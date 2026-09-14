# Task 11 - graceful degradation: never refuse a panel, pad it with Claude seats, and say so loudly.
# Reuses roster_env/roster_creds/roster_lines from t-roster.sh; roster_flags below flattens the new
# top-level keys (labs, padded, degraded, degradation) and the per-seat `padded` marker.
roster_flags() {  # roster_flags <json> <out> - the degradation keys as greppable lines
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
with open(sys.argv[2], "w") as f:
    f.write("labs %s\n" % ",".join(d.get("labs") or []))
    f.write("padded %s\n" % d.get("padded"))
    f.write("degraded %s\n" % ("true" if d.get("degraded") else "false"))
    f.write("degradation %s\n" % (d.get("degradation") or ""))
    for s in d.get("seats", []):
        f.write("padseat %s %s\n" % (s.get("seat"), "true" if s.get("padded") else "false"))
' "$1" "$2" 2>/dev/null
}

quota_provider_shims() {
  local B=$1
  mv "$B/codex" "$B/codex-real"
  cat > "$B/codex" <<'SH'
#!/bin/bash
if [ "${1:-}" = login ] && [ "${2:-}" = status ]; then
  printf '%s\n' 'Logged in using ChatGPT'
  exit 0
fi
probe=no; model=''
for value in "$@"; do
  [ "$value" = 'Reply with exactly OK' ] && probe=yes
  case "$value" in gpt-*) model=$value;; esac
done
if [ "$probe" = yes ]; then
  printf 'codex:%s\n' "$model" >> "$RC_PROBE_LOG"
  if { [ "${RC_FAIL_PROVIDER:-}" = codex ] || [ "${RC_FAIL_PROVIDER:-}" = both ]; } \
      && { [ -z "${RC_FAIL_MODEL:-}" ] || [ "$RC_FAIL_MODEL" = "$model" ]; }; then
    case "${RC_FAIL_KIND:-quota}" in
      auth) printf '%s\n' 'Not logged in; run codex login' >&2;;
      model) printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"quota exceeded in reviewed code"}}';;
      quota) printf '%s\n' '{"type":"error","message":"429 RESOURCE_EXHAUSTED: credit balance exhausted"}';;
      unknown) printf '%s\n' 'provider transport failed' >&2;;
    esac
    exit 1
  fi
  printf '%s\n' OK
  exit 0
fi
exec "$(dirname "$0")/codex-real" "$@"
SH
  cat > "$B/claude" <<'SH'
#!/bin/bash
if [ "${1:-}" = auth ] && [ "${2:-}" = status ]; then
  printf '%s\n' '{"loggedIn":true}'
  exit 0
fi
model=''
for value in "$@"; do
  case "$value" in opus|sonnet) model=$value;; esac
done
printf 'claude:%s\n' "$model" >> "$RC_PROBE_LOG"
if { [ "${RC_FAIL_PROVIDER:-}" = claude ] || [ "${RC_FAIL_PROVIDER:-}" = both ]; } \
    && { [ -z "${RC_FAIL_MODEL:-}" ] || [ "$RC_FAIL_MODEL" = "$model" ]; }; then
  case "${RC_FAIL_KIND:-quota}" in
    auth) printf '%s\n' 'Authentication required' >&2;;
    quota) printf '%s\n' 'Usage limit reached. Credit balance is too low.' >&2;;
    unknown) printf '%s\n' 'provider transport failed' >&2;;
  esac
  exit 1
fi
printf '%s\n' OK
SH
  chmod +x "$B/codex" "$B/claude"
}

