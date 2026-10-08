# 常见问题解答（FAQ）

本页汇总部署与使用中最常见的问题。更细节的排障见
[hardware-debug-notes.md](hardware-debug-notes.md)。

---

## 一、概念与架构

**Q1：系统有两种部署形态，我该选哪种？**

- 想以 Home Assistant 生态为中心、长期运行 → **形态 A**（gateway + MQTT + HA）。
- 想在香橙派上一体化交付面板、人脸、语音、摄像头 → **形态 B**（PC_Test Docker 栈）。

两种形态下 Arduino 双板的定位完全一致，详见 [architecture.md](architecture.md)。

**Q2：为什么规定 A 板、B 板都"不做决定"？**

把业务逻辑集中到决策层，可以让固件保持简单、可独立替换；联动规则随时改而无需重烧固件。
这是最高优先级约束，详见 [development-guide.md](development-guide.md)。

**Q3：`homeassistant/` 和 `ha_config/` 有什么区别？**

- `homeassistant/` 是仓库维护的**精简参考配置**，Docker 编排默认挂载它；
- `ha_config/` 是实际运行环境的**配置快照**（含 `.storage/`、数据库、日志等运行产物），
  用于还原实际部署状态。日常使用以 `homeassistant/` 为准。

**Q4：`PC_Test/` 是生产代码吗？**

它最初是 PC 端调试工具集，现在同时承载形态 B 的智能终端栈（Web / 语音 / 人脸 / 摄像头），
既可在开发机上调试硬件，也可作为设备端正式部署。

---

## 二、安装与部署

**Q5：如何安装 Docker？**

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && 重新登录
```

**Q6：Linux 下访问串口报 Permission denied？**

```bash
sudo usermod -a -G dialout $USER && 重新登录
```

**Q7：Arduino 拔插后设备名会变（ttyUSB0↔1），怎么办？**

使用稳定路径，在 `.env` 中填 `/dev/serial/by-id/<完整ID>`：

```bash
ls -l /dev/serial/by-id/
```

**Q8：首次 `docker compose build` 很慢？**

默认编排**不构建** qwen 镜像——本地 LLM 在 `profiles: ["local-llm"]` 后面，默认走云端（硅基流动）。
只有叠加 `docker-compose.local-llm.yml` 时才需要编译 llama.cpp，aarch64 上约 20~40 分钟，属正常现象。

**Q9：香橙派跑不动本地 3B 模型？**

不用跑：默认引擎就是云端（硅基流动 `Qwen/Qwen3.5-4B`，OpenAI 兼容）。在 `.env` 设置 `LLM_API_KEY` 后直接：

```bash
docker compose up -d --build
```

需要完全离线（无外网 / 不想用云端 Key）时，才叠加本地 LLM 覆盖文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up -d --build
```

**Q10：模型文件怎么准备？**

- 在有网环境运行 `download_qwen.py`、`download_sherpa_models.py` 直接下载
  （Sherpa 三件套必装；Qwen 权重只有走本地兜底、起了 `qwen` 容器时才需要）；
- 或从 Windows 用 `scp` 把 `models/` 传到香橙派。
模型不进镜像、不进 git，约 2.6GB，详见 [PC_Test/README.md](../PC_Test/README.md)。

**Q11：没有摄像头 / 没有麦克风能用吗？**

- 无摄像头：可以照常不起（`docker compose up -d --scale camera=0`），也可以留着容器不管——
  它现在支持热插拔，没设备时持续重试并发「NO CAMERA」占位帧，插上就自己出图；
- 无麦克风：给 voice 设 `SMART_HOME_DISABLE_MIC=1`，硬件工具与文本指令仍正常，
  适合只做人脸开门、不做语音对话的部署。

---

## 三、硬件与串口

**Q12：串口报"拒绝访问" / PermissionError？**

串口同一时刻只能被一个进程占用。形态 B 里 A/B 口由 **web 服务拉起的 MCP 子进程独占**
（语音助手完全不碰串口），所以只要 web 在跑，别的 Python 进程、`test_serial.py`、
Arduino 串口监视器就都打不开同一组 COM 口。Linux 下报 Permission denied 则按 Q6 加 `dialout` 组。

**Q13：板子反复重启（监视器刷多条 `ready`）？**

供电不足触发欠压复位。舵机、灯带、风扇改用**独立 5V/2A 电源**，GND 与 Uno 共地；
并把 `LIGHT_BOOT_ON` 设为 `0`。详见 [hardware-debug-notes.md](hardware-debug-notes.md)。

**Q14：舵机不动？**

