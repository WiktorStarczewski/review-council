"""A required source range wholly inside the seat's assigned hunks is proven by its patch lines."""
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from test_deleted_source_proof import SCRIPTS, SourceFixture, load_evidence

WHOLE = ('def whole():\n    first = "' + 'a' * 7000 + '"\n    second = "' + 'b' * 7000
         + '"\n    return first + second + "' + 'c' * 7000 + '"')
PARTIAL = ('def partial():\n' + ''.join(f'    value_{index:02d} = "' + 'p' * 2000 + '"\n'
                                       for index in range(12)) + '    return "old"\n')


class PatchFixture(SourceFixture):
    """whole.py changes inside one hunk that holds all of it; partial.py changes only its
    last line, so its declaration starts ten lines before the hunk."""

    def __init__(self, directory, adapter='codex', chunks='1'):
        self.patch_window_lines = 2
        self.root = directory / 'repo'
        self.session = directory / 'session'
        self.root.mkdir(parents=True)
        self.session.mkdir()
        self.env = dict(os.environ, REV_PATCH_CHUNKS=chunks, REV_SOURCE_CONTEXT='1')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(directory / 'no-hooks'))
        (self.root / 'whole.py').write_text(WHOLE)
        (self.root / 'partial.py').write_text(PARTIAL)
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        (self.root / 'whole.py').write_text(WHOLE.replace('"a', '"A', 1))
        (self.root / 'partial.py').write_text(PARTIAL.replace('"old"', '"new"'))
        (self.session / 'scope.env').write_text(
            f'REV_BASE={shlex.quote(self.base)}\n'
            f'REV_ROOT={shlex.quote(str(self.root))}\nREV_SCOPE=branch\n')
        for name in ('files.txt', 'untracked.txt'):
            (self.session / name).write_text('')
        (self.session / 'roster.json').write_text(json.dumps({'seats': [
            {'seat': seat, 'adapter': 'codex', 'model': 'gpt-6-luna', 'effort': 'xhigh'}
            if seat != 'sol' or adapter == 'codex' else {'seat': seat, 'adapter': adapter}
            for seat in ('sol', 'second', 'third', 'fourth')]}))
        self.label = '1'
        self.phase = 'discovery'
        self.run('prepare', str(self.session), self.label, '--phase', self.phase,
                 '--full-seat', 'sol')
        self.manifest_path = self.session / 'r1-evidence.manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text())
        self.seat = self.manifest['mechanical_owner']
        self.context = self.manifest['source_context']['seats'][self.seat]
        self.prompt = self.session / f'r1-{self.seat}.prompt.md'
        subprocess.run([str(SCRIPTS / 'rev-prompt.sh'), str(self.session), '1', self.seat,
                        self.manifest['assignments'][self.seat]['bundle'], 'patch proof',
                        '--evidence', str(self.manifest_path)],
                       env=self.env, text=True, capture_output=True, check=True)

    def required(self, path):
        rows = [row for row in self.context['required_source_ranges'] if row['path'] == path]
        assert len(rows) == 1, rows
        return rows[0]

    def target_read(self):
        target = self.target()
        return target, None, self.current_bytes(target)

    def audit_claude_with_target(self):
        raw, _, audit_path = self.claude_transcript()
        target = self.target()
        read = {'type': 'tool_use', 'id': 'claude-target', 'name': 'Read', 'input': {
            'file_path': str(self.root / target['path']), 'offset': target['line_start'],
            'limit': target['line_end'] - target['line_start'] + 1}}
        result = {'type': 'tool_result', 'tool_use_id': 'claude-target',
                  'content': self.current_bytes(target)}
        with raw.open('a') as stream:
            stream.write(json.dumps({'type': 'assistant', 'message': {
                'id': 'claude-target-turn', 'content': [read]}}) + '\n')
            stream.write(json.dumps({'type': 'user', 'message': {'content': [result]}}) + '\n')
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(raw), '--prompt', str(self.prompt),
             '--root', str(self.root), '--session', str(self.session), '--out', str(audit_path)],
            env=self.env, text=True, capture_output=True)
        return process.returncode, json.loads(audit_path.read_text())

    def covering_chunks(self, row):
        patch = Path(self.manifest['assignments'][self.seat]['patch']).read_bytes()
        lines = patch.splitlines(keepends=True)
        start = sum(map(len, lines[:row['patch_proof']['patch_line_start'] - 1]))
        end = sum(map(len, lines[:row['patch_proof']['patch_line_end']]))
        patch_set = self.manifest['patch_sets'][
            self.manifest['assignments'][self.seat]['patch_set']]
        return [chunk['artifact'] for chunk in patch_set['chunks']
                if chunk['byte_start'] < end and start < chunk['byte_end']]


