# Review Council Stable Release Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep ordinary Review Council reviews adaptive while making the plugin's own release review use a previous-stable engine, at most two P0/P1 review generations, a deterministic candidate gate, and changed-subsystem canaries.

**Architecture:** Retain the small global safety repairs at existing session boundaries, then add one repository-owned release authority outside the review engine. `session_inputs.py` seals preflight inputs, the host skills compose adversarial assignments into normal panels, and `verify-release-lane.py` binds immutable stable review decisions and canary receipts into one final certificate. There is no generic or release-specific mutable convergence database, and the candidate never reviews itself as a release gate.

**Tech Stack:** Python 3 standard library, Bash 3.2-compatible shell, Git, existing shell test harness, `unittest`, Claude Code and Codex plugin manifests.

**Spec:** `docs/superpowers/specs/2026-09-15-review-council-convergence-repair-design.md`

## Global Constraints

- Ordinary adaptive, numeric, read-only, document, and stack stopping rules remain unchanged.
- Every code panel gets one composite red-team assignment without adding a provider call.
- Large, high-risk, important, or explicitly adversarial adaptive reviews may add one full red-team panel before planning.
- Release review uses the installed signed N-1 plugin, never the candidate plugin.
- Release review gets one complete read-only generation and at most one read-only delta generation after P0/P1 repairs.
- Only P0 and P1 findings change or block the release. P2 and P3 are recorded and deferred.
- A remaining P0/P1, invalid review receipt, or infrastructure failure blocks the release without another generation.
- Evidence manifests seal `scope.env`, `roster.json`, `files.txt`, and `untracked.txt`.
- A hard evidence-audit failure stops the whole session and requires a fresh review session.
- Review roster remains exactly Sol, Terra, Opus, and Sonnet at maximum effort. Astra and Grok remain excluded.
- Do not add dependencies, lower a gate, weaken evidence checks, or change the canonical GitHub review template.
- Match the existing comment ratio: Python is below 1 percent repository-wide; shell is about 2 percent repository-wide, with `rev-preflight.sh` at 19 percent because it documents shell hazards.
- Do not use U+2013 or U+2014 in source, tests, docs, commits, or release text.
- Never amend commits. Each task lands as a new attribution-free commit.

---

## File and Responsibility Map

| File | Responsibility |
| --- | --- |
| `plugins/review-council/scripts/lib/rev-attempt.py` | Session-wide hard-audit stop and provider reservation refusal. |
| `plugins/review-council/scripts/lib/session_inputs.py` | Locking, seal detection, validation, and atomic installation for the four session inputs. |
| `plugins/review-council/scripts/rev-preflight.sh` | Build one staged input generation and refuse sealed sessions before probes. |
| `plugins/review-council/scripts/lib/roster.py` | Route session roster publication through the input authority. |
| `plugins/review-council/scripts/rev-evidence.py` | Hold the session-input lock through manifest publication. |
| `plugins/review-council/skills/rev/SKILL.md` | Claude Code composite red-team and promoted coverage contract. |
| `plugins/review-council/codex-skills/rev/SKILL.md` | Codex contract matching the Claude Code behavior. |
| `scripts/verify-release-lane.py` | Immutable stable review, canary, and final release receipt validator. |
| `tests/test_release_lane.py` | Stable identity, generation, receipt, canary, and certification tests. |
| `docs/release.md` | Operator sequence for stable review, P0/P1 repair, canaries, merge, tag, and install. |
| `README.md` | Short link and release-lane summary. |
| `CHANGELOG.md` | 0.4.4 user-visible release behavior. |

---

### Task 1: Stop the Entire Session After a Hard Evidence Audit

**Status:** Implemented in `c2ea6c8` and `500a28d`; scoped re-review found no P0/P1.

**Files:**

