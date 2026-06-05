# Video AI Analyzer v2

AI-powered video content understanding — extracts frames, analyzes with vision AI (multi-provider), transcribes with Whisper, generates structured report with **auto-generated summary**.

> **New in v2**: Multi-provider support (OpenAI, Anthropic, Google, Ollama, OpenAI-compatible), parallel frame analysis, automatic summary generation, retry logic, cost estimation.

## ✨ Features

- **Multi-Provider Vision**: OpenAI GPT-4V/GPT-4o, Anthropic Claude, Google Gemini, Ollama, any OpenAI-compatible
- **Parallel Frame Analysis**: Configurable concurrency (default 5× speedup)
- **Auto Summary**: AI-generated comprehensive summary after frame analysis (no more placeholder!)
- **Cost Control**: `--max-frames` and `--interval` precisely control API usage
- **Frame Caching**: Re-running picks up where it left off — no duplicate API calls
- **Retry Logic**: Exponential backoff on rate limits and transient errors
- **Audio Transcription**: Whisper API with multi-language support

## Quick Start

```bash
# Set your API key
export OPENAI_API_KEY="sk-..."
# Or: ANTHROPIC_API_KEY / GOOGLE_API_KEY (ollama needs no key)

# Analyze a video
./scripts/analyze.sh video.mp4

# Use a different provider
./scripts/analyze.sh video.mp4 --provider anthropic

# Local models (zero API cost)
./scripts/analyze.sh video.mp4 --provider ollama --model llava
```

## Supported Providers

| Provider | Auth | Default Model | 
|----------|------|---------------|
| `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-20241022` |
| `google` | `GOOGLE_API_KEY` | `gemini-2.0-flash-exp` |
| `ollama` | None (local) | `llava` |
| `openai-compatible` | `OPENAI_API_KEY` | `gpt-4o` |

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--provider NAME` | `openai` | AI provider |
| `--model MODEL` | per-provider | Vision model |
| `--summary-model M` | cheaper variant | Summary model |
| `--interval N` | `10` | Seconds between frames |
| `--max-frames N` | `20` | Max frames (cost control) |
| `--out DIR` | auto | Output directory |
| `--no-transcribe` | `false` | Skip audio |
| `--language LANG` | auto | Whisper language hint |
| `--parallel N` | `5` | Concurrent analyses |
| `--detail LEVEL` | `low` | Image detail (OpenAI) |
| `--base-url URL` | default | Custom API endpoint |

## Examples

```bash
# Basic analysis
./scripts/analyze.sh meeting.mp4

# Anthropic Claude
./scripts/analyze.sh video.mp4 --provider anthropic

# Google Gemini with Chinese language hint
./scripts/analyze.sh lecture.mp4 --provider google --language zh

# Local Ollama
./scripts/analyze.sh demo.mp4 --provider ollama --model llava

# DeepSeek (OpenAI-compatible)
./scripts/analyze.sh clip.mp4 --provider openai-compatible \
  --base-url https://api.deepseek.com --model deepseek-chat

# Long video: sparse sampling, skip transcription
./scripts/analyze.sh movie.mp4 --interval 60 --max-frames 15 --no-transcribe

# Fine-grained: fast parallel analysis
./scripts/analyze.sh product-demo.mp4 --interval 5 --max-frames 30 --parallel 10
```

## Output

```
video-analysis-{name}-{timestamp}/
├── report.md              # Full report (video info + transcript + frames + summary)
├── transcript.txt         # Whisper transcription
├── frames/                # Extracted frame images
│   └── frame_*.jpg
└── frame-analysis/        # Per-frame AI descriptions (cached)
    └── frame_*.txt
```

## Requirements

- **ffmpeg** + **ffprobe**: `brew install ffmpeg` or `apt install ffmpeg`
- **python3**: Standard library only — zero pip dependencies
- **API key**: One of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`

## Design Philosophy

- **Multi-Provider**: Not locked to any single LLM ecosystem
- **Lightweight**: Only ffmpeg + python3. Zero dependencies.
- **Focused**: Analysis only. "看懂" (understanding) is the single goal.
- **Comprehensive**: Vision + Audio + AI Summary for full comprehension
- **Cost-aware**: Full control over API usage
- **Agent-friendly**: Self-contained scripts, clear output, cache for resume

## License

MIT
