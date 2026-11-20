"""Codex review turns: the adapter refuses a command at once exactly when the read audit would."""
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
        """One explicit turn: a string runs as a command; a (command, output, exit code) tuple
        is recorded without running."""
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
            events.append({'type': 'item.completed',
                           'item': dict(item, aggregated_output=command[1], exit_code=command[2])})
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

    def audit(self, seat):
        """The post-run audit's return code and violation codes once the seat finishes."""
        self.turn(seat, [], FINDINGS)
        (self.session / f'{seat.label}-{SEAT}.json').write_text(FINDINGS + '\n')
        out = self.base / 'audit.json'
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

    def test_a_review_without_an_evidence_manifest_is_never_refused(self):
        legacy = self.session / 'legacy.prompt.md'
        legacy.write_text('use at most 4 repository tool calls before stopping this assignment.\n')
        seat = self.seat()
        self.turn(seat, [('node --test src/lib.py', '', 1)], READY)
        self.assertEqual(self.refusal(seat.turn, legacy), '')


if __name__ == '__main__':
    unittest.main()
