"""Codex port contracts. Isolated homes and CLI doubles; no model/network calls."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / 'plugins/review-council'
SCRIPTS = SHARED / 'scripts'


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, REVIEW_COUNCIL_HOST='codex', HOME=str(self.root),
                        REVIEW_COUNCIL_CONFIG=str(self.root / 'absent'))
        self.roster = module(SCRIPTS / 'lib/roster.py')
        self.roster.CODEX_HOST = True
        self.roster.ORDER = ('codex', 'grok', 'gemini', 'claude')

    def build_roster(self, seats, config=None, probe=None):
        detects = {key: (lambda cfg, key=key: (seats.get(key, []), None))
                   for key in self.roster.ORDER}
        with patch.dict(os.environ, self.env), patch.object(self.roster, 'DETECT', detects), \
             patch.object(self.roster, 'load_config', return_value=(config or {}, None)), \
             patch.object(self.roster, 'probe_seat', side_effect=probe):
            return self.roster.build(probe is not None)[0::2]

    def test_no_implicit_anthropic_seat(self):
        roster, failed = self.build_roster({})
        self.assertTrue(failed)
        self.assertEqual(roster['seats'], [])
        self.assertIn('no usable reviewer', roster['degradation'])

    def test_padding_uses_real_cli_and_honors_exclusions(self):
        seat = self.roster.make_seat('codex-astra', 'codex', 'gpt-6-astra', 'max')
        roster, failed = self.build_roster({'codex': [seat]}, {'claude_seat': False, 'extras': False})
        self.assertFalse(failed)
        self.assertEqual(len(roster['seats']), 3)
        self.assertEqual({s['adapter'] for s in roster['seats']}, {'codex'})
        self.assertEqual(len({s['seat'] for s in roster['seats']}), 3)
        self.assertTrue(roster['degraded'])
        self.assertEqual(roster['padded'], 2)

    def test_failed_probes_are_not_padded_back(self):
        seat = self.roster.make_seat('opus', 'claude', 'opus', 'max')
        roster, failed = self.build_roster({'claude': [seat]}, probe=lambda s: 'probe failed')
        self.assertTrue(failed)
        self.assertEqual(roster['seats'], [])

    def test_repeat_seats_do_not_satisfy_lab_floor(self):
        seat = self.roster.make_seat('codex-astra', 'codex', 'gpt-6-astra', 'max')
        _, failed = self.build_roster({'codex': [seat]}, {'min_labs': 2})
        self.assertTrue(failed)

    def test_integer_major_models(self):
        cache = self.root / 'cache.json'
        cache.write_text(json.dumps({'models': [
            {'slug': name, 'visibility': 'list', 'priority': priority,
             'supported_reasoning_levels': [{'effort': 'max'}]}
            for name, priority in [('gpt-5.6-sol', 1), ('gpt-6-astra', 2)]]}))
        self.assertEqual(self.roster.codex_models(cache), [('gpt-6-astra', 'max')])
        self.assertEqual(self.roster.codex_suffix('gpt-6-astra'), 'astra')

    def test_claude_auth_requires_positive_json(self):
        for rc, payload, expected in [(0, '{"loggedIn":true}', True),
                                      (0, '{"loggedIn":false}', False),
                                      (0, '{}', False), (0, 'bad', False),
                                      (1, '{"loggedIn":true}', False), (None, '', False)]:
            with self.subTest(payload=payload, rc=rc), patch.dict(os.environ, self.env), \
                 patch.object(self.roster.shutil, 'which', return_value='/bin/claude'), \
                 patch.object(self.roster, 'run', return_value=(rc, payload, '')):
                seats, _ = self.roster.detect_claude({})
                self.assertEqual(bool(seats), expected)
                if seats:
                    self.assertEqual(seats[0]['adapter'], 'claude')

    def test_bundle_is_self_contained(self):
        output = module(REPO / 'scripts/build-codex-plugin.py').build(self.root / 'review-council')
        self.assertTrue((output / 'scripts/seats.d/claude.sh').stat().st_mode & 0o111)
        self.assertTrue((output / 'schema/findings.schema.json').exists())
        self.assertTrue((output / 'docs/config.md').exists())
        self.assertFalse((output / '.claude-plugin').exists())
        self.assertFalse((output / 'hooks').exists())
        for name in ('rev', 'stack'):
            text = (output / 'codex-skills' / name / 'SKILL.md').read_text()
            self.assertIn('Codex', text)
            self.assertNotIn('${CLAUDE_PLUGIN_ROOT}', text)
        self.assertIn('export REVIEW_COUNCIL_HOST=codex', (output / 'scripts/roster.sh').read_text())
        # A repeat build replaces stale generated artifacts, not just changed files.
        (output / 'stale').touch()
        module(REPO / 'scripts/build-codex-plugin.py').build(output)
        self.assertFalse((output / 'stale').exists())

    def test_build_refuses_unrelated_directory(self):
        output = self.root / 'review-council'
        output.mkdir()
        with self.assertRaises(ValueError):
            module(REPO / 'scripts/build-codex-plugin.py').build(output)
        self.assertTrue(output.exists())

    def run_stream(self, events):
        output = self.root / 'out.json'
        proc = subprocess.run(['python3', str(SCRIPTS / 'lib/stream-summary.py'), 'claude', str(output)],
                              input='\n'.join(map(json.dumps, events)), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout, json.loads(output.read_text()) if output.exists() else None

    def test_claude_structured_findings_and_tool_evidence(self):
        findings = json.loads((SHARED / 'tests/fixtures/findings-valid.json').read_text())
        log, output = self.run_stream([
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read',
                                                          'input': {'file_path': '/code.py'}}]}},
            {'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': findings}])
        self.assertIn('tool_call Read:', log)
        self.assertEqual(output, findings)

    def test_claude_error_cannot_certify_clean_review(self):
        log, output = self.run_stream([{'type': 'result', 'is_error': True,
                                      'errors': ['usage limit'], 'structured_output': {'findings': []}}])
        self.assertIn('error: ', log)
        self.assertIsNone(output)

    def test_schema_tool_alone_is_not_repository_inspection(self):
        log, _ = self.run_stream([{'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'StructuredOutput', 'input': {}}]}}])
        self.assertNotIn('tool_call ', log)

    def test_claude_adapter_runs_readonly_and_validates(self):
        cli = self.root / 'claude'
        cli.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))
print(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','name':'Read','input':{}}]}}))
print(json.dumps({'type':'result','is_error':False,'subtype':'success',
                  'structured_output':json.loads(Path(os.environ['FINDINGS']).read_text())}))
''')
        cli.chmod(0o755)
        (self.root / 'roster.json').write_text(json.dumps({'seats': [
            self.roster.make_seat('opus', 'claude', 'opus', 'max')]}))
        prompt = self.root / 'prompt.md'
        prompt.write_text('Review the fixture.')
        capture = self.root / 'args.json'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   REV_REPO=str(self.root), CAPTURE=str(capture),
                   FINDINGS=str(SHARED / 'tests/fixtures/findings-valid.json'))
        proc = subprocess.run([str(SCRIPTS / 'rev-seat.sh'), 'opus', str(self.root), '1', str(prompt)],
                              env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.root / 'r1-opus.exit').read_text().strip(), '0')
        args = json.loads(capture.read_text())
        self.assertEqual(args[args.index('--permission-mode') + 1], 'plan')
        self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep,Bash')
        self.assertIn('--strict-mcp-config', args)
        self.assertEqual(args[args.index('--setting-sources') + 1], '')
        schema = json.loads(args[args.index('--json-schema') + 1])
        self.assertNotIn('$schema', schema)
        self.assertIn('findings', schema['properties'])
        settings = json.loads(args[args.index('--settings') + 1])
        command = settings['hooks']['PreToolUse'][0]['hooks'][0]['command']
        for text, rc in [('git diff --stat', 0), ('git reset --hard', 2), ('echo bad > file', 2)]:
            guarded = subprocess.run(command, shell=True, input=json.dumps({
                'tool_name': 'Bash', 'tool_input': {'command': text}}), text=True, capture_output=True)
            self.assertEqual(guarded.returncode, rc, guarded.stderr)

    def test_installer_preserves_marketplace_and_refreshes_version(self):
        installer = module(REPO / 'scripts/install-codex-plugin.py')
        marketplace = self.root / '.agents/plugins/marketplace.json'
        marketplace.parent.mkdir(parents=True)
        other = {'name': 'another', 'source': {'source': 'local', 'path': './plugins/another'}}
        marketplace.write_text(json.dumps({'name': 'mine', 'interface': {'displayName': 'My plugins'},
                                          'plugins': [other]}))
        with patch.object(installer.Path, 'home', return_value=self.root), \
             patch.object(installer.shutil, 'which', return_value='/bin/codex'), \
             patch.object(installer.subprocess, 'run') as run, patch('sys.stdout', new=io.StringIO()):
            installer.install()
            manifest = self.root / 'plugins/review-council/.codex-plugin/plugin.json'
            first = json.loads(manifest.read_text())['version']
            saved = marketplace.read_text()
            installer.install()
            self.assertNotEqual(first, json.loads(manifest.read_text())['version'])
            self.assertEqual(saved, marketplace.read_text())
            run.assert_called_with(['codex', 'plugin', 'add', 'review-council@mine'], check=True)
        data = json.loads(saved)
        self.assertEqual(data['plugins'][0], other)
        self.assertEqual(data['interface'], {'displayName': 'My plugins'})
        self.assertEqual(data['plugins'][1]['policy']['installation'], 'AVAILABLE')


    def test_curl_installer_runs_without_checkout(self):
        cli = self.root / 'codex'
        cli.write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\n")
        cli.chmod(0o755)
        capture = self.root / 'install-commands'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   CAPTURE=str(capture))
        installer = (REPO / 'install-codex.sh').read_text()
        proc = subprocess.run(['bash', '-s', '--', '--ref', 'feat/codex-port'], input=installer,
                              cwd=self.root, env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(capture.read_text().splitlines(), [
            'plugin marketplace add WiktorStarczewski/review-council --ref feat/codex-port',
            'plugin add review-council@review-council'])

    def test_curl_installer_does_not_mask_marketplace_failure(self):
        cli = self.root / 'codex'
        cli.write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$CAPTURE\"\nexit 19\n")
        cli.chmod(0o755)
        capture = self.root / 'install-commands'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   CAPTURE=str(capture))
        proc = subprocess.run(['bash'], input=(REPO / 'install-codex.sh').read_text(),
                              cwd=self.root, env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 19)
        self.assertEqual(len(capture.read_text().splitlines()), 1)


    def run_stack(self, missing_second_receipt=False):
        bundle = module(REPO / 'scripts/build-codex-plugin.py').build(self.root / 'review-council')
        (bundle / 'scripts/roster.sh').write_text('#!/bin/bash\nexit 0\n')
        cli = self.root / 'codex'
        cli.write_text('''#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
prompt = sys.stdin.read()
Path(os.environ['CAPTURE']).write_text(json.dumps({'args':sys.argv[1:], 'prompt':prompt,
    'leg':os.environ.get('REV_STACK_LEG'), 'host':os.environ.get('REVIEW_COUNCIL_HOST')}))
session = Path(re.search(r'use (.+) as the session dir', prompt).group(1))
(session/'findings.md').write_text('ledger')
if not (os.environ.get('MISS_SECOND') == '1' and os.environ.get('PASS') == '2'):
    (session/'report.md').write_text('completed review')
print('completed')
''')
        cli.chmod(0o755)
        config = self.root / 'config.sh'
        config.write_text('legs() { run_leg "' + str(self.root) + '" 1 fixture "Inspect the fixture"; }\n')
        root = self.root / 'sessions'
        capture = self.root / 'capture.json'
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                   ROOT=str(root), LOG=str(self.root / 'stack.log'), CAPTURE=str(capture),
                   REV_STACK_FOREGROUND='1', PASSES='2', POLL='1', MAX_ATTEMPTS='1',
                   MAX_INFRA_RETRIES='0', AUTH_WAIT_TRIES='1', STALL_SECS='30',
                   MISS_SECOND='1' if missing_second_receipt else '0')
        for key in ('NO_PUSH', 'NO_SQUASH', 'REV_ACTIVE', 'REV_STACK_LEG', 'REV_SCRIPTS'):
            env.pop(key, None)
        proc = subprocess.run([str(bundle / 'scripts/stack.sh'), str(config)],
                              env=env, text=True, capture_output=True, timeout=20)
        return proc, json.loads(capture.read_text())

    def test_codex_stack_launch_and_local_defaults(self):
        proc, capture = self.run_stack()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('NO_PUSH=1', proc.stdout)
        self.assertIn('NO_SQUASH=1', proc.stdout)
        self.assertEqual(capture['leg'], '1')
        self.assertEqual(capture['host'], 'codex')
        self.assertIn('workspace-write', capture['args'])
        self.assertIn('sandbox_workspace_write.network_access=true', capture['args'])
        self.assertNotIn('bypassPermissions', capture['args'])
        self.assertIn('Codex review-council skill at', capture['prompt'])
        self.assertIn('Read ', capture['prompt'])

    def test_old_receipt_cannot_complete_new_stack_pass(self):
        proc, _ = self.run_stack(missing_second_receipt=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn('wrote no report.md', proc.stdout)
        self.assertIn('COMPLETE WITH FAILURES', proc.stdout)


if __name__ == '__main__':
    unittest.main()
