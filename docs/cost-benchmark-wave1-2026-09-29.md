# First-wave benchmark results

Four live Terra runs measured 6.8% fewer estimated Standard credits and 14.7% less provider wall time for the first wave. Both versions found all four planted defects with zero false positives. These two small cases support keeping the first wave, but do not establish quality equivalence or an expected production saving.

## Live comparison

| Case | Credits, baseline | Credits, first wave | Reduction | Seconds, baseline | Seconds, first wave | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ledger, legacy mode | 2.87253 | 2.58977 | 9.8% | 77.91 | 62.19 | 20.2% |
| Cache, evidence mode | 4.04434 | 3.85659 | 4.6% | 109.80 | 97.88 | 10.9% |
| Combined | 6.91687 | 6.44636 | 6.8% | 187.71 | 160.08 | 14.7% |

Credits use reported live token categories and the dated Standard rates from [official pricing](https://learn.chatgpt.com/docs/pricing). They are estimates, not reported cash charges or subscription capacity. The CLI returned no dollars. The four successful executions together used an estimated 13.36323 credits. Two earlier routing failures returned no usage and remain unknown additional cost.

| Token category | Baseline total | First-wave total | Reduction |
| --- | ---: | ---: | ---: |
| Input, including cached input | 331,307 | 328,168 | 0.9% |
| Uncached input | 58,923 | 58,856 | 0.1% |
| Cached input | 272,384 | 269,312 | 1.1% |
| Output, including reasoning | 8,696 | 7,190 | 17.3% |
| Reasoning subset of output | 6,721 | 5,267 | 21.6% |
| Processed input plus output | 340,003 | 335,358 | 1.4% |

Most of the estimated saving came from lower output. Prompt words shrank much more than total provider input. Ledger uncached input rose 2.3%; cache uncached input fell 2.1%. Both versions completed four tools in the ledger case and eight in the cache case. This experiment does not isolate which first-wave change caused a difference, and stochastic reasoning length can change both credits and time.

Provider time includes adapter setup and cleanup. Adding rendering, validation and audit gives 190.38 seconds for baseline and 162.85 seconds for the first wave, a 14.5% reduction. Human adjudication is excluded.

## Correctness

| Check | Baseline | First wave |
| --- | ---: | ---: |
| Planted defects found | 4 / 4 | 4 / 4 |
| Recall | 100% | 100% |
| False positives | 0 | 0 |
| Finding precision | 100% | 100% |
| Schema and read audits | 2 / 2 passed | 2 / 2 passed |
| Incomplete proofs | 0 | 0 |

Every returned finding was inspected against the source and sealed runtime checks. Hash-bound adjudication confirms the quota equality and exclusive window endpoint defects in the ledger, and the tenant key and nested read alias defects in the cache. There were eight true findings across four executions, no duplicates and no additional claims to classify. Each version independently identified the same four defects.

Both fixtures pass all eight oracle checks, sixteen total. Mutation tests prove each planted-regression check fails when that regression is restored. These cases are deliberately small: this result does not measure large-repository recall, subtle concurrency bugs, severity calibration, multi-seat diversity or later review-and-fix rounds. It produces no full Council certification and does not review the implementation of the first wave itself.

## Local mechanics

The network-ready batch retained five compilation samples per case/version after one excluded warmup.

| Measurement | 0.5.6 | First wave | Interpretation |
| --- | ---: | ---: | --- |
| Legacy prompt words | 1,051 | 852 | 18.9% smaller |
| Evidence prompt words | 1,191 | 1,093 | 8.2% smaller |
| Legacy median compilation | 0.521 s | 0.617 s | 96 ms slower |
| Evidence median compilation | 2.082 s | 2.154 s | 72 ms slower |
| Roster probes after local contract failure | 1 | 0 | Counting stub, zero real provider calls |
| Native replay input/output | 0 / 0 | 17 / 9 | Ground truth is 17 / 9 |

The first wave's briefing contains 32 words and reports certification as `not evaluated`. Its local watch uses zero provider executions. The probe result measures rejection ordering, not avoided dollars. Native replay measures accounting fidelity, not a saving. Before live measurements, 145 Python tests passed, including 55 benchmark tests; the complete plugin gate is a separate verification step.

An earlier local batch measured compilation differences of 61 ms and 58 ms. The variation between batches is retained in the raw samples; neither batch demonstrates faster compilation.

## Reproduction and evidence

- Baseline commit: `4151007`, version 0.5.6. Candidate: the frozen uncommitted first-wave plugin tree.
- Model: `gpt-5.6-terra`, effort `max`, CLI 0.159.0, ordinary prompt mode.
- Order: ledger baseline/candidate, cache candidate/baseline. No paid probes, scoring calls or automatic reviewer retries.
- Common usage collector: the candidate's frozen normalizer reads both raw streams. Reasoning is already in output; missing categories and dollars stay unknown.
- Successful batch: `wave1-20260930-network`, four of four reservations completed with valid proofs and complete adjudications.
- Preserved transport failures: `wave1-20260929` at 17.28 seconds and `wave1-20260930-live` at 17.13 seconds. Both failed during workspace routing, returned no findings or terminal usage, and stopped their batches.

The [benchmark guide](../eval/COST_BENCHMARKS.md) contains reusable commands and the adjudication format. Each output directory retains frozen source and truth identities, reviewed roots, prompts, raw streams, findings, audits, execution ledger, timing samples and JSON/CSV/Markdown reports. The successful batch also contains complete adjudications and a supplemental aggregate report. Earlier failures remain separate from qualified pair measurements.

The subsequent integration gate exposed setup failures when copied fixtures retained read-only permissions. The harness and one prompt test now make only temporary working copies writable. The harness also automatically archives its engine, with two additional regression tests. All 147 Python tests pass in the frozen tree. The measured snapshots, first-wave runtime code, truth and live results are unchanged. All three retained batches contain the exact engine that produced them; regenerate their reports with that archived engine.

Server caches cannot be flushed. Reversing case order reduces one ordering bias but two pairs cannot establish statistical significance. Future comparisons should keep these cases as inexpensive canaries and add held-out realistic cases and repeated paired runs before relying on a production savings or quality claim.
