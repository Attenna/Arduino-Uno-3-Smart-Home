# voice_lab — 级联语音对话实验（ASR + LLM + TTS）

> 课程作业「第七章 智能识别 —— 语音与语言」的本地实验模块。
> 与 `PC_Test/voice_assistant.py` 的区别：本模块**不碰串口/硬件网关**，用内存 mock 设备，
> 专门做可复现的语音对话演示、准确率与延迟评测；两者可以并存。

## 1. 方案

```text
麦克风 / WAV
   │
   ▼
┌───────────────────────────────┐
│ ASR（三选一）                  │
│  • Sherpa-ONNX 2025 中文流式   │  默认，本地，约 0.9–1.2 s/句
│  • faster-whisper small        │  CT2 int8，本地 CPU，约 2.4 s/句
│  • OpenAI Whisper small        │  PyTorch 对照，本地 CPU，约 3.4 s/句
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 对话（三选一）                 │
│  • hybrid：规则快路径 + 本地 LLM │  默认，明确指令 <1 ms，开放问题走 LLM
│  • llama_cpp：Qwen2.5-3B/1.5B  │  纯 LLM，Q4_K_M，llama.cpp
│  • openai：任意 OpenAI 兼容 API │  硅基流动 / 百炼，可选
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 工具（6 个）                   │
│  control_light / control_fan   │
│  control_door / control_ac     │
│  set_scene / query_sensor      │
│  → 内存 MockHome，状态可查询    │
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ TTS（三选一）                  │
│  • edge-tts                    │  默认，自然，首句约 0.7–1.3 s
│  • Sherpa-ONNX VITS            │  全离线，较慢（本机 RTF≈1.6）
│  • CosyVoice2 HTTP API         │  可选，需 API Key
└───────────────────────────────┘
```

### 本地实测摘要（2026-11-10，Ryzen 9 6900HS / CPU）

| 项 | 结果 |
|---|---|
| ASR | Sherpa 2025：CER 0.039、精确匹配 88.2%、897 ms/句（RTF 0.40）；faster-whisper small：CER 0.063、2375 ms/句（RTF 1.09）；Whisper small：CER 0.055、3390 ms/句（RTF 1.53） |
| 对话 | 规则 90.3% 用例成功；hybrid（规则 + 对话状态改写 + LLM 兜底）100%、约 438 µs/轮 |
| TTS | edge-tts 首音 678 ms / 总合成 1216 ms（RTF 0.58）；离线 VITS 2323 ms（RTF 2.06） |
| 端到端 | Sherpa + rules/hybrid 27 条干净音频任务成功率 100%，总延迟 0.9–1.6 s（ASR 主导） |
| 纯 LLM | Qwen2.5-3B 单轮 bench LLM 总耗时约 30.6 s，适合对照/开放问题，不适合低延迟主路径 |

> 详细数字与失败案例见 `output/eval_*.json`；报告口径（warmup、关缓存、绝对时间线）见 `docs/voice-lab.md`。

设计要点：

1. **级联而不是端到端**：每一段可替换、可单独计时，适合分析「准确率换延迟」。
2. **ASR 先做领域后处理**：`asr.py` 里有一张很小的纠错表（如「我是灯」→「卧室灯」），
   只在智能家居短语上生效，用于修正流式模型的重复字/近音。
3. **对话默认 hybrid**：`打开客厅灯` 这类明确指令走规则快路径，时延 <1 ms；
   指代、省略、开放问题再交给本地 Qwen。纯 LLM 模式用 `--llm llama_cpp`。
4. **TTS 按句流式**：LLM 边生成，`SentenceSplitter` 按句切分，TTS 线程边合成边播；
   延迟指标记录「首音」而不是「整段合成完」。
5. **工具执行在内存里**：`MockHome` 与真实网关语义一致（灯/风扇/门/空调/场景/传感器），
   但没有串口依赖，单元测试可完全离线。
6. **连续模式是半双工**：KWS 唤醒 + VAD 端点 + 状态机；SPEAKING 关麦防自听，
   手动打断停 TTS；真 AEC 未实现，边界写在 README/报告里。

## 2. 目录

```text
PC_Test/voice_lab/
├─ config.yaml          # 后端、模型路径、系统提示词、端口
├─ asr.py               # Sherpa / faster-whisper / Whisper 适配器 + 领域纠错
├─ llm.py               # llama.cpp / OpenAI 兼容 / 规则 / hybrid
├─ tts.py               # edge-tts / Sherpa VITS / CosyVoice2 + 流式播放
├─ tools.py             # 6 个工具 schema + MockHome
├─ dialog.py            # 一轮对话编排 + 延迟分解
├─ conversation.py      # KWS 唤醒 + VAD + 半双工状态机
├─ app.py               # CLI + Flask Web 演示
├─ cases.py             # 31 个评测用例（27 单轮 + 4 多轮）
├─ make_dataset.py      # edge-tts 生成可复现 ASR 测试集
├─ eval.py              # ASR / 对话 / TTS / 端到端评测
├─ metrics.py           # CER、编辑距离、分位数等
├─ download_models.py   # 下载 Sherpa 2025 ASR + Qwen GGUF
└─ output/              # 评测 JSON、TTS 缓存（git-ignored）
```

