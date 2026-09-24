# Replace failed assignments in place; stop on the review's own code

Status: v6 (implementation spec), 2026-09-24. v1-v5 went through a verification panel and four
read-only panels; the last panel's findings were implementation-level. Scope (user decision): the
core changes plus the redesign of survivors and repairs. Target: 0.5.2, alongside
docs/audit-severity-2026-09-23.md.

## Incident

On 2026-09-23 the wallet C1 review ran 23 rounds and 20 sessions and made 42 review commits.

1. **The session-wide latch.** There were 8 hard audit failures, and each one restarted the session.
   Under 0.5.2 audit severity, 5 of them are valid. The other 3 (r3p, r9, r11) stay fatal.
2. **Churn on the review's own code.** About 30 of the 38 later findings were defects in the
   review's own fixes. The orchestrator graded 9 of them P1. Tests stubbed with jsdom satisfied the
   red-first and mutation checks.

## Part 1 - One replacement per panel, run on another seat

`rev-evidence.py` already supports a replacement generation: `prepare --phase repair
--parent-assignment <label>:<seat>` builds a child bound to one parent assignment, and `receipt` or
`verify-panel` accepts `replacements`. v6 generalises it.

- **The child is keyed by the seat that runs it.** Prepare it with the existing `--assignment
  <executor>=<parent bundle>` together with `--parent-assignment <label>:<failed seat>`. Relax the
  same-seat check (rev-evidence.py around :4527) to require exactly one chosen seat, which is not
  the parent seat and carries the parent's bundle. `validate_manifest` then reads the child's single
  assignment rather than `assigned.get(parent seat)`, and drops the adapter-equality clause.
  `verify_panel_selection` calls `result_generation` with the child's own seat.
  `finding_ownership` and `selected_advisories` build file names from the generation row's `seat`
  and `label`. The prompt, audit, launch and roster lookups need no change, because the executor is
  the child's assignment key.
- **Eligibility, enforced in `prepare`:**
  - the executor differs from the parent seat;
  - the executor is an enforced (non-Agent) seat, since an Agent result cannot be bound against
    copying;
  - the parent assignment has a recorded terminal failure:
    - `r<label>-<seat>.audit-invalid.json`, which covers both invalid audits and auditor-output
      failures;
    - or an `attempts` record showing the seat's one exact retry was exhausted with exit 1 or 2.

  With no eligible executor, the panel is incomplete and the orchestrator asks the user. Exits 3, 4
  and 7 keep today's handling.
- **At most one replacement per panel,** labelled `<N>x`. A second failure in the panel, or a
  failure of the replacement, makes the panel incomplete. The orchestrator then asks the user. No
  new session.
- **This one rule replaces coverage repair.** "An assignment without a valid result gets at most one
  replacement on another eligible seat: after its exact retry for an execution failure, immediately
  for a hard audit failure." That sentence replaces the coverage-repair text (skills/rev/SKILL.md
  :438 and :829-834, and their Codex twins) and drops the three-valid-reviewers precondition.
- **Plans.** Keep the refusal of plan parents in `repair`. A failed plan seat is replaced by an
  ordinary one-seat plan panel under `<N>px`:
  - `phase=plan round=<N>px seats=[<other>]`, then `prepare --phase plan` with the same plan file,
    `--assignment <other>=plan-completeness --full-seat <other>`;
  - it keeps the full schema-4 plan contract;
  - rev-state accepts `<N>px` in the plan-label and round patterns, and the fix gate passes on
    `plan_completed('<N>p') or plan_completed('<N>px')`.

  Under `plan_seats: all`, the replacement covers every cluster with the completeness lens.
- **Discovery** uses the same rule. The child has full scope, so replacing the full-state owner keeps
  full-state coverage.
- **Latch.** `rev-attempt.py` refuses only a relaunch of a `(label, seat)` that has
  `r<label>-<seat>.audit-invalid.json`, or whose `read-audit.json` is a hard failure. Delete the
  session and panel stop markers, `stop`, `check`, `stop_panel_generation` and the session-wide
  glob.
