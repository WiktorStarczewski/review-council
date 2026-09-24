#!/bin/bash

test_prompt_artifact_set_validator() {
  ( local R="$T/prompt-set-root" S="$T/prompt-set-session"
    mkdir -p "$R" "$S"
    local prompt="$S/r1p-sonnet.prompt.md"
    cat > "$prompt" <<EOF
Canonical assigned patch: $S/r1p-sonnet.patch SHA-256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bytes 8
Assigned patch chunk 1/1: $S/r1p-patch-p01-001.txt bytes 0-8 SHA-256 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
Source context packet: $S/r1p-sonnet-source-context-1.json
Required source segment 1/1: use Read to read $S/r1p-sonnet-source-segment-001-001.txt in full raw bytes 8 visible bytes 8 content SHA-256 cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
Evidence navigation index: $S/r1p-evidence.md
EOF
    python3 - "$SCRIPTS/lib/review-read-audit.py" "$R" "$S" "$prompt" <<'PY'
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('review_read_audit', sys.argv[1])
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
root, session, prompt = map(Path, sys.argv[2:])
required = [
    'r1p-patch-p01-001.txt',
    'r1p-sonnet-source-context-1.json',
    'r1p-sonnet-source-segment-001-001.txt',
    'r1p-sonnet.patch',
]
manifest = {
    'schema_version': 4,
    'phase': 'plan',
    'session': str(session),
    'label': '1p',
    'plan': {'common_artifacts': ['r1p-evidence.md']},
    'assignments': {'sonnet': {'required_artifacts': required}},
}

audit.validate_prompt_artifact_set(manifest, 'sonnet', prompt, root, session)
original = prompt.read_text()
mutations = [
    original.replace('Source context packet:', 'Source packet:'),
    original + 'Exact frozen assigned patch: ' + str(session / 'r1p-full.patch') + '\n',
    original + 'Read the entire assigned patch in bounded windows of at most 240 lines: '
        + str(session / 'r1p-opus.patch') + '\n',
    original + 'Source context packet: '
        + str(session / 'r1p-opus-source-context-1.json') + '\n',
    original.replace('Evidence navigation index:', 'Navigation index:'),
]
for index, text in enumerate(mutations):
    candidate = session / ('candidate-' + str(index) + '.prompt.md')
    candidate.write_text(text)
    try:
        audit.validate_prompt_artifact_set(manifest, 'sonnet', candidate, root, session)
    except ValueError:
        continue
    raise AssertionError('malformed prompt artifact set was accepted: ' + str(index))
PY
    assert_eq "prompt compiler rejects missing and surplus artifact authorization" "$?" 0
  )
}

