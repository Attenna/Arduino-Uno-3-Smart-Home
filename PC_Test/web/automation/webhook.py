"""HTTP 出站（webhook）：让规则把事件/状态推给外部系统。

这是给二次开发留的**唯一出站通道**，因此带两条护栏：

1. **默认只允许内网目标**。回环与 RFC1918 直接放行；公网地址、链路本地
   （``169.254.*``，云厂商元数据服务常用它）以及不认识的域名，都要在
   ``web_config.yaml`` 里显式打开（``automation.http_allow_public: true``）或逐台
   登记到 ``automation.http_allowed_hosts``。
   规则里的 URL 任何局域网客户端都能经 ``GET /api/automation/rules`` 读到，所以
   **不发送 Authorization/Cookie**，也不接受 URL 里带 ``user:pass@``。
2. **不跟随重定向**：否则一条内网 URL 用 302 就能把请求转到公网。

请求失败只影响这条动作的返回值（进执行记录），绝不抛异常拖垮规则线程。
"""
from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request

MAX_URL_LEN = 500
MAX_BODY_BYTES = 2048
MIN_TIMEOUT = 0.2
MAX_TIMEOUT = 8.0
DEFAULT_UA = "smart-home/1.0 (automation-webhook)"

# 局域网可解析的名字特征：mDNS 后缀，或根本不带点（路由器/ NAS 的 hostname）
_LAN_SUFFIXES = (".local", ".localhost", ".internal", ".lan")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """3xx 不当成功，也不跟着跳（护栏 2）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _host_kind(host: str) -> str:
    """主机名分类：loopback / private / link_local / public。字面 IP 按地址判，
    域名按名字判（``nas.local`` 算内网，``api.example.com`` 算公网）。"""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        low = host.lower().strip("[]")
        if low in ("localhost",) or low.endswith(_LAN_SUFFIXES) or "." not in low:
            return "private"
        return "public"
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local or addr.is_multicast or addr.is_reserved:
        return "link_local"
    if addr.is_private:
        return "private"
    return "public"


def check_format(url: str) -> tuple[bool, str]:
    """只查 URL 本身（协议/长度/凭据/主机名），不涉及主机放行策略。

    成功返回 (True, 去掉首尾空白的 URL)，失败返回 (False, 原因)。

    引擎读盘（宽松模式）用它：规则文件里手写一个公网地址不该让整个规则集校验失败，
    真正发请求前 _perform 会再按策略查一遍。
    """
    raw = str(url or "").strip()
    if not raw:
        return False, "URL 为空"
    if len(raw) > MAX_URL_LEN:
        return False, f"URL 超过 {MAX_URL_LEN} 字符"
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        return False, f"只允许 http/https，当前是 {parts.scheme or '（无协议）'}"
    if parts.username or parts.password:
        return False, "URL 里不要带账号密码（规则文件是明文，凭据会外泄）"
    if not (parts.hostname or ""):
        return False, "URL 缺少主机名"
    return True, raw


def check_url(url: str, *, allow_public: bool = False,
              allowed_hosts=()) -> tuple[bool, str]:
    """返回 (是否放行, 原因)。放行时原因里带归类，便于日志说明。"""
    ok, raw = check_format(url)
    if not ok:
        return False, raw
    parts = urllib.parse.urlsplit(raw)
    host = parts.hostname or ""
    registered = {str(h).lower().strip(".") for h in (allowed_hosts or ())}
    kind = _host_kind(host)
    if host.lower() in registered or host.lower().strip(".") in registered:
        return True, f"已登记主机（{host}）"
    if kind in ("public", "link_local") and not allow_public:
        hint = ("169.254.* 属链路本地（云厂商元数据服务用它），默认拒绝"
                if kind == "link_local" else
                f"{host} 是公网地址，默认不放行")
        return False, (f"{hint}；要在 web_config.yaml 的 "
                       "automation.http_allowed_hosts 登记该主机，"
                       "或打开 automation.http_allow_public")
    return True, kind


def clamp_timeout(seconds) -> float:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return 2.0
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, value))


def request(url: str, *, method: str = "post", body: str = "",
            timeout: float = 2.0) -> tuple[bool, str]:
    """发一次请求。返回 (成功?, 摘要)；摘要只含状态码，不回显响应内容。"""
    method = str(method or "post").lower()
    if method not in ("get", "post"):
        return False, f"不支持的方法 {method}"
    timeout = clamp_timeout(timeout)
    payload = None
    headers = {"User-Agent": DEFAULT_UA}
    if method == "post":
        text = str(body or "")
        payload = text.encode("utf-8")[:MAX_BODY_BYTES]
        ctype = "application/json; charset=utf-8" if _looks_like_json(text) \
            else "text/plain; charset=utf-8"
        headers["Content-Type"] = ctype
        headers["Content-Length"] = str(len(payload))
    req = urllib.request.Request(url, data=payload, headers=headers,
                                method=method.upper())
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            resp.read(512)                       # 读掉一小段，连接干净关闭
            return True, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            target = urllib.parse.urlsplit(e.headers.get("Location", "")).hostname or "?"
            return False, f"HTTP {e.code} 跳转到 {target}（出于安全不跟随重定向）"
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        return False, f"请求失败：{reason}"
    except Exception as e:                           # noqa: BLE001
        return False, f"请求异常：{e}"


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
        return True
    except (ValueError, TypeError):
        return False
