# Procedural Stable Release Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the custom release authority, restore the existing gate to green, and release 0.4.4 through one signed previous-stable review with at most one P0/P1 delta.

**Architecture:** The signed `review-council--v0.4.3` tag supplies the independent review engine through a temporary detached worktree. The existing `verify-review-council.py` remains the only deterministic candidate gate; release sequencing is a short operator checklist rather than executable certificate machinery.

**Tech Stack:** Python 3 standard library, Bash 3.2-compatible shell, Git, GitHub CLI, existing Review Council shell and Python tests.

**Spec:** `docs/superpowers/specs/2026-09-15-review-council-convergence-repair-design.md`

## Global Constraints

- Delete the release authority instead of replacing or shrinking it.
- Preserve the session-wide hard-audit stop, immutable session inputs, adversarial coverage, and PR publication behavior.
- Use the signed 0.4.3 tag as the review engine; candidate review code must not make the release decision.
- Use exactly Sol, Terra, Opus, and Sonnet at maximum effort. Exclude Grok and Astra.
- Only P0 and P1 findings block or change this release. Defer P2 and P3.
- Permit one initial stable review and at most one stable delta review after a P0/P1 repair.
- Do not add custom release receipts, canary receipts, certificate formats, dependencies, or prose-locking tests.
- Run the complete existing verifier before pushing, then require green hosted CI before squash merge.
- Never amend commits. Do not use U+2013 or U+2014 in any artifact.

---

### Task 1: Remove the Custom Release Authority

**Files:**

- Delete: `scripts/verify-release-lane.py`
- Delete: `tests/test_release_lane.py`
- Rewrite: `docs/release.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `tasks/todo.md`

**Interfaces:**

- Consumes: signed previous-stable tag, existing unified verifier, stable `rev` workflow.
- Produces: a procedural release checklist with no executable authority API.

- [ ] **Step 1: Capture the failing deletion-boundary check**

Run:

```bash
test ! -e scripts/verify-release-lane.py \
  && test ! -e tests/test_release_lane.py \
  && ! rg -n 'verify-release-lane|record-review|run-canary|release certificate' \
       README.md CHANGELOG.md docs/release.md tasks/todo.md
```

Expected: FAIL because both authority files and their documentation still exist.

- [ ] **Step 2: Delete the authority-only implementation and tests**

Use `apply_patch` to delete both files. Do not replace them with a wrapper.

- [ ] **Step 3: Replace the operator procedure**

Rewrite `docs/release.md` around these commands and decisions:

```bash
git verify-tag review-council--v0.4.3
STABLE_PARENT=$(mktemp -d /tmp/review-council-stable.XXXXXX)
STABLE_TREE="$STABLE_PARENT/review-council-0.4.3"
git worktree add --detach "$STABLE_TREE" review-council--v0.4.3
python3 scripts/verify-review-council.py --root .
```

The document must name the exact roster, P0/P1-only policy, two-generation cap,
canonical PR publication, green CI, squash merge, signed tag, reinstall, discovery
checks, and `git worktree remove "$STABLE_TREE"` cleanup. It must not define a custom
receipt or certificate.

- [ ] **Step 4: Remove stale authority claims**

Update README, CHANGELOG, and task tracking to describe the procedural signed-tag lane.
Keep the 0.4.4 user-visible review and publication changes intact.

- [ ] **Step 5: Verify the deletion boundary is green**

Run the command from Step 1 again.

Expected: PASS with no matches.

Also run:

```bash
git diff --check
python3 - <<'PY'
from pathlib import Path
for name in ('README.md', 'CHANGELOG.md', 'docs/release.md', 'tasks/todo.md'):
    text = Path(name).read_text()
    assert chr(0x2013) not in text and chr(0x2014) not in text, name
PY
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit the removal**

```bash
git add -A scripts/verify-release-lane.py tests/test_release_lane.py \
  docs/release.md README.md CHANGELOG.md tasks/todo.md
git commit -m "refactor(release): remove custom release authority"
```

---

### Task 2: Repair the Three Stale Gate Fixtures

**Files:**

- Modify: `plugins/review-council/tests/t-read-bounds.sh`
- Modify: `plugins/review-council/tests/t-evidence-boundaries.sh`
- Modify: `plugins/review-council/tests/t-efficient.sh`
- Modify: `docs/codex.md`

**Interfaces:**

