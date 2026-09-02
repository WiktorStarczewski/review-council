# B1/B2/B3/B9 + A7 — the recipe text IS the contract for the orchestrator: nothing but SKILL.md tells it
# to preserve a resumed ledger, to render the extra seats' prompts, to scope the baseline patch, or what
# `--read-only` means over code. Static assertions, so a regression in the prose is caught like any other.
test_skill_contract() {
  local K="$SK/SKILL.md" ST="$SK/../review-stack/SKILL.md"
  if [ ! -f "$K" ]; then fail "rev SKILL.md exists" "$K missing"; return; fi
  ok "rev SKILL.md exists"
  # B1 — a resumed leg's ledger must be read, never truncated
  assert_grep "findings.md created only if absent" "$K" '\[ -f \$S/findings\.md \] \|\| printf'
  assert_grep "rejected.md created only if absent" "$K" '\[ -f \$S/rejected\.md \] \|\| : >'
  assert_nogrep "no unconditional ledger truncation" "$K" "^   printf '# Findings ledger"
  assert_grep "says create, never truncate" "$K" 'Create, never truncate'
  assert_grep "says the existing ledger is read first" "$K" 'Create, never truncate'
  # B2 — every launched seat has a rendered prompt, and its lens is named
  assert_grep "codex-review prompt rendered" "$K" 'rev-prompt\.sh \$S 2 codex-review +security'
  assert_grep "grok-code-review prompt rendered" "$K" 'rev-prompt\.sh \$S 3 grok-code-review +maintainability'
  assert_grep "round 2 extra seat carries its lens" "$K" '`codex-review` — security'
  assert_grep "round 3 extra seat carries its lens" "$K" '`grok-code-review` — maintainability'
  # B3 — a path scope must not diff the whole branch, and untracked files are in no diff at all
  assert_grep "baseline patch is scoped" "$K" 'git diff \$REV_BASE -- "\$REV_SCOPE"'
  assert_grep "untracked appended to the baseline patch" "$K" 'git diff --no-index /dev/null "\$f" >> \$S/00-baseline\.patch'
  assert_grep "untracked.txt named in setup" "$K" 'untracked\.txt'
  assert_grep "session listing includes untracked.txt" "$K" 'scope\.env  files\.txt  untracked\.txt'
  # B9 — --read-only over code has a documented path of its own
  assert_grep "read-only over code documented" "$K" '\*\*Code with `--read-only`\*\*'
  assert_grep "read-only code still preflights" "$K" 'rev-preflight\.sh --scope <scope> --write \$S'
  assert_grep "read-only code skips fix/verify/commit" "$K" 'no \*\*Fix\*\*, no \*\*Verify\*\*'
  # A7 — the stack's verdict and finish semantics
  if [ ! -f "$ST" ]; then fail "review-stack SKILL.md exists" "$ST missing"; return; fi
  ok "review-stack SKILL.md exists"
  assert_grep "failed leg blocks its repo's finish" "$ST" 'COMPLETE WITH FAILURES'
  assert_grep "squash and push are independent" "$ST" 'squash refused for <repo>'
}