def finding(path, start, end):
    return {'summary': 'checked', 'findings': [{
        'severity': 'P2', 'file': path, 'line_start': start, 'line_end': end,
        'claim': 'the changed value is not covered', 'evidence': 'read in the assigned patch',
        'suggested_fix': 'cover it', 'confidence': 0.5}]}


def codes(audit):
    return {item['code'] for item in audit['violations']}


class PatchProvenSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        base = Path(cls.temp.name)
        cls.codex = PatchFixture(base / 'codex')
        cls.windows = PatchFixture(base / 'windows', chunks='0')
        cls.claude = PatchFixture(base / 'claude', adapter='claude')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_only_a_wholly_covered_range_drops_its_segments(self):
        for fixture in (self.codex, self.windows, self.claude):
            whole, partial = fixture.required('whole.py'), fixture.required('partial.py')
            self.assertEqual((whole['line_start'], whole['line_end'], whole['segments']), (1, 4, []))
            self.assertEqual(whole['patch_proof']['target']['line_start'], 1)
            self.assertNotIn('patch_proof', partial)
            self.assertEqual((partial['line_start'], partial['line_end']), (1, 14))
            self.assertTrue(partial['segments'])
            prompt = fixture.prompt.read_text()
            self.assertIn('Patch-proven source range: whole.py:1-4 ', prompt)
            self.assertIn('Required source range: partial.py:1-14 ', prompt)
            self.assertNotIn('source-segment-002-', prompt)
            self.assertEqual(len(list(fixture.session.glob('r1-sol-source-segment-*'))),
                             len(partial['segments']))

    def test_the_covering_patch_read_proves_the_range_and_its_citations(self):
        for fixture in (self.codex, self.windows):
            with self.subTest(mode=fixture.manifest['assignments']['sol']['patch_read_mode']):
                status, audit = fixture.audit(result=finding('whole.py', 2, 3),
                                              source=fixture.target_read())
                self.assertEqual(status, 0, audit['violations'])
                self.assertNotIn('citation_reaudit', audit)
                self.assertEqual(audit['required_source_ranges_covered'], 2)
                self.assertIn({'path': 'whole.py', 'line_start': 1, 'line_end': 4,
                               'origin': 'patch'}, audit['source_ranges'])
                self.assertEqual(audit['finding_citations'], 1)
                fixture.receipt_gate(audit)

    def test_a_skipped_covering_chunk_leaves_the_range_and_its_citation_unproven(self):
        skipped = self.codex.covering_chunks(self.codex.required('whole.py'))
        self.assertTrue(skipped)
        status, audit = self.codex.audit(result=finding('whole.py', 2, 3),
                                         omitted_artifacts=skipped,
                                         source=self.codex.target_read())
        self.assertEqual(status, 2)
        self.assertLessEqual({'missing-assigned-patch-chunk', 'missing-required-source-range',
                              'unsubstantiated-finding-range'}, codes(audit))
        self.assertNotIn('patch', {row['origin'] for row in audit['source_ranges']})
        self.assertNotIn('whole.py', {row['path'] for row in audit['required_source_range_proofs']})

    def test_a_partly_covered_range_still_needs_every_segment(self):
        partial = self.codex.required('partial.py')
        status, audit = self.codex.audit(
            result=finding('partial.py', 13, 14), source=self.codex.target_read(),
            omitted_artifacts=[partial['segments'][-1]['artifact']])
        self.assertEqual(status, 2)
        self.assertLessEqual({'missing-required-source-segment', 'unsubstantiated-finding-range'},
                             codes(audit))
        self.assertNotIn('partial.py', {row['path']
                                        for row in audit['required_source_range_proofs']})

    def test_a_codex_stage_plan_reads_no_segment_for_the_proven_range(self):
        stages = Path(self.temp.name) / 'codex-stages'
        proc = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/codex-proof-stages.py'), '--prompt',
             str(self.codex.prompt), '--seat', 'sol', '--model', 'gpt-6-luna',
             '--stage-dir', str(stages)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        reads = [Path(read['path']).name for stage in json.loads(
            (stages / 'stage-plan.json').read_text())['stages'] for read in stage['reads']]
        self.assertEqual([name for name in reads if '-source-segment-' in name],
                         [row['artifact'] for row in self.codex.required('partial.py')['segments']])

    def test_a_claude_seat_is_proven_by_the_same_patch_read(self):
        status, audit = self.claude.audit_claude_with_target()
        self.assertEqual(status, 0, audit['violations'])
        self.assertNotIn('citation_reaudit', audit)
        self.assertEqual(audit['required_source_ranges_covered'], 2)
        self.assertIn({'path': 'whole.py', 'line_start': 1, 'line_end': 4, 'origin': 'patch'},
                      audit['source_ranges'])
        self.claude.receipt_gate(audit)

    def test_the_manifest_cannot_claim_a_patch_proof_the_patch_does_not_hold(self):
        module = load_evidence()
        fixture = self.codex
        partial = fixture.required('partial.py')
        repo = module.Repository(fixture.session.resolve())
        for name, change in (
                ('partial range', lambda row: row if row['path'] != 'partial.py' else dict(
                    row, segments=[], patch_proof=dict(
                        fixture.required('whole.py')['patch_proof'],
                        target={key: partial['segments'][0][key]
                                for key in ('line_start', 'line_end', 'content_sha256')}))),
                ('shifted span', lambda row: row if row['path'] != 'whole.py' else dict(
                    row, patch_proof=dict(row['patch_proof'], patch_line_start=row[
                        'patch_proof']['patch_line_start'] + 1)))):
            with self.subTest(case=name):
                manifest = copy.deepcopy(fixture.manifest)
                packet = manifest['source_context']['seats']['sol']
                packet['required_source_ranges'] = [
                    change(row) for row in packet['required_source_ranges']]
                with self.assertRaisesRegex(ValueError, 'patch-proven source range'):
                    module.validate_source_context_bytes(repo, fixture.session, manifest)
        module.validate_source_context_bytes(repo, fixture.session, fixture.manifest)


