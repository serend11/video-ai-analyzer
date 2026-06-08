#!/usr/bin/env python3
"""
Local video perception engine — "Whisper for video".

Converts video into structured, time-stamped scene descriptions using only
local tools. No AI vision API required. Output is a JSON array of segments
(like Whisper's transcription output) that any AI agent can consume directly.

Capabilities (all optional — skip gracefully if tool unavailable):
  Core (ffmpeg + python3 stdlib only):
    - Scene change detection
    - Per-segment color palette / brightness / contrast
    - Motion level estimation
    - Synthesized natural-language descriptions

  Optional (auto-enabled if CLI tool found):
    - OCR text extraction (tesseract)
    - Face count detection (ffmpeg facedetect filter)
    - Audio transcription (whisper.cpp → OpenAI API fallback)

Usage:
  local-perceive.py video.mp4 > perception.json
  local-perceive.py video.mp4 --out perception.json --transcribe --ocr

Output format (Whisper-like segments):
{
  "segments": [
    {
      "index": 0,
      "start": 0.0,    "end": 12.5,
      "scene": {"brightness": 0.72, "motion": 0.03, "dominant_colors": [...]},
      "ocr": [{"text": "Welcome", "confidence": 92}],
      "description": "1 person visible; Bright scene, mostly static. Text: Welcome"
    }
  ]
}
"""

import sys
import os
import json
import re
import shutil
import struct
import tempfile
import subprocess
import argparse
from pathlib import Path
from datetime import timedelta
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def run(cmd: list[str], timeout: int = 120, check: bool = False
        ) -> subprocess.CompletedProcess:
    """Run command, return CompletedProcess (never raises)."""
    try:
        return subprocess.run(
            cmd, capture_output=True, timeout=timeout, text=True
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, "", "timeout")
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            cmd, -1, "", f"cmd not found: {cmd[0]}"
        )


def has_cmd(name: str) -> bool:
    """Check if a CLI tool is available."""
    return shutil.which(name) is not None


def fmt_time(seconds: float) -> str:
    """seconds → HH:MM:SS.mmm"""
    td = timedelta(seconds=seconds)
    ts = int(td.total_seconds())
    h, r = divmod(ts, 3600)
    m, s = divmod(r, 60)
    ms = int((seconds - ts) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def safe_div(a, b, default=0.0):
    return a / b if b else default


# ═══════════════════════════════════════════════════════════════════════
# Step 1 — Metadata
# ═══════════════════════════════════════════════════════════════════════

def get_metadata(video_path: str) -> dict:
    """Extract full video metadata via ffprobe."""
    result = run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", video_path
    ])
    if result.returncode != 0:
        return {"error": result.stderr.strip(), "file": os.path.basename(video_path)}

    data = json.loads(result.stdout)
    vs = None
    ast = None
    for s in data.get("streams", []):
        if s["codec_type"] == "video" and vs is None:
            vs = s
        elif s["codec_type"] == "audio" and ast is None:
            ast = s

    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0))
    fps_str = vs.get("r_frame_rate", "0/1") if vs else "0/1"
    try:
        num, den = fps_str.split("/")
        fps = round(float(num) / float(den), 2)
    except Exception:
        fps = 0.0

    return {
        "file": os.path.basename(video_path),
        "path": os.path.abspath(video_path),
        "duration_sec": round(duration, 2),
        "duration_fmt": fmt_time(duration)[:8],
        "size_mb": round(int(fmt.get("size", 0)) / (1024*1024), 1),
        "video": {
            "codec": vs.get("codec_name", "none") if vs else "none",
            "resolution": f"{vs.get('width','?')}x{vs.get('height','?')}"
                          if vs else "none",
            "fps": fps,
        } if vs else None,
        "audio": {
            "codec": ast.get("codec_name", "none") if ast else "none",
            "channels": ast.get("channels", 0) if ast else 0,
            "sample_rate": int(ast.get("sample_rate", 0)) if ast else 0,
        } if ast else None,
    }


# ═══════════════════════════════════════════════════════════════════════
# Step 2 — Scene Detection
# ═══════════════════════════════════════════════════════════════════════

