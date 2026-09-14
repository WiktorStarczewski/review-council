#!/bin/bash

test_provider_envelope_replay() {
  ( local R="$T/provider-envelope-root" S="$T/provider-envelope-session"
    mkdir -p "$R/src" "$S"
    printf 'alpha\nterminal\n\n' > "$R/src/provider-contract.txt"
    printf 'Assigned scope: full\n' > "$S/prompt.md"

    local adapter fixture out
    for adapter in codex grok claude; do
      fixture="$FX/provider-contract-$adapter.ndjson"
      out="$S/$adapter-audit.json"
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" \
        --raw "$fixture" --prompt "$S/prompt.md" --root "$R" --session "$S" --out "$out" \
        >/dev/null 2>&1
      assert_eq "$adapter preserved evidence envelope passes the production auditor" "$?" 0
      assert_grep "$adapter replay proves the source bytes" "$out" '"opened_source_ranges":1'
    done
    assert_grep "Claude terminal blank rendering remains byte exact" "$S/claude-audit.json" \
      '"status":"valid"'

    for adapter in codex grok claude; do
      python3 - "$FX/provider-contract-$adapter.ndjson" "$S/$adapter-missing.ndjson" <<'PY'
import json, pathlib, sys
source, target = map(pathlib.Path, sys.argv[1:])
rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
if sys.argv[1].endswith('codex.ndjson'):
    rows = [row for row in rows if not (row.get('type') == 'item.completed'
            and (row.get('item') or {}).get('id') == 'contract-read')]
elif sys.argv[1].endswith('grok.ndjson'):
    rows = [row for row in rows if not (row.get('type') == 'tool_call_update'
            and row.get('toolCallId') == 'contract-read' and row.get('status') == 'completed')]
else:
    rows = [row for row in rows if row.get('type') != 'user']
target.write_text(''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows))
PY
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" \
        --raw "$S/$adapter-missing.ndjson" --prompt "$S/prompt.md" --root "$R" --session "$S" \
        --out "$S/$adapter-missing-audit.json" >/dev/null 2>&1
      assert_eq "$adapter missing source proof remains fatal" "$?" 2
      assert_grep "$adapter missing proof has a stable failure" "$S/$adapter-missing-audit.json" \
        '"code":"missing-tool-output"'
    done
  )
}

