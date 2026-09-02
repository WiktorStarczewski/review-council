# tests for Task 2 — the roster: detect the installed lab CLIs and build the seat set. Sourced by run-tests.sh.
# Every case runs in a ( … ) subshell (the runner tallies through a FILE, so a subshell's ok/fail still counts)
# with a PATH that holds ONLY the shims the case wants plus the system directories. The real codex/grok/gemini
# live in ~/.local/bin and node's bin dir, so /usr/bin:/bin can never reach them — no network, ever.

roster_env() {   # roster_env <bin-dir> [shim …] — install the named shims and nothing else
  local bin=$1; shift
  mkdir -p "$bin"
  local s; for s in "$@"; do cp "$SHIMS/$s" "$bin/$s"; chmod +x "$bin/$s"; done
  export PATH="$bin:/usr/bin:/bin:/usr/sbin:/sbin"
  export HOME="$bin.home"; mkdir -p "$HOME"
  export SHIM_FIXTURE_DIR="$FX"
  export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$FX/roster-codex-cache-full.json"
  export REVIEW_COUNCIL_CONFIG="$HOME/no-such-config.json"
  export REVIEW_COUNCIL_GEMINI_CREDS="$HOME/.gemini/oauth_creds.json"
  unset GEMINI_API_KEY REVIEW_COUNCIL_GEMINI_MODEL REVIEW_COUNCIL_CLAUDE_SEAT SHIM_MODE SHIM_ARGS_FILE
}
roster_creds() { mkdir -p "$(dirname "$REVIEW_COUNCIL_GEMINI_CREDS")"; echo '{"access_token":"x"}' > "$REVIEW_COUNCIL_GEMINI_CREDS"; }
roster_lines() {  # roster_lines <json> <out> — flatten the roster into greppable lines
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
def v(x): return "null" if x is None else ("true" if x is True else ("false" if x is False else str(x)))
with open(sys.argv[2], "w") as f:
    for s in d.get("seats", []):
        f.write("seat %s %s %s %s %s %s %s %s\n" % tuple(v(s.get(k)) for k in
                ("seat","lab","adapter","model","effort","extra","mode","round")))
    for e in d.get("excluded", []):
        f.write("excluded %s -> %s\n" % (v(e.get("cli")), v(e.get("reason"))))
    f.write("counts %d %d\n" % (len([s for s in d.get("seats", []) if not s.get("extra")]), len(d.get("seats", []))))
    f.write("generated_at %s\n" % v(d.get("generated_at")))
' "$1" "$2" 2>/dev/null
}

test_roster_full() {
  ( local B="$T/roster-full"; roster_env "$B" codex grok gemini; roster_creds
    assert_eq "the shim is the only codex on PATH" "$(command -v codex)" "$B/codex"
    "$SCRIPTS/roster.sh" --write "$B/written.json" > "$B/out.json" 2> "$B/err"; assert_eq "full roster exits 0" "$?" 0
    assert_eq "nothing on stderr" "$(cat "$B/err")" ""
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_full" "stdout is not JSON"; return 1; }
    assert_grep "codex-sol seated at max"   "$B/lines" '^seat codex-sol openai codex gpt-5\.6-sol max false null null$'
    assert_grep "codex-terra seated at max" "$B/lines" '^seat codex-terra openai codex gpt-5\.6-terra max false null null$'
    assert_grep "grok seated at xhigh"      "$B/lines" '^seat grok xai grok grok-4\.6 xhigh false null null$'
    assert_grep "gemini seated, no effort"  "$B/lines" '^seat gemini google gemini gemini-2\.5-pro null false null null$'
    assert_grep "opus seated at max"        "$B/lines" '^seat opus anthropic agent opus max false null null$'
    assert_grep "codex-review extra is round 2"  "$B/lines" '^seat codex-review openai codex .* true review 2$'
    assert_grep "grok-code-review is round 3"    "$B/lines" '^seat grok-code-review xai grok .* true code-review 3$'
    assert_grep "5 seats + 2 extras" "$B/lines" '^counts 5 7$'
    assert_grep "generated_at is a UTC timestamp" "$B/lines" '^generated_at [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+'
    assert_nogrep "third-ranked model never seated"  "$B/lines" 'luna'
    assert_nogrep "hidden model never seated"        "$B/lines" 'hidden'
    assert_nogrep "older generation never seated"    "$B/lines" 'gpt-5\.5'
    assert_exit "--write stores exactly the JSON printed" 0 cmp -s "$B/written.json" "$B/out.json"
    "$SCRIPTS/roster.sh" --brief > "$B/brief" 2>&1; assert_eq "--brief exits 0" "$?" 0
    assert_eq "--brief is one line" "$(wc -l < "$B/brief" | tr -d ' ')" 1
    assert_eq "--brief line" "$(cat "$B/brief")" \
      'review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@max) · grok ✓ (grok-4.6@xhigh) · gemini ✓ (gemini-2.5-pro) · claude ✓ (opus@max)'
    "$SCRIPTS/roster.sh" --brief --write "$B/brief.json" > "$B/brief2" 2>&1
    assert_eq "--brief --write exits 0" "$?" 0
    assert_eq "--brief --write still prints one line" "$(wc -l < "$B/brief2" | tr -d ' ')" 1
    roster_lines "$B/brief.json" "$B/brieflines" && assert_grep "--brief --write stores the JSON" "$B/brieflines" '^counts 5 7$'
    "$SCRIPTS/roster.sh" --json > "$B/explicit.json"; assert_eq "--json is the default form" "$?" 0
    roster_lines "$B/explicit.json" "$B/lines2" && assert_grep "--json prints the same seats" "$B/lines2" '^counts 5 7$'
  )
}

