# rev-status.sh - the narrated one-line status tick.
# Ageing a file is BSD-only as `date -v`; it goes through compat.sh so this suite runs on Linux too.
. "$SCRIPTS/lib/compat.sh"
test_status() {
  local S="$T/status-sess"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=2 min_rounds=7 phase=collect 'seats=["codex-sol","codex-terra","sonnet","opus"]' open.P0=0 open.P1=1 open.P2=3 fixed=4 'dropped=["codex-terra"]' >/dev/null
  # sol: done with 1 finding, started 9 minutes ago, finished 2 minutes ago
  cp "$FX/findings-valid.json" "$S/r2-codex-sol.json"; echo 0 > "$S/r2-codex-sol.exit"; : > "$S/r2-codex-sol.prompt.md"
  rc_touch_ago 540 "$S/r2-codex-sol.prompt.md"; rc_touch_ago 120 "$S/r2-codex-sol.exit"
  # sonnet: running, last action from the log
  : > "$S/r2-sonnet.prompt.md"; rc_write_live_launch_marker "$S/r2-sonnet.started"; rc_touch_ago 840 "$S/r2-sonnet.started"
  printf 'tool_call shell: git diff abc --stat\ntext: thinking\ntool_call shell: rg "retry" src/api\n' > "$S/r2-sonnet.log"
  # opus: running, transcript present
  : > "$S/r2-opus.prompt.md"; rc_write_live_launch_marker "$S/r2-opus.started"; rc_touch_ago 300 "$S/r2-opus.started"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}\n{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Grep","input":{}}]}}\n' > "$T/opus.jsonl"
  "$SCRIPTS/rev-state.sh" "$S" "opus_transcript=$T/opus.jsonl" >/dev/null
  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"
  assert_eq "single line" "$(printf '%s' "$line" | wc -l | tr -d ' ')" "0"
  [ "${#line}" -le 820 ] && ok "narrative status ≤820 chars" || fail "narrative status ≤820 chars" "${#line}"
  echo "$line" > "$T/line"
  assert_grep "header" "$T/line" '^r2/7 collect \|'
  assert_grep "narrates review phase and completed seats" "$T/line" 'Council is in collect, round 2 of 7: 1 of 4 review seats have returned results'
  assert_grep "narrates dropped seats" "$T/line" '1 reviewer seat was dropped'
  assert_grep "narrates the latest recorded reviewer action" "$T/line" 'sonnet is still reviewing; its last recorded step was rg "retry" src/api'
  assert_grep "surfaces a recent returned P1 finding" "$T/line" 'A recent returned report flags P1 at src/x.ts:10: loop skips the last element'
  assert_grep "sol done with duration" "$T/line" 'sol: done 1f 7m'
  assert_grep "terra dropped" "$T/line" 'terra: dropped'
  assert_grep "sonnet running with last action" "$T/line" 'sonnet: running 14m ← rg "retry" src/api'
  assert_grep "opus last tool from legacy transcript" "$T/line" 'opus: running 5m ← Grep'
  assert_grep "totals" "$T/line" 'open P0:0 P1:1 P2:3 fixed 4$'
  local Q="$T/status-prompt-only"; mkdir -p "$Q"
  "$SCRIPTS/rev-state.sh" "$Q" round=1 min_rounds=1 phase=fan-out \
    'seats=["terra","sonnet"]' open.P0=0 open.P1=0 open.P2=0 fixed=0 >/dev/null
  : > "$Q/r1-terra.prompt.md"
  : > "$Q/r1-sonnet.prompt.md"; rc_touch_ago 900 "$Q/r1-sonnet.prompt.md"
  rc_write_live_launch_marker "$Q/r1-sonnet.started"; rc_touch_ago 180 "$Q/r1-sonnet.started"
  line=$("$SCRIPTS/rev-status.sh" "$Q"); printf '%s\n' "$line" > "$T/prompt-only-line"
  assert_grep "a prepared prompt without launch evidence stays pending" "$T/prompt-only-line" 'terra: pending'
  assert_nogrep "a prompt alone is not narrated as an active review" "$T/prompt-only-line" 'terra: running|terra is still reviewing'
  assert_grep "a launch marker starts the running duration" "$T/prompt-only-line" 'sonnet: running 3m'
  echo 4 > "$S/r2-sonnet.exit"; echo "$("$SCRIPTS/rev-status.sh" "$S")" > "$T/line"
  assert_grep "failed seat" "$T/line" 'sonnet: failed exit=4'
  assert_exit "missing session → 1" 1 "$SCRIPTS/rev-status.sh" "$T/nope"
  "$SCRIPTS/rev-state.sh" "$S" seats=codex-sol >/dev/null
  echo "$("$SCRIPTS/rev-status.sh" "$S")" > "$T/line"
  assert_grep "a bare seats string is one seat" "$T/line" 'sol: done 1f'
  assert_nogrep "a bare seats string is never split into characters" "$T/line" '\| c: '
  "$SCRIPTS/rev-state.sh" "$S" 'seats=["codex-sol","codex-terra","sonnet","opus"]' >/dev/null
  mkdir -p "$T/empty-sess"; echo "$("$SCRIPTS/rev-status.sh" "$T/empty-sess")" > "$T/line"
  assert_grep "no state yet is still one line" "$T/line" '^r\?/\? setup'

  local P="$T/status-p3"; mkdir -p "$P"
  "$SCRIPTS/rev-state.sh" "$P" round=1 min_rounds=1 phase=triage \
    'seats=["opus"]' open.P0=0 open.P1=0 open.P2=0 open.P3=1 fixed=0 >/dev/null
  : > "$P/r1-opus.prompt.md"; echo 0 > "$P/r1-opus.exit"
  cat > "$P/r1-opus.json" <<'JSON'
{"summary":"A P3 note","findings":[{"severity":"P3","file":"src/style.ts","line_start":4,"line_end":4,"claim":"style-only observation","evidence":"fixture","suggested_fix":"","confidence":0.8}]}
JSON
  echo "$("$SCRIPTS/rev-status.sh" "$P")" > "$T/p3-line"
  assert_grep "P3 does not change the actionable finding summary" "$T/p3-line" 'No P0-P2 findings are currently recorded as open'
  assert_nogrep "P3 claims are omitted from live progress" "$T/p3-line" 'style-only observation|src/style.ts'

  local C="$T/status-collect-zero"; mkdir -p "$C"
  "$SCRIPTS/rev-state.sh" "$C" round=1 min_rounds=1 phase=collect \
    'seats=["opus"]' open.P0=0 open.P1=0 open.P2=0 fixed=0 >/dev/null
  : > "$C/r1-opus.prompt.md"; echo 0 > "$C/r1-opus.exit"
  cat > "$C/r1-opus.json" <<'JSON'
{"summary":"A returned P1 finding","findings":[{"severity":"P1","file":"src/pair.ts","line_start":14,"line_end":14,"claim":"pair validation is skipped","evidence":"fixture","suggested_fix":"","confidence":0.9}]}
JSON
  echo "$("$SCRIPTS/rev-status.sh" "$C")" > "$T/collect-zero-line"
  assert_grep "collect progress says returned findings await triage" "$T/collect-zero-line" '[Rr]eturned findings have not yet been triaged'
  assert_nogrep "collect progress does not call a returned P1 review clean" "$T/collect-zero-line" 'No P0-P2 findings remain open'

  local B="$T/status-brief"; mkdir -p "$B"; printf '{}\n' > "$B/state.json"
  python3 "$SCRIPTS/rev-brief.py" "$B" --host codex > "$T/brief.json"
  assert_grep "10-minute progress ticks are enabled by default" "$T/brief.json" '"status_tick": true'
  local H="$T/status-home"; mkdir -p "$H/.config/review-council"
  printf '{"status_tick": false}\n' > "$H/.config/review-council/config.json"
  env -u REVIEW_COUNCIL_CONFIG HOME="$H" python3 "$SCRIPTS/rev-brief.py" "$B" --host codex > "$T/brief.json"
  assert_grep "normal brief invocation honors the user's config opt-out" "$T/brief.json" '"status_tick": false'
  printf '{"status_tick": true}\n' > "$T/status-config.json"
  "$SCRIPTS/rev-state.sh" "$B" status_tick=false >/dev/null
  python3 "$SCRIPTS/rev-brief.py" "$B" --host codex --config "$T/status-config.json" > "$T/brief.json"
  assert_grep "session can opt out of default progress ticks" "$T/brief.json" '"status_tick": false'
}

