"""Codex context capacity: a seat whose evidence cannot fit its model's window refuses at launch."""
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_codex_stage_repair import HELPER, MODEL, SEAT, build_session


def load_helper():
    spec = importlib.util.spec_from_file_location('codex_proof_stages', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.root, cls.session, cls.prompt = build_session(cls.base / 'fixture')
        cls.stage_dir = cls.base / 'stages'
        listed = subprocess.run(
            [sys.executable, str(HELPER), '--prompt', str(cls.prompt), '--seat', SEAT,
             '--model', MODEL, '--stage-dir', str(cls.stage_dir)], capture_output=True, text=True)
        if listed.returncode:
            raise AssertionError(listed.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def capacity(self, models=None, raw=None, stage_dir=None, prompt=None, switch=None):
        cache = self.base / 'models_cache.json'
        if raw is not None:
            cache.write_text(raw)
        elif models is None:
            cache.unlink(missing_ok=True)
        else:
            cache.write_text(json.dumps({'client_version': '0.0.0-test', 'models': models}))
        proc = subprocess.run(
            [sys.executable, str(HELPER), '--capacity', str(stage_dir or self.stage_dir),
             '--prompt', str(prompt or self.prompt), '--model', MODEL],
            env=dict({key: value for key, value in os.environ.items()
                      if key != 'REVIEW_COUNCIL_CODEX_MAX_CONTEXT_WINDOW'},
                     REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(cache),
                     **({} if switch is None else {'REVIEW_COUNCIL_CODEX_MAX_CONTEXT_WINDOW': switch})),
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.rstrip('\n').split('\t')

    def row(self, window, percent=95, slug=MODEL):
        return {'slug': slug, 'visibility': 'list', 'context_window': window,
                'effective_context_window_percent': percent}

    def projected(self, **paths):
        verdict = self.capacity([self.row(10_000_000, 100)], **paths)
        self.assertEqual(verdict[0], 'fits', verdict)
        return int(verdict[1])

    def test_a_window_that_holds_the_evidence_fits(self):
        verdict = self.capacity([self.row(272_000), self.row(500_000, slug='gpt-6.2-sol')])
        self.assertEqual(verdict[0], 'fits', verdict)
        projected, limit = int(verdict[1]), int(verdict[2])
        self.assertEqual(limit, 142_120)
        self.assertLess(projected, limit)

    def test_evidence_over_the_window_share_is_refused_with_its_numbers(self):
        verdict = self.capacity([self.row(20_000)])
        self.assertEqual(verdict[0], 'over', verdict)
        projected = self.projected()
        self.assertIn(f'~{projected} tokens', verdict[1])
        self.assertIn("over 10450 (55% of gpt-6-luna's 19000 usable)", verdict[1])

    def test_the_limit_is_55_percent_of_the_usable_window(self):
        projected = self.projected()
        fits = self.capacity([self.row(-(-projected * 100 // 55), 100)])
        self.assertEqual(fits[0], 'fits', fits)
        self.assertEqual(int(fits[2]), projected)
        over = self.capacity([self.row((projected - 1) * 100 // 55, 100)])
        self.assertEqual(over[0], 'over', over)

    def test_the_projection_counts_staged_reads_turns_and_the_prompt(self):
        module = load_helper()
        plan = json.loads((self.stage_dir / 'stage-plan.json').read_text())['stages']
        evidence = sum(len(Path(read['path']).read_bytes()) for stage in plan
                       for read in stage['reads'])
        self.assertGreater(len(plan), 3)
        projected = self.projected()
        self.assertGreater(projected, 17_000 + evidence / 3.0 + len(self.prompt.read_bytes()) / 4.0)
        padded = self.session / 'padded.prompt.md'
        padded.write_bytes(self.prompt.read_bytes() + b'z' * 3000 + b'0123456789abcdef' * 4)
        self.assertIn(self.projected(prompt=padded) - projected, (1063, 1064, 1065))
        shorter = self.base / 'shorter-stages'
        shutil.copytree(self.stage_dir, shorter)
        index = plan[-1]
        self.assertEqual(index['kind'], 'evidence navigation index')
        (shorter / 'stage-plan.json').write_text(json.dumps({'stages': plan[:-1]}))
        index_tokens = module.context_tokens(Path(index['reads'][0]['path']).read_bytes(), 2.8)
        self.assertLessEqual(abs(projected - self.projected(stage_dir=shorter)
                                 - (300 + 120 + index_tokens)), 1)
        self.assertEqual(module.context_tokens(b'a' * 28, 2.8), 10)
        self.assertEqual(module.context_tokens(b'0123456789abcdef' * 4, 2.8), 64)
        self.assertEqual(module.context_tokens(b'x ' + b'f' * 31, 3.0), 11)

    def test_the_switch_raises_the_window_only_when_its_maximum_holds_the_evidence(self):
        projected = self.projected()
        maximum = -(-projected * 100 // 55)
        row = dict(self.row(maximum // 2, 100), max_context_window=maximum)
        default = self.capacity([row])
        self.assertEqual(default[0], 'over', default)
        for switch in (None, '0', 'yes'):
            with self.subTest(switch=switch):
                self.assertEqual(self.capacity([row], switch=switch), default)
        raised = self.capacity([row], switch='1')
        self.assertEqual(raised[0], 'raise', raised)
        self.assertEqual((int(raised[1]), int(raised[2]), int(raised[3])),
                         (projected, projected, maximum))
        short = self.capacity([dict(row, max_context_window=maximum - 2)], switch='1')
        self.assertEqual(short[0], 'over', short)
        self.assertIn(f'at its {maximum - 2}-token maximum window', short[1])
        for name, value in (('no maximum', None), ('maximum at the default', maximum // 2),
                            ('boolean maximum', True)):
            with self.subTest(case=name):
                plain = dict(row)
                plain.pop('max_context_window')
                if value is not None:
                    plain['max_context_window'] = value
                self.assertEqual(self.capacity([plain], switch='1'), default)

    def test_an_unknown_window_launches_as_before(self):
        cases = {
            'no cache': None,
            'unreadable cache': 'not json',
            'model not listed': [self.row(272_000, slug='gpt-6-sol')],
            'no window': [{'slug': MODEL, 'visibility': 'list'}],
            'zero window': [self.row(0)],
            'percent out of range': [self.row(272_000, 140)],
            'boolean window': [self.row(True)],
        }
        for name, models in cases.items():
            with self.subTest(case=name):
                verdict = (self.capacity(raw=models) if isinstance(models, str)
                           else self.capacity(models))
                self.assertEqual(verdict[0], 'unknown', verdict)
                self.assertTrue(verdict[1])


if __name__ == '__main__':
    unittest.main()
