# tests for Task 3 - sourced by run-tests.sh
# NB: the bodies run in the RUNNER's shell, not a subshell, so ok()/fail()'s PASS/FAIL increments
# survive; seat_env's exports are undone at the end so later tests see a clean environment.
seat_timeout() {  # seat_timeout <secs> <cmd...> - hard cap, so a runaway seat cannot hang the suite
  local lim=$(( $1 * 10 )); shift
  "$@" >/dev/null 2>&1 &
  local pid=$! i=0
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt "$lim" ]; do sleep 0.1; i=$((i+1)); done
  if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124; fi
  wait "$pid"; return $?
}
seat_env_reset() { PATH="$1"; unset SHIM_FIXTURE_DIR SHIM_ARGS_FILE SHIM_ARGS_DIR SHIM_CALLS_FILE SHIM_CHILD_PID_FILE SHIM_STAGE_DIR SHIM_EVIDENCE_INDEX SHIM_UNPREPARED_TARGET REV_REPO SHIM_MODE; }
seat_roster() {  # seat_roster <session-dir> - the roster.json rev-preflight.sh leaves in the session dir.
  # Written by hand on purpose: these tests exercise rev-seat.sh's dispatch, not roster.sh's detection.
  mkdir -p "$1"
  cat > "$1/roster.json" <<'JSON'
{ "generated_at": "2026-09-02T00:00:00Z",
  "seats": [
    { "seat": "codex-sol",        "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",    "effort": "max",   "extra": false },
    { "seat": "codex-terra",      "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-terra",  "effort": "xhigh", "extra": false },
    { "seat": "gemini",           "lab": "google",    "adapter": "gemini", "model": "gemini-2.5-pro", "effort": null,    "extra": false },
    { "seat": "opus",             "lab": "anthropic", "adapter": "agent",  "model": "opus",           "effort": "max",   "extra": false },
    { "seat": "codex-review",     "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",    "effort": "max",   "mode": "review",      "extra": true, "round": 2 }
  ],
  "excluded": [] }
JSON
}
test_seat_rejects_retired_grok_adapter() {
  local _path="$PATH"; seat_env
  local S="$T/seat-retired-grok"; mkdir -p "$S"; echo "review the diff" > "$S/p.md"
  cat > "$S/roster.json" <<'JSON'
{"seats":[{"seat":"grok","lab":"xai","adapter":"grok","model":"grok-4.6","effort":"xhigh","extra":false}]}
JSON
  assert_exit "a forged retired Grok seat cannot launch" 1 \
    env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok "$S" 1 "$S/p.md"
  assert_exit "the live Grok adapter script is absent" 1 test -e "$SCRIPTS/seats.d/grok.sh"
  seat_env_reset "$_path"
}
test_seat_codex_instructions_required() {
  ( seat_env
    local COPY="$T/instruction-plugin" S="$T/instruction-seat" variant
    copy_writable_tree "$SK" "$COPY"
    mkdir -p "$S"
    printf 'review\n' > "$S/p.md"
    for variant in empty missing; do
      : > "$COPY/scripts/lib/reviewer-instructions.md"
      [ "$variant" != missing ] || rm "$COPY/scripts/lib/reviewer-instructions.md"
      : > "$T/instruction-calls"
      SEAT=codex-sol MODEL=fixture EFFORT=xhigh MODE=prompt ROOT="$T" \
        PROMPT="$S/p.md" SCHEMA="$COPY/schema/findings.schema.json" OUT="$S/result.json" \
        LOG="$S/adapter.log" RAW="$S/raw.jsonl" BASE=abc \
        SHIM_CALLS_FILE="$T/instruction-calls" bash "$COPY/scripts/seats.d/codex.sh" \
        > "$S/out" 2> "$S/err"
      assert_eq "$variant reviewer instructions refuse launch" "$?" 1
      assert_eq "$variant instructions spend zero CLI calls" "$(wc -l < "$T/instruction-calls" | tr -d ' ')" 0
      assert_grep "$variant instructions name the local failure" "$S/err" 'missing reviewer instructions'
    done
  )
}

