# shellcheck shell=bash
# Token categories are observational and never infer unreported billing.
test_profile_usage_normalizes_categories() {
  ( local S="$T/profile-usage-categories"; mkdir -p "$S"
    cat > "$S/r1-opus.stream.ndjson" <<'JSON'
{"type":"result","usage":{"input_tokens":10,"cache_creation_input_tokens":20,"cache_read_input_tokens":30,"output_tokens":8,"output_tokens_details":{"thinking_tokens":3},"cache_creation":{"ephemeral_5m_input_tokens":7,"ephemeral_1h_input_tokens":13}},"total_cost_usd":0}
JSON
    cat > "$S/r1-sol.stream.ndjson" <<'JSON'
{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":20,"cache_write_input_tokens":10,"output_tokens":11,"reasoning_output_tokens":4}}
JSON
    printf '%s\n' '{"type":"end","usage":{"input_tokens":5,"cache_read_input_tokens":7,"output_tokens":3,"total_tokens":15}}' > "$S/r1-grok.stream.ndjson"
    printf '%s\n' '{"type":"result","stats":{"input_tokens":10,"output_tokens":2}}' > "$S/r1-gemini.stream.ndjson"
    printf '%s\n' '{"type":"result","usage":{"input_tokens":0,"output_tokens":0},"total_cost_usd":0}' > "$S/r2-opus-free.stream.ndjson"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); u = d['totals']
assert u['calls'] == 5, u
assert u['uncached_input_tokens'] == 95, u
assert u['reasoning_output_tokens'] == 7, u
assert u['input_tokens'] == 182 and u['output_tokens'] == 24, u
assert u['processed_tokens'] == 206, u
assert u['cache_write_input_tokens'] == 30 and u['cache_read_input_tokens'] == 37, u
assert u['cache_write_5m_input_tokens'] == 7 and u['cache_write_1h_input_tokens'] == 13, u
assert u['cost_usd'] == 0 and u['cost_usd_known_calls'] == 2 and u['cost_usd_unknown_calls'] == 3, u
assert d['sessions'][0]['providers']['claude']['uncached_input_tokens'] == 10, d
assert d['sessions'][0]['providers']['codex']['uncached_input_tokens'] == 70, d
PY
    assert_eq "profile retains reasoning as output detail and distinguishes reported zero cost" "$?" 0
  )
}

test_profile_usage_deduplicates_native_messages() {
  ( local S="$T/profile-usage-native"; mkdir -p "$S"
    printf '%s\n' '{"seats":[{"seat":"opus","adapter":"agent"}]}' > "$S/roster.json"
    cat > "$S/r1-opus.stream.ndjson" <<'JSON'
{"type":"assistant","message":{"id":"native-a","usage":{"input_tokens":5,"output_tokens":2}}}
{"type":"assistant","message":{"id":"native-a","usage":{"input_tokens":5,"output_tokens":6}}}
{"type":"assistant","message":{"id":"native-b","usage":{"input_tokens":3,"output_tokens":1}}}
JSON
    cp "$S/r1-opus.stream.ndjson" "$S/r1-opus.stream.jsonl"
    printf '%s\n' '{"type":"assistant","message":{"id":"native-c","usage":{"input_tokens":9,"output_tokens":2}}}' > "$S/r2-opus.stream.ndjson"
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r1-opus.json"
    printf '0\n' > "$S/r1-opus.exit"
    printf '2\n' > "$S/r2-opus.exit"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); s = d['sessions'][0]
assert s['usage']['input_tokens'] == 17 and s['usage']['output_tokens'] == 9, s
assert s['usage']['processed_tokens'] == 26, s
assert s['calls'] == {'completed':1, 'metered':2, 'unmetered':0}, s
assert s['providers']['agent']['metered_calls'] == 2, s
assert s['providers']['agent']['completed_calls'] == 1, s
assert s['usage']['cost_usd_unknown_calls'] == 2, s
assert s['invalid_usage'] == [], s
PY
    assert_eq "native streaming blocks and mirrored files contribute once per message identity" "$?" 0
  )
}

