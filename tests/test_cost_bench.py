"""Provider-free safety contracts for repeatable paid benchmark runs."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'eval'))
try:
    spec = importlib.util.spec_from_file_location('cost_bench', REPO / 'eval/cost_bench.py')
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
except FileNotFoundError:
    bench = None


class CostBenchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bench, 'bounded benchmark runner is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reservation_survives_failure_and_resume_without_retry(self):
        ledger = self.root / 'budget.json'
        first = bench.Budget(ledger, {'model': 'terra'}, 2)
        self.assertTrue(first.reserve('case/baseline'))
        resumed = bench.Budget(ledger, {'model': 'terra'}, 2)
        self.assertFalse(resumed.reserve('case/baseline'))
        self.assertTrue(resumed.reserve('case/candidate'))
        with self.assertRaisesRegex(ValueError, 'budget'):
            resumed.reserve('extra/candidate')
        self.assertEqual(len(json.loads(ledger.read_text())['attempts']), 2)

    def test_changed_identity_or_budget_refuses_resumption(self):
        ledger = self.root / 'budget.json'
        bench.Budget(ledger, {'source': 'one'}, 4).reserve('first')
        for identity, maximum in (({'source': 'two'}, 4), ({'source': 'one'}, 5)):
            with self.assertRaisesRegex(ValueError, 'identity|budget'):
                bench.Budget(ledger, identity, maximum)

    def test_corrupt_ledger_never_resets_call_count(self):
        ledger = self.root / 'budget.json'
        ledger.write_text('{broken')
        with self.assertRaises(ValueError):
            bench.Budget(ledger, {}, 4)

    def test_source_freeze_includes_untracked_helpers_and_modes(self):
        source = self.root / 'source'
        source.mkdir()
        helper = source / 'new.py'
        helper.write_text('print(1)\n')
        destination = self.root / 'snapshot'
        identity = bench.snapshot_tree(source, destination)
        self.assertEqual((destination / 'new.py').read_bytes(), b'print(1)\n')
        self.assertEqual(identity, bench.tree_identity(destination))
        helper.chmod(0o755)
        self.assertNotEqual(identity, bench.tree_identity(source))

    def test_external_symlink_is_not_frozen_as_source(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'escaped').symlink_to(self.root / 'outside')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            bench.snapshot_tree(source, self.root / 'snapshot')

    def test_writable_subject_copy_preserves_read_only_frozen_source(self):
        source = self.root / 'sealed'
        (source / 'nested').mkdir(parents=True)
        (source / 'nested/value.py').write_text('before\n')
        for path in [*source.rglob('*'), source]:
            path.chmod(path.stat().st_mode & ~0o200)
        identity = bench.tree_identity(source)
        target = self.root / 'work'
        bench.snapshot_tree(source, target)
        bench.make_worktree_writable(target)
        bench.git(target, 'init', '-q')
        (target / 'nested/value.py').write_text('after\n')
        self.assertEqual(bench.tree_identity(source), identity)
        self.assertEqual((source / 'nested/value.py').read_text(), 'before\n')
        self.assertTrue((target / '.git').is_dir())

    def test_prepared_batch_can_report_with_its_archived_engine(self):
        candidate = self.root / 'candidate'
        plugin = candidate / 'plugins/review-council'
        plugin.parent.mkdir(parents=True)
        bench.snapshot_tree(REPO / 'plugins/review-council', plugin)
        bench.git(candidate, 'init', '-q', '-b', 'main')
        bench.git(candidate, 'add', '.')
        bench.git(candidate, '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture',
                  '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
        original = bench.command

        def command(argv, *args, **kwargs):
            return 'codex-fixture' if argv == ['codex', '--version'] else original(argv, *args, **kwargs)

        out = self.root / 'batch'
        with patch.object(bench, 'command', command):
            bench.prepare(out, 'main', candidate, 4)
        result = bench.command([sys.executable, str(out / 'engine/eval/cost_bench.py'),
                                'report', '--out', str(out)])
        self.assertIn('0/4 reserved', result)
        self.assertFalse((out / 'budget.json').exists())
        self.assertEqual(json.loads((out / 'report.json').read_text())['manifest']['identity']['engine'],
                         bench.engine_identity())

    def test_timeout_preserves_partial_output(self):
        log = self.root / 'partial.log'
        result = bench.run_process(
            [sys.executable, '-u', '-c', 'import time; print("partial"); time.sleep(30)'],
            self.root, dict(os.environ), log, 0.25)
        self.assertTrue(result['timed_out'])
        self.assertNotEqual(result['exit_code'], 0)
        self.assertIn('partial', log.read_text())
        self.assertLess(result['wall_seconds'], 5)

    def test_interrupt_cancels_owned_child(self):
        original_wait = bench.subprocess.Popen.wait
        interrupted = []

        def first_interrupt(process, timeout=None):
            if not interrupted:
                interrupted.append(process.pid)
                raise KeyboardInterrupt
            return original_wait(process, timeout=timeout)

        with patch.object(bench.subprocess.Popen, 'wait', first_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                bench.run_process([sys.executable, '-c', 'import time; time.sleep(30)'],
                                  self.root, dict(os.environ), self.root / 'interrupt.log', 20)
        try:
            with self.assertRaises(ProcessLookupError):
                os.kill(interrupted[0], 0)
        finally:
            try:
                os.kill(interrupted[0], 9)
                os.waitpid(interrupted[0], 0)
            except (ProcessLookupError, ChildProcessError):
                pass

    def test_schedule_reverses_second_case_and_rejects_insufficient_budget(self):
        cases = [{'id': 'first'}, {'id': 'second'}]
        self.assertEqual(bench.schedule(cases, 4), [
            ('first', 'baseline'), ('first', 'candidate'),
            ('second', 'candidate'), ('second', 'baseline')])
        with self.assertRaisesRegex(ValueError, 'budget'):
            bench.schedule(cases, 3)

    def test_contract_refusal_never_launches_even_fake_roster_probe(self):
        local_spec = importlib.util.spec_from_file_location('bench_local', REPO / 'eval/bench_local.py')
        if not local_spec.loader or not (REPO / 'eval/bench_local.py').exists():
            self.fail('local preflight benchmark is not implemented')
        local_module = importlib.util.module_from_spec(local_spec)
        local_spec.loader.exec_module(local_module)
        source = self.root / 'readonly-plugin'
        shutil.copytree(REPO / 'plugins/review-council', source)
        for path in [*source.rglob('*'), source]:
            path.chmod(path.stat().st_mode & ~0o200)
        identity = bench.tree_identity(source)
        result = local_module.preflight_case(source, self.root / 'preflight')
        self.assertEqual(result['roster_probes'], 0)
        self.assertEqual(result['exit_code'], 1)
        self.assertFalse(result['authoritative_receipt'])
        self.assertEqual(bench.tree_identity(source), identity)

    def test_accounting_replay_matches_independently_known_native_totals(self):
        local_spec = importlib.util.spec_from_file_location('bench_local', REPO / 'eval/bench_local.py')
        if not local_spec.loader or not (REPO / 'eval/bench_local.py').exists():
            self.fail('local accounting benchmark is not implemented')
        local_module = importlib.util.module_from_spec(local_spec)
        local_spec.loader.exec_module(local_module)
        result = local_module.accounting_case(REPO / 'plugins/review-council', self.root / 'accounting')
        self.assertEqual(result['input_tokens'], 17)
        self.assertEqual(result['output_tokens'], 9)
        self.assertTrue(result['matches_truth'])

    def test_evidence_case_compiles_a_valid_canonical_topology_without_providers(self):
        plugin = self.root / 'sources/candidate/plugins/review-council'
        plugin.parent.mkdir(parents=True)
        bench.snapshot_tree(REPO / 'plugins/review-council', plugin)
        case_root = REPO / 'eval/fixtures/cost-v1/cache-isolation'
        case = json.loads((case_root / 'case.json').read_text())
        root = self.root / 'work/cache-isolation/root'
        root.parent.mkdir(parents=True)
        bench.snapshot_tree(case_root / 'before', root)
        bench.make_worktree_writable(root)
        bench.git(root, 'init', '-q', '-b', 'main')
        bench.git(root, 'add', '.')
        bench.git(root, '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture',
                  '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Base')
        bench.git(root, 'checkout', '-qb', 'change')
        for file in case['files']:
            (root / file).write_bytes((case_root / 'after' / file).read_bytes())
        prompt, elapsed = bench.render(self.root, case, 'candidate', self.root / 'session')
        self.assertTrue(prompt.is_file())
        self.assertGreater(prompt.stat().st_size, 0)
        self.assertFalse((self.root / 'budget.json').exists())


if __name__ == '__main__':
    unittest.main()