test_roster_effort_steps_down() {
  ( local B="$T/roster-effort"; roster_env "$B" codex grok gemini; roster_creds
    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$FX/roster-codex-cache-terra-xhigh.json"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "roster exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_effort" "stdout is not JSON"; return 1; }
    assert_grep "sol keeps max"            "$B/lines" '^seat codex-sol .* gpt-5\.6-sol max false'
    assert_grep "terra steps down to xhigh" "$B/lines" '^seat codex-terra .* gpt-5\.6-terra xhigh false'
  )
}

test_roster_missing_and_signed_out() {
  ( local B="$T/roster-nogemini"; roster_env "$B" codex grok   # no gemini shim installed
    assert_eq "no real gemini leaks onto PATH" "$(command -v gemini || true)" ""
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "missing gemini still exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_missing" "stdout is not JSON"; return 1; }
    assert_grep "gemini excluded as not installed" "$B/lines" '^excluded gemini -> not installed$'
    assert_grep "4 seats + 2 extras" "$B/lines" '^counts 4 6$'
    "$SCRIPTS/roster.sh" --brief > "$B/brief"; assert_grep "brief marks gemini missing" "$B/brief" 'gemini ✗ not installed'
  )
  ( local B="$T/roster-nocreds"; roster_env "$B" codex grok gemini   # gemini installed, never signed in
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "signed-out gemini still exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_nocreds" "stdout is not JSON"; return 1; }
    assert_grep "gemini excluded as not signed in" "$B/lines" '^excluded gemini -> not signed in$'
    GEMINI_API_KEY=k "$SCRIPTS/roster.sh" > "$B/key.json"; roster_lines "$B/key.json" "$B/keylines"
    assert_grep "an API key signs gemini in" "$B/keylines" '^seat gemini google gemini gemini-2\.5-pro null false'
    GEMINI_API_KEY=k REVIEW_COUNCIL_GEMINI_MODEL=gemini-3.0-pro "$SCRIPTS/roster.sh" > "$B/m.json"
    roster_lines "$B/m.json" "$B/mlines"; assert_grep "the gemini model is overridable" "$B/mlines" '^seat gemini google gemini gemini-3\.0-pro null false'
  )
  ( local B="$T/roster-groknotauth"; roster_env "$B" codex grok gemini; roster_creds
    SHIM_MODE=grok-notauth "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "signed-out grok still exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_groknotauth" "stdout is not JSON"; return 1; }
    assert_grep "grok excluded as not signed in" "$B/lines" '^excluded grok -> not signed in$'
    assert_nogrep "no grok seat"       "$B/lines" '^seat grok '
    assert_nogrep "no grok extra"      "$B/lines" '^seat grok-code-review'
    assert_grep "4 seats + 1 extra"    "$B/lines" '^counts 4 5$'
  )
  # SHIM_MODE=notauth signs BOTH codex and grok out (the shims share one mode switch), so this case is
  # also the "one CLI left" refusal: gemini + the agent seat is two, under the three a round needs.
  ( local B="$T/roster-codexnotauth"; roster_env "$B" codex grok gemini; roster_creds
    SHIM_MODE=notauth "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "two signed-out CLIs refuse the run" "$?" 5
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_codexnotauth" "stdout is not JSON"; return 1; }
    assert_grep "codex excluded as not signed in" "$B/lines" '^excluded codex -> not signed in$'
    assert_grep "grok excluded as not signed in"  "$B/lines" '^excluded grok -> not signed in$'
    assert_nogrep "no codex seat"  "$B/lines" '^seat codex'
    assert_grep "gemini and the agent seat remain" "$B/lines" '^counts 2 2$'
    SHIM_MODE=notauth "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_eq "--brief carries the same refusal code" "$?" 5
    assert_grep "brief marks codex signed out" "$B/brief" 'codex ✗ not signed in'
  )
  ( local B="$T/roster-toofew"; roster_env "$B" codex   # codex alone, and its cache lists one model
    printf '%s' '{"models":[{"slug":"gpt-6.0-alpha","visibility":"list","priority":1,"supported_reasoning_levels":[{"effort":"high"},{"effort":"max"}]}]}' > "$B.home/one.json"
    REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/one.json" "$SCRIPTS/roster.sh" > "$B/out.json"
    assert_eq "two seats refuse the run" "$?" 5
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_toofew" "stdout is not JSON"; return 1; }
    assert_grep "the JSON is still emitted" "$B/lines" '^counts 2 3$'
    assert_grep "newest generation parsed"  "$B/lines" '^seat codex-alpha openai codex gpt-6\.0-alpha max false null null$'
    assert_grep "excluded says why (grok)"   "$B/lines" '^excluded grok -> not installed$'
    assert_grep "excluded says why (gemini)" "$B/lines" '^excluded gemini -> not installed$'
    REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/nope.json" "$SCRIPTS/roster.sh" > "$B/nc.json" 2> "$B/nc.err"
    assert_eq "a missing cache leaves one seat" "$?" 5
    assert_nogrep "no traceback on stderr" "$B/nc.err" 'Traceback'
    roster_lines "$B/nc.json" "$B/nclines" || { fail "roster_toofew" "stdout is not JSON"; return 1; }
    assert_grep "cache failure is reported" "$B/nclines" '^excluded codex -> no usable model in '
  )
}

