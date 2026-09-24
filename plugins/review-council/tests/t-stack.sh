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
    ln -sf "$SCRIPTS/rev-state.sh" "$RS/rev-state.sh"
    # lib/ comes along: the copy must run in the shipped configuration, portability layer and all, or the
    # REV_SCRIPTS-default case below would exercise a stack.sh whose compat.sh never loaded.
    ln -sfn "$SCRIPTS/lib" "$RS/lib"
    cp "$STACK/stack.sh" "$RS/stack.sh"
    cat > "$RS/rev-pr-review.py" <<'PY'
import os
from pathlib import Path
import shlex
import subprocess
import sys

command = sys.argv[1]
session = Path(sys.argv[2])
values = {}
scope = session / 'scope.env'
if scope.is_file():
    for line in scope.read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            parsed = shlex.split(value)
            if len(parsed) == 1:
                values[key] = parsed[0]
root = values.get('REV_ROOT')
local = remote = '-'
requested = '-'
previous = ''
for argument in sys.argv[1:]:
    if previous == '--head':
        requested = argument
    previous = argument
if root:
    local = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD'], text=True).strip()
    branch = values.get('REV_BRANCH') or subprocess.check_output(
        ['git', '-C', root, 'branch', '--show-current'], text=True).strip()
    result = subprocess.run(
        ['git', '-C', root, 'ls-remote', 'origin', f'refs/heads/{branch}'],
        text=True, capture_output=True)
    if result.returncode == 0 and result.stdout.strip():
        remote = result.stdout.split()[0]
calls = os.environ.get('STACK_PUBLISH_CALLS')
if calls:
    with Path(calls).open('a') as stream:
        stream.write(' '.join(sys.argv[1:]) + f' local={local} remote={remote}\n')
if os.environ.get('STACK_REQUIRE_SYNC') == '1':
    if command == 'publish' and local != remote:
        raise SystemExit(9)
    if command == 'finalize-stack' and (requested != local or local != remote):
        raise SystemExit(9)
if command == 'validate-stack':
    action = os.environ.get('STACK_AFTER_VALIDATE')
    if action == 'commit':
        changed = Path(root) / 'after-validation.txt'
        changed.write_text('changed after validation\n')
        subprocess.run(['git', '-C', root, 'add', changed.name], check=True)
        subprocess.run(
            ['git', '-C', root, 'commit', '-qm', 'fix(rev): after validation'], check=True)
    elif action == 'pushurl':
        subprocess.run(
            ['git', '-C', root, 'remote', 'set-url', '--add', '--push', 'origin',
             os.environ['STACK_REDIRECT_URL']], check=True)
    raise SystemExit(int(os.environ.get('STACK_VALIDATE_RC', '0')))
if command == 'finalize-stack':
    if os.environ.get('STACK_REMOVE_PUBLISHER') == '1':
        Path(__file__).unlink()
    raise SystemExit(int(os.environ.get('STACK_FINALIZE_RC', '0')))
if command == 'publish':
    capture = os.environ.get('STACK_PUBLISH_ENV')
    if capture:
        with Path(capture).open('a') as stream:
            stream.write(
                f"mode={os.environ.get('REV_STACK_PUBLICATION', '-')} "
                f"retry={os.environ.get('REVIEW_COUNCIL_RETRY_COMMAND', '-')}\n")
    rc = int(os.environ.get('STACK_PUBLISH_RC', '0'))
    if rc:
        retry = os.environ.get('REVIEW_COUNCIL_RETRY_COMMAND', '-')
        (session / 'incomplete.md').write_text(
            f'publisher failed\npr-review: retry: {retry}\n')
    raise SystemExit(rc)
raise SystemExit(0)
PY
    cat > "$RS/roster.sh" <<'RSEOF'
#!/bin/bash
printf '%s\n' "$@" >> "${FAKE_ROSTER_ARGS:-/dev/null}"
case "${FAKE_ROSTER_RC:-0}" in
  5) echo "review-council seats: codex x unavailable | STRICT availability: configured Codex seat did not survive probe";;
  6) echo "review-council seats: codex x invalid | STRICT config: codex_models must be a list";;
  *) echo "review-council seats: codex ok | gemini ok | claude ok";;
