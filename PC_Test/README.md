# PC 端工具集（PC_Test）

PC 端在电脑上通过 USB 串口直接与两块 Arduino 通信，用于**调试**、**测试**与**本地自动化**。

> 🚀 部署（含 Linux）/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

> 与 `gateway/`（Orange Pi 串口↔MQTT 网关）不同，本目录的工具**直接连串口**，不走 MQTT / Home Assistant，
> 适合在开发机上快速验证硬件与自动化逻辑。

---

## 目录结构

```text
PC_Test/
├── README.md               # 本文件（PC 端总览）
├── requirements.txt        # Python 依赖
│
├── test_serial.py          # ① 串口调试控制台（交互式，手动发命令测试硬件）
├── run_automation.py       # ② 自动化 DSL 运行器（运行 .auto 脚本）
├── oled_carousel.py        #    OLED 多行轮播模块（被 run_automation 调用）
├── camera_stream.py        # ④ USB 摄像头流式传输 + 人脸检测（本地窗口 / HTTP 流）
├── camera_test.py          #    摄像头快速自检（验证摄像头 + 检测链路）
├── link_server.py          # ③ 旧版联动服务（已过时，见下方说明）
│
├── voice_assistant.py      # ⑤ 语音交互模式（唤醒词 → Qwen2.5 → MCP 控硬件 → 流式 TTS）
├── qwen_server.py          #    本地 Qwen2.5 OpenAI 兼容服务（llama.cpp 后端 + 工具调用）
├── download_qwen.py        #    Qwen2.5 权重下载器（ModelScope 国内渠道）
├── mcp_home_server.py      #    智能家居 MCP server（独占串口，暴露 8 个工具）
├── tts_player.py           #    流式 TTS 播放器（Sherpa-ONNX VITS 本地合成）
├── voice_config.yaml       #    语音模式配置（串口/LLM 引擎/唤醒词/TTS 音色）
├── models/.gitignore       #    模型目录占位（Qwen GGUF / Sherpa-ONNX 语音模型不入库）
│
└── automation/             # AST 自动化引擎核心库
    ├── __init__.py
    ├── lexer.py            # 词法分析：脚本文本 → Token
    ├── parser.py           # 语法分析：Token → AST（递归下降）
    ├── runtime.py          # 运行时：遍历 AST + 动作映射
    ├── examples/           # 示例脚本（.auto）
    │   ├── smoke_alarm.auto
    │   ├── climate_control.auto
    │   └── edge_timer.auto
    └── README.md           # DSL 语法手册（写脚本时查这里）
```

---

## 三个工具怎么选

| 工具 | 用途 | 什么时候用 |
|------|------|-----------|
| `test_serial.py` | 手动发命令测试单块板 | 排查硬件、验证某个传感器/执行器是否正常 |
| `run_automation.py` | 运行 `.auto` 自动化脚本 | 写联动规则、定时任务、OLED 轮播 |
| `camera_stream.py` | USB 摄像头流式传输 + 人脸检测 | 视频监控、人脸识别（香橙派部署用 HTTP 流） |
| `voice_assistant.py` | 语音交互（KWS 唤醒 + Qwen2.5 + MCP） | 说「你邮你邮」唤醒，用自然语言控制硬件 |
| `link_server.py` | 旧的硬编码规则联动 | ⚠️ 已过时，建议改用 `run_automation.py` |

---

## 环境准备

```powershell
cd PC_Test
py -3.13 -m pip install -r requirements.txt
```

> 本机 Python 环境说明：`python` 指向 msys64 的 Python（无 pip），请使用 `py -3.13`（Windows 官方 Python 3.13）。

**识别串口**（COM6 = B 板执行器，COM7 = A 板传感器，需按实际调整）：

```powershell
py -3.13 -c "import serial.tools.list_ports as p; [print(x.device, x.description) for x in p.comports()]"
```

---

## ① test_serial.py — 串口调试控制台

交互式控制台，手动发送命令测试硬件。

