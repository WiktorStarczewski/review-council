"""Boundary source proofs retain the component that assigned the source row."""
import json
from pathlib import Path
import tempfile
import unittest

from test_code_source_promotion import PromotionFixture
from test_deleted_source_proof import load_evidence


class CodeProofOwnershipTests(unittest.TestCase):
    def test_boundary_only_changed_symbol_keeps_routed_specialist_owner(self):
        evidence = load_evidence()
        components = [
            {'id': 'test', 'files': ['tests/policy.test.ts']},
            {'id': 'export', 'files': ['lib/external.ts']},
        ]
        facts = {'snapshot_tree': 'current', 'symbols': [
            {'path': 'lib/external.ts', 'name': 'external'},
        ]}
        packet = {'omitted_source_ranges': [{
            'path': 'lib/external.ts', 'line_start': 1, 'line_end': 2,
            'blob_tree': 'current', 'reasons': ['production-caller:external'],
            'component_ids': ['test'],
        }]}
        assignment = {'adapter': 'codex', 'full_state': False, 'components': ['test']}
        ranges, owners = evidence.code_proof_obligations(
            assignment, components, facts, packet, with_tree=True)
        self.assertEqual(ranges, [('lib/external.ts', 1, 2, 'current')])
        self.assertEqual(owners[('lib/external.ts', 'current')], {'tests/policy.test.ts'})

    def test_complete_prepare_proves_boundary_callers_under_assigned_component(self):
        with tempfile.TemporaryDirectory(prefix='code-proof-ownership-') as directory:
            fixture = PromotionFixture(Path(directory))
            fixture.write('lib/external.ts',
                          'export function external() { return 1; }\n'
                          'export function wrapper() { return external(); }\n')
            fixture.write('lib/secondary.ts', 'export function secondary() { return 1; }\n')
            fixture.write('tests/policy.test.ts',
                          "import { external } from '../lib/external';\n"
                          "import { secondary } from '../lib/secondary';\n"
                          "test('policy', () => expect(external() + secondary()).toBe(2));\n")
            fixture.freeze()
            fixture.write('lib/external.ts',
                          'export function external() { return 2; }\n'
                          'export function wrapper() { return external(); }\n')
            fixture.write('lib/secondary.ts', 'export function secondary() { return 2; }\n')
            fixture.write('tests/policy.test.ts',
                          "import { external } from '../lib/external';\n"
                          "import { secondary } from '../lib/secondary';\n"
                          "test('policy', () => expect(external() + secondary()).toBe(4));\n")
            process = fixture.prepare()
            self.assertEqual(process.returncode, 0, process.stderr)
            fixture.load()
            evidence = load_evidence()
            manifest = fixture.manifest
            component = next(row for row in manifest['components']
                             if row['files'] == ['tests/policy.test.ts'])
            specialist = component['specialists'][0]
            assignment = manifest['assignments'][specialist]
            self.assertFalse(assignment['full_state'])
            self.assertEqual(assignment['components'], [component['id']])
            self.assertIn('lib/external.ts', component['boundary'])
            context = manifest['source_context']['seats'][specialist]
            delivered = [row for shard in context['shards'] for row in shard['ranges']]
            delivered += context['required_source_ranges']
            caller = next(row for row in delivered
                          if row['path'] == 'lib/external.ts'
                          and 'production-caller:external' in row['reasons'])
            self.assertEqual(caller['component_ids'], [component['id']])
            self.assertIn('declaration:code-proof', caller['reasons'])
            facts = json.loads((fixture.session / 'r1-evidence.json').read_text())
            obligations, _ = evidence.code_proof_obligations(
                assignment, manifest['components'], facts, context)
            self.assertEqual(obligations, [])
            evidence.validated_manifest(fixture.manifest_path)


if __name__ == '__main__':
    unittest.main()
