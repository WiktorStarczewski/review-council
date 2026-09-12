# tests for Task 7 - sourced by run-tests.sh
test_stack() {
  # The body runs in a subshell for env isolation; the runner tallies ok/fail through a results file, so nothing
  # needs to be handed back.
  ( seat_env
    # Portability: every mtime read goes through lib/compat.sh, so the same script runs on macOS and Linux.
    assert_grep "compat.sh is sourced" "$STACK/stack.sh" 'lib/compat\.sh'
    assert_nogrep "no bare BSD stat" "$STACK/stack.sh" 'stat -f'
    assert_nogrep "no bare BSD date" "$STACK/stack.sh" 'date -v'
    # REV_SCRIPTS points at a directory holding roster.sh + the two scripts the orchestrator shells out to.
    # The stack depends on the roster status and brief cause, so the double controls both.
    local RS="$T/rs"; mkdir -p "$RS"
    ln -sf "$SCRIPTS/rev-status.sh" "$RS/rev-status.sh"; ln -sf "$SCRIPTS/rev-squash.sh" "$RS/rev-squash.sh"
    # lib/ comes along: the copy must run in the shipped configuration, portability layer and all, or the
    # REV_SCRIPTS-default case below would exercise a stack.sh whose compat.sh never loaded.
    ln -sfn "$SCRIPTS/lib" "$RS/lib"
    cp "$STACK/stack.sh" "$RS/stack.sh"
    cat > "$RS/roster.sh" <<'RSEOF'
#!/bin/bash
printf '%s\n' "$@" >> "${FAKE_ROSTER_ARGS:-/dev/null}"
case "${FAKE_ROSTER_RC:-0}" in
  5) echo "review-council seats: codex x unavailable | STRICT availability: configured Codex seat did not survive probe";;
  6) echo "review-council seats: codex x invalid | STRICT config: codex_models must be a list";;
  *) echo "review-council seats: codex ok | grok ok | gemini x not installed | claude ok";;
