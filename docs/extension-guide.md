# 扩展开发指南（二次开发接口）

面向「不改核心架构，只在外围加东西」的三类需求：接自己的系统（NAS / HA / MQTT /
自建服务）、加一个自己的传感器或执行器、加一条自己的联动。

先按用途定位其它文档：接口清单看 [api.md](api.md)，配置项看
[configuration.md](configuration.md)，串口帧格式看 [serial-protocol.md](serial-protocol.md)，
分层约束看 [development-guide.md](development-guide.md)。

> **最高级约束（不可绕过）**：A 板只报告不判断，B 板只执行不判断，
> 所有业务联动留在 Web/自动化引擎这一层。见
> [development-guide.md 第 0 节](development-guide.md)。

---

## 1. 系统对外暴露的面

| 方向 | 入口 | 默认地址 | 鉴权 | 适合做什么 |
|------|------|---------|------|-----------|
| 入 | Web REST | `http://<host>:5000` | ❌ 无 | 读写状态、控制设备、读写规则与全局状态 |
| 入 | 硬件工具网关 | `http://<host>:5000/api/hardware/{tools,tool}` | ❌ 无 | 取 13 个工具清单、静默执行硬件（与面板同权同账；语音助手走的就是它） |
| 入 | 语音助手 HTTP | `http://<host>:8101` | ❌ 无 | 免唤醒下指令（`/say`）、看对话实况（`/events` SSE） |
| 入 | MCP（stdio） | web 的子进程 | — | 13 个硬件工具的底层；外部调用请走上面的工具网关，不要另起一份 |
| 入 | 摄像头 MJPEG | `http://<host>:8080/video_feed` | ❌ 无 | 取实时画面（热插拔：没画面时发占位帧，`/health` 说明原因） |
| 出 | 规则「HTTP 请求」积木 | 你的服务 | — | 把事件/状态推给外部系统（唯一出站通道） |
| 出 | Home Assistant 代理 | 你配置的 HA URL | HA token | 只在硬件管理页那条可选链路上 |

系统基本**不会**主动连你（没有 webhook 回调、没有 MQTT 发布；唯一的事件流是语音的
对话实况 SSE：voice `/events`，web 同源代理为 `/api/voice/events`，面向自己的前端直播，
不算对外集成点）。要让外部系统知道家里发生了什么，用第 3 节的出站积木，
或者在 Web 进程内挂一个订阅者（第 2 节）。

---

## 2. 官方预留的接缝（按改动成本从低到高）

### 2.1 全局状态：规则的「脚本变量」

自由命名的运行期变量，id 形如 `g:全屋模式`，类型 `bool/number/enum/text`，
存 `PC_Test/data/global_state.json`，重启后保留。

- 读：条件/触发里有专门的「📌 状态」积木（是/否、数值比较、选项等于），通用「数值 / 布尔 / 状态」积木的源下拉里同样能选到 `g:xxx`。
- 写：动作积木「设置全局状态」（`set` / `toggle` / `add`），或
  `PUT /api/automation/global_state/<id>`（id 要 URL 编码）。
- 建/删：自动化页每个变量是一条与规则并列的「📌 状态」条目——工具栏「📌 ＋ 新建状态」
  打开的是一块顶层「状态定义」积木（名字 + 类型 + 当前值），或 `GET|POST /api/automation/global_state`。

它是最省事的状态承载点：模式、在场、安全线、计数、去重标记都放这里，
不要往引擎里塞新状态机。种子变量与内置规则的既有用法（全屋模式、有人在家、
风扇安全线、手动优先 30 秒让位）见 `PC_Test/web/automation/default_rules.py`
文件头的注释。

引用了不存在变量的规则：**页面保存会被拒**（严格模式），引擎读盘只校验格式
（宽松模式，删变量不会清空整个规则集，只会让那条规则永不成立）。

### 2.2 硬件桥数据总线：`snapshot` / `event` / `ack`

`PC_Test/web/hardware.py` 的 `McpHardwareBridge` 三个通道，每通道
**一个主订阅者 + 任意多个观察者**：

