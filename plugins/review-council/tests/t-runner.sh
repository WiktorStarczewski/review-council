# Runner contract tests use nested fixtures so failures exercise the public script.
runner_fixture() {
  local target=$1
  unset REVIEW_COUNCIL_TEST_TASK REVIEW_COUNCIL_TEST_RESULTS_FILE \
    REVIEW_COUNCIL_TEST_DISCOVER REVIEW_COUNCIL_TEST_SHARD \
    REV_EVIDENCE_CASE REV_EVIDENCE_GROUP
  mkdir -p "$target"
  cp "$HERE/run-tests.sh" "$target/run-tests.sh"
  chmod +x "$target/run-tests.sh"
}

runner_costs() {
  local target=$1
  shift
  : > "$target/test-costs.tsv"
  while [ "$#" -gt 0 ]; do
    printf '%b\n' "$1" >> "$target/test-costs.tsv"
    shift
  done
}

test_runner_guards() {
  ( local D="$T/runner-probe"; runner_fixture "$D"
    printf 'test_probe_stops_early() { ok "one real assertion"; ( exit 3 ); }\n' > "$D/t-probe.sh"
    runner_costs "$D" 't-probe.sh::test_probe_stops_early\t1\tnormal'
    REVIEW_COUNCIL_TEST_WORKERS=1 "$D/run-tests.sh" > "$D/out.txt" 2>&1; local rc=$?
    [ "$rc" -ne 0 ] && ok "early-exit body fails the run" || fail "early-exit body fails the run" "exit $rc"
    assert_grep "names the test and its status" "$D/out.txt" 'FAIL probe_stops_early - exited 3 before reporting'
    assert_grep "tallied as a failure" "$D/out.txt" '^passed=1 failed=1$'
    "$D/run-tests.sh" no-such-test > "$D/out2.txt" 2>&1; local rc2=$?
    [ "$rc2" -ne 0 ] && ok "unmatched filter fails the run" || fail "unmatched filter fails the run" "exit $rc2"
    assert_grep "says no test matched" "$D/out2.txt" 'no test matched'
    "$D/run-tests.sh" probe > "$D/out3.txt" 2>&1
    assert_grep "a matching filter still runs the test" "$D/out3.txt" 'probe_stops_early'

    local D2="$T/runner-duplicates"; runner_fixture "$D2"
    printf '%s\n' 'test_same_name() { echo DUPLICATE-BODY-RAN; }' > "$D2/t-one.sh"
    printf '%s\n' 'function test_same_name' '{ echo DUPLICATE-BODY-RAN; }' > "$D2/t-two.sh"
    "$D2/run-tests.sh" > "$D2/out.txt" 2>&1; local rc3=$?
    [ "$rc3" -ne 0 ] && ok "duplicate definitions fail before execution" || fail "duplicate definitions fail before execution" "exit $rc3"
    assert_grep "duplicate diagnostic names the collision" "$D2/out.txt" 'duplicate test function: test_same_name'
    assert_nogrep "duplicate test bodies never run" "$D2/out.txt" 'DUPLICATE-BODY-RAN'

    local D3="$T/runner-heredoc"; runner_fixture "$D3"
    printf '%s\n' 'test_real() { ok "real"; }' > "$D3/t-real.sh"
    cat > "$D3/t-fixture.sh" <<'SH'
test_fixture() {
  cat >/dev/null <<'FIXTURE'
test_real() { echo fixture-only; }
FIXTURE
  ok "fixture"
}
SH
    runner_costs "$D3" 't-fixture.sh::test_fixture\t1\tnormal' 't-real.sh::test_real\t1\tnormal'
    REVIEW_COUNCIL_TEST_WORKERS=1 "$D3/run-tests.sh" > "$D3/out.txt" 2>&1; local rc4=$?
    assert_eq "test-shaped heredoc text is not a duplicate definition" "$rc4" 0
    assert_grep "heredoc fixture run executes both real tests" "$D3/out.txt" '^passed=2 failed=0$'

    local D4="$T/runner-same-file-duplicates"; runner_fixture "$D4"
    cat > "$D4/t-one.sh" <<'SH'
test_same_file() { echo FIRST-DUPLICATE-BODY-RAN; }
test_same_file() { echo SECOND-DUPLICATE-BODY-RAN; }
SH
    "$D4/run-tests.sh" > "$D4/out.txt" 2>&1; local rc5=$?
    [ "$rc5" -ne 0 ] && ok "same-file duplicate definitions fail before execution" || \
      fail "same-file duplicate definitions fail before execution" "exit $rc5"
    assert_grep "same-file duplicate diagnostic names the collision" "$D4/out.txt" \
      'duplicate test function: test_same_file'
    assert_nogrep "same-file duplicate bodies never run" "$D4/out.txt" 'DUPLICATE-BODY-RAN'

    local D5="$T/runner-empty"; runner_fixture "$D5"
    printf '%s\n' 'test_empty() { :; }' > "$D5/t-empty.sh"
    runner_costs "$D5" 't-empty.sh::test_empty\t1\tnormal'
    REVIEW_COUNCIL_TEST_WORKERS=1 "$D5/run-tests.sh" > "$D5/out.txt" 2>&1; local rc6=$?
    [ "$rc6" -ne 0 ] && ok "a zero-assertion exact task fails the aggregate" || \
      fail "a zero-assertion exact task fails the aggregate" "exit $rc6"
    assert_grep "zero-assertion failure names the empty task" "$D5/out.txt" \
      'FAIL empty - reported no assertions'
    assert_grep "zero-assertion task is tallied as failed" "$D5/out.txt" \
      '^tasks_passed=0 tasks_failed=1$'

    local D6="$T/runner-empty-tally"; runner_fixture "$D6"
    printf '%s\n' 'test_no_tally() { kill -KILL "$$"; }' > "$D6/t-killed.sh"
    runner_costs "$D6" 't-killed.sh::test_no_tally\t1\tnormal'
    REVIEW_COUNCIL_TEST_WORKERS=1 "$D6/run-tests.sh" > "$D6/out.txt" 2>&1; local rc7=$?
    [ "$rc7" -ne 0 ] && ok "an empty child tally fails the aggregate" || \
      fail "an empty child tally fails the aggregate" "exit $rc7"
    assert_grep "empty child tally has a specific aggregate diagnostic" "$D6/out.txt" \
      'FAIL t-killed.sh::test_no_tally - task reported no assertions'
  )
}

