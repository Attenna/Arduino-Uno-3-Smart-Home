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
                                    hardware bridge（MCP stdio → mcp_home_server）
                                                ─▶ Module B

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

import copy
import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from .capabilities import CONDITION_SOURCES, EVENT_TRIGGERS
from .default_rules import DEFAULT_RULES, PRESET_LEGACY_CONTENT, PRESETS_VERSION
from ..doorway import DoorwayDistance
from .global_state import GlobalStateStore, ID_PREFIX
from .oled_carousel import (DEFAULT_PAGES, PAGES_VERSION, OledCarousel,
                            OLED_MIN_INTERVAL, is_legacy_default_pages)
from .schema import validate_rule, validate_rules
from . import webhook
import midea_ac
from .. import voice_client
from .. import light_state
from ..ac_state import AC_LOCK, AC_KEYS, ac_state_from_db, write_ac_state
# RFID 卡号归一化：规则里存的与事件里带的两侧都归一后再比
from ..database import normalize_uid

logger = logging.getLogger(__name__)

# OLED 用英文标签（B 板 u8x8 字库只有 ASCII，汉字上屏是乱码）；页面/接口仍用中文
_MODE_LABELS_OLED = {"auto": "Auto", "manual": "Manual", "away": "Away"}


def _is_state_source(sensor) -> bool:
    """触发源是否为全局状态（``g:`` 变量）。

    这类源由 global_state 维护、与 A 板快照无关，因此「快照陈旧清理」与「滴答
    求值」都要把它与传感器源区别对待（见 on_snapshot / _tick_loop）。
    """
    return str(sensor or "").startswith(ID_PREFIX)


# 关键安全动作（关门/关窗/蜂鸣报警）失败后的有界重试：串口偶发忙/超时不应该让
# 「挡窗」「关门」这类安全动作直接放弃。非安全动作保持 fail-fast，避免把一次
# 明确的失败拖成多次副作用（见 R5）。
SAFETY_RETRY = 2
SAFETY_RETRY_DELAY = 1.0


def _is_safety_action(action: dict) -> bool:
    """关门 / 关窗 / 蜂鸣（非 off）——失败值得重试的动作。"""
    device = action.get("device")
    if device in ("door", "window"):
        return action.get("status") == "close"
    if device == "buzzer":
        return action.get("mode", "beep") != "off"
    return False


