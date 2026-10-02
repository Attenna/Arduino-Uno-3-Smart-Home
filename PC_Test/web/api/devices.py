"""设备控制：门/窗/灯/风扇走 MCP 直连 Arduino。

与别组旧实现的区别：按钮点击不再直接乐观写库，而是先经 MCP 向 Module B 下发
JSON 命令；只有收到 B 板 ACK 后才更新 system_status 并写历史，保证 UI 状态
与真实硬件一致。串口离线时返回 503，不产生虚假状态。
"""
import logging
import threading
import time

from flask import Blueprint, jsonify, request

import midea_ac

from .. import extensions
from ..ac_state import AC_KEYS, ac_state_from_db, write_ac_state
from ..extensions import db

logger = logging.getLogger(__name__)

bp = Blueprint("devices", __name__)


def _note_manual(device, **state):
    """把手动操作广播给自动化引擎（不含任何设备专属策略）。

    用户策略：自动/离家中从面板（或语音）手动操作任一设备，全屋转为「手动」，
    保持刚设的状态不被自动逻辑覆盖；再按触摸键或页面「自动」即恢复自动调节。

    「手动优先 30 秒让位」原先硬编码在引擎的 home_mode 状态机里，现在只是一条
    通用事件：manual_mark_x / manual_clear_x 预设收到 ``manual_control`` 后维护
    ``g:手动优先_x`` 与 ``g:全屋模式``，设备类预设带 ``g:手动优先_x == false``
    条件自行让位。

    风扇额外同步一次 ``note_external``：引擎对风扇下发做去重（``_last_cmd``），
    面板手动设了 60% 后水位仍是旧值，规则就会把「已经是 60%」再发一遍。
    """
    automation = getattr(extensions, "automation", None)
    if automation is None:
        return
    try:
        automation.on_event({"event": "manual_control", "device": device,
                            "ts": time.time()})
    except Exception:                                    # noqa: BLE001
        logger.debug("广播 manual_control 事件失败", exc_info=True)
    if device == "fan" and "speed" in state:
        try:
            automation.note_external("fan", int(state.get("speed") or 0))
        except Exception:                                # noqa: BLE001
            logger.debug("同步风扇下发水位失败", exc_info=True)


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


# ==================== 空调（美的红外）====================

def _ac_state_from_db() -> midea_ac.AcState:
    return ac_state_from_db(db)


def _opt_bool(data, key):
    """三态布尔：缺省/None = 不改；其余必须是真布尔或 0/1。"""
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise ValueError(f"{key} 需为 true/false")


def _record_ac(state, who="面板"):
    write_ac_state(db, state)
    _note_manual("ac", reason=f"{who}手动操作空调，全屋切到手动模式并保持当前状态")


def _pct(value, default=0):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _hardware_error(text):
    return jsonify({"error": "硬件控制失败", "error_en": "Hardware command failed",
                    "detail": text}), 503


def _hw_call(method, *args, **kwargs):
    """调用硬件桥方法；桥未初始化时返回 503 而不是抛 AttributeError(500)。"""
    bridge = extensions.bridge
    if bridge is None:
        return False, "硬件服务未启动（硬件桥未初始化）"
    return getattr(bridge, method)(*args, **kwargs)


# ==================== 设备命令收口器 ====================

