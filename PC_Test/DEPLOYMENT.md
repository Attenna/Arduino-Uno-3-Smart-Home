# PC_Test — PC 端工具集 部署与二次开发指南

> 面向：把 PC 端工具（串口调试控制台、积木自动化引擎、摄像头流）在 **Linux** 上运行、
> 接线调试、二次开发。
> 使用总览见 [README.md](README.md)；积木自动化扩展见 [web/automation/](web/automation/)。

**功能一句话**：PC 直接连 USB 串口调试 Arduino 双板；自动化统一走 Web 积木引擎（`/automation` 页面，web 自己就是硬件网关，串口在它拉起的 MCP 子进程里，不依赖 MQTT/HA）；也能起 USB 摄像头 MJPEG 流。

---

## 1. Linux 部署

### 1.1 安装 Python 与依赖

```bash
cd PC_Test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # pyserial

# 摄像头工具需要额外依赖（可选）
pip install opencv-python flask
```

### 1.2 串口权限

```bash
sudo usermod -a -G dialout $USER && newgrp dialout
ls /dev/ttyUSB* /dev/ttyACM*          # 确认设备
```

### 1.3 运行各工具

```bash
# ① 串口调试控制台（B 板）
python test_serial.py --port-b /dev/ttyUSB1

# ② 摄像头快速自检 / 流式传输
python camera_test.py
python camera_stream.py --mode web --host 0.0.0.0 --port 8080
```

> 与 Windows 的差异仅在设备名（`/dev/ttyUSB*` 而非 `COMx`）与 Python 命令（`python3`/venv 而非 `py -3.13`）。
>
> **自动化统一入口**：联动规则走 Web 积木引擎——`run_web.py` 自己就是硬件网关（拉起 MCP 子进程独占 A/B 串口，积木动作经它直发 Module B）后访问 `http://<IP>:5000/automation`。
> 历史 `.auto` 文本 DSL、`run_automation.py`、`link_server.py` 已移除。

---

## 2. 设备安装与连接

| 工具 | 需连接设备 | 连接方式 |
|------|-----------|---------|
| `test_serial.py` | Module A 或 B | USB 数据线连串口 |
| `camera_test.py` / `camera_stream.py` | USB 摄像头 | USB2.0 Web Cam 即插即用 |

接线细节（传感器/执行器到板）见对应板目录 [../module-a-sensor/DEPLOYMENT.md](../module-a-sensor/DEPLOYMENT.md)、[../module-b-output/DEPLOYMENT.md](../module-b-output/DEPLOYMENT.md)。

> 自动化规则无需另起进程：由 web 容器内的积木引擎经它自己拉起的 MCP 子进程直接下发到 Module B。

---

## 3. 调试方法

### 3.1 常见调试流程

```bash
# 1. 列出串口与摄像头
python -c "import serial.tools.list_ports as p; [print(x.device, x.description) for x in p.comports()]"
python camera_test.py

# 2. 手动测试 B 板（interactive 菜单 b1/b9/b12...）
python test_serial.py --port-b /dev/ttyUSB1

# 3. 自动化：在 Web /automation 页用积木编排规则（无需直连串口）
```

### 3.2 已知问题

- **命令错位**：OLED 文本连续下发过快会被 B 板串口打乱。积木引擎里的 OLED 动作按行节流下发（逐行 30ms + 仅发变化行）；仍错位可降低动作数量或延长 `delay` 块。
- **串口掉线**：`mcp_home_server.py` 已内置串口自愈（异常退避 → 重新打开 → 恢复数据）。频繁自愈则检查 USB 线 / Hub 供电等物理层问题。
- **数码管**：`display` 工具为保留接口，B 板 TM1637 已裁剪，调用会返回 error，属预期。

### 3.3 摄像头（热插拔）

摄像头容器与 `camera_stream.py` 都不要求「先插再启动」：设备按 `/dev/video*`
每轮重新枚举，拔插换了序号也能自己找回来。排查顺序：

```bash
ls -l /dev/video*                                  # 宿主机有没有枚举到节点（主设备号 81）
docker ps -a --format '{{.Names}}\t{{.Status}}' | grep camera
curl -s http://127.0.0.1:8080/health               # online / device / frame_age_s / error
curl -s http://127.0.0.1:5000/api/camera/status    # web 代理侧看到的同一份状态
docker compose up -d camera                        # 容器没起（Exited）时拉起
```