def detect_scenes(video_path: str, threshold: float = 0.3,
                  max_segments: int = 50) -> list[float]:
    """Detect scene-change timestamps via ffmpeg scene filter."""

    if max_segments < 1:
        max_segments = 50

    result = run([
        "ffmpeg", "-i", video_path,
        "-vf", f"select='gt(scene\\,{threshold})',showinfo",
        "-vsync", "vfr", "-f", "null", "-",
    ], timeout=180)

    timestamps = [0.0]

    if result.returncode == 0 and result.stderr:
        for line in result.stderr.split("\n"):
            m = re.search(r"pts_time:([\d]+(?:\.[\d]+)?)", line)
            if m:
                t = float(m.group(1))
                # Don't add scenes that are too close together (< 0.5s)
                if t - timestamps[-1] >= 0.5:
                    timestamps.append(round(t, 2))

    # Limit segments — subsample if too many
    meta = get_metadata(video_path)
    duration = meta.get("duration_sec", 60)
    if duration > 0 and timestamps[-1] < duration - 1:
        timestamps.append(round(duration, 2))

    if len(timestamps) > max_segments + 1:
        step = len(timestamps) // max_segments
        sampled = [timestamps[0]]
        for i in range(step, len(timestamps) - 1, step):
            sampled.append(timestamps[i])
        if sampled[-1] < duration:
            sampled.append(round(duration, 2))
        timestamps = sampled

    return timestamps


# ═══════════════════════════════════════════════════════════════════════
# Step 3 — Frame Extraction
# ═══════════════════════════════════════════════════════════════════════

def extract_frame(video_path: str, timestamp: float,
                  output_path: str) -> bool:
    """Extract one frame at given timestamp."""
    # For very short timestamps at end, pull back slightly
    ts = max(0, min(timestamp, 86400))
    result = run([
        "ffmpeg", "-y", "-ss", fmt_time(ts),
        "-i", video_path,
        "-frames:v", "1", "-q:v", "3",
        output_path,
    ], timeout=30)
    return result.returncode == 0 and os.path.isfile(output_path)


# ═══════════════════════════════════════════════════════════════════════
# Step 4 — Color / Brightness / Motion
# ═══════════════════════════════════════════════════════════════════════

