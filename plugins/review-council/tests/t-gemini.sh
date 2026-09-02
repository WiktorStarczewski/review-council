# gemini seat: stream-json → tool_call/text/end lines, JSON lifted out of the last assistant message.
# No live gemini on this box: the stream shape is the documented `-o stream-json` NDJSON, frozen in
# tests/fixtures/gemini-stream.ndjson. Sourced by run-tests.sh.
test_gemini() {
  ( seat_env; local S="$T/gem"; seat_roster "$S"; echo "review the diff" > "$S/p.md"; : > "$T/args.env"
    SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" gemini "$S" 1 "$S/p.md" > "$T/gem.out"; assert_eq "gemini ok exit" "$?" 0
    assert_grep "summary line" "$T/gem.out" '^seat=gemini round=1 exit=0 findings=1$'
    assert_grep "writes .exit" "$S/r1-gemini.exit" '^0$'
    assert_grep "findings lifted from the fenced answer" "$S/r1-gemini.json" '"claim": "loop skips the last element"'
    assert_grep "log has a shell tool_call" "$S/r1-gemini.log" '^tool_call run_shell_command: git diff abc123 --stat$'
    assert_grep "log names the file a read touched" "$S/r1-gemini.log" '^tool_call read_file: src/x.ts$'
    assert_grep "log has the assistant text" "$S/r1-gemini.log" '^text: Here is my review.'
    assert_grep "log ends with the result status" "$S/r1-gemini.log" '^end status=success$'
    assert_grep "raw stream kept" "$S/r1-gemini.stream.ndjson" '"type":"result"'
    assert_grep "model comes from the roster" "$T/args" '^gemini-2.5-pro$'
    assert_grep "plan approval mode" "$T/args" '^plan$'
    assert_grep "stream-json output" "$T/args" '^stream-json$'
    assert_grep "preamble tells it to run tools first" "$T/args" 'Run your tools first'
    assert_nogrep "no effort knob for gemini" "$T/args" 'reasoning|effort'
    assert_nogrep "no write flags" "$T/args" 'yolo|auto_edit|--approve'
    assert_grep "prompt on stdin" "$T/args.stdin" 'review the diff'
    assert_grep "seat carries REV_ACTIVE=1" "$T/args.env" '^REV_ACTIVE=1$'
    assert_grep "gemini runs from the repo root" "$T/args.env" "^cwd=$T$"
    assert_exit "notauth → 3" 3 env SHIM_MODE=notauth "$SCRIPTS/rev-seat.sh" gemini "$S" 2 "$S/p.md"
    assert_exit "ratelimit → 4" 4 env SHIM_MODE=ratelimit "$SCRIPTS/rev-seat.sh" gemini "$S" 3 "$S/p.md"
    assert_exit "empty → 2" 2 env SHIM_MODE=empty "$SCRIPTS/rev-seat.sh" gemini "$S" 4 "$S/p.md"
    assert_exit "badjson → 2" 2 env SHIM_MODE=badjson "$SCRIPTS/rev-seat.sh" gemini "$S" 5 "$S/p.md"
    assert_grep "exit file records 2" "$S/r5-gemini.exit" '^2$'
    # an answer with no tool calls is not a review — same rule as grok: retry once, then fail the seat
    SHIM_MODE=notools "$SCRIPTS/rev-seat.sh" gemini "$S" 6 "$S/p.md" > "$T/gem-nt.out" 2>&1
    assert_eq "no tool calls twice → exit 2" "$?" 2
    assert_grep "log explains" "$S/r6-gemini.log" 'answered without a single tool call \(attempt 2\)'
    assert_eq "no findings file left behind" "$(ls "$S/r6-gemini.json" 2>/dev/null)" ""
  )
}
