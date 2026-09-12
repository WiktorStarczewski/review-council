# Evidence-Efficient Review Council Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic scope snapshots, delta verification, mechanical routing, evidence indexes, and bounded source reads before measuring PR #812.

**Architecture:** One standard-library Python state machine captures worktree trees in a session-local Git object store, prepares per-panel views, and advances coverage only through validated receipts. The prompt renderer consumes a hashed manifest; both host skills orchestrate preparation and certification while preserving full-scope fallbacks.

**Tech Stack:** Python 3 standard library, Bash 3.2-compatible scripts, Git plumbing, JSON and Markdown artifacts.

**Spec:** `docs/superpowers/specs/2026-09-12-evidence-efficient-council-design.md`

## Global Constraints

- Preserve the exact Sol, Grok, Opus, and Opus-2 configured panel and all four risk bundles.
- Keep one full-state integration seat in every adaptive verification panel.
- Never touch the repository index, refs, or object database when capturing a worktree.
- Fall back to full scope on missing, stale, malformed, incomplete, or unsafe evidence.
- Keep explicit numeric schedules and document review behavior unchanged.
- Use no external dependencies and add no U+2013 or U+2014 characters.

---

### Task 1: Executable scope and receipt contracts

**Files:**
- Create: `plugins/review-council/tests/t-evidence.sh`
- Modify: `plugins/review-council/tests/t-prompt-inputs.sh`
- Modify: `plugins/review-council/tests/t-efficient.sh`
- Modify: `plugins/review-council/tests/t-skill.sh`
- Modify: `plugins/review-council/tests/t-plan.sh`

**Interfaces:**
- Consumes: the command and artifact contract in the spec.
- Produces: failing tests for snapshot isolation, hunk hashing, routing, packets, freshness, receipts, and host orchestration.

- [ ] Add a synthetic Git repository with semantic, lockfile, generated, snapshot, locale, binary, symlink, deleted, and untracked changes.
- [ ] Assert discovery owner and non-owner patch routing and conservative classifier negatives.
- [ ] Assert one changed hunk becomes delta while an unchanged hunk retains its hash.
- [ ] Assert no-fix, unsafe, missing-receipt, stale, and delta-larger states select full scope.
- [ ] Assert caller, test, and gate facts and deterministic byte-identical rerenders.
- [ ] Assert receipt rejection for failed or invalid results, prompt hash mismatch, and post-prepare mutation.
- [ ] Assert both host skills preserve exact seats, bundles, full-state coverage, repair, and fallback.
- [ ] Run the focused tests and confirm they fail for the missing implementation.

### Task 2: Deterministic evidence state machine

**Files:**
- Create: `plugins/review-council/scripts/rev-evidence.py`

**Interfaces:**
- Consumes: `scope.env`, `roster.json`, repository state, prior coverage receipts, and result artifacts.
- Produces: `prepare`, `render`, and `receipt` commands plus the artifacts named in the spec.

- [ ] Implement safe scope parsing and a session-local Git object and temporary index environment.
- [ ] Implement raw worktree overlay hashing without Git filters and immutable tree capture.
- [ ] Batch raw snapshot hashing, write only changed and untracked blobs, and keep evidence lookup near linear in repository text size.
- [ ] Implement pinned cumulative and predecessor-to-current diffs and canonical hunk or opaque-atom hashes.
- [ ] Implement conservative mechanical classification and semantic patch generation.
- [ ] Implement lexical symbol, call-site, related-test, and gate extraction with explicit limitations.
- [ ] Implement assignment selection, delta-size fallback, deterministic JSON and compact Markdown output.
- [ ] Implement manifest hash and freshness validation for `render`.
- [ ] Implement result, prompt, bundle, full-state, and snapshot validation for `receipt`.
- [ ] Publish every artifact atomically and leave the prior coverage head intact on failure.
- [ ] Run `t-evidence.sh` until it passes.

### Task 3: Prompt and reviewer integration

