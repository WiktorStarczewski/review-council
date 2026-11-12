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


def load_roster():
    spec = importlib.util.spec_from_file_location('roster_under_test', ROSTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PI_HOST = True
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

    def test_high_effort_is_two_sol_two_opus_and_high_risk_is_not(self):
        self.assertEqual(self.panel.chosen_mode('review this, high-risk'), 'normal')
        self.assertEqual(self.panel.chosen_mode('/rev this_pr, high effort'), 'high')
        self.assertEqual(self.panel.chosen_mode('high effort, then normal effort'), 'normal')
        config = self.panel.mode_config({'codex_effort': 'max', 'quota_fallback': True}, 'high', 'claude', False)
        self.assertEqual(config['codex_models'], ['latest-sol', 'latest-sol'])
        self.assertEqual(config['claude_seats'], 2)
        self.assertNotIn('claude_models', config)
        self.assertEqual(config['codex_effort'], 'max')
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

    def high_fixture(self):
        roster = load_roster()
        cfg = {'panel_mode': 'high', 'codex_models': ['gpt-5.6-sol'] * 2,
               'claude_seats': 2, 'extras': False, 'min_labs': 1}
        sols = [roster.make_seat(name, 'codex', 'gpt-5.6-sol', 'xhigh')
                for name in ('codex-sol', 'codex-sol-2')]
        opuses = roster.opus_seats('claude', 2)
        return roster, cfg, sols, opuses

    def test_high_preset_is_identical_on_all_hosts_and_drops_old_claude_models(self):
        for host in ('claude', 'codex', 'cursor', 'pi'):
            with self.subTest(host=host):
                session = Path(self.temp.name) / host
                base = Path(self.temp.name) / 'base.json'
                original = '{"claude_models":["opus","sonnet"],"quota_fallback":true}\n'
                base.write_text(original)
                path = self.panel.write_session(session, 'mode: high', base,
                                                host=host, grok_ready=True)
                cfg = json.loads(path.read_text())
                self.assertEqual(cfg['codex_models'], ['latest-sol', 'latest-sol'])
                self.assertEqual(cfg['claude_seats'], 2)
                self.assertNotIn('claude_models', cfg)
                self.assertNotIn('cursor_sdk_models', cfg)
                self.assertTrue(cfg['quota_fallback'])
                self.assertEqual(base.read_text(), original)

    def test_explicit_roster_still_overrides_high(self):
        path = self.panel.write_session(Path(self.temp.name) / 'explicit',
                                        'mode: high, use 4*luna', host='pi', grok_ready=False)
        cfg = json.loads(path.read_text())
        self.assertEqual(cfg['codex_models'], ['latest-luna'] * 4)
        self.assertEqual(cfg['claude_seats'], 0)
        self.assertNotIn('claude_models', cfg)
        self.assertEqual(json.loads((path.parent / 'panel-request.json').read_text())['roster'], 'explicit')

    def test_high_healthy_panel_has_four_distinct_required_seats(self):
        roster, cfg, sols, opuses = self.high_fixture()
        names = roster.codex_seat_names([('gpt-5.6-sol', 'xhigh')] * 2)
        self.assertEqual(names, ['codex-sol', 'codex-sol-2'])
        actual_opuses, error = roster.claude_seats('claude', cfg)
        self.assertIsNone(error)
        self.assertEqual([(s['seat'], s['model']) for s in actual_opuses],
                         [('opus', 'opus'), ('opus-2', 'opus')])
        kept, excluded = sols + opuses, []
        roster.substitute_high_pairs(kept, excluded, cfg)
        self.assertEqual([s['seat'] for s in kept], ['codex-sol', 'codex-sol-2', 'opus', 'opus-2'])
        self.assertEqual(excluded, [])
        self.assertEqual(roster.enforce_exact_seats(cfg, kept, excluded), (None, None))

    def test_high_replaces_both_missing_opus_seats_without_padding(self):
        roster, cfg, sols, _ = self.high_fixture()
        kept, excluded = sols, []
        roster.substitute_high_pairs(kept, excluded, cfg)
        clones = [s for s in kept if s.get('substitutes_for')]
        self.assertEqual([s['substitutes_for'] for s in clones], ['opus', 'opus-2'])
        self.assertEqual([s['model'] for s in clones], ['gpt-5.6-sol', 'gpt-5.6-sol'])
        self.assertEqual(len({s['seat'] for s in kept}), 4)
        self.assertFalse(any(s.get('padded') for s in kept))
        self.assertEqual(roster.enforce_exact_seats(cfg, kept, excluded), (None, None))

    def test_high_replaces_both_missing_sol_seats_without_padding(self):
        roster, cfg, _, opuses = self.high_fixture()
        kept, excluded = opuses, []
        roster.substitute_high_pairs(kept, excluded, cfg)
        clones = [s for s in kept if s.get('substitutes_for')]
        self.assertEqual([s['substitutes_for'] for s in clones], ['codex-sol', 'codex-sol-2'])
        self.assertEqual([s['model'] for s in clones], ['opus', 'opus'])
        self.assertEqual(len({s['seat'] for s in kept}), 4)
        self.assertEqual(roster.enforce_exact_seats(cfg, kept, excluded), (None, None))

    def test_high_partial_missing_seat_is_replaced_once_and_exclusions_are_not_bypassed(self):
        roster, cfg, sols, opuses = self.high_fixture()
        kept, excluded = sols + opuses[:1], []
        roster.substitute_high_pairs(kept, excluded, cfg)
        roster.substitute_high_pairs(kept, excluded, cfg)
        self.assertEqual([s['substitutes_for'] for s in kept if s.get('substitutes_for')], ['opus-2'])
        self.assertEqual(len(kept), 4)
        cfg['exclude'] = ['opus-2']
        kept, excluded = sols + opuses[:1], []
        roster.substitute_high_pairs(kept, excluded, cfg)
        self.assertEqual(len(kept), 3)
        self.assertIsNotNone(roster.enforce_exact_seats(cfg, kept, excluded)[0])

    def test_high_with_both_families_down_invents_nothing(self):
        roster, cfg, _, _ = self.high_fixture()
        kept, excluded = [], []
        roster.substitute_high_pairs(kept, excluded, cfg)
        self.assertEqual(kept, [])
        self.assertIsNotNone(roster.enforce_exact_seats(cfg, kept, excluded)[0])

    def test_high_mode_substitutes_a_missing_partner_and_not_a_third_family(self):
        roster = load_roster()
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
