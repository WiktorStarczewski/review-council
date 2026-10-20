"""Offline cancellation fixtures establish process bounds, never remote auth rollback."""

import json
import os
import signal
import subprocess
import sys
import time

from test_cursor_sdk import CursorSDKCase
from test_cursor_sdk_runtime import RuntimeFixture


UNCOOPERATIVE_LOGIN_SDK = r'''
import {appendFileSync} from 'node:fs';
const record = (call,detail = {}) => appendFileSync(process.env.SDK_LOGIN_TRACE,
  JSON.stringify({call,...detail})+'\n');
record('import',{entry:process.argv[1],pid:process.pid,parent:process.ppid,
  environmentKeyPresent:'CURSOR_API_KEY' in process.env,
  cliTokenPresent:'CURSOR_AUTH_TOKEN' in process.env});
export class AuthenticationError extends Error {}
export const Cursor = {auth:{async login(options) {
  record('auth.login',{signalPresent:options?.signal instanceof AbortSignal});
  setInterval(() => {},1000);
  options?.signal?.addEventListener('abort',() => record('auth.login.abort-observed'),{once:true});
  return new Promise(() => {});
}}};
'''


class CursorSDKLoginLifetimeTests(CursorSDKCase):
    def fixture(self, name):
        directory = self.directory / name
        directory.mkdir()
        fixture = RuntimeFixture(directory)
        fixture.sdk_files['dist/esm/index.js'] = UNCOOPERATIVE_LOGIN_SDK.encode()
        fixture.write_package('@cursor/sdk', fixture.sdk_files)
        fixture.write_template('package-lock.json', fixture.lock)
        fixture.trace = directory / 'login-trace.ndjson'
        fixture.driver = fixture.scripts / 'lib/cursor-sdk-driver.mjs'
        fixture.env = dict(self.env, REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=str(fixture.runtime),
                           SDK_LOGIN_TRACE=str(fixture.trace),
                           CURSOR_API_KEY='synthetic-lifetime-override',
                           CURSOR_AUTH_TOKEN='synthetic-lifetime-cli-token')
        verified = subprocess.run([sys.executable, str(fixture.verifier), str(fixture.runtime)],
                                  env=fixture.env, capture_output=True, text=True, timeout=25)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(json.loads(verified.stdout)['sdk_version'], '1.0.38')
        return fixture

    def calls(self, fixture):
        return ([json.loads(line) for line in fixture.trace.read_text().splitlines()]
                if fixture.trace.exists() else [])

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

    def test_outer_login_interrupt_bounds_an_uncooperative_verified_sdk_child(self):
        for interrupt in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(interrupt=interrupt.name):
                fixture = self.fixture(interrupt.name)
                process = subprocess.Popen(['node', str(fixture.driver), 'login'], env=fixture.env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, start_new_session=True)
                try:
                    deadline = time.monotonic() + 10
                    while process.poll() is None and time.monotonic() < deadline:
                        if any(call['call'] == 'auth.login' for call in self.calls(fixture)):
                            break
                        time.sleep(0.01)
                    calls = self.calls(fixture)
                    self.assertEqual([call['call'] for call in calls], ['import', 'auth.login'])
                    imported, login = calls
                    self.assertEqual(imported['entry'], str(fixture.runtime / 'launch.mjs'))
                    self.assertEqual(imported['parent'], process.pid)
                    self.assertNotEqual(imported['pid'], process.pid)
                    self.assertFalse(imported['environmentKeyPresent'])
                    self.assertFalse(imported['cliTokenPresent'])
                    self.assertTrue(login['signalPresent'])
                    self.assertIsNone(process.poll(), 'fixture must remain live until interrupted')

                    deadline = time.monotonic() + 5
                    process.send_signal(interrupt)
                    while time.monotonic() < deadline:
                        if any(call['call'] == 'auth.login.abort-observed'
                               for call in self.calls(fixture)):
                            break
                        time.sleep(0.01)
                    self.assertEqual([call['call'] for call in self.calls(fixture)],
                                     ['import', 'auth.login', 'auth.login.abort-observed'],
                                     'the outer launcher must first forward cooperative cancellation')
                    try:
                        stdout, stderr = process.communicate(timeout=max(0.01, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        self.fail('outer login and its verified SDK child did not stop within 5 seconds of '
                                  + interrupt.name)
                    self.assertNotEqual(process.returncode, 0, 'cancelled login must fail closed')
                    self.assertEqual(stdout, '', 'cancelled login cannot publish success')
                    while self.alive(imported['pid']) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(self.alive(imported['pid']),
                                     'outer completion must not leave the verified SDK child running')
                    output = stdout + stderr + fixture.trace.read_text()
                    for private in ('synthetic-lifetime-override', 'synthetic-lifetime-cli-token'):
                        self.assertNotIn(private, output)
                    self.assertFalse((fixture.runtime / '.qualification-key').exists())
                finally:
                    self.cleanup(process)
