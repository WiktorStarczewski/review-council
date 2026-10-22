## Triage, plan, fix, verify

Open the cited code and consumers; reproduce or reason through the concrete failure
before accepting a finding. Deduplicate by root cause. Reject false positives with
specific evidence in `rejected.md`. A reuse finding must name an existing symbol you
opened. Scope cuts are `DEFERRED (scope decision)`, not unrequested product changes.

Maintain a ledger entry per finding: ID, severity P0-P3, status OPEN/FIXED/REJECTED/
DEFERRED, file and line, claim, evidence, reporting seats, disposition, test result,
and commit if any. Do not re-raise resolved findings without new evidence.
Write all three counts in one call after the round's seats have exited: `rev-state.sh` refuses `phase=fix` while `open.P0`, `open.P1` and `open.P2` predate the newest `r<N>-<seat>.exit`, and only all three in one call refresh that stamp. A plan panel's `r<N>p-<seat>.exit` is not a seat exit for this purpose, so triage stays valid across the plan gate.

Run the plan panel when accepted findings require a nontrivial change; skip it when
there is no accepted fix or every accepted fix is a P3 or one-line P2. When `family` is set, the workhorse writes
`S/fix-plan.md` and you do not draft it. When `family` is null, write it yourself: accepted findings, proposed changes, existing components to reuse,
risks, and falsifiable tests. Repeat the gate only for a new P0/P1 root cause or
another nontrivial cluster.
The plan panel runs after triage and before any edit of the working tree.
When the plan panel is skipped, append a line beginning `Plan panel r<N>p - SKIPPED: <reason>` to `$S/findings.md` before `phase=fix`.
`rev-state.sh` refuses `phase=fix` for code round `<N>` while `open.P0 + open.P1 + open.P2` is above zero, unless that skip line exists or every seat recorded by `phase=plan round=<N>p`, or by its `<N>px` replacement panel, has `r<label>-<seat>.json` and a `0` exit.
An incomplete plan panel is not a skip: retry it once on the next higher enforced seat after fixing a local cause, and if that fails review the plan yourself against the plan contract before any edit.

When `$S/panel-request.json` exists, set `PLAN_COMPLETENESS_SEAT` to the first surviving non-extra seat in that frozen roster, preferring one whose adapter is not `agent`, and do not read the workhorse for this seat. When `$S/panel-request.json` is absent, the plan panel is one `plan-completeness` seat on the resolved workhorse: set `PLAN_COMPLETENESS_SEAT` to the `seat` in `$S/workhorse.json` when `family` is set, `PLAN_SEATS` to the JSON array `["<that seat>"]`, and set `PLAN_EVIDENCE_ARGS=(--assignment "$PLAN_COMPLETENESS_SEAT=plan-completeness")`. When `family` is null, set `PLAN_COMPLETENESS_SEAT` to the first surviving non-extra seat in roster order, preferring one whose adapter is not `agent` when the roster has one (an Agent seat runs the panel unenforced), `PLAN_SEATS` to the JSON array `["<that seat>"]`, and set `PLAN_EVIDENCE_ARGS=(--assignment "$PLAN_COMPLETENESS_SEAT=plan-completeness")`.
When `roster.json` has `"plan_seats": "all"`, set `PLAN_SEATS` to the JSON array of every surviving non-extra seat, including after an extra or a
one-seat repair, and deal `plan-completeness`, `plan-soundness`, `plan-simplicity`, and
`plan-tests` in stable roster order. Build one `--assignment` per seat and use the
plan-completeness seat as `--full-seat`. For three seats, combine
`plan-completeness+plan-tests` on the first seat.
For five or more, keep `plan-completeness` unique and cycle only the other three
lenses on surplus seats.
Immediately before launch, write
`rev-state.sh "$S" phase=plan round=<N>p "seats=$PLAN_SEATS"` so status reads the
plan artifacts and its seats instead of the completed code panel.

