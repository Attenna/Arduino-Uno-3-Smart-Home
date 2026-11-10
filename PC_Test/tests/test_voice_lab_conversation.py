import queue
import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_lab.config import DEFAULT_CONFIG
from voice_lab.conversation import (ConversationController, ConversationState,
                                    VAD)
from voice_lab.dialog import DialogEngine
from voice_lab.llm import RuleLLM
from voice_lab.schemas import Timing, TurnResult
from voice_lab.tts import NullTTS


def wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def frame(value=0.0, samples=480):
    if value:
        t = np.arange(samples, dtype=np.float32)
        return (value * np.sin(2 * np.pi * 180 * t / 16000)).astype(np.float32)
    return np.zeros(samples, dtype=np.float32)


class FakeKWS:
    def __init__(self):
        self.keywords = ["Hey Bota"]
        self.hits = 0

    def accept(self, frame):
        self.hits += 1
        return None

    def reset(self):
        pass


class FakeSource:
    def __init__(self, frames):
        self.q = queue.Queue()
        for f in frames:
            self.q.put(f)
        self.started = False

    def start(self):
        self.started = True

    def read(self, timeout=0.1):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        pass


class _NoASR:
    backend = "fake"

    def transcribe_file(self, path):
        raise AssertionError("text-only test should not call ASR")


class BlockingEngine:
    """Fake engine that holds the turn in SPEAKING until released."""

    def __init__(self):
        self.turns = []
        self.started = __import__("threading").Event()
        self.release = __import__("threading").Event()
        self.cancelled = False
        self.stage_cb = None

    def handle_audio(self, path, speak=True, play=None, stage_cb=None):
        self.turns.append(path)
        self.stage_cb = stage_cb
        if stage_cb:
            stage_cb("thinking")
            stage_cb("speaking")
        self.started.set()
        self.release.wait(timeout=5)
        if self.cancelled:
            return TurnResult("", "", state={}, error="cancelled")
        return TurnResult("把客厅的灯调成蓝色", "好的，客厅灯已设为蓝色。",
                          timing=Timing(total_ms=1.0), events=[], state={})

    def cancel(self):
        self.cancelled = True
        self.release.set()

    def handle_text(self, text, speak=True, play=None, stage_cb=None):
        return TurnResult(text, "好的", timing=Timing(total_ms=1.0), events=[])


def controller_config():
    cfg = __import__("copy").deepcopy(DEFAULT_CONFIG)
    cfg["audio"]["sample_rate"] = 16000
    cfg["audio"]["energy_threshold"] = 0.01
    cfg["audio"]["silence_seconds"] = 0.2
    cfg["audio"]["min_speech_seconds"] = 0.05
    cfg["wake"]["command_timeout"] = 2.0
    cfg["wake"]["followup_timeout"] = 2.0
    cfg["wake"]["max_utterance_seconds"] = 2.0
    cfg["wake"]["ack"] = "none"
    return cfg


class VADTests(unittest.TestCase):
    def test_speech_start_and_end(self):
        vad = VAD(sample_rate=16000, threshold=0.01, silence_s=0.2,
                  min_speech_s=0.05, max_speech_s=2.0)
        self.assertEqual(vad.push(frame()), [])
        events = []
        for _ in range(3):
            events.extend(vad.push(frame(0.2)))
        self.assertEqual([e.kind for e in events], ["speech_start"])
        self.assertTrue(vad.in_speech)
        end = []
        for _ in range(10):
            end.extend(vad.push(frame()))
        self.assertTrue(end)
        self.assertEqual(end[-1].kind, "speech_end")
        self.assertGreater(len(end[-1].audio), 0)
        self.assertFalse(vad.in_speech)

    def test_short_click_is_discarded(self):
        vad = VAD(sample_rate=16000, threshold=0.01, silence_s=0.1,
                  min_speech_s=0.2, max_speech_s=2.0)
        vad.push(frame(0.2))
        events = []
        for _ in range(5):
            events.extend(vad.push(frame()))
        self.assertTrue(any(e.kind == "speech_discarded" for e in events))
        self.assertFalse(vad.in_speech)


class ConversationTests(unittest.TestCase):
    def make_controller(self, frames, engine=None, kws=None):
        engine = engine or BlockingEngine()
        controller = ConversationController(
            engine, controller_config(), source=FakeSource(frames),
            kws=kws or FakeKWS())
        return controller, engine

    def test_half_duplex_ignores_speech_while_speaking(self):
        engine = BlockingEngine()
        frames = [frame(), frame()] + [frame(0.2)] * 4 + [frame()] * 8
        controller, engine = self.make_controller(frames, engine)
        controller.wake()
        self.assertTrue(controller.start())
        try:
            self.assertTrue(engine.started.wait(2.0))
            self.assertEqual(controller.state, ConversationState.SPEAKING)
            # These frames arrive while the engine is blocked in SPEAKING.
            for _ in range(8):
                controller._handle_frame(frame(0.2))
            engine.release.set()
            self.assertTrue(wait_until(lambda: controller.state == ConversationState.FOLLOWUP))
            self.assertEqual(len(engine.turns), 1)
        finally:
            controller.stop()

    def test_interrupt_returns_to_listening(self):
        engine = BlockingEngine()
        frames = [frame(), frame()] + [frame(0.2)] * 4 + [frame()] * 8
        controller, engine = self.make_controller(frames, engine)
        controller.wake()
        self.assertTrue(controller.start())
        try:
            self.assertTrue(engine.started.wait(2.0))
            self.assertEqual(controller.state, ConversationState.SPEAKING)
            controller.interrupt()
            self.assertEqual(controller.state, ConversationState.LISTENING)
            self.assertTrue(engine.cancelled)
        finally:
            controller.stop()

    def test_followup_timeout_returns_idle(self):
        engine = BlockingEngine()
        controller, _ = self.make_controller([frame()], engine)
        controller._set_state(ConversationState.FOLLOWUP)
        controller._state_since = time.monotonic() - 3.0
        controller._check_timeout()
        self.assertEqual(controller.state, ConversationState.IDLE)

    def test_manual_wake_enters_listening(self):
        engine = BlockingEngine()
        controller, _ = self.make_controller([frame()], engine)
        controller.wake()
        self.assertTrue(controller.start())
        try:
            self.assertTrue(wait_until(
                lambda: controller.state in (ConversationState.WAKING,
                                             ConversationState.LISTENING)))
        finally:
            controller.stop()


class DialogStageTests(unittest.TestCase):
    def test_stage_callback_thinking_speaking_done(self):
        cfg = __import__("copy").deepcopy(DEFAULT_CONFIG)
        stages = []
        engine = DialogEngine(cfg, asr=_NoASR(), llm=RuleLLM(),
                              tts=NullTTS(), tts_enabled=True, play_tts=False)
        result = engine.handle_text("打开风扇", speak=True,
                                    stage_cb=stages.append)
        self.assertEqual(result.error, "")
        self.assertIn("thinking", stages)
        self.assertIn("speaking", stages)
        self.assertIn("done", stages)

    def test_cancel_flag_is_exposed(self):
        cfg = __import__("copy").deepcopy(DEFAULT_CONFIG)
        engine = DialogEngine(cfg, asr=_NoASR(), llm=RuleLLM(),
                              tts=NullTTS(), tts_enabled=False)
        self.assertFalse(engine.cancelled)
        engine.cancel()
        self.assertTrue(engine.cancelled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
