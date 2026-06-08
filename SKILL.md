---
name: video-ai-analyzer
version: 3.0.0-alpha
description: >-
  Local video perception engine — "Whisper for video".
  DEFAULT MODE: Runs entirely locally (scene detection, color/motion analysis,
  optional OCR via tesseract, optional transcription via whisper.cpp).
  No AI vision API required. Outputs time-stamped structured JSON.
  OPT-IN VISION MODE: Extract frames → GPT-4V/Claude/Gemini describe each frame.
  Use when the user wants to "understand what's in a video", "analyze video
  content", "get scene descriptions", "perceive video without AI API".
  ⚠️ ALPHA — v3 branch, v2 stable on main.
providers:
  - local (default, zero API)
  - openai
  - anthropic
  - google
  - ollama
  - openai-compatible
---

# Video AI Analyzer v3 (alpha)

Dual-mode video perception engine:
- **Local mode (DEFAULT)**: Scene detection, color/motion analysis, OCR, face detection — zero API cost, zero privacy loss
- **Vision mode (opt-in)**: Extract frames → GPT-4V/Claude/Gemini describe each frame → AI-generated summary

## 🚀 Quick Start

```bash
# ─── Local mode (DEFAULT, zero API, zero cost) ─────────
/Users/mac/.workbuddy/skills/video-ai-analyzer/scripts/analyze.sh video.mp4
# Output: perception.json with time-stamped scene descriptions

# ─── Local + transcription ─────────────────────────────
/Users/mac/.workbuddy/skills/video-ai-analyzer/scripts/analyze.sh lecture.mp4 --transcribe --language zh

# ─── Vision mode (needs API key) ───────────────────────
export OPENAI_API_KEY="sk-..."
/Users/mac/.workbuddy/skills/video-ai-analyzer/scripts/analyze.sh video.mp4 --vision --provider openai
```

## ✨ What's New in v3

- **Local Perception Mode (DEFAULT)**: Scene detection + color palette + brightness + motion + face detection + OCR — no AI API needed
- **Whisper-like JSON output**: Structured time-stamped segments that any AI agent can consume
- **Dual-mode architecture**: `--local` (default) for zero-cost perception, `--vision` for AI-powered analysis
- **Auto-fallback transcription**: whisper.cpp → OpenAI Whisper API; no transcription dependency
- **Scene-aware sampling**: Intelligent scene-change detection instead of fixed-interval sampling
- **All v2 vision features retained**: Multi-provider, parallel analysis, caching, retry logic, cost estimation

## 🏗️ Supported Providers

| Provider | Default Vision Model | Default Summary Model | Auth |
|----------|---------------------|----------------------|------|
| `openai` | `gpt-4o` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic` | `claude-3-5-sonnet-20241022` | `claude-3-5-haiku-20241022` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.0-flash-exp` | `gemini-2.0-flash-exp` | `GOOGLE_API_KEY` |
| `ollama` | `llava` | same as vision | None (local) |
| `openai-compatible` | `gpt-4o` | same as vision | `OPENAI_API_KEY` |

## 📋 Modes

| Flag | Description |
|------|-------------|
| `--local` | **DEFAULT** — Local perception: scene detection, color/motion, OCR, face detection, optional transcription. Zero API cost. |
| `--vision` | AI vision mode: extract frames → AI describes each frame → AI-generated summary. Requires API key. |

## 📋 Common Options

| Flag | Default | Description |
|------|---------|-------------|
| `--out DIR` | `./video-analysis-{ts}` | Output directory |
| `--transcribe` | `false` | Enable audio transcription |
| `--language LANG` | auto | Language hint (e.g., `zh`, `en`, `ja`) |
| `--format FORMAT` | `json` (local) / `markdown` (vision) | Output format: json\|markdown |
| `--config FILE` | auto-discover | Config file path |

## 📋 Local Mode Options

