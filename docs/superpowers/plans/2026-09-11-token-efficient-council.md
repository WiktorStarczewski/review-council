# Token-Efficient Review Council Implementation Plan

> Execution: follow this plan task by task, with a failing test before each behavior change.

**Goal:** Replace the fixed eight-round review loop with the approved adaptive
schedule, compact prompts, and session usage reporting.

**Architecture:** The skills define the adaptive orchestration contract. Shared
prompt generation enforces compact, immutable reviewer inputs, while a separate
read-only profiler measures historical and live session cost. Provider adapters
with native schema options continue to own structured-output details; the renderer
supplies the schema to Agent and Gemini seats.

**Tech Stack:** POSIX shell, Python 3 standard library, Markdown skill contracts.

**Spec:** `docs/superpowers/specs/2026-09-11-token-efficient-council-design.md`

## Global Constraints

- Preserve Sol, Grok, and two Opus seats in the configured panel.
- Preserve the four-seat simplicity pass and maximum reasoning effort.
- Preserve the fix-plan gate for nontrivial accepted findings.
- Do not append the cumulative findings ledger to reviewer prompts.
- Use ASCII hyphens in all changed text.
- Keep reviewer access read-only.

### Task 1: Adaptive schedule contract

**Files:**

- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Modify: `plugins/review-council/tests/t-skill.sh`
- Create: `plugins/review-council/tests/t-efficient.sh`

**Produces:** A normal 12-launch schedule with one final verification panel, a
large or high-risk 16-launch schedule that adds risk discovery, adaptive continuation
rules, and four-bundle completion criteria for every roster size.

- [x] Add static contract tests for both host skills.
- [x] Run the focused tests and confirm they fail on the eight-round contract.
- [x] Replace the fixed schedule in both host skills.
- [x] Run the focused tests and confirm they pass.

### Task 2: Compact prompt generation

**Files:**

- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/scripts/seats.d/gemini.sh`
- Modify: `plugins/review-council/tests/t-plan.sh`
- Modify: `plugins/review-council/tests/t-gemini.sh`

**Produces:** Schema-free native-provider prompts, one rendered Agent/Gemini schema,
automatic compact session context, line-numbered immutable plans, bounded evidence
instructions, and prompt-size warnings.

- [x] Add tests for schema placement, inline plans, word-budget warnings, and
      removal of unlimited-work language.
- [x] Run the focused tests and confirm they fail.
- [x] Update the prompt renderer and Gemini adapter.
- [x] Run the focused tests and confirm they pass.

### Task 3: Session usage profiler

**Files:**

- Create: `plugins/review-council/scripts/rev-profile.py`
- Create: `plugins/review-council/tests/t-profile.sh`
- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`

**Interface:** `rev-profile.py SESSION [SESSION ...]` prints one summary row per
session plus an aggregate. `--json` emits the same fields as JSON.

- [x] Add fixture-driven tests for Claude, Codex, Grok, and Gemini terminal usage,
      unmetered completed seats, schema-invalid failures, and preserved CLI retries.
- [x] Run the focused test and confirm it fails before the script exists.
- [x] Implement terminal-record parsing, schema-valid completion and finding-yield
      classification, receipt-policy compatibility, independent metered attempts,
      and immutable retry streams.
- [x] Run the focused test and confirm it passes.

### Task 4: Exact panel configuration

**Files:**

- Modify: `plugins/review-council/scripts/lib/roster.py`
- Modify: `tests/test_codex.py`
- Modify: `plugins/review-council/tests/t-roster*.sh`
- Modify: `docs/config.md`, `docs/codex.md`

**Produces:** Exact Sol and repeated Opus selection that rejects malformed,
unavailable, or incomplete configured counts before padding, distinguishes permanent
configuration from retryable availability failures, uses unique seat IDs, discloses
padding, probes each model once, and enforces a strict three-lab panel floor.

- [x] Add failing exact-panel and configuration-edge tests.
- [x] Implement selection, validation, unique naming, and probe reuse.
- [x] Confirm the cheap roster is Sol, Grok, Opus, Opus-2.

### Task 5: Historical and delivery validation

**Files:**

- Modify: `tasks/todo.md`
- Modify only if required by validation: files from Tasks 1-3

- [x] Run the full plugin shell suite.
- [x] Run the Codex marketplace check and both skill validators.
- [x] Profile all six preserved sessions and record the baseline.
- [x] Render representative PR #812 prompts and confirm at least 2x reduction.
- [x] Scan changed text for Unicode dash characters and attribution trailers.
- [ ] Commit and push the feature branch.
- [ ] Install the cache-busted personal plugin and verify its loaded files.
- [ ] Run the optimized council over this branch, address actionable findings,
      and re-run validation.
- [ ] Resume PR #812 with the optimized verification panel.
