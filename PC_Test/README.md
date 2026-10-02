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
├── web_config.yaml         # ⑤ Web 仪表盘配置（串口/端口/语音地址/人脸/开门联动）
│
├── test_serial.py          # ① 串口调试控制台（交互式，手动发命令测试硬件）
├── camera_stream.py        # ③ USB 摄像头流式传输 + 人脸检测（本地窗口 / HTTP 流）
├── camera_test.py          #    摄像头快速自检（验证摄像头 + 检测链路）
│
├── voice_assistant.py      # ④ 语音交互模式（唤醒词 → Qwen3.5 → 经 ⑤ 的 HTTP 网关控硬件 → 流式 TTS）
├── qwen_server.py          #    本地 Qwen2.5 OpenAI 兼容服务（llama.cpp 后端；离线兜底，默认不用）
├── download_qwen.py        #    Qwen2.5 权重下载器（ModelScope 国内渠道）
├── mcp_home_server.py      # 智能家居 MCP server（⑤ 的 stdio 子进程：独占串口，暴露 13 个工具；④ 经 ⑤ 用它）
├── tts_player.py           #    流式 TTS 播放器（Sherpa-ONNX VITS 本地合成）
├── sherpa_listener.py      #    Sherpa-ONNX KWS/ASR 前端封装
├── voice_config.yaml       #    语音模式配置（web 网关地址/LLM 引擎/唤醒词/TTS 音色）
├── llm_key.txt             #    云端 LLM 的 API Key（粘贴 sk-xxx 即生效；已 gitignore + dockerignore）
├── siliconflow_key.txt     #    （备选）按服务商分的 Key 文件，llm_key.txt 不存在时才会读
├── dashscope_key.txt       #    （历史名）同上，仍可用
│
├── run_web.py              # ⑤ Web 仪表盘服务入口（Flask + 全系统唯一硬件网关，http://localhost:5000）
├── web/                    #    Web 服务包（数据库 + REST API + 人脸识别 + 硬件网关 + 前端）
│   ├── app.py              #    Flask 应用工厂（蓝图注册 / 错误处理 / 硬件桥启停）
│   ├── config.py           #    路径常量 + web_config.yaml 装载
│   ├── database.py         #    SQLite 持久层（仅真实硬件数据，含迁移/WAL/校验）
│   ├── hardware.py         #    MCP 硬件桥（stdio 拉起 mcp_home_server 独占串口，轮询入库 + 健康度）
│   ├── ha_client.py        #    可选 Home Assistant REST 客户端（硬件管理页）
│   ├── voice_client.py     #    语音助手 HTTP 客户端（唤醒/文本指令/对话实况 SSE 代理，与硬件无关）
│   ├── utils.py            #    节流 / 安全 Base64 / 连接健康 / 重试
│   ├── api/                #    REST 蓝图：status / devices / access / face / ha / pages / automation
│   ├── face/               #    人脸引擎：YOLOv8-face 检测 + ArcFace/灰度嵌入识别
│   ├── automation/         #    积木式自动化引擎（规则 JSON + 全局状态 + OLED 轮播）
│   ├── templates/          #    前端页面（dashboard/history/access/hardware/automation）
│   └── static/             #    前端资源（css/js，Chart.js 图表）
├── scripts/
│   └── enroll_faces.py     #    人脸注册：data/face/authorized/<姓名>/ → embeddings.pkl
├── data/                   #    运行时数据（不入库）：smart_home.db、face/、ha_config.json
├── models/                 #    模型权重（不入库）：qwen/、sherpa/、face/yolov8n-face.pt
```

---

## PC 端工具一览

| 工具 | 用途 | 什么时候用 |
|------|------|-----------|
| `test_serial.py` | 手动发命令测试单块板 | 排查硬件、验证某个传感器/执行器是否正常 |
| `camera_stream.py` | USB 摄像头流式传输 + 人脸检测 | 视频监控、人脸识别（香橙派部署用 HTTP 流） |
| `voice_assistant.py` | 语音交互（KWS 唤醒 + Qwen2.5 + 经 Web 网关控硬件） | 说「Hey Bota」唤醒（或键盘打字/HTTP 下发），自然语言控制硬件；**不占串口** |
| `run_web.py` | Web 仪表盘（监控 + 控制 + 门禁 + 人脸 + 积木自动化）+ **唯一硬件网关** | 浏览器访问 http://localhost:5000，日常使用的主界面；A/B 串口归它 |
| `start_all.py` | **一键启动联动栈**：Web 网关（持串口）→ 语音助手 → 摄像头流 | 三者要同时运行时用（或双击 start_all.bat） |

> **自动化统一入口**：所有联动规则走 Web 积木引擎（`/automation` 页面，Blockly「当触发→如果条件→执行动作/否则切换」）。
> 传感器、事件（触摸/按键/红外/RFID/人脸/手动操作）作为触发积木，门/窗/灯/风扇/蜂鸣器/OLED/全局状态/语音作为执行积木；
> 全局状态变量也能当条件读（「📌 状态」专用条件积木），每个变量本身是自动化页的一条积木条目；
> 「自动/手动/离家」不再是引擎内置状态机，而是积木读写的全局状态变量（详见下文「全局状态」）。
> 历史 DSL 脚本（`.auto`）与独立 `run_automation.py`、`link_server.py` 已移除，不再维护。

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

## ② 积木式自动化（Web /automation）

自动化统一入口：`run_web.py` 启动后访问 **http://localhost:5000/automation**，用 Blockly
积木可视化编排「当触发 → 如果条件（可多个） → 执行动作（依次）/ 否则切换」。

- **触发块**：数值判断（温度/湿度/光照/烟雾/雨水 + 任何 number 型全局状态）、布尔判断（PIR/触摸 + 任何 bool 型全局状态）、设备状态（门/窗/灯/风扇/空调，以及 enum 型全局状态如 `g:全屋模式`）、其它事件、周期（每 N 秒）、定时（HH:MM）；输入事件按来源各一块——触摸键、矩阵键盘、红外遥控、RFID 刷卡、手动操作、人脸授权；传感器触发可设「持续 N 秒」防止误触发；
- **条件块**：门/窗/灯/风扇状态，以及「📌 状态」三块专用条件（是/否、数值比较、选项等于）——全局状态不只能动，也能作为判断条件读；条件可叠加（全部/任一）；
- **执行块**：门、窗、灯（亮度/颜色）、风扇（转速）、空调、蜂鸣器、OLED 屏、等待、语音助手唤醒/播报，以及「设置全局状态」（布尔/取反/数值/枚举/文本五种写法）；
- **全局状态**：自由命名变量（bool/number/enum/text），在列表页与规则**并列**成为一条「📌 状态」条目——工具栏「📌 ＋ 新建状态」打开的是一块顶层「状态定义」积木（名字 + 类型 + 当前值），改名/改选项/删除都在这块积木里做。条目卡片只显示当前值，不给手动改值控件：值由规则里的「设置全局状态」积木维护，只有定义积木的「当前值」会在保存定义时写一次（用于放开安全线这类一次性操作）。积木读写、掉电保存（`data/global_state.json`）。原来的「自动/手动/离家」引擎状态机已拆除，就是这里的 `g:全屋模式` 条目；手动优先由 `manual_mark_*`/`manual_clear_*` 规则维护 `g:手动优先_设备`；`g:允许自动开风扇` 默认「否」＝风扇只能手动开，要放开就改这条状态定义的当前值；
- 每条规则可独立启停、设冷却秒数；内置 28 条默认规则（高温控风扇、光敏调光、雨水关窗、烟雾报警、人脸开门、离家关全屋、触摸键切模式、手动优先窗口等）默认注入，可编辑/停用/删除，可「恢复内置规则」。
- 执行记录与规则判定实时预览见同页。

> 历史 `.auto` 文本 DSL、`run_automation.py`、`link_server.py` 已移除，全部统一到本积木引擎。

---

## ③ camera_stream.py — USB 摄像头流式传输 + 人脸检测

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

# 指定摄像头（只作优先候选，不在位时仍会自动枚举其它设备）
py -3.13 camera_stream.py --cam 0            # 按索引
py -3.13 camera_stream.py --cam /dev/video1   # 按设备节点（Linux）
py -3.13 camera_stream.py --cam "Web Cam"     # 按名称（Windows/DSHOW）
```

