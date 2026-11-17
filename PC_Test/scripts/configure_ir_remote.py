"""离线生成遥控规则配置；不直接覆盖运行中的规则文件。"""
import argparse
import importlib.util
import json
from pathlib import Path

# Import this pure file directly: importing web runs application singletons and
# opens its runtime DB, which an offline configuration tool must never do.
_path = Path(__file__).resolve().parents[1] / "web/automation/remote_profile.py"
_spec = importlib.util.spec_from_file_location("remote_profile_offline", _path)
_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_profile)
configure_remote = _profile.configure_remote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("请写到独立输出文件，审阅后在网关停止期间替换")
    updated, removed = configure_remote(json.loads(args.input.read_text(encoding="utf-8")))
    # 拒绝覆盖已有文件，避免误覆盖先前配置或备份。
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(updated, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"replaced_ir_rules": removed, "new_ir_rules": 10}, ensure_ascii=False))


if __name__ == "__main__":
    main()
