"""The publisher consumes exact certified PR progression without widening drift."""
import importlib.util
import argparse
import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

import test_pr_progress as progress_tests
from test_deleted_source_proof import SCRIPTS


def publisher_module():
    spec = importlib.util.spec_from_file_location('pr_progress_publisher', SCRIPTS / 'rev-pr-review.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrProgressPublisherTests(unittest.TestCase):
    def test_clean_certified_head_is_not_rejected_as_initial_head_drift(self):
        fixture_case = progress_tests.PrProgressTests()
        self.addCleanup(fixture_case.doCleanups)
        fixture_case.setUp()
        fixture_case.advance()
        fixture = fixture_case.fixture
        fixture.git('add', '.')
        fixture.git('commit', '-qm', 'reviewed fix')
        head = fixture.git('rev-parse', 'HEAD')
        fixture_case.live['headRefOid'] = head
        fixture_case.write_live()
        publisher = publisher_module()
        scope = publisher.parse_scope(fixture.session / 'scope.env')
        with patch.object(publisher, 'certified_pr_progress_head', return_value=head, create=True), \
                patch.object(publisher, 'remote_merge_base', return_value=fixture.base):
            try:
                target = publisher.resolve_pr(scope, ['acme/repo'])
            except publisher.ReviewError as error:
                self.fail('the exact clean certified PR progression must resolve for publication: ' + str(error))
        self.assertEqual(target['head'], head)


    def certified_fixture(self):
        case = progress_tests.PrProgressTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        values = case.advance()
        fixture = case.fixture
        fixture.git('add', '.')
        fixture.git('commit', '-qm', 'local final fix')
        head = fixture.git('rev-parse', 'HEAD')
        values['pr_progress_head'] = head
        assignments = [seat + '=' + bundle for seat, bundle in zip(
            ('sol', 'second', 'third', 'fourth'), case.module.BUNDLES)]
        manifest = case.prepare('certified', phase='verification', full_seat='fourth',
                                assignment=assignments, **values)
        fixture.label = 'certified'
        fixture.phase = 'verification'
        fixture.manifest_path = fixture.session / 'rcertified-evidence.manifest.json'
        fixture.manifest = manifest
        fixture.env = dict(os.environ)
        for seat, assignment in manifest['assignments'].items():
            fixture.seat = seat
            fixture.context = manifest['source_context']['seats'][seat]
            result = subprocess.run([str(SCRIPTS / 'rev-prompt.sh'), str(fixture.session),
                                     fixture.label, seat, assignment['bundle'], 'certified progression',
                                     '--evidence', str(fixture.manifest_path)],
                                    env=fixture.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            fixture.prompt = Path(result.stdout.strip())
            code, audit = fixture.audit()
            self.assertEqual(code, 0, audit)
            (fixture.session / f'rcertified-{seat}.exit').write_text('0\n')
        with contextlib.redirect_stdout(io.StringIO()):
            case.module.receipt(argparse.Namespace(session=str(fixture.session), label='certified', replacement=[]))
        self.assertTrue(case.module.current_coverage_data(fixture.session)['eligible'])
        return case, publisher_module(), head

    def test_real_coverage_accepts_only_exact_clean_published_head(self):
        case, publisher, head = self.certified_fixture()
        scope = publisher.parse_scope(case.fixture.session / 'scope.env')
        with patch.object(publisher, 'remote_merge_base', return_value=case.fixture.base):
            with self.assertRaises(publisher.ReviewError):
                publisher.resolve_pr(scope, ['acme/repo'])
            record_path = case.fixture.session / 'rcertified-pr-progress.json'
            original = record_path.read_bytes()
            case.live['headRefOid'] = head
            case.write_live()
            self.assertEqual(publisher.resolve_pr(scope, ['acme/repo'])['head'], head)
            self.assertEqual(record_path.read_bytes(), original)
            case.fixture.write('change.txt', 'dirty publication refused\n')
            with self.assertRaises(publisher.ReviewError):
                publisher.resolve_pr(scope, ['acme/repo'])

    def test_missing_receipt_mutated_record_and_other_descendant_refuse(self):
        case, publisher, head = self.certified_fixture()
        scope = publisher.parse_scope(case.fixture.session / 'scope.env')
        case.live['headRefOid'] = head
        case.write_live()
        with patch.object(publisher, 'remote_merge_base', return_value=case.fixture.base):
            pointer = case.fixture.session / 'coverage-head.json'
            raw = pointer.read_bytes()
            pointer.unlink()
            with self.assertRaises(publisher.ReviewError):
                publisher.resolve_pr(scope, ['acme/repo'])
            pointer.write_bytes(raw)
            record = case.fixture.session / 'rcertified-pr-progress.json'
            original = record.read_bytes()
            record.write_bytes(original + b' ')
            with self.assertRaises(publisher.ReviewError):
                publisher.resolve_pr(scope, ['acme/repo'])
            record.write_bytes(original)
            case.fixture.git('commit', '--allow-empty', '-qm', 'another head with identical tree')
            case.live['headRefOid'] = case.fixture.git('rev-parse', 'HEAD')
            case.write_live()
            with self.assertRaises(publisher.ReviewError):
                publisher.resolve_pr(scope, ['acme/repo'])


    def test_semantic_rejection_revokes_progressed_publication_without_rebinding_history(self):
        case, publisher, head = self.certified_fixture()
        case.live['headRefOid'] = head
        case.write_live()
        fixture = case.fixture
        scope = publisher.parse_scope(fixture.session / 'scope.env')
        manifest_path = fixture.session / 'rcertified-evidence.manifest.json'
        manifest, manifest_hash = case.module.validated_manifest(manifest_path)
        _, generation = case.module.result_generation(fixture.session, manifest, manifest_hash, 'sol')
        preserved = {name: (fixture.session / name).read_bytes() for name in (
            'rcertified-evidence.manifest.json', 'rcertified-pr-progress.json',
            'rcertified-coverage.receipt.json')}
        with contextlib.redirect_stdout(io.StringIO()):
            case.module.reject_result(argparse.Namespace(session=str(fixture.session), label='certified', seat='sol',
                manifest_sha256=generation['manifest_sha256'], prompt_sha256=generation['prompt_sha256'],
                result_sha256=generation['result_sha256'], obligation='Read the entire assigned patch',
                evidence='checked', reason='A mandatory assertion check was omitted in this regression fixture.'))
        self.assertFalse(case.module.current_coverage_data(fixture.session)['eligible'])
        with patch.object(publisher, 'remote_merge_base', return_value=fixture.base), self.assertRaises(publisher.ReviewError):
            publisher.resolve_pr(scope, ['acme/repo'])
        self.assertEqual(preserved, {name: (fixture.session / name).read_bytes() for name in preserved})


if __name__ == '__main__':
    unittest.main()