SG90 峰值电流大，不能只靠 Uno 5V；接独立 5V 并共地。仍不动检查信号线引脚与 `Config.h`。

**Q15：风扇为什么不能调速？**

风扇接在 D8/D7，均为非 PWM 引脚，只能开关（0=停，>0=全速）。
如需调速请改用 PWM 引脚（3/5/6/9/10/11）。

**Q16：命令报 parse_error？**

固件已支持全角自动转半角。仍报错请检查：JSON 是否单行、`cmd`/`action` 是否正确、
字段是否完整。数码管 `display` 命令返回 error 是因为 TM1637 已裁剪，属预期。

**Q17：OLED 连续下发多条文本会错位？**

引擎已内置逐行 30ms 节流 + 仅发变化行。仍错位可减少动作数量或加入 `delay` 块。

---

## 四、人脸识别

**Q18：如何新增一个可识别的人？**

日常在网页上做，不用重启：门禁页 `/access` →「＋ 添加人员」只填姓名 → 该行点
「录入人脸」，页面从摄像头实时画面截几帧上传，后端检脸、存注册照、重算原型并热加载。
房卡则点「录入房卡」，45 秒内把卡贴到 A 板 RC522 上即可绑到人。

只有换模型、想把历史照片全部重算时才走离线整库重建：

```bash
# 1. 放 5~10 张正脸照到 data/face/authorized/<姓名>/（目录名 = face_id = 清洗后的姓名）
# 2. 生成嵌入库
python scripts/enroll_faces.py
# 3. 重启 web
```

**Q18b：录入了人脸/房卡，门还是不开？**

分两段看，门禁页顶部那条状态栏就是第一段的答案：

1. **有没有人去做识别** —— 门口识别哨兵（`web/face_watcher.py`）在不在跑、摄像头取不
   取到帧、人脸库有没有身份、PIR 门控开没开。状态栏会直接说「门口摄像头没人经过」
   「摄像头取不到画面」「人脸库是空的，先录入人脸」，旁边还有本次运行的
   通过/拒绝/陌生人计数。参数见 `face.watcher.*`（configuration.md §2.5）。
2. **鉴权有没有放行、放行后有没有规则** —— 通行日志新增的「原因」列说明白名单这一侧：
   `凭证未登记` / `人员已停用` / `人脸库有此身份，名单里没有对应人员` /
   `多个人员共用该凭证`。都通过了才轮到积木：到 /automation 确认「门禁通过 → 开门」
   （预设 `access_open_door`）还在且启用，硬件桥在线。同理「延时关门」是
   `access_auto_close`，「被拒响蜂鸣」是 `access_denied_buzzer`（默认停用）。

`GET /api/access/diagnostics` 把三方（名单 / 人脸库 / 哨兵）一次列全，页面上的体检条
就是它渲染的：孤儿身份、没有注册照的生效人员、共用人脸ID、演示残留别名、刚被去抖
合并掉的重复读数。

**Q18c：同一张卡/同一张脸连开了两次门，或者一次都没开？**

一次读数在 51ms 内被上报两次是 RC522 的正常抖动，过去会开两次门。现在同一
`(方式, 凭证)` 在 `face.watcher.repeat_window`（默认 8 秒）内只算一次**开门动作**、
只广播一次（`access_guard.merge_repeat`），被合并的次数在 `recent_repeats` 里能看到。
反过来，连点页面上的「自测鉴权」想看两次日志是有效的：自测口显式绕过去抖。放行后
同一张脸默认 60 秒内不再重复开门（`face.watcher.cooldown`），被拒的身份不受这个冷却
限制。

注意去抖**只挡开门动作**，不挡历史：每一轮识别都会在门禁页的事件表里各自成行（#75），
所以同一人站 30 秒会看到多行而不是一行，太远/节流/无脸/未唤醒这些「没跑完识别」的
轮次也会留一条灰色「已记录」记录，说明这一轮为什么没有结果。

**Q18d：门口没人，页面却显示「某某 验证通过」？**

那是历史遗留的假数据，不是刚刚发生的判定。`POST /api/face/notify` 是开放通道，
早前的联调脚本往里塞过 `FACE001 / 管理员 / 95%` 这类伪造结果，而门禁页过去无条件把
「库里最后一条事件」渲染成实时结果，于是页面能连着几天显示一次并不存在的放行。
现在两道一起收口：后端在 `/api/face/events/latest` 里回 `age_s`，页面超过 90 秒就不
再当实时判定（退回等待态，注明「最后一条记录是 X 前」）；库里那批伪造事件已清空，
联调脚本 `pi-staging/pi_face_door_check.sh` 跑完也会自己删掉留下的行。
判断当前真实状态看哨兵状态条：`通过/拒绝/陌生人` 计数是本次进程启动以来的，
重启就归零，不会掺历史数据。

