"""Search result limiters must retain their producer's output contract."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


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
        self.session = self.directory / 'session'
        self.session.mkdir()
        self.prompt = self.session / 'r1-opus.prompt.md'
        self.prompt.write_text(
            'Immutable plan snapshot SHA-256: ' + 'a' * 64 + '\n'
            'Evidence manifest SHA-256: ' + 'b' * 64 + '\n')
        self.args = SimpleNamespace(root=str(self.root), session=str(self.session),
                                    prompt=str(self.prompt), deps=None)

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


    def invoke(self, phase, name, data, response='needle\n'):
        event = {'tool_name': name, 'tool_input': data, 'tool_response': response}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(event))), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = getattr(self.audit, phase)(self.args)
        return status, stdout.getvalue(), stderr.getvalue()

    def assert_outcome(self, phase, name, data, code=None, response='needle\n'):
        status, stdout, stderr = self.invoke(phase, name, data, response)
        if code is None:
            self.assertEqual((status, stdout, stderr), (0, '', ''))
        elif phase == 'hook':
            self.assertEqual(status, 2)
            self.assertIn('review read blocked: ' + code, stderr)
        else:
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(stdout), {
                'continue': False, 'stopReason': 'review read blocked: ' + code})
            self.assertIn('review read blocked: ' + code, stderr)

    def test_native_hooks_enforce_bounds_without_loading_the_evidence_graph(self):
        read = {'file_path': str(self.root / 'source.txt'), 'offset': 1, 'limit': 40}
        search = {'path': str(self.root), 'pattern': 'needle', 'head_limit': 80}
        cases = [
            ('Read', read, None),
            ('Grep', search, None),
            ('Read', {**read, 'limit': 41}, 'unbounded-read'),
            ('Read', {'file_path': read['file_path'], 'limit': 40}, 'unbounded-read'),
            ('Read', {**read, 'file_path': str(self.directory / 'outside.txt')},
             'path-outside-scope'),
            ('Read', {**read, 'file_path': str(self.session / 'r1-other.prompt.md')},
             'unnamed-session-artifact'),
            ('Grep', {**search, 'head_limit': 81}, 'unbounded-search'),
        ]
        with patch.object(self.audit, 'load_evidence_manifest', side_effect=AssertionError(
                'native hooks must not reconstruct the evidence graph')):
            for phase in ('hook', 'post_hook'):
                for name, data, code in cases:
                    with self.subTest(phase=phase, name=name, code=code):
                        self.assert_outcome(phase, name, data, code)

    def test_native_post_hook_keeps_output_guards_without_loading_the_evidence_graph(self):
        read = {'file_path': str(self.root / 'source.txt'), 'offset': 1, 'limit': 40}
        search = {'path': str(self.root), 'pattern': 'needle', 'head_limit': 80}
        with patch.object(self.audit, 'load_evidence_manifest', side_effect=AssertionError(
                'native hooks must not reconstruct the evidence graph')):
            self.assert_outcome('post_hook', 'Read', read, 'tool-output-too-large',
                                'x' * (self.audit.OUTPUT_BYTES + 1))
            self.assert_outcome('post_hook', 'Grep', search, 'discovery-output-too-large',
                                'needle\n' * 81)
            self.assert_outcome('post_hook', 'Read', read, 'unsupported-hook-response', {})

    def test_shell_hooks_keep_exact_plan_search_authorization(self):
        command = "rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'needle' . | head -81"
        for phase in ('hook', 'post_hook'):
            for name in self.audit.SHELL_TOOLS:
                with self.subTest(phase=phase, name=name), patch.object(
                        self.audit, 'prompt_plan_search_commands', return_value={command}):
                    self.assert_outcome(phase, name, {'command': command})
                    self.assert_outcome(phase, name, {'command': command + ' '},
                                        'unbounded-shell-output')


if __name__ == '__main__':
    unittest.main()
