# 本次交付验证（2026-10-07）

- Issue：[#42](https://github.com/Attenna/Arduino-Uno-3-Smart-Home/issues/42)。
- 工作分支：`feat/42-asrpro-voice`，已从最新主分支同步。
- 用户明确要求审核通过后才部署。本次只上传待审查代码并运行隔离测试；
  未部署 ASRPRO 服务、未烧录、未执行开灯/开门等真实硬件动作。

## 已完成

1. 使用天问 Block AI 的 `riscv-nuclei-elf-g++`，配合 SDK 的实际头文件、
   `-march=rv32imafc -mabi=ilp32f -fshort-enums -fpermissive -fno-exceptions -Os`，
   对 `smart_home.cpp` 完成源文件语法检查和 `-c` 目标文件编译，均成功。
   SDK 自带 `asr_event.h` 有枚举及回调类型宽松转换警告，沿用其原有编译模式。
2. `python -m compileall PC_Test/asrpro_bridge.py PC_Test/tests/test_asrpro_bridge.py` 成功。
3. 在独立 Linux 测试容器中运行
   `python -m unittest discover -s PC_Test/tests -v`，设置 `PYTHONPATH=/src/PC_Test`，
   共 **170 项全部通过**，包括新增 7 项 ASRPRO 测试。
   容器使用已有测试镜像、`--network none --read-only --tmpfs /tmp`，
   限制为 0.5 CPU / 768MB 内存，仅挂载临时源码副本，没有设备和运行数据挂载。
   不接入真实串口、摄像头或生产 API，不属于部署。
4. 先前 Windows 测试中 6 项错误均来自 `test_face_model_guard` 的图片建库测试；中文身份目录
   下的 OpenCV 文件读写未产生可读取的测试图像，同环境在主工作目录运行该文件
   25 项测试亦出现相同 6 项错误。上述 Linux 全量回归已通过，未修改无关人脸代码或测试。
5. `git diff --check` 通过。仅新增 C++、桥接器、测试、systemd 单元及说明；
   模型、凭据、测试产物、环境和运行数据未纳入交付文件。

## 尚需完成

- 用户及独立审查人员审核 PR；批准前不合并部署。
- 合并后按仓库规定拉取 main、使用 `scripts/sync_orangepi.ps1` 同步精确提交。
- 在天问软件中生成本项目语音模型、整包编译下载，再进行实机验证。
- 香橙派选择专用 ASRPRO 适配器路径、配置现有服务令牌并安装桥接服务。

因此本交付是已通过 C++ 目标文件编译及 Linux 全量回归的源代码，不是已验证上线的固件。