```powershell
# 仅 B 板（执行器）
py -3.13 test_serial.py --port-b COM6

# 仅 A 板（传感器）
py -3.13 test_serial.py --port-a COM7

# 双板 + 自动跑一轮测试
py -3.13 test_serial.py --auto-test

# 记录传感器数据到 CSV
py -3.13 test_serial.py --log sensor_log.csv
```

常用菜单命令（B 板）：

| 输入 | 作用 |
|------|------|
| `b1` | 查询状态 STATUS |
| `b9` / `b10` | 开灯 / 关灯 |
| `b7` / `b8` | 开风扇 / 关风扇 |
| `b2` / `b3` | 开门 / 关门 |
| `b12` | 蜂鸣器（短鸣/长鸣/停止） |

---

## ② run_automation.py — 自动化 DSL 运行器

用接近自然语言的 `.auto` 脚本定义自动化规则（条件、分支、计时、边沿、定时器、操作）。

```powershell
# 运行示例脚本（自动探测串口）
py -3.13 run_automation.py automation/examples/smoke_alarm.auto

# 手动指定串口
py -3.13 run_automation.py automation/examples/smoke_alarm.auto --port-a COM7 --port-b COM6

# 只跑一轮（调试用）
py -3.13 run_automation.py automation/examples/smoke_alarm.auto --once

# 启用 OLED 多行轮播（3 秒切一页）
py -3.13 run_automation.py automation/examples/edge_timer.auto --carousel

# 调整轮播间隔 / 轮询间隔
py -3.13 run_automation.py automation/examples/edge_timer.auto --carousel --carousel-interval 5 --interval 1
```

**脚本语法见 [automation/README.md](automation/README.md)**，示例脚本在 [automation/examples/](automation/examples/)。

一个最小示例：

```
规则 "烟雾报警" {
    边沿 data.smoke {
        执行 蜂鸣器.开
        执行 红灯
    }
    边沿 下降 data.smoke {
        执行 蜂鸣器.关
        执行 关灯
    }
}
```

---

## ④ camera_stream.py — USB 摄像头流式传输 + 人脸检测

通过 USB 摄像头（如 USB2.0 Web Cam）采集画面，支持人脸检测，两种输出模式：

- **本地窗口**（`--mode local`）：开发机调试用，弹 OpenCV 窗口
- **HTTP MJPEG 流**（`--mode web`）：香橙派无头部署用，浏览器查看

```powershell
# 安装依赖（仅摄像头工具需要）
py -3.13 -m pip install opencv-python flask

# 本地窗口 + HTTP 流（默认 both）
py -3.13 camera_stream.py

# 香橙派无头环境：仅 HTTP 流（在浏览器访问 http://<香橙派IP>:8080）
py -3.13 camera_stream.py --mode web --host 0.0.0.0 --port 8080

# 关闭人脸检测（纯流式传输）
py -3.13 camera_stream.py --no-detect

# 指定摄像头
py -3.13 camera_stream.py --cam 0            # 按索引
py -3.13 camera_stream.py --cam "Web Cam"    # 按名称
```

**交互按键**（本地窗口模式）：

| 按键 | 作用 |
|------|------|
| `q` | 退出 |
| `s` | 保存当前帧为 `captured_<时间戳>.jpg` |

**摄像头发现策略**：用户指定 > 名称 `"Web Cam"` > 索引 `0~4` 依次尝试。

**快速自检**（先确认摄像头可用再上流）：

```powershell
py -3.13 camera_test.py              # 自动发现摄像头，读 5 帧
py -3.13 camera_test.py --cam 0 --frames 10
```

> 香橙派部署提示：`--mode web` 会用 Flask 起 MJPEG 流，浏览器打开 `http://<香橙派IP>:8080` 即可实时查看，
> 无需图形界面。HTTP 服务与摄像头采集在不同线程运行，互不阻塞。

---

## ③ link_server.py — 旧版联动服务（已过时）

