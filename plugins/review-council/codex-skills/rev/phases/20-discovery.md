## Run the adaptive panels

Read the roster and use every non-extra seat. Adaptive default panels use core seats
and omit extras. Explicit numeric round plans may include extras in their configured
rounds. Run these panels in order:

1. **Simplicity discovery:** every core seat gets `simplicity`. Keep all four seats;
   held-out evaluation shows the union finds material simplifications that one seat
   misses. When `$S/panel-request.json` exists, keep every core seat that roster froze,
   not the default Sol, Opus, and Sonnet mix.
2. **Risk discovery:** only for a large or high-risk change. Deal the four bundles
   below across the full panel.
3. **Full red team:** exactly once for a large, high-risk, user-marked-important, or
   explicitly adversarial adaptive review. Run it before planning under the promoted
   adversarial coverage contract below, rendered as a combined verification panel.
4. **Plan:** apply the plan gate below.
5. **Verification:** reuse the combined panel only when the coverage check below
   proves it remains current after triage; otherwise deal the four bundles across one full panel over the latest
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

One four-bundle verification panel reviews the latest material state: the current
combined panel when no fix follows, a separate panel after simplicity-only discovery,
or a fresh panel after fixes. Do not certify an adaptive panel until every assignment has a valid result, its own or its one replacement's. A certified risk or verification panel therefore has all four bundles. An assignment without a valid result gets at most one replacement on another eligible seat: after its exact retry for an execution failure, immediately for a hard audit failure or an exit-0 `INCOMPLETE PROOF` result. A replacement is one seat, so the three-reviewer minimum does not apply.

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

At a phase handoff or resume, run `python3 "$PLUGIN/scripts/rev-context.py" "$S"`
for the current state, exact seat identities, outstanding results, and artifact references.
Read the linked evidence when deciding a finding or coverage obligation. The briefing
does not evaluate certification and never replaces collection or receipt validation.

### Panel setup

Read the roster and rebuild the launched seat list before every panel. Set
`LAUNCHED_SEATS` from every surviving non-extra seat plus only extras configured for
this numeric round. Do not append seats from the prior panel. Assign every lens and
risk bundle before preparing or rendering prompts. Numeric extras keep their fixed
lenses.

### Adaptive scope preparation

Scope optimization never changes the preflight roster, its models, efforts, or
seat count. Use every configured core seat, including Sol, Luna, Opus, and Sonnet
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
For this panel, set `PANEL_PHASE=verification` and reuse the existing four canonical bundle assignments. Render this phase from the outset so every prompt also contains sibling-site completeness; keep the full cumulative owner and all composed adversarial emphases. The panel has these four distinct composed adversarial assignments, in bundle order:

1. correctness and boundaries plus attacker behavior and trust boundaries;
2. security, state, and API plus rollback and recovery;
3. concurrency, resources, and performance plus duplication and exhaustion;
4. tests, observability, and regression plus consumer compatibility and integration.

Map each entry above to its canonical bundle. When a core seat carries multiple canonical bundles, concatenate the matching adversarial emphases into that seat's single prompt emphasis in canonical bundle order.
For surplus seats, cycle the mapped adversarial emphasis with the canonical bundle, so
each repeated bundle repeats its matching emphasis. Keep the result in the existing
seat prompt; neither case changes the canonical topology or adds a provider call.

