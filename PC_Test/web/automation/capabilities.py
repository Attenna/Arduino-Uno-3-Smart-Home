"""积木下拉框的「能力清单」：可用传感器/状态、事件、比较符、执行器。

前端 Blockly 工具箱与后端校验共用同一份元数据（GET /api/automation/capabilities）。
只列**真实存在**的能力，避免出现"能选但永远不成立 / 选了没反应"的假能力。

V2.1 固件已裁剪的能力（故意不列）：
  - 超声波 distance、土壤 soil_moisture/soil_dry —— Module A 编译期关闭；
  - 数码管 display(TM1637) —— Module B 编译期关闭，硬件不存在；
  - buzzer_status(raw) / fan_level / light_level(raw 0-255) —— 旧 B 板 state 帧的
    原始电平，V2.1 裁剪后写入方 database.ingest_output() 已删除，永远为 NULL，
    不能作为条件源（执行器真值改用 P1 的 rb_* 回读列）；
  - face_denied —— 人脸拒绝时只写库不广播事件，不是真实事件。

V2.1 已移除的遗留设备：空调（虚拟设备，无任何真实执行器接线），已在数据库/API/前端全局删除。
"""
from __future__ import annotations

# 全屋模式的档位标签与「能力清单」共用同一份定义，避免两处文案漂移
# （home_mode 不反向依赖本模块，无循环导入）
from .home_mode import FAN_LABELS, LIGHT_LABELS, MODE_LABELS

# 比较符（积木下拉）
COMPARATORS = [
    {"id": ">", "label": "大于"},
    {"id": ">=", "label": "大于等于"},
    {"id": "<", "label": "小于"},
    {"id": "<=", "label": "小于等于"},
    {"id": "==", "label": "等于"},
    {"id": "!=", "label": "不等于"},
]

# 「全屋风扇档位」在 JSON 里用 auto/on/off 表示（None 是配置里的内部值，归一成 auto）
_HOME_FAN_CHOICES = ["auto", "on", "off"]
_HOME_FAN_LABELS = {"auto": FAN_LABELS[None], "on": FAN_LABELS["on"], "off": FAN_LABELS["off"]}

# 可作为「触发/条件」的数据源：id 即规则 JSON 里的 sensor 字段
# kind: number=数值比较；bool=与 true/false 比较；enum=与给定字符串比较
CONDITION_SOURCES = {
    # ── Module A 周期上报的传感器 ──
    "temperature": {"label": "温度", "kind": "number", "unit": "°C"},
    "humidity": {"label": "湿度", "kind": "number", "unit": "%"},
    "light": {"label": "光照", "kind": "number", "unit": "0-1023"},
    "smoke": {"label": "烟雾报警", "kind": "bool"},
    "rain": {"label": "雨水检测", "kind": "bool"},
    "touch": {"label": "触摸传感器", "kind": "bool"},
    "motion": {"label": "人体红外", "kind": "bool"},
    # ── 执行器当前状态（来自 SQLite，由面板控制 / 规则动作 / 全屋模式写入）──
    "door_status": {"label": "门状态", "kind": "enum",
                    "choices": ["open", "closed"],
                    "choice_labels": {"open": "开", "closed": "关"}},
    "window_status": {"label": "窗户状态", "kind": "enum",
                      "choices": ["open", "closed", "normal"],
                      "choice_labels": {"open": "全开", "closed": "关", "normal": "半开45°"}},
    "light_status": {"label": "灯状态", "kind": "enum",
                     "choices": ["on", "off"],
                     "choice_labels": {"on": "开", "off": "关"}},
    "light_brightness": {"label": "灯亮度", "kind": "number", "unit": "%"},
    "fan_speed": {"label": "风扇转速", "kind": "number", "unit": "%"},
    # ── 空调设定（美的红外遥控，由面板/语音/规则下发后写库）──
    "ac_status": {"label": "空调开关", "kind": "enum",
                  "choices": ["on", "off"],
                  "choice_labels": {"on": "开", "off": "关"}},
    "ac_mode": {"label": "空调模式", "kind": "enum",
                "choices": ["auto", "cool", "heat", "dry", "fan"],
                "choice_labels": {"auto": "自动", "cool": "制冷", "heat": "制热",
                                  "dry": "抽湿", "fan": "送风"}},
    "ac_temperature": {"label": "空调设定温度", "kind": "number", "unit": "℃"},
    # ── 全屋状态（状态机）──
    "home_mode": {"label": "全屋模式", "kind": "enum",
                  "choices": list(MODE_LABELS.keys()),
                  "choice_labels": dict(MODE_LABELS)},
    "home_enabled": {"label": "全屋自动调节已启用", "kind": "bool"},
    "home_fan": {"label": "全屋风扇档位", "kind": "enum",
                 "choices": list(_HOME_FAN_CHOICES),
                 "choice_labels": dict(_HOME_FAN_LABELS)},
    "home_light": {"label": "全屋灯光档位", "kind": "enum",
                   "choices": list(LIGHT_LABELS.keys()),
                   "choice_labels": dict(LIGHT_LABELS)},
    "person_present": {"label": "判定有人在家", "kind": "bool"},
    # ── 硬件在线健康位（15 秒心跳判定）──
    "sensor_online": {"label": "传感器板在线", "kind": "bool"},
    "output_online": {"label": "执行器板在线", "kind": "bool"},
}

