# B7/B10/A8 — preflight edges: grok-only sign-out, a relative --write, a master-only repo, a deleted path scope.
test_preflight_edges() {
  ( seat_env; export REV_CODEX_MODELS_CACHE="$FX/codex-models-cache.json"
    local R="$T/pf2"; mkrepo "$R"; cd "$R" || { fail "pf2 setup" "cannot cd"; return 1; }
    git checkout -qb feat; echo b > b.txt; git add b.txt; git commit -qm "feat: b"
    # "logged in" is a substring of "Not logged in": grok alone signed out must still refuse
    SHIM_MODE=grok-notauth "$SCRIPTS/rev-preflight.sh" > /dev/null 2> "$T/pf2.err"
    assert_eq "grok notauth refused" "$?" 1
    assert_grep "names grok" "$T/pf2.err" 'grok is not signed in'
    # --write is resolved against the CALLER's cwd, not the repo root it cds to
    mkdir -p "$R/sub"; cd "$R/sub" || { fail "pf2 setup" "cannot cd to sub"; return 1; }
    "$SCRIPTS/rev-preflight.sh" --write sess > /dev/null 2>&1; assert_eq "relative --write ok" "$?" 0
    assert_exit "relative --write lands under the cwd" 0 test -f "$R/sub/sess/scope.env"
    assert_exit "…and not under the repo root" 1 test -f "$R/sess/scope.env"
    cd "$R" || return 1
    # a path the change DELETES is still a reviewable scope
    git rm -q a.txt; git commit -qm "feat: drop a"
    "$SCRIPTS/rev-preflight.sh" --scope a.txt > "$T/pf2.out" 2>&1; assert_eq "deleted path scope ok" "$?" 0
    assert_grep "deleted path counts one file" "$T/pf2.out" ' scope=a.txt changed_files=1$'
    assert_exit "a path that never existed is still refused" 1 "$SCRIPTS/rev-preflight.sh" --scope nope.txt
    # default branch: origin/HEAD → main → master → refuse
    local M="$T/pf2-master"; mkrepo "$M"; cd "$M" || { fail "pf2 setup" "cannot cd to master repo"; return 1; }
    git branch -m master; git checkout -qb feat; echo m > m.txt; git add m.txt; git commit -qm "feat: m"
    "$SCRIPTS/rev-preflight.sh" > "$T/pf2m.out" 2>&1; assert_eq "master-only repo ok" "$?" 0
    assert_grep "default is master" "$T/pf2m.out" ' default=master '
    git branch -m master trunk
    "$SCRIPTS/rev-preflight.sh" > /dev/null 2> "$T/pf2n.err"; assert_eq "no base branch refused" "$?" 1
    assert_grep "says why" "$T/pf2n.err" 'cannot determine the default branch'
  )
}
