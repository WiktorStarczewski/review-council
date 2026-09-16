# tests for Task 3 - sourced by run-tests.sh
# NB: the bodies run in the RUNNER's shell, not a subshell, so ok()/fail()'s PASS/FAIL increments
# survive; seat_env's exports are undone at the end so later tests see a clean environment.
seat_timeout() {  # seat_timeout <secs> <cmd...> - hard cap, so a runaway seat cannot hang the suite
  local lim=$(( $1 * 10 )); shift
  "$@" >/dev/null 2>&1 &
  local pid=$! i=0
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt "$lim" ]; do sleep 0.1; i=$((i+1)); done
  if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124; fi
  wait "$pid"; return $?
}
seat_env_reset() { PATH="$1"; unset SHIM_FIXTURE_DIR SHIM_ARGS_FILE SHIM_CHILD_PID_FILE REV_REPO SHIM_MODE; }
seat_roster() {  # seat_roster <session-dir> - the roster.json rev-preflight.sh leaves in the session dir.
  # Written by hand on purpose: these tests exercise rev-seat.sh's dispatch, not roster.sh's detection.
  mkdir -p "$1"
  cat > "$1/roster.json" <<'JSON'
{ "generated_at": "2026-09-02T00:00:00Z",
  "seats": [
    { "seat": "codex-sol",        "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",    "effort": "max",   "extra": false },
    { "seat": "codex-terra",      "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-terra",  "effort": "xhigh", "extra": false },
    { "seat": "gemini",           "lab": "google",    "adapter": "gemini", "model": "gemini-2.5-pro", "effort": null,    "extra": false },
    { "seat": "opus",             "lab": "anthropic", "adapter": "agent",  "model": "opus",           "effort": "max",   "extra": false },
    { "seat": "codex-review",     "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",    "effort": "max",   "mode": "review",      "extra": true, "round": 2 }
  ],
  "excluded": [] }
JSON
}
test_seat_rejects_retired_grok_adapter() {
  local _path="$PATH"; seat_env
  local S="$T/seat-retired-grok"; mkdir -p "$S"; echo "review the diff" > "$S/p.md"
  cat > "$S/roster.json" <<'JSON'
{"seats":[{"seat":"grok","lab":"xai","adapter":"grok","model":"grok-4.6","effort":"xhigh","extra":false}]}
JSON
  assert_exit "a forged retired Grok seat cannot launch" 1 \
    env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok "$S" 1 "$S/p.md"
  assert_exit "the live Grok adapter script is absent" 1 test -e "$SCRIPTS/seats.d/grok.sh"
  seat_env_reset "$_path"
}
test_seat_codex() {
  local _path="$PATH"; seat_env
  local S="$T/seat-codex"; seat_roster "$S"; echo "review the diff" > "$S/p.md"; : > "$T/args.env"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" > "$T/out.txt"; local rc=$?
  assert_eq "codex ok exit" "$rc" 0
  assert_grep "prints summary line" "$T/out.txt" '^seat=codex-sol round=1 exit=0 findings=1$'
  assert_grep "writes .exit" "$S/r1-codex-sol.exit" '^0$'
  assert_grep "json copied" "$S/r1-codex-sol.json" '"severity": ?"P1"'
  assert_grep "log has exec line" "$S/r1-codex-sol.log" '^exec: .*git diff abc123'
  assert_grep "log has done line" "$S/r1-codex-sol.log" '^done: exit=0'
  assert_grep "prompt via stdin" "$T/args.stdin" 'review the diff'
  assert_grep "model comes from the roster" "$T/args" '^gpt-5.6-sol$'
  assert_grep "effort comes from the roster" "$T/args" '^model_reasoning_effort=max$'
  # the seat's environment is not visible in argv: REV_ACTIVE is the recursion guard, -C is the repo root
  assert_grep "seat carries REV_ACTIVE=1" "$T/args.env" '^REV_ACTIVE=1$'
  assert_nogrep "no seat runs unguarded" "$T/args.env" '^REV_ACTIVE=unset$'
  assert_grep "seat records its cwd" "$T/args.env" '^cwd=/'
  assert_grep "codex gets the repo root with -C" "$T/args" "^$T$"
  assert_grep "read-only sandbox" "$T/args" '^read-only$'
  assert_grep "schema passed" "$T/args" 'findings.schema.json$'
  assert_nogrep "no write flags" "$T/args" 'danger|workspace-write|--approve'
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 2 "$S/p.md" >/dev/null
  assert_grep "terra model from the roster" "$T/args" '^gpt-5.6-terra$'
  assert_grep "terra effort is its own roster entry" "$T/args" '^model_reasoning_effort=xhigh$'
  assert_exit "notauth → 3" 3 env SHIM_MODE=notauth "$SCRIPTS/rev-seat.sh" codex-sol "$S" 3 "$S/p.md"
  assert_exit "ratelimit → 4" 4 env SHIM_MODE=ratelimit "$SCRIPTS/rev-seat.sh" codex-sol "$S" 4 "$S/p.md"
  local classifier_bin="$T/seat-classifier-bin" seat_path=$PATH
  mkdir -p "$classifier_bin"
  cat > "$classifier_bin/codex" <<'SH'
#!/bin/bash
case "${FAILURE_MODE:-}" in
  capacity) printf '%s\n' '{"type":"error","message":"Credit balance is too low; provider capacity exhausted"}' ;;
  prose) printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"the reviewed code says quota exceeded"}}' ;;
