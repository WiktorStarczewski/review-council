"""Pi must use enforced external transports and its own resumable workflow."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / 'plugins/review-council'


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PiHostTests(unittest.TestCase):
    def test_pi_never_selects_an_implicit_agent_even_when_requested(self):
        with patch.dict(os.environ, {'REVIEW_COUNCIL_HOST': 'pi',
                                     'REVIEW_COUNCIL_CLAUDE_ADAPTER': 'agent'}):
            roster = module(PLUGIN / 'scripts/lib/roster.py')
            self.assertEqual(roster.anthropic_adapter({}), 'claude')

    def test_pi_workhorse_accepts_host_and_requires_cli_for_anthropic(self):
        code = '''import sys, json
sys.path.insert(0, sys.argv[1])
import workhorse as w
print(json.dumps([w.host_name('pi'), w.sonnet_candidate('pi', 'missing'),
w.resolve_available('pi', luna=('gpt-6-luna', 'high'))]))
'''
        proc = subprocess.run(['python3', '-c', code, str(PLUGIN / 'scripts/lib')],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        host, sonnet, record = json.loads(proc.stdout)
        self.assertEqual(host, 'pi')
        self.assertIsNone(sonnet)
        self.assertEqual((record['host'], record['adapter']), ('pi', 'codex'))

    def test_pi_request_freezes_the_normal_roster_without_rewriting_user_config(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            config = session / 'user.json'
            config.write_text('{"extras": false}\n')
            env = dict(os.environ, REVIEW_COUNCIL_HOST='pi')
            proc = subprocess.run(['python3', str(PLUGIN / 'scripts/rev-panel-request.py'),
                                   '--text', 'branch', '--session', directory, '--base', str(config)],
                                  env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            request = json.loads((session / 'panel-request.json').read_text())
            self.assertEqual(request['host'], 'pi')
            self.assertEqual(config.read_text(), '{"extras": false}\n')

    def test_pi_high_request_selects_two_sol_and_two_opus_without_user_config_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            config = session / 'user.json'
            original = '{"claude_models":["opus","sonnet"],"extras":true}\n'
            config.write_text(original)
            proc = subprocess.run(['python3', str(PLUGIN / 'scripts/rev-panel-request.py'),
                                   '--text', 'mode: high\nbranch', '--session', directory,
                                   '--base', str(config)],
                                  env=dict(os.environ, REVIEW_COUNCIL_HOST='pi'),
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            selected = json.loads((session / 'roster-config.json').read_text())
            self.assertEqual(selected['codex_models'], ['latest-sol', 'latest-sol'])
            self.assertEqual(selected['claude_seats'], 2)
            self.assertNotIn('claude_models', selected)
            self.assertEqual(config.read_text(), original)

    def test_pi_high_valid_pinned_opus_models_can_replace_both_sol_seats(self):
        with patch.dict(os.environ, {'REVIEW_COUNCIL_HOST': 'pi'}):
            roster = module(PLUGIN / 'scripts/lib/roster.py')
        cfg = {'panel_mode': 'high', 'codex_models': ['gpt-5.6-sol'] * 2,
               'claude_seats': 2, 'min_labs': 1,
               'pin': {'opus': {'model': 'claude-opus-4-7'},
                       'opus-2': {'model': 'claude-opus-4-7'}}}
        kept, excluded = roster.opus_seats('claude', 2), []
        roster.apply_pins(cfg, kept)
        self.assertIsNone(roster.claude_pin_conflict(cfg, 2))
        roster.substitute_high_pairs(kept, excluded, cfg)
        clones = [seat for seat in kept if seat.get('substitutes_for')]
        self.assertEqual([seat['substitutes_for'] for seat in clones],
                         ['codex-sol', 'codex-sol-2'])
        self.assertEqual([seat['model'] for seat in clones],
                         ['claude-opus-4-7', 'claude-opus-4-7'])
        self.assertEqual(roster.enforce_exact_seats(cfg, kept, excluded), (None, None))

    def test_pi_resumption_selects_bundled_phase_files(self):
        brief = module(PLUGIN / 'scripts/rev-brief.py')
        self.assertEqual(brief.skill_dir('pi'), PLUGIN / 'pi-skills/review-council-rev')
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / 'state.json').write_text(json.dumps({'phase': 'fix'}))
            proc = subprocess.run(['python3', str(PLUGIN / 'scripts/rev-brief.py'),
                                   directory, '--host', 'pi'],
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)['phase_file'], 'phases/30-triage.md')


if __name__ == '__main__':
    unittest.main()
