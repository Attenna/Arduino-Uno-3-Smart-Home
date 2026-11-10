"""Latency waterfall samples for the report and the web demo.

Runs a few representative turns after warmup, with TTS cache disabled, and
stores the absolute timing marks in ``output/latency_samples.json``.

    python -m voice_lab.bench
    python -m voice_lab.bench --repeats 3 --skip-whisper
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
from typing import Any, Optional

from .config import VOICE_LAB_DIR, load_config
from .dialog import DialogEngine

OUTPUT_DIR = os.path.join(VOICE_LAB_DIR, "output")
DATASET = os.path.join(VOICE_LAB_DIR, "dataset", "light_blue__xiaoxiao.wav")


def _run(cfg: dict[str, Any], kind: str, repeats: int) -> dict[str, Any]:
    engine = DialogEngine(copy.deepcopy(cfg), play_tts=False,
                          tts_enabled=cfg["tts"]["backend"] != "none")
    engine.preload()
    runs = []
    for _ in range(max(1, repeats)):
        if kind == "audio":
            result = engine.handle_audio(DATASET, speak=True, play=False)
        else:
            result = engine.handle_text("把客厅的灯调成蓝色", speak=True, play=False)
        runs.append({
            "timing": result.timing.to_dict(),
            "asr": result.asr.text if result.asr else "",
            "reply": result.reply,
            "tool": result.tool_calls[0].name if result.tool_calls else "",
            "error": result.error,
        })
    # Median of each timing field (TTS network jitter).
    keys = runs[0]["timing"].keys()
    median = {key: statistics.median(r["timing"].get(key, 0) for r in runs) for key in keys}
    return {
        "asr": cfg["asr"]["backend"], "llm": cfg["llm"]["backend"],
        "tts": cfg["tts"]["backend"], "input": kind,
        "runs": runs, "median": median,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="延迟瀑布采样")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--skip-whisper", action="store_true")
    parser.add_argument("--skip-llama", action="store_true")
    args = parser.parse_args(argv)
    base = load_config()
    base["tts"]["cache_dir"] = ""  # honest timing: no cache hits
    samples: dict[str, Any] = {"repeats": args.repeats, "samples": {}}

    scenarios: list[tuple[str, dict[str, Any], str]] = []
    cfg = copy.deepcopy(base); cfg["llm"]["backend"] = "rules"; cfg["asr"]["backend"] = "sherpa"
    scenarios.append(("rules_text_edge", cfg, "text"))
    cfg = copy.deepcopy(base); cfg["llm"]["backend"] = "hybrid"; cfg["asr"]["backend"] = "sherpa"
    scenarios.append(("hybrid_text_edge", cfg, "text"))
    cfg = copy.deepcopy(base); cfg["llm"]["backend"] = "hybrid"; cfg["asr"]["backend"] = "sherpa"
    scenarios.append(("hybrid_audio_edge", cfg, "audio"))
    cfg = copy.deepcopy(base); cfg["llm"]["backend"] = "hybrid"; cfg["asr"]["backend"] = "sherpa"
    cfg["tts"]["backend"] = "sherpa"
    scenarios.append(("hybrid_audio_sherpa_tts", cfg, "audio"))
    if not args.skip_whisper:
        cfg = copy.deepcopy(base); cfg["llm"]["backend"] = "hybrid"; cfg["asr"]["backend"] = "whisper"
        scenarios.append(("hybrid_audio_whisper_edge", cfg, "audio"))
    if not args.skip_llama:
        cfg = copy.deepcopy(base); cfg["llm"]["backend"] = "llama_cpp"; cfg["asr"]["backend"] = "sherpa"
        scenarios.append(("llama_text_edge", cfg, "text"))

    for name, cfg, kind in scenarios:
        print(f"[bench] {name} ({kind})", flush=True)
        try:
            samples["samples"][name] = _run(cfg, kind, args.repeats)
            med = samples["samples"][name]["median"]
            print(f"  ASR {med['asr_ms']:.0f} ms | LLM {med['llm_total_ms']:.0f} ms | "
                  f"首音 {med['tts_first_audio_ms']:.0f} ms | 整轮 {med['total_ms']:.0f} ms",
                  flush=True)
        except Exception as exc:
            samples["samples"][name] = {"error": str(exc)}
            print(f"  failed: {exc}", flush=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "latency_samples.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(samples, handle, ensure_ascii=False, indent=2)
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
