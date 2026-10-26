# classify_failure must ignore model-chosen commands echoed as exec:/done: lines — sourced by run-tests.sh
test_seat_classify_exec() {
  ( seat_env; local S="$T/seat-cls"; seat_roster "$S"
    printf '%s\n' 'use at most 4 repository tool calls before stopping this assignment.' 'review' > "$S/p.md"
    SHIM_MODE=noise401exec "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" > "$T/cls.out" 2>&1; local rc=$?
    assert_eq "401 inside a model-run command → exit 2, not 3" "$rc" 2
    assert_grep "the exec line is in the log" "$S/r1-codex-sol.log" '^exec: .*401 unauthorized'
  )
}
