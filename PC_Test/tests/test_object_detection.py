"""验证模型后处理及命中事件持久化，不接触真实硬件。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from web.api.objects import ObjectService


class ObjectPersistenceTests(unittest.TestCase):
    def test_evidence_survives_service_restart_and_cooldown(self):
        result = {'time': '2026-11-16T00:00:00+00:00', 'detections': [
            {'class_id': 0, 'label': 'drones', 'confidence': .9, 'box': [1, 2, 30, 40]}]}
        with tempfile.TemporaryDirectory() as directory, patch('web.api.objects.ObjectDetector') as detector:
            detector.return_value.detect.side_effect = lambda _: dict(result)
            service = ObjectService('unused', Path(directory))
            first = service.run(b'fixture-jpeg', True)
            self.assertIsNotNone(first['event_id'])
            self.assertIsNone(service.run(b'fixture-jpeg', True)['event_id'])
            restarted = ObjectService('unused', Path(directory))
            with restarted.connect() as db:
                rows = db.execute('SELECT * FROM object_events').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual((restarted.directory / rows[0]['image_name']).read_bytes(), b'fixture-jpeg')

    def test_no_detection_creates_no_event_or_image(self):
        with tempfile.TemporaryDirectory() as directory, patch('web.api.objects.ObjectDetector') as detector:
            detector.return_value.detect.return_value = {'time': 'now', 'detections': []}
            service = ObjectService('unused', Path(directory))
            service.run(b'fixture', True)
            with service.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM object_events').fetchone()[0], 0)
            self.assertEqual(list(service.directory.iterdir()), [])
