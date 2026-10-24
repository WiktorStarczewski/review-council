# Exact PR Binding and Exhaustible Replacement Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Refuse a PR review before provider probes when the checkout does not match the live PR head, preserve that identity in the session, and continue a failed assignment through the enforced model chain until it succeeds or the chain ends at Opus.

**Architecture:** Add an explicit PR-number input to preflight. Resolve the live repository, PR number, head, and base through `gh`, require the checked out branch and commit to match, and use the exact base commit to calculate the merge base. Store the PR identity in immutable `scope.env`; rendering resolves that exact PR, and evidence preparation rechecks both local checkout and live PR state before it snapshots source. Model replacements form a hash-bound parent chain, preserve valid siblings, and advance through Luna, Sonnet, Sol, and Opus, skipping unavailable families and stopping when none remain.

**PR binding details:** Ignore ambient `GH_REPO` while discovering contextual PR identity. Pass and validate both `--pr` and `--pr-repo` in quota fallback sessions, then re-query the same live PR during evidence preparation and before publication.

**Tech Stack:** Bash preflight, Python evidence compiler, shell and Python tests, one-seat normal internal review, GitHub CI release gate.

**Spec:** User request on 2026-10-23 to enforce correct PR checkout after repeated wrong-checkout capacity reports and drive the Council fix to release. Additional request: allow repeated per-assignment replacements until the enforced model chain is exhausted, ending at Opus.

The candidate is based on the verified latest stable release, `review-council--v0.7.11`, and targets release 0.8.0.

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
- Checkout or live PR changes after preflight: reject before creating a PR target or preparing another evidence snapshot.
- Non-PR scopes and historical sessions: retain existing behavior.
- A failed replacement can be followed by another bound replacement for the same root assignment, without invalidating sibling results.
- Replacements advance through the model chain and cannot skip backward, repeat a family, detach from the root assignment, or continue beyond Opus.
- A panel may replace several failed assignments, while child labels remain unique across all replacement chains.

---

### Task 1: Bind PR-number preflight to live GitHub identity

**Files:** `plugins/review-council/scripts/rev-preflight.sh`, `plugins/review-council/tests/t-preflight.sh`, `plugins/review-council/tests/test-costs.tsv`

- [x] Add integration tests for exact PR head/base binding, stale-head refusal before provider probing, repository override isolation, and explicit repository pinning.
- [x] Confirm the pre-fix behavior accepted a mismatched PR head in CI run `40010322339`.
- [x] Implement `--pr <number>`, optional `--pr-repo`, live metadata validation, exact base selection, and private session fields.
- [ ] Confirm the new repository-binding regressions fail on the tests-only CI head and pass on the final candidate.

### Task 2: Keep the pinned head through evidence preparation

**Files:** `plugins/review-council/scripts/rev-evidence.py`, focused Python evidence tests

- [x] Add regressions for checkout drift and live PR metadata drift during evidence preparation.
- [x] Confirm the pre-fix behavior accepted a mismatched PR source in CI run `40010322339`.
- [x] Validate the pinned repository, local checkout, and live PR identity before preparing an evidence snapshot.
- [ ] Pass the evidence regressions in the final candidate CI run.

### Task 3: Exhaust the replacement chain for each failed assignment

**Files:** `plugins/review-council/scripts/rev-evidence.py`, `plugins/review-council/scripts/lib/workhorse.py`, both host `rev` skill trees, focused evidence/workhorse/skill tests

- [x] Add a regression for two sequential replacements of the same assignment, reaching Opus and sealing only the terminal valid result. CI run `40001522036` proved the prior parent-chain validation rejected this flow on both platforms.
- [x] Preserve unique labels and parent hashes when separate failed seats each have their own replacement chain.
- [x] Validate each chain edge against the failed parent, exact source, bundle, and next available family; reject replay, reuse, backward movement, and post-Opus attempts.
- [x] Update both host workflows to continue failed assignments through the normal chain until no family remains.
- [ ] Pass evidence, workhorse, and skill regressions in the final candidate CI run.

### Task 4: Wire both host workflows and release metadata

**Files:** both `rev/phases/10-setup.md` host copies, manifests, `CHANGELOG.md`, `docs/release.md`, `tasks/todo.md`, `tasks/lessons.md`

- [x] Pass the requested PR number to preflight and explain its fail-closed identity check.
- [x] Bump the candidate consistently to 0.8.0 and document the behavior.
- [x] Record the lesson and release checklist.
- [x] Verify the change against repository instructions and the signed-release procedure.

### Task 5: Review, certify, and release

- [ ] Pass the focused regressions and complete frozen release gate in CI.
- [x] Review the finished code with one normal internal reviewer and close all P0-P2 findings.
- [x] Open the PR and push the tests-only regression commit.
- [ ] Push the implementation and wait for current-head macOS, Ubuntu, and Cursor package CI.
- [ ] Squash-merge, publish the signed 0.8.0 tag and GitHub release, and verify installed versions.
