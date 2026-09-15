# Review Council Convergence Repair Design

## Goal

Make adaptive Review Council runs converge or stop within a bounded number of paid
panel generations, without hiding P0/P1 findings or weakening final verification.

The repair also makes the session inputs used by evidence manifests immutable and
turns a hard evidence-audit failure into a session-wide stop.

## Problem

The current workflow has three interacting failure modes:

1. A new P0/P1 or any nontrivial repair can repeat plan, fix, and verification with
   no correction ceiling.
2. A hard audit failure blocks only one panel label. A fresh label can launch another
   paid generation in the same broken session.
3. Preflight and direct roster writes can replace `roster.json`, `scope.env`,
   `files.txt`, or `untracked.txt` after evidence manifests have hashed them.

The publication feature exposed the result: 26 panel generations, 89 paid calls,
and 73.9 percent of later-rewritten production and documentation lines originating
in earlier review fixes.

## Principles

- Preserve every P0/P1. The circuit breaker stops incomplete instead of declaring a
  risky tree clean.
- Bound semantic correction generations, not elapsed time. Provider latency alone
  must not terminate an otherwise valid panel.
- Treat review infrastructure failures separately from findings about the product
  being reviewed.
- Make launch authorization and completion machine-checkable. Prose remains the host
  contract, not the only enforcement point.
- Keep the repair smaller than a full orchestration rewrite.

## Modes

### Adaptive code review

Adaptive review gets two material fix generations:

1. The initial generation batches accepted findings from discovery, optional risk
   discovery, and conditional full red-team discovery, runs at most one plan panel,
   applies the coherent fix batch, and runs the first verification panel.
2. If that verification has a new or open P0/P1, one correction generation may run:
   at most one correction plan panel, one coherent fix batch, and one final
   verification panel.

If the final verification has any new or open P0/P1, the session becomes
`nonconvergent`. It cannot launch another semantic panel, publish a review, or write
a success report. The unresolved findings and receipts remain available for a
redesign or a user-authorized fresh review.

P2 and P3 findings remain reportable. They do not trigger a correction generation.
During an explicit P0/P1-only release convergence run, they are deferred without
changing the candidate tree.

Every code review gives at least one seat an explicit red-team assignment in addition
to its canonical lens or risk bundle. This adds no provider call. Large, high-risk,
or user-marked-important adaptive changes receive one full red-team discovery panel
before the plan and fix batch. Docs-only reviews skip it unless requested.

A change is high-risk when it crosses a security, persistence, concurrency,
transaction, protocol, public API, or irreversible external-mutation boundary.
Authentication, authorization, signatures, secrets, untrusted input, migrations,
serialization, and cross-repository contracts are explicit examples.

### Numeric code review

Numeric mode runs the exact user-requested minimum numbered panels. Generic
"nontrivial fix" language does not extend it. After the minimum, it may use the same
single P0/P1 correction generation. A remaining P0/P1 then stops incomplete.
At least one seat in its final requested code panel receives the composite red-team
assignment. A full red-team panel runs when the numeric schedule reaches that phase
or the user explicitly requests it; the adaptive high-risk trigger does not silently
increase an explicit numeric panel count.

### Read-only and document review

Read-only and document reviews run their requested panel count and never enter the
fix-generation state machine. Session-input sealing and session-wide audit stops
still apply. Read-only code review gives one seat a composite red-team assignment.
Document review does not unless requested.

### Stack review

Each stack leg owns its convergence state. A nonconvergent or infrastructure-blocked
leg remains incomplete and prevents a clean stack result. Other successfully reviewed
legs retain their receipts and may publish according to the existing partial-stack
contract.

## Finding admission

The orchestrator continues to verify every finding against source before accepting
it. Every accepted or deferred finding records one origin:

- `original-scope`: proven on the immutable snapshot that existed before review fixes.
- `fix-of-fix`: absent on the initial snapshot and introduced by a recorded review-fix
  tree transition.
- `unknown`: causal origin is not proven. Unknown P0/P1 remains blocking.
- `review-infrastructure`: an audit, transport, evidence compiler, or gate problem in
  the current review attempt. This blocks certification but never expands the product
  change under review.

A missing test is P2 unless source or a failing behavioral regression demonstrates a
reachable incorrect behavior or broken public contract. Severity is assigned from
impact, not from the amount of work required to prove or fix it.

The Markdown ledger adds `Origin:` to each entry. Machine state stores aggregate P0/P1
counts by origin. This release does not replace the findings ledger with a new
database or attempt to infer behavioral causality from `git blame`.

## Convergence authority

