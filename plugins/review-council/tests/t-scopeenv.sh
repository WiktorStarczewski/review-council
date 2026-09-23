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

# A Cargo repository with no REV_DEPS_DIR records the cargo registry root as the pinned-dependency
# root, and only when that directory exists.
test_scopeenv_records_cargo_registry_root() {
  ( seat_env; local PF; PF="$(pf_bin)/rev-preflight.sh"
    local R="$T/cargo-scope-repo" registry="$T/cargo-home/registry/src" case_name want
    mkrepo "$R"; cd "$R" || { fail "cargo scope setup" "cannot cd to $R"; return 1; }
    git checkout -qb feat && echo x > x.txt && git add x.txt && git commit -qm x
    mkdir -p "$registry" "$T/cargo-home-empty" "$T/cargo-user/.cargo/registry/src"
    deps_line() {
      python3 - "$1/scope.env" <<'PY'
import shlex, sys
rows = dict(line.split('=', 1) for line in open(sys.argv[1]).read().splitlines() if line)
print(shlex.split(rows['REV_DEPS_DIR'])[0] if 'REV_DEPS_DIR' in rows else '-')
PY
    }
    CARGO_HOME="$T/cargo-home" "$PF" --write "$T/cargo-scope-no-lock" >/dev/null 2>&1
    assert_eq "no Cargo.lock records no dependency root" "$(deps_line "$T/cargo-scope-no-lock")" -
    printf '# lock\n' > Cargo.lock; git add Cargo.lock; git commit -qm lock
    CARGO_HOME="$T/cargo-home" "$PF" --write "$T/cargo-scope-lock" >/dev/null 2>&1
    assert_eq "a Cargo.lock records the registry source root" \
      "$(deps_line "$T/cargo-scope-lock")" "$registry"
    ( unset CARGO_HOME; HOME="$T/cargo-user" "$PF" --write "$T/cargo-scope-home" >/dev/null 2>&1 )
    assert_eq "CARGO_HOME defaults to ~/.cargo" \
      "$(deps_line "$T/cargo-scope-home")" "$T/cargo-user/.cargo/registry/src"
    CARGO_HOME="$T/cargo-home-empty" "$PF" --write "$T/cargo-scope-absent" >/dev/null 2>&1
    assert_eq "a missing registry records no dependency root" "$(deps_line "$T/cargo-scope-absent")" -
    CARGO_HOME="$T/cargo-home" REV_DEPS_DIR="$T/view" "$PF" --write "$T/cargo-scope-explicit" >/dev/null 2>&1
    assert_eq "an explicit REV_DEPS_DIR is left to the environment" \
      "$(deps_line "$T/cargo-scope-explicit")" -
  )
}
