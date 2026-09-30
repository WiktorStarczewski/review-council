# Wave 3: lean packets and relevant decision digests

The tested wave 3 candidate reduces visible context, but this paired canary shows no cost or time saving.
The candidate attempt costs 1.0% more and takes 25.4% longer. Its original audit
also rejects two byte-complete reads, so the frozen report retains an invalid pair.

## Measurement

Exactly two reviewer executions ran: one baseline and one candidate. No paid probes,
graders, replacement reviewers or retries ran. Both transport exits are successful.
The model is frozen at `gpt-6-luna`, xhigh, with CLI `0.159.0` and the September 30
Standard credit rate card. Dollars and subscription capacity remain unknown.

| Metric | Wave 2 baseline | Wave 3 candidate | Observed attempt change |
| --- | ---: | ---: | ---: |
| Estimated credits | 0.195727 | 0.1976955 | +1.0% |
| Provider wall time | 140.05 s | 175.67 s | +25.4% |
| Compile + provider + validation + audit | 143.34 s | 179.13 s | +25.0% |
| Input tokens | 216,400 | 283,701 | +31.1% |
| Uncached input | 31,312 | 25,909 | -17.3% |
| Cached input | 185,088 | 257,792 | +39.3% |
| Output tokens | 5,694 | 5,478 | -3.8% |
| Reasoning tokens, included in output | 4,470 | 4,101 | -8.3% |
| Tool calls | 9 | 12 | +33.3% |
| Planted defects found | 2/2 | 2/2 | Same semantic recall |
| False positives | 0 | 0 | Same observed count |
| Original read audit | Valid | Invalid | Not a qualified live pair |

These are observed attempt deltas, including invalid work. The frozen engine
correctly leaves qualified savings percentages unset. Total estimated spend is
0.3934225 credits. Quality adjudications cover every returned finding and bind the
complete result hashes. Both citation ranges include the actual faulty lines.
Tenant severity changes from P1 to P0; severity calibration is unmeasured.

The cost arithmetic uses the [dated Standard rates](../eval/rates/codex-standard-2026-09-30.json),
linked to [official pricing](https://learn.chatgpt.com/docs/pricing). Lower uncached
input saves 0.0135075 credits and lower output saves 0.0027. Extra cached input
costs 0.018176, exceeding those savings. Cached tokens still have a price.

## Context fidelity and local performance

| Representation | Baseline | Candidate |
| --- | ---: | ---: |
| Measured-seat packet bytes | 3,968 | 2,010 |
| Source entries | 4 | 4 |
| Original source bytes | 1,092 | 1,092 |
| Initially visible decision bytes | 2,305 | 748 |
| Initially visible decision lines | 24 | 8 |
| Live prompt words | 1,421 | 1,232 |
| Live prompt bytes | 10,047 | 8,977 |
| Median local compilation, five samples | 2.899 s | 2.884 s |

Packet bytes fall 49.3%, initial digest bytes 67.5%, and prompt words 13.3%.
Rich source ranges, required segments, omitted ranges and allocation remain identical.
One excluded warmup precedes five local samples per version. Compile ranges are
2.748-3.282 s and 2.811-3.270 s. The small median difference is not a demonstrated
local performance improvement.

The candidate restores all 2,305 decision bytes before repository expansion.
It also performs an empty EOF check and an additional repository discovery call.
The smaller initial digest therefore does not remove that history from the complete
review conversation. More tool calls and accumulated cached history accompany the
higher processed-input count. One execution cannot establish their causal share of
the elapsed-time difference.

## What changed

- Packet v2 retains exact content, path, line bounds, reasons and base/snapshot
  provenance. Repeated cryptographic and routing fields stay in the rich manifest.
- Allocation still uses rich v1 sizes. Shards, order, omissions and required source
  segments stay fixed. Strict projection checks accept genuine v1 and v2 payloads.
- Optional `context.routes.json` annotates the sole authored `context.md`. Globals,
  unclassified decisions, unknown paths and uncertain or stale metadata remain visible.
- Full-state and unenforced seats receive the full digest. Routed specialists must
  restore exact bounded full context before expanding repository evidence.
- Active validation binds current decisions. Historical replay accepts original
  digest proof only after all five sealed result-artifact hashes still match.

Annotations can wrongly label a global decision as local. The tested routing was optional;
uncertain decisions belonged in the global set. Its archived tests cover late delivered output,
partial and altered proof, native line formatting, source projection tampering,
two-round history and replacement receipt mutations.

## Preserved failure and offline repair

The candidate read every decision byte with `sed -n '1,240p'`, then checked
`241,480` and received empty output. The new digest checker incorrectly invalidated
the completed proof on that EOF check. The candidate also read all 31 evidence-index
lines with one bounded window. The existing index checker required a literal full-read
command and rejected the byte-identical bounded result.

The original stream, audit, measurement and engine remain unchanged. Narrow offline
fixes address these two cases: exact empty EOF checks after complete restoration get
no additional proof credit, and a single bounded index window must deliver the entire
original index byte-for-byte. Partial, altered, late and compound reads remain rejected.
Offline replay results and the repair source identity are recorded separately from
the live candidate identity. Corrected replay passes with both citations intact;
its digest proof covers all 24 lines and 2,305 bytes. The 31 original candidate files
remain byte-identical. Only the auditor and its regression tests differ from the
frozen plugin source. No third reviewer execution was used in this experiment.

## Reuse and limits

The [benchmark guide](../eval/COST_BENCHMARKS.md) documents the new `--suite` option.
`cost-v2` retains the original cache bugs and oracle, adds an unchanged presentation
module and neutral decision history, and assigns the measured seat the same specialist
role in both versions. The unlaunched Sol row owns the full-state bundle.

This case differs from wave 2's cumulative-owner measurements, so its percentages
cannot be pooled into a cumulative savings estimate. Baseline runs first; server caches
cannot be flushed. One paired case cannot establish quality equivalence, clean-case
specificity, cross-component recall, panel savings or general time/cost effects.

The combined packet/digest implementation was discarded after this negative result.
Its frozen source remains available for reproduction; the active branch retains the
wave 2 behavior. The independent complete bounded-index audit correction is retained
as a correctness fix. Packet compression alone needs a separate experiment before
it can qualify as a retained optimization.

Further cost work should target proof turns, failed-seat
relaunches and repeated panels, with the same acceptance and source-coverage obligations.
The [wave 2 report](cost-benchmark-wave2-2026-09-30.md) retains the broader experiment backlog.

Sanitized measurements: [wave3-2026-09-30.json](../eval/results/wave3-2026-09-30.json).
Complete private artifacts remain in `wave3-context-20260930`, including the archived
engine, raw streams, adjudications, local samples and representation counts.

Full Council certification and installed-plugin activation remain separate from this
two-execution benchmark. The production roster retains latest Sol, latest Luna,
Opus and Sonnet; the benchmark budget does not reduce its seat count.
