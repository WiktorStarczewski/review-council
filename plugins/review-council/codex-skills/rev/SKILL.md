---
name: rev
description: Convene the Review Council for independent multi-model review, adversarial review panels, or iterative council review and fixes. Use when the user asks for review-council, a council review, or multiple model/provider opinions on code, a PR, a plan, or documents. Supports branch, uncommitted, path, PR, read-only, and round-count scopes.
---

# Review Council for Codex

This skill is an executable workflow contract. Follow every applicable step in its stated order. Do not cherry-pick, replace, or improvise around steps. Before omitting a step, record the exact reason it is inapplicable. A run missing any audit, receipt, or final report required by its selected mode is incomplete and must not be described as a Review Council review.

You are the orchestrator. Independent CLI reviewers inspect the scope; you verify
claims against evidence, fix actionable defects within the user's scope, and repeat.
Agreement is a signal, never proof. Preserve the user's requested scope and prior
authorization. A request for report-only review remains report-only. This skill does
not authorize pushing, rewriting history, or changing unrelated files. The completion
contract authorizes only the canonical `COMMENTED` PR review for an associated open PR.
Do not start a council automatically after unrelated implementation work.

## Locate and set up

Resolve `PLUGIN` to the directory two levels above **this loaded SKILL.md**. Never
assume the shell cwd is the plugin or use `CLAUDE_PLUGIN_ROOT`. All script paths below
are relative to that absolute `PLUGIN`; quote paths and use arrays for arguments.

- Check `REV_ACTIVE` on entry: if set, refuse a nested council.
- Set `REVIEW_COUNCIL_HOST=codex` on **every** runner invocation, including preflight.
  Shell environment changes may not persist between tool calls. All seats in the
  Codex roster are actual external CLI processes, including Anthropic Claude seats.
- Default scope is `branch`; accept `uncommitted`, a path, branch name, PR number or
  URL, or document paths. Resolve PR metadata and base read-only with `gh`; review a
  different branch in an isolated worktree instead of changing a dirty checkout.
  Respect an explicit `--base`. Do not fabricate a base when it cannot be resolved.
- The default code fix loop is adaptive. With the configured four-seat panel, a
  normal review plans 9 seat launches: four simplicity, one conditional plan, and
  four final verification launches. A large or high-risk review plans 17 by adding
  four risk-discovery and four full red-team launches. An important or explicitly
  adversarial review that is not otherwise large or high-risk plans 13 by adding
  four full red-team launches. With `"plan_seats": "all"`, every plan panel launches
  all four core seats instead of one.
  An explicit round count is a minimum override and exclusively selects the
  legacy numbered schedule. `--read-only` and
  document or plan reviews default to one panel with no edits or commits.
- A change is large with more than 25 changed files or more than 1,500 changed lines.
  It is high-risk when it crosses a security, persistence, concurrency,
  transaction, protocol, public API, or irreversible mutation boundary. Large or
  high-risk changes add risk discovery and the full red-team panel.
- Reuse a requested session directory; otherwise make one with `mktemp -d
  /tmp/rev-XXXXXX`. Call it `S`. Read any existing ledger before continuing. Keep all
  logs, prompts, reviewer outputs, and ledgers there, away from the reviewed files.
- For a code review associated with an open PR, `S` must resolve outside the reviewed repository.
  An unassociated local render may remain inside, but it cannot publish.

Immediately after selecting the session, canonicalize it once. This makes macOS `/tmp` and `/private/tmp`
share one manifest identity:

```bash
mkdir -p "$S"
S=$(cd "$S" && pwd -P)
```

Before any preflight or provider probe, classify a code session by inspecting
`scope.env`, `files.txt`, `untracked.txt`, and `roster.json` with `lstat`:

- `fresh`: none of the four inputs exists, so preflight may run once
- `initialized`: all four safe inputs exist, so validate and reuse them without probing
- `invalid`: a partial or unsafe set exists, so stop incomplete and use a fresh session

