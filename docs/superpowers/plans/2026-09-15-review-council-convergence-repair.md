# Review Council Convergence Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Review Council run either certify or stop after one bounded P0/P1 correction generation, while preserving immutable evidence inputs, session-wide audit stops, red-team coverage, and fail-closed PR publication.

**Architecture:** Add two small authorities beside the existing skill-driven orchestrator. `session_inputs.py` serializes and seals the four preflight inputs, while `rev-convergence.py` owns panel authorization, verification triage, terminal states, and completion receipts. The host skills still choose review lenses and apply fixes, but prompt rendering, provider reservation, PR publication, and stack completion enforce the authority's immutable receipts.

**Tech Stack:** Bash 3.2-compatible shell, Python 3 standard library, Git, GitHub CLI, existing shell test harness, existing `unittest` suite, Claude Code plugin manifests, Codex plugin manifests.

**Spec:** `docs/superpowers/specs/2026-09-15-review-council-convergence-repair-design.md`

## Global Constraints

- Adaptive code review gets one initial fix generation and at most one P0/P1 correction generation.
- A second verification with any new or open P0/P1 records `nonconvergent` and blocks every later semantic panel, publication, and success report.
- P2 and P3 findings remain reportable but never consume or extend the correction allowance.
- Missing tests are P2 unless a behavioral regression proves reachable incorrectness or a broken public contract.
- Every code review has one composite red-team seat assignment; large, high-risk, important, or explicitly requested adaptive reviews may add exactly one full red-team panel before planning.
- Full red-team assignments are attacker and trust boundaries, corruption and recovery, concurrency and exhaustion, and compatibility and consumer contracts.
- Regression and integration always receive full-state verification; compatibility, recovery, and security coverage are routed into existing seats without adding generations.
- Evidence manifests seal `scope.env`, `roster.json`, `files.txt`, and `untracked.txt`, including when a manifest is malformed.
- A hard evidence-audit failure stops the whole session. The user must start a fresh session.
- Write-capable legacy sessions without convergence state cannot resume under this release.
- Read-only reviews publish a `reported` receipt rather than a `clean` receipt, so findings remain reportable without claiming they were fixed.
- Quota fallback uses one fresh sibling session, inherits the parent logical authorization, and cannot reset the correction allowance.
- Review roster remains exactly Sol, Terra, Opus, and Sonnet at maximum effort. Astra and Grok remain excluded.
- Only P0 and P1 findings block this release. Record P2 and P3 without expanding the release scope.
- Do not add dependencies, weaken evidence checks, lower any gate, or alter the canonical GitHub review template.
- Match existing comment density in each edited language. Keep comments for invariants and traps, not narration.
- Do not use U+2013 or U+2014 in source, tests, docs, commits, or release text.
- Never amend commits. Every task lands as a new, attribution-free commit.

---

## File and Responsibility Map

| File | Responsibility |
| --- | --- |
| `plugins/review-council/scripts/lib/session_inputs.py` | Safe lock, seal detection, validation, and atomic installation for the four session inputs. |
| `plugins/review-council/scripts/rev-convergence.py` | Locked convergence state machine and immutable authorization, triage, reporting, and certification receipts. |
| `plugins/review-council/scripts/lib/rev-attempt.py` | Session-wide hard-audit stop marker and provider reservation refusal. |
| `plugins/review-council/scripts/rev-preflight.sh` | Stage all preflight inputs, refuse sealed or initialized sessions before probes, then install one complete generation. |
| `plugins/review-council/scripts/lib/roster.py` | Route session `roster.json` writes through the shared input authority. |
| `plugins/review-council/scripts/rev-evidence.py` | Hold the session-input lock through manifest publication and add the explicit `red-team` phase. |
| `plugins/review-council/scripts/rev-prompt.sh` | Validate and bind a canonical convergence authorization before publishing a prompt. |
| `plugins/review-council/scripts/rev-seat.sh` | Revalidate prompt and authorization immediately before reserving a paid call. |
| `plugins/review-council/scripts/rev-pr-review.py` | Require a matching completion receipt during render, publish, stack validate, and stack finalize. |
| `plugins/review-council/scripts/stack.sh` | Certify each authoritative leg before report promotion, including `NO_PUSH=1`. |
| `plugins/review-council/skills/rev/SKILL.md` | Claude Code orchestration contract, bounded transitions, red-team routing, and resume rules. |
| `plugins/review-council/codex-skills/rev/SKILL.md` | Codex orchestration contract matching the Claude Code behavior. |
| `plugins/review-council/skills/stack/SKILL.md` | Claude Code per-leg convergence and partial-stack contract. |
| `plugins/review-council/codex-skills/stack/SKILL.md` | Codex per-leg convergence and partial-stack contract. |
| `plugins/review-council/skills/rev/POLICY.md` | Always-loaded stop and certification invariants. |
| `plugins/review-council/tests/t-convergence.sh` | State-machine, receipt, tamper, budget, and fallback behavior. |
| Existing `tests/t-*.sh` files | Focused regressions at each integration boundary. |
| `plugins/review-council/tests/test-costs.tsv` | Runtime hints for every new exact shell test. |
| `CHANGELOG.md` and plugin manifests | Release notes and the already-reserved `0.4.4` version. |

---

### Task 1: Stop the Entire Session After a Hard Evidence Audit

**Files:**

- Modify: `plugins/review-council/tests/t-read-bounds.sh:2181`
- Modify: `plugins/review-council/tests/t-seat.sh:145`
- Modify: `plugins/review-council/scripts/lib/rev-attempt.py`
- Modify: `plugins/review-council/scripts/rev-seat.sh:139-170`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: existing `rev-attempt.py check|reserve|stop SESSION PANEL` commands and evidence audit diagnostics.
- Produces: `SESSION/attempts/session.stopped.json`, written under the existing attempt lock, and a stable `start a fresh review session` refusal from every later `check` or `reserve`.

