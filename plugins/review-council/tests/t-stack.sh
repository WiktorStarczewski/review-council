# tests for Task 9 — sourced by run-tests.sh
test_stack() {
  # The body runs in a subshell for env isolation; the runner tallies ok/fail through a results file, so nothing
  # needs to be handed back.
  ( seat_env; export REV_SCRIPTS="$SCRIPTS" SHIM_CLAUDE_ARGS_FILE="$T/claude-args" REV_STACK_FOREGROUND=1
    local R="$T/stk"; mkrepo "$R"; git -C "$R" checkout -qb feat; echo w > "$R/w.txt"; git -C "$R" add w.txt; git -C "$R" commit -qm "feat: w"
    printf 'legs() { run_leg "%s" 1 leg1 "premise one"; }\n' "$R" > "$T/stack.cfg"
    export ROOT="$T/stack-root" LOG="$T/stack.log" POLL=1 STATUS_EVERY=2 STALL_SECS=30 CPU_SAMPLE_SECS=1 \
           INFRA_SLEEP_SECS=1 FAST_FAIL_SECS=1 AUTH_WAIT_SECS=1 NO_PUSH=1 PASSES=2
    SHIM_MODE=ok "$STACK/rev-stack.sh" "$T/stack.cfg" > "$T/stack.out" 2>&1; assert_eq "stack ok exit" "$?" 0
    assert_grep "pass 1 done" "$LOG" '=== DONE leg1 pass1 exit=0'
    assert_grep "pass 2 done" "$LOG" '=== DONE leg1 pass2 exit=0'
    assert_grep "status line" "$LOG" '\[status\] leg1 pass[12] attempt1 \| r.* \| idle=[0-9]+s cpu='
    assert_grep "leg marked stack" "$T/claude-args" '^REV_STACK_LEG=1$'
    assert_grep "leg runs in the repo" "$T/claude-args" "^cwd=$R$"
    assert_grep "bypass permissions" "$T/claude-args" '^bypassPermissions$'
    assert_grep "stream-json" "$T/claude-args" '^stream-json$'
    assert_grep "effort max" "$T/claude-args" '^max$'
    assert_grep "session dir passed" "$T/claude-args" "use $ROOT/leg1 as the session dir"
    assert_grep "premise passed" "$T/claude-args" 'premise one'
    assert_grep "resume hint on pass 2" "$T/claude-args" "Read $ROOT/leg1/findings.md FIRST"
    assert_grep "report written" "$ROOT/leg1/report.md" 'report'
    assert_grep "phase 2 skipped when unset" "$LOG" 'PHASE 2 skipped'
    assert_grep "phase 3 skipped when unset" "$LOG" 'PHASE 3 skipped'
    assert_grep "finish runs squash" "$LOG" 'review commit\(s\) at tip'
    assert_grep "no push honoured" "$LOG" 'NO_PUSH=1'
    assert_grep "all complete" "$LOG" 'ALL PHASES COMPLETE'
    assert_exit "REV_STACK_LEG refuses" 1 env REV_STACK_LEG=1 "$STACK/rev-stack.sh" "$T/stack.cfg"
    assert_exit "REV_ACTIVE refuses" 1 env REV_ACTIVE=1 "$STACK/rev-stack.sh" "$T/stack.cfg"
    assert_exit "missing config refuses" 1 "$STACK/rev-stack.sh"
    # default = detach: returns at once, names the log, and the detached run completes on its own
    ( unset REV_STACK_FOREGROUND; export ROOT="$T/stack-root-d" LOG="$T/stack-d.log"; SHIM_MODE=ok "$STACK/rev-stack.sh" "$T/stack.cfg" > "$T/detach.out" 2>&1; echo "rc=$?" >> "$T/detach.out" )
    assert_grep "detach returns immediately" "$T/detach.out" '^rev-stack: detached \(pid [0-9]+\), session root .* log .*stack-d.log'
    assert_grep "detach exit 0" "$T/detach.out" '^rc=0$'
    for i in $(seq 1 60); do grep -q "ALL PHASES COMPLETE" "$T/stack-d.log" 2>/dev/null && break; sleep 1; done
    assert_grep "detached run completed on its own" "$T/stack-d.log" 'ALL PHASES COMPLETE'
    assert_grep "detached orchestrator output captured" "$T/stack-root-d/orchestrator.out" '=== DONE leg1 pass1'
    assert_eq "detached run is in its own session" "$(grep -c 'refusing to nest' "$T/stack-root-d/orchestrator.out")" "0"
    # resume: a second run with the same LOG *and* the same ROOT skips legs already DONE
    SHIM_MODE=ok "$STACK/rev-stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "resume skips done legs" "$LOG" '=== SKIP leg1 pass1'
    # …but a different stack sharing that LOG must not: fresh ROOT, same label, nothing may be skipped
    ( export ROOT="$T/stack-root-b"
      SHIM_MODE=ok "$STACK/rev-stack.sh" "$T/stack.cfg" > /dev/null 2>&1 )
    assert_eq "fresh root never skips" "$(grep -c '=== SKIP leg1' "$LOG" | tr -d ' ')" "2"
    # stall: a hung leg is killed after STALL_SECS with a frozen CPU, is NOT treated as infra, gives up after
    # MAX_ATTEMPTS. FAST_FAIL_SECS must exceed the run's duration, or the infra branch is unreachable anyway and
    # "not misread as infra" would pass even with the stall guard deleted.
    export ROOT="$T/stack-root2" LOG="$T/stack2.log" STALL_SECS=4 MAX_ATTEMPTS=1 PASSES=1 FAST_FAIL_SECS=60
    local t0; t0=$(date +%s)
    SHIM_MODE=hang "$STACK/rev-stack.sh" "$T/stack.cfg" > "$T/stack2.out" 2>&1; local hrc=$?
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
    SHIM_MODE=fail "$STACK/rev-stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "fast fail treated as infra once" "$LOG" 'failed in [0-9]+s — infrastructure'
    assert_grep "then gives up" "$LOG" 'GAVE UP on leg1'
    # exit 0 without report.md is NOT done: retried with resume, then gives up
    export ROOT="$T/stack-root4" LOG="$T/stack4.log" MAX_ATTEMPTS=2 MAX_INFRA_RETRIES=0 FAST_FAIL_SECS=1
    SHIM_MODE=noreport "$STACK/rev-stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "incomplete leg detected" "$LOG" 'exited 0 after [0-9]+s but wrote no report.md — incomplete'
    assert_nogrep "incomplete leg never marked DONE" "$LOG" '=== DONE leg1'
    assert_eq "incomplete leg retried up to MAX_ATTEMPTS" "$(grep -c '=== START leg1 pass1' "$LOG")" "2"
    assert_grep "incomplete leg gives up" "$LOG" 'GAVE UP on leg1'
    # A10 — a leg that goes quiet past STALL_SECS and then finishes during the CPU sample must not be killed
    export ROOT="$T/stack-root5" LOG="$T/stack5.log" STALL_SECS=4 CPU_SAMPLE_SECS=3 POLL=1 \
           MAX_ATTEMPTS=1 MAX_INFRA_RETRIES=0 PASSES=1 FAST_FAIL_SECS=1
    SHIM_MODE=slowstart "$STACK/rev-stack.sh" "$T/stack.cfg" > "$T/stack5.out" 2>&1
    assert_eq "slow-starting leg exits 0" "$?" 0
    assert_nogrep "a leg that ends inside the cpu sample is not killed" "$LOG" 'STALLED'
    assert_grep "the race is logged" "$LOG" 'finished during the [0-9]+s cpu sample — not killing'
    assert_grep "slow-starting leg recorded DONE" "$LOG" '=== DONE leg1 pass1 exit=0'
    # A8 — "logged in" is a substring of "Not logged in". grok-notauth signs out GROK ONLY, so codex's
    # (correct) check cannot mask the bug: the old grep -qi "logged in" passed on "Not logged in…" and
    # the leg ran as if signed in.
    export ROOT="$T/stack-root6" LOG="$T/stack6.log" STALL_SECS=30 AUTH_WAIT_TRIES=2 AUTH_WAIT_SECS=0
    SHIM_MODE=grok-notauth "$STACK/rev-stack.sh" "$T/stack.cfg" > "$T/stack6.out" 2>&1
    assert_eq "signed-out stack exits non-zero" "$?" 1
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
    SHIM_MODE=ok "$STACK/rev-stack.sh" "$T/stack-b.cfg" > "$T/stack7.out" 2>&1
    assert_eq "a refused squash does not fail the stack" "$?" 0
    assert_grep "squash refusal is logged" "$LOG" '!!! squash refused for stk2'
    assert_grep "refusal explains itself" "$LOG" 'only 0 unpushed'
    assert_grep "the push step still runs" "$LOG" 'NO_PUSH=1: not pushing'
    assert_grep "complete despite the refusal" "$LOG" 'ALL PHASES COMPLETE'
  )
}
