#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the figures used by the Lab7 report from output/*.json."""
from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _resolve_output() -> str:
    """Find output/ in voice_lab/, PC_Test/ or Lab7/ (the report copy)."""
    for base in (HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))):
        candidate = os.path.join(base, "output")
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(HERE, "output")


OUT = _resolve_output()
FIGS = os.path.join(OUT, "figs")
os.makedirs(FIGS, exist_ok=True)

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 160,
    "savefig.dpi": 160,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.22,
    "grid.linestyle": "--",
})
BLUE, GREEN, AMBER, RED, PURPLE = "#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"


def load(name, default=None):
    try:
        with open(os.path.join(OUT, name), encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default if default is not None else {}


def _bar_labels(ax, bars, fmt="{:.0f}"):
    for bar in bars:
        height = bar.get_height()
        ax.annotate(fmt.format(height), (bar.get_x() + bar.get_width() / 2, height),
                    ha="center", va="bottom", fontsize=8, color="#334155")


def fig_asr(data):
    backends = data.get("backends", {})
    names = [n for n in ("sherpa", "faster_whisper", "whisper") if n in backends]
    if not names:
        return
    base_labels = {"sherpa": "Sherpa 2025\n(streaming int8)",
                   "faster_whisper": "faster-whisper\n(CT2 int8)",
                   "whisper": "Whisper small\n(CPU)"}
    cer = [backends[n]["summary"]["cer"]["mean"] for n in names]
    exact = [backends[n]["summary"]["exact"]["mean"] * 100 for n in names]
    lat = [backends[n]["summary"]["latency_ms"]["mean"] for n in names]
    rtf = [backends[n]["summary"]["rtf"]["mean"] for n in names]
    labels = [f"{base_labels[n]}\nRTF {rtf[i]:.2f}" for i, n in enumerate(names)]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    for ax, values, title, color, fmt in (
        (axes[0], cer, "字符错误率 CER", RED, "{:.3f}"),
        (axes[1], exact, "整句精确匹配 [%]", GREEN, "{:.1f}"),
        (axes[2], lat, "平均识别延迟 [ms]", BLUE, "{:.0f}"),
    ):
        bars = ax.bar(labels, values, color=color, width=0.55)
        ax.set_title(title, fontsize=11)
        _bar_labels(ax, bars, fmt)
        ax.set_ylim(0, max(values) * 1.25 if max(values) else 1)
    fig.suptitle("ASR 准确率与延迟（93 条合成语音，已 warmup）", fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_asr.png"), bbox_inches="tight")
    plt.close(fig)


def fig_asr_groups(data):
    backends = data.get("backends", {})
    names = [n for n in ("sherpa", "faster_whisper", "whisper") if n in backends]
    if not names:
        return
    voices = ["xiaoxiao", "yunxi", "xiaoyi"]
    width = 0.28
    fig, ax = plt.subplots(figsize=(9.2, 3.4))
    palette = [BLUE, AMBER, GREEN]
    for i, backend in enumerate(names):
        groups = backends[backend]["summary"].get("groups", {})
        values = [groups.get(f"{v}/clean", {}).get("cer", {}).get("mean", 0) for v in voices]
        x = np.arange(len(voices)) + (i - (len(names) - 1) / 2) * width
        bars = ax.bar(x, values, width, label=backend, color=palette[i % len(palette)])
        _bar_labels(ax, bars, "{:.3f}")
    ax.set_xticks(np.arange(len(voices)))
    ax.set_xticklabels(["晓晓\nXiaoxiao", "云希\nYunxi", "晓伊\nXiaoyi"])
    ax.set_ylabel("CER")
    ax.set_title("不同音色的 CER（干净音频）")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_asr_voices.png"), bbox_inches="tight")
    plt.close(fig)


def fig_dialog(data):
    backends = data.get("backends", {})
    order = [n for n in ("rules", "hybrid", "llama_cpp") if n in backends]
    if not order:
        return
    label = {"rules": "规则", "hybrid": "hybrid\n(规则+LLM)", "llama_cpp": "纯 LLM\nQwen2.5-3B"}
    name = [backends[n]["summary"]["name_acc"] * 100 for n in order]
    args = [backends[n]["summary"]["args_acc"] * 100 for n in order]
    case = [backends[n]["summary"]["case_success"] * 100 for n in order]
    lat = [backends[n]["summary"]["latency_ms"]["mean"] for n in order]
    p95 = [backends[n]["summary"]["latency_ms"]["p95"] for n in order]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.8))
    x = np.arange(len(order))
    w = 0.25
    for i, (values, title, color) in enumerate((
        (name, "工具名", BLUE), (args, "参数", GREEN), (case, "用例成功", AMBER))):
        bars = axes[0].bar(x + (i - 1) * w, values, w, label=title, color=color)
        _bar_labels(axes[0], bars, "{:.0f}")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([label[n] for n in order])
    axes[0].set_ylim(0, 112)
    axes[0].set_ylabel("准确率 [%]")
    axes[0].set_title("对话与工具调用准确率")
    axes[0].legend(frameon=False, ncol=3, fontsize=8, loc="lower left")
    bars = axes[1].bar(x, [v * 1000 for v in lat], 0.5, color=PURPLE, label="均值")
    _bar_labels(axes[1], bars, "{:.0f}")
    axes[1].plot(x, [v * 1000 for v in p95], "o--", color=RED, label="P95")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([label[n] for n in order])
    axes[1].set_ylabel("每轮耗时 [µs]")
    axes[1].set_title("对话延迟（不含 TTS；hybrid 走规则快路径）")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_dialog.png"), bbox_inches="tight")
    plt.close(fig)


