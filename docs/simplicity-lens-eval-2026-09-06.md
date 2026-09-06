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