- [ ] **Step 1: Add failing cross-label and concurrency regressions**

Add `test_session_audit_stop_crosses_panel_labels` and `test_session_audit_stop_serializes_reservations`. The first must stop `r1`, attempt `r2`, and assert zero additional shim calls and unchanged invalid result and audit hashes. The second must race `stop` against two new-label reservations and assert no reservation is created after the stop marker.

```bash
python3 "$SCRIPTS/lib/rev-attempt.py" stop "$session" r1 --reason "hard evidence audit failed"
before=$(sha256sum "$session/r1-codex-sol.invalid.json" "$session/r1-codex-sol.audit.json")
"$SCRIPTS/rev-seat.sh" codex-sol "$session" r2 "$session/r2-codex-sol.prompt.md" \
  >"$T/session-stop.out" 2>"$T/session-stop.err"
assert_eq "a different label cannot bypass the hard stop" "$?" 2
assert_eq "the stopped session launches no provider" "$(wc -l < "$SHIM_ARGS_FILE")" 0
assert_eq "hard-audit evidence stays byte-identical" \
  "$(sha256sum "$session/r1-codex-sol.invalid.json" "$session/r1-codex-sol.audit.json")" "$before"
assert_grep "the refusal requires a fresh session" "$T/session-stop.err" \
  'hard evidence audit failed.*fresh review session'
```

- [ ] **Step 2: Run the focused tests and confirm the bypass is real**

Run: `cd plugins/review-council && ./tests/run-tests.sh session_audit_stop`

Expected: FAIL because `rev-attempt.py` scans only the current panel prefix and `r2` reserves a call.

- [ ] **Step 3: Add the locked session stop marker**

Implement these exact internal helpers in `rev-attempt.py`:

```python
SESSION_STOP = "session.stopped.json"

def session_stop_path(session: Path) -> Path:
    return session / "attempts" / SESSION_STOP

def prior_hard_audit(session: Path) -> Path | None:
    marker = session_stop_path(session)
    if marker.exists() or marker.is_symlink():
        return marker
    for audit in sorted(session.glob("r*-*.audit.json")):
        if hard_audit_failure(audit):
            return audit
    return None
```

Change `stop` to write the existing panel diagnostic and immutable session marker while the same lock is held. Change every `check` and `reserve` to call the session-wide form before inspecting per-seat attempt state. Preserve legacy advisory audits by making `hard_audit_failure()` accept only the existing hard-invalid schema and result.

- [ ] **Step 4: Update the wrapper diagnostic**

Replace every instruction to choose a fresh panel label with one stable message:

```text
review session stopped after a hard evidence audit failure; preserve this session and start a fresh review session
```

Do not delete, rename, or overwrite the invalid result or audit files.

- [ ] **Step 5: Run focused and neighboring attempt tests**

Run: `cd plugins/review-council && ./tests/run-tests.sh audit_stop && ./tests/run-tests.sh narrow_seat && ./tests/run-tests.sh seat`

Expected: all selected tasks PASS, no provider shim call appears after the stop marker, and legacy advisory tests still PASS.

- [ ] **Step 6: Commit the independently useful stop repair**

```bash
git add plugins/review-council/scripts/lib/rev-attempt.py \
  plugins/review-council/scripts/rev-seat.sh \
  plugins/review-council/tests/t-read-bounds.sh \
  plugins/review-council/tests/t-seat.sh \
  plugins/review-council/tests/test-costs.tsv
git commit -m "fix(rev): stop sessions after hard audit failures"
```

---

### Task 2: Seal and Install Session Inputs as One Generation

**Files:**

- Create: `plugins/review-council/scripts/lib/session_inputs.py`
- Modify: `plugins/review-council/scripts/rev-preflight.sh:87-180`
- Modify: `plugins/review-council/scripts/lib/roster.py:1352-1398`
- Modify: `plugins/review-council/tests/t-preflight.sh`
- Modify: `plugins/review-council/tests/t-roster.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: session directory and bytes for `scope.env`, `roster.json`, `files.txt`, and `untracked.txt`.
- Produces `STANDARD_INPUTS = ("scope.env", "roster.json", "files.txt", "untracked.txt")`, `LOCK_NAME = ".session-inputs.lock"`, `SessionInputsError`, and `SessionInputsSealedError`.
- Produces `find_evidence_seal(session: Path) -> Path | None`, `session_input_lock(session: Path) -> Iterator[Path]`, `assert_unsealed(session: Path) -> None`, `validate_standard_inputs(session: Path, *, require_all: bool) -> dict[str, bytes]`, and `install_inputs(session: Path, values: Mapping[str, bytes], *, complete: bool) -> None`.

CLI contract:

```text
session_inputs.py check-unsealed SESSION
session_inputs.py install SESSION STAGING_DIR
```

- [ ] **Step 1: Add failing sealed-preflight and sealed-roster tests**

Add `test_preflight_refuses_sealed_session_inputs`, `test_preflight_installs_complete_staged_generation`, `test_roster_write_refuses_sealed_session`, and `test_unsealed_legacy_roster_upgrade_remains_supported`.

```bash
printf old > "$session/roster.json"
printf old > "$session/scope.env"
printf old > "$session/files.txt"
printf old > "$session/untracked.txt"
printf malformed > "$session/r1-evidence.manifest.json"
before=$(sha256sum "$session"/{roster.json,scope.env,files.txt,untracked.txt})
RSTUB_CALLS="$T/sealed-probes" "$SCRIPTS/rev-preflight.sh" branch --write "$session"
assert_eq "sealed preflight fails before probing" "$?" 1
assert_exit "sealed preflight makes no roster call" 0 test ! -e "$T/sealed-probes"
assert_eq "sealed input bytes are unchanged" \
  "$(sha256sum "$session"/{roster.json,scope.env,files.txt,untracked.txt})" "$before"
