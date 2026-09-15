# Review Council Stable Release Lane Design

## Goal

Keep ordinary Review Council reviews adaptive while making Review Council's own
releases bounded, independently reviewed, and reproducible. The candidate plugin must
never certify the reviewer machinery that is deciding whether that candidate may ship.

The repair also keeps three generally useful improvements discovered during the
incident: a session-wide hard-audit stop, immutable evidence-session inputs, and more
adversarial coverage inside normal panels.

## Incident finding

The 0.4.4 feature-to-release path spent 15 hours 27 minutes across 26 panel
generations, 89 paid calls, and 128,164,553 processed tokens. The complete frozen-tree
gate took about 10 minutes and was stable. Most avoidable time came from the candidate
reviewing changes to its own prompt, audit, evidence, and orchestration machinery,
then reviewing the repairs created by those reviews.

Ordinary `/rev` runs did not show the same median behavior. Their median was four
panels and about 2.84 hours, although some outliers existed. A global two-generation
convergence controller would therefore optimize the exceptional self-host release
case by constraining a generally healthy review workflow.

## Chosen architecture

Use two different policies:

1. Ordinary review keeps the current adaptive and numeric schedules. It gains the
   general safety and review-coverage improvements in this design, but no new global
   correction cap or publication receipt.
2. Review Council releases use a dedicated stateful lane. The installed previous
   stable release reviews the candidate read-only. Candidate code runs deterministic
   gates and only the runtime canaries selected by changed subsystem paths.

The release lane permits one initial stable review generation and, only after verified
P0/P1 repairs, one stable delta generation. A remaining P0/P1 or infrastructure failure
blocks the release. It never creates a third review generation under another label.

## Global safety improvements

### Session-wide hard-audit stop

A hard evidence-audit failure writes an immutable session marker under the existing
attempt lock. Every later `check` and `reserve`, regardless of panel label, reads that
marker before creating a provider reservation. Existing production
`r*-*.read-audit.json` hard failures also stop legacy sessions.

Seats already reserved may finish or be canceled. No unreserved seat may start. The
diagnostic requires a fresh review session and preserves every invalid result, audit,
stream, and sibling receipt.

### Immutable session inputs

The four session inputs are `scope.env`, `roster.json`, `files.txt`, and
`untracked.txt`. Preflight stages all four and installs them while holding one
session-input lock. Any evidence manifest, including a malformed one, seals them.

`rev-evidence.py prepare` holds the same lock from its first input read through
manifest publication. Input installation therefore finishes before evidence capture
or fails after the manifest seals the prior complete generation. A manifest cannot
bind a mixed input set.

An initialized session reuses its complete inputs without another provider probe.
Partial or unsafe inputs stop incomplete. Quota fallback keeps using a fresh sibling
session.

### Promoted adversarial coverage

Every code panel assigns one existing seat a composite red-team emphasis. This adds no
provider call and never replaces the seat's canonical lens or bundle.

The verification owner always traces the cumulative change through consumers and
integration boundaries. Other emphases are composed when relevant:

- compatibility and consumer contracts for public APIs, protocols, schemas,
  serialization, CLI output, and cross-repository interfaces;
- recovery and idempotency for persistence, external writes, migrations, retries,
  concurrency, CI orchestration, and partial failure;
- security and trust boundaries for authentication, authorization, signatures,
  secrets, untrusted input, and privilege changes.

Large, high-risk, or user-marked-important adaptive reviews may add one full red-team
panel before planning. A change is high-risk when it crosses a security, persistence,
concurrency, transaction, protocol, public API, or irreversible mutation boundary.
Explicit numeric schedules do not silently gain another panel, but their final code
panel still contains the composite red-team assignment.

## Stable release lane

### Engine boundary

Release candidate N is reviewed only by an installed copy of stable release N-1. The
lane verifies all of the following before accepting a review artifact:

- the stable tag is an annotated tag whose signature passes `git verify-tag`;
- the stable tag resolves to the commit named by the lane;
- the installed stable plugin's regular files, symlinks, and executable modes exactly
  match `plugins/review-council` in that tag;