Every cluster must contain `Findings`,
`Rule`, `Sites`, `Prediction`, and at least one of `Test`, `Tests`, or `Regression`. Its
`Sites` field must include one bounded query in either exact form:
`found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'PATTERN' .`
or `found by: grep --exclude-dir=.git --null -r -n -- 'PATTERN' .`. These fixed
flags cover every regular worktree file except `.git`. Do not add other globs, types,
exclusions, path operands, maximum depth, redirects, or filename suppression. Keep the
result below 80 lines. It must include every path named in `Sites`, and every path it
finds must be one the cluster names in any field (`Sites`, or `Test`/`Tests`/`Regression`)
or an entry in the optional `Excluded: <path> - <reason>; <path> - <reason>` field.
Semicolons separate entries, so a reason may contain commas, and the reason is mandatory.
An `Excluded` entry naming a path the search did not find is refused, so a cluster can no
longer fix 8 of 10 sites silently: the 2 it skips have to be written down, with why.
Native text search cannot certify this proof.
`Prediction` states which test fails, on which arm, at which assertion or message, and
why - a concrete symptom, not a restatement of `Rule`. It is read twice, not filed and
forgotten: Fix compares it against the observed pre-fix red run, and Verify compares it
against the failure line `rev-mutate.sh` prints beside each pinned hunk. Both
comparisons are yours - the tool surfaces what failed and never reads a prediction.
Locations are read only from `Sites` and the first token of a test field
(`Test: <path> - <what fails today>`); every other field is prose, including
`Prediction`. Locations may use
`path:line`, `path:start-end`, or a shorthand `:start-end` after a path.
Write `$S/r<N>p-panel.tsv` with one line per plan seat, then bind and prepare the
immutable plan before rendering:

```bash
PANEL_LABEL=<N>p
PLAN_HASH=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
MANIFEST=$(REV_PATCH_CHUNKS=${REV_PATCH_CHUNKS:-auto} REV_SOURCE_CONTEXT=${REV_SOURCE_CONTEXT:-1} python3 "$PLUGIN/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" \
  --phase plan --plan "$S/fix-plan.md" --plan-sha256 "$PLAN_HASH" \
  --full-seat "$PLAN_COMPLETENESS_SEAT" "${PLAN_EVIDENCE_ARGS[@]}")
PLAN_SNAPSHOT="$S/r$PANEL_LABEL-plan.md"
"$PLUGIN/scripts/rev-prompt.sh" "$S" "$PANEL_LABEL" --panel "$S/r$PANEL_LABEL-panel.tsv" \
  --plan "$PLAN_SNAPSHOT" --evidence "$MANIFEST"
```

The `--panel` render validates each rendered plan prompt against the schema-4
manifest before atomically publishing it. Scope, lens, manifest hash, inline plan,
and the complete authorized artifact set must match exactly. After every plan prompt
renders, apply the same single ordinary prelaunch verify and require every prompt's
one embedded manifest hash to match before fan-out.

Every reviewer receives the full inline plan, every cluster, and the complete navigation
index. The plan-completeness seat receives the full cumulative patch and every cluster's
closure, search, and source obligations. With `"plan_seats": "all"`, each cluster is
also routed to one specialist. With a valid predecessor receipt, specialists
receive only the fix delta for their clusters; otherwise they
receive the cumulative cluster closure. They never receive a full-state fallback.
Assigned seats receive up to three source-context shards. Each specialist prompt names
one exact primary artifact as its mandatory first native read.
Do not prepend a directory command, search, or compound shell command. With
specialists, every cluster has two independent readers.
Preparation runs each repository-wide sibling-site query once against the frozen snapshot
and embeds its hash-bound result for the assigned seats. Assigned seats prove the required
source locations and may run additional searches when the prepared result raises a question.
Before triage run the following; `verify-panel` certifies the one-seat plan panel once
that seat returns:

```bash
python3 "$PLUGIN/scripts/rev-evidence.py" verify-panel "$S" "$PANEL_LABEL"
```

