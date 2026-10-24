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
            fixture, {f'src/use{index:02d}.py': (1, 2) for index in range(15)})
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


if __name__ == '__main__':
    unittest.main()
