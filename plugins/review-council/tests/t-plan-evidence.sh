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
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"codex"},{"seat":"opus","adapter":"codex"},{"seat":"opus-2","adapter":"codex"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - keep service results stable
Findings: F-001 (P1)
Rule: Apply the helper result exactly once at every service entry.
Sites: src/service.ts:1-2 (found by: rg --null -n 'run(Service|Alias)' .)
Must not: Change unrelated exports.
Test: tests/service.test.ts:1-2
Interacts with: none.
## C-02 - keep helper callers visible
Findings: F-002 (P1)
Rule: Check every helper caller before changing the helper result.
Sites: src/helper.ts:1 (found by: grep --null -R -n 'helper' .)
Must not: Skip callers outside the service entry.
Test: tests/service.test.ts:1-2
Interacts with: C-01.
EOF
    local plan_hash manifest
    plan_hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local assignments=(
      --assignment sol=plan-completeness
      --assignment grok=plan-soundness
      --assignment opus=plan-simplicity
      --assignment opus-2=plan-tests
    )
    manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1p --phase plan \
      --plan "$S/fix-plan.md" --plan-sha256 "$plan_hash" --full-seat sol \
      "${assignments[@]}") || return
    assert_exit "plan evidence prompt requires the bound plan argument" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 1p sol plan-completeness plan --evidence "$manifest"
    python3 - "$manifest" <<'PY'
import json, pathlib, sys
m = json.load(open(sys.argv[1])); session = pathlib.Path(sys.argv[1]).parent
assert m['schema_version'] == 3 and m['phase'] == 'plan'
assert m['mechanical_owner'] == 'sol' and m['assignments']['sol']['scope'] == 'full'
closures = [a for seat, a in m['assignments'].items() if seat != 'sol']
assert all(a['scope'] == 'closure' for a in closures)
assert len({a['patch_sha256'] for a in closures}) == 1
closure = (session / 'r1p-plan-closure.patch').read_text()
assert 'src/service.ts' in closure and 'src/helper.ts' in closure
assert 'tests/service.test.ts' in closure and 'src/unrelated.ts' not in closure
assert all(len(packet['shards']) <= 3 for packet in m['source_context']['seats'].values())
assert m['word_counts']['assigned_patch'] * 10 <= m['word_counts']['full'] * 4 * 9
assert m['word_counts']['plan'] > 0 and m['word_counts']['closure'] > 0
cluster = m['plan']['clusters'][0]
assert cluster['id'] == 'C-01' and cluster['search_pattern'] == 'run(Service|Alias)'
assert cluster['search_contract'] == {
    'engine':'rg','domain':'rg-default-worktree','pattern':'run(Service|Alias)'}
assert m['plan']['clusters'][1]['search_contract'] == {
    'engine':'grep-bre','domain':'grep-recursive-worktree','pattern':'helper'}
assert {row['path'] for row in cluster['paths']} == {'src/service.ts', 'tests/service.test.ts'}
PY
    assert_eq "plan evidence assigns one full seat and one common closure" "$?" 0

    local seat prompt lens
    for seat in sol grok opus opus-2; do
      case "$seat" in
        sol) lens=plan-completeness;;
        grok) lens=plan-soundness;;
        opus) lens=plan-simplicity;;
        *) lens=plan-tests;;
      esac
      prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1p "$seat" \
        "$lens" \
        plan --plan "$S/r1p-plan.md" --evidence "$manifest") || return
      assert_grep "$seat prompt contains the complete plan" "$prompt" '## C-01 - keep service results stable$'
      assert_grep "$seat prompt requires the cluster search" "$prompt" \
        '^Required cluster sibling search: C-01 engine rg domain rg-default-worktree pattern "run\(Service\|Alias\)" from repository root$'
      assert_grep "$seat prompt requires the grep cluster search" "$prompt" \
        '^Required cluster sibling search: C-02 engine grep-bre domain grep-recursive-worktree pattern "helper" from repository root$'
      assert_grep "$seat prompt renders the full plan source range" "$prompt" \
        '^Required cluster source: C-01 src/service.ts:1-2 resolution direct field sites$'
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
def call(identity, command, output):
    events.extend([
        {'type':'item.started','item':{'id':identity,'type':'command_execution','command':command}},
        {'type':'item.completed','item':{'id':identity,'type':'command_execution','command':command,
                                         'aggregated_output':output,'exit_code':0}},
    ])
