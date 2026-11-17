import unittest
from unittest.mock import Mock

from web.automation.light_feedback import LightFeedbackGuard
from web.hardware import McpHardwareBridge, normalize_output_state, readback_status
from web.readback import output_mismatch


OFF = {"light_status": "off", "light_brightness": 0}
ON = {"light_status": "on", "light_brightness": 100, "light_mode": "white"}


class LightFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.guard = LightFeedbackGuard()

    def test_own_illumination_does_not_change_dark_ambient(self):
        self.assertEqual(self.guard.update(796, OFF, 1), 796)
        self.assertIsNone(self.guard.update(796, ON, 1))
        for sample in range(2, 20):
            self.assertEqual(self.guard.update(550, ON, sample), 796)

    def test_actual_daylight_still_allows_automatic_off(self):
        self.guard.update(796, OFF, 1)
        self.guard.update(550, ON, 2)
        self.guard.update(550, ON, 3)
        self.assertLessEqual(self.guard.update(400, ON, 4), 670)
        self.assertEqual(self.guard.update(640, OFF, 5), 640)

    def test_first_partly_illuminated_sample_cannot_underestimate_feedback(self):
        self.guard.update(800, OFF, 1)
        self.guard.update(700, ON, 2)
        # Re-evaluating one frame must not count as the second sample.
        self.guard.update(700, ON, 2)
        self.guard.update(500, ON, 3)
        self.assertEqual(self.guard.update(500, ON, 4), 800)

    def test_brightness_change_relearns_contribution_from_new_sample(self):
        self.guard.update(796, OFF, 1)
        self.guard.update(550, ON, 2)
        dim = dict(ON, light_brightness=30)
        self.assertIsNone(self.guard.update(550, dim, 2))
        self.assertEqual(self.guard.update(700, dim, 3), 796)

    def test_restart_with_lamp_on_does_not_invent_off_baseline(self):
        for sample in range(1, 10):
            self.assertIsNone(self.guard.update(550, ON, sample))
        self.assertEqual(self.guard.update(800, OFF, 10), 800)
        self.assertEqual(self.guard.update(500, ON, 11), 800)

    def test_invalid_samples_do_not_corrupt_calibration(self):
        self.guard.update(796, OFF, 1)
        for raw in (True, None, float('nan'), float('inf'), -1, 1024):
            self.assertIsNone(self.guard.update(raw, ON, 2))
        self.assertEqual(self.guard.update(550, ON, 3), 796)


class BoardOwnershipTests(unittest.TestCase):
    def test_b_readback_clears_obsolete_light_channel(self):
        rb = normalize_output_state({"light": 0, "fan": 255, "door": "closed"})
        self.assertIsNone(rb['rb_light_brightness'])
        self.assertEqual(rb['rb_fan_speed'], 100)

    def test_old_b_light_readback_cannot_reconcile_a_lamp(self):
        self.assertEqual(readback_status({'rb_light_brightness': 0}), {})
        db = Mock()
        db.get_current_status.return_value = dict(ON, door_status='open')
        bridge = McpHardwareBridge({'serial': {'enabled': False}}, db)
        bridge._reconcile_after_reset({'rb_light_brightness': 0, 'rb_door_status': 'closed'}, 2)
        db.update_status.assert_called_once_with(door_status='closed')

    def test_legacy_b_light_value_does_not_raise_unapplied_warning(self):
        from datetime import datetime, timezone
        self.assertEqual(output_mismatch(dict(ON, rb_light_brightness=0,
            rb_seen_at=datetime.now(timezone.utc).isoformat())), [])
