#!/bin/bash

test_deleted_symbol_caller_evidence() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

script = sys.argv[1]
with tempfile.TemporaryDirectory(prefix='deleted-symbol-') as tmp:
    root = Path(tmp) / 'repo'
    session = Path(tmp) / 'session'
    root.mkdir(); session.mkdir()
    git_config = Path(tmp) / 'gitconfig'
    git_config.write_text('')
    git_env = dict(os.environ, GIT_CONFIG_GLOBAL=str(git_config), GIT_CONFIG_NOSYSTEM='1')

    def git(*args):
        return subprocess.check_output(
            ['git', '-C', str(root), *args], env=git_env).decode().strip()

    git('init', '-q')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@invalid')
    git('config', 'commit.gpgsign', 'false')
    (root / 'deleted.py').write_text('def gone(value):\n    return value + 1\n')
    (root / 'mixed.py').write_text(
        'def removed(value):\n    return value + 2\n\n'
        'def removed(value, extra):\n    return value + extra\n')
    (root / 'containers.py').write_text(
        'class A:\n    def duplicate(self):\n        return 1\n\n'
        'class B:\n    def duplicate(self):\n        return 2\n')
    signature_body = ''.join(f'    value_{index} = {index}\n' for index in range(500))
    (root / 'signature.py').write_text('def compute(value):\n' + signature_body)
    (root / 'overload.ts').write_text(
        'function parse(value: string): string;\n'
        'function parse(value: number): number;\n'
        'function parse(value: string | number): string | number { return value; }\n')
    (root / 'caller.py').write_text(
        'first = gone(1)\nsecond = removed(1)\nthird = A().duplicate()\n'
        'fourth = parse("1")\n')
    git('add', '.')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    (root / 'deleted.py').unlink()
    (root / 'mixed.py').write_text(
        'def removed(value, extra):\n    return value + extra\n')
    (root / 'containers.py').write_text(
        'class RenamedB:\n  def duplicate(self):\n    return 2\n')
    (root / 'signature.py').write_text(
        'def compute(value, extra=0):\n' + signature_body)
    (root / 'overload.ts').write_text(
        'function parse(value: number, radix?: number): number;\n'
        'function parse(value: string | number): string | number { return value; }\n')
    (session / 'scope.env').write_text(
        f"REV_BASE='{base}'\nREV_ROOT='{root}'\nREV_SCOPE='branch'\n")
    (session / 'roster.json').write_text(json.dumps({'seats': [
        {'seat': 'sol', 'adapter': 'codex'},
        {'seat': 'grok', 'adapter': 'grok'},
        {'seat': 'opus', 'adapter': 'claude'},
        {'seat': 'opus-2', 'adapter': 'claude'},
    ]}))
    env = dict(git_env, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1')
    subprocess.run(
        [sys.executable, script, 'prepare', str(session), '1', '--phase', 'discovery'],
        env=env, check=True, capture_output=True)
    evidence = json.loads((session / 'r1-evidence.json').read_text())
    manifest = json.loads((session / 'r1-evidence.manifest.json').read_text())
    assert any(row['path'] == 'deleted.py' and row['name'] == 'gone'
               for row in evidence['symbols']), evidence['symbols']
    assert any(row['path'] == 'mixed.py' and row['name'] == 'removed'
               for row in evidence['symbols']), evidence['symbols']
    assert any(row['path'] == 'caller.py' and row['name'] == 'gone'
               for row in evidence['call_sites']), evidence['call_sites']
    assert any(row['path'] == 'caller.py' and row['name'] == 'removed'
               for row in evidence['call_sites']), evidence['call_sites']
    assert any(row['path'] == 'containers.py' and row['name'] == 'duplicate'
               and row['blob_tree'] == manifest['base_tree']
               and row['line'] == 2 and row['line_end'] == 3
               for row in evidence['symbols']), evidence['symbols']
    assert any(row['path'] == 'caller.py' and row['name'] == 'duplicate'
               for row in evidence['call_sites']), evidence['call_sites']
    compute = [row for row in evidence['symbols']
               if row['path'] == 'signature.py' and row['name'] == 'compute']
    assert len(compute) == 1 and compute[0]['blob_tree'] == manifest['snapshot_tree'], compute
    old_parse = [row for row in evidence['symbols']
                 if row['path'] == 'overload.ts' and row['name'] == 'parse'
                 and row['blob_tree'] == manifest['base_tree']]
    assert len(old_parse) == 1 and old_parse[0]['line'] == 1, old_parse
    assert any(row['path'] == 'caller.py' and row['name'] == 'parse'
               for row in evidence['call_sites']), evidence['call_sites']
    ranges = [row for packet in manifest['source_context']['seats'].values()
              for shard in packet['shards'] for row in shard['ranges']]
    ranges += [row for packet in manifest['source_context']['seats'].values()
               for row in packet['required_source_ranges']]
    assert any(row['path'] == 'mixed.py' and row['blob_tree'] == manifest['base_tree']
               and 'declaration:removed' in row['reasons'] for row in ranges), ranges
    assert any(row['path'] == 'caller.py' and row['blob_tree'] == manifest['snapshot_tree']
               and 'production-caller:removed' in row['reasons'] for row in ranges), ranges
    assert any(row['path'] == 'containers.py' and row['blob_tree'] == manifest['base_tree']
               and 'declaration:duplicate' in row['reasons'] for row in ranges), ranges
    assert not any(row['path'] == 'signature.py' and row['blob_tree'] == manifest['base_tree']
                   and 'declaration:compute' in row['reasons'] for row in ranges), ranges
PY
  assert_eq "deleted declarations retain surviving caller evidence" "$?" 0
}
