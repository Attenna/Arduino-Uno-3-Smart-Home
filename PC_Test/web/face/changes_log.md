# 人脸识别变更日志

本文件长期记录 `PC_Test/web/face/` 及其直接调用链的功能、接口、数据和部署变更。
版本号采用 `主版本.次版本.修订号`：不兼容的数据或接口变更升级主版本，向后兼容的
功能升级次版本，缺陷修复升级修订号。

维护要求：每次修改人脸识别代码时，必须在最新版本顶部新增一节，写明版本号、发布时间、
分类条目和每条变更的要点；涉及模型、预处理或阈值时，还必须写明是否需要重建人脸库、
是否需要调整部署配置。尚未发布的改动使用“未发布”，发布或部署时再替换成实际日期。

## v1.0.1（2026-10-09）

对应 Issue #75「人脸识别历史记录入库不及时、有丢失」。本次不改人脸库、不涉及数据库
结构变更，属向后兼容的缺陷修复。

### 修复

- **每轮识别都留痕**：`AccessGuard.handle_face_result` 不再把去抖判断放在写库之前；
  去抖与 `cooldown` 只抑制重复的开门动作与通行日志，每一轮识别都各自写一条
  `face_events`，陌生人（空 `face_id`）也不再互相顶掉。
- **判定一次落终态**：`handle_face_result` 用单条 `INSERT` 写入最终 `status` / `verified`
  / `deny_reason`，不再先插 `pending` 再更新。放行瞬间 `/api/face/events/latest` 即为
  `granted`，进程中途退出也不会留下永久 `pending` 行。
- **观测轮次落库**：`face_watcher.inspect_once` 的太远 / 节流 / 无脸 / 未唤醒 / 摄像头
  失败 / 出错等分支统一经新增的 `AccessGuard.record_observation` 写一条
  `status='observed'` 记录（`deny_reason` 存轮次种类）；环境类
  （`idle`/`no_camera`/`no_identity`）只在状态变化时写一行，避免每 2 秒刷屏。
- **冷却期仍记录**：哨兵在 `cooldown` 窗口内认出同一人时改为
  `handle_face_result(record_only=True)`，补记这轮历史但不再重复开门。
- **单帧接口留痕**：`POST /api/face/recognize` 现在也写 `device_source='web'` 的
  `face_events` 行（`record_only`，不广播门禁事件、不开门），与 `docs/api.md` 一致。
- **前端三态**：门禁页把 `observed`（未判定）与 `pending`（旧库中间态）渲染为灰色
  「已记录 / 判定中」，不再一律显示「已拒绝」；轮询按 `id + status` 去重，状态被改写
  时会重新渲染，不再锁死中间态。

### 配置

- 新增 `face.watcher.repeat_window`（默认 `8.0` 秒）：重复识别去抖窗口，`0` 表示不去抖。
  原硬编码 `REPEAT_WINDOW_S` 保留为默认值，`AccessGuard.configure()` 从 Web 配置读取。

### 数据兼容与部署

- **无需重建人脸库**：不改嵌入模型、预处理或阈值。
- **无数据库结构变更**：`face_events` 表已具备所需列；旧的 `pending` 行保留，前端按
  「判定中」显示。
- 部署只需重建 Web 容器（`face_watcher.py` / `access_guard.py` / `api/face.py` /
  前端静态资源均在 web 镜像内）。

### 测试

- 新增 `PC_Test/tests/test_face_event_persistence.py`：覆盖逐轮留痕、陌生人各成行、
  去抖只挡动作、单次终态写入、观测轮次落库与环境类去抖、`/recognize` 留痕不开门。
- 更新 `test_face_latency.py` 的测试替身以匹配新增的 `record_observation`。

## v1.0.0（2026-10-08）

### 新增

- **五点人脸对齐**：读取 YOLOv8-face 输出的双眼、鼻尖和双嘴角坐标，通过相似变换
  对齐到 ArcFace 112×112 标准模板后再提取嵌入，降低姿态、旋转和裁剪偏移造成的假负例。
- **兼容回退**：检测权重没有五点输出或关键点无效时，保留边界框裁剪路径，避免整条
  识别链路因单帧关键点缺失而中断；识别结果中的 `aligned` 可用于判断该帧是否实际对齐。
- **预处理版本保护**：`embeddings.pkl` 新增 `preprocessing=arcface_5point_v1`，服务启动时
  拒绝把旧的框裁剪向量与新对齐向量混用，并返回明确的重建提示。

### 变更

- **页面分数语义**：门禁页面的“置信度”改为“ArcFace 相似度”，展示身份嵌入的余弦
  `score`（保留三位小数），不再把 YOLO 人脸检测置信度误当成身份识别分数。
- **事件数据拆分**：`face_events` 新增 `score` 与 `detection_confidence` 两列，分别保存
  ArcFace 身份相似度和 YOLO 检测置信度；旧 `confidence` 列仅用于接口兼容。
- **统一建库流程**：ArcFace 网页录入热更新和 `scripts/enroll_faces.py` 离线整库重建均
  使用同一套检测、五点对齐和嵌入预处理，防止注册阶段与识别阶段的输入分布不一致；
  `simple_grayscale_cosine` 调试回退仍可不加载检测模型。
- **推送接口**：`POST /api/face/notify` 新增 `score`、`detection_confidence` 字段；旧调用方
  传入的 `confidence` 仍兼容映射为 ArcFace 分数，新调用方应使用语义明确的新字段。
- **歧义匹配保护**：合并 main 的双阈值判定，除 `score >= 0.62` 外还要求第一名与第二名
  的分差 `margin >= 0.08`；候选人过于接近时拒绝放行，避免把相似人员误认成另一人。

### 数据兼容与部署

- **必须重建人脸库**：本版本首次启用五点对齐，旧 `embeddings.pkl` 不能继续使用；保留
  `data/face/authorized/` 原始注册照，运行 `scripts/enroll_faces.py` 后重启 Web 服务。
- **历史事件不伪装**：旧 `face_events` 没有独立 ArcFace 分数，页面显示 `--`，不会把历史
  YOLO 置信度误标为 ArcFace 相似度；数据库启动时会自动补齐新列，不删除旧记录。
- **检测模型要求**：建议使用能输出五点关键点的 YOLOv8-face 权重；若权重只输出人脸框，
  系统会回退普通裁剪，但无法获得本版本对姿态变化的完整改善。

### 测试

- 覆盖五点提取、相似变换、对齐输出尺寸、无关键点回退、预处理版本阻断、ArcFace 分数
  传递与事件落库，防止后续维护中再次混淆检测置信度和身份相似度。
