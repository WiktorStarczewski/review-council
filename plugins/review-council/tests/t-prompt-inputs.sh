# Prompt publication is transactional: invalid selected inputs remove stale output and print no path.
test_prompt_inputs() {
  ( local S="$T/prompt-inputs"; mkdir -p "$S"
    printf "REV_BASE='abc123'\nREV_BRANCH='feat'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" "$T" > "$S/scope.env"
    printf 'src/a.ts\n' > "$S/files.txt"
    local case_number=0
    expect_prompt_failure() {
      local label=$1 final=$2; shift 2
      case_number=$((case_number + 1))
      [ -e "$final" ] || printf 'stale prompt\n' > "$final"
      "$@" > "$T/prompt-fail-$case_number.out" 2> "$T/prompt-fail-$case_number.err"; local rc=$?
      [ "$rc" -ne 0 ] && ok "$label is rejected" || fail "$label is rejected" "exit $rc"
      assert_eq "$label prints no prompt path" "$(cat "$T/prompt-fail-$case_number.out")" ""
      assert_exit "$label leaves no final prompt" 1 test -e "$final"
      assert_eq "$label leaves no temporary prompt" "$(find "$(dirname "$final")" -maxdepth 1 -name '.rev-prompt.*' 2>/dev/null | wc -l | tr -d ' ')" 0
    }

    mkdir -p "$S/plan-dir"; printf 'content\n' > "$S/plan-dir/item"
    expect_prompt_failure "nonempty plan directory" "$S/r1-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 1 grok plan-tests plan --plan "$S/plan-dir"

    mkdir -p "$S/docs-dir"; printf 'content\n' > "$S/docs-dir/item"
    expect_prompt_failure "nonempty document-list directory" "$S/r2-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 2 grok correctness docs --read-only "$S/docs-dir"

    mv "$S/scope.env" "$S/scope.saved"; mkdir "$S/scope.env"; printf 'content\n' > "$S/scope.env/item"
    expect_prompt_failure "scope directory" "$S/r3-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 3 grok correctness scope
    rm -rf "$S/scope.env"; mv "$S/scope.saved" "$S/scope.env"

    mv "$S/files.txt" "$S/files.saved"; mkdir "$S/files.txt"; printf 'content\n' > "$S/files.txt/item"
    expect_prompt_failure "changed-file directory" "$S/r4-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 4 grok correctness files
    rm -rf "$S/files.txt"; mv "$S/files.saved" "$S/files.txt"

    mkdir "$S/untracked.txt"; printf 'content\n' > "$S/untracked.txt/item"
    expect_prompt_failure "untracked-file directory" "$S/r5-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 5 grok correctness untracked
    rm -rf "$S/untracked.txt"

    expect_prompt_failure "missing selected PR description" "$S/r6-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 6 grok correctness pr --pr "$S/missing-pr.md"

    printf '{not json}\n' > "$S/roster.json"
    expect_prompt_failure "malformed roster JSON" "$S/r7-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 7 grok correctness roster
    printf '%s\n' '{"seats":[{"seat":"opus","adapter":"agent"}]}' > "$S/roster.json"
    expect_prompt_failure "roster without selected seat" "$S/r8-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 8 grok correctness roster

    rm -f "$S/roster.json"; mkdir "$S/baseline.md"; printf 'content\n' > "$S/baseline.md/item"
    expect_prompt_failure "optional baseline directory" "$S/r9-grok.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 9 grok correctness baseline
    rm -rf "$S/baseline.md"

    local no_roster compatibility_seat
    for compatibility_seat in opus gemini native-seat unknown-seat; do
      no_roster=$("$SCRIPTS/rev-prompt.sh" "$S" 10 "$compatibility_seat" correctness compatibility)
      assert_eq "absent roster keeps $compatibility_seat compatibility" "$no_roster" \
        "$S/r10-$compatibility_seat.prompt.md"
      assert_eq "$compatibility_seat compatibility embeds one schema" \
        "$(grep -c '"[$]schema"' "$no_roster" || true)" 1
    done

    printf '%s\n' '{"seats":[{"seat":"opus","adapter":"agent"},{"seat":"gemini","adapter":"gemini"}]}' > "$S/roster.json"
    local prompt seat
    for seat in opus gemini; do
      prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 11 "$seat" correctness schema)
      assert_eq "$seat valid prompt embeds one schema" "$(grep -c '"[$]schema"' "$prompt" || true)" 1
    done

    local COPY="$T/prompt-copy"; mkdir -p "$COPY/scripts" "$COPY/schema" "$COPY/bin"
    cp "$SCRIPTS/rev-prompt.sh" "$COPY/scripts/rev-prompt.sh"
    cp "$SCRIPTS/../schema/findings.schema.json" "$COPY/schema/findings.schema.json"
    cat > "$COPY/bin/cat" <<'SH'
#!/bin/bash
last=${!#}
case "$last" in */findings.schema.json) exit 23;; esac
exec /bin/cat "$@"
SH
    chmod +x "$COPY/bin/cat"
    expect_prompt_failure "inline schema read failure" "$S/r12-opus.prompt.md" \
      env PATH="$COPY/bin:$PATH" \
      "$COPY/scripts/rev-prompt.sh" "$S" 12 opus correctness schema

    printf 'valid PR body\n' > "$S/pr.md"
    local first; first=$("$SCRIPTS/rev-prompt.sh" "$S" 13 opus correctness first --pr "$S/pr.md")
    assert_exit "same-label first render exists" 0 test -f "$first"
    rm "$S/pr.md"; mkdir "$S/pr.md"; printf 'content\n' > "$S/pr.md/item"
    expect_prompt_failure "same-label rerender with invalid PR" "$S/r13-opus.prompt.md" \
      "$SCRIPTS/rev-prompt.sh" "$S" 13 opus correctness second --pr "$S/pr.md"

    local FAILBIN="$T/prompt-render-bin"; mkdir -p "$FAILBIN"
    cat > "$FAILBIN/sed" <<'SH'
#!/bin/bash
exit 24
SH
    chmod +x "$FAILBIN/sed"
    rm -rf "$S/pr.md"; rm -f "$S/roster.json"
    expect_prompt_failure "renderer read failure" "$S/r14-grok.prompt.md" \
      env PATH="$FAILBIN:$PATH" "$SCRIPTS/rev-prompt.sh" "$S" 14 grok correctness render
  )
}
