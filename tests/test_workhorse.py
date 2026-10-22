"""Workhorse selection never calls a model."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


LIB = Path(__file__).resolve().parents[1] / 'plugins/review-council/scripts/lib/workhorse.py'


def load():
    spec = importlib.util.spec_from_file_location('workhorse_under_test', LIB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkhorseTests(unittest.TestCase):
    def setUp(self):
        self.workhorse = load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def luna(self, slug='gpt-5.6-luna', efforts=('high', 'xhigh')):
        return slug, 'high' if 'high' in efforts else efforts[0]

    def listed(self, models):
        path = Path(self.temp.name) / 'catalog.json'
        path.write_text(json.dumps({'models': models}))
        listed, error = self.workhorse.codex_catalog(path)
        self.assertIsNone(error)
        return listed

    def model(self, slug, efforts=('high', 'xhigh'), visibility='list'):
        return {'slug': slug, 'visibility': visibility,
                'supported_reasoning_levels': [{'effort': effort} for effort in efforts]}

    def test_cursor_tries_grok_then_the_normal_chain(self):
        grok = ('grok-4.7-xhigh', 'xhigh')
        sonnet = self.workhorse.sonnet_candidate('cursor', None)
        opus = self.workhorse.opus_candidate('cursor', None)
        chosen = self.workhorse.resolve_available(
            'cursor', luna=('gpt-5.6-luna', 'high'), sol=('gpt-5.6-sol', 'high'),
            sonnet=sonnet, opus=opus, cursor_grok=grok)
        self.assertEqual(chosen['family'], 'cursor-grok')
        self.assertEqual(chosen['available'],
                         ['cursor-grok', 'luna', 'sonnet', 'sol', 'opus'])
        without_grok = self.workhorse.resolve_available(
            'cursor', luna=('gpt-5.6-luna', 'high'), sonnet=sonnet, opus=opus)
        self.assertEqual(without_grok['family'], 'luna')
        only_later = self.workhorse.resolve_available(
            'cursor', sol=('gpt-5.6-sol', 'xhigh'), opus=opus)
        self.assertEqual(only_later['family'], 'sol')
        self.assertEqual(only_later['available'], ['sol', 'opus'])

    def test_every_host_prefers_cursor_grok_then_falls_back_to_luna(self):
        grok = ('grok-4.7-xhigh', 'xhigh')
        for host in ('claude', 'codex', 'cursor'):
            sonnet = self.workhorse.sonnet_candidate(host, None)
            opus = self.workhorse.opus_candidate(host, None)
            chosen = self.workhorse.resolve_available(
                host, luna=('gpt-5.6-luna', 'high'), sol=('gpt-5.6-sol', 'high'),
                sonnet=sonnet, opus=opus, cursor_grok=grok)
            self.assertEqual(chosen['family'], 'cursor-grok', host)
            self.assertEqual(chosen['adapter'], 'cursor-agent', host)
            self.assertEqual(chosen['model'], 'grok-4.7-xhigh', host)
            self.assertEqual(chosen['available'],
                             ['cursor-grok', 'luna', 'sonnet', 'sol', 'opus'], host)
            without_grok = self.workhorse.resolve_available(
                host, luna=('gpt-5.6-luna', 'high'), sonnet=sonnet, opus=opus)
            self.assertEqual(without_grok['family'], 'luna', host)
            self.assertEqual(without_grok['adapter'], 'codex', host)
            self.assertNotIn('cursor-grok', without_grok['available'], host)
            only_grok = self.workhorse.resolve_available(host, cursor_grok=grok)
            self.assertEqual(only_grok['family'], 'cursor-grok', host)
            self.assertEqual(only_grok['available'], ['cursor-grok'], host)

    def test_review_escalation_never_seats_the_cursor_writer(self):
        rows = [{'seat': 'codex-luna', 'adapter': 'codex', 'model': 'gpt-5.6-luna',
                 'effort': 'high', 'extra': False}]
        candidates = {
            'cursor-grok': {'adapter': 'cursor-agent', 'model': 'grok-4.7-xhigh',
                            'effort': 'xhigh', 'lab': 'cursor'},
            'luna': {'adapter': 'codex', 'model': 'gpt-5.6-luna', 'effort': 'high',
                     'lab': 'openai'},
            'sonnet': {'adapter': 'claude', 'model': 'sonnet', 'effort': 'high',
                       'lab': 'anthropic'},
            'sol': None,
            'opus': None,
        }
        for host in ('claude', 'codex', 'cursor'):
            chosen, existing = self.workhorse.choose_escalation(host, 'luna', rows, candidates)
            self.assertFalse(existing, host)
            self.assertEqual(chosen['adapter'], 'claude', host)
            self.assertEqual(chosen['model'], 'sonnet', host)

    def test_escalate_does_not_probe_the_cursor_writer(self):
        session = Path(self.temp.name) / 'escalate'
        session.mkdir()
        record = self.workhorse.resolve_available('codex', luna=('gpt-5.6-luna', 'high'))
        self.workhorse.write_record(session / 'workhorse.json', record)
        (session / 'roster.json').write_text(json.dumps({'seats': [
            {'seat': 'codex-luna', 'adapter': 'codex', 'model': 'gpt-5.6-luna',
             'effort': 'high', 'extra': False}]}))
        seen = []
        original = self.workhorse._candidates

        def spy(host, include_cursor=True):
            seen.append((host, include_cursor))
            return {}, {
                'cursor-grok': {'adapter': 'cursor-agent', 'model': 'grok-4.7-xhigh',
                                'effort': 'xhigh', 'lab': 'cursor'},
                'luna': None,
                'sonnet': {'adapter': 'claude', 'model': 'sonnet', 'effort': 'high',
                           'lab': 'anthropic'},
                'sol': None,
                'opus': None,
            }

        self.workhorse._candidates = spy
        try:
            chosen = self.workhorse.escalate(session, 'codex-luna')
        finally:
            self.workhorse._candidates = original
        self.assertEqual(seen, [('codex', False)])
        self.assertEqual(chosen['family'], 'sonnet')
        self.assertTrue(chosen['existing'] is False)

    def test_credit_or_auth_failure_blocks_a_failed_cursor_run_only(self):
        blocked = self.workhorse.cursor_writer_blocked
        self.assertTrue(blocked(1, '', 'You are out of credits'))
        self.assertTrue(blocked(1, 'hit your limit', ''))
        self.assertTrue(blocked(1, '', 'please log in'))
        self.assertTrue(blocked(1, 'payment required', ''))
        self.assertFalse(blocked(0, 'out of credits stays in the plan\n## C-01\n', ''))
        self.assertFalse(blocked(1, 'the cluster heading was missing', ''))
        quoted = 'rate_limit\n' * 500
        self.assertFalse(blocked(1, quoted, ''))
        self.assertTrue(blocked(1, quoted, 'out of credits'))
        self.assertFalse(blocked(1, '## C-01\nout of credits\n', ''))

    def test_stray_cursor_exit_4_stays_an_ordinary_failure(self):
        status = self.workhorse.cursor_launch_status
        self.assertEqual(status(4, '', 'out of credits'), 4)
        self.assertEqual(status(4, 'model failed to start', ''), 1)
        self.assertIsNone(status(0, 'out of credits', ''))
        self.assertIsNone(status(2, 'model failed to start', ''))

    def test_advance_past_cursor_grok_uses_luna_and_does_not_return(self):
        original = self.workhorse._candidates
        try:
            for host in ('claude', 'codex', 'cursor'):
                session = Path(self.temp.name) / host
                session.mkdir()
                current = self.workhorse.resolve_available(
                    host, luna=('gpt-5.6-luna', 'high'),
                    sonnet=self.workhorse.sonnet_candidate(host, None),
                    cursor_grok=('grok-4.7-xhigh', 'xhigh'))
                self.workhorse.write_record(session / 'workhorse.json', current)

                def fake(_host, bound=host):
                    self.assertEqual(_host, bound)
                    return {}, {
                        'cursor-grok': {'adapter': 'cursor-agent',
                                        'model': 'grok-4.7-xhigh',
                                        'effort': 'xhigh', 'lab': 'cursor'},
                        'luna': {'adapter': 'codex', 'model': 'gpt-5.6-luna',
                                 'effort': 'high', 'lab': 'openai'},
                        'sonnet': {'adapter': 'claude', 'model': 'sonnet',
                                   'effort': 'high', 'lab': 'anthropic'},
                        'sol': None,
                        'opus': None,
                    }

                self.workhorse._candidates = fake
                nxt = self.workhorse.advance(session)
                self.assertEqual((nxt['host'], nxt['family'], nxt['adapter']),
                                 (host, 'luna', 'codex'))
                self.assertNotIn('cursor-grok', nxt['available'])
                again = self.workhorse.advance(session)
                self.assertEqual(again['family'], 'sonnet', host)
                self.assertNotIn('cursor-grok', again['available'])
        finally:
            self.workhorse._candidates = original

    def test_escalation_walks_past_a_family_that_cannot_launch(self):
        rows = [{'seat': 'grok-1', 'adapter': 'cursor-sdk', 'model': 'grok-4.6',
                 'effort': 'xhigh', 'extra': False}]
        candidates = {
            'luna': None,
            'sonnet': {'adapter': 'agent', 'model': 'sonnet', 'effort': 'high',
                       'lab': 'anthropic'},
            'sol': {'adapter': 'codex', 'model': 'gpt-5.6-sol', 'effort': 'high',
                    'lab': 'openai'},
            'opus': {'adapter': 'claude', 'model': 'opus', 'effort': 'high',
                     'lab': 'anthropic'},
        }
        chosen, existing = self.workhorse.choose_escalation('cursor', 'cursor-grok', rows, candidates)
        self.assertFalse(existing)
        self.assertEqual(chosen['seat'], 'escalate-sol')
        self.assertEqual(chosen['model'], 'gpt-5.6-sol')
        seated = rows + [{'seat': 'codex-luna', 'adapter': 'codex', 'model': 'gpt-5.6-luna',
                          'effort': 'xhigh', 'extra': False}]
        reused, existing = self.workhorse.choose_escalation('cursor', 'cursor-grok', seated, candidates)
        self.assertTrue(existing)
        self.assertEqual(reused['seat'], 'codex-luna')
        self.assertIsNone(self.workhorse.choose_escalation('claude', 'opus', seated, {}))

    def test_claude_uses_luna_before_its_own_sonnet_agent(self):
        chosen = self.workhorse.resolve_available(
            'claude', luna=('gpt-5.6-luna', 'high'),
            sonnet=self.workhorse.sonnet_candidate('claude', 'not installed'))
        self.assertEqual((chosen['family'], chosen['adapter'], chosen['model']),
                         ('luna', 'codex', 'gpt-5.6-luna'))
        fallback = self.workhorse.resolve_available(
            'claude', sonnet=self.workhorse.sonnet_candidate('claude', 'not installed'))
        self.assertEqual((fallback['family'], fallback['adapter'], fallback['effort']),
                         ('sonnet', 'agent', 'high'))
        none = self.workhorse.resolve_available(
            'codex', sonnet=self.workhorse.sonnet_candidate('codex', 'not signed in'))
        self.assertIsNone(none['family'])
        self.assertEqual(none['available'], [])
        self.assertNotIn('seat', none)

    def test_a_prior_host_ordered_record_still_loads(self):
        session = Path(self.temp.name)
        document = {
            'version': 1, 'host': 'claude', 'family': 'sonnet', 'lab': 'anthropic',
            'seat': 'workhorse', 'adapter': 'agent', 'model': 'sonnet', 'effort': 'high',
            'available': ['sonnet', 'luna'],
            'reason': 'host claude; selected sonnet',
        }
        (session / 'workhorse.json').write_text(json.dumps(document))
        loaded = self.workhorse.read_record(session / 'workhorse.json')
        self.assertEqual(loaded['family'], 'sonnet')
        self.assertEqual(self.workhorse.plan_seat(session)['adapter'], 'agent')

    def test_writer_grok_is_grok_4_7_xhigh_only(self):
        text = '\n'.join([
            'grok-4.7-high - Grok 4.7 High',
            'grok-4.7-xhigh-fast - Grok 4.7 Extra High Fast',
            'cursor-grok-4.6-high - Grok 4.6',
            'cursor-grok-4.6-xhigh - Grok 4.6 Extra High',
            'grok-4.7-xhigh - Grok 4.7 Extra High',
            'auto - Auto',
        ])
        self.assertEqual(self.workhorse.select_cursor_grok(text), ('grok-4.7-xhigh', 'xhigh'))
        without = 'grok-4.7-high - Grok 4.7 High\ncursor-grok-4.6-xhigh - Grok 4.6 Extra High\n'
        self.assertIsNone(self.workhorse.select_cursor_grok(without))

    def test_newest_luna_prefers_high_and_skips_hidden_models(self):
        listed = self.listed([
            self.model('gpt-5.5-luna'),
            self.model('gpt-5.6-luna', ('xhigh', 'max')),
            self.model('gpt-9-luna', visibility='hide'),
            self.model('gpt-5.6-sol'),
        ])
        self.assertEqual(self.workhorse.select_luna(listed), ('gpt-5.6-luna', 'xhigh'))
        listed = self.listed([self.model('gpt-5.6-luna', ('high', 'xhigh'))])
        self.assertEqual(self.workhorse.select_luna(listed), ('gpt-5.6-luna', 'high'))

    def test_overlay_adds_the_workhorse_only_when_the_plan_seats_it(self):
        roster = {'seats': [{'seat': 'codex-sol', 'adapter': 'codex', 'model': 'gpt-5.6-sol',
                             'effort': 'xhigh', 'extra': False}]}
        row = {'seat': 'workhorse', 'lab': 'openai', 'adapter': 'codex', 'model': 'gpt-5.6-luna',
               'effort': 'high', 'extra': False}
        untouched = self.workhorse.overlay_roster(roster, row, ['codex-sol'])
        self.assertEqual(untouched['seats'], roster['seats'])
        overlaid = self.workhorse.overlay_roster(roster, row, ['workhorse'])
        self.assertEqual(overlaid['seats'][-1]['model'], 'gpt-5.6-luna')
        self.assertEqual(len(roster['seats']), 1)
        clash = {'seats': [{'seat': 'workhorse', 'adapter': 'claude', 'model': 'sonnet',
                            'effort': 'xhigh', 'extra': False}]}
        with self.assertRaises(ValueError):
            self.workhorse.overlay_roster(clash, row, ['workhorse'])

    def test_lookup_uses_the_workhorse_when_the_roster_does_not_seat_it(self):
        session = Path(self.temp.name)
        record = self.workhorse.resolve_available('codex', luna=('gpt-5.6-luna', 'high'))
        (session / 'workhorse.json').write_text(json.dumps(record))
        (session / 'roster.json').write_text(json.dumps({
            'seats': [{'seat': 'codex-sol', 'adapter': 'codex', 'model': 'gpt-5.6-sol',
                       'effort': 'xhigh'}]}))
        row = self.workhorse.lookup_launch(session / 'roster.json', 'workhorse')
        self.assertEqual(row['adapter'], 'codex')
        self.assertEqual(row['effort'], 'high')
        self.assertEqual(self.workhorse.lookup_adapter(session / 'roster.json', 'codex-sol'), 'codex')
        self.assertIsNotNone(self.workhorse.plan_seat(session))

    def test_launch_spec_keeps_review_on_rev_seat_and_implementation_writable(self):
        luna = self.workhorse.resolve_available('codex', luna=('gpt-5.6-luna', 'high'))
        with self.assertRaises(ValueError):
            self.workhorse.launch_spec(luna, 'review', '/repo', '/session', '/session/prompt.md')
        plan = self.workhorse.launch_spec(luna, 'plan', '/repo', '/session', '/session/prompt.md')
        self.assertEqual(plan['kind'], 'exec')
        self.assertIn('workspace-write', plan['argv'])
        self.assertNotIn('read-only', plan['argv'])
        self.assertIn('gpt-5.6-luna', plan['argv'])
        self.assertIn('model_reasoning_effort=high', plan['argv'])
        self.assertEqual(plan['cwd'], '/repo')
        self.assertNotIn('--force', plan['argv'])
        grok = self.workhorse.resolve_available(
            'cursor', cursor_grok=('grok-4.7-xhigh', 'xhigh'))
        review = self.workhorse.launch_spec(
            grok, 'review', '/repo', '/session', '/session/prompt.md', out='/session/out.json')
        self.assertEqual(review['argv'][0], 'agent')
        self.assertIn('grok-4.7-xhigh', review['argv'])
        self.assertIn('--mode', review['argv'])
        self.assertIn('ask', review['argv'])
        self.assertNotIn('--force', review['argv'])
        self.assertNotIn('disabled', review['argv'])
        implement = self.workhorse.launch_spec(
            grok, 'implement', '/repo', '/session', '/session/prompt.md', cluster='C-03')
        self.assertIn('grok-4.7-xhigh', implement['argv'])
        self.assertIn('disabled', implement['argv'])
        self.assertNotIn('--force', implement['argv'])
        self.assertNotIn('--yolo', implement['argv'])
        sonnet = self.workhorse.resolve_available(
            'claude', sonnet=self.workhorse.sonnet_candidate('claude', 'not installed'))
        agent = self.workhorse.launch_spec(
            sonnet, 'implement', '/repo', '/session', '/session/prompt.md', cluster='C-03')
        self.assertEqual(agent['kind'], 'agent')
        self.assertEqual(agent['agent'], 'review-council:rev-workhorse')
        review_agent = self.workhorse.launch_spec(
            sonnet, 'review', '/repo', '/session', '/session/prompt.md', out='/session/out.json')
        self.assertEqual(review_agent['agent'], 'review-council:rev-workhorse-review')

    def test_plan_and_findings_bodies_drop_fences(self):
        self.assertEqual(self.workhorse.plan_markdown('```markdown\n## C-03 · hold\n```\n'),
                         '## C-03 · hold\n')
        with self.assertRaises(ValueError):
            self.workhorse.plan_markdown('the plan follows\n## C-03\n')
        body = self.workhorse.findings_json('note\n```json\n{"findings": []}\n```')
        self.assertEqual(json.loads(body), {'findings': []})

    def test_prompt_names_the_cluster_and_forbids_commits(self):
        record = self.workhorse.resolve_available('codex', luna=('gpt-5.6-luna', 'high'))
        text = self.workhorse.prompt_text(record, 'implement', '/repo', '/session', cluster='C-03',
                                          plan='## C-03\n')
        self.assertIn('Implement only cluster C-03', text)
        self.assertIn('Do not commit', text)
        self.assertIn('gpt-5.6-luna', text)
