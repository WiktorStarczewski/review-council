# preflight + prompt - sourced by run-tests.sh
# Seats no longer come from hardcoded `codex login status` / `grok models` checks: preflight asks
# scripts/roster.sh. These tests drive that seam through a STUB roster.sh placed next to a symlink to the
# real rev-preflight.sh, so `$HERE/roster.sh` resolves to the stub. The stub models the contract preflight
# depends on (argv, strict exits + JSON, --brief); roster.sh's own detection is covered by t-roster.sh.
pf_bin() {  # pf_bin → prints a dir holding {roster.sh stub, rev-preflight.sh symlink}
  local D="$T/pf-bin"
  if [ ! -x "$D/roster.sh" ]; then
    mkdir -p "$D"
    cat > "$D/roster.sh" <<'STUB'
#!/bin/bash
# stub roster.sh: RSTUB_ARGS=<file> APPENDS every call's argv, RSTUB_EXIT sets the exit code,
# RSTUB_JSON overrides the JSON, RSTUB_BRIEF the --brief line. Like the real roster.sh, --write always
# stores the JSON and --brief only changes what goes to stdout; the exit code is the same either way.
[ -n "${RSTUB_ARGS:-}" ] && printf '%s\n' "$@" >> "$RSTUB_ARGS"
WRITE=""; BRIEF=0
while [ $# -gt 0 ]; do
  case "$1" in --write) WRITE=${2:-}; shift 2;; --brief) BRIEF=1; shift;; *) shift;; esac
done
JSON=${RSTUB_JSON:-}
if [ -z "$JSON" ]; then
  JSON=$(cat <<'J'
{"generated_at": "2026-09-02T00:00:00Z", "seats": [
 {"seat": "codex-sol", "lab": "openai", "adapter": "codex", "model": "gpt-5.6-sol", "effort": "max", "extra": false},
 {"seat": "codex-terra", "lab": "openai", "adapter": "codex", "model": "gpt-5.6-terra", "effort": "xhigh", "extra": false},
 {"seat": "grok", "lab": "xai", "adapter": "grok", "model": "grok-4.6", "effort": "xhigh", "extra": false},
 {"seat": "opus", "lab": "anthropic", "adapter": "agent", "model": "opus", "effort": "max", "extra": false},
 {"seat": "codex-review", "lab": "openai", "adapter": "codex", "mode": "review", "extra": true, "round": 2}],
 "result_receipts": {"version": 1, "legacy_no_exit_sha256": {}},
 "excluded": [{"cli": "gemini", "reason": "not installed"}]}
J
)
fi
[ -n "$WRITE" ] && printf '%s\n' "$JSON" > "$WRITE"
if [ "$BRIEF" = 1 ]; then
  printf '%s\n' "${RSTUB_BRIEF:-review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@xhigh) · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max)}"
else
  printf '%s\n' "$JSON"      # --json: preflight must keep this off its own stdout
