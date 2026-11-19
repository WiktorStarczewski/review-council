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

    def stop(self, raw, *, active=False, fixture=None, payload=None, prompt=None):
        fixture = fixture or self.fixture
        args = argparse.Namespace(
            adapter='claude', raw=str(raw), prompt=str(prompt or fixture.prompt),
            root=str(fixture.root),
            session=str(fixture.session), seat=None, deps=None, state=str(self.state))
        event = payload if payload is not None else json.dumps(
            {'hook_event_name': 'Stop', 'stop_hook_active': active})
        stdout = io.StringIO()
        with patch('sys.stdin', io.StringIO(event)), contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(io.StringIO()):
            status = self.audit.stop_hook(args)
        self.assertEqual(status, 0)
        return json.loads(stdout.getvalue()) if stdout.getvalue().strip() else None

    def submit(self, raw, tool='StructuredOutput', *, fixture=None, result=None):
        decision = self.stop(raw, fixture=fixture, payload=json.dumps({
            'hook_event_name': 'PreToolUse', 'tool_name': tool,
            'tool_input': result or {'summary': 'done', 'findings': []}}))
        if decision is None:
            return None
        specific = decision['hookSpecificOutput']
        self.assertEqual((specific['hookEventName'], specific['permissionDecision']),
                         ('PreToolUse', 'deny'))
        return specific['permissionDecisionReason']

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
                 (self.segments[0], 'partial-required-source-segment')]
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

    def test_bounded_and_grep_index_reads_after_a_complete_read_are_allowed(self):
        lines = self.index.read_text().splitlines(keepends=True)
        pattern = lines[0].strip()
        calls = [('Read', {'file_path': str(self.index), 'offset': 1, 'limit': 3},
                  ''.join(lines[:3])),
                 ('Grep', {'pattern': pattern, 'path': str(self.index), 'output_mode': 'content',
                           'head_limit': 5}, lines[0])]
        for name, data, _ in calls:
            with self.subTest(tool=name):
                self.assertEqual(self.hook(name, data), (0, ''))
        raw = self.transcript()
        events = self.events(raw)
        for number, (name, data, output) in enumerate(calls):
            call_id = f'index-again-{number}'
            events += [
                {'type': 'assistant', 'message': {'id': 'turn-' + call_id, 'content': [
                    {'type': 'tool_use', 'id': call_id, 'name': name, 'input': data}]}},
                {'type': 'user', 'message': {'content': [
                    {'type': 'tool_result', 'tool_use_id': call_id, 'content': output}]}}]
        self.write(raw, events)
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(raw), '--prompt', str(self.fixture.prompt),
             '--root', str(self.fixture.root), '--session', str(self.fixture.session),
             '--out', str(self.state.with_name('audit.json'))],
            env=self.fixture.env, text=True, capture_output=True)
        audit = json.loads(self.state.with_name('audit.json').read_text())
        self.assertEqual((process.returncode, audit['violations']), (0, []))
        self.assertEqual(audit['tool_calls'], len(self.events(raw)) // 2)

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

    def test_stop_gate_lists_the_next_missing_reads_in_protocol_order(self):
        raw = self.transcript(omitted=[*self.segments[3:], self.index])
        decision = self.stop(raw)
        self.assertEqual(decision['decision'], 'block')
        reason = decision['reason']
        self.assertIn('read audit', reason)
        self.assertIn('completely in one Read call with no offset or limit', reason)
        self.assertIn('StructuredOutput', reason)
        positions = [reason.index(str(path.resolve())) for path in [*self.segments[3:], self.index]]
        self.assertEqual(positions, sorted(positions))
        for path in self.segments[:3]:
            self.assertNotIn(str(path.resolve()), reason)
        self.assertEqual(json.loads(self.state.read_text())['blocks'], 1)
        self.assertNotIn('\n', reason)

    def test_structured_output_is_denied_while_required_reads_remain(self):
        raw = self.transcript(omitted=[*self.segments[5:], self.index])
        reason = self.submit(raw)
        positions = [reason.index(str(path.resolve())) for path in [*self.segments[5:], self.index]]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('return your complete result again with StructuredOutput', reason)
        self.assertIsNone(self.submit(raw))
        self.assertIsNone(self.submit(raw, tool='Read'))
        self.assertEqual(json.loads(self.state.read_text())['blocks'], 1)
        self.assertIn('(2 of 3)', self.submit(self.transcript(omitted=[self.segments[6], self.index])))
        last_segment_only = self.transcript(omitted=[self.segments[6]])
        self.assertIn('(3 of 3)', self.stop(last_segment_only)['reason'])
        self.assertIsNone(self.submit(last_segment_only))
        self.assertIsNone(self.submit(self.transcript()))

    def test_structured_output_gate_replays_only_settled_events(self):
        raw = self.transcript(omitted=[*self.segments[5:], self.index])
        events = self.events(raw) + [{'type': 'assistant', 'message': {
            'id': 'final-turn', 'content': [
                {'type': 'tool_use', 'id': 'final-output', 'name': 'StructuredOutput',
                 'input': {'summary': 'done', 'findings': []}}]}}]
        self.write(raw, events)
        with open(raw, 'a') as stream:
            stream.write('{"type": "assistant", "message": {"id": "partial')
        reason = self.submit(raw)
        self.assertIn(str(self.segments[5].resolve()), reason)
        self.assertIn(str(self.index.resolve()), reason)

    def test_stop_after_an_accepted_structured_output_skips_the_replay(self):
        raw = self.transcript(omitted=[*self.segments[5:], self.index])
        submission = [
            {'type': 'assistant', 'message': {'id': 'final-turn', 'content': [
                {'type': 'tool_use', 'id': 'final-output', 'name': 'StructuredOutput',
                 'input': {'summary': 'done', 'findings': []}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'final-output',
                 'content': 'Structured output provided successfully'}]}}]
        self.write(raw, self.events(raw) + submission)
        with patch.object(self.audit, 'assessed', wraps=self.audit.assessed) as replay:
            self.assertIsNone(self.stop(raw))
            replay.assert_not_called()
        self.assertFalse(self.state.exists())
        submission[1]['message']['content'][0]['is_error'] = True
        self.write(raw, self.events(raw)[:-1] + submission[1:])
        self.assertEqual(self.stop(raw)['decision'], 'block')

    def test_stop_gate_allows_a_complete_review(self):
        self.assertIsNone(self.stop(self.transcript()))
        self.assertIsNone(self.stop(self.transcript(), active=True))
        self.assertFalse(self.state.exists())

    def test_stop_gate_blocks_at_most_three_times_per_attempt(self):
        missing = list(self.segments[2:])
        for blocks in range(1, 4):
            raw = self.transcript(omitted=[*missing, self.index])
            decision = self.stop(raw, active=blocks > 1)
            self.assertEqual(decision['decision'], 'block')
            self.assertEqual(json.loads(self.state.read_text())['blocks'], blocks)
            missing.pop(0)
        raw = self.transcript(omitted=[*missing, self.index])
        self.assertIsNone(self.stop(raw, active=True))
        self.assertEqual(json.loads(self.state.read_text())['blocks'], 3)

    def test_stop_gate_allows_a_continuation_that_made_no_progress(self):
        raw = self.transcript(omitted=[*self.segments[4:], self.index])
        self.assertEqual(self.stop(raw)['decision'], 'block')
        self.assertIsNone(self.stop(raw, active=True))
        self.assertEqual(json.loads(self.state.read_text())['blocks'], 1)
        self.assertEqual(self.stop(raw, active=False)['decision'], 'block')

    def test_stop_gate_allows_gaps_that_more_reads_cannot_repair(self):
        raw = self.transcript(omitted=[self.segments[1]])
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(raw), '--prompt', str(self.fixture.prompt),
             '--root', str(self.fixture.root), '--session', str(self.fixture.session),
             '--out', str(self.state.with_name('audit.json'))],
            env=self.fixture.env, text=True, capture_output=True)
        self.assertEqual(process.returncode, 2)
        self.assertIsNone(self.stop(raw))
        raw = self.transcript(omitted=[*self.segments[3:], self.index])
        events = self.events(raw)
        segment = self.segments[0]
        call = next(block for event in events if event['type'] == 'assistant'
                    for block in event['message']['content']
                    if block['input'].get('file_path') == str(segment))
        call['input']['limit'] = 2
        self.write(raw, events)
        self.assertIsNone(self.stop(raw))
        self.assertFalse(self.state.exists())

    def test_stop_gate_errors_never_block_the_stop(self):
        raw = self.transcript(omitted=[*self.segments[3:], self.index])
        self.assertIsNone(self.stop(raw, payload='{'))
        self.assertIsNone(self.stop(self.directory / 'missing.ndjson'))
        with patch.object(self.audit, 'assess', side_effect=RuntimeError('boom')):
            self.assertIsNone(self.stop(raw))
        self.state.write_text('{')
        self.assertIsNone(self.stop(raw))
        self.state.unlink()
        self.state.mkdir()
        self.assertIsNone(self.stop(raw))

    def test_stop_gate_names_the_required_post_index_source_target(self):
        fixture = SourceFixture(self.directory / 'target', 'current', adapter='claude')
        raw = self.transcript(fixture=fixture)
        target = fixture.target()
        named = f"{target['path']} lines {target['line_start']}-{target['line_end']}"
        decision = self.stop(raw, fixture=fixture)
        self.assertEqual(decision['decision'], 'block')
        self.assertIn(named, decision['reason'])
        self.state.unlink()
        legacy = fixture.session / 'legacy.prompt.md'
        legacy.write_text(''.join(
            line for line in fixture.prompt.read_text().splitlines(keepends=True)
            if not line.startswith('Evidence manifest SHA-256:')))
        decision = self.stop(raw, fixture=fixture, prompt=legacy)
        self.assertEqual(decision['decision'], 'block')
        self.assertIn(named, decision['reason'])

    def test_structured_output_gate_never_sends_back_an_incomplete_proof(self):
        raw = self.transcript(omitted=[*self.segments[3:], self.index])
        incomplete = {'summary': 'INCOMPLETE PROOF: segments 4 onward and the index are unread.',
                      'findings': []}
        with patch.object(self.audit, 'assessed', wraps=self.audit.assessed) as replay:
            self.assertIsNone(self.submit(raw, result=incomplete))
            replay.assert_not_called()
        self.assertFalse(self.state.exists())
        self.assertIn('(1 of 3)', self.submit(raw, result={
            'summary': 'Reviewed. INCOMPLETE PROOF is not claimed.', 'findings': []}))

    def test_structured_output_gate_audits_the_submitted_result(self):
        fixture = SourceFixture(self.directory / 'salvage', 'current', adapter='claude')
        raw, result_path, audit_path = fixture.claude_transcript()
        cited = fixture.context['shards'][0]['ranges'][0]
        submitted = {'summary': 'checked', 'findings': [{
            'severity': 'P2', 'file': cited['path'], 'line_start': cited['line_start'],
            'line_end': cited['line_end'], 'claim': 'claim', 'evidence': 'evidence',
            'suggested_fix': 'fix', 'confidence': 0.5}]}
        result_path.write_text(json.dumps(submitted))
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(raw), '--prompt', str(fixture.prompt),
             '--root', str(fixture.root), '--session', str(fixture.session),
             '--out', str(audit_path)],
            env=fixture.env, text=True, capture_output=True)
        audit = json.loads(audit_path.read_text())
        self.assertEqual((process.returncode, audit['status'], audit.get('citation_reaudit')),
                         (0, 'valid', True))
        self.assertEqual([item['code'] for item in audit['advisories']],
                         ['missing-required-source-read'])
        self.assertIsNone(self.submit(raw, fixture=fixture, result=submitted))
        self.assertFalse(self.state.exists())
        target = fixture.target()
        self.assertIn(f"{target['path']} lines {target['line_start']}-{target['line_end']}",
                      self.submit(raw, fixture=fixture))

    def test_structured_output_gate_sends_back_a_finding_that_cites_unread_evidence(self):
        fixture = SourceFixture(self.directory / 'unread-packet', 'current', adapter='claude')
        packet = fixture.session / fixture.context['shards'][0]['artifact']
        raw, result_path, audit_path = fixture.claude_transcript(omitted_artifacts=(packet.name,))
        cited = fixture.context['shards'][0]['ranges'][0]
        submitted = {'summary': 'checked', 'findings': [{
            'severity': 'P2', 'file': cited['path'], 'line_start': cited['line_start'],
            'line_end': cited['line_end'], 'claim': 'claim', 'evidence': 'evidence',
            'suggested_fix': 'fix', 'confidence': 0.5}]}
        reason = self.submit(raw, fixture=fixture, result=submitted)
        self.assertIsNotNone(reason)
        self.assertIn(str(packet.resolve()), reason)
        self.state.unlink()
        self.write(raw, self.events(raw) + [
            {'type': 'assistant', 'message': {'id': 'late-packet', 'content': [
                {'type': 'tool_use', 'id': 'late-packet-read', 'name': 'Read',
                 'input': {'file_path': str(packet)}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'late-packet-read',
                 'content': packet.read_text()}]}}])
        self.assertIsNone(self.submit(raw, fixture=fixture, result=submitted))
        result_path.write_text(json.dumps(submitted))
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(raw), '--prompt', str(fixture.prompt),
             '--root', str(fixture.root), '--session', str(fixture.session),
             '--out', str(audit_path)],
            env=fixture.env, text=True, capture_output=True)
        self.assertEqual((process.returncode, json.loads(audit_path.read_text())['status']),
                         (0, 'valid'))

    def test_stop_hook_command_line_prints_only_the_decision(self):
        raw = self.transcript(omitted=[*self.segments[3:], self.index])
        command = [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'stop-hook',
                   '--adapter', 'claude', '--raw', str(raw), '--prompt', str(self.fixture.prompt),
                   '--root', str(self.fixture.root), '--session', str(self.fixture.session),
                   '--state', str(self.state)]
        process = subprocess.run(
            command, input=json.dumps({'hook_event_name': 'Stop', 'stop_hook_active': False}),
            env=self.fixture.env, text=True, capture_output=True)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout)['decision'], 'block')


if __name__ == '__main__':
    unittest.main()