test_seat_codex_stages_prepared_evidence() {
  local _path="$PATH"; seat_env
  local S="$T/seat-codex-stages" calls
  mkdir -p "$S/calls"
  : > "$S/calls.log"
  python3 - "$S" <<'PY'
import hashlib
import json
import shlex
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
repository_root = root.parent
target_source = b'line\n'
(repository_root / 'src').mkdir(exist_ok=True)
(repository_root / 'src/three.ts').write_bytes(target_source)
target_sha256 = hashlib.sha256(target_source).hexdigest()
contents = {
    'r1-full.patch': b'patch one\npatch two\n',
    'r1-patch-p01-001.txt': b'patch one\n',
    'r1-patch-p01-002.txt': b'patch two\n',
    'r1-codex-luna-source-context-1.json': b'{"packet":1}\n',
    'r1-codex-luna-source-context-2.json': b'{"packet":2}\n',
    'r1-codex-luna-source-segment-001-001.txt': b'segment one\n',
    'r1-codex-luna-source-segment-001-002.txt': b'x' * (16 * 1024),
    'r1-codex-luna-source-segment-002-001.txt': b'segment three\n',
    'r1-evidence.md': b'evidence index\n',
}
for name, content in contents.items():
    (root / name).write_bytes(content)

def digest(name):
    return hashlib.sha256(contents[name]).hexdigest()

def segment(label, name):
    size = len(contents[name])
    path = root / name
    command = shlex.join(['cat', '--', str(path)])
    visible = size + 8
    return (f'Required source segment {label}: run {command} raw bytes {size} '
            f'visible bytes {visible} content SHA-256 {digest(name)}')

lines = [
    'Review this prepared assignment after all listed evidence is read.',
    'use at most 4 repository tool calls before stopping this assignment.',
    'Required post-index original-source target: src/three.ts:1-1 tree '
    + 'a' * 40 + ' blob ' + 'b' * 40 + ' content SHA-256 '
    + target_sha256 + ' reasons []',
    f'Canonical assigned patch: {root}/r1-full.patch SHA-256 {digest("r1-full.patch")} bytes {len(contents["r1-full.patch"])}',
    'Patch chunk batch limit: 2',
]
for index, name in enumerate(('r1-patch-p01-001.txt', 'r1-patch-p01-002.txt'), 1):
    size = len(contents[name])
    start = 0 if index == 1 else len(contents['r1-patch-p01-001.txt'])
    lines.append(f'Assigned patch chunk {index}/2: {root}/{name} bytes {start}-{start + size} SHA-256 {digest(name)}')
lines.extend([
    'Source context packet batch limit: 1',
    f'Source context packet: {root}/r1-codex-luna-source-context-1.json',
    f'Source context packet: {root}/r1-codex-luna-source-context-2.json',
    segment('1/2', 'r1-codex-luna-source-segment-001-001.txt'),
    segment('2/2', 'r1-codex-luna-source-segment-001-002.txt'),
    'Required source segment batch limit: 2',
    segment('1/1', 'r1-codex-luna-source-segment-002-001.txt'),
    'Required source segment batch limit: 2',
    f'Evidence navigation index: {root}/r1-evidence.md',
])
artifacts = {
    name: {'sha256': digest(name), 'words': len(contents[name].split())}
    for name in contents
}
manifest = {
    'schema_version': 2,
    'label': '1',
    'session': str(root.resolve()),
    'artifacts': artifacts,
    'assignments': {
        'codex-luna': {
            'adapter': 'codex', 'model': 'gpt-6.1-luna',
            'patch': str(root / 'r1-full.patch'),
            'patch_sha256': digest('r1-full.patch'),
            'patch_bytes': len(contents['r1-full.patch']), 'patch_lines': 2,
            'patch_read_mode': 'chunks', 'patch_set': 'p01',
        },
    },
    'patch_sets': {
        'p01': {
            'read_mode': 'chunks', 'patch_sha256': digest('r1-full.patch'),
            'patch_bytes': len(contents['r1-full.patch']), 'patch_lines': 2,
            'chunks': [
                {'artifact': 'r1-patch-p01-001.txt', 'index': 1,
                 'byte_start': 0, 'byte_end': len(contents['r1-patch-p01-001.txt']),
                 'bytes': len(contents['r1-patch-p01-001.txt']),
                 'sha256': digest('r1-patch-p01-001.txt'),
                 'predicted_visible_bytes': len(contents['r1-patch-p01-001.txt'])},
                {'artifact': 'r1-patch-p01-002.txt', 'index': 2,
                 'byte_start': len(contents['r1-patch-p01-001.txt']),
                 'byte_end': len(contents['r1-full.patch']),
                 'bytes': len(contents['r1-patch-p01-002.txt']),
                 'sha256': digest('r1-patch-p01-002.txt'),
                 'predicted_visible_bytes': len(contents['r1-patch-p01-002.txt'])},
            ],
        },
    },
    'source_context': {
        'packet_batch_limit': 1,
        'seats': {
            'codex-luna': {
                'shards': [
                    {'artifact': 'r1-codex-luna-source-context-1.json',
                     'bytes': len(contents['r1-codex-luna-source-context-1.json'])},
                    {'artifact': 'r1-codex-luna-source-context-2.json',
                     'bytes': len(contents['r1-codex-luna-source-context-2.json'])},
                ],
                'required_source_ranges': [
                    {'segments': [
                        {'artifact': 'r1-codex-luna-source-segment-001-001.txt',
                         'index': 1, 'line_start': 1, 'line_end': 1,
                         'raw_bytes': len(contents['r1-codex-luna-source-segment-001-001.txt']),
                         'predicted_visible_bytes': len(contents['r1-codex-luna-source-segment-001-001.txt']) + 8,
                         'content_sha256': digest('r1-codex-luna-source-segment-001-001.txt')},
                        {'artifact': 'r1-codex-luna-source-segment-001-002.txt',
                         'index': 2, 'line_start': 2, 'line_end': 2,
                         'raw_bytes': len(contents['r1-codex-luna-source-segment-001-002.txt']),
                         'predicted_visible_bytes': len(contents['r1-codex-luna-source-segment-001-002.txt']) + 8,
                         'content_sha256': digest('r1-codex-luna-source-segment-001-002.txt')},
                    ]},
                    {'segments': [
                        {'artifact': 'r1-codex-luna-source-segment-002-001.txt',
                         'index': 1, 'line_start': 1, 'line_end': 1,
                         'raw_bytes': len(contents['r1-codex-luna-source-segment-002-001.txt']),
                         'predicted_visible_bytes': len(contents['r1-codex-luna-source-segment-002-001.txt']) + 8,
                         'content_sha256': digest('r1-codex-luna-source-segment-002-001.txt')},
                    ]},
                ],
            },
        },
    },
}
manifest_raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode() + b'\n'
(root / 'r1-evidence.manifest.json').write_bytes(manifest_raw)
lines[0:0] = [f'Evidence manifest SHA-256: {hashlib.sha256(manifest_raw).hexdigest()}']
(root / 'r1-codex-luna.prompt.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
PY
  SHIM_MODE=staged SHIM_ARGS_FILE="$S/last-args" SHIM_STAGE_DIR="$S/calls" \
    SHIM_CALLS_FILE="$S/calls.log" SEAT=codex-luna MODEL=gpt-6.1-luna EFFORT=xhigh \
    MODE=prompt ROOT="$T" PROMPT="$S/r1-codex-luna.prompt.md" SCHEMA="$SHIM_FIXTURE_DIR/findings.schema.json" \
    OUT="$S/result.json" LOG="$S/adapter.log" RAW="$S/raw.ndjson" BASE=abc \
    bash "$SCRIPTS/seats.d/codex.sh" > "$S/out" 2> "$S/err"
  local adapter_rc=$?
  if [ "$adapter_rc" -ne 0 ]; then
    printf 'staged Codex adapter stderr:\n' >&2
    sed -n '1,40p' "$S/err" >&2
    printf 'staged Codex adapter stdout:\n' >&2
    sed -n '1,40p' "$S/out" >&2
    printf 'staged Codex adapter log:\n' >&2
    sed -n '1,40p' "$S/adapter.log" >&2
  fi
  assert_eq "staged Codex proof exits successfully" "$adapter_rc" 0
  calls=$(wc -l < "$S/calls.log" | tr -d ' ')
  assert_eq "Codex uses separate resumable turns for prepared proof, source review, and findings" "$calls" 13
  if [ "$calls" = 13 ]; then
    python3 - "$S" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected = [
    ['r1-patch-p01-001.txt', 'r1-patch-p01-002.txt'],
    ['r1-codex-luna-source-context-1.json'],
    ['r1-codex-luna-source-context-2.json'],
    ['r1-codex-luna-source-segment-001-001.txt'],
    ['r1-codex-luna-source-segment-001-002.txt'],
    ['r1-codex-luna-source-segment-002-001.txt'],
    ['r1-evidence.md'],
]
for index, names in enumerate(expected, 1):
    prompt = (root / 'calls' / f'call-{index}.stdin').read_text(encoding='utf-8')
    actual = [line.removeprefix('Read exactly: cat -- ')
              for line in prompt.splitlines() if line.startswith('Read exactly: cat -- ')]
    wanted = [str(root / name) for name in names]
    assert actual == wanted, (index, actual, wanted)
    args = (root / 'calls' / f'call-{index}.args').read_text(encoding='utf-8').splitlines()
    assert '--ephemeral' not in args, (index, args)
    assert '--output-schema' not in args, (index, args)
    assert 'read-only' in args, (index, args)
    if index == 1:
        assert args[0] == 'exec' and str(root.parent) in args, args
    else:
        assert args[0] == 'exec' and args[1] == 'resume', args
        assert 'fixture-thread' in args, args
        assert 'sandbox_mode="read-only"' in args, args

first_review_args = (root / 'calls' / 'call-8.args').read_text(encoding='utf-8').splitlines()
first_review_prompt = (root / 'calls' / 'call-8.stdin').read_text(encoding='utf-8')
next_review_args = (root / 'calls' / 'call-9.args').read_text(encoding='utf-8').splitlines()
next_review_prompt = (root / 'calls' / 'call-9.stdin').read_text(encoding='utf-8')
required_review_args = (root / 'calls' / 'call-10.args').read_text(encoding='utf-8').splitlines()
ready_review_args = (root / 'calls' / 'call-12.args').read_text(encoding='utf-8').splitlines()
final_args = (root / 'calls' / 'call-13.args').read_text(encoding='utf-8').splitlines()
final_prompt = (root / 'calls' / 'call-13.stdin').read_text(encoding='utf-8')
for args in (first_review_args, next_review_args, required_review_args, ready_review_args, final_args):
    assert args[0:2] == ['exec', 'resume'], args
    assert 'fixture-thread' in args, args
    assert 'sandbox_mode="read-only"' in args, args
assert '--output-schema' in first_review_args and 'review-turn.schema.json' in first_review_args, first_review_args
assert '--output-schema' in next_review_args and 'review-turn.schema.json' in next_review_args, next_review_args
assert '--output-schema' in required_review_args and 'review-turn.schema.json' in required_review_args, required_review_args
assert '--output-schema' in ready_review_args and 'review-turn.schema.json' in ready_review_args, ready_review_args
assert '--output-schema' in final_args and 'findings.schema.json' in final_args, final_args
assert 'Review this prepared assignment' in first_review_prompt, first_review_prompt
assert 'already been read in earlier explicit turns' in first_review_prompt, first_review_prompt
assert 'Next evidence question:' in next_review_prompt and 'src/two.ts' in next_review_prompt, next_review_prompt
required_review_prompt = (root / 'calls' / 'call-10.stdin').read_text(encoding='utf-8')
assert 'Next evidence question:' in required_review_prompt and 'src/three.ts' in required_review_prompt, required_review_prompt
assert 'Return the final findings JSON' in final_prompt, final_prompt

events = [json.loads(line) for line in (root / 'raw.ndjson').read_text().splitlines()]
assert sum(event.get('type') == 'turn.started' for event in events) == 13
assert sum(event.get('type') == 'turn.completed' for event in events) == 13
threads = [event.get('thread_id') for event in events if event.get('type') == 'thread.started']
assert threads and set(threads) == {'fixture-thread'}, threads
assert sum(event.get('type') == 'item.started'
           and event.get('item', {}).get('type') == 'command_execution' for event in events) == 12
PY
    assert_eq "proof artifacts are staged in order with the final schema only on resume" "$?" 0
    assert_grep "staging keeps the exact findings output" "$S/result.json" '"findings": ?\['
  fi
  seat_env_reset "$_path"
}

test_seat_codex_resumes_unprepared_reviews() {
  local _path="$PATH"; seat_env
  local S="$T/seat-codex-unprepared" W="$T/seat-codex-unprepared-wrong" calls
  mkdir -p "$S" "$W" "$T/src"
  : > "$S/calls.log"
  printf 'first source\n' > "$T/src/first.ts"
  printf 'required source\n' > "$T/src/required.ts"
  printf 'evidence index\n' > "$S/r1-evidence.md"
  python3 - "$S" <<'PY'
import hashlib
import sys
from pathlib import Path

session = Path(sys.argv[1]).resolve()
target = b'required source\n'
prompt = (session / 'review.prompt.md')
prompt.write_text(
    'Review this unprepared assignment.\n'
    'use at most 4 repository tool calls before stopping this assignment.\n'
    f'Evidence navigation index: {session / "r1-evidence.md"}\n'
    'Required post-index original-source target: src/required.ts:1-1 tree '
    + 'a' * 40 + ' blob ' + 'b' * 40 + ' content SHA-256 '
    + hashlib.sha256(target).hexdigest() + ' reasons []\n', encoding='utf-8')
PY
  assert_eq "no-manifest target fixture is constructed" "$?" 0
  SHIM_MODE=resumable-no-manifest SHIM_EVIDENCE_INDEX="$S/r1-evidence.md" \
    SHIM_CALLS_FILE="$S/calls.log" SHIM_STAGE_DIR="$S/calls" \
    SEAT=codex-luna MODEL=gpt-6.1-luna EFFORT=xhigh MODE=prompt ROOT="$T" \
    PROMPT="$S/review.prompt.md" SCHEMA="$SHIM_FIXTURE_DIR/findings.schema.json" \
    OUT="$S/result.json" LOG="$S/adapter.log" RAW="$S/raw.ndjson" BASE=abc \
    bash "$SCRIPTS/seats.d/codex.sh" > "$S/out" 2> "$S/err"
  local adapter_rc=$?
  assert_eq "no-manifest Codex review exits successfully" "$adapter_rc" 0
  calls=$(wc -l < "$S/calls.log" | tr -d ' ')
  assert_eq "no-manifest Codex review uses bounded resumable turns" "$calls" 3
  assert_grep "no-manifest review starts with the review-turn schema" \
    "$S/calls/call-1.args" 'review-turn\.schema\.json'
  assert_nogrep "no-manifest review avoids one-shot ephemeral execution" \
    "$S/calls/call-1.args" '^--ephemeral$'
  if [ "$calls" = 3 ]; then
    python3 - "$S" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
first_args = (root / 'calls' / 'call-1.args').read_text().splitlines()
first_prompt = (root / 'calls' / 'call-1.stdin').read_text()
next_args = (root / 'calls' / 'call-2.args').read_text().splitlines()
next_prompt = (root / 'calls' / 'call-2.stdin').read_text()
final_args = (root / 'calls' / 'call-3.args').read_text().splitlines()
final_prompt = (root / 'calls' / 'call-3.stdin').read_text()
assert first_args[0] == 'exec' and 'resume' not in first_args, first_args
assert '--output-schema' in first_args and 'review-turn.schema.json' in first_args, first_args
assert first_args[first_args.index('-s') + 1] == 'read-only', first_args
assert first_args[first_args.index('-C') + 1] == str(root.parent), first_args
assert next_args[:2] == ['exec', 'resume'] and 'fixture-thread' in next_args, next_args
assert '--output-schema' in next_args and 'review-turn.schema.json' in next_args, next_args
assert final_args[:2] == ['exec', 'resume'] and 'fixture-thread' in final_args, final_args
assert '--output-schema' in final_args and 'findings.schema.json' in final_args, final_args
for args in (first_args, next_args, final_args):
    assert '--ephemeral' not in args, args
assert 'sandbox_mode="read-only"' in next_args, next_args
assert 'sandbox_mode="read-only"' in final_args, final_args
assert 'Review this unprepared assignment.' in first_prompt, first_prompt
assert 'Evidence navigation index:' in first_prompt, first_prompt
assert 'no prepared evidence was read in an earlier turn' in first_prompt, first_prompt
assert 'already been read in earlier explicit turns' not in first_prompt, first_prompt
assert 'Next evidence question:' in next_prompt and 'src/required.ts:1-1' in next_prompt, next_prompt
assert 'Return the final findings JSON' in final_prompt, final_prompt
events = [json.loads(line) for line in (root / 'raw.ndjson').read_text().splitlines()]
assert sum(event.get('type') == 'turn.started' for event in events) == 3
assert sum(event.get('type') == 'turn.completed' for event in events) == 3
assert sum(event.get('type') == 'item.started'
           and event.get('item', {}).get('type') == 'command_execution' for event in events) == 2
PY
    assert_eq "no-manifest review preserves source checks and finalizes tool-free" "$?" 0
  fi
  assert_grep "no-manifest review keeps findings schema" "$S/result.json" '"findings": ?\['

  : > "$W/calls.log"
  cp "$S/r1-evidence.md" "$W/r1-evidence.md"
  sed "s|$S/r1-evidence.md|$W/r1-evidence.md|" "$S/review.prompt.md" > "$W/review.prompt.md"
  SHIM_MODE=resumable-no-manifest SHIM_UNPREPARED_TARGET=wrong \
    SHIM_EVIDENCE_INDEX="$W/r1-evidence.md" SHIM_CALLS_FILE="$W/calls.log" \
    SHIM_STAGE_DIR="$W/calls" SEAT=codex-luna MODEL=gpt-6.1-luna EFFORT=xhigh \
    MODE=prompt ROOT="$T" PROMPT="$W/review.prompt.md" \
    SCHEMA="$SHIM_FIXTURE_DIR/findings.schema.json" OUT="$W/result.json" \
    LOG="$W/adapter.log" RAW="$W/raw.ndjson" BASE=abc \
    bash "$SCRIPTS/seats.d/codex.sh" > "$W/out" 2> "$W/err"
  assert_eq "unrelated repository reads do not satisfy the required target" "$?" 0
  calls=$(wc -l < "$W/calls.log" | tr -d ' ')
  assert_eq "wrong target triggers one more bounded review turn" "$calls" 4
  if [ "$calls" = 4 ]; then
    python3 - "$W" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
required_turn = (root / 'calls' / 'call-3.stdin').read_text(encoding='utf-8')
assert 'Next evidence question:' in required_turn, required_turn
assert 'exact required original-source target' in required_turn, required_turn
assert 'src/required.ts:1-1' in required_turn, required_turn
PY
    assert_eq "adapter names the exact unmet target after an unrelated read" "$?" 0
  fi
  seat_env_reset "$_path"
}

test_seat_codex() {
  local _path="$PATH"; seat_env
  local S="$T/seat-codex"; seat_roster "$S"; echo "review the diff" > "$S/p.md"; : > "$T/args.env"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" > "$T/out.txt"; local rc=$?
  assert_eq "codex ok exit" "$rc" 0
  assert_grep "prints summary line" "$T/out.txt" '^seat=codex-sol round=1 exit=0 findings=1$'
  assert_grep "writes .exit" "$S/r1-codex-sol.exit" '^0$'
  assert_grep "json copied" "$S/r1-codex-sol.json" '"severity": ?"P1"'
  assert_grep "log has exec line" "$S/r1-codex-sol.log" '^exec: .*git diff abc123'
  assert_grep "log has done line" "$S/r1-codex-sol.log" '^done: exit=0'
  assert_grep "prompt via stdin" "$T/args.stdin" 'review the diff'
  assert_grep "model comes from the roster" "$T/args" '^gpt-5.6-sol$'
  assert_grep "effort comes from the roster" "$T/args" '^model_reasoning_effort=max$'
  assert_grep "prompt review uses compact reviewer instructions" "$T/args" '^model_instructions_file=.*scripts/lib/reviewer-instructions.md$'
  # the seat's environment is not visible in argv: REV_ACTIVE is the recursion guard, -C is the repo root
  assert_grep "seat carries REV_ACTIVE=1" "$T/args.env" '^REV_ACTIVE=1$'
  assert_nogrep "no seat runs unguarded" "$T/args.env" '^REV_ACTIVE=unset$'
  assert_grep "seat records its cwd" "$T/args.env" '^cwd=/'
  assert_grep "codex gets the repo root with -C" "$T/args" "^$T$"
  assert_grep "read-only sandbox" "$T/args" '^read-only$'
  assert_grep "schema passed" "$T/args" 'findings.schema.json$'
  assert_nogrep "no write flags" "$T/args" 'danger|workspace-write|--approve'
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 2 "$S/p.md" >/dev/null
  assert_grep "terra model from the roster" "$T/args" '^gpt-5.6-terra$'
  assert_grep "terra effort is its own roster entry" "$T/args" '^model_reasoning_effort=xhigh$'
  assert_exit "notauth → 3" 3 env SHIM_MODE=notauth "$SCRIPTS/rev-seat.sh" codex-sol "$S" 3 "$S/p.md"
  assert_exit "ratelimit → 4" 4 env SHIM_MODE=ratelimit "$SCRIPTS/rev-seat.sh" codex-sol "$S" 4 "$S/p.md"
  local classifier_bin="$T/seat-classifier-bin" seat_path=$PATH
  mkdir -p "$classifier_bin"
  cat > "$classifier_bin/codex" <<'SH'
#!/bin/bash
case "${FAILURE_MODE:-}" in
  capacity) printf '%s\n' '{"type":"error","message":"Credit balance is too low; provider capacity exhausted"}' ;;
  prose) printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"the reviewed code says quota exceeded"}}' ;;
