# shellcheck shell=bash
# Usage profiling separates completed results from metered attempts and preserves provider detail.
test_session_profile() {
  ( local S="$T/profile-session" S2="$T/profile-session-2" S3="$T/profile-session-mixed" S4="$T/profile-session-malformed"; mkdir -p "$S" "$S2" "$S3" "$S4"
    cat > "$S/roster.json" <<'JSON'
{"result_receipts":{"version":1,"legacy_no_exit_sha256":{}},"seats":[
  {"seat":"opus-cli","adapter":"claude"},
  {"seat":"codex-sol","adapter":"codex"},
  {"seat":"grok","adapter":"grok"},
  {"seat":"gemini","adapter":"gemini"},
  {"seat":"opus-agent","adapter":"agent"}
]}
JSON
    cat > "$S/r1-opus-cli.stream.jsonl" <<'EOF'
{"type":"assistant","usage":{"input_tokens":999}}
{"type":"result","usage":{"input_tokens":10,"cache_creation_input_tokens":20,"cache_read_input_tokens":30,"output_tokens":4},"total_cost_usd":1.5}
EOF
    cat > "$S/r2-opus-cli.stream.ndjson" <<'EOF'
{"type":"result","is_error":true,"usage":{"input_tokens":8,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":2},"total_cost_usd":0.1}
EOF
    cat > "$S/r3-opus-cli.stream.ndjson" <<'EOF'
{"type":"result","is_error":true,"usage":{"input_tokens":6,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":3},"total_cost_usd":0.2}
EOF
    cat > "$S/r1x-codex-sol.stream.ndjson" <<'EOF'
{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":20,"cache_write_input_tokens":11,"output_tokens":10,"reasoning_output_tokens":5}}
EOF
    cat > "$S/r1p-grok.stream.ndjson" <<'EOF'
{"type":"end","usage":{"input_tokens":5,"cache_read_input_tokens":7,"output_tokens":3,"total_tokens":15,"cost_usd":0.5}}
EOF
    cp "$FX/gemini-stream.ndjson" "$S/r2-gemini.stream.ndjson"
    cat > "$S/preflight-gemini.stream.ndjson" <<'EOF'
{"type":"result","status":"success","stats":{"input_tokens":9000,"output_tokens":1000}}
EOF
    printf 'two words\n' > "$S/r1x-codex-sol.prompt.md"
    printf 'three prompt words\n' > "$S/r1p-grok.prompt.md"
    printf 'historical plan prompt\n' > "$S/r8-plan-opus-cli.prompt.md"
    python3 - "$S" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
fixtures = {
    'r1x-codex-sol': ('codex', 'valid', [], 4, 3, 100, 80),
    'r1p-grok': ('grok', 'invalid', [{'code': 'fixture-violation'}], 6, 2, 250, 200),
}
for stem, (adapter, status, violations, calls, turns, output, maximum) in fixtures.items():
    prompt = root / (stem + '.prompt.md')
    stream = root / (stem + '.stream.ndjson')
    audit = {
        'schema_version': 1,
        'status': status,
        'narrow': True,
        'adapter': adapter,
        'prompt_sha256': hashlib.sha256(prompt.read_bytes()).hexdigest(),
        'stream_sha256': hashlib.sha256(stream.read_bytes()).hexdigest(),
        'violations': violations,
        'tool_calls': calls,
        'tool_turns': turns,
        'tool_output_bytes': output,
        'max_tool_output_bytes': maximum,
    }
    (root / (stem + '.read-audit.json')).write_text(json.dumps(audit))
(root / 'r2-gemini.read-audit.json').write_text('{')
PY
    cat > "$S/r1x-codex-sol.json" <<'JSON'
{"summary":"code","findings":[{"severity":"P1","file":"src/a.py","line_start":3,"line_end":3,"claim":"a","evidence":"b","suggested_fix":"c","confidence":0.9}]}
JSON
    printf '{"summary":"plan","findings":[]}' > "$S/r1p-grok.json"
    printf '{"summary":"gemini","findings":[]}' > "$S/r2-gemini.json"
    printf '{"summary":"agent","findings":[]}' > "$S/r2-opus-agent.json"
    printf '{"summary":"failed invalid","findings":[{"claim":"missing schema fields"}]}' > "$S/r2-opus-cli.json"
    printf '{"summary":"failed valid","findings":[]}' > "$S/r3-opus-cli.json"
    printf '{"summary":"current missing receipt","findings":[]}' > "$S/r4-opus-agent.json"
    printf '{"summary":"current invalid","findings":[{"claim":"missing schema fields"}]}' > "$S/r5-opus-agent.json"
    printf '{"summary":"probe","findings":[]}' > "$S/preflight-opus-agent.json"
    printf '0\n' > "$S/r1x-codex-sol.exit"
    printf '0\n' > "$S/r1p-grok.exit"
    printf '0\n' > "$S/r2-gemini.exit"
    printf '0\n' > "$S/r2-opus-agent.exit"
    printf '0\n' > "$S/r5-opus-agent.exit"
    printf '2\n' > "$S/r2-opus-cli.exit"
    printf '2\n' > "$S/r3-opus-cli.exit"

    cat > "$S2/r9-plan-opus.stream.jsonl" <<'EOF'
{"type":"result","usage":{"input_tokens":2,"output_tokens":1},"total_cost_usd":0.25}
EOF
    printf '{"summary":"old plan","findings":[]}' > "$S2/r9-plan-opus.json"

    printf '{"summary":"legacy before receipt rollout","findings":[]}' > "$S3/r7-opus.json"
    printf '{"summary":"new incomplete result","findings":[]}' > "$S3/r8-opus.json"
    printf '{"summary":"overwritten legacy result","findings":[]}' > "$S3/r9-opus.json"
    python3 - "$S3" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
old = root / 'r7-opus.json'
roster = {
    'result_receipts': {
        'version': 1,
        'legacy_no_exit_sha256': {
            old.name: hashlib.sha256(old.read_bytes()).hexdigest(),
            'r9-opus.json': hashlib.sha256(b'different prior content').hexdigest(),
        },
    },
    'seats': [{'seat': 'opus', 'adapter': 'claude'}],
}
(root / 'roster.json').write_text(json.dumps(roster))
PY
    printf '{"summary":"malformed marker","findings":[]}' > "$S4/r10-opus.json"
    printf '{"result_receipts":{"version":"invalid"},"seats":[{"seat":"opus","adapter":"claude"}]}' > "$S4/roster.json"

    "$SCRIPTS/rev-profile.py" --json "$S" "$S2" "$S3" "$S4" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
s, old, mixed, malformed = d['sessions']
assert d['totals']['calls'] == 7, d
assert d['totals']['processed_tokens'] == 1411, d
assert d['totals']['cached_input_tokens'] == 20, d
assert d['totals']['cache_write_input_tokens'] == 31, d
assert d['totals']['cache_read_input_tokens'] == 37, d
assert abs(d['totals']['cost_usd'] - 2.55) < 1e-9, d
assert d['totals']['completed_calls'] == 6, d
assert d['totals']['metered_calls'] == 7, d
assert d['totals']['unmetered_calls'] == 2, d
assert d['totals']['read_activity'] == {
    'audits': 2,
    'violating_audits': 1,
    'invalid_audits': 1,
    'tool_calls': 10,
    'tool_turns': 5,
    'tool_output_bytes': 350,
    'max_tool_output_bytes': 200,
    'recognized_tool_calls': 0,
    'source_read_calls': 0,
    'packet_shards': 0,
    'packet_bytes': 0,
    'packet_ranges': 0,
    'opened_source_ranges': 0,
    'finding_citations': 0,
    'patch_proof_calls': 0,
    'patch_proof_turns': 0,
    'patch_proof_visible_bytes': 0,
    'expected_patch_chunks': 0,
    'opened_patch_chunks': 0,
    'window_seats': 0,
    'chunk_seats': 0,
}, d
assert s['calls'] == {'completed': 4, 'metered': 6, 'unmetered': 1}, s
assert s['prompts']['code'] == {'count': 1, 'words': 2}, s
assert s['prompts']['plan'] == {'count': 2, 'words': 6}, s
assert s['results']['code'] == {'calls': 3, 'findings': 1}, s
assert s['results']['plan'] == {'calls': 1, 'findings': 0}, s
assert s['providers']['gemini']['processed_tokens'] == 1200, s
assert s['providers']['gemini']['calls'] == 1, s
assert s['providers']['agent']['completed_calls'] == 1, s
assert s['providers']['agent']['unmetered_calls'] == 1, s
assert s['providers']['claude']['metered_calls'] == 3, s
assert s['providers']['claude']['completed_calls'] == 0, s
assert s['providers']['claude']['cached_input_tokens'] == 0, s
assert s['providers']['claude']['cache_write_input_tokens'] == 20, s
assert s['providers']['claude']['cache_read_input_tokens'] == 30, s
assert s['providers']['codex']['cached_input_tokens'] == 20, s
assert s['providers']['codex']['cache_write_input_tokens'] == 11, s
assert s['providers']['codex']['cache_read_input_tokens'] == 0, s
assert s['providers']['grok']['cache_read_input_tokens'] == 7, s
assert s['read_activity'] == {
    'audits': 2,
    'violating_audits': 1,
    'invalid_audits': [
        {'audit': 'r2-gemini.read-audit.json', 'reason': 'malformed read audit JSON'},
    ],
    'tool_calls': 10,
    'tool_turns': 5,
    'tool_output_bytes': 350,
    'max_tool_output_bytes': 200,
    'recognized_tool_calls': 0,
    'source_read_calls': 0,
    'packet_shards': 0,
    'packet_bytes': 0,
    'packet_ranges': 0,
    'opened_source_ranges': 0,
    'finding_citations': 0,
    'patch_proof_calls': 0,
    'patch_proof_turns': 0,
    'patch_proof_visible_bytes': 0,
    'expected_patch_chunks': 0,
    'opened_patch_chunks': 0,
    'window_seats': 0,
    'chunk_seats': 0,
}, s
assert old['prompts']['plan']['count'] == 0, old
assert old['results']['plan']['calls'] == 1, old
assert old['providers']['claude']['processed_tokens'] == 3, old
assert mixed['calls'] == {'completed': 1, 'metered': 0, 'unmetered': 1}, mixed
assert mixed['results']['code'] == {'calls': 1, 'findings': 0}, mixed
assert mixed['providers']['claude']['completed_calls'] == 1, mixed
assert malformed['calls'] == {'completed': 0, 'metered': 0, 'unmetered': 0}, malformed
PY
    assert_eq "profile accounts for providers, completions, and historical sessions" "$?" 0

    "$SCRIPTS/rev-profile.py" "$S" > "$S/profile.txt"
    assert_grep "text profile reports all call classes" "$S/profile.txt" 'completed=4 metered=6 unmetered=1'
    assert_grep "text profile separates provider cache metrics" "$S/profile.txt" \
      'cached_input=20 cache_write_input=31 cache_read_input=37'
    assert_grep "text profile separates bounded-read activity" "$S/profile.txt" \
      'read_activity=audits:2 violating:1 calls:10 turns:5 output_bytes:350 max_output_bytes:200 invalid:1'
    assert_grep "text profile explains invalid read audits" "$S/profile.txt" \
      'r2-gemini\.read-audit\.json: malformed read audit JSON'
    printf 'mutated\n' >> "$S/r1x-codex-sol.prompt.md"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile-stale-audit.json"
    python3 - "$S/profile-stale-audit.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
activity = d['sessions'][0]['read_activity']
assert activity == {
    'audits': 1,
    'violating_audits': 1,
    'invalid_audits': [
        {'audit': 'r1x-codex-sol.read-audit.json', 'reason': 'read audit prompt hash mismatch'},
        {'audit': 'r2-gemini.read-audit.json', 'reason': 'malformed read audit JSON'},
    ],
    'tool_calls': 6,
    'tool_turns': 2,
    'tool_output_bytes': 250,
    'max_tool_output_bytes': 200,
    'recognized_tool_calls': 0,
    'source_read_calls': 0,
    'packet_shards': 0,
    'packet_bytes': 0,
    'packet_ranges': 0,
    'opened_source_ranges': 0,
    'finding_citations': 0,
    'patch_proof_calls': 0,
    'patch_proof_turns': 0,
    'patch_proof_visible_bytes': 0,
    'expected_patch_chunks': 0,
    'opened_patch_chunks': 0,
    'window_seats': 0,
    'chunk_seats': 0,
}, activity
assert d['totals']['processed_tokens'] == 1408, d
PY
    assert_eq "stale read audits are diagnosed and excluded without changing tokens" "$?" 0
  )
}

# A no-tool retry and a later same-label launch must each retain every nonempty paid stream.
test_profile_retry_streams() {
  ( seat_env; local S="$T/profile-retries"; seat_roster "$S"; echo "review" > "$S/p.md"
    rm -f "$T/args.grok-calls"
    SHIM_MODE=metered_notools_then_ok "$SCRIPTS/rev-seat.sh" grok "$S" 1 "$S/p.md" >/dev/null
    assert_eq "internal retry keeps one archived attempt" "$(find "$S" -maxdepth 1 -name 'r1-grok.stream.*.ndjson' | wc -l | tr -d ' ')" 1
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/internal.json"
    python3 - "$S/internal.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['totals']['calls'] == 2, d
assert d['totals']['processed_tokens'] == 12, d
PY
    assert_eq "internal retry contributes both metered attempts" "$?" 0

    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok "$S" 2 "$S/p.md" >/dev/null
    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok "$S" 2 "$S/p.md" >/dev/null
    assert_eq "same-label relaunch keeps one archived attempt" "$(find "$S" -maxdepth 1 -name 'r2-grok.stream.*.ndjson' | wc -l | tr -d ' ')" 1
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/outer.json"
    python3 - "$S/outer.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['totals']['calls'] == 4, d
PY
    assert_eq "same-label relaunch contributes both metered attempts" "$?" 0
  )
}

test_profile_accepts_safe_nonnumeric_labels() {
  ( local S="$T/profile-safe-label"; mkdir -p "$S"
    cat > "$S/roster.json" <<'JSON'
{"seats":[
  {"seat":"codex-sol","adapter":"codex"},
  {"seat":"grok","adapter":"grok"},
  {"seat":"opus","adapter":"claude"},
  {"seat":"opus-2","adapter":"claude"},
  {"seat":"bad","adapter":"codex"}
]}
JSON
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":10}}' \
      > "$S/rv1-codex-sol.stream.ndjson"
    printf '%s\n' '{"type":"end","usage":{"input_tokens":5,"cache_read_input_tokens":7,"output_tokens":3,"total_tokens":15,"cost_usd":0.5}}' \
      > "$S/rv1-grok.stream.ndjson"
    printf '%s\n' '{"type":"result","usage":{"input_tokens":10,"cache_creation_input_tokens":20,"cache_read_input_tokens":30,"output_tokens":4},"total_cost_usd":1.5}' \
      > "$S/rv1-opus.stream.ndjson"
    printf '%s\n' '{"type":"result","usage":{"input_tokens":8,"cache_creation_input_tokens":0,"cache_read_input_tokens":12,"output_tokens":2},"total_cost_usd":0.1}' \
      > "$S/rv1-opus-2.stream.ndjson"
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":-1,"output_tokens":1}}' \
      > "$S/rv1-bad.stream.ndjson"
    for seat in codex-sol grok opus opus-2 bad; do printf '2\n' > "$S/rv1-$seat.exit"; done
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); s = d['sessions'][0]; totals = d['totals']
assert s['calls'] == {'completed': 0, 'metered': 4, 'unmetered': 0}, s
assert totals['input_tokens'] == 192 and totals['output_tokens'] == 19, totals
assert totals['processed_tokens'] == 211 and totals['cost_usd'] == 2.1, totals
assert totals['cached_input_tokens'] == 20, totals
assert totals['cache_write_input_tokens'] == 20, totals
assert totals['cache_read_input_tokens'] == 49, totals
assert len(s['invalid_usage']) == 1 and s['invalid_usage'][0]['stream'] == 'rv1-bad.stream.ndjson', s
PY
    assert_eq "profiler meters invalid attempts with safe nonnumeric labels" "$?" 0
  )
}

# Invalid session arguments are rejected by argparse before any profile is aggregated.
test_profile_invalid_sessions() {
  ( local V="$T/profile-valid" M="$T/profile-missing" F="$T/profile-file"
    mkdir -p "$V"; printf 'not a directory\n' > "$F"
    expect_invalid_profile() {
      local label=$1 offending=$2; shift 2
      local mode rc
      for mode in text json; do
        if [ "$mode" = text ]; then
          "$SCRIPTS/rev-profile.py" "$@" > "$T/profile-$label-$mode.out" 2> "$T/profile-$label-$mode.err"
        else
          "$SCRIPTS/rev-profile.py" --json "$@" > "$T/profile-$label-$mode.out" 2> "$T/profile-$label-$mode.err"
        fi
        rc=$?
        [ "$rc" -ne 0 ] && ok "$label session is rejected in $mode mode" || fail "$label session is rejected in $mode mode" "exit $rc"
        assert_eq "$label session emits no partial output in $mode mode" "$(cat "$T/profile-$label-$mode.out")" ""
        assert_grep "$label error names the argument in $mode mode" "$T/profile-$label-$mode.err" "$offending"
      done
    }

    expect_invalid_profile missing "$M" "$M"
    expect_invalid_profile regular-file "$F" "$F"
    expect_invalid_profile mixed "$M" "$V" "$M"

    local U="$T/profile-unreadable"; mkdir -p "$U"; chmod 000 "$U"
    if [ ! -r "$U" ] || [ ! -x "$U" ]; then
      expect_invalid_profile unreadable "$U" "$U"
    else
      ok "unreadable-directory check skipped when permissions are not enforced"
    fi
    chmod 700 "$U"
  )
}

# Only an absent roster or a valid historical roster without receipt metadata may
# grandfather receiptless results. Present invalid metadata fails closed.
test_profile_invalid_receipt_metadata() {
  ( local ROOT="$T/profile-receipt-policy"; mkdir -p "$ROOT"
    make_session() {
      local name=$1 roster=$2 session
      session="$ROOT/$name"
      mkdir -p "$session"
      printf '%s' '{"summary":"receiptless","findings":[]}' > "$session/r1-opus.json"
      if [ "$roster" != absent ]; then printf '%s' "$roster" > "$session/roster.json"; fi
    }
    make_session absent absent
    make_session historical '{"seats":[{"seat":"opus","adapter":"claude"}]}'
    make_session corrupt '{'
    make_session nonobject '[]'
    make_session badversion '{"result_receipts":{"version":"1","legacy_no_exit_sha256":{}}}'
    make_session boolversion '{"result_receipts":{"version":true,"legacy_no_exit_sha256":{}}}'
    make_session zeroversion '{"result_receipts":{"version":0,"legacy_no_exit_sha256":{}}}'
    make_session badmap '{"result_receipts":{"version":1,"legacy_no_exit_sha256":[]}}'
    make_session baddigest '{"result_receipts":{"version":1,"legacy_no_exit_sha256":{"r1-opus.json":"abc"}}}'
    mkdir -p "$ROOT/unreadable/roster.json"
    printf '%s' '{"summary":"receiptless","findings":[]}' > "$ROOT/unreadable/r1-opus.json"

    "$SCRIPTS/rev-profile.py" --json "$ROOT"/* > "$ROOT/profile.json"
    python3 - "$ROOT/profile.json" <<'PY'
import json, sys
sessions = {item['session']: item for item in json.load(open(sys.argv[1]))['sessions']}
assert sessions['absent']['calls']['completed'] == 1, sessions
assert sessions['historical']['calls']['completed'] == 1, sessions
for name in ('corrupt', 'nonobject', 'badversion', 'boolversion', 'zeroversion',
             'badmap', 'baddigest', 'unreadable'):
    assert sessions[name]['calls']['completed'] == 0, (name, sessions[name])
PY
    assert_eq "invalid present receipt metadata cannot grandfather results" "$?" 0
  )
}

# Scope projections come only from intact evidence manifests, remain readable after the
# repository is gone, and never alter metered usage.
test_profile_evidence_scope() {
  ( local S="$T/profile-evidence" R="$T/profile-evidence-repo"
    export REV_SOURCE_CONTEXT=1 REV_PATCH_CHUNKS=1
    mkrepo "$R"; mkdir -p "$S"
    printf 'Review repository instruction words.\n' > "$R/AGENTS.md"
    git -C "$R" add AGENTS.md && git -C "$R" commit -qm 'add instructions'
    local base; base=$(git -C "$R" rev-parse HEAD)
    python3 - "$R" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for file_number in range(3):
    lines = (['def source_0():\n']
             + [f'    value_0_{line} = "{line:04d}-' + 'x' * 70 + '"\n'
                for line in range(600)]
             + ['    return value_0_599\n']) if file_number == 0 else [
                 f'value_{file_number}_{line} = {line}\n' for line in range(350)]
    (root / f'source_{file_number}.py').write_text(''.join(lines))
PY
    printf "REV_ROOT='%s'\nREV_BASE='%s'\nREV_SCOPE='branch'\n" "$R" "$base" > "$S/scope.env"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"agent"},{"seat":"grok","adapter":"agent"},{"seat":"opus","adapter":"agent"},{"seat":"opus-2","adapter":"agent"}]}' > "$S/roster.json"
    : > "$S/files.txt"; : > "$S/untracked.txt"
    python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 6 --phase discovery >/dev/null || {
      fail "profile fixture discovery prepares"; return;
    }
    local seat
    for seat in sol grok opus opus-2; do
      python3 "$SCRIPTS/rev-evidence.py" render "$S/r6-evidence.manifest.json" "$seat" \
        > "$S/r6-$seat.prompt.md" || { fail "profile fixture discovery prompt renders"; return; }
      printf '%s' '{"summary":"checked","findings":[]}' > "$S/r6-$seat.json"
      printf '0\n' > "$S/r6-$seat.exit"
      python3 - "$S/r6-evidence.manifest.json" "$seat" "$S/r6-$seat.stream.ndjson" "$R/source_0.py" <<'PY'
import json, pathlib, sys
manifest_path, seat, stream_path, source_path = sys.argv[1:]
session = pathlib.Path(manifest_path).parent
manifest = json.load(open(manifest_path))
events = []
assignment = manifest['assignments'][seat]
patch = pathlib.Path(assignment['patch'])
patch_lines = patch.read_text().splitlines(keepends=True)
if assignment['patch_read_mode'] == 'chunks':
    for row in manifest['patch_sets'][assignment['patch_set']]['chunks']:
        path = session / row['artifact']; call_id = 'patch-' + str(row['index'])
        events.extend([
            {'type':'assistant','message':{'id':call_id,'content':[{
                'type':'tool_use','id':call_id,'name':'Read','input':{'file_path':str(path)}}]}},
            {'type':'user','message':{'content':[{
                'type':'tool_result','tool_use_id':call_id,'content':path.read_text()}]}},
        ])
else:
    for start in range(1, len(patch_lines) + 1, 240):
        end = min(start + 239, len(patch_lines)); call_id = 'patch-' + str(start)
        events.extend([
            {'type':'assistant','message':{'id':call_id,'content':[{
                'type':'tool_use','id':call_id,'name':'Read',
                'input':{'file_path':str(patch),'offset':start,'limit':end - start + 1}}]}},
            {'type':'user','message':{'content':[{
                'type':'tool_result','tool_use_id':call_id,
                'content':''.join(patch_lines[start - 1:end])}]}},
        ])
for index, shard in enumerate(manifest['source_context']['seats'][seat]['shards']):
    path = session / shard['artifact']; call_id = 'packet-' + str(index)
    events.extend([
        {'type':'assistant','message':{'id':call_id,'content':[{
            'type':'tool_use','id':call_id,'name':'Read','input':{'file_path':str(path)}}]}},
        {'type':'user','message':{'content':[{
            'type':'tool_result','tool_use_id':call_id,'content':path.read_text()}]}},
    ])
for required in manifest['source_context']['seats'][seat]['required_source_ranges']:
    for segment in required['segments']:
        source = session / segment['artifact']; call_id = 'source-' + str(segment['index'])
        events.extend([
            {'type':'assistant','message':{'id':call_id,'content':[{
                'type':'tool_use','id':call_id,'name':'Read',
                'input':{'file_path':str(source)}}]}},
            {'type':'user','message':{'content':[{
                'type':'tool_result','tool_use_id':call_id,
                'content':source.read_text()}]}},
        ])
if manifest['source_context']['seats'][seat]['source_read_required'] \
        and not manifest['source_context']['seats'][seat]['required_source_ranges']:
    context = manifest['source_context']['seats'][seat]
    components = {component['id']: component for component in manifest['components']}
    boundary = sorted({path for component_id in context['components']
                       for path in components[component_id]['boundary']})
    if not boundary:
        raise SystemExit('missing assigned component boundary')
    source = pathlib.Path(source_path).parent / boundary[0]
    content = source.read_text().splitlines(keepends=True)
    if not content:
        raise SystemExit('assigned component boundary is empty')
    events.extend([
        {'type': 'assistant', 'message': {'id': 'source', 'content': [{
            'type':'tool_use','id':'source','name':'Read',
            'input':{'file_path':str(source),'offset':1,'limit':1}}]}},
        {'type': 'user', 'message': {'content': [{
            'type':'tool_result','tool_use_id':'source','content':content[0]}]}},
    ])
with open(stream_path, 'w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter agent \
        --raw "$S/r6-$seat.stream.ndjson" --prompt "$S/r6-$seat.prompt.md" \
        --root "$R" --session "$S" --out "$S/r6-$seat.read-audit.json" || {
          fail "profile fixture Agent transcript audits"; return;
        }
    done
    python3 "$SCRIPTS/rev-evidence.py" receipt "$S" 6 >/dev/null || {
      fail "profile fixture discovery receipt completes"; return;
    }
    python3 - "$R/source_0.py" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text(path.read_text().replace('value_0_0 = "0000-', 'value_0_0 = "changed-', 1))
PY
    python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 7 --phase verification \
      --assignment sol=correctness-boundaries \
      --assignment grok=security-state-api \
      --assignment opus=concurrency-resources-performance \
      --assignment opus-2=tests-observability-maintenance-regression >/dev/null || {
        fail "profile fixture verification prepares"; return;
      }
    for seat in sol grok opus opus-2; do
      python3 "$SCRIPTS/rev-evidence.py" render "$S/r7-evidence.manifest.json" "$seat" \
        > "$S/r7-$seat.prompt.md" || { fail "profile fixture prompt renders"; return; }
    done
    cp "$S/r7-evidence.manifest.json" "$S/expected-evidence.manifest.json"
    printf '{' > "$S/r8-evidence.manifest.json"
    cat > "$S/r7-sol.stream.ndjson" <<'EOF'
{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}
EOF
    rm -f "$S"/r6-* "$S/coverage-head.json"
    rm -rf "$R" "$S/evidence-objects"

    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" "$S/expected-evidence.manifest.json" "$R" "$S/evidence-objects" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
m = json.load(open(sys.argv[2]))
s = d['sessions'][0]
assert any(required['segments'] for packet in m['source_context']['seats'].values()
           for required in packet['required_source_ranges']), m['source_context']
assert s['usage']['processed_tokens'] == 15, s
session = __import__('pathlib').Path(sys.argv[2]).parent
evidence_words = len((session / 'r7-evidence.md').read_bytes().split())
instruction_words = len((session / 'r7-instructions.md').read_bytes().split())
assert instruction_words > 0, instruction_words
assert m['word_counts']['evidence'] == evidence_words + instruction_words, m['word_counts']
expected = {
    'valid_manifests': 1,
    'invalid_manifests': [{'manifest': 'r8-evidence.manifest.json', 'reason': 'malformed manifest JSON'}],
    'full_words': m['word_counts']['full'],
    'assigned_patch_words': m['word_counts']['assigned_patch'],
    'delta_words': m['word_counts']['delta'],
    'evidence_words': m['word_counts']['evidence'],
    'source_context_words': m['word_counts']['source_context'],
    'avoided_words': m['word_counts']['avoided'],
    'plan_words': 0,
    'closure_words': 0,
}

assert s['scope_projection'] == expected, (s, expected)
assert expected['avoided_words'] > 0, expected
assert expected['delta_words'] > 0, expected
assert d['totals']['processed_tokens'] == 15, d
assert d['totals']['scope_projection'] == {
    'valid_manifests': 1,
    'invalid_manifests': 1,
    'full_words': expected['full_words'],
    'assigned_patch_words': expected['assigned_patch_words'],
    'delta_words': expected['delta_words'],
    'evidence_words': expected['evidence_words'],
    'source_context_words': expected['source_context_words'],
    'avoided_words': expected['avoided_words'],
    'plan_words': 0,
    'closure_words': 0,
}, d
assert not __import__('pathlib').Path(sys.argv[3]).exists(), sys.argv[3]
assert not __import__('pathlib').Path(sys.argv[4]).exists(), sys.argv[4]
PY
    assert_eq "profile validates preserved evidence offline without changing provider usage" "$?" 0

    "$SCRIPTS/rev-profile.py" "$S" > "$S/profile.txt"
    local full assigned delta evidence avoided
    read -r full assigned delta evidence avoided < <(python3 - "$S/expected-evidence.manifest.json" <<'PY'
import json, sys
w = json.load(open(sys.argv[1]))['word_counts']
print(w['full'], w['assigned_patch'], w['delta'], w['evidence'], w['avoided'])
PY
)
    assert_grep "text profile labels projected scope words" "$S/profile.txt" \
      "projected_scope_words=full:$full assigned:$assigned delta:$delta evidence:$evidence avoided:$avoided"
    assert_grep "text profile labels invalid evidence" "$S/profile.txt" 'evidence_invalid=1'
    assert_grep "text profile explains invalid evidence" "$S/profile.txt" \
      'r8-evidence\.manifest\.json: malformed manifest JSON'
    [ ! -e "$S/evidence-objects" ] && ok "offline profiling does not recreate evidence objects" || \
      fail "offline profiling does not recreate evidence objects"

    rm "$S/r7-sol.prompt.md"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile-unused.json"
    python3 - "$S/profile-unused.json" <<'PY'
import json, sys
scope = json.load(open(sys.argv[1]))['sessions'][0]['scope_projection']
assert scope == {
    'valid_manifests': 0,
    'invalid_manifests': [
        {'manifest': 'r7-evidence.manifest.json', 'reason': 'evidence prompt unavailable: sol'},
        {'manifest': 'r8-evidence.manifest.json', 'reason': 'malformed manifest JSON'},
    ],
    'full_words': 0,
    'assigned_patch_words': 0,
    'delta_words': 0,
    'evidence_words': 0,
    'source_context_words': 0,
    'avoided_words': 0,
    'plan_words': 0,
    'closure_words': 0,
}, scope
PY
    assert_eq "manifest without every hashed prompt cannot claim projected savings" "$?" 0
  )
}

test_profile_source_context_activity() {
  ( local S="$T/profile-source-context"; mkdir -p "$S"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"}]}' > "$S/roster.json"
    printf '{}\n' > "$S/r4-evidence.manifest.json"
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}' > "$S/r4-sol.stream.ndjson"
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r4-sol.json"
    printf '0\n' > "$S/r4-sol.exit"
    python3 - "$S" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = root / 'r4-evidence.manifest.json'
manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
(root / 'r4-sol.prompt.md').write_text('Evidence manifest SHA-256: ' + manifest_hash + '\nAssigned scope: semantic\n')
prompt = root / 'r4-sol.prompt.md'; stream = root / 'r4-sol.stream.ndjson'; result = root / 'r4-sol.json'
audit = {
    'schema_version': 2, 'status': 'valid', 'narrow': True, 'adapter': 'codex',
    'prompt_sha256': hashlib.sha256(prompt.read_bytes()).hexdigest(),
    'stream_sha256': hashlib.sha256(stream.read_bytes()).hexdigest(),
    'result_sha256': hashlib.sha256(result.read_bytes()).hexdigest(),
    'evidence_manifest_sha256': manifest_hash, 'violations': [],
    'tool_calls': 3, 'tool_turns': 2, 'tool_output_bytes': 1200, 'max_tool_output_bytes': 700,
    'recognized_tool_calls': 3, 'source_read_calls': 1, 'packet_shards': 2,
    'packet_bytes': 900, 'packet_ranges': 4, 'opened_source_ranges': 1,
    'patch_proof_mode': 'chunks', 'patch_proof_calls': 2, 'patch_proof_turns': 2,
    'patch_proof_visible_bytes': 280, 'expected_patch_chunks': 2, 'opened_patch_chunks': 2,
    'finding_citations': 0, 'source_ranges': [
        {'path':'src/a.py','line_start':1,'line_end':20,'origin':'packet'},
        {'path':'src/a.py','line_start':30,'line_end':40,'origin':'packet'},
        {'path':'src/c.py','line_start':1,'line_end':10,'origin':'packet'},
        {'path':'src/d.py','line_start':5,'line_end':15,'origin':'packet'},
        {'path':'src/b.py','line_start':40,'line_end':60,'origin':'tool'},
    ],
}

(root / 'r4-sol.read-audit.json').write_text(json.dumps(audit))
PY
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); a = d['sessions'][0]['read_activity']
assert a['packet_shards'] == 2 and a['packet_bytes'] == 900, a
assert a['packet_ranges'] == 4 and a['opened_source_ranges'] == 1, a
assert a['source_read_calls'] == 1 and a['recognized_tool_calls'] == 3, a
assert a['finding_citations'] == 0, a
assert a['patch_proof_calls'] == 2 and a['patch_proof_turns'] == 2, a
assert a['patch_proof_visible_bytes'] == 280, a
assert a['expected_patch_chunks'] == a['opened_patch_chunks'] == 2, a
assert a['chunk_seats'] == 1 and a['window_seats'] == 0, a
assert d['totals']['read_activity']['packet_bytes'] == 900, d
assert d['totals']['read_activity']['patch_proof_calls'] == 2, d
assert d['totals']['processed_tokens'] == 12, d
PY
    assert_eq "profile separates packet bytes and source-range activity from raw tokens" "$?" 0
    "$SCRIPTS/rev-profile.py" "$S" > "$S/profile.txt"
    assert_grep "text profile reports packet and source ranges separately" "$S/profile.txt" \
      'packet_shards:2 packet_bytes:900 packet_ranges:4 source_reads:1 opened_ranges:1 finding_citations:0'
    assert_grep "text profile reports patch proof activity separately" "$S/profile.txt" \
      'patch_proof_calls:2 patch_proof_turns:2 patch_proof_bytes:280 expected_chunks:2 opened_chunks:2 patch_modes:window:0,chunk:1'
  )
}

test_profile_rejects_invalid_usage_numbers() {
  ( local S="$T/profile-invalid-numbers"; mkdir -p "$S"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"}]}' > "$S/roster.json"
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}' > "$S/r1-sol.stream.ndjson"
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":-8,"output_tokens":1}}' > "$S/r2-sol.stream.ndjson"
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":true,"output_tokens":1}}' > "$S/r3-sol.stream.ndjson"
    printf '%s\n' '{"type":"end","usage":{"total_tokens":2,"output_tokens":3}}' > "$S/r4-grok.stream.ndjson"
    printf '%s\n' '{"type":"end","usage":{"input_tokens":4,"output_tokens":1,"cost_usd":NaN}}' > "$S/r5-grok.stream.ndjson"
    printf '%s\n' '{"type":"end","usage":{"input_tokens":4,"output_tokens":1},"cost_usd":false}' > "$S/r6-grok.stream.ndjson"
    printf '%s\n' '{"type":"turn.completed","usage":false}' > "$S/r7-sol.stream.ndjson"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, math, sys
raw = open(sys.argv[1]).read()
assert 'NaN' not in raw and 'Infinity' not in raw, raw
d = json.loads(raw); s = d['sessions'][0]
assert d['totals']['calls'] == 1 and d['totals']['processed_tokens'] == 12, d
assert len(s['invalid_usage']) == 6, s
assert all(math.isfinite(value) for value in (d['totals']['cost_usd'],)), d
PY
    assert_eq "profile excludes invalid numeric usage without reducing valid totals" "$?" 0
    "$SCRIPTS/rev-profile.py" "$S" > "$S/profile.txt"
    assert_grep "text profile reports rejected provider usage" "$S/profile.txt" 'usage_invalid=6'
  )
}

test_profile_requires_complete_evidence_patch_proofs() {
  ( local S="$T/profile-patch-proof-completeness"; mkdir -p "$S"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"}]}' > "$S/roster.json"
    printf 'prompt\n' > "$S/r1-sol.prompt.md"
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r1-sol.json"
    printf '{}\n' > "$S/r1-sol.stream.ndjson"
    printf '{}\n' > "$S/r1-evidence.manifest.json"
    python3 - "$S" <<'PY'
import hashlib, json, pathlib, sys
s = pathlib.Path(sys.argv[1]); prompt=s/'r1-sol.prompt.md'; result=s/'r1-sol.json'
stream=s/'r1-sol.stream.ndjson'; manifest=s/'r1-evidence.manifest.json'
base={
 'schema_version':2,'status':'valid','narrow':True,'adapter':'codex','violations':[],
 'prompt_sha256':hashlib.sha256(prompt.read_bytes()).hexdigest(),
 'stream_sha256':hashlib.sha256(stream.read_bytes()).hexdigest(),
 'result_sha256':hashlib.sha256(result.read_bytes()).hexdigest(),
 'evidence_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
 'tool_calls':3,'tool_turns':3,'tool_output_bytes':100,'max_tool_output_bytes':50,
 'recognized_tool_calls':3,'source_read_calls':0,'packet_shards':0,'packet_bytes':0,
 'packet_ranges':0,'opened_source_ranges':0,'finding_citations':0,'source_ranges':[],
 'patch_proof_mode':'chunks','patch_proof_calls':2,'patch_proof_turns':2,
 'patch_proof_visible_bytes':80,'expected_patch_chunks':2,'opened_patch_chunks':1,
}
(s/'r1-sol.read-audit.json').write_text(json.dumps(base))
PY
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1])); a=d['sessions'][0]['read_activity']
assert a['audits']==0 and a['violating_audits']==0, a
assert a['invalid_audits']==[{
    'audit':'r1-sol.read-audit.json',
    'reason':'invalid patch proof audit structure',
}], a
assert d['totals']['read_activity']['invalid_audits']==1, d
PY
    assert_eq "profile diagnoses an incomplete valid patch proof exactly" "$?" 0
    python3 - "$S/r1-sol.read-audit.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d['opened_patch_chunks']=d['expected_patch_chunks']
open(p,'w').write(json.dumps(d))
PY
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile-complete.json"
    python3 - "$S/profile-complete.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1])); a=d['sessions'][0]['read_activity']
assert a['audits']==1 and a['violating_audits']==0, a
assert a['invalid_audits']==[], a
assert a['expected_patch_chunks']==a['opened_patch_chunks']==2, a
assert d['totals']['read_activity']['audits']==1, d
assert d['totals']['read_activity']['invalid_audits']==0, d
PY
    assert_eq "profile counts one complete valid patch proof" "$?" 0
    python3 - "$S/r1-sol.read-audit.json" <<'PY'
import json, sys
p=sys.argv[1]; d=json.load(open(p)); d['status']='invalid'
d['violations']=[{'code':'missing-assigned-patch-chunk','tool':'codex'}]
d['opened_patch_chunks']=d['expected_patch_chunks']-1
open(p,'w').write(json.dumps(d))
PY
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile-invalid.json"
    python3 - "$S/profile-invalid.json" <<'PY'
import json,sys
a=json.load(open(sys.argv[1]))['sessions'][0]['read_activity']
assert a['audits']==1 and a['violating_audits']==1 and not a['invalid_audits'], a
PY
    assert_eq "profile keeps incomplete counters for invalid diagnostics" "$?" 0
    printf '%s\n' '{"summary":"uncited","findings":[{"severity":"P1","file":"src/x.ts","line_start":1,"line_end":1,"claim":"x","evidence":"x","suggested_fix":"x","confidence":0.9}]}' > "$S/r1-sol.json"
    python3 - "$S/r1-sol.read-audit.json" "$S/r1-sol.json" <<'PY'
import hashlib,json,sys
p,result=sys.argv[1:]; d=json.load(open(p))
d['violations']=[{'code':'unsubstantiated-finding-range','tool':'codex'}]
d['finding_citations']=0; d['opened_patch_chunks']=d['expected_patch_chunks']
d['result_sha256']=hashlib.sha256(open(result,'rb').read()).hexdigest()
open(p,'w').write(json.dumps(d))
PY
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile-uncited.json"
    python3 - "$S/profile-uncited.json" <<'PY'
import json,sys
a=json.load(open(sys.argv[1]))['sessions'][0]['read_activity']
assert a['audits']==1 and a['violating_audits']==1 and not a['invalid_audits'], a
PY
    assert_eq "profile counts a well-formed invalid uncited-finding audit" "$?" 0
    rm "$S/r1-sol.json"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile-discarded.json"
    python3 - "$S/profile-discarded.json" <<'PY'
import json,sys
a=json.load(open(sys.argv[1]))['sessions'][0]['read_activity']
assert a['audits']==1 and a['violating_audits']==1 and not a['invalid_audits'], a
PY
    assert_eq "profile counts an invalid audit after the runner discards its result" "$?" 0
    python3 - "$S/r1-sol.read-audit.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d.pop('patch_proof_mode'); open(p,'w').write(json.dumps(d))
PY
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile-missing.json"
    assert_grep "profile rejects evidence audits without patch mode" "$S/profile-missing.json" \
      'evidence audit lacks patch proof counters'
  )
}

test_profile_plan_label_classification() {
  python3 - "$SCRIPTS/rev-profile.py" <<'PY'
import importlib.util, pathlib, sys
spec=importlib.util.spec_from_file_location('profile',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
for name in ('r1p-opus.prompt.md','r1pf-opus.prompt.md','r12-plan-opus.json'):
    assert module.is_plan(pathlib.Path(name)), name
for name in ('r1-sol.prompt.md','r1-performance.json','r2-planner.stream.ndjson','r3x-plan-opus.json'):
    assert not module.is_plan(pathlib.Path(name)), name
PY
  assert_eq "profile recognizes plan fallback labels without code false positives" "$?" 0
}
