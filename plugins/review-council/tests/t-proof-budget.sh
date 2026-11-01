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
    sonnet_21_windows_fit_and_are_read_audited
  )
}

test_edited_tests_exceeding_proof_budget_are_refused() {
  ( local R="$T/proof-tests-root" S="$T/proof-tests-session"
    mkrepo "$R"; mkdir -p "$R/tests" "$S"
    python3 - "$R" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for index in range(17):
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
      "$T/proof-tests.err" 'proof reads exceed repository capacity: sol limit=16 count='
    python3 - "$S" <<'PY'
import json, sys
from pathlib import Path
diagnostic = json.loads((Path(sys.argv[1]) / 'prepare-diagnostic-tests.json').read_text())
row = next(item for item in diagnostic['refusals'] if item['seat'] == 'sol')
assert row['count'] > 16, row
assert row['partitions']
assert sum(partition['reads'] for partition in row['partitions']) == row['count']
assert all(1 <= partition['reads'] <= 16 for partition in row['partitions'])
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
    sonnet_22_windows_are_refused
  )
}

sonnet_window_fixture() {
  local count=$1 name=$2 R="$T/sonnet-window-$2-root" S="$T/sonnet-window-$2-session"
  mkrepo "$R" || return
  mkdir -p "$R/tests" "$S"
  python3 - "$R" "$count" <<'PY'
from pathlib import Path
import sys
root, count = Path(sys.argv[1]), int(sys.argv[2])
for index in range(count):
    (root / 'tests' / f'test_{index:02d}.py').write_text(
        f'def test_{index:02d}():\n    assert True\n')
PY
  git -C "$R" add . && git -C "$R" commit -qm "sonnet proof window base" || return
  local base; base=$(git -C "$R" rev-parse HEAD) || return
  python3 - "$R" <<'PY'
from pathlib import Path
import sys
for path in (Path(sys.argv[1]) / 'tests').glob('test_*.py'):
    path.write_text(path.read_text().replace('assert True', 'assert False'))
PY
  printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
    "$base" "$R" > "$S/scope.env"
  printf '%s\n' "$R"/tests/test_*.py | sed "s#^$R/##" > "$S/files.txt"
  : > "$S/untracked.txt"
  printf '%s\n' '{"seats":[{"seat":"sonnet","adapter":"claude","model":"sonnet","effort":"high","extra":false},{"seat":"sol","adapter":"codex","model":"gpt-6-sol","effort":"high","extra":false},{"seat":"opus","adapter":"claude","model":"opus","effort":"high","extra":false}]}' > "$S/roster.json"
  printf '%s\n' "$R" "$S"
}

sonnet_preserve_window_artifacts() {
  local name=$1 base=${REVIEW_COUNCIL_TEST_ARTIFACT_DIR:-}
  local tag=${REVIEW_COUNCIL_TEST_ARTIFACT_TAG:-} destination test_root=$T
  [ -n "$base" ] || return 0
  [ -n "$tag" ] || { echo "artifact tag is required when retention is enabled" >&2; return 1; }
  destination="$base/$tag/$name"
  [ ! -e "$destination" ] || { echo "artifact destination already exists: $destination" >&2; return 1; }
  mkdir -p "$destination" || return
  destination=$(cd "$destination" && pwd -P) || return
  mv "$test_root" "$destination/test-root" \
    && ln -s "$destination/test-root" "$test_root.preserved-link" \
    && mv "$test_root.preserved-link" "$test_root"
}

