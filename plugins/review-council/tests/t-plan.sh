# The fix-plan gate: rev-prompt.sh --plan renders a plan-review prompt (plan section, plan lenses, rule-not-instance
# suggested_fix requirement) on top of the normal code scope, and refuses a missing plan.
test_plan_prompt() {
  local S="$T/plan-session"; mkdir -p "$S"
  printf "REV_BASE='0000000'\nREV_BRANCH='feat'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" "$T" > "$S/scope.env"
  printf 'src/a.ts\n' > "$S/files.txt"
  printf '## C-01 · re-check ownership after every parking await\nRule: every call after an await re-checks the hold.\nSites: src/a.ts:10\nTest: a.test.ts\n' > "$S/fix-plan.md"
  local out
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol plan-completeness "plan round" --plan "$S/fix-plan.md") || { fail "plan prompt renders"; return; }
  ok "plan prompt renders"
  assert_grep "plan prompt names the plan file" "$out" "Read $S/fix-plan.md in full"
  assert_grep "plan prompt says nothing is implemented yet" "$out" 'nothing in it is implemented yet'
  assert_grep "plan-completeness lens text" "$out" 'list every one the plan misses'
  assert_grep "plan prompt keeps the code scope" "$out" 'Base commit: 0000000'
  assert_grep "suggested_fix must state the rule and its siblings" "$out" 'suggested_fix. states the general rule'
  for lens in plan-soundness plan-simplicity plan-tests; do
    out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 grok "$lens" "plan round" --plan "$S/fix-plan.md")
    assert_nogrep "plan lens $lens is known (not echoed verbatim as the whole lens text)" "$out" "^$lens\$"
  done
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 grok plan-simplicity "plan round" --plan "$S/fix-plan.md"); assert_grep "plan-simplicity asks for reuse" "$out" 'existing helper, type, hook, or path'
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol simplicity "code round"); assert_grep "simplicity lens checks the pinned dependency" "$out" 'pinned dependency source'; assert_grep "simplicity lens asks who passes the parameter" "$out" 'list every production caller'
  out=$("$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol correctness "code round"); assert_nogrep "a code prompt has no plan section" "$out" 'Fix plan under review'
  assert_grep "a code prompt still carries the rule-not-instance requirement" "$out" 'suggested_fix. states the general rule'
  assert_exit "missing plan file is refused" 1 "$SCRIPTS/rev-prompt.sh" "$S" 1 codex-sol plan-completeness "x" --plan "$S/no-such-plan.md"
}
