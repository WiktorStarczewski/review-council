## The loop - one round

`fan out → collect → triage → plan → fix → verify → commit → record`

### Panel setup

Read the roster for this panel:

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1]));
print('\n'.join('%s\t%s\t%s' % (s['seat'], s['adapter'], ('extra round %s' % s.get('round')) if s.get('extra') else 'base') for s in d['seats']))" $S/roster.json
```

Rebuild the launched seat list before every panel. Set `LAUNCHED_SEATS` from every
surviving non-extra seat plus only extras configured for this numeric round. Do not
append seats from the prior panel. Assign every lens and risk bundle before preparing
or rendering prompts. Numeric extras keep their fixed lenses.

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

Evidence preparation applies to adaptive code panels and accepted-fix plan panels,
whether or not their roster contains a `cursor-sdk` row.
Explicit numeric panels use the full cumulative patch for every launched seat.
Only explicit numeric panels without a `cursor-sdk` row keep the legacy path: omit
evidence preparation and leave `MANIFEST`
and `PANEL_PHASE` empty. With an SDK row, use the explicit numeric evidence protocol
below; retain the numbered schedule, lenses, final composed emphases and actual
launched set. Numeric evidence is never adaptive verification.
Scheduled opaque extras such as `codex-review` refuse before launch with
`cursor-sdk numeric extra mode is unsupported`; they cannot be silently dropped.
`extras:false` removes them explicitly. A dormant extra does not block its other
rounds. SDK document panels are unsupported and refuse before provider discovery.
Document panels read every supplied document in full and use their legacy rendering flow below.

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
if CANDIDATE=$(REV_PATCH_CHUNKS=${REV_PATCH_CHUNKS:-auto} REV_SOURCE_CONTEXT=${REV_SOURCE_CONTEXT:-1} python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" --phase "$PANEL_PHASE" "${EVIDENCE_ARGS[@]}"); then
  case "$CANDIDATE" in
    "$S/r$PANEL_LABEL-evidence.manifest.json") [ -r "$CANDIDATE" ] && MANIFEST=$CANDIDATE ;;
  esac
fi
if [ -z "$MANIFEST" ] && { [ "$PANEL_PHASE" = numeric ] || [ "${COVERED_PHASE:-}" = numeric ]; }; then
  echo 'numeric evidence preparation failed; preserve diagnostics and stop incomplete' >&2
  exit 1
fi
```

A code proof-budget refusal, proof reads exceed repository capacity, is not a legacy rerender and not a provider-seat replacement: stop before rendering, read `prepare-diagnostic-<label>.json`, and review each partitions entry as its own path scope.

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
same flag arrays for the entire panel. Append the usual `--vacuity` or `--pr` flag only
when applicable.

```bash
EVIDENCE_PROMPT_ARGS=()
[ -n "$MANIFEST" ] && EVIDENCE_PROMPT_ARGS=(--evidence "$MANIFEST")
PHASE_PROMPT_ARGS=()
[ -n "$PANEL_PHASE" ] && PHASE_PROMPT_ARGS=(--phase "$PANEL_PHASE")
${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh "$S" "$PANEL_LABEL" --panel "$S/r$PANEL_LABEL-panel.tsv" "${PHASE_PROMPT_ARGS[@]}" "${EVIDENCE_PROMPT_ARGS[@]}"
```

`--panel` loads the evidence manifest once, writes every `r<label>-<seat>.prompt.md`,
prints their paths in order, and publishes none when any seat fails. Render each replacement seat with a unique child label, using the per-seat form
`${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh "$S" "$PANEL_LABEL" "$SEAT" "$LENS" "$EMPHASIS" --phase "$COVERED_PHASE" "${EVIDENCE_PROMPT_ARGS[@]}"`,
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
narrowed attempt. Code panels use the all-legacy rerender path above, except a proof reads exceed repository capacity refusal, which stops before that rerender; schema-4 plan
panels fix the evidence or task compiler and prepare a fresh schema-4 label. A capacity refusal or a prepare timeout is not repeated unchanged and follows the plan-phase recovery. This is the one
repository-wide plan-search replay for the panel; prompt rendering and every
postlaunch check perform no search replay.

