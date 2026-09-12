# tests for Task 6 - sourced by run-tests.sh
# session-start is self-locating (HERE=$(dirname "$0")), so most cases below build an isolated
# probe plugin root (a fixture POLICY.md + a controlled roster.sh stub) and run the REAL
# hooks/session-start script copied into it - this exercises the hook's own contract (policy
# read, roster dispatch, timeout, fallback wording, JSON shape) without depending on Task 2's
# roster.sh or Task 5's POLICY.md, which are owned by other in-flight tasks and may not exist
# yet in this checkout. Two further cases run the unmodified script straight from the real
# shared plugin root ($SK) per the brief's literal "CLAUDE_PLUGIN_ROOT=$P, shims on PATH"
# wording; they assert only what's true regardless of whether those dependencies have landed.
HOOK_SRC="$SK/hooks/session-start"

mk_hook_root() {  # mk_hook_root <dir> - copies the real session-start into an isolated probe root
  mkdir -p "$1/hooks" "$1/skills/rev" "$1/scripts"
  cp "$HOOK_SRC" "$1/hooks/session-start"
  chmod +x "$1/hooks/session-start"
}
hook_ctx() {  # hook_ctx <out.json> → prints additionalContext to stdout, "" + exit 1 if not valid JSON
  python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    assert d["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    print(d["hookSpecificOutput"]["additionalContext"])
except Exception:
    sys.exit(1)
' "$1"
}

test_hook_json_shape() {  # the core contract: <policy>\n\n<roster line>, valid JSON, hookEventName set
  ( local R="$T/hook-shape"; mk_hook_root "$R"
    printf 'Line one of policy\nLine two of policy\n' > "$R/skills/rev/POLICY.md"
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
echo "review-council seats: codex ✓ (gpt-5.6-sol@max) · claude ✓ (opus@max)"
SH
    chmod +x "$R/scripts/roster.sh"
    "$R/hooks/session-start" > "$T/out.json" 2> "$T/err.txt"; local rc=$?
    assert_eq "exits 0" "$rc" 0
    if ! ctx=$(hook_ctx "$T/out.json"); then fail "output is valid JSON with hookEventName=SessionStart" "$(cat "$T/out.json")"; return; fi
    ok "output is valid JSON with hookEventName=SessionStart"
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "contains policy first line" "$T/ctx.txt" '^Line one of policy$'
    assert_grep "contains the roster line" "$T/ctx.txt" '^review-council seats: codex ✓'
    local want=$'Line one of policy\nLine two of policy\n\nreview-council seats: codex ✓ (gpt-5.6-sol@max) · claude ✓ (opus@max)'
    assert_eq "exact <policy>\\n\\n<roster line> layout" "$ctx" "$want"
  )
}

test_hook_missing_roster() {  # roster.sh not installed at all -- must still exit 0 with a usable line
  ( local R="$T/hook-noroster"; mk_hook_root "$R"
    printf 'Solo policy line\n' > "$R/skills/rev/POLICY.md"
    "$R/hooks/session-start" > "$T/out.json" 2> "$T/err.txt"; local rc=$?
    assert_eq "exits 0 with roster.sh absent" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "still valid JSON with roster.sh absent" "$(cat "$T/out.json")"; return; }
    ok "still valid JSON with roster.sh absent"
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "policy line still present" "$T/ctx.txt" '^Solo policy line$'
    assert_grep "reports not installed" "$T/ctx.txt" 'review-council seats: roster unavailable \(roster\.sh not installed\)'
  )
}

test_hook_roster_not_executable() {
  ( local R="$T/hook-noexec"; mk_hook_root "$R"
    printf 'p\n' > "$R/skills/rev/POLICY.md"
    echo 'echo nope' > "$R/scripts/roster.sh"; chmod -x "$R/scripts/roster.sh"
    "$R/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    assert_eq "exits 0 with roster.sh non-executable" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "valid JSON (non-executable roster.sh)" ""; return; }
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "reports not executable" "$T/ctx.txt" 'roster unavailable \(roster\.sh not executable\)'
  )
}