- Modify: `plugins/review-council/scripts/lib/rev-attempt.py`
- Modify: `plugins/review-council/tests/t-read-bounds.sh`
- Modify: `plugins/review-council/tests/t-seat.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: existing `check`, `reserve`, and `stop` commands.
- Produces: immutable `SESSION/attempts/session.stopped.json` and cross-label refusal before provider reservation.

- [x] **Step 1: Add failing cross-label and overlapping reservation regressions**
- [x] **Step 2: Prove a fresh label bypasses the old panel-local stop**
- [x] **Step 3: Add the session marker under the existing attempt lock**
- [x] **Step 4: Scan production `r*-*.read-audit.json` legacy artifacts**
- [x] **Step 5: Pass `session_audit_stop`, `narrow_seat`, and `seat` focused gates**
- [x] **Step 6: Pass the scoped fix re-review with no P0/P1**

---

### Task 2: Seal and Install Session Inputs as One Generation

**Files:**

- Create: `plugins/review-council/scripts/lib/session_inputs.py`
- Modify: `plugins/review-council/scripts/rev-preflight.sh`
- Modify: `plugins/review-council/scripts/lib/roster.py`
- Modify: `plugins/review-council/tests/t-preflight.sh`
- Modify: `plugins/review-council/tests/t-roster.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: a session directory and staged bytes for the four standard inputs.
- Produces:

```python
STANDARD_INPUTS = ("scope.env", "roster.json", "files.txt", "untracked.txt")

class SessionInputsError(RuntimeError): ...
class SessionInputsSealedError(SessionInputsError): ...

def find_evidence_seal(session: Path) -> Path | None: ...
def session_input_lock(session: Path) -> Iterator[Path]: ...
def assert_unsealed(session: Path) -> None: ...
def validate_standard_inputs(session: Path, require_all: bool) -> dict[str, bytes]: ...
def install_inputs(session: Path, values: Mapping[str, bytes], complete: bool) -> None: ...
```

CLI:

```text
session_inputs.py check-unsealed SESSION
session_inputs.py install SESSION STAGING_DIR
```

- [ ] **Step 1: Add sealed-session and complete-generation tests**

Add `test_preflight_refuses_sealed_session_inputs`,
`test_preflight_installs_complete_staged_generation`,
`test_roster_write_refuses_sealed_session`, and
`test_unsealed_legacy_roster_upgrade_remains_supported`. The sealed test writes all
four old inputs plus malformed `r1-evidence.manifest.json`, runs preflight, and asserts
zero roster probes and byte-identical inputs.

- [ ] **Step 2: Run the tests and capture RED**

```bash
cd plugins/review-council
./tests/run-tests.sh sealed_session
./tests/run-tests.sh staged_generation
```

Expected: preflight or `roster.py --write` mutates a sealed live session.

- [ ] **Step 3: Implement path validation, locking, and atomic install**

The lock opens `.session-inputs.lock` with `O_NOFOLLOW`, requires a regular one-link
file owned by the current UID, compares `lstat` with `fstat`, and holds
`fcntl.LOCK_EX`. Treat any directory entry matching `r*-evidence.manifest.json` as a
seal without parsing it. Validate all four byte values before the first write and use
mode-0600 same-directory temporaries plus `os.replace`.

`complete=True` accepts exactly all four inputs and refuses any initialized target.
`complete=False` accepts exactly `roster.json` for an unsealed legacy roster upgrade.

- [ ] **Step 4: Stage preflight output before probing or publication**

Call `check-unsealed` before the paid roster probe. Build all four files in one private
mode-0700 staging directory, use its roster for contract replay, then install once:

```bash
python3 "$HERE/lib/session_inputs.py" install "$WRITE" "$STAGE" \
  || die "cannot install immutable session inputs"
```

- [ ] **Step 5: Route session roster writes through the helper**

When `--write` resolves to a file named `roster.json`, call `assert_unsealed()` before
`build()` and `install_inputs(..., complete=False)` after rendering. Preserve the old
atomic write for every other destination.

- [ ] **Step 6: Run GREEN and neighboring tests**

```bash
cd plugins/review-council
./tests/run-tests.sh sealed_session
./tests/run-tests.sh staged_generation
./tests/run-tests.sh legacy_roster
./tests/run-tests.sh preflight
./tests/run-tests.sh roster_write
python3 -m py_compile scripts/lib/session_inputs.py scripts/lib/roster.py
```

