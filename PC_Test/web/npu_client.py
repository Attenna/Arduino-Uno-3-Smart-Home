"""Validated binary tensor transport to private Ascend inference services."""
import numpy as np
import requests


def infer_npu(url, token, tensor, output_shape):
    if len(token) < 32:
        raise ValueError('NPU 服务认证配置缺失')
    tensor = np.ascontiguousarray(tensor, dtype=np.float32)
    try:
        response = requests.post(url.rstrip('/') + '/infer', data=tensor.tobytes(),
                                 headers={'Authorization':'Bearer '+token,
                                          'Content-Type':'application/octet-stream'}, timeout=15)
    except requests.RequestException as exc:
        raise RuntimeError('NPU 推理服务未响应') from exc
    if response.status_code != 200:
        raise RuntimeError('NPU 推理服务不可用，请检查服务日志')
    shape = tuple(output_shape)
    if len(response.content) != int(np.prod(shape))*4:
        raise RuntimeError('NPU 输出尺寸不匹配')
    output = np.frombuffer(response.content,dtype=np.float32).reshape(shape)
    if not np.isfinite(output).all():
        raise RuntimeError('NPU 输出包含无效数值')
    return output