test_roster_config() {
  ( local B="$T/roster-cfg-exclude"; roster_env "$B" codex grok gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$FX/roster-config-exclude.json"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "excluding grok still exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_cfg_exclude" "stdout is not JSON"; return 1; }
    assert_grep "grok excluded by config" "$B/lines" '^excluded grok -> excluded by config$'
    assert_nogrep "no grok seat"  "$B/lines" '^seat grok'
    assert_grep "the other seats survive" "$B/lines" '^counts 4 5$'
  )
  ( local B="$T/roster-cfg-pin"; roster_env "$B" codex grok gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$FX/roster-config-pin.json"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "pinning exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_cfg_pin" "stdout is not JSON"; return 1; }
    assert_grep "pinned effort wins"       "$B/lines" '^seat codex-sol openai codex gpt-5\.6-sol ultra false'
    assert_grep "unpinned seat untouched"  "$B/lines" '^seat codex-terra openai codex gpt-5\.6-terra max false'
    assert_grep "pinned model wins"        "$B/lines" '^seat grok xai grok grok-4\.7-fast xhigh false'
  )
  ( local B="$T/roster-cfg-flags"; roster_env "$B" codex grok gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"extras": false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; roster_lines "$B/out.json" "$B/lines"
    assert_grep "extras: false drops both extras" "$B/lines" '^counts 5 5$'
    printf '%s' '{"claude_seat": false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out2.json"; assert_eq "dropping the claude seat exits 0" "$?" 0
    roster_lines "$B/out2.json" "$B/lines2"
    assert_nogrep "no opus seat"          "$B/lines2" '^seat opus'
    assert_grep "claude excluded"         "$B/lines2" '^excluded claude -> disabled$'
    assert_grep "4 seats + 2 extras"      "$B/lines2" '^counts 4 6$'
    "$SCRIPTS/roster.sh" --brief > "$B/brief"; assert_grep "brief marks claude off" "$B/brief" 'claude ✗ disabled'
    printf '%s' '{"claude_seat": false' > "$REVIEW_COUNCIL_CONFIG"   # malformed: truncated JSON
    "$SCRIPTS/roster.sh" > "$B/out3.json" 2> "$B/err3"; assert_eq "a malformed config still exits 0" "$?" 0
    assert_nogrep "no traceback on stderr" "$B/err3" 'Traceback'
    roster_lines "$B/out3.json" "$B/lines3" || { fail "roster_cfg_flags" "stdout is not JSON"; return 1; }
    assert_grep "the config is reported unreadable" "$B/lines3" '^excluded config -> config unreadable$'
    assert_grep "and otherwise ignored"             "$B/lines3" '^seat opus anthropic agent opus max false'
    rm -f "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_CLAUDE_SEAT=0 "$SCRIPTS/roster.sh" > "$B/out4.json"; roster_lines "$B/out4.json" "$B/lines4"
    assert_nogrep "the env switch drops the claude seat" "$B/lines4" '^seat opus'
  )
}