```

- [ ] **Step 2: Run the focused tests and confirm inputs are currently mutable**

Run: `cd plugins/review-council && ./tests/run-tests.sh sealed_session && ./tests/run-tests.sh staged_generation`

Expected: FAIL because preflight probes and overwrites the live session and `roster.py --write` bypasses evidence sealing.

- [ ] **Step 3: Implement strict path and lock validation**

Create `session_inputs.py`. `session_input_lock()` must open the canonical lock with `O_NOFOLLOW`, require a regular one-link file owned by the current UID, compare `lstat` and `fstat` device and inode values, and hold `fcntl.LOCK_EX` until exit. `find_evidence_seal()` must treat any directory entry matching `r*-evidence.manifest.json` as a seal without parsing it. Reject symlinks, hardlinks, nonregular inputs, missing required inputs, partial initialized sessions, and redirected session paths.

`install_inputs(values, complete=True)` validates all four byte values before its first write, publishes same-directory mode-0600 temporaries, then runs four `os.replace` calls while holding the lock. It refuses any existing standard input because initialized sessions resume rather than rerun preflight. `complete=False` accepts exactly `{"roster.json": bytes}` for an unsealed legacy roster upgrade.

- [ ] **Step 4: Stage preflight output and refuse before paid work**

In `rev-preflight.sh`, call `check-unsealed "$WRITE"` before the roster probe. Build all four standard inputs under one private mode-0700 staging directory, use the staged roster for contract replay, then run:

```bash
python3 "$HERE/lib/session_inputs.py" install "$WRITE" "$STAGE" \
  || die "cannot install immutable session inputs"
```

Print the successful preflight summary only after installation. Keep quota fallback's fresh-empty-directory rule.

- [ ] **Step 5: Route session roster writes through the helper**

When `--write` resolves to `roster.json`, call `assert_unsealed(write.parent)` before `build()` so a sealed target spends no probes. After building, call:

```python
install_inputs(write.parent, {"roster.json": text.encode("utf-8")}, complete=False)
```

Preserve the existing atomic `.new` behavior for destinations not named `roster.json`.

- [ ] **Step 6: Run focused preflight and roster tests**

Run: `cd plugins/review-council && ./tests/run-tests.sh sealed_session && ./tests/run-tests.sh staged_generation && ./tests/run-tests.sh legacy_roster && ./tests/run-tests.sh preflight && ./tests/run-tests.sh roster_write`

Expected: all selected tasks PASS; sealed paths make zero probe calls; successful preflight installs exactly four complete inputs.

- [ ] **Step 7: Commit the input authority**

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

- Modify: `plugins/review-council/scripts/rev-evidence.py:24-30,4146-4497`
- Modify: `plugins/review-council/tests/t-evidence.sh`
- Modify: `plugins/review-council/tests/t-skill.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: `session_input_lock(session)` and `validate_standard_inputs(session, require_all=True)` from Task 2.
- Produces: manifest publication that observes one complete input generation, plus host resume language that skips preflight for a complete initialized session.

- [ ] **Step 1: Add the two deterministic lock-order tests**

Add `test_prepare_and_input_install_are_serialized` and `test_malformed_manifest_seals_inputs`.

The race test must use two explicit synchronization files inside the test fixture. In install-first order, evidence preparation must hash all four new inputs. In prepare-first order, the manifest must hash all four old inputs and the installer must fail without changing any byte. No assertion may depend on process completion order.

```python
assert set(manifest["inputs"]) >= {
    "scope.env", "roster.json", "files.txt", "untracked.txt"
}
assert {manifest["inputs"][name] for name in expected_new} == expected_new_hashes
```

- [ ] **Step 2: Run the race test and confirm a mixed generation is possible**

Run: `cd plugins/review-council && ./tests/run-tests.sh input_install_are_serialized`

Expected: FAIL because `prepare()` reads inputs without the installation lock.

- [ ] **Step 3: Hold the lock through manifest publication**

Split `prepare()` exactly at its session resolution boundary:

```python
def prepare(args):
    session = Path(args.session).resolve()
    with session_input_lock(session):
        validate_standard_inputs(session, require_all=True)
        return _prepare_locked(args, session)

def _prepare_locked(args, session):
    repo = Repository(session)
```

Indent the current `prepare()` body from repository construction through `print(manifest_path)` verbatim under `_prepare_locked()`. The wrapper must hold the lock until after `publish(manifest_path, encoded(manifest))` returns.

Do not call `assert_unsealed()` from evidence preparation. Existing manifests are supposed to seal inputs while allowing later panels to read them.

- [ ] **Step 4: Make resume behavior executable in both host skills**

At session selection, require exactly one of these states:

```text
fresh: none of the four standard inputs exists, so preflight may run once
initialized: all four regular one-link inputs exist, so validate and reuse them without a provider probe
invalid: only some inputs exist or any input is unsafe, so stop incomplete and require a fresh session
```

Keep quota fallback on a fresh sibling. Add static assertions that both host skills explicitly say an initialized session never reruns preflight or provider probing.

- [ ] **Step 5: Run evidence, resume, and preflight neighbors**

Run: `cd plugins/review-council && ./tests/run-tests.sh input_install_are_serialized && ./tests/run-tests.sh malformed_manifest_seals && ./tests/run-tests.sh evidence_contract && ./tests/run-tests.sh skill`

Expected: all selected tasks PASS and neither lock ordering yields a mixed manifest.

- [ ] **Step 6: Commit the serialization boundary**

```bash
git add plugins/review-council/scripts/rev-evidence.py \
  plugins/review-council/tests/t-evidence.sh \
  plugins/review-council/tests/t-skill.sh \
  plugins/review-council/tests/test-costs.tsv \
  plugins/review-council/skills/rev/SKILL.md \
  plugins/review-council/codex-skills/rev/SKILL.md
git commit -m "fix(rev): serialize evidence session inputs"
```

---

