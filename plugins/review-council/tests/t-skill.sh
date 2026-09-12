# shellcheck shell=bash
# The skill text IS the contract for the orchestrator: nothing but SKILL.md tells it to preserve a
# resumed ledger, to read the roster, to render the extra seats' prompts, to scope the baseline patch,
# or what `--read-only` means over code. Static assertions, so a regression in the prose is caught like
# any other. Also the port guard: every plugin path is ${CLAUDE_PLUGIN_ROOT}-relative and resolves.
#
# The forbidden-string patterns below are written with bracket escapes ('~/[.]claude') on purpose:
# the recursive grep scans this file too, and a literal would match itself.
test_skill_contract() {
  local K="$SK/skills/rev/SKILL.md" ST="$SK/skills/stack/SKILL.md" POL="$SK/skills/rev/POLICY.md" AG="$SK/agents/rev-reviewer.md"
  local CK="$SK/codex-skills/rev/SKILL.md" CST="$SK/codex-skills/stack/SKILL.md"
  if [ ! -f "$K" ]; then fail "rev SKILL.md exists" "$K missing"; return; fi
  ok "rev SKILL.md exists"
  if [ ! -f "$ST" ]; then fail "stack SKILL.md exists" "$ST missing"; return; fi
  ok "stack SKILL.md exists"
  if [ ! -f "$CK" ]; then fail "Codex rev SKILL.md exists" "$CK missing"; return; fi
  ok "Codex rev SKILL.md exists"
  if [ ! -f "$CST" ]; then fail "Codex stack SKILL.md exists" "$CST missing"; return; fi
  ok "Codex stack SKILL.md exists"

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
  # This is a regular expression for a literal tilde, not a shell path.
  # shellcheck disable=SC2088
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

  # --- the fix-plan gate (0.2.0) ---------------------------------------------
  assert_grep "loop header has the plan step" "$K" 'triage → plan → fix'
  assert_grep "Plan section exists" "$K" '^### Plan'
  assert_grep "plan is written to fix-plan.md" "$K" '\$S/fix-plan\.md'
  assert_grep "plan prompts render with immutable plan evidence" "$K" \
    '--plan "\$PLAN_SNAPSHOT" --evidence "\$MANIFEST"'
  assert_grep "plan prompts use a distinct artifact label" "$K" 'PANEL_LABEL=<N>p'
  assert_grep "the four plan lenses are named" "$K" 'plan-completeness, plan-soundness,'
  assert_grep "triage clusters by root cause" "$K" '\*\*Cluster\.\*\*'
  assert_grep "fix lands one cluster per commit" "$K" 'one\s*cluster per commit'
  assert_grep "evidence doc is referenced" "$K" 'churn-analysis-2026-09-06\.md'
  assert_grep "rev skill documents --base" "$K" '--base <ref>'
  assert_grep "simplicity discovery uses every seat" "$K" '\| Simplicity discovery \|.*\| simplicity for every seat \|'
  assert_grep "PR description is not passed to seats by default" "$K" 'do \*\*not\*\* pass `--pr \$S/pr\.md`'

  # --- the agent and its read-only fence ------------------------------------
  if [ ! -f "$AG" ]; then fail "agent file exists" "$AG missing"; return; fi
  ok "agent file exists"
  assert_nogrep "agent does not advertise ignored hook frontmatter" "$AG" '^hooks:'
  assert_eq "the CLI guard remains executable" "$([ -x "$SK/scripts/lib/readonly-bash-guard.py" ] && echo yes)" "yes"
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
  # Task 11 - a degraded panel is run, not refused, and every launched agent seat gets its own call
  assert_grep "padded Claude seats are named" "$K" '`claude-1`'
  assert_grep "every agent-adapter seat is its own Agent call" "$K" 'one `Agent` call per seat whose adapter is `agent`'
  assert_grep "every Agent transcript is recorded by seat" "$K" 'agent_transcripts\.<seat>='
  assert_grep "CLI seats keep log-based status" "$K" 'CLI seats use their own logs'
  assert_grep "padding is explained where the roster is introduced" "$K" 'padded'
  assert_grep "the report opens with the degradation" "$K" 'Degraded panel:'
  assert_grep "coverage quotes the roster sentence verbatim" "$K" '`degradation`'

  # C-13 and C-14: both hosts keep panel state exact and numeric mode compatible.
  local H
  for H in "$K" "$CK"; do
    assert_grep "host writes exact code-panel state" "$H" 'phase=fan-out round=<N> "seats=\$LAUNCHED_SEATS"'
    assert_grep "host writes exact repair state" "$H" 'phase=repair round=<N>x "seats=\$REPAIR_SEATS"'
    assert_grep "host writes exact plan state" "$H" 'phase=plan round=<N>p "seats=\$PLAN_SEATS"'
    assert_grep "host counts only numbered code panels" "$H" 'Plan panels do not count as numbered code panels'
    assert_grep "host preserves numeric continuation" "$H" 'Only numeric mode continues past its requested minimum'
    assert_grep "host distinguishes retryable roster status" "$H" 'Exit 5 is retryable'
    assert_grep "host distinguishes permanent roster status" "$H" 'Exit 6 is permanent'
    assert_grep "direct document roster requests its brief cause" "$H" \
      'roster\.sh --probe --brief --write .*roster\.json'
    assert_grep "host prepares evidence before adaptive fan-out" "$H" \
      'rev-evidence\.py"? prepare .* --phase "\$PANEL_PHASE"'
    assert_eq "host canonicalizes the session once for macOS tmp aliases" \
      "$(grep -Ec '^[[:space:]]*S=\$\(cd "\$S" && pwd -P\)$' "$H" || true)" 1
    assert_grep "host names the macOS tmp alias pair" "$H" \
      'macOS `/tmp` and `/private/tmp`'
    assert_grep "host prepares against the canonical session" "$H" \
      'rev-evidence\.py"? prepare "\$S"'
    assert_grep "host compares the canonical manifest identity" "$H" \
      '"\$S/r\$PANEL_LABEL-evidence\.manifest\.json"'
    assert_grep "host invokes the non-executable evidence script with Python" "$H" \
      'python3 .*rev-evidence\.py"? prepare'
    assert_grep "host builds one conditional evidence flag" "$H" \
      'EVIDENCE_PROMPT_ARGS=\(--evidence "\$MANIFEST"\)'
    assert_grep "host passes the conditional evidence flag to every prompt" "$H" \
      'rev-prompt\.sh.*"\$\{EVIDENCE_PROMPT_ARGS\[@\]\}"'
    assert_grep "host renders every adaptive prompt before launching" "$H" \
      '[Rr]ender every seat before any reviewer process starts'
    assert_grep "fan-out launches the already-rendered prompts" "$H" \
      '[Ff]an-out launches only those already-rendered prompt files'
    assert_grep "host certifies evidence after collection" "$H" \
      'rev-evidence\.py"? receipt .* "\$PANEL_LABEL"'
    assert_grep "host certifies a completed discovery panel" "$H" \
      '[Cc]ertify discovery after its complete simplicity panel'
    assert_grep "host uses the first core seat as discovery owner" "$H" \
      '[Ff]irst core seat.*discovery.*full-state'
    assert_grep "host uses the regression bundle owner as integration seat" "$H" \
      'tests-observability-maintenance-regression.*full-state'
    assert_grep "valid narrowed panels keep one integration seat" "$H" \
      '[Vv]alid narrowed panel.*exactly one full-state seat'
    assert_grep "host gives repairs full cumulative scope" "$H" \
      '[Rr]epair.*full cumulative patch'
    assert_grep "host rerenders every prompt on evidence failure" "$H" \
      '[Rr]ender every seat again without `--evidence`'
    assert_grep "host does not narrow after receipt failure" "$H" \
      '[Rr]eceipt.*fails.*next adaptive panel.*full cumulative'
    assert_grep "host preserves the exact configured roster" "$H" \
      '[Ss]cope optimization never changes.*roster'
    assert_grep "host preserves all four bundles" "$H" \
      '[Aa]ll four risk bundles at least once'
    assert_grep "host assigns bundles in stable roster order" "$H" \
      'core seat `i` receives bundle `BUNDLES\[i mod 4\]`'
    assert_grep "three-seat panels combine the missing bundle deterministically" "$H" \
      '[Tt]hree core seats.*fourth bundle.*first seat'
    assert_grep "surplus seats repeat bundles deterministically" "$H" \
      '[Ff]ive or more core seats.*cycle through `BUNDLES` again'
    assert_grep "the exact four-seat assignment is unchanged" "$H" \
      '[Ww]ith four core seats.*one canonical bundle per seat'
    assert_grep "composite bundles use one canonical assignment" "$H" \
      'join.*bundle names with `\+`'
    assert_grep "evidence owns component assignment" "$H" \
      '`rev-evidence\.py` owns semantic component assignment'
    assert_grep "components retain specialist and integration coverage" "$H" \
      '[Ee]very semantic component.*specialist.*full-state'
    assert_grep "later fixes return to prior finding owners" "$H" \
      '[Pp]rior finding.*returns to that finding owner'
    assert_grep "integration-owned findings still get a specialist" "$H" \
      '[Ii]ntegration.*least-loaded specialist'
    assert_grep "invalid owner data restores normal routing" "$H" \
      '[Mm]issing or invalid ownership data.*normal component routing'
    assert_grep "unprovable component coverage widens fully" "$H" \
      '[Cc]omponent coverage cannot be proved.*full cumulative patch'
    assert_grep "host treats source-context bytes as original source" "$H" \
      'literal source bytes with original'
    assert_grep "host bounds specialist packet shards" "$H" \
      '[Ss]pecialist receives.*one 32 KiB shard'
    assert_grep "host bounds integration packet shards" "$H" \
      'integration seat receives at most three'
    assert_grep "host carries the paired source-context switch through prepare" "$H" \
      'REV_SOURCE_CONTEXT=\$\{REV_SOURCE_CONTEXT:-0\} python3'
    assert_grep "host carries the patch chunk switch through prepare" "$H" \
      'REV_PATCH_CHUNKS=\$\{REV_PATCH_CHUNKS:-0\} REV_SOURCE_CONTEXT='
    assert_grep "host keeps the monolithic patch as chunk identity" "$H" \
      'SHA-256 remain the identity'
    assert_grep "host shares identical patch sets" "$H" \
      '[Ii]dentical assigned patch bodies share one patch set'
    assert_grep "host records conservative chunk limits" "$H" \
      '24 KiB raw, 30 KiB.*eight prefix bytes'
    assert_grep "host preserves the ordinary output authority" "$H" \
      '32 KiB per-tool and ordinary per-turn output limits still apply'
    assert_grep "host bounds provider patch batches" "$H" \
      'Grok and Claude adapters may read two consecutive chunks in one turn.*60 KiB'
    assert_grep "host orders chunk reads before source packets" "$H" \
      'full, before source-context packets or source expansion'
    assert_grep "host denies chunk source citation credit" "$H" \
      'discovery only; they never establish source citation evidence'
    assert_grep "host documents the ten percent chunk gate" "$H" \
      '^10 percent against 240-line windows'
    assert_grep "host documents safe legacy chunk fallback" "$H" \
      'chunk set, or `REV_PATCH_CHUNKS=0` keeps window mode'
    assert_grep "host rejects incomplete chunk receipts" "$H" \
      '[Mm]issing, reordered, truncated, replaced,'
    assert_grep "host rejects redirected chunk receipts" "$H" \
      'duplicate, unassigned, redirected, or oversized chunks'
    assert_grep "host preserves component narrowing in paired baseline" "$H" \
      'same component assignments and patch narrowing'
    assert_grep "host checks narrow read audits before triage" "$H" \
      '[Bb]efore triage or receipt.*read-audit'
    assert_grep "every evidence seat requires a schema 2 read audit" "$H" \
      '[Ee]very evidence-launched seat.*schema 2'
    assert_grep "a narrow audit failure retries the whole panel fully" "$H" \
      '[Rr]erender and relaunch every seat.*full cumulative patch'
    assert_grep "audit fallback uses a fresh artifact label" "$H" \
      'fresh fallback label `<N>f`'
    assert_grep "host never mixes narrow and fallback results" "$H" \
      '[Nn]ever mix narrow and full results'
    assert_grep "host requires citation range coverage" "$H" \
      '[Ee]very finding citation must intersect'
    assert_grep "host fallback removes source-context packets" "$H" \
      'full cumulative patch and no source-context packet'
    assert_grep "host excludes unenforced Agent seats from evidence mode" "$H" \
      'adapter `agent`.*skip evidence preparation|skip evidence preparation.*adapter `agent`'
    assert_grep "numeric panels bypass evidence narrowing" "$H" \
      '[Ee]xplicit numeric.*full cumulative patch'
    assert_grep "document panels retain full reads" "$H" \
      '[Dd]ocument.*read every supplied document in full'
    assert_grep "plan preparation hash-binds the source plan" "$H" \
      '--phase plan --plan .*--plan-sha256'
    assert_grep "plan completeness owns full-state coverage" "$H" \
      'plan-completeness seat receives'
    assert_grep "surplus plan seats never duplicate completeness" "$H" \
      'keep `plan-completeness` unique'
    assert_grep "plan specialists share one closure" "$H" \
      'same plan-site and.*local-import.*closure'
    assert_grep "plan specialists may receive three source shards" "$H" \
      'up to three'
    assert_grep "plan clusters require repository-wide sibling searches" "$H" \
      'repository-wide sibling-site'
    assert_grep "plan cluster grep searches require recursive mode" "$H" \
      'grep.*requires `-r`, `-R`, or `--recursive`'
    assert_grep "plan clusters support source ranges" "$H" \
      'path:start-end'
    assert_grep "plan panels use non-persisting verification" "$H" \
      'rev-evidence\.py"? verify-panel "\$S" "\$PANEL_LABEL"'
    assert_grep "plan validation never advances code coverage" "$H" \
      'never writes a receipt or advances `coverage-head\.json`'
    assert_grep "plan evidence failure reruns every seat freshly" "$H" \
      'rerun all plan seats|rerun every plan seat under fresh'
    assert_grep "Agent plan panels retain legacy full scope" "$H" \
      'Agent-seat plan'
  done
  assert_nogrep "Claude Agent output transcript is not treated as enforced evidence" "$K" \
    'audit every Agent `output_file` as adapter `agent`'
  assert_grep "Claude Agent transcript is retained for profiling" "$K" \
    'copy `<output_file>` to `\$S/r<N>-<seat>\.stream\.ndjson`'
  assert_grep "Claude skill records why Agent evidence is disabled" "$K" \
    'plugin subagents ignore hook frontmatter'
  assert_grep "Claude host has one fan-out section" "$K" '^### Fan out$'
  assert_grep "Codex host has one fan-out section" "$CK" '^### Fan out$'
  awk '/^### Fan out$/{copy=1} /^### Collect$/{if(copy) exit} copy' "$K" > "$T/claude-fan-out"
  awk '/^### Fan out$/{copy=1} /^## Triage/{if(copy) exit} copy' "$CK" > "$T/codex-fan-out"
  assert_nogrep "Claude fan-out cannot overwrite adaptive prompts" "$T/claude-fan-out" \
    'rev-prompt\.sh.*\$S <N>'
  assert_nogrep "Codex fan-out cannot overwrite adaptive prompts" "$T/codex-fan-out" \
    'rev-prompt\.sh.*"\$S" "\$ROUND"'
  assert_grep "Claude schedule keeps state in round 5" "$K" '^\| 5 \| API & contract, compatibility \| api-contract, data-state, readability \| - \|$'
  assert_grep "Codex schedule keeps maintenance in round 5" "$CK" '^\| 5 \| Contracts and compatibility \| api-contract, readability, maintainability \| - \|$'
  for H in "$ST" "$CST"; do
    assert_grep "stack preserves numeric continuation" "$H" 'Numeric legs may continue past the requested minimum'
    assert_grep "stack excludes plan panels from numeric count" "$H" '[Pp]lan panels do not count'
    assert_grep "stack distinguishes retryable roster status" "$H" 'Exit 5 is retryable'
    assert_grep "stack distinguishes permanent roster status" "$H" 'Exit 6 is permanent'
  done

  # B1 - a resumed leg's ledger must be read, never truncated
  assert_grep "findings.md created only if absent" "$K" '\[ -f \$S/findings\.md \] \|\| printf'
  assert_grep "rejected.md created only if absent" "$K" '\[ -f \$S/rejected\.md \] \|\| : >'
  assert_nogrep "no unconditional ledger truncation" "$K" "^   printf '# Findings ledger"
  assert_grep "says create, never truncate" "$K" 'Create, never truncate'
  # B2 - every launched seat has a rendered prompt, and its lens is named
  assert_grep "numeric extras join the single render pass" "$K" \
    'add them.*`LAUNCHED_SEATS` before the single render pass'
  assert_grep "numeric extras keep fixed lenses" "$K" \
    'fixed `security` and'
  # B3 - a path scope must not diff the whole branch, and untracked files are in no diff at all
  assert_grep "baseline patch is scoped" "$K" 'git diff \$REV_BASE -- "\$REV_SCOPE"'
  assert_grep "untracked appended to the baseline patch" "$K" 'git diff --no-index /dev/null "\$f" >> \$S/00-baseline\.patch'
  assert_grep "untracked.txt named in setup" "$K" 'untracked\.txt'
  assert_grep "session listing includes untracked.txt" "$K" 'scope\.env  files\.txt  untracked\.txt'
  # B9 - --read-only over code has a documented path of its own
  assert_grep "read-only over code documented" "$K" '\*\*Code with `--read-only`\*\*'
  assert_grep "read-only code still preflights" "$K" 'rev-preflight\.sh --scope <scope> --write \$S'
  assert_grep "read-only code skips fix/verify/commit" "$K" 'no \*\*Fix\*\*, no \*\*Verify\*\*'
  # inherited loop machinery that other tasks' scripts depend on
  assert_grep "failure table kept" "$K" '\| seat exit 3 \|'
  assert_grep "status tick kept" "$K" 'rev-status\.sh'
  assert_grep "ledger format kept" "$K" '## F-012 · P1 · FIXED'
  assert_grep "report sections kept" "$K" 'Residual risk'
  assert_grep "stack-leg mode kept" "$K" 'REV_STACK_LEG=1'
  # A7 - the stack's verdict and finish semantics
  assert_grep "failed leg blocks its repo's finish" "$ST" 'COMPLETE WITH FAILURES'
  assert_grep "squash and push are independent" "$ST" 'squash refused for <repo>'
}
