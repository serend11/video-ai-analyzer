#!/usr/bin/env python3
"""
Report generator for Video AI Analyzer.
Produces Markdown or JSON reports from analysis data.
"""

import sys
import os
import json
import argparse
import re
from datetime import datetime, timezone


def parse_frame_filename(name: str) -> dict:
    """Parse frame filename like 'frame_0000_000000.jpg' into index and time."""
    m = re.match(r"frame_(\d+)_(\d{2})(\d{2})(\d{2})", name)
    if not m:
        return {"index": 0, "time_raw": name, "seconds": 0}
    idx = int(m.group(1))
    h, mi, s = int(m.group(2)), int(m.group(3)), int(m.group(4))
    seconds = h * 3600 + mi * 60 + s
    return {
        "index": idx,
        "timestamp": f"{h:02d}:{mi:02d}:{s:02d}",
        "seconds": seconds,
    }


def collect_frames(analysis_dir: str, frames_dir: str) -> list[dict]:
    """Collect frame analysis data from the output directory."""
    frames = []

    analysis_dir = analysis_dir or ""
    frames_dir = frames_dir or ""

    # Walk analysis files
    if os.path.isdir(analysis_dir):
        for fname in sorted(os.listdir(analysis_dir)):
            if not fname.endswith(".txt"):
                continue
            fpath = os.path.join(analysis_dir, fname)
            info = parse_frame_filename(fname)
            # Find corresponding image
            img_name = fname.replace(".txt", ".jpg")
            img_path = os.path.join(frames_dir, img_name)

            analysis = ""
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    analysis = f.read().strip()
            except Exception:
                pass

            frames.append({
                **info,
                "image": os.path.basename(img_path) if os.path.isfile(img_path) else img_name,
                "analysis": analysis,
            })
    else:
        # Fallback: try to scan frames directory directly
        if os.path.isdir(frames_dir):
            for fname in sorted(os.listdir(frames_dir)):
                if not fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue
                info = parse_frame_filename(fname)
                info["image"] = fname
                info["analysis"] = ""
                frames.append(info)

    return frames


def read_transcript(path: str) -> str:
    """Read transcript file, return empty string if not found."""
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def generate_markdown(args: argparse.Namespace, frames: list[dict],
                      transcript: str) -> str:
    """Generate Markdown report."""
    lines = []
    lines.append(f"# 视频分析报告: {os.path.basename(args.video_file)}")
    lines.append("")
    lines.append(f"> 分析时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"> 分析引擎: {args.provider}/{args.model} (视觉) + Whisper (语音)")
    lines.append("> 分析工具: Video AI Analyzer v2.0.0")
    lines.append("")

    # Video metadata
    lines.append("## 📊 视频信息")
    lines.append("")
    lines.append("| 属性 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 文件名 | `{os.path.basename(args.video_file)}` |")
    lines.append(f"| 时长 | {args.duration_fmt} ({args.duration} 秒) |")
    lines.append(f"| 分辨率 | {args.resolution} |")
    lines.append(f"| 编码 | {args.codec} |")
    lines.append(f"| 帧率 | {args.fps} fps |")
    lines.append(f"| 码率 | {args.bitrate} |")
    lines.append(f"| 文件大小 | {args.filesize} |")
    lines.append(f"| 音频 | {args.has_audio} |")
    lines.append("")

    # Transcript
    lines.append("## 🎙️ 语音转录")
    lines.append("")
    if transcript:
        lines.append(transcript)
    else:
        lines.append("> *(未进行语音转录，或无音频轨道)*")
    lines.append("")

    # Frame analysis
    lines.append("## 🖼️ 场景分析")
    lines.append("")
    lines.append(f"> 共分析 **{len(frames)}** 个关键帧")
    lines.append("")

    for i, frame in enumerate(frames):
        ts = frame.get("timestamp", frame.get("time_raw", f"frame_{i}"))
        lines.append(f"### 场景 {i + 1} — {ts}")
        lines.append("")
        analysis = frame.get("analysis", "")
        if analysis:
            lines.append(analysis)
        else:
            lines.append("> *(分析不可用)*")
        lines.append("")

    # Summary
    lines.append("## 🧠 综合摘要")
    lines.append("")
    if args.summary:
        lines.append(args.summary)
    else:
        lines.append("> *(综合摘要未生成)*")
    lines.append("")

    return "\n".join(lines)


def generate_json(args: argparse.Namespace, frames: list[dict],
                  transcript: str) -> str:
    """Generate JSON report."""
    report = {
        "version": "2.0.0",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "summary_model": args.summary_model,
        "video": {
            "file": os.path.basename(args.video_file),
            "path": args.video_file,
            "duration": int(args.duration),
            "duration_formatted": args.duration_fmt,
            "resolution": args.resolution,
            "codec": args.codec,
            "fps": args.fps,
            "bitrate": args.bitrate,
            "filesize": args.filesize,
            "has_audio": args.has_audio,
        },
        "transcript": transcript,
        "frames": [
            {
                "index": f["index"],
                "timestamp": f.get("timestamp", ""),
                "seconds": f.get("seconds", 0),
                "image": f.get("image", ""),
                "analysis": f.get("analysis", ""),
            }
            for f in frames
        ],
        "summary": args.summary or "",
    }
    return json.dumps(report, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Generate report for Video AI Analyzer")
    parser.add_argument("--out-dir", required=True, help="Analysis output directory")
    parser.add_argument("--video-file", required=True, help="Original video file path")
    parser.add_argument("--duration", required=True, help="Duration in seconds")
    parser.add_argument("--duration-fmt", required=True, help="Duration formatted (HH:MM:SS)")
    parser.add_argument("--resolution", default="unknown")
    parser.add_argument("--codec", default="unknown")
    parser.add_argument("--fps", default="unknown")
    parser.add_argument("--bitrate", default="unknown")
    parser.add_argument("--filesize", default="unknown")
    parser.add_argument("--has-audio", default="none")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--summary-model", default="gpt-4o-mini")
    parser.add_argument("--summary", default="", help="Summary text")
    parser.add_argument("--format", default="markdown",
                        choices=["markdown", "json"],
                        help="Output format (default: markdown)")

    args = parser.parse_args()

    transcript_path = os.path.join(args.out_dir, "transcript.txt")
    transcript = read_transcript(transcript_path)

    analysis_dir = os.path.join(args.out_dir, "frame-analysis")
    frames_dir = os.path.join(args.out_dir, "frames")
    frames = collect_frames(analysis_dir, frames_dir)

    if args.format == "json":
        output = generate_json(args, frames, transcript)
    else:
        output = generate_markdown(args, frames, transcript)

    print(output)


if __name__ == "__main__":
    main()
