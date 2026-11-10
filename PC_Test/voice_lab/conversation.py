"""Continuous voice mode: KWS wake word, VAD endpointing, half-duplex states.

The controller deliberately runs the microphone and the dialogue engine on
different threads:

    IDLE ──KWS/manual──▶ WAKING ──chirp──▶ LISTENING
                                              │ VAD speech_end
                                              ▼
                                          THINKING
                                              │ first TTS sentence
                                              ▼
                                          SPEAKING
                                              │ TTS queue drained
                                              ▼
                                          FOLLOWUP ──timeout──▶ IDLE
                                              │ speech_start
                                              └──────────────▶ LISTENING

SPEAKING is **half-duplex**: microphone frames are ignored while the assistant
talks, so the TTS cannot be recognised as a user utterance.  A real barge-in
needs acoustic echo cancellation (AEC); with AEC disabled the demo offers a
manual interrupt (Esc / HTTP / Web button) which stops TTS and opens LISTENING.
The browser's `echoCancellation` constraint is enabled, but server-side AEC is
intentionally not claimed here.
"""
from __future__ import annotations

import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

import numpy as np

from .audio import play_chirp, save_wav
from .config import VOICE_LAB_DIR
from .dialog import DialogEngine


class ConversationState(str, Enum):
    IDLE = "IDLE"
    WAKING = "WAKING"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    FOLLOWUP = "FOLLOWUP"


@dataclass
class VADEvent:
    kind: str
    audio: Optional[np.ndarray] = None
    duration_s: float = 0.0


class VAD:
    """Energy VAD with pre-roll, minimum speech and trailing-silence logic."""

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.012,
                 silence_s: float = 0.8, min_speech_s: float = 0.2,
                 max_speech_s: float = 15.0, pre_roll_frames: int = 10):
        self.sample_rate = int(sample_rate)
        self.threshold = float(threshold)
        self.silence_s = float(silence_s)
        self.min_speech_s = float(min_speech_s)
        self.max_speech_s = float(max_speech_s)
        self._pre_roll: deque[np.ndarray] = deque(maxlen=max(1, pre_roll_frames))
        self._buffer: list[np.ndarray] = []
        self._speech_s = 0.0
        self._silence_s = 0.0
        self._total_s = 0.0
        self.in_speech = False

    def reset(self) -> None:
        self._pre_roll.clear()
        self._buffer = []
        self._speech_s = 0.0
        self._silence_s = 0.0
        self._total_s = 0.0
        self.in_speech = False

    def force_end(self) -> Optional[VADEvent]:
        if not self.in_speech:
            return None
        return self._finish()

    def push(self, frame: np.ndarray) -> list[VADEvent]:
        frame = np.asarray(frame, dtype=np.float32).reshape(-1)
        if frame.size == 0:
            return []
        dt = frame.size / float(self.sample_rate)
        rms = float(np.sqrt(np.mean(np.square(frame)) + 1e-12))
        if not self.in_speech:
            self._pre_roll.append(frame)
            if rms < self.threshold:
                return []
            self.in_speech = True
            self._buffer = list(self._pre_roll)
            self._speech_s = dt
            self._silence_s = 0.0
            self._total_s = dt
            return [VADEvent("speech_start")]

        self._buffer.append(frame)
        self._total_s += dt
        if rms >= self.threshold:
            self._speech_s += dt
            self._silence_s = 0.0
        else:
            self._silence_s += dt

        if self._total_s >= self.max_speech_s:
            return [self._finish()]
        if self._silence_s >= self.silence_s:
            if self._speech_s < self.min_speech_s:
                self.reset()
                return [VADEvent("speech_discarded")]
            return [self._finish()]
        return []

    def _finish(self) -> VADEvent:
        audio = (np.concatenate(self._buffer).astype(np.float32)
                 if self._buffer else np.zeros(0, dtype=np.float32))
        event = VADEvent("speech_end", audio, len(audio) / float(self.sample_rate))
        self.reset()
        return event


