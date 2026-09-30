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
PROFILE = {'seat': 'codex-luna', 'model': 'fixture-luna', 'effort': 'xhigh',
           'selectors': ['latest-sol', 'latest-luna'],
           'roster': [dict(seat='codex-sol', model='fixture-sol', adapter='codex', effort='xhigh', extra=False),
                      dict(seat='codex-luna', model='fixture-luna', adapter='codex', effort='xhigh', extra=False),
                      dict(seat='opus', model='opus', adapter='claude', effort='max', extra=False)]}
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
        bench.make_worktree_writable(plugin)
        bench.git(candidate, 'init', '-q', '-b', 'main')
        bench.git(candidate, 'add', '.')
        bench.git(candidate, '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture',
                  '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
        original = bench.command

        def command(argv, *args, **kwargs):
            return 'codex-fixture' if argv == ['codex', '--version'] else original(argv, *args, **kwargs)

        out = self.root / 'batch'
        rates = self.root / 'rates.json'
        rates.write_text(json.dumps({'model': 'fixture-luna', 'input_per_million': 2,
                                    'cached_per_million': 0.2, 'output_per_million': 10}))
        archive_env = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'tar.umask',
                       'GIT_CONFIG_VALUE_0': '0000'}
        with patch.object(bench, 'command', command), patch.dict(os.environ, archive_env):
            manifest = bench.prepare(out, 'main', candidate, 4, PROFILE, rate_card=rates)
        self.assertEqual(manifest['identity']['sources']['baseline'],
                         manifest['identity']['sources']['candidate'])
        result = bench.command([sys.executable, str(out / 'engine/eval/cost_bench.py'),
                                'report', '--out', str(out)])
        self.assertIn('0/4 reserved', result)
        self.assertFalse((out / 'budget.json').exists())
        self.assertEqual(json.loads((out / 'report.json').read_text())['manifest']['identity']['engine'],
                         bench.engine_identity())

    def test_one_case_suite_freezes_a_two_call_pair_and_specialist_role(self):
        candidate = self.root / 'candidate'
        helper = candidate / 'plugins/review-council/scripts/lib/usage.py'
        helper.parent.mkdir(parents=True)
        shutil.copy2(REPO / 'plugins/review-council/scripts/lib/usage.py', helper)
        helper.chmod(0o644)
        bench.git(candidate, 'init', '-q', '-b', 'main')
        bench.git(candidate, 'add', '.')
        bench.git(candidate, '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture',
                  '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
        suite = self.root / 'one-case-suite'
        case_dir = suite / 'cache-isolation'
        shutil.copytree(REPO / 'eval/fixtures/cost-v1/cache-isolation', case_dir)
        bench.make_worktree_writable(case_dir)
        case = json.loads((case_dir / 'case.json').read_text())
        case['reviewer_role'] = 'specialist'
        (case_dir / 'case.json').write_text(json.dumps(case))
        rates = self.root / 'rates.json'
        rates.write_text(json.dumps({'model': 'fixture-luna', 'input_per_million': 2,
                                    'cached_per_million': 0.2, 'output_per_million': 10}))
        original = bench.command
        def command(argv, *args, **kwargs):
            return 'codex-fixture' if argv == ['codex', '--version'] else original(argv, *args, **kwargs)
        out = self.root / 'batch'
        with patch.object(bench, 'command', command):
            manifest = bench.prepare(out, 'main', candidate, 2, PROFILE,
                                     rate_card=rates, suite=suite)
        self.assertEqual(manifest['schedule'], [['cache-isolation', 'baseline'],
                                              ['cache-isolation', 'candidate']])
        frozen = json.loads((out / 'cases/cache-isolation/case.json').read_text())
        self.assertEqual(frozen['reviewer_role'], 'specialist')
        self.assertFalse((out / 'budget.json').exists())
        self.assertEqual(bench.tree_identity(out / 'cases'), manifest['identity']['cases'])
        limits = bench.report(out)['limits']
        self.assertIn('1 case provides no statistical quality equivalence.', limits)
        self.assertFalse(any('Two cases' in limit for limit in limits))

    def test_context_suite_preserves_truth_and_unchanged_unrelated_source(self):
        original = REPO / 'eval/fixtures/cost-v1/cache-isolation'
        enriched = REPO / 'eval/fixtures/cost-v2/cache-isolation'
        for snapshot in ('before', 'after'):
            self.assertEqual((enriched / snapshot / 'cache.py').read_bytes(),
                             (original / snapshot / 'cache.py').read_bytes())
        self.assertEqual((enriched / 'before/reporting.py').read_bytes(),
                         (enriched / 'after/reporting.py').read_bytes())
        self.assertEqual((enriched / 'oracle.py').read_bytes(), (original / 'oracle.py').read_bytes())
        checks = json.loads(bench.command([sys.executable, str(enriched / 'oracle.py'), '--json']))
        self.assertTrue(checks['passed'])
        self.assertEqual(len(checks['checks']), 8)
        context = (enriched / 'context.md').read_text()
        self.assertLessEqual(len(context.split()), 500)
        for defect in json.loads((enriched / 'case.json').read_text())['defects']:
            self.assertNotIn(defect['description'], context)
            self.assertNotIn(defect['id'], context)

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

    def test_single_stage_schedule_has_exactly_two_calls(self):
        cases = [{'id': 'first'}, {'id': 'second'}]
        self.assertEqual(bench.schedule(cases, 2, ('candidate',)),
                         [('first', 'candidate'), ('second', 'candidate')])
        with self.assertRaisesRegex(ValueError, 'variant'):
            bench.schedule(cases, 4, ('unsupported',))

    def test_rate_selection_refuses_an_unpriced_future_model(self):
        rates = {'models': {'gpt-99-luna': {'input_per_million': 2,
                  'cached_per_million': 0.2, 'output_per_million': 10}}}
        self.assertEqual(bench.model_rates(rates, 'gpt-99-luna')['output_per_million'], 10)
        with self.assertRaisesRegex(ValueError, 'rate'):
            bench.model_rates(rates, 'gpt-100-luna')

    def test_cross_stage_comparison_rejects_changed_profile_truth_and_source(self):
        before = {'identity': {'model': 'gpt-99-luna', 'effort': 'xhigh',
                  'cases': 'truth', 'codex_version': 'cli', 'rate_card': 'rates',
                  'collector': 'collector', 'engine': {},
                  'sources': {'candidate': 'before'}}}
        after = {'identity': dict(before['identity'], sources={'baseline': 'before',
                                  'candidate': 'after'})}
        bench.check_reference(before, after)
        for key in ('model', 'effort', 'cases', 'codex_version', 'rate_card', 'collector', 'engine'):
            changed = {'identity': dict(after['identity'], **{key: 'changed'})}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'reference'):
                bench.check_reference(before, changed)
        after['identity']['sources']['baseline'] = 'unrelated'
        with self.assertRaisesRegex(ValueError, 'reference'):
            bench.check_reference(before, after)

    def test_reusing_control_variant_requires_its_exact_frozen_source(self):
        identity = {'model': 'fixture-luna', 'effort': 'xhigh', 'cases': 'truth',
                    'codex_version': 'cli', 'rate_card': 'rates', 'collector': 'collector',
                    'engine': {}, 'sources': {'baseline': 'control', 'candidate': 'loser'}}
        original = {'identity': identity}
        later = {'identity': dict(identity, sources={'baseline': 'control', 'candidate': 'next'})}
        bench.check_reference(original, later, 'baseline')
        with self.assertRaisesRegex(ValueError, 'source'):
            bench.check_reference(original, later)
        with self.assertRaisesRegex(ValueError, 'variant'):
            bench.check_reference(original, later, 'unknown')

    def test_quality_provenance_replays_bound_artifacts_and_excludes_base_packets(self):
        import hashlib
        session = self.root / 'runs/example/candidate'
        session.mkdir(parents=True)
        root = self.root / 'work/example/root'
        root.mkdir(parents=True)
        result = {'summary': 'No actionable defects', 'findings': []}
        case = {'id': 'example', 'defects': []}
        artifacts = {}
        for key, content in (('prompt', b'contract'), ('raw', b'tool evidence'),
                             ('findings', json.dumps(result).encode())):
            path = session / (key + '.json')
            path.write_bytes(content)
            artifacts[key] = str(path.relative_to(self.root))
        snapshot = 'a' * 40
        packet_ranges = [dict(path='current.py', line_start=1, line_end=5, blob_tree=snapshot),
                         dict(path='old.py', line_start=1, line_end=5, blob_tree='b' * 40)]
        evidence_path = session / 'r1-evidence.manifest.json'
        evidence_path.write_text(json.dumps({'snapshot_tree': snapshot, 'source_context': {
            'seats': {PROFILE['seat']: {'shards': [{'ranges': packet_ranges}]}}}}))
        audit = {'status': 'valid', 'violations': [], 'source_ranges': [
            dict(path=r['path'], line_start=r['line_start'], line_end=r['line_end'], origin='packet')
            for r in packet_ranges], 'evidence_manifest_sha256': hashlib.sha256(evidence_path.read_bytes()).hexdigest()}
        for key, field in (('prompt', 'prompt_sha256'), ('raw', 'stream_sha256'), ('findings', 'result_sha256')):
            audit[field] = hashlib.sha256((self.root / artifacts[key]).read_bytes()).hexdigest()
        row = {'valid': True, 'variant': 'candidate', 'case': 'example', 'artifacts': artifacts}
        manifest = {'identity': {'profile': PROFILE}}
        def replay(argv, **kwargs):
            Path(argv[argv.index('--out') + 1]).write_text(json.dumps(audit))
            return ''
        with patch.object(bench, 'command', replay):
            provenance = bench.verified_quality_provenance(self.root, manifest, row, result, case, audit)
        self.assertEqual(provenance['snapshot_packet_ranges'], [packet_ranges[0]])
        def forged_replay(argv, **kwargs):
            Path(argv[argv.index('--out') + 1]).write_text(json.dumps(dict(audit, source_ranges=[])))
            return ''
        with patch.object(bench, 'command', forged_replay), self.assertRaisesRegex(ValueError, 'replayed'):
            bench.verified_quality_provenance(self.root, manifest, row, result, case, audit)
        (self.root / artifacts['raw']).write_bytes(b'changed evidence')
        with self.assertRaisesRegex(ValueError, 'artifact binding'):
            bench.verified_quality_provenance(self.root, manifest, row, result, case, audit)

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
        for suite_name in ('cost-v1', 'cost-v2'):
            with self.subTest(suite=suite_name):
                batch = self.root / suite_name
                plugin = batch / 'sources/candidate/plugins/review-council'
                plugin.parent.mkdir(parents=True)
                bench.snapshot_tree(REPO / 'plugins/review-council', plugin)
                case_root = REPO / 'eval/fixtures' / suite_name / 'cache-isolation'
                case = json.loads((case_root / 'case.json').read_text())
                frozen_case = batch / 'cases/cache-isolation'
                frozen_case.parent.mkdir(parents=True)
                bench.snapshot_tree(case_root, frozen_case)
                root = batch / 'work/cache-isolation/root'
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
                prompt, elapsed = bench.render(batch, case, 'candidate', batch / 'session', PROFILE)
                self.assertTrue(prompt.is_file())
                self.assertEqual(prompt.name, 'r1-codex-luna.prompt.md')
                self.assertGreater(prompt.stat().st_size, 0)
                self.assertFalse((batch / 'budget.json').exists())

                manifest = json.loads((batch / 'session/r1-evidence.manifest.json').read_text())
                if suite_name == 'cost-v2':
                    self.assertEqual(manifest['mechanical_owner'], 'codex-sol')
                    self.assertEqual(manifest['assignments']['codex-luna']['bundle'], 'security-state-api')
                    self.assertFalse(manifest['assignments']['codex-luna']['full_state'])
                    self.assertEqual((batch / 'session/context.md').read_bytes(), (case_root / 'context.md').read_bytes())
                    routes = json.loads((batch / 'session/context.routes.json').read_text())
                    self.assertEqual(routes['snapshot_tree'], manifest['snapshot_tree'])
                    body = prompt.read_text()
                    context = (case_root / 'context.md').read_text()
                    self.assertIn(context, body)
                else:
                    self.assertEqual(manifest['mechanical_owner'], 'codex-luna')


if __name__ == '__main__':
    unittest.main()
