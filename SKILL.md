---
name: video-ai-analyzer
version: 3.2.0
description: >-
  Local video perception engine — "Whisper for video".
  DEFAULT MODE: Runs entirely locally (scene detection, color/motion analysis,
  optional OCR via tesseract, optional transcription via whisper.cpp).
  No AI vision API required. Outputs time-stamped structured JSON.
  OPT-IN VISION MODE: Extract frames → GPT-4V/Claude/Gemini describe each frame.
  NEW: AI image recognition in local mode with --vision flag.
  Use when the user wants to "understand what's in a video", "analyze video
  content", "get scene descriptions", "perceive video without AI API".
  / 本地视频感知引擎。默认纯本地运行（场景检测、色彩/运动分析、OCR、语音转写）。
  可选AI视觉模式，支持逐帧AI描述。新增：本地模式下的AI识图功能。
providers:
  - local (default, zero API) / 本地（默认，零API费用）
  - openai
  - anthropic
  - google
  - ollama
  - openai-compatible
---

# Video AI Analyzer v3.2

> **"Whisper for video"** — Let your agent perceive video content.
> **"视频领域的 Whisper"** — 让你的 agent 能看懂视频内容。

Dual-mode video perception engine / 双模式视频感知引擎：
- **Local mode (DEFAULT) / 本地模式（默认）**: Scene detection, color/motion analysis, OCR, face detection — zero API cost, zero privacy loss
- **Vision mode (opt-in) / 视觉模式（可选）**: Extract frames → GPT-4V/Claude/Gemini describe each frame → AI-generated summary
- **🆕 AI image recognition in local mode / 本地模式识图**: Add `--vision` to local mode for AI-powered frame descriptions alongside computational analysis

## 🆕 What's New in v3.2 / v3.2 新特性

- **AI image recognition for local mode / 本地模式识图**: `--vision` flag adds AI-powered frame descriptions to local perception output
- **Shared utility module / 共享工具模块**: Extracted common functions into `common.py`, eliminated ~150 lines of duplicate code across files
- **Code cleanup / 代码清理**: Removed dead code (unused imports, unused functions, unused parameters), fixed return type annotation
- **Bug fix / Bug修复**: Fixed outdated `[GPT-4V analysis error:` check in analyze.sh

## 🚀 Quick Start / 快速开始

```bash
# ─── Local mode (DEFAULT, zero API, zero cost) ─────────
# ─── 本地模式（默认，零API费用）─────────────────────
scripts/analyze.sh video.mp4
# Output: perception.json with time-stamped scene descriptions

# ─── Local + AI image recognition (NEW!) ────────────────
# ─── 本地 + AI识图（新功能！）─────────────────────────
export OPENAI_API_KEY="sk-..."
scripts/analyze.sh video.mp4 --vision --vision-provider openai

# ─── Local + transcription ─────────────────────────────
# ─── 本地 + 语音转写 ────────────────────────────────
scripts/analyze.sh lecture.mp4 --transcribe --language zh

# ─── Vision mode (needs API key) ───────────────────────
# ─── 视觉模式（需要API密钥）──────────────────────────
export OPENAI_API_KEY="sk-..."
scripts/analyze.sh video.mp4 --vision --provider openai
```

## ✨ What's New in v3 / v3 新特性

- **Local Perception Mode (DEFAULT) / 本地感知模式（默认）**: Scene detection + color palette + brightness + motion + face detection + OCR — no AI API needed
- **Whisper-like JSON output / Whisper风格JSON输出**: Structured time-stamped segments that any AI agent can consume
- **Dual-mode architecture / 双模式架构**: `--local` (default) for zero-cost perception, `--vision` for AI-powered analysis
- **Auto-fallback transcription / 本地优先转写**: whisper.cpp → OpenAI Whisper API; no transcription dependency
- **Scene-aware sampling / 场景感知采样**: Intelligent scene-change detection instead of fixed-interval sampling
- **All v2 vision features retained / 保留所有v2视觉特性**: Multi-provider, parallel analysis, caching, retry logic, cost estimation

## 🏗️ Supported Providers / 支持的提供商