esac
exit "${FAKE_ROSTER_RC:-0}"
RSEOF
    chmod +x "$RS/roster.sh"
    export REV_SCRIPTS="$RS" FAKE_ROSTER_ARGS="$T/roster-args"
    export SHIM_CLAUDE_ARGS_FILE="$T/claude-args" REV_STACK_FOREGROUND=1
    export CLAUDECODE=1 CLAUDE_CODE_SESSION_ID=parent-session CLAUDE_CONFIG_DIR="$T/claude-config"
    export STACK_PUBLISH_CALLS="$T/stack.calls"
    : > "$STACK_PUBLISH_CALLS"
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
    assert_grep "leg inherits no-push mode" "$T/claude-args" '^NO_PUSH=1$'
    assert_grep "leg keeps review commits by default" "$T/claude-args" '^NO_SQUASH=1$'
    assert_grep "leg runs in the repo" "$T/claude-args" "^cwd=$R$"
    assert_grep "leg drops the parent Claude Code session marker" "$T/claude-args" '^CLAUDECODE=unset$'
    assert_grep "leg drops the parent session id" "$T/claude-args" '^CLAUDE_CODE_SESSION_ID=unset$'
    assert_grep "leg keeps the Claude config directory" "$T/claude-args" "^CLAUDE_CONFIG_DIR=$T/claude-config$"
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
    assert_grep "no-push stack suppresses external review publication" "$LOG" \
      'NO_PUSH=1: not publishing PR reviews'
    assert_grep "no-push stack validates the authoritative review" \
      "$STACK_PUBLISH_CALLS" '^validate-stack '
    assert_nogrep "no-push validation has no push endpoint" \
      "$STACK_PUBLISH_CALLS" '^validate-stack .*--push-url '
    assert_grep "all complete" "$LOG" 'ALL PHASES COMPLETE'

    export ROOT="$T/stack-invalid-review-root" LOG="$T/stack-invalid-review.log"
    export PASSES=1 STACK_VALIDATE_RC=1
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" \
      > "$T/stack-invalid-review.out" 2>&1
    assert_eq "no-push stack rejects an invalid review session" "$?" 1
    assert_exit "invalid no-push review exposes no final report" 0 \
      test ! -e "$ROOT/leg1/report.md"
    assert_exit "invalid no-push review preserves the ready report" 0 \
      test -s "$ROOT/leg1/stack-report.md"
    assert_grep "invalid no-push review names the validation phase" \
      "$LOG" 'COMPLETE WITH FAILURES: PR review validation'
    unset STACK_VALIDATE_RC

    printf 'NO_PUSH=1\nNO_SQUASH=1\nlegs() { run_leg "%s" 1 legcfg "config env"; }\n' \
      "$R" > "$T/stack-config-env.cfg"
    : > "$T/claude-config-env.args"
    ( unset NO_PUSH NO_SQUASH
      export ROOT="$T/stack-config-env-root" LOG="$T/stack-config-env.log" PASSES=1
      export SHIM_CLAUDE_ARGS_FILE="$T/claude-config-env.args"
      SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-config-env.cfg" \
        > "$T/stack-config-env.out" 2>&1
    )
    assert_eq "config-assigned no-push stack completes" "$?" 0
    assert_grep "config-assigned NO_PUSH reaches the leg" \
      "$T/claude-config-env.args" '^NO_PUSH=1$'
    assert_grep "config-assigned NO_SQUASH reaches the leg" \
      "$T/claude-config-env.args" '^NO_SQUASH=1$'

    : > "$T/args.env"
    ( unset NO_PUSH NO_SQUASH
      export REVIEW_COUNCIL_HOST=codex ROOT="$T/stack-codex-env-root"
      export LOG="$T/stack-codex-env.log" PASSES=1 MAX_ATTEMPTS=1
      SHIM_MODE=ok "$STACK/stack.sh" "$T/stack.cfg" > "$T/stack-codex-env.out" 2>&1
    )
    assert_eq "Codex stack double stops after its expected missing report" "$?" 1
    assert_grep "Codex default NO_PUSH reaches the leg" "$T/args.env" '^NO_PUSH=1$'
    assert_grep "Codex default NO_SQUASH reaches the leg" "$T/args.env" '^NO_SQUASH=1$'

    local PLAIN="$T/stk-plain"
    mkdir -p "$PLAIN"
    printf 'legs() { run_leg "%s" 1 plain "plain premise"; }\n' "$PLAIN" > "$T/stack-plain.cfg"
    export ROOT="$T/stack-plain-root" LOG="$T/stack-plain.log" PASSES=1 NO_PUSH=1 NO_SQUASH=0
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-plain.cfg" > "$T/stack-plain.out" 2>&1
    assert_eq "no-push plain-directory stack completes" "$?" 0
    assert_grep "plain-directory finish skips git operations explicitly" "$LOG" \
      'plain is not a git repository; NO_PUSH=1 skips squash and push'
    assert_nogrep "plain-directory finish does not claim un-collapsed commits" "$LOG" \
      'un-collapsed review commits'

    assert_exit "REV_STACK_LEG refuses" 1 env REV_STACK_LEG=1 "$STACK/stack.sh" "$T/stack.cfg"
    assert_exit "REV_ACTIVE refuses" 1 env REV_ACTIVE=1 "$STACK/stack.sh" "$T/stack.cfg"
    assert_exit "missing config refuses" 1 "$STACK/stack.sh"
    local RP="$T/stk-publish"; mkrepo "$RP"; git -C "$RP" checkout -qb feat
    git init -q --bare "$T/stk-publish-remote.git"
    git -C "$RP" remote add origin "$T/stk-publish-remote.git"
    git -C "$RP" push -q -u origin feat
    echo p > "$RP/p.txt"; git -C "$RP" add p.txt; git -C "$RP" commit -qm "fix(rev): publish"
    printf 'legs() { run_leg "%s" 1 legpub "publish premise"; }\n' "$RP" > "$T/stack-publish.cfg"
    export ROOT="$T/stack-publish-root" LOG="$T/stack-publish.log" PASSES=1 NO_PUSH=0 NO_SQUASH=1
    export STACK_PUBLISH_CALLS="$T/stack-publish.calls" STACK_REQUIRE_SYNC=1
    export STACK_PUBLISH_ENV="$T/stack-publish.env"
    : > "$STACK_PUBLISH_ENV"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-publish.cfg" > "$T/stack-publish.out" 2>&1
    assert_eq "completed pushed stack publishes PR review" "$?" 0
    local publish_head; publish_head=$(git -C "$RP" rev-parse HEAD)
    assert_grep "real-push validation records a nonempty endpoint" \
      "$STACK_PUBLISH_CALLS" '^validate-stack .*--push-url [^ ]+ '
    assert_grep "real-push validation binds the reviewed destination ref" \
      "$STACK_PUBLISH_CALLS" '^validate-stack .*--push-ref refs/heads/feat '
    assert_eq "literal-URL push refreshes the upstream tracking ref" \
      "$(git -C "$RP" rev-parse '@{u}')" "$publish_head"
    assert_eq "stack publisher receives the completed session" \
      "$(grep '^publish ' "$STACK_PUBLISH_CALLS")" \
      "publish $ROOT/legpub local=$publish_head remote=$publish_head"
    assert_grep "stack publisher defers failure-receipt cleanup" \
      "$STACK_PUBLISH_ENV" '^mode=1 '
    assert_grep "stack publisher receives the resumable stack command" \
      "$STACK_PUBLISH_ENV" "retry=.*ROOT=.*stack-publish-root.*stack.sh.*stack-publish.cfg"

    local RW="$T/stk-wrong-ref" rw_remote="$T/stk-wrong-ref-remote.git"
    mkrepo "$RW"
    git init -q --bare "$rw_remote"
    git -C "$RW" remote add origin "$rw_remote"
    git -C "$RW" push -q -u origin main
    git -C "$RW" checkout -qb feat origin/main
    echo reviewed > "$RW/reviewed.txt"; git -C "$RW" add reviewed.txt
    git -C "$RW" commit -qm 'fix(rev): wrong destination guard'
    local rw_main_before; rw_main_before=$(git -C "$RW" rev-parse origin/main)
    printf 'legs() { run_leg "%s" 1 legwrong "wrong destination"; }\n' "$RW" \
      > "$T/stack-wrong-ref.cfg"
    export ROOT="$T/stack-wrong-ref-root" LOG="$T/stack-wrong-ref.log"
    export STACK_PUBLISH_CALLS="$T/stack-wrong-ref.calls" NO_SQUASH=1
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-wrong-ref.cfg" \
      > "$T/stack-wrong-ref.out" 2>&1
    assert_eq "stack rejects an upstream ref different from the reviewed branch" "$?" 1
    assert_nogrep "wrong destination fails before Python validation" \
      "$STACK_PUBLISH_CALLS" '^validate-stack '
    assert_eq "wrong destination cannot advance remote main" \
      "$(git -C "$RW" ls-remote origin refs/heads/main | awk '{print $1}')" \
      "$rw_main_before"
    assert_eq "wrong destination cannot create remote feat" \
      "$(git -C "$RW" ls-remote origin refs/heads/feat | awk '{print $1}')" ""

    local RN="$T/stk-tracking-namespace" rn_remote="$T/stk-tracking-namespace-remote.git"
    mkrepo "$RN"; git -C "$RN" checkout -qb feat
    git init -q --bare "$rn_remote"
    git -C "$RN" remote add origin "$rn_remote"
    git -C "$RN" push -q -u origin feat
    git -C "$RN" config remote.origin.fetch '+refs/heads/*:refs/remotes/alternate/*'
    git -C "$RN" fetch -q origin
    echo reviewed > "$RN/reviewed.txt"; git -C "$RN" add reviewed.txt
    git -C "$RN" commit -qm 'fix(rev): tracking namespace guard'
    local rn_remote_before
    rn_remote_before=$(git -C "$RN" ls-remote origin refs/heads/feat | awk '{print $1}')
    printf 'legs() { run_leg "%s" 1 legnamespace "tracking namespace"; }\n' "$RN" \
      > "$T/stack-tracking-namespace.cfg"
    export ROOT="$T/stack-tracking-namespace-root" LOG="$T/stack-tracking-namespace.log"
    export STACK_PUBLISH_CALLS="$T/stack-tracking-namespace.calls"
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-tracking-namespace.cfg" \
      > "$T/stack-tracking-namespace.out" 2>&1
    assert_eq "stack rejects an upstream outside the selected tracking namespace" "$?" 1
    assert_nogrep "invalid tracking namespace fails before Python validation" \
      "$STACK_PUBLISH_CALLS" '^validate-stack '
    assert_eq "invalid tracking namespace cannot advance the remote" \
      "$(git -C "$RN" ls-remote origin refs/heads/feat | awk '{print $1}')" \
      "$rn_remote_before"

    export ROOT="$T/stack-publish-fail-root" LOG="$T/stack-publish-fail.log" STACK_PUBLISH_RC=1
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-publish.cfg" > "$T/stack-publish-fail.out" 2>&1
    assert_eq "stack publication failure fails the workflow" "$?" 1
    assert_grep "stack publication failure is terminal" "$LOG" \
      'COMPLETE WITH FAILURES: PR review publication'
    assert_exit "failed publication leaves no completed report" 0 \
      test ! -e "$ROOT/legpub/report.md"
    assert_exit "failed publication preserves the stack-ready report" 0 \
      test -s "$ROOT/legpub/stack-report.md"
    assert_exit "failed stack publication preserves its failure receipt" 0 \
      test -s "$ROOT/legpub/incomplete.md"
    assert_grep "stack failure receipt contains the resumable command" \
      "$ROOT/legpub/incomplete.md" \
      "retry: .*ROOT=.*stack-publish-fail-root.*stack.sh.*stack-publish.cfg"
    assert_nogrep "failed stack publication never reports completion" "$LOG" \
      'ALL PHASES COMPLETE'
    unset STACK_PUBLISH_RC

    export NO_PUSH=1
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-publish.cfg" \
      > "$T/stack-publish-no-push-retry.out" 2>&1
    assert_eq "no-push stack retry completes the ready session" "$?" 0
    assert_exit "no-push stack retry promotes the final report" 0 \
      test -s "$ROOT/legpub/report.md"
    assert_exit "no-push stack retry clears the stale failure receipt" 0 \
      test ! -e "$ROOT/legpub/incomplete.md"
    export NO_PUSH=0

    local state_real="$SCRIPTS/rev-state.sh"
    unlink "$RS/rev-state.sh"
    cat > "$RS/rev-state.sh" <<'SH'
