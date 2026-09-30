"""设备控制：门/窗/灯/风扇走 MCP 直连 Arduino；空调为虚拟状态（B 板无空调）。

与别组旧实现的区别：按钮点击不再直接乐观写库，而是先经 MCP 向 Module B 下发
JSON 命令；只有收到 B 板 ACK 后才更新 system_status 并写历史，保证 UI 状态
与真实硬件一致。串口离线时返回 503，不产生虚假状态。
"""
import logging

from flask import Blueprint, jsonify, request

from .. import extensions
from ..extensions import db

logger = logging.getLogger(__name__)

bp = Blueprint("devices", __name__)


def _note_manual(device, **state):
    """告知全屋状态机这是一次手动操作：切到「手动」并同步去重缓存。

    用户策略：自动/离家中从面板（或语音）手动操作任一设备，全屋转为「手动」，
    保持刚设的状态不被自动逻辑覆盖；再按触摸键或页面「自动」即恢复自动调节。
    """
    automation = getattr(extensions, "automation", None)
    home_mode = getattr(automation, "home_mode", None) if automation else None
    if home_mode is None:
        return
    try:
        home_mode.note_manual_control(device, **state)
    except Exception:                                # noqa: BLE001
        logger.debug("通知全屋模式失败", exc_info=True)


def _record_door(new_status, who="面板"):
    db.update_status(door_status=new_status)
    db.add_door_window_event("door", "前门", new_status)
    _note_manual("door", reason=f"{who}手动开关门，全屋切到手动模式并保持当前状态")


def _record_window(new_status):
    db.update_status(window_status=new_status)
    db.add_door_window_event("window", "客厅窗户", new_status)
    _note_manual("window", status=new_status)


def _record_light(status, brightness):
    db.update_status(light_status=status, light_brightness=brightness)
    db.add_light_event("客厅主灯", status, brightness)
    _note_manual("light", status=status, brightness=brightness)


def _record_fan(speed):
    db.update_status(fan_speed=speed)
    _note_manual("fan", speed=speed)


def _pct(value, default=0):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _hardware_error(text):
    return jsonify({"error": "硬件控制失败", "error_en": "Hardware command failed",
                    "detail": text}), 503


def _hw_call(method, *args):
    """调用硬件桥方法；桥未初始化时返回 503 而不是抛 AttributeError(500)。"""
    bridge = extensions.bridge
    if bridge is None:
        return False, "硬件服务未启动（硬件桥未初始化）"
    return getattr(bridge, method)(*args)


# ==================== 门 ====================

@bp.route("/api/door", methods=["GET"])
def get_door_status():
    status = db.get_current_status()
    return jsonify({"door_status": status.get("door_status", "closed")})


@bp.route("/api/door", methods=["POST"])
def control_door():
    new_status = (request.get_json(silent=True) or {}).get("status", "closed")
    if new_status not in ("open", "closed"):
        return jsonify({"error": "无效状态，只能是 open 或 closed"}), 400
    ok, msg = _hw_call("control_door", new_status)
    if not ok:
        return _hardware_error(msg)
    _record_door(new_status)
    action = "opened" if new_status == "open" else "closed"
    return jsonify({
        "door_status": new_status,
        "message": f"门已{'打开' if new_status == 'open' else '关闭'}",
        "message_en": f"Door {action}",
    })


# ==================== 窗 ====================

@bp.route("/api/window", methods=["GET"])
def get_window_status():
    status = db.get_current_status()
    return jsonify({"window_status": status.get("window_status", "closed")})


@bp.route("/api/window", methods=["POST"])
def control_window():
    new_status = (request.get_json(silent=True) or {}).get("status", "closed")
    if new_status not in ("open", "closed"):
        return jsonify({"error": "无效状态"}), 400
    ok, msg = _hw_call("control_window", new_status)
    if not ok:
        return _hardware_error(msg)
    _record_window(new_status)
    action = "opened" if new_status == "open" else "closed"
    return jsonify({
        "window_status": new_status,
        "message": f"窗户已{'打开' if new_status == 'open' else '关闭'}",
        "message_en": f"Window {action}",
    })


@bp.route("/api/door_window/history")
def get_door_window_history():
    hours = request.args.get("hours", 24, type=int)
    return jsonify(db.get_door_window_history(hours))


# ==================== 灯 ====================

@bp.route("/api/light", methods=["GET"])
def get_light_status():
    status = db.get_current_status()
    return jsonify({
        "light_status": status.get("light_status", "off"),
        "light_brightness": status.get("light_brightness", 0),
    })