assignment = m['assignments'][seat]; patch = pathlib.Path(assignment['patch'])
if assignment['patch_read_mode'] == 'chunks':
    for row in m['patch_sets'][assignment['patch_set']]['chunks']:
        path = session / row['artifact']; call('patch-' + str(row['index']), 'cat ' + str(path), path.read_text())
else:
    lines = patch.read_text().splitlines(keepends=True)
    for start in range(1, len(lines) + 1, 240):
        end = min(len(lines), start + 239)
        call('patch-' + str(start), "sed -n '%d,%dp' %s" % (start, end, patch), ''.join(lines[start - 1:end]))
context = m['source_context']['seats'][seat]
for index, shard in enumerate(context['shards'], 1):
    path = session / shard['artifact']; call('packet-' + str(index), 'cat ' + str(path), path.read_text())
if context['source_read_required']:
    path = root / 'src/service.ts'; call('source', "sed -n '1,2p' " + str(path), ''.join(path.read_text().splitlines(keepends=True)[:2]))
call('search-rg', "rg --null -n 'run(Service|Alias)' . | head -80", 'src/service.ts' + '\0' + '2:export function runService()\n' + 'src/sibling.ts' + '\0' + '1:export function runAlias() { return 1; }\n')
call('search-grep', "grep --null -R -n 'helper' . | head -80", 'src/helper.ts' + '\0' + '1:export function helper() { return 2; }\n')
out.write_text(''.join(json.dumps(event) + '\n' for event in events))
PY
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$S/r1p-$seat.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
        --out "$S/r1p-$seat.read-audit.json" >/dev/null || return
    done
    assert_exit "verify-panel starts without a coverage head" 1 test -e "$S/coverage-head.json"
    python3 "$SCRIPTS/rev-evidence.py" verify-panel "$S" 1p >/dev/null || return
    assert_exit "verify-panel does not write a coverage head" 1 test -e "$S/coverage-head.json"
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
PY
    assert_eq "profile reports plan closure and assigned-patch projections" "$?" 0
    assert_exit "plan panel cannot create a code coverage receipt" 2 \
      python3 "$SCRIPTS/rev-evidence.py" receipt "$S" 1p

    cp "$S/fix-plan.md" "$T/fix-plan.valid"
    printf '\nchanged\n' >> "$S/fix-plan.md"
    assert_exit "verify-panel rejects a changed source plan" 2 \
      python3 "$SCRIPTS/rev-evidence.py" verify-panel "$S" 1p
    cp "$T/fix-plan.valid" "$S/fix-plan.md"

    cp "$S/r1p-grok.stream.ndjson" "$T/grok.stream.valid"
    cp "$S/r1p-grok.read-audit.json" "$T/grok.audit.valid"
    python3 - "$S/r1p-grok.stream.ndjson" <<'PY'
import json, sys
p=sys.argv[1]; rows=[]
for line in open(p):
    row=json.loads(line)
    item=row.get('item') or {}
    if item.get('id') == 'search-rg':
        item['command']="cd src && rg --null -n 'run(Service|Alias)' . | head -80"
    rows.append(json.dumps(row))
open(p,'w').write('\n'.join(rows)+'\n')
PY
    assert_exit "subtree-relative search cannot prove a repository-root plan search" 2 \
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$S/r1p-grok.stream.ndjson" --prompt "$S/r1p-grok.prompt.md" \
        --root "$R" --session "$S" --out "$S/r1p-grok.read-audit.json"
    assert_grep "subtree-relative search has a stable missing-proof failure" \
      "$S/r1p-grok.read-audit.json" '"code":"missing-plan-cluster-search"'
    cp "$T/grok.stream.valid" "$S/r1p-grok.stream.ndjson"
    cp "$T/grok.audit.valid" "$S/r1p-grok.read-audit.json"

    local search_case=0 search_name search_id search_command search_output
    while IFS=$'\t' read -r search_name search_id search_command search_output; do
      search_case=$((search_case + 1))
      python3 - "$T/grok.stream.valid" "$S/r1p-grok.stream.ndjson" \
        "$search_id" "$search_command" "$search_output" <<'PY'
