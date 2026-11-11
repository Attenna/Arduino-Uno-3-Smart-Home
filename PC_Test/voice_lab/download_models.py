"""Download the voice-lab models into PC_Test/models (git-ignored).

    python -m voice_lab.download_models --all
    python -m voice_lab.download_models --asr
    python -m voice_lab.download_models --llm

The ASR download uses the 2025-06-30 Chinese streaming Zipformer (int8).  It
is noticeably more accurate on short commands than the older bilingual model
already used by voice_assistant.py.  The LLM download uses ModelScope, which is
reachable from mainland China without a HuggingFace mirror.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.request

from .config import PC_TEST_DIR

MODELS = os.path.join(PC_TEST_DIR, "models")
MIRRORS = ("https://ghfast.top/", "")

ASR_NAME = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
ASR_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
           + ASR_NAME + ".tar.bz2")
ASR_DIR = os.path.join(MODELS, "sherpa", "asr_zh")
LLM_REPO = "https://modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/master"
LLM_FILE = "qwen2.5-3b-instruct-q4_k_m.gguf"
LLM_DIR = os.path.join(MODELS, "qwen")

# CTranslate2 Whisper (faster-whisper) local model.  Sizes are from the HF API
# and are used to detect truncated/proxy-error downloads.
FW_REPO = "Systran/faster-whisper-small"
FW_DIR = os.path.join(MODELS, "whisper_ct2", "small")
FW_FILES = {
    "config.json": 2370,
    "model.bin": 483546902,
    "tokenizer.json": 2203239,
    "vocabulary.txt": 459861,
}


def _download(url: str, dest: str) -> None:
    if os.path.isfile(dest) and os.path.getsize(dest) > 1024:
        print(f"  exists: {dest}")
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last = None
    for prefix in MIRRORS:
        full = prefix + url
        try:
            print(f"  GET {full}")
            request = urllib.request.Request(full, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as handle:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if total and done % (50 << 20) < (1 << 20):
                        print(f"    {done * 100 // total}% ({done >> 20}/{total >> 20} MB)", flush=True)
            print(f"  OK {os.path.getsize(dest) >> 20} MB")
            return
        except Exception as exc:
            last = exc
            print(f"  failed: {exc}")
            try:
                os.remove(dest)
            except OSError:
                pass
    raise RuntimeError(f"下载失败: {url} ({last})")


def _valid_file(path: str, name: str, expected: int) -> bool:
    if not os.path.isfile(path) or os.path.getsize(path) != expected:
        return False
    try:
        if name.endswith(".json"):
            with open(path, encoding="utf-8") as handle:
                json.load(handle)
        elif name == "vocabulary.txt":
            with open(path, "rb") as handle:
                head = handle.read(256)
            if b"Request:" in head or b"Bad Gateway" in head:
                return False
    except Exception:
        return False
    return True


def _download_resumable(url: str, dest: str, expected: int, name: str,
                        retries: int = 8) -> None:
    """Download with Range resume; HF/proxy may drop large files mid-stream."""
    if _valid_file(dest, name, expected):
        print(f"  exists: {dest}")
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(1, retries + 1):
        if os.path.exists(dest) and os.path.getsize(dest) >= expected:
            os.remove(dest)  # corrupt/oversized: restart from zero
        if os.path.exists(dest) and os.path.getsize(dest) < expected:
            # A proxy error body (e.g. "Request: ... 502") must not be resumed.
            with open(dest, "rb") as handle:
                head = handle.read(2)
            if name.endswith(".json") and not head.startswith((b"{", b"[")):
                os.remove(dest)
            elif name == "vocabulary.txt":
                with open(dest, "rb") as handle:
                    head = handle.read(256)
                if b"Request:" in head or b"Bad Gateway" in head:
                    os.remove(dest)
        pos = os.path.getsize(dest) if os.path.exists(dest) else 0
        headers = {"User-Agent": "curl/8"}
        if pos:
            headers["Range"] = f"bytes={pos}-"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                mode = "ab" if pos and response.status == 206 else "wb"
                if mode == "wb":
                    pos = 0
                with open(dest, mode) as handle:
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        handle.write(chunk)
                        pos += len(chunk)
                        if pos % (50 << 20) < (1 << 20):
                            print(f"    {pos >> 20} MB", flush=True)
            if _valid_file(dest, name, expected):
                print(f"  OK {name} ({os.path.getsize(dest) >> 20} MB)")
                return
            print(f"  incomplete {name}: {os.path.getsize(dest)}/{expected} bytes")
        except Exception as exc:
            print(f"  retry {attempt}/{retries} {name}: {exc}")
        time.sleep(1.0)
    raise RuntimeError(f"下载失败: {url} (期望 {expected} 字节)")


def _link_or_copy(src: str, dst: str) -> None:
    if os.path.exists(dst):
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def download_asr() -> None:
    archive = os.path.join(MODELS, "sherpa", ASR_NAME + ".tar.bz2")
    _download(ASR_URL, archive)
    extract_root = os.path.join(MODELS, "sherpa", "_extract_" + ASR_NAME)
    os.makedirs(extract_root, exist_ok=True)
    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(extract_root)
    src = os.path.join(extract_root, ASR_NAME)
    os.makedirs(ASR_DIR, exist_ok=True)
    for name, target in (("encoder.int8.onnx", "encoder.onnx"),
                         ("joiner.int8.onnx", "joiner.onnx"),
                         ("decoder.onnx", "decoder.onnx"),
                         ("tokens.txt", "tokens.txt")):
        _link_or_copy(os.path.join(src, name), os.path.join(ASR_DIR, target))
    print(f"ASR -> {ASR_DIR}")


def download_llm() -> None:
    _download(f"{LLM_REPO}/{LLM_FILE}", os.path.join(LLM_DIR, LLM_FILE))
    print(f"LLM -> {os.path.join(LLM_DIR, LLM_FILE)}")


def download_faster_whisper() -> None:
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    print(f"  HF endpoint: {endpoint}")
    for name, expected in FW_FILES.items():
        url = f"{endpoint}/{FW_REPO}/resolve/main/{name}"
        _download_resumable(url, os.path.join(FW_DIR, name), expected, name)
    print(f"faster-whisper -> {FW_DIR}")


def download_whisper() -> None:
    try:
        import whisper
    except Exception as exc:
        raise SystemExit("请先安装 openai-whisper: pip install openai-whisper") from exc
    root = os.path.join(MODELS, "whisper")
    os.makedirs(root, exist_ok=True)
    print(f"Whisper -> {root} (首次加载会自动下载 small.pt)")
    whisper.load_model("small", download_root=root, device="cpu")


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 voice_lab 模型")
    parser.add_argument("--asr", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--faster-whisper", action="store_true",
                        help="下载 CTranslate2 Whisper small（本地 int8）")
    parser.add_argument("--whisper", action="store_true", help="下载 openai-whisper PyTorch 权重")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if not (args.asr or args.llm or args.faster_whisper or args.whisper or args.all):
        parser.print_help()
        return 0
    if args.asr or args.all:
        print("[ASR] Sherpa 2025 Chinese streaming Zipformer")
        download_asr()
    if args.llm or args.all:
        print("[LLM] Qwen2.5-3B-Instruct Q4_K_M")
        download_llm()
    if args.faster_whisper or args.all:
        print("[ASR] faster-whisper small (CT2 int8)")
        download_faster_whisper()
    if args.whisper:
        print("[Whisper] small (PyTorch, optional fallback)")
        download_whisper()
    return 0


if __name__ == "__main__":
    sys.exit(main())
