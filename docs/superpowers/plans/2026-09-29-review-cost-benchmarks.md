# Review cost benchmarks implementation plan

**Goal:** Reuse correctness, time and usage benchmarks to compare frozen plugin versions, starting with 0.5.6 and the first cost wave.

**Architecture:** A provider-free local lane measures mechanical correctness and compiler work. A separate single-seat lane uses each frozen version's renderer and Codex adapter exactly once per scheduled run. One common accounting collector and manually adjudicated sealed truth prevent accounting changes or word matching from becoming apparent review improvements.

**Stack:** Python standard library, Git, existing plugin renderer, adapter, validator and auditor.

## Constraints

- This run allows four reviewer executions: two cases, baseline/candidate then candidate/baseline.
- Live identity is `gpt-5.6-terra`, effort `max`, ordinary prompt execution. No probes, Claude scoring, replacement models or automatic reviewer retries.
- Freeze baseline commit `4151007` and candidate plugin contents including untracked helpers and executable modes.
- Retain prompts, raw streams, source identities, exit statuses, audits, elapsed times, token categories and scored findings outside the reviewed fixtures.
- Report missing dollars as unknown. A dated Standard credit estimate is a separate linear calculation; it does not measure cash or subscription capacity.
- Reasoning is already part of output tokens. Failed executions retain their usage and consume the call budget.
- Evidence rendering may use a production-shaped roster, but only Terra launches. No panel certification or quality equivalence claim follows from these two cases.

## Interfaces and ownership

- `eval/fixtures/cost-v1/<case>/case.json`, `before/`, `after/`, `oracle.py`: sealed runtime truth and reviewed source snapshots. Each oracle must fail on each planted defect and pass on baseline and clean controls.
- `eval/bench_score.py`: `score_findings(case, result, adjudication=None)`. Suggestions are provisional. Confirmed recall and precision require every finding's disposition and a findings hash.
- `eval/cost_bench.py`: freeze, local timing, four-call scheduling, adapter invocation, common usage collection and report export.
- `eval/rates/codex-standard-2026-09-29.json`: dated Terra rates with the official source link.
- `tests/test_bench_score.py`, `tests/test_cost_bench.py`: meaningful provider-free regressions, discovered by the existing Python gate.
- `eval/COST_BENCHMARKS.md`: commands, metric definitions, reproducibility and interpretation limits.

## Work

- [x] Create two sealed fixtures and prove all fault and clean-control oracles locally.
- [x] Add failing scorer tests, then implement candidate matching and complete hash-bound adjudication.
- [x] Add failing runner tests for reservation, resume, usage, timeout and source freezing; implement the bounded lane.
- [x] Run local mechanics and repeated compiler timings on both frozen versions.
- [x] Execute the four Terra runs in the approved order and preserve earlier failures without retry.
- [x] Inspect each finding against source, save adjudications and export paired JSON/CSV/Markdown results.
- [x] Run focused and available integration verification, record permission blockers, update the first-wave result and delivery checklist.

## Result

All 145 Python tests pass. All four network-ready live executions completed with valid schema and read audits. Both versions found all four planted defects, with zero false positives. Pooled estimated Standard credits fell 6.8% and provider time fell 14.7%. Two earlier routing failures are retained separately with unknown usage. Full access is now effective. Measurements, interpretation limits and reproducibility are recorded in `docs/cost-benchmark-wave1-2026-09-29.md`; the original first-wave integration gate remains a separate delivery step.

## Review focus

- Interrupted or concurrent execution must not spend an additional reserved call.
- A changed source, truth, model, effort or rate card must invalidate resumption.
- Missing or malformed usage must never become a zero-cost saving.
- Invalid schema, incomplete proof or failed audit must remain visible beside quality scores.
- Cached input varies by execution order; report its observed share and avoid significance claims with two pairs.

Final integration: the corrected private-copy setup and archived-engine reporting pass in the immutable gate. All 147 Python tests, 351 shell cases, 4,683 assertions and all validators pass. The measured runtime implementation and retained live snapshots are unchanged; only completion records follow the gate.