```python
from web.extensions import bridge          # create_app() 之后可用

bridge.add_listener("event", lambda ev: print(ev["event"]))   # 并挂，不顶掉自动化引擎
bridge.add_listener("snapshot", on_frame)                      # A 板每一帧原始数据
bridge.add_listener("ack", lambda tool, args: ...)             # 执行器成功 ACK
ok = bridge.remove_listener("event", my_fn)                    # 撤订阅
```

| 通道 | 回调签名 | 触发时机 |
|------|---------|---------|
| `snapshot` | `fn(data: dict)` | 轮询拿到 A 板新帧（约 2 秒一次） |
| `event` | `fn(event: dict)` | 硬件事件去重后（键盘/RFID/红外/触摸/PIR…） |
| `ack` | `fn(tool: str, args: dict)` | `door/window/light/fan/buzzer/ir/ac` 收到成功 ACK |

契约（`pi-staging/test_extension_seams.py` 钉住）：

- 老写法 `bridge.event_listener = fn` 仍然有效，语义是**设置主订阅者**
  （自动化引擎占的就是这个位置）；`add_listener(..., primary=True)` 可换主。
- 观察者异常只写 debug，**绝不**影响主订阅者、其它观察者与轮询线程。
- 钩子在硬件桥的轮询线程里同步执行：只许记账/投递，慢活（HTTP、模型）
  请自己起线程或排队，别把 2 秒一轮的串口节拍拖垮。
- `ack` 只在成功时发；`get_sensor_status` 这类读工具不算 ACK。

想加新订阅者的正确位置：`PC_Test/web/extensions.py::init_bridge()`
（现在写仪表盘心跳 `_mark_output_ack` 就挂在这里）。

### 2.3 HTTP 出站（webhook）动作

规则里用「动作 → HTTP 请求」积木（`device: "http"`）把结果推给外部系统。
字段、护栏与放开方式写在 [api.md 的 HTTP 出站动作](api.md)，配置项在
`web_config.yaml` 的 `automation:` 段：

```yaml
automation:
  http_enabled: true
  http_allow_public: false
  http_allowed_hosts: ["hooks.example.com"]
  http_timeout: 2.0
```

实现集中在 `PC_Test/web/automation/webhook.py`（策略 + 发请求）与
`engine.py::_perform` 的 `device == "http"` 分支，两条护栏是设计底线：
**默认只出内网**、**不携带凭据也不跟跳转**。要换更宽的出站（比如带签名头、
发 MQTT），就在 `webhook.py` 里加，不要往 `engine.py` 里塞第二个 if。

### 2.4 能力清单 `capabilities.py`：积木下拉的单一事实源

`CONDITION_SOURCES`（可读的量）、`EVENT_TRIGGERS`（可订阅的事件）、
`ACTION_DEVICES`（可执行的动作）、`COMPARATORS` 四张表同时喂给
前端 Blockly 工具箱和后端校验（`GET /api/automation/capabilities`）。
在这里加一条 = 页面能选 + 保存能过校验；只在页面加而这里没有 = 保存 400。

原则（文件头写得明说）：**只列真实存在的能力**。固件编译期裁掉的东西
（超声波、土壤、数码管、`face_denied`）故意不列，免得出现「能选但永远不成立」的假能力。

### 2.5 MCP 工具面

`PC_Test/mcp_home_server.py` 里每个 `@mcp.tool()` 就是一个工具（现 13 个），
它是 **web 拉起的 stdio 子进程**：web 侧经 `hardware.py` 的 `call_tool(name, args)`
线程安全调用，外部（含语音助手）经 web 的 `POST /api/hardware/tool` 调同一个名字、
`GET /api/hardware/tools` 拿清单。加一个纯软件工具（不碰新硬件）只需装饰器 + 实现；
但它要能进自动化动作，还得走第 4 节「加一个执行器」那条链。

---

## 3. 常见任务落点清单

### 3.1 加一个传感器（只读，最便宜的路径）

四处，**不需要**动引擎、schema 或前端积木：

