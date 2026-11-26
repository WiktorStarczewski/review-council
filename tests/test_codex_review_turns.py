"""Codex review turns: the adapter refuses a command at once exactly when the read audit would,
and credits a read exactly when the audit does."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from test_codex_stage_repair import (AUDIT, HELPER, MODEL, REPO, SCRIPTS, SEAT, Seat,
                                     build_plan_session, build_session, reads)

READY = '{"status":"ready","next_step":""}'
FINDINGS = '{"summary":"checked","findings":[]}'


class ReviewTurnRefusalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.root, cls.session, cls.prompt = build_session(cls.base / 'codex')
        stage_dir = cls.base / 'stages'
        subprocess.run([sys.executable, str(HELPER), '--prompt', str(cls.prompt), '--seat', SEAT,
                        '--model', MODEL, '--stage-dir', str(stage_dir)], check=True,
                       capture_output=True)
        seat = Seat(cls.root, cls.session, cls.prompt, stage_dir)
        while (step := seat.step())[0] == 'run':
            seat.run(reads(step[1]))
        cls.stage_dir, cls.staged = stage_dir, (seat.raw.read_text(), seat.turns, seat.ids)
        target = next(line for line in cls.prompt.read_text().splitlines()
                      if line.startswith('Required post-index original-source target: '))
        path, lines = target.split(': ', 1)[1].split(' ', 1)[0].rsplit(':', 1)
        cls.target = 'sed -n {},{}p {}'.format(*lines.split('-'), path)
        cls.location = f'{path}:{lines}'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def seat(self):
        """A seat that has read every prepared-evidence stage."""
        seat = Seat(self.root, self.session, self.prompt, self.stage_dir)
        text, seat.turns, seat.ids = self.staged
        seat.raw.write_text(text)
        return seat

    def turn(self, seat, commands, answer):
        """One explicit turn: a string runs as a command; a (command, output, exit code[,
        status]) tuple is recorded without running."""
        events = [{'type': 'turn.started'}]
        for command in commands:
            if isinstance(command, str):
                events.extend(seat.call(command))
                continue
            seat.ids += 1
            item = {'id': f'item_{seat.ids}', 'type': 'command_execution',
                    'command': '/bin/zsh -lc ' + shlex.quote(command[0])}
            events.append({'type': 'item.started',
                           'item': dict(item, aggregated_output='', exit_code=None)})
            completed = dict(item, aggregated_output=command[1], exit_code=command[2])
            if len(command) > 3:
                completed['status'] = command[3]
            events.append({'type': 'item.completed', 'item': completed})
        seat.turns += 1
        events.append({'type': 'item.completed', 'item': {
            'id': f'answer_{seat.turns}', 'type': 'agent_message', 'text': answer}})
        events.append({'type': 'turn.completed', 'usage': {}})
        text = ''.join(json.dumps(event) + '\n' for event in events)
        seat.turn.write_text(text)
        with seat.raw.open('a') as stream:
            stream.write(text)

    def refusal(self, turn, prompt=None):
        proc = subprocess.run(
            [sys.executable, str(HELPER), '--turn-refusal', str(turn),
             '--prompt', str(prompt or self.prompt), '--root', str(self.root),
             '--session', str(self.session)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def helper(self, *args):
        proc = subprocess.run(
            [sys.executable, str(HELPER), *args, '--prompt', str(self.prompt),
             '--root', str(self.root), '--session', str(self.session)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def gaps(self, seat):
        """The adapter's next evidence question when the seat returns ready, or ''."""
        return self.helper('--review-gaps', str(seat.raw), '--seat', SEAT)

    def audit(self, seat):
        """The post-run audit's return code and violation codes once the seat finishes."""
        self.turn(seat, [], FINDINGS)
        (self.session / f'{seat.label}-{SEAT}.json').write_text(FINDINGS + '\n')
        out = self.session / f'{seat.label}-{SEAT}.read-audit.json'
        proc = subprocess.run(
            [sys.executable, str(AUDIT), 'audit', '--adapter', 'codex', '--raw', str(seat.raw),
             '--prompt', str(self.prompt), '--root', str(self.root),
             '--session', str(self.session), '--seat', SEAT, '--out', str(out)],
            capture_output=True, text=True)
        return proc.returncode, sorted({row['code'] for row in json.loads(out.read_text())[
            'violations']})

    def test_a_command_the_audit_rejects_is_refused_with_the_audit_code(self):
        for command, code in (
                (('rg -n fn04 src | head-80', 'zsh: command not found: head-80\n', 127),
                 'unsupported-shell-command'),
                (('node --test src/lib.py', '', 1), 'unsupported-shell-command'),
                (('yarn ts --pretty false', '', 1), 'unsupported-shell-command'),
                (('sed -n 1,5p /etc/hosts', '', 0), 'path-outside-scope')):
            with self.subTest(command=command[0]):
                seat = self.seat()
                self.turn(seat, [self.target, command], READY)
                self.assertEqual(self.refusal(seat.turn), code)
                returncode, codes = self.audit(seat)
                self.assertEqual(returncode, 2)
                self.assertIn(code, codes)

    def test_a_mistyped_limiter_that_never_ran_is_not_refused_and_earns_no_credit(self):
        not_found = 'zsh:1: command not found: head-80\n'
        seat = self.seat()
        self.turn(seat, [self.target, ('rg -n -F fn04 src/lib.py | head-80', not_found, 127,
                                       'failed')], READY)
        self.assertEqual(self.refusal(seat.turn), '')
        self.assertEqual(self.audit(seat), (0, []))
        seat = self.seat()
        self.turn(seat, [(self.target + ' | head-80', not_found, 127, 'failed')], READY)
        self.assertEqual(self.refusal(seat.turn), '')
        returncode, codes = self.audit(seat)
        self.assertEqual(returncode, 2)
        self.assertIn('missing-required-source-read', codes)
        self.assertNotIn('unsupported-shell-command', codes)

    def test_a_command_that_ran_or_hides_one_stays_refused_though_its_output_says_not_found(self):
        not_found = 'zsh:1: command not found: head-80\n'
        for command in (
                ('rg -n fn04 src | head-80', not_found, 0),
                ('rg -n fn04 src | head-80; rm src/lib.py', not_found, 127, 'failed'),
                ('rg -n fn04 src | head-90', not_found, 127, 'failed'),
                ('rg -n fn04 src | head-80', not_found + 'more\n', 127, 'failed'),
                ('rg -n fn04 src | head-80', 'zsh:1: command not found: node\n', 127, 'failed'),
                ('node --test src/lib.py', 'zsh:1: command not found: node\n', 127, 'failed')):
            with self.subTest(command=command):
                seat = self.seat()
                self.turn(seat, [self.target, command], READY)
                self.assertEqual(self.refusal(seat.turn), 'unsupported-shell-command')
                returncode, codes = self.audit(seat)
                self.assertEqual(returncode, 2)
                self.assertIn('unsupported-shell-command', codes)

    def test_commands_the_audit_accepts_or_only_advises_on_are_not_refused(self):
        seat = self.seat()
        self.turn(seat, [self.target, 'rg -n fn04 src/lib.py',
                         ('npx tsc --noEmit', '', 0)], READY)
        self.assertEqual(self.refusal(seat.turn), '')
        self.assertEqual(self.audit(seat), (0, []))

    def test_a_target_read_the_audit_voids_counts_only_once_a_later_turn_reads_it_again(self):
        # Over 32 KiB in one turn (tool-turn-output-too-large), or batched with a second read
        # (unsupported-source-batch): the audit credits neither read, though both deliver it.
        big = [self.target, 'sed -n 1,5p src/lib.py', 'sed -n 13,17p src/lib.py']
        for reads in (big, [f'{self.target}; {self.target}']):
            with self.subTest(reads=reads):
                seat = self.seat()
                self.turn(seat, reads, READY)
                self.assertIn(f'the exact required original-source target {self.location}',
                              self.gaps(seat))
                returncode, codes = self.audit(seat)
                self.assertEqual(returncode, 2)
                self.assertIn('missing-required-source-read', codes)
                seat = self.seat()
                self.turn(seat, reads, READY)
                self.turn(seat, [self.target], READY)
                self.assertEqual(self.gaps(seat), '')
                self.assertEqual(self.audit(seat), (0, []))

    def delivered(self):
        return subprocess.run(['bash', '-c', self.target], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout

    def test_a_failed_command_over_32_kib_leaves_the_reads_beside_it_credited(self):
        # The audit pairs only a successful execution with its turn, so a failing test run's
        # output counts toward no turn's 32 KiB.
        failing = ''.join(f'FAIL src/lib.test.ts case {index}: expected y received x\n'
                          for index in range(1000))
        seat = self.seat()
        self.turn(seat, [self.target, ('yarn test src/lib.test.ts', failing, 1)], READY)
        calls, size, _ = self.helper('--turn-stats', str(seat.turn)).split('\t')
        self.assertEqual((calls, int(size)), ('2', len(self.delivered().encode())))
        self.assertEqual(self.helper('--voided-ranges', str(seat.turn)), '')
        self.assertEqual(self.helper('--voided-ranges', str(seat.raw)), '')
        self.assertEqual(self.gaps(seat), '')
        self.assertEqual(self.audit(seat), (0, []))

    def test_a_read_whose_command_failed_earns_no_credit(self):
        seat = self.seat()
        self.turn(seat, [(self.target, self.delivered(), 0, 'failed')], READY)
        self.assertEqual(self.helper('--turn-stats', str(seat.turn)).split('\t')[:2], ['1', '0'])
        self.assertIn(f'the exact required original-source target {self.location}',
                      self.gaps(seat))
        returncode, codes = self.audit(seat)
        self.assertEqual(returncode, 2)
        self.assertIn('missing-required-source-read', codes)

    def test_ranges_read_only_where_the_audit_credits_nothing_are_listed(self):
        seat = self.seat()
        self.turn(seat, [self.target, 'sed -n 1,5p src/lib.py', 'sed -n 13,17p src/lib.py'], READY)
        listed = 'src/lib.py:10-11, src/lib.py:1-5, src/lib.py:13-17'
        self.assertEqual(self.helper('--voided-ranges', str(seat.turn)), listed)
        self.assertEqual(self.helper('--voided-ranges', str(seat.raw)), listed)
        self.turn(seat, [self.target, 'sed -n 1,2p src/lib.py', 'sed -n 1,3p src/use00.py; '
                         'sed -n 1,1p src/use00.py'], READY)
        self.assertEqual(self.helper('--voided-ranges', str(seat.turn)), 'src/use00.py:1-3')
        self.assertEqual(self.helper('--voided-ranges', str(seat.raw)),
                         'src/lib.py:1-5, src/lib.py:13-17, src/use00.py:1-3')

    def test_a_review_without_an_evidence_manifest_is_never_refused(self):
        legacy = self.session / 'legacy.prompt.md'
        legacy.write_text('use at most 4 repository tool calls before stopping this assignment.\n')
        seat = self.seat()
        self.turn(seat, [('node --test src/lib.py', '', 1)], READY)
        self.assertEqual(self.refusal(seat.turn, legacy), '')

    def test_a_failed_typo_of_a_missing_session_artifact_is_skipped_while_siblings_stay_refused(self):
        import re
        match = re.search(
            r'Required source segment [^\n]*?(/\S+-source-segment-\d+-\d+\.txt)',
            self.prompt.read_text(encoding='utf-8'),
        )
        self.assertIsNotNone(match)
        real_seg = Path(match.group(1))
        typo = real_seg.with_name(
            re.sub(r'-(\d+)-(\d+)\.txt$', r'-0\1-\2.txt', real_seg.name)
        )
        self.assertFalse(typo.exists())

        seat = self.seat()
        self.turn(seat, [
            self.target,
            (f'cat -- {shlex.quote(str(typo))}', f'cat: {typo}: No such file or directory\n',
             1, 'failed'),
        ], READY)
        self.assertEqual(self.refusal(seat.turn), '')
        self.assertEqual(self.audit(seat), (0, []))

        sibling = self.session / 'r1-codex-luna-2.json'
        self.assertFalse(sibling.exists())
        seat = self.seat()
        self.turn(seat, [
            self.target,
            (f'cat -- {shlex.quote(str(sibling))}',
             f'cat: {sibling}: No such file or directory\n', 1, 'failed'),
        ], READY)
        self.assertEqual(self.refusal(seat.turn), 'unnamed-session-artifact')
        returncode, codes = self.audit(seat)
        self.assertEqual(returncode, 2)
        self.assertIn('unnamed-session-artifact', codes)


class PlanReviewTurnTests(unittest.TestCase):
    """A plan seat run through the Codex adapter, with the test shim as the Codex CLI."""

    def test_a_voided_turn_holding_the_only_site_reads_is_asked_for_them_again(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root, session, prompts = build_plan_session(base / 'plan')
            prompt = prompts['sol']
            windows = [line.split(': ', 1)[1] for line in prompt.read_text().splitlines()
                       if line.startswith('Mandatory cluster source window: ')]
            reads = ['sed -n {},{}p {}'.format(*lines.split('-'), path)
                     for path, lines in (window.rsplit(':', 1) for window in windows)]
            calls = base / 'calls'
            calls.mkdir()
            (base / 'tmp').mkdir()
            raw, log = session / 'r1p-sol.stream.ndjson', session / 'r1p-sol.log'
            env = dict(
                os.environ, PATH=f"{REPO / 'plugins/review-council/tests/shims'}:"
                + os.environ['PATH'], TMPDIR=str(base / 'tmp'),
                CODEX_HOME=str(base / 'codex-home'), SHIM_MODE='staged-audit',
                SHIM_STAGE_DIR=str(calls), SHIM_CALLS_FILE=str(base / 'calls.log'),
                SHIM_POST_INDEX_COMMAND='\n'.join(reads), SHIM_REVIEW_REREAD='1',
                # A successful typecheck's 40 KB voids the first review turn's site reads.
                SHIM_REVIEW_EXTRA_COMMAND='npx tsc --noEmit', SHIM_REVIEW_EXTRA_EXIT='0',
                SHIM_REVIEW_EXTRA_BYTES='40000', SEAT='sol', MODEL=MODEL, EFFORT='xhigh',
                MODE='prompt', ROOT=str(root), PROMPT=str(prompt),
                SCHEMA=str(REPO / 'plugins/review-council/schema/findings.schema.json'),
                OUT=str(session / 'r1p-sol.json'), LOG=str(log), RAW=str(raw), BASE='abc')
            env.pop('REV_DEPS_DIR', None)
            proc = subprocess.run(['bash', str(SCRIPTS / 'seats.d/codex.sh')], env=env,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr + log.read_text())
            self.assertRegex(log.read_text(), r'review turn 1 returned [0-9]+ bytes, over 32 KiB,'
                             r' so the read audit credits none of its reads')
            out = session / 'r1p-sol.read-audit.json'
            audited = subprocess.run(
                [sys.executable, str(AUDIT), 'audit', '--adapter', 'codex', '--raw', str(raw),
                 '--prompt', str(prompt), '--root', str(root), '--session', str(session),
                 '--seat', 'sol', '--out', str(out)], capture_output=True, text=True)
            audit = json.loads(out.read_text())
            self.assertEqual((audited.returncode, sorted({row['code'] for row in audit[
                'violations']})), (0, []))
            self.assertEqual(len(audit['plan_cluster_source_proofs']), 4)
            asked = [path.read_text() for path in sorted(calls.glob('call-*.stdin'))
                     if 'Next evidence question:' in path.read_text()]
            self.assertEqual(len(asked), 1)
            for window in windows:
                self.assertIn(window, asked[0])


if __name__ == '__main__':
    unittest.main()
