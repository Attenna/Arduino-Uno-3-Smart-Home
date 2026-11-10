"""Reproducible accuracy/latency evaluation for the cascade.

    python -m voice_lab.eval --all
    python -m voice_lab.eval --asr-backends sherpa,whisper --limit 30
    python -m voice_lab.eval --llm-backends rules,hybrid,llama_cpp
    python -m voice_lab.eval --tts-backends edge,sherpa

Results are written to ``voice_lab/output/*.json``.  Models, audio and caches
remain git-ignored; copy the JSON/figures into the report package.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import time
from typing import Any, Optional

from .asr import build_asr
from .cases import CASES, get_path
from .config import VOICE_LAB_DIR, load_config
from .dialog import DialogEngine
from .metrics import (cer, exact_match, keyword_recall, safe_div, summarize,
                      tool_match)
from .tts import build_tts

OUTPUT_DIR = os.path.join(VOICE_LAB_DIR, "output")
DATASET_META = os.path.join(VOICE_LAB_DIR, "dataset", "meta.json")


def _ensure_output() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _save(name: str, data: Any) -> str:
    _ensure_output()
    path = os.path.join(OUTPUT_DIR, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    print(f"  -> {path}")
    return path


def _load_meta() -> dict[str, Any]:
    if not os.path.isfile(DATASET_META):
        raise SystemExit("缺少评测集：先运行 python -m voice_lab.make_dataset")
    with open(DATASET_META, encoding="utf-8") as handle:
        return json.load(handle)


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(VOICE_LAB_DIR, path)


def _check_state(state: dict[str, Any], assertions: list[list[Any]]) -> tuple[bool, list[dict]]:
    details = []
    ok = True
    for path, expected in assertions or []:
        actual = get_path(state, path)
        match = actual == expected
        ok = ok and match
        details.append({"path": path, "expected": expected, "actual": actual, "ok": match})
    return ok, details


def run_asr(cfg: dict[str, Any], backends: list[str], limit: int = 0) -> dict[str, Any]:
    meta = _load_meta()
    items = list(meta.get("items") or [])
    if limit:
        items = items[:limit]
    if not items:
        return {"error": "empty dataset"}
    result: dict[str, Any] = {"dataset": os.path.relpath(DATASET_META, VOICE_LAB_DIR),
                              "items": len(items), "backends": {}}
    for backend in backends:
        print(f"[ASR] {backend}  ({len(items)} files)")
        asr = build_asr(cfg["asr"], backend)
        try:
            asr.transcribe_file(_abs(items[0]["path"]))  # warm up model load
        except Exception as exc:
            result["backends"][backend] = {"error": str(exc)}
            print(f"  failed: {exc}")
            continue
        rows = []
        for item in items:
            try:
                r = asr.transcribe_file(_abs(item["path"]))
                rows.append({
                    "case_id": item["case_id"], "voice": item["voice"],
                    "noise": item["noise"], "reference": item["reference"],
                    "hypothesis": r.text, "cer": cer(item["reference"], r.text),
                    "exact": exact_match(item["reference"], r.text),
                    "keyword_recall": keyword_recall(item.get("keywords") or [], r.text),
                    "latency_ms": r.latency_ms, "audio_duration_s": r.audio_duration_s,
                    "rtf": r.rtf,
                })
            except Exception as exc:
                rows.append({"case_id": item["case_id"], "voice": item["voice"],
                             "noise": item["noise"], "reference": item["reference"],
                             "hypothesis": "", "cer": 1.0, "exact": False,
                             "keyword_recall": 0.0, "error": str(exc),
                             "latency_ms": 0.0, "audio_duration_s": 0.0, "rtf": 0.0})
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row['voice']}/{row['noise']}"
            groups.setdefault(key, []).append(row)
        summary = {
            "cer": summarize(row["cer"] for row in rows),
            "exact": summarize(1.0 if row["exact"] else 0.0 for row in rows),
            "keyword_recall": summarize(row["keyword_recall"] for row in rows),
            "latency_ms": summarize(row["latency_ms"] for row in rows),
            "rtf": summarize(row["rtf"] for row in rows),
            "groups": {
                key: {
                    "n": len(group),
                    "cer": summarize(r["cer"] for r in group),
                    "exact": summarize(1.0 if r["exact"] else 0.0 for r in group),
                    "latency_ms": summarize(r["latency_ms"] for r in group),
                } for key, group in groups.items()
            },
        }
        result["backends"][backend] = {"summary": summary, "rows": rows}
        print(f"  CER={summary['cer']['mean']:.3f}  exact={summary['exact']['mean']*100:.1f}%  "
              f"latency={summary['latency_ms']['mean']:.0f} ms  RTF={summary['rtf']['mean']:.2f}")
    _save("eval_asr.json", result)
    return result


def _case_detail(engine: DialogEngine, case: dict[str, Any]) -> dict[str, Any]:
    engine.reset()
    turns = []
    for index, text in enumerate(case["turns"]):
        result = engine.handle_text(text, speak=False)
        expected = (case.get("expect_turns") or [])[index]
        actual = result.tool_calls[0] if result.tool_calls else None
        name_ok, args_ok = tool_match(
            expected,
            actual.name if actual else "",
            actual.arguments if actual else {},
        )
        turns.append({
            "text": text, "reply": result.reply,
            "actual_tool": actual.to_dict() if actual else None,
            "expected_tool": expected,
            "name_ok": name_ok, "args_ok": args_ok,
            "reply_text": result.reply,
            "latency_ms": result.timing.total_ms,
            "llm_first_token_ms": result.timing.llm_first_token_ms,
            "llm_total_ms": result.timing.llm_total_ms,
            "tool_ms": result.timing.tool_ms,
            "error": result.error,
        })
    state_ok, state_details = _check_state(engine.home.snapshot(),
                                           case.get("expect_state") or [])
    success = all(t["name_ok"] and t["args_ok"] for t in turns) and state_ok
    return {
        "id": case["id"], "intent": case.get("intent"), "turns": turns,
        "state_ok": state_ok, "state_details": state_details,
        "success": success,
        "latency_ms": sum(t["latency_ms"] for t in turns),
    }


def run_dialog(cfg: dict[str, Any], backends: list[str], limit: int = 0) -> dict[str, Any]:
    cases = CASES[:limit] if limit else CASES
    result: dict[str, Any] = {"cases": len(cases), "backends": {}}
    for backend in backends:
        print(f"[Dialog] {backend}  ({len(cases)} cases)")
        local = copy.deepcopy(cfg)
        local["llm"]["backend"] = backend
        engine = DialogEngine(local, tts_enabled=False, play_tts=False)
        try:
            engine.handle_text("你好", speak=False)  # warm up LLM/model load
        except Exception as exc:
            print(f"  warmup failed: {exc}")
        rows = []
        for case in cases:
            try:
                rows.append(_case_detail(engine, case))
            except Exception as exc:
                rows.append({"id": case["id"], "intent": case.get("intent"),
                             "turns": [], "success": False, "latency_ms": 0.0,
                             "error": str(exc)})
        turn_rows = [t for row in rows for t in row.get("turns", [])]
        summary = {
            "name_acc": safe_div(sum(1 for t in turn_rows if t["name_ok"]), len(turn_rows)),
            "args_acc": safe_div(sum(1 for t in turn_rows if t["args_ok"]), len(turn_rows)),
            "turn_success": safe_div(sum(1 for t in turn_rows if t["name_ok"] and t["args_ok"]),
                                     len(turn_rows)),
            "case_success": safe_div(sum(1 for r in rows if r.get("success")), len(rows)),
            "latency_ms": summarize(r["latency_ms"] for r in turn_rows),
            "llm_first_token_ms": summarize(t["llm_first_token_ms"] for t in turn_rows),
            "llm_total_ms": summarize(t["llm_total_ms"] for t in turn_rows),
        }
        by_intent: dict[str, list[bool]] = {}
        for row in rows:
            by_intent.setdefault(str(row.get("intent")), []).append(bool(row.get("success")))
        summary["by_intent"] = {
            key: {"n": len(values), "success": safe_div(sum(values), len(values))}
            for key, values in by_intent.items()
        }
        result["backends"][backend] = {"summary": summary, "rows": rows}
        print(f"  name={summary['name_acc']*100:.1f}%  args={summary['args_acc']*100:.1f}%  "
              f"case={summary['case_success']*100:.1f}%  "
              f"latency={summary['latency_ms']['mean']:.0f} ms")
    _save("eval_dialog.json", result)
    return result


def run_e2e(cfg: dict[str, Any], asr_backend: str, llm_backends: list[str],
            limit: int = 0) -> dict[str, Any]:
    meta = _load_meta()
    items = [item for item in meta.get("items") or []
             if item["voice"] == "xiaoxiao" and item["noise"] == "clean"]
    by_case = {item["case_id"]: item for item in items}
    cases = [case for case in CASES if len(case["turns"]) == 1 and case["id"] in by_case]
    if limit:
        cases = cases[:limit]
    result: dict[str, Any] = {"cases": len(cases), "asr": asr_backend, "backends": {}}
    for llm_backend in llm_backends:
        print(f"[E2E] ASR={asr_backend} LLM={llm_backend}  ({len(cases)} cases)")
        local = copy.deepcopy(cfg)
        local["asr"]["backend"] = asr_backend
        local["llm"]["backend"] = llm_backend
        engine = DialogEngine(local, tts_enabled=False, play_tts=False)
        try:
            engine.handle_audio(_abs(by_case[cases[0]["id"]]["path"]), speak=False)
        except Exception as exc:
            print(f"  warmup failed: {exc}")
        rows = []
        for case in cases:
            item = by_case[case["id"]]
            try:
                r = engine.handle_audio(_abs(item["path"]), speak=False)
                expected = (case.get("expect_turns") or [{}])[0]
                actual = r.tool_calls[0] if r.tool_calls else None
                name_ok, args_ok = tool_match(expected,
                                              actual.name if actual else "",
                                              actual.arguments if actual else {})
                state_ok, state_details = _check_state(
                    engine.home.snapshot(), case.get("expect_state") or [])
                rows.append({
                    "id": case["id"], "reference": item["reference"],
                    "asr_text": r.asr.text if r.asr else "",
                    "asr_cer": cer(item["reference"], r.asr.text if r.asr else ""),
                    "actual_tool": actual.to_dict() if actual else None,
                    "expected_tool": expected, "name_ok": name_ok, "args_ok": args_ok,
                    "state_ok": state_ok, "state_details": state_details,
                    "success": bool(name_ok and args_ok and state_ok),
                    "asr_ms": r.timing.asr_ms, "llm_ms": r.timing.llm_total_ms,
                    "total_ms": r.timing.total_ms, "error": r.error,
                })
            except Exception as exc:
                rows.append({"id": case["id"], "success": False, "error": str(exc),
                             "asr_cer": 1.0, "total_ms": 0.0, "asr_ms": 0.0,
                             "llm_ms": 0.0})
        summary = {
            "asr_cer": summarize(r["asr_cer"] for r in rows),
            "task_success": safe_div(sum(1 for r in rows if r.get("success")), len(rows)),
            "asr_ms": summarize(r["asr_ms"] for r in rows),
            "llm_ms": summarize(r["llm_ms"] for r in rows),
            "total_ms": summarize(r["total_ms"] for r in rows),
        }
        result["backends"][f"{asr_backend}+{llm_backend}"] = {
            "summary": summary, "rows": rows}
        print(f"  CER={summary['asr_cer']['mean']:.3f}  task={summary['task_success']*100:.1f}%  "
              f"total={summary['total_ms']['mean']:.0f} ms")
    _save("eval_e2e.json", result)
    return result


def run_tts(cfg: dict[str, Any], backends: list[str], limit: int = 0) -> dict[str, Any]:
    sentences = []
    for case in CASES:
        text = case["turns"][0]
        if text not in sentences:
            sentences.append(text)
    if limit:
        sentences = sentences[:limit]
    result: dict[str, Any] = {"sentences": len(sentences), "backends": {}}
    for backend in backends:
        print(f"[TTS] {backend}  ({len(sentences)} sentences)")
        tts = build_tts(cfg["tts"], backend, cache_dir="")  # no cache: honest timing
        try:
            tts.synthesize(sentences[0])
        except Exception as exc:
            result["backends"][backend] = {"error": str(exc)}
            print(f"  failed: {exc}")
            continue
        rows = []
        for text in sentences:
            try:
                r = tts.synthesize(text)
                rows.append({"text": text, "first_audio_ms": r.first_audio_ms,
                             "total_ms": r.total_ms, "duration_s": r.duration_s,
                             "rtf": safe_div(r.total_ms / 1000.0, r.duration_s),
                             "error": r.error})
            except Exception as exc:
                rows.append({"text": text, "first_audio_ms": 0.0, "total_ms": 0.0,
                             "duration_s": 0.0, "rtf": 0.0, "error": str(exc)})
        summary = {
            "first_audio_ms": summarize(r["first_audio_ms"] for r in rows),
            "total_ms": summarize(r["total_ms"] for r in rows),
            "duration_s": summarize(r["duration_s"] for r in rows),
            "rtf": summarize(r["rtf"] for r in rows),
            "errors": sum(1 for r in rows if r.get("error")),
        }
        result["backends"][backend] = {"summary": summary, "rows": rows}
        print(f"  first={summary['first_audio_ms']['mean']:.0f} ms  "
              f"total={summary['total_ms']['mean']:.0f} ms  RTF={summary['rtf']['mean']:.2f}")
    _save("eval_tts.json", result)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="语音对话级联评测")
    parser.add_argument("--config", default=None)
    parser.add_argument("--asr-backends", default="sherpa")
    parser.add_argument("--llm-backends", default="rules,hybrid")
    parser.add_argument("--tts-backends", default="edge")
    parser.add_argument("--limit", type=int, default=0, help="ASR/Dialog 用例上限")
    parser.add_argument("--e2e-limit", type=int, default=0)
    parser.add_argument("--skip-asr", action="store_true")
    parser.add_argument("--skip-dialog", action="store_true")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--skip-e2e", action="store_true")
    parser.add_argument("--all", action="store_true", help="ASR+Dialog+TTS+E2E")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    asr_backends = [x.strip() for x in args.asr_backends.split(",") if x.strip()]
    llm_backends = [x.strip() for x in args.llm_backends.split(",") if x.strip()]
    tts_backends = [x.strip() for x in args.tts_backends.split(",") if x.strip()]
    summary: dict[str, Any] = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not args.skip_asr:
        summary["asr"] = run_asr(cfg, asr_backends, args.limit)
    if not args.skip_dialog:
        summary["dialog"] = run_dialog(cfg, llm_backends, args.limit)
    if not args.skip_tts:
        summary["tts"] = run_tts(cfg, tts_backends, args.limit)
    if not args.skip_e2e:
        summary["e2e"] = run_e2e(cfg, asr_backends[0], llm_backends, args.e2e_limit)
    _save("summary.json", summary)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
