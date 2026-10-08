"""Remote 1–4 event routing, toggling and migration; no serial hardware."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from web.automation.engine import AutomationEngine


class RemoteBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Mock(online=True)
        for name in ('control_light', 'control_fan', 'control_door', 'control_window'):
            getattr(self.bridge, name).return_value = (True, 'ok')
        self.status = dict(light_status='off', light_brightness=0, fan_speed=0,
                           door_status='closed', window_status='closed')
        self.db = Mock()
        self.db.get_current_status.side_effect = lambda: dict(self.status)
        self.db.update_status.side_effect = lambda **kw: self.status.update(kw)
        self.engine = AutomationEngine(self.bridge, self.db, Path(self.temp.name) / 'rules.json')
        self.engine.load()
        self.addCleanup(self.engine.stop)
        self.engine._snapshot = dict(rain=False, smoke=False, motion=False, temperature=20, light=800)
        self.engine._snapshot_ts = time.time()

    def press(self, command):
        fired = []
        def run(rule, reason):
            fired.append(rule['preset'])
            branch = rule['actions'] if self.engine._conditions_hold(rule, self.engine._context()) else rule['else_actions']
            for action in branch:
                ok, msg = self.engine._perform(action, rule)
                if not ok:
                    break
        with patch.object(self.engine, '_fire', side_effect=run):
            self.engine.on_event(dict(event='ir', address=0, command=command))
        return fired

    def test_four_keys_toggle_independently(self):
        for cmd, device, field, opened, closed in [
            (0x45, 'light', 'light_status', 'on', 'off'),
            (0x46, 'fan', 'fan_speed', 60, 0),
            (0x47, 'door', 'door_status', 'open', 'closed'),
            (0x44, 'window', 'window_status', 'open', 'closed'),
        ]:
            with self.subTest(device=device):
                before = dict(self.status)
                self.assertEqual(self.press(cmd), [f'ir_remote_{device}_toggle'])
                self.assertEqual(self.status[field], opened)
                self.press(cmd)
                self.assertEqual(self.status[field], closed)
                for other in ('light_status', 'fan_speed', 'door_status', 'window_status'):
                    if other != field:
                        self.assertEqual(self.status[other], before[other])
        self.assertEqual(self.press(0x40), [])

    def test_normal_rules_yield_but_hazard_still_closes_window(self):
        self.press(0x45)
        self.press(0x46)
        self.press(0x44)
        rules = {r['preset']: r for r in self.engine.rules}
        self.engine.global_state.set_value('g:有人在家', False)
        ctx = self.engine._context()
        for pid in ('away_close_all', 'window_normal', 'light_off', 'temp_cool'):
            self.assertFalse(self.engine._conditions_hold(rules[pid], ctx))
        for hazard in ('rain', 'smoke'):
            self.engine._snapshot[hazard] = True
            self.assertTrue(self.engine._conditions_hold(rules['rain_window'], self.engine._context()))
            for action in rules['rain_window']['actions']:
                self.assertTrue(self.engine._perform(action)[0])
            self.assertEqual(self.status['window_status'], 'closed')
            self.press(0x44)
            self.assertEqual(self.status['window_status'], 'closed')
            self.engine._snapshot[hazard] = False

    def test_upgrade_replaces_old_key1_and_preserves_user_edits(self):
        rules = [copy.deepcopy(r) for r in self.engine.rules if not r['preset'].startswith('ir_remote_')]
        for r in rules:
            if r['preset'] in ('away_close_all', 'window_normal'):
                r['conditions'] = [c for c in r['conditions'] if not c['sensor'].startswith('g:手动优先_')]
            if r['preset'] == 'temp_hot':
                r['name'] = 'My temperature rule'
        rules.append(dict(id='old-ir', preset='ir_fan_toggle', name='Old key1', enabled=True,
                          trigger=dict(kind='event', event='ir', command='0x45'),
                          actions=[dict(device='fan', op='toggle', speed=60)]))
        self.engine.rules_path.write_text(json.dumps(dict(presets_version=7, rules=rules)), encoding='utf-8')
        self.engine.load()
        current = {r['preset']: r for r in self.engine.rules}
        self.assertNotIn('ir_fan_toggle', current)
        self.assertEqual(current['temp_hot']['name'], 'My temperature rule')
        self.assertEqual(self.press(0x45), ['ir_remote_light_toggle'])
        self.assertEqual(self.press(0x46), ['ir_remote_fan_toggle'])
        self.engine.load()
        self.assertEqual(len([r for r in self.engine.rules if r['preset'].startswith('ir_remote_')]), 4)


if __name__ == '__main__':
    unittest.main()