test_roster_probe() {
  ( local B="$T/roster-probe-ok"; roster_env "$B" codex grok gemini; roster_creds
    export SHIM_ARGS_FILE="$B/args"
    "$SCRIPTS/roster.sh" --probe > "$B/out.json" 2> "$B/err"; assert_eq "a passing probe exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_probe_ok" "stdout is not JSON"; return 1; }
    assert_grep "every seat survives" "$B/lines" '^counts 5 7$'
    assert_nogrep "nothing probe-excluded" "$B/lines" 'probe'
    assert_grep "the probe ran gemini read-only" "$B/args" '^--approval-mode$'
    assert_grep "the probe asked for one token" "$B/args" '^Reply with exactly OK$'
  )
  ( local B="$T/roster-probe-fail"; roster_env "$B" codex grok gemini; roster_creds
    SHIM_MODE=ratelimit "$SCRIPTS/roster.sh" --probe > "$B/out.json" 2> "$B/err"
    assert_eq "every CLI probe failing refuses the run" "$?" 5
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_probe_fail" "stdout is not JSON"; return 1; }
    assert_grep "codex-sol probe failure recorded"   "$B/lines" '^excluded codex-sol -> probe failed: '
    assert_grep "codex-terra probe failure recorded" "$B/lines" '^excluded codex-terra -> probe failed: '
    assert_grep "grok probe failure recorded"        "$B/lines" '^excluded grok -> probe failed: '
    assert_grep "gemini probe failure recorded"      "$B/lines" '^excluded gemini -> probe failed: '
    assert_nogrep "no codex seat left"  "$B/lines" '^seat codex'
    assert_nogrep "no extras without their lab" "$B/lines" 'true review'
    assert_grep "only the agent seat remains" "$B/lines" '^counts 1 1$'
    assert_nogrep "no traceback on stderr" "$B/err" 'Traceback'
    # a probe drop is recorded against the SEAT, so the brief line has to find it through the seat's adapter
    SHIM_MODE=ratelimit "$SCRIPTS/roster.sh" --probe --brief > "$B/brief" 2>&1
    assert_eq "--brief refuses too" "$?" 5
    assert_grep "brief explains the codex drop" "$B/brief" 'codex ✗ probe failed'
    "$SCRIPTS/roster.sh" > "$B/cheap.json"; assert_eq "without --probe the seats stay" "$?" 0
    roster_lines "$B/cheap.json" "$B/cheaplines"; assert_grep "cheap detection never probes" "$B/cheaplines" '^counts 5 7$'
  )
}
