"""download_qwen.py — 经魔搭社区 ModelScope（阿里巴巴，国内合法渠道）下载 Qwen2.5 量化权重

默认下载 Qwen/Qwen2.5-1.5B-Instruct-GGUF 的 q4_k_m 量化（约 1GB）到 PC_Test/models/qwen/。
选 1.5B：香橙派 AI Pro 纯 CPU 推理也能流畅跑（3B 留作开发机/有 GPU 时的升级选项）。

许可与合规提示：
    - Qwen2.5-1.5B 为 Apache-2.0 许可，商业友好
    - 如需更强理解力（开发机 CPU 够用或有 GPU；3B 为 Qwen Research License）：
        py -3.13 download_qwen.py --repo Qwen/Qwen2.5-3B-Instruct-GGUF --quant q4_k_m

用法：
    py -3.13 download_qwen.py                    # 默认 1.5B q4_k_m
    py -3.13 download_qwen.py --repo ... --quant q5_k_m
"""
import argparse
import glob
import os
import sys

PC_TEST_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    p = argparse.ArgumentParser(description="从 ModelScope（国内渠道）下载 Qwen2.5 GGUF")
    p.add_argument("--repo", default="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
                   help="ModelScope 仓库 id")
    p.add_argument("--quant", default="q4_k_m", help="量化档位（q4_k_m/q5_k_m/q8_0 等）")
    p.add_argument("--dest", default=os.path.join(PC_TEST_DIR, "models", "qwen"))
    args = p.parse_args()

    os.makedirs(args.dest, exist_ok=True)
    # 跳过检查必须绑定具体型号：Qwen/Qwen2.5-1.5B-Instruct-GGUF → qwen2.5-1.5b-instruct
    # 否则目录里已有的别的档位（如 3B）会被误判为"已存在"
    model_name = args.repo.rstrip("/").split("/")[-1].replace("-GGUF", "").lower()
    existing = glob.glob(os.path.join(args.dest, f"*{model_name}*{args.quant}*.gguf"))
    if existing:
        print(f"[OK] 模型已存在：{existing[0]}")
        print(f"     voice_config.yaml 中 llm.model 请设为："
              f"{os.path.splitext(os.path.basename(existing[0]))[0]}")
        return

    try:
        from modelscope import snapshot_download
    except ImportError:
        print("[错误] 未安装 modelscope：", file=sys.stderr)
        print("  py -3.13 -m pip install modelscope -i https://mirrors.aliyun.com/pypi/simple/",
              file=sys.stderr)
        sys.exit(1)

    print(f"[下载] {args.repo}（quant={args.quant}，国内渠道 modelscope.cn）→ {args.dest}")
    try:
        path = snapshot_download(args.repo, local_dir=args.dest,
                                 allow_patterns=[f"*{args.quant}*"])
    except TypeError:
        print("[提示] 当前 modelscope 版本不支持按文件过滤，将下载整个仓库（较大）...")
        path = snapshot_download(args.repo, local_dir=args.dest)

    gufs = sorted(glob.glob(os.path.join(path, "**", "*.gguf"), recursive=True))
    if not gufs:
        print(f"[错误] 下载目录未找到 GGUF：{path}", file=sys.stderr)
        sys.exit(1)
    gguf = gufs[0]
    print(f"[OK] 已下载：{gguf}")
    print(f"     voice_config.yaml 中 llm.model 请设为："
          f"{os.path.splitext(os.path.basename(gguf))[0]}")


if __name__ == "__main__":
    main()