# ---- 遥控器/键盘键位表（用户可选的「按键」清单）----
# 红外遥控：NEC，ADDRESS 0x00，Module A D3 实测键码（21 键小遥控，与通用 NEC 键表一致）
IR_KEYS = [
    ("0x45", "1"), ("0x46", "2"), ("0x47", "3"), ("0x44", "4"), ("0x40", "5"),
    ("0x43", "6"), ("0x07", "7"), ("0x15", "8"), ("0x09", "9"), ("0x19", "0"),
    ("0x16", "*"), ("0x0D", "#"),
    ("0x18", "上"), ("0x52", "下"), ("0x08", "左"), ("0x5A", "右"), ("0x1C", "OK"),
]
# 矩阵键盘（A 板 D4 第一横列 / A4 第一纵列）：4x4 键盘实际只用到 0-9 与 * / #
KEYPAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "*", "#"]

# 事件触发块。choices 供前端下拉（按键类事件让用户直接选键名，无需手填十六进制码）
#
# ！！每条都必须带 payload，且 payload 里必须含 "event" 键 ！！
# engine._evaluate_event_rule 用 EVENT_TRIGGERS[x]["payload"] 对事件做全等匹配；
# 若某条没有 payload（或没写 "event"），就会变成「任意事件都能触发它」。
EVENT_TRIGGERS = {
    # Module A 事件：state 由 Pi 上的 Protocol.cpp 归一化成 bool
    "touch_on": {"label": "触摸：按下", "payload": {"event": "touch", "state": True}},
    "touch_off": {"label": "触摸：松开", "payload": {"event": "touch", "state": False}},
    "smoke_on": {"label": "烟雾：报警", "payload": {"event": "smoke", "state": True}},
    "smoke_off": {"label": "烟雾：解除", "payload": {"event": "smoke", "state": False}},
    "rain_on": {"label": "雨水：检测到下雨", "payload": {"event": "rain", "state": True}},
    "rain_off": {"label": "雨水：雨停", "payload": {"event": "rain", "state": False}},
    "motion_on": {"label": "人体红外：检测到移动", "payload": {"event": "motion", "state": True}},
    "motion_off": {"label": "人体红外：移动结束", "payload": {"event": "motion", "state": False}},
    # RFID 刷卡事件：uid 是可选的过滤参数（不填=任意卡片都触发）
    "rfid": {"label": "RFID：刷到卡片", "param": "uid", "param_label": "卡号",
             "payload": {"event": "rfid"}},
    # 人脸授权（由 web 侧广播，非 A 板固件）
    "face_granted": {"label": "人脸识别：授权人员通过",
                     "payload": {"event": "face", "status": "granted"}},
    "keypad": {"label": "矩阵键盘：按下指定键", "param": "key", "param_label": "按键",
               "default": "1",
               "choices": [{"id": k, "label": k} for k in KEYPAD_KEYS],
               "payload": {"event": "keypad"}},
    "ir": {"label": "红外遥控：按下指定按键", "param": "command", "param_label": "按键",
           "default": "0x45",
           "choices": [{"id": code, "label": f"{name}（{code}）"} for code, name in IR_KEYS],
           "payload": {"event": "ir"}},
}

