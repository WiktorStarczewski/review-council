#!/bin/bash

read_bound_hook() {
  local root=$1 session=$2 payload=$3
  printf '%s' "$payload" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
    --root "$root" --session "$session" >/dev/null 2>&1
}

test_read_bound_hook_contract() {
  ( local R="$T/read-bound-root" S="$T/read-bound-session"
    mkdir -p "$R/src" "$S"
    printf 'one\ntwo\n' > "$R/src/x.ts"
    printf 'prompt\n' > "$S/r1-sol.prompt.md"
    printf 'index\n' > "$S/r1-evidence.md"
    mkdir -p "$S/deps" "$T/pinned-crate"
    printf 'dependency\n' > "$T/pinned-crate/lib.rs"
    ln -s "$T/pinned-crate" "$S/deps/pinned-crate"

    local source_ok='{"tool_name":"Read","tool_input":{"file_path":"src/x.ts","offset":1,"limit":200}}'
    local prompt_ok; prompt_ok=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' "$S/r1-sol.prompt.md")
    local index_ok; index_ok=$(printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' "$S/r1-evidence.md")
    local grep_ok='{"tool_name":"Grep","tool_input":{"pattern":"retry","path":"src","head_limit":50}}'
    local shell_ok='{"tool_name":"Bash","tool_input":{"command":"git diff HEAD | sed -n '\''1,200p'\''"}}'
    local shell_search_ok='{"tool_name":"Bash","tool_input":{"command":"rg -n retry src | head -80"}}'
    local shell_log_ok='{"tool_name":"Bash","tool_input":{"command":"git log -n 240"}}'
    for payload in "$source_ok" "$prompt_ok" "$index_ok" "$grep_ok" "$shell_ok" "$shell_search_ok" "$shell_log_ok"; do
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
    local wide_shell_search='{"tool_name":"Bash","tool_input":{"command":"rg -n retry src | head -81"}}'
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
      --root "$R" >/dev/null 2>&1
    assert_eq "hook refuses an artifact exemption without a bound session" "$?" 2
    printf '%s' "$other_artifact" | python3 "$SCRIPTS/lib/review-read-audit.py" hook \
      --session "$S" >/dev/null 2>&1
    assert_eq "hook refuses an artifact exemption without a bound root" "$?" 2
    python3 - "$T/other-session/r1-sol.prompt.md" <<'PY' | \
      python3 "$SCRIPTS/lib/review-read-audit.py" post-hook --root "$R" >/dev/null 2>&1
import json, sys
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':sys.argv[1]},
                  'tool_response':'x' * 32769}))
PY
    assert_eq "post-hook refuses an artifact exemption without a bound session" "$?" 2
  )
}

test_specialist_required_range_uses_session_objects() {
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
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    local manifest seat prompt
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
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 10 "$seat" correctness specialist-source --evidence "$manifest") || return
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
if mode == 'unrelated':
    command('source-unrelated', "sed -n '1,1p' a.txt", (root / 'a.txt').read_text())
else:
    required = context['required_source_ranges'][0]
    start = required['line_start']; end = min(required['line_end'], start + 239)
    source = (root / required['path']).read_text().splitlines(keepends=True)
    command('source-required', f"sed -n '{start},{end}p' '{required['path']}'",
            ''.join(source[start - 1:end]))
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
    assert_eq "specialist accepts one intersecting bounded range from an uncommitted snapshot" "$?" 0
    assert_grep "specialist receipt keeps partial required coverage explicit" \
      "$S/r10-$seat.read-audit.json" '"required_source_ranges_covered":0'
  )
}

test_disabled_context_requires_component_boundary() {
  ( local R="$T/disabled-context-root" S="$T/disabled-context-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"; printf 'value = 1\n' > "$R/src/x.py"
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/x.py\n' > "$S/files.txt"; printf 'src/x.py\n' > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    local manifest seat prompt
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
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 11 "$seat" correctness disabled-context --evidence "$manifest") || return
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
    done
  )
}

