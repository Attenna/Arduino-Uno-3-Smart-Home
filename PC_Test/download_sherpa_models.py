"""download_sherpa_models.py — Sherpa-ONNX 语音模型一键下载

三套模型（GitHub Release，自动走 ghfast.top 国内镜像加速）：
    KWS  sherpa-onnx-kws-zipformer-wenetspeech-3.3M  (~14MB)  → models/sherpa/kws/
    ASR  sherpa-onnx-streaming-zipformer-bilingual-zh-en（int8 三件套，香橙派 CPU 实时）→ models/sherpa/asr/
    TTS  vits-melo-tts-zh_en（中英双语 VITS）                → models/sherpa/tts/

解压后统一重命名为 encoder.onnx / decoder.onnx / joiner.onnx / tokens.txt，
并写入 keywords.txt（唤醒词「你邮你邮」，可再编辑）。

用法：
    py -3.13 download_sherpa_models.py               # 全部下载（缺失才下）
    py -3.13 download_sherpa_models.py --tts-only    # 只下 TTS
    py -3.13 download_sherpa_models.py --force       # 强制重下
"""
import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_ROOT = os.path.join(BASE_DIR, "models", "sherpa")

MIRRORS = ["https://ghfast.top/", ""]   # 先国内镜像，失败回退直连

# (release_tag, 包名, 目标子目录, {包内文件名匹配后缀: 标准名})
PACKS = {
    # prefer: 同名文件选谁优先（"int8"=量化版，体积/速度更优，适合香橙派）
    "kws": ("kws-models", "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01", "kws", {
        "encoder": ("encoder.onnx", ["fp32"]),
        "decoder": ("decoder.onnx", ["fp32"]),
        "joiner":  ("joiner.onnx",  ["fp32"]),
        "tokens.txt": ("tokens.txt", None),
    }),
    # transducer 架构（含 joiner），int8 三件套是香橙派/ARM CPU 实时识别推荐配置
    "asr": ("asr-models", "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20", "asr", {
        "encoder": ("encoder.onnx", ["int8", "fp32"]),
        "decoder": ("decoder.onnx", ["int8", "fp32"]),
        "joiner":  ("joiner.onnx",  ["int8", "fp32"]),
        "tokens.txt": ("tokens.txt", None),
    }),
    "tts": ("tts-models", "vits-melo-tts-zh_en", "tts", {
        "model.onnx": ("model.onnx", None),
        "tokens.txt": ("tokens.txt", None),
        "lexicon.txt": ("lexicon.txt", None),
        "dict/": ("dict", None),       # 整个目录（jieba 分词字典）
    }),
}

# 唤醒词（pypinyin 声调符号格式，空格分词，@ 后为显示名）
# 你邮你邮 = nǐ yóu nǐ yóu；另加一个「你好你好」别名（发音相近时兜底）
KEYWORDS_TXT = """\
n ǐ y óu n ǐ y óu @你邮你邮
n ǐ h ǎo n ǐ h ǎo @你好你好
"""


