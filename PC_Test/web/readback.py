"""B 板硬件回读 vs 命令下发值的比对（P1 看板展示 与 P2 审计共用同一份判定）。

web 以 --no-serial 运行、读不到 B 板真实状态时，system_status 里的 door_status /
fan_speed 等只是「上次命令下发值」。hardware.py 每 10s 把 B 板自己的电平写进并列的
rb_* 列，两者一对就能暴露「面板显示 0% 而风扇在转」这类静默失效（以前 B 板不上报，
根本看不出来）。
"""
from __future__ import annotations

from datetime import datetime, timezone

# 命令下发值 ←→ B 板硬件回读值 的对照表
READBACK_PAIRS = (
    ("fan", "fan_speed", "rb_fan_speed", "风扇"),
    ("door", "door_status", "rb_door_status", "门"),
    ("window", "window_status", "rb_window_status", "窗"),
    ("light", "light_brightness", "rb_light_brightness", "灯光"),
)

RB_FRESH_S = 30.0     # 回读新鲜窗口：超时说明心跳停了，不能拿旧回读判定
CMD_SETTLE_S = 15.0   # 刚下发过就跳过：回读是 10s 级心跳，本来就可能还没跟上


def parse_utc(text):
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def output_mismatch(status: dict, fresh_s: float = RB_FRESH_S,
                    settle_s: float = CMD_SETTLE_S) -> list:
    """列出「命令下发值 ≠ B 板硬件回读值」的设备。

    两类情况不判定，避免误报：
      * 回读过期（>fresh_s，心跳停了）；
      * 刚下发过（<settle_s）——回读是 10s 级心跳，本来就可能还没跟上。
        注意必须看 ``output_last_seen``（执行器指令被 ACK 的时刻），**不能用
        last_updated**：后者会被传感器轮询每 2 秒刷新，用它做闸门会导致永远不判定。
    """
    now = datetime.now(timezone.utc)
    seen = parse_utc(status.get("rb_seen_at"))
    if seen is None or not 0 <= (now - seen).total_seconds() < fresh_s:
        return []
    cmd_at = parse_utc(status.get("output_last_seen"))
    if cmd_at is not None and (now - cmd_at).total_seconds() < settle_s:
        return []

    out = []
    for device, cmd_key, rb_key, label in READBACK_PAIRS:
        cmd, rb = status.get(cmd_key), status.get(rb_key)
        if cmd is None or rb is None:
            continue
        if device in ("door", "window"):
            same = str(cmd) == str(rb)
        else:
            try:
                same = int(cmd) == int(rb)
            except (TypeError, ValueError):
                continue
        if not same:
            out.append({"device": device, "label": label,
                        "commanded": cmd, "readback": rb})
    return out
