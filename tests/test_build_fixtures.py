"""Public build behavior, independent repairs, and frozen scorer compatibility."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'eval/fixtures/cost-v4'
SCORER = ROOT / 'reference/bench_quality.py'
CURRENT_SCORER = REPO / 'eval/bench_quality.py'
sys.dont_write_bytecode = True


def support(test):
    path = ROOT / 'build_oracle.py'
    test.assertTrue(path.is_file(), 'the independent build oracle is not implemented')
    spec = importlib.util.spec_from_file_location('heldout_oracle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export_tool(test, name):
    path = ROOT / name
    test.assertTrue(path.is_file(), 'portable export tool is not implemented: ' + name)
    spec = importlib.util.spec_from_file_location('portable_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def diamond(module, options=None):
    service = module.build_system()
    specs = [module.TargetSpec('leaf', 'bundle', ('input',)),
             module.TargetSpec('middle', 'bundle', (), ('leaf',)),
             module.TargetSpec('root', 'bundle', (), ('middle',))]
    project = service.create_project('tenant', 'project', {'input': b'one'}, specs, options)
    return service, project


class BaselineBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.oracle = support(self)
        self.module = self.oracle.load(ROOT / 'incremental-build-a/before')

    def test_leaf_edit_changes_root_fingerprint_and_invalidates_all_consumers(self):
        service, project = diamond(self.module)
        service.build(project, ('root',))
        original = service.fetch(project, 'root')
        fingerprint = service.plan(project, ('root',)).node('root').fingerprint
        self.assertTrue(service.set_source(project, 'input', b'two'))
        self.assertEqual(service.status(project)['dirty'], ['leaf', 'middle', 'root'])
        with self.assertRaises(self.module.BuildNotReady):
            service.fetch(project, 'root')
        self.assertNotEqual(service.plan(project, ('root',)).node('root').fingerprint, fingerprint)
        service.build(project, ('root',))
        self.assertNotEqual(service.fetch(project, 'root'), original)

    def test_option_edit_changes_compiled_result_without_source_edit(self):
        service, project = diamond(self.module, {'mode': 'debug'})
        service.build(project, ('leaf',))
        previous = service.fetch(project, 'leaf')
        self.assertTrue(service.set_options(project, {'mode': 'release'}))
        service.build(project, ('leaf',))
        current = service.fetch(project, 'leaf')
        self.assertNotEqual(previous, current)
        self.assertEqual(json.loads(current)['options'], {'mode': 'release'})

    def test_active_staging_survives_collection_then_publishes(self):
        service, project = diamond(self.module)
        ticket = service.begin(project, ('root',))
        service.compile(ticket)
        before = service.ticket(project, ticket)['artifacts']
        removed = service.collect()
        self.assertTrue(before)
        self.assertFalse(set(before.values()) & set(removed))
        manifest = service.finish(ticket)
        self.assertEqual(manifest.revision, 1)
        self.assertTrue(service.fetch(project, 'root'))

    def test_missing_manifest_member_preserves_the_previous_head(self):
        service, project = diamond(self.module)
        manifest = service.build(project, ('root',))
        state = service.status(project)
        root_digest = dict(manifest.outputs)['root']
        with self.assertRaises(self.module.MissingArtifact):
            service.publisher.commit(project, {'leaf': root_digest, 'root': '0' * 64},
                                     state['epoch'], state['revision'], ())
        self.assertEqual(service.status(project), state)

    def test_same_content_can_share_blobs_without_sharing_project_heads(self):
        service, first = diamond(self.module)
        second = service.create_project('other', 'project', {'input': b'one'},
                                        [self.module.TargetSpec('leaf', 'bundle', ('input',))])
        service.build(first, ('leaf',))
        with self.assertRaises(self.module.BuildNotReady):
            service.fetch(second, 'leaf')
        service.build(second, ('leaf',))
        self.assertEqual(service.fetch(first, 'leaf'), service.fetch(second, 'leaf'))
        self.assertEqual(len(service.blobs), 1)

    def test_cancel_after_compile_keeps_head_and_releases_staging(self):
        service, project = diamond(self.module)
        service.build(project, ('root',))
        service.set_source(project, 'input', b'two')
        state = service.status(project)
        ticket = service.begin(project, ('root',))
        service.compile(ticket)
        staged = set(service.ticket(project, ticket)['artifacts'].values())
        self.assertTrue(service.cancel(project, ticket))
        self.assertFalse(service.cancel(project, ticket))
        with self.assertRaises(self.module.BuildCancelled):
            service.finish(ticket)
        self.assertEqual(service.status(project), state)
        self.assertEqual(set(service.collect()), staged)

    def test_source_change_rejects_a_previously_compiled_plan(self):
        service, project = diamond(self.module)
        ticket = service.begin(project, ('root',))
        service.compile(ticket)
        service.set_source(project, 'input', b'two')
        with self.assertRaises(self.module.StaleBuild):
            service.finish(ticket)
        self.assertEqual(service.status(project)['revision'], 0)

    def test_source_and_option_noops_do_not_stale_a_valid_ticket(self):
        service, project = diamond(self.module, {'mode': 'debug'})
        ticket = service.begin(project, ('root',))
        service.compile(ticket)
        self.assertFalse(service.set_source(project, 'input', b'one'))
        self.assertFalse(service.set_options(project, {'mode': 'debug'}))
        self.assertEqual(service.finish(ticket).revision, 1)

    def test_two_project_heads_cannot_commit_from_the_same_revision(self):
        service, project = diamond(self.module)
        first = service.begin(project, ('root',))
        second = service.begin(project, ('root',))
        service.compile(first)
        service.compile(second)
        service.finish(first)
        with self.assertRaises(self.module.StaleBuild):
            service.finish(second)
        self.assertEqual(service.status(project)['revision'], 1)

    def test_snapshots_and_input_mappings_are_owned(self):
        source = {'input': b'one'}
        options = {'mode': 'debug'}
        service = self.module.build_system()
        project = service.create_project('tenant', 'project', source,
                                         [self.module.TargetSpec('leaf', 'bundle', ('input',))], options)
        source['input'] = b'two'
        options['mode'] = 'release'
        service.build(project, ('leaf',))
        compiled = json.loads(service.fetch(project, 'leaf'))
        self.assertEqual(compiled['options'], {'mode': 'debug'})
        self.assertEqual(compiled['sources'], [['input', '6f6e65']])
        state = service.status(project)
        state['outputs'].clear()
        state['dirty'].append('leaf')
        self.assertTrue(service.fetch(project, 'leaf'))

    def test_unknown_project_cannot_inspect_or_cancel_another_ticket(self):
        service, first = diamond(self.module)
        second = service.create_project('other', 'project', {'input': b'two'},
                                        [self.module.TargetSpec('leaf', 'bundle', ('input',))])
        ticket = service.begin(first, ('leaf',))
        with self.assertRaises(self.module.UnknownBuild):
            service.ticket(second, ticket)
        with self.assertRaises(self.module.UnknownBuild):
            service.cancel(second, ticket)

    def test_graph_rejects_cycles_missing_dependencies_and_duplicate_targets(self):
        service = self.module.build_system()
        bad = [
            [self.module.TargetSpec('a', 'bundle', (), ('b',)), self.module.TargetSpec('b', 'bundle', (), ('a',))],
            [self.module.TargetSpec('a', 'bundle', (), ('absent',))],
            [self.module.TargetSpec('a', 'bundle'), self.module.TargetSpec('a', 'bundle')],
        ]
        for index, specs in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(self.module.InvalidGraph):
                service.create_project('tenant', str(index), {}, specs)


class HeldoutFixtureTests(unittest.TestCase):
    def setUp(self):
        self.oracle = support(self)

    def test_standalone_oracles_prove_faults_and_both_snapshot_controls(self):
        for case_id, defects in (('incremental-build-a', 5), ('incremental-build-b', 0)):
            with self.subTest(case=case_id):
                process = subprocess.run([sys.executable, str(ROOT / case_id / 'oracle.py'), '--json'],
                                         text=True, capture_output=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(result['case'], case_id)
                self.assertTrue(result['passed'])
                self.assertTrue(all(row['passed'] for row in result['checks']))
                self.assertEqual(sum(row['kind'] == 'defect' for row in result['checks']), defects)
                self.assertGreaterEqual(sum(row['kind'] == 'baseline-control' for row in result['checks']), 8)
                self.assertGreaterEqual(sum(row['kind'] == 'clean-control' for row in result['checks']), 8)

    def test_each_repair_removes_exactly_its_targeted_fault(self):
        for identifier in self.oracle.REPAIRS:
            with self.subTest(defect=identifier), tempfile.TemporaryDirectory() as directory:
                repaired = Path(directory) / 'after'
                shutil.copytree(ROOT / 'incremental-build-a/after', repaired, copy_function=shutil.copyfile)
                self.oracle.apply_repair(repaired, identifier)
                result = self.oracle.run_checks(after_root=repaired, case_root=ROOT / 'incremental-build-a')
                failures = [row['id'] for row in result['checks'] if not row['passed']]
                self.assertEqual(failures, [identifier])

    def test_every_fault_is_restored_in_the_clean_twin(self):
        faulty = ROOT / 'incremental-build-a/after'
        clean = ROOT / 'incremental-build-b/after'
        with tempfile.TemporaryDirectory() as directory:
            repaired = Path(directory) / 'repaired'
            shutil.copytree(faulty, repaired, copy_function=shutil.copyfile)
            for identifier in self.oracle.REPAIRS:
                self.oracle.apply_repair(repaired, identifier)
            for path in clean.iterdir():
                if path.is_file():
                    self.assertEqual(path.read_bytes(), (repaired / path.name).read_bytes(), path.name)
        result = self.oracle.run_checks(case_root=ROOT / 'incremental-build-b', clean=True)
        self.assertTrue(result['passed'], [row for row in result['checks'] if not row['passed']])

    def test_snapshot_loading_is_isolated_across_reloaded_oracle_modules(self):
        before = support(self).load(ROOT / 'incremental-build-a/before')
        after = support(self).load(ROOT / 'incremental-build-a/after')
        self.assertEqual(self.oracle.transitive_probe(before), [True, True, True, True])
        self.assertEqual(self.oracle.transitive_probe(after), [False, True, False, False])

    def test_source_truth_labels_and_frozen_source_hashes_are_consistent(self):
        for case_id in ('incremental-build-a', 'incremental-build-b'):
            case_root = ROOT / case_id
            case = json.loads((case_root / 'case.json').read_text())
            self.assertEqual(case['id'], case_id)
            self.assertEqual(len(case['defects']), 5 if case_id == 'incremental-build-a' else 0)
            for side in ('before', 'after'):
                snapshot = case_root / side
                hashes = case['source_sha256'][side]
                self.assertEqual(set(hashes), {path.name for path in snapshot.iterdir() if path.is_file()})
                self.assertGreaterEqual(sum(len(path.read_text().splitlines()) for path in snapshot.glob('*.py')), 450)
                self.assertLessEqual(sum(len(path.read_text().splitlines()) for path in snapshot.glob('*.py')), 800)
                for path in snapshot.iterdir():
                    if path.is_file():
                        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), hashes[path.name])
                self.assertFalse(list(snapshot.rglob('__pycache__')))
            for defect in case['defects']:
                lines = (case_root / 'after' / defect['file']).read_text().splitlines()
                self.assertEqual(defect['line_start'], defect['line_end'])
                self.assertEqual(lines[defect['line_start'] - 1], defect['line_label'])
                self.assertIn(defect['severity'], ('P1', 'P2'))
                self.assertEqual(self.oracle.REPAIRS[defect['id']][0], defect['file'])
                self.assertEqual(self.oracle.REPAIRS[defect['id']][1], defect['line_label'])

    def test_rubric_ranges_are_semantic_and_compatible_with_frozen_scorer(self):
        compatibility = export_tool(self, 'compatibility.py')
        scorer = compatibility.load_quality(SCORER)
        for case_id in ('incremental-build-a', 'incremental-build-b'):
            case_root = ROOT / case_id
            case = json.loads((case_root / 'case.json').read_text())
            self.assertEqual(scorer._rubric(case['behavior_rubric']), case['behavior_rubric'])
            score = scorer.score_run(case, {'summary': 'No adjudication', 'findings': []}, None, None, None)
            self.assertFalse(score['confirmed'])
            self.assertIsNone(score['quality_score'])
            for field in ('critical_flows', 'hypotheses'):
                for row in case['behavior_rubric'][field]:
                    for source in row['required_sources']:
                        lines = (case_root / 'after' / source['path']).read_text().splitlines()
                        self.assertLessEqual(source['line_end'], len(lines))
                        self.assertTrue(lines[source['line_start'] - 1].strip(), source)
                        self.assertTrue(lines[source['line_end'] - 1].strip(), source)

    def test_current_host_api_accepts_the_frozen_rubrics(self):
        if not CURRENT_SCORER.is_file():
            self.skipTest('the standalone export does not include a mutable host scorer')
        compatibility = export_tool(self, 'compatibility.py')
        checked = compatibility.check_compatibility(CURRENT_SCORER)
        self.assertTrue(checked['passed'], checked)
        self.assertEqual([row['case'] for row in checked['cases']],
                         ['incremental-build-a', 'incremental-build-b'])

    def test_reporting_only_scorer_change_preserves_compatibility(self):
        compatibility = export_tool(self, 'compatibility.py')
        with tempfile.TemporaryDirectory() as directory:
            scorer_root = Path(directory)
            shutil.copyfile(SCORER.parent / 'bench_score.py', scorer_root / 'bench_score.py')
            changed = scorer_root / 'bench_quality.py'
            changed.write_bytes(SCORER.read_bytes() + b'\n\ndef summary_for_export(value):\n    return value.get("score_version")\n')
            self.assertNotEqual(hashlib.sha256(changed.read_bytes()).hexdigest(),
                                hashlib.sha256(SCORER.read_bytes()).hexdigest())
            checked = compatibility.check_compatibility(changed)
            self.assertTrue(checked['passed'], checked)
            self.assertTrue(checked['scoring_ast_matches_reference'])

    def test_historical_case_sources_contexts_and_oracles_match_the_original_seal(self):
        provenance = json.loads((ROOT / 'provenance.json').read_text())
        historical = ROOT / 'reference/original-freeze.json'
        self.assertEqual(hashlib.sha256(historical.read_bytes()).hexdigest(), provenance['original_seal_sha256'])
        original = json.loads(historical.read_text())
        self.assertEqual(provenance['necessary_wrapper_changes'], [])
        self.assertEqual(provenance['cases'], original['cases'])
        for relative, expected in provenance['retained_artifacts'].items():
            self.assertEqual(expected, original['artifacts'][relative])
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)

    def test_freeze_receipt_binds_every_private_and_source_artifact(self):
        receipt = json.loads((ROOT / 'freeze.json').read_text())
        self.assertEqual(receipt['schema_version'], 1)
        self.assertEqual(receipt['scorer_sha256'], hashlib.sha256(SCORER.read_bytes()).hexdigest())
        self.assertEqual(receipt['correctness_scorer_sha256'],
                         hashlib.sha256((SCORER.parent / 'bench_score.py').read_bytes()).hexdigest())
        for case_id in ('incremental-build-a', 'incremental-build-b'):
            case = json.loads((ROOT / case_id / 'case.json').read_text())
            for field, value in (('case_sha256', case), ('rubric_sha256', case['behavior_rubric'])):
                canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                self.assertEqual(receipt['cases'][case_id][field], hashlib.sha256(canonical).hexdigest())
        actual_paths = {str(path.relative_to(ROOT)) for path in ROOT.rglob('*')
                        if path.is_file() and path.name != 'freeze.json' and '__pycache__' not in path.parts}
        self.assertEqual(set(receipt['artifacts']), actual_paths)
        for relative, expected in receipt['artifacts'].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)


if __name__ == '__main__':
    unittest.main()
