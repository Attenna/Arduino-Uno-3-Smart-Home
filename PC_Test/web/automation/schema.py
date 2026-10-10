"""规则 JSON 模型与校验（前端 Blockly 积木 <-> 后端规则 JSON 的契约）。

规则结构::

    {
      "id": "a1b2c3d4",
      "name": "高温自动开风扇",
      "enabled": true,
      "trigger": { ... 触发块 ... },
      "match": "all",                 # 条件块组合方式：all=全部满足 / any=任一满足
      "conditions": [ ... 条件块 ... ],
      "actions": [ ... 满足时执行的动作块序列 ... ],
      "else_actions": [ ... 不满足时的状态切换动作 ... ],
      "cooldown": 5                   # 两次触发的最小间隔（秒）
    }
"""
from __future__ import annotations

import math

from . import webhook
from .capabilities import (
    ACCESS_METHOD_IDS, ACTION_DEVICES, COMPARATORS, CONDITION_SOURCES,
    DELAY_MAX_SECONDS, EVENT_TRIGGERS,
)
from .global_state import is_var_id
# RFID 卡号归一化（"AA BB CC DD"）与上报值全等比对，避免大小写/分隔符导致匹配失败
from ..database import normalize_uid
# 空调风速的唯一真源是执行层的 midea_ac.FAN_LEVELS；旧 6 档数值由 ac_state 归一
import midea_ac
from ..ac_state import normalize_fan_level

COMPARATOR_IDS = {c["id"] for c in COMPARATORS}


class ValidationError(ValueError):
    """规则 JSON 不合法。"""


def _require(obj: dict, keys: tuple[str, ...], where: str) -> None:
    for key in keys:
        if key not in obj:
            raise ValidationError(f"{where} 缺少字段 {key}")


def _check_source(sensor_id, where: str, vars_info: dict | None,
                  strict: bool = True) -> None:
    """触发/条件的数据源合法性。

    静态白名单（CONDITION_SOURCES）之外，放行形如 ``g:名字`` 的全局状态。
    ``strict=False``（引擎读盘）只校验格式——变量被删掉不能让整个规则集校验
    失败（那会清空所有规则）；``strict=True``（页面保存 / 直接调用）要求变量
    确实存在，避免用户写出永远不成立的错字规则。
    """
    if sensor_id in CONDITION_SOURCES:
        return
    if is_var_id(sensor_id):
        if not strict or vars_info is None or sensor_id in vars_info:
            return
        raise ValidationError(
            f"{where}引用的全局状态不存在: {sensor_id}"
            "（请先在自动化页新建这条「📌 状态」条目）")
    raise ValidationError(f"{where}未知传感器/状态: {sensor_id}")


def _source_spec(sensor_id: str, vars_info: dict | None) -> dict | None:
    """数据源的比较元数据（kind + choices/min/max）。

    静态白名单永远有定义；``g:`` 变量只有严格模式（vars_info 来自页面保存时的
    变量定义）才知道类型，宽松模式拿不到 → 返回 None，比较校验随之跳过。
    """
    spec = CONDITION_SOURCES.get(sensor_id)
    if spec:
        return spec
    if is_var_id(sensor_id):
        return (vars_info or {}).get(sensor_id)
    return None


