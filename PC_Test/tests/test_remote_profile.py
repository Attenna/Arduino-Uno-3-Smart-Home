import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from web.automation.engine import AutomationEngine
from web.automation.remote_profile import configure_remote, is_ir_rule
from web.automation.schema import validate_rule


class RemoteProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = Mock(online=True)
        for name in ('control_fan', 'control_light', 'control_light_color', 'call_tool'):
            getattr(self.bridge, name).return_value = (True, 'ok')
        self.status = {'fan_speed': 0, 'light_status': 'off', 'light_brightness': 0}
        db = Mock()
        db.get_current_status.side_effect = lambda: dict(self.status)
        db.update_status.side_effect = lambda **kw: self.status.update(kw)
        self.engine = AutomationEngine(self.bridge, db, Path(self.tmp.name) / 'rules.json')
        self.engine.load()
        self.addCleanup(self.engine.stop)
        # Runtime uses the exact-26 rules instead of the older occupied-home fan rules.
        for rule in self.engine.rules:
            if not is_ir_rule(rule) and any(a.get('device') == 'fan'
                    for a in rule.get('actions', []) + rule.get('else_actions', [])):
                rule['enabled'] = False
        self.document = {'presets_version': 10, 'presets_seen': sorted(self.engine._presets_seen),
                         'rules': copy.deepcopy(self.engine.rules)}
        self.profile, _ = configure_remote(self.document)
        self.engine.rules = self.profile['rules']

    def press(self, command):
        fired = []
        def perform(rule, reason):
            fired.append(rule)
            branch = (rule['actions'] if self.engine._conditions_hold(rule, self.engine._context())
                      else rule['else_actions'])
            for action in branch:
                ok, message = self.engine._perform(action, rule)
                self.assertTrue(ok, message)
        with patch.object(self.engine, '_fire', side_effect=perform):
            self.engine.on_event({'event': 'ir', 'address': 0, 'command': command})
        self.assertEqual(len(fired), 1)
        return fired[0]

    def thermal_matches(self, temperature):
        ctx = {'sensor_fresh': True, 'temperature': temperature,
               **self.engine.global_state.values()}
        return [self.engine._conditions_hold(r, ctx) for r in self.engine.rules
                if r['id'] in ('temp26on', 'temp26off')]

    def test_key2_latches_on_and_off_beyond_old_grace(self):
        self.press(0x46)
        self.assertEqual(self.status['fan_speed'], 100)
        # The existing 30-second clear rule may clear this flag; it must not restore auto.
        self.engine.global_state.set_value('g:手动优先_风扇', False)
        for temp in (22, 26, 30):
            self.assertEqual(self.thermal_matches(temp), [False, False])
        self.press(0x46)
        self.assertEqual(self.status['fan_speed'], 0)
        self.assertEqual(self.thermal_matches(30), [False, False])
        self.assertEqual([c.args for c in self.bridge.control_fan.call_args_list], [(100,), (0,)])

    def test_key5_restores_exact_26_automatic_control(self):
        self.press(0x46)
        self.press(0x40)
        self.assertEqual(self.thermal_matches(26), [False, True])
        self.assertEqual(self.thermal_matches(26.1), [True, False])
        self.assertFalse(self.engine.global_state.values()['g:手动优先_风扇'])

    def test_light_levels_and_off_keep_manual_light_priority(self):
        for code, percent in ((0x07, 25), (0x15, 60), (0x09, 100)):
            self.press(code)
            self.assertEqual(self.status['light_brightness'], percent)
            self.assertTrue(self.engine.global_state.values()['g:手动优先_灯'])
        self.press(0x19)
        self.assertEqual(self.status['light_status'], 'off')
        self.bridge.control_fan.assert_not_called()

    def test_key6_only_short_beep_and_no_voice_actions(self):
        self.press(0x43)
        self.bridge.call_tool.assert_called_once_with('buzzer',
            {'action': 'beep', 'count': 1, 'on_ms': 100, 'off_ms': 100})
        remote = [r for r in self.engine.rules if is_ir_rule(r)]
        self.assertEqual(len(remote), 10)
        self.assertEqual(len({int(r['trigger']['command'], 16) for r in remote}), 10)
        self.assertFalse(any(a['device'] == 'voice' for r in remote
                             for a in r['actions'] + r['else_actions']))
        for rule in remote:
            validate_rule(rule)

    def test_offline_cli_has_no_web_database_side_effect(self):
        # Deliberately omit Flask/ONNX/etc. from this subprocess's import search path:
        # -S excludes site packages. A pure JSON tool needs only the standard library.
        cli = Path(__file__).resolve().parents[1] / 'scripts/configure_ir_remote.py'
        source, output = Path(self.tmp.name) / 'input.json', Path(self.tmp.name) / 'output.json'
        source.write_text(json.dumps(self.document), encoding='utf-8')
        result = subprocess.run([sys.executable, '-S', str(cli), '--input', str(source),
                                 '--output', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text(encoding='utf-8')), self.profile)

    def test_legacy_voice_and_english_ir_rules_are_replaced(self):
        for rule_id, code, device in [('voiceold', '0x45', 'voice'),
                                      ('lightold', '0x15', 'light')]:
            self.document['rules'].append({'id': rule_id, 'name': rule_id, 'enabled': True,
                'trigger': {'kind': 'event', 'event': 'ir', 'command': code},
                'actions': [{'device': device}]})
        result, removed = configure_remote(self.document)
        self.assertIn('voiceold', removed)
        self.assertIn('lightold', removed)
        self.assertEqual(len([r for r in result['rules'] if is_ir_rule(r)]), 10)

    def test_install_is_idempotent_preserves_other_rules_and_original(self):
        original = copy.deepcopy(self.document)
        first, removed = configure_remote(self.document)
        self.assertEqual(self.document, original)
        second, _ = configure_remote(first)
        self.assertEqual(first, second)
        self.assertEqual(len(removed), 4)
        other = [r for r in original['rules'] if not is_ir_rule(r)]
        self.assertEqual(first['rules'][:len(other)], other)
        old_ids = {r['preset']: r['id'] for r in original['rules'] if is_ir_rule(r)}
        for r in first['rules']:
            if r.get('preset') in old_ids:
                self.assertEqual(r['id'], old_ids[r['preset']])

    def test_conflicting_fan_automation_rejected_without_mutation(self):
        self.document['rules'].append({'id': 'otherfan', 'name': 'Other fan', 'enabled': True,
            'trigger': {'kind': 'interval', 'seconds': 2},
            'actions': [{'device': 'fan', 'op': 'off', 'speed': 0}]})
        original = copy.deepcopy(self.document)
        with self.assertRaisesRegex(ValueError, '其他自动风扇'):
            configure_remote(self.document)
        self.assertEqual(self.document, original)

    def test_reload_does_not_restore_removed_same_key_voice_rule(self):
        self.engine.rules_path.write_text(json.dumps(self.profile), encoding='utf-8')
        self.engine.load()
        self.assertEqual(len([r for r in self.engine.rules if is_ir_rule(r)]), 10)
        self.press(0x45)


if __name__ == '__main__':
    unittest.main()
