# Continued cost screens

Numeric quality gates rejected several apparent savings on the complex dispatcher and its clean twin.

| Experiment | Complex quality /100 | Clean quality /100 | Pooled credits change | Provider time change | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Frozen control | 92.50 | 91.25 | Reference | Reference | Control |
| Lean packets, wave 4 | 83.50 | 88.75 | -24.6% | -20.2% | Discard |
| Read transition cues, wave 5 | 92.50 | 91.25 | -10.0% | +15.5% | Discard after fresh pair |
| Default source batching, wave 6 | 78.00 | 91.25 | -14.2% | +3.8% | Discard |
| Material findings without five-item cap, wave 7 | 98.00 | 88.75 | -26.8% | -22.8% | Discard |
| Batching with explicit EOF fallback, wave 9 | 86.50 | 88.75 | +8.8% | +69.7% | Discard |
| Decisive summary cue, wave 10 | 92.50 | 97.50 | -16.5% | +74.0% | Unretained component screen |
| Complete findings and summary cue, wave 11 | 96.33 | 91.25 | -8.5% | -17.1% | Unretained component screen |
| Line-addressed packets, wave 12 | 98.00 | 90.00 | -4.8% | -4.4% | Combination fails holdout |
| Complete checks and line packets, wave 13 | 98.00 | 91.25 | -2.3% | -21.9% | Discard after holdout |
| Combined candidate on build holdout, wave 14 | 98.75 | 86.25 | -14.8% | -19.7% | Discard |

A separate fresh complex-case pair in wave 8 gives the read-cue control 87.5 and
candidate 81.0. Credits fall only 1.0%, while provider time rises 17.0%. This
contradicts the earlier screen's apparent saving. The control itself misses a P1,
showing why one execution cannot establish reliable equivalence.

All comparisons freeze Luna/xhigh, the provider CLI, rate card, case bytes,
quality-v1 rubric and benchmark engine. Waves 5, 6, 7, 9 and 10 reuse the exact wave 4
control identities and measurements to screen ideas cheaply. Waves 8 and 11 use fresh
executions, as does wave 13. Wave 12 compares against the exact wave 11 candidate,
so its reduction is incremental rather than relative to the original control.
Waves 11 and 13 alternate which variant runs first across the two cases. Wave 11's
control scores are 92.50 and 90.00, rather than the original 92.50 and 91.25. Cache state and provider load remain uncontrolled. No paid probes,
graders or automatic retries are used. Credits are estimates from reported usage,
not dollars or subscription capacity.

## Why candidates fail

The five-finding limit constrains the six-defect case. Removing it finds all six
faults with accurate citations in wave 7, but the clean review returns too little
substantiated diagnostic analysis to meet the fixed 90-point floor. That
experiment is discarded independently of its strong complex-case score.

Both batching variants issue compound ranges beyond a file's EOF. These commands
receive no source-exposure credit under the unchanged batch contract, even when
other required proof is valid. The explicit fallback sentence does not reliably
prevent that behavior. The resulting evidence score and cost do not justify
changing the default.

The source-flow component requires gapless exposure of predefined ranges. It
measures which exact source the review can prove it consulted, not understanding.
The hypothesis component requires a concrete verified or refuted claim with its
source. Broad reading, generic reassurance and a longer summary earn no bonus.
A correct clean result can therefore still have insufficient observable depth.
The rubric was frozen before the paid runs and remains unchanged. The score uses
truth severity to weight recall; it does not yet grade the model's severity
calibration. Overstated P0/P1 labels remain a separate limitation.

## Remaining low-cost directions

Two output instructions were tested separately and together: report every
substantiated material defect, and briefly name decisive verified or refuted risks
with the source that settled them. The combined candidate passes both fresh per-case gates, with mean quality
91.25 to 93.79 and minimum quality 90.00 to 91.25. It reports every planted fault
but cites store.py:32 instead of the faulty line 31; that citation loses points.
No private truth or scoring rubric enters the prompt. Neither instruction component
is adopted independently from its passing dispatcher screen.

A line-addressed packet representation preserves exact source bytes, original line
numbers, allocation and rich machine-manifest validation. The initial screen passes
both quality gates, and a fresh combined repeat raises mean quality from 89.63 to
94.63 and minimum quality from 88.75 to 91.25. Its credit saving is only 2.3%:
the complex case costs less, while the clean case costs more. A smaller payload
alone does not qualify as a saving. On the unrelated build holdout, the combination
finds all five faults, including a concrete interaction between collection and
publication. An independent local probe verifies that interaction. Its clean twin
scores only 86.25: too little of the frozen source-flow depth is proven. The control
also scores 86.25 on that twin. This is an absolute depth-floor failure rather than
an observed paired quality drop. The combination is discarded despite its 14.8%
credit saving and 19.7% time reduction on that suite.

Across the four fresh cases in both domains, the descriptive mean rises from
90.91 to 93.56, while the minimum remains 86.25. Pooled estimated credits fall
9.2% and provider time falls 20.6%. The failed clean case still rejects the
combination. The separate two-case holdout mean rises from 92.19 to 92.50, while
the minimum remains 86.25. This illustrates why the numeric mean is descriptive and every per-case
gate remains mandatory. Generic statements about safety cannot replace source
exposure or a substantiated concrete hypothesis.

The adapter already provides one output schema and compact reviewer instructions.
The two frozen control prompts share 5,187 prefix bytes before their repository
field. Only 587 later bytes are renderer-owned repeated text; the remaining shared
tail contains repository rules and round decisions. Prefix reordering removes no
bytes from repeated tool turns. Earlier CLI session metadata may also precede this
prefix, so no paid prefix-reordering canary is justified by current evidence.

Local CLI feature switches can disable auxiliary tools while retaining shell
execution. The actual advertised tool inventory and schema bytes are unavailable
in the streams. A switch accepting a name does not prove safe tool preservation
or token savings. Inventory evidence is required before spending on that canary.

[Quality definition](superpowers/specs/2026-09-30-review-quality-score.md) and
[sanitized measurements](../eval/results/) preserve component scores, exact
identities and per-case gates. Private executable snapshots, raw results, original
streams, adjudications and ledgers remain frozen. Production retains the wave 2
runtime plus the independent bounded-index audit correction. Full Council
certification remains pending while fewer than three allowed seats are available.
