# Does the `simplicity` lens find what a maintainer found? An evaluation loop

The `simplicity` lens (0.2.0) was distilled from one case: a stacked pair of PRs that added fee-commitment support for guarded multisig accounts in two SDKs, which a maintainer then cut by roughly two thirds after review — two commits, 1,950 lines removed, 240 added. Almost every cut traced to evidence already in the tree: a workaround whose own comment named the upstream method it avoided and a restriction that no longer held on the version the same stack pinned; optional parameters every production caller passed identically; wrappers that only forwarded; a test matrix whose second axis value a sibling PR had deleted.

The question was whether a panel running the lens would have found the same things before the maintainer did. The loop: check out both PRs at the exact commits the maintainer's review was posted against, run a round-1 simplicity pass with every seat, score the findings against the fifteen things the maintainer's commits removed, change only the general lens text if something is missed, repeat. Budget: five iterations. Nothing that names the PR's own symbols may enter the prompt.

## Ground truth (weights: K = load-bearing, S = structural, C = consequential)

Rust PR: **R1 K** hand-rolled commitment trait → the client's `fee_conversion_salt` builder method; **R2 S** two faucet resolvers → the client derives the faucet from the execution header; **R3 S** optional conversion-info parameter on six builders → removed; **R4 S** five forwarding wrappers → direct calls; **R5 S** public helper method → removed; **R6–R10 C** test matrix with one axis value, fee fixtures, anchor-vs-tip divergence tests, cross-implementation vector tests, docs.

TypeScript PR: **R11 K** the 205-line fee-auth module → the SDK's `withFeeConversionSalt`; **R12 S** the `feeFaucetId` option → removed; **R13–R14 C** exports and tests; **R15 S** execution reading the salt from the signed auth argument instead of the stored metadata (a correctness consequence of the swap).

Success: R1 and R11 with the exact upstream symbol and version, plus at least four of the five S rows, in the panel's union.

## Iteration 1 — lens + a hand-written round emphasis that said to open the pinned versions

| row | codex-sol | codex-terra | grok | opus |
|---|---|---|---|---|
| R1 K | ✓ | ✓ | ✓ | ✓ |
| R2 S | (c) | ✓ | ✓ | ✓ |
| R3 S | (c) | ✓ | ✓ | ✓ |
| R4 S | (c) | ✓ | – | ✓ |
| R5 S | (c) | ✓ | – | ✓ |
| R6–R10 C | R6, R9 | R6 | R6 | all five |
| R11 K | ✓ | ✓ (P1) | ✓ | ✓ |
| R12 S | ✓ | (c) | ✓ | ✓ |
| R13–R14 C | ✓ | (c) | ✓ | ✓ |
| R15 S | – | ✓ (P1) | – | ✓ |

Success criterion met. Every seat found the load-bearing row on its PR. The Opus seat on the TypeScript PR verified the replacement by calling the installed wasm at runtime and read the embedded crate versions out of the binary; the Opus seat on the Rust PR noticed that adopting the client's method closes a race the PR's README documented as unclosable. Two seats proposed, unprompted, the exact replacement tests the author wrote after the maintainer's review.

## Iteration 2 — ablation: the shipped lens text only, default round emphasis

Same commits, same seats, the emphasis reduced to the skill's default (`Simplicity first, then correctness, edge cases, error handling`). Purpose: establish that the lens text alone carries the result, since the iteration-1 emphasis overlapped with it.

| row | codex-sol | codex-terra | grok | opus |
|---|---|---|---|---|
| R1 K | ✓ (P1, 1.0) | ✓ | ✓ | ✓ |
| R2 S | ✓ | ✓ | ✓ | ✓ |
| R3 S | ✓ | ✓ | ✓ | ✓ |
| R4 S | ✓ | ✓ | – | – |
| R5 S | ✓ | ✓ | (c) | ✓ |
| R6–R10 C | R6 | R6, R7, R8, R10 | R6 | R6, R7, R8, R10 |
| R11 K | ✓ (P1) | ✓ (P1) | ✓ (P1) | ✓ |
| R12 S | ✓ | ✓ | ✓ | ✓ |
| R13–R14 C | ✓ | ✓ | ✓ | ✓ |
| R15 S | ✓ (P1) | ✓ (P1) | ✓ | ✓ |

Success criterion met again: 8/8 seats on the K rows, every S row by the union (R4 by two seats, all others by three or four). The ablation shows the lens text alone carries the result.

## What the loop established