esac
exit "${FAKE_ROSTER_RC:-0}"
RSEOF
    chmod +x "$RS/roster.sh"
    export REV_SCRIPTS="$RS" FAKE_ROSTER_ARGS="$T/roster-args"
    export SHIM_CLAUDE_ARGS_FILE="$T/claude-args" REV_STACK_FOREGROUND=1
    local R="$T/stk"; mkrepo "$R"; git -C "$R" checkout -qb feat; echo w > "$R/w.txt"; git -C "$R" add w.txt; git -C "$R" commit -qm "feat: w"
    printf 'legs() { run_leg "%s" 1 leg1 "premise one"; }\n' "$R" > "$T/stack.cfg"
    export ROOT="$T/stack-root" LOG="$T/stack.log" POLL=1 STATUS_EVERY=2 STALL_SECS=30 CPU_SAMPLE_SECS=1 \
           INFRA_SLEEP_SECS=1 FAST_FAIL_SECS=1 AUTH_WAIT_SECS=1 NO_PUSH=1 PASSES=2
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack.out" 2>&1; assert_eq "stack ok exit" "$?" 0
    assert_grep "pass 1 done" "$LOG" '=== DONE leg1 pass1 exit=0'
    assert_grep "pass 2 done" "$LOG" '=== DONE leg1 pass2 exit=0'
    assert_grep "status line" "$LOG" '\[status\] leg1 pass[12] attempt1 \| r.* \| idle=[0-9]+s cpu='
    assert_grep "auth gate asks the roster" "$T/roster-args" '^--brief$'
    assert_nogrep "roster brief is not echoed" "$T/stack.out" 'review-council seats:'
    assert_grep "leg marked stack" "$T/claude-args" '^REV_STACK_LEG=1$'
    assert_grep "leg runs in the repo" "$T/claude-args" "^cwd=$R$"
    assert_grep "bypass permissions" "$T/claude-args" '^bypassPermissions$'
    assert_grep "stream-json" "$T/claude-args" '^stream-json$'
    assert_grep "effort max" "$T/claude-args" '^max$'
    assert_grep "leg invokes the namespaced skill" "$T/claude-args" '^/review-council:rev branch 1 - use '
    assert_nogrep "no bare /rev invocation" "$T/claude-args" '^/rev branch'
    assert_grep "session dir passed" "$T/claude-args" "use $ROOT/leg1 as the session dir"
    assert_grep "premise passed" "$T/claude-args" 'premise one'
    assert_grep "resume hint on pass 2" "$T/claude-args" "Read $ROOT/leg1/findings.md FIRST"
    assert_grep "report written" "$ROOT/leg1/report.md" 'report'
    assert_grep "phase 2 skipped when unset" "$LOG" 'PHASE 2 skipped'
    assert_grep "phase 3 skipped when unset" "$LOG" 'PHASE 3 skipped'
    assert_grep "finish runs squash" "$LOG" 'review commit\(s\) at tip'
    assert_grep "no push honoured" "$LOG" 'NO_PUSH=1'
    assert_grep "all complete" "$LOG" 'ALL PHASES COMPLETE'
    assert_exit "REV_STACK_LEG refuses" 1 env REV_STACK_LEG=1 "$STACK/stack.sh" "$T/stack.cfg"
    assert_exit "REV_ACTIVE refuses" 1 env REV_ACTIVE=1 "$STACK/stack.sh" "$T/stack.cfg"
    assert_exit "missing config refuses" 1 "$STACK/stack.sh"
    # default = detach: returns at once, names the log, and the detached run completes on its own
    ( unset REV_STACK_FOREGROUND; export ROOT="$T/stack-root-d" LOG="$T/stack-d.log"; SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > "$T/detach.out" 2>&1; echo "rc=$?" >> "$T/detach.out" )
    assert_grep "detach returns immediately" "$T/detach.out" '^stack: detached \(pid [0-9]+\), session root .* log .*stack-d.log'
    assert_grep "detach exit 0" "$T/detach.out" '^rc=0$'
    for i in $(seq 1 60); do grep -q "ALL PHASES COMPLETE" "$T/stack-d.log" 2>/dev/null && break; sleep 1; done
    assert_grep "detached run completed on its own" "$T/stack-d.log" 'ALL PHASES COMPLETE'
    assert_grep "detached orchestrator output captured" "$T/stack-root-d/orchestrator.out" '=== DONE leg1 pass1'
    assert_eq "detached run is in its own session" "$(grep -c 'refusing to nest' "$T/stack-root-d/orchestrator.out")" "0"
    # resume: a second run with the same LOG *and* the same ROOT skips legs already DONE
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "resume skips done legs" "$LOG" '=== SKIP leg1 pass1'
    # …but a different stack sharing that LOG must not: fresh ROOT, same label, nothing may be skipped
    ( export ROOT="$T/stack-root-b"
      SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > /dev/null 2>&1 )
    assert_eq "fresh root never skips" "$(grep -c '=== SKIP leg1' "$LOG" | tr -d ' ')" "2"
    # stall: a hung leg is killed after STALL_SECS with a frozen CPU, is NOT treated as infra, gives up after
    # MAX_ATTEMPTS. FAST_FAIL_SECS must exceed the run's duration, or the infra branch is unreachable anyway and
    # "not misread as infra" would pass even with the stall guard deleted.
    export ROOT="$T/stack-root2" LOG="$T/stack2.log" STALL_SECS=4 MAX_ATTEMPTS=1 PASSES=1 FAST_FAIL_SECS=60
    local t0; t0=$(date +%s)
    SHIM_MODE=hang "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack2.out" 2>&1; local hrc=$?
    local dt=$(( $(date +%s) - t0 ))
    # a stack whose leg never completed must NOT report a clean finish
    assert_eq "failed leg exits non-zero" "$hrc" 1
    assert_grep "failure named in the verdict" "$LOG" 'COMPLETE WITH FAILURES: leg1'
    assert_nogrep "no false ALL PHASES COMPLETE" "$LOG" 'ALL PHASES COMPLETE'
    assert_grep "the failed leg's repo is not squashed" "$LOG" 'skipping .* a leg on it failed'
    assert_grep "stall detected" "$LOG" 'STALLED \([0-9]+s idle, cpu frozen'
    assert_grep "gave up" "$LOG" 'GAVE UP on leg1'
    assert_nogrep "stall not misread as infra" "$LOG" 'infrastructure'
    [ "$dt" -lt 60 ] && ok "stall path fast (${dt}s)" || fail "stall path fast" "${dt}s"
    assert_eq "hung leg killed" "$(pgrep -f 'sleep 3599' | wc -l | tr -d ' ')" "0"
    # fast failure is infra: retried after INFRA_SLEEP_SECS, then attempts count.
    # FAST_FAIL_SECS must exceed POLL: the watch loop always sleeps one POLL before reaping, so dur >= POLL.
    export ROOT="$T/stack-root3" LOG="$T/stack3.log" MAX_INFRA_RETRIES=1 MAX_ATTEMPTS=1 FAST_FAIL_SECS=5
    SHIM_MODE=fail "$STACK/stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "fast fail treated as infra once" "$LOG" 'failed in [0-9]+s - infrastructure'
    assert_grep "then gives up" "$LOG" 'GAVE UP on leg1'
    # exit 0 without report.md is NOT done: retried with resume, then gives up
    export ROOT="$T/stack-root4" LOG="$T/stack4.log" MAX_ATTEMPTS=2 MAX_INFRA_RETRIES=0 FAST_FAIL_SECS=1
    SHIM_MODE=noreport "$STACK/stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "incomplete leg detected" "$LOG" 'invalid completion receipt \(report.md is missing\)'
    assert_nogrep "incomplete leg never marked DONE" "$LOG" '=== DONE leg1'
    assert_eq "incomplete leg retried up to MAX_ATTEMPTS" "$(grep -c '=== START leg1 pass1' "$LOG")" "2"
    assert_grep "incomplete leg gives up" "$LOG" 'GAVE UP on leg1'
    # Empty, symlinked, and non-terminal reports are not completion receipts.
    printf '%s\n' '# unrelated file' > "$T/external-report.md"
    export SHIM_REPORT_TARGET="$T/external-report.md" MAX_ATTEMPTS=1
    for report_mode in emptyreport symlinkreport nodonestate; do
      export ROOT="$T/stack-root-$report_mode" LOG="$T/stack-$report_mode.log"
      SHIM_MODE="$report_mode" "$STACK/stack.sh" "$T/stack.cfg" > /dev/null 2>&1
      assert_grep "$report_mode receipt is rejected" "$LOG" 'invalid completion receipt'
      assert_nogrep "$report_mode never marks DONE" "$LOG" '=== DONE leg1'
      assert_nogrep "$report_mode never finalizes" "$LOG" 'ALL PHASES COMPLETE'
    done
    # A10 - a leg that goes quiet past STALL_SECS and then finishes during the CPU sample must not be killed
    export ROOT="$T/stack-root5" LOG="$T/stack5.log" STALL_SECS=4 CPU_SAMPLE_SECS=3 POLL=1 \
           MAX_ATTEMPTS=1 MAX_INFRA_RETRIES=0 PASSES=1 FAST_FAIL_SECS=1
    SHIM_MODE=slowstart "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack5.out" 2>&1
    assert_eq "slow-starting leg exits 0" "$?" 0
    assert_nogrep "a leg that ends inside the cpu sample is not killed" "$LOG" 'STALLED'
    assert_grep "the race is logged" "$LOG" 'finished during the [0-9]+s cpu sample - not killing'
    assert_grep "slow-starting leg recorded DONE" "$LOG" '=== DONE leg1 pass1 exit=0'
    # The file-activity half of the two-condition kill rule, which reads mtimes through lib/compat.sh: run.log
    # is silent (SHIM_MODE=hang never speaks again) but the session dir keeps being written, so the leg must NOT
    # be killed. Stub rc_mtime/rc_newest_mtime out and this is the only case that goes red.
    export ROOT="$T/stack-root9" LOG="$T/stack9.log" STALL_SECS=6 CPU_SAMPLE_SECS=1 POLL=1 \
           MAX_ATTEMPTS=1 MAX_INFRA_RETRIES=0 PASSES=1 FAST_FAIL_SECS=1 STATUS_EVERY=600
    mkdir -p "$ROOT/leg1"
    ( for _ in $(seq 1 40); do touch "$ROOT/leg1/heartbeat"; sleep 1; done ) & local toucher=$!
    SHIM_MODE=hang "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack9.out" 2>&1 & local spid=$!
    sleep 15
    # Teardown is scoped to THIS stack's leg group - never a machine-wide pgrep, which would reach another
    # run of this suite on the same box. A group kill is only ever aimed at a child that LEADS its own group:
    # stack.sh runs each leg under `set -m`, so the leg is a group leader (pgid == pid), while the orchestrator's
    # other children (the poll `sleep`, a squash pipeline) inherit the TEST RUNNER's group - negating one of
    # those would SIGKILL this suite and everything else in its group. Never compare a pgid to $$: run-tests.sh
    # inherits its group rather than leading one whenever it is launched from a non-interactive parent, so that
    # test is inert.
    local kids child cgid; kids=$(pgrep -P "$spid" 2>/dev/null)
    kill -9 "$spid" 2>/dev/null; kill -9 "$toucher" 2>/dev/null
    for child in $kids; do
      cgid=$(ps -o pgid= -p "$child" 2>/dev/null | tr -d ' ')
      [ -n "$cgid" ] && [ "$cgid" = "$child" ] && kill -9 "-$cgid" 2>/dev/null
    done
    wait "$spid" 2>/dev/null; wait "$toucher" 2>/dev/null
    assert_grep "the quiet-but-active leg was watched" "$LOG" '=== START leg1 pass1'
    assert_nogrep "session-dir activity keeps a silent leg alive" "$LOG" 'STALLED'
    # A retryable availability refusal waits, then gives up without starting the leg.
    export ROOT="$T/stack-root6" LOG="$T/stack6.log" STALL_SECS=30 AUTH_WAIT_TRIES=2 AUTH_WAIT_SECS=0
    FAKE_ROSTER_RC=5 SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack6.out" 2>&1
    assert_eq "under-seated stack exits non-zero" "$?" 1
    assert_grep "availability wait retries then gives up" "$LOG" 'reviewer availability not ready \(2/2\)'
    assert_eq "availability cause is logged for every retry" \
      "$(grep -c 'reviewer availability not ready.*STRICT availability: configured Codex seat did not survive probe' "$LOG")" 2
    assert_grep "leg skipped for availability" "$LOG" 'reviewer availability never recovered; skipping'
    assert_grep "final availability failure keeps the cause" "$LOG" \
      'reviewer availability never recovered; skipping: .*STRICT availability: configured Codex seat did not survive probe'
    assert_grep "auth failure reaches the verdict" "$LOG" 'COMPLETE WITH FAILURES: leg1'
    assert_nogrep "no leg ever started" "$LOG" '=== START leg1'
    export ROOT="$T/stack-root6-config" LOG="$T/stack6-config.log"
    rm -f "$T/roster-args-config"; export FAKE_ROSTER_ARGS="$T/roster-args-config"
    FAKE_ROSTER_RC=6 SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack6-config.out" 2>&1
    assert_eq "permanent roster failure exits nonzero" "$?" 1
    assert_eq "permanent roster failure is checked once" \
      "$(grep -c '^--brief$' "$T/roster-args-config")" 1
    assert_grep "permanent failure keeps its cause" "$LOG" \
      'roster configuration is invalid; skipping: .*STRICT config: codex_models must be a list'
    assert_nogrep "permanent failure is not retried" "$LOG" 'reviewer availability not ready'
    export ROOT="$T/stack-root6-error" LOG="$T/stack6-error.log"
    rm -f "$T/roster-args-error"; export FAKE_ROSTER_ARGS="$T/roster-args-error"
    FAKE_ROSTER_RC=1 SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack6-error.out" 2>&1
    assert_eq "local roster error exits nonzero" "$?" 1
    assert_eq "local roster error is checked once" \
      "$(grep -c '^--brief$' "$T/roster-args-error")" 1
    assert_grep "local roster error uses its own branch" "$LOG" 'roster check failed \(exit 1\); skipping:'
    assert_nogrep "local roster error is not retried" "$LOG" 'reviewer availability not ready'
    export FAKE_ROSTER_ARGS="$T/roster-args"
    # A7 - a refused squash must not swallow the push: they are independent steps
    local R2="$T/stk2"; mkrepo "$R2"; git -C "$R2" checkout -qb feat
    git init -q --bare "$T/stk2-remote.git"; git -C "$R2" remote add origin "$T/stk2-remote.git"
    for i in 1 2; do echo "$i" > "$R2/r$i.txt"; git -C "$R2" add "r$i.txt"; git -C "$R2" commit -qm "fix(rev): round $i - pushed"; done
    git -C "$R2" push -q -u origin feat
    printf 'legs() { run_leg "%s" 1 leg2 "premise two"; }\n' "$R2" > "$T/stack-b.cfg"
    export ROOT="$T/stack-root7" LOG="$T/stack7.log"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-b.cfg" > "$T/stack7.out" 2>&1
    assert_eq "a refused squash does not fail the stack" "$?" 0
    assert_grep "squash refusal is logged" "$LOG" '!!! squash refused for stk2'
    assert_grep "refusal explains itself" "$LOG" 'only 0 unpushed'
    assert_grep "the push step still runs" "$LOG" 'NO_PUSH=1: not pushing'
    assert_grep "complete despite the refusal" "$LOG" 'ALL PHASES COMPLETE'
    # REV_SCRIPTS defaults to the script's own directory: the copy in $RS finds roster/status/squash beside it
    # with nothing in the environment pointing there.
    ( unset REV_SCRIPTS
      export ROOT="$T/stack-root8" LOG="$T/stack8.log" FAKE_ROSTER_ARGS="$T/roster-args-sibling"
      SHIM_MODE=ok "$RS/stack.sh" "$T/stack.cfg" > "$T/stack8.out" 2>&1 )
    assert_grep "runs with no REV_SCRIPTS set" "$T/stack8.log" 'ALL PHASES COMPLETE'
    assert_grep "the sibling roster is the default" "$T/roster-args-sibling" '^--brief$'
    assert_grep "the sibling squash is the default" "$T/stack8.log" 'review commit\(s\) at tip'
  )
}

