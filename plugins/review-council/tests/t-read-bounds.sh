#!/bin/bash

read_bound_hook() {
  local root=$1 session=$2 payload=$3 prompt=${4:-}
  local args=(hook --root "$root" --session "$session")
  local response status
  [ -z "$prompt" ] || args+=(--prompt "$prompt")
  response=$(printf '%s' "$payload" | python3 "$SCRIPTS/lib/review-read-audit.py" \
    "${args[@]}" 2>/dev/null)
  status=$?
  [ "$status" -eq 0 ] || return "$status"
  [ -n "$response" ] || return 0
  printf '%s' "$response" | python3 -c '
import json, sys
response = json.load(sys.stdin)
specific = response.get("hookSpecificOutput", {})
blocked = response.get("continue") is False or specific.get("permissionDecision") == "deny"
raise SystemExit(2 if blocked else 0)
'
}

post_bound_hook() {
  local response status
  response=$(python3 "$SCRIPTS/lib/review-read-audit.py" post-hook "$@")
  status=$?
  [ "$status" -eq 0 ] || return "$status"
  [ -n "$response" ] || return 0
  printf '%s' "$response" | python3 -c '
import json, sys
response = json.load(sys.stdin)
raise SystemExit(2 if response.get("continue") is False else 0)
'
}

test_read_bound_hook_contract() {
  ( local R="$T/read-bound-root" S="$T/read-bound-session"
    mkdir -p "$R/src" "$S"
    printf 'one\ntwo\n' > "$R/src/x.ts"
    printf 'prompt\n' > "$S/r1-sol.prompt.md"
    printf 'index\n' > "$S/r1-evidence.md"
    printf 'segment\n' > "$S/r1-sol-source-segment-001-001.txt"
    mkdir -p "$S/deps" "$T/pinned-crate"
    printf 'dependency\n' > "$T/pinned-crate/lib.rs"
    ln -s "$T/pinned-crate" "$S/deps/pinned-crate"

    local source_ok='{"tool_name":"Read","tool_input":{"file_path":"src/x.ts","offset":1,"limit":200}}'
    local prompt_ok; prompt_ok=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' "$S/r1-sol.prompt.md")
    local index_ok; index_ok=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' "$S/r1-evidence.md")
    local segment_ok; segment_ok=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' \
      "$S/r1-sol-source-segment-001-001.txt")
    local grep_ok='{"tool_name":"Grep","tool_input":{"pattern":"retry","path":"src","head_limit":50}}'
    local shell_ok='{"tool_name":"Bash","tool_input":{"command":"git diff HEAD | sed -n '\''1,200p'\''"}}'
    local shell_search_ok='{"tool_name":"Bash","tool_input":{"command":"rg -n retry src | head -81"}}'
    local shell_log_ok='{"tool_name":"Bash","tool_input":{"command":"git log -n 240"}}'
    for payload in "$source_ok" "$prompt_ok" "$index_ok" "$segment_ok" "$grep_ok" "$shell_ok" "$shell_search_ok" "$shell_log_ok"; do
      read_bound_hook "$R" "$S" "$payload"
      assert_eq "bounded hook allows $payload" "$?" 0
    done
    local dependency_read; dependency_read=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s","offset":1,"limit":20}}' "$S/deps/pinned-crate/lib.rs")
    printf '%s' "$dependency_read" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
      --root "$R" --session "$S" --deps "$S/deps" >/dev/null 2>&1
    assert_eq "bounded hook allows an explicitly pinned dependency root" "$?" 0

    local outside; outside=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' "$T/outside.txt")
    printf 'outside\n' > "$T/outside.txt"
    mkdir -p "$T/other-session"; printf 'other prompt\n' > "$T/other-session/r1-sol.prompt.md"
    local other_artifact; other_artifact=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' \
      "$T/other-session/r1-sol.prompt.md")
    local bad_read='{"tool_name":"Read","tool_input":{"file_path":"src/x.ts","limit":200}}'
    local bad_grep='{"tool_name":"Grep","tool_input":{"pattern":"retry","path":"src"}}'
    local bad_shell='{"tool_name":"Bash","tool_input":{"command":"git diff HEAD"}}'
    local wide_shell_search='{"tool_name":"Bash","tool_input":{"command":"rg -n retry src | head -82"}}'
    local huge_shell='{"tool_name":"Bash","tool_input":{"command":"sed -n '\''1,500p'\'' src/x.ts"}}'
    local tail_from_start='{"tool_name":"Bash","tool_input":{"command":"cat src/x.ts | tail -n +1"}}'
    local tail_from_start_long='{"tool_name":"Bash","tool_input":{"command":"cat src/x.ts | tail --lines=+1"}}'
    local personal='{"tool_name":"Bash","tool_input":{"command":"cat ~/.claude/CLAUDE.md | head -20"}}'
    local opaque_shell='{"tool_name":"Bash","tool_input":{"command":"python3 -c '\''print(open(\"src/x.ts\").read())'\''"}}'
    for payload in "$outside" "$other_artifact" "$bad_read" "$bad_grep" "$bad_shell" "$wide_shell_search" "$huge_shell" "$tail_from_start" "$tail_from_start_long" "$personal" "$opaque_shell"; do
      read_bound_hook "$R" "$S" "$payload"
      assert_eq "bounded hook blocks $payload" "$?" 2
    done
    printf '%s' "$other_artifact" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
      --root "$R" >/dev/null 2> "$S/missing-session.err"
    assert_eq "hook refuses an artifact exemption without a bound session" "$?" 2
    assert_grep "missing hook session is an argument error" "$S/missing-session.err" \
      'the following arguments are required: --session'
    printf '%s' "$other_artifact" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
      --session "$S" >/dev/null 2> "$S/missing-root.err"
    assert_eq "hook refuses an artifact exemption without a bound root" "$?" 2
    assert_grep "missing hook root is an argument error" "$S/missing-root.err" \
      'the following arguments are required: --root'
    python3 - "$T/other-session/r1-sol.prompt.md" <<'PY' | \
      post_bound_hook --root "$R" \
        >/dev/null 2> "$S/post-missing-session.err"
import json, sys
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':sys.argv[1]},
                  'tool_response':'x' * 32769}))
PY
    assert_eq "post-hook refuses an artifact exemption without a bound session" "$?" 2
    assert_grep "missing post-hook session is an argument error" "$S/post-missing-session.err" \
      'the following arguments are required: --session'

    printf '%s' "$other_artifact" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
      --root "$R" --session "$S" --prompt "$S/r1-sol.prompt.md" \
      >/dev/null 2> "$S/cross-session.err"
    assert_eq "bounded hook rejects a cross-session artifact" "$?" 2
    assert_grep "cross-session artifact has a policy diagnostic" "$S/cross-session.err" \
      'path-outside-scope'
    printf '{' | post_bound_hook \
      --root "$R" --session "$S" >/dev/null 2> "$S/post-invalid.err"
    assert_eq "post-hook rejects malformed input without crashing" "$?" 2
    assert_grep "post-hook malformed input has a stable diagnostic" "$S/post-invalid.err" \
      'invalid-hook-payload'
  )
}

test_claude_terminal_hook_responses() {
  ( local R="$T/terminal-hook-root" S="$T/terminal-hook-session"
    mkdir -p "$R/src" "$S"
    printf 'one\n' > "$R/src/x.ts"
    printf 'Assigned scope: full\n' > "$S/prompt.md"

    local response status
    response=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git commit -m x"}}' | \
      python3 "$SCRIPTS/lib/review-read-audit.py" hook --root "$R" --session "$S" \
        --prompt "$S/prompt.md" 2> "$S/unsafe-pre.err")
    status=$?
    assert_eq "unsafe Bash pre-hook returns a structured terminal response" "$status" 0
    printf '%s' "$response" | python3 -c '
import json, sys
response = json.load(sys.stdin)
assert response["continue"] is False
assert isinstance(response["stopReason"], str) and response["stopReason"]
specific = response["hookSpecificOutput"]
assert specific["hookEventName"] == "PreToolUse"
assert specific["permissionDecision"] == "deny"
'
    assert_eq "unsafe Bash pre-hook denies and terminates Claude" "$?" 0

    response=$(python3 - <<'PY' | python3 "$SCRIPTS/lib/review-read-audit.py" post-hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" 2> "$S/fatal-post.err"
import json
print(json.dumps({'tool_name':'Read',
                  'tool_input':{'file_path':'src/x.ts','offset':1,'limit':1},
                  'tool_response':'x' * 32769}))
PY
)
    status=$?
    assert_eq "fatal post-hook violation returns a structured terminal response" "$status" 0
    printf '%s' "$response" | python3 -c '
import json, sys
response = json.load(sys.stdin)
assert response["continue"] is False
assert isinstance(response["stopReason"], str) and response["stopReason"]
'
    assert_eq "fatal post-hook violation terminates Claude" "$?" 0

    response=$(printf '%s' '{"tool_name":"Read","tool_input":{"file_path":"src/x.ts","limit":1}}' | \
      python3 "$SCRIPTS/lib/review-read-audit.py" hook --root "$R" --session "$S" \
        --prompt "$S/prompt.md" 2> "$S/recoverable-pre.err")
    status=$?
    assert_eq "recoverable read-shape denial remains nonterminal" "$status" 2
    assert_nogrep "recoverable read-shape denial does not stop Claude" "$S/recoverable-pre.err" \
      '"continue":false'
    read_bound_hook "$R" "$S" \
      '{"tool_name":"Read","tool_input":{"file_path":"src/x.ts","offset":1,"limit":1}}' \
      "$S/prompt.md"
    assert_eq "corrected bounded read succeeds after a recoverable denial" "$?" 0

    printf '{' | python3 "$SCRIPTS/lib/review-read-audit.py" hook --root "$R" --session "$S" \
      --prompt "$S/prompt.md" >/dev/null 2> "$S/malformed-pre.err"
    assert_eq "malformed pre-hook payload fails closed without crashing" "$?" 2
    assert_grep "malformed pre-hook payload has a stable diagnostic" "$S/malformed-pre.err" \
      'invalid-hook-payload'
  )
}

test_specialist_required_range_uses_session_artifacts() {
  ( local R="$T/specialist-source-root" S="$T/specialist-source-session"
    mkrepo "$R"; mkdir -p "$S"
    python3 - "$R/oversized.py" <<'PY'
import sys
with open(sys.argv[1], 'w') as stream:
    stream.write('def oversized():\n')
    for index in range(520):
        stream.write(f'    value_{index} = "{index:04d}-' + 'x' * 80 + '"\n')
    stream.write('    return value_519\n')
PY
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'oversized.py\n' > "$S/files.txt"; printf 'oversized.py\n' > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    local manifest seat bundle prompt
    manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 10 --phase discovery) || return
    seat=$(python3 - "$manifest" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
for seat, context in doc['source_context']['seats'].items():
    if context['role'] == 'specialist' and context['source_read_required'] and context['required_source_ranges']:
        print(seat)
        break
PY
) || return
    [ -n "$seat" ] || { fail "fixture assigns an omitted range to a specialist"; return; }
    bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"][sys.argv[2]]["bundle"])' "$manifest" "$seat") || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 10 "$seat" "$bundle" specialist-source --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r10-$seat.json"

    write_specialist_transcript() {
      python3 - "$manifest" "$S/r10-$seat.stream.ndjson" "$seat" "$R" "$1" <<'PY'
import json, pathlib, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2])
seat, root, mode = sys.argv[3], pathlib.Path(sys.argv[4]), sys.argv[5]
session = pathlib.Path(sys.argv[1]).parent; context = manifest['source_context']['seats'][seat]
events = []
def command(call_id, command_text, output):
    events.extend([
        {'type':'item.started','item':{'id':call_id,'type':'command_execution','command':command_text}},
        {'type':'item.completed','item':{'id':call_id,'type':'command_execution','command':command_text,
                                         'aggregated_output':output,'exit_code':0}},
    ])
for index, shard in enumerate(context['shards'], 1):
    path = session / shard['artifact']
    command('packet-' + str(index), "cat '" + str(path) + "'", path.read_text())
patch = pathlib.Path(manifest['assignments'][seat]['patch']); lines = patch.read_text().splitlines(keepends=True)
for start in range(1, len(lines) + 1, 240):
    end = min(len(lines), start + 239)
    command('patch-' + str(start), f"sed -n '{start},{end}p' '{patch}'", ''.join(lines[start - 1:end]))
if mode != 'unrelated':
    required = context['required_source_ranges'][0]
    for segment in required['segments']:
        path = session / segment['artifact']
        command('source-required-' + str(segment['index']), "cat '" + str(path) + "'",
                path.read_text())
index = session / f"r{manifest['label']}-evidence.md"
command('evidence-index', "cat '" + str(index) + "'", index.read_text())
if mode == 'unrelated':
    command('source-unrelated', "sed -n '1,1p' a.txt", (root / 'a.txt').read_text())
with out.open('w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    }

    write_specialist_transcript unrelated
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r10-$seat.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r10-$seat.read-audit.json" >/dev/null 2>&1
    assert_eq "specialist rejects a source read outside every assigned required range" "$?" 2
    assert_grep "unrelated specialist read has a stable violation" "$S/r10-$seat.read-audit.json" \
      '"code":"missing-required-source-read"'

    write_specialist_transcript required
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r10-$seat.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r10-$seat.read-audit.json" >/dev/null 2>&1
    local audit_rc=$?
    assert_eq "specialist accepts every exact required source segment" "$audit_rc" 0
    assert_grep "specialist receipt binds the complete required parent range" \
      "$S/r10-$seat.read-audit.json" '"required_source_ranges_covered":1'
  )
}

test_disabled_context_requires_component_boundary() {
  ( local R="$T/disabled-context-root" S="$T/disabled-context-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"; printf 'value = 1\n' > "$R/src/x.py"
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/x.py\n' > "$S/files.txt"; printf 'src/x.py\n' > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    local manifest seat bundle prompt
    manifest=$(REV_SOURCE_CONTEXT=0 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 11 --phase discovery) || return
    seat=$(python3 - "$manifest" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
for seat, context in doc['source_context']['seats'].items():
    if context['role'] == 'specialist' and context['source_read_required']:
        assert not context['required_source_ranges']
        print(seat)
        break
PY
) || return
    [ -n "$seat" ] || { fail "disabled context fixture assigns a specialist boundary"; return; }
    bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"][sys.argv[2]]["bundle"])' "$manifest" "$seat") || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 11 "$seat" "$bundle" disabled-context --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r11-$seat.json"

    write_disabled_transcript() {
      python3 - "$manifest" "$S/r11-$seat.stream.ndjson" "$seat" "$R" "$1" <<'PY'
import json, pathlib, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2])
seat, root, mode = sys.argv[3], pathlib.Path(sys.argv[4]), sys.argv[5]
events = []
def command(call_id, command_text, output):
    events.extend([
        {'type':'item.started','item':{'id':call_id,'type':'command_execution','command':command_text}},
        {'type':'item.completed','item':{'id':call_id,'type':'command_execution','command':command_text,
                                         'aggregated_output':output,'exit_code':0}},
    ])
patch = pathlib.Path(manifest['assignments'][seat]['patch']); lines = patch.read_text().splitlines(keepends=True)
for start in range(1, len(lines) + 1, 240):
    end = min(len(lines), start + 239)
    command('patch-' + str(start), f"sed -n '{start},{end}p' '{patch}'", ''.join(lines[start - 1:end]))
index = pathlib.Path(sys.argv[1]).parent / f"r{manifest['label']}-evidence.md"
command('evidence-index', "cat '" + str(index) + "'", index.read_text())
path = 'a.txt' if mode == 'unrelated' else 'src/x.py'
command('source', f"sed -n '1,1p' '{path}'", (root / path).read_text())
with out.open('w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    }

    write_disabled_transcript unrelated
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r11-$seat.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r11-$seat.read-audit.json" >/dev/null 2>&1
    assert_eq "disabled context rejects an unrelated repository read" "$?" 2
    assert_grep "disabled context names the missing assigned source read" \
      "$S/r11-$seat.read-audit.json" '"code":"missing-required-source-read"'

    write_disabled_transcript boundary
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r11-$seat.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r11-$seat.read-audit.json" >/dev/null 2>&1
    assert_eq "disabled context accepts a bounded assigned component boundary read" "$?" 0
  )
}

