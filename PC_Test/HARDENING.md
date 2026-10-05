# 智能家居修复记录（2026-10-03）

## 修复内容

- 面板使用独立账号登录，服务间使用限权 Token；阻止跨站写入，记录操作审计。
- 外部 `/api/face/notify` 默认关闭；门禁自测只查询名单，不广播开门事件。
- 硬件命令增加 ID 和有效期；超时未发送的命令取消，已发送命令返回结果未知，等待回读确认。
- 摄像头每帧编码一次，视频连接和快照共享缓存；处理频率限制为 12 FPS。Docker 摄像头关闭重复的人脸检测，由 Web 识别服务负责。
- 规则更新或服务停止时取消待执行延时动作；已发给硬件的动作无法撤回。
- 空调读状态、合并修改、发送和记账使用共享锁；相同参数也允许重发，接口注明这是上次发送状态。
- 分开 `/api/live` 和 `/api/ready`，就绪检查包含数据库、串口和数据新鲜度。
- Web/摄像头使用单进程 Waitress；容器使用 UID 1000、只读根文件系统、最小设备组、禁用额外 capabilities、日志轮转。
- 摄像头和语音端口仅绑定主机回环地址，通过登录后的 Web 页面访问。
- 依赖锁定为现有运行版本，新加入 Waitress 3.0.2；提供私有数据备份脚本。

## 访问

面板地址：http://10.29.127.49:5000/login

账号和新生成的面板密码保存在本地同目录 `web-login-credentials.txt`；开发板原件为 `/home/HwHiAiUser/smart-home/.auth-admin-credentials.txt`。SSH 账号密码未修改。

当前使用局域网 HTTP；HTTPS 尚未配置。若部署 HTTPS，设置 `SMART_HOME_HTTPS=1`，并正确配置可信反向代理。

## 测试

15 项 unittest 在不联网、不透传设备的容器中通过；以非 root 和只读文件系统重复验证通过。

测试文件：`tests/test_hardening.py`。不要在挂载真实运行数据库的容器里执行测试。

## 开发板备份

- 源码：`/home/HwHiAiUser/smart-home-code-backup-20261003-153248.tar.gz`
- 切换前数据：`/home/HwHiAiUser/smart-home-backups/20261003-154534/`
- 旧镜像：`smarthome-web:pre-hardening-20261003`、`smarthome-camera:pre-hardening-20261003`、`smarthome-voice:pre-hardening-20261003`

后续数据备份可在项目目录运行 `python scripts/backup_state.py`；备份保留在开发板，不会上传到外部服务。

## 验证边界

本次没有发送开门、关门或空调控制测试指令，也没有物理拔插设备。服务重启会重新连接串口；Arduino 可能随串口重新连接复位。
