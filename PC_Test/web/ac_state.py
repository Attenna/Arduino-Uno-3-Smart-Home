"""美的空调：数据库状态 ⇄ 协议状态的互转。

面板（api/devices.py）、语音动作回传（同文件 manual_report）与积木规则
（automation/engine.py）都要"按当前值补齐后整帧下发"，共用这里的转换，
避免三处各写一份而漂移。
"""
from __future__ import annotations

import midea_ac
import threading
from functools import wraps

AC_LOCK = threading.RLock()

def serialized_ac(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with AC_LOCK:
            return fn(*args, **kwargs)
    return wrapped


# 空调语义字段白名单（与 MCP 的 ac 工具参数一致）
AC_KEYS = ("power", "mode", "temperature", "fan", "swing_ud", "swing_lr")

_DEFAULT_TEMPERATURE = 26

# 真遥控器只有 4 档风速，但库里可能存着旧版 6 档（20/40/60/80/100）的历史值，
# 读回来时折算到最近的物理档位，否则编码表查不到会抛 KeyError。
_LEGACY_FAN = {"20": "low", "40": "low", "60": "mid", "80": "high", "100": "high"}


def normalize_fan_level(raw) -> str | None:
    """把任意来源的风速值归一成 ``midea_ac.FAN_LEVELS`` 里的档位。

    旧 6 档数值（20/40/60/80/100）折算到最近的物理档位；无法识别返回 None。
    规则校验（schema）与数据库读回（``_fan_from_db``）共用这一份映射，避免
    校验层与执行层再次各写一套枚举。
    """
    fan = str(raw).strip().lower() if raw not in (None, "") else ""
    fan = _LEGACY_FAN.get(fan, fan)
    return fan if fan in midea_ac.FAN_LEVELS else None


def _fan_from_db(raw) -> str:
    return normalize_fan_level(raw) or "auto"


def ac_state_from_db(db) -> midea_ac.AcState:
    """把 system_status 里最后一次成功的空调指令还原成协议状态。

    这里**不**用协议默认值去猜：库里没记录过就按默认空调（自动/26℃/自动风）算，
    用户第一次点"制冷"时补出来的完整状态才不会是空值。
    """
    s = db.get_current_status()
    temperature = s.get("ac_temperature")
    return midea_ac.AcState(
        power=(s.get("ac_status") == "on"),
        mode=s.get("ac_mode") or "auto",
        temperature=(_DEFAULT_TEMPERATURE if temperature is None
                     else int(round(float(temperature)))),
        fan=_fan_from_db(s.get("ac_fan")),
        swing_ud=bool(s.get("ac_swing_ud")),
        swing_lr=bool(s.get("ac_swing_lr")),
    )


def write_ac_state(db, state: midea_ac.AcState) -> None:
    """把协议状态写回 system_status（只记「已收到 ACK 的指令状态」）。

    关机时也写全套字段：这样重新开机时面板能回显上次的模式/温度/风速。
    """
    db.update_status(
        ac_status="on" if state.power else "off",
        ac_mode=state.mode,
        ac_temperature=state.temperature,
        ac_fan=state.fan,
        ac_swing_ud=int(state.swing_ud),
        ac_swing_lr=int(state.swing_lr),
    )