test_profile_usage_prefers_terminal_totals() {
  ( local S="$T/profile-usage-terminal"; mkdir -p "$S"
    cat > "$S/r1-opus.stream.ndjson" <<'JSON'
{"type":"assistant","message":{"id":"terminal-mirror","usage":{"input_tokens":100,"output_tokens":10}}}
{"type":"result","is_error":true,"usage":{"input_tokens":5,"output_tokens":2},"total_cost_usd":0.4}
JSON
    printf '2\n' > "$S/r1-opus.exit"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); s = d['sessions'][0]
assert s['calls'] == {'completed':0, 'metered':1, 'unmetered':0}, s
assert s['usage']['processed_tokens'] == 7 and s['usage']['cost_usd'] == 0.4, s
assert s['usage']['cost_usd_known_calls'] == 1, s
PY
    assert_eq "terminal usage replaces per-message usage while retaining failed attempt cost" "$?" 0
  )
}

test_profile_usage_host_envelope_attribution() {
  ( local S="$T/profile-usage-host" H="$T/host-usage.jsonl" H2="$T/host-usage-copy.jsonl"; mkdir -p "$S"
    python3 - "$S" "$H" "$H2" <<'PY'
import json, pathlib, sys
s, host, copy = map(pathlib.Path, sys.argv[1:])
def row(mid, inputs, outputs, command=None):
    content = ([{'type':'tool_use', 'name':'Bash', 'input':{'command':command}}]
               if command else [{'type':'text','text':'private text must not appear in the report'}])
    return {'type':'assistant','message':{'id':mid,'model':'fixture-model',
            'usage':{'input_tokens':inputs,'output_tokens':outputs},'content':content}}
leaf = row('leaf-mirror', 4, 1)
(s/'r1-opus.stream.ndjson').write_text(json.dumps(leaf)+'\n')
rows = [leaf, row('host-status',10,2, f'rev-status.sh {s}'),
        row('host-status',10,5, f'rev-status.sh {s}'),
        row('host-other',20,2), row('host-collision',30,3, f'rev-status.sh {s}-other'),
        row('host-script-collision',40,4, f'rev-status.sh-extra {s}'),
        row('host-text-collision',50,5, f'echo "rev-status.sh {s}"'),
        row('host-quoted',6,1, f'python3 /plugin/scripts/rev-evidence.py validate --session "{s}"'),
        row('host-no-operation',7,1, f'cat {s}/context.md')]
host.write_text(''.join(json.dumps(r)+'\n' for r in rows))
copy.write_text(json.dumps(rows[2])+'\n')
PY
    "$SCRIPTS/rev-profile.py" --json --host-log "$H" --host-log "$H" --host-log "$H2" "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
raw = open(sys.argv[1]).read(); d = json.loads(raw); h = d['host_usage']
assert 'private text' not in raw and 'leaf-mirror' not in raw and 'host-status' not in raw, raw
assert d['totals']['processed_tokens'] == 5 and d['totals']['calls'] == 1, d
assert h['files'] == 2 and h['duplicate_inputs'] == 1, h
assert h['leaf_overlap_messages'] == 1, h
assert h['envelope']['calls'] == 7 and h['envelope']['processed_tokens'] == 184, h
assert h['council_operations']['calls'] == 2 and h['council_operations']['processed_tokens'] == 22, h
assert h['envelope']['cost_usd_unknown_calls'] == 7, h
assert h['invalid_usage'] == [], h
PY
    assert_eq "explicit host inputs separate mixed envelopes from exact session Council operations" "$?" 0
    "$SCRIPTS/rev-profile.py" --host-log "$H" "$S" > "$S/profile.txt"
    assert_grep "text host report labels its mixed envelope" "$S/profile.txt" '^HOST_ENVELOPE '
    assert_grep "text host report labels conservative Council operations" "$S/profile.txt" '^HOST_COUNCIL_OPERATIONS '
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/default.json"
    assert_nogrep "default profile never discovers host logs" "$S/default.json" 'host_usage'
    assert_exit "missing explicit host log is rejected" 2 "$SCRIPTS/rev-profile.py" --host-log "$T/missing-host" "$S"
  )
}