import json, sys
source, target, search_id, command, output = sys.argv[1:]
if output == '@80':
    output=''.join('src/service.ts\0%d:runService\n' % line for line in range(1,81))
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
          --raw "$S/r1p-grok.stream.ndjson" --prompt "$S/r1p-grok.prompt.md" \
          --root "$R" --session "$S" --out "$S/r1p-grok.read-audit.json"
      assert_grep "$search_name has a stable missing-proof failure" \
        "$S/r1p-grok.read-audit.json" '"code":"missing-plan-cluster-search"'
    done <<'CASES'
nonrecursive grep	search-rg	grep -n 'run(Service|Alias)' . | head -80	grep: .: Is a directory
pipeline-masked producer error	search-rg	grep --null -R -n 'run(Service|Alias)' . | head -80	grep: .: Is a directory
scope-narrowing rg glob	search-rg	rg --glob '*.ts' -n 'run(Service|Alias)' . | head -80	src/service.ts:2:export function runService()
scope-narrowing rg max depth	search-rg	rg --max-depth 1 -n 'run(Service|Alias)' . | head -80	src/service.ts:2:export function runService()
multiple root operands	search-rg	rg --null -n 'run(Service|Alias)' src . | head -80	src/service.ts@NUL@2:export function runService()
omitted sibling via invert match	search-rg	rg --invert-match -n 'run(Service|Alias)' . | head -80	src/helper.ts:1:export function helper()
mixed BRE engine with empty output	search-rg	grep --null -R -n 'run(Service|Alias)' . | head -80	@EMPTY@
rg no-filename long	search-rg	rg --no-filename -n 'run(Service|Alias)' . | head -80	src/service.ts:2:export function runService()
rg no-filename short	search-rg	rg -I -n 'run(Service|Alias)' . | head -80	src/service.ts:2:export function runService()
grep no-filename long	search-grep	grep -R --no-filename -n 'helper' . | head -80	export function helper()
grep no-filename short	search-grep	grep -Rh -n 'helper' . | head -80	export function helper()
context consumes cap before sibling	search-rg	rg --null -A 80 -n 'run(Service|Alias)' . | head -80	@80context
slash-qualified local rg	search-rg	./rg --null -n 'run(Service|Alias)' . | head -80	zsh: command not found: ./rg
slash-qualified grep	search-rg	tools/grep --null -R -n 'run(Service|Alias)' . | head -80	tools/grep: No such file or directory
absolute ripgrep alias	search-rg	/tmp/ripgrep -n 'run(Service|Alias)' . | head -80	/tmp/ripgrep: not found
cap-saturated exact matches	search-rg	rg --null -n 'run(Service|Alias)' . | head -80	@80
unknown grep diagnostic	search-grep	grep --null -R -n '\(' . | head -80	grep: parentheses not balanced
redirected search output	search-rg	rg --null -n 'run(Service|Alias)' . | head -80 >/dev/null	src/service.ts@NUL@2:runService
empty exact search	search-rg	rg --null -n 'run(Service|Alias)' . | head -80	@EMPTY@
colon filename cannot impersonate site	search-rg	rg --null -n 'run(Service|Alias)' . | head -80	src/service.ts:2:decoy@NUL@1:runService
CASES

    while IFS=$'\t' read -r search_name search_id search_command search_output; do
      python3 - "$T/grok.stream.valid" "$S/r1p-grok.stream.ndjson" \
        "$search_id" "$search_command" "$search_output" <<'PY'
import json, sys
source, target, search_id, command, output = sys.argv[1:]
if output == '@79':
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
          --raw "$S/r1p-grok.stream.ndjson" --prompt "$S/r1p-grok.prompt.md" \
          --root "$R" --session "$S" --out "$S/r1p-grok.read-audit.json"
    done <<'CASES'
