#!/usr/bin/env python3
"""
Standalone audio transcription — local-first, API-fallback.

Priority:
  1. whisper.cpp (local) — if binary + model found
  2. OpenAI Whisper API — if OPENAI_API_KEY is set
  3. Skip gracefully — output empty

Usage:
  # Transcribe a video (auto-extracts audio)
  transcribe-audio.py video.mp4 --language zh --out transcript.txt

  # Transcribe an audio file directly
  transcribe-audio.py audio.wav --language en --out transcript.txt

Output: Plain text transcript written to --out (or stdout).
"""

import sys
import os
import json
import shutil
import tempfile
import subprocess
import argparse
from pathlib import Path
from typing import Optional


VERSION = "3.0.0"


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, "", "timeout")
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, -1, "", f"cmd not found: {cmd[0]}")


def has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def is_video(path: str) -> bool:
    """Heuristic: check extension for video formats."""
    ext = os.path.splitext(path)[1].lower()
    return ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg", ".wmv")


# ═══════════════════════════════════════════════════════════════════════
# Audio extraction
# ═══════════════════════════════════════════════════════════════════════

def extract_audio(video_path: str, output_path: str) -> bool:
    """Extract audio track as 16kHz mono WAV."""
    result = run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        output_path,
    ], timeout=120)
    return result.returncode == 0 and os.path.isfile(output_path)


# ═══════════════════════════════════════════════════════════════════════
# Provider 1: whisper.cpp (local)
# ═══════════════════════════════════════════════════════════════════════

def transcribe_whisper_cpp(audio_path: str, language: str = "") -> Optional[str]:
    """Transcribe using local whisper.cpp. Returns text or None."""
    binary = None
    for name in ["whisper-cpp", "whisper"]:
        if has_cmd(name):
            binary = name
            break
    if not binary:
        return None

    # Find model file
    model_dirs = [
        os.path.expanduser("~/.cache/whisper/"),
        os.path.expanduser("~/whisper.cpp/models/"),
        "/usr/local/share/whisper/",
    ]
    model_path = ""
    for d in model_dirs:
        for name in ["ggml-base.bin", "ggml-small.bin", "ggml-medium.bin", "ggml-tiny.bin"]:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                model_path = candidate
                break
        if model_path:
            break

    if not model_path:
        return None

    cmd = [binary, "-m", model_path, "-f", audio_path, "-otxt", "-of", audio_path]
    if language:
        cmd.extend(["-l", language])

    result = run(cmd, timeout=300)
    txt_out = audio_path + ".txt"
    if os.path.isfile(txt_out):
        try:
            with open(txt_out, encoding="utf-8") as f:
                text = f.read().strip()
            os.unlink(txt_out)
            return text if text else None
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════
# Provider 2: OpenAI Whisper API (fallback)
# ═══════════════════════════════════════════════════════════════════════

def transcribe_openai(audio_path: str, language: str = "") -> Optional[str]:
    """Transcribe using OpenAI Whisper API. Returns text or None."""
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
    add_field("response_format", "text")
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
            return resp.read().decode().strip()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=f"Local-first audio transcription v{VERSION}"
    )
    parser.add_argument("input", help="Video or audio file path")
    parser.add_argument("--language", default="", help="Language hint (e.g., zh, en, ja)")
    parser.add_argument("--out", default="", help="Output file (default: stdout)")

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Extract audio if input is video
    audio_path = args.input
    tmp_audio = None
    if is_video(args.input):
        tmp_audio = tempfile.mktemp(suffix="_audio.wav")
        if not extract_audio(args.input, tmp_audio):
            print("Error: Failed to extract audio from video.", file=sys.stderr)
            sys.exit(1)
        audio_path = tmp_audio

    try:
        # Priority 1: local whisper.cpp
        text = transcribe_whisper_cpp(audio_path, args.language)
        engine = "whisper.cpp"

        # Priority 2: OpenAI API fallback
        if text is None:
            text = transcribe_openai(audio_path, args.language)
            engine = "openai-whisper"

        # Priority 3: give up
        if text is None:
            text = ""
            engine = "none"

        # Write output
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            print(text)

        # Info to stderr
        if engine == "whisper.cpp":
            print(f"[transcribe] ✅ whisper.cpp (local)", file=sys.stderr)
        elif engine == "openai-whisper":
            print(f"[transcribe] ⚠️  OpenAI Whisper API (fallback)", file=sys.stderr)
        else:
            print(f"[transcribe] ⏭️  No transcription engine available", file=sys.stderr)

    finally:
        if tmp_audio:
            try:
                os.unlink(tmp_audio)
            except Exception:
                pass


if __name__ == "__main__":
    main()
