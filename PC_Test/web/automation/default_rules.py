"""内置默认规则（preset）：以前写死在 home_mode.py 里的全屋联动，现在全部
变成可在 /automation 页面查看、编辑、停用、删除的积木规则。

**阶段二语义**：全屋模式 / 人在家 / 手动优先 / 风扇安全线都不再由引擎硬编码，
而是建立在「全局状态」种子变量（见 global_state.DEFAULT_VARS）之上，由这些
预设规则自己维护。引擎只剩通用设施（事件转发、冷却、动作锁）。

注入时机：引擎启动加载规则时，若规则集里还没有 ``preset`` 标记（老版本升级）
或缺少本版本的某条预设，就把它补进去；用户删掉的预设不会被强行加回来
（用 ``presets_version`` + 规则里残留的 preset 标记判断，见 engine._seed_presets）。
用户想找回删掉的预设，可在页面点「恢复内置规则」。

每条 preset 的语义与触发时机：
    face_open_door 授权人脸通过 → 开门（原分离在 face.py 里的硬编码，本规则可停用）
    face_open_close 门禁通过 → 全屋自动 + 10 秒后自动关门
    door_in/door_out 门动作结合 g:有人在家 判定进门/出门 → 自动 / 离家
    presence_motion/presence_timeout PIR 维护 g:有人在家（1200 秒保持窗口，
        替代旧引擎的 person_present 判定）
    away_close_all g:全屋模式=离家 → 关闭全屋设备（原写死在 home_mode 的 _apply_away）
    temp_hot/temp_cool 自动模式且无人在家时按 25°C 阈值控风扇；开风扇额外要求
        g:允许自动开风扇==true（默认 false ⇒ 自动化只能关风扇，等价旧硬策略）
    light_dark/mid/off 自动模式且无人在家时按光照三档调光
    rain_window 检测到雨水关窗，雨停恢复 45°
    smoke_buzzer 检测到烟雾拉响蜂鸣器（固件侧已有 5 秒确认 + 3 次上限护栏）
    dwell_alarm 离家时有人逗留 30 秒且未通过门禁 → 蜂鸣器
    touch_to_manual/touch_to_auto 触摸键：g:全屋模式 手动↔自动 翻转
        （三值 enum 不做 toggle，避免循环踩到「离家」，所以拆成两条条件规则）
    manual_mark_*/manual_clear_* 手动优先 30 秒冷却窗口（替代旧引擎的
        within_manual_grace 仲裁，见下）
    ir_fan_toggle 遥控器 1 键风扇开/关切换（默认停用）

手动优先的实现（取代 ``home_mode.within_manual_grace``）：
    * 面板/语音每操作一个设备，引擎广播**通用事件** ``manual_control``（带
      device），``manual_mark_x`` 规则据此把 ``g:手动优先_x`` 做成一次
      「false → 3 秒 → true」脉冲并把全屋转手动；
    * ``manual_clear_x`` 规则看到 ``g:手动优先_x`` 持续为 true 满 30 秒后把它
      设回 false —— 窗口由此「每次手动操作都续期」；
    * 设备类预设都带 ``g:手动优先_x == false`` 条件，窗口内自动让位。
    脉冲为什么不写成「设 true → 等 30 秒 → 设 false」单条规则：动作锁非阻塞
    （engine._fire），上一条还在等待时新的手动事件会被整条丢弃，无法续期。
    延时取 3 秒（> A 板 2 秒快照周期）：false 必须至少被一次快照采到，
    清除规则的「持续」计时才会真正重置。

已知取舍（见 .trae/documents/全局状态积木化与全屋模式拆除方案.md）：
    「手动优先」从引擎保证降级为预设保证——用户自写规则不加该条件就不受保护；
    窗口时长由 30s 变为约 33~36s（脉冲 3s + 快照 2s 抖动）。
"""
from __future__ import annotations

# 预设版本：升级时 +1，引擎会把新版本里新增的预设补进现有规则集。
# v4：全屋模式/人在家/手动优先/风扇安全线全部改挂全局状态（g:* 变量）。
PRESETS_VERSION = 4

# ---- 常用片段（避免 10 条手动优先规则里反复手打同一个变量 id）----
_MODE = "g:全屋模式"
_PRESENT = "g:有人在家"
_FAN_OK = "g:允许自动开风扇"
_GRACE = {"door": "g:手动优先_门", "window": "g:手动优先_窗",
          "light": "g:手动优先_灯", "fan": "g:手动优先_风扇",
          "ac": "g:手动优先_空调"}
_GRACE_LABEL = {"door": "门", "window": "窗", "light": "灯",
                "fan": "风扇", "ac": "空调"}


def _set_mode(mode: str) -> dict:
    return {"device": "state", "name": _MODE, "op": "set", "value": mode}


def _not_grace(device: str) -> dict:
    """条件：该设备不在手动优先冷却窗口内（自动动作可以碰它）。"""
    return {"sensor": _GRACE[device], "op": "==", "value": False}