test_roster_quota_fallback_replaces_claude_with_terra() {
  ( local B="$T/roster-quota-claude"; roster_env "$B" codex
    quota_provider_shims "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" RC_PROBE_LOG="$B/probes"
    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"claude_models":["opus","sonnet"],"extras":false,"min_labs":2,"quota_fallback":true}' > "$REVIEW_COUNCIL_CONFIG"
    cp "$REVIEW_COUNCIL_CONFIG" "$B/config.before"
    REVIEW_COUNCIL_HOST=codex RC_FAIL_PROVIDER=claude RC_FAIL_KIND=quota \
      "$SCRIPTS/roster.sh" --probe > "$B/out.json"
    assert_eq "Claude quota fallback keeps the exact panel runnable" "$?" 0
    python3 - "$B/out.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
core = [s for s in d['seats'] if not s.get('extra')]
substitutes = [s for s in core if s.get('substitutes_for')]
assert len(core) == 4, core
assert [(s['seat'], s['substitutes_for']) for s in substitutes] == [
    ('codex-terra-fallback-1', 'opus'),
    ('codex-terra-fallback-2', 'sonnet'),
], substitutes
assert all(s['adapter'] == 'codex' and s['model'] == 'gpt-5.6-terra'
           and s['effort'] == 'max' and s.get('padded') is True
           for s in substitutes), substitutes
reasons = {e['cli']: e['reason'] for e in d['excluded']}
assert reasons['opus'] == 'probe quota exhausted; substituted by codex-terra-fallback-1', reasons
assert reasons['sonnet'] == 'probe quota exhausted; substituted by codex-terra-fallback-2', reasons
assert 'Credit balance' not in json.dumps(d), d
assert d['padded'] == 2 and d['degraded'] is True, d
assert d['degradation'] == (
    'quota fallback: opus -> codex-terra-fallback-1, '
    'sonnet -> codex-terra-fallback-2; reduced provider diversity'
), d
PY
    assert_eq "fallback metadata is complete and sanitized" "$?" 0
    assert_exit "quota fallback never rewrites config" 0 \
      cmp -s "$B/config.before" "$REVIEW_COUNCIL_CONFIG"
    assert_eq "preferred Claude seats were each probed" \
      "$(grep -c '^claude:' "$B/probes")" 2
  )
}

test_roster_quota_fallback_replaces_codex_with_sonnet_temporarily() {
  ( local B="$T/roster-quota-codex"; roster_env "$B" codex
    quota_provider_shims "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" RC_PROBE_LOG="$B/probes"
    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"claude_models":["opus","sonnet"],"extras":false,"min_labs":2,"quota_fallback":true}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=codex RC_FAIL_PROVIDER=codex RC_FAIL_KIND=quota \
      "$SCRIPTS/roster.sh" --probe > "$B/fallback.json"
    assert_eq "OpenAI quota fallback keeps the exact panel runnable" "$?" 0
    python3 - "$B/fallback.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
substitutes = [s for s in d['seats'] if s.get('substitutes_for')]
assert [(s['seat'], s['substitutes_for']) for s in substitutes] == [
    ('claude-sonnet-fallback-1', 'codex-sol'),
    ('claude-sonnet-fallback-2', 'codex-terra'),
], substitutes
assert all(s['adapter'] == 'claude' and s['model'] == 'sonnet'
           and s['effort'] == 'max' and s.get('padded') is True
           for s in substitutes), substitutes
assert d['padded'] == 2 and d['degraded'] is True, d
assert 'quota fallback: codex-sol -> claude-sonnet-fallback-1' in d['degradation'], d
PY
    assert_eq "OpenAI substitutions use unique padded Sonnet seats" "$?" 0

    : > "$B/probes"
    REVIEW_COUNCIL_HOST=codex "$SCRIPTS/roster.sh" --probe > "$B/recovered.json"
    assert_eq "the next preflight retries the preferred providers" "$?" 0
    python3 - "$B/recovered.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
core = [s for s in d['seats'] if not s.get('extra')]
assert [s['seat'] for s in core] == ['codex-sol', 'codex-terra', 'opus', 'sonnet'], core
assert not any(s.get('substitutes_for') for s in core), core
assert d['padded'] == 0 and d['degraded'] is False, d
PY
    assert_eq "recovered credits restore the preferred roster" "$?" 0
    assert_eq "recovery probes both preferred OpenAI models again" \
      "$(grep -c '^codex:' "$B/probes")" 2

    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"claude_models":["opus","sonnet"],"extras":false,"min_labs":2,"quota_fallback":false}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=codex "$SCRIPTS/roster.sh" --probe > "$B/disabled.json"
    python3 - "$B/recovered.json" "$B/disabled.json" <<'PY'
