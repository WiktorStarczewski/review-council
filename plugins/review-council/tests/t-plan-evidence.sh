#!/bin/bash

replace_literal() {
  python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1]); old = sys.argv[2]; new = sys.argv[3]
text = path.read_text()
if old not in text:
    raise SystemExit('fixture text not found: ' + old)
path.write_text(text.replace(old, new))
PY
}

insert_scope_line() {
  python3 - "$1" "$2" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1]); line = sys.argv[2]; text = path.read_text()
marker = '## Scope\n'
if marker not in text:
    raise SystemExit('scope heading not found')
path.write_text(text.replace(marker, marker + line + '\n', 1))
PY
}

test_plan_evidence_closure() {
  ( local R="$T/plan-evidence-root" S="$T/plan-evidence-session"
    mkrepo "$R"; mkdir -p "$R/src" "$R/tests" "$S"
    cat > "$R/src/helper.ts" <<'EOF'
export function helper() { return 1; }
EOF
    cat > "$R/src/service.ts" <<'EOF'
import { helper } from "./helper";
export function runService() { return helper(); }
EOF
    cat > "$R/src/sibling.ts" <<'EOF'
export function runAlias() { return 1; }
EOF
    cat > "$R/tests/service.test.ts" <<'EOF'
import { runService } from "../src/service";
test("service", () => runService());
EOF
    python3 - "$R/src/unrelated.ts" <<'PY'
import sys
open(sys.argv[1], 'w').write('\n'.join(f'export const unrelated{i} = {i};' for i in range(600)) + '\n')
PY
    git -C "$R" add . && git -C "$R" commit -qm "plan base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    replace_literal "$R/src/helper.ts" 'return 1' 'return 2' || return
    replace_literal "$R/src/service.ts" 'helper();' 'helper() + 1;' || return
    replace_literal "$R/tests/service.test.ts" 'runService());' 'runService() + 1);' || return
    python3 - "$R/src/unrelated.ts" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); p.write_text(p.read_text().replace(' = ', ' = 1000 + '))
PY
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' src/helper.ts src/service.ts src/unrelated.ts tests/service.test.ts > "$S/files.txt"
    : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - keep service results stable
Findings: F-001 (P1)
Rule: Apply the helper result exactly once at every service entry.
Sites: src/service.ts:1-2 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' .)
Must not: Change unrelated exports.
Test: tests/service.test.ts:1-2
Interacts with: none.
## C-02 - keep helper callers visible
Findings: F-002 (P1)
Rule: Check every helper caller before changing the helper result.
Sites: src/helper.ts:1 (found by: grep --exclude-dir=.git --null -r -n -- 'helper' .)
Must not: Skip callers outside the service entry.
Test: tests/service.test.ts:1-2
Interacts with: C-01.
EOF
    local plan_hash manifest
    plan_hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local assignments=(
      --assignment sol=plan-completeness
      --assignment terra=plan-soundness
      --assignment opus=plan-simplicity
      --assignment sonnet=plan-tests
    )
    manifest=$(REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1p --phase plan \
      --plan "$S/fix-plan.md" --plan-sha256 "$plan_hash" --full-seat sol \
      "${assignments[@]}") || return
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1p-child --phase repair \
      --assignment terra=plan-soundness --parent-assignment 1p:terra \
      > "$T/plan-child.out" 2> "$T/plan-child.err"
    assert_eq "plan replacement keeps whole-panel recovery" "$?" 2
    assert_grep "plan replacement has a stable fallback reason" "$T/plan-child.err" \
      'plan parent assignments require whole-panel recovery'
    assert_exit "plan evidence prompt requires the bound plan argument" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 1p sol plan-completeness plan --evidence "$manifest"
    python3 - "$manifest" <<'PY'
import json, pathlib, sys
m = json.load(open(sys.argv[1])); session = pathlib.Path(sys.argv[1]).parent
assert m['schema_version'] == 4 and m['phase'] == 'plan'
assert m['mechanical_owner'] == 'sol' and m['assignments']['sol']['scope'] == 'full'
closures = [a for seat, a in m['assignments'].items() if seat != 'sol']
assert all(a['scope'] == 'closure' for a in closures)
assert m['plan']['routing_version'] == 1
assert m['plan']['delta_mode'] == 'cumulative-closure'
assert m['predecessor'] is None
assert m['assignments']['sol']['plan_clusters'] == ['C-01', 'C-02']
assert m['assignments']['terra']['plan_clusters'] == ['C-01']
assert m['assignments']['opus']['plan_clusters'] == ['C-02']
assert m['assignments']['sonnet']['plan_clusters'] == ['C-01']
assert m['assignments']['terra']['delta_clusters'] == ['C-01']
assert m['assignments']['opus']['delta_clusters'] == ['C-02']
assert m['assignments']['sonnet']['delta_clusters'] == []
assert sum('C-01' in a['plan_clusters'] for a in m['assignments'].values()) == 3
assert sum('C-02' in a['plan_clusters'] for a in m['assignments'].values()) == 2
assert m['assignments']['sonnet']['patch_bytes'] == 0
assert all(a['plan_clusters'] for seat, a in m['assignments'].items() if seat != 'sol')
assert m['plan']['common_artifacts'] == ['r1p-evidence.md']
assert all(a['required_artifacts'] for a in m['assignments'].values())
closure = (session / 'r1p-plan-closure.patch').read_text()
assert 'src/service.ts' in closure and 'src/helper.ts' in closure
assert 'tests/service.test.ts' in closure and 'src/unrelated.ts' not in closure
specialist_paths = {
    seat: {path for component in m['components'] if seat in component['specialists']
           for path in component['files']}
    for seat in ('terra', 'opus')}
assert specialist_paths['terra'] | specialist_paths['opus'] == {
    'src/helper.ts', 'src/service.ts', 'tests/service.test.ts'}
assert set(m['assignments']['terra']['delta_paths']).isdisjoint(
    m['assignments']['opus']['delta_paths'])
required = {
    seat: ({row['path'] for row in m['source_context']['seats'][seat]['required_source_ranges']}
           | {row['path'] for shard in m['source_context']['seats'][seat]['shards']
              for row in shard['ranges']})
    for seat in ('terra', 'opus')}
assert {'src/service.ts', 'tests/service.test.ts'} <= required['terra']
assert {'src/helper.ts', 'tests/service.test.ts'} <= required['opus']
assert all(len(packet['shards']) <= 3 for packet in m['source_context']['seats'].values())
assert m['word_counts']['assigned_patch'] * 10 <= m['word_counts']['full'] * 4 * 9
assert m['word_counts']['plan'] > 0 and m['word_counts']['closure'] > 0
clusters = {cluster['id']: cluster for cluster in m['plan']['clusters']}
assert m['word_counts']['prepared_search'] == sum(
    len((session / clusters[cluster_id]['search_proof']['artifact']).read_bytes().split())
    for assignment in m['assignments'].values()
    for cluster_id in assignment['plan_clusters'])
cluster = m['plan']['clusters'][0]
assert cluster['id'] == 'C-01' and cluster['search_pattern'] == 'run(Service|Alias)'
assert cluster['search_contract'] == {
    'engine':'rg','domain':'rg-complete-worktree','pattern':'run(Service|Alias)'}
assert cluster['search_proof']['status'] == 0
assert cluster['search_proof']['saturated'] is False
assert cluster['search_proof']['paths'] == [
    'src/service.ts', 'src/sibling.ts', 'tests/service.test.ts']
assert (session / cluster['search_proof']['artifact']).is_file()
assert m['plan']['clusters'][1]['search_contract'] == {
    'engine':'grep-bre','domain':'grep-complete-worktree','pattern':'helper'}
assert {row['path'] for row in cluster['paths']} == {'src/service.ts', 'tests/service.test.ts'}
PY
    assert_eq "plan evidence assigns every cluster to integration and one specialist" "$?" 0

    local seat prompt lens
    for seat in sol terra opus sonnet; do
      case "$seat" in
        sol) lens=plan-completeness;;
        terra) lens=plan-soundness;;
        opus) lens=plan-simplicity;;
        *) lens=plan-tests;;
      esac
      prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1p "$seat" \
        "$lens" \
        plan --plan "$S/r1p-plan.md" --evidence "$manifest") || return
      assert_grep "$seat prompt contains the complete plan" "$prompt" '## C-01 - keep service results stable$'
      assert_exit "$seat prompt does not advertise a denied plan path" 0 \
        python3 - "$prompt" "$S/r1p-plan.md" <<'PY'
from pathlib import Path
import sys

assert sys.argv[2] not in Path(sys.argv[1]).read_text()
PY
      if [ "$seat" != sol ]; then
        assert_exit "$seat prompt puts its first read before competing evidence work" 0 \
          python3 - "$prompt" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
first = next(index for index, line in enumerate(lines)
             if line.startswith('Plan specialist first-call contract: '))
competing = (
    'Prepared cluster sibling search:', 'Required cluster sibling search:',
    'Required cluster source:', 'Assigned patch read mode:',
    'Canonical assigned patch:', 'Read the entire assigned patch',
    'Source context packet:', 'Required source segment ',
    'Evidence navigation index:',
)
later = [index for index, line in enumerate(lines)
         if line.startswith(competing)]
assert later and first < min(later), (first, min(later))
PY
      fi
      assert_grep "$seat prompt accepts its prepared search as proof" "$prompt" \
        'use its rendered prepared sibling-site result as the required search proof'
      assert_grep "$seat prompt limits additional search to unresolved questions" "$prompt" \
        'Run an additional search only to answer a concrete unresolved question'
      assert_nogrep "$seat prompt does not rerun every cluster search" "$prompt" \
        'For every cluster, run its rendered required sibling-site search'
      if [ "$seat" = sol ] || [ "$seat" = terra ]; then
        assert_grep "$seat prompt contains its frozen rg cluster search" "$prompt" \
          '^Prepared cluster sibling search: C-01 .* SHA-256 [0-9a-f]{64}$'
        assert_grep "$seat prompt contains the frozen sibling result" "$prompt" \
          'src/sibling\.ts\\u0000'
        assert_grep "$seat prompt renders its full plan source range" "$prompt" \
          '^Required cluster source: C-01 src/service.ts:1-2 resolution direct field sites$'
      else
        assert_nogrep "$seat prompt omits the unassigned rg cluster proof" "$prompt" \
          '^Required cluster sibling search: C-01 '
      fi
      if [ "$seat" = sol ] || [ "$seat" = opus ]; then
        assert_grep "$seat prompt contains its frozen grep cluster search" "$prompt" \
          '^Prepared cluster sibling search: C-02 .* SHA-256 [0-9a-f]{64}$'
      else
        assert_nogrep "$seat prompt omits the unassigned grep cluster proof" "$prompt" \
          '^Required cluster sibling search: C-02 '
      fi
      if [ "$seat" = sol ]; then
        printf '%s\n' '{"summary":"checked","findings":[{"severity":"P1","file":"r1p-plan.md","line_start":2,"line_end":3,"claim":"plan rule needs another constraint","evidence":"the findings and rule lines omit it","suggested_fix":"add the constraint to this cluster","confidence":0.9}]}' > "$S/r1p-$seat.json"
      else
        printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r1p-$seat.json"
      fi
      printf '0\n' > "$S/r1p-$seat.exit"
      python3 - "$manifest" "$seat" "$S/r1p-$seat.stream.ndjson" <<'PY'
import json, pathlib, sys
m = json.load(open(sys.argv[1])); seat = sys.argv[2]; out = pathlib.Path(sys.argv[3])
session = pathlib.Path(sys.argv[1]).parent; root = pathlib.Path(m['session']).parent / 'plan-evidence-root'
events = []
assignment = m['assignments'][seat]; patch = pathlib.Path(assignment['patch'])
def call(identity, command, output, path, offset=None, limit=None):
    if assignment['adapter'] == 'codex':
        events.extend([
            {'type':'item.started','item':{'id':identity,'type':'command_execution','command':command}},
            {'type':'item.completed','item':{'id':identity,'type':'command_execution','command':command,
                                             'aggregated_output':output,'exit_code':0}},
        ])
    else:
        tool_input = {'file_path':str(path)}
        if offset is not None:
            tool_input.update(offset=offset, limit=limit)
        events.extend([
            {'type':'assistant','message':{'content':[{
                'type':'tool_use','id':identity,'name':'Read','input':tool_input}]}},
            {'type':'user','message':{'content':[{
                'type':'tool_result','tool_use_id':identity,'content':output}]}},
        ])
if assignment['patch_read_mode'] == 'chunks':
    for row in m['patch_sets'][assignment['patch_set']]['chunks']:
        path = session / row['artifact']; call('patch-' + str(row['index']), 'cat -- ' + str(path), path.read_text(), path)
else:
    lines = patch.read_text().splitlines(keepends=True)
    for start in range(1, len(lines) + 1, 240):
        end = min(len(lines), start + 239)
        call('patch-' + str(start), "sed -n '%d,%dp' %s" % (start, end, patch),
             ''.join(lines[start - 1:end]), patch, start, 240)
context = m['source_context']['seats'][seat]
for index, shard in enumerate(context['shards'], 1):
    path = session / shard['artifact']; call('packet-' + str(index), 'cat -- ' + str(path), path.read_text(), path)
