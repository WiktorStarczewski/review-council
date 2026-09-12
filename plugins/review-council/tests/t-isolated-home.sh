#!/bin/bash

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

test_isolated_home_path_lookup_is_pure() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" path
    path=$(python3 "$helper" path grok "$T/pure-seat") || return
    assert_exit "path lookup does not create the private home" 1 test -e "$path"
  )
}

test_isolated_home_lease_serializes_same_seat() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" identity="$T/leased-seat"
    local path ready1="$T/ready-1" ready2="$T/ready-2" first second
    path=$(python3 "$helper" path grok "$identity") || return

    python3 "$helper" hold grok "$path" --parent "$$" > "$ready1" & first=$!
    wait_for_file "$ready1" "$first" || return
    printf 'live\n' > "$path/live-state"

    python3 "$helper" hold grok "$path" --parent "$$" > "$ready2" & second=$!
    sleep 0.1
    assert_exit "second holder waits for the active lease" 1 test -s "$ready2"
    assert_exit "waiting holder does not delete live state" 0 test -e "$path/live-state"

    kill -TERM "$first"; wait "$first"
    wait_for_file "$ready2" "$second" || return
    assert_exit "next holder starts from a clean private home" 1 test -e "$path/live-state"
    kill -TERM "$second"; wait "$second"
    assert_exit "lease owner removes its private home on exit" 1 test -e "$path"
  )
}

test_isolated_home_sweep_uses_leases_not_age() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" active stale ready="$T/ready-sweep" holder
    active=$(python3 "$helper" path grok "$T/active-old") || return

    python3 "$helper" hold grok "$active" --parent "$$" > "$ready" & holder=$!
    wait_for_file "$ready" "$holder" || return
    stale=$(python3 "$helper" create grok "$T/stale-new") || return
    touch -t 197001010000 "$active"
    touch "$stale"

    python3 "$helper" sweep grok || return
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
    path=$(python3 "$helper" path grok "$T/crashed-seat") || return
    sleep 30 & parent=$!
    python3 "$helper" hold grok "$path" --parent "$parent" > "$ready" & holder=$!
    wait_for_file "$ready" "$holder" || return
    kill -KILL "$parent"; wait "$parent" >/dev/null 2>&1
    wait_for_exit "$holder" || { kill -KILL "$holder"; return 1; }
    wait "$holder"
    assert_exit "lease owner removes the private home after its parent crashes" 1 test -e "$path"
  )
}

test_isolated_home_leases_do_not_add_per_seat_files() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" path ready="$T/ready-registry" holder before after
    before=$(find "${TMPDIR:-/tmp}" -maxdepth 1 -name ".review-council-grok-$(id -u)-*.lease" | wc -l | tr -d ' ')
    path=$(python3 "$helper" path grok "$T/registry-seat") || return
    python3 "$helper" hold grok "$path" --parent "$$" > "$ready" & holder=$!
    wait_for_file "$ready" "$holder" || return
    kill -TERM "$holder"; wait "$holder"
    after=$(find "${TMPDIR:-/tmp}" -maxdepth 1 -name ".review-council-grok-$(id -u)-*.lease" | wc -l | tr -d ' ')
    assert_eq "per-home lease metadata does not accumulate" "$after" "$before"
  )
}

test_isolated_home_refuses_unsafe_cleanup_targets() {
  ( local helper="$SCRIPTS/lib/isolated-seat-home.py" path victim="$T/victim"
    path=$(python3 "$helper" path grok "$T/symlink-seat") || return
    mkdir -p "$victim"; printf 'keep\n' > "$victim/marker"
    ln -s "$victim" "$path"
    assert_exit "cleanup refuses a symlink in the private-home slot" 1 \
      python3 "$helper" clean grok "$path"
    assert_exit "refused symlink cleanup preserves its target" 0 test -e "$victim/marker"
    assert_exit "cleanup refuses a path outside the private-home namespace" 1 \
      python3 "$helper" clean grok "$victim"
  )
}

test_adapter_installs_cleanup_before_waiting_for_home_lease() {
  ( seat_env
    local helper="$SCRIPTS/lib/isolated-seat-home.py" session="$T/startup-trap"
    local out="$session/r1-codex-sol.json" path ready="$T/ready-blocker" blocker adapter
    mkdir -p "$session" "$T/codex-state"
    printf '{}\n' > "$T/codex-state/auth.json"
    printf 'prompt\n' > "$session/p.md"
    path=$(python3 "$helper" path codex "$out") || return
    python3 "$helper" hold codex "$path" --parent "$$" > "$ready" & blocker=$!
    wait_for_file "$ready" "$blocker" || return

    SEAT=codex-sol MODEL=gpt-5.6-sol EFFORT=max MODE=default ROOT="$T" \
      PROMPT="$session/p.md" SCHEMA="$SCRIPTS/../schema/findings.schema.json" \
      OUT="$out" LOG="$session/seat.log" RAW="$session/seat.ndjson" BASE=main \
      CODEX_HOME="$T/codex-state" SHIM_ARGS_FILE="$T/startup-args" \
      "$SCRIPTS/seats.d/codex.sh" >/dev/null 2>&1 & adapter=$!
    sleep 0.1
    kill -TERM "$adapter"; wait "$adapter"
    kill -TERM "$blocker"; wait "$blocker"
    sleep 0.1

    assert_exit "interrupted adapter never starts after a blocked lease becomes free" \
      1 test -e "$T/startup-args"
  )
}

test_adapter_preserves_grok_state_home() {
  ( seat_env; local session="$T/grok-auth" state="$T/grok-state"
    seat_roster "$session"; mkdir -p "$state"; printf 'prompt\n' > "$session/p.md"
    GROK_HOME="$state" SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" \
      grok "$session" 1 "$session/p.md" >/dev/null || return
    assert_grep "Grok keeps its signed-in state directory" "$T/args.env" "^GROK_HOME=$state$"
  )
}
