# roster follow-ups from the build review: extras addressable by config, unreadable config visible, config path
# fallback, env-overridable timeouts. Reuses roster_env/roster_creds/roster_lines from t-roster.sh.
test_roster2() {
  ( local B="$T/roster2"; roster_env "$B" codex grok gemini; roster_creds
    printf '{"exclude":["codex-review"],"pin":{"grok-code-review":{"effort":"high"}}}\n' > "$B/cfg.json"
    REVIEW_COUNCIL_CONFIG="$B/cfg.json" "$SCRIPTS/roster.sh" > "$B/out.json"; roster_lines "$B/out.json" "$B/lines"
    assert_nogrep "excluded extra is not seated" "$B/lines" '^seat codex-review '
    assert_grep "excluded extra is reported" "$B/lines" '^excluded codex-review -> excluded by config$'
    assert_grep "pinned extra takes the pin" "$B/lines" '^seat grok-code-review xai grok grok-4.6 high true code-review 3$'
    assert_grep "base seats untouched" "$B/lines" '^seat codex-sol openai codex gpt-5.6-sol max false'
    printf '{not json' > "$B/bad.json"
    REVIEW_COUNCIL_CONFIG="$B/bad.json" "$SCRIPTS/roster.sh" --brief > "$B/brief"; assert_eq "unreadable config still exits 0" "$?" 0
    assert_grep "unreadable config is visible in the banner" "$B/brief" 'config unreadable'
    mkdir -p "$B/pdata"; printf '{"exclude":["gemini"]}\n' > "$B/pdata/config.json"
    ( unset REVIEW_COUNCIL_CONFIG; CLAUDE_PLUGIN_DATA="$B/pdata" "$SCRIPTS/roster.sh" > "$B/out2.json" ); roster_lines "$B/out2.json" "$B/lines2"
    assert_grep "CLAUDE_PLUGIN_DATA is NOT a config source (it leaks across plugins)" "$B/lines2" '^seat gemini '
    # a wedged `codex login status` must not hang: 1s budget, shim sleeps 3s → sign-in check timed out, run continues
    printf '#!/bin/bash\n[ "$1" = login ] && { sleep 3; echo "Logged in using ChatGPT"; exit 0; }\nexec "%s/codex" "$@"\n' "$SHIMS" > "$B/codex"; chmod +x "$B/codex"
    local t0=$(date +%s); REVIEW_COUNCIL_LOGIN_TIMEOUT=1 "$SCRIPTS/roster.sh" > "$B/out4.json"; local rc=$? dt=$(( $(date +%s) - t0 )); roster_lines "$B/out4.json" "$B/lines4"
    assert_grep "login timeout excludes codex with a reason" "$B/lines4" '^excluded codex -> sign-in check timed out'
    assert_eq "still 3 seats without codex (grok, gemini, opus) → exit 0" "$rc" 0
    [ "$dt" -lt 5 ] && ok "timeout is honoured (${dt}s)" || fail "timeout is honoured" "${dt}s"
    assert_nogrep "codex extra dropped with its lab" "$B/lines4" '^seat codex-review '
  )
}
test_roster_status_failed() {
  ( local B="$T/roster-sf"; roster_env "$B" codex grok gemini; roster_creds
    # a status command that fails for a reason other than sign-out (network blip, crash) is reported as such — and retried once
    printf '#!/bin/bash\nif [ "$1" = models ]; then n=$(cat "%s/n" 2>/dev/null || echo 0); echo $((n+1)) > "%s/n"; echo "error: connection reset" >&2; exit 1; fi\nexec "%s/grok" "$@"\n' "$B" "$B" "$SHIMS" > "$B/grok"; chmod +x "$B/grok"
    "$SCRIPTS/roster.sh" > "$B/out.json"; roster_lines "$B/out.json" "$B/lines"
    assert_grep "failed status is not called a sign-out" "$B/lines" '^excluded grok -> status check failed: error: connection reset$'
    assert_eq "the status command was retried once" "$(cat "$B/n")" "2"
    # a real sign-out is still a sign-out (no retry)
    rm -f "$B/n"; printf '#!/bin/bash\nif [ "$1" = models ]; then n=$(cat "%s/n" 2>/dev/null || echo 0); echo $((n+1)) > "%s/n"; echo "Not logged in. Run grok login."; exit 1; fi\nexec "%s/grok" "$@"\n' "$B" "$B" "$SHIMS" > "$B/grok"; chmod +x "$B/grok"
    "$SCRIPTS/roster.sh" > "$B/out2.json"; roster_lines "$B/out2.json" "$B/lines2"
    assert_grep "sign-out text wins" "$B/lines2" '^excluded grok -> not signed in$'
    assert_eq "no retry on an explicit sign-out" "$(cat "$B/n")" "1"
  )
}