- both installed plugin manifests name the stable version;
- the stable contract receipt identifies that installed plugin path, its runner hash,
  provider CLI versions, exact ordered roster, touched candidate boundaries, and
  candidate boundary hashes.

Version strings alone are never engine identity. A cachebuster suffix may be ignored
only in a generated version field when the installed bundle otherwise matches the tag.
The 0.4.3 Codex cache currently matches the signed 0.4.3 tag byte for byte, so no
exception is needed for this release.

### Candidate boundary

Every release generation names an exact candidate commit. The candidate worktree must
be clean, `HEAD` must equal that commit, and both plugin manifests must carry the same
candidate version. The candidate version must be greater than the stable version and
must correspond to the release tag name.

The candidate identity includes the commit, Git tree, full frozen-tree key used by
`verify-review-council.py`, and hashes and modes for every path changed from N-1.

### Two generations

Generation 1 is one read-only stable review of the complete candidate. Its four seats
cover the four verification bundles, with these adversarial compositions:

1. correctness and boundaries plus attacker behavior and trust boundaries;
2. security, state, and API plus rollback and recovery;
3. concurrency, resources, and performance plus duplication and exhaustion;
4. tests, observability, and regression plus consumer compatibility and integration.

The orchestrator verifies every finding against candidate source. Only verified P0 and
P1 findings may change the release candidate. P2 and P3 are recorded for later and do
not expand the release scope.

If generation 1 has no verified P0/P1, its reviewed tree is the final review tree and
the lane needs no second generation. If P0/P1 repairs change the tree, generation 2 is
one read-only stable delta review. It receives the repair delta, prior P0/P1 decisions,
and one full-state integration assignment. If generation 2 has a new or open P0/P1,
the lane records `blocked`. The release must be redesigned or started as a new lane;
the current lane cannot authorize another panel.

Provider execution, evidence, or hard-audit failure records `infrastructure-blocked`.
It is not a product finding and does not authorize a retry or a broader panel in the
same lane.

### Deterministic candidate gate

The final candidate runs:

```text
python3 scripts/verify-review-council.py --root .
```

The release lane validates the verifier receipt rather than trusting terminal prose.
It recomputes the frozen source key from the clean final commit, verifies the receipt
identity and key, and verifies every command log is regular, hash-matching, complete,
and exit 0. The exact candidate tree may reuse an existing valid receipt.

### Targeted canaries

Canaries prove only runtime boundaries whose candidate implementation changed. They do
not review the candidate and cannot create product findings. Each canary receipt binds
the canary ID, the hashes and modes of its trigger paths, the command, an exit-0 log,
and any referenced evidence artifacts. A receipt remains reusable across unrelated
commits while its trigger-path identities stay exact.

The initial trigger matrix is:

| Canary ID | Changed path trigger | Runtime proof |
| --- | --- | --- |
| `provider-codex` | `scripts/seats.d/codex.sh`, or shared read-audit and stream parsing | one Codex adapter envelope and valid evidence audit |
| `provider-claude` | `scripts/seats.d/claude.sh`, or shared read-audit and stream parsing | one Claude adapter envelope and valid evidence audit |
| `provider-gemini` | `scripts/seats.d/gemini.sh`, or shared read-audit and stream parsing | one Gemini adapter envelope and valid evidence audit |
| `github-publication` | `rev-pr-review.py`, `stack.sh`, or `docs/pr-review.md` | one disposable pending-to-commented transaction or an exact hash-bound replay when GitHub behavior was not changed |
| `host-claude` | `skills/rev/**`, `skills/stack/**`, `POLICY.md`, or Claude hooks | behavioral pressure test with the candidate Claude skill loaded |
| `host-codex` | `codex-skills/rev/**` or `codex-skills/stack/**` | behavioral pressure test with the candidate Codex skill loaded |

