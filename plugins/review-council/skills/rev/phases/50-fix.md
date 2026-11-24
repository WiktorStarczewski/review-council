### Fix

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=fix`. `phase=fix` also counts, for each code round with a sealed receipt, the chosen citations that land on lines this review changed since its first receipt, and refuses once two rounds since the last acknowledgement have a nonzero count. Apply the standing decision yourself: revert the cited review changes and defer the originating findings. Record the decision with `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh "$S" review_origin_ack=<N>` and put the outcome in the report. Receiptless legacy numeric rounds are not counted. SDK numeric receipts also support this review-origin accounting; they still never grant adaptive coverage. Run the test named in
Prediction before the fix exists and watch it fail, once per cluster's Prediction,
not once for the round. Record the observed failure line in fix-plan.md beside the
Prediction it belongs to: a failure whose message does not match the Prediction is a
STOP, not a note, because a test that fails for an unrelated reason proves nothing
about the defect. Implement each local cluster in `fix-plan.md` yourself. Launch the resolved workhorse for every other cluster, **one cluster per commit** (the commit
itself happens later, in the Commit phase below, not here in Fix), P0 clusters
first: every enumerated site, arm, realm and copy in the same commit. A fix that
covers the cited instance and leaves a listed sibling is not done - it is next
round's finding. Within a cluster, P3 only when trivial and safe. Match the
surrounding style; do not reformat untouched code. When two findings conflict,
resolve it explicitly in the ledger. A finding that is right but out of scope is
`DEFERRED (reason)`; wrong is `REJECTED (reason)`. Rejecting is a valid outcome -
never fix what is not broken to satisfy a reviewer.

**Design decisions.** A design decision inside the reviewed change (a constant or limit the diff introduces, the scope or boundary of its own behavior, a contract it documents, or a trade-off between two ways to make that code correct) is never handed to the author. Take the recommended action: use the recommendation the findings or panel carry, or form one yourself from the stated goal, the existing behavior and sibling code. Run it through the normal path (plan, red-before test when behavior changes, one commit per cluster, verification panel) and record `TAKEN (decision: <option chosen>; why: <rationale>)` in the ledger with the commit. Boundary: when the recommended action would change files or behavior outside what the reviewed diff already touches, flag it instead as `DEFERRED (decision for the author)`. Always flagged: product direction or roadmap, architecture beyond the PR, public API or protocol contracts owned by other components or repos, cross-PR or cross-repo design, anything not required to make the reviewed code correct and complete, and any decision that needs an authority the review cannot hold (spending funds or credentials, destructive or irreversible production actions, release or deployment, who owns or may merge the code, legal or licensing). P3 findings stay ignored and P0-P2 handling is unchanged.
