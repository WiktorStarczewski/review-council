### Plan - the fix-design gate

Run the plan panel when accepted findings require a nontrivial change; skip it when
there is no accepted fix or every accepted fix is a P3 or one-line P2. Repeat it only
when verification accepts a new P0/P1 root cause or another nontrivial cluster.
The plan panel runs after triage and before any edit of the working tree.
When the plan panel is skipped, append a line beginning `Plan panel r<N>p - SKIPPED: <reason>` to `$S/findings.md` before `phase=fix`.
`rev-state.sh` refuses `phase=fix` for code round `<N>` while `open.P0 + open.P1 + open.P2` is above zero, unless the skip line exists, every original plan assignment has its own valid result or a successful bound one-seat replacement, or a current, hash-bound manual plan review accepts the full plan after the eligible chain is exhausted.
An incomplete plan panel is not a skip: after fixing a local cause, continue through `rev-workhorse.py escalate`, which honors a matching per-review override and otherwise uses the next higher enforced seat, until a valid plan result exists or the eligible chain is exhausted. Once each unresolved assignment has recorded terminal failure and no replacement is pending, review the plan yourself against the plan contract before any edit and record that review in `r<N>p-manual-plan-review.json`. The record must bind the exact plan and manifest hashes, name every original assignment in `reviewed_assignments`, list exactly the unresolved failed assignments in `failed_assignments`, set `escalation_exhausted` to true and `decision` to `accepted`, include a non-empty summary, and set all five `contract_checks` (`required_cluster_fields`, `bounded_site_search_and_path_accounting`, `falsifiable_tests_and_predictions`, `authorized_scope_preserved`, and `objections_resolved`) to true. The gate verifies each failure against its persisted terminal-failure evidence and refuses while any replacement is pending. A matching non-certifying diagnostic settles only that replacement attempt; it never covers the original assignment. This record is an operator attestation, not a seat result, panel receipt, or SKIPPED marker.

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
   Preparation prints `evidence: stage <name>` on stderr as it moves through snapshot,
   plan-search, prior-coverage, source-context, and capacity. `REV_PREPARE_TIMEOUT` bounds
   that run (default 1200 seconds, an integer from 1 to 3600). Exit 2 leaves
   `prepare-diagnostic-<label>.json` in the session. That file is not a manifest, not a
   receipt, and never certifies a panel. A refusal of `mandatory source reads exceed
   repository capacity` records each seat's limit, calculated count, mandatory windows, and
   selected target in that diagnostic. A timeout records `timed_out` and the stage. Read
   limits and coverage requirements stay unchanged. Do not launch plan seats after either
   refusal, do not repeat that prepare unchanged, and do not use the provider-seat replacement.
   One fresh schema-4 label is allowed only after the plan's site list or the
   evidence compiler changes. If the same refusal remains, keep the plan panel incomplete.
   Review the plan and diagnostic to identify a plan, input, or compiler correction; do not
   enter `phase=fix` on manual approval alone. A root plan preparation diagnostic has no
   manifest or terminal seat evidence and cannot satisfy the manual plan-review gate. For a
   one-seat replacement, its matching diagnostic settles that attempt only; after correcting
   the cause, register a fresh child label. It never counts as a successful assignment.

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
   retry only that seat once with its exact prompt, assignment, model, and effort, even if it left an `INCOMPLETE PROOF` result. After that retry, or immediately after a hard plan read-audit failure or an exit-0 `INCOMPLETE PROOF` result, continue the failed assignment through `rev-workhorse.py escalate`. Initialize `LAST_EXECUTOR` to the failed seat; call `rev-workhorse.py escalate --session "$S" --seat "$LAST_EXECUTOR"`, then update `LAST_EXECUTOR` to each replacement executor that fails so the configured chain advances. Keep the replacement bound to the original failed assignment throughout. For each eligible replacement, use a fresh unique plan label (`<N>px`, then `<N>px2`, and upward), record it with `rev-state.sh`, and prepare it against the current plan bytes and hash. A replacement label always gets a fresh manifest and rendered prompt; if `fix-plan.md` changed, recompute `PLAN_HASH`, prepare the new label from that plan snapshot, render again, and verify the embedded manifest hash before launch. Each replacement is an ordinary one-seat plan panel on another eligible seat, for example `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh "$S" phase=plan round=<N>px2 plan_replacement_for="<N>p:<ORIGINAL_FAILED_SEAT>" "seats=[\"$OTHER\"]"`, then `${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py prepare "$S" "<N>px2" --phase plan --plan "$S/fix-plan.md" --plan-sha256 "$PLAN_HASH" --assignment "$OTHER=plan-completeness" --full-seat "$OTHER"`. This binding lets `rev-state.sh` require a successful current-hash result for every original plan assignment before `phase=fix`; one successful child cannot cover failed or stale siblings. It keeps the schema-4 plan contract, and under `plan_seats: all` it covers every cluster with the completeness lens; preserve every completed sibling and partial stream. Continue until a valid plan result exists or the configured eligible chain is exhausted. Only then review the plan yourself against the plan contract before any edit. Do not broaden a specialist to full scope or replace the schema-4 task with a legacy prompt.
3. Triage the plan findings like any others (verify against the code; ledger entries carry
   the `Cluster:` line). Amend `fix-plan.md` in place: add the sites the panel found, split
   or merge rules, replace a mechanism with the reuse a seat named. A plan finding that
   the panel got wrong is `REJECTED` like any other.
4. Then, and only then, **Fix**.

The default plan panel costs one seat launch. A plan that survives review is what the fix
commits implement - nothing outside it lands this round.

An explicitly authorized fresh full plan generation for the same code round uses
`<N>p2`, then `<N>p3` and upward. Use that exact label for state registration,
preparation, rendering and launch, preserving every earlier generation. Record its
full roster with `rev-state.sh` before launch. A failed assignment in `<N>p2` uses
children `<N>p2x`, `<N>p2x2` and upward with
`plan_replacement_for="<N>p2:<ORIGINAL_FAILED_SEAT>"`; never bind it to `<N>p`.
The fix gate requires the highest registered root generation for that numeric code
round, even after restoring `round=<N>`. Older completion or skip evidence cannot
bypass a newer pending generation. New root suffixes start at 2 without leading
zeros; legacy replacement spellings such as `<N>px02` remain accepted. Differently
spelled roots tied at the newest generation are ambiguous and refuse the fix gate.
Original manifests, prompts, plan hashes and sibling results remain unchanged;
children still require a failed or stale original assignment and successful
current-plan-hash evidence.
