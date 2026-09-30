# Second-wave benchmark results

Compact reviewer startup used 12.0% fewer estimated Standard credits and 14.4% less
pooled provider time on two Luna/xhigh canaries. Both versions found all four planted
defects with zero false positives. One candidate citation was imprecise. The combined
red-team/verification schedule removes four launches only when unchanged code has a
current enforced receipt; its full-panel cost and quality remain unmeasured.

## Measured workflow comparison

The model-settings baseline was measured first. The next two calls used the same
resolved model, effort, fixtures, CLI, collector, rate card and benchmark engine.
Only the candidate plugin changed. These calls exercise compact startup; they do
not execute a multi-round Council loop.

| Case | Credits before | Credits after | Reduction | Seconds before | Seconds after | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ledger, legacy mode | 0.1455865 | 0.1226730 | 15.7% | 141.04 | 73.18 | 48.1% |
| Cache, evidence mode | 0.1697525 | 0.1547195 | 8.9% | 93.16 | 127.30 | -36.6% |
| Combined | 0.3153390 | 0.2773925 | 12.0% | 234.20 | 200.48 | 14.4% |

Credits apply reported token categories to the dated Standard rates from
[official pricing](https://learn.chatgpt.com/docs/pricing). They estimate usage credits,
not cash charges or subscription capacity. Dollars remain unknown. All four authorized
calls together used an estimated 0.5927315 credits, with no paid probes, graders or
reviewer retries.

| Token category | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Input, including cached input | 324,580 | 296,539 | 8.6% |
| Uncached input | 59,364 | 52,059 | 12.3% |
| Cached input | 265,216 | 244,480 | 7.8% |
| Output, including reasoning | 8,050 | 6,890 | 14.4% |
| Reasoning subset | 6,017 | 5,191 | 13.7% |
| Tool calls | 13 | 13 | 0.0% |

The 0.0379465-credit difference comprises 0.0182625 fewer uncached-input credits,
0.005184 fewer cached-input credits and 0.0145 fewer output credits. The submitted
review prompts stay at 852 and 1,093 words. The changed 243-word startup contract
replaces generic coding instructions through `model_instructions_file`; the review
contract still supplies exact source, audit bounds and proof obligations. The
configuration field is described in the [official reference](https://learn.chatgpt.com/docs/config-file/config-reference).

These observations support a modest reduction, not a 12% production forecast.
Reasoning and latency vary: the cache case became 36.6% slower despite fewer tokens.
All baseline calls preceded candidate calls, server cache state cannot be reset,
and there is only one draw per case/version. Two runs cannot establish causality
or statistical significance.

Including rendering, validation and audit, machine time fell from 237.38 to 204.66
seconds, or 13.8%. Human adjudication is excluded. Local compilation medians rose
from 0.523 to 0.822 seconds for ledger and 1.980 to 2.874 seconds for cache. Each
median has five samples after an excluded warmup. This wave does not demonstrate
faster local compilation.

## Correctness and limits

| Check | Before | After |
| --- | ---: | ---: |
| Planted defects found | 4 / 4 | 4 / 4 |
| False positives | 0 | 0 |
| Duplicate or extra findings | 0 | 0 |
| Schema and read audits | 2 / 2 passed | 2 / 2 passed |
| Incomplete proofs | 0 | 0 |

Every finding was checked against source and the sealed runtime truth, then given
a complete hash-bound adjudication. Both versions identify quota equality, exclusive
query endpoints, cross-tenant cache collisions and shallow nested payload copies.
The candidate ledger endpoint finding cites lines 50-56, while the faulty predicate
is at line 58. Its semantic claim is correct; audit validity is not proof of perfect
citation precision. The cache tenant finding receives P0 in both stages; severity
calibration is outside this suite.

No realistic concurrency, large-repository, clean-case specificity, repair-round or
multi-seat diversity result is available. Only Luna was live-measured. Sol and the
Anthropic seats were not executed in this budget. This lane does not review or certify
the implementation itself. Full Council review remains pending while Claude quota is
unavailable.

## Model-settings measurement, before workflow changes

Latest selectors resolved to `gpt-6.1-sol` and `gpt-6-luna`, both at `xhigh`.
Production configuration uses `latest-sol` and `latest-luna`, rather than those
historical exact slugs. Newest-family selection refuses unsupported effort instead
of silently picking an older model. Opus and Sonnet retain provider aliases and
supported maximum effort. Resolved identities are frozen before reviewer launch.

| Historical reference | Earlier first-wave Terra/max | Latest-profile Luna/xhigh | Change |
| --- | ---: | ---: | ---: |
| Estimated credits | 6.44636 | 0.315339 | 95.1% lower |
| Provider seconds | 160.08 | 234.20 | 46.3% higher |
| Planted defects found | 4 / 4 | 4 / 4 | same observed recall |
| False positives | 0 | 0 | same observed count |

This is a historical migration reference that changes both model and effort, not
the controlled wave 2 workflow comparison. Its large credit difference principally
reflects model rates, not less review work: input falls only 1.1%, while output rises
12.0%. It cannot establish the cost of a Sol/Luna/Opus/Sonnet production panel.
The current installed plugin and global config require an update before selectors
can be activated there; the source branch and task-specific benchmark profile support them.

## Combined red-team/verification schedule

The final full red-team discovery panel is rendered as verification from the outset.
It retains four distinct seats, all four canonical bundles, composed adversarial
emphases, cumulative integration ownership and sibling-site checks. It may serve final
verification after triage only if no fix follows and the latest authenticated receipt
still covers current source, instructions, scope, roster, model and effort.

| Four-seat adaptive path | Earlier launches | New launches |
| --- | ---: | ---: |
| Large/high-risk, no fix, eligible combined receipt | 16 | 12 |
| Important/adversarial, no fix, eligible combined receipt | 12 | 8 |
| Large/high-risk, fix and one plan seat | 17 | 17 |
| Important/adversarial, fix and one plan seat | 13 | 13 |
| Ordinary, no nontrivial fix | 8 | 8 |
| Ordinary, one plan seat | 9 | 9 |

These are checked schedule contracts, not an executed orchestrator benchmark.
The conditional reduction is 25.0% or 33.3% of launches, not measured provider credits.
It removes one independent review draw. Keeping the four seats and their obligations
does not prove that another draw would find no additional defect.

`current-coverage` reuses the existing receipt constructor and verifier. Local
fixtures accept genuine current verification and authenticated replacement generations,
and reject risk-only or older receipts, incomplete assignments, forged metadata,
modified results/streams/exits, changed source, ignored repository instructions,
changed model/effort and stale pinned references. The check runs before omitting the
separate panel and again before completion. It proves present material identity;
the host must also enforce that no fix followed the combined panel.

Reuse requires enforced CLI generations. A native Agent receipt does not qualify,
so Claude Code panels containing such a seat keep separate verification. Any fix
following the combined panel also requires fresh verification. Ordinary simplicity-only
and explicit numeric schedules retain their existing rules. Missing or empty compact
startup instructions refuse the prompt seat before any CLI call; native review keeps
its existing startup instructions.

## Implementation verification

The complete frozen-tree gate passed 353 shell cases with 4,700 assertions, all
161 Python tests, both plugin validators and the marketplace validator. The new
source remained unchanged during the gate. This proves mechanical contracts, not
full Council review or production quality equivalence.

## Reproduction and evidence

- Model-settings controls: `profile-latest-xhigh-20260930-v2`, two calls.
- Wave 2 candidate: `wave2-context-rounds-20260930-v2`, two calls.
- Fixed live identity: `gpt-6-luna`, `xhigh`, CLI 0.159.0, ordinary prompt adapter.
- Predecessor commit: `b957fa1`; frozen plugin hash `6e43de81bddae0bbca95641e3d579392467220150de1f5092e60077a124508f6`.
- Candidate plugin hash: `d30c9e5af991fe3fd4fef958f0a0d0ac4087de690c390d3311d1cacbe21cc4`.
- Machine-readable summary: [wave2-2026-09-30.json](../eval/results/wave2-2026-09-30.json).
- Commands and adjudication format: [benchmark guide](../eval/COST_BENCHMARKS.md).

The research-notes benchmark directories retain exact source/truth/engine snapshots,
raw streams, reviewed roots, prompts, findings, audits, timings, execution ledgers,
and complete adjudications. Reference comparison authenticates exact model, effort,
profile, truth, CLI, rate card, collector, engine and predecessor source identity.

Two local setup failures made zero reviewer executions: the initial profile freeze
had noncanonical evidence assignment order, and the first workflow archive had Git's
group-write permission bits rather than the measured checkout permissions. Both are
preserved separately. Canonical ordering was fixed before the controls ran. The
successful second stage used process-local `tar.umask=0022`; the reusable runner now
sets that explicitly and its archive regression passes under conflicting ambient
configuration. Frozen paid engines are unchanged. Regenerate these reports with their
archived engines after any harness edit.

## Next cost experiments

These are proposals, with no measured percentage attached. Prioritize credits per
completed review, unique material defects, and failed-call spend over prompt word count.
Existing delta routing, cumulative integration ownership, adaptive ordinary scheduling,
and single-seat plan defaults remain part of the baseline.

| Priority | Experiment | Saving mechanism | Quality guard and evaluation |
| --- | --- | --- | --- |
| 1 | Component-specific decision digests | Stop repeating unrelated settled findings and long disposition histories in every seat | Include global invariants and interaction decisions; expire a disposition when its source identity changes; keep cumulative ownership |
| 1 | Lean source packet rendering | Keep machine-only hashes and repeated binding metadata outside the model-facing source | Preserve exact original bytes, paths, ranges and omissions; mutate Unicode, escaping, stale hashes and missing ranges in local tests |
| 1 | Fewer tool turns for small proof reads | Reduce repeated startup/context processing and serial reasoning | Stay within observed transport ceilings; retain original read order and truncation checks; count actual tool turns and input categories |
| 1 | Failure classification before allowed retry | Avoid a second expensive call for a deterministic contract or routing failure | Preserve the failed stream; still allow transient execution recovery; never turn an invalid result into coverage |
| 1 | Smaller host phase briefing | Reduce host reconstruction of long skills and todo histories | Compose existing scripts with a phase-specific checklist; avoid another large orchestration framework; measure host usage separately |
| 2 | Applicable instruction routing | Exclude rules from unrelated subtrees for specialists | Preserve ancestor/deeper precedence and load newly applicable instructions on expansion; test cross-directory consumers |
| 2 | Exact source reread elimination | Avoid reading unchanged declarations already delivered as proven source | Distinguish old and new bytes, track original locations and preserve necessary consumer expansion; do not replace source with conclusions |
| 2 | Stable instruction prefix | Improve reuse of unchanged contract and tool assumptions | Preserve evidence order, keep dynamic assignment/state later, measure uncached and cached input; never pad the prompt to chase cache hits |
| 2 | Completed sibling continuity | Avoid restarting healthy seats when one assignment fails | Authenticate exact generation, source, model, effort and replacement; broaden fallback only when certification cannot otherwise complete |
| 2 | Root-cause fix completeness | Reduce fix-of-fix rounds caused by missed siblings | Enumerate affected sites once, retain falsifiable regressions and cumulative integration checks; classify whether later findings are original or repair-induced |
| 3 | Typed binary asset evidence | Avoid opaque binary patch payloads on visual changes | Bind base/head blobs and authorize previews; retain actual visual inspection, since a hash cannot prove appearance |
| 3 | Narrow audited tool surface | Reduce schema overhead and accidental unrelated exploration | Keep every read/search ability needed to refute findings; support each tool in transcript audits before enabling it |
| 3 | Finer component boundaries | Avoid import-connected components giving every specialist nearly the full patch | Preserve overlap at APIs, shared state and dispatch; compare unique cross-component defects on realistic cases |
| Research | Retained reviewer sessions | Avoid repeated cumulative context reconstruction between delta rounds | Measure anchoring and stale-state failures against fresh independent rounds; do not make this a production default without held-out evidence |

### Better benchmark coverage

Keep these two tiny cases as cheap canaries. Add held-out cases for concurrency,
rollback/recovery, cross-component APIs, flawed tests, noisy clean changes, and
repair-induced sibling defects. Record per-seat unique P0/P1 findings, recall,
false positives, invalid proofs, retry counts, end-to-end time, and estimated credits
per completed review. Current fixtures have no clean-case specificity test or severity
calibration score. Use repetitions with alternating case order when a new paid budget
is authorized. Test the final four-seat combined panel against separate panels on
unchanged and post-fix code before making a production quality-equivalence claim.
