# Packet-only experiment and numeric review quality

Lean packets reduce measured credits by 24.6%, but fail the frozen quality gates and are discarded.

| Case | Baseline quality /100 | Candidate /100 | Credits change | Provider time change |
| --- | ---: | ---: | ---: | ---: |
| Complex dispatcher | 92.50 | 83.50 | -33.2% | -25.2% |
| Clean dispatcher | 91.25 | 88.75 | -3.7% | -4.5% |
| Equal-case mean | 91.88 | 86.13 | -24.6% pooled | -20.2% pooled |

Every case must pass independently. A mean is descriptive and cannot override a lost
critical defect, invalid proof or false-positive regression.

## Quality measured

The complex case has 700 source lines across nine files, six independently reproducible
faults, six critical flows, ten hypotheses and eleven clean behavior controls. Its clean
twin repairs all faults and retains only harmless wording and diagnostic changes.
Private truth and scoring rubrics never enter reviewer prompts or reviewed source roots.

[Quality v1](superpowers/specs/2026-09-30-review-quality-score.md) awards 55 points for
severity-weighted recall, 15 for precision, 10 for citation accuracy, 15 for audited
critical-flow exposure and 5 for manually substantiated hypotheses. It measures
observable evidence, not hidden reasoning or comprehension. All four scores bind the
complete result, truth, rubric, original stream, replayed audit and evidence manifest.

| Complex-case component | Maximum | Baseline | Candidate |
| --- | ---: | ---: | ---: |
| Severity-weighted recall | 55 | 50 | 45 |
| Precision | 15 | 15 | 15 |
| Citation accuracy | 10 | 10 | 6 |
| Critical-flow exposure | 15 | 15 | 15 |
| Useful hypotheses | 5 | 2.5 | 2.5 |

Both versions report five true findings and no false positives. The baseline finds all
five P1 faults and misses the P2 retry-clock fault. The candidate finds that P2 but misses
the P1 lease-generation fence. Two candidate citations omit the actual faulty line.
Both expose every critical flow. Broad source exposure alone does not establish that
all important defects were recognized.

The clean twin returns empty findings on both versions. Each exposes the diagnostic
flow but leaves a gap in the ready-list ownership flow. The baseline substantiates two
predefined hypotheses and one grounded novel refutation; the candidate substantiates
one predefined hypothesis. These lower scores describe evidence depth despite correct
empty findings. Novel scenarios contribute at most one hypothesis substitution.

Retention requires valid proof, at least 90/100, at least 90% weighted defect recall,
all P0/P1 defects found, no added false positives and no more than a three-point loss.
The complex candidate fails four gates; the clean candidate falls below the quality
floor. The active runtime retains wave 2 packet behavior.

The existing code prompt limits findings to five, while this fixture contains six
independent faults. That quality constraint warrants a separate experiment; no scoring
weight or truth severity was changed after viewing these results.

## Cost and timing

Exactly four Luna/xhigh executions ran in opposite case orders. No paid probes,
graders or automatic retries ran. All schemas and original read audits are valid.

| Pooled metric | Baseline | Candidate |
| --- | ---: | ---: |
| Estimated Standard credits | 0.5633245 | 0.4246130 |
| Provider wall time | 312.99 s | 249.90 s |
| Tool calls | 27 | 24 |

Complex-case packets shrink from 22,401 to 11,906 bytes; clean packets from 2,057 to
985 bytes. Source entries, exact source bytes, allocation and omissions are identical.
The rich machine manifest remains intact. Packet-only changes isolate this representation
from wave 3 decision routing; prompts and audit obligations remain unchanged.

The model is `gpt-6-luna` at xhigh, CLI `0.159.0`, with the September 30 Standard credit
rate card. [Sanitized identities and components](../eval/results/wave4-2026-09-30.json)
freeze both plugin sources, all five benchmark engine files, the case suite and policy.
The control includes wave 2 plus the independent complete bounded-index audit fix.
Private raw artifacts and executable snapshots remain in `wave4-packets-complex-20260930`.

Two cases cannot establish statistical quality equivalence. Cache state cannot be
reset, elapsed time varies, and estimated credits do not measure dollars or subscription
capacity. This single-seat screen does not certify a production Council panel.

## Historical comparison

[Retrospective core scores](../eval/results/quality-history-2026-09-30.json) cover the
latest-model controls, wave 2 and wave 3. Their maximum is 80, without rescaling. The
wave 2 ledger score drops from 80 to 75 because one citation omits the faulty predicate;
the cache scores remain 80. Original frozen cases and results are untouched. Severity
annotations were added after those runs and hashed separately. Missing behavior rubrics
and provenance keep full scores unknown. The original invalid wave 3 candidate stays
noncertifying despite its 80-point semantic core.