The full panel joins the same initial finding clusters and does not grant another correction cycle.
After triage, the combined panel may serve final verification only when no fix follows
and its latest sealed receipt remains current. Run `current-coverage "$S"` through
`rev-evidence.py`; require JSON `eligible: true` before omitting the separate panel.
Record the returned receipt, hash, snapshot, and exact selected generations in the
ledger. Never relabel a risk receipt. Missing, stale, or unenforced coverage keeps the separate verification obligation.
Invalid or incomplete panels follow the existing failure and replacement rules;
this scheduling check never authorizes an automatic full-panel rerun. Any fix or
material source, scope, roster, model, effort, or repository-instruction change after
the combined panel blocks reuse. Simplicity-only and explicit numeric schedules are unchanged.

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
Explicit numeric panels use the full cumulative patch for every launched seat.
Without a `cursor-sdk` row, keep the legacy path: omit evidence preparation and
leave `MANIFEST` and `PANEL_PHASE` empty. With an SDK row, use the explicit numeric
evidence protocol below; retain the numbered schedule, lenses, final composed
emphases and actual launched set. Numeric evidence is never adaptive verification.
Scheduled opaque extras such as `codex-review` refuse before launch with
`cursor-sdk numeric extra mode is unsupported`; they cannot be silently dropped.
`extras:false` removes them explicitly. A dormant extra does not block its other
rounds. SDK document panels are unsupported and refuse before provider discovery.
Document panels read every supplied document in full,
omit evidence preparation, and render each seat with the per-seat form and
`--read-only "$S/docs.txt"`.

Evidence mode depends on each launched row's adapter, never on the host.
Code preparation RUNS with an Agent seat and records it as unenforced rather than
skipping the panel. Claude Code plugin subagents ignore
hook frontmatter, so an Agent seat cannot provide the enforced tool transcript required
by evidence mode, but skipping preparation for the whole panel meant that wherever Claude
rows resolve to `agent`, no code panel reached evidence mode at all. The manifest lists
those seats in `unenforced_seats`, validation skips only their read audit, hashes their
result, exit and prompt into the receipt, and the receipt row carries `enforced: false`.
Be exact about what that leaves proven: the prompt is bound to this manifest, but the
result, exit and transcript are only hashed into the receipt, never compared to this
panel, so a result or transcript filed under the wrong seat or round is recorded rather
than detected. The orchestrator writes each Agent seat's result by hand, so a misfiling
is the realistic failure here, not an attacker.
Report such a panel as partially unenforced; never describe it as certified.
With `REV_UNENFORCED_AUDIT=1`, an unenforced seat's read audit is produced anyway, from
the transcript you copied, and recorded in `unenforced_audits` with its would-have-passed
verdict; nothing gates on it, because whether an Agent transcript clears the gate is
unmeasured and gating on an unmeasured pass rate would trade one blanket refusal for
another. Report that verdict; never read it as certification. Without that flag no audit
runs and each row records `would_pass: false` with the reason
`advisory read audit is off`; keep one setting for the whole session, because the receipt
records the verdict.
Rows on adapters `codex`, `gemini`, and `claude` launch through `rev-seat.sh` and keep
evidence mode.
`claude_adapter` decides whether a Claude Code host seats Claude rows on `agent`; a Codex host always seats them on `claude`.
Plan preparation RUNS with an Agent seat and records it as unenforced rather than
refusing. An Agent seat cannot supply the enforced read transcript, so a plan panel
containing one is never certified - but the value of the gate is its schema-4
structure (per-cluster closure obligations, sibling-site search proofs, source
shards), and that structure works on an Agent seat. Refusing meant a Claude-only
Agent roster got no fix-design gate at all, which is strictly worse. The manifest
lists those seats in `unenforced_seats`, validation skips only their read audit, hashes
their result, exit and prompt into the receipt, and the receipt row carries
`enforced: false`. Be exact about what that leaves proven: the prompt is bound to this
manifest, but the result, exit and transcript are only hashed into the receipt, never
compared to this panel, so a result or transcript filed under the wrong seat or round is
recorded rather than detected. The orchestrator writes each Agent seat's result by hand,
so a misfiling is the realistic failure here, not an attacker.
Report such a panel as an unenforced plan panel; never describe it as certified.
Do not replace the schema-4 plan with a legacy full-scope task.

Before evidence-backed fan-out, set `PANEL_LABEL` to the artifact label and `PANEL_PHASE` to
`discovery`, `risk`, `verification`, `repair`, or SDK `numeric`. Build `EVIDENCE_ARGS` from the exact
launched seats: discovery passes `--full-seat` for the first core seat; risk and
verification pass one `--assignment "$SEAT=$BUNDLE_OR_COMPOSITE"` per seat plus
`--full-seat` for the first regression-bundle seat; a replacement passes its one assignment and `--parent-assignment` (see the replacement rule below).

