#!/bin/bash

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
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"gemini"}]}' > "$S/roster.json"

    local assignments=(
      --assignment sol=correctness-boundaries
      --assignment grok=security-state-api
      --assignment opus=concurrency-resources-performance
      --assignment opus-2=tests-observability-maintenance-regression
    )
    local manifest
    manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 1 --phase risk "${assignments[@]}") || return

    local seat expected_bundle prompt fragment line
    for seat in sol grok opus opus-2; do
      case "$seat" in
        sol) expected_bundle=correctness-boundaries;;
        grok) expected_bundle=security-state-api;;
        opus) expected_bundle=concurrency-resources-performance;;
        opus-2) expected_bundle=tests-observability-maintenance-regression;;
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
        grok)
          assert_grep "$seat prompt uses Grok read_file" "$prompt" \
            '^First assigned-patch action: use read_file with offset 1 and limit 240 '
          ;;
        opus)
          assert_grep "$seat prompt uses Claude Read" "$prompt" \
            '^First assigned-patch action: use Read with offset 1 and limit 240 '
          ;;
        opus-2)
          assert_grep "$seat prompt uses Gemini read_file" "$prompt" \
            '^First assigned-patch action: use read_file with offset 1 and limit 240 '
          ;;
      esac
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
      assert_grep "$seat prompt stops answered evidence paths" "$prompt" 'Stop that evidence path when the question is answered'
      assert_grep "$seat prompt treats packet excerpts as original source" "$prompt" \
        'source-context.*exact.*original source|exact original source.*source-context'
      assert_grep "$seat prompt names packets as bounded-read exceptions" "$prompt" \
        'compact evidence index, assigned patch chunks, and listed source-context packets are the only full-read exceptions'
      assert_grep "$seat prompt requires citation coverage" "$prompt" \
        'finding.*intersect.*packet.*opened.*source range'
      assert_grep "$seat prompt names an assigned source-context shard" "$prompt" \
        '^Source context packet: '
      assert_eq "$seat prompt does not duplicate repository instruction text" \
        "$(grep -c '^Root rule marker\.$' "$prompt")" 1
    done

    local first="$S/r1-sol.prompt.md" frozen="$T/r1-sol.prompt.md"
    cp "$first" "$frozen"
    "$SCRIPTS/rev-prompt.sh" "$S" 1 sol correctness-boundaries verification --evidence "$manifest" >/dev/null || return
    assert_exit "evidence prompt rerender is byte-identical" 0 cmp -s "$frozen" "$first"

    local disabled_manifest disabled_prompt
    disabled_manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=0 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 12 \
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
assert m['patch_chunks_enabled'] is False
assert m['source_context']['enabled'] is False
assert {row['patch_read_mode'] for row in m['assignments'].values()} == {'windows'}
assert not list(session.glob('r13-patch-p*.txt'))
assert not list(session.glob('r13-*-source-context-*.json'))
PY
    assert_eq "evidence features default off before held-out adoption" "$?" 0

    local clean
    clean=$("$SCRIPTS/rev-prompt.sh" "$S" 1 sol clean-room design --evidence "$manifest") || return
    local clean_rule protocol_rule
    clean_rule=$(grep -n 'Do NOT read the diff first' "$clean" | cut -d: -f1 | head -1)
    protocol_rule=$(grep -n '^## Bounded evidence protocol$' "$clean" | cut -d: -f1)
    if [ -n "$clean_rule" ] && [ -n "$protocol_rule" ] && [ "$clean_rule" -lt "$protocol_rule" ]; then
      ok "clean-room design comes before bounded evidence reads"
    else
      fail "clean-room design comes before bounded evidence reads" "clean=$clean_rule protocol=$protocol_rule"
    fi
    clean=$("$SCRIPTS/rev-prompt.sh" "$S" 1 grok clean-room design --evidence "$manifest") || return
    assert_nogrep "Grok clean-room prompt does not order an immediate diff read" "$clean" 'FIRST run your tools: read the diff'
    assert_grep "Grok follows lens ordering before tool reads" "$clean" 'Follow the lens ordering below before using tools'

    printf '1. Verify the caller.\n' > "$S/fix-plan.md"
    assert_exit "plan prompt rejects a non-plan evidence manifest" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 1 grok plan-tests plan \
      --plan "$S/fix-plan.md" --evidence "$manifest"
    "$SCRIPTS/rev-prompt.sh" "$S" 1 grok security-state-api verification \
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
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"gemini"}]}' > "$S/roster.json"
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
    legacy_peer=$("$SCRIPTS/rev-prompt.sh" "$S" 8 grok security-state-api numeric) || return
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

    local composite sol_prefix grok_prefix opus_prefix
    composite=$("$SCRIPTS/rev-prompt.sh" "$S" 8 sol \
      correctness-boundaries+security-state-api composite) || return
    assert_grep "composite lens keeps correctness instructions" "$composite" \
      '^Check logic, boundary inputs, partial failure, cleanup, and error contracts\.'
    assert_grep "composite lens keeps security instructions" "$composite" \
      '^Check trust boundaries, authorization, durable-state invariants, serialization, idempotency, compatibility, and public API behavior\.'

    python3 - "$first" "$clean" "$composite" "$T" <<'PY'
from pathlib import Path
import sys
for source, name in zip(sys.argv[1:4], ('sol', 'grok', 'composite')):
    text = Path(source).read_text()
    assert text.startswith('# Reviewer contract\n')
    prefix, marker, _ = text.partition('\n## Review assignment\n')
    assert marker
    Path(sys.argv[4], name + '.prefix').write_text(prefix + '\n')
PY
    sol_prefix="$T/sol.prefix"; grok_prefix="$T/grok.prefix"; opus_prefix="$T/composite.prefix"
    assert_exit "invariant prefix is byte-stable across seat and lens" 0 cmp -s "$sol_prefix" "$grok_prefix"
    assert_exit "invariant prefix is byte-stable for composite bundles" 0 cmp -s "$sol_prefix" "$opus_prefix"
    assert_grep "stable prefix carries clean-room ordering" "$sol_prefix" 'clean-room lens, write the smallest design before any patch or source read'
    assert_grep "stable prefix carries exact Read bound" "$sol_prefix" 'offset.*limit.*240'
    assert_grep "stable prefix carries exact search bound" "$sol_prefix" 'result limit.*80'
    assert_grep "stable prefix carries per-turn byte bound" "$sol_prefix" '32 KiB combined output ceiling'
    assert_grep "stable prefix asks for batched independent windows" "$sol_prefix" 'Batch independent bounded windows.*one tool turn'
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