class _DeviceGate:
    """所有手动设备控制的单一收口点：串行化 + 合并连点 + 拒绝乱序 + 状态幂等。

    背景：手机弱网 + 串口往返慢（舵机/红外可达数秒）时，一次操作会在几秒内
    产生多个请求——用户以为没点上而连点、移动端触摸双发、请求延迟到达。若
    全部照单下发串口，排队的旧命令可能晚于「关闭」执行，表现为风扇「关了又
    自己开」。收口规则：

    * 同设备命令串行执行，排队期间到达的新目标**覆盖**旧目标（desired-state），
      硬件只执行最终意图，被合并的请求直接成功返回（不报错、不下发）；
    * 每个页面实例带 ``_cid`` + 单调 ``_seq``；同一实例迟到的旧 seq 直接丢弃，
      杜绝弱网下请求乱序到达造成的「旧意图覆盖新意图」；
    * 目标与数据库当前状态一致则不下发（无时间窗幂等），任何来源的同值重放
      都不会再动硬件；
    * 执行失败不推进水位，保留最新 desired，允许前端重试。

    自动化引擎走 bridge 直连且自带下发去重，不经此收口器。
    """

    DEVICES = ("door", "window", "light", "fan", "ac")

    def __init__(self):
        self._submit_lock = threading.Lock()
        self._exec_locks = {d: threading.Lock() for d in self.DEVICES}
        # desired: (client_id, seq, value)；applied: {client_id: 已服务水位 seq}
        self._state = {d: {"desired": None, "applied": {}} for d in self.DEVICES}

    def submit(self, device, value, cid, seq, run, get_current=None):
        """提交一条设备命令。

        run(value) -> (ok, msg)：真正下发并在成功后写库（记录实际执行的值）。
        get_current() -> 与 value 同构的当前状态，None 表示不做状态幂等。
        返回 (outcome, value, ok, msg)，outcome ∈ executed/noop/stale。
        """
        st = self._state[device]
        anon = not cid
        origin = _req_origin()
        with self._submit_lock:
            if not anon:
                if seq <= st["applied"].get(cid, 0):
                    logger.info("设备收口 %s 丢弃旧命令 seq=%s（已服务）%s",
                                device, seq, origin)
                    return "stale", (get_current() if get_current else None), True, ""
                d = st["desired"]
                if d is not None and d[0] == cid and d[1] > seq:
                    logger.info("设备收口 %s 丢弃旧命令 seq=%s（已有更新意图排队）%s",
                                device, seq, origin)
                    return "stale", (get_current() if get_current else None), True, ""
            token = cid if not anon else "\x00anon"
            order = seq if not anon else time.monotonic_ns()
            st["desired"] = (token, order, value)
        with self._exec_locks[device]:
            with self._submit_lock:
                d = st["desired"]
                if d is None:
                    # 自己排队期间，更新的意图已被先拿到锁的线程完整服务
                    return "stale", (get_current() if get_current else None), True, ""
                token2, order2, value2 = d
                if token2 != "\x00anon" and st["applied"].get(token2, 0) >= order2:
                    return "stale", (get_current() if get_current else None), True, ""
                current = get_current() if get_current else None
            # 状态幂等：硬件/库中已是目标值，任何重放都不再下发
            if current is not None and current == value2:
                with self._submit_lock:
                    if token2 != "\x00anon":
                        st["applied"][token2] = max(
                            st["applied"].get(token2, 0), order2)
                    if st["desired"] == (token2, order2, value2):
                        st["desired"] = None
                logger.info("设备收口 %s 同值跳过 value=%r %s", device, value2, origin)
                return "noop", value2, True, ""
            t0 = time.monotonic()
            ok, msg = run(value2)
            elapsed = time.monotonic() - t0
            with self._submit_lock:
                if ok and token2 != "\x00anon":
                    st["applied"][token2] = max(
                        st["applied"].get(token2, 0), order2)
                if ok and st["desired"] == (token2, order2, value2):
                    st["desired"] = None
            logger.info("设备收口 %s %s value=%r cid=%s seq=%s %.2fs %s%s",
                        device, "下发成功" if ok else "下发失败", value2,
                        token2 if token2 != "\x00anon" else "-",
                        order2 if token2 != "\x00anon" else "-",
                        elapsed, origin, f" msg={msg[:120]}" if not ok else "")
            return "executed", value2, ok, msg


gate = _DeviceGate()


def _client_token(data):
    """取前端页面实例标识与单调序号；缺失（curl/旧缓存页）返回 (None, None)。"""
    cid = str(data.get("_cid") or "")[:40]
    try:
        seq = int(data.get("_seq"))
    except (TypeError, ValueError):
        return None, None
    return (cid, seq) if cid else (None, None)


def _req_origin() -> str:
    """请求来源描述：IP + Referer 页面 + UA 片段。

    用来钉死「这条设备命令到底是哪个页面/标签页发的」——历史上「点进自动化页风扇
    自启动」这类问题最难查的就是找不到发起者，面板、轮询、程序化事件在日志里长得一样。
    """
    try:
        ip = request.remote_addr or "?"
        ref = (request.referrer or request.headers.get("Referer") or "-").strip() or "-"
        ua = (request.headers.get("User-Agent") or "-")[:70]
    except Exception:                                # noqa: BLE001
        # 非请求上下文（后台线程复用收口器）不能抛，退化为未知来源
        return "ip=? ref=- ua='-'"
    return f"ip={ip} ref={ref} ua={ua!r}"


# ==================== 门 ====================

@bp.route("/api/door", methods=["GET"])
def get_door_status():
    status = db.get_current_status()
    return jsonify({"door_status": status.get("door_status", "closed")})


