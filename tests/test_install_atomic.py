"""Atomic installation contracts for the generated Codex bundle."""
import errno
import importlib.util
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class AtomicInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.builder = load_module(REPO / 'scripts/build-codex-plugin.py', 'atomic_builder')
        self.installer = load_module(REPO / 'scripts/install-codex-plugin.py', 'atomic_installer')

    def test_standalone_build_keeps_source_version(self):
        source = json.loads(
            (REPO / 'plugins/review-council/.codex-plugin/plugin.json').read_text())
        output = self.builder.build(self.home / 'standalone/review-council')
        built = json.loads((output / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(built['version'], source['version'])
        self.assertEqual(
            (output / 'docs/pr-review.md').read_bytes(),
            (REPO / 'plugins/review-council/docs/pr-review.md').read_bytes(),
        )

    def test_real_exchange_swaps_two_nonempty_directories(self):
        left = self.home / 'left'
        right = self.home / 'right'
        left.mkdir()
        right.mkdir()
        (left / 'identity').write_text('left\n')
        (right / 'identity').write_text('right\n')

        self.builder._atomic_exchange(left, right)

        self.assertEqual((left / 'identity').read_text(), 'right\n')
        self.assertEqual((right / 'identity').read_text(), 'left\n')

    def test_unsupported_exchange_preserves_live_bundle(self):
        live = self.builder.build(self.home / 'plugins/review-council')
        marker = live / 'prior-bundle'
        marker.write_text('still valid\n')

        with patch.object(self.builder, '_atomic_exchange',
                          side_effect=OSError(errno.ENOTSUP, 'unsupported')):
            with self.assertRaisesRegex(OSError, 'unsupported'):
                self.builder.build(live)

        self.assertEqual(marker.read_text(), 'still valid\n')
        json.loads((live / '.codex-plugin/plugin.json').read_text())

    def run_killed_update(self, live, timing):
        script = '''
import importlib.util
import os
from pathlib import Path
import signal
import sys

spec = importlib.util.spec_from_file_location('killed_builder', sys.argv[1])
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
real_exchange = builder._atomic_exchange

def stop_during_exchange(left, right):
    if sys.argv[3] == 'after':
        real_exchange(left, right)
    os.kill(os.getpid(), signal.SIGKILL)

builder._atomic_exchange = stop_during_exchange
builder.build(Path(sys.argv[2]))
'''
        return subprocess.run([
            'python3', '-c', script,
            str(REPO / 'scripts/build-codex-plugin.py'), str(live), timing,
        ], capture_output=True, text=True)

    def test_process_killed_before_exchange_preserves_live_bundle(self):
        live = self.builder.build(self.home / 'plugins/review-council')
        marker = live / 'prior-bundle'
        marker.write_text('still valid\n')

        result = self.run_killed_update(live, 'before')

        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertEqual(marker.read_text(), 'still valid\n')

    def test_process_killed_after_exchange_leaves_new_bundle_live(self):
        live = self.builder.build(self.home / 'plugins/review-council')
        marker = live / 'prior-bundle'
        marker.write_text('old\n')

        result = self.run_killed_update(live, 'after')

        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(marker.exists())
        json.loads((live / '.codex-plugin/plugin.json').read_text())

    def test_exchange_observers_see_only_complete_old_or_new_trees(self):
        live = self.home / 'live'
        stage = self.home / 'stage'
        live.mkdir()
        stage.mkdir()
        (live / 'identity').write_text('old\n')
        (stage / 'identity').write_text('new\n')
        started = threading.Event()
        finished = threading.Event()
        observed = []

        def observe():
            started.set()
            while not finished.is_set():
                try:
                    observed.append((live / 'identity').read_text())
                except FileNotFoundError:
                    observed.append('missing')

        watcher = threading.Thread(target=observe)
        watcher.start()
        self.assertTrue(started.wait(timeout=1))
        for _ in range(200):
            self.builder._atomic_exchange(stage, live)
        finished.set()
        watcher.join(timeout=1)

        self.assertFalse(watcher.is_alive())
        self.assertTrue(observed)
        self.assertEqual(set(observed), {'old\n', 'new\n'})

    def test_stamp_failure_preserves_live_bundle_and_retry_succeeds(self):
        live = self.builder.build(self.home / 'plugins/review-council')
        manifest = live / '.codex-plugin/plugin.json'
        prior = json.loads(manifest.read_text())
        prior['version'] = '0.4.1+codex.prior'
        manifest.write_text(json.dumps(prior, indent=2) + '\n')
        marker = live / 'prior-bundle'
        marker.write_text('still valid\n')
        prior_manifest = manifest.read_bytes()

        marketplace = self.home / '.agents/plugins/marketplace.json'
        marketplace.parent.mkdir(parents=True)
        marketplace.write_text(json.dumps({
            'name': 'personal',
            'interface': {'displayName': 'Personal'},
            'plugins': [{
                'name': 'review-council',
                'source': {'source': 'local', 'path': './plugins/review-council'},
                'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
                'category': 'Productivity',
            }],
        }))

        original_write_text = Path.write_text
        injected = False

        def corrupt_stamp(path, data, *args, **kwargs):
            nonlocal injected
            if (not injected and path.name == 'plugin.json'
                    and path.parent.name == '.codex-plugin'):
                injected = True
                original_write_text(path, '{"name":"review-council"', *args, **kwargs)
                raise OSError('injected cachebuster stamp failure')
            return original_write_text(path, data, *args, **kwargs)

        common = (
            patch.object(self.installer.Path, 'home', return_value=self.home),
            patch.object(self.installer.shutil, 'which', return_value='/bin/codex'),
            patch.object(self.installer.time, 'time_ns', return_value=123456789),
            patch.object(self.installer.subprocess, 'run'),
            patch('sys.stdout', new=io.StringIO()),
        )
        with common[0], common[1], common[2], common[3] as run, common[4], \
                patch.object(Path, 'write_text', new=corrupt_stamp):
            with self.assertRaisesRegex(OSError, 'injected cachebuster stamp failure'):
                self.installer.install()
            run.assert_not_called()

        self.assertTrue(injected)
        self.assertEqual(manifest.read_bytes(), prior_manifest)
        self.assertEqual(marker.read_text(), 'still valid\n')
        json.loads(manifest.read_text())

        with patch.object(self.installer.Path, 'home', return_value=self.home), \
             patch.object(self.installer.shutil, 'which', return_value='/bin/codex'), \
             patch.object(self.installer.time, 'time_ns', return_value=123456790), \
             patch.object(self.installer.subprocess, 'run') as run, \
             patch('sys.stdout', new=io.StringIO()):
            self.installer.install()

        installed = json.loads(manifest.read_text())
        source_version = json.loads(
            (REPO / 'plugins/review-council/.codex-plugin/plugin.json').read_text())['version']
        self.assertEqual(installed['version'].split('+', 1)[0], source_version.split('+', 1)[0])
        self.assertTrue(installed['version'].endswith('+codex.123456790'))
        self.assertFalse(marker.exists())
        run.assert_called_once_with(
            ['codex', 'plugin', 'add', 'review-council@personal'], check=True)


if __name__ == '__main__':
    unittest.main()