- [ ] **Step 7: Commit**

```bash
git add plugins/review-council/scripts/lib/session_inputs.py \
  plugins/review-council/scripts/rev-preflight.sh \
  plugins/review-council/scripts/lib/roster.py \
  plugins/review-council/tests/t-preflight.sh \
  plugins/review-council/tests/t-roster.sh \
  plugins/review-council/tests/test-costs.tsv
git commit -m "fix(rev): seal evidence session inputs"
```

---

### Task 3: Serialize Evidence Preparation With Input Installation

**Files:**

- Modify: `plugins/review-council/scripts/rev-evidence.py`
- Modify: `plugins/review-council/tests/t-evidence.sh`
- Modify: `plugins/review-council/tests/t-skill.sh`
- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: Task 2's `session_input_lock()` and `validate_standard_inputs()`.
- Produces: one input generation per evidence manifest and exact fresh, initialized,
  or invalid resume behavior in both host skills.

- [ ] **Step 1: Add two lock-order tests and malformed-seal coverage**

`test_prepare_and_input_install_are_serialized` runs install-first and prepare-first
orders with explicit synchronization files. Install-first must hash all new inputs.
Prepare-first must hash all old inputs and the installer must fail without changing a
byte. `test_malformed_manifest_seals_inputs` proves parsing is not required for a seal.

- [ ] **Step 2: Run the race and capture RED**

```bash
cd plugins/review-council
./tests/run-tests.sh input_install_are_serialized
./tests/run-tests.sh malformed_manifest_seals
```

- [ ] **Step 3: Hold one lock through manifest publication**

Split preparation at session resolution:

```python
def prepare(args):
    session = Path(args.session).resolve()
    with session_input_lock(session):
        validate_standard_inputs(session, require_all=True)
        return _prepare_locked(args, session)
```

Move the existing body from repository construction through manifest publication into
`_prepare_locked`. Do not call `assert_unsealed()` because later panels read already
sealed inputs.

- [ ] **Step 4: Make resume behavior exact in both host skills**

Require exactly these states:

```text
fresh: none of the four inputs exists, so preflight may run once
initialized: all four safe inputs exist, so validate and reuse them without probing
invalid: a partial or unsafe set exists, so stop incomplete and use a fresh session
```

- [ ] **Step 5: Run GREEN and neighbors**

```bash
cd plugins/review-council
./tests/run-tests.sh input_install_are_serialized
./tests/run-tests.sh malformed_manifest_seals
./tests/run-tests.sh evidence_contract
./tests/run-tests.sh skill
python3 -m py_compile scripts/rev-evidence.py
```

- [ ] **Step 6: Commit**

```bash
git add plugins/review-council/scripts/rev-evidence.py \
  plugins/review-council/tests/t-evidence.sh \
  plugins/review-council/tests/t-skill.sh \
  plugins/review-council/skills/rev/SKILL.md \
  plugins/review-council/codex-skills/rev/SKILL.md \
  plugins/review-council/tests/test-costs.tsv
git commit -m "fix(rev): serialize evidence session inputs"
```

---

### Task 4: Promote Red-Team and Cross-Boundary Coverage

**Files:**

- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Modify: `plugins/review-council/tests/t-skill.sh`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**

- Consumes: current adaptive and numeric lens schedules.
- Produces: one composite red-team assignment in every code panel, one conditional
  full red-team panel in high-risk adaptive reviews, and promoted compatibility,
  recovery, security, and integration emphases without a generic panel cap.

- [ ] **Step 1: Add exact static contract tests**

For both host skills, assert:

```text
one existing seat receives composite red-team emphasis in every code panel
the emphasis never replaces the canonical lens or bundle
numeric mode adds no panel for the composite assignment
large, high-risk, important, or explicit adaptive review may run one full red-team panel before planning
the four full-panel adversarial assignments are distinct
compatibility, recovery, security, and integration routing is explicit
ordinary stopping rules remain unchanged
```

- [ ] **Step 2: Run and capture RED**

```bash
cd plugins/review-council
./tests/run-tests.sh skill
```