@bp.route("/api/light", methods=["POST"])
def control_light():
    data = request.get_json(silent=True) or {}
    light_status = data.get("status", "off")
    brightness = _pct(data.get("brightness"), 0)
    if light_status == "on" and brightness == 0:
        brightness = 100
    ok, msg = _hw_call("control_light", light_status, brightness)
    if not ok:
        return _hardware_error(msg)
    _record_light(light_status, brightness)
    return jsonify({
        "light_status": light_status,
        "light_brightness": brightness,
        "message": f"灯光已{'打开' if light_status == 'on' else '关闭'}，亮度: {brightness}%",
        "message_en": (f"Light {'turned on' if light_status == 'on' else 'turned off'}, "
                       f"brightness: {brightness}%"),
    })


@bp.route("/api/light/history")
def get_light_history():
    hours = request.args.get("hours", 24, type=int)
    return jsonify(db.get_light_history(hours))


# ==================== 风扇 ====================

@bp.route("/api/fan", methods=["GET"])
def get_fan_status():
    status = db.get_current_status()
    return jsonify({"fan_speed": status.get("fan_speed", 0)})


@bp.route("/api/fan", methods=["POST"])
def control_fan():
    speed = _pct((request.get_json(silent=True) or {}).get("speed"), 0)
    ok, msg = _hw_call("control_fan", speed)
    if not ok:
        return _hardware_error(msg)
    _record_fan(speed)
    return jsonify({
        "fan_speed": speed,
        "message": f"风扇速度已设为 {speed}%",
        "message_en": f"Fan speed set to {speed}%",
    })


# ==================== 语音动作回传（与面板等效）====================

@bp.route("/api/devices/manual_report", methods=["POST"])
def manual_report():
    """语音助手执行完硬件动作后回传，做与面板一致的记账。

    语音进程独占串口、直连 MCP，web 侧看不到它的调用，因此仪表盘状态/历史/
    全屋模式都会落后于真实硬件。语音在动作成功后把「哪个设备变成什么状态」
    回传到这里：本接口**只记账、不下发硬件**（动作已经执行完毕），使语音与
    面板产生等效效果——相同状态、相同历史记录、同样切到「手动」模式。
    """
    data = request.get_json(silent=True) or {}
    device = str(data.get("device", "")).lower()
    who = "语音" if data.get("source") == "voice" else str(data.get("source") or "外部")

    if device == "door":
        status = "open" if data.get("status") == "open" else "closed"
        _record_door(status, who=who)
        return jsonify({"ok": True, "door_status": status})
    if device == "window":
        status = data.get("status")
        if status not in ("open", "closed", "normal"):
            return jsonify({"error": "无效状态"}), 400
        _record_window(status)
        return jsonify({"ok": True, "window_status": status})
    if device == "light":
        status = "on" if data.get("status") == "on" else "off"
        brightness = _pct(data.get("brightness"), 0)
        if status == "on" and brightness == 0:
            brightness = 100
        _record_light(status, brightness)
        return jsonify({"ok": True, "light_status": status,
                        "light_brightness": brightness})
    if device == "fan":
        speed = _pct(data.get("speed"), 0)
        _record_fan(speed)
        return jsonify({"ok": True, "fan_speed": speed})

    return jsonify({"error": f"不支持的设备: {device or '(空)'}",
                    "error_en": f"Unsupported device: {device or '(empty)'}"}), 400


# ==================== 空调（虚拟设备：Module B 无空调执行器）====================

@bp.route("/api/ac", methods=["GET"])
def get_ac_status():
    status = db.get_current_status()
    return jsonify({
        "ac_status": status.get("ac_status", "off"),
        "ac_temperature": status.get("ac_temperature", 26),
    })


@bp.route("/api/ac", methods=["POST"])
def control_ac():
    data = request.get_json(silent=True) or {}
    ac_status = data.get("status", "off")
    ac_temp = max(16, min(30, int(data.get("temperature", 26) or 26)))
    # 空调仅记录期望状态；接入真实空调后可在此改走 HA / 红外 MCP 工具
    db.update_status(ac_status=ac_status, ac_temperature=ac_temp)
    return jsonify({
        "ac_status": ac_status,
        "ac_temperature": ac_temp,
        "message": f"空调已{'开启' if ac_status == 'on' else '关闭'}，温度设为 {ac_temp}°C",
        "message_en": f"AC {'turned on' if ac_status == 'on' else 'turned off'}, "
                      f"temp set to {ac_temp}°C",
    })
