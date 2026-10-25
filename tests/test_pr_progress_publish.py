"""The publisher consumes exact certified PR progression without widening drift."""
import importlib.util
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


if __name__ == '__main__':
    unittest.main()
