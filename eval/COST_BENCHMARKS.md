# Correctness, time and cost benchmarks

Compare two frozen plugin versions with local mechanical checks and bounded single-seat experiments. Results retain source hashes and modes, sealed fixtures, prompts, raw streams, findings, audits, elapsed time and token categories. This lane launches no availability probes or paid scoring calls.

## Run

```bash
python3 eval/cost_bench.py prepare --baseline 4151007 --out /tmp/rev-bench-wave1 --max-calls 4
python3 eval/cost_bench.py local --out /tmp/rev-bench-wave1 --repetitions 5
python3 eval/cost_bench.py live --out /tmp/rev-bench-wave1 --timeout 600
python3 eval/cost_bench.py report --out /tmp/rev-bench-wave1
```

Use a new output directory for another experiment. `--candidate` defaults to the current checkout and includes untracked plugin helpers. Local checks spend zero provider executions. Live runs require the passing local result and the configured latest Sol/Luna selectors at xhigh. The selected reviewer defaults to Luna; `--reviewer codex-sol` selects Sol. Preparation resolves provider catalog entries without paid probes and freezes the exact roster. Rendering evidence uses an unprobed three-seat roster without launching the other rows. A changed catalog resolution refuses live resumption.

The two cases run baseline/candidate and candidate/baseline. A disk-backed locked ledger reserves each execution before launch. A reserved execution is never retried, including after interruption. Authentication, quota or transport failures stop the active invocation and keep partial logs. A deadline terminates the owned process group. The cap counts reviewer executions, which can contain multiple provider HTTP requests or internal transport retries.

`report.json`, `report.csv` and `report.md` contain raw results. Altered frozen source, fixture, model identity, rate card or benchmark engine refuses resumption. The reviewed fixture roots remain outside the truth directories. No full Council receipt or panel certification is produced.

Preparation sets `git archive` to `tar.umask=0022`, preserving executable bits while
matching normal checkout permissions. Ambient archive settings cannot add group-write
bits and break staged source identity. Preparation also saves the exact engine and common usage helper. After changing the checkout's harness, regenerate an existing run's report with its archived engine:

```bash
python3 /tmp/rev-bench-wave1/engine/eval/cost_bench.py report --out /tmp/rev-bench-wave1
```

This command retains the original identity checks and launches no reviewers. Temporary reviewed roots and controlled test copies can be made writable for setup; frozen source and truth snapshots keep their permissions.

## Correctness

The original cost-v1 fixtures each contain two planted regressions, two baseline checks and four clean controls. Larger suites below use independent multi-file faults and repaired clean twins. Oracles prove the regressions occur; mutation tests prove the oracles fail when the regressions are restored. The reviewer sees source and the change, with no oracle or defect descriptions in its repository.

Keyword and source-range matches are suggestions. Inspect every finding, then write `runs/<case>/<version>/adjudication.json`:

```json
{
  "findings_sha256": "canonical reviewer-result hash from measurement.json",
  "dispositions": [
    {"finding": 0, "verdict": "true_positive", "defects": ["truth-id"], "reason": "Source and oracle demonstrate the reported regression."}
  ]
}
```

Adjudication must cover every finding exactly once. Other verdicts are `false_positive`, `valid_extra` and `duplicate`, with empty defect lists and a reason. Rerun `report` after adjudication. Recall is distinct truth defects found divided by planted defects. Precision counts true findings and verified extras, excluding duplicate reports. Empty findings have unknown precision. Schema validity, incomplete proof and read-audit validity remain separate from semantic correctness. Failed attempts and invalid pairs retain their usage; invalid pairs do not produce qualified savings percentages.

## Time and cost

