#!/usr/bin/env bash
set -euo pipefail

# ─── Video AI Analyzer v3 ─────────────────────────────────────────────
# Perceive video content without AI vision API — "Whisper for video"
#
# Default: local perception (scene detection + color/motion + OCR + transcript)
# Opt-in:  AI vision mode via --vision (GPT-4V / Claude / Gemini)
# ─────────────────────────────────────────────────────────────────────

VERSION="3.2.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPT_FILE="${SCRIPT_DIR}/../references/frame-prompt.md"
CALL_AI="${SCRIPT_DIR}/call-ai.py"
LOCAL_PERCEIVE="${SCRIPT_DIR}/local-perceive.py"
TRANSCRIBE_AUDIO="${SCRIPT_DIR}/transcribe-audio.py"
GENERATE_REPORT="${SCRIPT_DIR}/generate-report.py"

# ─── Usage ───────────────────────────────────────────────────────────

usage() {
  cat >&2 <<'EOF'
Video AI Analyzer — Local video perception (no AI API required)

Usage:
  analyze.sh <video-file> [options]

Modes:
  --local              Local perception (DEFAULT): scene detection, color/motion,
                       optional OCR (tesseract), optional transcription.
                       Zero cost, zero privacy loss, no API key needed.
  --vision             AI vision mode: extract frames → GPT-4V/Claude/Gemini
                       describe each frame. Requires API key.

Common options:
  --out DIR            Output directory (default: ./video-analysis-{name}-{ts})
  --transcribe         Enable audio transcription (needs whisper.cpp or OpenAI API)
  --language LANG      Language hint for transcription (e.g., zh, en, ja)
  --format FORMAT      Output format: json|markdown (default: json for local, markdown for vision)
  --no-ocr             Disable OCR text extraction in local mode
  --config FILE        Config file path (auto-discover by default)

Local mode options (--local, default):
  --scene-threshold N  Scene detection sensitivity 0-1 (default: 0.3)
  --max-segments N     Max scene segments (default: 50)

AI vision mode options (--vision):
  --provider NAME      AI provider: openai|anthropic|google|ollama|openai-compatible
  --model MODEL        Vision model name
  --interval N         Seconds between frame captures (default: 10)
  --max-frames N       Max frames to analyze (default: 20)
  --no-transcribe      Skip audio transcription (in vision mode)
  --no-summary         Skip AI-generated summary
  --parallel N         Max concurrent frame analyses (default: 5)
  --detail LEVEL       Image detail: low|high|auto (OpenAI only)

Environment:
  Local mode:         None required (ffmpeg + python3 only)
  Vision mode:        Depends on provider (see --help --vision for details)

Examples:
  # Default local perception (zero cost, zero API)
  analyze.sh meeting.mp4

  # Local with transcription
  analyze.sh lecture.mp4 --transcribe --language zh

  # AI vision mode (needs API key)
  analyze.sh product-demo.mp4 --vision --provider openai

  # AI vision with Anthropic Claude
  analyze.sh video.mp4 --vision --provider anthropic
EOF
  exit 2
}

# ─── Helpers ──────────────────────────────────────────────────────────

dim()  { echo -e "\033[2m$*\033[0m"; }
bold() { echo -e "\033[1m$*\033[0m"; }

require_env() {
  local key="$1"
  if [[ "${!key:-}" == "" ]]; then
    echo "Error: ${key} is not set" >&2
    echo "  export ${key}=\"your-key\"" >&2
    exit 1
  fi
}

# ─── Config file support ──────────────────────────────────────────────

# Discover and load a .video-ai-analyzer.yaml config file.
# Search order: explicit --config path > ./.video-ai-analyzer.yaml >
# parent dirs (up 3 levels) > ~/.config/video-ai-analyzer/config.yaml
find_config() {
  local explicit="${1:-}"

  if [[ -n "$explicit" && -f "$explicit" ]]; then
    echo "$explicit"
    return 0
  elif [[ -n "$explicit" ]]; then
    echo "Warning: Config file not found: $explicit" >&2
  fi

  # Check current & parent dirs
  local dir="$PWD"
  for _ in 1 2 3 4; do
    for name in ".video-ai-analyzer.yaml" ".video-ai-analyzer.yml"; do
      if [[ -f "$dir/$name" ]]; then
        echo "$dir/$name"
        return 0
      fi
    done
    dir="$(dirname "$dir")"
    [[ "$dir" == "/" ]] && break
  done

  # Check user config dir
  local user_config="$HOME/.config/video-ai-analyzer/config.yaml"
  if [[ -f "$user_config" ]]; then
    echo "$user_config"
    return 0
  fi

  return 1
}

