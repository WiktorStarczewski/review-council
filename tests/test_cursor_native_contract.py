"""Native bundle contract fixtures provide no application or live SDK qualification."""

import hashlib
import importlib.util
from pathlib import Path
import shutil
import stat
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CursorNativeContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cursor-native-contract-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.builder = module(REPO / 'scripts/build-cursor-plugin.py')
        self.contract = module(REPO / 'plugins/review-council/scripts/rev-contract-check.py')

    def bundle(self, parent):
        output = parent / 'review-council'
        self.assertEqual(self.builder.build(output), output)
        self.assertTrue((output / '.cursor-plugin/plugin.json').is_file())
        self.assertFalse((output / '.codex-plugin').exists())
        self.assertFalse((output / '.claude-plugin').exists())
        return output

    def test_cursor_only_bundle_root_is_a_contract_subject(self):
        output = self.bundle(self.root / 'standalone')
        self.assertEqual(self.contract.source_plugin(output), (output, ''),
                         'native Cursor bundles must not bypass contract replay as unrelated')

    def test_nested_cursor_only_bundle_is_a_contract_subject(self):
        source = self.root / 'repository'
        output = self.bundle(source / 'plugins')
        self.assertEqual(self.contract.source_plugin(source),
                         (output, 'plugins/review-council/'),
                         'nested native Cursor bundles need the repository-relative prefix')

    def test_builder_refuses_its_canonical_source_without_removing_other_hosts(self):
        source = self.root / 'source'
        for relative in ('scripts', 'docs', 'plugins/review-council'):
            shutil.copytree(REPO / relative, source / relative,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'node_modules',
                                                          '.archives', '.qualification-key'))
        shutil.copy2(REPO / 'LICENSE', source / 'LICENSE')
        plugin = source / 'plugins/review-council'
        before = {path.relative_to(plugin).as_posix():
                  (stat.S_IMODE(path.stat().st_mode), path.read_bytes())
                  for path in plugin.rglob('*') if path.is_file()}
        for required in ('.claude-plugin/plugin.json', '.claude-plugin/hooks.json',
                         '.codex-plugin/plugin.json', '.cursor-plugin/plugin.json',
                         'skills/rev/SKILL.md', 'codex-skills/rev/SKILL.md',
                         'cursor-skills/rev/SKILL.md', 'hooks/session-start'):
            self.assertIn(required, before)
        builder = module(source / 'scripts/build-cursor-plugin.py')
        with self.assertRaises(ValueError,
                               msg='a generated bundle cannot replace the canonical source tree'):
            builder.build(plugin)
        after = {path.relative_to(plugin).as_posix():
                 (stat.S_IMODE(path.stat().st_mode), path.read_bytes())
                 for path in plugin.rglob('*') if path.is_file()}
        self.assertEqual(after, before, 'all original host manifests, skills and hooks must survive')

    def test_native_host_changes_select_replay_and_change_input_hashes(self):
        output = self.bundle(self.root / 'boundaries')
        for relative in ('.cursor-plugin/plugin.json', 'cursor-skills/rev/SKILL.md',
                         'cursor-skills/stack/SKILL.md', 'docs/cursor-review-workflow.md',
                         'docs/cursor-stack-workflow.md'):
            with self.subTest(path=relative):
                for prefix in ('', 'plugins/review-council/'):
                    self.assertTrue(self.contract.is_boundary(prefix + relative, prefix),
                                    'native host inputs must select contract replay: ' + relative)
                path = output / relative
                original = path.read_bytes()
                before = self.contract.file_hashes(output)
                self.assertEqual(before.get(relative), {
                    'sha256': hashlib.sha256(original).hexdigest(),
                    'mode': stat.S_IMODE(path.stat().st_mode),
                }, 'the contract fingerprint must bind the native host input')
                path.write_bytes(original + b'\n')
                after = self.contract.file_hashes(output)
                self.assertEqual(after.get(relative), {
                    'sha256': hashlib.sha256(original + b'\n').hexdigest(),
                    'mode': stat.S_IMODE(path.stat().st_mode),
                })
                self.assertNotEqual(before[relative], after[relative],
                                    'changed native instructions must invalidate contract reuse')
                path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