**交互按键**（本地窗口模式）：

| 按键 | 作用 |
|------|------|
| `q` | 退出 |
| `s` | 保存当前帧为 `captured_<时间戳>.jpg` |

**摄像头发现策略**：`--cam` / `CAMERA_DEVICE` > 当前所有 `/dev/video*`（Linux，每轮重新枚举）
> 名称 `"Web Cam"` > 索引 `0~4`（开发机）。

**热插拔**：没插摄像头也照常起服务；采集线程读帧失败就释放旧句柄、退避后重新枚举重开
（1s 起指数增长，封顶 10s）。`GET /health` 给出 `{online, device, frame_age_s, error, capture_alive}`；
没有新鲜帧时 `/video_feed` 发「NO CAMERA」占位帧，因此页面能看到原因而不是白屏空转。
注意这台 UVC 摄像头**同一时刻只允许一个进程打开**：被别的容器/进程占着时会持续重试，
等对方释放后自动接上。

**快速自检**（先确认摄像头可用再上流）：

```powershell
py -3.13 camera_test.py              # 自动发现摄像头，读 5 帧
py -3.13 camera_test.py --cam 0 --frames 10
```

> 香橙派部署提示：`--mode web` 会用 Flask 起 MJPEG 流，浏览器打开 `http://<香橙派IP>:8080` 即可实时查看，
> 无需图形界面。HTTP 服务与摄像头采集在不同线程运行，互不阻塞。

---

## ④ voice_assistant.py — 语音交互模式（唤醒词 + Qwen2.5 + Web 硬件网关）

对着麦克风说唤醒词「**Hey Bota**」（或直接键盘打字 / HTTP 下发指令），
再说一句指令（如「把灯调成蓝色」「现在多少度」），
**Qwen2.5 大模型**理解意图后，通过 ⑤ Web 的硬件网关控制 Arduino Module B，回复用流式 TTS 播放。

**数据流**：

```text
麦克风 ──Sherpa-ONNX──▶ KWS 声学唤醒「Hey Bota」──▶ 切 COMMAND + 滴声提示
                        流式 ASR 整句 ──▶ 用户指令 ──▶ 切 IDLE
键盘打字回车 / HTTP POST /say ─────────┘
用户指令 ──Qwen3.5(默认云端硅基流动) 流式 + 工具调用──▶ delta.content 按句喂 VITS TTS（边生成边播）
                                  └─ tool_calls ──HTTP──▶ ⑤ web POST /api/hardware/tool
                                                            └─ MCP ──▶ mcp_home_server ──▶ Module B
```

语音前端为 **Sherpa-ONNX**（全离线，同栈可直接移植香橙派）：
KWS 关键词声学唤醒（zipformer-wenetspeech 3.3M）+ 流式 ASR（streaming Zipformer 中英双语 INT8，
自带端点检测）+ 本地 VITS 语音合成（vits-melo-tts-zh_en）。
模型一键下载：`py -3.13 download_sherpa_models.py`（KWS ~31MB / ASR ~1GB / TTS ~160MB，国内镜像加速）。

`mcp_home_server.py` 是 **⑤ web 的 stdio 子进程**，由它独占 A/B 两串口，暴露 13 个工具：
`light / door / window / fan / buzzer / oled / display / ir / ac / get_sensor_status /
get_serial_health / get_output_state / self_test`。
（`ir` 为红外发射，发 NEC 码控家电；`ac` 生成美的空调状态帧并走 `send_midea` 发射；
`display` 对应已移除的 TM1637 数码管，属保留接口，当前固件会返回 error；
`get_output_state` / `self_test` 是只读诊断：前者给 B 板硬件回读，后者给固件侧自检
——排查「灯不亮 / 风扇自转」时先用它们把故障定位到层次。）

