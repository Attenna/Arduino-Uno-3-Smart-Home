"""TTS adapters and a sentence-level streaming player.

Default is edge-tts (natural voice, ~0.7-1.3 s to a short sentence), with
Sherpa-ONNX VITS as the fully offline fallback and an optional CosyVoice2 HTTP
adapter.  The player synthesises sentence by sentence so the first sentence can
start while the LLM is still writing the rest of the answer.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Optional

import numpy as np

from .config import read_api_key
from .schemas import TTSResult

_SENTENCE_END = re.compile(r"[。！？!?；;\n]+")


def _cache_key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]


def _to_wav(src: str, dst: str, sample_rate: int = 24000) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("未找到 ffmpeg，无法解码 TTS 音频")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                    "-ar", str(sample_rate), "-ac", "1", dst], check=True)


def _duration(path: str) -> tuple[float, int]:
    import soundfile as sf

    info = sf.info(path)
    return float(info.duration), int(info.samplerate)


class BaseTTS:
    backend = "base"

    def synthesize(self, text: str, out_path: Optional[str] = None) -> TTSResult:
        raise NotImplementedError

    def close(self) -> None:
        pass


class EdgeTTS(BaseTTS):
    backend = "edge"

    def __init__(self, cfg: dict[str, Any], cache_dir: str = ""):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.voice = cfg.get("voice", "zh-CN-XiaoxiaoNeural")
        self.rate = cfg.get("rate", "+0%")
        self.volume = cfg.get("volume", "+0%")

    async def _synth_mp3(self, text: str, path: str) -> float:
        import edge_tts

        started = time.perf_counter()
        first = None
        chunks = []
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, volume=self.volume)
        async for chunk in communicate.stream():
            if chunk.get("type") != "audio":
                continue
            if first is None:
                first = (time.perf_counter() - started) * 1000.0
            data = chunk.get("data") or b""
            if data:
                chunks.append(data)
        with open(path, "wb") as handle:
            handle.write(b"".join(chunks))
        return first or 0.0

    def synthesize(self, text: str, out_path: Optional[str] = None) -> TTSResult:
        text = (text or "").strip()
        if not text:
            return TTSResult(self.backend, text, error="空文本")
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
            key = _cache_key(self.backend, self.voice, self.rate, self.volume, text)
            wav = os.path.join(self.cache_dir, key + ".wav")
            if os.path.isfile(wav) and os.path.getsize(wav) > 44:
                duration, sample_rate = _duration(wav)
                return TTSResult(self.backend, text, wav, total_ms=1.0,
                                 duration_s=duration, sample_rate=sample_rate)
        else:
            wav = out_path or os.path.join(
                os.environ.get("TEMP", "."), "voice_lab_" + _cache_key(text) + ".wav")
        mp3 = wav + ".mp3"
        os.makedirs(os.path.dirname(os.path.abspath(wav)), exist_ok=True)
        started = time.perf_counter()
        try:
            first_ms = asyncio.run(self._synth_mp3(text, mp3))
            _to_wav(mp3, wav)
        finally:
            try:
                os.remove(mp3)
            except OSError:
                pass
        total_ms = (time.perf_counter() - started) * 1000.0
        duration, sample_rate = _duration(wav)
        return TTSResult(self.backend, text, wav, first_audio_ms=first_ms,
                         total_ms=total_ms, duration_s=duration,
                         sample_rate=sample_rate)


class SherpaTTS(BaseTTS):
    backend = "sherpa"

    def __init__(self, cfg: dict[str, Any], cache_dir: str = ""):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self._tts = None

    def _load(self):
        if self._tts is not None:
            return self._tts
        import sherpa_onnx

        d = self.cfg["model_dir"]
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=os.path.join(d, "model.onnx"),
            tokens=os.path.join(d, "tokens.txt"),
            lexicon=os.path.join(d, "lexicon.txt")
            if os.path.isfile(os.path.join(d, "lexicon.txt")) else "",
            dict_dir=os.path.join(d, "dict")
            if os.path.isdir(os.path.join(d, "dict")) else "",
        )
        model = sherpa_onnx.OfflineTtsModelConfig(
            vits=vits, num_threads=int(self.cfg.get("num_threads", 2)),
            provider=self.cfg.get("provider", "cpu"))
        config = sherpa_onnx.OfflineTtsConfig(model=model, max_num_sentences=2)
        if not config.validate():
            raise RuntimeError(f"Sherpa TTS 配置校验失败: {d}")
        self._tts = sherpa_onnx.OfflineTts(config)
        return self._tts

    def synthesize(self, text: str, out_path: Optional[str] = None) -> TTSResult:
        text = (text or "").strip()
        if not text:
            return TTSResult(self.backend, text, error="空文本")
        tts = self._load()
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
            key = _cache_key(self.backend, str(self.cfg.get("speaker_id", 0)),
                             str(self.cfg.get("speed", 1.0)), text)
            wav = os.path.join(self.cache_dir, key + ".wav")
            if os.path.isfile(wav) and os.path.getsize(wav) > 44:
                duration, sample_rate = _duration(wav)
                return TTSResult(self.backend, text, wav, total_ms=1.0,
                                 duration_s=duration, sample_rate=sample_rate)
        else:
            wav = out_path or os.path.join(
                os.environ.get("TEMP", "."), "voice_lab_" + _cache_key(text) + ".wav")
        started = time.perf_counter()
        audio = tts.generate(text, sid=int(self.cfg.get("speaker_id", 0)),
                             speed=float(self.cfg.get("speed", 1.0)))
        samples = np.asarray(audio.samples, dtype=np.float32)
        import soundfile as sf
        os.makedirs(os.path.dirname(os.path.abspath(wav)), exist_ok=True)
        sf.write(wav, samples, audio.sample_rate)
        total_ms = (time.perf_counter() - started) * 1000.0
        return TTSResult(self.backend, text, wav, first_audio_ms=total_ms,
                         total_ms=total_ms, duration_s=len(samples) / audio.sample_rate,
                         sample_rate=audio.sample_rate)


class CosyVoiceTTS(BaseTTS):
    """SiliconFlow-compatible /audio/speech adapter (CosyVoice2)."""

    backend = "cosyvoice"

    def __init__(self, cfg: dict[str, Any], cache_dir: str = ""):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.base_url = str(cfg.get("base_url") or "").rstrip("/")
        self.api_key = read_api_key(cfg)

    def synthesize(self, text: str, out_path: Optional[str] = None) -> TTSResult:
        text = (text or "").strip()
        if not text:
            return TTSResult(self.backend, text, error="空文本")
        if not self.api_key:
            raise RuntimeError("未配置 CosyVoice API Key")
        import httpx

        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
            key = _cache_key(self.backend, self.cfg.get("voice", ""), text)
            wav = os.path.join(self.cache_dir, key + ".wav")
            if os.path.isfile(wav) and os.path.getsize(wav) > 44:
                duration, sample_rate = _duration(wav)
                return TTSResult(self.backend, text, wav, total_ms=1.0,
                                 duration_s=duration, sample_rate=sample_rate)
        else:
            wav = out_path or os.path.join(
                os.environ.get("TEMP", "."), "voice_lab_" + _cache_key(text) + ".wav")
        started = time.perf_counter()
        payload = {
            "model": self.cfg.get("model", "FunAudioLLM/CosyVoice2-0.5B"),
            "input": text,
            "voice": self.cfg.get("voice", "anna"),
            "response_format": self.cfg.get("response_format", "mp3"),
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=float(self.cfg.get("timeout_s", 60))) as client:
            response = client.post(f"{self.base_url}/audio/speech", json=payload, headers=headers)
            response.raise_for_status()
            raw = response.content
        suffix = ".mp3" if payload["response_format"] == "mp3" else ".wav"
        tmp = wav + suffix
        with open(tmp, "wb") as handle:
            handle.write(raw)
        try:
            _to_wav(tmp, wav)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        total_ms = (time.perf_counter() - started) * 1000.0
        duration, sample_rate = _duration(wav)
        return TTSResult(self.backend, text, wav, first_audio_ms=total_ms,
                         total_ms=total_ms, duration_s=duration,
                         sample_rate=sample_rate)


class NullTTS(BaseTTS):
    backend = "none"

    def synthesize(self, text: str, out_path: Optional[str] = None) -> TTSResult:
        return TTSResult(self.backend, text, total_ms=0.0, first_audio_ms=0.0)


def build_tts(cfg: dict[str, Any], backend: Optional[str] = None,
              cache_dir: Optional[str] = None) -> BaseTTS:
    backend = (backend or cfg.get("backend") or "edge").lower()
    if cache_dir is None:
        cache_dir = str(cfg.get("cache_dir") or "")
    if backend == "edge":
        return EdgeTTS(cfg.get("edge") or {}, cache_dir)
    if backend == "sherpa":
        return SherpaTTS(cfg.get("sherpa") or {}, cache_dir)
    if backend in ("cosyvoice", "cosyvoice2"):
        return CosyVoiceTTS(cfg.get("cosyvoice") or {}, cache_dir)
    if backend in ("none", "off", "null"):
        return NullTTS()
    raise RuntimeError(f"未知 TTS 后端: {backend}")


class SentenceSplitter:
    """Accumulates LLM tokens and emits complete sentences."""

    def __init__(self, max_chars: int = 60):
        self.buffer = ""
        self.max_chars = max_chars

    def feed(self, token: str) -> list[str]:
        if not token:
            return []
        self.buffer += token
        sentences: list[str] = []
        while True:
            match = _SENTENCE_END.search(self.buffer)
            if not match:
                # Keep latency low on long clauses without punctuation.
                if len(self.buffer) >= self.max_chars:
                    cut = max(self.buffer.rfind("，", 0, self.max_chars),
                              self.buffer.rfind(",", 0, self.max_chars))
                    if cut > 8:
                        sentences.append(self.buffer[:cut + 1].strip())
                        self.buffer = self.buffer[cut + 1:]
                        continue
                break
            sentence = self.buffer[:match.end()].strip()
            self.buffer = self.buffer[match.end():]
            if sentence:
                sentences.append(sentence)
        return sentences

    def flush(self) -> list[str]:
        rest = self.buffer.strip()
        self.buffer = ""
        return [rest] if rest else []

    def reset(self) -> None:
        self.buffer = ""


class TTSPlayer:
    """Background sentence synthesizer/player with first-audio timing."""

    def __init__(self, tts: BaseTTS, play: bool = True):
        self.tts = tts
        self.play = play
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._done.set()
        self._first_audio_ms: Optional[float] = None
        self._started_at: Optional[float] = None
        self._last_error = ""
        self._thread = threading.Thread(target=self._run, daemon=True, name="tts-worker")
        self._thread.start()

    def start(self) -> None:
        self._done.clear()
        self._first_audio_ms = None
        self._started_at = time.perf_counter()

    def feed(self, text: str) -> None:
        for sentence in text.split("\x00"):
            if sentence.strip():
                self._queue.put(sentence.strip())

    def feed_sentences(self, sentences: list[str]) -> None:
        for sentence in sentences:
            if sentence.strip():
                self._queue.put(sentence.strip())

    def clear(self) -> None:
        """Drop queued sentences without stopping the worker (tool-call turn)."""
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    def flush(self) -> None:
        self._queue.put(None)

    def wait_done(self, timeout: Optional[float] = None) -> bool:
        return self._done.wait(timeout or 120.0)

    def stop(self) -> None:
        self._stop.set()
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        self._queue.put(None)
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    @property
    def first_audio_ms(self) -> float:
        return float(self._first_audio_ms or 0.0)

    @property
    def last_error(self) -> str:
        return self._last_error

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            try:
                if self._stop.is_set():
                    continue
                result = self.tts.synthesize(item)
                if result.error:
                    self._last_error = result.error
                    continue
                if self._first_audio_ms is None and self._started_at is not None:
                    self._first_audio_ms = (time.perf_counter() - self._started_at) * 1000.0
                if self.play and result.audio_path:
                    self._play(result.audio_path)
            except Exception as exc:
                self._last_error = str(exc)
            finally:
                self._queue.task_done()
        self._done.set()

    @staticmethod
    def _play(path: str) -> None:
        import sounddevice as sd
        import soundfile as sf

        data, sample_rate = sf.read(path, dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        sd.play(data, sample_rate, blocking=True)
