# preflight edges: a degraded-but-sufficient roster, a relative --write, a master-only repo, a deleted path scope.
test_preflight_edges() {
  ( seat_env; local PF; PF="$(pf_bin)/rev-preflight.sh"
    local R="$T/pf2"; mkrepo "$R"; cd "$R" || { fail "pf2 setup" "cannot cd"; return 1; }
    git checkout -qb feat; echo b > b.txt; git add b.txt; git commit -qm "feat: b"
    # a lab that is out but still leaves three seats is a warning on the roster line, not a refusal
    RSTUB_BRIEF='review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@xhigh) · grok ✗ not signed in · gemini ✗ not installed · claude ✓ (opus@max)' \
      "$PF" > "$T/pf2.out" 2> "$T/pf2.err"
    assert_eq "a degraded but sufficient roster is accepted" "$?" 0
    assert_grep "the roster line names the missing lab" "$T/pf2.out" 'grok ✗ not signed in'
    assert_nogrep "and preflight adds no sign-in check of its own" "$T/pf2.err" 'not signed in'
    # --write is resolved against the CALLER's cwd, not the repo root it cds to
    mkdir -p "$R/sub"; cd "$R/sub" || { fail "pf2 setup" "cannot cd to sub"; return 1; }
    "$PF" --write sess > /dev/null 2>&1; assert_eq "relative --write ok" "$?" 0
    assert_exit "relative --write lands under the cwd" 0 test -f "$R/sub/sess/scope.env"
    assert_exit "roster.json lands beside scope.env" 0 test -f "$R/sub/sess/roster.json"
    assert_exit "…and not under the repo root" 1 test -f "$R/sess/scope.env"
    cd "$R" || return 1
    # a path the change DELETES is still a reviewable scope
    git rm -q a.txt; git commit -qm "feat: drop a"
    "$PF" --scope a.txt > "$T/pf2.out" 2>&1; assert_eq "deleted path scope ok" "$?" 0
    assert_grep "deleted path counts one file" "$T/pf2.out" ' scope=a.txt changed_files=1$'
    assert_exit "a path that never existed is still refused" 1 "$PF" --scope nope.txt
    # default branch: origin/HEAD → main → master → refuse
    local M="$T/pf2-master"; mkrepo "$M"; cd "$M" || { fail "pf2 setup" "cannot cd to master repo"; return 1; }
    git branch -m master; git checkout -qb feat; echo m > m.txt; git add m.txt; git commit -qm "feat: m"
    "$PF" > "$T/pf2m.out" 2>&1; assert_eq "master-only repo ok" "$?" 0
    assert_grep "default is master" "$T/pf2m.out" ' default=master '
    git branch -m master trunk
    "$PF" > /dev/null 2> "$T/pf2n.err"; assert_eq "no base branch refused" "$?" 1
    assert_grep "says why" "$T/pf2n.err" 'cannot determine the default branch'
  )
}

