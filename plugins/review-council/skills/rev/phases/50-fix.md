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