def _download(url: str, dest: str) -> None:
    last_err = None
    for prefix in MIRRORS:
        full = prefix + url
        try:
            print(f"  下载 {full}")
            req = urllib.request.Request(full, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                done, last_pct = 0, -1
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        if pct != last_pct and pct % 10 == 0:
                            print(f"    {pct}% ({done >> 20}/{total >> 20} MB)", flush=True)
                            last_pct = pct
            print(f"  OK: {os.path.getsize(dest) >> 20} MB")
            return
        except Exception as e:
            print(f"  失败（{'镜像' if prefix else '直连'}）: {e}")
            last_err = e
    raise RuntimeError(f"所有下载通道均失败: {last_err}")


def install_pack(key: str, force: bool) -> None:
    tag, name, subdir, wanted = PACKS[key]
    dest_dir = os.path.join(MODELS_ROOT, subdir)
    # 已就绪则跳过（检查非 dict 的标准文件 + tts 的 dict 目录）
    ready = os.path.isdir(dest_dir) and all(
        os.path.isfile(os.path.join(dest_dir, std))
        for stem, (std, _prefer) in wanted.items() if not stem.endswith("/"))
    if ready and (key != "tts" or os.path.isdir(os.path.join(dest_dir, "dict"))):
        if not force:
            print(f"[{key}] 已存在，跳过（--force 可重下）")
            return

    os.makedirs(dest_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = os.path.join(tmp, name + ".tar.bz2")
        _download(f"https://github.com/k2-fsa/sherpa-onnx/releases/download/{tag}/{name}.tar.bz2",
                  tar_path)
        print(f"  解压 {name} ...")
        with tarfile.open(tar_path, "r:bz2") as tf:
            tf.extractall(tmp)
        src_dir = os.path.join(tmp, name)
        # 收集所有候选文件
        candidates: dict[str, list[tuple[str, str]]] = {}
        for root, _dirs, files in os.walk(src_dir):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, src_dir).replace("\\", "/")
                for stem, (std, prefer) in wanted.items():
                    if stem.endswith("/"):
                        continue
                    # fn 必须包含词干且扩展名是 .onnx 或 .txt
                    ext = os.path.splitext(fn)[1]
                    if stem in fn and ext in (".onnx", ".txt"):
                        # 计算分数：出现在文件名中位置越靠前/完整文件名越短越好
                        score = fn.index(stem)
                        candidates.setdefault(std, []).append((full, fn, score, prefer))
        # 按优先级排序并复制
        copied = set()
        for std, cands in candidates.items():
            # prefer 是收集时就绑定好的优先级列表（候选自身携带，避免再反查 wanted）
            prefer = cands[0][3]
            if prefer:
                def _pref_score(item, prefer=prefer):
                    fn = item[1].lower()
                    for i, tag in enumerate(prefer):
                        if tag in fn:
                            return i
                    return len(prefer)  # 不在列表里的优先级最低
                # 先按优先级（int8 在前），同级再按文件名匹配位置
                cands.sort(key=lambda item: (_pref_score(item), item[2]))
            else:
                cands.sort(key=lambda x: x[2])  # score 越小越靠前
            shutil.copy2(cands[0][0], os.path.join(dest_dir, std))
            copied.add(std)
        # 目录类（dict/）
        for stem, (std, prefer) in wanted.items():
            if stem.endswith("/"):
                src_sub = os.path.join(src_dir, stem.rstrip("/"))
                if os.path.isdir(src_sub):
                    dst_sub = os.path.join(dest_dir, std)
                    if os.path.isdir(dst_sub):
                        shutil.rmtree(dst_sub)
                    shutil.copytree(src_sub, dst_sub)
                    copied.add(std)
        missing = [wanted[k][0] for k in wanted if wanted[k][0] not in copied and not k.endswith("/")]
        if missing:
            raise RuntimeError(f"[{key}] 解压后仍缺文件: {missing}")
    if key == "kws":
        kw_path = os.path.join(dest_dir, "keywords.txt")
        with open(kw_path, "w", encoding="utf-8") as f:
            f.write(KEYWORDS_TXT)
        print(f"  已写入唤醒词 keywords.txt: 你邮你邮 / 你好你好")
    print(f"[{key}] 安装完成 → {dest_dir}")


def main():
    p = argparse.ArgumentParser(description="下载 Sherpa-ONNX 语音模型（国内镜像加速）")
    p.add_argument("--force", action="store_true", help="强制重新下载")
    p.add_argument("--kws-only", action="store_true")
    p.add_argument("--asr-only", action="store_true")
    p.add_argument("--tts-only", action="store_true")
    args = p.parse_args()

    only = {k for k, v in (("kws", args.kws_only), ("asr", args.asr_only), ("tts", args.tts_only)) if v}
    targets = only or {"kws", "asr", "tts"}
    for k in ("kws", "asr", "tts"):
        if k in targets:
            install_pack(k, args.force)
    print("\n全部模型就绪。")


if __name__ == "__main__":
    sys.exit(main())
