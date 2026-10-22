"""A caller's panel roster is a session config, not a later guess."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


LIB = Path(__file__).resolve().parents[1] / 'plugins/review-council/scripts/lib/panel_request.py'


def load():
    spec = importlib.util.spec_from_file_location('panel_request_under_test', LIB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PanelRequestTests(unittest.TestCase):
    def setUp(self):
        self.panel = load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_four_luna_keeps_effort_and_drops_the_other_labs(self):
        request = self.panel.parse_panel_request('please use 4*luna for panels')
        self.assertEqual(request['codex_models'], ['latest-luna'] * 4)
        self.assertEqual(request['family'], 'luna')
        config = self.panel.session_config({
            'codex_models': ['latest-sol', 'latest-luna'],
            'codex_effort': 'xhigh',
            'claude_models': ['opus', 'sonnet'],
            'claude_seats': 1,
            'extras': True,
            'min_labs': 2,
            'quota_fallback': True,
        }, request)
        self.assertEqual(config['codex_models'], ['latest-luna'] * 4)
        self.assertEqual(config['codex_effort'], 'xhigh')
        self.assertEqual(config['claude_seats'], 0)
        self.assertNotIn('claude_models', config)
        self.assertFalse(config['extras'])
        self.assertEqual(config['min_labs'], 1)
        self.assertTrue(config['quota_fallback'])

    def test_spacing_and_latest_prefix_are_the_same_request(self):
        for text in ('4 x luna', '4×luna', 'use 4*latest-luna', '2*sol'):
            request = self.panel.parse_panel_request(text)
            self.assertIsNotNone(request, text)
        self.assertEqual(self.panel.parse_panel_request('2*sol')['codex_models'],
                         ['latest-sol', 'latest-sol'])
        self.assertIsNone(self.panel.parse_panel_request('review the branch'))

    def test_five_seats_and_two_rosters_are_refused(self):
        with self.assertRaises(ValueError):
            self.panel.parse_panel_request('5*luna')
        with self.assertRaises(ValueError):
            self.panel.parse_panel_request('4*luna and 2*sol')

    def test_write_leaves_the_user_config_untouched(self):
        session = Path(self.temp.name) / 'session'
        base = Path(self.temp.name) / 'config.json'
        original = '{"codex_models":["latest-sol"],"claude_models":["opus"]}\n'
        base.write_text(original)
        path = self.panel.write_session(session, 'use 4*luna for panels', base)
        self.assertEqual(base.read_text(), original)
        self.assertEqual(path, session / 'roster-config.json')
        saved = json.loads((session / 'panel-request.json').read_text())
        self.assertEqual(saved['count'], 4)
        self.assertEqual(json.loads(path.read_text())['codex_models'], ['latest-luna'] * 4)
        self.assertIsNone(self.panel.write_session(session, 'no roster here', base))