| Provider / 提供商 | Default Vision Model / 默认视觉模型 | Default Summary Model / 默认摘要模型 | Auth / 认证 |
|----------|---------------------|----------------------|------|
| `openai` | `gpt-4o` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic` | `claude-3-5-sonnet-20241022` | `claude-3-5-haiku-20241022` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.0-flash-exp` | `gemini-2.0-flash-exp` | `GOOGLE_API_KEY` |
| `ollama` | `llava` | same as vision | None (local) |
| `openai-compatible` | `gpt-4o` | same as vision | `OPENAI_API_KEY` |

## 📋 Modes / 模式

| Flag / 参数 | Description / 说明 |
|------|-------------|
| `--local` | **DEFAULT** — Local perception: scene detection, color/motion, OCR, face detection, optional transcription. Zero API cost. |
| `--vision` | AI vision mode: extract frames → AI describes each frame → AI-generated summary. Requires API key. |
| `--vision` (in local mode) | 🆕 AI image recognition: adds AI-powered `vision_description` to each segment alongside computational analysis. |

## 📋 Common Options / 常用参数

| Flag / 参数 | Default / 默认值 | Description / 说明 |
|------|---------|-------------|
| `--out DIR` | `./video-analysis-{ts}` | Output directory / 输出目录 |
| `--transcribe` | `false` | Enable audio transcription / 启用语音转写 |
| `--language LANG` | auto | Language hint (e.g., `zh`, `en`, `ja`) / 语言提示 |
| `--format FORMAT` | `json` (local) / `markdown` (vision) | Output format: json\|markdown / 输出格式 |
| `--config FILE` | auto-discover | Config file path / 配置文件路径 |

## 📋 Local Mode Options / 本地模式参数

| Flag / 参数 | Default / 默认值 | Description / 说明 |
|------|---------|-------------|
| `--scene-threshold N` | `0.3` | Scene detection sensitivity 0-1 / 场景检测灵敏度 |
| `--max-segments N` | `50` | Max scene segments / 最大场景段落数 |
| `--no-ocr` | `false` | Disable OCR text extraction / 禁用OCR |
| `--vision` | `false` | 🆕 Enable AI image recognition for frames / 启用AI识图 |
| `--vision-provider NAME` | `openai` | AI provider for vision / AI识图提供商 |
| `--vision-model MODEL` | provider default | Vision model for frame analysis / 识图模型 |
| `--vision-max-tokens N` | `300` | Max tokens per vision analysis / 每帧最大token数 |

## 📋 Vision Mode Options / 视觉模式参数

| Flag / 参数 | Default / 默认值 | Description / 说明 |
|------|---------|-------------|
| `--provider NAME` | `openai` | AI provider (openai\|anthropic\|google\|ollama\|openai-compatible) |
| `--model MODEL` | provider default | Vision model for frame analysis / 视觉分析模型 |
| `--summary-model M` | cheaper variant | Model for final summary generation / 摘要生成模型 |
| `--interval N` | `10` | Seconds between frame captures / 帧提取间隔（秒） |
| `--max-frames N` | `20` | Max frames to analyze (API cost control) / 最大帧数 |
| `--no-transcribe` | `false` | Skip audio transcription / 跳过语音转写 |
| `--detail LEVEL` | `low` | Image detail: low\|high\|auto (OpenAI) / 图像细节级别 |
| `--max-tokens N` | `500` | Max tokens per frame analysis / 每帧最大token数 |
| `--temperature T` | `0.7` | Sampling temperature / 采样温度 |
| `--parallel N` | `5` | Max concurrent frame analyses / 最大并行分析数 |
| `--base-url URL` | provider default | Override API base URL / 覆盖API地址 |
| `--no-summary` | `false` | Skip AI-generated summary / 跳过AI摘要 |

## ⚙️ Config File / 配置文件

Create `.video-ai-analyzer.yaml` in your project root / 在项目根目录创建配置文件：

```yaml
provider: anthropic
model: claude-3-5-sonnet-20241022
interval: 5
max_frames: 30
format: markdown
```

