#!/usr/bin/env python3
"""
Report generator for Video AI Analyzer v3.

Supports two modes:
  --mode local   → Reads perception.json, produces Markdown/JSON report
  --mode vision  → Reads frame-analysis/ + frames/, produces Markdown/JSON report

Output: Markdown (default) or JSON.
"""

import sys
import os
import json
import argparse
import re
from datetime import datetime, timezone
from typing import Optional


VERSION = "3.0.0"


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def safe_get(d: dict, *keys, default=""):
    """Drill into nested dicts safely."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d if d is not None else default


def fmt_duration(seconds: float) -> str:
    """Seconds → HH:MM:SS"""
    s = int(seconds)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def brightness_label(b: float) -> str:
    if b > 0.75: return "🔆 很亮"
    if b > 0.5:  return "💡 适中"
    if b > 0.25: return "🌙 偏暗"
    return "🌑 很暗"


def motion_label(m: float) -> str:
    if m > 0.3:  return "🏃 运动显著"
    if m > 0.1:  return "🚶 轻微运动"
    if m > 0.02: return "🧍 基本静态"
    return "🪨 完全静止"


def color_swatch(colors: list[str]) -> str:
    """Render color palette as inline swatches."""
    if not colors or colors == ["#808080"]:
        return "*(无显著主色调)*"
    parts = []
    for c in colors[:5]:
        parts.append(f'`{c}`')
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Local mode report
# ═══════════════════════════════════════════════════════════════════════

def generate_local_report(perception: dict, video_file: str,
                          fmt: str = "markdown") -> str:
    """Generate report from local-perceive.py output (perception.json)."""

    meta = perception.get("video", {})
    segments = perception.get("segments", [])
    transcript = perception.get("transcript", {})
    tools = perception.get("tools_available", {})

    if fmt == "json":
        return json.dumps({
            "version": VERSION,
            "mode": "local",
            "engine": perception.get("engine", "video-ai-analyzer-local"),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "video": meta,
            "tools_available": tools,
            "segment_count": len(segments),
            "segments": segments,
            "transcript": transcript,
        }, indent=2, ensure_ascii=False)

    # ── Markdown ───────────────────────────────────────────────────
    lines = []
    lines.append(f"# 🎬 视频感知报告: {meta.get('file', os.path.basename(video_file))}")
    lines.append("")
    lines.append(f"> 📅 分析时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"> 🔧 分析引擎: **本地感知模式** (Video AI Analyzer v{VERSION})")
    lines.append(f"> 💰 费用: **免费** (零 API 调用，纯本地处理)")
    lines.append("")

    # Video metadata
    lines.append("## 📊 视频信息")
    lines.append("")
    lines.append("| 属性 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 文件名 | `{meta.get('file', '?')}` |")
    lines.append(f"| 时长 | {meta.get('duration_fmt', '?')} ({meta.get('duration_sec', 0)} 秒) |")
    lines.append(f"| 大小 | {meta.get('size_mb', '?')} MB |")

    video_info = meta.get("video") or {}
    lines.append(f"| 分辨率 | {video_info.get('resolution', '?')} |")
    lines.append(f"| 编码 | {video_info.get('codec', '?')} |")
    lines.append(f"| 帧率 | {video_info.get('fps', '?')} fps |")

    audio_info = meta.get("audio") or {}
    lines.append(f"| 音频 | {audio_info.get('codec', '无')} ({audio_info.get('channels', 0)}ch, {audio_info.get('sample_rate', 0)}Hz) |")
    lines.append("")

    # Available tools
    lines.append("## 🛠️ 可用分析工具")
    lines.append("")
    for tool, available in sorted(tools.items()):
        icon = "✅" if available else "❌"
        lines.append(f"- {icon} `{tool}`")
    lines.append("")

    # Transcript
    lines.append("## 🎙️ 语音转录")
    lines.append("")
    if transcript:
        engine = transcript.get("engine", "unknown")
        text = transcript.get("text", "")
        if not text:
            segs = transcript.get("segments", [])
            if isinstance(segs, list):
                text = " ".join(
                    s.get("text", "") for s in segs
                    if isinstance(s, dict)
                )
            elif isinstance(segs, str):
                text = segs
        lines.append(f"> 转录引擎: `{engine}`")
        lines.append("")
        if text:
            lines.append(text)
        else:
            lines.append("*(转录内容为空)*")
    else:
        lines.append("> *(未进行语音转录，或无音频轨道)*")
    lines.append("")

    # Scene analysis
    lines.append("## 🖼️ 场景逐段分析")
    lines.append("")
    lines.append(f"> 共检测到 **{len(segments)}** 个场景段落")
    lines.append("")

    for seg in segments:
        idx = seg.get("index", 0)
        start = seg.get("start_fmt", fmt_duration(seg.get("start", 0)))
        end = seg.get("end_fmt", fmt_duration(seg.get("end", 0)))
        dur = seg.get("duration", 0)
        desc = seg.get("description", "")
        scene = seg.get("scene", {})

        lines.append(f"### 场景 {idx + 1} — {start} → {end} ({dur:.1f}s)")
        lines.append("")

        # Scene data table
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        b = scene.get("brightness", 0.5)
        m = scene.get("motion", 0)
        faces = scene.get("faces_detected", 0)
        colors = scene.get("dominant_colors", [])

        lines.append(f"| 亮度 | {brightness_label(b)} ({(b*100):.0f}%) |")
        lines.append(f"| 运动 | {motion_label(m)} ({(m*100):.0f}%) |")
        lines.append(f"| 人脸 | {faces} 张 |")
        lines.append(f"| 主色调 | {color_swatch(colors)} |")
        lines.append("")

        # Synthesized description
        if desc:
            lines.append(f"> {desc}")
            lines.append("")

        # OCR results
        ocr_items = seg.get("ocr", [])
        if ocr_items:
            lines.append("**识别文字：**")
            lines.append("")
            for item in ocr_items[:10]:
                t = item.get("text", "")
                if t.strip():
                    lines.append(f"- {t}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Scene timeline summary
    lines.append("## ⏱️ 场景时间线")
    lines.append("")
    lines.append("| # | 时间段 | 时长 | 摘要 |")
    lines.append("|---|--------|------|------|")
    for seg in segments:
        idx = seg.get("index", 0)
        start = seg.get("start_fmt", "?")
        end = seg.get("end_fmt", "?")
        dur = seg.get("duration", 0)
        desc = seg.get("description", "")
        # Truncate long descriptions for table
        if len(desc) > 60:
            desc = desc[:57] + "..."
        lines.append(f"| {idx + 1} | {start}–{end} | {dur:.0f}s | {desc} |")
    lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Vision mode report (from v2, preserved)
# ═══════════════════════════════════════════════════════════════════════

def parse_frame_filename(name: str) -> dict:
    """Parse frame filename like 'frame_0000_000000.jpg' into index and time."""
    m = re.match(r"frame_(\d+)_(\d{2})(\d{2})(\d{2})", name)
    if not m:
        return {"index": 0, "time_raw": name, "seconds": 0}
    idx = int(m.group(1))
    h, mi, s = int(m.group(2)), int(m.group(3)), int(m.group(4))
    return {
        "index": idx,
        "timestamp": f"{h:02d}:{mi:02d}:{s:02d}",
        "seconds": h * 3600 + mi * 60 + s,
    }


def collect_frames(analysis_dir: str, frames_dir: str) -> list[dict]:
    """Collect frame analysis data from vision mode output."""
    frames = []
    analysis_dir = analysis_dir or ""
    frames_dir = frames_dir or ""

    if os.path.isdir(analysis_dir):
        for fname in sorted(os.listdir(analysis_dir)):
            if not fname.endswith(".txt"):
                continue
            fpath = os.path.join(analysis_dir, fname)
            info = parse_frame_filename(fname)
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
    elif os.path.isdir(frames_dir):
        for fname in sorted(os.listdir(frames_dir)):
            if not fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            info = parse_frame_filename(fname)
            info["image"] = fname
            info["analysis"] = ""
            frames.append(info)

    return frames


def read_transcript(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def generate_vision_report(args: argparse.Namespace, frames: list[dict],
                           transcript: str, fmt: str = "markdown") -> str:
    """Generate report from vision mode data."""

    if fmt == "json":
        return json.dumps({
            "version": VERSION,
            "mode": "vision",
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
        }, indent=2, ensure_ascii=False)

    # ── Markdown ───────────────────────────────────────────────────
    lines = []
    lines.append(f"# 🧠 视频分析报告: {os.path.basename(args.video_file)}")
    lines.append("")
    lines.append(f"> 📅 分析时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"> 🤖 分析引擎: {args.provider}/{args.model} (视觉) + Whisper (语音)")
    lines.append(f"> 🔧 分析工具: Video AI Analyzer v{VERSION}")
    lines.append("")

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

    lines.append("## 🎙️ 语音转录")
    lines.append("")
    if transcript:
        lines.append(transcript)
    else:
        lines.append("> *(未进行语音转录，或无音频轨道)*")
    lines.append("")

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

    lines.append("## 🧠 综合摘要")
    lines.append("")
    if args.summary:
        lines.append(args.summary)
    else:
        lines.append("> *(综合摘要未生成)*")
    lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=f"Report generator for Video AI Analyzer v{VERSION}"
    )
    parser.add_argument("--mode", default="vision",
                        choices=["local", "vision"],
                        help="Report mode: local (from perception.json) or vision (from frame-analysis/)")

    # Local mode args
    parser.add_argument("--perception-file", default="",
                        help="Path to perception.json (local mode, default: <out-dir>/perception.json)")

    # Vision mode args
    parser.add_argument("--out-dir", default="",
                        help="Analysis output directory (vision mode)")
    parser.add_argument("--video-file", default="",
                        help="Original video file path")
    parser.add_argument("--duration", default="0",
                        help="Duration in seconds")
    parser.add_argument("--duration-fmt", default="00:00:00",
                        help="Duration formatted (HH:MM:SS)")
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

    # Common
    parser.add_argument("--format", default="markdown",
                        choices=["markdown", "json"],
                        help="Output format (default: markdown)")

    args = parser.parse_args()

    # ── Local mode ──────────────────────────────────────────────────
    if args.mode == "local":
        perception_path = args.perception_file
        if not perception_path and args.out_dir:
            perception_path = os.path.join(args.out_dir, "perception.json")
        if not perception_path:
            print("Error: --perception-file or --out-dir required for local mode", file=sys.stderr)
            sys.exit(1)
        if not os.path.isfile(perception_path):
            print(f"Error: perception.json not found at {perception_path}", file=sys.stderr)
            sys.exit(1)

        with open(perception_path, "r", encoding="utf-8") as f:
            perception = json.load(f)

        video_file = args.video_file or perception.get("video", {}).get("path", "unknown.mp4")
        print(generate_local_report(perception, video_file, args.format))
        sys.exit(0)

    # ── Vision mode ─────────────────────────────────────────────────
    if not args.out_dir:
        print("Error: --out-dir required for vision mode", file=sys.stderr)
        sys.exit(1)

    transcript_path = os.path.join(args.out_dir, "transcript.txt")
    transcript = read_transcript(transcript_path)

    analysis_dir = os.path.join(args.out_dir, "frame-analysis")
    frames_dir = os.path.join(args.out_dir, "frames")
    frames = collect_frames(analysis_dir, frames_dir)

    print(generate_vision_report(args, frames, transcript, args.format))


if __name__ == "__main__":
    main()
