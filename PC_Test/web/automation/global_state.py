"""全局状态（自由命名变量）：引擎级的键值状态，供积木规则读写。

**职责边界**：本模块只负责「一组带类型的命名状态」的存取与持久化，不含任何
联动策略——策略全是积木规则（见 default_rules.py）。设计要点：

1. **key 带前缀**：每个变量的 id 是 ``"g:" + 名字``，持久化时就带前缀。这样
   ``engine._context()`` 直接 ``ctx.update(store.values())`` 即可，冒号前缀天然
   避开 ``CONDITION_SOURCES`` 里的所有既有 id，规则侧不需要任何拆前缀逻辑。
2. **类型化**：bool / number / enum / text 四种。值在写入时按类型强校验并归一化
   （``set_value`` 返回 ``(ok, 值或原因)``），杜绝「字符串 'false' 当真值」这类坑。
3. **统一锁 + 原子写**：所有可变状态读写都持 ``self._lock``；落盘走
   ``.json.tmp → replace`` 三段式（与 home_mode._save 同构）。
4. **写放大抑制**：值未变化时**直接返回、不落盘也不改元数据**。规则反复把某个
   状态设成同一个值是最常见的写来源（例如「检测到人 → 有人在家=是」每 2 秒一次），
   不抑制会把 disk 写穿。

**生产约定**：单进程文件存储，与 ``automation_rules.json`` 完全同构（Flask 写、
引擎读，同一进程）。若将来 web 起多 worker，需迁到 SQLite。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ID_PREFIX = "g:"
MAX_VARS = 40
TEXT_MAX = 100
VARS_VERSION = 2

# 名字：1~24 字符，不含空白与冒号（冒号是 id 前缀的分隔符）
NAME_RE = re.compile(r"^[^\s:：]{1,24}$")
ID_RE = re.compile(r"^g:[^\s:：]{1,24}$")

TYPES = ("bool", "number", "enum", "text")
TYPE_LABELS = {"bool": "是/否", "number": "数字", "enum": "选项", "text": "文本"}

# 种子变量：原「全屋模式」硬编码状态的积木化等价物（见 default_rules.py 的预设）。
# 初值沿用旧引擎语义：全屋=自动；有人在家=**true**（无 PIR 数据时的安全默认，
# 与 home_mode.person_present 一致）；允许自动开风扇=true；
# 手动优先_*=false（不在冷却窗口）。用户可以自由改名/删除，删了不会被强行加回。
DEFAULT_VARS: list[dict] = [
    {"name": "全屋模式", "type": "enum", "value": "auto",
     "choices": ["auto", "manual", "away"],
     "choice_labels": {"auto": "自动", "manual": "手动", "away": "离家"}},
    {"name": "有人在家", "type": "bool", "value": True},
    {"name": "允许自动开风扇", "type": "bool", "value": True},
    {"name": "手动优先_门", "type": "bool", "value": False},
    {"name": "手动优先_窗", "type": "bool", "value": False},
    {"name": "手动优先_灯", "type": "bool", "value": False},
    {"name": "手动优先_风扇", "type": "bool", "value": False},
    {"name": "手动优先_空调", "type": "bool", "value": False},
]


def is_var_id(value: Any) -> bool:
    """是否为合法全局状态 id（``g:<名字>``）。schema 与能力清单共用。"""
    return bool(ID_RE.match(str(value or "")))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class GlobalStateStore:
    """全局状态存储。线程安全（RLock 保护全部可变状态）。"""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.vars: list[dict] = []
        self._version = 0
        self._load()

    # ==================== 持久化 ====================

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                items = data.get("vars") if isinstance(data, dict) else data
                self._version = int((data or {}).get("version") or 0) \
                    if isinstance(data, dict) else 0
                for item in (items or []):
                    var = self._normalize(item)
                    if var:
                        self.vars.append(var)
        except Exception as e:                       # noqa: BLE001
            logger.error("[全局状态] 读取失败，按空状态启动: %s", e)
            self.vars = []

    @staticmethod
    def _normalize(item: Any) -> Optional[dict]:
        """把磁盘/入参里的一条变量规整成合法定义；不合法返回 None（跳过而非崩溃）。"""
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or "").strip()
        if not name:
            var_id = str(item.get("id") or "")
            name = var_id[len(ID_PREFIX):] if var_id.startswith(ID_PREFIX) else ""
        if not NAME_RE.match(name):
            return None
        type_ = str(item.get("type") or "bool")
        if type_ not in TYPES:
            type_ = "bool"
        var: dict = {
            "id": ID_PREFIX + name,
            "name": name,
            "label": str(item.get("label") or name),
            "type": type_,
            "value": item.get("value"),
            "updated_at": str(item.get("updated_at") or ""),
            "source": str(item.get("source") or ""),
        }
        if type_ == "enum":
            choices = [str(c) for c in (item.get("choices") or []) if str(c) != ""]
            if not choices:
                choices = ["yes", "no"]
            var["choices"] = choices
            labels = item.get("choice_labels")
            var["choice_labels"] = (
                {str(k): str(v) for k, v in labels.items()}
                if isinstance(labels, dict) else {c: c for c in choices})
        if type_ == "number":
            for key in ("min", "max"):
                raw = item.get(key)
                if raw not in (None, ""):
                    try:
                        var[key] = float(raw)
                    except (TypeError, ValueError):
                        pass
            if "unit" in item and item.get("unit"):
                var["unit"] = str(item["unit"])
        # 初值按类型归一；非法则回落类型默认值
        ok, value = GlobalStateStore._coerce(var, var.get("value"))
        if not ok:
            value = _default_value(type_, var)
        var["value"] = value
        return var

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(
                {"version": VARS_VERSION, "vars": self.vars},
                ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            self._version = VARS_VERSION
        except Exception as e:                       # noqa: BLE001
            logger.debug("[全局状态] 保存失败: %s", e)

    # ==================== 读 ====================

    def definitions(self) -> list[dict]:
        """全部变量定义（状态条目卡片渲染 + 能力清单导出用），深拷贝防止外部改坏内部状态。"""
        with self._lock:
            return [dict(v) for v in self.vars]

    def values(self) -> dict:
        """``{"g:名字": 值}``，供 ``engine._context()`` 直接 update。"""
        with self._lock:
            return {v["id"]: v["value"] for v in self.vars}

    def var_specs(self) -> dict:
        """``{"g:名字": {"type", "label", "choices"}}``，供 API 侧严格校验规则。

        校验层要按变量类型约束比较符与取值（enum 必须落在 choices 内），
        所以这里一次给全，避免校验层再读第二份变量定义。
        """
        with self._lock:
            return {v["id"]: {"type": v["type"],
                              "label": v.get("label") or v["id"],
                              "choices": list(v.get("choices") or [])}
                    for v in self.vars}

    def get(self, var_id: str) -> Optional[dict]:
        with self._lock:
            var = self._find(var_id)
            return dict(var) if var else None

    def _find(self, var_id: str) -> Optional[dict]:
        """按 id 或名字查找（名字无前缀时自动补），调用方需持锁。"""
        key = str(var_id or "").strip()
        if not key:
            return None
        if not key.startswith(ID_PREFIX):
            key = ID_PREFIX + key
        for var in self.vars:
            if var["id"] == key:
                return var
        return None

    # ==================== 变更（页面侧：状态定义积木 / 手动写值） ====================

    def create(self, name: str, type_: str = "bool", *,
               label: Optional[str] = None, value: Any = None,
               choices: Optional[list] = None,
               choice_labels: Optional[dict] = None,
               unit: Optional[str] = None,
               min: Any = None, max: Any = None,
               source: str = "页面") -> tuple[bool, Any]:
        """新建变量。返回 ``(ok, 定义或原因)``。"""
        name = str(name or "").strip()
        if not NAME_RE.match(name):
            return False, "名字需为 1~24 个字符，且不含空格与冒号"
        if type_ not in TYPES:
            return False, f"类型只能是 {'/'.join(TYPES)}"
        with self._lock:
            if self._find(name) is not None:
                return False, f"已存在同名状态「{name}」"
            if len(self.vars) >= MAX_VARS:
                return False, f"最多 {MAX_VARS} 个全局状态"
            var = self._normalize({
                "name": name, "label": label or name, "type": type_,
                "value": value if value is not None else _default_value(type_, {
                    "choices": choices}),
                "choices": choices, "choice_labels": choice_labels,
                "unit": unit, "min": min, "max": max,
                "updated_at": _now(), "source": source})
            if var is None:
                return False, "变量定义不合法"
            self.vars.append(var)
            self._save()
            logger.info("[全局状态] 新建 %s（%s）= %r", var["id"], var["type"],
                        var["value"])
            return True, dict(var)

    def update(self, var_id: str, *, label: Optional[str] = None,
               choices: Optional[list] = None,
               choice_labels: Optional[dict] = None,
               unit: Optional[str] = None,
               min: Any = None, max: Any = None,
               source: str = "页面") -> tuple[bool, Any]:
        """改元数据（标签/选项/量程）。改选项后当前值不在新集合里会被重置。"""
        with self._lock:
            var = self._find(var_id)
            if var is None:
                return False, f"全局状态「{var_id}」不存在"
            if label:
                var["label"] = str(label)
            if var["type"] == "enum" and choices:
                new_choices = [str(c) for c in choices if str(c) != ""]
                if not new_choices:
                    return False, "选项不能为空"
                var["choices"] = new_choices
                if isinstance(choice_labels, dict):
                    var["choice_labels"] = {str(k): str(v)
                                            for k, v in choice_labels.items()}
                    for c in new_choices:
                        var["choice_labels"].setdefault(c, c)
                if var["value"] not in new_choices:
                    var["value"] = new_choices[0]
                    var["source"] = "选项变更重置"
                    var["updated_at"] = _now()
            if var["type"] == "number":
                for key, raw in (("min", min), ("max", max), ("unit", unit)):
                    if raw in (None, ""):
                        var.pop(key, None)
                    else:
                        var[key] = float(raw) if key in ("min", "max") else str(raw)
                ok, value = self._coerce(var, var["value"])
                if ok and value != var["value"]:
                    var["value"] = value
            var["updated_at"] = _now()
            var["source"] = source
            self._save()
            return True, dict(var)

    def rename(self, var_id: str, new_name: str,
               source: str = "页面") -> tuple[bool, Any]:
        """改名。id 随名字变（前缀 + 名字），调用方负责同步已保存规则里的引用。"""
        new_name = str(new_name or "").strip()
        if not NAME_RE.match(new_name):
            return False, "名字需为 1~24 个字符，且不含空格与冒号"
        with self._lock:
            var = self._find(var_id)
            if var is None:
                return False, f"全局状态「{var_id}」不存在"
            other = self._find(new_name)
            if other is not None and other is not var:
                return False, f"已存在同名状态「{new_name}」"
            old_id = var["id"]
            var["name"] = new_name
            var["id"] = ID_PREFIX + new_name
            var["updated_at"] = _now()
            var["source"] = source
            self._save()
            return True, {"old_id": old_id, "var": dict(var)}

    def delete(self, var_id: str) -> tuple[bool, Any]:
        with self._lock:
            var = self._find(var_id)
            if var is None:
                return False, f"全局状态「{var_id}」不存在"
            self.vars.remove(var)
            self._save()
            logger.info("[全局状态] 删除 %s", var["id"])
            return True, dict(var)

    # ==================== 写值（规则动作入口） ====================

    def set_value(self, var_id: str, value: Any,
                  source: str = "规则") -> tuple[bool, Any]:
        """按类型强校验后写值。返回 ``(ok, 值或原因)``。

        值未变化时**不落盘、不改元数据**（写放大抑制，见模块 docstring）。
        """
        with self._lock:
            var = self._find(var_id)
            if var is None:
                return False, f"全局状态「{var_id}」不存在"
            ok, result = self._coerce(var, value)
            if not ok:
                return False, result
            if var["value"] == result:
                return True, result
            var["value"] = result
            var["updated_at"] = _now()
            var["source"] = source
            self._save()
            return True, result

    def toggle(self, var_id: str, source: str = "规则") -> tuple[bool, Any]:
        """翻转：bool 取反；两项 enum 在两项间切换。其余类型拒绝。"""
        with self._lock:
            var = self._find(var_id)
            if var is None:
                return False, f"全局状态「{var_id}」不存在"
            if var["type"] == "bool":
                return self.set_value(var_id, not bool(var["value"]), source)
            choices = var.get("choices") or []
            if var["type"] == "enum" and len(choices) == 2:
                nxt = choices[1] if var["value"] == choices[0] else choices[0]
                return self.set_value(var_id, nxt, source)
            return False, "只有「是/否」状态或两项选项状态可以切换"

    def add(self, var_id: str, delta: Any = 1,
            source: str = "规则") -> tuple[bool, Any]:
        """数字累加（delta 可为负）。非数字类型拒绝。"""
        with self._lock:
            var = self._find(var_id)
            if var is None:
                return False, f"全局状态「{var_id}」不存在"
            if var["type"] != "number":
                return False, "只有数字状态可以加减"
            try:
                step = float(delta)
            except (TypeError, ValueError):
                return False, "加/减的量必须是数字"
            return self.set_value(var_id, float(var["value"] or 0) + step, source)

    # ==================== 类型校验 ====================

    @staticmethod
    def _coerce(var: dict, value: Any) -> tuple[bool, Any]:
        """按变量类型强校验并归一化值。返回 ``(ok, 值或原因)``。"""
        if value is None:
            return False, "值不能为空"
        type_ = var.get("type")
        if type_ == "bool":
            if isinstance(value, bool):
                return True, value
            if isinstance(value, (int, float)) and value in (0, 1):
                return True, bool(value)
            text = str(value).strip().lower()
            if text in ("true", "1", "yes", "on", "是", "开"):
                return True, True
            if text in ("false", "0", "no", "off", "否", "关"):
                return True, False
            return False, "「是/否」状态只接受 是/否（true/false）"
        if type_ == "number":
            if isinstance(value, bool):
                return False, "数字状态不接受 true/false"
            try:
                num = float(value)
            except (TypeError, ValueError):
                return False, "数字状态需要数字"
            lo, hi = var.get("min"), var.get("max")
            if lo is not None:
                num = max(float(lo), num)
            if hi is not None:
                num = min(float(hi), num)
            return True, int(num) if num == int(num) else num
        if type_ == "enum":
            text = str(value)
            choices = var.get("choices") or []
            if text not in choices:
                return False, f"值必须是 {'/'.join(choices)} 之一"
            return True, text
        # text
        text = str(value).strip()
        if len(text) > TEXT_MAX:
            return False, f"文本最长 {TEXT_MAX} 字"
        return True, text

    # ==================== 种子变量 ====================

    def seed_defaults(self) -> int:
        """补内置种子变量，返回新增条数。

        - 文件缺失或版本落后 → 补；
        - 用户删掉的**不会**被强行加回来（按名字判存在）；
        - DEFAULT_VARS 为空时什么都不做。
        """
        if not DEFAULT_VARS or self._version >= VARS_VERSION:
            return 0
        added = 0
        with self._lock:
            have = {v["name"] for v in self.vars}
            for spec in DEFAULT_VARS:
                if spec.get("name") in have:
                    continue
                kw = dict(spec)
                kw.pop("type", None)
                ok, _ = self.create(type_=spec.get("type", "bool"),
                                    source="种子默认", **kw)
                if ok:
                    added += 1
            if not self.vars:
                self._save()          # 空状态也落一次盘，记住 version
            else:
                self._version = VARS_VERSION
                self._save()
        if added:
            logger.info("[全局状态] 已注入种子变量 %d 个", added)
        return added


def _default_value(type_: str, var: dict) -> Any:
    if type_ == "bool":
        return False
    if type_ == "number":
        return 0
    if type_ == "enum":
        return (var.get("choices") or ["yes"])[0]
    return ""
