"""Search result limiters must retain their producer's output contract."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
AUDITOR = REPO / 'plugins/review-council/scripts/lib/review-read-audit.py'


class SearchPipelineBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('search_pipeline_audit', AUDITOR)
        cls.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.audit)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='search-pipeline-bounds-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.root = self.directory / 'repo'
        self.root.mkdir()
        (self.root / 'source.txt').write_text('needle\n' * 100)

    def codes(self, command, plan_search_commands=None):
        return [item['code'] for item in self.audit.shell_violations(
            command, [self.root], self.root, None, read_limit=40,
            plan_search_commands=plan_search_commands)]

    def test_search_result_limiter_accepts_eighty_lines(self):
        self.assertEqual(self.codes('rg -n -- needle . | head -80'), [])

    def test_compiler_search_sentinel_accepts_eighty_one_lines(self):
        command = "rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'needle' . | head -81"
        self.assertEqual(self.codes(command, {command}), [])

    def test_search_sentinel_requires_the_exact_assigned_plan_command(self):
        command = "rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'needle' . | head -81"
        self.assertEqual(self.codes(command), ['unbounded-shell-output'])
        self.assertEqual(self.codes(command, {command + ' '}), ['unbounded-shell-output'])

    def test_search_result_limiter_rejects_more_than_the_sentinel(self):
        self.assertEqual(self.codes('rg -n -- needle . | head -82'),
                         ['unbounded-shell-output'])

    def test_source_pipeline_does_not_inherit_the_search_sentinel(self):
        self.assertEqual(self.codes('cat source.txt | head -81'),
                         ['unbounded-shell-output'])

    def test_search_limiter_with_a_file_operand_remains_a_source_read(self):
        self.assertEqual(self.codes('rg -n -- needle . | head -81 source.txt'),
                         ['unbounded-shell-output'])

    def test_source_pipeline_retains_the_forty_line_limit(self):
        self.assertEqual(self.codes('cat source.txt | head -40'), [])
        self.assertEqual(self.codes('cat source.txt | head -41'),
                         ['unbounded-shell-output'])

    def test_direct_source_read_retains_the_forty_line_limit(self):
        self.assertEqual(self.codes('head -40 source.txt'), [])
        self.assertEqual(self.codes('head -41 source.txt'),
                         ['unbounded-shell-output'])

    def test_discovery_limiter_accepts_eighty_lines(self):
        self.assertEqual(self.codes('find . -type f | head -80'), [])

    def test_discovery_limiter_does_not_inherit_the_search_sentinel(self):
        self.assertEqual(self.codes('find . -type f | head -81'),
                         ['unbounded-shell-output'])

    def test_search_limit_does_not_bypass_scope_checks(self):
        self.assertEqual(self.codes('rg -n -- needle ../ | head -81'),
                         ['path-outside-scope'])

    def test_search_limit_does_not_allow_separate_source_batches(self):
        self.assertEqual(self.codes('rg -n -- needle . | head -81; head -40 source.txt'),
                         ['unsupported-source-batch'])


if __name__ == '__main__':
    unittest.main()
