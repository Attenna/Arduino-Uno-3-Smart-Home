# -*- coding: utf-8 -*-
"""人脸事件入库修复（issue #75）单测。

不加载模型、不连摄像头、不碰串口：只用真实 SQLite + 桩件引擎覆盖
「识别结果 → face_events 留痕 / 去抖只挡动作」这段写库与调度逻辑。

对应验收条件：
  (a) 每轮识别都留痕，去抖只抑制重复的开门动作与通行日志；
  (b) 陌生人（空 face_id）各自成行，不再互相顶掉；
  (c) 放行的就是终态 granted，单条 INSERT 落库，不留 pending；
  (d) `POST /api/face/recognize` 留痕（device_source='web'）但不开门。
"""
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask

from web.database import SmartHomeDB
from web.access_guard import AccessGuard, REPEAT_WINDOW_S
from web.face_watcher import FaceWatcher
from web.api import face as face_api


def temp_db():
    return SmartHomeDB(str(Path(tempfile.mkdtemp()) / "test.db"))


def enroll(db, name, face_id):
    person = db.create_person(name)
    return db.set_person_face(person["id"], face_id)


def face_rows(db, access_type="face"):
    return [r for r in db.get_access_logs(limit=200)
            if r["access_type"] == access_type]


class FakeEngine:
    """只回放固定识别结果，schedule 相关属性照 watcher 的读取方式给全。"""

    def __init__(self, result):
        self.result = dict(result)
        self.recognition_min_interval = 0.0

    def identity_count(self):
        return 1

    def recognize_jpeg(self, blob, min_face_px=0):
        return dict(self.result)


def make_watcher(engine, guard, **overrides):
    opts = {"enabled": True, "interval": 2.0, "motion_gate": False,
            "motion_hold": 20.0, "cooldown": 60.0, "min_face_px": 60}
    opts.update(overrides)
    cfg = {"camera": {"stream_url": "http://cam:8080/video_feed"},
           "face": {"watcher": opts}}
    watcher = FaceWatcher(engine, guard, cfg)
    watcher.grab_frame = lambda: b"jpeg"
    return watcher


def detected(face_id, side=120, score=0.9, confidence=0.95):
    return {"detected": True, "mode": "yolov8", "face_id": face_id,
            "faces": [{"face_id": face_id, "score": score,
                       "confidence": confidence,
                       "bbox": {"x1": 0, "y1": 0, "x2": side, "y2": side}}]}


class AccessGuardEventTests(unittest.TestCase):
    """核心写库语义：每轮留痕、去抖只挡动作、终态一次写入。"""

    def setUp(self):
        self.db = temp_db()
        self.guard = AccessGuard(self.db)
        enroll(self.db, "爱丽丝", "alice-face")
        self.events = lambda: self.db.get_face_events(limit=200)

    def ordered(self):
        """按写入先后排序（接口默认按 id 倒序）。"""
        return list(reversed(self.events()))

    def test_every_round_leaves_a_row_but_debounce_drops_the_repeat_action(self):
        for _ in range(3):
            self.guard.handle_face_result("alice-face", device_source="face_watcher")
        events = self.events()
        # (a) 同一人三轮识别 = 三行历史（可解释「站了 30 秒为什么这么多条」）
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e["status"] == "granted" for e in events))
        # 去抖只挡重复开门/记账动作：通行日志只有第一条
        self.assertEqual(len(face_rows(self.db)), 1)

    def test_strangers_do_not_merge_into_one_row(self):
        for _ in range(3):
            self.guard.handle_face_result("", device_source="face_watcher")
        events = self.events()
        # (b) 空 face_id 不再被去抖合并成一条，三个陌生轮次各自成行
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e["status"] == "denied" for e in events))
        self.assertTrue(all(e["deny_reason"] == "unmatched_face" for e in events))

    def test_grant_is_the_final_status_in_a_single_write(self):
        result = self.guard.handle_face_result("alice-face")
        latest = self.db.get_latest_face_event()
        # (c) 放行瞬间读到的就是终态，不是 pending 中间态
        self.assertEqual(latest["status"], "granted")
        self.assertEqual(latest["verified"], 1)
        self.assertIsNone(latest["deny_reason"])
        self.assertEqual(latest["id"], result["event_id"])
        self.assertFalse(result["duplicate"])
        self.assertEqual([e for e in self.events() if e["status"] == "pending"], [])

    def test_denied_row_carries_its_reason_in_the_same_write(self):
        outcome = self.guard.handle_face_result("")
        latest = self.db.get_latest_face_event()
        self.assertEqual(latest["status"], "denied")
        self.assertEqual(latest["verified"], 0)
        self.assertEqual(latest["deny_reason"], "unmatched_face")
        self.assertFalse(outcome["granted"])
        self.assertIsNone(outcome["person"])

    def test_record_only_keeps_history_without_opening(self):
        sink = []
        self.guard.event_sink = sink.append
        self.guard.handle_face_result("alice-face", device_source="web",
                                      record_only=True)
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "granted")
        self.assertEqual(events[0]["device_source"], "web")
        # 只留痕：不广播门禁事件、不写通行日志、不开门
        self.assertEqual(face_rows(self.db), [])
        self.assertEqual(sink, [])

    def test_zero_repeat_window_keeps_every_action(self):
        self.guard.configure({"face": {"watcher": {"repeat_window": 0}}})
        for _ in range(2):
            self.guard.handle_face_result("alice-face")
        self.assertEqual(len(self.events()), 2)
        self.assertEqual(len(face_rows(self.db)), 2)

    def test_repeat_window_falls_back_on_bad_config(self):
        self.guard.configure({"face": {"watcher": {"repeat_window": "oops"}}})
        self.assertEqual(self.guard.repeat_window, REPEAT_WINDOW_S)