### Task 4: Implement the Convergence State Machine

**Files:**

- Create: `plugins/review-council/scripts/rev-convergence.py`
- Create: `plugins/review-council/tests/t-convergence.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: immutable standard inputs, evidence manifests, coverage receipts, `coverage-head.json`, and the session-wide audit marker.
- Produces the approved public CLI:

```text
rev-convergence.py init SESSION --mode adaptive|numeric|read-only [--min-rounds N] [--full-red-team REASON]
rev-convergence.py init-fallback CHILD_SESSION --parent-session PARENT_SESSION --authorization PATH
rev-convergence.py authorize SESSION LABEL --kind discovery|risk|red-team|plan|verification|repair --manifest PATH
rev-convergence.py record SESSION LABEL --coverage-receipt PATH --new-p0 N --new-p1 N --open-p0 N --open-p1 N --origin-original N --origin-fix-of-fix N --origin-unknown N --origin-infrastructure N
rev-convergence.py certify SESSION
rev-convergence.py status SESSION
```

- Produces private read-only validation used by Tasks 5 and 7:

```text
rev-convergence.py check-authorization SESSION LABEL --authorization PATH
rev-convergence.py check-completion SESSION [--tree TREE] [--allow-reported]
```

- [ ] **Step 1: Add failing initialization and immutable-receipt tests**

Add tests for exact idempotent `init`, mismatched mode and minimum, unsafe paths, receipt replacement, and state tampering.

Use this exact state shape:

```json
{
  "schema_version": 1,
  "mode": "adaptive",
  "min_rounds": null,
  "session_identity_sha256": "<sha256>",
  "inputs": {
    "scope.env": "<sha256>",
    "roster.json": "<sha256>",
    "files.txt": "<sha256>",
    "untracked.txt": "<sha256>"
  },
  "status": "initialized",
  "generation": 0,
  "origin_snapshot_tree": null,
  "authorizations": {},
  "records": {},
    "latest_verification": null,
    "full_red_team_reason": null,
    "fallback_parent": null
}
```

- [ ] **Step 2: Run initialization tests and verify the command is absent**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence_init`

Expected: FAIL with an absent `scripts/rev-convergence.py` command.

- [ ] **Step 3: Implement canonical JSON, path checks, and locked state updates**

Use `json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"` for hashes and receipts. Store state via same-directory temporary plus `os.replace` while holding `SESSION/.convergence.lock` with the same no-follow, owner, inode, and one-link validation as the input lock. Require every receipt path to be a regular one-link direct child of the session and reject an existing receipt whose bytes differ.

`session_identity_sha256` hashes this canonical object:

```python
{
    "schema_version": 1,
    "mode": mode,
    "min_rounds": min_rounds,
    "inputs": input_hashes,
}
```

- [ ] **Step 4: Add failing authorization-budget tests**

Cover discovery 1, risk 1, conditional red-team 1, plan 2, verification 2, exact-repeat idempotence, changed-repeat refusal, wrong label, wrong phase, stale manifest, clean-state refusal, terminal-state refusal, and numeric minimum accounting.

Authorization receipts must contain:

```json
{
  "schema_version": 1,
  "session_identity_sha256": "<sha256>",
  "label": "3v",
  "kind": "verification",
  "generation": 1,
  "manifest": {"name": "r3v-evidence.manifest.json", "sha256": "<sha256>"},
  "manifest_phase": "verification",
  "base_tree": "<git tree>",
  "snapshot_tree": "<git tree>",
  "inputs": {"scope.env": "<sha256>", "roster.json": "<sha256>", "files.txt": "<sha256>", "untracked.txt": "<sha256>"}
}
```

- [ ] **Step 5: Implement exact authorization transitions**

Enforce this table in data, not label spelling:

```python
KIND_PHASE = {
    "discovery": "discovery",
    "risk": "risk",
    "red-team": "red-team",
    "plan": "plan",
    "verification": "verification",
    "repair": "repair",
}
MAX_GENERATIONS = {
    "discovery": 1,
    "risk": 1,
    "red-team": 1,
    "plan": 2,
    "verification": 2,
}
TERMINAL = {"clean", "reported", "infrastructure-blocked", "nonconvergent", "certified"}
```

The second plan and verification require `status == "correction-required"`. `--full-red-team` accepts one nonempty, single-line reason and is present only when the host classifies the review as high-risk, large, important, or explicit. Red-team authorization requires that initialization field, never a label guess. Repair authorizations retain the existing one-seat coverage repair limit and inherit their parent semantic generation.

`init-fallback` validates the parent authorization, requires the child session's source identity to match the parent through the existing `same-source` receipt, and stores the parent session identity, authorization hash, panel kind, and generation. It authorizes only a replacement of that same logical panel and can be called once.

Initial discovery, risk, red-team, and optional plan authorizations are legal only before the first verification. The first verification record moves the state to `clean`, `correction-required`, or `infrastructure-blocked`. A correction plan authorization moves `correction-required` to `correction`; only the second verification is then legal. `certify` is the only transition from `clean` or `reported` to `certified`.

For numeric mode, count every recorded non-plan code panel toward `min_rounds`, designate the final requested code panel as `verification`, and reject certification until the count reaches the exact minimum. A correction plan and verification may follow only when that final requested panel records P0/P1.

- [ ] **Step 6: Add failing triage and certification tests**

Cover balanced origins, unbalanced origins, P2/P3-only clean state, unknown P0/P1 blocking, first verification correction, second verification nonconvergence, infrastructure terminal state, clean certification, stale coverage head, hard-audit marker refusal, and read-only reporting.

Triage receipts contain:

