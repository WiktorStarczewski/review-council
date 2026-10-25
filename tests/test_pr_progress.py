"""Explicit PR progression preserves frozen review history."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from test_code_source_promotion import PromotionFixture
from test_deleted_source_proof import load_evidence


class PrProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='pr-progress-')
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.fixture = fixture = PromotionFixture(directory)
        fixture.freeze()
        fixture.git('branch', '-f', 'main', fixture.base)
        fixture.git('checkout', '-qb', 'feat')
        fixture.write('change.txt', 'reviewed\n')
        fixture.git('add', '.')
        fixture.git('commit', '-qm', 'reviewed head')
        self.original_head = fixture.git('rev-parse', 'HEAD')
        scope_path = fixture.session / 'scope.env'
        scope_path.write_text(scope_path.read_text() +
            f"REV_BRANCH=feat\nREV_BASE_BRANCH=main\nREV_PR_NUMBER=71\nREV_PR_REPO=acme/repo\n"
            f"REV_PR_HEAD={self.original_head}\nREV_PR_BASE_HEAD={fixture.base}\nREV_PR_BASE_REF=refs/heads/main\n")
        binary = directory / 'bin'
        binary.mkdir()
        gh = binary / 'gh'
        gh.write_text('#!/bin/sh\ncat ' + shlex.quote(str(directory / 'live.json')) + '\n')
        gh.chmod(0o755)
        self.live_path = directory / 'live.json'
        self.live = dict(number=71, url='https://github.com/acme/repo/pull/71', state='OPEN',
                         headRefName='feat', headRefOid=self.original_head,
                         baseRefName='main', baseRefOid=fixture.base)
        self.write_live()
        self.environment = patch.dict(os.environ, dict(fixture.env, PATH=str(binary) + os.pathsep + os.environ['PATH']))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.module = load_evidence()
        self.prepare('initial')
        self.original = {p.name: p.read_bytes() for p in fixture.session.glob('rinitial-*')}

    def write_live(self):
        self.live_path.write_text(json.dumps(self.live))

    def arguments(self, label, **overrides):
        values = dict(session=str(self.fixture.session), label=label, phase='discovery', head=None,
                      assignment=[], full_seat='sol', plan=None, plan_sha256=None,
                      parent_assignment=None, numeric_round=None, numeric_min_rounds=None, numeric_panel=None,
                      pr_progress_from=None, pr_progress_head=None, pr_progress_live_head=None,
                      pr_progress_tree=None, pr_progress_path=[], pr_progress_reason=None)
        values.update(overrides)
        return argparse.Namespace(**values)

    def prepare(self, label, **overrides):
        with contextlib.redirect_stdout(io.StringIO()):
            self.module.prepare(self.arguments(label, **overrides))
        return json.loads((self.fixture.session / f'r{label}-evidence.manifest.json').read_text())

    def advance(self):
        fixture = self.fixture
        fixture.write('regression.txt', 'required regression\n')
        fixture.git('add', '.')
        fixture.git('commit', '-qm', 'review regression')
        self.live['headRefOid'] = fixture.git('rev-parse', 'HEAD')
        self.write_live()
        fixture.write('change.txt', 'native device correction\n')
        repository = self.module.Repository(fixture.session.resolve())
        tree, _ = repository.snapshot()
        prior = fixture.session / 'rinitial-evidence.manifest.json'
        return dict(pr_progress_from='initial:' + self.module.digest(prior.read_bytes()),
                    pr_progress_head=self.live['headRefOid'], pr_progress_live_head=self.live['headRefOid'],
                    pr_progress_tree=tree, pr_progress_path=['change.txt', 'regression.txt'],
                    pr_progress_reason='Declared controller-owned regression and mandatory device fix.')

    def test_declared_published_head_and_dirty_fix_can_prepare(self):
        values = self.advance()
        try:
            manifest = self.prepare('next', **values)
        except ValueError as error:
            self.fail('declared review-owned progression must compile its descendant and dirty snapshot: ' + str(error))
        self.assertEqual(manifest['snapshot_tree'], values['pr_progress_tree'])
        self.assertIn('pr_progress', manifest)
        self.assertEqual(self.original, {name: (self.fixture.session / name).read_bytes() for name in self.original})


if __name__ == '__main__':
    unittest.main()
