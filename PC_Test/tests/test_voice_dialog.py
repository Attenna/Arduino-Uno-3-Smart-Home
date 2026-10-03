import asyncio
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from sherpa_listener import SherpaListener
from tts_player import TtsPlayer
from voice_assistant import VoiceAssistant, validate_tool_arguments
from voice_context_server import ConversationContextStore

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None


class ContextStoreTests(unittest.TestCase):
    def test_persists_only_bounded_confirmed_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.json"
            store = ConversationContextStore(path, max_turns=2, ttl_hours=1)
            for index in range(3):
                store.record("home", f"user {index}", f"answer {index}", [{
                    "name": "light", "arguments": {"action": "on"},
                    "ok": index == 2, "result": "ok" if index == 2 else "error",
                }])
            loaded = ConversationContextStore(path, max_turns=2, ttl_hours=1).get("home", 9)
            self.assertEqual([t["user"] for t in loaded["turns"]], ["user 1", "user 2"])
            self.assertTrue(loaded["turns"][-1]["tool_results"][0]["ok"])

    def test_expired_turn_is_not_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.json"
            path.write_text(json.dumps({"version": 1, "sessions": {"home": {
                "turns": [{"timestamp": 1, "user": "old", "assistant": "old"}]
            }}}), encoding="utf-8")
            store = ConversationContextStore(path, ttl_hours=1)
            self.assertEqual(store.get("home")["turns"], [])

    @unittest.skipUnless(MCP_AVAILABLE, "MCP SDK is installed in the voice image")
    def test_stdio_mcp_round_trip(self):
        from voice_context_client import VoiceContextClient

        async def scenario(directory):
            client = VoiceContextClient({
                "enabled": True,
                "store_path": str(Path(directory) / "context.json"),
                "session_id": "integration",
                "history_rounds": 3,
            }, str(Path(__file__).resolve().parents[1]))
            try:
                self.assertTrue(await client.start())
                await client.record_turn("开灯", "已经打开。", [{
                    "name": "light", "arguments": {"action": "on"},
                    "ok": True, "result": "ok",
                }])
                value = await client.get_context()
                self.assertEqual(value["turns"][0]["user"], "开灯")
                self.assertTrue(value["turns"][0]["tool_results"][0]["ok"])
            finally:
                await client.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(directory))


class ListenerGateTests(unittest.TestCase):
    def test_asr_is_not_fed_while_disabled(self):
        listener = SherpaListener.__new__(SherpaListener)
        listener.last_partial = ""
        listener.kws_stream = Mock()
        listener.kws = Mock()
        listener.kws.is_ready.return_value = False
        listener.kws.get_result.return_value = ""
        listener.asr_stream = Mock()
        listener.recognizer = Mock()
        events = listener.accept(np.zeros(1600, dtype=np.float32),
                                 enable_kws=True, enable_asr=False)
        self.assertEqual(events, [])
        listener.kws_stream.accept_waveform.assert_called_once()
        listener.asr_stream.accept_waveform.assert_not_called()


class TtsOutputTests(unittest.TestCase):
    def test_missing_output_device_skips_synthesis(self):
        player = TtsPlayer.__new__(TtsPlayer)
        player.output_available = False
        player._cancel = threading.Event()
        player.tts = Mock()
        player._play_sentence("测试回复")
        player.tts.generate.assert_not_called()