def fig_tts(data):
    backends = data.get("backends", {})
    order = [n for n in ("edge", "sherpa") if n in backends]
    if not order:
        return
    label = {"edge": "edge-tts\n(在线)", "sherpa": "Sherpa VITS\n(离线)"}
    first = [backends[n]["summary"]["first_audio_ms"]["mean"] for n in order]
    total = [backends[n]["summary"]["total_ms"]["mean"] for n in order]
    rtf = [backends[n]["summary"]["rtf"]["mean"] for n in order]
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    x = np.arange(len(order))
    w = 0.34
    bars1 = ax.bar(x - w / 2, first, w, label="首包/首音", color=BLUE)
    bars2 = ax.bar(x + w / 2, total, w, label="总合成", color=GREEN)
    _bar_labels(ax, bars1, "{:.0f}")
    _bar_labels(ax, bars2, "{:.0f}")
    for i, n in enumerate(order):
        ax.annotate(f"RTF {rtf[i]:.2f}", (i, max(first[i], total[i])), ha="center",
                    va="bottom", fontsize=8, color="#475569")
    ax.set_xticks(x)
    ax.set_xticklabels([label[n] for n in order])
    ax.set_ylabel("延迟 [ms]")
    n_sentences = len(backends[order[0]].get("rows", [])) if order else 0
    ax.set_title(f"TTS 延迟（{n_sentences} 句，关闭缓存）")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_tts.png"), bbox_inches="tight")
    plt.close(fig)