**Q19：检测得到人脸但身份总认错？**

- 确认注册照片角度/光线多样、数量足够；
- 调整 `recognition.similarity_threshold`（默认 0.5，调低更宽松、调高更严格）；
- 重新运行 `enroll_faces.py` 生成嵌入。

**Q20：没有模型可以先演示界面吗？**

把 `face.simulation_mode` 改为 `true`，会返回模拟人脸（FACE001/002/003）。注意它们是
写死的假 id、不是任何人的注册身份，所以门禁只会记「拒绝」；想看开门效果请在
/automation 页手动执行规则。

**Q21：模型加载失败怎么办？**

未安装 `ultralytics` / `onnxruntime` 时会自动回退模拟模式，`/api/face/status` 会标明当前模式。
安装：`pip install ultralytics onnxruntime`。改配置不生效时删除
`data/face/face_config.json` 后重启（该文件优先级高于 yaml）。

---

## 五、语音助手

**Q22：唤醒词不灵敏，或经常误唤醒？**

调整 `kws.keywords_score`（调大更易唤醒）与 `kws.keywords_threshold`（调小更灵敏），
两者都会同时增加误唤醒，需平衡。唤醒词为「Hey Bota」。

**Q23：TTS 没有声音？**

检查 TTS 模型目录、系统默认输出设备与音量；容器内确认 `/dev/snd` 已透传。
注意区分「引擎坏了」与「机器没喇叭」：香橙派 `/dev/snd` 只有采集设备（`pcmC0D0c`、无 DAC），
合成的 44.1k 音频已生成，只是 `sd.play` 报 `Error querying device -1`；用 Q28 的环回实测
能直接看出合成是好的。

**Q24：有多个麦克风，如何选择？**

```bash
python voice_assistant.py --list-mic
```

把索引填入 `mic.device_index` 或 `.env` 的 `MIC_INDEX`。

**Q25：不说唤醒词，能直接控制吗？**

可以。终端直接打字回车；或调用 HTTP：`POST /say {"text":"把灯打开"}`、
`GET /say?text=...`。Web 面板也提供等价按钮。

**Q26：语音回应要等十几秒，首字特别慢？**

默认模型 `Qwen/Qwen3.5-4B` 是思考型模型，会先把「思考过程」（`reasoning_content`）
流完才吐正文，实测首字 20~60s。代码里已对硅基流动默认带上顶层
`enable_thinking: false`，实测首字降到 ~1s，工具调用不变。想改回思考模式或加别的
请求参数，用 `llm.extra_body` 覆盖即可（注意硅基流动不认 vLLM 那套
`chat_template_kwargs` 写法）。若云端接了连接却一个字节都不回，客户端按 `llm.timeout_s`
（默认 30s）报「LLM 超时」并回到待唤醒，不会把那一轮永远挂在 THINKING。用 `--test-llm`
可以直接看耗时：

```bash
py -3.13 voice_assistant.py --test-llm "现在屋里有人吗"
```

**Q27：喊唤醒词完全没反应（不是灵敏度问题，一次都不响）？**

先分清两种情况：「不灵敏」是阈值/音素问题（见 Q22），「一次都不响」通常是命中后崩了。
sherpa-onnx 1.13 的 `KeywordSpotter` **只有 `reset_stream`，没有 `reset`**；照 ASR 那套写
`kws.reset(stream)` 会在第一次命中唤醒词时抛 `AttributeError`，而音频回调把异常吞成一行
`[音频] 回调异常: …`，看起来就像「喊破嘴也不唤醒」。`sherpa_listener.py` 已改用
`reset_stream`；`pi-staging/test_voice_audio_loopback.py` 里有一条打桩断言专门钉住这一点
（不用真人对着麦克风念）。

**Q28：没有麦克风/喇叭，怎么确认 ASR 与 TTS 真的在工作？**

`--self-check` 只证明引擎**能加载**，不代表模型真的在出声/认字。跑环回实测：VITS 合成一句
中文 → 重采样 16k → 逐帧喂 KWS/ASR → 断言端点切出的整句与原文一致，全程不需要音频硬件：

```bash
py -3.13 pi-staging/test_voice_audio_loopback.py
```

实测口径（改动语音前端后照这几条对一下）：

* TTS **不逐位可复现**（onnxruntime 多线程 CPU 推理），同一句连渲三次 md5 全不同，个别渲染
  起始音素会糊；ASR 对同一份 PCM 字节则完全确定。所以测试按「4 次渲染取最好一次 + 多数次」
  判定，而不是要求每次都精确。
