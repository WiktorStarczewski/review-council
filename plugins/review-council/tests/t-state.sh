# tests for Task 2 - sourced by run-tests.sh
test_state() {
  local S="$T/state-sess" ST="$SCRIPTS/rev-state.sh"
  "$ST" "$S" round=1 phase=fan-out min_rounds=7 >/dev/null
  assert_grep "creates state.json" "$S/state.json" '"round": 1'
  assert_grep "string value" "$S/state.json" '"phase": "fan-out"'
  "$ST" "$S" phase=triage open.P1=2 'seats=["codex-sol","codex-terra"]' last_commit=a1b2c3d >/dev/null
  assert_grep "merge keeps round" "$S/state.json" '"round": 1'
  assert_grep "overwrites phase" "$S/state.json" '"phase": "triage"'
  assert_grep "nested key" "$S/state.json" '"P1": 2'
  assert_grep "json list value" "$S/state.json" '"codex-terra"'
  assert_grep "sha stays string" "$S/state.json" '"last_commit": "a1b2c3d"'
  assert_exit "dotted path through scalar fails" 1 "$ST" "$S" round.sub=1
  assert_exit "usage without args fails" 1 "$ST"
}

# phase=fix with open P0-P2 findings needs a completed plan panel <N>p or a recorded skip line.
state_gate_refuses() {
  local name=$1 S=$2 round=$3; shift 3
  local before after rc
  before=$(cksum < "$S/state.json")
  "$SCRIPTS/rev-state.sh" "$S" "$@" > "$T/gate.out" 2> "$T/gate.err"; rc=$?
  after=$(cksum < "$S/state.json")
  assert_eq "$name: refused" "$rc" 2
  assert_eq "$name: state unchanged" "$after" "$before"
  assert_grep "$name: names the round" "$T/gate.err" "refusing phase=fix for round $round:"
  assert_grep "$name: names the plan panel way out" "$T/gate.err" "plan panel r${round}p"
  assert_grep "$name: names the skip-line way out" "$T/gate.err" "Plan panel r${round}p - SKIPPED: <reason>"
}