esac
exit 1
SH
  chmod +x "$classifier_bin/codex"
  PATH="$classifier_bin:$PATH" FAILURE_MODE=capacity \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 4c "$S/p.md" >/dev/null 2>&1
  assert_eq "provider capacity exhaustion uses the quota exit" "$?" 4
  PATH="$classifier_bin:$PATH" FAILURE_MODE=prose \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" 4p "$S/p.md" >/dev/null 2>&1
  assert_eq "quota words in model prose do not use the quota exit" "$?" 2
  PATH=$seat_path
  assert_exit "empty → 2" 2 env SHIM_MODE=empty "$SCRIPTS/rev-seat.sh" codex-sol "$S" 5 "$S/p.md"
  assert_exit "badjson → 2" 2 env SHIM_MODE=badjson "$SCRIPTS/rev-seat.sh" codex-sol "$S" 6 "$S/p.md"
  assert_grep "exit file records 2" "$S/r6-codex-sol.exit" '^2$'
  : > "$T/codex-notools-calls"
  SHIM_MODE=notools SHIM_CALLS_FILE="$T/codex-notools-calls" "$SCRIPTS/rev-seat.sh" codex-sol "$S" 6n "$S/p.md" > "$T/codex-notools.out" 2>&1
  assert_eq "Codex no-tool review exits unusable" "$?" 2
  assert_eq "Codex no-tool review retries once" "$(wc -l < "$T/codex-notools-calls" | tr -d ' ')" 2
  assert_grep "Codex no-tool log explains the rejection" "$S/r6n-codex-sol.log" 'answered without a single tool call \(attempt 2\)'
  assert_exit "codex-review needs --base" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-review "$S" 7 "$S/p.md"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-review "$S" 7 "$S/p.md" --base abc123 >/dev/null
  assert_grep "codex-review uses review subcommand" "$T/args" '^review$'
  assert_grep "codex-review passes base" "$T/args" '^abc123$'
    assert_nogrep "codex-review passes no sandbox flag (exec review has no -s)" "$T/args" '^(-s|read-only)$'
  assert_exit "seat that is not in the roster → 1" 1 "$SCRIPTS/rev-seat.sh" mystery "$S" 8 "$S/p.md"
  "$SCRIPTS/rev-seat.sh" mystery "$S" 8 "$S/p.md" 2> "$T/noseat.err"
  assert_grep "unknown seat says run preflight first" "$T/noseat.err" 'run preflight first'
  assert_exit "missing prompt → 1" 1 "$SCRIPTS/rev-seat.sh" codex-sol "$S" 9 "$S/nope.md"
  # a session without a roster has not been through preflight: refuse, do not guess a model
  local N="$T/seat-noroster"; mkdir -p "$N"; echo "review" > "$N/p.md"
  assert_exit "no roster → 1" 1 "$SCRIPTS/rev-seat.sh" codex-sol "$N" 1 "$N/p.md"
  "$SCRIPTS/rev-seat.sh" codex-sol "$N" 1 "$N/p.md" 2> "$T/noroster.err"
  assert_grep "missing roster says run preflight first" "$T/noroster.err" 'run preflight first'
  # a roster naming an adapter this plugin has no script for is a broken roster, not a seat to guess at
  local A="$T/seat-badadapter"; mkdir -p "$A"; echo "review" > "$A/p.md"
  cat > "$A/roster.json" <<'JSON'
{ "generated_at": "t", "seats": [ { "seat": "codex-sol", "lab": "openai", "adapter": "nosuchcli", "model": "m", "effort": "max", "extra": false } ], "excluded": [] }
JSON
  assert_exit "roster adapter with no script → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$A" 1 "$A/p.md"
  # a truncated roster must fail like a missing one, not crash with a python traceback for an exit code
  local B="$T/seat-badroster"; mkdir -p "$B"; echo "review" > "$B/p.md"; printf '{ "seats": [ {' > "$B/roster.json"
  assert_exit "unreadable roster → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$B" 1 "$B/p.md"
  env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$B" 1 "$B/p.md" 2> "$T/badroster.err"
  assert_grep "unreadable roster says run preflight first" "$T/badroster.err" 'run preflight first'
  # the agent seat is launched by the skill through the Agent tool - there is no CLI to run here
  assert_exit "agent seat → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$S/p.md"
  "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$S/p.md" 2> "$T/agent.err"
  assert_grep "agent seat explains itself" "$T/agent.err" 'Agent tool'
  # a failed run whose model stream merely quotes a 401 is "no output" (2), not "not signed in" (3)
  assert_exit "quoted 401 in stream → 2, not 3" 2 env SHIM_MODE=noise401 "$SCRIPTS/rev-seat.sh" codex-sol "$S" 10 "$S/p.md"
  assert_grep "the 401 really is in the raw stream" "$S/r10-codex-sol.stream.ndjson" '401 Unauthorized'
  # …and it reaches the LOG too, as the model's own `text:` line - that is exactly the line classify_failure
  # must ignore. Only CLI-originated lines decide sign-in and cap.
  assert_grep "the 401 is in the log as model text" "$S/r10-codex-sol.log" '^text: .*401 Unauthorized'
  assert_nogrep "no CLI-originated 401 line" "$S/r10-codex-sol.log" '^(error|exec|done): .*401'
  # the roster effort is the probed and receipted launch authority; later overrides cannot diverge
  assert_exit "REV_CODEX_EFFORT cannot lower the receipted effort" 1 env \
    REV_CODEX_EFFORT=high SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 11 "$S/p.md"
  assert_exit "--effort cannot raise the receipted effort" 1 env \
    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 12 "$S/p.md" --effort max
  assert_exit "REV_CODEX_EFFORT cannot raise the receipted effort" 1 env \
    REV_CODEX_EFFORT=ultra SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 13 "$S/p.md"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 14 "$S/p.md" --effort xhigh >/dev/null
  assert_grep "an exact matching effort preserves the roster launch" "$T/args" \
    '^model_reasoning_effort=xhigh$'
  # Codex requires the exact effort selected before its availability probe.
  local E="$T/seat-noeffort"; mkdir -p "$E"; echo "review" > "$E/p.md"
  cat > "$E/roster.json" <<'JSON'
{ "generated_at": "t", "seats": [ { "seat": "codex-sol", "lab": "openai", "adapter": "codex", "model": "gpt-5.6-sol", "effort": null, "extra": false } ], "excluded": [] }
JSON
  assert_exit "an effort-less Codex roster entry cannot launch" 1 env \
    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$E" 1 "$E/p.md"

  local C="$T/seat-call-cap"; seat_roster "$C"; echo "review the diff" > "$C/p.md"
  : > "$T/capped-calls"
  local call
  for call in 1 2 3 4; do
    SHIM_MODE=ok SHIM_CALLS_FILE="$T/capped-calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$C" cap "$C/p.md" >/dev/null
    assert_eq "provider call $call stays within the persistent cap" "$?" 0
  done
  printf '%s\n' '{"prior":"audit"}' > "$C/rcap-codex-sol.read-audit.json"
  local artifact
  for artifact in json read-audit.json stream.ndjson; do
    cp "$C/rcap-codex-sol.$artifact" "$C/before-cap.$artifact"
  done
  SHIM_MODE=ok SHIM_CALLS_FILE="$T/capped-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$C" cap "$C/p.md" >/dev/null 2>&1
  assert_eq "fifth provider call is rejected before launch" "$?" 7
  assert_eq "persistent cap permits exactly four provider processes" \
    "$(wc -l < "$T/capped-calls" | tr -d ' ')" 4
  for artifact in json read-audit.json stream.ndjson; do
    assert_exit "cap refusal preserves prior $artifact" 0 \
      cmp -s "$C/before-cap.$artifact" "$C/rcap-codex-sol.$artifact"
  done
  assert_grep "cap refusal persists its diagnostic in the seat log" \
    "$C/rcap-codex-sol.log" '^persistent provider-call cap reached for this seat generation$'
  assert_grep "cap refusal writes a fresh exit" "$C/rcap-codex-sol.exit" '^7$'

  local A="$T/seat-archive-failure" archive_path="$T/archive-path"
  seat_roster "$A"; echo "review the diff" > "$A/p.md"
  printf 'prior stream\n' > "$A/rarchive-codex-sol.stream.ndjson"
  mkdir -p "$archive_path"
  cat > "$archive_path/mv" <<'SH'