## 3. 环境

推荐 Python 3.11（3.13 也可，但 `llama-cpp-python` 的 Windows 轮子以 3.11 最稳）：

```powershell
cd <repo>
uv venv --python 3.11 .venv
uv pip install -r PC_Test/requirements-voice-lab.txt
# llama.cpp 的 CPU 预编译轮子（若 PyPI 源码编译失败）：
#   下载 https://abetlen.github.io/llama-cpp-python/whl/cpu 里对应的 win_amd64.whl
#   再 uv pip install <wheel>
```

模型（已在主 clone 的 `PC_Test/models` 里的可直接复用；`PC_Test/models/` 不入库）：

```powershell
cd PC_Test
python -m voice_lab.download_models --asr            # Sherpa 2025 中文流式 int8（约 133 MB）
python -m voice_lab.download_models --llm            # Qwen2.5-3B-Instruct Q4_K_M（约 2 GB）
python -m voice_lab.download_models --faster-whisper # CT2 small（约 484 MB，支持断点续传）
# 可选：python -m voice_lab.download_models --whisper # PyTorch small（约 461 MB）
```

`config.yaml` 默认路径：

| 后端 | 默认模型 | 说明 |
|---|---|---|
| ASR | `models/sherpa/asr_zh` | 2025-06-30 中文 streaming Zipformer int8；比仓库旧 bilingual 模型准 |
| ASR 对照 | `models/whisper_ct2/small` | faster-whisper small CT2 int8；HF 下载失败时用脚本断点续传 |
| LLM | `models/qwen/qwen2.5-3b-instruct-q4_k_m.gguf` | 想更快可换 1.5B 同名文件 |
| TTS | edge-tts | 需要网络；离线改用 `--tts sherpa` |

## 4. 快速开始

```powershell
cd PC_Test

# 文本一轮（最快，先验证工具/状态）
python -m voice_lab.app --text "把客厅的灯调成蓝色"

# 语音文件一轮
python -m voice_lab.app --wav voice_lab\dataset\light_blue__xiaoxiao.wav

# 麦克风录一句（能量 VAD，静音 0.8 s 结束）
python -m voice_lab.app --mic

# Web 演示（推荐加 --warmup，首次启动预加载权重）
python -m voice_lab.app --serve --warmup
# 浏览器打开 http://127.0.0.1:8110/

# 连续语音：Hey Bota 唤醒 + VAD 端点 + 半双工状态机
python -m voice_lab.app --wake --warmup
python -m voice_lab.app --serve --warmup --wake   # Web 上点“连续语音”

# 纯 LLM（不用规则快路径）
python -m voice_lab.app --llm llama_cpp --text "我有点热，帮我把空调调低一点"

# 关闭 TTS / 只合成不播放
python -m voice_lab.app --no-tts --text "打开风扇"
python -m voice_lab.app --tts edge --no-play --text "打开风扇"

# 自检（不加载模型）
python -m voice_lab.app --self-check
```

### 4.1 连续语音模式（KWS + VAD + 半双工）

不启用 `--wake` 时仍是“按一下录一句”。启用后：

```text
IDLE ──Hey Bota/回车/HTTP──▶ WAKING ──滴声──▶ LISTENING
                                                │ VAD 端点
                                                ▼
                                            THINKING
                                                │ 第一句 TTS
                                                ▼
                                            SPEAKING
                                                │ TTS 播完
                                                ▼
                                            FOLLOWUP ──超时──▶ IDLE
                                                │ 检测到追问
                                                └──────────▶ LISTENING
```

- **唤醒词**：Sherpa-ONNX KWS，默认 `Hey Bota`（`models/sherpa/kws`）；也可用回车、
  `POST /api/conversation/wake` 或网页“唤醒”按钮。
- **VAD**：能量阈值 + 最短语音 + 尾静音（默认 0.8 s）+ 最长句保护（15 s），
  带 300 ms 前置缓冲，端点后自动提交。
- **半双工**：`THINKING/SPEAKING` 期间**主动忽略麦克风**，所以 TTS 不会被识别成用户；
  `FOLLOWUP` 只有 TTS 播完后才重新开麦，避免自问自答。
- **打断**：`SPEAKING/THINKING` 时按 `i`（CLI）、网页“打断”或
  `POST /api/conversation/interrupt` 会 `engine.cancel()`：停 TTS、回到 LISTENING。
- **AEC 边界**：浏览器录音已启用 `echoCancellation:true`；服务端麦克风只做半双工，
  **没有实现真正的 WebRTC/Speex AEC**。要边播边听/自然打断，需要 AEC + 双工状态机，
  本次不假装实现，见 `docs/voice-lab.md`。

## 5. 评测