```json
{
  "schema_version": 1,
  "session_identity_sha256": "<sha256>",
  "label": "3v",
  "generation": 1,
  "authorization": {"name": "r3v-convergence.authorization.json", "sha256": "<sha256>"},
  "coverage_receipt": {"name": "r3v-coverage.receipt.json", "sha256": "<sha256>"},
  "manifest": {"name": "r3v-evidence.manifest.json", "sha256": "<sha256>"},
  "snapshot_tree": "<git tree>",
  "results": ["r3v-codex-sol.result.json"],
  "counts": {
    "new": {"P0": 0, "P1": 0},
    "open": {"P0": 0, "P1": 0},
    "origin": {"original-scope": 0, "fix-of-fix": 0, "unknown": 0, "review-infrastructure": 0}
  },
  "decision": "clean"
}
```

Origin counts must equal `new.P0 + new.P1`. Infrastructure origin greater than zero records `infrastructure-blocked`. The first write-capable verification records `clean` or `correction-required`; the second records `clean` or `nonconvergent`. Read-only records `reported`, may retain open findings, and never unlocks plan or repair.

- [ ] **Step 7: Implement certification and reporting receipts**

`certify` for adaptive and numeric modes requires the latest verification decision `clean`, zero open P0/P1, a matching `coverage-head.json`, matching snapshot tree, unchanged input hashes, and no hard-audit stop. It writes `convergence.receipt.json` with decision `clean`.

For read-only mode it requires the requested panel count and coverage receipt, then writes `convergence.receipt.json` with decision `reported`, the open counts, and the same immutable bindings. This implements the spec's reportability requirement without treating findings as fixed.

- [ ] **Step 8: Prove every state transition and terminal refusal**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence`

Expected: all convergence tests PASS, including that a second-verification P1 makes every later `authorize` fail without changing state.

- [ ] **Step 9: Commit the convergence authority**

```bash
git add plugins/review-council/scripts/rev-convergence.py \
  plugins/review-council/tests/t-convergence.sh \
  plugins/review-council/tests/test-costs.tsv
git commit -m "feat(rev): bound review convergence"
```

---

### Task 5: Enforce Authorization at Prompt and Provider Boundaries

**Files:**

- Modify: `plugins/review-council/scripts/rev-evidence.py:2815-2920,4146-4497,4841`
- Modify: `plugins/review-council/scripts/rev-prompt.sh:2-199`
- Modify: `plugins/review-council/scripts/rev-seat.sh:2-170`
- Modify: `plugins/review-council/tests/t-prompt-evidence.sh`
- Modify: `plugins/review-council/tests/t-plan-evidence.sh`
- Modify: `plugins/review-council/tests/t-seat.sh`
- Modify: `plugins/review-council/tests/t-evidence.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: Task 4 authorization receipts and `check-authorization`.
- Produces:

```text
rev-prompt.sh SESSION LABEL SEAT LENS EMPHASIS --evidence MANIFEST --authorization SESSION/r<LABEL>-convergence.authorization.json
rev-seat.sh SEAT SESSION LABEL PROMPT --authorization SESSION/r<LABEL>-convergence.authorization.json
Convergence authorization SHA-256: <hash>
```

- [ ] **Step 1: Add failing wrapper-boundary tests**

Add tests for authorized verification render, missing authorization, tampering, wrong session, wrong label, wrong kind-to-phase mapping, plan flag mismatch, duplicate hash line, arbitrary prompt path, and a relabeled third verification. Every failure must happen before attempt reservation and before any provider shim call.

```bash
"$SCRIPTS/rev-seat.sh" codex-sol "$session" 3v \
  "$session/r3v-codex-sol.prompt.md" \
  --authorization "$session/r3v-convergence.authorization.json"
assert_eq "a stale authorization refuses before launch" "$?" 2
assert_exit "a stale authorization makes no attempt" 0 \
  test ! -e "$session/attempts/r3v-codex-sol.json"
assert_eq "a stale authorization makes no provider call" "$(wc -l < "$SHIM_ARGS_FILE")" 0
```

- [ ] **Step 2: Run the wrapper tests and confirm missing enforcement**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence_authorization`

Expected: FAIL because neither wrapper currently accepts or validates `--authorization`.

- [ ] **Step 3: Add the explicit red-team evidence phase**

Extend `rev-evidence.py prepare --phase` choices with `red-team`. Treat it like risk discovery for full-state routing and four-bundle coverage, but preserve the distinct manifest phase so it consumes the separate convergence budget. Require the four assignments to be distinct composites rooted in:

```python
RED_TEAM_BUNDLES = (
    "attacker-trust-boundaries",
    "corruption-rollback-recovery",
    "concurrency-duplication-exhaustion",
    "consumer-contracts-compatibility",
)
```

Add tests that a red-team authorization rejects a risk manifest and that no bundle is missing or duplicated.

- [ ] **Step 4: Bind authorization during prompt publication**

Add `--authorization PATH` to `rev-prompt.sh`. For initialized adaptive or numeric code sessions require the canonical direct child `r<LABEL>-convergence.authorization.json`, reject symlinks and nonregular files, call `check-authorization`, and emit exactly one hash line. Enforce:

| Kind | Manifest phase | Prompt rule |
| --- | --- | --- |
| discovery | discovery | no `--plan` |
| risk | risk | no `--plan` |
| red-team | red-team | no `--plan` |
| plan | plan | `--plan` required |
| verification | verification | no `--plan` |
| repair | repair | no `--plan` |

Legacy read-only and document rendering remains readable without authorization. Write-capable adaptive and numeric panels must always prepare an evidence manifest, including Agent-backed fallback, so there is no manifestless authorization bypass.

- [ ] **Step 5: Revalidate immediately before reservation**

Add `--authorization PATH` to `rev-seat.sh`. Require the prompt to be the canonical `SESSION/r<LABEL>-<SEAT>.prompt.md`. Immediately before `rev-attempt.py check` and `reserve`:

```bash
AUTH_HASH=$(python3 "$HERE/rev-convergence.py" check-authorization \
  "$SESSION" "$ROUND" --authorization "$AUTHORIZATION") || exit 2