index = session / f"r{m['label']}-evidence.md"
call('evidence-index', 'cat -- ' + str(index), index.read_text(), index)
if context['source_read_required']:
    path = root / 'src/service.ts'; call('source', "sed -n '1,2p' " + str(path),
        ''.join(path.read_text().splitlines(keepends=True)[:2]), path, 1, 2)
out.write_text(''.join(json.dumps(event) + '\n' for event in events))
PY
      local adapter=codex
      case "$seat" in opus|sonnet) adapter=claude;; esac
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter "$adapter" \
        --raw "$S/r1p-$seat.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
        --out "$S/r1p-$seat.read-audit.json" >/dev/null || return
    done
    cp "$S/r1p-terra.stream.ndjson" "$T/plan-first-call.valid"
    local first_case=0 first_kind
    for first_kind in directory search compound; do
      first_case=$((first_case + 1))
      python3 - "$T/plan-first-call.valid" "$S/r1p-terra.stream.ndjson" \
        "$manifest" "$first_kind" <<'PY'
import json, pathlib, sys
source, target, manifest_path, kind = sys.argv[1:]
manifest = json.load(open(manifest_path)); assignment = manifest['assignments']['terra']
if assignment['patch_read_mode'] == 'chunks' and assignment['patch_bytes']:
    primary = pathlib.Path(manifest['session']) / manifest['patch_sets'][assignment['patch_set']]['chunks'][0]['artifact']
elif assignment['patch_bytes']:
    primary = pathlib.Path(assignment['patch'])
else:
    candidates = [name for name in assignment['required_artifacts']
                  if name != pathlib.Path(assignment['patch']).name]
    primary = pathlib.Path(manifest['session']) / (candidates[0] if candidates
              else manifest['plan']['common_artifacts'][0])
commands = {
    'directory':'ls src',
    'search':"rg -- 'service' src",
    'compound':'cat -- ' + str(primary) + '; pwd',
}
event = {'type':'item.completed','item':{
    'id':'invalid-first-' + kind, 'type':'command_execution',
    'command':commands[kind], 'aggregated_output':'', 'exit_code':0}}
pathlib.Path(target).write_text(json.dumps(event) + '\n' + pathlib.Path(source).read_text())
PY
      assert_exit "plan audit rejects a $first_kind call before the primary artifact" 2 \
        python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
          --raw "$S/r1p-terra.stream.ndjson" --prompt "$S/r1p-terra.prompt.md" \
          --root "$R" --session "$S" --out "$T/plan-first-$first_case.audit.json"
      assert_grep "$first_kind first-call failure is explicit" \
        "$T/plan-first-$first_case.audit.json" 'invalid-plan-first-call'
    done
    cp "$T/plan-first-call.valid" "$S/r1p-terra.stream.ndjson"
    cp "$S/r1p-sonnet.stream.ndjson" "$T/plan-first-call-sonnet.valid"
    first_case=0
    for first_kind in directory search compound; do
      first_case=$((first_case + 1))
      python3 - "$T/plan-first-call-sonnet.valid" "$S/r1p-sonnet.stream.ndjson" \
        "$manifest" "$first_kind" <<'PY'
import json, pathlib, sys
source, target, manifest_path, kind = sys.argv[1:]
manifest = json.load(open(manifest_path)); assignment = manifest['assignments']['sonnet']
context = manifest['source_context']['seats']['sonnet']
if assignment['patch_read_mode'] == 'chunks' and assignment['patch_bytes']:
    primary = pathlib.Path(manifest['session']) / manifest['patch_sets'][assignment['patch_set']]['chunks'][0]['artifact']
elif assignment['patch_bytes']:
    primary = pathlib.Path(assignment['patch'])
elif context['shards']:
    primary = pathlib.Path(manifest['session']) / context['shards'][0]['artifact']
elif context['required_source_ranges']:
    primary = pathlib.Path(manifest['session']) / context['required_source_ranges'][0]['segments'][0]['artifact']
else:
    primary = pathlib.Path(manifest['session']) / manifest['plan']['common_artifacts'][0]
commands = {
    'directory':'ls src',
    'search':"rg -- 'service' src",
    'compound':'cat -- ' + str(primary) + '; pwd',
}
identity = 'invalid-first-' + kind
events = [
    {'type':'assistant','message':{'content':[{
        'type':'tool_use','id':identity,'name':'Bash',
        'input':{'command':commands[kind]}}]}},
    {'type':'user','message':{'content':[{
        'type':'tool_result','tool_use_id':identity,'content':''}]}},
]
pathlib.Path(target).write_text(
    ''.join(json.dumps(event) + '\n' for event in events) + pathlib.Path(source).read_text())
PY
      assert_exit "Sonnet plan audit rejects a $first_kind call before native Read" 2 \
        python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
          --raw "$S/r1p-sonnet.stream.ndjson" --prompt "$S/r1p-sonnet.prompt.md" \
          --root "$R" --session "$S" --out "$T/plan-sonnet-first-$first_case.audit.json"
      assert_grep "Sonnet $first_kind first-call failure is explicit" \
        "$T/plan-sonnet-first-$first_case.audit.json" 'invalid-plan-first-call'
    done
    cp "$T/plan-first-call-sonnet.valid" "$S/r1p-sonnet.stream.ndjson"
    python3 - "$T/plan-first-call-sonnet.valid" "$S/r1p-sonnet.stream.ndjson" <<'PY'
import json, pathlib, sys

source, target = map(pathlib.Path, sys.argv[1:])
identity = 'denied-directory-before-read'
events = [
    {'type':'assistant','message':{'content':[{
        'type':'tool_use','id':identity,'name':'Bash','input':{'command':'ls src'}}]}},
    {'type':'user','tool_result_meta':[{
     'id':identity,'non_execution_kind':'permission-rule'}],
     'message':{'content':[{
        'type':'tool_result','tool_use_id':identity,
        'content':'PreToolUse:Bash hook error: policy denied\n',
        'is_error':True}]}},
]
target.write_text(''.join(json.dumps(event) + '\n' for event in events) + source.read_text())
PY
    assert_exit "Sonnet plan audit rejects a provider-denied call before native Read" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
        --raw "$S/r1p-sonnet.stream.ndjson" --prompt "$S/r1p-sonnet.prompt.md" \
        --root "$R" --session "$S" --out "$T/plan-sonnet-first-denied.audit.json"
    assert_grep "provider-denied first-call failure is explicit" \
      "$T/plan-sonnet-first-denied.audit.json" 'invalid-plan-first-call'
    python3 - "$S/r1p-sonnet.read-audit.json" \
      "$T/plan-sonnet-first-denied.audit.json" <<'PY'
import json, sys

valid, denied = (json.load(open(path)) for path in sys.argv[1:])
assert denied['tool_calls'] == valid['tool_calls'], (valid['tool_calls'], denied['tool_calls'])
assert any(row['code'] == 'invalid-plan-first-call' for row in denied['violations'])
PY
    assert_eq "provider-denied attempt is audited but excluded from completed tool calls" "$?" 0
    cp "$T/plan-first-call-sonnet.valid" "$S/r1p-sonnet.stream.ndjson"
    mkdir -p "$T/no-plan-search-replay"
    cat > "$T/no-plan-search-replay/rg" <<'EOF'
#!/bin/sh
printf 'rg\n' >> "$PLAN_PROMPT_SEARCH_REPLAY_LOG"
exit 97
EOF
    cat > "$T/no-plan-search-replay/grep" <<'EOF'
#!/bin/sh
printf 'grep\n' >> "$PLAN_PROMPT_SEARCH_REPLAY_LOG"
exit 97
EOF
    chmod +x "$T/no-plan-search-replay/rg" "$T/no-plan-search-replay/grep"
    rm -f "$T/plan-prompt-search-replay.log"
    for seat in sol terra opus sonnet; do
      assert_exit "$seat schema-4 prompt authorizes exactly its manifest artifacts" 0 \
        env PATH="$T/no-plan-search-replay:$PATH" \
          PLAN_PROMPT_SEARCH_REPLAY_LOG="$T/plan-prompt-search-replay.log" \
          python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
            --root "$R" --session "$S" --manifest "$manifest" --seat "$seat" \
            --prompt "$S/r1p-$seat.prompt.md"
    done
    assert_exit "per-seat prompt validation does not replay panel searches" 1 \
      test -e "$T/plan-prompt-search-replay.log"
    cp "$S/r1p-terra.prompt.md" "$T/plan-prompt-artifacts.valid"
    replace_literal "$S/r1p-terra.prompt.md" \
      'Read the entire assigned patch in bounded windows' \
      'Omitted assigned patch in bounded windows' || return
    assert_exit "schema-4 prompt rejects an omitted required artifact" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat terra \
        --prompt "$S/r1p-terra.prompt.md"
    cp "$T/plan-prompt-artifacts.valid" "$S/r1p-terra.prompt.md"
    local full_hash sibling_patch sibling_hash
    full_hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/r1p-full.patch")
    insert_scope_line "$S/r1p-terra.prompt.md" \
      "Canonical assigned patch: $S/r1p-full.patch SHA-256 $full_hash" || return
    assert_exit "schema-4 prompt rejects an unauthorized full patch" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat terra \
        --prompt "$S/r1p-terra.prompt.md"
    python3 - "$T/plan-first-call.valid" "$T/plan-widened.stream.ndjson" \
      "$S/r1p-full.patch" <<'PY'
import json, pathlib, sys

source, target, widened = map(pathlib.Path, sys.argv[1:])
identity = 'widened-full-patch'
event = {'type':'item.completed','item':{
    'id':identity,'type':'command_execution','command':'cat -- ' + str(widened),
    'aggregated_output':widened.read_text(),'exit_code':0}}
target.write_text(source.read_text() + json.dumps(event) + '\n')
PY
    assert_exit "post-run audit rejects a widened specialist prompt and read" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$T/plan-widened.stream.ndjson" --prompt "$S/r1p-terra.prompt.md" \
        --root "$R" --session "$S" --out "$T/plan-widened.audit.json"
    assert_grep "widened specialist audit has a stable artifact-set violation" \
      "$T/plan-widened.audit.json" 'invalid-prompt-artifact-set'
    cp "$T/plan-prompt-artifacts.valid" "$S/r1p-terra.prompt.md"
    replace_literal "$S/r1p-terra.prompt.md" \
      'Plan specialist first-call contract:' 'Plan specialist suggested first call:' || return
    assert_exit "schema-4 prompt binds the mandatory first-call instruction" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat terra \
        --prompt "$S/r1p-terra.prompt.md"
    assert_exit "post-run audit rejects a prompt without the mandatory first-call instruction" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$T/plan-first-call.valid" --prompt "$S/r1p-terra.prompt.md" \
        --root "$R" --session "$S" --out "$T/plan-first-contract.audit.json"
    assert_grep "missing first-call instruction has a stable plan-binding violation" \
      "$T/plan-first-contract.audit.json" 'invalid-plan-prompt-binding'
    cp "$T/plan-prompt-artifacts.valid" "$S/r1p-terra.prompt.md"
    sibling_patch="$S/r1p-opus.patch"
    sibling_hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$sibling_patch")
    insert_scope_line "$S/r1p-terra.prompt.md" \
      "Canonical assigned patch: $sibling_patch SHA-256 $sibling_hash" || return
    assert_exit "schema-4 prompt rejects an unauthorized sibling patch" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat terra \
        --prompt "$S/r1p-terra.prompt.md"
    cp "$T/plan-prompt-artifacts.valid" "$S/r1p-terra.prompt.md"
    printf '{}\n' > "$S/r1p-source-context-999.json"
    insert_scope_line "$S/r1p-terra.prompt.md" \
      "Source context packet: $S/r1p-source-context-999.json SHA-256 0000000000000000000000000000000000000000000000000000000000000000 bytes 3" || return
    assert_exit "schema-4 prompt rejects an unassigned source packet" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat terra \
        --prompt "$S/r1p-terra.prompt.md"
    cp "$T/plan-prompt-artifacts.valid" "$S/r1p-terra.prompt.md"
    replace_literal "$S/r1p-terra.prompt.md" '## Scope' '## Changed scope' || return
    assert_exit "schema-4 prompt rejects a changed scope heading" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat terra \
        --prompt "$S/r1p-terra.prompt.md"
    cp "$T/plan-prompt-artifacts.valid" "$S/r1p-terra.prompt.md"
    replace_literal "$S/r1p-terra.prompt.md" \
      'Read the entire assigned patch in bounded windows' \
      'Changed artifact prefix in bounded windows' || return
    assert_exit "schema-4 prompt rejects a changed artifact prefix" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat terra \
        --prompt "$S/r1p-terra.prompt.md"
    cp "$T/plan-prompt-artifacts.valid" "$S/r1p-terra.prompt.md"
    cp "$S/r1p-sol.prompt.md" "$T/plan-prompt.valid"
    replace_literal "$S/r1p-sol.prompt.md" \
      $'     1\t## C-01 - keep service results stable' \
      $'     1\t## C-01 - truncated from delivered prompt' || return
    assert_exit "plan audit rejects a prompt missing the bound inline plan" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$S/r1p-sol.stream.ndjson" --prompt "$S/r1p-sol.prompt.md" \
        --root "$R" --session "$S" --out "$T/truncated-plan-audit.json"
    assert_grep "truncated inline plan has a stable audit violation" \
      "$T/truncated-plan-audit.json" 'invalid-plan-prompt-binding'
    cp "$T/plan-prompt.valid" "$S/r1p-sol.prompt.md"
    replace_literal "$S/r1p-sol.prompt.md" \
      '## Your lens this round: plan-completeness' \
      '## Your lens this round: plan-soundness' || return
    assert_exit "plan audit rejects a prompt with the wrong assigned lens" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$S/r1p-sol.stream.ndjson" --prompt "$S/r1p-sol.prompt.md" \
        --root "$R" --session "$S" --out "$T/wrong-plan-lens-audit.json"
    assert_grep "wrong assigned lens has a stable audit violation" \
      "$T/wrong-plan-lens-audit.json" 'invalid-assignment-prompt-binding'
    cp "$T/plan-prompt.valid" "$S/r1p-sol.prompt.md"
    assert_exit "verify-panel starts without a coverage head" 1 test -e "$S/coverage-head.json"
    python3 "$SCRIPTS/rev-evidence.py" verify-panel "$S" 1p >/dev/null || return
    assert_exit "verify-panel does not write a coverage head" 1 test -e "$S/coverage-head.json"
    python3 - "$SCRIPTS/rev-evidence.py" "$manifest" <<'PY'
