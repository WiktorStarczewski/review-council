# A11 — the runner itself: a test body that stops early, and a filter that matches nothing, both used to
# pass vacuously. Driven through a NESTED run-tests.sh over a probe t-file, so this suite stays green.
test_runner_guards() {
  ( local D="$T/runner-probe"; mkdir -p "$D"
    cp "$HERE/run-tests.sh" "$D/run-tests.sh"; chmod +x "$D/run-tests.sh"
    printf 'test_probe_stops_early() { ok "one real assertion"; ( exit 3 ); }\n' > "$D/t-probe.sh"
    "$D/run-tests.sh" > "$D/out.txt" 2>&1; local rc=$?
    [ "$rc" -ne 0 ] && ok "early-exit body fails the run" || fail "early-exit body fails the run" "exit $rc"
    assert_grep "names the test and its status" "$D/out.txt" 'FAIL probe_stops_early — exited 3 before reporting'
    assert_grep "tallied as a failure" "$D/out.txt" '^passed=1 failed=1$'
    "$D/run-tests.sh" no-such-test > "$D/out2.txt" 2>&1; local rc2=$?
    [ "$rc2" -ne 0 ] && ok "unmatched filter fails the run" || fail "unmatched filter fails the run" "exit $rc2"
    assert_grep "says no test matched" "$D/out2.txt" 'no test matched'
    "$D/run-tests.sh" probe > "$D/out3.txt" 2>&1
    assert_grep "a matching filter still runs the test" "$D/out3.txt" 'probe_stops_early'
  )
}
