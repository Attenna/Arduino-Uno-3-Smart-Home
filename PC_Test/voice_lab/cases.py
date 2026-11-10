"""Evaluation cases shared by dataset generation and the evaluators.

Each case is a list of user turns plus the expected tool call per turn and
optional final-state assertions.  The wording deliberately includes both
explicit commands (rule fast path) and contextual/loose commands (LLM path).
"""
from __future__ import annotations

from typing import Any

CASES: list[dict[str, Any]] = [
    {
        "id": "light_blue", "intent": "control_light",
        "turns": ["把客厅的灯调成蓝色"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "set", "room": "living_room", "color": "blue"}}],
        "expect_state": [["light.living_room.on", True],
                         ["light.living_room.color", "blue"]],
        "keywords": ["客厅", "蓝色"],
    },
    {
        "id": "light_on_bedroom", "intent": "control_light",
        "turns": ["打开卧室的灯"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "on", "room": "bedroom"}}],
        "expect_state": [["light.bedroom.on", True]],
        "keywords": ["卧室", "灯"],
    },
    {
        "id": "light_off_kitchen", "intent": "control_light",
        "turns": ["关掉厨房的灯"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "off", "room": "kitchen"}}],
        "expect_state": [["light.kitchen.on", False]],
        "keywords": ["厨房", "关"],
    },
    {
        "id": "light_dim_living", "intent": "control_light",
        "turns": ["客厅灯调暗一点"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "set", "room": "living_room", "brightness": 30}}],
        "expect_state": [["light.living_room.brightness", 30]],
        "keywords": ["客厅", "暗"],
    },
    {
        "id": "light_dim_bedroom", "intent": "control_light",
        "turns": ["卧室灯太亮了，调暗一点"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "set", "room": "bedroom", "brightness": 30}}],
        "expect_state": [["light.bedroom.brightness", 30]],
        "keywords": ["卧室", "调暗"],
    },
    {
        "id": "light_bright", "intent": "control_light",
        "turns": ["把灯调亮一些"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "set", "room": "living_room", "brightness": 100}}],
        "expect_state": [["light.living_room.brightness", 100]],
        "keywords": ["灯", "亮"],
    },
    {
        "id": "light_green", "intent": "control_light",
        "turns": ["客厅的灯换成绿色"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "set", "room": "living_room", "color": "green"}}],
        "expect_state": [["light.living_room.color", "green"]],
        "keywords": ["客厅", "绿色"],
    },
    {
        "id": "light_off_loose", "intent": "control_light",
        "turns": ["帮我把客厅的灯关掉"],
        "expect_turns": [{"name": "control_light",
                          "args": {"action": "off", "room": "living_room"}}],
        "expect_state": [["light.living_room.on", False]],
        "keywords": ["客厅", "关"],
    },
    {
        "id": "fan_on", "intent": "control_fan",
        "turns": ["打开风扇"],
        "expect_turns": [{"name": "control_fan", "args": {"action": "on"}}],
        "expect_state": [["fan.on", True]],
        "keywords": ["风扇", "开"],
    },
    {
        "id": "fan_off", "intent": "control_fan",
        "turns": ["关掉风扇"],
        "expect_turns": [{"name": "control_fan", "args": {"action": "off"}}],
        "expect_state": [["fan.on", False]],
        "keywords": ["风扇", "关"],
    },
    {
        "id": "fan_speed3", "intent": "control_fan",
        "turns": ["风扇调到三档"],
        "expect_turns": [{"name": "control_fan", "args": {"action": "set", "speed": 3}}],
        "expect_state": [["fan.speed", 3], ["fan.on", True]],
        "keywords": ["风扇", "三档"],
    },
    {
        "id": "fan_speed1", "intent": "control_fan",
        "turns": ["风速调到一档"],
        "expect_turns": [{"name": "control_fan", "args": {"action": "set", "speed": 1}}],
        "expect_state": [["fan.speed", 1]],
        "keywords": ["风速", "一档"],
    },
    {
        "id": "door_unlock", "intent": "control_door",
        "turns": ["解锁大门"],
        "expect_turns": [{"name": "control_door", "args": {"action": "unlock"}}],
        "expect_state": [["door.locked", False]],
        "keywords": ["解锁", "门"],
    },
    {
        "id": "door_lock", "intent": "control_door",
        "turns": ["把门锁上"],
        "expect_turns": [{"name": "control_door", "args": {"action": "lock"}}],
        "expect_state": [["door.locked", True]],
        "keywords": ["门", "锁"],
    },
    {
        "id": "door_close", "intent": "control_door",
        "turns": ["关门"],
        "expect_turns": [{"name": "control_door", "args": {"action": "close"}}],
        "expect_state": [["door.open", False]],
        "keywords": ["关", "门"],
    },
    {
        "id": "ac_on", "intent": "control_ac",
        "turns": ["打开空调"],
        "expect_turns": [{"name": "control_ac", "args": {"action": "on"}}],
        "expect_state": [["ac.on", True]],
        "keywords": ["空调", "开"],
    },
    {
        "id": "ac_off", "intent": "control_ac",
        "turns": ["关掉空调"],
        "expect_turns": [{"name": "control_ac", "args": {"action": "off"}}],
        "expect_state": [["ac.on", False]],
        "keywords": ["空调", "关"],
    },
    {
        "id": "ac_26", "intent": "control_ac",
        "turns": ["空调调到26度"],
        "expect_turns": [{"name": "control_ac",
                          "args": {"action": "set", "temperature": 26}}],
        "expect_state": [["ac.temperature", 26], ["ac.on", True]],
        "keywords": ["空调", "26度"],
    },
    {
        "id": "ac_24", "intent": "control_ac",
        "turns": ["空调调到24度"],
        "expect_turns": [{"name": "control_ac",
                          "args": {"action": "set", "temperature": 24}}],
        "expect_state": [["ac.temperature", 24]],
        "keywords": ["空调", "24度"],
    },
    {
        "id": "scene_home", "intent": "set_scene",
        "turns": ["切换到回家模式"],
        "expect_turns": [{"name": "set_scene", "args": {"scene": "home"}}],
        "expect_state": [["scene", "home"]],
        "keywords": ["回家", "模式"],
    },
    {
        "id": "scene_away", "intent": "set_scene",
        "turns": ["切换到离家模式"],
        "expect_turns": [{"name": "set_scene", "args": {"scene": "away"}}],
        "expect_state": [["scene", "away"], ["light.living_room.on", False]],
        "keywords": ["离家", "模式"],
    },
    {
        "id": "scene_sleep", "intent": "set_scene",
        "turns": ["切换到睡觉模式"],
        "expect_turns": [{"name": "set_scene", "args": {"scene": "sleep"}}],
        "expect_state": [["scene", "sleep"]],
        "keywords": ["睡觉", "模式"],
    },
    {
        "id": "scene_movie", "intent": "set_scene",
        "turns": ["切换到观影模式"],
        "expect_turns": [{"name": "set_scene", "args": {"scene": "movie"}}],
        "expect_state": [["scene", "movie"]],
        "keywords": ["观影", "模式"],
    },
    {
        "id": "query_temperature", "intent": "query_sensor",
        "turns": ["现在屋里多少度？"],
        "expect_turns": [{"name": "query_sensor", "args": {"metric": "temperature"}}],
        "expect_state": [],
        "keywords": ["多少度"],
    },
    {
        "id": "query_humidity", "intent": "query_sensor",
        "turns": ["室内湿度是多少？"],
        "expect_turns": [{"name": "query_sensor", "args": {"metric": "humidity"}}],
        "expect_state": [],
        "keywords": ["湿度"],
    },
    {
        "id": "query_motion", "intent": "query_sensor",
        "turns": ["家里有没有人？"],
        "expect_turns": [{"name": "query_sensor", "args": {"metric": "motion"}}],
        "expect_state": [],
        "keywords": ["有没有人"],
    },
    {
        "id": "query_all", "intent": "query_sensor",
        "turns": ["查一下所有传感器"],
        "expect_turns": [{"name": "query_sensor", "args": {"metric": "all"}}],
        "expect_state": [],
        "keywords": ["传感器"],
    },
    # ── multi-turn / contextual ──────────────────────────────────────
    {
        "id": "multi_light", "intent": "multi_turn",
        "turns": ["打开客厅灯", "把颜色换成蓝色", "调暗一点"],
        "expect_turns": [
            {"name": "control_light", "args": {"action": "on", "room": "living_room"}},
            {"name": "control_light", "args": {"action": "set", "room": "living_room", "color": "blue"}},
            {"name": "control_light", "args": {"action": "set", "room": "living_room", "brightness": 30}},
        ],
        "expect_state": [["light.living_room.color", "blue"],
                         ["light.living_room.brightness", 30]],
        "keywords": ["客厅", "蓝色"],
    },
    {
        "id": "multi_fan", "intent": "multi_turn",
        "turns": ["打开风扇", "调到三档"],
        "expect_turns": [
            {"name": "control_fan", "args": {"action": "on"}},
            {"name": "control_fan", "args": {"action": "set", "speed": 3}},
        ],
        "expect_state": [["fan.speed", 3]],
        "keywords": ["风扇", "三档"],
    },
    {
        "id": "multi_ac", "intent": "multi_turn",
        "turns": ["打开空调", "调到24度"],
        "expect_turns": [
            {"name": "control_ac", "args": {"action": "on"}},
            {"name": "control_ac", "args": {"action": "set", "temperature": 24}},
        ],
        "expect_state": [["ac.temperature", 24]],
        "keywords": ["空调", "24度"],
    },
    {
        "id": "multi_door", "intent": "multi_turn",
        "turns": ["解锁大门", "把门打开"],
        "expect_turns": [
            {"name": "control_door", "args": {"action": "unlock"}},
            {"name": "control_door", "args": {"action": "open"}},
        ],
        "expect_state": [["door.open", True], ["door.locked", False]],
        "keywords": ["解锁", "开门"],
    },
]

SINGLE_TURN = [c for c in CASES if len(c["turns"]) == 1]
MULTI_TURN = [c for c in CASES if len(c["turns"]) > 1]


def get_path(state: dict, path: str) -> Any:
    node: Any = state
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
