# tests for Task 4 — sourced by run-tests.sh
test_status() {
  local S="$T/status-sess"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=2 min_rounds=7 phase=collect 'seats=["codex-sol","codex-terra","grok","opus"]' open.P0=0 open.P1=1 open.P2=3 fixed=4 'dropped=["codex-terra"]' >/dev/null
  # sol: done with 1 finding, started 9 minutes ago, finished 2 minutes ago
  cp "$FX/findings-valid.json" "$S/r2-codex-sol.json"; echo 0 > "$S/r2-codex-sol.exit"; : > "$S/r2-codex-sol.prompt.md"
  touch -t "$(date -v-9M +%Y%m%d%H%M.%S)" "$S/r2-codex-sol.prompt.md"; touch -t "$(date -v-2M +%Y%m%d%H%M.%S)" "$S/r2-codex-sol.exit"
  # grok: running, last action from the log
  : > "$S/r2-grok.prompt.md"; touch -t "$(date -v-14M +%Y%m%d%H%M.%S)" "$S/r2-grok.prompt.md"
  printf 'tool_call shell: git diff abc --stat\ntext: thinking\ntool_call shell: rg "retry" src/api\n' > "$S/r2-grok.log"
  # opus: running, transcript present
  : > "$S/r2-opus.prompt.md"; touch -t "$(date -v-5M +%Y%m%d%H%M.%S)" "$S/r2-opus.prompt.md"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}\n{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Grep","input":{}}]}}\n' > "$T/opus.jsonl"
  "$SCRIPTS/rev-state.sh" "$S" "opus_transcript=$T/opus.jsonl" >/dev/null
  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"
  assert_eq "single line" "$(printf '%s' "$line" | wc -l | tr -d ' ')" "0"
  [ "${#line}" -le 220 ] && ok "≤220 chars" || fail "≤220 chars" "${#line}"
  echo "$line" > "$T/line"
  assert_grep "header" "$T/line" '^r2/7 collect \|'
  assert_grep "sol done with duration" "$T/line" 'sol: done 1f 7m'
  assert_grep "terra dropped" "$T/line" 'terra: dropped'
  assert_grep "grok running with last action" "$T/line" 'grok: running 14m ← rg "retry" src/api'
  assert_grep "opus last tool from transcript" "$T/line" 'opus: running 5m ← Grep'
  assert_grep "totals" "$T/line" 'open P0:0 P1:1 P2:3 fixed 4$'
  echo 4 > "$S/r2-grok.exit"; echo "$("$SCRIPTS/rev-status.sh" "$S")" > "$T/line"
  assert_grep "failed seat" "$T/line" 'grok: failed exit=4'
  assert_exit "missing session → 1" 1 "$SCRIPTS/rev-status.sh" "$T/nope"
  mkdir -p "$T/empty-sess"; echo "$("$SCRIPTS/rev-status.sh" "$T/empty-sess")" > "$T/line"
  assert_grep "no state yet is still one line" "$T/line" '^r\?/\? setup'
}

# regression: the aggregate tail must survive a wide round (round 2/3 run a 5th seat)
test_status_overflow() {
  local S="$T/status-wide"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=3 min_rounds=7 phase=collect \
    'seats=["codex-sol","codex-terra","grok","opus","grok-code-review"]' \
    open.P0=2 open.P1=3 open.P2=4 fixed=9 >/dev/null
  local seat
  for seat in codex-sol codex-terra grok opus grok-code-review; do
    : > "$S/r3-$seat.prompt.md"; touch -t "$(date -v-11M +%Y%m%d%H%M.%S)" "$S/r3-$seat.prompt.md"
    printf 'tool_call shell: rg "retry|timeout|backoff" src/api/handlers --stats\n' > "$S/r3-$seat.log"
  done
  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"
  echo "$line" > "$T/wline"
  [ "${#line}" -le 220 ] && ok "5 seats ≤220 chars" || fail "5 seats ≤220 chars" "${#line}"
  assert_eq "5 seats single line" "$(printf '%s' "$line" | wc -l | tr -d ' ')" "0"
  assert_grep "5th seat present" "$T/wline" 'grok-cr: running 11m'
  assert_grep "tail survives 5 seats" "$T/wline" 'open P0:2 P1:3 P2:4 fixed 9$'
  assert_grep "actions still shown" "$T/wline" 'sol: running 11m ← rg'
  # pathological width: seats are elided with a marker, header and tail still intact
  local W="$T/status-huge"; mkdir -p "$W"
  "$SCRIPTS/rev-state.sh" "$W" round=3 min_rounds=7 phase=collect \
    'seats=["reviewer-seat-alpha","reviewer-seat-bravo","reviewer-seat-charlie","reviewer-seat-delta","reviewer-seat-echo","reviewer-seat-foxtrot","reviewer-seat-golf","reviewer-seat-hotel"]' \
    open.P0=1 open.P1=2 open.P2=3 fixed=5 >/dev/null
  for seat in alpha bravo charlie delta echo foxtrot golf hotel; do
    : > "$W/r3-reviewer-seat-$seat.prompt.md"
    touch -t "$(date -v-7M +%Y%m%d%H%M.%S)" "$W/r3-reviewer-seat-$seat.prompt.md"
    printf 'tool_call shell: rg "retry|timeout|backoff" src/api/handlers --stats\n' > "$W/r3-reviewer-seat-$seat.log"
  done
  line=$("$SCRIPTS/rev-status.sh" "$W"); echo "    $line"; echo "$line" > "$T/hline"
  [ "${#line}" -le 220 ] && ok "8 seats ≤220 chars" || fail "8 seats ≤220 chars" "${#line}"
  assert_grep "elision marker" "$T/hline" '\+[0-9]+ seats \|'
  assert_grep "tail survives elision" "$T/hline" 'open P0:1 P1:2 P2:3 fixed 5$'
  assert_grep "header survives elision" "$T/hline" '^r3/7 collect \|'
}
