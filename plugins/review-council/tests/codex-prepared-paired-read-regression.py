import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

scripts, fixtures, shims, temporary = map(Path, sys.argv[1:5])
session = (temporary / 'seat-codex-omitted-second').resolve()
repo = (temporary / 'repo').resolve()
stages = session / 'calls'
session.mkdir(parents=True)
repo.mkdir(parents=True)

patch = b'first patch chunk\nsecond patch chunk\n'
first, second = b'first patch chunk\n', b'second patch chunk\n'
index = b'evidence index\n'
files = {
    'r1-full.patch': patch,
    'r1-patch-p01-001.txt': first,
    'r1-patch-p01-002.txt': second,
    'r1-evidence.md': index,
}
for name, raw in files.items():
    (session / name).write_bytes(raw)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


manifest = {
    'schema_version': 2,
    'label': '1',
    'session': str(session.resolve()),
    'scope': '.',
    'delta_paths': [],
    'artifacts': {name: {'sha256': digest(raw)} for name, raw in files.items()},
    'assignments': {
        'codex-luna': {
            'adapter': 'codex',
            'model': 'gpt-6.1-luna',
            'scope': 'full',
            'full_state': True,
            'patch': str(session / 'r1-full.patch'),
            'patch_sha256': digest(patch),
            'patch_bytes': len(patch),
            'patch_lines': 2,
            'patch_read_mode': 'chunks',
            'patch_set': 'p01',
        },
    },
    'patch_sets': {
        'p01': {
            'read_mode': 'chunks',
            'patch_sha256': digest(patch),
            'patch_bytes': len(patch),
            'patch_lines': 2,
            'chunks': [
                {
                    'artifact': 'r1-patch-p01-001.txt',
                    'index': 1,
                    'byte_start': 0,
                    'byte_end': len(first),
                    'bytes': len(first),
                    'sha256': digest(first),
                    'predicted_visible_bytes': len(first),
                },
                {
                    'artifact': 'r1-patch-p01-002.txt',
                    'index': 2,
                    'byte_start': len(first),
                    'byte_end': len(patch),
                    'bytes': len(second),
                    'sha256': digest(second),
                    'predicted_visible_bytes': len(second),
                },
            ],
        },
    },
}
manifest_raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode() + b'\n'
(session / 'r1-evidence.manifest.json').write_bytes(manifest_raw)
prompt_lines = [
    'Evidence manifest SHA-256: ' + digest(manifest_raw),
    'Review this prepared assignment after reading all bound evidence.',
    'use at most 4 repository tool calls before stopping this assignment.',
    'Patch chunk batch limit: 2',
    f'Canonical assigned patch: {session / "r1-full.patch"} SHA-256 {digest(patch)} bytes {len(patch)}',
]
for number, (name, raw) in enumerate((('r1-patch-p01-001.txt', first),
                                      ('r1-patch-p01-002.txt', second)), 1):
    start = 0 if number == 1 else len(first)
    prompt_lines.append(
        f'Assigned patch chunk {number}/2: {session / name} bytes '
        f'{start}-{start + len(raw)} SHA-256 {digest(raw)}')
prompt_lines.append(f'Evidence navigation index: {session / "r1-evidence.md"}')
prompt = session / 'r1-codex-luna.prompt.md'
prompt.write_text('\n'.join(prompt_lines) + '\n', encoding='utf-8')

expected = [session / 'r1-patch-p01-001.txt',
            session / 'r1-patch-p01-002.txt', session / 'r1-evidence.md']
adapter = scripts / 'seats.d/codex.sh'
schema = fixtures / 'findings.schema.json'


def run(name, read_mode):
    capture = session / name
    capture.mkdir()
    env = os.environ.copy()
    env.update({
        'PATH': str(shims) + os.pathsep + env['PATH'],
        'SHIM_FIXTURE_DIR': str(fixtures),
        'SHIM_MODE': 'staged',
        'SHIM_STAGE_READ_MODE': read_mode,
        'SHIM_STAGE_DIR': str(capture),
        'SHIM_CALLS_FILE': str(capture / 'calls.log'),
        'SEAT': 'codex-luna',
        'MODEL': 'gpt-6.1-luna',
        'EFFORT': 'xhigh',
        'MODE': 'prompt',
        'ROOT': str(repo),
        'PROMPT': str(prompt),
        'SCHEMA': str(schema),
        'OUT': str(capture / 'result.json'),
        'LOG': str(capture / 'adapter.log'),
        'RAW': str(capture / 'stream.ndjson'),
        'BASE': 'abc',
        'REV_REPO': str(repo),
    })
    result = subprocess.run(['bash', str(adapter)], env=env, capture_output=True, text=True)
    (capture / 'stdout.txt').write_text(result.stdout)
    (capture / 'stderr.txt').write_text(result.stderr)
    return capture, result.returncode


def read_observations(stream):
    output = []
    for line in stream.read_text().splitlines():
        event = json.loads(line)
        item = event.get('item') or {}
        if event.get('type') == 'item.completed' and item.get('type') == 'command_execution':
            output.append((Path(shlex.split(item['command'])[2]), item.get('aggregated_output')))
    return output


def prompt_commands(capture):
    output = []
    patch_pair = 0
    for row in sorted(capture.glob('call-*.stdin'),
                      key=lambda path: int(path.stem.split('-')[1])):
        lines = row.read_text().splitlines()
        reads = [line[len('Read exactly: '):] for line in lines
                 if line.startswith('Read exactly: ')]
        if lines and 'patch chunks' in lines[0]:
            patch_pair = max(patch_pair, len(reads))
        output.extend(Path(shlex.split(command)[2]) for command in reads)
    return output, patch_pair


complete, rc = run('complete', 'complete')
assert rc == 0, f'complete full-scope evidence failed: {rc}: {(complete / "stderr.txt").read_text()}'
commands, _ = prompt_commands(complete)
assert commands == expected, commands
observations = read_observations(complete / 'stream.ndjson')
assert [path for path, _ in observations] == expected, observations
for path, output in observations:
    assert output == path.read_text(), (path, output)

omitted, rc = run('omitted', 'duplicate_second')
commands, pair_count = prompt_commands(omitted)
observations = read_observations(omitted / 'stream.ndjson')
call_count = len((omitted / 'calls.log').read_text().splitlines())
if pair_count == 2:
    assert [path for path, _ in observations[:2]] == [expected[0], expected[0]], observations
    assert rc == 1, f'paired stage accepted an omitted second manifest-bound patch chunk (exit {rc})'
    assert call_count == 1, f'paired stage did not stop at the incomplete first turn (calls {call_count})'
else:
    assert pair_count == 1, pair_count
    assert commands == expected, commands
    assert [path for path, _ in observations] == expected, observations
    assert rc == 0, f'single-read stages rejected complete full-scope evidence (exit {rc})'
