# tests for Task 2 - the roster: detect the installed lab CLIs and build the seat set. Sourced by run-tests.sh.
# Every case runs in a ( … ) subshell (the runner tallies through a FILE, so a subshell's ok/fail still counts)
# with a PATH that holds ONLY the shims the case wants plus the system directories. The real codex/grok/gemini
# live in ~/.local/bin and node's bin dir, so /usr/bin:/bin can never reach them - no network, ever.

roster_env() {   # roster_env <bin-dir> [shim …] - install the named shims and nothing else
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
roster_lines() {  # roster_lines <json> <out> - flatten the roster into greppable lines
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
    f.write("strict_class %s\n" % v(d.get("strict_class")))
    f.write("strict_reason %s\n" % v(d.get("strict_reason")))
    receipts = d.get("result_receipts")
    if isinstance(receipts, dict):
        f.write("result_receipts %s %d\n" %
                (v(receipts.get("version")), len(receipts.get("legacy_no_exit_sha256") or {})))
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
    assert_grep "written rosters require result receipts" "$B/lines" '^result_receipts 1 0$'
    assert_grep "codex-sol seated at max"   "$B/lines" '^seat codex-sol openai codex gpt-5\.6-sol max false null null$'
    assert_grep "codex-terra seated at max" "$B/lines" '^seat codex-terra openai codex gpt-5\.6-terra max false null null$'
    assert_grep "grok seated at xhigh"      "$B/lines" '^seat grok xai grok grok-4\.6 xhigh false null null$'
    assert_grep "gemini seated, no effort"  "$B/lines" '^seat gemini google gemini gemini-2\.5-pro null false null null$'
    assert_grep "opus seated at max"        "$B/lines" '^seat opus anthropic agent opus max false null null$'
    assert_grep "codex-review extra is round 3"  "$B/lines" '^seat codex-review openai codex .* true review 3$'
    assert_grep "grok-code-review is round 4"    "$B/lines" '^seat grok-code-review xai grok .* true code-review 4$'
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

test_roster_result_receipt_boundary() {
  ( local B="$T/roster-receipts"; roster_env "$B" codex grok
    mkdir -p "$B/session"
    printf '%s' '{"findings":["legacy"]}' > "$B/session/r1-grok.json"
    printf '%s' '{"findings":["legacy plan"]}' > "$B/session/r2p-opus.json"
    printf '%s' '{"findings":["legacy repair"]}' > "$B/session/r2x-opus.json"
    printf '%s' '{"findings":["receipted"]}' > "$B/session/r2-grok.json"
    printf '%s\n' 0 > "$B/session/r2-grok.exit"
    printf '%s' '{"seats":[]}' > "$B/session/roster.json"
    local expected
    expected=$(python3 - "$B/session/r1-grok.json" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).parent
print(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (root / 'r1-grok.json', root / 'r2p-opus.json', root / 'r2x-opus.json')}))
PY
)
    "$SCRIPTS/roster.sh" --write "$B/session/roster.json" > "$B/out.json"
    assert_eq "legacy roster upgrade exits 0" "$?" 0
    python3 - "$B/session/roster.json" "$expected" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['result_receipts'] == {
    'version': 1,
    'legacy_no_exit_sha256': json.loads(sys.argv[2]),
}
PY
    assert_eq "legacy result without exit is snapshotted" "$?" 0
    printf '%s' '{"findings":["overwritten"]}' > "$B/session/r1-grok.json"
    "$SCRIPTS/roster.sh" --write "$B/session/roster.json" > "$B/out2.json"
    assert_eq "marked roster replacement exits 0" "$?" 0
    python3 - "$B/session/roster.json" "$expected" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['result_receipts']['legacy_no_exit_sha256'] == json.loads(sys.argv[2])
PY
    assert_eq "marked roster preserves the original artifact boundary" "$?" 0
  )
}

