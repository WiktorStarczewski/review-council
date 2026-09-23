# The fix-plan gate: rev-prompt.sh --plan renders a plan-review prompt (plan section, plan lenses, rule-not-instance
# suggested_fix requirement) on top of the normal code scope, and refuses a missing plan.
test_plan_prompt() {
  local S="$T/plan-session"; mkdir -p "$S"
  printf "REV_BASE='0000000'\nREV_BRANCH='feat'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" "$T" > "$S/scope.env"
  printf 'src/a.ts\n' > "$S/files.txt"
  printf '## C-01 · re-check ownership after every parking await\nRule: every call after an await re-checks the hold.\nSites: src/a.ts:10\nTest: a.test.ts\n' > "$S/fix-plan.md"
  printf '%s\n' '- CONTEXT-SENTINEL-c04: retry ownership is checked after parking' > "$S/context.md"
  printf '%s\n' 'FINDINGS-SENTINEL-c04' > "$S/findings.md"
  printf '# Add an admin listing endpoint\n\nFor the browser dashboard demo.\n\nPR-SENTINEL-c04\n' > "$S/pr.md"
  local out
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol plan-completeness "plan round" --plan "$S/fix-plan.md" 2> "$S/normal-plan.err") || { fail "plan prompt renders"; return; }
  ok "plan prompt renders"
  assert_nogrep "normal plan prompt stays below its word budget" "$S/normal-plan.err" '.'
  assert_grep "plan prompt contains an immutable plan snapshot" "$out" 're-check ownership after every parking await'
  assert_nogrep "plan prompt does not depend on reading the live plan path" "$out" 'Read .*fix-plan\.md in full'
  assert_grep "plan prompt forbids opening a separate plan snapshot" "$out" 'Do not open a separate plan snapshot'
  assert_grep "plan snapshot basename is citation-only" "$out" 'fix-plan\.md.*citation label only'
  assert_nogrep "plan snapshot does not expose its denied physical source" "$out" '^Source: `.*fix-plan\.md`'
  out=$(cd "$S" && "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol plan-completeness "relative plan" --plan fix-plan.md)
  assert_nogrep "relative plan paths do not expose their denied physical source" "$out" '^Source: `.*fix-plan\.md`'
  assert_grep "plan snapshot shows source line numbers" "$out" '^[[:space:]]*1[[:space:]]+## C-01'
  assert_grep "plan prompt says nothing is implemented yet" "$out" 'nothing in it is implemented yet'
  assert_grep "plan prompt automatically includes compact context" "$out" 'CONTEXT-SENTINEL-c04'
  assert_nogrep "plan prompt excludes the cumulative findings ledger" "$out" 'FINDINGS-SENTINEL-c04'
  assert_nogrep "plan prompt excludes PR content without --pr" "$out" 'PR-SENTINEL-c04'
  assert_grep "plan-completeness lens text" "$out" 'list every one the plan misses'
  assert_grep "plan prompt keeps the code scope" "$out" 'Base commit: 0000000'
  assert_grep "suggested_fix must state the rule and its siblings" "$out" 'suggested_fix. states the general rule'
  for lens in plan-soundness plan-simplicity plan-tests; do
    out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-terra "$lens" "plan round" --plan "$S/fix-plan.md")
    assert_nogrep "plan lens $lens is known (not echoed verbatim as the whole lens text)" "$out" "^$lens\$"
  done
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-terra plan-simplicity "plan round" --plan "$S/fix-plan.md"); assert_grep "plan-simplicity asks for reuse" "$out" 'existing helper, type, hook, or path'
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol simplicity "code round"); assert_grep "simplicity lens checks the pinned dependency" "$out" 'pinned dependency source'; assert_grep "simplicity lens asks who passes the parameter" "$out" 'list every production caller'
  out=$(REV_SEAT_OFFLINE=1 REV_DEPS_DIR=/tmp/depsview "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol simplicity "blind"); assert_grep "offline paragraph names the deps view" "$out" 'linked under /tmp/depsview'; assert_nogrep "and does not name the registry as a source" "$out" 'the cargo registry, node_modules\)'
  out=$(REV_SEAT_OFFLINE=1 "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol simplicity "blind"); assert_grep "offline paragraph on request" "$out" '## Offline review'; assert_grep "offline forbids whole-registry searches" "$out" 'do not search the whole registry'
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol simplicity "code round"); assert_nogrep "no offline paragraph by default" "$out" '## Offline review'; assert_grep "simplicity lens carries proportionality" "$out" 'Proportionality'; assert_grep "simplicity lens rejects sibling-consistency as justification" "$out" 'Consistency with sibling code is not a justification'
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 opus clean-room "round 1" --pr "$S/pr.md"); assert_grep "clean-room lens says not to read the diff first" "$out" 'Do NOT read the diff first'; assert_grep "PR description section rendered" "$out" '## Change description \(from the author\)'; assert_grep "PR body is included" "$out" 'browser dashboard demo'
  assert_grep "PR sentinel is included only when requested" "$out" 'PR-SENTINEL-c04'
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 opus simplicity "round 1"); assert_nogrep "no PR section without --pr" "$out" 'Change description'; assert_nogrep "PR sentinel is excluded without --pr" "$out" 'PR-SENTINEL-c04'
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol correctness "code round" 2> "$S/normal-code.err"); assert_nogrep "a code prompt has no current immutable plan header" "$out" '## Immutable fix plan snapshot'
  assert_nogrep "normal code prompt stays below its word budget" "$S/normal-code.err" '.'
  assert_grep "code prompt automatically includes compact context" "$out" 'CONTEXT-SENTINEL-c04'
  assert_nogrep "code prompt excludes the cumulative findings ledger" "$out" 'FINDINGS-SENTINEL-c04'
  assert_grep "a code prompt still carries the rule-not-instance requirement" "$out" 'suggested_fix. states the general rule'
  assert_eq "no-roster Codex prompt embeds the JSON schema" "$(grep -c '"[$]schema"' "$out" || true)" 1
  local compatibility_seat
  for compatibility_seat in opus gemini native-seat unknown-seat; do
    out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 "$compatibility_seat" correctness "no-roster compatibility")
    assert_eq "no-roster $compatibility_seat prompt embeds one schema" \
      "$(grep -c '"[$]schema"' "$out" || true)" 1
  done
  printf '%s\n' '{"seats":[{"seat":"codex-sol","adapter":"codex"},{"seat":"codex-terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"},{"seat":"agent-compat","adapter":"agent"},{"seat":"gemini","adapter":"gemini"}]}' > "$S/roster.json"
  local seat
  for seat in codex-sol codex-terra opus sonnet; do
    out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 "$seat" correctness "native schema round")
    assert_eq "$seat native-schema prompt omits the JSON schema" "$(grep -c '"[$]schema"' "$out" || true)" 0
  done
  for seat in agent-compat gemini; do
    out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 "$seat" correctness "inline schema round")
    assert_eq "$seat prompt embeds the JSON schema exactly once" "$(grep -c '"[$]schema"' "$out" || true)" 1
  done
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 opus correctness "agent round")
  assert_grep "reviewer work has a finding bound" "$out" 'no more than five distinct findings'
  assert_grep "reviewer gets the bounded evidence protocol" "$out" '## Bounded evidence protocol'
  assert_grep "bounded protocol covers every assigned hunk" "$out" 'read every byte of the assigned patch'
  assert_nogrep "reviewer is not told work is unlimited" "$out" 'no time or token budget'
  assert_exit "removed --history flag is unknown" 1 "$SCRIPTS/rev-prompt.sh" "$S" 2 codex-sol correctness "resume" --history "$S/context.md"
  python3 - "$S/baseline.md" <<'PY'
