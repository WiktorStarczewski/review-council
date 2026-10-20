"""Offline public-process bounds prove no remote rollback or live qualification."""

import hashlib
import hmac
import json
import os
import signal
import shutil
import subprocess
import sys
import time

import test_cursor_sdk as sdk_cases
import test_cursor_sdk_auth as auth_cases
from test_cursor_sdk import CursorSDKCase, FIXTURES, SELECTION, SCRIPTS
from test_deleted_source_proof import SourceFixture


OVERRIDE = 'synthetic-attempt-override'
CLI_TOKEN = 'synthetic-attempt-cli-token'
ATTEMPT_EXTENSION = r'''
record('owned-child',{pid:process.pid,parent:process.ppid});
Agent.create = async options => {
  record('Agent.create',{...keyShape(options),model:options.model,
    settingSources:options.local.settingSources,retries:options.local.enableAgentRetries,
    customTools:Object.keys(options.local.customTools)});
  auth(options);
  if (spec.attemptBehavior === 'failure') throw new AuthenticationError();
  if (spec.attemptBehavior !== 'retain') throw new Error('invalid synthetic attempt mode');
  setInterval(() => {},1000);
  for (const name of ['SIGINT','SIGTERM']) {
    process.once(name,() => record('sdk.signal',{name}));
  }
  record('acquisition.ready');
  return new Promise(() => {});
};
'''


