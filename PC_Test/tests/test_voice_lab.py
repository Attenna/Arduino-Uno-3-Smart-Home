import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_lab.asr import ASRResult, FasterWhisperASR, build_asr, normalize_text
from voice_lab.cases import get_path
from voice_lab.config import DEFAULT_CONFIG, load_config
from voice_lab.dialog import DialogEngine
from voice_lab.llm import (BaseLLM, HybridLLM, RuleLLM, build_tool_followup,
                           parse_tool_calls, strip_tool_blocks)
from voice_lab.metrics import (cer, edit_distance, exact_match, percentile,
                               summarize, tool_match)
from voice_lab.schemas import LLMReply, ToolCall, ToolResult
from voice_lab.tools import MockHome, TOOLS, schema_errors
from voice_lab.tts import NullTTS, SentenceSplitter


class ToolSchemaTests(unittest.TestCase):
    def test_required_and_enum_validation(self):
        self.assertIn("缺少", "；".join(schema_errors("control_light", {"room": "living_room"})))
        self.assertIn("允许值", "；".join(schema_errors(
            "control_light", {"action": "on", "room": "garage"})))
        self.assertIn("最大值", "；".join(schema_errors(
            "control_light", {"action": "set", "room": "living_room", "brightness": 101})))
        self.assertEqual(schema_errors(
            "control_light", {"action": "set", "room": "living_room", "color": "blue"}), [])

    def test_unknown_tool_is_rejected(self):
        self.assertIn("未知工具", "；".join(schema_errors("launch_rocket", {})))


class MockHomeTests(unittest.TestCase):
    def setUp(self):
        self.home = MockHome()

    def test_light_color_and_brightness(self):
        result = self.home.execute(ToolCall("control_light", {
            "action": "set", "room": "living_room", "color": "blue"}))
        self.assertTrue(result.ok)
        state = self.home.snapshot()
        self.assertTrue(state["light"]["living_room"]["on"])
        self.assertEqual(state["light"]["living_room"]["color"], "blue")
        dim = self.home.execute(ToolCall("control_light", {
            "action": "set", "room": "living_room", "brightness": 30}))
        self.assertTrue(dim.ok)
        self.assertEqual(self.home.snapshot()["light"]["living_room"]["brightness"], 30)

    def test_door_must_be_unlocked_before_opening(self):
        blocked = self.home.execute(ToolCall("control_door", {"action": "open"}))
        self.assertFalse(blocked.ok)
        self.home.execute(ToolCall("control_door", {"action": "unlock"}))
        opened = self.home.execute(ToolCall("control_door", {"action": "open"}))
        self.assertTrue(opened.ok)
        self.assertTrue(self.home.snapshot()["door"]["open"])

    def test_scene_and_sensor(self):
        self.home.execute(ToolCall("set_scene", {"scene": "away"}))
        state = self.home.snapshot()
        self.assertEqual(state["scene"], "away")
        self.assertFalse(state["light"]["living_room"]["on"])
        sensor = self.home.execute(ToolCall("query_sensor", {"metric": "temperature"}))
        self.assertTrue(sensor.ok)
        self.assertIn("24.5", sensor.text)
        motion = self.home.execute(ToolCall("query_sensor", {"metric": "motion"}))
        self.assertTrue(motion.ok)
        self.assertIn("有人", motion.text)

    def test_reset(self):
        self.home.execute(ToolCall("control_fan", {"action": "on"}))
        self.home.reset()
        self.assertFalse(self.home.snapshot()["fan"]["on"])


class ToolParsingTests(unittest.TestCase):
    def test_qwen_double_brace_tool_call(self):
        raw = ('<tool_call>\n{{"name": "control_light", "arguments": '
               '{"action": "set", "room": "living_room", "color": "blue"}}}\n</tool_call>')
        calls = parse_tool_calls(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "control_light")
        self.assertEqual(calls[0].arguments["color"], "blue")
        self.assertEqual(strip_tool_blocks(raw), "")

    def test_unclosed_tool_call(self):
        raw = '<tool_call>{"name":"query_sensor","arguments":{"metric":"humidity"}}'
        calls = parse_tool_calls(raw)
        self.assertEqual(calls[0].name, "query_sensor")
        self.assertEqual(calls[0].arguments["metric"], "humidity")

    def test_plain_text_is_not_a_tool_call(self):
        self.assertEqual(parse_tool_calls("好的，已经打开。"), [])

    def test_followup_transcript(self):
        calls = [ToolCall("control_fan", {"action": "off"})]
        results = [ToolResult("control_fan", {"action": "off"}, True, "风扇已关闭")]
        messages = build_tool_followup([{"role": "user", "content": "关风扇"}], calls, results)
        self.assertEqual(messages[-2]["role"], "assistant")
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertIn("风扇已关闭", messages[-1]["content"])


