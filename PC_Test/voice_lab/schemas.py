"""Shared data types for the voice-lab cascade.

The module deliberately has no third-party imports so the unit tests and the
web layer can import it without models, audio devices or a GPU.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}


@dataclass
class ToolResult:
    name: str
    arguments: dict[str, Any]
    ok: bool
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "ok": self.ok,
            "text": self.text,
            "data": self.data,
            "latency_ms": round(self.latency_ms, 3),
        }


@dataclass
class ASRResult:
    text: str
    backend: str
    latency_ms: float = 0.0
    audio_duration_s: float = 0.0
    rtf: float = 0.0
    audio_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "backend": self.backend,
            "latency_ms": round(self.latency_ms, 3),
            "audio_duration_s": round(self.audio_duration_s, 3),
            "rtf": round(self.rtf, 3),
            "audio_path": self.audio_path,
        }


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    first_token_ms: Optional[float] = None
    total_ms: float = 0.0
    backend: str = ""
    raw: str = ""
    # True when ``text`` is already a complete spoken answer for the tool
    # calls (rule/hybrid fast path), so no second LLM call is needed.
    final_text_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "first_token_ms": None if self.first_token_ms is None else round(self.first_token_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "backend": self.backend,
        }


@dataclass
class TTSResult:
    backend: str
    text: str
    audio_path: str = ""
    first_audio_ms: float = 0.0
    total_ms: float = 0.0
    duration_s: float = 0.0
    sample_rate: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "text": self.text,
            "audio_path": self.audio_path,
            "first_audio_ms": round(self.first_audio_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "duration_s": round(self.duration_s, 3),
            "sample_rate": self.sample_rate,
            "error": self.error,
        }


@dataclass
class Timing:
    """Latency marks for one dialogue turn, all in milliseconds."""

    asr_ms: float = 0.0
    llm_first_token_ms: float = 0.0
    llm_total_ms: float = 0.0
    tool_ms: float = 0.0
    tts_first_audio_ms: float = 0.0
    tts_total_ms: float = 0.0
    total_ms: float = 0.0
    audio_duration_s: float = 0.0
    asr_rtf: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "asr_ms": round(self.asr_ms, 3),
            "llm_first_token_ms": round(self.llm_first_token_ms, 3),
            "llm_total_ms": round(self.llm_total_ms, 3),
            "tool_ms": round(self.tool_ms, 3),
            "tts_first_audio_ms": round(self.tts_first_audio_ms, 3),
            "tts_total_ms": round(self.tts_total_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "audio_duration_s": round(self.audio_duration_s, 3),
            "asr_rtf": round(self.asr_rtf, 3),
        }


@dataclass
class TurnResult:
    user_text: str
    reply: str
    tool_calls: list[ToolResult] = field(default_factory=list)
    timing: Timing = field(default_factory=Timing)
    events: list[dict[str, Any]] = field(default_factory=list)
    asr: Optional[ASRResult] = None
    state: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_text": self.user_text,
            "reply": self.reply,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "timing": self.timing.to_dict(),
            "events": self.events,
            "asr": self.asr.to_dict() if self.asr else None,
            "state": self.state,
            "error": self.error,
        }
