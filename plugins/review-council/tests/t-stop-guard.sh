# tests for the Stop hook - sourced by run-tests.sh
#
# The guard blocks a turn, so its failure mode is asymmetric: a guard that wrongly blocks traps
# the user behind a cap, while one that wrongly allows only misses. Every case below therefore
# pins a fail-OPEN path, plus the one case that must actually block and the cap that releases it.
STOP_HOOK_SRC="$SK/hooks/stop-session-guard"

# run_stop_guard <state-root> <count-dir> - runs the hook with review sessions discovered under
# <state-root>. The hook searches /tmp and /private/tmp, so a case that needs a session creates it
# there under a rev-* directory and removes it again.
stop_guard_decision() {  # stop_guard_decision <out.json> -> block | allow
  python3 -c '
import json, sys
raw = open(sys.argv[1]).read().strip()
if not raw:
    print("allow"); sys.exit(0)
try:
    d = json.loads(raw)
except Exception:
    print("invalid"); sys.exit(0)
print("block" if d.get("decision") == "block" else "allow")
' "$1"
}

mk_rev_session() {  # mk_rev_session <dir> <phase> [round] [root] - state.json (+ scope.env if root)
  mkdir -p "$1"
  [ -n "${4:-}" ] && printf "REV_ROOT='%s'\n" "$4" > "$1/scope.env"
  python3 -c '
import json, sys
json.dump({"round": sys.argv[3], "phase": sys.argv[2], "seats": [], "open": {"P0": 0, "P1": 1, "P2": 0}},
          open(sys.argv[1] + "/state.json", "w"))
' "$1" "$2" "${3:-1}"
}

test_stop_guard_allows_with_no_session() {
  ( local C="$T/sg-none-count"
    REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" </dev/null > "$T/sg1.json" 2>"$T/sg1.err"; local rc=$?
    assert_eq "exits 0 with no review session" "$rc" 0
    assert_eq "allows with no review session" "$(stop_guard_decision "$T/sg1.json")" allow )
}

test_stop_guard_allows_when_phase_done() {
  ( local D; D=$(mktemp -d /tmp/rev-sgdone.XXXXXX); local C="$T/sg-done-count"
    mk_rev_session "$D" done
    REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" </dev/null > "$T/sg2.json" 2>/dev/null
    assert_eq "allows when the newest live session is done" "$(stop_guard_decision "$T/sg2.json")" allow
    rm -rf "$D" )
}

test_stop_guard_blocks_mid_run() {
  ( local D; D=$(mktemp -d /tmp/rev-sgrun.XXXXXX); local C="$T/sg-run-count"
    mk_rev_session "$D" fix 2
    REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" </dev/null > "$T/sg3.json" 2>/dev/null
    assert_eq "blocks while a session is mid-run" "$(stop_guard_decision "$T/sg3.json")" block
    if grep -q 'phase=fix' "$T/sg3.json"; then ok "names the phase in the reason"
    else fail "names the phase in the reason" "$(cat "$T/sg3.json")"; fi
    rm -rf "$D" )
}

test_stop_guard_releases_at_the_cap() {
  ( local D; D=$(mktemp -d /tmp/rev-sgcap.XXXXXX); local C="$T/sg-cap-count"
    mk_rev_session "$D" fix 2
    local last=block
    for _ in 1 2 3 4; do
      REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" </dev/null > "$T/sg4.json" 2>/dev/null
      last=$(stop_guard_decision "$T/sg4.json")
    done
    assert_eq "allows once the consecutive-block cap is reached" "$last" allow
    rm -rf "$D" )
}

test_stop_guard_allows_when_counter_unwritable() {
  # The cap depends on the counter. If it cannot be persisted the guard must allow, never block
  # uncapped - this is the case that would otherwise trap a user with no escape.
  ( local D; D=$(mktemp -d /tmp/rev-sgro.XXXXXX); local C="$T/sg-ro/state"
    mk_rev_session "$D" fix 2
    mkdir -p "$T/sg-ro"; : > "$T/sg-ro/state"   # a FILE where the hook wants a directory
    REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" </dev/null > "$T/sg5.json" 2>/dev/null
    assert_eq "allows when the counter cannot be persisted" "$(stop_guard_decision "$T/sg5.json")" allow
    rm -rf "$D" )
}

test_stop_guard_ignores_a_review_of_another_tree() {
  # This machine runs concurrent sessions and /tmp is shared, so an unscoped guard blocks every
  # session for as long as ANY review is open anywhere. Observed live: a review of one repository
  # blocked a stop in an unrelated one.
  ( local D; D=$(mktemp -d /tmp/rev-sgother.XXXXXX); local C="$T/sg-other-count"
    local other="$T/other-tree"; mkdir -p "$other" "$T/my-tree"
    mk_rev_session "$D" collect 3 "$other"
    printf '{"cwd":"%s","hook_event_name":"Stop"}' "$T/my-tree" \
      | REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" > "$T/sg6.json" 2>/dev/null
    assert_eq "allows when the live review is of another working tree" \
      "$(stop_guard_decision "$T/sg6.json")" allow
    printf '{"cwd":"%s","hook_event_name":"Stop"}' "$other" \
      | REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" > "$T/sg7.json" 2>/dev/null
    assert_eq "still blocks inside the reviewed tree" \
      "$(stop_guard_decision "$T/sg7.json")" block
    rm -rf "$D" )
}

test_stop_guard_keeps_a_session_with_no_scope_env() {
  # Dropping a session whose scope.env is unreadable would silently disarm the guard, so an
  # unattributable review still blocks.
  ( local D; D=$(mktemp -d /tmp/rev-sgnoscope.XXXXXX); local C="$T/sg-noscope-count"
    mk_rev_session "$D" fix 2
    printf '{"cwd":"%s","hook_event_name":"Stop"}' "$T" \
      | REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" > "$T/sg8.json" 2>/dev/null
    assert_eq "blocks for a review with no readable scope.env" \
      "$(stop_guard_decision "$T/sg8.json")" block
    rm -rf "$D" )
}

test_stop_guard_does_not_hang_without_a_payload() {
  # The hook reads its cwd from the Stop payload on stdin. An unbounded read turns a missing or
  # never-closed stdin into a hang that burns the hook's whole timeout, so the read is bounded.
  ( local D; D=$(mktemp -d /tmp/rev-sghang.XXXXXX); local C="$T/sg-hang-count"
    mk_rev_session "$D" fix 2
    local start; start=$(date +%s)
    REVIEW_COUNCIL_STATE_DIR="$C" "$STOP_HOOK_SRC" </dev/null > "$T/sg9.json" 2>/dev/null
    local elapsed=$(( $(date +%s) - start ))
    if [ "$elapsed" -le 5 ]; then ok "returns promptly with no payload (${elapsed}s)"
    else fail "returns promptly with no payload" "took ${elapsed}s"; fi
    rm -rf "$D" )
}

test_stop_guard_is_declared_in_hooks_json() {
  ( local decl; decl=$(python3 -c '
import json
d = json.load(open("'"$SK"'/.claude-plugin/hooks.json"))["hooks"]["Stop"][0]["hooks"][0]
print(d["command"])
' 2>/dev/null)
    assert_eq "hooks.json declares the Stop hook at the shipped path" \
      "$decl" '${CLAUDE_PLUGIN_ROOT}/hooks/stop-session-guard'
    if [ -x "$STOP_HOOK_SRC" ]; then ok "the shipped hook is executable"
    else fail "the shipped hook is executable" "not executable"; fi )
}
