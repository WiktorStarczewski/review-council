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

    def test_cursor_prefers_cursor_grok_over_luna_and_sonnet(self):
        chosen = self.workhorse.resolve_available(
            'cursor', luna=('gpt-5.6-luna', 'high'),
            sonnet=self.workhorse.sonnet_candidate('cursor', None),
            cursor_grok=('cursor-grok-4.6-high', 'high'))
        self.assertEqual(chosen['family'], 'cursor-grok')
        self.assertEqual(chosen['model'], 'cursor-grok-4.6-high')
        self.assertEqual(chosen['effort'], 'high')
        self.assertEqual(chosen['adapter'], 'cursor-agent')
        self.assertEqual(chosen['available'], ['cursor-grok', 'luna', 'sonnet'])

    def test_cursor_grok_is_not_a_workhorse_off_cursor(self):
        chosen = self.workhorse.resolve_available(
            'codex', luna=('gpt-5.6-luna', 'high'),
            sonnet=self.workhorse.sonnet_candidate('codex', None),
            cursor_grok=('cursor-grok-4.6-high', 'high'))
        self.assertEqual(chosen['family'], 'luna')
        self.assertEqual(chosen['available'], ['luna', 'sonnet'])

    def test_claude_uses_sonnet_agent_without_the_cli_and_luna_when_sonnet_is_absent(self):
        agent = self.workhorse.resolve_available(
            'claude', luna=('gpt-5.6-luna', 'high'),
            sonnet=self.workhorse.sonnet_candidate('claude', 'not installed'))
        self.assertEqual((agent['family'], agent['adapter'], agent['model'], agent['effort']),
                         ('sonnet', 'agent', 'sonnet', 'high'))
        luna = self.workhorse.resolve_available(
            'codex', luna=('gpt-5.6-luna', 'high'),
            sonnet=self.workhorse.sonnet_candidate('codex', 'not installed'))
        self.assertEqual(luna['family'], 'luna')
        none = self.workhorse.resolve_available(
            'codex', sonnet=self.workhorse.sonnet_candidate('codex', 'not signed in'))
        self.assertIsNone(none['family'])
        self.assertEqual(none['available'], [])
        self.assertNotIn('seat', none)

    def test_newest_cursor_grok_at_high_ignores_fast_and_frontier_grok(self):
        text = '\n'.join([
            'grok-4.7-high - Grok 4.7 High',
            'cursor-grok-4.5-high - Grok 4.5',
            'cursor-grok-4.6-xhigh - Grok 4.6 Extra High',
            'cursor-grok-4.6-high-fast - Grok 4.6 Fast',
            'cursor-grok-4.6-high - Grok 4.6',
            'auto - Auto',
        ])
        self.assertEqual(self.workhorse.select_cursor_grok(text), ('cursor-grok-4.6-high', 'high'))
        only_xhigh = 'cursor-grok-4.6-xhigh - Grok 4.6 Extra High\n'
        self.assertEqual(self.workhorse.select_cursor_grok(only_xhigh),
                         ('cursor-grok-4.6-xhigh', 'xhigh'))

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
            'cursor', cursor_grok=('cursor-grok-4.6-high', 'high'))
        review = self.workhorse.launch_spec(
            grok, 'review', '/repo', '/session', '/session/prompt.md', out='/session/out.json')
        self.assertEqual(review['argv'][0], 'agent')
        self.assertIn('--mode', review['argv'])
        self.assertIn('ask', review['argv'])
        self.assertNotIn('--force', review['argv'])
        self.assertNotIn('disabled', review['argv'])
        implement = self.workhorse.launch_spec(
            grok, 'implement', '/repo', '/session', '/session/prompt.md', cluster='C-03')
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