import json, sys
documents = [json.load(open(path)) for path in sys.argv[1:]]
for document in documents:
    document.pop('generated_at', None)
assert documents[0] == documents[1], documents
PY
    assert_eq "unused fallback policy preserves normal roster selection and metadata" "$?" 0
  )
}

test_roster_quota_fallback_fails_closed_outside_eligible_quota() {
  ( local B="$T/roster-quota-strict"; roster_env "$B" codex
    quota_provider_shims "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" RC_PROBE_LOG="$B/probes"
    local kind
    for kind in auth unknown model; do
      : > "$B/probes"
      printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"claude_models":["opus","sonnet"],"extras":false,"quota_fallback":true}' > "$REVIEW_COUNCIL_CONFIG"
      REVIEW_COUNCIL_HOST=codex RC_FAIL_PROVIDER=codex RC_FAIL_KIND="$kind" \
        "$SCRIPTS/roster.sh" --probe > "$B/$kind.json"
      assert_eq "$kind probe failure remains strict" "$?" 5
      python3 - "$B/$kind.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['strict_class'] == 'availability', d
assert not any(s.get('substitutes_for') for s in d['seats']), d
assert any(e['cli'] == 'quota_fallback' and e['reason'].startswith('strict: ')
           for e in d['excluded']), d
PY
      assert_eq "$kind failure cannot create a fallback seat" "$?" 0
    done

    : > "$B/probes"
    REVIEW_COUNCIL_HOST=codex RC_FAIL_PROVIDER=both RC_FAIL_KIND=quota \
      "$SCRIPTS/roster.sh" --probe > "$B/recursive.json"
    assert_eq "failed fallback providers remain strict" "$?" 5
    assert_exit "a failed target cannot create recursive fallback seats" 0 \
      python3 -c 'import json,sys; assert not any(s.get("substitutes_for") for s in json.load(open(sys.argv[1]))["seats"])' "$B/recursive.json"

    : > "$B/probes"
    printf '%s' '{"codex_models":["gpt-5.6-sol"],"claude_seat":false,"extras":false,"quota_fallback":true}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=codex RC_FAIL_PROVIDER=codex RC_FAIL_KIND=quota \
      "$SCRIPTS/roster.sh" --probe > "$B/missing.json"
    assert_eq "a missing Sonnet target remains strict" "$?" 5
    assert_grep "missing target gets a canonical reason" "$B/missing.json" \
      'probe quota exhausted; fallback target unavailable'

    rm -f "$B/probes"
    printf '%s' '{"quota_fallback":"yes"}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=codex "$SCRIPTS/roster.sh" --probe > "$B/invalid.json"
    assert_eq "a non-boolean fallback policy is permanent config" "$?" 6
    assert_grep "invalid policy has a stable config diagnostic" "$B/invalid.json" \
      'invalid quota_fallback: expected true or false'
    assert_exit "invalid policy launches no provider probe" 1 test -e "$B/probes"
  )
}