test_prompt_evidence_contract() {
  ( local ROOT="$T/prompt-evidence-repo" S="$T/prompt-evidence-session"
    mkrepo "$ROOT"
    mkdir -p "$S"
    printf 'changed\n' > "$ROOT/a.txt"
    printf '{}\n' > "$ROOT/package-lock.json"
    printf 'Root rule marker.\n' > "$ROOT/AGENTS.md"
    local base; base=$(git -C "$ROOT" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$ROOT" > "$S/scope.env"
    printf 'a.txt\npackage-lock.json\n' > "$S/files.txt"
    : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"

    local assignments=(
      --assignment sol=correctness-boundaries
      --assignment terra=security-state-api
      --assignment opus=concurrency-resources-performance
      --assignment sonnet=tests-observability-maintenance-regression
    )
    local manifest
    manifest=$(REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1 --phase risk "${assignments[@]}") || return

    local seat expected_bundle prompt fragment line
    for seat in sol terra opus sonnet; do
      case "$seat" in
        sol) expected_bundle=correctness-boundaries;;
        terra) expected_bundle=security-state-api;;
        opus) expected_bundle=concurrency-resources-performance;;
        sonnet) expected_bundle=tests-observability-maintenance-regression;;
      esac
      prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1 "$seat" "$expected_bundle" verification --evidence "$manifest") || return
      fragment=$(python3 "$SCRIPTS/rev-evidence.py" render "$manifest" "$seat") || return
      while IFS= read -r line; do
        grep -Fxq -- "$line" "$prompt" || fail "$seat prompt preserves evidence renderer output" "missing $line"
      done <<< "$fragment"
      assert_grep "$seat prompt names its exact risk bundle" "$prompt" "^Assigned risk bundle: $expected_bundle$"
      assert_grep "$seat embeds manifest-bound repository instructions" "$prompt" '^Root rule marker\.$'
      assert_grep "$seat prompt has bounded evidence steps" "$prompt" '^## Bounded evidence protocol$'
      assert_grep "$seat prompt reads its complete assigned patch" "$prompt" \
        'read every byte of the assigned patch.*window mode.*at most 240 lines'
      case "$seat" in
        sol)
          assert_grep "$seat prompt uses a portable shell window recipe" "$prompt" \
            "^First assigned-patch action: run .*sed -n '[0-9][0-9]*,[0-9][0-9]*p' .*r1-.*\\.patch"
          assert_nogrep "$seat prompt never asks Codex for a native read tool" "$prompt" \
            'First assigned-patch action:.*Read|First assigned-patch action:.*read_file'
          ;;
        terra)
          assert_grep "$seat prompt uses a portable shell window recipe" "$prompt" \
            "^First assigned-patch action: run .*sed -n '[0-9][0-9]*,[0-9][0-9]*p' .*r1-.*\\.patch"
          ;;
        opus)
          assert_grep "$seat prompt uses Claude Read" "$prompt" \
            '^First assigned-patch action: use Read with offset 1 and limit 240 '
          ;;
        sonnet)
          assert_grep "$seat prompt uses Claude Read" "$prompt" \
            '^First assigned-patch action: use Read with offset 1 and limit 240 '
          ;;
      esac
      assert_grep "$seat prompt forbids all pre-patch artifact reads" "$prompt" \
        '^First assigned-patch action:.*Do not read the evidence index, source context, or original source until the assigned patch is complete\.$'
      assert_nogrep "$seat prompt does not request the embedded instruction artifact" "$prompt" \
        'repository instructions: /.*-instructions\.md$'
      assert_grep "$seat prompt gives one explicit post-patch evidence order" "$prompt" \
        '^Post-patch evidence order: read every listed source-context packet and required source segment in exact order before the evidence index or original source\.$'
      assert_grep "$seat prompt limits source-context packets to one per turn" "$prompt" \
        '^Source context packet batch limit: 1$'
      case "$seat" in
        sol|terra)
          assert_grep "$seat prompt gives an exact first source-context action" "$prompt" \
            '^First source-context action: run cat -- .*source-context-1\.json as the only source-context packet read in this turn; continue with one listed packet per turn in exact order\.$'
          ;;
        opus|sonnet)
          assert_grep "$seat prompt gives an exact first source-context action" "$prompt" \
            '^First source-context action: use Read to read .*source-context-1\.json in full as the only source-context packet read in this turn; continue with one listed packet per turn in exact order\.$'
          ;;
      esac
      local packet_line index_line omitted_line
      packet_line=$(grep -n '^Source context packet:' "$prompt" | cut -d: -f1 | head -1)
      index_line=$(grep -n '^Evidence navigation index:' "$prompt" | cut -d: -f1 | head -1)
      omitted_line=$(grep -n '^Required post-index original-source target:' "$prompt" | cut -d: -f1 | head -1)
      if [ -n "$packet_line" ] && [ -n "$index_line" ] && [ "$packet_line" -lt "$index_line" ]; then
        ok "$seat prompt lists source context before the evidence index"
      else
        fail "$seat prompt lists source context before the evidence index" \
          "packet=$packet_line index=$index_line"
      fi
      if [ -z "$omitted_line" ] || { [ -n "$index_line" ] && [ "$index_line" -lt "$omitted_line" ]; }; then
        ok "$seat prompt lists required original-source expansion after the evidence index"
      else
        fail "$seat prompt lists required original-source expansion after the evidence index" \
          "index=$index_line omitted=$omitted_line"
      fi
      assert_nogrep "$seat prompt has no pre-index direct-read target" "$prompt" \
        '^Required omitted source direct-read target:'
      assert_nogrep "$seat prompt never asks for a live git diff" "$prompt" \
        'Produce the diff yourself|run `git diff|use `git diff'
      assert_grep "$seat prompt locates symbols before reading" "$prompt" 'Locate the enclosing symbol or named section'
      assert_grep "$seat prompt reads narrow windows" "$prompt" 'Read the smallest useful line window'
      assert_grep "$seat prompt recommends portable byte-preserving source reads" "$prompt" \
        "sed -n 'START,ENDp' 'FILE'"
      assert_nogrep "$seat prompt avoids BSD-incompatible sed separators" "$prompt" \
        "sed -n 'START,ENDp' -- FILE"
      assert_grep "$seat prompt rejects shell interpolation in search patterns" "$prompt" \
        'Never put backticks or command substitutions in shell search patterns'
      assert_grep "$seat prompt prohibits numbered source pipelines" "$prompt" \
        'Do not use `nl -ba \.\.\. \| sed`'
      assert_grep "$seat prompt expands only for a concrete question" "$prompt" 'concrete question that could prove or refute a finding'
      assert_grep "$seat prompt keeps the question out of the command" "$prompt" \
        'in your reasoning, never as a comment inside the command'
      assert_grep "$seat prompt warns that head bounds lines, not bytes" "$prompt" \
        '`head` limits lines, not bytes'
      assert_grep "$seat prompt forbids interpreters and inline scripts" "$prompt" \
        'Never run an interpreter or inline script \(`node`, `python3`, `bash -c`, `eval`\)'
      assert_grep "$seat prompt reports an execution-only claim instead of running code" "$prompt" \
        'say in the finding that it is unverified at runtime'
      assert_grep "$seat prompt states that a bad chunk read fails the review" "$prompt" \
        'A skipped, partial, repeated, or out-of-order chunk read fails your whole review'
      assert_grep "$seat prompt never counts another revision as source" "$prompt" \
        '`git show` of the base or any other revision is context only and never satisfies a required read or a citation'
      assert_grep "$seat prompt stops answered evidence paths" "$prompt" 'Stop that evidence path when the question is answered'
      assert_grep "$seat prompt treats packet excerpts as original source" "$prompt" \
        'source-context.*exact.*original source|exact original source.*source-context'
      assert_grep "$seat prompt limits full reads to exact prompt inputs" "$prompt" \
        'Only exact full-read artifacts and document inputs named in this prompt are exceptions'
      assert_grep "$seat prompt requires citation coverage" "$prompt" \
        'finding.*intersect.*packet.*opened.*source range'
      assert_grep "$seat prompt names an assigned source-context shard" "$prompt" \
        '^Source context packet: '
      assert_eq "$seat prompt does not duplicate repository instruction text" \
        "$(grep -c '^Root rule marker\.$' "$prompt")" 1
    done

    local LARGE_ROOT="$T/prompt-many-omissions-repo" LARGE_S="$T/prompt-many-omissions-session"
    mkrepo "$LARGE_ROOT"; mkdir -p "$LARGE_S"
    python3 - "$LARGE_ROOT/many.py" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_text(''.join(f'value_{index} = {index}\n' for index in range(300)))
