"""Fresh plan generations retain their own root assignment and replacement chain."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_deleted_source_proof import SourceFixture, SCRIPTS


SEATS = ('sol', 'second', 'third', 'fourth')
BUNDLES = ('plan-completeness', 'plan-soundness', 'plan-simplicity', 'plan-tests')


class PlanGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plan-generations-')
        self.addCleanup(self.temp.cleanup)
        self.fixture = SourceFixture(Path(self.temp.name), 'plan')
        self.session = self.fixture.session

    def state(self, *args):
        return subprocess.run([str(SCRIPTS / 'rev-state.sh'), str(self.session), *args],
                              env=self.fixture.env, text=True, capture_output=True)

    def success(self, *args):
        result = self.state(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.session / 'state.json').read_text())

    def prepare(self, label, seats=SEATS):
        args = []
        for seat in seats:
            args += ['--assignment', seat + '=' + BUNDLES[SEATS.index(seat)]]
        if len(seats) == 1:
            args = ['--assignment', seats[0] + '=plan-completeness']
        plan = self.fixture.manifest['plan']
        self.fixture.run('prepare', str(self.session), label, '--phase', 'plan',
                         '--plan', str(self.session / 'fix-plan.md'), '--plan-sha256',
                         plan['sha256'], '--full-seat', seats[0], *args)
        path = self.session / f'r{label}-evidence.manifest.json'
        manifest = json.loads(path.read_text())
        panel = self.session / f'r{label}-panel.tsv'
        panel.write_text(''.join(seat + '\t' + assignment['bundle'] + '\tplan generation\n'
                                 for seat, assignment in manifest['assignments'].items()))
        result = subprocess.run([
            str(SCRIPTS / 'rev-prompt.sh'), str(self.session), label, '--panel', str(panel),
            '--phase', 'plan', '--evidence', str(path), '--plan',
            str(self.session / manifest['plan']['artifact'])], env=self.fixture.env,
            text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.fixture.run('verify', str(path))
        return path

    def complete(self, label, seats=SEATS):
        for seat in seats:
            (self.session / f'r{label}-{seat}.json').write_text(
                json.dumps({'summary': 'checked', 'findings': []}))
            (self.session / f'r{label}-{seat}.exit').write_text('0\n')

    def test_numbered_root_registers_and_its_own_replacement_allows_fix(self):
        self.success('phase=triage', 'round=3', 'open.P0=0', 'open.P1=1', 'open.P2=0')
        manifest = self.prepare('3p2')
        frozen = manifest.read_bytes()
        state = self.success('phase=plan', 'round=3p2', 'seats=' + json.dumps(SEATS))
        self.assertEqual(state.get('plans', {}).get('3p2'), list(SEATS),
                         'a prepared numbered plan generation must register its exact four seats')
        self.complete('3p2', SEATS[1:])
        (self.session / 'r3p2-sol.exit').write_text('2\n')
        (self.session / 'r3p2-sol.audit-invalid.json').write_text('{}\n')
        siblings = {path.name: path.read_bytes() for path in self.session.glob('r3p2-*')
                    if path.is_file()}
        self.assertEqual(self.state('phase=fix').returncode, 2)
        state = self.success('phase=plan', 'round=3p2x', 'seats=["fourth"]',
                             'plan_replacement_for=3p2:sol')
        self.assertEqual(state['plan_replacements']['3p2']['sol'], ['3p2x'])
        self.prepare('3p2x', ('fourth',))
        self.complete('3p2x', ('fourth',))
        self.success('phase=fix')
        self.assertEqual(manifest.read_bytes(), frozen)
        for name, raw in siblings.items():
            self.assertEqual((self.session / name).read_bytes(), raw)


    def test_newest_registered_generation_blocks_older_completion_and_skip(self):
        self.success('phase=triage', 'round=3', 'open.P0=0', 'open.P1=1', 'open.P2=0')
        self.prepare('3p')
        self.success('phase=plan', 'round=3p', 'seats=' + json.dumps(SEATS))
        self.complete('3p')
        self.success('phase=fix')
        (self.session / 'findings.md').write_text('Plan panel r3p - SKIPPED: historical exception\n')
        self.prepare('3p2')
        self.success('phase=plan', 'round=3p2', 'seats=' + json.dumps(SEATS))
        for round_label in ('3', '3p', '3p2'):
            result = self.state('phase=fix', 'round=' + round_label)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('r3p2', result.stderr)
        self.complete('3p2')
        self.success('phase=fix', 'round=3')
        self.success('phase=plan', 'round=3p3', 'seats=' + json.dumps(SEATS))
        self.assertEqual(self.state('phase=fix', 'round=3p2').returncode, 2)

    def test_skipped_plan_label_cannot_be_reprepared_with_changed_plan(self):
        self.success('phase=triage', 'round=3', 'open.P0=0', 'open.P1=1', 'open.P2=0')
        manifest = self.prepare('3p2')
        self.success('phase=plan', 'round=3p2', 'seats=' + json.dumps(SEATS))
        original_manifest = manifest.read_bytes()
        (self.session / 'findings.md').write_text(
            'Plan panel r3p2 - SKIPPED: plan generation was deferred\n')
        self.success('phase=fix')
        plan_path = self.session / 'fix-plan.md'
        original_plan = plan_path.read_text()
        updated_plan = original_plan.replace(
            'Keep active behavior after retirement.',
            'Keep active behavior stable after retirement.')
        self.assertNotEqual(updated_plan, original_plan)
        plan_path.write_text(updated_plan)
        state_path = self.session / 'state.json'
        original_state = state_path.read_bytes()
        stale_skip = self.state('phase=fix')
        self.assertEqual(stale_skip.returncode, 2, stale_skip.stderr)
        self.assertEqual(state_path.read_bytes(), original_state)
        plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        assignments = []
        for seat, bundle in zip(SEATS, BUNDLES):
            assignments += ['--assignment', seat + '=' + bundle]
        result = subprocess.run([
            sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare', str(self.session),
            '3p2', '--phase', 'plan', '--plan', str(plan_path), '--plan-sha256', plan_sha,
            '--full-seat', SEATS[0], *assignments], env=self.fixture.env,
            text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0,
                            'a skipped label must not be rebound to changed plan bytes')
        self.assertEqual(manifest.read_bytes(), original_manifest)

    def test_numbered_parent_binding_and_invalid_suffixes_fail_without_mutation(self):
        self.success('phase=triage', 'round=3', 'open.P0=0', 'open.P1=1', 'open.P2=0')
        self.prepare('3p2')
        self.success('phase=plan', 'round=3p2', 'seats=' + json.dumps(SEATS))
        (self.session / 'r3p2-sol.audit-invalid.json').write_text('{}\n')
        state_file = self.session / 'state.json'
        before = state_file.read_bytes()
        for label, binding in (
                ('3p1', None), ('3p02', None), ('3p0', None),
                ('3p2x1', '3p2:sol'), ('3p2x0', '3p2:sol'),
                ('3p2x', '3p:sol'), ('3p2x2', '3p2x:sol'),
                ('3p2x-fake', '3p2:sol'), ('3p2x', '3p2:second')):
            args = ['phase=plan', 'round=' + label, 'seats=["fourth"]']
            if binding is not None:
                args += ['plan_replacement_for=' + binding]
            with self.subTest(label=label, binding=binding):
                result = self.state(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(state_file.read_bytes(), before)
        self.success('phase=plan', 'round=3p2x02', 'seats=["fourth"]',
                     'plan_replacement_for=3p2:sol')

    def test_foreign_generation_child_cannot_complete_a_failed_assignment(self):
        self.success('phase=triage', 'round=3', 'open.P0=0', 'open.P1=1', 'open.P2=0')
        self.prepare('3p2')
        self.success('phase=plan', 'round=3p2', 'seats=' + json.dumps(SEATS))
        self.complete('3p2', SEATS[1:])
        (self.session / 'r3p2-sol.audit-invalid.json').write_text('{}\n')
        self.prepare('3p3x', ('fourth',))
        self.complete('3p3x', ('fourth',))
        self.success('plans.3p3x=["fourth"]', 'plan_replacements.3p2.sol=["3p3x"]')
        self.assertEqual(self.state('phase=fix').returncode, 2)



    def test_legacy_zero_padded_forms_remain_exact_and_alias_collision_refuses(self):
        self.success('phase=triage', 'round=3', 'open.P0=0', 'open.P1=1', 'open.P2=0')
        self.prepare('03p')
        self.success('phase=plan', 'round=03p', 'seats=' + json.dumps(SEATS))
        self.complete('03p', SEATS[1:])
        (self.session / 'r03p-sol.audit-invalid.json').write_text('{}\n')
        self.success('phase=plan', 'round=03px02', 'seats=["fourth"]',
                     'plan_replacement_for=03p:sol')
        self.prepare('03px02', ('fourth',))
        self.complete('03px02', ('fourth',))
        self.success('phase=fix', 'round=3')
        self.success('phase=plan', 'round=3p', 'seats=' + json.dumps(SEATS))
        result = self.state('phase=fix', 'round=3')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('ambiguous', result.stderr)



if __name__ == '__main__':
    unittest.main()
