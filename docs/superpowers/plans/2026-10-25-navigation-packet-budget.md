# Navigation Packet Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Keep generated navigation packets within the 16,384-byte limit while retaining every omission record and limitation.

**Architecture:** The renderer reserves the exact fixed metadata size before admitting optional navigation rows. It keeps the full deterministic facts JSON as the source of complete evidence and only omits rows from the navigation view, with their existing count and hash records intact.

**Tech Stack:** Python 3 standard library, Bash regression harness, GitHub Actions.

**Spec:** Issue #77's requirement that evidence preparation completes without weakening proof or scope limits; the synthetic overflow case supplied with the 0.8.5 prep diagnostic.

## Global Constraints

- Keep `NAVIGATION_TOTAL_LIMIT` at 16,384 bytes and `NAVIGATION_ROW_LIMIT` at 1,024 bytes.
- Retain all six omission records, their complete-list SHA-256 values, the limitations list, and the complete facts JSON.
- Keep full review scope, source proof requirements, and read-audit enforcement unchanged.
- The release owner verifies the fix; one independent normal reviewer checks Council code.

## Review Focus

- Many large optional rows across all six sections must fit while retaining every omission digest and limitation; the supplied overrun fixture pins this behavior.
- An oversized fixed metadata block must still fail closed instead of being truncated; the regression checks the refusal.
- Multibyte limitation text and line endings count as encoded bytes; the regression measures the resulting packet bytes.
- Empty sections must still emit their omission count and digest; the regression checks all six sections.
- Omitted row counts plus included row counts must equal the original section size; the regression parses each emitted section.

---

### Task 1: Pin the overflow in regression coverage

**Files:**
- Modify: `plugins/review-council/tests/t-evidence.sh`, `bounded_navigation_markdown`
- Test: the existing `structure` group in `plugins/review-council/tests/t-evidence.sh`

- [x] Add the six-section synthetic case with twelve 900-byte rows per section and seven retained limitation lines, including multibyte text.
- [x] Assert the packet byte bound, retained limitations and digests, accurate omitted counts, empty-section metadata, and fail-closed behavior when fixed metadata alone exceeds the limit.
- [ ] Run the test-only commit in GitHub Actions and confirm it fails at `navigation packet exceeds byte limit` on the exact source SHA.

### Task 2: Reserve fixed metadata before optional rows

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py`, `markdown`
- Test: the synthetic case from Task 1

- [ ] Compute the encoded size of the fixed header, section labels, worst-case omission records, and limitations before admitting rows.
- [ ] Admit each row only when its encoded bytes and newline fit in the remaining packet budget.
- [ ] Keep the existing omission count and digest for each section, then run the exact-head CI gate and package validation.

### Task 3: Review and release

**Files:**
- Modify: `CHANGELOG.md`, the three plugin manifests, and `docs/release.md` for the next patch release.

- [ ] Get one independent normal internal review and resolve actionable P0-P2 findings.
- [ ] Pass current-head CI, squash-merge, publish a signed release, and install it on Claude, Codex, and Cursor.
- [ ] Verify installed file and mode identity, then rerun the blocked 0.8.5 preparation with the new runtime before counting any Luna result.
