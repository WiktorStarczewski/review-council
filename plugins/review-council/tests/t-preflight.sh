# tests for Task 5 — sourced by run-tests.sh
# No subshell: ok/fail must increment the runner's PASS/FAIL in the parent shell, so state is saved and restored by hand.
test_preflight() {
  local old_pwd=$PWD old_path=$PATH
  seat_env; local R="$T/pf"; mkrepo "$R"
  cd "$R" || { fail "preflight setup" "cannot cd to $R"; PATH=$old_path; return 1; }
  R=$(git rev-parse --show-toplevel)   # /tmp is a symlink on macOS; git reports the physical path
  export REV_CODEX_MODELS_CACHE="$FX/codex-models-cache.json"
  "$SCRIPTS/rev-preflight.sh" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "main refused" "$?" 1
  assert_grep "reason names branch" "$T/pf.err" "shared branch 'main'"
  git checkout -qb feat; "$SCRIPTS/rev-preflight.sh" 2> "$T/pf.err"; assert_eq "empty scope refused" "$?" 1
  assert_grep "reason says empty" "$T/pf.err" 'scope is empty'
  echo b > b.txt; git add b.txt; git commit -qm "feat: b"; echo c > c.txt
  "$SCRIPTS/rev-preflight.sh" --write "$T/pf-sess" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "feature branch ok" "$?" 0
  assert_grep "summary line" "$T/pf.out" "^base=$(git rev-parse main) branch=feat default=main root=$R scope=branch changed_files=2$"
  assert_grep "sol seat with top effort" "$T/pf.out" '^  codex-sol@max$'
  assert_grep "terra steps down when max absent" "$T/pf.out" '^  codex-terra@xhigh$'
  assert_nogrep "luna never seated" "$T/pf.out" 'luna'
  assert_grep "grok seat" "$T/pf.out" '^  grok@xhigh$'
  assert_grep "opus seat" "$T/pf.out" '^  opus@max'
  # values are single-quoted so `. scope.env` can never expand or execute one (see t-scopeenv.sh)
  assert_grep "scope.env base" "$T/pf-sess/scope.env" "^REV_BASE='$(git rev-parse main)'$"
  assert_grep "scope.env root" "$T/pf-sess/scope.env" "^REV_ROOT='$R'$"
  assert_grep "files.txt committed" "$T/pf-sess/files.txt" '^b.txt$'
  assert_grep "files.txt untracked" "$T/pf-sess/files.txt" '^c.txt$'
  # untracked files are invisible to `git diff`: listed separately so the prompt can say "read them in full"
  assert_grep "untracked.txt lists the untracked file" "$T/pf-sess/untracked.txt" '^c.txt$'
  assert_nogrep "untracked.txt excludes tracked files" "$T/pf-sess/untracked.txt" '^b.txt$'
  "$SCRIPTS/rev-preflight.sh" --scope uncommitted > "$T/pf.out"; assert_eq "uncommitted scope ok" "$?" 0
  assert_grep "uncommitted base is HEAD" "$T/pf.out" "^base=$(git rev-parse HEAD) .* scope=uncommitted changed_files=1$"
  "$SCRIPTS/rev-preflight.sh" --scope b.txt > "$T/pf.out"; assert_eq "path scope ok" "$?" 0
  assert_grep "path scope counts" "$T/pf.out" ' scope=b.txt changed_files=1$'
  assert_exit "missing path refused" 1 "$SCRIPTS/rev-preflight.sh" --scope nope.txt
  assert_exit "REV_ACTIVE refused" 1 env REV_ACTIVE=1 "$SCRIPTS/rev-preflight.sh"
  SHIM_MODE=notauth "$SCRIPTS/rev-preflight.sh" 2> "$T/pf.err"; assert_eq "codex notauth refused" "$?" 1
  assert_grep "names codex" "$T/pf.err" 'codex is not signed in'
  # paths with spaces: the pathspec and the changed-file list must not be word-split (git quotes such paths in porcelain v1)
  mkdir -p "my dir"; echo s > "my dir/a note.txt"; git add "my dir/a note.txt"; git commit -qm "feat: spaces"
  echo u > "untracked note.txt"
  "$SCRIPTS/rev-preflight.sh" --write "$T/pf-sp" > "$T/pf.out" 2>&1; assert_eq "space paths ok" "$?" 0
  assert_grep "space path intact" "$T/pf-sp/files.txt" '^my dir/a note\.txt$'
  assert_grep "untracked space path intact" "$T/pf-sp/files.txt" '^untracked note\.txt$'
  assert_nogrep "no quote fragments" "$T/pf-sp/files.txt" '"'
  "$SCRIPTS/rev-preflight.sh" --scope "my dir" > "$T/pf.out" 2>&1; assert_eq "scope with a space ok" "$?" 0
  assert_grep "space scope counts one file" "$T/pf.out" ' scope=my dir changed_files=1$'
  # codex cache unusable → an explicit seat warning, never a silent two-seat run or a python traceback
  REV_CODEX_MODELS_CACHE="$T/nope.json" "$SCRIPTS/rev-preflight.sh" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "missing cache still exits 0" "$?" 0
  assert_grep "warns about the cache" "$T/pf.out" '^  codex: no usable model in '
  assert_nogrep "no traceback on stderr" "$T/pf.err" 'Traceback'
  printf '%s' '{"models":[{"slug":"gpt-5.6-sol","supported_reasoning_levels":[{}]}]}' > "$T/bad-cache.json"
  REV_CODEX_MODELS_CACHE="$T/bad-cache.json" "$SCRIPTS/rev-preflight.sh" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "effort-less level survives" "$?" 0
  assert_nogrep "no KeyError" "$T/pf.err" 'KeyError'
  assert_grep "warns when no effort" "$T/pf.out" '^  codex: no usable model in '
  cd "$T" && assert_exit "outside a repo refused" 1 "$SCRIPTS/rev-preflight.sh"
  cd "$old_pwd" 2>/dev/null || cd "$T" || return 1
  PATH=$old_path; export PATH; unset REV_CODEX_MODELS_CACHE
}
test_prompt() {
  local S="$T/pr-sess"; mkdir -p "$S"
  printf 'REV_BASE=abc123\nREV_BRANCH=feat\nREV_DEFAULT=main\nREV_ROOT=/repo\nREV_SCOPE=branch\n' > "$S/scope.env"
  printf 'src/x.ts\nsrc/x.test.ts\n' > "$S/files.txt"; echo "build: pass; test: 2 pre-existing failures (a, b); lint: pass" > "$S/baseline.md"
  local p; p=$("$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness "Correctness, edge cases, error handling")
  assert_eq "prints path" "$p" "$S/r1-grok.prompt.md"
  assert_grep "grok tools-first" "$p" '^FIRST run your tools'
  assert_grep "base sha" "$p" 'Base commit: abc123'
  assert_grep "diff command" "$p" 'git diff abc123'
  assert_grep "files listed" "$p" '^- src/x.test.ts$'
  assert_grep "lens text" "$p" 'off-by-one'
  assert_grep "emphasis" "$p" '^Round emphasis: Correctness, edge cases, error handling$'
  assert_grep "baseline included" "$p" 'pre-existing failures'
  assert_grep "rejected none" "$p" '\(none yet\)'
  assert_grep "schema embedded" "$p" '"severity"'
  assert_nogrep "no vacuity by default" "$p" 'VACUITY'
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 2 codex-sol tests "Tests, observability" --vacuity)
  assert_nogrep "codex has no tools-first" "$p" '^FIRST run your tools'
  assert_grep "vacuity section" "$p" '^## Vacuity check'
  echo "- F-003 REJECTED: retry is bounded by maxAttempts (handler.ts:40)" > "$S/rejected.md"
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 3 codex-terra red-team "Red team")
  assert_grep "rejected listed" "$p" 'F-003 REJECTED'
  assert_grep "red-team lens" "$p" 'Assume the change is wrong'
  # untracked files are invisible to `git diff`: rev-preflight.sh lists them in untracked.txt and the
  # prompt marks them so a seat reads them in full instead of reporting an empty diff.
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 5 grok correctness "Untracked")
  assert_nogrep "no untracked note without untracked.txt" "$p" 'untracked'
  : > "$S/untracked.txt"
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 5 grok correctness "Untracked")
  assert_nogrep "empty untracked.txt renders nothing" "$p" 'untracked'
  printf 'src/x.test.ts\n' > "$S/untracked.txt"
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 5 grok correctness "Untracked")
  assert_grep "untracked file marked" "$p" '^- src/x.test.ts \(untracked\)$'
  assert_grep "tracked file unmarked" "$p" '^- src/x.ts$'
  assert_grep "untracked note rendered" "$p" 'do not appear in .git diff.; read them in full'
  rm -f "$S/untracked.txt"
  printf '%s\n' "$S/plan.md" > "$S/docs.txt"; echo "# plan" > "$S/plan.md"
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness "Prose review" --read-only "$S/docs.txt")
  assert_grep "read-only lists docs" "$p" "^- $S/plan\.md$"
  assert_nogrep "read-only has no repo scope" "$p" '^Repository:'
  # scope.env is parsed, not sourced: a space in the root and metacharacters in the branch are inert data
  printf 'REV_BASE=abc123\nREV_BRANCH=x;touch %s/pwned\nREV_DEFAULT=main\nREV_ROOT=/my repo/w s\nREV_SCOPE=branch\n' "$S" > "$S/scope.env"
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 4 grok correctness "Injection") ; assert_eq "space/metachar scope.env ok" "$?" 0
  assert_grep "root with a space intact" "$p" '^Repository: /my repo/w s$'
  assert_grep "branch metachars are literal" "$p" 'branch .x;touch '
  assert_exit "no command ran from scope.env" 1 test -e "$S/pwned"
  printf 'REV_BASE=abc123\nREV_BRANCH=feat\nREV_DEFAULT=main\nREV_ROOT=/repo\nREV_SCOPE=branch\n' > "$S/scope.env"
  : > "$S/empty-docs.txt"
  assert_exit "empty --read-only list → 1" 1 "$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness x --read-only "$S/empty-docs.txt"
  assert_exit "missing --read-only list → 1" 1 "$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness x --read-only "$S/no-such-list.txt"
  "$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness x --read-only "$S/empty-docs.txt" 2> "$T/ro.err"
  assert_grep "names the missing list" "$T/ro.err" 'document list missing or empty'
  assert_exit "unknown flag → 1" 1 "$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness x --bogus
  # unwritable output must fail loudly, not print a path for a file that was never written
  assert_exit "unwritable OUT → 1" 1 "$SCRIPTS/rev-prompt.sh" "$T/no-such-session" 1 grok correctness x --read-only "$S/docs.txt"
  printf 'REV_ROOT=/repo\n' > "$S/scope.env"
  assert_exit "incomplete scope.env → 1" 1 "$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness x
  rm "$S/scope.env"; assert_exit "missing scope.env → 1" 1 "$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness x
}
