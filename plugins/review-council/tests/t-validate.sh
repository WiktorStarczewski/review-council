# tests for Task 1 — sourced by run-tests.sh
test_validate() {
  local V="$SCRIPTS/lib/validate-findings.py"
  assert_eq "valid counts findings" "$(python3 "$V" "$FX/findings-valid.json" 2>/dev/null)" "1"
  assert_exit "bad severity rejected" 2 python3 "$V" "$FX/findings-bad-severity.json"
  assert_exit "extra key rejected" 2 python3 "$V" "$FX/findings-extra-key.json"
  echo 'not json' > "$T/nj.json"; assert_exit "non-JSON rejected" 2 python3 "$V" "$T/nj.json"
  assert_exit "missing file rejected" 2 python3 "$V" "$T/does-not-exist.json"
  # json.load accepts NaN/Infinity, and every comparison against NaN is False, so the range check passed it
  assert_exit "NaN confidence rejected" 2 python3 "$V" "$FX/findings-nan-confidence.json"
  python3 "$V" "$FX/findings-nan-confidence.json" 2> "$T/nan.err"
  assert_grep "reason names the non-finite value" "$T/nan.err" '^invalid: non-finite number'
  sed 's/NaN/Infinity/' "$FX/findings-nan-confidence.json" > "$T/inf.json"
  assert_exit "Infinity confidence rejected" 2 python3 "$V" "$T/inf.json"
  echo '{"summary":"clean","findings":[]}' > "$T/empty.json"
  assert_eq "empty findings valid" "$(python3 "$V" "$T/empty.json" 2>/dev/null)" "0"
}