For `initialized`, import `validate_standard_inputs` from
`$PLUGIN/scripts/lib/session_inputs.py`, call
`validate_standard_inputs(Path(S), require_all=True)`, and continue with those exact
bytes. Never rerun preflight or repair inputs in that session. Any validation failure
makes the state `invalid`; preserve that session untouched and choose a fresh session
before retrying. Only a `fresh` code session runs this from the repository root:

```bash
REVIEW_COUNCIL_HOST=codex "$PLUGIN/scripts/rev-preflight.sh" \
  --scope branch --write "$S"
```

Substitute the resolved scope and append `--base <ref>` when specified. Fresh preflight writes
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
`exclude`, `pin`, `codex_models`, `claude_seat`, `claude_seats`, `extras`,
`min_labs`, `plan_seats`, and `quota_fallback` are shared with Claude Code.
A fresh session rebuilds its roster once during preflight. An initialized session validates
and reuses its frozen roster without probing.
Roster configuration changes require a fresh session, whose preflight applies the new
configuration once.
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
3. **Full red team:** exactly once for a large, high-risk, user-marked-important, or
   explicitly adversarial adaptive review. Run it before planning under the promoted
   adversarial coverage contract below.
4. **Plan:** apply the plan gate below.
5. **Verification:** deal the four bundles across one full panel over the latest
   material state. Prioritize changes
   since the last completed panel and trace their consumers; re-read cumulative code
   where the interaction requires it. `--phase verification` adds to every seat:
   Sibling-site completeness: for each fix commit since the base, name the rule it
   applies and search the repository for sites, arms, realms, callers and copies
   (tests, JSDoc, docs) the rule reaches but the commit missed.

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
| 4 | Concurrency and resource use | concurrency, resources, performance | - |
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
seat count. Use every configured core seat, including Sol, Terra, Opus, and Sonnet
when that is the configured roster.
Cover all four risk bundles at least once in every risk and verification panel.
Let `BUNDLES` be the four bundles in their listed order. In stable roster order, core seat `i` receives bundle `BUNDLES[i mod 4]`.
With three core seats, add the fourth bundle to the first seat.
With four core seats, use one canonical bundle per seat; this assignment is unchanged.
With five or more core seats, cycle through `BUNDLES` again for surplus seats.
When a seat receives multiple bundles, join the bundle names with `+` in one
`--assignment`. Set its risk or verification lens to the same canonical composite.

### Promoted adversarial coverage

Every code panel, including explicit numeric and read-only code panels, gives one existing core seat a composite red-team emphasis without another provider call.
Select it deterministically from stable roster order and rotate it across code panels:
for zero-based code-panel ordinal `j` and `n` core seats, use seat `j mod n`.
Derive `j` from the planned panel order so a retry keeps the same owner. Append the
red-team instruction to that seat's normal emphasis before rendering: assume the
change is wrong and try to prove it by finding the input, timing, state, attacker,
failure, or consumer boundary that breaks it. This supplements and never replaces the canonical lens, bundle, fixed numeric lens, or evidence assignment.
Numeric mode adds no panel for this composite assignment.

Large, high-risk, user-marked-important, or explicitly adversarial adaptive reviews run exactly one full red-team panel before planning.
For this panel, set `PANEL_PHASE=risk` and reuse the existing four canonical bundle assignments without changing `rev-evidence.py` or its schema. The panel has these four distinct composed adversarial assignments, in bundle order:

1. correctness and boundaries plus attacker behavior and trust boundaries;
2. security, state, and API plus rollback and recovery;
3. concurrency, resources, and performance plus duplication and exhaustion;
4. tests, observability, and regression plus consumer compatibility and integration.

Map each entry above to its canonical bundle. When a core seat carries multiple canonical bundles, concatenate the matching adversarial emphases into that seat's single prompt emphasis in canonical bundle order.
For surplus seats, cycle the mapped adversarial emphasis with the canonical bundle, so
each repeated bundle repeats its matching emphasis. Keep the result in the existing
seat prompt; neither case changes the canonical topology or adds a provider call.

The full panel joins the same initial finding clusters and does not grant another correction cycle.
The ordinary adaptive and numeric stopping rules remain unchanged. Document panels receive no automatic red-team assignment unless the user explicitly requests an adversarial document review.