Add `scripts/rev-convergence.py`. It owns a lock-protected `convergence.json` and
immutable per-panel authorization and triage receipts.

The public commands are:

```text
rev-convergence.py init SESSION --mode adaptive|numeric|read-only [--min-rounds N] [--full-red-team REASON]
rev-convergence.py init-fallback CHILD_SESSION --parent-session PARENT_SESSION --authorization PATH
rev-convergence.py authorize SESSION LABEL --kind discovery|risk|red-team|plan|verification|repair --manifest PATH
rev-convergence.py record SESSION LABEL --coverage-receipt PATH --new-p0 N --new-p1 N --open-p0 N --open-p1 N --origin-original N --origin-fix-of-fix N --origin-unknown N --origin-infrastructure N
rev-convergence.py certify SESSION
rev-convergence.py status SESSION
```

`init` is idempotent only for the exact same mode, numeric minimum, and full-red-team
reason. A mismatch fails closed.

`--full-red-team` records the nonempty, single-line high-risk, large, important, or
explicit trigger selected by the host. Without that initialization field, a full
red-team panel is not authorized. `init-fallback` binds a fresh quota-fallback sibling
to the parent session identity, authorization, panel kind, generation, and existing
same-source proof. It cannot create a new semantic allowance.

`authorize` validates the manifest label, phase, snapshot tree, input hashes, and
session identity. It writes `r<LABEL>-convergence.authorization.json` once. An exact
repeat is idempotent; a different repeat fails. Adaptive limits are:

| Semantic panel kind | Maximum generations |
| --- | ---: |
| Discovery | 1 |
| Risk discovery | 1 |
| Full red-team discovery | 1 when large, high-risk, important, or explicitly requested |
| Plan | 2 |
| Verification | 2 |
| Coverage repair | Existing one-seat repair only |

The second plan and verification authorizations require the first verification
triage decision to be `correction-required`. A clean first verification permits
certification, not another panel. An incomplete or hard-audit-failed panel permits no
replacement generation.

`record` validates the coverage receipt and binds the triage counts to its manifest,
snapshot tree, and result set. New P0/P1 origin counts must sum to the new P0/P1
total. The first verification records one of:

- `clean`: no new or open P0/P1.
- `correction-required`: a P0/P1 remains and the single correction allowance is free.
- `infrastructure-blocked`: current review infrastructure is not certifying.

The second verification records `clean`, `infrastructure-blocked`, or
`nonconvergent`. It never records another correction allowance.

`certify` requires the latest verification decision to be `clean`, zero open P0/P1,
the latest `coverage-head.json` to match that verification, and no session-wide audit
stop. It writes immutable `convergence.receipt.json`.

Read-only review instead writes a `reported` convergence receipt after its requested
coverage completes. It may retain open findings, never claims a clean fixed tree, and
cannot authorize a plan or repair generation.

`rev-prompt.sh` and `rev-seat.sh` validate the matching authorization before a paid
adaptive launch. This prevents a relabeled third plan or verification panel even if
host prose is ignored. Legacy sessions without convergence state cannot resume a
write-capable adaptive run under the new plugin; they require a fresh session.

## Immutable session inputs

Add `scripts/lib/session_inputs.py` with a shared session-input lock and these
responsibilities:

- Define the four standard inputs: `scope.env`, `roster.json`, `files.txt`, and
  `untracked.txt`.
- Stage and atomically install those inputs while holding the lock.
- Treat any session evidence manifest as a seal, including a malformed manifest.
- Refuse an input replacement after sealing without changing existing bytes.
- Reject symlinks, nonregular files, and redirected lock paths.

`rev-preflight.sh` builds all four inputs in a private staging directory, then installs
them through this helper. It checks for a sealed target before the paid roster probe.

`roster.py --write` uses the same helper when its destination is a session
`roster.json`.

`rev-evidence.py prepare` holds the shared lock from its first input read through
manifest publication. Therefore input installation either finishes before evidence
preparation or is rejected after the manifest seals the old bytes. A manifest can
never bind a mixed input generation.

An initialized session resumes from its existing inputs. It never reruns preflight or
provider probing. Quota fallback continues to use a fresh sibling session and the
existing byte and content-addressed source comparisons.

## Session-wide hard audit stop

Change `scripts/lib/rev-attempt.py` so a hard evidence-audit failure writes a
session-wide stop marker under a session lock as well as the panel diagnostic.

Every later `check` and `reserve`, for every label, reads the session marker before
reserving a provider call. Existing evidence-scoped invalid audits also count as a
session stop for backward compatibility. The diagnostic says to use a fresh session,
not a fresh panel label.