#!/bin/bash
if [ "${STACK_STATE_FAIL:-}" = 1 ] && printf '%s\n' "$@" | grep -qx 'phase=done'; then
  exit 1
fi
exec "$REV_STATE_REAL" "$@"
SH
    chmod +x "$RS/rev-state.sh"
    export REV_STATE_REAL="$state_real"
    export ROOT="$T/stack-state-fail-root" LOG="$T/stack-state-fail.log"
    export STACK_PUBLISH_CALLS="$T/stack-state-fail.calls" STACK_STATE_FAIL=1
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-publish.cfg" \
      > "$T/stack-state-fail.out" 2>&1
    assert_eq "failed completion state write fails the stack" "$?" 1
    assert_exit "failed state write exposes no final report" 0 \
      test ! -e "$ROOT/legpub/report.md"
    assert_exit "failed state write preserves the ready report" 0 \
      test -s "$ROOT/legpub/stack-report.md"
    assert_grep "failed state write retains the nonterminal phase" \
      "$ROOT/legpub/state.json" '"phase":[[:space:]]*"stack-ready"'
    unset STACK_STATE_FAIL
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-publish.cfg" \
      > "$T/stack-state-retry.out" 2>&1
    assert_eq "completion retries after a failed state write" "$?" 0
    assert_exit "state-write retry promotes the final report" 0 \
      test -s "$ROOT/legpub/report.md"

    local mv_bin="$T/stack-mv-bin"
    mkdir -p "$mv_bin"
    cat > "$mv_bin/mv" <<'SH'
