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
此功能不写数据库、不自动轮询、不触发执行器；自动化积木传感器列表暂未增加距离字段。
后续程序可按需轮询，建议间隔至少 100 ms，避免占满共享串口。

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
等待期间保持中断开启；单次请求测量阶段最多约 90 ms，低于现有 2 秒看门狗窗口。
返回小数位只表示数值格式，实际精度取决于目标形状、角度和环境。

## 验证与部署

1. 在独立测试环境运行 `python -m unittest discover -s PC_Test/tests -v`。
2. 在 `module-b-output` 运行 `python -m platformio run -e uno`。
3. PR 完成独立审查并合并后，依仓库流程同步香橙派服务，再烧录同一提交的 B 板固件。
4. 烧录需释放 B 板串口，会复位 B 板并恢复执行器默认状态；不要与 Web 串口读写并行。
5. 放置已知距离的平整目标进行实测，核对返回距离；移走目标确认无有效回波时不报告零距离。

回滚需同时恢复此前服务提交和 B 板固件；不能只回退上位机就视为固件已回退。
