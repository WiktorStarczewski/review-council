# Exact PR Binding and Exhaustible Replacement Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Refuse a PR review before provider probes when the checkout does not match the live PR head, preserve that identity in the session, and continue a failed assignment through the enforced model chain until it succeeds or the chain ends at Opus.

**Architecture:** Add an explicit PR-number input to preflight. Resolve the live PR head and base through `gh`, require the checked out branch and commit to match, and use the exact base commit to calculate the merge base. Store the PR identity in immutable `scope.env`; evidence preparation rechecks the pinned local head before it snapshots source. Model replacements form a hash-bound parent chain, preserve valid siblings, and advance through Luna, Sonnet, Sol, and Opus, skipping unavailable families and stopping when none remain.

**Tech Stack:** Bash preflight, Python evidence compiler, shell and Python tests, Review Council release gate.

**Spec:** User request on 2026-10-23 to enforce correct PR checkout after repeated wrong-checkout capacity reports and drive the Council fix to release. Additional request: allow repeated per-assignment replacements until the enforced model chain is exhausted, ending at Opus.

## Global Constraints

- Reject a mismatched PR checkout before any provider probe.
- Keep ordinary branch, path, and uncommitted scope behavior unchanged.
- Preserve initialized session inputs and older sessions without PR metadata.
- Allow each failed assignment to continue through distinct higher model families, preserving an auditable lineage and stopping after Opus or earlier exhaustion.
- Review Council changes with one normal internal reviewer; do not use Review Council to review itself.
- Preserve required CI and signed-release gates.

## Review Focus

- PR head advances between checkout and preflight: reject before roster probe.
- Local branch name points at a stale commit: reject even when its name matches.
- PR base advances or differs from the local base ref: bind the exact API base commit.
- Checkout changes after preflight: reject before preparing another evidence snapshot.
- Non-PR scopes and historical sessions: retain existing behavior.
- A failed replacement can be followed by another bound replacement for the same root assignment, without invalidating sibling results.
- Replacements advance through the model chain and cannot skip backward, repeat a family, detach from the root assignment, or continue beyond Opus.
- A panel may replace several failed assignments, while child labels remain unique across all replacement chains.

---

### Task 1: Bind PR-number preflight to live GitHub identity

**Files:** `plugins/review-council/scripts/rev-preflight.sh`, `plugins/review-council/tests/t-preflight.sh`, `plugins/review-council/tests/test-costs.tsv`

- [ ] Add a failing integration test for exact PR head/base binding and stale-head refusal before provider probing.
- [ ] Run the exact test and confirm it fails because `--pr` is unsupported.
- [ ] Implement `--pr <number>`, live metadata validation, exact base selection, and private session fields.
- [ ] Run the exact test and the preflight test group.

### Task 2: Keep the pinned head through evidence preparation

**Files:** `plugins/review-council/scripts/rev-evidence.py`, focused Python evidence tests

- [ ] Add a failing test for a PR-bound session whose checkout head changes after preflight.
- [ ] Run the test and confirm the changed checkout is currently accepted.
- [ ] Validate optional PR metadata and compare local `HEAD` with its pinned SHA before evidence preparation.
- [ ] Run the focused Python test.

### Task 3: Exhaust the replacement chain for each failed assignment

**Files:** `plugins/review-council/scripts/rev-evidence.py`, `plugins/review-council/scripts/lib/workhorse.py`, both host `rev` skill trees, focused evidence/workhorse/skill tests

- [x] Add a failing regression for two sequential replacements of the same assignment, reaching Opus and sealing only the terminal valid result. CI run `40001522036` confirmed `replacement_chain_reaches_opus` fails on both Ubuntu and macOS because advancing `escalation.json` makes the prior child fail validation with `assignment roster mismatch`.
- [ ] Preserve unique labels and parent hashes when separate failed seats each have their own replacement chain.
- [ ] Validate every chain edge against the failed parent, exact source, bundle, and next available family; reject replay, reuse, backward movement, and post-Opus attempts.
- [ ] Update both host workflows to retry the exact failed seat once when eligible, then continue the normal chain after replacement failures until no family remains.
- [ ] Run the exact tests and the focused evidence, workhorse, and skill suites.

### Task 4: Wire both host workflows and release metadata

**Files:** both `rev/phases/10-setup.md` host copies, manifests, `CHANGELOG.md`, `docs/release.md`, `tasks/todo.md`, `tasks/lessons.md`

- [ ] Pass the requested PR number to preflight and explain its fail-closed identity check.
- [ ] Bump the candidate consistently to 0.7.11 and document the behavior.
- [ ] Record the lesson and release checklist.
- [ ] Verify the change against the repository instructions and release procedure.

### Task 5: Review, certify, and release

- [ ] Run meaningful focused checks and the complete frozen release gate in CI.
- [ ] Review the finished candidate with one normal internal reviewer and fix actionable findings.
- [ ] Open and push the PR, then wait for current-head macOS and Ubuntu CI.
- [ ] Squash-merge, publish the signed 0.7.11 tag and GitHub release, and verify installed versions.