Discovery order / 发现顺序: `--config` arg → `./.video-ai-analyzer.yaml` → parent dirs → `~/.config/video-ai-analyzer/config.yaml`. CLI flags always override config values.

## 📖 Examples / 使用示例

```bash
# ─── Local mode (DEFAULT, zero API cost) ──────────────
# ─── 本地模式（默认，零API费用）─────────────────────
./scripts/analyze.sh meeting.mp4

# ─── Local + AI image recognition (NEW!) ────────────────
# ─── 本地 + AI识图（新功能！）─────────────────────────
./scripts/analyze.sh video.mp4 --vision --vision-provider openai

# ─── Local + transcription ────────────────────────────
# ─── 本地 + 语音转写 ────────────────────────────────
./scripts/analyze.sh lecture.mp4 --transcribe --language zh

# ─── Local + no OCR ───────────────────────────────────
# ─── 本地 + 关闭OCR ────────────────────────────────
./scripts/analyze.sh video.mp4 --no-ocr --scene-threshold 0.5

# ─── Vision mode: OpenAI ──────────────────────────────
./scripts/analyze.sh product-demo.mp4 --vision --provider openai

# ─── Vision mode: Anthropic Claude ────────────────────
./scripts/analyze.sh video.mp4 --vision --provider anthropic

# ─── Vision mode: Google Gemini ───────────────────────
./scripts/analyze.sh lecture.mp4 --vision --provider google --language zh

# ─── Vision mode: Local Ollama ────────────────────────
./scripts/analyze.sh demo.mp4 --vision --provider ollama --model llava

# ─── Vision mode: DeepSeek ────────────────────────────
./scripts/analyze.sh clip.mp4 --vision --provider openai-compatible \
  --base-url https://api.deepseek.com --model deepseek-chat

# ─── Vision mode: sparse sampling for long videos ─────
# ─── 视觉模式：长视频稀疏采样 ────────────────────────
./scripts/analyze.sh movie.mp4 --vision --interval 60 --max-frames 15 --no-transcribe
```

## 🔄 How It Works / 工作原理

```
                    ┌─────────────┐
                    │  Video File  │
                    │  视频文件     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         MODE: local   MODE: vision   (shared)
              │            │            │
    ┌─────────┤     ┌──────┤      ffprobe metadata
    ▼         ▼     ▼      ▼            │
  Scene     Frame  Frame   Frame     Duration/
  Detection Extract Extract Extract   Resolution
    │         │     │      │
    ▼         ▼     ▼      ▼
  Color     Motion Vision AI  Whisper
  Analysis          (parallel) (optional)
    │         │     │      │
    ▼         ▼     ▼      ▼
  OCR+Face  Synthe- Frame   Transcript
            size   Descriptions
    │         │     │      │
    ▼         ▼     ▼      ▼
  🆕 AI Vision (--vision in local mode)
    │
    └────┬────┘     └──┬───┘
         ▼             ▼
   perception.json  report.md
   (structured data) (comprehensive report)
         │             │
         └──────┬──────┘
                ▼
          AI Agent readable
```

### Local Mode Output (perception.json) / 本地模式输出
```json
{
  "segments": [
    {
      "index": 0,
      "start": 0.0, "end": 12.5,
      "scene": {"brightness": 0.72, "motion": 0.03, "dominant_colors": ["#2a3f5c", "#e8d5b7"]},
      "description": "1 face detected. moderately lit scene. cool tones dominate. mostly static.",
      "vision_description": "A modern office interior with natural light..."  // 🆕 AI-powered
    }
  ],
  "transcript": { "engine": "openai-whisper", "text": "..." }
}
```

### Vision Mode Output (report.md) / 视觉模式输出
```
video-analysis-{name}-{timestamp}/
├── report.md              # Comprehensive report with AI summary / 综合分析报告
├── transcript.txt         # Whisper transcription / 语音转写
├── frames/                # Extracted frame images / 提取的帧图像
└── frame-analysis/        # Per-frame AI descriptions (cached) / 逐帧AI描述
```

## 🤖 Agent Instructions / Agent 指令