#!/bin/bash
case "${STACK_PROMOTE_FAIL:-}:$1:$2" in
  1:*stack-report.md:*report.md) exit 1;;
esac
exec /bin/mv "$@"
SH
    chmod +x "$mv_bin/mv"
    export ROOT="$T/stack-promote-fail-root" LOG="$T/stack-promote-fail.log"
    export STACK_PUBLISH_CALLS="$T/stack-promote-fail.calls" NO_PUSH=1
    : > "$STACK_PUBLISH_CALLS"
    PATH="$mv_bin:$PATH" STACK_PROMOTE_FAIL=1 SHIM_MODE=ok \
      "$STACK/stack.sh" "$T/stack-publish.cfg" \
      > "$T/stack-promote-fail.out" 2>&1
    assert_eq "failed report promotion fails the stack" "$?" 1
    assert_exit "failed promotion exposes no joint completion receipt" 0 \
      test ! -e "$ROOT/legpub/report.md"
    assert_exit "failed promotion preserves a retryable ready report" 0 \
      test -s "$ROOT/legpub/stack-report.md"
    assert_grep "failed promotion may retain done only without a final report" \
      "$ROOT/legpub/state.json" '"phase": "done"'
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-publish.cfg" \
      > "$T/stack-promote-retry.out" 2>&1
    assert_eq "completion retries after a failed report promotion" "$?" 0
    assert_exit "promotion retry creates the joint completion receipt" 0 \
      test -s "$ROOT/legpub/report.md"
    export NO_PUSH=0

    echo later > "$RP/later.txt"; git -C "$RP" add later.txt
    git -C "$RP" commit -qm 'fix(rev): rejected push'
    mkdir -p "$T/stk-publish-remote.git/hooks"
    cat > "$T/stk-publish-remote.git/hooks/pre-receive" <<'SH'