#!/bin/sh
exit 1
SH
  chmod +x "$archive_path/mv"
  : > "$T/archive-calls"
  PATH="$archive_path:$PATH" SHIM_MODE=ok SHIM_CALLS_FILE="$T/archive-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$A" archive "$A/p.md" >/dev/null 2>&1
  assert_eq "failed transcript archival exits before provider launch" "$?" 1
  assert_eq "failed transcript archival consumes no provider call" \
    "$(wc -l < "$T/archive-calls" | tr -d ' ')" 0
  for call in 1 2 3 4; do
    SHIM_MODE=ok SHIM_CALLS_FILE="$T/archive-calls" \
      "$SCRIPTS/rev-seat.sh" codex-sol "$A" archive "$A/p.md" >/dev/null
    assert_eq "archive recovery retains provider call $call" "$?" 0
  done
  assert_eq "archive recovery retains all four provider launches" \
    "$(wc -l < "$T/archive-calls" | tr -d ' ')" 4

  local D="$T/seat-corrupt-cap"; seat_roster "$D"; echo "review the diff" > "$D/p.md"
  : > "$T/corrupt-calls"
  SHIM_MODE=ok SHIM_CALLS_FILE="$T/corrupt-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$D" corrupt "$D/p.md" >/dev/null
  printf '{' > "$(find "$D/attempts" -type f -name '*.json' -print -quit)"
  SHIM_MODE=ok SHIM_CALLS_FILE="$T/corrupt-calls" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$D" corrupt "$D/p.md" >/dev/null 2>&1
  assert_eq "corrupt persistent attempt state fails closed" "$?" 1
  assert_eq "corrupt attempt state launches no replacement provider" \
    "$(wc -l < "$T/corrupt-calls" | tr -d ' ')" 1
  assert_grep "corrupt attempt state writes a fresh exit" "$D/rcorrupt-codex-sol.exit" '^1$'

  local W="$T/seat-reserve-window"; seat_roster "$W"; echo "review the diff" > "$W/p.md"
  echo 0 > "$W/rblocked-codex-sol.exit"
  local python_bin="$T/reserve-python-bin" real_python reserve_pid reserve_rc i=0
  real_python=$(command -v python3)
  mkdir -p "$python_bin"
  cat > "$python_bin/python3" <<'SH'
