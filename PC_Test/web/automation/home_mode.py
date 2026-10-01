"""全屋模式状态机（引擎级状态）：自动 / 手动 / 离家 + 设备档位覆盖。

**职责边界**：本模块只负责「状态 + 仲裁」，不再内置任何联动策略（联动全是
积木规则，见 default_rules.py）。核心是解决两处历史 bug：
1. **手动优先 + 冷却窗口**：记录每设备最近一次手动操作的时刻 ``_last_manual``，
   `within_manual_grace()` 返回该设备是否处于手动冷却窗口内；规则动作与
   `tick()` 下发前都先查询它——设备刚被手动设置过则**跳过**，自动绝不和手动抢。
2. **统一锁**：所有可变状态（cfg / _last_* / _last_manual / _pir_last_seen）
   读写都持 ``self._lock``，杜绝自动化线程与 Flask 手动控制线程并发竞争。

保留的状态：
    auto / manual / away 及其语义（离家=全屋关闭 via away_close_all 积木规则）；
    fan_override / light_level 档位覆盖（供「全屋模式」积木设置，tick 持锁、
    且不覆盖手动冷却窗口内的设备）；
    person_present 人在家判定（PIR 保持窗口，静坐漏检时做安全默认）。

设计约束：任何异常只写日志，绝不拖垮 bridge 轮询线程。
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

# 风扇档位循环：强制关 → 强制开 → 自动 → …
FAN_LABELS = {None: "自动", "on": "强制开", "off": "强制关"}
FAN_CYCLE = {"off": "on", "on": None, None: "off"}

# 灯光档位循环：保持 → 暗 → 半亮 → 全亮 → 自动 → …
LIGHT_LABELS = {"auto": "自动", "hold": "保持当前", "dark": "暗",
                "half": "半亮", "bright": "全亮"}
LIGHT_CYCLE = ["hold", "dark", "half", "bright", "auto"]

# OLED 专用英文标签：B 板 u8x8 字库只有 ASCII，汉字上屏是乱码。
MODE_LABELS_EN = {MODE_AUTO: "Auto", MODE_MANUAL: "Manual", MODE_AWAY: "Away"}
FAN_LABELS_EN = {None: "Auto", "on": "ForceON", "off": "ForceOFF"}
LIGHT_LABELS_EN = {"auto": "Auto", "hold": "Hold", "dark": "Dark",
                   "half": "Half", "bright": "Full"}

# 档位对应的亮度百分比（档位是「相对档」，具体百分比固定在这里）
LEVEL_PCT = {"bright": 100, "half": 50, "dark": 30}

# 窗状态在 DB/页面里是 open/closed/normal，下发给 B 板是 open/close/normal
_WINDOW_HW = {"open": "open", "closed": "close", "close": "close", "normal": "normal"}


def _window_hw(status) -> str:
    return _WINDOW_HW.get(str(status or "close"), "close")


DEFAULT_CONFIG = {
    "enabled": True,
    "mode": MODE_AUTO,
    "fan_override": None,          # None=自动；"on"/"off"=强制档位
    "light_level": "auto",         # auto/hold/dark/half/bright
    "presence_hold_sec": 1200.0,   # PIR 触发后「人还在家」的保持窗口（秒，默认20分钟）
    "manual_grace_s": 30.0,        # 手动操作后，自动/规则/tick 让位的冷却窗口（秒）
    # 硬策略（2026-10-01 第四次风扇事故后确立）：自动化**永远只能关风扇，
    # 不能开风扇/调档**——风扇只接受面板/语音等显式人工指令开启。需要恢复
    # 「温度高自动开风扇」类玩法时，由熟悉语义的用户显式改成 True。
    "auto_fan_enable": False,
}

_NUMERIC_KEYS = ("presence_hold_sec", "manual_grace_s")


class HomeModeManager:
    """全屋模式 + 仲裁状态机。线程安全（RLock 保护全部可变状态）。"""

    # 会被「手动冷却窗口」仲裁覆盖的控制器设备
    GRACE_DEVICES = ("light", "fan", "window", "door", "ac")

    def __init__(self, bridge, db, path):
        self.bridge = bridge
        self.db = db
        self.path = Path(path)
        self._lock = threading.RLock()
        self.cfg = dict(DEFAULT_CONFIG)
        self._load()

        # ── 运行期状态（不持久化） ──
        self._snapshot: dict = {}
        self._pir_last_seen = 0.0      # 最近一次检测到「有人」的时刻
        self._last_fan = None          # 最近下发的风扇转速（去重）
        self._fan_memory = 60          # 最近一次非零转速（toggle/开启缺省时恢复）
        self._last_light = None        # 最近下发的 (status, brightness)
        self._last_window = None       # 最近下发的窗状态
        self._last_reason = ""
        self._last_manual: dict[str, float] = {}   # device -> 最近手动操作时刻
        self._fan_block_logged = False   # 自动开风扇被拦截的日志去重（状态变化才记）

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
        self.cfg["auto_fan_enable"] = bool(self.cfg.get("auto_fan_enable", False))
        for key in _NUMERIC_KEYS:
            try:
                self.cfg[key] = float(self.cfg[key])
            except (TypeError, ValueError):
                self.cfg[key] = float(DEFAULT_CONFIG[key])
        # 冷却窗口至少 1 秒、最多 1 小时
        self.cfg["manual_grace_s"] = max(1.0, min(3600.0, self.cfg["manual_grace_s"]))

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
        return self.config()

    def config(self) -> dict:
        with self._lock:
            cfg = dict(self.cfg)
        now = time.time()
        # 当前处于「手动冷却窗口」的设备（前端显示为「手动优先中」）
        graces = [d for d in self.GRACE_DEVICES if self.within_manual_grace(d, now)]
        cfg.update({
            "mode_label": MODE_LABELS[cfg["mode"]],
            "fan_label": FAN_LABELS[cfg["fan_override"]],
            "light_label": LIGHT_LABELS[cfg["light_level"]],
            "person_present": self.person_present(now),
            "last_reason": self._last_reason,
            "manual_grace_s": cfg["manual_grace_s"],
            "manual_graces": graces,
        })
        return cfg

    # ==================== 手动冷却窗口（自动/规则的仲裁闸门） ====================

    def within_manual_grace(self, device: str, now: float | None = None) -> bool:
        """设备是否处于「手动冷却窗口」内。

        - ``True``：该设备刚被手动操作过，自动规则 / tick() 都应让位（跳过）；
        - ``False``：可以下发。
        """
        if device not in self.GRACE_DEVICES:
            return False
        now = time.time() if now is None else now
        with self._lock:
            last = self._last_manual.get(device)
            return last is not None and (now - last) < self.cfg["manual_grace_s"]

    def remember_fan_speed(self, speed: int) -> None:
        """记忆最近一次非零转速；风扇积木「切换/开启」未给转速时恢复该档位。"""
        speed = int(speed or 0)
        if speed > 0:
            with self._lock:
                self._fan_memory = max(1, min(100, speed))

    @property
    def fan_memory(self) -> int:
        with self._lock:
            return self._fan_memory

    def note_manual_control(self, device: str, reason: str = "", **state) -> None:
        """面板/语音手动操作硬件后的状态机同步（用户策略：手动操作 → 全屋转手动）。

        做三件事（全程持锁）：
        1. 记录 ``_last_manual[device]`` 时刻 → 进入手动冷却窗口，自动让位；
        2. 更新去重缓存 ``_last_*``，清掉该设备的档位覆盖；
        3. 把全屋切到「手动」，使用户刚设的状态不被自动逻辑再次覆盖
           （页面切「自动」/触摸键可恢复）。
        """
        label = {"light": "灯光", "fan": "风扇", "door": "门",
                 "window": "窗户", "ac": "空调"}.get(device, device)
        dirty = False
        with self._lock:
            self._last_manual[device] = time.time()
            if device == "fan":
                fan_speed = max(0, min(100, int(state.get("speed", 0) or 0)))
                self._last_fan = fan_speed
                self._fan_block_logged = False   # 人工操作后恢复拦截日志的一次性记录
                if fan_speed > 0:
                    self._fan_memory = fan_speed
                if self.cfg["fan_override"] is not None:
                    self.cfg["fan_override"] = None      # 清掉强制档
                    dirty = True
            elif device == "light":
                status = "on" if state.get("status") == "on" else "off"
                brightness = max(0, min(100, int(state.get("brightness", 0) or 0)))
                self._last_light = (status, brightness)
                if self.cfg["light_level"] in LEVEL_PCT:
                    self.cfg["light_level"] = "auto"     # 清掉档位
                    dirty = True
            elif device == "window":
                self._last_window = _window_hw(state.get("status"))
            if dirty:
                self._save()
        self._set_mode(MODE_MANUAL,
                       reason or f"手动控制{label}，全屋切到手动模式并保持当前状态")

    def note_rule_action(self, device: str, **state) -> None:
        """积木规则下发了设备动作后：同步去重缓存，让档位覆盖让位。

        规则给的是**具体指令**（如风扇 40%），比「强制开/强制关」更具体，所以
        清掉该设备的覆盖档，避免下一秒 tick 再按覆盖值重下发（「刚设的值被改回去」）。

        与 ``note_manual_control`` 的区别：**不记录手动冷却、不切手动**——规则
        本来就是自动编排的，不该因自己执行一次动作就把全屋踢出自动。
        """
        dirty = False
        with self._lock:
            if device == "fan":
                fan_speed = max(0, min(100, int(state.get("speed", 0) or 0)))
                self._last_fan = fan_speed
                if fan_speed > 0:
                    self._fan_memory = fan_speed
                if self.cfg["fan_override"] is not None:
                    self.cfg["fan_override"] = None
                    dirty = True
            elif device == "light":
                status = "on" if state.get("status") == "on" else "off"
                brightness = max(0, min(100, int(state.get("brightness", 0) or 0)))
                self._last_light = (status, brightness)
                if self.cfg["light_level"] in LEVEL_PCT:
                    self.cfg["light_level"] = "auto"
                    dirty = True
            elif device == "window":
                self._last_window = _window_hw(state.get("status"))
            if dirty:
                self._save()

    # ==================== 档位循环/翻转（供积木的 cycle/toggle 动作） ====================

    def next_fan_override(self):
        with self._lock:
            return FAN_CYCLE[self.cfg["fan_override"]]

    def next_light_level(self) -> str:
        with self._lock:
            cur = self.cfg["light_level"]
            idx = LIGHT_CYCLE.index(cur) if cur in LIGHT_CYCLE else 0
        return LIGHT_CYCLE[(idx + 1) % len(LIGHT_CYCLE)]

    def toggled_mode(self) -> str:
        """触摸键那种「手动↔自动」翻转：非手动 → 手动，手动 → 自动。"""
        with self._lock:
            cur = self.cfg["mode"]
        return MODE_AUTO if cur == MODE_MANUAL else MODE_MANUAL

    # ==================== 人在家判定 ====================

    def person_present(self, now: float | None = None) -> bool:
        """是否判定「有人在家」（积木条件源 person_present）。

        PIR 只能测到「有动作」，静坐会漏检。处理策略：
        - 从未收到过 PIR 数据 → 按**安全默认「有人」**（除非显式离家），
          避免启动/无人数据时自动调控误判；
        - PIR 最近有动作、或在 ``presence_hold_sec`` 保持窗口内 → 有人；
        - PIR 超过窗口没动 → 判「无人」——此时温度/光照等「无人自动调控」才可能生效。
        真正常住离家请切「离家」模式（关闭全屋 + 安全规则）。
        """
        now = time.time() if now is None else now
        seen = self._pir_last_seen
        if not seen:
            return self.cfg["mode"] != MODE_AWAY
        return (now - seen) <= self.cfg["presence_hold_sec"]

    # ==================== 外部输入（引擎钩子） ====================

    def on_snapshot(self, snap: dict) -> None:
        """A 板周期快照：只更新「人在家」判定，不做任何设备动作。"""
        try:
            with self._lock:
                self._snapshot = dict(snap or {})
                if self._snapshot.get("motion"):
                    self._pir_last_seen = time.time()
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 快照处理异常: %s", e)

    def tick(self) -> None:
        """1s 滴答：持锁重新下发被积木设置的档位覆盖。

        关键：每个需要下发的设备先查 ``within_manual_grace``——若该设备刚被
        手动操作过（冷却窗口内）则**跳过**，绝不把用户的设置改回去。

        另一条硬边界：**手动模式下整个 tick 不下发任何覆盖档**。手动模式的
        语义是「用户全权」——历史遗留行为是在手动模式下若 fan_override=on，
        冷却窗口（30s）一过 tick 就把风扇强开到 100%，用户早已忘了页面上留着
        覆盖档，表现为「风扇自己转起来」。覆盖档的持续保证只在自动/离家模式
        生效；手动模式下用户在页面切换覆盖档时由 API 立即执行一次
        （见 `apply_overrides_now()`），不持续抢占。
        """
        try:
            with self._lock:
                if not self.cfg["enabled"]:
                    return
                if self.cfg["mode"] == MODE_MANUAL:
                    return
                now = time.time()
                override = self.cfg["fan_override"]
                if override in ("on", "off") and not self.within_manual_grace("fan", now):
                    self.auto_apply_fan(
                        100 if override == "on" else 0,
                        "档位覆盖：强制" + ("开" if override == "on" else "关") + "风扇")
                level = self.cfg["light_level"]
                if level in LEVEL_PCT and not self.within_manual_grace("light", now):
                    self._apply_light("on", LEVEL_PCT[level],
                                      f"档位覆盖：灯光{LIGHT_LABELS[level]}")
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全屋模式] 滴答处理异常: %s", e)

    def apply_overrides_now(self, reason: str = "页面切换覆盖档",
                            auto: bool = False) -> None:
        """覆盖档写入配置后立即执行一次。

        - ``auto=False``（页面 PUT，显式人工）：按档执行；
        - ``auto=True``（积木规则触发）：风扇走 `auto_apply_fan` 硬门控，
          默认策略下「强制开」不会真的开风扇。
        tick() 在手动模式下整体禁用；自动/离家模式 tick 续保。
        """
        with self._lock:
            if not self.cfg["enabled"]:
                return
            override = self.cfg["fan_override"]
            level = self.cfg["light_level"]
        if override in ("on", "off"):
            speed = 100 if override == "on" else 0
            label = f"{reason}：强制{'开' if override == 'on' else '关'}风扇"
            if auto:
                self.auto_apply_fan(speed, label)
            else:
                self._apply_fan(speed, label)
        if level in LEVEL_PCT:
            self._apply_light("on", LEVEL_PCT[level],
                              f"{reason}：灯光{LIGHT_LABELS[level]}")

    # ==================== 模式切换 ====================

    def _set_mode(self, mode: str, reason: str) -> bool:
        with self._lock:
            changed = self.cfg["mode"] != mode
            self.cfg["mode"] = mode
            self._last_reason = reason
            if changed:
                self._save()
        self._log(f"全屋模式 → {MODE_LABELS[mode]}：{reason}")
        return changed

    # ==================== 设备动作（经 bridge 下发，带去重） ====================

    def _hardware_ready(self) -> bool:
        bridge = self.bridge
        return bool(bridge) and (getattr(bridge, "online", False)
                                 or getattr(bridge, "relay_url", ""))

    def auto_apply_fan(self, speed: int, reason: str) -> tuple[bool, str, bool]:
        """**所有自动化路径**（积木规则/tick/规则设覆盖档）开/关风扇的唯一入口。

        硬策略：``auto_fan_enable=False``（默认）时，自动化只允许把风扇设为 0
        （关），任何正转速一律拦截且**不写库、不动去重缓存**——风扇只能由面板/
        语音等显式人工指令开启。返回 ``(ok, msg, applied)``：applied=False 表示
        被策略跳过（调用方不得再按目标值写库）。
        """
        speed = max(0, min(100, int(speed)))
        with self._lock:
            allowed = speed == 0 or bool(self.cfg["auto_fan_enable"])
        if not allowed:
            if not self._fan_block_logged:
                self._log(f"{reason}：自动开启风扇被硬策略拦截（风扇只能手动开），已跳过")
                self._fan_block_logged = True
            return True, "自动开启风扇已被禁用（只能手动开启）", False
        self._fan_block_logged = False
        ok = self._apply_fan(speed, reason)
        return ok, ("ok" if ok else "failed"), ok

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
            if speed > 0:
                self._fan_memory = speed
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