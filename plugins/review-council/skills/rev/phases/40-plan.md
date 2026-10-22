### Plan - the fix-design gate

Run the plan panel when accepted findings require a nontrivial change; skip it when
there is no accepted fix or every accepted fix is a P3 or one-line P2. Repeat it only
when verification accepts a new P0/P1 root cause or another nontrivial cluster.
The plan panel runs after triage and before any edit of the working tree.
When the plan panel is skipped, append a line beginning `Plan panel r<N>p - SKIPPED: <reason>` to `$S/findings.md` before `phase=fix`.
`rev-state.sh` refuses `phase=fix` for code round `<N>` while `open.P0 + open.P1 + open.P2` is above zero, unless that skip line exists or every seat recorded by `phase=plan round=<N>p`, or by its `<N>px` replacement panel, has `r<label>-<seat>.json` and a `0` exit.
An incomplete plan panel is not a skip: retry it once on the next higher enforced seat after fixing a local cause, and if that fails review the plan yourself against the plan contract before any edit.

Why: over 11 past runs, 56% of all findings (68% from round 5 on) were fixes of an
earlier round's fix, and 55% of those were *incomplete* fixes - a rule applied to the one
site a reviewer named while its siblings waited for the next round. The gate makes the
rule explicit and lets the panel attack it before it becomes code. Evidence:
`docs/churn-analysis-2026-09-06.md` in the plugin repository.

1. When `family` is set, the workhorse writes `$S/fix-plan.md` and you do not draft it. When `family` is null, write `$S/fix-plan.md` yourself. One section per cluster:

   ```markdown
   ## C-03 · re-check hold ownership after every parking await
   Findings: F-012 (P1), F-019 (P2), F-023 (P3)
   Rule:     an eviction abandons but does not cancel, so every WASM call that follows an
             await which can park must re-check that it still owns the hold.
   Sites:    src/lib/sync/useSyncTrigger.ts:141, :208; src/lib/miden/sdk/miden-client.ts:88;
             worker realm: src/workers/sync.ts:60
             (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'await .*lock' .)
   Excluded: src/workers/index.ts - re-exports only, and never awaits the hold;
             docs/sync.md - prose that quotes the old call, tracked by C-05
   Must not: change the eviction timing; touch the SW driver (owned by C-04).
   Test:     sync-lock.test.ts - evict mid-await, assert the late call is dropped (fails today).
   Interacts with: C-04 (both touch the ceiling; C-04 lands first).
   Prediction: reverting the guard fails sync-lock.test.ts at "drops the late call", because
             the call after the parking await no longer re-checks hold ownership.
   ```

   `Sites` is the part that matters: enumerate by searching, not by memory, and list every
   arm, realm, caller and copy (JSDoc, README, CHANGELOG, `.d.ts`) the rule reaches. The
   search reconciles against the plan in both directions, so every path it finds is either
   a path the cluster already names - under `Sites`, or under `Test`/`Tests`/`Regression` -
   or an `Excluded` entry carrying the reason it is not a fix site. An `Excluded` entry
   naming a path the search did not find is refused, and so is one that names a path
   without a reason. You can no longer fix 8 of 10 sites silently: the 2 you skip have to
   be written down, with why.
   `Prediction` states which test fails, on which arm, at which assertion or message, and
   why - a concrete symptom, not a restatement of `Rule`. It is read twice, not filed and
   forgotten: Fix compares it against the observed pre-fix red run, and Verify compares it
   against the failure line `rev-mutate.sh` prints beside each pinned hunk. Both
   comparisons are yours - the tool surfaces what failed and never reads a prediction.