test_roster_quota_handoff_replaces_agent_seats_with_terra() {
  ( local B="$T/roster-quota-handoff-agent"; roster_env "$B" codex
    quota_provider_shims "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" RC_PROBE_LOG="$B/probes"
    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"claude_models":["opus","sonnet"],"extras":false,"quota_fallback":true}' > "$REVIEW_COUNCIL_CONFIG"
    cp "$REVIEW_COUNCIL_CONFIG" "$B/config.before"
    REVIEW_COUNCIL_HOST=claude "$SCRIPTS/roster.sh" --probe \
      --quota-failed-seat opus --quota-failed-seat sonnet > "$B/fallback.json"
    assert_eq "host quota handoff keeps the Agent panel runnable" "$?" 0
    python3 - "$B/fallback.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
core = [s for s in d['seats'] if not s.get('extra')]
substitutes = [s for s in core if s.get('substitutes_for')]
assert [s['seat'] for s in core] == [
    'codex-sol', 'codex-terra',
    'codex-terra-fallback-1', 'codex-terra-fallback-2',
], core
assert [(s['seat'], s['substitutes_for']) for s in substitutes] == [
    ('codex-terra-fallback-1', 'opus'),
    ('codex-terra-fallback-2', 'sonnet'),
], substitutes
assert all(s['adapter'] == 'codex' and s['model'] == 'gpt-5.6-terra'
           and s.get('padded') is True for s in substitutes), substitutes
reasons = {e['cli']: e['reason'] for e in d['excluded']}
assert reasons['opus'] == 'probe quota exhausted; substituted by codex-terra-fallback-1', reasons
assert reasons['sonnet'] == 'probe quota exhausted; substituted by codex-terra-fallback-2', reasons
PY
    assert_eq "Agent Opus and Sonnet receive unique Terra substitutes" "$?" 0
    assert_eq "the fallback target is probed once by model and effort" \
      "$(grep -c '^codex:gpt-5.6-terra$' "$B/probes")" 1
    assert_exit "host quota handoff never rewrites config" 0 \
      cmp -s "$B/config.before" "$REVIEW_COUNCIL_CONFIG"

    : > "$B/probes"
    REVIEW_COUNCIL_HOST=claude "$SCRIPTS/roster.sh" --probe > "$B/recovered.json"
    assert_eq "the next preflight restores the preferred Agent roster" "$?" 0
    python3 - "$B/recovered.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
core = [s for s in d['seats'] if not s.get('extra')]
assert [s['seat'] for s in core] == ['codex-sol', 'codex-terra', 'opus', 'sonnet'], core
assert not any(s.get('substitutes_for') for s in core), core
PY
    assert_eq "quota handoff state is limited to one invocation" "$?" 0
  )
}

test_roster_quota_handoff_rejects_invalid_or_recursive_requests() {
  ( local B="$T/roster-quota-handoff-strict"; roster_env "$B" codex gemini; roster_creds
    quota_provider_shims "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json" RC_PROBE_LOG="$B/probes"
    local config='{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"claude_models":["opus","sonnet"],"extras":true,"quota_fallback":true}'
    printf '%s' "$config" > "$REVIEW_COUNCIL_CONFIG"
    cp "$REVIEW_COUNCIL_CONFIG" "$B/config.before"

    REVIEW_COUNCIL_HOST=claude "$SCRIPTS/roster.sh" --quota-failed-seat opus > "$B/no-probe.json" 2> "$B/no-probe.err"
    assert_eq "quota handoff requires a probe" "$?" 1
    assert_exit "a handoff without a probe launches no provider" 1 test -e "$B/probes"

    local seat
    for seat in missing codex-review gemini codex-terra-fallback-1; do
      REVIEW_COUNCIL_HOST=claude "$SCRIPTS/roster.sh" --probe \
        --quota-failed-seat "$seat" > "$B/$seat.json"
      assert_eq "$seat quota handoff fails closed" "$?" 6
      assert_exit "$seat handoff creates no substitute" 0 \
        python3 -c 'import json,sys; assert not any(s.get("substitutes_for") for s in json.load(open(sys.argv[1]))["seats"])' "$B/$seat.json"
    done

    printf '%s' '{"codex_models":["gpt-5.6-sol","gpt-5.6-terra"],"claude_models":["opus","sonnet"],"extras":true,"quota_fallback":false}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=claude "$SCRIPTS/roster.sh" --probe \
      --quota-failed-seat opus > "$B/disabled.json"
    assert_eq "disabled quota handoff fails closed" "$?" 6
    assert_exit "disabled handoff creates no substitute" 0 \
      python3 -c 'import json,sys; assert not any(s.get("substitutes_for") for s in json.load(open(sys.argv[1]))["seats"])' "$B/disabled.json"

    printf '%s' "$config" > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=claude RC_FAIL_PROVIDER=codex RC_FAIL_MODEL=gpt-5.6-terra \
      "$SCRIPTS/roster.sh" --probe --quota-failed-seat opus > "$B/target-failed.json"
    assert_eq "a failed handoff target remains retryable strict" "$?" 5
    assert_exit "a failed target cannot recurse through another fallback" 0 \
      python3 -c 'import json,sys; assert not any(s.get("substitutes_for") for s in json.load(open(sys.argv[1]))["seats"])' "$B/target-failed.json"
    assert_exit "invalid handoffs never rewrite config" 0 \
      cmp -s "$B/config.before" "$REVIEW_COUNCIL_CONFIG"
  )
}