#!/bin/sh
exit 1
SH
    chmod +x "$T/stk-publish-remote.git/hooks/pre-receive"
    export ROOT="$T/stack-push-fail-root" LOG="$T/stack-push-fail.log"
    unset STACK_REQUIRE_SYNC
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-publish.cfg" > "$T/stack-push-fail.out" 2>&1
    assert_eq "failed stack push fails the workflow" "$?" 1
    assert_nogrep "failed stack push invokes no publisher" "$STACK_PUBLISH_CALLS" '^publish '
    assert_grep "failed stack push is attributed to the push" "$LOG" \
      'COMPLETE WITH FAILURES: push:stk-publish'
    assert_nogrep "failed stack push never reaches finalization" \
      "$STACK_PUBLISH_CALLS" '^finalize-stack '
    assert_nogrep "failed stack push never reports completion" "$LOG" 'ALL PHASES COMPLETE'
    assert_eq "failed stack push records only the actual remote head" \
      "$(git -C "$RP" rev-parse '@{u}')" \
      "$(git -C "$RP" ls-remote origin refs/heads/feat | awk '{print $1}')"

    local RH="$T/stk-head-race" rh_remote="$T/stk-head-race-remote.git"
    mkrepo "$RH"; git -C "$RH" checkout -qb feat
    git init -q --bare "$rh_remote"
    git -C "$RH" remote add origin "$rh_remote"
    git -C "$RH" push -q -u origin feat
    echo reviewed > "$RH/reviewed.txt"; git -C "$RH" add reviewed.txt
    git -C "$RH" commit -qm 'fix(rev): reviewed head'
    printf 'legs() { run_leg "%s" 1 legrace "head race"; }\n' "$RH" \
      > "$T/stack-head-race.cfg"
    export ROOT="$T/stack-head-race-root" LOG="$T/stack-head-race.log"
    export STACK_PUBLISH_CALLS="$T/stack-head-race.calls" STACK_AFTER_VALIDATE=commit
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-head-race.cfg" \
      > "$T/stack-head-race.out" 2>&1
    assert_eq "branch movement during push fails the stack" "$?" 1
    local reviewed_head raced_head remote_head
    assert_grep "head-race fixture reaches pre-push validation" \
      "$STACK_PUBLISH_CALLS" '^validate-stack '
    raced_head=$(git -C "$RH" rev-parse HEAD)
    reviewed_head=$(sed -n 's/^validate-stack .* local=\([^ ]*\) remote=.*/\1/p' \
      "$STACK_PUBLISH_CALLS")
    remote_head=$(git -C "$RH" ls-remote origin refs/heads/feat | awk '{print $1}')
    assert_eq "branch movement cannot widen the immutable push" \
      "$remote_head" "$reviewed_head"
    assert_eq "branch movement still records the immutable pushed head" \
      "$(git -C "$RH" rev-parse '@{u}')" "$reviewed_head"
    assert_nogrep "branch movement never reaches finalization" \
      "$STACK_PUBLISH_CALLS" '^finalize-stack '
    assert_exit "race fixture really advances the local branch" 0 \
      test "$raced_head" != "$reviewed_head"
    unset STACK_AFTER_VALIDATE
    export NO_SQUASH=0 STACK_VALIDATE_RC=1
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-head-race.cfg" \
      > "$T/stack-head-race-retry.out" 2>&1
    assert_eq "head-race retry remains incomplete on the unreviewed local commit" "$?" 1
    assert_grep "head-race retry refuses to rewrite the pushed review commit" \
      "$LOG" 'refusing: 2 review commits at tip but only 1 unpushed'
    assert_exit "head-race retry preserves the pushed commit in local history" 0 \
      git -C "$RH" merge-base --is-ancestor "$reviewed_head" HEAD
    unset STACK_VALIDATE_RC
    export NO_SQUASH=1

    local RT="$T/stk-tracking-retry" rt_remote="$T/stk-tracking-retry-remote.git"
    local rt_bin="$T/stk-tracking-retry-bin" rt_git
    mkrepo "$RT"; git -C "$RT" checkout -qb feat
    git init -q --bare "$rt_remote"
    git -C "$RT" remote add origin "$rt_remote"
    git -C "$RT" push -q -u origin feat
    local rt_before; rt_before=$(git -C "$RT" rev-parse '@{u}')
    echo one > "$RT/one.txt"; git -C "$RT" add one.txt
    git -C "$RT" commit -qm 'fix(rev): tracking retry one'
    echo two > "$RT/two.txt"; git -C "$RT" add two.txt
    git -C "$RT" commit -qm 'fix(rev): tracking retry two'
    local rt_head; rt_head=$(git -C "$RT" rev-parse HEAD)
    printf 'legs() { run_leg "%s" 1 legtracking "tracking retry"; }\n' "$RT" \
      > "$T/stack-tracking-retry.cfg"
    mkdir -p "$rt_bin"
    rt_git=$(command -v git)
    cat > "$rt_bin/git" <<'SH'
#!/bin/sh
after_update=0
for argument in "$@"; do
  if [ "$after_update" = 1 ] && [ "$argument" = "${STACK_FAIL_TRACKING_HEAD:-}" ]; then
    exit 88
  fi
  [ "$argument" = update-ref ] && after_update=1