- Local compilation includes session setup, evidence preparation when enabled and prompt rendering. One warmup is excluded; retain all samples plus median and range. It excludes provider latency.
- Provider wall time runs from adapter start to exit, including private-home setup and cleanup. It excludes rendering, validation, audit and human adjudication.
- A common frozen collector reads both versions' raw streams. Input includes cached input; reasoning is already included in output. Missing categories and dollars are unknown.
- Estimated Standard credits use the selected model's dated input, cache and output rates, divided by one million. Unknown future model rates refuse preparation; a model selector never silently inherits an older model's price. Cache writes have no separate credit charge. The dated rate card links to [official Codex pricing](https://learn.chatgpt.com/docs/pricing). This estimate does not measure cash paid or subscription capacity.
- Report observed cache share and uncached input separately. Server caches cannot be flushed here. Reverse case order reduces one ordering bias, but two pairs do not establish statistical significance or quality equivalence.

The local contract failure scenario replaces the roster executable with a counting stub and the fixture runner with an intentional failure. A change from one probe to zero demonstrates launch ordering, with no measured avoided tokens or dollars. Native accounting replay measures fidelity against known request IDs, not provider savings. The context helper's compact output and local watch demonstrate zero provider executions, with no historical host-cost counterfactual.

Keep the suite ID, exact source identities, CLI version, model, effort, rate card and raw cache categories when comparing future runs. Existing `eval/bench.sh` remains the separate multi-seat held-out simplicity evaluation.

## One-case context experiment

`--suite eval/fixtures/cost-v2` selects one evidence case for a two-execution pair.
The original cache regressions and oracle are unchanged. An unchanged presentation
module and neutral decision history exercise relevant-context routing. Both versions
give the measured Luna seat the same security-state-api specialist bundle; the
unlaunched Sol row owns the combined full-state bundle. This is a specialist canary,
so its results cannot be directly pooled with the earlier cumulative-owner runs.

```bash
python3 eval/cost_bench.py prepare --baseline <wave2-commit> --suite eval/fixtures/cost-v2 --out /tmp/rev-context-pair --max-calls 2
python3 eval/cost_bench.py local --out /tmp/rev-context-pair
python3 eval/cost_bench.py live --out /tmp/rev-context-pair --timeout 600
python3 eval/cost_bench.py report --out /tmp/rev-context-pair
```

The sealed case's `context.md` is the sole decision text. Its sparse route template
is bound to that text's SHA-256 and the prepared material tree before rendering.
The archived wave 3 candidate routed global and relevant decisions and restored the
full digest before repository expansion. Its combined optimization was discarded
after a negative paired result. Current rendering supplies full decision history;
the route template is retained as experimental fixture data. Packet bytes and
delivered digest bytes are local size metrics, not
provider-token or credit savings. One pair has ordering bias and cannot establish
quality equivalence or production panel savings.

## Staged experiments

Measure model settings before changing workflow. A two-case candidate-only stage
reserves at most two executions; its immutable source and engine remain usable
while the checkout changes. Create a second two-call stage after the workflow
change, using the first stage's exact candidate commit as the new baseline.

```bash
python3 eval/cost_bench.py prepare --baseline <wave1-commit> --out /tmp/rev-profile --variants candidate --max-calls 2
python3 eval/cost_bench.py local --out /tmp/rev-profile
python3 eval/cost_bench.py live --out /tmp/rev-profile
# Commit the measured source before making the workflow changes.
python3 eval/cost_bench.py prepare --baseline <profile-commit> --out /tmp/rev-workflow --variants candidate --max-calls 2
python3 eval/cost_bench.py local --out /tmp/rev-workflow
python3 eval/cost_bench.py live --out /tmp/rev-workflow
python3 eval/cost_bench.py report --out /tmp/rev-workflow --reference /tmp/rev-profile
```

Adjudicate each stage's findings before comparing. The reference comparison refuses
model, effort, profile, fixture, CLI, rate, collector, engine or baseline-source drift.
It retains the first report and hashes its manifest rather than modifying its
measurement rows. All controls precede candidates, so cache and temporal ordering
remain confounders. Two stages with caps of two authorize four executions total;
creating another batch does not confer another usage budget.

Earlier Terra/max measurements use their archived engine and rate card. A migration
comparison against those measurements changes model and effort, and must be labeled
as a historical reference, separate from a workflow-only comparison.

## Complex cases and numeric quality

`--suite eval/fixtures/cost-v3` selects a 700-line dispatcher across nine Python
files plus repository instructions, and a wholly correct twin retaining harmless
edits. Six planted faults require following tenant identity, lease generations,
retry clocks, cancellation, transactional rollback and partial acknowledgement
contracts across modules. Truth, independent repair mutations and behavior rubrics
remain outside both reviewed source roots. One paired suite needs four executions;
a candidate-only stage needs two. Record a finite cap for each stage within the
authorized experiment budget or standing autonomous testing scope.

Quality v1 is a fixed 0-100 score:

| Component | Maximum points | Evidence |
| --- | ---: | --- |
| Severity-weighted defect recall | 55 | Complete source/oracle adjudication; P0/P1/P2/P3 weights 8/4/2/1. |
| Precision | 15 | All distinct findings adjudicated, including valid extra findings and false positives. |
| Citation accuracy | 10 | Exact fault-range overlap plus manual evidence validation. |
| Critical-flow coverage | 15 | Gapless audited source reads for every private flow; packet reads qualify only for the current snapshot. |
| Useful hypotheses | 5 | Manually verified or refuted scenarios supported by the required source reads. |

A clean case awards the recall component for specificity only when there are zero
false positives. Empty clean results have an explicit precision/citation convention;
an empty defective result receives zero outcome points. Novel, grounded scenarios
are tracked separately and can substitute at most one untested hypothesis. More
prose earns no additional credit. Exact validated snapshot packets can establish
flow exposure without redundant rereads; base-revision packets cannot. Coverage
proves exposure to source, not understanding;
hidden reasoning is not available and is never requested or scored.

After `adjudication.json`, write a complete `behavior-adjudication.json` using the
[versioned scoring contract](../docs/superpowers/specs/2026-09-30-review-quality-score.md).
The envelope binds the case, rubric, entire result, audit and evidence manifest.
Reporting verifies original artifact hashes and independently replays the frozen
read auditor before crediting flow coverage. Missing provenance, severities, rubric
or complete adjudication leaves the corresponding score unknown. Legacy results
can show a core score out of 80 when sufficient evidence exists; it is not silently
rescaled into a 100-point score.

JSON exposes every component, unavailable reason, policy identity and paired delta;
CSV and Markdown show quality and core scores. Default retention requires valid
proof, quality at least 90/100, weighted recall at least 90%, all planted P0/P1 found,
no added false positives, and a paired drop no larger than 3 points. A cost saving
with a failed quality gate is discarded. A passing small suite is evidence for an
experiment, not statistical equivalence or full-panel certification. Freeze this
policy and score version when comparing runs; recalibration requires replaying both
sides using a newly versioned scorer.

Each variant also has a descriptive equal-case mean and minimum out of 100,
using `quality-v1` and aggregation version `quality-equal-case-v1`. A known
aggregate requires every expected frozen case exactly once, with valid,
provenance-confirmed full scores and matching case/rubric identities. Missing,
invalid, unconfirmed, core-only or mixed-version scores leave both aggregate
values unknown; a known subset is never averaged. Reports show complete/expected
case counts, and JSON records exact identities and unavailable reasons.
Per-case retention gates remain required even when the aggregate mean is high.

A retained control can be reused without another baseline execution using
`report --reference <frozen-pair> --reference-variant baseline` on a later
candidate-only stage. The selected reference source must exactly match the new
baseline; all other identity checks still apply. This saves development calls, but
increases temporal separation and does not create a fresh contemporaneous pair.
Reusing a control does not erase failed or invalid attempts from either ledger.
Reference comparisons produce both variant summaries from the paired cases and
preserve the reference's JSON, CSV and Markdown report files.

## Independent build-cache holdout

`--suite eval/fixtures/cost-v4` selects a different 541-line subsystem across ten
Python modules and its repaired clean twin. Five independent faults cover recursive
cache identities, compiler options, transitive invalidation, active artifact
ownership and complete manifest publication. Eleven clean controls and isolated
repairs produce 32 oracle observations per case. Shared immutable blobs and private
project heads exercise a different boundary from dispatcher tenant deduplication.

```sh
python3 -m unittest discover -s tests -p test_build_fixtures.py -v
python3 eval/fixtures/cost-v4/seal_fixture.py
python3 eval/cost_bench.py prepare --baseline <control-commit> --suite eval/fixtures/cost-v4 --out /tmp/rev-build-holdout --max-calls 4
python3 eval/cost_bench.py local --out /tmp/rev-build-holdout --repetitions 5
python3 eval/cost_bench.py live --out /tmp/rev-build-holdout --timeout 900
```

Adjudicate and report using the same frozen quality-v1 contract. Truth, executable
oracles, references and rubrics remain outside the review checkouts. The seal binds
dated historical scorer references; compatibility checks separately validate the
current API. A reporting-only source change therefore does not invalidate the
fixture's historical provenance. Compare identical case and rubric identities,
and retain per-case gates across both domains before keeping an optimization.