class RuleLLMTests(unittest.TestCase):
    def setUp(self):
        self.llm = RuleLLM()

    def call(self, text):
        return self.llm.chat([{"role": "user", "content": text}], tools=TOOLS)

    def test_light_color(self):
        reply = self.call("把客厅的灯调成蓝色")
        self.assertEqual(reply.tool_calls[0].name, "control_light")
        self.assertEqual(reply.tool_calls[0].arguments,
                         {"action": "set", "room": "living_room", "color": "blue"})
        self.assertTrue(reply.final_text_ready)

    def test_air_conditioner_number_is_set(self):
        reply = self.call("空调调到26度")
        self.assertEqual(reply.tool_calls[0].arguments,
                         {"action": "set", "temperature": 26})

    def test_chinese_temperature_from_asr(self):
        reply = self.call("空调调到二十六度")
        self.assertEqual(reply.tool_calls[0].arguments,
                         {"action": "set", "temperature": 26})
        self.assertEqual(self.call("空调调到二十四度").tool_calls[0].arguments,
                         {"action": "set", "temperature": 24})

    def test_query_and_scene(self):
        self.assertEqual(self.call("现在屋里多少度？").tool_calls[0].arguments,
                         {"metric": "temperature"})
        self.assertEqual(self.call("切换到观影模式").tool_calls[0].arguments,
                         {"scene": "movie"})

    def test_free_chat_has_no_tool(self):
        reply = self.call("你好，你能做什么？")
        self.assertEqual(reply.tool_calls, [])
        self.assertIn("智能家居", reply.text)


class _FakeFallback(BaseLLM):
    backend = "fake"

    def chat(self, messages, tools=None, stream_cb=None):
        return LLMReply(text="fallback", backend="fake", first_token_ms=1.0)


class HybridTests(unittest.TestCase):
    def test_fast_path_skips_fallback_for_explicit_command(self):
        hybrid = HybridLLM(_FakeFallback())
        reply = hybrid.chat([{"role": "user", "content": "打开卧室的灯"}], tools=TOOLS)
        self.assertEqual(reply.tool_calls[0].name, "control_light")
        self.assertTrue(reply.final_text_ready)

    def test_open_question_goes_to_fallback(self):
        hybrid = HybridLLM(_FakeFallback())
        reply = hybrid.chat([{"role": "user", "content": "给我讲个笑话"}], tools=TOOLS)
        self.assertEqual(reply.text, "fallback")

    def test_context_ellipsis_uses_previous_device(self):
        hybrid = HybridLLM(_FakeFallback())
        reply = hybrid.chat([
            {"role": "user", "content": "打开卧室的灯"},
            {"role": "assistant", "content": "好的，卧室灯已打开。"},
            {"role": "user", "content": "把颜色换成蓝色"},
        ], tools=TOOLS)
        self.assertEqual(reply.tool_calls[0].name, "control_light")
        self.assertEqual(reply.tool_calls[0].arguments["room"], "bedroom")
        self.assertEqual(reply.tool_calls[0].arguments["color"], "blue")

    def test_context_ellipsis_fan_speed(self):
        hybrid = HybridLLM(_FakeFallback())
        reply = hybrid.chat([
            {"role": "user", "content": "打开风扇"},
            {"role": "assistant", "content": "好的，风扇已打开。"},
            {"role": "user", "content": "调到三档"},
        ], tools=TOOLS)
        self.assertEqual(reply.tool_calls[0].arguments, {"action": "set", "speed": 3})


