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
        fixture.git('checkout', '-qb', 'feat')
        fixture.git('branch', '-f', 'main', fixture.base)
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


    def test_undeclared_head_and_dirty_changes_still_refuse(self):
        self.advance()
        with self.assertRaisesRegex(ValueError, 'checked out HEAD does not match pinned PR'):
            self.prepare('undeclared')

    def test_exact_declared_paths_and_expected_identities_are_required(self):
        values = self.advance()
        for key, value in (
                ('pr_progress_path', ['regression.txt']),
                ('pr_progress_head', self.original_head),
                ('pr_progress_live_head', self.original_head),
                ('pr_progress_tree', self.fixture.base),
                ('pr_progress_from', 'initial:' + '0' * 64)):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.prepare('bad-' + key.replace('_', '-'), **dict(values, **{key: value}))
        self.assertFalse(list(self.fixture.session.glob('rbad-*-evidence.manifest.json')))

    def test_live_identity_and_base_guards_remain_strict(self):
        values = self.advance()
        for field, value in (('state', 'CLOSED'), ('headRefName', 'other'),
                             ('headRefOid', '9' * 40), ('baseRefName', 'next'),
                             ('baseRefOid', self.original_head)):
            old = self.live[field]
            self.live[field] = value
            self.write_live()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare('drift-' + field, **values)
            self.live[field] = old
        self.write_live()

    def test_staged_only_and_untracked_paths_cannot_be_omitted(self):
        values = self.advance()
        self.fixture.write('index-only.txt', 'staged correction\n')
        self.fixture.git('add', 'index-only.txt')
        (self.fixture.root / 'index-only.txt').unlink()
        self.fixture.write('untracked.txt', 'untracked correction\n')
        repository = self.module.Repository(self.fixture.session.resolve())
        tree, _ = repository.snapshot()
        with self.assertRaises(ValueError):
            self.prepare('missing-index-path', **dict(values, pr_progress_tree=tree))
        paths = values['pr_progress_path'] + ['index-only.txt', 'untracked.txt']
        manifest = self.prepare('full-index-paths', **dict(values, pr_progress_tree=tree, pr_progress_path=paths))
        self.assertEqual(manifest['snapshot_tree'], tree)

    def test_historical_binding_survives_later_changes_but_fresh_validation_refuses(self):
        values = self.advance()
        manifest = self.prepare('bound', **values)
        path = self.fixture.session / 'rbound-evidence.manifest.json'
        original = path.read_bytes()
        self.module.validated_manifest(path)
        with self.assertRaises(ValueError):
            self.prepare('bound', **dict(values, pr_progress_reason='different declaration'))
        self.assertEqual(path.read_bytes(), original)
        self.fixture.write('change.txt', 'later drift\n')
        with self.assertRaises(ValueError):
            self.module.validated_manifest(path)
        self.module.validated_manifest(path, fresh=False)
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(ValueError):
            self.prepare('bound', **dict(values, pr_progress_reason='different declaration'))
        self.assertEqual(path.read_bytes(), original)
        binding = manifest['pr_progress']
        record = self.fixture.session / binding['artifact']
        retained = record.with_suffix('.retained')
        record.rename(retained)
        record.symlink_to(retained.name)
        with self.assertRaises(ValueError):
            self.module.validated_manifest(path, fresh=False)


    def test_cli_requires_complete_explicit_declaration(self):
        import subprocess
        from test_deleted_source_proof import SCRIPTS
        values = self.advance()
        options = [part for key, value in values.items()
                   for item in (value if isinstance(value, list) else [value])
                   for part in ('--' + key.replace('_', '-'), item)]
        result = subprocess.run(['python3', str(SCRIPTS / 'rev-evidence.py'), 'prepare',
                                 str(self.fixture.session), 'cli', '--phase', 'discovery',
                                 '--full-seat', 'sol', *options], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(['python3', str(SCRIPTS / 'rev-evidence.py'), 'prepare',
                                 str(self.fixture.session), 'partial', '--phase', 'discovery',
                                 '--full-seat', 'sol', '--pr-progress-head', values['pr_progress_head']],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('complete explicit PR progression', result.stderr)


    def test_inspection_reports_modes_without_touching_index_or_generations(self):
        import subprocess
        from test_deleted_source_proof import SCRIPTS
        values = self.advance()
        index = self.fixture.root / self.fixture.git('rev-parse', '--git-path', 'index')
        before_index = index.read_bytes()
        before = set(self.fixture.session.glob('r*-*'))
        result = subprocess.run(['python3', str(SCRIPTS / 'rev-evidence.py'), 'pr-progress-inspect',
                                 str(self.fixture.session), '--from', values['pr_progress_from'],
                                 '--live-head', values['pr_progress_live_head']], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed['snapshot_tree'], values['pr_progress_tree'])
        self.assertEqual(observed['paths'], sorted(values['pr_progress_path']))
        self.assertEqual(observed['changes'][0]['snapshot'][0], '100644')
        self.assertEqual(index.read_bytes(), before_index)
        self.assertEqual(set(self.fixture.session.glob('r*-*')), before)

    def test_unfinished_provider_launch_refuses_progression(self):
        values = self.advance()
        self.attempt_call('reserve', 'a' * 32)
        with self.assertRaisesRegex(ValueError, 'unfinished provider launch'):
            self.prepare('active', **values)


    def test_forged_prior_binding_is_rejected_even_with_rehashed_record(self):
        values = self.advance()
        manifest = self.prepare('forged', **values)
        path = self.fixture.session / 'rforged-evidence.manifest.json'
        name = manifest['pr_progress']['artifact']
        record_path = self.fixture.session / name
        record = json.loads(record_path.read_text())
        record['prior'] = 'initial:' + '0' * 64
        raw = self.module.encoded(record)
        record_path.write_bytes(raw)
        manifest['pr_progress']['sha256'] = self.module.digest(raw)
        manifest['artifacts'][name] = dict(sha256=self.module.digest(raw), words=len(raw.split()))
        path.write_bytes(self.module.encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'prior manifest hash mismatch'):
            self.module.validated_manifest(path, fresh=False)

    def test_mode_only_change_requires_declaration(self):
        values = self.advance()
        self.fixture.git('config', 'core.filemode', 'true')
        (self.fixture.root / 'unchanged.txt').chmod(0o755)
        tree, _ = self.module.Repository(self.fixture.session.resolve()).snapshot()
        with self.assertRaises(ValueError):
            self.prepare('missing-mode', **dict(values, pr_progress_tree=tree))
        manifest = self.prepare('declared-mode', **dict(values, pr_progress_tree=tree,
            pr_progress_path=values['pr_progress_path'] + ['unchanged.txt']))
        record = json.loads((self.fixture.session / manifest['pr_progress']['artifact']).read_text())
        row = next(row for row in record['changes'] if row['path'] == 'unchanged.txt')
        self.assertEqual(row['prior'][0], '100644')
        self.assertEqual(row['snapshot'][0], '100755')


    def test_only_exact_declared_head_may_catch_up_without_rebinding_observation(self):
        values = self.advance()
        self.fixture.git('add', '.')
        self.fixture.git('commit', '-qm', 'local reviewed fix')
        local_head = self.fixture.git('rev-parse', 'HEAD')
        values['pr_progress_head'] = local_head
        manifest = self.prepare('before-push', **values)
        record_path = self.fixture.session / manifest['pr_progress']['artifact']
        original = record_path.read_bytes()
        self.live['headRefOid'] = local_head
        self.write_live()
        self.module.validated_manifest(self.fixture.session / 'rbefore-push-evidence.manifest.json')
        self.assertEqual(record_path.read_bytes(), original)
        self.assertNotEqual(json.loads(original)['live_head'], local_head)
        with self.assertRaises(ValueError):
            self.prepare('stale-observation', **values)
        self.fixture.git('commit', '--allow-empty', '-qm', 'another descendant with the same tree')
        self.live['headRefOid'] = self.fixture.git('rev-parse', 'HEAD')
        self.write_live()
        with self.assertRaises(ValueError):
            self.module.validated_manifest(self.fixture.session / 'rbefore-push-evidence.manifest.json')


    def attempt_call(self, command, token=None, code=None):
        import subprocess
        from test_deleted_source_proof import SCRIPTS
        prompt = self.fixture.session / 'rinitial-sol.prompt.md'
        if not prompt.exists():
            prompt.write_text('Canonical launch lifecycle fixture.\n')
        arguments = ['python3', str(SCRIPTS / 'lib/rev-attempt.py'), command,
                     str(self.fixture.session), 'initial', 'sol', str(prompt)]
        if code is not None:
            arguments.append(str(code))
        if token is not None:
            arguments.append(token)
        return subprocess.run(arguments, capture_output=True, text=True)

    def lifecycle_record(self):
        prompt = self.fixture.session / 'rinitial-sol.prompt.md'
        path, _ = self.module.attempt_module().record_path(self.fixture.session, 'initial', 'sol', prompt)
        return path, json.loads(path.read_text())

    def test_pending_metadata_without_any_launch_allows_progression(self):
        values = self.advance()
        (self.fixture.session / 'state.json').write_text(json.dumps(dict(
            phase='plan', round='6p', seats=['sol', 'second', 'third', 'fourth'])))
        manifest = self.prepare('zero-launches', **values)
        self.assertIn('pr_progress', manifest)

    def test_bound_terminal_tracks_internal_retries_and_lost_raw_exit(self):
        values = self.advance()
        token = 'a' * 32
        self.assertEqual(self.attempt_call('reserve', token).returncode, 0)
        self.assertEqual(self.attempt_call('reserve', token).returncode, 0)
        self.assertEqual(self.attempt_call('record', token, 2).returncode, 0)
        path, record = self.lifecycle_record()
        self.assertEqual((record['calls'], record['launches'], record['completed_calls']), (2, [2], 2))
        original = path.read_bytes()
        (self.fixture.session / 'rinitial-sol.stream.ndjson').write_text('')
        self.assertFalse((self.fixture.session / 'rinitial-sol.exit').exists())
        self.prepare('terminal-lost-exit', **values)
        self.assertEqual(path.read_bytes(), original)

    def test_duplicate_stale_and_concurrent_tokens_cannot_finish_a_new_reservation(self):
        values = self.advance()
        first, second = 'a' * 32, 'b' * 32
        self.assertEqual(self.attempt_call('reserve', first).returncode, 0)
        self.assertNotEqual(self.attempt_call('reserve', second).returncode, 0)
        self.assertEqual(self.attempt_call('record', first, 2).returncode, 0)
        path, _ = self.lifecycle_record()
        completed = path.read_bytes()
        self.assertNotEqual(self.attempt_call('record', first, 2).returncode, 0)
        self.assertEqual(path.read_bytes(), completed)
        self.assertEqual(self.attempt_call('reserve', second).returncode, 0)
        reserved = path.read_bytes()
        self.assertNotEqual(self.attempt_call('record', first, 2).returncode, 0)
        self.assertEqual(path.read_bytes(), reserved)
        with self.assertRaisesRegex(ValueError, 'unfinished provider launch'):
            self.prepare('active-second', **values)
        self.assertEqual(self.attempt_call('record', second, 0).returncode, 0)
        self.prepare('completed-second', **values)

    def test_legacy_managed_terminal_requires_matching_exit_and_unambiguous_counts(self):
        values = self.advance()
        self.assertEqual(self.attempt_call('reserve').returncode, 0)
        self.assertEqual(self.attempt_call('record', code=2).returncode, 0)
        path, record = self.lifecycle_record()
        original = path.read_bytes()
        exit_path = self.fixture.session / 'rinitial-sol.exit'
        with self.assertRaisesRegex(ValueError, 'matching terminal exit'):
            self.prepare('legacy-missing-exit', **values)
        exit_path.write_text('0\n')
        with self.assertRaisesRegex(ValueError, 'matching terminal exit'):
            self.prepare('legacy-wrong-exit', **values)
        exit_path.write_text('2\n')
        self.prepare('legacy-managed-complete', **values)
        self.assertEqual(path.read_bytes(), original)
        record['calls'] = 2
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'ambiguous legacy'):
            self.prepare('legacy-ambiguous', **values)


if __name__ == '__main__':
    unittest.main()
