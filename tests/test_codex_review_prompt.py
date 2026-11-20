"""Review-turn prompt bytes: one copy of each required source range, and a hashless Codex copy."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_codex_stage_repair import AUDIT, HELPER, SEAT, build_session
from test_patch_proven_source import PatchFixture

IDENTITY = re.compile(r'(?:\d+\. )?(?:Required source range: |Patch-proven source range: '
                      r'|Required source segment |Assigned patch chunk |Canonical assigned patch: '
                      r'|(?:Required|Optional) post-index original-source target: )')
HASH = re.compile(r'(?<![0-9a-f])(?:[0-9a-f]{40}|[0-9a-f]{64})(?![0-9a-f])')


def numbered(prompt):
    return [line for line in prompt.splitlines() if re.match(r'\d+\. ', line)]


class ReviewPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        base = Path(cls.temp.name)
        cls.root, cls.session, cls.prompt = build_session(base / 'codex')
        cls.claude = PatchFixture(base / 'claude', adapter='claude')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def compact(self, prompt):
        proc = subprocess.run([sys.executable, str(HELPER), '--compact-prompt', str(prompt)],
                              capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_each_required_source_range_is_listed_once(self):
        for prompt, ranges in ((self.prompt, 6), (self.claude.prompt, 1)):
            with self.subTest(prompt=prompt.name):
                text = prompt.read_text()
                steps = numbered(text.split('## Required reads, in this order', 1)[1].split(
                    '\n\n', 1)[0])
                self.assertEqual([int(line.split('.', 1)[0]) for line in steps],
                                 list(range(1, len(steps) + 1)))
                self.assertFalse([line for line in steps if 'source range: ' in line])
                self.assertEqual(len(re.findall(r'^Required source range: ', text, re.M)), ranges)
                self.assertTrue(any(line.startswith(
                    ('1. First assigned-patch action: ', '1. Read the entire assigned patch'))
                    for line in steps), steps)
                self.assertTrue(any('Required post-index original-source target: ' in line
                                    for line in steps))

    def test_the_codex_copy_drops_only_identity_hashes(self):
        original = self.prompt.read_bytes()
        copy = self.compact(self.prompt)
        before, after = original.decode().split('\n'), copy.decode().split('\n')
        self.assertEqual(len(before), len(after))
        stripped = 0
        for old, new in zip(before, after):
            if not IDENTITY.match(old):
                self.assertEqual(old, new)
                continue
            self.assertFalse(HASH.search(new), new)
            self.assertEqual(re.sub(r' (?:tree|blob|(?:content )?SHA-256) [0-9a-f]{40,64}', '',
                                    re.sub(r'("[a-z-]+):[0-9a-f]{64}"', r'\1"', old)), new)
            stripped += old != new
        self.assertGreater(stripped, 10)
        self.assertLess(len(copy), len(original) * 9 // 10)
        self.assertIn(b'Evidence manifest SHA-256: ', copy)
        self.assertEqual(self.prompt.read_bytes(), original)

    def test_the_receipted_prompt_still_binds_its_manifest(self):
        manifest = self.session / 'r1-evidence.manifest.json'
        proc = subprocess.run(
            [sys.executable, str(AUDIT), 'validate-prompt', '--root', str(self.root),
             '--session', str(self.session), '--manifest', str(manifest), '--seat', SEAT,
             '--prompt', str(self.prompt)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_the_capacity_projection_counts_the_copy_codex_reads(self):
        stages = Path(self.temp.name) / 'stages'
        subprocess.run([sys.executable, str(HELPER), '--prompt', str(self.prompt), '--seat', SEAT,
                        '--model', 'gpt-6-luna', '--stage-dir', str(stages)], check=True,
                       capture_output=True)
        cache = Path(self.temp.name) / 'models.json'
        cache.write_text(json.dumps({'models': [{
            'slug': 'gpt-6-luna', 'context_window': 10_000_000,
            'effective_context_window_percent': 100}]}))
        padded = self.session / 'padded.prompt.md'

        def projected(extra):
            padded.write_bytes(self.prompt.read_bytes() + extra)
            proc = subprocess.run(
                [sys.executable, str(HELPER), '--capacity', str(stages), '--prompt', str(padded),
                 '--model', 'gpt-6-luna'], capture_output=True, text=True,
                env=dict(os.environ, REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(cache)))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return int(proc.stdout.split('\t')[1])

        line = ('Required source segment 9/9: run cat -- /x raw bytes 1 visible bytes 9 '
                'content SHA-256 ' + 'ab' * 32 + '\n').encode()
        visible = b'\n' + line[:line.index(b' content SHA-256')] + b'\n'
        self.assertLessEqual(abs(projected(b'\n' + line) - projected(b'') - len(visible) / 3), 1)


if __name__ == '__main__':
    unittest.main()
