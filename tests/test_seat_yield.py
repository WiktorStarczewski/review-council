"""Seat yield reports failure codes by model, and cited findings survive a protocol miss."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins' / 'review-council'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeatYieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load(PLUGIN / 'scripts/rev-profile.py', 'rev_profile_yield')
        cls.audit = load(PLUGIN / 'scripts/lib/review-read-audit.py', 'review_read_audit_yield')

    def test_yield_counts_codes_by_model(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            (session / 'roster.json').write_text(json.dumps({'seats': [
                {'seat': 'luna', 'model': 'gpt-6-luna', 'adapter': 'codex', 'effort': 'xhigh'},
                {'seat': 'sol', 'model': 'gpt-6.1-sol', 'adapter': 'codex', 'effort': 'xhigh'},
            ]}))
            (session / 'r1-luna.exit').write_text('0\n')
            (session / 'r1-luna.json').write_text(json.dumps({
                'summary': 'checked', 'findings': []}))
            (session / 'r1-luna.read-audit.json').write_text(json.dumps({
                'status': 'valid', 'violations': [], 'advisories': []}))
            (session / 'r2-luna.exit').write_text('2\n')
            (session / 'r2-luna.audit-invalid.json').write_text(json.dumps({
                'summary': 'kept', 'findings': []}))
            (session / 'r2-luna.read-audit.json').write_text(json.dumps({
                'status': 'invalid',
                'violations': [{'code': 'missing-required-source-read', 'tool': 'codex'},
                               {'code': 'evidence-read-order', 'tool': 'audit'}],
                'advisories': []}))
            (session / 'r3-luna.exit').write_text('0\n')
            (session / 'r3-luna.json').write_text(json.dumps({
                'summary': 'INCOMPLETE PROOF: patch unread', 'findings': []}))
            (session / 'r1-sol.exit').write_text('0\n')
            (session / 'r1-sol.json').write_text(json.dumps({
                'summary': 'cited', 'findings': [{'file': 'a.py'}]}))
            (session / 'r1-sol.read-audit.json').write_text(json.dumps({
                'status': 'valid', 'citation_reaudit': True, 'violations': [],
                'advisories': [{'code': 'discovery-output-too-large', 'tool': 'codex'}]}))
            rows = self.profile.seat_yield(session)
            luna = rows['gpt-6-luna']
            self.assertEqual(luna['runs'], 3)
            self.assertEqual(luna['usable'], 1)
            self.assertEqual(luna['audit_invalid'], 1)
            self.assertEqual(luna['incomplete_proof'], 1)
            self.assertEqual(luna['codes']['missing-required-source-read'], 1)
            self.assertEqual(luna['codes']['evidence-read-order'], 1)
            sol = rows['gpt-6.1-sol']
            self.assertEqual(sol['salvaged'], 1)
            self.assertEqual(sol['codes']['discovery-output-too-large'], 1)
            text = '\n'.join(self.profile.format_seat_yield(rows))
            self.assertIn('model=gpt-6-luna', text)
            self.assertIn('missing-required-source-read:1', text)

    def test_cited_findings_are_salvaged_and_an_empty_result_is_not(self):
        ranges = [{'path': 'src/a.py', 'line_start': 4, 'line_end': 9, 'origin': 'tool'}]
        finding = {'file': 'src/a.py', 'line_start': 5, 'line_end': 6, 'claim': 'layout'}
        violations = [{'code': 'missing-required-source-read', 'tool': 'codex'},
                      {'code': 'evidence-read-order', 'tool': 'audit'}]
        self.assertTrue(self.audit.should_salvage_citations([finding], ranges, violations))
        self.assertFalse(self.audit.should_salvage_citations([], ranges, violations))
        self.assertFalse(self.audit.should_salvage_citations(
            [dict(finding, file='src/other.py')], ranges, violations))
        self.assertFalse(self.audit.should_salvage_citations(
            [finding], ranges, violations + [{'code': 'invalid-review-result', 'tool': 'codex'}]))
