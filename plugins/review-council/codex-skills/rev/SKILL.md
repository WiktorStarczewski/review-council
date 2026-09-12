---
name: rev
description: Convene the Review Council for independent multi-model review, adversarial review panels, or iterative council review and fixes. Use when the user asks for review-council, a council review, or multiple model/provider opinions on code, a PR, a plan, or documents. Supports branch, uncommitted, path, PR, read-only, and round-count scopes.
---

# Review Council for Codex

You are the orchestrator. Independent CLI reviewers inspect the scope; you verify
claims against evidence, fix actionable defects within the user's scope, and repeat.
Agreement is a signal, never proof. Preserve the user's requested scope and prior
authorization. A request for report-only review remains report-only. This skill does
not authorize pushing, publishing, rewriting history, or changing unrelated files.
Do not start a council automatically after unrelated implementation work.

## Locate and set up

Resolve `PLUGIN` to the directory two levels above **this loaded SKILL.md**. Never
assume the shell cwd is the plugin or use `CLAUDE_PLUGIN_ROOT`. All script paths below
are relative to that absolute `PLUGIN`; quote paths and use arrays for arguments.

- Check `REV_ACTIVE` on entry: if set, refuse a nested council.
- Set `REVIEW_COUNCIL_HOST=codex` on **every** runner invocation, including preflight.
  Shell environment changes may not persist between tool calls. All seats in the
  Codex roster are actual external CLI processes, including Anthropic's `opus` seat.
- Default scope is `branch`; accept `uncommitted`, a path, branch name, PR number or
  URL, or document paths. Resolve PR metadata and base read-only with `gh`; review a
  different branch in an isolated worktree instead of changing a dirty checkout.
  Respect an explicit `--base`. Do not fabricate a base when it cannot be resolved.
- The default code fix loop is adaptive. With the configured four-seat panel, a
  normal review plans 12 seat launches: four simplicity, four conditional plan, and
  four final verification launches. A large or high-risk review plans 16 by adding
  four risk-discovery launches.
  An explicit round count is a minimum override and exclusively selects the
  legacy numbered schedule. `--read-only` and
  document or plan reviews default to one panel with no edits or commits.
- A change is large with more than 25 changed files or more than 1,500 changed lines.
  It is high-risk when it crosses a security, persistence, concurrency,
  transaction, or public API boundary. Either condition adds risk discovery.
- Reuse a requested session directory; otherwise make one with `mktemp -d
  /tmp/rev-XXXXXX`. Call it `S`. Read any existing ledger before continuing. Keep all
  logs, prompts, reviewer outputs, and ledgers there, away from the reviewed files.

Immediately after selecting the session, canonicalize it once. This makes macOS `/tmp` and `/private/tmp`
share one manifest identity:

```bash
mkdir -p "$S"
S=$(cd "$S" && pwd -P)
```

For code, run from the repository root:

```bash
REVIEW_COUNCIL_HOST=codex "$PLUGIN/scripts/rev-preflight.sh" \
  --scope branch --write "$S"
```

Substitute the resolved scope and append `--base <ref>` when specified. This writes
`scope.env`, `files.txt`, `untracked.txt`, and the **probed** `roster.json`. Preflight
refuses empty scopes or shared branches; use a worktree if a code review needs one.
For documents, write absolute paths to `S/docs.txt`, set `REV_REPO` to their root,
and run `roster.sh --probe --brief --write "$S/roster.json"` without git preflight.
Probes and reviews contact the configured providers and consume their usage.