[ "$(grep -c "^Convergence authorization SHA-256: $AUTH_HASH$" "$PROMPT")" = 1 ] \
  || die "prompt does not bind exactly one current convergence authorization"
```

The validation must recompute manifest, input, snapshot, and state bindings. A failure changes no attempts and launches no provider.

- [ ] **Step 6: Prove wrapper, prompt, evidence, and plan contracts**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence_authorization && ./tests/run-tests.sh red_team_phase && ./tests/run-tests.sh prompt_evidence && ./tests/run-tests.sh plan_evidence && ./tests/run-tests.sh seat`

Expected: all selected tasks PASS with zero shim calls on every local-contract refusal.

- [ ] **Step 7: Commit the launch boundary**

```bash
git add plugins/review-council/scripts/rev-evidence.py \
  plugins/review-council/scripts/rev-prompt.sh \
  plugins/review-council/scripts/rev-seat.sh \
  plugins/review-council/tests/t-prompt-evidence.sh \
  plugins/review-council/tests/t-plan-evidence.sh \
  plugins/review-council/tests/t-seat.sh \
  plugins/review-council/tests/t-evidence.sh \
  plugins/review-council/tests/test-costs.tsv
git commit -m "fix(rev): authorize paid review panels"
```

---

### Task 6: Rewrite Both Host Contracts Around the Bounded Machine

**Files:**

- Modify: `plugins/review-council/skills/rev/POLICY.md`
- Modify: `plugins/review-council/skills/rev/SKILL.md`
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Modify: `plugins/review-council/skills/stack/SKILL.md`
- Modify: `plugins/review-council/codex-skills/stack/SKILL.md`
- Modify: `plugins/review-council/tests/t-skill.sh`
- Modify: `plugins/review-council/tests/t-efficient.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: exact CLI commands from Tasks 3-5.
- Produces: matching Claude Code and Codex workflows that initialize once, authorize each panel, record verification counts, certify once, and stop on terminal state.

- [ ] **Step 1: Add failing executable-contract assertions**

For both host skill files, assert exact commands and semantics rather than loose keywords:

```text
rev-convergence.py init "$S" --mode adaptive
rev-convergence.py authorize "$S" "$PANEL_LABEL" --kind "$PANEL_KIND" --manifest "$MANIFEST"
rev-convergence.py record "$S" "$PANEL_LABEL" --coverage-receipt "$COVERAGE_RECEIPT" --new-p0 "$NEW_P0" --new-p1 "$NEW_P1" --open-p0 "$OPEN_P0" --open-p1 "$OPEN_P1" --origin-original "$ORIGINAL_P01" --origin-fix-of-fix "$FIX_OF_FIX_P01" --origin-unknown "$UNKNOWN_P01" --origin-infrastructure "$INFRASTRUCTURE_P01"
rev-convergence.py certify "$S"
```

Assert one initial and one correction generation, no generic nontrivial-fix extension, terminal `nonconvergent`, session-wide audit stop, input reuse on resume, P2 missing-test calibration, composite red-team assignment, conditional full red-team panel, and promoted compatibility, recovery, security, and full-state integration coverage.

- [ ] **Step 2: Run skill contract tests and confirm the prose is unbounded**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence_skill`

Expected: FAIL because current skills still say to repeat for new P0/P1 or any nontrivial cluster and do not invoke the convergence authority.

- [ ] **Step 3: Replace adaptive prose with the exact transition sequence**

Both host skills must execute this sequence:

```text
preflight once -> init -> discovery -> optional risk -> optional full red-team ->
one initial plan when needed -> one coherent fix batch -> verification 1 ->
clean: certify
P0/P1: one correction plan -> one coherent correction batch -> verification 2 ->
clean: certify
P0/P1: record nonconvergent and stop incomplete
infrastructure failure: record infrastructure-blocked and stop incomplete
```

Delete every instruction that repeats plan, fix, or verification for a generic nontrivial change. Numeric mode runs the exact requested numbered panels and may use only the same single P0/P1 correction generation. Read-only mode records findings and certifies `reported` without fixes.

- [ ] **Step 4: Route red-team and promoted lenses without extra calls**

In every code verification panel, compose one seat's canonical risk bundle with `red-team-composite`. Keep the full-state integration owner. Route these triggers:

```text
public API, protocol, schema, serialization, CLI output, cross-repo -> contract and consumer compatibility
persistence, external write, migration, retry, concurrency, CI orchestration -> recovery and idempotency
authentication, authorization, signature, secret, untrusted input, privilege transition -> security and trust boundaries
```

For large, high-risk, important, or explicit requests, authorize exactly one `red-team` discovery panel before planning with the four bundles from Task 5. Docs-only skips it unless requested. Numeric mode never silently increases the explicit panel count.

- [ ] **Step 5: Make finding origin and severity admission explicit**

Require every accepted or deferred finding ledger entry to include one of:

```text
Origin: original-scope
Origin: fix-of-fix
Origin: unknown
Origin: review-infrastructure
```

Require the host to pass aggregate P0/P1 origin counts to `record`. State exactly that unknown P0/P1 blocks, infrastructure findings stop certification without expanding product fixes, and an unproven missing test is P2.

- [ ] **Step 6: Bind quota fallback to the parent authorization**

When creating the one permitted fallback sibling, run `init-fallback CHILD_SESSION --parent-session PARENT_SESSION --authorization PARENT_AUTHORIZATION` after `same-source`. The child copies the parent logical authorization hash and generation. Require the matching parent handoff before any fallback prompt render. The fallback may replace provider seats but may not create another discovery, plan, or verification allowance.

- [ ] **Step 7: Update stack skills for per-leg convergence**

Each leg owns its state. A `nonconvergent` or `infrastructure-blocked` leg is incomplete and cannot be selected as the authoritative completed session. Valid sibling legs remain publishable under the current partial-stack contract. The seam and completeness critic may report cross-repository findings but cannot reset a leg's correction generation.