Before triage or receipt, require every evidence-launched seat to have a read audit with schema 2 in `r<label>-<seat>.read-audit.json`, a valid status, exact
manifest, prompt, stream, and result hashes, at least one recognized review tool, and
canonical packet or bounded source ranges. Every finding citation must intersect one
of those audited ranges. A bounded `git show <snapshot tree>:<path>` read counts only when its bytes match the frozen snapshot blob; a read of the base or any other revision is context, never a range or a citation. Shell comments are ignored. Agent-adapter findings must intersect a range from that
seat's assigned packet, and the audit must prove that every assigned shard was opened
in full. The enforced read hooks are an earlier guard, not post-run evidence. A missing, malformed,
stale, partial, or unassigned packet or source range invalidates
the whole attempt. The same is true for unsupported provider transcript shapes and
zero-tool answers. In chunk mode, the audit also requires every hash-bound chunk once
in exact order before packet and source reads. Missing, reordered, truncated, replaced,
unassigned, or redirected chunks invalidate the attempt.
A seat's evidence read audit with status `invalid` is a hard evidence-audit failure. A valid audit may carry advisories: these never discard the review, stay visible in the receipt, and never earn credit. A call that raises a call-local violation, and every proof call in a turn that overflows the turn ceiling, proves no range, no patch chunk, packet or segment, and no citation. Pacing counts and whole-transcript counts revoke nothing.

Retain one launch handle for every pending seat and inspect each terminal result as it arrives. Store every Bash task ID and Agent task ID under its seat name. A provider execution exit 1 or 2 with no invalid read audit is seat-local and may retry only the failed seat once with its exact prompt, assignment, model, and effort while other seats continue, even if it left an `INCOMPLETE PROOF` result. A hard evidence-audit failure ends only that seat's assignment: never relaunch that seat under that label (`rev-attempt.py` refuses it), keep every sibling running, and preserve every valid sibling and partial stream. A launch that exits 0 with a result whose `summary` begins `INCOMPLETE PROOF` ends its assignment the same way: it is never a valid result, and an exact retry with the same prompt and budget would repeat the same exhaustion. After the exact retry for an execution failure, or immediately after a hard audit failure or exit-0 `INCOMPLETE PROOF` result, continue that assignment through the configured eligible replacement chain until valid proof exists or no eligible seat remains. There is no panel-wide cap either; every attempt uses a unique child label and binds directly to its original failed parent assignment.

Exit 3 or 4 must cancel that provider's pending siblings. Exit 3 never enters quota fallback:
retry through `rev-workhorse.py escalate`, which honors a matching per-review override and otherwise selects the next higher enforced seat; if that fails, finish the lens yourself. On exit 4,
when the configuration sets `quota_fallback` to `true`, preserve
the prior roster, streams, prompt identities, and scope identity, then run preflight again against a fresh sibling session.
For an Agent seat, accept quota classification only from platform terminal metadata, never reviewer prose.
Never run quota fallback preflight against the original session. Pass the failed seat into the rerun explicitly:

```bash
PARENT_S=$S
PARENT_MANIFEST=$MANIFEST
FALLBACK_S=$(mktemp -d "$(dirname "$S")/$(basename "$S").quota.XXXXXX")
${CLAUDE_PLUGIN_ROOT}/scripts/rev-preflight.sh --scope "$REV_SCOPE" --write "$FALLBACK_S" \
  --quota-failed-seat "$SEAT"
```

Before switching the active session to `FALLBACK_S`, run `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh "$FALLBACK_S" inherit-breaker "$PARENT_S"` so the review-origin window carries over, then require its `scope.env`, `files.txt`, and `untracked.txt` to byte-match the files in `PARENT_S`. Require a nonempty parent evidence manifest and require the generated roster to identify every temporary
substitution. For SDK numeric recovery, keep the same numbered `FALLBACK_LABEL` in the fresh session, rebuild its TSV from the fresh actual roster and final emphases, and set `FALLBACK_EVIDENCE_ARGS=(--numeric-round "$FALLBACK_LABEL" --numeric-min-rounds "$NUMERIC_MIN_ROUNDS" --numeric-panel "$FALLBACK_S/r$FALLBACK_LABEL-panel.tsv")`; loss of the required SDK identity stops recovery. For other phases, set `FALLBACK_LABEL` to a fresh label, rebuild `FALLBACK_EVIDENCE_ARGS` from that roster's assignments, build `FALLBACK_LAUNCHED_SEATS` from every seat in the fresh roster, and prepare its fresh full-panel evidence manifest without launching:

```bash
FALLBACK_MANIFEST=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" prepare \
  "$FALLBACK_S" "$FALLBACK_LABEL" --phase "$PANEL_PHASE" "${FALLBACK_EVIDENCE_ARGS[@]}")
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" same-source "$PARENT_MANIFEST" "$FALLBACK_MANIFEST"
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
if a fallback seat itself reports quota, or if any source identity changed, retry through `rev-workhorse.py escalate`, which honors a matching per-review override and otherwise selects the next higher enforced seat; if that fails, finish the lens yourself. The
next review run probes the preferred providers again because fallback never mutates
configuration. Call TaskStop only for pending task identifiers. Never cancel a completed valid sibling
before its terminal state is preserved, and preserve every
partial stream and log for diagnosis.

Exit 7 is local attempt exhaustion, not provider quota. Preserve valid siblings and finish the missing assignment yourself without another repair child.

Retain each completed valid result; a result whose `summary` begins `INCOMPLETE PROOF` is never one. Triage valid results as they arrive, but do not edit until the receipt seals. Continue each failed assignment through the configured eligible replacement chain until valid proof exists or no eligible seat remains. There is no panel-wide cap; each attempt uses a unique child label bound directly to its original failed parent assignment.

Use `rev-workhorse.py escalate` to select the replacement executor. It applies a matching per-review override, or uses the next family on the host's normal enforced chain. A nonzero exit means the chain is exhausted: finish that assignment yourself in the spirit of its lens. When the JSON says `"existing": false`, repair preparation reads `$S/escalation.json`. The parent must have a recorded terminal failure: its archived `r<N>-<seat>.audit-invalid.json`, exit-0 `INCOMPLETE PROOF` result, or an exact retry that also exited 1 or 2.

Choose `<N>x` for the first child and distinct suffixes such as `<N>x2` for additional failed assignments. Prepare each child with:

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" prepare "$S" "$CHILD_LABEL" --phase repair --assignment "$EXECUTOR=$PARENT_BUNDLE" --parent-assignment "<N>:$FAILED_SEAT"`

Preparation rejects an ineligible executor, a parent without a terminal failure, or a duplicate child label. It permits multiple attempts for the same original failed assignment, each with a distinct label and each bound directly to that original panel assignment. Render the child with the per-seat form above and record `"${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh" "$S" phase=repair "round=$CHILD_LABEL" "seats=[\"$EXECUTOR\"]"` before launch. Add `REPLACEMENT_ARGS+=(--replacement "$FAILED_SEAT=$CHILD_LABEL")` once for each repaired parent assignment before sealing. Discovery follows the same rule, and every child has full scope. If no eligible seat remains or the configured chain is exhausted without a valid result, finish that missing assignment yourself in this session.

After every assigned seat has a valid result, seal an SDK numeric panel only after
its exact complete launched set has valid full-scope generations, including one selected separately bound successful child for each failed assignment when applicable. Its receipt stays numeric and preserves any
existing adaptive coverage head. Certify discovery after its complete simplicity panel.
For risk and verification, certify only after the complete four-bundle panel is
collected:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" receipt "$S" "$PANEL_LABEL" \
  "${REPLACEMENT_ARGS[@]}"
```

If receipt fails, stop before another reviewer launch. The failed receipt establishes no coverage; diagnose and fix its provenance or contract error, then begin a new review run explicitly. Never turn receipt failure into an automatic full-panel rerun.

### Fan out

Immediately before launch, write the exact artifact label and the same seats whose
prompts were already rendered:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=fan-out round=<N> "seats=$LAUNCHED_SEATS"
```