# 执行器动作块
ACTION_DEVICES = {
    "door": {"label": "门", "params": {"status": {"choices": ["open", "close"],
                                                  "labels": ["打开", "关闭"]}}},
    "window": {"label": "窗户", "params": {"status": {"choices": ["open", "close", "normal"],
                                                      "labels": ["打开", "关闭", "半开45°"]}}},
    "light": {"label": "灯", "params": {
        "status": {"choices": ["on", "off"], "labels": ["打开", "关闭"]},
        "brightness": {"range": [0, 100], "unit": "%"},
        # B 板是 8 颗 WS2812 可寻址灯珠，整条同色；只有 white 接受亮度(value 0-255)，
        # 彩色预设与 rgb 不接受亮度参数
        "color": {"choices": ["white", "red", "green", "blue", "yellow", "purple", "cyan", "rgb"],
                  "labels": ["白光(可用亮度)", "红", "绿", "蓝", "黄", "紫", "青", "RGB(需 r,g,b)"]},
        "value": {"range": [0, 255], "unit": "白光亮度"},
        "r": {"range": [0, 255]}, "g": {"range": [0, 255]}, "b": {"range": [0, 255]}}},
    "fan": {"label": "风扇", "params": {
        "op": {"choices": ["set", "on", "off", "toggle"],
               "labels": ["设置转速", "开启", "关闭", "切换开/关（同一键再按一次反转）"]},
        "speed": {"range": [0, 100], "unit": "%", "label": "转速（开启/切换为开时使用）"}}},
    "buzzer": {"label": "蜂鸣器", "params": {
        "mode": {"choices": ["beep", "on", "off"], "labels": ["间歇响", "持续响", "停"]},
        "count": {"range": [1, 10], "label": "次数"},
        "on_ms": {"range": [50, 2000], "unit": "ms"},
        "off_ms": {"range": [50, 2000], "unit": "ms"}}},
    "oled": {"label": "OLED 屏", "params": {
        "text": {"label": "文本（可含 {temperature} 等占位符）", "maxlen": 200},
        "line": {"range": [0, 7], "label": "指定行（不填=按换行自动分配）"},
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
                        "labels": ["不改", "自动", "保持当前", "暗", "半亮", "全亮", "循环下一档"]},
        # 状态机自身参数（原先只能在代码里改）
        "enabled": {"type": "bool", "label": "全屋自动调节总开关"},
        "presence_hold_sec": {"range": [0, 86400], "unit": "秒", "label": "存在判定保持时长"},
        "manual_grace_s": {"range": [1, 3600], "unit": "秒", "label": "手动冷却窗口"}}},
    "delay": {"label": "等待（延时）", "params": {"seconds": {"range": [1, 300], "unit": "秒"}}},
    # 语音助手联动：免唤醒词激活 / 直接下发一句文本指令
    "voice": {"label": "语音助手", "params": {
        "action": {"choices": ["wake", "say"], "labels": ["唤醒（跳过唤醒词）", "播报/执行文本"]},
        "text": {"label": "文本（action=播报时必填）", "maxlen": 200}}},
    # 红外发射（B 板 D12，NEC 38kHz）。code 为十进制 32 位码；
    # 也可给 address+command，由 hardware.py 的 helper 换算（NEC 约定见该处注释）。
    # 注意：本系统不支持红外自学习/回环转发，B 板发出的码会被 A 板接收头收到，
    # 引擎有「自发射回声抑制」兜底，但同码的收发规则仍应避免同时存在。
    "ir": {"label": "红外发射", "params": {
        "code": {"range": [0, 4294967295], "label": "NEC 码（十进制 32 位）"},
        "address": {"range": [0, 255], "label": "NEC 地址（与 command 配合，可替代 code）"},
        "command": {"range": [0, 255], "label": "NEC 命令"}}},
    # 美的空调（RN02G(X) 红外状态帧）。留空的项表示"不改"，与 midea_ac.apply_overrides 一致。
    # 注意：改模式/温度/风速会连带把空调开机（状态帧自带开机效果）。
    "ac": {"label": "空调（美的红外）", "params": {
        "power": {"type": "bool", "label": "开关机"},
        "mode": {"choices": ["", "auto", "cool", "heat", "dry", "fan"],
                 "labels": ["不改", "自动", "制冷", "制热", "抽湿", "送风"]},
        "temperature": {"range": [17, 30], "label": "温度（℃ 整数）"},
        "fan": {"choices": ["", "auto", "low", "mid", "high"],
                "labels": ["不改", "自动", "低", "中", "高"]},
        "swing_ud": {"type": "bool", "label": "上下扫风"},
        "swing_lr": {"type": "bool", "label": "左右扫风"}}},
}


def capabilities_payload() -> dict:
    return {
        "comparators": COMPARATORS,
        "sources": [{"id": k, **v} for k, v in CONDITION_SOURCES.items()],
        "events": [{"id": k, **v} for k, v in EVENT_TRIGGERS.items()],
        "devices": [{"id": k, **v} for k, v in ACTION_DEVICES.items()],
    }