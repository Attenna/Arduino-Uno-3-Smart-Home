# GitHub Issues / PR 归档

- 来源仓库: https://github.com/Attenna/Arduino-Uno-3-Smart-Home
- 拉取方式: GitHub REST API `/repos/{owner}/{repo}/issues?state=all`
- 说明: 本文件为离线归档，供香橙派侧协作者查阅；以 GitHub 线上为准。

- 条目总数: 69
- open ISSUE 数: 12

## 目录

- #69 [closed] PR feat(face): 增加五点人脸对齐与 ArcFace 分数展示
- #68 [closed] PR fix: preserve persistent data during Orange Pi deployment
- #67 [closed] PR feat(automation): 将遥控器 1–4 键绑定灯、风扇、门、窗
- #66 [closed] ISSUE fix: prevent deployments from overwriting persistent runtime data
- #65 [closed] PR fix: surface RFID enrollment failures
- #64 [closed] PR fix: reject ambiguous face recognition matches
- #63 [closed] ISSUE fix: make RFID enrollment state observable and resilient
- #62 [closed] ISSUE fix: reconcile face identities with access list and reduce false matches
- #61 [open] ISSUE fix(homeassistant): configuration.yaml 与固件 V2.2/V2.11 不一致（Distance 已裁剪、Light 路由到 B 板）
- #60 [closed] PR docs: 同步引脚定义与服务器架构文档到最新代码
- #59 [closed] ISSUE docs: 同步引脚定义与服务器架构文档到最新代码
- #58 [open] ISSUE fix: make OLED updates resilient to Module B resets
- #57 [closed] PR fix: keep Module A light commands within Uno serial buffer
- #56 [closed] ISSUE fix: keep Module A light commands within Uno serial RX buffer
- #55 [closed] PR fix: move eight-pixel light control to Module A A0
- #54 [closed] ISSUE fix: move NeoPixel light control to Module A A0
- #53 [closed] PR feat(light): add independent eight-pixel lighting levels
- #52 [closed] ISSUE feat(light): redesign eight-pixel lighting controls
- #51 [closed] PR fix(asrpro): align service paths with deployed runtime
- #50 [closed] ISSUE fix: align ASRPRO systemd paths with flattened Orange Pi runtime
- #49 [closed] PR feat: 移除仪表盘空调控制卡片
- #48 [closed] ISSUE feat: 移除仪表盘空调控制卡片
- #47 [closed] PR fix(voice): 使用 ASRPRO 板载 Type-C CH340 串口
- #46 [closed] ISSUE fix(voice): ASRPRO 板载 Type-C CH340 使用 UART0 桥接
- #45 [closed] PR feat: 历史数据展示每秒光照强度
- #44 [closed] ISSUE feat: 在历史数据中记录并展示每秒光照强度
- #43 [closed] PR feat(voice): ASRPRO V2.0 语音控制与温湿度时间播报
- #42 [closed] ISSUE feat(voice): ASRPRO V2.0 离线语音控制与动态数据播报
- #41 [closed] PR fix: 光敏 400/700 回差与 Module A 每秒上报
- #40 [closed] ISSUE fix: calibrate light thresholds and one-second sensor reports
- #39 [closed] PR fix: restore OLED carousel configuration at startup
- #38 [closed] ISSUE fix: load persisted OLED carousel settings during automation startup
- #37 [closed] PR feat(doorway): show live distance and configure dwell-triggered photos
- #36 [closed] ISSUE feat(doorway): independent configurable distance photo linkage
- #35 [closed] PR fix(module-b): reduce reset risk under display load
- #34 [closed] ISSUE fix: prevent OLED carousel from repeatedly resetting module B
- #33 [open] ISSUE feat(automation): 超声波实时距离与门口持续接近拍照规则
- #32 [closed] PR feat(module-b): 接入 HC-SR04 测距工具（Trig D6 / Echo D5）
- #31 [closed] ISSUE feat(module-b): 接入 HC-SR04 超声波测距（Trig D6 / Echo D5）
- #30 [open] ISSUE fix(web): 暗色自定义灯让「命令未生效」判定长期误报（回读比的是峰值电平，不是命令亮度）
- #29 [open] ISSUE test(history): test_history_ui.js 的 DOM 桩缺 style/setAttribute，干净 main 上就 FAIL
- #28 [closed] PR fix(web): 灯光四种亮法统一成服务端状态并可互转 (#27)
- #27 [closed] ISSUE fix(light): 亮度/色温/颜色/夜灯四种亮法无法互相转换，服务端也不回报当前亮法
- #26 [closed] PR feat(automation): 积木工具箱与规则卡片摊平，去掉折叠层级（#18）
- #25 [open] ISSUE feat(history): 门窗/灯光历史改为设备状态时间轴（重做被丢弃的 84052c0）
- #24 [open] ISSUE perf(face): 识别收尾——imgsz 可配置（当前硬编码 640）与门口端到端复测
- #23 [open] ISSUE feat(web): 房间平面图图形化设备控制（点窗即开窗）
- #22 [open] ISSUE feat(sensor): 光照传感器校准——线性映射表与 lux 语义（自然光读数 A / 遮挡读数 B）
- #21 [open] ISSUE fix(automation): 给缺去抖/冷却的触发源补防抖，消除误触发
- #20 [open] ISSUE feat(automation): 补强 sleep 积木（现有 delay 为阻塞式、上限 300 秒、无法等待事件）
- #19 [open] ISSUE refactor(automation): 收口硬编码开/关门路径，让门禁行为由 Blocks 规则决定
- #18 [closed] ISSUE feat(automation): Blocks 规则编辑去掉折叠层级，改为扁平化列表
- #17 [closed] PR fix(deploy): 上传给派上的脚本规范化成 LF（#16）
- #16 [closed] ISSUE 部署脚本在 Windows 部署机上必然失败：scp 上传的 sync_orangepi.sh 带 CRLF
- #15 [closed] PR perf(web): 嵌入模型换 MobileFaceNet 并拦住跨模型混用（#14）
- #14 [closed] ISSUE perf(web): 换轻量嵌入模型砍掉每脸 ~371ms 的 ArcFace R50 推理（含 embeddings 库模型指纹校验）
- #13 [closed] PR perf(web): 消除人脸识别的三处非推理等待（首帧预热 / PIR 即时触发 / 无效提特征）
- #12 [closed] PR fix(web): show humidity stat labels and hide stats for door/light his…
- #11 [closed] PR feat(automation): 全屋有人联动、触摸开门及可疑行为抓拍
- #10 [closed] ISSUE 人脸识别端到端延迟：首帧 3.8s 冷启动罚 + PIR 后最多空等 2s
- #9 [closed] ISSUE 修复 PR #7 灯光调光溢出、零亮度语义和页面控件冲突
- #8 [closed] ISSUE 全屋自动化：触摸开门、有人温光联动及门口可疑行为记录
- #7 [closed] PR feat(light): 支持夜灯分区点亮与色温/RGB 调光
- #6 [closed] PR Show voice dialog state and missing audio feedback in UI
- #5 [closed] PR fix(web): 温湿度入库防丢 + 前端周期刷新
- #4 [closed] ISSUE 温湿度入库链路丢数据 + 前端显示滞留（图表停在页面打开时刻）
- #3 [closed] ISSUE Fix voice UI state and missing response feedback
- #2 [closed] PR 优化语音轮次监听并增加 MCP 上下文
- #1 [closed] ISSUE 优化语音轮次监听与 MCP 上下文

---

## #69 [CLOSED] PR feat(face): 增加五点人脸对齐与 ArcFace 分数展示

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/69

## 变更内容

- 增加 ArcFace 五点人脸对齐，并记录预处理版本，避免旧向量与新向量混用
- 页面与门禁事件改为展示 ArcFace 相似度分数，同时保留检测置信度
- 合并 main 的相似身份歧义保护，只有最高分与次高分间距达到阈值才放行
- 增加中文人脸识别 changes_log、迁移说明和相关测试
- 同步最新 origin/main（19b0347）并修正灯光串口测试夹具

## 验证

- Python：211 项测试全部通过
- 前端 JavaScript：8 项测试全部通过
- 差异与冲突检查通过
- Docker Web 镜像构建尚未完成：依赖下载过程中 OpenCV 网络超时；PyTorch 已成功下载并通过哈希校验。正式部署前需重试镜像构建

## 部署注意

启用五点对齐后，旧的人脸特征向量不能继续使用。部署时需保留注册照片，并重新运行 scripts/enroll_faces.py 生成 embeddings.pkl。

## #68 [CLOSED] PR fix: preserve persistent data during Orange Pi deployment

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/68

Closes #66.

Deployments previously copied the entire long-lived `PC_Test` checkout with `cp -a`. A Git-ignored stale database in that checkout could overwrite the persistent runtime database while the separately preserved face library remained, producing orphan identities and also losing RFID/person records.

This change creates a consistent runtime-state backup before each overlay and deploys only files tracked by the exact Git commit via `git archive`. Ignored databases, face data, models, credentials, and environment files can no longer enter the deployment payload.

Validation:
- `python -m unittest PC_Test.tests.test_deploy_data_safety -v` (2 passed)
- Real archive extraction over a sentinel `data/smart_home.db` preserved the sentinel unchanged.
- `scripts/backup_state.py` completed successfully against the Orange Pi runtime after face-data cleanup.

## #67 [CLOSED] PR feat(automation): 将遥控器 1–4 键绑定灯、风扇、门、窗

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/67

_(无正文)_

## #66 [CLOSED] ISSUE fix: prevent deployments from overwriting persistent runtime data

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/66

The Orange Pi deployment overlays the whole local `PC_Test` checkout with `cp -a`. Git-ignored files left in that checkout, including a stale `PC_Test/data/smart_home.db`, can overwrite the persistent runtime database and split the access list from the preserved face library.

Copy only files tracked by the deployed commit, exclude persistent state and credentials by construction, and create a database backup before changing the runtime tree. Add a regression test that proves ignored runtime files are never copied.

## #65 [CLOSED] PR fix: surface RFID enrollment failures

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/65

Closes #63.

RFID enrollment could appear to hang or end with a generic timeout because malformed reader events were silently ignored, expired sessions had no reason, and the browser stopped polling before reading the server's final state.

This change rejects enrollment immediately when the hardware bridge is offline, records malformed reader events as actionable failures, returns session age and remaining time, and gives the browser a short grace period to display the server's specific error.

Validation:
- `python -m unittest PC_Test.tests.test_rfid_enrollment_state -v` (4 passed)
- Windows full discovery was stopped when the existing serial polling test did not return; the full suite will run in the isolated ARM/Linux container before merge/deploy.

## #64 [CLOSED] PR fix: reject ambiguous face recognition matches

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/64

Closes #62.

Face recognition previously accepted the highest similarity score as soon as it crossed a 0.50 threshold. Similar enrolled identities could therefore be confused even when the winning score barely led the runner-up.

This change raises the deployed threshold to 0.62 and requires an 0.08 lead over the second-best identity. The recognition result now exposes the runner-up score and margin for diagnostics.

Validation:
- `python -m unittest PC_Test.tests.test_face_ambiguity PC_Test.tests.test_face_latency -v` (21 passed)
- Windows full discovery was stopped when the existing serial polling test did not return; the full suite will run in the isolated ARM/Linux container before merge/deploy.

## #63 [CLOSED] ISSUE fix: make RFID enrollment state observable and resilient

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/63

## Problem
A transient RFID enrollment failure can recover without leaving enough diagnostic state to distinguish session expiry from missing hardware events.

## Scope
- expose enrollment session timing and link readiness
- retain terminal outcomes for the UI
- distinguish timeout, offline link, malformed event, credential conflict, and success
- add tests without serial devices

## Acceptance criteria
- the API reports why enrollment did not complete
- valid events bind exactly once
- duplicate events and conflicts remain safe
- full service tests pass

## #62 [CLOSED] ISSUE fix: reconcile face identities with access list and reduce false matches

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/62

## Problem
The deployed face library contained A/B/C/a/b while the access list contained only A/B. The UI reported orphan identities and the recognizer could return b/B inconsistently. The configured ArcFace similarity threshold was 0.5; current A and B prototypes have cosine similarity about 0.54, so threshold-only matching can select the wrong person. Person A also had valid photos but a missing face_id binding.

## Runtime recovery already performed
- backed up the live database, face config, embeddings, and authorized photos
- restored person A -> face_id A
- quarantined C/a/b photos outside the active authorized directory
- rebuilt embeddings with active A/B photos only

## Code scope
- reject ambiguous recognition when top-two scores are too close
- increase the default ArcFace threshold for new configurations
- limit runtime recognition identities to face IDs owned by enabled access-list persons
- report quarantined/ignored identities without showing stale orphan warnings after reconciliation
- add tests for threshold, margin, and list filtering

## Acceptance criteria
- only active listed identities can be returned for access
- an ambiguous top-two match is rejected
- A/B bindings and photos are consistent after deployment
- no orphan identity warning remains
- full ARM/Linux service tests pass

## #61 [OPEN] ISSUE fix(homeassistant): configuration.yaml 与固件 V2.2/V2.11 不一致（Distance 已裁剪、Light 路由到 B 板）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/61

## 问题
`homeassistant/configuration.yaml`（形态 A：HA + gateway）仍按旧固件假设配置，与当前固件不一致，至少两处：

### 1) Distance 传感器指向已被裁剪的字段
- `homeassistant/configuration.yaml:36-40` 的 `sensor.Distance` 读取 `value_json.data.distance`；但 Module A 自 `V2.2` 起 `ENABLE_ULTRASONIC=0`（`module-a-sensor/src/Config.h:18`），`smarthome/sensor/data` 报文不再含 `distance` → 该实体长期 unknown/空。
- 超声波现只在 Module B（`ULTRASONIC_TRIG_PIN D6` / `ULTRASONIC_ECHO_PIN D5`），且仅通过**形态 B** 的 MCP `get_distance` 暴露，不经 A 的 MQTT 数据主题 → 形态 A 已无距离来源。

### 2) Light 命令发往 B 板，但灯带已迁到 A 板 A0
- `homeassistant/configuration.yaml:69-76` 的 `switch.Light` 把 `{"cmd":"light",...}` 发到 `smarthome/output/command`；该主题由 `gateway/src/output_gateway.py`（`TOPIC_COMMAND`）转发到 **Module B** 串口。
- 但灯带数据线已迁到 **Module A A0**（`module-a-sensor/src/Config.h:24-27`；MCP 侧 `mcp_home_server.handle_light → _send_a`），B 板仅保留同名驱动、不由网关路由 → 形态 A 下 HA 的灯开关不再控制真实灯带。
- 同类引用：`homeassistant/scripts.yaml`（`set_light_rgb`，第 59-72 行）与 `homeassistant/automations.yaml:46` 的 `{"cmd":"light","action":"red"}` 同样发往 B 板命令主题。

## 触发 / 复现
- 形态 A 部署（Mosquitto + HA + gateway）后：`sensor.distance` 无值；`switch.light` 开关不改变实际灯带。
- 静态核对：`grep -n "distance\|light" homeassistant/configuration.yaml gateway/src/output_gateway.py`。

## 计划处理方向（待评审确认）
- `Distance`：移除/停用该实体，或定义形态 A 下的距离上报路径（可能需要网关或固件支持，把 B 板测距并入 MQTT）。
- `Light` 归属：明确形态 A 的灯光路径——或让 `output_gateway` 把 `light` 命令改发 A 板，或在配置/文档中显式声明「形态 A 不支持 A0 灯带」。
- 同步 `scripts.yaml` / `automations.yaml` / `scenes.yaml` 内的 light 命令与 `ha_config/configuration.yaml` 快照。

## 验收条件
- `homeassistant/**` 配置与固件 `V2.2`/`V2.11` 一致：不再引用被裁剪字段；灯光命令能到达灯带所在板，或显式声明不支持。
- HA 配置校验通过（`docker compose config` 或 HA 自带配置检查）。
- 相关文档同步：`docs/architecture.md`（形态 A）、`homeassistant/DEPLOYMENT.md`、`gateway/README.md`。

## 影响面
涉及 HA 配置、形态 A 网关路由与串口协议路径；可能需改 `gateway/src/output_gateway.py` 及主题/固件约定；不涉及数据库结构与形态 B Docker 编排。是否需要实际部署形态 A 待确认。

> 关联：本问题由文档同步 #59 过程中发现，未包含在 #59（#59 仅改 `docs/`、README、DEPLOYMENT 等文档）。

## #60 [CLOSED] PR docs: 同步引脚定义与服务器架构文档到最新代码

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/60

## 问题与触发条件
拉取最新 `main`（b383c69）后发现文档与代码不一致，重点是**引脚定义**与**服务器架构**。复现方式（无需硬件）：
- 对比 `module-a-sensor/src/Config.h`（A `V2.2`，`RGB_PIN A0`）与 `docs/architecture.md`（写 A `V2.1`）；
- 对比 `module-b-output/src/Config.h`（B `V2.11`、`LIGHT_BRIGHTNESS 128`、`WDTO_4S`）与各文档（写 `V2.4`/`V2.10`、`60`、`WDTO_2S`）；
- 对比 `PC_Test/mcp_home_server.py`（`@mcp.tool()` 共 **14** 个；`handle_light` → `_send_a`）与文档（写 13 个工具、灯带在 B 板 D4）。

## 修改后的行为
文档与代码一致，读者不再被过期版本号、错误的引脚归属和工具数误导：
- 灯带归属：`light` 由 **Module A（A0）** 执行；B 板仅保留同名驱动、不参与网关路由。
- 版本：A `V2.2` / B `V2.11`；看门狗 `WDTO_4S`；A 上报周期 1s；B `LIGHT_BRIGHTNESS 128`。
- MCP 工具 **14 个**，并标注每个工具路由到 A 还是 B。
- `temp` 灯光命令标注已停用（A 板无该分支）；`pixels` 归属由 B 更正为 A。

