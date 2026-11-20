"""Codex review turns: the adapter refuses a command at once exactly when the read audit would,
and credits a read exactly when the audit does."""
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from test_codex_stage_repair import AUDIT, HELPER, MODEL, SEAT, Seat, build_session, reads

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
                self.assertEqual(self.helper('--post-index-target-read-count', str(seat.raw)),
                                 '0\t1')
                returncode, codes = self.audit(seat)
                self.assertEqual(returncode, 2)
                self.assertIn('missing-required-source-read', codes)
                seat = self.seat()
                self.turn(seat, reads, READY)
                self.turn(seat, [self.target], READY)
                self.assertEqual(self.helper('--post-index-target-read-count', str(seat.raw)),
                                 '1\t1')
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
        self.assertEqual(self.helper('--post-index-target-read-count', str(seat.raw)), '1\t1')
        self.assertEqual(self.audit(seat), (0, []))

    def test_a_read_whose_command_failed_earns_no_credit(self):
        seat = self.seat()
        self.turn(seat, [(self.target, self.delivered(), 0, 'failed')], READY)
        self.assertEqual(self.helper('--turn-stats', str(seat.turn)).split('\t')[:2], ['1', '0'])
        self.assertEqual(self.helper('--post-index-target-read-count', str(seat.raw)), '0\t1')
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


if __name__ == '__main__':
    unittest.main()