* 合成速度别要求比实时快：桌面 PC RTF≈0.5，**4 核香橙派 RTF≈2.1**（合成 2.76s 出 1.29s 音频），
  且 `tts.num_threads` 从 2 调到 4/6 反而更慢（RTF 2.96），配置里的 2 已是该板最优。
* 流式 ASR 解码跟得上实时：PC RT≈0.11，派上 RT≈0.5（>1 才会漏字）。
* 尾静音不能用数字 0：完美静音会让流式模型幻听出多余字且不触发端点，要带 -50dBFS 底噪。
* 派上 `[TTS] 播放失败: Error querying device -1` 是**没有 DAC**（`/dev/snd` 只有 `pcmC0D0c`
  采集设备），发生在合成成功之后的 `sd.play` 阶段，与引擎无关。

**Q29：模型回答了但设备没动？**

查看模型是否真正产生工具调用。小模型偶发只回文本或生成半截 JSON，重说一次即可；
默认引擎已是云端（硅基流动 `Qwen/Qwen3.5-4B`，备选百炼 `qwen-plus`），工具调用成功率与速度都显著优于本地 3B，
本地推理只作为离线兜底（`llm.mode: local`）。工具调用最终经 web 的
`POST /api/hardware/tool` 下发，`/api/automation/logs`、历史记录里都能看到来源标注。

---

## 六、自动化

**Q30：规则配置了却不触发？**

- 确认规则已启用、冷却时间已过；
- 用 `/api/automation/preview` 查看当前真实数据下触发/条件是否成立；
- 传感器触发可设「持续 N 秒」，注意该条件是否过严。

**Q31：误删了默认规则怎么办？**

在自动化页点「恢复内置规则」，或调用 `POST /api/automation/rules/restore`。

**Q32：全屋模式（自动/手动/离家）是怎么工作的？**

已经没有「全屋模式状态机」了——屋子处于什么模式，现在就是一个全局状态变量
`g:全屋模式`（enum：auto/manual/away），由积木自己读写：

- 设备类预设的规则都带条件 `g:全屋模式 == 自动`，所以「切离家」就是把这一个变量改掉；
- 触摸键 / 页面 / 语音的切换动作，各自对应一条把 `g:全屋模式` 置成某个值的规则；
- 想加「晚上 11 点自动离家」，新建一条定时规则写这个变量即可，不需要改代码。

全局状态在自动化页与规则**并列**，每个变量是一条「📌 状态」条目：点工具栏
「📌 ＋ 新建状态」用一块顶层「状态定义」积木（名字 + 类型 + 当前值）建它，条目卡片只
显示当前值，值本身由规则里的「设置全局状态」积木维护；读它则用条件里的「📌 状态」积木。

**Q33：手动操作后为什么一会儿不被自动规则覆盖（手动优先）？**

面板/语音操作设备时，Web 会广播一个 `manual_control` 事件（不带任何设备专属策略）。
内置的 `manual_mark_灯` 一类规则收到它，把 `g:手动优先_灯` 先置假、延时 3 秒再置真，
随后 `manual_clear_灯` 在该变量持续为真满 30 秒后把它复位。这段时间里，灯的自动规则
因为带着 `g:手动优先_灯 == 否` 的条件而让位。整套逻辑都是普通规则，可在页面上改时长、
删掉或换成别的设备。

**Q34：风扇为什么默认不自动开？**

风扇安全线：`temp_hot` 等「开风扇」的预设额外要求 `g:允许自动开风扇 == 是`，
该变量默认为「否」，所以默认只有手动才会转风扇。点开列表页那条「📌 允许自动开风扇」条目，
把定义积木的「当前值」改成「是」再保存，即放开。关风扇的规则**不带**这个条件，任何模式下都能自动关。

两点要知道：① 删掉这个变量不是放开而是更保守——引用它的条件从此永远不成立，
自动开风扇的规则全部失效；② 自己新写的开风扇规则不会自动带这条线，需要放开自动化
控制风扇时，请自己在规则里加上它。

**Q35：OLED 轮播不更新 / 想关掉？**

通过 `PUT /api/automation/oled` 修改 `enabled`、`interval`、`pages`。
第二页的 Home Mode / Presence / Fan Auto 三个值直接读全局状态
（`g:全屋模式`、`g:有人在家`、`g:允许自动开风扇`），B 板字库没有汉字所以显示英文。

---

> 未覆盖的问题：先查 [文档中心](README.md) 按角色定位相关文档，
> 再结合 `docker compose logs` 与串口原始数据分析。