esac
exit 1
SH
  chmod +x "$classifier_bin/codex"
  PATH="$classifier_bin:$PATH" FAILURE_MODE=capacity \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 4c "$S/p.md" >/dev/null 2>&1
  assert_eq "provider capacity exhaustion uses the quota exit" "$?" 4
  PATH="$classifier_bin:$PATH" FAILURE_MODE=prose \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 4p "$S/p.md" >/dev/null 2>&1
  assert_eq "quota words in model prose do not use the quota exit" "$?" 2
  PATH=$seat_path
  assert_exit "empty → 2" 2 env SHIM_MODE=empty "$SCRIPTS/rev-seat.sh" codex-sol "$S" 5 "$S/p.md"
  assert_exit "badjson → 2" 2 env SHIM_MODE=badjson "$SCRIPTS/rev-seat.sh" codex-sol "$S" 6 "$S/p.md"
  assert_grep "exit file records 2" "$S/r6-codex-sol.exit" '^2$'
  : > "$T/codex-notools-calls"
  SHIM_MODE=notools SHIM_CALLS_FILE="$T/codex-notools-calls" "$SCRIPTS/rev-seat.sh" codex-sol "$S" 6n "$S/p.md" > "$T/codex-notools.out" 2>&1
  assert_eq "Codex no-tool review exits unusable" "$?" 2
  assert_eq "Codex no-tool review retries once" "$(wc -l < "$T/codex-notools-calls" | tr -d ' ')" 2
  assert_grep "Codex no-tool log explains the rejection" "$S/r6n-codex-sol.log" 'answered without a single tool call \(attempt 2\)'
  assert_exit "codex-review needs --base" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-review "$S" 7 "$S/p.md"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-review "$S" 7 "$S/p.md" --base abc123 >/dev/null
  assert_grep "codex-review uses review subcommand" "$T/args" '^review$'
  assert_grep "codex-review passes base" "$T/args" '^abc123$'
  assert_nogrep "native review keeps its own instructions" "$T/args" '^model_instructions_file='
    assert_nogrep "codex-review passes no sandbox flag (exec review has no -s)" "$T/args" '^(-s|read-only)$'
  assert_exit "seat that is not in the roster → 1" 1 "$SCRIPTS/rev-seat.sh" mystery "$S" 8 "$S/p.md"
  "$SCRIPTS/rev-seat.sh" mystery "$S" 8 "$S/p.md" 2> "$T/noseat.err"
  assert_grep "unknown seat says run preflight first" "$T/noseat.err" 'run preflight first'
  assert_exit "missing prompt → 1" 1 "$SCRIPTS/rev-seat.sh" codex-sol "$S" 9 "$S/nope.md"
  # a session without a roster has not been through preflight: refuse, do not guess a model
  local N="$T/seat-noroster"; mkdir -p "$N"; echo "review" > "$N/p.md"
  assert_exit "no roster → 1" 1 "$SCRIPTS/rev-seat.sh" codex-sol "$N" 1 "$N/p.md"
  "$SCRIPTS/rev-seat.sh" codex-sol "$N" 1 "$N/p.md" 2> "$T/noroster.err"
  assert_grep "missing roster says run preflight first" "$T/noroster.err" 'run preflight first'
  # a roster naming an adapter this plugin has no script for is a broken roster, not a seat to guess at
  local A="$T/seat-badadapter"; mkdir -p "$A"; echo "review" > "$A/p.md"
  cat > "$A/roster.json" <<'JSON'
{ "generated_at": "t", "seats": [ { "seat": "codex-sol", "lab": "openai", "adapter": "nosuchcli", "model": "m", "effort": "max", "extra": false } ], "excluded": [] }
JSON
  assert_exit "roster adapter with no script → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$A" 1 "$A/p.md"
  # a truncated roster must fail like a missing one, not crash with a python traceback for an exit code
  local B="$T/seat-badroster"; mkdir -p "$B"; echo "review" > "$B/p.md"; printf '{ "seats": [ {' > "$B/roster.json"
  assert_exit "unreadable roster → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$B" 1 "$B/p.md"
  env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$B" 1 "$B/p.md" 2> "$T/badroster.err"
  assert_grep "unreadable roster says run preflight first" "$T/badroster.err" 'run preflight first'
  # the agent seat is launched by the skill through the Agent tool - there is no CLI to run here
  assert_exit "agent seat → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$S/p.md"
  "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$S/p.md" 2> "$T/agent.err"
  assert_grep "agent seat explains itself" "$T/agent.err" 'Agent tool'
  # a failed run whose model stream merely quotes a 401 is "no output" (2), not "not signed in" (3)
  assert_exit "quoted 401 in stream → 2, not 3" 2 env SHIM_MODE=noise401 "$SCRIPTS/rev-seat.sh" codex-sol "$S" 10 "$S/p.md"
  assert_grep "the 401 really is in the raw stream" "$S/r10-codex-sol.stream.ndjson" '401 Unauthorized'
  # …and it reaches the LOG too, as the model's own `text:` line - that is exactly the line classify_failure
  # must ignore. Only CLI-originated lines decide sign-in and cap.
  assert_grep "the 401 is in the log as model text" "$S/r10-codex-sol.log" '^text: .*401 Unauthorized'
  assert_nogrep "no CLI-originated 401 line" "$S/r10-codex-sol.log" '^(error|exec|done): .*401'
  # the roster effort is the probed and receipted launch authority; later overrides cannot diverge
  assert_exit "REV_CODEX_EFFORT cannot lower the receipted effort" 1 env \
    REV_CODEX_EFFORT=high SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 11 "$S/p.md"
  assert_exit "--effort cannot raise the receipted effort" 1 env \
    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 12 "$S/p.md" --effort max
  assert_exit "REV_CODEX_EFFORT cannot raise the receipted effort" 1 env \
    REV_CODEX_EFFORT=ultra SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 13 "$S/p.md"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 14 "$S/p.md" --effort xhigh >/dev/null
  assert_grep "an exact matching effort preserves the roster launch" "$T/args" \
    '^model_reasoning_effort=xhigh$'
  # Codex requires the exact effort selected before its availability probe.
  local E="$T/seat-noeffort"; mkdir -p "$E"; echo "review" > "$E/p.md"
  cat > "$E/roster.json" <<'JSON'
{ "generated_at": "t", "seats": [ { "seat": "codex-sol", "lab": "openai", "adapter": "codex", "model": "gpt-5.6-sol", "effort": null, "extra": false } ], "excluded": [] }
JSON
  assert_exit "an effort-less Codex roster entry cannot launch" 1 env \
    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$E" 1 "$E/p.md"

  local C="$T/seat-call-cap"; seat_roster "$C"; echo "review the diff" > "$C/p.md"
  : > "$T/capped-calls"
  local call
  for call in 1 2 3 4; do
    SHIM_MODE=ok SHIM_CALLS_FILE="$T/capped-calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$C" cap "$C/p.md" >/dev/null
    assert_eq "provider call $call stays within the persistent cap" "$?" 0
  done
  printf '%s\n' '{"prior":"audit"}' > "$C/rcap-codex-sol.read-audit.json"
  local artifact
  for artifact in json read-audit.json stream.ndjson; do
    cp "$C/rcap-codex-sol.$artifact" "$C/before-cap.$artifact"
  done
  SHIM_MODE=ok SHIM_CALLS_FILE="$T/capped-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$C" cap "$C/p.md" >/dev/null 2>&1
  assert_eq "fifth provider call is rejected before launch" "$?" 7
  assert_eq "persistent cap permits exactly four provider processes" \
    "$(wc -l < "$T/capped-calls" | tr -d ' ')" 4
  for artifact in json read-audit.json stream.ndjson; do
    assert_exit "cap refusal preserves prior $artifact" 0 \
      cmp -s "$C/before-cap.$artifact" "$C/rcap-codex-sol.$artifact"
  done
  assert_grep "cap refusal persists its diagnostic in the seat log" \
    "$C/rcap-codex-sol.log" '^persistent provider-call cap reached for this seat generation$'
  assert_grep "cap refusal writes a fresh exit" "$C/rcap-codex-sol.exit" '^7$'

  local A="$T/seat-archive-failure" archive_path="$T/archive-path" real_python
  seat_roster "$A"; echo "review the diff" > "$A/p.md"
  printf 'prior stream\n' > "$A/rarchive-codex-sol.stream.ndjson"
  mkdir -p "$archive_path"
  real_python=$(command -v python3)
  cat > "$archive_path/python3" <<'SH'