Before numeric SDK preparation, finish every scheduled lens and composed emphasis,
then write the exact three-column panel TSV described below in `LAUNCHED_SEATS`
order. Set `PANEL_PHASE=numeric`, keep `PANEL_LABEL` equal to the numbered round,
and bind the requested minimum already recorded in `state.json`:

```bash
NUMERIC_MIN_ROUNDS=$(python3 - "$S/state.json" <<'PYMIN'
import json, sys
value = json.load(open(sys.argv[1], encoding='utf-8'))['min_rounds']
if type(value) is not int or value < 1:
    raise SystemExit('numeric minimum must be the explicit positive request')
print(value)
PYMIN
) || exit 1
EVIDENCE_ARGS=(--numeric-round "$PANEL_LABEL" --numeric-min-rounds "$NUMERIC_MIN_ROUNDS" --numeric-panel "$S/r$PANEL_LABEL-panel.tsv")
```

All numeric SDK assignments receive identical full cumulative patch bytes, including
mechanical changes, under the exact legacy lens and final emphasis. The manifest
freezes the round, minimum and ordered TSV identity. Its receipt proves this numeric
panel only; it never updates adaptive `coverage-head.json`, supplies an adaptive
predecessor or makes `current-coverage` eligible. A numeric-parent repair inherits
the parent's full scope, round/minimum binding, lens and exact emphasis and renders
with `COVERED_PHASE=numeric`. Never substitute an adaptive covered phase.

Then prepare once:

```bash
MANIFEST=
if CANDIDATE=$(REV_PATCH_CHUNKS=${REV_PATCH_CHUNKS:-auto} REV_SOURCE_CONTEXT=${REV_SOURCE_CONTEXT:-1} python3 "$PLUGIN/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" --phase "$PANEL_PHASE" "${EVIDENCE_ARGS[@]}"); then
  case "$CANDIDATE" in
    "$S/r$PANEL_LABEL-evidence.manifest.json") [ -r "$CANDIDATE" ] && MANIFEST=$CANDIDATE ;;
  esac
fi
if [ -z "$MANIFEST" ] && { [ "$PANEL_PHASE" = numeric ] || [ "${COVERED_PHASE:-}" = numeric ]; }; then
  echo 'numeric evidence preparation failed; preserve diagnostics and stop incomplete' >&2
  exit 1
fi
```

`REV_PATCH_CHUNKS=auto` selects chunks when they save proof reads or are required to
fit the compiled provider capacity. `REV_PATCH_CHUNKS=1` forces chunks when the patch
is representable, while `REV_PATCH_CHUNKS=0` requests window mode and fails preparation
when that mode cannot fit. `REV_SOURCE_CONTEXT=1` enables literal source packets and
required-source segments. Baseline measurements may set both paths explicitly, but
must otherwise use the same snapshot, roster, models, efforts, bundles, and host steps.
Both runs keep the same component assignments and patch narrowing.

Build the optional flags once. SDK numeric reuses its already bound TSV byte for byte.
For other modes, write one `<seat>`, tab, `<lens>`, tab, `<emphasis>`
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
prints their paths in order, and publishes none when any seat fails. Render a single `<N>x` replacement seat with the per-seat form
`"$PLUGIN/scripts/rev-prompt.sh" "$S" "$PANEL_LABEL" "$SEAT" "$LENS" "$EMPHASIS" --phase "$COVERED_PHASE" "${EVIDENCE_PROMPT_ARGS[@]}"`,
where `COVERED_PHASE` is the phase of the panel it replaces into (`discovery`, `risk`, `verification`, or `numeric` for a bound numeric parent).
An exact seat retry reuses its already-rendered prompt.