test_grok_visible_output_accounting() {
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
    assert_eq "failed Grok content remains a failed tool output" "$?" 2
    assert_grep "failed Grok visible output keeps failure semantics" "$S/grok-audit.json" \
      '"code":"failed-tool-output"'
  )
}

test_read_audit_source_evidence_contract() {
  ( local R="$T/source-evidence-root" S="$T/source-evidence-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    printf 'one\ntwo\nthree\n' > "$R/src/x.ts"
    git -C "$R" add src/x.ts && git -C "$R" commit -qm 'source baseline'
    local base reviewed; base=$(git -C "$R" rev-parse HEAD)
    printf 'one\nchanged\nthree\n' > "$R/src/x.ts"
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/x.ts\n' > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    local manifest prompt packet assigned_patch
    manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 4 --phase discovery) || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 4 sol correctness source-evidence --evidence "$manifest") || return
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
    python3 - "$S/r4-sol.stream.ndjson" "$packet" "$assigned_patch" <<'PY'
import json, sys
packet = open(sys.argv[2]).read(); patch = open(sys.argv[3]).read()
packet_command = "cat '" + sys.argv[2] + "'"
patch_command = "sed -n '1,240p' '" + sys.argv[3] + "'"
events = [
    {'type':'item.started','item':{'id':'p1','type':'command_execution','command':packet_command}},
    {'type':'item.completed','item':{'id':'p1','type':'command_execution','command':packet_command,
                                     'aggregated_output':packet,'exit_code':0}},
    {'type':'item.started','item':{'id':'p2','type':'command_execution','command':patch_command}},
    {'type':'item.completed','item':{'id':'p2','type':'command_execution','command':patch_command,
                                     'aggregated_output':patch,'exit_code':0}},
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
    {'type':'item.started','item':{'id':'packet','type':'command_execution','command':packet_command}},
    {'type':'item.completed','item':{'id':'packet','type':'command_execution','command':packet_command,
                                     'aggregated_output':packet,'exit_code':0}},
    {'type':'item.started','item':{'id':'patch','type':'command_execution','command':patch_command}},
    {'type':'item.completed','item':{'id':'patch','type':'command_execution','command':patch_command,
                                     'aggregated_output':patch,'exit_code':0}},
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

    python3 - "$S/r4-sol.stream.ndjson" "$packet" "$assigned_patch" <<'PY'
import json, sys
path, packet, assigned_patch = sys.argv[1:]
raw = open(packet).read(); command = "cat '" + packet + "'"
patch = open(assigned_patch).read(); patch_command = "sed -n '1,240p' '" + assigned_patch + "'"
events = [
    {'type':'item.started','item':{'id':'p2','type':'command_execution','command':command}},
    {'type':'item.completed','item':{'id':'p2','type':'command_execution','command':command,
                                     'aggregated_output':raw,'exit_code':0}},
    {'type':'item.started','item':{'id':'p3','type':'command_execution','command':patch_command}},
    {'type':'item.completed','item':{'id':'p3','type':'command_execution','command':patch_command,
                                     'aggregated_output':patch,'exit_code':0}},
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
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    manifest=$(REV_PATCH_CHUNKS=0 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 8 --phase discovery) || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 8 sol correctness patch-chunks --evidence "$manifest") || return
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
for index, shard in enumerate(manifest['source_context']['seats'][seat]['shards'], 1):
    path = session / shard['artifact']
    command('packet-' + str(index), "cat '" + str(path) + "'", path.read_text())
patch = pathlib.Path(assignment['patch']); lines = patch.read_text().splitlines(keepends=True)
command('patch-1', "sed -n '1,240p' '" + str(patch) + "'", ''.join(lines[:240]))
if complete:
    command('patch-2', "sed -n '241,480p' '" + str(patch) + "'", ''.join(lines[240:480]))
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
    mkrepo "$R"; mkdir -p "$S"
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
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    local manifest prompt
    manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 9 --head "$reviewed" --phase discovery) || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 9 sol correctness required-source --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r9-sol.json"

    write_required_transcript() {
      python3 - "$manifest" "$S/r9-sol.stream.ndjson" "$1" "$R" <<'PY'
import json, pathlib, subprocess, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2]); complete = sys.argv[3] == 'complete'
session = pathlib.Path(sys.argv[1]).parent; seat = 'sol'; context = manifest['source_context']['seats'][seat]
assert context['role'] == 'integration' and len(context['required_source_ranges']) == 1
events = []
def command(call_id, command, output):
    events.extend([
        {'type':'item.started','item':{'id':call_id,'type':'command_execution','command':command}},
        {'type':'item.completed','item':{'id':call_id,'type':'command_execution','command':command,
                                         'aggregated_output':output,'exit_code':0}},
    ])
