"""Changed imports retain declaration files and deleted public callers."""
from pathlib import Path
import tempfile
import unittest

from test_code_source_promotion import PromotionFixture
from test_deleted_source_proof import load_evidence


class ImportSourceRootsTests(unittest.TestCase):
    def test_typescript_import_resolves_declaration_file(self):
        evidence = load_evidence()
        entries = {'generated/api.d.ts': ('100644', 'a' * 40)}
        self.assertEqual(evidence.resolve_import_candidates(
            'src/consumer.ts', '../generated/api', entries), ['generated/api.d.ts'])

    def test_surviving_python_import_retains_deleted_public_caller(self):
        with tempfile.TemporaryDirectory(prefix='deleted-public-import-') as directory:
            fixture = PromotionFixture(Path(directory))
            fixture.write('deleted.py', 'def gone(value):\n    return value + 1\n')
            fixture.write('caller.py', 'from deleted import gone\nresult = gone(1)\n')
            fixture.freeze()
            (fixture.root / 'deleted.py').unlink()
            evidence = load_evidence()
            repository = evidence.Repository(fixture.session.resolve())
            snapshot, unsafe = repository.snapshot()
            self.assertEqual(unsafe, [])
            base_tree = repository.tree(fixture.base)
            _, hunks, categories, _ = repository.changes(base_tree, snapshot)
            facts = evidence.facts(repository, snapshot, hunks, categories, base_tree)
            self.assertTrue(any(row['path'] == 'caller.py' and row['name'] == 'gone'
                                for row in facts['call_sites']), facts['call_sites'])


if __name__ == '__main__':
    unittest.main()
