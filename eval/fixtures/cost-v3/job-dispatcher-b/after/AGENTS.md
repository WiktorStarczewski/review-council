# Dispatcher contracts

Review the synchronous dispatcher and its public caller boundaries as one subsystem.
Preserve tenant isolation, active attempt ownership, cancellation, transactional job
and event consistency, and the sink's partial acknowledgement contract.

Storage and the sink are intentionally deterministic, in-process implementations.
No real network, durable database, distributed lock, worker thread, or wall clock is
part of this change. Do not demand those facilities as fixes. Numeric time arguments
represent the caller's clock. A lease expires at its exact deadline. Job identifiers
are globally allocated, while lookup and deduplication remain tenant scoped.

Delivery is at least once. Replay of an already accepted event is valid; the sink
deduplicates its stable identity. A delivery receipt may acknowledge only part of a
batch. Handlers receive owned payloads and may mutate their local copies. Public
snapshots are owned data. Running cancellation is cooperative: an active attempt
observes its request before publishing a terminal outcome. Retries use a capped
delay from failure time and stop at the attempt budget.

Use the actual callers and dependency contracts when judging a change. Diagnostics
are human-readable text without a compatibility promise. Review only this source
tree; benchmark metadata and evaluation tools are outside repository scope.