- Consumes: session-wide hard stops, four standard session inputs, promoted red-team schedule.
- Produces: fixtures and contract assertions aligned with those already-approved behaviors.

- [ ] **Step 1: Reproduce RED on the exact three tests**

Run:

```bash
plugins/review-council/tests/run-tests.sh evidence_audit_failure_modes
plugins/review-council/tests/run-tests.sh deleted_symbol_caller_evidence
plugins/review-council/tests/run-tests.sh adaptive_schedule_contract
```

Expected: all three commands fail for the already-recorded fixture or contract mismatch.

- [ ] **Step 2: Isolate independent audit scenarios**

In `test_evidence_audit_failure_modes`, create a fresh `seat_roster` session for the
malformed declaration, full-scope audit, legacy advisory, and each metadata failure.
Do not weaken the session-wide hard-stop behavior.

- [ ] **Step 3: Complete the evidence fixture inputs**

Before `rev-evidence.py prepare`, create empty private fixture files:

```python
(session / 'files.txt').write_text('')
(session / 'untracked.txt').write_text('')
```

Keep the existing `scope.env` and `roster.json` fixture content unchanged.

- [ ] **Step 4: Align schedule assertions and current documentation**

Assert the current contracts:

```text
A large or high-risk review plans 20 by adding four risk-discovery and four full red-team launches.
An important or explicitly adversarial review that is not otherwise large or high-risk plans 16 by adding four full red-team launches.
```

Update `docs/codex.md`. Do not rewrite the historical 0.4.1 CHANGELOG statement, and
stop treating that historical entry as the current schedule contract.

- [ ] **Step 5: Run GREEN on the three exact tests**

Run the three commands from Step 1.

Expected: each exits 0 with `failed=0`.

- [ ] **Step 6: Run neighboring focused suites**

```bash
plugins/review-council/tests/run-tests.sh session_audit_stop
plugins/review-council/tests/run-tests.sh sealed_session
plugins/review-council/tests/run-tests.sh skill
python3 -m py_compile plugins/review-council/scripts/lib/session_inputs.py \
  plugins/review-council/scripts/rev-evidence.py
```

Expected: every command exits 0 with no errors.

- [ ] **Step 7: Commit the fixture correction**

```bash
git add plugins/review-council/tests/t-read-bounds.sh \
  plugins/review-council/tests/t-evidence-boundaries.sh \
  plugins/review-council/tests/t-efficient.sh docs/codex.md
git commit -m "fix(tests): align fixtures with current review contracts"
```

---

### Task 3: Prove the Candidate With the Existing Gate

**Files:**

- No planned source changes.
- Output: existing verifier receipt and logs outside the repository.

**Interfaces:**

- Consumes: clean candidate commit.
- Produces: one hash-bound receipt from `verify-review-council.py`.

- [ ] **Step 1: Verify repository invariants**

```bash
git status --short
python3 - <<'PY'
import json
from pathlib import Path
paths = [
    Path('plugins/review-council/.claude-plugin/plugin.json'),
    Path('plugins/review-council/.codex-plugin/plugin.json'),
]
versions = {json.loads(path.read_text())['version'] for path in paths}
assert versions == {'0.4.4'}, versions
PY
```

Expected: clean status and exactly one version, `0.4.4`.

- [ ] **Step 2: Run the complete frozen-tree verifier**

```bash
VERIFY_STDOUT=$(mktemp /tmp/review-council-verifier.XXXXXX)
python3 scripts/verify-review-council.py --root . | tee "$VERIFY_STDOUT"
VERIFY_RECEIPT=$(sed -n 's/^\(reused \)\{0,1\}verification receipt: //p' \
  "$VERIFY_STDOUT" | tail -1)
test -f "$VERIFY_RECEIPT"
VERIFIER_LOG_DIR="$(dirname "$VERIFY_RECEIPT")/logs"
```

Expected: exit 0 and a printed verification receipt path.

- [ ] **Step 3: Inspect the complete result**

Read every verifier stage result and require exit 0. Search command logs for anchored
failure records rather than raw words that may occur in test names:

```bash
rg -n '(^|[[:space:]])(FAIL|FAILED|ERROR)([[:space:]:]|$)|"exit_code":[[:space:]]*[1-9]' \
  "$VERIFIER_LOG_DIR"
```

Expected: no matches. Confirm the built Codex bundle contains both manifests.

---

### Task 4: Run the Signed Previous-Stable Review

**Files:**