test_status_detects_dead_cli_launches() {
  local S="$T/status-dead-launch"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=1 min_rounds=1 phase=collect \
    'seats=["codex-sol"]' open.P0=0 open.P1=0 open.P2=0 fixed=0 >/dev/null
  sleep 30 &
  local dead_pid=$! dead_started
  dead_started=$(LC_ALL=C ps -p "$dead_pid" -o lstart= 2>/dev/null)
  kill -KILL "$dead_pid" 2>/dev/null || true
  wait "$dead_pid" 2>/dev/null || true
  printf 'cli\n%s\n%s\n' "$dead_pid" "$dead_started" > "$S/r1-codex-sol.started"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/dead-launch-line"
  assert_grep "a force-terminated seat is reported as interrupted" "$T/dead-launch-line" \
    'codex-sol: interrupted'
  assert_nogrep "a dead launch marker is not narrated as active" "$T/dead-launch-line" \
    'codex-sol: running|codex-sol is still reviewing'
  python3 "$SCRIPTS/rev-context.py" "$S" --json > "$T/dead-launch-context.json"
  local context_status
  context_status=$(python3 - "$T/dead-launch-context.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['seats'][0]['status'])
PY
  )
  assert_eq "the session briefing also identifies a dead launch" "$context_status" interrupted
}

