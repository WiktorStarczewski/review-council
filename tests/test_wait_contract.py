"""The orchestrator waits inside bounded foreground calls and never ends a turn merely to wait."""
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins' / 'review-council'
MECHANICAL = PLUGIN / 'scripts' / 'rev-mechanical.sh'
CORE = {
    'claude': PLUGIN / 'skills/rev',
    'codex': PLUGIN / 'codex-skills/rev',
    'pi': PLUGIN / 'pi-skills/review-council-rev',
    'cursor': PLUGIN / 'cursor-skills/rev',
}
CONTRACT = (
    r'wait contract',
    r'one bounded foreground call',
    r'9 minutes',
    r'never end the turn merely to wait',
    r'status line',
)
TURN_ENDING_WAIT = (
    r'waiting for all notifications',
    r'end (?:the|your) turn (?:and|to) wait',
    r'stop (?:the|your) turn (?:and|to) wait',
    r'wait for (?:the )?(?:background )?(?:task )?notifications?',
)


def flat(path):
    return re.sub(r'\s+', ' ', path.read_text(encoding='utf-8')).lower()


class WaitContractTests(unittest.TestCase):
    def test_every_host_variant_states_the_wait_contract(self):
        for host, directory in CORE.items():
            text = flat(directory / 'SKILL.md')
            for pattern in CONTRACT:
                with self.subTest(host=host, pattern=pattern):
                    self.assertRegex(text, pattern)

    def test_fresh_orchestrator_section_carries_the_contract(self):
        for host in ('claude', 'codex'):
            text = (CORE[host] / 'SKILL.md').read_text(encoding='utf-8')
            section = text.split('## Fresh orchestrator', 1)[1].split('\n## ', 1)[0]
            with self.subTest(host=host):
                self.assertRegex(section.lower(), r'wait contract')

    def test_collect_phase_polls_exit_files_in_the_foreground(self):
        for host in ('claude', 'codex', 'pi'):
            text = flat(CORE[host] / 'phases/20-discovery.md')
            for pattern in (r'until ', r'\.exit', r'9 minutes', r'one bounded foreground call'):
                with self.subTest(host=host, pattern=pattern):
                    self.assertRegex(text, pattern)

    def test_no_phase_ends_a_turn_to_wait(self):
        for host, directory in CORE.items():
            for path in sorted(directory.rglob('*.md')):
                text = flat(path)
                for pattern in TURN_ENDING_WAIT:
                    with self.subTest(file=str(path.relative_to(PLUGIN)), pattern=pattern):
                        self.assertNotRegex(text, pattern)

    def test_pi_skills_match_their_generator(self):
        result = subprocess.run(
            ['python3', str(ROOT / 'scripts/generate-pi-skills.py'), '--check'],
            check=False, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_ci(self, statuses, wait_secs):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = root / 'session'
            session.mkdir()
            (session / 'state.json').write_text('{"ci_run": "123"}')
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            queue = root / 'queue'
            queue.write_text('\n'.join(statuses) + '\n')
            gh = bin_dir / 'gh'
            gh.write_text(
                '#!/bin/bash\n'
                'if [ "$1 $2" = "run watch" ]; then echo "UNBOUNDED watch" >&2; exit 99; fi\n'
                'line=$(head -n1 "%(q)s"); [ "$(wc -l < "%(q)s")" -gt 1 ] && sed -i.bak 1d "%(q)s"\n'
                'echo "$line"\n' % {'q': queue})
            gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
            env = dict(os.environ, PATH='%s:%s' % (bin_dir, os.environ['PATH']),
                       REV_CI_POLL_SECS='0', REV_CI_WAIT_SECS=str(wait_secs))
            return subprocess.run([str(MECHANICAL), 'ci', str(session)], env=env,
                                  check=False, capture_output=True, text=True, timeout=60)

    def test_ci_watch_is_one_bounded_call_that_ends_on_a_conclusion(self):
        done = self.run_ci(['in_progress', 'in_progress', 'completed success'], 30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        failed = self.run_ci(['completed failure'], 30)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)

    def test_ci_watch_reports_still_running_instead_of_hanging(self):
        pending = self.run_ci(['in_progress'], 0)
        self.assertEqual(pending.returncode, 124, pending.stdout + pending.stderr)
        self.assertRegex(pending.stdout + pending.stderr, r'still running')


if __name__ == '__main__':
    unittest.main()