PY
    local large_base; large_base=$(git -C "$LARGE_ROOT" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$large_base" "$LARGE_ROOT" > "$LARGE_S/scope.env"
    printf 'many.py\n' > "$LARGE_S/files.txt"
    printf 'many.py\n' > "$LARGE_S/untracked.txt"
    cp "$S/roster.json" "$LARGE_S/roster.json"
    local large_manifest large_seat large_bundle omitted_count target_line large_prompt large_words
    large_manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$LARGE_S" many --phase risk \
      "${assignments[@]}") || return
    read -r large_seat large_bundle omitted_count target_line < <(python3 - "$large_manifest" "$LARGE_ROOT" <<'PY'
import hashlib, json, pathlib, sys

manifest_path = pathlib.Path(sys.argv[1]); session = manifest_path.parent
manifest = json.loads(manifest_path.read_text())
evidence_path = session / 'rmany-evidence.json'
evidence = json.loads(evidence_path.read_text())
candidates = []
for seat, packet in manifest['source_context']['seats'].items():
    for shard in packet['shards']:
        for row in shard['ranges']:
            if row['path'] == 'many.py':
                candidates.append((seat, packet, row))
seat, packet, template = candidates[0]
lines = (pathlib.Path(sys.argv[2]) / 'many.py').read_bytes().splitlines(keepends=True)
used = [(row['line_start'], row['line_end']) for shard in packet['shards'] for row in shard['ranges']]
used += [(row['line_start'], row['line_end']) for row in packet['required_source_ranges']]
available = [line for line in range(1, len(lines) + 1)
             if not any(start <= line <= end for start, end in used)][:120]
assert len(available) == 120
priority = max(row['priority'] for shard in packet['shards'] for row in shard['ranges']) + 1
omitted = []
for offset, line in enumerate(available):
    row = dict(template, line_start=line, line_end=line, priority=priority + offset,
               content_sha256=hashlib.sha256(lines[line - 1]).hexdigest())
    omitted.append(row)
    for reason in row['reasons']:
        packet['omitted'][reason.split(':', 1)[0]] += 1
packet['omitted_source_ranges'] = omitted
for document in (manifest, evidence):
    document['source_context']['seats'][seat] = packet
encode = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
evidence_raw = encode(evidence).encode(); evidence_path.write_bytes(evidence_raw)
manifest['artifacts'][evidence_path.name] = {
    'sha256': hashlib.sha256(evidence_raw).hexdigest(), 'words': len(evidence_raw.split())}
manifest_path.write_text(encode(manifest))
print(seat, manifest['assignments'][seat]['bundle'], len(omitted), omitted[0]['line_start'])
PY
)
    if [ "$omitted_count" -ge 100 ]; then
      ok "large prompt fixture retains at least one hundred omitted source identities"
    else
      fail "large prompt fixture retains at least one hundred omitted source identities" \
        "count=$omitted_count"
    fi
    large_prompt=$("$SCRIPTS/rev-prompt.sh" "$LARGE_S" many "$large_seat" "$large_bundle" \
      verification --evidence "$large_manifest") || return
    assert_eq "large prompt renders one deterministic required post-index source target" \
      "$(grep -c '^Required post-index original-source target:' "$large_prompt")" 1
    assert_grep "large prompt chooses the highest-priority omitted source identity" \
      "$large_prompt" "^Required post-index original-source target: many\\.py:$target_line-$target_line "
    local large_index_line large_target_line
    large_index_line=$(grep -n '^Evidence navigation index:' "$large_prompt" | cut -d: -f1)
    large_target_line=$(grep -n '^Required post-index original-source target:' "$large_prompt" | cut -d: -f1)
    if [ "$large_index_line" -lt "$large_target_line" ]; then
      ok "large prompt puts required source expansion after the evidence index"
    else
      fail "large prompt puts required source expansion after the evidence index" \
        "index=$large_index_line target=$large_target_line"
    fi
    assert_nogrep "large prompt does not enumerate retained omitted source identities" \
      "$large_prompt" '^Omitted source range:'
    assert_grep "large prompt reports every additional retained omission without listing it" \
      "$large_prompt" "^Additional omitted source identities retained in manifest: $((omitted_count - 1))\\. Read them only for a concrete question that could prove or refute a finding\\.$"
    large_words=$(wc -w < "$large_prompt" | tr -d ' ')
    if [ "$large_words" -le 1800 ]; then
      ok "many omitted identities keep the code prompt within its word budget"
    else
      fail "many omitted identities keep the code prompt within its word budget" \
        "words=$large_words"
    fi

    python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import runpy, sys

read_batch_limit = runpy.run_path(sys.argv[1])['read_batch_limit']
assert read_batch_limit('claude') == 2
assert read_batch_limit('codex') == 1
assert read_batch_limit('gemini') == 1
assert runpy.run_path(sys.argv[1])['SOURCE_PACKET_BATCH_LIMIT'] == 1
PY
    assert_eq "patch and source limits share one adapter capability" "$?" 0

    local first="$S/r1-sol.prompt.md" frozen="$T/r1-sol.prompt.md"
    cp "$first" "$frozen"
    "$SCRIPTS/rev-prompt.sh" "$S" 1 sol correctness-boundaries verification --evidence "$manifest" >/dev/null || return
    assert_exit "evidence prompt rerender is byte-identical" 0 cmp -s "$frozen" "$first"

    local race_manifest real_python shim_dir
    race_manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 14 --phase risk "${assignments[@]}") || return
    real_python=$(command -v python3); shim_dir="$T/prompt-python-shim"; mkdir -p "$shim_dir"
    cat > "$shim_dir/python3" <<'SH'
