"""语音助手 HTTP 客户端：面板/自动化引擎触达 voice :8101 的独立通道。

与硬件无关——串口归 web 服务独占，这里只转发「唤醒 / 文本指令 / 状态 /
事件流」。地址解析优先级：环境变量 SMART_HOME_VOICE_URL >
web_config.yaml 的 voice.url > 默认 http://127.0.0.1:8101。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_VOICE_URL = "http://127.0.0.1:8101"


def resolve_voice_url(cfg: dict | None = None) -> str:
    url = (os.environ.get("SMART_HOME_VOICE_URL")
           or (cfg or {}).get("voice", {}).get("url")
           or DEFAULT_VOICE_URL)
    return str(url).rstrip("/")


def voice_request(base_url: str, path: str, payload: dict | None = None,
                  timeout: float = 3.0) -> tuple[bool, str]:
    """请求语音助手 HTTP 接口，返回 (是否成功, 文本)。"""
    url = f"{base_url}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "X-Trigger-Source": "web"},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            return False, str(body.get("error") or f"语音助手 HTTP {e.code}")
        except Exception:
            return False, f"语音助手 HTTP {e.code}"
    except Exception as e:
        return False, f"语音助手不可达（{base_url}）: {e}"
    if not body.get("ok", True):
        return False, str(body.get("error") or "语音助手拒绝了请求")
    return True, json.dumps(body, ensure_ascii=False)


def open_event_stream(base_url: str, path: str = "/events"):
    """打开语音助手的 SSE 长连接（调用方逐行读取并及时关闭）。

    urllib 的响应对象本身可迭代行；timeout=None 表示不因上游安静而断开——
    心跳事件由语音侧周期发送，空闲超过 60s 视为上游失联。
    """
    req = urllib.request.Request(f"{base_url}{path}",
                                 headers={"Accept": "text/event-stream"})
    return urllib.request.urlopen(req, timeout=60)
