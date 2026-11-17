import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from web.automation.engine import AutomationEngine
from web.automation.schema import validate_rule


class FanTemperatureRuleTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'examples/automation/fan-temperature-26.json'
        self.rules = [validate_rule(r) for r in json.loads(path.read_text(encoding='utf-8'))['rules']]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = Mock(online=True)
        self.bridge.control_fan.return_value = (True, 'ok')
        self.status = {'fan_speed': 0}
        db = Mock()
        db.get_current_status.side_effect = lambda: dict(self.status)
        db.update_status.side_effect = lambda **kw: self.status.update(kw)
        self.engine = AutomationEngine(self.bridge, db, Path(self.tmp.name) / 'rules.json')

    def matches(self, temperature, fresh=True):
        ctx = {'temperature': temperature, 'sensor_fresh': fresh}
        return [self.engine._conditions_hold(rule, ctx) for rule in self.rules]

    def test_exact_threshold_has_one_unambiguous_branch(self):
        for temperature, expected in [(-5, [False, True]), (25.9, [False, True]),
                                      (26, [False, True]), (26.1, [True, False]),
                                      (40, [True, False])]:
            with self.subTest(temperature=temperature):
                self.assertEqual(self.matches(temperature), expected)

    def test_missing_or_stale_sensor_never_runs_either_branch(self):
        self.assertEqual(self.matches(None), [False, False])
        self.assertEqual(self.matches(float('nan')), [False, False])
        for temperature in (22, 30):
            self.assertEqual(self.matches(temperature, fresh=False), [False, False])

    def test_temperature_sequence_controls_on_then_off(self):
        for temperature in (27, 26):
            for rule, match in zip(self.rules, self.matches(temperature)):
                if match:
                    ok, _ = self.engine._perform(rule['actions'][0], rule)
                    self.assertTrue(ok)
        self.assertEqual([c.args for c in self.bridge.control_fan.call_args_list], [(100,), (0,)])
        self.assertEqual(self.status['fan_speed'], 0)
