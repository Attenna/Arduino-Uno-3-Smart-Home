"""Generate the reproducible ASR test set with edge-tts.

The text is known, so CER can be computed without human labels.  Three voices
plus additive noise cover the main variability axes we care about on a laptop.
Audio is written under ``voice_lab/dataset`` which is git-ignored.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

import numpy as np

from .cases import CASES
from .config import VOICE_LAB_DIR

DATASET_DIR = os.path.join(VOICE_LAB_DIR, "dataset")
VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "yunxi": "zh-CN-YunxiNeural",
    "xiaoyi": "zh-CN-XiaoyiNeural",
}


async def _synthesize(text: str, voice: str, mp3_path: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(mp3_path)


def _to_wav(mp3: str, wav: str) -> None:
    import subprocess

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
                    "-ar", "16000", "-ac", "1", wav], check=True)


def _add_noise(wav: str, out: str, snr_db: float) -> None:
    import soundfile as sf

    data, sample_rate = sf.read(wav, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(data)) + 1e-12))
    noise_rms = rms / (10 ** (snr_db / 20.0))
    noise = np.random.default_rng(20261110).normal(0.0, noise_rms, len(data)).astype(np.float32)
    sf.write(out, np.clip(data + noise, -1.0, 1.0), sample_rate)


def build(voices: list[str], limit: int = 0, with_noise: bool = True) -> dict[str, Any]:
    import soundfile as sf

    os.makedirs(DATASET_DIR, exist_ok=True)
    items: list[dict[str, Any]] = []
    single = [c for c in CASES if len(c["turns"]) == 1]
    if limit:
        single = single[:limit]
    started = time.time()
    for case in single:
        text = case["turns"][0]
        for voice_key in voices:
            voice = VOICES[voice_key]
            stem = f"{case['id']}__{voice_key}"
            wav = os.path.join(DATASET_DIR, stem + ".wav")
            if not os.path.isfile(wav):
                mp3 = wav + ".mp3"
                try:
                    asyncio.run(_synthesize(text, voice, mp3))
                    _to_wav(mp3, wav)
                finally:
                    try:
                        os.remove(mp3)
                    except OSError:
                        pass
            items.append({"case_id": case["id"], "turn": 0, "voice": voice_key,
                          "noise": "clean", "path": os.path.relpath(wav, VOICE_LAB_DIR),
                          "reference": text, "intent": case["intent"],
                          "keywords": case.get("keywords", [])})
            if with_noise and voice_key == voices[0] and case["id"] in (
                    "light_blue", "query_temperature", "fan_speed3", "scene_movie",
                    "light_dim_bedroom", "door_unlock"):
                for snr in (20, 10):
                    noisy = os.path.join(DATASET_DIR, f"{stem}__snr{snr}.wav")
                    if not os.path.isfile(noisy):
                        _add_noise(wav, noisy, snr)
                    items.append({"case_id": case["id"], "turn": 0, "voice": voice_key,
                                  "noise": f"snr{snr}", "path": os.path.relpath(noisy, VOICE_LAB_DIR),
                                  "reference": text, "intent": case["intent"],
                                  "keywords": case.get("keywords", [])})
        print(f"  {case['id']}: {len(voices)} voices", flush=True)
    meta = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sample_rate": 16000,
        "voices": {k: VOICES[k] for k in voices},
        "seconds": round(time.time() - started, 1),
        "items": items,
        "cases": CASES,
    }
    with open(os.path.join(DATASET_DIR, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
    print(f"dataset: {len(items)} files, {meta['seconds']} s -> {DATASET_DIR}")
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 ASR 评测集（edge-tts，文本已知）")
    parser.add_argument("--voices", default="xiaoxiao,yunxi,xiaoyi")
    parser.add_argument("--limit", type=int, default=0, help="只生成前 N 个单轮用例")
    parser.add_argument("--no-noise", action="store_true")
    args = parser.parse_args()
    voices = [v.strip() for v in args.voices.split(",") if v.strip()]
    unknown = [v for v in voices if v not in VOICES]
    if unknown:
        parser.error(f"未知音色: {unknown}")
    build(voices, args.limit, not args.no_noise)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