class CursorSDKAttemptLifetimeTests(CursorSDKCase):
    def fixture(self, operation, behavior='retain'):
        fixture = auth_cases.CursorSDKAuthTests.fixture(self, override=OVERRIDE)
        fixture.directory.chmod(0o700)
        shutil.copytree(SCRIPTS.parent / 'schema', fixture.scripts.parent / 'schema')
        fixture.sdk_files['dist/esm/index.js'] = (auth_cases.AUTH_SDK + ATTEMPT_EXTENSION).encode()
        fixture.write_package('@cursor/sdk', fixture.sdk_files)
        fixture.write_template('package-lock.json', fixture.lock)
        fixture.spec['attemptBehavior'] = behavior
        fixture.spec_path.write_text(json.dumps(fixture.spec))
        fixture.env.update(CURSOR_API_KEY=OVERRIDE, CURSOR_AUTH_TOKEN=CLI_TOKEN,
                           GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@invalid',
                           GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@invalid')
        verified = subprocess.run([sys.executable, str(fixture.verifier), str(fixture.runtime)],
                                 env=fixture.env, capture_output=True, text=True, timeout=25)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(json.loads(verified.stdout)['sdk_version'], '1.0.38')
        catalog = self.node(fixture.driver, 'catalog', environment=fixture.env)
        self.assertEqual(catalog.returncode, 0, catalog.stdout + catalog.stderr)
        fixture.catalog = json.loads(catalog.stdout)
        self.assertEqual(fixture.catalog['sdk_version'], '1.0.38')
        self.assertEqual([row['call'] for row in self.calls(fixture)],
                         ['import', 'owned-child', 'models.list'])
        self.assert_private(fixture, catalog.stdout + catalog.stderr)
        fixture.trace.write_text('')
        fixture.operation = operation
        fixture.output = fixture.directory / 'must-not-qualify.json'
        if operation == 'probe':
            selection = fixture.directory / 'selection.json'
            selection.write_text(json.dumps({'effort': 'xhigh', 'selection': SELECTION}))
            fixture.arguments = ['probe', '--selection', str(selection),
                                 '--output', str(fixture.output)]
        else:
            qualification = self.qualification(fixture)
            identity = {
                'sdk_version': '1.0.38', 'runtime_sha256': fixture.catalog['runtime_sha256'],
                'catalog_sha256': hashlib.sha256(catalog.stdout.encode()).hexdigest(),
                'runtime_path': str(fixture.runtime), 'qualification_path': str(qualification),
                'qualification_sha256': hashlib.sha256(qualification.read_bytes()).hexdigest(),
                'provenance': {'transport': 'Cursor', 'model_lineage': ['Cursor', 'SpaceXAI'],
                               'laboratory': 'xai'},
            }
            source = self.source(fixture, 'review', identity)
            fixture.env['REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION'] = str(qualification)
            fixture.output = source.session / f'r1-{source.seat}.json'
            fixture.arguments = ['seat', '--session', str(source.session), '--round', '1',
                                 '--seat', source.seat, '--prompt', str(source.prompt),
                                 '--root', str(source.root)]
            fixture.frozen = {path: path.read_bytes() for path in
                              (qualification, fixture.runtime / '.qualification-key',
                               source.session / 'roster.json', source.manifest_path, source.prompt)}
        return fixture

    def source(self, fixture, name, identity=None):
        directory = fixture.directory / name
        directory.mkdir(mode=0o700)
        source = SourceFixture(directory, 'current')
        source.env = dict(fixture.env, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1')
        roster = json.loads((source.session / 'roster.json').read_text())
        roster['seats'][0].update(adapter='cursor-sdk', lab='xai', model=SELECTION['id'],
                                  effort='xhigh', model_selection=SELECTION)
        if identity is not None:
            roster['seats'][0]['cursor_sdk'] = identity
        (source.session / 'roster.json').write_text(json.dumps(roster))
        prepared = subprocess.run([
            sys.executable, str(fixture.scripts / 'rev-evidence.py'), 'prepare',
            str(source.session), '1', '--phase', 'discovery', '--full-seat', 'sol'],
            env=source.env, capture_output=True, text=True, timeout=40)
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        source.manifest = json.loads(source.manifest_path.read_text())
        source.seat = 'sol'
        source.context = source.manifest['source_context']['seats']['sol']
        source.prompt = source.session / 'r1-sol.prompt.md'
        assignment = source.manifest['assignments']['sol']
        rendered = subprocess.run([
            str(fixture.scripts / 'rev-prompt.sh'), str(source.session), '1', 'sol',
            assignment['bundle'], 'Offline public process lifetime only',
            '--evidence', str(source.manifest_path)],
            env=source.env, capture_output=True, text=True, timeout=40)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        if identity is not None:
            self.assertEqual(assignment['cursor_sdk'], identity)
            self.assertEqual(assignment['model_selection'], SELECTION)
        return source

    def events(self):
        return [json.loads(line) for line in
                (FIXTURES / 'cursor-sdk-stream.ndjson').read_text().splitlines()]

    def qualification(self, fixture):
        source = self.source(fixture, 'synthetic-proof')
        events, _ = sdk_cases.CursorStreamTests.canonical_events(self, source)
        raw = source.session / 'r1-sol.stream.ndjson'
        result = source.session / 'r1-sol.json'
        audit = source.session / 'r1-sol.read-audit.json'
        raw.write_text(''.join(json.dumps(event) + '\n' for event in events))
        result.write_text('{"summary":"Synthetic fixture checked","findings":[]}\n')
        checked = subprocess.run([
            sys.executable, str(fixture.scripts / 'lib/review-read-audit.py'), 'audit',
            '--adapter', 'cursor-sdk', '--raw', str(raw), '--result', str(result),
            '--prompt', str(source.prompt), '--root', str(source.root),
            '--session', str(source.session), '--out', str(audit)],
            env=source.env, capture_output=True, text=True, timeout=40)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        report = json.loads(audit.read_text())
        self.assertEqual(report['status'], 'valid')
        self.assertFalse(report['narrow'])
        self.assertEqual(report['stream_sha256'], hashlib.sha256(raw.read_bytes()).hexdigest())
        self.assertEqual(report['result_sha256'], hashlib.sha256(result.read_bytes()).hexdigest())
        body = {
            'version': 1, 'kind': 'cursor-sdk-live-qualification', 'synthetic': True,
            'sdk_version': '1.0.38', 'runtime_sha256': fixture.catalog['runtime_sha256'],
            'platform': fixture.platform, 'arch': fixture.arch, 'helper': fixture.helper,
            'selection': SELECTION, 'effort': 'xhigh',
            'raw': str(raw), 'result': str(result), 'audit': str(audit),
            'prompt': str(source.prompt), 'manifest': str(source.manifest_path),
            'binding': {'root': str(source.root), 'session': str(source.session),
                        'prompt': str(source.prompt)},
            'evidence': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (raw, result, audit, source.prompt, source.manifest_path)},
            'provenance': {'transport': 'Cursor', 'model_lineage': ['Cursor', 'SpaceXAI'],
                           'laboratory': 'xai'},
        }
        key = b'\x17' * 32
        key_path = fixture.runtime / '.qualification-key'
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        payload = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        body['signature'] = hmac.new(key, payload, hashlib.sha256).hexdigest()
        path = fixture.directory / 'synthetic-local-only-qualification.json'
        path.write_text(json.dumps(body, ensure_ascii=False, separators=(',', ':')) + '\n')
        path.chmod(0o600)
        return path

    def calls(self, fixture):
        return ([json.loads(line) for line in fixture.trace.read_text().splitlines()]
                if fixture.trace.exists() else [])

    def assert_private(self, fixture, output=''):
        output += fixture.trace.read_text() if fixture.trace.exists() else ''
        for value in (OVERRIDE, CLI_TOKEN, *auth_cases.PRIVATE_VALUES):
            self.assertNotIn(value, output)
        for row in self.calls(fixture):
            if row['call'] == 'import':
                self.assertEqual(row['entry'], str(fixture.runtime / 'launch.mjs'))
                self.assertFalse(row['environmentKeyPresent'])
                self.assertFalse(row['cliTokenPresent'])

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def cleanup(self, process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)

    def interrupt(self, operation):
        for interrupt in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(interrupt=interrupt.name):
                fixture = self.fixture(operation)
                process = subprocess.Popen(['node', str(fixture.driver), *fixture.arguments],
                                           env=fixture.env, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, start_new_session=True)
                try:
                    deadline = time.monotonic() + 20
                    while process.poll() is None and time.monotonic() < deadline:
                        if any(row['call'] == 'acquisition.ready' for row in self.calls(fixture)):
                            break
                        time.sleep(0.01)
                    calls = self.calls(fixture)
                    names = [row['call'] for row in calls]
                    expected = ['import', 'owned-child']
                    if operation == 'probe':
                        expected += ['models.list']
                    self.assertEqual(names, expected + ['Agent.create', 'acquisition.ready'],
                                     'real public admission must reach retained SDK acquisition')
                    owned = calls[1]
                    self.assertEqual(owned['parent'], process.pid)
                    self.assertNotEqual(owned['pid'], process.pid)
                    self.assert_private(fixture)
                    created = next(row for row in calls if row['call'] == 'Agent.create')
                    self.assertEqual(created['model'], SELECTION)
                    self.assertEqual(created['settingSources'], [])
                    self.assertIs(created['retries'], False)
                    self.assertEqual(created['customTools'], ['council_read'])
                    self.assertIsNone(process.poll(), 'the owned attempt must be live before cancellation')

                    deadline = time.monotonic() + 5
                    process.send_signal(interrupt)
                    while time.monotonic() < deadline:
                        if any(row['call'] == 'sdk.signal' for row in self.calls(fixture)):
                            break
                        time.sleep(0.01)
                    observed = [row for row in self.calls(fixture) if row['call'] == 'sdk.signal']
                    self.assertEqual(observed, [{'call': 'sdk.signal', 'name': interrupt.name}],
                                     'outer-only cancellation must first reach its verified SDK child')
                    try:
                        stdout, stderr = process.communicate(timeout=max(0.01, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        self.fail('public ' + operation + ' and its retained SDK child did not stop within '
                                  '5 seconds of ' + interrupt.name)
                    self.assertNotEqual(process.returncode, 0, 'cancelled attempts cannot report success')
                    self.assertEqual(stdout, '', 'cancelled attempts cannot publish model results')
                    while self.alive(owned['pid']) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(self.alive(owned['pid']),
                                     'public completion cannot leave its owned SDK child alive')
                    self.assert_private(fixture, stdout + stderr)
                    self.assertFalse(fixture.output.exists())
                    for path, content in getattr(fixture, 'frozen', {}).items():
                        self.assertEqual(path.read_bytes(), content)
                    if operation == 'probe':
                        self.assertFalse((fixture.runtime / '.qualification-key').exists())
                finally:
                    self.cleanup(process)

    def test_public_probe_forwards_outer_interrupts_and_bounds_its_owned_child(self):
        self.interrupt('probe')

    def test_public_seat_forwards_outer_interrupts_and_bounds_its_owned_child(self):
        self.interrupt('seat')

    def test_public_attempts_preserve_normal_closed_auth_failure_classification(self):
        for operation, code, reason in (('probe', 5, 'qualification_unavailable'),
                                        ('seat', 3, 'sdk_unauthenticated')):
            with self.subTest(operation=operation):
                fixture = self.fixture(operation, 'failure')
                process = self.node(fixture.driver, *fixture.arguments, environment=fixture.env)
                self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                self.assertEqual(process.stdout, '')
                self.assertEqual(process.stderr, reason + '\n')
                calls = self.calls(fixture)
                expected = ['import', 'owned-child']
                if operation == 'probe':
                    expected += ['models.list']
                self.assertEqual([row['call'] for row in calls], expected + ['Agent.create'])
                self.assert_private(fixture, process.stdout + process.stderr)
                self.assertFalse(fixture.output.exists())
                for path, content in getattr(fixture, 'frozen', {}).items():
                    self.assertEqual(path.read_bytes(), content)
