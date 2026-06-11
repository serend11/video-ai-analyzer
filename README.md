# Video AI Analyzer v3.2

> **"Whisper for video"** — Let your agent perceive video content.
> **"视频领域的 Whisper"** — 让你的 agent 能看懂视频内容。

Dual-mode video perception engine / 双模式视频感知引擎：
- **🏠 Local mode (DEFAULT) / 本地模式（默认）**: Scene detection + color/brightness/motion analysis + OCR + face detection + transcription — **zero API cost, zero privacy loss**
- **🤖 AI Vision mode (opt-in) / AI视觉模式（可选）**: Extract frames → GPT-4V/Claude/Gemini describe each frame → AI-generated summary
- **🆕 AI image recognition in local mode / 本地模式识图**: Add `--vision` to local mode for AI-powered frame descriptions alongside computational analysis

---

## 🆕 What's New in v3.2 / v3.2 新特性

- **🆕 AI image recognition for local mode / 本地模式识图**: `--vision` flag adds AI-powered `vision_description` to each segment
- **Shared utility module / 共享工具模块**: Extracted `common.py` — eliminated ~150 lines of duplicate code
- **Code cleanup / 代码清理**: Removed dead code (unused imports, functions, parameters), fixed return type annotations
- **Bug fix / Bug修复**: Fixed outdated error prefix check in `analyze.sh`

## 🚀 Quick Start / 快速开始

```bash
# ─── Local mode (DEFAULT, zero API cost) ───────────
# ─── 本地模式（默认，零API费用）───────────────────
./scripts/analyze.sh meeting.mp4
# Output / 输出: perception.json + report.md

# ─── Local + AI image recognition (NEW!) ────────────
# ─── 本地 + AI识图（新功能！）─────────────────────
export OPENAI_API_KEY="sk-..."
./scripts/analyze.sh video.mp4 --vision --vision-provider openai

# ─── Local + transcription ─────────────────────────
# ─── 本地 + 语音转写 ────────────────────────────
./scripts/analyze.sh lecture.mp4 --transcribe --language zh

# ─── AI Vision mode (needs API key) ────────────────
# ─── AI视觉模式（需要API密钥）────────────────────
export OPENAI_API_KEY="sk-..."
./scripts/analyze.sh product-demo.mp4 --vision --provider openai
```

## ✨ v3 Features / v3 特性

- **🏠 Local Perception Mode (DEFAULT) / 本地感知模式**: Scene detection + color palette + brightness + motion + face detection + OCR — no AI API needed
- **Whisper-like JSON output / Whisper风格输出**: Structured time-stamped segments any AI agent can consume
- **Dual-mode architecture / 双模式**: `--local` (default, free) → `--vision` (AI-powered)
- **Local-first transcription / 本地优先转写**: whisper.cpp (local) → OpenAI Whisper API (fallback)
- **Scene-aware sampling / 场景感知采样**: Intelligent scene-change detection
- **All v2 vision features / 完整v2功能**: Multi-provider, parallel, caching, retry, cost estimation

## 🏗️ Supported Modes / 支持的模式

| Mode / 模式 | Command / 命令 | Cost / 费用 | API Key |
|------|------|------|-------------|
| **Local perception (default) / 本地感知** | `analyze.sh video.mp4` | **Free / 免费** | ❌ |
| 🆕 **Local + AI recognition / 本地+识图** | `analyze.sh video.mp4 --vision` | Pay-as-you-go | ✅ |
| AI Vision / AI视觉 | `analyze.sh video.mp4 --vision --provider openai` | Pay-as-you-go | ✅ |

### Local Mode Capabilities / 本地模式能力

| Feature / 功能 | Dependency / 依赖 | Description / 说明 |
|------|------|------|
| Scene detection / 场景检测 | ffmpeg | Auto-detect scene change points |
| Color analysis / 色彩分析 | ffmpeg | Dominant color palette + warm/cool tone |
| Brightness analysis / 亮度分析 | ffmpeg | Per-segment brightness evaluation |
| Motion estimation / 运动估计 | ffmpeg | Scene change magnitude |
| OCR text recognition / 文字识别 | tesseract (optional) | Extract text from frames |
| Face detection / 人脸检测 | ffmpeg facedetect | Count faces per segment |
| Audio transcription / 语音转写 | whisper.cpp → OpenAI fallback | Local-first transcription |
| 🆕 AI image recognition / AI识图 | OpenAI/Claude/Gemini/Ollama | AI-powered frame descriptions |

## 🏗️ AI Vision Providers / AI视觉提供商

