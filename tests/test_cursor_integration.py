"""Offline SDK integration contracts; synthetic inputs cannot qualify a live seat."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from test_cursor_sdk import CursorSDKCase, FIXTURES, SELECTION, SCRIPTS, module
from test_deleted_source_proof import SourceFixture


class CursorIntegrationTests(CursorSDKCase):
    def sdk_seat(self, directory=None):
        directory = directory or self.directory
        runtime = directory / 'runtime'
        runtime.mkdir(exist_ok=True)
        qualification = directory / 'synthetic-nonqualifying-receipt.json'
        qualification.write_text('{"synthetic":true}\n')
        return {
            'seat': 'sdk', 'adapter': 'cursor-sdk', 'lab': 'xai', 'model': SELECTION['id'],
            'effort': 'xhigh', 'extra': False, 'model_selection': copy.deepcopy(SELECTION),
            'cursor_sdk': {
                'sdk_version': '1.0.38', 'runtime_sha256': 'a' * 64,
                'catalog_sha256': 'b' * 64, 'runtime_path': str(runtime),
                'qualification_path': str(qualification),
                'qualification_sha256': hashlib.sha256(qualification.read_bytes()).hexdigest(),
                'provenance': {'transport': 'Cursor', 'model_lineage': ['Cursor', 'SpaceXAI'],
                               'laboratory': 'xai'},
            },
        }

    def identity(self):
        function = getattr(module(SCRIPTS / 'lib/roster.py'), 'cursor_sdk_identity', None)
        self.assertTrue(callable(function),
                        'SDK integration requires one frozen model/runtime/qualification identity')
        return function

    def test_sdk_closed_auth_and_quota_labels_keep_provider_failure_classes(self):
        roster = module(SCRIPTS / 'lib/roster.py')
        for label, expected in (('sdk_unauthenticated', 'auth'), ('sdk_quota', 'quota')):
            with self.subTest(label=label):
                self.assertEqual(roster.classify_provider_failure(
                    'cursor-sdk', stderr=label + '\n')[0], expected,
                    'closed SDK labels must survive roster availability classification')
                self.assertEqual(roster.classify_provider_failure(
                    'cursor-sdk', summary_log=label + '\n')[0], expected)
        self.assertEqual(roster.classify_provider_failure(
            'cursor-sdk', summary_log='text: sdk_quota\n')[0], 'other')

    def seat_transport(self, directory, code, mutate=False):
        scripts = directory / 'scripts'
        shutil.copytree(SCRIPTS, scripts)
        adapter = scripts / 'seats.d/cursor-sdk.sh'
        adapter.chmod(0o755)
        adapter.write_text(
            '#!/bin/bash\n'
            'printf "called\\n" >> "$LOG.launches"\n'
            'printf "%s\\n%s\\n" "$REVIEW_COUNCIL_CURSOR_SDK_RUNTIME" '
            '"$REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION" > "$LOG.environment"\n'
            'exit ' + str(code) + '\n')
        session = directory / 'session'
        session.mkdir()
        row = self.sdk_seat(directory)
        (session / 'roster.json').write_text(json.dumps({'seats': [row]}))
        prompt = session / 'r1-sdk.prompt.md'
        prompt.write_text('Synthetic wrapper test only. No provider or source proof.\n')
        if mutate:
            Path(row['cursor_sdk']['qualification_path']).write_text('{"changed":true}\n')
        environment = dict(self.env, REV_REPO=str(directory),
                           REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=str(directory / 'ambient-runtime'),
                           REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION=str(directory / 'ambient-receipt'))
        result = subprocess.run([str(scripts / 'rev-seat.sh'), 'sdk', str(session), '1', str(prompt)],
                                env=environment, text=True, capture_output=True, timeout=15)
        return result, session, row

    def test_sdk_wrapper_preserves_exact_driver_failures_once_and_frozen_runtime_paths(self):
        for code in (1, 2, 3, 4):
            with self.subTest(exit=code):
                directory = self.directory / str(code)
                directory.mkdir()
                result, session, row = self.seat_transport(directory, code)
                launches = session / 'r1-sdk.log.launches'
                self.assertTrue(launches.is_file(), 'SDK wrapper must launch its selected adapter')
                self.assertEqual(launches.read_text(), 'called\n', 'failure must never retry the SDK')
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertEqual((session / 'r1-sdk.exit').read_text(), str(code) + '\n')
                self.assertEqual((session / 'r1-sdk.log.environment').read_text().splitlines(), [
                    row['cursor_sdk']['runtime_path'], row['cursor_sdk']['qualification_path']])
                self.assertFalse((session / 'r1-sdk.json').exists(),
                                 'synthetic failed transport cannot publish findings or proof')

    def test_sdk_wrapper_refuses_changed_frozen_qualification_before_adapter_launch(self):
        result, session, _ = self.seat_transport(self.directory, 3, mutate=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((session / 'r1-sdk.log.launches').exists(),
                         'changed qualification must be rejected before any provider adapter')

    def test_sdk_identity_rejects_model_effort_runtime_and_lineage_substitution(self):
        identity = self.identity()
        row = self.sdk_seat()
        expected = {key: row[key] for key in ('model_selection', 'cursor_sdk')}
        self.assertEqual(identity(row), expected)
        for mutation in ('model', 'effort', 'selection', 'runtime', 'qualification', 'lineage'):
            with self.subTest(mutation=mutation):
                altered = copy.deepcopy(row)
                if mutation == 'model':
                    altered['model'] = 'grok-other'
                elif mutation == 'effort':
                    altered['effort'] = 'high'
                elif mutation == 'selection':
                    altered['model_selection']['params'][0]['value'] = 'high'
                elif mutation == 'runtime':
                    altered['cursor_sdk']['runtime_sha256'] = 'unknown'
                elif mutation == 'qualification':
                    del altered['cursor_sdk']['qualification_sha256']
                else:
                    altered['cursor_sdk']['provenance']['laboratory'] = 'cursor'
                with self.assertRaises(ValueError):
                    identity(altered)
        with self.assertRaises(ValueError):
            identity({key: row[key] for key in row if key != 'cursor_sdk'})

    def test_provider_contract_freezes_sdk_selection_catalog_runtime_and_qualification(self):
        self.identity()
        contract = module(SCRIPTS / 'rev-contract-check.py')
        row = self.sdk_seat()
        path = self.directory / 'roster.json'
        path.write_text(json.dumps({'seats': [row]}))
        baseline = contract.core_roster(path)
        self.assertEqual(baseline, [{key: row[key] for key in (
            'seat', 'adapter', 'model', 'effort', 'model_selection', 'cursor_sdk')}])
        for key in ('runtime_sha256', 'catalog_sha256', 'qualification_sha256'):
            altered = copy.deepcopy(row)
            altered['cursor_sdk'][key] = 'd' * 64
            path.write_text(json.dumps({'seats': [altered]}))
            self.assertNotEqual(contract.core_roster(path), baseline,
                                'contract reuse must detect changed SDK ' + key)

    def sdk_source(self):
        row = self.sdk_seat()

        class SDKFixture(SourceFixture):
            def run(source, *arguments):
                if arguments[0] == 'prepare':
                    path = source.session / 'roster.json'
                    roster = json.loads(path.read_text())
                    roster['seats'][0] = dict(row, seat='sol')
                    path.write_text(json.dumps(roster))
                return super().run(*arguments)

        directory = self.directory / 'source-fixture'
        directory.mkdir()
        return SDKFixture(directory, 'current'), row

    def test_evidence_assignment_freezes_sdk_identity_and_rejects_rebinding(self):
        fixture, row = self.sdk_source()
        assignment = fixture.manifest['assignments'][fixture.seat]
        expected = {key: row[key] for key in ('model_selection', 'cursor_sdk')}
        self.assertEqual({key: assignment.get(key) for key in expected}, expected,
                         'SDK assignments must preserve exact frozen selection and qualification')
        evidence = module(SCRIPTS / 'rev-evidence.py')
        evidence.validated_manifest(fixture.manifest_path)
        altered = copy.deepcopy(fixture.manifest)
        altered['assignments'][fixture.seat]['cursor_sdk']['qualification_sha256'] = 'd' * 64
        fixture.manifest_path.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'SDK|sdk'):
            evidence.validated_manifest(fixture.manifest_path)

    def test_sdk_prompt_names_the_qualified_reader_and_original_canonical_read_bounds(self):
        fixture, _ = self.sdk_source()
        text = fixture.prompt.read_text()
        self.assertIn('council_read', text, 'SDK prompt must name its only available reader')
        self.assertIn('Patch chunk batch limit: 1', text)
        self.assertIn('Source context packet batch limit: 1', text)
        self.assertIn('in full', text)
        self.assertNotIn('use read_file', text)

    def test_sdk_receipt_serialization_retains_identity_and_refuses_unbound_sdk_rows(self):
        fixture, row = self.sdk_source()
        evidence = module(SCRIPTS / 'rev-evidence.py')
        stem = 'r' + fixture.label + '-' + fixture.seat
        hashes = {stem + suffix: 'e' * 64 for suffix in (
            '.prompt.md', '.stream.ndjson', '.json', '.read-audit.json', '.exit')}
        with patch.object(evidence, 'validate_results', return_value=hashes):
            _, generation = evidence.result_generation(
                fixture.session, fixture.manifest, 'f' * 64, fixture.seat)
        self.assertEqual({key: generation.get(key) for key in ('model_selection', 'cursor_sdk')},
                         {key: row[key] for key in ('model_selection', 'cursor_sdk')},
                         'receipt serialization must retain the validated SDK proof identity')
        roster_path = fixture.session / 'roster.json'
        roster = json.loads(roster_path.read_text())
        del roster['seats'][0]['cursor_sdk']
        roster_path.write_text(json.dumps(roster))
        del fixture.manifest['assignments'][fixture.seat]['cursor_sdk']
        with patch.object(evidence, 'validate_results', return_value=hashes), \
                self.assertRaisesRegex(ValueError, 'SDK|sdk'):
            evidence.result_generation(fixture.session, fixture.manifest, 'f' * 64, fixture.seat)

    def test_profile_identity_distinguishes_sdk_runtime_and_qualification_changes(self):
        profile = module(SCRIPTS / 'rev-profile.py')
        row = self.sdk_seat()
        path = self.directory / 'roster.json'
        path.write_text(json.dumps({'seats': [row]}))
        baseline = profile.roster_identity(self.directory)
        self.assertTrue(baseline['complete'])
        self.assertEqual(baseline['core_seats'][0].get('cursor_sdk'), row['cursor_sdk'],
                         'profile comparability must retain the exact SDK proof identity')
        for key in ('runtime_sha256', 'catalog_sha256', 'qualification_sha256'):
            altered = copy.deepcopy(row)
            altered['cursor_sdk'][key] = 'd' * 64
            path.write_text(json.dumps({'seats': [altered]}))
            self.assertNotEqual(profile.roster_identity(self.directory)['signature'],
                                baseline['signature'])

    def test_opted_in_sdk_missing_runtime_is_availability_and_never_falls_through(self):
        config = {'cursor_sdk_models': ['latest-grok'], 'extras': False}
        with patch.dict(os.environ, self.env, clear=True):
            roster = module(SCRIPTS / 'lib/roster.py')
            detectors = {adapter: lambda _config: ([], None) for adapter in roster.DETECT}
            with patch.object(roster, 'load_config', return_value=(config, None)), \
                    patch.object(roster, 'DETECT', detectors), \
                    patch.object(roster.shutil, 'which', return_value=None), \
                    patch.object(roster, 'run', side_effect=AssertionError('no SDK turn allowed')):
                result, _, strict = roster.build(False)
        self.assertEqual(strict, 'availability', 'explicit SDK availability must be enforced')
        reason = result.get('strict_reason', '').lower()
        self.assertTrue(('cursor-sdk' in reason or 'cursor_sdk' in reason) and 'runtime' in reason,
                        'availability must identify the missing SDK runtime, not a generic host floor')
        self.assertEqual(result['seats'], [], 'a missing SDK cannot be replaced with another transport')

    def test_reported_sdk_usage_is_normalized_without_inventing_a_known_cost(self):
        usage = module(SCRIPTS / 'lib/usage.py')
        terminal = json.loads((FIXTURES / 'cursor-sdk-stream.ndjson').read_text().splitlines()[-1])
        terminal['usage'] = {'inputTokens': 13, 'outputTokens': 5, 'cacheReadTokens': 2,
                             'cacheWriteTokens': 3, 'totalTokens': 18, 'reasoningTokens': 4}
        path = self.directory / 'usage.ndjson'
        path.write_text(json.dumps(terminal) + '\n')
        reported, _, _, invalid = usage.read_stream(path, 'cursor-sdk')
        self.assertEqual(invalid, [])
        self.assertIsNotNone(reported, 'reported SDK usage must not disappear as unknown tokens')
        self.assertEqual({key: reported[key] for key in (
            'input_tokens', 'output_tokens', 'processed_tokens', 'cache_read_input_tokens',
            'cache_write_input_tokens', 'reasoning_output_tokens', 'cost_usd_known_calls',
            'cost_usd_unknown_calls')}, {
                'input_tokens': 13, 'output_tokens': 5, 'processed_tokens': 18,
                'cache_read_input_tokens': 2, 'cache_write_input_tokens': 3,
                'reasoning_output_tokens': 4, 'cost_usd_known_calls': 0,
                'cost_usd_unknown_calls': 1})


if __name__ == '__main__':
    unittest.main()