#!/bin/bash
if [ "$1" = "$ATTEMPT_HELPER" ] && [ "$2" = reserve ]; then
  "$REAL_PYTHON" - "$@" <<'PY'
import os
import runpy
import sys

helper, *args = sys.argv[1:]
replace = os.replace
def reject_stream_archive(source, destination):
    target = str(destination)
    if (os.environ.get('FAIL_REPLACE') == 'archive'
            and target.endswith('.stream.attempt1.ndjson')):
        raise OSError('injected transcript archival failure')
    if (os.environ.get('FAIL_REPLACE') == 'attempt-write'
            and '/attempts/' in target and target.endswith('.json')):
        raise OSError('injected attempt state write failure')
    return replace(source, destination)
os.replace = reject_stream_archive
sys.argv = [helper, *args]
runpy.run_path(helper, run_name='__main__')
PY
  exit $?
fi
exec "$REAL_PYTHON" "$@"
SH
  chmod +x "$archive_path/python3"
  : > "$T/archive-calls"
  PATH="$archive_path:$PATH" REAL_PYTHON="$real_python" FAIL_REPLACE=archive \
    ATTEMPT_HELPER="$SCRIPTS/lib/rev-attempt.py" SHIM_MODE=ok SHIM_CALLS_FILE="$T/archive-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$A" archive "$A/p.md" >/dev/null 2>&1
  assert_eq "failed transcript archival exits before provider launch" "$?" 1
  assert_eq "failed transcript archival consumes no provider call" \
    "$(wc -l < "$T/archive-calls" | tr -d ' ')" 0
  assert_eq "failed transcript archival leaves no empty attempt record" \
    "$(find "$A/attempts" -type f -name '*.json' -print | wc -l | tr -d ' ')" 0
  PATH="$archive_path:$PATH" REAL_PYTHON="$real_python" FAIL_REPLACE=attempt-write \
    ATTEMPT_HELPER="$SCRIPTS/lib/rev-attempt.py" SHIM_MODE=ok SHIM_CALLS_FILE="$T/archive-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$A" archive "$A/p.md" >/dev/null 2>&1
  assert_eq "failed reservation state write exits before provider launch" "$?" 1
  assert_eq "failed reservation state write consumes no provider call" \
    "$(wc -l < "$T/archive-calls" | tr -d ' ')" 0
  assert_grep "failed reservation state write restores the prior transcript" \
    "$A/rarchive-codex-sol.stream.ndjson" '^prior stream$'
  assert_eq "failed reservation state write removes its archived copy" \
    "$(find "$A" -maxdepth 1 -name 'rarchive-codex-sol.stream.attempt*.ndjson' -print | wc -l | tr -d ' ')" 0
  assert_eq "failed reservation state write leaves no empty attempt record" \
    "$(find "$A/attempts" -type f -name '*.json' -print | wc -l | tr -d ' ')" 0
  for call in 1 2 3 4; do
    SHIM_MODE=ok SHIM_CALLS_FILE="$T/archive-calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$A" archive "$A/p.md" >/dev/null
    assert_eq "archive recovery retains provider call $call" "$?" 0
  done
  assert_eq "archive recovery retains all four provider launches" \
    "$(wc -l < "$T/archive-calls" | tr -d ' ')" 4

  local D="$T/seat-corrupt-cap"; seat_roster "$D"; echo "review the diff" > "$D/p.md"
  : > "$T/corrupt-calls"
  SHIM_MODE=ok SHIM_CALLS_FILE="$T/corrupt-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$D" corrupt "$D/p.md" >/dev/null
  printf '{' > "$(find "$D/attempts" -type f -name '*.json' -print -quit)"
  SHIM_MODE=ok SHIM_CALLS_FILE="$T/corrupt-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$D" corrupt "$D/p.md" >/dev/null 2>&1
  assert_eq "corrupt persistent attempt state fails closed" "$?" 1
  assert_eq "corrupt attempt state launches no replacement provider" \
    "$(wc -l < "$T/corrupt-calls" | tr -d ' ')" 1
  assert_grep "corrupt attempt state preserves the prior completion exit" \
    "$D/rcorrupt-codex-sol.exit" '^0$'

  local W="$T/seat-reserve-window"; seat_roster "$W"; echo "review the diff" > "$W/p.md"
  echo 0 > "$W/rblocked-codex-sol.exit"
  local python_bin="$T/reserve-python-bin" real_python reserve_pid reserve_rc i=0
  real_python=$(command -v python3)
  mkdir -p "$python_bin"
  cat > "$python_bin/python3" <<'SH'