test_runner_metadata_reconciles_exact_inventory() {
  ( local D="$T/runner-metadata"; runner_fixture "$D"
    printf '%s\n' 'test_alpha() { ok "alpha"; }' 'test_alphabet() { ok "alphabet"; }' > "$D/t-a.sh"
    runner_costs "$D" 't-a.sh::test_alpha\t2\tnormal' 't-a.sh::test_alphabet\t1\texclusive'
    REVIEW_COUNCIL_TEST_WORKERS=2 "$D/run-tests.sh" > "$D/good.out" 2>&1
    assert_eq "one metadata row per discovered task succeeds" "$?" 0
    REVIEW_COUNCIL_TEST_DISCOVER=1 "$D/run-tests.sh" > "$D/inventory"
    assert_eq "inventory comes from loaded Bash functions" "$(cat "$D/inventory")" \
      $'t-a.sh::test_alpha\nt-a.sh::test_alphabet'

    runner_costs "$D" 't-a.sh::test_alpha\t2\tnormal'
    "$D/run-tests.sh" > "$D/missing.out" 2>&1
    assert_grep "a missing metadata row fails before execution" "$D/missing.out" 'missing metadata: t-a.sh::test_alphabet'
    runner_costs "$D" 't-a.sh::test_alpha\t2\tnormal' 't-a.sh::test_alphabet\t1\tnormal' \
      't-a.sh::test_unknown\t9\tnormal'
    "$D/run-tests.sh" > "$D/unknown.out" 2>&1
    assert_grep "an unknown metadata row fails before execution" "$D/unknown.out" 'unknown metadata: t-a.sh::test_unknown'
    runner_costs "$D" 't-a.sh::test_alpha\t2\tnormal' 't-a.sh::test_alpha\t3\tnormal' \
      't-a.sh::test_alphabet\t1\tnormal'
    "$D/run-tests.sh" > "$D/duplicate.out" 2>&1
    assert_grep "a duplicate metadata row fails before execution" "$D/duplicate.out" 'duplicate metadata: t-a.sh::test_alpha'
    runner_costs "$D" 't-a.sh::test_alpha\tbad\tnormal' 't-a.sh::test_alphabet\t1\tnormal'
    "$D/run-tests.sh" > "$D/bad-cost.out" 2>&1
    assert_grep "an invalid cost hint fails before execution" "$D/bad-cost.out" 'invalid cost hint: t-a.sh::test_alpha'
  )
}

