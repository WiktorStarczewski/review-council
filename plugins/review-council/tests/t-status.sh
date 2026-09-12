# rev-status.sh - the one-line status tick.
# Ageing a file is BSD-only as `date -v`; it goes through compat.sh so this suite runs on Linux too.
. "$SCRIPTS/lib/compat.sh"
test_status() {
  local S="$T/status-sess"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=2 min_rounds=7 phase=collect 'seats=["codex-sol","codex-terra","grok","opus"]' open.P0=0 open.P1=1 open.P2=3 fixed=4 'dropped=["codex-terra"]' >/dev/null
  # sol: done with 1 finding, started 9 minutes ago, finished 2 minutes ago
  cp "$FX/findings-valid.json" "$S/r2-codex-sol.json"; echo 0 > "$S/r2-codex-sol.exit"; : > "$S/r2-codex-sol.prompt.md"
  rc_touch_ago 540 "$S/r2-codex-sol.prompt.md"; rc_touch_ago 120 "$S/r2-codex-sol.exit"
  # grok: running, last action from the log
  : > "$S/r2-grok.prompt.md"; rc_touch_ago 840 "$S/r2-grok.prompt.md"
  printf 'tool_call shell: git diff abc --stat\ntext: thinking\ntool_call shell: rg "retry" src/api\n' > "$S/r2-grok.log"
  # opus: running, transcript present
  : > "$S/r2-opus.prompt.md"; rc_touch_ago 300 "$S/r2-opus.prompt.md"
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
  assert_grep "opus last tool from legacy transcript" "$T/line" 'opus: running 5m ← Grep'
  assert_grep "totals" "$T/line" 'open P0:0 P1:1 P2:3 fixed 4$'
  echo 4 > "$S/r2-grok.exit"; echo "$("$SCRIPTS/rev-status.sh" "$S")" > "$T/line"
  assert_grep "failed seat" "$T/line" 'grok: failed exit=4'
  assert_exit "missing session → 1" 1 "$SCRIPTS/rev-status.sh" "$T/nope"
  mkdir -p "$T/empty-sess"; echo "$("$SCRIPTS/rev-status.sh" "$T/empty-sess")" > "$T/line"
  assert_grep "no state yet is still one line" "$T/line" '^r\?/\? setup'
}

test_status_agent_transcripts() {
  local S="$T/status-agent-transcripts"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=4 min_rounds=4 phase=collect \
    'seats=["opus","opus-2"]' open.P0=0 open.P1=0 open.P2=0 fixed=2 >/dev/null
  : > "$S/r4-opus.prompt.md"; rc_touch_ago 360 "$S/r4-opus.prompt.md"
  : > "$S/r4-opus-2.prompt.md"; rc_touch_ago 420 "$S/r4-opus-2.prompt.md"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}\n' > "$T/opus-mapped.jsonl"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Glob","input":{}}]}}\n' > "$T/opus-2-mapped.jsonl"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"LegacyIgnored","input":{}}]}}\n' > "$T/opus-legacy-shadow.jsonl"
  "$SCRIPTS/rev-state.sh" "$S" \
    "agent_transcripts={\"opus\":\"$T/opus-mapped.jsonl\",\"opus-2\":\"$T/opus-2-mapped.jsonl\"}" \
    "opus_transcript=$T/opus-legacy-shadow.jsonl" >/dev/null

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/agent-line"
  [ "${#line}" -le 220 ] && ok "mapped Agent status ≤220 chars" || fail "mapped Agent status ≤220 chars" "${#line}"
  assert_grep "mapped opus action" "$T/agent-line" 'opus: running 6m ← Read'
  assert_grep "mapped opus-2 action" "$T/agent-line" 'opus-2: running 7m ← Glob'
  assert_nogrep "mapped opus wins over legacy scalar" "$T/agent-line" 'LegacyIgnored'
}

