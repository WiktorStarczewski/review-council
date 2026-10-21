"""Cursor host contracts; package and process fixtures do not prove app discovery."""

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
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


class CursorHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cursor-host-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('REV_', 'REVIEW_COUNCIL_', 'CURSOR_'))}
        self.env.update(HOME=str(self.root), REVIEW_COUNCIL_HOST='cursor',
                        REVIEW_COUNCIL_CONFIG=str(self.root / 'absent'))

    def bundle(self):
        path = REPO / 'scripts/build-cursor-plugin.py'
        self.assertTrue(path.is_file(),
                        'Cursor host requires the self-contained build-cursor-plugin.py entry point')
        builder = module(path)
        self.assertTrue(callable(getattr(builder, 'build', None)),
                        'Cursor package builder must expose build(output: Path)')
        output = self.root / 'bundle/review-council'
        self.assertEqual(builder.build(output), output)
        return output

    def roster(self, directory=SCRIPTS):
        with patch.dict(os.environ, self.env, clear=True):
            return module(directory / 'lib/roster.py')

    def test_cursor_manifest_discovers_both_skills_inside_the_built_package(self):
        output = self.bundle()
        manifest_path = output / '.cursor-plugin/plugin.json'
        self.assertTrue(manifest_path.is_file(), 'Cursor native manifest must be packaged')
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest['name'], 'review-council')
        skill_paths = manifest.get('skills', './skills/')
        if isinstance(skill_paths, str):
            skill_paths = [skill_paths]
        self.assertIsInstance(skill_paths, list)
        discovered = {}
        for value in skill_paths:
            path = (output / value).resolve()
            self.assertTrue(path.is_relative_to(output), 'skill discovery cannot escape the bundle')
            candidates = [path] if path.name == 'SKILL.md' else path.glob('*/SKILL.md')
            for candidate in candidates:
                self.assertTrue(candidate.is_file(), str(candidate))
                header = candidate.read_text().split('---', 2)
                self.assertEqual(len(header), 3, 'discoverable skill requires front matter')
                name = re.search(r'^name:\s*(\S+)\s*$', header[1], re.M)
                self.assertIsNotNone(name, 'discoverable skill requires a name')
                discovered[name.group(1)] = candidate.relative_to(output).as_posix()
        self.assertEqual(discovered, {
            'rev': 'cursor-skills/rev/SKILL.md',
            'stack': 'cursor-skills/stack/SKILL.md',
        })

    def test_bundle_contains_runtime_schema_and_executable_modes_without_host_hooks(self):
        output = self.bundle()
        for relative in ('scripts/roster.sh', 'scripts/stack.sh', 'scripts/rev-seat.sh',
                         'scripts/lib/review-read-audit.py', 'tests/run-tests.sh'):
            with self.subTest(path=relative):
                built = output / relative
                self.assertTrue(built.is_file(), relative)
                self.assertEqual(stat.S_IMODE(built.stat().st_mode) & 0o111,
                                 stat.S_IMODE((SHARED / relative).stat().st_mode) & 0o111)
                self.assertTrue(os.access(built, os.X_OK), relative)
        for relative in ('schema/findings.schema.json', 'docs/config.md',
                         'scripts/lib/cursor-sdk-driver.mjs',
                         'scripts/lib/cursor-sdk-reader.mjs',
                         'scripts/lib/cursor-read-helper.py', 'LICENSE'):
            self.assertTrue((output / relative).is_file(), relative)
        for relative in ('.claude-plugin', '.codex-plugin', 'hooks'):
            self.assertFalse((output / relative).exists(), relative)

    def test_repeat_build_replaces_stale_files_and_refuses_unrelated_output(self):
        output = self.bundle()
        stale = output / 'stale.txt'
        stale.write_text('obsolete\n')
        builder = module(REPO / 'scripts/build-cursor-plugin.py')
        builder.build(output)
        self.assertFalse(stale.exists(), 'rebuilding must replace the complete generated package')
        unrelated = self.root / 'unrelated/review-council'
        unrelated.mkdir(parents=True)
        sentinel = unrelated / 'keep.txt'
        sentinel.write_text('keep\n')
        with self.assertRaises(ValueError):
            builder.build(unrelated)
        self.assertEqual(sentinel.read_text(), 'keep\n')

    def test_cursor_host_cannot_implicitly_use_native_claude_agent(self):
        roster = self.roster()
        with patch.dict(os.environ, dict(self.env, REVIEW_COUNCIL_CLAUDE_ADAPTER='agent'), clear=True), \
                patch.object(roster.shutil, 'which', return_value=None), \
                patch.object(roster, 'run', side_effect=AssertionError('no provider process expected')):
            adapter = roster.anthropic_adapter({})
        self.assertEqual(adapter, 'claude',
                         'Cursor hosting must use the explicit Claude CLI transport')

    def test_built_roster_selects_cursor_host_even_with_ambient_claude_host(self):
        output = self.bundle()
        capture = self.root / 'host.txt'
        (output / 'scripts/lib/roster.py').write_text(
            'import os\nfrom pathlib import Path\n'
            'Path(os.environ["HOST_CAPTURE"]).write_text(os.environ.get("REVIEW_COUNCIL_HOST", ""))\n')
        environment = dict(self.env, REVIEW_COUNCIL_HOST='claude', HOST_CAPTURE=str(capture))
        process = subprocess.run([str(output / 'scripts/roster.sh'), '--json'],
                                 env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(capture.is_file(), 'built roster must execute its own runtime')
        self.assertEqual(capture.read_text(), 'cursor')

    def test_default_roster_does_not_discover_or_pad_optional_sdk_seats(self):
        roster = self.roster()
        seats = {
            'codex': [roster.make_seat('sol', 'codex', 'gpt-9-sol', 'xhigh'),
                      roster.make_seat('luna', 'codex', 'gpt-9-luna', 'xhigh')],
            'claude': [roster.make_seat('opus', 'claude', 'opus', 'xhigh'),
                       roster.make_seat('sonnet', 'claude', 'sonnet', 'xhigh')],
        }
        calls = []

        def detect(adapter):
            def run(_config):
                calls.append(adapter)
                return seats.get(adapter, []), None
            return run

        detectors = {adapter: detect(adapter) for adapter in roster.DETECT}
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(roster, 'load_config', return_value=({'extras': False}, None)), \
                patch.object(roster, 'DETECT', detectors), \
                patch.object(roster, 'anthropic_adapter', return_value='claude'):
            result, _, strict = roster.build(False)
        self.assertIsNone(strict)
        self.assertEqual([(seat['adapter'], seat['model'], seat['effort'])
                          for seat in result['seats']],
                         [('codex', 'gpt-9-sol', 'xhigh'), ('codex', 'gpt-9-luna', 'xhigh'),
                          ('claude', 'opus', 'xhigh'), ('claude', 'sonnet', 'xhigh')])
        self.assertNotIn('cursor-sdk', calls, 'optional SDK discovery must require explicit opt-in')
        self.assertNotIn('grok', calls, 'retired standalone Grok transport must remain retired')

    def test_cursor_stack_routes_the_leg_to_its_packaged_rev_skill(self):
        output = self.bundle()
        (output / 'scripts/roster.sh').write_text('#!/bin/bash\nexit 0\n')
        bindir = self.root / 'bin'
        bindir.mkdir()
        capture = self.root / 'stack-call.json'
        shim = '''#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
text = " ".join(sys.argv[1:]) + "\\n" + sys.stdin.read()
Path(os.environ['STACK_CAPTURE']).write_text(json.dumps({
    'host': os.environ.get('REVIEW_COUNCIL_HOST'), 'leg': os.environ.get('REV_STACK_LEG'),
    'prompt': text, 'args': sys.argv[1:]}))
match = re.search(r'use (.+?) as the session dir', text)
if match is None:
    raise SystemExit(9)
session = Path(match.group(1))
(session / 'findings.md').write_text('checked fixture\\n')
(session / 'stack-report.md').write_text('completed fixture\\n')
(session / 'state.json').write_text(json.dumps({'phase': 'stack-ready'}))
'''
        for executable in ('agent', 'cursor-agent'):
            path = bindir / executable
            path.write_text(shim)
            path.chmod(0o755)
        for executable in ('claude', 'codex'):
            path = bindir / executable
            path.write_text('#!/bin/sh\nexit 91\n')
            path.chmod(0o755)
        config = self.root / 'stack.sh'
        config.write_text('legs() { run_leg "' + str(self.root) + '" 1 fixture "Inspect fixture"; }\n')
        environment = dict(self.env, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                           ROOT=str(self.root / 'sessions'), LOG=str(self.root / 'stack.log'),
                           STACK_CAPTURE=str(capture), REV_STACK_FOREGROUND='1',
                           PASSES='1', POLL='1', MAX_ATTEMPTS='1', MAX_INFRA_RETRIES='0',
                           AUTH_WAIT_TRIES='1', STALL_SECS='30')
        process = subprocess.run([str(output / 'scripts/stack.sh'), str(config)],
                                 env=environment, capture_output=True, text=True, timeout=25)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(capture.is_file(), 'Cursor stack must launch the Cursor host process')
        call = json.loads(capture.read_text())
        self.assertEqual((call['host'], call['leg']), ('cursor', '1'))
        self.assertIn(str(output / 'cursor-skills/rev/SKILL.md'), call['prompt'])
        self.assertIn('NO_PUSH=1', process.stdout)
        self.assertIn('NO_SQUASH=1', process.stdout)


if __name__ == '__main__':
    unittest.main()
