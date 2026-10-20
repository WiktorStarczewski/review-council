"""Offline numeric SDK code contracts; no synthetic proof qualifies a live seat."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import test_cursor_integration as integration_cases
import test_cursor_sdk as sdk_cases
from test_cursor_sdk import CursorSDKCase, FIXTURES, SCRIPTS, module
from test_deleted_source_proof import SourceFixture


REPO = Path(__file__).resolve().parents[1]
DOCUMENT_REASON = 'cursor-sdk document mode is unsupported'
EXTRA_REASON = 'cursor-sdk numeric extra mode is unsupported'


class CursorNumericTests(CursorSDKCase):
    def fixture(self, name, number=1, minimum=1, sdk=True, extra=False):
        directory = self.directory / name
        directory.mkdir()
        fixture = SourceFixture(directory, 'current')
        fixture.env = dict(self.env, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1')
        (fixture.root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{}}\n')
        (fixture.session / 'files.txt').write_text('zz_current.py\npackage-lock.json\n')
        (fixture.session / 'untracked.txt').write_text('package-lock.json\n')
        seats = [
            {'seat': name, 'adapter': 'codex', 'lab': 'openai', 'model': 'gpt-9-' + name,
             'effort': 'xhigh', 'extra': False} for name in ('sol', 'luna')
        ]
        seats.append(integration_cases.CursorIntegrationTests.sdk_seat(self, directory) if sdk else
                     dict(seats[0], seat='sol-second'))
        if extra:
            seats.append(dict(seats[0], seat='codex-review', extra=True, mode='review', round=3))
        fixture.roster = {'seats': seats}
        (fixture.session / 'roster.json').write_text(json.dumps(fixture.roster))
        fixture.label, fixture.phase, fixture.minimum = str(number), 'numeric', minimum
        fixture.manifest_path = fixture.session / f'r{fixture.label}-evidence.manifest.json'
        fixture.panel = fixture.session / f'r{fixture.label}-panel.tsv'
        lens = {1: 'simplicity', 2: 'correctness,edge-cases,error-handling', 8: 'regression'}.get(
            number, 'security,data-state')
        fixture.rows = [(row['seat'], lens, 'Numeric fixture emphasis for ' + row['seat'])
                        for row in seats if not row.get('extra') or row.get('round') == number]
        fixture.panel.write_text(''.join('\t'.join(row) + '\n' for row in fixture.rows))
        return fixture

    def command(self, *args, environment=None):
        return subprocess.run([os.sys.executable, str(SCRIPTS / 'rev-evidence.py'), *map(str, args)],
                              env=environment or self.env, capture_output=True, text=True, timeout=40)

    def prepare(self, fixture):
        result = self.command(
            'prepare', fixture.session, fixture.label, '--phase', 'numeric',
            '--numeric-round', fixture.label, '--numeric-min-rounds', fixture.minimum,
            '--numeric-panel', fixture.panel, environment=fixture.env)
        self.assertEqual(result.returncode, 0,
                         'SDK numeric code requires explicit full-scope preparation: ' + result.stderr)
        fixture.manifest = json.loads(fixture.manifest_path.read_text())
        return fixture.manifest

    def render(self, fixture, evidence=True):
        arguments = [str(SCRIPTS / 'rev-prompt.sh'), str(fixture.session), fixture.label,
                     '--panel', str(fixture.panel)]
        if evidence:
            arguments += ['--phase', 'numeric', '--evidence', str(fixture.manifest_path)]
        return subprocess.run(arguments, env=fixture.env, capture_output=True, text=True, timeout=40)

    def rendered(self, fixture):
        self.prepare(fixture)
        result = self.render(fixture)
        self.assertEqual(result.returncode, 0,
                         'numeric evidence must render unchanged legacy lenses: ' + result.stderr)

    def events(self):
        return [json.loads(line) for line in (FIXTURES / 'cursor-sdk-stream.ndjson').read_text().splitlines()]

    def proofs(self, fixture):
        for seat, assignment in fixture.manifest['assignments'].items():
            fixture.seat = seat
            fixture.context = fixture.manifest['source_context']['seats'][seat]
            fixture.prompt = fixture.session / f'r{fixture.label}-{seat}.prompt.md'
            stem = fixture.session / f'r{fixture.label}-{seat}'
            if assignment['adapter'] == 'cursor-sdk':
                events, _ = sdk_cases.CursorStreamTests.canonical_events(self, fixture)
                request = {'path': 'zz_current.py', 'offset': 1, 'limit': 2}
                text = fixture.current_bytes({'path': 'zz_current.py', 'line_start': 1, 'line_end': 2})
                running, callback, completed = copy.deepcopy(self.events()[1:4])
                for event in (running, completed):
                    event['call_id'] = 'numeric-post-index-source'
                    event['args']['args'] = request
                callback.update(call_id='numeric-post-index-source', input=request,
                                text_sha256=hashlib.sha256(text.encode()).hexdigest())
                completed['result']['value']['content'] = [{'text': {'text': text}}]
                events[-1:-1] = [running, callback, completed]
                Path(str(stem) + '.stream.ndjson').write_text(''.join(json.dumps(row) + '\n' for row in events))
                Path(str(stem) + '.json').write_text('{"summary":"Synthetic fixture checked","findings":[]}\n')
                result = subprocess.run([
                    os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
                    '--adapter', 'cursor-sdk', '--raw', str(stem) + '.stream.ndjson',
                    '--result', str(stem) + '.json', '--prompt', str(fixture.prompt),
                    '--root', str(fixture.root), '--session', str(fixture.session),
                    '--out', str(stem) + '.read-audit.json'],
                    env=fixture.env, capture_output=True, text=True, timeout=40)
                code = result.returncode
                report_path = Path(str(stem) + '.read-audit.json')
                self.assertTrue(report_path.is_file(), 'canonical SDK auditor must publish a verdict: ' + result.stderr)
                report = json.loads(report_path.read_text())
            else:
                row = fixture.target()
                code, report = fixture.audit(source=(row, None, fixture.current_bytes(row)))
            self.assertEqual(code, 0, 'numeric proof must use the canonical auditor: ' + json.dumps(report))
            self.assertEqual(report['status'], 'valid')
            self.assertFalse(report['narrow'])
            Path(str(stem) + '.exit').write_text('0\n')

    def evidence(self):
        return module(SCRIPTS / 'rev-evidence.py')

    def roster_code(self, roster, arguments):
        try:
            return roster.main(arguments)
        except SystemExit as error:
            return error.code

    def test_numeric_rounds_bind_minimum_legacy_lenses_and_full_cumulative_patch(self):
        for number, minimum in ((1, 1), (2, 1), (8, 3)):
            with self.subTest(round=number, minimum=minimum):
                fixture = self.fixture(str(number), number, minimum)
                manifest = self.prepare(fixture)
                self.assertEqual(manifest['phase'], 'numeric')
                self.assertEqual(manifest['numeric'], {
                    'round': number, 'min_rounds': minimum, 'panel': fixture.panel.name,
                    'panel_sha256': hashlib.sha256(fixture.panel.read_bytes()).hexdigest(),
                    'launched_seats': [row[0] for row in fixture.rows],
                })
                self.assertIn(fixture.panel.name, manifest['artifacts'])
                full = (fixture.session / f'r{number}-full.patch').read_bytes()
                self.assertIn(b'package-lock.json', full, 'mechanical changes belong to every numeric seat')
                for seat, lens, emphasis in fixture.rows:
                    assignment = manifest['assignments'][seat]
                    self.assertEqual((assignment['scope'], assignment['full_state']), ('full', True))
                    self.assertEqual((assignment['bundle'], assignment['emphasis']), (lens, emphasis))
                    self.assertEqual(Path(assignment['patch']).read_bytes(), full)
                    self.assertEqual(assignment['patch_sha256'], hashlib.sha256(full).hexdigest())
                sdk = manifest['assignments']['sdk']
                row = fixture.roster['seats'][2]
                self.assertEqual(sdk['model_selection'], row['model_selection'])
                self.assertEqual(sdk['cursor_sdk'], row['cursor_sdk'])
                self.assertIsNone(manifest['predecessor'])

    def test_numeric_prepare_rejects_invalid_round_minimum_and_launched_set(self):
        self.prepare(self.fixture('numeric-input-control', 2))
        for invalid in ('zero-round', 'zero-minimum', 'label', 'missing-minimum',
                        'duplicate-seat', 'missing-seat', 'unknown-seat'):
            with self.subTest(invalid=invalid):
                fixture = self.fixture(invalid, 0 if invalid == 'zero-round' else 2)
                number = fixture.label
                label = '3' if invalid == 'label' else fixture.label
                if invalid == 'label':
                    original = fixture.panel
                    fixture.panel = fixture.session / 'r3-panel.tsv'
                    original.rename(fixture.panel)
                minimum = '0' if invalid == 'zero-minimum' else '1'
                if invalid.endswith('seat'):
                    rows = list(fixture.rows)
                    if invalid == 'duplicate-seat':
                        rows.append(rows[0])
                    elif invalid == 'missing-seat':
                        rows.pop()
                    else:
                        rows.append(('unknown', 'simplicity', 'Unknown seat'))
                    fixture.panel.write_text(''.join('\t'.join(row) + '\n' for row in rows))
                arguments = ['prepare', fixture.session, label, '--phase', 'numeric',
                             '--numeric-round', number, '--numeric-panel', fixture.panel]
                if invalid != 'missing-minimum':
                    arguments += ['--numeric-min-rounds', minimum]
                result = self.command(*arguments, environment=fixture.env)
                self.assertNotEqual(result.returncode, 0, 'invalid numeric input must refuse: ' + invalid)
                self.assertIn('numeric', result.stderr.lower())
                self.assertFalse((fixture.session / f'r{label}-evidence.manifest.json').exists())

    def test_numeric_render_rejects_changed_panel_atomically(self):
        for mutation in ('lens', 'emphasis', 'seat', 'order'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture(mutation, 2)
                self.rendered(fixture)
                rows = list(fixture.rows)
                first = list(rows[0])
                if mutation == 'order':
                    rows.reverse()
                else:
                    first[{'lens': 1, 'emphasis': 2, 'seat': 0}[mutation]] += '-changed'
                    rows[0] = tuple(first)
                fixture.panel.write_text(''.join('\t'.join(row) + '\n' for row in rows))
                result = self.render(fixture)
                self.assertNotEqual(result.returncode, 0, 'changed numeric panel cannot publish prompts')
                for seat, _, _ in fixture.rows:
                    self.assertFalse((fixture.session / f'r{fixture.label}-{seat}.prompt.md').exists())

    def test_numeric_prompt_validator_binds_emphasis_once(self):
        fixture = self.fixture('emphasis')
        self.rendered(fixture)
        seat, lens, emphasis = fixture.rows[0]
        prompt = fixture.session / f'r1-{seat}.prompt.md'
        original = prompt.read_text()
        self.assertIn('## Your lens this round: ' + lens, original)
        marker = 'Round emphasis: ' + emphasis
        self.assertEqual(original.splitlines().count(marker), 1)
        for changed in (original.replace(marker, marker + ' changed'), original + marker + '\n'):
            with self.subTest(duplicate=changed.count(marker) > 1):
                prompt.write_text(changed)
                result = subprocess.run([
                    os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'validate-prompt',
                    '--root', str(fixture.root), '--session', str(fixture.session),
                    '--manifest', str(fixture.manifest_path), '--seat', seat, '--prompt', str(prompt)],
                    env=fixture.env, capture_output=True, text=True, timeout=40)
                self.assertNotEqual(result.returncode, 0, 'unbound numeric emphasis cannot be accepted')
                self.assertIn('emphasis', result.stderr.lower())
        prompt.write_text(original)

    def test_numeric_seal_uses_real_audits_without_advancing_adaptive_coverage(self):
        for prior in (False, True):
            with self.subTest(prior_head=prior):
                fixture = self.fixture('seal-' + str(prior))
                self.rendered(fixture)
                self.proofs(fixture)
                head = fixture.session / 'coverage-head.json'
                sentinel = b'{"receipt":"existing.receipt.json","sha256":"' + b'f' * 64 + b'"}\n'
                if prior:
                    head.write_bytes(sentinel)
                evidence = self.evidence()
                # Live qualification is outside this offline compiler/receipt contract.
                with patch.object(evidence, 'validate_cursor_sdk_qualification') as qualification, \
                        redirect_stdout(io.StringIO()):
                    evidence.receipt(SimpleNamespace(session=str(fixture.session), label='1', replacement=[]))
                self.assertGreater(qualification.call_count, 0)
                receipt = json.loads((fixture.session / 'r1-coverage.receipt.json').read_text())
                self.assertEqual(receipt['phase'], 'numeric')
                self.assertEqual(set(receipt['results']) & {
                    f'r1-{seat}.json' for seat, _, _ in fixture.rows},
                    {f'r1-{seat}.json' for seat, _, _ in fixture.rows})
                self.assertEqual(head.read_bytes() if head.exists() else None, sentinel if prior else None)
                self.assertFalse(evidence.current_coverage_data(fixture.session)['eligible'])

    def test_numeric_seal_rejects_failed_incomplete_and_changed_generation(self):
        fixture = self.fixture('generation')
        self.rendered(fixture)
        self.proofs(fixture)
        evidence = self.evidence()
        mutations = [
            ('exit', fixture.session / 'r1-sdk.exit', b'2\n'),
            ('incomplete', fixture.session / 'r1-sdk.json',
             b'{"summary":"INCOMPLETE PROOF: source not read","findings":[]}\n'),
            ('stream', fixture.session / 'r1-sdk.stream.ndjson', b'{}\n'),
            ('source', fixture.root / 'zz_current.py', b'def changed():\n    return 0\n'),
        ]
        manifest = fixture.manifest_path.read_bytes()
        changed = copy.deepcopy(fixture.manifest)
        changed['numeric']['min_rounds'] = 2
        mutations.append(('minimum', fixture.manifest_path, json.dumps(changed).encode()))
        roster_path = fixture.session / 'roster.json'
        changed = copy.deepcopy(fixture.roster)
        changed['seats'][2]['cursor_sdk']['runtime_sha256'] = 'd' * 64
        mutations.append(('runtime', roster_path, json.dumps(changed).encode()))
        with patch.object(evidence, 'validate_cursor_sdk_qualification'):
            for name, path, content in mutations:
                with self.subTest(mutation=name):
                    evidence.verify_panel_selection(fixture.session, '1')
                    original = path.read_bytes()
                    path.write_bytes(content)
                    try:
                        with self.assertRaises((ValueError, OSError)):
                            evidence.verify_panel_selection(fixture.session, '1')
                    finally:
                        path.write_bytes(original)
            evidence.verify_panel_selection(fixture.session, '1')
        self.assertEqual(fixture.manifest_path.read_bytes(), manifest)

    def test_numeric_replacement_keeps_parent_contract_and_valid_siblings(self):
        fixture = self.fixture('replacement', 2)
        self.rendered(fixture)
        self.proofs(fixture)
        parent_bytes = fixture.manifest_path.read_bytes()
        parent = fixture.manifest['assignments']['sdk']
        siblings = {path: path.read_bytes() for seat in ('sol', 'luna') for suffix in (
            '.prompt.md', '.stream.ndjson', '.json', '.read-audit.json', '.exit')
            for path in [fixture.session / ('r2-' + seat + suffix)]}
        incomplete = '{"summary":"INCOMPLETE PROOF: assigned checks remain unsettled","findings":[]}'
        result_path = fixture.session / 'r2-sdk.json'
        result_path.write_text(incomplete + '\n')
        stream_path = fixture.session / 'r2-sdk.stream.ndjson'
        events = [json.loads(line) for line in stream_path.read_text().splitlines()]
        self.assertEqual((events[-1]['type'], events[-1]['status']), ('result', 'finished'))
        events[-1]['result'] = incomplete
        stream_path.write_text(''.join(json.dumps(event) + '\n' for event in events))
        audit_path = fixture.session / 'r2-sdk.read-audit.json'
        result = subprocess.run([
            os.sys.executable, str(SCRIPTS / 'lib/review-read-audit.py'), 'audit',
            '--adapter', 'cursor-sdk', '--raw', str(stream_path), '--result', str(result_path),
            '--prompt', str(fixture.session / 'r2-sdk.prompt.md'), '--root', str(fixture.root),
            '--session', str(fixture.session), '--out', str(audit_path)],
            env=fixture.env, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, 'incomplete SDK generation must retain honest read proof: ' + result.stderr)
        report = json.loads(audit_path.read_text())
        self.assertEqual(report['status'], 'valid')
        self.assertEqual(report['result_sha256'], hashlib.sha256(result_path.read_bytes()).hexdigest())
        self.assertEqual(report['stream_sha256'], hashlib.sha256(stream_path.read_bytes()).hexdigest())
        self.assertEqual((fixture.session / 'r2-sdk.exit').read_text().strip(), '0')
        result = self.command(
            'prepare', fixture.session, '2x', '--phase', 'repair',
            '--assignment', 'sol=' + parent['bundle'], '--parent-assignment', '2:sdk',
            environment=fixture.env)
        self.assertEqual(result.returncode, 0,
                         'numeric terminal failure needs its existing bounded repair route: ' + result.stderr)
        child = copy.copy(fixture)
        child.label = '2x'
        child.phase = 'repair'
        child.manifest_path = fixture.session / 'r2x-evidence.manifest.json'
        child.manifest = json.loads(child.manifest_path.read_text())
        assignment = child.manifest['assignments']['sol']
        binding = child.manifest['parent_assignment']
        self.assertEqual(child.manifest['phase'], 'repair')
        self.assertEqual(set(child.manifest['assignments']), {'sol'})
        self.assertEqual((binding['manifest'], binding['manifest_sha256'], binding['seat']),
                         ('r2-evidence.manifest.json', hashlib.sha256(parent_bytes).hexdigest(), 'sdk'))
        self.assertEqual(binding['assignment_sha256'], hashlib.sha256(
            (json.dumps(parent, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode()).hexdigest())
        self.assertEqual((binding['model'], binding['effort']),
                         (fixture.roster['seats'][2]['model'], 'xhigh'))
        self.assertEqual(fixture.manifest['numeric']['round'], 2)
        self.assertEqual(fixture.manifest['numeric']['min_rounds'], 1)
        self.assertEqual((assignment['bundle'], assignment['emphasis'], assignment['scope'],
                          assignment['full_state']),
                         (parent['bundle'], parent['emphasis'], 'full', True))
        self.assertEqual(Path(assignment['patch']).read_bytes(),
                         (fixture.session / 'r2-full.patch').read_bytes())
        self.assertEqual(child.manifest['source'], fixture.manifest['source'])
        self.assertEqual(child.manifest['snapshot_tree'], fixture.manifest['snapshot_tree'])
        prompt_command = [str(SCRIPTS / 'rev-prompt.sh'), str(fixture.session), '2x',
                          'sol', parent['bundle'], parent['emphasis'],
                          '--evidence', str(child.manifest_path)]
        for emphasis, phase in ((parent['emphasis'] + ' changed', 'numeric'),
                                (parent['emphasis'], 'risk')):
            invalid = list(prompt_command)
            invalid[5] = emphasis
            result = subprocess.run(invalid + ['--phase', phase], env=fixture.env,
                                    capture_output=True, text=True, timeout=40)
            self.assertNotEqual(result.returncode, 0, 'numeric repair cannot change emphasis or phase')
        result = subprocess.run(prompt_command + ['--phase', 'numeric'], env=fixture.env,
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, 'repair must retain its numeric covered phase: ' + result.stderr)
        self.proofs(child)
        evidence = self.evidence()
        with patch.object(evidence, 'validate_cursor_sdk_qualification'):
            evidence.verify_panel_selection(fixture.session, '2', ['sdk=2x'])
            sibling = fixture.session / 'r2-luna.json'
            original = sibling.read_bytes()
            sibling.write_text('{"summary":"INCOMPLETE PROOF: second failure","findings":[]}\n')
            try:
                result = self.command(
                    'prepare', fixture.session, '2x', '--phase', 'repair',
                    '--assignment', 'sol=' + parent['bundle'], '--parent-assignment', '2:luna',
                    environment=fixture.env)
                self.assertNotEqual(result.returncode, 0, 'a numeric panel permits only one replacement')
                self.assertIn('panel already has a replacement', result.stderr)
                with self.assertRaisesRegex(ValueError, 'at most one replacement'):
                    evidence.verify_panel_selection(fixture.session, '2', ['sdk=2x', 'luna=2x'])
            finally:
                sibling.write_bytes(original)
            with redirect_stdout(io.StringIO()):
                evidence.receipt(SimpleNamespace(session=str(fixture.session), label='2',
                                                 replacement=['sdk=2x']))
        receipt = json.loads((fixture.session / 'r2-coverage.receipt.json').read_text())
        self.assertEqual(receipt['phase'], 'numeric')
        selected = receipt['selected_generations']
        self.assertEqual((selected['sdk']['label'], selected['sdk']['seat']), ('2x', 'sol'))
        self.assertEqual((selected['sol']['label'], selected['luna']['label']), ('2', '2'))
        self.assertEqual(fixture.manifest_path.read_bytes(), parent_bytes)
        for path, original in siblings.items():
            self.assertEqual(path.read_bytes(), original, 'replacement must retain valid siblings')
        self.assertFalse((fixture.session / 'coverage-head.json').exists())

    def test_numeric_opaque_extra_refuses_only_when_scheduled(self):
        fixture = self.fixture('extra-dormant', extra=True)
        self.prepare(fixture)
        self.assertEqual(set(fixture.manifest['assignments']), {'sol', 'luna', 'sdk'})
        active = self.fixture('extra-active', 3, extra=True)
        result = self.command(
            'prepare', active.session, '3', '--phase', 'numeric', '--numeric-round', '3',
            '--numeric-min-rounds', '3', '--numeric-panel', active.panel, environment=active.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(EXTRA_REASON, result.stderr)
        self.assertFalse(active.manifest_path.exists(), 'opaque extra cannot leave a usable numeric manifest')

    def test_non_sdk_legacy_numeric_render_remains_manifestless(self):
        fixture = self.fixture('legacy', 2, sdk=False)
        before = set(fixture.session.glob('*evidence.manifest.json'))
        result = self.render(fixture, evidence=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(fixture.session.glob('*evidence.manifest.json')), before)
        for seat, lens, emphasis in fixture.rows:
            prompt = (fixture.session / f'r2-{seat}.prompt.md').read_text()
            self.assertIn('## Your lens this round: ' + lens, prompt)
            self.assertIn('Round emphasis: ' + emphasis, prompt)
            self.assertNotIn('Evidence manifest SHA-256:', prompt)

    def test_numeric_evidence_refuses_a_roster_without_sdk(self):
        fixture = self.fixture('numeric-no-sdk', 2, sdk=False)
        control = self.render(fixture, evidence=False)
        self.assertEqual(control.returncode, 0, control.stderr)
        result = self.command(
            'prepare', fixture.session, '2', '--phase', 'numeric', '--numeric-round', '2',
            '--numeric-min-rounds', '1', '--numeric-panel', fixture.panel, environment=fixture.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('numeric evidence requires cursor-sdk', result.stderr)

    def test_sdk_document_roster_refuses_before_auth_catalog_or_provider_work(self):
        with patch.dict(os.environ, self.env, clear=True):
            roster = module(SCRIPTS / 'lib/roster.py')
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(roster, 'load_config', return_value=({'cursor_sdk_models': ['latest-grok']}, None)), \
                patch.object(roster, 'prepare_cursor_sdk_config', side_effect=AssertionError('SDK discovery before mode guard')), \
                patch.object(roster, 'run', side_effect=AssertionError('provider process before mode guard')), \
                redirect_stdout(output), redirect_stderr(errors):
            code = self.roster_code(roster, ['--review-mode', 'documents', '--probe', '--json'])
        self.assertEqual(code, 6, 'SDK documents require a static unsupported-mode refusal')
        self.assertIn(DOCUMENT_REASON, output.getvalue() + errors.getvalue())

    def test_non_sdk_document_mode_keeps_existing_availability_result(self):
        for config in ({'extras': False}, {'extras': False, 'cursor_sdk_models': []}):
            with self.subTest(config=config):
                with patch.dict(os.environ, self.env, clear=True):
                    roster = module(SCRIPTS / 'lib/roster.py')
                detectors = {name: (lambda _cfg: ([], 'offline absence')) for name in roster.DETECT}
                output, errors = io.StringIO(), io.StringIO()
                with patch.dict(os.environ, self.env, clear=True), \
                        patch.object(roster, 'load_config', return_value=(config, None)), \
                        patch.object(roster, 'DETECT', detectors), \
                        patch.object(roster, 'anthropic_adapter', return_value='claude'), \
                        patch.object(roster, 'run', side_effect=AssertionError('no provider process expected')), \
                        redirect_stdout(output), redirect_stderr(errors):
                    code = self.roster_code(roster, ['--review-mode', 'documents', '--probe', '--json'])
                self.assertEqual(code, 5, 'empty SDK document mode keeps ordinary unavailable-provider status')
                self.assertNotIn(DOCUMENT_REASON, output.getvalue() + errors.getvalue())

    def test_document_renderer_rejects_sdk_roster_without_publishing_any_prompt(self):
        fixture = self.fixture('documents')
        document = fixture.root / 'public-note.md'
        document.write_text('A public synthetic document.\n')
        listing = fixture.session / 'docs.txt'
        listing.write_text(str(document) + '\n')
        roster_path = fixture.session / 'roster.json'
        roster_path.write_text(json.dumps({'seats': fixture.roster['seats'][:2]}))
        control = subprocess.run([
            str(SCRIPTS / 'rev-prompt.sh'), str(fixture.session), 'docs-control',
            'sol', 'correctness', 'Read the public document', '--read-only', str(listing)],
            env=fixture.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(control.returncode, 0, control.stderr)
        roster_path.write_text(json.dumps(fixture.roster))
        result = subprocess.run([
            str(SCRIPTS / 'rev-prompt.sh'), str(fixture.session), 'docs', '--panel', str(fixture.panel),
            '--read-only', str(listing)], env=fixture.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, 'manifestless SDK documents must refuse before rendering')
        self.assertIn(DOCUMENT_REASON, result.stderr)
        self.assertFalse(list(fixture.session.glob('rdocs-*.prompt.md')))

    def test_actual_cursor_stack_numeric_route_requires_a_fresh_ready_receipt(self):
        bundle = module(REPO / 'scripts/build-cursor-plugin.py').build(self.directory / 'bundle/review-council')
        (bundle / 'scripts/roster.sh').write_text('#!/bin/bash\nexit 0\n')
        bindir = self.directory / 'bin'
        bindir.mkdir()
        capture = self.directory / 'cursor-route.json'
        for name in ('agent', 'cursor-agent'):
            executable = bindir / name
            executable.write_text(
                '#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
                'Path(os.environ["ROUTE_CAPTURE"]).write_text(json.dumps({"argv":sys.argv[1:],'
                '"host":os.environ.get("REVIEW_COUNCIL_HOST"),"leg":os.environ.get("REV_STACK_LEG")}))\n')
            executable.chmod(0o755)
        config = self.directory / 'stack-config.sh'
        config.write_text('legs() { run_leg "' + str(self.directory) + '" 1 fixture "Read-only route control"; }\n')
        root = self.directory / 'stack-session'
        result = subprocess.run([str(bundle / 'scripts/stack.sh'), str(config)],
            env=dict(self.env, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                     ROOT=str(root), LOG=str(self.directory / 'stack.log'), ROUTE_CAPTURE=str(capture),
                     NO_PUSH='1', NO_SQUASH='1', REV_STACK_FOREGROUND='1', PASSES='1', POLL='1',
                     MAX_ATTEMPTS='1', MAX_INFRA_RETRIES='0', AUTH_WAIT_TRIES='1', STALL_SECS='30'),
            capture_output=True, text=True, timeout=25)
        self.assertTrue(capture.is_file(), 'real stack routing must launch the offline Cursor double')
        call = json.loads(capture.read_text())
        self.assertEqual((call['host'], call['leg']), ('cursor', '1'))
        self.assertIn('Review branch 1 rounds', ' '.join(call['argv']))
        self.assertIn(str(bundle / 'cursor-skills/rev/SKILL.md'), ' '.join(call['argv']))
        self.assertNotEqual(result.returncode, 0, 'zero CLI exit alone cannot complete a numeric stack')
        self.assertIn('invalid completion receipt', result.stdout)
        self.assertFalse((root / 'fixture/stack-report.md').exists())
        self.assertFalse((root / 'fixture/report.md').exists())