fi
exit "${RSTUB_EXIT:-0}"
STUB
    chmod +x "$D/roster.sh"
    ln -sf "$SCRIPTS/rev-preflight.sh" "$D/rev-preflight.sh"
  fi
  printf '%s' "$D"
}
pf_strict_roster() {  # a padded single-lab panel that a config min_labs floor refuses (roster exit 5)
  cat <<'J'
{"generated_at": "2026-09-02T00:00:00Z", "seats": [
 {"seat": "opus", "lab": "anthropic", "adapter": "agent", "model": "opus", "effort": "max", "extra": false},
 {"seat": "claude-1", "lab": "anthropic", "adapter": "agent", "model": "opus", "effort": "max", "extra": false, "padded": true},
 {"seat": "claude-2", "lab": "anthropic", "adapter": "agent", "model": "opus", "effort": "max", "extra": false, "padded": true}],
 "labs": ["anthropic"], "padded": 2, "degraded": true,
 "degradation": "only Claude is available - 3 Claude seats, no cross-lab decorrelation", "strict_class": "availability",
 "strict_reason": "1 lab(s) available, min_labs=2",
 "result_receipts": {"version": 1, "legacy_no_exit_sha256": {}},
 "excluded": [{"cli": "codex", "reason": "not signed in"}, {"cli": "gemini", "reason": "not installed"},
              {"cli": "min_labs", "reason": "strict: 1 lab(s) available, min_labs=2"}]}
J
}
pf_config_roster() {
  cat <<'J'
{"generated_at": "2026-09-02T00:00:00Z", "seats": [], "strict_class": "config",
 "strict_reason": "invalid codex_models: expected a list",
 "result_receipts": {"version": 1, "legacy_no_exit_sha256": {}},
 "excluded": [{"cli": "codex", "reason": "invalid codex_models: expected a list"},
              {"cli": "codex_models", "reason": "strict: invalid codex_models: expected a list"}]}
J
}
pf_degraded_roster() {  # a padded panel that is accepted - preflight warns, it does not refuse
  cat <<'J'
{"generated_at": "2026-09-02T00:00:00Z", "seats": [
 {"seat": "grok", "lab": "xai", "adapter": "grok", "model": "grok-4.6", "effort": "xhigh", "extra": false},
 {"seat": "opus", "lab": "anthropic", "adapter": "agent", "model": "opus", "effort": "max", "extra": false},
 {"seat": "claude-1", "lab": "anthropic", "adapter": "agent", "model": "opus", "effort": "max", "extra": false, "padded": true}],
 "labs": ["xai", "anthropic"], "padded": 1, "degraded": true,
 "degradation": "only xai, anthropic available - padded with 1 Claude seat",
 "result_receipts": {"version": 1, "legacy_no_exit_sha256": {}},
 "excluded": [{"cli": "codex", "reason": "not signed in"}, {"cli": "gemini", "reason": "not installed"}]}
J
}

