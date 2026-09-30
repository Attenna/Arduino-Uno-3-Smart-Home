"""全屋模式状态机（引擎级联动）：自动 / 手动 / 离家 + 设备级强制覆盖。

「十条全屋自动化」里跨设备、带时序的联动无法用单条积木规则表达，
统一收敛到本状态机，由自动化引擎在**快照 / 事件 / 滴答**三个入口驱动：

    需求1  PIR 检测到人靠近门逗留 >=30s 且未通过门禁 ─▶ 蜂鸣器拉响
    需求2  门禁通过 ─▶ 开锁，10s 后自动关门
    需求3  检测到人后门舵机动作 = 进门 → 全屋自动；无人时门动作 = 出门 → 全屋关闭
    需求4  自动模式温度 > 阈值 ─▶ 风扇全速；红外键1 循环 强制关→强制开→自动
    需求5  自动模式光敏调光；红外键2/3 循环 保持→暗→半亮→全亮→自动
    需求6  雨水关窗、雨停恢复 45°；烟雾 ─▶ 蜂鸣器持续报警
    需求8  触摸按下 ─▶ 手动（保持当前状态）；再按 ─▶ 恢复自动
    需求9  烟雾/雨水安全联动在任何模式（含离家/手动/禁用）下都生效

设计约束：
- 任何异常只写日志，绝不拖垮 bridge 轮询线程；
- 动作经 bridge 下发（relay → voice → Module B），与积木规则共用同一通道；
- 状态与配置持久化到 data/home_mode.json，容器重建不丢。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_AWAY = "away"
MODES = (MODE_AUTO, MODE_MANUAL, MODE_AWAY)
MODE_LABELS = {MODE_AUTO: "自动", MODE_MANUAL: "手动", MODE_AWAY: "离家"}

# 风扇红外覆盖档位循环（需求4）：强制关 → 强制开 → 自动 → …
FAN_LABELS = {None: "自动", "on": "强制开", "off": "强制关"}
_FAN_CYCLE = {"off": "on", "on": None, None: "off"}

# 灯光档位循环（需求5）：自动 → 保持 → 暗 → 半亮 → 全亮 → 自动
LIGHT_LABELS = {"auto": "自动", "hold": "保持当前", "dark": "暗",
                "half": "半亮", "bright": "全亮"}
_LIGHT_CYCLE = ["hold", "dark", "half", "bright", "auto"]

# 红外键码（NEC，ADDRESS 0x00；见派上 ~/ir_remote_keymap.txt）
IR_FAN_KEYS = (0x45,)          # 键'1'
IR_LIGHT_KEYS = (0x46, 0x47)   # 键'2'/'3'

DEFAULT_CONFIG = {
    "enabled": True,
    "mode": MODE_AUTO,
    "fan_override": None,          # None=自动调节；"on"/"off"=红外强制
    "light_level": "auto",         # auto/hold/dark/half/bright
    "temp_threshold": 25.0,        # 需求4：高于此温度自动开风扇
    "fan_auto_speed": 100,         # 需求4：默认全速
    "door_dwell_sec": 30.0,        # 需求1：靠近门逗留报警阈值
    "dwell_only_away": True,       # 需求1：仅在「离家」模式做逗留报警，避免家人走动误响
    "door_close_sec": 10.0,        # 需求2：开门后自动关门延时
    "pir_recent_sec": 60.0,        # 判定「检测到人」的时间窗
    "smoke_realarm_sec": 15.0,     # 烟雾未消散时的重复报警间隔
    "smoke_confirm_sec": 5.0,      # 需连续检测到烟雾该时长才报警（滤除单帧抖动）
    "smoke_realarm_max": 3,        # 未消散时的重复报警次数上限，之后只记录不再鸣响
    "light_dark_max": 200,         # 需求5：光照 <= 此值 → 全亮
    "light_mid_max": 500,          # 需求5：光照 <= 此值 → 半亮，否则关灯
    "bright_pct": 100,
    "half_pct": 50,
    "dark_pct": 30,
}

_NUMERIC_KEYS = ("temp_threshold", "door_dwell_sec", "door_close_sec",
                 "pir_recent_sec", "smoke_realarm_sec", "smoke_confirm_sec",
                 "light_dark_max", "light_mid_max")
_INT_KEYS = ("fan_auto_speed", "bright_pct", "half_pct", "dark_pct",
             "smoke_realarm_max")


class HomeModeManager:
    """全屋模式 + 强制覆盖状态机。线程安全（RLock 保护配置）。"""

    def __init__(self, bridge, db, path):
        self.bridge = bridge
        self.db = db
        self.path = Path(path)
        self._lock = threading.RLock()
        self.cfg = dict(DEFAULT_CONFIG)
        self._load()

        # ── 运行期状态（不持久化） ──
        self._snapshot: dict = {}
        self._prev_touch = False
        self._pir_since = 0.0          # 本轮 PIR 起始时刻（0=当前无人）
        self._pir_last_seen = 0.0      # 最近一次检测到人的时刻
        self._pir_alarm_done = False   # 本轮逗留是否已报警
        self._door_granted_at = 0.0    # 最近一次门禁通过时刻
        self._door_close_at = 0.0      # 待自动关门时刻（0=无）
        self._smoke_active = False
        self._smoke_since = 0.0
        self._smoke_alarms = 0
        self._smoke_last_alarm = 0.0
        self._rain_wet = False
        self._last_fan = None          # 最近下发的风扇转速（去重）
        self._last_light = None        # 最近下发的 (status, brightness)
        self._last_window = None       # 最近下发的窗状态
        self._last_reason = ""

    # ==================== 配置与持久化 ====================

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for key in DEFAULT_CONFIG:
                    if key in data:
                        self.cfg[key] = data[key]
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 配置读取失败: %s", e)
        self._normalize()

    def _normalize(self) -> None:
        if self.cfg.get("mode") not in MODES:
            self.cfg["mode"] = MODE_AUTO
        if self.cfg.get("fan_override") not in FAN_LABELS:
            self.cfg["fan_override"] = None
        if self.cfg.get("light_level") not in LIGHT_LABELS:
            self.cfg["light_level"] = "auto"
        self.cfg["enabled"] = bool(self.cfg.get("enabled", True))
        raw = self.cfg.get("dwell_only_away", True)
        if isinstance(raw, str):
            raw = raw.strip().lower() not in ("0", "false", "no", "off", "")
        self.cfg["dwell_only_away"] = bool(raw)
        for key in _NUMERIC_KEYS:
            try:
                self.cfg[key] = float(self.cfg[key])
            except (TypeError, ValueError):
                self.cfg[key] = float(DEFAULT_CONFIG[key])
        for key in _INT_KEYS:
            try:
                self.cfg[key] = max(0, min(100, int(self.cfg[key])))
            except (TypeError, ValueError):
                self.cfg[key] = int(DEFAULT_CONFIG[key])

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 配置保存失败: %s", e)

    def configure(self, reason: str = "页面设置", **kw) -> dict:
        """更新配置并落盘。fan_override 允许显式传 None 表示回到自动。"""
        with self._lock:
            prev_mode = self.cfg["mode"]
            for key, value in kw.items():
                if key not in DEFAULT_CONFIG:
                    continue
                if value is None and key != "fan_override":
                    continue
                self.cfg[key] = value
            self._normalize()
            self._save()
        self._log(f"设置更新（{reason}）：模式={MODE_LABELS[self.cfg['mode']]}"
                  f"｜风扇={FAN_LABELS[self.cfg['fan_override']]}"
                  f"｜灯光={LIGHT_LABELS[self.cfg['light_level']]}")
        # 页面/语音切到离家时，与「出门判定」一致地关闭全屋设备
        if self.cfg["mode"] == MODE_AWAY and prev_mode != MODE_AWAY:
            self._apply_away()
        return self.config()

    def config(self) -> dict:
        with self._lock:
            cfg = dict(self.cfg)
        now = time.time()
        cfg.update({
            "mode_label": MODE_LABELS[cfg["mode"]],
            "fan_label": FAN_LABELS[cfg["fan_override"]],
            "light_label": LIGHT_LABELS[cfg["light_level"]],
            "pir_near_door": bool(self._pir_since),
            "pir_dwell_seconds": round(now - self._pir_since, 1) if self._pir_since else 0.0,
            "door_close_in": max(0.0, round(self._door_close_at - now, 1))
            if self._door_close_at else 0.0,
            "smoke_active": self._smoke_active,
            "rain_wet": self._rain_wet,
            "last_reason": self._last_reason,
        })
        return cfg

    # ==================== 外部输入（引擎钩子） ====================

    def on_snapshot(self, snap: dict) -> None:
        """A 板周期快照：只更新状态，实际动作交给 tick（1s）。"""
        try:
            self._snapshot = dict(snap or {})
            now = time.time()
            if self._snapshot.get("motion"):
                self._pir_last_seen = now
                if not self._pir_since:
                    self._pir_since = now
                    self._pir_alarm_done = False
            else:
                self._pir_since = 0.0
                self._pir_alarm_done = False
            self._handle_touch(self._snapshot.get("touch"))
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 快照处理异常: %s", e)

    def on_event(self, event: dict) -> None:
        """离散事件：门禁通过 / 红外遥控。"""
        try:
            event = dict(event or {})
            name = event.get("event")
            if name == "face" and event.get("status") == "granted":
                self.on_face_granted(str(event.get("person") or ""))
            elif name == "ir":
                self._handle_ir(event.get("command"))
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 事件处理异常: %s", e)

    def tick(self) -> None:
        """1s 滴答：安全联动（始终）→ 逗留报警 → 自动关门 → 自动调节。"""
        try:
            now = time.time()
            # 需求6/9：烟雾与雨水任何模式下都自动工作
            self._handle_smoke(now)
            self._handle_rain()
            if not self.cfg["enabled"]:
                return
            self._check_dwell(now)
            self._check_door_close(now)
            self._auto_regulate()
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 滴答处理异常: %s", e)

    def note_door_action(self, source: str = "rule") -> None:
        """门舵机动作（积木规则/手动控制）：结合 PIR 判定进门 / 出门（需求3）。"""
        if source == "face":
            return                                    # 门禁流程已单独处理
        now = time.time()
        if self._pir_last_seen and now - self._pir_last_seen <= self.cfg["pir_recent_sec"]:
            self._set_mode(MODE_AUTO, "检测到人后门舵机动作，判定为进门")
        else:
            self._set_mode(MODE_AWAY, "未检测到人时门舵机动作，判定为出门")

    def note_manual_control(self, device: str, reason: str = "", **state) -> None:
        """面板/语音手动操作硬件后的状态机同步（用户策略：手动操作 → 全屋转手动）。

        做两件事：
        1. 把去重缓存 ``_last_*`` 更新为手动值——否则自动调节会误判「已下发过」
           而静默不再下发（实测：自动模式下面板开灯后，自动逻辑 4 秒都没关灯）；
        2. 任何手动操作都把全屋切到「手动」，并清掉该设备此前的红外强制档位，
           使用户刚设的状态不被自动逻辑/旧档位覆盖（触摸键或页面「自动」可恢复）。
        """
        label = {"light": "灯光", "fan": "风扇", "door": "门",
                 "window": "窗户"}.get(device, device)
        dirty = False
        with self._lock:
            if device == "fan":
                self._last_fan = max(0, min(100, int(state.get("speed", 0) or 0)))
                if self.cfg["fan_override"] is not None:
                    self.cfg["fan_override"] = None      # 清掉红外强制档
                    dirty = True
            elif device == "light":
                status = "on" if state.get("status") == "on" else "off"
                brightness = max(0, min(100, int(state.get("brightness", 0) or 0)))
                self._last_light = (status, brightness)
                if self.cfg["light_level"] in ("dark", "half", "bright"):
                    self.cfg["light_level"] = "auto"     # 清掉红外档位
                    dirty = True
            elif device == "window":
                raw = str(state.get("status") or "close")
                self._last_window = "open" if raw == "open" else "close"
            if dirty:
                self._save()
        self._set_mode(MODE_MANUAL,
                       reason or f"手动控制{label}，全屋切到手动模式并保持当前状态")

    def on_face_granted(self, person: str = "") -> None:
        """需求2/3：门禁通过 → 开门 + 10s 后自动关门 + 判定进门。"""
        now = time.time()
        self._door_granted_at = now
        self._pir_alarm_done = True                   # 已通过门禁，取消逗留报警
        who = f"（{person}）" if person else ""
        self._apply_door("open", f"门禁通过{who}，开锁")
        self._door_close_at = now + self.cfg["door_close_sec"]
        self._set_mode(MODE_AUTO, "门禁通过，判定为进门 → 全屋自动调节")

    # ==================== 需求1：逗留报警 ====================

    def _check_dwell(self, now: float) -> None:
        if not self._pir_since or self._pir_alarm_done:
            return
        # PIR 装在房间而非门口，家里有人时走动也会触发；
        # 默认只在「离家」模式报警，语义上等同「无人在家却有人逗留」。
        if self.cfg["dwell_only_away"] and self.cfg["mode"] != MODE_AWAY:
            return
        dwell = self.cfg["door_dwell_sec"]
        if now - self._pir_since < dwell:
            return
        if self._door_granted_at >= self._pir_since:
            self._pir_alarm_done = True               # 期间门禁通过，不算可疑逗留
            return
        self._pir_alarm_done = True
        self._buzzer(3, 300, 200,
                     f"有人靠近门逗留超过 {dwell:g} 秒且未通过门禁，蜂鸣器报警")

    def _check_door_close(self, now: float) -> None:
        if self._door_close_at and now >= self._door_close_at:
            self._door_close_at = 0.0
            self._apply_door("close", "门禁开门后自动关门")

    # ==================== 需求6/9：安全联动（始终生效） ====================

    def _handle_rain(self) -> None:
        wet = bool(self._snapshot.get("rain"))
        if wet and not self._rain_wet:
            self._rain_wet = True
            self._apply_window("close", "检测到雨水，自动关窗")
        elif not wet and self._rain_wet:
            self._rain_wet = False
            self._apply_window("normal", "雨水消失，窗户恢复 45°")

    def _handle_smoke(self, now: float) -> None:
        active = bool(self._snapshot.get("smoke"))
        if active and not self._smoke_active:
            self._smoke_since = now
            self._smoke_active = True
        elif not active and self._smoke_active:
            self._smoke_active = False
            self._smoke_alarms = 0
            self._log("烟雾解除，停止报警")
            return
        if not active:
            return
        # 需连续确认 smoke_confirm_sec 才拉响（滤除预热抖动/单帧误报）
        if now - self._smoke_since < self.cfg["smoke_confirm_sec"]:
            return
        # 未消散时最多重复 realarm_max 次，防止模块异常时蜂鸣器响个不停
        if now - self._smoke_last_alarm >= self.cfg["smoke_realarm_sec"]:
            if self._smoke_alarms >= self.cfg["smoke_realarm_max"]:
                self._log("烟雾持续存在已超过重复报警上限，停止鸣响（仅记录）")
                self._smoke_last_alarm = now
                return
            self._smoke_alarms += 1
            self._smoke_last_alarm = now
            self._buzzer(5, 400, 200,
                         f"检测到烟雾，蜂鸣器拉响报警（第 {self._smoke_alarms} 次）")

    # ==================== 需求8：触摸切换 手动/自动 ====================

    def _handle_touch(self, touch) -> None:
        pressed = bool(touch)
        if pressed and not self._prev_touch:
            if self.cfg["mode"] == MODE_MANUAL:
                self._set_mode(MODE_AUTO, "触摸传感器再按，恢复自动调节")
            else:
                self._set_mode(MODE_MANUAL, "触摸传感器按下，全屋转手动（保持当前状态）")
        self._prev_touch = pressed

    # ==================== 需求4/5：红外按键循环 ====================

    def _handle_ir(self, command) -> None:
        try:
            code = int(command)
        except (TypeError, ValueError):
            return
        if code in IR_FAN_KEYS:
            nxt = _FAN_CYCLE[self.cfg["fan_override"]]
            self.configure(reason=f"红外键 0x{code:02X}：风扇切到「{FAN_LABELS[nxt]}」",
                           fan_override=nxt)
            self._auto_regulate()
        elif code in IR_LIGHT_KEYS:
            cur = self.cfg["light_level"]
            idx = _LIGHT_CYCLE.index(cur) if cur in _LIGHT_CYCLE else 0
            nxt = _LIGHT_CYCLE[(idx + 1) % len(_LIGHT_CYCLE)]
            self.configure(reason=f"红外键 0x{code:02X}：灯光切到「{LIGHT_LABELS[nxt]}」",
                           light_level=nxt)
            self._auto_regulate()

    # ==================== 需求4/5：自动模式下的自动调节 ====================

    def _auto_regulate(self) -> None:
        mode = self.cfg["mode"]
        if mode == MODE_AWAY:
            return                                    # 离家：保持全关，不自动开启

        override = self.cfg["fan_override"]
        if override == "on":
            self._apply_fan(100, "红外强制开风扇")
        elif override == "off":
            self._apply_fan(0, "红外强制关风扇")
        elif mode == MODE_AUTO:
            temp = self._snapshot.get("temperature")
            if temp is not None:
                threshold = self.cfg["temp_threshold"]
                if float(temp) > threshold:
                    self._apply_fan(
                        self.cfg["fan_auto_speed"],
                        f"自动模式：温度 {float(temp):.1f}°C 高于 {threshold:g}°C，风扇全速")
                else:
                    self._apply_fan(
                        0, f"自动模式：温度 {float(temp):.1f}°C 不高于 {threshold:g}°C，关闭风扇")

        level = self.cfg["light_level"]
        if level == "hold":
            return
        if level == "bright":
            self._apply_light("on", self.cfg["bright_pct"], "手动档位：灯光全亮")
        elif level == "half":
            self._apply_light("on", self.cfg["half_pct"], "手动档位：灯光半亮")
        elif level == "dark":
            self._apply_light("on", self.cfg["dark_pct"], "手动档位：灯光调暗")
        elif mode == MODE_AUTO:
            light = self._snapshot.get("light")
            if light is None:
                return
            light = float(light)
            if light <= self.cfg["light_dark_max"]:
                self._apply_light("on", self.cfg["bright_pct"],
                                  f"自动调光：光照 {light:.0f} 偏暗，灯光全亮")
            elif light <= self.cfg["light_mid_max"]:
                self._apply_light("on", self.cfg["half_pct"],
                                  f"自动调光：光照 {light:.0f} 中等，灯光半亮")
            else:
                self._apply_light("off", 0,
                                  f"自动调光：光照 {light:.0f} 充足，关闭灯光")

    # ==================== 模式切换 ====================

    def _set_mode(self, mode: str, reason: str) -> bool:
        with self._lock:
            changed = self.cfg["mode"] != mode
            self.cfg["mode"] = mode
            self._last_reason = reason
            if changed:
                self._save()
        self._log(f"全屋模式 → {MODE_LABELS[mode]}：{reason}")
        if changed and mode == MODE_AWAY:
            self._apply_away()
        return changed

    def _apply_away(self) -> None:
        """需求3：出门 → 全屋关闭（仅保留烟雾/雨水安全联动）。"""
        self._apply_light("off", 0, "离家模式：关闭全屋灯光")
        self._apply_fan(0, "离家模式：关闭风扇")
        self._apply_window("close", "离家模式：关闭窗户")
        self._log("离家模式已生效：灯光/风扇/窗户全部关闭，烟雾与雨水检测继续工作")

    # ==================== 设备动作（经 bridge 下发，带去重） ====================

    def _hardware_ready(self) -> bool:
        bridge = self.bridge
        return bool(bridge) and (getattr(bridge, "online", False)
                                 or getattr(bridge, "relay_url", ""))

    def _apply_fan(self, speed: int, reason: str) -> bool:
        speed = max(0, min(100, int(speed)))
        if self._last_fan == speed:
            return True
        if not self._hardware_ready():
            self._log(f"{reason}（硬件桥离线，未下发）", ok=False)
            return False
        ok, msg = self.bridge.control_fan(speed)
        if ok:
            self._last_fan = speed
            try:
                self.db.update_status(fan_speed=speed)
            except Exception:                        # noqa: BLE001
                logger.debug("[全屋模式] 风扇状态写库失败", exc_info=True)
        self._log(f"{reason} → 风扇 {speed}%", ok=ok, detail=msg)
        return ok

    def _apply_light(self, status: str, brightness: int, reason: str) -> bool:
        brightness = max(0, min(100, int(brightness)))
        key = (status, brightness)
        if self._last_light == key:
            return True
        if not self._hardware_ready():
            self._log(f"{reason}（硬件桥离线，未下发）", ok=False)
            return False
        ok, msg = self.bridge.control_light(status, brightness)
        if ok:
            self._last_light = key
            try:
                self.db.update_status(light_status=status,
                                      light_brightness=brightness)
                self.db.add_light_event("客厅主灯(全屋模式)", status, brightness)
            except Exception:                        # noqa: BLE001
                logger.debug("[全屋模式] 灯光状态写库失败", exc_info=True)
        self._log(f"{reason} → 灯 {status}/{brightness}%", ok=ok, detail=msg)
        return ok

    def _apply_window(self, status: str, reason: str) -> bool:
        """status: open/close/normal(45°)。"""
        if self._last_window == status:
            return True
        if not self._hardware_ready():
            self._log(f"{reason}（硬件桥离线，未下发）", ok=False)
            return False
        ok, msg = self.bridge.control_window(status)
        if ok:
            self._last_window = status
            db_status = {"open": "open", "close": "closed"}.get(status, "normal")
            try:
                self.db.update_status(window_status=db_status)
                self.db.add_door_window_event("window", "客厅窗户(全屋模式)", db_status)
            except Exception:                        # noqa: BLE001
                logger.debug("[全屋模式] 窗状态写库失败", exc_info=True)
        self._log(f"{reason} → 窗 {status}", ok=ok, detail=msg)
        return ok

    def _apply_door(self, status: str, reason: str) -> bool:
        if not self._hardware_ready():
            self._log(f"{reason}（硬件桥离线，未下发）", ok=False)
            return False
        ok, msg = self.bridge.control_door(status)
        if ok:
            db_status = "open" if status == "open" else "closed"
            try:
                self.db.update_status(door_status=db_status)
                self.db.add_door_window_event("door", "前门(全屋模式)", db_status)
            except Exception:                        # noqa: BLE001
                logger.debug("[全屋模式] 门状态写库失败", exc_info=True)
        self._log(f"{reason} → 门 {status}", ok=ok, detail=msg)
        return ok

    def _buzzer(self, count: int, on_ms: int, off_ms: int, reason: str) -> bool:
        if not self._hardware_ready():
            self._log(f"{reason}（硬件桥离线，未下发）", ok=False)
            return False
        try:
            ok, msg = self.bridge.call_tool("buzzer", {
                "action": "beep", "count": int(count),
                "on_ms": int(on_ms), "off_ms": int(off_ms)})
        except Exception as e:                       # noqa: BLE001
            ok, msg = False, str(e)
        self._log(reason, ok=ok, detail=msg)
        return ok

    # ==================== 日志 ====================

    def _log(self, reason: str, ok: bool = True, detail=None) -> None:
        self._last_reason = reason
        try:
            self.db.add_automation_log(
                rule_id="home_mode", rule_name="全屋模式", triggered=1,
                conditions_hold=1, reason=reason, success=1 if ok else 0,
                detail=json.dumps(detail if detail is not None else "", ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 记录写库失败: %s", e)