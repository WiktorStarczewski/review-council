# Review Council Wall-Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut invalid-panel retries and deterministic evidence turns while preserving the exact four-seat review contract and all coverage proofs.

**Architecture:** Harden provider contracts with local replay, separate required evidence failures from unused exploration advisories, batch exact immutable proof, and recover one failed seat at a time. Reduce plan duplication by preparing sibling search results once and routing cluster closure with the same specialist-plus-integration invariant used by code panels.

**Tech Stack:** Bash, Python 3 standard library, JSON manifests, provider NDJSON streams, Git object snapshots.

**Spec:** `docs/superpowers/specs/2026-09-12-review-council-wall-time-design.md`

## Global Constraints

- Keep Sol max, Terra max, Opus max, and Sonnet max reviewers. Historical measurements below retain the roster label that produced them.
- Keep every risk bundle, every-hunk discovery, and one full-state integration seat.
- Required evidence and source citation integrity fail closed.
- Run no paid panel until local replay and the required local gates pass.
- Add each behavior test first and observe the expected failure before implementation.

---

### Task 1: Provider transcript replay and audit advisories

**Files:**
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py`
- Modify: `plugins/review-council/scripts/rev-profile.py`
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Test: `plugins/review-council/tests/t-read-bounds.sh`
- Test: `plugins/review-council/tests/t-profile.sh`
- Test: `plugins/review-council/tests/t-evidence.sh`

**Interfaces:**
- Extends audit schema 2 with `violations` for fatal failures and an optional `advisories` field for unused exploration deviations.
- Preserves profiling and receipt validation for completed historical schema-2 sessions that omit `advisories`.

- [ ] Add a minimized c3 Claude fixture whose numbered final blank line lacks a rendering newline. Assert that it proves the requested bytes.
- [ ] Run `plugins/review-council/tests/run-tests.sh read_audit` and confirm the new assertion fails with `source-output-mismatch`.
- [ ] Add a passing complete-evidence control plus one unused unparseable read-only exploration call. Assert a valid audit, no extra source credit, and one advisory.
- [ ] Mutate the same fixture so the bad call is the only assigned patch, required-source, or finding-citation proof. Assert a fatal violation for each mutation.
- [ ] Add a manifest-backed fixture where the live worktree changes after the read. Assert that output matching the frozen blob is credited and output matching only the later worktree is rejected.
- [ ] Implement exact Claude terminal-blank normalization, frozen-blob comparison, and post-coverage advisory classification.
- [ ] Extend receipt and profiler validation for optional advisories, while preserving immutable schema-2 historical audits.
- [ ] Run the focused read-audit, evidence, and profiler suites and confirm they pass without warnings.

### Task 2: Adapter surface reduction and exact proof batching

**Files:**
- Preserve historical Grok decoder fixtures without a live adapter.
- Modify: `plugins/review-council/scripts/seats.d/claude.sh`
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py`
- Test: `plugins/review-council/tests/t-read-bounds.sh`
- Test: `plugins/review-council/tests/t-patch-chunks.sh`

**Interfaces:**
- Live dispatch allows only Codex, Gemini, and Claude CLI adapters, with Agent seats handled by the host.
- Claude keeps `Read,Grep,Bash` and disables slash commands.
- The auditor credits a single call or turn only when its output exactly equals the ordered concatenation of listed immutable artifacts and stays at or below 60 KiB.

- [ ] Add adapter argument assertions for the Claude restrictions. Run them and confirm they fail on the absent flags.
- [ ] Add exact two-chunk and multi-segment concatenation fixtures for Codex and Claude. Preserve Grok fixtures only as historical decoder coverage. Add reordered, missing, replaced, and 60 KiB overflow mutations.
- [ ] Run the focused patch and read suites and confirm the new valid batches fail while every mutation already fails closed.
- [ ] Add adapter flags and provider-specific render limits. Keep Codex batching disabled behind a hash-bound canary receipt.
- [ ] Teach the auditor to split one exact concatenated result back into its ordered artifact proofs.
- [ ] Run `plugins/review-council/tests/run-tests.sh patch_chunk` and `plugins/review-council/tests/run-tests.sh read_audit` and confirm all assertions pass.