#!/bin/bash
if [ "${1:-}" = "$REV_SWAP_EVIDENCE" ] && [ "${2:-}" = render ]; then
  count=0
  [ ! -f "$REV_SWAP_COUNT" ] || count=$(cat "$REV_SWAP_COUNT")
  count=$((count + 1)); printf '%s\n' "$count" > "$REV_SWAP_COUNT"
  if [ "$count" = 2 ]; then printf '\n' >> "$REV_SWAP_MANIFEST"; fi
fi
if [ "${1:-}" = "$REV_SWAP_EVIDENCE" ] && [ "${2:-}" = verify ]; then
  count=0
  [ ! -f "$REV_VERIFY_COUNT" ] || count=$(cat "$REV_VERIFY_COUNT")
  printf '%s\n' "$((count + 1))" > "$REV_VERIFY_COUNT"
fi
exec "$REV_REAL_PYTHON" "$@"
SH
    chmod +x "$shim_dir/python3"; : > "$T/prompt-render-count"; printf '0\n' > "$T/prompt-verify-count"
    PATH="$shim_dir:$PATH" REV_REAL_PYTHON="$real_python" \
      REV_SWAP_EVIDENCE="$SCRIPTS/rev-evidence.py" \
      REV_SWAP_COUNT="$T/prompt-render-count" REV_VERIFY_COUNT="$T/prompt-verify-count" \
      REV_SWAP_MANIFEST="$race_manifest" \
      "$SCRIPTS/rev-prompt.sh" "$S" 14 sol correctness-boundaries verification \
        --evidence "$race_manifest" > "$T/prompt-race.out" 2> "$T/prompt-race.err"
    assert_eq "same-label manifest swap during prompt render is rejected" "$?" 1
    assert_eq "publication revalidates with a second no-replay render" \
      "$(cat "$T/prompt-render-count")" 2
    assert_eq "prompt rendering never replays prepared searches" \
      "$(cat "$T/prompt-verify-count")" 0
    assert_exit "manifest swap publishes no stale prompt" 1 test -e "$S/r14-sol.prompt.md"
    assert_eq "manifest swap leaves no evidence fragment temporaries" \
      "$(find "$S" -maxdepth 1 -name '.rev-evidence-fragment.*' | wc -l | tr -d ' ')" 0

    assert_grep "Codex source batching defaults off" "$first" \
      '^Codex source batching enabled: false$'
    assert_nogrep "default Codex prompt does not invite source batching" "$first" \
      'one Bash call may contain semicolon-separated pure'
    local batch_prompt
    batch_prompt=$(REV_CODEX_SOURCE_BATCH=1 "$SCRIPTS/rev-prompt.sh" "$S" 1 sol \
      correctness-boundaries verification --evidence "$manifest") || return
    assert_grep "Codex source batching opt-in is frozen into the prompt" "$batch_prompt" \
      '^Codex source batching enabled: true$'
    assert_grep "opt-in Codex prompt permits only strict semicolon source batches" "$batch_prompt" \
      "Codex source batching:.*semicolon-separated.*sed -n 'START,ENDp' 'FILE'"
    assert_grep "opt-in Codex prompt caps total source-batch lines and bytes" "$batch_prompt" \
      'combined selected lines.*240.*combined visible output.*32 KiB'
    assert_grep "opt-in Codex prompt forbids overlap and mixed batch producers" "$batch_prompt" \
      'Do not overlap or duplicate windows.*mix.*searches.*metadata.*transforms'

    local disabled_manifest disabled_prompt
    disabled_manifest=$(REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=0 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 12 \
      --phase risk "${assignments[@]}") || return
    disabled_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 12 sol correctness-boundaries \
      verification --evidence "$disabled_manifest") || return
    assert_grep "paired baseline records disabled source context" "$disabled_prompt" \
      '^Source context enabled: false$'
    assert_nogrep "paired baseline emits no source-context packet" "$disabled_prompt" \
      '^Source context packet: '
    assert_grep "paired baseline requires direct source reads" "$disabled_prompt" \
      '^Source read required: true$'
    assert_grep "paired baseline keeps component-scoped assigned patch" "$disabled_prompt" \
      '^Read the entire assigned patch in bounded windows of at most 240 lines: '

    local default_manifest
    default_manifest=$(python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 13 \
      --phase risk "${assignments[@]}") || return
    python3 - "$default_manifest" "$S" <<'PY'