for index, shard in enumerate(context['shards'], 1):
    path = session / shard['artifact']
    command('packet-' + str(index), "cat '" + str(path) + "'", path.read_text())
patch = pathlib.Path(manifest['assignments'][seat]['patch']); patch_lines = patch.read_text().splitlines(keepends=True)
for start in range(1, len(patch_lines) + 1, 240):
    end = min(len(patch_lines), start + 239)
    command('patch-' + str(start), f"sed -n '{start},{end}p' '{patch}'",
            ''.join(patch_lines[start - 1:end]))
required = context['required_source_ranges'][0]
blob = subprocess.check_output(['git', '-C', sys.argv[4], 'cat-file', 'blob', required['blob_oid']])
source_lines = blob.decode().splitlines(keepends=True)
starts = list(range(required['line_start'], required['line_end'] + 1, 240))
if not complete:
    starts = starts[:-1]
for start in starts:
    end = min(required['line_end'], start + 239)
    command('source-' + str(start), f"git show '{required['blob_oid']}' | sed -n '{start},{end}p'",
            ''.join(source_lines[start - 1:end]))
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

    write_required_transcript partial
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r9-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r9-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "integration seat rejects a gap in required source range coverage" "$?" 2
    assert_grep "missing required source range has a stable violation" "$S/r9-sol.read-audit.json" \
      '"code":"missing-required-source-range"'
    assert_grep "partial required source range is not counted as covered" "$S/r9-sol.read-audit.json" \
      '"required_source_ranges_covered":0'

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
for index, shard in enumerate(context['shards'], 1):
    path = pathlib.Path(sys.argv[1]).parent / shard['artifact']
    command('packet-' + str(index), "cat '" + str(path) + "'", path.read_text())
patch = pathlib.Path(manifest['assignments']['sol']['patch']); lines = patch.read_text().splitlines(keepends=True)
for start in range(1, len(lines) + 1, 240):
    end = min(len(lines), start + 239)
    command('patch-' + str(start), f"sed -n '{start},{end}p' '{patch}'", ''.join(lines[start - 1:end]))
required = context['required_source_ranges'][0]
live = (root / required['path']).read_text().splitlines(keepends=True)
for start in range(required['line_start'], required['line_end'] + 1, 240):
    end = min(required['line_end'], start + 239)
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
      '"code":"required-source-output-mismatch"'
    assert_grep "wrong named-head tree produces no exact blob proof" "$S/r9-sol.read-audit.json" \
      '"required_source_range_proofs":\[\]'
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
  )
}

test_read_transcript_audit_contract() {
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

    python3 - <<'PY' | python3 "$SCRIPTS/lib/review-read-audit.py" post-hook --root "$R" --session "$S" >/dev/null 2>&1
import json
print(json.dumps({'tool_name':'Read','tool_input':{'file_path':'src/x.ts','offset':1,'limit':1},'tool_response':'x' * 32769}))
PY
    assert_eq "post-tool hook rejects an oversized response" "$?" 2
  )
}