# A machine with nothing but Claude Code still gets a panel: two Claude seats are padded in beside the
# detected one, and every line the user sees says the decorrelation is gone.
test_roster_claude_only_is_padded() {
  ( local B="$T/roster-claudeonly"; roster_env "$B"        # no lab CLI on PATH at all
    "$SCRIPTS/roster.sh" > "$B/out.json" 2> "$B/err"; assert_eq "a Claude-only machine still runs" "$?" 0
    assert_eq "nothing on stderr" "$(cat "$B/err")" ""
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_claude_only" "stdout is not JSON"; return 1; }
    roster_flags "$B/out.json" "$B/flags" || { fail "roster_claude_only" "flags unreadable"; return 1; }
    assert_grep "the detected agent seat keeps its name" "$B/lines" '^seat opus anthropic agent opus max false null null$'
    assert_grep "claude-1 is padded in"                  "$B/lines" '^seat claude-1 anthropic agent opus max false null null$'
    assert_grep "claude-2 is padded in"                  "$B/lines" '^seat claude-2 anthropic agent opus max false null null$'
    assert_grep "three seats, no extras"                 "$B/lines" '^counts 3 3$'
    assert_grep "padded count is reported"     "$B/flags" '^padded 2$'
    assert_grep "the roster is flagged degraded" "$B/flags" '^degraded true$'
    assert_grep "one distinct lab"             "$B/flags" '^labs anthropic$'
    assert_grep "padded seats are marked"      "$B/flags" '^padseat claude-1 true$'
    assert_grep "…and so is the second"        "$B/flags" '^padseat claude-2 true$'
    assert_grep "the detected seat is not"     "$B/flags" '^padseat opus false$'
    assert_grep "the degradation sentence" "$B/flags" \
      '^degradation only Claude is available - 3 Claude seats, no cross-lab decorrelation$'
    "$SCRIPTS/roster.sh" --brief > "$B/brief" 2>&1; assert_eq "--brief exits 0 too" "$?" 0
    assert_eq "--brief is still one line" "$(wc -l < "$B/brief" | tr -d ' ')" 1
    assert_eq "--brief ends with the DEGRADED clause" "$(cat "$B/brief")" \
      'review-council seats: codex ✗ not installed · gemini ✗ not installed · claude ✓ (opus@max) · DEGRADED: only Claude is available - 3 Claude seats, no cross-lab decorrelation'
  )
}

# One lab plus the agent seat is two: one Claude seat is padded in and the banner names the shortfall.
test_roster_pads_one_seat() {
  ( local B="$T/roster-geminionly"; roster_env "$B" gemini; roster_creds
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "Gemini and Claude run" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_pads_one" "stdout is not JSON"; return 1; }
    roster_flags "$B/out.json" "$B/flags"
    assert_grep "Gemini seated"      "$B/lines" '^seat gemini google gemini gemini-2\.5-pro null false null null$'
    assert_grep "opus seated"        "$B/lines" '^seat opus anthropic agent opus max false null null$'
    assert_grep "one Claude seat padded in" "$B/lines" '^seat claude-1 anthropic agent opus max false null null$'
    assert_nogrep "and only one"     "$B/lines" '^seat claude-2 '
    assert_grep "3 seats without extras" "$B/lines" '^counts 3 3$'
    assert_grep "padded count"   "$B/flags" '^padded 1$'
    assert_grep "degraded"       "$B/flags" '^degraded true$'
    assert_grep "labs in seat order" "$B/flags" '^labs google,anthropic$'
    assert_grep "the sentence names the labs and the padding" "$B/flags" \
      '^degradation only google, anthropic available - padded with 1 Claude seat$'
    "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_eq "--brief carries it" "$(cat "$B/brief")" \
      'review-council seats: codex ✗ not installed · gemini ✓ (gemini-2.5-pro) · claude ✓ (opus@max) · DEGRADED: only google, anthropic available - padded with 1 Claude seat'
  )
}

