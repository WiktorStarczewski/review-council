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
      'review-council seats: codex ✗ not installed · grok ✗ not installed · gemini ✗ not installed · claude ✓ (opus@max) · DEGRADED: only Claude is available - 3 Claude seats, no cross-lab decorrelation'
  )
}

# One lab plus the agent seat is two: one Claude seat is padded in and the banner names the shortfall.
test_roster_pads_one_seat() {
  ( local B="$T/roster-grokonly"; roster_env "$B" grok
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "grok + claude runs" "$?" 0
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_pads_one" "stdout is not JSON"; return 1; }
    roster_flags "$B/out.json" "$B/flags"
    assert_grep "grok seated"        "$B/lines" '^seat grok xai grok grok-4\.6 xhigh false null null$'
    assert_grep "opus seated"        "$B/lines" '^seat opus anthropic agent opus max false null null$'
    assert_grep "one Claude seat padded in" "$B/lines" '^seat claude-1 anthropic agent opus max false null null$'
    assert_nogrep "and only one"     "$B/lines" '^seat claude-2 '
    assert_grep "3 seats + the grok extra" "$B/lines" '^counts 3 4$'
    assert_grep "padded count"   "$B/flags" '^padded 1$'
    assert_grep "degraded"       "$B/flags" '^degraded true$'
    assert_grep "labs in seat order" "$B/flags" '^labs xai,anthropic$'
    assert_grep "the sentence names the labs and the padding" "$B/flags" \
      '^degradation only xai, anthropic available - padded with 1 Claude seat$'
    "$SCRIPTS/roster.sh" --brief > "$B/brief"
    assert_eq "--brief carries it" "$(cat "$B/brief")" \
      'review-council seats: codex ✗ not installed · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max) · DEGRADED: only xai, anthropic available - padded with 1 Claude seat'
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
  ( local B="$T/roster-full-keys"; roster_env "$B" codex grok gemini; roster_creds
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "full roster exits 0" "$?" 0
    roster_flags "$B/out.json" "$B/flags" || { fail "roster_full_keys" "flags unreadable"; return 1; }
    assert_grep "padded is zero"     "$B/flags" '^padded 0$'
    assert_grep "not degraded"       "$B/flags" '^degraded false$'
    assert_grep "every lab listed once, in seat order" "$B/flags" '^labs openai,xai,google,anthropic$'
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
  ( local B="$T/roster-minlabs-real"; roster_env "$B" grok
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_seat": false, "min_labs": 2}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "padded seats do not satisfy min_labs" "$?" 5
    roster_lines "$B/out.json" "$B/lines" || { fail "roster_minlabs_real" "stdout is not JSON"; return 1; }
    assert_grep "the count is of real labs, not padded ones" "$B/lines" \
      '^excluded min_labs -> strict: 1 lab\(s\) available, min_labs=2$'
    assert_grep "the panel is still built and reported" "$B/lines" '^counts 3 4$'
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
  ( local B="$T/roster-excl-all"; roster_env "$B" codex grok gemini; roster_creds
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"exclude": ["codex", "grok", "gemini", "claude"]}' > "$REVIEW_COUNCIL_CONFIG"
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
      'review-council seats: codex ✗ not installed · grok ✗ not installed · gemini ✗ not installed · claude ✗ disabled (3 padded seats) · DEGRADED: only Claude is available - 3 Claude seats, no cross-lab decorrelation'
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
  ( local B="$T/roster-brief-nopad"; roster_env "$B" codex grok gemini; roster_creds
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