Seats already running when a sibling fails may finish or be canceled by the host.
No seat that has not yet reserved a call may start afterward.

Legacy full-scope audit advisories do not create the hard-stop marker.

## Promoted review coverage

Promoted coverage normally changes assignments inside an existing panel rather than
adding another panel generation.

- `Regression and integration`: the full-state verification owner always rereads the
  cumulative diff and traces the changed behavior through its consumers end to end.
- `Contract and consumer compatibility`: add this emphasis when public APIs,
  protocols, schemas, serialization, CLI output, or cross-repository interfaces
  change.
- `Recovery and idempotency`: add this emphasis for persistence, external writes,
  migrations, retries, concurrency, CI orchestration, and partial failure.
- `Security and trust boundaries`: add this emphasis for authentication,
  authorization, signatures, secrets, untrusted input, and privilege transitions.

The one always-present red-team assignment is composed with the most relevant
verification seat. It never replaces a canonical risk bundle.

The full high-risk red-team panel uses four distinct adversarial assignments:

1. Attacker behavior and trust boundaries.
2. State corruption, rollback, and recovery.
3. Concurrency, duplication, and resource exhaustion.
4. Consumer contracts and compatibility.

Red-team findings join the initial root-cause clusters and fix plan. The full panel
runs before code changes so it cannot create an extra post-verification repair cycle.
It never grants another correction generation.

## Verification and publication

Focused tests run after each edit. The evidence fixture runs after a coherent contract
cluster. The complete local gate runs once for each final candidate tree, and an exact
unchanged tree reuses its existing verification receipt.

`rev-pr-review.py` refuses to render or publish a successful code-review report unless
`convergence.receipt.json` is valid and matches the latest coverage and reviewed
snapshot. Stack finalization applies the same requirement to each publishable leg.

Publication failure remains independently recoverable under the existing pending
review transaction. Convergence certification does not authorize pushing,
publication, or merging.

## Compatibility

- Existing evidence manifests seal their sessions immediately.
- An existing write-capable session without convergence state cannot be certified by
  the new release. Start a fresh session so the correction budget is unambiguous.
- Existing read-only artifacts remain readable and reportable.
- No change is required to the provider findings schema.
- Quota fallback remains one fresh full-panel restart and inherits the logical panel
  authorization from its parent receipt. It cannot reset the correction allowance.

## Tests

All behavior changes use red-green TDD.

### Session inputs

- A sealed preflight rerun fails before the roster stub and preserves all four hashes.
- Direct `roster.py --write` cannot replace a sealed roster.
- A deterministic race between input installation and evidence preparation produces
  either the complete old generation or the complete new generation, never a mix.
- A resumed evidence-bearing session performs no provider probe.

### Audit stop

- A hard audit failure in label `r1` prevents a provider reservation under label `r2`.
- The refusal preserves the original invalid result and audit bytes.
- Concurrent reservations observe a single session stop state.
- A legacy advisory does not stop the session.

### Convergence

- Initial plan and verification authorizations succeed.
- Every verification contains one red-team assignment without losing a canonical
  risk bundle.
- High-risk and user-marked-important changes permit exactly one full red-team panel
  before the initial plan, while ordinary changes permit none unless requested.
- The full red-team panel carries all four distinct adversarial assignments.
- Contract, recovery, security, and regression promotions route into existing panels
  without increasing their generation count.
- A clean first verification refuses another plan or verification.
- A first-verification P0/P1 permits exactly one correction plan and verification.
- A clean correction verification certifies.
- A correction verification with a new or open P0/P1 becomes nonconvergent and refuses
  every later semantic panel.
- P2/P3-only triage never consumes the correction allowance.
- Origin counts must balance and unknown P0/P1 stays blocking.
- A quota-fallback sibling cannot reset the parent allowance.
- Numeric mode honors its explicit minimum without generic automatic extension.

### Completion

- Missing, stale, tampered, nonconvergent, or infrastructure-blocked convergence
  receipts prevent normal and stack publication.
- A receipt matching the final coverage head and snapshot permits the existing
  publication transaction.
- Pressure scenarios confirm both host skills stop after the correction verification
  instead of inventing a new label or continuing because the fix is nontrivial.

## Non-goals

- Replacing the skill-driven host with a monolithic runner.
- Automatically deciding whether a behavioral defect is a fix-of-fix.
- Lowering reviewer effort, roster size, or four-bundle final coverage.
- Adding arbitrary wall-clock, token, or cost termination thresholds.
- Changing GitHub review formatting or publication transaction semantics.