test_roster_invalid_receipt_policy_fails_closed() {
  ( local B="$T/roster-invalid-receipts"; roster_env "$B" codex grok
    mkdir -p "$B/session"
    printf '%s' '{"summary":"legacy","findings":[]}' > "$B/session/r1-opus.json"
    local case_name document
    while IFS='|' read -r case_name document; do
      printf '%s' "$document" > "$B/session/roster.json"
      "$SCRIPTS/roster.sh" --write "$B/session/roster.json" > "$B/$case_name.json"
      assert_eq "$case_name receipt policy rewrite exits 0" "$?" 0
      python3 - "$B/session/roster.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['result_receipts'] == {
    'version': 1,
    'legacy_no_exit_sha256': {},
}
PY
      assert_eq "$case_name receipt policy does not snapshot legacy results" "$?" 0
    done <<'EOF'
corrupt|{
nonobject|[]
bad-version|{"result_receipts":{"version":"1","legacy_no_exit_sha256":{}}}
bad-map|{"result_receipts":{"version":1,"legacy_no_exit_sha256":[]}}
bad-digest|{"result_receipts":{"version":1,"legacy_no_exit_sha256":{"r1-opus.json":"abc"}}}
EOF
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
  # also the "one CLI left" one: gemini + the agent seat is two, and the third is padded in (Task 11).
  ( local B="$T/roster-codexnotauth"; roster_env "$B" codex grok gemini; roster_creds
    SHIM_MODE=notauth "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "two signed-out CLIs still run, padded" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_codexnotauth" "stdout is not JSON"; return 1; }
    assert_grep "codex excluded as not signed in" "$B/lines" '^excluded codex -> not signed in$'
    assert_grep "grok excluded as not signed in"  "$B/lines" '^excluded grok -> not signed in$'
    assert_nogrep "no codex seat"  "$B/lines" '^seat codex'
    assert_grep "gemini, the agent seat and one padded seat" "$B/lines" '^counts 3 3$'
    assert_grep "the padded seat is a Claude seat" "$B/lines" '^seat claude-1 anthropic agent opus max false'
    SHIM_MODE=notauth "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_eq "--brief exits 0 as well" "$?" 0
    assert_grep "brief marks codex signed out" "$B/brief" 'codex ✗ not signed in'
    assert_grep "brief says the panel is degraded" "$B/brief" 'DEGRADED: only google, anthropic available - padded with 1 Claude seat$'
  )
  ( local B="$T/roster-toofew"; roster_env "$B" codex   # codex alone, and its cache lists one model
    printf '%s' '{"models":[{"slug":"gpt-6.0-alpha","visibility":"list","priority":1,"supported_reasoning_levels":[{"effort":"high"},{"effort":"max"}]}]}' > "$B.home/one.json"
    REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/one.json" "$SCRIPTS/roster.sh" > "$B/out.json"
    assert_eq "two seats are padded to three" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_toofew" "stdout is not JSON"; return 1; }
    assert_grep "the JSON is still emitted" "$B/lines" '^counts 3 4$'
    assert_grep "one seat padded in" "$B/lines" '^seat claude-1 anthropic agent opus max false'
    assert_grep "newest generation parsed"  "$B/lines" '^seat codex-alpha openai codex gpt-6\.0-alpha max false null null$'
    assert_grep "excluded says why (grok)"   "$B/lines" '^excluded grok -> not installed$'
    assert_grep "excluded says why (gemini)" "$B/lines" '^excluded gemini -> not installed$'
    REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/nope.json" "$SCRIPTS/roster.sh" > "$B/nc.json" 2> "$B/nc.err"
    assert_eq "a missing cache leaves one detected seat, padded to three" "$?" 0
    assert_nogrep "no traceback on stderr" "$B/nc.err" 'Traceback'
    roster_lines "$B/nc.json" "$B/nclines" || { fail "roster_toofew" "stdout is not JSON"; return 1; }
    assert_grep "cache failure is reported" "$B/nclines" '^excluded codex -> Codex model cache unavailable:'
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
    assert_eq "every CLI probe failing still leaves a padded panel" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_probe_fail" "stdout is not JSON"; return 1; }
    assert_grep "codex-sol probe failure recorded"   "$B/lines" '^excluded codex-sol -> probe failed: '
    assert_grep "codex-terra probe failure recorded" "$B/lines" '^excluded codex-terra -> probe failed: '
    assert_grep "grok probe failure recorded"        "$B/lines" '^excluded grok -> probe failed: '
    assert_grep "gemini probe failure recorded"      "$B/lines" '^excluded gemini -> probe failed: '
    assert_nogrep "no codex seat left"  "$B/lines" '^seat codex'
    assert_nogrep "no extras without their lab" "$B/lines" 'true review'
    # padding happens AFTER the probe: the seats a probe drops are replaced, never left short
    assert_grep "the agent seat plus two padded seats" "$B/lines" '^counts 3 3$'
    assert_grep "padded after the probe" "$B/lines" '^seat claude-2 anthropic agent opus max false'
    assert_nogrep "no traceback on stderr" "$B/err" 'Traceback'
    # a probe drop is recorded against the SEAT, so the brief line has to find it through the seat's adapter
    SHIM_MODE=ratelimit "$SCRIPTS/roster.sh" --probe --brief > "$B/brief" 2>&1
    assert_eq "--brief exits 0 too" "$?" 0
    assert_grep "brief says the panel is degraded" "$B/brief" 'DEGRADED: only Claude is available'
    assert_grep "brief explains the codex drop" "$B/brief" 'codex ✗ probe failed'
    "$SCRIPTS/roster.sh" > "$B/cheap.json"; assert_eq "without --probe the seats stay" "$?" 0
    roster_lines "$B/cheap.json" "$B/cheaplines"; assert_grep "cheap detection never probes" "$B/cheaplines" '^counts 5 7$'
  )
}