class PatchNewSideTests(unittest.TestCase):
    def setUp(self):
        self.module = load_evidence()

    def index(self, *blocks):
        return self.module.patch_new_side_index(b''.join(blocks))

    def test_new_side_lines_follow_hunk_counts_and_missing_newlines(self):
        block = (b'diff --git a/f.py b/f.py\nindex 1..2 100644\n--- a/f.py\n+++ b/f.py\n'
                 b'@@ -1,2 +1,3 @@\n keep\n-old\n+new\n+last\n\\ No newline at end of file\n'
                 b'@@ -9 +10,0 @@\n-gone\n')
        self.assertEqual(self.index(block)[b'diff --git a/f.py b/f.py\n'],
                         {1: (6, b'keep\n'), 2: (8, b'new\n'), 3: (9, b'last')})
        row = {'path': 'f.py', 'line_start': 2, 'line_end': 3}
        mapped = self.index(block)
        self.assertEqual(self.module.patch_proof_span(mapped, row, [b'keep\n', b'new\n', b'last']),
                         (8, 9))
        self.assertIsNone(self.module.patch_proof_span(
            mapped, row, [b'keep\n', b'new\n', b'last\n']))
        self.assertIsNone(self.module.patch_proof_span(
            mapped, dict(row, line_end=4), [b'keep\n', b'new\n', b'last', b'more\n']))

    def test_an_unreadable_or_repeated_block_proves_nothing(self):
        header = b'diff --git a/f.py b/f.py\n'
        good = header + b'@@ -1 +1 @@\n-a\n+b\n'
        self.assertIsNone(self.index(header + b'@@ -1,2 +1,2 @@\n-a\n+b\n')[header])
        self.assertIsNone(self.index(header + b'@@ -1 +1 @@\n-a\n+b\nstray\n')[header])
        self.assertIsNone(self.index(good, good)[header])
        quoted = b'diff --git "a/sp\\303\\244ce.py" "b/sp\\303\\244ce.py"\n@@ -0,0 +1 @@\n+x\n'
        self.assertEqual(self.module.patch_proof_span(
            self.index(good, quoted), {'path': 'späce.py', 'line_start': 1, 'line_end': 1},
            [b'x\n']), (7, 7))


if __name__ == '__main__':
    unittest.main()
