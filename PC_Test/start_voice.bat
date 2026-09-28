@echo off
REM start_voice.bat — 一键启动语音助手（双击即可，全自愈：依赖/模型/服务自动补齐）
title SmartHome Voice Assistant
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_voice.ps1"
pause
