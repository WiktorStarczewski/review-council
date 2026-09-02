# A1 — scope.env must be safe to `source`: values are single-quoted, so a branch name or a repo path
# carrying shell metacharacters is data, never a command. SKILL.md tells the orchestrator to source it.
test_scopeenv() {
  ( seat_env; export REV_CODEX_MODELS_CACHE="$FX/codex-models-cache.json"
    local R="$T/se repo"                       # a repo root containing a space
    mkrepo "$R"; cd "$R" || { fail "scopeenv setup" "cannot cd to $R"; return 1; }
    local B='feat/$(>'"$T"'/pwned)'            # a legal git branch name that is also a shell command
    git checkout -qb "$B" 2>/dev/null || { fail "scopeenv setup" "git refused the branch name"; return 1; }
    echo x > x.txt; git add x.txt; git commit -qm "feat: x"
    "$SCRIPTS/rev-preflight.sh" --write "$T/se-sess" > "$T/se.out" 2>&1
    assert_eq "preflight accepts a metacharacter branch" "$?" 0
    assert_grep "value is single-quoted" "$T/se-sess/scope.env" "^REV_BRANCH='"
    ( set -u; . "$T/se-sess/scope.env"
      printf '%s' "$REV_BRANCH" > "$T/se.branch"; printf '%s' "$REV_ROOT" > "$T/se.root" ) 2>/dev/null
    assert_exit "sourcing scope.env executed nothing" 1 test -e "$T/pwned"
    assert_eq "branch survives sourcing verbatim" "$(cat "$T/se.branch" 2>/dev/null)" "$B"
    assert_eq "root with a space round-trips" "$(cat "$T/se.root" 2>/dev/null)" "$(git rev-parse --show-toplevel)"
    # …and rev-prompt.sh, which parses rather than sources, must strip the same quoting
    local p; p=$("$SCRIPTS/rev-prompt.sh" "$T/se-sess" 1 codex-sol correctness "Injection")
    assert_grep "prompt shows the unquoted root" "$p" "^Repository: $(git rev-parse --show-toplevel)$"
    assert_nogrep "prompt does not leak the quoting" "$p" "^Repository: '"
  )
}