## 主要文件与设计选择
仅改文档，14 个文件：
docs/architecture.md、docs/serial-protocol.md、docs/api.md、docs/configuration.md、docs/extension-guide.md、docs/ultrasonic.md、docs/hardware-debug-notes.md、PC_Test/README.md、README.md、homeassistant/DEPLOYMENT.md、module-a-sensor/README.md、module-a-sensor/DEPLOYMENT.md、module-b-output/README.md、module-b-output/DEPLOYMENT.md

设计选择：以「网关实际路由」（`_send_a`/`encode_a_light_command`）为权威描述灯带归属；`serial-layer-hardening-plan.md` 中的 `WDTO_2S`/`V2.4` 属历史记录，未改动。

## 测试命令与结果
- 文档检查（链接/路径）：遍历本 PR 改动的 14 个 md 的相对链接 → `link-check: OK (0 broken)`。
- 过期值扫描：`13 个工具|V2.4|每 2s|7 类现役` → 仅命中历史文档 `serial-layer-hardening-plan.md`（预期）。
- 未运行单元测试：本次仅文档改动，`PC_Test/tests` 不涉及。

## 配置 / 数据库 / 硬件 / 部署影响
- 无配置、数据库、Docker、固件、协议实现改动；
- 不涉及香橙派部署（无需烧录/同步）。

## 回滚方法
`git revert` 本 PR 的 squash 提交，或 `git checkout main && git revert <squash-sha>`；纯文档回滚，无数据影响。

Closes #59

## #59 [CLOSED] ISSUE docs: 同步引脚定义与服务器架构文档到最新代码

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/59

## 问题
拉取最新 main（b383c69）后，文档与代码在多处不一致，重点是引脚定义与服务器架构：

- 固件版本：Module A 实际 `V2.2`（文档写 `V2.1`）；Module B 实际 `V2.11`（架构/README 写 `V2.4`，协议文档写 `V2.10`）。
- MCP 工具实际 **14 个**（多处写 13 个，且列表缺 `get_distance`）。
- 灯光归属：`light` 命令已路由到 **Module A（A0 灯带）**（`mcp_home_server._send_a` / `encode_a_light_command`），B 板仅保留同名驱动；架构/协议/模块文档仍按「灯带在 B 板 D4」描述。
- 其它：A 板上报周期实际 1000ms（文档写 2s）；B 板 `LIGHT_BRIGHTNESS` 实际 `128`（文档写 60）；B 板看门狗实际 `WDTO_4S`（部分文档写 2s）；Module A DEPLOYMENT 误称「A0/A1 悬空」（A0 已接灯带）。

## 触发/复现
对比下列代码与文档即可复现（无需硬件、无需串口）：
- `module-a-sensor/src/Config.h`、`module-b-output/src/Config.h`
- `PC_Test/mcp_home_server.py`（`@mcp.tool()` 数量、`_send_a` 路由、`encode_a_light_command`）
- `PC_Test/web/hardware.py`（`control_light*` 走 `light` 工具）

## 计划修改（仅文档）
docs/architecture.md、docs/serial-protocol.md、docs/api.md、docs/configuration.md、docs/extension-guide.md、docs/ultrasonic.md、docs/hardware-debug-notes.md、PC_Test/README.md、README.md、homeassistant/DEPLOYMENT.md、module-a-sensor/README.md、module-a-sensor/DEPLOYMENT.md、module-b-output/README.md、module-b-output/DEPLOYMENT.md

## 验收条件
- 全部 Markdown 的固件版本号、MCP 工具数/清单、引脚归属与固件及服务器代码一致；
- 文档内部链接与路径有效；
- 仅文档改动，不触碰固件、Python、Docker、数据库。

## 影响面
串口协议文档有修订（仅描述层，未改协议实现）；不涉及数据库结构、Docker 编排、设备部署，无需部署。

## #58 [OPEN] ISSUE fix: make OLED updates resilient to Module B resets

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/58

## Problem
Enabling the OLED carousel sends several SPI-backed row writes at each page change. On the deployed Module B this correlates with repeated ready frames, command timeouts, serial reopen cycles, and visible resets. Disabling OLED stops its writes, but the display cannot be used.

## Scope
- preserve an explicit user-disabled setting during default-page migration
- replace burst row writes with paced single-row updates
- add startup grace and serial-health reset detection
- automatically suspend OLED writes after a reset and require a stable cooldown before retrying
- persist/report the intended enabled setting without silently re-enabling it
- add regression tests and compile Module B firmware if firmware changes are needed

## Acceptance criteria
- no burst of OLED commands at startup or page changes
- disabling OLED remains disabled across upgrades and restarts
- a detected Module B reset suspends further OLED writes
- normal status display resumes only after a stable cooldown
- ARM/Linux full test suite passes
- deployed B reset count remains stable during an observation window

This may touch the automation engine/carousel and read-only serial health path. Runtime data and credentials remain outside Git.

## #57 [CLOSED] PR fix: keep Module A light commands within Uno serial buffer

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/57

## Problem
After deploying #55, the roughly 90-byte light JSON frame can exceed Arduino Uno's 64-byte serial RX buffer while sensors are being read. Module A stays online but intermittently drops the command, causing 8-pixel requests to time out.

## Result
The gateway now encodes A-board light commands as compact line frames under 64 bytes. Module A parses these frames and returns the existing JSON acknowledgement with the matching request ID. Off, white, RGB, preset colors, brightness, and 2/4/6/8 pixel levels remain supported.

## Validation
- Module A firmware compile: PASS (Flash 71%, SRAM 64%).
- Focused transport tests: 4 PASS.
- Direct production diagnosis confirmed Module A did not reset; oversized JSON commands were dropped while sensor reports continued.

## Deployment
After review and merge, deploy the exact main commit, rebuild Web, back up Module A flash, flash the merged firmware, and verify repeated 2/4/6/8 pixel commands.

Closes #56

## #56 [CLOSED] ISSUE fix: keep Module A light commands within Uno serial RX buffer

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/56

## Problem
After deploying #55, direct serial verification showed that Module A remains healthy but intermittently ignores the approximately 90-byte light JSON frame. Arduino Uno has a 64-byte default serial RX buffer, so frames arriving while sensor reads run can be truncated.

## Plan
Use a compact, line-based light command between the MCP gateway and Module A while retaining request IDs and JSON responses. Keep each command below 64 bytes. Preserve off, white, RGB, brightness, and 2/4/6/8 pixel levels.

## Acceptance criteria
- Maximum emitted A-board light command is below 64 bytes including newline.
- Repeated 2/4/6/8 pixel commands receive matching acknowledgements.
- Module A firmware compiles and focused gateway tests pass.
- Deployment occurs only after review and merge.

## #55 [CLOSED] PR fix: move eight-pixel light control to Module A A0

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/55

## Problem
Module B resets and times out while controlling the NeoPixel strip. The web panel therefore reports hardware control failure even though the eight LEDs and A0 data path are healthy.

## Result
- Module A firmware drives the 8-pixel strip from A0 (digital D14).
- Existing off, brightness, RGB color, preset color, and centered 2/4/6/8 pixel commands are retained.
- The MCP gateway sends only light commands to Module A; door, window, fan, buzzer, OLED, IR, and other outputs remain on Module B.
- D0/D1 remain reserved for the USB serial link.
- The strip starts off and uses a 50% global current cap in addition to relative UI brightness.

## Validation
- `arduino-cli compile --fqbn arduino:avr:uno module-a-sensor`: PASS (Flash 68%, SRAM 64%).
- `python -m compileall -q PC_Test`: PASS.
- Focused light suites: 29 tests PASS (`tests.test_light_pixels`, `tests.test_light_style`) in an isolated container with no serial devices.
- Full discovery was attempted; unrelated optional runtime/data dependencies on the test host prevented a clean full-suite result.
- Physical diagnostic before this change confirmed all 8 LEDs produce uniform white light from Module A A0 at safe brightness.

## Hardware and deployment
Move strip DIN to Module A A0 through a 330–470 ohm resistor. Use an external regulated 5V supply and common ground. Do not connect the strip to D0/D1. Deployment must flash Module A and restart the web service only after review and merge.

## Rollback
Restore the pre-deployment Module A flash backup and deploy the previous merged commit.

Closes #54

## #54 [CLOSED] ISSUE fix: move NeoPixel light control to Module A A0

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/54

## Problem
Module B repeatedly resets or times out while controlling the 8-pixel NeoPixel strip, leaving the web UI with hardware control failures.

## Plan
- Move the NeoPixel data signal from Module B D4 to Module A A0 (digital D14).
- Keep Module A USB serial on D0/D1; those pins remain reserved for RX/TX.
- Add light command handling and state acknowledgement to Module A.
- Route light commands to Module A in the Orange Pi MCP bridge while keeping other actuators on Module B.
- Update protocol and wiring documentation.

## Acceptance criteria
- White/RGB/off and 2/4/6/8 pixel levels work through the existing light API.
- Module A sensor reporting remains valid.
- Module B no longer receives light commands.
- Relevant PlatformIO builds and PC_Test unit tests pass.

## Hardware/deployment impact
Requires moving only the strip data wire to Module A A0. The strip must retain an external regulated 5V supply and common ground. No credentials or runtime data are changed.

## #53 [CLOSED] PR feat(light): add independent eight-pixel lighting levels

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/53

灯光面板原有“全亮/半亮/白光/夜灯”混合了亮度、颜色和灯珠数量。现在移除面板色温入口，保留颜色、亮度，提供微光2颗、柔光4颗、明亮6颗、全灯8颗，切换数量时保留颜色和亮度。增加独立开关、8颗灯珠指示和常用颜色。

Closes #52

## 实现与影响
- 前端模板/样式/语言/交互及对应测试；设备API、状态记账、硬件桥、MCP网关、自动化数量继承。
- B板新增 pixels 原子指令，携带 RGB、亮度和count，居中点亮并清除其余灯珠。旧固件会拒绝新指令，失败不更新数据库。
- 数据库新增可空 light_count 列；保留历史数据、旧颜色/色温协议兼容。无Docker编排变更，A板无需修改。
- B板必须更新固件后才能使用新分档。未部署或操作实体执行器。

## 验证
- 后端灯光测试29项通过：python -m unittest discover -s PC_Test/tests -p 'test_light*.py' -v。
- node --test PC_Test/tests/test_light_ui.js：8项通过。
- python -m unittest discover -s PC_Test/tests -v：180项中174通过、6个现有人脸图片测试错误。独立worktree的测试环境，不连接真实串口；合成图片复现OpenCV 5.0.0中文目录写入路径异常。
- Python compileall、git diff --check通过。浏览器模拟预览验证6颗、65%及颜色保持。
- 本机缺少PlatformIO，B板编译尚未验证。

## 合并前必须完成
- 修复测试环境并完成完整回归；完成B板PlatformIO编译。
- 至少一名未参与实现的审查者完成审查，处理所有反馈，确认自动检查通过。
- 已确认本分支包含最新origin/main（87fbcdeb32b9ce89f29db1e13681e2a4040e9259）。

## 部署与回滚
仅在合并后更新本地main，由单一部署者执行scripts/sync_orangepi.ps1，并同步B板固件。保留香橙派data/models/.env/.auth*.env及凭据。检查三端提交、容器健康、/api/ready和匿名API拒绝。
回滚通过revert PR合并后部署main；新增可空数据库列可保留，旧代码忽略；新固件保留旧指令兼容。

本PR为草稿，以上编译、全套测试及独立审查完成前不得合并或部署。

## #52 [CLOSED] ISSUE feat(light): redesign eight-pixel lighting controls

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/52

现有灯光面板的全亮/半亮/白光/夜灯操作不够直观，颜色、亮度和点亮灯珠数量需要独立控制。灯泡由8颗灯珠组成。

修改范围：dashboard 模板、CSS、main.js、lang.js；web/api/devices.py、web/light_state.py、web/database.py、web/hardware.py、web/automation/engine.py；mcp_home_server.py；B板 Light 驱动及 CommandDispatcher；相关测试和 API/串口文档。当前没有开放PR。

验收条件：
- 面板移除色温，保留RGB颜色和亮度。
- 提供2/4/6/8颗四档，切换档位保留颜色及亮度，显示8颗灯珠的状态。
- 独立开关与常用颜色快捷键。
- pixels 原子指令携带颜色/亮度/数量；旧固件拒绝指令时不得错误记账。
- 灯光、前端及完整回归测试通过，B板PlatformIO编译通过，再经独立审查合并部署。

涉及串口协议扩展和可空 light_count 数据库列；不修改Docker编排。B板需要更新固件，部署保留运行数据和凭据。

本地实现提交4caf9d02466fc5704cedbd3f3f4acbc3c9a36b41。先前网络不可用时离线实现，现已确认最新origin/main仍为87fbcdeb32b9ce89f29db1e13681e2a4040e9259。后端灯光29项、前端8项通过；完整180项中6个人脸图片测试受Windows OpenCV中文路径问题影响。固件编译待补。

## #51 [CLOSED] PR fix(asrpro): align service paths with deployed runtime

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/51

The Orange Pi deployment flattens `PC_Test` into `/home/HwHiAiUser/smart-home`, so the ASRPRO service could not find either its environment file or bridge script. This updates the unit to use the deployed paths and documents the source/deployment distinction.

Closes #50

Validation: `python -m unittest discover -s PC_Test/tests -p test_asrpro_bridge.py -v` (7 passed); `git diff --check`.

## #50 [CLOSED] ISSUE fix: align ASRPRO systemd paths with flattened Orange Pi runtime

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/50

The Orange Pi deployment copies PC_Test contents directly into /home/HwHiAiUser/smart-home, but firmware/asrpro/asrpro-bridge.service references PC_Test/asrpro_bridge.py and PC_Test/.auth.asrpro.env. The bridge cannot start after deployment. Update the unit to use the flattened runtime paths and validate the unit configuration.

## #49 [CLOSED] PR feat: 移除仪表盘空调控制卡片

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/49

仪表盘首页当前单独展示“空调（美的红外）”控制卡片，用户要求删除截图中的该前端模块。

本 PR 删除 dashboard.html 中完整空调卡片，清理 main.js 中只为该卡片服务的状态缓存、温度滑块绑定、状态回显及控制函数，并移除对应无用样式。首页核心区域保留温湿度、风扇、门窗和灯光四张卡片。

Closes #48

范围说明：保留仪表盘远程控制区的空调开关快捷按钮，也保留硬件管理、自动化、语音和后端 /api/ac 能力；本次只删除用户截图中的独立空调控制卡片。开放 PR #47 只修改 ASRPRO 固件文件，与本 PR 无冲突。

