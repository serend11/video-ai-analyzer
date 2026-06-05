# Video AI Analyzer

AI-powered video content understanding — extracts frames, analyzes with GPT-4V, transcribes with Whisper, generates structured report.

## Features

- **Frame Extraction**: Automatically sample key frames at configurable intervals
- **Visual Analysis**: GPT-4V/GPT-4o analyzes each frame for scene understanding
- **Audio Transcription**: Whisper API transcribes speech with multi-language support
- **Structured Report**: Generates a comprehensive Markdown report with video info, transcript, scene analysis, and summary

## Quick Start

```bash
# Set API key
export OPENAI_API_KEY="sk-..."

# Analyze a video
./scripts/analyze.sh video.mp4
```

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
./scripts/analyze.sh meeting.mp4

# Fine-grained analysis for a short clip
./scripts/analyze.sh demo.mp4 --interval 5 --max-frames 30

# Chinese video with language hint
./scripts/analyze.sh lecture.mp4 --language zh

# Long video: sparse sampling, skip transcription
./scripts/analyze.sh movie.mp4 --interval 60 --max-frames 15 --no-transcribe
```

## Requirements

- **ffmpeg** + **ffprobe**: `brew install ffmpeg` or `apt install ffmpeg`
- **python3**: For the Vision API helper (no pip dependencies needed)
- **OPENAI_API_KEY**: Required for GPT-4V and Whisper API calls

## Output

The tool generates:

```
video-analysis-{name}-{timestamp}/
├── report.md           # Comprehensive analysis report
├── transcript.txt      # Whisper transcription
├── frames/             # Extracted frame images
│   ├── frame_0000_000000.jpg
│   ├── frame_0001_000010.jpg
│   └── ...
└── frame-analysis/     # Per-frame GPT-4V descriptions
    ├── frame_0000_000000.txt
    ├── frame_0001_000010.txt
    └── ...
```

## License

MIT