# Load flat key:value YAML config into shell variables prefixed with CFG_
# Only handles simple string/number values (one level, no nesting).
load_config() {
  local file="$1"
  local key val

  while IFS=: read -r key val; do
    # Skip comments, empty lines, and sections
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$(echo "$key" | tr -d '[:space:]')" ]] && continue
    [[ "$key" =~ ^[[:space:]]*--- ]] && continue

    # Trim whitespace
    key=$(echo "$key" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    val=$(echo "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

    # Remove surrounding quotes if present
    val="${val#\"}"; val="${val%\"}"
    val="${val#\'}"; val="${val%\'}"

    case "$key" in
      provider)        CFG_PROVIDER="$val" ;;
      model)           CFG_MODEL="$val" ;;
      summary_model)   CFG_SUMMARY_MODEL="$val" ;;
      interval)        CFG_INTERVAL="$val" ;;
      max_frames)      CFG_MAX_FRAMES="$val" ;;
      output_dir)      CFG_OUT="$val" ;;
      transcribe)      CFG_TRANSCRIBE="$val" ;;
      language)        CFG_LANGUAGE="$val" ;;
      detail)          CFG_DETAIL="$val" ;;
      max_tokens)      CFG_FRAME_MAX_TOKENS="$val" ;;
      temperature)     CFG_TEMPERATURE="$val" ;;
      parallel)        CFG_MAX_PARALLEL="$val" ;;
      base_url)        CFG_BASE_URL="$val" ;;
      format)          CFG_FORMAT="$val" ;;
    esac
  done < "$file"
}

# ─── Parse arguments ──────────────────────────────────────────────────

# Handle flags that don't need a video file
if [[ "${1:-}" == "--version" ]]; then
  echo "Video AI Analyzer v${VERSION}"
  exit 0
