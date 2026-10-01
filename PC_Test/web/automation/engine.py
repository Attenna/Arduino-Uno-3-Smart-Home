"""自动化规则引擎（运行在 web 容器内）。

数据流::

    hardware bridge 每 2s 拉到 A 板快照 ──▶ engine.on_snapshot()  ─┐
    A 板事件(motion/keypad/ir)、人脸授权 ─▶ engine.on_event()     ├─▶ 规则求值
    内置 1s 滴答定时器（周期/定时触发） ──▶ engine._tick()       ─┘
                                                                   │
                                          满足触发且条件成立 ──────┤
                                                                   ▼
                                    动作执行线程（支持延时、防重入）
                                                                   │
                                                    bridge ─relay─▶ voice ─▶ Module B

设计要点：
- 传感器触发为**边沿触发**：条件由假变真的瞬间触发一次（跨阈值防刷屏）；
  触发块可加 ``hold_sec``（「持续 N 秒」），条件连续保持满 N 秒才触发；
- 条件由真变假时，**只有规则写了「否则」动作**才走 else_actions
  （雨停恢复 45° 这类状态回切；没写否则的规则自然回落不动作）；
- 每条规则有 cooldown 冷却与独立的动作锁（动作序列执行中不重入）；
- 内置联动已全部下沉为默认规则积木（见 default_rules.py），代码里不再写死策略；
- 引擎任何异常只写日志，绝不能拖垮 bridge 轮询线程。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from .capabilities import CONDITION_SOURCES, EVENT_TRIGGERS
from .default_rules import DEFAULT_RULES, PRESETS_VERSION
from .home_mode import (FAN_LABELS, FAN_LABELS_EN, LIGHT_LABELS,
                        LIGHT_LABELS_EN, MODE_LABELS, MODE_LABELS_EN,
                        HomeModeManager)
from .oled_carousel import (DEFAULT_PAGES, PAGES_VERSION, OledCarousel,
                            is_legacy_default_pages)
from .schema import validate_rules
import midea_ac
from ..ac_state import AC_KEYS, ac_state_from_db, write_ac_state
# RFID 卡号归一化：规则里存的与事件里带的两侧都归一后再比
from ..database import normalize_uid

logger = logging.getLogger(__name__)


class AutomationEngine:
    def __init__(self, bridge, db, rules_path: Path):
        self.bridge = bridge
        self.db = db
        self.rules_path = Path(rules_path)
        self.rules: list[dict] = []

        self._lock = threading.RLock()          # 保护规则热更新
        self._snapshot: dict = {}               # A 板最新一帧（原始字段名）
        self._snapshot_ts: float = 0.0
        # 事件队列（带序号），规则按各自 last_event_id 消费
        self._events: list[tuple[int, dict]] = []
        self._event_seq = 0
        # 每条规则的运行期状态
        self._prev_trigger: dict[str, bool] = {}     # 上次触发条件真假（边沿）
        self._hold_since: dict[str, float] = {}      # 「持续 N 秒」起算时刻
        self._hold_fired: dict[str, bool] = {}       # 本轮持续是否已触发过
        self._last_fire: dict[str, float] = {}       # 上次开火时间（冷却）
        self._last_event_id: dict[str, int] = {}
        self._last_interval: dict[str, float] = {}
        self._last_time_key: dict[str, str] = {}
        self._action_locks: dict[str, threading.Lock] = {}
        # 红外自发射回声抑制：(address, command) -> 抑制截止时刻。
        # B 板发的 NEC 码会被 A 板接收头当成「有人按了遥控器」，上报的 ir 事件
        # 没有任何来源标记，若不抑制，「发码 X → 收到 X → 再发 X」会永不停止。
        self._ir_echo_until: dict[tuple[int, int], float] = {}
        # 事件身份去重（纵深防御）：硬件桥已按 ts 去重，这里再挡一层任何来源
        # （测试 API/人脸回调/上层重放）的同一事件。只对带 ts/timestamp 的事件生效。
        self._seen_event_keys: set[str] = set()
        self._seen_event_order: deque[str] = deque()
        self._stopping = False
        self._tick_thread: threading.Thread | None = None
        # 已注入过的内置默认规则（preset id）；用户删掉的不会再被强行加回来
        self._presets_seen: set[str] = set()

        # ── OLED 轮播（默认关闭，避免扰民） ──
        self.oled_path = Path(rules_path).parent / "oled_carousel.json"
        self.oled_enabled = False
        self.oled_interval = 5.0
        self.oled_pages: list[dict] | None = None
        self._oled_carousel = OledCarousel(emitter=self._oled_emit,
                                           on_log=self._oled_log)
        self._oled_thread: threading.Thread | None = None

        # ── 全屋模式状态机（自动/手动/离家 + 红外强制覆盖） ──
        # 承载十条全屋联动需求里跨设备、带时序的部分（见 home_mode.py）
        self.home_mode = HomeModeManager(
            bridge, db, Path(rules_path).parent / "home_mode.json")

    # ==================== 生命周期 ====================

    def start(self) -> None:
        self.load()
        self._tick_thread = threading.Thread(
            target=self._tick_loop, name="automation-tick", daemon=True)
        self._tick_thread.start()
        self._oled_thread = threading.Thread(
            target=self._oled_loop, name="automation-oled", daemon=True)
        self._oled_thread.start()
        logger.info("[自动化] 引擎已启动，规则 %d 条", len(self.rules))

    def stop(self) -> None:
        self._stopping = True

    # ==================== 规则持久化 ====================

    def load(self) -> None:
        raw = None
        if self.rules_path.exists():
            try:
                raw = json.loads(self.rules_path.read_text(encoding="utf-8"))
            except Exception as e:                       # noqa: BLE001
                logger.error("[自动化] 规则文件读取失败，保留空规则: %s", e)
                raw = []
        data = raw if isinstance(raw, dict) else {"rules": raw}
        self._presets_seen = {str(x) for x in (data.get("presets_seen") or [])}
        try:
            self.rules = validate_rules(data.get("rules") or [])
        except Exception as e:                           # noqa: BLE001
            logger.error("[自动化] 规则校验失败，保留空规则: %s", e)
            self.rules = []
        if self.seed_presets():
            self._write_rules()

    def seed_presets(self, force: bool = False) -> int:
        """把内置默认规则补进规则集，返回新增条数。

        - 老版本升级（规则集里没有 preset 标记）→ 一次性补齐全部默认规则；
        - 用户主动删掉的不会被强行加回来；force=True（页面「恢复内置规则」）才补回。
        """
        added = 0
        with self._lock:
            have = {r.get("preset") for r in self.rules if r.get("preset")}
            for preset in DEFAULT_RULES:
                pid = preset.get("preset")
                if pid in have:
                    continue
                if not force and pid in self._presets_seen:
                    continue
                rule = dict(preset)
                rule["id"] = None
                self.rules.append(rule)
                self._presets_seen.add(pid)
                added += 1
            if added:
                self.rules = validate_rules(self.rules)
                for rule in self.rules:
                    if not rule["id"]:
                        rule["id"] = uuid.uuid4().hex[:8]
        if added:
            logger.info("[自动化] 已注入内置默认规则 %d 条", added)
        return added

    def restore_presets(self) -> list[dict]:
        """页面「恢复内置规则」：把用户删掉/改名的默认规则按原样补回并落盘。"""
        with self._lock:
            self.seed_presets(force=True)
            self._write_rules()
            return list(self.rules)

    def _write_rules(self) -> None:
        self.rules_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.rules_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "presets_version": PRESETS_VERSION,
            "presets_seen": sorted(self._presets_seen),
            "rules": self.rules,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.rules_path)

    def save_rules(self, rules: list[dict]) -> list[dict]:
        """校验并落盘新规则集（整表替换），返回补全 id 后的规则。"""
        clean = validate_rules(rules)
        with self._lock:
            old_ids = {r["id"] for r in self.rules}
            for rule in clean:
                if not rule["id"]:
                    rule["id"] = uuid.uuid4().hex[:8]
            self.rules = clean
            # 页面保存的规则里带 preset 标记的，同样计入「已注入过」
            self._presets_seen |= {r["preset"] for r in clean if r.get("preset")}
            self._write_rules()
            # 清理已删除规则的运行期状态
            new_ids = {r["id"] for r in clean}
            for store in (self._prev_trigger, self._hold_since, self._hold_fired,
                          self._last_fire, self._last_event_id,
                          self._last_interval, self._last_time_key):
                for dead in old_ids - new_ids:
                    store.pop(dead, None)
        logger.info("[自动化] 规则已保存，共 %d 条", len(clean))
        return clean

    # ==================== 外部输入（bridge / face API 调用） ====================

    def on_snapshot(self, snap: dict) -> None:
        """A 板周期数据（字段名：temperature/humidity/light/smoke/rain/touch/motion）。"""
        try:
            self._snapshot = dict(snap or {})
            self._snapshot_ts = time.time()
            self.home_mode.on_snapshot(self._snapshot)
            for rule in list(self._iter_enabled()):
                if rule["trigger"]["kind"] == "sensor":
                    self._evaluate_sensor_rule(rule)
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] 快照求值异常: %s", e)

    def on_event(self, event: dict) -> None:
        """离散事件：A 板 motion/keypad/ir 或人脸授权。线程安全。"""
        try:
            # 红外回声抑制必须在入队/求值之前：否则「发码→收到码→再发码」会自激
            if event.get("event") == "ir" and self._is_ir_echo(event):
                return
            # 按事件时间戳去重：同一物理事件（同一 ts）被任何链路重放时直接丢弃
            ev_ts = event.get("ts") or event.get("timestamp")
            if ev_ts:
                ev_key = f"{event.get('event', 'unknown')}@{ev_ts}"
                if ev_key in self._seen_event_keys:
                    return
                self._seen_event_keys.add(ev_key)
                self._seen_event_order.append(ev_key)
                while len(self._seen_event_order) > 256:
                    self._seen_event_keys.discard(self._seen_event_order.popleft())
            self._event_seq += 1
            seq = self._event_seq
            self._events.append((seq, dict(event or {})))
            if len(self._events) > 100:
                self._events = self._events[-100:]
            for rule in list(self._iter_enabled()):
                if rule["trigger"]["kind"] == "event":
                    self._evaluate_event_rule(rule, seq, event)
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] 事件求值异常: %s", e)

    # ==================== 红外自发射回声抑制 ====================

    @staticmethod
    def _ir_key(action: dict) -> tuple[int, int] | None:
        """从红外动作里解出 (address, command)，用于回声比对。

        A 板上报的 ir 事件只带 protocol/address/command（没有 32 位整码），
        所以抑制窗口必须按 (address, command) 记；只给 code 时按 NEC 帧序反解。
        """
        addr, cmd = action.get("address"), action.get("command")
        if addr is None or cmd is None:
            code = action.get("code")
            if code is None:
                return None
            code = int(code) & 0xFFFFFFFF
            addr = (code >> 24) & 0xFF
            cmd = (code >> 8) & 0xFF
        return int(addr) & 0xFF, int(cmd) & 0xFF

    def _is_ir_echo(self, event: dict) -> bool:
        """刚由本引擎发射出去的红外码又被打回，直接丢弃并记一条日志。"""
        try:
            key = (int(event.get("address", -1)) & 0xFF,
                   int(event.get("command", -1)) & 0xFF)
        except (TypeError, ValueError):
            return False
        now = time.time()
        with self._lock:
            until = self._ir_echo_until.get(key)
            if not until:
                return False
            if until <= now:
                self._ir_echo_until.pop(key, None)   # 顺手清理，避免无限增长
                return False
        logger.info("[自动化] 忽略自发射红外回声 addr=0x%02X cmd=0x%02X", key[0], key[1])
        return True

    # ==================== 周期/定时触发 ====================

    def _tick_loop(self) -> None:
        while not self._stopping:
            time.sleep(1.0)
            try:
                now = time.time()
                minute = datetime.now().strftime("%H:%M")
                self.home_mode.tick()
                for rule in list(self._iter_enabled()):
                    trig = rule["trigger"]
                    if trig["kind"] == "interval":
                        last = self._last_interval.get(rule["id"], 0.0)
                        if last == 0.0:
                            self._last_interval[rule["id"]] = now
                        elif now - last >= float(trig["seconds"]):
                            self._last_interval[rule["id"]] = now
                            self._fire(rule, reason=f"每 {trig['seconds']:g} 秒")
                    elif trig["kind"] == "time":
                        key = datetime.now().strftime("%Y-%m-%d ") + trig["hhmm"]
                        if minute == trig["hhmm"] and self._last_time_key.get(rule["id"]) != key:
                            self._last_time_key[rule["id"]] = key
                            self._fire(rule, reason=f"定时 {trig['hhmm']}")
            except Exception as e:                   # noqa: BLE001
                logger.debug("[自动化] 滴答求值异常: %s", e)

    # ==================== OLED 轮播（默认关闭） ====================

    def set_oled(self, pages=None, interval=None, enabled=None) -> dict:
        """配置 OLED 轮播。任一参数为 None 表示保持当前值。

        pages:   页面列表（{"title","lines"}），list 且非空才生效
        interval: 每页停留秒数（>=1）
        enabled:  是否启用轮播
        """
        if interval is not None:
            if isinstance(interval, bool) or not isinstance(interval, (int, float)):
                raise ValueError("间隔必须是数字（秒）")
            self.oled_interval = max(1.0, float(interval))
            self._oled_carousel.interval = self.oled_interval
        if pages is not None:
            if not isinstance(pages, list) or not pages:
                raise ValueError("页面需为非空列表")
            self.oled_pages = pages
            self._oled_carousel.pages = pages
            self._oled_carousel._page_idx = 0
            self._oled_carousel._next_switch = time.time()
        if enabled is not None:
            self.oled_enabled = bool(enabled)
        self._save_oled_config()
        return self.oled_config()

    def _save_oled_config(self) -> None:
        try:
            self.oled_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.oled_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({
                "enabled": self.oled_enabled,
                "interval": self.oled_interval,
                "pages_version": PAGES_VERSION,
                "pages": self.oled_pages or DEFAULT_PAGES,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.oled_path)
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] OLED 配置保存失败: %s", e)

    def oled_config(self) -> dict:
        """返回当前 OLED 轮播配置（含持久化文件里的历史配置）。"""
        # 本进程从未显式配置且未持久化过：尝试把磁盘配置并入内存
        if not (self.oled_enabled or self.oled_pages
                or self.oled_interval != 5.0):
            try:
                if self.oled_path.exists():
                    cfg = json.loads(self.oled_path.read_text(encoding="utf-8"))
                    self.oled_enabled = bool(cfg.get("enabled", False))
                    self.oled_interval = float(cfg.get("interval", 5.0))
                    # 默认页随代码升级：磁盘里是旧版默认页时自动换新文案，
                    # 并默认开启轮播（需求7：OLED 实时显示全屋状态，可在页面关掉）
                    pages = cfg.get("pages")
                    if int(cfg.get("pages_version", 0) or 0) < PAGES_VERSION \
                            and is_legacy_default_pages(pages):
                        pages = None
                        self.oled_enabled = True
                    self.oled_pages = pages if isinstance(pages, list) and pages else None
                    self._oled_carousel.pages = self.oled_pages or DEFAULT_PAGES
                    self._oled_carousel.interval = self.oled_interval
            except Exception as e:                   # noqa: BLE001
                logger.debug("[自动化] OLED 配置读取失败: %s", e)
        return {"enabled": self.oled_enabled, "interval": self.oled_interval,
                "pages": self.oled_pages or DEFAULT_PAGES}

    def _oled_loop(self) -> None:
        """独立轮播线程：仅当启用时填充数据源并 tick。"""
        while not self._stopping:
            time.sleep(0.5)
            try:
                if not self.oled_enabled:
                    continue
                self._oled_carousel.set_data(self._oled_data())
                self._oled_carousel.tick()
            except Exception as e:                   # noqa: BLE001
                logger.debug("[自动化] OLED 轮播异常: %s", e)

    def _oled_data(self) -> dict:
        """A 板快照 + B 板执行器状态 + 最近自动化，组成扁平数据源。"""
        data = dict(self._snapshot)
        try:
            hm = self.home_mode.config()
            # OLED 用英文标签（B 板字库无汉字），页面/接口仍返回中文标签
            data["home_mode"] = MODE_LABELS_EN.get(hm["mode"], "Auto")
            data["home_fan"] = FAN_LABELS_EN.get(hm["fan_override"], "Auto")
            data["home_light"] = LIGHT_LABELS_EN.get(hm["light_level"], "Auto")
            # 需求11：人在家时自动调节暂停，屏上给出可见原因
            data["presence"] = "YES" if hm.get("person_present") else "NO"
        except Exception:                            # noqa: BLE001
            pass
        try:
            status = self.db.get_current_status()
            data["b_door"] = status.get("door_status")
            data["b_window"] = status.get("window_status")
            data["b_fan"] = status.get("fan_speed")
            data["light_lv"] = status.get("light_brightness")
            data["b_buzzer"] = status.get("buzzer_status")
        except Exception:                            # noqa: BLE001
            pass
        try:
            logs = self.db.get_automation_logs(1)
            if logs:
                row = logs[0]
                # OLED 只能显示 ASCII：状态标记用 OK/NG，规则名由用户自取
                # （中文规则名会被 to_oled_text 丢弃，不会花屏）
                mark = "OK" if row.get("success") else "NG"
                data["recent_auto"] = f"{mark} {row.get('rule_name', '')}"
        except Exception:                            # noqa: BLE001
            pass
        return data

    def _oled_emit(self, line: int, text: str) -> None:
        """轮播逐行下发；桥离线（且无 relay）时静默跳过。"""
        if not self.bridge or (not self.bridge.online and not self.bridge.relay_url):
            return
        try:
            self.bridge.call_tool("oled", {"action": "show_text",
                                           "line": int(line), "text": text})
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] OLED 逐行下发失败: %s", e)

    def _oled_log(self, message: str) -> None:
        """轮播切页记入自动化日志（作为 reason 记录）。"""
        try:
            self.db.add_automation_log(
                rule_id="oled_carousel", rule_name="OLED轮播显示",
                triggered=0, conditions_hold=0, reason=message, success=1, detail="")
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] OLED 轮播记录写库失败: %s", e)

    # ==================== 规则求值 ====================

    def _iter_enabled(self):
        with self._lock:
            for rule in self.rules:
                if rule.get("enabled", True):
                    yield rule

    def _context(self) -> dict:
        """传感器快照 + SQLite 中的执行器当前状态 + 全屋模式/人在家判定。"""
        ctx = dict(self._snapshot)
        try:
            cfg = self.home_mode.cfg
            ctx["home_mode"] = cfg["mode"]
            ctx["home_enabled"] = bool(cfg.get("enabled", True))
            # 配置里风扇档位用 None 表示「自动」，规则侧统一用 "auto"，否则
            # 「全屋风扇档位 = 自动」永远不成立（None 参与比较恒为假）
            fan_override = cfg.get("fan_override")
            ctx["home_fan"] = "auto" if fan_override is None else fan_override
            ctx["home_light"] = cfg.get("light_level", "auto")
            ctx["person_present"] = self.home_mode.person_present()
        except Exception:                            # noqa: BLE001
            pass
        try:
            status = self.db.get_current_status()
            for key in ("door_status", "window_status", "light_status",
                        "light_brightness", "fan_speed",
                        "sensor_online", "output_online"):
                if status.get(key) is not None:
                    ctx[key] = status[key]
        except Exception:                           # noqa: BLE001
            pass
        return ctx

    @staticmethod
    def _compare(left, op: str, right) -> bool:
        if left is None:
            return False
        # 布尔传感器：字符串 true/false 归一
        if isinstance(left, bool) and isinstance(right, str) and right in ("true", "false"):
            right = right == "true"
        if isinstance(right, bool) or isinstance(left, bool):
            left_b = bool(left)
            right_b = bool(right)
            return left_b == right_b if op in ("==", "!=") else False
        # 字符串枚举（门/窗/灯状态）
        if isinstance(left, str) or isinstance(right, str):
            if op in ("==", "!="):
                equal = str(left) == str(right)
                return equal if op == "==" else not equal
            return False
        try:
            l, r = float(left), float(right)
        except (TypeError, ValueError):
            return False
        return {">": l > r, ">=": l >= r, "<": l < r,
                "<=": l <= r, "==": l == r, "!=": l != r}[op]

    def _eval_condition(self, cond: dict, ctx: dict) -> bool:
        return self._compare(ctx.get(cond["sensor"]), cond["op"], cond["value"])

    def _conditions_hold(self, rule: dict, ctx: dict) -> bool:
        conds = rule["conditions"]
        if not conds:
            return True
        results = (self._eval_condition(c, ctx) for c in conds)
        return all(results) if rule["match"] == "all" else any(results)

    def _evaluate_sensor_rule(self, rule: dict) -> None:
        with self._lock:
            trig = rule["trigger"]
            ctx = self._context()
            now_true = self._compare(ctx.get(trig["sensor"]), trig["op"], trig["value"])
            was_true = self._prev_trigger.get(rule["id"], False)
            self._prev_trigger[rule["id"]] = now_true
            label = CONDITION_SOURCES.get(trig["sensor"], {}).get("label", trig["sensor"])
            reason = f"{label} {trig['op']} {trig['value']}"

            if not now_true:
                self._hold_since.pop(rule["id"], None)
                self._hold_fired.pop(rule["id"], None)
                # 下降沿：只有写了「否则」动作的规则才回切（雨停恢复 45° 这类）
                if was_true and rule.get("else_actions"):
                    self._fire(rule, reason=f"{reason} 已恢复", force_hold=False)
                return

            hold_sec = float(trig.get("hold_sec") or 0)
            if hold_sec <= 0:
                if not was_true:
                    self._fire(rule, reason=reason)
                return
            # 「持续 N 秒」：连续保持满 N 秒触发一次，中断（条件转假）则重新计时
            start = self._hold_since.get(rule["id"])
            if start is None:
                self._hold_since[rule["id"]] = time.time()
                return
            if time.time() - start >= hold_sec and not self._hold_fired.get(rule["id"]):
                self._hold_fired[rule["id"]] = True
                self._fire(rule, reason=f"{reason} 持续 {hold_sec:g} 秒")

    def _evaluate_event_rule(self, rule: dict, seq: int, event: dict) -> None:
        with self._lock:
            # 只消费本规则没见过的事件；当前事件即新事件
            if seq <= self._last_event_id.get(rule["id"], 0):
                return
            self._last_event_id[rule["id"]] = seq
            trig = rule["trigger"]
            want = EVENT_TRIGGERS[trig["event"]].get("payload", {})
            if not all(event.get(k) == v for k, v in want.items()):
                return
            if trig.get("key") and str(event.get("key", "")) != trig["key"]:
                return
            if trig.get("command"):
                try:
                    want_cmd = int(str(trig["command"]), 16) if str(trig["command"]).startswith("0x") \
                        else int(trig["command"])
                    if int(event.get("command", -1)) != want_cmd:
                        return
                except (TypeError, ValueError):
                    return
            # RFID 卡号过滤：两侧都归一化成 "AA BB CC DD" 再比
            if trig.get("uid"):
                try:
                    if normalize_uid(event.get("uid")) != trig["uid"]:
                        return
                except ValueError:
                    return
            label = EVENT_TRIGGERS[trig["event"]]["label"]
            self._fire(rule, reason=label)

    def _fire(self, rule: dict, reason: str, force_hold: bool | None = None) -> None:
        with self._lock:
            now = time.time()
            if now - self._last_fire.get(rule["id"], 0.0) < float(rule.get("cooldown", 3)):
                return
            ctx = self._context()
            hold = self._conditions_hold(rule, ctx) if force_hold is None else force_hold
            branch = rule["actions"] if hold else rule.get("else_actions", [])
            if not branch:
                # 条件不成立且没写「否则」动作：这条规则这次什么都不做（不记冷却、不记日志）
                return
            self._last_fire[rule["id"]] = now
            lock = self._action_locks.setdefault(rule["id"], threading.Lock())
            if not lock.acquire(blocking=False):
                logger.info("[自动化] 规则「%s」上一轮动作未完成，跳过", rule["name"])
                return
            threading.Thread(
                target=self._run_actions, args=(rule, branch, hold, reason, lock),
                name=f"auto-{rule['id']}", daemon=True).start()

    # ==================== 动作执行 ====================

    def _run_actions(self, rule, actions, hold, reason, lock: threading.Lock) -> None:
        detail: list[dict] = []
        ok_all = True
        try:
            for action in actions:
                ok, msg = self._perform(action)
                detail.append({"action": action, "ok": ok, "result": msg})
                if not ok:
                    ok_all = False
                    logger.warning("[自动化] 规则「%s」动作失败 %s: %s",
                                   rule["name"], action.get("device"), msg)
                    break
            self._log(rule, fired=True, conditions_hold=hold, reason=reason,
                      ok=ok_all, detail=detail)
        finally:
            lock.release()

    def _perform(self, action: dict) -> tuple[bool, str]:
        device = action["device"]
        # 手动优先：控制器设备刚被手动设置过（冷却窗口内）→ 自动动作让位跳过，
        # 绝不把用户刚设的状态改回去（「网页控制失败/风扇自启」的根治点）。
        if device in ("door", "window", "light", "fan", "ac"):
            if self.home_mode.within_manual_grace(device):
                label = {"door": "门", "window": "窗", "light": "灯",
                         "fan": "风扇", "ac": "空调"}.get(device, device)
                return True, f"{label}处于手动冷却窗口，自动动作让位（跳过）"
        if device == "delay":
            time.sleep(float(action["seconds"]))
            return True, f"等待 {action['seconds']:g}s"
        if device == "home_mode":
            # 纯状态机，不碰硬件：即使桥离线也照常生效
            kw = {}
            mode = action.get("mode")
            if mode == "toggle":
                mode = self.home_mode.toggled_mode()      # 手动↔自动 翻转
            if mode:
                kw["mode"] = mode
            fan = action.get("fan_override")
            if fan == "cycle":
                # 循环下一档；None 表示回到自动，必须显式下发
                kw["fan_override"] = self.home_mode.next_fan_override()
            elif fan:
                kw["fan_override"] = None if fan == "auto" else fan
            light = action.get("light_level")
            if light == "cycle":
                light = self.home_mode.next_light_level()
            if light:
                kw["light_level"] = light
            # 状态机自身参数（原先只能在代码里改）
            if "enabled" in action and action.get("enabled") is not None:
                kw["enabled"] = bool(action["enabled"])
            if action.get("presence_hold_sec") is not None:
                kw["presence_hold_sec"] = float(action["presence_hold_sec"])
            if action.get("manual_grace_s") is not None:
                kw["manual_grace_s"] = float(action["manual_grace_s"])
            # 手动冷却窗口内，规则不得把全屋从手动抢到「自动」——页面承诺
            # 「手动操作后 30 秒内不被自动规则改动」，模式横跳是风扇事故的
            # 放大器（刚手动关完，规则立刻切 auto）。切离家不受限（只关不开）。
            if mode == "auto":
                now = time.time()
                if any(self.home_mode.within_manual_grace(d, now)
                       for d in self.home_mode.GRACE_DEVICES):
                    return True, "设备处于手动冷却窗口，规则不切换到自动模式（保持手动）"
            self.home_mode.configure(reason="积木规则", **kw)
            # 覆盖档以前靠 1s tick 下发；手动模式下 tick 已被禁用，因此规则若
            # 显式带了覆盖档，这里立即执行一次（auto=True 走自动化硬门控）
            if "fan_override" in kw or "light_level" in kw:
                self.home_mode.apply_overrides_now(reason="积木规则", auto=True)
            parts = []
            if "mode" in kw:
                parts.append(f"模式={MODE_LABELS.get(kw['mode'], kw['mode'])}")
            if "fan_override" in kw:
                parts.append(f"风扇={FAN_LABELS.get(kw['fan_override'], kw['fan_override'])}")
            if "light_level" in kw:
                parts.append(f"灯光={LIGHT_LABELS.get(kw['light_level'], kw['light_level'])}")
            if "enabled" in kw:
                parts.append(f"自动调节={'开' if kw['enabled'] else '关'}")
            if "presence_hold_sec" in kw:
                parts.append(f"存在判定保持={kw['presence_hold_sec']:g}s")
            if "manual_grace_s" in kw:
                parts.append(f"手动冷却={kw['manual_grace_s']:g}s")
            return True, "全屋模式：" + "，".join(parts)
        if device == "voice":
            # 语音助手自带 HTTP 触发口：wake 免唤醒词进入指令模式（遥控器按键 1
            # 之类的「半自动」就是这条），say 直接让它播报/执行一句话
            if self.bridge is None or not getattr(self.bridge, "relay_url", ""):
                return False, "语音助手未配置（SMART_HOME_HW_RELAY）"
            act = action.get("action") or "wake"
            if act == "wake":
                ok, msg = self.bridge.voice_request("/trigger")
                return (True, "语音助手已唤醒") if ok else (False, msg)
            text = str(action.get("text") or "").strip()
            if not text:
                return False, "语音指令文本不能为空"
            ok, msg = self.bridge.voice_request("/say", {"text": text})
            return (True, f"语音助手已接收：{text}") if ok else (False, msg)
        if not self.bridge or not self.bridge.online and not self.bridge.relay_url:
            return False, "硬件桥离线"
        if device in ("door", "window"):
            # 积木动作用 open/close（窗另有 normal=45°）；DB 与页面约定 open/closed/normal
            status = action["status"]
            db_status = {"open": "open", "close": "closed"}.get(status, "normal")
            method = self.bridge.control_door if device == "door" else self.bridge.control_window
            label = "前门(自动化)" if device == "door" else "客厅窗户(自动化)"
            ok, msg = method(status)
            if ok:
                self.db.update_status(**{f"{device}_status": db_status})
                self.db.add_door_window_event(device, label, db_status)
                if device == "window":
                    # 同步去重缓存，否则档位覆盖会立刻把窗户改回原状态
                    self.home_mode.note_rule_action("window", status=status)
            return ok, msg
        if device == "light":
            status = action["status"]
            brightness = action["brightness"] if status == "on" else 0
            color = action.get("color") if status == "on" else None
            if color:
                ok, msg = self.bridge.control_light_color(
                    color, action.get("r"), action.get("g"), action.get("b"))
                # 颜色没有亮度通道，按「等效亮度」写库与去重缓存：
                # 白光用 value(0-255)，RGB 取三分量最大值，彩色预设按全亮
                if color == "white":
                    brightness = max(1, min(100, round(int(action.get("value", 255)) * 100 / 255)))
                elif color == "rgb":
                    peak = max(int(action.get("r") or 0), int(action.get("g") or 0),
                               int(action.get("b") or 0))
                    brightness = max(1, min(100, round(peak * 100 / 255)))
                else:
                    brightness = 100
            else:
                ok, msg = self.bridge.control_light(status, brightness)
            if ok:
                self.db.update_status(light_status=status, light_brightness=brightness)
                self.db.add_light_event("客厅主灯(自动化)", status, brightness)
                # 同步去重缓存并清掉档位覆盖，否则下一秒 tick 会用白光顶掉颜色
                self.home_mode.note_rule_action("light", status=status,
                                                brightness=brightness)
            return ok, msg
        if device == "fan":
            # 风扇状态机：set=绝对转速（旧规则兼容）；on/off 语义动作；
            # toggle=按 DB 当前转速在开/关间翻转（同一遥控器键按一次开、再按关），
            # 从关翻到开时用动作给定转速，没给正转速则恢复最近一次非零档位。
            op = action.get("op", "set")
            speed = int(action.get("speed", 60))
            target = speed
            if op == "off":
                target = 0
            elif op in ("on", "toggle"):
                current = 0
                try:
                    current = int(self.db.get_current_status().get("fan_speed") or 0)
                except Exception:                            # noqa: BLE001
                    current = 0
                if op == "toggle" and current > 0:
                    target = 0
                elif speed > 0:
                    target = speed
                else:
                    target = self.home_mode.fan_memory
            target = max(0, min(100, int(target)))
            # 自动化唯一入口：硬策略下规则只能关风扇（target=0），正转速被拦截，
            # 拦截时不写库、不记规则动作（applied=False）。
            ok, msg, applied = self.home_mode.auto_apply_fan(
                target, f"积木规则风扇动作（{op}）")
            if not applied:
                return True, msg
            if ok:
                self.db.update_status(fan_speed=target)
                self.home_mode.note_rule_action("fan", speed=target)
                if op == "set":
                    return ok, msg
                verb = {"on": "开启", "off": "关闭",
                        "toggle": "关闭" if target == 0 else "开启"}.get(op, "设置")
                return True, f"风扇已{verb}（{target}%）"
            return ok, msg
        if device == "buzzer":
            # mode: beep(间歇，默认) / on(持续响) / off(停)
            mode = action.get("mode", "beep")
            if mode in ("on", "off"):
                return self.bridge.call_tool("buzzer", {"action": mode})
            return self.bridge.call_tool("buzzer", {
                "action": "beep", "count": action["count"],
                "on_ms": action["on_ms"], "off_ms": action["off_ms"]})
        if device == "ir":
            # 红外发射：先登记回声抑制窗口再下发（发射发生在调用内部，
            # 轮询线程可能在同一时刻抓到被 A 板接收头捡回来的码）
            key = self._ir_key(action)
            if key is None:
                return False, "红外发射需要 code，或 address + command"
            window = max(3.0, float(getattr(self.bridge, "poll_interval", 2.0) or 2.0) + 1.0)
            with self._lock:
                self._ir_echo_until[key] = time.time() + window
            ok, msg = self.bridge.control_ir(
                code=action.get("code"),
                address=action.get("address"), command=action.get("command"))
            if ok:
                return True, f"红外已发射 addr=0x{key[0]:02X} cmd=0x{key[1]:02X}"
            return False, msg
        if device == "ac":
            # 空调是"合并式"状态（一帧带齐开关/模式/温度/风速）：
            # 规则只给要改的项，其余按库里的当前值补齐后整帧下发。
            try:
                target, changed = midea_ac.apply_overrides(
                    ac_state_from_db(self.db),
                    **{k: action.get(k) for k in AC_KEYS})
            except (ValueError, TypeError) as e:
                return False, f"空调参数无效：{e}"
            if not changed:
                return True, "空调状态未变化"
            ok, msg = self.bridge.control_ac(**target.snapshot())
            if ok:
                write_ac_state(self.db, target)
                return True, "空调已更新"
            return False, msg
        if device == "oled":
            # 清屏比分快且不依赖占位符
            if action.get("clear"):
                return self.bridge.call_tool("oled", {"action": "clear"})
            text = self._oled_format(action.get("text", ""))
            if not text.strip():
                return False, "OLED 文本为空"
            # 指定行：一行只能放一行文本，取第一个非空行直发
            fixed = action.get("line")
            if fixed is not None:
                block = next((b.strip() for b in text.split("\n") if b.strip()), "")
                if not block:
                    return False, "OLED 文本为空"
                return self.bridge.call_tool(
                    "oled", {"action": "show_text", "line": int(fixed), "text": block})
            # 未指定：支持按换行拆到 line 0..7
            lines = [blk.strip() for blk in text.split("\n")[:8] if blk.strip()]
            if not lines:
                return False, "OLED 文本为空"
            ok_all, last_msg = True, ""
            for line_no, block in enumerate(lines):
                ok, last_msg = self.bridge.call_tool(
                    "oled", {"action": "show_text", "line": line_no, "text": block})
                if not ok:
                    ok_all = False
                    break
            return ok_all, last_msg
        return False, f"未知设备 {device}"

    def _oled_format(self, template: str) -> str:
        """用轮播数据源替换动作文本里的 {占位符}。"""
        try:
            self._oled_carousel.set_data(self._oled_data())
            return self._oled_carousel.format_text(str(template))
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] OLED 模板格式化失败: %s", e)
            return str(template)

    def _log(self, rule, fired, conditions_hold, reason, ok, detail) -> None:
        try:
            self.db.add_automation_log(
                rule_id=rule["id"], rule_name=rule["name"],
                triggered=1 if fired else 0, conditions_hold=1 if conditions_hold else 0,
                reason=reason, success=1 if ok else 0,
                detail=json.dumps(detail, ensure_ascii=False))
        except Exception as e:                           # noqa: BLE001
            logger.debug("[自动化] 执行记录写库失败: %s", e)

    def manual_fire(self, rule_id: str) -> dict:
        """页面「立即测试」：无视冷却与触发沿，按当前条件直接执行一轮。"""
        with self._lock:
            rule = next((r for r in self.rules if r["id"] == rule_id), None)
        if rule is None:
            return {"ok": False, "error": "规则不存在"}
        self._last_fire[rule["id"]] = time.time()
        ctx = self._context()
        hold = self._conditions_hold(rule, ctx)
        branch = rule["actions"] if hold else rule.get("else_actions", [])
        if not branch:
            return {"ok": True, "conditions_hold": hold,
                    "message": "当前条件不成立，且该规则没有「否则」动作"}
        lock = self._action_locks.setdefault(rule["id"], threading.Lock())
        if not lock.acquire(blocking=False):
            return {"ok": False, "error": "上一轮动作仍在执行，请稍后"}
        threading.Thread(
            target=self._run_actions,
            args=(rule, branch, hold, "页面手动测试", lock),
            name=f"auto-manual-{rule['id']}", daemon=True).start()
        return {"ok": True, "conditions_hold": hold,
                "message": "已按当前条件提交执行（条件成立走「那么」，否则走「否则」）"}

    # ==================== 调试 API 支撑 ====================

    def preview(self) -> list[dict]:
        """基于当前快照，给出每条规则的触发/条件实时判定（不执行动作）。"""
        ctx = self._context()
        result = []
        with self._lock:
            for rule in self.rules:
                trig = rule["trigger"]
                if trig["kind"] == "sensor":
                    trigger_now = self._compare(
                        ctx.get(trig["sensor"]), trig["op"], trig["value"])
                elif trig["kind"] == "event":
                    trigger_now = None      # 事件类无法静态预测
                elif trig["kind"] == "interval":
                    trigger_now = None
                else:
                    trigger_now = datetime.now().strftime("%H:%M") == trig["hhmm"]
                result.append({
                    "id": rule["id"], "name": rule["name"],
                    "enabled": rule.get("enabled", True),
                    "trigger_now": trigger_now,
                    "conditions": [
                        {"sensor": c["sensor"], "op": c["op"], "value": c["value"],
                         "current": ctx.get(c["sensor"]),
                         "hold": self._eval_condition(c, ctx)}
                        for c in rule["conditions"]],
                    "conditions_hold": self._conditions_hold(rule, ctx),
                })
        return result
