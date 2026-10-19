"""Required source proof must describe an executable, exact snapshot obligation."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / 'plugins/review-council/scripts'
TARGET = re.compile(
    r'^Required post-index original-source target: (.+):(\d+)-(\d+) '
    r'tree (\w+) blob (\w+) content SHA-256 (\w+) reasons ', re.M)


def load_evidence():
    spec = importlib.util.spec_from_file_location(
        'deleted_source_evidence', SCRIPTS / 'rev-evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SourceFixture:
    def __init__(self, directory, mode):
        self.root = directory / 'repo'
        self.session = directory / 'session'
        self.root.mkdir(parents=True)
        self.session.mkdir()
        self.env = dict(os.environ, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(directory / 'no-hooks'))
        (self.root / 'keep.txt').write_text('unchanged nonsemantic context\n')
        if mode != 'current':
            self.historical_source = self.declarations('retired', 110, 'old')
            if mode == 'deleted':
                self.oversized_source = ('def retired_oversized():\n' + ''.join(
                    f'    value_{index:03d} = "historical-{index:03d}-{"y" * 96}"\n'
                    for index in range(180)) + '    return value_179\n')
                self.historical_source += self.oversized_source
            (self.root / 'aa_retired.py').write_text(self.historical_source)
        if mode in ('mixed', 'plan', 'current'):
            count = 110 if mode == 'current' else 8
            (self.root / 'zz_current.py').write_text(self.declarations('active', count, 'old'))
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        if mode == 'renamed':
            (self.root / 'aa_retired.py').rename(self.root / 'zz_relocated.py')
        elif mode != 'current':
            (self.root / 'aa_retired.py').unlink()
        if mode in ('mixed', 'plan', 'current'):
            (self.root / 'zz_current.py').write_text(self.declarations('active', count, 'new'))
        (self.session / 'scope.env').write_text(
            f'REV_BASE={shlex.quote(self.base)}\n'
            f'REV_ROOT={shlex.quote(str(self.root))}\nREV_SCOPE=branch\n')
        for name in ('files.txt', 'untracked.txt'):
            (self.session / name).write_text('')
        (self.session / 'roster.json').write_text(json.dumps({'seats': [
            {'seat': seat, 'adapter': 'codex'} for seat in ('sol', 'second', 'third', 'fourth')
        ]}))
        self.label = '1p' if mode == 'plan' else '1'
        self.phase = 'plan' if mode == 'plan' else 'discovery'
        extra = []
        if mode == 'plan':
            plan = self.session / 'fix-plan.md'
            plan.write_text(
                '## C-01 - replace the retired implementation\n'
                'Findings: F-001 (P1)\nRule: Keep active behavior after retirement.\n'
                "Sites: zz_current.py:1-2 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'active_000' .)\n"
                'Test: zz_current.py:1-2 - active behavior stays observable\n'
                'Prediction: reverting the guard fails zz_current.py at active_000, '
                'because its returned value changes.\n')
            extra = ['--plan', str(plan), '--plan-sha256', hashlib.sha256(plan.read_bytes()).hexdigest()]
            for seat, bundle in zip(('sol', 'second', 'third', 'fourth'),
                                    ('plan-completeness', 'plan-soundness', 'plan-simplicity', 'plan-tests')):
                extra += ['--assignment', seat + '=' + bundle]
        self.run('prepare', str(self.session), self.label, '--phase', self.phase,
                 '--full-seat', 'sol', *extra)
        self.manifest_path = self.session / f'r{self.label}-evidence.manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text())
        self.seat = self.manifest['mechanical_owner']
        self.context = self.manifest['source_context']['seats'][self.seat]
        self.prompt = self.session / f'r{self.label}-{self.seat}.prompt.md'
        assignment = self.manifest['assignments'][self.seat]
        command = [str(SCRIPTS / 'rev-prompt.sh'), str(self.session), self.label,
                   self.seat, assignment['bundle'], 'required source proof',
                   '--evidence', str(self.manifest_path)]
        if mode == 'plan':
            command += ['--phase', 'plan', '--plan',
                        str(self.session / self.manifest['plan']['artifact'])]
        subprocess.run(command, env=self.env, text=True, capture_output=True, check=True)

    @staticmethod
    def declarations(prefix, count, value):
        return ''.join(f'def {prefix}_{index:03d}():\n    return "{value}{"x" * 400}"\n\n'
                       for index in range(count))

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       stderr=subprocess.PIPE, text=True).strip()

    def run(self, *args):
        return subprocess.run([os.sys.executable, str(SCRIPTS / 'rev-evidence.py'), *args],
                              env=self.env, text=True, capture_output=True, check=True)

    def target(self):
        match = TARGET.search(self.prompt.read_text())
        if match is None:
            raise AssertionError('available current source must produce an exact mandatory target')
        path, start, end, tree, oid, digest = match.groups()
        return {'path': path, 'line_start': int(start), 'line_end': int(end),
                'blob_tree': tree, 'blob_oid': oid, 'content_sha256': digest}

    def audit(self, source=None, result=None, omitted_artifacts=()):
        events = []

        def read(command, output):
            call = 'read-' + str(len(events))
            item = {'id': call, 'type': 'command_execution', 'command': command}
            events.append({'type': 'item.started', 'item': item})
            events.append({'type': 'item.completed', 'item': dict(
                item, aggregated_output=output, exit_code=0)})

        def read_artifact(path):
            if path.name not in omitted_artifacts:
                read(shlex.join(['cat', '--', str(path)]), path.read_text())

        assignment = self.manifest['assignments'][self.seat]
        for chunk in self.manifest['patch_sets'][assignment['patch_set']]['chunks']:
            read_artifact(self.session / chunk['artifact'])
        for shard in self.context['shards']:
            read_artifact(self.session / shard['artifact'])
        for required in self.context['required_source_ranges']:
            for segment in required['segments']:
                read_artifact(self.session / segment['artifact'])
        index = self.session / f'r{self.label}-evidence.md'
        read_artifact(index)
        if source is not None:
            row, tree, output = source
            window = f"{row['line_start']},{row['line_end']}p"
            if tree is None:
                command = shlex.join(['sed', '-n', window, row['path']])
            else:
                command = (shlex.join(['git', 'show', tree + ':' + row['path']])
                           + ' | ' + shlex.join(['sed', '-n', window]))
            read(command, output)
        stem = self.session / f'r{self.label}-{self.seat}'
        raw = Path(str(stem) + '.stream.ndjson')
        raw.write_text(''.join(json.dumps(event) + '\n' for event in events))
        result_path = Path(str(stem) + '.json')
        result_path.write_text(json.dumps(result or {'summary': 'checked', 'findings': []}))
        audit_path = Path(str(stem) + '.read-audit.json')
        process = subprocess.run(
            [os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
             '--adapter', 'codex', '--raw', str(raw), '--prompt', str(self.prompt),
             '--root', str(self.root), '--session', str(self.session), '--out', str(audit_path)],
            env=self.env, text=True, capture_output=True)
        return process.returncode, json.loads(audit_path.read_text())

    def current_bytes(self, row):
        return ''.join((self.root / row['path']).read_text().splitlines(keepends=True)[
            row['line_start'] - 1:row['line_end']])

    def receipt_gate(self, audit):
        stem = self.session / f'r{self.label}-{self.seat}'
        audit_path = Path(str(stem) + '.read-audit.json')
        audit_path.write_text(json.dumps(audit))
        result = Path(str(stem) + '.json')
        load_evidence().audit_gate(
            self.manifest, hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
            self.phase, self.seat, stem, self.manifest['assignments'][self.seat],
            self.prompt, result, json.loads(result.read_text()), audit_path)


class RequiredSourceProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='required-source-proof-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def fixture(self, mode):
        return SourceFixture(self.directory, mode)

    def assert_current_target(self, fixture):
        target = fixture.target()
        self.assertEqual(target['blob_tree'], fixture.manifest['snapshot_tree'],
                         'mandatory source target must belong to the current snapshot')
        self.assertTrue((fixture.root / target['path']).is_file(),
                        'mandatory source target must exist in the working tree')
        raw = fixture.current_bytes(target)
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), target['content_sha256'])
        evidence = load_evidence()
        repository = evidence.Repository(fixture.session)
        self.assertEqual(repository.entries(fixture.manifest['snapshot_tree'])[target['path']][1],
                         target['blob_oid'])
        return target

    def test_mixed_deletion_selects_available_current_target_without_losing_history(self):
        fixture = self.fixture('mixed')
        rows = [row for shard in fixture.context['shards'] for row in shard['ranges']]
        rows += fixture.context['required_source_ranges'] + fixture.context['omitted_source_ranges']
        self.assertTrue(any(row['path'] == 'aa_retired.py'
                            and row['blob_tree'] == fixture.manifest['base_tree'] for row in rows))
        patch = (fixture.session / f'r{fixture.label}-full.patch').read_text()
        self.assertIn('--- a/aa_retired.py', patch)
        self.assertIn('+++ b/zz_current.py', patch)
        self.assertTrue(fixture.context['source_read_required'])
        self.assert_current_target(fixture)

    def test_rename_never_requires_the_old_absent_path(self):
        self.assert_current_target(self.fixture('renamed'))

    def test_schema4_plan_selects_current_target_in_shared_source_context(self):
        fixture = self.fixture('plan')
        self.assertEqual(fixture.manifest['schema_version'], 4)
        self.assert_current_target(fixture)

    def test_deletion_only_has_explicit_absence_and_retains_historical_reads(self):
        fixture = self.fixture('deleted')
        expected_packets = [f'r1-{fixture.seat}-source-context-{index}.json'
                            for index in (1, 2, 3)]
        self.assertEqual([shard['artifact'] for shard in fixture.context['shards']],
                         expected_packets, 'deletion-only review must retain every historical packet')
        historical_lines = fixture.historical_source.splitlines(keepends=True)
        base_tree = fixture.manifest['base_tree']
        expected_oid = fixture.git('rev-parse', fixture.base + ':aa_retired.py')
        expected_reads = {}
        expected_packet_ranges = 0
        for shard in fixture.context['shards']:
            raw = (fixture.session / shard['artifact']).read_bytes()
            self.assertEqual(shard['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(shard['bytes'], len(raw))
            payload = json.loads(raw)
            self.assertTrue(payload['entries'], 'historical packets must contain actual source')
            expected_packet_ranges += len(payload['entries'])
            for row in payload['entries']:
                self.assertEqual((row['path'], row['blob_tree'], row['blob_oid']),
                                 ('aa_retired.py', base_tree, expected_oid))
                expected = ''.join(historical_lines[row['line_start'] - 1:row['line_end']])
                self.assertTrue(expected)
                self.assertEqual(row['content'], expected)
                self.assertEqual(row['content_sha256'], hashlib.sha256(expected.encode()).hexdigest())
            expected_reads[shard['artifact']] = raw
        required = fixture.context['required_source_ranges']
        self.assertEqual(len(required), 1, 'the oversized historical declaration must require segments')
        required = required[0]
        oversized_offset = fixture.historical_source.index(fixture.oversized_source)
        start = fixture.historical_source[:oversized_offset].count('\n') + 1
        end = start + len(fixture.oversized_source.splitlines()) - 1
        expected_proof = {
            'path': 'aa_retired.py', 'line_start': start, 'line_end': end,
            'blob_tree': base_tree, 'blob_oid': expected_oid,
            'content_sha256': hashlib.sha256(fixture.oversized_source.encode()).hexdigest(),
        }
        self.assertEqual({key: required[key] for key in expected_proof}, expected_proof)
        self.assertGreater(len(required['segments']), 1, 'historical source must exercise real segmentation')
        segment_bytes = []
        for segment in required['segments']:
            raw = (fixture.session / segment['artifact']).read_bytes()
            expected = ''.join(historical_lines[segment['line_start'] - 1:segment['line_end']]).encode()
            self.assertEqual(raw, expected)
            self.assertEqual(segment['raw_bytes'], len(expected))
            self.assertEqual(segment['content_sha256'], hashlib.sha256(expected).hexdigest())
            expected_reads[segment['artifact']] = expected
            segment_bytes.append(raw)
        self.assertEqual(b''.join(segment_bytes), fixture.oversized_source.encode())
        self.assertIsNone(TARGET.search(fixture.prompt.read_text()),
                          'deletion-only review must not invent a current source target')
        self.assertRegex(fixture.prompt.read_text(),
                         r'(?im)^.*no (?:eligible )?current(?:-tree| snapshot) source.*$',
                         'absence must state why no current source target exists')
        rc, audit = fixture.audit()
        self.assertEqual((rc, audit['violations']), (0, []))
        self.assertEqual(audit['packet_shards'], len(expected_packets))
        self.assertEqual(audit['packet_bytes'], sum(len(expected_reads[name]) for name in expected_packets))
        self.assertEqual(audit['packet_ranges'], expected_packet_ranges)
        self.assertEqual(audit['required_source_ranges_covered'], 1)
        self.assertEqual(audit['required_source_range_proofs'], [expected_proof])
        raw_path = fixture.session / f'r1-{fixture.seat}.stream.ndjson'
        raw = raw_path.read_bytes()
        self.assertEqual(audit['stream_sha256'], hashlib.sha256(raw).hexdigest())
        observed_reads = []
        for event in map(json.loads, raw.decode().splitlines()):
            if event['type'] != 'item.completed':
                continue
            item = event['item']
            path = Path(shlex.split(item['command'])[-1])
            if path.name in expected_reads:
                self.assertEqual(item['aggregated_output'].encode(), expected_reads[path.name])
                observed_reads.append(path.name)
        self.assertEqual(observed_reads, list(expected_reads),
                         'historical packet and segment identities must be consumed exactly once in order')
        self.assertEqual(audit['source_ranges'], [],
                         'historical packet coverage must not earn snapshot citation proof')
        fixture.receipt_gate(audit)
        for omitted, code in ((expected_packets, 'missing-source-packet'),
                              ([segment['artifact'] for segment in required['segments']],
                               'missing-required-source-segment')):
            with self.subTest(omitted=omitted):
                rc, incomplete = fixture.audit(omitted_artifacts=omitted)
                self.assertEqual(rc, 2, 'missing historical reads must never produce valid proof')
                self.assertIn(code, [row['code'] for row in incomplete['violations']])
                with self.assertRaises(ValueError):
                    fixture.receipt_gate(incomplete)

    def test_exact_target_passes_both_transcript_and_receipt_gates(self):
        fixture = self.fixture('current')
        target = self.assert_current_target(fixture)
        rc, audit = fixture.audit((target, None, fixture.current_bytes(target)))
        self.assertEqual((rc, audit['violations']), (0, []))
        fixture.receipt_gate(audit)

    def test_available_current_target_cannot_be_waived_in_the_manifest(self):
        fixture = self.fixture('current')
        self.assert_current_target(fixture)
        evidence = load_evidence()
        index = json.loads((fixture.session / 'r1-evidence.json').read_text())
        evidence.validate_source_context(fixture.session, fixture.manifest, index)
        waived = copy.deepcopy(fixture.manifest)
        waived['source_context']['seats'][fixture.seat]['source_read_required'] = False
        waived_index = dict(index, source_context=waived['source_context'])
        with self.assertRaisesRegex(ValueError, 'invalid source context read requirement'):
            evidence.validate_source_context(fixture.session, waived, waived_index)

    def test_target_identity_cannot_name_a_missing_path_or_wrong_blob(self):
        fixture = self.fixture('current')
        self.assert_current_target(fixture)
        evidence = load_evidence()
        repository = evidence.Repository(fixture.session)
        evidence.validate_source_context_snapshot(repository, fixture.session, fixture.manifest)
        for mutation in ({'path': 'missing.py'}, {'blob_oid': '0' * 40},
                         {'blob_tree': fixture.manifest['base_tree']}):
            with self.subTest(mutation=mutation):
                forged = copy.deepcopy(fixture.manifest)
                row = forged['source_context']['seats'][fixture.seat]['omitted_source_ranges'][0]
                row.update(mutation)
                with self.assertRaisesRegex(ValueError, 'source context blob identity mismatch'):
                    evidence.validate_source_context_snapshot(repository, fixture.session, forged)

    def test_unrelated_omitted_range_cannot_replace_the_exact_target(self):
        fixture = self.fixture('current')
        target = self.assert_current_target(fixture)
        rc, positive = fixture.audit((target, None, fixture.current_bytes(target)))
        self.assertEqual((rc, positive['violations']), (0, []), 'positive control must be valid')
        other = next(row for row in fixture.context['omitted_source_ranges']
                     if row['path'] == target['path']
                     and (row['line_start'] > target['line_end']
                          or row['line_end'] < target['line_start']))
        rc, audit = fixture.audit((other, None, fixture.current_bytes(other)))
        self.assertEqual(rc, 2, 'a different omitted range must not satisfy the named exact target')
        self.assertIn('missing-required-source-read', [row['code'] for row in audit['violations']])

    def test_partial_exact_target_is_insufficient(self):
        fixture = self.fixture('current')
        target = self.assert_current_target(fixture)
        rc, positive = fixture.audit((target, None, fixture.current_bytes(target)))
        self.assertEqual((rc, positive['violations']), (0, []), 'positive control must be valid')
        self.assertGreater(target['line_end'], target['line_start'])
        partial = dict(target, line_end=target['line_start'])
        rc, audit = fixture.audit((partial, None, fixture.current_bytes(partial)))
        self.assertEqual(rc, 2, 'a one-line intersection must not replace the complete named target')
        self.assertIn('missing-required-source-read', [row['code'] for row in audit['violations']])

    def test_base_or_wrong_tree_bytes_cannot_satisfy_the_target(self):
        fixture = self.fixture('current')
        target = self.assert_current_target(fixture)
        rc, positive = fixture.audit((target, None, fixture.current_bytes(target)))
        self.assertEqual((rc, positive['violations']), (0, []), 'positive control must be valid')
        base_raw = fixture.git('show', fixture.base + ':' + target['path']) + '\n'
        base_output = ''.join(base_raw.splitlines(keepends=True)[
            target['line_start'] - 1:target['line_end']])
        for tree in (fixture.manifest['base_tree'], fixture.manifest['snapshot_tree'], None):
            with self.subTest(tree=tree):
                rc, audit = fixture.audit((target, tree, base_output))
                self.assertEqual(rc, 2, 'base or mismatched-tree bytes must not prove current source')
                self.assertIn('missing-required-source-read',
                              [row['code'] for row in audit['violations']])

    def test_receipt_rechecks_exact_target_instead_of_trusting_valid_status(self):
        fixture = self.fixture('current')
        target = self.assert_current_target(fixture)
        rc, positive = fixture.audit((target, None, fixture.current_bytes(target)))
        self.assertEqual((rc, positive['violations']), (0, []), 'positive control must be valid')
        fixture.receipt_gate(positive)
        other = next(row for row in fixture.context['omitted_source_ranges']
                     if row['path'] == target['path'] and row['line_start'] > target['line_end'])
        forged = copy.deepcopy(positive)
        tool = next(row for row in forged['source_ranges'] if row['origin'] == 'tool')
        tool.update(path=other['path'], line_start=other['line_start'], line_end=other['line_end'])
        forged['source_ranges'].sort(key=lambda row: (
            row['path'], row['line_start'], row['line_end'], row['origin']))
        with self.assertRaisesRegex(ValueError, 'read audit evidence coverage mismatch'):
            fixture.receipt_gate(forged)


if __name__ == '__main__':
    unittest.main()