The verification owner always traces the cumulative change through consumers and integration boundaries. Compose these additional emphases when relevant:

- compatibility and consumer contracts for public APIs, protocols, schemas,
  serialization, CLI output, and cross-repository interfaces;
- recovery and idempotency for persistence, external writes, migrations, retries,
  concurrency, CI orchestration, and partial failure;
- security and trust boundaries for authentication, authorization, signatures,
  secrets, untrusted input, and privilege changes.

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
The 32 KiB per-tool and ordinary per-turn output limits still apply. Claude adapters may use two ordered proof reads in one turn across patch chunks, required source segments, and the evidence index under a 60 KiB combined cap; other adapters read one. Source-context packets and repository reads retain the ordinary 32 KiB turn cap. Repository expansion begins in a later turn. Chunk mode is used only when it saves at least
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
An oversized mandatory range remains one parent proof but is delivered through
manifest-hashed, session-local source artifacts as ordered, gapless segments of at
most 240 lines and normally at most 16 KiB predicted visible output. A one-line
segment may extend to the 32 KiB per-tool ceiling when that line cannot be split.
The renderer uses each adapter's
native full-file action: shell `cat` for Codex, `Read` for Claude, and `read_file` for
Gemini. Claude may read two listed source segments per turn; Codex and Gemini read
one. Every segment must be read once in order before the parent range
earns a receipt.

Evidence preparation applies to adaptive code panels and accepted-fix plan panels.
Explicit numeric panels use the full cumulative patch, omit evidence preparation,
and leave `MANIFEST` and `PANEL_PHASE` empty.
Document panels read every supplied document in full,
omit evidence preparation, and render each seat with the per-seat form and
`--read-only "$S/docs.txt"`.

Evidence mode depends on each launched row's adapter, never on the host.
If any launched code-panel roster row has adapter `agent`, skip evidence preparation
for the whole code panel and keep `MANIFEST` empty. Claude Code plugin subagents ignore
hook frontmatter, so an Agent seat cannot provide the enforced tool transcript required
by evidence mode. Render and launch every code seat at full legacy scope under the same
panel label. Rows on adapters `codex`, `gemini`, and `claude` launch through
`rev-seat.sh` and keep evidence mode.
`claude_adapter` decides whether a Claude Code host seats Claude rows on `agent`; a Codex host always seats them on `claude`.
Plan preparation instead fails before publishing artifacts when any non-extra roster
row uses adapter `agent`. Report that plan review is unavailable with an Agent seat
and requires a roster whose seats use enforceable Codex or Claude CLI adapters, and
record that refusal as the plan panel's skip reason. Do not replace the schema-4 plan
with a legacy full-scope task.

Before adaptive fan-out, set `PANEL_LABEL` to the artifact label and `PANEL_PHASE` to
`discovery`, `risk`, `verification`, or `repair`. Build `EVIDENCE_ARGS` from the exact
launched seats: discovery passes `--full-seat` for the first core seat; risk and
verification pass one `--assignment "$SEAT=$BUNDLE_OR_COMPOSITE"` per seat plus
`--full-seat` for the first regression-bundle seat; repair passes its one assignment
and that repair seat as `--full-seat`. Then prepare once:

```bash
MANIFEST=
if CANDIDATE=$(REV_PATCH_CHUNKS=${REV_PATCH_CHUNKS:-auto} REV_SOURCE_CONTEXT=${REV_SOURCE_CONTEXT:-1} python3 "$PLUGIN/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" --phase "$PANEL_PHASE" "${EVIDENCE_ARGS[@]}"); then
  case "$CANDIDATE" in
    "$S/r$PANEL_LABEL-evidence.manifest.json") [ -r "$CANDIDATE" ] && MANIFEST=$CANDIDATE ;;
  esac
fi
```

`REV_PATCH_CHUNKS=auto` selects chunks when they save proof reads or are required to
fit the compiled provider capacity. `REV_PATCH_CHUNKS=1` forces chunks when the patch
is representable, while `REV_PATCH_CHUNKS=0` requests window mode and fails preparation
when that mode cannot fit. `REV_SOURCE_CONTEXT=1` enables literal source packets and
required-source segments. Baseline measurements may set both paths explicitly, but
must otherwise use the same snapshot, roster, models, efforts, bundles, and host steps.
Both runs keep the same component assignments and patch narrowing.

