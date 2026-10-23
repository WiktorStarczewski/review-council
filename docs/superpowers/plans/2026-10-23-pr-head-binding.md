# Exact PR Head Binding Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Refuse a PR review before provider probes when the checkout does not match the live PR head, and preserve that identity in the session.

**Architecture:** Add an explicit PR-number input to preflight. Resolve the live PR head and base through `gh`, require the checked out branch and commit to match, and use the exact base commit to calculate the merge base. Store the PR identity in immutable `scope.env`; evidence preparation rechecks the pinned local head before it snapshots source.

**Tech Stack:** Bash preflight, Python evidence compiler, shell and Python tests, Review Council release gate.

**Spec:** User request on 2026-10-23 to enforce correct PR checkout after repeated wrong-checkout capacity reports and drive the Council fix to release.

## Global Constraints

- Reject a mismatched PR checkout before any provider probe.
- Keep ordinary branch, path, and uncommitted scope behavior unchanged.
- Preserve initialized session inputs and older sessions without PR metadata.
- Use the previous signed Council release for candidate review; the candidate must not review itself.
- Preserve required CI and signed-release gates.

## Review Focus

- PR head advances between checkout and preflight: reject before roster probe.
- Local branch name points at a stale commit: reject even when its name matches.
- PR base advances or differs from the local base ref: bind the exact API base commit.
- Checkout changes after preflight: reject before preparing another evidence snapshot.
- Non-PR scopes and historical sessions: retain existing behavior.

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

### Task 3: Wire both host workflows and release metadata

**Files:** both `rev/phases/10-setup.md` host copies, manifests, `CHANGELOG.md`, `docs/release.md`, `tasks/todo.md`, `tasks/lessons.md`

- [ ] Pass the requested PR number to preflight and explain its fail-closed identity check.
- [ ] Bump the candidate consistently to 0.7.11 and document the behavior.
- [ ] Record the lesson and release checklist.
- [ ] Verify the change against the repository instructions and release procedure.

### Task 4: Review, certify, and release

- [ ] Run meaningful focused checks and the complete frozen release gate in CI.
- [ ] Review the candidate with signed stable 0.7.10 and fix actionable P0/P1 findings.
- [ ] Open and push the PR, then wait for current-head macOS and Ubuntu CI.
- [ ] Squash-merge, publish the signed 0.7.11 tag and GitHub release, and verify installed versions.