#!/bin/bash
if [ "$1" = "$RESERVE_HELPER" ] && [ "$2" = reserve ]; then
  : > "$RESERVE_READY"
  while [ ! -e "$RESERVE_RELEASE" ]; do sleep 0.02; done
  exit 7
fi
exec "$REAL_PYTHON" "$@"
SH
  chmod +x "$python_bin/python3"
  env PATH="$python_bin:$PATH" REAL_PYTHON="$real_python" \
    RESERVE_HELPER="$SCRIPTS/lib/rev-attempt.py" RESERVE_READY="$T/reserve.ready" \
    RESERVE_RELEASE="$T/reserve.release" SHIM_MODE=ok \
    "$SCRIPTS/rev-seat.sh" codex-sol "$W" blocked "$W/p.md" > "$T/reserve.out" 2>&1 &
  reserve_pid=$!
  while [ ! -e "$T/reserve.ready" ] && kill -0 "$reserve_pid" 2>/dev/null && [ "$i" -lt 100 ]; do
    sleep 0.02; i=$((i + 1))
  done
  if [ ! -e "$T/reserve.ready" ]; then
    fail "reserve test reaches the blocked reservation" "wrapper exited before reservation"
  elif [ ! -e "$W/rblocked-codex-sol.exit" ]; then
    ok "same-label stale exit is clear while reservation is pending"
  else
    fail "same-label stale exit is clear while reservation is pending" "old exit remained observable"
  fi
  : > "$T/reserve.release"
  wait "$reserve_pid"; reserve_rc=$?
  assert_eq "blocked cap refusal exits with reserve status" "$reserve_rc" 7
  assert_grep "blocked cap refusal publishes a fresh exit" "$W/rblocked-codex-sol.exit" '^7$'
  assert_grep "blocked cap refusal persists its diagnostic" \
    "$W/rblocked-codex-sol.log" '^persistent provider-call cap reached for this seat generation$'
  seat_env_reset "$_path"
}
test_seat_process_group_cancellation_preserves_partial_stream() {
  local _path="$PATH"; seat_env
  local S="$T/seat-cancel"; seat_roster "$S"; echo "review the diff" > "$S/p.md"
  local child_file="$T/seat-cancel-child.pid" leader pgid child i=0
  set -m
  SHIM_MODE=hang_with_child SHIM_CHILD_PID_FILE="$child_file" \
    "$SCRIPTS/rev-seat.sh" codex-sol "$S" kill "$S/p.md" > "$T/seat-cancel.out" 2>&1 &
  leader=$!
  while [ ! -s "$child_file" ] && kill -0 "$leader" 2>/dev/null && [ "$i" -lt 100 ]; do
    sleep 0.1; i=$((i + 1))
  done
  if [ ! -s "$child_file" ]; then
    fail "cancellation shim records its sleeping descendant" "leader exited before publishing a child PID"
    kill -9 "$leader" 2>/dev/null || true
    wait "$leader" 2>/dev/null || true
    set +m
    seat_env_reset "$_path"
    return
  fi
  child=$(cat "$child_file")
  pgid=$(ps -o pgid= -p "$leader" | tr -d ' ')
  assert_eq "rev-seat background job owns its process group" "$pgid" "$leader"
  kill -TERM "-$pgid" 2>/dev/null || true
  wait "$leader" 2>/dev/null || true
  set +m
  i=0
  while kill -0 "$child" 2>/dev/null && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
  if kill -0 "$leader" 2>/dev/null; then fail "cancellation kills the rev-seat leader" "PID $leader remains"; else ok "cancellation kills the rev-seat leader"; fi
  if kill -0 "$child" 2>/dev/null; then
    fail "cancellation reaches the provider descendant" "PID $child remains"
    kill -9 "$child" 2>/dev/null || true
  else
    ok "cancellation reaches the provider descendant"
  fi
  assert_grep "cancellation retains the partial provider stream" \
    "$S/rkill-codex-sol.stream.ndjson" '"type":"item.started"'
  seat_env_reset "$_path"
}