When a user asks to analyze a video, follow these steps / 当用户要求分析视频时，按以下步骤操作：

### Default: Local Mode (recommended first) / 默认：本地模式（推荐首选）

1. **Check prerequisites / 检查依赖**: Ensure `ffmpeg` + `ffprobe` are installed (`brew install ffmpeg`)
2. **Run local perception / 运行本地感知**: `scripts/analyze.sh <video>`
   - Add `--transcribe --language zh` for Chinese videos with speech
   - Add `--no-ocr` if OCR is slow/unnecessary
   - 🆕 Add `--vision --vision-provider openai` for AI image recognition
3. **Read result / 读取结果**: Parse `perception.json` — it contains time-stamped `segments[]` with `description`, `scene` data, optional `vision_description`, and optional `transcript`
4. **Present to user / 呈现给用户**: Synthesize the JSON data into a human-readable summary in the user's language

### Opt-in: Vision Mode (for deep understanding) / 可选：视觉模式（深度理解）

1. **Set API key / 设置API密钥**: Export `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`
2. **Run vision analysis / 运行视觉分析**: `scripts/analyze.sh <video> --vision --provider <provider>`
3. **Read results / 读取结果**: Open `report.md` and present findings to the user

### Mode Selection Guide / 模式选择指南

| User Intent / 用户意图 | Use Mode / 使用模式 | Why / 原因 |
|-------------|----------|-----|
| "这个视频讲什么" / "What's in this video" | `--local` | Fast, free, sufficient for content overview |
| "详细分析每个场景" / "Deep scene analysis" | `--vision` | AI-powered per-frame description |
| "视频里有文字吗" / "Is there text?" | `--local --transcribe` | OCR + transcription gives full text |
| "帮我总结这个讲座" / "Summarize this lecture" | `--local --transcribe --language zh` | Transcript + scene context → Agent summarizes |
| "分析产品演示视频" / "Analyze product demo" | `--vision --interval 5` | Need detailed visual understanding |
| 🆕 "视频里有什么物体/人物" / "What objects/people in video" | `--local --vision` | AI recognition + local analysis combined |

## 🎨 Design Philosophy / 设计哲学

- **Local-first / 本地优先**: Default mode uses zero API — scene detection, color analysis, motion estimation, OCR, face detection all run locally
- **Dual-mode / 双模式**: `--local` for free perception, `--vision` for AI-powered deep analysis
- **Multi-Provider / 多提供商**: Vision mode works with OpenAI, Anthropic, Google, Ollama, any OpenAI-compatible
- **Lightweight / 轻量级**: Only ffmpeg + python3. Zero pip dependencies. Zero local model downloads (tesseract/whisper.cpp optional)
- **Focused / 专注**: "看懂" (understanding) is the single goal
- **Agent-friendly / Agent友好**: Structured JSON output (local) or Markdown report (vision), clear structure, cache for resume

## 📝 Notes / 注意事项

- **Local mode is the default** — always try `--local` first before reaching for `--vision`
- Local mode outputs structured JSON (`perception.json`) that any AI agent can read and summarize
- 🆕 `--vision` in local mode adds AI-powered `vision_description` to each segment alongside computational analysis
- Vision mode frame analysis results are cached — re-running picks up where it left off
- Transcription auto-fallback: whisper.cpp (local) → OpenAI Whisper API → skip gracefully
- OCR requires `tesseract` (`brew install tesseract`). Gracefully skips if unavailable.
- Face detection uses ffmpeg's built-in `facedetect` filter — no extra deps
- Ollama requires `ollama pull llava` (or preferred vision model) before first use
- For videos >30 min, increase `--interval` or reduce `--max-frames` (vision mode)

## 🔧 Requirements / 依赖

- **ffmpeg** + **ffprobe**: `brew install ffmpeg` or `apt install ffmpeg`
- **python3**: Standard library only — no pip installs needed
- **API key** (vision mode only): One of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` (none for Ollama)
- **Optional / 可选**: `tesseract` (OCR), `whisper-cpp` (local transcription)

## 📄 License / 许可证

MIT