test_implicit_turn_output_cap() {
  # Historical Grok and Gemini transcripts keep their decoder and turn-accounting coverage.
  ( local R="$T/implicit-turn-root" S="$T/implicit-turn-session"
    mkdir -p "$R/src" "$S"; printf 'x\n' > "$R/src/x.ts"
    printf 'Assigned scope: full\n' > "$S/prompt.md"
    local adapter
    for adapter in grok gemini; do
      python3 - "$S/$adapter.ndjson" "$adapter" <<'PY'
import json, sys
path, adapter = sys.argv[1:]
if adapter == 'grok':
    events = [
        {'type':'tool_call','toolCallId':'a','toolName':'read_file','rawInput':{'target_file':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_call','toolCallId':'b','toolName':'read_file','rawInput':{'target_file':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_call_update','toolCallId':'a','status':'completed','rawOutput':'a' * 20000},
        {'type':'tool_call_update','toolCallId':'b','status':'completed','rawOutput':'b' * 20000},
    ]
else:
    events = [
        {'type':'tool_use','tool_id':'a','tool_name':'read_file','parameters':{'path':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_use','tool_id':'b','tool_name':'read_file','parameters':{'path':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_result','tool_id':'a','status':'success','output':'a' * 20000},
        {'type':'tool_result','tool_id':'b','status':'success','output':'b' * 20000},
    ]
with open(path, 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" \
        --raw "$S/$adapter.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
        --out "$S/$adapter-audit.json" >/dev/null 2>&1
      assert_eq "$adapter implicit parallel turn enforces combined byte cap" "$?" 2
      assert_grep "$adapter implicit turn cap has a stable violation" "$S/$adapter-audit.json" \
        '"code":"tool-turn-output-too-large"'

      python3 - "$S/$adapter-stale.ndjson" "$adapter" <<'PY'
import json, sys
path, adapter = sys.argv[1:]
if adapter == 'grok':
    events = [
        {'type':'tool_call','toolCallId':'missing','toolName':'read_file','rawInput':{'target_file':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_call','toolCallId':'first','toolName':'read_file','rawInput':{'target_file':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_call_update','toolCallId':'first','status':'completed','rawOutput':'a' * 20000},
        {'type':'tool_call','toolCallId':'second','toolName':'read_file','rawInput':{'target_file':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_call_update','toolCallId':'second','status':'completed','rawOutput':'b' * 20000},
    ]
else:
    events = [
        {'type':'tool_use','tool_id':'missing','tool_name':'read_file','parameters':{'path':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_use','tool_id':'first','tool_name':'read_file','parameters':{'path':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_result','tool_id':'first','status':'success','output':'a' * 20000},
        {'type':'tool_use','tool_id':'second','tool_name':'read_file','parameters':{'path':'src/x.ts','offset':1,'limit':1}},
        {'type':'tool_result','tool_id':'second','status':'success','output':'b' * 20000},
    ]
with open(path, 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" \
        --raw "$S/$adapter-stale.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
        --out "$S/$adapter-stale-audit.json" >/dev/null 2>&1
      assert_eq "$adapter stale missing output still fails closed" "$?" 2
      assert_grep "$adapter stale missing call retains its violation" \
        "$S/$adapter-stale-audit.json" '"code":"missing-tool-output"'
      assert_grep "$adapter call after accepted output starts a second implicit turn" \
        "$S/$adapter-stale-audit.json" '"tool_turns":2'
      assert_nogrep "$adapter stale call does not merge later completed turns" \
        "$S/$adapter-stale-audit.json" '"code":"tool-turn-output-too-large"'
    done
  )
}

test_ordered_evidence_phase_validator() {
  ( local R="$T/evidence-order-root" S="$T/evidence-order-session"
    mkdir -p "$R/src" "$S"
    printf 'source\n' > "$R/src/x.ts"
    for artifact in patch packet-1 packet-2 segment-1 segment-2 index; do
      printf '%s\n' "$artifact" > "$S/$artifact"
    done
    python3 - "$SCRIPTS/lib/review-read-audit.py" "$R" "$S" <<'PY'
import importlib.util, pathlib, sys

spec = importlib.util.spec_from_file_location('review_read_audit', sys.argv[1])
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
root, session = (pathlib.Path(value).resolve() for value in sys.argv[2:])
paths = {name: session / name for name in (
    'patch', 'packet-1', 'packet-2', 'segment-1', 'segment-2', 'index')}

def validate(order, shared_turn=()):
    calls = {}
    outputs = {}
    patch_calls = set()
    verified_ranges = {}
    for position, name in enumerate(order):
        call_id = name + '-' + str(position)
        if name == 'repo':
            data = {'file_path':'src/x.ts', 'offset':1, 'limit':1}
            verified_ranges[call_id] = [{'path':'src/x.ts','line_start':1,'line_end':1}]
        elif name == 'segment-packet-batch':
            data = {'command':'cat ' + str(paths['segment-1']) + ' ' +
                    str(paths['packet-1'])}
        else:
            data = {'file_path':str(paths[name])}
        tool = 'Bash' if name == 'segment-packet-batch' else 'Read'
        turn = ('shared-artifacts' if name in shared_turn else
                ('batch-packets' if name.startswith('packet-') else 'turn-' + str(position)))
        calls[call_id] = (tool, data, turn)
        outputs[call_id] = {'success':True, 'value':'evidence', 'bytes':8,
                            'non_execution':False}
        if name == 'patch':
            patch_calls.add(call_id)
    return audit.evidence_order_violations(
        calls, outputs, patch_calls,
        [paths['packet-1'], paths['packet-2']],
        [paths['segment-1'], paths['segment-2']], paths['index'],
        root, session, verified_ranges)

assert validate(['patch', 'packet-1', 'packet-2', 'segment-1', 'segment-2',
                 'index', 'repo']) == []
assert validate(['patch', 'packet-1', 'segment-1', 'index', 'repo', 'repo'],
                {'repo'}) == []
assert validate(['packet-1', 'packet-2', 'segment-1', 'segment-2',
                 'index', 'repo']) == []
assert validate(['patch', 'packet-1', 'segment-1', 'index'],
                {'patch', 'packet-1', 'segment-1', 'index'}) == []
assert validate(['patch', 'packet-1', 'segment-1', 'index', 'repo'],
                {'patch', 'packet-1', 'segment-1', 'index', 'repo'}) == [
                    {'code':'evidence-read-order', 'tool':'audit'}]
for order in (
    ['patch', 'packet-2', 'packet-1', 'segment-1', 'segment-2', 'index', 'repo'],
    ['patch', 'segment-1', 'packet-1', 'packet-2', 'segment-2', 'index', 'repo'],
    ['patch', 'packet-1', 'index', 'packet-2', 'segment-1', 'segment-2', 'repo'],
    ['patch', 'segment-packet-batch'],
    ['segment-1', 'packet-1', 'packet-2', 'segment-2', 'index', 'repo'],
    ['index', 'packet-1', 'packet-2', 'segment-1', 'segment-2', 'repo'],
):
    assert validate(order) == [{'code':'evidence-read-order', 'tool':'audit'}]

batch_calls = {
    'packet-1': ('Read', {}, 'shared'),
    'packet-2': ('Read', {}, 'shared'),
}
assert audit.turn_batch_violations(
    batch_calls, set(batch_calls), 1, 'source-packet-batch-too-large', 'claude') == [
        {'code':'source-packet-batch-too-large', 'tool':'claude'}]
batch_calls['packet-2'] = ('Read', {}, 'later')
assert audit.turn_batch_violations(
    batch_calls, set(batch_calls), 1, 'source-packet-batch-too-large', 'claude') == []

context = {
    'source_read_required': True,
    'role': 'integration',
    'required_source_ranges': [],
    'omitted_source_ranges': [
        {'path':'src/caller.ts', 'line_start':10, 'line_end':14},
    ],
}
assert audit.source_read_requirement_violations(
    context, {'src/declaration.ts', 'src/caller.ts'},
    [{'path':'src/declaration.ts', 'line_start':1, 'line_end':5, 'origin':'tool'}],
    'claude') == [{'code':'missing-required-source-read', 'tool':'claude'}]
assert audit.source_read_requirement_violations(
    context, {'src/declaration.ts', 'src/caller.ts'},
    [{'path':'src/caller.ts', 'line_start':12, 'line_end':12, 'origin':'tool'}],
    'claude') == []
PY
    assert_eq "evidence phases enforce ordered packets, segments, index, and expansion" "$?" 0
  )
}

test_ordered_proof_turn_exemption() {
  python3 - "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, sys

spec = importlib.util.spec_from_file_location('review_read_audit', sys.argv[1])
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
proof = {'chunk', 'segment', 'index'}
assert audit.ordered_proof_turn_exempt(2, ['chunk', 'index'], proof, 40 * 1024)
assert audit.ordered_proof_turn_exempt(2, ['segment', 'index'], proof, 60 * 1024)
assert not audit.ordered_proof_turn_exempt(1, ['chunk', 'index'], proof, 40 * 1024)
assert not audit.ordered_proof_turn_exempt(2, ['chunk', 'segment', 'index'], proof, 40 * 1024)
assert not audit.ordered_proof_turn_exempt(2, ['chunk', 'index'], proof, 60 * 1024 + 1)
assert not audit.ordered_proof_turn_exempt(2, ['packet', 'index'], proof, 40 * 1024)
assert not audit.ordered_proof_turn_exempt(2, ['chunk', 'source'], proof, 40 * 1024)
PY
  assert_eq "only bounded ordered proof reads share the 60 KiB turn exemption" "$?" 0
}

test_grok_visible_output_accounting() {
  # Historical Grok transcripts remain auditable after Grok leaves the live roster.
  ( local R="$T/grok-visible-root" S="$T/grok-visible-session"
    mkdir -p "$R/src" "$S"; printf 'Assigned scope: full\n' > "$S/prompt.md"

    write_grok_read() {
      python3 - "$R/src/x.txt" "$S/grok.ndjson" "$1" "$2" "${3:-visible}" <<'PY'
import json, pathlib, sys
source, stream = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
size, status, content_mode = int(sys.argv[3]), sys.argv[4], sys.argv[5]
body = 'x' * (size - 1) + '\n'; source.write_text(body)
visible = '1→' + body
raw = {'type':'ReadFile', 'FileContent':{
    'content':visible,
    'content_bytes':list(visible.encode()),
    'internal_copy':list(visible.encode()),
    'total_lines':1,
}}
events = [
    {'type':'tool_call','toolCallId':'read-1','toolName':'read_file',
     'rawInput':{'target_file':'src/x.txt','offset':1,'limit':1}},
    {'type':'tool_call_update','toolCallId':'read-1','status':status,
     'content':([{'type':'progress','value':'complete'}] if content_mode == 'metadata' else
                [{'type':'content','content':{'type':'text','text':visible}}]),
     'rawOutput':raw},
]
with stream.open('w') as out:
    for event in events:
        out.write(json.dumps(event) + '\n')
print(len(visible.encode()))
PY
    }

    local visible_bytes
    visible_bytes=$(write_grok_read 29696 completed) || return
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok \
      --raw "$S/grok.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/grok-audit.json" >/dev/null 2>&1
    assert_eq "Grok accepts one visible 29 KiB ReadFile result despite duplicated raw metadata" "$?" 0
    assert_eq "Grok counts the delivered text exactly once" \
      "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tool_output_bytes"])' "$S/grok-audit.json")" \
      "$visible_bytes"

    visible_bytes=$(write_grok_read 128 completed metadata) || return
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok \
      --raw "$S/grok.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/grok-audit.json" >/dev/null 2>&1
    assert_eq "Grok falls back to rawOutput when content has no delivered result text" "$?" 0
    assert_eq "Grok rawOutput fallback extracts FileContent text without wrapper bytes" \
      "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tool_output_bytes"])' "$S/grok-audit.json")" \
      "$visible_bytes"

    visible_bytes=$(write_grok_read 32769 completed) || return
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok \
      --raw "$S/grok.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/grok-audit.json" >/dev/null 2>&1
    assert_eq "Grok rejects delivered ReadFile text above 32 KiB" "$?" 2
    assert_eq "oversized Grok output still records only visible bytes" \
      "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tool_output_bytes"])' "$S/grok-audit.json")" \
      "$visible_bytes"
    assert_grep "oversized visible Grok output has the byte-cap violation" "$S/grok-audit.json" \
      '"code":"tool-output-too-large"'

    write_grok_read 128 failed >/dev/null || return
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok \
      --raw "$S/grok.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/grok-audit.json" >/dev/null 2>&1
    assert_eq "failed Grok exploration does not invalidate the review" "$?" 0
    assert_grep "failed Grok exploration provides no source proof" "$S/grok-audit.json" \
      '"source_read_calls":0'
  )
}

test_read_audit_source_evidence_contract() {
  ( local R="$T/source-evidence-root"
    mkrepo "$R"
    local S="$R/.review-session"
    mkdir -p "$R/src" "$S"
    printf '.review-session/\n' > "$R/.gitignore"
    printf 'one\ntwo\nthree\n' > "$R/src/x.ts"
    git -C "$R" add .gitignore src/x.ts && git -C "$R" commit -qm 'source baseline'
    local base reviewed; base=$(git -C "$R" rev-parse HEAD)
    printf 'one\nchanged\nthree\n' > "$R/src/x.ts"
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/x.ts\n' > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    local manifest prompt packet assigned_patch evidence_index
    manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 4 --phase discovery) || return
    local bundle
    bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["sol"]["bundle"])' "$manifest") || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 4 sol "$bundle" source-evidence --evidence "$manifest") || return
    packet=$(python3 - "$manifest" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
print(str(__import__('pathlib').Path(sys.argv[1]).parent /
          doc['source_context']['seats']['sol']['shards'][0]['artifact']))
PY
) || return
    assigned_patch=$(python3 - "$manifest" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['assignments']['sol']['patch'])
PY
) || return
    evidence_index="$S/r4-evidence.md"
    python3 - "$S/r4-sol.stream.ndjson" "$packet" "$assigned_patch" "$evidence_index" <<'PY'
import json, sys
packet = open(sys.argv[2]).read(); patch = open(sys.argv[3]).read(); index = open(sys.argv[4]).read()
packet_command = "cat '" + sys.argv[2] + "'"
patch_command = "sed -n '1,240p' '" + sys.argv[3] + "'"
index_command = "cat '" + sys.argv[4] + "'"
events = [
    {'type':'item.started','item':{'id':'p2','type':'command_execution','command':patch_command}},
    {'type':'item.completed','item':{'id':'p2','type':'command_execution','command':patch_command,
                                     'aggregated_output':patch,'exit_code':0}},
    {'type':'item.started','item':{'id':'p1','type':'command_execution','command':packet_command}},
    {'type':'item.completed','item':{'id':'p1','type':'command_execution','command':packet_command,
                                     'aggregated_output':packet,'exit_code':0}},
    {'type':'item.started','item':{'id':'i1','type':'command_execution','command':index_command}},
    {'type':'item.completed','item':{'id':'i1','type':'command_execution','command':index_command,
                                     'aggregated_output':index,'exit_code':0}},
    {'type':'item.started','item':{'id':'s1','type':'command_execution','command':"sed -n '1,1p' src/x.ts"}},
    {'type':'item.completed','item':{'id':'s1','type':'command_execution','command':"sed -n '1,1p' src/x.ts",
                                     'aggregated_output':'one\n','exit_code':0}},
]
with open(sys.argv[1], 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    cat > "$S/r4-sol.json" <<'JSON'
{"summary":"checked","findings":[{"severity":"P1","file":"src/x.ts","line_start":2,"line_end":2,"claim":"changed line","evidence":"the changed line is wrong","suggested_fix":"fix it and test it","confidence":0.9}]}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json"
    assert_eq "packet-backed finding citation audits successfully" "$?" 0
    assert_grep "audit schema records source evidence" "$S/r4-sol.read-audit.json" '"schema_version":2'
    assert_grep "audit hash-binds the evidence manifest" "$S/r4-sol.read-audit.json" '"evidence_manifest_sha256":"[0-9a-f]{64}"'
    assert_grep "audit hash-binds the result" "$S/r4-sol.read-audit.json" '"result_sha256":"[0-9a-f]{64}"'
    assert_grep "audit records packet bytes separately" "$S/r4-sol.read-audit.json" '"packet_bytes":[1-9][0-9]*'
    assert_grep "audit records packet source ranges" "$S/r4-sol.read-audit.json" '"origin":"packet"'
    assert_grep "audit records a covered finding" "$S/r4-sol.read-audit.json" '"finding_citations":1'
    assert_grep "audit hash-binds the assigned patch" "$S/r4-sol.read-audit.json" \
      '"assigned_patch_sha256":"[0-9a-f]{64}"'
    assert_grep "audit records assigned patch bytes" "$S/r4-sol.read-audit.json" \
      '"assigned_patch_bytes":[1-9][0-9]*'
    assert_grep "audit records assigned patch lines" "$S/r4-sol.read-audit.json" \
      '"assigned_patch_lines":[1-9][0-9]*'
    assert_grep "audit records byte-proven assigned patch reads" "$S/r4-sol.read-audit.json" \
      '"assigned_patch_reads":1'
    assert_grep "audit records inclusive assigned patch ranges" "$S/r4-sol.read-audit.json" \
      '"assigned_patch_ranges":\[\{"line_end":[1-9][0-9]*,"line_start":1\}\]'
    assert_grep "audit records required source range coverage" "$S/r4-sol.read-audit.json" \
      '"required_source_ranges_covered":0'

    cp "$S/r4-sol.stream.ndjson" "$T/source-evidence-with-index.ndjson"
    python3 - "$S/r4-sol.stream.ndjson" <<'PY'
import json, sys
path = sys.argv[1]
rows = [json.loads(line) for line in open(path)]
rows = [row for row in rows if (row.get('item') or {}).get('id') != 'i1']
open(path, 'w').write(''.join(json.dumps(row) + '\n' for row in rows))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "complete evidence remains valid when the navigation index is omitted" "$?" 0
    assert_grep "omitted evidence index is recorded as an advisory" "$S/r4-sol.read-audit.json" \
      '"advisories":\[[^]]*"code":"missing-evidence-index"'
    assert_grep "omitted evidence index does not discard substantive proof" \
      "$S/r4-sol.read-audit.json" '"violations":\[\]'
    cp "$T/source-evidence-with-index.ndjson" "$S/r4-sol.stream.ndjson"

    printf 'live mutation\nchanged\nthree\n' > "$R/src/x.ts"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "source reads remain bound to the frozen evidence snapshot" "$?" 0
    assert_grep "frozen snapshot bytes retain source-range credit after live mutation" \
      "$S/r4-sol.read-audit.json" '"source_read_calls":1'
    printf 'one\nchanged\nthree\n' > "$R/src/x.ts"

    write_incorrect_artifact_transcript() {
      python3 - "$S/r4-sol.stream.ndjson" "$packet" "$assigned_patch" "$1" <<'PY'
import json, sys
out, packet_path, patch_path, mode = sys.argv[1:]
packet = open(packet_path).read(); patch = open(patch_path).read()
if mode == 'packet':
    packet = ('X' if packet[:1] != 'X' else 'Y') + packet[1:]
else:
    patch = ('X' if patch[:1] != 'X' else 'Y') + patch[1:]
packet_command = "cat '" + packet_path + "'"
patch_command = "sed -n '1,240p' '" + patch_path + "'"
events = [
    {'type':'item.started','item':{'id':'patch','type':'command_execution','command':patch_command}},
    {'type':'item.completed','item':{'id':'patch','type':'command_execution','command':patch_command,
                                     'aggregated_output':patch,'exit_code':0}},
    {'type':'item.started','item':{'id':'packet','type':'command_execution','command':packet_command}},
    {'type':'item.completed','item':{'id':'packet','type':'command_execution','command':packet_command,
                                     'aggregated_output':packet,'exit_code':0}},
]
with open(out, 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    }
    write_incorrect_artifact_transcript packet
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "same-length incorrect packet output fails closed" "$?" 2
    assert_grep "incorrect packet output has a stable violation" "$S/r4-sol.read-audit.json" \
      '"code":"source-packet-output-mismatch"'
    assert_grep "incorrect packet output receives no packet credit" "$S/r4-sol.read-audit.json" \
      '"packet_shards":0'

    write_incorrect_artifact_transcript patch
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "same-length incorrect assigned patch output fails closed" "$?" 2
    assert_grep "incorrect assigned patch output has a stable violation" "$S/r4-sol.read-audit.json" \
      '"code":"assigned-patch-output-mismatch"'
    assert_grep "incorrect assigned patch output receives no patch credit" "$S/r4-sol.read-audit.json" \
      '"assigned_patch_reads":0'

    cat > "$S/r4-sol.stream.ndjson" <<'JSON'
{"type":"item.started","item":{"id":"s1","type":"command_execution","command":"sed -n '2,2p' src/x.ts"}}
{"type":"item.completed","item":{"id":"s1","type":"command_execution","command":"sed -n '2,2p' src/x.ts","aggregated_output":"changed\n","exit_code":0}}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "narrow transcript that skips an assigned packet fails closed" "$?" 2
    assert_grep "missing assigned packet has a stable code" "$S/r4-sol.read-audit.json" \
      '"code":"missing-source-packet"'

    python3 - "$S/r4-sol.stream.ndjson" "$packet" "$assigned_patch" "$evidence_index" <<'PY'
import json, sys
path, packet, assigned_patch, evidence_index = sys.argv[1:]
raw = open(packet).read(); command = "cat '" + packet + "'"
patch = open(assigned_patch).read(); patch_command = "sed -n '1,240p' '" + assigned_patch + "'"
index = open(evidence_index).read(); index_command = "cat '" + evidence_index + "'"
events = [
    {'type':'item.started','item':{'id':'p3','type':'command_execution','command':patch_command}},
    {'type':'item.completed','item':{'id':'p3','type':'command_execution','command':patch_command,
                                     'aggregated_output':patch,'exit_code':0}},
    {'type':'item.started','item':{'id':'p2','type':'command_execution','command':command}},
    {'type':'item.completed','item':{'id':'p2','type':'command_execution','command':command,
                                     'aggregated_output':raw,'exit_code':0}},
    {'type':'item.started','item':{'id':'index','type':'command_execution','command':index_command}},
    {'type':'item.completed','item':{'id':'index','type':'command_execution','command':index_command,
                                     'aggregated_output':index,'exit_code':0}},
    {'type':'item.started','item':{'id':'s1','type':'command_execution','command':"sed -n '2,2p' src/x.ts"}},
    {'type':'item.completed','item':{'id':'s1','type':'command_execution','command':"sed -n '2,2p' src/x.ts",
                                     'aggregated_output':'changed\n','exit_code':0}},
]
with open(path, 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json"
    assert_eq "packet plus bounded shell source range substantiates a finding" "$?" 0
    assert_grep "audit records tool-opened original source" "$S/r4-sol.read-audit.json" '"origin":"tool"'
    assert_grep "audit separates direct source reads from packet reads" "$S/r4-sol.read-audit.json" \
      '"packet_bytes":[1-9][0-9]*.*"source_read_calls":1'

    python3 - "$S/r4-sol.stream.ndjson" <<'PY'
import json, sys
path = sys.argv[1]
command = "sed -n '1,241p' src/x.ts"
events = [
    {'type':'item.started','item':{'id':'unused','type':'command_execution','command':command}},
    {'type':'item.completed','item':{'id':'unused','type':'command_execution','command':command,
                                     'aggregated_output':'one\nchanged\nthree\n','exit_code':0}},
]
with open(path, 'a') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "unused bounded-output exploration does not discard complete proof" "$?" 0
    assert_grep "unused unparseable exploration is recorded as advisory" \
      "$S/r4-sol.read-audit.json" '"advisories":\[[^]]*"code":"unbounded-shell-output"'
    assert_grep "unused exploration receives no source-range credit" \
      "$S/r4-sol.read-audit.json" '"opened_source_ranges":1'
    assert_grep "complete evidence with advisories has no fatal violation" \
      "$S/r4-sol.read-audit.json" '"violations":\[\]'

    python3 - "$S/r4-sol.json" <<'PY'
import json, sys
path = sys.argv[1]; doc = json.load(open(path)); doc['findings'][0]['line_start'] = 99; doc['findings'][0]['line_end'] = 99
json.dump(doc, open(path, 'w'))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "finding outside packet and opened source ranges fails closed" "$?" 2
    assert_grep "unsupported finding citation has a stable code" "$S/r4-sol.read-audit.json" \
      '"code":"unsubstantiated-finding-range"'

    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r4-sol.json"
    : > "$S/r4-sol.stream.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "zero-tool narrowed transcript fails closed" "$?" 2
    assert_grep "zero-tool transcript has a stable code" "$S/r4-sol.read-audit.json" \
      '"code":"no-recognized-review-tools"'

    printf '%s\n' '{"type":"future_provider_shape","payload":{}}' > "$S/r4-sol.stream.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "unrecognized provider transcript shape fails closed" "$?" 2
    assert_grep "provider shape drift has a stable code" "$S/r4-sol.read-audit.json" \
      '"code":"no-recognized-review-tools"'

    cat > "$S/r4-sol.stream.ndjson" <<'JSON'
{"type":"item.started","item":{"type":"command_execution","command":"sed -n '2,2p' src/x.ts"}}
{"type":"item.completed","item":{"type":"command_execution","command":"sed -n '2,2p' src/x.ts","aggregated_output":"changed\n","exit_code":0}}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r4-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r4-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "recognized call without a stable identifier fails closed" "$?" 2
    assert_grep "missing call identifier has a stable code" "$S/r4-sol.read-audit.json" \
      '"code":"missing-tool-call-id"'
  )
}

test_assigned_patch_chunk_coverage() {
  ( local R="$T/patch-chunks-root" S="$T/patch-chunks-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R/src/large.py" <<'PY'
import sys
with open(sys.argv[1], 'w') as stream:
    for index in range(310):
        stream.write(f'value_{index} = {index}\n')
PY
    local base manifest prompt
    base=$(git -C "$R" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/large.py\n' > "$S/files.txt"; printf 'src/large.py\n' > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    manifest=$(REV_PATCH_CHUNKS=0 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 8 --phase discovery) || return
    local bundle
    bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["sol"]["bundle"])' "$manifest") || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 8 sol "$bundle" patch-chunks --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r8-sol.json"

    write_patch_transcript() {
      python3 - "$manifest" "$S/r8-sol.stream.ndjson" "$1" "$R" <<'PY'
import json, pathlib, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2]); complete = sys.argv[3] == 'complete'
root = pathlib.Path(sys.argv[4])
session = pathlib.Path(sys.argv[1]).parent
seat = 'sol'; assignment = manifest['assignments'][seat]
events = []
def command(call_id, command, output):
    events.extend([
        {'type':'item.started','item':{'id':call_id,'type':'command_execution','command':command}},
        {'type':'item.completed','item':{'id':call_id,'type':'command_execution','command':command,
                                         'aggregated_output':output,'exit_code':0}},
    ])
patch = pathlib.Path(assignment['patch']); lines = patch.read_text().splitlines(keepends=True)
if sys.argv[3] == 'reversed':
    command('patch-2', "sed -n '241,480p' '" + str(patch) + "'", ''.join(lines[240:480]))
    command('patch-1', "sed -n '1,240p' '" + str(patch) + "'", ''.join(lines[:240]))
else:
    command('patch-1', "sed -n '1,240p' '" + str(patch) + "'", ''.join(lines[:240]))
    if complete:
        command('patch-2', "sed -n '241,480p' '" + str(patch) + "'", ''.join(lines[240:480]))
for index, shard in enumerate(manifest['source_context']['seats'][seat]['shards'], 1):
    path = session / shard['artifact']
    command('packet-' + str(index), "cat '" + str(path) + "'", path.read_text())
index = session / f"r{manifest['label']}-evidence.md"
command('evidence-index', "cat '" + str(index) + "'", index.read_text())
if manifest['source_context']['seats'][seat]['source_read_required']:
    source = root / 'src/large.py'
    command('source', "sed -n '1,240p' 'src/large.py'", ''.join(source.read_text().splitlines(keepends=True)[:240]))
with out.open('w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    }

    write_patch_transcript complete
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r8-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r8-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "two bounded reads can prove one assigned patch" "$?" 0
    assert_grep "assigned patch receipt records both proven chunks" "$S/r8-sol.read-audit.json" \
      '"assigned_patch_reads":2'
    assert_grep "assigned patch receipt covers the second chunk" "$S/r8-sol.read-audit.json" \
      '"line_start":241'

    write_claude_patch_overshoot() {
      python3 - "$manifest" "$S/r8-sol.stream.ndjson" "$1" "$R" <<'PY'
import json, pathlib, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2]); mode = sys.argv[3]
root = pathlib.Path(sys.argv[4]); session = pathlib.Path(sys.argv[1]).parent
seat = 'sol'; assignment = manifest['assignments'][seat]
events = []
def read(call_id, path, output, offset=None, limit=None):
    data = {'file_path': str(path)}
    if offset is not None:
        data.update(offset=offset, limit=limit)
    events.extend([
        {'type':'assistant','message':{'content':[{
            'type':'tool_use','id':call_id,'name':'Read','input':data}]}},
        {'type':'user','message':{'content':[{
            'type':'tool_result','tool_use_id':call_id,'content':output}]}},
    ])
patch = pathlib.Path(assignment['patch']); lines = patch.read_text().splitlines(keepends=True)
if mode == 'premature':
    read('patch-extra', patch,
         '<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>',
         999999, 240)
read('patch-1', patch, ''.join(lines[:240]), 1, 240)
read('patch-2', patch, ''.join(lines[240:480]), 241, 240)
if mode == 'complete':
    read('patch-extra', patch,
         '<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>',
         999999, 240)
for index, shard in enumerate(manifest['source_context']['seats'][seat]['shards'], 1):
    path = session / shard['artifact']
    read('packet-' + str(index), path, path.read_text())
index = session / f"r{manifest['label']}-evidence.md"
read('evidence-index', index, index.read_text())
if manifest['source_context']['seats'][seat]['source_read_required']:
    source = root / 'src/large.py'
    read('source', source, ''.join(source.read_text().splitlines(keepends=True)[:240]), 1, 240)
with out.open('w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    }

    write_claude_patch_overshoot complete
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r8-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r8-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "redundant Claude patch window after complete proof remains valid" "$?" 0
    assert_grep "redundant final patch window is retained as an advisory" \
      "$S/r8-sol.read-audit.json" \
      '"advisories":\[[^]]*"code":"redundant-assigned-patch-read"'
    assert_grep "redundant final patch window does not discard patch proof" \
      "$S/r8-sol.read-audit.json" '"assigned_patch_reads":2'

    write_claude_patch_overshoot premature
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r8-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r8-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "out-of-range Claude patch window before complete proof fails closed" "$?" 2
    assert_grep "premature out-of-range patch window remains a fatal violation" \
      "$S/r8-sol.read-audit.json" '"status":"invalid"'

    write_patch_transcript reversed
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r8-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r8-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "complete window patch ranges survive reversed read order" "$?" 0
    assert_grep "reversed window patch ranges retain an ordering advisory" \
      "$S/r8-sol.read-audit.json" '"advisories":\[[^]]*"code":"evidence-read-order"'
    assert_grep "reversed complete patch proof has no fatal violation" \
      "$S/r8-sol.read-audit.json" '"violations":\[\]'

    write_patch_transcript partial
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r8-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r8-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "assigned patch receipt rejects an uncovered trailing chunk" "$?" 2
    assert_grep "assigned patch gap has a stable violation" "$S/r8-sol.read-audit.json" \
      '"code":"missing-assigned-patch-range"'
  )
}

test_required_source_range_coverage() {
  ( local R="$T/required-source-root" S="$T/required-source-session"
    export GIT_CONFIG_GLOBAL="$T/gitconfig" GIT_CONFIG_NOSYSTEM=1
    [ -f "$T/gitconfig" ] || printf '[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n' > "$T/gitconfig"
    mkdir -p "$R" "$S"; git -C "$R" init -q --object-format=sha256
    printf 'a\n' > "$R/a.txt"; git -C "$R" add a.txt; git -C "$R" commit -qm init
    python3 - "$R/oversized.py" <<'PY'
import sys
with open(sys.argv[1], 'w') as stream:
    stream.write('def oversized():\n')
    for index in range(500):
        stream.write(f'    value_{index} = "{index:04d}-' + 'x' * 80 + '"\n')
    stream.write('    return value_499\n')
PY
    git -C "$R" add oversized.py && git -C "$R" commit -qm 'oversized baseline'
    local base; base=$(git -C "$R" rev-parse HEAD)
    python3 - "$R/oversized.py" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1]); text = path.read_text()
path.write_text(text.replace('value_400 =', 'value_400_changed ='))
PY
    git -C "$R" add oversized.py && git -C "$R" commit -qm 'reviewed oversized change'
    reviewed=$(git -C "$R" rev-parse HEAD)
    git -C "$R" checkout -q "$base"
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'oversized.py\n' > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    local manifest prompt
    manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 9 --head "$reviewed" --phase discovery) || return
    local bundle
    bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["sol"]["bundle"])' "$manifest") || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 9 sol "$bundle" required-source --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r9-sol.json"

    write_required_transcript() {
      python3 - "$manifest" "$S/r9-sol.stream.ndjson" "$1" "$R" <<'PY'
import json, pathlib, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2]); mode = sys.argv[3]
complete = mode != 'partial'
session = pathlib.Path(sys.argv[1]).parent; seat = 'sol'; context = manifest['source_context']['seats'][seat]
assert context['role'] == 'integration' and len(context['required_source_ranges']) == 1
events = []
def command(call_id, command, output):
    events.extend([
        {'type':'item.started','item':{'id':call_id,'type':'command_execution','command':command}},
        {'type':'item.completed','item':{'id':call_id,'type':'command_execution','command':command,
                                         'aggregated_output':output,'exit_code':0}},
    ])
