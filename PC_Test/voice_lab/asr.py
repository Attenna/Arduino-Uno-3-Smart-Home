"""ASR adapters: Sherpa-ONNX streaming Zipformer and OpenAI Whisper.

Both return the same :class:`ASRResult`, so the dialogue layer and the
evaluator can swap engines without special cases.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from typing import Any, Optional

import numpy as np

from .schemas import ASRResult


class ASRError(RuntimeError):
    pass


def _text_of(value: Any) -> str:
    """Sherpa's Python binding has returned str, list and object over versions."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "".join(_text_of(v) for v in value).strip()
    if hasattr(value, "text"):
        return str(value.text).strip()
    return str(value).strip()


# Domain lexicon fixes for errors repeatedly observed on the streaming model.
# Kept deliberately short and only applied to smart-home-shaped phrases.
_ASR_FIXES = (
    ("我是灯", "卧室灯"),
    ("我室灯", "卧室灯"),
    ("主卧灯", "卧室灯"),
    ("风风尚晒晒", "风扇"),
    ("风尚晒晒", "风扇"),
    ("空调调调调", "空调调"),
    ("空调调调", "空调调"),
)


def correct_asr_text(text: str) -> str:
    for wrong, right in _ASR_FIXES:
        text = text.replace(wrong, right)
    return text


def normalize_text(text: str) -> str:
    """Remove punctuation/spaces and convert Traditional Chinese if opencc exists."""
    text = (text or "").strip()
    try:
        from opencc import OpenCC  # type: ignore
        text = OpenCC("t2s").convert(text)
    except Exception:
        pass
    text = re.sub(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()《》]", "", text)
    return text


def _load_wave(path: str, sample_rate: int = 16000) -> np.ndarray:
    """Read any audio file as mono float32 at ``sample_rate``.

    soundfile handles WAV/FLAC natively; for MP3/WebM/Opus we shell out to
    ffmpeg, which is already a repository prerequisite for the camera tools.
    """
    import soundfile as sf

    suffix = os.path.splitext(path)[1].lower()
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=False)
    except Exception:
        data, sr = None, None
    if data is None:
        if not shutil.which("ffmpeg"):
            raise ASRError(f"无法读取音频且未找到 ffmpeg: {path}")
        tmp = path + ".asr16k.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-ar", str(sample_rate), "-ac", "1", tmp],
                       check=True)
        data, sr = sf.read(tmp, dtype="float32", always_2d=False)
        try:
            os.remove(tmp)
        except OSError:
            pass
    data = np.asarray(data, dtype=np.float32)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != sample_rate:
        # Linear resampling is enough for 16 kHz speech; avoids a librosa dep.
        duration = len(data) / float(sr)
        target = int(round(duration * sample_rate))
        if target <= 0:
            return np.zeros(0, dtype=np.float32)
        x_old = np.linspace(0.0, duration, num=len(data), endpoint=False)
        x_new = np.linspace(0.0, duration, num=target, endpoint=False)
        data = np.interp(x_new, x_old, data).astype(np.float32)
    return np.clip(data, -1.0, 1.0)


class BaseASR:
    backend = "base"

    def transcribe_file(self, path: str) -> ASRResult:
        raise NotImplementedError


class SherpaASR(BaseASR):
    backend = "sherpa"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._recognizer = None
        self._sample_rate = 16000

    def _load(self):
        if self._recognizer is not None:
            return self._recognizer
        import sherpa_onnx

        d = self.cfg["model_dir"]
        if not os.path.isdir(d):
            raise ASRError(f"Sherpa ASR 模型目录不存在: {d}")

        def pick(*names: str) -> str:
            for name in names:
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    return path
            return os.path.join(d, names[0])

        joiner = pick("joiner.onnx", "joiner.int8.onnx")
        common = dict(
            tokens=os.path.join(d, "tokens.txt"),
            encoder=pick("encoder.onnx", "encoder.int8.onnx"),
            decoder=os.path.join(d, "decoder.onnx"),
            num_threads=int(self.cfg.get("num_threads", 4)),
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=float(self.cfg.get("rule1_silence", 2.4)),
            rule2_min_trailing_silence=float(self.cfg.get("rule2_silence", 1.2)),
            rule3_min_utterance_length=float(self.cfg.get("rule3_utt_len", 20.0)),
            provider=self.cfg.get("provider", "cpu"),
        )
        hotwords = self.cfg.get("hotwords_file")
        if hotwords and os.path.isfile(hotwords):
            common.update(
                hotwords_file=hotwords,
                hotwords_score=float(self.cfg.get("hotwords_score", 2.0)),
                decoding_method="modified_beam_search",
                max_active_paths=int(self.cfg.get("max_active_paths", 4)),
            )
        if os.path.isfile(joiner):
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                joiner=joiner, **common)
        else:
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(**common)
        return self._recognizer

    def transcribe_file(self, path: str) -> ASRResult:
        audio = _load_wave(path, self._sample_rate)
        duration = len(audio) / float(self._sample_rate)
        recognizer = self._load()
        stream = recognizer.create_stream()
        started = time.perf_counter()
        chunk = 1600
        for offset in range(0, len(audio), chunk):
            stream.accept_waveform(self._sample_rate, audio[offset:offset + chunk])
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
        text = _text_of(recognizer.get_result(stream))
        elapsed = (time.perf_counter() - started) * 1000.0
        return ASRResult(text=normalize_text(correct_asr_text(text)), backend=self.backend,
                         latency_ms=elapsed, audio_duration_s=duration,
                         rtf=(elapsed / 1000.0 / duration) if duration else 0.0,
                         audio_path=path)


