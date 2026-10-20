"""Offline status-first SDK streams must earn the existing canonical proof."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys

import test_cursor_sdk as sdk_cases
import test_cursor_sdk_auth as auth_cases
from test_cursor_sdk import CursorSDKCase, FIXTURES, SELECTION, SCRIPTS
from test_deleted_source_proof import SourceFixture


class CurrentSourceFixture(SourceFixture):
    @staticmethod
    def declarations(prefix, count, value):
        return (SourceFixture.declarations(prefix, count, value)
                + f'def {prefix}_oversized():\n'
                + ''.join(f'    value_{index:03d} = "{value}-{index:03d}-{"y" * 96}"\n'
                          for index in range(180))
                + '    return value_179\n')


class CursorSDKStatusStreamTests(CursorSDKCase):
    def events(self):
        return [json.loads(line) for line in
                (FIXTURES / 'cursor-sdk-stream.ndjson').read_text().splitlines()]

    def source(self):
        directory = self.directory / 'canonical'
        directory.mkdir()
        source = CurrentSourceFixture(directory, 'current')
        source.env = dict(self.env, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1')
        roster = json.loads((source.session / 'roster.json').read_text())
        roster['seats'][0].update(adapter='cursor-sdk', lab='xai', model=SELECTION['id'],
                                  effort='xhigh', model_selection=SELECTION)
        (source.session / 'roster.json').write_text(json.dumps(roster))
        prepared = subprocess.run([
            sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare', str(source.session),
            '1', '--phase', 'discovery', '--full-seat', 'sol'], env=source.env,
            capture_output=True, text=True, timeout=40)
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        source.manifest = json.loads(source.manifest_path.read_text())
        source.seat = 'sol'
        source.context = source.manifest['source_context']['seats']['sol']
        source.prompt = source.session / 'r1-sol.prompt.md'
        rendered = subprocess.run([
            str(SCRIPTS / 'rev-prompt.sh'), str(source.session), '1', 'sol',
            source.manifest['assignments']['sol']['bundle'], 'Offline status stream fixture',
            '--evidence', str(source.manifest_path)], env=source.env,
            capture_output=True, text=True, timeout=40)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        self.assertTrue(source.context['required_source_ranges'],
                        'canonical control must exercise real required-source segments')
        self.assertTrue(source.context['source_read_required'])
        self.assertTrue((source.root / source.target()['path']).is_file(),
                        'canonical control requires a current post-index source target')
        return source

    def canonical_events(self, source, legacy=False, status='RUNNING'):
        events, _ = sdk_cases.CursorStreamTests.canonical_events(self, source)
        if not legacy:
            first = events[0]
            events[0] = {'type': 'status', 'status': status,
                         'agent_id': first['agent_id'], 'run_id': first['run_id']}
        for event in events:
            if 'call_id' in event:
                event['call_id'] = 'mcp-call-fixture-0000-0000-0000-' + event['call_id'] + '\nuser_tool-council_read_0'
        return events

    def audit(self, source, events):
        stem = source.session / 'r1-sol'
        raw = stem.with_suffix('.stream.ndjson')
        result = stem.with_suffix('.json')
        report = stem.with_suffix('.read-audit.json')
        raw.write_text(''.join(json.dumps(event) + '\n' for event in events))
        result.write_text('{"summary":"Synthetic fixture checked","findings":[]}\n')
        process = subprocess.run([
            sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
            '--adapter', 'cursor-sdk', '--raw', str(raw), '--result', str(result),
            '--prompt', str(source.prompt), '--root', str(source.root),
            '--session', str(source.session), '--out', str(report)], env=source.env,
            capture_output=True, text=True, timeout=40)
        self.assertTrue(report.is_file(), process.stdout + process.stderr)
        return process, json.loads(report.read_text())

    def assert_full_proof(self, source, events):
        process, report = self.audit(source, events)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr + json.dumps(report))
        self.assertEqual(report['status'], 'valid')
        self.assertFalse(report['narrow'])
        self.assertTrue(report['evidence_scoped'])
        self.assertEqual(report['violations'], [])
        self.assertEqual(report['required_source_ranges_covered'],
                         len(source.context['required_source_ranges']))
        self.assertTrue(report['post_index_source_ranges'])
        self.assertEqual(report['stream_sha256'], hashlib.sha256(
            (source.session / 'r1-sol.stream.ndjson').read_bytes()).hexdigest())
        source.receipt_gate(report)

    def assert_refused(self, source, events):
        process, report = self.audit(source, events)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(report['status'], 'invalid')
        self.assertTrue(report['violations'])

    def test_status_first_without_discovery_earns_full_canonical_read_proof(self):
        source = self.source()
        for status in ('CREATING', 'RUNNING'):
            with self.subTest(status=status):
                events = self.canonical_events(source, status=status)
                self.assertFalse(any(event['type'] == 'system' or event.get('name') == 'GetMcpTools'
                                     for event in events))
                self.assert_full_proof(source, events)

    def test_legacy_system_init_retains_full_canonical_read_proof(self):
        source = self.source()
        self.assert_full_proof(source, self.canonical_events(source, legacy=True))

    def test_status_identity_and_initial_order_are_mandatory(self):
        source = self.source()
        for mutation in ('missing-agent', 'missing-run', 'empty-agent', 'empty-run',
                         'finished-first', 'tool-first', 'changed-tool-run',
                         'changed-status-run', 'changed-terminal-agent'):
            with self.subTest(mutation=mutation):
                events = self.canonical_events(source)
                if mutation in ('missing-agent', 'missing-run'):
                    del events[0]['agent_id' if mutation == 'missing-agent' else 'run_id']
                elif mutation in ('empty-agent', 'empty-run'):
                    events[0]['agent_id' if mutation == 'empty-agent' else 'run_id'] = ''
                elif mutation == 'finished-first':
                    events[0]['status'] = 'FINISHED'
                elif mutation == 'tool-first':
                    events[0], events[1] = events[1], events[0]
                elif mutation == 'changed-tool-run':
                    events[1]['run_id'] = 'different-run'
                elif mutation == 'changed-status-run':
                    events.insert(-1, {'type': 'status', 'status': 'RUNNING',
                                       'agent_id': events[0]['agent_id'], 'run_id': 'different-run'})
                else:
                    events[-1]['agent_id'] = 'different-agent'
                self.assert_refused(source, events)

    def test_status_terminal_requires_finished_exact_frozen_model(self):
        source = self.source()
        for mutation in ('missing-model', 'wrong-model', 'wrong-params', 'wrong-max',
                         'wrong-id', 'cancelled', 'missing-terminal'):
            with self.subTest(mutation=mutation):
                events = self.canonical_events(source)
                terminal = events[-1]
                if mutation == 'missing-model':
                    del terminal['model']
                elif mutation == 'wrong-model':
                    terminal['model']['id'] = 'grok-older'
                elif mutation == 'wrong-params':
                    terminal['model']['params'][0]['value'] = 'high'
                elif mutation == 'wrong-max':
                    terminal['model']['maxMode'] = False
                elif mutation == 'wrong-id':
                    terminal['id'] = 'different-run'
                elif mutation == 'cancelled':
                    terminal['status'] = 'cancelled'
                else:
                    events.pop()
                self.assert_refused(source, events)

    def test_status_reader_identity_bytes_completion_and_order_remain_mandatory(self):
        source = self.source()
        for mutation in ('missing-callback', 'completion-before-callback', 'callback-before-running',
                         'wrong-call', 'wrong-session', 'wrong-input', 'wrong-hash', 'wrong-text',
                         'missing-completion', 'duplicate-completion', 'unexpected-tool'):
            with self.subTest(mutation=mutation):
                events = self.canonical_events(source)
                if mutation == 'missing-callback':
                    del events[2]
                elif mutation == 'completion-before-callback':
                    events[2], events[3] = events[3], events[2]
                elif mutation == 'callback-before-running':
                    events[1], events[2] = events[2], events[1]
                elif mutation == 'wrong-call':
                    events[3]['call_id'] = 'different-call'
                elif mutation == 'wrong-session':
                    events[2]['session_id'] = 'different-agent'
                elif mutation == 'wrong-input':
                    events[2]['input']['path'] = 'unassigned.py'
                elif mutation == 'wrong-hash':
                    events[2]['text_sha256'] = '0' * 64
                elif mutation == 'wrong-text':
                    events[3]['result']['value']['content'][0]['text']['text'] += 'changed\n'
                elif mutation == 'missing-completion':
                    del events[3]
                elif mutation == 'duplicate-completion':
                    events.insert(4, copy.deepcopy(events[3]))
                else:
                    for event in (events[1], events[3]):
                        event['name'] = 'shell'
                self.assert_refused(source, events)

    def public_probe(self):
        fixture = auth_cases.CursorSDKAuthTests.fixture(self)
        fixture.directory.chmod(0o700)
        shutil.copytree(SCRIPTS.parent / 'schema', fixture.scripts.parent / 'schema')
        extension = (FIXTURES / 'cursor-sdk-status-probe.mjs').read_text()
        fixture.sdk_files['dist/esm/index.js'] = (auth_cases.AUTH_SDK + extension).encode()
        fixture.write_package('@cursor/sdk', fixture.sdk_files)
        fixture.write_template('package-lock.json', fixture.lock)
        fixture.env.update(GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@invalid',
                           GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@invalid')
        verified = subprocess.run([sys.executable, str(fixture.verifier), str(fixture.runtime)],
                                 env=fixture.env, capture_output=True, text=True, timeout=25)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(json.loads(verified.stdout)['sdk_version'], '1.0.38')
        catalog = self.node(fixture.driver, 'catalog', environment=fixture.env)
        self.assertEqual(catalog.returncode, 0, catalog.stdout + catalog.stderr)
        self.assertIn(SELECTION['id'], [row['id'] for row in json.loads(catalog.stdout)['models']])
        selection = fixture.directory / 'selection.json'
        selection.write_text(json.dumps({'effort': 'xhigh', 'selection': SELECTION}))
        fixture.output = fixture.directory / 'synthetic-local-only-qualification.json'
        process = subprocess.run([
            shutil.which('node'), str(fixture.driver), 'probe', '--selection', str(selection),
            '--output', str(fixture.output)], env=fixture.env,
            capture_output=True, text=True, timeout=90)
        directories = list(fixture.directory.glob('.cursor-sdk-probe-*'))
        self.assertEqual(len(directories), 1, process.stdout + process.stderr)
        fixture.probe = directories[0]
        fixture.session = fixture.probe / 'session'
        fixture.manifest = json.loads((fixture.session / 'r1-evidence.manifest.json').read_text())
        fixture.context = fixture.manifest['source_context']['seats']['grok']
        fixture.raw = fixture.session / 'r1-grok.stream.ndjson'
        fixture.events = [json.loads(line) for line in fixture.raw.read_text().splitlines()]
        calls = [json.loads(line) for line in fixture.trace.read_text().splitlines()]
        self.assertEqual([call['call'] for call in calls],
                         ['import', 'models.list', 'import', 'models.list', 'Agent.create',
                          'agent.send', 'run.wait', 'agent.close'])
        imports = [call for call in calls if call['call'] == 'import']
        self.assertTrue(all(call['entry'] == str(fixture.runtime / 'launch.mjs')
                            and not call['environmentKeyPresent'] and not call['cliTokenPresent']
                            for call in imports))
        self.assertTrue(all(call['apiKeyUndefined'] for call in calls if call['call'] in
                            ('models.list', 'Agent.create')))
        created = next(call for call in calls if call['call'] == 'Agent.create')
        waited = next(call for call in calls if call['call'] == 'run.wait')
        self.assertEqual(created['model'], SELECTION)
        self.assertEqual(created['settingSources'], [])
        self.assertFalse(created['retries'])
        self.assertEqual(created['tools'], ['mcp'])
        self.assertEqual(created['customTools'], ['council_read'])
        self.assertEqual(created['mcpServers'], {})
        self.assertEqual(created['agents'], {})
        self.assertEqual(created['disallowedTools'],
                         ['task', 'shell', 'read', 'edit', 'delete', 'webSearch', 'webFetch'])
        self.assertEqual(waited['terminal']['status'], 'finished')
        self.assertEqual(waited['terminal']['model'], SELECTION)
        self.assertEqual(created['sourceBefore'], waited['sourceAfter'])
        self.assertEqual(waited['sourceAfter'], hashlib.sha256(
            (fixture.probe / 'source/sample.py').read_bytes()).hexdigest())
        self.assertEqual(json.loads((fixture.session / 'r1-grok.json').read_text()),
                         {'summary': 'Synthetic fixture checked', 'findings': []})
        self.assertEqual(fixture.events[0]['type'], 'status')
        self.assertFalse(any(event['type'] == 'system' or event.get('name') == 'GetMcpTools'
                             for event in fixture.events))
        self.assertEqual(fixture.events[-1]['model'], SELECTION)
        self.assertEqual(fixture.events[-1]['status'], 'finished')
        running = {event['call_id']: event for event in fixture.events
                   if event['type'] == 'tool_call' and event['status'] == 'running'}
        callbacks = {event['call_id']: event for event in fixture.events
                     if event['type'] == 'council_read_result'}
        completed = {event['call_id']: event for event in fixture.events
                     if event['type'] == 'tool_call' and event['status'] == 'completed'}
        self.assertEqual(len(running), len(created['requests']))
        self.assertEqual(set(running), set(callbacks))
        self.assertEqual(set(running), set(completed))
        for call_id, event in running.items():
            self.assertIn('\n', call_id)
            self.assertEqual(event['args']['args'], callbacks[call_id]['input'])
            text = completed[call_id]['result']['value']['content'][0]['text']['text']
            self.assertEqual(callbacks[call_id]['text_sha256'], hashlib.sha256(text.encode()).hexdigest())
        for value in auth_cases.PRIVATE_VALUES:
            self.assertNotIn(value, process.stdout + process.stderr + fixture.trace.read_text())
        return fixture, process

    def test_public_probe_without_init_or_discovery_qualifies_after_real_reader_audit(self):
        fixture, process = self.public_probe()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output['status'], 'qualified')
        self.assertEqual(output['receipt_sha256'], hashlib.sha256(fixture.output.read_bytes()).hexdigest())
        receipt = json.loads(fixture.output.read_text())
        self.assertEqual(receipt['selection'], SELECTION)
        report = json.loads((fixture.session / 'r1-grok.read-audit.json').read_text())
        self.assertEqual(report['status'], 'valid')
        self.assertTrue(report['evidence_scoped'])
        self.assertFalse(report['narrow'])
        self.assertEqual(report['violations'], [])
        self.assertGreaterEqual(report['required_source_ranges_covered'], 1)
        self.assertTrue(report['post_index_source_ranges'])

    def test_public_probe_generator_publishes_nonempty_required_source_segments(self):
        fixture, _ = self.public_probe()
        required = fixture.context['required_source_ranges']
        self.assertTrue(required, 'public probe must exercise its required-source coverage gate')
        self.assertTrue(all(row['segments'] for row in required))
        expected = {str(fixture.session / segment['artifact'])
                    for row in required for segment in row['segments']}
        opened = {event['input']['path'] for event in fixture.events
                  if event['type'] == 'council_read_result' and set(event['input']) == {'path'}}
        self.assertTrue(expected <= opened, 'generated required segments must reach the real reader')