test_status_requires_an_agent_task_id() {
  local S="$T/status-agent-launch"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=1 min_rounds=1 phase=collect \
    'seats=["opus","opus-2","opus-3"]' open.P0=0 open.P1=0 open.P2=0 fixed=0 >/dev/null
  printf 'agent\nagent-task-123\n' > "$S/r1-opus.started"
  printf 'agent\n\n' > "$S/r1-opus-2.started"
  : > "$S/r1-opus-3.started"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/agent-launch-line"
  assert_grep "a stored Agent task ID identifies a launched seat" "$T/agent-launch-line" 'opus: running 0m'
  assert_grep "an empty Agent task ID is interrupted" "$T/agent-launch-line" 'opus-2: interrupted'
  assert_grep "an empty launch marker is interrupted" "$T/agent-launch-line" 'opus-3: interrupted'
  python3 "$SCRIPTS/rev-context.py" "$S" --json > "$T/agent-launch-context.json"
  python3 - "$T/agent-launch-context.json" <<'PY'
import json
import sys

statuses = {seat['seat']: seat['status'] for seat in json.load(open(sys.argv[1]))['seats']}
assert statuses == {'opus': 'running', 'opus-2': 'interrupted', 'opus-3': 'interrupted'}, statuses
PY
  assert_eq "the briefing uses the same Agent launch evidence" "$?" 0

  python3 - "$S" "$SCRIPTS/rev-context.py" <<'PY'
import importlib.util
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('rev_context_snapshot_test', sys.argv[2])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
marker = Path(sys.argv[1]) / 'snapshot.started'
replacement = marker.with_name('replacement.started')
marker.write_text('agent\n\n', encoding='utf-8')
replacement.write_text('agent\nagent-task-456\n', encoding='utf-8')
os.utime(marker, (100, 100))
os.utime(replacement, (200, 200))
real_open = os.open

def replace_after_open(path, flags, *args, **kwargs):
    descriptor = real_open(path, flags, *args, **kwargs)
    if Path(path) == marker:
        os.replace(replacement, marker)
    return descriptor

os.open = replace_after_open
try:
    state, started = module.launch_state_with_mtime(marker)
finally:
    os.open = real_open
assert state == 'interrupted', state
assert started == 100, started
assert module.launch_state(marker) == 'running'
assert marker.stat().st_mtime == 200
PY
  assert_eq "launch status and duration use one marker snapshot" "$?" 0
}

