#!/bin/bash

test_isolated_home_rejects_retired_grok_kind() {
  python3 "$SCRIPTS/lib/isolated-seat-home.py" path grok retired \
    > "$T/retired-grok.out" 2> "$T/retired-grok.err"
  assert_eq "isolated homes reject the retired Grok kind" "$?" 2
  assert_eq "retired Grok gets no isolated home path" "$(cat "$T/retired-grok.out")" ""
}

wait_for_file() {
  local path=$1 pid=$2 attempts=0
  while [ ! -s "$path" ] && kill -0 "$pid" >/dev/null 2>&1 && [ "$attempts" -lt 100 ]; do
    sleep 0.02
    attempts=$((attempts + 1))
  done
  [ -s "$path" ]
}

wait_for_exit() {
  local pid=$1 attempts=0
  while kill -0 "$pid" >/dev/null 2>&1 && [ "$attempts" -lt 100 ]; do
    sleep 0.02
    attempts=$((attempts + 1))
  done
  ! kill -0 "$pid" >/dev/null 2>&1
}

probe_lease() {
  python3 - "$1" "$2" "$3" <<'PY'
import os
from pathlib import Path
import runpy
import sys

module = runpy.run_path(sys.argv[1])
descriptor = module['acquire_lease'](Path(sys.argv[2]), sys.argv[3], False)
if descriptor is None:
    print('blocked')
else:
    os.close(descriptor)
    print('acquired')
PY
}

wait_for_home_helper() {
  local parent=$1 attempts=0 child command
  while kill -0 "$parent" >/dev/null 2>&1 && [ "$attempts" -lt 100 ]; do
    for child in $(pgrep -P "$parent" 2>/dev/null); do
      command=$(ps -o command= -p "$child" 2>/dev/null)
      case "$command" in
        *isolated-seat-home.py*hold*) printf '%s\n' "$child"; return 0 ;;
      esac
    done
    sleep 0.02
    attempts=$((attempts + 1))
  done
  return 1
}

test_isolated_home_path_lookup_is_pure() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" path
    path=$(python3 "$helper" path codex "$T/pure-seat") || return
    assert_exit "path lookup does not create the private home" 1 test -e "$path"
  )
}

test_isolated_home_lease_serializes_same_seat() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" identity="$T/leased-seat"
    local path ready1="$T/ready-1" ready2="$T/ready-2" first second
    path=$(python3 "$helper" path codex "$identity") || return

    python3 "$helper" hold codex "$path" --parent "$$" > "$ready1" & first=$!
    wait_for_file "$ready1" "$first" || return
    printf 'live\n' > "$path/live-state"

    assert_eq "another process observes the active lease" \
      "$(probe_lease "$helper" "$path" codex)" blocked
    assert_exit "lease probe does not delete live state" 0 test -e "$path/live-state"

    kill -TERM "$first"; wait "$first"
    python3 "$helper" hold codex "$path" --parent "$$" > "$ready2" & second=$!
    wait_for_file "$ready2" "$second" || return
    assert_exit "next holder starts from a clean private home" 1 test -e "$path/live-state"
    kill -TERM "$second"; wait "$second"
    assert_exit "lease owner removes its private home on exit" 1 test -e "$path"
  )
}

test_isolated_home_sweep_uses_leases_not_age() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" active stale ready="$T/ready-sweep" holder
    active=$(python3 "$helper" path codex "$T/active-old") || return

    python3 "$helper" hold codex "$active" --parent "$$" > "$ready" & holder=$!
    wait_for_file "$ready" "$holder" || return
    stale=$(python3 "$helper" create codex "$T/stale-new") || return
    touch -t 197001010000 "$active"
    touch "$stale"

    python3 "$helper" sweep codex || return
    assert_exit "sweep retains an old home with an active lease" 0 test -d "$active"
    assert_exit "sweep removes a new home whose lease is free" 1 test -e "$stale"

    kill -TERM "$holder"; wait "$holder"
  )
}

test_isolated_home_hold_preserves_codex_auth() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" auth="$T/auth.json" path ready="$T/ready-auth" holder
    printf '{}\n' > "$auth"
    path=$(python3 "$helper" path codex "$T/auth-seat") || return
    python3 "$helper" hold codex "$path" --parent "$$" --auth "$auth" > "$ready" & holder=$!
    wait_for_file "$ready" "$holder" || return
    assert_exit "leased Codex home links the existing auth file" 0 test -L "$path/auth.json"
    assert_eq "leased Codex auth resolves to the source file" \
      "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$path/auth.json")" \
      "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$auth")"
    kill -TERM "$holder"; wait "$holder"
  )
}

