"""Behavioral contracts for the reusable dispatcher review fixture."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
CASE = REPO / 'eval/fixtures/cost-v3/job-dispatcher-a'


class ComplexBenchTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((CASE / 'case.json').is_file(), 'complex fixture metadata is missing')
        self.case = json.loads((CASE / 'case.json').read_text())
        spec = importlib.util.spec_from_file_location('dispatcher_oracle', CASE / 'oracle.py')
        self.oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.oracle)

    def test_correct_baseline_broken_transitions_and_clean_controls(self):
        result = self.oracle.run_checks()
        self.assertTrue(result['passed'], result)
        checks = result['checks']
        defects = {row['id'] for row in self.case['defects']}
        self.assertEqual({row['id'] for row in checks if row['kind'] == 'defect'}, defects)
        self.assertEqual({row['id'].removesuffix('-before') for row in checks
                          if row['kind'] == 'baseline'}, defects)
        self.assertGreaterEqual(len({row['id'] for row in checks if row['kind'] == 'clean-control'}), 8)

    def test_each_individual_repair_invalidates_only_its_planted_outcome(self):
        for defect in self.case['defects']:
            with self.subTest(defect=defect['id']), tempfile.TemporaryDirectory() as tmp:
                repaired = Path(tmp) / 'after'
                shutil.copytree(CASE / 'after', repaired)
                self.oracle.apply_repair(repaired, defect['id'])
                result = self.oracle.run_checks(after_root=repaired)
                failed = {row['id'] for row in result['checks'] if not row['passed']}
                self.assertFalse(result['passed'])
                self.assertEqual(failed, {defect['id']})

    def test_reviewed_source_size_scope_and_truth_separation(self):
        paths = sorted(path.relative_to(CASE / 'after').as_posix()
                       for path in (CASE / 'after').rglob('*') if path.is_file())
        python = [path for path in paths if path.endswith('.py')]
        lines = sum(len((CASE / 'after' / path).read_bytes().splitlines()) for path in python)
        self.assertGreaterEqual(len(python), 6)
        self.assertLessEqual(len(python), 10)
        self.assertGreaterEqual(lines, 600)
        self.assertLessEqual(lines, 1000)
        self.assertIn('AGENTS.md', paths)
        self.assertFalse({'case.json', 'oracle.py', 'repairs.json'}.intersection(paths))
        changed = {path for path in paths
                   if (CASE / 'before' / path).read_bytes() != (CASE / 'after' / path).read_bytes()}
        self.assertEqual(changed, set(self.case['files']))
        self.assertNotIn('transport.py', changed)
        self.assertGreaterEqual(len(changed), 6)

    def test_exact_defect_ranges_and_source_hashes(self):
        import hashlib
        for snapshot in ('before', 'after'):
            actual = {path.relative_to(CASE / snapshot).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (CASE / snapshot).rglob('*') if path.is_file()}
            self.assertEqual(actual, self.case['source_sha256'][snapshot])
        for defect in self.case['defects']:
            lines = (CASE / 'after' / defect['file']).read_text().splitlines()
            selected = '\n'.join(lines[defect['line_start'] - 1:defect['line_end']])
            self.assertEqual(selected, defect['line_label'])

    def test_oracle_runs_from_read_only_frozen_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp) / 'suite'
            shutil.copytree(CASE.parent, frozen)
            try:
                for path in frozen.rglob('*'):
                    path.chmod(0o555 if path.is_dir() else 0o444)
                result = subprocess.run([sys.executable, str(frozen / CASE.name / 'oracle.py'), '--json'],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)['passed'])
                self.assertFalse(list(frozen.rglob('__pycache__')))
            finally:
                for path in frozen.rglob('*'):
                    path.chmod(0o755 if path.is_dir() else 0o644)

    def test_clean_twin_preserves_harmless_changes_and_the_private_rubric(self):
        clean = CASE.parent / 'job-dispatcher-b'
        metadata = json.loads((clean / 'case.json').read_text())
        self.assertEqual(metadata['defects'], [])
        self.assertEqual(len(metadata['behavior_rubric']['critical_flows']), 2)
        self.assertEqual(len(metadata['behavior_rubric']['hypotheses']), 4)
        self.assertEqual({source['path'] for row in metadata['behavior_rubric']['critical_flows']
                          for source in row['required_sources']}, {'jobs.py', 'worker.py', 'store.py'})
        with tempfile.TemporaryDirectory() as tmp:
            repaired = Path(tmp) / 'after'
            shutil.copytree(CASE / 'after', repaired)
            for defect in self.case['defects']:
                self.oracle.apply_repair(repaired, defect['id'])
            for path in repaired.rglob('*'):
                if path.is_file():
                    self.assertEqual(path.read_bytes(), (clean / 'after' / path.relative_to(repaired)).read_bytes())
        self.assertTrue(self.oracle.support.run_checks(case_root=clean, clean=True)['passed'])
        self.assertEqual(set(metadata['files']), {'jobs.py', 'worker.py'})

    def test_behavior_rubric_names_only_valid_exact_snapshot_ranges(self):
        rubric = self.case['behavior_rubric']
        self.assertEqual(len(rubric['critical_flows']), 6)
        for category in ('critical_flows', 'hypotheses'):
            rows = rubric[category]
            self.assertEqual(len({row['id'] for row in rows}), len(rows))
            for row in rows:
                self.assertGreaterEqual(len(row['required_sources']), 2)
                for source in row['required_sources']:
                    count = len((CASE / 'after' / source['path']).read_text().splitlines())
                    self.assertLessEqual(1, source['line_start'])
                    self.assertLessEqual(source['line_start'], source['line_end'])
                    self.assertLessEqual(source['line_end'], count)
        clean = CASE.parent / 'job-dispatcher-b'
        rubric = json.loads((clean / 'case.json').read_text())['behavior_rubric']
        for category in ('critical_flows', 'hypotheses'):
            for row in rubric[category]:
                for source in row['required_sources']:
                    count = len((clean / 'after' / source['path']).read_text().splitlines())
                    self.assertLessEqual(1, source['line_start'])
                    self.assertLessEqual(source['line_start'], source['line_end'])
                    self.assertLessEqual(source['line_end'], count)


if __name__ == '__main__':
    unittest.main()