test_status_rejects_incomplete_or_invalid_results() {
  local S="$T/status-proof"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=1 min_rounds=1 phase=collect \
    'seats=["complete","incomplete","malformed"]' open.P0=0 open.P1=0 open.P2=0 fixed=0 >/dev/null
  cp "$FX/findings-valid.json" "$S/r1-complete.json"
  printf '%s\n' '{"summary":"INCOMPLETE PROOF: source remains unread","findings":[]}' > "$S/r1-incomplete.json"
  printf '%s\n' '{broken json' > "$S/r1-malformed.json"
  for seat in complete incomplete malformed; do echo 0 > "$S/r1-$seat.exit"; : > "$S/r1-$seat.prompt.md"; done

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/proof-line"
  assert_grep "only a schema-valid complete result counts as returned" "$T/proof-line" \
    'Council is in collect, round 1 of 1: 1 of 3 review seats have returned results'
  assert_grep "incomplete proof is reported separately" "$T/proof-line" 'incomplete: incomplete proof'
  assert_grep "malformed result is reported separately" "$T/proof-line" 'malformed: invalid result'
  assert_grep "invalid results are narrated as failed proof" "$T/proof-line" \
    '2 reviewer seats have failed or returned invalid proof'
  assert_nogrep "incomplete proof finding is not surfaced" "$T/proof-line" \
    'A recent returned report flags.*source remains unread'
}

test_status_agent_transcripts() {
  local S="$T/status-agent-transcripts"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=4 min_rounds=4 phase=collect \
    'seats=["opus","opus-2"]' open.P0=0 open.P1=0 open.P2=0 fixed=2 >/dev/null
  : > "$S/r4-opus.prompt.md"; rc_write_live_launch_marker "$S/r4-opus.started"; rc_touch_ago 360 "$S/r4-opus.started"
  : > "$S/r4-opus-2.prompt.md"; rc_write_live_launch_marker "$S/r4-opus-2.started"; rc_touch_ago 420 "$S/r4-opus-2.started"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}\n' > "$T/opus-mapped.jsonl"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Glob","input":{}}]}}\n' > "$T/opus-2-mapped.jsonl"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"LegacyIgnored","input":{}}]}}\n' > "$T/opus-legacy-shadow.jsonl"
  "$SCRIPTS/rev-state.sh" "$S" \
    "agent_transcripts={\"opus\":\"$T/opus-mapped.jsonl\",\"opus-2\":\"$T/opus-2-mapped.jsonl\"}" \
    "opus_transcript=$T/opus-legacy-shadow.jsonl" >/dev/null

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/agent-line"
  [ "${#line}" -le 820 ] && ok "mapped Agent status ≤820 chars" || fail "mapped Agent status ≤820 chars" "${#line}"
  assert_grep "mapped opus action" "$T/agent-line" 'opus: running 6m ← Read'
  assert_grep "mapped opus-2 action" "$T/agent-line" 'opus-2: running 7m ← Glob'
  assert_nogrep "mapped opus wins over legacy scalar" "$T/agent-line" 'LegacyIgnored'
}