Take this panel's lens list from the **Adaptive panel plan** and assign lenses by the
rule below before scope preparation. Complete the single render pass above for every
launched seat. Fan-out launches only those already-rendered prompt files. Never call
`rev-prompt.sh` between that completed render pass and launch.

Launch **every non-extra seat in ONE message**. In explicit numeric round mode,
also launch any extra seat whose `round` is this round. Use one `Bash` call with
`run_in_background: true` per seat whose adapter is `codex`, `gemini`, or `claude` -
each launches through `rev-seat.sh` - and one `Agent` call per seat whose adapter is `agent`. Route each
agent row by its roster model: `sonnet` uses `rev-reviewer-sonnet`; `opus` and padded
`claude-1`, `claude-2`, ... rows use `rev-reviewer`.

Before every initial or same-label retry launch, synchronously remove `$S/r$PANEL_LABEL-$SEAT.exit` and confirm it is absent before starting the reviewer process. Perform this host-side step before dispatch so collection cannot observe an exit from an earlier launch.

```
Bash: ${CLAUDE_PLUGIN_ROOT}/scripts/rev-seat.sh <seat> $S <N> $S/r<N>-<seat>.prompt.md   (run_in_background)
      … one per rev-seat.sh row (codex, gemini, or claude - whatever the roster lists) …
Agent: { subagent_type: "review-council:rev-reviewer", description: "rev r<N> <seat> <lens>",
         prompt: "Your instructions are in $S/r<N>-<seat>.prompt.md. Read that file first with the Read tool, follow it exactly, and return ONLY the JSON object it asks for. You are one seat inside a review that is already running: never invoke /review-council:rev, /review-council:stack, or claude -p, and never start a review by any other means." }
Agent: { subagent_type: "review-council:rev-reviewer-sonnet", description: "rev r<N> sonnet <lens>",
         prompt: "Your instructions are in $S/r<N>-sonnet.prompt.md. Read that file first with the Read tool, follow it exactly, and return ONLY the JSON object it asks for. You are one seat inside a review that is already running: never invoke /review-council:rev, /review-council:stack, or claude -p, and never start a review by any other means." }
      ... one per agent seat, selected from the row's model ...
```

Each agent seat gets its **own** already-rendered prompt and its own lens, and its
`Agent` prompt names that file.
A launch is complete only after its returned Bash task ID or Agent task ID is stored
under the seat name in the pending-seat handle map. That map is the authority for
collection, seat-local retry, and cancellation.
A padded seat is a seat, not a copy of the first one: launching one Agent for all of
them, or handing two of them the same prompt, throws away the only diversity a degraded
panel has left.

The `agent` adapter is not a script: it is those `Agent` calls. `rev-seat.sh` refuses it.

**Extra seats** are omitted by the adaptive default. In explicit numeric round mode,
they carry `"extra": true` and a `round` in the roster - currently `codex-review`
in round 3.
In its round, add it to `LAUNCHED_SEATS` before the single render pass, keep its fixed `security` lens,
and launch it in the same message as the rest.

`codex-review` never sees its prompt (`codex exec review --base` refuses custom
instructions) - render it anyway: it is the record of what that seat was asked.

```
Bash: ${CLAUDE_PLUGIN_ROOT}/scripts/rev-seat.sh codex-review $S <N> $S/r<N>-codex-review.prompt.md --base $REV_BASE   (run_in_background)
```

After every seat has launched, preserve the same `round` and exact `seats` while
switching to collect:
`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=collect round=<N> "seats=$LAUNCHED_SEATS"`.
Then, for each row whose adapter is `agent`, record its Agent result path under its seat name with
`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S agent_transcripts.<seat>=<the Agent result's output_file path>`.
Record every Agent seat separately. CLI seats use their own logs and need no transcript state.

### Lens assignment

Order the non-extra seats exactly as `roster.seats` lists them and index them from
`0`. With `L` lenses in this round's list and round number `N`:

```
seat i gets lenses[(i + N) mod L]
```

The `+ N` offset is what makes a small roster cover everything: without it a 2-lens
round would hand the same seat the same lens in every round it appears. Extra seats do
not take part - each keeps the fixed lens the round plan names for it.

