@echo off
REM deploy_voice.bat — 语音交互模式一键部署（双击运行）
REM 等价于：powershell -ExecutionPolicy Bypass -File deploy_voice.ps1
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy_voice.ps1"
pause