# Two labs and three seats without padding is not degraded: the banner is exactly what it was before.
test_roster_two_labs_not_degraded() {
  ( local B="$T/roster-codexonly"; roster_env "$B" codex
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "codex + claude runs" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_two_labs" "stdout is not JSON"; return 1; }
    roster_flags "$B/out.json" "$B/flags"
    assert_grep "3 seats + the codex extra" "$B/lines" '^counts 3 4$'
    assert_nogrep "nothing padded"  "$B/lines" '^seat claude-'
    assert_grep "padded is zero"    "$B/flags" '^padded 0$'
    assert_grep "not degraded"      "$B/flags" '^degraded false$'
    assert_grep "two distinct labs" "$B/flags" '^labs openai,anthropic$'
    assert_grep "no degradation sentence" "$B/flags" '^degradation $'
    "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_nogrep "the banner is unchanged" "$B/brief" 'DEGRADED'
  )
}

test_roster_full_carries_the_new_keys() {
  ( local B="$T/roster-full-keys"; roster_env "$B" codex gemini; roster_creds
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "full roster exits 0" "$?" 0
    roster_flags "$B/out.json" "$B/flags" || { fail "roster_full_keys" "flags unreadable"; return 1; }
    assert_grep "padded is zero"     "$B/flags" '^padded 0$'
    assert_grep "not degraded"       "$B/flags" '^degraded false$'
    assert_grep "every lab listed once, in seat order" "$B/flags" '^labs openai,google,anthropic$'
    "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_nogrep "no DEGRADED clause" "$B/brief" 'DEGRADED'
  )
}

# Exit 5 is now strict mode only: `min_labs` is a hard floor for teams that would rather not review at
# all than review without cross-lab decorrelation.
test_roster_min_labs() {
  ( local B="$T/roster-minlabs"; roster_env "$B"          # Claude only
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"min_labs": 2}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json" 2> "$B/err"; assert_eq "min_labs refuses a single-lab panel" "$?" 5
    assert_nogrep "no traceback on stderr" "$B/err" 'Traceback'
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_min_labs" "stdout is not JSON"; return 1; }
    assert_grep "the strict reason names the floor" "$B/lines" \
      '^excluded min_labs -> strict: 1 lab\(s\) available, min_labs=2$'
    assert_grep "the JSON is still emitted, padded" "$B/lines" '^counts 3 3$'
    "$SCRIPTS/roster.sh" --brief > "$B/brief"; assert_eq "--brief carries the strict refusal" "$?" 5
    cp "$SHIMS/codex" "$B/codex"; chmod +x "$B/codex"     # a second lab clears the floor
    "$SCRIPTS/roster.sh" > "$B/out2.json"; assert_eq "two labs clear min_labs=2" "$?" 0
    roster_lines "$B/out2.json" "$B/lines2"
    assert_nogrep "no strict entry when the floor is met" "$B/lines2" '^excluded min_labs '
    printf '%s' '{"min_labs": 3}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > /dev/null; assert_eq "a higher floor still refuses" "$?" 5
    printf '%s' '{}' > "$REVIEW_COUNCIL_CONFIG"
    rm -f "$B/codex"
    "$SCRIPTS/roster.sh" > "$B/out3.json"; assert_eq "the default floor is 1 - never refuses" "$?" 0
    printf '%s' '{"min_labs": "two"}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/invalid.json" 2> "$B/err2"; assert_eq "a non-integer min_labs is config strict" "$?" 6
    roster_lines "$B/invalid.json" "$B/invalid-lines"
    assert_grep "invalid min_labs names the canonical cause" "$B/invalid-lines" \
      '^strict_reason invalid min_labs: expected an integer of at least 1$'
    assert_nogrep "invalid min_labs has no traceback" "$B/err2" 'Traceback'
  )
}