test_runner_longest_first_and_process_control_exclusive() {
  ( local D="$T/runner-schedule"; runner_fixture "$D"; mkdir -p "$D/records"
    cat > "$D/t-schedule.sh" <<'SH'
wait_for_file() {
  local path=$1 tries=0
  while [ ! -e "$path" ] && [ "$tries" -lt 300 ]; do sleep 0.01; tries=$((tries + 1)); done
  [ -e "$path" ]
}
normal_probe() {
  local name=$1
  printf '%s\n' "$T" > "$PROBE_RECORD/$name.tmp"
  : > "$PROBE_RECORD/$name.active"
  : > "$PROBE_RECORD/$name.ready"
  for peer in high1 high2 high3 high4; do wait_for_file "$PROBE_RECORD/$peer.ready" || return; done
  [ ! -e "$PROBE_RECORD/exclusive.active" ] || return 9
  sleep 0.05
  rm "$PROBE_RECORD/$name.active"
}
exclusive_probe() {
  local name=$1
  if find "$PROBE_RECORD" -name '*.active' -print -quit | grep -q .; then return 8; fi
  : > "$PROBE_RECORD/exclusive.active"
  printf '%s\n' "$name" >> "$PROBE_RECORD/exclusive.order"
  sleep 0.05
  rm "$PROBE_RECORD/exclusive.active"
}
test_high1() { normal_probe high1; ok "high1"; }
test_high2() { normal_probe high2; ok "high2"; }
test_high3() { normal_probe high3; ok "high3"; }
test_high4() { normal_probe high4; ok "high4"; }
test_exclusive1() { exclusive_probe exclusive1; ok "exclusive1"; }
test_exclusive2() { exclusive_probe exclusive2; ok "exclusive2"; }
test_low() {
  [ ! -e "$PROBE_RECORD/exclusive.active" ] || return 7
  printf '%s\n' "$T" > "$PROBE_RECORD/low.tmp"
  ok "low"
}
SH
    runner_costs "$D" \
      't-schedule.sh::test_low\t1\tnormal' \
      't-schedule.sh::test_exclusive2\t20\texclusive' \
      't-schedule.sh::test_high4\t60\tnormal' \
      't-schedule.sh::test_high2\t80\tnormal' \
      't-schedule.sh::test_exclusive1\t30\texclusive' \
      't-schedule.sh::test_high1\t90\tnormal' \
      't-schedule.sh::test_high3\t70\tnormal'
    PROBE_RECORD="$D/records" REVIEW_COUNCIL_TEST_WORKERS=4 \
      "$D/run-tests.sh" > "$D/out.txt" 2>&1; local rc=$?
    assert_eq "longest-first scheduled run succeeds" "$rc" 0
    assert_grep "complete task inventory is tallied" "$D/out.txt" '^tasks_passed=7 tasks_failed=0$'
    assert_eq "all four longest tasks entered the first worker batch" \
      "$(find "$D/records" -name 'high*.ready' | wc -l | tr -d ' ')" 4
    assert_eq "adjacent process-control tasks run in order" \
      "$(tr '\n' ' ' < "$D/records/exclusive.order" | sed 's/ $//')" 'exclusive1 exclusive2'
    assert_eq "each parallel task receives a distinct temporary root" \
      "$(cat "$D/records"/*.tmp | sort -u | wc -l | tr -d ' ')" 5
  )
}

