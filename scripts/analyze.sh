#!/usr/bin/env bash
set -euo pipefail

# ─── Video AI Analyzer ───────────────────────────────────────────────
# AI-powered video understanding: frames → GPT-4V + audio → Whisper
# Output: comprehensive Markdown report
# ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPT_FILE="${SCRIPT_DIR}/../references/frame-prompt.md"

usage() {
  cat >&2 <<'EOF'
Usage:
  analyze.sh <video-file> [options]

Options:
  --interval N      Seconds between frame captures (default: 10)
  --max-frames N    Max frames to analyze (default: 20)
  --out DIR         Output directory (default: ./video-analysis-{timestamp})
  --model MODEL     OpenAI vision model (default: gpt-4o)
  --no-transcribe   Skip audio transcription
  --language LANG   Whisper language hint (e.g., zh, en, ja)

Examples:
  analyze.sh meeting.mp4
  analyze.sh lecture.mp4 --language zh --interval 5
  analyze.sh movie.mp4 --interval 60 --max-frames 15 --no-transcribe
EOF
  exit 2
}

# ─── Parse arguments ─────────────────────────────────────────────────

if [[ "${1:-}" == "" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
fi

IN="$1"
shift

INTERVAL=10
MAX_FRAMES=20
OUT=""
MODEL="gpt-4o"
TRANSCRIBE=true
LANGUAGE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval)    INTERVAL="${2:-}"; shift 2 ;;
    --max-frames)  MAX_FRAMES="${2:-}"; shift 2 ;;
    --out)         OUT="${2:-}"; shift 2 ;;
    --model)       MODEL="${2:-}"; shift 2 ;;
    --no-transcribe) TRANSCRIBE=false; shift ;;
    --language)    LANGUAGE="${2:-}"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

# ─── Validate inputs ─────────────────────────────────────────────────

if [[ ! -f "$IN" ]]; then
  echo "Error: Video file not found: $IN" >&2
  exit 1
fi

for cmd in ffmpeg ffprobe curl base64 python3; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: Required command not found: $cmd" >&2
    exit 1
  fi
done

if [[ "${OPENAI_API_KEY:-}" == "" ]]; then
  echo "Error: OPENAI_API_KEY is not set" >&2
  echo "  export OPENAI_API_KEY=\"sk-...\"" >&2
  exit 1
fi

# ─── Setup output directory ──────────────────────────────────────────

if [[ "$OUT" == "" ]]; then
  BASENAME="$(basename "$IN")"
  NAME="${BASENAME%.*}"
  TS="$(date +%Y%m%d-%H%M%S)"
  OUT="./video-analysis-${NAME}-${TS}"
fi

mkdir -p "$OUT/frames"
echo "📁 Output: $OUT"

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

# ─── Step 2: Transcribe audio (if present and enabled) ───────────────

TRANSCRIPT_TEXT=""
TRANSCRIPT_FILE="$OUT/transcript.txt"

if $TRANSCRIBE && [[ "$HAS_AUDIO" != "" && "$HAS_AUDIO" != "none" ]]; then
  echo "🎙️ Extracting audio and transcribing via Whisper..."
  
  AUDIO_FILE="$OUT/audio.mp3"
  ffmpeg -hide_banner -loglevel error -y -i "$IN" -vn -ar 16000 -ac 1 -b:a 64k "$AUDIO_FILE" 2>/dev/null
  
  LANG_ARG=""
  if [[ "$LANGUAGE" != "" ]]; then
    LANG_ARG="-F language=${LANGUAGE}"
  fi
  
  HTTP_STATUS=$(curl -s -w "%{http_code}" -o "$TRANSCRIPT_FILE" \
    https://api.openai.com/v1/audio/transcriptions \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -F "file=@${AUDIO_FILE}" \
    -F "model=whisper-1" \
    -F "response_format=text" \
    ${LANG_ARG} 2>/dev/null)
  
  if [[ "$HTTP_STATUS" == "200" ]]; then
    TRANSCRIPT_TEXT=$(cat "$TRANSCRIPT_FILE")
    echo "   ✅ Transcription complete ($(wc -c < "$TRANSCRIPT_FILE") chars)"
  else
    echo "   ⚠️  Transcription failed (HTTP $HTTP_STATUS). Continuing without transcript."
    TRANSCRIPT_TEXT=""
  fi
  
  rm -f "$AUDIO_FILE"
else
  if ! $TRANSCRIBE; then
    echo "⏭️  Transcription skipped (--no-transcribe)"
  else
    echo "⏭️  No audio stream found, skipping transcription"
  fi
fi

# ─── Step 3: Extract frames at intervals ─────────────────────────────

echo "🖼️  Extracting frames every ${INTERVAL}s (max ${MAX_FRAMES})..."

FRAME_COUNT=$(( DURATION / INTERVAL ))
if [[ $FRAME_COUNT -gt $MAX_FRAMES ]]; then
  FRAME_COUNT=$MAX_FRAMES
  # Recalculate interval for even distribution
  INTERVAL=$(( DURATION / MAX_FRAMES ))