If numeric SDK preparation or rendering fails, or its numeric-parent repair fails
to render, stop incomplete and preserve the diagnostics. Never clear its manifest,
rerender it as legacy, narrow its coverage or launch a partial panel.
For other modes, if any evidence prompt render fails, discard the narrowed panel.
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
panels fix the evidence or task compiler and prepare a fresh schema-4 label. A capacity refusal or a prepare timeout is not repeated unchanged and follows the plan-phase recovery. This is the one
repository-wide plan-search replay for the panel; prompt rendering and every
postlaunch check perform no search replay.

Before triage or receipt, require every evidence-launched seat to have a read audit with schema 2 in `r<label>-<seat>.read-audit.json`, a valid status, exact
manifest, prompt, stream, and result hashes, at least one recognized review tool, and
canonical packet or bounded source ranges. Every finding citation must intersect one
of those audited ranges. A bounded `git show <snapshot tree>:<path>` read counts only when its bytes match the frozen snapshot blob; a read of the base or any other revision is context, never a range or a citation. Shell comments are ignored. A missing, malformed,
stale, partial, or unassigned packet or source range invalidates
the whole attempt. The same is true for unsupported provider transcript shapes and
zero-tool answers. In chunk mode, the audit also requires every hash-bound chunk once
in exact order before packet and source reads. Missing, reordered, truncated, replaced,
unassigned, or redirected chunks invalidate the attempt.
A seat's evidence read audit with status `invalid` is a hard evidence-audit failure. A valid audit may carry advisories: these never discard the review, stay visible in the receipt, and never earn credit. A call that raises a call-local violation, and every proof call in a turn that overflows the turn ceiling, proves no range, no patch chunk, packet or segment, and no citation. Pacing counts and whole-transcript counts revoke nothing.

Retain one launch handle for every pending seat and inspect each terminal result as it arrives. Store every attached execution session identifier under its seat name. A provider execution exit 1 or 2 with no invalid read audit is seat-local and may retry only the failed seat once with its exact prompt, assignment, model, and effort while other seats continue, even if it left an `INCOMPLETE PROOF` result. A hard evidence-audit failure ends only that seat's assignment: never relaunch that seat under that label (`rev-attempt.py` refuses it), keep every sibling running, and preserve every valid sibling and partial stream. A launch that exits 0 with a result whose `summary` begins `INCOMPLETE PROOF` ends its assignment the same way: it is never a valid result, and an exact retry with the same prompt and budget would repeat the same exhaustion. An assignment without a valid result gets at most one replacement on another eligible seat: after its exact retry for an execution failure, immediately for a hard audit failure or an exit-0 `INCOMPLETE PROOF` result.

Exit 3 or 4 must cancel that provider's pending siblings. Exit 3 never enters quota fallback:
retry the assignment on the next higher enforced seat, and if that fails finish the lens yourself. On exit 4,
when the configuration sets `quota_fallback` to `true`, preserve
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

Before switching the active session to `FALLBACK_S`, run `"$PLUGIN/scripts/rev-state.sh" "$FALLBACK_S" inherit-breaker "$PARENT_S"` so the review-origin window carries over, then require its `scope.env`, `files.txt`, and `untracked.txt` to byte-match the files in `PARENT_S`. Require a nonempty parent evidence manifest and require the generated roster to identify every temporary
substitution. For SDK numeric recovery, keep the same numbered `FALLBACK_LABEL` in the fresh session, rebuild its TSV from the fresh actual roster and final emphases, and set `FALLBACK_EVIDENCE_ARGS=(--numeric-round "$FALLBACK_LABEL" --numeric-min-rounds "$NUMERIC_MIN_ROUNDS" --numeric-panel "$FALLBACK_S/r$FALLBACK_LABEL-panel.tsv")`; loss of the required SDK identity stops recovery. For other phases, set `FALLBACK_LABEL` to a fresh label, rebuild `FALLBACK_EVIDENCE_ARGS` from that roster's assignments, build `FALLBACK_LAUNCHED_SEATS` from every seat in the fresh roster, and prepare its fresh full-panel evidence manifest without launching:

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
The quota fallback panel is the only permitted full-panel restart for this panel generation. An exit-4 quota substitution never uses a replacement child; a later hard audit inside the fallback panel follows the replacement rule.
If the new roster cannot replace the quota-failed lab,
if a fallback seat itself reports quota, or if any source identity changed, retry the assignment on the next higher enforced seat, and if that fails finish the lens yourself. The
next review run probes the preferred providers again because fallback never mutates
configuration. Interrupt only pending sessions. Never cancel a completed valid sibling
before its terminal state is preserved, and preserve every partial stream and log for
diagnosis.