test_hook_roster_nonzero_still_passed_through() {  # strict roster output is real content, not a hook failure
  ( local R="$T/hook-exit5"; mk_hook_root "$R"
    printf 'p\n' > "$R/skills/rev/POLICY.md"
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
echo "review-council seats: codex x unavailable | STRICT availability: configured Codex seat did not survive probe"
exit 5
SH
    chmod +x "$R/scripts/roster.sh"
    "$R/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    assert_eq "hook still exits 0 when roster.sh exits 5" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "valid JSON (roster exit 5)" ""; return; }
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "retryable cause passes through verbatim" "$T/ctx.txt" \
      '^review-council seats: codex x unavailable \| STRICT availability: configured Codex seat did not survive probe$'
    assert_nogrep "not misreported as unavailable" "$T/ctx.txt" 'roster unavailable'
  )
  ( local R="$T/hook-exit6"; mk_hook_root "$R"
    printf 'p\n' > "$R/skills/rev/POLICY.md"
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
echo "review-council seats: codex x invalid | STRICT config: codex_models must be a list"
exit 6
SH
    chmod +x "$R/scripts/roster.sh"
    "$R/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    assert_eq "hook still exits 0 when roster.sh exits 6" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "valid JSON (roster exit 6)" ""; return; }
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "permanent cause passes through verbatim" "$T/ctx.txt" \
      '^review-council seats: codex x invalid \| STRICT config: codex_models must be a list$'
  )
}

test_hook_roster_timeout() {  # a hanging roster.sh must not hang the session -- capped defensively
  ( local R="$T/hook-timeout"; mk_hook_root "$R"
    printf 'p\n' > "$R/skills/rev/POLICY.md"
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
sleep 30
SH
    chmod +x "$R/scripts/roster.sh"
    local start=$(date +%s)
    "$R/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    local elapsed=$(( $(date +%s) - start ))
    assert_eq "exits 0 even on a hung roster.sh" "$rc" 0
    [ "$elapsed" -lt 15 ] && ok "capped well under the 30s sleep (${elapsed}s)" || fail "capped well under the 30s sleep" "took ${elapsed}s"
    ctx=$(hook_ctx "$T/out.json") || { fail "valid JSON (roster timeout)" ""; return; }
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "reports timed out" "$T/ctx.txt" 'roster unavailable \(timed out\)'
  )
}

test_hook_no_policy_file() {  # POLICY.md not present yet -- no leading blank separator, just the roster line
  ( local R="$T/hook-nopolicy"; mk_hook_root "$R"
    rm -f "$R/skills/rev/POLICY.md"
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
echo "review-council seats: claude ✓ (opus@max)"
SH
    chmod +x "$R/scripts/roster.sh"
    "$R/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    assert_eq "exits 0 with no POLICY.md" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "valid JSON (no POLICY.md)" ""; return; }
    assert_eq "context is just the roster line, no leading blank" "$ctx" "review-council seats: claude ✓ (opus@max)"
  )
}

test_hook_json_escaping() {  # quotes, backslashes, unicode -- proves json.dumps is doing the escaping
  ( local R="$T/hook-escape"; mk_hook_root "$R"
    printf 'A "quoted" line with a back\\slash and unicode ✓/✗\n' > "$R/skills/rev/POLICY.md"
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
echo 'review-council seats: codex ✓ (gpt-5.6-sol@max) · gemini ✗ not installed'
SH
    chmod +x "$R/scripts/roster.sh"
    "$R/hooks/session-start" > "$T/out.json" 2>"$T/err.txt"; local rc=$?
    assert_eq "exits 0 with special characters" "$rc" 0
    assert_exit "output parses as JSON" 0 python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$T/out.json"
    ctx=$(hook_ctx "$T/out.json") || { fail "hookEventName still correct" ""; return; }
    ok "hookEventName still correct"
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "quoted text intact after decode" "$T/ctx.txt" 'A "quoted" line with a back.slash'
    assert_grep "unicode intact after decode" "$T/ctx.txt" 'unicode ✓/✗'
    assert_grep "roster unicode intact after decode" "$T/ctx.txt" 'codex ✓ .*gemini ✗ not installed'
  )
}