test_stack_real_roster_strict_classes() {
  ( seat_env
    local R="$T/stack-real-roster"; mkrepo "$R"
    git -C "$R" checkout -qb feat; echo w > "$R/w.txt"; git -C "$R" add w.txt
    git -C "$R" commit -qm "feat: w"
    printf 'legs() { run_leg "%s" 1 leg1 "premise"; }\n' "$R" > "$T/stack-real.cfg"
    export REV_STACK_FOREGROUND=1 REV_SCRIPTS="$SCRIPTS" SHIM_CLAUDE_ARGS_FILE="$T/unused-claude-args"
    export POLL=1 STATUS_EVERY=30 STALL_SECS=30 CPU_SAMPLE_SECS=1 INFRA_SLEEP_SECS=0
    export FAST_FAIL_SECS=1 AUTH_WAIT_TRIES=2 AUTH_WAIT_SECS=0 NO_PUSH=1 PASSES=1
    export HOME="$T/stack-real-home" PATH="/usr/bin:/bin:/usr/sbin:/sbin"
    mkdir -p "$HOME"

    printf '%s' '{"codex_models":"gpt-5.6-sol"}' > "$T/stack-invalid-roster.json"
    export REVIEW_COUNCIL_CONFIG="$T/stack-invalid-roster.json"
    export ROOT="$T/stack-real-config-root" LOG="$T/stack-real-config.log"
    "$STACK/stack.sh" "$T/stack-real.cfg" > "$T/stack-real-config.out" 2>&1
    assert_eq "real roster config refusal fails the stack" "$?" 1
    assert_grep "permanent config fails immediately" "$LOG" 'roster configuration is invalid; skipping'
    assert_grep "real permanent failure logs its canonical cause" "$LOG" \
      'STRICT config: invalid codex_models:'
    assert_nogrep "permanent config never enters availability wait" "$LOG" 'reviewer availability not ready'
    assert_nogrep "permanent config never starts a leg" "$LOG" '=== START leg1'

    printf '%s' '{"codex_models":["gpt-5.6-sol"]}' > "$T/stack-unavailable-roster.json"
    export REVIEW_COUNCIL_CONFIG="$T/stack-unavailable-roster.json"
    export ROOT="$T/stack-real-availability-root" LOG="$T/stack-real-availability.log"
    "$STACK/stack.sh" "$T/stack-real.cfg" > "$T/stack-real-availability.out" 2>&1
    assert_eq "real roster availability refusal fails after waiting" "$?" 1
    assert_grep "availability retries to its bound" "$LOG" 'reviewer availability not ready \(2/2\)'
    assert_grep "real availability retry logs its canonical cause" "$LOG" \
      'STRICT availability: codex_models requires 1 matching seat\(s\), 0 survived'
    assert_grep "availability failure names recovery" "$LOG" 'reviewer availability never recovered; skipping'
    assert_nogrep "unavailable roster never starts a leg" "$LOG" '=== START leg1'
  )
}
test_stack_status_never_blank() {
  ( seat_env; export REV_STACK_FOREGROUND=1 SHIM_CLAUDE_ARGS_FILE="$T/claude-args-sb"
    local R="$T/stk-sb"; mkrepo "$R"; git -C "$R" checkout -qb feat; echo w > "$R/w.txt"; git -C "$R" add w.txt; git -C "$R" commit -qm "feat: w"
    # a rev-status.sh that prints nothing and fails must not blank the status line
    local D="$T/scripts-sb"; mkdir -p "$D"; cp "$SCRIPTS"/*.sh "$D"/; cp -R "$SCRIPTS/lib" "$D"/; printf '#!/bin/bash\necho "boom" >&2; exit 1\n' > "$D/rev-status.sh"; chmod +x "$D/rev-status.sh"
    printf 'legs() { run_leg "%s" 1 leg1 "premise"; }\n' "$R" > "$T/stack-sb.cfg"
    export REV_SCRIPTS="$D" ROOT="$T/stack-root-sb" LOG="$T/stack-sb.log" POLL=1 STATUS_EVERY=1 STALL_SECS=30 CPU_SAMPLE_SECS=1 INFRA_SLEEP_SECS=1 FAST_FAIL_SECS=1 AUTH_WAIT_SECS=1 NO_PUSH=1 PASSES=1
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-sb.cfg" > /dev/null 2>&1
    assert_grep "blank status is reported, not dropped" "$LOG" '\[status\] leg1 pass1 attempt1 \| \(status unavailable - see .*status.err\) \| idle='
    assert_grep "rev-status stderr is kept" "$ROOT/status.err" '^boom$'
  )
}

test_stack_report_is_attempt_local() {
  ( seat_env
    local D="$T/attempt-scripts" B="$T/attempt-bin" R="$T/attempt-repo"
    mkdir -p "$D" "$B"
    cp "$STACK/stack.sh" "$D/stack.sh"
    cp -R "$SCRIPTS/lib" "$D/lib"
    mkdir -p "$T/codex-skills/rev"
    cp "$SK/codex-skills/rev/SKILL.md" "$T/codex-skills/rev/SKILL.md"
    cat > "$D/roster.sh" <<'SH'
#!/bin/bash
echo 'review-council seats: fixture'
SH
    cat > "$D/rev-status.sh" <<'SH'
#!/bin/bash
echo 'fixture ready'
SH
    cat > "$D/rev-squash.sh" <<'SH'
#!/bin/bash
echo 'unexpected squash'
SH
    chmod +x "$D"/*.sh
    cat > "$B/review-leg" <<'SH'
#!/bin/bash
prompt=
if [ "$(basename "$0")" = claude ]; then
  previous=
  for argument in "$@"; do
    [ "$previous" = -p ] && prompt=$argument
    previous=$argument
  done
else
  prompt=$(cat)
fi
session=$(printf '%s\n' "$prompt" | sed -n 's/.*use \([^ ]*\) as the session dir.*/\1/p' | head -1)
mkdir -p "$session"
count=0
[ ! -f "$ATTEMPT_COUNT" ] || count=$(cat "$ATTEMPT_COUNT")
count=$((count + 1))
printf '%s\n' "$count" > "$ATTEMPT_COUNT"
printf 'command=%s pass=%s count=%s session=%s\n' "$(basename "$0")" "${PASS:-}" "$count" "$session" >> "$ATTEMPT_COUNT.trace"
case "$STALE_REPORT_MODE" in
  later-pass)
    if [ "${PASS:-}" = 1 ]; then
      echo '# pass 1 report' > "$session/report.md"
      echo '# findings' > "$session/findings.md"
    fi
    exit 0
    ;;
  retry)
    if [ "$count" = 1 ]; then
      echo '# failed attempt report' > "$session/report.md"
      echo '# findings' > "$session/findings.md"
      exit 1
    fi
    exit 0
    ;;
