"""Claude seats are stopped before a partial or skipped required read discards the review."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_deleted_source_proof import SCRIPTS, SourceFixture, load_read_audit


class ClaudeReadGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='claude-read-gate-')
        cls.directory = Path(cls.temp.name)
        cls.fixture = SourceFixture(
            cls.directory / 'segments', 'deleted', adapter='claude', compact_segment_lines=1500)
        cls.audit = load_read_audit()
        fixture = cls.fixture
        assignment = fixture.manifest['assignments'][fixture.seat]
        cls.chunks = [fixture.session / row['artifact'] for row in
                      fixture.manifest['patch_sets'][assignment['patch_set']]['chunks']]
        cls.packets = [fixture.session / shard['artifact'] for shard in fixture.context['shards']]
        cls.segments = [fixture.session / segment['artifact']
                        for required in fixture.context['required_source_ranges']
                        for segment in required['segments']]
        cls.index = fixture.session / f'r{fixture.label}-evidence.md'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        state = tempfile.TemporaryDirectory(prefix='claude-stop-gate-')
        self.addCleanup(state.cleanup)
        self.state = Path(state.name) / 'r1-sol.stop-gate'

    def hook(self, name, data):
        fixture = self.fixture
        args = argparse.Namespace(root=str(fixture.root), session=str(fixture.session),
                                  prompt=str(fixture.prompt), deps=None)
        stderr = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps({'tool_name': name, 'tool_input': data}))), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            status = self.audit.hook(args)
        return status, stderr.getvalue()

    def transcript(self, omitted=(), fixture=None):
        raw, _, _ = (fixture or self.fixture).claude_transcript(
            omitted_artifacts=tuple(path.name for path in omitted))
        return raw

    @staticmethod
    def denied(path, data, code):
        call_id = 'denied-' + path.name
        reason = ('PreToolUse:Read hook error: [python3 review-read-audit.py hook]: '
                  f'review read blocked: {code}; read {path} completely in one Read call '
                  'with no offset or limit\n')
        return [
            {'type': 'assistant', 'message': {'id': 'turn-' + call_id, 'content': [
                {'type': 'tool_use', 'id': call_id, 'name': 'Read',
                 'input': {'file_path': str(path), **data}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': call_id, 'content': reason,
                 'is_error': True}]}},
        ]

    @staticmethod
    def events(raw):
        return [json.loads(line) for line in Path(raw).read_text().splitlines()]

    @staticmethod
    def write(raw, events):
        Path(raw).write_text(''.join(json.dumps(event) + '\n' for event in events))

    def insert_before_read(self, raw, path, inserted):
        events = self.events(raw)
        position = next(index for index, event in enumerate(events)
                        if event['type'] == 'assistant' and any(
                            block['input'].get('file_path') == str(path)
                            for block in event['message']['content']))
        self.write(raw, events[:position] + inserted + events[position:])

    def test_hook_denies_reads_the_audit_cannot_credit_as_whole(self):
        cases = [(self.chunks[0], 'partial-patch-chunk'),
                 (self.packets[0], 'partial-source-packet'),
                 (self.segments[0], 'partial-required-source-segment'),
                 (self.index, 'partial-evidence-index')]
        for path, code in cases:
            remedy = (f'review read blocked: {code}; read {path.resolve()} completely in one '
                      'Read call with no offset or limit')
            for bounds in ({'limit': 20}, {'offset': 2}, {'offset': 1, 'limit': 3}):
                with self.subTest(artifact=path.name, bounds=bounds):
                    status, stderr = self.hook('Read', {'file_path': str(path), **bounds})
                    self.assertEqual(status, 2)
                    self.assertIn(remedy, stderr)
                    self.assertEqual(len(stderr.splitlines()), 1)
            with self.subTest(artifact=path.name, tool='Grep'):
                status, stderr = self.hook(
                    'Grep', {'pattern': 'def', 'path': str(path), 'head_limit': 5})
                self.assertEqual(status, 2)
                self.assertIn(remedy, stderr)

    def test_hook_allows_complete_reads_and_keeps_other_rules(self):
        for path in (self.chunks[0], self.packets[0], self.segments[0], self.index):
            with self.subTest(artifact=path.name):
                self.assertEqual(self.hook('Read', {'file_path': str(path)}), (0, ''))
        lines = len(self.index.read_bytes().splitlines())
        self.assertEqual(self.hook('Read', {'file_path': str(self.index), 'offset': 1,
                                            'limit': lines}), (0, ''))
        self.assertEqual(self.hook('Read', {'file_path': str(self.fixture.prompt),
                                            'offset': 1, 'limit': 40}), (0, ''))
        status, stderr = self.hook('Read', {'file_path': str(self.fixture.root / 'keep.txt')})
        self.assertEqual(status, 2)
        self.assertIn('review read blocked: unbounded-read', stderr)

    def test_a_denied_partial_read_leaves_the_audit_verdict_unchanged(self):
        raw = self.transcript()
        segment = self.segments[2]
        self.insert_before_read(raw, segment, self.denied(
            segment, {'limit': 20}, 'partial-required-source-segment'))
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(raw), '--prompt', str(self.fixture.prompt),
             '--root', str(self.fixture.root), '--session', str(self.fixture.session),
             '--out', str(self.state.with_name('audit.json'))],
            env=self.fixture.env, text=True, capture_output=True)
        audit = json.loads(self.state.with_name('audit.json').read_text())
        self.assertEqual((process.returncode, audit['violations']), (0, []))

if __name__ == '__main__':
    unittest.main()