- No candidate edits unless generation 1 reports a verified P0/P1.
- Output: stable review session outside the repository.

**Interfaces:**

- Consumes: clean candidate, signed 0.4.3 tag, exact four-model configuration.
- Produces: one complete stable review and optionally one P0/P1 delta review.

- [ ] **Step 1: Verify and materialize the stable engine**

```bash
git verify-tag review-council--v0.4.3
STABLE_PARENT=$(mktemp -d /tmp/review-council-stable.XXXXXX)
STABLE_TREE="$STABLE_PARENT/review-council-0.4.3"
git worktree add --detach "$STABLE_TREE" review-council--v0.4.3
STABLE_PLUGIN="$STABLE_TREE/plugins/review-council"
```

Expected: signature verification succeeds and the worktree resolves to the tagged
0.4.3 commit.

- [ ] **Step 2: Verify the exact roster configuration**

Read `~/.config/review-council/config.json` without printing secrets. Require
`codex_models` to be `gpt-5.6-sol` and `gpt-5.6-terra`, `claude_models` to be `opus`
and `sonnet`, both OpenAI efforts to be maximum, and Grok and Astra to be excluded.

- [ ] **Step 3: Run generation 1 from the stable skill**

Load and follow `$STABLE_PLUGIN/codex-skills/rev/SKILL.md` with:

- candidate scope `branch` against the PR base;
- `--read-only` behavior, so reviewers never edit;
- `REVIEW_COUNCIL_HOST=codex` on every stable runner call;
- one four-seat panel using the four composite assignments from the spec;
- session artifacts outside both worktrees;
- 10-minute `rev-status.sh` relays while seats run;
- P0/P1 as the only release-blocking severities.

Require valid results, audits, coverage receipt, profiler output, and `report.md` before
calling the review complete. Verify every reviewer claim against candidate source.

- [ ] **Step 4: Apply the bounded decision**

If generation 1 has no verified P0/P1, skip generation 2. If it has a verified P0/P1:

1. add a regression that fails for that defect;
2. apply the minimal repair;
3. run the focused test and complete verifier;
4. commit the repair without amending;
5. run one stable read-only delta panel over the repair delta, prior P0/P1 decisions,
   and one full-state integration assignment.

Stop if generation 2 has a new or open P0/P1. Never launch generation 3.

- [ ] **Step 5: Publish the canonical PR review**

Use the candidate publication workflow once the stable decision is clean. Require the
canonical badge, headings, verdict tip, decisions section, collapsible sections, and
footer. Read back the GitHub review and compare its body and reviewed commit with the
rendered session artifact.

---

### Task 5: Merge, Release, and Verify Installation

**Files:**

- No planned source changes.

**Interfaces:**

- Consumes: clean stable review, green local verifier, open PR #6.
- Produces: squash-merged PR, signed 0.4.4 release, installed plugin, discovery proof.

- [ ] **Step 1: Push and wait for required CI**

```bash
git push origin feat/pr-review-post
gh pr checks 6 --watch
```

Expected: every required check is green. Diagnose and fix any red check before merge.

- [ ] **Step 2: Squash-merge the PR**

```bash
gh pr merge 6 --squash
test "$(gh pr view 6 --json state --jq .state)" = MERGED
MERGE_COMMIT=$(gh pr view 6 --json mergeCommit --jq .mergeCommit.oid)
test -n "$MERGE_COMMIT"
```

Read back the PR state and merge commit. Do not use `--admin`.

- [ ] **Step 3: Create and publish the signed release**

From a clean checkout of merged `main`:

```bash
git tag -s review-council--v0.4.4 -m "review-council 0.4.4" "$MERGE_COMMIT"
git push origin review-council--v0.4.4
git verify-tag review-council--v0.4.4
gh release create review-council--v0.4.4 --verify-tag \
  --title "review-council 0.4.4" --generate-notes
```

Expected: tag verification and GitHub release creation both succeed.

- [ ] **Step 4: Reinstall and verify fresh-session discovery**

Install `review-council@review-council` from the released marketplace. Start fresh
Claude and Codex sessions and require both to discover `rev` and `stack` at version
`0.4.4`. Compare the installed plugin files and modes with the released tag.

- [ ] **Step 5: Clean up the stable worktree**

```bash
git worktree remove "$STABLE_TREE"
rmdir "$STABLE_PARENT"
```

Preserve external review and verifier artifacts. Report the PR, merge commit, tag,
release URL, installed version, and discovery results.