fi
if [[ "${1:-}" == "" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
fi

IN="$1"
shift

PROVIDER="openai"
MODEL=""
SUMMARY_MODEL=""
INTERVAL=10
MAX_FRAMES=20
OUT=""
TRANSCRIBE=false
NO_SUMMARY=false
LANGUAGE=""
DETAIL="low"
FRAME_MAX_TOKENS=500
SUMMARY_MAX_TOKENS=2000
TEMPERATURE=0.7
MAX_PARALLEL=5
BASE_URL=""
FORMAT="markdown"
CONFIG_FILE=""
MODE="local"
SCENE_THRESHOLD="0.3"
MAX_SEGMENTS=50
OCR_ENABLED=true
VISION_ENABLED=false
VISION_PROVIDER="openai"
VISION_MODEL=""
VISION_MAX_TOKENS=300

# ─── Load config file (before CLI args so CLI can override) ───────────

CONFIG_PATH=$(find_config "$CONFIG_FILE") || true
if [[ -n "$CONFIG_PATH" ]]; then
  load_config "$CONFIG_PATH"
  # Apply config values as defaults (only if not already set by explicit args...)
  # We set them BEFORE the while loop but after defaults, so CLI args win
  PROVIDER="${CFG_PROVIDER:-$PROVIDER}"
  MODEL="${CFG_MODEL:-$MODEL}"
  SUMMARY_MODEL="${CFG_SUMMARY_MODEL:-$SUMMARY_MODEL}"
  INTERVAL="${CFG_INTERVAL:-$INTERVAL}"
  MAX_FRAMES="${CFG_MAX_FRAMES:-$MAX_FRAMES}"
  OUT="${CFG_OUT:-$OUT}"
  TRANSCRIBE="${CFG_TRANSCRIBE:-$TRANSCRIBE}"
  # Normalize boolean strings from YAML
  case "${TRANSCRIBE,,}" in
    false|off|no|0) TRANSCRIBE=false ;;
    true|on|yes|1)  TRANSCRIBE=true ;;
  esac
  LANGUAGE="${CFG_LANGUAGE:-$LANGUAGE}"
  DETAIL="${CFG_DETAIL:-$DETAIL}"
  FRAME_MAX_TOKENS="${CFG_FRAME_MAX_TOKENS:-$FRAME_MAX_TOKENS}"
  TEMPERATURE="${CFG_TEMPERATURE:-$TEMPERATURE}"
  MAX_PARALLEL="${CFG_MAX_PARALLEL:-$MAX_PARALLEL}"
  BASE_URL="${CFG_BASE_URL:-$BASE_URL}"
  FORMAT="${CFG_FORMAT:-$FORMAT}"
  dim "   📄 Config: ${CONFIG_PATH}"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider)        PROVIDER="${2:-openai}"; shift 2 ;;
    --model)           MODEL="${2:-}"; shift 2 ;;
    --summary-model)   SUMMARY_MODEL="${2:-}"; shift 2 ;;
    --interval)        INTERVAL="${2:-10}"; shift 2 ;;
    --max-frames)      MAX_FRAMES="${2:-20}"; shift 2 ;;
    --out)             OUT="${2:-}"; shift 2 ;;
    --no-transcribe)   TRANSCRIBE=false; shift ;;
    --language)        LANGUAGE="${2:-}"; shift 2 ;;
    --detail)          DETAIL="${2:-low}"; shift 2 ;;
    --max-tokens)      FRAME_MAX_TOKENS="${2:-500}"; shift 2 ;;
    --temperature)     TEMPERATURE="${2:-0.7}"; shift 2 ;;
    --parallel)        MAX_PARALLEL="${2:-5}"; shift 2 ;;
    --base-url)        BASE_URL="${2:-}"; shift 2 ;;
    --config)           CONFIG_FILE="${2:-}"; shift 2 ;;
    --format)           FORMAT="${2:-markdown}"; shift 2 ;;
    --mode)             MODE="${2:-local}"; shift 2 ;;
    --local)            MODE="local"; shift ;;
    --vision)           VISION_ENABLED=true; shift ;;
    --vision-provider)  VISION_PROVIDER="${2:-openai}"; shift 2 ;;
    --vision-model)     VISION_MODEL="${2:-}"; shift 2 ;;
    --vision-max-tokens) VISION_MAX_TOKENS="${2:-300}"; shift 2 ;;
    --no-summary)       NO_SUMMARY=true; shift ;;
    --transcribe)       TRANSCRIBE=true; shift ;;
    --scene-threshold)  SCENE_THRESHOLD="${2:-0.3}"; shift 2 ;;
    --max-segments)     MAX_SEGMENTS="${2:-50}"; shift 2 ;;
    --no-ocr)           OCR_ENABLED=false; shift ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

# ─── Validate inputs ──────────────────────────────────────────────────

if [[ ! -f "$IN" ]]; then
  echo "Error: Video file not found: $IN" >&2
  exit 1
fi

# Check required binaries
for cmd in ffmpeg ffprobe python3; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: Required command not found: $cmd" >&2
    exit 1
  fi
done

# ─── Route to pipeline ────────────────────────────────────────────────

# --vision without --local means full vision mode (extract frames + AI)
if $VISION_ENABLED && [[ "$MODE" != "local" ]]; then
  MODE="vision"
fi

