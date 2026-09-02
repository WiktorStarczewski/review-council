# tests for the codex-review native-prose conversion — sourced by run-tests.sh
test_cxreview() {
  ( seat_env; local C="$SCRIPTS/lib/codex-review-to-findings.py"
    local n; n=$(python3 "$C" "$FX/codex-review-native.txt" "$T/cx.json" --root /repo); assert_eq "converter counts 2" "$n" "2"
    assert_exit "converted JSON validates" 0 python3 "$SCRIPTS/lib/validate-findings.py" "$T/cx.json"
    assert_grep "path made repo-relative" "$T/cx.json" '"file": "src/lib/rev-selftest/clamp.ts"'
    assert_grep "severity kept" "$T/cx.json" '"severity": "P1"'
    assert_grep "line range parsed" "$T/cx.json" '"line_start": 6, "line_end": 8'
    assert_grep "multi-line body joined" "$T/cx.json" 'cannot catch the upper-bound defect. Assert that'
    assert_grep "summary is first line" "$T/cx.json" '"summary": "The clamp implementation violates'
    printf 'Looks good. No issues found.\n' > "$T/clean.txt"; n=$(python3 "$C" "$T/clean.txt" "$T/clean.json"); assert_eq "clean review → 0 findings" "$n" "0"
    assert_exit "clean JSON validates" 0 python3 "$SCRIPTS/lib/validate-findings.py" "$T/clean.json"
    local S="$T/cx-sess"; seat_roster "$S"; echo "custom instructions (unused by exec review)" > "$S/p.md"
    SHIM_MODE=native "$SCRIPTS/rev-seat.sh" codex-review "$S" 2 "$S/p.md" --base abc123 > "$T/cx.out"; assert_eq "codex-review seat exit 0 on prose" "$?" 0
    assert_grep "seat summary counts converted findings" "$T/cx.out" '^seat=codex-review round=2 exit=0 findings=2$'
    assert_grep "native prose kept" "$S/r2-codex-review.native.txt" '^Full review comments:'
    assert_grep "no stdin prompt for exec review" "$T/args" '^--base$'
    assert_eq "exec review gets no prompt on stdin" "$(cat "$T/args.stdin")" ""
    # `exec review` takes no -s, so the read-only sandbox is pinned through config instead
    assert_grep "codex-review pins the read-only sandbox" "$T/args" '^sandbox_mode="read-only"$'
    # a location whose path contains a space used to fail the header regex, silently converting to "clean"
    printf 'A review.\n\nFull review comments:\n\n- [P1] Title here — /repo/my dir/x.ts:4-6\n  evidence line\n' > "$T/cx-space.txt"
    n=$(python3 "$C" "$T/cx-space.txt" "$T/cx-space.json" --root /repo); assert_eq "space path converts" "$n" "1"
    assert_grep "space kept in the file value" "$T/cx-space.json" '"file": "my dir/x.ts"'
    assert_grep "lines still parsed" "$T/cx-space.json" '"line_start": 4, "line_end": 6'
    assert_exit "converted space finding validates" 0 python3 "$SCRIPTS/lib/validate-findings.py" "$T/cx-space.json"
    # a marker we can see but cannot place must fail loudly, never convert the review to "clean"
    python3 "$C" "$FX/codex-review-native-bad.txt" "$T/cx-bad.json" > "$T/cx-bad.out" 2>&1
    assert_eq "unparseable finding → exit 1" "$?" 1
    assert_grep "says which line" "$T/cx-bad.out" '^cannot parse finding: - \[P1\] Broken marker'
    assert_exit "no JSON written for an unparseable review" 1 test -f "$T/cx-bad.json"
    SHIM_MODE=native_bad "$SCRIPTS/rev-seat.sh" codex-review "$S" 3 "$S/p.md" --base abc123 > "$T/cx3.out" 2>&1
    assert_eq "seat reports exit 2 on an unconvertible review" "$?" 2
    assert_grep "seat summary says 2" "$T/cx3.out" '^seat=codex-review round=3 exit=2 findings=-$'
  )
}
