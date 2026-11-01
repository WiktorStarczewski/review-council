"""Full code scopes retain exact consumer and edited-assertion source proofs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from test_deleted_source_proof import SCRIPTS, SourceFixture, load_evidence


class PromotionFixture(SourceFixture):
    def __init__(self, directory):
        self.root = directory / 'repo'
        self.session = directory / 'session'
        self.root.mkdir()
        self.session.mkdir()
        self.env = dict(os.environ, REV_PATCH_CHUNKS='auto', REV_SOURCE_CONTEXT='1')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(directory / 'no-hooks'))
        self.write('unchanged.txt', 'preserve full branch context\n')
        self.label = '1'
        self.phase = 'discovery'
        self.seat = 'sol'

    def write(self, path, content):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)

    def freeze(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        (self.session / 'scope.env').write_text(
            f'REV_BASE={shlex.quote(self.base)}\n'
            f'REV_ROOT={shlex.quote(str(self.root))}\nREV_SCOPE=branch\n')
        for name in ('files.txt', 'untracked.txt'):
            (self.session / name).write_text('')
        (self.session / 'roster.json').write_text(json.dumps({'seats': [
            {'seat': seat, 'adapter': 'codex'}
            for seat in ('sol', 'second', 'third', 'fourth')
        ]}))

    def prepare(self):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare',
             str(self.session), self.label, '--phase', self.phase, '--full-seat', self.seat],
            env=self.env, text=True, capture_output=True, timeout=60)

    def load(self):
        self.manifest_path = self.session / 'r1-evidence.manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text())
        self.context = self.manifest['source_context']['seats'][self.seat]
        self.prompt = self.session / 'r1-sol.prompt.md'
        assignment = self.manifest['assignments'][self.seat]
        subprocess.run(
            [str(SCRIPTS / 'rev-prompt.sh'), str(self.session), self.label,
             self.seat, assignment['bundle'], 'complete code source proof',
             '--evidence', str(self.manifest_path)],
            env=self.env, text=True, capture_output=True, check=True, timeout=60)


class CodeSourcePromotionTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='code-source-promotion-')
        self.addCleanup(temporary.cleanup)
        return PromotionFixture(Path(temporary.name))

    def callers(self):
        fixture = self.fixture()
        declarations = []
        for index in range(15):
            declarations.append(f'def fn{index:02d}():\n    return "{"x" * 10000}"\n')
            fixture.write(f'src/use{index:02d}.py',
                          f'from src.lib import fn{index:02d}\n'
                          f'def use{index:02d}():\n    return fn{index:02d}("{"y" * 8000}")\n')
        fixture.write('src/lib.py', '\n'.join(declarations))
        fixture.freeze()
        fixture.write('src/lib.py', '\n'.join(declarations).replace('return "x', 'return "z'))
        return fixture

    def assert_full_proof(self, fixture, required_ranges):
        status_before = fixture.git('status', '--porcelain')
        process = fixture.prepare()
        self.assertEqual(process.returncode, 0, process.stderr)
        fixture.load()
        evidence = load_evidence()
        repository = evidence.Repository(fixture.session.resolve())
        snapshot, unsafe = repository.snapshot()
        self.assertEqual(unsafe, [])
        self.assertEqual(fixture.manifest['snapshot_tree'], snapshot)
        self.assertEqual(fixture.manifest['scope'], '.')
        self.assertEqual(fixture.git('status', '--porcelain'), status_before)
        self.assertIn('unchanged.txt', repository.entries(snapshot))
        expected_changes = ({'src/lib.py'} if (fixture.root / 'src/lib.py').exists()
                            else set(required_ranges))
        self.assertEqual(set(fixture.manifest['paths']), expected_changes)
        self.assertTrue(fixture.context['required_source_ranges'],
                        'the fixture must exercise mandatory segment promotion')
        delivered = [row for shard in fixture.context['shards'] for row in shard['ranges']]
        delivered += fixture.context['required_source_ranges']
        for path, (start, end) in required_ranges.items():
            self.assertTrue(evidence.source_target_covered(
                {'path': path, 'line_start': start, 'line_end': end}, delivered), path)
        for required in fixture.context['required_source_ranges']:
            self.assertEqual(required['blob_tree'], snapshot)
            raw = fixture.current_bytes(required).encode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), required['content_sha256'])
            segments = b''.join((fixture.session / segment['artifact']).read_bytes()
                                for segment in required['segments'])
            self.assertEqual(segments, raw)
        for capacity in fixture.manifest['task_capacity']['seats'].values():
            self.assertLessEqual(capacity['mandatory_repository_reads'], 12)
        facts = json.loads((fixture.session / 'r1-evidence.json').read_text())
        for seat, assignment in fixture.manifest['assignments'].items():
            packet = fixture.manifest['source_context']['seats'][seat]
            obligations, _ = evidence.code_proof_obligations(
                assignment, fixture.manifest['components'], facts, packet)
            self.assertEqual(obligations, [], 'every residual code proof must be delivered: ' + seat)
        evidence.validated_manifest(fixture.manifest_path)
        return evidence, repository

    def test_many_real_consumers_are_promoted_with_complete_branch_scope(self):
        fixture = self.callers()
        evidence, repository = self.assert_full_proof(
            fixture, {f'src/use{index:02d}.py': (1, 3) for index in range(15)})
        target = evidence.repository_source_target(fixture.context, fixture.manifest['snapshot_tree'])
        source = (target, None, fixture.current_bytes(target)) if target is not None else None
        status, audit = fixture.audit(source=source)
        self.assertEqual(status, 0, audit['violations'])
        fixture.receipt_gate(audit)
        omitted = fixture.context['required_source_ranges'][0]['segments'][0]['artifact']
        status, audit = fixture.audit(source=source, omitted_artifacts=(omitted,))
        self.assertNotEqual(status, 0)
        self.assertIn('missing-required-source-segment',
                      {row['code'] for row in audit['violations']})
        forged = copy.deepcopy(fixture.manifest)
        forged['source_context']['seats'][fixture.seat]['required_source_ranges'].pop()
        with self.assertRaises(ValueError):
            evidence.validate_source_context_snapshot(repository, fixture.session, forged)

    def test_edited_assertions_are_promoted_beyond_packet_and_manual_read_capacity(self):
        fixture = self.fixture()
        paths = [f'tests/test_{index:02d}.py' for index in range(26)]
        for index, path in enumerate(paths):
            fixture.write(path, f'def test_{index:02d}():\n    assert "old{"x" * 8000}"\n')
        fixture.freeze()
        for path in paths:
            fixture.write(path, (fixture.root / path).read_text().replace('assert "old', 'assert "new'))
        self.assert_full_proof(fixture, {path: (2, 2) for path in paths})

    def test_type_only_consumers_do_not_expand_changed_static_method_docs(self):
        fixture = self.fixture()
        declaration = '''export interface ClientOptions { feeFaucetId?: string; }
export declare class MidenClient {
  /**
   * Creates and initializes a new MidenClient.
   *
   * Every non-mock client must name the chain's fee faucet in
   * {@link ClientOptions.feeFaucetId} while the SDK carries a default for no
   * network; without it creation fails with an error saying so.
   */
  static create(options?: ClientOptions): Promise<MidenClient>;
  /**
   * Creates a client preconfigured for testnet (rpc, prover, note transport, autoSync).
   *
   * Still needs {@link ClientOptions.feeFaucetId}: the preconfigured defaults
   * cover the endpoints, not the chain's fee asset.
   */
  static createTestnet(options?: ClientOptions): Promise<MidenClient>;
  /**
   * Creates a client preconfigured for devnet (rpc, prover, note transport, autoSync).
   *
   * Still needs {@link ClientOptions.feeFaucetId}: the preconfigured defaults
   * cover the endpoints, not the chain's fee asset.
   */
  static createDevnet(options?: ClientOptions): Promise<MidenClient>;
}
'''
        updated_declaration = declaration.replace(
            "   * Every non-mock client must name the chain's fee faucet in\n"
            '   * {@link ClientOptions.feeFaucetId} while the SDK carries a default for no\n'
            '   * network; without it creation fails with an error saying so.\n',
            '   * {@link ClientOptions.feeFaucetId} is optional: the client receives the\n'
            "   * chain's protocol configuration, which names the fee asset, from the node\n"
            '   * when it syncs. The option only sets what `feeFaucetId()` reports before\n'
            '   * that first sync.\n')
        updated_declaration = updated_declaration.replace(
            '   * Still needs {@link ClientOptions.feeFaucetId}: the preconfigured defaults\n'
            "   * cover the endpoints, not the chain's fee asset.\n",
            '   * {@link ClientOptions.feeFaucetId} is optional: the client receives the\n'
            "   * chain's protocol configuration, which names the fee asset, from the node\n"
            '   * when it syncs. The option only sets what `feeFaucetId()` reports before\n'
            '   * that first sync.\n')
        old_changelog = (
            '* [FIX][docs] The shipped agent guides no longer call `feeFaucetId` required. '
            'The `@miden-sdk/react` and `@miden-sdk/miden-sdk` `AGENTS.md`, the '
            '`web-client-usage` skill, the root README and the Turnkey React example said '
            'a client or provider created without it fails; since 0.17 the client receives '
            'the fee asset with the protocol configuration when it syncs, and the option '
            'only sets what `client.feeFaucetId()` reports before the first sync. The guides '
            'now say so, including that `feeFaucetId()` rejects before the first sync on a '
            'client created without it ([#515](https://github.com/0xMiden/web-sdk/issues/515), '
            '[#517](https://github.com/0xMiden/web-sdk/pull/517)).\n')
        new_changelog = (
            '* [FIX][docs] The shipped agent guides and type declarations no longer call '
            '`feeFaucetId` required. The `@miden-sdk/react` and `@miden-sdk/miden-sdk` '
            '`AGENTS.md`, the `web-client-usage` skill, the root README, the Turnkey React '
            'example and the `MidenClient.create`, `createTestnet` and `createDevnet` '
            'declaration JSDoc said a client or provider created without it fails; since '
            '0.17 the client receives the fee asset with the protocol configuration when '
            'it syncs, and the option only sets what `client.feeFaucetId()` reports before '
            'the first sync. They now say so, including that `feeFaucetId()` rejects before '
            'the first sync on a client created without it '
            '([#515](https://github.com/0xMiden/web-sdk/issues/515), '
            '[#517](https://github.com/0xMiden/web-sdk/pull/517), '
            '[#518](https://github.com/0xMiden/web-sdk/pull/518)).\n')
        fixture.write('CHANGELOG.md', old_changelog)
        declaration_path = 'crates/web-client/js/types/api-types.d.ts'
        fixture.write(declaration_path, declaration)
        fixture.write('src/client-factory.ts',
                      "import { MidenClient } from '../crates/web-client/js/types/api-types';\n"
                      'export async function createClient() {\n'
                      '  return MidenClient.create({ feeFaucetId: "faucet" });\n'
                      '}\n')
        fixture.write('tests/miden-client-create.test.ts',
                      "import { MidenClient } from '../crates/web-client/js/types/api-types';\n"
                      'export async function createsTestnetClient() {\n'
                      '  return MidenClient.createTestnet();\n'
                      '}\n')
        type_only_paths = set()
        for index in range(100):
            path = f'tests/type_only_consumer_{index:03}.test.ts'
            type_only_paths.add(path)
            fixture.write(path,
                          "import type { MidenClient } from '../crates/web-client/js/types/api-types';\n"
                          f'type ClientShape{index:03} = MidenClient;\n')
        fixture.freeze()
        fixture.seat = 'codex-luna'
        (fixture.session / 'roster.json').write_text(json.dumps({'seats': [
            {'seat': seat, 'adapter': 'codex', 'model': 'gpt-6-luna'}
            for seat in ('codex-luna', 'codex-luna-2', 'codex-luna-3', 'codex-luna-4')
        ]}))
        fixture.write('CHANGELOG.md', new_changelog)
        fixture.write(declaration_path, updated_declaration)
        changed = set(fixture.git('diff', '--name-only', fixture.base).splitlines())
        self.assertEqual(changed, {'CHANGELOG.md', declaration_path})

        process = fixture.prepare()
        self.assertEqual(process.returncode, 0, process.stderr)
        fixture.load()
        self.assertEqual(set(fixture.manifest['paths']), changed)
        self.assertEqual(fixture.manifest['scope'], '.')
        facts = json.loads((fixture.session / 'r1-evidence.json').read_text())
        related = {row['path'] for row in facts['related_tests']}
        self.assertEqual(related, {'tests/miden-client-create.test.ts'})
        delivered = [row for shard in fixture.context['shards'] for row in shard['ranges']]
        delivered += fixture.context['required_source_ranges']
        delivered_paths = {row['path'] for row in delivered}
        self.assertIn(declaration_path, delivered_paths)
        self.assertIn('src/client-factory.ts', delivered_paths)
        self.assertIn('tests/miden-client-create.test.ts', delivered_paths)
        self.assertFalse(type_only_paths & delivered_paths)
        capacity = fixture.manifest['task_capacity']['seats'][fixture.seat]
        self.assertEqual(capacity['mandatory_repository_read_limit'], 96)
        self.assertLessEqual(capacity['mandatory_repository_reads'], 96)

    def test_missing_import_target_still_refuses_before_manifest_publication(self):
        fixture = self.fixture()
        fixture.write('Cargo.toml', '[package]\nname = "fixture_game"\nversion = "0.1.0"\n')
        fixture.write('src/lib.rs', 'pub mod missing;\npub mod consumer;\n')
        fixture.write('src/consumer.rs',
                      'use crate::missing as options;\n'
                      'pub fn consume() -> usize { options::read_options() }\n')
        fixture.write('src/other.rs', 'pub fn read_options() -> usize { 1 }\n')
        fixture.freeze()
        fixture.write('src/other.rs', 'pub fn read_options() -> usize { 2 }\n')
        process = fixture.prepare()
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertIn('unreadable import candidates', process.stderr)
        self.assertFalse((fixture.session / 'r1-evidence.manifest.json').exists())
        diagnostic = json.loads((fixture.session / 'prepare-diagnostic-1.json').read_text())
        self.assertFalse(diagnostic['certifying'])

    def test_deleted_import_candidate_retains_its_exact_historical_segments(self):
        fixture = self.fixture()
        fixture.write('Cargo.toml', '[package]\nname = "fixture_game"\nversion = "0.1.0"\n')
        fixture.write('src/lib.rs', 'pub mod options;\npub mod consumer;\n')
        fixture.write('src/options.rs',
                      'pub fn keep() -> usize { 1 }\n\n\n'
                      'pub fn retired() -> usize {\n    2 // ' + 'x' * 20000 + '\n}\n')
        fixture.write('src/consumer.rs',
                      'use crate::options as opts;\n'
                      'pub fn consume() -> usize { opts::retired() }\n')
        fixture.freeze()
        fixture.write('src/options.rs', 'pub fn keep() -> usize { 1 }\n')
        process = fixture.prepare()
        self.assertEqual(process.returncode, 0, process.stderr)
        fixture.load()
        assignment = fixture.manifest['assignments'][fixture.seat]
        self.assertEqual(
            fixture.manifest['patch_sets'][assignment['patch_set']]['read_mode'], 'windows')
        evidence = load_evidence()
        facts = json.loads((fixture.session / 'r1-evidence.json').read_text())
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.rs')
        retired = next(row for row in obligation['candidate_symbols'] if row['name'] == 'retired')
        self.assertEqual(retired['blob_tree'], fixture.manifest['base_tree'])
        historical = [row for row in fixture.context['required_source_ranges']
                      if row['path'] == 'src/options.rs'
                      and row['blob_tree'] == fixture.manifest['base_tree']]
        self.assertTrue(historical, 'the deleted declaration must require exact historical segments')
        self.assertTrue(any(row['line_start'] <= 4 and row['line_end'] >= 6 for row in historical))
        target = evidence.repository_source_target(fixture.context, fixture.manifest['snapshot_tree'])
        source = (target, None, fixture.current_bytes(target)) if target is not None else None
        status, audit = fixture.audit(source=source)
        self.assertEqual(status, 0, audit['violations'])
        fixture.receipt_gate(audit)
        segment = historical[0]['segments'][0]['artifact']
        status, audit = fixture.audit(source=source, omitted_artifacts=(segment,))
        self.assertNotEqual(status, 0)
        self.assertIn('missing-required-source-segment',
                      {row['code'] for row in audit['violations']})
        evidence.validated_manifest(fixture.manifest_path)

    def test_historical_and_current_proofs_at_same_coordinates_do_not_cover_each_other(self):
        evidence = load_evidence()
        path = 'tests/policy.rs'
        assignment = {'adapter': 'codex', 'full_state': True}
        components = [{'id': 'policy', 'files': [path]}]
        facts = {
            'snapshot_tree': 'current', 'base_tree': 'historical',
            'hunks': [{'path': path, 'kind': 'modify', 'changed_lines': [2]}],
            'unresolved_imports': [{
                'path': 'src/consumer.rs', 'line_start': 1, 'line_end': 1,
                'candidate_symbols': [{
                    'path': path, 'name': 'retired', 'line_start': 2, 'line_end': 2,
                    'blob_tree': 'historical',
                }],
            }],
        }
        for delivered_tree, missing_tree in [('historical', 'current'), ('current', 'historical')]:
            with self.subTest(delivered_tree=delivered_tree):
                packet = {'required_source_ranges': [{
                    'path': path, 'line_start': 2, 'line_end': 2, 'blob_tree': delivered_tree,
                }]}
                ranges, _ = evidence.code_proof_obligations(
                    assignment, components, facts, packet, with_tree=True)
                self.assertIn((path, 2, 2, missing_tree), ranges)
                self.assertNotIn((path, 2, 2, delivered_tree), ranges)

    def test_owned_import_keeps_other_candidates_outside_assigned_files(self):
        evidence = load_evidence()
        assignment = {'adapter': 'codex', 'components': ['active']}
        components = [{'id': 'active', 'files': ['src/active.ts']}]
        facts = {'snapshot_tree': 'current', 'unresolved_imports': [{
            'path': 'src/consumer.ts', 'line_start': 1, 'line_end': 1,
            'candidate_targets': ['src/active.ts', 'lib/history.ts'],
            'candidate_symbols': [
                {'path': 'src/active.ts', 'line_start': 1, 'line_end': 2},
                {'path': 'lib/history.ts', 'line_start': 8, 'line_end': 10},
            ],
        }]}
        ranges, owners = evidence.code_proof_obligations(
            assignment, components, facts, {}, with_tree=True)
        self.assertIn(('lib/history.ts', 8, 10, 'current'), ranges)
        self.assertEqual(owners[('lib/history.ts', 'current')], {'src/active.ts'})


if __name__ == '__main__':
    unittest.main()
