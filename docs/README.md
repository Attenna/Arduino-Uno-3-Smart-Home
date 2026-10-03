# 文档中心（Documentation Hub）

多人同时开发请先阅读 [Git 多人协作规范](git-workflow.md)。

本目录汇集整套智能家居系统的文档。按**用途**分为四层：

| 层级 | 文档 | 用途 |
|------|------|------|
| **概念 / 架构** | [architecture.md](architecture.md) | 两种部署形态、分层架构、数据流向、模块边界 |
| | [serial-protocol.md](serial-protocol.md) | 串口 JSON 协议规范（A 上报 / B 命令，含固件裁剪说明） |
| | [development-guide.md](development-guide.md) | 开发规范（依赖方向、命名、禁止跨层、PC_Test/Web 前端硬约定） |
| | [git-workflow.md](git-workflow.md) | 多人并行开发、分支、worktree、提交、评审和部署规范 |
| **接口 / 配置** | [api.md](api.md) | 全部编程接口（Web REST / 语音 HTTP / MCP 工具 / LLM / 摄像头） |
| | [extension-guide.md](extension-guide.md) | 二次开发接口指南（对外表面、四条扩展缝、加积木的清单与落地顺序） |
| | [configuration.md](configuration.md) | 配置项参考（yaml / .env / 环境变量 / Config.h） |
| **实战 / 排障** | [ha-automation-examples.md](ha-automation-examples.md) | Home Assistant 自动化实战 |
| | [hardware-debug-notes.md](hardware-debug-notes.md) | 硬件踩坑复盘、排障速查 |
| | [faq.md](faq.md) | 常见问题解答（38 问） |
| **部署 / 运维** | 见下表 ↓ | 每部分的 Linux 部署、接线、调试、二次开发 |

---

## 按部件部署指南（DEPLOYMENT.md）

每个部件目录内各有一份 `DEPLOYMENT.md`，统一覆盖四块内容：
**① Linux 部署  ② 设备安装连接  ③ 调试方法  ④ 二次开发定义**

| 部件 | 功能 | 部署指南 |
|------|------|---------|
| Module A 传感器板 | 采集 9 类传感器（含矩阵键盘），上报 data/event | [../module-a-sensor/DEPLOYMENT.md](../module-a-sensor/DEPLOYMENT.md) |
| Module B 执行器板 | 接收命令驱动门/窗/风扇/灯/蜂鸣/OLED/红外 | [../module-b-output/DEPLOYMENT.md](../module-b-output/DEPLOYMENT.md) |
| Gateway 网关 | 串口 ↔ MQTT 协议转换（形态 A，Orange Pi 上跑） | [../gateway/DEPLOYMENT.md](../gateway/DEPLOYMENT.md) |
| Home Assistant + Docker | 业务决策层 + Mosquitto Broker（形态 A） | [../homeassistant/DEPLOYMENT.md](../homeassistant/DEPLOYMENT.md) |
| PC_Test 工具集 | 面板 + 硬件网关（独占串口）/人脸/语音/摄像头 Docker 栈（形态 B） | [../PC_Test/DEPLOYMENT.md](../PC_Test/DEPLOYMENT.md) |

---

## 快速定位：不同角色看哪些文档

| 角色 | 先看 | 再看 |
|------|------|------|
| 我要部署形态 A（HA + 网关） | 根 [README](../README.md) → [architecture.md](architecture.md) → [../homeassistant/DEPLOYMENT.md](../homeassistant/DEPLOYMENT.md) → [../gateway/DEPLOYMENT.md](../gateway/DEPLOYMENT.md) | 两块板的 DEPLOYMENT（烧录接线） |
| 我要部署形态 B（香橙派 Docker 智能终端） | [architecture.md](architecture.md) 第 3 节 → [../PC_Test/DEPLOYMENT.md](../PC_Test/DEPLOYMENT.md) | [configuration.md](configuration.md) |
| 我要在电脑上调试硬件 | [../PC_Test/DEPLOYMENT.md](../PC_Test/DEPLOYMENT.md) | [serial-protocol.md](serial-protocol.md) |
| 我要对接系统 / 二次开发接口 | [api.md](api.md) → [extension-guide.md](extension-guide.md) | [configuration.md](configuration.md) |
| 我要给 Arduino 加传感器/执行器 | 对应板 DEPLOYMENT 第 4 节 | [development-guide.md](development-guide.md) |
| 我要改 web 后端 / 页面脚本 | [development-guide.md](development-guide.md) 第 9 节 → [extension-guide.md](extension-guide.md) §3.4 | 跑 `pi-staging/` 回归 |
| 我要写新联动规则 | [ha-automation-examples.md](ha-automation-examples.md) | [serial-protocol.md](serial-protocol.md) |
| 我遇到问题 / 报错 | [faq.md](faq.md) | [hardware-debug-notes.md](hardware-debug-notes.md) |

> 原则：各 `DEPLOYMENT.md` 自包含可直接照做，避免文档间跳转过深。
