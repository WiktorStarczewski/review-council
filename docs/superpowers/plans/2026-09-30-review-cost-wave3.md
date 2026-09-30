# Review cost wave 3

## Objective and authorization

Implement lean source packets and relevant decision digests, then compare correctness,
provider time and estimated credits. Wave 2 is committed at `4571f99`; the new branch
is `perf/review-cost-third-wave`. The paid budget is exactly two Luna reviewer
executions on one paired evidence case. This limits the benchmark, not production
seat count. No paid probes, graders, replacements or retries.

## Invariants

- Discover latest Sol/Luna and freeze exact model/effort; use xhigh for both.
- Keep the production four-seat panel, canonical bundles and proof obligations.
- Preserve exact source bytes, paths, original ranges, reasons and base/snapshot provenance.
- Preserve rich manifest metadata, selection, shard membership/order, omissions and required segments.
- Keep packet names and outer manifest/receipt/read-audit schemas compatible.
- Never heuristically classify free-form decision prose or maintain two copies of it.
- Global, unclassified, uncertain or stale decisions remain visible.
- Full-state/cumulative and unenforced seats receive the full decision digest.
- Before routed reviewers expand repository evidence, restore full hash-bound decision context.
- A missing or partial required full-context proof cannot become a valid result.
- Old cost-v1 fixtures and historical frozen engines remain unchanged.

## Packet representation

Emit payload schema version 2 with entries containing `path`, `line_start`,
`line_end`, `reasons`, `revision` and `content`. Remove repeated seat/tree/shard
headers and per-entry cryptographic/routing metadata from the model-facing packet.
Keep those values in the validated rich manifest. Continue using rich v1 sizes for
allocation and required-byte accounting so lean rendering cannot silently select
more, less or different source. Validate v2 by exact canonical projection; retain
strict v1 compatibility. Check content hashes offline and original pinned bytes
when source validation is fresh.

## Digest routing

Keep `context.md` as the sole text source. Optional `context.routes.json` binds its
raw SHA-256 and material snapshot tree. Explicit non-overlapping one-based line blocks
may name literal repository paths; empty paths mean global. Retain unannotated lines,
globals and unknown paths. Relevant specialist paths derive from authenticated component
boundaries, packet/required/omitted ranges, instructions and plan obligations.
Invalid, stale or ambiguous annotations fall back to the full digest.

For routed mode declare the exact session digest path/hash in Scope. Authorize bounded
original reads of that path without a full-read exemption. Require gapless exact
full-digest proof before repository expansion; it grants no source citation credit.
Preserve current read limits and proof ordering. This fallback can reduce savings or
add a tool turn. Measure actual behavior rather than assuming routing is cheaper.

## Work ownership

- Packet/integration worker: rev-evidence.py, rev-prompt.sh, t-evidence.sh and relevant
  skill guidance. Integrate the pure routing helper without duplicating decision prose.
- Digest worker: lib/decision_digest.py, review-read-audit.py, t-read-bounds.sh and
  focused pure-helper tests. Coordinate the helper interface with packet/integration.
- Root: benchmark runner, new fixture suite, benchmark tests, docs, task plan,
  inventory reconciliation, measurements, adjudication, final gate and delivery.

No worker commits or provider calls. Shared files require explicit coordination.

## Verification and measurement

- [ ] Add failing packet projection/compatibility/tamper tests and digest routing/proof tests.
- [ ] Implement both changes and pass focused contracts with source stable.
- [ ] Add a single-case suite with the same two cache defects, unchanged unrelated module,
      neutral decision history and explicit routing sidecar; no defect descriptions in context.
- [ ] Give Sol the canonical first combined/full bundle and Luna security-state-api in both
      versions, so the measured seat exercises specialist routing. Only Luna runs.
- [ ] Freeze wave 2 baseline and wave 3 candidate, truth, role, model, effort, rate and engine.
- [ ] Pass local oracles, metadata/source fidelity, routing fallback and accounting checks.
- [ ] Run exactly two reviewer executions, one per version, with failures preserved.
- [ ] Inspect every finding and save complete hash-bound adjudications.
- [ ] Report provider categories/time/credits separately from packet/digest size proxies.
- [ ] Run the full configured gate before commit and feature push; open a separate draft.

## Quality limits and delivery

One paired case cannot establish quality equivalence, clean-case specificity, severity
calibration, realistic cross-component recall or full-panel savings. Full-context fallback
may erase routed savings, and a scope annotation can misclassify an inherently global
decision. Keep routing optional and conservative; document this risk. Report negative
or mixed measurements honestly. Full Council review remains separate while Claude
quota is unavailable. No release, merge or global installed-profile activation is included.

## Observed outcome

The original two-call experiment completed. Estimated credits rose 1.0% and
provider time rose 25.4%; both results found the two planted bugs, but the original
candidate proof audit failed. The narrow corrected offline replay is separate from
the immutable live measurements. The combined packet/digest runtime was discarded.
Its archived source and tests remain available for reproduction. Only the independent
complete bounded-index proof correction remains active.

The initial full gate was canceled when the losing runtime was removed; cancellation
is not a pass. The replacement gate covers the active source and reusable benchmark
additions. Further experiments have fresh source identities and execution ledgers
under the user's subsequent autonomous-continuation authorization.