import json, pathlib, sys
m = json.load(open(sys.argv[1])); session = pathlib.Path(sys.argv[2])
assert m['patch_chunks_mode'] == 'auto'
assert m['patch_chunks_effective_mode'] == 'auto'
assert m['patch_chunks_enabled'] is True
assert m['source_context']['enabled'] is False
assert {row['patch_read_mode'] for row in m['assignments'].values()} == {'windows'}
assert not list(session.glob('r13-patch-p*.txt'))
assert not list(session.glob('r13-*-source-context-*.json'))
PY
    assert_eq "patch chunks default to auto while source context remains opt-in" "$?" 0

    local clean
    clean=$("$SCRIPTS/rev-prompt.sh" "$S" 1 sol clean-room design) || return
    local clean_rule protocol_rule
    clean_rule=$(grep -n 'Do NOT read the diff first' "$clean" | cut -d: -f1 | head -1)
    protocol_rule=$(grep -n '^## Bounded evidence protocol$' "$clean" | cut -d: -f1)
    if [ -n "$clean_rule" ] && [ -n "$protocol_rule" ] && [ "$clean_rule" -lt "$protocol_rule" ]; then
      ok "clean-room design comes before bounded evidence reads"
    else
      fail "clean-room design comes before bounded evidence reads" "clean=$clean_rule protocol=$protocol_rule"
    fi
    clean=$("$SCRIPTS/rev-prompt.sh" "$S" 1 terra clean-room design) || return
    assert_nogrep "Terra clean-room prompt does not order an immediate diff read" "$clean" 'FIRST run your tools: read the diff'

    printf '1. Verify the caller.\n' > "$S/fix-plan.md"
    assert_exit "plan prompt rejects a non-plan evidence manifest" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 1 terra plan-tests plan \
      --plan "$S/fix-plan.md" --evidence "$manifest"
    "$SCRIPTS/rev-prompt.sh" "$S" 1 terra security-state-api verification \
      --evidence "$manifest" >/dev/null || return

    local legacy session_real
    session_real=$(cd "$S" && pwd -P)
    legacy=$("$SCRIPTS/rev-prompt.sh" "$S" 8 sol regression numeric) || return
    assert_grep "legacy prompt names its exact frozen patch" "$legacy" \
      "^Exact frozen assigned patch: $session_real/r8-full\\.patch$"
    assert_grep "legacy Codex prompt makes a portable patch read the first evidence action" "$legacy" \
      '^First evidence action after any required clean-room design: run portable bounded sed windows over '
    local legacy_agent
    printf '%s\n' '{"seats":[{"seat":"opus","adapter":"agent"}]}' > "$S/roster.json"
    legacy_agent=$("$SCRIPTS/rev-prompt.sh" "$S" 8 opus regression numeric) || return
    assert_grep "legacy Agent prompt uses the Claude Read tool" "$legacy_agent" \
      '^First evidence action after any required clean-room design: use Read to read the exact frozen assigned patch '
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    assert_nogrep "legacy prompt never asks for a live git diff" "$legacy" \
      'Produce the diff yourself|run `git diff|use `git diff'
    assert_grep "legacy frozen patch includes tracked worktree changes" "$S/r8-full.patch" \
      '^diff --git a/a\.txt b/a\.txt$'
    assert_grep "legacy frozen patch includes untracked changes" "$S/r8-full.patch" \
      '^diff --git a/package-lock\.json b/package-lock\.json$'
    assert_grep "legacy frozen patch keeps untracked contents" "$S/r8-full.patch" '^\+\{\}$'
    cp "$S/r8-full.patch" "$T/r8-full.frozen"
    printf 'changed after freeze\n' > "$ROOT/a.txt"
    local legacy_peer
    legacy_peer=$("$SCRIPTS/rev-prompt.sh" "$S" 8 terra security-state-api numeric) || return
    assert_exit "same-label legacy seats reuse one byte-stable frozen patch" 0 \
      cmp -s "$T/r8-full.frozen" "$S/r8-full.patch"
    assert_grep "peer legacy prompt names the shared frozen patch" "$legacy_peer" \
      "^Exact frozen assigned patch: $session_real/r8-full\\.patch$"
    printf 'changed\n' > "$ROOT/a.txt"
    assert_eq "legacy patch generation leaves no patch temporary" \
      "$(find "$S" -maxdepth 1 -name '.rev-patch.*' | wc -l | tr -d ' ')" 0
    assert_eq "legacy patch generation leaves no temporary index" \
      "$(find "$S" -maxdepth 1 -name '.evidence-index-*' | wc -l | tr -d ' ')" 0

    cp "$S/scope.env" "$T/scope-valid.env"
    sed "s#REV_SCOPE='branch'#REV_SCOPE='../../outside'#" "$T/scope-valid.env" > "$S/scope.env"
    "$SCRIPTS/rev-prompt.sh" "$S" 83 sol regression invalid-path \
      > "$T/prompt-patch-invalid.out" 2> "$T/prompt-patch-invalid.err"
    local patch_rc=$?
    if [ "$patch_rc" -ne 0 ]; then
      ok "failed legacy patch capture is rejected"
    else
      fail "failed legacy patch capture is rejected" "exit $patch_rc"
    fi
    assert_exit "failed legacy patch capture publishes no partial artifact" 1 \
      test -e "$S/r83-full.patch"
    assert_eq "failed legacy patch capture removes temporaries" \
      "$(find "$S" -maxdepth 1 \( -name '.rev-patch.*' -o -name '.evidence-index-*' \) | wc -l | tr -d ' ')" 0
    cp "$T/scope-valid.env" "$S/scope.env"
    assert_nogrep "absent evidence has no manifest claim" "$legacy" '^Evidence manifest SHA-256:'
    assert_grep "numeric code prompt still uses bounded reads" "$legacy" '^## Bounded evidence protocol$'

    printf 'OUTSIDE_SENTINEL\n' > "$T/prompt-outside.txt"
    ln -s "$T/prompt-outside.txt" "$ROOT/link.py"
    printf 'link.py\n' > "$S/files.txt"
    local symlink_prompt
    symlink_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 81 sol regression symlink) || return
    assert_grep "external file symlink keeps frozen-patch rendering" "$symlink_prompt" '^Exact frozen assigned patch:'
    assert_nogrep "external file symlink does not read its target" "$symlink_prompt" 'OUTSIDE_SENTINEL'

    mkdir -p "$T/prompt-outside-dir"
    printf 'OUTSIDE_DIRECTORY_SENTINEL\n' > "$T/prompt-outside-dir/item.py"
    ln -s "$T/prompt-outside-dir" "$ROOT/linked-dir"
    printf 'linked-dir/item.py\n' > "$S/files.txt"
    symlink_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 82 sol regression symlink-dir) || return
    assert_grep "external directory symlink keeps frozen-patch rendering" "$symlink_prompt" '^Exact frozen assigned patch:'
    assert_nogrep "external directory symlink does not read its target" "$symlink_prompt" 'OUTSIDE_DIRECTORY_SENTINEL'
    printf 'a.txt\npackage-lock.json\n' > "$S/files.txt"

    local composite sol_prefix terra_prefix opus_prefix
    composite=$("$SCRIPTS/rev-prompt.sh" "$S" 8 sol \
      correctness-boundaries+security-state-api composite) || return
    assert_grep "composite lens keeps correctness instructions" "$composite" \
      '^Check logic, boundary inputs, partial failure, cleanup, and error contracts\.'
    assert_grep "composite lens keeps security instructions" "$composite" \
      '^Check trust boundaries, authorization, durable-state invariants, serialization, idempotency, compatibility, and public API behavior\.'

    python3 - "$first" "$clean" "$composite" "$T" <<'PY'
