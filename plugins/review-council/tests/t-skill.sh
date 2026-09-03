# The skill text IS the contract for the orchestrator: nothing but SKILL.md tells it to preserve a
# resumed ledger, to read the roster, to render the extra seats' prompts, to scope the baseline patch,
# or what `--read-only` means over code. Static assertions, so a regression in the prose is caught like
# any other. Also the port guard: every plugin path is ${CLAUDE_PLUGIN_ROOT}-relative and resolves.
#
# The forbidden-string patterns below are written with bracket escapes ('~/[.]claude') on purpose:
# the recursive grep scans this file too, and a literal would match itself.
test_skill_contract() {
  local K="$SK/skills/rev/SKILL.md" ST="$SK/skills/stack/SKILL.md" POL="$SK/skills/rev/POLICY.md" AG="$SK/agents/rev-reviewer.md"
  if [ ! -f "$K" ]; then fail "rev SKILL.md exists" "$K missing"; return; fi
  ok "rev SKILL.md exists"
  if [ ! -f "$ST" ]; then fail "stack SKILL.md exists" "$ST missing"; return; fi
  ok "stack SKILL.md exists"

  # --- names and namespaces -------------------------------------------------
  assert_grep "rev skill is named rev" "$K" '^name: rev$'
  assert_grep "stack skill is named stack" "$ST" '^name: stack$'
  assert_grep "rev skill points at the namespaced agent" "$K" 'subagent_type: "review-council:rev-reviewer"'
  assert_grep "rev skill points at the namespaced stack" "$K" '/review-council:stack'
  assert_grep "rev skill is invoked namespaced" "$K" '/review-council:rev '
  assert_grep "stack legs run the namespaced rev" "$ST" '/review-council:rev'
  assert_grep "stack launch line is the plugin script" "$ST" '\$\{CLAUDE_PLUGIN_ROOT\}/scripts/stack\.sh'

  # --- the port: nothing outside the plugin, everything referenced resolves ---
  local pat hits
  for pat in '~/[.]claude/skills' 'review[-]via[-]cursor' 'rev[-]stack[.]sh'; do
    hits=$(grep -rlE -- "$pat" "$SK" 2>/dev/null | tr '\n' ' ')
    if [ -z "$hits" ]; then ok "no /$pat/ anywhere under the plugin"; else fail "no /$pat/ anywhere under the plugin" "in: $hits"; fi
  done
  assert_nogrep "rev skill has no \$R script shorthand left" "$K" '\$R/'
  assert_nogrep "stack skill has no \$R script shorthand left" "$ST" '\$R/'
  grep -hoE '\$\{CLAUDE_PLUGIN_ROOT\}/[A-Za-z0-9_./-]+' "$K" "$ST" "$AG" | sed 's/[.,:;]*$//' | sort -u > "$T/skill-paths"
  assert_eq "the skills reference plugin paths at all" "$([ -s "$T/skill-paths" ] && echo yes)" "yes"
  local p rel
  while IFS= read -r p; do
    rel=${p#\$\{CLAUDE_PLUGIN_ROOT\}/}
    if [ -e "$SK/$rel" ]; then ok "referenced plugin file exists: $rel"; else fail "referenced plugin file exists: $rel" "$SK/$rel missing"; fi
  done < "$T/skill-paths"

  # --- the agent and its read-only fence ------------------------------------
  if [ ! -f "$AG" ]; then fail "agent file exists" "$AG missing"; return; fi
  ok "agent file exists"
  assert_grep "agent hook is the plugin guard" "$AG" '^          command: \$\{CLAUDE_PLUGIN_ROOT\}/scripts/lib/readonly-bash-guard\.py$'
  assert_eq "the guard the hook names is executable" "$([ -x "$SK/scripts/lib/readonly-bash-guard.py" ] && echo yes)" "yes"
  assert_grep "agent schema reference is plugin-relative" "$AG" '\$\{CLAUDE_PLUGIN_ROOT\}/schema/findings\.schema\.json'

  # --- POLICY.md: what the session-start hook injects ------------------------
  if [ ! -f "$POL" ]; then fail "POLICY.md exists" "$POL missing"; return; fi
  ok "POLICY.md exists"
  local lines; lines=$(awk 'END{print NR}' "$POL")
  if [ "$lines" -le 12 ] && [ "$lines" -gt 0 ]; then ok "POLICY.md is ≤ 12 lines ($lines)"; else fail "POLICY.md is ≤ 12 lines" "got $lines"; fi
  assert_grep "POLICY names the rev command" "$POL" '/review-council:rev'
  assert_grep "POLICY names the stack command" "$POL" '/review-council:stack'
  assert_grep "POLICY says reviewers never write" "$POL" 'never edit|never write'
  assert_grep "POLICY says apply actionable findings" "$POL" 'actionable'
  assert_grep "POLICY says relay the status line" "$POL" 'status line'
  assert_grep "POLICY forbids self-review as a substitute" "$POL" 'substitute'
  assert_grep "POLICY says a degraded panel still runs, loudly" "$POL" 'degraded'

  # --- fan-out reads the roster ---------------------------------------------
  assert_grep "fan-out reads the session roster" "$K" '\$S/roster\.json'
  assert_grep "non-extra seats launch together" "$K" 'every non-extra seat'
  assert_grep "the agent-adapter seat is launched with the Agent tool" "$K" 'adapter is `agent`'
  assert_grep "the agent adapter is not an adapter script" "$K" 'The `agent` adapter is not a script'
  assert_grep "extras join in their own round" "$K" '`round`'
  assert_grep "lens rule is stated as a formula" "$K" 'lenses\[\(i \+ N\) mod L\]'
  assert_grep "worked example for a 3-seat roster" "$K" '\*\*3 seats\*\*'
  assert_grep "worked example for a 4-seat roster" "$K" '\*\*4 seats\*\*'
  assert_grep "worked example for a 6-seat roster" "$K" '\*\*6 seats\*\*'
  assert_grep "three-seat minimum survives the port" "$K" 'three or more'
  # Task 11 — a degraded panel is run, not refused, and every launched agent seat gets its own call
  assert_grep "padded Claude seats are named" "$K" '`claude-1`'
  assert_grep "every agent-adapter seat is its own Agent call" "$K" 'one `Agent` call per seat whose adapter is `agent`'
  assert_grep "padding is explained where the roster is introduced" "$K" 'padded'
  assert_grep "the report opens with the degradation" "$K" 'Degraded panel:'
  assert_grep "coverage quotes the roster sentence verbatim" "$K" '`degradation`'

  # B1 — a resumed leg's ledger must be read, never truncated
  assert_grep "findings.md created only if absent" "$K" '\[ -f \$S/findings\.md \] \|\| printf'
  assert_grep "rejected.md created only if absent" "$K" '\[ -f \$S/rejected\.md \] \|\| : >'
  assert_nogrep "no unconditional ledger truncation" "$K" "^   printf '# Findings ledger"
  assert_grep "says create, never truncate" "$K" 'Create, never truncate'
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
  # inherited loop machinery that other tasks' scripts depend on
  assert_grep "failure table kept" "$K" '\| seat exit 3 \|'
  assert_grep "status tick kept" "$K" 'rev-status\.sh'
  assert_grep "ledger format kept" "$K" '## F-012 · P1 · FIXED'
  assert_grep "report sections kept" "$K" 'Residual risk'
  assert_grep "stack-leg mode kept" "$K" 'REV_STACK_LEG=1'
  # A7 — the stack's verdict and finish semantics
  assert_grep "failed leg blocks its repo's finish" "$ST" 'COMPLETE WITH FAILURES'
  assert_grep "squash and push are independent" "$ST" 'squash refused for <repo>'
}
