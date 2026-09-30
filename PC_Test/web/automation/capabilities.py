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
                      "choices": ["open", "closed"],
                      "choice_labels": {"open": "开", "closed": "关"}},
    "light_status": {"label": "灯状态", "kind": "enum",
                     "choices": ["on", "off"],
                     "choice_labels": {"on": "开", "off": "关"}},
    "fan_speed": {"label": "风扇转速", "kind": "number", "unit": "%"},
}

# 事件触发块
EVENT_TRIGGERS = {
    "motion_on": {"label": "人体红外：检测到移动", "payload": {"event": "motion", "state": True}},
    "motion_off": {"label": "人体红外：移动结束", "payload": {"event": "motion", "state": False}},
    "face_granted": {"label": "人脸识别：授权人员通过", "payload": {"event": "face", "status": "granted"}},
    "keypad": {"label": "矩阵键盘：按下指定键", "param": "key", "param_label": "按键", "default": "1"},
    "ir": {"label": "红外遥控：按下指定键码", "param": "command", "param_label": "命令码(十六进制)", "default": "0x45"},
}

# 执行器动作块
ACTION_DEVICES = {
    "door": {"label": "门", "params": {"status": {"choices": ["open", "close"],
                                                  "labels": ["打开", "关闭"]}}},
    "window": {"label": "窗户", "params": {"status": {"choices": ["open", "close"],
                                                      "labels": ["打开", "关闭"]}}},
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
    "delay": {"label": "等待（延时）", "params": {"seconds": {"range": [1, 300], "unit": "秒"}}},
}


def capabilities_payload() -> dict:
    return {
        "comparators": COMPARATORS,
        "sources": [{"id": k, **v} for k, v in CONDITION_SOURCES.items()],
        "events": [{"id": k, **v} for k, v in EVENT_TRIGGERS.items()],
        "devices": [{"id": k, **v} for k, v in ACTION_DEVICES.items()],
    }
