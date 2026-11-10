"""Dialogue backends: local llama.cpp, OpenAI-compatible cloud, and a rule
baseline.  The rule backend is both an offline fallback and the deterministic
reference used in the accuracy comparison.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Iterable, Optional

from .config import read_api_key
from .schemas import LLMReply, ToolCall, ToolResult

StreamCallback = Optional[Callable[[str], None]]

SYSTEM_PROMPT = (
    "你是智能家居语音助手。用户要求控制设备时必须调用工具，不要编造执行结果。"
    "回复口语化、简短，一次只说一两句；不要输出 JSON、工具名或思维过程。"
    "不确定意图时简短反问。"
)

_TOOL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.S)


def _parse_payload(payload: str) -> list[ToolCall]:
    payload = payload.strip()
    if not payload:
        return []
    payload = re.sub(r"^```(?:json)?|```$", "", payload, flags=re.I | re.M).strip()
    candidates = [payload]
    if "{{" in payload or "}}" in payload:
        candidates.append(payload.replace("{{", "{").replace("}}", "}"))
    first, last = payload.find("{"), payload.rfind("}")
    if first >= 0 and last > first:
        inner = payload[first:last + 1]
        candidates.append(inner)
        if "{{" in inner or "}}" in inner:
            candidates.append(inner.replace("{{", "{").replace("}}", "}"))
    data = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except Exception:
            continue
    if data is None:
        return []
    items = data if isinstance(data, list) else [data]
    calls = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else item
        name = fn.get("name") or fn.get("tool") or fn.get("tool_name")
        arguments = fn.get("arguments", fn.get("parameters", fn.get("args", {})))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                continue
        if name and isinstance(arguments, dict):
            calls.append(ToolCall(str(name), arguments, raw=payload))
    return calls


def parse_tool_calls(text: str) -> list[ToolCall]:
    """Parse Qwen's ``<tool_call>{...}</tool_call>`` text format.

    The GGUF chat template used by llama.cpp 0.3 emits tool calls as text
    rather than OpenAI ``tool_calls`` deltas, so this parser is the bridge.
    """
    if not text:
        return []
    calls: list[ToolCall] = []
    for match in _TOOL_BLOCK.finditer(text):
        calls.extend(_parse_payload(match.group(1)))
    if calls:
        return calls
    stripped = text.strip()
    if stripped.startswith("{") and '"name"' in stripped:
        return _parse_payload(stripped)
    return []


def strip_tool_blocks(text: str) -> str:
    return _TOOL_BLOCK.sub("", text or "").strip()


def _merge_tool_delta(acc: list[dict[str, Any]], deltas: Iterable[dict[str, Any]]) -> None:
    for delta in deltas or []:
        index = int(delta.get("index", len(acc)))
        while len(acc) <= index:
            acc.append({"id": "", "name": "", "arguments": ""})
        item = acc[index]
        if delta.get("id"):
            item["id"] = delta["id"]
        fn = delta.get("function") or {}
        if fn.get("name"):
            item["name"] += fn["name"]
        if fn.get("arguments"):
            item["arguments"] += fn["arguments"]


class BaseLLM:
    backend = "base"

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict]] = None,
             stream_cb: StreamCallback = None) -> LLMReply:
        raise NotImplementedError


class LlamaCppLLM(BaseLLM):
    backend = "llama_cpp"

    def __init__(self, cfg: dict[str, Any], **common: Any):
        self.cfg = cfg
        self.common = common
        self._llm = None

    def _load(self):
        if self._llm is not None:
            return self._llm
        from llama_cpp import Llama

        model_path = self.cfg.get("model_path")
        if not model_path or not __import__("os").path.isfile(model_path):
            raise RuntimeError(f"本地 LLM 模型不存在: {model_path}")
        self._llm = Llama(
            model_path=model_path,
            n_ctx=int(self.cfg.get("n_ctx", 4096)),
            n_threads=int(self.cfg.get("n_threads", 12)),
            n_batch=int(self.cfg.get("n_batch", 512)),
            n_gpu_layers=int(self.cfg.get("n_gpu_layers", 0)),
            verbose=bool(self.cfg.get("verbose", False)),
        )
        return self._llm

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict]] = None,
             stream_cb: StreamCallback = None) -> LLMReply:
        llm = self._load()
        kwargs: dict[str, Any] = dict(
            messages=messages,
            stream=True,
            max_tokens=int(self.common.get("max_tokens", 128)),
            temperature=float(self.common.get("temperature", 0.2)),
        )
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        started = time.perf_counter()
        first_ms: Optional[float] = None
        content_parts: list[str] = []
        delta_calls: list[dict[str, Any]] = []
        try:
            for chunk in llm.create_chat_completion(**kwargs):
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                if delta.get("tool_calls"):
                    if first_ms is None:
                        first_ms = (time.perf_counter() - started) * 1000.0
                    _merge_tool_delta(delta_calls, delta["tool_calls"])
                if text:
                    if first_ms is None:
                        first_ms = (time.perf_counter() - started) * 1000.0
                    content_parts.append(text)
                    if stream_cb:
                        stream_cb(text)
        except Exception as exc:
            raise RuntimeError(f"本地 LLM 推理失败: {exc}") from exc
        total_ms = (time.perf_counter() - started) * 1000.0
        raw = "".join(content_parts)
        calls: list[ToolCall] = []
        for item in delta_calls:
            arguments = item.get("arguments") or "{}"
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except Exception:
                parsed = {}
            if item.get("name") and isinstance(parsed, dict):
                calls.append(ToolCall(item["name"], parsed, raw=arguments))
        if not calls:
            calls = parse_tool_calls(raw)
        text = strip_tool_blocks(raw)
        if calls and not text:
            text = ""
        return LLMReply(text=text, tool_calls=calls, first_token_ms=first_ms,
                        total_ms=total_ms, backend=self.backend, raw=raw)


class OpenAICompatLLM(BaseLLM):
    backend = "openai"

    def __init__(self, cfg: dict[str, Any], **common: Any):
        self.cfg = cfg
        self.common = common
        self.base_url = str(cfg.get("base_url") or "").rstrip("/")
        self.api_key = read_api_key(cfg)
        self.model = cfg.get("model") or ""

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict]] = None,
             stream_cb: StreamCallback = None) -> LLMReply:
        if not self.api_key:
            raise RuntimeError("未配置 LLM API Key（llm.openai.api_key / LLM_API_KEY / llm_key.txt）")
        import httpx

        payload: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            stream=True,
            max_tokens=int(self.common.get("max_tokens", 128)),
            temperature=float(self.common.get("temperature", 0.2)),
        )
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        payload.update(self.cfg.get("extra_body") or {})
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = time.perf_counter()
        first_ms: Optional[float] = None
        content_parts: list[str] = []
        delta_calls: list[dict[str, Any]] = []
        timeout = float(self.cfg.get("timeout_s", 30.0))
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", f"{self.base_url}/chat/completions",
                               headers=headers, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    text = delta.get("content") or ""
                    if delta.get("tool_calls"):
                        if first_ms is None:
                            first_ms = (time.perf_counter() - started) * 1000.0
                        _merge_tool_delta(delta_calls, delta["tool_calls"])
                    if text:
                        if first_ms is None:
                            first_ms = (time.perf_counter() - started) * 1000.0
                        content_parts.append(text)
                        if stream_cb:
                            stream_cb(text)
        total_ms = (time.perf_counter() - started) * 1000.0
        raw = "".join(content_parts)
        calls: list[ToolCall] = []
        for item in delta_calls:
            arguments = item.get("arguments") or "{}"
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except Exception:
                parsed = {}
            if item.get("name") and isinstance(parsed, dict):
                calls.append(ToolCall(item["name"], parsed, raw=arguments))
        if not calls:
            calls = parse_tool_calls(raw)
        return LLMReply(text=strip_tool_blocks(raw), tool_calls=calls,
                        first_token_ms=first_ms, total_ms=total_ms,
                        backend=self.backend, raw=raw)


_ROOM_WORDS = {
    "客厅": "living_room", "起居室": "living_room", "卧室": "bedroom",
    "房间": "bedroom", "厨房": "kitchen",
}
_COLOR_WORDS = {
    "红": "red", "蓝": "blue", "绿": "green", "白": "white",
    "黄": "yellow", "紫": "purple", "橙": "orange", "粉": "pink",
}
_SCENE_WORDS = {
    "回家": "home", "离家": "away", "睡觉": "sleep", "睡眠": "sleep",
    "观影": "movie", "电影": "movie",
}
_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(value: str) -> Optional[int]:
    value = (value or "").strip()
    if not value:
        return None
    if "十" in value:
        tens, _, ones = value.partition("十")
        tens_value = _CN_NUM.get(tens, 1) if tens else 1
        ones_value = _CN_NUM.get(ones, 0) if ones else 0
        return tens_value * 10 + ones_value
    if len(value) == 1:
        return _CN_NUM.get(value)
    return None


class RuleLLM(BaseLLM):
    """Regex intent parser used as a deterministic fallback/baseline."""

    backend = "rules"

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict]] = None,
             stream_cb: StreamCallback = None) -> LLMReply:
        text = ""
        for message in reversed(messages):
            if message.get("role") == "user" and message.get("content"):
                text = str(message["content"]).strip()
                break
        started = time.perf_counter()
        calls, answer = self._parse(text)
        if stream_cb and answer:
            stream_cb(answer)
        return LLMReply(text=answer, tool_calls=calls,
                        first_token_ms=0.1, total_ms=(time.perf_counter() - started) * 1000.0,
                        backend=self.backend, raw=text,
                        final_text_ready=True)

    @staticmethod
    def _room(text: str) -> str:
        for word, room in _ROOM_WORDS.items():
            if word in text:
                return room
        return "living_room"

    @staticmethod
    def _number(text: str) -> Optional[int]:
        match = re.search(r"([0-9]+)\s*(?:档|度|%)", text)
        if match:
            return int(match.group(1))
        match = re.search(r"([零一二两三四五六七八九十]+)\s*(?:档|度|%)", text)
        if match:
            return _cn_to_int(match.group(1))
        return None

    def _parse(self, text: str) -> tuple[list[ToolCall], str]:
        if not text:
            return [], "我在，请说。"
        if "灯" in text:
            room = self._room(text)
            color = next((value for word, value in _COLOR_WORDS.items() if word in text), None)
            if "关" in text and "开" not in text:
                return [ToolCall("control_light", {"action": "off", "room": room})], "好的，已关灯。"
            if "暗" in text:
                return [ToolCall("control_light", {"action": "set", "room": room, "brightness": 30})], "好的，已调暗。"
            if "亮" in text:
                return [ToolCall("control_light", {"action": "set", "room": room, "brightness": 100})], "好的，已调亮。"
            if color:
                return [ToolCall("control_light", {"action": "set", "room": room, "color": color})], "好的，灯光颜色已切换。"
            brightness = self._number(text)
            if brightness is not None:
                return [ToolCall("control_light", {"action": "set", "room": room,
                                                    "brightness": min(100, brightness)})], "好的，亮度已调整。"
            return [ToolCall("control_light", {"action": "on", "room": room})], "好的，已开灯。"
        if "风扇" in text or "风速" in text:
            if "关" in text:
                return [ToolCall("control_fan", {"action": "off"})], "好的，风扇已关闭。"
            speed = self._number(text)
            if speed is not None:
                return [ToolCall("control_fan", {"action": "set", "speed": min(3, max(0, speed))})], "好的，风速已调整。"
            return [ToolCall("control_fan", {"action": "on"})], "好的，风扇已打开。"
        if "门" in text:
            if "解锁" in text:
                return [ToolCall("control_door", {"action": "unlock"})], "好的，门已解锁。"
            if "锁" in text:
                return [ToolCall("control_door", {"action": "lock"})], "好的，门已上锁。"
            if "开" in text:
                return [ToolCall("control_door", {"action": "open"})], "好的，门已打开。"
            return [ToolCall("control_door", {"action": "close"})], "好的，门已关闭。"
        if "空调" in text:
            if "关" in text:
                return [ToolCall("control_ac", {"action": "off"})], "好的，空调已关闭。"
            temperature = self._number(text)
            args: dict[str, Any] = {"action": "on"}
            if temperature is not None:
                args = {"action": "set", "temperature": min(30, max(16, temperature))}
            return [ToolCall("control_ac", args)], "好的，空调已调整。"
        for word, scene in _SCENE_WORDS.items():
            if word in text:
                return [ToolCall("set_scene", {"scene": scene})], "好的，场景已切换。"
        if any(word in text for word in ("温度", "湿度", "多少度", "有人", "传感器")):
            if "湿度" in text:
                metric = "humidity"
            elif "有人" in text or "人体" in text:
                metric = "motion"
            elif "温度" in text or "多少度" in text:
                metric = "temperature"
            else:
                metric = "all"
            return [ToolCall("query_sensor", {"metric": metric})], "我查一下。"
        if any(word in text for word in ("你好", "在吗", "你是谁")):
            return [], "你好，我是智能家居语音助手，可以控制灯、风扇、门和空调，也能查温度和湿度。"
        return [], "抱歉，我没有理解。你可以说“打开客厅灯”或“现在多少度”。"


class HybridLLM(BaseLLM):
    """Fast deterministic router + LLM for open-ended turns.

    Explicit device commands (``打开客厅灯``) are handled by the rule parser in
    microseconds; anything else goes to the local/cloud LLM.  This is the
    latency/quality compromise used by the live demo by default.
    """

    backend = "hybrid"

    def __init__(self, fallback: BaseLLM):
        self.fallback = fallback
        self.rapid = RuleLLM()

    @staticmethod
    def _last_user(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content") or "")
        return ""

    @staticmethod
    def _context_rewrite(text: str, messages: list[dict[str, Any]]) -> str:
        """Resolve ellipsis like 「调到三档」 using the previous device.

        This is a tiny dialogue-state tracker, not a language model: it only
        fires when the current turn has no device noun and an explicit action
        or attribute that belongs to the last device.
        """
        if any(word in text for word in ("灯", "风扇", "空调", "门", "传感器", "湿度", "温度")):
            return text
        last_device = ""
        room_word = ""
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            previous = str(message.get("content") or "")
            if "灯" in previous:
                last_device = "light"
                room_id = next((room for word, room in _ROOM_WORDS.items() if word in previous),
                               "living_room")
                room_word = {"living_room": "客厅", "bedroom": "卧室",
                             "kitchen": "厨房"}.get(room_id, "客厅")
                break
            if "风扇" in previous or "风速" in previous:
                last_device = "fan"
                break
            if "空调" in previous:
                last_device = "ac"
                break
            if "门" in previous:
                last_device = "door"
                break
        if last_device == "light" and any(k in text for k in ("颜色", "色", "亮", "暗", "开", "关", "调")):
            return f"{room_word}灯{text}"
        if last_device == "fan" and any(k in text for k in ("档", "风速", "开", "关", "调")):
            return "风扇" + text
        if last_device == "ac" and (re.search(r"\d+\s*度", text) or any(
                k in text for k in ("调到", "温度", "模式"))):
            return "空调" + text
        if last_device == "door" and any(k in text for k in ("开", "关", "锁")):
            return "门" + text
        return text

    def chat(self, messages: list[dict[str, Any]], tools: Optional[list[dict]] = None,
             stream_cb: StreamCallback = None) -> LLMReply:
        if tools:
            fast = self.rapid.chat(messages, tools=None, stream_cb=None)
            if not fast.tool_calls:
                current = self._last_user(messages)
                rewritten = self._context_rewrite(current, messages[:-1])
                if rewritten != current:
                    probe = list(messages)
                    probe[-1] = {**probe[-1], "content": rewritten}
                    fast = self.rapid.chat(probe, tools=None, stream_cb=None)
            if fast.tool_calls:
                # The dialogue layer phrases the result from the real tool
                # output, so no second LLM call is necessary.
                fast.text = ""
                fast.backend = self.backend
                fast.final_text_ready = True
                return fast
        return self.fallback.chat(messages, tools=tools, stream_cb=stream_cb)


def build_llm(cfg: dict[str, Any], backend: Optional[str] = None,
              **common: Any) -> BaseLLM:
    backend = (backend or cfg.get("backend") or "hybrid").lower()
    if backend in ("llama_cpp", "local", "llama"):
        return LlamaCppLLM(cfg.get("llama_cpp") or {}, **common)
    if backend in ("openai", "siliconflow", "dashscope", "cloud"):
        return OpenAICompatLLM(cfg.get("openai") or {}, **common)
    if backend in ("rules", "rule"):
        return RuleLLM()
    if backend in ("hybrid", "auto"):
        return HybridLLM(LlamaCppLLM(cfg.get("llama_cpp") or {}, **common))
    raise RuntimeError(f"未知 LLM 后端: {backend}")


def build_tool_followup(messages: list[dict[str, Any]], calls: list[ToolCall],
                        results: list[ToolResult]) -> list[dict[str, Any]]:
    """Native tool-call transcript for the second LLM call."""
    tool_calls = []
    tool_messages = []
    for index, (call, result) in enumerate(zip(calls, results)):
        call_id = f"call_{index}"
        tool_calls.append({
            "id": call_id, "type": "function",
            "function": {"name": call.name,
                         "arguments": json.dumps(call.arguments, ensure_ascii=False)},
        })
        tool_messages.append({
            "role": "tool", "tool_call_id": call_id,
            "content": ("成功：" if result.ok else "失败：") + result.text,
        })
    return messages + [{"role": "assistant", "content": "", "tool_calls": tool_calls}] + tool_messages
