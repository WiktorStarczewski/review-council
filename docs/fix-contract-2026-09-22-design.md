# Fix Contract: stopping the loop from fixing its own fixes

Design, 2026-09-22. Successor to `churn-analysis-2026-09-06.md`, which measured the problem
and motivated the plan gate shipped in 0.2.0. This document measures what the plan gate left
behind and specifies the next three instruments.

## The problem, measured

Across 12 fix-doing review sessions, **591 findings, of which 262 (44%) are defects in a fix
the loop itself made in an earlier round.** Three independent classifiers over disjoint ledger
sets agreed within four points on the key ratio.

| class | n | share | reachable by |
|---|---:|---:|---|
| DESIGN-ERROR | 79 | 30% | judgment, mostly |
| INCOMPLETE-SITES | 73 | 28% | script |
| VACUOUS | 50 | 19% | mutation run |
| FALSE-PREMISE | 42 | 16% | script |
| OTHER (bookkeeping) | 18 | 7% | script |

Two facts shape everything below.

**The plan gate already works on the cheap classes.** Of the 165 own-fix defects in the two
sets that recorded where they were caught, 103 died at the plan gate and only 62 shipped. A
plan-gate catch costs a re-plan; a shipped one costs a round. The shipped population is
different in kind: roughly 44% DESIGN-ERROR and 26% VACUOUS. Building more static claim
checking would mostly accelerate catches we already make.

**The remedy is where rigour is absent.** The loop establishes a finding with evidence - a
quoted line, a bisect, a reproduction - and then writes the fix from intuition, because the fix
feels like a consequence of the finding rather than a new claim. It is a new claim: this is
where the defect lives, these are all the places it lives, this rule applies here, this
precedent supports the shape. Each of those is checkable and none of them is checked.

## Goal, and the explicit non-goal

Goal: cut own-fix defect volume by roughly half, deterministically, at near-zero token cost.

**Non-goal, stated plainly so nobody is surprised: this does not make review rounds rare.** A
round is triggered by at least one surviving defect, not by their count. The current rate is
about 22 own-fix defects per session, of which ~8 ship. A 55% cut leaves ~3.6 shipped per
session, which forces the same rounds that 8 would. Reaching "fixes rarely need fixes" needs
the shipped count below about one per session, an ~88% reduction, and DESIGN-ERROR alone puts
a floor well above that. The instruments here make each round cheaper and less frequent at the
margin. Making rounds structurally cheaper is separate work and is not foreclosed by any of this.

## Instrument 1: the Fix Contract

A fix may not be committed until its plan cluster carries four things, all machine-enforced.

### 1a. Sites are generated, never authored

The single most common mechanical failure is typing a list that a command had already computed.
One case cited an `rg` as the plan's discovery proof and then hand-wrote the Sites list from
memory: the command returns ten files, the list named eight, and the two dropped were the ones
that do not look like imports.

0.4.8 already runs the plan's `Sites` search itself and refuses when a named path is missing
from real output (`prepare_plan_searches`, `scripts/rev-evidence.py:1511-1557`). That is the
right shape and the wrong direction: it validates a list the orchestrator wrote. Invert it.

The tool runs the search and emits the hit list. The orchestrator's only permitted edit is to
annotate each hit as `fix` or `exclude: <reason>`. A plan whose Sites block contains a path not
in the search output, or omits one that is, is refused. Fixing 8 of 10 stops being possible
rather than becoming detectable.

This does not close the case where the *search itself* is wrong - one plan searched file
content for a pattern literal and so structurally could not enumerate its targets. The search
expression therefore remains a reviewed artifact, and `strict_search_words` keeps rejecting
`head`, extra globs and redirects.

### 1b. Test-first, with a proven red

The fix's test is written and observed failing **before** the fix exists. A test written after
the fix is shaped by the fix and inherits its blind spots; the red step is what makes a vacuous
test impossible to write by accident.

The red step also falsifies premises about where behaviour lives. In one case the planned
discriminator was set by both the throw path and the resolved-but-never-ready path, so the fix
would have been inert. Test-first surfaces that immediately: the test goes red, the fix lands,
and it stays red.

Where a fix is not cheaply unit-testable (CI selectors, changelog gates, locale bundles,
generated assets), the obligation degrades to "write the check that would have caught it" and
the cluster records why a test was not possible. That degradation is recorded, not silent.

### 1c. A prediction, then a per-hunk mutation proof