test_status_source_fallthrough() {
  local S="$T/status-fallthrough"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=6 min_rounds=adaptive phase=collect \
    'seats=["opus"]' open.P0=0 open.P1=0 open.P2=0 fixed=2 >/dev/null
  : > "$S/r6-opus.prompt.md"; rc_touch_ago 180 "$S/r6-opus.prompt.md"
  printf 'tool_call shell: rg "cli-fallback" src\n' > "$S/r6-opus.log"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"LegacyRead","input":{}}]}}\n' \
    > "$T/status-legacy-valid.jsonl"
  : > "$T/status-empty.jsonl"
  printf '{"type":"assistant","message":{"content":[{"type":"text","text":"thinking"}]}}\n' \
    > "$T/status-actionless.jsonl"

  local mapped label line
  for label in missing empty actionless; do
    case "$label" in
      missing) mapped="$T/status-missing.jsonl";;
      empty) mapped="$T/status-empty.jsonl";;
      actionless) mapped="$T/status-actionless.jsonl";;
    esac
    "$SCRIPTS/rev-state.sh" "$S" \
      "agent_transcripts={\"opus\":\"$mapped\"}" \
      "opus_transcript=$T/status-legacy-valid.jsonl" >/dev/null
    line=$("$SCRIPTS/rev-status.sh" "$S"); printf '%s\n' "$line" > "$T/status-fallthrough-line"
    assert_grep "$label mapped transcript falls through to legacy" "$T/status-fallthrough-line" \
      'opus: running 3m .* LegacyRead'
  done

  local legacy legacy_label
  for label in missing empty actionless; do
    case "$label" in
      missing) mapped="$T/status-mapped-missing.jsonl";;
      empty) mapped="$T/status-empty.jsonl";;
      actionless) mapped="$T/status-actionless.jsonl";;
    esac
    for legacy_label in missing empty actionless; do
      case "$legacy_label" in
        missing) legacy="$T/status-legacy-missing.jsonl";;
        empty) legacy="$T/status-empty.jsonl";;
        actionless) legacy="$T/status-actionless.jsonl";;
      esac
      "$SCRIPTS/rev-state.sh" "$S" \
        "agent_transcripts={\"opus\":\"$mapped\"}" "opus_transcript=$legacy" >/dev/null
      line=$("$SCRIPTS/rev-status.sh" "$S"); printf '%s\n' "$line" > "$T/status-fallthrough-line"
      assert_grep "$label mapped and $legacy_label legacy transcripts fall through to CLI" \
        "$T/status-fallthrough-line" 'opus: running 3m .* rg "cli-fallback" src'
      [ "${#line}" -le 220 ] && ok "$label/$legacy_label fallback stays within 220 chars" \
        || fail "$label/$legacy_label fallback stays within 220 chars" "${#line}"
    done
  done

  "$SCRIPTS/rev-state.sh" "$S" 'seats=["opus-2"]' \
    "agent_transcripts={\"opus-2\":\"$T/status-actionless.jsonl\"}" >/dev/null
  : > "$S/r6-opus-2.prompt.md"; rc_touch_ago 180 "$S/r6-opus-2.prompt.md"
  printf 'tool_call shell: rg "non-opus-fallback" tests\n' > "$S/r6-opus-2.log"
  line=$("$SCRIPTS/rev-status.sh" "$S"); printf '%s\n' "$line" > "$T/status-fallthrough-line"
  assert_grep "non-Opus actionless mapping falls through to CLI" "$T/status-fallthrough-line" \
    'opus-2: running 3m .* rg "non-opus-fallback" tests'
}

test_status_unmapped_opus_cli_logs() {
  local S="$T/status-opus-cli"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=5 min_rounds=5 phase=collect \
    'seats=["opus","opus-2"]' open.P0=0 open.P1=0 open.P2=1 fixed=3 >/dev/null
  : > "$S/r5-opus.prompt.md"; rc_touch_ago 480 "$S/r5-opus.prompt.md"
  : > "$S/r5-opus-2.prompt.md"; rc_touch_ago 540 "$S/r5-opus-2.prompt.md"
  printf 'tool_call shell: rg "first-opus-action" src\n' > "$S/r5-opus.log"
  printf 'tool_call shell: rg "second-opus-action" tests\n' > "$S/r5-opus-2.log"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/cli-line"
  [ "${#line}" -le 220 ] && ok "unmapped CLI status ≤220 chars" || fail "unmapped CLI status ≤220 chars" "${#line}"
  assert_grep "unmapped opus uses own CLI log" "$T/cli-line" 'opus: running 8m ← rg "first-opus-action" src'
  assert_grep "unmapped opus-2 uses own CLI log" "$T/cli-line" 'opus-2: running 9m ← rg "second-opus-action" tests'
}

