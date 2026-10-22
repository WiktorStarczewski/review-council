### Triage

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=triage`. Read every
launched seat's `$S/r<N>-<seat>.json` (they are small; manifests, audits and
`r<N>-render.json` are not results). For each finding:

1. **Deduplicate** across seats; record how many independently found it. Agreement is
   signal, not proof.
2. **Verify against the source yourself.** Open the file at the cited lines. Reviewers
   hallucinate line numbers, invent APIs, and misread control flow. A claim you cannot
   substantiate is `REJECTED (unsubstantiated)`.
3. **Assign severity** - P0 incorrect behaviour / security hole / data loss / crash;
   P1 real bug on a reachable path, bad edge case, broken contract; P2
   maintainability, performance, missing test, unclear API; P3 nit.
4. Append the ledger entry (format below). For every rejection, append one line to
   `$S/rejected.md`: `- F-xxx REJECTED: <reason> (<file>:<line>)` - the next round's
   prompts carry it so seats do not resurface settled items.

5. **Cluster.** Group the round's accepted findings by root cause: one cluster is one rule
   that, applied everywhere it holds, closes every finding in it. Name it in each ledger entry
   (`Cluster:  C-03 re-check hold ownership after every parking await`). A finding that is the
   only member of its cluster is still a cluster.

Update counts: `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S open.P0=<n> open.P1=<n> open.P2=<n> rejected=<n>`.
Write all three counts in one call after the round's seats have exited: `rev-state.sh` refuses `phase=fix` while `open.P0`, `open.P1` and `open.P2` predate the newest `r<N>-<seat>.exit`, and only all three in one call refresh that stamp. A plan panel's `r<N>p-<seat>.exit` is not a seat exit for this purpose, so triage stays valid across the plan gate.
