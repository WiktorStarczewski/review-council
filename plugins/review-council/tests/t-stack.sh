# tests for Task 7 — sourced by run-tests.sh
test_stack() {
  # The body runs in a subshell for env isolation; the runner tallies ok/fail through a results file, so nothing
  # needs to be handed back.
  ( seat_env
    # Portability: every mtime read goes through lib/compat.sh, so the same script runs on macOS and Linux.
    assert_grep "compat.sh is sourced" "$STACK/stack.sh" 'lib/compat\.sh'
    assert_nogrep "no bare BSD stat" "$STACK/stack.sh" 'stat -f'
    assert_nogrep "no bare BSD date" "$STACK/stack.sh" 'date -v'
    # REV_SCRIPTS points at a directory holding roster.sh + the two scripts the orchestrator shells out to.
    # roster.sh is Task 2's; the stack only depends on its exit code, so a double with a switchable code is
    # the whole contract under test (and keeps this suite independent of that task's progress).
    local RS="$T/rs"; mkdir -p "$RS"
    ln -sf "$SCRIPTS/rev-status.sh" "$RS/rev-status.sh"; ln -sf "$SCRIPTS/rev-squash.sh" "$RS/rev-squash.sh"
    # lib/ comes along: the copy must run in the shipped configuration, portability layer and all, or the
    # REV_SCRIPTS-default case below would exercise a stack.sh whose compat.sh never loaded.
    ln -sfn "$SCRIPTS/lib" "$RS/lib"
    cp "$STACK/stack.sh" "$RS/stack.sh"
    cat > "$RS/roster.sh" <<'RSEOF'
#!/bin/bash
printf '%s\n' "$@" >> "${FAKE_ROSTER_ARGS:-/dev/null}"
echo "review-council seats: codex ✓ · grok ✓ · gemini ✗ not installed · claude ✓"
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
    assert_grep "leg invokes the namespaced skill" "$T/claude-args" '^/review-council:rev branch 1 — use '
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
    assert_grep "fast fail treated as infra once" "$LOG" 'failed in [0-9]+s — infrastructure'
    assert_grep "then gives up" "$LOG" 'GAVE UP on leg1'
    # exit 0 without report.md is NOT done: retried with resume, then gives up
    export ROOT="$T/stack-root4" LOG="$T/stack4.log" MAX_ATTEMPTS=2 MAX_INFRA_RETRIES=0 FAST_FAIL_SECS=1
    SHIM_MODE=noreport "$STACK/stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "incomplete leg detected" "$LOG" 'exited 0 after [0-9]+s but wrote no report.md — incomplete'
    assert_nogrep "incomplete leg never marked DONE" "$LOG" '=== DONE leg1'
    assert_eq "incomplete leg retried up to MAX_ATTEMPTS" "$(grep -c '=== START leg1 pass1' "$LOG")" "2"
    assert_grep "incomplete leg gives up" "$LOG" 'GAVE UP on leg1'
    # A10 — a leg that goes quiet past STALL_SECS and then finishes during the CPU sample must not be killed
    export ROOT="$T/stack-root5" LOG="$T/stack5.log" STALL_SECS=4 CPU_SAMPLE_SECS=3 POLL=1 \
           MAX_ATTEMPTS=1 MAX_INFRA_RETRIES=0 PASSES=1 FAST_FAIL_SECS=1
    SHIM_MODE=slowstart "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack5.out" 2>&1
    assert_eq "slow-starting leg exits 0" "$?" 0
    assert_nogrep "a leg that ends inside the cpu sample is not killed" "$LOG" 'STALLED'
    assert_grep "the race is logged" "$LOG" 'finished during the [0-9]+s cpu sample — not killing'
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
    # Teardown is scoped to THIS stack's leg group — never a machine-wide pgrep, which would reach another
    # run of this suite on the same box. A group kill is only ever aimed at a child that LEADS its own group:
    # stack.sh runs each leg under `set -m`, so the leg is a group leader (pgid == pid), while the orchestrator's
    # other children (the poll `sleep`, a squash pipeline) inherit the TEST RUNNER's group — negating one of
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
    # A8 — a refusing roster (exit 5 — since Task 11, strict mode's `min_labs` floor) means the leg never
    # starts. The stack owns no sign-in logic of its own; the roster's exit code is the entire gate.
    export ROOT="$T/stack-root6" LOG="$T/stack6.log" STALL_SECS=30 AUTH_WAIT_TRIES=2 AUTH_WAIT_SECS=0
    FAKE_ROSTER_RC=5 SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack6.out" 2>&1
    assert_eq "under-seated stack exits non-zero" "$?" 1
    assert_grep "auth wait retries then gives up" "$LOG" 'auth not ready \(2/2\)'
    assert_grep "leg skipped for auth" "$LOG" 'auth never came back; skipping'
    assert_grep "auth failure reaches the verdict" "$LOG" 'COMPLETE WITH FAILURES: leg1'
    assert_nogrep "no leg ever started" "$LOG" '=== START leg1'
    # A7 — a refused squash must not swallow the push: they are independent steps
    local R2="$T/stk2"; mkrepo "$R2"; git -C "$R2" checkout -qb feat
    git init -q --bare "$T/stk2-remote.git"; git -C "$R2" remote add origin "$T/stk2-remote.git"
    for i in 1 2; do echo "$i" > "$R2/r$i.txt"; git -C "$R2" add "r$i.txt"; git -C "$R2" commit -qm "fix(rev): round $i — pushed"; done
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