class MicSource:
    """Blocking 16 kHz mono microphone source; safe to stop from another thread."""

    def __init__(self, sample_rate: int = 16000, block_ms: int = 30,
                 device: Optional[int] = None):
        self.sample_rate = int(sample_rate)
        self.block = max(1, int(sample_rate * block_ms / 1000))
        self.device = device
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=64)
        self._stream = None

    def start(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            if status:
                pass
            try:
                self._queue.put_nowait(np.asarray(indata, dtype=np.float32).reshape(-1).copy())
            except queue.Full:
                pass

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            blocksize=self.block, device=self.device, callback=callback)
        self._stream.start()

    def read(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass


class SherpaKWS:
    """Optional Sherpa-ONNX keyword spotter ("Hey Bota" by default)."""

    def __init__(self, cfg: dict[str, Any]):
        import sherpa_onnx

        model_dir = cfg.get("model_dir") or ""
        keywords = cfg.get("keywords_file") or ""
        if not os.path.isdir(model_dir):
            raise RuntimeError(f"KWS 模型目录不存在: {model_dir}")
        if not os.path.isfile(keywords):
            raise RuntimeError(f"KWS 关键词文件不存在: {keywords}")
        self.keywords = []
        for line in open(keywords, encoding="utf-8"):
            if line.strip() and "@" in line:
                name = line.split("@", 1)[1].strip().replace("_", " ")
                if name not in self.keywords:
                    self.keywords.append(name)
        self.kws = sherpa_onnx.KeywordSpotter(
            tokens=os.path.join(model_dir, "tokens.txt"),
            encoder=os.path.join(model_dir, "encoder.onnx"),
            decoder=os.path.join(model_dir, "decoder.onnx"),
            joiner=os.path.join(model_dir, "joiner.onnx"),
            keywords_file=keywords,
            keywords_score=float(cfg.get("keywords_score", 1.5)),
            keywords_threshold=float(cfg.get("keywords_threshold", 0.25)),
            num_threads=int(cfg.get("num_threads", 2)),
            provider=cfg.get("provider", "cpu"),
        )
        self.stream = self.kws.create_stream()

    def accept(self, frame: np.ndarray) -> Optional[str]:
        self.stream.accept_waveform(16000, np.asarray(frame, dtype=np.float32).reshape(-1))
        while self.kws.is_ready(self.stream):
            self.kws.decode_stream(self.stream)
        result = self.kws.get_result(self.stream)
        if not result:
            return None
        self.kws.reset_stream(self.stream)
        return str(result).replace("_", " ")

    def reset(self) -> None:
        try:
            self.kws.reset_stream(self.stream)
        except Exception:
            pass


class ConversationController:
    def __init__(self, engine: DialogEngine, cfg: dict[str, Any], *,
                 source=None, kws=None, on_event: Optional[Callable[[dict], None]] = None):
        self.engine = engine
        self.cfg = cfg
        wake_cfg = cfg.get("wake") or {}
        self.wake_cfg = wake_cfg
        audio_cfg = cfg.get("audio") or {}
        self.source = source or MicSource(
            sample_rate=int(audio_cfg.get("sample_rate", 16000)),
            block_ms=30)
        self.on_event = on_event
        self.vad = VAD(
            sample_rate=int(audio_cfg.get("sample_rate", 16000)),
            threshold=float(audio_cfg.get("energy_threshold", 0.012)),
            silence_s=float(audio_cfg.get("silence_seconds", 0.8)),
            min_speech_s=float(audio_cfg.get("min_speech_seconds", 0.2)),
            max_speech_s=float(wake_cfg.get("max_utterance_seconds", 15.0)),
        )
        self._state = ConversationState.IDLE
        self._state_since = time.monotonic()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._manual_wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._turn_thread: Optional[threading.Thread] = None
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._seq = 0
        self._subs: list[queue.Queue] = []
        self.last_result: Optional[dict[str, Any]] = None
        self.kws = kws
        self.kws_error = ""
        if self.kws is None:
            try:
                self.kws = SherpaKWS(wake_cfg.get("kws") or {})
            except Exception as exc:
                self.kws_error = str(exc)
                self.kws = None

    # ── public API ───────────────────────────────────────────────────
    @property
    def state(self) -> ConversationState:
        with self._lock:
            return self._state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return False
        self._stop.clear()
        try:
            self.source.start()
        except Exception as exc:
            self._emit("error", stage="mic", text=str(exc))
            return False
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="voice-conversation")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self.engine.cancel()
        try:
            self.source.stop()
        except Exception:
            pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._set_state(ConversationState.IDLE, reason="stopped")

    def run_forever(self) -> None:
        if not self.start():
            return
        try:
            while self.running:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def wake(self) -> None:
        if self.state in (ConversationState.THINKING, ConversationState.SPEAKING):
            self.interrupt()
            return
        if self.state == ConversationState.FOLLOWUP:
            self._begin_listening(reason="manual")
            return
        self._manual_wake.set()

    def interrupt(self) -> None:
        state = self.state
        if state in (ConversationState.THINKING, ConversationState.SPEAKING):
            self.engine.cancel()
            self._vad_reset()
            self._set_state(ConversationState.LISTENING, reason="interrupt")
            self._emit("interrupt", text="已打断，请继续说话")
        elif state == ConversationState.FOLLOWUP:
            self._begin_listening(reason="manual")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._state.value
            events = list(self._events)[-60:]
        return {
            "state": state,
            "running": self.running,
            "kws": bool(self.kws is not None),
            "kws_error": self.kws_error,
            "events": events,
            "last_result": self.last_result,
        }

    def subscribe(self) -> tuple[queue.Queue, list[dict]]:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subs.append(q)
            history = list(self._events)[-40:]
        return q, history

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    # ── loop / states ────────────────────────────────────────────────
    def _loop(self) -> None:
        self._set_state(ConversationState.IDLE, reason="start")
        while not self._stop.is_set():
            frame = self.source.read(timeout=0.1)
            if frame is None:
                self._check_timeout()
                continue
            try:
                self._handle_frame(frame)
            except Exception as exc:
                self._emit("error", stage="conversation", text=str(exc))
                self._set_state(ConversationState.IDLE, reason="error")
        try:
            self.source.stop()
        except Exception:
            pass

    def _handle_frame(self, frame: np.ndarray) -> None:
        state = self.state
        if state == ConversationState.IDLE:
            if self._manual_wake.is_set():
                self._manual_wake.clear()
                self._begin_listening(reason="manual")
                return
            if self.kws is not None and self.kws.accept(frame):
                self._begin_listening(reason="kws")
            return
        if state in (ConversationState.LISTENING, ConversationState.FOLLOWUP):
            for event in self.vad.push(frame):
                if event.kind == "speech_start":
                    if state == ConversationState.FOLLOWUP:
                        self._set_state(ConversationState.LISTENING, reason="followup_speech")
                    self._emit("vad", event="speech_start")
                elif event.kind == "speech_end":
                    self._start_turn(event.audio if event.audio is not None
                                     else np.zeros(0, dtype=np.float32))
                elif event.kind == "speech_discarded":
                    self._emit("vad", event="speech_discarded")
            return
        # THINKING / SPEAKING: half-duplex, deliberately ignore microphone input.

    def _begin_listening(self, reason: str = "manual") -> None:
        self._vad_reset()
        self._set_state(ConversationState.WAKING, reason=reason)
        if str(self.wake_cfg.get("ack", "chirp")) == "chirp":
            play_chirp(float(self.wake_cfg.get("chirp_freq", 880)),
                       int(self.wake_cfg.get("chirp_ms", 120)))
        self._set_state(ConversationState.LISTENING, reason=reason)
        self._emit("wake", text="Hey Bota" if reason == "kws" else "手动唤醒")

    def _start_turn(self, audio: np.ndarray) -> None:
        if audio.size == 0 or self.state not in (ConversationState.LISTENING,
                                                 ConversationState.FOLLOWUP):
            return
        out_dir = os.path.join(VOICE_LAB_DIR, "output", "turns")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"turn_{int(time.time() * 1000)}.wav")
        save_wav(path, audio, int(self.cfg.get("audio", {}).get("sample_rate", 16000)))
        self._set_state(ConversationState.THINKING, reason="speech_end")
        self._emit("turn_start", audio_path=path, duration_s=len(audio) / 16000.0)
        self._turn_thread = threading.Thread(target=self._run_turn, args=(path,),
                                             daemon=True, name="voice-turn")
        self._turn_thread.start()

    def _run_turn(self, path: str) -> None:
        try:
            result = self.engine.handle_audio(path, speak=True, play=None,
                                              stage_cb=self._stage)
        except Exception as exc:
            self._emit("error", stage="turn", text=str(exc))
            self._set_state(ConversationState.IDLE, reason="turn_error")
            return
        self.last_result = result.to_dict()
        self._emit("result", **self.last_result)
        if result.error == "cancelled":
            # interrupt() already moved us to LISTENING.
            return
        if self.state in (ConversationState.THINKING, ConversationState.SPEAKING):
            self._vad_reset()
            self._set_state(ConversationState.FOLLOWUP, reason="answer_done")

    def _stage(self, stage: str) -> None:
        if stage in ("thinking", "transcribing"):
            if self.state in (ConversationState.LISTENING, ConversationState.FOLLOWUP):
                self._set_state(ConversationState.THINKING, reason=stage)
        elif stage == "speaking":
            self._set_state(ConversationState.SPEAKING, reason="tts")

    def _check_timeout(self) -> None:
        elapsed = time.monotonic() - self._state_since
        state = self.state
        if state == ConversationState.LISTENING and not self.vad.in_speech:
            if elapsed > float(self.wake_cfg.get("command_timeout", 8.0)):
                self._set_state(ConversationState.IDLE, reason="listen_timeout")
                self._emit("timeout", text="没有听到指令")
        elif state == ConversationState.FOLLOWUP:
            if elapsed > float(self.wake_cfg.get("followup_timeout", 8.0)):
                self._set_state(ConversationState.IDLE, reason="followup_timeout")

    def _vad_reset(self) -> None:
        self.vad.reset()

    def _set_state(self, state: ConversationState, **fields: Any) -> None:
        with self._lock:
            if self._state == state:
                return
            self._state = state
            self._state_since = time.monotonic()
        self._emit("state", state=state.value, **fields)

    def _emit(self, kind: str, **fields: Any) -> None:
        with self._lock:
            self._seq += 1
            event = {"type": kind, "seq": self._seq, "ts": time.time(), **fields}
            self._events.append(event)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                pass
