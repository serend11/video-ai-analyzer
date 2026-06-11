#!/usr/bin/env python3
"""
Local video perception engine — "Whisper for video" (OPTIMIZED)

Performance improvements over original:
  - Parallel segment analysis using ThreadPoolExecutor
  - Cached metadata (eliminates redundant ffprobe calls)
  - Batch ffprobe commands where possible
  - Structured progress output

Converts video into structured, time-stamped scene descriptions using only
local tools. No AI vision API required.
"""

import sys
import os
import json
import re
import base64
import shutil
import struct
import tempfile
import subprocess
import argparse
from datetime import timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock

# Shared utilities
from common import run, run_bytes, has_cmd, extract_audio, transcribe_whisper_cpp, transcribe_openai


# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VideoMetadata:
    """Cached video metadata."""
    file: str
    path: str
    duration_sec: float
    duration_fmt: str
    size_mb: float
    video_codec: str
    resolution: str
    fps: float
    audio_codec: str
    audio_channels: int
    audio_sample_rate: int
    has_audio: bool

    @classmethod
    def from_dict(cls, data: dict) -> "VideoMetadata":
        video = data.get("video") or {}
        audio = data.get("audio") or {}
        return cls(
            file=data.get("file", ""),
            path=data.get("path", ""),
            duration_sec=data.get("duration_sec", 0),
            duration_fmt=data.get("duration_fmt", "00:00:00"),
            size_mb=data.get("size_mb", 0),
            video_codec=video.get("codec", "none"),
            resolution=video.get("resolution", "none"),
            fps=video.get("fps", 0),
            audio_codec=audio.get("codec", "none"),
            audio_channels=audio.get("channels", 0),
            audio_sample_rate=audio.get("sample_rate", 0),
            has_audio=audio.get("codec") != "none" if audio else False,
        )


@dataclass
class SegmentAnalysis:
    """Result of analyzing a single video segment."""
    index: int
    start: float
    end: float
    start_fmt: str
    end_fmt: str
    duration: float
    brightness: float
    dominant_colors: list
    motion: float
    faces_detected: int
    ocr: list
    description: str
    frame_base64: Optional[str] = None
    frame_mime: Optional[str] = None
    vision_description: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# Time Formatting
# ═══════════════════════════════════════════════════════════════════════════

