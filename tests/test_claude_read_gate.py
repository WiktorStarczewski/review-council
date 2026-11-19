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

    def test_stop_gate_names_the_boundary_file_without_source_context(self):
        # The component boundary holds the deleted aa_retired.py and the current zz_current.py.
        fixture = SourceFixture(self.directory / 'boundary', 'mixed', adapter='claude',
                                source_context='0')
        line = next(line for line in fixture.prompt.read_text().splitlines()
                    if line.startswith('Required post-index original-source boundary: '))
        boundary = line.rsplit(': ', 1)[1]
        self.assertTrue((fixture.root / boundary).is_file())
        reason = self.stop(self.transcript(fixture=fixture), fixture=fixture)['reason']
        self.assertIn(f'original source {boundary} with a bounded Read (offset and limit)', reason)
        self.assertNotIn('aa_retired.py', reason)

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


class ClaudeCallGateTests(unittest.TestCase):
    """A required read the audit cannot credit in order is refused when it is made."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='claude-call-gate-')
        cls.directory = Path(cls.temp.name)
        cls.fixture = SourceFixture(
            cls.directory / 'segments', 'deleted', adapter='claude', compact_segment_lines=1500)
        cls.audit = load_read_audit()
        fixture = cls.fixture
        assignment = fixture.manifest['assignments'][fixture.seat]
        cls.chunks = [fixture.session / row['artifact'] for row in
                      fixture.manifest['patch_sets'][assignment['patch_set']]['chunks']]
        cls.packets = [fixture.session / shard['artifact'] for shard in fixture.context['shards']]
        cls.ranges = [(required, segment) for required in fixture.context['required_source_ranges']
                      for segment in required['segments']]
        cls.segments = [fixture.session / segment['artifact'] for _, segment in cls.ranges]
        cls.index = fixture.session / f'r{fixture.label}-evidence.md'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix='claude-call-gate-run-')
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.raw = self.work / 'r1-sol.stream.ndjson'
        self.gate = self.work / 'r1-sol.read-gate'
        self.raw.write_text('')
        self.turn = 0
        self.calls = 0
        self.initialize()

    def initialize(self):
        fixture = self.fixture
        return subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'read-gate-init',
             '--prompt', str(fixture.prompt), '--root', str(fixture.root),
             '--session', str(fixture.session), '--state', str(self.gate)],
            env=fixture.env, text=True, capture_output=True)

    def args(self):
        fixture = self.fixture
        return argparse.Namespace(root=str(fixture.root), session=str(fixture.session),
                                  prompt=str(fixture.prompt), deps=None, raw=str(self.raw),
                                  gate=str(self.gate))

    def append(self, *events):
        with open(self.raw, 'a') as stream:
            for event in events:
                stream.write(json.dumps(event) + '\n')

    def next_turn(self):
        self.turn += 1

    def run_hook(self, function, event):
        stderr = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(event))), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            status = function(self.args())
        return status, stderr.getvalue()

    def call(self, name, data, output, *, pending=False):
        """Make one call as the CLI does: tool_use, PreToolUse, then the result and PostToolUse."""
        self.calls += 1
        call_id = f'toolu-{self.turn}-{self.calls}'
        self.append({'type': 'assistant', 'message': {'id': f'turn-{self.turn}', 'content': [
            {'type': 'tool_use', 'id': call_id, 'name': name, 'input': data}]}})
        if pending:
            return None
        status, stderr = self.run_hook(self.audit.hook, {
            'hook_event_name': 'PreToolUse', 'tool_name': name, 'tool_input': data,
            'tool_use_id': call_id})
        if status == 2:
            message = f'PreToolUse:{name} hook error: [python3 review-read-audit.py hook]: {stderr}'
            self.append({'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': call_id, 'content': message,
                 'is_error': True}]},
                'tool_result_meta': [{'id': call_id, 'non_execution_kind': 'permission-rule'}]})
            return stderr.strip()
        self.assertEqual((status, stderr), (0, ''))
        self.append({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': call_id, 'content': output}]}})
        if name == 'Read':
            lines = len(output.split('\n'))
            response = {'type': 'text', 'file': {
                'filePath': data['file_path'], 'content': output, 'numLines': lines,
                'startLine': data.get('offset', 1), 'totalLines': lines}}
        else:
            response = {'mode': 'content', 'content': output, 'numLines': output.count('\n')}
        self.assertEqual(self.run_hook(self.audit.post_hook, {
            'hook_event_name': 'PostToolUse', 'tool_name': name, 'tool_input': data,
            'tool_use_id': call_id, 'tool_response': response}), (0, ''))
        return None

    def read(self, path, **kwargs):
        return self.call('Read', {'file_path': str(path)}, path.read_text(), **kwargs)

    def grep(self, path):
        return self.call('Grep', {'pattern': 'def', 'path': str(path), 'output_mode': 'content',
                                  'head_limit': 5}, 'def x\n')

    def read_in_turns(self, paths, size):
        for start in range(0, len(paths), size):
            self.next_turn()
            for path in paths[start:start + size]:
                self.assertIsNone(self.read(path))

    def audit_stream(self):
        out = self.work / 'audit.json'
        result = self.work / 'result.json'
        result.write_text(json.dumps({'summary': 'checked', 'findings': []}))
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(self.raw), '--prompt', str(self.fixture.prompt),
             '--root', str(self.fixture.root), '--session', str(self.fixture.session),
             '--result', str(result), '--out', str(out)],
            env=self.fixture.env, text=True, capture_output=True)
        return process.returncode, json.loads(out.read_text())

    def evidence_through_packets(self):
        self.read_in_turns(self.chunks, 2)
        self.read_in_turns(self.packets, 1)

    def stop_reason(self):
        fixture = self.fixture
        args = argparse.Namespace(
            adapter='claude', raw=str(self.raw), prompt=str(fixture.prompt),
            root=str(fixture.root), session=str(fixture.session), seat=None, deps=None,
            state=str(self.work / 'r1-sol.stop-gate'))
        with contextlib.redirect_stderr(io.StringIO()):
            return self.audit.stop_gate_reason(args, {
                'hook_event_name': 'PreToolUse', 'tool_name': 'StructuredOutput',
                'tool_input': {'summary': 'checked', 'findings': []}})

    @staticmethod
    def codes(audit):
        return {row['code'] for row in audit['violations'] + audit['advisories']}

    def assert_valid(self):
        status, audit = self.audit_stream()
        self.assertEqual((status, audit['status'], audit['violations']), (0, 'valid', []))
        return audit

    def read_voided_with(self, path):
        """Read `path` beside the prompt and a packet, a turn over 32 KiB the audit voids."""
        self.next_turn()
        self.assertIsNone(self.read(path))
        self.assertIsNone(self.read(Path(self.fixture.prompt)))
        self.assertIsNone(self.read(self.packets[0]))

    def test_init_records_the_manifest_order_and_no_credit(self):
        self.assertEqual(self.initialize().returncode, 0)
        rows = [json.loads(line) for line in self.gate.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        header = rows[0]
        self.assertEqual(header['chunks'], [str(path.resolve()) for path in self.chunks])
        self.assertEqual(header['packets'], [str(path.resolve()) for path in self.packets])
        self.assertEqual(header['segments'], [str(path.resolve()) for path in self.segments])
        self.assertEqual(header['index'], str(self.index.resolve()))

    def test_every_call_of_an_in_order_review_is_allowed_and_the_audit_is_valid(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments, 4)
        self.read_in_turns([self.index], 1)
        self.next_turn()
        self.assertIsNone(self.grep(self.fixture.root / 'keep.txt'))
        status, audit = self.audit_stream()
        self.assertEqual((status, audit['violations']), (0, []))

    def test_a_required_segment_ahead_of_an_unread_one_is_denied(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments[:2], 2)
        reason = self.read(self.segments[3])
        self.assertIsNotNone(reason)
        self.assertIn('reordered-required-source-segments', reason)
        self.assertIn(f'read {self.segments[2].resolve()} next', reason)
        self.assertEqual(reason.count('\n'), 0)
        # The denied call never ran, so this turn is still a batch of required segments only.
        self.assertIsNone(self.read(self.segments[2]))
        self.assertIsNone(self.read(self.segments[3]))
        self.read_in_turns(self.segments[4:], 4)
        self.read_in_turns([self.index], 1)
        status, audit = self.audit_stream()
        self.assertEqual((status, audit['violations']), (0, []))

    def test_a_patch_chunk_ahead_of_an_unread_one_is_denied(self):
        self.read_in_turns(self.chunks[:1], 1)
        self.next_turn()
        reason = self.read(self.chunks[2])
        self.assertIn('reordered-patch-chunks', reason)
        self.assertIn(f'read {self.chunks[1].resolve()} next', reason)

    def test_a_second_read_is_denied_only_beside_a_full_segment_batch(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments[:2], 2)
        self.next_turn()
        # The audit only advises on a repeated read, so a lone one is allowed.
        self.assertIsNone(self.read(self.segments[0]))
        self.assertIsNone(self.read(self.chunks[0]))
        self.next_turn()
        for path in self.segments[2:5]:
            self.assertIsNone(self.read(path))
        # A repeat is no required segment read, so the audit rejects it beside three of them.
        reason = self.read(self.segments[0])
        self.assertIn('evidence-proof-batch-too-large', reason)
        self.assertIn(f'read {self.segments[5].resolve()} next', reason)
        self.read_in_turns(self.segments[5:], 4)
        self.read_in_turns([self.index], 1)
        self.assertIn('duplicate-required-source-segment', self.codes(self.assert_valid()))

    def test_a_lone_second_read_of_a_credited_segment_or_chunk_is_allowed(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments, 4)
        self.read_in_turns([self.index], 1)
        self.read_in_turns([self.segments[0]], 1)
        self.read_in_turns([self.chunks[-1]], 1)
        self.assertLessEqual({'duplicate-required-source-segment', 'duplicate-patch-chunk'},
                             self.codes(self.assert_valid()))

    def test_the_last_segment_of_a_turn_the_audit_voids_can_be_read_again(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments[:-1], 1)
        self.read_in_turns([self.index], 1)
        self.read_voided_with(self.segments[-1])
        status, audit = self.audit_stream()
        self.assertEqual(status, 2)
        self.assertIn('tool-turn-output-too-large', self.codes(audit))
        reason = self.stop_reason()
        self.assertIn(f'in this order: {self.segments[-1].resolve()}. Read each', reason)
        self.read_in_turns([self.segments[-1]], 1)
        self.assert_valid()

    def test_the_last_patch_chunk_of_a_turn_the_audit_voids_can_be_read_again(self):
        self.read_in_turns(self.chunks[:-1], 2)
        self.next_turn()
        for path in (self.chunks[-1], *self.packets[:2]):
            self.assertIsNone(self.read(path))
        self.read_in_turns(self.packets[2:], 1)
        self.read_in_turns(self.segments, 4)
        self.read_in_turns([self.index], 1)
        status, audit = self.audit_stream()
        self.assertEqual(status, 2)
        self.assertIn('tool-turn-output-too-large', self.codes(audit))
        listed = [self.chunks[-1], *self.packets[:2]]
        reason = self.stop_reason()
        self.assertIn('in this order: ' + '; '.join(str(path.resolve()) for path in listed)
                      + '. Read each', reason)
        self.read_in_turns(listed, 1)
        self.assert_valid()

    def test_a_segment_past_one_whose_credit_the_audit_voids_is_denied(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments[:5], 4)
        self.read_voided_with(self.segments[5])
        self.next_turn()
        reason = self.read(self.segments[6])
        self.assertIn('reordered-required-source-segments', reason or '')
        self.assertIn(f'read {self.segments[5].resolve()} next', reason)
        self.assertIsNone(self.read(self.segments[5]))
        self.assertIsNone(self.read(self.segments[6]))
        self.read_in_turns([self.index], 1)
        self.assert_valid()

    def test_a_read_whose_credit_the_audit_voids_counts_again_in_the_turn_batch(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments[:5], 4)
        self.read_voided_with(self.segments[5])
        self.next_turn()
        self.assertIsNone(self.read(self.segments[5]))
        self.assertIsNone(self.read(self.segments[6]))
        self.assertIn('evidence-proof-batch-too-large', self.read(self.index) or '')
        self.read_in_turns([self.index], 1)
        self.assert_valid()

    def finish_after_chunks(self):
        self.read_in_turns(self.packets, 1)
        self.read_in_turns(self.segments, 4)
        self.read_in_turns([self.index], 1)
        self.assert_valid()

    def test_a_chunk_past_one_whose_credit_the_audit_voids_is_denied(self):
        self.read_in_turns(self.chunks[:2], 2)
        self.next_turn()
        # A packet is no ordered proof read, so this pair is not exempt from the 32 KiB turn limit.
        self.assertIsNone(self.read(self.chunks[2]))
        self.assertIsNone(self.read(self.packets[0]))
        self.next_turn()
        self.assertIn(f'read {self.chunks[2].resolve()} next', self.read(self.chunks[3]) or '')
        self.read_in_turns(self.chunks[2:], 1)
        self.finish_after_chunks()

    def test_the_credit_view_assesses_again_as_the_audit_does(self):
        self.read_in_turns(self.chunks[:2], 2)
        self.next_turn()
        self.assertIsNone(self.read(self.chunks[2]))
        self.assertIsNone(self.read(Path(self.fixture.prompt)))
        # A repeat is no proof read, so this pair is voided too, and then so is the repeat itself.
        self.read_in_turns(self.chunks[2:4], 2)
        self.next_turn()
        self.assertIn(f'read {self.chunks[2].resolve()} next', self.read(self.chunks[4]) or '')
        self.read_in_turns(self.chunks[2:], 1)
        self.finish_after_chunks()

    def test_a_turn_holding_a_read_the_gate_did_not_record_keeps_its_credits(self):
        self.next_turn()
        self.assertIsNone(self.read(self.chunks[0]))
        header = self.gate.read_text()
        # Two chunks pass 32 KiB, an exempt pair only while both count as ordered proof reads.
        self.assertIsNone(self.read(self.chunks[1]))
        self.gate.write_text(header)
        self.read_in_turns(self.chunks[2:], 2)
        self.read_in_turns(self.packets, 1)
        self.read_in_turns(self.segments, 4)
        self.read_in_turns([self.index], 1)
        self.assert_valid()

    def test_a_lone_whole_read_over_32_kib_keeps_its_credit(self):
        index, large = str(self.index.resolve()), 'x' * (40 * 1024)
        read = {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': index}}
        grep = {'type': 'tool_use', 'name': 'Grep', 'input': {'pattern': 'x', 'path': index}}
        self.append(
            {'type': 'assistant', 'message': {'id': 'lone', 'content': [dict(read, id='a')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'a', 'content': large}]}},
            {'type': 'assistant', 'message': {'id': 'pair', 'content': [
                dict(read, id='b'), dict(grep, id='c')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'b', 'content': large},
                {'type': 'tool_result', 'tool_use_id': 'c', 'content': 'x'}]}},
            {'type': 'assistant', 'message': {'id': 'open', 'content': [dict(grep, id='d')]}})
        root, session = self.fixture.root.resolve(), self.fixture.session.resolve()
        _, complete = self.audit.prompt_permissions(self.fixture.prompt, root, session)
        header = json.loads(self.gate.read_text().splitlines()[0])
        credits, voided, _, _ = self.audit.read_gate_credits(
            str(self.raw), header, [(index, 'b'), (index, 'a')], root, session, complete)
        self.assertEqual((credits, voided), ({index: 'a'}, {'b', 'c'}))

    def test_the_open_turn_is_not_judged_before_it_ends(self):
        self.evidence_through_packets()
        self.read_in_turns(self.segments[:5], 4)
        self.read_voided_with(self.segments[5])
        self.assertIsNone(self.read(self.segments[6]))

    def test_no_denial_names_a_source_file_missing_from_the_snapshot_tree(self):
        snapshot = self.fixture.manifest['snapshot_tree']
        absent = {required['path'] for required, _ in self.ranges
                  if required['blob_tree'] != snapshot
                  and not (self.fixture.root / required['path']).exists()}
        self.assertTrue(absent)
        self.evidence_through_packets()
        self.read_in_turns(self.segments[:2], 2)
        self.next_turn()
        reasons = [self.read(self.segments[0]), self.read(self.segments[3])]
        self.next_turn()
        for path in self.segments[2:5]:
            self.assertIsNone(self.read(path))
        reasons += [self.read(self.index), self.grep(self.fixture.root / 'keep.txt'),
                    self.call('Read', {'file_path': str(self.segments[5]), 'limit': 3}, ''),
                    self.stop_reason()]
        self.assertGreaterEqual(len([reason for reason in reasons if reason]), 5)
        for reason in filter(None, reasons):
            for path in absent:
                self.assertNotIn(path, reason)

    def test_a_proof_read_beyond_the_turn_batch_limit_is_denied(self):
        self.next_turn()
        self.assertIsNone(self.read(self.chunks[0]))
        self.assertIsNone(self.read(self.chunks[1]))
        reason = self.read(self.chunks[2])
        self.assertIn('evidence-proof-batch-too-large', reason)
        self.assertIn(f'{self.chunks[2].resolve()} in a later turn', reason)
        self.read_in_turns(self.chunks[2:], 2)
        self.read_in_turns(self.packets, 1)
        self.next_turn()
        for path in self.segments[:4]:
            self.assertIsNone(self.read(path))
        self.assertIn('evidence-proof-batch-too-large', self.read(self.segments[4]))
        reason = self.grep(self.fixture.root / 'keep.txt')
        self.assertIn('evidence-proof-batch-too-large', reason)
        self.assertIn(f'read {self.segments[4].resolve()} next', reason)
        self.next_turn()
        self.assertIsNone(self.read(self.segments[4]))
        self.assertIsNone(self.read(self.segments[5]))
        self.assertIn('evidence-proof-batch-too-large', self.read(self.index))
        self.next_turn()
        self.assertIsNone(self.read(self.segments[6]))
        self.assertIsNone(self.read(self.index))
        self.next_turn()
        self.assertIsNone(self.grep(self.fixture.root / 'keep.txt'))
        status, audit = self.audit_stream()
        self.assertEqual((status, audit['violations']), (0, []))

    def test_a_predecessor_still_in_flight_in_the_same_turn_allows_the_read(self):
        self.evidence_through_packets()
        self.next_turn()
        self.read(self.segments[0], pending=True)
        self.assertIsNone(self.read(self.segments[1]))

    def test_a_repeated_read_in_one_turn_is_not_a_second_proof_read(self):
        self.evidence_through_packets()
        self.next_turn()
        self.read(self.segments[0], pending=True)
        self.assertIsNone(self.read(self.segments[0]))
        self.assertIsNone(self.read(self.index))

    def test_the_gate_fails_open_without_trustworthy_state(self):
        self.evidence_through_packets()
        self.next_turn()
        self.gate.unlink()
        self.assertIsNone(self.read(self.segments[2]))
        self.gate.write_text('{')
        self.assertIsNone(self.read(self.segments[4]))

    def test_a_credit_the_post_hook_missed_is_found_in_the_stream(self):
        self.evidence_through_packets()
        header = self.gate.read_text()
        self.read_in_turns(self.segments[:1], 1)
        self.gate.write_text(header)
        self.next_turn()
        self.assertIsNone(self.read(self.segments[1]))

    def test_credits_without_call_ids_leave_the_turn_batch_ungated(self):
        with open(self.gate, 'a') as stream:
            stream.write(json.dumps({'credit': str(self.chunks[4].resolve())}) + '\n')
        self.next_turn()
        for path in self.chunks[:3]:
            self.assertIsNone(self.read(path))

    def test_the_turn_is_read_back_past_a_large_result(self):
        self.append(
            {'type': 'assistant', 'message': {'id': 'old', 'content': [
                {'type': 'tool_use', 'id': 'a', 'name': 'Read', 'input': {'file_path': 'x'}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'a', 'content': 'old'}]}},
            {'type': 'assistant', 'message': {'id': 'now', 'content': [
                {'type': 'tool_use', 'id': 'b', 'name': 'Read', 'input': {'file_path': 'y'}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'b', 'content': 'z' * (1 << 19)}]}},
            {'type': 'assistant', 'message': {'id': 'now', 'content': [
                {'type': 'tool_use', 'id': 'c', 'name': 'Grep', 'input': {'path': 'y'}}]}})
        turn = self.audit.claude_turn(str(self.raw), 'c')
        self.assertEqual([row[:2] for row in turn], [('b', 'Read')])
        self.assertIsNone(self.audit.claude_turn(str(self.raw), 'missing'))

    def test_a_delivered_output_that_differs_earns_no_credit(self):
        self.evidence_through_packets()
        self.next_turn()
        self.call('Read', {'file_path': str(self.segments[0])}, 'tampered\n')
        self.assertIsNone(self.read(self.segments[1]))
        credits = [json.loads(line) for line in self.gate.read_text().splitlines()[1:]]
        self.assertEqual([row['credit'] for row in credits if 'credit' in row][-1:],
                         [str(self.segments[1].resolve())])
        self.assertNotIn(str(self.segments[0].resolve()), [row.get('credit') for row in credits])


class ClaudeDeniedCallTests(unittest.TestCase):
    """A call the PreToolUse hook denied never ran, so the audit does not count it."""

    HOOK = ('python3 /plugin/scripts/seats.d/../lib/review-read-audit.py hook --root /repo '
            '--session /session --prompt /session/r1-sol.prompt.md')

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='claude-denied-call-')
        cls.fixture = SourceFixture(Path(cls.temp.name) / 'denied', 'deleted', adapter='claude',
                                    compact_segment_lines=1500)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def audit_with(self, *calls):
        fixture = self.fixture
        raw, result, out = fixture.claude_transcript()
        events = [json.loads(line) for line in raw.read_text().splitlines()]
        for number, (data, outcome) in enumerate(calls):
            call_id = f'grep-{number}'
            events.append({'type': 'assistant', 'message': {'id': f'turn-grep-{number}', 'content': [
                {'type': 'tool_use', 'id': call_id, 'name': 'Grep', 'input': data}]}})
            events.append(outcome(call_id))
        raw.write_text(''.join(json.dumps(event) + '\n' for event in events))
        result.write_text(json.dumps({'summary': 'checked', 'findings': []}))
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'claude', '--raw', str(raw), '--prompt', str(fixture.prompt),
             '--root', str(fixture.root), '--session', str(fixture.session), '--out', str(out)],
            env=fixture.env, text=True, capture_output=True)
        audit = json.loads(out.read_text())
        codes = {row['code'] for row in audit['violations'] + audit['advisories']}
        return process.returncode, audit['tool_calls'], codes

    def denial(self, code, *, meta, echo=True, hook=None):
        message = f'PreToolUse:Grep hook error: [{hook or self.HOOK}]: review read blocked: {code}\n'

        def outcome(call_id):
            event = {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': call_id, 'content': message,
                 'is_error': True}]}}
            if meta:  # claude 2.1.328 confirms the hook rejection beside the result
                event['tool_result_meta'] = [{
                    'id': call_id, 'non_execution_kind': 'permission-rule',
                    'permission_decision': {'decision': 'reject', 'source': 'hook'}}]
            elif echo:  # claude 2.1.121 only echoes the error text as the tool use result
                event['tool_use_result'] = 'Error: ' + message
            return event
        return outcome

    @staticmethod
    def executed(content):
        def outcome(call_id):
            return {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': call_id, 'content': content}]},
                'tool_use_result': {'mode': 'content', 'content': content}}
        return outcome

    def bounded_retry(self):
        return ({'pattern': 'def', 'path': str(self.fixture.root / 'keep.txt'),
                 'output_mode': 'content', 'head_limit': 5}, self.executed(''))

    def test_a_denied_call_in_either_cli_format_is_not_counted(self):
        session_search = {'pattern': 'def', 'path': str(self.fixture.session),
                          'output_mode': 'files_with_matches'}
        unbounded = {'pattern': 'def', 'path': str(self.fixture.root / 'keep.txt'),
                     'output_mode': 'content'}
        for meta in (True, False):
            with self.subTest(meta=meta):
                status, calls, codes = self.audit_with(
                    (session_search, self.denial('unnamed-session-artifact', meta=meta)),
                    (unbounded, self.denial('unbounded-search', meta=meta)),
                    self.bounded_retry())
                self.assertEqual((status, codes), (0, set()))
                self.assertEqual(calls, len(self.fixture.claude_transcript()[0].read_text()
                                            .splitlines()) // 2 + 1)

    def test_a_call_that_ran_or_an_unconfirmed_denial_still_counts(self):
        unbounded = {'pattern': 'def', 'path': str(self.fixture.root / 'keep.txt'),
                     'output_mode': 'content'}
        session_search = {'pattern': 'def', 'path': str(self.fixture.session),
                          'output_mode': 'files_with_matches'}
        _, _, codes = self.audit_with((unbounded, self.executed('keep.txt:1:def\n')))
        self.assertIn('unbounded-search', codes)
        denied = self.denial('unnamed-session-artifact', meta=False)

        def succeeded(call_id):
            event = denied(call_id)
            del event['message']['content'][0]['is_error']
            return event

        def shared(call_id):
            event = denied(call_id)
            event['message']['content'].append(dict(event['message']['content'][0],
                                                    tool_use_id='elsewhere'))
            return event
        for outcome in (self.denial('unnamed-session-artifact', meta=False, echo=False),
                        self.denial('unnamed-session-artifact', meta=False,
                                    hook='python3 /elsewhere/other-hook.py'),
                        succeeded, shared):
            status, _, codes = self.audit_with((session_search, outcome))
            self.assertEqual(status, 2)
            self.assertIn('unnamed-session-artifact', codes)


if __name__ == '__main__':
    unittest.main()