> ⚠️ **建议改用 `run_automation.py`**。本脚本用硬编码的 `RULES` 列表实现联动，
> 逻辑与代码耦合，改规则需要改 Python 代码；新方案用 `.auto` 脚本解耦，可读可维护。

仅作历史参考保留，不再维护。

---

## ⑤ voice_assistant.py — 语音交互模式（唤醒词 + Qwen2.5 + MCP）

对着麦克风说唤醒词「你邮你邮」，再说一句指令（如「把灯调成蓝色」「现在多少度」），
**Qwen2.5 大模型**理解意图后，通过 MCP 工具直接控制 Arduino Module B，回复用流式 TTS 播放。

**数据流**：

```text
麦克风 ──Sherpa-ONNX──▶ KWS 声学唤醒「你邮你邮」──▶ 切 COMMAND + TTS 回「在的」
                        流式 ASR 整句 ──▶ 用户指令 ──▶ 切 IDLE
用户指令 ──Qwen2.5 流式 + 工具调用──▶ delta.content 按句喂 VITS TTS（边生成边播）
                                  └─ tool_calls ──MCP──▶ mcp_home_server ──▶ Module B
```

语音前端为 **Sherpa-ONNX**（全离线，同栈可直接移植香橙派）：
KWS 关键词声学唤醒（zipformer-wenetspeech 3.3M）+ 流式 ASR（streaming Paraformer 中英双语，
自带端点检测）+ 本地 VITS 语音合成（vits-melo-tts-zh_en）。
模型一键下载：`py -3.13 download_sherpa_models.py`（KWS ~14MB / ASR ~1GB / TTS ~160MB，国内镜像加速）。

`mcp_home_server.py` 作为子进程独占 A/B 两串口，暴露 8 个工具：
`light / door / window / fan / buzzer / oled / display / get_sensor_status`。
`voice_assistant.py` 不直接碰串口，所有硬件操作经 MCP `call_tool`。

### LLM 引擎：Qwen2.5（国内合规）

> ⚠️ 已移除 Ollama。当前引擎为 **Qwen2.5**，权重与推理均走国内合规渠道，两种模式可切换
> （`voice_config.yaml` → `llm.mode`）：

