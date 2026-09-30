"""内置默认规则（preset）：以前写死在 home_mode.py 里的全屋联动，现在全部
变成可在 /automation 页面查看、编辑、停用、删除的积木规则。

注入时机：引擎启动加载规则时，若规则集里还没有 ``preset`` 标记（老版本升级）
或缺少本版本的某条预设，就把它补进去；用户删掉的预设不会被强行加回来
（用 ``presets_version`` + 规则里残留的 preset 标记判断，见 engine._seed_presets）。
用户想找回删掉的预设，可在页面点「恢复内置规则」。

每条 preset 的语义与触发时机：
    face_open_door 授权人脸通过 → 开门（原分离在 face.py 里的硬编码，本规则可停用）
    face_open_close 门禁通过 → 全屋自动 + 10 秒后自动关门
    door_in/door_out 门动作结合「人在家」判定进门/出门 → 自动 / 离家
    away_close_all 切到离家 → 关闭全屋设备（原写死在 home_mode 的 _apply_away）
    temp_hot/temp_cool 自动模式且无人在家时按 25°C 阈值控风扇
    light_dark/mid/off 自动模式且无人在家时按光照三档调光
    rain_window 检测到雨水关窗，雨停恢复 45°
    smoke_buzzer 检测到烟雾拉响蜂鸣器（固件侧已有 5 秒确认 + 3 次上限护栏）
    dwell_alarm 离家时有人逗留 30 秒且未通过门禁 → 蜂鸣器
    touch_toggle 触摸传感器：手动↔自动 翻转
    ir_* 遥控器 1/2/3 键的档位循环（默认停用，避免与用户自己的按键规则冲突）
"""
from __future__ import annotations

# 预设版本：升级时 +1，引擎会把新版本里新增的预设补进现有规则集
PRESETS_VERSION = 2

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
        # 开门由上面 face_open_door 承接，这里只负责「判定进门」与延时关门
        "actions": [{"device": "home_mode", "mode": "auto"},
                    {"device": "delay", "seconds": 10},
                    {"device": "door", "status": "close"}],
        "cooldown": 3,
    },
    {
        "preset": "door_in",
        "name": "检测到人后开门 → 全屋自动（判定进门）",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "door_status",
                    "op": "==", "value": "open"},
        "conditions": [{"sensor": "person_present", "op": "==", "value": True}],
        "actions": [{"device": "home_mode", "mode": "auto"}],
        "cooldown": 3,
    },
    {
        "preset": "door_out",
        "name": "无人在家时开门 → 离家（判定出门）",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "door_status",
                    "op": "==", "value": "open"},
        "conditions": [{"sensor": "person_present", "op": "==", "value": False}],
        "actions": [{"device": "home_mode", "mode": "away"}],
        "cooldown": 3,
    },
    {
        "preset": "temp_hot",
        "name": "自动模式·无人在家：温度高于25°C开风扇",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "temperature",
                    "op": ">", "value": 25},
        "conditions": [{"sensor": "home_mode", "op": "==", "value": "auto"},
                       {"sensor": "person_present", "op": "==", "value": False}],
        "actions": [{"device": "fan", "speed": 100}],
        "cooldown": 5,
    },
    {
        "preset": "temp_cool",
        "name": "自动模式·无人在家：温度不高于25°C关风扇",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "temperature",
                    "op": "<=", "value": 25},
        "conditions": [{"sensor": "home_mode", "op": "==", "value": "auto"},
                       {"sensor": "person_present", "op": "==", "value": False}],
        "actions": [{"device": "fan", "speed": 0}],
        "cooldown": 5,
    },
    {
        "preset": "light_dark",
        "name": "自动模式·无人在家：光照偏暗(≤200)灯全亮",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "light", "op": "<=", "value": 200},
        "conditions": [{"sensor": "home_mode", "op": "==", "value": "auto"},
                       {"sensor": "person_present", "op": "==", "value": False}],
        "actions": [{"device": "light", "status": "on", "brightness": 100}],
        "cooldown": 5,
    },
    {
        "preset": "light_mid",
        "name": "自动模式·无人在家：光照中等(200~500)灯半亮",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "light", "op": ">", "value": 200},
        "conditions": [{"sensor": "home_mode", "op": "==", "value": "auto"},
                       {"sensor": "person_present", "op": "==", "value": False},
                       {"sensor": "light", "op": "<=", "value": 500}],
        "actions": [{"device": "light", "status": "on", "brightness": 50}],
        "cooldown": 5,
    },
    {
        "preset": "light_off",
        "name": "自动模式·无人在家：光照充足(>500)关灯",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "light", "op": ">", "value": 500},
        "conditions": [{"sensor": "home_mode", "op": "==", "value": "auto"},
                       {"sensor": "person_present", "op": "==", "value": False}],
        "actions": [{"device": "light", "status": "off", "brightness": 0}],
        "cooldown": 5,
    },
    {
        "preset": "rain_window",
        "name": "检测到雨水关窗，雨停恢复45°",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "rain", "op": "==", "value": True},
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
        # 持续 30 秒才触发；门禁通过会由 face 规则把模式切成自动，条件不成立即取消
        "trigger": {"kind": "sensor", "sensor": "motion", "op": "==",
                    "value": True, "hold_sec": 30},
        "conditions": [{"sensor": "home_mode", "op": "==", "value": "away"}],
        "actions": [{"device": "buzzer", "count": 3, "on_ms": 300, "off_ms": 200}],
        "cooldown": 60,
    },
    {
        "preset": "touch_toggle",
        "name": "触摸传感器：手动↔自动 切换",
        "enabled": True,
        "trigger": {"kind": "sensor", "sensor": "touch", "op": "==", "value": True},
        "actions": [{"device": "home_mode", "mode": "toggle"}],
        "cooldown": 2,
    },
    {
        "preset": "ir_fan_cycle",
        "name": "红外键1：风扇档位循环【默认停用】",
        "enabled": False,
        "trigger": {"kind": "event", "event": "ir", "command": "0x45"},
        "actions": [{"device": "home_mode", "fan_override": "cycle"}],
        "cooldown": 2,
    },
    {
        "preset": "ir_light_cycle_2",
        "name": "红外键2：灯光档位循环【默认停用】",
        "enabled": False,
        "trigger": {"kind": "event", "event": "ir", "command": "0x46"},
        "actions": [{"device": "home_mode", "light_level": "cycle"}],
        "cooldown": 2,
    },
    {
        "preset": "ir_light_cycle_3",
        "name": "红外键3：灯光档位循环【默认停用】",
        "enabled": False,
        "trigger": {"kind": "event", "event": "ir", "command": "0x47"},
        "actions": [{"device": "home_mode", "light_level": "cycle"}],
        "cooldown": 2,
    },
    {
        "preset": "away_close_all",
        "name": "切到离家：关闭全屋设备（灯/风扇/窗）",
        "enabled": True,
        # 原写死在 home_mode._apply_away 的「离家关全屋」，现为可编辑积木。
        # 触发块用 home_mode==away 状态源，切离家（含手动/规则设置）即关灯/风扇/窗。
        "trigger": {"kind": "sensor", "sensor": "home_mode", "op": "==",
                    "value": "away"},
        "actions": [{"device": "light", "status": "off", "brightness": 0},
                    {"device": "fan", "speed": 0},
                    {"device": "window", "status": "close"}],
        "cooldown": 1,
    },
]