- [ ] **Step 3: Add the shared coverage contract to both skills**

Use the exact four release-quality compositions from the spec. Select the composite
seat deterministically from roster order and rotate it across panels so the same model
does not own every adversarial check. A full red-team panel runs before planning, joins
the same initial finding clusters, and does not itself grant another correction cycle.

Do not add `rev-convergence.py`, change numeric continuation, or change read-only panel
counts.

- [ ] **Step 4: Update user-facing schedule documentation**

Change README launch-count examples only where the optional full red-team panel changes
the adaptive count. Explain that ordinary panels gain the composite assignment for
zero extra calls. Add one compact 0.4.4 changelog bullet.

- [ ] **Step 5: Run GREEN**

```bash
cd plugins/review-council
./tests/run-tests.sh skill
```

- [ ] **Step 6: Commit**

```bash
git add plugins/review-council/skills/rev/SKILL.md \
  plugins/review-council/codex-skills/rev/SKILL.md \
  plugins/review-council/tests/t-skill.sh README.md CHANGELOG.md
git commit -m "feat(rev): promote adversarial panel coverage"
```

---

### Task 5: Implement the Stable Release Authority

**Files:**

- Create: `scripts/verify-release-lane.py`
- Create: `tests/test_release_lane.py`

**Interfaces:**

- Consumes: a clean Git candidate, signed stable tag, installed stable plugin,
  stable-engine review sessions, frozen-tree verifier receipt, and selected canary
  receipts.
- Produces:

```text
verify-release-lane.py requirements --root ROOT --candidate-commit SHA --stable-tag TAG
verify-release-lane.py record-review --root ROOT --candidate-commit SHA --stable-plugin PATH --stable-tag TAG --session SESSION --new-p0 N --new-p1 N --open-p0 N --open-p1 N --out RECEIPT
verify-release-lane.py run-canary --root ROOT --stable-tag TAG --id ID --out RECEIPT -- COMMAND [ARG ...]
verify-release-lane.py certify --root ROOT --candidate-commit SHA --stable-plugin PATH --stable-tag TAG --review RECEIPT [--review RECEIPT] --verification-receipt PATH --canary ID=PATH --out RECEIPT
```

Canonical review decision contains:

```json
{
  "schema_version": 1,
  "stable": {"tag": "review-council--v0.4.3", "commit": "<sha>", "tree": "<tree>", "plugin_identity": "<sha256>"},
  "candidate": {"version": "0.4.4", "commit": "<sha>", "tree": "<tree>"},
  "review": {"session_identity": "<sha256>", "new_p0": 0, "new_p1": 0, "open_p0": 0, "open_p1": 0},
  "status": "clean"
}
```

- [ ] **Step 1: Add stable and candidate identity tests**

Create temporary Git repositories and installed plugin copies. Cover signed-tag command
failure, tag commit mismatch, byte mutation, mode mutation, forged version, dirty
candidate, moved `HEAD`, equal or lower candidate version, unsafe paths, and exact
idempotent receipt publication.

- [ ] **Step 2: Run identity tests and capture RED**

```bash
python3 -m unittest tests.test_release_lane.ReleaseLaneIdentityTests -v
```

Expected: import or executable missing.

- [ ] **Step 3: Implement canonical identity and receipt publication**

Use only the standard library. Enumerate the stable tag subtree with
`git ls-tree -rz`, read blobs with `git cat-file blob`, and compare kind, relative path,
mode, size, and SHA-256 with the installed plugin. Reject extra installed files except
documented generated cache metadata outside the plugin root. Run `git verify-tag` and
resolve `TAG^{commit}` explicitly.

Use canonical JSON with sorted keys and compact separators. Validate direct paths and
regular one-link receipts. Publish with a same-directory mode-0600 temporary and
collision refusal.

- [ ] **Step 4: Add generation and stable-session tests**

Cover a clean first review, a correction-required first review, a clean delta on a new
commit, open P0/P1, infrastructure marker, stable checker failure, wrong executor,
roster mutation, contract mutation, missing coverage, coverage hash mutation, and
reviewed tree mismatch.