done
exec "$STACK_GIT_REAL" "$@"
SH
    chmod +x "$rt_bin/git"
    export ROOT="$T/stack-tracking-retry-root" LOG="$T/stack-tracking-retry.log"
    export STACK_PUBLISH_CALLS="$T/stack-tracking-retry.calls"
    export STACK_GIT_REAL="$rt_git" STACK_FAIL_TRACKING_HEAD="$rt_head" NO_SQUASH=1
    : > "$STACK_PUBLISH_CALLS"
    PATH="$rt_bin:$PATH" SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-tracking-retry.cfg" \
      > "$T/stack-tracking-retry.out" 2>&1
    assert_eq "post-push tracking failure keeps the stack incomplete" "$?" 1
    assert_eq "tracking failure occurs after the immutable push lands" \
      "$(git -C "$RT" ls-remote origin refs/heads/feat | awk '{print $1}')" "$rt_head"
    assert_eq "failed tracking transaction does not claim the pushed head" \
      "$(git -C "$RT" rev-parse '@{u}')" "$rt_before"
    assert_nogrep "tracking failure never reaches finalization" \
      "$STACK_PUBLISH_CALLS" '^finalize-stack '
    unset STACK_FAIL_TRACKING_HEAD
    export NO_SQUASH=0
    PATH="$rt_bin:$PATH" SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-tracking-retry.cfg" \
      > "$T/stack-tracking-retry-retry.out" 2>&1
    assert_eq "tracking failure retry reconciles and completes" "$?" 0
    assert_grep "tracking retry refuses to rewrite already-pushed commits" \
      "$LOG" 'refusing: 2 review commits at tip but only 0 unpushed'
    assert_eq "tracking retry records the actual pushed head" \
      "$(git -C "$RT" rev-parse '@{u}')" "$rt_head"
    unset STACK_GIT_REAL
    export NO_SQUASH=1

    local RR="$T/stk-pushurl-race" rr_remote="$T/stk-pushurl-race-remote.git"
    local rr_redirect="$T/stk-pushurl-redirect.git"
    mkrepo "$RR"; git -C "$RR" checkout -qb feat
    git init -q --bare "$rr_remote"; git init -q --bare "$rr_redirect"
    git -C "$RR" remote add origin "$rr_remote"
    git -C "$RR" push -q -u origin feat
    echo reviewed > "$RR/reviewed.txt"; git -C "$RR" add reviewed.txt
    git -C "$RR" commit -qm 'fix(rev): pinned push URL'
    printf 'legs() { run_leg "%s" 1 legurl "push URL race"; }\n' "$RR" \
      > "$T/stack-pushurl-race.cfg"
    export ROOT="$T/stack-pushurl-race-root" LOG="$T/stack-pushurl-race.log"
    export STACK_PUBLISH_CALLS="$T/stack-pushurl-race.calls"
    export STACK_AFTER_VALIDATE=pushurl STACK_REDIRECT_URL="$rr_redirect"
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-pushurl-race.cfg" \
      > "$T/stack-pushurl-race.out" 2>&1
    assert_eq "push URL movement cannot redirect the reviewed push" "$?" 0
    assert_grep "push-URL fixture reaches pre-push validation" \
      "$STACK_PUBLISH_CALLS" '^validate-stack '
    assert_eq "push-URL fixture changes the configured endpoint after validation" \
      "$(git -C "$RR" remote get-url --push origin)" "$rr_redirect"
    remote_head=$(git -C "$RR" ls-remote "$rr_remote" refs/heads/feat | awk '{print $1}')
    assert_eq "captured push URL receives the reviewed commit" \
      "$remote_head" "$(git -C "$RR" rev-parse HEAD)"
    assert_eq "changed push URL receives no branch" \
      "$(git -C "$RR" ls-remote "$rr_redirect" refs/heads/feat | awk '{print $1}')" ""
    unset STACK_AFTER_VALIDATE STACK_REDIRECT_URL

    local RMP="$T/stk-missing-publisher" rmp_remote="$T/stk-missing-publisher-remote.git"
    local RSM="$T/rs-missing-publisher"
    mkrepo "$RMP"; git -C "$RMP" checkout -qb feat
    git init -q --bare "$rmp_remote"
    git -C "$RMP" remote add origin "$rmp_remote"
    git -C "$RMP" push -q -u origin feat
    echo reviewed > "$RMP/reviewed.txt"; git -C "$RMP" add reviewed.txt
    git -C "$RMP" commit -qm 'fix(rev): missing publisher'
    printf 'legs() { run_leg "%s" 1 legmissingpub "missing publisher"; }\n' "$RMP" \
      > "$T/stack-missing-publisher.cfg"
    copy_writable_tree "$RS" "$RSM"
    export REV_SCRIPTS="$RSM" ROOT="$T/stack-missing-publisher-root"
    export LOG="$T/stack-missing-publisher.log"
    export STACK_PUBLISH_CALLS="$T/stack-missing-publisher.calls"
    export STACK_REMOVE_PUBLISHER=1
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-missing-publisher.cfg" \
      > "$T/stack-missing-publisher.out" 2>&1
    assert_eq "publisher disappearance fails the stack" "$?" 1
    assert_grep "publisher disappearance is attributed to publication" "$LOG" \
      'COMPLETE WITH FAILURES: PR review publication'
    assert_exit "publisher disappearance exposes no final report" 0 \
      test ! -e "$ROOT/legmissingpub/report.md"
    assert_exit "publisher disappearance preserves the ready report" 0 \
      test -s "$ROOT/legmissingpub/stack-report.md"
    unset STACK_REMOVE_PUBLISHER
    export REV_SCRIPTS="$RS"

    local RSQ="$T/stk-squash"; mkrepo "$RSQ"; git -C "$RSQ" checkout -qb feat
    git init -q --bare "$T/stk-squash-remote.git"
    git -C "$RSQ" remote add origin "$T/stk-squash-remote.git"
    git -C "$RSQ" push -q -u origin feat
    for i in 1 2; do echo "$i" > "$RSQ/s$i.txt"; git -C "$RSQ" add "s$i.txt"; git -C "$RSQ" commit -qm "fix(rev): squash $i"; done
    printf 'legs() { run_leg "%s" 1 legsquash "squash premise"; }\n' "$RSQ" > "$T/stack-squash.cfg"
    export ROOT="$T/stack-squash-root" LOG="$T/stack-squash.log" NO_SQUASH=0
    export STACK_PUBLISH_CALLS="$T/stack-squash.calls" STACK_FINALIZE_RC=1
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-squash.cfg" > "$T/stack-squash.out" 2>&1
    assert_eq "failed stack finalization fails the workflow" "$?" 1
    assert_exit "failed stack finalization preserves authoritative session state" 0 \
      test -s "$ROOT/repo-sessions.tsv"
    assert_exit "failed finalization leaves no completed report" 0 \
      test ! -e "$ROOT/legsquash/report.md"
    assert_exit "failed finalization preserves the stack-ready report" 0 \
      test -s "$ROOT/legsquash/stack-report.md"
    assert_nogrep "failed stack finalization does not publish" "$STACK_PUBLISH_CALLS" '^publish '
    unset STACK_FINALIZE_RC
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-squash.cfg" > "$T/stack-squash-retry.out" 2>&1
    assert_eq "stack finalization retry publishes" "$?" 0
    local squash_root; squash_root=$(git -C "$RSQ" rev-parse --show-toplevel)
    publish_head=$(git -C "$RSQ" rev-parse HEAD)
    assert_eq "stack finalizes links at the changed-head squash tip" \
      "$(grep '^finalize-stack ' "$STACK_PUBLISH_CALLS")" \
      "finalize-stack $ROOT/legsquash --head $publish_head --root $squash_root local=$publish_head remote=$publish_head"
    assert_eq "stack publishes the remote aggregate head" \
      "$(grep '^publish ' "$STACK_PUBLISH_CALLS")" \
      "publish $ROOT/legsquash local=$publish_head remote=$publish_head"

    local RNP="$T/stk-no-push-squash" rnp_root
    mkrepo "$RNP"; git -C "$RNP" checkout -qb feat
    git init -q --bare "$T/stk-no-push-squash-remote.git"
    git -C "$RNP" remote add origin "$T/stk-no-push-squash-remote.git"
    git -C "$RNP" push -q -u origin feat
    rnp_root=$(git -C "$RNP" rev-parse --show-toplevel)
    for i in 1 2; do
      echo "$i" > "$RNP/n$i.txt"
      git -C "$RNP" add "n$i.txt"
      git -C "$RNP" commit -qm "fix(rev): no-push squash $i"
    done
    printf 'legs() { run_leg "%s" 1 legnopush "no-push squash"; }\n' \
      "$RNP" > "$T/stack-no-push-squash.cfg"
    export ROOT="$T/stack-no-push-squash-root" LOG="$T/stack-no-push-squash.log"
    export NO_PUSH=1 NO_SQUASH=0 STACK_PUBLISH_CALLS="$T/stack-no-push-squash.calls"
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-no-push-squash.cfg" \
      > "$T/stack-no-push-squash.out" 2>&1
    assert_eq "no-push squash run completes without publishing" "$?" 0
    : > "$STACK_PUBLISH_CALLS"
    export NO_PUSH=0 STACK_REQUIRE_SYNC=1
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-no-push-squash.cfg" \
      > "$T/stack-no-push-squash-retry.out" 2>&1
    assert_eq "later push recovers no-push squash finalization" "$?" 0
    publish_head=$(git -C "$RNP" rev-parse HEAD)
    assert_eq "later push finalizes the exact aggregate head from durable state" \
      "$(grep '^finalize-stack ' "$STACK_PUBLISH_CALLS")" \
      "finalize-stack $ROOT/legnopush --head $publish_head --root $rnp_root local=$publish_head remote=$publish_head"
    unset STACK_REQUIRE_SYNC

    local RMISS="$T/stk-missing-session"
    mkrepo "$RMISS"; git -C "$RMISS" checkout -qb feat
    git init -q --bare "$T/stk-missing-session-remote.git"
    git -C "$RMISS" remote add origin "$T/stk-missing-session-remote.git"
    git -C "$RMISS" push -q -u origin feat
    echo later > "$RMISS/later.txt"; git -C "$RMISS" add later.txt
    git -C "$RMISS" commit -qm 'fix(rev): missing session'
    printf 'legs() { run_leg "%s" 1 legmissing "missing session"; }\n' \
      "$RMISS" > "$T/stack-missing-session.cfg"
    export ROOT="$T/stack-missing-session-root" LOG="$T/stack-missing-session.log"
    export NO_PUSH=0 NO_SQUASH=1 STACK_PUBLISH_CALLS="$T/stack-missing-session.calls"
    cat > "$RMISS/.git/hooks/pre-push" <<SH
