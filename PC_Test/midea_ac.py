"""美的 RN02G(X) 空调遥控编码（Linux 侧，纯数据）。

真机遥控器型号 **RN02G(X)**，与参考仓库的 RN02S13 **不共用任何码表**。
本模块只做「语义 → 3 字节帧」，真正的红外发射由 Module B 的 IR 驱动完成
（``ir/send_midea``）。

=== 实测帧结构（香橙派 A 板红外接收头抓取真遥控器）===
    整帧 = 引导(4400µs 载波 + 4400µs 空闲) + 48bit + 结束(500µs 载波 + 5220µs 空闲)
    **同一帧连发 2 遍**（两遍之间就是结束位的长空档）
    48bit = 6 字节 ``[A, ~A, B, ~B, C, ~C]``，三组互为逐位补码，
    **全部 MSB-first**（这一点与 RN02S13 的「B/C 低位先发」不同，勿照抄旧码）
    A = 0xB2（状态帧）/ 0xB5（功能帧，实测只有左右扫风用到）

=== 状态字节编码（本模块的编码目标）===
    B = 高半字节风速码 | 0x0F
        自动 0xB / 低 0x9 / 中 0x5 / 高 0x3
        抽湿、自动没有独立风速档，B 固定 0x1F；送风固定 0xBF
    C = (温度码 << 4) | 模式码
        温度码（17→30，实测非单调）：0,1,3,2,6,7,5,4,C,D,9,8,A,B
        模式码：制冷 0x0 / 抽湿 0x4 / 自动 0x8 / 制热 0xC
        送风 0xE4（该模式不设温度，C 整字节固定）

=== 特殊帧 ===
    关机      B2 7B E0
    上下扫风  B2 0F E0
    左右扫风  B5 4A A9   （唯一用 0xB5 的功能帧）

=== 开机 ===
RN02G(X) 没有独立的「开机码」——**收到任意合法状态帧即开机**（实测开机帧
``B2 4D 1F E0 C8 37`` 恰好等于 auto/25℃ 的状态帧）。所以开机 = 下发当前
（模式, 温度, 风速）状态帧。

=== 未支持 ===
省电(ECO)/防直吹(FZC)/定时 三个功能本轮真机抓取未能复现，码表未知，故不实现
（web 面板与 MCP 参数已同步移除，避免点了没反应还写库）。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

TEMP_MIN = 17
TEMP_MAX = 30

MODES = ("auto", "cool", "heat", "dry", "fan")
FAN_LEVELS = ("auto", "low", "mid", "high")

# 温度 → C 字节高半字节（实测表，注意不是单调的）
_TEMP_CODE = {17: 0x0, 18: 0x1, 19: 0x3, 20: 0x2, 21: 0x6, 22: 0x7,
              23: 0x5, 24: 0x4, 25: 0xC, 26: 0xD, 27: 0x9, 28: 0x8,
              29: 0xA, 30: 0xB}

# 模式 → C 字节低半字节
_MODE_CODE = {"cool": 0x0, "dry": 0x4, "auto": 0x8, "heat": 0xC}

# 风速 → B 字节高半字节
_FAN_CODE = {"auto": 0xB, "low": 0x9, "mid": 0x5, "high": 0x3}

# 这些模式的 B 高半字节固定（B 已不表示风速）：抽湿/自动无风速档，送风恒为自动风
_FIXED_B_HIGH = {"auto": 0x1, "dry": 0x1, "fan": 0xB}

# 送风模式不设温度，C 整字节固定
_FAN_MODE_C = 0xE4

_FRAME_POWER_OFF = (0xB2, 0x7B, 0xE0)
_FRAME_SWING_UD = (0xB2, 0x0F, 0xE0)
_FRAME_SWING_LR = (0xB5, 0x4A, 0xA9)


def _hex(frame: tuple[int, int, int]) -> str:
    return "".join(f"{b & 0xFF:02X}" for b in frame)


def _state_frame(mode: str, temperature: int, fan: str) -> tuple[int, int, int]:
    """把（模式, 温度, 风速）编成 3 字节状态帧 (A, B, C)。

    A 恒为 0xB2；~A/~B/~C 由 B 板固件按位取反生成。
    """
    if mode == "fan":
        c = _FAN_MODE_C
    else:
        c = (_TEMP_CODE[temperature] << 4) | _MODE_CODE[mode]
    if mode in _FIXED_B_HIGH:
        b = (_FIXED_B_HIGH[mode] << 4) | 0x0F
    else:
        b = (_FAN_CODE[fan] << 4) | 0x0F
    return 0xB2, b, c


@dataclass
class AcState:
    """空调当前设定（MCP / web 进程内维护，写库后跨重启恢复）。

    温度只支持整数度：RN02G(X) 的温度码表是 17~30 共 14 个离散值，没有半度档。
    扫风是**遥控器上的翻转键**，本模块只能在"设定值发生变化"时补发一次翻转帧，
    实际朝向取决于空调当时的状态，不做绝对位置保证。
    """
    power: bool = False
    mode: str = "auto"
    temperature: int = 26
    fan: str = "auto"
    swing_ud: bool = False
    swing_lr: bool = False

    def snapshot(self) -> dict:
        """给前端/DB 用的语义状态。"""
        return {"power": self.power, "mode": self.mode,
                "temperature": self.temperature, "fan": self.fan,
                "swing_ud": self.swing_ud, "swing_lr": self.swing_lr}


def apply_overrides(state: AcState, **kw) -> tuple[AcState, set[str]]:
    """把（可为 None 的）overrides 合并进状态，返回 (新状态, 变更字段集合)。

    非法取值抛 ``ValueError``。``None`` 一律表示"该项不改"。
    """
    new = replace(state)
    changed: set[str] = set()

    if kw.get("power") is not None:
        value = bool(kw["power"])
        if value != new.power:
            changed.add("power")
        new.power = value

    mode = kw.get("mode")
    if mode:
        if mode not in MODES:
            raise ValueError(f"模式只能是 {'/'.join(MODES)}")
        if mode != new.mode:
            changed.add("mode")
        new.mode = mode

    temperature = kw.get("temperature")
    if temperature is not None:
        temperature = int(round(float(temperature)))
        if not TEMP_MIN <= temperature <= TEMP_MAX:
            raise ValueError(f"温度需在 {TEMP_MIN}~{TEMP_MAX}℃ 之间")
        if temperature != new.temperature:
            changed.add("temperature")
        new.temperature = temperature

    fan = kw.get("fan")
    if fan:
        if fan not in FAN_LEVELS:
            raise ValueError(f"风速只能是 {'/'.join(FAN_LEVELS)}")
        if fan != new.fan:
            changed.add("fan")
        new.fan = fan

    for key in ("swing_ud", "swing_lr"):
        value = kw.get(key)
        if value is not None:
            value = bool(value)
            if value != getattr(new, key):
                changed.add(key)
            setattr(new, key, value)

    return new, changed


def to_frames(state: AcState, changed: set[str]) -> list[str]:
    """把一次状态变更翻译成有序的帧十六进制串列表（每串 3 字节，由固件补反码）。

    - 关机：只发关机帧
    - 未开机且本次没要求开机：不下发，避免把空调误开
    - 开机或改动模式/温度/风速：发**一帧完整状态帧**（一帧即带齐全部设定，且能唤醒空调）
    - 扫风：只能在数值变更时补发一次翻转帧
    """
    if not state.power:
        return [_hex(_FRAME_POWER_OFF)] if "power" in changed else []

    frames: list[str] = []
    if changed & {"power", "mode", "temperature", "fan"}:
        frames.append(_hex(_state_frame(state.mode, state.temperature, state.fan)))
    if "swing_ud" in changed:
        frames.append(_hex(_FRAME_SWING_UD))
    if "swing_lr" in changed:
        frames.append(_hex(_FRAME_SWING_LR))
    return frames


def encode_frame(mode: str, temperature: int, fan: str) -> str:
    """便捷函数：直接编出一帧状态帧的十六进制串（自检/对照用）。"""
    return _hex(_state_frame(mode, int(round(temperature)), fan))