Test-first pins the behaviour the author thought of. It does not pin every line they changed.
Measured: three changes shipped unpinned in one session while the suite was green, each masked
by a sibling guard or a redundant second mechanism.

So every changed hunk is reverted on its own, with every other change kept, and the suite is
re-run. Before running, the plan records the prediction: **which test, on which arm, fails at
which assertion or message, and why.** Divergence is a STOP, not a note.

The prediction is the load-bearing half. Measured on two rounds, 3 of 7 and 4 of 7 predictions
diverged, and every divergence was a real defect the passing suite hid. The runs that matched
taught us nothing we did not already know. A bare mutation check answers "something went red",
which is satisfying and nearly useless.

Two failure modes the implementation must handle, both observed:

- **A matching count is not a matching prediction.** One check predicted a failure via an
  `unhandledRejection` spy, saw one failure, and was called a match; the spy can never fire, and
  the test failed only because Jest pins the stray rejection on the running test. Right test,
  wrong reason. The runner must compare the failing assertion, not the count.
- **A mutation that does not apply produces a green run indistinguishable from a real one.** The
  runner must prove the file changed before trusting the result.

Scoping: the mutation runs the suite the fix's arm actually executes. The recurring vacuity
failure is "I asserted on the arm I was looking at rather than the arm the defect lived on".

### 1d. Refuse `phase=fix` on stale evidence

The plan gate exists and is enforced every round, but the whole gate hangs off `total > 0` over
a hand-maintained counter (`scripts/rev-state.sh:108`). Rounds sail through it whenever `open`
still holds the previous round's `0/0/0`. A gate keyed on a counter that nothing forces to be
current is open by default.

Stamp `open` with a seat generation and refuse `phase=fix` when it has not been written since
the round's last seat exit. Derive `open` from `findings.md` so triage and the gate read one
source.

## Instrument 2: five lint rules for guard and lifecycle protocol

Design errors are **not** broadly reachable by targeted detection. Four candidate detectors
were built and adversarially attacked; all four came back weak. See "Rejected" below, which is
the most reusable part of this document.

What survives is narrow and real. Of one detector's 15 genuine catches, **13 are
single-function, single-file AST predicates** needing no typestate lattice, no interprocedural
summary and no second language backend:

1. `guard-release-completeness` - a flag raised true on a path that can throw, released only in
   a `catch` arm rather than a `finally`.
2. `guard-release-locality` - the clear sits in a different function from the set.
3. `no-statement-between-raise-and-try` - anything that can throw synchronously between raising
   a latch and the `try` whose `finally` clears it, including a dereference of a possibly-absent
   global. This is the shape that left a copy control dead forever.
4. `latch-armed-before-early-return` - a once-latch whose arming assignment follows an early
   return rather than dominating entry.
5. `staleness-token-read-before-await` - a generation token compared against a value re-read
   after the first `await` instead of captured into a local before it.

Plus one standalone script for the discarded check-and-set result.

**These ship repo-wide as warnings over a suppressed baseline, and can never be hard errors.**
The corpus contains byte-identical structures with opposite verdicts: after one fix, the same
ref is still one-write-no-clear and is now correct in its narrowed role as a mount latch.
Scoping to plan-named symbols controls volume, not precision, and precision is what decides
whether the operator reads the alert.

Why this is worth building despite a weak parent verdict: in one session a single screen's
lane-and-generation protocol produced findings in rounds 4, 6, 6, 11, 12 and 13. A lint firing
once at round 1 collapses six panel rounds. And for one of those the ledger records that the
mutation check could not see it, because the test double settled synchronously - static
analysis is the only route there. The rules also keep paying for ordinary PR authors long after
a review ends, which no instrument aimed at the loop itself does.

## Instrument 3: run the gates we already have

Free, already a standing repo rule, and simply not enforced by the loop on itself: run the
repository's **full** gate list on every review-fix commit, not the subset the author's diff
suggests. Record the result in the ledger. This alone decides a measured slice of cases,
including at least one lint gate the loop's own fix violated while a seat asserted the gate did
not police that file.

Also cheap and worth taking from the same cluster: for any plan edit that is a one-line
predicate, signature or type change, apply it on a scratch worktree, run `tsc` plus the named
suite, and paste the output. The compiler names the caller the plan missed.

## Rejected, with evidence

Recorded so nobody rebuilds these.

**A typestate checker over the control-flow graph.** Rated weak. The expensive machinery is
paid for by the cases it misses, and the cases it catches do not need it. Reduced to the five
lint rules above.

