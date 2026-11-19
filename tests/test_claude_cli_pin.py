"""Claude seats run the claude binary preflight recorded, at a version the read gates support."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / 'plugins/review-council/scripts/lib'


def load_roster():
    sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location('roster_cli_pin', LIB / 'roster.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClaudeCliPinTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='claude-cli-pin-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.roster = load_roster()

    def fake(self, directory, version):
        path = self.root / directory / 'claude'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\n'
                        f'[ "$1" = --version ] && {{ printf "%s\\n" "{version}"; exit 0; }}\n'
                        'echo "$0 $*" >> "$(dirname "$0")/calls"\n')
        path.chmod(0o755)
        return path

    def launch(self, roster, path_dirs=()):
        target = self.root / 'roster.json'
        target.write_text(json.dumps(roster))
        stdout, stderr = io.StringIO(), io.StringIO()
        environment = dict(os.environ, PATH=os.pathsep.join(
            [str(self.root / directory) for directory in path_dirs] + ['/usr/bin', '/bin']))
        with patch.dict(os.environ, environment, clear=True), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = self.roster.main(['--claude-cli', str(target)])
        return status, stdout.getvalue().splitlines(), stderr.getvalue().strip()

    def test_versions_compare_numerically(self):
        parse = self.roster.parse_claude_cli_version
        self.assertEqual(parse('2.1.328 (Claude Code)\n'), '2.1.328')
        self.assertIsNone(parse('{"type":"result"}'))
        self.assertIsNone(parse('OK'))
        key = self.roster.claude_cli_version_key
        self.assertLess(key('2.1.99'), key(self.roster.CLAUDE_CLI_MIN_VERSION))
        self.assertGreater(key('2.1.1000'), key('2.1.328'))
        self.assertGreater(key('2.2.0'), key('2.1.999'))
        self.assertEqual(self.roster.CLAUDE_CLI_MIN_VERSION, '2.1.328')

    def test_a_seat_runs_the_recorded_binary_not_the_first_one_on_path(self):
        pinned = self.fake('pinned', '2.1.328 (Claude Code)')
        self.fake('impostor', '2.1.400 (Claude Code)')
        status, lines, stderr = self.launch(
            {'seats': [], 'claude_cli': {'path': str(pinned), 'version': '2.1.328'}},
            path_dirs=('impostor',))
        self.assertEqual((status, lines, stderr), (0, [str(pinned), '2.1.328'], ''))

    def test_a_seat_refuses_a_claude_cli_older_than_the_minimum(self):
        stale = self.fake('stale', '2.1.121 (Claude Code)')
        status, lines, stderr = self.launch(
            {'seats': [], 'claude_cli': {'path': str(stale), 'version': '2.1.121'}})
        self.assertEqual((status, lines), (1, []))
        self.assertEqual(stderr, f'claude CLI 2.1.121 at {stale} is older than 2.1.328')

    def test_a_seat_refuses_a_cli_whose_version_it_cannot_read(self):
        silent = self.fake('silent', 'OK')
        status, _, stderr = self.launch({'seats': [], 'claude_cli': {'path': str(silent)}})
        self.assertEqual((status, stderr), (1, f'claude CLI at {silent} reports no version'))
        status, _, stderr = self.launch({'seats': [], 'claude_cli': {'path': 'claude'}})
        self.assertEqual((status, stderr), (1, 'roster claude_cli has no absolute path'))

    def test_a_roster_without_a_record_resolves_path_once_at_launch(self):
        real = self.fake('real', '2.1.330 (Claude Code)')
        link = self.root / 'linked' / 'claude'
        link.parent.mkdir()
        link.symlink_to(real)
        status, lines, _ = self.launch({'seats': []}, path_dirs=('linked',))
        self.assertEqual((status, lines), (0, [str(real), '2.1.330']))
        status, _, stderr = self.launch({'seats': []}, path_dirs=())
        self.assertEqual((status, stderr), (1, 'claude CLI not found on PATH'))

    def test_a_written_roster_records_the_claude_binary_it_resolved(self):
        real = self.fake('real', '2.1.328 (Claude Code)')
        link = self.root / 'linked' / 'claude'
        link.parent.mkdir()
        link.symlink_to(real)
        built = {'seats': [{'seat': 'opus', 'adapter': 'claude', 'model': 'opus'}],
                 'excluded': [], 'labs': ['anthropic']}
        target = self.root / 'written' / 'roster.json'
        target.parent.mkdir()
        environment = dict(os.environ, PATH=f'{link.parent}:/usr/bin:/bin')
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(self.roster, 'build', return_value=(dict(built), {}, None)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.roster.main(['--write', str(target)]), 0)
        self.assertEqual(json.loads(target.read_text())['claude_cli'],
                         {'path': str(real), 'version': '2.1.328'})
        built['seats'][0]['adapter'] = 'codex'
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(self.roster, 'build', return_value=(dict(built), {}, None)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.roster.main(['--write', str(target)]), 0)
        self.assertNotIn('claude_cli', json.loads(target.read_text()))
        self.assertFalse((real.parent / 'calls').exists())

    def test_the_seat_log_records_the_cli_version_and_model_that_ran(self):
        stream = ''.join(json.dumps(event) + '\n' for event in (
            {'type': 'system', 'subtype': 'init', 'claude_code_version': '2.1.328',
             'model': 'claude-haiku-5-5', 'tools': ['Read']},
            {'type': 'result', 'subtype': 'success', 'num_turns': 1, 'is_error': False,
             'structured_output': {'summary': 'ok', 'findings': []}}))
        out = self.root / 'result.json'
        process = subprocess.run([sys.executable, str(LIB / 'stream-summary.py'), 'claude', str(out)],
                                 input=stream, text=True, capture_output=True)
        self.assertEqual(process.stdout.splitlines()[0],
                         'init claude_code_version=2.1.328 model=claude-haiku-5-5')


if __name__ == '__main__':
    unittest.main()
