# Home Assistant 配置（业务决策层）

> **职责：做决定。** 本目录是 Home Assistant 的配置，所有传感器联动/自动化都在这里实现。
>
> 🚀 部署/接线/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

## 目录文件

| 文件 | 作用 |
|------|------|
| `configuration.yaml` | HA 主配置：MQTT 集成 + 实体定义（sensor/binary_sensor/switch/fan） |
| `automations.yaml` | 自动化规则（温度开风扇/下雨关窗/烟雾报警/刷卡开门） |
| `scripts.yaml` | 可复用脚本（开门/关窗/风扇调速/OLED 显示等硬件命令封装） |
| `scenes.yaml` | 场景占位说明（本系统推荐用脚本代替 scene） |

## 部署要点

- 通过 `../docker/compose.yaml` 以 Docker 运行，本目录挂载为容器 `/config`。
- 依赖同一台机的 Mosquitto（`localhost:1883`）。
- 改完 yaml 需重启容器或 reload。

详见 [DEPLOYMENT.md](DEPLOYMENT.md) 与 [../docs/ha-automation-examples.md](../docs/ha-automation-examples.md)。
