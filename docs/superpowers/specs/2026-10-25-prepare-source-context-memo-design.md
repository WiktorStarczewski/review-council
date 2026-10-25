# Per-prepare source-context validation memo

## Intent

Reduce the long pause before large plan reviews by avoiding repeated reconstruction of identical predecessor source context within one `rev-evidence.py prepare` process. Keep every review proof and tamper check in force.

## Evidence and success

The #1841 preparation trace recorded 181 canonical source-context rebuilds in one process while recursively validating overlapping predecessor history across 9 manifests and 4 receipts. The current plan's own source-context stage had not started. Two independent code and trace inspections traced the repeated work to recursive calls through `prior_coverage()`, `validated_manifest()`, and `validate_source_context_snapshot()`.

Success means canonical reconstruction runs at most once per unique manifest and canonical input set in a single prepare invocation, while every repeated visit still rejects changed or invalid inputs. The optimization should reduce the recorded 181 rebuilds to roughly the 9 distinct historical manifests.

## Design

Memoize only the deterministic canonical reconstruction used to compare recorded source-context packets with their expected packets. Scope the memo to one process. Key each entry by the resolved session and manifest paths, the raw manifest hash, repository identity, base and snapshot tree IDs, validation mode, and the identities of any canonical change, delta, or predecessor inputs used for reconstruction.

Every validation visit must still perform cycle detection, manifest schema and hash checks, receipt hash and lineage checks, input and artifact verification, source-byte checks, and other existing freshness and scope checks. A cache hit may skip only rebuilding canonical Git facts and packet selection after those checks pass. Cache only a fully successful canonical reconstruction. Do not cache validation success, persist entries to disk, or use entries across hook processes. A failure or incomplete reconstruction is never cached.

## Goals and non-goals

- Preserve all existing source proof, artifact, receipt, and freshness requirements.
- Reduce repeated work in predecessor preparation for large reviews.
- Keep hook-time validation and any future cross-process cache as separate measured work.
- Do not change reviewer prompts, model budgets, locale scope, review scope, or proof thresholds.
- Keep the optimization independent of the matched #1830 Luna benchmark.

## Anti-goals

- Never let a memo hit stand in for rechecking current artifacts, inputs, receipts, or cycle paths.
- Do not trade validation depth or source coverage for a faster preparation result.
- Do not add a durable cache or persistent trust state in this change.

## Validation

- Add a regression fixture with shared predecessor history and assert one canonical reconstruction per unique manifest in one validation process.
- After a successful memo entry, mutate a referenced source-context artifact or other bound input and confirm validation still rejects it.
- Confirm changed manifest or predecessor identities miss the memo, and cyclic predecessor history still fails.
- Run the full candidate verification in CI and measure the reconstruction count on the fixture.
- After #1830 merges, run one Luna panel against the exact final Sol-reviewed source tree and human scope. Compare elapsed time, first-attempt proof validity, and findings. This is the authorized large-batch parity benchmark, not a release gate.

## Release boundary

Ship the memo only after an independent normal review and the exact-head CI gates pass. Keep #1830's final frozen Sol identity supplied by its owner; do not infer the benchmark scope from the merged branch.