**Files:**
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/agents/rev-reviewer.md`
- Modify: `eval/bench-case.sh`

**Interfaces:**
- Consumes: `rev-evidence.py render MANIFEST SEAT` through `--evidence MANIFEST`.
- Produces: transactional prompts with assigned scope and the bounded evidence protocol.

- [ ] Add `--evidence` parsing, file validation, and transactional fragment rendering.
- [ ] Replace the broad reviewer opening with the bounded evidence recipe for code and plan prompts.
- [ ] Preserve the clean-room ordering exception and full document reads.
- [ ] Make the Agent fallback reinforce the renderer rather than request broad surrounding-code reads.
- [ ] Remove unlimited-work wording from the benchmark Agent launcher.
- [ ] Run prompt, reviewer, and evaluation focused tests until they pass.

### Task 4: Host orchestration and profiling

**Files:**
- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Modify: `plugins/review-council/scripts/rev-profile.py`
- Modify: `plugins/review-council/tests/t-profile.sh`

**Interfaces:**
- Consumes: evidence prepare and receipt commands and manifest word counts.
- Produces: identical adaptive scope rules on both hosts and separate measured and projected usage reporting.

- [ ] Add prepare-before-fan-out and receipt-after-collection steps to both skills.
- [ ] Define first-seat discovery ownership, regression-bundle full ownership, full repair scope, and fail-safe fallback.
- [ ] Keep numeric and document flows on full scope.
- [ ] Extend the profiler with full, assigned, delta, evidence, and avoided word counts without changing provider totals.
- [ ] Run host contract and profiler tests until they pass.

### Task 5: Documentation and regression evaluation

**Files:**
- Modify: `README.md`
- Modify: `docs/codex.md`
- Modify: `CHANGELOG.md`
- Modify: `tasks/todo.md`

**Interfaces:**
- Consumes: final command and artifact behavior.
- Produces: concise user documentation and measured development-regression evidence.

- [ ] Document scope preparation, conservative routing, receipts, fallbacks, and profiler fields.
- [ ] Replay preserved sessions and existing benchmark fixtures as development regression data.
- [ ] Record patch and evidence word savings separately from actual provider usage.
- [ ] Run the full shell and Python suites, validators, syntax checks, diff checks, and attribution and Unicode scans.
- [ ] Update the task review with exact results and limitations.

### Task 6: Final review and PR #812 measurement

**Files:**
- Modify as required by accepted council findings.

**Interfaces:**
- Consumes: installed cache-busted plugin build and the existing optimizer and PR #812 review sessions.
- Produces: a clean optimizer council result and the first same-PR measured reduction.

- [ ] Install and hash-verify the source, staged, and cache-busted plugin copies.
- [ ] Run the exact four-seat final optimizer verification panel with evidence scope and status reporting.
- [ ] Fix every verified finding, rerun gates, and repeat verification when required.
- [ ] Commit, sign, and push the optimizer without attribution or history rewriting.
- [ ] Attempt to seed PR #812 coverage only if its preserved prompts and base satisfy the new receipt contract; otherwise record the required full fallback.
- [ ] Run the optimized exact four-seat verification and profile actual provider usage.
- [ ] Complete local wallet gates, push the PR branch, babysit CI to green, and admin squash merge.

### Task 7: Final-panel correctness repairs

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/scripts/rev-profile.py`
- Modify: `plugins/review-council/scripts/stack.sh`
- Modify: evidence, profile, install, stack, prompt, and host contract tests

- [ ] Add failing path-scope fixtures with sibling tracked and untracked changes.
- [ ] Add sparse, gitlink, and unsupported special-file snapshot fixtures.
- [ ] Add 3-seat and 5-seat four-bundle receipt fixtures while keeping repair panels non-certifying.
- [ ] Add stale report fixtures for later passes and retries on both stack host paths.
- [ ] Add changed-file-count scale and bounded-memory regression fixtures.
- [ ] Add distinct fallback diagnostics and offline preserved-session profiling fixtures.
- [ ] Make every shebang script executable and test the invariant.
- [ ] Implement the smallest coherent fixes and rerun focused tests.

### Task 8: Semantic component and finding-owner routing

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: both `rev` host skills and their contract tests

- [ ] Add failing disconnected-component, connected-component, single-component, and path-scope fixtures.
- [ ] Add failing receipt ownership and later-fix owner-routing fixtures.
- [ ] Derive deterministic dependency edges and stable weighted component assignments.
- [ ] Publish and validate per-seat component patch artifacts and complete semantic-hunk coverage.
- [ ] Record stable finding identities and owners in receipts and consume them only from valid predecessors.
- [ ] Preserve one complete full-state seat and safe cumulative fallback.

