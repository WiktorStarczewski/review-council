### Verify

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=verify`. Re-run the gates from
setup. Compare with `baseline.md`: pre-existing failures are not regressions;
anything newly failing is yours to repair or revert **before** the next round.
Never advance on an unverified material tree. Run the repository's required gate list
within the user's authorized scope, and record the result in the ledger. Then run
rev-mutate.sh over the changed hunks before committing: revert each hunk alone and
confirm a test notices, and compare what failed against the cluster's Prediction:
`${CLAUDE_PLUGIN_ROOT}/scripts/rev-mutate.sh $S "<the test command>"`. For
review-council self-hosting, run an 8-30 second focused test after each edit, the
roughly three-minute evidence fixture after a coherent contract cluster, and the
complete suite once for each material tree. Record the tree hash and successful
command so an unchanged tree reuses that gate result.
Before a paid panel after adapter, prompt, manifest, or audit changes, preflight
replays the preserved provider envelopes through the current auditor.
Static replay runs before the roster probe for changed provider boundaries. It cannot
certify a session. Authoritative replay runs after the roster probe and before any reviewer launch.
The probe binds the exact models and efforts. Preflight reuses a hash-keyed pass receipt
only when the boundary, fixtures, contract tests, and provider versions match; a replay
failure blocks the paid run.

### Commit

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=commit`. Only after verification
passes, and only if the round changed files. Commit each cluster on its own: stage exactly
that cluster's changes (never `git add -A` blindly; the session dir is outside the repo)
and commit them. No push. Never `--amend`, never
`--no-verify`, never force. No AI attribution of any kind. Review commits are never squashed: each fix is its own commit, and its subject names the finding IDs it closes, never the round. One cluster is one fix.

```
fix(rev): F-012, F-019 re-check hold ownership after every parking await

F-012 P1  late call after eviction re-entered the client
F-019 P2  worker realm had the same late call
```

Then `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S last_commit=<sha> fixed=<total fixed so far>`.

### Record

Append a round block to `findings.md`: seats and efforts used, lenses, new findings
by severity, fixed/rejected/deferred counts, verification result, one commit SHA per fixed cluster with its finding IDs (or
"no changes"). Tell the user in two or three sentences: round number, seats, new
findings by severity, what was fixed, gate status, commit.

## Adaptive panel plan

With four core seats, a normal review uses eight code-seat launches plus one
conditional plan. A large or high-risk review uses twelve before fixes: four
simplicity, four risk-discovery, and four combined red-team/verification launches.
An important or explicitly adversarial review that is not otherwise large or
high-risk uses eight before fixes. If any fix follows the combined panel, run four
separate verification launches; a one-seat plan then gives totals of 17 or 13
respectively. With `"plan_seats": "all"`, every
plan panel launches all four core seats instead of one. An explicit round count remains a
minimum override and exclusively selects the legacy numbered schedule.

A change is large with more than 25 changed files or more than 1,500 changed lines.
It is high-risk when it crosses a security, persistence, concurrency, transaction,
protocol, public API, or irreversible mutation boundary.

| Panel | When | Lenses, in order |
|---|---|---|
| Simplicity discovery | always | simplicity for every seat |
| Risk discovery | large or high-risk only | correctness-boundaries, security-state-api, concurrency-resources-performance, tests-observability-maintenance-regression |
| Full red team | exactly once for large, high-risk, user-marked-important, or explicitly adversarial adaptive reviews | the four risk bundles with the four distinct composed adversarial assignments, rendered as verification with sibling-site completeness |
| Plan | accepted nontrivial fixes | plan-completeness on one seat; `"plan_seats": "all"` deals plan-completeness, plan-soundness, plan-simplicity, plan-tests |
| Verification | reuse the current combined panel when no fix follows; otherwise after discovery or fixes | the four risk bundles; `--phase verification` adds to every seat: Sibling-site completeness: for each fix commit since the base, name the rule it applies and search the repository for sites, arms, realms, callers and copies (tests, JSDoc, docs) the rule reaches but the commit missed. |

Adaptive default panels use core seats and omit extras. Explicit numeric round plans
may include extras in their configured rounds. The four risk bundles cover logic,
boundaries, error handling, security, state, API contracts, concurrency, resources,
performance, tests, observability, maintenance, and regression. Keep the same evidence
rules and the same receipted effort in every bundle.