Exit 7 is local attempt exhaustion, not provider quota. Preserve valid siblings and finish the missing assignment yourself without another repair child.

Retain each completed valid result; a result whose `summary` begins `INCOMPLETE PROOF` is never one. Triage completed valid results as they arrive, but do not edit until the receipt seals. An assignment without a valid result gets at most one replacement on another eligible seat: after its exact retry for an execution failure, immediately for a hard audit failure or an exit-0 `INCOMPLETE PROOF` result. The replacement executor is the `seat` printed by `python3 "$PLUGIN/scripts/rev-workhorse.py" escalate --session "$S" --seat "$FAILED_SEAT"`. That is the next enforced family on the normal chain (Cursor Grok only when this host is Cursor, then Luna, Sonnet, Sol, Opus). A non-zero exit means the chain is exhausted: finish that assignment yourself in the spirit of its lens. When the JSON says `"existing": false`, repair preparation reads `$S/escalation.json`. The failed assignment needs a recorded terminal failure: its archived `r<N>-<seat>.audit-invalid.json`, its exit-0 `INCOMPLETE PROOF` result, or an exact retry that also exited 1 or 2. Prepare the child with `"$PLUGIN/scripts/rev-evidence.py" prepare "$S" "<N>x" --phase repair --assignment "$EXECUTOR=$PARENT_BUNDLE" --parent-assignment "<N>:$FAILED_SEAT"`, which refuses an ineligible executor, a parent with no recorded terminal failure, and a second replacement in the panel. Render it with the per-seat form above, record `"$PLUGIN/scripts/rev-state.sh" "$S" phase=repair round=<N>x "seats=[\"$EXECUTOR\"]"`, launch it, and seal with `REPLACEMENT_ARGS=(--replacement "$FAILED_SEAT=<N>x")`. Discovery uses the same rule, and the child has full scope. With no eligible seat, a second failed assignment in the panel, or a failed replacement, the panel is still incomplete: finish the missing assignment yourself in the spirit of its lens, in this same session.

After every assigned seat has a valid result, seal an SDK numeric panel only after
its exact complete launched set has valid full-scope generations, including its
one replacement when applicable. Its receipt stays numeric and preserves any
existing adaptive coverage head. Certify discovery after its complete simplicity panel.
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
findings is not success without a valid completed response, and a result whose `summary` begins `INCOMPLETE PROOF` is never one.
Exit 1/2 with no invalid read audit: retry that seat
once immediately with the same receipted effort while siblings continue, even if it left an `INCOMPLETE PROOF` result, unless `rev-attempt.py` refused the launch for one. A hard audit failure, exit 0 with an `INCOMPLETE PROOF` result, or a relaunch `rev-attempt.py` refused for one: replace now, and never relaunch that seat under that label. An assignment without a valid result gets at most one replacement on another eligible seat: after its exact retry for an execution failure, immediately for a hard audit failure or an exit-0 `INCOMPLETE PROOF` result. Exit 3 or 4:
cancel that provider's pending siblings, retry the assignment on the next higher enforced seat, and if that fails finish the lens yourself. Name the blocker in the ledger.
Never lower effort or drop a configured core seat. If fewer than three reviewers
complete a round, retry each missing assignment on the next higher enforced seat. If that fails, cover the missing lens yourself, record it as orchestrator coverage, and continue. Do not describe that coverage as a certified seat. An `<N>x` replacement and the default one-seat plan panel are the only exceptions.
Record reduced coverage and failed extras; never label an incomplete run clean.