### Task 9: Enforced bounded reads and stable prompt prefixes

**Files:**
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/agents/rev-reviewer.md`
- Modify: seat adapters, transcript validation, profiler, and focused tests

- [ ] Add failing tests for unbounded Read, Grep, shell reads, and transcript violations.
- [ ] Add explicit bounded expansion rules and prompt or evidence exceptions.
- [ ] Enforce budgets through Claude hooks and post-run audits for adapters without hooks.
- [ ] Retry a violated narrow review at full scope and refuse to receipt the narrow attempt.
- [ ] Move the invariant reviewer contract before volatile scope and lens content.
- [ ] Enable provider-supported cache-stability flags and report cache-write, cache-read, raw input, and cost separately.
- [ ] Verify clean-room ordering, exact model and effort, manifest binding, and byte-identical prefixes.

### Task 10: Expanded validation and measurement

- [ ] Run the full shell, Python, validator, syntax, diff, Unicode, attribution, and mode checks.
- [ ] Run a fresh exact four-seat optimizer panel and fix every supported finding.
- [ ] Reinstall and hash-verify the final personal plugin build.
- [ ] Measure PR #812 with raw provider tokens, cached input, scope words, and billed cost kept separate.

### Task 11: Hash-bound literal source-context packets

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py`
- Modify: both `rev` host skills, profiler, and focused tests

- [x] Add failing tests for deterministic range selection, exact source bytes, line numbering, overlap merging, shard limits, stable ordering, and explicit overflow.
- [x] Emit one at-most-32-KiB shard for each specialist and at most three shards for the full-state seat.
- [x] Bind packet shards and opened source ranges to the manifest, prompt, stream, and receipt hashes.
- [x] Let exact packet ranges count as opened original source while requiring bounded expansion for omitted or ambiguous evidence.
- [x] Fail the whole panel to the existing no-packet full-scope path on stale, escaped, truncated, malformed, or oversized packet evidence.
- [x] Extend profiling with packet bytes and source-range activity without counting projections as measured token savings.
- [ ] Run paired exact-roster adoption measurement and retain the feature only if total and median processed tokens improve by at least 10% with every review-quality gate intact.

### Task 12: Hash-bound assigned-patch chunks

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py`
- Modify: both `rev` host skills, profiler, and focused tests

- [x] Add failing tests for exact UTF-8 reconstruction, long physical lines, terminal lines without LF, deterministic shared sets, tampering, symlinks, and the disable switch.
- [x] Partition safe assigned patches under 24 KiB raw, 30 KiB predicted visible, 1,000-line, and UTF-8 scalar-boundary ceilings.
- [x] Activate chunk mode only when it saves at least 10% against 240-line windows.
- [x] Require ordered complete native reads and byte-exact provider-visible output while keeping chunks ineligible as source or citation evidence.
- [x] Preserve schema-1 manifests and unsafe-patch window fallback.
- [x] Extend profiling with patch proof calls, turns, visible bytes, chunks, and delivery modes.
- [ ] Measure paired exact-roster provider usage and retain chunk mode only if it clears the total and median 10% adoption gate without losing findings.

### Task 13: Adaptive plan-site closure

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py`
- Modify: both `rev` host skills, profiler, and focused tests

- [x] Parse and hash-bind every plan cluster, named site, test, regression path, line range, and exact sibling-search expression.
- [x] Give plan-completeness the full cumulative patch and every specialist one identical all-cluster changed-site and local-import closure.
- [x] Require bounded repository-root sibling searches and exact source proof for every cluster while preserving separate plan-file citations.
- [x] Validate plan panels without a coverage receipt and fail the entire attempt to a fresh legacy full-scope label on any error.
- [x] Preserve deterministic three through six seat topology, schema-1/2 compatibility, and Agent-panel legacy scope.
- [x] Repair missing-plan, subtree-search, ambiguous-expression, same-turn chunk, fallback-profile, and vacuous-test findings from the independent audit.
- [ ] Retain plan closure only if paired exact-roster runs clear the 10% total and median processed-token gates without losing baseline findings.