Build the optional flags once. Write one `<seat>`, tab, `<lens>`, tab, `<emphasis>`
line per launched seat, in `LAUNCHED_SEATS` order, to `$S/r$PANEL_LABEL-panel.tsv`;
each emphasis is one line with no tab.
Render every seat before any reviewer process starts, with one `--panel` call and the
same flag arrays for the entire panel. Append `--vacuity` whenever tests are touched.

```bash
EVIDENCE_PROMPT_ARGS=()
[ -n "$MANIFEST" ] && EVIDENCE_PROMPT_ARGS=(--evidence "$MANIFEST")
PHASE_PROMPT_ARGS=()
[ -n "$PANEL_PHASE" ] && PHASE_PROMPT_ARGS=(--phase "$PANEL_PHASE")
"$PLUGIN/scripts/rev-prompt.sh" "$S" "$PANEL_LABEL" --panel "$S/r$PANEL_LABEL-panel.tsv" "${PHASE_PROMPT_ARGS[@]}" "${EVIDENCE_PROMPT_ARGS[@]}"
```

`--panel` loads the evidence manifest once, writes every `r<label>-<seat>.prompt.md`,
prints their paths in order, and publishes none when any seat fails. Render a single
`<N>x` repair seat with the per-seat form
`"$PLUGIN/scripts/rev-prompt.sh" "$S" "$PANEL_LABEL" "$SEAT" "$LENS" "$EMPHASIS" "${PHASE_PROMPT_ARGS[@]}" "${EVIDENCE_PROMPT_ARGS[@]}"`.
An exact seat retry reuses its already-rendered prompt.

If any evidence prompt render fails, discard the narrowed panel.
Set `MANIFEST=` and `EVIDENCE_PROMPT_ARGS=()`.
Render every seat again without `--evidence`. A failed legacy render stops the panel. Never mix evidence and legacy
prompts in one panel, reuse a partially prepared manifest, or narrow coverage after
an evidence error.

When `MANIFEST` is nonempty, after every prompt renders, run one ordinary `rev-evidence.py verify` against
`MANIFEST` before writing fan-out state or launching a reviewer. Capture the final
space-delimited field from its output, require exactly 64 lowercase hexadecimal
characters, then inspect every already-rendered prompt. Every evidence prompt must
contain exactly one matching `Evidence manifest SHA-256: <hash>` line. A failed
verify, malformed hash, missing line, duplicate line, or mismatch discards the whole
narrowed attempt. Code panels use the all-legacy rerender path above; schema-4 plan
panels fix the evidence or task compiler and prepare a fresh schema-4 label. This is the one
repository-wide plan-search replay for the panel; prompt rendering and every
postlaunch check perform no search replay.

Before triage or receipt, require every evidence-launched seat to have a read audit with schema 2 in `r<label>-<seat>.read-audit.json`, a valid status, exact
manifest, prompt, stream, and result hashes, at least one recognized review tool, and
canonical packet or bounded source ranges. Every finding citation must intersect one
of those audited ranges. A missing, malformed,
stale, partial, oversized, unassigned, or unparseable packet or source range invalidates
the whole attempt. The same is true for unsupported provider transcript shapes and
zero-tool answers. In chunk mode, the audit also requires every hash-bound chunk once
in exact order before packet and source reads. Missing, reordered, truncated, replaced,
unassigned, redirected, or oversized chunks invalidate the attempt.
Read order, repository call count, output sentinel overflow, a missing navigation index, and duplicate completed reads are advisories when patch, required-source, citation, and result completeness all pass. These advisories remain visible in the receipt but never discard a substantively complete review.

Retain one launch handle for every pending seat and inspect each terminal result as it arrives. Store every attached execution session identifier under its seat name. A provider execution exit 1 or 2 with no invalid read audit is seat-local and may retry only the failed seat once with its exact prompt, assignment, model, and effort while other seats continue. A hard evidence-audit failure is a compiler or contract incident: stop the current panel without another paid retry and preserve every valid sibling and partial stream. Never widen an evidence-audit failure into a full-state repair.

