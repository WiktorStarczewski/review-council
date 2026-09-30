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
| Finite patch completion and caller-flow cue, wave 15 | 98.75 | 86.88 | -15.7% | -16.0% | Discard |
| Immutable source batches, wave 16 | Unknown | Unknown | Unqualified | Unqualified | Discard invalid proof |
| Exact producer stderr suppression, wave 17 | 98.75 | 91.25 | -20.0% | -37.7% | Discard after transfer |
| Same immutable candidate on dispatcher, wave 18 | 98.00 | 80.00 | +7.8% | +36.4% | Discard |

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

A finite patch-completion cue removes both extra empty patch reads in wave 15.
Combined with a general caller/state-flow instruction, it finds all five holdout
faults and reports the independently verified collection/publication interaction.
Estimated credits fall 15.7% and provider time falls 16.0% against exact frozen
controls. The clean result proves only one of three private source flows and
scores 86.875, so the combination remains isolated and is discarded. A true
statement that the planner supplies sorted option pairs does not establish every
input-version, fingerprint and output consequence of reordering configuration.
Partial analysis and exposure alone earn no full hypothesis credit.

An immutable Git snapshot producer is measured separately in wave 16. Both
executions finish but exact proof fails: Apple Git emits sandbox confstr/xcrun
diagnostics on stderr before each producer, and captured output merges stderr
with source stdout. The code findings semantically cover all five faults, with a
joint planner citation missing one fault line. Full quality and qualified savings
are unknown. Original streams and audits remain unchanged. A producer-level stderr
correction is tested separately; no arbitrary diagnostic-looking text is stripped
from source output to rescue the failed executions.

The corrected immutable-source candidate passes both build holdout gates in wave 17.
Its exact stdout audits validate two source batches per case. Mean quality is 95.00
and minimum 91.25, with all five faults found and no clean false positives. The
clean result proves two of three frozen source flows and two complete hypotheses;
partial compiler-option analysis earns no additional hypothesis credit. Credits
fall 20.0% and provider time 37.7% against unchanged reused controls. This remains
a passing screen, but the unchanged candidate fails dispatcher transfer in wave 18.
That clean twin reads only jobs.py and worker.py, omitting the storage source
needed by both frozen flows. Quality is 80.00 despite no false positives. The
complex twin finds all six faults with accurate citations and scores 98.00.
Dispatcher credits rise 7.8% and time 36.4%, so the combination is discarded.
Prospective integration stops before any runtime edit or new paid validation.

Native live-file compound proof is independently retired after a real regression
shows its joined output can be attributed to the wrong files. Explicit opt-in
configuration refuses with a standalone-read alternative. Exact standalone LF,
CRLF and unterminated reads still work. This correction preserves old artifacts,
scoring versions and advisory classifications, and makes no performance claim.

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
runtime plus the independent bounded-index audit correction and retirement of
ambiguous native compound proof. Full Council
certification remains pending while fewer than three allowed seats are available.

Complete-case aggregation is reporting added after the frozen live stages. Its
first sealed implementation is commit `17c64af`, using aggregation version
`quality-equal-case-v1`. The original quality-v1 scoring functions and all paid
measurement engine identities remain unchanged. Later records explicitly retain
the aggregation module hash separately from the paid measurement engine.

## Measured cost composition

Fourteen unique executions in waves 11-14 reconcile to 3.001094 estimated credits.
Reused wave 12 controls are counted once. The same dated Luna rate card charges
reasoning once within output; dollars remain unknown.

| Component | Reported tokens | Estimated credits | Credit share |
| --- | ---: | ---: | ---: |
| Uncached input | 454,671 | 1.136678 | 37.9% |
| Cached input | 3,000,064 | 0.750016 | 25.0% |
| Output, including reasoning | 89,152 | 1.114400 | 37.1% |

Cache supplies 86.8% of input tokens, but repeated conversation input still costs
62.9% of credits. Source-read turn consolidation has a concrete causal target.
Aggregate usage cannot identify dispensable output or advertised tool-schema bytes.
Further output limits, tool switches or prefix rearrangements lack the evidence
needed for another paid canary. [Bound totals and inputs](../eval/results/cost-components-wave11-14-2026-09-30.json)
allow this breakdown to be reproduced without access to private streams.

Across the four cases in waves 17 and 18, the mean is 92.00 versus 90.91 for the
reused controls, while the minimum falls from 86.25 to 80.00. Pooled credits fall
7.5% and time 7.7%, but that descriptive aggregate cannot qualify the failed
clean case. [The bound two-domain record](../eval/results/wave17-18-two-domain-2026-09-30.json)
records four new executions and four reused controls explicitly. No fresh paired
validation is purchased for a candidate already rejected by transfer.

## Screening stop condition

The measured representations, output cues, EOF cues and source-turn mechanisms
are exhausted for this pass. None of the wave 3-18 runtime combinations clears
all fixed gates across both complex domains and their clean twins. Production
keeps wave 2 and the independent proof corrections. Negative experiments remain
reproducible; their runtime changes remain isolated. Future paid screens need a
distinct causal target, such as locally validated caller/source closure or actual
provider tool-inventory and per-turn accounting evidence. Rewording the same cues
or lowering the score floor would not justify further spending.
