"""A caller's panel roster is a session config, not a later guess."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROSTER = Path(__file__).resolve().parents[1] / 'plugins/review-council/scripts/lib/roster.py'


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
        self.assertEqual(json.loads(path.read_text())['exclude'], ['cursor-sdk', 'gemini'])
        plain = self.panel.write_session(session, 'no roster here', base, host='claude', grok_ready=False)
        self.assertEqual(plain, session / 'roster-config.json')
        normal = json.loads(plain.read_text())
        self.assertEqual(normal['codex_models'], ['latest-luna'] * 4)
        self.assertEqual(normal['panel_mode'], 'normal')
        recorded = json.loads((session / 'panel-request.json').read_text())
        self.assertEqual(recorded['chain'], ['luna', 'sonnet', 'sol', 'opus'])

    def test_high_effort_is_one_of_each_and_high_risk_is_not(self):
        self.assertEqual(self.panel.chosen_mode('review this, high-risk'), 'normal')
        self.assertEqual(self.panel.chosen_mode('/rev this_pr, high effort'), 'high')
        self.assertEqual(self.panel.chosen_mode('high effort, then normal effort'), 'normal')
        config = self.panel.mode_config({'codex_effort': 'max', 'quota_fallback': True}, 'high', 'claude', False)
        self.assertEqual(config['codex_models'], ['latest-sol', 'latest-luna'])
        self.assertEqual(config['claude_models'], ['opus', 'sonnet'])
        self.assertEqual(config['codex_effort'], 'max')
        self.assertNotIn('claude_seats', config)
        self.assertEqual(config['panel_mode'], 'high')
        cursor = self.panel.chain_for('cursor')
        self.assertEqual(cursor, ('grok', 'luna', 'sonnet', 'sol', 'opus'))
        self.assertEqual(self.panel.chain_for('codex'), ('luna', 'sonnet', 'sol', 'opus'))

    def test_cursor_normal_is_four_grok_and_falls_back_when_the_sdk_is_absent(self):
        ready = self.panel.mode_config({}, 'normal', 'cursor', True)
        self.assertEqual(ready['cursor_sdk_models'], ['latest-grok'] * 4)
        self.assertNotIn('codex_models', ready)
        self.assertEqual(ready['panel_fallback'], 'luna')
        self.assertIn('codex', ready['exclude'])
        missing = self.panel.mode_config({}, 'normal', 'cursor', False)
        self.assertEqual(missing['codex_models'], ['latest-luna'] * 4)
        self.assertNotIn('cursor_sdk_models', missing)
        with self.assertRaises(ValueError):
            self.panel.session_config({}, {'family': 'grok', 'count': 4}, host='cursor', grok_ready=False)
        explicit = self.panel.session_config({}, {'family': 'grok', 'count': 4}, host='cursor', grok_ready=True)
        self.assertNotIn('panel_fallback', explicit)

    def test_high_mode_substitutes_a_missing_partner_and_not_a_third_family(self):
        spec = importlib.util.spec_from_file_location('roster_under_test', ROSTER)
        roster = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roster)
        cfg = {'panel_mode': 'high', 'codex_models': ['gpt-5.6-sol', 'gpt-5.6-luna'],
               'claude_models': ['opus', 'sonnet']}
        sol = {'seat': 'codex-sol', 'adapter': 'codex', 'model': 'gpt-5.6-sol',
               'effort': 'xhigh', 'extra': False, 'lab': 'openai'}
        sonnet = {'seat': 'sonnet', 'adapter': 'claude', 'model': 'sonnet',
                  'effort': 'xhigh', 'extra': False, 'lab': 'anthropic'}
        luna = {'seat': 'codex-luna', 'adapter': 'codex', 'model': 'gpt-5.6-luna',
                'effort': 'xhigh', 'extra': False, 'lab': 'openai'}
        kept = [sol, sonnet, luna]
        excluded = []
        roster.substitute_high_pairs(kept, excluded, cfg)
        clones = [seat for seat in kept if seat.get('substitutes_for')]
        self.assertEqual([seat['substitutes_for'] for seat in clones], ['opus'])
        self.assertEqual(clones[0]['model'], 'gpt-5.6-sol')
        both_down = [dict(sonnet), dict(luna)]
        roster.substitute_high_pairs(both_down, [], cfg)
        self.assertEqual(len(both_down), 2)