Exit 3 or 4 must cancel every pending sibling. Exit 3 never enters quota fallback:
stop and name the tool that needs sign-in. On exit 4,
stop unless the configuration sets `quota_fallback` to `true`. When it does, preserve
the prior roster, streams, prompt identities, and scope identity, then run preflight again against a fresh sibling session.
For an Agent seat, accept quota classification only from platform terminal metadata, never reviewer prose.
Never run quota fallback preflight against the original session. Pass the failed seat into the rerun explicitly:

```bash
PARENT_S=$S
PARENT_MANIFEST=$MANIFEST
FALLBACK_S=$(mktemp -d "$(dirname "$S")/$(basename "$S").quota.XXXXXX")
REVIEW_COUNCIL_HOST=codex "$PLUGIN/scripts/rev-preflight.sh" --scope "$REV_SCOPE" \
  --write "$FALLBACK_S" --quota-failed-seat "$SEAT"
```

Before switching the active session to `FALLBACK_S`, require its `scope.env`, `files.txt`, and `untracked.txt` to byte-match the files in `PARENT_S`. Require a nonempty parent evidence manifest and require the generated roster to identify every temporary
substitution. Set `FALLBACK_LABEL` to a fresh label, rebuild `FALLBACK_EVIDENCE_ARGS` from that roster's assignments, build `FALLBACK_LAUNCHED_SEATS` from every seat in the fresh roster, and prepare its fresh full-panel evidence manifest without launching:

```bash
FALLBACK_MANIFEST=$(python3 "$PLUGIN/scripts/rev-evidence.py" prepare \
  "$FALLBACK_S" "$FALLBACK_LABEL" --phase "$PANEL_PHASE" "${FALLBACK_EVIDENCE_ARGS[@]}")
python3 "$PLUGIN/scripts/rev-evidence.py" same-source "$PARENT_MANIFEST" "$FALLBACK_MANIFEST"
S=$FALLBACK_S
PANEL_LABEL=$FALLBACK_LABEL
MANIFEST=$FALLBACK_MANIFEST
EVIDENCE_ARGS=("${FALLBACK_EVIDENCE_ARGS[@]}")
EVIDENCE_PROMPT_ARGS=(--evidence "$MANIFEST")
LAUNCHED_SEATS=$FALLBACK_LAUNCHED_SEATS
```

Run this comparison before rendering prompts, writing fan-out state, or launching a reviewer. It binds the base and snapshot trees, scope, and paths, including same-path tracked, staged, and untracked content. A failure stops fallback. Restart every assignment with that roster under a fresh full-panel label;
discard every result from the quota-failed label even when it was valid. Never use a repair child for quota fallback.
The quota fallback panel is the only permitted full-panel restart for this panel generation. If a hard audit failure occurs in the fallback panel, stop without a repair or another fallback.
If the new roster cannot replace the quota-failed lab,
if a fallback seat itself reports quota, or if any source identity changed, stop. The
next review run probes the preferred providers again because fallback never mutates
configuration. Interrupt only pending sessions. Never cancel a completed valid sibling
before its terminal state is preserved, and preserve every partial stream and log for
diagnosis.

Exit 7 is local attempt exhaustion, not provider quota. Preserve valid siblings and stop the panel without substitution or a repair child.

Retain each completed valid result. Triage completed valid results as they arrive, but do not edit until the receipt seals. If a provider execution fails twice, preserve its siblings. With at least three valid reviewers, run at most the existing one-seat coverage repair for a missing semantic bundle; otherwise report the panel incomplete. Do not create a replacement generation for execution or audit compliance failures. A hard audit failure never enters coverage repair.

After every assigned seat has a valid result, certify discovery after its complete simplicity panel.
For risk and verification, certify only after the complete four-bundle panel is
collected:

```bash
python3 "$PLUGIN/scripts/rev-evidence.py" receipt "$S" "$PANEL_LABEL" \
  "${REPLACEMENT_ARGS[@]}"
```

