"""Prepared search output belongs to one cluster even when bytes are shared."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_deleted_source_proof import SourceFixture, SCRIPTS, load_evidence


def load_audit():
    spec = importlib.util.spec_from_file_location(
        'plan_proof_token_audit', SCRIPTS / 'lib/review-read-audit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlanProofTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plan-proof-tokens-')
        self.addCleanup(self.temp.cleanup)
        self.fixture = SourceFixture(Path(self.temp.name), 'plan')
        plan = self.fixture.session / 'shared-plan.md'
        plan.write_text(''.join(
            f'## C-{index:02d} - preserve active behavior {index}\n'
            f'Findings: F-{index:03d} (P1)\nRule: Keep active behavior.\n'
            "Sites: zz_current.py:1-2 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'active_000' .)\n"
            'Test: zz_current.py:1-2 - active behavior stays observable\n'
            'Prediction: reverting the guard fails zz_current.py at active_000, '
            'because its returned value changes.\n'
            for index in range(1, 3)))
        assignments = []
        for seat, bundle in zip(('sol', 'second', 'third', 'fourth'),
                                ('plan-completeness', 'plan-soundness',
                                 'plan-simplicity', 'plan-tests')):
            assignments += ['--assignment', seat + '=' + bundle]
        self.fixture.run(
            'prepare', str(self.fixture.session), '2p', '--phase', 'plan',
            '--full-seat', 'sol', '--plan', str(plan), '--plan-sha256',
            hashlib.sha256(plan.read_bytes()).hexdigest(), *assignments)
        self.manifest_path = self.fixture.session / 'r2p-evidence.manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text())

    def render(self, seat):
        assignment = self.manifest['assignments'][seat]
        return subprocess.run([
            str(SCRIPTS / 'rev-prompt.sh'), str(self.fixture.session), '2p',
            seat, assignment['bundle'], 'shared synthetic search proof',
            '--evidence', str(self.manifest_path), '--phase', 'plan', '--plan',
            str(self.fixture.session / self.manifest['plan']['artifact'])],
            env=self.fixture.env, text=True, capture_output=True)

    def rendered_prompt(self, seat='sol'):
        result = self.render(seat)
        self.assertEqual(result.returncode, 0,
                         'distinct clusters with identical search output must render: '
                         + result.stderr)
        return self.fixture.session / f'r2p-{seat}.prompt.md'

    def test_shared_output_renders_all_four_seats_and_verifies(self):
        self.assertEqual(self.manifest['schema_version'], 4)
        proofs = [row['search_proof'] for row in self.manifest['plan']['clusters']]
        self.assertEqual(len(proofs), 2)
        self.assertEqual(proofs[0]['sha256'], proofs[1]['sha256'])
        self.assertNotEqual(proofs[0]['artifact'], proofs[1]['artifact'])
        for seat in self.manifest['assignments']:
            with self.subTest(seat=seat):
                prompt = self.rendered_prompt(seat)
                self.fixture.run('verify', str(self.manifest_path))
                load_audit().validate_plan_prompt_binding(
                    self.manifest, seat, prompt, load_evidence())

    def test_missing_duplicate_and_swapped_output_bindings_are_rejected(self):
        prompt = self.rendered_prompt()
        text = prompt.read_text()
        audit = load_audit()
        module = load_evidence()
        output_lines = [line for line in text.splitlines()
                        if line.startswith('Prepared cluster search output:')]
        self.assertEqual(len(output_lines), 2)
        for mutation in (
                text.replace(output_lines[0] + '\n', '', 1),
                text + output_lines[0] + '\n',
                text.replace(output_lines[0], output_lines[1], 1)):
            with self.subTest(mutation=mutation[-100:]):
                with self.assertRaisesRegex(ValueError, 'bound plan evidence'):
                    audit.validate_plan_prompt_binding(
                        self.manifest, 'sol', prompt, module, text=mutation)


if __name__ == '__main__':
    unittest.main()
