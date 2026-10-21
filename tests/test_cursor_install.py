"""The Cursor one-line installer builds the native bundle without a prior checkout."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / 'install-cursor.sh'


class CursorInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cursor-install-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def run_installer(self, *args, source=None, dest=None, path=None, ref=None):
        env = os.environ.copy()
        env.pop('REVIEW_COUNCIL_SOURCE', None)
        env.pop('REVIEW_COUNCIL_CURSOR_DEST', None)
        env.pop('REVIEW_COUNCIL_REF', None)
        if source is not None:
            env['REVIEW_COUNCIL_SOURCE'] = str(source)
        if dest is not None:
            env['REVIEW_COUNCIL_CURSOR_DEST'] = str(dest)
        if ref is not None:
            env['REVIEW_COUNCIL_REF'] = ref
        if path is not None:
            env['PATH'] = path
        return subprocess.run(['bash', str(INSTALLER), *args], env=env,
                              text=True, capture_output=True)

    def test_help_and_unknown_option(self):
        help_run = self.run_installer('--help')
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        self.assertIn('install-cursor.sh [--ref <branch-or-tag>]', help_run.stdout)
        unknown = self.run_installer('--build')
        self.assertEqual(unknown.returncode, 2)
        self.assertIn('unknown option', unknown.stderr)

    def test_source_checkout_installs_a_native_bundle_and_replaces_it(self):
        dest = self.root / 'local/review-council'
        first = self.run_installer(source=REPO, dest=dest)
        self.assertEqual(first.returncode, 0, first.stderr)
        manifest = json.loads((dest / '.cursor-plugin/plugin.json').read_text())
        source_version = json.loads(
            (REPO / 'plugins/review-council/.cursor-plugin/plugin.json').read_text())['version']
        self.assertEqual(manifest['version'], source_version)
        self.assertTrue((dest / 'docs/cursor-review-workflow.md').is_file())
        self.assertTrue((dest / 'docs/cursor-stack-workflow.md').is_file())
        self.assertIn('REVIEW_COUNCIL_HOST=cursor', (dest / 'scripts/roster.sh').read_text())
        for absent in ('.claude-plugin', '.codex-plugin', 'hooks', 'skills', 'codex-skills'):
            self.assertFalse((dest / absent).exists(), absent)
        self.assertIn(source_version, first.stdout)
        self.assertIn(str(dest), first.stdout)
        stale = dest / 'stale.txt'
        stale.write_text('old\n')
        second = self.run_installer(source=REPO, dest=dest)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(stale.exists())

    def test_refuses_a_misnamed_or_relative_destination_before_building(self):
        relative = self.run_installer(source=REPO, dest=Path('review-council'))
        self.assertEqual(relative.returncode, 2)
        self.assertIn('absolute', relative.stderr)
        misnamed = self.root / 'local/council'
        refused = self.run_installer(source=REPO, dest=misnamed)
        self.assertEqual(refused.returncode, 2)
        self.assertIn('named review-council', refused.stderr)
        self.assertFalse(misnamed.exists())

    def test_clone_uses_the_public_repository_and_selected_ref(self):
        bindir = self.root / 'bin'
        bindir.mkdir()
        git = bindir / 'git'
        git.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CAPTURE"\nexit 9\n')
        git.chmod(0o755)
        capture = self.root / 'capture'
        dest = self.root / 'out/review-council'
        env_path = str(bindir) + os.pathsep + os.environ['PATH']
        env_note = os.environ.get('CAPTURE')
        os.environ['CAPTURE'] = str(capture)
        def restore_capture():
            if env_note is None:
                os.environ.pop('CAPTURE', None)
            else:
                os.environ['CAPTURE'] = env_note
        self.addCleanup(restore_capture)
        proc = self.run_installer('--ref', 'review-council--v0.7.1', dest=dest, path=env_path)
        self.assertEqual(proc.returncode, 9, proc.stderr)
        self.assertFalse(dest.exists())
        line = capture.read_text().strip()
        self.assertTrue(line.startswith(
            'clone --depth 1 --branch review-council--v0.7.1 '
            'https://github.com/WiktorStarczewski/review-council.git '), line)
        self.assertFalse(Path(line.rsplit(' ', 1)[-1]).exists(),
                         'a failed clone must remove its temporary checkout')

    def test_missing_source_checkout_does_not_require_git(self):
        dest = self.root / 'out/review-council'
        missing = self.root / 'not-a-checkout'
        missing.mkdir()
        proc = self.run_installer(source=missing, dest=dest)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('REVIEW_COUNCIL_SOURCE', proc.stderr)
        self.assertFalse(dest.exists())


if __name__ == '__main__':
    unittest.main()
