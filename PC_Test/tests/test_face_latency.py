# -*- coding: utf-8 -*-
"""人脸识别延迟单测（issue #10）：首帧预热、JPEG 直解、提特征前置门控、
PIR 上升沿即时抓帧。

不加载模型、不连摄像头：detector/recognizer/guard 都用桩件，为的是测「什么时候
付那 370ms/张 的提特征钱、什么时候才肯等满一个 interval」这段调度与裁剪逻辑。
识别精度不在这里测。
"""
import base64
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.face import engine as engine_mod
from web import face_watcher as watcher_mod
from web.face.engine import FaceEngine
from web.face_watcher import FaceWatcher


class FakeBox:
    def __init__(self, x1, y1, x2, y2, confidence=0.9, landmarks=None):
        self.bbox = (x1, y1, x2, y2)
        self.confidence = confidence
        self.landmarks = landmarks

    def xyxy_int(self):
        return self.bbox


class FakeDetector:
    def __init__(self, boxes=()):
        self.boxes = list(boxes)
        self.frames = []

    def detect(self, frame):
        self.frames.append(getattr(frame, "shape", None))
        return [b if isinstance(b, FakeBox) else FakeBox(*b) for b in self.boxes]


class FakeRecognizer:
    def __init__(self, score=0.8, authorized=True):
        self.calls = []
        self.score = score
        self.authorized = authorized
        self.image_size = 112

    def recognize(self, crop):
        self.calls.append(crop.shape[:2])
        return type("R", (), {"score": self.score, "authorized": self.authorized,
                              "identity": "爱丽丝"})()


def build_engine(boxes=(), max_faces=5, saved_max_faces=None):
    """构造一个「有模型」外观的引擎，但推理全是桩件。

    max_faces 走 web_cfg（= web_config.yaml 的那一行）；saved_max_faces 用来模拟
    data/face/face_config.json 里别的机器留下的旧取值。
    """
    cfg = Path(tempfile.mkdtemp()) / "face_config.json"
    saved = {"simulation_mode": True}
    if saved_max_faces is not None:
        saved["max_faces"] = saved_max_faces
    cfg.write_text(json.dumps(saved), encoding="utf-8")
    engine = FaceEngine(config_path=cfg, web_cfg={"face": {"max_faces": max_faces}})
    engine.simulation_mode = False
    engine.throttler.min_interval = 0.0
    engine.detector = FakeDetector(boxes)
    engine.recognizer = FakeRecognizer()
    return engine


def jpeg(width=320, height=240, seed=3):
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", frame)[1].tobytes()


