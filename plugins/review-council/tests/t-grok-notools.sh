# grok seat: an answer with zero tool calls is retried once, then fails — sourced by run-tests.sh
test_grok_notools() {
  ( seat_env; local S="$T/gnt"; seat_roster "$S"; echo "review" > "$S/p.md"; rm -f "$T/args.grok-calls"
    SHIM_MODE=notools "$SCRIPTS/rev-seat.sh" grok "$S" 1 "$S/p.md" > "$T/gnt.out" 2>&1; assert_eq "no tool calls twice → exit 2 (no findings file)" "$?" 2
    assert_grep "log explains" "$S/r1-grok.log" 'answered without a single tool call \(attempt 2\)'
    assert_eq "no findings file left behind" "$(ls "$S/r1-grok.json" 2>/dev/null)" ""
    assert_grep "exit file records 2" "$S/r1-grok.exit" '^2$'
    rm -f "$T/args.grok-calls"
    SHIM_MODE=notools_then_ok "$SCRIPTS/rev-seat.sh" grok "$S" 2 "$S/p.md" > "$T/gnt2.out" 2>&1; assert_eq "retry succeeds → exit 0" "$?" 0
    assert_grep "first attempt logged" "$S/r2-grok.log" 'attempt 1'
    assert_grep "second attempt has tool calls" "$S/r2-grok.log" '^tool_call shell'
    assert_grep "findings from retry" "$T/gnt2.out" '^seat=grok round=2 exit=0 findings=1$'
  )
}
