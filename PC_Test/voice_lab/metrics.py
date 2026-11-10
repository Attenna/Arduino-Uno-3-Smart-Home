"""Small, dependency-free metrics used by the evaluators and tests."""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

from .asr import normalize_text


def edit_distance(reference: str, hypothesis: str) -> int:
    if reference == hypothesis:
        return 0
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)
    previous = list(range(len(hypothesis) + 1))
    for i, ref_char in enumerate(reference, 1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ref_char != hyp_char),
            ))
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def exact_match(reference: str, hypothesis: str) -> bool:
    return normalize_text(reference) == normalize_text(hypothesis)


def keyword_recall(keywords: Iterable[str], hypothesis: str) -> float:
    words = [w for w in keywords if w]
    if not words:
        return 1.0
    text = normalize_text(hypothesis)
    return sum(1 for w in words if normalize_text(w) in text) / len(words)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def summarize(values: Iterable[float]) -> dict[str, float]:
    data = [float(v) for v in values if v is not None]
    if not data:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p95": 0.0,
                "min": 0.0, "max": 0.0}
    return {
        "count": len(data),
        "mean": sum(data) / len(data),
        "median": percentile(data, 0.5),
        "p95": percentile(data, 0.95),
        "min": min(data),
        "max": max(data),
    }


def args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Expected is a subset; the model may add harmless defaults."""
    for key, value in (expected or {}).items():
        if key not in actual:
            return False
        if isinstance(value, str) and isinstance(actual[key], str):
            if value != actual[key]:
                return False
        elif value != actual[key]:
            return False
    return True


def tool_match(expected: Optional[dict[str, Any]], actual_name: str,
               actual_args: dict[str, Any]) -> tuple[bool, bool]:
    """Return (name_match, args_match)."""
    if not expected:
        return not actual_name, not actual_args
    name_ok = expected.get("name") == actual_name
    args_ok = name_ok and args_match(expected.get("args") or {}, actual_args or {})
    return name_ok, args_ok


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