class AutomationEngine:
    def __init__(self, bridge, db, rules_path: Path, cfg: dict | None = None):
        self.bridge = bridge
        self.db = db
        self.rules_path = Path(rules_path)
        self.rules: list[dict] = []
        # HTTP 出站动作的主机放行策略（web_config.yaml 的 automation: 段）
        self._cfg = cfg or {}

        self._lock = threading.RLock()          # 保护规则热更新
        self._snapshot: dict = {}               # A 板最新一帧（原始字段名）
        self._snapshot_ts: float = 0.0
        # 光照明暗判定（带回差）：raw≥730 判暗、raw≤670 判亮，区间内维持上一状态。
        # light_dark 作为布尔源供积木引用，回差避免灯光回照导致的自激抖动。
        self._light_dark: bool | None = None
        self.doorway = DoorwayDistance()
        self.capture_photo = None
        # 事件队列（带序号），规则按各自 last_event_id 消费
        self._events: list[tuple[int, dict]] = []
        self._event_seq = 0
        # 每条规则的运行期状态
        self._prev_trigger: dict[str, bool] = {}     # 上次触发条件真假（边沿）
        self._armed: set[str] = set()                # 该规则已建立过触发基线
        self._hold_since: dict[str, float] = {}      # 「持续 N 秒」起算时刻
        self._hold_fired: dict[str, bool] = {}       # 本轮持续是否已触发过
        self._last_fire: dict[str, float] = {}       # 上次开火时间（冷却）
        self._last_event_id: dict[str, int] = {}
        self._last_interval: dict[str, float] = {}
        self._last_time_key: dict[str, str] = {}
        self._action_locks: dict[str, threading.Lock] = {}
        self._running: dict[str, threading.Event] = {}
        self._execution = threading.local()
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
        # 最近一次启动的旧规则迁移结果（页面提示一次后由 API 消费清空）
        self._migration_info: dict | None = None

        # ── OLED（V2.12：屏上 3 页 Environment/Devices/Safety 已由 B 板固件每 15s
        # 主动拉取渲染，香橙派不再逐行推送。此处配置仅存档；`_oled_carousel` 仍供
        # {} 占位符格式化与手动 oled 工具/规则使用） ──
        self.oled_path = Path(rules_path).parent / "oled_carousel.json"
        self.oled_enabled = False
        self.oled_interval = OLED_MIN_INTERVAL
        self.oled_pages: list[dict] | None = None
        self._oled_config_loaded = False
        self._oled_carousel = OledCarousel(emitter=self._oled_emit,
                                           on_log=self._oled_log)

        # ── 自动化下发去重（原 home_mode 的 _last_fan/_fan_memory，状态机拆除后留在引擎）──
        # 只记「最近一次自动化下发的值」，同值重放不再占串口；手动/语音不经这里，互不影响
        self._last_cmd: dict[str, object] = {}
        self._fan_memory = 60            # 风扇最近一次非零转速（on/toggle 缺省档位）

        # ── 全局状态（自由命名变量，见 global_state.py）──
        # 变量 id 形如 "g:名字"。读侧靠 _context() 合并（触发/条件积木零改动即可
        # 引用），写侧靠「设置全局状态」动作。与规则文件同目录、同单进程约定。
        self.global_state = GlobalStateStore(
            Path(rules_path).parent / "global_state.json")

    # ==================== HTTP 出站（webhook）策略 ====================

    @property
    def http_policy(self) -> dict:
        """页面保存时的严格主机策略；None 之外的键都来自 web_config.yaml。"""
        section = self._cfg.get("automation") or {}
        return {
            "enabled": bool(section.get("http_enabled", True)),
            "allow_public": bool(section.get("http_allow_public", False)),
            "allowed_hosts": [str(h) for h in (section.get("http_allowed_hosts") or ())],
        }

    def _http_timeout(self) -> float:
        section = self._cfg.get("automation") or {}
        return webhook.clamp_timeout(section.get("http_timeout", 2.0))

    # ==================== 生命周期 ====================

    def start(self) -> None:
        self.load()
        self._load_oled_config()
        self._tick_thread = threading.Thread(
            target=self._tick_loop, name="automation-tick", daemon=True)
        self._tick_thread.start()
        # OLED 轮播线程已移除：屏上内容现由 B 板固件每 15s 主动拉取渲染，
        # 香橙派不再逐行下发（避免持续串口流量触发 B 板复位）。
        logger.info("[自动化] 引擎已启动，规则 %d 条", len(self.rules))

    def stop(self) -> None:
        self._stopping = True
        with self._lock:
            for cancelled in self._running.values():
                cancelled.set()

    # ==================== 规则持久化 ====================

    # 旧引擎硬编码时代的引用 → 全局状态种子变量（无损映射，见 _migrate_legacy_rules）
    _LEGACY_SOURCE_MAP = {"home_mode": "g:全屋模式", "person_present": "g:有人在家"}
    # 拆除后不再有对应物的源：带这些引用的规则整条丢弃（宁缺勿猜）
    _LEGACY_UNMAPPABLE = ("home_enabled", "home_fan", "home_light")
    # v4 起删除的预设：touch_toggle 拆成两条条件规则，档位 cycle 类不再重建
    _REMOVED_PRESETS = ("ir_fan_toggle", "ir_fan_cycle", "ir_light_cycle_2", "ir_light_cycle_3",
                        "touch_toggle", "touch_to_manual", "touch_to_auto",
                        "door_in", "door_out", "dwell_alarm", "light_mid",
                        "access_auto_close",
                        # v10（R2）：门/空调没有周期性自动规则去覆盖手动操作，
                        # 「手动优先」只写不读，删除这 4 条误导性预设。
                        "manual_mark_door", "manual_clear_door",
                        "manual_mark_ac", "manual_clear_ac")
    # v5：门禁鉴权事件由「只有人脸」的 face_granted 换成统一的 access_granted
    # （带 method=face/rfid/keypad）。旧事件名不再有任何广播方，因此自定义规则
    # 里的 face_granted 触发就地换成等价写法，行为不变（只有人脸通过时才触发）。
    _LEGACY_EVENT_MAP = {"face_granted": ("access_granted", "face")}
    # 同批改名的预设：语义没变，保留用户开关与规则 id，只把内容换成新版
    _PRESET_RENAMES = {"face_open_door": "access_open_door",
                       "face_open_close": "access_auto_close"}

    def load(self) -> None:
        # 种子全局状态先就位：迁移与规则里都会引用 g:xxx，变量必须先存在
        self.global_state.seed_defaults()
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
            presets_version = int(data.get("presets_version") or 0)
        except (TypeError, ValueError):
            presets_version = 0
        if presets_version < 6:
            self.global_state.set_value("g:允许自动开风扇", True, source="全屋自动化升级")
        rules_list = self._migrate_legacy_rules(
            data.get("rules") or [], presets_version, from_file=raw is not None)
        # 逐条校验：坏的只跳过这一条并告警。以前整表 validate_rules 抛错会把
        # self.rules 清成 []，而 _presets_seen 已从旧文件读入 ⇒ 预设也不补，
        # 升级后得到「几乎空的规则集且页面无提示」。
        clean, bad_names = [], []
        for item in rules_list:
            try:
                clean.append(validate_rule(item, strict=False))
            except Exception as e:                       # noqa: BLE001
                label = (item.get("name") if isinstance(item, dict) else item)
                bad_names.append(f"{label}: {e}")
                logger.warning("[自动化] 规则不合法已跳过「%s」: %s", label, e)
        self.rules = clean
        if bad_names and self._migration_info is not None:
            self._migration_info["invalid"] = bad_names
        if self.seed_presets():
            self._write_rules()
        elif self._migration_info and any(
                self._migration_info.get(k)
                for k in ("migrated", "dropped", "warnings", "invalid")):
            # 迁移结果落盘，下次启动不再重复迁移（写盘会带上当前 PRESETS_VERSION）。
            # 只在有内容改动时写会漏掉「预设全被用户改过、只产出告警」这一支——版本号
            # 不前进，每次重启都会重复弹同一批提示（见 R4）。
            self._write_rules()

    # R4：比对预设是否等于某个历史内置版本。id/name/enabled 属于用户（改名、
    # 开关都不算定制），所以「内容」只比触发/条件/动作/匹配/冷却。
    _PRESET_CONTENT_KEYS = ("trigger", "conditions", "actions", "else_actions",
                            "match", "cooldown")
    _PRESET_LIST_KEYS = ("conditions", "actions", "else_actions")

    @classmethod
    def _preset_content_matches(cls, rule: dict, variants: list) -> bool:
        def content(r: dict) -> dict:
            # 缺 key 与空列表是同一个意思（校验层会把缺失的 conditions 归一成 []）
            return {k: (r.get(k) or [] if k in cls._PRESET_LIST_KEYS else r.get(k))
                    for k in cls._PRESET_CONTENT_KEYS}
        mine = content(rule)
        return any(mine == content(v) for v in variants)

    def _rule_is_legacy(self, rule: dict) -> bool:
        """规则里是否还有引擎硬编码时代的源/动作/事件引用（home_mode、face_granted 等）。"""
        trig = rule.get("trigger") or {}
        if trig.get("kind") == "event" and trig.get("event") in self._LEGACY_EVENT_MAP:
            return True
        if trig.get("kind") == "sensor" and (
                trig.get("sensor") in self._LEGACY_SOURCE_MAP
                or trig.get("sensor") in self._LEGACY_UNMAPPABLE):
            return True
        for c in rule.get("conditions") or []:
            if isinstance(c, dict) and (
                    c.get("sensor") in self._LEGACY_SOURCE_MAP
                    or c.get("sensor") in self._LEGACY_UNMAPPABLE):
                return True
        for key in ("actions", "else_actions"):
            for a in rule.get(key) or []:
                if isinstance(a, dict) and a.get("device") == "home_mode":
                    return True
        return False

    def _map_legacy_action(self, action: dict, warns: list[str]) -> tuple[dict | None, bool]:
        """home_mode 动作 → 无损映射为 state 动作；不可表达的项丢弃并告警。

        ``mode: auto/manual/away`` 直接映射到 ``g:全屋模式``；``toggle`` 与
        ``fan_override/light_level/enabled/presence_hold_sec/manual_grace_s``
        是旧状态机的私有语义，积木世界里没有无损等价物 —— 宁缺勿猜，去掉并记 warning。
        """
        if action.get("device") != "home_mode":
            return action, False
        mode = action.get("mode")
        dropped = [k for k in ("fan_override", "light_level", "enabled",
                               "presence_hold_sec", "manual_grace_s")
                   if action.get(k) not in (None, "")]
        if mode == "toggle":
            dropped.append("mode:toggle")
            mapped = None
        elif mode in ("auto", "manual", "away"):
            mapped = {"device": "state", "name": "g:全屋模式",
                      "op": "set", "value": mode}
        else:
            mapped = None
        if dropped:
            warns.append("丢弃不可映射的动作参数：" + "、".join(dropped))
        return mapped, True

    def _map_legacy_rule(self, rule: dict) -> tuple[dict | None, bool, str]:
        """自定义规则就地映射（深拷贝）。返回 (新规则或 None, 是否改动, 丢弃原因)。"""
        new = copy.deepcopy(rule)
        changed = False
        warns: list[str] = []
        trig = new.get("trigger") or {}
        if trig.get("kind") == "event" and trig.get("event") in self._LEGACY_EVENT_MAP:
            # 旧的门禁事件只有人脸一条来源；换成统一事件 + 限定方式，行为等价
            trig["event"], trig["method"] = self._LEGACY_EVENT_MAP[trig["event"]]
            changed = True
        for holder in [trig] + list(new.get("conditions") or []):
            sensor = holder.get("sensor")
            if sensor in self._LEGACY_UNMAPPABLE:
                return None, False, f"条件源「{sensor}」已随引擎仲裁拆除，无法映射"
            if sensor in self._LEGACY_SOURCE_MAP:
                holder["sensor"] = self._LEGACY_SOURCE_MAP[sensor]
                changed = True
        for key in ("actions", "else_actions"):
            kept, any_map = [], False
            for a in new.get(key) or []:
                if not isinstance(a, dict):
                    continue
                mapped, did = self._map_legacy_action(a, warns)
                any_map = any_map or did
                if mapped is not None:
                    kept.append(mapped)
            if any_map:
                new[key] = kept
                changed = True
        if changed and not (new.get("actions") or new.get("else_actions")):
            return None, False, "全部动作都是旧状态机私有语义，无可映射等价物"
        reason = ("；".join(dict.fromkeys(warns))) if warns else ""
        return new, changed, reason

    def _migrate_legacy_rules(self, rules: list, presets_version: int,
                              from_file: bool) -> list:
        """把 home_mode 时代的规则一次性迁到全局状态上（迁移方案·阶段二）。

        策略（宁缺勿猜，原文件先备份到 ``automation_rules.pre-global-state.json``）：

        * **内置预设**（带已知 preset 标记的旧文件规则）整体换成 v4 等价版，
          保留用户的开关状态与规则 id —— 这是行为等价的关键：旧 temp_hot 不带
          「g:允许自动开风扇」条件，阶段三拆掉 auto_apply_fan 后安全线会静默失效；
        * **自定义规则**只做无损映射（home_mode→g:全屋模式、person_present→g:有人在家、
          mode 动作→state 动作）；``fan_override/light_level/enabled`` 等参数与
          ``mode:toggle`` 丢弃并记 warning；
        * 已删除预设（档位 cycle、touch_toggle）直接删，替代预设由 seed_presets 补；
        * 结果存到 ``self._migration_info``，由 GET /api/automation/rules 消费、
          前端 boot 时 toast 一次。
        """
        items = [r for r in rules if isinstance(r, dict)]
        needs = from_file and (presets_version < PRESETS_VERSION
                               or any(self._rule_is_legacy(r) for r in items))
        if not needs:
            return items
        # 备份只在迁移发生时做一次，且不覆盖已有备份（保留最早的原文件）
        try:
            if self.rules_path.exists():
                backup = self.rules_path.with_name(
                    "automation_rules.pre-global-state.json")
                if not backup.exists():
                    backup.write_bytes(self.rules_path.read_bytes())
                    logger.info("[自动化] 旧规则文件已备份 → %s", backup.name)
        except Exception as e:                           # noqa: BLE001
            logger.warning("[自动化] 旧规则备份失败（继续迁移）: %s", e)
        v4_by_pid = {p["preset"]: p for p in DEFAULT_RULES if p.get("preset")}
        out, migrated, dropped = [], 0, []
        warns: list[str] = []
        for rule in items:
            pid = str(rule.get("preset") or "")
            name = str(rule.get("name") or pid or "?")
            if pid in self._REMOVED_PRESETS:
                dropped.append(name)
                continue
            pid = self._PRESET_RENAMES.get(pid, pid)
            if pid in self._REMOVED_PRESETS:
                dropped.append(name)
                continue
            if (presets_version >= 6 and pid in v4_by_pid
                    and pid in {"away_close_all", "window_normal"}):
                # v9 给两条未改动的内置预设补「手动优先」让位条件：仍与旧内置版一致才换新，
                # 用户改过的一律保留（与下方 R4 同一策略）。
                old = copy.deepcopy(v4_by_pid[pid])
                old["conditions"] = [
                    c for c in old.get("conditions", [])
                    if not str(c.get("sensor", "")).startswith("g:手动优先_")]
                keys = ("trigger", "conditions", "actions", "else_actions", "match", "cooldown")
                default_for = {"conditions": [], "else_actions": [], "match": "all", "cooldown": 3}
                if all(rule.get(k, default_for.get(k)) == old.get(k, default_for.get(k))
                       for k in keys):
                    new = copy.deepcopy(v4_by_pid[pid])
                    new["id"] = rule.get("id") or None
                    new["enabled"] = bool(rule.get("enabled", True))
                    out.append(new)
                    migrated += 1
                    continue
                out.append(rule)
                continue
            if presets_version >= 8 and pid in v4_by_pid:
                out.append(rule)
                continue
            if (presets_version >= 6 and pid in v4_by_pid
                    and pid not in PRESET_LEGACY_CONTENT):
                # v6 起内置预设已带完整全局状态条件；保留用户对这些预设的配置。
                out.append(rule)
                continue
            if pid in v4_by_pid and presets_version < PRESETS_VERSION:
                legacy = PRESET_LEGACY_CONTENT.get(pid)
                if presets_version >= 6 and legacy \
                        and not self._preset_content_matches(rule, legacy):
                    # 用户改过这条预设 → 不覆盖（R4）。以前是无条件替换，会把用户
                    # 调过的阈值/动作悄悄改回内置值。
                    warns.append(f"「{name}」：内置版本已更新，但你改过这条规则，"
                                 "已保留你的版本")
                    out.append(rule)
                    continue
                if presets_version < 6:
                    # 太老的文件（v6 之前）无法可靠判定是否被改过：只能整体换新，
                    # 但必须告警，避免用户以为自己的定制还在。
                    warns.append(f"「{name}」：内置规则结构已升级，已换成新版")
                new = copy.deepcopy(v4_by_pid[pid])
                new["id"] = rule.get("id") or None
                new["enabled"] = bool(rule.get("enabled", True))  # 保留用户开关
                out.append(new)
                migrated += 1
                continue
            if not self._rule_is_legacy(rule):
                out.append(rule)
                continue
            mapped, changed, why = self._map_legacy_rule(rule)
            if mapped is None:
                dropped.append(name)
                if why:
                    warns.append(f"「{name}」：{why}")
                continue
            if changed:
                migrated += 1
                if why:
                    warns.append(f"「{name}」：{why}")
            out.append(mapped)
        self._migration_info = {"migrated": migrated, "dropped": dropped,
                                "warnings": warns[:10]}
        logger.info("[自动化] 旧规则迁移：改写 %d 条、删除 %d 条（预设 %d 条已换成全局状态版）",
                    migrated, len(dropped), len(v4_by_pid))
        return out

    def consume_migration_info(self) -> dict | None:
        """返回最近一次启动的迁移结果（只给一次，前端提示后不再重复弹）。"""
        info, self._migration_info = self._migration_info, None
        return info

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
                self.rules = validate_rules(self.rules, strict=False)
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
        """校验并落盘新规则集（整表替换），返回补全 id 后的规则。

        页面保存走严格模式：引用的全局状态必须真实存在，避免用户写出
        永远不成立的错字规则（引擎读盘才是宽松模式，见 load）；
        HTTP 动作的主机也一并按 automation: 策略查，让用户当场看到而不是等执行失败。
        """
        clean = validate_rules(rules, vars_info=self.global_state.var_specs(),
                               http_policy=self.http_policy, strict=True)
        with self._lock:
            old_ids = {r["id"] for r in self.rules}
            old_rules = {r["id"]: r for r in self.rules}
            for rule in clean:
                if not rule["id"]:
                    rule["id"] = uuid.uuid4().hex[:8]
            for cancelled in self._running.values():
                cancelled.set()
            for rule in clean:
                if (rule["trigger"].get("sensor") == "distance_cm"
                        and old_rules.get(rule["id"]) != rule):
                    for store in (self._prev_trigger, self._hold_since, self._hold_fired, self._last_fire):
                        store.pop(rule["id"], None)
            self.rules = clean
            # 页面保存的规则里带 preset 标记的，同样计入「已注入过」
            self._presets_seen |= {r["preset"] for r in clean if r.get("preset")}
            self._write_rules()
            # 清理已删除规则的运行期状态
            new_ids = {r["id"] for r in clean}
            # 页面保存是用户显式动作：规则立即生效，不做「首轮只登记」的启动基线
            # （只有引擎启动时的首轮才需要基线，见 _evaluate_sensor_rule）
            self._armed |= new_ids
            for store in (self._prev_trigger, self._hold_since, self._hold_fired,
                          self._last_fire, self._last_event_id,
                          self._last_interval, self._last_time_key):
                for dead in old_ids - new_ids:
                    store.pop(dead, None)
            self._armed -= (old_ids - new_ids)
        logger.info("[自动化] 规则已保存，共 %d 条", len(clean))
        return clean

    def rewrite_state_refs(self, old_id: str, new_id: str) -> int:
        """全局状态改名后，把规则里的引用同步换成新 id，返回替换处数。

        改名前 id 只可能出现在三处：传感器触发/条件的 ``sensor``、
        「设置全局状态」动作的 ``name``。事件触发不涉及。
        """
        n = 0
        with self._lock:
            for rule in self.rules:
                trig = rule.get("trigger") or {}
                if trig.get("kind") == "sensor" and trig.get("sensor") == old_id:
                    trig["sensor"] = new_id
                    n += 1
                for cond in rule.get("conditions") or []:
                    if cond.get("sensor") == old_id:
                        cond["sensor"] = new_id
                        n += 1
                for key in ("actions", "else_actions"):
                    for act in rule.get(key) or []:
                        if act.get("device") == "state" and act.get("name") == old_id:
                            act["name"] = new_id
                            n += 1
            if n:
                self.rules = validate_rules(self.rules, strict=False)   # 宽松：变量已存在
                self._write_rules()
        if n:
            logger.info("[自动化] 全局状态改名 %s→%s，更新规则引用 %d 处",
                        old_id, new_id, n)
        return n

    # ==================== 外部输入（bridge / face API 调用） ====================

    def on_distance(self, payload):
        with self._lock:
            interrupted = self.doorway.update(payload)
            for rule in list(self._iter_enabled()):
                trig = rule["trigger"]
                if trig.get("sensor") != "distance_cm" or trig["kind"] != "sensor":
                    continue
                rid = rule["id"]
                if interrupted or not self.doorway.snapshot()["valid"]:
                    self._hold_since.pop(rid, None)
                    self._hold_fired.pop(rid, None)
                    self._prev_trigger[rid] = False
                # Fresh measurements may start a dwell immediately after startup.
                self._armed.add(rid)
                self._evaluate_sensor_rule(rule)

    def on_snapshot(self, snap: dict) -> None:
        """A 板周期数据（字段名：temperature/humidity/light/smoke/rain/touch/motion）。"""
        try:
            if self._snapshot_ts and time.time() - self._snapshot_ts > 10:
                for rule in self.rules:
                    sensor = rule["trigger"].get("sensor")
                    # 距离规则的中断由 doorway 自己判定；g: 变量与快照新鲜度无关，
                    # 否则传感器板离线会连带把「手动优先到期」的计时清掉
                    if sensor != "distance_cm" and not _is_state_source(sensor):
                        self._hold_since.pop(rule["id"], None)
                        self._hold_fired.pop(rule["id"], None)
            self._snapshot = dict(snap or {})
            self._snapshot_ts = time.time()
            for rule in list(self._iter_enabled()):
                if rule["trigger"]["kind"] == "sensor" and rule["trigger"].get("sensor") != "distance_cm":
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

    def note_external(self, device: str, value) -> None:
        """面板/语音手动下发后同步自动化下发去重水位（``_last_cmd``）。

        规则分支同值会跳过重发；不接这条，用户手动把风扇开到某档后，
        同档位的自动化规则会被静默跳过、与真实硬件脱节。
        """
        with self._lock:
            self._last_cmd[device] = value
            if device == "fan":
                try:
                    speed = int(value or 0)
                except (TypeError, ValueError):
                    speed = 0
                if speed > 0:
                    self._fan_memory = max(1, min(100, speed))

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

    # 定时触发错过后的补触发窗口（秒）。tick 被动作线程抢锁、系统挂起或 NTP 跳变
    # 都可能让某一拍错过整分钟；窗口内补一次，避免当天彻底漏触发。
    TIME_CATCHUP_SEC = 300

    def _tick_loop(self) -> None:
        while not self._stopping:
            time.sleep(1.0)
            try:
                # 计时一律用单调时钟：墙钟被 NTP 回拨/校时会让「持续 N 秒」「每 N 秒」
                # 出现负间隔或凭空超时（定时触发仍按墙钟的绝对时刻判定）
                now_mono = time.monotonic()
                for rule in list(self._iter_enabled()):
                    trig = rule["trigger"]
                    if trig["kind"] == "interval":
                        last = self._last_interval.get(rule["id"], 0.0)
                        if last == 0.0:
                            self._last_interval[rule["id"]] = now_mono
                        elif now_mono - last >= float(trig["seconds"]):
                            self._last_interval[rule["id"]] = now_mono
                            self._fire(rule, reason=f"每 {trig['seconds']:g} 秒")
                    elif trig["kind"] == "time":
                        self._maybe_fire_time(rule, datetime.now())
                    elif trig["kind"] == "sensor" and _is_state_source(trig.get("sensor")):
                        # g: 变量的 sensor 触发只在 on_snapshot 求值，传感器板离线时
                        # 永不触发（「手动优先到期释放」被永久卡住）；随 tick 补一条。
                        self._evaluate_sensor_rule(rule)
            except Exception as e:                   # noqa: BLE001
                logger.debug("[自动化] 滴答求值异常: %s", e)

    def _maybe_fire_time(self, rule: dict, now_wall: datetime) -> None:
        """定时触发：到达时刻后在补触发窗口内触发一次（按当日 key 去重）。

        原先要求 tick 恰好落在 ``minute == hhmm`` 那一刻，若该分钟 tick 被阻塞，
        当天就彻底漏触发；改为「已到点且当日未触发过」后，窗口内的下一拍会补上。
        """
        hhmm = rule["trigger"]["hhmm"]
        hour, minute = (int(x) for x in hhmm.split(":"))
        target = now_wall.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_wall < target or (now_wall - target).total_seconds() > self.TIME_CATCHUP_SEC:
            return
        key = f"{target:%Y-%m-%d} {hhmm}"
        if self._last_time_key.get(rule["id"]) == key:
            return
        self._last_time_key[rule["id"]] = key
        self._fire(rule, reason=f"定时 {hhmm}")

    # ==================== OLED 轮播（默认关闭） ====================

    def set_oled(self, pages=None, interval=None, enabled=None) -> dict:
        """配置 OLED 轮播。任一参数为 None 表示保持当前值。

        pages:   页面列表（{"title","lines"}），list 且非空才生效
        interval: 每页停留秒数（>=1）
        enabled:  是否启用轮播
        """
        self._load_oled_config()
        if interval is not None:
            if isinstance(interval, bool) or not isinstance(interval, (int, float)):
                raise ValueError("间隔必须是数字（秒）")
            self.oled_interval = max(OLED_MIN_INTERVAL, float(interval))
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
        self._load_oled_config()
        return {"enabled": self.oled_enabled, "interval": self.oled_interval,
                "pages": self.oled_pages or DEFAULT_PAGES}

    def _load_oled_config(self) -> None:
        """首次使用前把持久化配置载入轮播器。

        使用显式标志记录加载状态，避免把某个合法的默认间隔当作“尚未加载”
        哨兵。启动流程会在线程运行前调用本方法；API 入口也保留一次性兜底。
        """
        with self._lock:
            if self._oled_config_loaded:
                return
            self._oled_config_loaded = True
            try:
                if self.oled_path.exists():
                    cfg = json.loads(self.oled_path.read_text(encoding="utf-8"))
                    self.oled_enabled = bool(cfg.get("enabled", False))
                    self.oled_interval = max(
                        OLED_MIN_INTERVAL, float(cfg.get("interval", OLED_MIN_INTERVAL)))
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

    def _oled_data(self) -> dict:
        """A 板快照 + B 板执行器状态 + 最近自动化，组成扁平数据源。"""
        data = dict(self._snapshot)
        try:
            # 屏上是英文标签（B 板字库无汉字），页面/接口仍用中文标签。
            # 全屋模式已积木化：这三个占位符直接读全局状态，不再是引擎状态机。
            vals = self.global_state.values()
            data["home_mode"] = _MODE_LABELS_OLED.get(vals.get("g:全屋模式"), "Auto")
            data["presence"] = "YES" if vals.get("g:有人在家") else "NO"
            data["fan_auto"] = "YES" if vals.get("g:允许自动开风扇") else "NO"
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
            # 必须跳过 OLED 轮播自己写的那条日志：它每换一页就写一条（reason=显示页），
            # 若把它当「最近自动化」显示，就会形成
            #   页面内容变 → 重发 → 又写一条日志 → 页面内容再变
            # 的自反馈，OLED 会被反复重刷（实测 oled 调用量是全场第一，持续占用串口，
            # 把用户命令挤到秒级）。
            logs = [r for r in self.db.get_automation_logs(5)
                    if r.get("rule_id") != "oled_carousel"]
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
        """轮播逐行下发；桥离线时静默跳过。"""
        if not self.bridge or not self.bridge.online:
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

    # 光照明暗回差边界（现场实测：捂住光敏≈918、环境光≈479，两态分离≈440）。
    LIGHT_DARK_RAW = 730
    LIGHT_BRIGHT_RAW = 670

    def _track_light_dark(self, raw) -> None:
        """按回差维护 self._light_dark：raw≥730 判暗、raw≤670 判亮，区间内维持。"""
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return
        if raw >= self.LIGHT_DARK_RAW:
            self._light_dark = True
        elif raw <= self.LIGHT_BRIGHT_RAW:
            self._light_dark = False

    def _context(self) -> dict:
        """传感器快照 + SQLite 中的执行器当前状态 + 全局状态（g: 变量）。"""
        ctx = dict(self._snapshot)
        ctx["distance_cm"] = self.doorway.snapshot()["distance_cm"]
        ctx["sensor_fresh"] = bool(self._snapshot_ts and time.time() - self._snapshot_ts <= 10)
        if ctx["sensor_fresh"]:
            self._track_light_dark(ctx.get("light"))
            if self._light_dark is not None:
                ctx["light_dark"] = self._light_dark
        else:
            for key in ("temperature", "humidity", "light", "light_dark",
                        "motion", "touch", "rain", "smoke"):
                ctx.pop(key, None)
        try:
            status = self.db.get_current_status()
            for key in ("door_status", "window_status", "light_status",
                        "light_brightness", "fan_speed",
                        "sensor_online", "output_online"):
                if status.get(key) is not None:
                    ctx[key] = status[key]
        except Exception:                           # noqa: BLE001
            pass
        try:
            # 全局状态：直接以 "g:名字" 为键并入上下文，触发/条件积木无需任何
            # 特殊分支即可引用（_compare 已覆盖 bool/number/enum）。
            ctx.update(self.global_state.values())
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] 全局状态读取失败: %s", e)
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
            rid = rule["id"]
            ctx = self._context()
            if ctx.get(trig["sensor"]) is None:
                self._hold_since.pop(rid, None)
                self._hold_fired.pop(rid, None)
                return
            now_true = self._compare(ctx.get(trig["sensor"]), trig["op"], trig["value"])
            # 进程启动后的首轮求值：只把当前真值登记为基线，**绝不触发**。
            # DB 里的执行器状态是「上次命令下发值」，B 板一旦复位（开串口拉 DTR 就
            # 会复位 Uno）就与硬件脱节；若不建基线，首轮会把陈旧的 door_status='open'
            # 判成「假→真」新边沿，凭空触发一次规则（实测每次容器重建都会误触发
            # 「检测到人后开门 → 全屋自动」）。首轮取不到该传感器值时先不登记，
            # 等下一轮有数据再建基线，避免把「暂无数据」误当成 False。
            if rid not in self._armed:
                if ctx.get(trig["sensor"]) is None:
                    return
                self._armed.add(rid)
                self._prev_trigger[rid] = now_true
                return
            was_true = self._prev_trigger.get(rid, False)
            self._prev_trigger[rid] = now_true
            label = CONDITION_SOURCES.get(trig["sensor"], {}).get("label", trig["sensor"])
            reason = f"{label} {trig['op']} {trig['value']}"

            if not now_true:
                self._hold_since.pop(rid, None)
                self._hold_fired.pop(rid, None)
                # 下降沿：只有写了「否则」动作的规则才回切（雨停恢复 45° 这类）
                if was_true and rule.get("else_actions"):
                    self._fire(rule, reason=f"{reason} 已恢复", force_hold=False)
                return

            hold_sec = float(trig.get("hold_sec") or 0)
            if hold_sec <= 0:
                if not was_true:
                    self._fire(rule, reason=reason)
                return
            # 「持续 N 秒」：连续保持满 N 秒触发一次，中断（条件转假）则重新计时。
            # 计时用单调时钟，墙钟回拨/校时不会造成假超时。
            start = self._hold_since.get(rid)
            if start is None:
                self._hold_since[rid] = time.monotonic()
                return
            if time.monotonic() - start >= hold_sec and not self._hold_fired.get(rid):
                # 只有真正入队执行了才记「本轮已触发」：_fire 因冷却未到或动作锁
                # 被占而直接返回时必须保留触发权，否则本轮持续会被静默吞掉。
                if self._fire(rule, reason=f"{reason} 持续 {hold_sec:g} 秒"):
                    self._hold_fired[rid] = True

    def _evaluate_event_rule(self, rule: dict, seq: int, event: dict) -> None:
        with self._lock:
            # 只消费本规则没见过的事件；当前事件即新事件
            if seq <= self._last_event_id.get(rule["id"], 0):
                return
            self._last_event_id[rule["id"]] = seq
            trig = rule["trigger"]
            want = EVENT_TRIGGERS[trig["event"]].get("payload") or {}
            # 空 payload 会让下面的 all(...) 恒真 = 这条规则匹配**任意**事件。
            # 契约由 capabilities 的导入断言保证，这里是运行期兜底（见 R9）。
            if not want or not all(event.get(k) == v for k, v in want.items()):
                return
            if trig.get("key") and str(event.get("key", "")) != trig["key"]:
                return
            # 设备过滤（manual_control 事件带 device）：不填=任意设备的手动操作
            if trig.get("device") and str(event.get("device", "")) != str(trig["device"]):
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
            # 门禁事件的验证方式过滤（不填=任一方式：人脸/刷卡/键盘都算）
            if trig.get("method") and str(event.get("method", "")) != trig["method"]:
                return
            label = EVENT_TRIGGERS[trig["event"]]["label"]
            self._fire(rule, reason=label)

    def _fire(self, rule: dict, reason: str, force_hold: bool | None = None) -> bool:
        """触发一轮执行，返回是否**真的入队**。

        冷却未到、条件不成立且无「否则」动作、上一轮动作锁未释放都不算入队；
        调用方（「持续 N 秒」）必须据此决定是否记「本轮已触发」，否则会把一次
        被跳过的触发错当成已完成、整轮持续被静默吞掉。
        """
        with self._lock:
            # 冷却与「每 N 秒」同口径使用单调时钟：墙钟被 NTP 校时会凭空产生
            # 超长/负间隔（见 R10）。
            now = time.monotonic()
            if now - self._last_fire.get(rule["id"], 0.0) < float(rule.get("cooldown", 3)):
                return False
            ctx = self._context()
            hold = self._conditions_hold(rule, ctx) if force_hold is None else force_hold
            branch = rule["actions"] if hold else rule.get("else_actions", [])
            if not branch:
                # 条件不成立且没写「否则」动作：这条规则这次什么都不做（不记冷却、不记日志）
                return False
            lock = self._action_locks.setdefault(rule["id"], threading.Lock())
            if not lock.acquire(blocking=False):
                logger.info("[自动化] 规则「%s」上一轮动作未完成，跳过", rule["name"])
                return False
            self._last_fire[rule["id"]] = now
            threading.Thread(
                target=self._run_actions, args=(rule, branch, hold, reason, lock),
                name=f"auto-{rule['id']}", daemon=True).start()
            return True

    # ==================== 动作执行 ====================

    def _run_actions(self, rule, actions, hold, reason, lock: threading.Lock) -> None:
        detail: list[dict] = []
        ok_all = True
        cancelled = threading.Event()
        with self._lock:
            self._running[rule["id"]] = cancelled
        self._execution.cancelled = cancelled
        try:
            for action in actions:
                with self._lock:
                    current = next((r for r in self.rules if r["id"] == rule["id"]), None)
                    if self._stopping or current is not rule:
                        cancelled.set()
                if cancelled.is_set():
                    ok_all = False
                    detail.append({"cancelled": True, "reason": "规则已更新或服务停止"})
                    break
                ok, msg = self._perform_with_retry(action, rule)
                entry = {"action": action, "ok": ok, "result": msg}
                if not ok:
                    ok_all = False
                    if _is_safety_action(action):
                        # 安全动作重试耗尽：整条规则记为「部分成功」，前端/日志
                        # 能一眼看出是「前半段动作成功、关键安全动作没做到」。
                        entry["partial"] = True
                    detail.append(entry)
                    logger.warning("[自动化] 规则「%s」动作失败 %s: %s",
                                   rule["name"], action.get("device"), msg)
                    break
                detail.append(entry)
            if detail and all(d.get("ok") and "重复指令跳过" in d.get("result", "") for d in detail):
                return
            self._log(rule, fired=True, conditions_hold=hold, reason=reason,
                      ok=ok_all, detail=detail)
        except Exception as e:                       # noqa: BLE001
            # R14：任一动作的意外异常此前会直接冒泡出线程，规则既没记「部分成功」
            # 也不落执行日志。这里兜底成一次失败的执行记录，异常本身仍写入日志。
            ok_all = False
            detail.append({"action": None, "ok": False, "result": f"执行异常: {e}"})
            logger.exception("[自动化] 规则「%s」动作执行异常", rule["name"])
            self._log(rule, fired=True, conditions_hold=hold, reason=reason,
                      ok=False, detail=detail)
        finally:
            with self._lock:
                self._running.pop(rule["id"], None)
            self._execution.cancelled = None
            lock.release()

    def _perform_with_retry(self, action: dict, rule: dict | None) -> tuple[bool, str]:
        """关键安全动作失败后有界重试；其余动作 fail-fast（见 R5）。

        ``SAFETY_RETRY`` 是**额外**尝试次数（默认共 3 次），间隔 ``SAFETY_RETRY_DELAY``。
        重试会二次触发副作用，所以只用于关门/关窗/蜂鸣这类「没做到就有安全后果」的
        动作；关灯/开窗这类失败重试反而可能造成意外动作的动作不在此列。
        """
        ok, msg = self._perform(action, rule)
        if ok or not _is_safety_action(action):
            return ok, msg
        name = rule["name"] if rule else "?"
        for attempt in range(1, SAFETY_RETRY + 1):
            logger.warning("[自动化] 规则「%s」安全动作 %s 失败（%s），第 %d 次重试",
                           name, action.get("device"), msg, attempt)
            time.sleep(SAFETY_RETRY_DELAY)
            ok, msg = self._perform(action, rule)
            if ok:
                return True, f"{msg}（重试第 {attempt} 次成功）"
        return False, f"{msg}（已重试 {SAFETY_RETRY} 次仍失败）"

    def _perform(self, action: dict, rule: dict | None = None) -> tuple[bool, str]:
        device = action["device"]
        if device == "camera":
            if self.capture_photo is None:
                return False, "拍照服务未初始化"
            try:
                return self.capture_photo(rule or {}, self.doorway.snapshot())
            except Exception as exc:
                return False, f"照片存储失败: {exc}"
        # 「手动优先 30 秒让位」不再是引擎仲裁：面板/语音广播 manual_control
        # 事件，manual_mark_*/manual_clear_* 预设维护 g:手动优先_x，设备类预设
        # 带 ``g:手动优先_x == false`` 条件自行让位（见 default_rules.py）。
        if device == "delay":
            cancelled = getattr(self._execution, "cancelled", None)
            if cancelled is not None:
                if cancelled.wait(float(action["seconds"])):
                    return False, "延时已取消"
            else:
                time.sleep(float(action["seconds"]))
            return True, f"等待 {action['seconds']:g}s"
        if device == "state":
            # 全局状态写入：纯状态、不碰硬件，所以放在 bridge 在线检查之前
            # （桥离线也要能记账，否则规则里的变量会永久卡住）。
            name = str(action.get("name") or "")
            op = str(action.get("op") or "set")
            source = (f"规则「{rule['name']}」" if rule and rule.get("name")
                      else "规则")
            var_before = self.global_state.get(name) or {}
            unchanged = op == "set" and var_before.get("value") == action.get("value")
            if op == "toggle":
                ok, res = self.global_state.toggle(name, source=source)
            elif op == "add":
                ok, res = self.global_state.add(name, action.get("value", 1),
                                                source=source)
            else:
                ok, res = self.global_state.set_value(
                    name, action.get("value"), source=source)
            if not ok:
                return False, str(res)
            # Event-driven state assignment renews any hold timer watching that state.
            # This lets repeated manual controls extend grace without a false pulse.
            if op == "set" and rule and rule.get("trigger", {}).get("kind") == "event":
                with self._lock:
                    for waiting in self.rules:
                        trig = waiting.get("trigger", {})
                        if trig.get("kind") == "sensor" and trig.get("sensor") == name:
                            self._hold_since.pop(waiting["id"], None)
                            self._hold_fired.pop(waiting["id"], None)
            if unchanged:
                return True, "状态重复指令跳过"
            var = self.global_state.get(name) or {}
            return True, f"全局状态「{var.get('label', name)}」= {res}"
        if device == "http":
            # 二次开发预留的出站通道：不碰串口，所以同样放在在线检查之前。
            # 每次执行都按当前策略复查主机（策略改了不必让用户重存规则）。
            policy = self.http_policy
            if not policy["enabled"]:
                return False, "HTTP 出站已关闭（automation.http_enabled: false）"
            url = self._web_format(action.get("url", ""))
            ok, why = webhook.check_url(
                url, allow_public=policy["allow_public"],
                allowed_hosts=policy["allowed_hosts"])
            if not ok:
                return False, f"HTTP 已拒发：{why}"
            body = self._web_format(action.get("text") or "")
            sent, msg = webhook.request(url, method=action.get("method", "post"),
                                        body=body, timeout=self._http_timeout())
            if sent:
                return True, f"HTTP 已发送（{msg}）"
            # 目标不可达是外部系统的事：记为动作失败，不能让整条规则抛异常
            logger.info("[自动化] HTTP 出站失败 %s: %s", url, msg)
            return False, msg
        if device == "voice":
            # 语音助手自带 HTTP 触发口：wake 免唤醒词进入指令模式（遥控器按键 1
            # 之类的「半自动」就是这条），say 直接让它播报/执行一句话。
            # 与串口无关，独立经 voice_client 直达 :8101。
            act = action.get("action") or "wake"
            base = voice_client.resolve_voice_url(self._cfg)
            if act == "wake":
                ok, msg = voice_client.voice_request(base, "/trigger")
                return (True, "语音助手已唤醒") if ok else (False, msg)
            text = str(action.get("text") or "").strip()
            if not text:
                return False, "语音指令文本不能为空"
            ok, msg = voice_client.voice_request(base, "/say", {"text": text})
            return (True, f"语音助手已接收：{text}") if ok else (False, msg)
        if not self.bridge or not self.bridge.online:
            return False, "硬件桥离线"
        if device in ("door", "window"):
            # 积木动作用 open/close（窗另有 normal=45°）；DB 与页面约定 open/closed/normal
            status = action["status"]
            db_status = {"open": "open", "close": "closed"}.get(status, "normal")
            if device == "window" and status != "close":
                ctx = self._context()
                if ctx.get("rain") is not False or ctx.get("smoke") is not False:
                    return False, "雨水/烟雾未确认解除，暂不自动开窗"
            method = self.bridge.control_door if device == "door" else self.bridge.control_window
            label = "前门(自动化)" if device == "door" else "客厅窗户(自动化)"
            if device == "window" and self._last_cmd.get("window") == status and self.db.get_current_status().get("window_status") == db_status:
                return True, "窗户重复指令跳过"
            ok, msg = method(status)
            if ok and device == "window":
                self._last_cmd["window"] = status
            if ok:
                self.db.update_status(**{f"{device}_status": db_status})
                self.db.add_door_window_event(device, label, db_status)
            return ok, msg
        if device == "light":
            status = action["status"]
            brightness = action["brightness"] if status == "on" else 0
            color = action.get("color") if status == "on" else None
            current = self.db.get_current_status()
            # 积木只表达「开多亮」，没写颜色的规则**沿用当前亮法**：B 板没有「只改
            # 亮度」的指令，white 命令必然覆盖颜色，所以缺省成白光会把用户选的夜灯/
            # 色温/自定义颜色在硬件上清掉（#27 在规则路径上的同一症状）。
            style = (light_state.from_color_param(
                color, action.get("r"), action.get("g"), action.get("b"))
                if color else light_state.from_status(current))
            count = current.get("light_count") if not color else None
            target_light = (status, brightness, style, count)
            if not color and self._last_cmd.get("light") == target_light \
                    and (current.get("light_status"), current.get("light_brightness")) == (status, brightness):
                return True, "灯重复指令跳过"
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
                # 与面板同一条口径：下发前把亮法展开成固件能执行的完整命令
                method, args, kwargs = light_state.hardware_plan(status, brightness, style, count)
                ok, msg = getattr(self.bridge, method)(*args, **kwargs)
            if ok:
                self._last_cmd["light"] = target_light if not color else None
                # 亮法一并记账：规则把灯设成红色/色温后，面板显示的才是灯真正的
                # 样子，而不是上一次面板命令留下的颜色（#27）。关灯不改亮法。
                values = light_state.status_values(status, brightness, style, count)
                self.db.update_status(**values)
                self.db.add_light_event("客厅主灯(自动化)", values["light_status"],
                                        values["light_brightness"])
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
                    target = self._fan_memory
            target = max(0, min(100, int(target)))
            # 默认规则控制自动开启权限；结合当前设备状态去重，手动改动后可恢复联动。
            with self._lock:
                dup = (self._last_cmd.get("fan") == target
                       and self.db.get_current_status().get("fan_speed") == target)
            if dup:
                return True, f"风扇已是 {target}%，重复指令跳过"
            ok, msg = self.bridge.control_fan(target)
            if ok:
                with self._lock:
                    self._last_cmd["fan"] = target
                    if target > 0:
                        self._fan_memory = target
                self.db.update_status(fan_speed=target)
                if op == "set":
                    return True, msg
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
            with AC_LOCK:
                # 空调是"合并式"状态（一帧带齐开关/模式/温度/风速）：
                # 规则只给要改的项，其余按库里的当前值补齐后整帧下发。
                try:
                    target, changed = midea_ac.apply_overrides(
                        ac_state_from_db(self.db),
                        **{k: action.get(k) for k in AC_KEYS})
                except (ValueError, TypeError) as e:
                    return False, f"空调参数无效：{e}"
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
        """用轮播数据源替换 {占位符}，并裁剪成 OLED 的 16 列纯 ASCII。"""
        return self._fill_template(template, self._oled_carousel.format_text)

    def _web_format(self, template: str) -> str:
        """同一套占位符，但不做 OLED 裁剪：URL 与正文可以是中文、可以是长 JSON。"""
        return self._fill_template(template, self._oled_carousel.format_plain)

    def _fill_template(self, template: str, renderer) -> str:
        try:
            self._oled_carousel.set_data(self._oled_data())
            return renderer(str(template))
        except Exception as e:                       # noqa: BLE001
            logger.debug("[自动化] 模板格式化失败: %s", e)
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
        self._last_fire[rule["id"]] = time.monotonic()
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