@bp.route("/api/door", methods=["POST"])
def control_door():
    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "closed")
    if new_status not in ("open", "closed"):
        return jsonify({"error": "无效状态，只能是 open 或 closed"}), 400
    cid, seq = _client_token(data)

    def _run(v):
        ok, msg = _hw_call("control_door", v)
        if ok:
            _record_door(v)
        return ok, msg

    outcome, value, ok, msg = gate.submit(
        "door", new_status, cid, seq, _run,
        get_current=lambda: db.get_current_status().get("door_status", "closed"))
    if not ok:
        return _hardware_error(msg)
    shown = value if outcome != "stale" else \
        db.get_current_status().get("door_status", "closed")
    if outcome == "executed":
        message = f"门已{'打开' if shown == 'open' else '关闭'}"
    elif outcome == "noop":
        message = f"门已经是{'打开' if shown == 'open' else '关闭'}状态"
    else:
        message = f"已按最新操作执行（门已{'打开' if shown == 'open' else '关闭'}）"
    return jsonify({"door_status": shown, "message": message,
                    "message_en": f"Door {'opened' if shown == 'open' else 'closed'}"})


# ==================== 窗 ====================

@bp.route("/api/window", methods=["GET"])
def get_window_status():
    status = db.get_current_status()
    return jsonify({"window_status": status.get("window_status", "closed")})


@bp.route("/api/window", methods=["POST"])
def control_window():
    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "closed")
    if new_status not in ("open", "closed"):
        return jsonify({"error": "无效状态"}), 400
    cid, seq = _client_token(data)

    def _run(v):
        ok, msg = _hw_call("control_window", v)
        if ok:
            _record_window(v)
        return ok, msg

    outcome, value, ok, msg = gate.submit(
        "window", new_status, cid, seq, _run,
        get_current=lambda: db.get_current_status().get("window_status", "closed"))
    if not ok:
        return _hardware_error(msg)
    shown = value if outcome != "stale" else \
        db.get_current_status().get("window_status", "closed")
    if outcome == "executed":
        message = f"窗户已{'打开' if shown == 'open' else '关闭'}"
    elif outcome == "noop":
        message = f"窗户已经是{'打开' if shown == 'open' else '关闭'}状态"
    else:
        message = f"已按最新操作执行（窗户已{'打开' if shown == 'open' else '关闭'}）"
    return jsonify({"window_status": shown, "message": message,
                    "message_en": f"Window {'opened' if shown == 'open' else 'closed'}"})


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
    if light_status == "off":
        brightness = 0
    cid, seq = _client_token(data)
    target = (light_status, brightness)

    def _run(v):
        status, level = v
        ok, msg = _hw_call("control_light", status, level)
        if ok:
            _record_light(status, level)
        return ok, msg

    # 灯光**不做基于 DB 的状态幂等**（与 /api/fan 同理，见那里的说明）：web 以
    # --no-serial 运行，读不到 B 板真实状态，db.light_status/light_brightness 只是
    # 「上次软件下发的值」。若拿它做幂等，一旦灯被外部关掉、或 B 板复位后固件回默认
    # （DB 仍记着 on/100），用户再点「开灯」会被判成同值直接吞掉 → 命令根本没下发，
    # 表现为「按下没反应」。同客户端连点重放仍由 cid+seq 水位拦截；control_light 是
    # 绝对指令（white(value)/off），重复下发无害。
    outcome, _, ok, msg = gate.submit("light", target, cid, seq, _run)
    if not ok:
        return _hardware_error(msg)
    row = db.get_current_status()
    status_shown = row.get("light_status", "off")
    shown = int(row.get("light_brightness") or 0)
    if outcome == "executed":
        message = f"灯光已{'打开' if status_shown == 'on' else '关闭'}，亮度: {shown}%"
        message_en = (f"Light {'turned on' if status_shown == 'on' else 'turned off'}, "
                      f"brightness: {shown}%")
    else:
        message = f"已按最新操作执行（灯光 {status_shown}/{shown}%）"
        message_en = f"Latest command applied (light {status_shown}/{shown}%)"
    return jsonify({"light_status": status_shown, "light_brightness": shown,
                    "message": message, "message_en": message_en})


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
    data = request.get_json(silent=True) or {}
    speed = _pct(data.get("speed"), 0)
    cid, seq = _client_token(data)

    def _run(v):
        ok, msg = _hw_call("control_fan", v)
        if ok:
            _record_fan(v)
        return ok, msg

    # 风扇**不做基于 DB 的状态幂等**：web 以 --no-serial 运行，读不到 B 板真实状态，
    # db.fan_speed 只是「上次软件下发的值」，不能当作硬件真值。若拿它做幂等，一旦
    # 风扇被外部原因误开（DB 仍为 0），用户点「关」（0）会被判成同值直接吞掉，
    # 命令根本不下发 → 风扇永远关不掉（现象：面板 0% 但物理在转）。
    # 同客户端连点重放仍由 cid+seq 水位拦截；set_speed/off 本身是绝对指令，重复下发无害。
    outcome, value, ok, msg = gate.submit("fan", speed, cid, seq, _run)
    if not ok:
        return _hardware_error(msg)
    shown = value if outcome != "stale" else \
        int(db.get_current_status().get("fan_speed") or 0)
    if outcome == "executed":
        message = f"风扇速度已设为 {shown}%"
        message_en = f"Fan speed set to {shown}%"
    else:
        message = f"已按最新操作执行（风扇 {shown}%）"
        message_en = f"Latest command applied (fan {shown}%)"
    return jsonify({"fan_speed": shown, "message": message,
                    "message_en": message_en})