test_provider_envelope_replay_narrow_advisory() {
  ( local R="$T/provider-narrow-root" S="$T/provider-narrow-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    printf 'alpha\nterminal\n\n' > "$R/src/provider-contract.txt"
    git -C "$R" add src/provider-contract.txt
    git -C "$R" commit -qm 'provider contract source'
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf 'alpha\nchanged\n\n' > "$R/src/provider-contract.txt"
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/provider-contract.txt\n' > "$S/files.txt"
    : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"}]}' \
      > "$S/roster.json"
    local manifest prompt bundle
    manifest=$(REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare \
      "$S" 1 --phase discovery) || return
    bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["assignments"]["opus"]["bundle"])' \
      "$manifest") || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1 opus "$bundle" provider-contract \
      --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r1-opus.json"

    python3 - "$FX/provider-contract-claude.ndjson" "$manifest" \
      "$S/r1-opus.stream.ndjson" "$R" <<'PY'
import copy, json, pathlib, sys
fixture, manifest_path, output, root = map(pathlib.Path, sys.argv[1:])
template = [json.loads(line) for line in fixture.read_text().splitlines() if line.strip()]
prefix = next(row for row in template if row.get('type') == 'system')
assistant = next(row for row in template if row.get('type') == 'assistant')
user = next(row for row in template if row.get('type') == 'user')
suffix = next(row for row in template if row.get('type') == 'result')
manifest = json.loads(manifest_path.read_text())
assignment = manifest['assignments']['opus']
context = manifest['source_context']['seats']['opus']
session = manifest_path.parent

def rendered_read(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    rendered = ''.join(str(index) + '\t' + line for index, line in enumerate(lines, 1))
    if text.endswith('\n'):
        rendered += str(len(lines) + 1) + '\t'
    return rendered

rows = [prefix]
def call(call_id, name, data, content):
    call_row = copy.deepcopy(assistant)
    call_row['message']['id'] = 'message-' + call_id
    block = call_row['message']['content'][0]
    block['id'] = call_id; block['name'] = name; block['input'] = data
    result_row = copy.deepcopy(user)
    result_row['message']['content'][0]['tool_use_id'] = call_id
    result_row['message']['content'][0]['content'] = content
    rows.extend((call_row, result_row))

patch = pathlib.Path(assignment['patch'])
patch_lines = len(patch.read_bytes().splitlines())
call('patch', 'Read', {'file_path': str(patch), 'offset': 1, 'limit': patch_lines},
     rendered_read(patch.read_bytes()))
for index, shard in enumerate(context['shards'], 1):
    path = session / shard['artifact']
    call('packet-' + str(index), 'Read', {'file_path': str(path)}, rendered_read(path.read_bytes()))
index = session / f"r{manifest['label']}-evidence.md"
call('evidence-index', 'Read', {'file_path': str(index)}, rendered_read(index.read_bytes()))
source = root / 'src/provider-contract.txt'
call('source', 'Read', {'file_path': 'src/provider-contract.txt', 'offset': 1, 'limit': 3},
     rendered_read(source.read_bytes()))
call('unused', 'Bash', {'command': "sed -n '1,241p' src/provider-contract.txt"},
     source.read_text())
rows.append(suffix)
output.write_text(''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r1-opus.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r1-opus.read-audit.json" >/dev/null 2>&1
    assert_eq "Claude envelope keeps unused read-only exploration advisory" "$?" 0
    assert_grep "unused Claude exploration is recorded as advisory" \
      "$S/r1-opus.read-audit.json" '"advisories":\[[^]]*"code":"unbounded-shell-output"'
    assert_grep "Claude terminal blank source read still proves exact bytes" \
      "$S/r1-opus.read-audit.json" '"opened_source_ranges":1'
    assert_grep "advisory leaves no fatal violation" "$S/r1-opus.read-audit.json" \
      '"violations":\[\]'

    python3 - "$S/r1-opus.stream.ndjson" "$S/r1-opus-missing.stream.ndjson" <<'PY'
import json, pathlib, sys
source, target = map(pathlib.Path, sys.argv[1:])
rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
rows = [row for row in rows if not (
    row.get('type') == 'assistant'
    and any(block.get('id') == 'source' for block in (row.get('message') or {}).get('content', [])
              if isinstance(block, dict))) and not (
    row.get('type') == 'user'
    and any(block.get('tool_use_id') == 'source'
            for block in (row.get('message') or {}).get('content', []) if isinstance(block, dict)))]
target.write_text(''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r1-opus-missing.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r1-opus-missing.read-audit.json" >/dev/null 2>&1
    assert_eq "missing required Claude source proof remains fatal" "$?" 2
    assert_grep "missing required proof has a stable failure" \
      "$S/r1-opus-missing.read-audit.json" '"code":"missing-required-source-read"'
  )
}

test_provider_contract_receipt_identity() {
  ( local R="$T/provider-contract-repo" S="$T/provider-contract-session"
    mkrepo "$R"; mkdir -p "$R/plugins/review-council/.codex-plugin" \
      "$R/plugins/review-council/scripts" "$S"
    printf '{}\n' > "$R/plugins/review-council/.codex-plugin/plugin.json"
    printf 'old boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    git -C "$R" add . && git -C "$R" commit -qm 'provider contract base'
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf 'new boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    cat > "$S/roster-a.json" <<'JSON'
{"seats":[
 {"seat":"codex-sol","adapter":"codex","model":"gpt-5.6-sol","effort":"max","extra":false},
 {"seat":"codex-terra","adapter":"codex","model":"gpt-5.6-terra","effort":"max","extra":false},
 {"seat":"opus","adapter":"claude","model":"opus","effort":"max","extra":false},
 {"seat":"sonnet","adapter":"claude","model":"sonnet","effort":"max","extra":false},
 {"seat":"codex-review","adapter":"codex","model":"gpt-5.6-sol","effort":"max","extra":true}]}
JSON
    sed 's/"model":"sonnet"/"model":"opus"/' "$S/roster-a.json" > "$S/roster-b.json"
    python3 - "$S/roster-a.json" "$S/roster-gemini.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
data['seats'][-2] = {
    'seat':'gemini','adapter':'gemini','model':'gemini-2.5-pro','effort':None,'extra':False}
open(sys.argv[2], 'w').write(json.dumps(data))
PY
    local runner="$T/provider-contract-runner" calls="$T/provider-contract.calls"
    cat > "$runner" <<'SH'
#!/bin/bash
printf '%s\n' "$1" >> "$CONTRACT_CALLS"
SH
    chmod +x "$runner"; : > "$calls"
    local common=(--root "$R" --base "$base") receipt_a receipt_b receipt_v2
    sed 's/"adapter":"codex"/"adapter":"grok"/' "$S/roster-a.json" > "$S/roster-retired.json"
    assert_exit "a retired adapter cannot enter a provider contract receipt" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/retired" \
        --roster "$S/roster-retired.json"
    assert_eq "retired adapter rejection runs no contract test" \
      "$(wc -l < "$calls" | tr -d ' ')" 0
    sed 's/"seat":"codex-review","adapter":"codex"/"seat":"grok-review","adapter":"grok"/' \
      "$S/roster-a.json" > "$S/roster-retired-extra.json"
    assert_exit "a retired extra adapter cannot enter a provider contract receipt" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" \
        --session "$S/retired-extra" --roster "$S/roster-retired-extra.json"
    assert_eq "retired extra rejection runs no contract test" \
      "$(wc -l < "$calls" | tr -d ' ')" 0
    receipt_a=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/a" --roster "$S/roster-a.json") || return
    assert_exit "contract receipt is published" 0 test -f "$receipt_a"
    assert_eq "contract groups run once for the first identity" \
      "$(wc -l < "$calls" | tr -d ' ')" 4
    python3 - "$receipt_a" "$R/plugins/review-council/scripts/rev-prompt.sh" <<'PY'
import json, os, stat, sys
receipt = json.load(open(sys.argv[1]))
assert receipt['schema_version'] == 2
assert receipt['identity']['core_roster'] == [
 {'seat':'codex-sol','adapter':'codex','model':'gpt-5.6-sol','effort':'max'},
 {'seat':'codex-terra','adapter':'codex','model':'gpt-5.6-terra','effort':'max'},
 {'seat':'opus','adapter':'claude','model':'opus','effort':'max'},
 {'seat':'sonnet','adapter':'claude','model':'sonnet','effort':'max'}]
subject = receipt['identity']['subject_boundaries']
assert set(subject) == {'scripts/rev-prompt.sh'}
assert subject['scripts/rev-prompt.sh']['kind'] == 'regular'
assert subject['scripts/rev-prompt.sh']['mode'] == stat.S_IMODE(os.stat(sys.argv[2]).st_mode)
assert len(subject['scripts/rev-prompt.sh']['sha256']) == 64
PY
    assert_eq "receipt binds the ordered active core roster" "$?" 0

    receipt_b=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/b" --roster "$S/roster-b.json") || return
    [ "$(basename "$receipt_a")" != "$(basename "$receipt_b")" ] && ok "a different core roster gets a different receipt key" \
      || fail "a different core roster gets a different receipt key"
    assert_eq "different roster replays the contract" "$(wc -l < "$calls" | tr -d ' ')" 8

    receipt_v2=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"2","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/v2" --roster "$S/roster-a.json") || return
    [ "$(basename "$receipt_a")" != "$(basename "$receipt_v2")" ] && ok "a provider version change gets a different receipt key" \
      || fail "a provider version change gets a different receipt key"
    assert_eq "provider version change replays the contract" "$(wc -l < "$calls" | tr -d ' ')" 12

    rm -rf "$S/a"; mkdir -p "$S/cache-reuse"
    local reused
    reused=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" --roster "$S/roster-a.json") || return
    assert_exit "cache recreates a deleted session receipt" 0 test -f "$reused"
    assert_eq "cache reuse runs no paid contract test" "$(wc -l < "$calls" | tr -d ' ')" 12

    REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" \
        --roster "$S/roster-a.json" --verify-only > "$T/contract.out" 2> "$T/contract.err"
    assert_eq "verify-only accepts the exact receipt identity" "$?" 0
    assert_eq "verify-only runs no paid contract test" "$(wc -l < "$calls" | tr -d ' ')" 12

    chmod +x "$R/plugins/review-council/scripts/rev-prompt.sh"
    assert_exit "verify-only rejects a chmod-only boundary change" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" \
        --roster "$S/roster-a.json" --verify-only
    local mode_receipt
    mode_receipt=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/mode-change" \
        --roster "$S/roster-a.json") || return
    [ "$(basename "$mode_receipt")" != "$(basename "$receipt_a")" ] \
      && ok "a chmod-only boundary change gets a different receipt key" \
      || fail "a chmod-only boundary change gets a different receipt key"
    assert_eq "a chmod-only boundary change replays the contract" \
      "$(wc -l < "$calls" | tr -d ' ')" 16
    chmod -x "$R/plugins/review-council/scripts/rev-prompt.sh"

    assert_exit "verify-only rejects a different provider version identity" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"2","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" \
        --roster "$S/roster-a.json" --verify-only
    assert_exit "verify-only rejects a different core roster identity" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" \
        --roster "$S/roster-b.json" --verify-only
    assert_eq "identity mismatch checks run no paid contract test" \
      "$(wc -l < "$calls" | tr -d ' ')" 16

    printf 'later boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" \
        --roster "$S/roster-a.json" --verify-only > "$T/contract.out" 2> "$T/contract.err"
    assert_eq "foreign target mutation invalidates the active executor receipt" "$?" 2
    printf 'new boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"

    rm "$reused"
    assert_exit "verify-only rejects a deleted receipt" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" \
        --roster "$S/roster-a.json" --verify-only
    reused=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" --roster "$S/roster-a.json") || return
    printf '{}\n' > "$reused"
    assert_exit "verify-only rejects a corrupt session receipt" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/cache-reuse" \
        --roster "$S/roster-a.json" --verify-only

    local cache_path="$T/provider-contract-cache/contracts/$(basename "$receipt_a" | sed 's/^contract-pass-//')"
    printf '{}\n' > "$cache_path"
    assert_exit "a corrupt cache fails closed instead of rerunning paid tests" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/corrupt-cache" \
        --roster "$S/roster-a.json"
    assert_eq "corrupt cache launches no contract test" "$(wc -l < "$calls" | tr -d ' ')" 16

    local gemini_v1 gemini_v2
    gemini_v1=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1","gemini":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/gemini-v1" \
        --roster "$S/roster-gemini.json") || return
    gemini_v2=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1","gemini":"2"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" "${common[@]}" --session "$S/gemini-v2" \
        --roster "$S/roster-gemini.json") || return
    [ "$(basename "$gemini_v1")" != "$(basename "$gemini_v2")" ] && ok "Gemini version changes the contract key" \
      || fail "Gemini version changes the contract key"
    python3 - "$gemini_v1" <<'PY'
import json, sys
receipt = json.load(open(sys.argv[1]))
gemini = next(row for row in receipt['identity']['core_roster'] if row['adapter'] == 'gemini')
assert gemini['effort'] is None
assert receipt['identity']['provider_versions']['gemini'] == '1'
PY
    assert_eq "Gemini null effort and CLI version are preserved" "$?" 0

    git -C "$R" add plugins/review-council/scripts/rev-prompt.sh
    git -C "$R" commit -qm 'provider prompt boundary'
    local mid_base; mid_base=$(git -C "$R" rev-parse HEAD)
    printf 'current evidence boundary\n' > "$R/plugins/review-council/scripts/rev-evidence.py"
    local broad_receipt narrow_receipt
    broad_receipt=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/broad-base" --roster "$S/roster-a.json") || return
    narrow_receipt=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-contract-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$mid_base" \
        --session "$S/narrow-base" --roster "$S/roster-a.json") || return
    [ "$(basename "$broad_receipt")" != "$(basename "$narrow_receipt")" ] && ok "different touched sets get different keys" \
      || fail "different touched sets get different keys"
    python3 - "$broad_receipt" "$narrow_receipt" <<'PY'
import json, sys
broad, narrow = (json.load(open(path)) for path in sys.argv[1:])
assert broad['identity']['touched_boundaries'] == broad['touched_boundaries']
assert narrow['identity']['touched_boundaries'] == narrow['touched_boundaries']
assert broad['touched_boundaries'] != narrow['touched_boundaries']
PY
    assert_eq "receipt identity binds the exact touched boundary set" "$?" 0
    assert_eq "new Gemini and touched-set identities each replay once" \
      "$(wc -l < "$calls" | tr -d ' ')" 32
  )
}