- [ ] **Step 5: Implement `record-review`**

Read session `scope.env` without shell evaluation. Require its root to match the
candidate root and use its base and `roster.json` to invoke the installed stable
`rev-contract-check.py --verify-only`. Require the matching contract receipt's
`identity.executor.plugin` to equal the verified stable path.

Validate `coverage-head.json`, its named coverage receipt, all receipt hashes, the
latest reviewed snapshot tree, `state.json`, and `findings.md`. Hash the complete
decision artifact set into the review record. Counts must be nonnegative integers.
All four zero counts record `clean`; any new or open P0/P1 records
`correction-required`. A session stop marker records `infrastructure-blocked` and
accepts no product counts. The final certificate, not this command, decides whether a
first correction-required receipt is followed by one clean delta.

- [ ] **Step 6: Add canary selection and execution tests**

Cover each trigger row, shared-auditor fan-out, no-trigger behavior, unknown triggering
paths, exact command-vector execution, nonzero exit, output limit, signal termination,
stale path identity, malformed receipt, receipt collision, missing required receipt,
and unknown extra canary.

- [ ] **Step 7: Implement `requirements`, `run-canary`, and trigger identity**

Hardcode the spec matrix as data. Derive changed paths from `stable.tag..candidate`
with `git diff --name-only -z --no-renames`. `requirements` prints their canary IDs as
canonical JSON. `run-canary` accepts only a currently required ID, invokes the exact
argument vector without a shell, captures stdout and stderr to a private bounded log,
terminates the process group on timeout, and writes a receipt only for exit 0. Bind the
ID, trigger path identities, command vector, log hash, and any evidence paths emitted
in canonical JSON by the command.

- [ ] **Step 8: Add deterministic receipt and final certification tests**

Cover verifier tree mismatch, key mismatch, missing command, failed or truncated log,
log hash mismatch, nonregular log, dirty or moved final candidate, stale stable bundle,
zero or three review receipts, an unnecessary second review, same-commit delta, unclean
latest review, and successful one- and two-review final receipts.

- [ ] **Step 9: Implement `certify`**

Recompute the final clean candidate identity. Validate the verifier receipt schema,
`identity.tree`, `key`, exact default command set, every log path, size, hash, terminal
JSON footer, and exit 0. Require the latest stable review tree to equal the final Git
tree, all and only current required canaries, and no session stop. Accept one or two
review decision receipts only. One clean initial receipt succeeds. One
`correction-required` initial receipt requires one later clean receipt on a different
candidate commit. Reject every other transition. Write a receipt binding the full
candidate, stable, review, verification, and canary hashes.

- [ ] **Step 10: Run GREEN and commit**

```bash
python3 -m unittest tests.test_release_lane -v
python3 -m py_compile scripts/verify-release-lane.py
git diff --check
git add scripts/verify-release-lane.py tests/test_release_lane.py
git commit -m "feat(release): verify with the previous stable council"
```

---

### Task 6: Document, Pressure-Test, Certify, and Release 0.4.4

**Files:**

- Create: `docs/release.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `tasks/todo.md`
- Modify: `.superpowers/sdd/2026-09-15-review-council-convergence-repair/progress.md`

**Interfaces:**

- Consumes: Tasks 1-5 and the installed exact 0.4.3 plugin at the verified cache path.
- Produces: documented release procedure, pressure-test receipts, one bounded stable
  review lane, green CI, squash-merged PR #6, release `review-council--v0.4.4`, and
  verified fresh-session discovery.

- [ ] **Step 1: Document the executable operator sequence**

The document includes these commands with real arguments:

```bash
python3 scripts/verify-release-lane.py requirements --root . \
  --candidate-commit "$(git rev-parse HEAD)" \
  --stable-tag review-council--v0.4.3
python3 scripts/verify-review-council.py --root .
python3 scripts/verify-release-lane.py certify --root . \
  --candidate-commit "$(git rev-parse HEAD)" \
  --stable-plugin "$STABLE_PLUGIN" \
  --stable-tag review-council--v0.4.3 \
  --review "$FINAL_REVIEW_RECEIPT" \
  --verification-receipt "$VERIFY_RECEIPT" \
  --canary host-claude="$CLAUDE_CANARY" \
  --canary host-codex="$CODEX_CANARY" \
  --out "$RELEASE_RECEIPT"
