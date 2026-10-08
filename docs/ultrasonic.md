# B 板 HC-SR04 超声波测距

## 接线与版本

Arduino Uno B 板：HC-SR04 **Trig → D6、Echo → D5、VCC → 5V、GND → GND**。
D5/D6 原数码管功能保持关闭，启用 TM1637 会编译报错，防止引脚冲突。
需要 B 板固件 V2.10 或以上，以及包含 `get_distance` 的 MCP 服务。
仅更新香橙派服务不会更新 Uno 固件，必须另行编译并烧录 B 板。

## 后续程序调用

通过已有且受认证保护的工具网关调用，串口仍由 Web 的 MCP 子进程独占。
`GET /api/hardware/tools` 会列出 `get_distance`，无需另行注册。

```python
import json
import os
import requests

response = requests.post(
    os.environ["SMART_HOME_URL"].rstrip("/") + "/api/hardware/tool",
    headers={"Authorization": "Bearer " + os.environ["SMART_HOME_SERVICE_TOKEN"]},
    json={"name": "get_distance", "arguments": {}},
    timeout=10,
)
response.raise_for_status()
measurement = json.loads(response.json()["result"])
if measurement["valid"]:
    print(measurement["distance_cm"], "cm")
else:
    print("无有效距离：", measurement["status"])
```

也可直接通过 MCP 调用无参数工具 `get_distance`。不要为测距另开串口。
Web 硬件桥每次测量完成后间隔 500 ms 再读取，通过原 MCP 锁与其他命令串行共享串口。
独立距离通道不依赖 A 板是否在线，也不会刷新 A 板数据的新鲜度。
测距结果缓存 3 秒；无效回波、离线和过期值均不能当成 0 cm。

## 实时显示与自定义拍照

在人脸识别（门禁管理）页面查看实时距离；页面只读取服务端缓存。
关闭页面后服务端测距和自动化仍然运行。

进入「自动化」，点击「新建门口测距拍照规则」，默认提供：

- 门口超声波距离 **小于 50 cm**，连续保持 **2 秒**；
- 执行「门口拍照并存储」。

可修改比较符、距离（2–400 cm）、持续时间（1–86400 秒，0 表示即时触发），
以及其他条件和动作。点击保存后生效，规则重启后保留。
模板不会自动覆盖现有规则，也不会在未保存时启用。
连续停留只触发一次，离开后重新靠近可再次触发；无效读数或超过 3 秒未更新会重新计时。
修改距离规则后重新计时；冷却时间仍服从该规则的设置。

照片和事件 JSON 保存在 `PC_Test/data/security/`，通过「查看照片记录」访问。
记录包含规则名、距离、阈值、持续时间及时间戳，摄像头不可用会显示拍照失败。
当前摄像头服务供实时预览持续运行，联动触发的是获取快照并存储，不切换摄像头供电。
照片不依赖人脸识别成功，也不会自动开门。无需更改固件或数据库结构。
运行目录的数据由现有部署流程保留，不提交到 Git。

## 串口协议

请求（115200 baud，末尾换行）：

```json
{"cmd":"ultrasonic","action":"read","id":42}
```

响应示例（距离单位为厘米，`uptime_ms` 是 B 板开机时间）：

```json
{"module":"output","type":"distance","id":42,"sensor":"HC-SR04","valid":true,"status":"ok","distance_cm":25.0,"echo_us":1450,"uptime_ms":12345}
```

每次调用触发新测量，无旧值缓存。`status` 为 `timeout` 或 `out_of_range` 时，
`valid=false`、`distance_cm=null`，不能当作 0 cm 或无人靠近。
这类响应仍是 HTTP 200（调用成功，但测量无效）；串口断开、通信超时、旧固件
`unknown_command` 属于调用失败，由现有网关返回 HTTP 502。
距离帧必须匹配本次请求 id，迟到帧不会成为下次调用的结果。

驱动按[HC-SR04 数据手册](https://cdn.sparkfun.com/datasheets/Sensors/Proximity/HCSR04.pdf)
使用 10 µs 触发脉冲、65 ms 最小测量周期、25 ms 回波超时及 2–400 cm 有效范围。
等待期间保持中断开启；单次请求测量阶段最多约 90 ms，低于现有 4 秒看门狗窗口（V2.11）。
返回小数位只表示数值格式，实际精度取决于目标形状、角度和环境。

## 验证与部署

1. 在独立测试环境运行 `python -m unittest discover -s PC_Test/tests -v`。
2. 在 `module-b-output` 运行 `python -m platformio run -e uno`。
3. PR 完成独立审查并合并后，依仓库流程同步香橙派服务，再烧录同一提交的 B 板固件。
4. 烧录需释放 B 板串口，会复位 B 板并恢复执行器默认状态；不要与 Web 串口读写并行。
5. 放置已知距离的平整目标进行实测，核对返回距离；移走目标确认无有效回波时不报告零距离。

回滚需同时恢复此前服务提交和 B 板固件；不能只回退上位机就视为固件已回退。