#!/bin/sh
rm -f '$ROOT/repo-sessions.tsv'
SH
    chmod +x "$RMISS/.git/hooks/pre-push"
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-missing-session.cfg" \
      > "$T/stack-missing-session.out" 2>&1
    assert_eq "missing authoritative session fails the stack" "$?" 1
    assert_grep "missing session is attributed to finalization" "$LOG" \
      'COMPLETE WITH FAILURES: PR review finalization'
    assert_nogrep "missing finalization session skips publication" \
      "$STACK_PUBLISH_CALLS" '^publish '

    local RM="$T/stk-multi" RM2="$T/stk-multi-second"
    mkrepo "$RM"; git -C "$RM" checkout -qb feat
    mkdir -p "$RM/sub"; echo nested > "$RM/sub/nested.txt"
    git -C "$RM" add sub/nested.txt; git -C "$RM" commit -qm 'feat: nested leg'
    git init -q --bare "$T/stk-multi-remote.git"
    git -C "$RM" remote add origin "$T/stk-multi-remote.git"
    git -C "$RM" push -q -u origin feat
    echo later > "$RM/later.txt"; git -C "$RM" add later.txt
    git -C "$RM" commit -qm 'fix(rev): same repository'
    mkrepo "$RM2"; git -C "$RM2" checkout -qb feat
    git init -q --bare "$T/stk-multi-second-remote.git"
    git -C "$RM2" remote add origin "$T/stk-multi-second-remote.git"
    git -C "$RM2" push -q -u origin feat
    echo second > "$RM2/second.txt"; git -C "$RM2" add second.txt
    git -C "$RM2" commit -qm 'fix(rev): second repository'
    printf 'legs() { run_leg "%s" 1 primary "primary"; run_leg "%s" 1 secondary "secondary"; run_leg "%s/sub" 1 seam "seam"; }\n' \
      "$RM" "$RM2" "$RM" > "$T/stack-multi.cfg"
    export ROOT="$T/stack-multi-root" LOG="$T/stack-multi.log" NO_SQUASH=1 NO_PUSH=0
    export STACK_PUBLISH_CALLS="$T/stack-multi.calls" STACK_REQUIRE_SYNC=1
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-multi.cfg" > "$T/stack-multi.out" 2>&1
    assert_eq "same-repository stack completes" "$?" 0
    assert_eq "stack publishes once per canonical repository" \
      "$(grep -c '^publish ' "$STACK_PUBLISH_CALLS")" 2
    publish_head=$(git -C "$RM" rev-parse HEAD)
    assert_eq "latest same-repository session is authoritative" \
      "$(grep "^publish $ROOT/seam " "$STACK_PUBLISH_CALLS")" \
      "publish $ROOT/seam local=$publish_head remote=$publish_head"
    publish_head=$(git -C "$RM2" rev-parse HEAD)
    assert_eq "distinct repository keeps its authoritative publication" \
      "$(grep "^publish $ROOT/secondary " "$STACK_PUBLISH_CALLS")" \
      "publish $ROOT/secondary local=$publish_head remote=$publish_head"

    local RF="$T/stk-partial-fail" RG="$T/stk-partial-good"
    mkrepo "$RF"; git -C "$RF" checkout -qb feat
    mkrepo "$RG"; git -C "$RG" checkout -qb feat
    git init -q --bare "$T/stk-partial-good-remote.git"
    git -C "$RG" remote add origin "$T/stk-partial-good-remote.git"
    git -C "$RG" push -q -u origin feat
    echo good > "$RG/good.txt"; git -C "$RG" add good.txt
    git -C "$RG" commit -qm 'fix(rev): successful repository'
    printf 'legs() { run_leg "%s" 1 failed "failed"; run_leg "%s" 1 good "good"; }\n' \
      "$RF" "$RG" > "$T/stack-partial.cfg"
    export ROOT="$T/stack-partial-root" LOG="$T/stack-partial.log" NO_SQUASH=1 NO_PUSH=0
    export MAX_ATTEMPTS=1 MAX_INFRA_RETRIES=0 SHIM_FAIL_CWD="$RF"
    export STACK_PUBLISH_CALLS="$T/stack-partial.calls"
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-partial.cfg" \
      > "$T/stack-partial.out" 2>&1
    assert_eq "partial multi-repository failure remains nonzero" "$?" 1
    assert_grep "successful repository still publishes after a sibling failure" \
      "$STACK_PUBLISH_CALLS" "^publish $ROOT/good "
    assert_grep "partial failure remains explicit" "$LOG" 'COMPLETE WITH FAILURES: failed'
    unset SHIM_FAIL_CWD

    local RR="$T/stk-resume-order"
    mkrepo "$RR"; git -C "$RR" checkout -qb feat
    git init -q --bare "$T/stk-resume-order-remote.git"
    git -C "$RR" remote add origin "$T/stk-resume-order-remote.git"
    git -C "$RR" push -q -u origin feat
    printf 'legs() { run_leg "%s" 1 fresh "fresh"; run_leg "%s" 1 stale "stale"; }\n' \
      "$RR" "$RR" > "$T/stack-resume-order.cfg"
    export ROOT="$T/stack-resume-order-root" LOG="$T/stack-resume-order.log"
    export NO_SQUASH=1 NO_PUSH=0 STACK_PUBLISH_CALLS="$T/stack-resume-order.calls"
    mkdir -p "$ROOT/stale"
    printf '%s\n' '# stale report' > "$ROOT/stale/report.md"
    printf '%s\n' '{"phase":"done"}' > "$ROOT/stale/state.json"
    printf "REV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" "$RR" \
      > "$ROOT/stale/scope.env"
    printf '%s\n' "=== DONE stale pass1 exit=0 root=$ROOT" > "$LOG"
    : > "$STACK_PUBLISH_CALLS"
    SHIM_MODE=ok "$STACK/stack.sh" "$T/stack-resume-order.cfg" \
      > "$T/stack-resume-order.out" 2>&1
    assert_eq "resume-order stack completes" "$?" 0
    assert_grep "latest completed leg stays authoritative after a later skip" \
      "$STACK_PUBLISH_CALLS" "^publish $ROOT/fresh "
    assert_nogrep "skipped stale session cannot reclaim repository authority" \
      "$STACK_PUBLISH_CALLS" "^publish $ROOT/stale "

    export ROOT="$T/stack-root" LOG="$T/stack.log" PASSES=2 NO_PUSH=1 NO_SQUASH=0
    unset STACK_REQUIRE_SYNC
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
    # exit 0 without stack-report.md is NOT ready: retried with resume, then gives up
    export ROOT="$T/stack-root4" LOG="$T/stack4.log" MAX_ATTEMPTS=2 MAX_INFRA_RETRIES=0 FAST_FAIL_SECS=1
    SHIM_MODE=noreport "$STACK/stack.sh" "$T/stack.cfg" > /dev/null 2>&1
    assert_grep "incomplete leg detected" "$LOG" \
      'invalid completion receipt \(stack-report.md is missing\)'
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
    local D="$T/scripts-sb"; mkdir -p "$D"
    local script
    for script in "$SCRIPTS"/*.sh; do copy_writable_file "$script" "$D/$(basename "$script")"; done
    copy_writable_tree "$SCRIPTS/lib" "$D/lib"
    printf '#!/bin/bash\necho "boom" >&2; exit 1\n' > "$D/rev-status.sh"; chmod +x "$D/rev-status.sh"
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
    copy_writable_tree "$SCRIPTS/lib" "$D/lib"
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
      echo '# pass 1 report' > "$session/stack-report.md"
      printf '%s\n' '{"phase":"stack-ready"}' > "$session/state.json"
      echo '# findings' > "$session/findings.md"
    fi
    exit 0
    ;;
  retry)
    if [ "$count" = 1 ]; then
      echo '# failed attempt report' > "$session/stack-report.md"
      printf '%s\n' '{"phase":"stack-ready"}' > "$session/state.json"
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
      assert_grep "$host later pass archives the prior report" \
        "$ROOT/leg/stack-report.pass2.attempt1.previous.md" 'pass 1 report'

      export PASSES=1 MAX_ATTEMPTS=2 ROOT="$T/attempt-$host-retry" LOG="$T/attempt-$host-retry.log"
      export ATTEMPT_COUNT="$T/attempt-$host-retry.count" STALE_REPORT_MODE=retry
      "$D/stack.sh" "$T/attempt-stack.cfg" > "$T/attempt-$host-retry.out" 2>&1
      rc=$?
      assert_eq "$host retry rejects a stale report" "$rc" 1
      assert_nogrep "$host retry is never certified" "$LOG" '=== DONE leg pass1'
      assert_grep "$host retry invokes both attempts" "$ATTEMPT_COUNT.trace" 'count=2 '
      assert_grep "$host retry archives the failed attempt report" \
        "$ROOT/leg/stack-report.pass1.attempt2.previous.md" 'failed attempt report'
    done
  )
}