test_read_audit_binds_delivered_output() {
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
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a1","content":"1\tone\n2\ttwo\n3\tthree\n"}]}}
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
      assert_eq "$adapter rejects failed tool output" "$?" 2
      assert_grep "$adapter failed output has a stable violation" "$S/$adapter-failed-audit.json" \
        '"code":"failed-tool-output"'
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
    SHIM_MODE=unbounded "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" > "$T/narrow-refusal.out" 2>&1
    assert_eq "invalid narrowed seat exits as unusable" "$?" 2
    assert_exit "invalid narrowed seat removes findings" 1 test -e "$S/r1-codex-sol.json"
    assert_grep "invalid narrowed audit remains reviewable" "$S/r1-codex-sol.read-audit.json" '"status":"invalid"'
    assert_grep "narrowed audit declares narrow validity" "$S/r1-codex-sol.read-audit.json" '"narrow":true'
    assert_grep "seat log requests whole-panel full fallback" "$S/r1-codex-sol.log" 'rerun the whole panel at full scope'
  )
}

test_evidence_audit_failure_modes() {
  ( seat_env; local S="$T/audit-failure-modes"; seat_roster "$S"
    cat > "$S/full-evidence.md" <<'EOF'
Evidence manifest SHA-256: 0000000000000000000000000000000000000000000000000000000000000000
Assigned scope: full
EOF
    SHIM_MODE=unbounded "$SCRIPTS/rev-seat.sh" codex-sol "$S" full "$S/full-evidence.md" \
      > "$T/full-evidence.out" 2>&1
    assert_eq "invalid full-scope evidence seat exits as unusable" "$?" 2
    assert_exit "invalid full-scope evidence seat removes findings" 1 test -e "$S/rfull-codex-sol.json"
    assert_grep "full-scope evidence failure gets a full-scope message" "$S/rfull-codex-sol.log" \
      'rejected full-scope evidence review'
    assert_nogrep "full-scope evidence failure does not request a narrowed fallback" \
      "$S/rfull-codex-sol.log" 'rerun the whole panel at full scope'

    printf 'Assigned scope: full\n' > "$S/legacy.md"
    SHIM_MODE=unbounded "$SCRIPTS/rev-seat.sh" codex-sol "$S" legacy "$S/legacy.md" \
      > "$T/legacy.out" 2>&1
    assert_eq "invalid legacy audit remains advisory" "$?" 0
    assert_exit "legacy findings remain available" 0 test -s "$S/rlegacy-codex-sol.json"
    assert_grep "legacy audit message is explicitly advisory" "$S/rlegacy-codex-sol.log" \
      'legacy review; result retained as advisory'
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

    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok "$S" 2 "$S/p.md" >/dev/null
    assert_grep "Grok sends the prompt verbatim" "$T/args" '^--verbatim$'
    local grok_home; grok_home=$(sed -n 's/^HOME=//p' "$T/args.env" | tail -1)
    assert_exit "Grok isolated home is removed after the attempt" 1 test -e "$grok_home"

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
    assert_grep "Claude settings include Read bounds" "$T/args" 'review-read-audit.py hook'
    assert_grep "Claude settings include output byte checks" "$T/args" 'review-read-audit.py post-hook'
  )
}

test_isolated_home_startup_cleanup() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" first second
    first=$(python3 "$helper" create grok "$T/stable-seat") || return
    printf 'stale\n' > "$first/stale-state"
    second=$(python3 "$helper" create grok "$T/stable-seat") || return
    assert_eq "isolated home path is deterministic for startup cleanup" "$second" "$first"
    assert_exit "startup cleanup removes prior seat state" 1 test -e "$second/stale-state"
    assert_eq "isolated home permissions are private" \
      "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777)[2:])' "$second")" 700
    python3 "$helper" clean grok "$second" || return
    assert_exit "explicit cleanup removes the isolated home" 1 test -e "$second"
  )
}