def _manual_priority_rules() -> list[dict]:
    """每个设备两条：手动操作后开 30 秒让位窗口（mark 脉冲 + clear 计时）。"""
    out: list[dict] = []
    for device, var in _GRACE.items():
        label = _GRACE_LABEL[device]
        out.append({
            "preset": f"manual_mark_{device}",
            "name": f"手动操作{label}：转手动 + 手动优先续期",
            "enabled": True,
            "trigger": {"kind": "event", "event": "manual_control",
                        "device": device},
            "actions": [_set_mode("manual"),
                        {"device": "state", "name": var, "op": "set",
                         "value": False},
                        {"device": "delay", "seconds": 3},
                        {"device": "state", "name": var, "op": "set",
                         "value": True}],
            "cooldown": 0,
        })
        out.append({
            "preset": f"manual_clear_{device}",
            "name": f"手动优先到期：解除{label}让位",
            "enabled": True,
            "trigger": {"kind": "sensor", "sensor": var, "op": "==",
                        "value": True, "hold_sec": 30},
            "actions": [{"device": "state", "name": var, "op": "set",
                         "value": False}],
            "cooldown": 5,
        })
    return out


DEFAULT_RULES: list[dict] = [
    {
        "preset": "face_open_door",
        "name": "授权人脸通过 → 开门",
        "enabled": True,
        # face_granted 事件由 face.py 在鉴权通过后广播；开门 DB 状态/历史由动作自行写入
        "trigger": {"kind": "event", "event": "face_granted"},
        "actions": [{"device": "door", "status": "open"}],
        "cooldown": 2,
    },
    {
        "preset": "face_open_close",
        "name": "门禁通过：全屋自动 + 10秒后关门",
        "enabled": True,
        "trigger": {"kind": "event", "event": "face_granted"},
        # 开门由上面 face_open_door 承接，这里只负责「判定进门」与延时关门；
        # 手动优先窗口内不抢用户刚设好的门状态
        "conditions": [_not_grace("door")],
        "actions": [_set_mode("auto"),
                    {"device": "delay", "seconds": 10},
                    {"device": "door", "status": "close"}],
        "cooldown": 3,
    },
    {
        "preset": "door_in",
        "name": "有人在家时开门 → 全屋自动（判定进门）",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "door_status",
                    "op": "==", "value": "open"},
        "conditions": [{"sensor": _PRESENT, "op": "==", "value": True}],
        "actions": [_set_mode("auto")],
        "cooldown": 3,
    },
    {
        "preset": "door_out",
        "name": "无人在家时开门 → 离家（判定出门）",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "door_status",
                    "op": "==", "value": "open"},
        "conditions": [{"sensor": _PRESENT, "op": "==", "value": False}],
        "actions": [_set_mode("away")],
        "cooldown": 3,
    },
    {
        "preset": "presence_motion",
        "name": "PIR 检测到人 → 有人在家",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "motion", "op": "==",
                    "value": True},
        "actions": [{"device": "state", "name": _PRESENT, "op": "set",
                     "value": True}],
        "cooldown": 1,
    },
    {
        "preset": "presence_timeout",
        "name": "PIR 连续 20 分钟无移动 → 判定无人（保持窗口）",
        "enabled": True,
        # PIR 只测得到「有动作」，静坐会漏检，所以用 1200 秒保持窗口而非瞬时值；
        # 「持续」计时跟随 A 板快照节奏，误差 ≤ 快照周期
        "trigger": {"kind": "sensor", "sensor": "motion", "op": "==",
                    "value": False, "hold_sec": 1200},
        "actions": [{"device": "state", "name": _PRESENT, "op": "set",
                     "value": False}],
        "cooldown": 5,
    },
    {
        "preset": "temp_hot",
        "name": "自动模式·无人·允许自动开：温度高于25°C开风扇",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "temperature",
                    "op": ">", "value": 25},
        # g:允许自动开风扇 默认 false ⇒ 本条永远不成立 —— 等价旧引擎的
        # auto_apply_fan 硬拦截（风扇只能手动开）；改这条状态定义的「当前值」即放开
        "conditions": [{"sensor": _MODE, "op": "==", "value": "auto"},
                       {"sensor": _PRESENT, "op": "==", "value": False},
                       {"sensor": _FAN_OK, "op": "==", "value": True},
                       _not_grace("fan")],
        "actions": [{"device": "fan", "speed": 100}],
        "cooldown": 5,
    },
    {
        "preset": "temp_cool",
        "name": "自动模式·无人在家：温度不高于25°C关风扇",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "temperature",
                    "op": "<=", "value": 25},
        # 关风扇不受「允许自动开风扇」限制：安全线只拦开、不拦关
        "conditions": [{"sensor": _MODE, "op": "==", "value": "auto"},
                       {"sensor": _PRESENT, "op": "==", "value": False},
                       _not_grace("fan")],
        "actions": [{"device": "fan", "speed": 0}],
        "cooldown": 5,
    },
    {
        "preset": "light_dark",
        "name": "自动模式·无人在家：光照偏暗(≤200)灯全亮",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "light", "op": "<=", "value": 200},
        "conditions": [{"sensor": _MODE, "op": "==", "value": "auto"},
                       {"sensor": _PRESENT, "op": "==", "value": False},
                       _not_grace("light")],
        "actions": [{"device": "light", "status": "on", "brightness": 100}],
        "cooldown": 5,
    },
    {
        "preset": "light_mid",
        "name": "自动模式·无人在家：光照中等(200~500)灯半亮",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "light", "op": ">", "value": 200},
        "conditions": [{"sensor": _MODE, "op": "==", "value": "auto"},
                       {"sensor": _PRESENT, "op": "==", "value": False},
                       {"sensor": "light", "op": "<=", "value": 500},
                       _not_grace("light")],
        "actions": [{"device": "light", "status": "on", "brightness": 50}],
        "cooldown": 5,
    },
    {
        "preset": "light_off",
        "name": "自动模式·无人在家：光照充足(>500)关灯",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "light", "op": ">", "value": 500},
        "conditions": [{"sensor": _MODE, "op": "==", "value": "auto"},
                       {"sensor": _PRESENT, "op": "==", "value": False},
                       _not_grace("light")],
        "actions": [{"device": "light", "status": "off", "brightness": 0}],
        "cooldown": 5,
    },
    {
        "preset": "rain_window",
        "name": "检测到雨水关窗，雨停恢复45°",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "rain", "op": "==", "value": True},
        "conditions": [_not_grace("window")],
        "actions": [{"device": "window", "status": "close"}],
        # 触发条件由真变假（雨停）时执行否则分支 → 恢复半开
        "else_actions": [{"device": "window", "status": "normal"}],
        "cooldown": 3,
    },
    {
        "preset": "smoke_buzzer",
        "name": "检测到烟雾：蜂鸣器报警",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "smoke", "op": "==", "value": True},
        "actions": [{"device": "buzzer", "count": 5, "on_ms": 400, "off_ms": 200}],
        "cooldown": 30,
    },
    {
        "preset": "dwell_alarm",
        "name": "离家时有人逗留30秒未通过门禁 → 蜂鸣器",
        "enabled": True,
        # 持续 30 秒才触发；门禁通过会由 face 规则把 g:全屋模式 切成自动，条件不成立即取消
        "trigger": {"kind": "sensor", "sensor": "motion", "op": "==",
                    "value": True, "hold_sec": 30},
        "conditions": [{"sensor": _MODE, "op": "==", "value": "away"}],
        "actions": [{"device": "buzzer", "count": 3, "on_ms": 300, "off_ms": 200}],
        "cooldown": 60,
    },
    {
        "preset": "touch_to_manual",
        "name": "触摸键：非手动 → 手动",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "touch", "op": "==", "value": True},
        "conditions": [{"sensor": _MODE, "op": "!=", "value": "manual"}],
        "actions": [_set_mode("manual")],
        "cooldown": 2,
    },
    {
        "preset": "touch_to_auto",
        "name": "触摸键：手动 → 自动",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "touch", "op": "==", "value": True},
        "conditions": [{"sensor": _MODE, "op": "==", "value": "manual"}],
        "actions": [_set_mode("auto")],
        "cooldown": 2,
    },
    {
        "preset": "ir_fan_toggle",
        "name": "红外键1：风扇开/关切换（按一次开、再按关）【默认停用】",
        "enabled": False,
        "trigger": {"kind": "event", "event": "ir", "command": "0x45"},
        # 风扇状态机 toggle：当前关→以 60% 开启；当前开→关闭（事件重放已去重，
        # 同一物理按键不会连发开关）。遥控器是显式人工操作，不带手动优先条件。
        "actions": [{"device": "fan", "op": "toggle", "speed": 60}],
        "cooldown": 2,
    },
    {
        "preset": "away_close_all",
        "name": "切到离家：关闭全屋设备（灯/风扇/窗）",
        "enabled": True,
        # 原写死在 home_mode._apply_away 的「离家关全屋」，现为可编辑积木。
        # 离家是显式意图，不受手动优先窗口拦截（窗口只保「不被自动改回去」，
        # 而这里的目标恰恰就是全关）。
        "trigger": {"kind": "sensor", "sensor": _MODE, "op": "==",
                    "value": "away"},
        "actions": [{"device": "light", "status": "off", "brightness": 0},
                    {"device": "fan", "speed": 0},
                    {"device": "window", "status": "close"}],
        "cooldown": 1,
    },
]

# 追加 10 条「手动优先」规则（5 设备 × mark/clear）
DEFAULT_RULES.extend(_manual_priority_rules())