- **Contract.** In both SKILL copies, replace every hard-audit stop clause and the coverage-repair
  clauses with the rule above. That includes skills/rev/SKILL.md :394, :428, :438, :567, :724,
  :829-834 and :999, and codex-skills/rev/SKILL.md :390, :424, :434, :488 and :597, found by search
  rather than by line number. The quota-fallback clause keeps one restriction: an exit-4 quota
  substitution cannot use a replacement child. A later hard audit inside the fallback panel follows
  the new rule.

## Part 2 - Review-origin breaker

- **Scope.** Evidence code rounds, the ones with a sealed `r<N>-coverage.receipt.json`. Numeric,
  stack and legacy-fallback rounds have no manifest and are not counted. That is a documented
  limit.
- **Baseline.** `review_base_tree` is the `snapshot_tree` of the first code round's receipt in the
  session. It is read from that receipt, not copied.
- **Derivation at `phase=fix`.** For round `<N>`, rev-state calls a new read-only subcommand,
  `rev-evidence.py review-origin <S> <N>`. The subcommand:
  - loads the round's receipt;
  - takes the chosen valid result for each assignment, including the replacement;
  - reads each citation (`file`, `line_start`, `line_end`);
  - counts citations that intersect the current-side changed intervals of
    `Repository.changes(review_base_tree, receipt snapshot_tree)`.

  A deletion anchor is clamped to a surviving line (1 at the start of a file, the last line at the
  end). A file emptied or deleted by the review counts any citation of that path. Severity is
  ignored. rev-state stores the count under `review_origin.<N>`.
- **Breaker.** When two rounds have a nonzero count since the last acknowledgement, `phase=fix`
  refuses until `review_origin_ack=<N>` is recorded. The SKILL requires asking the user first and
  recommends reverting the cited review changes and deferring the originating findings. The
  outcome goes in the report. Recording the acknowledgement starts a new window.
- **Quota fallback.** Before switching to the fallback session, run `rev-state.sh <fallback>
  inherit-breaker <parent>`. It copies `review_base_tree`, `review_origin.*` and
  `review_origin_ack`, and refuses when the fallback already has breaker keys.
- **Known limits (documented):**
  - A regression caused by deleted review code but cited only at a distant sink is not counted.
  - Non-evidence rounds are not counted.

## Tests (test-first)

- Replacement:
  - After a hard failure on `(r4, codex-sol)`, `prepare 4x --phase repair --assignment
    codex-terra=<bundle> --parent-assignment 4:codex-sol` builds the child, and the receipt seals.
  - The executor must differ from the parent seat, or prepare refuses.
  - An Agent executor refuses.
  - A seat with no recorded terminal failure refuses.
  - An exhausted exact-retry record allows the replacement.
  - A second replacement in the panel refuses.
  - A failed replacement leaves the panel unsealed.
  - A bundle-scoped parent's child keeps the same bundle.
  - A full-state owner's child keeps full scope.
- Plan: after `(5p, codex-terra)` fails hard, a valid `5px` plan panel on codex-sol lets
  `phase=fix` pass, and its manifest is schema 4 with the same plan hash. Without it, `phase=fix`
  refuses.
- Latch:
  - `(r4, codex-sol)` refuses on an invalid audit, and also on an auditor-output failure (archived
    `audit-invalid.json`).
  - `(r4, codex-terra)`, `(r5, codex-sol)` and `(r6, codex-sol)` are allowed.
  - No marker files exist.
- Contract: none of the removed clause phrases survives in either copy. The new rule is present in
  each copy's hard-audit, coverage-repair and failure-table locations.
- Breaker:
  - Counting is correct for citations inside a changed interval, outside one, on first-line and
    last-line deletions, in a file the review emptied, and on uncommitted changes.
  - Severity has no effect: all-P3 citations count.
  - A replacement result's citations count once.
  - One nonzero round passes.
  - Two nonzero rounds refuse `phase=fix` until acknowledged, then allow it. Two more nonzero rounds
    trip it again.
  - Plan labels and rounds without a receipt are ignored.
  - `inherit-breaker` copies the breaker keys and refuses to overwrite.

## Rejected alternatives

- Survivor-count thresholds, a separate executing-seat field, and a repair-phase plan child. See
  panels 3-5.
- Test-based proof gates, a churn ratio gate, severity exemptions and a 40-line cap. See panels 1-2.
- A session lease and a version gate. Out of scope by the user's decision.