#!/bin/bash
if [ "$1" = "$RESERVE_HELPER" ] && [ "$2" = reserve ]; then
  : > "$RESERVE_READY"
  while [ ! -e "$RESERVE_RELEASE" ]; do sleep 0.02; done
  exit 7
fi
exec "$REAL_PYTHON" "$@"
SH
  chmod +x "$python_bin/python3"
  env PATH="$python_bin:$PATH" REAL_PYTHON="$real_python" \
    RESERVE_HELPER="$SCRIPTS/lib/rev-attempt.py" RESERVE_READY="$T/reserve.ready" \
    RESERVE_RELEASE="$T/reserve.release" SHIM_MODE=ok \
    "$SCRIPTS/rev-seat.sh" codex-sol "$W" blocked "$W/p.md" > "$T/reserve.out" 2>&1 &
  reserve_pid=$!
  while [ ! -e "$T/reserve.ready" ] && kill -0 "$reserve_pid" 2>/dev/null && [ "$i" -lt 100 ]; do
    sleep 0.02; i=$((i + 1))
  done
  if [ ! -e "$T/reserve.ready" ]; then
    fail "reserve test reaches the blocked reservation" "wrapper exited before reservation"
  elif grep -qx '0' "$W/rblocked-codex-sol.exit"; then
    ok "the prior exit remains until a reservation succeeds"
  else
    fail "the prior exit remains until a reservation succeeds" "the old exit was removed or changed"
  fi
  : > "$T/reserve.release"
  wait "$reserve_pid"; reserve_rc=$?
  assert_eq "blocked cap refusal exits with reserve status" "$reserve_rc" 7
  assert_grep "blocked cap refusal publishes a fresh exit" "$W/rblocked-codex-sol.exit" '^7$'
  assert_grep "blocked cap refusal persists its diagnostic" \
    "$W/rblocked-codex-sol.log" '^persistent provider-call cap reached for this seat generation$'
  seat_env_reset "$_path"
}
test_seat_zero_tool_incomplete_proof_keeps_its_retry() {
  local _path="$PATH"; seat_env
  local S="$T/seat-zero-tool-proof" bin="$T/seat-zero-tool-bin" label
  seat_roster "$S"; echo "review the diff" > "$S/p.md"; mkdir -p "$bin"
  cat > "$bin/codex" <<'SH'
#!/bin/bash
printf '%s\n' call >> "$ZERO_TOOL_CALLS"
[ "$(wc -l < "$ZERO_TOOL_CALLS" | tr -d ' ')" = 1 ] || exec "$SHIM_CODEX" "$@"
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out=$a; prev=$a; done
cat > /dev/null
echo '{"type":"item.completed","item":{"id":"answer","type":"agent_message","text":"INCOMPLETE PROOF"}}'
printf '%s\n' '{"summary":"INCOMPLETE PROOF: no assigned source was read","findings":[]}' > "$out"
SH
  chmod +x "$bin/codex"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 2 "$S/p.md" >/dev/null 2>&1
  assert_eq "label 2's setup launch exits 0" "$?" 0
  assert_eq "label 2 starts with a completed launch on record" \
    "$(python3 -c 'import glob,json,sys; print([r.get("launches") for r in (json.load(open(p)) for p in glob.glob(sys.argv[1] + "/attempts/*.json")) if (r.get("panel"), r.get("seat")) == ("2", "codex-sol")])' "$S")" \
    "[[0]]"
  # With a completed launch on record, only discarding the zero-tool answer lets label 2's retry reserve.
  for label in 1 2; do
    : > "$T/zero-tool-calls"
    PATH="$bin:$PATH" ZERO_TOOL_CALLS="$T/zero-tool-calls" SHIM_CODEX="$SHIMS/codex" SHIM_MODE=ok \
      "$SCRIPTS/rev-seat.sh" codex-sol "$S" "$label" "$S/p.md" >/dev/null 2>&1
    assert_eq "label $label: a zero-tool INCOMPLETE PROOF answer still gets its retry" "$?" 0
    assert_eq "label $label: the answer and its retry are two provider calls" \
      "$(wc -l < "$T/zero-tool-calls" | tr -d ' ')" 2
    assert_grep "label $label: the tool-using retry is the seat's result" \
      "$S/r$label-codex-sol.json" '"severity": ?"P1"'
    assert_grep "label $label: the log names the zero-tool answer" "$S/r$label-codex-sol.log" \
      'answered without a single tool call \(attempt 1\)'
  done
  seat_env_reset "$_path"
}
seat_incomplete_relaunch_case() {
  local variant=$1 expected_calls=1 legacy=0 refusals=1 refusal relaunch_rc
  local _path="$PATH"; seat_env
  local S="$T/seat-incomplete-$variant" bin="$T/seat-incomplete-$variant-bin"
  local calls="$T/incomplete-$variant-calls" artifact
  seat_roster "$S"; echo "review the diff" > "$S/p.md"; mkdir -p "$bin"
  cat > "$bin/codex" <<'SH'
#!/bin/bash
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out=$a; prev=$a; done
if [ "${INCOMPLETE_MODE:-}" = zero-tool ] && [ ! -s "$SHIM_CALLS_FILE" ]; then
  printf '%s\n' call >> "$SHIM_CALLS_FILE"
  cat > /dev/null
  echo '{"type":"item.completed","item":{"id":"answer","type":"agent_message","text":"INCOMPLETE PROOF"}}'
  printf '%s\n' '{"summary":"INCOMPLETE PROOF: no assigned source was read","findings":[]}' > "$out"
  exit 0
fi
"$SHIM_CODEX" "$@" || exit
printf '%s\n' '{"summary":"INCOMPLETE PROOF: the tool budget ran out with source unread","findings":[]}' > "$out"
SH
  chmod +x "$bin/codex"
  : > "$calls"
  [ "$variant" != zero-tool ] || expected_calls=2
  PATH="$bin:$PATH" SHIM_CODEX="$SHIMS/codex" INCOMPLETE_MODE="$variant" SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" >/dev/null 2>&1
  assert_eq "$variant: a tool-using incomplete launch exits 0" "$?" 0
  assert_eq "$variant: only the initial launch and any internal retry call the provider" \
    "$(wc -l < "$calls" | tr -d ' ')" "$expected_calls"
  case "$variant" in
    legacy-*)
      legacy=1; refusals=2
      # Legacy sessions retain the genuine completion but predate the retirement marker.
      rm "$S/r1-codex-sol.incomplete-proof"
      assert_exit "$variant: the fixture has no retirement marker" 1 \
        test -e "$S/r1-codex-sol.incomplete-proof"
      assert_grep "$variant: the legacy completion still has its original exit" \
        "$S/r1-codex-sol.exit" '^0$'
      cp "$S/r1-codex-sol.exit" "$S/before-precheck.exit"
      mkdir "$S/before-reservation"
      cp "$S"/attempts/*.json "$S/before-reservation/";;
  esac
  if [ "$variant" = zero-tool ]; then
    python3 - "$S" <<'PY'
import json
from pathlib import Path
import sys

records = [json.loads(path.read_text()) for path in (Path(sys.argv[1]) / 'attempts').glob('*.json')]
assert len(records) == 1 and records[0]['calls'] == 2 and records[0]['launches'] == [0], records
PY
    assert_eq "zero-tool: two reservations with one successful completion still retire an incomplete assignment" "$?" 0
  fi
  for artifact in json read-audit.json stream.ndjson; do
    cp "$S/r1-codex-sol.$artifact" "$S/before-relaunch.$artifact"
  done
  cp "$S/p.md" "$S/launched-prompt.md"
  case "$variant" in
    hardlink|legacy-hardlink) ln "$S/r1-codex-sol.json" "$S/retained-result.json";;
    symlink|legacy-symlink)
      mv "$S/r1-codex-sol.json" "$S/retained-result.json"
      ln -s retained-result.json "$S/r1-codex-sol.json";;
    changed-prompt) printf '\nAlso check consumer ordering.\n' >> "$S/p.md";;
  esac
  for ((refusal=1; refusal<=refusals; refusal++)); do
    SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" >/dev/null 2> "$S/relaunch.err"
    relaunch_rc=$?
    if [ "$legacy" = 1 ]; then
      if [ "$relaunch_rc" -ne 0 ]; then ok "$variant: relaunch $refusal fails closed"
      else fail "$variant: relaunch $refusal fails closed" "unsafe legacy result launched again"
      fi
      for artifact in "$S"/before-reservation/*.json; do
        assert_exit "$variant: refusal $refusal spends no reservation" 0 \
          cmp -s "$artifact" "$S/attempts/${artifact##*/}"
      done
      assert_exit "$variant: refusal $refusal invents no completion marker" 1 \
        test -e "$S/r1-codex-sol.incomplete-proof"
      assert_exit "$variant: refusal $refusal retains the original completion evidence" 0 \
        cmp -s "$S/before-precheck.exit" "$S/r1-codex-sol.exit"
      if [ "$variant" = legacy-symlink ]; then
        assert_exit "$variant: refusal $refusal retains the unresolved symbolic link" 0 \
          test -L "$S/r1-codex-sol.json"
      else
        assert_exit "$variant: refusal $refusal retains the unresolved hard link" 0 \
          test "$S/r1-codex-sol.json" -ef "$S/retained-result.json"
      fi
    else
      assert_eq "$variant: rev-seat.sh refuses the same assignment" "$relaunch_rc" 2
      assert_grep "$variant: refusal identifies the incomplete result" "$S/relaunch.err" 'INCOMPLETE PROOF'
      assert_grep "$variant: refusal publishes its exit" "$S/r1-codex-sol.exit" '^2$'
    fi
    assert_eq "$variant: refusal $refusal spends no additional provider call" \
      "$(wc -l < "$calls" | tr -d ' ')" "$expected_calls"
    for artifact in json read-audit.json stream.ndjson; do
      assert_exit "$variant: refusal $refusal preserves the prior $artifact" 0 \
        cmp -s "$S/before-relaunch.$artifact" "$S/r1-codex-sol.$artifact"
    done
  done
  python3 - "$SCRIPTS/lib/rev-attempt.py" "$S" "$S/p.md" "$legacy" <<'PY'