patch = pathlib.Path(manifest['assignments'][seat]['patch']); patch_lines = patch.read_text().splitlines(keepends=True)
for start in range(1, len(patch_lines) + 1, 240):
    end = min(len(patch_lines), start + 239)
    command('patch-' + str(start), f"sed -n '{start},{end}p' '{patch}'",
            ''.join(patch_lines[start - 1:end]))
for index, shard in enumerate(context['shards'], 1):
    path = session / shard['artifact']
    command('packet-' + str(index), "cat '" + str(path) + "'", path.read_text())
required = context['required_source_ranges'][0]
segments = required['segments']
if not complete:
    segments = segments[:-1]
for position, segment in enumerate(segments):
    path = session / segment['artifact']
    output = path.read_text()
    if mode == 'bad-output' and position == 0:
        output = ('X' if output[:1] != 'X' else 'Y') + output[1:]
    if mode == 'partial' and position == 0:
        output = output.splitlines(keepends=True)[0]
        command('source-' + str(segment['index']), "sed -n '1,1p' '" + str(path) + "'", output)
    else:
        command('source-' + str(segment['index']), "cat '" + str(path) + "'", output)
if mode in ('duplicate', 'duplicate-partial'):
    path = session / segments[0]['artifact']
    if mode == 'duplicate-partial':
        command('source-duplicate', "sed -n '1,1p' '" + str(path) + "'",
                path.read_text().splitlines(keepends=True)[0])
    else:
        command('source-duplicate', "cat '" + str(path) + "'", path.read_text())