def _as_number(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{where} 需要数字，得到 {value!r}")
    return float(value)


# 各 kind 允许的比较符：布尔/选项只能比相等，数值可全量比较
_OPS_BY_KIND = {"bool": ("==", "!="), "number": tuple(COMPARATOR_IDS),
                "enum": ("==", "!=")}


def _clean_comparison(sensor_id, op, value, where, vars_info, strict: bool):
    """按数据源类型约束比较符与阈值，并归一化阈值。

    ``_compare`` 遇到「数值源 vs 字符串阈值」会掉进字符串分支、``>``/``<`` 恒假，
    所以这类「保存得下去、运行永远不成立」的组合必须在保存期拦掉：

    - number：阈值必须能转成数字（``"26"`` 也接受并归一成 26），有量程的源查范围；
    - bool：只允许 ==/!=，阈值归一成 true/false；
    - enum：只允许 ==/!=，阈值必须是该源的合法选项。

    宽松模式（引擎读盘，strict=False）只做**能做的归一**、不做拒绝：历史脏数据
    不能让整条规则在启动时被丢掉（与 ``_check_source`` 的双模约定一致）。
    """
    spec = _source_spec(sensor_id, vars_info)
    if spec is None:
        return value
    label = spec.get("label", sensor_id)
    allowed = _OPS_BY_KIND.get(spec.get("kind"))
    if allowed is None:
        if strict:
            raise ValidationError(f"{where}「{label}」不能作为比较源")
        return value
    if op not in allowed:
        if strict:
            raise ValidationError(
                f"{where}「{label}」只支持 {'/'.join(allowed)} 比较")
        return value
    if spec["kind"] == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "false"):
            return text == "true"
        if strict:
            raise ValidationError(
                f"{where}「{label}」的条件值只能是 是/否（true/false）")
        return value
    if spec["kind"] == "number":
        # 只接受真正的数字（bool 也是 int 的子类，必须先从数值里排除）：字符串阈值
        # 会让运行期 `_compare` 掉进字符串分支、"26" > 26 恒假
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            if strict:
                raise ValidationError(f"{where}「{label}」需要数字，得到 {value!r}")
            # 宽松模式（引擎读盘）：能安全转成数字的历史脏值就地归一，其余原样保留
            try:
                num = float(value)
            except (TypeError, ValueError):
                return value
            if not math.isfinite(num):
                return value
            return int(num) if num.is_integer() else num
        num = float(value)
        if not math.isfinite(num):
            if strict:
                raise ValidationError(f"{where}「{label}」需要有限数字")
            return value
        lo, hi = spec.get("min"), spec.get("max")
        if strict and lo is not None and hi is not None and not lo <= num <= hi:
            raise ValidationError(
                f"{where}「{label}」需在 {lo:g}~{hi:g}{spec.get('unit') or ''} 之间")
        return int(num) if num.is_integer() else num
    # enum：阈值先归成字符串，再按 choices 校验
    text = value if isinstance(value, str) else str(value)
    choices = spec.get("choices") or []
    if strict and choices and text not in choices:
        raise ValidationError(
            f"{where}「{label}」只能是 {'/'.join(map(str, choices))} 之一")
    return text


