# A1 — scope.env must be safe to `source`: values are single-quoted, so a branch name or a repo path
# carrying shell metacharacters is data, never a command. SKILL.md tells the orchestrator to source it.
test_scopeenv() {
  ( seat_env; local PF; PF="$(pf_bin)/rev-preflight.sh"
    local R="$T/se repo"                       # a repo root containing a space
    mkrepo "$R"; cd "$R" || { fail "scopeenv setup" "cannot cd to $R"; return 1; }
    local B='feat/$(>'"$T"'/pwned)'            # a legal git branch name that is also a shell command
    git checkout -qb "$B" 2>/dev/null || { fail "scopeenv setup" "git refused the branch name"; return 1; }
    echo x > x.txt; git add x.txt; git commit -qm "feat: x"
    "$PF" --write "$T/se-sess" > "$T/se.out" 2>&1
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

# Preflight records no dependency root: prepare builds the per-crate view from each panel's snapshot.
test_scopeenv_records_no_dependency_root() {
  ( seat_env; local PF; PF="$(pf_bin)/rev-preflight.sh"
    local R="$T/cargo-scope-repo"
    mkrepo "$R"; cd "$R" || { fail "cargo scope setup" "cannot cd to $R"; return 1; }
    git checkout -qb feat && echo x > x.txt && git add x.txt && git commit -qm x
    mkdir -p "$T/cargo-home/registry/src/index.crates.io-0"
    printf '# lock\n' > Cargo.lock; git add Cargo.lock; git commit -qm lock
    CARGO_HOME="$T/cargo-home" "$PF" --write "$T/cargo-scope-lock" >/dev/null 2>&1
    assert_eq "a Cargo repository's scope.env names no dependency root" \
      "$(python3 -c 'import sys; print(sorted(l.split("=")[0] for l in open(sys.argv[1]) if l.strip()))' "$T/cargo-scope-lock/scope.env")" \
      "['REV_BASE', 'REV_BASE_BRANCH', 'REV_BRANCH', 'REV_DEFAULT', 'REV_ROOT', 'REV_SCOPE']"
  )
}
