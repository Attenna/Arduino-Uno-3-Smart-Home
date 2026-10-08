"""五点对齐与 ArcFace 分数事件的回归测试。"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.database import SmartHomeDB
from web.face.detector import FaceDetection, extract_five_landmarks
from web.face.recognizer import (ARCFACE_TEMPLATE_112, align_face_5point,
                                 estimate_face_alignment,
                                 prepare_detected_face)


class FaceAlignmentTests(unittest.TestCase):
    def test_similarity_transform_maps_landmarks_to_arcface_template(self):
        source = ARCFACE_TEMPLATE_112 * 1.35 + np.array([17.0, 23.0], dtype=np.float32)
        matrix = estimate_face_alignment(source)
        self.assertIsNotNone(matrix)
        mapped = cv2.transform(source.reshape(1, 5, 2), matrix).reshape(5, 2)
        np.testing.assert_allclose(mapped, ARCFACE_TEMPLATE_112, atol=0.2)

    def test_alignment_returns_arcface_input_size(self):
        image = np.full((220, 220, 3), 127, dtype=np.uint8)
        landmarks = ARCFACE_TEMPLATE_112 * 1.4 + np.array([20.0, 25.0])
        aligned = align_face_5point(image, landmarks)
        self.assertEqual(aligned.shape, (112, 112, 3))

    def test_prepare_face_falls_back_to_bbox_without_landmarks(self):
        image = np.zeros((100, 120, 3), dtype=np.uint8)
        detection = FaceDetection((10, 20, 70, 90), 0.9, 0)
        face, aligned = prepare_detected_face(image, detection)
        self.assertFalse(aligned)
        self.assertEqual(face.shape, (70, 60, 3))

    def test_detector_extracts_five_points(self):
        result = type("Result", (), {
            "keypoints": type("Keypoints", (), {
                "xy": np.asarray([ARCFACE_TEMPLATE_112], dtype=np.float32),
            })(),
        })()
        points = extract_five_landmarks(result, 0)
        self.assertEqual(len(points), 5)
        self.assertAlmostEqual(points[2][0], float(ARCFACE_TEMPLATE_112[2, 0]))

    def test_invalid_landmarks_do_not_create_transform(self):
        self.assertIsNone(estimate_face_alignment(np.zeros((5, 2))))


class FaceEventScoreTests(unittest.TestCase):
    def test_arcface_score_and_detector_confidence_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = SmartHomeDB(Path(tmp) / "smart_home.db")
            db.add_face_event("c", person_name="C", score=0.713,
                              detection_confidence=0.982)
            event = db.get_latest_face_event()
        self.assertAlmostEqual(event["score"], 0.713)
        self.assertAlmostEqual(event["detection_confidence"], 0.982)
        self.assertIsNone(event["confidence"])

    def test_existing_face_event_table_gets_score_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE face_events (id INTEGER PRIMARY KEY, "
                    "timestamp TEXT, face_id TEXT, person_name TEXT, "
                    "confidence REAL, image_path TEXT, device_source TEXT, "
                    "status TEXT, verified INTEGER)")
            db = SmartHomeDB(path)
            with db.connection() as connection:
                columns = {
                    row["name"] for row in connection.execute(
                        "PRAGMA table_info(face_events)")
                }
        self.assertIn("score", columns)
        self.assertIn("detection_confidence", columns)


if __name__ == "__main__":
    unittest.main()