def fmt_time(seconds: float) -> str:
    """seconds → HH:MM:SS.mmm"""
    td = timedelta(seconds=seconds)
    ts = int(td.total_seconds())
    h, r = divmod(ts, 3600)
    m, s = divmod(r, 60)
    ms = int((seconds - ts) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — Metadata (Cached, Single Call)
# ═══════════════════════════════════════════════════════════════════════════

def get_video_metadata(video_path: str) -> dict:
    """
    Extract full video metadata via ffprobe.
    This is called ONCE and cached for the entire pipeline.
    """
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
        "size_mb": round(int(fmt.get("size", 0)) / (1024 * 1024), 1),
        "video": {
            "codec": vs.get("codec_name", "none") if vs else "none",
            "resolution": f"{vs.get('width', '?')}x{vs.get('height', '?')}"
                          if vs else "none",
            "fps": fps,
        } if vs else None,
        "audio": {
            "codec": ast.get("codec_name", "none") if ast else "none",
            "channels": ast.get("channels", 0) if ast else 0,
            "sample_rate": int(ast.get("sample_rate", 0)) if ast else 0,
        } if ast else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — Scene Detection
# ═══════════════════════════════════════════════════════════════════════════

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
                if t - timestamps[-1] >= 0.5:  # Don't add scenes < 0.5s apart
                    timestamps.append(round(t, 2))

    # Add end marker if needed
    if timestamps[-1] < 36000:  # Only if < 10 hours (reasonable video)
        timestamps.append(timestamps[-1] + 1.0)  # Placeholder, will be fixed

    return timestamps


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — Per-Segment Analysis (Can Run in Parallel)
# ═══════════════════════════════════════════════════════════════════════════

def analyze_segment_sync(args: tuple) -> tuple[int, dict]:
    """
    Analyze a single video segment synchronously.
    This function is designed to be called from a thread pool.

    Returns: (segment_index, segment_data_dict)
    """
    (idx, start, end, video_path, tmpdir, enable_ocr, enable_face_detect,
     scene_threshold, max_segments) = args

    mid = (start + end) / 2
    frame_path = os.path.join(tmpdir, f"seg_{idx:04d}.jpg")

    # Extract representative frame
    result = run([
        "ffmpeg", "-y", "-ss", fmt_time(mid),
        "-i", video_path,
        "-frames:v", "1", "-q:v", "3",
        frame_path
    ], timeout=30)

    segment = {
        "index": idx,
        "start": round(start, 2),
        "end": round(end, 2),
        "start_fmt": fmt_time(start)[:8],
        "end_fmt": fmt_time(end)[:8],
        "duration": round(end - start, 2),
    }

    if result.returncode == 0 and os.path.isfile(frame_path):
        # Embed frame as base64
        try:
            with open(frame_path, "rb") as f:
                frame_bytes = f.read()
            if len(frame_bytes) < 5_000_000:  # Skip frames > 5MB
                segment["frame_base64"] = base64.b64encode(frame_bytes).decode("ascii")
                segment["frame_mime"] = "image/jpeg"
        except Exception:
            pass

        # Analyze visual characteristics
        visual = analyze_visual(frame_path, video_path, start, end)
        segment["scene"] = visual

        # OCR (optional)
        if enable_ocr and has_cmd("tesseract"):
            ocr_result = try_ocr(frame_path)
            if ocr_result:
                segment["ocr"] = ocr_result

        # Face detection (optional)
        if enable_face_detect:
            faces = try_face_detect(frame_path)
            segment["scene"]["faces_detected"] = faces
        else:
            segment["scene"]["faces_detected"] = 0
    else:
        segment["scene"] = {
            "brightness": 0.5, "dominant_colors": [],
            "motion": 0.0, "faces_detected": 0,
        }

    # Synthesized description
    segment["description"] = synthesize_description(segment, {})

    return idx, segment


def analyze_visual(frame_path: str, video_path: str,
                   start: float, end: float) -> dict:
    """Analyze colors, brightness, and motion for a segment."""

    result = {"brightness": 0.5, "dominant_colors": [], "motion": 0.0}

    # Color palette via small thumbnail (binary output)
    palette = run_bytes([
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

    # Brightness (average luminance of thumbnail)
    thumb = run_bytes([
        "ffmpeg", "-i", frame_path, "-vf", "scale=10:10",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], timeout=10)

    if thumb.returncode == 0 and len(thumb.stdout) >= 3:
        pixels = []
        raw = thumb.stdout
        for i in range(0, len(raw), 3):
            if i + 2 < len(raw):
                r, g, b = raw[i], raw[i + 1], raw[i + 2]
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                pixels.append(lum / 255.0)
        if pixels:
            result["brightness"] = round(sum(pixels) / len(pixels), 3)

    # Motion estimation
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


# ═══════════════════════════════════════════════════════════════════════════
# OCR (Optional)
# ═══════════════════════════════════════════════════════════════════════════

def try_ocr(frame_path: str) -> list:
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
            texts.append({"text": line, "confidence": 0})
    return texts[:20]


# ═══════════════════════════════════════════════════════════════════════════
# Face Detection (Optional)
# ═══════════════════════════════════════════════════════════════════════════

def try_face_detect(frame_path: str) -> int:
    """Count faces via ffmpeg facedetect filter. Returns 0 if unavailable."""
    result = run([
        "ffmpeg", "-i", frame_path,
        "-vf", "facedetect",
        "-f", "null", "-",
    ], timeout=15)

    faces = 0
    for line in (result.stderr or "").split("\n"):
        if "faces detected" in line.lower():
            m = re.search(r"(\d+)\s*faces?\s*detected", line, re.IGNORECASE)
            if m:
                faces = max(faces, int(m.group(1)))
    return faces


# ═══════════════════════════════════════════════════════════════════════════
# Description Synthesis
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# AI Vision Recognition (Optional Enhancement)
# ═══════════════════════════════════════════════════════════════════════════

def run_vision_recognition(segments: list[dict], args) -> None:
    """
    Enhance segments with AI vision descriptions.
    Runs in parallel for better performance.
    """
    if not getattr(args, "vision_in_local", False):
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    provider = getattr(args, "vision_provider", "openai")
    model = getattr(args, "vision_model", "")
    max_tokens = getattr(args, "vision_max_tokens", 300)

    # Import here to avoid circular dependency
    from call_ai import CallAI
    ai_client = CallAI(provider=provider, model=model)

    def analyze_segment(idx: int, seg: dict) -> tuple[int, Optional[str]]:
        frame_path = seg.get("_frame_path", "")
        if not frame_path or not os.path.isfile(frame_path):
            return idx, None

        result = ai_client.analyze_image(
            image_path=frame_path,
            prompt="Describe this video frame in detail.",
            max_tokens=max_tokens,
        )
        return idx, result.strip() if result else None

    # Run in parallel
    with ThreadPoolExecutor(max_workers=min(4, len(segments))) as pool:
        futures = {
            pool.submit(analyze_segment, i, seg): i
            for i, seg in enumerate(segments)
            if seg.get("_frame_path")
        }

        for future in as_completed(futures):
            idx, description = future.result()
            if idx < len(segments):
                segments[idx]["vision_description"] = description

    # Clean up internal field
    for seg in segments:
        seg.pop("_frame_path", None)


# ═══════════════════════════════════════════════════════════════════════════
# Main Pipeline (Parallel Processing)
# ═══════════════════════════════════════════════════════════════════════════

def analyze_local(
    video_path: str,
    scene_threshold: float = 0.3,
    max_segments: int = 50,
    enable_ocr: bool = True,
    enable_transcribe: bool = False,
    language: str = "",
    parallel_workers: int = 4,
    enable_vision: bool = False,
    vision_provider: str = "openai",
    vision_model: str = "",
    vision_max_tokens: int = 300,
    quiet: bool = False,
) -> dict:
    """
    Main local perception pipeline with PARALLEL segment processing.

    Performance: Uses ThreadPoolExecutor to analyze segments concurrently.
    Expected speedup: 2-4x on multi-core systems (depends on I/O).
    """

    # Check prerequisites
    tools = {
        "ffmpeg": has_cmd("ffmpeg"),
        "ffprobe": has_cmd("ffprobe"),
        "tesseract": has_cmd("tesseract"),
        "whisper_cpp": has_cmd("whisper-cpp") or has_cmd("whisper"),
    }
    if not tools["ffmpeg"] or not tools["ffprobe"]:
        print("Error: ffmpeg and ffprobe are required.", file=sys.stderr)
        sys.exit(1)

    # Get metadata ONCE (cached for entire pipeline)
    meta = get_video_metadata(video_path)
    duration = meta.get("duration_sec", 0)
    has_audio = meta.get("audio") is not None

    if duration <= 0:
        print("Error: Could not determine video duration.", file=sys.stderr)
        sys.exit(1)

    # Detect scenes
    scene_times = detect_scenes(video_path, scene_threshold, max_segments)

    # Ensure last timestamp is actual duration
    if scene_times[-1] < duration - 0.1:
        scene_times[-1] = duration

    # Limit to max segments
    if len(scene_times) > max_segments + 1:
        step = len(scene_times) // max_segments
        sampled = [scene_times[0]]
        for i in range(step, len(scene_times) - 1, step):
            sampled.append(scene_times[i])
        if sampled[-1] < duration:
            sampled.append(duration)
        scene_times = sampled

    # Create temp directory for frames
    tmpdir = tempfile.mkdtemp(prefix="video-perceive-")

    try:
        total_segments = len(scene_times) - 1
        segments = [None] * total_segments  # Pre-allocate, fill by index

        # Prepare analysis tasks
        tasks = [
            (
                i,
                scene_times[i],
                scene_times[i + 1],
                video_path,
                tmpdir,
                enable_ocr,
                True,  # enable_face_detect
                scene_threshold,
                max_segments,
            )
            for i in range(total_segments)
        ]

        # PARALLEL PROCESSING: Analyze segments concurrently
        if not quiet:
            print(f"   🔍 Processing {total_segments} segments with {parallel_workers} workers...",
                  file=sys.stderr, end="", flush=True)

        completed = 0
        with ThreadPoolExecutor(max_workers=parallel_workers) as pool:
            futures = {
                pool.submit(analyze_segment_sync, task): task[0]
                for task in tasks
            }

            for future in as_completed(futures):
                idx, segment = future.result()
                segments[idx] = segment
                completed += 1
                if not quiet:
                    print(f"\r   🔍 {completed}/{total_segments} segments analyzed...",
                          end="", flush=True, file=sys.stderr)

        if not quiet:
            print()  # New line after progress

        # Handle any None entries (shouldn't happen, but safety)
        segments = [s if s is not None else {
            "index": i, "start": 0, "end": 0, "scene": {}
        } for i, s in enumerate(segments)]

        # Clean internal frame path references
        for seg in segments:
            seg.pop("_frame_path", None)

        # Transcription (optional, runs after parallel segments)
        transcript = None
        if enable_transcribe and has_audio:
            # Try local whisper.cpp first, then OpenAI API
            tmp_audio = tempfile.mktemp(suffix="_audio.wav")
            try:
                if extract_audio(video_path, tmp_audio):
                    # Try whisper.cpp
                    text = transcribe_whisper_cpp(tmp_audio, language, output_format="json")
                    engine = "whisper.cpp"

                    # Fallback to OpenAI
                    if not text:
                        text = transcribe_openai(tmp_audio, language, output_format="verbose_json")
                        engine = "openai-whisper"

                    if text:
                        try:
                            data = json.loads(text) if isinstance(text, str) else text
                            transcript = {
                                "engine": engine,
                                "segments": data.get("segments", []),
                                "text": data.get("text", ""),
                            }
                        except json.JSONDecodeError:
                            transcript = {"engine": engine, "text": str(text)}
            finally:
                try:
                    os.unlink(tmp_audio)
                except Exception:
                    pass

        # Build output
        output = {
            "engine": "video-ai-analyzer-local",
            "version": "3.2.0",
            "video": meta,
            "tools_available": tools,
            "segment_count": len(segments),
            "segments": segments,
        }
        if transcript:
            output["transcript"] = transcript

        return output

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# CLI Entry Point (for backwards compatibility)
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Local video perception engine — 'Whisper for video'"
    )
    parser.add_argument("video", help="Video file path")
    parser.add_argument("--out", default="",
                        help="Output file (default: stdout)")
    parser.add_argument("--scene-threshold", type=float, default=0.3)
    parser.add_argument("--max-segments", type=int, default=50)
    parser.add_argument("--ocr", action="store_true", default=True)
    parser.add_argument("--no-ocr", action="store_true", default=False)
    parser.add_argument("--transcribe", action="store_true", default=False)
    parser.add_argument("--language", default="")
    parser.add_argument("--vision", action="store_true", default=False)
    parser.add_argument("--vision-provider", default="openai")
    parser.add_argument("--vision-model", default="")
    parser.add_argument("--vision-max-tokens", type=int, default=300)
    parser.add_argument("--parallel", type=int, default=4,
                        help="Max parallel workers")
    parser.add_argument("--quiet", action="store_true", default=False)

    args = parser.parse_args()

    if not os.path.isfile(args.video):
        print(f"Error: File not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    result = analyze_local(
        video_path=args.video,
        scene_threshold=args.scene_threshold,
        max_segments=args.max_segments,
        enable_ocr=not args.no_ocr,
        enable_transcribe=args.transcribe,
        language=args.language,
        parallel_workers=args.parallel,
        enable_vision=args.vision,
        vision_provider=args.vision_provider,
        vision_model=args.vision_model,
        vision_max_tokens=args.vision_max_tokens,
        quiet=args.quiet,
    )

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