- The lens finds the maintainer's cuts without codebase knowledge, because the evidence is mechanical: the pinned dependency source on disk, the callers of an optional parameter, the constructor each test-axis arm resolves to. Seats that opened the cargo registry or the installed `.d.ts` found the key rows every time; the lens text tells them to.
- The K rows are found by every seat in both iterations; the S rows by the union in both; the C rows mostly by the Opus seat, which reads furthest. Agreement across four models on the same replacement is the strongest signal the loop has produced.
- No prompt change was needed. The loop terminates at iteration 2 with the lens as shipped in 0.2.0.
- Two limits remain. Timing: the pinned version that made the workaround unnecessary was bumped into the stack twelve hours before the maintainer's commit; a run before that bump would have found nothing, correctly. Cross-PR context: several rows were only visible because a sibling PR made the account a standard one; the seats here saw that because it was already merged into the base, and a `/stack` run reviews legs separately — feeding each leg the other legs' summaries is the follow-up.
- Seats also found things outside the maintainer's diff: an error module nothing constructs (the second reviewer's finding), and a coverage gap the replacement tests left, that nothing runs a builder's output through the VM with a non-zero fee.

Method: worktrees at the pre-review heads with the stacked bases (`--base <previous PR head>`), `rev-prompt.sh … simplicity …` per seat, `rev-seat.sh` for the CLI seats and an Opus subagent for the fourth, findings scored by hand against the rows. Session directories `/tmp/rev-simp-*` and `/tmp/rev-simp2-*` hold every prompt, log and JSON.

## Held-out cases (2026-09-07): the lens as shipped in 0.2.0 does not generalise

The guardian case above is the one the lens was written from, so passing it proves the seats can execute the checklist, not that the checklist covers the next case. A separate agent searched 20 repositories (3,167 merged PRs) for PRs whose post-review commits removed a large share of what the PR had added, with the recipient of its report kept blind to the content; two clean cases came back, both in repositories nobody in this loop had reviewed: a 0xMiden/crypto PR (1,489 added lines at review, 855 merged) and a 0xMiden/node PR (1,216 at review, 651 merged). Each was checked out in an isolated repository containing the review-time head and its ancestors only — no remote, no later history — and reviewed by the same four seats with the generic lens. A different agent built the ground truth from the maintainers' actual post-review diffs, and a third scored the findings against it. The lens author read neither the diffs nor the truth until the scores were in.

| | crypto | node |
|---|---|---|
| ground-truth rows (K/S/C) | 9 (3/3/3) | 11 (2/5/4) |
| K rows hit by the union | 2 of 3 | 0 of 2 |
| S rows hit by the union | 1 of 3 | 1 of 5 |
| verdict | fail (near miss) | fail |
| findings contradicted by the merged head | 0 | 4 |
| real findings the maintainer did not ask for | 4 bugs, fixed differently upstream; 2 test gaps still open | 4 (error handling, secret residency, an unreachable arm) |

What generalised: the reuse and dead-code rules. On the crypto case every seat found the re-implementation of an existing tree type, a duplicated index conversion, a cloned error enum and a write-only field, and all four found two real logic bugs the maintainer fixed another way. What did not: on the node case the maintainer replaced a typed RPC transport with two JSON routes because the only consumer was a browser, removed cursor pagination because every consumer reads the whole table, folded a migration into the initial schema because the table was created on the same unreleased branch, replaced a hand-rolled sequence with the engine's autoincrement, and deleted a strategy trait every call site passed the same value to. The lens asked "does something already exist to reuse", not "is this machinery proportionate to its named consumer", and two seats explicitly defended the mechanisms the maintainer removed. On the crypto case the miss was of the same family: an associated error type plus a marker trait that no implementation used, which the maintainer replaced with one concrete enum.

Contamination: in the first held-out attempt the checkouts were worktrees sharing the full clone, and one seat cross-checked its findings against the merged commit; that run was discarded and the isolated checkouts built. In the isolated run one codex seat still opened the PR page through shell network access and another read a later published version of the crate under review from the cargo registry. Neither's findings show any trace of it, but both channels are now named in an offline paragraph that `REV_SEAT_OFFLINE=1` adds to every seat prompt, and the scorer checks the transcripts.

The scorer phrased every miss as a general rule. Those rules, none naming either PR, became the lens in 0.2.2: the burden of proof is on each mechanism; native engine or framework features over hand-rolled ones; proportionality to the named consumer; one value or one implementation means no parameter and no generic; unreleased history folds into the original; surface follows the file's convention; test axes, helpers and divergence tests must still have two sides. Iteration 3 re-ran both held-out cases blind with that lens; results follow.

### Iteration 3 (rewritten lens, both held-out cases blind again)

| | crypto iter 2 → 3 | node iter 2 → 3 |
|---|---|---|
| K rows hit by the union | 2/3 → 2/3 | 0/2 → 1/2 |
| S rows hit by the union | 1/3 → 2/3 | 1/5 → 3/5 |
| newly hit | module exposed as a path against the file's re-export convention; the write-only version parameters | the migration folded into the initial schema (all four seats); the hand-rolled sequence replaced by the engine's autoincrement; the policy trait deleted; cursor pagination dropped |
| still missed | the associated error type replaced by one concrete enum with a boxed catch-all | the typed RPC transport replaced by two JSON routes for a browser consumer |
| contradicted findings | 0 → 0 | 4 → 1 |

