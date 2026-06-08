# Video AI Analyzer v3

> **"Whisper for video"** — 让你的 agent 能分析视频

双模式视频感知引擎：
- **🏠 本地模式（默认）**：场景检测 + 色彩/亮度/运动分析 + OCR + 人脸检测 + 语音转写 — **零 API 费用，零隐私泄露**
- **🤖 AI 视觉模式（可选）**：抽帧 → GPT-4V/Claude/Gemini 逐帧描述 → AI 自动生成摘要

---

## 🚀 快速开始

```bash
# ─── 本地模式（默认，零 API 费用）───────────
./scripts/analyze.sh meeting.mp4
# 输出: perception.json（结构化感知数据）+ report.md（人类可读报告）

# ─── 本地 + 语音转写 ─────────────────────
./scripts/analyze.sh lecture.mp4 --transcribe --language zh

# ─── AI 视觉模式（需要 API key）────────────
export OPENAI_API_KEY="sk-..."
./scripts/analyze.sh product-demo.mp4 --vision --provider openai
```

## ✨ v3 新特性

- **🏠 本地感知模式（默认）**：场景检测 + 色彩调色板 + 亮度 + 运动估计 + 人脸检测 + OCR — 无需 AI API
- **Whisper 风格 JSON 输出**：结构化时间戳分段数据，任何 AI Agent 可直接消费
- **双模式架构**：`--local`（默认，零费用感知）→ `--vision`（AI 深度分析）
- **本地优先转写**：whisper.cpp（本地）→ OpenAI Whisper API（回退）；无需强制 API key
- **场景感知采样**：智能场景切换检测替代固定间隔采样
- **保留所有 v2 视觉特性**：多提供商、并行分析、缓存、重试、费用估算

## 🏗️ 支持的模式

| 模式 | 命令 | 费用 | 需要 API key |
|------|------|------|-------------|
| **本地感知（默认）** | `analyze.sh video.mp4` | **免费** | ❌ |
| AI 视觉 | `analyze.sh video.mp4 --vision --provider openai` | 按量付费 | ✅ |

### 本地模式能力

| 功能 | 依赖 | 说明 |
|------|------|------|
| 场景检测 | ffmpeg | 自动识别场景切换点 |
| 色彩分析 | ffmpeg | 主色调调色板 + 暖/冷色调判断 |
| 亮度分析 | ffmpeg | 逐段亮度评估 |
| 运动估计 | ffmpeg | 场景变化程度 |
| OCR 文字识别 | tesseract（可选） | 提取画面中文字 |
| 人脸检测 | ffmpeg facedetect | 检测人脸数量 |
| 语音转写 | whisper.cpp（可选）→ OpenAI 回退 | 本地优先 |

## 🏗️ AI 视觉模式提供商

| Provider | 默认视觉模型 | 默认摘要模型 | 认证 |
|----------|------------|------------|------|
| `openai` | `gpt-4o` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `anthropic` | `claude-3-5-sonnet-20241022` | `claude-3-5-haiku-20241022` | `ANTHROPIC_API_KEY` |
| `google` | `gemini-2.0-flash-exp` | `gemini-2.0-flash-exp` | `GOOGLE_API_KEY` |
| `ollama` | `llava` | 同上 | 无（本地） |
| `openai-compatible` | `gpt-4o` | 同上 | `OPENAI_API_KEY` |

## 📖 更多示例

```bash
BASE="./scripts"

# ─── 本地模式 ─────────────────────────────
$BASE/analyze.sh meeting.mp4                                    # 默认本地感知
$BASE/analyze.sh lecture.mp4 --transcribe --language zh         # +中文语音转写
$BASE/analyze.sh video.mp4 --no-ocr --scene-threshold 0.5       # 关闭OCR，调灵敏度

# ─── AI 视觉模式 ──────────────────────────
$BASE/analyze.sh product-demo.mp4 --vision --provider openai
$BASE/analyze.sh video.mp4 --vision --provider anthropic
$BASE/analyze.sh lecture.mp4 --vision --provider google --language zh
$BASE/analyze.sh demo.mp4 --vision --provider ollama --model llava
$BASE/analyze.sh clip.mp4 --vision --provider openai-compatible \
  --base-url https://api.deepseek.com --model deepseek-chat

# ─── 长视频稀疏采样 ───────────────────────
$BASE/analyze.sh movie.mp4 --vision --interval 60 --max-frames 15 --no-transcribe
```

## 📋 输出结构

### 本地模式
```
video-analysis-{name}-{timestamp}/
├── perception.json        # 结构化感知数据（Whisper 风格分段 JSON）
└── report.md              # 人类可读的 Markdown 报告
```

### AI 视觉模式
```
video-analysis-{name}-{timestamp}/
├── report.md              # 综合分析报告（含 AI 摘要）
├── transcript.txt         # 语音转写文本
├── frames/                # 提取的帧图片
└── frame-analysis/        # 逐帧 AI 描述（缓存）
```

## 🔄 工作流程

```
                    ┌─────────────┐
                    │  视频文件     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         MODE: local   MODE: vision   (共享)
              │            │            │
    ┌─────────┤     ┌──────┤      ffprobe 元信息
    ▼         ▼     ▼      ▼            │
  场景检测  抽帧   帧提取  帧提取    时长/分辨率
    │         │     │      │
    ▼         ▼     ▼      ▼
  颜色分析  运动  Vision AI  Whisper
    │         │    (并行多Provider)  (本地优先)
    ▼         ▼     │      │
  OCR+人脸  合成   逐帧描述  文字稿
    │         │     │      │
    └────┬────┘     └──┬───┘
         ▼             ▼
   perception.json  report.md
   (结构化感知数据)  (综合分析报告)
```

## 🎨 设计哲学

- **本地优先**：默认模式零 API — 场景检测、色彩分析、运动估计、OCR、人脸检测全部本地运行
- **双模式**：`--local` 免费感知，`--vision` AI 深度分析
- **多提供商**：视觉模式支持 OpenAI、Anthropic、Google、Ollama、兼容接口
- **轻量级**：只需 ffmpeg + python3。零 pip 依赖。零本地模型下载（tesseract/whisper.cpp 可选）
- **专注**：「看懂」是唯一目标
- **Agent 友好**：结构化 JSON 输出（本地）或 Markdown 报告（视觉），清晰结构，缓存支持续传

## 🔧 依赖

- **ffmpeg** + **ffprobe**：`brew install ffmpeg` 或 `apt install ffmpeg`
- **python3**：仅标准库 — 无需 pip 安装
- **API key**（仅 AI 视觉模式）：`OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 或 `GOOGLE_API_KEY` 之一
- **可选**：`tesseract`（OCR）、`whisper-cpp`（本地语音转写）

## 📄 License

MIT