import contextlib, importlib.util, io, pathlib, types, sys
spec=importlib.util.spec_from_file_location('evidence',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
manifest=pathlib.Path(sys.argv[2]); calls=[]; original=module.prepare_plan_searches
def counted(*args, **kwargs):
    calls.append(1)
    return original(*args, **kwargs)
module.prepare_plan_searches=counted
with contextlib.redirect_stdout(io.StringIO()):
    for seat in ('sol','terra','opus','sonnet'):
        for _ in range(2):
            module.render(types.SimpleNamespace(
                manifest=manifest, seat=seat, offline=False,
                plan_source=str(manifest.parent / 'r1p-plan.md')))
assert len(calls) == 0, calls
with contextlib.redirect_stdout(io.StringIO()):
    module.verify(types.SimpleNamespace(manifest=manifest))
assert len(calls) == 1, calls
module.verify_panel_data(manifest.parent, '1p')
assert len(calls) == 1, calls
try:
    with contextlib.redirect_stdout(io.StringIO()):
        module.receipt(types.SimpleNamespace(
            session=str(manifest.parent), label='1p', replacement=[]))
except ValueError as error:
    assert str(error) == 'plan panels never advance code coverage', error
else:
    raise AssertionError('plan receipt unexpectedly succeeded')
assert len(calls) == 1, calls
PY
    assert_eq "render skips searches, prelaunch verify replays once, and postlaunch checks do not replay" "$?" 0
    python3 - "$S/r1p-sol.read-audit.json" "$plan_hash" <<'PY'
import json, sys
a=json.load(open(sys.argv[1]))
assert a['finding_citations'] == 0
assert a['plan_artifact_sha256'] == sys.argv[2]
assert a['plan_finding_citations'] == 1
assert a['plan_citation_ranges'] == [{'line_start':2,'line_end':3}]
assert all(row['path'] != 'r1p-plan.md' for row in a['source_ranges'])
PY
    assert_eq "plan-file findings use separate hash-bound citation ranges" "$?" 0
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json" || return
    python3 - "$S/profile.json" "$manifest" <<'PY'
import json, sys
profile=json.load(open(sys.argv[1]))['sessions'][0]['scope_projection']
manifest=json.load(open(sys.argv[2]))
assert profile['valid_manifests'] == 1 and not profile['invalid_manifests'], profile
assert profile['plan_words'] == manifest['word_counts']['plan']
assert profile['closure_words'] == manifest['word_counts']['closure']
assert profile['assigned_patch_words'] == manifest['word_counts']['assigned_patch']
assert profile['prepared_search_words'] == manifest['word_counts']['prepared_search']
PY
    assert_eq "profile reports plan closure and assigned-patch projections" "$?" 0
    assert_exit "plan panel cannot create a code coverage receipt" 2 \
      python3 "$SCRIPTS/rev-evidence.py" receipt "$S" 1p

    cp "$S/fix-plan.md" "$T/fix-plan.valid"
    printf '\nchanged\n' >> "$S/fix-plan.md"
    assert_exit "verify-panel rejects a changed source plan" 2 \
      python3 "$SCRIPTS/rev-evidence.py" verify-panel "$S" 1p
    cp "$T/fix-plan.valid" "$S/fix-plan.md"
    local search_artifact
    search_artifact=$(python3 -c \
      'import json,sys; print(json.load(open(sys.argv[1]))["plan"]["clusters"][0]["search_proof"]["artifact"])' \
      "$manifest")
    cp "$S/$search_artifact" "$T/prepared-search.valid"
    printf 'changed\n' >> "$S/$search_artifact"
    assert_exit "verify-panel rejects changed prepared search bytes" 2 \
      python3 "$SCRIPTS/rev-evidence.py" verify-panel "$S" 1p
    cp "$T/prepared-search.valid" "$S/$search_artifact"
    python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('rev_evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
accepted = b''.join(b'src/value.ts\x001:value\n' for _ in range(80))
assert module.plan_search_paths(accepted) == ['src/value.ts']
bad = [
    b''.join(b'src/value.ts\x001:value\n' for _ in range(81)),
    b'../outside.ts\x001:value\n',
    b'src/value.ts:1:value\n',
]
for raw in bad:
    try:
        module.plan_search_paths(raw)
    except ValueError:
        continue
    raise AssertionError(raw[:80])
PY
    assert_eq "prepared plan searches accept 80 and reject overflow or malformed paths" "$?" 0

    cp "$S/r1p-evidence.manifest.json" "$T/prepared.manifest"
    cp "$S/r1p-evidence.json" "$T/prepared.evidence"
    cp "$S/r1p-sol.prompt.md" "$T/prepared.prompt"
    cp "$S/r1p-sol.stream.ndjson" "$T/prepared.stream"
    cp "$S/r1p-sol.read-audit.json" "$T/prepared.audit"
    python3 - "$S/r1p-evidence.manifest.json" "$S/r1p-evidence.json" \
      "$S/r1p-sol.prompt.md" "$S/r1p-sol.stream.ndjson" <<'PY'
import hashlib, json, pathlib, sys
manifest_path, evidence_path, prompt_path, stream_path = map(pathlib.Path, sys.argv[1:])
manifest = json.load(open(manifest_path)); evidence = json.load(open(evidence_path))
old_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
outputs = {}
for cluster in manifest['plan']['clusters']:
    proof = cluster.pop('search_proof')
    outputs[cluster['id']] = (manifest_path.parent / proof['artifact']).read_text()
    manifest['artifacts'].pop(proof['artifact'])
for cluster in evidence['plan']['clusters']:
    cluster.pop('search_proof')
manifest['word_counts'].pop('prepared_search')
words = manifest['word_counts']
words['avoided'] = max(0, len(manifest['assignments']) * words['full']
                       - words['assigned_patch']
                       - len(manifest['assignments']) * words['evidence']
                       - words['source_context'])
encoded = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
evidence_raw = encoded(evidence)
evidence_path.write_text(evidence_raw)
manifest['artifacts'][evidence_path.name] = {
    'sha256': hashlib.sha256(evidence_raw.encode()).hexdigest(),
    'words': len(evidence_raw.encode().split()),
}
manifest_path.write_text(encoded(manifest))
new_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
prompt_path.write_text(prompt_path.read_text().replace(
    'Evidence manifest SHA-256: ' + old_hash, 'Evidence manifest SHA-256: ' + new_hash))
events = [json.loads(line) for line in stream_path.read_text().splitlines()]
commands = {
    'C-01': "rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | head -81",
    'C-02': "grep --exclude-dir=.git --null -r -n -- 'helper' . | head -81",
}
for cluster_id in ('C-01', 'C-02'):
    identity = 'search-rg' if cluster_id == 'C-01' else 'search-grep'
    events.extend([
        {'type':'item.started','item':{'id':identity,'type':'command_execution',
                                      'command':commands[cluster_id]}},
        {'type':'item.completed','item':{'id':identity,'type':'command_execution',
                                        'command':commands[cluster_id],
                                        'aggregated_output':outputs[cluster_id], 'exit_code':0}},
    ])
stream_path.write_text(''.join(json.dumps(event) + '\n' for event in events))
PY
    "$SCRIPTS/rev-prompt.sh" "$S" 1p sol plan-completeness plan \
      --plan "$S/r1p-plan.md" --evidence "$S/r1p-evidence.manifest.json" >/dev/null || return
    assert_grep "live plan search reads one overflow sentinel" "$S/r1p-sol.prompt.md" \
      'Required cluster sibling search: C-01 .* \| head -81 .*an 81st line invalidates proof'
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r1p-sol.stream.ndjson" --prompt "$S/r1p-sol.prompt.md" \
      --root "$R" --session "$S" --out "$S/r1p-sol.read-audit.json" >/dev/null || return
    cp "$S/r1p-sol.stream.ndjson" "$T/terra.stream.valid"
    cp "$S/r1p-sol.read-audit.json" "$T/terra.audit.valid"
    python3 - "$S/r1p-sol.stream.ndjson" <<'PY'
import json, sys
p=sys.argv[1]; rows=[]
for line in open(p):
    row=json.loads(line)
    item=row.get('item') or {}
    if item.get('id') == 'search-rg':
        item['command']="cd src && rg --null -n 'run(Service|Alias)' . | head -81"
    rows.append(json.dumps(row))
open(p,'w').write('\n'.join(rows)+'\n')
PY
    assert_exit "subtree-relative search cannot prove a repository-root plan search" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$S/r1p-sol.stream.ndjson" --prompt "$S/r1p-sol.prompt.md" \
        --root "$R" --session "$S" --out "$S/r1p-sol.read-audit.json"
    assert_grep "subtree-relative search has a stable missing-proof failure" \
      "$S/r1p-sol.read-audit.json" '"code":"missing-plan-cluster-search"'
    cp "$T/terra.stream.valid" "$S/r1p-sol.stream.ndjson"
    cp "$T/terra.audit.valid" "$S/r1p-sol.read-audit.json"

    local search_case=0 search_name search_id search_command search_output
    while IFS=$'\t' read -r search_name search_id search_command search_output; do
      search_case=$((search_case + 1))
      python3 - "$T/terra.stream.valid" "$S/r1p-sol.stream.ndjson" \
        "$search_id" "$search_command" "$search_output" <<'PY'
import json, sys
source, target, search_id, command, output = sys.argv[1:]
if output == '@81':
    output=''.join('src/service.ts\0%d:runService\n' % line for line in range(1,82))
elif output == '@80context':
    output='src/service.ts:2:runService\n' + ''.join(
        'src/service.ts-%d-context\n' % line for line in range(3,82))
elif output == '@EMPTY@':
    output=''
else:
    output=output.replace('@NUL@','\0')
rows=[]
for line in open(source):
    row=json.loads(line); item=row.get('item') or {}
    if item.get('id') == search_id:
        item['command']=command
        if row.get('type') == 'item.completed':
            item['aggregated_output']=output
    rows.append(json.dumps(row))
open(target,'w').write('\n'.join(rows)+'\n')
PY
      assert_exit "$search_name cannot earn a root-search proof" 2 \
        python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
          --raw "$S/r1p-sol.stream.ndjson" --prompt "$S/r1p-sol.prompt.md" \
          --root "$R" --session "$S" --out "$S/r1p-sol.read-audit.json"
      assert_grep "$search_name has a stable missing-proof failure" \
        "$S/r1p-sol.read-audit.json" '"code":"missing-plan-cluster-search"'
    done <<'CASES'
nonrecursive grep	search-rg	grep -n 'run(Service|Alias)' . | head -81	grep: .: Is a directory
pipeline-masked producer error	search-rg	grep --null -R -n 'run(Service|Alias)' . | head -81	grep: .: Is a directory
scope-narrowing rg glob	search-rg	rg --glob '*.ts' -n 'run(Service|Alias)' . | head -81	src/service.ts:2:export function runService()
scope-narrowing rg max depth	search-rg	rg --max-depth 1 -n 'run(Service|Alias)' . | head -81	src/service.ts:2:export function runService()
multiple root operands	search-rg	rg --null -n 'run(Service|Alias)' src . | head -81	src/service.ts@NUL@2:export function runService()
omitted sibling via invert match	search-rg	rg --invert-match -n 'run(Service|Alias)' . | head -81	src/helper.ts:1:export function helper()
mixed BRE engine with empty output	search-rg	grep --null -R -n 'run(Service|Alias)' . | head -81	@EMPTY@
rg no-filename long	search-rg	rg --no-filename -n 'run(Service|Alias)' . | head -81	src/service.ts:2:export function runService()
rg no-filename short	search-rg	rg -I -n 'run(Service|Alias)' . | head -81	src/service.ts:2:export function runService()
grep no-filename long	search-grep	grep -R --no-filename -n 'helper' . | head -81	export function helper()
grep no-filename short	search-grep	grep -Rh -n 'helper' . | head -81	export function helper()
context consumes cap before sibling	search-rg	rg --null -A 80 -n 'run(Service|Alias)' . | head -81	@80context
slash-qualified local rg	search-rg	./rg --null -n 'run(Service|Alias)' . | head -81	zsh: command not found: ./rg
slash-qualified grep	search-rg	tools/grep --null -R -n 'run(Service|Alias)' . | head -81	tools/grep: No such file or directory
absolute ripgrep alias	search-rg	/tmp/ripgrep -n 'run(Service|Alias)' . | head -81	/tmp/ripgrep: not found
missing overflow sentinel	search-rg	rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | head -80	src/service.ts@NUL@2:runService
more than 80 exact matches	search-rg	rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | head -81	@81
smaller head can hide matches	search-rg	rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | head -40	src/service.ts@NUL@2:runService
tail can hide earlier matches	search-rg	rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | tail -80	src/service.ts@NUL@2:runService
recursive grep follows symlinks	search-grep	grep --exclude-dir=.git --null -R -n -- 'helper' . | head -81	./src/helper.ts@NUL@1:helper
egrep alias cannot prove BRE search	search-grep	egrep --exclude-dir=.git --null -r -n -- 'helper' . | head -81	./src/helper.ts@NUL@1:helper
fgrep alias cannot prove BRE search	search-grep	fgrep --exclude-dir=.git --null -r -n -- 'helper' . | head -81	./src/helper.ts@NUL@1:helper
unknown grep diagnostic	search-grep	grep --null -R -n '\(' . | head -81	grep: parentheses not balanced
redirected search output	search-rg	rg --null -n 'run(Service|Alias)' . | head -81 >/dev/null	src/service.ts@NUL@2:runService
empty exact search	search-rg	rg --null -n 'run(Service|Alias)' . | head -81	@EMPTY@
colon filename cannot impersonate site	search-rg	rg --null -n 'run(Service|Alias)' . | head -81	src/service.ts:2:decoy@NUL@1:runService
CASES

    while IFS=$'\t' read -r search_name search_id search_command search_output; do
      python3 - "$T/terra.stream.valid" "$S/r1p-sol.stream.ndjson" \
        "$search_id" "$search_command" "$search_output" <<'PY'
import json, sys
source, target, search_id, command, output = sys.argv[1:]
if output == '@80':
    output=''.join('src/service.ts\0%d:runService\n' % line for line in range(1,81))
elif output == '@79':
    output=''.join('src/service.ts\0%d:runService\n' % line for line in range(1,80))
else:
    output=output.replace('@NUL@','\0')
rows=[]
for line in open(source):
    row=json.loads(line); item=row.get('item') or {}
    if item.get('id') == search_id:
        item['command']=command
        if output and row.get('type') == 'item.completed':
            item['aggregated_output']=output
    rows.append(json.dumps(row))
open(target,'w').write('\n'.join(rows)+'\n')
PY
      assert_exit "$search_name earns a root-search proof" 0 \
        python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
          --raw "$S/r1p-sol.stream.ndjson" --prompt "$S/r1p-sol.prompt.md" \
          --root "$R" --session "$S" --out "$S/r1p-sol.read-audit.json"
    done <<'CASES'
complete-worktree rg	search-rg	rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | head -81	src/service.ts@NUL@2:runService
79 exact match lines	search-rg	rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | head -81	@79
80 exact match lines	search-rg	rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' . | head -81	@80
complete recursive grep	search-grep	grep --exclude-dir=.git --null -r -n -- 'helper' . | head -81	./src/helper.ts@NUL@1:helper
complete long recursive grep	search-grep	grep --exclude-dir=.git --null --recursive -n -- 'helper' . | head -81	./src/helper.ts@NUL@1:helper
complete grep with filename	search-grep	grep --exclude-dir=.git --null -rH -n -- 'helper' . | head -81	./src/helper.ts@NUL@1:helper
CASES
    cp "$T/terra.stream.valid" "$S/r1p-sol.stream.ndjson"
    cp "$T/terra.audit.valid" "$S/r1p-sol.read-audit.json"

    local native_name native_data native_exit
    while IFS=$'\t' read -r native_name native_exit native_data; do
      python3 - "$T/terra.stream.valid" "$S/r1p-sol.stream.ndjson" \
        "$native_data" <<'PY'
import json, sys
source, target, search_data = sys.argv[1:]
events=[]
for line in open(source):
    row=json.loads(line); item=row.get('item') or {}
    if row.get('type') != 'item.completed' or item.get('type') != 'command_execution':
        continue
    identity=item['id']; name='Grep' if identity == 'search-rg' else 'Bash'
    data=json.loads(search_data) if identity == 'search-rg' else {'command':item['command']}
    events.extend([
        {'type':'assistant','message':{'content':[
            {'type':'tool_use','id':identity,'name':name,'input':data}]}},
        {'type':'user','message':{'content':[
            {'type':'tool_result','tool_use_id':identity,
             'content':item.get('aggregated_output',''),'is_error':False}]}},
    ])
open(target,'w').write(''.join(json.dumps(row)+'\n' for row in events))
PY
      assert_exit "$native_name native root-search contract" "$native_exit" \
        python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
          --raw "$S/r1p-sol.stream.ndjson" --prompt "$S/r1p-sol.prompt.md" \
          --root "$R" --session "$S" --out "$S/r1p-sol.read-audit.json"
      if [ "$native_exit" != 0 ]; then
        assert_grep "$native_name native search has no cluster proof" \
          "$S/r1p-sol.read-audit.json" '"code":"missing-plan-cluster-search"'
      fi
    done <<'CASES'
exact	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80}
glob	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80,"glob":"*.ts"}
type	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80,"type":"ts"}
offset	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80,"offset":10}
CASES
    cp "$T/terra.stream.valid" "$S/r1p-sol.stream.ndjson"
    cp "$T/terra.audit.valid" "$S/r1p-sol.read-audit.json"

    cp "$T/prepared.manifest" "$S/r1p-evidence.manifest.json"
    cp "$T/prepared.evidence" "$S/r1p-evidence.json"
    cp "$T/prepared.prompt" "$S/r1p-sol.prompt.md"
    cp "$T/prepared.stream" "$S/r1p-sol.stream.ndjson"
    cp "$T/prepared.audit" "$S/r1p-sol.read-audit.json"
    python3 - "$S/r1p-sol.read-audit.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d['plan_cluster_search_proofs'] = []; open(p, 'w').write(json.dumps(d))