- `/health` 里 `online:false` 且 `error` 写着「未发现可用摄像头」：没插、线/口没枚举、
  或者**被别的进程占着**——这台 UVC 摄像头同一时刻只允许一个进程打开，对方释放后会自动接上。
- `capture_alive:false`（`/health` 返回 503）：采集线程异常退出，`docker logs` 看原因。
- 页面黑屏但 `/health` 在线：看 `frame_age_s`，越来越大就是设备停止出帧，服务会改发
  「NO CAMERA」占位帧，因此前端能显示问题所在（不再是一根字节都不发的假 200）。
- compose 里摄像头用 `device_cgroup_rules: ["c 81:* rmw"]` + 挂载 `/dev`，与 voice 的串口
  同理：**不要**改回 `devices:`，那会在容器创建时固化设备号，拔插后容器里的节点永久失效。
  重建只动 camera：`docker compose build camera && docker compose up -d camera`。

---

## 4. 二次开发定义（积木自动化引擎）

自动化规则全部统一到 Web 积木引擎 `PC_Test/web/automation/`：

```text
面板(Blockly) ─▶ 规则JSON(schema.py) ─▶ 引擎(engine.py) ─▶ bridge(MCP 子进程，独占串口) ▶ Module B
     传感器快照(SENSOR:)、事件(EVENT:)、人脸授权 ─▶ 引擎注入(边沿/条件/冷却)
```

- `capabilities.py`   积木下拉的能力清单（传感器/事件/比较符/执行器/全局状态变量），前端与校验共用
- `schema.py`         规则 JSON 模型与校验（触发/条件/那么/否则/冷却）
- `engine.py`         规则引擎：触发沿、持续秒数、条件组合、动作线程、防重入、记录
- `default_rules.py`  内置默认规则积木（高温控风扇、光敏调光、雨水关窗、烟雾报警、人脸开门、离家关全屋、按键/红外切换等），可增删/停用
- `global_state.py`   全局状态仓库：自由命名变量（bool/number/enum/text），积木读写，落盘 `data/global_state.json`；每个变量在自动化页是一张「📌 状态」条目卡片，由顶层「状态定义」积木新建/改名/删除
- `oled_carousel.py`  OLED 轮播（扁平数据源 + 内容去重）

> 「自动/手动/离家」不再是引擎里的状态机：它就是一组全局状态变量
> （`g:全屋模式`、`g:有人在家`、`g:手动优先_灯`、`g:允许自动开风扇` 等），
> 由 `default_rules.py` 的预设积木维护。手动优先 = `manual_mark_*` 置脉冲 +
> `manual_clear_*` 到期复位，设备预设再带一条 `g:手动优先_X == 否` 条件让位。
> 引擎只做同值去重（`note_external` 供面板/语音手动操作同步水位），不做设备仲裁。

### 4.2 常用扩展点

| 需求 | 改哪里 |
|------|--------|
| 新增传感器/状态积木 | `capabilities.py` 的 `CONDITION_SOURCES` 加一项（后端校验自动跟随） |
| 新增执行器积木 | `capabilities.py` 的 `ACTION_DEVICES` + `engine._perform` 加分支 |
| 加入默认规则 | `default_rules.py` 追加一条 `preset` 并 `PRESETS_VERSION += 1` |
| 新增全局状态变量 | 自动化页工具栏「📌 ＋ 新建状态」（一块状态定义积木），或 `POST /api/automation/global_state`；积木下拉自动出现 |
| 组合触发/条件积木 | Blockly 页面直接编排「当→如果→那么/否则」，无需改代码 |

### 4.3 相关文档

- 工具总览：[README.md](README.md)
- 串口协议：[docs/serial-protocol.md](../docs/serial-protocol.md)
- 对外接口与扩展缝（事件总线多订阅者、HTTP 出站积木、加传感器/事件/执行器清单）：
  [docs/extension-guide.md](../docs/extension-guide.md)
- 接口清单：[docs/api.md](../docs/api.md)