if mode == 'unassigned':
    path = session / 'r9-sol-source-segment-999-999.txt'; path.write_text('unassigned\n')
    command('source-unassigned', "cat '" + str(path) + "'", path.read_text())
index = session / f"r{manifest['label']}-evidence.md"
command('evidence-index', "cat '" + str(index) + "'", index.read_text())
if mode == 'live-window':
    live = (pathlib.Path(sys.argv[4]) / required['path']).read_text().splitlines(keepends=True)
    first = required['segments'][0]
    start = max(1, first['line_start'] - 1)
    end = min(len(live), first['line_end'] + 1, start + 239)
    assert (start, end) != (required['line_start'], required['line_end'])
    command('live-window', f"sed -n '{start},{end}p' '{required['path']}'",
            ''.join(live[start - 1:end]))
with out.open('w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    }

    write_required_transcript complete
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r9-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r9-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "integration seat proves an oversized required source range in bounded chunks" "$?" 0
    assert_grep "complete required source range increments the canonical counter" \
      "$S/r9-sol.read-audit.json" '"required_source_ranges_covered":1'
    assert_grep "required source proof records the exact manifest blob" \
      "$S/r9-sol.read-audit.json" '"required_source_range_proofs":\[\{"blob_oid":"[0-9a-f]+"'
    assert_grep "SHA-256 required source proof retains a 64-digit blob" \
      "$S/r9-sol.read-audit.json" '"required_source_range_proofs":\[\{"blob_oid":"[0-9a-f]{64}"'
    assert_grep "Codex keeps one required source segment per turn" "$prompt" \
      '^Required source segment batch limit: 1$'
    assert_grep "Codex reads required source through a session artifact" "$prompt" \
      '^Required source segment [0-9]+/[0-9]+: run cat -- .*-source-segment-[0-9]{3}-[0-9]{3}\.txt '
    assert_nogrep "Codex prompt exposes no detached Git repository command" "$prompt" \
      'git --git-dir=|evidence-repository'

    write_required_transcript live-window
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r9-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r9-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "a bounded live window may differ from a separately proven frozen range" "$?" 0
    assert_nogrep "live source bytes are not compared as one required frozen range" \
      "$S/r9-sol.read-audit.json" '"code":"required-source-output-mismatch"'
    assert_grep "prompt-named segment artifacts still prove the frozen range" \
      "$S/r9-sol.read-audit.json" '"required_source_ranges_covered":1'

    local terra_prompt terra_bundle
    terra_bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["terra"]["bundle"])' "$manifest") || return
    terra_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 9 terra "$terra_bundle" required-source \
      --evidence "$manifest") || return
    assert_grep "Terra uses the Codex artifact reader for required source" "$terra_prompt" \
      '^Required source segment [0-9]+/[0-9]+: run cat -- .*-source-segment-[0-9]{3}-[0-9]{3}\.txt '

    local opus_prompt opus_bundle
    opus_bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["opus"]["bundle"])' "$manifest") || return
    opus_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 9 opus "$opus_bundle" required-source \
      --evidence "$manifest") || return
    assert_grep "Claude uses its native reader for required source" "$opus_prompt" \
      '^Required source segment [0-9]+/[0-9]+: use Read to read .*-source-segment-[0-9]{3}-[0-9]{3}\.txt in full '

    cp "$S/roster.json" "$T/required-source-roster.json"
    python3 - "$S/roster.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1]); roster = json.loads(path.read_text())
roster['seats'][0]['adapter'] = 'claude'; path.write_text(json.dumps(roster))
PY
    local claude_manifest claude_prompt claude_bundle
    claude_manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare \
      "$S" 9c --head "$reviewed" --phase discovery) || return
    claude_bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["sol"]["bundle"])' "$claude_manifest") || return
    claude_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 9c sol "$claude_bundle" required-source \
      --evidence "$claude_manifest") || return
    assert_grep "Claude may batch two required source segments" "$claude_prompt" \
      '^Required source segment batch limit: 2$'
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r9c-sol.json"
    python3 - "$claude_manifest" "$S/r9c-sol.stream.ndjson" <<'PY'
import json, pathlib, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2])
required = manifest['source_context']['seats']['sol']['required_source_ranges'][0]
assert len(required['segments']) >= 3
uses = []; results = []
for segment in required['segments'][:3]:
    path = pathlib.Path(sys.argv[1]).parent / segment['artifact']
    call_id = 'source-' + str(segment['index'])
    uses.append({'type':'tool_use','id':call_id,'name':'Read','input':{'file_path':str(path)}})
    results.append({'type':'tool_result','tool_use_id':call_id,
                    'content':path.read_text()})
events = [
    {'type':'assistant','message':{'id':'real-claude-turn','content':uses}},
    {'type':'user','message':{'content':results}},
]
out.write_text(''.join(json.dumps(row) + '\n' for row in events))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r9c-sol.stream.ndjson" --prompt "$claude_prompt" --root "$R" --session "$S" \
      --out "$S/r9c-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "Claude rejects three required source segments in one real message" "$?" 2
    assert_grep "oversized Claude source batch has a stable violation" "$S/r9c-sol.read-audit.json" \
      '"code":"required-source-segment-batch-too-large"'
    cp "$T/required-source-roster.json" "$S/roster.json"

    python3 - "$S/roster.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1]); roster = json.loads(path.read_text())
roster['seats'][0]['adapter'] = 'gemini'; path.write_text(json.dumps(roster))
PY
    local gemini_manifest gemini_prompt gemini_bundle
    gemini_manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare \
      "$S" 9g --head "$reviewed" --phase discovery) || return
    gemini_bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["sol"]["bundle"])' "$gemini_manifest") || return
    gemini_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 9g sol "$gemini_bundle" required-source \
      --evidence "$gemini_manifest") || return
    assert_grep "Gemini uses its native reader for required source" "$gemini_prompt" \
      '^Required source segment [0-9]+/[0-9]+: use read_file to read .*-source-segment-[0-9]{3}-[0-9]{3}\.txt in full '
    cp "$T/required-source-roster.json" "$S/roster.json"

    write_required_transcript partial
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r9-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r9-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "integration seat rejects a gap in required source range coverage" "$?" 2
    assert_grep "missing required source range has a stable violation" "$S/r9-sol.read-audit.json" \
      '"code":"missing-required-source-range"'
    assert_grep "partial source artifact has a stable violation" "$S/r9-sol.read-audit.json" \
      '"code":"partial-required-source-segment"'
    assert_grep "partial required source range is not counted as covered" "$S/r9-sol.read-audit.json" \
      '"required_source_ranges_covered":0'

    local mode code
    for mode in bad-output duplicate duplicate-partial unassigned; do
      write_required_transcript "$mode"
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$S/r9-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
        --out "$S/r9-sol.read-audit.json" >/dev/null 2>&1
      local audit_rc=$?
      if [ "$mode" = duplicate ]; then
        assert_eq "duplicate completed required source read is advisory" "$audit_rc" 0
        assert_grep "duplicate completed required source read has a stable advisory" \
          "$S/r9-sol.read-audit.json" '"advisories":\[{"code":"duplicate-required-source-segment"'
        assert_nogrep "duplicate completed required source read is not a violation" \
          "$S/r9-sol.read-audit.json" '"violations":\[{"code":"duplicate-required-source-segment"'
        continue
      fi
      assert_eq "$mode required source artifact is rejected" "$audit_rc" 2
      case "$mode" in
        bad-output) code=required-source-output-mismatch ;;
        duplicate-partial) code=partial-required-source-segment ;;
        unassigned) code=unassigned-required-source-segment ;;
      esac
      assert_grep "$mode required source artifact has a stable violation" \
        "$S/r9-sol.read-audit.json" "\"code\":\"$code\""
    done

    python3 - "$manifest" "$S/r9-sol.stream.ndjson" "$R" <<'PY'
import json, pathlib, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2]); root = pathlib.Path(sys.argv[3])
context = manifest['source_context']['seats']['sol']; events = []
def command(call_id, command_text, output):
    events.extend([
        {'type':'item.started','item':{'id':call_id,'type':'command_execution','command':command_text}},
        {'type':'item.completed','item':{'id':call_id,'type':'command_execution','command':command_text,
                                         'aggregated_output':output,'exit_code':0}},
    ])
patch = pathlib.Path(manifest['assignments']['sol']['patch']); lines = patch.read_text().splitlines(keepends=True)
for start in range(1, len(lines) + 1, 240):
    end = min(len(lines), start + 239)
    command('patch-' + str(start), f"sed -n '{start},{end}p' '{patch}'", ''.join(lines[start - 1:end]))
for index, shard in enumerate(context['shards'], 1):
    path = pathlib.Path(sys.argv[1]).parent / shard['artifact']
    command('packet-' + str(index), "cat '" + str(path) + "'", path.read_text())
required = context['required_source_ranges'][0]
live = (root / required['path']).read_text().splitlines(keepends=True)
for segment in required['segments']:
    start, end = segment['line_start'], segment['line_end']
    command('wrong-tree-' + str(start), f"sed -n '{start},{end}p' '{required['path']}'",
            ''.join(live[start - 1:end]))
with out.open('w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r9-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r9-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "named-head review rejects matching path and lines from the wrong checked-out tree" "$?" 2
    assert_grep "wrong named-head tree has a stable provenance violation" "$S/r9-sol.read-audit.json" \
      '"code":"missing-required-source-segment"'
    assert_grep "wrong named-head tree produces no exact blob proof" "$S/r9-sol.read-audit.json" \
      '"required_source_range_proofs":\[\]'
  )
}

test_read_prompt_derived_authorization() {
  ( local R="$T/prompt-auth-root" S="$T/prompt-auth-session"
    mkdir -p "$R/docs" "$S"
    printf 'listed document\n' > "$R/docs/listed.md"
    printf 'unlisted document\n' > "$R/docs/unlisted.md"
    local P="$S/r21-sol.prompt.md" own_packet="$S/r21-sol-source-context-1.json"
    printf '{"ranges":[]}\n' > "$own_packet"
    printf 'sibling prompt\n' > "$S/r21-terra.prompt.md"
    printf '{"summary":"sibling","findings":[]}\n' > "$S/r21-terra.json"
    printf 'sibling findings\n' > "$S/findings.md"
    cat > "$P" <<EOF
## Scope
Assigned scope: full
Source context packet: $own_packet in full
Documents to review (read them in full):
- docs/listed.md
EOF
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r21-sol.json"

    read_payload() {
      python3 - "$1" <<'PY'
import json, sys
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':sys.argv[1]}}))
PY
    }
    post_payload() {
      python3 - "$1" <<'PY'
import json, sys
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':sys.argv[1]},
                  'tool_response':'visible result'}))