| Flag | Default | Description |
|------|---------|-------------|
| `--scene-threshold N` | `0.3` | Scene detection sensitivity 0-1 |
| `--max-segments N` | `50` | Max scene segments |
| `--no-ocr` | `false` | Disable OCR text extraction |

## 📋 Vision Mode Options

| Flag | Default | Description |
|------|---------|-------------|
| `--provider NAME` | `openai` | AI provider (openai\|anthropic\|google\|ollama\|openai-compatible) |
| `--model MODEL` | provider default | Vision model for frame analysis |
| `--summary-model M` | cheaper variant | Model for final summary generation |
| `--interval N` | `10` | Seconds between frame captures |
| `--max-frames N` | `20` | Max frames to analyze (API cost control) |
| `--no-transcribe` | `false` | Skip audio transcription |
| `--detail LEVEL` | `low` | Image detail: low\|high\|auto (OpenAI) |
| `--max-tokens N` | `500` | Max tokens per frame analysis |
| `--temperature T` | `0.7` | Sampling temperature |
| `--parallel N` | `5` | Max concurrent frame analyses |
| `--base-url URL` | provider default | Override API base URL |
| `--no-summary` | `false` | Skip AI-generated summary |

## ⚙️ Config File

Create `.video-ai-analyzer.yaml` in your project root:

```yaml
provider: anthropic
model: claude-3-5-sonnet-20241022
interval: 5
max_frames: 30
format: markdown
```

Discovery order: `--config` arg → `./.video-ai-analyzer.yaml` → parent dirs → `~/.config/video-ai-analyzer/config.yaml`. CLI flags always override config values.

## 📖 Examples

```bash
BASE="/Users/mac/.workbuddy/skills/video-ai-analyzer/scripts"

# ─── Local mode (DEFAULT, zero API cost) ──────────────
$BASE/analyze.sh meeting.mp4

# ─── Local + transcription ────────────────────────────
$BASE/analyze.sh lecture.mp4 --transcribe --language zh

# ─── Local + no OCR ───────────────────────────────────
$BASE/analyze.sh video.mp4 --no-ocr --scene-threshold 0.5

# ─── Vision mode: OpenAI ──────────────────────────────
$BASE/analyze.sh product-demo.mp4 --vision --provider openai

# ─── Vision mode: Anthropic Claude ────────────────────
$BASE/analyze.sh video.mp4 --vision --provider anthropic

# ─── Vision mode: Google Gemini ───────────────────────
$BASE/analyze.sh lecture.mp4 --vision --provider google --language zh

# ─── Vision mode: Local Ollama ────────────────────────
$BASE/analyze.sh demo.mp4 --vision --provider ollama --model llava

# ─── Vision mode: DeepSeek ────────────────────────────
$BASE/analyze.sh clip.mp4 --vision --provider openai-compatible \
  --base-url https://api.deepseek.com --model deepseek-chat

# ─── Vision mode: sparse sampling for long videos ─────
$BASE/analyze.sh movie.mp4 --vision --interval 60 --max-frames 15 --no-transcribe
```

## 🔄 How It Works

```
                    ┌─────────────┐
                    │  视频文件     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         MODE: local   MODE: vision   (shared)
              │            │            │
    ┌─────────┤     ┌──────┤      ffprobe 元信息
    ▼         ▼     ▼      ▼            │
  场景检测  抽帧   帧提取  帧提取    时长/分辨率
    │         │     │      │
    ▼         ▼     ▼      ▼
  颜色分析  运动  Vision AI  Whisper
    │         │    (并行多Provider)  (可选)
    ▼         ▼     │      │
  OCR+人脸  合成   逐帧描述  文字稿
    │         │     │      │
    └────┬────┘     └──┬───┘
         ▼             ▼
   perception.json  report.md
   (结构化感知数据)  (综合分析报告)
         │             │
         └──────┬──────┘
                ▼
          AI Agent 可读
```