### Task 3: Frozen plan search packets and cluster routing

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py`
- Test: `plugins/review-council/tests/t-plan-evidence.sh`
- Test: `plugins/review-council/tests/t-prompt-evidence.sh`

**Interfaces:**
- Each plan cluster stores one frozen `search_proof` with contract, status, saturation, bytes, and SHA-256.
- Each cluster has one specialist owner plus the full-state plan owner.
- Additional reviewer searches remain allowed but are not mandatory proof.

- [ ] Add plan fixtures proving one local search per cluster, identical search packets for all seats, and specialist-plus-full ownership for every cluster.
- [ ] Add mutations for changed search bytes, changed contract, nonzero status other than no-match, saturation at 80 results, missing site paths, and missing cluster owners.
- [ ] Run the plan suites and confirm the valid fixture fails because prepared search proof and routed closure do not exist.
- [ ] Execute each strict search contract against the frozen snapshot during prepare, publish its immutable artifact, and validate it again during manifest freshness checks.
- [ ] Route cluster closure round-robin over non-full plan seats while keeping the whole inline plan and every cluster on the full-state owner.
- [ ] Replace mandatory reviewer search calls with the prepared exact search result and keep reviewer-initiated expansion available.
- [ ] Run `plugins/review-council/tests/run-tests.sh plan_evidence` and `plugins/review-council/tests/run-tests.sh prompt_evidence` and confirm all assertions pass.

### Task 4: Seat-local recovery and persistent attempt budgets

**Files:**
- Modify: `plugins/review-council/scripts/rev-seat.sh`
- Modify: `plugins/review-council/scripts/rev-state.sh`
- Modify: `plugins/review-council/scripts/rev-status.sh`
- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Test: `plugins/review-council/tests/t-seat.sh`
- Test: `plugins/review-council/tests/t-state.sh`
- Test: `plugins/review-council/tests/t-status.sh`
- Test: `plugins/review-council/tests/t-evidence.sh`
- Test: `plugins/review-council/tests/t-skill.sh`

**Interfaces:**
- Persist `attempts[panel][seat][generation]` and cap provider calls at four across wrapper and host retries.
- Parent-child receipts bind replacement generation, parent manifest, seat, bundle, model, effort, prompt, stream, result, and frozen snapshot hashes.

- [ ] Add a runner fixture that restarts `rev-seat.sh` and prove the fifth provider call is rejected before launch.
- [ ] Add a four-seat receipt fixture with one invalid seat, then a valid same-assignment retry. Assert that three original valid seats are retained.
- [ ] Add a repeated-failure fixture with a full-scope child assignment. Assert one generation per assignment and reject every mixed snapshot, model, bundle, or prompt mutation.
- [ ] Add skill contract assertions for immediate seat retry, panel-global cancellation, straggler triage, and no edits before the composite receipt seals.
- [ ] Run the focused seat, state, status, evidence, and skill suites and confirm the new recovery assertions fail for the current whole-panel fallback.
- [ ] Implement atomic attempt counters, typed terminal status, child assignment preparation, and composite receipt validation.
- [ ] Update both host skills to react as soon as a seat finishes, retain valid seats, and cancel siblings only for panel-global failure.
- [ ] Run the same focused suites and confirm all assertions pass.

### Task 5: Self-host replay gate, tiered verification, and probe concurrency

**Files:**
- Create: `plugins/review-council/scripts/rev-contract-check.py`
- Modify: `plugins/review-council/scripts/rev-preflight.sh`
- Modify: `plugins/review-council/scripts/lib/roster.py`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Test: `plugins/review-council/tests/t-preflight.sh`
- Test: `plugins/review-council/tests/t-roster.sh`
- Test: `plugins/review-council/tests/t-skill.sh`

**Interfaces:**
- `rev-contract-check.py --root ROOT --session SESSION` writes an immutable pass receipt keyed by boundary hashes and provider versions.
- Roster probes unique adapter/model/effort tuples concurrently and emits configured seat order.

- [ ] Add a preflight fixture where an auditor change and a failing replay prevent paid probes, and an unrelated repository change bypasses the self-host-only replay gate.
- [ ] Add delayed probe shims proving three unique probes overlap while duplicate Opus seats share one probe and output order remains deterministic.
- [ ] Run preflight and roster suites and confirm the new timing and replay assertions fail.
- [ ] Implement the hash-keyed replay receipt and invoke it before paid probes only when review-council provider boundaries changed.
- [ ] Probe unique adapter/model/effort tuples concurrently with bounded workers.
- [ ] Add the 8-30 second focused, 3-minute evidence, and one-full-suite-per-material-tree rules to both skills.
- [ ] Run preflight, roster, and skill suites and confirm all assertions pass.

### Task 6: Local and live certification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `tasks/todo.md`
- Modify: `tasks/lessons.md`

**Interfaces:**
- Produces one named local gate receipt and one exact-roster live certification report.

- [ ] Run Python compilation, shell syntax, Unicode dash scan, plugin validators, Python tests, focused shell suites, and the complete shell suite once on the final material tree.
- [ ] Replay the preserved c3 transcripts through the final auditor. Require the two Claude terminal-blank cases and unused Sol exploration deviations to pass while every missing-proof mutation stays fatal.
- [ ] Run only the adapter canaries whose exact batch behavior is absent from replay. Enable Codex concatenation only if its bytes pass exactly.
- [ ] Run one exact Sol, Terra, Opus, Sonnet panel at maximum effort. Require four valid results, complete bundles, one full-state integration proof, and no lost actionable findings.
- [ ] Compare model-independent prompt, evidence, proof-call, tool-turn, retry, and local-suite metrics with the named c3 and 0.4.0 baselines. Report provider tokens, cost, elapsed time, and finding yield under the new Sol/Terra/Opus/Sonnet roster label without attributing their difference to workflow changes alone.
- [ ] If the four-seat panel clears the prior inline-specialist quality gate, implement that already specified feature through its own failing tests, then repeat this final certification once. Otherwise leave it disabled and record the measured reason.
- [ ] Commit without attribution, push, reinstall the cache-busted plugin, and resume wallet PR #812 with this installed version.

### Task 5a: Codex source-window batching

**Files:**
- Modify: `plugins/review-council/scripts/rev-prompt.sh`
- Modify: `plugins/review-council/scripts/lib/readonly-bash-guard.py`
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py`
- Modify: `plugins/review-council/scripts/rev-profile.py`
- Test: `plugins/review-council/tests/t-prompt-evidence.sh`
- Test: `plugins/review-council/tests/t-read-bounds.sh`
- Test: `plugins/review-council/tests/t-profile.sh`

- [x] Measure consecutive c3 Sol source windows and prove a conservative 21.5 percent tool-turn reduction.
- [x] Add a strict Codex-only semicolon batch parser with per-window and aggregate line, byte, path, and overlap checks.
- [x] Require exact concatenated frozen bytes and reject mixed producers, transforms, conditions, substitutions, and redirects.
- [x] Report source-read calls separately from source-read batches.
- [x] Pass focused prompt, guard, audit, and profiler tests.
- [x] Run one exact Sol canary before enabling the prompt path for certification.