Both remaining misses are the same shape: the rule was in the lens, and a seat argued consistency with sibling code against it. 0.2.2 adds that consistency is not a justification and that when a generic is forced by one bound, the side no implementation varies is the one to collapse. Those two cases are no longer blind — the scorer's reports named their rows — so any further tuning on them is training, and the next validation must come from fresh PRs found the same blind way. The strict criterion (every load-bearing row plus half the structural rows) was not met on either held-out case; the lens is shipped because every change is general, recall improved on both cases without a single contradicted finding on the crypto case, and the alternative is a lens that only passes the case it was written from.

Leak channels found, all now covered by the offline paragraph or the isolated checkout: worktrees sharing the full clone; later published versions of the crate under review in the cargo registry; whole-registry symbol searches that match them; shell network access to the PR page.

## The benchmark (2026-09-07): eight post-cutoff held-out PRs, four configurations

`eval/bench.sh` runs every case blind: an isolated single-lineage checkout, four seats, the lens under test, a headless truth builder (once per case) and a headless scorer that prints one summary line. Cases were found by an agent reporting identifiers only, filtered to PRs merged after June 2026 so that no model's training data can contain the merged result, and cleaned of PRs whose post-review reduction came from a sibling PR being rebased away. Eight survived: protocol #3766, node #2464, midenup #219, protocol #3500, miden-usdcx #67, miden-vm #3314, protocol #3299, protocol #3588. The lens author read no diff, no review, no truth file and no score beyond the summary line. Cells are load-bearing rows hit / structural rows hit; PASS needs every K row and at least half the S rows.

| case | 0.2.2 (4× simplicity) | 0.3.0 (3× simplicity + clean-room on seat 3, PR body) | 0.3.1 (clean-room on the Claude seat, PR body) | 0.3.1 without PR body |
|---|---|---|---|---|
| protocol-3766 | 0/1, 1/6 | 0/1, 0/6 | 0/1, 1/6 | 0/1, 0/6 |
| node-2464 | 1/1, 0/2 | 0/1, 0/2 | 0/1, 0/2 | 1/1, 0/2 |
| midenup-219 | 1/1, 0/0 PASS | 0/1, 0/0 | 0/1, 0/0 | 0/1, 0/0 |
| protocol-3500 | 1/1, 4/6 PASS | 1/1, 3/6 PASS | 1/1, 1/6 | 1/1, 3/6 PASS |
| miden-usdcx-67 | 0/1, 0/5 | 0/1, 1/5 | 0/1, 1/5 | 0/1, 0/5 |
| miden-vm-3314 | 2/3, 4/4 | 2/3, 4/4 | 1/3, 3/4 | 2/3, 4/4 |
| protocol-3299 | 1/1, 1/4 | 0/1, 1/4 | 1/1, 0/4 | 1/1, 1/4 |
| protocol-3588 | 0/1, 0/5 | 1/1, 1/5 | 1/1, 0/5 | 0/1, 1/5 |
| **totals** | **K 6/10, S 10/28, 2 pass** | **K 4/10, S 10/28, 1 pass** | **K 4/10, S 6/28, 0 pass** | **K 5/10, S 9/28, 1 pass** |

Reading of the first two columns: the lens as shipped in 0.2.2 finds the load-bearing simplification on six of ten rows and passes two of eight cases; the misses are concentrated on the one design call per PR, as they were on the two earlier held-out cases. 0.3.0 changed two things at once — the author's PR description in every prompt, and a `clean-room` seat that under the dealing rule landed on the third roster position (grok) — and lost three load-bearing rows while gaining one. The two ablation columns separate those changes: 0.3.1 moves the clean-room lens to the Claude seat, and the last column removes the PR description. Two seat-level observations from the run logs: grok's first commands in every run execute in the harness's own working directory before it changes into the checkout (harmless, a different repository, but the scorer flags it), and codex-sol twice searched the whole cargo registry despite the offline paragraph, which is why 0.3.x builds a filtered per-case dependency view and names it as the only dependency source.

### What the four columns established

- Step 1 (the whole panel on simplicity in round 1) is what the baseline column measures, and it stands: four seats found 6 of 10 load-bearing rows where the earlier single-seat runs found about half.
- Step 2 (the author's PR description in every seat prompt) cost recall. With the body, three cases lost the load-bearing row the baseline had found and one gained it; the no-body ablation recovered two of the three. The mechanism is anchoring: a seat that reads the author's framing reviews inside it. The description stays available (`--pr`) for the orchestrator's own triage and for a user who asks, and is not passed to seats by default.
- Step 3 (a `clean-room` design seat in place of one simplicity seat) cost recall whichever seat took it: on grok it changed little, on the Claude seat it dropped structural rows from 10 to 6, because that seat had been the best checklist finder. A design seat is not free. It remains available as a fifth seat on rosters that have one.
- 0.3.2 therefore ships the baseline configuration plus the eight-round plan, the filtered dependency view for blind runs, and the benchmark itself. The next lens revision comes from the eight scorers' miss rules, which the lens author has not yet read; once read, these eight cases become training data and the revision must be validated on fresh PRs found the same blind way.
