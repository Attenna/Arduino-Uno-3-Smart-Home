# 物体检测本机联调

功能分支基于已部署整合版本 cfff479。GitHub 网络不可用，尚未刷新远程 main。

模型放在 PC_Test/models/objects/best.onnx，或用 SMART_HOME_OBJECT_MODEL 指定绝对路径。权重和运行数据不提交 Git。
本次权重 SHA256 为 30b85399e72f985c51c1169b651178d3c460c3e5c058187cdc5d680337481656。
元数据为 YOLO11n，类别仅 drones，固定输入 1×3×512×512，输出 1×5×5376。没有灭火器类别。
运行依赖为 onnxruntime、numpy、opencv-python，沿用现有 Web 环境。

/objects 页面支持单次摄像头检测、每3秒连续检测、图片上传与事件查询。
摄像头地址沿用 SMART_HOME_CAMERA_URL 或 camera.stream_url，从同一服务 /snapshot 读取，不直接打开摄像头。
接口为 GET /api/objects/status、GET /api/objects/result、POST /api/objects/detect、GET /api/objects/events。
POST 接口支持 multipart image，省略图片则读取共享摄像头。evidence=true 保存命中图片。
阈值 0.4，按类别 NMS 阈值 0.45，返回原图 xyxy 像素框、类别、置信度、UTC 时间及模型指纹。
命中事件最多每30秒一条，记录在现有 smart_home.db 的 object_events 表中，查询最近100条。
图片保存到 data/objects，默认关闭取证，无自动清理。连续检测由打开的网页发起，关闭网页即停止。

已用本机摄像头真实快照完成 ONNX 推理，当前画面无目标。尚缺无人机正样本和带标注数据，不能据此确认准确率。
自动化测试使用模拟命中结果验证入库、冷却与服务重新创建后的读取，不代表实物识别准确性。
后续完成正样本验收后，再备份香橙派并进行分支真机测试、评审合并、部署指定提交。

## 三类别 640 模型本机调试

2026-11-16 接入 yolov8s_3class_640.onnx，输入 1×3×640×640，输出 1×7×8400。
类别为 drone（无人机）、fire extinguisher（灭火器）、light bulb（灯泡）。
SHA256 为 b7070f98f5ddda717efe248da61242c2a9772368f295f7e1c2c59eb949318eef。
通过 SMART_HOME_OBJECT_MODEL 指定权重，无需改动检测接口，页面中统一显示中文名称。
本机启动脚本为 /Users/wangtianran/Documents/YOLO_face_dection/.venv-smart-home/local_object_640_preview.py。
测试地址 http://127.0.0.1:5004/objects，摄像头继续使用 8082 共享采集服务。
已经完成真实摄像头快照推理，无目标画面返回空检测结果。正样本准确率需另行验证。