验证：
- node --test PC_Test/tests/*.js：18/18 通过。
- 香橙派隔离容器，无网络、无真实串口：python -m unittest discover -s PC_Test/tests -v，172/172 通过。
- python -m compileall -q PC_Test/web：通过。
- git diff --check：通过。

影响：仅前端模板、脚本、样式和对应前端测试；不修改数据库、串口协议、Arduino 固件、Docker 编排或执行器后端。静态脚本版本已更新，部署后浏览器会获取新 main.js。

回滚：通过 revert PR 恢复该提交后重新部署已合并 main。

## #48 [CLOSED] ISSUE feat: 移除仪表盘空调控制卡片

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/48

仪表盘当前展示“空调（美的红外）”控制卡片，但用户要求从前端界面移除该模块。

计划只修改仪表盘展示层：删除 PC_Test/web/templates/dashboard.html 中的空调卡片，并清理 PC_Test/web/static/js/main.js 中只服务于该卡片的状态、滑块绑定、状态回显和控制函数。保留后端 /api/ac、语音、自动化及硬件管理能力，避免扩大功能删除范围；仪表盘远程控制区不属于截图中的独立空调卡片。

验收条件：仪表盘 HTML 不再包含空调卡片及 acTempSlider/acModeButtons 等元素；main.js 不再查询或绑定这些元素；其他设备卡片、灯光控制和远程控制不受影响；前端与 PC_Test 全套测试通过。

不涉及数据库、串口协议、Arduino 固件或 Docker 编排。

## #47 [CLOSED] PR fix(voice): 使用 ASRPRO 板载 Type-C CH340 串口

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/47

用户通过 ASRPRO 开发板板载 Type-C/CH340 与香橙派连接，而现有固件使用外接 PA2/PA3 的 UART1，导致板载 USB 串口无法承载桥接协议。本修复改用天问 SDK 默认 Serial（UART0），并更新连接说明。

Closes #46

验证：ASRPRO Python 桥接 7 项测试全部通过，git diff --check 通过；确认源码不再访问 Serial1，所有收发和初始化统一使用 Serial 115200。天问自带旧 RISC-V 编译器本次在 Windows 上因系统 DLL 重定位错误无法启动，因此仍需在天问 Block 中执行“生成模型”和“2M 编译下载”作为最终固件构建验证。

硬件：Type-C 数据线必须连接香橙派 USB Host 口并在 lsusb 中出现独立 CH340/ttyUSB；当前香橙派尚未枚举该设备，批准前不启用桥接服务。

## #46 [CLOSED] ISSUE fix(voice): ASRPRO 板载 Type-C CH340 使用 UART0 桥接

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/46

现有 ASRPRO 固件将香橙派桥接放在 UART1 PA2/PA3，适用于独立 USB-TTL。用户实际采用开发板板载 Type-C/CH340，因此串口应使用天问 SDK 默认 Serial（UART0）。

计划修改 firmware/asrpro/smart_home.cpp 与 README，保留协议和香橙派桥接器不变。验收：使用本机天问 RISC-V SDK 编译通过；Python 全量回归通过；文档明确 Type-C 必须连接香橙派 USB Host 并枚举为独立 ttyUSB，禁止误用 A/B 板 ttyACM。

硬件影响：需要重新生成/编译下载固件；当前 Type-C-to-Type-C 链路尚未在香橙派 lsusb 中枚举，启用服务前必须先出现独立 CH340 设备。

## #45 [CLOSED] PR feat: 历史数据展示每秒光照强度

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/45

历史页目前只展示温湿度、门窗和灯具状态，环境光敏 ADC 虽已入库但没有查询或可视化入口；生产实测 Web 轮询约 2 秒一次，也没有完整记录 A 板当前每秒上报的数据。

本 PR 在数据类型下拉中新增“光照强度”，与“灯光状态”明确分开。页面展示 ADC 统计卡、趋势图和详细记录；最近 1 小时保留每秒点，较长窗口做有界分桶，7 天后进入小时聚合。Web 硬件桥轮询间隔同步为 1 秒，使每个 A 板周期快照写入 sensor_history.light_raw。中英文文案及静态资源版本已更新。

Closes #44

主要文件：PC_Test/web/database.py、PC_Test/web/api/status.py、PC_Test/web/hardware.py、PC_Test/web/config.py、PC_Test/web_config.yaml、PC_Test/web/templates/history.html、PC_Test/web/static/js/history.js、PC_Test/web/static/js/lang.js，以及对应测试。开放 PR #43 不修改这些文件。

验证：
- 香橙派隔离容器，无网络、无真实串口：python -m unittest discover -s PC_Test/tests -v，165/165 通过。
- Windows 隔离环境：test_sensor_pipeline 10/10 通过。
- node --test PC_Test/tests/*.js：17/17 通过。
- python -m compileall -q PC_Test/web PC_Test/tests：通过。
- git diff --check：通过。
- 部署前生产只读检查：最近光照记录约每 2.04 秒一条，符合本 PR 要修正的轮询节拍问题。

影响：启动时为 sensor_hourly 添加可空 light_raw 列，不重建或删除数据库；sensor_history 继续保留秒级原始记录 7 天，之后只保留小时均值。轮询频率由 2 秒提高到 1 秒，会使传感器历史写入量约翻倍至每天 8.6 万条，现有保留和聚合机制限制长期磁盘增长。不修改 Arduino 固件、串口协议、执行器逻辑或 Docker 编排。

部署：本 PR 尚未合并或部署。审查合并后按 scripts/sync_orangepi.ps1 部署，验证 /api/light-level/history、三服务健康、匿名 API 拒绝，并实测数据库相邻光照记录约 1 秒。

回滚：通过 revert PR 恢复轮询和页面入口；新增的可空数据库列可安全保留，既有 sensor_history 数据不需要删除。

## #44 [CLOSED] ISSUE feat: 在历史数据中记录并展示每秒光照强度

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/44

当前 Module A 已每秒上报光敏 ADC，但历史数据页面只能查看温湿度、门窗状态和灯光状态，无法查看环境光强变化。

计划修改 PC_Test/web/database.py、PC_Test/web/api/status.py、PC_Test/web/templates/history.html、PC_Test/web/static/js/history.js、PC_Test/web/static/js/lang.js 以及对应测试。

验收条件：历史数据下拉增加“光照强度”；每个有效的 Module A 秒级快照都把 light 写入 sensor_history.light_raw；API 按所选时间范围返回光照数据，7 天内保留秒级原始读数，长时间范围使用小时聚合；统计卡、趋势图和详细记录显示 ADC 读数；空值不会污染统计；中英文界面均有文案。

不修改串口协议、Arduino 固件、Docker 编排或现有运行数据；数据库迁移只为 sensor_hourly 增加可空 light_raw 列。

## #43 [CLOSED] PR feat(voice): ASRPRO V2.0 语音控制与温湿度时间播报

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/43

为 ASRPRO V2.0 增加离线语音入口，支持开灯、关灯、开门、开窗、开风扇、关风扇，以及温度、湿度和时间播报。识别口令后通过专用串口桥接调用已有 Web 硬件网关；仅在收到成功确认后回复成功，超时不自动重试物理动作。

Closes #42

### 改动
- 天问 Block AI C++ 源码、语音模型配置注释及数字播报资源。
- Python 串口桥接器：固定指令映射、有效在线传感器值检查、分帧与重连。
- 安装说明、可选服务单元及 7 项模拟测试。
- 不改变已有 A/B 板协议、数据库和 Docker 编排。

### 验证
- 天问 SDK RISC-V 编译器目标文件编译通过；尚待用户生成模型并完成整包烧录和实机联调。
- Python compileall 通过。
- 独立断网、无真实设备的 Linux 环境运行 python -m unittest discover -s PC_Test/tests -v：170 项全部通过。
- Windows 既有人脸测试的 6 项失败在主分支同样复现，Linux 全套通过；未修改无关人脸代码。
- Git diff 格式检查通过。

### 配置与部署
需要专用 3.3V TTL USB 适配器、串口路径及已有网关服务凭据。模型、凭据和运行数据不提交。
用户要求先审核；批准前不合并、不部署。

### 回滚
安装后可停用新增桥接服务，再按仓库的回滚 PR 流程恢复已验证版本，保留运行数据和认证配置。

## #42 [CLOSED] ISSUE feat(voice): ASRPRO V2.0 离线语音控制与动态数据播报

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/42

现有系统缺少 ASRPRO V2.0 离线语音入口。新增天问 Block AI C++ 程序与香橙派专用 UART 桥接，支持开灯、关灯、开门、开窗、开风扇、关风扇、温度、湿度和北京时间播报。

计划文件：firmware/asrpro/smart_home.cpp、README.md、VALIDATION.md、asrpro-bridge.service；PC_Test/asrpro_bridge.py；PC_Test/tests/test_asrpro_bridge.py。不修改共享的 A/B 板固件、Web API、数据库或 Docker 编排。

验收：SDK 目标文件编译成功；模拟网关测试覆盖九项功能、鉴权、无效值、串口分帧和超时不重试；运行完整 PC_Test 测试；真实数据播报仅使用在线有效传感器值。

新增 ASRPRO 专用 ASCII UART 协议，不改变 A/B 现有协议。部署需要专用 USB 转 TTL、独立桥接服务与现有服务令牌。用户明确要求先上传 PR，审核通过后才合并部署。当前不部署、不发送执行器指令。

## #41 [CLOSED] PR fix: 光敏 400/700 回差与 Module A 每秒上报

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/41

将交接包的光敏回差调整应用到最新 main（cb97be4），并把 Module A 上报间隔从 2000ms 改为 1000ms。满足原有有人在家、传感器新鲜、未手动接管等条件时，ADC <400 开灯，>700 关灯，400–700（含端点）保持状态；规则复查仍为 2 秒。

Closes #40

修改范围：仅 PC_Test/web/automation/default_rules.py、PC_Test/web/automation/engine.py、PC_Test/tests/test_home_automation.py、module-a-sensor/src/Config.h。v6→v7 只更新两条光敏预设，其他已有预设配置保留。未上传压缩包、凭据、模型或运行数据。

验证：
- 隔离 venv，无真实串口设备：python -m unittest discover -s PC_Test/tests -p test_home_automation.py -v：23/23 通过。
- python -m unittest discover -s PC_Test/tests -v：161 项，155 通过、6 个错误，均为 test_face_model_guard 的 No valid authorized face images found。未修改 main 上运行该测试文件同样 25 项中 6 个错误；测试使用含中文名称的图片目录，疑似 Windows OpenCV 路径兼容问题。未在本 PR 扩大修改范围。按仓库规范，全套测试问题解决前禁止合并。
- python -m compileall -q PC_Test/web/automation PC_Test/tests/test_home_automation.py：通过。
- python -m platformio run -d module-a-sensor：成功，RAM 1023/2048，Flash 18804/32256。
- git diff --check：通过。

协调：开放 PR #39 同样修改 engine.py，但仅涉及 OLED 配置加载；本 PR 仅改预设迁移，逐段检查无重叠。建议 #39 先合并，再同步本分支并重跑测试。需要未参与实现的审查者完成审查。

部署影响：无数据库结构、协议格式或 Docker 配置变化。服务首次加载迁移预设；1 秒上报需另行烧录 Module A。尚未合并、部署或烧录，等待用户批准及测试阻塞解除。之后按仓库脚本部署已合并 main，保留 Orange Pi 的 data/、models/、.env、认证文件；不改 Module B。

回滚：通过新的 revert PR 撤回该提交并部署合并后的 main；固件恢复此前已验证版本。运行规则已迁移到 v7 时，代码回滚不会自动恢复旧阈值，须结合部署前规则备份处理。

## #40 [CLOSED] ISSUE fix: calibrate light thresholds and one-second sensor reports

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/40

交接包的光敏规则使用旧阈值 200/300，Module A 每 2 秒上报。计划仅修改 PC_Test/web/automation/default_rules.py、PC_Test/web/automation/engine.py、PC_Test/tests/test_home_automation.py、module-a-sensor/src/Config.h。验收：ADC <400 开灯、>700 关灯、含边界的中间区间保持；v6 到 v7 保留其他预设配置；上报周期 1000ms；全套隔离单测及 Uno 编译通过。无协议格式、数据库结构、Docker 改动；服务部署和 Module A 烧录待用户批准并合并后处理。

## #39 [CLOSED] PR fix: restore OLED carousel configuration at startup

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/39

Fixes #38.

After the safe OLED interval default changed from 5 seconds to 15 seconds, startup still treated `interval != 5` as proof that configuration had already loaded. An enabled persisted carousel was therefore skipped and the display stayed black after restart.

This change loads OLED configuration explicitly before the carousel thread starts, uses a dedicated one-time load flag for API fallback, and preserves interval clamping and page migration. It also adds restart and malformed-file regression coverage.

Validation:
- OLED startup/reset-risk tests: 4 passed
- ARM/Linux isolated full suite: 162 passed
- Windows full suite: 156 passed; 6 existing OpenCV failures caused by Chinese temporary paths

## #38 [CLOSED] ISSUE fix: load persisted OLED carousel settings during automation startup

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/38

## Problem
After PR #35 changed the safe OLED interval default from 5s to 15s, `oled_config()` still uses a comparison with 5s as its uninitialized sentinel. On service startup the engine therefore skips the persisted `enabled: true` configuration, sends no OLED commands, and leaves the display black.

## Scope
- load and normalize persisted OLED settings explicitly during engine startup
- remove the numeric-default sentinel from the lazy loader
- add a restart regression test proving enabled state, safe interval, pages, and carousel runtime state are restored

## Acceptance criteria
- an enabled persisted carousel resumes after service restart
- unsafe historical intervals are clamped to 15s
- malformed/missing files retain safe defaults
- relevant tests and ARM/Linux full suite pass

No database, serial protocol, firmware, or actuator behavior change.

## #37 [CLOSED] PR feat(doorway): show live distance and configure dwell-triggered photos

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/37

Closes #36.

Adds live B-board ultrasonic distance to the face/access screen and a configurable Blockly distance trigger plus camera snapshot action. The new doorway template starts at distance < 50 cm held for 2 seconds; users edit and save it explicitly. Existing rules and issue #33 worktree remain untouched.

The hardware bridge polls through the existing serialized MCP connection every 500 ms after completion, independently of A-board polling. Invalid samples and gaps over 3 seconds reset the hold. One capture per continuous visit; edits reset the timer. Camera service remains running for preview; the action fetches and stores a snapshot, without opening doors or requiring face recognition.

Photos and metadata use existing persistent data/security storage and authenticated security pages. Failures are recorded. Changes cover hardware polling, automation engine/schema/capabilities, camera cache API, access/automation/security UI, and ultrasonic documentation. No firmware, protocol, database migration or Docker dependency change.

Validation after rebasing onto origin/main 9fd0e87:
- Isolated venv, no real serial/camera devices: python -m unittest discover -s PC_Test/tests -v: 160 tests, 154 passed, 6 pre-existing errors in test_face_model_guard.
- Baseline origin/main reproduces the same 6 errors: OpenCV on this Windows host miswrites Chinese directory paths, so generated face fixtures are not discovered. No production face code changed.
- All 13 new backend tests pass (hold/boundary/reentry/invalid/stale/edit/persistence/polling/photo success and failure).
- node --test PC_Test/tests/test_doorway_ui.js PC_Test/tests/test_blocks_flat_ui.js: 8 passed.
- Python compileall, JavaScript syntax and git diff --check pass.

Draft: independent review and a clean supported-environment full test run are still required before merging under docs/git-workflow.md. No deployment performed. After approved squash merge, update main and deploy that exact commit via scripts/sync_orangepi.ps1. Rollback through a reviewed revert PR; retain data/, models/, .env and credentials. Disable the custom rule to stop new captures.

## #36 [CLOSED] ISSUE feat(doorway): independent configurable distance photo linkage

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/36

Implement a separate worktree as requested by the user; leave existing issue #33 worktree untouched. Scope: PC_Test/web hardware distance polling, automation engine/schema/capabilities, camera API, face UI and security photo storage. Acceptance: live valid distance, configurable threshold and continuous hold, one capture per visit, invalid/stale reset, persistent photo records, isolated tests. No serial protocol, firmware, schema or Docker changes. Deployment only after independent review and merge.

## #35 [CLOSED] PR fix(module-b): reduce reset risk under display load

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/35

Fixes #34.

B 板在 OLED 5 秒轮播及高亮 RGB 负载下会反复输出 ready 帧；现场 25 分钟内达到 87 次复位，且没有香橙派欠压或 USB 断连记录。暂停 OLED 后复位计数在观察窗口内停止增长。

修改后的行为：OLED 最短 15 秒切页且不重发未变化行；B 板看门狗由 2 秒调整为 4 秒并在一批命令后重新喂狗；8 颗 WS2812 的全局亮度限制为 128，使满白估算电流从约 480mA 降至约 240mA。固件版本升级为 V2.11。

验证：
- `python -m unittest discover -s PC_Test/tests -p test_b_reset_risk.py -v`：2 项通过
- `python -m unittest discover -s PC_Test/tests -p test_home_automation.py -v`：22 项通过
- `node --test PC_Test/tests/test_blocks_flat_ui.js`：5 项通过
- ARM/Linux 隔离容器全量测试：147 项通过
- Windows 全量测试：148 项中 142 项通过；6 项为已有 OpenCV 无法读取中文临时路径问题，ARM/Linux 同批全量通过
- `python -m compileall -q PC_Test/web PC_Test/tests`：通过
- `platformio run -d module-b-output`：通过，RAM 1614/2048，Flash 25312/32256

影响：OLED 快速轮播配置会被钳制为 15 秒；灯带最高物理亮度约减半，UI 的相对亮度范围保持 0–100%。不修改数据库、串口协议或执行器业务规则。部署后需要同步 Web 服务并烧录 B 板 V2.11。

回滚：revert 本 PR 并重新部署 Web 服务、烧录 V2.10。

## #34 [CLOSED] ISSUE fix: prevent OLED carousel from repeatedly resetting module B

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/34

## Problem
Module B emits a new ready frame roughly every 6–20 seconds while the OLED carousel is enabled. In one 25-minute MCP process, reset_count reached 87. Kernel logs show no USB disconnect or undervoltage event. Disabling the OLED carousel stopped the reset counter for the observation window.

## Scope
- rate-limit and coalesce OLED carousel writes
- make the module B watchdog tolerant of bounded OLED/SPI writes without disabling hang recovery
- add regression tests for command volume and watchdog servicing
- preserve all persistent data and actuator behavior

## Acceptance criteria
- unchanged OLED rows are not resent
- carousel writes cannot starve the module B watchdog
- existing automation and MCP tests pass
- deploy only after reviewed PR is merged

Hardware/operations: changes module B firmware and the PC_Test automation service; no database or serial protocol schema change.

## #33 [OPEN] ISSUE feat(automation): 超声波实时距离与门口持续接近拍照规则

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/33

用户要求将 B 板 HC-SR04 实时距离接入自定义规则，默认小于 50 cm 连续 2 秒拍照记录并持久保存。计划修改 PC_Test/web/hardware.py、automation/engine.py/capabilities.py/schema.py、extensions.py、security_monitor.py、automation.js/模板/双语词条、规则与安全记录 API、相关测试和文档。现无其他 open PR。验收：实时距离含有效性/新鲜度；可编辑阈值和持续时间；一次接近仅拍一次，离开/无效/断线重置；抓拍与原因/距离/规则信息保存并可查看；隔离全量测试和前端检查通过。复用现有 security 持久化，不改 Arduino 固件或串口协议，不迁移数据库；涉及香橙派服务部署。

## #32 [CLOSED] PR feat(module-b): 接入 HC-SR04 测距工具（Trig D6 / Echo D5）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/32

## 问题与行为
B 板新增 HC-SR04（Trig=D6、Echo=D5），原系统没有可调用的测距接口。新增 B 板 V2.10 固件命令 ultrasonic/read 与 MCP 工具 get_distance，经现有受认证保护的 POST /api/hardware/tool 调用，每次实时测量并返回厘米距离。

无回波/超范围返回 valid=false、distance_cm=null；迟到或无匹配 id 的距离帧不会串入下一次请求。测距失败不主动复位 B 板，不改变执行器状态、不写数据库、不新增自动联动。

## 实现与硬件影响
- Ultrasonic 驱动经 CommandDispatcher 接入 Protocol；触发脉冲 10 us、测量间隔 65 ms、回波等待上限 25 ms；有效范围 2–400 cm。
- D5/D6 与 TM1637 编译期互斥。配置、B 板接线、协议、API 和调用示例同步更新。
- 新增 9 项串口模拟/MCP/HTTP 测试，覆盖有效/无效距离、过期响应、断线、旧固件、普通 ACK 缺少测量、匿名拒绝和服务令牌调用。
- 无数据库迁移、Docker 编排变化、凭据或运行数据。

## 验证
- PlatformIO Uno 编译通过：Flash 25324/32256 bytes，RAM 1614/2048 bytes。
- 隔离 Windows 环境新增测距测试 9/9 通过；python -m compileall -q PC_Test 通过。
- Linux 全量测试通过：python -m unittest discover -s PC_Test/tests -v，145 tests，OK。使用一次性容器、--network none、无设备挂载，临时可写目录；复用本机 voice 镜像的 sounddevice/ALSA 依赖。Windows 全量 145 tests 中 6 个既有人脸中文路径读取错误，在 Linux 全部通过。
- 已部署合并提交 b938901f178d502118243770e0baacc8a215ce09，B 板固件 V2.10 烧录成功，avrdude 写入校验流程退出 0。正式 HTTP 工具实测 5 次：9.9、9.9、9.9、10.2、10.1 cm，全部 valid=true。

## 部署、审查与回滚
用户确认已完成独立审查，PR 已合并。已执行 scripts/sync_orangepi.ps1，同步本地/GitHub/香橙派到 b938901f178d502118243770e0baacc8a215ce09；B 板烧录前停止 Web/Voice 并备份旧固件，完成后恢复服务。Web、Camera、Voice 均 healthy，/api/ready=200，匿名硬件 API=401。已验证真实回波和完整 API 链路，尚未用尺标做精度标定。旧固件备份：/home/HwHiAiUser/smart-home-backups/ultrasonic-31/module-b-before-b938901.hex。
回滚需恢复上一个已验证的服务提交和 B 板固件，保留运行数据、模型和认证文件。

Closes #31
审查：用户已在本任务中明确确认已完成审查。

## #31 [CLOSED] ISSUE feat(module-b): 接入 HC-SR04 超声波测距（Trig D6 / Echo D5）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/31

B 板新增 HC-SR04，Trig=D6、Echo=D5，需要供后续程序调用。计划修改 module-b-output/src/Config.h、Protocol、drivers，PC_Test/mcp_home_server.py 及对应测试、调用文档。新增按需只读测距命令和 MCP/现有 HTTP 工具入口；超时/超范围不得伪装成有效距离；不新增自动执行器联动。验收：Uno PlatformIO 编译、隔离 PC_Test 全量测试通过，接线与协议文档一致。涉及串口协议和固件/服务部署，不涉及数据库迁移或 Docker 编排。

## #30 [OPEN] ISSUE fix(web): 暗色自定义灯让「命令未生效」判定长期误报（回读比的是峰值电平，不是命令亮度）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/30
- Labels: bug

## 问题和复现方法

「命令下发值 ≠ B 板硬件回读值」这条判定对**暗色/低饱和度的自定义颜色**永远为真，于是系统持续报告一次并没有发生的「静默失效」。

复现（需要 B 板在线、回读新鲜；纯离线跑不出来）：

1. 面板灯光卡片把自定义颜色设成 `#643214`（= RGB 100,50,20），亮度 100%；
2. 等过 `readback.py` 的稳定期（`CMD_SETTLE_S = 15s`）且回读新鲜（`RB_FRESH_S = 30s`）；
3. `GET /api/status` 的 `device_mismatch` 里出现 `{"device":"light","label":"灯光","commanded":100,"readback":39}`；
4. 同时 `automation_log` 落一条 `rule_id="cmd_not_applied"`、`success=0` 的「命令未生效审计」，日志里是 `WARNING [硬件桥] 命令成功但状态未变：[...]`（`hardware.py:391-399`）。

灯其实是好的：固件按 100% 不缩放地点亮了 (100,50,20)。换成饱和色（如 `#ff0080`，峰值通道 255）就不误报，只有峰值通道 < 255 的颜色会中。

## 根因（都在 `origin/main` = d093dfc 上核对过）

回读的是**峰值通道电平**，比较的却是**命令亮度百分比**，两者只在峰值通道 = 255 时才相等：

- `module-b-output/src/drivers/Light.cpp:53` `setRgb()` 里 `_level = max(r, max(g, b))`，而且是**亮度缩放之后**的值；
- 状态帧上报的就是它：`module-b-output/src/core/CommandDispatcher.cpp:218-219` `,"light":{"level":` + `_light.getLevel()`；
- web 侧把它按 255 折算成百分比：`PC_Test/web/hardware.py:120` `"rb_light_brightness": _pct(state.get("light"), 255)`；
- 比对表直接拿它和 `light_brightness` 比：`PC_Test/web/readback.py:17` `("light", "light_brightness", "rb_light_brightness", "灯光")`，判定在 `:50-63`（`int(cmd) == int(rb)`）。

按亮法逐条算（`brightness` = 命令百分比，`level` = 固件上报）：

| 亮法 | 固件行为 | level 折算 | 是否相等 |
|---|---|---|---|
| white | `setRgb(v,v,v)` | = brightness | ✓ |
| temp | `TEMP_TABLE` 每行 r 都是 255（`Light.cpp:18-25`），缩放后 r = v | = brightness | ✓ |
| night | `_level = level`（`Light.cpp:85`），只点居中 2 颗 | = brightness | ✓ |
| rgb 峰值 255（如 255,0,128） | 缩放后峰值 = v | = brightness | ✓ |
| **rgb 峰值 < 255（如 100,50,20）** | 缩放后峰值 = v × 100/255 | **= brightness × 峰值/255** | ✗ |

所以这不是 #27 引入的，是 main 上既有的判定口径问题；但 #27 之后「自定义颜色 + 任意亮度」成了面板的常规用法（以前调个亮度就把颜色打回白光，反而撞不上），暴露面明显变大。

顺带两个相关事实，别在修的时候踩：

- `readback_status()`（`hardware.py:96-99`）把 `rb_light_brightness` 直接写进 `light_brightness`/`light_status`，但它**只在 B 板复位对账时被调用**（`hardware.py:415`）。当前 `Config.h:39` 的 `LIGHT_BOOT_ON = 0`，复位后灯是灭的、level = 0，所以写回 0/off 是对的；一旦哪天把 `LIGHT_BOOT_ON` 打开，暗色就会被写成峰值百分比（100% → 39%），面板滑块跟着掉。修的时候要么一并换算，要么在注释里写清这个前提。
- `output_mismatch()` 目前**没有任何测试覆盖**（`PC_Test/tests/` 下搜不到 `output_mismatch`/`device_mismatch`），这也是它能一直误报的原因。

## 计划修改的模块与文件

只动 web，不碰固件、不碰串口协议、不碰 DB 结构：

- `PC_Test/web/light_state.py`：加一个「命令亮度 → 固件会上报的电平百分比」的换算（`rgb` 按 `max(r,g,b)/255` 折算，`white`/`temp`/`night` 原样返回），与 `hardware_plan` 放在一起，保证「下发什么」和「期待回读什么」是同一份知识；
- `PC_Test/web/readback.py`：灯光这一行改成拿**期望回读值**比，而不是拿命令亮度比。判定函数已经收整个 `status` 行，`light_mode`/`light_temp`/`light_rgb` 都在里面（#27 加的列），不需要改签名；
- `PC_Test/web/hardware.py`：`readback_status()` 写回 `light_brightness` 的口径跟着统一（换算回命令口径，或明确只写 `rb_*` 不写 `light_brightness`），并在注释里写清 `LIGHT_BOOT_ON` 这个前提；
- `PC_Test/tests/`：新增回读判定的单测（见验收条件）。

## 验收条件

1. 暗色自定义颜色（峰值 < 255）在任意亮度下**不再**产生 `device_mismatch` 与 `cmd_not_applied` 审计；
2. 真失效仍要报得出来：白/夜灯/色温/饱和色下，把回读值人为改成与命令不一致（含 0），判定必须命中——这条要用单测锁住，别只验「不误报」；
3. 单测覆盖五种亮法 × 至少两档亮度（含 0% 与 100%）× 峰值 255 / 峰值 < 255 两类颜色，并覆盖回读过期（`rb_seen_at` 超窗）与稳定期内（`output_last_seen` 未过 15s）两种「不判定」分支；
4. 门/窗/风扇三条判定行为不变（它们没有亮法维度）；
5. B 板复位对账写回的 `light_brightness` 与面板显示的亮度口径一致。

## 是否涉及串口协议 / 数据库结构 / Docker / 部署

都不涉及。纯 web 改动，合并后只需重建 web 容器；`rb_*` 列与 `light_mode`/`light_temp`/`light_rgb` 列都已存在，无迁移。

## 关联

#27 / PR #28 之后才容易撞上（颜色+亮度成了常规组合）。与 #29 无重叠。

## #29 [OPEN] ISSUE test(history): test_history_ui.js 的 DOM 桩缺 style/setAttribute，干净 main 上就 FAIL

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/29
- Labels: bug

## 问题和复现方法

`PC_Test/tests/test_history_ui.js` 在**干净的 `origin/main`** 上就是红的，不是任何在途分支引入的回归。PR #28（修 #27）跑全量时也被它挡住，所以在 #27 里只做了说明、没顺带改它（一个 PR 只解决一个问题）。

复现：

```bash
cd PC_Test
node --test tests/test_history_ui.js
```

```text
not ok 1 - NULL and empty history clear previous summary values
  error: "Cannot set properties of undefined (setting 'display')"
  applyStatView (evalmachine.<anonymous>:103:28)
  loadHistory (evalmachine.<anonymous>:125:5)
```

## 根因

**是测试桩的缺口，不是产品 bug。** 该测试用 `node:vm` 把 `history.js` 跑在假 DOM 上，`getElementById` 的桩只给了 `value` 和 `textContent` 两个字段：

```js
elements.set(id, { value: ..., textContent: '' });
```

而 `applyStatView()`（`PC_Test/web/static/js/history.js:101`）后来加了统计区的显隐与多语言标签逻辑，会碰 `.style.display` 和 `.setAttribute()`：

```js
const grid = document.getElementById('statGrid');
if (grid) grid.style.display = ...        // 桩对象没有 style -> TypeError
...
if (label) label.setAttribute('data-i18n', key);   // 桩对象没有 setAttribute
```

真页面上这些元素都在（`PC_Test/web/templates/history.html:71` 的 `#statGrid`，以及 `statMaxLabel/statMaxUnit` 等），所以产品代码无需改动。已实测验证：只给桩补 `style: {}` 和 `setAttribute() {}` 两个字段，用例即通过，产品文件一个没动。

顺带一提，`if (grid)` 这类守卫在真实浏览器里永远为真（元素存在），桩却因为总是返回对象而绕过了 `undefined` 分支——这条覆盖路径本身也是虚的，可以在本 issue 里一并收紧。

## 计划修改的模块与文件

只动测试，不动实现：

- `PC_Test/tests/test_history_ui.js`：给 DOM 桩补 `style`（可读写）、`setAttribute`，并让 `getElementById` 对页面里不存在的 id 返回 `null`，这样才真的走到源码的守卫分支。

## 验收条件

1. `node --test tests/test_history_ui.js` 通过；`node --test tests/` 下其余 JS 用例不受影响。
2. 不修改 `web/static/js/history.js` 与 `templates/history.html`（若发现确需改实现，那属于另一个 issue）。
3. 用例在干净 `origin/main` 上跑为绿，且在 PR #28 合并后的 `main` 上仍为绿。
4. 若打算把统计区在门窗/灯光下隐藏的行为做成断言（而不是只让它不抛异常），补一条针对 `dataType === 'door_window' / 'light'` 时 `statGrid.style.display === 'none'` 的断言。

## 是否涉及串口协议 / 数据库结构 / Docker / 设备部署

都不涉及。纯测试文件，无需重新部署任何容器。

## 与 #25 的关系

#25 要重做历史页（把门窗/灯光从折线改成状态时间轴），届时这段统计区显隐逻辑可能会被改写或删掉。本 issue 很小、可以独立先做；如果 #25 先动工，就把本 issue 的桩修复并入 #25 的分支，避免两次改同一个测试文件。

## #28 [CLOSED] PR fix(web): 灯光四种亮法统一成服务端状态并可互转 (#27)

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/28

Fixes #27

修复 Issue #27：面板上亮度、色温、颜色、夜灯四种亮法无法互相转化。

按 issue 里定的范围走**前后端闭环，不动固件**——串口协议一个字节都没改，B 板不用重烧。

## 问题

四种亮法各自为政：前端每改一次亮度就把亮法重置成 `white`，服务端也没记住「当前用哪种亮法」，所以：

- 调色温或选颜色之后，再拖亮度条 → 亮法被抹成白光；
- 关灯再开灯 → 恢复不出上次的颜色；
- 固件侧还有个缺陷：只带亮度的命令会清掉颜色。

## 改法

**`PC_Test/web/light_state.py`（新增）**：四种亮法的唯一真相源——互斥解析（优先级 `rgb > temp > mode`）、DB 行 ⇄ 协议状态互转、下发计划、标签。仿已有的 `web/ac_state.py`，面板 API、工具网关、`manual_report`、自动化引擎四处共用，避免各写一份而漂移。

**`web/database.py`**：`system_status` 增量迁移 `light_mode` / `light_temp` / `light_rgb` 三列并纳入 `OUTPUTS`（`get_current_status()` 是 `SELECT *`，所以 `/api/status` 自动带上）。

顺手修掉一个只在浏览器里才暴露的真 bug：`light_rgb` 在库里存成 `"r,g,b"` 文本，对外一律转成三元列表。`/api/status` 是公开契约，前端取色器和灯泡着色此前正是因为这个文本恢复失败的（HA 同样不该去猜存储格式）。

**四个写入路径**统一记账规则：请求没带亮法就沿用当前亮法，关灯只改 status、保留亮法；每条下发都自带**完整解析后的亮法**，因此固件「只调亮度会清色」的缺陷被直接绕开。

**亮度 0 语义统一为关灯**——此前有两处把 `on/0` 悄悄抬成 100%。

**前端 `main.js`**：删掉 `setLight`，换成 `setLightBrightness` / `setLightWhite` / `setLightNight` / `turnLightOff`；新增 `syncLightControls`，控件状态由服务端回填（滑块、色温标签、取色器、灯泡着色），带 `activeElement` 守卫以免打断正在拖动的滑块。卡片按钮改为 全亮 / 半亮 / 白光 / 夜灯 / 关闭。

## 验证

- `PYTHONPATH=. py -3.13 -m unittest discover -s PC_Test/tests`：**134 tests OK**（新增 `tests/test_light_style.py` 20 个，覆盖亮度继承、双向切换、关灯保留亮法、`on/0` 即关灯、`/api/status` 的 rgb 列表契约、工具网关记账、自动化引擎记账）。
- `node --test PC_Test/tests/test_light_ui.js`：**5/5 通过**（重写，含服务端回填与 onclick 函数名对齐校验）。
- 真实浏览器端到端：`PC_Test` 的临时副本 + 假 B 板（记录每次 `_hw_call`），确认实际下发的固件命令——
  - 4000K 下点「全亮/半亮」→ `control_light_temp(4000, 100/50)`（亮度不再清色温）
  - 自定义颜色下点「全亮」→ `control_light_color('rgb', 255, 0, 128, brightness_pct=100)`
  - 夜灯 → 半亮 → `control_light('on', 25, 'night')` → `control_light('on', 50, 'night')`
  - 「关闭」→ `control_light('off', 0)`，库里仍记 `light_mode=rgb`，再开灯颜色回来
  - 页面刷新后取色器回到 `#ff0080`、灯泡着色 `rgb(255, 0, 128)`
- 没碰真实 `PC_Test/data`（浏览器验证一律在临时副本里跑），临时副本与假设备日志已删除。

## 部署

合并后只需重建 web 容器；`system_status` 走增量 `ALTER TABLE`，历史数据保留。语音侧无需重启（不再持串口），积木规则里已有的灯光动作会自动带上当前亮法。

## 遗留

`PC_Test/tests/test_history_ui.js` 有 1 个用例在干净的 `origin/main` 上就已失败（测试 DOM 桩缺 `style`/`setAttribute`，非本 PR 引入），已记 #29。

## #27 [CLOSED] ISSUE fix(light): 亮度/色温/颜色/夜灯四种亮法无法互相转换，服务端也不回报当前亮法

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/27

## 问题和复现方法

灯光卡片有四个维度：亮度、色温、自定义颜色(RGB)、夜灯/白光亮法。它们目前**不能互相转化**，每一层各丢一块信息。逐条复现（全部在当前 `main` = d093dfc 上成立）：

1. **选好色温或自定义颜色后点「全亮/半亮」→ 变回白光。**
   `setLight()` 无条件把 `lightStyle` 改写成 `{ mode }` 或 `{}`（`PC_Test/web/static/js/main.js:593`），而「全亮/半亮」两个按钮不带 mode（`PC_Test/web/templates/dashboard.html:204-205`）→ 亮法被清成白光，同时亮度被硬写成 100/50。

2. **刷新页面后拖亮度滑块 → 白光，且界面上的色温/颜色是假的。**
   `lightStyle` 初值 `{}`（`main.js:19`，注释自己写明「状态接口只回传开关/亮度」）。服务端确实没有这个信息：`system_status` 只有 `light_status/light_brightness` 两列（`PC_Test/web/database.py:134-137`），`_record_light(status, level)` 把亮法丢掉（`PC_Test/web/api/devices.py:411`），B 板 state 帧也只回报 `getLevel()`（`module-b-output/src/core/CommandDispatcher.cpp:183-184`）。结果色温滑块永远显示 4000K、取色器永远显示 `#ffb347`，与硬件实际亮法脱节，用户下一次操作是基于错误假设下发的。

3. **没有「保持亮度只换亮法」的路径。**
   后端按 `off > rgb > temp > mode` 优先级择一（`devices.py:397-409`），所以从夜灯/白光 → 色温/RGB 可以（`applyLightTemp`/`applyLightColor` 会带当前亮度，`main.js:604,619`），但反过来从色温/RGB 回到普通白光只能借道「全亮/半亮」，等于被顺带改了亮度。

4. **亮度 0 的语义三处不一致。**
   `devices.py:387-388`：`status=on` 且 `brightness=0` 被强制改成 100；`hardware.py:663,671`：`<=0` 转成 off。所以在 RGB 下把亮度滑到 0 不是「暗到灭」而是关灯，滑回来时前端仍记着 rgb、后端却走了另一分支。这正是 #9 里「value=0 语义」那条的残留。

5. **固件侧色温和颜色是同一条通道，互相覆盖。**
   硬件是单条 WS2812 而非双色温灯带（`module-b-output/src/drivers/Light.cpp:7`），色温靠查表近似成 RGB（`Light.cpp:17-25` `TEMP_TABLE`，2700K→`255,169,87`），`setRgb()` 又把 `_level = max(r,g,b)` 覆写进去（`Light.cpp:53-61`），`white(level)` 直接 `setRgb(level,level,level)`（`Light.cpp:73-76`）。即「只给亮度的命令」必然把颜色重置为白光——颜色与亮度没有分离。

## 与 Issue #9 的关系

#9 的第 1 项（Uno 上 `255*255` 16 位溢出）**已修**：现在走 `LightMath.h:7-9` 的 `(uint32_t)channel*level/255`。剩下三项（value=0 语义、色温标签与温度卡片共用 `tempValue` ID（`dashboard.html:68` 与 `main.js:311` 确实同名）、调亮度丢模式）与本 Issue 同源，建议由本 Issue 承接，或在 #9 里标注分工，避免两个分支同时改 `Light.cpp` 和 `main.js` 撞车。

## 计划修改的模块与文件

- `PC_Test/web/static/js/main.js`（`lightStyle` 的来源与提交语义：亮法不再被按钮清空，改为从服务端回报初始化）
- `PC_Test/web/templates/dashboard.html`（四种亮法的选中态呈现；`tempValue` ID 冲突）
- `PC_Test/web/api/devices.py:335-430`（`control_light` 的组合语义与 `brightness=0` 唯一语义；`_record_light` 持久化亮法）
- `PC_Test/web/hardware.py:657-698`（`<=0` 转 off 的收口）
- `PC_Test/web/database.py:134-137,226`（`system_status` 需要能表达当前亮法 → **涉及数据库结构与迁移**）
- `module-b-output/src/drivers/Light.cpp`、`include/Light.h`（颜色与亮度分离：`_level` 不再由 `max(r,g,b)` 推导；`white()` 不重置颜色）
- `module-b-output/src/core/CommandDispatcher.cpp`、`src/Protocol.cpp`（state 帧回报当前亮法）
- `PC_Test/tests/test_light_ui.js`（互转回归）、串口协议文档
- 声明冲突风险：本 Issue 会同时碰 `dashboard.html`、`main.js`、`devices.py`、`Light.cpp`，开工前需确认 #9 与 #23（平面图控制设备）没有并发改这些文件

## 验收条件

1. 四种亮法（白光/夜灯/色温/RGB）在**保持当前亮度**的前提下任意互转；改亮度、改色温都不丢另一维度（含从色温/RGB 回到白光）。
2. 刷新页面、换浏览器、5 秒轮询之后，界面显示的亮法与硬件实际一致：色温滑块/取色器/夜灯高亮来自服务端回报，不再是本地默认值。
3. `brightness=0` 有唯一确定语义（明确选「关灯」或「最暗」），前端、`devices.py`、`hardware.py`、固件四处一致，并写进协议文档；不再出现「on+0 被改成 100」。
4. 后端对互斥组合要么按文档化优先级执行并回报**实际生效**的亮法，要么 400 拒绝；不再静默择一后只记亮度。
5. 回归：`PC_Test/tests/test_light_ui.js` 覆盖上述互转与回报还原；`python -m unittest discover -s PC_Test/tests -v` 在隔离环境（无真实串口）全绿；Uno `platformio run` 编译通过。
6. 浏览器验证必须在 `PC_Test` 的临时副本上做（真库与真人脸照片风险），验证完删除副本。

## 影响面

**涉及串口协议**（state 帧新增字段 + `light` 命令语义变更，需前后向兼容评估）、**涉及数据库结构**（`system_status` 表达当前亮法，需要迁移）、**涉及设备部署**（B 板重新烧录 + 派上 web 容器重建，同一时间只允许一个部署者）。不改 Docker 编排。

> 注意：#24 里记录过 Uno 侧 `255*255` 类整数问题已修，本 Issue 不要重复修那处；协议帧字段变更要在 Issue 里先贴出前后对比再动代码。

## #26 [CLOSED] PR feat(automation): 积木工具箱与规则卡片摊平，去掉折叠层级（#18）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/26

Closes #18

## 改了什么

1. **工具箱只留一层分类**：删掉 `触发→事件`、`条件→全局状态`、`动作→全局状态` 三个子分类，积木一律直接列出，组与组之间用 `<sep gap="14">` 做视觉分隔。`PC_Test/web/static/js/automation.js` `buildToolbox()`。
2. **规则卡片摊开显示**：条件、动作、否则分支逐条成 chip（`如果全部/任一` → 条件 → `→` → 动作 → `否则` → 动作），不再压成「开门 等 3 项」。`ruleCardHtml()`，新增 `summarizeConditions()` / `summarizeActionList()`，条件复用 `summarizeTrigger()` 的标签换算（条件与传感器触发同形）。meta 行的动作计数改为含 else 分支。
3. **样式**：`PC_Test/web/templates/automation.html` 加 `.rc-flow`（flex-wrap + `max-height:92px` 行内滚动）与 `.chip` 系列；JS 版本号 bump 到 `20261004a`，避免旧缓存。

规则 JSON 与积木 XML 结构**未改**，后端 `schema.py` / `default_rules.py` / 引擎均未触碰，无数据库迁移。

## 为什么条件也各自成格

第一版把全部条件拼进一个长 chip，实测 5 条件的规则（如「有人：高于26°C开风扇」）在 `white-space: nowrap` 下会撑出横向滚动。改成一条一格后浏览器实测 `scrollWidth <= clientWidth`。

## 测试

- 新增 `PC_Test/tests/test_blocks_flat_ui.js`（5 条）：分类嵌套深度必须为 1、每个已注册 `trig_/cond_/act_/rule_block` 积木都能在工具箱拿到且无悬空引用、卡片全展开无「等 N 项」、条件/动作逐条成格、卡片文本走 `esc`、`.rc-flow` 允许换行与滚动。
  用 `git show origin/main:...` 的旧文件反跑过：第 1、3 条在改前 FAIL，确认不是自证。
- `PYTHONPATH=. py -3.13 -m unittest discover -s PC_Test/tests` → **115 tests OK**（隔离环境、无真实串口）。
- `node --test PC_Test/tests/test_blocks_flat_ui.js` 5/5；`test_light_ui.js` 2/2。
- `test_history_ui.js` 1 FAIL：在干净 `main`（d093dfc）上同样失败（`Cannot set properties of undefined (setting 'display')`），与本 PR 无关，另案处理。

## 浏览器实机验证

按仓库约定在 `PC_Test` 的**临时副本**上跑（独立空 `data/`、`serial.enabled=false`、一次性沙箱凭据），未接触真库与注册照片：

- 列表页：24 条内置规则卡片全部摊开，`truncated = 0`，无 chip 溢出容器。
- 编辑器：工具箱 accessibility tree 为 4 个 `level=1` 项、0 个可展开文件夹；「动作」flyout 一次列出 21 块（改前有 5 块藏在折叠里）。
- 往返：打开规则 → 直接保存，24 条规则 JSON 逐字节相同。
- 沙箱目录与进程已清理。

## 复审要点

- 卡片高度：内置规则现在普遍多一行 flow，长列表变高是否符合预期（`.rc-flow` 已限 92px 滚动）。
- 工具箱 21 块的动作 flyout 变成一屏多（约 5 屏滚动），确认这是「扁平化」想要的取舍，而不是需要保留分组视觉。
- Uno 侧、串口协议、数据库、Docker 编排均无改动；部署只需重建 web 容器。

🤖 Generated with [Qoder](https://qoder.com)


---

## 分支规划：#27（灯光四种亮法无法互转）

顺手把 #27 与本 PR 的排期核对过文件清单，结论记在这里，免得后面有人按「都改前端」的直觉去串行。

| 范围 | 本 PR #26 | #27 |
|---|---|---|
| 前端 | `automation.js`、`templates/automation.html` | `main.js`、`templates/dashboard.html` |
| 后端 | 未触碰 | `api/devices.py`、`hardware.py`、`database.py` |
| 固件 | 未触碰 | `drivers/Light.cpp`、`Light.h`、`CommandDispatcher.cpp`、`Protocol.cpp` |
| 测试 | `tests/test_blocks_flat_ui.js` | `tests/test_light_ui.js` |

1. **#26 与 #27 文件完全不相交** → #27 不需要等 #26 合并，可以直接从最新 `origin/main` 开 `fix/27-light-style-state` + 独立 worktree 并行做。两边唯一的小摩擦是模板里的 `?v=` 缓存串（本 PR 已 bump 到 `20261004a`），后落地的一方按当时值统一即可。
2. **#9 归并进 #27，不单独开分支**：#9 剩余三项（`brightness=0` 语义、色温标签与温度卡片共用 `tempValue` ID、调亮度丢模式）与 #27 是同一处代码，拆开改必然冲突；#9 的 `255*255` 溢出已修，无需再动。
3. **真正要串行的是 #27 与 #23**：两者都要改 `main.js` 的灯光控件与 `dashboard.html` 的灯卡片，#23 还依赖 `GET /api/status` 回报可信的「当前亮法」——而那个回报正是 #27 要补的。建议顺序 **#27 → #23**，#23 在 #27 合并后从 `origin/main` 起分支。
4. **部署窗口单独占**：#27 涉及 state 帧字段变更 + B 板重新烧录，属协议变更，必须等 #26 部署完成、派上 `/api/ready` 与 Docker 健康确认之后，单独占一个部署窗口（同一时间只允许一个部署者）。协议改动先在 #27 里贴出前后帧对比，再动代码。

## #25 [OPEN] ISSUE feat(history): 门窗/灯光历史改为设备状态时间轴（重做被丢弃的 84052c0）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/25

## 问题和复现方法

历史页把 4 类数据都用同一套「折线 + 表格」呈现：温度/湿度/门窗/灯光（选项 `PC_Test/web/templates/history.html:48-53`；取数与画线 `static/js/history.js:133-197`）。对开关量这是错的：门窗被画成 `status==='open'?1:0` 的折线（`history.js:185`），灯光画 `brightness`（`187`），而 #12/PR #12 干脆为门窗/灯光**隐藏了统计块**（`history.js:100-104`），所以这两类历史现在既看不懂也看不到「开过几次、开了多久」，也缺「最高温度」那一行的多维汇总。

已有未合并的尝试：提交 `84052c0`（`origin/feat/history-state-timeline`，无 Issue 无 PR）实现了设备状态时间轴，改动纯前端 4 文件 +254/-25 —— `static/css/style.css`、`static/js/history.js`、`static/js/lang.js`、`templates/history.html`。该分支落后当前 main（不含 #12/#15/#17 之后的改动），**不能直接合并**，需要在新分支上重做或 rebase 后走 PR。

数据侧已就绪，不需要新表：`door_window_history(id,timestamp,device_type,device_name,status)`、`light_history(id,timestamp,light_name,status,brightness)` 建表 `PC_Test/web/database.py:168-169`、索引 `200-201`。写入点三处：手动 `database.py:409-415` ← `web/api/devices.py:55-57,61-63,67-69`；自动化 `automation/engine.py:1037,1065`（标签「前门(自动化)/客厅窗户(自动化)」`1029`）；遥测 `database.py:305-307`。可复用查询：`GET /api/door_window/history?hours=`（`devices.py:317-320`）、`GET /api/light/history`（`441-444`）、`/api/temperature`（`api/status.py:52-55`），底层 `database._history`（≤720h、上限 5000 行，`database.py:372-407`）。

## 计划修改的模块与文件

- `PC_Test/web/static/js/history.js`、`templates/history.html`、`static/css/style.css`、`static/js/lang.js`（中英文案）
- 汇总行（含最高温度）若需后端聚合：`PC_Test/web/database.py`、`web/api/status.py` / `devices.py`

## 验收条件

1. 门窗/灯光以状态时间轴（分段条 + 区间时长）展示，不再是 0/1 折线；能直接看出「几点到几点是开的」「今天开了几次」。
2. 温度/湿度保持折线 + 统计（最高/最低/平均），湿度标签与「最高温度」那一行不回归（#12 已修的显示问题保持）。
3. 时间轴在 720h/5000 行上限下不卡；超限时明确提示而不是静默截断。
4. 注意 `door_window_history` / `light_history` **不参与保留期清理**（清理只覆盖温湿度与传感器，`database.py:310-339`）——本 Issue 内给出结论：是否需要一并清理（如需则涉及数据删除，单独确认后再做）。
5. 浏览器实机验证（历史页 4 类数据各切一遍）；`python -m unittest discover -s PC_Test/tests -v` 全绿。

## 影响面

不改串口协议、不改 Docker。数据库结构默认不动（除非选择做保留期清理，届时在本 Issue 内说明）。涉及设备部署（web 容器）。

## #24 [OPEN] ISSUE perf(face): 识别收尾——imgsz 可配置（当前硬编码 640）与门口端到端复测

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/24

## 问题和复现方法

人脸识别前两阶段已合并部署（#10/PR #13 消除首帧冷启动罚与 PIR 空等；#14/PR #15 嵌入模型换 MobileFaceNet w600k_mbf，派上实测 93ms p50）。剩余两项：

1. **检测输入尺寸硬编码**：`imgsz=640` 写死在 `PC_Test/web/face/engine.py:98`，**不读 yaml**，传入 `engine.py:177` → `web/face/detector.py:43,68`。跑 416 能省下的推理时间完全没法验证，只能改代码。运行期可写的 `data/face/face_config.json` 已被 gitignore（`.gitignore:48`），不能作为配置来源。
2. **门口端到端未复测**：轻模型部署后没重新量过「PIR 触发 → 认出/拒绝 → 开门」的端到端耗时。当前节流参数：`recognition_interval 1.5s`（`face/engine.py:80-81,105`，覆盖 `web/utils.py:42` 的默认 2.0）、哨兵唤醒下限跟随节流 + `MIN_WAKE_SPACING_S 0.4`（`face_watcher.py:29,135-138`）、PIR 门控 `interval 2.0 / motion_gate true / motion_hold 20 / cooldown 60 / min_face_px 60`（`web_config.yaml:69-75`，代码默认同名 `face_watcher.py:30-31,73-82`，`min_face_px` 在提特征前生效 `engine.py:403-423`）。

另需注意：派上常态负载 ~20，识别哨兵必须保持 PIR 门控且 `interval ≥ 2s`，任何降延迟改动都要重新核对这条。

## 计划修改的模块与文件

- `PC_Test/web/face/engine.py`（`98` 默认值改为读配置；`177` 传参链路）
- `PC_Test/web_config.yaml`（新增检测 `imgsz` 项，与 `confidence 0.4 / iou 0.45 / max_faces 5`（`48-50`）、`similarity_threshold 0.5`（`64`）、嵌入输入 112×112（`65`）并列）
- `PC_Test/web/face/detector.py:43,68`
- `docs/face-models.md`、`docs/configuration.md`（记录实测数值）

## 验收条件

1. `imgsz` 可配置且校验合法范围，640 为默认值（行为与今日一致）。
2. 给出 416 vs 640 在同一批门口帧上的 detect 耗时与漏检/误检对比数据（含空帧基线，因为 detect 与空帧同价）。
3. 门口端到端复测报告：PIR→开门 的 p50/p95，分别记录「已注册」「陌生人」「无人」三种情形。端到端开门验证需用户在场。
4. 首帧预热不回归（`face/engine.py:300-336`、`web/extensions.py:81-83`）。
5. 隔离环境 `python -m unittest discover -s PC_Test/tests -v` 全绿；部署后 `/api/ready` 健康、匿名 API 仍被拒。

## 影响面

不改串口协议、不改数据库结构、不改 Docker。涉及设备部署（需在派上真实摄像头前复测，浏览器验证时注意人脸库为 A/B/C 三身份 8 张的现状，别触发删除）。

## #23 [OPEN] ISSUE feat(web): 房间平面图图形化设备控制（点窗即开窗）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/23

## 问题和复现方法

设备控制目前是一排排卡片 + 装饰性 SVG，没有空间形态的可视化：门（`PC_Test/web/templates/dashboard.html:137-173`，按钮 `157,169`）、窗（同区块）、灯（`176-217`）、风扇（`99-134`）、空调（`220-268`）、快捷遥控矩阵（`288-350`）。处理器在 `static/js/main.js:530-546`（门/窗 toggle）、`562-600`（灯）、`628-650`（风扇）、`660-710`（空调 + `remoteControl` 映射 `697-700`），防误连点 `tapGuard/guardDoor`（`main.js:540`）。

问题：用户要按「哪个房间/哪扇窗」思考，界面却按「设备类型」组织；仓库内全量搜索无 floor/room/平面图元素。目标是在平面图上点窗即开窗、点灯即切灯，状态用图形本身表达。

## 计划修改的模块与文件

- `PC_Test/web/templates/dashboard.html`、`static/js/main.js`、`static/css/style.css`
- 新增平面图 SVG/图形资源（放 `PC_Test/web/static/`）
- 设备清单：现在 HTML 里硬编码、**没有设备列表 API**。可复用 `GET /api/automation/capabilities` 的 devices（`PC_Test/web/api/automation.py:13` → `automation/capabilities.py:136-204`），或新增只读 `/api/devices`
- 状态来源：`GET /api/status`（`main.js:272` → `web/api/status.py:14-28` → `database.get_current_status:225-241`）
- 下发通道沿用：`POST /api/door|window|light|fan|ac`（`web/api/devices.py:247,286,382,455,494`）

## 验收条件

1. 平面图上的可交互元素与现有设备一一对应，点击行为与卡片按钮等价（同样走 `_DeviceGate` 记账与 `manual_control` 广播，`devices.py:25-57,122-160`）。
2. 状态变化后平面图同步更新（沿用 `/api/status` 轮询或现有 SSE/广播通道）。
3. 保留现有防误触（连点合并）与无权限时的拒绝行为；匿名请求不得下发（`/api/ready` 与鉴权回归）。
4. 图形化不替换卡片视图，作为可切换视图存在，避免 dashboard 其他功能回归。
5. 浏览器实机验证（含点击开窗/关窗、灯亮灭）；`python -m unittest discover -s PC_Test/tests -v` 全绿。

## 影响面

不改串口协议、不改数据库结构、不改 Docker。涉及设备部署（web 容器）；点击即开窗属于真实执行动作，验证时需在人在场的条件下进行。

## #22 [OPEN] ISSUE feat(sensor): 光照传感器校准——线性映射表与 lux 语义（自然光读数 A / 遮挡读数 B）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/22

## 问题和复现方法

光照通道从采集到入库全程都是原始 ADC 值，**既不是 lux 也没有任何校准**：

- Arduino：`LIGHT_PIN A5`（`module-a-sensor/src/Config.h:42`）、`analogRead` 不做换算（`src/sensors/LightSensor.cpp:9-14`）、上报 0-1023（`src/core/SensorManager.cpp:92` → `src/Protocol.cpp:52-53`）。`Config.h` 里没有光照阈值/校准宏（对比雨水有 `RAIN_THRESHOLD`，`Config.h:50`）。
- Web：入库截到 0-1023 的 `light_raw`（`PC_Test/web/database.py:140,173,286-289`），引擎按裸数值比较，单位就写成 `"0-1023"`（`automation/capabilities.py:41`），仪表盘不显示照度（`static/js/main.js:309-427`）。
- 二值化只发生在派生规则的阈值上：暗/亮 200、300 硬编码在 `automation/default_rules.py:125,136`。
- 校准配置项**不存在**（`PC_Test/web_config.yaml` 无 light 段，`ha_config/*.yaml` 无相关项）。`docs/home-automation.md:8` 已经声明「需要实测校准」，但没有落地任务。

后果：200/300 这两个阈值是按当前分压电阻和摆放位置猜出来的，换位置/换光照环境后规则就跑偏；也无法回答「现在算不算白天」这类需要真实照度的判断。

先要确认的开放问题：**这个光敏在实际接线上是二流（开关量够不够用）还是需要连续的模拟量**。当前代码走 `analogRead`，即按连续量处理；本 Issue 按连续量 + 两点标定推进，若现场验证为只需有光/无光，则在 Issue 内收窄为阈值校准。

## 计划修改的模块与文件

- `module-a-sensor/include/Config.h` 或 `src/Config.h`、`src/sensors/LightSensor.cpp`、`src/core/SensorManager.cpp`（保持上报原始 ADC，避免在 Uno 侧做映射；换算留在 web 侧便于调整）
- `PC_Test/web_config.yaml`（新增 `light.calibration` 段：`raw_dark` B、`raw_bright` A、目标量程、平滑窗口）
- `PC_Test/web/database.py`（`light_raw` 之外存换算后的照度，或只在读取层换算 —— 实现时在本 Issue 里定案）
- `PC_Test/web/automation/capabilities.py:41`（单位从 `0-1023` 改为换算后语义）
- 校准向导：`PC_Test/web/static/js/`、`templates/` 下新增读数采样界面（自然光读 A、手捂住读 B）
- `docs/home-automation.md`

## 验收条件

1. 提供可复现的两点校准流程：记录自然光读数 A、完全遮挡读数 B，生成线性映射；A≤B 或 A、B 差值过小时明确报错而不是静默生成反相映射。
2. 校准参数缺失时回落到当前裸 ADC 行为，规则不被破坏（向后兼容）。
3. 阈值语义文档化：换算前后各是什么范围，`default_rules.py` 的 200/300 如何迁移。
4. 单测：映射函数含边界（0、1023、A、B）；`python -m unittest discover -s PC_Test/tests -v` 全绿。
5. Uno 侧编译通过（`platformio run`），串口协议帧格式**不变**——只加不改现有字段。

## 影响面

涉及串口协议兼容性评估（结论：不改帧结构）、可能需要数据库新增列（决定后立即更新本 Issue 并写迁移）、涉及设备部署（Uno 重新烧录 + 派上 web 重启）。同一时间只允许一个人部署。

## #21 [OPEN] ISSUE fix(automation): 给缺去抖/冷却的触发源补防抖，消除误触发

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/21

## 问题和复现方法

逐个触发源核对现状后，**已有节流的**：PIR 固件去抖 5000ms（`module-a-sensor/src/Config.h:82`）+ 边沿基线（`src/core/SensorManager.cpp:76-87,112-163`）、快照 2s（`PC_Test/web_config.yaml:17`）、哨兵保持窗 20s/失活 120s（`PC_Test/web/face_watcher.py:26,30-31`）；人脸识别 1.5s 引擎节流（`web/face/engine.py:80-81`）+ 同脸 60s（`face_watcher.py:31,198-202`）+ 凭证去重窗 8s（`web/access_guard.py:32,86-99`）+ 事件 ts 去重（`automation/engine.py:498-507`）；烟雾/雨水固件 1000/3000ms（`Config.h:79-80`）；红外防连按 500ms（`src/sensors/IRSensor.cpp:31`）、键盘 40/120ms（`Config.h:63-64`）。

**没有防抖、会误触发的**（复现方式随附）：

1. **光照**：阈值 200/300 回差写在 `automation/default_rules.py:118-139`，但 `cooldown 0` 且无 hold。手影/车灯扫过 → ADC 抖动在阈值附近来回穿越 → 灯反复开关。
2. **温湿度联动**：边沿触发 + `sensor_fresh` 10s 门控（`engine.py:743-746`），预设 26/25 回差（`default_rules.py:95-117`），但 cooldown 0、无 `hold_sec`、无最小间隔，`interval 2s` 每轮复评 → 温度卡在阈值线上时风扇反复启停。
3. **触摸开门**：固件 300ms 去抖（`Config.h:78`），但预设 `touch_open_close` **cooldown=0** 且直接开门 + 10s 关门（`default_rules.py:186-193`）；连续触摸会把关门定时器顶掉，只靠动作锁（`engine.py:895-898`）兜。
4. **雨水/门窗**：`rain_window` / `window_normal` cooldown 0（`default_rules.py:167-185`），磁簧抖动会连续写历史 + 连续播报。
5. **语音**：`/trigger`、`act_voice` 完全无限频（`engine.py:1004-1017`、`web/api/voice.py:53-64`），回声/重复唤醒会连发指令。

## 计划修改的模块与文件

- `PC_Test/web/automation/default_rules.py`（各预设补 `cooldown` / `hold_sec`）
- `PC_Test/web/automation/engine.py`、`automation/schema.py`（若需要新的最小间隔参数）
- `PC_Test/web_config.yaml`（光照去抖相关，与 Issue「光照校准」联动）
- `PC_Test/web/api/voice.py`（`/trigger` 限频）

## 验收条件

1. 上述 5 类触发源逐项给出结论：已加去抖 / 确认无需去抖（写明理由），不允许留空。
2. 阈值附近抖动场景（合成 ±5 噪声序列）下单规则触发次数有上界，单测覆盖。
3. 连续触摸只产生一次开门 + 一个关门定时器；重复语音唤醒不产生重复动作。
4. 隔离环境 `python -m unittest discover -s PC_Test/tests -v` 全绿。

## 影响面

不改串口协议（`Config.h` 现有去抖宏保持不变）、不改数据库结构、不改 Docker。涉及设备部署：新默认规则要在派上确认 seed 行为，避免与用户已存规则重复。

## #20 [OPEN] ISSUE feat(automation): 补强 sleep 积木（现有 delay 为阻塞式、上限 300 秒、无法等待事件）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/20

## 问题和复现方法

「等一会儿再做」的能力其实已经存在：动作类型 `delay`（1~300 秒）在 `PC_Test/web/automation/engine.py:944-951` 实现，参数校验 `automation/schema.py:153-158`、白名单 `automation/capabilities.py:165`，积木 UI `static/js/automation.js:417-426`（工具箱 `864`、摘要 `989`、序列化 `1695`、反序列化 `1923`）。但当前实现有三个体验/能力缺口，用户在实际规则里遇到：

1. **阻塞**：每条规则一个 daemon 线程 + 单规则动作锁（`engine.py:895-901`、`_run_actions:905-937`），延时期间这条规则被占住，同规则的新触发只能靠取消位打断，其它规则不受影响但没有优先级/排队语义。
2. **上限 300 秒**：「开门后 10 分钟自动关门」「每天定时播报」这类需求直接写不出来（`schema.py:153-158`）。
3. **只能等时间，不能等事件**：现有等待事件语义分散在两处且不可组合——触发侧「持续 N 秒」`_evaluate_sensor_rule:833-845`、1 秒滴答线程 `_tick_loop:574-595`（interval 触发 ≥2s `schema.py:115-119`、定时 HH:MM `589-593`）。规则中间没法插「等到门关上再继续」。

## 计划修改的模块与文件

- `PC_Test/web/automation/engine.py`（`_perform` 的 delay 分支 `939-951`；若引入非阻塞调度需改 `_run_actions:905-937` 与 `_tick_loop:574-595`）
- `PC_Test/web/automation/schema.py:153-158`、`automation/capabilities.py:165`
- `PC_Test/web/static/js/automation.js:417-426`
- `PC_Test/tests/`（新增引擎调度单测）

## 验收条件

1. 上限提升后的延时在服务重启时的语义明确并写入文档（丢失 / 持久化后恢复），不出现「重启后突然执行」的意外动作。
2. 延时可被同规则新触发取消（现有取消位行为保留），并有单测覆盖取消路径。
3. 若引入「等待事件」积木，等待超时有上界，不会让规则线程无限挂起。
4. 隔离环境 `python -m unittest discover -s PC_Test/tests -v` 全绿，新增用例覆盖：长延时、延时中重启、延时中被取消。

## 影响面

不改串口协议、不改数据库结构（若选择持久化待执行任务则需要新表，届时在本 Issue 里更新说明）、不改 Docker 编排。改动仅在 web 容器内。

## #19 [OPEN] ISSUE refactor(automation): 收口硬编码开/关门路径，让门禁行为由 Blocks 规则决定

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/19

## 问题和复现方法

自动化引擎本身已经没有写死的开门 handler（策略下沉为默认规则，`PC_Test/web/automation/engine.py:22` 注释），但仍有 4 条完全绕过引擎的开关门/锁路径，导致「改了 Blocks 却发现门还是按别的地方开的」：

1. 面板 REST 直控：`PC_Test/web/api/devices.py:247-275`（`POST /api/door`）、`286-314`（`/api/window`），经 `_DeviceGate`（`122-160`）直接下发并广播 `manual_control`（`25-57`）。
2. 语音/外部工具网关：`devices.py:555-595` 可直发 door 工具；MCP 侧 `PC_Test/mcp_home_server.py:720-724`、工具声明 `859-869`——不经任何规则评估。
3. HomeAssistant 旁路开关锁：`PC_Test/web/ha_client.py:230-236`、`PC_Test/web/api/ha.py:93-96`，页面按钮 `PC_Test/web/templates/hardware.html:154-161` + `static/js/hardware.js:225-227`。
4. 键盘密码在 MCP 子进程内校验并上报 granted：`mcp_home_server.py:36-38`（密码 1111、10s 窗口）、`312-341`，归一交给 `PC_Test/web/access_guard.py:196-202`。

另外「内置预设」仍是隐性硬编码：`engine.py:360-400`（`seed_presets` 自动注入）+ `automation/default_rules.py:9-16,186-193`（门禁/触摸开门 + 10s 关门）。文档漂移：`docs/home-automation.md` 引用的 `access_auto_close` 预设已从 `engine.py:159-162` 的删除清单移除。

复现：删掉所有 Blocks 规则后，网页门按钮、语音「开门」、HA 服务、键盘密码仍然可以开门。

## 计划修改的模块与文件

- `PC_Test/web/api/devices.py`、`PC_Test/web/ha_client.py`、`PC_Test/web/api/ha.py`
- `PC_Test/mcp_home_server.py`、`PC_Test/web/access_guard.py`
- `PC_Test/web/automation/engine.py`（`seed_presets`、默认规则）、`automation/default_rules.py`
- `docs/home-automation.md`（同步文档，消除 `access_auto_close` 漂移）

## 验收条件

1. 明确分类并写进文档：哪些是「用户显式指令」（面板/语音/键盘，允许旁路）、哪些是「自动化行为」（必须走规则，不得旁路）。
2. 触摸开门、10s 自动关门、有人联动这类自动化行为全部能在 Blocks 里看到、能删掉且删后真的不再发生。
3. `default_rules.py` 预设保持数据驱动，去掉 `seed_presets` 里不可见/不可删的写死动作。
4. 回归：删除全部规则 → 自动化触发不再产生开门；手动/语音/键盘路径行为不变。
5. 隔离环境 `python -m unittest discover -s PC_Test/tests -v` 全绿（不接真实串口）。

## 影响面

不改串口协议、不改数据库结构、不改 Docker 编排。涉及设备部署（ Uno 侧行为无变化，但需现场验证门控）。

## #18 [CLOSED] ISSUE feat(automation): Blocks 规则编辑去掉折叠层级，改为扁平化列表

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/18

## 问题和复现方法

规则数据模型已经是扁平数组（每条规则恰好 1 触发 + 条件组 + 动作组，无 group/子规则），但编辑界面把内容藏在三层折叠里，用户要点开才知道有什么：

- Blockly 工具箱用嵌套 category，渲染成可点开合的文件夹：触发→事件、条件→全局状态、动作→全局状态（`PC_Test/web/static/js/automation.js:809-879`，其中 `821-830`、`838-846`、`865-877`）。
- 规则本体是 C 型容器块，子块必须逐层展开（`automation.js:65-86` 的 `rule_block`，装配 `1454-1469`，回收 `1471-1492`，摊平 `1543-1548`）。
- 卡片列表把动作压成一行「等 N 项」摘要并强制单行截断（`automation.js:1035-1040`、`1103-1131`；`PC_Test/web/templates/automation.html:36-41`），工具箱宽度写死 96px（`automation.html:74-79`）。

复现：打开自动化页 → 想找一个「动作」积木必须先展开两层分类；已有规则看不到动作内容，必须先点开卡片或进编辑器。

## 计划修改的模块与文件

- `PC_Test/web/static/js/automation.js`（工具箱结构、卡片摘要、注入点）
- `PC_Test/web/templates/automation.html`（工具箱宽度、卡片样式）
- `PC_Test/web/static/css/style.css`
- 后端契约不动：`PC_Test/web/automation/schema.py:375-410`、`default_rules.py` 保持扁平结构，不加 group 字段

## 验收条件

1. 常用积木（触发/条件/动作各主要项）在扁平列表中一次可见，无需展开子分类；分类若保留则默认展开。
2. 规则卡片直接显示全部动作与条件，不用进编辑器；长列表可滚动而不是截断成「等 N 项」。
3. 现有规则 JSON 与 Blockly XML 往返（导入/导出、保存/重开）结果字节级等价，不需要数据库迁移。
4. 隔离环境跑 `python -m unittest discover -s PC_Test/tests -v` 全绿；JS 回归覆盖卡片渲染与 XML 往返。

## 影响面

不改串口协议、不改数据库结构、不改 Docker 编排。改动纯前端 + 现有 API 使用方式，需重新部署 web 容器。

## #17 [CLOSED] PR fix(deploy): 上传给派上的脚本规范化成 LF（#16）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/17

## 问题

见 issue #16：`powershell -File scripts/sync_orangepi.ps1` 在 Windows 部署机上第一步就失败
—— scp 上传的是工作区里的 `scripts/sync_orangepi.sh`，而本机 `core.autocrlf=true`、仓库没有
`.gitattributes`，所以它是 CRLF。派上的 bash 把行尾 CR 当成选项名的一部分：

```
/tmp/sync_orangepi.sh: line 2: set: pipefail: invalid option name
```

第 2 行就退出，数据、模型、compose 文件一个都没碰。只要部署机开着 autocrlf，每次部署都会这样。

## 改了什么

只改 `scripts/sync_orangepi.ps1`：上传前把脚本写成纯 LF 的临时副本（`finally` 里清掉）。
`.sh` 只由远端 bash 执行，没有理由带 CR；这样部署结果不再取决于部署机的换行设置。
`scripts/sync_orangepi.sh` 的内容与语义一字未动。

## 验证

- PowerShell 解析：`PSParser::Tokenize` → 0 个错误。
- 规范化产物：CR 计数 0、LF 计数 58（上传内容确实是正 LF）。
- 端到端：合并后从 main 重跑 `sync_orangepi.ps1`（main 仍是 1bce317，属同码重部署），
  确认能走到 `docker compose up -d --build` 与健康检查。

## 本次部署实际怎么走的

1bce3171795e 已经上线，是手工绕过的：bundle 与脚本照常 scp，在远端
`sed -i 's/\r$//' /tmp/sync_orangepi.sh` 之后再执行脚本；随后备份并重建 embeddings 库、
重启 web。健康检查与识别状态见 PR #15 的合并说明。

## 影响面与回滚

部署工具，不动运行时代码 / 数据 / 模型 / 凭据。回滚 = revert 本提交。

Closes #16

## #16 [CLOSED] ISSUE 部署脚本在 Windows 部署机上必然失败：scp 上传的 sync_orangepi.sh 带 CRLF

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/16
- Labels: bug

## 现象

`powershell -File scripts/sync_orangepi.ps1` 在 Windows 部署机上第一步就失败：

```
/tmp/sync_orangepi.sh: line 2: set: pipefail: invalid option name
Orange Pi deployment failed
```

## 根因

`scripts/sync_orangepi.sh` 在 Git 里是 LF，但部署机 `core.autocrlf=true` 且仓库没有
`.gitattributes`，所以工作区里它是 CRLF。`sync_orangepi.ps1` 直接 `scp` 工作区文件，
派上拿到的是 `set -euo pipefail\r` —— bash 把 `\r` 当成选项名的一部分，报「invalid option name」。
失败发生在脚本第 2 行，因此什么都还没做就退出了（数据、模型、compose 文件都没动）。

本次部署（main = 1bce3171795e）是手工绕过的：bundle 与脚本照常 scp，在远端
`sed -i 's/\r$//' /tmp/sync_orangepi.sh` 后再执行，才走完 `docker compose up -d --build`
与健康检查。**只要部署机开着 autocrlf，脚本就每次都会这样失败。**

## 期望

`sync_orangepi.ps1` 不依赖部署机的换行设置：上传前把上传给远端执行的脚本规范化成 LF
（`.sh` 只会被 bash 执行，没有理由带 `\r`）。

## 影响面

只改 `scripts/sync_orangepi.ps1`（部署工具），不动运行时代码、不动 `.sh` 的内容语义。
不引入凭据、不动 `data/`、`models/`、`.env`。

## #15 [CLOSED] PR perf(web): 嵌入模型换 MobileFaceNet 并拦住跨模型混用（#14）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/15

## 背景 / 问题

issue #10 清掉人脸识别里的「非推理等待」之后，开门链路上剩下最大的一笔开销就是嵌入模型本身：现役 `recognition.onnx` 是 InsightFace **iresnet50**（174MB，43.6M 参数，容器内实测输入 `1×3×112×112` / 输出 512 维），在派上（aarch64 3 核、纯 CPU、常驻负载 ~19）**每张脸 411ms(p50)**。动态 batch 实测是线性的（1/3/5 张 = 33/97/160ms），加线程也摊不掉——只能换模型。

顺带修一个换模型必然踩的坑：`embeddings.pkl` 只记 `method` / `image_size`，**不记原型是哪个 ONNX 算的**（`FaceRecognizer.__init__` 还会拿库里的值反向覆盖配置）。跨模型的余弦相似度实测只有 **0.077**（同人也一样），所以「换了模型没重建库」的表现是服务正常启动、日志一句不错、**谁都进不了门**（是 fail-closed 全拒，不是误开门——这点我专门测了）。

## 改了什么

1. **嵌入模型换成 InsightFace `w600k_mbf`（MobileFaceNet，13.6MB）**
   - 与现有管线逐字节兼容：manifest 写明 112×112、512 维、`(x-127.5)/127.5`，预处理一行没改
   - `PC_Test/web_config.yaml` 里 `face.recognition.model_path` 指过去；来源 URL + sha256 + 实测数据记在新增的 `docs/face-models.md`
2. **模型路径改由 web_config.yaml 决定**（`FaceEngine._recognition_model_path`，相对路径按 `PC_Test/` 解析）
   - `data/face/face_config.json` 里那句 `model_path` 不再参与——它是运行期写的，常年带着另一台机器的绝对路径
   - 回滚 = 只改 yaml 那一行，不动代码
3. **库内写 `model_fingerprint`（method + 文件大小 + 文件头 sha256 前 16 位），加载时校验**
   - 不匹配 → **停用认人但保留检测**（`mode` 退回 `yolov8`），日志 `[人脸] 库与模型不匹配，认人已停用`
   - 原因顶到三处：`/api/status` 的 `recognition.block_reason`、`/api/access/diagnostics` 的 `model_mismatch` / `recognition_block`、门禁体检页排最前的一条 `bad`（中英双语，指纹结构化传前端拼句子）
   - 混库期间 **拒绝录入**，避免建出一个库里混着两种向量的库
   - 没记指纹的老库照常工作（不能因为升级就把门停了），下次录入或重建时补写
4. **`scripts/enroll_faces.py`**：相对模型路径按 `PC_Test/` 定死（容器里 `-w /app` 与仓库根跑法一致），文档串里写明「换模型后必须重建库」

## 实测（Orange Pi，生产同一容器与同一批注册照）

单脸提特征 + A/B/C 各 8 张注册照的留一法（每张 vs 自己其余 7 张均值原型取最小；vs 另外两个身份原型的最大值）：

| 模型 | 大小 | p50 | p90 | 同人最低 | 异人最高 | 余量 | 阈值 0.5 命中 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| iresnet50（改前） | 174.4MB | 411ms | 833ms | 0.804 | 0.200 | 0.604 | 24/24 |
| **w600k_mbf（本 PR）** | 13.6MB | **93ms** | 173ms | 0.788 | 0.265 | 0.523 | 24/24 |

- 每张脸省 **~318ms**；单脸场景一轮从 ~686ms 降到 ~370ms 量级（配合 #10 的改动）
- 判别余量比 iresnet50 略窄（0.523 vs 0.604），但两侧离阈值都还有 0.23 以上——这是本次唯一的精度让步，明确写进 `docs/face-models.md`
- 跨模型混用风险量化：iresnet50 查询 × MobileFaceNet 原型 = 自己 0.077 / 别人 0.067，24 张全部低于阈值（证明守卫拦下的是「全拒」这种可诊断故障，不是安全洞）

真模型端到端验证（本机，非桩）：新库 + 新模型 → `mode=recognition`、`face_id=甲`、score 0.645；把 yaml 改回 iresnet50 → `blocked=True` + 两个指纹都列出来；模型文件删掉 → `block=人脸身份识别不可用：Recognition model not found...`。

## 涉及文件

`PC_Test/web/face/recognizer.py`、`PC_Test/web/face/engine.py`、`PC_Test/web/api/access.py`、`PC_Test/web/static/js/access.js`、`PC_Test/web/static/js/lang.js`、`PC_Test/web_config.yaml`、`PC_Test/scripts/enroll_faces.py`、`PC_Test/tests/test_face_model_guard.py`（新增）、`docs/face-models.md`（新增）、`docs/README.md`、`docs/configuration.md`

## 测试

`python -m unittest discover -s PC_Test/tests -v` → **Ran 93 tests, OK**（新增 21 项，全部用桩：不加载模型、不开摄像头、不碰串口）。

踩到并修掉的一个自身问题：新加的 `DiagnosticsEndpointTests` 最初在 `setUp` 里写了个假密码哈希且不还原，会把后面的 `test_login_and_csrf` 带崩——现在测完还原环境变量。

## 影响面与回滚

- 鉴权层与积木规则一字未动（`access_guard`、`access_open_door` 不变）；只是「认得出谁」这件事从此要求库与模型对齐
- 对已经部署的机器：**合并后必须重新 embedding**，否则门禁停用认人（会显示原因，不会静默）
- 回滚：yaml 那行改回 `models/face/recognition.onnx` + 恢复重建前备份的 `embeddings.pkl` + `docker compose restart web`，不需要回退代码

## 部署（合并后执行，涉及设备部署：是）

模型二进制不进 Git，我已按 sha256 核对放到派上 `~/smart-home/models/face/w600k_mbf.onnx`（`9cc6e4a7…9eb4f`，与官方 manifest 一致）。上线顺序：

```bash
# 1. 同步合并后的 main
powershell -File scripts/sync_orangepi.ps1
# 2. 备份旧库 → 用新模型重建 → 重启 web（顺序不能反：旧代码认的是 recognition.onnx）
docker exec smart-home-web-1 cp /app/data/face/embeddings.pkl /app/data/face/embeddings-r50.pkl.bak
docker exec -w /app smart-home-web-1 python scripts/enroll_faces.py --method arcface_onnx
docker compose restart web
# 3. 健康检查：docker ps -a、/api/ready、匿名 API 必须被拒、diagnostics 里 model_mismatch 为空
```

端到端开门复测需要有人站到门口，那时再叫上你；PIR 触发 → 判定的时延我会和 #10 的基线一起报。

## #14 [CLOSED] ISSUE perf(web): 换轻量嵌入模型砍掉每脸 ~371ms 的 ArcFace R50 推理（含 embeddings 库模型指纹校验）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/14

## 问题

issue #10 把人脸识别里的「非推理等待」清完之后，开门链路上剩下的最大一笔开销就是嵌入模型本身：

- 现役模型 `models/face/recognition.onnx` = ArcFace **iresnet50**，**174MB**，输入 `1×3×112×112` float32（RGB，`(x-127.5)/127.5`），输出 **512 维**（容器内实测）
- 派上（Orange Pi，aarch64，3 核，纯 CPU，onnxruntime 1.30）单脸提特征 **≈371ms/张**
- 同一颗 CPU 上常驻负载就有 ~20（见项目记忆），所以这笔钱没法靠加线程摊掉；#10 也验证过 ONNX 动态 batch 是线性的（1/3/5 张脸 33→97→160ms），压缩不了

insightface 官方模型族里有同预处理、同输入尺寸、参数量小两个数量级的轻量嵌入模型（MobileFaceNet / EfficientNet 级，几 MB 到十几 MB）。本 Issue 的目标是换过去，并解决换模型时一个会静默咬人的坑。

## 必须一并修的坑：换模型后旧 embeddings 库会被静默当成有效库

`data/face/embeddings.pkl` 只记 `version` / `method` / `model_path` / `image_size`，**不记这些原型是哪个 ONNX 算出来的**（`PC_Test/web/face/recognizer.py:269-275`）。更糟的是加载时 `FaceRecognizer` 会拿库里的 `method`、`image_size` 反向覆盖配置（`recognizer.py:49-50`），而引擎又把模型路径固定成代码常量 `RECOGNITION_MODEL_PATH`（`engine.py:174-186`）。

结果：把 `recognition.onnx` 换成另一个模型、库里仍是旧原型的 512 维向量时，服务照常启动、识别器照常加载（旧库和新查询都是 `method=arcface_onnx`），但**跨模型的余弦相似度接近噪声** —— 表现是「站在那儿谁都不开权限」，日志、门禁页、`/api/access/diagnostics` 都不会说出真正原因。这属于换模型必然踩的第一脚坑，先补防护再动模型。

## 测量方法（先测后改，不接受「感觉变快了」）

1. PC 侧（`py -3.13`，cwd=`PC_Test`）：候选 onnx 的输入/输出张量核对 + 112×112 crop 提特征延迟初筛
2. 派上容器内（与生产同一运行时）：拿 `data/face/authorized/{A,B,C}/` 各 8 张注册照做**留一法**——
   - 同人余量：每张照 vs 其余 7 张的均值原型，取最小值
   - 异人余量：每张照 vs 另外两个身份原型的最大相似度
   - 现役 R50 做同一套基线，候选必须在 `similarity_threshold=0.5` 下留出**不劣于基线**的正余量
3. 端到端复测：PIR 触发 → 判定，与 #10 的基线（稳态 686ms/轮、单脸 extract 371ms）对比
4. 模型二进制不进 Git（AGENTS.md 第 2 条）：走 `scp` 上派，仓库里只落来源 URL + sha256 + 重建步骤

## 计划改动

| 文件 | 改动 |
| --- | --- |
| `PC_Test/web/face/recognizer.py` | 建库时写入模型指纹；加载时校验，不匹配就明确拒绝而不是静默比对 |
| `PC_Test/web/face/engine.py` | 录入路径跟随同一指纹；不匹配时给出「需要重新录入」的可读原因 |
| `PC_Test/web/api/access.py` | `/api/access/diagnostics` 暴露库/模型不匹配状态 |
| `PC_Test/scripts/enroll_faces.py` | 离线全库重建（换模型后必用） |
| `PC_Test/web/config.py` + `web_config.yaml` | 默认识别模型与注释更新 |
| `PC_Test/tests/` | 指纹校验、库重建、模型切换的单测（桩，不碰模型与摄像头） |
| `docs/` | 模型来源、校验和、重新录入步骤 |

## 验收标准

- [ ] 候选模型在派上实测单脸 extract 延迟，并给出与 R50 的对比数字
- [ ] A/B/C 留一法同人/异人余量 ≥ 现役基线；给出具体数值表
- [ ] 用旧模型建的库在新模型下**不会静默运行**：状态接口 / 诊断页 / 日志三处都能指到「人脸库与当前模型不匹配，需重新录入」
- [ ] `python -m unittest discover -s PC_Test/tests -v` 全绿
- [ ] 派上完成重新录入（改前库文件落 `_backup-*` 目录），部署后健康检查通过，端到端开门时延复测有数字
- [ ] 不改变鉴权与规则层语义（`access_guard`、积木 `access_open_door` 不动）

## 风险与回滚

主要风险是识别精度退化（误识或拒识），因此**先量化余量再切换**，且生产切换必须备份旧 `embeddings.pkl`。回滚 = 把原 `recognition.onnx` 和备份库一起放回去并重启 web 容器（`docker compose restart web`），不需要改代码。

涉及设备部署：**是**（模型二进制 + 重新录入 + 端到端复测都要在派上做）。

## #13 [CLOSED] PR perf(web): 消除人脸识别的三处非推理等待（首帧预热 / PIR 即时触发 / 无效提特征）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/13

Closes #10

## 具体问题与触发条件

香橙派（4 核、常态 load ≈ 18）上一轮 `recognize_jpeg` 稳态 686ms，但其中有三笔钱不必付，外加最多 2 秒纯等待：

| 现象 | 触发条件 | 实测代价 |
|---|---|---|
| 模型加载后**第一次**推理特别贵 | 服务刚启动 / 容器重启后，第一个人站到门口 | 首帧检测 3782ms（稳态 251ms）、首次提特征 466ms |
| PIR 报「有人」后要等满轮询间隔 | `FaceWatcher._loop` 睡 `interval`，上升沿不叫醒 | 最多白等 2.0s |
| 太远的脸照样付一张嵌入 | `min_face_px` 在识别**之后**才判定 | 371ms/张 |
| 多人同框线性恶化 | `max_faces` 被读进 config 但从未生效 | 5 张 ≈ 1.9s |
| JPEG → base64 → 再解码 | 哨兵每轮 | 本地约 3ms + 整串 `,` 扫描 |

## 修改后的行为

1. **后台预热**：`FaceEngine.warmup()` 空跑一帧检测 + 一次提特征，`start_warmup()` 把它丢进守护线程，由 `start_watchers()` 触发。`/api/ready` 不等待（`start_warmup()` 实测 0ms 返回），预热与识别/录入共用 `_enroll_lock`，不插队。
2. **PIR 上升沿即时抓帧**：`on_snapshot` 认出 `motion` 由假变真就置位 `_wake`，主循环据此立刻起一轮；`MIN_WAKE_SPACING_S = 0.4` 为下限，抖动的 PIR 不会打成连拍。边沿来得太早时事件**先攒着**（用 `_stop.wait()` 睡觉而不是丢弃），到下限再起轮——写第一版时这里踩过坑：过早唤醒会被消费掉，反而白等一整轮。
3. **提特征前置门控**：哨兵把 `min_face_px` 传进引擎，`_embed_targets()` 按面积从大到小取「够近的、最多 `max_faces` 张」。**检出框仍全部返回**，前端画框、`too_far` 状态、`faces` 列表语义都不变。
4. `recognize_jpeg` 直接收 JPEG 字节（`_decode_frame` / `_recognize_blob`），`recognize_from_base64` 仍兼容 data URI；`_yolov8_recognize` 增加一行分阶段耗时的 DEBUG 日志。
5. 顺带修 `stop()`：以前只置 `_stop`，线程正睡在等待上，退出要等满一轮。

**识别结果不变**：10 组测试帧（7 档人脸尺寸 + 多人同框 + 空帧）改前后的 `face_id` / `bbox` / `confidence` / `score` 逐字节一致（对比脚本 `_tmp/compare_identity.py` 在两棵树各跑一遍后 diff）。

## 主要文件与设计选择

- `PC_Test/web/face/engine.py`：预热、JPEG 直解、`_embed_targets`、耗时 DEBUG 日志。
- `PC_Test/web/face_watcher.py`：`_wake` 事件与主循环调度、`min_face_px` 透传。
- `PC_Test/web/extensions.py`：`start_watchers()` 里挂后台预热。
- `PC_Test/tests/test_face_latency.py`：14 项新单测（桩件，不加载模型、不连摄像头）。

设计取舍：
- **没有**默认改检测分辨率。`imgsz 640→416` 实测在派上可再省约 30% 且本地召回扫描无损（50px 脸仍 5/5），但属于行为参数变更，按约定留作后续 Issue。
- **没有**换更轻的嵌入模型（换掉 174MB ArcFace 才能让 371ms/张 这一步降一个量级），代价是 `embeddings.pkl` 特征空间作废、需用注册照离线重建，另开 Issue。
- ONNX 批量推理实测无收益（输入 batch 轴是动态的，但 1→3 张耗时 33ms→97ms 线性），所以没走批处理这条路。
- 只给 `recognize_jpeg` 这条内部路径加锁，`/api/face/recognize` 的 HTTP 入口沿用原有不加锁行为，避免让看板抢哨兵的锁；这处历史竞态不在本 PR 范围内。

## 测试命令与结果

```
cd PC_Test
py -3.13 -m unittest discover -s tests -v     # Ran 86 tests ... OK（含新增 14 项）
py -3.13 -m compileall -q web/face/engine.py web/face_watcher.py web/extensions.py
```

未连接真实串口与执行器；`PC_Test/tests/test_hardening.py` 一并在绿色集合内。

本地 16 核 A/B（独立进程，避免同进程内第二次天然被预热污染）：

| 场景 | 改前 | 改后 |
|---|---|---|
| 首帧端到端 | 2188–2233ms | **174ms**（预热已付） |
| 稳态一轮 | 83–95ms | 80–95ms |
| 48px 远脸一轮 | 85ms | **40ms**（不再付嵌入） |
| 同框 4 张脸 | 199ms | 118ms（`max_faces=1` 时） |

派上的首帧与开门时延需合并部署后现场复测（见下）。

## 配置 / 数据库 / 硬件 / 部署影响

- 配置：无新增项，`face.watcher.min_face_px`、`face.max_faces` 从「被忽略」变成「真正生效」——若有人此前依赖 `max_faces` 大于实际人数，行为不变。
- 数据库：无变化。人脸库、`embeddings.pkl`、阈值均未动。
- 硬件/协议：不改串口协议，只消费既有的 A 板 `motion` 快照字段；不发执行器指令。
- Docker：不改编排。启动阶段会多约 4s 的后台 CPU 预热（`--start-period 90s` 内），换来第一个人不付首帧罚。
- 部署：合并后由一人执行 `powershell -File scripts/sync_orangepi.ps1`。

## 回滚方法

`git revert <本 PR 的 squash 提交>` 后重新部署即可。没有数据迁移、没有配置写入、没有镜像内文件残留，回滚不需要清库或重录人脸。


---

## 审核修正（2026-10-03，见评论与 `01eab0e`）

- 两轮下限改为 `max(0.4s, 引擎节流窗口)`：唤醒撞在 1.5s 节流里只会被判 `throttled` 白白消耗，
  现由 `FaceEngine.recognition_min_interval` 把窗口暴露给哨兵；抖动 PIR 的取帧频率同时被压住。
- `max_faces` 只认 `web_config.yaml`：`data/face/face_config.json` 是运行期写的、可能来自另一台机器，
  过去会整键覆盖 yaml（与 #15 修模型路径的立场对齐）。
- 测试计数更新：`py -3.13 -m unittest discover -s tests` → **Ran 89 tests, OK**（新增 3 项）。

## #12 [CLOSED] PR fix(web): show humidity stat labels and hide stats for door/light his…

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/12

…tory

历史数据页选择湿度时统计块改为最高/最低/平均湿度并显示 % 单位；门窗状态与灯光状态不再展示这四个统计块。

## #11 [CLOSED] PR feat(automation): 全屋有人联动、触摸开门及可疑行为抓拍

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/11

## 行为

Closes #8

修正旧预设中无人时开灯/风扇、触摸切模式和离家关窗的相反行为：
- 触摸开门，10秒后关门；门禁成功也由同一条规则完成开关序列，取消MCP重复控制。
- PIR有人时温度>26°C开风扇、≤25°C关；光照ADC<200开灯、≥300关，保留回差。
- 连续120秒无PIR活动关闭灯和风扇；雨水或烟雾独立于占用状态关窗，两者解除后45°。
- 密码按完整尝试计数，连续第三次及以后失败抓拍留档；正确密码清零。新增登录保护的/security记录页。
- 门口超声波独立使用doorway_distance_cm，100cm/30秒停留逻辑默认禁用，断流重置；尚未接硬件。

## 实现和影响

主要修改 automation/default_rules.py、engine.py、mcp_home_server.py，新增 keypad_code.py、security_monitor.py 和回归测试。内置预设升级v6，保留启停开关和自定义规则，开启自动风扇许可，删除冲突预设。事件驱动状态写入可续期持续计时，手动优先立即生效。传感器超过10秒无新快照不再用于联动；同值指令去重考虑手动后的设备状态，重复无动作不刷日志。

键盘新增password_result内部事件；现有A/B串口协议及固件不变。数据库结构和Docker编排不变。照片及JSON记录写入已忽略的PC_Test/data/security；抓拍失败也留事件，重启中断的抓拍标记失败。照片不依赖人脸识别模型。配置/阈值和回滚说明见docs/home-automation.md。与PR #7共用mcp_home_server.py，但本PR仅改键盘区域，其灯光区域不变。

## 验证

基于最新origin/main 9a5b1c8，在独立worktree虚拟环境、假硬件桥中运行（无真实串口/执行器）：
- PYTHONPATH=PC_Test python -m unittest discover -s PC_Test/tests -v：48 tests，全部通过，无跳过。
- python -m compileall -q PC_Test：通过。
- git diff --check：通过。

新增21项回归覆盖温光阈值、有人/离家、触摸顺序、雨烟组合、数据失效、无人计时断流、手动优先续期、迁移、密码聚合和清零、门口停留、拍照失败/成功、重启中断、照片鉴权。

## 审查与部署

等待未参与实现者独立审查，尚未合并或部署。只读SSH核验被publickey/password认证拒绝，因此香橙派当前提交和服务健康未核验。审查通过并合并后，应更新本地main并运行scripts/sync_orangepi.ps1，再核对三端提交、Docker健康、/api/ready及匿名API拒绝。

回滚：通过主分支PR恢复代码；同步恢复/重新配置automation_rules.json，因为旧代码不认识sensor_fresh条件。保留data/models/.env/.auth及认证文件。

## 审核修复与验证（2026-10-03）

审核复现并修复：触摸预设只检查2秒周期快照，短按在两帧间完成时 touch_on 离散事件不会触发开门。已改为消费固件现有 touch_on 事件，并覆盖短按、松开、事件重放和启动快照；开门/10秒延时/关门序列不变。另修正安全接口测试对其他测试模块认证环境的隐式依赖。完整隔离 unittest 49/49，compileall、git diff --check 通过，无真实串口或执行器。提交 f5e217c65777866002830dd00dcaef4537aa5366，已包含最新 main。由于审核者参与了本次修复，依照 docs/git-workflow.md 留待未参与实现者复审；本 PR 未合并或部署。

## #10 [CLOSED] ISSUE 人脸识别端到端延迟：首帧 3.8s 冷启动罚 + PIR 后最多空等 2s

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/10
- Labels: performance

## 问题

门口识别哨兵（`FaceWatcher`）在香橙派上单轮 `recognize_jpeg` 稳态约 686ms，但存在两处与推理无关的等待：

1. **首帧冷启动罚**：`FaceEngine._load_model()` 只构造模型对象，不做任何预热。模型加载后第一次 ultralytics 推理耗时 3782ms、第一次 ONNX 提特征 466ms（实测见下表）。服务刚启动后第一个人站在门口时，从 PIR 触发到鉴权要多等约 4 秒。
2. **PIR 之后空等轮询间隔**：`FaceWatcher._loop` 用 `self._stop.wait(self.interval)` 睡整段 `interval`（默认 2.0s），PIR 上升沿不会立刻唤醒它。人已经站到门口了，却还要等最多 2 秒才抓第一帧。

另外三处是白花的时间：

3. `min_face_px`（默认 60px，太远的脸不参与开门）目前是在 `FaceWatcher.inspect_once` 里、也就是**完整识别之后**才判定。够不到的脸照样跑一遍 371ms 的 ArcFace 嵌入。`_yolov8_recognize` 遍历了**所有**检测结果并逐张提特征。
4. `max_faces` 配置（默认 5）被读进 config 但从未生效，多人同框时最坏 5×371ms ≈ 1.9s 一轮，且随人数线性恶化。
5. `recognize_jpeg` 把 JPEG 先 `base64.b64encode` 成字符串、再在 `recognize_from_base64` 里 `b64decode` 回来，纯往返；顺带对整串做 `"," in raw` 扫描。

### 复现方法

在派上 web 容器内跑只读探针（新建 `FaceEngine` 进程 → 第一次 `detector.detect` vs 稳态对比），或看服务启动后第一个 PIR 周期与后续周期的耗时差。

### 实测数据（香橙派 4 核，load ≈ 18；模型为 `yolov8n-face.pt` + `recognition.onnx`，库内 3 个身份）

| 环节 | 耗时 |
|---|---|
| `FaceEngine()` 构造（含模型加载） | 609ms |
| **加载后首次 detect** | **3782ms** |
| 加载后首次 extract | 466ms |
| 稳态 detect @imgsz 640 | 251–269ms（空帧同价，与检出人数无关） |
| 稳态 extract（每张脸） | 371ms；batch 无加速（3× 输入 ≈ 3× 耗时） |
| 稳态端到端 `recognize_jpeg` | 686ms（样本 858/676/686/928/684） |
| 本地 16 核对照端到端 | 83ms |

## 计划修改的模块与文件

- `PC_Test/web/face/engine.py`：新增模型预热入口；识别路径直接吃 JPEG 字节，去掉 base64 往返；`_yolov8_recognize` 支持在提特征前按边长过滤、并真正执行 `max_faces` 上限（按面积取前 N）；分阶段耗时 DEBUG 日志。
- `PC_Test/web/face_watcher.py`：PIR 上升沿立即触发一轮识别（不睡满 `interval`，并保留最小间隔防止连打）；把 `min_face_px` 作为「提特征前置门控」传给引擎，`too_far` 状态语义不变。
- `PC_Test/web/app.py` 或引擎构造处：启动后在后台线程预热，避免拖慢 `/api/ready`。
- `PC_Test/tests/`：预热、上升沿即时触发、尺寸前置门控、`max_faces` 上限的单元测试。

**不改**：识别精度相关的任何阈值与模型；`embeddings.pkl` 结构；串口协议；数据库结构；Docker 编排。检测分辨率（imgsz 640→416 实测可省约 30% 且召回无损）与更轻的嵌入模型（371ms/张 的主成本）作为后续独立 Issue，本 Issue 不做。

## 验收条件

1. 服务启动后**第一轮**真实识别的耗时与稳态轮同一量级（派上实测首帧从 ~4.5s 降到 <1s）。
2. PIR 从 `motion=false` 变 `true` 后，哨兵在远小于 `interval` 的时间内开始抓帧（不等满 2 秒），且不会因此提高采样频率上限（保留最小间隔）。
3. 检出但边长小于 `min_face_px` 的脸不再触发嵌入提特征，`inspect_once` 仍返回 `too_far`。
4. 多人同框时提特征次数不超过 `max_faces`（按人脸面积从大到小取），`faces` 列表仍包含全部检出框。
5. `python -m unittest discover -s PC_Test/tests -v` 全绿；无真实串口/执行器。
6. 识别结果与现在一致：同一批测试帧的 `face_id`/`score` 不变（不引入精度回退）。

## 是否涉及串口协议 / 数据库结构 / Docker 编排 / 设备部署

- 串口协议：否（只**消费**已有的 A 板 `motion` 快照事件，不改协议字段）。
- 数据库结构：否。
- Docker 编排：否。
- 设备部署：是，合并后由一人执行 `scripts/sync_orangepi.ps1` 同步到香橙派；端到端开门需人在现场验证。

## #9 [CLOSED] ISSUE 修复 PR #7 灯光调光溢出、零亮度语义和页面控件冲突

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/9

审核 PR #7 发现 Uno 上 255*255 使用 16 位 int 溢出；value=0 被错误替换为默认亮度；色温标签与温度卡片共用 tempValue ID；调节亮度会丢失当前灯光模式。计划修改 module-b-output/src/drivers/Light.cpp、core/CommandParser.{cpp,h}、core/CommandDispatcher.cpp、Protocol.cpp，PC_Test/web/static/js/main.js、templates/dashboard.html、web/hardware.py 和相关测试。验收：隔离 Python 全套测试、JavaScript 回归、Uno 编译通过，补充零亮度/整数运算验证。涉及灯光协议语义，不修改数据库或 Docker。修复上传原 PR 后等待独立复审。

## #8 [CLOSED] ISSUE 全屋自动化：触摸开门、有人温光联动及门口可疑行为记录

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/8

实现触摸开门后10秒关门；有人且温度>26°C开风扇、低光开灯，无人关闭灯和风扇；雨水或烟雾关窗，正常45度；连续3次密码错误拍照留档；独立门口距离停留检测默认禁用。主要文件：PC_Test/web/automation/{default_rules,engine}.py、PC_Test/mcp_home_server.py、新增安全记录模块及测试、web/api/camera.py、web/extensions.py、docs。保留现有串口协议，新增密码结果事件；不改变数据库结构和Docker编排。验收：隔离无硬件单元测试通过；独立审查后合并和部署健康检查。

## #7 [CLOSED] PR feat(light): 支持夜灯分区点亮与色温/RGB 调光

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/7

面板的「全亮/半亮/夜灯/关闭」此前只有白光亮度一个维度，四个按钮的区别只是
0~255 的 level，亮的方式没有差异。按前端灯光卡片的设定补齐三种亮法：

- night：只点亮居中 LIGHT_NIGHT_COUNT(默认 2) 颗灯珠，其余保持熄灭，当小夜灯用
- temp：色温 2700~6500K，固件用 PROGMEM 查表 + 线性插值出 RGB，避免引入 log()/浮点
- rgb：新增可选 value 作为整体亮度缩放，缺省 255 与旧行为一致

协议为增量扩展（新增 action 与 temp 字段），旧帧 white/off/预设色不变；
文本命令补 LIGHT:NIGHT 与 LIGHT:TEMP:<K>[:<level>]。
Web 侧 /api/light 新增 mode/temp/rgb，优先级 rgb > temp > mode，status=off 时一律走关灯；DB 仍只记 status+brightness，不新增列、不做迁移。

自检帧新增 light.lit（本次点亮灯珠数，0=整条），用于区分「整条暗」与「只亮几颗」。
自检的 rawPinTest 会按夜灯区间恢复上屏，避免把「只亮两颗」变成整条常亮。

测试：python -m unittest discover -s PC_Test/tests -v（28 passed） 固件：pio run -e uno SUCCESS（RAM 77.8% / Flash 75.6%），Uno 资源占用无明显变化。

## 2026-10-03 审核修复与最终验证

审核修复已上传：灯光缩放使用宽整数防止 Uno int16 溢出；区分缺省 value 与显式0；零亮度状态记为关闭；修复重复 tempValue ID；亮度调节保留本页已选夜灯/色温/RGB模式。最新提交已包含 main 9a5b1c8。隔离 unittest 42/42，Node UI 回归2/2，compileall、Uno PlatformIO编译和 AVR 静态边界断言全部通过。RAM 1594/2048，Flash 24418/32256。未烧录固件或执行设备命令。关联 #9。

本次审核者参与了这些修复，按 docs/git-workflow.md 的独立审查要求，保留 PR 待未参与实现者复审。

## #6 [CLOSED] PR Show voice dialog state and missing audio feedback in UI

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/6

The voice page now shows the complete IDLE, ACK, COMMAND, THINKING, and FOLLOWUP flow with a description of when the microphone is active. It displays runtime audio/context status, speech detection, cancellation, timeout, model errors, replies, and tool results. Systems without an ALSA output device skip TTS synthesis and clearly report that replies are UI-only.

Production diagnosis: the previous deployment continuously recognized ambient noise as A/N/M and issued incorrect model tool calls. PR #2 is now deployed and its state gate eliminated those idle recognitions. A safe text prompt returned '测试成功' without calling hardware.

Validation:
- Voice image: 11/11
- Web image: 16/16
- MCP stdio round trip included
- JavaScript syntax check passed

Closes #3

## #5 [CLOSED] PR fix(web): 温湿度入库防丢 + 前端周期刷新

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/5

**具体问题与触发条件**
传感器单字段毛刺即整帧不入库且日志不可见；原始遥测无保留策略（约 8.6 万行/天）迟早写满磁盘导致入库停摆；看板图表/历史页只在打开时取数一次——19 点看 17 点曲线。

**修改后行为**
- ingest_sensor 列级容错，坏字段 NULL、整帧保留、warning 汇总；
- 硬件桥统计 ok/fail 计数与最近错误，/api/status 可见；
- 原始数据保留 7 天，更旧的聚合进 sensor_hourly（小时均值+样本数）后删除；>7 天窗口合并归档小时与最近原始数据；历史页新增「最近30天(小时聚合)」；
- 看板图表 60s 周期刷新、复用 Chart 实例、回前台立即补取；温湿度卡片显示最后更新时间，停更红色告警并带失败帧数。

**主要文件与设计选择**
见 Issue。清理任务不新增线程：启动时 + 每小时随 ingest_sensor 顺带触发；聚合幂等（INSERT OR REPLACE 先聚合后删除）。固件采样/上报频率按约定不动。

**测试命令与结果**
- `py -3.13 -m unittest discover -s tests`（PC_Test/）：22 项全部通过（rebase 最新 main 后复跑）；
- `py -3.13 -m compileall web`；`node --check` main.js/history.js；
- 浏览器实测在临时副本（--no-serial、假登录）完成：图表增量刷新出现新点、Chart 实例保持 1 个、聚合窗口正常渲染、控制台无报错。未连接真实串口（无法执行，按规范说明）。

**配置/数据库/硬件/部署影响**
- 新增表 sensor_hourly，随 init_database 自动建（user_version 不变，破坏性为零）；
- 首次部署启动即触发一次清理：派上 7 天前的原始行会被聚合后删除——聚合值可长期保留趋势；
- 无串口协议、无 Docker 变更；回滚：还原本 PR 即恢复旧行为，sensor_hourly 表留着无害。

**回滚方法**
revert 合并提交；旧代码不认识 sensor_hourly，不受影响；原始行删除不可逆（如需保留更长原始数据，回滚前先备份 data/smart_home.db）。

## 2026-10-03 审核修复与最终验证

审核修复已上传：超过7天的查询现合并归档小时与最近原始数据；空数据/全NULL时清除旧统计；修正删除测试边界并增加长窗口回归。最新提交已包含 main 9a5b1c8。隔离环境完整 unittest 35/35，通过 compileall、Node 历史UI回归及 JS 语法检查。无真实串口。关联 #4。

本次审核者参与了这些修复，按 docs/git-workflow.md 的独立审查要求，保留 PR 待未参与实现者复审。

## #4 [CLOSED] ISSUE 温湿度入库链路丢数据 + 前端显示滞留（图表停在页面打开时刻）

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/4

验收核对（基于 main d093dfc，含 PR #5 合并 33336ce，已部署至香橙派）：

1. 入库防丢：database.py 列级容错，坏字段只写 NULL 整帧照入库；/api/status 暴露 hardware_bridge.ingest 失败计数；7 天保留 + sensor_hourly 小时聚合与 >7 天窗口读聚合已实现。
2. 前端刷新：看板图表 60s 自动刷新且复用实例（main.js），卡片显示更新时间/过期告警；历史页 60s 自动重载并对 NULL 安全（history.js）。
3. 审核补修 945c48d（长窗口查询遗漏最近 7 天原始数据、NULL/空历史旧统计）已随 PR #5 合入。

测试：PC_Test/tests/test_sensor_pipeline.py、test_history_ui.js 覆盖上述行为。关闭本 issue。

## #3 [CLOSED] ISSUE Fix voice UI state and missing response feedback

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/3

The voice page does not map the new ACK state and the wake API reports COMMAND before listening starts. Production diagnostics also found no ALSA playback device, so users need explicit visual recognition, timeout, model, and tool feedback. Add complete UI state coverage and visible failure feedback.

## #2 [CLOSED] PR 优化语音轮次监听并增加 MCP 上下文

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/2

修复唤醒提示期间提前监听、固定超时截断发言、TTS 回声进入追问和被取消轮次污染历史的问题。新增 MCP stdio 上下文服务，只持久化已完成轮次与真实工具结果；工具调用增加 schema 校验、单轮去重和次数上限。

验证：
- 语音镜像：10/10（包含 MCP stdio 写入/读取联调）
- Web 镜像：15/15 加固回归
- Python AST 语法检查通过
- docker compose config --quiet 通过
- 香橙派现有服务保持 healthy，/api/ready 为 ok

Closes #1

## #1 [CLOSED] ISSUE 优化语音轮次监听与 MCP 上下文

- URL: https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/1

目标：明确唤醒、提示、指令、思考、播报和追问各阶段的监听边界，避免 TTS 回声和固定超时截断语音；使用 MCP stdio 服务持久保存已确认轮次与真实工具结果，并在本地校验、去重模型工具调用。

验收：语音镜像测试、MCP 往返测试、Web 加固回归和 Compose 配置均通过。
