"""Host orchestration cost: the injected skill stays small and the brief is compact."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins' / 'review-council'
BRIEF = PLUGIN / 'scripts' / 'rev-brief.py'
COST = PLUGIN / 'scripts' / 'rev-host-cost.py'
MECHANICAL = PLUGIN / 'scripts' / 'rev-mechanical.sh'


def load_cost():
    spec = importlib.util.spec_from_file_location('rev_host_cost', COST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HostCostTests(unittest.TestCase):
    def test_injected_skill_is_much_smaller_than_0_7_5(self):
        report = load_cost().report()
        claude = report['hosts']['claude']
        codex = report['hosts']['codex']
        self.assertLess(claude['after_bytes'], 16000)
        self.assertLess(codex['after_bytes'], 12000)
        self.assertGreater(claude['saved_tokens_per_turn'], 15000)
        self.assertGreater(codex['saved_tokens_per_turn'], 10000)
        self.assertIn('phases/20-discovery.md',
                      (PLUGIN / 'skills/rev/SKILL.md').read_text())

    def test_brief_names_one_phase_file_and_a_mechanical_model(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            (session / 'state.json').write_text(json.dumps({
                'phase': 'publish', 'round': 2, 'open.P0': 0, 'open.P1': 1}))
            config = session / 'config.json'
            config.write_text(json.dumps({
                'host_mechanical_model': 'claude-haiku', 'status_tick': False}))
            result = subprocess.run(
                ['python3', str(BRIEF), str(session), '--host', 'claude',
                 '--config', str(config)],
                check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(result.stdout)
            self.assertEqual(document['phase_file'], 'phases/70-publish.md')
            self.assertTrue(document['mechanical'])
            self.assertEqual(document['model'], 'claude-haiku')
            self.assertFalse(document['status_tick'])

    def test_closeout_is_one_call_and_ci_without_a_run_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            (session / 'state.json').write_text(json.dumps({'phase': 'fix'}))
            closeout = subprocess.run(
                [str(MECHANICAL), 'closeout', str(session)],
                check=False, capture_output=True, text=True)
            self.assertEqual(closeout.returncode, 0, closeout.stderr)
            self.assertIn('phases/50-fix.md', closeout.stdout)
            missing = subprocess.run(
                [str(MECHANICAL), 'ci', str(session)],
                check=False, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