import sys
open(sys.argv[1], 'w').write('baseline ' * 2200)
PY
  "$SCRIPTS/rev-prompt.sh" "$S" 2 codex-sol correctness "large code prompt" > "$S/code-path" 2> "$S/code-warn"
  assert_grep "oversized code prompt warns" "$S/code-warn" 'code prompt.*exceeds 1800 words'
  python3 - "$S/fix-plan.md" <<'PY'
import sys
open(sys.argv[1], 'w').write('plan-rule ' * 3200)
PY
  "$SCRIPTS/rev-prompt.sh" "$S" 2 codex-sol plan-tests "large plan prompt" --plan "$S/fix-plan.md" > "$S/plan-path" 2> "$S/plan-warn"
  assert_grep "oversized plan prompt warns" "$S/plan-warn" 'plan prompt.*exceeds 3000 words'
  assert_exit "missing plan file is refused" 1 "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol plan-completeness "x" --plan "$S/no-such-plan.md"
}

# Prompt step 6 names the pinned-dependency root: the environment's REV_DEPS_DIR, else scope.env's.
test_prompt_names_dependency_root() {
  local S="$T/deps-prompt-session"; mkdir -p "$S"
  printf "REV_BASE='0000000'\nREV_BRANCH='feat'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" "$T" > "$S/scope.env"
  printf 'src/a.ts\n' > "$S/files.txt"
  local out
  out=$(env -u REV_DEPS_DIR "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol correctness "no deps")
  assert_grep "step 6 is rendered" "$out" '^6\. Expand to another bounded block'
  assert_nogrep "no dependency root names no directory" "$out" 'Read pinned dependency source only under'
  printf "REV_DEPS_DIR='%s'\n" "$T/cargo home/registry/src" >> "$S/scope.env"
  out=$(env -u REV_DEPS_DIR "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol correctness "scope deps")
  assert_grep "step 6 names the scope.env dependency root" "$out" \
    "^6\. Expand .*Read pinned dependency source only under $T/cargo home/registry/src\.$"
  out=$(REV_DEPS_DIR=/tmp/depsview "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol correctness "env deps")
  assert_grep "the environment's dependency root wins" "$out" \
    '^6\. Expand .*Read pinned dependency source only under /tmp/depsview\.$'
  out=$(env -u REV_DEPS_DIR REV_SEAT_OFFLINE=1 "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol correctness "offline")
  assert_nogrep "a registry root is not described as a lockfile view" "$out" 'one directory per pinned crate'
}
