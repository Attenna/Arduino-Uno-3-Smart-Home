"""灯光「亮法」：请求/工具参数 ⇄ system_status 的互转。

B 板是一条 WS2812，一条 light 命令只认一种亮法：

    white —— 整条灯带白光，value 是亮度
    night —— 夜灯，只点亮居中 LIGHT_NIGHT_COUNT 颗
    temp  —— 色温白光 2700~6500K（固件查表近似成 RGB），value 是亮度
    rgb   —— 自定义颜色 (r,g,b)，value 是整体亮度缩放

面板（api/devices.py）、语音工具网关与 manual_report（同文件）、积木规则
（automation/engine.py）四条路径都会写灯的状态，共用这里的解析与记账。

内存里统一表示为 ``(mode, temp, rgb)``：mode ∈ 上面四种，temp 仅在 mode=temp
时为整数 K，rgb 仅在 mode=rgb 时为 (r,g,b)，其余一律 None —— 库里因此不可能
出现「色温和颜色同时有效」的矛盾行。
"""
from __future__ import annotations

MODES = ("white", "night", "temp", "rgb")
TEMP_MIN, TEMP_MAX = 2700, 6500

# 与固件 Config.h 的缺省保持一致：语音只说「开灯/夜灯」不带 value 时，
# 面板记的亮度才是灯真的亮度。
WHITE_DEFAULT_LEVEL = 255
NIGHT_DEFAULT_LEVEL = 60

# 固件彩色预设（Light.cpp 的 red()/green()/…），面板据此把预设色显示成实际颜色。
PRESET_RGB = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 180, 0),
    "purple": (160, 0, 255),
    "cyan": (0, 180, 255),
}

_STYLE_KEYS = ("mode", "temp", "rgb")


def _clamp(value, low, high):
    return max(low, min(high, value))


def pct(value, default=None):
    """亮度百分比 0~100；缺省/非法返回 default。"""
    try:
        return _clamp(int(value), 0, 100)
    except (TypeError, ValueError):
        return default


def pct255(value, default=0):
    """MCP 工具用 0~255 表示亮度/转速，面板记账用百分比。"""
    try:
        return _clamp(round(int(value) * 100 / 255), 0, 100)
    except (TypeError, ValueError):
        return default


def parse_temp(value):
    """色温 K，钳到固件支持区间；缺省/非法返回 None（= 本次不改色温）。"""
    try:
        kelvin = int(value)
    except (TypeError, ValueError):
        return None
    return _clamp(kelvin, TEMP_MIN, TEMP_MAX)


def parse_rgb(value):
    """(r,g,b) 0~255；接受三元列表/元组或库里的 "r,g,b" 文本，其余返回 None。"""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(_clamp(int(v), 0, 255) for v in value)
    except (TypeError, ValueError):
        return None


def rgb_field(rgb):
    """库里 light_rgb 列的写法；None = 当前不是自定义颜色。"""
    return None if rgb is None else ",".join(str(int(v)) for v in rgb)


def resolve(mode=None, temp=None, rgb=None):
    """把三个维度归化成唯一亮法，优先级 rgb > temp > mode。

    只给 mode='temp'/'rgb' 而没带对应参数时退回白光：固件需要 K 值或 (r,g,b)
    才能下发，缺了就只能当普通白光，不能凭空猜一个颜色。
    """
    color = parse_rgb(rgb)
    if color is not None:
        return ("rgb", None, color)
    kelvin = parse_temp(temp)
    if kelvin is not None:
        return ("temp", kelvin, None)
    mode = str(mode or "white").lower()
    if mode not in ("white", "night"):
        mode = "white"
    return (mode, None, None)


def from_request(data):
    """HTTP 请求里的亮法。

    三个维度一个都没给时返回 **None**，表示「沿用当前亮法」——只拖亮度、只开关的
    请求不该顺手把色温或颜色清掉（#27 的核心）。其余情况按 rgb > temp > mode 归一。
    """
    if not any(data.get(key) is not None for key in _STYLE_KEYS):
        return None
    return resolve(**{key: data.get(key) for key in _STYLE_KEYS})


def from_tool_args(args):
    """MCP ``light`` 工具参数 → (status, brightness, style)；无关调用返回 None。

    工具成功 ACK 后网关要按面板等效口径记账，因此这里把 0~255 的 value 换算成
    百分比，并按固件口径补全缺省亮度（white/temp/rgb 缺省 255、night 缺省 60）。
    彩色预设没有亮度通道：固件 ``setRgb`` 把电平记成三分量最大值，就按它记。
    亮度为 0 一律记成关灯 —— 先判亮度，参数不全的畸形调用才不会记出一个亮着的灯。
    """
    action = str(args.get("action") or "").lower()
    if action == "pixels" and (type(args.get("count")) is not int or not 1 <= args["count"] <= 8):
        return None
    if action == "off":
        return ("off", 0, None)
    preset = PRESET_RGB.get(action)
    if preset is None and action not in ("white", "on", "night", "temp", "rgb", "pixels"):
        return None
    # 先把固件的 0~255 电平凑齐，再统一换算成面板用的百分比
    if preset is not None:
        level = max(preset)
    else:
        raw = args.get("value")
        level = (NIGHT_DEFAULT_LEVEL if action == "night" else WHITE_DEFAULT_LEVEL) \
            if raw is None else raw
    brightness = pct255(level)
    if brightness <= 0:
        return ("off", 0, None)
    if preset is not None:
        return ("on", brightness, ("rgb", None, preset))
    if action == "night":
        return ("on", brightness, ("night", None, None))
    if action == "temp":
        kelvin = parse_temp(args.get("temp"))
        # 工具侧缺 temp 会直接报错、不动硬件，这里也就没有状态可记
        if kelvin is None:
            return None
        return ("on", brightness, ("temp", kelvin, None))
    if action in ("rgb", "pixels"):
        color = parse_rgb([args.get("r"), args.get("g"), args.get("b")])
        if color is None:
            return None
        return ("on", brightness, ("rgb", None, color))
    return ("on", brightness, ("white", None, None))