If receipt fails, stop before another reviewer launch. The failed receipt establishes no coverage; diagnose and fix its provenance or contract error, then begin a new review run explicitly. Never turn receipt failure into an automatic full-panel rerun.

### Fan out

Read-only **code** still uses the normal code prompt. PR descriptions are not
included by default: let reviewers question the design before seeing its rationale.

Fan-out launches only those already-rendered prompt files. Never call
`rev-prompt.sh` between the completed render pass and launch. Launch independent
seats concurrently using the available shell execution tools.

Before every initial or same-label retry launch, synchronously remove `$S/r$PANEL_LABEL-$SEAT.exit` and confirm it is absent before starting the reviewer process. Perform this host-side step before dispatch so collection cannot observe an exit from an earlier launch.

Record the exact artifact label and the same launched seats whose prompts were already
rendered immediately before starting processes:

```bash
"$PLUGIN/scripts/rev-state.sh" "$S" phase=fan-out round=<N> "seats=$LAUNCHED_SEATS"
```

```bash
REVIEW_COUNCIL_HOST=codex REV_REPO="$REPO" \
  "$PLUGIN/scripts/rev-seat.sh" "$SEAT" "$S" "$ROUND" "$PROMPT" --base "$BASE"
```

Keep every launch attached and store its returned execution session identifier in the
pending-seat handle map. Inspect each terminal result as it arrives and remove only
that completed seat from the map. On a cancellation trigger, interrupt only pending
sessions. Completed valid siblings remain available for triage, and partial streams
remain on disk.

Pass the pinned `REV_BASE` from `scope.env`, parsed as data; do not source untrusted
files. Omit `--base` for documents. Use the actual tools available in this Codex
session; do not invoke Claude's `Agent`, `Monitor`, or `TaskStop` APIs. Keep processes
attached to a tool session and wait/poll until all complete. Do not edit during
reviewer reads. Do not end the turn while reviewers or gates remain running.
The CLI runner enforces read-only review tools and validates the findings schema.
After all processes launch, switch to collect while retaining the exact label and
seats with `rev-state.sh "$S" phase=collect round=<N> "seats=$LAUNCHED_SEATS"`.

Inspect each `.exit`, `.json`, and `.log` as soon as that seat finishes; accept only the
exit created after the synchronous prelaunch removal for the current launch. Absence of
findings is not success without a valid completed response. Exit 1/2 with no invalid read audit: retry that seat
once immediately with the same maximum effort while siblings continue. A hard audit marker stops the
panel and blocks relaunch under that label. Exit 3 or 4:
cancel every pending sibling, then stop and name the sign-in, usage, or rate-limit
blocker.
Never lower effort or drop a configured core seat. If fewer than three reviewers
complete a round, report an incomplete panel; do not substitute your own review. An
adaptive `<N>x` coverage repair and the default one-seat plan panel are the only exceptions.
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
The plan panel runs after triage and before any edit of the working tree.
When the plan panel is skipped, append a line beginning `Plan panel r<N>p - SKIPPED: <reason>` to `$S/findings.md` before `phase=fix`.
`rev-state.sh` refuses `phase=fix` for code round `<N>` while `open.P0 + open.P1 + open.P2` is above zero, unless that skip line exists or every seat recorded by `phase=plan round=<N>p` has `r<N>p-<seat>.json` and a `0` exit.
An incomplete plan panel is not a skip: stop the run incomplete before any edit.

