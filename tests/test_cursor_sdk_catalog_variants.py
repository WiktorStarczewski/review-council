"""Offline catalog admission uses synthetic proof, never live qualification."""

import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch

import test_cursor_sdk_attempt_lifetime as attempt_cases
from test_cursor_sdk import CursorSDKCase, SCRIPTS, module
from test_cursor_sdk_runtime import RuntimeFixture


MODEL = 'grok-4.7'


def catalog_model():
    variants = []
    for context in ('256k', '500k'):
        for effort in ('low', 'medium', 'high', 'xhigh'):
            for fast in ('false', 'true'):
                variant = {'params': [{'id': 'context', 'value': context},
                                      {'id': 'reasoning_effort', 'value': effort},
                                      {'id': 'fast', 'value': fast}],
                           'displayName': 'Grok 4.7 ' + effort}
                if context == '500k':
                    variant['isMaxMode'] = True
                if (context, effort, fast) == ('500k', 'high', 'true'):
                    variant['isDefault'] = True
                variants.append(variant)
    return {'id': MODEL, 'displayName': 'Grok 4.7', 'parameters': [
        {'id': 'context', 'values': [{'value': value} for value in ('256k', '500k')]},
        {'id': 'reasoning_effort', 'values': [
            {'value': value} for value in ('low', 'medium', 'high', 'xhigh')]},
        {'id': 'fast', 'values': [{'value': value} for value in ('false', 'true')]},
    ], 'variants': variants}


def selections():
    selected = []
    for variant in catalog_model()['variants']:
        if {'id': 'reasoning_effort', 'value': 'xhigh'} not in variant['params']:
            continue
        value = {'id': MODEL, 'params': copy.deepcopy(variant['params'])}
        if 'isMaxMode' in variant:
            value['maxMode'] = variant['isMaxMode']
        selected.append(value)
    return selected