def analyze_visual(frame_path: str, video_path: str,
                   start: float, end: float) -> dict:
    """Analyze colors, brightness, and motion for a segment."""
    result = {"brightness": 0.5, "dominant_colors": [], "motion": 0.0}

    # ── Color palette via small thumbnail ──
    palette = run([
        "ffmpeg", "-i", frame_path, "-vf",
        "palettegen=stats_mode=diff:max_colors=5:reserve_transparent=0",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-frames:v", "1", "-",
    ], timeout=10)

    colors = []
    if palette.returncode == 0 and palette.stdout:
        raw = palette.stdout
        for i in range(0, min(len(raw) - 2, 15), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            colors.append(f"#{r:02x}{g:02x}{b:02x}")
    result["dominant_colors"] = colors[:5] if colors else ["#808080"]

    # ── Brightness (average luminance of thumbnail) ──
    thumb = run([
        "ffmpeg", "-i", frame_path, "-vf", "scale=10:10",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], timeout=10)

    if thumb.returncode == 0 and len(thumb.stdout) >= 3:
        pixels = []
        raw = thumb.stdout
        for i in range(0, len(raw), 3):
            if i + 2 < len(raw):
                r, g, b = raw[i], raw[i + 1], raw[i + 2]
                # perceptual luminance
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                pixels.append(lum / 255.0)
        if pixels:
            result["brightness"] = round(sum(pixels) / len(pixels), 3)

    # ── Motion estimation (frame-difference via ffmpeg scene score) ──
    duration = max(end - start, 0.5)
    motion = run([
        "ffmpeg", "-ss", fmt_time(start), "-t", str(min(duration, 30)),
        "-i", video_path,
        "-vf", "select='gt(scene\\,0.1)',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ], timeout=30)

    motion_val = 0.0
    if motion.returncode == 0 and motion.stderr:
        scores = re.findall(r"lavfi\.scene_score=([\d.]+)", motion.stderr)
        if scores:
            motion_val = round(sum(float(s) for s in scores) / len(scores), 3)
    result["motion"] = min(motion_val, 1.0)

    return result


# ═══════════════════════════════════════════════════════════════════════
# Optional — OCR
# ═══════════════════════════════════════════════════════════════════════

def try_ocr(frame_path: str) -> list[dict]:
    """Extract text via tesseract. Returns [] if unavailable."""
    if not has_cmd("tesseract"):
        return []

    result = run([
        "tesseract", frame_path, "stdout",
        "-l", "eng+chi_sim", "--psm", "6", "--oem", "1",
    ], timeout=30)

    if result.returncode != 0 or not result.stdout:
        return []

    texts = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if len(line) >= 2:
            # Try to parse confidence from tesseract TSV-style output
            texts.append({"text": line, "confidence": 0})
    return texts[:20]  # limit


# ═══════════════════════════════════════════════════════════════════════
# Optional — Face Detection
# ═══════════════════════════════════════════════════════════════════════

def try_face_detect(frame_path: str) -> int:
    """Count faces via ffmpeg facedetect filter. Returns 0 if unavailable."""
    result = run([
        "ffmpeg", "-i", frame_path,
        "-vf", "facedetect",
        "-f", "null", "-",
    ], timeout=15)

    faces = 0
    for line in (result.stderr or "").split("\n"):
        # ffmpeg facedetect prints coordinates
        if "faces detected" in line.lower():
            m = re.search(r"(\d+)\s*faces?\s*detected", line, re.IGNORECASE)
            if m:
                faces = max(faces, int(m.group(1)))
    return faces


# ═══════════════════════════════════════════════════════════════════════
# Optional — Audio Transcription
# ═══════════════════════════════════════════════════════════════════════

def _extract_audio(video_path: str, output_path: str) -> bool:
    """Extract audio track as 16kHz mono WAV."""
    result = run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        output_path,
    ], timeout=120)
    return result.returncode == 0 and os.path.isfile(output_path)


def _transcribe_whisper_cpp(audio_path: str, language: str = ""
                             ) -> Optional[dict]:
    """Transcribe using local whisper.cpp."""
    if not has_cmd("whisper-cpp") and not has_cmd("whisper"):
        return None

    binary = has_cmd("whisper-cpp") and "whisper-cpp" or "whisper"
    # Look for model in common locations
    model_dirs = [
        os.path.expanduser("~/.cache/whisper/"),
        os.path.expanduser("~/whisper.cpp/models/"),
        "/usr/local/share/whisper/",
    ]
    model_path = ""
    for d in model_dirs:
        for name in ["ggml-base.bin", "ggml-small.bin", "ggml-tiny.bin"]:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                model_path = candidate
                break
        if model_path:
            break

    if not model_path:
        return None

    cmd = [binary, "-m", model_path, "-f", audio_path, "-oj", "-of", audio_path]
    if language:
        cmd.extend(["-l", language])
    result = run(cmd, timeout=300)

    json_out = audio_path + ".json"
    if os.path.isfile(json_out):
        try:
            with open(json_out, encoding="utf-8") as f:
                data = json.load(f)
            os.unlink(json_out)
            return {"engine": "whisper.cpp", "segments": data.get("transcription", data)}
        except Exception:
            pass
    return None


def _transcribe_openai(audio_path: str, language: str = "") -> Optional[dict]:
    """Transcribe using OpenAI Whisper API."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    import urllib.request
    import urllib.error

    boundary = "----WhisperBoundary2026"
    body = bytearray()

    def add_field(name: str, value: str):
        body.extend(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )

    add_field("model", "whisper-1")
    add_field("response_format", "verbose_json")
    if language:
        add_field("language", language)

    body.extend(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode()
    )
    with open(audio_path, "rb") as f:
        body.extend(f.read())
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return {
                "engine": "openai-whisper",
                "segments": data.get("segments", []),
                "text": data.get("text", ""),
            }
    except Exception:
        return None


def try_transcribe(video_path: str, language: str = ""
                   ) -> Optional[dict]:
    """Transcribe video audio. Tries whisper.cpp → OpenAI → fail gracefully."""
    tmp = tempfile.mktemp(suffix="_audio.wav")
    try:
        if not _extract_audio(video_path, tmp):
            return None

        # Try local first
        result = _transcribe_whisper_cpp(tmp, language)
        if result:
            return result

        # Fallback to OpenAI
        result = _transcribe_openai(tmp, language)
        if result:
            return result

        return None
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# Description Synthesis
# ═══════════════════════════════════════════════════════════════════════

def synthesize_description(segment: dict, tools_available: dict) -> str:
    """Build a natural-language description from structured perceptual data."""
    parts = []
    scene = segment.get("scene", {})

    # Faces
    faces = scene.get("faces_detected", 0)
    if faces > 0:
        parts.append(f"{faces} person face detected" if faces == 1
                     else f"{faces} faces detected")

    # Brightness
    b = scene.get("brightness", 0.5)
    if b > 0.75:
        parts.append("bright scene")
    elif b > 0.5:
        parts.append("moderately lit scene")
    elif b > 0.25:
        parts.append("dim scene")
    else:
        parts.append("very dark scene")

    # Colors
    colors = scene.get("dominant_colors", [])
    if colors and colors[0] != "#808080":
        warm = sum(
            int(c[1:3], 16) > int(c[5:7], 16) and int(c[3:5], 16) > int(c[5:7], 16)
            for c in colors[:3]
        )
        if warm >= 2:
            parts.append("warm tones dominate")
        elif warm <= 0:
            parts.append("cool tones dominate")

    # Motion
    motion = scene.get("motion", 0)
    if motion > 0.3:
        parts.append("significant motion")
    elif motion > 0.1:
        parts.append("subtle movement")
    elif motion > 0.02:
        parts.append("mostly static")
    else:
        parts.append("completely still")

    # OCR
    ocr_texts = segment.get("ocr", [])
    if ocr_texts:
        preview = " | ".join(t["text"] for t in ocr_texts[:5])
        if len(preview) > 120:
            preview = preview[:117] + "..."
        parts.append(f'text visible: "{preview}"')

    return ". ".join(parts) + "."


# ═══════════════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Local video perception engine — 'Whisper for video'"
    )
    parser.add_argument("video", help="Video file path")
    parser.add_argument("--out", default="",
                        help="Output file (default: stdout)")
    parser.add_argument("--scene-threshold", type=float, default=0.3,
                        help="Scene detection sensitivity 0-1 (default: 0.3)")
    parser.add_argument("--max-segments", type=int, default=50,
                        help="Max segments (default: 50)")
    parser.add_argument("--ocr", action="store_true", default=True,
                        help="Enable OCR (needs tesseract)")
    parser.add_argument("--no-ocr", action="store_false", dest="ocr",
                        help="Disable OCR")
    parser.add_argument("--face-detect", action="store_true", default=True,
                        help="Enable face detection")
    parser.add_argument("--no-face-detect", action="store_false",
                        dest="face_detect")
    parser.add_argument("--transcribe", action="store_true", default=False,
                        help="Enable audio transcription")
    parser.add_argument("--language", default="",
                        help="Language hint for transcription (e.g. zh, en)")

    args = parser.parse_args()

    if not os.path.isfile(args.video):
        print(f"Error: File not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    # Check available tools
    tools = {
        "ffmpeg": has_cmd("ffmpeg"),
        "ffprobe": has_cmd("ffprobe"),
        "tesseract": has_cmd("tesseract"),
        "whisper_cpp": has_cmd("whisper-cpp") or has_cmd("whisper"),
    }
    if not tools["ffmpeg"] or not tools["ffprobe"]:
        print("Error: ffmpeg and ffprobe are required.", file=sys.stderr)
        sys.exit(1)

    # ── 1. Metadata ──
    meta = get_metadata(args.video)
    duration = meta.get("duration_sec", 0)
    has_audio = meta.get("audio") is not None

    if duration <= 0:
        print("Error: Could not determine video duration.", file=sys.stderr)
        sys.exit(1)

    # ── 2. Scene detection ──
    scene_times = detect_scenes(args.video, args.scene_threshold,
                                args.max_segments)

    # ── 3. Process each segment ──
    segments = []
    tmpdir = tempfile.mkdtemp(prefix="video-perceive-")

    try:
        total = len(scene_times) - 1
        for i in range(total):
            start = scene_times[i]
            end = scene_times[i + 1]
            mid = (start + end) / 2

            seg = {
                "index": i,
                "start": round(start, 2),
                "end": round(end, 2),
                "start_fmt": fmt_time(start)[:8],
                "end_fmt": fmt_time(end)[:8],
                "duration": round(end - start, 2),
            }

            # Extract representative frame
            frame_path = os.path.join(tmpdir, f"seg_{i:04d}.jpg")
            if extract_frame(args.video, mid, frame_path):
                # Core visual analysis (always runs)
                seg["scene"] = analyze_visual(frame_path, args.video, start, end)

                # OCR (optional)
                if args.ocr and tools["tesseract"]:
                    ocr_result = try_ocr(frame_path)
                    if ocr_result:
                        seg["ocr"] = ocr_result

                # Face detection (optional)
                if args.face_detect:
                    faces = try_face_detect(frame_path)
                    # Always include the field for consistency
                    seg["scene"]["faces_detected"] = faces
                else:
                    seg["scene"]["faces_detected"] = 0
            else:
                seg["scene"] = {
                    "brightness": 0.5, "dominant_colors": [],
                    "motion": 0.0, "faces_detected": 0,
                }

            # Synthesized description
            seg["description"] = synthesize_description(seg, tools)
            segments.append(seg)

        # ── 4. Transcription (optional) ──
        transcript = None
        if args.transcribe and has_audio:
            t = try_transcribe(args.video, args.language)
            if t:
                transcript = t

        # ── 5. Build output ──
        output = {
            "engine": "video-ai-analyzer-local",
            "version": "3.1.0",
            "video": meta,
            "tools_available": tools,
            "segment_count": len(segments),
            "segments": segments,
        }
        if transcript:
            output["transcript"] = transcript

        # ── 6. Write ──
        json_text = json.dumps(output, indent=2, ensure_ascii=False)
        if args.out:
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(json_text)
        else:
            print(json_text)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