2. Choose the plan seats from the roster. When `$S/panel-request.json` exists, set `PLAN_COMPLETENESS_SEAT` to the first surviving non-extra seat in that frozen roster, preferring one whose adapter is not `agent`, and do not read the workhorse for this seat. When `$S/panel-request.json` is absent, the plan panel is one `plan-completeness` seat on the resolved workhorse: set `PLAN_COMPLETENESS_SEAT` to the `seat` in `$S/workhorse.json` when `family` is set, `PLAN_SEATS` to the JSON array `["<that seat>"]`, and set `PLAN_EVIDENCE_ARGS=(--assignment "$PLAN_COMPLETENESS_SEAT=plan-completeness")`. When `family` is null, set `PLAN_COMPLETENESS_SEAT` to the first surviving non-extra seat in roster order, preferring one whose adapter is not `agent` when the roster has one (an Agent seat runs the panel unenforced), `PLAN_SEATS` to the JSON array `["<that seat>"]`, and set `PLAN_EVIDENCE_ARGS=(--assignment "$PLAN_COMPLETENESS_SEAT=plan-completeness")`.
   When `roster.json` has `"plan_seats": "all"`, set `PLAN_SEATS` to the JSON array of every surviving non-extra seat, even when the preceding code
   panel included an extra or a one-seat repair, and deal the plan lenses by the same
   rule (`lenses = [plan-completeness,
   plan-soundness, plan-simplicity, plan-tests]`). Build one assignment per seat,
   with the plan-completeness seat as `--full-seat`. For three seats, combine
   `plan-completeness+plan-tests` on the first seat.
   For five or more, keep `plan-completeness` unique and cycle only the other
   three lenses on surplus seats.
   Record the plan panel immediately before launch:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=plan round=<N>p "seats=$PLAN_SEATS"
   ```
   Write `$S/r<N>p-panel.tsv` with one line per plan seat, bind the current plan bytes, and
   prepare the plan closure before rendering:
   ```bash
   PANEL_LABEL=<N>p
   PLAN_HASH=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
   MANIFEST=$(REV_PATCH_CHUNKS=${REV_PATCH_CHUNKS:-auto} REV_SOURCE_CONTEXT=${REV_SOURCE_CONTEXT:-1} python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" \
     --phase plan --plan "$S/fix-plan.md" --plan-sha256 "$PLAN_HASH" \
     --full-seat "$PLAN_COMPLETENESS_SEAT" "${PLAN_EVIDENCE_ARGS[@]}")
   PLAN_SNAPSHOT="$S/r$PANEL_LABEL-plan.md"
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh "$S" "$PANEL_LABEL" --panel "$S/r$PANEL_LABEL-panel.tsv" \
     --plan "$PLAN_SNAPSHOT" --evidence "$MANIFEST"
   ```
   The `--panel` render validates each rendered plan prompt against the schema-4
   manifest before atomically publishing it. Scope, lens, manifest hash, inline plan,
   and the complete authorized artifact set must match exactly. After every plan prompt
   renders, apply the same single ordinary prelaunch verify and require every prompt's
   one embedded manifest hash to match before fan-out.
   The parser requires every cluster to have `Findings`, `Rule`, `Sites`, `Prediction`,
   and at least one of `Test`, `Tests`, or `Regression`. Every path must resolve in the
   pinned repository snapshot. Locations are read only from `Sites` and the first
   token of a test field (`Test: <path> - <what fails today>`); every other field is prose,
   including `Prediction`.
   Locations may use `path:line`, `path:start-end`,
   or a shorthand `:start-end` after a path. `Sites` must include one bounded query in
   either exact form: `found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'PATTERN' .`
   or `found by: grep --exclude-dir=.git --null -r -n -- 'PATTERN' .`. These fixed
   flags cover every regular worktree file except `.git`. Do not add other globs,
   types, exclusions, path operands, maximum depth, redirects, or filename suppression.
   Keep the result below 80 lines. It must include every path named in `Sites`, and every
   path it finds must be one the cluster names in any field or an entry in the optional
   `Excluded: <path> - <reason>; <path> - <reason>` field. Semicolons separate entries, so
   a reason may contain commas, and the reason is mandatory. Native text search cannot
   certify this proof.
   Every reviewer receives the full inline plan and complete navigation index. The
   plan-completeness seat receives the full cumulative patch and every cluster's
   closure, search, and source obligations. With `"plan_seats": "all"`, each cluster is
   also routed to one specialist. With a valid predecessor receipt, specialists
   receive only the fix delta for their clusters; otherwise they
   receive the cumulative cluster closure. They never receive a full-state fallback.
   Each specialist prompt names one exact primary artifact as its
   mandatory first native read. Do not prepend a directory command, search, or
   compound shell command. Assigned seats receive up to three source-context shards and
   the hash-bound repository-wide sibling-site search result prepared once from the
   frozen snapshot. With specialists, every cluster has two independent readers.
   Assigned seats may run additional searches when the prepared result raises a
   question. If preparation or any render fails, fix the evidence or task compiler and
   prepare a fresh schema-4 label before launch. Never mix attempts.

   Use the matching round label `<N>p` (the plan panel is extra, not a numbered code
   panel); write its outputs as `r<N>p-<seat>.json`. Collect as usual. Before triage,
   validate the complete panel without changing code coverage; `verify-panel` certifies
   the one-seat plan panel once that seat returns:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" verify-panel "$S" "$PANEL_LABEL"
   ```
   `verify-panel` binds the plan, manifest, prompts, streams, results, patch chunks,
   source packets, finding citations, and every cluster search and source proof. It
   never writes a receipt or advances `coverage-head.json`. An individual provider
   execution failure with no invalid read audit retains valid sibling results and may
   retry only that seat once with its exact prompt, assignment, model, and effort, even if it left an `INCOMPLETE PROOF` result. A failed plan seat, after its exact retry for an execution failure or immediately for a hard plan read-audit failure or an exit-0 `INCOMPLETE PROOF` result, is replaced by an ordinary one-seat plan panel on another eligible seat: `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh "$S" phase=plan round=<N>px "seats=[\"$OTHER\"]"`, then `${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py prepare "$S" "<N>px" --phase plan --plan "$S/fix-plan.md" --plan-sha256 "$PLAN_SHA256" --assignment "$OTHER=plan-completeness" --full-seat "$OTHER"`. It keeps the schema-4 plan contract, and under `plan_seats: all` it covers every cluster with the completeness lens; preserve every completed sibling and partial stream. If the `<N>px` panel fails too, leave the configured plan panel incomplete and review the plan yourself against the plan contract before any edit. Do not broaden a specialist to full scope or replace the
   schema-4 task with a legacy prompt.
3. Triage the plan findings like any others (verify against the code; ledger entries carry
   the `Cluster:` line). Amend `fix-plan.md` in place: add the sites the panel found, split
   or merge rules, replace a mechanism with the reuse a seat named. A plan finding that
   the panel got wrong is `REJECTED` like any other.
4. Then, and only then, **Fix**.

The default plan panel costs one seat launch. A plan that survives review is what the fix
commits implement - nothing outside it lands this round.