PY
    assert_exit "verify-panel rejects a missing cluster search proof" 2 \
      python3 "$SCRIPTS/rev-evidence.py" verify-panel "$S" 1p
  )
}

test_plan_evidence_fail_closed() {
  ( local R="$T/plan-fail-root" S="$T/plan-fail-session"
    mkrepo "$R"; mkdir -p "$R/src" "$R/one" "$R/two" "$S"
    printf 'export const value = 1;\n' > "$R/src/value.ts"
    python3 - "$R/src/unrelated.ts" <<'PY'
import sys
open(sys.argv[1], 'w').write('\n'.join(f'export const unrelated{i} = {i};' for i in range(300)) + '\n')
PY
    printf 'test value\n' > "$R/one/value.test.ts"
    printf 'test value\n' > "$R/two/value.test.ts"
    git -C "$R" add . && git -C "$R" commit -qm "plan fail base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf 'export const value = 2;\n' > "$R/src/value.ts"
    replace_literal "$R/src/unrelated.ts" ' = ' ' = 10 + ' || return
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/value.ts\nsrc/unrelated.ts\n' > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - ambiguous test
Findings: F-001
Rule: Keep value stable.
Sites: src/value.ts:1 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'value' .)
Test: value.test.ts:1
EOF
    local hash; hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    assert_exit "ambiguous basename rejects the whole adaptive plan attempt" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 2p "${args[@]}"
    assert_eq "failed plan preparation publishes no manifest" \
      "$(find "$S" -maxdepth 1 -name 'r2p-*' | wc -l | tr -d ' ')" 0
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"grok"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 2p-retired "${args[@]}" \
      > "$T/plan-retired.out" 2> "$T/plan-retired.err"
    assert_eq "retired plan adapter fails before launch" "$?" 2
    assert_grep "retired plan adapter gets a stable rejection" \
      "$T/plan-retired.err" 'unsupported or retired roster adapter: grok'
    assert_eq "retired adapter rejection publishes no artifacts" \
      "$(find "$S" -maxdepth 1 -name 'r2p-retired-*' | wc -l | tr -d ' ')" 0
    replace_literal "$S/fix-plan.md" 'Test: value.test.ts:1' 'Test: one/value.test.ts:1' || return
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"agent"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 3p "${args[@]}" \
      > "$T/plan-agent.out" 2> "$T/plan-agent.err"
    assert_eq "agent plan routing fails before launch" "$?" 2
    assert_grep "agent failure names the unenforceable restricted contract" \
      "$T/plan-agent.err" 'agent adapter cannot enforce receipt-relative plan specialist scope'
    assert_eq "agent failure publishes no artifacts" \
      "$(find "$S" -maxdepth 1 -name 'r3p-*' | wc -l | tr -d ' ')" 0
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"},{"seat":"agent-extra","adapter":"agent","extra":true}]}' > "$S/roster.json"
    local valid_args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    assert_exit "an extra Agent seat does not block a CLI-backed core plan panel" 0 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 3p-extra "${valid_args[@]}"
    assert_exit "stale plan hash rejects adaptive plan preparation" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 4p "${valid_args[@]/$hash/0000000000000000000000000000000000000000000000000000000000000000}"
    ln "$S/fix-plan.md" "$S/hardlinked-plan.md"
    valid_args=(--phase plan --plan "$S/hardlinked-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    assert_exit "hardlinked plan source rejects adaptive plan preparation" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 5p "${valid_args[@]}"
    rm "$S/hardlinked-plan.md"
    printf 'export const value = "-legacy";\n' > "$R/src/value.ts"
    sed "s/-- 'value' \./-- -legacy ./" "$S/fix-plan.md" > "$S/legacy-pattern-plan.md"
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/legacy-pattern-plan.md")
    valid_args=(--phase plan --plan "$S/legacy-pattern-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    local legacy_manifest
    legacy_manifest=$(python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 6p "${valid_args[@]}") || return
    assert_grep "prepare preserves a leading-hyphen search expression" "$legacy_manifest" \
      '"search_pattern": "-legacy"'
    sed 's/-- -legacy \./-e one -e two -- ./' "$S/legacy-pattern-plan.md" > "$S/multiple-expression-plan.md"
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/multiple-expression-plan.md")
    valid_args=(--phase plan --plan "$S/multiple-expression-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    assert_exit "prepare rejects multiple search expressions" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 7p "${valid_args[@]}"
  )
}

test_plan_receipt_relative_routing() {
  ( local R="$T/plan-relative-root" S="$T/plan-relative-session"
    mkrepo "$R"; mkdir -p "$R/src" "$R/tests" "$S"
    printf 'export function service() { return 1; }\n' > "$R/src/service.ts"
    printf 'import { service } from "../src/service";\ntest("service", service);\n' \
      > "$R/tests/service.test.ts"
    python3 - "$R/src/unrelated.ts" <<'PY'
import sys
open(sys.argv[1], 'w').write(''.join(f'export const padding{i} = {i};\n' for i in range(800)))
PY
    git -C "$R" add . && git -C "$R" commit -qm "receipt relative base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    replace_literal "$R/src/service.ts" 'return 1' 'return 2' || return
    replace_literal "$R/src/unrelated.ts" ' = ' ' = 1000 + ' || return
    printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" "$base" "$R" > "$S/scope.env"
    printf '%s\n' src/service.ts > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - keep the service stable
Findings: F-001
Rule: Preserve the service result.
Sites: src/service.ts:1 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'service' .)
Test: tests/service.test.ts:1-2
EOF
    REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 python3 - \
      "$SCRIPTS/rev-evidence.py" "$S" "$R" <<'PY'
import contextlib, hashlib, importlib.util, io, json, os, pathlib, sys, types
script, session_value, root_value = sys.argv[1:]
session = pathlib.Path(session_value).resolve(); root = pathlib.Path(root_value).resolve()
spec = importlib.util.spec_from_file_location('evidence', script)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
snapshot = module.Repository(session).snapshot()[0]
reference = {'receipt':'rfrozen-coverage.receipt.json','sha256':'1' * 64}
coverage = {'snapshot_tree':snapshot, 'coverage_reference':reference, 'findings':[]}
module.prior_coverage = lambda *args, **kwargs: {
    'status':'valid', 'coverage':coverage, 'reason':None}
plan = session / 'fix-plan.md'
plan_hash = hashlib.sha256(plan.read_bytes()).hexdigest()
assignments = [
    'sol=plan-completeness', 'terra=plan-soundness',
    'opus=plan-simplicity', 'sonnet=plan-tests']
def prepare(label):
    args = types.SimpleNamespace(
        session=str(session), label=label, phase='plan', head=None,
        assignment=assignments, full_seat='sol', plan=str(plan),
        plan_sha256=plan_hash, parent_assignment=None)
    with contextlib.redirect_stdout(io.StringIO()):
        module.prepare(args)
    return json.loads((session / f'r{label}-evidence.manifest.json').read_text())

same = prepare('same')
assert same['schema_version'] == 4
assert same['plan']['delta_mode'] == 'receipt-delta'
assert same['predecessor'] == reference
assert same['assignments']['sol']['scope'] == 'full'
assert same['assignments']['sol']['patch_bytes'] > 0
assert all(same['assignments'][seat]['scope'] == 'delta'
           for seat in ('terra','opus','sonnet'))
assert all(same['assignments'][seat]['patch_bytes'] == 0
           for seat in ('terra','opus','sonnet'))
assert all(same['assignments'][seat]['plan_clusters'] == ['C-01']
           for seat in ('terra','opus','sonnet'))
assert same['assignments']['terra']['delta_clusters'] == ['C-01']
assert same['assignments']['opus']['delta_clusters'] == []
assert same['assignments']['sonnet']['delta_clusters'] == []
assert same['plan']['common_artifacts'] == ['rsame-evidence.md']
for seat, assignment in same['assignments'].items():
    expected = {pathlib.Path(assignment['patch']).name}
    expected.update(chunk['artifact'] for chunk in
                    same['patch_sets'][assignment['patch_set']]['chunks'])
    packet = same['source_context']['seats'][seat]
    expected.update(shard['artifact'] for shard in packet['shards'])
    expected.update(segment['artifact'] for row in packet['required_source_ranges']
                    for segment in row['segments'])
    assert assignment['required_artifacts'] == sorted(expected)

(root / 'src/unrelated.ts').write_text(
    (root / 'src/unrelated.ts').read_text() + 'export const later = 1;\n')
unrelated = prepare('unrelated')
assert all(unrelated['assignments'][seat]['patch_bytes'] == 0
           for seat in ('terra','opus','sonnet'))
(root / 'src/service.ts').write_text(
    (root / 'src/service.ts').read_text().replace('return 2', 'return 3'))
changed = prepare('changed')
assert changed['assignments']['terra']['delta_paths'] == ['src/service.ts']
assert changed['assignments']['terra']['patch_bytes'] > 0
assert changed['assignments']['opus']['patch_bytes'] == 0
assert changed['assignments']['sonnet']['patch_bytes'] == 0
assert all(assignment['scope'] != 'full' for seat, assignment in
           changed['assignments'].items() if seat != 'sol')

module.prior_coverage = lambda *args, **kwargs: {
    'status':'invalid', 'coverage':None,
    'reason':'invalid coverage predecessor: fixture'}
cumulative = prepare('cumulative')
assert cumulative['plan']['delta_mode'] == 'cumulative-closure'
assert cumulative['predecessor'] is None
assert cumulative['assignments']['terra']['patch_bytes'] > 0
assert all(assignment['scope'] != 'full' for seat, assignment in
           cumulative['assignments'].items() if seat != 'sol')
PY
    assert_eq "schema-4 plans route receipt-relative deltas and preserve proof coverage" "$?" 0
    local label seat manifest_hash
    for label in same unrelated changed cumulative; do
      manifest_hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' \
        "$S/r$label-evidence.manifest.json")
      for seat in sol terra opus sonnet; do
        printf 'Evidence manifest SHA-256: %s\n' "$manifest_hash" \
          > "$S/r$label-$seat.prompt.md"
      done
    done
    "$SCRIPTS/rev-profile.py" --json "$S" > "$S/profile.json" || return
    python3 - "$S/profile.json" "$S" <<'PY'
import json, pathlib, sys
profile = json.load(open(sys.argv[1]))['sessions'][0]['scope_projection']
session = pathlib.Path(sys.argv[2])
manifests = [json.load(open(path)) for path in session.glob('r*-evidence.manifest.json')]
expected_specialist = sum(
    len(pathlib.Path(assignment['patch']).read_bytes().split())
    for manifest in manifests for seat, assignment in manifest['assignments'].items()
    if seat != manifest['mechanical_owner'])
assert profile['receipt_relative_plan_manifests'] == 3, profile
assert profile['cumulative_plan_manifests'] == 1, profile
assert profile['plan_specialist_patch_words'] == expected_specialist, profile
PY
    assert_eq "profile separates receipt-relative plan routing from roster identity" "$?" 0
  )
}

test_plan_generated_name_collision() {
  ( local R="$T/plan-name-root" S="$T/plan-name-session"
    mkrepo "$R"; mkdir -p "$R/src" "$R/tests" "$S"
    printf 'export const value = 1;\n' > "$R/src/value.ts"
    : > "$R/src/empty.ts"
    printf 'test value\n' > "$R/tests/value.test.ts"
    printf 'repository source with a generated-looking name\n' > "$R/r1p-plan.md"
    python3 - "$R/src/unrelated.ts" <<'PY'
import sys
open(sys.argv[1], 'w').write('\n'.join(f'export const unrelated{i} = {i};' for i in range(500)) + '\n')
PY
    git -C "$R" add . && git -C "$R" commit -qm "plan collision base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf 'export const value = 2;\n' > "$R/src/value.ts"
    replace_literal "$R/src/unrelated.ts" ' = ' ' = 10 + ' || return
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' src/value.ts src/unrelated.ts > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - keep value stable
Findings: F-001
Rule: Keep the value stable.
Sites: src/value.ts:1 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'value' .)
Test: tests/value.test.ts:1
EOF
    local hash; hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1p "${args[@]}" \
      > "$T/plan-name.out" 2> "$T/plan-name.err"
    assert_eq "root source cannot collide with the generated plan name" "$?" 2
    assert_grep "plan-name collision has a stable reason" "$T/plan-name.err" \
      'repository path collides with generated plan artifact: r1p-plan.md'
    assert_eq "plan-name collision publishes no label artifacts" \
      "$(find "$S" -maxdepth 1 -name 'r1p-*' | wc -l | tr -d ' ')" 0

    local manifest
    manifest=$(python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 2p "${args[@]}") || return
    assert_exit "a different generated plan name remains valid" 0 \
      python3 "$SCRIPTS/rev-evidence.py" verify "$manifest"

    python3 - "$S" <<'PY'
import hashlib, json, pathlib, sys
session = pathlib.Path(sys.argv[1])
for source in list(session.glob('r2p-*')):
    target = session / source.name.replace('r2p-', 'r1p-', 1)
    target.write_bytes(source.read_bytes().replace(b'r2p-', b'r1p-'))
path = session / 'r1p-evidence.manifest.json'
manifest = json.loads(path.read_text())
manifest['label'] = '1p'
for name, metadata in manifest['artifacts'].items():
    raw = (session / name).read_bytes()
    metadata.update(sha256=hashlib.sha256(raw).hexdigest(), words=len(raw.split()))
path.write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n')
PY
    assert_exit "legacy collision remains available to offline validation" 0 \
      python3 "$SCRIPTS/rev-evidence.py" render "$S/r1p-evidence.manifest.json" sol \
        --offline --plan-source "$S/r1p-plan.md"
    python3 "$SCRIPTS/rev-evidence.py" verify "$S/r1p-evidence.manifest.json" \
      > "$T/plan-name.out" 2> "$T/plan-name.err"
    assert_eq "fresh validation rejects a legacy bound-tree collision" "$?" 2
    assert_grep "fresh legacy collision has the same stable reason" "$T/plan-name.err" \
      'repository path collides with generated plan artifact: r1p-plan.md'
  )
}