```powershell
cd PC_Test

# 1) 生成 ASR 测试集：3 个 edge-tts 音色 × 27 个单轮用例 + 12 个加噪变体
python -m voice_lab.make_dataset

# 2) ASR：Sherpa / faster-whisper / Whisper（Whisper CPU 较慢，可用 --limit 30 控制）
python -m voice_lab.eval --asr-backends sherpa,faster_whisper,whisper --skip-dialog --skip-tts --skip-e2e

# 3) 对话：规则 / hybrid / 纯 LLM
python -m voice_lab.eval --llm-backends rules,hybrid,llama_cpp --skip-asr --skip-tts --skip-e2e

# 4) TTS：edge vs 离线 VITS
python -m voice_lab.eval --tts-backends edge,sherpa --skip-asr --skip-dialog --skip-e2e

# 5) 端到端：WAV → ASR → LLM/工具 → 任务成功
python -m voice_lab.eval --asr-backends sherpa --llm-backends rules,hybrid --skip-tts

# 全量（Whisper 会跑很久）
python -m voice_lab.eval --all --asr-backends sherpa,faster_whisper,whisper
```

输出在 `voice_lab/output/`：

| 文件 | 内容 |
|---|---|
| `eval_asr.json` | 每条音频的参考/识别文本、CER、精确匹配、关键词召回、延迟、RTF；按音色/噪声分组 |
| `eval_dialog.json` | 每个用例每轮的期望/实际工具、名称/参数是否正确、最终状态、延迟 |
| `eval_tts.json` | 每句的首包/总合成延迟、音频时长、RTF |
| `eval_e2e.json` | 端到端 ASR CER、任务成功率、ASR/LLM/总延迟 |
| `summary.json` | 上述四项的汇总 |

评测脚本默认先 warmup，避免把模型加载算进单句延迟；TTS 评测显式关闭缓存，
所以数字是「冷合成」而不是缓存命中。

## 6. Web API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 演示页（录音、文本、对话流、延迟瀑布、设备状态） |
| GET | `/api/info` | 后端、模型是否就绪、设备状态、历史轮数 |
| POST | `/api/text` | `{"text":"...","speak":true}`，返回完整 `TurnResult` |
| POST | `/api/audio` | multipart `file`（WebM/Opus、WAV、MP3），返回 ASR + 对话 |
| GET | `/api/conversation/state` | 连续模式状态、最近事件、最后一次结果 |
| POST | `/api/conversation/start` | 启动服务端麦克风的连续模式 |
| POST | `/api/conversation/wake` | 手动唤醒（等价于 Hey Bota） |
| POST | `/api/conversation/interrupt` | 打断当前 THINKING/SPEAKING，回到 LISTENING |
| POST | `/api/conversation/stop` | 停止连续模式 |
| POST | `/api/reset` | 重置 mock 设备与对话历史 |
| GET | `/api/health` | 健康检查 |

页面用浏览器 `MediaRecorder` 录音，后端用 ffmpeg 转 16 kHz WAV；TTS 声音从
**运行服务的电脑扬声器**播放（页面只负责采集与展示）。

## 7. 已知限制

- **Sherpa 流式模型不是完美 ASR**：短指令仍可能出现重复字/近音（如「卧室」→「我室」），
  本模块用领域纠错表兜底；追求准确率请用 `--asr faster_whisper`（约 2.4 s/句）
  或 `--asr whisper`（约 3.4 s/句）。
- **本地 3B LLM 冷启动慢**：首次 prompt 处理约 10–30 s，之后同一进程会快很多；
  `hybrid` 模式把明确指令挡在 LLM 之前，是现场演示的默认选择。
- **edge-tts 需要网络**；离线演示用 `--tts sherpa`，本机 VITS 的 RTF 约 1.6。
- **CosyVoice2 适配器未做真实 API 验证**：仓库当前没有可用的 SiliconFlow Key；
  配好 `tts.cosyvoice.api_key` 后可用，接口按 OpenAI `/audio/speech` 风格实现。
- **测试集是 TTS 合成音**，不是真人录音；CER 绝对值会偏乐观，适合做引擎之间的相对比较。
- **半双工已实现，真 AEC 未实现**：`SPEAKING` 期间关麦，避免自听；手动打断可用。
  真正的“边播边听/自然 barge-in”需要 WebRTC/Speex AEC + 双工状态机，属于后续工作。
- 唤醒词是声学 KWS（`Hey Bota`），不是任意语音唤醒；远场/噪声下的唤醒率未做系统评测。

## 8. 与现有语音助手的关系

`PC_Test/voice_assistant.py` 仍是香橙派运行时的语音入口：KWS「Hey Bota」+ 流式 ASR +
云端/本地 LLM + VITS，经 web 硬件网关控制真实 Arduino。`voice_lab` 复用它的模型与
级联思路，但：

- 不启动 MCP、不打开串口、不依赖 `run_web.py`；
- 增加可替换后端、延迟分解、批量评测与报告素材；
- 默认使用更新的 2025 中文 ASR 模型（旧模型仍在 `models/sherpa/asr`，未改动）。