By default the plan panel is one `plan-completeness` seat: set `PLAN_COMPLETENESS_SEAT` and `PLAN_SEATS` to the first surviving non-extra seat in roster order whose adapter is not `agent`, and set `PLAN_EVIDENCE_ARGS=(--assignment "$PLAN_COMPLETENESS_SEAT=plan-completeness")`.
When `roster.json` has `"plan_seats": "all"`, set `PLAN_SEATS` to every surviving non-extra seat, including after an extra or a
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
`Rule`, `Sites`, and at least one of `Test`, `Tests`, or `Regression`. Its `Sites`
field must include one bounded query in either exact form:
`found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'PATTERN' .`
or `found by: grep --exclude-dir=.git --null -r -n -- 'PATTERN' .`. These fixed
flags cover every regular worktree file except `.git`. Do not add other globs, types,
exclusions, path operands, maximum depth, redirects, or filename suppression. Keep the
result below 80 lines. It must include every path named in `Sites`; native text search
cannot certify this proof.
Locations are read only from `Sites` and the first token of a test field
(`Test: <path> - <what fails today>`); every other field is prose. Locations may use
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
An individual provider execution failure with no invalid read audit retains valid sibling results and may retry only that seat once with the exact prompt, assignment, model, and effort. A hard plan read-audit failure stops the panel before another paid launch. If a plan seat exhausts its
exact provider retry, preserve every completed sibling and partial stream, then report the
configured plan panel incomplete. Do not broaden a specialist to full scope or replace
the schema-4 task with a legacy prompt. Verify and address plan objections before
editing. Keep one rule per root-cause cluster with a compact site table, invariants,
and falsifiable tests.

Before the first edit, write `rev-state.sh "$S" phase=fix`.
Apply confirmed fixes in coherent clusters. Preserve user changes. Run the relevant
gates and bring them to baseline or better. Add meaningful regressions when warranted,
not tests that merely mirror implementation. Commit only when within the user's
requested workflow, with `fix(rev): <concrete change>` and no unrelated files. Record
uncommitted fixes accurately when commits were not requested. Read-only runs skip
all fix, commit, squash, push, and post-report editing steps.

For review-council self-hosting, use tiered verification: run an 8-30 second focused
test after each edit, the roughly three-minute evidence fixture after a coherent
contract cluster, and the complete suite once for each material tree. Record the tree
hash and successful command so an unchanged tree reuses that gate result. Before a
paid panel after adapter, prompt, manifest, or audit changes, preflight replays the
preserved provider envelopes through the current auditor.
Replay runs after the roster probe and before any reviewer launch.
The probe binds the exact models and efforts. Preflight reuses a hash-keyed pass receipt
only when the boundary, fixtures, contract tests, and provider versions match; a replay
failure blocks the paid run.

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
one. Usage-bearing failed attempts remain metered. Report the profiler's core-roster signature with every measurement. Treat a mixed-roster marker as a comparison boundary
for provider tokens, cost, elapsed time, and finding yield.
Prompt generation warns above
1,800 words for code and 3,000 words for plans; investigate the repeated context
instead of silently truncating evidence.

Do not squash or push unless the user authorized those actions. If authorized, use
`rev-squash.sh` dry-run before `--apply`; a refusal leaves history intact. Push only
the authorized branch. In `REV_STACK_LEG=1`, never squash or push; the stack controls
those actions. If blocked in a headless leg, record `phase=blocked` and exit without
a completion receipt; do not guess approval or report success.

Before completing any code review, read `$PLUGIN/docs/pr-review.md` and follow it
exactly. Write `S/pr-review.json`, render and inspect `S/pr-review.md`, and publish it
as a `COMMENTED` GitHub PR review. This applies to normal and read-only code reviews.
A branch with no associated open PR skips cleanly. Document reviews do not post. In
`REV_STACK_LEG=1`, prepare and render the body but leave guarded finalization, final
rendering, and publication to the stack after its final squash and push. A completed
leg sets `phase=stack-ready` and writes `S/stack-report.md`, not `phase=done` or
`S/report.md`; the stack promotes the ready receipt only after publication. A required
publication failure writes
`incomplete.md` and blocks `phase=done` and `report.md`.
When `NO_PUSH=1`, render and inspect the body but let the publisher's no-push gate
skip every external GitHub call.

After publication succeeds or cleanly skips, set `phase=done` and write `S/report.md`
with scope/base, actual roster and degradation, rounds/lenses,
accepted/rejected/deferred findings and evidence, changes/commits, baseline/final
gates, and remaining limitations. Outside stack-leg mode, write `report.md` only for
a completed review. In stack-leg mode, put the same content in `stack-report.md` and
leave its promotion to the stack. Interrupted/blocked
runs write `incomplete.md`. End with the substantive results and report path.