One four-bundle verification panel reviews the latest material state: the current
combined panel when no fix follows, a separate panel after simplicity-only discovery,
or a fresh panel after fixes. Do not certify an adaptive panel until every assignment has a valid result, either its own result or one selected successful replacement's result. A certified risk or verification panel therefore has all four bundles. After the exact retry for an execution failure, or immediately after a hard audit failure or exit-0 `INCOMPLETE PROOF` result, continue that assignment through the configured eligible replacement chain until valid proof exists or no eligible seat remains. There is no panel-wide cap either; every attempt uses a unique child label and binds directly to its original failed parent assignment. A replacement is one seat, so the three-reviewer minimum does not apply.

An explicit numeric override exclusively uses the legacy numbered code-panel schedule below.
Conditional plan panels are extra and do not count toward the requested total.
For round 9 and later, target uncovered or unresolved risk.

| Round | Emphasis | Lenses, in order | Extra seat |
|---|---|---|---|
| 1 | Simplicity - could this change be smaller? | simplicity | - |
| 2 | Correctness, edge cases, error handling | correctness, edge-cases, error-handling | - |
| 3 | Security, data & state | security, data-state | `codex-review` - security |
| 4 | Concurrency, resources, performance | concurrency, resources, performance | - |
| 5 | API & contract, compatibility | api-contract, data-state, readability | - |
| 6 | Tests, observability | tests, observability | - |
| 7 | Red team - argue the change is broken | red-team | - |
| 8 | Regression + cumulative diff re-read | regression | - |
| 9+ | Whatever is least covered or still open | the uncovered lenses, rotated off the previous pairing | - |

**Simplicity first.** Round 1 belongs entirely to the question "could this change be
smaller?": every seat gets `simplicity`. Measured on eight held-out PRs (the plugin's
`docs/simplicity-lens-eval-2026-09-06.md`), four seats with the lens found the load-bearing
simplification on 6 of 10 rows; every variant that replaced one of them with a design seat
(`clean-room`, which sketches the smallest design for the named consumer before reading the
diff) found fewer, and giving the seats the author's PR description cost more load-bearing
rows than it gained - reviewers anchor on the author's framing instead of attacking it. So
neither is dealt by default: `clean-room` is available as an *additional* seat when the roster
has five or more, and `--pr` is available but off. At triage, a reuse finding is accepted only
with the existing symbol named at a location and version you have opened; a scope cut is
`DEFERRED (scope decision)` for the user. Correctness lenses start in round 2: reviewing lines
that should be deleted is the purest form of churn.

**Vacuity.** Whenever the diff touches tests, every prompt carries `--vacuity`. It is
empirically the most common defect a panel finds and it finds it late - a 12-leg
review once produced eleven, several not until round 3, three of them the
orchestrator's own.

## Extension and termination

Repeat plan, fix, and verification only when a verification panel produces a new
P0/P1 root cause, leaves a P0/P1 open, or is followed by another nontrivial fix.
A P3 or one-line P2 follow-up needs the project gates. Every other accepted fix needs
a full adaptive verification panel.

Adaptive completion requires a full four-bundle verification panel after discovery
or the latest nontrivial fix, no new or open P0/P1, no material change left
unreviewed, and gates at or better than baseline.
Immediately before finishing with a reused combined panel, rerun
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" current-coverage "$S"`
and require `eligible: true`. A failed final check requires fresh verification before completion.

Only numeric mode continues past its requested minimum while any of these hold: the
last numbered code panel produced a new P0/P1; the last numbered panel's fixes were
nontrivial; any P0/P1 remains open; or a lens or major changed file remains unreviewed.
Numeric mode stops only after the requested minimum numbered code panels ran, two
consecutive numbered code panels produced no new P0/P1, no P0/P1 remains open, and
gates are at or better than baseline. Plan panels do not count as numbered code panels.
Still finding P0s in a later cycle is a rework signal and must be reported plainly.

Never append the cumulative findings ledger to reviewer prompts. For a resumed run,
write `$S/context.md` as a concise one-line digest of settled decisions; the prompt
renderer includes it automatically. Do not copy `findings.md`. After every panel, run
`${CLAUDE_PLUGIN_ROOT}/scripts/rev-profile.py $S` and relay completed calls, processed
tokens, prompt words, provider cost, and each `seat_yield` line with its failure codes by model. Current-session completion
and finding yield require a schema-valid result with a successful exit receipt. Only
exact hashed receiptless results recorded in a versioned legacy roster policy may omit
one. Usage-bearing failed attempts remain metered. Report the profiler's core-roster signature with every measurement. Treat a mixed-roster marker as a comparison boundary
for provider tokens, cost, elapsed time, and finding yield.
Prompt warnings above 1,800
code words or 3,000 plan words require removing repeated context, not truncating
evidence.