| 步骤 | 文件 | 做什么 |
|------|------|--------|
| 1 | `module-a-sensor/src/sensors/`、`Config.h` | 驱动 + 引脚，一个类一个 `.h/.cpp` |
| 2 | `module-a-sensor/src/Protocol.cpp` | `sendReport()` 里带上 `{"你的字段": 值}`（`data` 帧） |
| 3 | `PC_Test/web/database.py` | `SENSORS` 元组 + `ingest_sensor()` 里的范围校验 + `init_database()` 的 `extra` 列声明（老库自动 `ALTER TABLE ADD COLUMN`） |
| 4 | `PC_Test/web/automation/capabilities.py` | `CONDITION_SOURCES` 加一条 `{"label","kind","unit"}` |

做完，触发/条件积木的下拉里就有它，页面 `/api/status` 也会带这个字段。
数值一律走 `database.number()` 的范围校验：越界或类型错会丢掉整帧，
所以阈值要按真实硬件给。

### 3.2 加一个事件（触摸/键盘/RFID 这类一次性触发）

| 步骤 | 文件 | 做什么 |
|------|------|--------|
| 1 | `module-a-sensor/src/...` | 检测到就 `Protocol::sendEvent({"event": "你的名字", ...})` |
| 2 | `PC_Test/mcp_home_server.py` | `get_sensor_status` 的 `recent_events` 能带出来（有界 50 条） |
| 3 | `PC_Test/web/automation/capabilities.py` | `EVENT_TRIGGERS` 加条目（要不要 `key/uid/command/device` 过滤参数） |
| 4 | `PC_Test/web/automation/schema.py` | 若有**新的过滤字段**，`validate_trigger` 的 event 分支放行它（现允许 `key`/`command`/`device`/`uid`） |
| 5 | `PC_Test/web/automation/engine.py` | 新过滤字段要在 `_evaluate_event_rule` 里参与匹配 |
| 6 | `PC_Test/web/static/js/automation.js` | 工具箱里加一块 `trig_*` 积木 + 序列化/回填分支 |
| 7 | `PC_Test/web/automation/default_rules.py` | 需要配套内置规则时再加 |

事件必须带稳定身份（`ts`/`timestamp`）：硬件桥按身份去重，且**首轮只登记不触发**
（防止桥重启时把 50 条历史事件重放一遍）。这个约定别绕。

### 3.3 加一个执行器（最贵，≥7 处）

B 板命令是扁平 JSON、未知键直接丢，分发是 `CommandDispatcher::_route` 的
if/elif 链，所以「多一个设备」是全链路改动：

1. `module-b-output/src/Config.h` 引脚 + `drivers/` 新驱动（只做硬件，不含业务判断）
2. `module-b-output/src/core/CommandParser.cpp` 命令白名单/键
3. `module-b-output/src/core/CommandDispatcher.cpp` `_route` 分支 + ACK 文本
4. `module-b-output/src/Protocol.cpp` 需要回读时扩 `state` 帧
5. `PC_Test/mcp_home_server.py` 新 `@mcp.tool()`
6. `PC_Test/web/hardware.py` `control_xxx()` 助手 + `ACK_TRACKED_TOOLS` 加名字
   （否则成功 ACK 不刷新 `output_last_seen`，面板会显示离线）
7. `PC_Test/web/automation/capabilities.py` `ACTION_DEVICES` +
   `schema.py::validate_action` 新分支 + `engine.py::_perform` 新分支
8. `PC_Test/web/database.py` `OUTPUTS` 列（指令状态）+ 可选 `rb_*` 回读列
9. `PC_Test/web/api/devices.py` 若要面板按钮：路由 + `_DeviceGate.DEVICES`
10. `PC_Test/web/static/js/automation.js` `act_*` 积木 + 序列化/回填，
    `templates/*.html` 页面控件

这里**没有**注册表可填：`_perform`/`validate_action` 就是 if/elif。这一轮刻意
没有重写它（改动面太大、回归风险高）。如果确实要做第 4 个以上的新执行器，
再考虑把它抽成 `ACTION_REGISTRY: name → (校验函数, 执行函数)`，并先补
`pi-staging/test_automation_engine.py` 的用例覆盖现有每一种设备。

### 3.4 加一条 REST 路由 / 一个页面

