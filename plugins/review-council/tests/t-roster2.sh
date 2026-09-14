# roster follow-ups from the build review: extras addressable by config, unreadable config visible, config path
# fallback, env-overridable timeouts. Reuses roster_env/roster_creds/roster_lines from t-roster.sh.
test_roster2() {
  ( local B="$T/roster2"; roster_env "$B" codex gemini; roster_creds
    printf '{"pin":{"codex-review":{"effort":"ultra"}}}\n' > "$B/cfg.json"
    REVIEW_COUNCIL_CONFIG="$B/cfg.json" "$SCRIPTS/roster.sh" > "$B/out.json"; roster_lines "$B/out.json" "$B/lines"
    assert_grep "pinned extra takes the pin" "$B/lines" '^seat codex-review openai codex gpt-5.6-sol ultra true review 3$'
    assert_grep "base seats untouched" "$B/lines" '^seat codex-sol openai codex gpt-5.6-sol max false'
    printf '{"exclude":["codex-review"]}\n' > "$B/cfg.json"
    REVIEW_COUNCIL_CONFIG="$B/cfg.json" "$SCRIPTS/roster.sh" > "$B/excluded.json"; roster_lines "$B/excluded.json" "$B/excluded-lines"
    assert_nogrep "excluded extra is not seated" "$B/excluded-lines" '^seat codex-review '
    assert_grep "excluded extra is reported" "$B/excluded-lines" '^excluded codex-review -> excluded by config$'
    printf '{not json' > "$B/bad.json"
    REVIEW_COUNCIL_CONFIG="$B/bad.json" "$SCRIPTS/roster.sh" --brief > "$B/brief"; assert_eq "unreadable config exits permanent strict" "$?" 6
    assert_grep "unreadable config is visible in the banner" "$B/brief" 'config unreadable'
    assert_grep "unreadable config is classified as permanent" "$B/brief" 'STRICT config: config unreadable'
    mkdir -p "$B/pdata"; printf '{"exclude":["gemini"]}\n' > "$B/pdata/config.json"
    ( unset REVIEW_COUNCIL_CONFIG; CLAUDE_PLUGIN_DATA="$B/pdata" "$SCRIPTS/roster.sh" > "$B/out2.json" ); roster_lines "$B/out2.json" "$B/lines2"
    assert_grep "CLAUDE_PLUGIN_DATA is NOT a config source (it leaks across plugins)" "$B/lines2" '^seat gemini '
    # a wedged `codex login status` must not hang: 1s budget, shim sleeps 3s → sign-in check timed out, run continues
    printf '#!/bin/bash\n[ "$1" = login ] && { sleep 3; echo "Logged in using ChatGPT"; exit 0; }\nexec "%s/codex" "$@"\n' "$SHIMS" > "$B/codex"; chmod +x "$B/codex"
    local t0=$(date +%s); REVIEW_COUNCIL_LOGIN_TIMEOUT=1 "$SCRIPTS/roster.sh" > "$B/out4.json"; local rc=$? dt=$(( $(date +%s) - t0 )); roster_lines "$B/out4.json" "$B/lines4"
    assert_grep "login timeout excludes codex with a reason" "$B/lines4" '^excluded codex -> sign-in check timed out'
    assert_eq "Gemini and Opus are padded to 3 seats without Codex" "$rc" 0
    [ "$dt" -lt 5 ] && ok "timeout is honoured (${dt}s)" || fail "timeout is honoured" "${dt}s"
    assert_nogrep "codex extra dropped with its lab" "$B/lines4" '^seat codex-review '
  )
}
test_roster_status_failed() {
  ( local B="$T/roster-sf"; roster_env "$B" codex gemini; roster_creds
    # a status command that fails for a reason other than sign-out is reported as such and retried once
    printf '#!/bin/bash\nif [ "$1" = login ] && [ "$2" = status ]; then n=$(cat "%s/n" 2>/dev/null || echo 0); echo $((n+1)) > "%s/n"; echo "error: connection reset" >&2; exit 1; fi\nexec "%s/codex" "$@"\n' "$B" "$B" "$SHIMS" > "$B/codex"; chmod +x "$B/codex"
    "$SCRIPTS/roster.sh" > "$B/out.json"; roster_lines "$B/out.json" "$B/lines"
    assert_grep "failed status is not called a sign-out" "$B/lines" '^excluded codex -> status check failed: error: connection reset$'
    assert_eq "the status command was retried once" "$(cat "$B/n")" "2"
    # a real sign-out is still a sign-out (no retry)
    rm -f "$B/n"; printf '#!/bin/bash\nif [ "$1" = login ] && [ "$2" = status ]; then n=$(cat "%s/n" 2>/dev/null || echo 0); echo $((n+1)) > "%s/n"; echo "Not logged in. Run codex login."; exit 1; fi\nexec "%s/codex" "$@"\n' "$B" "$B" "$SHIMS" > "$B/codex"; chmod +x "$B/codex"
    "$SCRIPTS/roster.sh" > "$B/out2.json"; roster_lines "$B/out2.json" "$B/lines2"
    assert_grep "sign-out text wins" "$B/lines2" '^excluded codex -> not signed in$'
    assert_eq "no retry on an explicit sign-out" "$(cat "$B/n")" "1"
  )
}