test_profile_usage_discloses_malformed_records() {
  ( local S="$T/profile-usage-malformed" H="$T/host-malformed.jsonl"; mkdir -p "$S"
    python3 - "$S" "$H" <<'PY'
import json, pathlib, sys
s, host = map(pathlib.Path, sys.argv[1:])
bad = [
 {'input_tokens':True,'output_tokens':1},
 {'input_tokens':1,'output_tokens':1,'reasoning_output_tokens':2},
 {'input_tokens':1,'output_tokens':1,'output_tokens_details':{'thinking_tokens':False}},
 {'input_tokens':1,'output_tokens':1,'cache_creation':{'ephemeral_5m_input_tokens':-1}},
 {'input_tokens':1,'output_tokens':1,'cached_input_tokens':2},
 {'input_tokens':1,'output_tokens':1,'cache_creation_input_tokens':1,
  'cache_creation':{'ephemeral_5m_input_tokens':2}},
]
for n, usage in enumerate(bad, 1):
    (s/f'r{n}-sol.stream.ndjson').write_text(json.dumps({'type':'turn.completed','usage':usage})+'\n')
(s/'r7-sol.stream.ndjson').write_text('{broken\n'+json.dumps({'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':1}})+'\n')
(s/'r8-opus.stream.ndjson').write_text(json.dumps({'type':'result','usage':{'input_tokens':1,'output_tokens':1,'cost_usd':0.2},'total_cost_usd':False})+'\n')
(s/'r9-opus.stream.ndjson').write_text(json.dumps({'type':'result','usage':{'input_tokens':1,'output_tokens':1},'total_cost_usd':10**400})+'\n')
rows = [json.dumps({'type':'assistant','message':{'id':'good','usage':{'input_tokens':3,'output_tokens':1}}}),
        '{broken', json.dumps({'type':'assistant','message':{'id':'bad','usage':bad[0]}}),
        json.dumps({'type':'assistant','message':{'usage':{'input_tokens':3,'output_tokens':1}}})]
host.write_text('\n'.join(rows)+'\n')
PY
    "$SCRIPTS/rev-profile.py" --json --host-log "$H" "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); s = d['sessions'][0]; h = d['host_usage']
assert s['usage']['calls'] == 1 and s['usage']['processed_tokens'] == 3, s
assert len(s['invalid_usage']) == 9, s
assert h['envelope']['processed_tokens'] == 4 and h['envelope']['calls'] == 1, h
assert len(h['invalid_usage']) == 3, h
assert any('message identity' in item['reason'] for item in h['invalid_usage']), h
assert any('malformed JSON' in item['reason'] for item in s['invalid_usage']), s
PY
    assert_eq "invalid usage is disclosed without discarding other metered records" "$?" 0
  )
}

test_profile_usage_incomplete_result_is_metered() {
  ( local S="$T/profile-usage-incomplete"; mkdir -p "$S"
    printf '%s\n' '{"summary":"INCOMPLETE PROOF: assigned source remains unread","findings":[]}' > "$S/r1-sol.json"
    printf '0\n' > "$S/r1-sol.exit"
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":2,"reasoning_output_tokens":1}}' > "$S/r1-sol.stream.ndjson"
    printf '%s\n' '{"summary":"INCOMPLETE PROOF legacy unfinished obligation","findings":[]}' > "$S/r2-sol.json"
    printf '0\n' > "$S/r2-sol.exit"
    cp "$S/r1-sol.stream.ndjson" "$S/r2-sol.stream.ndjson"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); s = d['sessions'][0]
assert s['calls'] == {'completed':0, 'metered':2, 'unmetered':0}, s
assert s['results']['code'] == {'calls':0, 'findings':0}, s
assert s['usage']['processed_tokens'] == 28 and s['usage']['reasoning_output_tokens'] == 2, s
PY
    assert_eq "explicit incomplete proof remains metered even with an exit-zero result" "$?" 0
  )
}


test_profile_usage_deduplicates_terminal_identity() {
  ( local S="$T/profile-usage-terminal-mirrors"; mkdir -p "$S"
    cat > "$S/r1-opus.stream.ndjson" <<'JSON'
{"type":"assistant","message":{"id":"terminal-shared","usage":{"input_tokens":100,"output_tokens":10}}}
{"type":"result","usage":{"input_tokens":5,"output_tokens":2},"total_cost_usd":0.4}
JSON
    cp "$S/r1-opus.stream.ndjson" "$S/r1-opus.stream.jsonl"
    printf '%s\n' '{"type":"result","usage":{"input_tokens":3,"output_tokens":1}}' > "$S/r2-opus.stream.ndjson"
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json"
    python3 - "$S/profile.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); s = d['sessions'][0]
assert s['usage']['calls'] == 2 and s['usage']['processed_tokens'] == 11, s
assert s['usage']['cost_usd'] == 0.4, s
assert s['usage']['unidentified_terminal_calls'] == 1, s
assert d['totals']['unidentified_terminal_calls'] == 1, d
PY
    assert_eq "terminal mirrors with stable native identities contribute once and unidentified streams stay disclosed" "$?" 0
    "$SCRIPTS/rev-profile.py" "$S" > "$S/profile.txt"
    assert_grep "text profile discloses terminal identity limits" "$S/profile.txt" 'terminal_identity_unknown=1'
  )
}