default-worktree rg	search-rg	rg --null -n 'run(Service|Alias)' . | head -80	src/service.ts@NUL@2:runService
79 exact match lines	search-rg	rg --null -n 'run(Service|Alias)' . | head -80	@79
recursive grep -R	search-grep	grep --null -R -n 'helper' . | head -80	./src/helper.ts@NUL@1:helper
recursive grep -r	search-grep	grep --null -r -n 'helper' . | head -80	./src/helper.ts@NUL@1:helper
recursive grep with filename	search-grep	grep --null -RH -n 'helper' . | head -80	./src/helper.ts@NUL@1:helper
CASES
    cp "$T/grok.stream.valid" "$S/r1p-grok.stream.ndjson"
    cp "$T/grok.audit.valid" "$S/r1p-grok.read-audit.json"

    local native_name native_data native_exit
    while IFS=$'\t' read -r native_name native_exit native_data; do
      python3 - "$T/grok.stream.valid" "$S/r1p-grok.stream.ndjson" \
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
          --raw "$S/r1p-grok.stream.ndjson" --prompt "$S/r1p-grok.prompt.md" \
          --root "$R" --session "$S" --out "$S/r1p-grok.read-audit.json"
      if [ "$native_exit" != 0 ]; then
        assert_grep "$native_name native search has no cluster proof" \
          "$S/r1p-grok.read-audit.json" '"code":"missing-plan-cluster-search"'
      fi
    done <<'CASES'
exact	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80}
glob	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80,"glob":"*.ts"}
type	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80,"type":"ts"}
offset	2	{"pattern":"run(Service|Alias)","path":".","head_limit":80,"offset":10}
CASES
    cp "$T/grok.stream.valid" "$S/r1p-grok.stream.ndjson"
    cp "$T/grok.audit.valid" "$S/r1p-grok.read-audit.json"

    python3 - "$S/r1p-grok.read-audit.json" <<'PY'
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
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - ambiguous test
Findings: F-001
Rule: Keep value stable.
Sites: src/value.ts:1 (found by: rg --null -n 'value' .)
Test: value.test.ts:1
EOF
    local hash; hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment grok=plan-soundness
      --assignment opus=plan-simplicity --assignment opus-2=plan-tests)
    assert_exit "ambiguous basename rejects the whole adaptive plan attempt" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 2p "${args[@]}"
    assert_eq "failed plan preparation publishes no manifest" \
      "$(find "$S" -maxdepth 1 -name 'r2p-*' | wc -l | tr -d ' ')" 0
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"agent"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    assert_exit "agent seat selects legacy full plan scope" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 3p "${args[@]}"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    replace_literal "$S/fix-plan.md" 'Test: value.test.ts:1' 'Test: one/value.test.ts:1' || return
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local valid_args=(--phase plan --plan "$S/fix-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment grok=plan-soundness
      --assignment opus=plan-simplicity --assignment opus-2=plan-tests)
    assert_exit "stale plan hash rejects adaptive plan preparation" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 4p "${valid_args[@]/$hash/0000000000000000000000000000000000000000000000000000000000000000}"
    ln "$S/fix-plan.md" "$S/hardlinked-plan.md"
    valid_args=(--phase plan --plan "$S/hardlinked-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment grok=plan-soundness
      --assignment opus=plan-simplicity --assignment opus-2=plan-tests)
    assert_exit "hardlinked plan source rejects adaptive plan preparation" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 5p "${valid_args[@]}"
    rm "$S/hardlinked-plan.md"
    sed "s/rg --null -n 'value' \./rg --null -n -- -legacy ./" "$S/fix-plan.md" > "$S/legacy-pattern-plan.md"
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/legacy-pattern-plan.md")
    valid_args=(--phase plan --plan "$S/legacy-pattern-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment grok=plan-soundness
      --assignment opus=plan-simplicity --assignment opus-2=plan-tests)
    local legacy_manifest
    legacy_manifest=$(python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 6p "${valid_args[@]}") || return
    assert_grep "prepare preserves a leading-hyphen search expression" "$legacy_manifest" \
      '"search_pattern": "-legacy"'
    sed 's/rg --null -n -- -legacy \./rg --null -n -e one -e two ./' "$S/legacy-pattern-plan.md" > "$S/multiple-expression-plan.md"
    hash=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/multiple-expression-plan.md")
    valid_args=(--phase plan --plan "$S/multiple-expression-plan.md" --plan-sha256 "$hash" --full-seat sol
      --assignment sol=plan-completeness --assignment grok=plan-soundness
      --assignment opus=plan-simplicity --assignment opus-2=plan-tests)
    assert_exit "prepare rejects multiple search expressions" 2 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 7p "${valid_args[@]}"
  )
}