| 模式 | 说明 | 渠道/合规 |
|------|------|----------|
| `local`（默认） | 本地推理（离线），`qwen_server.py` 提供 OpenAI 兼容服务（llama.cpp 后端） | 权重经**魔搭社区 ModelScope**（阿里，modelscope.cn）下载；推理全程本地无外部服务 |
| `dashscope` | 阿里云百炼 OpenAI 兼容端点（免本地算力） | 阿里云国内云服务；需 API Key（[申请地址](https://bailian.console.aliyun.com/)） |

**百炼 Key 三种给法（任选其一）**：① 粘贴到 `PC_Test/dashscope_key.txt`（推荐，已入 .gitignore）；
② 环境变量 `DASHSCOPE_API_KEY`；③ config `llm.api_key`。
切到 dashscope 模式只需改 `llm.mode: "dashscope"`——端点和模型名会自动纠正，无需改 base_url。

**模型选择（面向香橙派 AI Pro 纯 CPU）**：默认 `Qwen2.5-3B-Instruct`（q4_k_m 量化，~2GB，
工具调用成功率显著更高，见下方压测表）；香橙派多核 ARM CPU 可跑，首字延迟略高于小模型。
追求极致低占用可换 **Apache-2.0**（商业友好）的 1.5B：
`py -3.13 download_qwen.py --repo Qwen/Qwen2.5-1.5B-Instruct-GGUF --quant q4_k_m`，
并同步改 `voice_config.yaml` 的 `llm.model` / `llm.local.gguf_path`；
要更强理解力且不在意云端，直接切 `dashscope` 模式用 qwen2.5-7b/14b。

### 环境准备

**一键部署（推荐）**：

```powershell
# 双击 deploy_voice.bat，或在终端执行：
cd PC_Test
powershell -ExecutionPolicy Bypass -File deploy_voice.ps1
```

脚本会自动：装 Python 依赖（阿里云 PyPI 镜像）→ 经 ModelScope 下载 Qwen2.5 权重 → 下载 Sherpa-ONNX 语音模型（KWS+ASR+TTS）→ 运行自检。

日常启动用 [start_voice.bat](start_voice.bat)（双击即可，自动拉起本地 Qwen 服务并启动助手）。

<details>
<summary>手动安装步骤（不想用脚本时点开）</summary>

```powershell
cd PC_Test
py -3.13 -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

**① 下载 Sherpa-ONNX 语音模型**（KWS 唤醒 + 流式 ASR + 本地 TTS，全离线）：

```powershell
py -3.13 download_sherpa_models.py   # → models/sherpa/{kws,asr,tts}/（国内镜像加速）
```

**② 下载 Qwen2.5 权重**（ModelScope 国内渠道，默认 3B q4_k_m ~2GB）：

```powershell
py -3.13 download_qwen.py     # Qwen/Qwen2.5-3B-Instruct-GGUF q4_k_m（~2GB）→ models/qwen/
```

**③ 启动本地 Qwen 服务**（每次使用前，或交给 start_voice.bat 自动拉起）：

```powershell
py -3.13 qwen_server.py       # 监听 http://127.0.0.1:8000/v1，加载约 10~30 秒
```

> 提示：
> - **纯 CPU 推理（默认，与香橙派一致）**：`voice_config.yaml` 的 `llm.local.n_gpu_layers: 0`。
>   目标机香橙派 AI Pro 的昇腾 NPU 目前 llama.cpp / Sherpa-ONNX 均无可用后端（Sherpa ACL 面向 Ascend 910），
>   CPU + 3B-Q4 + ASR INT8 已满足实时链路；NPU 加速属后期优化（交叉编译 + ACL 上下文绑定）。
> - Windows/Py3.13 若无预编译轮子会自动源码编译 CPU 版（需 VS Build Tools / VS2022 C++，约 3~10 分钟）。
> - 引擎可用 `py -3.13 qwen_server.py --smoke` 做冒烟验证（输出 `[SMOKE_OK] device=CPU`）。
> - 不想本地跑就切 `llm.mode: dashscope`（零本地算力，阿里云百炼国内云）。

**④ 配置串口**：复制配置做本地定制（不入库）：

```powershell
copy voice_config.yaml voice_config.local.yaml
# 编辑 voice_config.local.yaml：serial.port_a/port_b、llm.mode/model、wake.words 等
```

</details>

### 运行

```powershell
# 自检（Sherpa 模型 / 麦克风 / Qwen 引擎 / MCP 工具 / 串口）
py -3.13 voice_assistant.py --self-check

# 验证 LLM：流式对话 + 工具调用探测（需 qwen_server 或百炼 Key 就绪）
py -3.13 voice_assistant.py --test-llm "你好"

# 列出麦克风设备索引（配置 mic.device_index 用）
py -3.13 voice_assistant.py --list-mic

# 校准唤醒词识别（持续打印 KWS 命中 / partial / final，不调 LLM）
py -3.13 voice_assistant.py --kws-repl

# 启动语音助手（自动探测串口；需本地 Qwen 服务已在跑）
py -3.13 voice_assistant.py

# 手动指定串口 / 模式 / 模型 / 音色
py -3.13 voice_assistant.py --port-a COM7 --port-b COM6 --llm-mode local --model qwen2.5-3b-instruct-q4_k_m
```

> ⚠️ **串口互斥**：语音模式运行期间，COM 口被 mcp_home_server 子进程独占，
> 不要同时运行 `test_serial.py / full_test.py / run_automation.py / link_server.py`
> 或 Arduino IDE 串口监视器（会报「拒绝访问」，属 Windows 串口单进程规则，非 bug）。
> TCP 方面无冲突：Qwen 服务固定 8000，camera_stream 8080。

启动后说「你邮你邮」→ 听到「在的」→ 说指令，例如：

- 「把灯调成蓝色」→ Module B 灯变蓝 + TTS「已为您把灯调成蓝色」
- 「现在多少度」→ 调 `get_sensor_status` → TTS 回读数
- 「开门」「关风扇」「蜂鸣器响三声」→ 对应工具执行

### 调试 MCP server（独立）

用 MCP Inspector GUI 手动调每个工具，观察 B 板动作与 A 板状态：

```powershell
pip install mcp       # 含 mcp CLI
mcp dev mcp_home_server.py --port-a COM7 --port-b COM6
```

### 唤醒词说明

「你邮你邮」由 Sherpa-ONNX KWS 做声学级唤醒（不再依赖文本模糊匹配），唤醒词定义在
`models/sherpa/kws/keywords.txt`（pypinyin 声调格式），另内置别名「你好你好」。
灵敏度在 `voice_config.yaml` 的 `sherpa.kws.keywords_score / keywords_threshold` 调节
（score 调大 / threshold 调小 = 更易唤醒，误唤醒也会增加）。
播放 TTS 期间自动跳过唤醒检测（防喇叭回声误触发）。

### 合规说明

语音链路已全离线境内化：Sherpa-ONNX（KWS/ASR/TTS）+ Qwen2.5（ModelScope / 百炼），
不再依赖 edge-tts（微软）与 Vosk 等境外服务；模型下载走 ghfast.top 国内镜像。

### 手动触发对话（不喊唤醒词也能开始）

除了 KWS 语音唤醒，助手内置两条等价的手动触发通道（`voice_config.yaml` 的 `trigger` 段）：

- **键盘**：终端运行时直接按回车。
- **HTTP**（默认 `http://0.0.0.0:8101`）：
  - 手机/浏览器开 `http://<香橙派IP>:8101/`，页面上有大按钮；
  - 命令行：`curl http://<香橙派IP>:8101/trigger`（POST 亦可，可用请求头
    `X-Trigger-Source: gpio-button` 标记来源）；
  - 香橙派物理按键：GPIO 守护进程检测到按下时 `curl` 一下 `/trigger` 即可接入；
  - `GET /state` 查当前状态（IDLE/COMMAND/THINKING/FOLLOWUP）。

手动触发会立即打断正在播放的回答（barge-in）并丢弃触发前的半句录音，响一声提示音后进入听指令状态。
stdin 被重定向（后台运行）时键盘通道自动禁用，不会误触发。

### ASR 热词（智能家居词汇提准）

`models/sherpa/asr/hotwords.txt` 内置 51 个高频词（开灯/关灯/红色/蓝色/开门/风扇调到/
蜂鸣器/现在多少度/回家模式…），解码时自动加权（配合 `modified_beam_search`）。
想加自家设备的叫法（如"小爱""客厅灯"），直接按"字 空格 分 隔"每行一个编辑该文件，重启生效；
权重在 `sherpa.asr.hotwords_score`（1.5~3，过大会误识）。

### 工具调用能力（Qwen2.5-3B 压测）

2026-09-29 流式工具调用压测（temperature=0.3，本地 CPU，3B q4_k_m）：

| 指令 | 1.5B | 3B | 解析出的调用 |
|------|------|----|-------------|
| 把灯调成红色 | ✅ | ✅（连测 4/4） | `light({"action":"red"})` |
| 风扇调到150 | ✅ | ✅ | `fan({"speed":150})` |
| 帮我开一下门 | ❌ 只回文本 | ✅ | `door({"action":"open"})` |
| 现在屋里多少度 | ❌ 只回文本 | ✅ | `get_sensor_status({})` |
| 把窗户打开 | — | ✅ | `window({"action":"open"})` |
| 蜂鸣器响一下 | — | ✅ | `buzzer({"action":"on"})` |

3B 修复了 1.5B 在**隐式动作**和**查询类**指令上的短板，故作为默认模型。
`qwen_server.py` 仍保留三层工具解析兜底：① system 注入带示例的调用规则；
② 支持 `<tool_call>` 标签 / 裸 JSON / `{{...}}` 双括号变体；③ 流式收尾全文扫描合法 JSON。
小模型偶发采样出半截 JSON 时，助手会以自然语言提示，重说一次即可。

模型档位自由切换（GGUF 同协议，改配置即可）：
- 追求低占用：`py -3.13 download_qwen.py --repo Qwen/Qwen2.5-1.5B-Instruct-GGUF --quant q4_k_m`
- 想要更强（香橙派 CPU 偏慢，建议走云）：`llm.mode: dashscope` + `dashscope_key.txt`，
  可用 qwen2.5-7b/14b-instruct 等，零本地算力。

### 更新记录

- **2026-09-29（晚）**：3B 模型 + 交互体验迭代。
  - LLM 默认升为 **Qwen2.5-3B-Instruct q4_k_m**（~2GB）：隐式动作/查询类工具调用修复，六指令压测全过。
  - **手动触发接口**：终端回车 + HTTP（`/trigger`、`/state`、手机网页大按钮），
    供香橙派 GPIO 实体按键/外部系统接入；手动触发可打断 TTS 播报。
  - **ASR 热词**：51 个智能家居高频词加权（自动切 modified_beam_search），热词文件可自行增删。
  - **唤醒提示音**：默认改为零延迟"滴"声（`wake.ack_mode: chirp/voice/both/none` 可配），
    不再等"在的"合成；修复 stdin EOF 时键盘触发空转误唤醒。
- **2026-09-29**：面向香橙派 AI Pro（昇腾 NPU）落地纯 CPU 链路。
  - 语音前端由 Vosk + edge-tts 切换为 **Sherpa-ONNX**（KWS 声学唤醒 + 流式 Zipformer 中英双语
    INT8 ASR + 本地 VITS TTS），模型由 `download_sherpa_models.py` 一键下载（ghfast.top 镜像）。
  - 移除 CUDA 编译/检测逻辑，llama-cpp-python 统一 CPU 版；`sherpa_listener.py` 按
    `joiner.onnx` 有无自动分派 transducer/paraformer。
  - JSON 板子交互链路（MCP 8 工具独占串口）保持不变。
- 更早：Qwen2.5（ModelScope 国内渠道）替换 Ollama/Gemma；MCP 工具调用 3 轮上限；
  TTS 播放期间跳过唤醒检测；8 秒 FOLLOWUP 追问窗口。

---

## 常见问题

### 串口被占用（PermissionError / 拒绝访问）

串口同一时刻只能被一个程序打开。若报 `拒绝访问`，先关闭其他占用串口的程序（包括之前启动的 Python 进程）。

### 命令发送过快导致错位

OLED 轮播连发多行命令时，若 B 板固件处理不过来会导致命令错位。已在 `oled_carousel.py` 中内置**逐行 30ms 节流** + **仅发送变化行**，正常使用即可。

### B 板 JSON 命令 parse_error（已修复）

~~B 板固件曾存在 JSON 解析 bug（所有 JSON 命令返回 `parse_error`）~~ 已修复：根因是 Uno 2KB RAM 下
ArduinoJson 7 的堆分配必然失败（详见 `module-b-output/src/core/CommandParser.cpp` 头部注释），
现固件改用零分配解析器，JSON 与冒号命令均已实测正常。DSL 动作继续使用 `B:XXX` 文本命令亦无问题。

---

## 与其它模块的关系

```text
                    ┌─────────────┐
                    │  PC_Test    │  本目录：直接串口，用于调试与本地自动化
                    └─────────────┘
                           │ USB 串口
              ┌────────────┴────────────┐
              │  Module A（传感器）      │  Module B（执行器）
              └─────────────────────────┘

生产部署走 gateway/（串口↔MQTT）+ Home Assistant，见根目录 README。
```
