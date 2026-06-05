#!/usr/bin/env bash
set -euo pipefail

# ─── Video AI Analyzer v2 ─────────────────────────────────────────────
# Multi-provider video understanding: frames → AI vision + audio → Whisper
# Output: comprehensive Markdown report with auto-generated summary
#
# Supported providers: openai | anthropic | google | ollama | openai-compatible
# ─────────────────────────────────────────────────────────────────────

VERSION="2.0.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPT_FILE="${SCRIPT_DIR}/../references/frame-prompt.md"
CALL_AI="${SCRIPT_DIR}/call-ai.py"

# ─── Usage ───────────────────────────────────────────────────────────

usage() {
  cat >&2 <<'EOF'
Video AI Analyzer — Multi-provider video content understanding

Usage:
  analyze.sh <video-file> [options]

Options:
  --provider NAME       AI provider: openai|anthropic|google|ollama|openai-compatible
                        (default: openai)
  --model MODEL         Vision model name (provider-specific default if unset)
  --summary-model M     Model for final summary (default: cheaper variant of model)
  --interval N          Seconds between frame captures (default: 10)
  --max-frames N        Max frames to analyze — API cost control (default: 20)
  --out DIR             Output directory (default: ./video-analysis-{name}-{ts})
  --no-transcribe       Skip audio transcription
  --language LANG       Whisper language hint (e.g., zh, en, ja)
  --detail LEVEL        Image detail: low|high|auto (default: low, OpenAI only)
  --max-tokens N        Max tokens per frame analysis (default: 500)
  --temperature T       Sampling temperature 0-2 (default: 0.7)
  --parallel N          Max concurrent frame analyses (default: 5)
  --base-url URL        Override API base URL for the chosen provider
  --version             Print version and exit

Environment (per provider):
  openai / openai-compatible → export OPENAI_API_KEY="sk-..."
  anthropic                 → export ANTHROPIC_API_KEY="sk-ant-..."
  google                    → export GOOGLE_API_KEY="..."
  ollama                    → no key needed (localhost:11434)

Examples:
  # OpenAI (default)
  analyze.sh meeting.mp4

  # Anthropic Claude
  analyze.sh video.mp4 --provider anthropic --model claude-3-5-sonnet-20241022

  # Google Gemini (free tier available)
  analyze.sh lecture.mp4 --provider google --language zh

  # Local Ollama
  analyze.sh demo.mp4 --provider ollama --model llava

  # DeepSeek / Groq / any OpenAI-compatible
  analyze.sh clip.mp4 --provider openai-compatible \
    --base-url https://api.deepseek.com --model deepseek-chat

  # Long video: sparse sampling + skip transcription
  analyze.sh movie.mp4 --interval 60 --max-frames 15 --no-transcribe
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
TRANSCRIBE=true
LANGUAGE=""
DETAIL="low"
FRAME_MAX_TOKENS=500
SUMMARY_MAX_TOKENS=2000
TEMPERATURE=0.7
MAX_PARALLEL=5
BASE_URL=""

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
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

# ─── Validate inputs ──────────────────────────────────────────────────

if [[ ! -f "$IN" ]]; then
  echo "Error: Video file not found: $IN" >&2
  exit 1
fi

# Validate numeric inputs
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

# Transcription always uses OpenAI Whisper
if $TRANSCRIBE && [[ "${OPENAI_API_KEY:-}" == "" ]]; then
  echo "⚠️  OPENAI_API_KEY not set — Whisper transcription unavailable."
  echo "   Transcription will be skipped. Set OPENAI_API_KEY or use --no-transcribe."
  TRANSCRIBE=false
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
  echo "🎙️  Transcribing via Whisper..."
  
  AUDIO_FILE="$OUT/audio.mp3"
  ffmpeg -hide_banner -loglevel error -y -i "$IN" -vn -ar 16000 -ac 1 -b:a 64k "$AUDIO_FILE" 2>/dev/null
  
  LANG_ARG=""
  if [[ "$LANGUAGE" != "" ]]; then
    LANG_ARG="-F language=${LANGUAGE}"
  fi
  
  TRANSCRIBE_HTTP=$(curl -s -w "%{http_code}" -o "$TRANSCRIPT_FILE" \
    https://api.openai.com/v1/audio/transcriptions \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -F "file=@${AUDIO_FILE}" \
    -F "model=whisper-1" \
    -F "response_format=text" \
    ${LANG_ARG} 2>/dev/null)
  
  if [[ "$TRANSCRIBE_HTTP" == "200" ]]; then
    TRANSCRIPT_TEXT=$(cat "$TRANSCRIPT_FILE")
    echo "   ✅ Transcription complete ($(wc -c < "$TRANSCRIPT_FILE" | tr -d ' ') chars)"
  else
    echo "   ⚠️  Transcription failed (HTTP $TRANSCRIBE_HTTP). Continuing without transcript."
    TRANSCRIPT_TEXT=""
  fi
  
  rm -f "$AUDIO_FILE"
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
  RUNNING=0
  COMPLETED=0
  FAILED=0

  while IFS='|' read -r FRAME_PATH FRAME_TIME ANALYSIS_FILE; do
    FRAME_IDX=$(basename "$FRAME_PATH" | sed 's/frame_\([0-9]*\).*/\1/' | sed 's/^0*//')
    [[ "$FRAME_IDX" == "" ]] && FRAME_IDX="?"

    RUNNING=$((RUNNING + 1))

    (
      RESULT=$("$CALL_AI" "$FRAME_PATH" \
        --provider "$PROVIDER" \
        --model "$MODEL" \
        --prompt-file "$FRAME_PROMPT_TMP" \
        --out "$ANALYSIS_FILE" \
        --detail "$DETAIL" \
        --max-tokens "$FRAME_MAX_TOKENS" \
        --temperature "$TEMPERATURE" \
        $BASE_URL_ARG 2>&1)
      EXIT_CODE=$?

      if [[ $EXIT_CODE -ne 0 ]]; then
        echo "[AI analysis error: $RESULT]" > "$ANALYSIS_FILE"
      fi
    ) &

    # Limit concurrency — wait for one to finish when at capacity
    if [[ $RUNNING -ge $MAX_PARALLEL ]]; then
      wait -n 2>/dev/null || true
      RUNNING=$((RUNNING - 1))
    fi

    # Progress indicator (rough — actual completion tracked by wait)
    COMPLETED=$((COMPLETED + 1))
    echo -ne "\r   🔍 Progress: ${COMPLETED}/${NEW_JOBS} dispatched..."
  done < "$JOB_FILE"

  # Wait for all remaining jobs
  wait 2>/dev/null || true
  echo ""
fi

# Count actual successes
SUCCESS_COUNT=0
for ((i=0; i<ACTUAL_FRAMES; i++)); do
  FRAME_NAME="$(basename "${FRAME_PATHS[$i]}")"
  ANALYSIS_FILE="$ANALYSIS_DIR/${FRAME_NAME%.jpg}.txt"
  if [[ -f "$ANALYSIS_FILE" && -s "$ANALYSIS_FILE" ]]; then
    FIRST_LINE=$(head -1 "$ANALYSIS_FILE")
    if [[ "$FIRST_LINE" != "[AI analysis error:"* ]] && [[ "$FIRST_LINE" != "[GPT-4V analysis error:"* ]]; then
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

echo ""
echo "📄 Generating report..."

REPORT="$OUT/report.md"

{
  echo "# 视频分析报告: $(basename "$IN")"
  echo ""
  echo "> 分析时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "> 分析引擎: ${PROVIDER}/${MODEL} (视觉) + Whisper (语音)"
  echo "> 分析工具: Video AI Analyzer v${VERSION}"
  echo ""
  
  echo "## 📊 视频信息"
  echo ""
  echo "| 属性 | 值 |"
  echo "|------|-----|"
  echo "| 文件名 | \`$(basename "$IN")\` |"
  echo "| 时长 | $DURATION_FMT ($DURATION 秒) |"
  echo "| 分辨率 | $RESOLUTION |"
  echo "| 编码 | $CODEC |"
  echo "| 帧率 | ${FPS} fps |"
  echo "| 码率 | $BITRATE |"
  echo "| 文件大小 | $FILESIZE |"
  echo "| 音频 | $HAS_AUDIO |"
  echo ""
  
  echo "## 🎙️ 语音转录"
  echo ""
  if [[ "$TRANSCRIPT_TEXT" != "" ]]; then
    echo "$TRANSCRIPT_TEXT"
  else
    echo "> *(未进行语音转录，或无音频轨道)*"
  fi
  echo ""
  
  echo "## 🖼️ 场景分析"
  echo ""
  echo "> 共分析 **${ACTUAL_FRAMES}** 个关键帧，间隔约 ${INTERVAL} 秒，成功 ${SUCCESS_COUNT} 帧"
  echo ""
  
  for ((i=0; i<ACTUAL_FRAMES; i++)); do
    FRAME_TIME="${FRAME_TIMES[$i]}"
    FRAME_PATH="${FRAME_PATHS[$i]}"
    FRAME_NAME="$(basename "$FRAME_PATH")"
    ANALYSIS_FILE="$ANALYSIS_DIR/${FRAME_NAME%.jpg}.txt"
    
    echo "### 场景 $((i+1)) — ${FRAME_TIME}"
    echo ""
    
    if [[ -f "$ANALYSIS_FILE" ]]; then
      cat "$ANALYSIS_FILE"
    else
      echo "> *(分析不可用)*"
    fi
    echo ""
  done
  
} > "$REPORT"

echo "   ✅ Report: $REPORT"

# ─── Step 6: Generate AI summary ──────────────────────────────────────

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

# Append summary to report
{
  echo "## 🧠 综合摘要"
  echo ""
  if [[ $SUMMARY_EXIT -eq 0 && "$SUMMARY_RESULT" != "" ]]; then
    echo "$SUMMARY_RESULT"
  else
    echo "> *(自动摘要生成失败: $SUMMARY_RESULT)*"
    echo "> 请 AI Agent 阅读上方场景分析和语音转录来撰写摘要。"
  fi
  echo ""
} >> "$REPORT"

if [[ $SUMMARY_EXIT -eq 0 ]]; then
  echo "   ✅ Summary generated"
else
  echo "   ⚠️  Summary generation failed — report contains placeholder"
fi

# Cleanup
rm -f "$SUMMARY_INPUT" "$SUMMARY_PROMPT_FILE"

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