def validate_trigger(trig: dict, vars_info: dict | None = None,
                     strict: bool = True) -> dict:
    _require(trig, ("kind",), "触发块")
    kind = trig["kind"]
    if kind == "sensor":
        _require(trig, ("sensor", "op", "value"), "传感器触发块")
        _check_source(trig["sensor"], "传感器触发块", vars_info, strict)
        if trig["op"] not in COMPARATOR_IDS:
            raise ValidationError(f"非法比较符: {trig['op']}")
        value = _clean_comparison(trig["sensor"], trig["op"], trig["value"],
                                  "传感器触发块", vars_info, strict=strict)
        clean = {"kind": "sensor", "sensor": trig["sensor"],
                 "op": trig["op"], "value": value}
        # 「持续 N 秒」：条件连续保持该时长才触发（逗留报警/烟雾确认这类需求）
        hold = trig.get("hold_sec")
        if hold not in (None, "", 0):
            hold = _as_number(hold, "传感器触发块的持续时长")
            if not 1 <= hold <= 86400:
                raise ValidationError("持续时长需在 1~86400 秒之间")
            clean["hold_sec"] = hold
        return clean
    if kind == "event":
        _require(trig, ("event",), "事件触发块")
        event = trig["event"]
        if event not in EVENT_TRIGGERS:
            raise ValidationError(f"未知事件: {event}")
        clean = {"kind": "event", "event": event}
        # keypad / ir / manual_control 事件可带参数过滤（按键名 / 红外命令码 / 设备）
        for extra in ("key", "command", "device"):
            if trig.get(extra) not in (None, ""):
                clean[extra] = str(trig[extra]).strip()
        # rfid 事件可带卡号过滤（不填=任意卡片都触发）
        if trig.get("uid") not in (None, ""):
            try:
                clean["uid"] = normalize_uid(trig["uid"])
            except ValueError as e:
                raise ValidationError(f"RFID 卡号非法：{e}")
        # 门禁事件可限定验证方式（不填=人脸/刷卡/键盘任一）
        if trig.get("method") not in (None, ""):
            method = str(trig["method"]).strip()
            if method not in ACCESS_METHOD_IDS:
                raise ValidationError(
                    f"门禁验证方式只能是 {'/'.join(ACCESS_METHOD_IDS)}，得到 {method!r}")
            clean["method"] = method
        return clean
    if kind == "interval":
        seconds = _as_number(trig.get("seconds"), "周期触发块")
        if seconds < 2:
            raise ValidationError("周期间隔不能小于 2 秒")
        return {"kind": "interval", "seconds": min(seconds, 86400)}
    if kind == "time":
        hhmm = str(trig.get("hhmm", ""))
        try:
            hour, minute = (int(x) for x in hhmm.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValidationError(f"定时时间格式应为 HH:MM，得到 {hhmm!r}")
        return {"kind": "time", "hhmm": f"{hour:02d}:{minute:02d}"}
    raise ValidationError(f"未知触发类型: {kind}")


def validate_condition(cond: dict, vars_info: dict | None = None,
                       strict: bool = True) -> dict:
    _require(cond, ("sensor", "op", "value"), "条件块")
    _check_source(cond["sensor"], "条件块", vars_info, strict)
    if cond["op"] not in COMPARATOR_IDS:
        raise ValidationError(f"条件块非法比较符: {cond['op']}")
    value = _clean_comparison(cond["sensor"], cond["op"], cond["value"],
                              "条件块", vars_info, strict=strict)
    return {"sensor": cond["sensor"], "op": cond["op"], "value": value}


def validate_action(action: dict, where: str = "动作块",
                    vars_info: dict | None = None,
                    http_policy: dict | None = None,
                    strict: bool = True) -> dict:
    _require(action, ("device",), where)
    device = action["device"]
    if device not in ACTION_DEVICES:
        raise ValidationError(f"{where}未知设备: {device}")
    clean = {"device": device}
    if device == "camera":
        if action.get("action", "snapshot") != "snapshot":
            raise ValidationError("摄像头动作只能是 snapshot")
        return {"device": "camera", "action": "snapshot"}
    if device == "delay":
        seconds = _as_number(action.get("seconds", 1), where)
        if not 0 < seconds <= DELAY_MAX_SECONDS:
            raise ValidationError(f"延时需在 1~{DELAY_MAX_SECONDS} 秒之间")
        clean["seconds"] = seconds
        return clean
    if device == "wait":
        # 「等待事件」：等到条件成立再继续。源的合法性与比较沿用「条件块」同一套
        # （_check_source + _clean_comparison），因此触发/条件能用的源与比较符这里都能用。
        _require(action, ("sensor", "op", "value"), "等待动作块")
        _check_source(action["sensor"], "等待动作块", vars_info, strict)
        if action["op"] not in COMPARATOR_IDS:
            raise ValidationError(f"等待动作块非法比较符: {action['op']}")
        value = _clean_comparison(action["sensor"], action["op"], action["value"],
                                  "等待动作块", vars_info, strict=strict)
        # 超时必填（#20 验收 3）：等待必须有上界，不能无限挂起规则动作线程。
        timeout = _as_number(action.get("timeout_sec"), "等待动作块的最长等待时长")
        if not 0 < timeout <= DELAY_MAX_SECONDS:
            raise ValidationError(f"等待超时需在 1~{DELAY_MAX_SECONDS} 秒之间")
        return {"device": "wait", "sensor": action["sensor"], "op": action["op"],
                "value": value, "timeout_sec": timeout}
    if device == "state":
        return _validate_state_action(action, clean, where, vars_info, strict)
    if device == "door":
        status = action.get("status", "open")
        if status not in ("open", "close"):
            raise ValidationError("门动作只能是 open/close")
        clean["status"] = status
    elif device == "window":
        status = action.get("status", "open")
        if status not in ("open", "close", "normal"):
            raise ValidationError("窗动作只能是 open/close/normal(半开45°)")
        clean["status"] = status
    elif device == "light":
        status = action.get("status", "on")
        if status not in ("on", "off"):
            raise ValidationError("灯动作只能是 on/off")
        brightness = int(_as_number(action.get("brightness", 100), where))
        clean.update({"status": status,
                      "brightness": max(0, min(100, brightness))})
        # 颜色（可选）：不填=普通白光；B 板是 8 颗 WS2812，整条同色
        color = str(action.get("color") or "").strip()
        if color:
            if color not in ("white", "red", "green", "blue",
                             "yellow", "purple", "cyan", "rgb"):
                raise ValidationError(
                    "灯颜色只能是 white/red/green/blue/yellow/purple/cyan/rgb")
            clean["color"] = color
            if color == "rgb":
                for ch in ("r", "g", "b"):
                    if action.get(ch) is None:
                        raise ValidationError("灯 RGB 需要 r/g/b 三个值(0~255)")
                    clean[ch] = max(0, min(255, int(_as_number(action.get(ch), where))))
            elif color == "white" and action.get("value") is not None:
                # 白光可指定 0-255 原始亮度（彩色预设不接受亮度）
                clean["value"] = max(0, min(255, int(_as_number(action.get("value"), where))))
    elif device == "fan":
        # op：set=设置为指定转速（旧规则默认，兼容）；on=以 speed 开启（speed 缺省
        # 用记忆转速）；off=关闭；toggle=在开/关之间切换（同一遥控器键按一次开、
        # 再按关），从关切换到开时使用 speed（缺省用记忆转速）。
        op = str(action.get("op") or "set").strip()
        if op not in ("set", "on", "off", "toggle"):
            raise ValidationError("风扇动作只能是 set(设置转速)/on/off/toggle(切换)")
        clean["op"] = op
        speed = int(_as_number(action.get("speed", 60), where))
        clean["speed"] = max(0, min(100, speed))
    elif device == "buzzer":
        # mode: beep(间歇，默认) / on(持续响) / off(停)
        mode = str(action.get("mode") or "beep").strip()
        if mode not in ("beep", "on", "off"):
            raise ValidationError("蜂鸣器模式只能是 beep(间歇)/on(持续)/off(停)")
        clean["mode"] = mode
        if mode == "beep":
            count = int(_as_number(action.get("count", 1), where))
            on_ms = int(_as_number(action.get("on_ms", 200), where))
            off_ms = int(_as_number(action.get("off_ms", 200), where))
            clean.update({"count": max(1, min(10, count)),
                          "on_ms": max(50, min(2000, on_ms)),
                          "off_ms": max(50, min(2000, off_ms))})
    elif device == "oled":
        # 可选 line：指定行号直发；不填则按文本里的换行自动分配到 0..7 行
        if action.get("line") not in (None, ""):
            line_no = int(_as_number(action.get("line"), where))
            if not 0 <= line_no <= 7:
                raise ValidationError("OLED 行号需在 0~7 之间")
            clean["line"] = line_no
        # 二选一：clear 清屏，或 text 显示文本（可含 {占位符}）
        if action.get("clear"):
            clean["clear"] = True
        else:
            raw = action.get("text")
            if not isinstance(raw, str):
                raise ValidationError("OLED 文本必须为字符串")
            text = raw.strip()
            if not text:
                raise ValidationError("OLED 文本不能为空（或请用 clear 清屏）")
            if len(text) > 200:
                raise ValidationError("OLED 文本过长（最多 200 字符）")
            clean["text"] = text
    elif device == "ir":
        # 红外发射：优先 address+command，其次十进制 32 位 code
        addr, cmd = action.get("address"), action.get("command")
        if addr is not None and cmd is not None:
            a = int(_as_number(addr, where))
            c = int(_as_number(cmd, where))
            if not 0 <= a <= 255 or not 0 <= c <= 255:
                raise ValidationError("NEC 地址/命令需在 0~255 之间")
            clean["address"] = a
            clean["command"] = c
        else:
            if action.get("code") is None:
                raise ValidationError("红外发射需要 code，或 address + command")
            code = int(_as_number(action.get("code"), where))
            if not 0 <= code <= 4294967295:
                raise ValidationError("NEC 码需为 0~4294967295（32 位无符号）")
            clean["code"] = code
    elif device == "ac":
        # 与 MCP 的 ac 工具一致：全部可选，空串/None = 该项不改，但至少要设一项
        if action.get("power") is not None:
            clean["power"] = bool(action["power"])
        mode = str(action.get("mode") or "").strip()
        if mode:
            if mode not in ("auto", "cool", "heat", "dry", "fan"):
                raise ValidationError("空调模式只能是 auto/cool/heat/dry/fan")
            clean["mode"] = mode
        temperature = action.get("temperature")
        if temperature not in (None, ""):
            temperature = round(_as_number(temperature, where) * 2) / 2
            if not 17 <= temperature <= 30:
                raise ValidationError("空调温度需在 17~30℃ 之间")
            clean["temperature"] = temperature
        fan = str(action.get("fan") or "").strip()
        if fan:
            # 唯一真源是执行层的 midea_ac.FAN_LEVELS；旧版数值档位（20/40/60/80/100）
            # 由 ac_state.normalize_fan_level 折算到最近的物理档位，此后全网只有一套枚举
            level = normalize_fan_level(fan)
            if level is None:
                raise ValidationError(
                    "空调风速只能是 " + "/".join(midea_ac.FAN_LEVELS))
            clean["fan"] = level
        for key in ("swing_ud", "swing_lr", "eco", "fzc"):
            if action.get(key) is not None:
                clean[key] = bool(action[key])
        timer = action.get("timer")
        if timer not in (None, ""):
            timer = round(_as_number(timer, where) * 2) / 2
            if not 0 <= timer <= 24:
                raise ValidationError("空调定时需在 0~24 小时之间（0=取消）")
            clean["timer"] = timer
        if len(clean) == 1:
            raise ValidationError("空调动作至少要设置一项（开关/模式/温度/风速/扫风/ECO/防直吹/定时）")
    elif device == "voice":
        act = str(action.get("action") or "wake").strip()
        if act not in ("wake", "say"):
            raise ValidationError("语音助手动作只能是 wake(唤醒)/say(播报)")
        clean["action"] = act
        text = str(action.get("text") or "").strip()
        if act == "say" and not text:
            raise ValidationError("语音播报需要填写文本")
        if len(text) > 200:
            raise ValidationError("语音文本过长（最多 200 字符）")
        if text:
            clean["text"] = text
    elif device == "http":
        # 二次开发出站通道：URL/正文都可含 {占位符}，运行时由引擎渲染。
        method = str(action.get("method") or "post").strip().lower()
        if method not in ("get", "post"):
            raise ValidationError(f"{where}HTTP 方法只能是 get/post")
        ok, value = webhook.check_format(action.get("url"))
        if not ok:
            raise ValidationError(f"{where}{value}")
        clean.update({"method": method, "url": value})
        if http_policy is not None:
            if not http_policy.get("enabled", True):
                raise ValidationError(
                    f"{where}HTTP 出站已关闭（web_config.yaml: "
                    "automation.http_enabled: false）")
            ok, why = webhook.check_url(
                value,
                allow_public=bool(http_policy.get("allow_public")),
                allowed_hosts=http_policy.get("allowed_hosts") or ())
            if not ok:
                raise ValidationError(f"{where}{why}")
        body = str(action.get("text") or "")
        if body:
            if len(body.encode("utf-8")) > webhook.MAX_BODY_BYTES:
                raise ValidationError(
                    f"{where}HTTP 正文不能超过 "
                    f"{webhook.MAX_BODY_BYTES} 字节（UTF-8）")
            clean["text"] = body
    return clean


STATE_OPS = ("set", "toggle", "add")


def _validate_state_action(action: dict, clean: dict, where: str,
                           vars_info: dict | None, strict: bool = True) -> dict:
    """「设置全局状态」动作校验。

    ``strict=True`` 且拿到变量定义（``vars_info``）时按变量的类型与选项校验 op 与
    取值：enum 必须落在 choices 内、toggle 只对是/否或双项选项成立、add 只对数字
    成立——这些原本要等运行期 ``GlobalStateStore.set_value`` 才拒绝，规则却已经存
    进库。``strict=False``（引擎读盘）下变量被删不再报错——否则删一个变量会清空
    整个规则集。
    """
    name = str(action.get("name") or "").strip()
    if not is_var_id(name):
        raise ValidationError(
            f"{where}需选择一个全局状态（先新建「📌 状态」条目）")
    spec = None
    if vars_info is not None:
        spec = vars_info.get(name)
        if spec is None and strict:
            raise ValidationError(f"{where}引用的全局状态不存在: {name}")
    op = str(action.get("op") or "set").strip()
    if op not in STATE_OPS:
        raise ValidationError(f"{where}全局状态操作只能是 set/toggle/add")
    clean["name"] = name
    clean["op"] = op
    type_ = spec.get("type") if spec else None
    choices = list(spec.get("choices") or []) if spec else []
    value = action.get("value")
    if op == "toggle":
        if spec is not None:
            if type_ not in ("bool", "enum"):
                raise ValidationError(f"{where}只有「是/否」或选项状态可以切换")
            if type_ == "enum" and len(choices) != 2:
                raise ValidationError(f"{where}只有两项的选项状态可以切换")
        return clean
    if op == "add":
        if spec is not None and type_ != "number":
            raise ValidationError(f"{where}只有数字状态可以加减")
        if value in (None, ""):
            value = 1
        clean["value"] = _as_number(value, f"{where}加减量")
        return clean
    if value is None or (isinstance(value, str) and value.strip() == ""):
        # 注意不能写 `value == ""`：False == "" 在 Python 里成立，会把布尔 False 误判成空
        raise ValidationError(f"{where}设置全局状态需要填值")
    if type_ == "number":
        clean["value"] = _as_number(value, f"{where}值")
    elif type_ == "bool" or (type_ is None and isinstance(value, bool)):
        # 宽松模式下真布尔原样保留（enum/text 变量本不该收到 bool，交给写侧强校验）
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            value = value.strip().lower() == "true"
        if not isinstance(value, bool):
            raise ValidationError(f"{where}「是/否」状态的值只能是 是/否")
        clean["value"] = value
    else:                                    # enum / text / 宽松模式
        text = str(value)
        if choices and text not in choices:
            raise ValidationError(
                f"{where}「{spec.get('label', name)}」只能是 "
                f"{'/'.join(map(str, choices))} 之一")
        clean["value"] = text
    return clean


def validate_rule(rule: dict, vars_info: dict | None = None,
                  http_policy: dict | None = None, strict: bool = True) -> dict:
    _require(rule, ("name", "trigger", "actions"), "规则")
    name = str(rule["name"]).strip()
    if not name:
        raise ValidationError("规则名称不能为空")
    trigger = validate_trigger(rule["trigger"], vars_info, strict)
    conditions = [validate_condition(c, vars_info, strict)
                  for c in (rule.get("conditions") or [])]
    match = rule.get("match", "all")
    if match not in ("all", "any"):
        raise ValidationError("条件组合方式只能是 all/any")
    actions = [validate_action(a, "执行块", vars_info, http_policy, strict)
               for a in (rule.get("actions") or [])]
    if not actions:
        raise ValidationError("每条规则至少要有一个执行动作")
    else_actions = [validate_action(a, "否则块", vars_info, http_policy, strict)
                    for a in (rule.get("else_actions") or [])]
    raw_cooldown = rule.get("cooldown", 3)
    cooldown = 3.0 if raw_cooldown is None else float(raw_cooldown)
    clean = {
        "id": str(rule.get("id") or "").strip() or None,   # None 时由引擎补 id
        "name": name[:50],
        "enabled": bool(rule.get("enabled", True)),
        "trigger": trigger,
        "match": match,
        "conditions": conditions,
        "actions": actions,
        "else_actions": else_actions,
        "cooldown": max(0.0, min(cooldown, 3600.0)),
    }
    # 内置默认规则带 preset 标记（仅用于「是否已注入过」的判断，用户可自由改名/删除）
    preset = str(rule.get("preset") or "").strip()
    if preset:
        clean["preset"] = preset[:40]
    return clean


def validate_rules(payload, vars_info: dict | None = None,
                   http_policy: dict | None = None,
                   strict: bool = True) -> list[dict]:
    """payload 可以是 {'rules': [...]} 或直接 [...]。

    ``strict=False`` 是引擎读盘用的宽松模式：变量被删、历史脏阈值都不再拒绝，
    只做能做的归一化（否则一条坏规则会连带整表被丢弃）。
    ``strict=True``（默认，页面保存与直接调用）会拒绝：引用不存在的全局状态、
    比较符/阈值与源类型不匹配、enum 取值越界。``vars_info``（``{变量id:
    {type, choices, label}}``）用于解析 ``g:`` 变量的类型。
    http_policy 同理：None 只查 URL 格式，传策略字典则连主机放行一起查。
    """
    if isinstance(payload, dict):
        payload = payload.get("rules")
    if not isinstance(payload, list):
        raise ValidationError("规则列表格式错误")
    if len(payload) > 80:
        raise ValidationError("规则数量不能超过 80 条")
    return [validate_rule(r, vars_info, http_policy, strict) for r in payload]
