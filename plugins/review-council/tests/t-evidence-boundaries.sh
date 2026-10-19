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
        {'seat': 'terra', 'adapter': 'codex'},
        {'seat': 'opus', 'adapter': 'claude'},
        {'seat': 'sonnet', 'adapter': 'claude'},
    ]}))
    (session / 'files.txt').write_text('')
    (session / 'untracked.txt').write_text('')
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

test_generated_lexical_callers_do_not_become_source_obligations() {
  ( local R="$T/generated-caller-root" S="$T/generated-caller-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
(root / 'src/main.py').write_text('def options(value):\n    return value + 1\n')
(root / 'src/consumer.py').write_text(
    'from main import options\n\ndef consume():\n    return options(1)\n')
(root / 'src/original.ts').write_text(
    'export function consumeOriginal() { return options(2); }\n')
source_map = json.dumps({
    'version': 3, 'file': 'bundle.js', 'sources': ['../src/original.ts'],
    'sourcesContent': ['options(2);\n' + 'x' * (20 * 1024)],
    'names': ['options'], 'mappings': '',
}, separators=(',', ':')) + '\n'
outputs = {
    '00-first.js.map': source_map,
    'zz-last.js.map': source_map,
    'dist/bundle.min.js': 'options(2);\n',
    'generated/bundle.js': 'options(2);\n',
    'emitted/bundle.js': '// @generated\noptions(2);\n',
}
for path, body in outputs.items():
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
PY
    git -C "$R" add . && git -C "$R" commit -qm "generated caller base"
    local base manifest
    base=$(git -C "$R" rev-parse HEAD)
    printf 'def options(value):\n    return value + 2\n' > "$R/src/main.py"
    printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" "$base" "$R" > "$S/scope.env"
    : > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    manifest=$(REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1 --phase discovery) || return
    python3 - "$manifest" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
manifest = json.loads(path.read_text())
rows = [row for packet in manifest['source_context']['seats'].values()
        for shard in packet['shards'] for row in shard['ranges']]
rows += [row for packet in manifest['source_context']['seats'].values()
         for row in packet['required_source_ranges']]
for caller in ('src/consumer.py', 'src/original.ts'):
    assert any(row['path'] == caller and any(
        reason in ('production-caller:options', 'extra-caller:options')
        for reason in row['reasons']) for row in rows), (caller, rows)
generated = {'00-first.js.map', 'zz-last.js.map', 'dist/bundle.min.js',
             'generated/bundle.js', 'emitted/bundle.js'}
selected = [row for row in rows if row['path'] in generated]
assert not selected, ('unchanged generated lexical callers became source obligations', selected)
assert any(row['path'] in ('src/consumer.py', 'src/original.ts')
           and 'production-caller:options' in row['reasons'] for row in rows), rows
PY
    assert_eq "generated lexical noise leaves authored caller proof selected" "$?" 0
  )
}

test_generated_declarations_and_changed_outputs_remain_reviewable() {
  ( local R="$T/generated-proof-root" S="$T/generated-proof-session" cargo_home="$T/generated-proof-cargo"
    mkrepo "$R"; mkdir -p "$R/src" "$R/generated" "$S"
    printf 'def options(value):\n    return value + 1\n' > "$R/src/main.py"
    printf '// @generated\nexport function options(value: number): number;\n' > "$R/generated/api.d.ts"
    printf '{"version":3,"sourcesContent":["options(1);"],"mappings":""}\n' > "$R/generated/bundle.js.map"
    cat > "$R/Cargo.lock" <<'EOF'
version = 3

[[package]]
name = "pinned"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "0000000000000000000000000000000000000000000000000000000000000000"
EOF
    local dependency="$cargo_home/registry/src/index.crates.io-0/pinned-1.0.0"
    mkdir -p "$dependency/src"
    printf '// @generated\npub fn options() {}\n' > "$dependency/src/lib.rs"
    git -C "$R" add . && git -C "$R" commit -qm "generated proof base"
    local base manifest
    base=$(git -C "$R" rev-parse HEAD)
    printf 'def options(value):\n    return value + 2\n' > "$R/src/main.py"
    printf '// @generated\nexport function options(value: number, strict: boolean): number;\n' > "$R/generated/api.d.ts"
    printf '{"version":3,"sourcesContent":["options(2);"],"mappings":""}\n' > "$R/generated/bundle.js.map"
    printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" "$base" "$R" > "$S/scope.env"
    : > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    manifest=$(env -u REV_DEPS_DIR CARGO_HOME="$cargo_home" REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1 --phase discovery) || return
    python3 - "$manifest" "$dependency" "$SCRIPTS/rev-prompt.sh" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

path = Path(sys.argv[1])
manifest = json.loads(path.read_text())
owner = manifest['mechanical_owner']
patch = Path(manifest['assignments'][owner]['patch']).read_text()
assert 'generated/api.d.ts' in patch and 'strict: boolean' in patch, patch
assert 'generated/bundle.js.map' in patch and 'options(2);' in patch, patch
rows = [row for packet in manifest['source_context']['seats'].values()
        for shard in packet['shards'] for row in shard['ranges']]
rows += [row for packet in manifest['source_context']['seats'].values()
         for row in packet['required_source_ranges']]
assert any(row['path'] == 'generated/api.d.ts' and 'declaration:options' in row['reasons']
           and row['blob_tree'] == manifest['snapshot_tree'] for row in rows), rows
view = manifest['dependency_view']
assert view['crates'] == ['pinned-1.0.0'], view
linked = Path(view['path']) / 'pinned-1.0.0/src/lib.rs'
assert linked.resolve() == Path(sys.argv[2]).resolve() / 'src/lib.rs'
assert linked.read_text() == '// @generated\npub fn options() {}\n'
env = dict(os.environ)
env.pop('REV_DEPS_DIR', None)
prompt_path = subprocess.check_output(
    [sys.argv[3], str(path.parent), '1', owner, manifest['assignments'][owner]['bundle'],
     'generated proof', '--evidence', str(path)], env=env, text=True).strip()
prompt = Path(prompt_path).read_text()
assert f'Read pinned dependency source only under {view["path"]}.' in prompt, prompt
PY
    assert_eq "generated declarations, changed output and explicit pinned dependencies stay reviewable" "$?" 0
  )
}
