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

Preparation also saves the exact engine and common usage helper. After changing the checkout's harness, regenerate an existing run's report with its archived engine:

```bash
python3 /tmp/rev-bench-wave1/engine/eval/cost_bench.py report --out /tmp/rev-bench-wave1
```

This command retains the original identity checks and launches no reviewers. Temporary reviewed roots and controlled test copies can be made writable for setup; frozen source and truth snapshots keep their permissions.

## Correctness

Each fixture contains two planted regressions, two baseline checks and four clean controls. Oracles prove the regressions occur; mutation tests prove the oracles fail when the regressions are restored. The reviewer sees source and the change, with no oracle or defect descriptions in its repository.

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