import importlib.util
from pathlib import Path
import shutil
import sys

spec = importlib.util.spec_from_file_location('rev_attempt', sys.argv[1])
attempt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attempt)
if sys.argv[4] == '1':
    session = Path(sys.argv[2])
    try:
        terminal = attempt.terminal_failure(session, '1', 'codex-sol', Path(sys.argv[3]))
    except (OSError, ValueError):
        terminal = False
    assert not terminal, 'unsafe legacy bytes cannot establish replacement eligibility'
    restored = session / 'restored-result.json'
    shutil.copyfile(session / 'before-relaunch.json', restored)
    restored.replace(session / 'r1-codex-sol.json')
    assert attempt.terminal_failure(session, '1', 'codex-sol', Path(sys.argv[3])), \
        'repairing only the result must restore genuine legacy completion eligibility'
else:
    assert attempt.terminal_failure(Path(sys.argv[2]), '1', 'codex-sol', Path(sys.argv[3]))
PY
  assert_eq "$variant: refusal preserves honest replacement eligibility" "$?" 0
  if [ "$legacy" = 1 ]; then
    SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" >/dev/null 2> "$S/repaired-relaunch.err"
    assert_eq "$variant: the repaired legacy result retires without relaunching" "$?" 2
    assert_exit "$variant: genuine completion now has a retirement record" 0 \
      test -s "$S/r1-codex-sol.incomplete-proof"
    assert_eq "$variant: repairing the result spends no provider call" \
      "$(wc -l < "$calls" | tr -d ' ')" "$expected_calls"
    for artifact in "$S"/before-reservation/*.json; do
      assert_exit "$variant: recovering retirement spends no reservation" 0 \
        cmp -s "$artifact" "$S/attempts/${artifact##*/}"
    done
    for artifact in json read-audit.json stream.ndjson; do
      assert_exit "$variant: recovering retirement retains the original $artifact" 0 \
        cmp -s "$S/before-relaunch.$artifact" "$S/r1-codex-sol.$artifact"
    done
  fi
  SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
    "$SCRIPTS/rev-seat.sh" codex-terra "$S" 1 "$S/p.md" >/dev/null 2>&1
  assert_eq "$variant: a sibling under the same label still launches" "$?" 0
  SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 2 "$S/p.md" >/dev/null 2>&1
  assert_eq "$variant: the same seat under the next label still launches" "$?" 0
  assert_eq "$variant: only the sibling and later label spend new calls" \
    "$(wc -l < "$calls" | tr -d ' ')" "$((expected_calls + 2))"
  seat_env_reset "$_path"
}
test_seat_incomplete_proof_refuses_a_relaunch() {
  seat_incomplete_relaunch_case regular
}
test_seat_hardlinked_incomplete_proof_refuses_a_relaunch() {
  seat_incomplete_relaunch_case hardlink
  seat_incomplete_relaunch_case legacy-hardlink
}
test_seat_symlinked_incomplete_proof_refuses_a_relaunch() {
  seat_incomplete_relaunch_case symlink
  seat_incomplete_relaunch_case legacy-symlink
}
test_seat_incomplete_proof_refuses_a_changed_prompt_relaunch() {
  seat_incomplete_relaunch_case changed-prompt
}
test_seat_zero_tool_retry_completed_incomplete_proof_is_terminal() {
  seat_incomplete_relaunch_case zero-tool
}
test_seat_unrecorded_failed_incomplete_proof_keeps_its_exact_retry() {
  local _path="$PATH"; seat_env
  local S="$T/seat-unrecorded-failure" bin="$T/unrecorded-failure-bin" real_python
  local calls="$T/unrecorded-failure-calls"
  seat_roster "$S"; echo "review the diff" > "$S/p.md"; mkdir -p "$bin"
  : > "$calls"
  SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" >/dev/null 2>&1
  assert_eq "the earlier complete launch exits 0" "$?" 0
  real_python=$(command -v python3)
  cat > "$bin/python3" <<'SH'
#!/bin/bash
if [ "$1" = "$ATTEMPT_HELPER" ] && [ "$2" = record ]; then exit 1; fi
exec "$REAL_PYTHON" "$@"
SH
  cat > "$bin/codex" <<'SH'
#!/bin/bash
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out=$a; prev=$a; done
"$SHIM_CODEX" "$@" || exit
printf '%s\n' '{"summary":"INCOMPLETE PROOF: the failed launch left source unread","findings":[]}' > "$out"
exit 1
SH
  chmod +x "$bin/python3" "$bin/codex"
  PATH="$bin:$PATH" REAL_PYTHON="$real_python" ATTEMPT_HELPER="$SCRIPTS/lib/rev-attempt.py" \
    SHIM_CODEX="$SHIMS/codex" SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" >/dev/null 2>&1
  assert_eq "the next incomplete launch fails with exit 1" "$?" 1
  assert_grep "the failed launch publishes its exit before recording" "$S/r1-codex-sol.exit" '^1$'
  assert_grep "the fixture reaches the failed completion-record write" "$S/r1-codex-sol.log" \
    '^cannot record this launch.s exit$'
  python3 - "$S" <<'PY'
import json
from pathlib import Path
import sys

records = [json.loads(path.read_text()) for path in (Path(sys.argv[1]) / 'attempts').glob('*.json')]
assert len(records) == 1 and records[0]['calls'] == 2 and records[0]['launches'] == [0], records
PY
  assert_eq "the failed record leaves an older success after the new reservation" "$?" 0
  cp "$S/r1-codex-sol.json" "$S/failed-result.json"
  SHIM_MODE=ok SHIM_CALLS_FILE="$calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" >/dev/null 2>&1
  assert_eq "the current failed incomplete launch keeps its real wrapper retry" "$?" 0
  assert_eq "exactly one provider call is spent on the permitted retry" \
    "$(wc -l < "$calls" | tr -d ' ')" 3
  assert_grep "the retry's complete result replaces the failed incomplete result" \
    "$S/r1-codex-sol.json" '"severity": ?"P1"'
  assert_grep "the failed result remains available in the retained diagnostic" \
    "$S/failed-result.json" 'INCOMPLETE PROOF'

  python3 - "$S" <<'PY'
import json
from pathlib import Path
import sys

records = [json.loads(path.read_text()) for path in (Path(sys.argv[1]) / 'attempts').glob('*.json')]
assert (len(records) == 1 and records[0]['calls'] == 3
        and records[0]['launches'] == [0, 1, 0]
        and records[0]['completed_calls'] == 3
        and records[0]['active_launch'] is None), records
PY
  assert_eq "retry records the interrupted launch before its successor" "$?" 0

  local A="$T/seat-active-launch" active_calls="$T/active-launch-calls"
  seat_roster "$A"; echo "review the diff" > "$A/p.md"
  : > "$active_calls"
  python3 - "$SCRIPTS/lib/rev-attempt.py" "$A" "$A/p.md" <<'PY'
import importlib.util
import json
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('rev_attempt', sys.argv[1])
attempt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attempt)
session, prompt = Path(sys.argv[2]), Path(sys.argv[3])
path, identity = attempt.record_path(session, '1', 'codex-sol', prompt)
path.parent.mkdir(mode=0o700, exist_ok=True)
record = dict(identity, calls=1, launches=[], lifecycle_version=2,
              completed_calls=0, active_launch='a' * 32, last_launch=None)
