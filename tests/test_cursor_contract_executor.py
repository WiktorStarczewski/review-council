"""Native checker fixtures do not qualify an application or live reviewer."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
import time
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


class ContractWorkerBoundsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='contract-worker-bounds-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checker = module(REPO / 'plugins/review-council/scripts/rev-contract-check.py')
        self.runner = self.root / 'runner'
        self.runner.write_text('#!' + sys.executable + '\n' + textwrap.dedent('''\
            import fcntl, json, os, subprocess, sys, time
            name = sys.argv[1]
            def record(kind):
                with open(os.environ['CONTRACT_TRACE'], 'a') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX)
                    stream.write(json.dumps([kind, name]) + '\\n')
                    stream.flush()
            record('start')
            if os.environ['CONTRACT_MODE'] == 'timeout':
                time.sleep(30)
            if os.environ['CONTRACT_MODE'] == 'fail' and name == 'provider_envelope_replay':
                raise SystemExit(7)
            if os.environ['CONTRACT_MODE'] == 'descendant' and name == 'provider_envelope_replay':
                child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            time.sleep(0.7 if os.environ['CONTRACT_MODE'] == 'budget' else 0.15)
            print(name, flush=True)
            record('end')
            if os.environ['CONTRACT_MODE'] == 'eof':
                sink = os.open(os.devnull, os.O_WRONLY)
                os.dup2(sink, 1)
                os.dup2(sink, 2)
                os.close(sink)
                time.sleep(0.25)
        '''))
        self.runner.chmod(0o755)

    def run_contracts(self, workers, mode='success'):
        trace = self.root / ('trace-' + str(workers) + '-' + mode)
        environment = dict(os.environ, CONTRACT_TRACE=str(trace), CONTRACT_MODE=mode)
        with patch.dict(os.environ, {'REVIEW_COUNCIL_CONTRACT_WORKERS': str(workers)},
                        clear=True):
            policy = self.checker.execution_policy()
        policy.update(shared_deadline_seconds={'timeout': 1, 'budget': 2}.get(mode, 10),
                      term_grace_seconds=1)
        launched = []
        self.observed_groups = []
        self.live_at_launch = []
        launch = self.checker.launch_group
        def observe_launch(command, *args, **kwargs):
            launched.append(command[-1])
            self.live_at_launch.append(1 + sum(
                group['process'].poll() is None for group in self.observed_groups))
            group = launch(command, *args, **kwargs)
            if group is not None:
                self.observed_groups.append(group)
            return group
        with patch.object(self.checker, 'launch_group', side_effect=observe_launch):
            outputs, failure = self.checker.run_contracts(
                self.runner, self.root, environment, policy)
        self.assertEqual(self.checker._ACTIVE_GROUPS, {})
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        return outputs, failure, launched, events

    def test_worker_cap_preserves_all_groups_and_output_order(self):
        for workers in (1, 2, 4):
            with self.subTest(workers=workers):
                outputs, failure, launched, events = self.run_contracts(workers)
                self.assertIsNone(failure)
                self.assertEqual(launched, list(self.checker.CONTRACT_TESTS))
                self.assertEqual(outputs, [(name + '\n').encode()
                                           for name in self.checker.CONTRACT_TESTS])
                self.assertCountEqual([name for kind, name in events if kind == 'start'],
                                      self.checker.CONTRACT_TESTS)
                active, peak = 0, 0
                for kind, _ in events:
                    active += 1 if kind == 'start' else -1
                    peak = max(peak, active)
                self.assertEqual(active, 0)
                self.assertLessEqual(peak, workers)
                self.assertLessEqual(max(self.live_at_launch), workers)

    def test_failure_does_not_launch_queued_groups(self):
        outputs, failure, launched, _ = self.run_contracts(1, 'fail')
        self.assertIsNone(outputs)
        self.assertIn('provider_envelope_replay (exit 7)', failure[0])
        self.assertEqual(launched, ['provider_envelope_replay'])

    def test_shared_deadline_includes_queued_groups(self):
        outputs, failure, launched, _ = self.run_contracts(1, 'timeout')
        self.assertIsNone(outputs)
        self.assertIn('shared deadline exceeded', failure[0])
        for name in self.checker.CONTRACT_TESTS:
            self.assertIn(name, failure[0])
        self.assertEqual(launched, ['provider_envelope_replay'])

    def test_successful_queued_groups_share_one_deadline(self):
        outputs, failure, launched, events = self.run_contracts(1, 'budget')
        self.assertIsNone(outputs)
        self.assertIn('shared deadline exceeded', failure[0])
        self.assertGreaterEqual(len(launched), 2)
        self.assertTrue(any(kind == 'end' for kind, _ in events))
        self.assertNotIn(self.checker.CONTRACT_TESTS[-1], launched)

    def test_stdout_eof_does_not_release_a_live_parent_slot(self):
        outputs, failure, launched, _ = self.run_contracts(1, 'eof')
        self.assertIsNone(failure)
        self.assertEqual(launched, list(self.checker.CONTRACT_TESTS))
        self.assertEqual(outputs, [(name + '\n').encode() for name in self.checker.CONTRACT_TESTS])
        self.assertEqual(max(self.live_at_launch), 1)

    def test_reaped_parent_descendant_blocks_queued_launch(self):
        outputs, failure, launched, _ = self.run_contracts(1, 'descendant')
        self.assertIsNone(outputs)
        self.assertIn('provider_envelope_replay left a descendant process running', failure[0])
        self.assertEqual(launched, ['provider_envelope_replay'])
        deadline = time.monotonic() + 2
        while self.checker.group_alive(self.observed_groups[0]['process'].pid) \
                and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.checker.group_alive(self.observed_groups[0]['process'].pid))

    def test_cancelled_replay_does_not_launch_any_groups(self):
        self.checker._CANCELLED.set()
        with patch.dict(os.environ, {'REVIEW_COUNCIL_CONTRACT_WORKERS': '2'}, clear=True):
            policy = self.checker.execution_policy()
        with patch.object(self.checker, 'launch_group', wraps=self.checker.launch_group) as launch:
            outputs, failure = self.checker.run_contracts(
                self.runner, self.root, dict(os.environ), policy)
        self.assertIsNone(outputs)
        self.assertIn('cancelled', failure[0])
        self.assertEqual(launch.call_count, 0)
        self.assertEqual(self.checker._ACTIVE_GROUPS, {})

    def test_worker_policy_defaults_to_four_and_rejects_invalid_caps(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.checker.execution_policy().get('max_workers'), 4)
        for invalid in ('0', '5', '-1', 'two', '2.0', ''):
            with self.subTest(invalid=invalid), patch.dict(os.environ, {
                    'REVIEW_COUNCIL_CONTRACT_WORKERS': invalid}, clear=True):
                with self.assertRaisesRegex(ValueError, 'REVIEW_COUNCIL_CONTRACT_WORKERS'):
                    self.checker.execution_policy()


if __name__ == '__main__':
    unittest.main()