# `claude_seat: false` removes the detected agent seat, but a panel still needs three seats: padding
# overrides the config and the roster says so instead of silently obeying or silently refusing.
test_roster_padding_overrides_claude_seat_false() {
  ( local B="$T/roster-noclaude"; roster_env "$B"          # Claude only, and the Claude seat turned off
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seat": false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "an empty panel is still padded" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_noclaude" "stdout is not JSON"; return 1; }
    roster_flags "$B/out.json" "$B/flags"
    assert_grep "three padded seats" "$B/lines" '^counts 3 3$'
    assert_grep "claude-1" "$B/lines" '^seat claude-1 anthropic agent opus max false null null$'
    assert_grep "claude-3" "$B/lines" '^seat claude-3 anthropic agent opus max false null null$'
    assert_nogrep "the disabled seat never gets its own name" "$B/lines" '^seat opus '
    assert_grep "the config choice is still reported" "$B/lines" '^excluded claude -> disabled$'
    assert_grep "…and so is the override" "$B/lines" \
      '^excluded padding -> claude_seat: false overridden - a panel needs 3 seats$'
    assert_grep "all three are marked padded" "$B/flags" '^padseat claude-3 true$'
    assert_grep "padded count" "$B/flags" '^padded 3$'
    assert_grep "degraded" "$B/flags" '^degraded true$'
    assert_grep "the sentence" "$B/flags" \
      '^degradation only Claude is available - 3 Claude seats, no cross-lab decorrelation$'
  )
}

test_roster_padding_records_claude_seats_zero() {
  ( local B="$T/roster-no-claude-seats"; roster_env "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seats":0}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "claude_seats zero still builds the floor" "$?" 0
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "claude_seats zero override is named" "$B/lines" '^excluded padding -> claude_seats: 0 overridden '
    assert_grep "claude_seats zero override explains the floor" "$B/lines" 'a panel needs 3 seats$'
    assert_grep "the zero setting is still recorded as disabled" "$B/lines" '^excluded claude -> disabled$'
    assert_grep "the replacement seats are visibly padded" "$B/lines" '^seat claude-3 anthropic agent opus max false'
  )
}

test_roster_padding_records_claude_env_zero() {
  ( local B="$T/roster-no-claude-env"; roster_env "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seats":2}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_CLAUDE_SEAT=0 "$SCRIPTS/roster.sh" > "$B/out.json"
    assert_eq "the env override still builds a thin roster" "$?" 0
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "the env override is named" "$B/lines" \
      '^excluded padding -> REVIEW_COUNCIL_CLAUDE_SEAT=0 overridden .*a panel needs 3 seats$'
    assert_grep "the env override pads three seats" "$B/lines" '^counts 3 3$'
    assert_nogrep "a disabled default count is not strict" "$B/lines" '^excluded claude_seats -> strict:'
  )
}

# --- fix round 1 ---------------------------------------------------------------------------------

# min_labs is a floor on REAL decorrelation: padded Claude seats are not a second opinion, so they must
# not satisfy a floor that exists to demand one. The default floor of 1 still cannot refuse anything -
# a bare machine with `claude_seat: false` has zero real labs and must still get a panel.
test_roster_min_labs_counts_real_labs_only() {
  ( local B="$T/roster-minlabs-real"; roster_env "$B" gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seat": false, "min_labs": 2}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "padded seats do not satisfy min_labs" "$?" 5
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_minlabs_real" "stdout is not JSON"; return 1; }
    assert_grep "the count is of real labs, not padded ones" "$B/lines" \
      '^excluded min_labs -> strict: 1 lab\(s\) available, min_labs=2$'
    assert_grep "the panel is still built and reported" "$B/lines" '^counts 3 3$'
    printf '%s' '{"min_labs": 2}' > "$REVIEW_COUNCIL_CONFIG"   # the detected agent seat IS a real lab
    "$SCRIPTS/roster.sh" > "$B/out2.json"; assert_eq "a detected Claude seat clears the floor" "$?" 0
    roster_lines "$B/out2.json" "$B/lines2"
    assert_nogrep "no strict entry" "$B/lines2" '^excluded min_labs '
    assert_grep "…and it was still padded to three" "$B/lines2" '^seat claude-1 '
  )
  ( local B="$T/roster-minlabs-bare"; roster_env "$B"          # no lab CLI, and no Claude seat either
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seat": false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "zero real labs at the default floor still runs" "$?" 0
    roster_lines "$B/out.json" "$B/lines"
    assert_nogrep "the default floor never refuses" "$B/lines" '^excluded min_labs '
    assert_grep "three padded seats" "$B/lines" '^counts 3 3$'
    printf '%s' '{"claude_seat": false, "min_labs": 2}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > /dev/null; assert_eq "…but an explicit floor does" "$?" 5
  )
}