if [[ "$MODE" == "local" ]]; then
  echo ""
  bold "🎬 Video AI Analyzer v${VERSION} — Local Perception Mode"
  dim "   Zero API cost · Zero privacy loss · Pure local processing"
  echo ""

  # Setup output
  if [[ "$OUT" == "" ]]; then
    BASENAME="$(basename "$IN")"
    NAME="${BASENAME%.*}"
    TS="$(date +%Y%m%d-%H%M%S)"
    OUT="./video-analysis-${NAME}-${TS}"
  fi
  mkdir -p "$OUT"

  # Default to JSON for local mode (unless user explicitly requested markdown)
  if [[ "$FORMAT" == "markdown" ]]; then
    FORMAT="json"
  fi

  # Build local-perceive arguments
  LP_ARGS=("$LOCAL_PERCEIVE" "$IN" "--out" "$OUT/perception.json"
           "--scene-threshold" "$SCENE_THRESHOLD"
           "--max-segments" "$MAX_SEGMENTS")

  ${OCR_ENABLED:-true} || LP_ARGS+=("--no-ocr")
  $TRANSCRIBE && LP_ARGS+=("--transcribe")
  [[ "$LANGUAGE" != "" ]] && LP_ARGS+=("--language" "$LANGUAGE")

  # Pass vision args to local-perceive.py for AI image recognition
  if $VISION_ENABLED; then
    LP_ARGS+=("--vision")
    [[ -n "${VISION_PROVIDER:-}" ]] && LP_ARGS+=("--vision-provider" "$VISION_PROVIDER")
    [[ -n "${VISION_MODEL:-}" ]] && LP_ARGS+=("--vision-model" "$VISION_MODEL")
    LP_ARGS+=("--vision-max-tokens" "$VISION_MAX_TOKENS")
  fi

  "${LP_ARGS[@]}"

  # Generate human-readable report from perception.json
  REPORT_EXT="md"
  if [[ "$FORMAT" == "json" ]]; then
    REPORT_EXT="json"
  fi
  REPORT="$OUT/report.${REPORT_EXT}"

  "$GENERATE_REPORT" \
    --mode local \
    --perception-file "$OUT/perception.json" \
    --video-file "$IN" \
    --format "$FORMAT" \
    > "$REPORT"

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  bold "✅ 视频感知完成！（local mode）"
  echo ""
  echo "   📊 感知数据: $OUT/perception.json"
  echo "   📄 分析报告: $REPORT"
  echo ""
  echo "   💡 将 perception.json 提供给任何 AI Agent 来理解视频内容。"
  echo "   AI Agent 可以阅读 segments[].description 和 transcript。"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "$OUT"
  exit 0
fi

# ─── Vision mode: validate AI-specific inputs ─────────────────────────
if ! [[ "$INTERVAL" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --interval must be a positive integer (got: $INTERVAL)" >&2
  exit 1
fi
if ! [[ "$MAX_FRAMES" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --max-frames must be a positive integer (got: $MAX_FRAMES)" >&2
  exit 1
fi
if ! [[ "$MAX_PARALLEL" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --parallel must be a positive integer (got: $MAX_PARALLEL)" >&2
  exit 1
fi

# Check required binaries
for cmd in ffmpeg ffprobe python3; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: Required command not found: $cmd" >&2
    exit 1
  fi
done

# Check provider-specific API key
case "$PROVIDER" in
  openai|openai-compatible) require_env OPENAI_API_KEY ;;
  anthropic) require_env ANTHROPIC_API_KEY ;;
  google) require_env GOOGLE_API_KEY ;;
  ollama) ;;  # local, no key needed
  *) echo "Error: Unknown provider: $PROVIDER" >&2; exit 1 ;;
esac

# Transcription: local-first (whisper.cpp → OpenAI API). No API key strictly required
# if whisper.cpp is installed locally. We'll warn but allow it to proceed.
if $TRANSCRIBE; then
  if command -v whisper-cpp &>/dev/null || command -v whisper &>/dev/null; then
    dim "   🎙️  whisper.cpp detected — local transcription available"
  elif [[ "${OPENAI_API_KEY:-}" == "" ]]; then
    echo "⚠️  No local whisper.cpp found and OPENAI_API_KEY not set."
    echo "   Transcription may be unavailable. Install whisper.cpp or set OPENAI_API_KEY."
  fi
fi

# ─── Provider defaults ────────────────────────────────────────────────

case "$PROVIDER" in
  openai)
    MODEL="${MODEL:-gpt-4o}"
    SUMMARY_MODEL="${SUMMARY_MODEL:-gpt-4o-mini}"
    ;;
  anthropic)
    MODEL="${MODEL:-claude-3-5-sonnet-20241022}"
    SUMMARY_MODEL="${SUMMARY_MODEL:-claude-3-5-haiku-20241022}"
    ;;
  google)
    MODEL="${MODEL:-gemini-2.0-flash-exp}"
    SUMMARY_MODEL="${SUMMARY_MODEL:-gemini-2.0-flash-exp}"
    ;;
  ollama)
    MODEL="${MODEL:-llava}"
    SUMMARY_MODEL="${SUMMARY_MODEL:-$MODEL}"
    ;;
  openai-compatible)
    MODEL="${MODEL:-gpt-4o}"
    SUMMARY_MODEL="${SUMMARY_MODEL:-$MODEL}"
    ;;