test_roster_exact_panel_config() {
  ( local B="$T/roster-exact-panel"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    python3 - "$FX/roster-codex-cache-full.json" "$B.home/exact-cache.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
data['models'].append({
    'slug': 'gpt-6-astra', 'visibility': 'list', 'priority': 1,
    'supported_reasoning_levels': [{'effort': 'max'}],
})
json.dump(data, open(sys.argv[2], 'w'))
PY
    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/exact-cache.json"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"claude_seats":2,"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "exact panel exits 0" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_exact_panel" "stdout is not JSON"; return 1; }
    assert_grep "exact panel seats Sol" "$B/lines" '^seat codex-sol openai codex gpt-5\.6-sol max false'
    assert_nogrep "exact panel does not seat Terra" "$B/lines" 'gpt-5\.6-terra'
    assert_nogrep "exact panel does not seat Astra" "$B/lines" 'gpt-6-astra'
    assert_grep "exact panel seats first Opus" "$B/lines" '^seat opus anthropic agent opus max false'
    assert_grep "exact panel seats second Opus" "$B/lines" '^seat opus-2 anthropic agent opus max false'
    assert_grep "exact panel has four core seats" "$B/lines" '^counts 4 4$'
  )

  ( local B="$T/roster-exact-invalid"; roster_env "$B" codex grok gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"codex_models":"gpt-5.6-sol","claude_seats":"2","extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "malformed exact settings refuse permanently" "$?" 6
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "invalid Codex allowlist is reported" "$B/lines" '^excluded codex -> invalid codex_models:'
    assert_grep "invalid Claude count is reported" "$B/lines" '^excluded claude -> invalid claude_seats:'
    assert_nogrep "invalid Codex allowlist does not fail open" "$B/lines" '^seat codex-'
    assert_nogrep "invalid Claude count does not fail open" "$B/lines" '^seat opus '
    assert_grep "malformed exact settings are config strict" "$B/lines" '^strict_class config$'

    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-9-unknown"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/unknown.json"; assert_eq "unknown exact Codex slug refuses permanently" "$?" 6
    roster_lines "$B/unknown.json" "$B/unknown-lines"
    assert_grep "unknown Codex slug is reported" "$B/unknown-lines" '^excluded codex -> unknown Codex model slug: gpt-9-unknown$'
    assert_nogrep "partly valid Codex allowlist does not seat a subset" "$B/unknown-lines" '^seat codex-'
    assert_grep "unknown Codex slug has an exact strict reason" "$B/unknown-lines" \
      '^excluded codex_models -> strict: codex_models requires 2 matching seat\(s\), 0 survived$'

    printf '%s' '{"codex_models":["gpt-5.6-sol"],"pin":{"codex-sol":{"model":"gpt-6-astra"}},"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/pin.json"; assert_eq "an off-list exact Codex pin refuses permanently" "$?" 6
    roster_lines "$B/pin.json" "$B/pin-lines"
    assert_grep "off-allowlist model pin is reported" "$B/pin-lines" '^excluded codex-sol -> pinned model gpt-6-astra is outside codex_models$'
    assert_nogrep "off-allowlist model pin is removed" "$B/pin-lines" '^seat .* gpt-6-astra '
    assert_grep "the removed pin has an exact strict reason" "$B/pin-lines" \
      '^excluded codex_models -> strict: codex_models requires 1 matching seat\(s\), 0 survived$'

    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"pin":{"codex-terra":{"model":"gpt-5.6-sol"}},"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/dup.json"; assert_eq "a duplicate exact Codex pin refuses permanently" "$?" 6
    roster_lines "$B/dup.json" "$B/dup-lines"
    assert_grep "duplicate pin reason is retained" "$B/dup-lines" \
      '^excluded codex-terra -> pinned model gpt-5.6-sol duplicates another Codex seat$'
    assert_grep "duplicate pin is config strict" "$B/dup-lines" '^strict_class config$'
  )

  ( local B="$T/roster-exact-excluded"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"exclude":["codex"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/codex.json"; assert_eq "excluding an exact Codex lab refuses permanently" "$?" 6
    roster_lines "$B/codex.json" "$B/codex-lines"
    assert_grep "excluded Codex count is strict" "$B/codex-lines" \
      '^excluded codex_models -> strict: codex_models requires 1 matching seat\(s\), 0 survived$'

    rm -f "$B/codex"
    printf '%s' '{"claude_seats":2,"exclude":["opus-2"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/claude.json"; assert_eq "excluding an exact Opus seat refuses permanently" "$?" 6
    roster_lines "$B/claude.json" "$B/claude-lines"
    assert_grep "excluded Opus count is strict" "$B/claude-lines" \
      '^excluded claude_seats -> strict: claude_seats requires 2 matching seat\(s\), 1 survived$'
    assert_grep "padding still builds a reportable panel" "$B/claude-lines" '^counts 3 3$'
  )

  ( local B="$T/roster-exact-probe"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"claude_seats":1,"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    SHIM_MODE=ratelimit "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "a failed exact Codex probe is retryable" "$?" 5
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the probe failure is preserved" "$B/lines" '^excluded codex-sol -> probe failed: '
    assert_grep "the exact probe failure is strict" "$B/lines" \
      '^excluded codex_models -> strict: codex_models requires 1 matching seat\(s\), 0 survived$'
    assert_grep "probe failures are availability strict" "$B/lines" '^strict_class availability$'
  )

  ( local B="$T/roster-exact-cache"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/missing.json"
    "$SCRIPTS/roster.sh" > "$B/missing.json"; assert_eq "a missing exact cache is retryable" "$?" 5
    roster_lines "$B/missing.json" "$B/missing-lines"
    assert_grep "missing cache keeps its diagnostic" "$B/missing-lines" '^excluded codex -> Codex model cache unavailable:'
    assert_grep "missing cache is availability strict" "$B/missing-lines" '^strict_class availability$'

    printf '{' > "$B.home/corrupt.json"
    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/corrupt.json"
    "$SCRIPTS/roster.sh" > "$B/corrupt-out.json"; assert_eq "a corrupt exact cache is retryable" "$?" 5
    roster_lines "$B/corrupt-out.json" "$B/corrupt-lines"
    assert_grep "corrupt cache keeps its diagnostic" "$B/corrupt-lines" '^excluded codex -> Codex model cache unreadable:'

    cat > "$B.home/unsupported.json" <<'JSON'
{"models":[{"slug":"gpt-5.6-sol","visibility":"list","priority":1,"supported_reasoning_levels":[{"effort":"medium"}]}]}
JSON
    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/unsupported.json"
    "$SCRIPTS/roster.sh" > "$B/unsupported-out.json"; assert_eq "unsupported exact effort refuses permanently" "$?" 6
    roster_lines "$B/unsupported-out.json" "$B/unsupported-lines"
    assert_grep "unsupported effort keeps its diagnostic" "$B/unsupported-lines" \
      '^excluded codex -> configured Codex model has no supported high effort: gpt-5.6-sol$'
    assert_grep "unsupported effort is config strict" "$B/unsupported-lines" '^strict_class config$'

    printf '%s' '{"codex_models":"gpt-5.6-sol","min_labs":4}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/mixed.json"; assert_eq "config strict wins a mixed refusal" "$?" 6
    roster_lines "$B/mixed.json" "$B/mixed-lines"
    assert_grep "mixed refusal is classified config" "$B/mixed-lines" '^strict_class config$'
    assert_grep "mixed refusal retains availability evidence" "$B/mixed-lines" '^excluded min_labs -> strict:'

    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$FX/roster-codex-cache-full.json"
    rm -f "$B/codex"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"pin":{"codex-sol":{"model":"gpt-6-astra"}}}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/mixed-pin.json"; assert_eq "pin conflict wins over unavailable Codex" "$?" 6
    roster_lines "$B/mixed-pin.json" "$B/mixed-pin-lines"
    assert_grep "mixed pin refusal is classified config" "$B/mixed-pin-lines" '^strict_class config$'
    assert_grep "mixed pin refusal retains the config cause" "$B/mixed-pin-lines" \
      '^excluded codex-sol -> pinned model gpt-6-astra is outside codex_models$'
  )
}

