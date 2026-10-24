#!/bin/bash
# Exact source artifacts preserve caller proof within the frozen repository read budget.

test_code_proof_budget_promotes_exact_caller_segments() {
  ( local R="$T/proof-budget-root" S="$T/proof-budget-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
functions = []
for index in range(13):
    body = 'x' * 10000
    functions.append(f'def fn{index:02d}(value=None):\n    return "{body}"\n')
    call = 'y' * 8000
    (root / 'src' / f'use{index:02d}.py').write_text(
        f'from src.lib import fn{index:02d}\n\ndef use{index:02d}():\n    return fn{index:02d}("{call}")\n')
(root / 'src' / 'lib.py').write_text('\n'.join(functions))
PY
    git -C "$R" add . && git -C "$R" commit -qm "proof budget base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    python3 - "$R/src/lib.py" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text(path.read_text().replace('return "x', 'return "y', 13))
PY
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' src/lib.py > "$S/files.txt"
    : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" proof --phase discovery \
      > "$T/proof-budget.out" 2> "$T/proof-budget.err"
    local status=$?
    if [ "$status" -ne 0 ]; then
      cat "$T/proof-budget.out" "$T/proof-budget.err" >&2
    fi
    assert_eq "thirteen qualified consumers launch with exact source proof" "$status" 0
    [ "$status" -eq 0 ] || return 0
    local manifest="$S/rproof-evidence.manifest.json" prompt
    local bundle
    bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["sol"]["bundle"])' "$manifest") || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" proof sol "$bundle" \
      proof-budget --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/rproof-sol.json"
    python3 - "$manifest" "$SCRIPTS/rev-evidence.py" <<'PYPROOF'
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import sys

manifest_path = Path(sys.argv[1])
session = manifest_path.parent
manifest = json.loads(manifest_path.read_text())
context = manifest['source_context']['seats']['sol']
capacity = manifest['task_capacity']['seats']['sol']
assert manifest['task_capacity']['mandatory_repository_read_limit'] == 12, capacity
assert capacity['mandatory_repository_reads'] <= 12, capacity
expected = {f'src/use{index:02d}.py' for index in range(13)}
delivered = [row for shard in context['shards'] for row in shard['ranges']]
delivered += context['required_source_ranges']
assert all(any(row['path'] == path and row['line_start'] <= 4 <= row['line_end']
               for row in delivered) for path in expected), delivered
assert any(row['path'] in expected for row in context['required_source_ranges']), context
assert not any(row['path'] in expected for row in context['omitted_source_ranges']), context
spec = importlib.util.spec_from_file_location('proof_evidence', sys.argv[2])
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
events = []
def command(identifier, text, output):
    events.extend([
        {'type': 'item.started', 'item': {'id': identifier, 'type': 'command_execution',
                                         'command': text}},
        {'type': 'item.completed', 'item': {'id': identifier, 'type': 'command_execution',
                                           'command': text, 'aggregated_output': output,
                                           'exit_code': 0}},
    ])
def artifact(identifier, path):
    command(identifier, shlex.join(['cat', str(path)]), path.read_text())
for index, shard in enumerate(context['shards']):
    artifact(f'packet-{index}', session / shard['artifact'])
assignment = manifest['assignments']['sol']
if assignment['patch_read_mode'] == 'chunks':
    for chunk in manifest['patch_sets'][assignment['patch_set']]['chunks']:
        artifact(f'patch-{chunk["index"]}', session / chunk['artifact'])
else:
    patch = Path(assignment['patch'])
    lines = patch.read_text().splitlines(keepends=True)
    for first in range(1, len(lines) + 1, 40):
        last = min(first + 39, len(lines))
        command(f'patch-{first}', shlex.join(['sed', '-n', f'{first},{last}p', str(patch)]),
                ''.join(lines[first - 1:last]))
for index, required in enumerate(context['required_source_ranges']):
    for segment in required['segments']:
        artifact(f'source-{index}-{segment["index"]}', session / segment['artifact'])
artifact('index', session / 'rproof-evidence.md')
if context['source_read_required']:
    prompt = (session / 'rproof-sol.prompt.md').read_text()
    target = re.search(r'^Required post-index original-source target: (.+):(\d+)-(\d+) '
                       r'tree (\w+) blob (\w+) content SHA-256 (\w+) reasons ', prompt, re.M)
    assert target, prompt
    path, start, end, tree, oid, content_hash = target.groups()
    start, end = int(start), int(end)
    repo = evidence.Repository(session.resolve())
    entry = repo.entries(tree)[path]
    assert entry[1] == oid
    lines = evidence.split_lf_lines(repo.blob(entry))
    assert hashlib.sha256(b''.join(lines[start - 1:end])).hexdigest() == content_hash
    for first in range(start, end + 1, 40):
        last = min(first + 39, end)
        command(f'current-{first}', shlex.join(['git', 'show', tree + ':' + path])
                + ' | ' + shlex.join(['sed', '-n', f'{first},{last}p']),
                b''.join(lines[first - 1:last]).decode())
(session / 'rproof-sol.stream.ndjson').write_text(
    ''.join(json.dumps(event) + '\n' for event in events))
PYPROOF
    assert_eq "all thirteen consumers receive bounded immutable proof artifacts" "$?" 0
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/rproof-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/rproof-sol.read-audit.json" > "$T/proof-budget-audit.out" 2> "$T/proof-budget-audit.err"
    assert_eq "the complete caller proof passes the transcript audit" "$?" 0
    python3 - "$S/rproof-sol.read-audit.json" <<'PYAUDIT'
import json
import sys

audit = json.load(open(sys.argv[1]))
assert audit['status'] == 'valid', audit
expected = {f'src/use{index:02d}.py' for index in range(13)}
assert all(any(row['path'] == path and row['line_start'] <= 4 <= row['line_end']
               for row in audit['source_ranges']) for path in expected), audit
assert not audit['violations'], audit
PYAUDIT
    assert_eq "the auditor credits every qualified caller range" "$?" 0
  )
}