esac

# Build base URL arg for call-ai.py
BASE_URL_ARG=""
if [[ "$BASE_URL" != "" ]]; then
  BASE_URL_ARG="--base-url $BASE_URL"
fi

# ─── Setup output directory ───────────────────────────────────────────

if [[ "$OUT" == "" ]]; then
  BASENAME="$(basename "$IN")"
  NAME="${BASENAME%.*}"
  TS="$(date +%Y%m%d-%H%M%S)"
  OUT="./video-analysis-${NAME}-${TS}"
fi

FRAMES_DIR="$OUT/frames"
ANALYSIS_DIR="$OUT/frame-analysis"
mkdir -p "$FRAMES_DIR" "$ANALYSIS_DIR"

echo ""
bold "🎬 Video AI Analyzer v${VERSION}"
dim "   Provider: ${PROVIDER} | Model: ${MODEL} | Summary: ${SUMMARY_MODEL}"
dim "   Interval: ${INTERVAL}s | Max frames: ${MAX_FRAMES} | Parallel: ${MAX_PARALLEL}"
dim "   Output: ${OUT}"
echo ""

# ─── Step 1: Get video metadata ──────────────────────────────────────

echo "📊 Extracting video metadata..."

DURATION_RAW=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$IN" 2>/dev/null || echo "0")
DURATION=$(printf "%.0f" "$DURATION_RAW" 2>/dev/null || echo "0")
DURATION_FMT=$(printf '%02d:%02d:%02d' $((DURATION/3600)) $(((DURATION%3600)/60)) $((DURATION%60)))

RESOLUTION=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$IN" 2>/dev/null || echo "unknown")
CODEC=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$IN" 2>/dev/null || echo "unknown")
FPS_RAW=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$IN" 2>/dev/null || echo "unknown")
if [[ "$FPS_RAW" != "unknown" && "$FPS_RAW" == *"/"* ]]; then
  FPS=$(echo "$FPS_RAW" | awk -F'/' '{printf "%.2f", $1/$2}' 2>/dev/null || echo "$FPS_RAW")
else
  FPS="$FPS_RAW"
fi
BITRATE=$(ffprobe -v quiet -show_entries format=bit_rate -of csv=p=0 "$IN" 2>/dev/null || echo "unknown")
if [[ "$BITRATE" != "unknown" ]]; then
  BITRATE="$(( BITRATE / 1000 )) kbps"
fi
FILESIZE=$(du -h "$IN" | cut -f1)
HAS_AUDIO=$(ffprobe -v quiet -select_streams a -show_entries stream=codec_name -of csv=p=0 "$IN" 2>/dev/null | head -1 || echo "none")

dim "   Duration: ${DURATION_FMT} | Resolution: ${RESOLUTION} | Codec: ${CODEC}"
dim "   FPS: ${FPS} | Bitrate: ${BITRATE} | Size: ${FILESIZE} | Audio: ${HAS_AUDIO}"

# ─── Step 2: Transcribe audio ────────────────────────────────────────

TRANSCRIPT_TEXT=""
TRANSCRIPT_FILE="$OUT/transcript.txt"

if $TRANSCRIBE && [[ "$HAS_AUDIO" != "" && "$HAS_AUDIO" != "none" ]]; then
  echo ""
  echo "🎙️  Transcribing (local-first: whisper.cpp → OpenAI API fallback)..."

  TRANS_LANG_ARGS=""
  if [[ "$LANGUAGE" != "" ]]; then
    TRANS_LANG_ARGS="--language $LANGUAGE"
  fi

  # Use local-first transcription engine
  python3 "$TRANSCRIBE_AUDIO" "$IN" $TRANS_LANG_ARGS --out "$TRANSCRIPT_FILE"

  if [[ -f "$TRANSCRIPT_FILE" && -s "$TRANSCRIPT_FILE" ]]; then
    TRANSCRIPT_TEXT=$(cat "$TRANSCRIPT_FILE")
    echo "   ✅ Transcription complete ($(wc -c < "$TRANSCRIPT_FILE" | tr -d ' ') chars)"
  else
    echo "   ⚠️  Transcription unavailable. Continuing without transcript."
    TRANSCRIPT_TEXT=""
  fi