`voice_assistant.py` **完全不碰串口，也不自己起 MCP 进程**：启动时 `GET /api/hardware/tools`
取工具清单喂给大模型，工具调用一律 `POST /api/hardware/tool`（带 `source=voice`）。
web 既是执行者也是记账者，所以语音与面板的状态、历史、`manual_control`（全屋切手动）
事件**天然等价**，无需任何回传对账。

### LLM 引擎：Qwen3.5 / Qwen2.5（国内合规）

> ⚠️ 已移除 Ollama。当前引擎为 **Qwen3.5 / Qwen2.5**，云端与本地权重均走国内合规渠道，
> 三种模式可切换（`voice_config.yaml` → `llm.mode`，也可用环境变量 `SMART_HOME_LLM_MODE` /
> 命令行 `--llm-mode`）：

| 模式 | 说明 | 渠道/合规 |
|------|------|----------|
| `siliconflow`（**默认**） | 硅基流动 SiliconFlow 的 OpenAI 兼容端点（免本地算力）。本地 3B 在纯 CPU 上太慢，故默认走云端 | 国内云服务商；需 API Key（[申请地址](https://cloud.siliconflow.cn/account/ak)），默认模型 `Qwen/Qwen3.5-4B` |
| `dashscope`（备选云端） | 阿里云百炼 OpenAI 兼容端点，同为免算力方案 | 阿里云国内云服务；需 API Key（[申请地址](https://bailian.console.aliyun.com/)），如 `qwen-plus` |
| `local`（离线兜底） | 本地推理（全程离线），`qwen_server.py` 提供 OpenAI 兼容服务（llama.cpp 后端） | 权重经**魔搭社区 ModelScope**（阿里，modelscope.cn）下载；推理全程本地无外部服务 |

**云端 Key 三种给法（任选其一，优先级从高到低）**：① config `llm.api_key`；
② 环境变量 `LLM_API_KEY` / `SILICONFLOW_API_KEY` / `DASHSCOPE_API_KEY`；
③ 粘贴到 `PC_Test/llm_key.txt`（推荐，已入 .gitignore + .dockerignore；也认
`siliconflow_key.txt` / `dashscope_key.txt`，第一行非 `#` 内容即 Key）。
切到本地模式只需改 `llm.mode: "local"`——端点和模型名会自动纠正，无需改 base_url。

**模型选择**：默认 `Qwen/Qwen3.5-4B`（硅基流动模型广场里的 id，4B 级工具调用够用且快）；
想换名直接去广场复制（`llm.model` 一处即可）；走百炼则填 `qwen-plus`（工具调用与中文效果稳）、
快而省用 `qwen-turbo`，零本地算力。
想更强可填 `qwen2.5-7b-instruct` / `qwen2.5-14b-instruct`，零本地算力。
只有必须离线时才走 `local`：默认权重 `Qwen2.5-3B-Instruct`（q4_k_m 量化，~2GB，
工具调用成功率在小模型里最稳，见下方压测表），香橙派多核 ARM CPU 纯 CPU 可跑但首字延迟明显。

**Qwen3.5 是「思考型」模型**：不关思考会先把 `reasoning_content` 流完才吐正文，
语音场景首字实测 20~60s；客户端对硅基流动默认带顶层 `enable_thinking: false`
（实测 ~1s，工具调用不变）。要开思考或加别的请求参数用 `llm.extra_body` 覆盖，
注意硅基流动不认 vLLM 那套 `chat_template_kwargs` 写法。
追求极致低占用可换 **Apache-2.0**（商业友好）的 1.5B：
`py -3.13 download_qwen.py --repo Qwen/Qwen2.5-1.5B-Instruct-GGUF --quant q4_k_m`，
并同步改 `voice_config.yaml` 的 `llm.model` / `llm.local.gguf_path`。

### 环境准备

**一键部署（推荐）**：

```powershell
# 双击 deploy_voice.bat，或在终端执行：
cd PC_Test
powershell -ExecutionPolicy Bypass -File deploy_voice.ps1
```

脚本会自动：装 Python 依赖（阿里云 PyPI 镜像）→ 备好本地 llama.cpp 与 Qwen2.5 权重（**离线兜底**才用得上）→ 下载 Sherpa-ONNX 语音模型（KWS+ASR+TTS）→ 运行自检。

日常启动用 [start_voice.bat](start_voice.bat)（双击即可：默认按云端模式（硅基流动）启动助手，
`llm.mode: local` 时会自动拉起本地 Qwen 服务）。

> 语音助手要能控硬件，前提是 **⑤ Web（`run_web.py`）在跑**——它是唯一的硬件网关。
> web 没起时助手仍能对话，但工具调用会报「硬件网关不可达」。
> 三件套一起跑直接用 ⑥ `start_all.py`（它会先起 web）。

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

**② 下载 Qwen2.5 权重**（ModelScope 国内渠道，3B q4_k_m ~2GB；**只有 `llm.mode: local` 离线兜底才需要**）：

```powershell
py -3.13 download_qwen.py     # Qwen/Qwen2.5-3B-Instruct-GGUF q4_k_m（~2GB）→ models/qwen/
```

**③ 启动本地 Qwen 服务**（仅 `local` 模式；每次使用前，或交给 start_voice.bat 自动拉起）：

```powershell
py -3.13 qwen_server.py       # 监听 http://127.0.0.1:8000/v1，加载约 10~30 秒
```

> 提示：
> - **纯 CPU 推理（与香橙派一致）**：`voice_config.yaml` 的 `llm.local.n_gpu_layers: 0`。
>   目标机香橙派 AI Pro 的昇腾 NPU 目前 llama.cpp / Sherpa-ONNX 均无可用后端（Sherpa ACL 面向 Ascend 910），
>   CPU + 3B-Q4 + ASR INT8 已满足实时链路；NPU 加速属后期优化（交叉编译 + ACL 上下文绑定）。
> - Windows/Py3.13 若无预编译轮子会自动源码编译 CPU 版（需 VS Build Tools / VS2022 C++，约 3~10 分钟）。
> - 引擎可用 `py -3.13 qwen_server.py --smoke` 做冒烟验证（输出 `[SMOKE_OK] device=CPU`）。
> - ②③ 两步默认**不需要**：现引擎是云端硅基流动（`llm.mode: siliconflow`），只有断网/不想用云时才走本地。

**④ 配置网关与个性化**：复制配置做本地定制（不入库）：

```powershell
copy voice_config.yaml voice_config.local.yaml
# 编辑 voice_config.local.yaml：gateway.url（web 硬件网关）、llm.mode/model、wake.words 等
# A/B 串口不在这里配——串口归 web，改 web_config.yaml 的 serial.port_a/port_b
```

</details>

### 运行

```powershell
# 自检（Sherpa 模型 / 麦克风 / LLM 引擎 / web 硬件网关的工具清单）
py -3.13 voice_assistant.py --self-check

# 验证 LLM：流式对话 + 工具调用探测（需云端 Key 就绪；local 模式需 qwen_server 在跑）
py -3.13 voice_assistant.py --test-llm "你好"

# 列出麦克风设备索引（配置 mic.device_index 用）
py -3.13 voice_assistant.py --list-mic

# 校准唤醒词识别（持续打印 KWS 命中 / partial / final，不调 LLM）
py -3.13 voice_assistant.py --kws-repl

# 启动语音助手（需 ⑤ web 网关在跑；默认云端硅基流动，串口与它无关）
py -3.13 voice_assistant.py

# 手动指定网关 / 模式 / 模型
py -3.13 voice_assistant.py --gateway http://127.0.0.1:5000 --llm-mode local --model qwen2.5-3b-instruct-q4_k_m
```

> ⚠️ **串口互斥在 web 那一侧**：COM 口被 web 拉起的 `mcp_home_server` 子进程独占，
> web 运行期间不要同时跑 `test_serial.py / full_test.py`
> 或 Arduino IDE 串口监视器（会报「拒绝访问」，属 Windows 串口单进程规则，非 bug）。
> 语音助手不占串口，随时可起可停。
> TCP 方面无冲突：Web 5000，语音控制台 8101，Qwen 服务固定 8000，camera_stream 8080。

启动后说「Hey Bota」（发音贴近「黑波塔」）→ 听到滴声 → 说指令；
也可以直接在终端打字回车发送指令。例如：

- 「把灯调成蓝色」→ Module B 灯变蓝 + TTS「已为您把灯调成蓝色」
- 「现在多少度」→ 调 `get_sensor_status` → TTS 回读数
- 「开门」「关风扇」「蜂鸣器响三声」→ 对应工具执行

### 调试 MCP server（独立）

用 MCP Inspector GUI 手动调每个工具，观察 B 板动作与 A 板状态：

```powershell
pip install mcp       # 含 mcp CLI
mcp dev mcp_home_server.py --port-a COM7 --port-b COM6
```

> ⚠️ 这条链路正常由 **⑤ web** 拉起（它是唯一的硬件网关）。手工 Inspector 前请先停掉 web，
> 否则两边抢同一组 COM 口。日常只读排查用 `POST /api/hardware/tool`（见下文 ⑤）。

### 唤醒词说明（Hey Bota）

「Hey Bota」由 Sherpa-ONNX KWS 做声学级唤醒，定义在
`models/sherpa/kws/keywords.txt`。由于 KWS 模型是中文 wenetspeech（拼音音素词表），
英文唤醒词按最近发音拆成拼音声韵母，并放了 4 个声调变体提高命中率：

```text
h ēi b ōu t ǎ @Hey_Bota     ← @ 后名字不能含空格，下划线在代码里还原为 "Hey Bota"
h éi b ōu t ā @Hey_Bota
h ēi b ōu t a @Hey_Bota
h ēi b ō t ǎ @Hey_Bota
```

换唤醒词时直接编辑该文件（每行「音素 空格 分隔 @名字」，音素必须取自同目录 `tokens.txt`），
重启即可；注意 `voice_config.yaml` 的 `wake.words` 也要同步（用于剥连读前缀）。
灵敏度在 `sherpa.kws.keywords_score / keywords_threshold` 调节
（score 调大 / threshold 调小 = 更易唤醒，误唤醒也会增加）。
播放 TTS 期间自动跳过唤醒检测（防喇叭回声误触发）。

### 合规说明

语音链路已全离线境内化：Sherpa-ONNX（KWS/ASR/TTS）+ Qwen（ModelScope 本地权重 / 硅基流动、百炼国内云端），
不再依赖 edge-tts（微软）与 Vosk 等境外服务；模型下载走 ghfast.top 国内镜像。

### 手动输入：键盘文字对话 + HTTP 接口（不喊唤醒词也行）

除 KWS 语音唤醒外，助手内置两类手动输入通道（`voice_config.yaml` 的 `trigger` 段）：

- **键盘双通道**（终端运行时）：
  - 直接**打字后回车** → 文本指令，绕过麦克风直接送给大模型（安静环境/调试/没带麦时用）；
  - **只按回车（空行）** → 开启语音监听，等价于喊唤醒词。
- **HTTP**（默认 `http://0.0.0.0:8101`，零额外依赖，标准库实现）：
  - 手机/浏览器开 `http://<香橙派IP>:8101/`：**聊天式控制台**（深色对话界面）——点麦克风按钮开语音、
    输入框直接打字发送，并把每一轮的识别中/用户句/助手回复/工具调用**实况**流式显示出来；
  - 开语音监听：`curl http://<香橙派IP>:8101/trigger`（POST 亦可）；
  - **直接下发文本指令**（外部系统/Home Assistant/任何程序都能对话控家）：

    ```bash
    curl -X POST http://<香橙派IP>:8101/say \
         -H "Content-Type: application/json" \
         -d '{"text":"把灯打开"}'
    curl "http://<香橙派IP>:8101/say?text=把灯打开"      # GET 形式，适合极简 IoT 设备
    ```
  - **对话实况（SSE）**：`curl -N http://<香橙派IP>:8101/events`，事件类型
    `hello / state / partial / user / delta / tool / turn_end / system`（空闲 15s 发 `: ping` 心跳）；
    Web 面板同源代理为 `GET http://<IP>:5000/api/voice/events`；
  - 香橙派物理按键：GPIO 守护进程按下时 `curl` 一下 `/trigger` 即可接入（可用请求头
    `X-Trigger-Source: gpio-button` 标记来源）；
  - `GET /state` 查当前状态（IDLE/COMMAND/THINKING/FOLLOWUP）。

> 语音助手**不再有 `/tool` 端点**：直调硬件请用 web 网关
> `POST http://<IP>:5000/api/hardware/tool`（清单见 `GET /api/hardware/tools`）。

无论是键盘还是 HTTP 文本，都会立即打断正在播放的回答（barge-in）、丢弃半句旧录音后进对话；
文本指令不受"先唤醒"限制，随时可发。stdin 被重定向（后台运行）时键盘通道自动禁用，不会误触发。

### ASR 热词（智能家居词汇提准）

`models/sherpa/asr/hotwords.txt` 内置 51 个高频词（开灯/关灯/红色/蓝色/开门/风扇调到/
蜂鸣器/现在多少度/回家模式…），解码时自动加权（配合 `modified_beam_search`）。
想加自家设备的叫法（如"小爱""客厅灯"），直接按"字 空格 分 隔"每行一个编辑该文件，重启生效；
权重在 `sherpa.asr.hotwords_score`（1.5~3，过大会误识）。

### 工具调用能力（本地 Qwen2.5-3B 压测）

2026-09-29 流式工具调用压测（temperature=0.3，本地 CPU，3B q4_k_m）：

| 指令 | 1.5B | 3B | 解析出的调用 |
|------|------|----|-------------|
| 把灯调成红色 | ✅ | ✅（连测 4/4） | `light({"action":"red"})` |
| 风扇调到150 | ✅ | ✅ | `fan({"speed":150})` |
| 帮我开一下门 | ❌ 只回文本 | ✅ | `door({"action":"open"})` |
| 现在屋里多少度 | ❌ 只回文本 | ✅ | `get_sensor_status({})` |
| 把窗户打开 | — | ✅ | `window({"action":"open"})` |
| 蜂鸣器响一下 | — | ✅ | `buzzer({"action":"on"})` |

3B 修复了 1.5B 在**隐式动作**和**查询类**指令上的短板，故作为**本地模式**的默认模型；
云端（默认引擎）走 `Qwen/Qwen3.5-4B`（备选百炼 `qwen-plus` / `qwen-turbo`），工具调用成功率与首字延迟都更好。
`qwen_server.py` 仍保留三层工具解析兜底：① system 注入带示例的调用规则；
② 支持 `<tool_call>` 标签 / 裸 JSON / `{{...}}` 双括号变体；③ 流式收尾全文扫描合法 JSON。
小模型偶发采样出半截 JSON 时，助手会以自然语言提示，重说一次即可。

模型档位自由切换（GGUF 同协议，改配置即可，仅 `llm.mode: local` 时相关）：
- 追求低占用：`py -3.13 download_qwen.py --repo Qwen/Qwen2.5-1.5B-Instruct-GGUF --quant q4_k_m`
- 想要更强（香橙派 CPU 偏慢，也正因如此默认走云）：默认 `llm.mode: siliconflow` + `llm_key.txt`，
  模型广场里换个 id 即可（如更大的 Qwen 或 DeepSeek）；要用阿里云百炼就 `llm.mode: dashscope`，
  可用 qwen2.5-7b/14b-instruct 等，零本地算力。

### 更新记录

- **2026-09-29（深夜）**：唤醒词改「Hey Bota」+ 键盘/HTTP 文本对话。
  - 唤醒词由「你邮你邮」改为英文 **Hey Bota**：中文 KWS 模型用拼音音近拼接
    （`h ēi b ōu t ǎ` 等 4 个声调变体，绕开 @ 名禁空格限制，下划线在代码层还原）；
    前缀剥离改为大小写/空格/标点归一化匹配。
  - **键盘文字对话**：终端直接打字回车即把文本送 LLM（无需唤醒、无需麦克风），
    空回车仍为开启语音监听。
  - **HTTP /say 接口**：`POST /say {"text":"..."}` / `GET /say?text=...` 直接下发文本指令，
    供外部程序、Home Assistant、其他 IoT 系统对接控家；网页控制台同步加文本输入框。
  - 已实测：文本指令端到端（LLM 回复 + TTS + 工具调用无板容错）、6 条前缀剥离去例、
    HTTP 端点 POST/GET/空值/来源头。
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
  - JSON 板子交互链路（MCP 9 工具独占串口）保持不变。
- 更早：Qwen2.5（ModelScope 国内渠道）替换 Ollama/Gemma；MCP 工具调用 3 轮上限；
  TTS 播放期间跳过唤醒检测；8 秒 FOLLOWUP 追问窗口。

---

## ⑤ run_web.py — Web 仪表盘 + 硬件网关（监控 / 控制 / 门禁 / 历史）

合并自协作组的数据库、Flask 前端和 YOLO 人脸识别三部分，重构为本目录下的 `web/` 包，
作为 PC_Test 的标准服务之一。它同时是**全系统唯一的硬件网关**：A/B 串口只归它。
浏览器访问 **http://localhost:5000**：

| 页面 | 路由 | 功能 |
|------|------|------|
| 仪表盘 | `/` | 实时传感器卡片、门/窗/灯/风扇控制、温湿度曲线 |
| 门禁管理 | `/access` | 授权人员（人脸/RFID）、识别记录、人脸照片上传识别 |
| 历史记录 | `/history` | 传感器历史、设备操作日志、图表查询 |
| 硬件管理 | `/hardware` | 硬件桥状态、可选 Home Assistant 对接配置 |

```powershell
# 正常启动（自动探测 A/B 串口；也可在 web_config.yaml 写死）
py -3.13 run_web.py

# 指定端口 / 串口
py -3.13 run_web.py --host 0.0.0.0 --port 5000 --port-a COM7 --port-b COM6

# 演示降级：不开串口、不拉 MCP 子进程（纯看板，硬件控制与 /api/hardware/tool 返回 503）
# 只用于桌面体验 / 无板子演示，正常部署不要用
py -3.13 run_web.py --no-serial
```

**架构（串口安全是重点）**：Web 进程**绝不直接打开 COM 口**——串口由它拉起的子进程持有。
启动时由硬件桥（[web/hardware.py](web/hardware.py)）以 stdio 方式拉起 `mcp_home_server.py`，
通过 MCP 协议操作硬件，并把这套能力经 HTTP 开放给语音助手与外部程序：

```text
浏览器 ──HTTP── Flask(web/ 蓝图) ──MCP stdio── mcp_home_server.py ──USB── A/B 板
    │                 │                        （独占串口，13 个工具）
    │                 ├── 每 2s get_sensor_status 轮询 → data/smart_home.db
    │                 │        └─ 每 10s 刷新 get_serial_health / B 板回读
    │                 └── GET /api/hardware/tools ＋ POST /api/hardware/tool
    │                          ▲
 ④ 语音助手 ──────HTTP（source=voice，执行 + 记账一步到位）
```

- 设备控制（门/窗/灯/风扇）必须先收到 MCP ACK 才写库；MCP 离线返回 **503**，不产生假状态。
- `POST /api/hardware/tool` 执行成功后做**与面板点击完全相同**的记账：更新 SQLite 状态、
  写历史、广播 `manual_control`（全屋切手动）；因此语音控制与面板控制天然一致，
  不再需要 `manual_report` 二段式回传（该端点只留给外部系统补记账）。
- 传感器快照由后台线程轮询入库（按 timestamp 去重），页面只从 SQLite 读数。
- MCP 子进程断线自动重连（指数退避 1→30s）；父进程退出后子进程随 stdin EOF 自动退出。
- 配置在 [web_config.yaml](web_config.yaml)；运行时人脸配置写入 `data/face/face_config.json`（其优先级高于 yaml）。
- 可选项：在硬件管理页配置 Home Assistant（配置存 `data/ha_config.json`，默认不含任何密钥）。

**串口互斥**：A/B 口在 web 的 MCP 子进程手里，所以**只有 web 会与 `test_serial.py /
full_test.py / Arduino IDE 串口监视器`抢口**。④ `voice_assistant.py` 完全不碰串口，
与 web 随时可以同时运行；单独跑调试脚本时才需要先停 web。
两者（+摄像头流）要一起用时直接用 ⑥ `start_all.py`。

### 人脸识别（YOLOv8-face + ArcFace）

当前 `web_config.yaml` 已启用**真实模式**（`face.simulation_mode: false`）：

- 检测：YOLOv8n-face（`models/face/yolov8n-face.pt`，ultralytics 推理，CPU 即可）。
- 身份识别：ArcFace ONNX（`models/face/recognition.onnx`，~174MB，onnxruntime CPU 推理）。
- 已注册 `person_01`、`person_02`（`data/face/authorized/`，各 10 张），
  实测 20/20 检出、20/20 身份正确，相似度 0.61~0.82（阈值 0.5）。

依赖安装（首次启用时）：

```powershell
py -3.13 -m pip install ultralytics onnxruntime
```

新增可识别人员：

```powershell
# 1. 每人 5~10 张不同角度/光线的正脸照放到 data/face/authorized/<姓名>/
# 2. 重新生成嵌入库
py -3.13 scripts/enroll_faces.py
#    零依赖快速回退方案（精度一般）：--method simple_grayscale_cosine
# 3. 重启 run_web.py；识别 face_id 即目录名
```

- 已授权人脸识别通过且 `door.open_on_face_grant: true` 时，硬件桥在线即自动开门并记录；
  门禁页需用相同 face_id（如 `person_01`）添加授权人员。
- 未识别照片存 `data/face/unauthorized/`；嵌入文件 `data/face/embeddings.pkl`。
- 运行时人脸设置保存在 `data/face/face_config.json`，**优先级高于 yaml**；
  改 yaml 不生效时删掉该 json 重启即可（会按 yaml 重建）。
- YOLO/ArcFace 加载失败（如未装 ultralytics）会自动回退模拟模式并在 `/api/face/status` 标明；
  想先演示界面可把 `simulation_mode` 改回 `true`（返回 FACE001/002/003）。

运行时数据全部在 `data/`（SQLite、人脸配置、注册照片、嵌入文件，已在 .gitignore 中）；
模型权重在 `models/face/`（同样不入库，recognition.onnx 可从根目录
`yolo_face_detection 3.zip` 重新解压获得）。

---

## ⑥ start_all.py — 一键启动「语音 + 人脸识别 + 摄像头流」

语音助手、Web 人脸识别、摄像头视频流三者一起运行的联动栈，一条命令（或双击
[start_all.bat](start_all.bat)）：

```powershell
py -3.13 start_all.py                                  # 全部启动
py -3.13 start_all.py --port-a COM7 --port-b COM6 --cam 0   # 指定串口/摄像头
py -3.13 start_all.py --camera-mode both               # 摄像头同时弹本地窗口
py -3.13 start_all.py --no-camera                      # 不起摄像头
```

启动后：

| 服务 | 地址 | 说明 |
|------|------|------|
| Web 仪表盘 / 人脸识别 / **硬件网关** | http://localhost:5000 | YOLO+ArcFace 真实识别、门禁、历史；独占 A/B 串口 |
| 摄像头 MJPEG 视频流 | http://localhost:8080 | 默认 web 模式（无头可访问；被占用可 `--camera-port` 改） |
| 语音助手控制台 | http://localhost:8101 | 聊天式界面：唤醒/对话 + `GET /events` 对话实况（硬件动作经 Web 网关） |
| 本地 LLM | http://localhost:8000/v1 | qwen_server.py，**仅 `--llm-mode local` 时启动**（默认云端硅基流动，不拉起） |

**串口归属与开门联动（关键设计）**：A/B 串口同一时刻只能一个进程占用，因此联动栈里

- **串口归 Web**：`run_web.py` 拉起 `mcp_home_server.py` stdio 子进程独占 A/B 口，
  它是全系统唯一的硬件入口（`--port-a/--port-b` 就是传给它的）；
- **语音助手不碰串口**：启动时 `GET /api/hardware/tools` 取工具清单，工具调用
  `POST /api/hardware/tool`（`source=voice`）——所以两者可以同时跑，且状态、历史、
  「全屋切手动」事件与面板点击**完全等价**，无需回传对账；
- 「识别到授权人脸自动开门」就在 Web 进程内闭环（积木规则 `face_open_door` → 硬件桥），
  **不经 LLM、不发语音**——室外摄像头识别通过后门直接开，室内不会播报。
  需要语音播报/唤醒时走另一条独立配置：`voice.url`（环境变量 `SMART_HOME_VOICE_URL`，
  启动器注入 `http://127.0.0.1:8101`），它只管「说话」，不管「动手」。
- 启动顺序：先 Web（网关就绪）→ 再语音助手 → 再摄像头；`--llm-mode local` 时最先起本地 Qwen。

```text
摄像头(室外) ──MJPEG :8080──▶ Web(人脸 YOLO+ArcFace)
                                │ 识别到授权人脸 → 积木规则 face_open_door
                                ▼
浏览器 ──:5000──▶ Web 硬件桥 ──MCP stdio──▶ mcp_home_server ──USB──▶ B板开门
                    ▲
语音(室内/手机) ──▶ 语音助手(:8101) ──POST /api/hardware/tool──▶ 同一个 Web 桥
                   （不占串口；:8101/ 聊天界面 + /events 对话实况）
```

生命周期：启动前自动检查 8000/8101/5000/8080 端口占用；各服务就绪后打印地址；
窗口 **Ctrl+C** 会 `taskkill /T` 整个进程树（含 Web 的 mcp_home_server 子进程、llama.cpp），
无孤儿。各服务日志在 `logs/{qwen,voice,web,camera}.log`（已 gitignore）。
无摄像头/无板子时对应服务降级提示，不拖垮其它服务。

---

## ⑦ Docker 部署（推荐在香橙派等 Linux 设备上使用）

与 ⑥ 相同的联动栈，但以容器形态交付，换机器只需装 Docker，不再手工配
Python/依赖。文件：

- [docker-compose.yml](docker-compose.yml)：web(:5000，**独占串口**的硬件网关) +
  voice(:8101，纯 HTTP 客户端) + camera(:8080)；qwen(:8000) 在 `profiles: ["local-llm"]`
  后面，默认**不启动**
- [docker/](docker/)：4 个 Dockerfile（多阶段）+ 各服务独立 requirements
- [docker-compose.local-llm.yml](docker-compose.local-llm.yml)：离线兜底覆盖文件
  （放开 qwen，并把 voice 指到本地 llama.cpp：`SMART_HOME_LLM_MODE=local` +
  `SMART_HOME_LLM_BASE_URL=http://qwen:8000/v1`）
- [docker-compose.desktop.yml](docker-compose.desktop.yml)：Docker Desktop 体验用
  （透传不了串口 → web 降级 `--no-serial`、voice 无麦克风、camera 加 profile 默认不起）
- [docker/.env.example](docker/.env.example)：串口/摄像头/端口/API Key 等环境变量模板

### 架构（容器间关系与 ⑥ 一致）

```text
宿主机 /dev/ttyUSB0|1 ──▶ web 容器（独占串口，内含 mcp_home_server 子进程 + cgroup 放行 /dev）
宿主机 /dev/video0    ──▶ camera 容器（MJPEG :8080，热插拔靠 cgroup + 重新枚举）
宿主机 /dev/snd       ──▶ voice 容器（麦克风/扬声器，ALSA；voice 已不再透传串口）
models/  bind mount  ──▶ web / voice /（local-llm 时的）qwen（模型不进镜像，2GB+）
data/    bind mount  ──▶ web（SQLite、人脸注册照片、embeddings.pkl 持久化）
voice ──SMART_HOME_WEB_URL=http://web:5000──▶ web GET/POST /api/hardware/* ──▶ MCP ──▶ 板子
web   ──SMART_HOME_VOICE_URL=http://voice:8101──▶ voice（唤醒/文本指令/对话实况 SSE 代理）
voice ──默认直连硅基流动（SMART_HOME_LLM_MODE=siliconflow）；local-llm 编排下才 ──▶ qwen
```

### 首次部署（香橙派 / 任意 Linux）

```bash
# 0. 安装 Docker Engine + Compose 插件（官方脚本，arm64 可直接用）
#    curl -fsSL https://get.docker.com | sudo sh
#    sudo usermod -aG docker $USER && 重新登录

# 1. 拿到 PC_Test 目录后，先跑自检脚本：查架构/Docker/串口号/摄像头/声卡/模型，
#    并自动生成 .env（按探测结果填好 SERIAL_PORT_A/B 与 CAMERA_DEVICE）
cd PC_Test
bash scripts/deploy_orangepi.sh --install-docker --gen-env
#    若 Windows 传过来的脚本报 /bin/bash^M 错误： sed -i 's/\r$//' scripts/deploy_orangepi.sh
#    手动核对： cat .env（串口建议用 /dev/serial/by-id/ 稳定路径，插拔顺序不变）

# 2. 准备模型（模型不打进镜像；约 2.6GB，见下节“如何把代码和模型传到香橙派”）
#    models/qwen/qwen2.5-3b-instruct-q4_k_m.gguf（2GB，云端 LLM 可不要）
#    models/sherpa/{kws,asr,tts}/（376MB）、models/face/（172MB）
#    注册照片放 data/face/authorized/<姓名>/

# 3. 构建并后台启动（默认云端 LLM=硅基流动：web 独占串口，voice 只发 HTTP）
#    先把 Key 写进 .env（容器里没有 llm_key.txt，密钥文件已被 .dockerignore 排除）
echo 'LLM_API_KEY=sk-xxxx' >> .env
sudo docker compose up -d --build
#    离线兜底（自建 llama.cpp，首次很慢，aarch64 编译 llama 约 20~40 分钟）：
#    sudo docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up -d --build

# 4. 注册人脸嵌入（在 web 容器里执行；新增人员后重跑+重启 web）
sudo docker compose exec web python scripts/enroll_faces.py
sudo docker compose restart web
```

访问：仪表盘 http://设备IP:5000 ｜ 摄像头流 http://设备IP:8080 ｜
语音控制台 http://设备IP:8101 。

### 如何把代码和模型传到香橙派（从 Windows）

代码本身不大，但 `models/` 约 2.6GB、不进镜像也不进 git，需要单独传。
**推荐方式：局域网 scp 直传（Win10/11 自带 scp，无需装软件）**。

先在香橙派上建好目录（假设用户名 `orangepi`，IP 以实际为准，如 192.168.1.50）：

```bash
ssh orangepi@192.168.1.50 'mkdir -p ~/smart-home'
```

在 **Windows PowerShell**（PC_Test 目录内）执行：

```powershell
# 代码 + 配置（不含 .git/虚拟环境，很小）
scp -r web scripts docker run_web.py voice_assistant.py qwen_server.py `
  mcp_home_server.py camera_stream.py *.yaml *.yml .dockerignore requirements.txt `
  orangepi@192.168.1.50:~/smart-home/

# 模型（约 2.6GB，局域网几分钟；vosk 目录是旧 ASR，不用传）
scp -r models orangepi@192.168.1.50:~/smart-home/

# 已注册的人脸照片 + 嵌入库（也可以到派上重新 enroll，二选一）
scp -r data orangepi@192.168.1.50:~/smart-home/
```

> 也可以用 U 盘拷贝，或在派上直接跑 `python3 download_qwen.py`、
> `download_sherpa_models.py` 现场下载模型（省去传输，但要在派上配 Python 环境）。
> 默认走 siliconflow 云端 LLM 时 qwen 的 2GB 可完全不传，也不起 qwen 容器；
> 只有用 `local-llm` 覆盖文件做离线兜底时才需要。

### 常用命令

```bash
sudo docker compose logs -f voice web   # 跟日志
sudo docker compose restart web         # 改 web_config.yaml 后重启（yaml 只读挂载）
sudo docker compose exec voice python voice_assistant.py --list-mic   # 查麦克风索引
sudo docker compose up -d --scale camera=0   # 无摄像头主机跳过 camera
sudo docker compose down                # 停止全部（数据/模型在宿主机不丢）
```

### 本地 LLM 兜底（无外网 / 不想用云端时）

默认就是云端硅基流动（`.env` 里有 `LLM_API_KEY`，直接 `up -d --build`）。
要改回本地 llama.cpp（香橙派跑不动 3B 时不建议）：

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up -d --build
# 效果：放开 qwen 容器（:8000），voice 的 SMART_HOME_LLM_MODE=local 指向它
```

### 注意事项

- **平台**：Dockerfile 基于 `python:3.12-slim`，arm64（香橙派）/x86_64 通用；
  web 镜像的 torch 走 PyTorch **CPU 专用 index**（不带 CUDA，镜像小 2GB+）。
  在 x86 机器为香橙派交叉构建：`docker buildx build --platform linux/arm64 ...`
  （QEMU 较慢，建议直接在香橙派上构建）。
- **设备透传**：Arduino/摄像头/声卡以 `devices:` 直透容器；设备名与 `.env`
  不一致时 `compose up` 会直接报错（比运行时才失败好排查）。无界面 Linux
  上 camera 固定 `--mode web --cam 0`。
- **无麦克风的纯语音客户端**：给 voice 设环境变量 `SMART_HOME_DISABLE_MIC=1`
  可跳过音频采集，`/say`、`/trigger`、`/events` 与经由 web 网关的硬件工具仍正常
  （适合只做人脸开门联动、不做语音对话的部署）。
- **依赖固定**：镜像内 `mcp` 固定 1.x（mcp 2.x 移除了 `mcp.server.fastmcp`，
  全新 pip 解析会装到 2.x 导致 mcp_home_server 崩溃——容器实测已踩过并固定）。
- Windows/macOS 桌面开发仍建议用 ⑥ `start_all.py`（Docker Desktop 无法透传
  /dev 串口与 /dev/snd 这类物理外设），Docker 形态面向**设备端部署**。
  若只想在桌面 Docker 里体验 Web/LLM（不接板子/麦克风/摄像头），可用内置覆盖：
  `docker compose -f docker-compose.yml -f docker-compose.desktop.yml up -d`
  （web 降级 `--no-serial` 只当看板，voice 无麦克风，camera 默认跳过）。
- 容器内进程以 tini 托管，`docker compose down` 不会留下 mcp_home_server
  孤儿子进程。

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