test_isolated_home_lease_cleans_after_parent_crash() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" path ready="$T/ready-crash" parent holder
    path=$(python3 "$helper" path codex "$T/crashed-seat") || return
    sleep 30 & parent=$!
    python3 "$helper" hold codex "$path" --parent "$parent" > "$ready" & holder=$!
    wait_for_file "$ready" "$holder" || return
    kill -KILL "$parent"; wait "$parent" >/dev/null 2>&1
    wait_for_exit "$holder" || { kill -KILL "$holder"; return 1; }
    wait "$holder"
    assert_exit "lease owner removes the private home after its parent crashes" 1 test -e "$path"
  )
}

test_isolated_home_leases_do_not_add_per_seat_files() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" path ready="$T/ready-registry" holder before after
    before=$(find "${TMPDIR:-/tmp}" -maxdepth 1 -name ".review-council-codex-$(id -u)-*.lease" | wc -l | tr -d ' ')
    path=$(python3 "$helper" path codex "$T/registry-seat") || return
    python3 "$helper" hold codex "$path" --parent "$$" > "$ready" & holder=$!
    wait_for_file "$ready" "$holder" || return
    kill -TERM "$holder"; wait "$holder"
    after=$(find "${TMPDIR:-/tmp}" -maxdepth 1 -name ".review-council-codex-$(id -u)-*.lease" | wc -l | tr -d ' ')
    assert_eq "per-home lease metadata does not accumulate" "$after" "$before"
  )
}

test_isolated_home_refuses_unsafe_cleanup_targets() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" path victim="$T/victim"
    path=$(python3 "$helper" path codex "$T/symlink-seat") || return
    mkdir -p "$victim"; printf 'keep\n' > "$victim/marker"
    ln -s "$victim" "$path"
    assert_exit "cleanup refuses a symlink in the private-home slot" 1 \
      python3 "$helper" clean codex "$path"
    assert_exit "refused symlink cleanup preserves its target" 0 test -e "$victim/marker"
    assert_exit "cleanup refuses a path outside the private-home namespace" 1 \
      python3 "$helper" clean codex "$victim"
  )
}

test_adapter_installs_cleanup_before_waiting_for_home_lease() {
  ( seat_env
    local helper="$SCRIPTS/lib/isolated-seat-home.py" session out path ready blocker adapter
    local ready_dir args lease_child
    mkdir -p "$T/codex-state"
    printf '{}\n' > "$T/codex-state/auth.json"
    session="$T/startup-trap-codex"; out="$session/r1-codex.json"
    ready="$T/ready-blocker-codex"; ready_dir="$session/ready"; args="$T/startup-args-codex"
    mkdir -p "$session" "$ready_dir"
    printf 'prompt\n' > "$session/p.md"
    path=$(TMPDIR="$ready_dir" python3 "$helper" path codex "$out") || return
    TMPDIR="$ready_dir" python3 "$helper" hold codex "$path" --parent "$$" > "$ready" & blocker=$!
    wait_for_file "$ready" "$blocker" || return

    TMPDIR="$ready_dir" SEAT=codex-sol MODEL=gpt-5.6-sol EFFORT=max MODE=default ROOT="$T" \
      PROMPT="$session/p.md" SCHEMA="$SCRIPTS/../schema/findings.schema.json" \
      OUT="$out" LOG="$session/seat.log" RAW="$session/seat.ndjson" BASE=main \
      CODEX_HOME="$T/codex-state" SHIM_ARGS_FILE="$args" \
      "$SCRIPTS/seats.d/codex.sh" >/dev/null 2>&1 & adapter=$!
    lease_child=$(wait_for_home_helper "$adapter") || return
    kill -TERM "$adapter"; wait "$adapter"
    wait_for_exit "$lease_child" || return
    assert_eq "Codex adapter removes its lease-ready file on interruption" \
      "$(find "$ready_dir" -type f -name 'review-council-*-ready.*' | wc -l | tr -d ' ')" 0
    assert_exit "Codex adapter never starts while its lease is blocked" 1 test -e "$args"

    kill -TERM "$blocker"; wait "$blocker"
    assert_exit "Codex blocker cleanup removes the private home" 1 test -e "$path"
  )
}
