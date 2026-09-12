# The default schedule must preserve the independent discovery and verification
# panels without paying for eight unconditional full-panel rounds.
assert_flat_fixed() {
  local name=$1 file=$2 expected=$3 flat
  flat="$T/flat-$(basename "$file")-$RANDOM"
  tr '\n' ' ' < "$file" | tr -s ' ' > "$flat"
  grep -Fq -- "$expected" "$flat" && ok "$name" || fail "$name" "missing fixed text in $file"
}

test_adaptive_schedule_contract() {
  local K
  local timing='One four-bundle verification panel reviews the latest material state: directly after discovery when no nontrivial fix follows, or after the latest nontrivial fix.'
  local plan_trigger='Run the plan panel when accepted findings require a nontrivial change; skip it when there is no accepted fix or every accepted fix is a P3 or one-line P2.'
  local extras='Adaptive default panels use core seats and omit extras. Explicit numeric round plans may include extras in their configured rounds.'
  local repair='After a risk or verification panel returns at least three valid reviewers, compute coverage from valid outputs for any roster size; run every missing bundle as an `<N>x` repair on a distinct surviving seat before certification.'
  local numeric_continue="Only numeric mode continues past its requested minimum while any of these hold: the last numbered code panel produced a new P0/P1; the last numbered panel's fixes were nontrivial; any P0/P1 remains open; or a lens or major changed file remains unreviewed."
  local numeric_stop='Numeric mode stops only after the requested minimum numbered code panels ran, two consecutive numbered code panels produced no new P0/P1, no P0/P1 remains open, and gates are at or better than baseline. Plan panels do not count as numbered code panels.'
  local receipt='Current-session completion and finding yield require a schema-valid result with a successful exit receipt. Only exact hashed receiptless results recorded in a versioned legacy roster policy may omit one. Usage-bearing failed attempts remain metered.'
  for K in "$SK/skills/rev/SKILL.md" "$SK/codex-skills/rev/SKILL.md"; do
    assert_nogrep "$(basename "$(dirname "$(dirname "$K")")") has no eight-round floor" "$K" 'minimum[^[:alnum:]]{0,12}(8|eight)|8 rounds|eight rounds' -i
    assert_flat_fixed "normal schedule budgets one final panel" "$K" 'normal review plans 12 seat launches: four simplicity, four conditional plan, and four final verification launches.'
    assert_flat_fixed "large schedule adds only risk discovery" "$K" 'large or high-risk review plans 16 by adding four risk-discovery launches.'
    assert_grep "large threshold names 25 files" "$K" 'more than 25 changed files'
    assert_grep "large threshold names 1500 lines" "$K" 'more than 1,500 changed lines'
    assert_flat_fixed "verification timing is canonical" "$K" "$timing"
    assert_flat_fixed "plan trigger is canonical" "$K" "$plan_trigger"
    assert_flat_fixed "extras policy is canonical" "$K" "$extras"
    assert_flat_fixed "bundle repair is canonical" "$K" "$repair"
    assert_grep "explicit round count is named" "$K" '[Ee]xplicit round count'
    assert_grep "explicit rounds remain a minimum override" "$K" 'minimum override'
    assert_grep "numeric schedule preserves round 8 regression" "$K" '\| 8 \|[^|]*\| regression \|'
    assert_grep "numeric mode exclusively uses the legacy schedule" "$K" '[Ee]xplicit numeric.*(exclusively|instead).*legacy'
    assert_nogrep "numeric schedule has no additional-round ambiguity" "$K" 'additional requested rounds|legacy lens rotation for any additional'
    assert_flat_fixed "numeric continuation is restored" "$K" "$numeric_continue"
    assert_flat_fixed "numeric stop is restored" "$K" "$numeric_stop"
    assert_flat_fixed "adaptive completion covers every bundle" "$K" 'Do not certify the adaptive panel until all four bundles have valid results.'
    assert_nogrep "verification is not duplicated after a fix" "$K" 'always.*verification.*after discovery.*again|after discovery.*and again' -i
    assert_nogrep "bundle repair is not limited by roster size" "$K" 'only three core seats|a four-seat panel loses|three-seat panel or failed bundle owner' -i
    assert_nogrep "legacy plan trigger is absent" "$K" 'Before fixing after round 1'
    assert_grep "code launch records exact seats" "$K" 'phase=fan-out round=<N> "seats=\$LAUNCHED_SEATS"'
    assert_grep "repair launch records exact seats" "$K" 'phase=repair round=<N>x "seats=\$REPAIR_SEATS"'
    assert_grep "plan launch records exact seats" "$K" 'phase=plan round=<N>p "seats=\$PLAN_SEATS"'
    assert_grep "plan panel restores every surviving core seat" "$K" 'PLAN_SEATS.*every surviving non-extra seat|every surviving non-extra seat.*PLAN_SEATS'
    assert_grep "seat lists are rebuilt rather than accumulated" "$K" '[Rr]ebuild.*seat.*list.*before every|[Ee]xtra.*absent from the next panel'
    assert_grep "collect state retains exact seats" "$K" 'phase=collect round=<N> "seats=\$LAUNCHED_SEATS"'
    assert_grep "exit 5 is documented as retryable" "$K" '[Ee]xit 5 is retryable'
    assert_grep "exit 6 is documented as permanent" "$K" '[Ee]xit 6 is permanent'
    assert_flat_fixed "receipt completion policy is canonical" "$K" "$receipt"
    assert_grep "cumulative ledger is forbidden in prompts" "$K" '[Nn]ever.*cumulative findings ledger|cumulative findings ledger.*never'
  done

  assert_flat_fixed "Claude simplicity contract uses the exact adaptive row" \
    "$SK/skills/rev/SKILL.md" '| Simplicity discovery | always | simplicity for every seat |'
  assert_flat_fixed "Codex simplicity contract uses the exact adaptive sentence" \
    "$SK/codex-skills/rev/SKILL.md" '1. **Simplicity discovery:** every core seat gets `simplicity`. Keep all four seats;'

  assert_flat_fixed "Claude numeric schedule keeps its round 5 lenses" "$SK/skills/rev/SKILL.md" '| 5 | API & contract, compatibility | api-contract, data-state, readability | - |'
  assert_flat_fixed "Codex numeric schedule keeps its round 5 lenses" "$SK/codex-skills/rev/SKILL.md" '| 5 | Contracts and compatibility | api-contract, readability, maintainability | - |'
  for K in "$SK/skills/rev/SKILL.md" "$SK/codex-skills/rev/SKILL.md"; do
    assert_grep "numeric schedule restores Emphasis column" "$K" '^\| Round \| Emphasis \| Lenses(, in order)? \| Extra( seat)? \|$'
    assert_grep "numeric round 3 restores its extra" "$K" '^\| 3 \|.*\| security, data-state \| `?codex-review`?.*\|$'
    assert_grep "numeric round 4 restores its extra" "$K" '^\| 4 \|.*\| concurrency, resources, performance \| `?grok-code-review`?.*\|$'
  done

  local ST
  for ST in "$SK/skills/stack/SKILL.md" "$SK/codex-skills/stack/SKILL.md"; do
    assert_grep "stack names numeric legacy continuation" "$ST" 'numeric.*continue.*past.*minimum' -i
    assert_grep "stack says plan panels do not count" "$ST" '[Pp]lan panels do not count'
    assert_grep "stack exit 5 is retryable" "$ST" '[Ee]xit 5 is retryable'
    assert_grep "stack exit 6 is permanent" "$ST" '[Ee]xit 6 is permanent'
  done
  assert_grep "stack example documents numeric continuation" "$SK/scripts/stack.example.sh" 'numeric mode may continue past it'
  assert_grep "stack example excludes plan panels from count" "$SK/scripts/stack.example.sh" '[Pp]lan panels do not count'

  local D
  for D in "$SK/../../README.md" "$SK/../../docs/codex.md" "$SK/../../docs/superpowers/specs/2026-09-11-token-efficient-council-design.md"; do
    assert_nogrep "$(basename "$D") has no undefined two-provider spot check" "$D" 'two-provider|two different providers|two providers' -i
    assert_flat_fixed "$(basename "$D") uses canonical verification timing" "$D" "$timing"
  done
  assert_flat_fixed "README uses canonical extras policy" "$SK/../../README.md" "$extras"
  for D in "$SK/skills/rev/SKILL.md" "$SK/codex-skills/rev/SKILL.md" "$SK/../../README.md" "$SK/../../docs/codex.md" "$SK/../../CHANGELOG.md"; do
    assert_grep "$(basename "$D") states 12 launches" "$D" '12 seat launches|plans 12 launches|plans four simplicity'
    assert_flat_fixed "$(basename "$D") states 16 launches" "$D" 'A large or high-risk review plans 16 by adding four risk-discovery launches.'
  done
}

test_assert_grep_honors_flags() {
  printf 'UPPERCASE CONTRACT\n' > "$T/grep-flags"
  assert_grep "assert_grep honors case-insensitive matching" "$T/grep-flags" 'uppercase contract' -i
}

test_bounded_reviewer_contract() {
  local A="$SK/agents/rev-reviewer.md" B="$SK/../../eval/bench-case.sh"
  assert_nogrep "reviewer has no blanket surrounding-code read" "$A" 'Read the surrounding code'
  assert_grep "reviewer follows prompt ordering before evidence reads" "$A" 'ordering rule in the prompt'
  assert_grep "reviewer locates symbols and references" "$A" 'enclosing symbol or named section.*direct references'
  assert_grep "reviewer reads narrow windows" "$A" 'smallest useful line window'
  assert_grep "reviewer expands for a concrete question" "$A" 'concrete question.*prove or refute'
  assert_grep "reviewer stops answered evidence paths" "$A" 'Stop that evidence path when the question is answered'
  assert_nogrep "benchmark launcher has no unlimited-work wording" "$B" 'no time or token budget|unlimited work|Reason at maximum depth' -i
}