fi
if [[ $FRAME_COUNT -lt 1 ]]; then
  FRAME_COUNT=1
fi

echo "   Will extract $FRAME_COUNT frames at ~${INTERVAL}s intervals"

declare -a FRAME_PATHS=()
declare -a FRAME_TIMES=()

for ((i=0; i<FRAME_COUNT; i++)); do
  SECONDS=$(( i * INTERVAL ))
  if [[ $SECONDS -ge $DURATION ]]; then
    SECONDS=$(( DURATION - 1 ))
  fi
  TIME_FMT=$(printf '%02d:%02d:%02d' $((SECONDS/3600)) $(((SECONDS%3600)/60)) $((SECONDS%60)))
  
  FRAME_PATH="$OUT/frames/frame_$(printf '%04d' $i)_${TIME_FMT//:/}.jpg"
  
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
echo "   ✅ Extracted $ACTUAL_FRAMES frames"

if [[ $ACTUAL_FRAMES -eq 0 ]]; then
  echo "Error: No frames extracted. Check the video file." >&2
  exit 1
fi

# ─── Step 4: Analyze frames with GPT-4V ──────────────────────────────

echo "🧠 Analyzing frames with GPT-4V ($MODEL)..."

# Load frame analysis prompt
FRAME_PROMPT="Describe this video frame in detail. What do you see? Include:
- The setting/environment
- People present and what they are doing
- Objects, text, or UI elements visible
- The mood or atmosphere
- Any notable details

Respond in the same language as the video content. Be concise but thorough."

if [[ -f "$PROMPT_FILE" ]]; then
  FRAME_PROMPT=$(cat "$PROMPT_FILE")
fi

ANALYSIS_DIR="$OUT/frame-analysis"
mkdir -p "$ANALYSIS_DIR"

for ((i=0; i<ACTUAL_FRAMES; i++)); do
  FRAME_PATH="${FRAME_PATHS[$i]}"
  FRAME_TIME="${FRAME_TIMES[$i]}"
  FRAME_NAME="$(basename "$FRAME_PATH")"
  ANALYSIS_FILE="$ANALYSIS_DIR/${FRAME_NAME%.jpg}.txt"
  
  # Skip if already analyzed
  if [[ -f "$ANALYSIS_FILE" && -s "$ANALYSIS_FILE" ]]; then
    echo "   ⏭️  Frame $((i+1))/$ACTUAL_FRAMES ($FRAME_TIME) — cached"
    continue
  fi
  
  echo "   🔍 Analyzing frame $((i+1))/$ACTUAL_FRAMES ($FRAME_TIME)..."
  
  # Use Python helper for robust API call (handles base64, JSON, errors)
  VISION_RESULT=$("$SCRIPT_DIR"/call-vision.py \
    "$FRAME_PATH" \
    --model "$MODEL" \
    --prompt "$FRAME_PROMPT" \
    --out "$ANALYSIS_FILE" \
    2>&1)
  
  VISION_EXIT=$?
  if [[ $VISION_EXIT -ne 0 ]]; then
    echo "[GPT-4V analysis error: $VISION_RESULT]" > "$ANALYSIS_FILE"
    echo "   ⚠️  Frame $((i+1)) failed: $VISION_RESULT"
  fi
  
  # Small delay to avoid rate limits
  sleep 0.5
done

echo "   ✅ Frame analysis complete"

# ─── Step 5: Generate comprehensive report ───────────────────────────

echo "📄 Generating comprehensive report..."

REPORT="$OUT/report.md"

{
  echo "# 视频分析报告: $(basename "$IN")"
  echo ""
  echo "> 分析时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "> 分析模型: $MODEL (视觉) + Whisper (语音)"
  echo ""
  
  # ─── Video Info ───
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
  
  # ─── Transcript ───
  echo "## 🎙️ 语音转录"
  echo ""
  if [[ "$TRANSCRIPT_TEXT" != "" ]]; then
    echo "$TRANSCRIPT_TEXT"
  else
    echo "> *(未进行语音转录，或无音频轨道)*"
  fi
  echo ""
  
  # ─── Scene Analysis ───
  echo "## 🖼️ 场景分析"
  echo ""
  echo "> 共分析 **$ACTUAL_FRAMES** 个关键帧，间隔约 ${INTERVAL} 秒"
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
  
  # ─── Summary section placeholder (will be filled by the LLM agent) ───
  echo "## 🧠 综合摘要"
  echo ""
  echo "> 以下由 AI 综合分析视觉帧描述与语音转录，生成整体理解："
  echo ""
  
} > "$REPORT"

echo "   ✅ Report generated: $REPORT"

# ─── Done ────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 视频分析完成！"
echo ""
echo "   📄 报告: $REPORT"
echo "   🖼️ 帧图片: $OUT/frames/ ($ACTUAL_FRAMES 张)"
echo "   📝 逐帧分析: $OUT/frame-analysis/"
echo ""
echo "   下一步: 让 AI Agent 阅读 report.md 中的帧分析结果"
echo "           和语音转录，撰写综合摘要。"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "$OUT"