def fig_latency(data):
    samples = data.get("samples", {})
    # The pure-LLM outlier (30 s+) is shown in the table; the figure keeps the
    # interactive scenarios readable on a linear axis.
    order = [n for n in ("rules_text_edge", "hybrid_text_edge", "hybrid_audio_edge",
                         "hybrid_audio_sherpa_tts", "hybrid_audio_whisper_edge")
             if n in samples]
    if not order:
        return
    label = {
        "rules_text_edge": "规则 / 文本",
        "hybrid_text_edge": "hybrid / 文本",
        "hybrid_audio_edge": "hybrid / 语音 · Sherpa",
        "hybrid_audio_whisper_edge": "hybrid / 语音 · Whisper",
        "llama_text_edge": "纯 LLM / 文本（见表）",
        "hybrid_audio_sherpa_tts": "hybrid / 语音 · 离线 VITS",
    }
    rows = []
    for name in order:
        med = samples[name].get("median") or {}
        rows.append((label.get(name, name), med.get("asr_ms", 0), med.get("llm_total_ms", 0),
                     med.get("tts_first_audio_ms", 0), med.get("total_ms", 0)))
    fig, ax = plt.subplots(figsize=(10.8, 3.9))
    y = np.arange(len(rows))
    for i, (name, asr, llm, first_audio, total) in enumerate(rows):
        ax.plot([0, total], [i, i], color="#cbd5e1", lw=7, solid_capstyle="round", zorder=1)
        ax.scatter([asr], [i], color=BLUE, s=55, zorder=3)
        ax.scatter([asr + llm], [i], color=PURPLE, s=45, marker="D", zorder=3)
        ax.scatter([first_audio], [i], color=GREEN, s=55, marker="^", zorder=3)
        ax.annotate(f"{total:.0f} ms", (total, i), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8, color="#334155")
        ax.annotate(f"ASR {asr:.0f}", (asr, i), xytext=(0, 9), textcoords="offset points",
                    ha="center", fontsize=7, color=BLUE)
        ax.annotate(f"首音 {first_audio:.0f}", (first_audio, i), xytext=(0, -14),
                    textcoords="offset points", ha="center", fontsize=7, color=GREEN)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel("从本轮开始的绝对时间 [ms]")
    ax.set_title("代表性一轮的时间线（中位数，关闭 TTS 缓存）")
    ax.set_xlim(0, max(r[4] for r in rows) * 1.08)
    from matplotlib.lines import Line2D
    ax.legend(handles=[
        Line2D([], [], color=BLUE, marker="o", lw=0, label="ASR 完成"),
        Line2D([], [], color=PURPLE, marker="D", lw=0, label="LLM 完成"),
        Line2D([], [], color=GREEN, marker="^", lw=0, label="首音"),
    ], frameon=False, ncol=3, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_latency.png"), bbox_inches="tight")
    plt.close(fig)


def fig_e2e(data):
    backends = data.get("backends", {})
    order = list(backends)
    if not order:
        return
    label = [name.replace("sherpa+", "Sherpa + ").replace("whisper+", "Whisper + ")
             for name in order]
    success = [backends[n]["summary"]["task_success"] * 100 for n in order]
    total = [backends[n]["summary"]["total_ms"]["mean"] for n in order]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5))
    bars = axes[0].bar(label, success, color=GREEN, width=0.5)
    _bar_labels(axes[0], bars, "{:.1f}")
    axes[0].set_ylim(0, 110)
    axes[0].set_ylabel("任务成功率 [%]")
    axes[0].set_title("端到端任务成功率")
    bars = axes[1].bar(label, total, color=BLUE, width=0.5)
    _bar_labels(axes[1], bars, "{:.0f}")
    axes[1].set_ylabel("每轮总耗时 [ms]")
    axes[1].set_title("端到端延迟（不含 TTS 播放）")
    axes[1].text(0.02, 0.92, "同一 ASR；差异来自热节流/测量顺序",
                 transform=axes[1].transAxes, fontsize=8, color="#64748b")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_e2e.png"), bbox_inches="tight")
    plt.close(fig)


def main():
    asr = load("eval_asr.json")
    dialog = load("eval_dialog.json")
    tts = load("eval_tts.json")
    latency = load("latency_samples.json")
    e2e = load("eval_e2e.json")
    fig_asr(asr)
    fig_asr_groups(asr)
    fig_dialog(dialog)
    fig_tts(tts)
    fig_latency(latency)
    fig_e2e(e2e)
    print("figures ->", FIGS)
    for name in sorted(os.listdir(FIGS)):
        if name.endswith(".png"):
            print("  ", name)


if __name__ == "__main__":
    main()
