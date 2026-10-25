# Per-prepare Source-Context Memo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut repeated predecessor source-context reconstruction during large review preparation without skipping any proof or tamper checks.

**Architecture:** Keep a process-local memo of canonical source-context expectations in `rev-evidence.py`. Validate the current manifest, receipt chain, inputs, artifacts, source bytes, and recursion path on every visit; use the memo only to skip rebuilding canonical Git facts and packet selection for the same validated inputs. Do not persist memo entries or change reviewer prompts, budgets, or scope.

**Tech Stack:** Python 3, shell-based evidence tests, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-25-prepare-source-context-memo-design.md`

## Global Constraints

- Preserve all existing manifest, receipt, input, artifact, source-byte, cycle, freshness, and review-scope checks.
- Cache only fully reconstructed canonical source-context expectations, keyed by session and manifest identity, repository and tree identity, mode, and all canonical inputs.
- Keep the memo in process memory and clear it at the start of each `prepare()` invocation.
- Prove the new regression fails on frozen test-only source in CI before adding the implementation.
- Run the full candidate gate in CI on the exact PR head; do not substitute a smaller local suite.
- Review Council changes with one independent normal reviewer. Do not use Review Council to review its own repository.
- Keep the three plugin manifests aligned at 0.8.9 and preserve existing verification thresholds.
- Run one matched #1830 Luna replay after its merge, using the final Sol source and scope identity from its owner. This benchmark is not a 0.8.9 release gate.

## Review Focus

- Repeated visits with different canonical delta inputs must not reuse the wrong packet expectation; bind the serialized change and delta inputs in the memo key and test a predecessor transition.
- Artifact or input mutation after a memo hit must still fail; validate all current bytes before reading the memo and test a tampered source-context shard.
- Cyclic predecessor chains must still fail after a prior successful lookup; test that recursion detection runs before memo lookup.
- A failed or partial reconstruction must not seed the memo; inject a one-time reconstruction failure and assert the next attempt reconstructs again.
- Identical manifest bytes in another session or repository must not share entries; test that resolved session and repository identities distinguish keys.

---

### Task 1: Add the shared-predecessor regression

**Files:**
- Modify: `plugins/review-council/tests/t-evidence.sh`

**Interfaces:**
- Consumes: existing `fixture()`, `prepare()`, `finish()`, `module.prior_coverage()`, and `module.plan_source_context()` test helpers.
- Produces: `source_context_memo_reuses_shared_predecessor_reconstruction()` and a companion tamper assertion in the evidence test group.

- [ ] Build a small history with shared predecessor ancestry and successful receipts. Wrap `module.plan_source_context()` to count canonical reconstructions by manifest label. Call `module.prior_coverage()` in the imported test process and assert one canonical rebuild per unique manifest, regardless of how often the history revisits it.
- [ ] After a successful lookup, mutate a referenced source-context shard and assert validation rejects it. Restore it, alter canonical delta inputs, and assert the changed identity is not accepted through the prior memo entry.
- [ ] Assert equal manifest bytes in a second session or repository produce a distinct memo key. Inject one reconstruction failure, retry that key, and assert the failure did not seed an entry.
- [ ] Exercise cyclic-predecessor refusal after a successful lookup and assert it still fails.
- [ ] Push the test-only commit on the candidate PR. Require the exact-head CI run to fail only at the new reconstruction-count assertion on Ubuntu and macOS; proof preparation and package validation must pass.
- [ ] Commit the expected-red test as `test: cover source context memo validation`.

### Task 2: Memoize only canonical reconstruction

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Test: `plugins/review-council/tests/t-evidence.sh`

**Interfaces:**
- Consumes: `validate_source_context_snapshot(repo, session, manifest, canonical_changes, canonical_delta, manifest_sha256)` and its existing caller in `_validated_manifest()`.
- Produces: `SOURCE_CONTEXT_RECONSTRUCTION_MEMO: dict[tuple[str, ...], dict]` and private `_source_context_reconstruction_key(repo, session, manifest, manifest_sha256, canonical_changes, canonical_delta) -> tuple[str, ...]`.

- [ ] Pass the raw manifest hash already computed by `_validated_manifest()` into `validate_source_context_snapshot()`. Add the memo and key helper, binding resolved session path, raw manifest hash, repository root, base and snapshot tree IDs, phase and source-context mode, plus digests of canonical change and delta inputs.
- [ ] Clear the memo at the start of `prepare()`. Keep `_validated_manifest()` schema, hash, receipt, lineage, input, artifact, freshness, and cycle checks ahead of any memo lookup.
- [ ] Keep `validate_source_context_bytes()` on every validation visit. Read a memo entry only for the later canonical reconstruction block. Store the reconstructed expectation only after the packet comparisons succeed; never store exceptions, partial values, or a validation-success flag.
- [ ] Run the targeted regression through the candidate CI workflow and confirm one rebuild per unique manifest, repeated tampering rejection, changed-key misses, and cycle refusal.
- [ ] Commit the implementation as `perf: memoize source context reconstruction per prepare`.

### Task 3: Review and release 0.8.9

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/release.md`
- Modify: `plugins/review-council/.claude-plugin/plugin.json`
- Modify: `plugins/review-council/.codex-plugin/plugin.json`
- Modify: `plugins/review-council/.cursor-plugin/plugin.json`

**Interfaces:**
- Consumes: the tested memo implementation and the current signed 0.8.8 release.
- Produces: a candidate PR with all three manifests at 0.8.9, a 0.8.9 changelog entry, and release instructions pinned to the 0.8.8 base.

- [ ] Update release metadata for 0.8.9, retaining the existing Unreleased history and exact test thresholds.
- [ ] Run one independent read-only normal review of the finished code diff. Resolve actionable P0-P2 findings and obtain a clean follow-up review; ignore P3 per the repository rule.
- [ ] Push the candidate and require proof preparation, macOS verification, Ubuntu verification, and Cursor package validation to pass on its exact head.
- [ ] Recheck PR head and mergeability, mark it ready, and squash-merge only after the review and all required CI checks are clean.
- [ ] From the merged commit, create and verify signed tag `review-council--v0.8.9`, publish the GitHub release, reinstall Claude, Codex, and Cursor, and compare installed version, file identity, and mode identity with the tag.

### Task 4: Run the one large-batch Luna parity benchmark

**Files:**
- Read: the final #1830 Sol manifests, receipts, prompts, audits, and timing records supplied by its owner.
- Record: #77 release ledger and this task's close-out notes.

**Interfaces:**
- Consumes: the owner's final Sol source tree, base, human scope, and review timing identity; the released Luna runtime.
- Produces: a matched 4-seat Luna result and a Sol-versus-Luna comparison for #1830.

- [ ] Wait for the #1830 owner to confirm merge and provide the final frozen Sol identity. Do not infer scope from the merged branch.
- [ ] Run one 4-seat Luna/xhigh panel on the same frozen tree and human scope after merge. Keep the existing Sol review unchanged.
- [ ] Compare preparation and reviewer wall-clock time separately, first-attempt valid results and proof failures, retries, and findings by severity and overlap. Record both runtime versions.
- [ ] Update the eligible post-release Luna denominator in issue #77. Keep the issue open until its stated first-attempt failure target is met; use this benchmark to decide whether a separate Luna budget change is warranted.

## Close-out

Record exact CI run IDs and SHAs, the review result, merged commit, signed release identity, host installation checks, and the #1830 comparison outcome in `tasks/todo.md`.