Worked, round 4 (`lenses = [concurrency, resources, performance]`, `L = 3`, `N = 4`):

- **3 seats** (`codex-sol, codex-terra, opus`) → `(0+4)%3=1`, `(1+4)%3=2`, `(2+4)%3=0` →
  resources, performance, concurrency. Every lens covered once.
- **4 seats** (`codex-sol, codex-terra, opus, sonnet`) → resources, performance,
  concurrency, resources. The repeat is deliberate: two models on one lens is the
  agreement signal.
- **6 seats** (`codex-sol, codex-terra, gemini, opus, sonnet, claude-1`) → resources,
  performance, concurrency, resources, performance, concurrency - two seats per lens.
- **3 padded seats** (`opus, claude-1, claude-2` on a Claude-only machine) → the same
  three lenses, one each. Padded seats are dealt lenses exactly like detected ones;
  never collapse them or give two of them the same lens.

Worked, round 6 (`lenses = [tests, observability]`, `L = 2`, `N = 6`) with 4 seats →
`(0+6)%2=0`, `(1+6)%2=1`, `(2+6)%2=0`, `(3+6)%2=1` → tests, observability,
tests, observability. In round 7 the same seats would swap sides.

### Collect

Inspect terminal results as they arrive instead of waiting for all notifications.
Remove a seat from the pending map only after its terminal result is recorded. Do not
edit the working tree while seats run.

- Each `rev-seat.sh` prints `seat=<s> round=<n> exit=<c> findings=<k>` when it exits.
- The Agent returns the `agent` seat's JSON as text. Write it to `$S/r<N>-<seat>.json`
  - take the outermost `{…}` and drop anything around it: a ```` ```json ```` fence, or
  a sentence of prose before the object (seen live in round 1). Then
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lib/validate-findings.py $S/r<N>-<seat>.json`;
  write `0` (valid) or `2` to `$S/r<N>-<seat>.exit`.
- For each Agent seat, copy `<output_file>` to `$S/r<N>-<seat>.stream.ndjson` without opening it
  in the orchestrator context, so profiling retains the complete subagent transcript.
  An Agent seat is an unenforced evidence seat, not an excluded one: it is launched under the same
  manifest as every other row, recorded in `unenforced_seats`, and the transcript left here is what
  the receipt audits, ungated, to record whether that seat would have passed.

| seat exit | action |
|---|---|
| `0` | done, unless the result's `summary` begins `INCOMPLETE PROOF` |
| `1` or `2` with no invalid read audit | retry that seat once immediately at the same receipted effort while siblings continue, even if it left an `INCOMPLETE PROOF` result, unless `rev-attempt.py` refused the launch for one; if the retry fails, continue through the configured replacement chain below |
| hard evidence-audit failure | keep siblings running; never relaunch that seat under that label. After the exact retry for an execution failure, or immediately after a hard audit failure or exit-0 `INCOMPLETE PROOF` result, continue that assignment through the configured eligible replacement chain until valid proof exists or no eligible seat remains. There is no panel-wide cap either; every attempt uses a unique child label and binds directly to its original failed parent assignment. |
| `0` with an `INCOMPLETE PROOF` result, or a relaunch `rev-attempt.py` refused for one | replace now, as for a hard evidence-audit failure: it is never a valid result; keep siblings running; never relaunch that seat under that label |
| `3` | cancel that provider's pending siblings, retry through `rev-workhorse.py escalate` (matching per-review override first, then the default chain), and if that fails finish the lens yourself |
| `4` | cancel that provider's pending siblings, retry through `rev-workhorse.py escalate` (matching per-review override first, then the default chain), and if that fails finish the lens yourself |

A round needs **three or more** seats' output. With fewer, retry each missing assignment through `rev-workhorse.py escalate` (matching per-review override first, then the default chain), then cover any seat that is still missing yourself and record that coverage in the ledger.
Repair children use `<N>x`, then distinct suffixed labels such as `<N>x2`; the default one-seat plan panel remains a separate exception. Do not call orchestrator coverage a certified seat.
Padding guarantees three
seats were *launched*, so this rule is now about seats that failed, not seats that were
never there.