test_provider_version_process_bounds() {
  ( local B="$T/provider-version-bounds"; mkdir -p "$B/bin"
    cat > "$B/bin/codex" <<'SH'
#!/bin/bash
if [ "${VERSION_MODE:-}" = cancel ]; then
  printf '%s\n' "$$" >> "$VERSION_PIDS"
  sleep 30
elif [ "${VERSION_MODE:-}" = timeout ]; then
  sleep 30 &
  printf '%s\n' "$!" > "$VERSION_CHILD_PID"
  wait
elif [ "${VERSION_MODE:-}" = success-child ]; then
  sleep 30 </dev/null >/dev/null 2>&1 &
  printf '%s\n' "$!" > "$VERSION_CHILD_PID"
  printf 'codex 1.2.3\n'
elif [ "${VERSION_MODE:-}" = flood ]; then
  python3 -c "import sys; sys.stdout.write('x' * 2000000)"
elif [ "${VERSION_MODE:-}" = registration-race ]; then
  sleep 30
elif [ "${VERSION_MODE:-}" = failure ]; then
  exit 7
else
  printf 'codex 1.2.3\n'
fi
SH
    chmod +x "$B/bin/codex"
    local child="$B/child.pid" started elapsed value i=0
    started=$(date +%s)
    value=$(PATH="$B/bin:/usr/bin:/bin" VERSION_MODE=timeout VERSION_CHILD_PID="$child" \
      REVIEW_COUNCIL_CONTRACT_VERSION_TIMEOUT_SECONDS=1 \
      python3 - "$SCRIPTS/rev-contract-check.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('contract', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
print(module.one_version('codex')[1])
PY
    )
    assert_eq "a timed-out provider version is unavailable" "$value" unavailable
    elapsed=$(( $(date +%s) - started ))
    [ "$elapsed" -le 4 ] && ok "provider version timeout is bounded" \
      || fail "provider version timeout is bounded" "elapsed ${elapsed}s"
    while [ ! -s "$child" ] && [ "$i" -lt 20 ]; do sleep 0.05; i=$((i + 1)); done
    if [ -s "$child" ]; then
      i=0
      while kill -0 "$(cat "$child")" 2>/dev/null && [ "$i" -lt 40 ]; do
        sleep 0.05; i=$((i + 1))
      done
      assert_exit "provider version timeout terminates its descendant" 1 kill -0 "$(cat "$child")"
    else
      fail "provider version timeout launches its descendant" "missing child pid"
    fi
    value=$(PATH="$B/bin:/usr/bin:/bin" VERSION_MODE=flood \
      REVIEW_COUNCIL_CONTRACT_VERSION_OUTPUT_BYTES=1024 \
      python3 - "$SCRIPTS/rev-contract-check.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('contract', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
print(module.one_version('codex')[1])
PY
    )
    assert_eq "a flooding provider version is unavailable" "$value" unavailable

    child="$B/success-child.pid"
    value=$(PATH="$B/bin:/usr/bin:/bin" VERSION_MODE=success-child VERSION_CHILD_PID="$child" \
      python3 - "$SCRIPTS/rev-contract-check.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('contract', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
print(module.one_version('codex')[1])
PY
    )
    assert_eq "a provider version parent with a live child is unavailable" "$value" unavailable
    local alive=no pid
    pid=$(cat "$child")
    if kill -0 "$pid" 2>/dev/null; then
      alive=yes
      kill -KILL "$pid" 2>/dev/null || true
    fi
    assert_eq "a rejected provider version terminates its child" "$alive" no

    local signal_spec signal_name expected race_pid race_rc
    for signal_spec in HUP:129 INT:130 TERM:143; do
      signal_name=${signal_spec%%:*}; expected=${signal_spec##*:}
      race_pid="$B/registration-race-$signal_name.pid"
      PATH="$B/bin:/usr/bin:/bin" VERSION_MODE=registration-race \
        python3 - "$SCRIPTS/rev-contract-check.py" "$race_pid" "$signal_name" \
        > "$B/registration-race-$signal_name.out" \
        2> "$B/registration-race-$signal_name.err" <<'PY'
import importlib.util, os, pathlib, signal, sys
spec = importlib.util.spec_from_file_location('contract', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
register = module.register_group
def interrupted_registration(group):
    pathlib.Path(sys.argv[2]).write_text(str(group['process'].pid))
    os.kill(os.getpid(), getattr(signal, 'SIG' + sys.argv[3]))
    return register(group)
module.register_group = interrupted_registration
signum = getattr(signal, 'SIG' + sys.argv[3])
signal.signal(signum, module.cancellation_signal)
module.run_provider_version(['codex', '--version'], 60, 4096)
PY
      race_rc=$?
      assert_eq "$signal_name during provider version registration keeps the graceful status" \
        "$race_rc" "$expected"
      alive=no
      pid=$(cat "$race_pid")
      if kill -0 "$pid" 2>/dev/null; then
        alive=yes
        kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
      fi
      assert_eq "$signal_name during provider version registration terminates the new group" \
        "$alive" no
    done

    cp "$B/bin/codex" "$B/bin/claude"
    local R="$B/root" S="$B/session" runner="$B/runner" base checker_pid checker_rc
    base=$(provider_contract_fixture "$R" "$S") || return
    printf 'changed boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    provider_contract_roster "$S/roster.json"
    cat > "$runner" <<'SH'
#!/bin/sh
printf '%s\n' "$1" >> "$CONTRACT_CALLS"
SH
    chmod +x "$runner"
    PATH="$B/bin:/usr/bin:/bin" VERSION_MODE=failure CONTRACT_CALLS="$B/failure.calls" \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CACHE_DIR="$B/failure-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/failure" --roster "$S/roster.json" \
        > "$B/failure.out" 2> "$B/failure.err"
    assert_eq "an unavailable provider version blocks contract replay" "$?" 2
    assert_grep "an unavailable provider version has a stable failure" "$B/failure.err" \
      '^contract replay: provider versions unavailable: claude, codex$'
    local failure_calls=0 failure_receipts
    [ -f "$B/failure.calls" ] && failure_calls=$(wc -l < "$B/failure.calls" | tr -d ' ')
    assert_eq "an unavailable provider version runs no contract group" "$failure_calls" 0
    failure_receipts=$(find "$S/failure" "$B/failure-cache" -type f -name '*.json' \
      2>/dev/null | wc -l | tr -d ' ')
    assert_eq "an unavailable provider version publishes no receipt" "$failure_receipts" 0

    local invalid_override invalid_name invalid_calls invalid_receipts
    for invalid_name in empty whitespace; do
      if [ "$invalid_name" = empty ]; then
        invalid_override='{"claude":"1","codex":""}'
      else
        invalid_override='{"claude":"1","codex":"   "}'
      fi
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS="$invalid_override" \
        CONTRACT_CALLS="$B/$invalid_name.calls" REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
        REVIEW_COUNCIL_CACHE_DIR="$B/$invalid_name-cache" \
        python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
          --session "$S/$invalid_name" --roster "$S/roster.json" \
          > "$B/$invalid_name.out" 2> "$B/$invalid_name.err"
      assert_eq "$invalid_name provider version override blocks contract replay" "$?" 2
      assert_grep "$invalid_name provider version override has a stable failure" \
        "$B/$invalid_name.err" '^contract replay: invalid REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS$'
      invalid_calls=0
      [ -f "$B/$invalid_name.calls" ] \
        && invalid_calls=$(wc -l < "$B/$invalid_name.calls" | tr -d ' ')
      assert_eq "$invalid_name provider version override runs no contract group" \
        "$invalid_calls" 0
      invalid_receipts=$(find "$S/$invalid_name" "$B/$invalid_name-cache" \
        -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
      assert_eq "$invalid_name provider version override publishes no receipt" \
        "$invalid_receipts" 0
    done

    PATH="$B/bin:/usr/bin:/bin" VERSION_MODE=cancel VERSION_PIDS="$B/version.pids" \
      CONTRACT_CALLS="$B/cancel.calls" REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CACHE_DIR="$B/cache" \
      python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S" --roster "$S/roster.json" > "$B/cancel.out" 2> "$B/cancel.err" &
    checker_pid=$!
    local count=0 leaked=0
    i=0
    while [ "$count" -lt 2 ] && [ "$i" -lt 100 ]; do
      sleep 0.02
      if [ -f "$B/version.pids" ]; then
        count=$(wc -l < "$B/version.pids" | tr -d ' ')
      fi
      i=$((i + 1))
    done
    kill -TERM "$checker_pid" 2>/dev/null || true
    wait "$checker_pid"; checker_rc=$?
    assert_eq "TERM cancellation gives the contract checker a graceful status" "$checker_rc" 143
    if [ -f "$B/version.pids" ]; then
      while read -r pid; do
        [ -n "$pid" ] || continue
        if kill -0 "$pid" 2>/dev/null; then
          leaked=$((leaked + 1))
          kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
        fi
      done < "$B/version.pids"
    fi
    assert_eq "contract cancellation reaches concurrent version checks" "$count" 2
    assert_eq "contract cancellation terminates every version process group" "$leaked" 0
  )
}

test_provider_contract_registration_race() {
  ( local B="$T/provider-contract-registration-race" runner="$T/provider-contract-race-runner"
    mkdir -p "$B"
    cat > "$runner" <<'SH'
#!/bin/sh
sleep 30
SH
    chmod +x "$runner"
    local signal_spec signal_name expected race_pid race_rc alive pid
    for signal_spec in HUP:129 INT:130 TERM:143; do
      signal_name=${signal_spec%%:*}; expected=${signal_spec##*:}
      race_pid="$B/group-$signal_name.pid"
      python3 - "$SCRIPTS/rev-contract-check.py" "$runner" "$race_pid" "$signal_name" \
        > "$B/$signal_name.out" 2> "$B/$signal_name.err" <<'PY'
import importlib.util, os, pathlib, signal, sys
spec = importlib.util.spec_from_file_location('contract', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
popen = module.subprocess.Popen
holder = {}
def interrupt_next_line(frame, event, arg):
    if event == 'line' and frame.f_code.co_name == 'launch_group':
        sys.settrace(None)
        frame.f_trace = None
        process = holder['process']
        pathlib.Path(sys.argv[3]).write_text(str(process.pid))
        os.kill(os.getpid(), getattr(signal, 'SIG' + sys.argv[4]))
    return interrupt_next_line
def interrupted_launch(*args, **kwargs):
    process = popen(*args, **kwargs)
    holder['process'] = process
    caller = sys._getframe(1)
    caller.f_trace = interrupt_next_line
    sys.settrace(interrupt_next_line)
    return process
module.subprocess.Popen = interrupted_launch
signum = getattr(signal, 'SIG' + sys.argv[4])
signal.signal(signum, module.cancellation_signal)
policy = {'shared_deadline_seconds': 60, 'output_bytes': 4096,
          'diagnostic_bytes': 256, 'term_grace_seconds': 1}
module.run_contracts(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[2]).parent,
                     dict(os.environ), policy)
PY
      race_rc=$?
      assert_eq "$signal_name before contract group registration keeps the graceful status" \
        "$race_rc" "$expected"
      alive=no
      pid=$(cat "$race_pid")
      if kill -0 "$pid" 2>/dev/null; then
        alive=yes
        kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
      fi
      assert_eq "$signal_name before contract group registration terminates the new group" \
        "$alive" no
    done
  )
}

test_provider_contract_trusted_executor() {
  ( local R="$T/provider-untrusted-target" S="$T/provider-trust-session"
    local X="$T/provider-trusted-source" E="$T/provider-trusted-source/plugins/review-council"
    mkrepo "$X"; mkdir -p "$E/.codex-plugin" "$E/docs" "$E/scripts" "$E/tests"
    printf '{}\n' > "$E/.codex-plugin/plugin.json"
    cp "$SCRIPTS/rev-contract-check.py" "$E/scripts/rev-contract-check.py"
    printf 'trusted boundary v1\n' > "$E/scripts/rev-prompt.sh"
    printf 'documentation v1\n' > "$E/docs/note.md"
    printf 'test_unlisted_helper() { :; }\n' > "$E/tests/t-unlisted.sh"
    cat > "$E/tests/run-tests.sh" <<'SH'
#!/bin/bash
for file in "$(dirname "$0")"/t-*.sh; do . "$file"; done
printf 'trusted:%s\n' "$1" >> "$EXECUTOR_CALLS"
SH
    chmod +x "$E/tests/run-tests.sh"
    git -C "$X" add . && git -C "$X" commit -qm 'trusted executor base'
    local executor_base; executor_base=$(git -C "$X" rev-parse HEAD)

    mkrepo "$R"; mkdir -p "$R/plugins/review-council/.codex-plugin" \
      "$R/plugins/review-council/scripts" "$R/plugins/review-council/tests" "$S"
    printf '{}\n' > "$R/plugins/review-council/.codex-plugin/plugin.json"
    printf 'old boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    git -C "$R" add . && git -C "$R" commit -qm 'provider contract base'
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf 'changed boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    cat > "$R/plugins/review-council/tests/run-tests.sh" <<'SH'
#!/bin/bash
printf 'target runner executed\n' >> "$TARGET_SENTINEL"
SH
    chmod +x "$R/plugins/review-council/tests/run-tests.sh"
    cat > "$S/roster.json" <<'JSON'
{"seats":[{"seat":"sol","adapter":"codex","model":"gpt-5.6-sol","effort":"max","extra":false}]}
JSON
    local sentinel="$T/target-runner.sentinel" executor_calls="$T/executor.calls" receipt
    : > "$executor_calls"
    receipt=$(TARGET_SENTINEL="$sentinel" EXECUTOR_CALLS="$executor_calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-trust-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/default" --roster "$S/roster.json") || return
    assert_exit "foreign target runner is never executed" 1 test -e "$sentinel"
    assert_eq "checker-owned runner executes every contract group" \
      "$(wc -l < "$executor_calls" | tr -d ' ')" 4
    python3 - "$receipt" "$E" <<'PY'
import json, pathlib, sys
receipt = json.load(open(sys.argv[1]))
executor = receipt['identity']['executor']
assert pathlib.Path(executor['plugin']) == pathlib.Path(sys.argv[2]).resolve()
assert executor['policy'] == 'checker-owned'
assert pathlib.Path(executor['runner']).name == 'run-tests.sh'
assert len(executor['runner_sha256']) == 64
subject = receipt['identity']['subject_boundaries']
assert set(subject) == {'scripts/rev-prompt.sh', 'tests/run-tests.sh'}
assert all(value['kind'] == 'regular' for value in subject.values())
assert all(isinstance(value['mode'], int) for value in subject.values())
assert all(len(value['sha256']) == 64 for value in subject.values())
PY
    assert_eq "receipt identifies the checker-owned executor" "$?" 0

    printf 'later foreign boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-trust-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/default" --roster "$S/roster.json" --verify-only >/dev/null 2>&1
    assert_eq "foreign target bytes invalidate the active executor receipt" "$?" 2

    printf 'test_unlisted_helper() { true; }\n' > "$E/tests/t-unlisted.sh"
    local unlisted_receipt
    unlisted_receipt=$(EXECUTOR_CALLS="$executor_calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-trust-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/unlisted-test-change" --roster "$S/roster.json") || return
    [ "$(basename "$receipt")" != "$(basename "$unlisted_receipt")" ] \
      && ok "an unlisted sourced test file changes the receipt key" \
      || fail "an unlisted sourced test file changes the receipt key"
    assert_eq "a sourced test tree change replays every contract group" \
      "$(wc -l < "$executor_calls" | tr -d ' ')" 8
    printf 'documentation v2\n' > "$E/docs/note.md"
    local docs_receipt
    docs_receipt=$(EXECUTOR_CALLS="$executor_calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-trust-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/docs-change" --roster "$S/roster.json") || return
    assert_eq "docs-only executor changes keep the contract key" \
      "$(basename "$docs_receipt")" "$(basename "$unlisted_receipt")"
    assert_eq "docs-only executor changes reuse the cached contract" \
      "$(wc -l < "$executor_calls" | tr -d ' ')" 8

    local target_override="$R/plugins/review-council/tests/run-tests.sh"
    TARGET_SENTINEL="$sentinel" REVIEW_COUNCIL_CONTRACT_RUNNER="$target_override" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-target-override-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/target-override" --roster "$S/roster.json" \
        > "$T/target-override.out" 2> "$T/target-override.err"
    assert_eq "foreign target-local override is rejected" "$?" 2
    assert_exit "rejected target-local override is not executed" 1 test -e "$sentinel"
    assert_grep "target-local override has a stable trust error" "$T/target-override.err" \
      'contract runner must be outside the foreign review target'

    local redirected_dir="$T/redirected-target-runner" redirected_sentinel="$T/redirected.sentinel"
    mkdir -p "$redirected_dir"
    cat > "$redirected_dir/run-tests.sh" <<'SH'
#!/bin/bash
printf 'redirected target runner executed\n' >> "$REDIRECTED_SENTINEL"
SH
    chmod +x "$redirected_dir/run-tests.sh"
    ln -s "$redirected_dir" "$R/plugins/review-council/redirected-tests"
    REDIRECTED_SENTINEL="$redirected_sentinel" \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$R/plugins/review-council/redirected-tests/run-tests.sh" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-redirected-override-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/redirected-override" --roster "$S/roster.json" \
        > "$T/redirected-override.out" 2> "$T/redirected-override.err"
    assert_eq "foreign target path through a symlink is rejected" "$?" 2
    assert_exit "redirected target-local runner is not executed" 1 test -e "$redirected_sentinel"

    local external="$T/external-contract-runner" calls="$T/external-contract.calls"
    cat > "$external" <<'SH'
#!/bin/bash
printf 'v1:%s\n' "$1" >> "$CONTRACT_CALLS"
SH
    chmod +x "$external"; : > "$calls"
    local external_a external_b
    external_a=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$external" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-external-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/external-a" --roster "$S/roster.json") || return
    python3 - "$external" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text(path.read_text().replace('v1:%s', 'v2:%s'))
PY
    external_b=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$external" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-external-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/external-b" --roster "$S/roster.json") || return
    [ "$(basename "$external_a")" != "$(basename "$external_b")" ] && ok "external runner bytes change the receipt key" \
      || fail "external runner bytes change the receipt key"
    [ "$(basename "$receipt")" != "$(basename "$external_a")" ] \
      && ok "executor policy changes the receipt key" || fail "executor policy changes the receipt key"
    assert_eq "each external runner identity executes once" "$(wc -l < "$calls" | tr -d ' ')" 8

    local linked="$T/linked-contract-runner" disabled="$T/disabled-contract-runner"
    ln -s "$external" "$linked"
    cp "$external" "$disabled"; chmod -x "$disabled"
    local invalid
    for invalid in "$linked" "$disabled"; do
      REVIEW_COUNCIL_CONTRACT_RUNNER="$invalid" CONTRACT_CALLS="$calls" \
        REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
        REVIEW_COUNCIL_CACHE_DIR="$T/provider-invalid-runner-cache" \
        python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
          --session "$S/invalid-runner" --roster "$S/roster.json" \
          > "$T/invalid-runner.out" 2> "$T/invalid-runner.err"
      assert_eq "invalid explicit runner is rejected before cache lookup" "$?" 2
      assert_grep "invalid explicit runner has a stable shape error" "$T/invalid-runner.err" \
        'contract runner must be a regular executable file'
    done

    printf 'trusted boundary v2\n' > "$E/scripts/rev-prompt.sh"
    local same_root
    same_root=$(EXECUTOR_CALLS="$executor_calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-same-root-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$X" --base "$executor_base" \
        --session "$S/same-root" --roster "$S/roster.json") || return
    printf 'trusted boundary v3\n' > "$E/scripts/rev-prompt.sh"
    EXECUTOR_CALLS="$executor_calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-same-root-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$X" --base "$executor_base" \
        --session "$S/same-root" --roster "$S/roster.json" --verify-only \
        > "$T/same-root.out" 2> "$T/same-root.err"
    assert_eq "same-root executor mutation invalidates its receipt" "$?" 2
    assert_grep "same-root mutation requires an exact new receipt" "$T/same-root.err" \
      'matching provider contract receipt is missing'

    local E2="$T/provider-trusted-copy" copied
    cp -R "$E" "$E2"
    copied=$(EXECUTOR_CALLS="$executor_calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-path-cache" \
      python3 "$E2/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/copied" --roster "$S/roster.json") || return
    local original_path
    original_path=$(EXECUTOR_CALLS="$executor_calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-path-cache" \
      python3 "$E/scripts/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/original-path" --roster "$S/roster.json") || return
    [ "$(basename "$receipt")" != "$(basename "$original_path")" ] \
      && ok "executor boundary bytes change the receipt key" \
      || fail "executor boundary bytes change the receipt key"
    [ "$(basename "$copied")" != "$(basename "$original_path")" ] \
      && ok "executor path changes the receipt key" || fail "executor path changes the receipt key"
  )
}

provider_contract_fixture() {
  local root=$1 session=$2 layout=${3:-nested} plugin
  mkrepo "$root"
  if [ "$layout" = nested ]; then
    plugin="$root/plugins/review-council"
  else
    plugin="$root"
  fi
  mkdir -p "$plugin/.codex-plugin" "$plugin/scripts" "$plugin/docs" "$session"
  printf '{}\n' > "$plugin/.codex-plugin/plugin.json"
  printf 'old boundary\n' > "$plugin/scripts/rev-prompt.sh"
  git -C "$root" add . && git -C "$root" commit -qm 'provider contract fixture'
  git -C "$root" rev-parse HEAD
}

provider_contract_roster() {
  cat > "$1" <<'JSON'
{"seats":[
 {"seat":"codex-sol","adapter":"codex","model":"gpt-5.6-sol","effort":"max","extra":false},
 {"seat":"codex-terra","adapter":"codex","model":"gpt-5.6-terra","effort":"max","extra":false},
 {"seat":"opus","adapter":"claude","model":"opus","effort":"max","extra":false},
 {"seat":"sonnet","adapter":"claude","model":"sonnet","effort":"max","extra":false}]}
JSON
}

test_provider_contract_rename_boundaries() {
  ( local runner="$T/provider-rename-runner" calls="$T/provider-rename.calls"
    cat > "$runner" <<'SH'
#!/bin/bash
printf '%s\n' "$1" >> "$CONTRACT_CALLS"
SH
    chmod +x "$runner"; : > "$calls"
    local layout R S plugin base receipt expected
    for layout in nested top; do
      R="$T/provider-rename-$layout"; S="$T/provider-rename-$layout-session"
      base=$(provider_contract_fixture "$R" "$S" "$layout") || return
      if [ "$layout" = nested ]; then
        plugin="$R/plugins/review-council"
        expected='plugins/review-council/scripts/rev-prompt.sh'
      else
        plugin="$R"
        expected='scripts/rev-prompt.sh'
      fi
      provider_contract_roster "$S/roster.json"
      git -C "$R" config diff.renames true
      git -C "$R" mv "$plugin/scripts/rev-prompt.sh" "$plugin/docs/rev-prompt-moved.sh"
      receipt=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
        REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
        REVIEW_COUNCIL_CACHE_DIR="$T/provider-rename-cache-$layout" \
        python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
          --session "$S" --roster "$S/roster.json") || return
      python3 - "$receipt" "$expected" <<'PY'
import json, sys
receipt = json.load(open(sys.argv[1]))
assert sys.argv[2] in receipt['touched_boundaries'], receipt['touched_boundaries']
PY
      assert_eq "$layout rename retains the removed provider boundary" "$?" 0
    done
    assert_eq "both rename cases execute every contract group" \
      "$(wc -l < "$calls" | tr -d ' ')" 8

    R="$T/provider-helper-inputs"; S="$T/provider-helper-inputs-session"
    plugin="$R/plugins/review-council"
    mkrepo "$R"; mkdir -p "$plugin/.codex-plugin" "$plugin/scripts/lib" "$S"
    printf '{}\n' > "$plugin/.codex-plugin/plugin.json"
    local helper
    for helper in readonly-bash-guard.py isolated-seat-home.py rev-attempt.py; do
      printf 'old helper\n' > "$plugin/scripts/lib/$helper"
    done
    git -C "$R" add . && git -C "$R" commit -qm 'provider helper inputs'
    base=$(git -C "$R" rev-parse HEAD)
    for helper in readonly-bash-guard.py isolated-seat-home.py rev-attempt.py; do
      printf 'changed helper\n' > "$plugin/scripts/lib/$helper"
    done
    provider_contract_roster "$S/roster.json"
    receipt=$(REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-helper-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S" --roster "$S/roster.json") || return
    python3 - "$receipt" <<'PY'
import json, sys
receipt = json.load(open(sys.argv[1]))
assert receipt['touched_boundaries'] == [
    'plugins/review-council/scripts/lib/isolated-seat-home.py',
    'plugins/review-council/scripts/lib/readonly-bash-guard.py',
    'plugins/review-council/scripts/lib/rev-attempt.py',
]
PY
    assert_eq "every hashed provider helper triggers contract replay" "$?" 0
    assert_eq "helper-only changes execute every contract group" \
      "$(wc -l < "$calls" | tr -d ' ')" 12
  )
}

test_provider_contract_execution_policy_identity() {
  ( local R="$T/provider-policy-root" S="$T/provider-policy-session"
    local runner="$T/provider-policy-runner" calls="$T/provider-policy.calls"
    local base; base=$(provider_contract_fixture "$R" "$S") || return
    printf 'changed boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    provider_contract_roster "$S/roster.json"
    cat > "$runner" <<'SH'
#!/bin/bash
printf '%s\n' "$1" >> "$CONTRACT_CALLS"
SH
    chmod +x "$runner"; : > "$calls"
    policy_receipt() {
      local label=$1 deadline=$2 output=$3 diagnostic=$4 grace=$5
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" CONTRACT_CALLS="$calls" \
        REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
        REVIEW_COUNCIL_CONTRACT_DEADLINE_SECONDS="$deadline" \
        REVIEW_COUNCIL_CONTRACT_OUTPUT_BYTES="$output" \
        REVIEW_COUNCIL_CONTRACT_DIAGNOSTIC_BYTES="$diagnostic" \
        REVIEW_COUNCIL_CONTRACT_TERM_GRACE_SECONDS="$grace" \
        REVIEW_COUNCIL_CACHE_DIR="$T/provider-policy-cache" \
        python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
          --session "$S/$label" --roster "$S/roster.json"
    }
    local baseline deadline output diagnostic grace
    baseline=$(policy_receipt baseline 10 4096 256 1) || return
    deadline=$(policy_receipt deadline 11 4096 256 1) || return
    output=$(policy_receipt output 10 8192 256 1) || return
    diagnostic=$(policy_receipt diagnostic 10 4096 512 1) || return
    grace=$(policy_receipt grace 10 4096 256 2) || return
    python3 - "$baseline" "$deadline" "$output" "$diagnostic" "$grace" <<'PY'
import json, pathlib, sys
paths = [pathlib.Path(path) for path in sys.argv[1:]]
assert len({path.name for path in paths}) == len(paths)
policy = json.loads(paths[0].read_text())['identity']['executor']['execution']
assert policy == {
    'diagnostic_bytes': 256,
    'output_bytes': 4096,
    'shared_deadline_seconds': 10,
    'term_grace_seconds': 1,
}
PY
    assert_eq "every resolved execution policy value changes the receipt identity" "$?" 0
    assert_eq "every execution policy identity runs every contract group" \
      "$(wc -l < "$calls" | tr -d ' ')" 20
    assert_exit "verify-only cannot reuse a receipt under another deadline" 2 env \
      REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
      REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
      REVIEW_COUNCIL_CONTRACT_DEADLINE_SECONDS=12 \
      REVIEW_COUNCIL_CONTRACT_OUTPUT_BYTES=4096 \
      REVIEW_COUNCIL_CONTRACT_DIAGNOSTIC_BYTES=256 \
      REVIEW_COUNCIL_CONTRACT_TERM_GRACE_SECONDS=1 \
      REVIEW_COUNCIL_CACHE_DIR="$T/provider-policy-cache" \
      python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
        --session "$S/baseline" --roster "$S/roster.json" --verify-only
  )
}

test_provider_contract_bounded_executor() {
  ( local R="$T/provider-bounded-root" S="$T/provider-bounded-session"
    local runner="$T/provider-bounded-runner" base
    base=$(provider_contract_fixture "$R" "$S") || return
    printf 'changed boundary\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
    provider_contract_roster "$S/roster.json"
    cat > "$runner" <<'SH'
#!/bin/bash
if [ "${CONTRACT_MODE:-}" = timeout ] && [ "$1" = provider_envelope_replay ]; then
  sleep 30 &
  printf '%s\n' "$!" > "$CONTRACT_CHILD_PID"
  wait
elif [ "${CONTRACT_MODE:-}" = success-child ] && [ "$1" = provider_envelope_replay ]; then
  sleep 30 </dev/null >/dev/null 2>&1 &
  printf '%s\n' "$!" > "$CONTRACT_CHILD_PID"
  printf 'ok:%s\n' "$1"
elif [ "${CONTRACT_MODE:-}" = flood ] && [ "$1" = provider_envelope_replay ]; then
  python3 -c "import sys; sys.stdout.write('x' * 200000)"
elif [ "${CONTRACT_MODE:-}" = flood ] && [ "$1" = plan_evidence ]; then
  sleep 30 &
  printf '%s\n' "$!" > "$CONTRACT_CHILD_PID"
  wait
elif [ "${CONTRACT_MODE:-}" = fail ] && [ "$1" = provider_envelope_replay ]; then
  sleep 0.2
  python3 -c "import sys; sys.stdout.write('y' * 80000 + '\\nstable fast failure\\n')"
  exit 7
elif [ "${CONTRACT_MODE:-}" = fail ] && [ "$1" = plan_evidence ]; then
  sleep 30 &
  printf '%s\n' "$!" > "$CONTRACT_CHILD_PID"
  wait
else
  printf 'ok:%s\n' "$1"
fi
SH
    chmod +x "$runner"
    run_failure() {
      local mode=$1 deadline=$2 output=$3 diagnostic=$4 child=$5 session="$S/$mode"
      CONTRACT_MODE="$mode" CONTRACT_CHILD_PID="$child" \
        REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" \
        REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}' \
        REVIEW_COUNCIL_CONTRACT_DEADLINE_SECONDS="$deadline" \
        REVIEW_COUNCIL_CONTRACT_OUTPUT_BYTES="$output" \
        REVIEW_COUNCIL_CONTRACT_DIAGNOSTIC_BYTES="$diagnostic" \
        REVIEW_COUNCIL_CONTRACT_TERM_GRACE_SECONDS=1 \
        REVIEW_COUNCIL_CACHE_DIR="$T/provider-bounded-cache-$mode" \
        python3 "$SCRIPTS/rev-contract-check.py" --root "$R" --base "$base" \
          --session "$session" --roster "$S/roster.json" \
          > "$T/provider-$mode.out" 2> "$T/provider-$mode.err"
    }
    local mode child start elapsed i files
    for mode in timeout flood fail success-child; do
      child="$T/provider-$mode-child.pid"; start=$(date +%s)
      if [ "$mode" = timeout ]; then
        run_failure "$mode" 1 4096 256 "$child"
      elif [ "$mode" = fail ]; then
        run_failure "$mode" 20 131072 256 "$child"
      elif [ "$mode" = flood ]; then
        run_failure "$mode" 20 1024 256 "$child"
      else
        run_failure "$mode" 20 4096 256 "$child"
      fi
      assert_eq "$mode contract failure returns the stable status" "$?" 2
      elapsed=$(( $(date +%s) - start ))
      [ "$elapsed" -le 4 ] && ok "$mode contract failure is bounded" \
        || fail "$mode contract failure is bounded" "elapsed ${elapsed}s"
      i=0
      while [ ! -s "$child" ] && [ "$i" -lt 20 ]; do sleep 0.05; i=$((i + 1)); done
      if [ -s "$child" ]; then
        i=0
        while kill -0 "$(cat "$child")" 2>/dev/null && [ "$i" -lt 40 ]; do
          sleep 0.05; i=$((i + 1))
        done
        local alive=no pid
        pid=$(cat "$child")
        if kill -0 "$pid" 2>/dev/null; then
          alive=yes
          kill -KILL "$pid" 2>/dev/null || true
        fi
        assert_eq "$mode failure terminates the sibling descendant" "$alive" no
      else
        fail "$mode failure launches the sibling descendant" "missing child pid"
      fi
      files=$(find "$S/$mode" "$T/provider-bounded-cache-$mode" -type f -name '*.json' \
        2>/dev/null | wc -l | tr -d ' ')
      assert_eq "$mode failure publishes no receipt" "$files" 0
    done
    assert_grep "timeout has a stable shared-deadline failure" "$T/provider-timeout.err" \
      '^contract replay failed: shared deadline exceeded'
    assert_grep "output flood has a stable cap failure" "$T/provider-flood.err" \
      '^contract replay failed: provider_envelope_replay \(output limit exceeded\)$'
    assert_grep "fast failure keeps its group and status" "$T/provider-fail.err" \
      '^contract replay failed: provider_envelope_replay \(exit 7\)$'
    assert_grep "fast failure retains its bounded diagnostic tail" "$T/provider-fail.err" \
      'stable fast failure'
    assert_grep "successful parent with a child has a stable failure" \
      "$T/provider-success-child.err" \
      '^contract replay failed: provider_envelope_replay left a descendant process running$'
    local bytes; bytes=$(wc -c < "$T/provider-flood.err" | tr -d ' ')
    [ "$bytes" -le 512 ] && ok "output flood diagnostics stay byte bounded" \
      || fail "output flood diagnostics stay byte bounded" "${bytes} bytes"
  )
}