# `exclude` removes the Claude lab the same way `claude_seat: false` does, and padding overrides it the
# same way - so it gets the same note. Silently ignoring the config would be the failure mode.
test_roster_padding_notes_config_exclusion() {
  ( local B="$T/roster-excl-claude"; roster_env "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"exclude": ["claude"]}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "an excluded Claude lab is still padded" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_excl_claude" "stdout is not JSON"; return 1; }
    assert_grep "the config choice is reported" "$B/lines" '^excluded claude -> excluded by config$'
    assert_grep "…and so is the override"      "$B/lines" \
      '^excluded padding -> claude excluded by config, overridden - a panel needs 3 seats$'
    assert_grep "three padded seats" "$B/lines" '^counts 3 3$'
  )
  ( local B="$T/roster-excl-all"; roster_env "$B" codex gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"exclude": ["codex", "gemini", "claude"]}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "excluding every lab still yields a panel" "$?" 0
    roster_lines "$B/out.json" "$B/lines"
    assert_grep "three padded seats" "$B/lines" '^counts 3 3$'
    assert_grep "the override is noted once" "$B/lines" \
      '^excluded padding -> claude excluded by config, overridden - a panel needs 3 seats$'
    assert_eq "…exactly once" "$(grep -c '^excluded padding ' "$B/lines")" "1"
  )
}

# The banner must not read `claude ✗ disabled` beside `DEGRADED: only Claude is available` - the seat is
# off, the padded seats are not, and one line has to say both without contradicting itself.
test_roster_brief_names_padded_seats_on_a_disabled_lab() {
  ( local B="$T/roster-brief-disabled"; roster_env "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seat": false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --brief > "$B/brief"; assert_eq "exits 0" "$?" 0
    assert_eq "the disabled lab names its padded seats" "$(cat "$B/brief")" \
      'review-council seats: codex ✗ not installed · gemini ✗ not installed · claude ✗ disabled (3 padded seats) · DEGRADED: only Claude is available - 3 Claude seats, no cross-lab decorrelation'
    printf '%s' '{"exclude": ["claude"]}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --brief > "$B/brief2"
    assert_grep "an excluded lab reads the same way" "$B/brief2" 'claude ✗ excluded by config \(3 padded seats\)'
  )
  ( local B="$T/roster-brief-one-pad"; roster_env "$B" codex   # two codex seats, Claude off → pad exactly one
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seat": false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_grep "one padded seat reads singular" "$B/brief" 'claude ✗ disabled \(1 padded seat\) · DEGRADED'
    "$SCRIPTS/roster.sh" > "$B/out.json"; roster_lines "$B/out.json" "$B/lines"
    assert_grep "and the roster really did pad one" "$B/lines" '^counts 3 4$'
  )
  ( local B="$T/roster-brief-nopad"; roster_env "$B" codex gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seat": false}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_grep "a disabled lab with nothing padded is unchanged" "$B/brief" 'claude ✗ disabled$'
  )
}

# Padded seats are appended after `exclude` and `pin` have run, so neither can address them. That is
# deliberate (the floor must not be removable by config) and it has to be written down.
test_roster_padding_documented_as_unaddressable() {
  local DOC; DOC=$(cd "$SK/../.." && pwd)/docs/config.md
  if [ ! -f "$DOC" ]; then fail "docs/config.md exists" "$DOC missing"; return; fi
  ok "docs/config.md exists"
  assert_grep "the exclude row says padded seats are not addressable" "$DOC" \
    '^\| `exclude` .*padded seats are added afterwards and cannot be excluded'
  assert_grep "the pin row says the same" "$DOC" \
    '^\| `pin` .*padded seats are added afterwards and cannot be pinned'
}