# …and the same seam against the REAL roster.sh, driven by the shims: preflight seats from it, pads and
# warns instead of refusing when a lab is missing, and never runs a sign-in check of its own. PATH holds
# only the shims plus the system directories, so a real codex/grok/gemini can never be reached.
test_preflight_roster() {
  ( local B="$T/pfr-bin" R="$T/pfr"; mkdir -p "$B"; mkrepo "$R"
    cp "$SHIMS/codex" "$SHIMS/grok" "$B/"; chmod +x "$B/codex" "$B/grok"
    export PATH="$B:/usr/bin:/bin:/usr/sbin:/sbin"
    export HOME="$T/pfr-home"; mkdir -p "$HOME"
    export SHIM_FIXTURE_DIR="$FX"
    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$FX/roster-codex-cache-full.json"
    export REVIEW_COUNCIL_CONFIG="$HOME/no-such-config.json"
    export REVIEW_COUNCIL_GEMINI_CREDS="$HOME/no-such-creds.json"
    unset GEMINI_API_KEY REVIEW_COUNCIL_GEMINI_MODEL REVIEW_COUNCIL_CLAUDE_SEAT SHIM_MODE SHIM_ARGS_FILE
    cd "$R" || { fail "pfr setup" "cannot cd to $R"; return 1; }
    git checkout -qb feat; echo b > b.txt; git add b.txt; git commit -qm "feat: b"
    "$SCRIPTS/rev-preflight.sh" --write "$T/pfr-sess" > "$T/pfr.out" 2> "$T/pfr.err"
    assert_eq "real roster: four seats accepted" "$?" 0
    assert_grep "base line first" "$T/pfr.out" '^base=[0-9a-f]{7,} base_branch=main \(nearest fork point\) branch=feat '
    assert_grep "roster line second" "$T/pfr.out" '^review-council seats: codex ✓ \(gpt-5\.6-sol@max, gpt-5\.6-terra@max\) · grok ✓ \(grok-4\.6@xhigh\)'
    assert_grep "an absent lab is reported, not fatal" "$T/pfr.out" 'gemini ✗ not installed'
    assert_grep "roster.json holds the probed seats" "$T/pfr-sess/roster.json" '"seat": "codex-sol"'
    assert_nogrep "an excluded lab is never seated" "$T/pfr-sess/roster.json" '"seat": "gemini"'
    assert_exit "scope.env is written beside it" 0 test -f "$T/pfr-sess/scope.env"
    # codex gone → grok + opus only: the panel is padded to three and the run is warned about, not refused
    rm -f "$B/codex"
    "$SCRIPTS/rev-preflight.sh" --write "$T/pfr-sess2" > "$T/pfr.out" 2> "$T/pfr.err"
    assert_eq "real roster: a two-lab machine still runs" "$?" 0
    assert_grep "base line printed" "$T/pfr.out" '^base=[0-9a-f]{7,} base_branch=main \(nearest fork point\) branch=feat '
    assert_grep "the roster line carries DEGRADED" "$T/pfr.out" \
      'DEGRADED: only xai, anthropic available — padded with 1 Claude seat$'
    assert_grep "…and preflight adds its own warning line" "$T/pfr.out" \
      '^preflight: WARNING — only xai, anthropic available — padded with 1 Claude seat$'
    assert_grep "the padded seat is in roster.json" "$T/pfr-sess2/roster.json" '"seat": "claude-1"'
    assert_grep "…marked as padded" "$T/pfr-sess2/roster.json" '"padded": true'
    assert_exit "scope.env is written for a degraded run" 0 test -f "$T/pfr-sess2/scope.env"
    assert_nogrep "nothing on stderr" "$T/pfr.err" '.'
    # min_labs is the hard floor for teams that would rather not review than review single-lab
    printf '%s' '{"min_labs": 3}' > "$HOME/strict.json"
    REVIEW_COUNCIL_CONFIG="$HOME/strict.json" "$SCRIPTS/rev-preflight.sh" --write "$T/pfr-sess3" \
      > "$T/pfr.out" 2> "$T/pfr.err"
    assert_eq "real roster: min_labs refuses" "$?" 1
    assert_grep "the strict reason is relayed" "$T/pfr.err" '^preflight: strict: 2 lab\(s\) available, min_labs=3 — '
    assert_nogrep "no base line on a refusal" "$T/pfr.out" '^base='
    assert_exit "no scope.env from a refused run" 1 test -f "$T/pfr-sess3/scope.env"
  )
}

# The base is the branch the change was cut from, not origin/HEAD: a feature branch off `next` must be
# measured against next (74 commits of next-only history were once reviewed as the change). --base and
# REV_BASE_REF override; the nearest fork point decides otherwise; HEAD on the chosen base is refused.
test_preflight_base() {
  ( seat_env; local PF; PF="$(pf_bin)/rev-preflight.sh"
    local R="$T/pf-base"; mkrepo "$R"; cd "$R" || { fail "pf-base setup" "cannot cd"; return 1; }
    git checkout -qb next; for i in 1 2 3; do echo "n$i" > "n$i.txt"; git add "n$i.txt"; git commit -qm "next: $i"; done
    git checkout -qb feat-next; echo f > f.txt; git add f.txt; git commit -qm "feat: on next"
    local mb_next mb_main; mb_next=$(git merge-base HEAD next); mb_main=$(git merge-base HEAD main)
    "$PF" --write "$T/pfb-sess" > "$T/pfb.out" 2>&1; assert_eq "branch cut from next: preflight ok" "$?" 0
    assert_grep "nearest fork point picks next" "$T/pfb.out" ' base_branch=next \(nearest fork point\) '
    assert_grep "base is the merge-base with next" "$T/pfb.out" "^base=$mb_next "
    assert_grep "only the branch's own file is in scope" "$T/pfb.out" ' changed_files=1$'
    assert_grep "scope.env records the base branch" "$T/pfb-sess/scope.env" "^REV_BASE_BRANCH='next'$"
    "$PF" --base main > "$T/pfb2.out" 2>&1; assert_eq "--base main accepted" "$?" 0
    assert_grep "--base main is honoured" "$T/pfb2.out" "^base=$mb_main base_branch=main \(given\) "
    assert_grep "…and widens the scope to next's files" "$T/pfb2.out" ' changed_files=4$'
    REV_BASE_REF=main "$PF" > "$T/pfb3.out" 2>&1; assert_grep "REV_BASE_REF is honoured" "$T/pfb3.out" ' base_branch=main \(given\) '
    "$PF" --base nosuch > /dev/null 2> "$T/pfb4.err"; assert_eq "unknown --base refused" "$?" 1
    assert_grep "says why" "$T/pfb4.err" "base 'nosuch' is not a branch"
    git checkout -qb feat-main main; echo g > g.txt; git add g.txt; git commit -qm "feat: on main"
    "$PF" > "$T/pfb5.out" 2>&1; assert_grep "a branch cut from main still picks main" "$T/pfb5.out" ' base_branch=main \(nearest fork point\) '
    git checkout -q next
    "$PF" > /dev/null 2> "$T/pfb6.err"; assert_eq "HEAD on next is refused as shared" "$?" 1
    assert_grep "says why" "$T/pfb6.err" "shared branch 'next'"
  )
}