Provider adapter files always require their provider canary. Shared auditor or stream
parser changes require one canary for each configured live adapter. Other provider
orchestration changes use the existing preserved-envelope contract replay unless that
replay cannot establish the newly exposed model-visible behavior.

The matrix is fail closed. A triggering path without a known canary mapping or a
missing, failed, malformed, stale, or mismatched required receipt blocks certification.

## Release authority

Add `scripts/verify-release-lane.py` with these public commands:

```text
verify-release-lane.py requirements --root ROOT --candidate-commit SHA --stable-tag TAG
verify-release-lane.py record-review --root ROOT --candidate-commit SHA --stable-plugin PATH --stable-tag TAG --session SESSION --new-p0 N --new-p1 N --open-p0 N --open-p1 N --out RECEIPT
verify-release-lane.py run-canary --root ROOT --stable-tag TAG --id ID --out RECEIPT -- COMMAND [ARG ...]
verify-release-lane.py certify --root ROOT --candidate-commit SHA --stable-plugin PATH --stable-tag TAG --review RECEIPT [--review RECEIPT] --verification-receipt PATH --canary ID=PATH --out RECEIPT
```

`requirements` validates the clean candidate identity and prints the changed-path
canary set as canonical JSON. It writes nothing.

`record-review` invokes the installed stable engine's
`scripts/rev-contract-check.py --verify-only` against the session, validates the
session coverage receipt and source tree, records the supplied P0/P1 decision counts,
and writes one immutable decision receipt for that reviewed commit.

P0/P1 counts are explicit host decisions because severity and source verification are
orchestrator responsibilities. `record-review` also requires the session findings and
state artifacts to be hash-bound, so the decision cannot later be paired with different
review bytes.

`run-canary` accepts only a canary ID selected by the current changed paths, runs the
argument vector without a shell, captures a bounded log, and writes a receipt only for
exit 0. It binds the current trigger path identities. It may run before unrelated final
commits without becoming stale.

`certify` requires a clean final candidate, the latest review generation to be clean on
that exact Git tree, a valid deterministic verifier receipt, every required current
canary, no extra unknown canary, and no session-wide audit stop. It accepts one or two
review decision receipts and rejects any other count. One clean initial receipt
certifies directly. A nonclean initial receipt requires one later clean receipt on a
different candidate commit; a nonclean second receipt blocks certification. This makes
a third generation structurally unrepresentable without maintaining another mutable
orchestration database. It writes one immutable `release-receipt.json`. It never
pushes, publishes, tags, merges, or installs.

Review records, canary receipts, and the final receipt use canonical JSON,
same-directory atomic publication, regular one-link file validation, and collision
refusal.

## Publication and installation

After certification, the normal human-authorized sequence remains:

1. push the feature branch and wait for green CI;
2. squash-merge the PR;
3. verify version and changelog from the merged commit;
4. create and verify the signed release tag;
5. publish the GitHub release;
6. update the local plugin cache through the plugin-creator install flow;
7. start a fresh host session and verify discovery.

Post-release discovery is a smoke check, not another release review generation. A P0
or P1 found after publication causes a follow-up release or yank decision. It never
rewrites the already published candidate in place.

## Compatibility and non-goals

- Ordinary adaptive, numeric, read-only, document, and stack convergence rules remain
  unchanged except for the global safety and composite red-team additions above.
- No generic `rev-convergence.py` is added.
- PR review rendering and publication keep the canonical badge, headings, tip,
  decisions section, and collapsible sections exactly as already implemented.
- Existing release artifacts remain readable. Only new releases use the lane state.
- The lane does not decide whether a finding is true or assign severity.
- The lane does not grant push, merge, tag, release, or installation authority.

## Tests

Every behavior change follows red-green TDD. Focused tests cover hard-stop races,
session-input sealing and lock order, composite red-team wording, stable engine byte
and mode identity, signed-tag and version mismatches, dirty or moved candidates,
review-generation limits, stable contract and coverage tampering, deterministic
receipt and log validation, canary selection and staleness, output collisions, and
final certification.

The complete frozen-tree verifier remains the final deterministic gate.