```

It states that `record-review` is run immediately after each stable read-only review,
before another review launch, and that a nonclean second receipt ends the lane.

- [ ] **Step 2: Add release documentation tests or static assertions**

Assert that README links `docs/release.md`, that the document names N-1 review,
P0/P1-only repairs, the two-generation cap, candidate non-self-review, deterministic
gate, targeted canaries, squash merge, signed tag, and fresh-session discovery.

- [ ] **Step 3: Pressure-test the edited host contracts**

Run the existing behavioral pressure harness against normal, read-only, and stack
scenarios for each host. Record canary receipts through `run-canary`. A scenario fails
if it omits the composite red-team assignment, invents a third release generation,
uses candidate scripts for stable review, or treats P2/P3 as release blockers.

- [ ] **Step 4: Run focused and complete deterministic gates**

```bash
cd plugins/review-council
./tests/run-tests.sh audit_stop
./tests/run-tests.sh sealed_session
./tests/run-tests.sh input_install_are_serialized
./tests/run-tests.sh skill
cd ../..
python3 -m unittest discover -s tests -v
python3 scripts/verify-review-council.py --root .
```

Inspect every log for `error`, `ERROR`, and failed tallies. Require the expected Codex
bundle manifests and verifier receipt to exist.

- [ ] **Step 5: Run the stable 0.4.3 release lane**

Record the required canary set against the exact installed 0.4.3 bundle. Use its `rev`
skill and scripts for one read-only complete release panel with the four composite
assignments. Verify and apply only P0/P1. Write the immutable generation-1 decision
receipt immediately. If code changed, rerun focused and full deterministic gates, then
run one stable read-only delta panel and write generation 2. Do not launch another
panel if generation 2 is nonclean or infrastructure-blocked.

- [ ] **Step 6: Certify the final candidate and commit records**

Run required canaries, certify, update the task review with exact receipt paths and
hashes, scan for forbidden Unicode, and create a new documentation commit without
amending.

- [ ] **Step 7: Push and wait for green CI**

Confirm attribution flags are false, push `feat/pr-review-post`, read every configured
gate, and wait until all required checks for PR #6 are successful. Fix P0/P1 or real CI
regressions only; do not start another release review generation.

- [ ] **Step 8: Squash-merge PR #6**

```bash
gh pr merge 6 --squash
```

Do not use `--admin`. Read back the merged state and merge commit.

- [ ] **Step 9: Create and publish the signed 0.4.4 release**

From a clean checkout of the merged commit, verify both manifests, changelog, tag
absence, and complete gate receipt. Create the signed annotated tag and GitHub release:

```bash
git tag -s review-council--v0.4.4 -m "review-council 0.4.4" "$MERGE_COMMIT"
git push origin review-council--v0.4.4
git verify-tag review-council--v0.4.4
gh release create review-council--v0.4.4 --verify-tag \
  --title "review-council 0.4.4" --notes-file "$RELEASE_NOTES"
```

- [ ] **Step 10: Reinstall and verify discovery from a fresh session**

Follow `plugin-creator`: read the marketplace name, update the cachebuster, reinstall
the released plugin, then start fresh Claude Code and Codex sessions. Verify both hosts
discover `rev` and `stack`, both installed manifests say 0.4.4, and installed plugin
file/mode identity matches the released tag. This smoke check does not reopen release
review.

---

## Plan Self-Review

- Spec coverage: every global safety, normal-review, release identity, bounded
  generation, deterministic gate, canary, and publication requirement maps to a task.
- Placeholder scan: no TBD, TODO, or unspecified implementation step remains.
- Interface consistency: Task 3 consumes Task 2's exact lock helpers; Task 6 consumes
  Task 5's four immutable receipt commands and transition validation.
- Scope check: the release authority is one independent repository tool; normal review
  keeps its existing orchestrator and receives only small boundary changes.
