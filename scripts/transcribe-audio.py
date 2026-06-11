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
import tempfile
import argparse
from typing import Optional

# Shared utilities (eliminates duplication with local-perceive.py)
from common import run, has_cmd, is_video, extract_audio, transcribe_whisper_cpp, transcribe_openai


VERSION = "3.2.0"


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