class ObservationTests(unittest.TestCase):
    """观测轮次（太远/节流/无脸…）留痕，环境类只在种类变化时留一行。"""

    def setUp(self):
        self.db = temp_db()
        self.guard = AccessGuard(self.db)
        enroll(self.db, "爱丽丝", "alice-face")

    def ordered_kinds(self):
        return [e["deny_reason"] for e in
                reversed(self.db.get_face_events(limit=200))]

    def test_non_ambient_observations_are_recorded_every_round(self):
        for kind in ("too_far", "throttled", "no_face"):
            self.assertIsNotNone(self.guard.record_observation(kind))
        events = self.db.get_face_events(limit=200)
        self.assertEqual(self.ordered_kinds(), ["too_far", "throttled", "no_face"])
        self.assertTrue(all(e["status"] == "observed" for e in events))
        self.assertTrue(all(e["verified"] == 0 for e in events))
        self.assertTrue(all(e["device_source"] == "face_watcher" for e in events))

    def test_ambient_observations_only_record_on_change(self):
        for _ in range(5):
            self.guard.record_observation("idle")
        self.assertEqual(len(self.db.get_face_events()), 1)
        self.assertIsNotNone(self.guard.record_observation("no_camera"))
        self.assertIsNotNone(self.guard.record_observation("idle"))
        self.assertEqual(self.ordered_kinds(), ["idle", "no_camera", "idle"])
        # 变化后再重复同一环境状态，仍然被去抖吞掉
        self.assertIsNone(self.guard.record_observation("idle"))

    def test_a_match_splits_the_ambient_sequence(self):
        self.guard.record_observation("idle")
        self.guard.handle_face_result("alice-face")
        self.guard.record_observation("idle")
        # 中间那条是判定事件（granted → deny_reason 为空），两侧各留一段 idle
        self.assertEqual(self.ordered_kinds(), ["idle", None, "idle"])


