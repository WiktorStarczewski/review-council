"""Changed imports retain declaration files and deleted public callers."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

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

class MemoryRepository:
    def __init__(self, files):
        self.files = {path: body if isinstance(body, bytes) else body.encode()
                      for path, body in files.items()}

    def scoped(self, path):
        return True

    def entries(self, tree):
        return {path: ('100644', path) for path in self.files}

    def blob(self, entry):
        return self.files[entry[1]]

    def iter_blobs(self, entries):
        return ((path, self.blob(entry)) for path, entry in entries.items())


class ImportCandidateIdentityTests(unittest.TestCase):
    def facts(self, files, *changed, evidence=None):
        evidence = evidence or load_evidence()
        repository = MemoryRepository(files)
        hunks = [{'path': path, 'changed_lines': [1]} for path in changed]
        return evidence.facts(repository, 'snapshot', hunks, {path: 'code' for path in changed})

    def test_resolved_import_does_not_borrow_an_unrelated_changed_export(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/consumer.ts': 'import { useAccount } from "./hooks";\nuseAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'visual/fixture.tsx')
        self.assertFalse(any(row['target'] == 'visual/fixture.tsx'
                             and row['source'] == 'src/consumer.ts'
                             for row in facts['dependencies']), facts)
        self.assertFalse(any(row['path'] == 'src/consumer.ts'
                             for row in facts['unresolved_imports'] + facts['call_sites']), facts)
        self.assertIn({'source': 'src/consumer.ts', 'target': 'src/hooks.ts',
                       'kind': 'local-import'}, facts['dependencies'])

    def test_true_consumer_keeps_exact_changed_module_with_name_collision(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/consumer.ts': 'import { useAccount } from "./hooks";\nuseAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        self.assertTrue(any(row['path'] == 'src/consumer.ts' for row in facts['call_sites']), facts)
        self.assertFalse(any(row['source'] == 'src/consumer.ts'
                             and row['target'] == 'visual/fixture.tsx'
                             for row in facts['dependencies']), facts)

    def test_unresolved_named_import_retains_search_obligation(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/consumer.ts': 'import { useAccount } from "missing-hooks";\nuseAccount();\n',
        }, 'src/hooks.ts')
        self.assertTrue(any(row['path'] == 'src/consumer.ts'
                            and row['candidate_targets'] == ['src/hooks.ts']
                            for row in facts['unresolved_imports']), facts)
        self.assertTrue(any(row.get('resolution') == 'unresolved import search required'
                            for row in facts['call_sites']), facts)

    def test_namespace_member_does_not_borrow_from_another_resolved_module(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/consumer.ts': 'import * as hooks from "./hooks";\nhooks.useAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'visual/fixture.tsx')
        self.assertFalse(any(row['path'] == 'src/consumer.ts'
                             for row in facts['unresolved_imports'] + facts['call_sites']), facts)
        self.assertFalse(any(row['source'] == 'src/consumer.ts'
                             and row['target'] == 'visual/fixture.tsx'
                             for row in facts['dependencies']), facts)

    def test_missing_namespace_import_keeps_qualified_search(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/consumer.ts': 'import * as hooks from "missing-hooks";\nhooks.useAccount();\n',
        }, 'src/hooks.ts')
        self.assertTrue(any(row['path'] == 'src/consumer.ts'
                            for row in facts['unresolved_imports']), facts)
        self.assertTrue(any(row.get('local_name') == 'hooks.useAccount'
                            for row in facts['call_sites']), facts)

    def test_wildcard_barrel_keeps_the_exact_export_route(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': 'export * from "./exports";\n',
            'src/exports.ts': 'export * from "./hooks";\n',
            'src/consumer.ts': 'import { useAccount } from "./index";\nuseAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertEqual({row['path'] for row in obligation['candidate_route_symbols']},
                         {'src/index.ts', 'src/exports.ts'})
        self.assertNotIn('visual/fixture.tsx', obligation['candidate_targets'])
        self.assertTrue(any(row['path'] == 'src/consumer.ts' for row in facts['call_sites']), facts)

    def test_named_barrel_keeps_only_its_actual_export_route(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': 'export { useAccount } from "./hooks";\n',
            'src/consumer.ts': 'import { useAccount } from "./index";\nuseAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        self.assertTrue(any(row['path'] == 'src/consumer.ts' for row in facts['call_sites']), facts)
        self.assertIn({'source': 'src/index.ts', 'target': 'src/hooks.ts',
                       'kind': 'local-import'}, facts['dependencies'])
        self.assertFalse(any(row['source'] == 'src/consumer.ts'
                             and row['target'] == 'visual/fixture.tsx'
                             for row in facts['dependencies']), facts)

    def test_named_barrel_route_work_is_bounded_per_snapshot(self):
        evidence = load_evidence()
        consumers = {f'src/consumer{index}.ts' for index in range(32)}
        files = {
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': 'export { useAccount } from "./exports";\n',
            'src/exports.ts': 'export { useAccount } from "./hooks";\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
            **{path: 'import { useAccount } from "./index";\nuseAccount();\n'
               for path in consumers},
        }
        changed = ('src/hooks.ts', 'visual/fixture.tsx')
        with mock.patch.object(evidence, 'ts_reexport_references',
                               wraps=evidence.ts_reexport_references) as traversals:
            facts = self.facts(files, *changed, evidence=evidence)
            self.assertEqual({row['path'] for row in facts['call_sites']
                              if row['name'] == 'useAccount'}, consumers)
            obligations = {row['path']: row for row in facts['unresolved_imports']
                           if row['path'] in consumers}
            self.assertEqual(set(obligations), consumers)
            for path, obligation in obligations.items():
                self.assertEqual({row['path'] for row in obligation['candidate_symbols']},
                                 {'src/hooks.ts', 'src/index.ts', 'src/exports.ts'})
                self.assertNotIn('visual/fixture.tsx', obligation['candidate_targets'])
                self.assertIn({'source': path, 'target': 'src/hooks.ts',
                               'kind': 'ambiguous-import'}, facts['dependencies'])
                self.assertIn({'source': path, 'target': 'src/index.ts',
                               'kind': 'local-import'}, facts['dependencies'])
            self.assertIn({'source': 'src/index.ts', 'target': 'src/exports.ts',
                           'kind': 'local-import'}, facts['dependencies'])
            self.assertIn({'source': 'src/exports.ts', 'target': 'src/hooks.ts',
                           'kind': 'local-import'}, facts['dependencies'])
            self.assertLessEqual(traversals.call_count, 12,
                                 'shared named-barrel routes were traversed again per consumer')
            snapshots = [(dict(files), facts)]

            files['src/exports.ts'] = 'export { useAccount } from "../visual/fixture";\n'
            traversals.reset_mock()
            facts = self.facts(files, *changed, evidence=evidence)
            for obligation in facts['unresolved_imports']:
                if obligation['path'] in consumers:
                    self.assertIn('visual/fixture.tsx', obligation['candidate_targets'])
                    self.assertNotIn('src/hooks.ts', obligation['candidate_targets'])
            self.assertEqual({row['path'] for row in facts['call_sites']
                              if row['name'] == 'useAccount'}, consumers)
            self.assertLessEqual(traversals.call_count, 12)
            snapshots.append((dict(files), facts))

            files['src/index.ts'] += 'export * from "./missing";\n'
            traversals.reset_mock()
            facts = self.facts(files, *changed, evidence=evidence)
            obligations = {row['path']: row for row in facts['unresolved_imports']
                           if row['path'] in consumers}
            self.assertEqual(set(obligations), consumers)
            for obligation in obligations.values():
                self.assertTrue(obligation['candidate_route_symbols'])
                self.assertIn({'path': 'src/index.ts', 'line_start': 1, 'line_end': 2},
                              obligation['candidate_search_ranges'])
            self.assertLessEqual(traversals.call_count, 12)
            snapshots.append((dict(files), facts))

        with mock.patch.object(evidence, 'lru_cache',
                               lambda **options: lambda function: function, create=True):
            for source, cached in snapshots:
                self.assertEqual(self.facts(source, *changed, evidence=evidence), cached)

    def test_distinct_routes_reuse_lexical_work_for_the_same_barrel_blob(self):
        evidence = load_evidence()
        sources = {f'src/unit{index}.ts': f'export const read{index} = () => {index};\n'
                   for index in range(6)}
        barrel = ''.join(f'import {{ read{index} as local{index} }} from "./unit{index}";\n'
                         f'export {{ local{index} as entry{index} }};\n' for index in range(6))
        consumers = {f'src/consumer{index}.ts' for index in range(3)}
        consumer = ('import { ' + ', '.join(f'entry{index}' for index in range(6))
                    + ' } from "./index";\n'
                    + ''.join(f'entry{index}();\n' for index in range(6)))
        files = {**sources, 'src/index.ts': barrel,
                 'visual/fixture.tsx': 'export const read0 = () => 100;\n',
                 **{path: consumer for path in consumers}}
        changed = (*sources, 'visual/fixture.tsx')
        snapshots = []
        retargeted = barrel.replace('"./unit0"', '"../visual/fixture"')
        for body in [barrel, retargeted, retargeted + 'export * from "./missing";\n']:
            with self.subTest(barrel=body):
                files['src/index.ts'] = body
                with mock.patch.object(evidence, 'brace_code', wraps=evidence.brace_code) as masking, \
                        mock.patch.object(evidence, 'ts_import_bindings',
                                          wraps=evidence.ts_import_bindings) as imports:
                    facts = self.facts(files, *changed, evidence=evidence)
                obligations = {(row['path'], row['imported_name']): row
                               for row in facts['unresolved_imports'] if row['path'] in consumers}
                self.assertEqual(set(obligations),
                                 {(path, f'entry{index}') for path in consumers for index in range(6)})
                calls = {(row['path'], row['name'], row.get('local_name'))
                         for row in facts['call_sites'] if row['path'] in consumers}
                expected = {(path, f'read{index}', f'entry{index}')
                            for path in consumers for index in range(6)}
                if './missing' in body:
                    self.assertTrue(expected <= calls, calls)
                else:
                    self.assertEqual(calls, expected)
                for (path, imported_name), obligation in obligations.items():
                    index = int(imported_name.removeprefix('entry'))
                    target = ('visual/fixture.tsx' if index == 0 and body != barrel
                              else f'src/unit{index}.ts')
                    self.assertIn(target, obligation['candidate_targets'])
                    self.assertIn({'source': path, 'target': target, 'kind': 'ambiguous-import'},
                                  facts['dependencies'])
                    self.assertEqual({row['path'] for row in obligation['candidate_route_symbols']},
                                     {'src/index.ts'})
                    if './missing' in body:
                        self.assertIn({'path': 'src/index.ts', 'line_start': 1, 'line_end': 13},
                                      obligation['candidate_search_ranges'])
                    else:
                        self.assertEqual({row['path'] for row in obligation['candidate_symbols']},
                                         {target, 'src/index.ts'})
                source_text = body.removesuffix('\n')
                mask_calls = sum(call.args[0] == source_text for call in masking.call_args_list)
                import_calls = sum('\n'.join(call.args[0]) == source_text
                                   for call in imports.call_args_list)
                self.assertLessEqual(mask_calls, 3,
                                     'distinct routes masked the same immutable barrel again')
                self.assertLessEqual(import_calls, 2,
                                     'distinct routes reparsed the same immutable barrel imports')
                snapshots.append((dict(files), facts))

        with mock.patch.object(evidence, 'lru_cache', lambda **options: lambda function: function):
            for source, cached in snapshots:
                self.assertEqual(self.facts(source, *changed, evidence=evidence), cached)

    def test_aliased_barrel_retains_original_symbol_without_fixture_homonym(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': 'export { useAccount as getAccount } from "./hooks";\n',
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertNotIn('visual/fixture.tsx', obligation['candidate_targets'])
        self.assertTrue(any(row['path'] == 'src/consumer.ts'
                            and row['name'] == 'useAccount'
                            and row.get('local_name') == 'getAccount'
                            for row in facts['call_sites']), facts)
        self.assertIn({'source': 'src/index.ts', 'target': 'src/hooks.ts',
                       'kind': 'local-import'}, facts['dependencies'])

    def test_consumer_alias_keeps_renamed_barrel_export(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': 'export { useAccount as getAccount } from "./hooks";\n',
            'src/consumer.ts': 'import { getAccount as currentAccount } from "./index";\ncurrentAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        self.assertTrue(any(row['path'] == 'src/consumer.ts'
                            and row['name'] == 'useAccount'
                            and row.get('local_name') == 'currentAccount'
                            for row in facts['call_sites']), facts)
        self.assertFalse(any(row['source'] == 'src/consumer.ts'
                             and row['target'] == 'visual/fixture.tsx'
                             for row in facts['dependencies']), facts)

    def test_local_import_then_export_alias_keeps_both_source_proofs(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': ('import { useAccount as localAccount } from "./hooks";\n'
                             'export { localAccount as getAccount };\n'),
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertEqual({(row['path'], row['line_start'], row['line_end'])
                          for row in obligation['candidate_route_symbols']},
                         {('src/index.ts', 1, 1), ('src/index.ts', 2, 2)})
        self.assertNotIn('visual/fixture.tsx', obligation['candidate_targets'])
        self.assertTrue(any(row['path'] == 'src/consumer.ts'
                            and row['name'] == 'useAccount' for row in facts['call_sites']), facts)

    def test_comment_or_string_export_cannot_prove_an_alias_route(self):
        fake_exports = [
            '// export { useAccount as getAccount } from "./hooks";\n',
            '/* export { useAccount as getAccount } from "./hooks"; */\n',
            'const text = \'export { useAccount as getAccount } from "./hooks";\';\n',
            'const text = `export { useAccount as getAccount } from "./hooks";`;\n',
        ]
        for source in fake_exports:
            with self.subTest(source=source):
                facts = self.facts({
                    'src/hooks.ts': 'export const useAccount = () => 1;\n',
                    'src/index.ts': source,
                    'src/consumer.ts': ('import { getAccount as currentAccount } from "./index";\n'
                                        'currentAccount();\n'),
                }, 'src/hooks.ts')
                self.assertFalse(any(row.get('candidate_route_symbols')
                                     for row in facts['unresolved_imports']
                                     if row['path'] == 'src/consumer.ts'), facts)
                self.assertFalse(any(row['path'] == 'src/consumer.ts'
                                     for row in facts['call_sites']), facts)

    def test_valid_alias_route_keeps_an_unresolved_sibling_search(self):
        valid = 'export { useAccount as getAccount } from "./hooks";\n'
        missing = 'export * from "./missing";\n'
        for source in [missing + valid, valid + missing]:
            with self.subTest(source=source):
                facts = self.facts({
                    'src/hooks.ts': 'export const useAccount = () => 1;\n',
                    'src/index.ts': source,
                    'src/consumer.ts': ('import { getAccount as currentAccount } from "./index";\n'
                                        'currentAccount();\n'),
                }, 'src/hooks.ts')
                obligation = next(row for row in facts['unresolved_imports']
                                  if row['path'] == 'src/consumer.ts')
                self.assertTrue(obligation['candidate_route_symbols'], facts)
                self.assertIn({'path': 'src/index.ts', 'line_start': 1, 'line_end': 2},
                              obligation['candidate_search_ranges'], facts)

    def test_commented_import_cannot_supply_a_local_export_route(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': ('// import { useAccount as localAccount } from "./hooks";\n'
                             'export { localAccount as getAccount };\n'),
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
        }, 'src/hooks.ts')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertFalse(obligation['candidate_route_symbols'], facts)
        self.assertTrue(obligation['candidate_search_ranges'], facts)

    def test_arrow_regex_literal_cannot_prove_a_local_export_route(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': ('import { useAccount } from "./hooks";\n'
                             'const match = () => /export { useAccount as getAccount }/.test(text);\n'),
            'src/consumer.ts': ('import { getAccount as currentAccount } from "./index";\n'
                                'currentAccount();\n'),
        }, 'src/hooks.ts')
        self.assertFalse(any(row.get('candidate_route_symbols')
                             for row in facts['unresolved_imports']
                             if row['path'] == 'src/consumer.ts'), facts)

    def test_mixed_wildcard_and_named_alias_hops_keep_exact_route(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/exports.ts': 'export { useAccount as readAccount } from "./hooks";\n',
            'src/middle.ts': 'export * from "./exports";\n',
            'src/index.ts': 'export { readAccount as getAccount } from "./middle";\n',
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertEqual({row['path'] for row in obligation['candidate_route_symbols']},
                         {'src/index.ts', 'src/middle.ts', 'src/exports.ts'})
        self.assertNotIn('visual/fixture.tsx', obligation['candidate_targets'])
        self.assertTrue(any(row['path'] == 'src/consumer.ts'
                            and row['name'] == 'useAccount' for row in facts['call_sites']), facts)

    def test_reexport_revisit_keeps_distinct_export_names(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': ('export { relay as getAccount } from "./next";\n'
                             'export { useAccount } from "./hooks";\n'),
            'src/next.ts': 'export { useAccount as relay } from "./index";\n',
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertEqual({(row['path'], row['line_start'])
                          for row in obligation['candidate_route_symbols']},
                         {('src/index.ts', 1), ('src/index.ts', 2), ('src/next.ts', 1)})
        self.assertNotIn('visual/fixture.tsx', obligation['candidate_targets'])

    def test_alias_does_not_bind_another_changed_name_in_the_target_file(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': 'export { otherAccount as getAccount } from "./hooks";\n',
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
            'visual/fixture.tsx': 'export const useAccount = () => 2;\n',
        }, 'src/hooks.ts', 'visual/fixture.tsx')
        self.assertFalse(any(row['path'] == 'src/consumer.ts'
                             for row in facts['unresolved_imports'] + facts['call_sites']), facts)

    def test_unsupported_local_export_keeps_explicit_search_obligation(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': 'export { unknownAccount as getAccount };\n',
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
        }, 'src/hooks.ts')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertIn('src/hooks.ts', obligation['candidate_targets'])
        self.assertTrue(obligation['candidate_search_ranges'])

    def test_ambiguous_local_export_keeps_explicit_search_obligation(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/other.ts': 'export const otherAccount = () => 2;\n',
            'src/index.ts': ('import { useAccount as localAccount } from "./hooks";\n'
                             'import { otherAccount as localAccount } from "./other";\n'
                             'export { localAccount as getAccount };\n'),
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
        }, 'src/hooks.ts')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertIn('src/hooks.ts', obligation['candidate_targets'])
        self.assertTrue(obligation['candidate_search_ranges'])

    def test_cyclic_local_exports_keep_explicit_search_obligation(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/index.ts': ('import { getAccount as localAccount } from "./next";\n'
                             'export { localAccount as getAccount };\n'),
            'src/next.ts': ('import { getAccount as localAccount } from "./index";\n'
                            'export { localAccount as getAccount };\n'),
            'src/consumer.ts': 'import { getAccount } from "./index";\ngetAccount();\n',
        }, 'src/hooks.ts')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertIn('src/hooks.ts', obligation['candidate_targets'])
        self.assertTrue(obligation['candidate_search_ranges'])

    def test_dynamic_import_and_unbound_dispatch_keep_their_existing_proof(self):
        facts = self.facts({
            'src/hooks.ts': 'export const useAccount = () => 1;\n',
            'src/dynamic.ts': 'import("./hooks").then(module => module.useAccount());\n',
            'tests/dynamic.ts': 'const moduleName = "hooks";\nimport(moduleName);\nuseAccount();\n',
        }, 'src/hooks.ts')
        self.assertIn({'source': 'src/dynamic.ts', 'target': 'src/hooks.ts',
                       'kind': 'local-import'}, facts['dependencies'])
        self.assertTrue(any(row['path'] == 'tests/dynamic.ts'
                            and row.get('resolution') == 'unresolved name search required'
                            for row in facts['call_sites']), facts)

    def test_same_stem_test_does_not_cross_unrelated_languages(self):
        facts = self.facts({
            'visual/main.tsx': 'export const mounted = true;\n',
            'native/Tests/main.swift': 'print("native test")\n',
            'visual/tests/main.jsx': 'const fixture = true;\n',
        }, 'visual/main.tsx')
        self.assertNotIn({'source': 'native/Tests/main.swift', 'target': 'visual/main.tsx',
                          'kind': 'related-test'}, facts['dependencies'])
        self.assertFalse(any(row['path'] == 'native/Tests/main.swift'
                             for row in facts['related_tests']), facts)
        self.assertIn({'source': 'visual/tests/main.jsx', 'target': 'visual/main.tsx',
                       'kind': 'related-test'}, facts['dependencies'])

    def test_unreadable_resolved_module_keeps_search_obligation(self):
        facts = self.facts({
            'src/hooks.ts': b'\0unreadable module',
            'src/consumer.ts': 'import { useAccount } from "./hooks";\nuseAccount();\n',
            'src/candidate.ts': 'export const useAccount = () => 1;\n',
        }, 'src/candidate.ts')
        obligation = next(row for row in facts['unresolved_imports']
                          if row['path'] == 'src/consumer.ts')
        self.assertIn('src/hooks.ts', obligation['unreadable_candidate_targets'])
        self.assertIn('src/candidate.ts', obligation['candidate_targets'])

    def test_unresolved_barrel_export_keeps_search_obligation(self):
        facts = self.facts({
            'src/index.ts': 'export * from "missing-hooks";\n',
            'src/consumer.ts': 'import { useAccount } from "./index";\nuseAccount();\n',
            'src/candidate.ts': 'export const useAccount = () => 1;\n',
        }, 'src/candidate.ts')
        self.assertTrue(any(row['path'] == 'src/consumer.ts'
                            for row in facts['unresolved_imports']), facts)

    def test_c_test_and_header_stem_relationship_is_preserved(self):
        facts = self.facts({
            'include/bridge.h': 'int bridge(void);\n',
            'tests/bridge.cpp': 'int fixture = 1;\n',
        }, 'include/bridge.h')
        self.assertIn({'source': 'tests/bridge.cpp', 'target': 'include/bridge.h',
                       'kind': 'related-test'}, facts['dependencies'])

    def test_cross_language_lexical_bridge_is_not_removed_by_stem_filter(self):
        facts = self.facts({
            'src/bridge.ts': 'export function nativeBridgeCall() { return 1; }\n',
            'native/Tests/bridge.swift': 'func verifyBridge() { nativeBridgeCall() }\n',
        }, 'src/bridge.ts')
        self.assertTrue(any(row['path'] == 'native/Tests/bridge.swift'
                            for row in facts['related_tests']), facts)
        self.assertIn({'source': 'native/Tests/bridge.swift', 'target': 'src/bridge.ts',
                       'kind': 'related-test'}, facts['dependencies'])
        self.assertFalse(any(row['path'] == 'native/Tests/bridge.swift'
                             for row in facts['call_sites']), facts)

    def test_cross_language_lexical_test_keeps_obligation_without_matching_stem(self):
        facts = self.facts({
            'src/bridge.ts': 'export function nativeBridgeCall() { return 1; }\n',
            'native/Tests/protocol.swift': 'func verifyBridge() { nativeBridgeCall() }\n',
        }, 'src/bridge.ts')
        self.assertTrue(any(row['path'] == 'native/Tests/protocol.swift'
                            for row in facts['related_tests']), facts)
        self.assertIn({'source': 'native/Tests/protocol.swift', 'target': 'src/bridge.ts',
                       'kind': 'related-test'}, facts['dependencies'])
        self.assertFalse(any(row['path'] == 'native/Tests/protocol.swift'
                             for row in facts['call_sites']), facts)

    def test_cross_language_lexical_value_keeps_related_test_without_call_claim(self):
        facts = self.facts({
            'src/bridge.ts': 'export const featureEnabled = true;\n',
            'native/Tests/protocol.swift': 'let observed = featureEnabled\n',
        }, 'src/bridge.ts')
        self.assertTrue(any(row['path'] == 'native/Tests/protocol.swift'
                            for row in facts['related_tests']), facts)
        self.assertIn({'source': 'native/Tests/protocol.swift', 'target': 'src/bridge.ts',
                       'kind': 'related-test'}, facts['dependencies'])
        self.assertFalse(any(row['path'] == 'native/Tests/protocol.swift'
                             for row in facts['call_sites']), facts)


if __name__ == '__main__':
    unittest.main()