test_status_repair_label() {
  local S="$T/status-repair"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=3x min_rounds=adaptive phase=repair \
    'seats=["opus-2"]' open.P0=0 open.P1=0 open.P2=0 fixed=4 >/dev/null
  : > "$S/r3x-opus-2.prompt.md"; rc_touch_ago 180 "$S/r3x-opus-2.prompt.md"
  printf 'tool_call shell: rg "missing-bundle" src\n' > "$S/r3x-opus-2.log"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/repair-line"
  [ "${#line}" -le 220 ] && ok "repair status ≤220 chars" || fail "repair status ≤220 chars" "${#line}"
  assert_grep "repair header uses artifact label" "$T/repair-line" '^r3x/adaptive repair \|'
  assert_grep "repair seat is running rather than pending" "$T/repair-line" 'opus-2: running 3m ← rg "missing-bundle" src'
  assert_nogrep "repair seat is not pending" "$T/repair-line" 'pending'
}

test_status_post_extra_exact_seats() {
  local S="$T/status-after-extra"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=4 min_rounds=4 phase=collect \
    'seats=["codex-sol","grok"]' open.P0=0 open.P1=0 open.P2=0 fixed=5 >/dev/null
  cp "$FX/findings-valid.json" "$S/r4-codex-sol.json"
  cp "$FX/findings-valid.json" "$S/r4-grok.json"
  echo 0 > "$S/r4-codex-sol.exit"; echo 0 > "$S/r4-grok.exit"
  : > "$S/r4-codex-sol.prompt.md"; : > "$S/r4-grok.prompt.md"
  : > "$S/r3-codex-review.prompt.md"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/post-extra-line"
  [ "${#line}" -le 220 ] && ok "post-extra status ≤220 chars" || fail "post-extra status ≤220 chars" "${#line}"
  assert_grep "current core seats are complete" "$T/post-extra-line" 'sol: done 1f 0m \| grok: done 1f 0m'
  assert_nogrep "prior extra does not leak into status" "$T/post-extra-line" 'codex-review|cx-rev'
  assert_nogrep "completed panel has no pending seat" "$T/post-extra-line" 'pending'
}

# regression: the aggregate tail must survive a wide round (round 2/3 run a 5th seat)
test_status_overflow() {
  local S="$T/status-wide"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=3 min_rounds=7 phase=collect \
    'seats=["codex-sol","codex-terra","grok","opus","grok-code-review"]' \
    open.P0=2 open.P1=3 open.P2=4 fixed=9 >/dev/null
  local seat
  for seat in codex-sol codex-terra grok opus grok-code-review; do
    : > "$S/r3-$seat.prompt.md"; rc_touch_ago 660 "$S/r3-$seat.prompt.md"
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
    rc_touch_ago 420 "$W/r3-reviewer-seat-$seat.prompt.md"
    printf 'tool_call shell: rg "retry|timeout|backoff" src/api/handlers --stats\n' > "$W/r3-reviewer-seat-$seat.log"
  done
  line=$("$SCRIPTS/rev-status.sh" "$W"); echo "    $line"; echo "$line" > "$T/hline"
  [ "${#line}" -le 220 ] && ok "8 seats ≤220 chars" || fail "8 seats ≤220 chars" "${#line}"
  assert_grep "elision marker" "$T/hline" '\+[0-9]+ seats \|'
  assert_grep "tail survives elision" "$T/hline" 'open P0:1 P1:2 P2:3 fixed 5$'
  assert_grep "header survives elision" "$T/hline" '^r3/7 collect \|'
}
