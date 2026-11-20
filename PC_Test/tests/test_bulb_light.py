import unittest
from unittest.mock import Mock, patch
from web.bulb_light import BulbLightLink, activate_light


class BulbLightTests(unittest.TestCase):
    def test_camera_hit_and_cooldown(self):
        link = BulbLightLink()
        action = Mock(return_value=(True, 'ack'))
        hit = [{'label': 'light bulb'}]
        self.assertEqual(link.process(hit, True, True, action)['state'], 'success')
        self.assertEqual(link.process(hit, True, True, action)['state'], 'cooldown')
        action.assert_called_once()

    def test_disabled_upload_and_other_class_do_not_actuate(self):
        link = BulbLightLink()
        action = Mock()
        hit = [{'label': 'light bulb'}]
        link.process(hit, False, True, action)
        link.process(hit, True, False, action)
        link.process([{'label': 'drone'}], True, True, action)
        action.assert_not_called()

    @patch('web.bulb_light.activate_light', return_value=(True, 'ack'))
    @patch('web.extensions.db')
    @patch('web.extensions.automation')
    def test_continuous_hit_miss_and_manual_takeover(self, engine, db, activate):
        import threading
        engine.output_locks = {'light': threading.RLock()}
        engine.output_holds = {}
        db.get_current_status.return_value = {'light_status':'off'}
        link = BulbLightLink()
        hit = [{'label':'light bulb'}]
        for frame in [hit, hit, [], []]:
            link.follow(frame, 1, 5, lambda: True)
        self.assertEqual([c.args[0] for c in activate.call_args_list], ['on', 'off'])
        link.follow(hit, 1, 5, lambda: True)
        engine.output_holds.clear()
        link.follow([], 1, 5, lambda: True)
        self.assertEqual(activate.call_count, 3)

    def test_failure_is_reported_and_throttled(self):
        link = BulbLightLink()
        action = Mock(return_value=(False, 'offline'))
        self.assertEqual(link.process([{'label':'light bulb'}], True, True, action),
                         {'state':'failed', 'message':'offline'})
        self.assertEqual(link.process([{'label':'light bulb'}], True, True, action)['state'], 'cooldown')

    @patch('web.extensions.bridge')
    @patch('web.extensions.db')
    def test_failed_hardware_does_not_write_success(self, db, bridge):
        db.get_current_status.return_value = {'light_status':'off', 'light_brightness':0}
        bridge.control_light.return_value = (False, 'offline')
        ok, _ = activate_light()
        self.assertFalse(ok)
        db.update_status.assert_not_called()
        db.add_light_event.assert_not_called()