Print the roster and any `degradation` reason before reviewing. Never replace a
missing provider with an imaginary in-process agent. Repeated CLI seats are separate
runs with different lenses, **not** additional labs. Exit 5 is retryable. Relay the
one-line reason verbatim, preserve the session, and retry when provider availability
recovers. Exit 6 is permanent. Relay the one-line reason verbatim and stop because the
scope or strict roster contract cannot run as asked.
Configuration is `~/.config/review-council/config.json` (or `REVIEW_COUNCIL_CONFIG`):
`exclude`, `pin`, `codex_models`, `claude_seat`, `claude_seats`, `extras`, and
`min_labs` are shared with Claude Code.
See [configuration](https://github.com/WiktorStarczewski/review-council/blob/main/docs/config.md) for the full format.

Read repository instructions, inspect the diff and consumers, and record existing
failures in `S/baseline.md` using relevant project checks. Do not require unrelated
checks for prose. Initialize `findings.md` and `rejected.md` without overwriting a
resumed ledger. Record state via `rev-state.sh "$S" key=value ...`:
`round`, `min_rounds` (the explicit override or `adaptive`), `phase`, `seats` (JSON array), `dropped`, `open.P0` through
`open.P3`, and `fixed`. State updates are sequential.

## Run the adaptive panels

Read the roster and use every non-extra seat. Adaptive default panels use core seats
and omit extras. Explicit numeric round plans may include extras in their configured
rounds. Run these panels in order:

1. **Simplicity discovery:** every core seat gets `simplicity`. Keep all four seats;
   held-out evaluation shows the union finds material simplifications that one seat
   misses.
2. **Risk discovery:** only for a large or high-risk change. Deal the four bundles
   below across the full panel.
3. **Plan:** apply the plan gate below before a nontrivial edit.
4. **Verification:** deal the four bundles across one full panel over the latest
   material state. Prioritize changes
   since the last completed panel and trace their consumers; re-read cumulative code
   where the interaction requires it.

The four risk and verification bundles are `correctness-boundaries`,
`security-state-api`, `concurrency-resources-performance`, and
`tests-observability-maintenance-regression`. Together they cover logic, edge cases,
error handling, trust boundaries, durable state, contracts, concurrency, resources,
performance, tests, observability, maintenance, and regression risk.

One four-bundle verification panel reviews the latest material state: directly after
discovery when no nontrivial fix follows, or after the latest nontrivial fix. After a
risk or verification panel returns at least three valid reviewers, compute coverage
from valid outputs for any roster size; run every missing bundle as an `<N>x` repair
on a distinct surviving seat before certification. A coverage repair is one seat, so
the three-reviewer minimum does not apply. Do not certify the adaptive panel until all
four bundles have valid results. Set `REPAIR_SEATS` to exactly the seats launched for
that repair, then write `rev-state.sh "$S" phase=repair round=<N>x "seats=$REPAIR_SEATS"`
immediately before launching it.

An explicit numeric override exclusively uses the legacy numbered code-panel schedule below.
Conditional plan panels are extra and do not count toward the requested total.
For round 9 and later, target uncovered or unresolved risk.

| Round | Emphasis | Lenses | Extra |
| --- | --- | --- | --- |
| 1 | Could this change be smaller? | simplicity | - |
| 2 | Logic and boundaries | correctness, edge-cases, error-handling | - |
| 3 | Security and state | security, data-state | codex-review |
| 4 | Concurrency and resource use | concurrency, resources, performance | grok-code-review |
| 5 | Contracts and compatibility | api-contract, readability, maintainability | - |
| 6 | Verification | tests, observability | - |
| 7 | Argue the change is broken | red-team | - |
| 8 | Re-read the cumulative diff | regression | - |
| 9+ | Remaining gaps | rotate uncovered or unresolved lenses | - |

Repeat plan, fix, and verification only for a new P0/P1 root cause, an open P0/P1,
or another nontrivial fix. A P3 or one-line P2 follow-up needs the project gates;
every other accepted fix needs a full adaptive verification panel. Never append the cumulative findings ledger to a
prompt. For a resumed run, write `S/context.md` as a concise digest of
settled decisions; the renderer includes it automatically. Do not copy `findings.md` into it.

### Panel setup

Read the roster and rebuild the launched seat list before every panel. Set
`LAUNCHED_SEATS` from every surviving non-extra seat plus only extras configured for
this numeric round. Do not append seats from the prior panel. Assign every lens and
risk bundle before preparing or rendering prompts. Numeric extras keep their fixed
lenses.

### Adaptive scope preparation

Scope optimization never changes the preflight roster, its models, efforts, or
seat count. Use every configured core seat, including Sol, Grok, and both Opus seats
when that is the configured roster.
Cover all four risk bundles at least once in every risk and verification panel.
Let `BUNDLES` be the four bundles in their listed order. In stable roster order, core seat `i` receives bundle `BUNDLES[i mod 4]`.
With three core seats, add the fourth bundle to the first seat.
With four core seats, use one canonical bundle per seat; this assignment is unchanged.
With five or more core seats, cycle through `BUNDLES` again for surplus seats.
When a seat receives multiple bundles, join the bundle names with `+` in one
`--assignment`. Set its risk or verification lens to the same canonical composite.

The first core seat is the discovery full-state owner. The first seat in roster order
that carries `tests-observability-maintenance-regression` is the full-state owner for
risk and verification. A repair seat receives the full cumulative patch.
A valid narrowed panel has exactly one full-state seat.

`rev-evidence.py` owns semantic component assignment; the host passes no component flags.
Every semantic component receives specialist and full-state integration coverage.
A changed component containing a prior finding returns to that finding owner.
When the integration seat owns the finding, the component also goes to the least-loaded specialist.
Missing or invalid ownership data restores normal component routing. If complete
component coverage cannot be proved, every seat receives the full cumulative patch.
No usable delta keeps specialists on cumulative semantic scope when current evidence is safe.
Only delta scope binds a predecessor; it alone reuses prior finding ownership.
An invalid predecessor sends every seat the full cumulative patch.

For a large valid UTF-8 assigned patch, the manifest may replace 240-line proof
windows with ordered immutable patch chunks. The canonical monolithic patch and its
SHA-256 remain the identity. Identical assigned patch bodies share one patch set.
Each chunk is at most 24 KiB raw, 30 KiB after reserving eight prefix bytes per
displayed line, and 1,000 displayed lines. Its inclusive start and exclusive end byte
offsets are contiguous, and concatenating the chunks without delimiters must reproduce
the canonical patch exactly. Reviewers read every chunk once, in rendered order and in
full, before source-context packets or source expansion. Chunk reads prove change
discovery only; they never establish source citation evidence.
The 32 KiB per-tool and ordinary per-turn output limits still apply. Grok and Claude adapters may read two consecutive chunks in one turn under a patch-only 60 KiB combined cap; other adapters
read one. Chunk mode is used only when it saves at least
10 percent against 240-line windows. Invalid UTF-8, NUL, an older manifest without a
chunk set, or `REV_PATCH_CHUNKS=0` keeps window mode.

Each assignment also carries deterministic source-context shards selected from the
exact manifest snapshot. These JSON shards contain literal source bytes with original
paths and one-based ranges. They are evidence, not summaries. A specialist receives at most one 32 KiB shard; the full-state integration seat receives at most three.
Every reviewer reads each listed shard in full before source expansion. When the
rendered fragment says `Source read required: true`, or a concrete control-flow or
dispatch question extends outside a shard, the reviewer opens another bounded source
range. Repository instructions remain in the separate manifest-bound instruction
snapshot and are never copied into source-context shards.
An oversized mandatory range remains one parent proof but is delivered through the
rendered immutable-object recipes as ordered, gapless segments of at most 240 lines
and 16 KiB predicted visible output. Claude and Grok may read two listed source
segments per turn; Codex and Gemini read one.
Every segment must be read once in order before the parent range earns a receipt.

Evidence preparation applies to adaptive code panels and accepted-fix plan panels.
Explicit numeric panels use the full cumulative patch, omit evidence preparation,
and leave `MANIFEST` empty. Document panels read every supplied document in full,
omit evidence preparation, and append `--read-only "$S/docs.txt"` in the render pass.

If any launched roster row has adapter `agent`, skip evidence preparation for the
whole panel and keep `MANIFEST` empty. Claude Code plugin subagents ignore hook frontmatter,
so an Agent seat cannot provide the enforced tool transcript required by evidence mode.
Render and launch every seat at full legacy scope under the same panel label.

Before adaptive fan-out, set `PANEL_LABEL` to the artifact label and `PANEL_PHASE` to
`discovery`, `risk`, `verification`, or `repair`. Build `EVIDENCE_ARGS` from the exact
launched seats: discovery passes `--full-seat` for the first core seat; risk and
verification pass one `--assignment "$SEAT=$BUNDLE_OR_COMPOSITE"` per seat plus
`--full-seat` for the first regression-bundle seat; repair passes its one assignment
and that repair seat as `--full-seat`. Then prepare once:

```bash
MANIFEST=
if CANDIDATE=$(REV_PATCH_CHUNKS=${REV_PATCH_CHUNKS:-0} REV_SOURCE_CONTEXT=${REV_SOURCE_CONTEXT:-0} python3 "$PLUGIN/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" --phase "$PANEL_PHASE" "${EVIDENCE_ARGS[@]}"); then
  case "$CANDIDATE" in
    "$S/r$PANEL_LABEL-evidence.manifest.json") [ -r "$CANDIDATE" ] && MANIFEST=$CANDIDATE ;;
  esac
fi
```

`REV_PATCH_CHUNKS=1` and `REV_SOURCE_CONTEXT=1` enable the held-out adoption
candidate. The defaults remain `0` until an exact-roster panel certifies the delivery
path. Baseline and candidate runs must otherwise use the same snapshot, roster,
models, efforts, bundles, and host steps.
Both runs keep the same component assignments and patch narrowing.

Build the optional flag once. Render every seat before any reviewer process starts,
using the same flag array for the entire panel. Append `--vacuity` whenever tests are
touched, and append `--read-only "$S/docs.txt"` for document panels only.

```bash
EVIDENCE_PROMPT_ARGS=()
[ -n "$MANIFEST" ] && EVIDENCE_PROMPT_ARGS=(--evidence "$MANIFEST")
"$PLUGIN/scripts/rev-prompt.sh" "$S" "$PANEL_LABEL" "$SEAT" "$LENS" "$EMPHASIS" "${EVIDENCE_PROMPT_ARGS[@]}"
```

If any evidence prompt render fails, discard the narrowed panel.
Set `MANIFEST=` and `EVIDENCE_PROMPT_ARGS=()`.
Render every seat again without `--evidence`. A failed legacy render stops the panel. Never mix evidence and legacy
prompts in one panel, reuse a partially prepared manifest, or narrow coverage after
an evidence error.

Before triage or receipt, require every evidence-launched seat to have a read audit with schema 2 in `r<label>-<seat>.read-audit.json`, a valid status, exact
manifest, prompt, stream, and result hashes, at least one recognized review tool, and
canonical packet or bounded source ranges. Every finding citation must intersect one
of those audited ranges. A missing, malformed,
stale, partial, oversized, unassigned, or unparseable packet or source range invalidates
the whole attempt. The same is true for unsupported provider transcript shapes and
zero-tool answers. In chunk mode, the audit also requires every hash-bound chunk once
in exact order before packet and source reads. Missing, reordered, truncated, replaced,
duplicate, unassigned, redirected, or oversized chunks invalidate the attempt.

On any such failure, discard every result from the attempt. Under a fresh fallback label `<N>f`, clear `MANIFEST` and `EVIDENCE_PROMPT_ARGS`, then rerender and relaunch every seat with the full cumulative patch and no source-context packet. Use only fallback results for
triage. Never mix narrow and full results, and never create a coverage receipt for the
failed attempt.

After every assigned seat has a valid result, certify discovery after its complete simplicity panel.
For risk and verification, certify only after the complete four-bundle panel is
collected:

```bash
python3 "$PLUGIN/scripts/rev-evidence.py" receipt "$S" "$PANEL_LABEL"
```

If receipt fails, the next adaptive panel must use the full cumulative patch.
The failed receipt establishes no coverage. A standalone `<N>x` repair cannot advance the
coverage head. Run the repair at full scope, then rerun a complete four-bundle panel
under a fresh label before certification.

### Fan out

Read-only **code** still uses the normal code prompt. PR descriptions are not
included by default: let reviewers question the design before seeing its rationale.

Fan-out launches only those already-rendered prompt files. Never call
`rev-prompt.sh` between the completed render pass and launch. Launch independent
seats concurrently using the available shell execution tools.

Record the exact artifact label and the same launched seats whose prompts were already
rendered immediately before starting processes:

```bash
"$PLUGIN/scripts/rev-state.sh" "$S" phase=fan-out round=<N> "seats=$LAUNCHED_SEATS"
```

```bash
REVIEW_COUNCIL_HOST=codex REV_REPO="$REPO" \
  "$PLUGIN/scripts/rev-seat.sh" "$SEAT" "$S" "$ROUND" "$PROMPT" --base "$BASE"
```

Pass the pinned `REV_BASE` from `scope.env`, parsed as data; do not source untrusted
files. Omit `--base` for documents. Use the actual tools available in this Codex
session; do not invoke Claude's `Agent`, `Monitor`, or `TaskStop` APIs. Keep processes
attached to a tool session and wait/poll until all complete. Do not edit during
reviewer reads. Do not end the turn while reviewers or gates remain running.
The CLI runner enforces read-only review tools and validates the findings schema.
After all processes launch, switch to collect while retaining the exact label and
seats with `rev-state.sh "$S" phase=collect round=<N> "seats=$LAUNCHED_SEATS"`.

Inspect each `.exit`, `.json`, and `.log`; absence of findings is not success without
a valid completed response. Exit 1/2: retry once at the next supported lower effort
(`max` → `xhigh` → `high`; omit for models without effort). Exit 3: stop and name the
sign-in problem. Exit 4: drop that seat for the run. If fewer than three reviewers
complete a round, report an incomplete panel; do not substitute your own review.
Record reduced coverage and failed extras; never label an incomplete run clean.

## Triage, plan, fix, verify

Open the cited code and consumers; reproduce or reason through the concrete failure
before accepting a finding. Deduplicate by root cause. Reject false positives with
specific evidence in `rejected.md`. A reuse finding must name an existing symbol you
opened. Scope cuts are `DEFERRED (scope decision)`, not unrequested product changes.

Maintain a ledger entry per finding: ID, severity P0-P3, status OPEN/FIXED/REJECTED/
DEFERRED, file and line, claim, evidence, reporting seats, disposition, test result,
and commit if any. Do not re-raise resolved findings without new evidence.

Run the plan panel when accepted findings require a nontrivial change; skip it when
there is no accepted fix or every accepted fix is a P3 or one-line P2. Write
`S/fix-plan.md`: accepted findings, proposed changes, existing components to reuse,
risks, and falsifiable tests. Repeat the gate only for a new P0/P1 root cause or
another nontrivial cluster.
Set `PLAN_SEATS` to every surviving non-extra seat, including after an extra or a
one-seat repair. Immediately before launch, write
`rev-state.sh "$S" phase=plan round=<N>p "seats=$PLAN_SEATS"` so status reads the
plan artifacts and its full panel instead of the completed code panel.

Deal `plan-completeness`, `plan-soundness`, `plan-simplicity`, and `plan-tests` in
stable roster order. Build one `--assignment` per seat and use the
plan-completeness seat as `--full-seat`. For three seats, combine
`plan-completeness+plan-tests` on the first seat.
For five or more, keep `plan-completeness` unique and cycle only the other three
lenses on surplus seats.
Every cluster must contain `Findings`,
`Rule`, `Sites`, and at least one of `Test`, `Tests`, or `Regression`. Its `Sites`
field must include a bounded `found by: rg ...` or `found by: grep ...` query whose
only path operand is `.`. Using grep requires `-r`, `-R`, or `--recursive`. Do not
use traversal filters such as globs, types, exclusions, hidden/ignore flags, or
maximum depth. Require line-numbered filename output, add `--null`, do not redirect it,
and keep the result below 80 lines. The output must include every path named in `Sites`;
native text search cannot certify this proof.
Locations may use `path:line`, `path:start-end`, or a shorthand `:start-end` after
a path.
Bind and prepare the immutable plan before rendering:

```bash
PANEL_LABEL=<N>p
PLAN_HASH=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
MANIFEST=$(python3 "$PLUGIN/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" \
  --phase plan --plan "$S/fix-plan.md" --plan-sha256 "$PLAN_HASH" \
  --full-seat "$PLAN_COMPLETENESS_SEAT" "${PLAN_EVIDENCE_ARGS[@]}")
PLAN_SNAPSHOT="$S/r$PANEL_LABEL-plan.md"
"$PLUGIN/scripts/rev-prompt.sh" "$S" "$PANEL_LABEL" <seat> <plan-lens> \
  "<round emphasis>" --plan "$PLAN_SNAPSHOT" --evidence "$MANIFEST"
```

Every reviewer receives the full inline plan, every cluster, the complete navigation
index, the same plan-site and one-hop local-import changed closure, and up to three
source-context shards. The plan-completeness seat receives the full cumulative patch.
Every seat must run each cluster's rendered repository-wide sibling-site query from the repository
root and prove each required cluster source location. Before triage run:

```bash
python3 "$PLUGIN/scripts/rev-evidence.py" verify-panel "$S" "$PANEL_LABEL"
```

This validation never writes a receipt or advances `coverage-head.json`. If prepare,
render, or validation fails, discard every result and rerun all plan seats under a
fresh `<N>pf` label with legacy full scope and no evidence manifest. Agent-seat plan
panels always use that legacy-full path. Never mix attempts. Verify and address plan
objections before editing. Keep one rule per root-cause cluster with a compact site
table, invariants, and falsifiable tests.

Apply confirmed fixes in coherent clusters. Preserve user changes. Run the relevant
gates and bring them to baseline or better. Add meaningful regressions when warranted,
not tests that merely mirror implementation. Commit only when within the user's
requested workflow, with `fix(rev): <concrete change>` and no unrelated files. Record
uncommitted fixes accurately when commits were not requested. Read-only runs skip
all fix, commit, squash, push, and post-report editing steps.

Update state and the ledger after every phase. During foreground work send concise
progress regularly, including `rev-status.sh "$S"` when useful; use waits of at most
60 seconds so the user can steer. The status script reads artifacts without model
calls. Large changes deserve explicit remaining-coverage notes, not just counts.

## Finish

Adaptive completion requires a full four-bundle verification panel after discovery
or the latest nontrivial fix, no new or open P0/P1 findings, no material change left
unreviewed, and gates at baseline or better.

Only numeric mode continues past its requested minimum while any of these hold: the
last numbered code panel produced a new P0/P1; the last numbered panel's fixes were
nontrivial; any P0/P1 remains open; or a lens or major changed file remains unreviewed.
Numeric mode stops only after the requested minimum numbered code panels ran, two
consecutive numbered code panels produced no new P0/P1, no P0/P1 remains open, and
gates are at or better than baseline. Plan panels do not count as numbered code panels.
Respect user stops and resource limits; report incomplete coverage honestly. Read-only
panels stop at the requested panel count and report findings without requiring fixes.

After every panel, run `rev-profile.py "$S"` and report completed calls, processed
tokens, prompt words, and provider cost when available. Current-session completion
and finding yield require a schema-valid result with a successful exit receipt. Only
exact hashed receiptless results recorded in a versioned legacy roster policy may omit
one. Usage-bearing failed attempts remain metered.
Prompt generation warns above
1,800 words for code and 3,000 words for plans; investigate the repeated context
instead of silently truncating evidence.

Do not squash or push unless the user authorized those actions. If authorized, use
`rev-squash.sh` dry-run before `--apply`; a refusal leaves history intact. Push only
the authorized branch. In `REV_STACK_LEG=1`, never squash or push; the stack controls
those actions. If blocked in a headless leg, record `phase=blocked` and exit without
a completion receipt; do not guess approval or report success.

On completion set `phase=done` and write `S/report.md` with scope/base, actual roster
and degradation, rounds/lenses, accepted/rejected/deferred findings and evidence,
changes/commits, baseline/final gates, and remaining limitations. `report.md` is the
stack's success receipt: write it only for a completed review. Interrupted/blocked
runs write `incomplete.md`. End with the substantive results and report path.