test_roster_exact_active_pins_and_static_probe_gate() {
  ( local B="$T/roster-active-extra-pin"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" SHIM_ARGS_FILE="$B/args"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"pin":{"codex-review":{"model":"gpt-6-astra"}}}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "an active off-list extra pin is permanent config" "$?" 6
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the active extra pin is reported" "$B/lines" \
      '^excluded codex-review -> pinned model gpt-6-astra is outside codex_models$'
    assert_grep "the active extra pin owns the strict cause" "$B/lines" \
      '^strict_reason codex-review: pinned model gpt-6-astra is outside codex_models$'
    assert_eq "the active extra creates one strict entry" \
      "$(grep -c '^excluded codex_models -> strict:' "$B/lines")" 1
    assert_nogrep "permanent config is decided before probes" "$B/args" '^Reply with exactly OK$'

    printf '%s' '{"codex_models":["gpt-5.6-sol"],"extras":false,"pin":{"codex-review":{"model":"gpt-6-astra"}}}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/disabled.json"
    assert_eq "a disabled extra ignores its stale pin" "$?" 0
    roster_lines "$B/disabled.json" "$B/disabled-lines"
    assert_nogrep "the disabled extra has no pin conflict" "$B/disabled-lines" '^excluded codex-review -> pinned model '
    assert_grep "the valid control reaches a paid probe" "$B/args" '^Reply with exactly OK$'

    printf '%s' '{"codex_models":["gpt-5.6-sol"],"exclude":["codex-review"],"pin":{"codex-review":{"model":"gpt-6-astra"}}}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/excluded.json"
    assert_eq "an excluded extra ignores its stale pin" "$?" 0
    roster_lines "$B/excluded.json" "$B/excluded-lines"
    assert_grep "the excluded extra remains excluded" "$B/excluded-lines" \
      '^excluded codex-review -> excluded by config$'
    assert_nogrep "the excluded extra has no pin conflict" "$B/excluded-lines" '^excluded codex-review -> pinned model '
    assert_grep "the excluded-extra control still probes" "$B/args" '^Reply with exactly OK$'
  )

  ( local B="$T/roster-orphan-extra-pin"; roster_env "$B" grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" SHIM_ARGS_FILE="$B/args"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"pin":{"codex-review":{"model":"gpt-6-astra"}}}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "an orphaned extra pin stays retryable availability" "$?" 5
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the missing core seat owns the strict cause" "$B/lines" \
      '^strict_reason codex_models requires 1 matching seat\(s\), 0 survived$'
    assert_nogrep "the orphaned extra has no pin conflict" "$B/lines" '^excluded codex-review -> pinned model '
    assert_grep "an availability failure still probes surviving seats" "$B/args" '^Reply with exactly OK$'
  )

  ( local B="$T/roster-claude-pin"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" SHIM_ARGS_FILE="$B/args"
    printf '%s' '{"claude_seats":2,"extras":false,"pin":{"opus-2":{"model":"sonnet"}}}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "a counted Claude Code seat pinned away from Opus is config" "$?" 6
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the Claude Code pin owns the strict cause" "$B/lines" \
      '^strict_reason opus-2: pinned model sonnet is outside the Opus family$'
    assert_eq "the Claude Code pin creates one strict entry" \
      "$(grep -c '^excluded claude_seats -> strict:' "$B/lines")" 1
    assert_nogrep "the Claude Code pin fails before probes" "$B/args" '^Reply with exactly OK$'
  )

  ( local B="$T/roster-codex-host-claude-pin"; roster_env "$B" codex grok
    cat > "$B/claude" <<'SH'
#!/bin/bash
if [ "${1:-}" = auth ] && [ "${2:-}" = status ]; then
  printf '%s\n' '{"loggedIn":true}'
  exit 0
fi
exit 0
SH
    chmod +x "$B/claude"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" SHIM_ARGS_FILE="$B/args"
    printf '%s' '{"claude_seats":2,"extras":false,"pin":{"opus-2":{"model":"sonnet"}}}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=codex "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "a counted Codex-host Claude seat pinned away from Opus is config" "$?" 6
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the Codex-host pin owns the strict cause" "$B/lines" \
      '^strict_reason opus-2: pinned model sonnet is outside the Opus family$'
    assert_eq "the Codex-host pin creates one strict entry" \
      "$(grep -c '^excluded claude_seats -> strict:' "$B/lines")" 1
    assert_nogrep "the Codex-host pin fails before probes" "$B/args" '^Reply with exactly OK$'
  )

  ( local B="$T/roster-default-claude-pin"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" SHIM_ARGS_FILE="$B/args"
    printf '%s' '{"extras":false,"pin":{"opus":{"model":"sonnet"}}}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "a default non-exact Claude pin remains allowed" "$?" 0
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the default Claude pin still applies" "$B/lines" \
      '^seat opus anthropic agent sonnet max false'
    assert_grep "the non-exact control reaches probes" "$B/args" '^Reply with exactly OK$'
  )

  ( local B="$T/roster-plural-unsupported"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" SHIM_ARGS_FILE="$B/args"
    cat > "$B.home/unsupported.json" <<'JSON'
{"models":[
  {"slug":"gpt-5.6-sol","visibility":"list","priority":1,"supported_reasoning_levels":[{"effort":"medium"}]},
  {"slug":"gpt-5.6-terra","visibility":"list","priority":2,"supported_reasoning_levels":[{"effort":"medium"}]}
]}
JSON
    export REVIEW_COUNCIL_CODEX_MODELS_CACHE="$B.home/unsupported.json"
    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "two unsupported configured models are permanent config" "$?" 6
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the plural unsupported diagnostic is retained" "$B/lines" \
      '^excluded codex -> configured Codex models have no supported high effort: gpt-5.6-sol, gpt-5.6-terra$'
    assert_grep "the plural diagnostic owns the strict cause" "$B/lines" \
      '^strict_reason configured Codex models have no supported high effort: gpt-5.6-sol, gpt-5.6-terra$'
    assert_eq "plural unsupported models create one strict entry" \
      "$(grep -c '^excluded codex_models -> strict:' "$B/lines")" 1
    assert_nogrep "plural unsupported models fail before probes" "$B/args" '^Reply with exactly OK$'
  )
}

