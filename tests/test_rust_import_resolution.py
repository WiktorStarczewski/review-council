"""Rust import obligations follow the declared module and its crate root."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/review-council/scripts/rev-evidence.py'
SPEC = importlib.util.spec_from_file_location('rust_import_evidence', SCRIPT)
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


class RustImportResolutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='rust-import-resolution-')
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.root = directory / 'repo'
        self.session = directory / 'session'
        self.root.mkdir()
        self.session.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(directory / 'no-hooks'))
        self.write('Cargo.toml', '[package]\nname = "fixture_game"\nversion = "0.1.0"\n')
        self.write('src/lib.rs', 'pub mod login_options;\npub mod consumer;\n')
        self.write('src/consumer.rs',
                   'use crate::login_options as options;\n'
                   'pub fn consume() -> usize { options::read_options() }\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       stderr=subprocess.PIPE, text=True).strip()

    def write(self, path, source):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source)

    def freeze(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        base = self.git('rev-parse', 'HEAD')
        (self.session / 'scope.env').write_text(
            f'REV_BASE={shlex.quote(base)}\nREV_ROOT={shlex.quote(str(self.root))}\n'
            'REV_SCOPE=branch\n')
        for name in ('files.txt', 'untracked.txt'):
            (self.session / name).write_text('')
        (self.session / 'roster.json').write_text(json.dumps({'seats': [
            {'seat': seat, 'adapter': 'codex'} for seat in ('sol', 'second', 'third', 'fourth')
        ]}))
        repository = EVIDENCE.Repository(self.session.resolve())
        return repository, repository.entries(repository.tree(base))

    def binding(self, path, entries, repository):
        lines = (self.root / path).read_text().splitlines()
        bindings = EVIDENCE.rust_import_bindings(path, lines, entries, repository)
        self.assertEqual(len(bindings), 1)
        return bindings[0]

    def prepare(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT), 'prepare', str(self.session), '1',
             '--phase', 'discovery', '--full-seat', 'sol'],
            env=dict(os.environ, REV_PATCH_CHUNKS='auto', REV_SOURCE_CONTEXT='1'),
            capture_output=True, text=True, timeout=30)

    def test_single_file_module_does_not_require_absent_mod_rs(self):
        self.write('src/login_options.rs', 'pub fn read_options() -> usize { 1 }\n')
        repository, entries = self.freeze()
        binding = self.binding('src/consumer.rs', entries, repository)
        self.assertEqual(binding['candidate_targets'], ['src/login_options.rs'])
        self.assertTrue(binding['module_alias'])

    def test_directory_module_does_not_require_absent_sibling_rs(self):
        self.write('src/login_options/mod.rs', 'pub fn read_options() -> usize { 1 }\n')
        repository, entries = self.freeze()
        self.assertEqual(self.binding('src/consumer.rs', entries, repository)['candidate_targets'],
                         ['src/login_options/mod.rs'])

    def test_explicit_path_excludes_existing_conventional_module(self):
        self.write('src/lib.rs', '#[path = "chosen.rs"]\npub mod login_options;\n')
        self.write('src/chosen.rs', 'pub fn read_options() -> usize { 1 }\n')
        self.write('src/login_options.rs', 'pub fn unrelated() {}\n')
        repository, entries = self.freeze()
        self.assertEqual(self.binding('src/consumer.rs', entries, repository)['candidate_targets'],
                         ['src/chosen.rs'])

    def test_inline_module_excludes_existing_conventional_module(self):
        self.write('src/lib.rs',
                   'pub mod login_options {\n    pub fn read_options() -> usize { 1 }\n}\n')
        self.write('src/login_options.rs', 'pub fn unrelated() {}\n')
        repository, entries = self.freeze()
        self.assertEqual(self.binding('src/consumer.rs', entries, repository)['candidate_targets'],
                         ['src/lib.rs'])

    def test_missing_declared_module_keeps_unreadable_candidates(self):
        self.write('src/other.rs', 'pub fn read_options() -> usize { 1 }\n')
        repository, entries = self.freeze()
        self.assertEqual(self.binding('src/consumer.rs', entries, repository)['candidate_targets'],
                         ['src/login_options.rs', 'src/login_options/mod.rs'])
        self.write('src/other.rs', 'pub fn read_options() -> usize { 2 }\n')
        process = self.prepare()
        self.assertNotEqual(process.returncode, 0, process.stdout)
        self.assertIn('unreadable import candidates', process.stderr)

    def test_missing_explicit_path_keeps_unreadable_target(self):
        self.write('src/lib.rs', '#[path = "missing.rs"]\npub mod login_options;\n')
        self.write('src/login_options.rs', 'pub fn read_options() -> usize { 1 }\n')
        repository, entries = self.freeze()
        self.assertEqual(self.binding('src/consumer.rs', entries, repository)['candidate_targets'],
                         ['src/missing.rs'])
        self.write('src/login_options.rs', 'pub fn read_options() -> usize { 2 }\n')
        process = self.prepare()
        self.assertNotEqual(process.returncode, 0, process.stdout)
        self.assertIn('unreadable import candidates', process.stderr)

    def test_integration_crate_module_does_not_resolve_to_library_module(self):
        self.write('src/login_options.rs', 'pub fn library_only() {}\n')
        self.write('tests/durable.rs',
                   'mod login_options;\nuse crate::login_options as options;\n'
                   'fn run() { options::exercise(); }\n')
        self.write('tests/login_options/mod.rs', 'pub fn exercise() {}\n')
        repository, entries = self.freeze()
        self.assertEqual(self.binding('tests/durable.rs', entries, repository)['candidate_targets'],
                         ['tests/login_options/mod.rs'])

    def test_integration_child_super_resolves_to_its_crate_root(self):
        self.write('src/login_options.rs', 'pub fn library_only() {}\n')
        self.write('src/support.rs', 'pub fn unrelated() {}\n')
        self.write('src/lib.rs', 'pub mod login_options;\npub mod support;\n')
        self.write('tests/durable.rs',
                   'mod login_options;\npub mod support {\n    pub fn helper() {}\n}\n')
        self.write('tests/login_options/mod.rs',
                   'use super::support as helpers;\npub fn exercise() { helpers::helper(); }\n')
        repository, entries = self.freeze()
        self.assertEqual(self.binding('tests/login_options/mod.rs', entries, repository)[
            'candidate_targets'], ['tests/durable.rs'])

    def test_prepare_retains_real_module_proof_without_phantom_alternate(self):
        self.write('src/login_options.rs', 'pub fn read_options() -> usize { 1 }\n')
        self.freeze()
        self.write('src/login_options.rs', 'pub fn read_options() -> usize { 2 }\n')
        process = self.prepare()
        self.assertEqual(process.returncode, 0, process.stderr)
        facts = json.loads((self.session / 'r1-evidence.json').read_text())
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.rs')
        self.assertEqual(obligation['candidate_targets'], ['src/login_options.rs'])
        self.assertEqual(obligation['unreadable_candidate_targets'], [])
        self.assertTrue(any(row['path'] == 'src/login_options.rs'
                            and row['name'] == 'read_options'
                            for row in obligation['candidate_symbols']))
        manifest = json.loads((self.session / 'r1-evidence.manifest.json').read_text())
        paths = {row['path'] for packet in manifest['source_context']['seats'].values()
                 for shard in packet['shards'] for row in shard['ranges']}
        paths.update(row['path'] for packet in manifest['source_context']['seats'].values()
                     for row in packet['required_source_ranges'])
        self.assertIn('src/consumer.rs', paths)
        self.assertNotIn('src/login_options/mod.rs', paths)


if __name__ == '__main__':
    unittest.main()