- 路由：`PC_Test/web/api/<模块>.py` 里加 `@bp.route`，新模块要在
  `web/app.py` 的 `register_blueprint` 元组里登记；返回 `jsonify`，
  错误统一 `{"error", "error_en", "detail"}`。
- 页面：`api/pages.py` 一个 `render_template` 路由 + `templates/*.html`，
  静态资源带 `?v=YYYYMMDDx` 版本号（改 JS 必须抬，否则浏览器吃旧缓存 ——
  `pi-staging/test_frontend_blocks.py` 会检查）。
- 配置项：`web/config.py::DEFAULTS` 加默认值，`PC_Test/web_config.yaml`
  加注释说明；`_deep_merge` 让 yaml 只覆盖写了的键。

### 3.5 从外部驱动硬件（不想改代码时）

两条现成路子：

```bash
# 1) 直接叫 web 面板的设备接口（会走收口器 + 写库 + 广播 manual_control）
curl -X POST http://<host>:5000/api/fan -H 'Content-Type: application/json' \
     -d '{"speed": 60, "_cid": "mygateway", "_seq": 1}'

# 2) 经 web 硬件工具网关直调 MCP（静默、不经 LLM；web 执行完顺手做面板等效记账：
#    写库 + 历史 + 广播 manual_control，无需再补报）
curl -X POST http://<host>:5000/api/hardware/tool -H 'Content-Type: application/json' \
     -d '{"name": "door", "arguments": {"action": "open"}, "source": "voice"}'
```

`_cid` + `_seq` 是给弱网连点用的：同实例迟到的旧 seq 被丢弃、排队中的旧目标被
新目标覆盖。外部程序每次自增 `_seq` 即可，省略也能用（退化为无乱序保护）。

> 工具网关走的是「执行 + 记账」一条路，但**不经过**收口器（`_cid`/`_seq` 那套），
> 语义与 `manual_report` 一样是「记这一次动作」；需要乱序保护请用第 1) 条面板接口。
> `POST /api/devices/manual_report` 现在只剩**外部补偿**用途：硬件是在本系统之外
> 被拨动的（手工操作、另一台网关）才用它补记账，语音助手已不再调用。

---

## 4. 数据面速查

文件（都在 `PC_Test/data/`，除规则外均可删可重建）：

| 文件 | 内容 |
|------|------|
| `automation_rules.json` | 规则集 + `presets_version` + `presets_seen`（原子整表重写） |
| `global_state.json` | 全局状态变量（`version: 2`） |
| `automation_rules.pre-global-state.json` | 积木化迁移前的一次性备份 |
| `oled_carousel.json` | OLED 轮播页面与间隔 |
| `ha_config.json` | HA 地址/token/实体映射（明文！）；**只有在硬件管理页保存过 HA 配置才存在**，默认没有这个文件 |
| `smart_home.db` | SQLite（WAL），`PRAGMA user_version = 3` |

SQLite 主要表：`system_status`（单行，`id=1`；基础列 + 迁移期 `ALTER` 出来的
`smoke/rain/touch/motion/ac_*/rb_*` 扩展列）、`temperature_history`、
`door_window_history`、`light_history`、`sensor_history`、`hardware_events`、
`automation_logs`、`access_logs`、`authorized_persons`、`face_events`。

「指令状态」与「硬件回读」是两套列：`door_status` 等是**已收到 ACK 的指令值**
（持久保留，B 板不主动上报 state），`rb_*` 是 P1 回读到的真实电平。两者不一致
就是静默失效，`/api/status` 的 `device_mismatch` 与 `self_test` 用来定位这类问题。

---

## 5. 测试与部署约定

改完至少跑这几套（`py -3.13`，从仓库根跑；`pi-staging/` 是 git-ignored 的本地套件）：