test_hook_ascii_locale() {  # roster.sh output is UTF-8; the hook must decode it as UTF-8 even under a C/ASCII locale
  ( local R="$T/hook-ascii-locale"; mk_hook_root "$R"
    printf 'p\n' > "$R/skills/rev/POLICY.md"
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
echo "review-council seats: codex ✓ (gpt-5.6-sol@max) · gemini ✗ not installed"
SH
    chmod +x "$R/scripts/roster.sh"
    LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 "$R/hooks/session-start" > "$T/out.json" 2>"$T/err.txt"; local rc=$?
    assert_eq "exits 0 under a C/ASCII locale" "$rc" 0
    if ! ctx=$(hook_ctx "$T/out.json"); then fail "output still parses as JSON under a C/ASCII locale" "$(cat "$T/out.json") $(cat "$T/err.txt")"; return; fi
    ok "output still parses as JSON under a C/ASCII locale"
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "unicode roster glyphs intact, not decode-crashed" "$T/ctx.txt" 'codex ✓ .*gemini ✗ not installed'
  )
}

test_hook_survives_policy_read_error() {  # POLICY.md path is a directory -- must not crash the hook
  ( local R="$T/hook-direrr"; mk_hook_root "$R"
    rmdir "$R/skills/rev" 2>/dev/null; mkdir -p "$R/skills/rev/POLICY.md"  # a directory where a file is expected
    cat > "$R/scripts/roster.sh" <<'SH'
#!/bin/bash
echo "review-council seats: claude ✓ (opus@max)"
SH
    chmod +x "$R/scripts/roster.sh"
    "$R/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    assert_eq "still exits 0 when POLICY.md path is unreadable" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "still valid JSON when POLICY.md path is unreadable" ""; return; }
    ok "still valid JSON when POLICY.md path is unreadable"
  )
}

# The two cases below run the unmodified script straight from the real shared plugin root, per the
# brief's literal "CLAUDE_PLUGIN_ROOT=$P, shims on PATH" wording. scripts/roster.sh (Task 2) and
# skills/rev/POLICY.md (Task 5) are owned by other in-flight tasks; these assertions hold whether or
# not that work has landed yet (the roster-unavailable fallback text always contains "not installed"
# / "review-council seats:" too), and the POLICY.md check activates itself once that file exists.
test_hook_real_root_with_shims() {
  ( local _path="$PATH"
    export PATH="$SHIMS:$PATH" CLAUDE_PLUGIN_ROOT="$SK"
    "$SK/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    PATH="$_path"
    assert_eq "real plugin root: exits 0" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "real plugin root: valid JSON" ""; return; }
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "real plugin root: has a seats line" "$T/ctx.txt" 'review-council seats:'
    if [ -f "$SK/skills/rev/POLICY.md" ]; then
      local first; first=$(head -1 "$SK/skills/rev/POLICY.md")
      assert_grep "real plugin root: policy first line present once POLICY.md exists" "$T/ctx.txt" "^$(printf '%s' "$first" | sed 's/[.[\*^$]/\\&/g')\$"
    fi
  )
}

test_hook_real_root_no_shims() {
  ( local _path="$PATH"
    export PATH="/usr/bin:/bin:/usr/sbin:/sbin" CLAUDE_PLUGIN_ROOT="$SK"
    "$SK/hooks/session-start" > "$T/out.json" 2>/dev/null; local rc=$?
    PATH="$_path"
    assert_eq "real plugin root, no CLIs on PATH: exits 0" "$rc" 0
    ctx=$(hook_ctx "$T/out.json") || { fail "real plugin root, no CLIs on PATH: valid JSON" ""; return; }
    printf '%s' "$ctx" > "$T/ctx.txt"
    assert_grep "real plugin root, no CLIs on PATH: reports not installed" "$T/ctx.txt" 'not installed'
    # Task 11: with only the agent seat detected the panel is padded, and the banner has to say so -
    # this is the line a Claude-Code-only machine sees at every session start.
    assert_grep "real plugin root, no CLIs on PATH: the banner is marked DEGRADED" "$T/ctx.txt" \
      'DEGRADED: only Claude is available - 3 Claude seats, no cross-lab decorrelation$'
    assert_grep "…and still names the claude seat as present" "$T/ctx.txt" 'claude ✓ \(opus@max\)'
  )
}
