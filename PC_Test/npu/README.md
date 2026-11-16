# Ascend 310B4 物体推理服务

使用香橙派主机的 CANN 7.0、Python 3.10 和 pyACL 运行独立服务，Web 容器通过私有 Docker 网桥调用，避免 Python ABI 不一致。

先用 ATC 将对应 ONNX 转为静态 OM，必须保持 float32 输入输出和 1×3×640×640 输入。

```bash
. /usr/local/Ascend/ascend-toolkit/set_env.sh
atc --model=yolov8s_3class_640.onnx --framework=5 --output=yolov8s_3class_640_310B4 --soc_version=Ascend310B4 --input_format=NCHW --input_shape="images:1,3,640,640"
```

CANN 7.0 的转换环境使用 NumPy 1.24 和独立虚拟环境。不要替换主机全局 NumPy。
服务环境需要 SMART_HOME_NPU_MODEL（OM绝对路径）、SMART_HOME_NPU_TOKEN（至少32字符）、SMART_HOME_NPU_BIND（私有Docker网桥地址，默认127.0.0.1）。
Web 设置 SMART_HOME_NPU_URL、同一 SMART_HOME_NPU_TOKEN。ONNX 权重仍用于模型元数据和尺寸检查，预处理、NMS与框坐标转换沿用原实现。
GET /health 与 POST /infer 均要求 Bearer 认证，端口8093，输入和输出均为连续 float32 字节。
接口只负责模型前向推理，硬件联动继续由Web控制。模型、凭据及测试数据不提交Git。
切回CPU时移除Web的 SMART_HOME_NPU_URL 后重建Web服务。

## 已验证的板卡测试

2026-11-16，Ascend310B4/CANN7.0，将三类别640模型转换为OM。输入1×3×640×640，输出1×7×8400，均为float32。
ONNX SHA256 为 b7070f98f5ddda717efe248da61242c2a9772368f295f7e1c2c59eb949318eef。
OM SHA256 为 f6e8eba6cc0aed0c12f94874d89023a37dbe30c7ff5d4ab07123186529dee209。
6次直接NPU执行（含输出拷贝）23.88–24.15毫秒。与同一已有测试图的CPU输出相比，类别分数最大绝对误差0.0000694，框坐标平均绝对误差0.130像素。单图数值一致性不能替代带标注数据集的准确率验收。
板卡电流读取告警80E3A203仍存在，实际ACL推理成功；告警未进行驱动/固件升级处理。

部署时将.env凭据存为运行目录的.auth.npu.env（权限600），包含 SMART_HOME_NPU_TOKEN、SMART_HOME_NPU_MODEL、SMART_HOME_NPU_BIND。
安装本目录的 smart-home-npu.service 后启用系统服务，将 docker-compose.npu.yml 加入现有Compose文件列表，重建Web。
服务绑定Docker私有网桥地址，Web使用host.docker.internal访问。新增模型权重、OM和凭据均不进入Git。

## 人脸适配（板上验收待完成）

代码沿用当前整合分支，增加两个可选后端。

- SMART_HOME_FACE_DETECTOR_NPU_URL 指向人脸检测服务（建议私有端口8094），静态输入1×3×640×640，五点姿态输出1×20×8400。
- SMART_HOME_FACE_EMBEDDING_NPU_URL 指向MobileFaceNet服务（建议私有端口8095），输入1×3×112×112，输出1×512。
- 使用同一个SMART_HOME_NPU_TOKEN认证。服务通过SMART_HOME_NPU_PORT指定端口，由smart-home-npu@.service模板读取.auth.npu.face-detector.env或.auth.npu.face-embedding.env。
- 启用前验证原YOLOFaceDetector与新解码的人脸框和五点坐标，并对现有注册样本比较CPU/NPU归一化特征、相似度、身份与授权判定。阈值继续取现有配置。

原检测权重SHA256为d545bf1add5aa736a4febac4f4f9245a6d596cd0fe70d5d57989fe0cb9e626ca。
本机导出的ONNX为opset12、静态640输入。8张已有本机人脸样本的PyTorch/ONNX框与五点解码最大坐标差0.233像素。
板上已启动w600k_mbf的ATC转换，随后SSH握手超时，转换结果与NPU特征兼容性尚待确认。当前运行版本仍采用CPU人脸后端，不能把代码适配和本机解码验证视为人脸NPU已上线。