else
  if ! $TRANSCRIBE; then
    echo ""
    echo "⏭️  Transcription skipped (--no-transcribe)"
  else
    echo ""
    echo "⏭️  No audio stream found, skipping transcription"
  fi
fi

# ─── Step 3: Extract frames ──────────────────────────────────────────

echo ""
echo "🖼️  Extracting frames every ${INTERVAL}s (max ${MAX_FRAMES})..."

FRAME_COUNT=$(( DURATION / INTERVAL ))
if [[ $FRAME_COUNT -gt $MAX_FRAMES ]]; then
  FRAME_COUNT=$MAX_FRAMES
  INTERVAL=$(( DURATION / MAX_FRAMES ))
fi
if [[ $FRAME_COUNT -lt 1 ]]; then
  FRAME_COUNT=1
fi

dim "   Will extract ${FRAME_COUNT} frames at ~${INTERVAL}s intervals"

declare -a FRAME_PATHS=()
declare -a FRAME_TIMES=()

for ((i=0; i<FRAME_COUNT; i++)); do
  SECONDS=$(( i * INTERVAL ))
  if [[ $SECONDS -ge $DURATION ]]; then
    SECONDS=$(( DURATION - 1 ))
  fi
  TIME_FMT=$(printf '%02d:%02d:%02d' $((SECONDS/3600)) $(((SECONDS%3600)/60)) $((SECONDS%60)))
  FRAME_PATH="$FRAMES_DIR/frame_$(printf '%04d' $i)_${TIME_FMT//:/}.jpg"
  
  ffmpeg -hide_banner -loglevel error -y \
    -ss "$TIME_FMT" -i "$IN" \
    -frames:v 1 -q:v 3 \
    "$FRAME_PATH" 2>/dev/null
  
  if [[ -f "$FRAME_PATH" ]]; then
    FRAME_PATHS+=("$FRAME_PATH")
    FRAME_TIMES+=("$TIME_FMT")
  fi
done

