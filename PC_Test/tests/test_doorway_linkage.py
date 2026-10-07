import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from web.automation.engine import AutomationEngine
from web.automation.schema import validate_rule, validate_condition, ValidationError
from web.doorway import DoorwayDistance
from web.security_monitor import SecurityMonitor


class DoorwayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db = Mock()
        db.get_current_status.return_value = {}
        self.engine = AutomationEngine(Mock(online=False), db, Path(self.tmp.name)/'rules.json')
        self.rule = validate_rule(dict(id='doorway', name='门口拍照', enabled=True,
            trigger=dict(kind='sensor', sensor='distance_cm', op='<', value=50, hold_sec=2),
            conditions=[], actions=[dict(device='camera', action='snapshot')], cooldown=0))
        self.engine.rules = [self.rule]
        self.timer = patch('web.doorway.time.monotonic', return_value=100)
        self.clock = self.timer.start()
        self.addCleanup(self.timer.stop)
        self.fire_patch = patch.object(self.engine, '_fire')
        self.fire = self.fire_patch.start()
        self.addCleanup(self.fire_patch.stop)

    def feed(self, at, value=20):
        self.clock.return_value = at
        self.engine.on_distance(dict(valid=value is not None, status='ok', distance_cm=value))

    def test_boundary_and_one_photo_per_visit(self):
        self.feed(100, 50)
        self.feed(101, 49)
        self.feed(102.99, 49)
        self.fire.assert_not_called()
        self.feed(103, 49)
        self.feed(104, 10)
        self.assertEqual(self.fire.call_count, 1)
        self.feed(105, 60)
        self.feed(106)
        self.feed(108)
        self.assertEqual(self.fire.call_count, 2)

    def test_startup_counts_full_hold(self):
        self.feed(100)
        self.feed(101.99)
        self.fire.assert_not_called()
        self.feed(102)
        self.fire.assert_called_once()

    def test_invalid_resets_hold(self):
        self.feed(100)
        self.feed(101, None)
        self.feed(102)
        self.feed(103.99)
        self.fire.assert_not_called()
        self.feed(104)
        self.fire.assert_called_once()

    def test_long_gap_requires_new_hold(self):
        self.feed(100)
        self.feed(104)
        self.feed(105)
        self.fire.assert_not_called()
        self.feed(106)
        self.fire.assert_called_once()

    def test_a_board_cannot_refresh_distance_or_advance_hold(self):
        self.feed(100)
        self.clock.return_value = 102
        self.engine.on_snapshot({'temperature': 22})
        self.fire.assert_not_called()
        self.feed(102)
        self.fire.assert_called_once()
        self.clock.return_value = 106
        self.engine.on_snapshot({'temperature': 24})
        self.assertIsNone(self.engine._context()['distance_cm'])

    def test_distance_does_not_refresh_a_board(self):
        self.engine._snapshot = {'temperature': 22}
        self.engine._snapshot_ts = 1
        self.feed(100)
        self.assertNotIn('temperature', self.engine._context())

    def test_bad_measurements(self):
        for value in (None, True, '20', 0, 401, float('nan'), float('inf')):
            self.feed(100, value)
            self.assertFalse(self.engine.doorway.snapshot()['valid'])
        self.feed(100)
        self.clock.return_value = 103.01
        self.assertIsNone(self.engine.doorway.snapshot()['distance_cm'])

    def test_threshold_validation(self):
        for value in (True, '20', 0, 401, float('nan'), float('inf')):
            with self.assertRaises(ValidationError):
                validate_condition(dict(sensor='distance_cm', op='<', value=value))

    def test_camera_success_and_failure_persist(self):
        monitor = SecurityMonitor(Path(self.tmp.name)/'photos',
                                  {'camera': {'stream_url': 'http://camera/video_feed'}})
        self.engine.capture_photo = monitor.capture_rule
        self.feed(100)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'\xff\xd8photo\xff\xd9'
        with patch('web.security_monitor.urllib.request.urlopen', return_value=response):
            self.assertTrue(self.engine._perform(self.rule['actions'][0], self.rule)[0])
        event = monitor.events()[0]
        self.assertTrue((monitor.directory/event['image']).exists())
        self.assertEqual(event['details']['distance_cm'], 20)
        self.assertEqual(event['details']['trigger']['hold_sec'], 2)
        with patch('web.security_monitor.urllib.request.urlopen', side_effect=TimeoutError('offline')):
            self.assertFalse(self.engine._perform(self.rule['actions'][0], self.rule)[0])
        self.assertTrue(any(e['capture'] == 'failed' for e in monitor.events()))

    def test_saved_rule_retains_custom_parameters(self):
        self.rule['trigger'].update(value=85, hold_sec=7)
        self.engine.save_rules([self.rule])
        self.engine.load()
        rule = next(r for r in self.engine.rules if r['id'] == 'doorway')
        self.assertEqual(rule['trigger']['value'], 85)
        self.assertEqual(rule['trigger']['hold_sec'], 7)

    def test_editing_hold_starts_new_interval(self):
        import copy
        self.feed(100)
        edited = copy.deepcopy(self.rule)
        edited['trigger']['hold_sec'] = 3
        self.engine.save_rules([edited])
        self.feed(102)
        self.feed(104)
        self.fire.assert_not_called()
        self.feed(105)
        self.fire.assert_called_once()

    def test_storage_failure_returns_failed_action(self):
        self.engine.capture_photo = Mock(side_effect=OSError('disk full'))
        ok, message = self.engine._perform(self.rule['actions'][0], self.rule)
        self.assertFalse(ok)
        self.assertIn('disk full', message)


class DistancePollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_and_shutdown_never_open_serial(self):
        from web.hardware import McpHardwareBridge
        bridge = McpHardwareBridge({}, Mock())
        bridge.tool_schemas = [{'name': 'get_distance'}]
        values = []
        def listener(value):
            values.append(value)
            bridge._stopping = True
        bridge.add_listener('distance', listener)
        async def call(session, name, args):
            self.assertEqual(name, 'get_distance')
            return json.dumps(dict(valid=True, status='ok', distance_cm=21))
        bridge._call = call
        await bridge._distance_loop(None)
        self.assertEqual(values[0]['distance_cm'], 21)
        self.assertEqual(values[-1], {})