class MetricsTests(unittest.TestCase):
    def test_edit_distance_and_cer(self):
        self.assertEqual(edit_distance("abc", "abc"), 0)
        self.assertEqual(edit_distance("abc", "abd"), 1)
        self.assertAlmostEqual(cer("把客厅的灯调成蓝色", "把客厅的灯调成蓝色"), 0.0)
        self.assertGreater(cer("关掉风扇", "关掉风风尚晒晒"), 0.0)
        self.assertTrue(exact_match("把客厅的灯调成蓝色。", "把客厅的灯调成蓝色"))

    def test_percentile_and_summary(self):
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        summary = summarize([1, 2, 3])
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["mean"], 2)

    def test_tool_match_subset(self):
        name_ok, args_ok = tool_match(
            {"name": "control_light", "args": {"action": "set", "room": "living_room"}},
            "control_light", {"action": "set", "room": "living_room", "color": "blue"})
        self.assertTrue(name_ok)
        self.assertTrue(args_ok)

    def test_state_path(self):
        self.assertEqual(get_path({"light": {"on": True}}, "light.on"), True)
        self.assertIsNone(get_path({"light": {}}, "light.on"))


class SentenceSplitterTests(unittest.TestCase):
    def test_splits_chinese_and_flushes(self):
        splitter = SentenceSplitter()
        self.assertEqual(splitter.feed("好的。"), ["好的。"])
        self.assertEqual(splitter.feed("还没结束"), [])
        self.assertEqual(splitter.flush(), ["还没结束"])
        self.assertEqual(splitter.flush(), [])

    def test_normalize_text(self):
        self.assertEqual(normalize_text("把 客廳的燈調成藍色。"), "把客厅的灯调成蓝色")


class _FakeASR:
    backend = "fake"

    def transcribe_file(self, path):
        return ASRResult(text="把客厅的灯调成蓝色", backend="fake",
                         latency_ms=120.0, audio_duration_s=2.0, rtf=0.06,
                         audio_path=path)


class DialogEngineTests(unittest.TestCase):
    def make_engine(self):
        return DialogEngine(DEFAULT_CONFIG, asr=_FakeASR(), llm=RuleLLM(),
                            tts=NullTTS(), tts_enabled=False, play_tts=False)

    def test_text_turn_executes_tool_and_records_timing(self):
        engine = self.make_engine()
        result = engine.handle_text("把客厅的灯调成蓝色", speak=False)
        self.assertEqual(result.error, "")
        self.assertEqual(result.tool_calls[0].name, "control_light")
        self.assertIn("蓝色", result.reply)
        self.assertEqual(engine.home.snapshot()["light"]["living_room"]["color"], "blue")
        self.assertGreaterEqual(result.timing.total_ms, 0)
        self.assertIn("user", [e["type"] for e in result.events])
        self.assertIn("tool", [e["type"] for e in result.events])
        self.assertEqual(len(engine.history), 2)

    def test_audio_turn_merges_asr_timing(self):
        engine = self.make_engine()
        result = engine.handle_audio("demo.wav", speak=False)
        self.assertIsNotNone(result.asr)
        self.assertGreater(result.timing.asr_ms, 0)
        self.assertGreaterEqual(result.timing.total_ms, result.timing.asr_ms)
        self.assertEqual(result.events[0]["type"], "asr")

    def test_empty_input_is_reported(self):
        engine = self.make_engine()
        result = engine.handle_text("   ", speak=False)
        self.assertEqual(result.error, "空指令")

    def test_reset_clears_history_and_state(self):
        engine = self.make_engine()
        engine.handle_text("打开风扇", speak=False)
        engine.reset()
        self.assertEqual(engine.history, [])
        self.assertFalse(engine.home.snapshot()["fan"]["on"])


class ASRFactoryTests(unittest.TestCase):
    def test_faster_whisper_backend_is_selectable_without_loading_model(self):
        cfg = {"backend": "sherpa", "sherpa": {}, "whisper": {},
               "faster_whisper": {"model_dir": "models/whisper_ct2/small"}}
        asr = build_asr(cfg, "faster_whisper")
        self.assertIsInstance(asr, FasterWhisperASR)
        self.assertEqual(asr.backend, "faster_whisper")


class ConfigTests(unittest.TestCase):
    def test_default_paths_resolve_under_pc_test(self):
        cfg = load_config()
        self.assertTrue(cfg["asr"]["sherpa"]["model_dir"].endswith("models\\sherpa\\asr_zh")
                        or cfg["asr"]["sherpa"]["model_dir"].endswith("models/sherpa/asr_zh"))
        self.assertEqual(cfg["llm"]["backend"], "hybrid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
