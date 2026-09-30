"""积木下拉框的「能力清单」：可用传感器/状态、事件、比较符、执行器。

前端 Blockly 工具箱与后端校验共用同一份元数据（GET /api/automation/capabilities）。
V2.1 固件已移除超声波(distance)与土壤(soil_*)，此处不再列出。
"""
from __future__ import annotations

# 比较符（积木下拉）
COMPARATORS = [
    {"id": ">", "label": "大于"},
    {"id": ">=", "label": "大于等于"},
    {"id": "<", "label": "小于"},
    {"id": "<=", "label": "小于等于"},
    {"id": "==", "label": "等于"},
    {"id": "!=", "label": "不等于"},
]

# 可作为「触发/条件」的数据源：id 即规则 JSON 里的 sensor 字段
# kind: number=数值比较；bool=与 true/false 比较；enum=与给定字符串比较
CONDITION_SOURCES = {
    "temperature": {"label": "温度", "kind": "number", "unit": "°C"},
    "humidity": {"label": "湿度", "kind": "number", "unit": "%"},
    "light": {"label": "光照", "kind": "number", "unit": "0-1023"},
    "smoke": {"label": "烟雾报警", "kind": "bool"},
    "rain": {"label": "雨水检测", "kind": "bool"},
    "touch": {"label": "触摸传感器", "kind": "bool"},
    "motion": {"label": "人体红外", "kind": "bool"},
    "door_status": {"label": "门状态", "kind": "enum",
                    "choices": ["open", "closed"],
                    "choice_labels": {"open": "开", "closed": "关"}},
    "window_status": {"label": "窗户状态", "kind": "enum",
                      "choices": ["open", "closed", "normal"],
                      "choice_labels": {"open": "全开", "closed": "关", "normal": "半开45°"}},
    "home_mode": {"label": "全屋模式", "kind": "enum",
                  "choices": ["auto", "manual", "away"],
                  "choice_labels": {"auto": "自动", "manual": "手动", "away": "离家"}},
    "person_present": {"label": "判定有人在家", "kind": "bool"},
    "light_status": {"label": "灯状态", "kind": "enum",
                     "choices": ["on", "off"],
                     "choice_labels": {"on": "开", "off": "关"}},
    "fan_speed": {"label": "风扇转速", "kind": "number", "unit": "%"},
}

# ---- 遥控器/键盘键位表（用户可选的「按键」清单）----
# 红外遥控：NEC，ADDRESS 0x00，Module A D3 实测键码（21 键小遥控，与通用 NEC 键表一致）
IR_KEYS = [
    ("0x45", "1"), ("0x46", "2"), ("0x47", "3"), ("0x44", "4"), ("0x40", "5"),
    ("0x43", "6"), ("0x07", "7"), ("0x15", "8"), ("0x09", "9"), ("0x19", "0"),
    ("0x16", "*"), ("0x0D", "#"),
    ("0x18", "上"), ("0x52", "下"), ("0x08", "左"), ("0x5A", "右"), ("0x1C", "OK"),
]
# 矩阵键盘（D4/A4）：4x4 键盘实际只用到 0-9 与 * / #
KEYPAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "*", "#"]

# 事件触发块。choices 供前端下拉（按键类事件让用户直接选键名，无需手填十六进制码）
EVENT_TRIGGERS = {
    "motion_on": {"label": "人体红外：检测到移动", "payload": {"event": "motion", "state": True}},
    "motion_off": {"label": "人体红外：移动结束", "payload": {"event": "motion", "state": False}},
    "face_granted": {"label": "人脸识别：授权人员通过", "payload": {"event": "face", "status": "granted"}},
    "keypad": {"label": "矩阵键盘：按下指定键", "param": "key", "param_label": "按键",
               "default": "1",
               "choices": [{"id": k, "label": k} for k in KEYPAD_KEYS]},
    "ir": {"label": "红外遥控：按下指定按键", "param": "command", "param_label": "按键",
           "default": "0x45",
           "choices": [{"id": code, "label": f"{name}（{code}）"} for code, name in IR_KEYS]},
}

# 执行器动作块
ACTION_DEVICES = {
    "door": {"label": "门", "params": {"status": {"choices": ["open", "close"],
                                                  "labels": ["打开", "关闭"]}}},
    "window": {"label": "窗户", "params": {"status": {"choices": ["open", "close", "normal"],
                                                      "labels": ["打开", "关闭", "半开45°"]}}},
    "light": {"label": "灯", "params": {"status": {"choices": ["on", "off"],
                                                   "labels": ["打开", "关闭"]},
                                        "brightness": {"range": [0, 100], "unit": "%"}}},
    "fan": {"label": "风扇", "params": {"speed": {"range": [0, 100], "unit": "%"}}},
    "buzzer": {"label": "蜂鸣器", "params": {"count": {"range": [1, 10], "label": "次数"},
                                             "on_ms": {"range": [50, 2000], "unit": "ms"},
                                             "off_ms": {"range": [50, 2000], "unit": "ms"}}},
    "oled": {"label": "OLED 屏", "params": {
        "text": {"label": "文本（可含 {temperature} 等占位符）", "maxlen": 200},
        "clear": {"type": "bool", "label": "清屏"}}},
    # 全屋模式状态机：把「进门切自动 / 触摸切手动 / 档位循环」交给用户自己编排。
    # mode=toggle 为「手动↔自动」翻转（触摸键那种一键切换）；
    # fan_override/light_level 的 cycle 为档位循环，按一次换下一档。
    "home_mode": {"label": "全屋模式", "params": {
        "mode": {"choices": ["", "auto", "manual", "away", "toggle"],
                 "labels": ["不改", "自动", "手动", "离家", "手动↔自动 翻转"]},
        "fan_override": {"choices": ["", "on", "off", "auto", "cycle"],
                         "labels": ["不改", "强制开", "强制关", "回到自动", "循环下一档"]},
        "light_level": {"choices": ["", "auto", "hold", "dark", "half", "bright", "cycle"],
                        "labels": ["不改", "自动", "保持当前", "暗", "半亮", "全亮", "循环下一档"]}}},
    "delay": {"label": "等待（延时）", "params": {"seconds": {"range": [1, 300], "unit": "秒"}}},
    # 语音助手联动：免唤醒词激活 / 直接下发一句文本指令
    "voice": {"label": "语音助手", "params": {
        "action": {"choices": ["wake", "say"], "labels": ["唤醒（跳过唤醒词）", "播报/执行文本"]},
        "text": {"label": "文本（action=播报时必填）", "maxlen": 200}}},
}


def capabilities_payload() -> dict:
    return {
        "comparators": COMPARATORS,
        "sources": [{"id": k, **v} for k, v in CONDITION_SOURCES.items()],
        "events": [{"id": k, **v} for k, v in EVENT_TRIGGERS.items()],
        "devices": [{"id": k, **v} for k, v in ACTION_DEVICES.items()],
    }