from pathlib import Path
import sys
for source, name in zip(sys.argv[1:4], ('sol', 'terra', 'composite')):
    text = Path(source).read_text()
    assert text.startswith('# Reviewer contract\n')
    prefix, marker, _ = text.partition('\n## Review assignment\n')
    assert marker
    Path(sys.argv[4], name + '.prefix').write_text(prefix + '\n')
PY
    sol_prefix="$T/sol.prefix"; terra_prefix="$T/terra.prefix"; opus_prefix="$T/composite.prefix"
    assert_exit "invariant prefix is byte-stable across seat and lens" 0 cmp -s "$sol_prefix" "$terra_prefix"
    assert_exit "invariant prefix is byte-stable for composite bundles" 0 cmp -s "$sol_prefix" "$opus_prefix"
    assert_grep "stable prefix carries clean-room ordering" "$sol_prefix" 'clean-room lens, write the smallest design before any patch or source read'
    assert_grep "stable prefix carries exact Read bound" "$sol_prefix" 'offset.*limit.*240'
    assert_grep "stable prefix carries exact search bound" "$sol_prefix" 'result limit.*80'
    assert_grep "stable prefix carries the shell overflow sentinel" "$sol_prefix" \
      '\| head -81.*81st line invalidates the audit'
    assert_grep "stable prefix carries per-turn byte bound" "$sol_prefix" '32 KiB combined output ceiling'
    assert_grep "stable prefix carries ordered proof turn bound" "$sol_prefix" \
      'at most the rendered proof read limit.*60 KiB combined output ceiling'
    assert_grep "stable prefix keeps source packets on the ordinary cap" "$sol_prefix" \
      'Source-context packets and repository reads keep the ordinary 32 KiB turn ceiling'
    assert_grep "stable prefix asks for batched independent tool calls" "$sol_prefix" 'Batch independent bounded tool calls into one turn'
    assert_grep "stable prefix defines inclusive shell window arithmetic" "$sol_prefix" \
      'END - START \+ 1 <= 240'
    assert_grep "stable prefix rejects per-file search caps as global bounds" "$sol_prefix" \
      'rg --max-count.*per file'
    assert_grep "stable prefix keeps one-producer behavior as the default" "$sol_prefix" \
      'each shell tool call to one producer pipeline'
    assert_grep "stable prefix forbids mixed search and source output" "$sol_prefix" \
      'Never mix source reads and searches in one shell call'
    assert_grep "stable prefix reserves the required structured result" "$sol_prefix" \
      'reserve capacity to return the required JSON'
    assert_grep "stable prefix reserves a bounded post-proof completion window" "$sol_prefix" \
      'use at most 16 repository tool calls.*no new evidence path after call 12'
    assert_grep "stable prefix marks unfinished proof without another tool call" "$sol_prefix" \
      'summary.*INCOMPLETE PROOF:.*unfinished obligations'
    assert_nogrep "Terra prompt keeps source batching disabled" "$clean" \
      'Codex source batching:'
    assert_grep "patch chunks use the rendered per-turn batch limit" "$first" \
      'rendered patch chunk batch limit'
    assert_nogrep "volatile repository path stays after prefix" "$sol_prefix" "$ROOT"

    printf 'Root rule marker.\n' > "$ROOT/AGENTS.md"
    local with_rules
    with_rules=$("$SCRIPTS/rev-prompt.sh" "$S" 11 sol correctness rules) || return
    assert_grep "applicable repo rules are embedded" "$with_rules" '^Root rule marker\.$'
    assert_grep "repo rules section is after stable prefix" "$with_rules" '^## Applicable repository instructions$'

    printf '%s\n' "$S/fix-plan.md" > "$S/documents.txt"
    local docs
    docs=$("$SCRIPTS/rev-prompt.sh" "$S" 9 sol correctness documents --read-only "$S/documents.txt") || return
    assert_grep "document review still requires full reads" "$docs" 'Documents to review \(read them in full\):'
    assert_nogrep "document review does not use hunk protocol" "$docs" '^## Bounded evidence protocol$'
    "$SCRIPTS/rev-prompt.sh" "$S" 1 sol correctness documents --read-only "$S/documents.txt" --evidence "$manifest" \
      > "$T/prompt-evidence-docs.out" 2> "$T/prompt-evidence-docs.err"
    local rc=$?
    if [ "$rc" -ne 0 ]; then
      ok "document review rejects an inapplicable evidence manifest"
    else
      fail "document review rejects an inapplicable evidence manifest" "exit $rc"
    fi
    assert_exit "document evidence mismatch leaves no prompt" 1 test -e "$S/r1-sol.prompt.md"

    printf 'stale prompt\n' > "$S/r2-sol.prompt.md"
    "$SCRIPTS/rev-prompt.sh" "$S" 2 sol correctness wrong-label --evidence "$manifest" \
      > "$T/prompt-evidence-label.out" 2> "$T/prompt-evidence-label.err"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      ok "evidence label must match the prompt label"
    else
      fail "evidence label must match the prompt label" "exit $rc"
    fi
    assert_exit "wrong-label evidence removes stale prompt" 1 test -e "$S/r2-sol.prompt.md"

    local manifest10
    manifest10=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 10 --phase risk "${assignments[@]}") || return
    printf 'newer worktree state\n' > "$ROOT/a.txt"
    printf 'stale prompt\n' > "$S/r10-sol.prompt.md"
    "$SCRIPTS/rev-prompt.sh" "$S" 10 sol correctness invalid --evidence "$manifest10" \
      > "$T/prompt-evidence-invalid.out" 2> "$T/prompt-evidence-invalid.err"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      ok "stale evidence is rejected"
    else
      fail "stale evidence is rejected" "exit $rc"
    fi
    assert_eq "invalid evidence prints no prompt path" "$(cat "$T/prompt-evidence-invalid.out")" ""
    assert_exit "invalid evidence removes stale prompt" 1 test -e "$S/r10-sol.prompt.md"
    assert_eq "invalid evidence leaves no prompt temporaries" \
      "$(find "$S" -maxdepth 1 -name '.rev-prompt.*' | wc -l | tr -d ' ')" 0
    assert_eq "invalid evidence leaves no fragment temporaries" \
      "$(find "$S" -maxdepth 1 -name '.rev-evidence-fragment.*' | wc -l | tr -d ' ')" 0
  )
}
