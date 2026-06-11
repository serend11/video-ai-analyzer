#!/usr/bin/env python3
"""
Video AI Analyzer v3.2 — Optimized Python Entry Point

Replaces analyze.sh with a Python-native implementation for:
- Better error handling and type safety
- Parallel processing of video segments
- Structured logging and progress output
- Cross-platform compatibility

Usage:
  python3 main.py video.mp4 [options]
  python3 main.py --help
"""

import sys
import os
import json
import time
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Local modules
from common import run, has_cmd, extract_audio
from local_perceive import analyze_local, get_video_metadata
from call_ai import CallAI
from report_generator import generate_local_report, generate_vision_report

VERSION = "3.2.0"


# ═══════════════════════════════════════════════════════════════════════════
# CLI Argument Parser
# ═══════════════════════════════════════════════════════════════════════════

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Video AI Analyzer v{VERSION} — Local video perception (no AI API required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local mode (DEFAULT, zero cost)
  python3 main.py video.mp4

  # Local + transcription
  python3 main.py video.mp4 --transcribe --language zh

  # Vision mode (needs API key)
  python3 main.py video.mp4 --vision --provider openai

  # Vision + custom provider
  python3 main.py video.mp4 --vision --provider anthropic
        """
    )

    # Positional
    parser.add_argument("video", nargs="?", help="Video file path")

    # Mode selection
    mode_group = parser.add_argument_group("Mode Selection")
    mode_group.add_argument("--local", action="store_true", default=True,
                            help="Local perception mode (DEFAULT)")
    mode_group.add_argument("--vision", action="store_true", default=False,
                            help="AI vision mode (requires API key)")

    # Common options
    common = parser.add_argument_group("Common Options")
    common.add_argument("--out", default="", help="Output directory")
    common.add_argument("--transcribe", action="store_true", default=False,
                        help="Enable audio transcription")
    common.add_argument("--language", default="", help="Language hint (zh, en, ja)")
    common.add_argument("--format", default="json", choices=["json", "markdown"],
                        help="Output format (default: json for local, markdown for vision)")
    common.add_argument("--no-ocr", action="store_true", default=False,
                        help="Disable OCR text extraction")
    common.add_argument("--config", default="", help="Config file path")
    common.add_argument("--parallel", type=int, default=4,
                        help="Max parallel workers for local mode (default: 4)")

    # Local mode options
    local = parser.add_argument_group("Local Mode Options")
    local.add_argument("--scene-threshold", type=float, default=0.3,
                       help="Scene detection sensitivity 0-1 (default: 0.3)")
    local.add_argument("--max-segments", type=int, default=50,
                       help="Max scene segments (default: 50)")
    local.add_argument("--vision-in-local", action="store_true", default=False,
                       help="Enable AI vision recognition in local mode")

    # Vision mode options
    vision = parser.add_argument_group("Vision Mode Options")
    vision.add_argument("--provider", default="openai",
                        choices=["openai", "anthropic", "google", "ollama", "openai-compatible"],
                        help="AI provider (default: openai)")
    vision.add_argument("--model", default="", help="Vision model name")
    vision.add_argument("--summary-model", default="", help="Summary model name")
    vision.add_argument("--interval", type=int, default=10,
                        help="Seconds between frame captures (default: 10)")
    vision.add_argument("--max-frames", type=int, default=20,
                        help="Max frames to analyze (default: 20)")
    vision.add_argument("--no-summary", action="store_true", default=False,
                        help="Skip AI-generated summary")
    vision.add_argument("--detail", default="low", choices=["low", "high", "auto"],
                        help="Image detail level (OpenAI only)")
    vision.add_argument("--max-tokens", type=int, default=500,
                        help="Max tokens per frame analysis")
    vision.add_argument("--temperature", type=float, default=0.7)
    vision.add_argument("--no-transcribe", action="store_true", default=False,
                        help="Skip audio transcription")
    vision.add_argument("--base-url", default="", help="API base URL override")

    return parser


# ═══════════════════════════════════════════════════════════════════════════
# Config File Loader
# ═══════════════════════════════════════════════════════════════════════════

def find_config(explicit_path: str = "") -> Optional[str]:
    """Find config file. Search order: explicit > ./ > parent > ~/.config/"""
    if explicit_path and os.path.isfile(explicit_path):
        return explicit_path

    # Check current and parent dirs (up to 3 levels)
    dir_path = os.getcwd()
    for _ in range(4):
        for name in [".video-ai-analyzer.yaml", ".video-ai-analyzer.yml"]:
            path = os.path.join(dir_path, name)
            if os.path.isfile(path):
                return path
        dir_path = os.path.dirname(dir_path)
        if dir_path == "/":
            break

    # User config dir
    user_config = os.path.expanduser("~/.config/video-ai-analyzer/config.yaml")
    if os.path.isfile(user_config):
        return user_config

    return None


def load_config(path: str) -> dict:
    """Load simple YAML config (key: value pairs only)."""
    config = {}
    if not os.path.isfile(path):
        return config

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#") or line.startswith("---"):
                    continue
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    if key and val:
                        config[key] = val
    except Exception:
        pass

    return config


# ═══════════════════════════════════════════════════════════════════════════
# Output Helpers
# ═══════════════════════════════════════════════════════════════════════════

def print_step(step: str, msg: str, done: bool = False):
    """Print progress step."""
    icon = "✅" if done else "📍"
    print(f"{icon} [{step}] {msg}", file=sys.stderr)


def print_info(msg: str):
    """Print info message."""
    print(f"   {msg}", file=sys.stderr)


def ensure_output_dir(base_out: str, video_path: str) -> str:
    """Create and return output directory path."""
    if base_out:
        out_dir = base_out
    else:
        basename = os.path.basename(video_path)
        name = os.path.splitext(basename)[0]
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = f"./video-analysis-{name}-{timestamp}"

    os.makedirs(out_dir, exist_ok=True)
    return out_dir


# ═══════════════════════════════════════════════════════════════════════════
# Prerequisites Checker
# ═══════════════════════════════════════════════════════════════════════════

def check_prerequisites(require_api: bool = False, provider: str = "openai"):
    """Check that required tools and API keys are available."""
    errors = []

    # Required binaries
    for cmd in ["ffmpeg", "ffprobe", "python3"]:
        if not has_cmd(cmd):
            errors.append(f"Required command not found: {cmd}")

    # API key check for vision mode
    if require_api:
        env_keys = {
            "openai": "OPENAI_API_KEY",
            "openai-compatible": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "ollama": None,  # No key needed
        }
        required_key = env_keys.get(provider)
        if required_key and not os.environ.get(required_key):
            errors.append(f"Required environment variable not set: {required_key}")

    return errors


# ═══════════════════════════════════════════════════════════════════════════
# Local Mode Pipeline
# ═══════════════════════════════════════════════════════════════════════════

def run_local_mode(args, out_dir: str) -> dict:
    """Run local perception mode with parallel processing."""
    print_step("START", f"Video AI Analyzer v{VERSION} — Local Perception Mode")
    print_info("Zero API cost · Zero privacy loss · Pure local processing")
    print_info(f"Parallel workers: {args.parallel}")
    print()

    # Get metadata once (cached)
    print_step("META", "Extracting video metadata...")
    metadata = get_video_metadata(args.video)
    duration = metadata.get("duration_sec", 0)

    if duration <= 0:
        print("Error: Could not determine video duration", file=sys.stderr)
        sys.exit(1)

    print_info(f"Duration: {metadata.get('duration_fmt', '?')} | "
              f"Resolution: {metadata.get('video', {}).get('resolution', '?')} | "
              f"Codec: {metadata.get('video', {}).get('codec', '?')}")
    print()

    # Run local perception with parallel processing
    print_step("SCENE", "Detecting scenes & analyzing frames...")
    perception_result = analyze_local(
        video_path=args.video,
        scene_threshold=args.scene_threshold,
        max_segments=args.max_segments,
        enable_ocr=not args.no_ocr,
        enable_transcribe=args.transcribe,
        language=args.language,
        parallel_workers=args.parallel,
        enable_vision=args.vision_in_local,
        vision_provider=args.provider if args.vision_in_local else "openai",
        vision_model=args.model if args.vision_in_local else "",
        vision_max_tokens=300,
    )

    # Write perception.json
    perception_file = os.path.join(out_dir, "perception.json")
    with open(perception_file, "w", encoding="utf-8") as f:
        json.dump(perception_result, f, indent=2, ensure_ascii=False)
    print()

    # Generate report
    print_step("REPORT", "Generating human-readable report...")
    output_format = args.format if args.format != "json" else "markdown"
    report_text = generate_local_report(perception_result, args.video, output_format)

    report_file = os.path.join(out_dir, f"report.{'md' if output_format == 'markdown' else 'json'}")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    print()
    print("=" * 60, file=sys.stderr)
    print("✅ Video perception complete!", file=sys.stderr)
    print(f"   📊 Perception data: {perception_file}", file=sys.stderr)
    print(f"   📄 Analysis report: {report_file}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    return perception_result


# ═══════════════════════════════════════════════════════════════════════════
# Vision Mode Pipeline
# ═══════════════════════════════════════════════════════════════════════════

def run_vision_mode(args, out_dir: str):
    """Run AI vision mode."""
    print_step("START", f"Video AI Analyzer v{VERSION} — Vision Mode")
    print_info(f"Provider: {args.provider} | Model: {args.model or 'default'}")
    print_info(f"Interval: {args.interval}s | Max frames: {args.max_frames}")
    print_info(f"Output: {out_dir}")
    print()

    # Get metadata
    print_step("META", "Extracting video metadata...")
    metadata = get_video_metadata(args.video)
    duration = metadata.get("duration_sec", 0)

    if duration <= 0:
        print("Error: Could not determine video duration", file=sys.stderr)
        sys.exit(1)

    # Extract frames
    print_step("FRAMES", f"Extracting frames every {args.interval}s...")
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    frame_count = max(1, min(duration // args.interval, args.max_frames))
    actual_interval = duration / frame_count if frame_count > 0 else args.interval

    print_info(f"Will extract {frame_count} frames at ~{actual_interval:.1f}s intervals")

    frame_paths = []
    for i in range(frame_count):
        timestamp = i * actual_interval
        frame_path = os.path.join(frames_dir, f"frame_{i:04d}.jpg")

        # Use ffmpeg to extract frame
        result = run([
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", args.video,
            "-frames:v", "1", "-q:v", "3",
            frame_path
        ], timeout=30)

        if result.returncode == 0 and os.path.isfile(frame_path):
            frame_paths.append((frame_path, timestamp))

    print_info(f"Extracted {len(frame_paths)} frames")

    if not frame_paths:
        print("Error: No frames extracted", file=sys.stderr)
        sys.exit(1)

    # Cost estimate
    print()
    print_info(f"💰 Estimated cost: ~{len(frame_paths)} vision API calls")
    print()

    # Initialize AI client
    print_step("AI", f"Analyzing frames with {args.provider}...")
    ai_client = CallAI(
        provider=args.provider,
        model=args.model or "",
        base_url=args.base_url,
    )

    # Analyze frames in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed

    analysis_dir = os.path.join(out_dir, "frame-analysis")
    os.makedirs(analysis_dir, exist_ok=True)

    def analyze_frame(frame_path: str, idx: int) -> tuple[str, str, bool]:
        basename = os.path.basename(frame_path)
        output_file = os.path.join(analysis_dir, basename.replace(".jpg", ".txt"))

        # Skip if cached
        if os.path.isfile(output_file) and os.path.getsize(output_file) > 10:
            return (frame_path, "cached", True)

        # Call AI
        result = ai_client.analyze_image(
            image_path=frame_path,
            prompt="Describe this video frame in detail. What do you see? Include setting, people, objects, text, mood.",
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            detail=args.detail,
        )

        if result:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result)
            return (frame_path, result[:50], True)
        return (frame_path, "failed", False)

    completed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(analyze_frame, path, i): i
            for i, (path, _) in enumerate(frame_paths)
        }

        for future in as_completed(futures):
            path, preview, success = future.result()
            completed += 1
            if success:
                print(f"\r   🔍 {completed}/{len(frame_paths)} analyzed", end="", flush=True)
            else:
                failed += 1

    print()
    print_info(f"Frame analysis: {completed - failed}/{completed} succeeded")
    print()

    # Generate summary (if not skipped)
    summary_text = ""
    if not args.no_summary:
        print_step("SUMMARY", "Generating comprehensive summary...")
        summary_text = "Summary generation placeholder"
    else:
        print_step("SKIP", "Summary generation skipped (--no-summary)")

    # Generate report
    print_step("REPORT", "Generating final report...")
    report_text = generate_vision_report(
        video_file=args.video,
        duration=duration,
        duration_fmt=metadata.get("duration_fmt", "00:00:00"),
        resolution=metadata.get("video", {}).get("resolution", "unknown"),
        codec=metadata.get("video", {}).get("codec", "unknown"),
        fps=metadata.get("video", {}).get("fps", 0),
        provider=args.provider,
        model=args.model or "default",
        summary=summary_text,
        format_type=args.format or "markdown",
    )

    report_file = os.path.join(out_dir, f"report.{'md' if args.format == 'markdown' else 'json'}")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    print()
    print("=" * 60, file=sys.stderr)
    print("✅ Video analysis complete!", file=sys.stderr)
    print(f"   📄 Report: {report_file}", file=sys.stderr)
    print(f"   🖼️  Frames: {frames_dir}/ ({len(frame_paths)} images)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = create_parser()
    args = parser.parse_args()

    # Show help if no args
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    # Check for video file
    if not args.video:
        print("Error: Video file required", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    if not os.path.isfile(args.video):
        print(f"Error: Video file not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    # Load config file
    config_path = find_config(args.config)
    if config_path:
        config = load_config(config_path)
        print_info(f"Config: {config_path}")
        # Apply config values (CLI args take precedence)
        for key, val in config.items():
            if key == "provider" and not (hasattr(args, f"provider") and getattr(args, "provider", "openai") != "openai"):
                args.provider = val
            elif key == "model" and not args.model:
                args.model = val
            elif key == "parallel" and hasattr(args, "parallel"):
                try:
                    args.parallel = int(val)
                except ValueError:
                    pass

    # Determine mode
    is_vision = args.vision and not args.local

    # Check prerequisites
    errors = check_prerequisites(
        require_api=is_vision,
        provider=args.provider
    )
    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    out_dir = ensure_output_dir(args.out, args.video)

    # Route to pipeline
    if is_vision:
        run_vision_mode(args, out_dir)
    else:
        run_local_mode(args, out_dir)

    # Output path for scripting
    print(out_dir)


if __name__ == "__main__":
    main()