# ==================== 空调（美的红外遥控）====================

@bp.route("/api/ac", methods=["GET"])
def get_ac_status():
    return jsonify(_ac_state_from_db().snapshot())


@bp.route("/api/ac", methods=["POST"])
def control_ac():
    """只传要改的字段；其余按数据库里的当前状态补齐后整帧下发。

    红外指令里一帧就带齐了开关/模式/温度/风速，所以这里下发的是**完整状态**
    而不是增量——MCP 进程重启后第一次指令也能一次带齐全部设定。
    """
    data = request.get_json(silent=True) or {}
    try:
        target, changed = midea_ac.apply_overrides(
            _ac_state_from_db(),
            power=_opt_bool(data, "power"),
            mode=data.get("mode"),
            temperature=data.get("temperature"),
            fan=data.get("fan"),
            swing_ud=_opt_bool(data, "swing_ud"),
            swing_lr=_opt_bool(data, "swing_lr"),
        )
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"空调参数无效：{e}",
                        "error_en": f"Invalid AC parameter: {e}"}), 400

    payload = target.snapshot()
    if not changed:
        return jsonify({**payload, "message": "空调状态未变化",
                        "message_en": "No change"})
    cid, seq = _client_token(data)

    def _run(v):
        payload2, target2 = v
        ok, msg = _hw_call("control_ac", **payload2)
        if ok:
            _record_ac(target2)
        return ok, msg

    # 空调整帧天然幂等，这里只需串行化 + 连点合并 + seq 防乱序（不做状态比对）
    outcome, _, ok, msg = gate.submit(
        "ac", (payload, target), cid, seq, _run, get_current=None)
    if not ok:
        return _hardware_error(msg)
    snap = _ac_state_from_db().snapshot()
    if outcome == "stale":
        return jsonify({**snap, "message": "已按最新操作执行",
                        "message_en": "Latest command applied"})
    return jsonify({**snap, "message": "空调已更新",
                    "message_en": "AC updated"})


# ==================== 语音动作回传（与面板等效）====================

@bp.route("/api/devices/manual_report", methods=["POST"])
def manual_report():
    """语音助手执行完硬件动作后回传，做与面板一致的记账。

    语音进程独占串口、直连 MCP，web 侧看不到它的调用，因此仪表盘状态/历史都会
    落后于真实硬件。语音在动作成功后把「哪个设备变成什么状态」回传到这里：本
    接口**只记账、不下发硬件**（动作已经执行完毕），使语音与面板产生等效效果
    ——相同状态、相同历史记录，同样广播 manual_control 让积木切到「手动优先」。
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
    if device == "ac":
        # 空调是"合并式"状态：语音只报变化的字段，这里按 DB 当前值补齐
        state = data.get("state")
        if not isinstance(state, dict):
            return jsonify({"error": "空调回传需要 state 对象"}), 400
        try:
            target, _ = midea_ac.apply_overrides(
                _ac_state_from_db(),
                **{k: v for k, v in state.items() if k in AC_KEYS})
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"空调参数无效：{e}"}), 400
        _record_ac(target, who=who)
        return jsonify({"ok": True, **target.snapshot()})

    return jsonify({"error": f"不支持的设备: {device or '(空)'}",
                    "error_en": f"Unsupported device: {device or '(empty)'}"}), 400
