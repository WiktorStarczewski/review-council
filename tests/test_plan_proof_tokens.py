"""Prepared search output belongs to one cluster even when bytes are shared."""
import hashlib
import importlib.util
import json
import re
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
            f"Sites: zz_current.py:{4 if index == 3 else 1}-{5 if index == 3 else 2} "
            f"(found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'active_{1 if index == 3 else 0:03d}' .)\n"
            'Test: zz_current.py:1-2 - active behavior stays observable\n'
            'Prediction: reverting the guard fails zz_current.py at active_000, '
            'because its returned value changes.\n'
            for index in range(1, 4)))
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
        self.assertEqual(len(proofs), 3)
        self.assertEqual(proofs[0]['sha256'], proofs[1]['sha256'])
        self.assertNotEqual(proofs[0]['artifact'], proofs[1]['artifact'])
        self.assertNotEqual(proofs[0]['sha256'], proofs[2]['sha256'])
        for seat in self.manifest['assignments']:
            with self.subTest(seat=seat):
                prompt = self.rendered_prompt(seat)
                self.fixture.run('verify', str(self.manifest_path))
                load_audit().validate_plan_prompt_binding(
                    self.manifest, seat, prompt, load_evidence())

    def test_shared_output_atomic_panel_publishes_all_four_prompts(self):
        panel = self.fixture.session / 'panel.tsv'
        panel.write_text(''.join(
            seat + '\t' + assignment['bundle'] + '\tshared synthetic search proof\n'
            for seat, assignment in self.manifest['assignments'].items()))
        result = subprocess.run([
            str(SCRIPTS / 'rev-prompt.sh'), str(self.fixture.session), '2p',
            '--panel', str(panel), '--evidence', str(self.manifest_path),
            '--phase', 'plan', '--plan',
            str(self.fixture.session / self.manifest['plan']['artifact'])],
            env=self.fixture.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0,
                         'shared search output must support atomic full-panel rendering: '
                         + result.stderr)
        for seat in self.manifest['assignments']:
            prompt = self.fixture.session / f'r2p-{seat}.prompt.md'
            self.assertTrue(prompt.is_file())
            load_audit().validate_plan_prompt_binding(
                self.manifest, seat, prompt, load_evidence())
        self.fixture.run('verify', str(self.manifest_path))

    def test_unique_legacy_prompt_remains_valid_without_rewriting(self):
        prompt = self.fixture.session / 'legacy.prompt.md'
        legacy = re.sub(r'(Prepared cluster search output: )C-[0-9]+ ',
                        r'\1', self.fixture.prompt.read_text())
        prompt.write_text(legacy)
        original = prompt.read_bytes()
        manifest_bytes = self.fixture.manifest_path.read_bytes()
        load_audit().validate_plan_prompt_binding(
            self.fixture.manifest, self.fixture.seat, prompt, load_evidence())
        self.fixture.run('verify', str(self.fixture.manifest_path))
        self.assertEqual(prompt.read_bytes(), original)
        self.assertEqual(self.fixture.manifest_path.read_bytes(), manifest_bytes)

    def test_shared_legacy_mixed_and_unknown_bindings_are_rejected(self):
        prompt = self.rendered_prompt()
        text = prompt.read_text()
        legacy = re.sub(r'(Prepared cluster search output: )C-[0-9]+ ', r'\1', text)
        mixed = text.replace('Prepared cluster search output: C-01 ',
                             'Prepared cluster search output: ', 1)
        unknown = text.replace('Prepared cluster search output: C-01 ',
                               'Prepared cluster search output: C-99 ', 1)
        for mutation in (legacy, mixed, unknown):
            with self.subTest(mutation=mutation[-100:]):
                with self.assertRaisesRegex(ValueError, 'bound plan evidence'):
                    load_audit().validate_plan_prompt_binding(
                        self.manifest, 'sol', prompt, load_evidence(), text=mutation)

    def test_unassigned_output_and_wrong_cluster_hash_are_rejected(self):
        prompt = self.rendered_prompt('second')
        text = prompt.read_text()
        cluster = self.manifest['plan']['clusters'][1]
        self.assertNotIn(cluster['id'],
                         self.manifest['assignments']['second']['plan_clusters'])
        body = (self.fixture.session / cluster['search_proof']['artifact']).read_text()
        injected = ('Prepared cluster search output: ' + cluster['id'] + ' '
                    + json.dumps(body, ensure_ascii=True, separators=(',', ':')))
        with self.assertRaisesRegex(ValueError, 'unassigned plan cluster'):
            load_audit().validate_plan_prompt_binding(
                self.manifest, 'second', prompt, load_evidence(), text=text + injected + '\n')
        first = self.manifest['plan']['clusters'][0]['search_proof']
        third = self.manifest['plan']['clusters'][2]['search_proof']
        wrong_hash = text.replace(first['sha256'], third['sha256'])
        with self.assertRaisesRegex(ValueError, 'bound plan evidence'):
            load_audit().validate_plan_prompt_binding(
                self.manifest, 'second', prompt, load_evidence(), text=wrong_hash)

    def test_missing_duplicate_and_swapped_output_bindings_are_rejected(self):
        prompt = self.rendered_prompt()
        text = prompt.read_text()
        audit = load_audit()
        module = load_evidence()
        output_lines = [line for line in text.splitlines()
                        if line.startswith('Prepared cluster search output:')]
        self.assertEqual(len(output_lines), 3)
        for mutation in (
                text.replace(output_lines[0] + '\n', '', 1),
                text + output_lines[0] + '\n',
                text.replace(output_lines[0], output_lines[1], 1),
                text.replace(output_lines[0], output_lines[2].replace(
                    'C-03 ', 'C-01 ', 1), 1)):
            with self.subTest(mutation=mutation[-100:]):
                with self.assertRaisesRegex(ValueError, 'bound plan evidence'):
                    audit.validate_plan_prompt_binding(
                        self.manifest, 'sol', prompt, module, text=mutation)


if __name__ == '__main__':
    unittest.main()
