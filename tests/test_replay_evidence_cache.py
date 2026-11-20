"""In-run read-audit replays validate a seat's evidence once per attempt, never on stale bytes."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_codex_stage_repair import HELPER, MODEL, SEAT, Seat, build_session, load, reads
from test_deleted_source_proof import SCRIPTS, SourceFixture, load_read_audit

AUDIT = SCRIPTS / 'lib/review-read-audit.py'


class CountedValidation:
    """Counts whole manifest validations, not the nested parent validations inside one."""

    def __init__(self, module):
        self.inner = module.validated_manifest
        self.calls = 0
        self.depth = 0

    def __call__(self, *args, **kwargs):
        self.calls += self.depth == 0
        self.depth += 1
        try:
            return self.inner(*args, **kwargs)
        finally:
            self.depth -= 1


class ClaudeStopGateCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='replay-cache-claude-')
        cls.fixture = SourceFixture(Path(cls.temp.name) / 'segments', 'deleted', adapter='claude')
        cls.audit = load_read_audit()
        cls.index = cls.fixture.session / f'r{cls.fixture.label}-evidence.md'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix='replay-cache-attempt-')
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.cache = self.work / 'r1-sol.evidence-cache'
        self.counter = CountedValidation(self.audit._load_evidence_module())
        counting = patch.object(self.audit._load_evidence_module(), 'validated_manifest',
                                self.counter)
        counting.start()
        self.addCleanup(counting.stop)

    def stop(self, raw, state, cache=None):
        fixture = self.fixture
        args = argparse.Namespace(
            adapter='claude', raw=str(raw), prompt=str(fixture.prompt), root=str(fixture.root),
            session=str(fixture.session), seat=None, deps=None, state=str(state),
            evidence_cache=None if cache is None else str(cache), log=None, timeout=None)
        event = json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'StructuredOutput',
                            'tool_input': {'summary': 'done', 'findings': []}})
        stdout = io.StringIO()
        with patch('sys.stdin', io.StringIO(event)), contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.audit.stop_hook(args), 0)
        return stdout.getvalue()

    def transcript(self):
        raw, _, _ = self.fixture.claude_transcript(omitted_artifacts=(self.index.name,))
        return raw

    def test_stop_gate_replays_in_one_attempt_validate_the_evidence_once(self):
        raw = self.transcript()
        uncached = [self.stop(raw, self.work / 'plain.stop-gate') for _ in range(2)]
        self.assertEqual(self.counter.calls, 2)
        self.counter.calls = 0
        cached = [self.stop(raw, self.work / 'cached.stop-gate', self.cache) for _ in range(2)]
        self.assertEqual(self.counter.calls, 1, 'the second replay validated the evidence again')
        self.assertEqual(cached, uncached)
        self.assertIn('review stop blocked (1 of 3)', cached[0])

    def test_a_changed_bound_file_is_validated_again_with_the_uncached_verdict(self):
        raw = self.transcript()
        self.stop(raw, self.work / 'warm.stop-gate', self.cache)
        roster = self.fixture.session / 'roster.json'
        original = roster.read_bytes()
        self.addCleanup(roster.write_bytes, original)
        roster.write_bytes(original + b' ')
        self.counter.calls = 0
        cached = self.stop(raw, self.work / 'cached.stop-gate', self.cache)
        self.assertEqual(self.counter.calls, 1, 'a changed roster reused the cached validation')
        self.assertEqual(cached, self.stop(raw, self.work / 'plain.stop-gate'))
        self.assertEqual(cached, '', 'an invalid manifest never sends the seat back')

    def test_the_post_run_audit_validates_every_time(self):
        raw = self.transcript()
        self.stop(raw, self.work / 'warm.stop-gate', self.cache)
        self.counter.calls = 0
        fixture = self.fixture
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()):
                self.audit.audit(argparse.Namespace(
                    adapter='claude', raw=str(raw), prompt=str(fixture.prompt),
                    root=str(fixture.root), session=str(fixture.session), seat=None, deps=None,
                    result=None, out=str(self.work / 'audit.json')))
        self.assertEqual(self.counter.calls, 2)

    def test_a_warmed_cache_serves_the_first_replay(self):
        fixture = self.fixture
        warmed = subprocess.run(
            [sys.executable, str(AUDIT), 'evidence-cache', '--prompt', str(fixture.prompt),
             '--root', str(fixture.root), '--session', str(fixture.session),
             '--cache', str(self.cache)], capture_output=True, text=True)
        self.assertEqual(warmed.returncode, 0, warmed.stderr)
        self.assertIn('evidence validated', warmed.stderr)
        raw = self.transcript()
        decision = self.stop(raw, self.work / 'cached.stop-gate', self.cache)
        self.assertEqual(self.counter.calls, 0, 'the warmed validation was not reused')
        self.assertEqual(decision, self.stop(raw, self.work / 'plain.stop-gate'))


class InProcessSeat(Seat):
    """The scripted Codex seat, its stage steps run in this process to count validations."""

    def __init__(self, stages, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stages = stages

    def step(self):
        return list(self.stages.stage_step(
            str(self.stage_dir), str(self.raw), str(self.turn), str(self.prompt), self.name,
            str(self.root), str(self.session)))


class CodexStageStepCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='replay-cache-codex-')
        cls.base = Path(cls.temp.name)
        cls.root, cls.session, cls.prompt = build_session(cls.base / 'f6')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def drive(self, slips):
        stages = load(HELPER)
        audit = stages.read_audit_module()
        counter = CountedValidation(audit._load_evidence_module())
        stage_dir = Path(tempfile.mkdtemp(dir=self.base))
        listed = subprocess.run(
            [sys.executable, str(HELPER), '--prompt', str(self.prompt), '--seat', SEAT,
             '--model', MODEL, '--stage-dir', str(stage_dir)], capture_output=True, text=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        seat = InProcessSeat(stages, self.root, self.session, self.prompt, stage_dir)
        transcript = []
        with patch.object(stages, 'read_audit_module', lambda: audit), \
                patch.object(audit._load_evidence_module(), 'validated_manifest', counter):
            for _ in range(60):
                step = seat.step()
                transcript.append(step)
                if step[0] != 'run':
                    return transcript, counter.calls
                slip = slips.get(seat.turns + 1)
                commands = reads(step[1])
                seat.run(slip(commands) if slip else commands)
        raise AssertionError('stage steps did not finish')

    def test_slow_stage_steps_in_one_attempt_validate_the_evidence_once(self):
        transcript, calls = self.drive({2: lambda listed: [], 5: lambda listed: []})
        self.assertEqual(transcript[-1], ['done'])
        repairs = [step for step in transcript if step[0] == 'run' and len(step) == 3]
        self.assertEqual(len(repairs), 2, transcript)
        self.assertEqual(calls, 1, f'{len(repairs)} slow steps validated the evidence {calls} times')


if __name__ == '__main__':
    unittest.main()