class RecognizePathTests(unittest.TestCase):
    def test_jpeg_is_decoded_directly_without_base64_roundtrip(self):
        engine = build_engine([(10, 10, 130, 130)])
        with patch.object(engine_mod.base64, "b64encode",
                          side_effect=AssertionError("不该再走 base64")):
            result = engine.recognize_jpeg(jpeg(320, 240))
        self.assertTrue(result["detected"])
        self.assertEqual(engine.detector.frames, [(240, 320, 3)])
        self.assertEqual(engine.recognizer.calls, [(120, 120)])
        self.assertEqual(result["face_id"], "爱丽丝")
        self.assertEqual(result["score"], 0.8)

    def test_five_landmarks_align_before_arcface(self):
        landmarks = ((58.0, 82.0), (128.0, 82.0), (93.0, 122.0),
                     (65.0, 162.0), (121.0, 162.0))
        engine = build_engine([FakeBox(30, 40, 160, 190, landmarks=landmarks)])
        result = engine.recognize_jpeg(jpeg(220, 220))
        self.assertEqual(engine.recognizer.calls, [(112, 112)])
        self.assertTrue(result["faces"][0]["aligned"])
        self.assertEqual(result["faces"][0]["score"], 0.8)

    def test_base64_entry_still_accepts_data_uri_prefix(self):
        engine = build_engine([(10, 10, 130, 130)])
        blob = jpeg(200, 160)
        encoded = "data:image/jpeg;base64," + base64.b64encode(blob).decode()
        self.assertTrue(engine.recognize_from_base64(encoded)["detected"])
        self.assertTrue(engine.recognize_from_base64(
            base64.b64encode(blob).decode())["detected"])

    def test_face_too_small_for_door_never_pays_for_embedding(self):
        far, near = (100, 100, 140, 140), (10, 10, 210, 210)
        engine = build_engine([far, near])
        result = engine.recognize_jpeg(jpeg(240, 240), min_face_px=60)
        # 小脸照样出现在 faces 里（前端要画框、状态要说「站得太远」），但不提特征
        self.assertEqual(len(result["faces"]), 2)
        self.assertEqual(engine.recognizer.calls, [(200, 200)])
        self.assertEqual([f["score"] for f in result["faces"]], [None, 0.8])
        self.assertTrue(result["detected"])

    def test_max_faces_caps_how_many_faces_get_embedded(self):
        boxes = [(0, 0, s, s) for s in (40, 50, 60, 70, 80)]
        engine = build_engine(boxes, max_faces=2)
        result = engine.recognize_jpeg(jpeg(100, 100))
        self.assertEqual(len(result["faces"]), 5)
        # 面积最大的两张（80、70）才提特征；顺序仍按画面里的检出顺序
        self.assertEqual(engine.recognizer.calls, [(70, 70), (80, 80)])

    def test_max_faces_zero_means_no_cap(self):
        boxes = [(0, 0, s, s) for s in (40, 50, 60)]
        engine = build_engine(boxes, max_faces=0)
        engine.recognize_jpeg(jpeg(100, 100))
        self.assertEqual(len(engine.recognizer.calls), 3)

    def test_stale_saved_max_faces_is_ignored(self):
        """上限只认 yaml：face_config.json 是运行期写的，可能带着另一台机器的取值。"""
        boxes = [(0, 0, s, s) for s in (40, 50, 60)]
        engine = build_engine(boxes, max_faces=1, saved_max_faces=9)
        engine.recognize_jpeg(jpeg(100, 100))
        self.assertEqual(len(engine.recognizer.calls), 1)

    def test_blocked_recognition_pays_no_embedding(self):
        """认人被停用（库与模型不匹配）时不该再为每张脸付提特征的钱。"""
        engine = build_engine([(10, 10, 130, 130), (10, 160, 50, 200)])
        engine.recognition_block = "人脸库由模型 X 建立，当前模型是 Y"
        result = engine.recognize_jpeg(jpeg(240, 240), min_face_px=20)
        self.assertEqual(engine.recognizer.calls, [])
        self.assertEqual(result["mode"], "yolov8")
        # 检测照常：框还在，页面仍能说「站得太远」，只是不比对身份
        self.assertTrue(result["detected"])
        self.assertEqual(len(result["faces"]), 2)

    def test_throttle_window_is_visible_to_the_watcher(self):
        """哨兵要靠这个属性把两轮下限抬到不低于节流窗口。"""
        engine = build_engine()
        self.assertEqual(engine.recognition_min_interval, 0.0)
        engine.throttler.min_interval = 1.5
        self.assertEqual(engine.recognition_min_interval, 1.5)


class WarmupTests(unittest.TestCase):
    def test_warmup_runs_one_detect_and_one_embed(self):
        engine = build_engine()
        self.assertTrue(engine.warmup())
        self.assertEqual(len(engine.detector.frames), 1)
        self.assertEqual(engine.detector.frames[0], (480, 640, 3))
        self.assertEqual(len(engine.recognizer.calls), 1)

    def test_warmup_survives_model_failure(self):
        engine = build_engine()
        engine.detector.detect = lambda frame: (_ for _ in ()).throw(
            RuntimeError("boom"))
        self.assertFalse(engine.warmup())

    def test_warmup_skipped_in_simulation(self):
        cfg = Path(tempfile.mkdtemp()) / "face_config.json"
        cfg.write_text('{"simulation_mode": true}', encoding="utf-8")
        engine = FaceEngine(config_path=cfg, web_cfg={"face": {}})
        self.assertFalse(engine.start_warmup())

    def test_start_warmup_is_idempotent(self):
        engine = build_engine()
        self.assertTrue(engine.start_warmup())
        self.assertFalse(engine.start_warmup())
        deadline = time.time() + 2.0
        while not engine._warmup_done and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(engine._warmup_done, "后台预热线程没跑起来")
        self.assertEqual(len(engine.detector.frames), 1)


