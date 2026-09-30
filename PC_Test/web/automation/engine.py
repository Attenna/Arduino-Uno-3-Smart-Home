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
- 传感器触发为**上升沿**：条件由假变真的瞬间只触发一次（跨阈值防刷屏）；
- 每条规则有 cooldown 冷却与独立的动作锁（动作序列执行中不重入）；
- 条件不成立时执行 else_actions（「状态切换」，如温度回落自动关风扇）；
- 引擎任何异常只写日志，绝不能拖垮 bridge 轮询线程。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .capabilities import CONDITION_SOURCES, EVENT_TRIGGERS
from .schema import validate_rules

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
        self._last_fire: dict[str, float] = {}       # 上次开火时间（冷却）
        self._last_event_id: dict[str, int] = {}
        self._last_interval: dict[str, float] = {}
        self._last_time_key: dict[str, str] = {}
        self._action_locks: dict[str, threading.Lock] = {}
        self._stopping = False
        self._tick_thread: threading.Thread | None = None

    # ==================== 生命周期 ====================

    def start(self) -> None:
        self.load()
        self._tick_thread = threading.Thread(
            target=self._tick_loop, name="automation-tick", daemon=True)
        self._tick_thread.start()
        logger.info("[自动化] 引擎已启动，规则 %d 条", len(self.rules))

    def stop(self) -> None:
        self._stopping = True

    # ==================== 规则持久化 ====================

    def load(self) -> None:
        if not self.rules_path.exists():
            self.rules = []
            return
        try:
            data = json.loads(self.rules_path.read_text(encoding="utf-8"))
            self.rules = validate_rules(data)
        except Exception as e:
            logger.error("[自动化] 规则文件读取失败，保留空规则: %s", e)
            self.rules = []

    def save_rules(self, rules: list[dict]) -> list[dict]:
        """校验并落盘新规则集（整表替换），返回补全 id 后的规则。"""
        clean = validate_rules(rules)
        with self._lock:
            old_ids = {r["id"] for r in self.rules}
            for rule in clean:
                if not rule["id"]:
                    rule["id"] = uuid.uuid4().hex[:8]
            self.rules = clean
            self.rules_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.rules_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"rules": clean}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.rules_path)
            # 清理已删除规则的运行期状态
            new_ids = {r["id"] for r in clean}
            for store in (self._prev_trigger, self._last_fire, self._last_event_id,
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
            for rule in list(self._iter_enabled()):
                if rule["trigger"]["kind"] == "sensor":
                    self._evaluate_sensor_rule(rule)
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] 快照求值异常: %s", e)

    def on_event(self, event: dict) -> None:
        """离散事件：A 板 motion/keypad/ir 或人脸授权。线程安全。"""
        try:
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

    # ==================== 周期/定时触发 ====================

    def _tick_loop(self) -> None:
        while not self._stopping:
            time.sleep(1.0)
            try:
                now = time.time()
                minute = datetime.now().strftime("%H:%M")
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

    # ==================== 规则求值 ====================

    def _iter_enabled(self):
        with self._lock:
            for rule in self.rules:
                if rule.get("enabled", True):
                    yield rule

    def _context(self) -> dict:
        """传感器快照 + SQLite 中的执行器当前状态。"""
        ctx = dict(self._snapshot)
        try:
            status = self.db.get_current_status()
            for key in ("door_status", "window_status", "light_status", "fan_speed"):
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
        trig = rule["trigger"]
        ctx = self._context()
        now_true = self._compare(ctx.get(trig["sensor"]), trig["op"], trig["value"])
        was_true = self._prev_trigger.get(rule["id"], False)
        self._prev_trigger[rule["id"]] = now_true
        # 上升沿触发
        if now_true and not was_true:
            label = CONDITION_SOURCES.get(trig["sensor"], {}).get("label", trig["sensor"])
            self._fire(rule, reason=f"{label} {trig['op']} {trig['value']}")

    def _evaluate_event_rule(self, rule: dict, seq: int, event: dict) -> None:
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
        label = EVENT_TRIGGERS[trig["event"]]["label"]
        self._fire(rule, reason=label)

    def _fire(self, rule: dict, reason: str) -> None:
        now = time.time()
        if now - self._last_fire.get(rule["id"], 0.0) < float(rule.get("cooldown", 3)):
            return
        self._last_fire[rule["id"]] = now
        lock = self._action_locks.setdefault(rule["id"], threading.Lock())
        if not lock.acquire(blocking=False):
            logger.info("[自动化] 规则「%s」上一轮动作未完成，跳过", rule["name"])
            return
        ctx = self._context()
        hold = self._conditions_hold(rule, ctx)
        branch = rule["actions"] if hold else rule.get("else_actions", [])
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
        if device == "delay":
            time.sleep(float(action["seconds"]))
            return True, f"等待 {action['seconds']:g}s"
        if not self.bridge or not self.bridge.online and not self.bridge.relay_url:
            return False, "硬件桥离线"
        if device == "door":
            status = action["status"]
            ok, msg = self.bridge.control_door(status)
            if ok:
                self.db.update_status(door_status=status)
                self.db.add_door_window_event("door", "前门(自动化)", status)
            return ok, msg
        if device == "window":
            status = action["status"]
            ok, msg = self.bridge.control_window(status)
            if ok:
                self.db.update_status(window_status=status)
                self.db.add_door_window_event("window", "客厅窗户(自动化)", status)
            return ok, msg
        if device == "light":
            status = action["status"]
            brightness = action["brightness"] if status == "on" else 0
            ok, msg = self.bridge.control_light(status, brightness)
            if ok:
                self.db.update_status(light_status=status, light_brightness=brightness)
                self.db.add_light_event("客厅主灯(自动化)", status, brightness)
            return ok, msg
        if device == "fan":
            speed = action["speed"]
            ok, msg = self.bridge.control_fan(speed)
            if ok:
                self.db.update_status(fan_speed=speed)
            return ok, msg
        if device == "buzzer":
            return self.bridge.call_tool("buzzer", {
                "action": "beep", "count": action["count"],
                "on_ms": action["on_ms"], "off_ms": action["off_ms"]})
        return False, f"未知设备 {device}"

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
