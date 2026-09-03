# tests for Task 10 (update-notice side) — sourced by run-tests.sh
# update-check.py is opt-in (config check_updates) and must NEVER break session start: every failure
# path is silent + exit 0. No network here — the "remote" plugin.json is a file:// fixture, and
# REVIEW_COUNCIL_CACHE_DIR keeps every run out of the user's ~/.cache.
UPD="$SCRIPTS/lib/update-check.py"

mk_upd_root() {  # mk_upd_root <dir> [version] — a plugin root whose .claude-plugin/plugin.json says <version>
  mkdir -p "$1/.claude-plugin"
  printf '{\n  "name": "review-council",\n  "version": "%s"\n}\n' "${2:-0.1.1}" > "$1/.claude-plugin/plugin.json"
}
mk_upd_cfg() {  # mk_upd_cfg <path> <json-body> — a review-council config file
  mkdir -p "$(dirname "$1")"; printf '%s\n' "$2" > "$1"
}
mk_upd_cache() {  # mk_upd_cache <dir> <latest> <age-seconds>
  mkdir -p "$1"
  python3 - "$1/update-check.json" "$2" "$3" <<'PY'
import json, sys, time
json.dump({'checked_at': time.time() - float(sys.argv[3]), 'latest': sys.argv[2]}, open(sys.argv[1], 'w'))
PY
}
upd_hook_ctx() {  # upd_hook_ctx <out.json> → additionalContext on stdout, exit 1 if the JSON is wrong
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
UPD_LINE="review-council 0.9.9 available: claude plugin update review-council"

test_update_newer_version_prints_the_line() {
  ( local D="$T/upd-newer"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" \
      python3 "$UPD" "$D/root" > "$D/out.txt" 2> "$D/err.txt"; local rc=$?
    assert_eq "exits 0" "$rc" 0
    assert_eq "prints exactly the update line" "$(cat "$D/out.txt")" "$UPD_LINE"
    assert_eq "says nothing on stderr" "$(cat "$D/err.txt")" ""
  )
}

test_update_same_version_prints_nothing() {
  ( local D="$T/upd-same"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-same.json" \
      python3 "$UPD" "$D/root" > "$D/out.txt" 2>&1; local rc=$?
    assert_eq "exits 0 when already up to date" "$rc" 0
    assert_eq "prints nothing when the versions match" "$(cat "$D/out.txt")" ""
  )
}

test_update_opt_in_required() {  # absent, false, and a non-boolean truthy value all mean "off"
  ( local D="$T/upd-optin"; mk_upd_root "$D/root" 0.1.1
    for body in '{}' '{ "check_updates": false }' '{ "exclude": ["gemini"] }' '{ "check_updates": 1 }'; do
      mk_upd_cfg "$D/config.json" "$body"
      REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
        REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" \
        python3 "$UPD" "$D/root" > "$D/out.txt" 2>&1
      assert_eq "silent with config $body" "$(cat "$D/out.txt")" ""
    done
    [ -f "$D/cache/update-check.json" ] && fail "no cache written while opted out" "cache exists" || ok "no cache written while opted out"
    rm -f "$D/config.json"
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" \
      python3 "$UPD" "$D/root" > "$D/out.txt" 2>&1; local rc=$?
    assert_eq "exits 0 with no config file at all" "$rc" 0
    assert_eq "silent with no config file at all" "$(cat "$D/out.txt")" ""
  )
}

test_update_unreachable_url_is_silent() {
  ( local D="$T/upd-unreachable"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$D/no-such-file.json" \
      python3 "$UPD" "$D/root" > "$D/out.txt" 2> "$D/err.txt"; local rc=$?
    assert_eq "exits 0 when the update URL cannot be fetched" "$rc" 0
    assert_eq "prints nothing on stdout" "$(cat "$D/out.txt")" ""
    assert_eq "prints nothing on stderr either" "$(cat "$D/err.txt")" ""
  )
}

test_update_bad_inputs_are_silent() {  # malformed remote JSON, missing/garbled plugin.json, junk cache
  ( local D="$T/upd-bad"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    printf 'not json at all' > "$D/remote-bad.json"
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$D/remote-bad.json" python3 "$UPD" "$D/root" > "$D/o1.txt" 2>&1
    assert_eq "silent on malformed remote JSON" "$(cat "$D/o1.txt")" ""
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" python3 "$UPD" "$D/no-such-root" > "$D/o2.txt" 2>&1
    assert_eq "silent when the plugin root has no plugin.json" "$(cat "$D/o2.txt")" ""
    mk_upd_root "$D/root2" "not.a.version"
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache2" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" python3 "$UPD" "$D/root2" > "$D/o3.txt" 2>&1
    assert_eq "silent on a non-numeric installed version" "$(cat "$D/o3.txt")" ""
    mkdir -p "$D/cache3"; printf '{ broken' > "$D/cache3/update-check.json"
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache3" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" python3 "$UPD" "$D/root" > "$D/o4.txt" 2>&1
    assert_eq "a corrupt cache falls through to the fetch" "$(cat "$D/o4.txt")" "$UPD_LINE"
    assert_exit "exit 0 throughout" 0 env REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$D/remote-bad.json" python3 "$UPD" "$D/root"
  )
}

test_update_fresh_cache_is_honoured() {  # a cache younger than the TTL is used even when the URL is dead
  ( local D="$T/upd-cache-fresh"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    mk_upd_cache "$D/cache" 0.9.9 60
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$D/no-such-file.json" \
      python3 "$UPD" "$D/root" > "$D/out.txt" 2>&1; local rc=$?
    assert_eq "exits 0" "$rc" 0
    assert_eq "prints the line from the cache without fetching" "$(cat "$D/out.txt")" "$UPD_LINE"
  )
}

test_update_stale_cache_is_not_used() {  # past the TTL the cache is ignored; a dead URL then means silence
  ( local D="$T/upd-cache-stale"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    mk_upd_cache "$D/cache" 0.9.9 3600
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" REVIEW_COUNCIL_UPDATE_TTL=1 \
      REVIEW_COUNCIL_UPDATE_URL="file://$D/no-such-file.json" \
      python3 "$UPD" "$D/root" > "$D/out.txt" 2>&1; local rc=$?
    assert_eq "exits 0 on a stale cache with a dead URL" "$rc" 0
    assert_eq "prints nothing rather than a stale claim" "$(cat "$D/out.txt")" ""
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" REVIEW_COUNCIL_UPDATE_TTL=1 \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-same.json" python3 "$UPD" "$D/root" > "$D/out2.txt" 2>&1
    assert_eq "a stale cache is refreshed from the URL when it is reachable" "$(cat "$D/out2.txt")" ""
    assert_eq "the refreshed cache holds the newly fetched version" \
      "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["latest"])' "$D/cache/update-check.json")" "0.1.1"
  )
}

test_update_writes_the_cache() {
  ( local D="$T/upd-cachewrite"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_CACHE_DIR="$D/cache" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" python3 "$UPD" "$D/root" > /dev/null 2>&1
    [ -f "$D/cache/update-check.json" ] && ok "creates the cache file" || { fail "creates the cache file" "no $D/cache/update-check.json"; return; }
    assert_eq "caches the fetched version" \
      "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["latest"])' "$D/cache/update-check.json")" "0.9.9"
    assert_exit "records a numeric checked_at" 0 python3 -c \
      'import json,sys,time; d=json.load(open(sys.argv[1])); sys.exit(0 if abs(time.time()-float(d["checked_at"]))<300 else 1)' "$D/cache/update-check.json"
  )
}

test_update_hook_appends_the_line() {  # the real hook, real plugin root, shims on PATH (as t-hook.sh does)
  ( local D="$T/upd-hook"; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    export PATH="$SHIMS:$PATH" CLAUDE_PLUGIN_ROOT="$SK" REVIEW_COUNCIL_CONFIG="$D/config.json" \
           REVIEW_COUNCIL_CACHE_DIR="$D/cache" REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json"
    "$SK/hooks/session-start" > "$D/out.json" 2>/dev/null; local rc=$?
    assert_eq "hook exits 0 with the update check on" "$rc" 0
    local ctx; ctx=$(upd_hook_ctx "$D/out.json") || { fail "hook output is still valid JSON" "$(cat "$D/out.json")"; return; }
    ok "hook output is still valid JSON"
    printf '%s' "$ctx" > "$D/ctx.txt"
    assert_grep "the update line is its own line in additionalContext" "$D/ctx.txt" "^review-council 0\.9\.9 available: claude plugin update review-council\$"
    assert_grep "the roster line is still there" "$D/ctx.txt" '^review-council seats:'
    assert_eq "the update line comes last" "$(tail -1 "$D/ctx.txt")" "$UPD_LINE"
  )
}

test_update_hook_silent_when_not_opted_in() {
  ( local D="$T/upd-hook-off"; mk_upd_cfg "$D/config.json" '{}'
    export PATH="$SHIMS:$PATH" CLAUDE_PLUGIN_ROOT="$SK" REVIEW_COUNCIL_CONFIG="$D/config.json" \
           REVIEW_COUNCIL_CACHE_DIR="$D/cache" REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json"
    "$SK/hooks/session-start" > "$D/out.json" 2>/dev/null; local rc=$?
    assert_eq "hook exits 0 with the update check off" "$rc" 0
    local ctx; ctx=$(upd_hook_ctx "$D/out.json") || { fail "valid JSON with the update check off" ""; return; }
    printf '%s' "$ctx" > "$D/ctx.txt"
    assert_nogrep "no update line when check_updates is absent" "$D/ctx.txt" 'available: claude plugin update'
    assert_grep "the roster line is still there" "$D/ctx.txt" '^review-council seats:'
  )
}

test_update_hook_survives_a_hung_update_check() {  # the outer cap: a wedged check must not stall the session
  ( local D="$T/upd-hook-hang"; mkdir -p "$D/root/hooks" "$D/root/skills/rev" "$D/root/scripts/lib"
    cp "$SK/hooks/session-start" "$D/root/hooks/session-start"; chmod +x "$D/root/hooks/session-start"
    printf 'p\n' > "$D/root/skills/rev/POLICY.md"
    printf '#!/bin/bash\necho "review-council seats: claude ✓ (opus@max)"\n' > "$D/root/scripts/roster.sh"
    chmod +x "$D/root/scripts/roster.sh"
    printf 'import time\ntime.sleep(30)\n' > "$D/root/scripts/lib/update-check.py"
    export CLAUDE_PLUGIN_ROOT="$D/root"
    local start=$(date +%s)
    "$D/root/hooks/session-start" > "$D/out.json" 2>/dev/null; local rc=$?
    local elapsed=$(( $(date +%s) - start ))
    assert_eq "hook still exits 0" "$rc" 0
    [ "$elapsed" -lt 15 ] && ok "capped well under the 30s sleep (${elapsed}s)" || fail "capped well under the 30s sleep" "took ${elapsed}s"
    local ctx; ctx=$(upd_hook_ctx "$D/out.json") || { fail "valid JSON after an update-check timeout" ""; return; }
    ok "valid JSON after an update-check timeout"
    printf '%s' "$ctx" > "$D/ctx.txt"
    # Only the update notice is this test's business: the roster line's own text (and its own
    # timeout) belong to t-hook.sh, and a loaded machine can trip it on a freshly written stub.
    assert_grep "the policy is still injected" "$D/ctx.txt" '^p$'
    assert_nogrep "the timed-out check contributes no line" "$D/ctx.txt" 'available: claude plugin update'
  )
}

test_update_hook_ignores_a_foreign_plugin_root() {  # CLAUDE_PLUGIN_ROOT can carry ANOTHER plugin's value
  # (this repo already refuses to trust CLAUDE_PLUGIN_DATA for the same reason). The hook must run
  # the update check that ships beside it, never one found through an inherited variable.
  ( local D="$T/upd-decoy"; mkdir -p "$D/decoy/scripts/lib" "$D/decoy/.claude-plugin"
    printf 'print("INJECTED by the decoy root")\n' > "$D/decoy/scripts/lib/update-check.py"
    printf '{ "name": "decoy", "version": "9.9.9" }\n' > "$D/decoy/.claude-plugin/plugin.json"
    mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    export PATH="$SHIMS:$PATH" CLAUDE_PLUGIN_ROOT="$D/decoy" REVIEW_COUNCIL_CONFIG="$D/config.json" \
           REVIEW_COUNCIL_CACHE_DIR="$D/cache" REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json"
    "$SK/hooks/session-start" > "$D/out.json" 2>/dev/null; local rc=$?
    assert_eq "hook exits 0 with a foreign CLAUDE_PLUGIN_ROOT" "$rc" 0
    local ctx; ctx=$(upd_hook_ctx "$D/out.json") || { fail "valid JSON with a foreign CLAUDE_PLUGIN_ROOT" "$(cat "$D/out.json")"; return; }
    printf '%s' "$ctx" > "$D/ctx.txt"
    assert_nogrep "the decoy root's script is never executed" "$D/ctx.txt" 'INJECTED'
    assert_grep "the hook's own update check still ran" "$D/ctx.txt" "^review-council 0\.9\.9 available: claude plugin update review-council\$"
  )
}

test_update_cache_dir_respects_xdg() {  # XDG_CACHE_HOME is the standard override; ~/.cache is only the default
  ( local D="$T/upd-xdg"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    env -u REVIEW_COUNCIL_CACHE_DIR XDG_CACHE_HOME="$D/xdg" REVIEW_COUNCIL_CONFIG="$D/config.json" \
      REVIEW_COUNCIL_UPDATE_URL="file://$FX/plugin-newer.json" python3 "$UPD" "$D/root" > "$D/out.txt" 2>&1
    assert_eq "still prints the line" "$(cat "$D/out.txt")" "$UPD_LINE"
    [ -f "$D/xdg/review-council/update-check.json" ] && ok "the cache lands under XDG_CACHE_HOME" \
      || fail "the cache lands under XDG_CACHE_HOME" "no $D/xdg/review-council/update-check.json"
  )
}

test_update_suite_defaults_keep_home_untouched() {  # the runner must sandbox every test, not just these two files
  ( assert_grep "run-tests.sh pins REVIEW_COUNCIL_CONFIG for every test" "$HERE/run-tests.sh" 'REVIEW_COUNCIL_CONFIG='
    assert_grep "run-tests.sh pins REVIEW_COUNCIL_CACHE_DIR for every test" "$HERE/run-tests.sh" 'REVIEW_COUNCIL_CACHE_DIR='
    assert_grep "run-tests.sh pins REVIEW_COUNCIL_UPDATE_URL for every test" "$HERE/run-tests.sh" 'REVIEW_COUNCIL_UPDATE_URL='
    case "${REVIEW_COUNCIL_CACHE_DIR:-}" in
      "$T"/*) ok "the inherited cache dir is inside the test sandbox" ;;
      *) fail "the inherited cache dir is inside the test sandbox" "got '${REVIEW_COUNCIL_CACHE_DIR:-<unset>}'"; return ;;
    esac
    case "${REVIEW_COUNCIL_UPDATE_URL:-}" in
      file://*) ok "the inherited update URL is a local fixture, not the network" ;;
      *) fail "the inherited update URL is a local fixture, not the network" "got '${REVIEW_COUNCIL_UPDATE_URL:-<unset>}'" ;;
    esac
    [ -e "${REVIEW_COUNCIL_CONFIG:-/nonexistent}" ] && fail "the inherited config path is a file that does not exist" "it exists" \
      || ok "the inherited config path is a file that does not exist"
    # and behaviourally: opted in, unreachable URL, no per-test cache override -> nothing under $HOME
    local D="$T/upd-home"; mk_upd_root "$D/root" 0.1.1; mk_upd_cfg "$D/config.json" '{ "check_updates": true }'
    local HC="$HOME/.cache/review-council/update-check.json"
    local before; before=$( [ -f "$HC" ] && cksum < "$HC" || echo absent )
    REVIEW_COUNCIL_CONFIG="$D/config.json" REVIEW_COUNCIL_UPDATE_URL="file://$D/no-such-file.json" \
      python3 "$UPD" "$D/root" > "$D/out.txt" 2>&1
    assert_eq "silent, as an unreachable URL should be" "$(cat "$D/out.txt")" ""
    local after; after=$( [ -f "$HC" ] && cksum < "$HC" || echo absent )
    assert_eq "nothing was written to the real ~/.cache/review-council" "$after" "$before"
  )
}