path.write_text(json.dumps(record) + '\n')
path.chmod(0o600)
PY
  echo 0 > "$A/r1-codex-sol.exit"
  printf '{"summary":"prior completion"}\n' > "$A/r1-codex-sol.json"
  cp "$A/r1-codex-sol.json" "$T/active-launch-prior.json"
  local reserve_bin="$T/active-reserve-bin" real_python active_pid active_rc i=0
  local reserve_ready="$T/active-reserve.ready" reserve_release="$T/active-reserve.release"
  local active_raw="$A/r1-codex-sol.stream.ndjson"
  printf 'active provider stream\n' > "$active_raw"
  cp "$active_raw" "$T/active-launch-prior-stream.ndjson"
  real_python=$(command -v python3); mkdir -p "$reserve_bin"
  cat > "$reserve_bin/python3" <<'SH'
#!/bin/bash
if [ "$1" = "$ATTEMPT_HELPER" ] && [ "$2" = reserve ]; then
  : > "$RESERVE_READY"
  while [ ! -e "$RESERVE_RELEASE" ]; do sleep 0.02; done
  exit 1
fi
exec "$REAL_PYTHON" "$@"
SH
  chmod +x "$reserve_bin/python3"
  env PATH="$reserve_bin:$PATH" REAL_PYTHON="$real_python" \
    ATTEMPT_HELPER="$SCRIPTS/lib/rev-attempt.py" \
    RESERVE_READY="$reserve_ready" RESERVE_RELEASE="$reserve_release" \
    SHIM_MODE=ok SHIM_CALLS_FILE="$active_calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$A" 1 "$A/p.md" > "$T/active-reserve.out" 2>&1 &
  active_pid=$!
  while [ ! -e "$reserve_ready" ] && kill -0 "$active_pid" 2>/dev/null && [ "$i" -lt 100 ]; do
    sleep 0.02; i=$((i + 1))
  done
  if [ ! -e "$reserve_ready" ]; then
    fail "a competing wrapper reaches its reservation" "wrapper exited before reserve"
  else
    assert_exit "a competing wrapper leaves the active transcript in place" 0 \
      cmp -s "$T/active-launch-prior-stream.ndjson" "$active_raw"
  fi
  : > "$reserve_release"
  wait "$active_pid"; active_rc=$?
  assert_eq "a competing wrapper cannot take an active reservation" "$active_rc" 1
  assert_eq "active reservation refusals launch no provider" \
    "$(wc -l < "$active_calls" | tr -d ' ')" 0
  assert_exit "a competing wrapper preserves the active transcript" 0 \
    cmp -s "$T/active-launch-prior-stream.ndjson" "$active_raw"
  assert_grep "a competing wrapper preserves the prior exit" \
    "$A/r1-codex-sol.exit" '^0$'
  assert_exit "a competing wrapper preserves the prior result" 0 \
    cmp -s "$T/active-launch-prior.json" "$A/r1-codex-sol.json"
  python3 - "$A" <<'PY'