test_state_fix_gate() {
  local ST="$SCRIPTS/rev-state.sh" S

  S="$T/gate-refused"
  "$ST" "$S" round=3 phase=triage open.P0=0 open.P1=1 open.P2=0 >/dev/null
  state_gate_refuses "no plan and no skip" "$S" 3 phase=fix
  assert_grep "refusal keeps the triage phase" "$S/state.json" '"phase": "triage"'
  printf '# Findings ledger\n\n  Plan panel r3p - SKIPPED: indented\n> Plan panel r3p - SKIPPED: quoted\nPlan panel r13p - SKIPPED: other round\nPlan panel r3p - SKIPPED:   \n' > "$S/findings.md"
  state_gate_refuses "skip line must start the line, match the round, and carry a reason" "$S" 3 phase=fix
  printf 'Plan panel r3p - SKIPPED: every accepted fix is a one-line P2\n' >> "$S/findings.md"
  assert_exit "recorded skip line allows fix" 0 "$ST" "$S" phase=fix
  assert_grep "allowed fix is written" "$S/state.json" '"phase": "fix"'

  S="$T/gate-effective-counts"
  "$ST" "$S" round=2 phase=triage open.P1=1 >/dev/null
  assert_exit "counts cleared in the same call allow fix" 0 "$ST" "$S" phase=fix open.P1=0
  "$ST" "$S" phase=triage >/dev/null
  state_gate_refuses "counts raised in the same call" "$S" 2 phase=fix open.P2=1
  "$ST" "$S" open.P2=0 'open.P1="one"' >/dev/null
  local before rc
  before=$(cksum < "$S/state.json")
  "$ST" "$S" phase=fix > /dev/null 2> "$T/gate.err"; rc=$?
  assert_eq "a non-integer count fails closed" "$rc" 2
  assert_eq "a non-integer count leaves state unchanged" "$(cksum < "$S/state.json")" "$before"
  assert_grep "a non-integer count names its key" "$T/gate.err" "open.P1='one' is not a non-negative integer"

  S="$T/gate-one-seat-plan"
  "$ST" "$S" round=4 phase=triage open.P0=1 open.P1=2 >/dev/null
  "$ST" "$S" phase=plan round=4p 'seats=["codex-sol"]' >/dev/null
  assert_eq "plan launch persists its seats" \
    "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["plans"]["4p"])' "$S/state.json")" "['codex-sol']"
  state_gate_refuses "plan launched but not returned" "$S" 4 phase=fix
  printf '{"findings":[]}\n' > "$S/r4p-codex-sol.json"
  state_gate_refuses "plan result without an exit receipt" "$S" 4 phase=fix
  echo 0 > "$S/r4p-codex-sol.exit"
  assert_exit "completed one-seat plan allows fix" 0 "$ST" "$S" phase=fix
  assert_grep "fix after a plan panel is written" "$S/state.json" '"phase": "fix"'
  "$ST" "$S" round=5 phase=triage open.P1=1 >/dev/null
  state_gate_refuses "a completed plan for another round does not count" "$S" 5 phase=fix

  S="$T/gate-plan-seat-failed"
  "$ST" "$S" round=6 phase=triage open.P1=1 >/dev/null
  "$ST" "$S" phase=plan round=6p 'seats=["codex-sol","opus"]' >/dev/null
  printf '{"findings":[]}\n' > "$S/r6p-codex-sol.json"; echo 0 > "$S/r6p-codex-sol.exit"
  printf '{"findings":[]}\n' > "$S/r6p-opus.json"; echo 2 > "$S/r6p-opus.exit"
  state_gate_refuses "a plan seat with a nonzero exit" "$S" 6 phase=fix
  rm -f "$S/r6p-opus.json"; echo 0 > "$S/r6p-opus.exit"
  state_gate_refuses "a plan seat with an exit but no result" "$S" 6 phase=fix
  printf '{"findings":[]}\n' > "$S/r6p-opus.json"
  assert_exit "every plan seat returned allows fix" 0 "$ST" "$S" phase=fix

  S="$T/gate-round-labels"
  "$ST" "$S" round=7x phase=triage open.P2=1 >/dev/null
  printf 'Plan panel r7p - SKIPPED: plan review unavailable with an Agent seat\n' > "$S/findings.md"
  assert_exit "a repair label resolves to its code round" 0 "$ST" "$S" phase=fix
  "$ST" "$S" phase=triage >/dev/null
  state_gate_refuses "a round argument wins over state" "$S" 8 phase=fix round=8
  "$ST" "$S" round=setup phase=triage >/dev/null
  before=$(cksum < "$S/state.json")
  "$ST" "$S" phase=fix > /dev/null 2> "$T/gate.err"; rc=$?
  assert_eq "an unparseable round fails closed" "$rc" 2
  assert_eq "an unparseable round leaves state unchanged" "$(cksum < "$S/state.json")" "$before"
  assert_grep "an unparseable round explains itself" "$T/gate.err" "cannot determine the code round from round='setup'"

  S="$T/gate-p3-and-other-phases"
  "$ST" "$S" round=9 phase=triage open.P0=0 open.P1=0 open.P2=0 open.P3=4 >/dev/null
  assert_exit "P3-only findings allow fix without a plan" 0 "$ST" "$S" phase=fix
  "$ST" "$S" round=10 phase=triage open.P1=3 >/dev/null
  local phase
  for phase in fan-out collect triage plan verify commit done; do
    assert_exit "phase=$phase ignores the fix gate" 0 "$ST" "$S" "phase=$phase"
  done
  assert_exit "plain keys ignore the fix gate" 0 "$ST" "$S" last_commit=abc1234 fixed=2
  "$ST" "$S" phase=fan-out round=10 'seats=["codex-sol","opus"]' >/dev/null
  "$ST" "$S" phase=repair round=10x 'seats=["opus"]' >/dev/null
  "$ST" "$S" phase=plan round=10 'seats=["opus"]' >/dev/null
  assert_nogrep "only a <N>p plan launch records plan seats" "$S/state.json" '"plans"'
}
