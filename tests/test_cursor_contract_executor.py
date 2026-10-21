"""Native checker fixtures do not qualify an application or live reviewer."""

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CursorContractExecutorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cursor-contract-executor-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.builder = module(REPO / 'scripts/build-cursor-plugin.py')

    def bundle(self):
        output = self.root / 'native' / 'review-council'
        self.assertEqual(self.builder.build(output), output)
        self.assertTrue((output / '.cursor-plugin/plugin.json').is_file())
        self.assertFalse((output / '.codex-plugin').exists())
        self.assertFalse((output / '.claude-plugin').exists())
        checker = module(output / 'scripts/rev-contract-check.py')
        self.assertEqual(checker.source_plugin(output), (output, ''))
        return output, checker

    def test_native_checker_uses_its_owned_replay_runner(self):
        output, checker = self.bundle()
        with patch.dict(os.environ, {}, clear=True):
            try:
                plugin, runner, identity = checker.contract_executor(output, output)
            except ValueError as error:
                self.fail('native Cursor checker must admit its owned runner: ' + str(error))
        expected = output / 'tests/run-tests.sh'
        self.assertEqual(plugin, output)
        self.assertEqual(runner, expected)
        self.assertEqual(identity['policy'], 'checker-owned')
        self.assertEqual(identity['plugin'], str(output))
        self.assertEqual(identity['runner'], str(expected))
        self.assertEqual(identity['runner_sha256'], hashlib.sha256(expected.read_bytes()).hexdigest())
        self.assertEqual(identity['runner_mode'], stat.S_IMODE(expected.stat().st_mode))

    def test_native_checker_still_refuses_an_override_owned_by_a_foreign_subject(self):
        output, checker = self.bundle()
        foreign = self.root / 'foreign'
        (foreign / '.cursor-plugin').mkdir(parents=True)
        (foreign / '.cursor-plugin/plugin.json').write_bytes(
            (output / '.cursor-plugin/plugin.json').read_bytes())
        (foreign / 'scripts').mkdir()
        self.assertEqual(checker.source_plugin(foreign), (foreign, ''))
        runner = foreign / 'replay.sh'
        runner.write_text('#!/bin/sh\nexit 0\n')
        runner.chmod(0o755)
        with patch.dict(os.environ, {'REVIEW_COUNCIL_CONTRACT_RUNNER': str(runner)}, clear=True):
            with self.assertRaisesRegex(ValueError, 'outside the foreign review target',
                                        msg='native admission must retain checker/subject separation'):
                checker.contract_executor(foreign, foreign)

    def test_checker_without_a_host_manifest_stays_unavailable(self):
        output, checker = self.bundle()
        (output / '.cursor-plugin/plugin.json').unlink()
        self.assertEqual(checker.source_plugin(output), (None, None))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'checker-owned plugin root is unavailable'):
                checker.contract_executor(output, output)

    def test_existing_canonical_checker_keeps_its_owned_runner(self):
        output = REPO / 'plugins/review-council'
        checker = module(output / 'scripts/rev-contract-check.py')
        with patch.dict(os.environ, {}, clear=True):
            plugin, runner, identity = checker.contract_executor(output, output)
        self.assertEqual(plugin, output)
        self.assertEqual(runner, output / 'tests/run-tests.sh')
        self.assertEqual(identity['policy'], 'checker-owned')


if __name__ == '__main__':
    unittest.main()
