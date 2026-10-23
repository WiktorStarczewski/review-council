#!/bin/bash
# Code scopes must fit the frozen post-index proof budget before a panel launches.
# The first run of this test is expected to fail while preparation still accepts
# a change whose omitted consumers do not fit that budget.

test_code_proof_budget_refuses_before_launch() {
  ( local R="$T/proof-budget-root" S="$T/proof-budget-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
functions = []
for index in range(13):
    body = 'x' * 10000
    functions.append(f'def fn{index:02d}():\n    return "{body}"\n')
    call = 'y' * 8000
    (root / 'src' / f'use{index:02d}.py').write_text(
        f'def use{index:02d}():\n    return fn{index:02d}("{call}")\n')
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
    if [ "$status" -ne 2 ]; then
      echo "---- prepare stdout ----" >&2
      cat "$T/proof-budget.out" >&2
      echo "---- prepare stderr ----" >&2
      cat "$T/proof-budget.err" >&2
    fi
    assert_eq "thirteen omitted consumers are refused before launch" "$status" 2
    [ "$status" -eq 2 ] || return 0
    assert_grep "the refusal names the frozen proof budget" \
      "$T/proof-budget.err" 'proof reads exceed repository capacity: sol limit=12 count='
    assert_grep "preparation names the capacity stage" \
      "$T/proof-budget.err" 'evidence: stage capacity'
    assert_eq "a refused code prepare publishes no manifest" \
      "$(find "$S" -maxdepth 1 -name 'rproof-evidence.manifest.json' | wc -l | tr -d ' ')" 0
    python3 - "$S" <<'PY'
import json, sys
from pathlib import Path
diagnostic = json.loads((Path(sys.argv[1]) / 'prepare-diagnostic-proof.json').read_text())
assert diagnostic['schema_version'] == 1
assert diagnostic['kind'] == 'prepare-diagnostic'
assert diagnostic['certifying'] is False
assert diagnostic['label'] == 'proof' and diagnostic['phase'] == 'discovery'
assert diagnostic['timed_out'] is False
assert diagnostic['error'].startswith('proof reads exceed repository capacity:')
assert 'partitions=' in diagnostic['error']
row = next(item for item in diagnostic['refusals'] if item['seat'] == 'sol')
assert row['limit'] == 12 and row['count'] > 12, row
assert row['partitions']
assert sum(partition['reads'] for partition in row['partitions']) == row['count']
assert all(1 <= partition['reads'] <= 12 and partition['paths'] for partition in row['partitions'])
assert all('src/lib.py' in partition['paths'] for partition in row['partitions'])
window_keys = {(item['path'], item['line_start'], item['line_end']) for item in row['windows']}
partition_keys = {(item['path'], item['line_start'], item['line_end'])
                  for partition in row['partitions'] for item in partition['windows']}
assert window_keys == partition_keys, (window_keys, partition_keys)
PY
    assert_eq "partition guidance fits the frozen budget and covers the changed file" "$?" 0
    python3 "$SCRIPTS/rev-evidence.py" verify "$S/prepare-diagnostic-proof.json" \
      > "$T/proof-budget-verify.out" 2> "$T/proof-budget-verify.err"
    assert_eq "verify does not certify a proof-budget diagnostic" "$?" 2
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
