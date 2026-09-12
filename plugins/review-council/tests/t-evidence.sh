#!/bin/bash
# Also runnable directly, without the suite harness.
test_evidence_contract() {
  python3 - "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)/rev-evidence.py" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

script = sys.argv[1]
with tempfile.TemporaryDirectory(prefix='evidence-test-') as tmp:
    root = Path(tmp) / 'repo'; root.mkdir()
    session = Path(tmp) / 'session'; session.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
    def write(path, data):
        p = root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(data)
    def run(*args, good=True):
        env = dict(os.environ, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1')
        p = subprocess.run([sys.executable, script, *map(str, args)], capture_output=True, text=True, env=env)
        assert (p.returncode == 0) == good, (args, p.returncode, p.stdout, p.stderr)
        return p.stdout
    def prepare(label, phase='discovery', *extra):
        run('prepare', session, label, '--phase', phase, *extra)
        return json.loads((session / f'r{label}-evidence.manifest.json').read_text())
    def agent_audit(label, seat, manifest):
        assignment = manifest['assignments'][seat]
        packet = manifest['source_context']['seats'][seat]
        proof_keys = ('path', 'line_start', 'line_end', 'blob_tree', 'blob_oid', 'content_sha256')
        proofs = [{key: required[key] for key in proof_keys}
                  for required in packet['required_source_ranges']]
        ranges = [{'path': row['path'], 'line_start': row['line_start'], 'line_end': row['line_end'], 'origin': 'packet'}
                  for shard in packet['shards'] for row in shard['ranges']]
        tool_ranges = []
        for required in packet['required_source_ranges']:
            tool_ranges.extend({'path': required['path'], 'line_start': start,
                                'line_end': min(start + 239, required['line_end']), 'origin': 'tool'}
                               for start in range(required['line_start'], required['line_end'] + 1, 240))
        if packet['source_read_required'] and not tool_ranges:
            component = next(component for component in manifest['components']
                             if component['id'] == packet['components'][0])
            tool_ranges.append({'path': component['boundary'][0], 'line_start': 1,
                                'line_end': 1, 'origin': 'tool'})
        ranges.extend(tool_ranges); source_calls = len(tool_ranges)
        ranges.sort(key=lambda row: (row['path'], row['line_start'], row['line_end'], row['origin']))
        stream = session / f'r{label}-{seat}.stream.ndjson'; stream.write_text('{}\n')
        prompt = session / f'r{label}-{seat}.prompt.md'; result = session / f'r{label}-{seat}.json'
        patch = Path(assignment['patch']); patch_raw = patch.read_bytes(); patch_lines = len(patch_raw.splitlines())
        patch_mode = assignment['patch_read_mode']
        chunks = manifest['patch_sets'][assignment['patch_set']]['chunks'] if patch_mode == 'chunks' else []
        patch_ranges = [] if chunks else [{'line_start': start, 'line_end': min(start + 239, patch_lines)}
                                          for start in range(1, patch_lines + 1, 240)]
        patch_reads = len(chunks) if chunks else max(1, len(patch_ranges))
        calls = max(1, len(packet['shards']) + source_calls + patch_reads)
        packet_bytes = sum(shard['bytes'] for shard in packet['shards'])
        audit = {'schema_version':2, 'status':'valid', 'narrow':assignment['scope'] != 'full', 'adapter':'agent',
                 'prompt_sha256':hashlib.sha256(prompt.read_bytes()).hexdigest(),
                 'stream_sha256':hashlib.sha256(stream.read_bytes()).hexdigest(),
                 'result_sha256':hashlib.sha256(result.read_bytes()).hexdigest(),
                 'evidence_manifest_sha256':hashlib.sha256((session / f'r{label}-evidence.manifest.json').read_bytes()).hexdigest(),
                 'violations':[], 'tool_calls':calls, 'tool_turns':calls,
                 'tool_output_bytes':packet_bytes + source_calls + len(patch_raw),
                 'max_tool_output_bytes':max([shard['bytes'] for shard in packet['shards']] + [source_calls, len(patch_raw)]),
                 'recognized_tool_calls':calls, 'source_read_calls':source_calls,
                 'packet_shards':len(packet['shards']), 'packet_bytes':packet_bytes,
                 'packet_ranges':sum(1 for row in ranges if row['origin'] == 'packet'),
                 'opened_source_ranges':sum(1 for row in ranges if row['origin'] == 'tool'),
                 'finding_citations':0, 'source_ranges':ranges,
                 'required_source_ranges_covered':len(packet['required_source_ranges']),
                 'required_source_range_proofs':proofs,
                 'assigned_patch_sha256':hashlib.sha256(patch_raw).hexdigest(),
                 'assigned_patch_bytes':len(patch_raw), 'assigned_patch_lines':patch_lines,
                 'assigned_patch_reads':patch_reads, 'assigned_patch_ranges':patch_ranges,
                 'patch_proof_mode':patch_mode, 'patch_proof_calls':patch_reads,
                 'patch_proof_turns':patch_reads, 'patch_proof_visible_bytes':len(patch_raw),
                 'expected_patch_chunks':len(chunks), 'opened_patch_chunks':len(chunks)}
        (session / f'r{label}-{seat}.read-audit.json').write_text(json.dumps(audit))
    def results(label):
        manifest_path = session / f'r{label}-evidence.manifest.json'; manifest = json.loads(manifest_path.read_text())
        for seat in manifest['assignments']:
            (session / f'r{label}-{seat}.prompt.md').write_text(run('render', manifest_path, seat))
            (session / f'r{label}-{seat}.json').write_text('{"summary":"checked","findings":[]}')
            (session / f'r{label}-{seat}.exit').write_text('0\n')
            agent_audit(label, seat, manifest)
    def fingerprint():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / '.git').rglob('*') if p.is_file()}
    git('init', '-q'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
    git('config', 'commit.gpgsign', 'false')
    write('main.py', 'def calculate():\n    return 1\n' + '\n' * 15 + 'def stable():\n    return 1\n')
    write('deleted.py', 'gone\n'); write('package-lock.json', '{}\n')
    write('replaced.txt', 'old file\n')
    write('test_main.py', 'from main import calculate\nassert calculate() == 1\n')
    write('package.json', '{"scripts":{"test":"pytest","lint":"ruff check ."}}\n')
    write('.gitattributes', '*.py filter=tripwire\n')
    git('add', '.'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
    git('config', 'filter.tripwire.clean', 'touch FILTER_RAN; cat')
    write('main.py', 'def calculate():\n    return 2\n' + '\n' * 15 + 'def stable():\n    return 2\n')
    (root / 'deleted.py').unlink()
    (root / 'replaced.txt').unlink(); write('replaced.txt/child.py', 'new child\n')
    for name in ['package-lock.json', 'generated/types.ts', '__snapshots__/one.snap', 'locales/fr.json',
                 'i18n/config.ts', 'build/app.ts', 'fixtures/input.json', 'golden/value.txt', 'vendor/code.c']:
        write(name, 'updated content\n')
    write('new.py', 'def fresh():\n    return calculate()\n')
    write('image.bin', 'opaque extension with text content\n')
    (root / 'shortcut').symlink_to('main.py')
    (session / 'scope.env').write_text(f"REV_BASE='{base}'\nREV_ROOT='{root}'\nREV_SCOPE='branch'\n")
    seats = ['sol', 'grok', 'opus', 'opus-2']
    bundles = ['correctness-boundaries', 'security-state-api', 'concurrency-resources-performance', 'tests-observability-maintenance-regression']
    (session / 'roster.json').write_text(json.dumps({'seats': [{'seat': s, 'extra': False, 'adapter': 'agent'} for s in seats]}))
    before = fingerprint(); first = prepare('1')
    assert fingerprint() == before, 'snapshot modified repository Git state'
    assert not (root / 'FILTER_RAN').exists(), 'clean filter ran'
    deleted_context = [row for packet in first['source_context']['seats'].values()
                       for shard in packet['shards'] for row in shard['ranges']
                       if row['path'] == 'deleted.py']
    deleted_context += [row for packet in first['source_context']['seats'].values()
                        for row in packet['required_source_ranges'] if row['path'] == 'deleted.py']
    assert deleted_context and all(row['blob_tree'] == first['base_tree'] for row in deleted_context)
    assert first['mechanical_owner'] == 'sol'
    assert first['assignments']['sol']['scope'] == 'full'
    assert first['assignments']['grok']['scope'] == 'semantic'
    full = (session / 'r1-full.patch').read_text(); semantic = (session / 'r1-semantic.patch').read_text()
    for name in ['package-lock.json', 'generated/types.ts', '__snapshots__/one.snap', 'locales/fr.json']:
        assert name in full and name not in semantic, name
    for name in ['i18n/config.ts', 'build/app.ts', 'fixtures/input.json', 'golden/value.txt', 'vendor/code.c', 'image.bin', 'shortcut', 'deleted.py', 'new.py']:
        assert name in semantic, name
    facts = json.loads((session / 'r1-evidence.json').read_text())
    assert any(x['name'] == 'calculate' for x in facts['symbols'])
    assert any(x['path'] == 'test_main.py' for x in facts['call_sites'])
    assert {'path': 'test_main.py', 'line': 2, 'name': 'calculate', 'kind': 'lexical name( match, not resolved dispatch'} in facts['call_sites']
    assert any(x['path'] == 'test_main.py' for x in facts['related_tests'])
    assert {'path': 'package.json', 'line': 1, 'command': '{"scripts":{"test":"pytest","lint":"ruff check ."}}', 'kind': 'lexical gate candidate'} in facts['gates']
    assert run('render', session / 'r1-evidence.manifest.json', 'grok') == run('render', session / 'r1-evidence.manifest.json', 'grok')
    frozen = {p.name: p.read_bytes() for p in session.glob('r1-*')}; prepare('1')
    assert all((session / name).read_bytes() == data for name, data in frozen.items()), 'nondeterministic prepare'
    results('1'); run('receipt', session, '1')
    head = (session / 'coverage-head.json').read_bytes()
    args = [a for s, b in zip(seats, bundles) for a in ['--assignment', s + '=' + b]]
    nofix = prepare('2', 'verification', *args)
    assert all(a['scope'] == 'full' for a in nofix['assignments'].values()), nofix
    assert nofix['fallback_reason']
    write('main.py', (root / 'main.py').read_text().replace('return 2', 'return 3', 1))
    run('render', session / 'r2-evidence.manifest.json', 'sol', good=False)
    larger = prepare('2b', 'verification', *args)
    assert all(a['scope'] == 'full' for a in larger['assignments'].values())
    assert 'not smaller' in larger['fallback_reason']
    # Make the cumulative semantic patch much larger than the evidence packet.
    for i in range(8):
        write(f'src/unit{i}.py', f'def unit{i}():\n' + ''.join(f'    value_{j} = {j}\n' for j in range(400)))
    prepare('3'); results('3'); run('receipt', session, '3')
    oldfacts = json.loads((session / 'r3-evidence.json').read_text())
    write('main.py', (root / 'main.py').read_text().replace('return 3', 'return 4', 1))
    delta = prepare('4', 'verification', *args)
    assert delta['assignments']['opus-2']['scope'] == 'full'
    assert delta['assignments']['sol']['scope'] == 'delta', delta['fallback_reason']
    patch = (session / 'r4-delta.patch').read_text()
    assert '-    return 3' in patch and '+    return 4' in patch
    assert 'def stable' not in patch and 'src/unit' not in patch
    newfacts = json.loads((session / 'r4-evidence.json').read_text())
    oldhashes = [h['sha256'] for h in oldfacts['hunks'] if h['path'] == 'main.py']
    newhashes = [h['sha256'] for h in newfacts['hunks'] if h['path'] == 'main.py']
    assert len(set(oldhashes) & set(newhashes)) == 1, 'unchanged hunk lost identity'
    assert len(set(newhashes) - set(oldhashes)) == 1, 'changed hunk not isolated'
    results('4'); head = (session / 'coverage-head.json').read_bytes()
    for suffix, bad in [('exit', '1'), ('json', '{"summary":"missing findings"}'), ('prompt.md', 'wrong hash')]:
        p = session / ('r4-sol.' + suffix); saved = p.read_bytes(); p.write_text(bad)
        run('receipt', session, '4', good=False); assert (session / 'coverage-head.json').read_bytes() == head
        p.write_bytes(saved)
    run('receipt', session, '4'); receipt = (session / 'r4-coverage.receipt.json').read_bytes()
    run('receipt', session, '4'); assert (session / 'r4-coverage.receipt.json').read_bytes() == receipt
    write('main.py', (root / 'main.py').read_text() + '# later\n')
    run('receipt', session, '4', good=False)
    prepare('5', 'verification', *args); results('5')
    (session / 'r5-evidence.md').write_text('tampered')
    run('render', session / 'r5-evidence.manifest.json', 'sol', good=False)
    repair = prepare('6', 'repair', '--assignment', 'grok=security-state-api')
    assert list(repair['assignments']) == ['grok'] and repair['assignments']['grok']['scope'] == 'full'
    results('6'); run('receipt', session, '6', good=False)
    (session / 'coverage-head.json').write_text('{bad')
    missing = prepare('7', 'verification', *args)
    assert all(a['scope'] == 'full' for a in missing['assignments'].values())
    risk = prepare('8', 'risk')
    assert all(a['scope'] == 'full' for a in risk['assignments'].values()), 'ambiguous risk must widen'
    unknown = prepare('9', 'verification', '--head', 'unknown-reviewed-ref', *args)
    assert all(a['scope'] == 'full' for a in unknown['assignments'].values())
    assert unknown['fallback_reason']
    seed = prepare('10', 'discovery', '--head', base)
    results('10'); run('receipt', session, '10')
    assert seed['snapshot_tree'] == git('rev-parse', base + '^{tree}')
    small = prepare('11', 'verification', *args)
    results('11'); run('receipt', session, '11')
    (root / 'image.bin').unlink(); (root / 'image.bin').symlink_to('main.py')
    unsafe = prepare('12', 'verification', *args)
    assert all(a['scope'] == 'full' for a in unsafe['assignments'].values()) and 'unsafe' in unsafe['fallback_reason']
    manifest_path = session / 'r12-evidence.manifest.json'
    saved_manifest = manifest_path.read_bytes()
    for key, value in [('patch', '/tmp/other.patch'), ('full_state', False)]:
        corrupt = json.loads(saved_manifest)
        corrupt['assignments']['opus-2'][key] = value
        manifest_path.write_text(json.dumps(corrupt))
        run('render', manifest_path, 'opus-2', good=False)
    manifest_path.write_bytes(saved_manifest)
    write('nested/item.py', 'original\n')
    git('-c', 'filter.tripwire.clean=cat', 'add', 'nested/item.py')
    git('commit', '-qm', 'nested file')
    external = Path(tmp) / 'external'; external.mkdir()
    (external / 'item.py').write_text('OUTSIDE_CONTENT_MUST_NOT_BE_READ\n')
    (root / 'nested/item.py').unlink(); (root / 'nested').rmdir()
    (root / 'nested').symlink_to(external, target_is_directory=True)
    prepare('12a')
    assert 'OUTSIDE_CONTENT_MUST_NOT_BE_READ' not in (session / 'r12a-full.patch').read_text()
    (root / 'main.py').unlink(); os.mkfifo(root / 'main.py')
    run('prepare', session, '12b', '--phase', 'discovery', good=False)
    assert not list(session.glob('r12b-*'))
    (session / 'scope.env').write_text(f"REV_BASE='{base}'\nREV_ROOT='{root}'\nREV_SCOPE='branch'\nREV_EVIL=$(touch UNWANTED)\n")
    run('prepare', session, '13', '--phase', 'discovery', good=False)
    assert not (root / 'UNWANTED').exists()
    print('PASS evidence snapshots, routing, deterministic facts, hunk identity, delta, freshness, receipts and fallback')
PY
  local rc=$?
  if declare -F ok >/dev/null && declare -F fail >/dev/null; then
    if [ "$rc" -eq 0 ]; then ok "evidence state machine contract"; else fail "evidence state machine contract" "exit $rc"; fi
  fi
  return "$rc"
}

test_evidence_hardening() {
  python3 - "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)/rev-evidence.py" <<'PY'
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

script = Path(sys.argv[1]); spec = importlib.util.spec_from_file_location('evidence', script)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
seats = ['sol', 'grok', 'opus', 'opus-2']
bundles = ['correctness-boundaries', 'security-state-api', 'concurrency-resources-performance', 'tests-observability-maintenance-regression']
assign = [a for s, b in zip(seats, bundles) for a in ('--assignment', s + '=' + b)]

def write_agent_audit(session, label, seat):
    manifest_path = session / f'r{label}-evidence.manifest.json'; manifest = json.loads(manifest_path.read_text())
    assignment = manifest['assignments'][seat]
    packet = manifest['source_context']['seats'][seat]
    proof_keys = ('path', 'line_start', 'line_end', 'blob_tree', 'blob_oid', 'content_sha256')
    proofs = [{key: required[key] for key in proof_keys}
              for required in packet['required_source_ranges']]
    ranges = [{'path': row['path'], 'line_start': row['line_start'], 'line_end': row['line_end'], 'origin': 'packet'}
              for shard in packet['shards'] for row in shard['ranges']]
    findings = json.loads((session / f'r{label}-{seat}.json').read_text())['findings']
    missing = [finding for finding in findings if not any(
        row['path'] == finding['file'] and row['line_start'] <= finding['line_end']
        and finding['line_start'] <= row['line_end'] for row in ranges)]
    tool_ranges = [{'path': finding['file'], 'line_start': finding['line_start'],
                    'line_end': finding['line_end'], 'origin': 'tool'} for finding in missing]
    for required in packet['required_source_ranges']:
        tool_ranges.extend({'path': required['path'], 'line_start': start,
                            'line_end': min(start + 239, required['line_end']), 'origin': 'tool'}
                           for start in range(required['line_start'], required['line_end'] + 1, 240))
    if packet['source_read_required'] and not tool_ranges:
        component = next(component for component in manifest['components']
                         if component['id'] == packet['components'][0])
        tool_ranges.append({'path': component['boundary'][0], 'line_start': 1,
                            'line_end': 1, 'origin': 'tool'})
    ranges.extend(tool_ranges)
    ranges = sorted({(row['path'], row['line_start'], row['line_end'], row['origin']) for row in ranges})
    ranges = [{'path': path, 'line_start': start, 'line_end': end, 'origin': origin}
              for path, start, end, origin in ranges]
    stream = session / f'r{label}-{seat}.stream.ndjson'; stream.write_text('{}\n')
    prompt = session / f'r{label}-{seat}.prompt.md'; result = session / f'r{label}-{seat}.json'
    packet_bytes = sum(shard['bytes'] for shard in packet['shards'])
    patch = Path(assignment['patch']); patch_raw = patch.read_bytes(); patch_lines = len(patch_raw.splitlines())
    patch_mode = assignment['patch_read_mode']
    chunks = manifest['patch_sets'][assignment['patch_set']]['chunks'] if patch_mode == 'chunks' else []
    patch_ranges = [] if chunks else [{'line_start': start, 'line_end': min(start + 239, patch_lines)}
                                      for start in range(1, patch_lines + 1, 240)]
    patch_reads = len(chunks) if chunks else max(1, len(patch_ranges))
    calls = max(1, len(packet['shards']) + len(tool_ranges) + patch_reads)
    cited = sum(any(row['path'] == finding['file'] and row['line_start'] <= finding['line_end']
                    and finding['line_start'] <= row['line_end'] for row in ranges) for finding in findings)
    audit = {'schema_version':2, 'status':'valid', 'narrow':assignment['scope'] != 'full', 'adapter':'agent',
             'prompt_sha256':module.digest(prompt.read_bytes()), 'stream_sha256':module.digest(stream.read_bytes()),
             'result_sha256':module.digest(result.read_bytes()),
             'evidence_manifest_sha256':module.digest(manifest_path.read_bytes()), 'violations':[],
             'tool_calls':calls, 'tool_turns':calls, 'tool_output_bytes':packet_bytes + len(tool_ranges) + len(patch_raw),
             'max_tool_output_bytes':max([shard['bytes'] for shard in packet['shards']] + [len(tool_ranges), len(patch_raw)]),
             'recognized_tool_calls':calls, 'source_read_calls':len(tool_ranges),
             'packet_shards':len(packet['shards']), 'packet_bytes':packet_bytes,
             'packet_ranges':sum(row['origin'] == 'packet' for row in ranges),
             'opened_source_ranges':sum(row['origin'] == 'tool' for row in ranges),
             'finding_citations':cited, 'source_ranges':ranges,
             'required_source_ranges_covered':len(packet['required_source_ranges']),
             'required_source_range_proofs':proofs,
             'assigned_patch_sha256':module.digest(patch_raw), 'assigned_patch_bytes':len(patch_raw),
             'assigned_patch_lines':patch_lines, 'assigned_patch_reads':patch_reads,
             'assigned_patch_ranges':patch_ranges,
             'patch_proof_mode':patch_mode, 'patch_proof_calls':patch_reads,
             'patch_proof_turns':patch_reads, 'patch_proof_visible_bytes':len(patch_raw),
             'expected_patch_chunks':len(chunks), 'opened_patch_chunks':len(chunks)}
    (session / f'r{label}-{seat}.read-audit.json').write_text(json.dumps(audit))

@contextlib.contextmanager
def fixture(name='repo'):
    with tempfile.TemporaryDirectory(prefix='evidence-hardening-') as tmp:
        root = Path(tmp) / name; root.mkdir(); session = Path(tmp) / 'session'; session.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
        def write(name, text):
            p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        def call(*args, good=True, timeout=30, env=None):
            run_env = dict(os.environ, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1')
            run_env.update(env or {})
            p = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, timeout=timeout, env=run_env)
            assert 'Traceback' not in p.stderr, p.stderr
            assert (p.returncode == 0) == good, (p.returncode, p.stdout, p.stderr)
            return p.stdout
        def prepare(label='1', phase='discovery', *extra, **kw):
            call('prepare', session, label, '--phase', phase, *extra, **kw)
            return json.loads((session / f'r{label}-evidence.manifest.json').read_text())
        def finish(label='1'):
            mpath = session / f'r{label}-evidence.manifest.json'
            for seat in json.loads(mpath.read_text())['assignments']:
                (session / f'r{label}-{seat}.prompt.md').write_text(call('render', mpath, seat))
                (session / f'r{label}-{seat}.json').write_text('{"summary":"verified","findings":[]}')
                (session / f'r{label}-{seat}.exit').write_text('0\n')
                write_agent_audit(session, label, seat)
            call('receipt', session, label)
        git('init', '-q'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid'); git('config', 'commit.gpgsign', 'false')
        write('main.py', 'def first():\n    return 1\n\ndef second():\n    return 1\n')
        write('test_calls.py', 'assert first() == 1\nassert second() == 1\n')
        write('package.json', '{"scripts":{"test":"pytest"}}\n')
        git('add', '.'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
        (session / 'scope.env').write_text(''.join(k + '=' + shlex.quote(v) + '\n' for k, v in [('REV_BASE', base), ('REV_ROOT', str(root)), ('REV_SCOPE', 'branch')]))
        (session / 'roster.json').write_text(json.dumps({'seats': [{'seat': s, 'extra': False, 'adapter': 'agent'} for s in seats]}))
        write('main.py', (root / 'main.py').read_text().replace('return 1', 'return 2'))
        yield root, session, git, write, call, prepare, finish

def storage_redirects():
    for nested in (False, True):
        with fixture() as (root, session, git, write, call, prepare, finish):
            target = root / '.git/objects'; store = session / 'evidence-objects'
            if nested:
                store.mkdir(); (store / 'aa').symlink_to(target, target_is_directory=True)
            else:
                store.symlink_to(target, target_is_directory=True)
            before = {str(p): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            call('prepare', session, '1', '--phase', 'discovery', good=False)
            assert before == {str(p): p.read_bytes() for p in target.rglob('*') if p.is_file()}

def quoted_paths():
    with fixture('r\u00e9po space\'"colon:back\\slash') as (root, session, git, write, call, prepare, finish):
        prepare(); call('render', session / 'r1-evidence.manifest.json', 'sol')

def changed_symbols():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('_locales/en/messages.json', '{"hello":{"message":"Hello"}}\n')
        prepare(); facts = json.loads((session / 'r1-evidence.json').read_text())
        assert {s['name'] for s in facts['symbols'] if s['path'] == 'main.py'} == {'first', 'second'}
        assert {(c['name'], c['line']) for c in facts['call_sites'] if c['path'] == 'test_calls.py'} == {('first', 1), ('second', 2)}
        assert facts['mechanical']['_locales/en/messages.json'] == 'locale'

def conservative_mechanical_classification():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('src/i18n/api/config.json', '{"handwritten":true}\n')
        write('src/generated-looking.ts', '// Generated code handles account recovery.\nexport const recovery = 1;\n')
        write('generated/actual.ts', '// @generated\nexport const actual = 1;\n')
        m = prepare(); facts = json.loads((session / 'r1-evidence.json').read_text())
        assert 'src/i18n/api/config.json' in m['semantic_paths']
        assert 'src/generated-looking.ts' in m['semantic_paths']
        assert facts['mechanical']['generated/actual.ts'] == 'generated'

def bounded_navigation_markdown():
    with fixture() as (root, session, git, write, call, prepare, finish):
        huge = 'x' * 100000
        write('package.json', '{"scripts":{"test":"' + huge + '"}}\n')
        prepare(); packet = (session / 'r1-evidence.md').read_bytes()
        assert len(packet) <= 16384
        assert huge.encode() not in packet
        assert b'complete list SHA-256:' in packet and b'Omitted:' in packet

def opaque_transitions():
    for reverse in (False, True):
        with fixture() as (root, session, git, write, call, prepare, finish):
            write('generated/data.txt', 'ordinary text\n'); write('package-lock.json', '{}\n')
            if not reverse:
                (root / 'generated/data.txt').write_bytes(b'\0binary')
                (root / 'package-lock.json').unlink(); (root / 'package-lock.json').symlink_to('main.py')
            git('add', '.'); git('commit', '-qm', 'transition base')
            base = git('rev-parse', 'HEAD')
            scope = (session / 'scope.env').read_text(); scope = '\n'.join('REV_BASE=' + base if s.startswith('REV_BASE=') else s for s in scope.splitlines()) + '\n'; (session / 'scope.env').write_text(scope)
            (root / 'package-lock.json').unlink()
            if reverse:
                (root / 'package-lock.json').symlink_to('main.py'); (root / 'generated/data.txt').write_bytes(b'\0binary')
            else:
                write('package-lock.json', '{}\n'); write('generated/data.txt', 'ordinary text\n')
            prepare(); patch = (session / 'r1-semantic.patch').read_text()
            assert 'package-lock.json' in patch and 'generated/data.txt' in patch

def invalid_manifests():
    with fixture() as (root, session, git, write, call, prepare, finish):
        prepare(); mpath = session / 'r1-evidence.manifest.json'; original = mpath.read_bytes()
        bad = json.loads(original)
        for seat in seats[1:]:
            bad['assignments'][seat].update(scope='delta', patch=str(session.resolve() / 'r1-delta.patch'), full_state=False)
        mpath.write_text(json.dumps(bad)); call('render', mpath, 'grok', good=False)
        mpath.write_bytes(original)
        call('prepare', session, 'bad-owner', '--phase', 'verification', *assign, '--full-seat', 'sol', good=False)
        for key, value in [('source', None), ('assignments', []), ('artifacts', []), ('snapshot_unsafe', {}), ('word_counts', None)]:
            bad = json.loads(original); bad[key] = value; mpath.write_text(json.dumps(bad))
            call('render', mpath, 'sol', good=False)
        mpath.write_bytes(original); finish()
        headpath = session / 'coverage-head.json'; saved_head = headpath.read_bytes()
        receiptpath = session / 'r1-coverage.receipt.json'; saved_receipt = receiptpath.read_bytes()
        for key, value in [('source', None), ('assignments', []), ('artifacts', []), ('word_counts', None)]:
            bad = json.loads(original); bad[key] = value; raw = json.dumps(bad).encode(); mpath.write_bytes(raw)
            receipt = json.loads(saved_receipt); receipt['manifest_sha256'] = hashlib.sha256(raw).hexdigest()
            raw_receipt = json.dumps(receipt).encode(); receiptpath.write_bytes(raw_receipt)
            head = json.loads(saved_head); head['sha256'] = hashlib.sha256(raw_receipt).hexdigest(); headpath.write_text(json.dumps(head))
            widened = prepare('fallback-' + key, 'verification', *assign)
            assert all(a['scope'] == 'full' for a in widened['assignments'].values())

def opaque_mode_transition():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('generated/tool.py', '# generated file\nprint(1)\n'); git('add','.'); git('commit','-qm','mode base')
        base=git('rev-parse','HEAD'); text=(session/'scope.env').read_text()
        (session/'scope.env').write_text('\n'.join('REV_BASE='+base if s.startswith('REV_BASE=') else s for s in text.splitlines())+'\n')
        (root/'generated/tool.py').chmod(0o755); prepare()
        assert 'generated/tool.py' in (session/'r1-semantic.patch').read_text()

def phase_and_predecessor_integrity():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('padding.py', ''.join(f'value_{i} = {i}\n' for i in range(1000)))
        prepare(); mpath = session / 'r1-evidence.manifest.json'; epath = session / 'r1-evidence.json'
        original = mpath.read_bytes(); original_evidence = epath.read_bytes()
        def replace(manifest, evidence, mpath, epath):
            raw = json.dumps(evidence).encode(); epath.write_bytes(raw)
            manifest['artifacts'][epath.name]['sha256'] = hashlib.sha256(raw).hexdigest()
            manifest['artifacts'][epath.name]['words'] = len(raw.split())
            mpath.write_text(json.dumps(manifest))
        for mode in ('delta', 'full'):
            bad = json.loads(original); evidence = json.loads(original_evidence)
            for seat in seats[1:]:
                bad['assignments'][seat].update(scope=mode, patch=str(session.resolve() / f'r1-{mode}.patch'), full_state=mode == 'full')
            evidence['assignments'] = bad['assignments']; replace(bad, evidence, mpath, epath)
            call('render', mpath, 'sol', good=False)
            call('receipt', session, '1', good=False)
        mpath.write_bytes(original); epath.write_bytes(original_evidence); finish()
        write('main.py', (root / 'main.py').read_text().replace('return 2', 'return 3', 1))
        delta = prepare('2', 'verification', *assign)
        assert delta['assignments']['sol']['scope'] == 'delta'
        mpath = session / 'r2-evidence.manifest.json'; epath = session / 'r2-evidence.json'
        original = mpath.read_bytes(); original_evidence = epath.read_bytes()
        for field, value in [('predecessor', None), ('predecessor', {'receipt': 'missing.json', 'sha256': '0' * 64}), ('mechanical_owner', 'sol')]:
            bad = json.loads(original); evidence = json.loads(original_evidence)
            bad[field] = value; evidence[field] = value; replace(bad, evidence, mpath, epath)
            call('render', mpath, 'sol', good=False)
        mpath.write_bytes(original); epath.write_bytes(original_evidence)
        prior = session / 'r1-coverage.receipt.json'; prior.write_text('{"manifest":null}')
        call('render', mpath, 'sol', good=False)

def same_stat_and_index_flags():
    with fixture() as (root, session, git, write, call, prepare, finish):
        for flag in ('--assume-unchanged', '--skip-worktree'):
            git('update-index', '--no-assume-unchanged', '--no-skip-worktree', 'main.py')
            git('update-index', flag, 'main.py')
            before = (root / 'main.py').stat()
            write('main.py', (root / 'main.py').read_text().replace('return 2', 'return 3'))
            os.utime(root / 'main.py', ns=(before.st_atime_ns, before.st_mtime_ns))
            label = flag.lstrip('-'); prepare(label)
            assert '+    return 3' in (session / f'r{label}-full.patch').read_text()
            write('main.py', (root / 'main.py').read_text().replace('return 3', 'return 2'))
            os.utime(root / 'main.py', ns=(before.st_atime_ns, before.st_mtime_ns))
            call('render', session / f'r{label}-evidence.manifest.json', 'sol', good=False)

def cstyle_enclosing_bodies():
    assert not module.brace_spans(['export default function() {', '  return 2;', '}'], '.js'), 'anonymous functions need file scope'
    assert not module.brace_spans(['object.method()', '{', '  changed();', '}'], '.js'), 'calls followed by blocks are not declarations'
    signatures = {
        'ts': ('export function alpha(): number', 'export function gamma(): number', 'export function beta(): number'),
        'js': ('export const alpha = () =>', 'function gamma()', 'function beta()'),
        'rs': ('pub fn alpha() -> i32', 'fn gamma() -> i32', 'fn beta() -> i32'),
        'go': ('func alpha() int', 'func gamma() int', 'func beta() int'),
        'java': ('public static int alpha()', 'public static int gamma()', 'public static int beta()'),
        'c': ('static int alpha(void)', 'int gamma(void)', 'int beta(void)'),
        'cpp': ('static int alpha() noexcept', 'int gamma()', 'int beta()'),
    }
    with fixture() as (root, session, git, write, call, prepare, finish):
        for extension, (alpha, gamma, beta) in signatures.items():
            source = (alpha + ' {\n  /* a misleading close: } */\n  if (true) {\n    return 1;\n  }\n}\n'
                      + gamma + ' {\n  return 1;\n}\n' + beta + ' {\n  return alpha();\n}\n')
            if extension == 'java':
                source = 'class Example {\n' + source + '}\n'
            elif extension == 'cpp':
                source = source.replace('if (true)', 'if constexpr (true)')
            elif extension == 'go':
                source = source.replace('if (true)', 'if check()')
            write('body.' + extension, source)
        write('quoted.ts', 'export function quoted() {\n  const text = "}";\n  const pattern = /[{}]/;\n  if (text) {\n    return 1;\n  }\n}\nexport function caller() { return quoted(); }\n')
        write('body_only.ts', 'export function alpha() {\n  return 1;\n}\nexport function beta() {\n  return alpha();\n}\n')
        write('receiver.go', 'func (r Receiver) method() int {\n  if true {\n    return 1\n  }\n  return 0\n}\nfunc caller() int { return r.method() }\n')
        write('ambiguous.ts', 'export function unfinished() {\n  return 1;\n')
        git('add', '.'); git('commit', '-qm', 'brace baseline')
        base = git('rev-parse', 'HEAD'); text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join('REV_BASE=' + base if s.startswith('REV_BASE=') else s for s in text.splitlines()) + '\n')
        for name in [*('body.' + extension for extension in signatures), 'quoted.ts', 'body_only.ts', 'receiver.go', 'ambiguous.ts']:
            write(name, (root / name).read_text().replace('return 1', 'return 2'))
        prepare(); facts = json.loads((session / 'r1-evidence.json').read_text())
        for extension in signatures:
            path = 'body.' + extension
            actual = {s['name'] for s in facts['symbols'] if s['path'] == path}
            assert actual == {'alpha', 'gamma'}, (path, actual)
            assert len([h for h in facts['hunks'] if h['path'] == path]) == 1, path
            expected_line = (root / path).read_text().splitlines().index('  return alpha();') + 1
            assert any(c['path'] == path and c['name'] == 'alpha' and c['line'] == expected_line for c in facts['call_sites']), path
        assert {s['name'] for s in facts['symbols'] if s['path'] == 'quoted.ts'} == {'quoted'}
        assert any(c['path'] == 'quoted.ts' and c['name'] == 'quoted' and c['line'] == 8 for c in facts['call_sites'])
        assert {s['name'] for s in facts['symbols'] if s['path'] == 'body_only.ts'} == {'alpha'}
        assert any(c['path'] == 'body_only.ts' and c['name'] == 'alpha' and c['line'] == 5 for c in facts['call_sites'])
        assert {s['name'] for s in facts['symbols'] if s['path'] == 'receiver.go'} == {'method'}
        assert any(c['path'] == 'receiver.go' and c['name'] == 'method' and c['line'] == 7 for c in facts['call_sites'])
        assert any(s['path'] == 'ambiguous.ts' and s['name'] is None for s in facts['symbols'])

def wallet_scale():
    with fixture() as (root, session, git, write, call, prepare, finish):
        for i in range(1600):
            write(f'src/unchanged_{i}.py', ''.join(f'value_{j} = "unique_{i}_{j}_stable_payload"\n' for j in range(120)))
        source = ''.join(f'def changed_{i}():\n    return 1\n\n' for i in range(500))
        write('main.py', source); git('add', '.'); git('commit', '-qm', 'large baseline')
        base = git('rev-parse', 'HEAD'); text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join('REV_BASE=' + base if s.startswith('REV_BASE=') else s for s in text.splitlines()) + '\n')
        write('main.py', source.replace('return 1', 'return 2'))
        gitbin = subprocess.check_output(['which', 'git'], text=True).strip()
        bindir = session / 'bin'; bindir.mkdir(); log = session / 'git-calls.log'
        wrapper = bindir / 'git'; wrapper.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$EVIDENCE_GIT_LOG"\nexec ' + shlex.quote(gitbin) + ' "$@"\n'); wrapper.chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'], EVIDENCE_GIT_LOG=str(log))
        started = time.monotonic(); prepare(env=env, timeout=25); elapsed = time.monotonic() - started
        calls = log.read_text().splitlines()
        assert sum('hash-object' in line for line in calls) <= 2, 'worktree hashing must use bounded raw batches'
        assert len(calls) < 100, ('nonlinear Git calls', len(calls))
        objects = [p for p in (session / 'evidence-objects').rglob('*') if p.is_file()]
        assert len(objects) < 20 and sum(p.stat().st_size for p in objects) < 100000
        facts = json.loads((session / 'r1-evidence.json').read_text())
        assert len({s['name'] for s in facts['symbols'] if s['path'] == 'main.py'}) == 500
        print(f'SCALE files=1603 symbols=500 elapsed={elapsed:.2f}s git_calls={len(calls)} objects={len(objects)}')

def literal_scope_and_inventories():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('inside/a.py', 'value = 1\n'); write('outside.py', 'SIBLING_SECRET = 1\n')
        git('add', '.'); git('commit', '-qm', 'path base')
        base = git('rev-parse', 'HEAD')
        write('inside/a.py', 'value = 2\n'); write('inside/new.py', 'new = 1\n')
        write('outside.py', 'SIBLING_SECRET = 2\n'); write('outside-new.py', 'UNTRACKED_SECRET = 3\n')
        git('add', 'outside.py'); git('commit', '-qm', 'out of scope commit')
        (session / 'scope.env').write_text(''.join(k + '=' + shlex.quote(v) + '\n' for k, v in [('REV_BASE', base), ('REV_ROOT', str(root)), ('REV_SCOPE', 'inside')]))
        (session / 'files.txt').write_text('inside/a.py\ninside/new.py\n'); (session / 'untracked.txt').write_text('inside/new.py\n')
        m = prepare()
        for p in session.glob('r1-*'):
            assert b'SIBLING_SECRET' not in p.read_bytes() and b'outside-new.py' not in p.read_bytes(), p
        assert 'files.txt' in m['inputs'] and 'untracked.txt' in m['inputs']
        (session / 'files.txt').write_text('inside/a.py\n')
        call('render', session / 'r1-evidence.manifest.json', 'sol', good=False)

def sparse_gitlink_and_special():
    with fixture() as (root, session, git, write, call, prepare, finish):
        git('update-index', '--skip-worktree', 'test_calls.py'); (root / 'test_calls.py').unlink()
        prepare(); assert 'test_calls.py' not in (session / 'r1-full.patch').read_text()
        git('update-index', '--no-skip-worktree', 'test_calls.py')
        prepare('2'); assert 'deleted file mode' in (session / 'r2-full.patch').read_text()
        (root / 'main.py').unlink(); os.mkfifo(root / 'main.py')
        call('prepare', session, 'special', '--phase', 'discovery', good=False)
        assert not list(session.glob('rspecial-*'))
    with fixture() as (root, session, git, write, call, prepare, finish):
        pointer = git('rev-parse', 'HEAD')
        git('update-index', '--add', '--cacheinfo', '160000', pointer, 'module')
        prepare(); patch = (session / 'r1-full.patch').read_text()
        assert 'module' in patch and 'Subproject commit ' + pointer in patch
        finish()

def roster_bundle_coverage():
    for count in (3, 5):
        with fixture() as (root, session, git, write, call, prepare, finish):
            panel = ['sol', 'grok', 'opus'] if count == 3 else seats + ['fifth']
            (session / 'roster.json').write_text(json.dumps({'seats': [{'seat': s, 'adapter': 'agent'} for s in panel]}))
            dealt = [bundles[0] + '+' + bundles[3], bundles[1], bundles[2]] if count == 3 else bundles + [bundles[0]]
            args = [part for seat, bundle in zip(panel, dealt) for part in ('--assignment', seat + '=' + bundle)]
            m = prepare('1', 'risk', *args); finish()
            assert set(b for a in m['assignments'].values() for b in a['bundles']) == set(bundles)
            assert sum(a['full_state'] for a in m['assignments'].values()) == 1
            if count == 3:
                repeated = args[2:] + ['--assignment', panel[0] + '=' + bundles[0], '--assignment', panel[0] + '=' + bundles[3]]
                again = prepare('repeated', 'risk', *repeated)
                assert again['assignments'][panel[0]]['bundles'] == [bundles[0], bundles[3]]
                assert again['assignments'][panel[0]]['bundle'] == bundles[0] + '+' + bundles[3]
    with fixture() as (root, session, git, write, call, prepare, finish):
        (session / 'roster.json').write_text(json.dumps({'seats': [{'seat': 'sol', 'adapter': 'agent'}]}))
        call('prepare', session, 'too-small', '--phase', 'discovery', good=False)
    with fixture() as (root, session, git, write, call, prepare, finish):
        skewed = [bundles[0] + '+' + bundles[1], bundles[2], bundles[3], bundles[0]]
        args = [part for seat, bundle in zip(seats, skewed) for part in ('--assignment', seat + '=' + bundle)]
        call('prepare', session, 'skewed', '--phase', 'risk', *args, good=False)

def source_context_packets():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('main.py',
              'def first(value):\n    return value + 1\n\n'
              'def second(value):\n    return value + 2\n\n'
              'class Alternate:\n'
              '    def first(self, value):\n'
              '        return value + 3\n')
        write('consumer.py',
              'from main import first, second\n\n'
              'def use_first():\n    return first(4)\n\n'
              'def use_second():\n    return second(5)\n')
        write('tests/test_main.py',
              'from main import first, second\n\n'
              'def test_first():\n    assert first(1) == 2\n\n'
              'def test_second():\n    assert second(1) == 3\n')
        write('pyproject.toml', '[tool.pytest.ini_options]\naddopts = "--strict-markers"\n')
        git('add', '.'); git('commit', '-qm', 'packet base'); base = git('rev-parse', 'HEAD')
        scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join('REV_BASE=' + base if row.startswith('REV_BASE=') else row for row in scope_text.splitlines()) + '\n')
        write('main.py', (root / 'main.py').read_text().replace('value + 1', 'value + 10')
              .replace('value + 2', 'value + 20').replace('value + 3', 'value + 30'))
        m = prepare(); context = m['source_context']
        assert context['schema_version'] == 1 and context['enabled'] is True and context['snapshot_tree'] == m['snapshot_tree']
        assert context['max_shard_bytes'] == 32768
        context_words = sum(len((session / shard['artifact']).read_bytes().split())
                            for packet in context['seats'].values() for shard in packet['shards'])
        assert m['word_counts']['source_context'] == context_words
        assert m['word_counts']['avoided'] == max(
            0, len(m['assignments']) * m['word_counts']['full']
            - m['word_counts']['assigned_patch'] - len(m['assignments']) * m['word_counts']['evidence']
            - context_words)
        owner = m['mechanical_owner']
        for seat, packet in context['seats'].items():
            assert packet['role'] == ('integration' if seat == owner else 'specialist')
            assert 0 < len(packet['shards']) <= (3 if seat == owner else 1)
            for shard in packet['shards']:
                path = session / shard['artifact']; raw = path.read_bytes()
                assert shard['bytes'] == len(raw) <= 32768
                assert shard['sha256'] == hashlib.sha256(raw).hexdigest()
                body = json.loads(raw)
                assert body['snapshot_tree'] == m['snapshot_tree'] and body['seat'] == seat
                assert [{key: value for key, value in entry.items() if key != 'content'}
                        for entry in body['entries']] == shard['ranges']
                for entry in body['entries']:
                    assert 1 <= entry['line_start'] <= entry['line_end']
                    assert entry['component_ids'] and len(entry['hunk_binding_sha256']) == 64
                    assert 'hunk_sha256' not in entry
                    expected = ''.join((root / entry['path']).read_text().splitlines(keepends=True)[entry['line_start'] - 1:entry['line_end']])
                    assert entry['content'] == expected
        integration = [json.loads((session / shard['artifact']).read_text())
                       for shard in context['seats'][owner]['shards']]
        reasons = [reason for shard in integration for entry in shard['entries'] for reason in entry['reasons']]
        assert all(len(entry['reasons']) == len(set(entry['reasons']))
                   for shard in integration for entry in shard['entries'])
        assert {'declaration:first', 'declaration:second'} <= set(reasons)
        assert {'production-caller:first', 'production-caller:second'} <= set(reasons)
        assert any(reason.startswith('related-test:') for reason in reasons)
        assert any(reason.startswith('gate:') for reason in reasons)
        prompt = call('render', session / 'r1-evidence.manifest.json', owner)
        assert 'Source context enabled: true' in prompt and 'Source context packet:' in prompt and 'Source read required:' in prompt
        assert 'Read the entire assigned patch in bounded windows of at most 240 lines:' in prompt
        old = module.Repository
        try:
            module.Repository = lambda *_: (_ for _ in ()).throw(AssertionError('offline source-context validation used Git'))
            module.validated_manifest(session / 'r1-evidence.manifest.json', fresh=False, offline=True)
        finally:
            module.Repository = old
        manifest_path = session / 'r1-evidence.manifest.json'
        call('verify', manifest_path)
        call('render', manifest_path, owner, '--offline')
        source_before = (root / 'main.py').read_text()
        write('main.py', source_before + '# changed after verification\n')
        call('render', manifest_path, owner, '--offline')
        call('verify', manifest_path, good=False)
        write('main.py', source_before)

        evidence_path = session / 'r1-evidence.json'
        original = {path: path.read_bytes() for path in session.glob('r1-*')}
        def restore():
            for path, raw in original.items(): path.write_bytes(raw)
        def reseal(transform):
            manifest = json.loads(manifest_path.read_text()); evidence = json.loads(evidence_path.read_text())
            seat = owner; shard_meta = manifest['source_context']['seats'][seat]['shards'][0]
            artifact = session / shard_meta['artifact']; payload = json.loads(artifact.read_text())
            transform(manifest, payload)
            artifact.write_bytes(module.encoded(payload))
            shard_meta = manifest['source_context']['seats'][seat]['shards'][0]
            shard_meta.update(sha256=module.digest(artifact.read_bytes()), bytes=len(artifact.read_bytes()),
                              ranges=[{key: value for key, value in entry.items() if key != 'content'}
                                      for entry in payload['entries']], entries=len(payload['entries']))
            evidence['source_context'] = manifest['source_context']
            evidence_path.write_bytes(module.encoded(evidence))
            manifest['artifacts'][artifact.name] = {'sha256': module.digest(artifact.read_bytes()),
                                                    'words': len(artifact.read_bytes().split())}
            manifest['artifacts'][evidence_path.name] = {'sha256': module.digest(evidence_path.read_bytes()),
                                                        'words': len(evidence_path.read_bytes().split())}
            manifest_path.write_bytes(module.encoded(manifest))

        def replace_content_with_valid_hash(manifest, payload):
            entry = payload['entries'][0]
            original = entry['content']
            replacement = ('X' if original[:1] != 'X' else 'Y') + original[1:]
            entry.update(content=replacement, content_sha256=module.digest(replacement.encode()))

        mutations = [
            lambda m, p: p['entries'][0].update(path='../escape.py'),
            lambda m, p: p['entries'][0].update(line_start=p['entries'][0]['line_end'] + 1),
            lambda m, p: p['entries'][0].update(content=p['entries'][0]['content'][:-1]),
            lambda m, p: p['entries'][0].update(component_ids=[]),
            lambda m, p: p['entries'][0].update(hunk_binding_sha256='0' * 64),
            lambda m, p: p['entries'][0].update(blob_oid='0' * 40),
            replace_content_with_valid_hash,
            lambda m, p: p['entries'].reverse(),
            lambda m, p: p['entries'][0].update(content='x' * 40000),
        ]
        for mutation in mutations:
            restore(); reseal(mutation)
            call('render', manifest_path, owner, good=False)
        restore()
        source_path = session / context['seats'][owner]['shards'][0]['artifact']
        source_path.write_text(source_path.read_text() + ' ')
        call('render', manifest_path, owner, good=False)

    with fixture() as (root, session, git, write, call, prepare, finish):
        disabled_env = dict(os.environ, REV_SOURCE_CONTEXT='0')
        call('prepare', session, 'disabled', '--phase', 'discovery', env=disabled_env)
        m = json.loads((session / 'rdisabled-evidence.manifest.json').read_text())
        assert m['source_context']['enabled'] is False
        assert m['components'] and any(a['scope'] == 'semantic' for a in m['assignments'].values())
        assert m['word_counts']['source_context'] == 0
        assert all(not packet['shards'] and packet['source_read_required']
                   for packet in m['source_context']['seats'].values())
        assert not list(session.glob('rdisabled-*-source-context-*.json'))
        prompt = call('render', session / 'rdisabled-evidence.manifest.json', 'sol')
        assert 'Source context enabled: false' in prompt
        assert 'Source context packet:' not in prompt and 'Source read required: true' in prompt
        bad_env = dict(os.environ, REV_SOURCE_CONTEXT='maybe')
        call('prepare', session, 'badflag', '--phase', 'discovery', env=bad_env, good=False)

def complete_declaration_context():
    with fixture() as (root, session, git, write, call, prepare, finish):
        body = ('def long_function():\n'
                + ''.join(f'    value_{i} = {i}\n' for i in range(100))
                + '    return value_99\n')
        write('main.py', body); git('add', '.'); git('commit', '-qm', 'long declaration base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        changed = body.replace('value_50 = 50', 'value_50 = 500'); write('main.py', changed)
        manifest = prepare(); owner = manifest['mechanical_owner']
        facts = json.loads((session / 'r1-evidence.json').read_text())
        symbol = next(row for row in facts['symbols'] if row['name'] == 'long_function')
        assert symbol['line'] == 1 and symbol['line_end'] == 102
        entries = [entry for shard in manifest['source_context']['seats'][owner]['shards']
                   for entry in json.loads((session / shard['artifact']).read_text())['entries']]
        declaration = next(entry for entry in entries if 'declaration:long_function' in entry['reasons'])
        assert declaration['line_start'] == 1 and declaration['line_end'] == 102
        assert declaration['content'] == changed

    with fixture() as (root, session, git, write, call, prepare, finish):
        body = ('def oversized():\n'
                + ''.join(f'    value_{i} = "{i:04d}-' + 'x' * 50 + '"\n' for i in range(6000))
                + '    return value_5999\n')
        write('main.py', body); git('add', '.'); git('commit', '-qm', 'oversized declaration base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        write('main.py', body.replace('value_4000 =', 'value_4000_changed ='))
        manifest = prepare(); owner = manifest['mechanical_owner']
        packet = manifest['source_context']['seats'][owner]
        assert packet['omitted']['declaration'] >= 1 and packet['source_read_required'] is True
        required = packet['required_source_ranges']
        declaration = next(row for row in required if 'declaration:oversized' in row['reasons'])
        assert declaration['path'] == 'main.py' and declaration['line_start'] == 1 and declaration['line_end'] == 6002
        assert declaration['blob_tree'] == manifest['snapshot_tree']
        assert declaration['blob_oid'] and declaration['content_sha256']
        assert declaration['required_payload_bytes'] > manifest['source_context']['max_shard_bytes']
        rendered = call('render', session / 'r1-evidence.manifest.json', owner)
        assert 'Required source range: main.py:1-6002' in rendered
        reasons = [reason for shard in packet['shards']
                   for entry in json.loads((session / shard['artifact']).read_text())['entries']
                   for reason in entry['reasons']]
        assert 'declaration:oversized' not in reasons
        for seat in manifest['assignments']:
            (session / f'r1-{seat}.prompt.md').write_text(call('render', session / 'r1-evidence.manifest.json', seat))
            (session / f'r1-{seat}.json').write_text('{"summary":"checked","findings":[]}')
            (session / f'r1-{seat}.exit').write_text('0\n')
            write_agent_audit(session, '1', seat)
        call('receipt', session, '1')
        audit_path = session / f'r1-{owner}.read-audit.json'; saved_audit = audit_path.read_bytes()
        audit = json.loads(saved_audit)
        audit['source_ranges'] = [row for row in audit['source_ranges']
                                  if row['origin'] == 'packet' or (row['path'] == 'main.py' and row['line_start'] == 1)]
        audit['source_read_calls'] = 1; audit['opened_source_ranges'] = 1
        audit['required_source_ranges_covered'] = 0
        audit_path.write_text(json.dumps(audit)); call('receipt', session, '1', good=False)
        audit_path.write_bytes(saved_audit)

        manifest_path = session / 'r1-evidence.manifest.json'; evidence_path = session / 'r1-evidence.json'
        saved_manifest = manifest_path.read_bytes(); saved_evidence = evidence_path.read_bytes()
        for key, bad in [('line_end', 6001), ('blob_tree', manifest['base_tree']),
                         ('content_sha256', '0' * 64), ('required_payload_bytes', 32768)]:
            changed_manifest = json.loads(saved_manifest); changed_evidence = json.loads(saved_evidence)
            row = next(value for value in changed_manifest['source_context']['seats'][owner]['required_source_ranges']
                       if 'declaration:oversized' in value['reasons'])
            row[key] = bad
            changed_evidence['source_context'] = changed_manifest['source_context']
            evidence_path.write_bytes(module.encoded(changed_evidence))
            changed_manifest['artifacts'][evidence_path.name] = {
                'sha256': module.digest(evidence_path.read_bytes()),
                'words': len(evidence_path.read_bytes().split())}
            manifest_path.write_bytes(module.encoded(changed_manifest))
            call('render', manifest_path, owner, good=False)
        manifest_path.write_bytes(saved_manifest); evidence_path.write_bytes(saved_evidence)

    with fixture() as (root, session, git, write, call, prepare, finish):
        base_body = ('def provenance():\n'
                     + ''.join(f'    value_{i} = "base-{i:04d}-' + 'x' * 45 + '"\n'
                               for i in range(600))
                     + '    return value_599\n')
        write('provenance.py', base_body); git('add', '.'); git('commit', '-qm', 'provenance base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        head_body = base_body.replace('base-0300-', 'head-0300-')
        write('provenance.py', head_body); git('add', '.'); git('commit', '-qm', 'provenance head')
        head = git('rev-parse', 'HEAD'); git('checkout', '-q', base)
        call('prepare', session, 'named', '--phase', 'discovery', '--head', head)
        manifest_path = session / 'rnamed-evidence.manifest.json'
        manifest = json.loads(manifest_path.read_text()); owner = manifest['mechanical_owner']
        required = manifest['source_context']['seats'][owner]['required_source_ranges'][0]
        assert required['blob_tree'] == manifest['snapshot_tree'] == git('rev-parse', head + '^{tree}')
        for seat in manifest['assignments']:
            (session / f'rnamed-{seat}.prompt.md').write_text(call('render', manifest_path, seat))
            (session / f'rnamed-{seat}.json').write_text('{"summary":"checked","findings":[]}')
            (session / f'rnamed-{seat}.exit').write_text('0\n')
            write_agent_audit(session, 'named', seat)
        call('receipt', session, 'named')
        audit_path = session / f'rnamed-{owner}.read-audit.json'
        audit = json.loads(audit_path.read_text())
        proof = audit['required_source_range_proofs'][0]
        proof.update(blob_tree=manifest['base_tree'], blob_oid=git('rev-parse', base + ':provenance.py'),
                     content_sha256=module.digest(base_body.encode()))
        audit_path.write_text(json.dumps(audit))
        call('receipt', session, 'named', good=False)

    with fixture() as (root, session, git, write, call, prepare, finish):
        body = 'value = "' + 'x' * 2_000_010 + '"\n'
        write('huge.py', body); git('add', '.'); git('commit', '-qm', 'huge text base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        write('huge.py', body[:-2] + 'y"\n')
        call('prepare', session, 'unrepresentable', '--phase', 'discovery', good=False)

    with fixture() as (root, session, git, write, call, prepare, finish):
        (root / 'unrepresentable.py').write_bytes(b'\0binary source')
        call('prepare', session, 'binary', '--phase', 'discovery', good=False)

def budget_omissions_are_not_mandatory_ranges():
    with fixture() as (root, session, git, write, call, prepare, finish):
        for unit in range(4):
            body = (f'def unit_{unit}():\n'
                    + ''.join(f'    value_{index} = "{unit}-{index:04d}-' + 'x' * 55 + '"\n'
                              for index in range(260))
                    + '    return value_259\n')
            write(f'unit_{unit}.py', body)
        manifest = prepare('budget-omissions')
        omitted = [packet for packet in manifest['source_context']['seats'].values()
                   if packet['omitted']['declaration']]
        assert omitted
        assert all(packet['source_read_required'] and not packet['required_source_ranges']
                   for packet in omitted)
        finish('budget-omissions')

def innermost_declarations_and_bounded_anchors():
    with fixture() as (root, session, git, write, call, prepare, finish):
        method = ('    def changed_method(self):\n'
                  + ''.join(f'        value_{index} = "{index:04d}-' + 'x' * 45 + '"\n'
                            for index in range(280))
                  + '        return value_279\n')
        stable = ('    def stable_method(self):\n'
                  + ''.join(f'        stable_{index} = "{index:04d}-' + 'y' * 45 + '"\n'
                            for index in range(900))
                  + '        return stable_899\n')
        body = 'MODULE_FLAG = 1\n\nclass Large:\n' + method + '\n' + stable
        write('large.py', body); git('add', '.'); git('commit', '-qm', 'large class base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        changed = body.replace('MODULE_FLAG = 1', 'MODULE_FLAG = 2').replace(
            'value_140 = "0140-', 'value_140_changed = "0140-')
        write('large.py', changed)
        manifest = prepare('bounded-anchor'); facts = json.loads(
            (session / 'rbounded-anchor-evidence.json').read_text())
        symbols = [row for row in facts['symbols'] if row['path'] == 'large.py']
        declaration = next(row for row in symbols if row['name'] == 'changed_method')
        anchors = [row for row in symbols if row['kind'] == 'changed-line anchor']
        assert not any(row['name'] == 'Large' for row in symbols)
        assert declaration['line_end'] - declaration['line'] + 1 == 282
        assert len(anchors) == 1 and anchors[0]['line_end'] - anchors[0]['line'] + 1 <= 17
        owner = manifest['mechanical_owner']; packet = manifest['source_context']['seats'][owner]
        assert packet['source_read_required'] is True
        assert not [row for row in packet['required_source_ranges'] if row['path'] == 'large.py']
        entries = [entry for shard in packet['shards']
                   for entry in json.loads((session / shard['artifact']).read_text())['entries']]
        assert any('declaration:changed_method' in row['reasons'] for row in entries)
        assert any('declaration:changed-line-anchor' in row['reasons'] for row in entries)
        before_words = len(changed.split())
        after_words = sum(len((session / shard['artifact']).read_bytes().split())
                          for shard in packet['shards'])
        print(f'ANCHOR before_mandatory=1 after_mandatory=0 before_words={before_words} '
              f'packet_words={after_words}')
        finish('bounded-anchor')

def high_confidence_component_union():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('src/core.ts', 'import { dep } from "./dep";\nconst version = 1;\nexport function alpha() { return dep(); }\n')
        write('src/dep.ts', 'export function dep() { return 1; }\n')
        write('src/other.ts', 'export function other() { return 1; }\n')
        write('tests/multi.test.ts',
              'import { alpha } from "../src/core";\nimport { other } from "../src/other";\n'
              '// version 1\ntest("both", () => alpha() + other());\n')
        write('a.py', 'def same_stem():\n    return 1\n')
        write('test_a.py', 'assert same_stem() == 1\n')
        write('a.md', 'version 1 same_stem alpha dep\n')
        git('add', '.'); git('commit', '-qm', 'component base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        for name in ('src/core.ts', 'src/dep.ts', 'src/other.ts', 'tests/multi.test.ts',
                     'a.py', 'test_a.py', 'a.md'):
            write(name, (root / name).read_text().replace('1', '2', 1))
        manifest = prepare('component-policy')
        components = manifest['components']
        assert {path for component in components for path in component['files']} == set(manifest['semantic_paths'])
        assert len([path for component in components for path in component['files']]) == len(manifest['semantic_paths'])
        imported = next(component for component in components if 'src/core.ts' in component['files'])
        assert {'src/core.ts', 'src/dep.ts'} <= set(imported['files'])
        same_stem = next(component for component in components if 'a.py' in component['files'])
        assert 'test_a.py' in same_stem['files'] and 'a.md' not in same_stem['files']
        multi = next(component for component in components if 'tests/multi.test.ts' in component['files'])
        assert multi['files'] == ['tests/multi.test.ts']
        other = next(component for component in components if 'src/other.ts' in component['files'])
        assert 'tests/multi.test.ts' in imported['boundary'] and 'tests/multi.test.ts' in other['boundary']
        prose = next(component for component in components if 'a.md' in component['files'])
        assert prose['files'] == ['a.md']
        evidence = json.loads((session / 'rcomponent-policy-evidence.json').read_text())
        repo = module.Repository(session.resolve()); snapshot, _ = repo.snapshot()
        changes, _, categories, _ = repo.changes(repo.tree(base), snapshot)
        patches = {path: patch for path, patch in changes if categories[path] == 'semantic'}
        chosen = {seat: assignment['bundle'] for seat, assignment in manifest['assignments'].items()}
        assert components == module.components_for(
            patches, list(reversed(evidence['dependencies'])), chosen,
            manifest['mechanical_owner'])
        specialist_files = {path for component in components if component['specialists']
                            for path in component['files']}
        assert specialist_files == set(manifest['semantic_paths'])
        owner_patch = Path(manifest['assignments'][manifest['mechanical_owner']]['patch']).read_text()
        assert all(path in owner_patch for path in manifest['semantic_paths'])

def components_ownership_and_instructions():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('AGENTS.md', 'Repository constraint.\n'); write('src/AGENTS.md', 'Source constraint.\n')
        write('src/a.ts', 'import { dependency } from "./dep";\nexport function alpha() { return dependency(); }\n')
        write('src/dep.ts', 'export function dependency() { return 1; }\n')
        write('separate.py', 'def separate():\n    return 1\n')
        write('large.py', ''.join(f'value_{i} = {i}\n' for i in range(1200)))
        m = prepare()
        component = next(c for c in m['components'] if 'src/a.ts' in c['files'])
        assert 'src/dep.ts' in component['files'] and component['edges']
        covered = {p for c in m['components'] if c['specialists'] for p in c['files']}
        assert covered == set(m['semantic_paths'])
        assert (session / 'r1-instructions.md').read_text().count('Repository constraint.') == 1
        assert 'Source constraint.' in (session / 'r1-instructions.md').read_text()
        assert any(p.endswith('-grok.patch') for p in m['artifacts'])
        finding_owner = component['specialists'][0]
        finding = {'severity':'P2','file':'src/a.ts','line_start':2,'line_end':2,'claim':'Dependency result needs validation','evidence':'The result is returned directly.','suggested_fix':'Validate it.','confidence':0.9}
        for seat in m['assignments']:
            (session / f'r1-{seat}.prompt.md').write_text(call('render', session / 'r1-evidence.manifest.json', seat))
            (session / f'r1-{seat}.json').write_text(json.dumps({'summary':'checked','findings':[finding] if seat == finding_owner else []}))
            (session / f'r1-{seat}.exit').write_text('0\n')
        for seat in m['assignments']:
            write_agent_audit(session, '1', seat)
        call('receipt', session, '1')
        receipt = json.loads((session / 'r1-coverage.receipt.json').read_text())
        assert receipt['findings'][0]['owners'] == [finding_owner] and len(receipt['findings'][0]['id']) == 64
        write('src/dep.ts', 'export function dependency() { return 2; }\n')
        later = prepare('2', 'verification', *assign)
        changed = next(c for c in later['components'] if 'src/dep.ts' in c['files'])
        assert finding_owner in changed['specialists'] or finding_owner == later['mechanical_owner']
        old = module.Repository
        try:
            module.Repository = lambda *_: (_ for _ in ()).throw(AssertionError('offline validator used Git'))
            module.validated_manifest(session / 'r2-evidence.manifest.json', fresh=False, offline=True)
        finally:
            module.Repository = old

def instruction_override_precedence():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('AGENTS.md', 'root ordinary\n'); write('AGENTS.override.md', 'root override\n')
        write('src/AGENTS.md', 'src ordinary\n'); write('src/AGENTS.override.md', 'src override\n')
        write('src/deep/AGENTS.md', 'deep ordinary\n'); write('src/deep/main.py', 'value = 1\n')
        git('add', '.'); git('commit', '-qm', 'instruction base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        write('src/deep/main.py', 'value = 2\n')
        worktree = prepare('override-worktree')
        assert [row['path'] for row in worktree['instructions']] == [
            'AGENTS.override.md', 'src/AGENTS.override.md', 'src/deep/AGENTS.md']
        packet = (session / 'roverride-worktree-instructions.md').read_text()
        assert 'root override' in packet and 'src override' in packet and 'deep ordinary' in packet
        assert 'root ordinary' not in packet and 'src ordinary' not in packet

        write('src/deep/AGENTS.override.md', 'deep snapshot override\n')
        git('add', '.'); git('commit', '-qm', 'named instruction head'); head = git('rev-parse', 'HEAD')
        git('checkout', '-q', base)
        named = prepare('override-ref', 'discovery', '--head', head)
        assert [row['path'] for row in named['instructions']] == [
            'AGENTS.override.md', 'src/AGENTS.override.md', 'src/deep/AGENTS.override.md']
        assert 'deep snapshot override' in (session / 'roverride-ref-instructions.md').read_text()
        manifest_path = session / 'roverride-ref-evidence.manifest.json'
        manifest = json.loads(manifest_path.read_text()); evidence_path = session / 'roverride-ref-evidence.json'
        evidence = json.loads(evidence_path.read_text())
        manifest['instructions'][0]['path'] = 'AGENTS.md'; evidence['instructions'] = manifest['instructions']
        evidence_path.write_bytes(module.encoded(evidence))
        manifest['artifacts'][evidence_path.name] = {
            'sha256': module.digest(evidence_path.read_bytes()), 'words': len(evidence_path.read_bytes().split())}
        manifest_path.write_bytes(module.encoded(manifest))
        call('render', manifest_path, 'sol', good=False)
        (root / 'AGENTS.override.md').write_bytes(b'\xff')
        call('prepare', session, 'unreadable-override', '--phase', 'discovery', good=False)

def empty_source_context():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('emptied.py', 'value = 1\n'); write('deleted-empty.py', '')
        git('add', '.'); git('commit', '-qm', 'empty context base')
        base = git('rev-parse', 'HEAD'); scope_text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join(
            'REV_BASE=' + base if row.startswith('REV_BASE=') else row
            for row in scope_text.splitlines()) + '\n')
        write('emptied.py', ''); (root / 'deleted-empty.py').unlink(); write('added-empty.py', '')
        manifest = prepare('empty-context')
        assert not manifest['snapshot_unsafe']
        owner = manifest['mechanical_owner']; packet = manifest['source_context']['seats'][owner]
        entries = [entry for shard in packet['shards']
                   for entry in json.loads((session / shard['artifact']).read_text())['entries']]
        emptied = next(entry for entry in entries if entry['path'] == 'emptied.py')
        assert emptied['content'] == 'value = 1\n' and emptied['blob_tree'] == manifest['base_tree']
        assert all(row['path'] not in ('added-empty.py', 'deleted-empty.py')
                   for row in [*entries, *packet['required_source_ranges']])
        finish('empty-context')

def bounded_work_and_memory():
    import tracemalloc
    with fixture() as (root, session, git, write, call, prepare, finish):
        for i in range(60): write(f'changed/{i}.py', f'value = {i}\n')
        for i in range(200): write(f'unchanged/{i}.txt', '# ' + 'x' * 100000 + f'{i}\n')
        git('add', '.'); git('commit', '-qm', 'bounded baseline')
        base = git('rev-parse', 'HEAD'); text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join('REV_BASE=' + base if s.startswith('REV_BASE=') else s for s in text.splitlines()) + '\n')
        for i in range(60): write(f'changed/{i}.py', f'value = {i + 1}\n')
        repo = module.Repository(session.resolve()); tree, _ = repo.snapshot(); _, hunks, cats, _ = repo.changes(repo.tree(base), tree)
        tracemalloc.start(); module.facts(repo, tree, hunks, cats); _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        assert peak < 16 * 1024 * 1024, ('repository-sized retained memory', peak)
        gitbin = subprocess.check_output(['which','git'], text=True).strip(); bindir=session/'bin'; bindir.mkdir(); log=session/'calls'
        wrapper=bindir/'git'; wrapper.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$EVIDENCE_GIT_LOG"\nexec '+shlex.quote(gitbin)+' "$@"\n'); wrapper.chmod(0o755)
        env=dict(os.environ, PATH=str(bindir)+os.pathsep+os.environ['PATH'], EVIDENCE_GIT_LOG=str(log))
        prepare(env=env)
        assert len(log.read_text().splitlines()) < 50, 'Git commands scale with changed paths'
        original_source_context = module.source_context
        def unexpected_source_context(*args, **kwargs):
            raise AssertionError('fresh validation rebuilt source context')
        module.source_context = unexpected_source_context
        try:
            module.validated_manifest(session / 'r1-evidence.manifest.json')
        finally:
            module.source_context = original_source_context
        assert os.access(script, os.X_OK), 'evidence entry point is not executable'

failures = []
def receipt_read_audits():
    with fixture() as (root, session, git, write, call, prepare, finish):
        roster = json.loads((session / 'roster.json').read_text()); roster['seats'][0]['adapter'] = 'codex'
        (session / 'roster.json').write_text(json.dumps(roster)); m = prepare()
        for seat in m['assignments']:
            (session / f'r1-{seat}.prompt.md').write_text(call('render', session / 'r1-evidence.manifest.json', seat))
            (session / f'r1-{seat}.json').write_text('{"summary":"checked","findings":[]}')
            (session / f'r1-{seat}.exit').write_text('0\n')
            if seat != 'sol':
                write_agent_audit(session, '1', seat)
        call('receipt', session, '1', good=False)
        stream = session / 'r1-sol.stream.ndjson'; stream.write_text('{}\n')
        manifest_path = session / 'r1-evidence.manifest.json'
        manifest = json.loads(manifest_path.read_text()); packet = manifest['source_context']['seats']['sol']
        packet_ranges = [{'path': row['path'], 'line_start': row['line_start'], 'line_end': row['line_end'], 'origin': 'packet'}
                         for shard in packet['shards'] for row in shard['ranges']]
        audit = {'schema_version':2,'status':'valid','narrow':False,'adapter':'codex',
                 'prompt_sha256':module.digest((session / 'r1-sol.prompt.md').read_bytes()),
                 'stream_sha256':module.digest(stream.read_bytes()),'violations':[],
                 'result_sha256':module.digest((session / 'r1-sol.json').read_bytes()),
                 'evidence_manifest_sha256':module.digest(manifest_path.read_bytes()),
                 'tool_calls':max(1, len(packet['shards'])),'tool_turns':max(1, len(packet['shards'])),
                 'tool_output_bytes':sum(shard['bytes'] for shard in packet['shards']),
                 'max_tool_output_bytes':max([shard['bytes'] for shard in packet['shards']] or [0]),
                 'recognized_tool_calls':max(1, len(packet['shards'])), 'source_read_calls':0,
                 'packet_shards':len(packet['shards']), 'packet_bytes':sum(shard['bytes'] for shard in packet['shards']),
                 'packet_ranges':len(packet_ranges), 'opened_source_ranges':0,
                 'finding_citations':0, 'required_source_ranges_covered':0,
                 'required_source_range_proofs':[],
                 'source_ranges':sorted(packet_ranges, key=lambda row: (row['path'], row['line_start'], row['line_end'], row['origin']))}
        path = session / 'r1-sol.read-audit.json'
        for key, bad in [('status','invalid'), ('prompt_sha256','0'*64), ('stream_sha256','0'*64),
                         ('result_sha256','0'*64), ('evidence_manifest_sha256','0'*64),
                         ('adapter','agent'), ('narrow',True), ('violations',['outside']),
                         ('tool_calls',None), ('recognized_tool_calls',0), ('packet_bytes',0),
                         ('finding_citations',1), ('source_ranges',[])]:
            path.write_text(json.dumps(dict(audit, **{key:bad}))); call('receipt', session, '1', good=False)
        path.write_text(json.dumps(audit)); call('receipt', session, '1', good=False)
        patch = Path(manifest['assignments']['sol']['patch']); patch_lines = len(patch.read_bytes().splitlines())
        assignment = manifest['assignments']['sol']; patch_mode = assignment['patch_read_mode']
        chunks = manifest['patch_sets'][assignment['patch_set']]['chunks'] if patch_mode == 'chunks' else []
        audit.update(assigned_patch_sha256=module.digest(patch.read_bytes()),
                     assigned_patch_bytes=len(patch.read_bytes()), assigned_patch_lines=patch_lines,
                     assigned_patch_reads=len(chunks) if chunks else max(1, (patch_lines + 239) // 240),
                     assigned_patch_ranges=[] if chunks or patch_lines == 0 else [{'line_start':1, 'line_end':patch_lines}],
                     patch_proof_mode=patch_mode,
                     patch_proof_calls=len(chunks) if chunks else max(1, (patch_lines + 239) // 240),
                     patch_proof_turns=len(chunks) if chunks else max(1, (patch_lines + 239) // 240),
                     patch_proof_visible_bytes=len(patch.read_bytes()),
                     expected_patch_chunks=len(chunks), opened_patch_chunks=len(chunks))
        for key, bad in [('assigned_patch_sha256','0'*64), ('assigned_patch_bytes',0),
                         ('assigned_patch_lines',0), ('assigned_patch_reads',0),
                         ('assigned_patch_ranges',[{'line_start':2,'line_end':patch_lines}])]:
            path.write_text(json.dumps(dict(audit, **{key:bad}))); call('receipt', session, '1', good=False)
        path.write_text(json.dumps(audit)); call('receipt', session, '1')
        stream.write_text('changed\n'); call('receipt', session, '1', good=False)

def narrow_agent_requires_proven_reads():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write('main.py', 'def oversized():\n' + ''.join(
            f'    value_{index} = "{index:04d}-' + 'x' * 50 + '"\n' for index in range(1200))
              + '    return value_1199\n')
        manifest = prepare()
        for seat, assignment in manifest['assignments'].items():
            (session / f'r1-{seat}.prompt.md').write_text(call('render', session / 'r1-evidence.manifest.json', seat))
            (session / f'r1-{seat}.json').write_text('{"summary":"checked","findings":[]}')
            (session / f'r1-{seat}.exit').write_text('0\n')
            assert assignment['adapter'] == 'agent'
        for seat in manifest['assignments']:
            write_agent_audit(session, '1', seat)
        call('receipt', session, '1')
        manifest = prepare('narrow-corrupt')
        for seat in manifest['assignments']:
            (session / f'rnarrow-corrupt-{seat}.prompt.md').write_text(
                call('render', session / 'rnarrow-corrupt-evidence.manifest.json', seat))
            (session / f'rnarrow-corrupt-{seat}.json').write_text('{"summary":"checked","findings":[]}')
            (session / f'rnarrow-corrupt-{seat}.exit').write_text('0\n')
            write_agent_audit(session, 'narrow-corrupt', seat)
        seat = next(seat for seat, assignment in manifest['assignments'].items()
                    if assignment['scope'] != 'full')
        path = session / f'rnarrow-corrupt-{seat}.read-audit.json'; audit = json.loads(path.read_text())
        required = manifest['source_context']['seats'][seat]['required_source_ranges']
        assert required
        audit['source_ranges'] = [row for row in audit['source_ranges'] if row['origin'] == 'packet']
        outside = required[0]['line_end'] + 1
        audit['source_ranges'].append({'path': required[0]['path'], 'line_start': outside,
                                       'line_end': outside, 'origin': 'tool'})
        audit['source_ranges'].sort(key=lambda row: (row['path'], row['line_start'], row['line_end'], row['origin']))
        audit['source_read_calls'] = 1; audit['opened_source_ranges'] = 1
        audit['required_source_ranges_covered'] = 0; audit['required_source_range_proofs'] = []
        path.write_text(json.dumps(audit))
        call('receipt', session, 'narrow-corrupt', good=False)

def full_agent_requires_proven_reads():
    with fixture() as (root, session, git, write, call, prepare, finish):
        manifest = prepare('full-agent')
        seat = manifest['mechanical_owner']; manifest_path = session / 'rfull-agent-evidence.manifest.json'
        assert manifest['assignments'][seat]['scope'] == 'full'
        for assigned in manifest['assignments']:
            (session / f'rfull-agent-{assigned}.prompt.md').write_text(call('render', manifest_path, assigned))
            (session / f'rfull-agent-{assigned}.json').write_text('{"summary":"checked","findings":[]}')
            (session / f'rfull-agent-{assigned}.exit').write_text('0\n')
            write_agent_audit(session, 'full-agent', assigned)
        call('receipt', session, 'full-agent')
        manifest = prepare('full-agent-corrupt')
        seat = manifest['mechanical_owner']
        manifest_path = session / 'rfull-agent-corrupt-evidence.manifest.json'
        for assigned in manifest['assignments']:
            (session / f'rfull-agent-corrupt-{assigned}.prompt.md').write_text(
                call('render', manifest_path, assigned))
            (session / f'rfull-agent-corrupt-{assigned}.json').write_text(
                '{"summary":"checked","findings":[]}')
            (session / f'rfull-agent-corrupt-{assigned}.exit').write_text('0\n')
            write_agent_audit(session, 'full-agent-corrupt', assigned)
        (session / f'rfull-agent-corrupt-{seat}.read-audit.json').write_text('{}')
        call('receipt', session, 'full-agent-corrupt', good=False)

def scoped_names_and_gitlink_lifecycle():
    with fixture() as (root, session, git, write, call, prepare, finish):
        write(':(glob)thing[1].py', 'literal = 1\n'); write('thing1.py', 'SECRET_SIBLING\n')
        text = (session / 'scope.env').read_text().replace('REV_SCOPE=branch', "REV_SCOPE=':(glob)thing[1].py'")
        (session / 'scope.env').write_text(text)
        m = prepare(); assert m['paths'] == [':(glob)thing[1].py']; finish()
    with fixture() as (root, session, git, write, call, prepare, finish):
        child = root / 'module'; child.mkdir()
        def subgit(*args):
            return subprocess.check_output(['git', '-C', str(child), *args], stderr=subprocess.PIPE).decode().strip()
        subgit('init','-q'); subgit('config','user.name','Test'); subgit('config','user.email','test@example.invalid'); subgit('config','commit.gpgsign','false')
        (child / 'entry.py').write_text('value = 1\n'); subgit('add','.'); subgit('commit','-qm','first')
        git('add','module'); git('commit','-qm','gitlink base')
        base = git('rev-parse','HEAD'); text = (session / 'scope.env').read_text()
        (session / 'scope.env').write_text('\n'.join('REV_BASE=' + base if s.startswith('REV_BASE=') else s for s in text.splitlines()) + '\n')
        (child / 'entry.py').write_text('value = 2\n'); subgit('add','.'); subgit('commit','-qm','second')
        m = prepare(); assert 'Subproject commit' in (session / 'r1-full.patch').read_text(); finish()
        (child / 'entry.py').write_text('dirty\n'); call('prepare', session, 'dirty', '--phase','discovery',good=False)
        assert not list(session.glob('rdirty-*'))
        git('rm','-f','--cached','module'); shutil.rmtree(child)
        m = prepare('deleted'); assert 'deleted file mode 160000' in (session / 'rdeleted-full.patch').read_text(); finish('deleted')

def component_and_full_tampering():
    with fixture() as (root, session, git, write, call, prepare, finish):
        m = prepare(); mp = session / 'r1-evidence.manifest.json'; ep = session / 'r1-evidence.json'
        saved = {p: p.read_bytes() for p in session.glob('r1-*')}
        def replace(m,e):
            ep.write_bytes(module.encoded(e)); m['artifacts'][ep.name] = {'sha256':module.digest(ep.read_bytes()),'words':len(ep.read_bytes().split())}
            mp.write_bytes(module.encoded(m))
        e = json.loads(ep.read_text()); m['components'][0]['specialists'] = []; e['components'] = m['components']; replace(m,e)
        call('render', mp, 'sol', good=False)
        for path, data in saved.items(): path.write_bytes(data)
        m = json.loads(mp.read_text()); e = json.loads(ep.read_text())
        m['components'][0]['prior_owners'] = ['sol']; e['components'] = m['components']; replace(m,e)
        call('render',mp,'sol',good=False)
        for path, data in saved.items(): path.write_bytes(data)
        m = json.loads(mp.read_text()); e = json.loads(ep.read_text())
        m['paths'] = []; m['semantic_paths'] = []; m['components'] = []; m['fallback_reason'] = 'no semantic components'
        for seat, a in m['assignments'].items(): a.update(scope='full', full_state=True, patch=str(session.resolve()/'r1-full.patch'),components=[])
        for key in ('paths','semantic_paths','components','fallback_reason','assignments'): e[key] = m[key]
        for name in list(m['artifacts']):
            if name.endswith('.patch'):
                if name not in ('r1-full.patch','r1-semantic.patch','r1-delta.patch'): del m['artifacts'][name]; continue
                (session/name).write_bytes(b''); m['artifacts'][name] = {'sha256':module.digest(b''),'words':0}
        words=m['word_counts']; words.update(full=0,semantic=0,delta=0,assigned_patch=0,avoided=0); replace(m,e)
        call('render',mp,'sol',good=False)

def offline_structure_and_predecessor_walk():
    with fixture() as (root, session, git, write, call, prepare, finish):
        old = module.prior_coverage
        try:
            module.prior_coverage = lambda *_: (_ for _ in ()).throw(AssertionError('discovery/risk walked predecessor'))
            args = type('Args', (), {'session':str(session),'label':'probe','phase':'discovery','head':None,'assignment':[],'full_seat':None})()
            module.prepare(args)
            args.phase='risk'; args.label='risk-probe'; args.assignment=[s+'='+b for s,b in zip(seats,bundles)]; module.prepare(args)
        finally: module.prior_coverage=old
        m=prepare(); path=session/'r1-evidence.manifest.json'
        for bad in ({}, None, [], {'seats':None}):
            (session/'coverage-head.json').write_text(json.dumps(bad))
            m=prepare('fallback','verification',*assign)
            assert 'invalid coverage predecessor:' in m['fallback_reason']
        old=module.Repository
        try:
            module.Repository=lambda *_: (_ for _ in ()).throw(AssertionError('offline used repository'))
            module.validated_manifest(path, offline=True)
        finally: module.Repository=old

def local_ignored_instructions():
    with fixture() as (root, session, git, write, call, prepare, finish):
        (root/'.git/info/exclude').write_text('AGENTS.md\n')
        write('AGENTS.md','Applicable ignored repository rule.\n'); write('inside/main.py','value = 1\n')
        text=(session/'scope.env').read_text().replace('REV_SCOPE=branch','REV_SCOPE=inside'); (session/'scope.env').write_text(text)
        m=prepare(); assert 'Applicable ignored repository rule.' in (session/'r1-instructions.md').read_text()
        assert m['paths']==['inside/main.py']
        write('AGENTS.md','Changed local rule.\n'); call('render', session/'r1-evidence.manifest.json','sol',good=False)
        old=prepare('historical','discovery','--head','HEAD'); assert old['instructions']==[]
        (root/'AGENTS.md').unlink(); outside=root.parent/'outside-rules'; outside.write_text('OUTSIDE_RULE\n')
        (root/'AGENTS.md').symlink_to(outside)
        call('prepare',session,'unsafe-rules','--phase','discovery',good=False)
        assert not list(session.glob('runsafe-rules-*'))

for test in (storage_redirects, quoted_paths, changed_symbols, conservative_mechanical_classification, bounded_navigation_markdown, opaque_transitions, opaque_mode_transition, invalid_manifests, phase_and_predecessor_integrity, same_stat_and_index_flags, cstyle_enclosing_bodies, wallet_scale, literal_scope_and_inventories, sparse_gitlink_and_special, roster_bundle_coverage, source_context_packets, complete_declaration_context, budget_omissions_are_not_mandatory_ranges, innermost_declarations_and_bounded_anchors, high_confidence_component_union, components_ownership_and_instructions, instruction_override_precedence, empty_source_context, bounded_work_and_memory, receipt_read_audits, narrow_agent_requires_proven_reads, full_agent_requires_proven_reads, scoped_names_and_gitlink_lifecycle, component_and_full_tampering, offline_structure_and_predecessor_walk, local_ignored_instructions):
    try:
        test(); print('PASS', test.__name__)
    except Exception as error:
        failures.append(test.__name__); print('FAIL', test.__name__, str(error))
assert not failures, failures
PY
  local rc=$?
  if declare -F ok >/dev/null && declare -F fail >/dev/null; then
    if [ "$rc" -eq 0 ]; then ok "evidence hardening and scale"; else fail "evidence hardening and scale" "exit $rc"; fi
  fi
  return "$rc"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  test_evidence_contract && test_evidence_hardening
fi