test_plan_parser_handles_literal_searches_and_special_paths() {
  python3 - "$SCRIPTS/rev-evidence.py" "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, pathlib, shlex, sys
spec = importlib.util.spec_from_file_location('rev_evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
audit_spec = importlib.util.spec_from_file_location('read_audit', sys.argv[2])
audit = importlib.util.module_from_spec(audit_spec); audit_spec.loader.exec_module(audit)
raw = b'''## C-01 - build entry\nFindings: F-001\nRule: Keep the build target stable.\nSites: Makefile:1-2, :4-5; tests/value.test.ts:1-3 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'src/(value|fake)\\.ts' .)\nRegression: src/value.ts:1\n'''
clusters = module.parse_plan(raw, {'Makefile', 'tests/value.test.ts', 'src/value.ts'})
assert clusters[0]['search_pattern'] == r'src/(value|fake)\.ts'
assert clusters[0]['search_contract'] == {
    'engine':'rg', 'domain':'rg-complete-worktree', 'pattern':r'src/(value|fake)\.ts'}
assert [(row['path'], row['resolution']) for row in clusters[0]['paths']] == [
    ('Makefile', 'basename'), ('Makefile', 'basename'),
    ('tests/value.test.ts', 'direct'), ('src/value.ts', 'direct')]
assert [(row['line_start'], row['line_end']) for row in clusters[0]['paths']] == [
    (1, 2), (4, 5), (1, 3), (1, 1)]
numeric_search = b'''## C-02 - numeric search regex\nFindings: F-002\nRule: Keep numeric search patterns valid.\nSites: src/value.ts:1 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'value{2}|code80' .)\nTest: tests/value.test.ts:1\n'''
assert module.parse_plan(
    numeric_search, {'src/value.ts', 'tests/value.test.ts'})[0]['search_pattern'] == 'value{2}|code80'
assert module.plan_search_pattern("x (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- -legacy .)") == '-legacy'
assert audit.search_pattern(shlex.split("rg --hidden --no-ignore --glob '!.git/**' --null -n -- -legacy .")) == '-legacy'
assert audit.repository_search_pattern(
    'Bash', {'command':"rg --hidden --no-ignore --glob '!.git/**' --null -n -- -legacy . | head -81"}, pathlib.Path('/repo')) == {
        'engine':'rg', 'domain':'rg-complete-worktree', 'pattern':'-legacy'}
assert module.plan_search_pattern("x (found by: grep --exclude-dir=.git --null -r -n -- value .)") == 'value'
assert audit.repository_search_pattern(
    'Bash', {'command':'grep --exclude-dir=.git --null -r -n -- value . | head -81'}, pathlib.Path('/repo')) == {
        'engine':'grep-bre', 'domain':'grep-complete-worktree', 'pattern':'value'}
PY
  assert_eq "plan parser isolates parenthesized searches and resolves special basenames" "$?" 0
}

test_plan_parser_rejects_incomplete_and_escaping_clusters() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('rev_evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
entries = {'src/value.ts', 'tests/value.test.ts'}
bad = [
    b'''## C-01 - missing search\nFindings: F-001\nRule: Keep value stable.\nSites: src/value.ts:1\nTest: tests/value.test.ts:1\n''',
    b'''## C-01 - escaping path\nFindings: F-001\nRule: Keep value stable.\nSites: ../src/value.ts:1 (found by: rg -n value .)\nTest: tests/value.test.ts:1\n''',
    b'''## C-01 - reversed range\nFindings: F-001\nRule: Keep value stable.\nSites: src/value.ts:4-2 (found by: rg -n value .)\nTest: tests/value.test.ts:1\n''',
    b'''## C-01 - bare range after path\nFindings: F-001\nRule: Keep value stable.\nSites: src/value.ts:1, 4-6 (found by: rg -n value .)\nTest: tests/value.test.ts:1\n''',
    b'''## C-01 - bare range before path\nFindings: F-001\nRule: Keep value stable.\nSites: 4-6, src/value.ts:1 (found by: rg -n value .)\nTest: tests/value.test.ts:1\n''',
    b'''## C-01 - missing regression\nFindings: F-001\nRule: Keep value stable.\nSites: src/value.ts:1 (found by: rg -n value .)\n''',
]
sites_form = '; expected Sites: <path>[:<start>[-<end>]], ... (found by: <search>)'
messages = {
    b'escaping path': 'plan cluster C-01 field Sites: path escape "../src/value.ts:1"' + sites_form,
    b'reversed range': 'plan cluster C-01 field Sites: invalid line range "src/value.ts:4-2"' + sites_form,
    b'bare range after': 'plan cluster C-01 field Sites: unparsed line range "4-6"' + sites_form,
    b'bare range before': 'plan cluster C-01 field Sites: unparsed line range "4-6"' + sites_form,
}
for raw in bad:
    try:
        module.parse_plan(raw, entries)
    except ValueError as error:
        for name, message in messages.items():
            if name in raw:
                assert str(error) == message, str(error)
        continue
    raise AssertionError(raw.decode())
PY
  assert_eq "plan parser fails closed on incomplete and escaping clusters" "$?" 0
}

test_plan_parser_reads_locations_only_in_sites_and_test_path() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('rev_evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
entries = {'src/client.ts', 'tests/client.test.ts'}
search = " (found by: grep --exclude-dir=.git --null -r -n -- 'sync' .)"
def plan(rule, test, sites='src/client.ts:1', field='Test'):
    return (f'## C-07 - prose\nFindings: F-001\nRule: {rule}\nSites: {sites}{search}\n'
            f'Must not: retry after 600 ms or touch client.sync.\n{field}: {test}\n').encode()
prose = ['600', '3 s', 'client.sync', "onStage('submitting')/markSubmitting",
         'onStage(a)/b', 'try/catch', 'failure/cancellation']
for text in prose:
    for field in ('Test', 'Tests', 'Regression'):
        rows = module.parse_plan(plan(text, 'tests/client.test.ts:1 - ' + text + ' fails today', field=field),
                                 entries)[0]['paths']
        assert [(row['path'], row['line_start'], row['field']) for row in rows] == [
            ('src/client.ts', 1, 'sites'), ('tests/client.test.ts', 1, field.lower())], (text, rows)
combined = plan('wait 600 ms, then 3 s, for client.sync inside try/catch around onStage(a)/b.',
                'tests/client.test.ts - client.sync after 600 ms skips try/catch in onStage(a)/b.')
assert [row['path'] for row in module.parse_plan(combined, entries)[0]['paths']] == [
    'src/client.ts', 'tests/client.test.ts']
test_form = '; expected Test: <path> - <what fails today>'
sites_form = '; expected Sites: <path>[:<start>[-<end>]], ... (found by: <search>)'
refused = {
    plan('ok', 'manager - rejects a late call'):
        'plan cluster C-07 field Test: no resolvable path "manager"' + test_form,
    plan('ok', 'client.sync - rejects a late call'):
        'plan cluster C-07 field Test: missing basename in pinned snapshot "client.sync"' + test_form,
    plan('ok', 'tests/client.test.ts', sites='src/missing.ts:1'):
        'plan cluster C-07 field Sites: path does not exist in pinned snapshot "src/missing.ts"' + sites_form,
    plan('ok', 'tests/client.test.ts', sites='src/client.ts:1 inside try/catch'):
        'plan cluster C-07 field Sites: path does not exist in pinned snapshot "try/catch"' + sites_form,
    plan('ok', 'tests/client.test.ts', sites='src/client.ts:1 after 600 ms'):
        'plan cluster C-07 field Sites: unparsed line range "600"' + sites_form,
    plan('ok', 'tests/client.test.ts', sites="onStage('submitting')/markSubmitting"):
        'plan cluster C-07 field Sites: path escape "onStage(\'submitting\')/markSubmitting"' + sites_form,
}
for raw, message in refused.items():
    try:
        module.parse_plan(raw, entries)
    except ValueError as error:
        assert str(error) == message, str(error)
    else:
        raise AssertionError(raw.decode())
PY
  assert_eq "plan parser treats prose outside Sites and the leading test path as prose" "$?" 0
}

test_plan_search_parser_rejects_ambiguous_commands() {
  python3 - "$SCRIPTS/rev-evidence.py" "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, pathlib, random, sys
def load(name, path):
    spec=importlib.util.spec_from_file_location(name, path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
evidence=load('evidence',sys.argv[1]); audit=load('audit',sys.argv[2])
root=pathlib.Path('/repo')
def prepare_contract(command):
    return evidence.plan_search_contract('site (found by: '+command+')')
def audit_contract(command):
    return audit.repository_search_pattern(
        'Bash', {'command':command+' | head -81'}, root)
commands=[
    "rg -e one -e two .", "rg --ignore-file ignored pattern .", "rg -Z value pattern .",
    "rg -f patterns.txt bogus .", "rg --file=patterns.txt bogus .",
    "grep -n value .", "rg --glob '*.ts' value .", "rg -g '*.ts' value .",
    "rg --iglob '*.ts' value .", "rg --type ts value .", "rg -t ts value .",
    "rg --type-not test value .", "rg -T test value .", "rg --max-depth 2 value .",
    "grep -R --include '*.ts' value .", "grep -R --exclude '*.ts' value .",
    "grep -R --exclude-dir vendor value .", "rg --hidden value .", "rg --follow value .",
    "rg --max-filesize 1M value .", "grep -R --binary-files without-match value .",
    "grep -RI value .", "grep -R --threads 1 value .", "rg value src .",
    "rg --invert-match value .", "rg -v value .", "rg --files-without-match value .",
    "rg --fixed-strings value .", "rg -F value .", "rg --line-regexp value .",
    "rg -x value .", "rg --word-regexp value .", "rg -w value .",
    "grep -Rv value .", "grep -RF value .", "grep -Rx value .", "grep -Rw value .",
    "rg --count value .", "rg --count-matches value .", "rg --files-with-matches value .",
    "rg -l value .", "rg --only-matching value .", "rg -o value .",
    "rg --replace replacement value .", "rg -r replacement value .",
    "rg --ignore-case value .", "rg -i value .", "rg --smart-case value .",
    "rg --case-sensitive value .", "rg --multiline value .", "rg -U value .",
    "rg --pcre2 value .", "rg --crlf value .", "rg --engine pcre2 value .",
    "rg --encoding utf-8 value .", "rg --max-columns 120 value .",
    "grep -Ri value .", "grep -RE value .", "egrep -R value .", "fgrep -R value .",
    "rg --no-filename value .", "rg -I value .", "grep -R --no-filename value .",
    "grep -Rh value .", "rg -A 2 value .", "rg -B2 value .", "rg -C 2 value .",
    "rg --after-context 2 value .", "rg --before-context=2 value .",
    "rg --context 2 value .", "rg --heading value .", "./rg value .",
    "tools/grep -R value .", "/tmp/ripgrep value .", "ripgrep value .",
]
for command in commands:
    try:
        prepare_contract(command)
    except ValueError:
        pass
    else:
        raise AssertionError(command)
    assert audit_contract(command) is None, command
positive=["rg --hidden --no-ignore --glob '!.git/**' --null -n -- value .",
          "grep --exclude-dir=.git --null -r -n -- value .",
          "grep --exclude-dir=.git --null -rH -n -- value ."]
for command in positive:
    assert audit_contract(command) == prepare_contract(command), command
assert audit.repository_search_pattern(
    'Grep', {'pattern':'value','path':'.','head_limit':80}, pathlib.Path('/repo')) is None
assert audit.repository_search_pattern(
    'Grep', {'pattern':'value','path':'/repo','head_limit':80}, pathlib.Path('/repo')) is None
native={'pattern':'value','path':'.','head_limit':80}
for extra in ({'glob':'*.ts'},{'type':'ts'},{'offset':10},{'query':'other'},
              {'max_results':80},{'output_mode':'files_with_matches'}):
    assert audit.repository_search_pattern(
        'Grep', dict(native,**extra), pathlib.Path('/repo')) is None, extra
for invalid in (
    {'pattern':'value','path':'.'},
    {'pattern':'value','path':'.','head_limit':'80'},
    {'pattern':'value','path':'.','head_limit':True},
    {'pattern':'value','path':'.','head_limit':81},
):
    assert audit.repository_search_pattern('Grep', invalid, pathlib.Path('/repo')) is None, invalid
tokens=['-n','-i','--fixed-strings','--glob','*.ts','--max-depth','2','--hidden',
        '--ignore-file','ignored','-R','-r','value','.','src']
random.seed(812)
for _ in range(400):
    words=['grep' if random.randrange(2) else 'rg']
    words.extend(random.choice(tokens) for _ in range(random.randrange(1,7)))
    command=' '.join(words)
    try:
        expected=prepare_contract(command)
    except (ValueError,UnicodeError):
        expected=None
    assert audit_contract(command) == expected, (command,expected,audit_contract(command))
PY
  assert_eq "prepare and audit parsers reject ambiguous search commands identically" "$?" 0
}

test_plan_search_domain_covers_worktree_without_following_symlinks() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, os, pathlib, signal, subprocess, sys, tempfile, time
spec=importlib.util.spec_from_file_location('evidence',sys.argv[1])
evidence=importlib.util.module_from_spec(spec); spec.loader.exec_module(evidence)
with tempfile.TemporaryDirectory(prefix='plan-search-domain-') as tmp:
    parent=pathlib.Path(tmp); root=parent/'repo'; root.mkdir()
    for path in (root/'.hidden/match.txt', root/'ignored/match.txt', root/'visible.txt'):
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text('needle\n')
    (root/'.git').mkdir(); (root/'.git/config').write_text('needle\n')
    (root/'.gitignore').write_text('ignored/\n')
    outside=parent/'outside'; outside.mkdir(); (outside/'match.txt').write_text('needle\n')
    (root/'escape').symlink_to(outside,target_is_directory=True)
    contract={'engine':'rg','domain':'rg-complete-worktree','pattern':'needle'}
    assert evidence.plan_search_timeout({'REV_PLAN_SEARCH_TIMEOUT':'1'}) == 1
    assert evidence.plan_search_timeout({}) == 30
    for value in ('0','301','1.5','invalid'):
        try:
            evidence.plan_search_timeout({'REV_PLAN_SEARCH_TIMEOUT':value})
        except ValueError as error:
            assert str(error) == 'REV_PLAN_SEARCH_TIMEOUT must be an integer from 1 to 300'
        else:
            raise AssertionError('invalid plan search timeout accepted: '+value)
    command = [sys.executable, '-c',
               'import sys; sys.stdout.write("x\\n" * int(sys.argv[1]))']
    exact, status = evidence.run_plan_search(
        command + ['80'], root, dict(os.environ), time.monotonic() + 5)
    assert status == 0 and evidence.patch_display_lines(exact) == 80
    try:
        evidence.run_plan_search(
            command + ['81'], root, dict(os.environ), time.monotonic() + 5)
    except ValueError as error:
        assert str(error) == 'plan search output is saturated', error
    else:
        raise AssertionError('81 prepared search results were accepted')
    result=subprocess.run(evidence.plan_search_argv(contract),cwd=root,
                          capture_output=True,check=True)
    paths={row.split(b'\0',1)[0].decode().removeprefix('./')
           for row in result.stdout.splitlines() if b'\0' in row}
    assert {'.hidden/match.txt','ignored/match.txt','visible.txt'} <= paths, paths
    assert '.git/config' not in paths and not any(path.startswith('escape/') for path in paths), paths

    class UnionRepo:
        session=parent
        env=dict(os.environ)
        trees={
            'snapshot': {
                'type-swap/current.txt': 'needle current\n',
                'reverse-swap': 'needle current file\n',
            },
            'base': {
                'deleted.txt': 'needle deleted\n',
                'type-swap': 'needle old file\n',
                'reverse-swap/old.txt': 'needle old child\n',
            },
        }
        @classmethod
        def entries(cls, tree):
            return {path: ('100644', path) for path in cls.trees[tree]}
        @classmethod
        def materialize_regular(cls, tree, destination, paths=None):
            selected=cls.trees[tree]
            if paths is not None:
                selected={path: selected[path] for path in paths}
            for path, body in selected.items():
                target=destination/path; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(body)
    union_cluster={
        'id':'C-02', 'search_contract':contract,
        'paths':[{'path':'deleted.txt','field':'sites'},
                 {'path':'type-swap','field':'sites'},
                 {'path':'reverse-swap/old.txt','field':'sites'}],
    }
    prepared, artifacts=evidence.prepare_plan_searches(
        UnionRepo(), 'snapshot', [union_cluster], 'r1u', 'base')
    accepted={
        'deleted.txt', 'type-swap', 'reverse-swap/old.txt',
        'type-swap/current.txt', 'reverse-swap',
    }
    assert set(prepared[0]['search_proof']['paths']) == accepted, prepared
    assert evidence.plan_search_paths(artifacts['r1u-plan-search-C-02.txt']) == sorted(accepted)

    class SlowRepo:
        session=parent
        env=dict(os.environ)
        @staticmethod
        def materialize_regular(snapshot, destination):
            time.sleep(1.1)
            (destination/'site.txt').write_text('needle\n')
    slow_cluster={'id':'C-03','search_contract':contract,
                  'paths':[{'path':'site.txt','field':'sites'}]}
    old=os.environ.get('REV_PLAN_SEARCH_TIMEOUT')
    os.environ['REV_PLAN_SEARCH_TIMEOUT']='1'
    try:
        slow, _=evidence.prepare_plan_searches(SlowRepo(), 'snapshot', [slow_cluster], 'r1s')
    finally:
        if old is None: os.environ.pop('REV_PLAN_SEARCH_TIMEOUT',None)
        else: os.environ['REV_PLAN_SEARCH_TIMEOUT']=old
    assert slow[0]['search_proof']['paths'] == ['site.txt'], slow

    shared_shim=parent/'shared-bin'; shared_shim.mkdir()
    (shared_shim/'rg').write_text(
        '#!/bin/bash\n'
        'sleep 0.65\n'
        "printf './site.txt\\0001:needle\\n'\n")
    (shared_shim/'rg').chmod(0o755)
    class SharedRepo:
        session=parent
        env=dict(os.environ, PATH=str(shared_shim)+os.pathsep+os.environ.get('PATH',''))
        @staticmethod
        def materialize_regular(snapshot, destination):
            (destination/'site.txt').write_text('needle\n')
    shared_clusters=[
        {'id':'C-04','search_contract':contract,
         'paths':[{'path':'site.txt','field':'sites'}]},
        {'id':'C-05','search_contract':contract,
         'paths':[{'path':'site.txt','field':'sites'}]},
    ]
    old=os.environ.get('REV_PLAN_SEARCH_TIMEOUT')
    os.environ['REV_PLAN_SEARCH_TIMEOUT']='1'
    try:
        try:
            evidence.prepare_plan_searches(SharedRepo(), 'snapshot', shared_clusters, 'r1d')
        except ValueError as error:
            assert str(error) == 'plan search timed out', error
        else:
            raise AssertionError('each plan search received a fresh deadline')
    finally:
        if old is None: os.environ.pop('REV_PLAN_SEARCH_TIMEOUT',None)
        else: os.environ['REV_PLAN_SEARCH_TIMEOUT']=old

    shim=parent/'bin'; shim.mkdir(); pid_file=parent/'search-child.pid'
    (shim/'rg').write_text(
        '#!/bin/bash\n'
        'trap "" TERM\n'
        "python3 -c 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)' &\n"
        'echo $! > "$REV_SEARCH_CHILD_PID"\n'
        'while :; do sleep 1; done\n')
    (shim/'rg').chmod(0o755)
    class Repo:
        session=parent
        env=dict(os.environ, PATH=str(shim)+os.pathsep+os.environ.get('PATH',''),
                 REV_SEARCH_CHILD_PID=str(pid_file))
        @staticmethod
        def materialize_regular(snapshot, destination):
            (destination/'site.txt').write_text('needle\n')
    cluster={'id':'C-01','search_contract':contract,
             'paths':[{'path':'site.txt','field':'sites'}]}
    old=os.environ.get('REV_PLAN_SEARCH_TIMEOUT')
    os.environ['REV_PLAN_SEARCH_TIMEOUT']='1'
    started=time.monotonic()
    real_killpg=evidence.os.killpg
    denied={'raised':False}
    def deny_first_group_signal(group, chosen_signal):
        if chosen_signal != 0 and not denied['raised']:
            denied['raised']=True
            raise PermissionError('injected cleanup race')
        return real_killpg(group, chosen_signal)
    evidence.os.killpg=deny_first_group_signal
    try:
        try:
            evidence.prepare_plan_searches(Repo(), 'snapshot', [cluster], 'r1p')
        except ValueError as error:
            assert str(error) == 'plan search timed out', error
        else:
            raise AssertionError('hanging plan search returned')
    finally:
        evidence.os.killpg=real_killpg
        if old is None: os.environ.pop('REV_PLAN_SEARCH_TIMEOUT',None)
        else: os.environ['REV_PLAN_SEARCH_TIMEOUT']=old
    assert denied['raised'], 'permission race was not exercised'
    assert time.monotonic()-started < 5
    deadline=time.monotonic()+2
    while not pid_file.exists() and time.monotonic()<deadline: time.sleep(0.01)
    assert pid_file.exists()
    child=int(pid_file.read_text())
    while time.monotonic()<deadline:
        try: os.kill(child,0)
        except ProcessLookupError: break
        time.sleep(0.02)
    else:
        os.kill(child,signal.SIGKILL)
        raise AssertionError('plan search descendant survived timeout cleanup')

    cancel_pid_file=parent/'cancelled-search-child.pid'
    driver=parent/'cancel-driver.py'
    driver.write_text('''\
import importlib.util, os, pathlib, sys
spec=importlib.util.spec_from_file_location("evidence",sys.argv[1])
evidence=importlib.util.module_from_spec(spec); spec.loader.exec_module(evidence)
shim=pathlib.Path(sys.argv[2]); pid_file=pathlib.Path(sys.argv[3]); parent=pathlib.Path(sys.argv[4])
contract={"engine":"rg","domain":"rg-complete-worktree","pattern":"needle"}
class Repo:
    session=parent
    env=dict(os.environ, PATH=str(shim)+os.pathsep+os.environ.get("PATH",""),
             REV_SEARCH_CHILD_PID=str(pid_file))
    @staticmethod
    def materialize_regular(snapshot, destination):
        (destination/"site.txt").write_text("needle\\n")
cluster={"id":"C-01","search_contract":contract,
         "paths":[{"path":"site.txt","field":"sites"}]}
def prepare(_args):
    evidence.prepare_plan_searches(Repo(), "snapshot", [cluster], "r1p")
evidence.prepare=prepare
sys.argv=["rev-evidence.py","prepare",str(parent),"probe","--phase","plan"]
raise SystemExit(evidence.main())
''')
    cancelled=subprocess.Popen(
        [sys.executable,str(driver),sys.argv[1],str(shim),str(cancel_pid_file),str(parent)],
        env=dict(os.environ,REV_PLAN_SEARCH_TIMEOUT='30'),stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    cancel_deadline=time.monotonic()+3
    while not cancel_pid_file.exists() and time.monotonic()<cancel_deadline: time.sleep(0.01)
    assert cancel_pid_file.exists(), 'cancelled plan search did not start'
    cancelled.send_signal(signal.SIGTERM)
    assert cancelled.wait(timeout=5) == 128+signal.SIGTERM
    cancelled_child=int(cancel_pid_file.read_text())
    cleanup_deadline=time.monotonic()+2
    while time.monotonic()<cleanup_deadline:
        try: os.kill(cancelled_child,0)
        except ProcessLookupError: break
        time.sleep(0.02)
    else:
        os.kill(cancelled_child,signal.SIGKILL)
        raise AssertionError('plan search descendant survived host cancellation')

    race_pid_file=parent/'race-search-child.pid'
    race_driver=parent/'race-driver.py'
    race_driver.write_text('''\
import importlib.util, os, pathlib, signal, subprocess, sys, time
spec=importlib.util.spec_from_file_location("evidence",sys.argv[1])
evidence=importlib.util.module_from_spec(spec); spec.loader.exec_module(evidence)
shim=pathlib.Path(sys.argv[2]); pid_file=pathlib.Path(sys.argv[3]); parent=pathlib.Path(sys.argv[4])
real_popen=evidence.subprocess.Popen
def signal_before_return(*args, **kwargs):
    process=real_popen(*args, **kwargs)
    os.kill(os.getpid(), signal.SIGTERM)
    return process
evidence.subprocess.Popen=signal_before_return
environment=dict(os.environ,PATH=str(shim)+os.pathsep+os.environ.get("PATH",""),
                 REV_SEARCH_CHILD_PID=str(pid_file))
def prepare(_args):
    evidence.run_plan_search(["rg"],parent,environment,time.monotonic()+30)
evidence.prepare=prepare
sys.argv=["rev-evidence.py","prepare",str(parent),"probe","--phase","plan"]
raise SystemExit(evidence.main())
''')
    raced=subprocess.Popen(
        [sys.executable,str(race_driver),sys.argv[1],str(shim),str(race_pid_file),str(parent)],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert raced.wait(timeout=5) == 128+signal.SIGTERM
    race_deadline=time.monotonic()+2
    while not race_pid_file.exists() and time.monotonic()<race_deadline: time.sleep(0.01)
    assert race_pid_file.exists(), 'racing plan search child did not start'
    raced_child=int(race_pid_file.read_text())
    while time.monotonic()<race_deadline:
        try: os.kill(raced_child,0)
        except ProcessLookupError: break
        time.sleep(0.02)
    else:
        os.kill(raced_child,signal.SIGKILL)
        raise AssertionError('plan search descendant survived the Popen assignment signal race')
PY
  assert_eq "complete plan search covers the worktree and cleans descendants on timeout and host cancellation" "$?" 0
}

test_plan_topology_keeps_one_completeness_seat() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, types, sys
spec=importlib.util.spec_from_file_location('evidence',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
for count in (3,4,5,6):
    seats=[f'seat{i}' for i in range(count)]
    topology=module.canonical_bundle_topology(seats,module.PLAN_BUNDLES)
    args=types.SimpleNamespace(
        phase='plan', full_seat=seats[0],
        assignment=[seat+'='+topology[seat] for seat in seats])
    roster={'seats':[{'seat':seat,'adapter':'codex'} for seat in seats]}
    chosen, owner=module.assignments(args,roster)
    assert list(chosen)==seats and owner==seats[0]
    assert sum('plan-completeness' in bundles.split('+') for bundles in chosen.values())==1
    assert set(bundle for bundles in chosen.values() for bundle in bundles.split('+'))==set(module.PLAN_BUNDLES)
seats=['sol','terra','opus','sonnet']
roster={'seats':[{'seat':seat,'adapter':'codex'} for seat in seats]}
for seat in seats:
    for full_seat in (seat, None):
        args=types.SimpleNamespace(phase='plan', full_seat=full_seat,
                                   assignment=[seat+'=plan-completeness'])
        assert module.assignments(args,roster)==({seat:'plan-completeness'},seat)
    module.validate_assignment_topology({seat:'plan-completeness'},[seat],'plan')
expected=('plan assignment does not match canonical seat topology; expected '
          'sol=plan-completeness terra=plan-soundness opus=plan-simplicity sonnet=plan-tests '
          'or one <seat>=plan-completeness')
rejected=[
    ('sol',['sol=plan-soundness']),
    ('sol',['sol=plan-completeness+plan-tests']),
    ('sol',['sol=plan-completeness','terra=plan-soundness']),
    ('terra',['sol=plan-soundness','terra=plan-completeness','opus=plan-simplicity','sonnet=plan-tests']),
]
for full_seat, values in rejected:
    try:
        module.assignments(types.SimpleNamespace(phase='plan', full_seat=full_seat, assignment=values), roster)
    except ValueError as error:
        assert str(error)==expected, (values, str(error))
    else:
        raise AssertionError(values)
try:
    module.validate_assignment_topology({'sol':'plan-completeness','terra':'plan-tests'},['sol','terra'],'plan')
except ValueError as error:
    assert str(error).endswith('expected one <seat>=plan-completeness'), str(error)
else:
    raise AssertionError('two-seat plan topology accepted')
PY
  assert_eq "plan topologies keep completeness unique and accept one completeness seat" "$?" 0
}

test_plan_single_seat_panel_certifies() {
  ( local R="$T/plan-single-root" S="$T/plan-single-session"
    mkrepo "$R"; mkdir -p "$R/src" "$R/tests" "$S"
    printf 'export function helper() { return 1; }\n' > "$R/src/helper.ts"
    printf 'import { helper } from "./helper";\nexport function runService() { return helper(); }\n' > "$R/src/service.ts"
    printf 'import { runService } from "../src/service";\ntest("service", () => runService());\n' > "$R/tests/service.test.ts"
    git -C "$R" add . && git -C "$R" commit -qm "single plan base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    replace_literal "$R/src/helper.ts" 'return 1' 'return 2' || return
    replace_literal "$R/src/service.ts" 'helper();' 'helper() + 1;' || return
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' src/helper.ts src/service.ts > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - keep service results stable
Findings: F-001 (P1)
Rule: Wait 600 ms, then 3 s, before client.sync; keep try/catch around onStage('submitting')/markSubmitting.
Sites: src/service.ts:1-2, src/helper.ts:1 (found by: grep --exclude-dir=.git --null -r -n -- 'helper' .)
Must not: Change unrelated exports.
Test: tests/service.test.ts:1-2 - client.sync after 600 ms skips try/catch in onStage(a)/b (fails today).
EOF
    local hash manifest
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash")
    REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 0p \
      "${args[@]}" --full-seat sol --assignment sol=plan-soundness \
      > "$T/plan-single-lens.out" 2> "$T/plan-single-lens.err"
    assert_eq "one-seat plan with a non-completeness lens is refused" "$?" 2
    assert_grep "one-seat lens refusal prints the expected plan topology" "$T/plan-single-lens.err" \
      'expected sol=plan-completeness terra=plan-soundness opus=plan-simplicity sonnet=plan-tests or one <seat>=plan-completeness'
    manifest=$(REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1p \
      "${args[@]}" --full-seat sol --assignment sol=plan-completeness) || return
    python3 - "$manifest" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
assert list(m['assignments']) == ['sol'], m['assignments']
sol = m['assignments']['sol']
assert sol['scope'] == 'full' and sol['plan_clusters'] == ['C-01'] and sol['delta_clusters'] == []
assert m['mechanical_owner'] == 'sol' and m['components']
assert all(component['specialists'] == [] for component in m['components'])
assert sol['components'] == [component['id'] for component in m['components']]
assert m['source_context']['seats']['sol']['role'] == 'integration'
assert [row['token'] for row in m['plan']['clusters'][0]['paths']] == [
    'src/service.ts', 'src/helper.ts', 'tests/service.test.ts']
PY
    assert_eq "one-seat plan evidence routes every cluster to the completeness seat" "$?" 0
    local prompt
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1p sol plan-completeness plan \
      --plan "$S/r1p-plan.md" --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r1p-sol.json"
    printf '0\n' > "$S/r1p-sol.exit"
    python3 - "$manifest" "$S/r1p-sol.stream.ndjson" "$R" <<'PY'
import json, pathlib, sys
m = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2]); root = pathlib.Path(sys.argv[3])
session = pathlib.Path(sys.argv[1]).parent; assignment = m['assignments']['sol']; events = []
def call(identity, path, output, command=None):
    command = command or 'cat -- ' + str(path)
    events.extend([
        {'type':'item.started','item':{'id':identity,'type':'command_execution','command':command}},
        {'type':'item.completed','item':{'id':identity,'type':'command_execution','command':command,
                                         'aggregated_output':output,'exit_code':0}},
    ])
if assignment['patch_read_mode'] == 'chunks':
    for row in m['patch_sets'][assignment['patch_set']]['chunks']:
        path = session / row['artifact']; call('patch-' + str(row['index']), path, path.read_text())
else:
    patch = pathlib.Path(assignment['patch']); lines = patch.read_text().splitlines(keepends=True)
    for start in range(1, len(lines) + 1, 240):
        end = min(len(lines), start + 239)
        call('patch-' + str(start), patch, ''.join(lines[start - 1:end]),
             "sed -n '%d,%dp' %s" % (start, end, patch))
context = m['source_context']['seats']['sol']
for index, shard in enumerate(context['shards'], 1):
    path = session / shard['artifact']; call('packet-' + str(index), path, path.read_text())
for index, row in enumerate(context['required_source_ranges'], 1):
    for segment in row['segments']:
        path = session / segment['artifact']
        call('segment-%d-%d' % (index, segment['index']), path, path.read_text())
index = session / 'r1p-evidence.md'; call('evidence-index', index, index.read_text())
if context['source_read_required']:
    path = root / 'src/service.ts'
    call('source', path, ''.join(path.read_text().splitlines(keepends=True)[:2]),
         "sed -n '1,2p' " + str(path))
out.write_text(''.join(json.dumps(event) + '\n' for event in events))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r1p-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r1p-sol.read-audit.json" >/dev/null || return
    assert_exit "one-seat plan prompt authorizes exactly its manifest artifacts" 0 \
      python3 "$SCRIPTS/lib/review-read-audit.py" validate-prompt \
        --root "$R" --session "$S" --manifest "$manifest" --seat sol --prompt "$prompt"
    python3 "$SCRIPTS/rev-evidence.py" verify-panel "$S" 1p > "$T/plan-single-verify.out" \
      2> "$T/plan-single-verify.err"
    assert_eq "verify-panel certifies a one-seat plan panel" "$?" 0
    python3 - "$T/plan-single-verify.out" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
assert data['phase'] == 'plan'
assert sorted({name.split('.', 1)[0] for name in data['results']}) == ['r1p-sol'], data['results']
PY
    assert_eq "one-seat certification binds only the assigned seat's results" "$?" 0
    "$SCRIPTS/rev-profile.py" --json "$S" > "$T/plan-single-profile.json" || return
    python3 - "$T/plan-single-profile.json" <<'PY'
import json, sys
profile = json.load(open(sys.argv[1]))['sessions'][0]['scope_projection']
assert profile['valid_manifests'] == 1 and not profile['invalid_manifests'], profile
assert profile['plan_specialist_patch_words'] == 0, profile
PY
    assert_eq "profile reads a one-seat plan manifest" "$?" 0
  )
}

test_plan_source_capacity_compiles_to_bounded_reads() {
  ( local R="$T/plan-capacity-root" S="$T/plan-capacity-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for index in range(54):
    path = root / 'src' / f'site{index:02d}.py'
    path.write_text(f'capacity_marker_{index:02d} = 1\n' + ''.join(
        f'filler_{index:02d}_{line:03d} = "' + 'x' * 92 + '"\n'
        for line in range(199)))
PY
    git -C "$R" add . && git -C "$R" commit -qm "capacity base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    python3 - "$R" <<'PY'
from pathlib import Path
import sys
for path in (Path(sys.argv[1]) / 'src').glob('site*.py'):
    path.write_text(path.read_text().replace(' = 1\n', ' = 2\n', 1))
PY
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' "$R"/src/site*.py | sed "s#^$R/##" > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    python3 - "$S/fix-plan.md" <<'PY'
from pathlib import Path
import sys

clusters = []
for cluster in range(3):
    start = cluster * 18
    sites = [f'src/site{index:02d}.py:1-200' for index in range(start, start + 18)]
    clusters.append(
        f'## C-0{cluster + 1} - bounded mandatory reads {cluster + 1}\n'
        f'Findings: F-00{cluster + 1}\n'
        'Rule: Keep every capacity marker visible.\n'
        'Sites: ' + ', '.join(sites)
        + f" (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'capacity_marker_(0[0-9]|1[0-7])' .)\n".replace(
            'capacity_marker_(0[0-9]|1[0-7])',
            f'capacity_marker_({start:02d}|{start + 1:02d}|{start + 2:02d}|{start + 3:02d}|{start + 4:02d}|{start + 5:02d}|{start + 6:02d}|{start + 7:02d}|{start + 8:02d}|{start + 9:02d}|{start + 10:02d}|{start + 11:02d}|{start + 12:02d}|{start + 13:02d}|{start + 14:02d}|{start + 15:02d}|{start + 16:02d}|{start + 17:02d})')
        + f'Test: src/site{start:02d}.py:1\n')
Path(sys.argv[1]).write_text(''.join(clusters))
PY
    local hash manifest
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" capacity --phase plan \
      --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol \
      --assignment sol=plan-completeness --assignment terra=plan-soundness \
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests) || return
    python3 - "$manifest" <<'PY'
import json, sys

manifest = json.load(open(sys.argv[1]))
capacity = manifest['task_capacity']
assert capacity['repository_expansion_call_limit'] == 16
assert capacity['repository_refutation_call_reserve'] == 4
assert capacity['mandatory_repository_read_limit'] == 12
for seat, assignment in manifest['assignments'].items():
    context = manifest['source_context']['seats'][seat]
    delivered = [row for shard in context['shards'] for row in shard['ranges']]
    delivered += context['required_source_ranges']
    clusters = {row['id']: row for row in manifest['plan']['clusters']}
    mandatory = [source for cluster in assignment['plan_clusters']
                 for source in clusters[cluster]['paths']]
    direct = [source for source in mandatory if not any(
        row['path'] == source['path'] and row['line_start'] <= source['line_start']
        and row['line_end'] >= source['line_end'] for row in delivered)]
    assert len(direct) <= 12, (seat, len(direct))
    assert capacity['seats'][seat]['mandatory_repository_reads'] == len(direct)
    if assignment['adapter'] == 'claude':
        assert capacity['seats'][seat]['projected_turns'] <= 160
required = [row for packet in manifest['source_context']['seats'].values()
            for row in packet['required_source_ranges']]
assert required
assert all(segment['predicted_visible_bytes'] <= manifest['source_context']['max_shard_bytes']
           for row in required for segment in row['segments'])
PY
    assert_eq "mandatory plan reads compile under the reserved repository-call budget" "$?" 0
    assert_exit "capacity-compiled plan evidence validates before launch" 0 \
      python3 "$SCRIPTS/rev-evidence.py" verify "$manifest"
  )
}

test_plan_location_domain() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, sys

spec=importlib.util.spec_from_file_location('evidence',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
entries = {
    'README.md', 'src/value.ts', 'src/value.ts.generated',
    'src/nested value.ts', 'src/uber value.ts', 'src/über value.ts',
    'tests/unique.test.ts', 'one/shared.test.ts', 'two/shared.test.ts',
}
raw = b'''## C-01 - canonical locations
Findings: F-001
Rule: Keep every exact location stable.
Sites: src/value.ts.generated:2, `src/nested value.ts`:1-2, src/\xc3\xbcber value.ts:3, unique.test.ts:4, README.md:1 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'value' .)
Test: `src/uber value.ts:5-6`; src/value.ts:7 stays prose
'''
rows = module.parse_plan(raw, entries)[0]['paths']
assert [(row['path'], row['line_start'], row['line_end'], row['resolution']) for row in rows] == [
    ('src/value.ts.generated', 2, 2, 'direct'),
    ('src/nested value.ts', 1, 2, 'direct'),
    ('src/über value.ts', 3, 3, 'direct'),
    ('tests/unique.test.ts', 4, 4, 'basename'),
    ('README.md', 1, 1, 'basename'),
    ('src/uber value.ts', 5, 6, 'direct'),
], rows
try:
    module.plan_field_paths('prefixsrc/value.ts.generated.extra', entries)
except ValueError as error:
    assert str(error).endswith('"prefixsrc/value.ts.generated.extra"'), error
else:
    raise AssertionError('embedded path fragment unexpectedly resolved')

bad_fields = {
    'zero direct': 'src/value.ts:0',
    'zero direct range': 'src/value.ts:0-2',
    'zero shorthand': 'src/value.ts:1, :0-2',
    'reversed direct': 'src/value.ts:3-2',
    'reversed shorthand': 'src/value.ts:1, :3-2',
    'path escape': '../src/value.ts:1',
    'ambiguous basename': 'shared.test.ts:1',
}
for name, field in bad_fields.items():
    try:
        module.plan_field_paths(field, entries)
    except ValueError:
        continue
    raise AssertionError(name)
try:
    module.validate_plan_range(1, 1, 0, 'src/empty.ts')
except ValueError as error:
    assert str(error).endswith('"src/empty.ts"'), error
else:
    raise AssertionError('empty-file line unexpectedly resolved')
PY
  assert_eq "plan locations use exact snapshot paths and one-based ranges" "$?" 0
}

test_plan_location_range_revalidated_fresh() {
  ( local R="$T/plan-location-root" S="$T/plan-location-session"
    mkrepo "$R"; mkdir -p "$R/src" "$R/tests" "$S"
    printf 'export const value = 1;\n' > "$R/src/value.ts"
    : > "$R/src/empty.ts"
    printf 'test value\n' > "$R/tests/value.test.ts"
    python3 - "$R/src/unrelated.ts" <<'PY'
import sys
open(sys.argv[1], 'w').write('\n'.join(f'export const unrelated{i} = {i};' for i in range(400)) + '\n')
PY
    git -C "$R" add . && git -C "$R" commit -qm "plan location base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf 'export const value = 2;\n' > "$R/src/value.ts"
    replace_literal "$R/src/unrelated.ts" ' = ' ' = 10 + ' || return
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf '%s\n' src/value.ts src/unrelated.ts > "$S/files.txt"; : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - bounded location
Findings: F-001
Rule: Keep the value stable.
Sites: src/value.ts:2 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'value' .)
Test: tests/value.test.ts:1
EOF
    local hash; hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    python3 "$SCRIPTS/rev-evidence.py" prepare "$S" bad "${args[@]}" \
      > "$T/plan-location-prepare.out" 2> "$T/plan-location-prepare.err"
    assert_eq "past-EOF plan range fails before publication" "$?" 2
    assert_grep "past-EOF preparation reports the canonical range error" \
      "$T/plan-location-prepare.err" 'plan cluster C-01 field Sites: line range is outside pinned source "src/value\.ts:2"; expected Sites: '
    assert_eq "past-EOF preparation leaves no label artifacts" \
      "$(find "$S" -maxdepth 1 -name 'rbad-*' | wc -l | tr -d ' ')" 0

    replace_literal "$S/fix-plan.md" 'src/value.ts:2' 'src/empty.ts:1' || return
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    python3 "$SCRIPTS/rev-evidence.py" prepare "$S" empty "${args[@]}" \
      > "$T/plan-location-empty.out" 2> "$T/plan-location-empty.err"
    assert_eq "a location in an empty file fails before publication" "$?" 2
    assert_grep "empty-file location reports the canonical range error" \
      "$T/plan-location-empty.err" 'plan cluster C-01 field Sites: line range is outside pinned source "src/empty\.ts:1"; expected Sites: '
    assert_eq "empty-file location leaves no label artifacts" \
      "$(find "$S" -maxdepth 1 -name 'rempty-*' | wc -l | tr -d ' ')" 0

    replace_literal "$S/fix-plan.md" 'src/empty.ts:1' 'src/value.ts:1' || return
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    local manifest
    manifest=$(python3 "$SCRIPTS/rev-evidence.py" prepare "$S" fresh "${args[@]}") || return
    python3 - "$manifest" "$S/rfresh-evidence.json" "$S/fix-plan.md" "$S/rfresh-plan.md" <<'PY'
import hashlib, json, pathlib, sys

manifest_path, evidence_path, source_path, artifact_path = map(pathlib.Path, sys.argv[1:])
source = source_path.read_text().replace('src/value.ts:1', 'src/value.ts:2')
source_path.write_text(source); artifact_path.write_text(source)
source_raw = source.encode(); source_hash = hashlib.sha256(source_raw).hexdigest()
manifest = json.loads(manifest_path.read_text()); evidence = json.loads(evidence_path.read_text())
for document in (manifest, evidence):
    row = next(row for row in document['plan']['clusters'][0]['paths']
               if row['path'] == 'src/value.ts')
    row['line_start'] = row['line_end'] = 2
    document['plan'].update(source_sha256=source_hash, sha256=source_hash, bytes=len(source_raw))
manifest['artifacts'][artifact_path.name] = {'sha256': source_hash, 'words': len(source_raw.split())}
encode = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
evidence_raw = encode(evidence).encode(); evidence_path.write_bytes(evidence_raw)
manifest['artifacts'][evidence_path.name] = {
    'sha256': hashlib.sha256(evidence_raw).hexdigest(), 'words': len(evidence_raw.split())}
manifest_path.write_text(encode(manifest))
PY
    python3 "$SCRIPTS/rev-evidence.py" verify "$manifest" \
      > "$T/plan-location-verify.out" 2> "$T/plan-location-verify.err"
    assert_eq "fresh verification rechecks plan ranges against pinned source" "$?" 2
    assert_grep "fresh verification reports the canonical range error" \
      "$T/plan-location-verify.err" 'plan cluster C-01 field Sites: line range is outside pinned source "src/value\.ts:2"; expected Sites: '
  )
}
