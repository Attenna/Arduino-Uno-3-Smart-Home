"""Microphone capture and audio-file helpers (lazy sounddevice imports)."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Optional

import numpy as np


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())


def record_fixed(seconds: float = 5.0, sample_rate: int = 16000,
                 device: Optional[int] = None) -> np.ndarray:
    import sounddevice as sd

    frames = max(1, int(seconds * sample_rate))
    data = sd.rec(frames, samplerate=sample_rate, channels=1,
                  dtype="float32", device=device)
    sd.wait()
    return np.asarray(data, dtype=np.float32).reshape(-1)


def record_until_silence(max_seconds: float = 8.0, sample_rate: int = 16000,
                         silence_seconds: float = 0.8, threshold: float = 0.012,
                         device: Optional[int] = None) -> np.ndarray:
    """Simple energy VAD: wait for speech, then stop after trailing silence."""
    import sounddevice as sd

    block = int(0.03 * sample_rate)
    chunks: list[np.ndarray] = []
    speaking = False
    silence_start: Optional[float] = None
    started = time.perf_counter()
    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32",
                        blocksize=block, device=device) as stream:
        while time.perf_counter() - started < max_seconds:
            data, _ = stream.read(block)
            frame = np.asarray(data, dtype=np.float32).reshape(-1)
            rms = float(np.sqrt(np.mean(np.square(frame)) + 1e-12))
            now = time.perf_counter()
            if rms >= threshold:
                speaking = True
                silence_start = None
                chunks.append(frame.copy())
            elif speaking:
                chunks.append(frame.copy())
                if silence_start is None:
                    silence_start = now
                elif now - silence_start >= silence_seconds:
                    break
            elif now - started > 1.5:
                # No speech in the first 1.5 s: give up instead of recording silence.
                break
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32)


def save_wav(path: str, samples: np.ndarray, sample_rate: int = 16000) -> str:
    import soundfile as sf

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sf.write(path, np.asarray(samples, dtype=np.float32), sample_rate)
    return path


def convert_to_wav16k(src: str, dst: Optional[str] = None) -> str:
    """Convert browser WebM/Opus or any ffmpeg-readable file to 16 kHz mono WAV."""
    dst = dst or (os.path.splitext(src)[0] + ".16k.wav")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("未找到 ffmpeg，无法解码浏览器录音")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                    "-ar", "16000", "-ac", "1", dst], check=True)
    return dst


def play_wav(path: str) -> None:
    import sounddevice as sd
    import soundfile as sf

    data, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    sd.play(data, sample_rate, blocking=True)