This validation never writes a receipt or advances `coverage-head.json`. A manifest,
snapshot, roster, render, or other panel-global failure discards the invalid generation;
fix the evidence or task compiler and prepare a fresh schema-4 label before launching.
An individual provider execution failure with no invalid read audit retains valid sibling results and may retry only that seat once with the exact prompt, assignment, model, and effort, even if it left an `INCOMPLETE PROOF` result. A failed plan seat, after its exact retry for an execution failure or immediately for a hard plan read-audit failure or an exit-0 `INCOMPLETE PROOF` result, is replaced by an ordinary one-seat plan panel on another eligible seat: `"$PLUGIN/scripts/rev-state.sh" "$S" phase=plan round=<N>px "seats=[\"$OTHER\"]"`, then `"$PLUGIN/scripts/rev-evidence.py" prepare "$S" "<N>px" --phase plan --plan "$S/fix-plan.md" --plan-sha256 "$PLAN_SHA256" --assignment "$OTHER=plan-completeness" --full-seat "$OTHER"`. It keeps the schema-4 plan contract, and under `plan_seats: all` it covers every cluster with the completeness lens; preserve every completed sibling and partial stream. If the `<N>px` panel fails too, leave the configured plan panel incomplete and review the plan yourself against the plan contract before any edit. Do not broaden a specialist to full scope or replace
the schema-4 task with a legacy prompt. Verify and address plan objections before
editing. Keep one rule per root-cause cluster with a compact site table, invariants,
and falsifiable tests.

Before the first edit, write `rev-state.sh "$S" phase=fix`.
`phase=fix` also counts, for each code round with a sealed receipt, the chosen citations that land on lines this review changed since its first receipt, and refuses once two rounds since the last acknowledgement have a nonzero count. Apply the standing decision yourself: revert the cited review changes and defer the originating findings. Record the decision with `"$PLUGIN/scripts/rev-state.sh" "$S" review_origin_ack=<N>` and put the outcome in the report. Receiptless legacy numeric rounds are not counted. SDK numeric receipts also support this review-origin accounting; they still never grant adaptive coverage.
Run the test named in Prediction before the fix exists and watch it fail, once per
cluster's Prediction, not once for the round. Record the observed failure line in
fix-plan.md beside the Prediction it belongs to: a failure whose message does not
match the Prediction is a STOP, not a note, because a test that fails for an
unrelated reason proves nothing about the defect. Apply each local cluster yourself. Launch the resolved workhorse for every other cluster (one cluster per eventual commit, made only later when the round is
actually committed, not here). Preserve user changes. Run the relevant gates and
bring them to baseline or better. Add meaningful regressions when warranted, not
tests that merely mirror implementation. Run the repository's required gate list
within the user's authorized scope, and record the result in the ledger. Then run
rev-mutate.sh over the changed hunks before committing: revert each hunk alone and
confirm a test notices, and compare what failed against the cluster's Prediction:
`$PLUGIN/scripts/rev-mutate.sh "$S" "<the test command>"`. Commit only when within
the user's requested workflow, one commit per cluster, with `fix(rev): <finding IDs> <concrete change>` and no unrelated
files. Review commits are never squashed: each fix is its own commit, and its subject names the finding IDs it closes, never the round. Finding IDs are unique within the session and never reused. Record uncommitted fixes accurately when commits were not requested.
Read-only runs skip all fix, commit, push, and post-report editing steps.

For review-council self-hosting, use tiered verification: run an 8-30 second focused
test after each edit, the roughly three-minute evidence fixture after a coherent
contract cluster, and the complete suite once for each material tree. Record the tree
hash and successful command so an unchanged tree reuses that gate result. Before a
paid panel after adapter, prompt, manifest, or audit changes, preflight replays the
preserved provider envelopes through the current auditor.
Static replay runs before the roster probe for changed provider boundaries. It cannot
certify a session. Authoritative replay runs after the roster probe and before any reviewer launch.
The probe binds the exact models and efforts. Preflight reuses a hash-keyed pass receipt
only when the boundary, fixtures, contract tests, and provider versions match; a replay
failure blocks the paid run.

Update state and the ledger after every phase. Do not wake on a ten-minute
cadence unless `status_tick` is true. Wake on a phase change, a seat failure, or a
terminal result, and run `rev-status.sh "$S"` then. The status script reads artifacts
without model calls. Large changes deserve explicit remaining-coverage notes, not just counts.
When `status_tick` is true, use `python3 "$PLUGIN/scripts/rev-context.py" "$S" --watch --duration 600`
in an attached execution. Relay those scheduled events only while the tick is enabled.
