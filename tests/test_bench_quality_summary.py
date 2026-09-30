"""Complete-case descriptive summaries cannot replace individual quality gates."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import test_bench_quality as fixtures
from eval import bench_quality as quality
from eval import cost_bench as bench

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'eval'))


class QualitySummaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BenchQualityTests('test_fixed_components_and_truth_severity')
        self.fixture.setUp()
        clean = fixtures.BenchQualityTests('test_fixed_components_and_truth_severity')
        clean.setUp()
        clean.case['id'] = 'clean'
        clean.case['defects'] = []
        clean.result['findings'] = []
        clean.rows = []
        self.cases = [self.fixture.case, clean.case]
        self.scores = {'example': self.fixture.score(), 'clean': clean.score()}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def row(self, case, variant, **overrides):
        return {'case': case, 'variant': variant, 'valid': True, 'schema_valid': True,
                'audit_valid': True, 'status': 'valid', 'wall_seconds': 2,
                'run_quality': copy.deepcopy(self.scores[case]), **overrides}

    def rows(self):
        return [self.row(case['id'], variant)
                for variant in ('baseline', 'candidate') for case in self.cases]

    def summarize(self, rows, cases=None):
        self.assertTrue(hasattr(quality, 'summarize_quality'), 'quality summary is not implemented')
        return quality.summarize_quality(rows, self.cases if cases is None else cases)

    def test_complete_scores_have_equal_case_mean_minimum_and_exact_identities(self):
        rows = self.rows()
        correctness, behavior, provenance = self.fixture.inputs()
        for citation in behavior['citations']:
            citation['verdict'] = 'inaccurate'
        rows[2]['run_quality'] = quality.score_run(
            self.fixture.case, self.fixture.result, correctness, self.fixture.audit, behavior,
            verified_provenance=provenance)
        summary = self.summarize(rows)
        self.assertEqual(summary['baseline']['quality_score'], 100)
        candidate = summary['candidate']
        self.assertEqual(candidate['status'], 'known')
        self.assertEqual(candidate['quality_score'], 95)
        self.assertEqual(candidate['minimum_quality_score'], 90)
        self.assertEqual(candidate['complete_cases'], 2)
        self.assertEqual(candidate['expected_cases'], 2)
        self.assertEqual(candidate['maximum'], 100)
        self.assertEqual(candidate['score_version'], 'quality-v1')
        self.assertEqual(candidate['aggregation_version'], 'quality-equal-case-v1')
        self.assertEqual(candidate['unavailable'], [])
        self.assertEqual(candidate['case_identities'], [
            {'case': case['id'], 'case_sha256': quality.canonical_sha256(case),
             'rubric_sha256': quality.canonical_sha256(case['behavior_rubric'])}
            for case in sorted(self.cases, key=lambda case: case['id'])])

    def test_missing_expected_case_never_averages_the_known_subset(self):
        summary = self.summarize([self.row('example', 'candidate')])
        candidate = summary['candidate']
        self.assertEqual(candidate['status'], 'unknown')
        self.assertIsNone(candidate['quality_score'])
        self.assertIsNone(candidate['minimum_quality_score'])
        self.assertEqual(candidate['complete_cases'], 1)
        self.assertEqual(candidate['expected_cases'], 2)
        self.assertTrue(candidate['unavailable'])
        self.assertEqual(summary['baseline']['complete_cases'], 0)

    def test_invalid_or_unconfirmed_scores_make_the_full_variant_unknown(self):
        for field, value in (('valid', False), ('confirmed', False),
                             ('unavailable', ['verified-provenance']),
                             ('unavailable', ['valid-audit']), ('behavior_available', False)):
            rows = self.rows()
            if field == 'valid':
                rows[2][field] = value
            else:
                rows[2]['run_quality'][field] = value
            with self.subTest(field=field, value=value):
                summary = self.summarize(rows)
                self.assertIsNone(summary['candidate']['quality_score'])
                self.assertEqual(summary['candidate']['complete_cases'], 1)
                self.assertTrue(summary['candidate']['unavailable'])
                self.assertEqual(summary['baseline']['quality_score'], 100)

    def test_core_only_score_remains_unknown_without_rescaling(self):
        rows = self.rows()
        correctness, behavior, _ = self.fixture.inputs()
        rows[2]['run_quality'] = quality.score_run(
            self.fixture.case, self.fixture.result, correctness, self.fixture.audit, behavior)
        self.assertEqual(rows[2]['run_quality']['core_score'], 80)
        self.assertIsNone(rows[2]['run_quality']['quality_score'])
        summary = self.summarize(rows)
        self.assertIsNone(summary['candidate']['quality_score'])
        self.assertIsNone(summary['candidate']['minimum_quality_score'])
        self.assertEqual(summary['candidate']['complete_cases'], 1)

    def test_unknown_or_malformed_full_score_is_not_a_numeric_average(self):
        for value in (None, True, -1, 101, 10 ** 400, float('nan'), float('inf'), '100'):
            rows = self.rows()
            rows[2]['run_quality']['quality_score'] = value
            with self.subTest(value=value):
                summary = self.summarize(rows)
                self.assertIsNone(summary['candidate']['quality_score'])
                self.assertEqual(summary['candidate']['complete_cases'], 1)

    def test_missing_score_or_provenance_identity_is_unknown(self):
        for field in ('run_quality', 'audit_sha256', 'findings_sha256', 'evidence_manifest_sha256'):
            rows = self.rows()
            if field == 'run_quality':
                rows[2].pop(field)
            else:
                rows[2]['run_quality'].pop(field)
            with self.subTest(field=field):
                self.assertIsNone(self.summarize(rows)['candidate']['quality_score'])

    def test_confirmed_zero_score_remains_a_known_case(self):
        rows = self.rows()
        self.fixture.result['findings'] = []
        self.fixture.rows = []
        self.fixture.audit['source_ranges'] = []
        rows[2]['run_quality'] = self.fixture.score()
        self.assertEqual(rows[2]['run_quality']['quality_score'], 0)
        summary = self.summarize(rows)['candidate']
        self.assertEqual(summary['status'], 'known')
        self.assertEqual(summary['quality_score'], 50)
        self.assertEqual(summary['minimum_quality_score'], 0)
        self.assertEqual(summary['complete_cases'], 2)

    def test_duplicate_case_variant_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.summarize(self.rows() + [self.row('example', 'candidate')])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.summarize(self.rows(), self.cases + [self.cases[0]])

    def test_mixed_score_versions_make_both_variants_unknown(self):
        rows = self.rows()
        for row in rows[2:]:
            row['run_quality']['score_version'] = 'quality-v2'
        summary = self.summarize(rows)
        for variant in ('baseline', 'candidate'):
            self.assertIsNone(summary[variant]['quality_score'])
            self.assertIn('mixed-score-versions', summary[variant]['unavailable'])

    def test_unsupported_score_or_schema_version_is_unknown(self):
        for field, value in (('score_version', 'quality-v2'), ('schema_version', 2), ('maximum', 80)):
            rows = self.rows()[2:]
            for row in rows:
                row['run_quality'][field] = value
            with self.subTest(field=field):
                self.assertIsNone(self.summarize(rows)['candidate']['quality_score'])

    def test_case_or_rubric_identity_must_match_the_expected_frozen_cases(self):
        for field in ('case_sha256', 'rubric_sha256'):
            rows = self.rows()
            rows[2]['run_quality'][field] = '0' * 64
            with self.subTest(field=field):
                summary = self.summarize(rows)
                self.assertIsNone(summary['candidate']['quality_score'])
                self.assertEqual(summary['candidate']['complete_cases'], 1)

    def test_unexpected_case_and_empty_expected_set_cannot_score(self):
        rows = self.rows()
        rows[2]['case'] = 'unexpected'
        self.assertIsNone(self.summarize(rows)['candidate']['quality_score'])
        for summary in self.summarize([], []).values():
            self.assertEqual(summary['status'], 'unknown')
            self.assertIsNone(summary['quality_score'])
            self.assertEqual(summary['expected_cases'], 0)

    def report_fixture(self, name, rows):
        out = self.root / name
        for case in self.cases:
            bench.write_json(out / 'cases' / case['id'] / 'case.json', case)
        sources = {}
        for variant in ('baseline', 'candidate'):
            plugin = out / 'sources' / variant / 'plugins/review-council'
            plugin.mkdir(parents=True)
            (plugin / 'identity.txt').write_text('unchanged runtime\n')
            sources[variant] = bench.tree_identity(plugin)
        bench.write_json(out / 'rate-card.json', {'model': 'fixture'})
        identity = {'sources': sources, 'cases': bench.tree_identity(out / 'cases'),
                    'baseline_commit': '989b662', 'profile': {'seat': 'fixture'},
                    'model': 'fixture', 'effort': 'xhigh', 'engine': bench.engine_identity(),
                    'rate_card': hashlib.sha256((out / 'rate-card.json').read_bytes()).hexdigest()}
        bench.write_json(out / 'manifest.json', {'identity': identity, 'maximum': len(rows),
                         'schedule': [[row['case'], row['variant']] for row in rows]})
        for row in rows:
            bench.write_json(out / 'runs' / row['case'] / row['variant'] / 'measurement.json', row)
        return out

    def test_reference_report_produces_both_summaries_without_overwriting_controls(self):
        reference = self.report_fixture('control', self.rows()[2:])
        current = self.report_fixture('candidate', self.rows()[2:])
        sealed = {}
        for suffix in ('json', 'csv', 'md'):
            path = reference / ('report.' + suffix)
            path.write_text('sealed ' + suffix + '\n')
            sealed[path] = path.read_bytes()
        result = bench.report(current, reference)
        for path, expected in sealed.items():
            self.assertEqual(path.read_bytes(), expected)
        self.assertIn('quality_summaries', result, 'report has no complete-case quality summaries')
        self.assertEqual(result['quality_summaries']['baseline']['quality_score'], 100)
        self.assertEqual(result['quality_summaries']['candidate']['quality_score'], 100)
        self.assertEqual(len(result['quality_comparisons']), 2)
        markdown = (current / 'report.md').read_text()
        self.assertIn('Equal-case mean /100', markdown)
        self.assertIn('Minimum /100', markdown)
        self.assertIn('quality-equal-case-v1', markdown)
        self.assertIn('| Variant | Equal-case mean /100', markdown)
        self.assertIn('| Case | Variant | Status |', markdown)

    def test_high_mean_never_certifies_a_losing_case(self):
        rows = self.rows()
        correctness, behavior, provenance = self.fixture.inputs()
        for citation in behavior['citations']:
            citation['verdict'] = 'inaccurate'
        rows[2]['run_quality'] = quality.score_run(
            self.fixture.case, self.fixture.result, correctness, self.fixture.audit, behavior,
            verified_provenance=provenance)
        result = bench.report(self.report_fixture('losing', rows))
        self.assertIn('quality_summaries', result, 'report has no complete-case quality summaries')
        self.assertEqual(result['quality_summaries']['candidate']['quality_score'], 95)
        comparison = next(row for row in result['quality_comparisons'] if row['case'] == 'example')
        self.assertFalse(comparison['acceptable'])
        self.assertIn('quality-loss', comparison['reasons'])
        self.assertIn('acceptable False', (self.root / 'losing/report.md').read_text())

    def test_report_unknown_is_explicit_for_an_incomplete_case_set(self):
        result = bench.report(self.report_fixture('missing', [self.row('example', 'candidate')]))
        self.assertIn('quality_summaries', result, 'report has no complete-case quality summaries')
        self.assertIsNone(result['quality_summaries']['candidate']['quality_score'])
        self.assertEqual(result['quality_summaries']['candidate']['expected_cases'], 2)
        self.assertIn('unknown', (self.root / 'missing/report.md').read_text())

    def test_report_refuses_an_older_engine_without_touching_control_outputs(self):
        reference = self.report_fixture('old-control', self.rows()[2:])
        current = self.report_fixture('new-candidate', self.rows()[2:])
        manifest = json.loads((reference / 'manifest.json').read_text())
        manifest['identity']['engine']['bench_quality.py'] = '0' * 64
        bench.write_json(reference / 'manifest.json', manifest)
        path = reference / 'report.md'
        path.write_text('sealed report\n')
        with self.assertRaisesRegex(ValueError, 'engine changed'):
            bench.report(current, reference)
        self.assertEqual(path.read_text(), 'sealed report\n')
        self.assertFalse((current / 'report.json').exists())


if __name__ == '__main__':
    unittest.main()
