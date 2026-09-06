# Why the fix-plan gate exists: churn in 11 past runs

Measured 2026-09-06 over 11 `/rev` runs across three repositories (115 round commits, 759 findings), two ways: `git blame` of every line a round removed, attributing it to the original change, an earlier round's fix, or pre-existing code; and one agent per run classifying every finding named in a round's commit message from the diff and the blame.

| | share |
|---|---|
| removed lines that an earlier round's fix had written | 50% overall; 58–64% in the three longest runs (15, 21 and 23 rounds) |
| findings that were fixes of an earlier round's fix | 56% (430 of 759) |
| the same, P0 and P1 only | 52% |
| the same, from round 5 onward | 68% |
| runs whose last P0/P1 was itself a fix of a fix | 8 of 11 |
| fix-of-fix findings caught the very next round | 57% (248 of 439) |

Causes of the fix-of-fix and reversal findings: incomplete fix 55%, wrong fix 20%, new code with a new bug 13%, two fixes interacting 6%, reviewer disagreement 1%, late design change 1%.

Every one of the eleven classifying agents, independently, described the same mechanism: a finding names one call site, one branch of a conditional, one realm, one copy of a doc, and the fix covers exactly that instance; the next round finds the sibling. One guardian-rotation chain went four round trips one call site at a time; a sync fuse evolved over nine rounds; a doc correction was applied to two of six public surfaces and then propagated one copy per round.

Asked whether a one-page fix design written after round 1 and reviewed by the same panel before any code was written would have prevented the churn, the agents said yes for most of it in 10 of 11 runs and named the chains: in each case the churn was one design question (which sites does the rule cover; what does an eviction mean at each hold; which surfaces carry the doc claim) answered one instance per round instead of once.

What a plan does not fix: original defects the panel missed until late (one unguarded option found in round 6 after five rounds). That is recall, and lens rotation is the tool for it.

Hence 0.2.0: findings are clustered by root cause at triage; after round 1 (and after any later round that accepts a P0/P1 or opens a new cluster) the orchestrator writes `fix-plan.md` stating the rule per cluster with every site enumerated, and the panel reviews the plan before code; fixes land one cluster per commit, every enumerated site in the same commit; and every seat's `suggested_fix` must state the rule and its siblings, not a patch for the cited line. The next real runs will show whether the fix-of-fix share drops; the analysis script is in the session that produced this document, and the measurement is repeatable from git alone.