test_status_source_fallthrough() {
  local S="$T/status-fallthrough"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=6 min_rounds=adaptive phase=collect \
    'seats=["opus"]' open.P0=0 open.P1=0 open.P2=0 fixed=2 >/dev/null
  : > "$S/r6-opus.prompt.md"; rc_write_live_launch_marker "$S/r6-opus.started"; rc_touch_ago 180 "$S/r6-opus.started"
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
      [ "${#line}" -le 820 ] && ok "$label/$legacy_label fallback stays within 820 chars" \
        || fail "$label/$legacy_label fallback stays within 820 chars" "${#line}"
    done
  done

  "$SCRIPTS/rev-state.sh" "$S" 'seats=["opus-2"]' \
    "agent_transcripts={\"opus-2\":\"$T/status-actionless.jsonl\"}" >/dev/null
  : > "$S/r6-opus-2.prompt.md"; rc_write_live_launch_marker "$S/r6-opus-2.started"; rc_touch_ago 180 "$S/r6-opus-2.started"
  printf 'tool_call shell: rg "non-opus-fallback" tests\n' > "$S/r6-opus-2.log"
  line=$("$SCRIPTS/rev-status.sh" "$S"); printf '%s\n' "$line" > "$T/status-fallthrough-line"
  assert_grep "non-Opus actionless mapping falls through to CLI" "$T/status-fallthrough-line" \
    'opus-2: running 3m .* rg "non-opus-fallback" tests'
}

test_status_unmapped_opus_cli_logs() {
  local S="$T/status-opus-cli"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=5 min_rounds=5 phase=collect \
    'seats=["opus","opus-2"]' open.P0=0 open.P1=0 open.P2=1 fixed=3 >/dev/null
  : > "$S/r5-opus.prompt.md"; rc_write_live_launch_marker "$S/r5-opus.started"; rc_touch_ago 480 "$S/r5-opus.started"
  : > "$S/r5-opus-2.prompt.md"; rc_write_live_launch_marker "$S/r5-opus-2.started"; rc_touch_ago 540 "$S/r5-opus-2.started"
  printf 'tool_call shell: rg "first-opus-action" src\n' > "$S/r5-opus.log"
  printf 'tool_call shell: rg "second-opus-action" tests\n' > "$S/r5-opus-2.log"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/cli-line"
  [ "${#line}" -le 820 ] && ok "unmapped CLI status ≤820 chars" || fail "unmapped CLI status ≤820 chars" "${#line}"
  assert_grep "unmapped opus uses own CLI log" "$T/cli-line" 'opus: running 8m ← rg "first-opus-action" src'
  assert_grep "unmapped opus-2 uses own CLI log" "$T/cli-line" 'opus-2: running 9m ← rg "second-opus-action" tests'
}

test_status_repair_label() {
  local S="$T/status-repair"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=3x min_rounds=adaptive phase=repair \
    'seats=["opus-2"]' open.P0=0 open.P1=0 open.P2=0 fixed=4 >/dev/null
  : > "$S/r3x-opus-2.prompt.md"; rc_write_live_launch_marker "$S/r3x-opus-2.started"; rc_touch_ago 180 "$S/r3x-opus-2.started"
  printf 'tool_call shell: rg "missing-bundle" src\n' > "$S/r3x-opus-2.log"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/repair-line"
  [ "${#line}" -le 820 ] && ok "repair status ≤820 chars" || fail "repair status ≤820 chars" "${#line}"
  assert_grep "repair header uses artifact label" "$T/repair-line" '^r3x/adaptive repair \|'
  assert_grep "repair seat is running rather than pending" "$T/repair-line" 'opus-2: running 3m ← rg "missing-bundle" src'
  assert_nogrep "repair seat is not pending" "$T/repair-line" 'pending'
}

