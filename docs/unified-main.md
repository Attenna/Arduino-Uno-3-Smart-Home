# 统一主程序

本次把 PR #134（NEC 发射位序及回声）、#137（光敏回照防闪烁）、#139（OLED 禁屏）
合入同一整合分支，以最新 main 的硬件桥轮询优化为基线，保留已经验证的 A1 风扇、
D3 接收初始化、0–9 遥控方案和精确26°C温控。最终经审阅合并到唯一发布分支 main。

## 一个版本、三个运行组件

| 组件 | 程序入口 | 统一版行为 |
|---|---|---|
| 香橙派 | `PC_Test/docker-compose.yml` | Web 独占串口，统一执行积木规则；Camera/Voice 按原配置运行 |
| A 板 | `module-a-sensor/src/main.cpp` | V2.5-UNIFIED；环境采集、D3遥控接收、A0灯带、A1风扇 |
| B 板 | `module-b-output/src/main.cpp` | V2.15-OLED-OFF；门窗/蜂鸣器/红外发射，OLED默认禁用 |

两块独立 Arduino 和香橙派各自运行对应程序，业务逻辑在 Web 自动化引擎统一处理。
发布使用同一 Git 提交，避免单独试验分支的代码在后续部署时丢失。
原 HA/MQTT 部署形态保留供其他场景使用；当前机器使用上述智能终端栈。

## 保留的控制方式

- 1灯切换，2风扇持续手动开/关，3门，4窗，5恢复26°C自动温控。
- 6短提示音，7/8/9白光25%/60%/100%，0关灯；无遥控语音唤醒。
- 灯光手动优先30秒后恢复光敏；回照补偿避免灯带照亮自身传感器而反复切换。
- 26°C以上开扇，不高于26°C关扇；按2后温控让位，直到按5恢复。
- D3接收沿用显式初始化，过滤未知/溢出/重复及超过32位的遥控帧。
- NEC发射按字节反转位序，接收端得到原始命令；自动化回声抑制使用同一映射。
- B板OLED保持复位，不初始化显示驱动、不刷新；不改变现有接线。

## 发布与启动

先按 [Git工作流](git-workflow.md) 完成独立分支测试、人工审阅及合并。
本地拉取同一 main 提交，再从仓库根目录同步香橙派：

```powershell
git pull --ff-only origin main
powershell -File scripts/sync_orangepi.ps1
```

脚本使用 Git bundle 同步源码、备份持久状态、构建容器并检查就绪。
运行时位于 `/home/HwHiAiUser/smart-home`；data、models、env及认证文件必须保留。
若当前机器的 GitHub 访问受限，按脚本的 bundle 参数或封装传输同一提交。

A/B固件分别用 `pio run -d module-a-sensor` 和 `pio run -d module-b-output` 编译。
烧录前停止独占串口的网关，备份真实Flash；烧录后回读验证并恢复网关。
同步脚本只部署上位机，不自动烧录Arduino。通过回读校验确认已有固件一致时无需重烧。
组件提交分别记录在 `.deployed-a-firmware-commit`、`.deployed-b-firmware-commit`，
服务版本记录在 `.deployed-git-commit`。

## 整合验证与回滚

合并前运行隔离PC_Test全量测试、A/B PlatformIO构建、OLED启用备选构建、
Docker配置及构建检查，再备份当前运行时和main头做分支真机验证。
重点检查光敏遮挡/放开、遥控手动风扇、5键恢复自动、OLED保持关闭及NEC环回。

回滚时恢复测试前的运行时代码、规则/全局状态及必要的A/B Flash，保留持久数据。
来源PR的提交通过整合分支的合并历史保留，最终普通merge可同时保留来源归属，
避免旧PR被反复整合。合并前不关闭来源PR。