class ListeningStateTests(unittest.TestCase):
    @staticmethod
    def assistant():
        assistant = VoiceAssistant.__new__(VoiceAssistant)
        assistant.state = "IDLE"
        assistant._state_lock = threading.RLock()
        assistant._listen_generation = 0
        assistant._turn_cancel = threading.Event()
        assistant.command_state_start = 0.0
        assistant.speech_state_start = 0.0
        assistant.command_timeout = 8.0
        assistant.followup_timeout = 8.0
        assistant.ack_mode = "chirp"
        assistant.chirp_freq = 880
        assistant.chirp_ms = 20
        assistant.wake_ack = "在的"
        assistant.listener = Mock()
        assistant.stream = object()
        assistant.events = Mock()
        assistant._last_state = None
        assistant.tts = Mock()
        assistant.tts.is_busy.return_value = False
        assistant.tts.wait_done.return_value = True
        return assistant

    def test_listening_starts_only_after_ack_is_done(self):
        assistant = self.assistant()
        release = threading.Event()
        assistant.tts.wait_done.side_effect = lambda: release.wait(1)
        with patch("builtins.print"):
            assistant._on_wake("Hey Bota", time.time())
            self.assertEqual(assistant.state, "ACK")
            self.assertEqual(assistant.command_state_start, 0.0)
            release.set()
            deadline = time.time() + 1
            while assistant.state != "COMMAND" and time.time() < deadline:
                time.sleep(.01)
        self.assertEqual(assistant.state, "COMMAND")
        self.assertGreater(assistant.command_state_start, 0)
        assistant.listener.reset_asr.assert_called()

    def test_followup_clock_starts_after_tts(self):
        assistant = self.assistant()
        assistant.state = "THINKING"
        with patch("builtins.print"):
            assistant._open_followup()
        self.assertEqual(assistant.state, "FOLLOWUP")
        self.assertGreater(assistant.command_state_start, 0)
        self.assertEqual(assistant.speech_state_start, 0)

    def test_manual_wake_cancels_inflight_thinking(self):
        assistant = self.assistant()
        assistant.state = "THINKING"
        assistant._begin_listening_after_ack = Mock()
        with patch("builtins.print"):
            assistant._on_wake("button", time.time(), manual=True)
        self.assertTrue(assistant._turn_cancel.is_set())


class ToolSafetyTests(unittest.TestCase):
    def test_schema_validation_rejects_bad_arguments(self):
        tool = {"function": {"name": "fan", "parameters": {
            "type": "object", "properties": {
                "value": {"type": "integer", "minimum": 0, "maximum": 255}},
            "required": ["value"], "additionalProperties": False}}}
        self.assertIn("缺少", validate_tool_arguments(tool, {}))
        self.assertIn("类型", validate_tool_arguments(tool, {"value": "fast"}))
        self.assertIn("最大值", validate_tool_arguments(tool, {"value": 300}))
        self.assertIsNone(validate_tool_arguments(tool, {"value": 128}))

    def test_duplicate_hardware_call_is_blocked(self):
        assistant = VoiceAssistant.__new__(VoiceAssistant)
        assistant.system_prompt = "test"
        assistant.history_rounds = 0
        assistant.history = []
        assistant.context = SimpleNamespace(online=False)
        assistant._turn_cancel = threading.Event()
        assistant.llm_tools = [{"type": "function", "function": {
            "name": "light", "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["on", "off"]}},
                "required": ["action"]}}}]
        call = {"id": "1", "type": "function", "function": {
            "name": "light", "arguments": '{"action":"on"}'}}
        assistant.stream_llm = AsyncMock(side_effect=[("", [call, {**call, "id": "2"}]),
                                                      ("已经打开。", [])])
        assistant.gateway = SimpleNamespace(call=Mock(return_value=(True, "ok")))
        assistant.tts = Mock()
        assistant.events = Mock()
        assistant.max_tool_calls = 6
        assistant.publish = Mock()
        asyncio.run(assistant.handle_command("开灯"))
        assistant.gateway.call.assert_called_once_with("light", {"action": "on"})

    def test_cancelled_turn_is_not_remembered(self):
        assistant = VoiceAssistant.__new__(VoiceAssistant)
        assistant.system_prompt = "test"
        assistant.history_rounds = 2
        assistant.history = []
        assistant.context = SimpleNamespace(online=False)
        assistant._turn_cancel = threading.Event()
        assistant._turn_cancel.set()
        assistant.llm_tools = []
        assistant.stream_llm = AsyncMock(return_value=("", []))
        assistant.tts = Mock()
        assistant.events = Mock()
        assistant.max_tool_calls = 6
        assistant.publish = Mock()
        asyncio.run(assistant.handle_command("旧指令"))
        self.assertEqual(assistant.history, [])
        assistant.publish.assert_called_with("turn_end", cancelled=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