test_roster_min_labs_static_config_and_retryable_probe() {
  ( local B="$T/roster-min-labs-static"; roster_env "$B" codex grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" SHIM_ARGS_FILE="$B/args"
    local value
    for value in '"two"' true 0 -1; do
      rm -f "$B/args"
      printf '{"min_labs":%s,"extras":false}' "$value" > "$REVIEW_COUNCIL_CONFIG"
      "$SCRIPTS/roster.sh" --probe > "$B/invalid.json"
      assert_eq "min_labs $value is permanent config" "$?" 6
      roster_lines "$B/invalid.json" "$B/invalid-lines"
      assert_grep "min_labs $value keeps the config cause" "$B/invalid-lines" \
        '^strict_reason invalid min_labs: expected an integer of at least 1$'
      assert_nogrep "min_labs $value fails before probes" "$B/args" '^Reply with exactly OK$'
    done

    rm -f "$B/args"
    printf '%s' '{"min_labs":3,"exclude":["grok","gemini"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/impossible.json"
    assert_eq "a floor above configured capacity is permanent" "$?" 6
    roster_lines "$B/impossible.json" "$B/impossible-lines"
    assert_grep "the configured capacity owns the cause" "$B/impossible-lines" \
      '^strict_reason min_labs=3 exceeds 2 configured lab\(s\)$'
    assert_nogrep "an impossible floor fails before probes" "$B/args" '^Reply with exactly OK$'

    cat > "$B/grok" <<'SH'
#!/bin/bash
if [ "${1:-}" = models ]; then
  printf '%s\n' 'You are logged in with grok.com.' 'Default model: grok-4.6'
  exit 0
fi
printf '%s\n' probe >> "$SHIM_PROBE_FILE"
printf '%s\n' 'temporary probe failure' >&2
exit 1
SH
    chmod +x "$B/grok"
    rm -f "$B/args" "$B/probes"
    export SHIM_PROBE_FILE="$B/probes"
    printf '%s' '{"min_labs":3,"exclude":["gemini"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/retryable.json"
    assert_eq "a satisfiable floor with a failed provider is retryable" "$?" 5
    roster_lines "$B/retryable.json" "$B/retryable-lines"
    assert_grep "the live shortfall owns the availability cause" "$B/retryable-lines" \
      '^strict_reason 2 lab\(s\) available, min_labs=3$'
    assert_eq "the temporarily unavailable provider was probed once" \
      "$(wc -l < "$B/probes" | tr -d ' ')" 1
    assert_grep "the other CLI provider was also probed" "$B/args" '^Reply with exactly OK$'
  )
}
