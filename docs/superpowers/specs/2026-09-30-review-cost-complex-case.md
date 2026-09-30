# Complex review cost benchmark case

## Objective

Build one reusable, deterministic multi-tenant job dispatcher case for comparing
review cost first and elapsed time second. The reviewed subsystem spans 600-1000
lines across 6-10 files. Six planted defects require following caller and dependency
contracts. The benchmark remains an experiment; one case cannot establish general
review quality.

## Reviewed system

Each source tree contains 700 lines across eight Python modules and a public
construction module, plus repository instructions:

- `models.py`: job states, immutable lease tokens, retry plans, and outbox records.
- `store.py`: indexed tenant storage, copy ownership, rollback, and event emission.
- `jobs.py`: enqueue deduplication, cancellation, and tenant-scoped lookups.
- `leases.py`: claim, expiry recovery, renewal, and attempt fencing.
- `retry.py`: capped exponential retry delays measured from the failure time.
- `worker.py`: deterministic handlers, completion, cancellation checkpoints, and failure.
- `outbox.py`: partial acknowledgement handling and replay of pending events.
- `transport.py`: an idempotent sink with explicit partial acknowledgements.

The injected clock is an explicit numeric argument. There are no network calls,
sleeps, background threads, or external dependencies. Storage is intentionally
in-process and transactional, with deterministic failures injected at the event
emission boundary. Persistence, distributed locks, and true parallel execution are
out of scope. Public module contracts describe tenant isolation, active lease
fencing, cancellation, retries, rollback, and at-least-once event delivery.

## Planted defects

| ID | Fault | Cross-module proof |
| --- | --- | --- |
| tenant-dedup | Deduplication omits the tenant from its lookup key. | Enqueue callers for two tenants collide in indexed storage. |
| stale-lease-fence | Lease validation omits the generation check. | A worker reusing its name can complete a reclaimed attempt with an old token. |
| retry-clock-origin | Retry readiness is based on creation time. | Failure after a long lease schedules a retry that is already due. |
| partial-outbox-ack | Dispatch marks unacknowledged events delivered. | A partial sink receipt loses an event produced by a committed job transition. |
| running-cancellation | Cancellation fails to record intent for an active job. | Worker completion publishes success after a successful cancellation request. |
| rollback-record-alias | A rollback checkpoint retains mutable job aliases. | Event emission failure leaves a completed job without its corresponding event. |

Each defect has an isolated behavioral probe, a correct baseline expectation, and
an independently observable broken outcome. A repair mutation replaces only that
defect's source span and must make the sealed after oracle fail while preserving
the other defect checks. Repair snippets and truth remain outside the reviewed
source roots.

## Clean controls and distractors

Eleven controls cover correct tenant isolation for direct reads, enqueue
payload ownership, exact-deadline lease recovery, rejecting an expired token,
retry caps and terminal exhaustion, queued cancellation, transaction rollback of
new inserts, and sink replay deduplication. They exercise plausible false positive
traps: same worker identity is valid only for the current generation; leases expire
at their deadline; partial acknowledgements are permitted; a retry may exceed its
configured delay cap only through caller scheduling; duplicate delivery is expected
and consumers deduplicate it.

Harmless edits change diagnostic formatting, normalize input validation, and make
ordering explicit without changing behavior. One dependency module remains byte
identical to ensure reviewers must inspect context outside the patch. Instructions
make subsystem contracts and intentional limitations explicit without identifying
the defects or revealing expected findings.

## Oracle and sealed metadata

The two materialized cases use neutral identities `job-dispatcher-a` and
`job-dispatcher-b` so reviewer paths do not reveal expected cleanliness. The latter
contains all six exact repairs while retaining harmless diagnostic and validation
message edits. Tests enforce this derivation rather than maintaining another
implementation independently.

`case.json` and `oracle.py` live alongside `before/` and `after/`, never inside either
reviewed root. One shared private `dispatcher_oracle.py` holds the probes and repair
spans. Case metadata records exact changed paths, defect ranges and labels, severity,
matching keywords, clean controls, and source hashes. The oracle imports each
reviewed tree under a unique package name and observes public transitions and sink
receipts. It uses hand-stated outcomes and invariants, not a second dispatcher
implementation. Its JSON interface is compatible with the existing benchmark local
gate.

The private `behavior_rubric` contains six `critical_flows` with exact after-snapshot
`required_sources` ranges and rationale, plus ten finite `hypotheses` with scenario
identities, descriptions, and source obligations. It measures observed source reads
and independently verified scenarios. Hidden reasoning is unavailable; verbosity
receives no credit. The clean twin has a scope-calibrated rubric and an empty defect
list, allowing specificity to be measured on a wholly correct change.

Provider-free tests prove baseline correctness, all six after failures, all clean
controls, independent single-defect repair sensitivity, hidden-truth separation,
exact ranges and bytes, clean-twin derivation, and read-only frozen-copy compatibility.
Each variant passes 34 oracle checks; seven fixture contract tests cover these gates.
Existing cost-v1
and cost-v2 fixtures remain unchanged. The harness, runtime, provider experiments,
commits, and publishing remain outside this fixture's ownership.

## Scope calibration before provider execution

The neutral `job-dispatcher-a` case has six critical flows and ten scenario
objectives. The neutral `job-dispatcher-b` clean twin changes only validation wording
and human-readable diagnostics. Its private rubric therefore has two relevant flows
and four scenarios covering ready-list validation, tenant/data ownership and actual
statistic formatting. Requiring unchanged retry and outbox paths on this clean patch
would reward unnecessary reads and bias cost optimization. All eleven executable
clean controls still run on both complete implementations. This scope calibration
is frozen before the first paid execution; no result is used to tune the weights or
rubric. Full quality scores compare versions of the same case, not unrelated cases.

The baseline contract caps output at five distinct findings. The complex case's six
planted root causes deliberately put that prioritization under pressure. Severity
weights and the hard P0/P1 gate distinguish a smaller missed defect from a critical
miss; a higher numeric average cannot hide the latter.