PY
    }
    write_auth_transcript() {
      python3 - "$S/auth.ndjson" "$1" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[2])
events = [
    {'type':'assistant','message':{'id':'auth-turn','content':[
        {'type':'tool_use','id':'auth-read','name':'Read','input':{'file_path':str(path)}}]}},
    {'type':'user','message':{'content':[
        {'type':'tool_result','tool_use_id':'auth-read','content':path.read_text()}]}},
]
pathlib.Path(sys.argv[1]).write_text(''.join(json.dumps(row) + '\n' for row in events))
PY
    }

    local allowed payload
    for allowed in "$P" "$own_packet" "$R/docs/listed.md"; do
      payload=$(read_payload "$allowed") || return
      read_bound_hook "$R" "$S" "$payload" "$P"
      assert_eq "prompt authorization hook permits $allowed" "$?" 0
      printf '%s' "$(post_payload "$allowed")" | post_bound_hook \
        --root "$R" --session "$S" --prompt "$P" > /dev/null 2> "$S/post.err"
      assert_eq "prompt authorization post-hook permits $allowed" "$?" 0
      write_auth_transcript "$allowed" || return
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude --raw "$S/auth.ndjson" \
        --prompt "$P" --root "$R" --session "$S" --out "$S/r21-sol.read-audit.json" \
        >/dev/null 2>&1
      assert_eq "prompt authorization transcript permits $allowed" "$?" 0
    done

    local sibling
    for sibling in "$S/r21-terra.prompt.md" "$S/r21-terra.json" "$S/findings.md"; do
      payload=$(read_payload "$sibling") || return
      printf '%s' "$payload" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
        --root "$R" --session "$S" --prompt "$P" > /dev/null 2> "$S/hook.err"
      assert_eq "prompt authorization hook rejects sibling $sibling" "$?" 2
      assert_grep "sibling hook refusal is explicit" "$S/hook.err" 'unnamed-session-artifact'
      printf '%s' "$(post_payload "$sibling")" | post_bound_hook \
        --root "$R" --session "$S" --prompt "$P" > /dev/null 2> "$S/post.err"
      assert_eq "prompt authorization post-hook rejects sibling $sibling" "$?" 2
      assert_grep "sibling post-hook refusal is explicit" "$S/post.err" 'unnamed-session-artifact'
      write_auth_transcript "$sibling" || return
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude --raw "$S/auth.ndjson" \
        --prompt "$P" --root "$R" --session "$S" --out "$S/r21-sol.read-audit.json" \
        >/dev/null 2>&1
      assert_eq "prompt authorization transcript rejects sibling $sibling" "$?" 2
      assert_grep "sibling transcript refusal is explicit" "$S/r21-sol.read-audit.json" \
        '"code":"unnamed-session-artifact"'
    done

    payload=$(read_payload "$R/docs/unlisted.md") || return
    printf '%s' "$payload" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
      --root "$R" --session "$S" --prompt "$P" > /dev/null 2> "$S/hook.err"
    assert_eq "prompt authorization hook requires a bound for an unlisted document" "$?" 2
    assert_grep "unlisted document hook refusal is explicit" "$S/hook.err" 'unbounded-read'
    printf '%s' "$(post_payload "$R/docs/unlisted.md")" | post_bound_hook \
      --root "$R" --session "$S" --prompt "$P" > /dev/null 2> "$S/post.err"
    assert_eq "prompt authorization post-hook requires a bound for an unlisted document" "$?" 2
    assert_grep "unlisted document post-hook refusal is explicit" "$S/post.err" 'unbounded-read'
    write_auth_transcript "$R/docs/unlisted.md" || return
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude --raw "$S/auth.ndjson" \
      --prompt "$P" --root "$R" --session "$S" --out "$S/r21-sol.read-audit.json" \
      >/dev/null 2>&1
    assert_eq "prompt authorization transcript requires a bound for an unlisted document" "$?" 2
    assert_grep "unlisted document transcript refusal is explicit" "$S/r21-sol.read-audit.json" \
      '"code":"unbounded-read"'
  )
}

test_read_command_classification_and_discovery_bounds() {
  ( local R="$T/read-command-root" S="$T/read-command-session"
    mkdir -p "$R/src" "$S"; printf 'value\n' > "$R/src/x.ts"
    printf 'Assigned scope: full\n' > "$S/prompt.md"
    python3 - "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, pathlib, sys

audit_path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('read_audit_contract', audit_path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
classified = (audit.SOURCE_COMMANDS | audit.UNSUPPORTED_FILE_COMMANDS |
              audit.METADATA_COMMANDS)
assert classified == audit.READONLY_POLICY.READ_CMDS
assert not (audit.SOURCE_COMMANDS & audit.UNSUPPORTED_FILE_COMMANDS)
assert not (audit.SOURCE_COMMANDS & audit.METADATA_COMMANDS)
assert not (audit.UNSUPPORTED_FILE_COMMANDS & audit.METADATA_COMMANDS)
PY
    assert_eq "every read-only shell command has one closed audit category" "$?" 0

    local payload
    payload='{"tool_name":"Bash","tool_input":{"command":"fd --max-results 80 . src"}}'
    read_bound_hook "$R" "$S" "$payload" "$S/prompt.md"
    assert_eq "fd native result cap accepts 80 results" "$?" 0
    payload='{"tool_name":"Bash","tool_input":{"command":"fd --max-results 81 . src"}}'
    read_bound_hook "$R" "$S" "$payload" "$S/prompt.md"
    assert_eq "fd native result cap rejects 81 results" "$?" 2
    payload='{"tool_name":"Bash","tool_input":{"command":"find src | head -80"}}'
    read_bound_hook "$R" "$S" "$payload" "$S/prompt.md"
    assert_eq "discovery pipeline accepts an 80-result limiter" "$?" 0
    payload='{"tool_name":"Bash","tool_input":{"command":"find src | head -81"}}'
    read_bound_hook "$R" "$S" "$payload" "$S/prompt.md"
    assert_eq "discovery pipeline rejects an 81-result limiter" "$?" 2
    payload='{"tool_name":"Bash","tool_input":{"command":"column src/x.ts"}}'
    printf '%s' "$payload" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" > /dev/null 2> "$S/column.err"
    assert_eq "unsupported file producer fails closed" "$?" 2
    assert_grep "unsupported file producer has a stable range violation" "$S/column.err" \
      'unsupported-source-range'

    python3 - <<'PY' | post_bound_hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" > /dev/null 2> "$S/glob.err"
import json
print(json.dumps({'tool_name':'Glob','tool_input':{'pattern':'**/*','path':'.'},
                  'tool_response':'\n'.join('src/file-' + str(i) for i in range(81))}))
PY
    assert_eq "post-hook rejects an unbounded Glob before counting results" "$?" 2
    assert_grep "post-hook Glob refusal is explicit" "$S/glob.err" 'unbounded-search'

    python3 - <<'PY' | post_bound_hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" >/dev/null 2> "$S/structured-bash.err"
import json
print(json.dumps({'tool_name':'Bash','tool_input':{'command':'rg -n retry src | head -80'},
                  'tool_response':{'interrupted':False,'isImage':False,'noOutputExpected':False,
                                   'stdout':'src/a.ts:1:retry\nsrc/b.ts:2:retry','stderr':''}}))
PY
    assert_eq "post-hook accepts a bounded structured Bash response" "$?" 0

    python3 - <<'PY' | post_bound_hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" >/dev/null 2> "$S/shell-overflow.err"
import json
print(json.dumps({'tool_name':'Bash','tool_input':{'command':'rg -n retry src | head -81'},
                  'tool_response':{'stdout':'\n'.join('src/x.ts:' + str(index) + ':retry'
                                                     for index in range(1, 82)),
                                   'stderr':''}}))
PY
    assert_eq "post-hook rejects the shell search overflow sentinel" "$?" 2
    assert_grep "shell search overflow has a stable diagnostic" "$S/shell-overflow.err" \
      'discovery-output-too-large'

    python3 - <<'PY' | post_bound_hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" >/dev/null 2> "$S/structured-grep.err"
import json
files = ['src/file-' + str(index) for index in range(81)]
print(json.dumps({'tool_name':'Grep','tool_input':{'pattern':'retry','path':'src','head_limit':80,
                                                  'output_mode':'files_with_matches'},
                  'tool_response':{'filenames':files,'mode':'files_with_matches','numFiles':81,
                                   'totalFiles':81,'truncated':False}}))
PY
    assert_eq "post-hook rejects 81 structured Grep filenames" "$?" 2
    assert_grep "structured Grep overflow is explicit" "$S/structured-grep.err" \
      'discovery-output-too-large'

    python3 - <<'PY' | post_bound_hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" >/dev/null 2> "$S/structured-read.err"
import json
content = '\\' * 20000
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':'src/x.ts','offset':1,'limit':1},
                  'tool_response':{'type':'text','file':{'content':content,'filePath':'src/x.ts',
                                                       'numLines':1,'startLine':1,'totalLines':1}}}))
PY
    assert_eq "post-hook measures structured Read text instead of JSON escaping" "$?" 0

    python3 - <<'PY' | post_bound_hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" >/dev/null 2> "$S/unknown-response.err"
import json
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':'src/x.ts','offset':1,'limit':1},
                  'tool_response':{'unexpected':'shape'}}))
PY
    assert_eq "post-hook rejects an unknown structured response" "$?" 2
    assert_grep "unknown hook response has a distinct diagnostic" "$S/unknown-response.err" \
      'unsupported-hook-response'

    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r23-sol.json"
    python3 - "$S/glob.ndjson" <<'PY'
import json, pathlib, sys
output = '\n'.join('src/file-' + str(i) for i in range(81))
events = [
    {'type':'assistant','message':{'id':'glob-turn','content':[
        {'type':'tool_use','id':'glob-call','name':'Glob',
         'input':{'pattern':'**/*','path':'.'}}]}},
    {'type':'user','message':{'content':[
        {'type':'tool_result','tool_use_id':'glob-call','content':output}]}},
]
pathlib.Path(sys.argv[1]).write_text(''.join(json.dumps(row) + '\n' for row in events))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude --raw "$S/glob.ndjson" \
      --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$S/r23-sol.read-audit.json" \
      >/dev/null 2>&1
    assert_eq "transcript audit rejects more than 80 discovery results" "$?" 2
    assert_grep "transcript discovery overflow is explicit" "$S/r23-sol.read-audit.json" \
      '"code":"discovery-output-too-large"'
  )
}

test_read_source_packets_share_turn_byte_cap() {
  ( local R="$T/source-packet-cap-root" S="$T/source-packet-cap-session"
    mkdir -p "$R" "$S"
    local P="$S/r22-sol.prompt.md" first="$S/r22-sol-source-context-1.json"
    local second="$S/r22-sol-source-context-2.json"
    python3 - "$first" "$second" <<'PY'
import pathlib, sys
for index, name in enumerate(sys.argv[1:], 1):
    pathlib.Path(name).write_text('{"packet":' + '"' + chr(96 + index) * 17390 + '"}\n')
PY
    cat > "$P" <<EOF
## Scope
Assigned scope: full
Source context packet: $first in full
Source context packet: $second in full
EOF
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r22-sol.json"
    python3 - "$S/packets.ndjson" "$first" "$second" <<'PY'
import json, pathlib, sys
paths = [pathlib.Path(value) for value in sys.argv[2:]]
uses = [{'type':'tool_use','id':'packet-' + str(index),'name':'Read',
         'input':{'file_path':str(path)}} for index, path in enumerate(paths, 1)]
results = [{'type':'tool_result','tool_use_id':'packet-' + str(index),
            'content':path.read_text()} for index, path in enumerate(paths, 1)]
events = [
    {'type':'assistant','message':{'id':'one-packet-turn','content':uses}},
    {'type':'user','message':{'content':results}},
]
pathlib.Path(sys.argv[1]).write_text(''.join(json.dumps(row) + '\n' for row in events))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude --raw "$S/packets.ndjson" \
      --prompt "$P" --root "$R" --session "$S" --out "$S/r22-sol.read-audit.json" \
      >/dev/null 2>&1
    assert_eq "two source packets over 32 KiB cannot share one Claude turn" "$?" 2
    assert_grep "source packet batch uses the ordinary turn byte cap" "$S/r22-sol.read-audit.json" \
      '"code":"tool-turn-output-too-large"'
    assert_nogrep "assigned source packets do not fail prompt authorization" \
      "$S/r22-sol.read-audit.json" '"code":"unnamed-session-artifact"'
    assert_grep "both source packet reads are assigned to one tool turn" \
      "$S/r22-sol.read-audit.json" '"tool_turns":1'
  )
}

test_read_audit_reuses_source_file_cache() {
  ( local R="$T/source-cache-root" S="$T/source-cache-session"
    mkdir -p "$R/src" "$S"
    printf 'one\ntwo\nthree\nfour\n' > "$R/src/x.ts"
    printf 'Assigned scope: full\n' > "$S/prompt.md"
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/rcache-sol.json"
    cat > "$S/cache.ndjson" <<'JSON'
{"type":"item.started","item":{"id":"first","type":"command_execution","command":"sed -n '1,2p' src/x.ts"}}
{"type":"item.completed","item":{"id":"first","type":"command_execution","command":"sed -n '1,2p' src/x.ts","aggregated_output":"one\ntwo\n","exit_code":0}}
{"type":"item.started","item":{"id":"second","type":"command_execution","command":"sed -n '3,4p' src/x.ts"}}
{"type":"item.completed","item":{"id":"second","type":"command_execution","command":"sed -n '3,4p' src/x.ts","aggregated_output":"three\nfour\n","exit_code":0}}
JSON
    local proof
    proof=$(python3 - "$SCRIPTS/lib/review-read-audit.py" "$R" "$S" <<'PY'
import argparse, importlib.util, pathlib, sys

script, root, session = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
spec = importlib.util.spec_from_file_location('read_audit_cache', script)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
source = (root / 'src/x.ts').resolve()
original = pathlib.Path.read_bytes
reads = 0
def counted(path):
    global reads
    if path.resolve() == source:
        reads += 1
    return original(path)
pathlib.Path.read_bytes = counted
try:
    rc = audit.audit(argparse.Namespace(
        adapter='codex', raw=str(session / 'cache.ndjson'),
        prompt=str(session / 'prompt.md'), root=str(root), session=str(session),
        deps=None, out=str(session / 'rcache-sol.read-audit.json')))
finally:
    pathlib.Path.read_bytes = original
print(rc, reads)
PY
) || return
    assert_eq "one audit reads a repeatedly windowed worktree source file once" "$proof" "0 1"
  )
}

