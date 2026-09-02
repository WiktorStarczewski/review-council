# tests for Task 2 — sourced by run-tests.sh
test_state() {
  local S="$T/state-sess" ST="$SCRIPTS/rev-state.sh"
  "$ST" "$S" round=1 phase=fan-out min_rounds=7 >/dev/null
  assert_grep "creates state.json" "$S/state.json" '"round": 1'
  assert_grep "string value" "$S/state.json" '"phase": "fan-out"'
  "$ST" "$S" phase=triage open.P1=2 'seats=["codex-sol","grok"]' last_commit=a1b2c3d >/dev/null
  assert_grep "merge keeps round" "$S/state.json" '"round": 1'
  assert_grep "overwrites phase" "$S/state.json" '"phase": "triage"'
  assert_grep "nested key" "$S/state.json" '"P1": 2'
  assert_grep "json list value" "$S/state.json" '"grok"'
  assert_grep "sha stays string" "$S/state.json" '"last_commit": "a1b2c3d"'
  assert_exit "dotted path through scalar fails" 1 "$ST" "$S" round.sub=1
  assert_exit "usage without args fails" 1 "$ST"
}
