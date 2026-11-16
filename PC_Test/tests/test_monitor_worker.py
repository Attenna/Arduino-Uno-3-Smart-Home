import unittest
from unittest.mock import Mock, patch
from web.monitor_worker import MonitorWorker


class MonitorWorkerTests(unittest.TestCase):
    def worker(self):
        worker = MonitorWorker(Mock())
        worker.thread = Mock()
        return worker

    def test_lease_blocks_second_owner_and_expiry_releases_it(self):
        worker = self.worker()
        with patch('web.monitor_worker.time.monotonic', return_value=100):
            worker.configure('one', True, {'faces':'true'})
            with self.assertRaises(RuntimeError):
                worker.configure('two', True, {})
        with patch('web.monitor_worker.time.monotonic', return_value=116):
            worker.configure('two', True, {})
            self.assertEqual(worker.owner, 'two')

    def test_stale_frame_and_stopped_results_are_removed(self):
        worker = self.worker()
        with patch('web.monitor_worker.time.monotonic', return_value=100):
            worker.configure('one', True, {})
            revision = worker.revision
            worker.result = {'detections': []}
            worker.result_started = 97
            self.assertIsNotNone(worker.snapshot()['result'])
            worker.result_started = 94
            self.assertIsNone(worker.snapshot()['result'])
            worker.configure('one', False, {})
            self.assertFalse(worker.current(revision))
            self.assertIsNone(worker.snapshot()['result'])

    def test_option_change_invalidates_pending_inference(self):
        worker = self.worker()
        worker.configure('one', True, {'bulb_light':'true'})
        revision = worker.revision
        worker.configure('one', True, {'bulb_light':'false'})
        self.assertFalse(worker.current(revision))
