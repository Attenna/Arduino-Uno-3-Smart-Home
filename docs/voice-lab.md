# 语音对话实验（voice_lab）

> 课程作业「第七章 智能识别 —— 语音与语言」在智能家居仓库里的本地实现。
> 代码与运行说明见 [`PC_Test/voice_lab/README.md`](../PC_Test/voice_lab/README.md)。
> 本文只记录设计决策、评测口径和限制。

## 1. 为什么做级联

端到端语音大模型（Qwen-Audio / GPT-4o audio）把 ASR、对话、TTS 合成一个模型，
交互自然，但本机只有 8 GB 显存，且课程要求能解释「准确性、延迟」来自哪一段。
级联方案的每一段都可以替换、单独计时、单独评估：

| 阶段 | 默认 | 对照 | 关键指标 |
|---|---|---|---|
| ASR | Sherpa-ONNX 2025 中文流式 int8 | Whisper small（CPU） | CER、精确匹配、RTF |
| 对话 | hybrid（规则快路径 + Qwen2.5-3B） | rules / llama_cpp / OpenAI API | 工具名/参数准确率、任务成功率、首字/总延迟 |
| TTS | edge-tts | Sherpa VITS / CosyVoice2 API | 首包、总合成、RTF |
| 端到端 | 上述默认组合 | 各组合 | 任务成功率、ASR/LLM/总延迟 |

## 2. 任务域与工具

智能家居的 6 个工具与现有 `PC_Test/voice_assistant.py` 的语义一致：

- `control_light(action, room, color?, brightness?)`
- `control_fan(action, speed?)`
- `control_door(action)`
- `control_ac(action, temperature?, mode?)`
- `set_scene(scene)`
- `query_sensor(metric)`

`MockHome` 保存灯（三房间）、风扇、门、空调、场景与传感器状态。门在锁定时不能直接打开，
这是一个**有状态失败**用例，用来检查模型是否会编造执行结果；工具返回失败时，助手必须
说「失败/请先解锁」，不能声称成功。

## 3. 对话编排

一轮的时序：

1. `handle_audio`：读 WAV → Sherpa/Whisper → 领域纠错 → 文本；
2. `handle_text`：system + 最近 N 轮 + 用户句 → LLM；
3. 若 LLM 返回工具调用：校验 JSON Schema → 执行 MockHome → 把真实结果交回 LLM
   生成口语回复；`hybrid`/`rules` 快路径直接用模板把工具结果说人话，省掉第二次 LLM；
4. 回复按句切分，TTS 线程合成并播放；首句先播，后续句子边生成边合成；
5. 记录 `Timing`：ASR、LLM 首字、LLM 总、工具、首音、整轮。

`hybrid` 的规则快路径只处理**明确设备指令**；「我有点冷」「把客厅弄得适合看电影」
这类需要推理/指代的句子仍走 LLM。这样现场演示不会因为 3B 模型冷启动而卡 30 秒。

## 4. 评测口径

### ASR

- 测试集：`make_dataset.py` 用 edge-tts 生成 3 个音色 × 27 条单轮指令，
  另有 12 条加噪变体（SNR 20/10 dB，固定随机种子）。
- 指标：字符错误率 `CER = edit_distance(ref, hyp) / len(ref)`（先去标点/空格，
  Whisper 输出用 OpenCC 转简体）；精确匹配；关键词召回；延迟与 RTF。
- 参考文本已知，不需要人工标注；但合成音的 CER 绝对值会比真人录音乐观，
  适合引擎之间的相对比较。

### 对话

- 31 个用例：27 个单轮 + 4 个多轮（灯的颜色/亮度、风扇档位、空调温度、门锁/开门）。
- 每个用例给出每轮的期望工具名与参数（参数按子集匹配），以及最终状态断言。
- `name_acc`：工具名正确率；`args_acc`：参数子集正确率；`case_success`：
  所有轮工具正确且最终状态满足。
- 多轮用例专门测「省略/指代」：第二轮「调到三档」「把颜色换成蓝色」没有重复设备名，
  规则快路径会失败，必须靠 LLM 的上下文——这是规则与 LLM 的差距所在。

### TTS

- 对 27 个单轮用例的文本去重后得到 28 句，逐句合成并关闭缓存；记录首包、总合成、音频时长、RTF。
- edge-tts 的首包是网络首块；Sherpa VITS 是非流式，首包≈总合成。

### 端到端

- 用 xiaoxiao 音色的干净 WAV → ASR → 对话 → 工具，比较任务成功率与
  `asr_ms / llm_ms / total_ms`。TTS 不计入端到端任务成功，但单独评测。

## 5. 延迟分解的读法

`Timing.tts_first_audio_ms` 是**从本轮开始**到第一次出声的绝对时间，不是「TTS 单独耗时」。
因为 LLM 流式输出与 TTS 合成是重叠的，各段不能简单相加；报告里用绝对时间线画瀑布图，
并另列 `llm_total_ms`、`tool_ms` 等。

## 6. 限制与后续

- 没有唤醒词/回声消除/远场阵列；这些是产品化问题。
- 没有真机串口；`MockHome` 只验证语义与状态，不验证 Arduino 协议。
- 本地 3B LLM 的冷启动和 3B 的能力上限是主要瓶颈；有可用 API Key 时
  切 `--llm openai` 可以把首字降到 1 s 量级。
- CosyVoice2 适配器按 OpenAI `/audio/speech` 风格实现，但本次没有可用 Key，
  未做真实 API 验证；报告里如实标注。
- 后续可加：流式 VAD、KWS 唤醒、TTS 真流式解码、更多真人录音测试集。