- [ ] **Step 8: Run all host contract tests**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence_skill && ./tests/run-tests.sh efficient && ./tests/run-tests.sh skill && ./tests/run-tests.sh stack_skill`

Expected: all selected tasks PASS and searches find no unbounded repeat instruction.

- [ ] **Step 9: Commit the bounded host workflow**

```bash
git add plugins/review-council/skills/rev/POLICY.md \
  plugins/review-council/skills/rev/SKILL.md \
  plugins/review-council/codex-skills/rev/SKILL.md \
  plugins/review-council/skills/stack/SKILL.md \
  plugins/review-council/codex-skills/stack/SKILL.md \
  plugins/review-council/tests/t-skill.sh \
  plugins/review-council/tests/t-efficient.sh \
  plugins/review-council/tests/test-costs.tsv
git commit -m "fix(rev): enforce bounded review orchestration"
```

---

### Task 7: Gate PR and Stack Completion on Convergence Receipts

**Files:**

- Modify: `plugins/review-council/scripts/rev-pr-review.py:603-850,1076-1145`
- Modify: `plugins/review-council/scripts/stack.sh:525-635`
- Modify: `plugins/review-council/tests/t-pr-review.sh`
- Modify: `plugins/review-council/tests/t-stack.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**

- Consumes: `convergence.receipt.json` and `rev-convergence.py check-completion` from Task 4.
- Produces: fail-closed render, publish, stack validation, stack finalization, and final report promotion with a convergence receipt hash frozen into `pr-review-target.json`.

- [ ] **Step 1: Add failing normal and stack completion tests**

Add `test_pr_review_convergence_gate` and `test_stack_convergence_gate`. Cover missing, stale, tampered, `nonconvergent`, and `infrastructure-blocked` receipts; a matching `clean` receipt; a matching read-only `reported` receipt; and one invalid stack leg beside one valid sibling.

Every invalid case must fail before a GitHub call and leave no `report.md` promotion:

```bash
PATH="$bin:$PATH" GH_CALLS="$T/convergence-gh.calls" \
  python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15
assert_eq "missing convergence blocks render" "$?" 2
assert_exit "a blocked render makes no GitHub call" 0 test ! -s "$T/convergence-gh.calls"
assert_exit "a blocked stack leg has no final report" 0 test ! -e "$session/report.md"
```

- [ ] **Step 2: Run completion tests and confirm publication currently ignores convergence**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence_gate`

Expected: FAIL because `rev-pr-review.py` accepts `pr-review.json` without convergence state.

- [ ] **Step 3: Add one shared completion validator**

Implement:

```python
def require_convergence(session: Path, expected_tree: str, *, allow_reported: bool) -> dict:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("rev-convergence.py")),
         "check-completion", str(session), "--tree", expected_tree]
        + (["--allow-reported"] if allow_reported else []),
        text=True, capture_output=True, timeout=30,
    )
    require(result.returncode == 0, result.stderr.strip() or "review convergence is not certified")
    return load_input(session / "convergence.receipt.json")
```

Call it before PR resolution or GitHub access in `render_session()`, again inside the publication transaction in `publish()`, in `validate_stack()`, and inside the publication lock in `finalize_stack()`.

- [ ] **Step 4: Freeze the receipt into the target envelope**

Add to target version 3:

```json
"convergence": {
  "name": "convergence.receipt.json",
  "sha256": "<sha256>",
  "decision": "clean",
  "snapshot_tree": "<tree>"
}
```

Validate the same bytes again during publish and stack finalization. Preserve version-2 target readability only for existing read-only artifacts; write-capable version-2 targets require a fresh review and cannot publish.

- [ ] **Step 5: Certify before stack report promotion**

In `complete_reviews()`, before `phase=done` or moving `stack-report.md` to `report.md`, run:

```bash
python3 "$REV_SCRIPTS/rev-convergence.py" certify "$session" \
  || { note_failure "convergence:$label" "$repo"; continue; }
```

Apply the same validation under `NO_PUSH=1`. Keep successful sibling publication independent from a failed leg.

- [ ] **Step 6: Run the publication and stack transaction suites**

Run: `cd plugins/review-council && ./tests/run-tests.sh convergence_gate && ./tests/run-tests.sh pr_review && ./tests/run-tests.sh stack`

Expected: all selected tasks PASS, valid publication remains idempotent, and blocked receipts cause zero GitHub writes.

- [ ] **Step 7: Commit the completion gate**

```bash
git add plugins/review-council/scripts/rev-pr-review.py \
  plugins/review-council/scripts/stack.sh \
  plugins/review-council/tests/t-pr-review.sh \
  plugins/review-council/tests/t-stack.sh \
  plugins/review-council/tests/test-costs.tsv