sonnet_21_windows_fit_and_are_read_audited() {
  ( local pair R S status manifest prompt
    pair=$(sonnet_window_fixture 21 positive) || return
    R=${pair%%$'\n'*}; S=${pair#*$'\n'}
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=0 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" sonnet21 --phase discovery \
      > "$T/sonnet-21-prepare.out" 2> "$T/sonnet-21-prepare.err"
    status=$?
    if [ "$status" -ne 0 ]; then
      cat "$T/sonnet-21-prepare.out" "$T/sonnet-21-prepare.err" >&2
    fi
    assert_eq "a full-state Sonnet assignment retains exactly 21 mandatory windows" "$status" 0
    [ "$status" -eq 0 ] || return 0
    manifest="$S/rsonnet21-evidence.manifest.json"
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" sonnet21 sonnet simplicity proof-budget \
      --evidence "$manifest") || return
    python3 - "$manifest" "$R" "$S/rsonnet21-sonnet.stream.ndjson" \
      "$SCRIPTS/rev-evidence.py" "$SCRIPTS/lib/review_limits.py" <<'PY'
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
manifest_path, root_path, stream_path, evidence_path, limits_path = map(Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text())
root = root_path.resolve()
session = manifest_path.parent
assignment = manifest['assignments']['sonnet']
capacity = manifest['task_capacity']['seats']['sonnet']
rows = capacity['mandatory_window_rows']
expected = [f'tests/test_{index:02d}.py' for index in range(21)]
assert assignment['full_state'] is True, assignment
assert assignment['model'] == 'sonnet', assignment
assert capacity['mandatory_repository_reads'] == 21, capacity
assert capacity['repository_expansion_call_limit'] == 25, capacity
assert capacity['repository_refutation_call_reserve'] == 4, capacity
assert capacity['mandatory_repository_read_limit'] == 21, capacity
context = manifest['source_context']['seats']['sonnet']
assert context['source_read_required'] is True, context
assert capacity['repository_source_target'] is None, capacity
limits_spec = importlib.util.spec_from_file_location('sonnet_window_limits', limits_path)
limits = importlib.util.module_from_spec(limits_spec)
limits_spec.loader.exec_module(limits)
target = {'path': 'tests/test_00.py'}
assert limits.repository_expansion_call_limit_for_seat(True, None, 'sonnet', True) == 25
assert limits.mandatory_repository_read_limit_for_seat(True, None, 'sonnet', True) == 21
assert limits.repository_expansion_call_limit_for_seat(True, None, 'sonnet') == 20
assert limits.mandatory_repository_read_limit_for_seat(True, None, 'sonnet') == 16
assert limits.repository_refutation_call_reserve_for_model('sonnet') == 4
assert limits.repository_expansion_call_limit_for_seat(True, target, 'sonnet') == 16
assert limits.mandatory_repository_read_limit_for_seat(True, target, 'sonnet') == 12
assert limits.repository_expansion_call_limit_for_seat(True, None, 'gpt-6-sol') == 20
assert limits.mandatory_repository_read_limit_for_seat(True, None, 'gpt-6-sol') == 16
assert [row['path'] for row in rows] == expected, rows
assert all(row['line_start'] == 2 and row['line_end'] == 2 for row in rows), rows
spec = importlib.util.spec_from_file_location('sonnet_window_evidence', evidence_path)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
repository = evidence.Repository(session.resolve())
entries = repository.entries(manifest['snapshot_tree'])
events = []
def read(identity, path, output, offset=None, limit=None):
    tool_input = {'file_path': str(path)}
    if offset is not None:
        tool_input.update(offset=offset, limit=limit)
    events.extend([
        {'type': 'assistant', 'message': {'content': [{
            'type': 'tool_use', 'id': identity, 'name': 'Read', 'input': tool_input}]}},
        {'type': 'user', 'message': {'content': [{
            'type': 'tool_result', 'tool_use_id': identity, 'content': output}]}},
    ])
if assignment['patch_read_mode'] == 'chunks':
    for chunk in manifest['patch_sets'][assignment['patch_set']]['chunks']:
        artifact = session / chunk['artifact']
        read('patch-' + str(chunk['index']), artifact, artifact.read_text())
else:
    patch = Path(assignment['patch'])
    patch_lines = patch.read_text().splitlines(keepends=True)
    for first in range(1, len(patch_lines) + 1, 240):
        last = min(len(patch_lines), first + 239)
        read('patch-' + str(first), patch, ''.join(patch_lines[first - 1:last]),
             first, last - first + 1)
context = manifest['source_context']['seats']['sonnet']
for index, shard in enumerate(context['shards'], 1):
    artifact = session / shard['artifact']
    read('packet-' + str(index), artifact, artifact.read_text())
for index, required in enumerate(context['required_source_ranges'], 1):
    for segment in required['segments']:
        artifact = session / segment['artifact']
        read(f'segment-{index}-{segment["index"]}', artifact, artifact.read_text())
index_path = session / 'rsonnet21-evidence.md'
read('evidence-index', index_path, index_path.read_text())
for number, row in enumerate(rows):
    path = row['path']
    entry = entries[path]
    blob = repository.blob(entry)
    lines = evidence.split_lf_lines(blob)
    first, last = row['line_start'], row['line_end']
    content = b''.join(lines[first - 1:last]).decode()
    on_disk = (root / path).read_bytes()
    assert hashlib.sha256(blob).digest() == hashlib.sha256(on_disk).digest(), path
    read('window-' + str(number), root / path, content, first, last - first + 1)
stream_path.write_text(''.join(json.dumps(event) + '\n' for event in events))
Path(str(stream_path).replace('.stream.ndjson', '.json')).write_text(
    '{"summary":"checked","findings":[]}\n')
PY
    assert_eq "the audit transcript contains the exact full-scope window order and snapshot content" "$?" 0
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/rsonnet21-sonnet.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/rsonnet21-sonnet.read-audit.json" > "$T/sonnet-21-audit.out" 2> "$T/sonnet-21-audit.err"
    assert_eq "the Claude read audit accepts the 21-window transcript" "$?" 0
    python3 - "$S/rsonnet21-sonnet.read-audit.json" <<'PY'
import json
import sys
audit = json.load(open(sys.argv[1]))
assert audit['status'] == 'valid', audit
assert not audit['violations'], audit
for index in range(21):
    path = f'tests/test_{index:02d}.py'
    assert any(row['path'] == path and row['line_start'] <= 2 <= row['line_end']
               for row in audit['source_ranges']), (path, audit['source_ranges'])
PY
    assert_eq "the read audit credits every one of the 21 scoped windows" "$?" 0
    sonnet_preserve_window_artifacts sonnet21
    assert_eq "the full manifest, prompt, transcript, source and audit are retained" "$?" 0
    sonnet_partial_21_windows_are_refused
  )
}

sonnet_partial_21_windows_are_refused() {
  ( local pair R S status
    pair=$(sonnet_window_fixture 21 partial) || return
    R=${pair%%$'\n'*}; S=${pair#*$'\n'}
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex","model":"gpt-6-sol","effort":"high","extra":false},{"seat":"sonnet","adapter":"claude","model":"sonnet","effort":"high","extra":false}]}' \
      > "$S/roster.json"
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=0 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" sonnetpartial --phase discovery \
      > "$T/sonnet-partial-prepare.out" 2> "$T/sonnet-partial-prepare.err"
    status=$?
    if [ "$status" -ne 2 ]; then
      cat "$T/sonnet-partial-prepare.out" "$T/sonnet-partial-prepare.err" >&2
    fi
    assert_eq "a partial Sonnet assignment with 21 source windows is refused" "$status" 2
    [ "$status" -eq 2 ] || return 0
    assert_grep "the partial assignment is held to Sonnet's standard mandatory read limit" \
      "$T/sonnet-partial-prepare.err" 'proof reads exceed repository capacity: sonnet limit=16 count=21'
    python3 - "$S" <<'PY'
import json
import sys
from pathlib import Path
diagnostic = json.loads((Path(sys.argv[1]) / 'prepare-diagnostic-sonnetpartial.json').read_text())
row = next(item for item in diagnostic['refusals'] if item['seat'] == 'sonnet')
expected = [f'tests/test_{index:02d}.py' for index in range(21)]
assert row['limit'] == 16 and row['count'] == 21, row
assert [window['path'] for window in row['windows']] == expected, row
PY
    assert_eq "the partial-seat refusal preserves its exact 21 ordered source windows" "$?" 0
    sonnet_preserve_window_artifacts sonnetpartial
    assert_eq "the complete partial-seat refusal diagnostic and source are retained" "$?" 0
  )
}

sonnet_22_windows_are_refused() {
  ( local pair R S status
    pair=$(sonnet_window_fixture 22 over-budget) || return
    R=${pair%%$'\n'*}; S=${pair#*$'\n'}
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=0 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" sonnet22 --phase discovery \
      > "$T/sonnet-22-prepare.out" 2> "$T/sonnet-22-prepare.err"
    status=$?
    if [ "$status" -ne 2 ]; then
      cat "$T/sonnet-22-prepare.out" "$T/sonnet-22-prepare.err" >&2
    fi
    assert_eq "a Sonnet assignment over the 21-window limit is refused before launch" "$status" 2
    [ "$status" -eq 2 ] || return 0
    assert_grep "the refusal names the current Sonnet limit and 22-window count" \
      "$T/sonnet-22-prepare.err" 'proof reads exceed repository capacity: sonnet limit=[0-9]+ count=22'
    python3 - "$S" "$SCRIPTS/lib/review_limits.py" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path
session, limits_path = Path(sys.argv[1]), Path(sys.argv[2])
diagnostic = json.loads((session / 'prepare-diagnostic-sonnet22.json').read_text())
row = next(item for item in diagnostic['refusals'] if item['seat'] == 'sonnet')
expected = [f'tests/test_{index:02d}.py' for index in range(22)]
spec = importlib.util.spec_from_file_location('sonnet_window_limits', limits_path)
limits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(limits)
expected_limit = limits.mandatory_repository_read_limit_for_seat(True, None, 'sonnet')
assert row['limit'] == expected_limit and row['count'] == 22, row
assert [window['path'] for window in row['windows']] == expected, row
assert all(1 <= partition['reads'] <= row['limit'] for partition in row['partitions']), row
PY
    assert_eq "the refusal preserves all 22 ordered proof windows" "$?" 0
    sonnet_preserve_window_artifacts sonnet22
    assert_eq "the complete 22-window refusal diagnostic and source are retained" "$?" 0
  )
}