def from_color_param(color, r=None, g=None, b=None):
    """自动化积木的 ``color`` 字段（white/red…/rgb）→ 亮法。缺省白光。"""
    color = str(color or "white").lower()
    if color == "rgb":
        return resolve(rgb=[r, g, b])
    if color in PRESET_RGB:
        return ("rgb", None, PRESET_RGB[color])
    return resolve(mode=color)


def from_status(status_row):
    """system_status 里的当前亮法。

    列没写过（刚迁移的老库、或从没设过亮法的灯）按白光；库里写着 temp/rgb 却
    缺参数时同样退回白光，免得下发一条固件无法执行的命令。
    """
    mode = str(status_row.get("light_mode") or "white").lower()
    if mode not in MODES:
        return ("white", None, None)
    kelvin = parse_temp(status_row.get("light_temp")) if mode == "temp" else None
    color = parse_rgb(status_row.get("light_rgb")) if mode == "rgb" else None
    if (mode == "temp") != (kelvin is not None) or (mode == "rgb") != (color is not None):
        return ("white", None, None)
    return (mode, kelvin, color)


def target_from_request(data, current_brightness):
    """请求 → (status, brightness)，统一 #27 的亮度语义。

    * 亮度 0 就是关灯：``control_light`` 本来就把 <=0 直接发 off，旧代码却在这里
      把 on/0 偷偷抬成 100，于是库里记着 100%、滑块显示 0%、灯其实灭着。
    * 请求没带亮度（只改亮法的色温/颜色命令）沿用库里当前亮度，关着则 100 起步。
    * ``status`` 缺失一律按关灯处理：面板与工具网关都会带 status，宁可关灯也不要
      凭一条只含亮法的裸请求把灯点亮。
    """
    if data.get("status") != "on":
        return ("off", 0)
    raw = data.get("brightness")
    brightness = pct(raw, 0) if raw is not None else (current_brightness or 100)
    return ("on", brightness) if brightness > 0 else ("off", 0)


def to_request(style):
    """亮法 → 记账载荷的三个键（与 from_request 接受的形式一致）。"""
    mode, kelvin, color = style
    return {"mode": mode, "temp": kelvin, "rgb": list(color) if color else None}


def status_values(status, brightness, style, count=None):
    """system_status 的灯光记账字段（含亮法），供四条写入路径共用。"""
    mode, kelvin, color = style
    if status != "on" or not brightness:
        status, brightness = "off", 0
    return {"light_status": status, "light_brightness": brightness,
            "light_count": count,
            "light_mode": mode, "light_temp": kelvin,
            "light_rgb": rgb_field(color)}


def expected_readback_pct(brightness, style):
    """命令亮度 + 亮法 → B 板会回报的电平百分比（0~100）。

    B 板把「实际点亮电平」记进 ``Light::_level`` 后回报，web 再把 0~255 折算成
    百分比（``hardware.py`` 的 ``_pct(state["light"], 255)``）。这条折算对暗色
    无效：``_level`` 是**缩放后**的最大分量，峰值 < 255 的颜色本就比命令亮度低，
    拿「命令亮度」直接比对就会长期误报「命令未生效」（#30）。

    这里按固件同款整数运算复刻一遍「命令亮度 → 会上报的电平百分比」，作为比对
    的期望值：white/night/temp 的电平就等于缩放到 0~255 的命令亮度；rgb/pixels
    则按最大分量缩放（``peak * value // 255``，与 ``LightMath.scaleLightChannel``
    一致）。返回 None 表示无法判定（亮度非法），调用方跳过。
    """
    try:
        pct = int(brightness)
    except (TypeError, ValueError):
        return None
    if pct <= 0:
        return 0
    value = max(1, min(255, round(pct * 255 / 100)))
    mode, _kelvin, color = style
    if mode == "rgb" and color:
        level = max(color) * value // 255
    else:
        level = value
    return round(level * 100 / 255)


def hardware_plan(status, brightness, style, count=None):
    """意图 → 硬件桥调用 (方法名, 位置参数, 关键字参数)。

    0 亮度一律走 off：否则 rgb 会下发一条 value=0 的「全黑但不是关灯」命令，
    固件的 ``off()`` 还会清掉夜灯的点亮颗数，两者在灯带上不是同一个状态。
    """
    mode, kelvin, color = style
    if status != "on" or not brightness:
        return "control_light", ("off", 0), {}
    if count is not None and mode != "temp":
        return "control_light_pixels", (brightness, color or (255, 255, 255), count), {}
    if mode == "rgb":
        return ("control_light_color", ("rgb", color[0], color[1], color[2]),
                {"brightness_pct": brightness})
    if mode == "temp":
        return "control_light_temp", (kelvin, brightness), {}
    return "control_light", (status, brightness, mode), {}


def label(style):
    """亮法的双语短标签，用于操作提示与面板回显。"""
    mode, kelvin, color = style
    if mode == "rgb":
        return f"自定义颜色 RGB{color}", f"custom color RGB{color}"
    if mode == "temp":
        return f"色温 {kelvin}K", f"color temperature {kelvin}K"
    if mode == "night":
        return "夜灯", "night light"
    return "白光", "white light"
