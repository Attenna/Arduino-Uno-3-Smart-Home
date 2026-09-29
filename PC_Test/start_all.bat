@echo off
REM start_all.bat — 一键启动「语音助手 + 人脸识别Web + 摄像头视频流」
REM 双击即可；参数可直接追加，例如： start_all.bat --port-a COM7 --port-b COM6 --cam 0
title SmartHome All-In-One
cd /d %~dp0
py -3.13 start_all.py %*
pause
