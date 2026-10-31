"""Whole-file reads stay auditable, and a path scope does not forbid context reads."""
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


class ReviewBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load(PLUGIN / 'scripts/lib/review-read-audit.py', 'review_read_audit')
        cls.evidence = load(PLUGIN / 'scripts/rev-evidence.py', 'rev_evidence')

    def test_whole_file_read_starts_at_line_1_and_does_not_raise(self):
        root = Path('/tmp/review-council-boundary')
        patch = (root / 'seat.patch').resolve()
        call = self.audit.assigned_patch_ranges_for_call
        self.assertEqual(call('Read', {'file_path': str(patch)}, patch, root, 12), [(1, 12)])
        self.assertEqual(
            call('Read', {'file_path': str(patch), 'offset': 3}, patch, root, 12),
            [(3, 12)])
        self.assertEqual(
            call('Read', {'file_path': str(patch), 'offset': 2, 'limit': 4}, patch, root, 12),
            [(2, 5)])
        self.assertEqual(call('Read', {'file_path': str(patch), 'offset': 0}, patch, root, 12), [])
        self.assertEqual(
            call('Read', {'file_path': str(patch), 'offset': 999999, 'limit': 240}, patch, root, 12),
            [(999999, 12)])
        self.assertEqual(call('Read', {'path': 'other.txt'}, patch, root, 12), [])

    def test_codex_ordered_proof_reads_use_the_two_read_batch_limit(self):
        self.assertEqual(self.evidence.read_batch_limit('codex'), 2)
        self.assertEqual(self.evidence.read_batch_limit('claude'), 2)
        self.assertEqual(self.evidence.read_batch_limit('cursor-sdk'), 1)

    def test_source_only_segment_turn_checks_adapter_membership_and_bytes(self):
        calls = ['segment-1', 'segment-2', 'segment-3', 'segment-4']
        required = [(call, 1) for call in calls]
        outputs = {call: {'success': True, 'bytes': 15 * 1024} for call in calls}
        helper = self.audit.source_only_segment_turn
        self.assertTrue(helper('claude', calls, outputs, required, 4))
        self.assertFalse(helper('codex', calls, outputs, required, 4))
        self.assertFalse(helper('claude', calls[:3] + ['index'], outputs, required, 4))
        failed = {**outputs, 'segment-4': {'success': False, 'bytes': 1}}
        self.assertFalse(helper('claude', calls, failed, required, 4))
        missing = {k: v for k, v in outputs.items() if k != 'segment-4'}
        self.assertFalse(helper('claude', calls, missing, required, 4))
        oversized = {**outputs, 'segment-4': {'success': True, 'bytes': 32 * 1024 + 1}}
        self.assertFalse(helper('claude', calls, oversized, required, 4))
        too_large = {call: {'success': True, 'bytes': 16 * 1024} for call in calls}
        self.assertFalse(helper('claude', calls, too_large, required, 4))

    def test_ordered_proof_turn_limit_rejects_output_over_60_kib(self):
        calls = ['read-1', 'read-2']
        proof_calls = set(calls)
        self.assertTrue(self.audit.ordered_proof_turn_exempt(
            2, calls, proof_calls, 60 * 1024))
        mixed_calls = ['required-segment', 'evidence-index']
        self.assertTrue(self.audit.ordered_proof_turn_exempt(
            2, mixed_calls, set(mixed_calls), 40 * 1024))
        self.assertFalse(self.audit.ordered_proof_turn_exempt(
            2, mixed_calls, {'evidence-index'}, 40 * 1024))
        self.assertFalse(self.audit.ordered_proof_turn_exempt(
            2, calls, proof_calls, 60 * 1024 + 1))

    def test_context_read_outside_a_path_scope_is_audited(self):
        allowed = self.evidence.source_range_path_allowed
        context = {'path': 'src/app/defaults.tsx', 'line_start': 1, 'line_end': 20, 'origin': 'tool'}
        self.assertTrue(allowed(context, 'src/history'))
        self.assertFalse(allowed(dict(context, origin='packet'), 'src/history'))
        self.assertFalse(allowed({'path': '/etc/passwd', 'origin': 'tool'}, 'src/history'))
        self.assertFalse(allowed({'path': '../secret', 'origin': 'tool'}, 'src/history'))
        self.assertTrue(allowed(context, '.'))

    def test_finding_outside_a_path_scope_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp)
            (session / 'r1-sol.json').write_text(json.dumps({
                'findings': [{'file': 'src/app/defaults.tsx', 'claim': 'callers live here'}]}))
            manifest = {'label': '1', 'scope': 'src/history', 'assignments': {'sol': {}}}
            with self.assertRaisesRegex(ValueError, 'finding outside literal review scope'):
                self.evidence.finding_ownership(session, manifest)
