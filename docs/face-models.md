# 人脸嵌入模型

「认人」这一步用的 ONNX 模型不进 Git（见 `AGENTS.md` 与 `docs/git-workflow.md`：模型权重属于运行时资产），
所以本页记录**来源、校验和、实测数据、换模型步骤**。检测模型（`yolov8n-face.pt`）不在本页范围。

配置项：`PC_Test/web_config.yaml` 的 `face.recognition.model_path`（相对路径按 `PC_Test/` 解析，
容器里就是 `/app`）。`PC_Test/data/face/face_config.json` 里的同名字段**不参与**模型选择——
那是运行期写出来的文件，可能带着另一台机器的绝对路径。

## 候选与实测（Orange Pi，aarch64 3 核，纯 CPU，onnxruntime 1.30，服务常驻负载 ~19）

| 模型 | 文件 | 大小 | 单脸提特征 p50 | p90 | 同人最低 | 异人最高 |
| --- | --- | --- | --- | --- | --- | --- |
| InsightFace **w600k_mbf**（MobileFaceNet，现役） | `models/face/w600k_mbf.onnx` | 13.6 MB | **93 ms** | 173 ms | 0.788 | 0.265 |
| InsightFace **iresnet50**（回滚方案） | `models/face/recognition.onnx` | 174.4 MB | 411 ms | 833 ms | 0.804 | 0.200 |

- 两者输入均为 `1×3×112×112` float32、RGB、`(x-127.5)/127.5`，输出 512 维 —— 对本项目的预处理管线逐字节兼容。
- 表中「同人/异人」是留一法：拿派上 `data/face/authorized/{A,B,C}/` 各 8 张注册照，每张 vs 自己其余 7 张的均值原型
  取最小值，以及 vs 另外两个身份原型的最大值。生产阈值 `similarity_threshold: 0.5`，两侧各有 0.23 以上余量。
- 换到 MobileFaceNet 后判别余量比 iresnet50 略窄（0.523 vs 0.604），但离阈值还很远；换来的是每脸省 ~318 ms。

## 来源与校验

```
buffalo_sc.zip  https://github.com/deepinsight/insightface/releases/download/model-zoo/buffalo_sc.zip
                （内含 det_500m.onnx + w600k_mbf.onnx；本仓库只用后者）
sha256  w600k_mbf.onnx      9cc6e4a75f0e2bf0b1aed94578f144d15175f357bdc05e815e5c4a02b319eb4f
        recognition.onnx    4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43
```

放好文件后核对一次：

```bash
sha256sum PC_Test/models/face/w600k_mbf.onnx
```

## 换模型必须重建人脸库

不同模型的 512 维向量互不相通：实测拿 iresnet50 的查询向量去比 MobileFaceNet 的原型，
相似度只有 **0.077**（同人也一样），也就是说混用的后果是**谁都开不了门**，而不是误开门。

`data/face/embeddings.pkl` 因此记录 `model_fingerprint`（method + 模型文件大小 + 模型文件头 sha256 前 16 位）。
引擎加载时发现库内指纹与当前模型不一致就停用认人：日志报 `[人脸] 库与模型不匹配，认人已停用`，
门禁页的体检条列出两个指纹（`GET /api/access/diagnostics` 的 `model_mismatch`），录脸也会被拒绝，
避免建出混着两种向量的库。没有该字段的老库按当前模型继续用，下次录入或重建时补写指纹。

重建步骤（改 `model_path` 之后立刻做，否则门禁认不出人）：

```bash
# 派上（容器里跑，宿主机 ~/smart-home 挂载为 /app）
docker exec smart-home-web-1 cp /app/data/face/embeddings.pkl /app/data/face/embeddings-前一个模型.pkl.bak
docker exec -w /app smart-home-web-1 python scripts/enroll_faces.py --method arcface_onnx
docker compose restart web

# PC 上（cwd 必须是 PC_Test，模型路径是相对的）
cd PC_Test && py -3.13 scripts/enroll_faces.py --method arcface_onnx
```

重建前先落一份 `.bak`；回滚 = 把 yaml 那行改回 `recognition.onnx`、恢复备份库、重启 web，不需要改代码。