esac
exit 2
SH
    chmod +x "$B/review-leg"
    ln -s review-leg "$B/claude"
    ln -s review-leg "$B/codex"
    mkrepo "$R"
    git -C "$R" checkout -qb feat
    echo changed > "$R/changed.txt"
    git -C "$R" add changed.txt
    git -C "$R" commit -qm 'feat: changed'
    printf 'legs() { run_leg "%s" 1 leg "premise"; }\n' "$R" > "$T/attempt-stack.cfg"
    export PATH="$B:$PATH" REV_STACK_FOREGROUND=1 REV_SCRIPTS="$D" POLL=1
    export STATUS_EVERY=600 STALL_SECS=30 CPU_SAMPLE_SECS=1 FAST_FAIL_SECS=0
    export MAX_INFRA_RETRIES=0 NO_PUSH=1 NO_SQUASH=1

    local host rc
    for host in claude codex; do
      export REVIEW_COUNCIL_HOST=$host PASSES=2 MAX_ATTEMPTS=1
      export ROOT="$T/attempt-$host-pass" LOG="$T/attempt-$host-pass.log"
      export ATTEMPT_COUNT="$T/attempt-$host-pass.count" STALE_REPORT_MODE=later-pass
      "$D/stack.sh" "$T/attempt-stack.cfg" > "$T/attempt-$host-pass.out" 2>&1
      rc=$?
      assert_eq "$host later pass rejects a stale report" "$rc" 1
      assert_nogrep "$host later pass is never certified" "$LOG" '=== DONE leg pass2'
      assert_grep "$host later pass invokes both attempts" "$ATTEMPT_COUNT.trace" 'count=2 '
      assert_grep "$host later pass archives the prior report" "$ROOT/leg/report.pass2.attempt1.previous.md" 'pass 1 report'

      export PASSES=1 MAX_ATTEMPTS=2 ROOT="$T/attempt-$host-retry" LOG="$T/attempt-$host-retry.log"
      export ATTEMPT_COUNT="$T/attempt-$host-retry.count" STALE_REPORT_MODE=retry
      "$D/stack.sh" "$T/attempt-stack.cfg" > "$T/attempt-$host-retry.out" 2>&1
      rc=$?
      assert_eq "$host retry rejects a stale report" "$rc" 1
      assert_nogrep "$host retry is never certified" "$LOG" '=== DONE leg pass1'
      assert_grep "$host retry invokes both attempts" "$ATTEMPT_COUNT.trace" 'count=2 '
      assert_grep "$host retry archives the failed attempt report" "$ROOT/leg/report.pass1.attempt2.previous.md" 'failed attempt report'
    done
  )
}
