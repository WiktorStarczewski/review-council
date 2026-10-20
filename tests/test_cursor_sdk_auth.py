"""Offline public authentication contracts do not perform sign-in or qualify a live seat."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import patch

from test_cursor_sdk import CursorSDKCase, FIXTURES, SELECTION, SCRIPTS, module
from test_cursor_sdk_runtime import RuntimeFixture


PRIVATE_VALUES = ('synthetic-returned-api-key', 'synthetic-environment-key',
                  'synthetic-cli-token', 'synthetic-app-token',
                  'private-account-canary', 'private-backend-canary', 'private-auth-error')

AUTH_SDK = r'''
import {appendFileSync,readFileSync} from 'node:fs';
const spec = JSON.parse(readFileSync(process.env.SDK_AUTH_SPEC,'utf8'));
const record = (call,detail = {}) => appendFileSync(process.env.SDK_AUTH_TRACE,
  JSON.stringify({call,...detail})+'\n');
record('import',{entry:process.argv[1],environmentKeyPresent:'CURSOR_API_KEY' in process.env,
  cliTokenPresent:'CURSOR_AUTH_TOKEN' in process.env});
export class AuthenticationError extends Error { constructor() { super('private-auth-error'); this.status = 401; } }
const auth = options => {
  if (options?.apiKey !== undefined) {
    if (!spec.override || options.apiKey !== spec.override) throw new AuthenticationError();
  } else if (spec.state !== 'usable') throw new AuthenticationError();
};
const keyShape = options => ({apiKeyUndefined:options?.apiKey === undefined,
  explicitMatches:spec.override !== undefined && options?.apiKey === spec.override,
  explicitEmpty:options?.apiKey === ''});
export const Cursor = {
  auth:{
    async login(options) {
      record('auth.login',{defaultStore:options?.store === undefined,
        browserAllowed:options?.openBrowser !== false,
        signalPresent:options?.signal instanceof AbortSignal,
        customBackend:options?.backendUrl !== undefined || options?.websiteUrl !== undefined});
      if (spec.loginWait) return new Promise((resolve,reject) => {
        const timer = setInterval(() => {},1000);
        const abort = () => { clearInterval(timer); record('auth.login.aborted'); reject(new AuthenticationError()); };
        if (options?.signal?.aborted) abort();
        else options?.signal?.addEventListener('abort',abort,{once:true});
      });
      if (spec.loginFailure) throw new AuthenticationError();
      return {apiKey:'synthetic-returned-api-key',email:'private-account-canary',
        backendUrl:'private-backend-canary',apiKeyExpiresAtMs:9999999999999};
    },
    async status(options) {
      record('auth.status',{defaultStore:options?.store === undefined});
      return ['usable','revoked'].includes(spec.state)
        ? {status:'logged-in',email:'private-account-canary',backendUrl:'private-backend-canary',
           apiKeyExpiresAtMs:9999999999999}
        : {status:'logged-out'};
    },
    async logout() { record('auth.logout'); throw new Error('unexpected logout'); },
  },
  models:{async list(options) { record('models.list',keyShape(options)); auth(options); return spec.models; }},
};
export class JsonlLocalAgentStore { constructor(directory) { this.directory = directory; } }
export class Agent {
  static async create(options) {
    record('Agent.create',{...keyShape(options),cwd:options.local.cwd,
      storeDirectory:options.local.store.directory,settingSources:options.local.settingSources,
      retries:options.local.enableAgentRetries,tools:options.tools,
      disallowedTools:options.disallowedTools,mcpServers:options.mcpServers,agents:options.agents,
      customTools:Object.keys(options.local.customTools)});
    auth(options);
    const agentId = 'synthetic-auth-agent', id = 'synthetic-auth-run';
    return {agentId,async send() {
      record('agent.send');
      return {id,agentId,async *stream() {},async wait() {
        record('run.wait');
        return {id,status:'finished',model:options.model,
          result:'{"summary":"Synthetic auth fixture","findings":[]}'};
      },async cancel() { record('run.cancel'); }};
    },close() { record('agent.close'); }};
  }
}
'''


class CursorSDKAuthTests(CursorSDKCase):
    def fixture(self, **changes):
        number = getattr(self, 'fixture_number', 0) + 1
        self.fixture_number = number
        directory = self.directory / ('auth-' + str(number))
        directory.mkdir()
        fixture = RuntimeFixture(directory)
        fixture.sdk_files['dist/esm/index.js'] = AUTH_SDK.encode()
        fixture.write_package('@cursor/sdk', fixture.sdk_files)
        fixture.write_template('package-lock.json', fixture.lock)
        fixture.spec = {
            'state': 'usable',
            'models': json.loads((FIXTURES / 'cursor-sdk-catalog.json').read_text())['models'],
        }
        fixture.spec.update(changes)
        fixture.spec_path = directory / 'synthetic-auth-spec.json'
        fixture.spec_path.write_text(json.dumps(fixture.spec))
        fixture.trace = directory / 'public-api-trace.ndjson'
        fixture.driver = fixture.scripts / 'lib/cursor-sdk-driver.mjs'
        fixture.env = dict(self.env, REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=str(fixture.runtime),
                           SDK_AUTH_SPEC=str(fixture.spec_path), SDK_AUTH_TRACE=str(fixture.trace))
        verified = subprocess.run([sys.executable, str(fixture.verifier), str(fixture.runtime)],
                                  env=fixture.env, capture_output=True, text=True, timeout=25)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(json.loads(verified.stdout)['sdk_version'], '1.0.38')
        return fixture

    def calls(self, fixture):
        return ([json.loads(line) for line in fixture.trace.read_text().splitlines()]
                if fixture.trace.exists() else [])

    def run_driver(self, fixture, operation, *arguments, environment=None):
        return self.node(fixture.driver, operation, *arguments,
                         environment=environment or fixture.env)

    def assert_private(self, fixture, process):
        output = process.stdout + process.stderr + (fixture.trace.read_text() if fixture.trace.exists() else '')
        for value in PRIVATE_VALUES:
            self.assertNotIn(value, output)
        for call in self.calls(fixture):
            if call['call'] == 'import':
                self.assertEqual(call['entry'], str(fixture.runtime / 'launch.mjs'),
                                 'public SDK imports must run through the verified installed launcher')
                self.assertFalse(call['environmentKeyPresent'])
                self.assertFalse(call['cliTokenPresent'])
        self.assertFalse((fixture.runtime / '.qualification-key').exists())

    def test_explicit_login_uses_public_browser_flow_once_without_exposing_its_result(self):
        fixture = self.fixture()
        process = self.run_driver(fixture, 'login')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout), {'version': 1, 'status': 'signed-in'})
        calls = self.calls(fixture)
        self.assertEqual([call['call'] for call in calls], ['import', 'auth.login'])
        self.assertEqual(calls[-1], {'call': 'auth.login', 'defaultStore': True,
                                    'browserAllowed': True, 'signalPresent': True,
                                    'customBackend': False})
        self.assert_private(fixture, process)

    def test_login_failure_is_closed_without_retry_or_automatic_renewal(self):
        fixture = self.fixture(loginFailure=True)
        process = self.run_driver(fixture, 'login')
        self.assertEqual([call['call'] for call in self.calls(fixture)], ['import', 'auth.login'])
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(process.stdout, '')
        self.assertIn('sdk_unauthenticated', process.stderr)
        self.assert_private(fixture, process)

    def test_auth_status_reports_only_sanitized_local_sdk_state(self):
        for state, expected in (('usable', 'sdk-login-present'), ('revoked', 'sdk-login-present'),
                                ('logged-out', 'sdk-login-absent'), ('expired', 'sdk-login-absent'),
                                ('backend-mismatch', 'sdk-login-absent')):
            with self.subTest(state=state):
                fixture = self.fixture(state=state)
                process = self.run_driver(fixture, 'auth-status')
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(json.loads(process.stdout), {'version': 1, 'status': expected})
                self.assertEqual([call['call'] for call in self.calls(fixture)],
                                 ['import', 'auth.status'])
                self.assert_private(fixture, process)

    def test_auth_status_can_report_override_without_login_or_model_discovery(self):
        fixture = self.fixture(state='logged-out')
        environment = dict(fixture.env, CURSOR_API_KEY='synthetic-environment-key')
        process = self.run_driver(fixture, 'auth-status', environment=environment)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout),
                         {'version': 1, 'status': 'environment-override-present'})
        self.assertTrue(all(call['call'] in ('import', 'auth.status') for call in self.calls(fixture)))
        self.assert_private(fixture, process)

    def test_login_and_status_verify_runtime_before_any_public_sdk_import(self):
        for operation in ('login', 'auth-status', 'catalog'):
            with self.subTest(operation=operation):
                fixture = self.fixture()
                installed = fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js'
                installed.write_bytes(installed.read_bytes() + b'\n')
                environment = dict(fixture.env, CURSOR_API_KEY='synthetic-environment-key')
                process = self.run_driver(fixture, operation, environment=environment)
                self.assertEqual(process.returncode, 5, process.stdout + process.stderr)
                self.assertEqual(process.stderr, 'runtime_invalid\n')
                self.assertEqual(process.stdout, '')
                self.assertEqual(self.calls(fixture), [])
                self.assert_private(fixture, process)

    def test_catalog_uses_sdk_stored_login_when_override_is_missing_or_blank(self):
        for override in (None, '   '):
            with self.subTest(override=repr(override)):
                fixture = self.fixture()
                environment = dict(fixture.env)
                if override is not None:
                    environment['CURSOR_API_KEY'] = override
                process = self.run_driver(fixture, 'catalog', environment=environment)
                self.assertEqual(process.returncode, 0,
                                 'a usable SDK login must reach the public catalog: ' + process.stderr)
                self.assertEqual(json.loads(process.stdout)['models'], fixture.spec['models'])
                self.assertEqual([call['call'] for call in self.calls(fixture)], ['import', 'models.list'])
                self.assertEqual(self.calls(fixture)[-1], {'call': 'models.list',
                                 'apiKeyUndefined': True, 'explicitMatches': False, 'explicitEmpty': False})
                self.assert_private(fixture, process)

    def test_explicit_catalog_override_is_private_and_takes_precedence_over_stored_login(self):
        fixture = self.fixture(state='logged-out', override='synthetic-environment-key')
        environment = dict(fixture.env, CURSOR_API_KEY='synthetic-environment-key',
                           CURSOR_AUTH_TOKEN='synthetic-cli-token')
        process = self.run_driver(fixture, 'catalog', environment=environment)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout)['models'], fixture.spec['models'])
        self.assertEqual([call['call'] for call in self.calls(fixture)], ['import', 'models.list'])
        self.assertEqual(self.calls(fixture)[-1], {'call': 'models.list',
                         'apiKeyUndefined': False, 'explicitMatches': True, 'explicitEmpty': False})
        self.assert_private(fixture, process)

    def test_unusable_stored_login_refuses_catalog_without_login_or_agent_run(self):
        for state in ('logged-out', 'expired', 'revoked', 'backend-mismatch'):
            with self.subTest(state=state):
                fixture = self.fixture(state=state)
                process = self.run_driver(fixture, 'catalog')
                self.assertEqual([call['call'] for call in self.calls(fixture)], ['import', 'models.list'],
                                 'the public SDK owns stored-login resolution')
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(process.stdout, '')
                self.assertIn('sdk_unauthenticated', process.stderr)
                self.assertIn('login', process.stderr)
                self.assert_private(fixture, process)

    def test_app_and_cli_credentials_cannot_authenticate_a_logged_out_sdk(self):
        fixture = self.fixture(state='logged-out')
        app = self.directory / '.cursor/auth.json'
        app.parent.mkdir()
        app.write_text('{"accessToken":"synthetic-app-token"}\n')
        before = app.read_bytes()
        environment = dict(fixture.env, CURSOR_AUTH_TOKEN='synthetic-cli-token')
        process = self.run_driver(fixture, 'catalog', environment=environment)
        self.assertEqual([call['call'] for call in self.calls(fixture)], ['import', 'models.list'])
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('sdk_unauthenticated', process.stderr)
        self.assertEqual(process.stdout, '')
        self.assertEqual(app.read_bytes(), before)
        self.assert_private(fixture, process)

    def test_probe_auth_failure_cannot_start_a_model_or_publish_qualification(self):
        fixture = self.fixture(state='logged-out')
        requested = fixture.directory / 'selection.json'
        requested.write_text(json.dumps({'effort': 'xhigh', 'selection': SELECTION}))
        output = fixture.directory / 'must-not-qualify.json'
        process = self.run_driver(fixture, 'probe', '--selection', requested, '--output', output)
        self.assertEqual([call['call'] for call in self.calls(fixture)], ['import', 'models.list'])
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(output.exists())
        self.assertEqual(process.stdout, '')
        self.assert_private(fixture, process)

    def test_stored_login_seat_options_keep_strict_boundaries_and_undefined_api_key(self):
        fixture = self.fixture()
        entry = fixture.directory / 'transport-auth-control.mjs'
        entry.write_text('''
import {appendFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
export async function runDriver(argv) {
  const driver = await import(pathToFileURL(argv[0]));
  const sdk = await import(pathToFileURL(argv[1]));
  const selection = JSON.parse(argv[4]);
  const outcome = await driver.runSdkSession({sdk,selection,cwd:argv[2],
    store:new sdk.JsonlLocalAgentStore(argv[3]),apiKey:undefined,prompt:'Synthetic transport auth only',
    reader:{},disposeReader:async () => appendFileSync(process.env.SDK_AUTH_TRACE,
      JSON.stringify({call:'reader.dispose'})+'\\n'),onRawEvent:async () => {}});
  console.log(JSON.stringify({synthetic:true,exitCode:outcome.exitCode}));
}
''')
        cwd, store = fixture.directory / 'empty-cwd', fixture.directory / 'private-store'
        cwd.mkdir(mode=0o700)
        store.mkdir(mode=0o700)
        process = self.node(fixture.runtime / 'launch.mjs', entry, fixture.driver,
                            fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js',
                            cwd, store, json.dumps(SELECTION), environment=fixture.env)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout), {'synthetic': True, 'exitCode': 0})
        calls = self.calls(fixture)
        self.assertEqual([call['call'] for call in calls],
                         ['import', 'Agent.create', 'agent.send', 'run.wait', 'reader.dispose', 'agent.close'])
        options = calls[1]
        self.assertTrue(options['apiKeyUndefined'])
        self.assertFalse(options['explicitEmpty'])
        self.assertEqual(options['cwd'], str(cwd))
        self.assertEqual(options['storeDirectory'], str(store))
        self.assertEqual(options['settingSources'], [])
        self.assertIs(options['retries'], False)
        self.assertEqual(options['tools'], ['mcp'])
        self.assertEqual(options['mcpServers'], {})
        self.assertEqual(options['agents'], {})
        self.assertEqual(options['customTools'], ['council_read'])
        self.assertEqual(set(options['disallowedTools']),
                         {'task', 'shell', 'read', 'edit', 'delete', 'webSearch', 'webFetch'})
        self.assertEqual(list(cwd.iterdir()), [])
        self.assert_private(fixture, process)

    def test_explicit_login_interrupt_aborts_the_public_flow_without_secret_output(self):
        fixture = self.fixture(loginWait=True)
        process = subprocess.Popen(['node', str(fixture.driver), 'login'], env=fixture.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                if any(call['call'] == 'auth.login' for call in self.calls(fixture)):
                    break
                time.sleep(0.01)
            self.assertEqual([call['call'] for call in self.calls(fixture)], ['import', 'auth.login'],
                             'explicit setup must reach the public cancellable login flow')
            os.killpg(process.pid, signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(stdout, '')
            self.assertEqual([call['call'] for call in self.calls(fixture)],
                             ['import', 'auth.login', 'auth.login.aborted'])
            result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
            self.assert_private(fixture, result)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=5)

    def roster_fixture(self):
        fixture = self.fixture()
        roster = module(fixture.scripts / 'lib/roster.py')
        proof = {'kind': 'cursor-sdk-live-qualification', 'version': 1, 'sdk_version': '1.0.38',
                 'effort': 'xhigh', 'provenance': roster.SDK_PROVENANCE, 'signature': 'a' * 64,
                 'selection': SELECTION, 'runtime_sha256': 'a' * 64}
        receipt = fixture.directory / 'synthetic-nonqualifying-receipt.json'
        receipt.write_text(json.dumps(proof))
        environment = dict(fixture.env, REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION=str(receipt))
        catalog = json.loads((FIXTURES / 'cursor-sdk-catalog.json').read_text())
        catalog_result = (0, json.dumps(catalog), '')
        return fixture, roster, receipt, environment, catalog_result

    def test_roster_admits_matching_qualified_catalog_without_an_environment_key_guard(self):
        fixture, roster, receipt, environment, catalog = self.roster_fixture()
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(roster, 'run', return_value=catalog) as run, \
                patch.object(roster, 'validate_cursor_sdk_qualification') as validate:
            effective, error, cause = roster.prepare_cursor_sdk_config({'cursor_sdk_models': ['latest-grok']})
        self.assertIsNone(error, 'stored-login roster admission cannot require an environment key')
        self.assertIsNone(cause)
        self.assertEqual(effective['cursor_sdk_model_selections'], [SELECTION])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['node', str(fixture.driver), 'catalog'])
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(validate.call_args.args[0]['model_selection'], SELECTION)
        self.assertEqual(roster._RESOLVED['cursor_sdk_identity']['qualification_sha256'],
                         hashlib.sha256(receipt.read_bytes()).hexdigest())
        self.assertEqual(self.calls(fixture), [], 'mocked proof admission supplies no live SDK evidence')

    def test_roster_keeps_qualification_refusals_before_catalog_without_an_environment_key(self):
        for proof in (None, {}, {'qualified': True}):
            with self.subTest(proof=proof):
                fixture, roster, receipt, environment, catalog = self.roster_fixture()
                if proof is None:
                    environment.pop('REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION')
                else:
                    receipt.write_text(json.dumps(proof))
                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(roster, 'run', side_effect=AssertionError('unqualified catalog call')):
                    _, error, cause = roster.prepare_cursor_sdk_config({'cursor_sdk_models': ['latest-grok']})
                self.assertEqual(cause, 'availability')
                self.assertIn('qualification', error)
                self.assertEqual(self.calls(fixture), [])

    def test_roster_retains_full_qualification_validation_after_stored_login_catalog(self):
        fixture, roster, receipt, environment, catalog = self.roster_fixture()
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(roster, 'run', return_value=catalog) as run, \
                patch.object(roster, 'validate_cursor_sdk_qualification',
                             side_effect=ValueError('synthetic invalid evidence')) as validate:
            _, error, cause = roster.prepare_cursor_sdk_config({'cursor_sdk_models': ['latest-grok']})
        self.assertEqual(validate.call_count, 1, 'stored login cannot bypass existing qualification validation')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(cause, 'availability')
        self.assertIn('qualification', error)
        self.assertNotIn('cursor_sdk_identity', roster._RESOLVED)

    def test_disabled_sdk_configuration_performs_no_authentication_or_catalog_discovery(self):
        roster = module(SCRIPTS / 'lib/roster.py')
        for config in ({}, {'cursor_sdk_models': []}):
            with self.subTest(config=config), patch.dict(os.environ, self.env, clear=True), \
                    patch.object(roster, 'run', side_effect=AssertionError('disabled SDK discovery')):
                effective, error, cause = roster.prepare_cursor_sdk_config(config)
                self.assertIsNone(error)
                self.assertIsNone(cause)
                self.assertFalse(effective.get('cursor_sdk_models'))