git commit -m "fix(rev): require convergence before completion"
```

---

### Task 8: Pressure-Test the Workflow, Verify the Frozen Tree, and Release 0.4.4

**Files:**

- Modify: `CHANGELOG.md`
- Verify: `plugins/review-council/.claude-plugin/plugin.json`
- Verify: `plugins/review-council/.codex-plugin/plugin.json`
- Modify: `tasks/todo.md`
- Modify: `tasks/lessons.md`

**Interfaces:**

- Consumes: completed Tasks 1-7, the existing unified verifier, exact personal roster configuration, PR #6, and the plugin update/install flow.
- Produces: behavior-tested host skills, one frozen-tree P0/P1 Review Council result, green CI, squash-merged PR #6, GitHub release `0.4.4`, and hash-verified Claude Code and Codex installations.

- [ ] **Step 1: Run behavior pressure scenarios against both host skills**

Use fresh isolated agents for these exact scenarios and save their transcripts outside the reviewed repository:

1. A hard audit failure in `r1` followed by a stale instruction to relaunch as `r2`. Pass only if the agent preserves artifacts and stops before launch.
2. A first verification with one verified P1, then a correction verification with another verified P1 after eight simulated hours. Pass only if the agent records `nonconvergent` and does not invent a third plan or verification label.
3. A small ordinary code review. Pass only if one existing verification seat receives red-team composite coverage and no extra panel is added.
4. A signature and persistence change marked important. Pass only if one four-seat red-team panel runs before planning, recovery, trust, compatibility, and full-state integration are all covered, and the correction ceiling remains one.
5. A read-only code review with an open P1. Pass only if it produces `reported`, makes no fix, and remains publishable without claiming clean convergence.
6. A two-leg stack with one nonconvergent leg. Pass only if the bad leg stays incomplete and the valid sibling retains its publication receipt.

Compare actual command sequences to the state-machine receipts, not to the agent's prose conclusion. Any invented label, missing authorization, provider call after a stop, or false `clean` result is a release-blocking P1.

- [ ] **Step 2: Run focused gates by changed contract cluster**

Run:

```bash
cd plugins/review-council
./tests/run-tests.sh convergence
./tests/run-tests.sh audit_stop
./tests/run-tests.sh sealed_session
./tests/run-tests.sh prompt_evidence
./tests/run-tests.sh plan_evidence
./tests/run-tests.sh pr_review
./tests/run-tests.sh stack
./tests/run-tests.sh skill
```

Expected: every selected task PASS with zero `FAIL` lines.

- [ ] **Step 3: Update release notes without changing the canonical post template**

Add compact 0.4.4 bullets for bounded convergence, immutable session inputs, session-wide audit stops, red-team routing, and convergence-gated publication. Confirm both plugin manifests still say `0.4.4`; do not bump again. Search all changed text for forbidden dash characters and attribution.

Run:

```bash
rg -n $'\u2013|\u2014|Co-authored-by:|Generated with|generated by|AI-generated' \
  CHANGELOG.md plugins/review-council/scripts plugins/review-council/skills \
  plugins/review-council/codex-skills plugins/review-council/tests
```

Expected: no U+2013, U+2014, attribution trailer, or generated-by attribution. Legitimate provider names in code and product docs are reviewed manually and are not attribution.

- [ ] **Step 4: Run the complete frozen-tree verifier once**

Run from a clean committed tree:

```bash
python3 scripts/verify-review-council.py --root .
```

Confirm the final output contains no `error`, `ERROR`, `compiled with`, `FAIL`, or missing-output diagnostic. Confirm all expected verifier receipts and both plugin manifests exist.

Expected baseline: at least 229 shell tasks, 3,723 shell assertions, 89 Python tests, all validators PASS, and a frozen-tree receipt matching the candidate tree. The totals may increase with this work but must not decrease.

- [ ] **Step 5: Run exactly one bounded P0/P1 Review Council release review**

Before launch, verify personal configuration is exactly:

```json
{
  "codex_models": ["gpt-5.6-sol", "gpt-5.6-terra"],
  "claude_models": ["opus", "sonnet"]
}
```

Run the repaired adaptive workflow on the final candidate tree. This is high-risk self-hosting, so it includes the one full red-team panel before planning. Apply only verified P0/P1 findings. P2/P3 are recorded and deferred. If correction verification still has P0/P1, stop the release as `nonconvergent`; do not launch another panel.

- [ ] **Step 6: Rerun only invalidated local gates, then one final frozen-tree verifier**

If the council made no source change, reuse the matching verifier receipt. If it made a P0/P1 fix, run its focused regression first, then rerun the complete frozen-tree verifier exactly once for the changed tree. Do not rerun paid panels after a clean correction verification.

- [ ] **Step 7: Commit release metadata and task evidence**

```bash
git add CHANGELOG.md tasks/todo.md tasks/lessons.md
git commit -m "docs: record bounded review release"
```

Do not amend prior commits. Confirm `git log --format='%B' origin/main..HEAD` contains no attribution trailer.

- [ ] **Step 8: Push, wait for green CI, and squash-merge PR #6**

```bash
git push origin feat/pr-review-post
gh pr checks 6 --watch
gh pr merge 6 --squash
```

Do not use `--admin` unless the user separately authorizes bypassing a branch rule. Before merge, confirm every required check is green and the PR head equals the verified local head.

- [ ] **Step 9: Tag and publish release 0.4.4**

After the squash merge reaches `origin/main`, verify the merged manifests and changelog from a fresh `origin/main` checkout, then create the release from the merge commit:

```bash
git fetch origin main --tags
git tag -s review-council--v0.4.4 origin/main -m "review-council 0.4.4"
git push origin review-council--v0.4.4
gh release create review-council--v0.4.4 --verify-tag --title "review-council 0.4.4" --notes-file /tmp/review-council-0.4.4-notes.md
```

Generate `/tmp/review-council-0.4.4-notes.md` from the final 0.4.4 changelog section using `apply_patch`, not shell redirection. The verified repository tag convention is `review-council--v<version>`.

- [ ] **Step 10: Reinstall and verify both plugin surfaces**

Follow the `plugin-creator` update flow. Refresh the local development install with the CLI-driven cachebuster, reinstall the released Claude marketplace plugin, run `codex plugin marketplace upgrade review-council`, and start fresh discovery sessions. Hash-compare installed scripts and skill files to the released tag.

Verify:

```text
Claude Code discovers /review-council:rev and /review-council:stack at version 0.4.4.
Codex discovers review-council:rev and review-council:stack at version 0.4.4.
Both installed rev skills contain the bounded correction rule and red-team routing.
Both installed wrappers contain the session-wide stop and convergence authorization checks.
```

- [ ] **Step 11: Record final evidence**

Mark every checklist item in `tasks/todo.md`, add the exact verifier receipt, council session, PR merge commit, release URL, tag, and installed hashes to its review section, and record any new machine-independent gotcha in `agentic-kb` without personal or sensitive data.
