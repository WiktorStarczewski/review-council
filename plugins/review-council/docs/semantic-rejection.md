# Reject an unfinished mandatory assignment

A valid read audit proves recorded reads and citations, not that every semantic
assignment was completed. Verify an explicitly unfinished obligation against the
exact rendered prompt. Skipping optional runtime tests alone does not justify rejection.

```bash
python3 "$PLUGIN/scripts/rev-evidence.py" reject-result "$S" "$FAILED_LABEL" "$FAILED_SEAT" \
  --manifest-sha256 "$MANIFEST_SHA256" \
  --prompt-sha256 "$PROMPT_SHA256" \
  --result-sha256 "$RESULT_SHA256" \
  --obligation "$EXACT_PROMPT_QUOTE" \
  --evidence "$EXACT_SUMMARY_QUOTE" \
  --reason "$OBSERVED_MANDATORY_OMISSION"
```

Compute the hashes from the original manifest, prompt and result. The obligation
must occur literally in that prompt, and the evidence literally in its result
summary. State which mandatory work remains unfinished. This is an explicit semantic
judgment, not an inferred provider error. The command validates the generation and
creates a separate immutable `r<label>-<seat>.semantic-rejection.json` record.
An identical request is idempotent. Changed reasons, stale hashes, linked files and
unbound quotes are refused.

Preserve the original result, exit, read audit and transcript. Never edit a summary
to add `INCOMPLETE PROOF`, fabricate an exit, or create an audit failure. The
rejected generation cannot relaunch under that label, verify, seal a receipt or
supply current coverage. Valid siblings and unrelated prior coverage retain their
eligibility. Status distinguishes semantic rejection from provider failure.

Continue the existing configured replacement chain:

```bash
python3 "$PLUGIN/scripts/rev-workhorse.py" escalate --session "$S" --seat "$FAILED_SEAT"
python3 "$PLUGIN/scripts/rev-evidence.py" prepare "$S" "$CHILD_LABEL" \
  --phase repair --assignment "$EXECUTOR=$PARENT_BUNDLE" \
  --parent-assignment "$FAILED_LABEL:$FAILED_SEAT"
```

Use a fresh child label in the original root panel's replacement namespace. Follow
the existing render, prelaunch verification and launch requirements with the same
phase, lens, effort, scope and proof obligations. Preserve completed siblings. This
does not authorize a full-panel rerun or a smaller assignment.

Once the selected child independently completes every obligation, use the ordinary
root `receipt --replacement <root-seat>=<child-label>` command. If that panel already
had a mechanically sealed receipt selecting a rejected generation, the old receipt
remains unchanged as historical evidence. The command prints a content-addressed
successor receipt and moves `coverage-head.json` to it. The successor binds its
immutable predecessor's name and SHA-256, the rejection records, the identical root
manifest, source and roster, and independently valid eligible replacement results.
Consumers use the printed path or coverage-head reference rather than assuming the
original filename. A changed predecessor, rejection or selected generation invalidates reuse.

Record the observed omission, original result, rejection, replacement outcome and
receipt lineage in the findings ledger and completion report. Mechanical sealing
alone never proves semantic completion.