test_read_audit_shell_range_hardening() {
  ( local R="$T/shell-range-root" S="$T/shell-range-session"
    mkdir -p "$R/src" "$S"; printf 'one\ntwo\n' > "$R/src/x.ts"
    local wrapped='{"tool_name":"Bash","tool_input":{"command":"/bin/zsh -lc '\''git diff HEAD | head -240'\''"}}'
    read_bound_hook "$R" "$S" "$wrapped"
    assert_eq "Codex zsh wrapper validates its safe unwrapped command" "$?" 0

    local redirected='{"tool_name":"Bash","tool_input":{"command":"cat </etc/hosts | head -20"}}'
    local unresolved='{"tool_name":"Bash","tool_input":{"command":"cat $ADAPTER_ONLY_SECRET | head -20"}}'
    local opaque_range='{"tool_name":"Bash","tool_input":{"command":"awk '\''NR >= 1 && NR <= 20'\'' src/x.ts | head -20"}}'
    local transformed_range='{"tool_name":"Bash","tool_input":{"command":"cat src/x.ts | grep one | head -20"}}'
    local multiple_sources='{"tool_name":"Bash","tool_input":{"command":"cat src/x.ts src/x.ts | head -20"}}'
    local negated_unbounded='{"tool_name":"Bash","tool_input":{"command":"! cat src/x.ts"}}'
    local nested_prefix_unbounded='{"tool_name":"Bash","tool_input":{"command":"env LC_ALL=C command cat src/x.ts"}}'
    local prefix_assignment_unbounded='{"tool_name":"Bash","tool_input":{"command":"time LC_ALL=C cat src/x.ts"}}'
    local transformed_numbered_source='{"tool_name":"Bash","tool_input":{"command":"nl -ba src/x.ts | sed -n '\''1,2p'\''"}}'
    for payload in "$redirected" "$unresolved" "$opaque_range" "$transformed_range" "$multiple_sources" \
        "$negated_unbounded" "$nested_prefix_unbounded" "$prefix_assignment_unbounded" \
        "$transformed_numbered_source"; do
      read_bound_hook "$R" "$S" "$payload"
      assert_eq "range audit rejects unsafe or unparseable shell evidence: $payload" "$?" 2
    done
    local ambiguous_overlong
    ambiguous_overlong=$(python3 - <<'PY'
import json
print(json.dumps({'tool_name':'Bash','tool_input':{
    'command':"rg '" + 'x' * 10000 + "' src | head -80"}}))
PY
)
    read_bound_hook "$R" "$S" "$ambiguous_overlong"
    assert_eq "ambiguous overlong search token is treated as a non-path" "$?" 0
    local explicit_overlong
    explicit_overlong=$(python3 - <<'PY'
import json
print(json.dumps({'tool_name':'Bash','tool_input':{
    'command':"cat './" + 'x' * 10000 + "' | head -20"}}))
PY
)
    read_bound_hook "$R" "$S" "$explicit_overlong"
    assert_eq "explicit overlong path fails closed" "$?" 2

    local native_search='{"tool_name":"Bash","tool_input":{"command":"rg -n -m 80 retry src"}}'
    read_bound_hook "$R" "$S" "$native_search"
    assert_eq "native rg max-count satisfies the search result bound" "$?" 0
    local wide_native_search='{"tool_name":"Bash","tool_input":{"command":"rg -n -m 81 retry src"}}'
    read_bound_hook "$R" "$S" "$wide_native_search"
    assert_eq "native rg max-count rejects more than 80 results" "$?" 2

    local quoted_search_pattern='{"tool_name":"Bash","tool_input":{"command":"grep -n '\''rm -f \"\\$S\"/r6-\\*'\'' plugins/review-council/tests/t-profile.sh | head -40"}}'
    read_bound_hook "$R" "$S" "$quoted_search_pattern"
    assert_eq "quoted grep pattern is not mistaken for an unresolved path" "$?" 0
  )
}

test_codex_multirange_source_batch_contract() {
  ( local R="$T/codex-source-batch-root" S="$T/codex-source-batch-session"
    mkdir -p "$R/src" "$S"
    python3 - "$R/src/a.ts" "$R/src/b.ts" <<'PY'
import pathlib, sys
for path, prefix in zip(sys.argv[1:], ('a', 'b')):
    pathlib.Path(path).write_text(''.join(f'{prefix}{index:03d}:' + 'x' * 160 + '\n' for index in range(1, 261)))
PY
    printf 'Codex source batching enabled: true\nAssigned scope: full\n' > "$S/prompt.md"

    write_codex_batch() {
      python3 - "$S/$1.ndjson" "$R" "$2" "$3" <<'PY'
import json, pathlib, subprocess, sys
out, root, command, mode = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
completed = subprocess.run(command, cwd=root, shell=True, text=True, capture_output=True)
output = completed.stdout
if mode == 'mismatch':
    output = output[:-1] + ('Z' if output else 'Z')
rows = [
    {'type':'item.started','item':{'id':'batch','type':'command_execution','command':command}},
    {'type':'item.completed','item':{'id':'batch','type':'command_execution','command':command,
                                    'aggregated_output':output,'exit_code':completed.returncode}},
]
out.write_text(''.join(json.dumps(row) + '\n' for row in rows))
PY
    }
    audit_codex_batch() {
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex --raw "$S/$1.ndjson" \
        --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$S/$1-audit.json" \
        >/dev/null 2>&1
    }

    local good="sed -n '1,80p' 'src/a.ts'; sed -n '121,200p' 'src/b.ts'"
    write_codex_batch good "$good" exact || return
    audit_codex_batch good
    local good_rc=$?
    assert_eq "Codex accepts two pure bounded source windows in one Bash call" "$good_rc" 0
    assert_grep "Codex batch proves both exact source ranges" "$S/good-audit.json" \
      '"opened_source_ranges":2'
    assert_grep "Codex audit counts one multirange source batch" "$S/good-audit.json" \
      '"source_read_batches":1'
    assert_grep "Codex batch remains one source read call" "$S/good-audit.json" \
      '"source_read_calls":1'

    local wrapped="/bin/sh -lc \"$good\""
    write_codex_batch wrapped "$wrapped" exact || return
    audit_codex_batch wrapped
    assert_eq "Codex accepts the live shell-wrapped source batch envelope" "$?" 0
    assert_grep "Codex counts a live shell-wrapped source batch" "$S/wrapped-audit.json" \
      '"source_read_batches":1'

    printf 'Codex source batching enabled: false\nAssigned scope: full\n' > "$S/prompt.md"
    audit_codex_batch good
    assert_eq "Codex source batching stays disabled unless the frozen prompt opts in" "$?" 2
    assert_grep "disabled Codex source batching fails closed" "$S/good-audit.json" \
      '"code":"unsupported-source-batch"'
    printf 'Codex source batching enabled: true\nAssigned scope: full\n' > "$S/prompt.md"

    local bad label code
    while IFS='~' read -r label bad code; do
      write_codex_batch "$label" "$bad" exact || return
      audit_codex_batch "$label"
      assert_eq "Codex rejects unsafe source batch $label" "$?" 2
      assert_grep "Codex source batch $label has a stable violation" "$S/$label-audit.json" \
        "\"code\":\"$code\""
    done <<'CASES'
conditional~sed -n '1,80p' 'src/a.ts' && sed -n '121,200p' 'src/b.ts'~unsupported-source-batch
wide-total~sed -n '1,121p' 'src/a.ts'; sed -n '121,241p' 'src/b.ts'~source-batch-lines-too-large
overlap~sed -n '1,80p' 'src/a.ts'; sed -n '80,120p' 'src/a.ts'~overlapping-source-batch
mixed-search~sed -n '1,80p' 'src/a.ts'; rg -n 'never-matches' src | head -80~unsupported-source-batch
mixed-output~sed -n '1,80p' 'src/a.ts'; printf marker; sed -n '121,160p' 'src/b.ts'~unsupported-source-batch
variable-path~sed -n '1,80p' "$FILE"; sed -n '121,160p' 'src/b.ts'~unsupported-source-batch
CASES

    write_codex_batch mismatch "$good" mismatch || return
    audit_codex_batch mismatch
    assert_eq "Codex rejects a multirange output with one changed byte" "$?" 2
    assert_grep "Codex multirange mismatch is fatal" "$S/mismatch-audit.json" \
      '"code":"source-batch-output-mismatch"'

    local overflow="sed -n '1,130p' 'src/a.ts'; sed -n '131,240p' 'src/b.ts'"
    write_codex_batch overflow "$overflow" exact || return
    audit_codex_batch overflow
    assert_eq "Codex rejects exact multirange output above 32 KiB" "$?" 2
    assert_grep "Codex multirange overflow is fatal" "$S/overflow-audit.json" \
      '"code":"tool-output-too-large"'

    # Historical Grok shell transcripts remain rejected by the compatibility decoder.
    python3 - "$S/grok.ndjson" "$R" "$good" <<'PY'
import json, pathlib, subprocess, sys
out, root, command = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
result = subprocess.run(command, cwd=root, shell=True, text=True, capture_output=True)
rows = [
 {'type':'tool_call','toolCallId':'batch','toolName':'run_terminal_command','rawInput':{'command':command}},
 {'type':'tool_call_update','toolCallId':'batch','status':'completed','rawOutput':result.stdout},
]
out.write_text(''.join(json.dumps(row) + '\n' for row in rows))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok --raw "$S/grok.ndjson" \
      --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$S/grok-audit.json" \
      >/dev/null 2>&1
    assert_eq "non-Codex adapters reject a multi-producer Bash call" "$?" 2
    assert_grep "non-Codex source batch has a stable violation" "$S/grok-audit.json" \
      '"code":"unsupported-source-batch"'
  )
}

test_read_transcript_audit_contract() {
  # Historical Grok transcripts remain in the cross-adapter decoder contract.
  ( local R="$T/audit-root" S="$T/audit-session"
    mkdir -p "$R/src" "$S"
    printf 'x\n' > "$R/src/x.ts"
    printf 'Assigned scope: full\n' > "$S/prompt.md"

    cat > "$S/codex-ok.ndjson" <<'JSON'
{"type":"item.started","item":{"id":"c1","type":"command_execution","command":"sed -n '1,120p' src/x.ts"}}
{"type":"item.completed","item":{"id":"c1","type":"command_execution","command":"sed -n '1,120p' src/x.ts","aggregated_output":"x\n","exit_code":0}}
JSON
    cat > "$S/grok-ok.ndjson" <<'JSON'
{"type":"tool_call","toolCallId":"g1","toolName":"read_file","rawInput":{"target_file":"src/x.ts","offset":1,"limit":120}}
{"type":"tool_call_update","toolCallId":"g1","status":"completed","rawOutput":"x\n"}
JSON
    cat > "$S/gemini-ok.ndjson" <<'JSON'
{"type":"tool_use","tool_id":"m1","tool_name":"read_file","parameters":{"path":"src/x.ts","offset":1,"limit":120}}
{"type":"tool_result","tool_id":"m1","status":"success","output":"x\n"}
JSON
    cat > "$S/claude-ok.ndjson" <<'JSON'
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"a1","name":"Read","input":{"file_path":"src/x.ts","offset":1,"limit":120}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a1","content":"x\n"}]}}
JSON
    cp "$S/claude-ok.ndjson" "$S/agent-ok.ndjson"
    local adapter raw out
    for adapter in codex grok gemini claude agent; do
      raw="$S/$adapter-ok.ndjson"; out="$S/$adapter-audit.json"
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" --raw "$raw" \
        --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$out"
      assert_eq "$adapter bounded transcript passes" "$?" 0
      assert_grep "$adapter audit is valid" "$out" '"status":"valid"'
      assert_grep "$adapter audit binds prompt hash" "$out" '"prompt_sha256":"[0-9a-f]{64}"'
      assert_grep "$adapter audit binds stream hash" "$out" '"stream_sha256":"[0-9a-f]{64}"'
      assert_grep "$adapter audit marks full-scope review" "$out" '"narrow":false'
      assert_grep "$adapter audit records tool turns" "$out" '"tool_turns":1'
      assert_grep "$adapter audit records output bytes" "$out" '"tool_output_bytes":2'
    done

    cat > "$S/codex-bad.ndjson" <<'JSON'
{"type":"item.started","item":{"id":"c2","type":"command_execution","command":"cat ~/.claude/projects/example/memory/decision-profile.md"}}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex --raw "$S/codex-bad.ndjson" \
      --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$S/bad-audit.json" >/dev/null 2>&1
    assert_eq "outside unbounded transcript fails closed" "$?" 2
    assert_grep "invalid audit is published" "$S/bad-audit.json" '"status":"invalid"'
    assert_grep "invalid audit names the stable violation code" "$S/bad-audit.json" '"code":"path-outside-scope"'

    printf '{bad json}\n' > "$S/malformed.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok --raw "$S/malformed.ndjson" \
      --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$S/malformed-audit.json" >/dev/null 2>&1
    assert_eq "malformed narrowed transcript fails closed" "$?" 2
    assert_grep "malformed transcript is diagnosed" "$S/malformed-audit.json" '"code":"malformed-transcript"'

    python3 - "$S/grok-large.ndjson" <<'PY'
import json, sys
events = [
    {'type': 'tool_call', 'toolCallId': 'large', 'toolName': 'read_file',
     'rawInput': {'target_file': 'src/x.ts', 'offset': 1, 'limit': 16}},
    {'type': 'tool_call_update', 'toolCallId': 'large', 'status': 'completed',
     'rawOutput': 'x' * 32769},
]
with open(sys.argv[1], 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok --raw "$S/grok-large.ndjson" \
      --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$S/large-audit.json" >/dev/null 2>&1
    assert_eq "long-line tool output fails the byte cap" "$?" 2
    assert_grep "byte-cap violation is explicit" "$S/large-audit.json" '"code":"tool-output-too-large"'
    assert_grep "actual oversized byte count is recorded" "$S/large-audit.json" '"max_tool_output_bytes":32769'

    python3 - "$S/claude-batch.ndjson" <<'PY'
import json, sys
events = [
    {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'id': 'b1', 'name': 'Read', 'input': {'file_path': 'src/x.ts', 'offset': 1, 'limit': 8}},
        {'type': 'tool_use', 'id': 'b2', 'name': 'Read', 'input': {'file_path': 'src/x.ts', 'offset': 9, 'limit': 8}},
    ]}},
    {'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': 'b1', 'content': 'a' * 20000},
        {'type': 'tool_result', 'tool_use_id': 'b2', 'content': 'b' * 20000},
    ]}},
]
with open(sys.argv[1], 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude --raw "$S/claude-batch.ndjson" \
      --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$S/batch-audit.json" >/dev/null 2>&1
    assert_eq "combined parallel output over 32 KiB fails" "$?" 2
    assert_grep "combined turn cap is explicit" "$S/batch-audit.json" '"code":"tool-turn-output-too-large"'
    assert_grep "parallel calls count as one tool turn" "$S/batch-audit.json" '"tool_turns":1'

    python3 - <<'PY' | post_bound_hook --root "$R" --session "$S" >/dev/null 2>&1
import json
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':'src/x.ts','offset':1,'limit':1},'tool_response':'x' * 32769}))
PY
    assert_eq "post-tool hook rejects an oversized response" "$?" 2
  )
}

test_read_audit_rejects_unknown_tools() {
  python3 - "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('review_read_audit', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
root = pathlib.Path('/repo'); session = pathlib.Path('/session')
unknown = module.validate_call('web_fetch', {}, [root], root, session)
assert unknown == [{'code':'unrecognized-review-tool', 'tool':'web_fetch'}]
legacy_list = module.validate_call('list_dir', {}, [root], root, session)
assert legacy_list == [{'code':'unrecognized-review-tool', 'tool':'list_dir'}]
assert module.validate_call('StructuredOutput', {}, [root], root, session) == []
PY
  assert_eq "unknown and legacy Grok tools fail closed while terminal schema output is allowed" "$?" 0
}