test_plan_parser_handles_literal_searches_and_special_paths() {
  python3 - "$SCRIPTS/rev-evidence.py" "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, pathlib, shlex, sys
spec = importlib.util.spec_from_file_location('rev_evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
audit_spec = importlib.util.spec_from_file_location('read_audit', sys.argv[2])
audit = importlib.util.module_from_spec(audit_spec); audit_spec.loader.exec_module(audit)
raw = b'''## C-01 - build entry\nFindings: F-001\nRule: Keep the build target stable.\nSites: Makefile:1-2, :4-5; tests/value.test.ts:1-3 (found by: rg --null -n 'src/(value|fake)\\.ts' .)\nRegression: src/value.ts:1\n'''
clusters = module.parse_plan(raw, {'Makefile', 'tests/value.test.ts', 'src/value.ts'})
assert clusters[0]['search_pattern'] == r'src/(value|fake)\.ts'
assert clusters[0]['search_contract'] == {
    'engine':'rg', 'domain':'rg-default-worktree', 'pattern':r'src/(value|fake)\.ts'}
assert [(row['path'], row['resolution']) for row in clusters[0]['paths']] == [
    ('Makefile', 'basename'), ('Makefile', 'basename'),
    ('tests/value.test.ts', 'direct'), ('src/value.ts', 'direct')]
assert [(row['line_start'], row['line_end']) for row in clusters[0]['paths']] == [
    (1, 2), (4, 5), (1, 3), (1, 1)]
assert module.plan_search_pattern("x (found by: rg --null -n -- -legacy .)") == '-legacy'
assert audit.search_pattern(shlex.split('rg --null -n -- -legacy .')) == '-legacy'
assert audit.repository_search_pattern(
    'Bash', {'command':'rg --null -n -- -legacy . | head -80'}, pathlib.Path('/repo')) == {
        'engine':'rg', 'domain':'rg-default-worktree', 'pattern':'-legacy'}
assert module.plan_search_pattern("x (found by: grep --null -R -n value .)") == 'value'
assert audit.repository_search_pattern(
    'Bash', {'command':'grep --null -R -n value . | head -80'}, pathlib.Path('/repo')) == {
        'engine':'grep-bre', 'domain':'grep-recursive-worktree', 'pattern':'value'}
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
    b'''## C-01 - missing regression\nFindings: F-001\nRule: Keep value stable.\nSites: src/value.ts:1 (found by: rg -n value .)\n''',
]
for raw in bad:
    try:
        module.parse_plan(raw, entries)
    except ValueError:
        continue
    raise AssertionError(raw.decode())
PY
  assert_eq "plan parser fails closed on incomplete and escaping clusters" "$?" 0
}

test_plan_search_parser_rejects_ambiguous_commands() {
  python3 - "$SCRIPTS/rev-evidence.py" "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import ast, importlib.util, inspect, pathlib, random, shlex, sys
def load(name, path):
    spec=importlib.util.spec_from_file_location(name, path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
evidence=load('evidence',sys.argv[1]); audit=load('audit',sys.argv[2])
assert ast.dump(ast.parse(inspect.getsource(evidence.strict_search_words))) == \
       ast.dump(ast.parse(inspect.getsource(audit.strict_search_words)))
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
        evidence.plan_search_pattern('site (found by: '+command+')')
    except ValueError:
        pass
    else:
        raise AssertionError(command)
    assert audit.search_pattern(shlex.split(command)) is None, command
positive=["rg --null -n value .", "grep --null -R -n value .",
          "grep --null -r -n value .", "grep --null -RH -n value ."]
for command in positive:
    expected=evidence.strict_search_words(shlex.split(command))
    assert audit.strict_search_words(shlex.split(command)) == expected, command
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
    command=['grep' if random.randrange(2) else 'rg']
    command.extend(random.choice(tokens) for _ in range(random.randrange(1,7)))
    outcomes=[]
    for parser in (evidence.strict_search_words,audit.strict_search_words):
        try:
            outcomes.append(('ok',parser(command)))
        except (ValueError,UnicodeError) as error:
            outcomes.append(('error',str(error)))
    assert outcomes[0] == outcomes[1], (command,outcomes)
PY
  assert_eq "prepare and audit parsers reject ambiguous search commands identically" "$?" 0
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
PY
  assert_eq "three through six seat plan topologies keep completeness unique" "$?" 0
}
