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

qwen 镜像需要在 aarch64 上编译 llama.cpp，约 20~40 分钟，属正常现象。
想更快可改用云端 LLM：叠加 `docker-compose.dashscope.yml`（免本地 3B，构建快、省内存）。

**Q9：香橙派跑不动本地 3B 模型？**

在 `.env` 设置 `DASHSCOPE_API_KEY`，然后：

```bash
docker compose -f docker-compose.yml -f docker-compose.dashscope.yml up -d --build
```

**Q10：模型文件怎么准备？**

- 在有网环境运行 `download_qwen.py`、`download_sherpa_models.py` 直接下载；
- 或从 Windows 用 `scp` 把 `models/` 传到香橙派。
模型不进镜像、不进 git，约 2.6GB，详见 [PC_Test/README.md](../PC_Test/README.md)。

**Q11：没有摄像头 / 没有麦克风能用吗？**

- 无摄像头：`docker compose up -d --scale camera=0`；
- 无麦克风：给 voice 设 `SMART_HOME_DISABLE_MIC=1`，硬件工具与文本指令仍正常，
  适合只做人脸开门、不做语音对话的部署。

---

## 三、硬件与串口

**Q12：串口报"拒绝访问" / PermissionError？**

串口同一时刻只能被一个进程占用。关闭其他占用程序（其他 Python 进程、Arduino 串口监视器等）。

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

```bash
# 1. 放 5~10 张正脸照
#    data/face/authorized/<姓名>/
# 2. 生成嵌入库
python scripts/enroll_faces.py
# 3. 重启 web；并在门禁页用相同 face_id 添加授权人员
```

**Q19：检测得到人脸但身份总认错？**

- 确认注册照片角度/光线多样、数量足够；
- 调整 `recognition.similarity_threshold`（默认 0.5，调低更宽松、调高更严格）；
- 重新运行 `enroll_faces.py` 生成嵌入。

**Q20：没有模型可以先演示界面吗？**

把 `face.simulation_mode` 改为 `true`，会返回模拟人脸（FACE001/002/003）。

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

**Q24：有多个麦克风，如何选择？**

```bash
python voice_assistant.py --list-mic
```

把索引填入 `mic.device_index` 或 `.env` 的 `MIC_INDEX`。

**Q25：不说唤醒词，能直接控制吗？**

可以。终端直接打字回车；或调用 HTTP：`POST /say {"text":"把灯打开"}`、
`GET /say?text=...`。Web 面板也提供等价按钮。

**Q26：模型回答了但设备没动？**

查看模型是否真正产生工具调用。小模型偶发只回文本或生成半截 JSON，重说一次即可；
3B 模型工具调用成功率显著更高，建议作为默认。

---

## 六、自动化

**Q27：规则配置了却不触发？**

- 确认规则已启用、冷却时间已过；
- 用 `/api/automation/preview` 查看当前真实数据下触发/条件是否成立；
- 传感器触发可设「持续 N 秒」，注意该条件是否过严。

**Q28：误删了默认规则怎么办？**

在自动化页点「恢复内置规则」，或调用 `POST /api/automation/rules/restore`。

**Q29：全屋模式（自动/手动/离家）是怎么工作的？**

- 自动：按规则自动调节；
- 手动：用户手动操作任一设备后切入，保持当前状态不被自动覆盖；
- 离家：执行离家联动（关门窗/灯/风扇）。
按触摸键或页面切回「自动」即恢复自动调节。

**Q30：OLED 轮播不更新 / 想关掉？**

通过 `PUT /api/automation/oled` 修改 `enabled`、`interval`、`pages`。

---

> 未覆盖的问题：先查 [文档中心](README.md) 按角色定位相关文档，
> 再结合 `docker compose logs` 与串口原始数据分析。
