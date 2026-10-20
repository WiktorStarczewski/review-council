"""Offline extraction boundary only; synthetic inputs provide no qualification or review credit."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1] / 'plugins/review-council'
SCRIPTS = PLUGIN / 'scripts'
STREAM = PLUGIN / 'tests/fixtures/cursor-sdk-stream.ndjson'

ADAPTER = r'''#!/bin/bash
# LOCAL TEST adapter: emulate driver artifacts and preserve its exit, without importing an SDK.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
printf 'called\n' >> "$LOG.launches"
cp "${OUT%/*}/fixture.stream.ndjson" "$RAW"
cp "${OUT%/*}/fixture.published.json" "$OUT"
python3 -u "$HERE/../lib/stream-summary.py" cursor-sdk "$OUT.summary-candidate.json" < "$RAW" >> "$LOG"
printf '%s\n' "$?" > "$LOG.summary-exit"
exit DRIVER_EXIT
'''

DOWNSTREAM_AUDIT = '''"""LOCAL TEST stub: observe downstream entry; no source audit or qualification occurs."""
import json
import os
from pathlib import Path
import sys

with open(os.environ['LOG'] + '.downstream-calls', 'a') as marker:
    marker.write('LOCAL TEST audit called\\n')
output = Path(sys.argv[sys.argv.index('--out') + 1])
output.write_text(json.dumps({
    'schema_version': 2, 'status': 'valid', 'evidence_scoped': False,
    'narrow': False, 'violations': [], 'evidence_manifest_sha256': None,
    'local_test_stub': 'No source proof, qualification or review credit',
}))
'''


class CursorSDKResultGateTests(unittest.TestCase):
    def events(self):
        return [json.loads(line) for line in STREAM.read_text().splitlines() if line.strip()]

    def wrapper(self, events, published, driver_exit=0):
        temporary = tempfile.TemporaryDirectory(prefix='sdk-result-gate-')
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name).resolve()
        scripts = directory / 'scripts'
        shutil.copytree(SCRIPTS, scripts)
        schema = directory / 'schema'
        shutil.copytree(PLUGIN / 'schema', schema)
        for tree in (scripts, schema):
            for path in [tree, *tree.rglob('*')]:
                path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        adapter = scripts / 'seats.d/cursor-sdk.sh'
        adapter.chmod(0o755)
        adapter.write_text(ADAPTER.replace('DRIVER_EXIT', str(driver_exit)))
        auditor = scripts / 'lib/review-read-audit.py'
        auditor.chmod(0o644)
        auditor.write_text(DOWNSTREAM_AUDIT)
        for relative in ('rev-seat.sh', 'lib/stream-summary.py', 'lib/validate-findings.py'):
            self.assertEqual((scripts / relative).read_bytes(), (SCRIPTS / relative).read_bytes())
        self.assertEqual((directory / 'schema/findings.schema.json').read_bytes(),
                         (PLUGIN / 'schema/findings.schema.json').read_bytes())

        session = directory / 'session'
        session.mkdir()
        runtime = directory / 'empty-runtime'
        runtime.mkdir()
        receipt = directory / 'synthetic-nonqualifying-receipt.json'
        receipt.write_text('{"synthetic":true}\n')
        selection = self.events()[-1]['model']
        row = {
            'seat': 'sdk', 'adapter': 'cursor-sdk', 'lab': 'xai',
            'model': selection['id'], 'effort': 'xhigh', 'mode': 'exec', 'extra': False,
            'model_selection': selection,
            'cursor_sdk': {
                'sdk_version': '1.0.38', 'runtime_sha256': 'a' * 64,
                'catalog_sha256': 'b' * 64, 'runtime_path': str(runtime),
                'qualification_path': str(receipt),
                'qualification_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest(),
                'provenance': {'transport': 'Cursor', 'model_lineage': ['Cursor', 'SpaceXAI'],
                               'laboratory': 'xai'},
            },
        }
        (session / 'roster.json').write_text(json.dumps({'seats': [row]}))
        prompt = session / 'r1-sdk.prompt.md'
        prompt.write_text('LOCAL TEST extraction boundary. No provider, source proof or qualification.\n')
        stream = ''.join(json.dumps(event) + '\n' for event in events)
        (session / 'fixture.stream.ndjson').write_text(stream)
        (session / 'fixture.published.json').write_text(json.dumps(published))
        environment = {
            'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(directory),
            'REV_REPO': str(directory), 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONNOUSERSITE': '1',
        }
        process = subprocess.run(
            ['/bin/bash', str(scripts / 'rev-seat.sh'), 'sdk', str(session), '1', str(prompt)],
            env=environment, capture_output=True, text=True, timeout=20)
        artifacts = {
            'out': session / 'r1-sdk.json',
            'candidate': session / 'r1-sdk.json.summary-candidate.json',
            'summary_exit': session / 'r1-sdk.log.summary-exit',
            'downstream': session / 'r1-sdk.log.downstream-calls',
            'exit': session / 'r1-sdk.exit',
            'log': session / 'r1-sdk.log',
        }
        self.assertEqual((session / 'r1-sdk.log.launches').read_text(), 'called\n',
                         'the wrapper must launch the local adapter exactly once')
        self.assertEqual((session / 'r1-sdk.stream.ndjson').read_text(), stream)
        self.assertTrue(artifacts['exit'].is_file(), process.stdout + process.stderr)
        return process, artifacts

    def assert_extraction_rejected(self, process, artifacts):
        detail = process.stdout + process.stderr + artifacts['log'].read_text()
        self.assertEqual(process.returncode, 2,
                         'SDK success must fail closed at extraction before audit: ' + detail)
        self.assertEqual(artifacts['exit'].read_text(), '2\n')
        self.assertFalse(artifacts['downstream'].exists(),
                         'invalid extraction must never reach downstream audit/qualification')
        self.assertFalse(artifacts['out'].exists(),
                         'an extraction-invalid published result must be removed or quarantined')

    def test_valid_terminal_matches_published_result_and_reaches_downstream(self):
        events = self.events()
        published = json.loads(events[-1]['result'])
        process, artifacts = self.wrapper(events, published)
        self.assertEqual(artifacts['summary_exit'].read_text(), '0\n')
        self.assertEqual(json.loads(artifacts['candidate'].read_text()), published)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(artifacts['exit'].read_text(), '0\n')
        self.assertEqual(artifacts['downstream'].read_text(), 'LOCAL TEST audit called\n')
        self.assertEqual(json.loads(artifacts['out'].read_text()), published)

    def test_duplicate_result_key_is_rejected_before_downstream_despite_driver_success(self):
        events = self.events()
        events[-1]['result'] = '{"summary":"first","summary":"second","findings":[]}'
        published = json.loads(events[-1]['result'])
        self.assertEqual(published, {'summary': 'second', 'findings': []})
        process, artifacts = self.wrapper(events, published)
        self.assertEqual(artifacts['summary_exit'].read_text(), '2\n')
        self.assertFalse(artifacts['candidate'].exists())
        self.assert_extraction_rejected(process, artifacts)

    def test_valid_terminal_disagreeing_with_published_result_is_rejected_before_downstream(self):
        events = self.events()
        terminal = json.loads(events[-1]['result'])
        published = dict(terminal, summary='Different synthetic published result')
        process, artifacts = self.wrapper(events, published)
        self.assertEqual(artifacts['summary_exit'].read_text(), '0\n')
        self.assertEqual(json.loads(artifacts['candidate'].read_text()), terminal)
        self.assertNotEqual(terminal, published)
        self.assert_extraction_rejected(process, artifacts)

    def test_missing_malformed_or_schema_invalid_terminal_is_rejected_before_downstream(self):
        for mutation in ('missing-terminal', 'malformed-result', 'schema-invalid-result'):
            with self.subTest(mutation=mutation):
                events = self.events()
                published = json.loads(events[-1]['result'])
                if mutation == 'missing-terminal':
                    events.pop()
                elif mutation == 'malformed-result':
                    events[-1]['result'] = '{"summary":'
                else:
                    events[-1]['result'] = '{"summary":"missing findings"}'
                process, artifacts = self.wrapper(events, published)
                self.assertEqual(artifacts['summary_exit'].read_text(), '2\n')
                self.assertFalse(artifacts['candidate'].exists())
                self.assert_extraction_rejected(process, artifacts)

    def test_nonzero_driver_status_is_preserved_without_outer_reclassification_or_downstream(self):
        for driver_exit in (1, 2, 3, 4):
            with self.subTest(driver_exit=driver_exit):
                events = self.events()
                events[-1]['result'] = '{"summary":"first","summary":"second","findings":[]}'
                process, artifacts = self.wrapper(events, json.loads(events[-1]['result']), driver_exit)
                self.assertEqual(artifacts['summary_exit'].read_text(), '2\n')
                self.assertFalse(artifacts['candidate'].exists())
                self.assertEqual(process.returncode, driver_exit, process.stdout + process.stderr)
                self.assertEqual(artifacts['exit'].read_text(), str(driver_exit) + '\n')
                self.assertFalse(artifacts['downstream'].exists())
                self.assertFalse(artifacts['out'].exists())


if __name__ == '__main__':
    unittest.main()