test_claude_hook_line_counts_and_nonexecuted_exploration() {
  ( local R="$T/claude-hook-root" S="$T/claude-hook-session"
    mkdir -p "$R/src" "$S"
    printf 'one\ntwo\n' > "$R/src/x.ts"
    printf 'Assigned scope: full\n' > "$S/prompt.md"

    python3 - "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('review_read_audit', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

def response(content, count, total=None):
    return {'type':'text', 'file':{'content':content, 'filePath':'src/x.ts',
            'numLines':count, 'startLine':1, 'totalLines':count if total is None else total}}

assert module.claude_hook_output('Read', response('one\ntwo\n', 3))[1] == 3
assert module.claude_hook_output('Read', response('one\ntwo\n', 2))[1] == 2
assert module.claude_hook_output('Read', response('', 1))[1] == 1
assert module.claude_hook_output('Read', response('one\ntwo', 2))[1] == 2
try:
    module.claude_hook_output('Read', response('one\ntwo\n', 4))
except ValueError:
    pass
else:
    raise AssertionError('mismatched provider line count was accepted')
PY
    assert_eq "Claude hook accepts provider and logical terminal-LF counts only" "$?" 0

    python3 - <<'PY' | post_bound_hook \
      --root "$R" --session "$S" --prompt "$S/prompt.md" >/dev/null 2> "$S/truncated.err"
import json
print(json.dumps({'tool_name':'Grep',
                  'tool_input':{'pattern':'one','path':'src','head_limit':80},
                  'tool_response':{'content':'src/x.ts:1:one','mode':'content',
                                   'numLines':1,'totalLines':1,'truncated':True}}))
PY
    assert_eq "Claude hook preserves the truncated-search overflow signal" "$?" 2
    assert_grep "truncated Claude search remains over the result cap" "$S/truncated.err" \
      'discovery-output-too-large'

    python3 - "$S/nonexecuted.ndjson" <<'PY'
import json, pathlib, sys
rows = [
 {'type':'assistant','message':{'content':[
  {'type':'tool_use','id':'denied-read','name':'Read','input':{'file_path':'src/x.ts'}},
  {'type':'tool_use','id':'denied-grep','name':'Grep','input':{'pattern':'one','path':'src'}},
  {'type':'tool_use','id':'ordinary','name':'Read','input':{'file_path':'src/x.ts','offset':1,'limit':2}},
 ]}},
 {'type':'user','tool_result_meta':[
  {'id':'denied-read','non_execution_kind':'permission-rule'},
  {'id':'denied-grep','non_execution_kind':'permission-rule'},
 ],'message':{'content':[
  {'type':'tool_result','tool_use_id':'denied-read','is_error':True,
   'content':'PreToolUse:Read hook error: review read blocked: unbounded-read\n'},
  {'type':'tool_result','tool_use_id':'denied-grep','is_error':True,
   'content':'PreToolUse:Grep hook error: review read blocked: unbounded-search\n'},
  {'type':'tool_result','tool_use_id':'ordinary','content':'1\tone\n2\ttwo\n3\t'},
 ]}},
]
pathlib.Path(sys.argv[1]).write_text(''.join(json.dumps(row) + '\n' for row in rows))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/nonexecuted.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/nonexecuted-audit.json" >/dev/null 2>&1
    assert_eq "confirmed nonexecuted Claude Read and Grep calls are omitted" "$?" 0
    assert_grep "only the executed Claude read counts" "$S/nonexecuted-audit.json" \
      '"tool_calls":1'

    sed 's/"id": "denied-read", "non_execution_kind": "permission-rule"/"id": "other-read", "non_execution_kind": "permission-rule"/' \
      "$S/nonexecuted.ndjson" > "$S/mismatched-denial.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/mismatched-denial.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/mismatched-denial-audit.json" >/dev/null 2>&1
    assert_eq "mismatched Claude denial metadata does not suppress a failed read" "$?" 2
    assert_grep "mismatched Claude denial keeps its call violation" \
      "$S/mismatched-denial-audit.json" '"code":"unbounded-read"'

    sed 's/PreToolUse:Read hook error: /permission denied: /' \
      "$S/nonexecuted.ndjson" > "$S/generic-denial.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/generic-denial.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/generic-denial-audit.json" >/dev/null 2>&1
    assert_eq "generic failed Claude reads do not bypass call validation" "$?" 2
    assert_grep "generic failed Claude read keeps its bound failure" \
      "$S/generic-denial-audit.json" '"code":"unbounded-read"'

    python3 - "$S/denied-bash.ndjson" <<'PY'
import json, pathlib, sys
rows = [
 {'type':'assistant','message':{'content':[
  {'type':'tool_use','id':'denied-bash','name':'Bash','input':{'command':'ls'}},
  {'type':'tool_use','id':'ordinary','name':'Read','input':{'file_path':'src/x.ts','offset':1,'limit':2}},
 ]}},
 {'type':'user','tool_result_meta':[
  {'id':'denied-bash','non_execution_kind':'permission-rule'},
 ],'message':{'content':[
  {'type':'tool_result','tool_use_id':'denied-bash','is_error':True,
   'content':'PreToolUse:Bash hook error: review read blocked: unbounded-shell-output\n'},
  {'type':'tool_result','tool_use_id':'ordinary','content':'1\tone\n2\ttwo\n3\t'},
 ]}},
]
pathlib.Path(sys.argv[1]).write_text(''.join(json.dumps(row) + '\n' for row in rows))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/denied-bash.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/denied-bash-audit.json" >/dev/null 2>&1
    assert_eq "provider-confirmed nonexecuted safe Bash is omitted" "$?" 0
    assert_grep "omitted safe Bash earns no tool-call proof" "$S/denied-bash-audit.json" \
      '"tool_calls":1'
    assert_nogrep "omitted safe Bash earns no shell violation" "$S/denied-bash-audit.json" \
      '"code":"unbounded-shell-output"'

    sed 's/"id": "denied-bash", "non_execution_kind": "permission-rule"/"id": "other-bash", "non_execution_kind": "permission-rule"/' \
      "$S/denied-bash.ndjson" > "$S/mismatched-bash-denial.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/mismatched-bash-denial.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/mismatched-bash-denial-audit.json" >/dev/null 2>&1
    assert_eq "mismatched safe Bash denial metadata remains fatal" "$?" 2
    assert_grep "mismatched safe Bash denial keeps its call violation" \
      "$S/mismatched-bash-denial-audit.json" '"code":"unbounded-shell-output"'

    sed 's/PreToolUse:Bash hook error: /permission denied: /' \
      "$S/denied-bash.ndjson" > "$S/generic-bash-denial.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/generic-bash-denial.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/generic-bash-denial-audit.json" >/dev/null 2>&1
    assert_eq "generic safe Bash denial text remains fatal" "$?" 2
    assert_grep "generic safe Bash denial keeps its call violation" \
      "$S/generic-bash-denial-audit.json" '"code":"unbounded-shell-output"'

    sed 's/"command": "ls"/"command": "git commit -m x"/' \
      "$S/denied-bash.ndjson" > "$S/unsafe-bash-denial.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/unsafe-bash-denial.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/unsafe-bash-denial-audit.json" >/dev/null 2>&1
    assert_eq "provider-confirmed write-capable Bash remains fatal" "$?" 2
    assert_grep "unsafe Bash denial keeps its policy violation" \
      "$S/unsafe-bash-denial-audit.json" '"code":"unsupported-shell-command"'
  )
}

test_read_audit_binds_delivered_output() {
  # Historical Grok transcripts remain in output-binding and normalization coverage.
  ( local R="$T/output-binding-root" S="$T/output-binding-session"
    mkdir -p "$R/src" "$S"
    printf 'one\ntwo\nthree\n' > "$R/src/x.ts"
    printf 'Assigned scope: full\n' > "$S/prompt.md"

    cat > "$S/codex.ndjson" <<'JSON'
{"type":"item.started","item":{"id":"c1","type":"command_execution","command":"sed -n '1,3p' src/x.ts"}}
{"type":"item.completed","item":{"id":"c1","type":"command_execution","command":"sed -n '1,3p' src/x.ts","aggregated_output":"one\ntwo\nthree\n","exit_code":0}}
JSON
    cat > "$S/grok.ndjson" <<'JSON'
{"type":"tool_call","toolCallId":"g1","toolName":"read_file","rawInput":{"target_file":"src/x.ts","offset":1,"limit":3}}
{"type":"tool_call_update","toolCallId":"g1","status":"completed","rawOutput":{"type":"ReadFile","FileContent":{"content":"1→one\ntwo\nthree","total_lines":3}}}
JSON
    cat > "$S/gemini.ndjson" <<'JSON'
{"type":"tool_use","tool_id":"m1","tool_name":"read_file","parameters":{"path":"src/x.ts","offset":1,"limit":3}}
{"type":"tool_result","tool_id":"m1","status":"success","output":"one\ntwo\nthree\n"}
JSON
    cat > "$S/claude.ndjson" <<'JSON'
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"a1","name":"Read","input":{"file_path":"src/x.ts","offset":1,"limit":3}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a1","content":"1\tone\n2\ttwo\n3\tthree\n4\t"}]}}
JSON
    cp "$S/claude.ndjson" "$S/agent.ndjson"

    local adapter
    for adapter in codex grok gemini claude agent; do
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" \
        --raw "$S/$adapter.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
        --out "$S/$adapter-audit.json" >/dev/null 2>&1
      assert_eq "$adapter accepts successful byte-proven source output" "$?" 0
      assert_grep "$adapter credits the proven source range" "$S/$adapter-audit.json" \
        '"opened_source_ranges":1'
    done

    python3 - "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, sys
spec=importlib.util.spec_from_file_location('audit',sys.argv[1])
audit=importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
reminder='<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>'
assert audit.delivered_matches_bytes('claude','Read',reminder,b'',1)
assert not audit.delivered_matches_bytes('claude','Read',reminder,b'\n',1)
assert not audit.delivered_matches_bytes('claude','Read',reminder + 'x',b'',1)
PY
    assert_eq "Claude empty-file reminder matches only exact empty bytes" "$?" 0

    printf 'alpha\rbeta\fstill one LF line\nomega\n' > "$R/src/lf-only.ts"
    python3 - "$S/lf-only.ndjson" "$R/src/lf-only.ts" <<'PY'
import json, pathlib, sys
output=pathlib.Path(sys.argv[2]).read_bytes().split(b'\n',1)[0].decode()+'\n'
rows=[
 {'type':'item.started','item':{'id':'lf','type':'command_execution',
                                'command':"sed -n '1,1p' src/lf-only.ts"}},
 {'type':'item.completed','item':{'id':'lf','type':'command_execution',
                                  'command':"sed -n '1,1p' src/lf-only.ts",
                                  'aggregated_output':output,'exit_code':0}},
]
pathlib.Path(sys.argv[1]).write_text(''.join(json.dumps(row)+'\n' for row in rows))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/lf-only.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/lf-only-audit.json" >/dev/null 2>&1
    assert_eq "bare CR and form feed stay inside one LF source line" "$?" 0
    assert_grep "LF-only source range receives audit credit" "$S/lf-only-audit.json" \
      '"opened_source_ranges":1'

    printf 'terminal\n\n' > "$R/src/terminal-blank.ts"
    cat > "$S/grok-terminal-blank.ndjson" <<'JSON'
{"type":"tool_call","toolCallId":"g2","toolName":"read_file","rawInput":{"target_file":"src/terminal-blank.ts","offset":1,"limit":2}}
{"type":"tool_call_update","toolCallId":"g2","status":"completed","rawOutput":{"type":"ReadFile","FileContent":{"content":"1→terminal\n","total_lines":2}}}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok \
      --raw "$S/grok-terminal-blank.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/grok-terminal-blank-audit.json" >/dev/null 2>&1
    assert_eq "Grok may omit one rendered terminal blank line" "$?" 0
    assert_grep "terminal blank normalization still proves the exact range" \
      "$S/grok-terminal-blank-audit.json" '"opened_source_ranges":1'

    cat > "$S/claude-terminal-blank.ndjson" <<'JSON'
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"a2","name":"Read","input":{"file_path":"src/terminal-blank.ts","offset":1,"limit":2}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a2","content":"1\tterminal\n2\t\n3\t"}]}}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/claude-terminal-blank.ndjson" --prompt "$S/prompt.md" --root "$R" \
      --session "$S" --out "$S/claude-terminal-blank-audit.json" >/dev/null 2>&1
    assert_eq "Claude numbered EOF marker preserves a real terminal blank line" "$?" 0

    sed 's/2\\t\\n3\\t/2\\t/' "$S/claude-terminal-blank.ndjson" > "$S/claude-explicit-blank.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/claude-explicit-blank.ndjson" --prompt "$S/prompt.md" --root "$R" \
      --session "$S" --out "$S/claude-explicit-blank-audit.json" >/dev/null 2>&1
    assert_eq "Claude explicit numbered blank proves the final requested blank line" "$?" 0
    assert_grep "Claude explicit blank receives source-range credit" \
      "$S/claude-explicit-blank-audit.json" '"opened_source_ranges":1'

    sed 's/2\\t\\n3\\t//' "$S/claude-terminal-blank.ndjson" > "$S/claude-missing-blank.ndjson"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/claude-missing-blank.ndjson" --prompt "$S/prompt.md" --root "$R" \
      --session "$S" --out "$S/claude-missing-blank-audit.json" >/dev/null 2>&1
    assert_eq "Claude cannot omit an unnumbered real terminal blank line" "$?" 2
    assert_grep "missing Claude blank has a stable mismatch" "$S/claude-missing-blank-audit.json" \
      '"code":"source-output-mismatch"'

    cat > "$S/truncated.ndjson" <<'JSON'
{"type":"item.started","item":{"id":"short","type":"command_execution","command":"sed -n '1,3p' src/x.ts"}}
{"type":"item.completed","item":{"id":"short","type":"command_execution","command":"sed -n '1,3p' src/x.ts","aggregated_output":"one\n","exit_code":0}}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/truncated.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/truncated-audit.json" >/dev/null 2>&1
    assert_eq "fake one-line sed output cannot prove a three-line source read" "$?" 2
    assert_grep "truncated source output has a stable violation" "$S/truncated-audit.json" \
      '"code":"source-output-mismatch"'
    assert_grep "truncated source output receives no source-range credit" "$S/truncated-audit.json" \
      '"opened_source_ranges":0'

    python3 - "$S" <<'PY'
import json, pathlib, sys
s = pathlib.Path(sys.argv[1])
events = {
    'codex': [
        {'type':'item.started','item':{'id':'f','type':'command_execution','command':"sed -n '1,3p' src/x.ts"}},
        {'type':'item.completed','item':{'id':'f','type':'command_execution','command':"sed -n '1,3p' src/x.ts",'aggregated_output':'one\ntwo\nthree\n','exit_code':1}},
    ],
    'grok': [
        {'type':'tool_call','toolCallId':'f','toolName':'read_file','rawInput':{'target_file':'src/x.ts','offset':1,'limit':3}},
        {'type':'tool_call_update','toolCallId':'f','status':'failed','rawOutput':'one\ntwo\nthree\n'},
    ],
    'gemini': [
        {'type':'tool_use','tool_id':'f','tool_name':'read_file','parameters':{'path':'src/x.ts','offset':1,'limit':3}},
        {'type':'tool_result','tool_id':'f','status':'error','output':'one\ntwo\nthree\n'},
    ],
    'claude': [
        {'type':'assistant','message':{'content':[{'type':'tool_use','id':'f','name':'Read','input':{'file_path':'src/x.ts','offset':1,'limit':3}}]}},
        {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'f','is_error':True,'content':'one\ntwo\nthree\n'}]}},
    ],
}
events['agent'] = events['claude']
for adapter, rows in events.items():
    with (s / f'{adapter}-failed.ndjson').open('w') as stream:
        for row in rows:
            stream.write(json.dumps(row) + '\n')
