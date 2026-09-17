"""Codex port contracts. Isolated homes and CLI doubles; no model/network calls."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / 'plugins/review-council'
SCRIPTS = SHARED / 'scripts'


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, REVIEW_COUNCIL_HOST='codex', HOME=str(self.root),
                        REVIEW_COUNCIL_CONFIG=str(self.root / 'absent'),
                        REVIEW_COUNCIL_CLAUDE_ADAPTER='agent')
        self.roster = module(SCRIPTS / 'lib/roster.py')
        self.roster.CODEX_HOST = True
        self.roster.ORDER = ('codex', 'gemini', 'claude')

    def build_roster(self, seats, config=None, probe=None, quota_failed_seats=()):
        detects = {key: (lambda cfg, key=key: (seats.get(key, []), None))
                   for key in self.roster.ORDER}
        with patch.dict(os.environ, self.env), patch.object(self.roster, 'DETECT', detects), \
             patch.object(self.roster, 'load_config', return_value=(config or {}, None)), \
             patch.object(self.roster, 'probe_seat', side_effect=probe):
            return self.roster.build(probe is not None, quota_failed_seats)[0::2]

    def test_grok_is_not_a_live_roster_provider(self):
        for collection in (self.roster.LABS, self.roster.NAMES,
                           self.roster.PROBE_CMD, self.roster.DETECT):
            self.assertNotIn('grok', collection)
        self.assertNotIn('grok', self.roster.ORDER)
        self.assertFalse(hasattr(self.roster, 'detect_grok'))
        self.assertFalse(any(extra[0] == 'grok' for extra in self.roster.EXTRAS))

    def test_no_implicit_anthropic_seat(self):
        roster, failed = self.build_roster({})
        self.assertTrue(failed)
        self.assertEqual(roster['seats'], [])
        self.assertIn('no usable reviewer', roster['degradation'])

    def test_padding_uses_real_cli_and_honors_exclusions(self):
        seat = self.roster.make_seat('codex-astra', 'codex', 'gpt-6-astra', 'max')
        roster, failed = self.build_roster({'codex': [seat]}, {'claude_seat': False, 'extras': False})
        self.assertFalse(failed)
        self.assertEqual(len(roster['seats']), 3)
        self.assertEqual({s['adapter'] for s in roster['seats']}, {'codex'})
        self.assertEqual(len({s['seat'] for s in roster['seats']}), 3)
        self.assertTrue(roster['degraded'])
        self.assertEqual(roster['padded'], 2)

    def test_failed_probes_are_not_padded_back(self):
        seat = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        roster, failed = self.build_roster(
            {'claude': [seat]},
            probe=lambda _seat: ('probe failed', 'other', 'unclassified provider failure'),
        )
        self.assertTrue(failed)
        self.assertEqual(roster['seats'], [])

    def test_provider_probes_bind_the_selected_effort(self):
        commands = []

        def capture(command, _timeout):
            commands.append(command)
            return 0, 'OK', ''

        with patch.object(self.roster, 'run', side_effect=capture):
            self.assertEqual(
                self.roster.probe_seat(
                    self.roster.make_seat('sol', 'codex', 'gpt-5.6-sol', 'max')),
                (None, None, None),
            )
            self.assertEqual(
                self.roster.probe_seat(
                    self.roster.make_seat('sonnet', 'claude', 'sonnet', 'max')),
                (None, None, None),
            )
        self.assertIn('model_reasoning_effort=max', commands[0])
        self.assertEqual(commands[1][commands[1].index('--effort') + 1], 'max')

    def test_repeat_seats_do_not_satisfy_lab_floor(self):
        seat = self.roster.make_seat('codex-astra', 'codex', 'gpt-6-astra', 'max')
        _, failed = self.build_roster({'codex': [seat]}, {'min_labs': 2})
        self.assertTrue(failed)

    def test_integer_major_models(self):
        cache = self.root / 'cache.json'
        cache.write_text(json.dumps({'models': [
            {'slug': name, 'visibility': 'list', 'priority': priority,
             'supported_reasoning_levels': [{'effort': 'max'}]}
            for name, priority in [('gpt-5.6-sol', 1), ('gpt-6-astra', 2)]]}))
        listed, reason = self.roster.codex_catalog(cache)
        self.assertIsNone(reason)
        self.assertEqual(self.roster.select_codex_models(listed), [('gpt-6-astra', 'max')])
        self.assertEqual(self.roster.codex_suffix('gpt-6-astra'), 'astra')

    def test_configured_codex_models_select_exact_slugs(self):
        cache = self.root / 'cache.json'
        cache.write_text(json.dumps({'models': [
            {'slug': name, 'visibility': 'list', 'priority': priority,
             'supported_reasoning_levels': [{'effort': 'max'}]}
            for name, priority in [('gpt-5.6-sol', 1), ('gpt-5.6-terra', 2),
                                   ('gpt-6-astra', 1)]]}))
        listed, reason = self.roster.codex_catalog(cache)
        self.assertIsNone(reason)
        self.assertEqual(self.roster.select_codex_models(listed, ['gpt-5.6-sol']),
                         [('gpt-5.6-sol', 'max')])

    def test_exact_count_detects_sol_terra_and_two_opus_seats(self):
        cache = self.root / 'cache.json'
        cache.write_text(json.dumps({'models': [
            {'slug': name, 'visibility': 'list', 'priority': priority,
             'supported_reasoning_levels': [{'effort': 'max'}]}
            for name, priority in [('gpt-5.6-sol', 1), ('gpt-5.6-terra', 2),
                                   ('gpt-6-astra', 1)]]}))
        cfg = {'codex_models': ['gpt-5.6-sol', 'gpt-5.6-terra'], 'claude_seats': 2,
               'exclude': ['gemini'], 'extras': False}

        def fake_run(cmd, _timeout):
            if cmd[:3] == ['codex', 'login', 'status']:
                return 0, 'Logged in using ChatGPT', ''
            if cmd[:4] == ['claude', 'auth', 'status', '--json']:
                return 0, '{"loggedIn":true}', ''
            self.fail('unexpected command: %r' % cmd)

        env = dict(self.env, REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(cache))
        with patch.dict(os.environ, env), \
             patch.object(self.roster, 'load_config', return_value=(cfg, None)), \
             patch.object(self.roster.shutil, 'which', return_value='/fixture/cli'), \
             patch.object(self.roster, 'run', side_effect=fake_run):
            roster, _, failed = self.roster.build(False)
        self.assertFalse(failed)
        self.assertEqual(
            [(seat['seat'], seat['adapter'], seat['model']) for seat in roster['seats']],
            [('codex-sol', 'codex', 'gpt-5.6-sol'),
             ('codex-terra', 'codex', 'gpt-5.6-terra'),
             ('opus', 'claude', 'opus'),
             ('opus-2', 'claude', 'opus')],
        )

    def test_exact_panel_detects_ordered_opus_and_sonnet_on_both_hosts(self):
        config = {'claude_models': ['opus', 'sonnet'], 'extras': False}
        for codex_host, adapter in ((True, 'claude'), (False, 'agent')):
            with self.subTest(codex_host=codex_host), patch.dict(os.environ, self.env), \
                 patch.object(self.roster.shutil, 'which', return_value='/fixture/claude'), \
                 patch.object(self.roster, 'run', return_value=(
                     0, '{"loggedIn":true}', '')):
                self.roster.CODEX_HOST = codex_host
                seats, reason = (self.roster.detect_claude(config) if codex_host
                                 else self.roster.detect_agent(config))
            self.assertIsNone(reason)
            self.assertEqual(
                [(seat['seat'], seat['adapter'], seat['model'], seat['effort'])
                 for seat in seats],
                [('opus', adapter, 'opus', 'max'),
                 ('sonnet', adapter, 'sonnet', 'max')],
            )

    def test_invalid_exact_settings_fail_closed(self):
        invalid_codex = [
            'gpt-5.6-sol', [],
            ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-6-astra'],
            ['gpt-5.6-sol', 3], ['gpt-5.6-sol', 'gpt-5.6-sol'],
        ]
        for value in invalid_codex:
            with self.subTest(codex_models=value), \
                 patch.object(self.roster.shutil, 'which', return_value=None):
                seats, reason = self.roster.detect_codex({'codex_models': value})
                self.assertEqual(seats, [])
                self.assertIn('invalid codex_models', reason)
        for value in ('2', True, -1, 5, 1.5):
            with self.subTest(claude_seats=value), \
                 patch.object(self.roster.shutil, 'which', return_value=None):
                seats, reason = self.roster.detect_claude({'claude_seats': value})
                self.assertEqual(seats, [])
                self.assertIn('invalid claude_seats', reason)
        invalid_claude_models = (
            'opus', [], ['opus', 'sonnet', 'haiku'], ['haiku'],
            ['claude-opus-4-1'], ['opus', 3], ['opus', 'opus'],
            ['opus', 'OPUS'], [' opus'],
        )
        for value in invalid_claude_models:
            with self.subTest(claude_models=value):
                seats, reason = self.roster.detect_agent({'claude_models': value})
                self.assertEqual(seats, [])
                self.assertIn('invalid claude_models', reason)
        seats, reason = self.roster.detect_agent(
            {'claude_models': ['opus', 'sonnet'], 'claude_seats': 2})
        self.assertEqual(seats, [])
        self.assertEqual(reason, 'claude_models and claude_seats are mutually exclusive')
        for config in ({'codex_models': 'gpt-5.6-sol'}, {'claude_seats': '2'},
                       {'claude_models': 'opus'},
                       {'claude_models': ['opus'], 'claude_seats': 1}):
            with self.subTest(config=config):
                roster, strict_class = self.build_roster({}, config)
                self.assertEqual(strict_class, 'config')
                self.assertEqual(roster['strict_class'], 'config')
                self.assertTrue(any(entry['reason'].startswith(
                    ('strict: invalid ', 'strict: claude_models and claude_seats '))
                                    for entry in roster['excluded']))

    def test_claude_model_seat_names_are_stable_and_unique(self):
        self.assertEqual(
            self.roster.claude_model_seat_names(['opus', 'sonnet']),
            ['opus', 'sonnet'],
        )

    def test_permanent_config_wins_over_availability(self):
        roster, strict_class = self.build_roster(
            {}, {'codex_models': 'gpt-5.6-sol', 'min_labs': 3})
        self.assertEqual(strict_class, 'config')
        self.assertEqual(roster['strict_class'], 'config')
        self.assertTrue(any(entry['cli'] == 'min_labs' for entry in roster['excluded']))
        cases = (
            {'codex_models': ['gpt-5.6-sol'],
             'pin': {'codex-sol': {'model': 'gpt-6-astra'}}},
            {'claude_seats': 2, 'exclude': ['opus-2']},
        )
        for config in cases:
            with self.subTest(config=config):
                roster, strict_class = self.build_roster({}, config)
                self.assertEqual(strict_class, 'config')
                self.assertEqual(roster['strict_class'], 'config')

    def test_unknown_configured_codex_slug_fails_the_exact_selection(self):
        cache = self.root / 'cache.json'
        cache.write_text(json.dumps({'models': [
            {'slug': 'gpt-5.6-sol', 'visibility': 'list', 'priority': 1,
             'supported_reasoning_levels': [{'effort': 'max'}]},
        ]}))
        env = dict(self.env, REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(cache))
        with patch.dict(os.environ, env), \
             patch.object(self.roster.shutil, 'which', return_value='/fixture/codex'), \
             patch.object(self.roster, 'run', return_value=(0, 'Logged in using ChatGPT', '')):
            seats, reason = self.roster.detect_codex(
                {'codex_models': ['gpt-5.6-sol', 'gpt-9-unknown']})
        self.assertEqual(seats, [])
        self.assertIn('unknown Codex model slug', reason)
        self.assertIn('gpt-9-unknown', reason)
        with patch.dict(os.environ, env), \
             patch.object(self.roster.shutil, 'which', return_value=None):
            seats, reason = self.roster.detect_codex(
                {'codex_models': ['gpt-9-unknown']})
        self.assertEqual(seats, [])
        self.assertIn('unknown Codex model slug', reason)

    def test_configured_codex_cache_diagnostics_keep_the_cause(self):
        missing = self.root / 'missing.json'
        corrupt = self.root / 'corrupt.json'
        unsupported = self.root / 'unsupported.json'
        corrupt.write_text('{')
        unsupported.write_text(json.dumps({'models': [{
            'slug': 'gpt-5.6-sol', 'visibility': 'list', 'priority': 1,
            'supported_reasoning_levels': [{'effort': 'medium'}],
        }]}))
        with patch.object(self.roster.shutil, 'which', return_value='/fixture/codex'), \
             patch.object(self.roster, 'run', return_value=(0, 'Logged in using ChatGPT', '')):
            for cache, expected in ((missing, 'model cache unavailable'),
                                    (corrupt, 'model cache unreadable')):
                with self.subTest(cache=cache), patch.dict(
                        os.environ, dict(self.env, REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(cache))):
                    seats, reason = self.roster.detect_codex(
                        {'codex_models': ['gpt-5.6-sol']})
                    self.assertEqual(seats, [])
                    self.assertIn(expected, reason)
            with patch.dict(os.environ, dict(
                    self.env, REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(unsupported))):
                seats, reason = self.roster.detect_codex(
                    {'codex_models': ['gpt-5.6-sol']})
                self.assertEqual(seats, [])
                self.assertEqual(reason,
                                 'configured Codex model has no supported high effort: gpt-5.6-sol')

    def test_cross_generation_codex_suffixes_get_unique_seat_ids(self):
        cache = self.root / 'cache.json'
        cache.write_text(json.dumps({'models': [
            {'slug': slug, 'visibility': 'list', 'priority': 1,
             'supported_reasoning_levels': [{'effort': 'max'}]}
            for slug in ('gpt-5.6-sol', 'gpt-6-sol')
        ]}))
        env = dict(self.env, REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(cache))
        with patch.dict(os.environ, env), \
             patch.object(self.roster.shutil, 'which', return_value='/fixture/codex'), \
             patch.object(self.roster, 'run', return_value=(0, 'Logged in using ChatGPT', '')):
            seats, reason = self.roster.detect_codex(
                {'codex_models': ['gpt-5.6-sol', 'gpt-6-sol']})
        self.assertIsNone(reason)
        self.assertEqual([seat['seat'] for seat in seats],
                         ['codex-5-6-sol', 'codex-6-sol'])

    def test_codex_model_pin_cannot_escape_exact_allowlist(self):
        sol = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        gemini = self.roster.make_seat('gemini', 'gemini', 'gemini-2.5-pro', None)
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        config = {'codex_models': ['gpt-5.6-sol'], 'claude_seats': 1,
                  'extras': False,
                  'pin': {'codex-sol': {'model': 'gpt-6-astra'}}}
        roster, failed = self.build_roster(
            {'codex': [sol], 'gemini': [gemini], 'claude': [opus]}, config)
        self.assertEqual(failed, 'config')
        self.assertNotIn('gpt-6-astra', [seat['model'] for seat in roster['seats']])
        self.assertIn(
            {'cli': 'codex-sol',
             'reason': 'pinned model gpt-6-astra is outside codex_models'},
            roster['excluded'],
        )
        self.assertIn(
            {'cli': 'codex_models',
             'reason': 'strict: codex_models requires 1 matching seat(s), 0 survived'},
            roster['excluded'],
        )

    def test_exact_extra_pins_apply_only_to_active_extras(self):
        def seats(include_codex=True):
            found = {
                'gemini': [self.roster.make_seat(
                    'gemini', 'gemini', 'gemini-2.5-pro', None)],
                'claude': [self.roster.make_seat('opus', 'claude', 'opus', 'max')],
            }
            if include_codex:
                found['codex'] = [self.roster.make_seat(
                    'codex-sol', 'codex', 'gpt-5.6-sol', 'max')]
            return found

        pin = {'codex-review': {'model': 'gpt-6-astra'}}
        active, failed = self.build_roster(
            seats(), {'codex_models': ['gpt-5.6-sol'], 'pin': pin})
        self.assertEqual(failed, 'config')
        self.assertEqual(active['strict_reason'],
                         'codex-review: pinned model gpt-6-astra is outside codex_models')
        self.assertEqual(sum(entry['reason'].startswith('strict: codex_models')
                             for entry in active['excluded']), 1)

        inactive_configs = (
            {'codex_models': ['gpt-5.6-sol'], 'pin': pin, 'extras': False},
            {'codex_models': ['gpt-5.6-sol'], 'pin': pin,
             'exclude': ['codex-review']},
        )
        for config in inactive_configs:
            with self.subTest(config=config):
                roster, failed = self.build_roster(seats(), config)
                self.assertFalse(failed)
                self.assertNotIn('strict_class', roster)
                self.assertFalse(any(entry['reason'].startswith('pinned model ')
                                     for entry in roster['excluded']))

        orphaned, failed = self.build_roster(
            seats(include_codex=False),
            {'codex_models': ['gpt-5.6-sol'], 'pin': pin},
        )
        self.assertEqual(failed, 'availability')
        self.assertEqual(orphaned['strict_reason'],
                         'codex_models requires 1 matching seat(s), 0 survived')
        self.assertFalse(any(entry['reason'].startswith('pinned model ')
                             for entry in orphaned['excluded']))

    def test_explicit_claude_pins_must_remain_in_opus_family_on_both_hosts(self):
        for codex_host, adapter in ((True, 'claude'), (False, 'agent')):
            with self.subTest(codex_host=codex_host):
                self.roster.CODEX_HOST = codex_host
                self.roster.ORDER = (adapter,)
                detected = [self.roster.make_seat(
                    'opus' if index == 0 else 'opus-%d' % (index + 1),
                    adapter, 'opus', 'max') for index in range(2)]
                roster, failed = self.build_roster(
                    {adapter: detected},
                    {'claude_seats': 2, 'extras': False,
                     'pin': {'opus-2': {'model': 'sonnet'}}},
                )
                self.assertEqual(failed, 'config')
                self.assertEqual(
                    roster['strict_reason'],
                    'opus-2: pinned model sonnet is outside the Opus family',
                )
                self.assertEqual(sum(entry['reason'].startswith('strict: claude_seats')
                                     for entry in roster['excluded']), 1)

    def test_exact_claude_model_pins_are_fail_closed_on_both_hosts(self):
        cases = (
            ({'opus': {'model': 'haiku'}},
             'opus: pinned model haiku is outside claude_models'),
            ({'sonnet': {'model': 'opus'}},
             'sonnet: pinned model opus does not match required model sonnet'),
            ({'opus': {'model': 'sonnet'}, 'sonnet': {'model': 'opus'}},
             'opus: pinned model sonnet does not match required model opus'),
            ({'sonnet': {'effort': 'high'}},
             'sonnet: pinned effort high does not match required effort max'),
        )
        for codex_host, adapter in ((True, 'claude'), (False, 'agent')):
            for pins, expected in cases:
                with self.subTest(codex_host=codex_host, pins=pins):
                    self.roster.CODEX_HOST = codex_host
                    self.roster.ORDER = (adapter,)
                    detected = [
                        self.roster.make_seat('opus', adapter, 'opus', 'max'),
                        self.roster.make_seat('sonnet', adapter, 'sonnet', 'max'),
                    ]
                    roster, failed = self.build_roster(
                        {adapter: detected},
                        {'claude_models': ['opus', 'sonnet'], 'extras': False,
                         'pin': pins},
                    )
                    self.assertEqual(failed, 'config')
                    self.assertEqual(roster['strict_reason'], expected)
                    self.assertEqual(
                        sum(entry['reason'].startswith('strict: claude_models')
                            for entry in roster['excluded']),
                        1,
                    )

    def test_excluding_an_exact_claude_model_is_permanent_config(self):
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        sonnet = self.roster.make_seat('sonnet', 'claude', 'sonnet', 'max')
        calls = []
        roster, failed = self.build_roster(
            {'claude': [opus, sonnet]},
            {'claude_models': ['opus', 'sonnet'], 'exclude': ['sonnet'],
             'extras': False},
            probe=lambda seat: calls.append(seat['seat']),
        )
        self.assertEqual(failed, 'config')
        self.assertEqual(roster['strict_reason'], 'sonnet: excluded by config')
        self.assertEqual(calls, [])
        self.assertIn(
            {'cli': 'claude_models',
             'reason': 'strict: claude_models requires 2 matching seat(s), 1 survived'},
            roster['excluded'],
        )

    def test_exact_claude_models_cannot_be_disabled_and_skip_probes(self):
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        sonnet = self.roster.make_seat('sonnet', 'claude', 'sonnet', 'max')
        cases = (
            ({'claude_seat': False}, {},
             'claude_models conflicts with claude_seat: false'),
            ({}, {'REVIEW_COUNCIL_CLAUDE_SEAT': '0'},
             'claude_models conflicts with REVIEW_COUNCIL_CLAUDE_SEAT=0'),
        )
        for extra_config, extra_env, expected in cases:
            calls = []
            config = {'claude_models': ['opus', 'sonnet'], 'extras': False,
                      **extra_config}
            with self.subTest(config=extra_config, env=extra_env), \
                 patch.dict(os.environ, extra_env):
                roster, failed = self.build_roster(
                    {'claude': [opus, sonnet]}, config,
                    probe=lambda seat: calls.append(seat['seat']),
                )
            self.assertEqual(failed, 'config')
            self.assertEqual(roster['strict_reason'], expected)
            self.assertEqual(calls, [])

    def test_default_claude_pin_behavior_remains_non_exact(self):
        detected = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        roster, failed = self.build_roster(
            {'claude': [detected]},
            {'extras': False, 'pin': {'opus': {'model': 'sonnet'}}},
        )
        self.assertFalse(failed)
        self.assertNotIn('strict_class', roster)
        self.assertEqual(next(seat for seat in roster['seats']
                              if seat['seat'] == 'opus')['model'], 'sonnet')

    def test_plural_unsupported_codex_models_are_permanent_config(self):
        cache = self.root / 'unsupported.json'
        models = ['gpt-5.6-sol', 'gpt-5.6-terra']
        cache.write_text(json.dumps({'models': [
            {'slug': slug, 'visibility': 'list', 'priority': index,
             'supported_reasoning_levels': [{'effort': 'medium'}]}
            for index, slug in enumerate(models, 1)
        ]}))
        self.roster.ORDER = ('codex',)
        env = dict(self.env, REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(cache))
        with patch.dict(os.environ, env), \
             patch.object(self.roster, 'DETECT', {'codex': self.roster.detect_codex}), \
             patch.object(self.roster, 'load_config',
                          return_value=({'codex_models': models, 'extras': False}, None)), \
             patch.object(self.roster.shutil, 'which', return_value='/fixture/codex'), \
             patch.object(self.roster, 'run', return_value=(0, 'Logged in using ChatGPT', '')):
            roster, _, failed = self.roster.build(False)
        self.assertEqual(failed, 'config')
        self.assertEqual(
            roster['strict_reason'],
            'configured Codex models have no supported high effort: '
            'gpt-5.6-sol, gpt-5.6-terra',
        )

    def test_permanent_exact_config_skips_probes_but_valid_control_probes(self):
        def seats():
            return {
                'codex': [self.roster.make_seat(
                    'codex-sol', 'codex', 'gpt-5.6-sol', 'max')],
                'gemini': [self.roster.make_seat(
                    'gemini', 'gemini', 'gemini-2.5-pro', None)],
                'claude': [self.roster.make_seat('opus', 'claude', 'opus', 'max')],
            }

        calls = []
        invalid, failed = self.build_roster(
            seats(),
            {'codex_models': ['gpt-5.6-sol'],
             'pin': {'codex-review': {'model': 'gpt-6-astra'}}},
            probe=lambda seat: calls.append(seat['seat']),
        )
        self.assertEqual(failed, 'config')
        self.assertEqual(calls, [])
        self.assertEqual(sum(entry['reason'].startswith('strict: codex_models')
                             for entry in invalid['excluded']), 1)

        valid_calls = []
        valid, failed = self.build_roster(
            seats(),
            {'codex_models': ['gpt-5.6-sol'], 'claude_seats': 1,
             'extras': False},
            probe=lambda seat: (valid_calls.append(seat['seat']), None, None),
        )
        self.assertFalse(failed)
        self.assertEqual(len(valid_calls), 3)
        self.assertEqual(set(valid_calls), {'codex-sol', 'gemini', 'opus'})
        self.assertNotIn('strict_class', valid)

    def test_exact_codex_count_rejects_padded_name_collision(self):
        sol = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        gemini = self.roster.make_seat('gemini', 'gemini', 'gemini-2.5-pro', None)
        roster, failed = self.build_roster(
            {'codex': [sol], 'gemini': [gemini]},
            {'codex_models': ['gpt-5.6-sol', 'gpt-5.6-sol-1'], 'extras': False},
        )
        self.assertEqual(failed, 'availability')
        self.assertEqual(roster['padded'], 1)
        self.assertEqual(
            [(seat['seat'], seat['model'], seat.get('padded'))
             for seat in roster['seats'] if seat['adapter'] == 'codex'],
            [('codex-sol', 'gpt-5.6-sol', None),
             ('codex-sol-1', 'gpt-5.6-sol', True)],
        )
        self.assertIn(
            {'cli': 'codex_models',
             'reason': 'strict: codex_models requires 2 matching seat(s), 1 survived'},
            roster['excluded'],
        )

    def test_exact_claude_count_is_checked_before_padding(self):
        sol = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        roster, failed = self.build_roster(
            {'codex': [sol], 'claude': [opus]},
            {'claude_seats': 2, 'extras': False},
        )
        self.assertEqual(failed, 'availability')
        self.assertEqual(roster['padded'], 1)
        self.assertIn(
            {'cli': 'claude_seats',
             'reason': 'strict: claude_seats requires 2 matching seat(s), 1 survived'},
            roster['excluded'],
        )

    def test_exact_probe_failure_refuses_even_after_padding(self):
        sol = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        roster, failed = self.build_roster(
            {'codex': [sol], 'claude': [opus]},
            {'codex_models': ['gpt-5.6-sol'], 'claude_seats': 1, 'extras': False},
            probe=lambda _seat: ('probe failed', 'other', 'unclassified provider failure'),
        )
        self.assertEqual(failed, 'availability')
        self.assertEqual(roster['seats'], [])
        strict = [entry['reason'] for entry in roster['excluded']
                  if entry['reason'].startswith('strict: ')]
        self.assertIn('strict: codex_models requires 1 matching seat(s), 0 survived', strict)
        self.assertIn('strict: claude_seats requires 1 matching seat(s), 0 survived', strict)

    def test_disabled_claude_count_is_not_an_exact_requirement(self):
        self.roster.CODEX_HOST = False
        self.roster.ORDER = ('agent',)
        env = dict(self.env, REVIEW_COUNCIL_CLAUDE_SEAT='0')
        with patch.dict(os.environ, env), \
             patch.object(self.roster, 'DETECT', {'agent': self.roster.detect_agent}), \
             patch.object(self.roster, 'load_config',
                          return_value=({'claude_seats': 2, 'extras': False}, None)):
            roster, _, failed = self.roster.build(False)
        self.assertFalse(failed)
        self.assertEqual(roster['padded'], 3)
        self.assertFalse(any(entry['cli'] == 'claude_seats'
                             for entry in roster['excluded']))

    def test_result_receipt_policy_snapshots_and_preserves_legacy_results(self):
        session = self.root / 'session'
        session.mkdir()
        missing_exit = session / 'r1-codex-sol.json'
        plan_missing_exit = session / 'r2p-opus.json'
        repair_missing_exit = session / 'r2x-grok.json'
        with_exit = session / 'r1-grok.json'
        missing_exit.write_bytes(b'{"one":1}\n')
        plan_missing_exit.write_bytes(b'{"plan":1}\n')
        repair_missing_exit.write_bytes(b'{"repair":1}\n')
        with_exit.write_bytes(b'{"two":2}\n')
        with_exit.with_suffix('.exit').write_text('0\n')
        roster_path = session / 'roster.json'

        policy = self.roster.result_receipt_policy(roster_path)
        self.assertEqual(policy, {
            'version': 1,
            'legacy_no_exit_sha256': {
                missing_exit.name: hashlib.sha256(missing_exit.read_bytes()).hexdigest(),
                plan_missing_exit.name: hashlib.sha256(plan_missing_exit.read_bytes()).hexdigest(),
                repair_missing_exit.name: hashlib.sha256(repair_missing_exit.read_bytes()).hexdigest(),
            },
        })

        preserved = {
            'version': 7,
            'legacy_no_exit_sha256': {'old.json': 'a' * 64},
        }
        roster_path.write_text(json.dumps({'result_receipts': preserved}))
        (session / 'r2-opus.json').write_text('{}')
        self.assertEqual(self.roster.result_receipt_policy(roster_path), preserved)

    def test_invalid_present_receipt_policy_never_snapshots_legacy_results(self):
        session = self.root / 'invalid-receipts'
        session.mkdir()
        legacy = session / 'r1-opus.json'
        legacy.write_text('{"summary":"legacy","findings":[]}')
        roster_path = session / 'roster.json'
        empty = {'version': 1, 'legacy_no_exit_sha256': {}}
        invalid_documents = (
            '{',
            '[]',
            json.dumps({'result_receipts': {'version': '1',
                                                    'legacy_no_exit_sha256': {}}}),
            json.dumps({'result_receipts': {'version': True,
                                                    'legacy_no_exit_sha256': {}}}),
            json.dumps({'result_receipts': {'version': 0,
                                                    'legacy_no_exit_sha256': {}}}),
            json.dumps({'result_receipts': {'version': 1,
                                                    'legacy_no_exit_sha256': []}}),
            json.dumps({'result_receipts': {'version': 1,
                                                    'legacy_no_exit_sha256': {
                                                        legacy.name: 'abc',
                                                    }}}),
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                roster_path.write_text(document)
                self.assertEqual(self.roster.result_receipt_policy(roster_path), empty)

        roster_path.unlink()
        roster_path.mkdir()
        self.assertEqual(self.roster.result_receipt_policy(roster_path), empty)

    def test_min_labs_rejects_invalid_and_impossible_config_before_probes(self):
        codex = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        gemini = self.roster.make_seat('gemini', 'gemini', 'gemini-2.5-pro', None)
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        seats = {'codex': [codex], 'gemini': [gemini], 'claude': [opus]}
        for value in ('two', True, 0, -1):
            calls = []
            with self.subTest(min_labs=value):
                roster, failed = self.build_roster(
                    seats, {'min_labs': value, 'extras': False},
                    probe=lambda seat: calls.append(seat['seat']),
                )
                self.assertEqual(failed, 'config')
                self.assertEqual(roster['strict_reason'],
                                 'invalid min_labs: expected an integer of at least 1')
                self.assertEqual(calls, [])

        calls = []
        roster, failed = self.build_roster(
            seats,
            {'min_labs': 3, 'exclude': ['gemini'], 'extras': False},
            probe=lambda seat: calls.append(seat['seat']),
        )
        self.assertEqual(failed, 'config')
        self.assertEqual(roster['strict_reason'],
                         'min_labs=3 exceeds 2 configured lab(s)')
        self.assertEqual(calls, [])

    def test_satisfiable_min_labs_availability_shortfall_remains_retryable(self):
        codex = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        gemini = self.roster.make_seat('gemini', 'gemini', 'gemini-2.5-pro', None)
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        calls = []

        def probe(seat):
            calls.append(seat['seat'])
            if seat['adapter'] == 'gemini':
                return 'probe failed', 'other', 'unclassified provider failure'
            return None, None, None

        roster, failed = self.build_roster(
            {'codex': [codex], 'gemini': [gemini], 'claude': [opus]},
            {'min_labs': 3, 'extras': False},
            probe=probe,
        )
        self.assertEqual(failed, 'availability')
        self.assertEqual(roster['strict_reason'], '2 lab(s) available, min_labs=3')
        self.assertCountEqual(calls, ['codex-sol', 'gemini', 'opus'])

    def test_forced_quota_seats_cannot_fallback_to_each_other(self):
        terra = self.roster.make_seat(
            'codex-terra', 'codex', 'gpt-5.6-terra', 'max')
        sonnet = self.roster.make_seat('sonnet', 'claude', 'sonnet', 'max')
        roster, failed = self.build_roster(
            {'codex': [terra], 'claude': [sonnet]},
            {'extras': False, 'quota_fallback': True},
            probe=lambda _seat: (None, None, None),
            quota_failed_seats=('codex-terra', 'sonnet'),
        )
        self.assertEqual(failed, 'availability')
        self.assertFalse(any(seat.get('substitutes_for') for seat in roster['seats']))
        self.assertIn('codex-terra has no usable fallback target', roster['strict_reason'])
        self.assertIn('sonnet has no usable fallback target', roster['strict_reason'])

    def test_quota_substitution_does_not_waive_an_unrelated_lab_failure(self):
        terra = self.roster.make_seat(
            'codex-terra', 'codex', 'gpt-5.6-terra', 'max')
        gemini = self.roster.make_seat('gemini', 'gemini', 'gemini-2.5-pro', None)
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')

        def probe(seat):
            if seat['adapter'] == 'gemini':
                return 'probe failed', 'other', 'unclassified provider failure'
            if seat['adapter'] == 'claude':
                return 'probe failed', 'quota', 'quota exhausted'
            return None, None, None

        roster, failed = self.build_roster(
            {'codex': [terra], 'gemini': [gemini], 'claude': [opus]},
            {'extras': False, 'min_labs': 3, 'quota_fallback': True},
            probe=probe,
        )
        self.assertEqual(failed, 'availability')
        self.assertEqual(roster['strict_reason'], '1 lab(s) available, min_labs=3')
        self.assertTrue(any(seat.get('substitutes_for') == 'opus'
                            for seat in roster['seats']))
        self.assertIn(
            {'cli': 'min_labs', 'reason': 'strict: 1 lab(s) available, min_labs=3'},
            roster['excluded'],
        )
        self.assertFalse(any('temporarily waived' in entry['reason']
                             for entry in roster['excluded']))

    def test_repeated_provider_model_probe_runs_once(self):
        sol = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        gemini = self.roster.make_seat('gemini', 'gemini', 'gemini-2.5-pro', None)
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        opus2 = self.roster.make_seat('opus-2', 'claude', 'opus', 'max')
        calls = []

        def probe(seat):
            calls.append((seat['adapter'], seat['model']))
            return None, None, None

        roster, failed = self.build_roster(
            {'codex': [sol], 'gemini': [gemini], 'claude': [opus, opus2]},
            {'codex_models': ['gpt-5.6-sol'], 'claude_seats': 2,
             'extras': False}, probe)
        self.assertFalse(failed)
        self.assertEqual(len(roster['seats']), 4)
        self.assertEqual(calls.count(('claude', 'opus')), 1)

    def test_probe_cache_distinguishes_a_pinned_extra_effort(self):
        sol = self.roster.make_seat('codex-sol', 'codex', 'gpt-5.6-sol', 'max')
        calls = []

        def probe(seat):
            calls.append((seat['adapter'], seat['model'], seat['effort'], seat['extra']))
            return None, None, None

        roster, failed = self.build_roster(
            {'codex': [sol]},
            {'pin': {'codex-review': {'effort': 'ultra'}}, 'claude_seat': False},
            probe,
        )
        self.assertFalse(failed)
        self.assertIn(
            ('codex', 'gpt-5.6-sol', 'max', False), calls)
        self.assertIn(
            ('codex', 'gpt-5.6-sol', 'ultra', True), calls)
        extra = next(seat for seat in roster['seats'] if seat['extra'])
        self.assertEqual(extra['effort'], 'ultra')

    def test_exact_claude_models_probe_each_model_and_require_both(self):
        opus = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        sonnet = self.roster.make_seat('sonnet', 'claude', 'sonnet', 'max')
        calls = []

        def probe(seat):
            calls.append((seat['adapter'], seat['model']))
            if seat['model'] == 'sonnet':
                return 'probe failed', 'other', 'unclassified provider failure'
            return None, None, None

        roster, failed = self.build_roster(
            {'claude': [opus, sonnet]},
            {'claude_models': ['opus', 'sonnet'], 'extras': False}, probe)
        self.assertEqual(failed, 'availability')
        self.assertCountEqual(calls, [('claude', 'opus'), ('claude', 'sonnet')])
        self.assertIn(
            {'cli': 'claude_models',
             'reason': 'strict: claude_models requires 2 matching seat(s), 1 survived'},
            roster['excluded'],
        )

    def test_claude_seats_zero_padding_override_is_recorded(self):
        self.roster.CODEX_HOST = False
        self.roster.ORDER = ('agent',)
        with patch.dict(os.environ, self.env), \
             patch.object(self.roster, 'DETECT', {'agent': self.roster.detect_agent}), \
             patch.object(self.roster, 'load_config',
                          return_value=({'claude_seats': 0, 'extras': False}, None)):
            roster, _, failed = self.roster.build(False)
        self.assertFalse(failed)
        self.assertEqual(roster['padded'], 3)
        padding = [entry['reason'] for entry in roster['excluded']
                   if entry['cli'] == 'padding']
        self.assertEqual(len(padding), 1)
        self.assertTrue(padding[0].startswith('claude_seats: 0 overridden'))
        self.assertTrue(padding[0].endswith('a panel needs 3 seats'))

    def test_claude_seats_configures_independent_opus_runs(self):
        with patch.dict(os.environ, self.env), \
             patch.object(self.roster.shutil, 'which', return_value='/bin/claude'), \
             patch.object(self.roster, 'run', return_value=(0, '{"loggedIn":true}', '')):
            seats, reason = self.roster.detect_claude({'claude_seats': 2})
        self.assertIsNone(reason)
        self.assertEqual([seat['seat'] for seat in seats], ['opus', 'opus-2'])
        self.assertEqual({seat['model'] for seat in seats}, {'opus'})

    def test_claude_auth_requires_positive_json(self):
        for rc, payload, expected in [(0, '{"loggedIn":true}', True),
                                      (0, '{"loggedIn":false}', False),
                                      (0, '{}', False), (0, 'bad', False),
                                      (1, '{"loggedIn":true}', False), (None, '', False)]:
            with self.subTest(payload=payload, rc=rc), patch.dict(os.environ, self.env), \
                 patch.object(self.roster.shutil, 'which', return_value='/bin/claude'), \
                 patch.object(self.roster, 'run', return_value=(rc, payload, '')):
                seats, _ = self.roster.detect_claude({})
                self.assertEqual(bool(seats), expected)
                if seats:
                    self.assertEqual(seats[0]['adapter'], 'claude')

    def test_bundle_is_self_contained(self):
        output = module(REPO / 'scripts/build-codex-plugin.py').build(self.root / 'review-council')
        self.assertTrue((output / 'scripts/seats.d/claude.sh').stat().st_mode & 0o111)
        self.assertTrue((output / 'schema/findings.schema.json').exists())
        self.assertTrue((output / 'tests/run-tests.sh').stat().st_mode & 0o111)
        self.assertTrue((output / 'tests/t-provider-contract.sh').exists())
        self.assertTrue((output / 'agents/rev-reviewer.md').exists())
        self.assertTrue((output / 'agents/rev-reviewer-sonnet.md').exists())
        self.assertTrue((output / 'docs/config.md').exists())
        self.assertFalse((output / '.claude-plugin').exists())
        self.assertFalse((output / 'hooks').exists())
        for name in ('rev', 'stack'):
            text = (output / 'codex-skills' / name / 'SKILL.md').read_text()
            self.assertIn('Codex', text)
            self.assertNotIn('${CLAUDE_PLUGIN_ROOT}', text)
        self.assertIn('export REVIEW_COUNCIL_HOST=codex', (output / 'scripts/roster.sh').read_text())
        # A repeat build replaces stale generated artifacts, not just changed files.
        (output / 'stale').touch()
        module(REPO / 'scripts/build-codex-plugin.py').build(output)
        self.assertFalse((output / 'stale').exists())

    def test_public_exit_contract_distinguishes_quota_and_local_attempts(self):
        seats = (REPO / 'docs/seats.md').read_text()
        self.assertIn('`4` provider quota, capacity, or rate limit', seats)
        self.assertIn('`7` persistent local attempt exhaustion', seats)
        for relative in ('plugins/review-council/skills/rev/SKILL.md',
                         'plugins/review-council/codex-skills/rev/SKILL.md'):
            contract = (REPO / relative).read_text()
            self.assertIn('Exit 7 is local attempt exhaustion, not provider quota', contract)
            self.assertIn('Exit 3 never enters quota fallback', contract)

    def test_bundle_builds_repeatedly_from_a_read_only_source(self):
        source = self.root / 'source'
        plugin_files = {
            '.codex-plugin/plugin.json': '{"name":"review-council"}\n',
            'agents/rev-reviewer.md': 'reviewer\n',
            'codex-skills/rev/SKILL.md': 'skill\n',
            'docs/pr-review.md': 'review format\n',
            'scripts/roster.sh': '#!/bin/bash\nprintf roster\\n\n',
            'scripts/stack.sh': '#!/bin/bash\nprintf stack\\n\n',
            'schema/findings.schema.json': '{}\n',
            'tests/run-tests.sh': '#!/bin/bash\nprintf tests\\n',
        }
        files = {
            **{f'plugins/review-council/{relative}': content
               for relative, content in plugin_files.items()},
            'docs/config.md': 'config\n',
            'LICENSE': 'license\n',
        }
        executable = {'scripts/roster.sh', 'scripts/stack.sh', 'tests/run-tests.sh'}
        for relative, content in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            output_relative = relative.removeprefix('plugins/review-council/')
            path.chmod(0o555 if output_relative in executable else 0o444)
        for current, directories, _ in os.walk(source, topdown=False):
            for name in directories:
                (Path(current) / name).chmod(0o555)
        source.chmod(0o555)

        def restore_source_write():
            for current, directories, _ in os.walk(source):
                Path(current).chmod(Path(current).stat().st_mode | stat.S_IWUSR)
                for name in directories:
                    path = Path(current) / name
                    path.chmod(path.stat().st_mode | stat.S_IWUSR)

        self.addCleanup(restore_source_write)

        def snapshot(root):
            return {
                str(path.relative_to(root)): (
                    stat.S_IMODE(path.lstat().st_mode),
                    path.read_bytes() if path.is_file() else None,
                )
                for path in (root, *root.rglob('*'))
            }

        original = snapshot(source)
        builder = module(REPO / 'scripts/build-codex-plugin.py')
        builder.REPO = source
        output = self.root / 'output' / 'review-council'
        for _ in range(2):
            self.assertEqual(builder.build(output), output.absolute())
            for built in (output, *output.rglob('*')):
                mode = built.lstat().st_mode
                if stat.S_ISDIR(mode) or stat.S_ISREG(mode):
                    self.assertTrue(mode & stat.S_IWUSR, built)
            for relative in files:
                output_relative = relative.removeprefix('plugins/review-council/')
                built = output / output_relative
                source_mode = original[relative][0]
                self.assertEqual(stat.S_IMODE(built.lstat().st_mode),
                                 source_mode | stat.S_IWUSR)
            self.assertEqual(
                stat.S_IMODE((output / '.codex-plugin').stat().st_mode),
                original['plugins/review-council/.codex-plugin'][0] | stat.S_IWUSR,
            )
            for script in ('roster.sh', 'stack.sh'):
                content = (output / 'scripts' / script).read_text()
                self.assertEqual(content.count('export REVIEW_COUNCIL_HOST=codex'), 1)
                self.assertTrue(content.startswith(
                    '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=codex\n'))
            self.assertTrue((output / 'tests/run-tests.sh').stat().st_mode & 0o111)
        self.assertEqual(snapshot(source), original)

        guard = self.root / 'symlink-guard'
        guard.mkdir()
        target = guard / 'target'
        target.write_text('guard\n')
        target.chmod(0o444)
        staging = guard / 'stage'
        staging.mkdir()
        (staging / 'link').symlink_to(target)
        builder._make_staging_writable(staging)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o444)

    def test_built_bundle_replays_its_own_contract_for_a_foreign_target(self):
        output = module(REPO / 'scripts/build-codex-plugin.py').build(self.root / 'review-council')
        checker = module(output / 'scripts/rev-contract-check.py')
        expected_selectors = list(checker.CONTRACT_TESTS)
        recorder = self.root / 'contract-recorder.jsonl'
        bundled_runner = output / 'tests/run-tests.sh'
        bundled_runner.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
allowed = set(%s)
if len(sys.argv) != 2 or sys.argv[1] not in allowed:
    raise SystemExit(2)
record = {'selector': sys.argv[1], 'owner': str(Path(__file__).resolve())}
descriptor = os.open(os.environ['CONTRACT_RECORDER'], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
with os.fdopen(descriptor, 'a') as output:
    output.write(json.dumps(record, sort_keys=True) + '\\n')
print('passed=1 failed=0')
''' % repr(expected_selectors))
        bundled_runner.chmod(0o755)
        target = self.root / 'target'
        subject = target / 'plugins/review-council'
        (subject / '.codex-plugin').mkdir(parents=True)
        (subject / 'scripts').mkdir()
        (subject / 'tests').mkdir()
        (subject / '.codex-plugin/plugin.json').write_text('{}\n')
        (subject / 'scripts/rev-prompt.sh').write_text('base boundary\n')
        subprocess.run(['git', 'init', '-q', str(target)], check=True)
        subprocess.run(['git', '-C', str(target), '-c', 'user.name=test',
                        '-c', 'user.email=test@example.invalid', 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(target), '-c', 'user.name=test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'base'], check=True)
        base = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
        (subject / 'scripts/rev-prompt.sh').write_text('changed boundary\n')
        sentinel = self.root / 'foreign-runner.sentinel'
        foreign_runner = subject / 'tests/run-tests.sh'
        foreign_runner.write_text('#!/bin/bash\nprintf hit >> "$TARGET_SENTINEL"\n')
        foreign_runner.chmod(0o755)
        session = self.root / 'session'
        session.mkdir()
        roster = session / 'roster.json'
        roster.write_text(json.dumps({'seats': [
            {'seat': 'sol', 'adapter': 'codex', 'model': 'gpt-5.6-sol',
             'effort': 'max', 'extra': False}]}))
        env = dict(os.environ, TARGET_SENTINEL=str(sentinel),
                   CONTRACT_RECORDER=str(recorder),
                   REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}',
                   REVIEW_COUNCIL_CACHE_DIR=str(self.root / 'cache'))
        proc = subprocess.run([
            'python3', str(output / 'scripts/rev-contract-check.py'),
            '--root', str(target), '--base', base, '--session', str(session),
            '--roster', str(roster),
        ], env=env, text=True, capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(sentinel.exists())
        receipt = json.loads(Path(proc.stdout.strip()).read_text())
        self.assertEqual(receipt['identity']['executor']['plugin'], str(output.resolve()))
        self.assertEqual(receipt['identity']['executor']['policy'], 'checker-owned')
        records = [json.loads(line) for line in recorder.read_text().splitlines()]

        def verify_records(rows):
            self.assertEqual(sorted(row['selector'] for row in rows), sorted(expected_selectors))
            self.assertEqual({row['owner'] for row in rows}, {str(bundled_runner.resolve())})

        verify_records(records)
        with self.assertRaises(AssertionError):
            verify_records(records[:-1])
        with self.assertRaises(AssertionError):
            verify_records([dict(records[0], owner=str(foreign_runner.resolve())), *records[1:]])

    def test_build_refuses_unrelated_directory(self):
        output = self.root / 'review-council'
        output.mkdir()
        with self.assertRaises(ValueError):
            module(REPO / 'scripts/build-codex-plugin.py').build(output)
        self.assertTrue(output.exists())

    def run_stream(self, events):
        output = self.root / 'out.json'
        proc = subprocess.run(['python3', str(SCRIPTS / 'lib/stream-summary.py'), 'claude', str(output)],
                              input='\n'.join(map(json.dumps, events)), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout, json.loads(output.read_text()) if output.exists() else None

    def test_claude_structured_findings_and_tool_evidence(self):
        findings = json.loads((SHARED / 'tests/fixtures/findings-valid.json').read_text())
        log, output = self.run_stream([
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read',
                                                          'input': {'file_path': '/code.py'}}]}},
            {'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': findings}])
        self.assertIn('tool_call Read:', log)
        self.assertEqual(output, findings)

    def test_claude_error_cannot_certify_clean_review(self):
        log, output = self.run_stream([{'type': 'result', 'is_error': True,
                                      'errors': ['usage limit'], 'structured_output': {'findings': []}}])
        self.assertIn('error: ', log)
        self.assertIsNone(output)

    def test_schema_tool_alone_is_not_repository_inspection(self):
        log, _ = self.run_stream([{'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'StructuredOutput', 'input': {}}]}}])
        self.assertNotIn('tool_call ', log)

    def test_claude_adapter_runs_sonnet_at_max_readonly_and_validates(self):
        cli = self.root / 'claude'
        cli.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))
print(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','name':'Read','input':{}}]}}))
print(json.dumps({'type':'result','is_error':False,'subtype':'success',
                  'structured_output':json.loads(Path(os.environ['FINDINGS']).read_text())}))
''')
        cli.chmod(0o755)
        (self.root / 'roster.json').write_text(json.dumps({'seats': [
            self.roster.make_seat('sonnet', 'claude', 'sonnet', 'max')]}))
        prompt = self.root / 'prompt.md'
        prompt.write_text('Review the fixture.')
        deps = self.root / 'deps'
        deps.mkdir()
        capture = self.root / 'args.json'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   REV_REPO=str(self.root), CAPTURE=str(capture),
                   REV_DEPS_DIR=str(deps),
                   FINDINGS=str(SHARED / 'tests/fixtures/findings-valid.json'))
        proc = subprocess.run([str(SCRIPTS / 'rev-seat.sh'), 'sonnet', str(self.root), '1', str(prompt)],
                              env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.root / 'r1-sonnet.exit').read_text().strip(), '0')
        args = json.loads(capture.read_text())
        self.assertEqual(args[args.index('--model') + 1], 'sonnet')
        self.assertEqual(args[args.index('--effort') + 1], 'max')
        self.assertEqual(args[args.index('--max-turns') + 1], '160')
        self.assertEqual(args[args.index('--permission-mode') + 1], 'bypassPermissions')
        self.assertEqual(args[args.index('--tools') + 1], 'Read,Grep')
        self.assertIn('--strict-mcp-config', args)
        self.assertEqual(args[args.index('--setting-sources') + 1], '')
        continuation = args[args.index('--append-system-prompt') + 1]
        self.assertIn('Continue the noninteractive review without waiting for user input', continuation)
        self.assertIn('Never end a response with progress text alone', continuation)
        schema = json.loads(args[args.index('--json-schema') + 1])
        self.assertNotIn('$schema', schema)
        self.assertIn('findings', schema['properties'])
        settings = json.loads(args[args.index('--settings') + 1])
        for phase in ('PreToolUse', 'PostToolUse'):
            self.assertEqual({row['matcher'] for row in settings['hooks'][phase]},
                             {'Read', 'Grep'})
        self.assertNotIn('readonly-bash-guard.py', json.dumps(settings))
        audit_commands = [
            hook['command']
            for phase in ('PreToolUse', 'PostToolUse')
            for matcher in settings['hooks'][phase]
            for hook in matcher['hooks']
            if 'review-read-audit.py' in hook['command']
        ]
        self.assertTrue(audit_commands)
        for audit_command in audit_commands:
            command_args = shlex.split(audit_command)
            self.assertEqual(command_args[command_args.index('--prompt') + 1], str(prompt))
            self.assertEqual(command_args[command_args.index('--deps') + 1], str(deps))

    def test_claude_reviewer_limits_session_reads_to_current_prompt(self):
        reviewer = (SHARED / 'agents/rev-reviewer.md').read_text()
        sonnet = (SHARED / 'agents/rev-reviewer-sonnet.md').read_text()
        for contract in (reviewer, sonnet):
            self.assertIn('exact review-session artifacts named in the current prompt', contract)
            self.assertIn('explicitly named pinned dependency roots', contract)
            self.assertIn('document inputs listed in the current prompt', contract)
            self.assertNotIn('the named review session', contract)

    def test_production_installer_atomically_replaces_bundle_and_preserves_marketplace(self):
        installer = module(REPO / 'scripts/install-codex-plugin.py')
        marketplace = self.root / '.agents/plugins/marketplace.json'
        marketplace.parent.mkdir(parents=True)
        other = {'name': 'another', 'source': {'source': 'local', 'path': './plugins/another'}}
        marketplace.write_text(json.dumps({'name': 'mine', 'interface': {'displayName': 'My plugins'},
                                          'plugins': [other]}))
        with patch.object(installer.Path, 'home', return_value=self.root), \
             patch.object(installer.shutil, 'which', return_value='/bin/codex'), \
             patch.object(installer.subprocess, 'run') as run, patch('sys.stdout', new=io.StringIO()):
            installer.install()
            manifest = self.root / 'plugins/review-council/.codex-plugin/plugin.json'
            first = json.loads(manifest.read_text())['version']
            prior_marker = manifest.parents[1] / 'prior-bundle'
            prior_marker.write_text('old\n')
            saved = marketplace.read_text()
            installer.install()
            self.assertNotEqual(first, json.loads(manifest.read_text())['version'])
            self.assertFalse(prior_marker.exists())
            self.assertEqual(saved, marketplace.read_text())
            run.assert_called_with(['codex', 'plugin', 'add', 'review-council@mine'], check=True)
        data = json.loads(saved)
        self.assertEqual(data['plugins'][0], other)
        self.assertEqual(data['interface'], {'displayName': 'My plugins'})
        self.assertEqual(data['plugins'][1]['policy']['installation'], 'AVAILABLE')


    def test_curl_installer_runs_without_checkout(self):
        cli = self.root / 'codex'
        cli.write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\n")
        cli.chmod(0o755)
        capture = self.root / 'install-commands'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   CAPTURE=str(capture))
        installer = (REPO / 'install-codex.sh').read_text()
        proc = subprocess.run(['bash', '-s', '--', '--ref', 'feat/codex-port'], input=installer,
                              cwd=self.root, env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(capture.read_text().splitlines(), [
            'plugin marketplace add WiktorStarczewski/review-council --ref feat/codex-port',
            'plugin add review-council@review-council'])

    def test_curl_installer_does_not_mask_marketplace_failure(self):
        cli = self.root / 'codex'
        cli.write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\nexit 19\n")
        cli.chmod(0o755)
        capture = self.root / 'install-commands'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   CAPTURE=str(capture))
        proc = subprocess.run(['bash'], input=(REPO / 'install-codex.sh').read_text(),
                              cwd=self.root, env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 19)
        self.assertEqual(len(capture.read_text().splitlines()), 1)


    def run_stack(self, missing_second_receipt=False):
        bundle = module(REPO / 'scripts/build-codex-plugin.py').build(self.root / 'review-council')
        (bundle / 'scripts/roster.sh').write_text('#!/bin/bash\nexit 0\n')
        cli = self.root / 'codex'
        cli.write_text('''#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
prompt = sys.stdin.read()
Path(os.environ['CAPTURE']).write_text(json.dumps({'args':sys.argv[1:], 'prompt':prompt,
    'leg':os.environ.get('REV_STACK_LEG'), 'host':os.environ.get('REVIEW_COUNCIL_HOST')}))
session = Path(re.search(r'use (.+) as the session dir', prompt).group(1))
(session/'findings.md').write_text('ledger')
if not (os.environ.get('MISS_SECOND') == '1' and os.environ.get('PASS') == '2'):
    (session/'stack-report.md').write_text('completed review')
    (session/'state.json').write_text(json.dumps({'phase':'stack-ready'}))
print('completed')
''')
        cli.chmod(0o755)
        config = self.root / 'config.sh'
        config.write_text('legs() { run_leg "' + str(self.root) + '" 1 fixture "Inspect the fixture"; }\n')
        root = self.root / 'sessions'
        capture = self.root / 'capture.json'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   ROOT=str(root), LOG=str(self.root / 'stack.log'), CAPTURE=str(capture),
                   REV_STACK_FOREGROUND='1', PASSES='2', POLL='1', MAX_ATTEMPTS='1',
                   MAX_INFRA_RETRIES='0', AUTH_WAIT_TRIES='1', STALL_SECS='30',
                   MISS_SECOND='1' if missing_second_receipt else '0')
        for key in ('NO_PUSH', 'NO_SQUASH', 'REV_ACTIVE', 'REV_STACK_LEG', 'REV_SCRIPTS'):
            env.pop(key, None)
        proc = subprocess.run([str(bundle / 'scripts/stack.sh'), str(config)],
                              env=env, text=True, capture_output=True, timeout=20)
        return proc, json.loads(capture.read_text())

    def test_codex_stack_launch_and_local_defaults(self):
        proc, capture = self.run_stack()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('NO_PUSH=1', proc.stdout)
        self.assertIn('NO_SQUASH=1', proc.stdout)
        self.assertEqual(capture['leg'], '1')
        self.assertEqual(capture['host'], 'codex')
        self.assertIn('workspace-write', capture['args'])
        self.assertIn('sandbox_workspace_write.network_access=true', capture['args'])
        self.assertNotIn('bypassPermissions', capture['args'])
        self.assertIn('Codex review-council skill at', capture['prompt'])
        self.assertIn('Read ', capture['prompt'])

    def test_old_receipt_cannot_complete_new_stack_pass(self):
        proc, _ = self.run_stack(missing_second_receipt=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn('invalid completion receipt (stack-report.md is missing)', proc.stdout)
        self.assertIn('COMPLETE WITH FAILURES', proc.stdout)


if __name__ == '__main__':
    unittest.main()
