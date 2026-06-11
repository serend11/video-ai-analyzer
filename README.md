# Video AI Analyzer v3.2

Video perception engine that converts video files into structured, time-stamped data any AI agent can consume directly.

将视频文件转换为带时间戳的结构化数据，供 AI Agent 直接消费。

## How It Works / 工作原理

The pipeline extracts metadata, detects scene changes, captures key frames, and embeds them as base64 in the output. An AI agent reads the JSON, decodes the frames, and uses its own multimodal model to describe what it sees — no external vision API required.

流水线提取元数据、检测场景变化、捕获关键帧并以 base64 嵌入输出。AI Agent 读取 JSON，解码帧图片，用自身的多模态模型直接理解画面内容——无需外部视觉 API。

### Agent-Native Vision / Agent 原生视觉

Each segment in `perception.json` contains `frame_base64` (JPEG image encoded as base64) and `frame_mime`. The agent reads these fields directly and applies its built-in vision capability. This is the primary analysis path — local computational analysis (color, brightness, motion, OCR, face detection) supplements the agent's own visual understanding.

`perception.json` 中每个分段包含 `frame_base64`（JPEG 图片的 base64 编码）和 `frame_mime`。Agent 直接读取这些字段，用内置的视觉能力理解画面。这是主要的分析路径——本地计算分析（色彩、亮度、运动、OCR、人脸检测）作为补充数据。

### Analysis Capabilities / 分析能力

| Capability / 能力 | Method / 方法 | Dependency / 依赖 |
|---|---|---|
| Scene detection / 场景检测 | ffmpeg scene filter | ffmpeg |
| Color palette / 色彩调色板 | ffmpeg palettegen | ffmpeg |
| Brightness analysis / 亮度分析 | Perceptual luminance | ffmpeg |
| Motion estimation / 运动估计 | Frame-difference scoring | ffmpeg |
| Face detection / 人脸检测 | ffmpeg facedetect | ffmpeg |
| OCR text extraction / 文字识别 | tesseract | tesseract (optional) |
| Audio transcription / 语音转写 | whisper.cpp -> OpenAI fallback | whisper.cpp (optional) |
| Visual understanding / 视觉理解 | Agent reads frame_base64 | Agent's own model |
| AI frame description / AI 帧描述 | call-ai.py subprocess | API key (optional) |

### Output Format / 输出格式

Local mode produces a single `perception.json` file with this structure:

```json
{
  "engine": "video-ai-analyzer-local",
  "version": "3.2.0",
  "video": {
    "file": "demo.mp4",
    "duration_sec": 120.5,
    "video": {"codec": "h264", "resolution": "1920x1080", "fps": 30.0}
  },
  "segments": [
    {
      "index": 0,
      "start": 0.0, "end": 12.5,
      "start_fmt": "00:00:00", "end_fmt": "00:00:12",
      "frame_base64": "/9j/4AAQSkZJRg...",
      "frame_mime": "image/jpeg",
      "scene": {
        "brightness": 0.72,
        "dominant_colors": ["#2a3f5c", "#e8d5b7"],
        "motion": 0.03,
        "faces_detected": 1
      },
      "ocr": [{"text": "Welcome", "confidence": 92}],
      "description": "1 face detected. moderately lit scene. cool tones dominate."
    }
  ],
  "transcript": {"engine": "openai-whisper", "text": "..."}
}
```

## Quick Start / 快速开始

```bash
# Default: local perception with embedded frame images
./scripts/analyze.sh meeting.mp4

# With transcription (Chinese lecture example)
./scripts/analyze.sh lecture.mp4 --transcribe --language zh

# With external AI vision (requires API key)
export OPENAI_API_KEY="sk-..."
./scripts/analyze.sh product-demo.mp4 --vision --provider openai

# Long video, sparse sampling
./scripts/analyze.sh movie.mp4 --vision --interval 60 --max-frames 15
```

## Installation / 安装

Requirements: `ffmpeg`, `ffprobe`, `python3` (standard library only, no pip packages).

依赖: `ffmpeg`、`ffprobe`、`python3`（仅标准库，无需 pip 安装）。

```bash
# macOS
brew install ffmpeg

# Optional / 可选
brew install tesseract          # for OCR
brew install whisper-cpp        # for local transcription
```

## Supported AI Providers / 支持的 AI 提供商

For external vision mode (`--vision` flag), the following providers are supported:

| Provider | Default Model | Auth |
|----------|--------------|------|
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `anthropic` | `claude-3-5-sonnet-20241022` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.0-flash-exp` | `GOOGLE_API_KEY` |
| `ollama` | `llava` | None (local) |
| `openai-compatible` | `gpt-4o` | `OPENAI_API_KEY` |

## Command Line Reference / 命令行参考

```
analyze.sh <video> [options]

Options / 参数:
  --out DIR               Output directory (default: ./video-analysis-{name}-{ts})
  --transcribe            Enable audio transcription
  --language LANG         Language hint (zh, en, ja, etc.)
  --format FORMAT         Output format: json | markdown (default: json)
  --no-ocr                Disable OCR text extraction
  --scene-threshold N     Scene detection sensitivity 0-1 (default: 0.3)
  --max-segments N        Maximum scene segments (default: 50)
  --config FILE           Config file path

Vision mode / 视觉模式:
  --vision                Enable AI vision recognition
  --provider NAME         AI provider (default: openai)
  --model MODEL           Vision model name
  --interval N            Seconds between frame captures (default: 10)
  --max-frames N          Maximum frames to analyze (default: 20)
  --parallel N            Concurrent frame analyses (default: 5)
  --no-transcribe         Skip audio transcription
  --no-summary            Skip AI-generated summary
  --detail LEVEL          Image detail: low | high | auto (OpenAI only)
```

## Project Structure / 项目结构

```
video-ai-analyzer/
├── SKILL.md                # Agent skill definition
├── README.md               # This file
├── VERSION
├── LICENSE                 # MIT
├── scripts/
│   ├── analyze.sh          # Main entry point
│   ├── common.py           # Shared utilities (run, has_cmd, transcription)
│   ├── local-perceive.py   # Local perception engine
│   ├── call-ai.py          # Multi-provider AI API client
│   ├── generate-report.py  # Report generator (Markdown/JSON)
│   ├── transcribe-audio.py # Standalone audio transcription
│   └── batch-run.py        # Parallel job runner
├── references/
│   └── frame-prompt.md     # AI frame description prompt
└── tests/
    ├── conftest.py
    ├── test_errors.py
    ├── test_providers.py
    └── test_retry.py
```

## Design Decisions / 设计决策

- **Local-first / 本地优先**: Default mode uses zero external APIs. All computational analysis runs locally via ffmpeg and python3 stdlib.
- **Agent-native vision / Agent 原生视觉**: Frame images are embedded as base64 in the output JSON. The agent reads them directly — no separate vision API call needed.
- **Structured output / 结构化输出**: All data follows a consistent JSON schema with time-stamped segments, making it trivial for any agent to parse and summarize.
- **Zero pip dependencies / 零 pip 依赖**: Only python3 standard library. No requirements.txt needed.
- **Graceful degradation / 优雅降级**: OCR, face detection, and transcription are optional. The pipeline continues if any tool is unavailable.
- **Frame caching / 帧缓存**: In vision mode, previously analyzed frames are skipped on re-run.

## License / 许可证

MIT