import json
from pathlib import Path
import sys

records = [json.loads(path.read_text()) for path in (Path(sys.argv[1]) / 'attempts').glob('*.json')]
assert (len(records) == 1 and records[0]['calls'] == 1
        and records[0]['launches'] == []
        and records[0]['completed_calls'] == 0
        and records[0]['active_launch'] == 'a' * 32), records
PY
  assert_eq "active reservation state remains unchanged" "$?" 0
  seat_env_reset "$_path"
}
test_seat_process_group_cancellation_preserves_partial_stream() {
  local _path="$PATH"; seat_env
  local S="$T/seat-cancel"; seat_roster "$S"; echo "review the diff" > "$S/p.md"
  local child_file="$T/seat-cancel-child.pid" leader pgid child i=0
  set -m
  SHIM_MODE=hang_with_child SHIM_CHILD_PID_FILE="$child_file" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" kill "$S/p.md" > "$T/seat-cancel.out" 2>&1 &
  leader=$!
  while [ ! -s "$child_file" ] && kill -0 "$leader" 2>/dev/null && [ "$i" -lt 100 ]; do
    sleep 0.1; i=$((i + 1))
  done
  if [ ! -s "$child_file" ]; then
    fail "cancellation shim records its sleeping descendant" "leader exited before publishing a child PID"
    kill -9 "$leader" 2>/dev/null || true
    wait "$leader" 2>/dev/null || true
    set +m
    seat_env_reset "$_path"
    return
  fi
  child=$(cat "$child_file")
  pgid=$(ps -o pgid= -p "$leader" | tr -d ' ')
  assert_eq "rev-seat background job owns its process group" "$pgid" "$leader"
  kill -TERM "-$pgid" 2>/dev/null || true
  wait "$leader" 2>/dev/null || true
  set +m
  i=0
  while kill -0 "$child" 2>/dev/null && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
  if kill -0 "$leader" 2>/dev/null; then fail "cancellation kills the rev-seat leader" "PID $leader remains"; else ok "cancellation kills the rev-seat leader"; fi
  if kill -0 "$child" 2>/dev/null; then
    fail "cancellation reaches the provider descendant" "PID $child remains"
    kill -9 "$child" 2>/dev/null || true
  else
    ok "cancellation reaches the provider descendant"
  fi
  assert_grep "cancellation retains the partial provider stream" \
    "$S/rkill-codex-sol.stream.ndjson" '"type":"item.started"'
  seat_env_reset "$_path"
}

test_seat_scope_env_selects_root_outside_repository() {
  local _path="$PATH"; seat_env
  local R="$T/scope-root'quoted" S="$T/seat-scope-root" CALLER="$T/caller"
  mkrepo "$R"
  seat_roster "$S"
  echo "review the diff" > "$S/p.md"
  python3 - "$S/scope.env" "$R" <<'PY'
import shlex
import sys

with open(sys.argv[1], 'w', encoding='utf-8') as stream:
    stream.write('REV_ROOT=' + shlex.quote(sys.argv[2]) + '\n')
PY
  mkdir -p "$CALLER"
  : > "$T/args"
  : > "$T/args.env"
  (
    cd "$CALLER"
    env -u REV_REPO SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md"
  ) > "$T/scope-root.out"
  assert_eq "scope-root seat exits successfully outside the repository" "$?" 0
  assert_grep "Codex receives the frozen scope root" "$T/args" "^$R$"
  assert_nogrep "Codex does not receive the caller's unrelated directory" "$T/args" "^$CALLER$"
  env REV_REPO="$CALLER" SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 2 "$S/p.md" > "$T/scope-override.out"
  assert_eq "scope root overrides a stale REV_REPO" "$?" 0
  assert_grep "a stale override still launches from the frozen root" "$T/args" "^$R$"
  assert_nogrep "a stale override cannot redirect the provider" "$T/args" "^$CALLER$"
  seat_env_reset "$_path"
}