**Enumerate-and-diff over a registry of set extractors.** Rated weak, and the objection is
fatal: the registry is a lookup table transcribed from the ledger entries it claims, with one
extractor's wording verbatim from a case in the holdout set. Its "17 cases" is a grouping
decision, not a measurement of any mechanism's yield. Measured precision on its own best
example is 25%: it fires on four sites in one file, one is the defect, one is provably correct
because it is the assertion that defines the list it is accused of subsetting, and two are
undecidable without runtime knowledge.

**Sibling-parity diffing.** Rated weak and **actively harmful**. Measured precision about 1 in
10, and three holdout cases are failures caused by exactly this prescription: a presence gate
generalised to a sibling that was a select-with-fallback, which would have hard-failed ten-plus
specs; an env-resolution rule generalised to a stress suite where the localhost default was a
safety interlock; and a testid wired symmetrically to both render branches, which would have
broken 11 Playwright waits. The corpus contains a matched pair with an identical detector
signature and opposite correct verdicts. A difference is not a defect signal.

**Replay a new gate over merged history to find its false positives.** Premise inverted. The
rule says any historically merged PR the gate fails is a false positive, but these gates exist
*because* history contains violations - changelog misfiling hit three consecutive PRs. The rule
classifies the gate's only true positives as false positives.

**A failure-path review lens.** Superseded by 1b. A test obligation per trigger path is
falsifiable where a lens opinion is not, leaves an artifact that keeps paying, and moves the
uncertainty from "will the seat think of it" to "did we enumerate the triggers", which is an
enumeration problem we already attack with search.

## Expected effect, and how we will know

Assumed per-class efficacy, which is the part to challenge:

| class | n | instrument | efficacy | limit |
|---|---:|---|---:|---|
| INCOMPLETE-SITES | 73 | 1a | 75% | does not fix a wrong search |
| VACUOUS | 50 | 1b + 1c | 80% | the check itself can be run wrong |
| FALSE-PREMISE | 42 | 1a + 3 | 65% | semantic premises resist grep |
| OTHER | 18 | 1d + 3 | 80% | bookkeeping |
| DESIGN-ERROR | 79 | 2 + 3 | 20-25% | most of it needs a reasoner |

Central estimate: **55-60% fewer own-fix defects**, range 45-70%.

Measurement is already possible from git alone and the two scripts live in
`churn-analysis-2026-09-06.md`. Report the churn ratio in every run's final report: findings
raised against the original change versus against the loop's own fixes. That number is the only
honest test of whether any of this worked, and it did not drift down on its own as the loop
"got more careful", because care is not the mechanism.

## Integration points

- Plan schema: `parse_plan` in `scripts/rev-evidence.py` reads `## C-<id>` clusters with
  `Field: value` lines. `Sites` and `Test` exist; add `Prediction`. Field parsing is generic, so
  this is additive.
- Sites inversion: `prepare_plan_searches` and `plan_search_contract`,
  `scripts/rev-evidence.py:1511-1582`.
- Gate arming: `scripts/rev-state.sh:100-118`.
- New `scripts/rev-mutate.sh`. It must refuse to run while a panel is live, because seats read
  the live tree and a script that reverts hunks for seconds shows them a tree that is neither
  base nor fix.
- Contract text: `skills/rev/SKILL.md` Fix section (696-706) and Verify (707-722).
- Lint rules ship as their own package, consumed by the reviewed repo, not by the plugin.

## Risks

- **The lint rules become noise and get ignored.** Mitigation: warnings over a suppressed
  baseline, and measure the alert-to-defect ratio before promoting anything.
- **Mutation runtime on large suites.** Mitigation: scope to the suite the fix's arm runs, and
  cache by tree hash as the Verify step already does.
- **Test-first slows a round enough to be skipped under pressure.** Mitigation: it is enforced
  at the gate, not by discipline. The degradation path for untestable fixes is explicit so there
  is no incentive to lie about it.
- **The classification underpinning all of this is approximate.** See below.

## Open questions

1. The design-error extraction found 110 cases where the classifiers counted 79, same corpus,
   looser boundary. If 110 is right, DESIGN-ERROR is a larger share than 30% and every estimate
   here is optimistic. Worth reconciling before trusting the efficacy table.
2. Efficacy figures are estimates, not measurements. The first two sessions under the contract
   should be measured against them.
3. Which repository owns the lint rules, given they are useful to PR authors and not only to
   the loop.
