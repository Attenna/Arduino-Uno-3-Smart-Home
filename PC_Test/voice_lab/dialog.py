"""One-turn orchestration: ASR -> LLM/tools -> streaming TTS, with timing."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Optional

from .asr import ASRResult, build_asr
from .config import load_config
from .llm import BaseLLM, build_llm, build_tool_followup
from .schemas import Timing, ToolResult, TurnResult
from .tools import TOOLS, MockHome
from .tts import BaseTTS, SentenceSplitter, TTSPlayer, build_tts


class DialogEngine:
    def __init__(self, cfg: dict[str, Any], *, asr=None, llm: Optional[BaseLLM] = None,
                 tts: Optional[BaseTTS] = None, home: Optional[MockHome] = None,
                 play_tts: bool = True, tts_enabled: bool = True):
        self.cfg = cfg
        self.asr = asr or build_asr(cfg["asr"])
        self.llm = llm or build_llm(
            cfg["llm"],
            max_tokens=int(cfg["llm"].get("max_tokens", 128)),
            temperature=float(cfg["llm"].get("temperature", 0.2)),
        )
        self.tts = tts or build_tts(cfg["tts"])
        self.home = home or MockHome()
        self.play_tts = play_tts
        self.tts_enabled = tts_enabled
        self.history: list[dict[str, str]] = []
        self._lock = threading.RLock()
        self._last_events: list[dict[str, Any]] = []
        self._cancel = threading.Event()
        self._active_player: Optional[TTSPlayer] = None

    # ── status ───────────────────────────────────────────────────────
    def model_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {"asr": self.asr.backend, "llm": self.llm.backend,
                                  "tts": self.tts.backend}
        asr_cfg = self.cfg["asr"]
        if self.asr.backend == "sherpa":
            d = asr_cfg["sherpa"].get("model_dir", "")
            status["asr_model"] = all(os.path.isfile(os.path.join(d, f))
                                      for f in ("encoder.onnx", "decoder.onnx", "tokens.txt"))
        elif self.asr.backend == "whisper":
            d = asr_cfg["whisper"].get("download_root", "")
            status["asr_model"] = os.path.isdir(d) and any(
                name.endswith(".pt") for name in os.listdir(d))
        if self.llm.backend == "llama_cpp":
            status["llm_model"] = os.path.isfile(self.cfg["llm"]["llama_cpp"].get("model_path", ""))
        elif self.llm.backend == "openai":
            from .config import read_api_key
            status["llm_model"] = bool(read_api_key(self.cfg["llm"].get("openai") or {}))
        else:
            status["llm_model"] = True
        status["state"] = self.home.summary()
        return status

    def info(self) -> dict[str, Any]:
        return {
            **self.model_status(),
            "history_turns": len(self.history) // 2,
            "tts_play": self.play_tts,
            "tts_enabled": self.tts_enabled,
            "tools": [t["function"]["name"] for t in TOOLS],
        }

    def reset(self) -> None:
        with self._lock:
            self.home.reset()
            self.history.clear()
            self._last_events = []

    def preload(self) -> dict[str, str]:
        """Load ASR/LLM/TTS weights so the first user turn is not a cold start."""
        status: dict[str, str] = {}
        targets = [("asr", self.asr)]
        llm_target = getattr(self.llm, "fallback", self.llm)
        targets.append(("llm", llm_target))
        targets.append(("tts", self.tts))
        for name, obj in targets:
            loader = getattr(obj, "_load", None)
            if loader is None:
                status[name] = "lazy/none"
                continue
            try:
                loader()
                status[name] = "loaded"
            except Exception as exc:
                status[name] = f"failed: {exc}"
        return status

    def cancel(self) -> None:
        """Stop the current turn/TTS; safe to call from another thread."""
        self._cancel.set()
        player = self._active_player
        if player is not None:
            player.stop()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ── dialogue ─────────────────────────────────────────────────────
    def _messages(self, user_text: str) -> list[dict[str, str]]:
        rounds = int(self.cfg["llm"].get("history_rounds", 3)) * 2
        history = self.history[-rounds:] if rounds else []
        return [{"role": "system", "content": str(self.cfg["dialog"]["system_prompt"])}] \
            + history + [{"role": "user", "content": user_text}]

    @staticmethod
    def _answer_from_tools(results: list[ToolResult]) -> str:
        if not results:
            return "好的。"
        parts = []
        for result in results:
            if not result.ok:
                parts.append("抱歉，" + result.text)
            elif result.name.startswith("query_"):
                parts.append(result.text)
            else:
                parts.append("好的，" + result.text)
        text = "；".join(parts)
        return text if text.endswith(("。", "！", "？")) else text + "。"

    def _remember(self, user_text: str, final_text: str,
                  tool_results: list[ToolResult]) -> None:
        note = ""
        if tool_results:
            note = "（工具：" + "；".join(
                f"{r.name}{'成功' if r.ok else '失败'}" for r in tool_results) + "）"
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": final_text + note})
        rounds = int(self.cfg["llm"].get("history_rounds", 3)) * 2
        if rounds and len(self.history) > rounds:
            self.history = self.history[-rounds:]

    def handle_text(self, text: str, *, speak: bool = True,
                    play: Optional[bool] = None,
                    stage_cb: Optional[Callable[[str], None]] = None) -> TurnResult:
        text = (text or "").strip()
        self._cancel.clear()
        self._active_player = None
        with self._lock:
            started = time.perf_counter()
            events: list[dict[str, Any]] = []
            timing = Timing()

            def emit(kind: str, **fields: Any) -> None:
                events.append({"type": kind, "ts": time.time(), **fields})

            def stage(name: str) -> None:
                if stage_cb is None:
                    return
                try:
                    stage_cb(name)
                except Exception:
                    pass

            stage("thinking")
            if not text:
                result = TurnResult("", "", events=events, state=self.home.snapshot(),
                                    error="空指令")
                self._last_events = events
                return result

            emit("user", text=text)
            messages = self._messages(text)
            player: Optional[TTSPlayer] = None
            splitter: Optional[SentenceSplitter] = None
            if speak and self.tts_enabled:
                player = TTSPlayer(self.tts, play=self.play_tts if play is None else play)
                player.start()
                splitter = SentenceSplitter()

            def stream_cb(token: str) -> None:
                if not token or self._cancel.is_set():
                    return
                emit("assistant_delta", text=token)
                if splitter is not None and player is not None:
                    for sentence in splitter.feed(token):
                        player.feed_sentences([sentence])

            llm_started = time.perf_counter()
            tool_results: list[ToolResult] = []
            final_text = ""
            final_first_ms: Optional[float] = None
            final_streamed = False
            try:
                reply = self.llm.chat(messages, tools=TOOLS, stream_cb=stream_cb)
                final_text = (reply.text or "").strip()
                final_first_ms = reply.first_token_ms
                calls = reply.tool_calls
                if self._cancel.is_set():
                    if player is not None:
                        player.stop()
                    emit("cancelled", text="用户打断")
                    timing.total_ms = (time.perf_counter() - started) * 1000.0
                    result = TurnResult(text, "", tool_results, timing, events,
                                        state=self.home.snapshot(), error="cancelled")
                    self._last_events = events
                    return result
                if calls:
                    # A tool-call turn: discard any partial speech, execute tools,
                    # then let the model phrase the result in natural language.
                    if splitter is not None:
                        splitter.reset()
                    if player is not None:
                        player.clear()
                    seen: set[tuple] = set()
                    max_calls = int(self.cfg["llm"].get("max_tool_calls", 4))
                    for call in calls[:max_calls]:
                        key = (call.name, json.dumps(call.arguments, sort_keys=True,
                                                     ensure_ascii=False))
                        if key in seen:
                            result = ToolResult(call.name, call.arguments, False,
                                                "重复调用已忽略")
                        else:
                            seen.add(key)
                            tool_started = time.perf_counter()
                            result = self.home.execute(call)
                            result.latency_ms = (time.perf_counter() - tool_started) * 1000.0
                            timing.tool_ms += result.latency_ms
                        tool_results.append(result)
                        emit("tool", **result.to_dict())
                    if self._cancel.is_set():
                        if player is not None:
                            player.stop()
                        emit("cancelled", text="用户打断")
                        timing.total_ms = (time.perf_counter() - started) * 1000.0
                        result = TurnResult(text, "", tool_results, timing, events,
                                            state=self.home.snapshot(), error="cancelled")
                        self._last_events = events
                        return result
                    if getattr(reply, "final_text_ready", False):
                        final_text = self._answer_from_tools(tool_results)
                        final_streamed = False
                    else:
                        followup = build_tool_followup(messages, calls[:max_calls], tool_results)
                        try:
                            second = self.llm.chat(followup, tools=None, stream_cb=stream_cb)
                            final_text = (second.text or "").strip()
                            final_first_ms = second.first_token_ms or final_first_ms
                            final_streamed = True
                        except Exception as exc:
                            emit("error", stage="llm_followup", text=str(exc))
                            final_text = self._answer_from_tools(tool_results)
                    if not final_text:
                        final_text = self._answer_from_tools(tool_results)
                else:
                    final_streamed = True
                timing.llm_total_ms = (time.perf_counter() - llm_started) * 1000.0
                timing.llm_first_token_ms = float(final_first_ms or reply.first_token_ms or 0.0)

                if player is not None and splitter is not None:
                    if not final_streamed and final_text:
                        player.feed_sentences(splitter.flush())
                        for sentence in splitter.feed(final_text):
                            player.feed_sentences([sentence])
                    player.feed_sentences(splitter.flush())
                    self._active_player = player
                    stage("speaking")
                    player.flush()
                    player.wait_done()
                    self._active_player = None
                    timing.tts_first_audio_ms = player.first_audio_ms
                    timing.tts_total_ms = (time.perf_counter() - started) * 1000.0
                    if player.last_error:
                        emit("error", stage="tts", text=player.last_error)
                    if self._cancel.is_set():
                        emit("cancelled", text="用户打断")
                        timing.total_ms = (time.perf_counter() - started) * 1000.0
                        result = TurnResult(text, "", tool_results, timing, events,
                                            state=self.home.snapshot(), error="cancelled")
                        self._last_events = events
                        return result

                timing.total_ms = (time.perf_counter() - started) * 1000.0
                self._remember(text, final_text, tool_results)
                emit("assistant", text=final_text)
                emit("timing", **timing.to_dict())
                emit("state", state=self.home.snapshot())
                stage("done")
                result = TurnResult(text, final_text, tool_results, timing, events,
                                    state=self.home.snapshot())
                self._last_events = events
                return result
            except Exception as exc:
                self._active_player = None
                if player is not None:
                    player.stop()
                emit("error", stage="turn", text=str(exc))
                timing.total_ms = (time.perf_counter() - started) * 1000.0
                result = TurnResult(text, "", tool_results, timing, events,
                                    state=self.home.snapshot(), error=str(exc))
                self._last_events = events
                return result

    def handle_audio(self, path: str, *, speak: bool = True,
                     play: Optional[bool] = None,
                     stage_cb: Optional[Callable[[str], None]] = None) -> TurnResult:
        with self._lock:
            if stage_cb is not None:
                try:
                    stage_cb("transcribing")
                except Exception:
                    pass
            asr_started = time.perf_counter()
            try:
                asr = self.asr.transcribe_file(path)
            except Exception as exc:
                result = TurnResult("", "", state=self.home.snapshot(), error=f"ASR 失败: {exc}")
                result.events = [{"type": "error", "stage": "asr", "text": str(exc)}]
                return result
            asr.latency_ms = (time.perf_counter() - asr_started) * 1000.0
            if asr.audio_duration_s:
                asr.rtf = asr.latency_ms / 1000.0 / asr.audio_duration_s
            if not asr.text:
                result = TurnResult("", "", state=self.home.snapshot(), error="没有识别到语音")
                result.asr = asr
                result.events = [{"type": "asr", **asr.to_dict()},
                                 {"type": "error", "stage": "asr", "text": "没有识别到语音"}]
                return result
            if self._cancel.is_set():
                result = TurnResult(asr.text, "", state=self.home.snapshot(), error="cancelled")
                result.asr = asr
                result.events = [{"type": "asr", **asr.to_dict()},
                                 {"type": "cancelled", "text": "用户打断"}]
                return result
            result = self.handle_text(asr.text, speak=speak, play=play, stage_cb=stage_cb)
            result.asr = asr
            result.timing.asr_ms = asr.latency_ms
            result.timing.audio_duration_s = asr.audio_duration_s
            result.timing.asr_rtf = asr.rtf
            result.timing.total_ms += asr.latency_ms
            if result.timing.tts_first_audio_ms:
                result.timing.tts_first_audio_ms += asr.latency_ms
            result.events.insert(0, {"type": "asr", **asr.to_dict()})
            return result


def make_engine(config_path: Optional[str] = None, *, asr_backend: Optional[str] = None,
                llm_backend: Optional[str] = None, tts_backend: Optional[str] = None,
                play_tts: bool = True, tts_enabled: bool = True) -> DialogEngine:
    cfg = load_config(config_path)
    if asr_backend:
        cfg["asr"]["backend"] = asr_backend
    if llm_backend:
        cfg["llm"]["backend"] = llm_backend
    if tts_backend:
        cfg["tts"]["backend"] = tts_backend
    return DialogEngine(cfg, play_tts=play_tts, tts_enabled=tts_enabled)