test_edited_tests_exceeding_proof_budget_are_refused() {
  ( local R="$T/proof-tests-root" S="$T/proof-tests-session"
    mkrepo "$R"; mkdir -p "$R/tests" "$S"
    python3 - "$R" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for index in range(13):
    (root / 'tests' / f'test_{index:02d}.py').write_text(
        f'def test_{index:02d}():\n    assert True\n')
PY
    git -C "$R" add . && git -C "$R" commit -qm "proof test base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    python3 - "$R" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for path in (root / 'tests').glob('test_*.py'):
    path.write_text(path.read_text().replace('assert True', 'assert False'))
PY
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' "$R"/tests/test_*.py | sed "s#^$R/##" > "$S/files.txt"
    : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=0 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" tests --phase discovery \
      > "$T/proof-tests.out" 2> "$T/proof-tests.err"
    local status=$?
    if [ "$status" -ne 2 ]; then
      echo "---- prepare stdout ----" >&2
      cat "$T/proof-tests.out" >&2
      echo "---- prepare stderr ----" >&2
      cat "$T/proof-tests.err" >&2
    fi
    assert_eq "edited tests beyond the proof budget are refused before launch" "$status" 2
    [ "$status" -eq 2 ] || return 0
    assert_grep "the refusal names the frozen proof budget" \
      "$T/proof-tests.err" 'proof reads exceed repository capacity: sol limit=12 count='
    python3 - "$S" <<'PY'
import json, sys
from pathlib import Path
diagnostic = json.loads((Path(sys.argv[1]) / 'prepare-diagnostic-tests.json').read_text())
row = next(item for item in diagnostic['refusals'] if item['seat'] == 'sol')
assert row['count'] > 12, row
assert row['partitions']
assert sum(partition['reads'] for partition in row['partitions']) == row['count']
assert all(1 <= partition['reads'] <= 12 for partition in row['partitions'])
assert all(path.startswith('tests/test_') for partition in row['partitions'] for path in partition['paths'])
PY
    assert_eq "edited-test partitions stay inside the frozen budget" "$?" 0
  )
}

test_unsplittable_source_line_stays_launchable() {
  ( local R="$T/wide-line-root" S="$T/wide-line-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    printf '%s\n' 'def wide():' '    return "base"' > "$R/src/lib.py"
    git -C "$R" add . && git -C "$R" commit -qm "wide line base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    python3 - "$R/src/lib.py" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_text('def wide():\n    return "' + ('x' * 40000) + '"\n')
PY
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' src/lib.py > "$S/files.txt"
    : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" wide --phase discovery \
      > "$T/wide-line.out" 2> "$T/wide-line.err"
    local status=$?
    if [ "$status" -ne 0 ]; then
      echo "---- prepare stdout ----" >&2
      cat "$T/wide-line.out" >&2
      echo "---- prepare stderr ----" >&2
      cat "$T/wide-line.err" >&2
    fi
    assert_eq "an unsplittable source line does not abort preparation" "$status" 0
    [ "$status" -eq 0 ] || return 0
    assert_nogrep "the segment ceiling is not a prepare failure" \
      "$T/wide-line.err" 'required source line exceeds visible segment limit'
    python3 - "$S" <<'PY'
import json, sys
from pathlib import Path
session = Path(sys.argv[1])
manifest = json.loads((session / 'rwide-evidence.manifest.json').read_text())
packet = manifest['source_context']['seats']['sol']
assert packet['required_source_ranges'] == []
assert packet['omitted_source_ranges'] == []
assert packet['source_read_required'] is False
assert packet['omitted']['declaration'] >= 1
PY
    assert_eq "the unsplittable line is not a required source read" "$?" 0
    python3 "$SCRIPTS/rev-evidence.py" verify "$S/rwide-evidence.manifest.json" \
      > "$T/wide-line-verify.out" 2> "$T/wide-line-verify.err"
    assert_eq "verify accepts a panel that omitted an unsplittable line" "$?" 0
  )
}