PY
    for adapter in codex grok gemini claude agent; do
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" \
        --raw "$S/$adapter-failed.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
        --out "$S/$adapter-failed-audit.json" >/dev/null 2>&1
      assert_eq "$adapter ignores failed exploratory output" "$?" 0
      assert_grep "$adapter failed output proves no source range" "$S/$adapter-failed-audit.json" \
        '"source_read_calls":0'
    done

    cat > "$S/duplicate.ndjson" <<'JSON'
{"type":"tool_use","tool_id":"d1","tool_name":"read_file","parameters":{"path":"src/x.ts","offset":1,"limit":3}}
{"type":"tool_result","tool_id":"d1","status":"success","output":"one\ntwo\nthree\n"}
{"type":"tool_result","tool_id":"d1","status":"success","output":"one\ntwo\nthree\n"}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter gemini \
      --raw "$S/duplicate.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/duplicate-audit.json" >/dev/null 2>&1
    assert_eq "duplicate tool output fails closed" "$?" 2
    assert_grep "duplicate tool output has a stable violation" "$S/duplicate-audit.json" \
      '"code":"duplicate-tool-output"'

    cat > "$S/orphan.ndjson" <<'JSON'
{"type":"tool_use","tool_id":"known","tool_name":"read_file","parameters":{"path":"src/x.ts","offset":1,"limit":3}}
{"type":"tool_result","tool_id":"unknown","status":"success","output":"one\ntwo\nthree\n"}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter gemini \
      --raw "$S/orphan.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
      --out "$S/orphan-audit.json" >/dev/null 2>&1
    assert_eq "unknown tool output fails closed" "$?" 2
    assert_grep "unknown tool output has a stable violation" "$S/orphan-audit.json" \
      '"code":"orphan-tool-output"'
  )
}

test_narrow_seat_refuses_invalid_audit() {
  ( seat_env; local S="$T/narrow-refusal"; seat_roster "$S"
    cat > "$S/p.md" <<'EOF'
Evidence manifest SHA-256: 0000000000000000000000000000000000000000000000000000000000000000
Assigned scope: semantic
EOF
    SHIM_MODE=unbounded SHIM_CALLS_FILE="$T/narrow-refusal.calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" > "$T/narrow-refusal.out" 2>&1
    assert_eq "invalid narrowed seat exits as unusable" "$?" 2
    assert_exit "invalid narrowed seat removes findings" 1 test -e "$S/r1-codex-sol.json"
    assert_exit "invalid narrowed seat preserves findings for diagnosis" 0 \
      test -s "$S/r1-codex-sol.audit-invalid.json"
    assert_grep "invalid narrowed audit remains reviewable" "$S/r1-codex-sol.read-audit.json" '"status":"invalid"'
    assert_grep "narrowed audit declares narrow validity" "$S/r1-codex-sol.read-audit.json" '"narrow":true'
    assert_grep "seat log stops before another paid launch" "$S/r1-codex-sol.log" \
      'stop the panel before another reviewer launch'
    assert_nogrep "seat log does not request an audit retry" "$S/r1-codex-sol.log" 'retry|rerun'
    local invalid_hash audit_hash
    invalid_hash=$(shasum -a 256 "$S/r1-codex-sol.audit-invalid.json" | awk '{print $1}')
    audit_hash=$(shasum -a 256 "$S/r1-codex-sol.read-audit.json" | awk '{print $1}')
    SHIM_MODE=ok SHIM_CALLS_FILE="$T/narrow-refusal.calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" > "$T/narrow-relaunch.out" 2>&1
    assert_eq "hard-audit marker refuses a same-generation relaunch" "$?" 2
    assert_eq "hard-audit relaunch refusal makes no second provider call" \
      "$(wc -l < "$T/narrow-refusal.calls" | tr -d ' ')" 1
    assert_eq "hard-audit relaunch refusal preserves the diagnostic result" \
      "$(shasum -a 256 "$S/r1-codex-sol.audit-invalid.json" | awk '{print $1}')" "$invalid_hash"
    assert_eq "hard-audit relaunch refusal preserves the invalid audit" \
      "$(shasum -a 256 "$S/r1-codex-sol.read-audit.json" | awk '{print $1}')" "$audit_hash"
    assert_grep "hard-audit relaunch refusal names the existing marker" \
      "$T/narrow-relaunch.out" 'review session stopped after a hard evidence audit failure.*fresh review session'
    SHIM_MODE=ok SHIM_CALLS_FILE="$T/narrow-refusal.calls" \
      "$SCRIPTS/rev-seat.sh" codex-terra "$S" 1 "$S/p.md" > "$T/sibling-relaunch.out" 2>&1
    assert_eq "hard-audit marker refuses a sibling under the same panel label" "$?" 2
    assert_eq "sibling hard-audit refusal makes no provider call" \
      "$(wc -l < "$T/narrow-refusal.calls" | tr -d ' ')" 1
    assert_exit "sibling hard-audit refusal creates no attempt reservation" 1 \
      grep -R -q -- '"seat":"codex-terra"' "$S/attempts"
    assert_grep "sibling hard-audit refusal names the stopped panel" \
      "$T/sibling-relaunch.out" 'review session stopped after a hard evidence audit failure.*fresh review session'
  )
}

test_session_audit_stop_crosses_panel_labels() {
  ( seat_env; local session="$T/session-audit-stop"; seat_roster "$session"
    printf 'review\n' > "$session/r2-codex-sol.prompt.md"
    printf 'invalid result\n' > "$session/r1-codex-sol.invalid.json"
    printf 'invalid audit\n' > "$session/r1-codex-sol.audit.json"
    : > "$SHIM_ARGS_FILE"
    python3 "$SCRIPTS/lib/rev-attempt.py" stop "$session" r1 --reason "hard evidence audit failed"
    assert_eq "hard evidence audit stop persists" "$?" 0
    local before
    before=$(sha256sum "$session/r1-codex-sol.invalid.json" "$session/r1-codex-sol.audit.json")
    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$session" r2 "$session/r2-codex-sol.prompt.md" \
      >"$T/session-stop.out" 2>"$T/session-stop.err"
    assert_eq "a different label cannot bypass the hard stop" "$?" 2
    assert_eq "the stopped session launches no provider" "$(wc -l < "$SHIM_ARGS_FILE" | tr -d ' ')" 0
    assert_eq "hard-audit evidence stays byte-identical" \
      "$(sha256sum "$session/r1-codex-sol.invalid.json" "$session/r1-codex-sol.audit.json")" "$before"
    assert_grep "the refusal requires a fresh session" "$T/session-stop.err" \
      'hard evidence audit failed.*fresh review session'
  )
}

test_evidence_audit_failure_modes() {
  ( seat_env; local S="$T/audit-failure-modes"; seat_roster "$S"
    cat > "$S/malformed-evidence.md" <<'EOF'
Evidence manifest SHA-256: 000000000000000000000000000000000000000000000000000000000000000
Assigned scope: semantic
EOF
    SHIM_MODE=unbounded "$SCRIPTS/rev-seat.sh" codex-sol "$S" malformed \
      "$S/malformed-evidence.md" > "$T/malformed-evidence.out" 2>&1
    assert_eq "malformed evidence declaration exits as unusable" "$?" 2
    assert_exit "malformed evidence declaration removes findings" 1 \
      test -e "$S/rmalformed-codex-sol.json"
    assert_grep "malformed declaration remains evidence scoped" \
      "$S/rmalformed-codex-sol.read-audit.json" '"evidence_scoped":true'
    assert_grep "malformed declaration remains narrowed" \
      "$S/rmalformed-codex-sol.read-audit.json" '"narrow":true'
    assert_grep "malformed declaration has one stable failure" \
      "$S/rmalformed-codex-sol.read-audit.json" \
      '"code":"invalid-evidence-manifest-declaration"'
    assert_nogrep "malformed evidence is never treated as legacy" \
      "$S/rmalformed-codex-sol.log" 'legacy review; result retained as advisory'

    cat > "$S/full-evidence.md" <<'EOF'
Evidence manifest SHA-256: 0000000000000000000000000000000000000000000000000000000000000000
Assigned scope: full
EOF
    SHIM_MODE=unbounded "$SCRIPTS/rev-seat.sh" codex-sol "$S" full "$S/full-evidence.md" \
      > "$T/full-evidence.out" 2>&1
    assert_eq "invalid full-scope evidence seat exits as unusable" "$?" 2
    assert_exit "invalid full-scope evidence seat removes findings" 1 test -e "$S/rfull-codex-sol.json"
    assert_exit "invalid full-scope seat preserves findings for diagnosis" 0 \
      test -s "$S/rfull-codex-sol.audit-invalid.json"
    assert_grep "full-scope audit is authoritatively evidence scoped" \
      "$S/rfull-codex-sol.read-audit.json" '"evidence_scoped":true'
    assert_grep "full-scope evidence failure stops before another paid launch" \
      "$S/rfull-codex-sol.log" 'stop the panel before another reviewer launch'
    assert_nogrep "full-scope evidence failure does not request a retry" \
      "$S/rfull-codex-sol.log" 'retry|rerun'

    printf 'Assigned scope: full\n' > "$S/legacy.md"
    SHIM_MODE=unbounded "$SCRIPTS/rev-seat.sh" codex-sol "$S" legacy "$S/legacy.md" \
      > "$T/legacy.out" 2>&1
    assert_eq "invalid legacy audit remains advisory" "$?" 0
    assert_exit "legacy findings remain available" 0 test -s "$S/rlegacy-codex-sol.json"
    assert_grep "legacy audit is authoritatively outside evidence scope" \
      "$S/rlegacy-codex-sol.read-audit.json" '"evidence_scoped":false'
    assert_grep "legacy audit message is explicitly advisory" "$S/rlegacy-codex-sol.log" \
      'legacy review; result retained as advisory'

    local real_python="$PATH" audit_python="$T/audit-python"
    mkdir -p "$audit_python"
    cat > "$audit_python/python3" <<'SH'
#!/bin/bash
if [ "$1" = "$AUDIT_SCRIPT" ] && [ "$2" = audit ]; then
  args=("$@"); out=""
  for ((index=0; index < ${#args[@]}; index++)); do
    [ "${args[$index]}" != --out ] || out="${args[$((index + 1))]}"
  done
  case "$AUDIT_SHIM_MODE" in
    missing) exit 2;;
    malformed) printf '{\n' > "$out"; exit 2;;
    inconsistent)
      printf '%s\n' '{"schema_version":2,"status":"valid","evidence_scoped":false,"narrow":false,"evidence_manifest_sha256":null,"violations":[]}' > "$out"
      exit 2;;
  esac
fi
PATH="$REAL_PYTHON_PATH" exec python3 "$@"
SH
    chmod +x "$audit_python/python3"
    local audit_mode
    for audit_mode in missing malformed inconsistent; do
      local audit_label="metadata-$audit_mode"
      PATH="$audit_python:$real_python" REAL_PYTHON_PATH="$real_python" \
        AUDIT_SCRIPT="$SCRIPTS/lib/review-read-audit.py" AUDIT_SHIM_MODE="$audit_mode" \
        SHIM_MODE=unbounded "$SCRIPTS/rev-seat.sh" codex-sol "$S" "$audit_label" \
        "$S/legacy.md" > "$T/audit-$audit_mode.out" 2>&1
      assert_eq "$audit_mode audit metadata fails closed" "$?" 2
      assert_exit "$audit_mode audit metadata removes findings" 1 \
        test -e "$S/r$audit_label-codex-sol.json"
      assert_exit "$audit_mode audit metadata preserves findings for diagnosis" 0 \
        test -s "$S/r$audit_label-codex-sol.audit-invalid.json"
      assert_grep "$audit_mode audit metadata has one wrapper diagnostic" \
        "$S/r$audit_label-codex-sol.log" \
        'bounded-read audit metadata is missing, malformed, or inconsistent'
    done
  )
}

test_adapter_isolation_and_cache_flags() {
  ( seat_env; local S="$T/read-adapters"; seat_roster "$S"; printf 'full prompt\n' > "$S/p.md"
    mkdir -p "$T/codex-state"; printf '{}\n' > "$T/codex-state/auth.json"
    CODEX_HOME="$T/codex-state" SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" >/dev/null
    assert_grep "Codex ignores user config" "$T/args" '^--ignore-user-config$'
    assert_grep "Codex disables project instruction discovery" "$T/args" '^project_doc_max_bytes=0$'
    assert_nogrep "Codex does not misuse execpolicy ignore-rules" "$T/args" '^--ignore-rules$'
    assert_grep "Codex uses an isolated auth symlink" "$T/args.env" '^CODEX_AUTH_LINK=yes$'
    local codex_home; codex_home=$(sed -n 's/^CODEX_HOME=//p' "$T/args.env" | tail -1)
    assert_exit "Codex isolated home is removed after the attempt" 1 test -e "$codex_home"

    python3 - "$S/roster.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
for seat in data['seats']:
    if seat['seat'] == 'opus':
        seat['adapter'] = 'claude'
json.dump(data, open(path, 'w'))
PY
    local real_path=$PATH
    mkdir -p "$T/claude-seat"
    cat > "$T/claude-seat/claude" <<'SH'
#!/bin/bash
printf '%s\n' "$@" > "$SHIM_ARGS_FILE"
cat >/dev/null
python3 - "$SHIM_FIXTURE_DIR/findings-valid.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1]))
print(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','id':'a1','name':'Bash','input':{'command':'git diff --stat | head -240'}}]}}))
print(json.dumps({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'a1','content':' 2 files changed\n'}]}}))
print(json.dumps({'type':'result','subtype':'success','is_error':False,'num_turns':1,'structured_output':result}))
PY
SH
    chmod +x "$T/claude-seat/claude"
    PATH="$T/claude-seat:$PATH" SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" opus "$S" 3 "$S/p.md" >/dev/null
    PATH=$real_path
    assert_grep "Claude enables its documented cache stability flag" "$T/args" '^--exclude-dynamic-system-prompt-sections$'
    assert_grep "Claude disables slash command discovery" "$T/args" '^--disable-slash-commands$'
    assert_grep "Claude settings include Read bounds" "$T/args" 'review-read-audit.py hook'
    assert_grep "Claude settings include output byte checks" "$T/args" 'review-read-audit.py post-hook'
  )
}

test_isolated_home_startup_cleanup() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" first second
    first=$(python3 "$helper" create codex "$T/stable-seat") || return
    printf 'stale\n' > "$first/stale-state"
    second=$(python3 "$helper" create codex "$T/stable-seat") || return
    assert_eq "isolated home path is deterministic for startup cleanup" "$second" "$first"
    assert_exit "startup cleanup removes prior seat state" 1 test -e "$second/stale-state"
    assert_eq "isolated home permissions are private" \
      "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777)[2:])' "$second")" 700
    python3 "$helper" clean codex "$second" || return
    assert_exit "explicit cleanup removes the isolated home" 1 test -e "$second"
  )
}
test_search_helpers_reuse_declared_command_set() {
  ( python3 - "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import runpy, sys

audit = runpy.run_path(sys.argv[1])
audit['SEARCH_COMMANDS'].add('probe-search')
assert audit['search_pattern_indexes'](['probe-search', 'needle', '.']) == {1}
assert audit['line_limiter'](['probe-search', '--max-count', '4', 'needle', '.'])
assert audit['shell_search_producer'](['probe-search', 'needle', '.'])
PY
    assert_eq "search helpers reuse the declared command set" "$?" 0
  )
}