| Provider / 提供商 | Default Vision Model | Default Summary Model | Auth / 认证 |
|----------|------------|------------|------|
| `openai` | `gpt-4o` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic` | `claude-3-5-sonnet-20241022` | `claude-3-5-haiku-20241022` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.0-flash-exp` | `gemini-2.0-flash-exp` | `GOOGLE_API_KEY` |
| `ollama` | `llava` | Same | None (local) |
| `openai-compatible` | `gpt-4o` | Same | `OPENAI_API_KEY` |

## 📖 More Examples / 更多示例

```bash
# ─── Local mode / 本地模式 ─────────────────────────────
./scripts/analyze.sh meeting.mp4                                    # Default local perception
./scripts/analyze.sh lecture.mp4 --transcribe --language zh         # + Chinese transcription
./scripts/analyze.sh video.mp4 --no-ocr --scene-threshold 0.5       # No OCR, adjust sensitivity
./scripts/analyze.sh video.mp4 --vision --vision-provider openai    # 🆕 + AI image recognition

# ─── AI Vision mode / AI视觉模式 ──────────────────────────
./scripts/analyze.sh product-demo.mp4 --vision --provider openai
./scripts/analyze.sh video.mp4 --vision --provider anthropic
./scripts/analyze.sh lecture.mp4 --vision --provider google --language zh
./scripts/analyze.sh demo.mp4 --vision --provider ollama --model llava
./scripts/analyze.sh clip.mp4 --vision --provider openai-compatible \
  --base-url https://api.deepseek.com --model deepseek-chat

# ─── Sparse sampling for long videos / 长视频稀疏采样 ──
./scripts/analyze.sh movie.mp4 --vision --interval 60 --max-frames 15 --no-transcribe
```

## 📋 Output Structure / 输出结构

### Local Mode / 本地模式
```
video-analysis-{name}-{timestamp}/
├── perception.json        # Structured perception data (Whisper-style segments)
│                          # 🆕 Includes vision_description when --vision is used
└── report.md              # Human-readable Markdown report
```

### AI Vision Mode / AI视觉模式
```
video-analysis-{name}-{timestamp}/
├── report.md              # Comprehensive report with AI summary
├── transcript.txt         # Whisper transcription text
├── frames/                # Extracted frame images
└── frame-analysis/        # Per-frame AI descriptions (cached)
```

## 🔄 Workflow / 工作流程

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
  Scene     Frame   Frame   Frame     Duration/
  Detection Extract Extract Extract   Resolution
    │         │     │      │
    ▼         ▼     ▼      ▼
  Color     Motion Vision AI  Whisper
  Analysis          (parallel) (local-first)
    │         │     │      │
    ▼         ▼     ▼      ▼
  OCR+Face  Synthe- Frame   Transcript
            size   Descriptions
    │         │     │      │
    ▼         ▼     ▼      ▼
  🆕 AI Vision (--vision flag)
    │
    └────┬────┘     └──┬───┘
         ▼             ▼
   perception.json  report.md
```

## 🎨 Design Philosophy / 设计哲学

- **Local-first / 本地优先**: Default mode uses zero API — all processing runs locally
- **Dual-mode / 双模式**: `--local` for free perception, `--vision` for AI deep analysis
- **Multi-Provider / 多提供商**: Vision mode supports OpenAI, Anthropic, Google, Ollama, compatible APIs
- **Lightweight / 轻量级**: Only ffmpeg + python3 needed. Zero pip dependencies
- **Focused / 专注**: "Understanding video" is the single goal
- **Agent-friendly / Agent友好**: Structured JSON or Markdown, clear structure, cache for resume

## 🔧 Requirements / 依赖

- **ffmpeg** + **ffprobe**: `brew install ffmpeg` or `apt install ffmpeg`
- **python3**: Standard library only — no pip installs
- **API key** (vision mode only): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`
- **Optional / 可选**: `tesseract` (OCR), `whisper-cpp` (local transcription)

## 📂 Project Structure / 项目结构

```
video-ai-analyzer/
├── SKILL.md                # Skill definition / 技能定义
├── README.md               # Documentation / 文档 (zh/en bilingual)
├── VERSION                 # Version number / 版本号
├── LICENSE                 # MIT License
├── scripts/
│   ├── analyze.sh          # Main entry point / 主入口脚本
│   ├── common.py           # 🆕 Shared utilities / 共享工具模块
│   ├── local-perceive.py   # Local perception engine / 本地感知引擎
│   ├── call-ai.py          # Multi-provider AI API client / 多提供商API客户端
│   ├── generate-report.py  # Report generator / 报告生成器
│   ├── transcribe-audio.py # Audio transcription / 音频转录
│   └── batch-run.py        # Parallel job runner / 并行任务执行器
├── references/
│   └── frame-prompt.md     # AI frame description prompt / AI帧描述提示词
└── tests/
    ├── conftest.py
    ├── test_errors.py
    ├── test_providers.py
    └── test_retry.py
```

## 📄 License / 许可证

MIT