test_runner_public_substring_and_internal_exact_selection() {
  ( local D="$T/runner-selection"; runner_fixture "$D"
    cat > "$D/t-select.sh" <<'SH'
test_alpha() { printf 'alpha\n' >> "$PROBE_RECORD"; ok "alpha"; }
test_alphabet() { printf 'alphabet\n' >> "$PROBE_RECORD"; ok "alphabet"; }
SH
    runner_costs "$D" 't-select.sh::test_alpha\t2\tnormal' 't-select.sh::test_alphabet\t1\tnormal'
    PROBE_RECORD="$D/public" "$D/run-tests.sh" alpha > "$D/public.out" 2>&1
    assert_eq "public substring filters retain sibling matches" \
      "$(sort "$D/public" | tr '\n' ' ' | sed 's/ $//')" 'alpha alphabet'
    PROBE_RECORD="$D/exact" REVIEW_COUNCIL_TEST_TASK='t-select.sh::test_alpha' \
      REVIEW_COUNCIL_TEST_RESULTS_FILE="$D/exact.results" \
      "$D/run-tests.sh" > "$D/exact.out" 2>&1
    assert_eq "internal exact selection runs only the named identity" "$(cat "$D/exact")" alpha
    PROBE_RECORD="$D/bad" REVIEW_COUNCIL_TEST_TASK='t-select.sh::test_alph' \
      REVIEW_COUNCIL_TEST_RESULTS_FILE="$D/bad.results" \
      "$D/run-tests.sh" > "$D/bad.out" 2>&1
    assert_grep "an inexact internal identity cannot match siblings" "$D/bad.out" 'unknown exact test identity'
    assert_exit "an inexact internal identity fails" 1 test -e "$D/bad"
  )
}

test_runner_failure_retains_sibling_results() {
  ( local D="$T/runner-failure"; runner_fixture "$D"
    cat > "$D/t-results.sh" <<'SH'
test_pass_one() { ok "pass one"; }
test_fails() { ok "before stop"; return 7; }
test_pass_two() { ok "pass two"; }
SH
    runner_costs "$D" 't-results.sh::test_pass_one\t3\tnormal' \
      't-results.sh::test_fails\t2\tnormal' 't-results.sh::test_pass_two\t1\tnormal'
    REVIEW_COUNCIL_TEST_WORKERS=3 "$D/run-tests.sh" > "$D/out.txt" 2>&1; local rc=$?
    [ "$rc" -ne 0 ] && ok "one failed task fails the aggregate" || fail "one failed task fails the aggregate" "exit $rc"
    assert_grep "aggregate retains every sibling task result" "$D/out.txt" '^tasks_passed=2 tasks_failed=1$'
    assert_grep "aggregate retains assertion tallies" "$D/out.txt" '^passed=3 failed=1$'
    assert_grep "aggregate names the task that stopped" "$D/out.txt" 'FAIL fails - exited 7 before reporting'
  )
}

test_runner_writable_fixture_copies_from_frozen_sources() {
  ( local source="$T/runner-frozen-source" target="$T/runner-writable-target"
    mkdir -p "$source/tree"
    printf '%s\n' original > "$source/file"
    printf '%s\n' original > "$source/tree/file"
    chmod -R a-w "$source"

    mkdir -p "$target"
    copy_writable_file "$source/file" "$target/file"
    copy_writable_tree "$source/tree" "$target/tree"
    printf '%s\n' replaced > "$target/file"
    printf '%s\n' replaced > "$target/tree/file"

    assert_grep "a fixture file copied from a frozen source can be replaced" \
      "$target/file" '^replaced$'
    assert_grep "a fixture tree copied from a frozen source can be replaced" \
      "$target/tree/file" '^replaced$'
    chmod -R u+w "$source"
  )
}
