"""Optional SDK contracts using synthetic catalogs/streams, never live qualification."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_deleted_source_proof import SourceFixture


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / 'plugins/review-council/scripts'
FIXTURES = REPO / 'plugins/review-council/tests/fixtures'
DRIVER = SCRIPTS / 'lib/cursor-sdk-driver.mjs'
HELPER = SCRIPTS / 'lib/cursor-read-helper.py'
READER = SCRIPTS / 'lib/cursor-sdk-reader.mjs'
SELECTION = {'id': 'grok-9.10', 'params': [{'id': 'reasoning', 'value': 'xhigh'}],
             'maxMode': True}


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CursorSDKCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cursor-sdk-contract-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('REV_', 'REVIEW_COUNCIL_', 'CURSOR_'))}
        self.env.update(HOME=str(self.directory), REVIEW_COUNCIL_HOST='cursor',
                        REVIEW_COUNCIL_CONFIG=str(self.directory / 'absent'))

    def require_entry(self, path):
        self.assertTrue(path.is_file(), 'missing SDK contract entry point: ' + path.name)

    def node(self, *arguments, environment=None, input_text=None):
        executable = shutil.which('node')
        self.assertIsNotNone(executable, 'CI must supply Node for offline SDK contract fixtures')
        return subprocess.run([executable, *map(str, arguments)], env=environment or self.env,
                              input=input_text, capture_output=True, text=True, timeout=20)


class CursorCatalogTests(CursorSDKCase):
    def resolver(self):
        roster = module(SCRIPTS / 'lib/roster.py')
        resolve = getattr(roster, 'resolve_cursor_sdk_config', None)
        self.assertTrue(callable(resolve),
                        'optional SDK requires the pure exact catalog resolver')
        return resolve

    def catalog(self):
        return json.loads((FIXTURES / 'cursor-sdk-catalog.json').read_text())['models']

    def test_latest_grok_resolves_numeric_generation_and_exact_catalog_parameters(self):
        config = {'cursor_sdk_models': ['latest-grok']}
        original = copy.deepcopy(config)
        with patch('subprocess.Popen', side_effect=AssertionError('pure resolver cannot launch SDK')):
            effective, error, strict = self.resolver()(config, self.catalog())
        self.assertIsNone(error)
        self.assertIsNone(strict)
        self.assertEqual(effective['cursor_sdk_models'], ['grok-9.10'])
        self.assertEqual(effective['cursor_sdk_model_selections'], [SELECTION])
        self.assertEqual(effective['cursor_sdk_effort'], 'xhigh')
        self.assertEqual(config, original, 'resolution must not mutate requested settings')

    def test_exact_sdk_id_preserves_catalog_selection_instead_of_cli_slug(self):
        effective, error, strict = self.resolver()(
            {'cursor_sdk_models': ['grok-9.9'], 'cursor_sdk_effort': 'xhigh'}, self.catalog())
        self.assertIsNone(error)
        self.assertIsNone(strict)
        self.assertEqual(effective['cursor_sdk_models'], ['grok-9.9'])
        self.assertEqual(effective['cursor_sdk_model_selections'], [
            {'id': 'grok-9.9', 'params': [{'id': 'reasoning', 'value': 'xhigh'}]}])
        _, error, strict = self.resolver()(
            {'cursor_sdk_models': ['grok-9.10-xhigh']}, self.catalog())
        self.assertEqual(strict, 'availability')
        self.assertTrue(error)

    def test_newest_without_xhigh_never_falls_back_to_an_older_model(self):
        models = self.catalog()
        models.append({'id': 'grok-10', 'displayName': 'Grok 10', 'parameters': [
            {'id': 'reasoning', 'values': [{'value': 'high'}]}], 'variants': [
                {'displayName': 'High', 'params': [{'id': 'reasoning', 'value': 'high'}]}]})
        effective, error, strict = self.resolver()({'cursor_sdk_models': ['latest-grok']}, models)
        self.assertEqual(strict, 'availability')
        self.assertTrue(error)
        self.assertFalse(effective.get('cursor_sdk_model_selections'))

    def test_catalog_ambiguity_and_unknown_effort_parameter_fail_availability(self):
        duplicate = self.catalog() + [copy.deepcopy(self.catalog()[1])]
        unknown = [{'id': 'grok-10', 'displayName': 'Grok 10', 'parameters': [
            {'id': 'mystery', 'values': [{'value': 'xhigh'}]}], 'variants': [
                {'displayName': 'Extra High', 'params': [{'id': 'mystery', 'value': 'xhigh'}]}]}]
        for models in (duplicate, unknown, []):
            with self.subTest(models=models):
                _, error, strict = self.resolver()({'cursor_sdk_models': ['latest-grok']}, models)
                self.assertEqual(strict, 'availability')
                self.assertTrue(error)

    def test_invalid_settings_refuse_instead_of_seating_auto_or_lower_effort(self):
        for config in ({'cursor_sdk_models': 'latest-grok'},
                       {'cursor_sdk_models': [True]}, {'cursor_sdk_models': ['Auto']},
                       {'cursor_sdk_models': ['latest-grok'], 'cursor_sdk_effort': 'low'}):
            with self.subTest(config=config):
                _, error, strict = self.resolver()(config, self.catalog())
                self.assertEqual(strict, 'config')
                self.assertTrue(error)

    def test_disabled_sdk_does_not_need_a_catalog_or_mutate_default_roster(self):
        config = {'codex_models': ['latest-sol', 'latest-luna'],
                  'claude_models': ['opus', 'sonnet'], 'extras': False}
        with patch('subprocess.Popen', side_effect=AssertionError('disabled SDK cannot be loaded')):
            effective, error, strict = self.resolver()(config, None)
        self.assertEqual(effective, config)
        self.assertIsNone(error)
        self.assertIsNone(strict)

    def test_sdk_seat_has_one_model_laboratory_and_preserves_adapter_identity(self):
        roster = module(SCRIPTS / 'lib/roster.py')
        self.assertIn('cursor-sdk', roster.LABS,
                      'SDK transport must have an explicit model-laboratory identity')
        first = roster.make_seat('grok', 'cursor-sdk', 'grok-9.10', 'xhigh')
        second = roster.make_seat('grok-2', 'cursor-sdk', 'grok-9.10', 'xhigh')
        self.assertEqual((first['adapter'], first['lab'], first['model'], first['effort']),
                         ('cursor-sdk', 'xai', 'grok-9.10', 'xhigh'))
        self.assertEqual({seat['lab'] for seat in (first, second)}, {'xai'},
                         'Cursor transport and the model laboratory cannot count as two labs')
        self.assertNotIn('grok', roster.DETECT, 'retired standalone Grok must stay unavailable')


class CursorReaderTests(CursorSDKCase):
    def fixture(self, mode='current'):
        self.require_entry(HELPER)
        return SourceFixture(self.directory, mode)

    def read(self, fixture, request, deps=None, manifest_hash=None):
        command = [os.sys.executable, str(HELPER), '--root', str(fixture.root),
                   '--session', str(fixture.session), '--prompt', str(fixture.prompt),
                   '--manifest', str(fixture.manifest_path), '--manifest-sha256',
                   manifest_hash or hashlib.sha256(fixture.manifest_path.read_bytes()).hexdigest(),
                   '--seat', fixture.seat]
        if deps is not None:
            command += ['--deps-root', str(deps)]
        return subprocess.run(command, input=json.dumps(request), env=self.env,
                              capture_output=True, text=True, timeout=20)

    def assert_read(self, fixture, request, text, deps=None):
        process = self.read(fixture, request, deps)
        self.assertEqual(process.returncode, 0, process.stderr)
        response = json.loads(process.stdout)
        self.assertEqual(set(response), {'text', 'meta'})
        self.assertEqual(response['text'], text)
        self.assertIsInstance(response['meta'], dict)
        return response

    def assert_refused(self, fixture, request, deps=None, manifest_hash=None):
        process = self.read(fixture, request, deps, manifest_hash)
        self.assertNotEqual(process.returncode, 0, 'unauthorized source must not be returned')
        self.assertFalse(process.stdout.strip(), 'rejected input must not leak source bytes')
        return process

    def test_bounded_snapshot_read_preserves_lf_and_exact_requested_range(self):
        fixture = self.fixture()
        self.assert_read(fixture, {'path': 'zz_current.py', 'offset': 2, 'limit': 2},
                         '    return "new' + 'x' * 400 + '"\n\n')
        self.assert_read(fixture, {'path': 'zz_current.py', 'offset': 329, 'limit': 20},
                         '    return "new' + 'x' * 400 + '"\n\n')

    def test_complete_packet_chunks_segments_and_navigation_keep_unbounded_contract(self):
        fixture = self.fixture('deleted')
        fixture.prompt.write_text(fixture.prompt.read_text() + '\n' + 'Review context.\n' * 300)
        assignment = fixture.manifest['assignments'][fixture.seat]
        chunks = fixture.manifest['patch_sets'][assignment['patch_set']]['chunks']
        names = [row['artifact'] for row in chunks]
        names += [row['artifact'] for row in fixture.context['shards']]
        names += [segment['artifact'] for row in fixture.context['required_source_ranges']
                  for segment in row['segments']]
        paths = [fixture.prompt, fixture.session / 'r1-evidence.md']
        paths += [fixture.session / name for name in names]
        self.assertTrue(any(len(path.read_text().splitlines()) > 240 for path in paths),
                        'positive control must exercise complete-artifact line-cap exemption')
        for path in paths:
            with self.subTest(artifact=path.name):
                response = self.assert_read(fixture, {'path': str(path)}, path.read_text())
                self.assertNotIn('offset', response['meta'].get('input', {}))
                self.assertNotIn('limit', response['meta'].get('input', {}))

    def test_prompt_authorized_complete_document_keeps_byte_ceiling_exemption(self):
        fixture = self.fixture()
        document = self.directory / 'approved-document.txt'
        document.write_text(('approved context ' + 'x' * 70 + '\n') * 500)
        text = fixture.prompt.read_text().replace(
            '## Scope\n', '## Scope\nDocuments to review (read them in full):\n- '
            + str(document) + '\n\n', 1)
        fixture.prompt.write_text(text)
        self.assertGreater(document.stat().st_size, 32768)
        self.assert_read(fixture, {'path': str(document)}, document.read_text())

    def test_historical_packets_deliver_frozen_blob_instead_of_recreated_live_file(self):
        fixture = self.fixture('deleted')
        historical = fixture.root / 'aa_retired.py'
        historical.write_text('mutable replacement must not be substituted\n')
        for row in fixture.context['shards']:
            path = fixture.session / row['artifact']
            self.assert_read(fixture, {'path': str(path)}, path.read_text())

    def test_declared_pinned_dependency_symlink_is_context_without_broad_cache_access(self):
        fixture = self.fixture()
        cache = self.directory / 'crate-cache'
        crate = cache / 'pinned'
        crate.mkdir(parents=True)
        (crate / 'lib.rs').write_text('pinned dependency context\n')
        sibling = cache / 'unlisted'
        sibling.mkdir()
        (sibling / 'lib.rs').write_text('unlisted dependency\n')
        deps = fixture.session / 'deps'
        deps.mkdir(exist_ok=True)
        (deps / 'pinned').symlink_to(crate, target_is_directory=True)
        self.assert_read(fixture, {'path': str(deps / 'pinned/lib.rs'), 'offset': 1, 'limit': 1},
                         'pinned dependency context\n', deps)
        self.assert_refused(fixture, {'path': str(sibling / 'lib.rs'), 'offset': 1, 'limit': 1}, deps)

    def test_additional_repository_context_is_not_limited_to_selected_packets(self):
        fixture = self.fixture()
        self.assert_read(fixture, {'path': 'keep.txt', 'offset': 1, 'limit': 1},
                         'unchanged nonsemantic context\n')

    def test_stale_blob_and_changed_manifest_binding_cannot_return_source(self):
        fixture = self.fixture()
        path = fixture.root / 'zz_current.py'
        path.write_text('changed live bytes\n')
        process = self.read(fixture, {'path': str(path), 'offset': 1, 'limit': 1})
        if process.returncode == 0:
            self.assertEqual(json.loads(process.stdout)['text'], 'def active_000():\n',
                             'a successful read must use frozen snapshot bytes')
        else:
            self.assertFalse(process.stdout.strip(), 'stale source failure cannot leak mutable bytes')
        self.assert_refused(fixture, {'path': 'keep.txt', 'offset': 1, 'limit': 1},
                            manifest_hash='0' * 64)

    def test_strict_wire_bounds_and_closed_request_shape_are_enforced(self):
        fixture = self.fixture()
        valid = {'path': 'keep.txt', 'offset': 1, 'limit': 1}
        self.assert_read(fixture, valid, 'unchanged nonsemantic context\n')
        invalid = [dict(valid, offset=value) for value in (0, -1, True, 1.5, '1', None)]
        invalid += [dict(valid, limit=value) for value in (0, -1, True, 1.5, '1', None, 241)]
        invalid += [{'path': 'keep.txt'}, {'path': 'keep.txt', 'limit': 1},
                    {'path': 'keep.txt', 'offset': 1}, dict(valid, root=str(fixture.root)),
                    dict(valid, manifest=str(fixture.manifest_path)), dict(valid, expected_hash='0' * 64),
                    dict(valid, start=1, end=1), dict(valid, path=True), [], None]
        for request in invalid:
            with self.subTest(request=request):
                self.assert_refused(fixture, request)

    def test_traversal_unlisted_artifacts_symlink_escapes_and_special_files_are_refused(self):
        fixture = self.fixture()
        outside = self.directory / 'outside.txt'
        outside.write_text('private outside sentinel\n')
        (fixture.root / 'escape').symlink_to(outside)
        (fixture.root / 'pipe').mkdir()
        sibling_prompt = fixture.session / 'r1-other.prompt.md'
        sibling_prompt.write_text('sibling private prompt\n')
        candidates = [str(outside), '../outside.txt', 'sub/../keep.txt', 'escape', 'pipe',
                      str(sibling_prompt)]
        if hasattr(os, 'mkfifo'):
            os.mkfifo(fixture.root / 'fifo')
            candidates.append('fifo')
        for path in candidates:
            with self.subTest(path=path):
                process = self.assert_refused(fixture, {'path': path, 'offset': 1, 'limit': 1})
                self.assertNotIn('private outside sentinel', process.stdout + process.stderr)

    def test_source_byte_ceiling_applies_before_returning_a_single_oversized_line(self):
        fixture = self.fixture()
        deps = fixture.session / 'deps'
        deps.mkdir(exist_ok=True)
        path = deps / 'large.txt'
        path.write_text('x' * 32769 + '\n')
        self.assert_refused(fixture, {'path': str(path), 'offset': 1, 'limit': 1}, deps)

    def test_unauthorized_fifo_is_rejected_before_any_source_open(self):
        fixture = self.fixture()
        fifo = self.directory / 'unauthorized-fifo'
        os.mkfifo(fifo)
        self.assert_refused(fixture, {'path': str(fifo), 'offset': 1, 'limit': 1})

    def test_sdk_callback_returns_one_exact_text_block_without_controller_metadata(self):
        self.require_entry(READER)
        fixture = self.fixture()
        options = {'root': str(fixture.root), 'session': str(fixture.session),
                   'prompt': str(fixture.prompt), 'manifest': str(fixture.manifest_path),
                   'manifestSha256': hashlib.sha256(fixture.manifest_path.read_bytes()).hexdigest(),
                   'seat': fixture.seat}
        program = '''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const bridge = await import(pathToFileURL(process.argv[1]));
assert.equal(typeof bridge.createCouncilReader, 'function');
const tool = bridge.createCouncilReader(JSON.parse(process.argv[2]));
assert.equal(typeof tool.execute, 'function', 'reader must implement the public SDKCustomTool contract');
const response = await tool.execute({path:'keep.txt',offset:1,limit:1},
  {toolCallId:'synthetic-reader-call',sessionId:'synthetic-reader-session'});
assert.deepEqual(response.content,[{type:'text',text:'unchanged nonsemantic context\\n'}]);
assert.ok(!('structuredContent' in response), 'identity metadata must remain controller-only');
console.log('synthetic callback fixture only');
'''
        process = self.node('--input-type=module', '-e', program, READER, json.dumps(options))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


class CursorStreamTests(CursorSDKCase):
    def setUp(self):
        super().setUp()
        self.audit_module = module(SCRIPTS / 'lib/review-read-audit.py')
        self.root = self.directory / 'repo'
        (self.root / 'src').mkdir(parents=True)
        (self.root / 'src/sample.ts').write_text('alpha\nbeta\ngamma\ndelta\n')
        self.session = self.directory / 'session'
        self.session.mkdir()
        self.prompt = self.session / 'r1-grok.prompt.md'
        self.prompt.write_text('Review src/sample.ts using bounded source reads.\n')

    def events(self):
        return [json.loads(line) for line in
                (FIXTURES / 'cursor-sdk-stream.ndjson').read_text().splitlines() if line]

    def require_decoder(self):
        calls = self.audit_module.extract_calls('cursor-sdk', self.events()[1])
        self.assertEqual(calls, [('sdk-read-1', 'read_file',
                                 {'path': 'src/sample.ts', 'offset': 2, 'limit': 2})],
                         'SDK custom-reader calls must enter the canonical read auditor')

    def audit(self, events, fixture=None):
        self.require_decoder()
        root, session, prompt = self.root, self.session, self.prompt
        stem = self.session / 'r1-grok'
        if fixture is not None:
            root, session, prompt = fixture.root, fixture.session, fixture.prompt
            stem = fixture.session / f'r{fixture.label}-{fixture.seat}'
        raw = Path(str(stem) + '.stream.ndjson')
        raw.write_text(''.join(json.dumps(event) + '\n' for event in events))
        report = Path(str(stem) + '.read-audit.json')
        result = Path(str(stem) + '.json')
        result.write_text('{"summary":"Synthetic fixture checked","findings":[]}\n')
        process = subprocess.run([
            os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
            '--adapter', 'cursor-sdk', '--raw', str(raw), '--prompt', str(prompt),
            '--root', str(root), '--session', str(session), '--result', str(result),
            '--out', str(report)], env=dict(self.env, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1'),
            capture_output=True, text=True, timeout=25)
        self.assertTrue(report.is_file(),
                        'SDK audit must produce a canonical report: ' + process.stderr)
        return process, json.loads(report.read_text())

    def assert_valid(self, events):
        process, report = self.audit(events)
        self.assertEqual(process.returncode, 0, process.stderr + json.dumps(report))
        self.assertEqual(report['status'], 'valid')
        self.assertEqual(report['tool_calls'], 1)
        self.assertEqual(report['tool_output_bytes'], 11)
        self.assertEqual(report['stream_sha256'], hashlib.sha256(
            (self.session / 'r1-grok.stream.ndjson').read_bytes()).hexdigest())
        return report

    def assert_invalid(self, events):
        process, report = self.audit(events)
        self.assertNotEqual(process.returncode, 0, 'invalid SDK proof cannot receive a valid receipt')
        self.assertEqual(report['status'], 'invalid')
        self.assertTrue(report['violations'], 'transport integrity failures cannot become advisories')
        return report

    def test_completed_custom_reader_delivers_exact_text_and_actual_call_identity(self):
        self.require_decoder()
        event = self.events()[3]
        self.assertEqual(self.audit_module.extract_outputs('cursor-sdk', event),
                         [('sdk-read-1', True, 'beta\ngamma\n', None)])
        report = self.assert_valid(self.events())
        self.assertEqual([(row['path'], row['line_start'], row['line_end'])
                          for row in report['source_ranges']], [('src/sample.ts', 2, 3)])

    def test_parallel_calls_share_implicit_turn_until_a_completed_output_is_seen(self):
        original = self.events()
        second_running, second_callback, second_completed = copy.deepcopy(original[1:4])
        request = {'path': 'src/sample.ts', 'offset': 4, 'limit': 1}
        for event in (second_running, second_completed):
            event['call_id'] = 'sdk-read-2'
            event['args']['args'] = dict(request)
        second_callback.update(call_id='sdk-read-2', input=request,
                               text_sha256=hashlib.sha256(b'delta\n').hexdigest())
        second_completed['result']['value']['content'][0]['text']['text'] = 'delta\n'
        parallel = [original[0], original[1], second_running, original[2], second_callback,
                    original[3], second_completed, original[-1]]
        _, report = self.audit(parallel)
        self.assertEqual(report['tool_turns'], 1,
                         'SDK event-per-read grouping cannot evade canonical aggregate limits')
        sequential = original[:-1] + [second_running, second_callback, second_completed, original[-1]]
        _, report = self.audit(sequential)
        self.assertEqual(report['tool_turns'], 2)

    def test_reader_exact_bytes_do_not_inherit_native_rendering_or_newline_tolerance(self):
        match = self.audit_module.delivered_matches_bytes
        self.assertTrue(match('cursor-sdk', 'read_file', 'beta\ngamma\n', b'beta\ngamma\n', 2))
        for text in ('beta\ngamma', '2\tbeta\n3\tgamma\n', '2→beta\n3→gamma\n',
                     '{"text":"beta\\ngamma\\n"}', 'beta\r\ngamma\r\n'):
            with self.subTest(text=text):
                self.assertFalse(match('cursor-sdk', 'read_file', text, b'beta\ngamma\n', 2),
                                 'SDK callback payloads require exact delivered UTF-8 bytes')

    def test_metadata_discovery_of_only_custom_reader_adds_no_source_credit(self):
        events = self.events()
        discovery = json.loads((FIXTURES / 'cursor-sdk-discovery.json').read_text())
        events[1:1] = discovery['events']
        process, report = self.audit(events)
        self.assertEqual(process.returncode, 0, process.stderr + json.dumps(report))
        self.assertEqual(report['status'], 'valid')
        self.assertEqual(report['opened_source_ranges'], 1)

    def test_native_tools_noncustom_servers_and_unknown_mcp_tools_fail_closed(self):
        self.assert_valid(self.events())
        for key, value in (('name', 'shell'), ('name', 'read'), ('name', 'task'),
                           ('name', 'webSearch'), ('name', 'unknown-tool'),
                           ('providerIdentifier', 'untrusted-server'),
                           ('toolName', 'custom-user-tools-council_read'),
                           ('toolName', 'other_read')):
            with self.subTest(key=key, value=value):
                events = self.events()
                for index in (1, 3):
                    if key == 'name':
                        events[index][key] = value
                    else:
                        events[index]['args'][key] = value
                self.assert_invalid(events)

    def test_metadata_discovery_rejects_unknown_servers_tools_and_source_payloads(self):
        discovery = json.loads((FIXTURES / 'cursor-sdk-discovery.json').read_text())['events']
        for mutation in ('server', 'tool', 'source'):
            with self.subTest(mutation=mutation):
                extra = copy.deepcopy(discovery)
                if mutation == 'server':
                    for event in extra:
                        event['args']['providerIdentifier'] = 'untrusted-server'
                elif mutation == 'tool':
                    extra[-1]['result']['value']['tools'].append({'name': 'shell'})
                else:
                    extra[-1]['result']['value']['content'] = 'unbounded source payload'
                events = self.events()
                events[1:1] = extra
                self.assert_invalid(events)

    def test_callback_only_completion_only_and_unpaired_ids_cannot_prove_delivery(self):
        self.assert_valid(self.events())
        for mutation in ('callback-only', 'no-callback', 'different-id', 'missing-id',
                         'wrong-hash', 'wrong-input', 'missing-context'):
            with self.subTest(mutation=mutation):
                events = self.events()
                if mutation == 'callback-only':
                    del events[3]
                elif mutation == 'no-callback':
                    del events[2]
                elif mutation == 'different-id':
                    events[3]['call_id'] = 'another-call'
                elif mutation == 'missing-id':
                    del events[3]['call_id']
                elif mutation == 'wrong-hash':
                    events[2]['text_sha256'] = '0' * 64
                elif mutation == 'wrong-input':
                    events[2]['input']['offset'] = 1
                else:
                    del events[2]['session_id']
                self.assert_invalid(events)

    def test_truncation_missing_text_error_results_and_extra_result_blocks_are_fatal(self):
        self.assert_valid(self.events())
        for mutation in ('args-truncated', 'result-truncated', 'error', 'isError',
                         'missing-text', 'image', 'extra-text', 'wrong-text', 'changed-args'):
            with self.subTest(mutation=mutation):
                events = self.events()
                done = events[3]
                if mutation.endswith('-truncated'):
                    done['truncated'] = {mutation.split('-')[0]: True}
                elif mutation == 'error':
                    done['status'] = 'error'
                    done['result'] = {'status': 'error', 'error': 'synthetic failure'}
                elif mutation == 'isError':
                    done['result']['value']['isError'] = True
                elif mutation == 'missing-text':
                    done['result']['value']['content'] = []
                elif mutation == 'image':
                    done['result']['value']['content'] = [{'image': {'data': 'AA==', 'mimeType': 'image/png'}}]
                elif mutation == 'extra-text':
                    done['result']['value']['content'].append({'text': {'text': 'extra\n'}})
                elif mutation == 'wrong-text':
                    done['result']['value']['content'][0]['text']['text'] = 'different\n'
                else:
                    done['args']['args']['offset'] = 1
                self.assert_invalid(events)

    def test_duplicate_running_identity_conflicts_and_duplicate_completions_are_fatal(self):
        for mutation in ('running', 'completed', 'callback'):
            with self.subTest(mutation=mutation):
                events = self.events()
                index = {'running': 1, 'callback': 2, 'completed': 3}[mutation]
                duplicate = copy.deepcopy(events[index])
                if mutation == 'running':
                    duplicate['args']['args']['offset'] = 1
                events.insert(index + 1, duplicate)
                self.assert_invalid(events)

    def test_cancelled_error_missing_terminal_and_observed_model_mismatch_are_fatal(self):
        for mutation in ('cancelled', 'error', 'missing-terminal', 'missing-model', 'wrong-model'):
            with self.subTest(mutation=mutation):
                events = self.events()
                if mutation == 'missing-terminal':
                    events.pop()
                elif mutation == 'missing-model':
                    del events[-1]['model']
                elif mutation == 'wrong-model':
                    events[-1]['model']['id'] = 'grok-older'
                else:
                    events[-1]['status'] = mutation
                self.assert_invalid(events)

    def test_summary_extracts_one_schema_valid_terminal_result(self):
        self.require_decoder()
        output = self.session / 'summary.json'
        process = subprocess.run([os.sys.executable, str(SCRIPTS / 'lib/stream-summary.py'),
                                  'cursor-sdk', str(output)], input=''.join(
                                      json.dumps(event) + '\n' for event in self.events()),
                                 env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(output.is_file(), 'SDK terminal result must be extracted')
        self.assertEqual(json.loads(output.read_text()),
                         {'summary': 'Synthetic fixture checked', 'findings': []})

    def test_summary_does_not_extract_results_from_partial_or_ambiguous_text(self):
        self.require_decoder()
        for mutation in ('cancelled', 'not-json', 'multiple-objects', 'missing-findings'):
            with self.subTest(mutation=mutation):
                events = self.events()
                if mutation == 'cancelled':
                    events[-1]['status'] = 'cancelled'
                elif mutation == 'not-json':
                    events[-1]['result'] = 'not a findings object'
                elif mutation == 'multiple-objects':
                    events[-1]['result'] += '\n{"summary":"ambiguous","findings":[]}'
                else:
                    events[-1]['result'] = '{"summary":"missing findings"}'
                output = self.session / (mutation + '.json')
                subprocess.run([os.sys.executable, str(SCRIPTS / 'lib/stream-summary.py'),
                                'cursor-sdk', str(output)], input=''.join(
                                    json.dumps(event) + '\n' for event in events),
                               env=self.env, capture_output=True, text=True, timeout=10)
                self.assertFalse(output.exists(), 'invalid terminal findings must not be published')

    def test_absent_sdk_usage_and_cost_remain_unknown(self):
        raw = self.session / 'no-usage.ndjson'
        raw.write_text(''.join(json.dumps(event) + '\n' for event in self.events()))
        usage = module(SCRIPTS / 'lib/usage.py')
        reported, _, _, invalid = usage.read_stream(raw, 'cursor-sdk')
        self.assertIsNone(reported, 'missing SDK usage cannot become known zero tokens/cost')
        self.assertEqual(invalid, [])

    def canonical_fixture(self, mode):
        self.require_decoder()
        directory = self.directory / 'canonical'
        directory.mkdir()
        fixture = SourceFixture(directory, mode)
        roster = json.loads((fixture.session / 'roster.json').read_text())
        for seat in roster['seats']:
            seat.update(adapter='cursor-sdk', lab='xai', model='grok-9.10', effort='xhigh',
                        model_selection=SELECTION)
        (fixture.session / 'roster.json').write_text(json.dumps(roster))
        process = subprocess.run([
            os.sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare',
            str(fixture.session), fixture.label, '--phase', fixture.phase, '--full-seat', 'sol'],
            env=fixture.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0,
                         'canonical evidence compiler must admit SDK assignments: ' + process.stderr)
        fixture.manifest = json.loads(fixture.manifest_path.read_text())
        fixture.seat = fixture.manifest['mechanical_owner']
        fixture.context = fixture.manifest['source_context']['seats'][fixture.seat]
        fixture.prompt = fixture.session / f'r{fixture.label}-{fixture.seat}.prompt.md'
        assignment = fixture.manifest['assignments'][fixture.seat]
        process = subprocess.run([
            str(SCRIPTS / 'rev-prompt.sh'), str(fixture.session), fixture.label, fixture.seat,
            assignment['bundle'], 'SDK canonical proof fixture', '--evidence', str(fixture.manifest_path)],
            env=fixture.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0,
                         'SDK prompt must preserve canonical evidence obligations: ' + process.stderr)
        return fixture

    def canonical_events(self, fixture):
        events = [self.events()[0]]
        artifacts = {}

        def read(request, text):
            call_id = 'proof-' + str(len(artifacts))
            artifacts[request['path']] = call_id
            running, callback, completed = copy.deepcopy(self.events()[1:4])
            for event in (running, completed):
                event['call_id'] = call_id
                event['args']['args'] = dict(request)
            callback.update(call_id=call_id, input=dict(request),
                            text_sha256=hashlib.sha256(text.encode()).hexdigest())
            completed['result']['value']['content'] = [{'text': {'text': text}}]
            events.extend([running, callback, completed])

        def artifact(name):
            path = fixture.session / name
            read({'path': str(path)}, path.read_text())

        assignment = fixture.manifest['assignments'][fixture.seat]
        for chunk in fixture.manifest['patch_sets'][assignment['patch_set']]['chunks']:
            artifact(chunk['artifact'])
        for shard in fixture.context['shards']:
            artifact(shard['artifact'])
        for required in fixture.context['required_source_ranges']:
            for segment in required['segments']:
                artifact(segment['artifact'])
        artifact(f'r{fixture.label}-evidence.md')
        if fixture.context['source_read_required']:
            target = fixture.target()
            read({'path': target['path'], 'offset': target['line_start'],
                  'limit': target['line_end'] - target['line_start'] + 1},
                 fixture.current_bytes(target))
        events.append(self.events()[-1])
        return events, artifacts

    def test_complete_canonical_packets_and_required_segments_earn_real_audit_proof(self):
        fixture = self.canonical_fixture('current')
        events, _ = self.canonical_events(fixture)
        process, report = self.audit(events, fixture)
        self.assertEqual(process.returncode, 0, process.stderr + json.dumps(report))
        self.assertEqual(report['status'], 'valid')
        self.assertEqual(report['packet_shards'], len(fixture.context['shards']))
        self.assertEqual(report['required_source_ranges_covered'],
                         len(fixture.context['required_source_ranges']))
        self.assertTrue(report['assigned_patch_sha256'])
        self.assertTrue(report['post_index_source_ranges'])

    def test_complete_required_proof_cannot_make_sdk_delivery_mismatch_advisory(self):
        fixture = self.canonical_fixture('current')
        events, _ = self.canonical_events(fixture)
        process, report = self.audit(events, fixture)
        self.assertEqual(process.returncode, 0, process.stderr + json.dumps(report))
        running, callback, completed = copy.deepcopy(self.events()[1:4])
        request = {'path': 'keep.txt', 'offset': 1, 'limit': 1}
        for event in (running, completed):
            event['call_id'] = 'extra-context-read'
            event['args']['args'] = dict(request)
        callback.update(call_id='extra-context-read', input=request,
                        text_sha256=hashlib.sha256(b'unchanged nonsemantic context\n').hexdigest())
        completed['result']['value']['content'][0]['text']['text'] = 'mismatched delivery\n'
        events[-1:-1] = [running, callback, completed]
        process, report = self.audit(events, fixture)
        self.assertNotEqual(process.returncode, 0,
                            'completed required proof cannot excuse an unmatched SDK delivery')
        self.assertEqual(report['status'], 'invalid')
        self.assertTrue(report['violations'])

    def test_bounded_or_missing_packets_and_segments_cannot_satisfy_complete_obligations(self):
        fixture = self.canonical_fixture('current')
        original, calls = self.canonical_events(fixture)
        process, report = self.audit(original, fixture)
        self.assertEqual(process.returncode, 0, process.stderr + json.dumps(report))
        paths = [(row['artifact'], 'source-packet') for row in fixture.context['shards']]
        paths += [(segment['artifact'], 'required-source-segment')
                  for row in fixture.context['required_source_ranges'] for segment in row['segments']]
        self.assertTrue(paths)
        for name, kind in paths:
            for mutation in ('missing', 'bounded'):
                with self.subTest(artifact=name, mutation=mutation):
                    events = copy.deepcopy(original)
                    path = str(fixture.session / name)
                    call_id = calls[path]
                    if mutation == 'missing':
                        events = [event for event in events if event.get('call_id') != call_id]
                    else:
                        for event in events:
                            if event.get('call_id') != call_id:
                                continue
                            request = (event['input'] if event['type'] == 'council_read_result'
                                       else event['args']['args'])
                            request.update(offset=1, limit=1)
                    process, report = self.audit(events, fixture)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertEqual(report['status'], 'invalid')
                    codes = {row['code'] for row in report['violations']}
                    expected = 'missing-' + kind if mutation == 'missing' else 'partial-' + kind
                    self.assertIn(expected, codes)

    def test_historical_packet_proof_does_not_create_current_snapshot_citations(self):
        fixture = self.canonical_fixture('deleted')
        events, _ = self.canonical_events(fixture)
        process, report = self.audit(events, fixture)
        self.assertEqual(process.returncode, 0, process.stderr + json.dumps(report))
        self.assertGreater(report['packet_shards'], 0)
        self.assertGreater(report['required_source_ranges_covered'], 0)
        self.assertFalse(any(row['path'] == 'aa_retired.py' for row in report['source_ranges']),
                         'historical context must not earn current snapshot finding credit')

    def test_pinned_dependency_read_remains_context_without_repository_citation_credit(self):
        self.require_decoder()
        dependency = self.directory / 'pinned-dependency'
        dependency.mkdir()
        path = dependency / 'lib.rs'
        path.write_text('dependency context\n')
        self.prompt.write_text('Review bounded dependency context.\n')
        events = self.events()
        request = {'path': str(path), 'offset': 1, 'limit': 1}
        for index in (1, 3):
            events[index]['args']['args'] = dict(request)
        events[2].update(input=dict(request),
                         text_sha256=hashlib.sha256(b'dependency context\n').hexdigest())
        events[3]['result']['value']['content'][0]['text']['text'] = 'dependency context\n'
        raw = self.session / 'r1-grok.stream.ndjson'
        raw.write_text(''.join(json.dumps(event) + '\n' for event in events))
        report_path = self.session / 'dependency.read-audit.json'
        process = subprocess.run([
            os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
            '--adapter', 'cursor-sdk', '--raw', str(raw), '--prompt', str(self.prompt),
            '--root', str(self.root), '--session', str(self.session), '--deps', str(dependency),
            '--out', str(report_path)], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertTrue(report_path.is_file(), process.stderr)
        report = json.loads(report_path.read_text())
        self.assertEqual(process.returncode, 0, process.stderr + json.dumps(report))
        self.assertEqual(report['status'], 'valid')
        self.assertEqual(report['source_ranges'], [])


class CursorDriverTests(CursorSDKCase):
    def test_catalog_missing_runtime_fails_availability_without_installing(self):
        self.require_entry(DRIVER)
        missing = self.directory / 'not-installed'
        environment = dict(self.env, REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=str(missing),
                           CURSOR_API_KEY='synthetic-key-canary')
        process = self.node(DRIVER, 'catalog', environment=environment)
        self.assertEqual(process.returncode, 5, process.stdout + process.stderr)
        self.assertIn('runtime', (process.stdout + process.stderr).lower())
        self.assertNotIn('synthetic-key-canary', process.stdout + process.stderr)
        self.assertFalse(missing.exists(), 'SDK discovery cannot install optional dependencies')

    def poison_runtime(self):
        runtime = self.directory / 'synthetic-runtime'
        package = runtime / 'node_modules/@cursor/sdk'
        package.mkdir(parents=True)
        metadata = {'name': '@cursor/sdk', 'version': '1.0.38', 'type': 'module',
                    'exports': './index.mjs', 'engines': {'node': '>=22.13.0'}}
        (package / 'package.json').write_text(json.dumps(metadata))
        (runtime / 'package.json').write_text(json.dumps({
            'private': True, 'dependencies': {'@cursor/sdk': '1.0.38'}}))
        (runtime / 'package-lock.json').write_text(json.dumps({
            'lockfileVersion': 3, 'packages': {
                '': {'dependencies': {'@cursor/sdk': '1.0.38'}},
                'node_modules/@cursor/sdk': {'version': '1.0.38'}}}))
        marker = self.directory / 'sdk-imported'
        (package / 'index.mjs').write_text(
            'import {writeFileSync} from "node:fs";\n'
            'writeFileSync(process.env.SDK_IMPORT_MARKER,"unexpected import");\n'
            'throw new Error("synthetic SDK import poison");\n')
        return runtime, marker

    def test_cli_auth_token_is_not_an_sdk_key_and_missing_key_precedes_import(self):
        self.require_entry(DRIVER)
        runtime, marker = self.poison_runtime()
        environment = dict(self.env, REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=str(runtime),
                           SDK_IMPORT_MARKER=str(marker), CURSOR_AUTH_TOKEN='cli-token-canary')
        auth = self.directory / '.cursor/auth.json'
        auth.parent.mkdir()
        auth.write_text('{"accessToken":"ambient-auth-canary"}\n')
        before = auth.read_bytes()
        process = self.node(DRIVER, 'catalog', environment=environment)
        output = process.stdout + process.stderr
        self.assertEqual(process.returncode, 5, output)
        self.assertIn('key', output.lower(), 'missing SDK key must have a closed availability reason')
        self.assertFalse(marker.exists(), 'missing explicit SDK key must stop before SDK import')
        self.assertEqual(auth.read_bytes(), before)
        for canary in ('cli-token-canary', 'ambient-auth-canary', 'synthetic SDK import poison'):
            self.assertNotIn(canary, output)

    def test_pure_seat_options_disable_ambient_sources_delegation_and_retries(self):
        self.require_entry(DRIVER)
        workspace = self.directory / 'empty-workspace'
        workspace.mkdir(mode=0o700)
        program = '''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const driver = await import(pathToFileURL(process.argv[1]));
assert.equal(typeof driver.buildSeatOptions, 'function', 'driver must expose pure buildSeatOptions');
const selection = {id:'grok-9.10',params:[{id:'reasoning',value:'xhigh'}],maxMode:true};
const reader = {execute: async () => ({content:[{type:'text',text:'synthetic callback'}]})};
const store = Object.freeze({syntheticPrivateStore:true});
const options = driver.buildSeatOptions({selection,cwd:process.argv[2],store,apiKey:'key-canary',reader});
assert.deepEqual(options.model, selection);
assert.equal(options.apiKey, 'key-canary');
assert.equal(options.local.cwd, process.argv[2]);
assert.equal(options.local.store, store);
assert.deepEqual(options.local.settingSources, []);
assert.equal(options.local.enableAgentRetries, false);
assert.deepEqual(options.mcpServers, {});
assert.deepEqual(options.agents, {});
assert.deepEqual(options.tools, ['mcp']);
for (const tool of ['task','shell','read','edit','delete','webSearch','webFetch']) {
  assert.ok(options.disallowedTools.includes(tool), 'missing explicit tool exclusion: '+tool);
}
assert.ok(!options.disallowedTools.includes('mcp'));
assert.deepEqual(Object.keys(options.local.customTools), ['council_read']);
assert.equal(options.local.customTools.council_read, reader);
for (const key of ['dirs','cloud','agentId','resume','reload']) {
  assert.ok(!(key in options));
  assert.ok(!(key in options.local));
}
console.log('synthetic option construction only');
'''
        process = self.node('--input-type=module', '-e', program, DRIVER, workspace)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(list(workspace.iterdir()), [], 'option construction must not scan/write workspace')

    def test_missing_or_fabricated_qualification_cannot_launch_an_enforced_seat(self):
        self.require_entry(DRIVER)
        runtime, marker = self.poison_runtime()
        session = self.directory / 'session'
        session.mkdir()
        prompt = session / 'r1-grok.prompt.md'
        prompt.write_text('Read only the synthetic public fixture.\n')
        (session / 'roster.json').write_text(json.dumps({'seats': [{
            'seat': 'grok', 'adapter': 'cursor-sdk', 'lab': 'xai', 'model': 'grok-9.10',
            'effort': 'xhigh', 'model_selection': SELECTION}]}))
        qualification = self.directory / 'qualification.json'
        environment = dict(self.env, REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=str(runtime),
                           REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION=str(qualification),
                           SDK_IMPORT_MARKER=str(marker), CURSOR_API_KEY='synthetic-key-canary')
        for proof in (None, {'qualified': True},
                      {'type': 'council_read_result', 'call_id': 'fake', 'input': {'path': 'x'},
                       'text_sha256': hashlib.sha256(b'synthetic').hexdigest()}):
            with self.subTest(proof=proof):
                if proof is not None:
                    qualification.write_text(json.dumps(proof))
                process = self.node(DRIVER, 'seat', '--session', session, '--round', '1',
                                    '--seat', 'grok', '--prompt', prompt, '--root', self.directory,
                                    environment=environment)
                self.assertNotEqual(process.returncode, 0, 'unqualified SDK cannot receive enforced credit')
                self.assertFalse(marker.exists(), 'unqualified seat must stop before SDK import/call')
                self.assertFalse((session / 'r1-grok.read-audit.json').exists())
                self.assertNotIn('synthetic-key-canary', process.stdout + process.stderr)


if __name__ == '__main__':
    unittest.main()
