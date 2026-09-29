"""download_sherpa_models.py — Sherpa-ONNX 语音模型一键下载

三套模型（GitHub Release，自动走 ghfast.top 国内镜像加速）：
    KWS  sherpa-onnx-kws-zipformer-wenetspeech-3.3M  (~14MB)  → models/sherpa/kws/
    ASR  sherpa-onnx-streaming-zipformer-bilingual-zh-en（int8 三件套，香橙派 CPU 实时）→ models/sherpa/asr/
    TTS  vits-melo-tts-zh_en（中英双语 VITS）                → models/sherpa/tts/

解压后统一重命名为 encoder.onnx / decoder.onnx / joiner.onnx / tokens.txt，
并写入 keywords.txt（唤醒词「Hey Bota」，可再编辑）。

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

# 唤醒词「Hey Bota」：KWS 模型是中文 wenetspeech（拼音音素 token），
# 英文词用发音最近的拼音声韵母拼接，并放多个声调变体提高命中率。
#   Hey /heɪ/ → hēi(h ēi) 或阳平升调 h éi
#   Bota /ˈboʊtə/ → bōu(b ōu)/bō(b ō) + 轻声/各声调 t a
# 每行格式：音素空格分隔 @内部名；注意 @ 后名字不能含空格（否则被当音素编码失败），
# 用下划线 Hey_Bota，sherpa_listener 回调时自动还原成 "Hey Bota"。
KEYWORDS_TXT = """\
h ēi b ōu t ǎ @Hey_Bota
h éi b ōu t ā @Hey_Bota
h ēi b ōu t a @Hey_Bota
h ēi b ō t ǎ @Hey_Bota
"""

# ASR 热词（hotwords）：智能家居控制高频词，按字切分（该 BPE 词表中文以单字为 token）。
# 作用：在解码时给这些词额外加权，显著提升「开灯/红色/蜂鸣器」等专业词的识别率。
# 权重在 voice_config.yaml 的 sherpa.asr.hotwords_score 统一配置；可自行增删词组后重启。
HOTWORDS = [
    # 灯 / 颜色
    "开灯", "关灯", "把灯打开", "把灯关了", "打开灯", "关掉灯", "灯光",
    "红色", "蓝色", "绿色", "白色", "紫色", "黄色", "粉色", "橙色", "彩色",
    "把灯调成红色", "把灯调成蓝色", "把灯调成绿色", "亮一点", "暗一点",
    # 门 / 窗 / 窗帘
    "开门", "关门", "把门打开", "把门关上", "开窗", "关窗", "窗帘",
    # 风扇
    "风扇", "开风扇", "关风扇", "风速", "风扇调到", "风大一点", "风小一点",
    # 蜂鸣器 / 显示
    "蜂鸣器", "响一下", "数码管", "显示屏",
    # 传感器查询
    "温度", "湿度", "现在多少度", "屋里多少度", "现在几度", "人体感应", "有没有人",
    # 设备 / 场景
    "空调", "电视", "回家模式", "离家模式", "睡觉模式",
]


def _build_hotwords_txt() -> str:
    return "\n".join(" ".join(list(w)) for w in HOTWORDS) + "\n"


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
    write_wordlists()
    print(f"[{key}] 安装完成 → {dest_dir}")


def write_wordlists() -> None:
    """（重）写项目定制词表：KWS 唤醒词 + ASR 热词。

    每次运行都刷新，便于升级脚本后给已下载的模型补词表，无需 --force 重下。
    """
    kws_dir = os.path.join(MODELS_ROOT, "kws")
    if os.path.isdir(kws_dir):
        with open(os.path.join(kws_dir, "keywords.txt"), "w", encoding="utf-8") as f:
            f.write(KEYWORDS_TXT)
        print("  刷新 KWS 唤醒词 keywords.txt: Hey Bota（4 个拼音音近变体）")
    asr_dir = os.path.join(MODELS_ROOT, "asr")
    if os.path.isdir(asr_dir):
        with open(os.path.join(asr_dir, "hotwords.txt"), "w", encoding="utf-8") as f:
            f.write(_build_hotwords_txt())
        print(f"  刷新 ASR 热词 hotwords.txt: {len(HOTWORDS)} 个智能家居高频词")


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
    write_wordlists()   # 模型已存在被跳过时，也能补上新版词表
    print("\n全部模型就绪。")


if __name__ == "__main__":
    sys.exit(main())