class FasterWhisperASR(BaseASR):
    """CTranslate2 Whisper (faster-whisper): int8 CPU, low memory, ~1/2 latency."""

    backend = "faster_whisper"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # pragma: no cover - optional extra
            raise ASRError("未安装 faster-whisper，请先 pip install faster-whisper") from exc
        model_dir = self.cfg.get("model_dir")
        if model_dir and os.path.isdir(model_dir):
            target = model_dir
        else:
            target = self.cfg.get("model", "small")
            root = self.cfg.get("download_root")
            if root:
                os.makedirs(root, exist_ok=True)
        self._model = WhisperModel(
            target,
            device=self.cfg.get("device", "cpu"),
            compute_type=self.cfg.get("compute_type", "int8"),
            cpu_threads=int(self.cfg.get("cpu_threads", 8)),
            num_workers=int(self.cfg.get("num_workers", 1)),
            download_root=self.cfg.get("download_root") if not (
                model_dir and os.path.isdir(model_dir)) else None,
        )
        return self._model

    def transcribe_file(self, path: str) -> ASRResult:
        model = self._load()
        started = time.perf_counter()
        segments, info = model.transcribe(
            path,
            language=self.cfg.get("language", "zh"),
            beam_size=int(self.cfg.get("beam_size", 1)),
            vad_filter=bool(self.cfg.get("vad_filter", True)),
            condition_on_previous_text=False,
        )
        text = "".join(segment.text for segment in segments)
        elapsed = (time.perf_counter() - started) * 1000.0
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        if not duration:
            try:
                import soundfile as sf
                duration = float(sf.info(path).duration)
            except Exception:
                duration = 0.0
        return ASRResult(text=normalize_text(correct_asr_text(text)),
                         backend=self.backend, latency_ms=elapsed,
                         audio_duration_s=duration,
                         rtf=(elapsed / 1000.0 / duration) if duration else 0.0,
                         audio_path=path)


class WhisperASR(BaseASR):
    backend = "whisper"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import whisper  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional extra
            raise ASRError("未安装 openai-whisper，请先 pip install openai-whisper") from exc
        path = self.cfg.get("download_root") or None
        if path:
            os.makedirs(path, exist_ok=True)
        self._model = whisper.load_model(
            self.cfg.get("model", "small"),
            download_root=path,
            device=self.cfg.get("device", "cpu"),
        )
        return self._model

    def transcribe_file(self, path: str) -> ASRResult:
        import soundfile as sf

        try:
            info = sf.info(path)
            duration = float(info.duration)
        except Exception:
            duration = 0.0
        model = self._load()
        started = time.perf_counter()
        result = model.transcribe(
            path,
            language=self.cfg.get("language", "zh"),
            fp16=bool(self.cfg.get("fp16", False)),
            beam_size=int(self.cfg.get("beam_size", 1)),
            condition_on_previous_text=False,
            verbose=False,
        )
        elapsed = (time.perf_counter() - started) * 1000.0
        text = normalize_text(correct_asr_text(result.get("text", "")))
        return ASRResult(text=text, backend=self.backend, latency_ms=elapsed,
                         audio_duration_s=duration,
                         rtf=(elapsed / 1000.0 / duration) if duration else 0.0,
                         audio_path=path)


def build_asr(cfg: dict[str, Any], backend: Optional[str] = None) -> BaseASR:
    backend = (backend or cfg.get("backend") or "sherpa").lower()
    if backend == "sherpa":
        return SherpaASR(cfg.get("sherpa") or cfg)
    if backend in ("faster_whisper", "faster-whisper", "ct2"):
        return FasterWhisperASR(cfg.get("faster_whisper") or cfg)
    if backend == "whisper":
        return WhisperASR(cfg.get("whisper") or cfg)
    raise ASRError(f"未知 ASR 后端: {backend}")
