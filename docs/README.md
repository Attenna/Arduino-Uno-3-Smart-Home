# 文档中心（Documentation Hub）

本目录汇集整套智能家居系统的文档。按**用途**分为三层：

| 层级 | 文档 | 用途 |
|------|------|------|
| **概念 / 架构** | [architecture.md](architecture.md) | 分层架构、数据流向、模块边界 |
| | [serial-protocol.md](serial-protocol.md) | 串口 JSON 协议规范（A 上报 / B 命令） |
| | [development-guide.md](development-guide.md) | 开发规范（依赖方向、命名、禁止跨层） |
| | [hardware-debug-notes.md](hardware-debug-notes.md) | 硬件踩坑复盘、排障速查 |
| **HA 实战** | [ha-automation-examples.md](ha-automation-examples.md) | Home Assistant 自动化实战 |
| **部署 / 运维** | 见下表 ↓ | 每部分的 Linux 部署、接线、调试、二次开发 |

---

## 按部件部署指南（DEPLOYMENT.md）

每个部件目录内各有一份 `DEPLOYMENT.md`，统一覆盖四块内容：
**① Linux 部署  ② 设备安装连接  ③ 调试方法  ④ 二次开发定义**

| 部件 | 功能 | 部署指南 |
|------|------|---------|
| Module A 传感器板 | 采集 10 类传感器，上报 data/event | [../module-a-sensor/DEPLOYMENT.md](../module-a-sensor/DEPLOYMENT.md) |
| Module B 执行器板 | 接收命令驱动门/窗/风扇/灯/蜂鸣/显示/红外 | [../module-b-output/DEPLOYMENT.md](../module-b-output/DEPLOYMENT.md) |
| Gateway 网关 | 串口 ↔ MQTT 协议转换（Orange Pi 上跑） | [../gateway/DEPLOYMENT.md](../gateway/DEPLOYMENT.md) |
| Home Assistant + Docker | 业务决策层 + Mosquitto Broker | [../homeassistant/DEPLOYMENT.md](../homeassistant/DEPLOYMENT.md) |
| PC_Test 工具集 | 串口调试、自动化 DSL、摄像头流 | [../PC_Test/DEPLOYMENT.md](../PC_Test/DEPLOYMENT.md) |

---

## 快速定位：不同角色看哪些文档

| 角色 | 先看 | 再看 |
|------|------|------|
| 我要把整套系统部署到 Orange Pi | 根 [README](../README.md) → [../homeassistant/DEPLOYMENT.md](../homeassistant/DEPLOYMENT.md) → [../gateway/DEPLOYMENT.md](../gateway/DEPLOYMENT.md) | 两块板的 DEPLOYMENT（烧录接线） |
| 我要在电脑上调试硬件 | [../PC_Test/DEPLOYMENT.md](../PC_Test/DEPLOYMENT.md) | [serial-protocol.md](serial-protocol.md) |
| 我要给 Arduino 加传感器/执行器 | 对应板 DEPLOYMENT 第 4 节 | [development-guide.md](development-guide.md) |
| 我要写新联动规则 | [ha-automation-examples.md](ha-automation-examples.md) | [serial-protocol.md](serial-protocol.md) |
| 硬件有问题 | [hardware-debug-notes.md](hardware-debug-notes.md) | 对应板 DEPLOYMENT 第 3 节 |

> 原则：各 `DEPLOYMENT.md` 自包含可直接照做，避免文档间跳转过深。
