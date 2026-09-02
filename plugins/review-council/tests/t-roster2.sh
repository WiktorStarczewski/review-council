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
    assert_grep "CLAUDE_PLUGIN_DATA config honoured" "$B/lines2" '^excluded gemini -> excluded by config$'
    ( REVIEW_COUNCIL_CONFIG="$B/cfg.json" CLAUDE_PLUGIN_DATA="$B/pdata" "$SCRIPTS/roster.sh" > "$B/out3.json" ); roster_lines "$B/out3.json" "$B/lines3"
    assert_grep "REVIEW_COUNCIL_CONFIG wins over CLAUDE_PLUGIN_DATA" "$B/lines3" '^seat gemini '
    # a wedged `codex login status` must not hang: 1s budget, shim sleeps 3s → sign-in check timed out, run continues
    printf '#!/bin/bash\n[ "$1" = login ] && { sleep 3; echo "Logged in using ChatGPT"; exit 0; }\nexec "%s/codex" "$@"\n' "$SHIMS" > "$B/codex"; chmod +x "$B/codex"
    local t0=$(date +%s); REVIEW_COUNCIL_LOGIN_TIMEOUT=1 "$SCRIPTS/roster.sh" > "$B/out4.json"; local rc=$? dt=$(( $(date +%s) - t0 )); roster_lines "$B/out4.json" "$B/lines4"
    assert_grep "login timeout excludes codex with a reason" "$B/lines4" '^excluded codex -> sign-in check timed out'
    assert_eq "still 3 seats without codex (grok, gemini, opus) → exit 0" "$rc" 0
    [ "$dt" -lt 5 ] && ok "timeout is honoured (${dt}s)" || fail "timeout is honoured" "${dt}s"
    assert_nogrep "codex extra dropped with its lab" "$B/lines4" '^seat codex-review '
  )
}