test_session_audit_stop_serializes_reservations() {
  ( local session="$T/session-stop-reservations" prompt="$T/session-stop.prompt.md"
    local lock="$session/attempts/.session.lock" ready="$T/session-stop.ready" release="$T/session-stop.release"
    mkdir -p "$session/attempts"; printf 'review\n' > "$prompt"
    python3 - "$lock" "$ready" "$release" <<'PY' &
import fcntl
import os
from pathlib import Path
import sys
import time

lock, ready, release = map(Path, sys.argv[1:])
descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(descriptor, fcntl.LOCK_EX)
ready.touch()
while not release.exists():
    time.sleep(0.01)
PY
    local lock_pid=$!
    local i=0
    while [ ! -e "$ready" ] && kill -0 "$lock_pid" 2>/dev/null && [ "$i" -lt 100 ]; do
      sleep 0.02; i=$((i + 1))
    done
    python3 "$SCRIPTS/lib/rev-attempt.py" stop "$session" r1 --reason "hard evidence audit failed" >/dev/null 2>&1 &
    local stop_pid=$!
    sleep 0.05
    assert_exit "stop waits for the held session lock" 1 test -e "$session/attempts/session.stopped.json"
    python3 "$SCRIPTS/lib/rev-attempt.py" reserve "$session" r2 codex-sol "$prompt" >/dev/null 2>&1 &
    local r2_pid=$!
    python3 "$SCRIPTS/lib/rev-attempt.py" reserve "$session" r3 codex-terra "$prompt" >/dev/null 2>&1 &
    local r3_pid=$!
    : > "$release"
    wait "$lock_pid"; assert_eq "race lock holder releases" "$?" 0
    wait "$stop_pid"; assert_eq "hard evidence audit stop completes" "$?" 0
    wait "$r2_pid"; local r2_rc=$?
    wait "$r3_pid"; local r3_rc=$?
    case "$r2_rc" in 0|2) ok "first reservation races the stop";; *) fail "first reservation races the stop" "exit $r2_rc";; esac
    case "$r3_rc" in 0|2) ok "second reservation races the stop";; *) fail "second reservation races the stop" "exit $r3_rc";; esac
    assert_exit "no reservation is created after the session marker" 0 python3 - "$session/attempts" <<'PY'
