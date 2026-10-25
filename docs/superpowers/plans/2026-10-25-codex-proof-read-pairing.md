# Codex Proof-Read Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Codex reviewer turns on large assignments by permitting two separate, consecutive proof reads in one Codex model turn while preserving exact audit proof.

**Architecture:** Keep each read as one native `cat -- <artifact>` call and retain current per-path and byte validation. Track Codex `turn.started` and `turn.completed` boundaries so the auditor can group independent calls that lack their own turn ID. Raise only Codex's eligible proof-read batch limit to two; source-context packets and repository expansion retain their existing limits.

**Tech Stack:** Python, Codex NDJSON transcripts, unittest, generated Review Council evidence prompts.

**Spec:** `docs/superpowers/specs/2026-10-25-codex-proof-read-pairing-design.md`

## Global Constraints

- Keep compound shell reads disabled; each proof call reads exactly one artifact.
- Retain exact per-artifact bytes, identity, order, and completeness validation.
- Each tool output remains at most 32 KiB; a paired proof turn remains at most 60 KiB.
- Pair only patch chunks, required source segments, and the evidence index, in exact order.
- Keep source-context packets to one per turn and leave repository expansion limits unchanged.
- A required source segment whose predicted visible size exceeds 16 KiB because it is one line must be read alone; its per-tool ceiling remains 32 KiB.
- Transcripts without explicit Codex turn boundaries keep the conservative one-call-per-turn interpretation.

## Review Focus

- Missing or truncated Codex turn boundaries must not merge otherwise separate reads; cover absent-boundary and unclosed-turn audit cases.
- Reordered, repeated, or missing exact artifacts must remain invalid; cover with paired source-segment transcript cases.
- Three or more proof reads in one Codex turn must fail; cover with three distinct required segments in one turn.
- A one-line segment over the normal 16 KiB segment target must not be paired even when the total is under 60 KiB; cover with one oversized segment and a neighboring segment.
- Capacity estimates must count oversized one-line segments as standalone turns instead of halving every segment count; cover with the prepared manifest for the oversized-line fixture.
- Per-call output over 32 KiB or combined output over 60 KiB must fail; cover the aggregate guard directly and retain the auditor's per-call regression.

---

### Task 1: Pair exact Codex proof reads

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py` to set the Codex proof batch limit to two and render explicit separate-read instructions.
- Modify: `plugins/review-council/scripts/lib/review-read-audit.py` to group calls only within explicit Codex turn boundaries and reject oversized-segment pairing.
- Modify: `plugins/review-council/skills/rev/phases/20-discovery.md` and `plugins/review-council/codex-skills/rev/phases/20-discovery.md` to document the Codex-specific limit and unchanged packet limit.
- Modify: `tests/test_deleted_source_proof.py` for exact audit transcript regressions, `tests/test_review_boundaries.py` for batch-limit and combined-byte guard tests, and `plugins/review-council/tests/t-read-bounds.sh`, `plugins/review-council/tests/t-patch-chunks.sh`, and `plugins/review-council/tests/t-prompt-evidence.sh` for the updated Codex contracts.

**Interfaces:**
- Consumes: existing Codex `item.started` / `item.completed` events and enclosing `turn.started` / `turn.completed` events; existing manifest-bound patch chunks and required source segments.
- Produces: `read_batch_limit('codex') == 2`; paired proof reads share an audit turn only when enclosed by the same explicit Codex turn; `read_batch_limit` does not affect `source_context.packet_batch_limit`.

- [x] **Step 1: Write regressions first.** Add tests for paired patch chunks and required segments, a final segment paired with the evidence index, absent and unclosed turn boundaries, reordered, repeated, and missing reads, three distinct reads in one turn, packet batching still rejected, oversized one-line segment solitude, the capacity estimate for standalone segments, and the 60 KiB aggregate cap. Commits `4012130` and `c5c61dd` contain the regression set.
- [x] **Step 2: Verify the expected failures in CI.** Run `40235826237` verified exact head `c5c61dde1407c673e66f6fc0a2cbc2f5c2f4144e`: Ubuntu and macOS each reported the eight intended missing-behavior failures. Proof preparation and Cursor packaging passed in `40235826268` at the same SHA.
- [x] **Step 3: Implement turn grouping and the Codex limit.** Track explicit Codex turn boundaries without relaxing the implicit fallback; allow two eligible proof calls, preserve packet and expansion limits, reject any pair containing an oversized one-line required segment, and keep prepared capacity estimates accurate for standalone segments.
- [x] **Step 4: Update rendered and installed discovery instructions.** Tell Codex it may issue up to two consecutive eligible proof reads as separate native commands in one model turn; keep source-context packet instructions at one packet per turn.
- [ ] **Step 5: Run full verification and review the diff.** The full exact-head verify job, proof-preparation job, and Cursor package job pass; `git diff --check` passes; existing compound-read and mutation-restoration regressions remain unchanged and passing in CI.
- [ ] **Step 6: Commit the reviewed implementation.** Use a descriptive commit without tool attribution.

**Expected results:** A valid paired transcript receives exact credit for both artifacts and records one fewer tool turn. All malformed, reordered, repeated, missing, over-count, oversized-segment, packet-pair, and aggregate-overflow cases remain rejected.

### Task 2: Release 0.8.10

**Files:**
- Modify: `CHANGELOG.md` with the 0.8.10 entry.
- Modify: `plugins/review-council/.claude-plugin/plugin.json`, `plugins/review-council/.codex-plugin/plugin.json`, and `plugins/review-council/.cursor-plugin/plugin.json` to version 0.8.10.
- Modify: `docs/release.md` with the signed 0.8.10 tag and host-install verification steps.
- Modify: `tasks/todo.md` with exact expected-red, internal-review, CI, merge, and release evidence.

**Interfaces:**
- Consumes: Task 1's tested Codex proof-read behavior and the stable signed 0.8.9 release.
- Produces: a normal-reviewed candidate PR with aligned 0.8.10 metadata, green current-head CI, a squash merge, signed release tag, published release, and verified Claude, Codex, and Cursor installs.

- [ ] **Step 1: Align release metadata.** Add the 0.8.10 changelog entry and update all three manifests and `docs/release.md` together.
- [ ] **Step 2: Commit release metadata.** Use a descriptive commit without tool attribution.
- [ ] **Step 3: Complete independent internal review.** Fix actionable P0-P2 findings and repeat the review on the corrected diff; do not use Review Council for this repository.
- [ ] **Step 4: Pass exact-head CI.** Require proof-preparation, Ubuntu verification, macOS verification, and Cursor package validation on the same PR head.
- [ ] **Step 5: Merge and publish.** Squash-merge without bypassing branch protection, create and verify signed tag `review-council--v0.8.10`, publish the release, reinstall all three hosts, and verify installed version and file/mode identity.