```bash
py -3.13 pi-staging/test_global_state.py        # 全局状态语义
py -3.13 pi-staging/test_automation_engine.py   # 规则语义 / 去重 / 能力清单
py -3.13 pi-staging/test_automation_api.py      # REST 冒烟
py -3.13 pi-staging/test_frontend_blocks.py     # 前端静态契约（积木/版本号）
py -3.13 pi-staging/test_extension_seams.py     # 数据总线 + HTTP 出站
py -3.13 pi-staging/test_device_gate.py         # 命令收口器
py -3.13 pi-staging/test_llm_provider.py        # 云端 LLM 供应商、Key 来源与读超时
py -3.13 pi-staging/test_serial_ports_env.py    # 串口定位：SMART_HOME_PORT_A/B 覆盖 yaml
py -3.13 pi-staging/test_reset_reconcile.py     # 复位对账
py -3.13 pi-staging/test_camera_hotplug.py      # 摄像头枚举 / 重开 / 占位帧 / health
```

部署到香橙派（形态 B）：

```bash
tar czf /tmp/web.tgz -C PC_Test web web_config.yaml
scp /tmp/web.tgz HwHiAiUser@<host>:~/smart-home/
ssh HwHiAiUser@<host> 'cd ~/smart-home && tar xzf web.tgz && docker compose build web && docker compose up -d web'
```

`~/smart-home` 是**非 git 副本**：覆盖前先跟本地 HEAD 比一遍，别把线上手工改动冲掉。
**只重建 `web` 容器**——A/B 串口就在 web 拉起的 MCP 子进程里，重启 web 等于重启整条
串口链路（B 板会被 DTR 复位一次，web 会自己做复位对账），但语音侧不受影响：它只是
web 的 HTTP 客户端，会自动重试取工具清单。**不要重建 `voice` 容器来「恢复硬件」**，
它已经不占串口；改了 `voice_assistant.py` / `voice_config.yaml` 才单独
`docker compose build voice && docker compose up -d voice`。改 `camera_stream.py` /
`docker-compose.yml` 的 camera 段时同理只动 camera（`docker compose build camera &&
docker compose up -d camera`）。

> `web_config.yaml` 是以 `:ro` 挂进容器的，改配置要落到**宿主机那份**
> （`~/smart-home/web_config.yaml`）并在 web 容器里生效；改完 `docker compose up -d web` 重启即可。

---

## 6. 安全边界（二次开发时必须知道的）

- Web REST 无鉴权：`GET /api/automation/rules` 会把全部规则（含你写的 webhook URL）
  给任何能连到 :5000 的客户端。所以**出站动作里不放凭据**，需要签名请放在
  你的接收端按 IP/内网段校验。
- 只监听内网：不要把 :5000 / :8101 / :8080 暴露到公网；要对外就自己加反代 + 鉴权。
- 出站默认不出内网：公网目标、`169.254.*`（云元数据）需要显式登记或开关，
  且不跟随 3xx ——这是为了堵住「内网 URL 用 302 把请求转到公网」。
- 不要在 web 进程里绕过桥直接开串口：A/B 口由 `McpHardwareBridge` 的 MCP 子进程独占，
  抢口会让整条硬件链路（含语音）失效。语音助手已完全不碰串口，硬件请一律经
  `POST /api/hardware/tool`。
- 不要在钩子/动作里做阻塞长活（见 2.2）。
- 不要整表 `validate_rules` 失败就清空规则：引擎读盘是**逐条**校验、
  坏的只跳过并记进 `migration.invalid` 提示，改这块时保持该行为。

---

## 7. 还没做、但留了余地的事

这些是刻意留下的口子，动手前先想清楚代价：

| 想做 | 现状 | 代价 |
|------|------|------|
| 执行器注册表（替掉 `_perform` 的 if/elif） | 无 | 大：需先给现有设备补齐用例 |
| 对外 API 鉴权开关 | 完全没有 | 中：会影响所有前端与语音联动，需一并改 |
| CORS / 反向代理信任 | 无 | 小，但要和鉴权一起设计 |
| 事件推送给外部（SSE/WebSocket） | 无对外端点（voice 的 `/events` SSE 只服务自己的对话实况，经 web `/api/voice/events` 同源代理） | 中：需要新端点 + 客户端重连语义 |
| 规则级权限（谁能改规则） | 无 | 依赖鉴权 |
| 多进程共享全局状态 | 单进程假设（与规则文件同目录） | 大：现在整个自动化层按单进程写 |