from pathlib import Path
import sys

attempts = Path(sys.argv[1])
marker = attempts / 'session.stopped.json'
if not marker.is_file():
    raise SystemExit(1)
marker_time = marker.stat().st_mtime_ns
for reservation in attempts.glob('*.json'):
    if reservation.name.endswith('stopped.json'):
        continue
    if reservation.stat().st_mtime_ns > marker_time:
        raise SystemExit(1)
PY

    session="$T/session-stop-panel-lock"
    lock="$session/attempts/.panel-$(printf r1 | shasum -a 256 | awk '{print $1}').lock"
    ready="$T/session-panel-stop.ready"
    release="$T/session-panel-stop.release"
    mkdir -p "$session/attempts"
    python3 - "$lock" "$ready" "$release" <<'PY' &
import fcntl
import os
from pathlib import Path
import sys
import time

lock, ready, release = map(Path, sys.argv[1:])
descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(descriptor, fcntl.LOCK_EX)
ready.touch()
while not release.exists():
    time.sleep(0.01)
PY
    lock_pid=$!
    i=0
    while [ ! -e "$ready" ] && kill -0 "$lock_pid" 2>/dev/null && [ "$i" -lt 100 ]; do
      sleep 0.02; i=$((i + 1))
    done
    python3 "$SCRIPTS/lib/rev-attempt.py" stop "$session" r1 \
      --reason "hard evidence audit failed" >/dev/null 2>&1 &
    stop_pid=$!
    i=0
    while [ ! -e "$session/attempts/session.stopped.json" ] \
        && kill -0 "$stop_pid" 2>/dev/null && [ "$i" -lt 100 ]; do
      sleep 0.02; i=$((i + 1))
    done
    assert_exit "session stop is durable before the panel lock is acquired" 0 \
      test -s "$session/attempts/session.stopped.json"
    kill -TERM "$stop_pid" 2>/dev/null || true
    wait "$stop_pid" 2>/dev/null || true
    : > "$release"
    wait "$lock_pid"; assert_eq "held panel lock releases after stop interruption" "$?" 0
    python3 "$SCRIPTS/lib/rev-attempt.py" reserve "$session" r2 codex-sol "$prompt" \
      >"$T/session-panel-stop.out" 2>"$T/session-panel-stop.err"
    assert_eq "interrupted panel-marker write leaves the session stopped" "$?" 2
  )
}