ACTUAL_FRAMES=${#FRAME_PATHS[@]}
echo "   ✅ Extracted ${ACTUAL_FRAMES} frames"

if [[ $ACTUAL_FRAMES -eq 0 ]]; then
  echo "Error: No frames extracted. Check the video file." >&2
  exit 1
fi

# ─── Cost estimate ────────────────────────────────────────────────────

echo ""
echo "💰 Estimated cost: ~${ACTUAL_FRAMES} vision API calls + 1 summary call"
dim "   Use --max-frames to control cost (current: ${MAX_FRAMES})"

# ─── Step 4: Analyze frames with AI (parallel) ─────────────────────────

echo ""
echo "🧠 Analyzing frames (${PROVIDER}/${MODEL}, parallel×${MAX_PARALLEL})..."

# Load frame analysis prompt
FRAME_PROMPT_DEFAULT="Describe this video frame in detail. What do you see? Include:
- The setting/environment
- People present and what they are doing
- Objects, text, or UI elements visible
- The mood or atmosphere
- Any notable details

Respond in the same language as the video content. Be concise but thorough."

FRAME_PROMPT="$FRAME_PROMPT_DEFAULT"
if [[ -f "$PROMPT_FILE" ]]; then
  FRAME_PROMPT=$(cat "$PROMPT_FILE")
fi

# Create temp prompt file for call-ai.py (handles multiline safely)
FRAME_PROMPT_TMP=$(mktemp /tmp/video-analyzer-prompt.XXXXXX)
echo "$FRAME_PROMPT" > "$FRAME_PROMPT_TMP"

# Build job list: only uncached frames
JOB_FILE=$(mktemp /tmp/video-analyzer-jobs.XXXXXX)
CACHED=0
NEW_JOBS=0

for ((i=0; i<ACTUAL_FRAMES; i++)); do
  FRAME_NAME="$(basename "${FRAME_PATHS[$i]}")"
  ANALYSIS_FILE="$ANALYSIS_DIR/${FRAME_NAME%.jpg}.txt"

  if [[ -f "$ANALYSIS_FILE" && -s "$ANALYSIS_FILE" ]]; then
    CACHED=$((CACHED + 1))
    continue  # skip cached
  fi

  echo "${FRAME_PATHS[$i]}|${FRAME_TIMES[$i]}|${ANALYSIS_FILE}" >> "$JOB_FILE"
  NEW_JOBS=$((NEW_JOBS + 1))
done

if [[ $CACHED -gt 0 ]]; then
  dim "   ⏭️  ${CACHED} frames cached, ${NEW_JOBS} to analyze"
fi

# Process jobs in parallel
if [[ $NEW_JOBS -gt 0 ]]; then
  # Write commands to a batch job file
  BATCH_FILE=$(mktemp /tmp/video-analyzer-batch.XXXXXX)
  while IFS='|' read -r FRAME_PATH FRAME_TIME ANALYSIS_FILE; do
    echo "\"$CALL_AI\" \"$FRAME_PATH\" --provider \"$PROVIDER\" --model \"$MODEL\" --prompt-file \"$FRAME_PROMPT_TMP\" --out \"$ANALYSIS_FILE\" --detail \"$DETAIL\" --max-tokens \"$FRAME_MAX_TOKENS\" --temperature \"$TEMPERATURE\" $BASE_URL_ARG" >> "$BATCH_FILE"
  done < "$JOB_FILE"

  "$SCRIPT_DIR/batch-run.py" --jobs "$BATCH_FILE" --parallel "$MAX_PARALLEL" || true
  rm -f "$BATCH_FILE"
fi

# Count actual successes
SUCCESS_COUNT=0
for ((i=0; i<ACTUAL_FRAMES; i++)); do
  FRAME_NAME="$(basename "${FRAME_PATHS[$i]}")"
  ANALYSIS_FILE="$ANALYSIS_DIR/${FRAME_NAME%.jpg}.txt"
  if [[ -f "$ANALYSIS_FILE" && -s "$ANALYSIS_FILE" ]]; then
    FIRST_LINE=$(head -1 "$ANALYSIS_FILE")
    if [[ "$FIRST_LINE" != "[AI analysis error:"* ]]; then
      SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    fi
  fi
done

echo "   ✅ Frame analysis: ${SUCCESS_COUNT}/${ACTUAL_FRAMES} succeeded"

# Cleanup
rm -f "$FRAME_PROMPT_TMP" "$JOB_FILE"

if [[ $SUCCESS_COUNT -eq 0 ]]; then
  echo ""
  echo "Error: All frame analyses failed. Check your API key and network." >&2
  echo "The analysis cannot proceed without at least one successful frame analysis." >&2
  exit 1
fi

# ─── Step 5: Generate report ──────────────────────────────────────────
#
# The report is now generated via generate-report.py, which supports both
# Markdown and JSON output formats.

echo ""
echo "📄 Generating report (format: ${FORMAT})..."

REPORT_EXT="md"
if [[ "$FORMAT" == "json" ]]; then
  REPORT_EXT="json"
fi
REPORT="$OUT/report.${REPORT_EXT}"

# ─── Step 6: Generate AI summary (before report, so it can be embedded) ───

SUMMARY_FINAL=""
if $NO_SUMMARY; then
  echo ""
  echo "⏭️  Summary skipped (--no-summary)"
else
echo ""
echo "🧠 Generating comprehensive summary (${SUMMARY_MODEL})..."

# Collect all frame analyses into a string for the summary prompt
SUMMARY_INPUT=$(mktemp /tmp/video-analyzer-summary-input.XXXXXX)
{
  echo "## Video Metadata"
  echo "- Duration: ${DURATION_FMT} (${DURATION}s)"
  echo "- Resolution: ${RESOLUTION}"
  echo "- Codec: ${CODEC}"
  echo "- FPS: ${FPS}"
  echo ""

  if [[ "$TRANSCRIPT_TEXT" != "" ]]; then
    echo "## Audio Transcript"
    echo "$TRANSCRIPT_TEXT"
    echo ""
  else
    echo "## Audio Transcript"
    echo "(No transcript available)"
    echo ""
  fi

  echo "## Frame-by-Frame Visual Analysis"
  echo ""
  for ((i=0; i<ACTUAL_FRAMES; i++)); do
    FRAME_TIME="${FRAME_TIMES[$i]}"
    FRAME_PATH="${FRAME_PATHS[$i]}"
    FRAME_NAME="$(basename "$FRAME_PATH")"
    ANALYSIS_FILE="$ANALYSIS_DIR/${FRAME_NAME%.jpg}.txt"

    echo "### Frame $((i+1)) — ${FRAME_TIME}"
    if [[ -f "$ANALYSIS_FILE" ]]; then
      cat "$ANALYSIS_FILE"
    else
      echo "(Analysis not available)"
    fi
    echo ""
  done
} > "$SUMMARY_INPUT"

# Build summary prompt
SUMMARY_PROMPT_FILE=$(mktemp /tmp/video-analyzer-summary-prompt.XXXXXX)
{
  echo "You are a video content analyst. Based on the following per-frame visual descriptions and audio transcript, write a comprehensive summary of the video."
  echo ""
  echo "Your summary should cover:"
  echo "1. **Overall Topic/Purpose**: What is this video about? What is its main subject?"
  echo "2. **Key Moments & Timeline**: What are the most important events or sections, in chronological order?"
  echo "3. **People & Setting**: Who appears? Where does it take place? What is the atmosphere?"
  echo "4. **Main Takeaways**: What are the key conclusions, messages, or learnings?"
  echo ""
  echo "Write the summary in the SAME LANGUAGE as the video content. If the video content is in Chinese, write the summary in Chinese. If English, write in English."
  echo "Be thorough but well-structured. Use clear section headings."
  echo ""
  echo "---"
  echo ""
  cat "$SUMMARY_INPUT"
} > "$SUMMARY_PROMPT_FILE"

# Call AI for summary (text-only mode)
SUMMARY_RESULT=$("$CALL_AI" \
  --provider "$PROVIDER" \
  --model "$SUMMARY_MODEL" \
  --prompt-file "$SUMMARY_PROMPT_FILE" \
  --text-only \
  --max-tokens "$SUMMARY_MAX_TOKENS" \
  --temperature 0.5 \
  $BASE_URL_ARG 2>&1)
SUMMARY_EXIT=$?

if [[ $SUMMARY_EXIT -eq 0 && "$SUMMARY_RESULT" != "" ]]; then
  SUMMARY_FINAL="$SUMMARY_RESULT"
  echo "   ✅ Summary generated"
else
  SUMMARY_FINAL="Summary generation failed: ${SUMMARY_RESULT}"
  echo "   ⚠️  Summary generation failed — embedding placeholder"
fi

# Cleanup summary temp files
rm -f "$SUMMARY_INPUT" "$SUMMARY_PROMPT_FILE"

fi  # --no-summary

# ─── Generate final report ────────────────────────────────────────────

"$GENERATE_REPORT" \
  --out-dir "$OUT" \
  --video-file "$IN" \
  --duration "$DURATION" \
  --duration-fmt "$DURATION_FMT" \
  --resolution "$RESOLUTION" \
  --codec "$CODEC" \
  --fps "$FPS" \
  --bitrate "$BITRATE" \
  --filesize "$FILESIZE" \
  --has-audio "$HAS_AUDIO" \
  --provider "$PROVIDER" \
  --model "$MODEL" \
  --summary-model "$SUMMARY_MODEL" \
  --summary "$SUMMARY_FINAL" \
  --format "$FORMAT" \
  > "$REPORT"

echo "   ✅ Report: $REPORT"


# ─── Done ─────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold "✅ 视频分析完成！"
echo ""
echo "   📄 报告: $REPORT"
echo "   🖼️ 帧图片: $FRAMES_DIR/ (${ACTUAL_FRAMES} 张)"
echo "   📝 逐帧分析: $ANALYSIS_DIR/"
echo "   🧠 综合摘要: 已自动生成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Output the report path as last line (for scripting/programmatic use)
echo "$OUT"