test_status_post_extra_exact_seats() {
  local S="$T/status-after-extra"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=4 min_rounds=4 phase=collect \
    'seats=["codex-sol","codex-terra"]' open.P0=0 open.P1=0 open.P2=0 fixed=5 >/dev/null
  cp "$FX/findings-valid.json" "$S/r4-codex-sol.json"
  cp "$FX/findings-valid.json" "$S/r4-codex-terra.json"
  echo 0 > "$S/r4-codex-sol.exit"; echo 0 > "$S/r4-codex-terra.exit"
  : > "$S/r4-codex-sol.prompt.md"; : > "$S/r4-codex-terra.prompt.md"
  : > "$S/r3-codex-review.prompt.md"

  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"; echo "$line" > "$T/post-extra-line"
  [ "${#line}" -le 820 ] && ok "post-extra status ≤820 chars" || fail "post-extra status ≤820 chars" "${#line}"
  assert_grep "current core seats are complete" "$T/post-extra-line" 'sol: done 1f 0m \| terra: done 1f 0m'
  assert_nogrep "prior extra does not leak into status" "$T/post-extra-line" 'codex-review|cx-rev'
  assert_nogrep "completed panel has no pending seat" "$T/post-extra-line" 'pending'
}

# regression: the aggregate tail must survive a wide round (round 2/3 run a 5th seat)
test_status_overflow() {
  local S="$T/status-wide"; mkdir -p "$S"
  "$SCRIPTS/rev-state.sh" "$S" round=3 min_rounds=7 phase=collect \
    'seats=["codex-sol","codex-terra","gemini","opus","sonnet"]' \
    open.P0=2 open.P1=3 open.P2=4 fixed=9 >/dev/null
  local seat
  for seat in codex-sol codex-terra gemini opus sonnet; do
    : > "$S/r3-$seat.prompt.md"; rc_write_live_launch_marker "$S/r3-$seat.started"; rc_touch_ago 660 "$S/r3-$seat.started"
    printf 'tool_call shell: rg "retry|timeout|backoff" src/api/handlers --stats\n' > "$S/r3-$seat.log"
  done
  local line; line=$("$SCRIPTS/rev-status.sh" "$S"); echo "    $line"
  echo "$line" > "$T/wline"
  [ "${#line}" -le 820 ] && ok "5 seats ≤820 chars" || fail "5 seats ≤820 chars" "${#line}"
  assert_eq "5 seats single line" "$(printf '%s' "$line" | wc -l | tr -d ' ')" "0"
  assert_grep "5th seat present" "$T/wline" 'sonnet: running 11m'
  assert_grep "tail survives 5 seats" "$T/wline" 'open P0:2 P1:3 P2:4 fixed 9$'
  assert_grep "actions still shown" "$T/wline" 'sol: running 11m ← rg'
  # pathological width: seats are elided with a marker, header and tail still intact
  local W="$T/status-huge"; mkdir -p "$W"
  "$SCRIPTS/rev-state.sh" "$W" round=3 min_rounds=7 phase=collect \
    'seats=["reviewer-seat-alpha","reviewer-seat-bravo","reviewer-seat-charlie","reviewer-seat-delta","reviewer-seat-echo","reviewer-seat-foxtrot","reviewer-seat-golf","reviewer-seat-hotel"]' \
    open.P0=1 open.P1=2 open.P2=3 fixed=5 >/dev/null
  for seat in alpha bravo charlie delta echo foxtrot golf hotel; do
    : > "$W/r3-reviewer-seat-$seat.prompt.md"
    rc_write_live_launch_marker "$W/r3-reviewer-seat-$seat.started"
    rc_touch_ago 420 "$W/r3-reviewer-seat-$seat.started"
    printf 'tool_call shell: rg "retry|timeout|backoff" src/api/handlers --stats\n' > "$W/r3-reviewer-seat-$seat.log"
  done
  line=$("$SCRIPTS/rev-status.sh" "$W"); echo "    $line"; echo "$line" > "$T/hline"
  [ "${#line}" -le 820 ] && ok "8 seats ≤820 chars" || fail "8 seats ≤820 chars" "${#line}"
  assert_grep "elision marker" "$T/hline" '\+[0-9]+ seats \|'
  assert_grep "tail survives elision" "$T/hline" 'open P0:1 P1:2 P2:3 fixed 5$'
  assert_grep "header survives elision" "$T/hline" '^r3/7 collect \|'
}