# No subshell: ok/fail must increment the runner's PASS/FAIL in the parent shell, so state is saved and restored by hand.
test_preflight() {
  local old_pwd=$PWD old_path=$PATH
  seat_env; local PF; PF="$(pf_bin)/rev-preflight.sh"
  export RSTUB_ARGS="$T/rstub.args"
  local R="$T/pf"; mkrepo "$R"
  cd "$R" || { fail "preflight setup" "cannot cd to $R"; PATH=$old_path; return 1; }
  R=$(git rev-parse --show-toplevel)   # /tmp is a symlink on macOS; git reports the physical path
  rm -f "$RSTUB_ARGS"
  "$PF" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "main refused" "$?" 1
  assert_grep "reason names branch" "$T/pf.err" "shared branch 'main'"
  assert_exit "roster is not consulted before the git checks" 1 test -e "$RSTUB_ARGS"
  git checkout -qb feat; "$PF" 2> "$T/pf.err"; assert_eq "empty scope refused" "$?" 1
  assert_grep "reason says empty" "$T/pf.err" 'scope is empty'
  echo b > b.txt; git add b.txt; git commit -qm "feat: b"; echo c > c.txt
  rm -f "$T/args"                      # the shims record every call here; preflight must make none
  "$PF" --write "$T/pf-sess" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "feature branch ok" "$?" 0
  assert_grep "summary line" "$T/pf.out" "^base=$(git rev-parse main) base_branch=main \(nearest fork point\) branch=feat default=main root=$R scope=branch changed_files=2$"
  assert_grep "roster brief line follows it" "$T/pf.out" '^review-council seats: codex ✓'
  assert_nogrep "roster JSON never reaches stdout" "$T/pf.out" '"seats"'
  assert_grep "roster is probed" "$T/rstub.args" '^--probe$'
  assert_grep "roster is written" "$T/rstub.args" '^--write$'
  assert_grep "…into the session dir" "$T/rstub.args" "^$T/pf-sess/roster.json$"
  # one call, not two: the printed line comes from the same probed roster the JSON was built from
  assert_grep "the line is asked for in the same call" "$T/rstub.args" '^--brief$'
  assert_eq "the roster is consulted exactly once" "$(wc -l < "$T/rstub.args" | tr -d ' ')" "4"
  assert_grep "roster.json stored" "$T/pf-sess/roster.json" '"seat": "codex-sol"'
  assert_grep "new session records the receipt policy" "$T/pf-sess/roster.json" '"result_receipts"'
  assert_exit "preflight calls no lab CLI itself" 1 test -e "$T/args"
  # values are single-quoted so `. scope.env` can never expand or execute one (see t-scopeenv.sh)
  assert_grep "scope.env base" "$T/pf-sess/scope.env" "^REV_BASE='$(git rev-parse main)'$"
  assert_grep "scope.env root" "$T/pf-sess/scope.env" "^REV_ROOT='$R'$"
  assert_grep "files.txt committed" "$T/pf-sess/files.txt" '^b.txt$'
  assert_grep "files.txt untracked" "$T/pf-sess/files.txt" '^c.txt$'
  # untracked files are invisible to `git diff`: listed separately so the prompt can say "read them in full"
  assert_grep "untracked.txt lists the untracked file" "$T/pf-sess/untracked.txt" '^c.txt$'
  assert_nogrep "untracked.txt excludes tracked files" "$T/pf-sess/untracked.txt" '^b.txt$'
  "$PF" --scope uncommitted > "$T/pf.out"; assert_eq "uncommitted scope ok" "$?" 0
  assert_grep "uncommitted base is HEAD" "$T/pf.out" "^base=$(git rev-parse HEAD) .* scope=uncommitted changed_files=1$"
  "$PF" --scope b.txt > "$T/pf.out"; assert_eq "path scope ok" "$?" 0
  assert_grep "path scope counts" "$T/pf.out" ' scope=b.txt changed_files=1$'
  assert_exit "missing path refused" 1 "$PF" --scope nope.txt
  assert_exit "REV_ACTIVE refused" 1 env REV_ACTIVE=1 "$PF"
  # without --write the roster JSON goes in a private temp directory that is cleaned up
  rm -f "$RSTUB_ARGS"
  local real_mktemp mktemp_bin scratch
  real_mktemp=$(command -v mktemp); mktemp_bin="$T/mktemp-bin"; mkdir -p "$mktemp_bin"
  cat > "$mktemp_bin/mktemp" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$MKTEMP_CALLS"
out=$("$REAL_MKTEMP" "$@") || exit $?
printf '%s\n' "$out" >> "$MKTEMP_OUTPUTS"
printf '%s\n' "$out"
SH
  chmod +x "$mktemp_bin/mktemp"
  MKTEMP_CALLS="$T/mktemp.calls" MKTEMP_OUTPUTS="$T/mktemp.outputs" REAL_MKTEMP="$real_mktemp" \
    PATH="$mktemp_bin:$PATH" "$PF" > "$T/pf.out" 2>&1
  assert_grep "the roster is still probed" "$T/rstub.args" '^--probe$'
  local tmpj; tmpj=$(grep -A1 -- '^--write$' "$T/rstub.args" | sed -n '2p')
  [ -n "$tmpj" ] && ok "the JSON still lands on a file" || fail "the JSON still lands on a file" "no --write target recorded"
  assert_grep "bare preflight requests a private temp directory" "$T/mktemp.calls" '^-d '
  scratch=$(tail -n 1 "$T/mktemp.outputs")
  assert_eq "roster file is inside the private temp directory" "$tmpj" "$scratch/roster.json"
  case "$tmpj" in "$R"/*) fail "…outside the repository" "$tmpj";; *) ok "…outside the repository";; esac
  assert_exit "…and that temp file is removed" 1 test -e "$tmpj"
  assert_exit "the private temp directory is removed" 1 test -e "$scratch"
  assert_exit "no roster.json left in the repo" 1 test -e "$R/roster.json"
  # a thin panel is no longer a refusal - it is a padded panel and a loud warning (Task 11)
  rm -f "$RSTUB_ARGS"
  RSTUB_JSON="$(pf_degraded_roster)" \
    RSTUB_BRIEF='review-council seats: codex ✗ not signed in · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max) · DEGRADED: only xai, anthropic available - padded with 1 Claude seat' \
    "$PF" --write "$T/pf-deg" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "a degraded roster is accepted" "$?" 0
  assert_grep "the summary line is still printed" "$T/pf.out" '^base='
  assert_grep "the roster line carries DEGRADED" "$T/pf.out" 'DEGRADED: only xai, anthropic available - padded with 1 Claude seat$'
  assert_grep "…and a warning line of its own follows it" "$T/pf.out" \
    '^preflight: WARNING - only xai, anthropic available - padded with 1 Claude seat$'
  assert_exit "scope.env is written for a degraded run" 0 test -f "$T/pf-deg/scope.env"
  assert_nogrep "nothing on stderr" "$T/pf.err" '.'
  # a not-degraded roster gets no warning line at all
  "$PF" > "$T/pf.out" 2>&1; assert_grep "still fine" "$T/pf.out" '^base='
  assert_nogrep "no warning when the panel is whole" "$T/pf.out" 'WARNING'
  # Retryable availability and permanent configuration refusals stay distinct.
  rm -f "$RSTUB_ARGS"
  RSTUB_EXIT=5 RSTUB_JSON="$(pf_strict_roster)" RSTUB_BRIEF='provider availability: only anthropic survived' \
    "$PF" > "$T/pf.out" 2> "$T/pf.err"; assert_eq "strict roster preserves retryable status" "$?" 5
  assert_grep "retryable refusal includes provider evidence" "$T/pf.err" \
    '^provider availability: only anthropic survived$'
  assert_grep "retryable strict reason is relayed" "$T/pf.err" \
    '^preflight: strict availability \(retryable\): 1 lab\(s\) available, min_labs=2$'
  assert_eq "retryable canonical diagnostic is the final line" "$(awk 'NF { line=$0 } END { print line }' "$T/pf.err")" \
    'preflight: strict availability (retryable): 1 lab(s) available, min_labs=2'
  assert_eq "provider evidence precedes retryable diagnostic" \
    "$(awk '/^provider availability:/{p=NR} /^preflight: strict availability/{s=NR} END {print ((p < s) ? "yes" : "no")}' "$T/pf.err")" yes
  assert_grep "the roster still ran with --probe" "$T/rstub.args" '^--probe$'
  assert_nogrep "no summary line on a refusal" "$T/pf.out" '^base='
  RSTUB_EXIT=6 RSTUB_JSON="$(pf_config_roster)" RSTUB_BRIEF='provider availability: configuration rejected before probes' \
    "$PF" > "$T/pf.out" 2> "$T/pf.err"
  assert_eq "permanent config roster preserves status" "$?" 6
  assert_grep "permanent refusal includes provider evidence" "$T/pf.err" \
    '^provider availability: configuration rejected before probes$'
  assert_grep "permanent strict reason is relayed" "$T/pf.err" \
    '^preflight: strict config \(permanent\): invalid codex_models: expected a list$'
  assert_eq "permanent canonical diagnostic is the final line" "$(awk 'NF { line=$0 } END { print line }' "$T/pf.err")" \
    'preflight: strict config (permanent): invalid codex_models: expected a list'
  assert_eq "provider evidence precedes permanent diagnostic" \
    "$(awk '/^provider availability:/{p=NR} /^preflight: strict config/{s=NR} END {print ((p < s) ? "yes" : "no")}' "$T/pf.err")" yes
  assert_nogrep "no summary line on a permanent refusal" "$T/pf.out" '^base='
  RSTUB_EXIT=5 RSTUB_JSON='{"strict_class":"config","strict_reason":"wrong class"}' \
    "$PF" > /dev/null 2> "$T/pf.err"
  assert_eq "mismatched strict metadata is a wrapper error" "$?" 1
  assert_grep "mismatched strict metadata is explained" "$T/pf.err" 'valid matching strict metadata'
  RSTUB_EXIT=6 RSTUB_JSON='{"strict_class":"config"}' "$PF" > /dev/null 2> "$T/pf.err"
  assert_eq "missing strict reason is a wrapper error" "$?" 1
  assert_grep "missing strict reason is explained" "$T/pf.err" 'valid matching strict metadata'
  RSTUB_EXIT=5 RSTUB_JSON='{"strict_class":"availability","strict_reason":"provider unavailable"}' \
    "$PF" > /dev/null 2> "$T/pf.err"
  assert_eq "strict metadata without a roster shape is a wrapper error" "$?" 1
  assert_grep "invalid roster shape is explained" "$T/pf.err" 'valid matching strict metadata'
  # A roster crash outside the strict 5/6 contract fails loudly instead of running seatless.
  RSTUB_EXIT=5 RSTUB_JSON='not json at all' "$PF" > /dev/null 2> "$T/pf.err"; assert_eq "unreadable roster refused" "$?" 1
  assert_grep "says strict metadata could not be validated" "$T/pf.err" 'valid matching strict metadata'
  assert_nogrep "no traceback" "$T/pf.err" 'Traceback'
  RSTUB_EXIT=7 "$PF" > /dev/null 2> "$T/pf.err"; assert_eq "roster crash refused" "$?" 1
  assert_grep "names the roster exit code" "$T/pf.err" 'roster.sh failed \(exit 7\)'
  local D2="$T/pf-bin-noroster"; mkdir -p "$D2"; ln -sf "$SCRIPTS/rev-preflight.sh" "$D2/rev-preflight.sh"
  "$D2/rev-preflight.sh" > /dev/null 2> "$T/pf.err"; assert_eq "missing roster.sh refused" "$?" 1
  assert_grep "blames the roster" "$T/pf.err" 'roster.sh failed'
  # paths with spaces: the pathspec and the changed-file list must not be word-split (git quotes such paths in porcelain v1)
  mkdir -p "my dir"; echo s > "my dir/a note.txt"; git add "my dir/a note.txt"; git commit -qm "feat: spaces"
  echo u > "untracked note.txt"
  "$PF" --write "$T/pf-sp" > "$T/pf.out" 2>&1; assert_eq "space paths ok" "$?" 0
  assert_grep "space path intact" "$T/pf-sp/files.txt" '^my dir/a note\.txt$'
  assert_grep "untracked space path intact" "$T/pf-sp/files.txt" '^untracked note\.txt$'
  assert_nogrep "no quote fragments" "$T/pf-sp/files.txt" '"'
  "$PF" --scope "my dir" > "$T/pf.out" 2>&1; assert_eq "scope with a space ok" "$?" 0
  assert_grep "space scope counts one file" "$T/pf.out" ' scope=my dir changed_files=1$'
  cd "$T" && assert_exit "outside a repo refused" 1 "$PF"
  cd "$old_pwd" 2>/dev/null || cd "$T" || return 1
  PATH=$old_path; export PATH; unset RSTUB_ARGS
}
test_prompt() {
  local S="$T/pr-sess"; mkdir -p "$S"
  printf 'REV_BASE=abc123\nREV_BRANCH=feat\nREV_DEFAULT=main\nREV_ROOT=/repo\nREV_SCOPE=branch\n' > "$S/scope.env"
  printf 'src/x.ts\nsrc/x.test.ts\n' > "$S/files.txt"; echo "build: pass; test: 2 pre-existing failures (a, b); lint: pass" > "$S/baseline.md"
  printf '%s' '{"seats":[{"seat":"grok","adapter":"grok"},{"seat":"codex-sol","adapter":"codex"},{"seat":"codex-terra","adapter":"codex"}]}' > "$S/roster.json"
  local p; p=$("$SCRIPTS/rev-prompt.sh" "$S" 1 grok correctness "Correctness, edge cases, error handling")
  assert_eq "prints path" "$p" "$S/r1-grok.prompt.md"
  assert_grep "grok follows lens ordering before tools" "$p" '^Follow the lens ordering below before using tools\.'
  assert_grep "base sha" "$p" 'Base commit: abc123'
  assert_grep "diff command" "$p" 'git diff abc123'
  assert_grep "files listed" "$p" '^- src/x.test.ts$'
  assert_grep "lens text" "$p" 'off-by-one'
  assert_grep "emphasis" "$p" '^Round emphasis: Correctness, edge cases, error handling$'
  assert_grep "baseline included" "$p" 'pre-existing failures'
  assert_grep "rejected none" "$p" '\(none yet\)'
  assert_nogrep "native-provider schema is not embedded" "$p" '"severity"'
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
  assert_nogrep "no untracked note without untracked.txt" "$p" 'Files marked .untracked.'
  : > "$S/untracked.txt"
  p=$("$SCRIPTS/rev-prompt.sh" "$S" 5 grok correctness "Untracked")
  assert_nogrep "empty untracked.txt renders no file note" "$p" 'Files marked .untracked.'
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