class FaceWatcherObservationTests(unittest.TestCase):
    """哨兵逐轮次的留痕与冷却期补记。"""

    def setUp(self):
        self.db = temp_db()
        self.guard = AccessGuard(self.db)
        enroll(self.db, "爱丽丝", "alice-face")

    def latest(self):
        return self.db.get_latest_face_event()

    def test_no_face_round_is_recorded_as_observed(self):
        watcher = make_watcher(
            FakeEngine({"detected": False, "faces": [], "mode": "yolov8"}),
            self.guard)
        note = watcher.inspect_once()
        self.assertEqual(note["kind"], "no_face")
        self.assertEqual(self.latest()["status"], "observed")
        self.assertEqual(self.latest()["deny_reason"], "no_face")

    def test_throttled_round_is_recorded_as_observed(self):
        watcher = make_watcher(
            FakeEngine({"detected": False, "faces": [], "mode": "throttled"}),
            self.guard)
        self.assertEqual(watcher.inspect_once()["kind"], "throttled")
        self.assertEqual(self.latest()["deny_reason"], "throttled")

    def test_too_far_round_is_recorded_as_observed(self):
        watcher = make_watcher(FakeEngine(detected("", side=20)),
                               self.guard, min_face_px=60)
        self.assertEqual(watcher.inspect_once()["kind"], "too_far")
        self.assertEqual(self.latest()["deny_reason"], "too_far")

    def test_idle_round_is_recorded_as_observed(self):
        # 让门控「见过 motion 但此刻不在保持窗口」：motion_hold=0 + 一次 motion=false
        watcher = make_watcher(FakeEngine({"detected": False, "faces": []}),
                               self.guard, motion_gate=True, motion_hold=0)
        watcher.on_snapshot({"motion": False})
        self.assertEqual(watcher.inspect_once()["kind"], "idle")
        self.assertEqual(self.latest()["deny_reason"], "idle")

    def test_no_identity_round_is_recorded_once(self):
        engine = FakeEngine({"detected": False, "faces": []})
        engine.identity_count = lambda: 0
        watcher = make_watcher(engine, self.guard)
        for _ in range(3):
            self.assertEqual(watcher.inspect_once()["kind"], "no_identity")
        # 环境类观测按种类去抖：连跑三轮只留一条
        self.assertEqual(len(self.db.get_face_events()), 1)

    def test_grant_then_cooldown_records_without_reopening(self):
        watcher = make_watcher(FakeEngine(detected("alice-face")),
                               self.guard, cooldown=60)
        self.assertEqual(watcher.inspect_once()["kind"], "granted")
        # 人还在门口站着：第二轮落 cooldown，但历史照样补记（record_only）
        self.assertEqual(watcher.inspect_once()["kind"], "cooldown")
        events = self.db.get_face_events(limit=200)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["status"] == "granted" for e in events))
        # 冷却期只挡动作：只开了一次门
        self.assertEqual(len(face_rows(self.db)), 1)

    def test_stranger_round_is_denied_and_logged(self):
        watcher = make_watcher(FakeEngine(detected("")), self.guard)
        note = watcher.inspect_once()
        self.assertEqual(note["kind"], "denied")
        self.assertEqual(self.latest()["status"], "denied")
        self.assertEqual(len(face_rows(self.db)), 1)


class RecognizeRouteTests(unittest.TestCase):
    """`POST /api/face/recognize` 与 docs/api.md 一致：留痕但不开门。"""

    def setUp(self):
        self.db = temp_db()
        self.guard = AccessGuard(self.db)
        enroll(self.db, "爱丽丝", "alice-face")
        self.app = Flask(__name__)
        self.sink = []
        self.guard.event_sink = self.sink.append

    def call(self, result):
        engine = SimpleNamespace(recognize_from_base64=lambda b64: dict(result))
        with patch.object(face_api, "face_engine", engine), \
                patch.object(face_api, "access_guard", self.guard):
            with self.app.test_request_context(
                    "/api/face/recognize", method="POST",
                    json={"image": base64.b64encode(b"jpeg").decode()}):
                return face_api.face_recognize()

    def test_matched_frame_is_recorded_but_never_opens(self):
        result = self.call({"detected": True, "face_id": "alice-face",
                            "score": 0.9, "confidence": 0.95})
        self.assertEqual(result.get_json()["face_id"], "alice-face")
        events = self.db.get_face_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["device_source"], "web")
        self.assertEqual(events[0]["status"], "granted")
        self.assertEqual(face_rows(self.db), [])
        self.assertEqual(self.sink, [])

    def test_empty_frame_is_recorded_as_observed(self):
        self.call({"detected": False, "faces": [], "mode": "yolov8"})
        latest = self.db.get_latest_face_event()
        self.assertEqual(latest["status"], "observed")
        self.assertEqual(latest["deny_reason"], "no_face")
        self.assertEqual(face_rows(self.db), [])

    def test_throttled_frame_is_recorded_as_observed(self):
        self.call({"detected": False, "faces": [], "mode": "throttled"})
        self.assertEqual(self.db.get_latest_face_event()["deny_reason"], "throttled")

    def test_error_result_is_not_persisted(self):
        self.call({"error": "模型未加载"})
        self.assertEqual(self.db.get_face_events(), [])


if __name__ == "__main__":
    unittest.main()
