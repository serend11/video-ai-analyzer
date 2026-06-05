---
name: video-ai-analyzer
description: AI-powered video content understanding — extracts frames, analyzes them with GPT-4V, transcribes audio with Whisper, and generates a comprehensive report. Use when the user wants to "understand what's in a video", "analyze video content", "get a summary of a video", "see what happens in this video", or any video comprehension task.
---

# Video AI Analyzer

AI-driven video understanding: extract frames, analyze with GPT-4V vision, transcribe speech with Whisper, and produce a comprehensive structured report — all in one pipeline.

## Quick Start

```bash
{baseDir}/scripts/analyze.sh /path/to/video.mp4
```

This produces a full analysis report at `./video-analysis-{timestamp}/report.md`.

## How It Works

```
                     ┌─────────────┐
                     │  视频文件     │
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ffprobe 元信息   ffmpeg 抽帧    ffmpeg 提取音频
              │             │             │
              ▼             ▼             ▼
           时长/分辨率   关键帧图片    Whisper 转录
              │             │             │
              │             ▼             │
              │      GPT-4V 视觉分析      │
              │      逐帧描述场景          │
              │             │             │
              └──────────┬──┘─────────────┘
                         ▼
                  📄 综合分析报告 (Markdown)
                  
  ┌─────────────────────────────────────────┐
  │  # 视频分析报告                          │
  │                                         │
  │  ## 📊 视频信息 (时长/分辨率/编码)        │
  │  ## 🎙️ 语音转录 (带时间戳的完整文字稿)    │
  │  ## 🖼️ 场景分析 (逐帧 AI 视觉描述)        │
  │  ## 🧠 综合摘要 (整体内容理解)            │
  └─────────────────────────────────────────┘
```

## Requirements

- **ffmpeg** + **ffprobe**: `brew install ffmpeg` or `apt install ffmpeg`
- **OPENAI_API_KEY**: `export OPENAI_API_KEY="sk-..."`

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--interval N` | `10` | Seconds between frame captures |
| `--max-frames N` | `20` | Max frames to analyze (API cost control) |
| `--out DIR` | `./video-analysis-{ts}` | Output directory |
| `--model MODEL` | `gpt-4o` | OpenAI vision model |
| `--no-transcribe` | `false` | Skip audio transcription |
| `--language LANG` | auto | Whisper language hint (e.g., `zh`, `en`) |

## Examples

```bash
# Basic analysis
{baseDir}/scripts/analyze.sh meeting.mp4

# Fine-grained analysis (every 5s) for a short clip
{baseDir}/scripts/analyze.sh product-demo.mp4 --interval 5 --max-frames 30

# Chinese video with language hint for better transcription
{baseDir}/scripts/analyze.sh lecture.mp4 --language zh

# Custom output location
{baseDir}/scripts/analyze.sh video.mp4 --out /tmp/my-analysis

# Long video: sparse sampling, skip transcription
{baseDir}/scripts/analyze.sh movie.mp4 --interval 60 --max-frames 15 --no-transcribe
```

## Output Report Structure

The generated `report.md` includes:

1. **📊 视频信息** — duration, resolution, codec, frame rate, bitrate
2. **🎙️ 语音转录** — complete transcript with timestamps (from Whisper)
3. **🖼️ 场景分析** — per-frame GPT-4V visual description at each timestamp
4. **🧠 综合摘要** — overall understanding: what the video is about, key moments, people, setting, mood

## Design Philosophy

- **Lightweight**: Only ffmpeg + curl + OPENAI_API_KEY. Zero Python dependencies. Zero local model downloads.
- **Focused**: Analysis only. No video generation, no editing. "看懂" is the single goal.
- **Comprehensive**: Combines visual understanding (GPT-4V) + audio understanding (Whisper) for full comprehension.
- **Cost-aware**: `--max-frames` and `--interval` controls give full control over API usage.

## Notes

- Each frame is analyzed independently via GPT-4V, then results are synthesized
- For long videos (>30 min), increase `--interval` or reduce `--max-frames`
- Whisper transcription supports 99+ languages; use `--language` for accuracy
- Frame analysis prompts are in `references/frame-prompt.md`
