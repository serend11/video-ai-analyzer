#!/usr/bin/env python3
"""
Shared utilities for Video AI Analyzer scripts.
Eliminates code duplication between local-perceive.py and transcribe-audio.py.
"""

import os
import json
import shutil
import subprocess
from typing import Optional


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
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


def is_video(path: str) -> bool:
    """Check if file is a video by extension."""
    ext = os.path.splitext(path)[1].lower()
    return ext in (
        ".mp4", ".mov", ".avi", ".mkv", ".webm",
        ".flv", ".m4v", ".mpg", ".mpeg", ".wmv",
    )


def extract_audio(video_path: str, output_path: str) -> bool:
    """Extract audio track as 16kHz mono WAV."""
    result = run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        output_path,
    ], timeout=120)
    return result.returncode == 0 and os.path.isfile(output_path)


# ═══════════════════════════════════════════════════════════════════════
# Transcription (shared between local-perceive.py and transcribe-audio.py)
# ═══════════════════════════════════════════════════════════════════════

WHISPER_MODEL_DIRS = [
    os.path.expanduser("~/.cache/whisper/"),
    os.path.expanduser("~/whisper.cpp/models/"),
    "/usr/local/share/whisper/",
]

WHISPER_MODEL_NAMES = [
    "ggml-base.bin", "ggml-small.bin",
    "ggml-medium.bin", "ggml-tiny.bin",
]


def find_whisper_binary() -> Optional[str]:
    """Find whisper.cpp binary. Returns name or None."""
    for name in ["whisper-cpp", "whisper"]:
        if has_cmd(name):
            return name
    return None


def find_whisper_model() -> Optional[str]:
    """Find a whisper.cpp model file. Returns path or None."""
    for d in WHISPER_MODEL_DIRS:
        for name in WHISPER_MODEL_NAMES:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def transcribe_whisper_cpp(
    audio_path: str, language: str = "", output_format: str = "txt"
) -> Optional[str]:
    """
    Transcribe using local whisper.cpp.
    
    Args:
        audio_path: Path to WAV audio file.
        language: Language hint (e.g., 'zh', 'en').
        output_format: 'txt' for plain text, 'json' for structured JSON.
    
    Returns:
        Plain text string (txt mode) or JSON string (json mode), or None if failed.
    """
    binary = find_whisper_binary()
    if not binary:
        return None

    model_path = find_whisper_model()
    if not model_path:
        return None

    fmt_flag = "-otxt" if output_format == "txt" else "-oj"
    cmd = [binary, "-m", model_path, "-f", audio_path, fmt_flag, "-of", audio_path]
    if language:
        cmd.extend(["-l", language])

    result = run(cmd, timeout=300)

    if output_format == "json":
        json_out = audio_path + ".json"
        if os.path.isfile(json_out):
            try:
                with open(json_out, encoding="utf-8") as f:
                    data = json.load(f)
                os.unlink(json_out)
                return json.dumps(data, ensure_ascii=False)
            except Exception:
                pass
        return None

    # Plain text
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


def transcribe_openai(
    audio_path: str, language: str = "", output_format: str = "text"
) -> Optional[str]:
    """
    Transcribe using OpenAI Whisper API.
    
    Args:
        audio_path: Path to WAV audio file.
        language: Language hint.
        output_format: 'text' for plain text, 'verbose_json' for structured JSON.
    
    Returns:
        Response text or JSON string, or None if failed.
    """
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
    add_field("response_format", output_format)
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
            result = resp.read().decode()
            if output_format == "verbose_json":
                return result  # JSON string
            return result.strip()
    except Exception:
        return None