class MotionEdgeWakeTests(unittest.TestCase):
    """PIR 报「有人」要立刻抓帧，而不是等满 interval。"""

    class Engine:
        def __init__(self):
            self.calls = []
            self.result = {"detected": False, "faces": [], "mode": "yolov8"}
            self.recognition_min_interval = 0.0

        def identity_count(self):
            return 1

        def recognize_jpeg(self, blob, min_face_px=0):
            self.calls.append({"min_face_px": min_face_px})
            return dict(self.result)

    class Guard:
        def handle_face_result(self, face_id, confidence=None, device_source="", **kwargs):
            return {"granted": False, "reason": "no_identity"}

        def record_observation(self, kind, face_id="", device_source="", **kwargs):
            return None

    def setUp(self):
        # interval 设得很长：观察到的第二轮只可能来自上升沿，不可能是周期到点
        self.patcher = patch.object(watcher_mod, "MIN_WAKE_SPACING_S", 0.05)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.engine = self.Engine()
        cfg = {"camera": {"stream_url": "http://cam:8080/video_feed"},
               "face": {"watcher": {"interval": 30.0, "motion_gate": True,
                                    "min_face_px": 77}}}
        self.watcher = FaceWatcher(self.engine, self.Guard(), cfg)
        self.watcher.grab_frame = lambda: b"jpeg"
        self.watcher.start()
        self.addCleanup(self.watcher.stop)

    def wait_for_calls(self, at_least, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.engine.calls) >= at_least:
                return True
            time.sleep(0.01)
        return False

    def test_first_cycle_runs_immediately(self):
        self.assertTrue(self.wait_for_calls(1))

    def test_motion_rising_edge_starts_a_cycle_without_waiting(self):
        self.assertTrue(self.wait_for_calls(1))
        self.watcher.on_snapshot({"motion": True})
        self.assertTrue(self.wait_for_calls(2), "上升沿没能在 interval 内触发第二轮")

    def test_wake_floor_follows_the_recognition_throttle(self):
        """唤醒撞在节流窗口里只会白取一帧（下一轮还要等满 interval）：下限跟着节流走。"""
        self.engine.recognition_min_interval = 0.6
        self.assertTrue(self.wait_for_calls(1))
        self.watcher.on_snapshot({"motion": True})
        time.sleep(0.25)          # 已过 MIN_WAKE_SPACING_S，但还在节流里
        self.assertEqual(len(self.engine.calls), 1)
        self.assertTrue(self.wait_for_calls(2, timeout=2.0),
                        "节流窗口打开后没补上这一轮")

    def test_steady_motion_does_not_repeatedly_wake(self):
        self.assertTrue(self.wait_for_calls(1))
        self.watcher.on_snapshot({"motion": True})
        self.assertTrue(self.wait_for_calls(2))
        seen = len(self.engine.calls)
        # 持续为真（没有新的上升沿）和转假都不该再起一轮
        for _ in range(6):
            self.watcher.on_snapshot({"motion": True})
        for _ in range(6):
            self.watcher.on_snapshot({"motion": False})
        time.sleep(0.2)
        self.assertEqual(len(self.engine.calls), seen)

    def test_min_face_px_reaches_the_engine(self):
        self.assertTrue(self.wait_for_calls(1))
        self.assertEqual(self.engine.calls[0]["min_face_px"], 77)

    def test_stop_does_not_wait_for_the_interval(self):
        self.assertTrue(self.wait_for_calls(1))
        started = time.monotonic()
        self.watcher.stop()
        self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