class CursorSDKCatalogVariantTests(CursorSDKCase):
    source = attempt_cases.CursorSDKAttemptLifetimeTests.source
    qualification = attempt_cases.CursorSDKAttemptLifetimeTests.qualification

    def events(self):
        events = attempt_cases.CursorSDKAttemptLifetimeTests.events(self)
        for event in events:
            if 'model' in event:
                event['model'] = copy.deepcopy(self.selected)
        return events

    def fixture(self, selected):
        number = getattr(self, 'fixture_number', 0) + 1
        self.fixture_number = number
        directory = self.directory / ('variant-' + str(number))
        directory.mkdir(mode=0o700)
        fixture = RuntimeFixture(directory)
        shutil.copytree(SCRIPTS.parent / 'schema', fixture.scripts.parent / 'schema')
        fixture.env = dict(self.env, REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=str(fixture.runtime),
                           GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@invalid',
                           GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@invalid')
        fixture.catalog = {'version': 1, 'sdk_version': '1.0.38',
                           'runtime_sha256': 'a' * 64, 'models': [catalog_model()]}
        self.selected = copy.deepcopy(selected)
        with patch.object(attempt_cases, 'SELECTION', self.selected):
            fixture.receipt = self.qualification(fixture)
        fixture.env['REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION'] = str(fixture.receipt)
        fixture.roster = module(fixture.scripts / 'lib/roster.py')
        fixture.selected = copy.deepcopy(selected)
        return fixture

    def prepare(self, fixture, requested='latest-grok'):
        config = {'cursor_sdk_models': [requested]}
        original = copy.deepcopy(config)
        stdout = json.dumps(fixture.catalog)
        proof = json.loads(fixture.receipt.read_text())
        frozen = {path: path.read_bytes() for path in
                  [fixture.receipt, fixture.runtime / '.qualification-key',
                   *map(Path, proof['evidence'])]}
        with patch.dict(os.environ, fixture.env, clear=True), \
                patch.object(fixture.roster, 'run', return_value=(0, stdout, '')) as run:
            effective, error, cause = fixture.roster.prepare_cursor_sdk_config(config)
        self.assertEqual(config, original)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0],
                         ['node', str(fixture.scripts / 'lib/cursor-sdk-driver.mjs'), 'catalog'])
        for path, content in frozen.items():
            self.assertEqual(path.read_bytes(), content)
        return effective, error, cause

    def accepted(self, fixture, requested='latest-grok'):
        effective, error, cause = self.prepare(fixture, requested)
        self.assertIsNone(error, 'a uniquely matching qualified variant must resolve: ' + str(error))
        self.assertIsNone(cause)
        self.assertEqual(effective['cursor_sdk_models'], [MODEL])
        self.assertEqual(effective['cursor_sdk_model_selections'], [fixture.selected])
        self.assertEqual(effective['cursor_sdk_effort'], 'xhigh')
        identity = fixture.roster._RESOLVED['cursor_sdk_identity']
        self.assertEqual(identity['catalog_sha256'],
                         hashlib.sha256(json.dumps(fixture.catalog).encode()).hexdigest())
        self.assertEqual(identity['qualification_sha256'],
                         hashlib.sha256(fixture.receipt.read_bytes()).hexdigest())
        seat = fixture.roster.make_seat('grok', 'cursor-sdk', MODEL, 'xhigh')
        seat.update(model_selection=fixture.selected, cursor_sdk=identity)
        fixture.roster.validate_cursor_sdk_qualification(seat)

    def refused(self, fixture, requested='latest-grok'):
        effective, error, cause = self.prepare(fixture, requested)
        self.assertEqual(cause, 'availability')
        self.assertTrue(error)
        self.assertFalse(effective.get('cursor_sdk_model_selections'))
        self.assertNotIn('cursor_sdk_identity', fixture.roster._RESOLVED)
        return error

    def rewrite_selection(self, fixture, selected):
        proof = json.loads(fixture.receipt.read_text())
        proof.pop('signature')
        if selected is None:
            proof.pop('selection')
        else:
            proof['selection'] = selected
        payload = json.dumps(proof, ensure_ascii=False, separators=(',', ':')).encode()
        secret = (fixture.runtime / '.qualification-key').read_bytes()
        proof['signature'] = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        fixture.receipt.write_text(json.dumps(proof, ensure_ascii=False) + '\n')

    def test_qualified_xhigh_variants_preserve_all_parameters_and_max_mode(self):
        for selected in selections() + [dict(selections()[0], maxMode=False)]:
            with self.subTest(selection=selected):
                self.accepted(self.fixture(selected))

    def test_exact_model_request_uses_its_unique_qualified_variant(self):
        fixture = self.fixture(selections()[-1])
        model = fixture.catalog['models'][0]
        variants = model['variants']
        model['variants'] = [variant for variant in variants
                             if variant['params'] == fixture.selected['params']]
        self.accepted(fixture, MODEL)
        model['variants'] = variants
        self.accepted(fixture, MODEL)

    def test_bare_pure_resolver_keeps_multi_variant_catalog_ambiguous(self):
        roster = module(SCRIPTS / 'lib/roster.py')
        config = {'cursor_sdk_models': ['latest-grok']}
        with patch('subprocess.Popen', side_effect=AssertionError('pure resolver cannot launch')):
            effective, error, cause = roster.resolve_cursor_sdk_config(config, [catalog_model()])
        self.assertEqual(cause, 'availability')
        self.assertIn('ambiguous', error)
        self.assertFalse(effective.get('cursor_sdk_model_selections'))
        self.assertEqual(config, {'cursor_sdk_models': ['latest-grok']})

    def test_qualified_variant_must_be_unique_present_and_advertised(self):
        for mutation in ('missing', 'duplicate', 'duplicate-different-max', 'undefined-value', 'max-mode'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture(selections()[-1])
                model = fixture.catalog['models'][0]
                selected = next(variant for variant in model['variants']
                                if variant['params'] == fixture.selected['params'])
                if mutation == 'missing':
                    model['variants'].remove(selected)
                elif mutation in ('duplicate', 'duplicate-different-max'):
                    duplicate = copy.deepcopy(selected)
                    if mutation == 'duplicate-different-max':
                        duplicate['isMaxMode'] = False
                    model['variants'].append(duplicate)
                elif mutation == 'undefined-value':
                    model['parameters'][2]['values'] = [{'value': 'false'}]
                else:
                    selected['isMaxMode'] = False
                self.refused(fixture)

    def test_older_qualification_cannot_replace_newest_requested_grok(self):
        fixture = self.fixture(selections()[-1])
        newer = copy.deepcopy(fixture.catalog['models'][0])
        newer['id'] = 'grok-4.8'
        fixture.catalog['models'].append(newer)
        self.refused(fixture)

    def test_variant_selection_retains_real_hmac_and_evidence_checks(self):
        for multiple in (False, True):
            for mutation in ('signature', 'evidence'):
                with self.subTest(multiple=multiple, mutation=mutation):
                    fixture = self.fixture(selections()[-1])
                    if not multiple:
                        model = fixture.catalog['models'][0]
                        model['variants'] = [variant for variant in model['variants']
                                             if variant['params'] == fixture.selected['params']]
                    proof = json.loads(fixture.receipt.read_text())
                    if mutation == 'signature':
                        proof['signature'] = '0' * 64
                        fixture.receipt.write_text(json.dumps(proof) + '\n')
                    else:
                        Path(proof['result']).write_text('{"summary":"changed","findings":[]}\n')
                    error = self.refused(fixture)
                    if not multiple:
                        self.assertIn('qualification', error)

    def test_missing_invalid_or_partial_qualification_cannot_choose_a_default(self):
        selected = selections()[-1]
        partial = copy.deepcopy(selected)
        partial['params'] = partial['params'][:-1]
        invalid = dict(selected, maxMode='true')
        for value in (None, invalid, partial):
            with self.subTest(selection=value):
                fixture = self.fixture(selected)
                self.rewrite_selection(fixture, value)
                self.refused(fixture)