### Local Mode Output (perception.json)
```json
{
  "segments": [
    {
      "index": 0,
      "start": 0.0, "end": 12.5,
      "scene": {"brightness": 0.72, "motion": 0.03, "dominant_colors": ["#2a3f5c", "#e8d5b7"]},
      "description": "1 face detected. moderately lit scene. cool tones dominate. mostly static."
    }
  ],
  "transcript": { "engine": "openai-whisper", "text": "..." }
}
```

### Vision Mode Output (report.md)
```
video-analysis-{name}-{timestamp}/
├── report.md              # Comprehensive report with AI summary
├── transcript.txt         # Whisper transcription
├── frames/                # Extracted frame images
└── frame-analysis/        # Per-frame AI descriptions (cached)
```

## 🤖 Agent Instructions

When a user asks to analyze a video, follow these steps:

### Default: Local Mode (recommended first)

1. **Check prerequisites**: Ensure `ffmpeg` + `ffprobe` are installed (`brew install ffmpeg`)
2. **Run local perception**: `/Users/mac/.workbuddy/skills/video-ai-analyzer/scripts/analyze.sh <video>`
   - Add `--transcribe --language zh` for Chinese videos with speech
   - Add `--no-ocr` if OCR is slow/unnecessary
3. **Read result**: Parse `perception.json` — it contains time-stamped `segments[]` with `description`, `scene` data, and optional `transcript`
4. **Present to user**: Synthesize the JSON data into a human-readable summary in the user's language

### Opt-in: Vision Mode (for deep understanding)

1. **Set API key**: Export `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`
2. **Run vision analysis**: `/Users/mac/.workbuddy/skills/video-ai-analyzer/scripts/analyze.sh <video> --vision --provider <provider>`
3. **Read results**: Open `report.md` and present findings to the user

### Mode Selection Guide

| User Intent | Use Mode | Why |
|-------------|----------|-----|
| "这个视频讲什么" / "What's in this video" | `--local` | Fast, free, sufficient for content overview |
| "详细分析每个场景" / "Deep scene analysis" | `--vision` | AI-powered per-frame description |
| "视频里有文字吗" / "Is there text?" | `--local --transcribe` | OCR + transcription gives full text |
| "帮我总结这个讲座" / "Summarize this lecture" | `--local --transcribe --language zh` | Transcript + scene context → Agent summarizes |
| "分析产品演示视频" / "Analyze product demo" | `--vision --interval 5` | Need detailed visual understanding |

## 🎨 Design Philosophy

- **Local-first**: Default mode uses zero API — scene detection, color analysis, motion estimation, OCR, face detection all run locally
- **Dual-mode**: `--local` for free perception, `--vision` for AI-powered deep analysis
- **Multi-Provider**: Vision mode works with OpenAI, Anthropic, Google, Ollama, any OpenAI-compatible
- **Lightweight**: Only ffmpeg + python3. Zero pip dependencies. Zero local model downloads (tesseract/whisper.cpp optional)
- **Focused**: "看懂" (understanding) is the single goal
- **Agent-friendly**: Structured JSON output (local) or Markdown report (vision), clear structure, cache for resume

## 📝 Notes

- **Local mode is the default** — always try `--local` first before reaching for `--vision`
- Local mode outputs structured JSON (`perception.json`) that any AI agent can read and summarize
- Vision mode frame analysis results are cached — re-running picks up where it left off
- Transcription auto-fallback: whisper.cpp (local) → OpenAI Whisper API → skip gracefully
- OCR requires `tesseract` (`brew install tesseract`). Gracefully skips if unavailable.
- Face detection uses ffmpeg's built-in `facedetect` filter — no extra deps
- Ollama requires `ollama pull llava` (or preferred vision model) before first use
- For videos >30 min, increase `--interval` or reduce `--max-frames` (vision mode)

## 🔧 Requirements

- **ffmpeg** + **ffprobe**: `brew install ffmpeg` or `apt install ffmpeg`
- **python3**: Standard library only — no pip installs needed
- **API key**: One of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` (none for Ollama)

## 📄 License

MIT
