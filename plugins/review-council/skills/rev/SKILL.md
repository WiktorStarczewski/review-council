---
name: rev
description: Multi-model review-and-fix loop run from this session - a panel built at run time from whichever frontier CLIs are installed and signed in (Codex and Gemini) plus configured Claude subagents, all at maximum effort, triaged into a ledger, fixed, verified and committed until rounds stop producing material findings. Use when the user runs /review-council:rev, asks for a review, audit, or check of code changes (a PR, a branch, uncommitted work, a path), after completing any non-trivial implementation, or for a read-only second opinion on a plan, design doc, or prose.
user_invocable: true
---

# rev - multi-model review-and-fix loop

This skill is an executable workflow contract. Follow every applicable step in its stated order. Do not cherry-pick, replace, or improvise around steps. Before omitting a step, record the exact reason it is inapplicable. A run missing any audit, receipt, or final report required by its selected mode is incomplete and must not be described as a Review Council review.

You are the orchestrator. The reviewers are other labs' frontier models plus configured
Claude subagents; **they never edit**. You fan out, verify their claims against the source,
fix, verify the gates, commit, and report. The point is decorrelation: a reviewer
that shares your weights shares your blind spots, so a review you run on your own
work alone is proofreading. Disagreement between labs is the signal worth having.

Keep the independent panel and maximum effort. Bound cost by running only the panels
that change the verdict, keeping prompts compact, and reporting usage after each panel.

Scripts live in `${CLAUDE_PLUGIN_ROOT}/scripts/` and are written out in full below.
If `$CLAUDE_PLUGIN_ROOT` is not set in the shell a `Bash` call gets, resolve it once
from this file's own location - the plugin root is the parent of `skills/rev/` - and
export it for the rest of the run.

**The panel is not a fixed list of seats.** Preflight builds the roster from the CLIs
actually installed and signed in on this machine and writes it to `$S/roster.json`;
every seat name in this document is an example from a typical roster. Read the roster,
launch what it names, and never invent a seat, a model slug, or an effort tier.

**A thin panel is padded, never refused.** With fewer than three seats detected, the
roster appends Claude seats - `claude-1`, `claude-2`, … , adapter `agent`, marked
`"padded": true` - until there are three, and sets `"degraded": true` with a
one-sentence `degradation`. Those seats are full seats: they are dealt lenses like any
other, so three Claude seats read the diff through three different lenses. What is lost
is decorrelation, not coverage - and losing it is something you say out loud (see
**Report**), never a reason to skip the loop or to read the diff yourself instead.

## Parse

`/review-council:rev [scope] [rounds] [--read-only]`

| | values | default |
|---|---|---|
| scope | `branch`, `uncommitted`, a path, a PR number or URL, a branch name | `branch` |
| rounds | optional integer minimum override | adaptive |
| `--read-only` | findings only - no fixes, no commits | off |

"use S as the session dir" in the invocation names the session directory
(`/review-council:stack` passes this). Otherwise `S=/tmp/rev-$(date +%s)`.

## Route

- `REV_ACTIVE` set on entry → refuse: "a review is already running here". Test it
  yourself, first thing (`echo "REV_ACTIVE=${REV_ACTIVE:-unset}"`): `rev-preflight.sh`
  is the only script that checks it, and the read-only panel never runs it. Nothing
  downstream of a review may start another.
- `--read-only`, or the scope is a document (`.md`/`.txt`/`.rst` path, or the user
  named a plan, design doc, or prose) → **Read-only panel** (below).
- Otherwise → **The loop**.
- `REV_STACK_LEG=1` → **Stack-leg mode** differences apply (below).

## Setup (once)

Configuration lives at `~/.config/review-council/config.json` or the path in
`REVIEW_COUNCIL_CONFIG`. The optional `quota_fallback` boolean is shared with the
Codex host.

1. Resolve the scope. PR number/URL: `gh pr checkout <n>`, then save the author's own
   description for the seats: `gh pr view <n> --json title,body --jq '"# " + .title + "\n\n" + .body' > $S/pr.md`.
   For a branch or path scope, try the same with `gh pr view` (no number) and ignore failure.
   `$S/pr.md` is for you (triage, scope decisions); do **not** pass `--pr $S/pr.md` to seat
   prompts by default - measured, it anchors reviewers on the author's framing and loses
   findings. Pass it only when the user asks for it. Branch name: `git checkout
   <name>`. Then canonicalize the session once so macOS `/tmp` and `/private/tmp`
   share one manifest identity:
   ```bash
   mkdir -p "$S"
   S=$(cd "$S" && pwd -P)
   ```
   Then run:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-preflight.sh --scope <branch|uncommitted|path> --write $S
   ```
   Non-zero → relay the one-line reason verbatim. Exit 5 is retryable. Preserve the
   session and retry after the temporary provider availability problem clears. Exit 6 is permanent.
   Stop because the scope or strict roster contract cannot run as asked. A thin
   roster is not one of those; it is
   padded and run. Zero → it printed `base=… base_branch=… (how) branch=… changed_files=…` - check
   `base_branch` (the open PR's base, else the nearest fork point) and re-run with `--base <ref>`
   if it is wrong, since a wrong base reviews someone else's commits - the roster
   line, and, when the panel is degraded, a second line `preflight: WARNING - <sentence>`;
   carry that sentence into the report. `$S/scope.env`, `$S/files.txt`,
   `$S/untracked.txt` and `$S/roster.json` now exist. Source `scope.env` for
   `REV_BASE`, `REV_ROOT`, `REV_SCOPE` - every value in it is single-quoted, so a
   branch name or path with shell metacharacters is inert data.
   Arm the recursion guard once preflight has passed (it refuses when `REV_ACTIVE` is
   already set, so arming it earlier would block your own run): from here on every seat
   runs with `REV_ACTIVE=1` in its environment - `rev-seat.sh` exports it itself, and
   each `Bash` call is a fresh shell, so prefix any other seat-side command you run with
   `REV_ACTIVE=1`. Do not run `rev-preflight.sh` again inside this run. The `Agent` seat
   carries no environment; the clause in its prompt (below) is its fence.
2. Baseline patch, scoped exactly as the review is - a path scope must not capture
   the whole branch, and untracked files appear in **no** diff at all:
   ```bash
   case "$REV_SCOPE" in
     branch|uncommitted) git diff $REV_BASE ;;
     *)                  git diff $REV_BASE -- "$REV_SCOPE" ;;
   esac > $S/00-baseline.patch
   # untracked files are listed in files.txt but are invisible to git diff - append them as add-patches
   while IFS= read -r f; do [ -n "$f" ] && git diff --no-index /dev/null "$f" >> $S/00-baseline.patch; done < $S/untracked.txt
   ```
   (`git diff --no-index` exits 1 when the files differ; that is the normal case here.)
   Then run the repo's build, tests and linters (from its CLAUDE.md, `package.json`
   scripts, `Cargo.toml`, `Makefile` - whatever the project uses) and write
   `$S/baseline.md`: one line per gate, `pass` or `fail` with the failing test/lint
   names. Pre-existing failures are not regressions later.
3. Read the diff yourself - the same command as the baseline patch above, plus every
   file in `$S/untracked.txt` read in full (nothing in a diff will show them). You
   triage; you need your own model of the change before you see anyone else's.
4. State and ledger. The seat list comes from the roster, not from memory:
   ```bash
   SEATS=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps([s['seat'] for s in d['seats'] if not s.get('extra')]))" $S/roster.json)
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S round=0 min_rounds=<explicit-rounds-or-adaptive> phase=setup "seats=$SEATS" open.P0=0 open.P1=0 open.P2=0 fixed=0 rejected=0 started_at=<iso-now>
   [ -f $S/findings.md ] || printf '# Findings ledger - %s\n\nScope: %s @ %s\n\n' "$S" "$REV_BRANCH" "$REV_BASE" > $S/findings.md
   [ -f $S/rejected.md ] || : > $S/rejected.md
   ```
   **Create, never truncate.** A session dir is reused across passes and retries
   (`/review-council:stack` hands you the same `$S` for pass 2 and for every retry of a
   leg), and `findings.md` is the whole prior verdict. When either file already exists,
   READ it before round 1 and treat its `FIXED` / `REJECTED` / `DEFERRED` entries as
   settled: do not re-raise them, and append this run's entries below the existing
   ones. `>` there would have deleted the ledger the resume note tells seats to read.
   Make a todo list with one item per planned panel.
5. Arm the status tick, once (not in stack-leg mode):
   ```
   Monitor({ command: "while true; do sleep 600; ${CLAUDE_PLUGIN_ROOT}/scripts/rev-status.sh <S>; done",
             description: "rev status <S>", persistent: true, timeout_ms: 3600000 })
   ```
   Every event it emits is relayed to the user (see **Status tick**).

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
seat count. Use every configured core seat, including Sol, Terra, Opus, and Sonnet
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
and leave `MANIFEST` empty. Document panels read every supplied document in full and
use their legacy rendering flow below.

If any launched code-panel roster row has adapter `agent`, skip evidence preparation
for the whole code panel and keep `MANIFEST` empty. Claude Code plugin subagents ignore
hook frontmatter, so an Agent seat cannot provide the enforced tool transcript required
by evidence mode. Render and launch every code seat at full legacy scope under the same
panel label. Plan preparation instead fails before publishing artifacts when any plan
seat uses adapter `agent`. Report that plan review is unavailable with an Agent seat
and requires a roster whose seats use enforceable Codex or Claude CLI adapters. Do not
replace the schema-4 plan with a legacy full-scope task.

Before adaptive fan-out, set `PANEL_LABEL` to the artifact label and `PANEL_PHASE` to
`discovery`, `risk`, `verification`, or `repair`. Build `EVIDENCE_ARGS` from the exact
launched seats: discovery passes `--full-seat` for the first core seat; risk and
verification pass one `--assignment "$SEAT=$BUNDLE_OR_COMPOSITE"` per seat plus
`--full-seat` for the first regression-bundle seat; repair passes its one assignment
and that repair seat as `--full-seat`. Then prepare once:

```bash
MANIFEST=
if CANDIDATE=$(REV_PATCH_CHUNKS=${REV_PATCH_CHUNKS:-auto} REV_SOURCE_CONTEXT=${REV_SOURCE_CONTEXT:-1} python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" --phase "$PANEL_PHASE" "${EVIDENCE_ARGS[@]}"); then
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

Build the optional flag once. Render every seat before any reviewer process starts,
using the same flag array for the entire panel. Append the usual `--vacuity` or `--pr`
flag only when applicable.

```bash
EVIDENCE_PROMPT_ARGS=()
[ -n "$MANIFEST" ] && EVIDENCE_PROMPT_ARGS=(--evidence "$MANIFEST")
${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh "$S" "$PANEL_LABEL" "$SEAT" "$LENS" "$EMPHASIS" "${EVIDENCE_PROMPT_ARGS[@]}"
```

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
of those audited ranges. Agent-adapter findings must intersect a range from that
seat's assigned packet, and the audit must prove that every assigned shard was opened
in full. The enforced read hooks are an earlier guard, not post-run evidence. A missing, malformed,
stale, partial, oversized, unassigned, or unparseable packet or source range invalidates
the whole attempt. The same is true for unsupported provider transcript shapes and
zero-tool answers. In chunk mode, the audit also requires every hash-bound chunk once
in exact order before packet and source reads. Missing, reordered, truncated, replaced,
unassigned, redirected, or oversized chunks invalidate the attempt.
Read order, repository call count, output sentinel overflow, a missing navigation index, and duplicate completed reads are advisories when patch, required-source, citation, and result completeness all pass. These advisories remain visible in the receipt but never discard a substantively complete review.

Retain one launch handle for every pending seat and inspect each terminal result as it arrives. Store every Bash task ID and Agent task ID under its seat name. A provider execution exit 1 or 2 with no invalid read audit is seat-local and may retry only the failed seat once with its exact prompt, assignment, model, and effort while other seats continue. A hard evidence-audit failure is a compiler or contract incident: stop the current panel without another paid retry and preserve every valid sibling and partial stream. Never widen an evidence-audit failure into a full-state repair.

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
${CLAUDE_PLUGIN_ROOT}/scripts/rev-preflight.sh --scope "$REV_SCOPE" --write "$FALLBACK_S" \
  --quota-failed-seat "$SEAT"
```

Before switching the active session to `FALLBACK_S`, require its `scope.env`, `files.txt`, and `untracked.txt` to byte-match the files in `PARENT_S`. Require a nonempty parent evidence manifest and require the generated roster to identify every temporary
substitution. Set `FALLBACK_LABEL` to a fresh label, rebuild `FALLBACK_EVIDENCE_ARGS` from that roster's assignments, build `FALLBACK_LAUNCHED_SEATS` from every seat in the fresh roster, and prepare its fresh full-panel evidence manifest without launching:

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
The quota fallback panel is the only permitted full-panel restart for this panel generation. If a hard audit failure occurs in the fallback panel, stop without a repair or another fallback.
If the new roster cannot replace the quota-failed lab,
if a fallback seat itself reports quota, or if any source identity changed, stop. The
next review run probes the preferred providers again because fallback never mutates
configuration. Call TaskStop only for pending task identifiers. Never cancel a completed valid sibling
before its terminal state is preserved, and preserve every
partial stream and log for diagnosis.

Exit 7 is local attempt exhaustion, not provider quota. Preserve valid siblings and stop the panel without substitution or a repair child.

Retain each completed valid result. Triage completed valid results as they arrive, but do not edit until the receipt seals. If a provider execution fails twice, preserve its siblings. With at least three valid reviewers, run at most the existing one-seat coverage repair for a missing semantic bundle; otherwise report the panel incomplete. Do not create a replacement generation for execution or audit compliance failures. A hard audit failure never enters coverage repair.

After every assigned seat has a valid result, certify discovery after its complete simplicity panel.
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
`run_in_background: true` per seat whose adapter is
an adapter script, and one `Agent` call per seat whose adapter is `agent`. Route each
agent row by its roster model: `sonnet` uses `rev-reviewer-sonnet`; `opus` and padded
`claude-1`, `claude-2`, ... rows use `rev-reviewer`.

Before every initial or same-label retry launch, synchronously remove `$S/r$PANEL_LABEL-$SEAT.exit` and confirm it is absent before starting the reviewer process. Perform this host-side step before dispatch so collection cannot observe an exit from an earlier launch.

```
Bash: ${CLAUDE_PLUGIN_ROOT}/scripts/rev-seat.sh <seat> $S <N> $S/r<N>-<seat>.prompt.md   (run_in_background)
      … one per adapter seat (codex or gemini - whatever the roster lists) …
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
Then record each Agent result path under its seat name with
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
  Agent-containing code panels always use full legacy scope and do not create evidence audits.

| seat exit | action |
|---|---|
| `0` | done |
| `1` or `2` with no invalid read audit | retry that seat once immediately at the same maximum effort while siblings continue; still failing means the configured panel is incomplete |
| hard evidence-audit failure | stop the panel; preserve its diagnostics; do not relaunch that label |
| `3` | cancel pending siblings, stop the run, and tell the user which tool needs sign-in |
| `4` | cancel pending siblings, stop the run, and name the usage or rate-limit blocker |

A round needs **three or more** seats' output. With fewer, stop and say so. An
adaptive `<N>x` coverage repair is one seat, not a panel, and is the only exception. Never fall
back to reviewing the diff yourself and calling it reviewed. Padding guarantees three
seats were *launched*, so this rule is now about seats that failed, not seats that were
never there.

### Triage

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=triage`. Read every
`$S/r<N>-*.json` (they are small). For each finding:

1. **Deduplicate** across seats; record how many independently found it. Agreement is
   signal, not proof.
2. **Verify against the source yourself.** Open the file at the cited lines. Reviewers
   hallucinate line numbers, invent APIs, and misread control flow. A claim you cannot
   substantiate is `REJECTED (unsubstantiated)`.
3. **Assign severity** - P0 incorrect behaviour / security hole / data loss / crash;
   P1 real bug on a reachable path, bad edge case, broken contract; P2
   maintainability, performance, missing test, unclear API; P3 nit.
4. Append the ledger entry (format below). For every rejection, append one line to
   `$S/rejected.md`: `- F-xxx REJECTED: <reason> (<file>:<line>)` - the next round's
   prompts carry it so seats do not resurface settled items.

5. **Cluster.** Group the round's accepted findings by root cause: one cluster is one rule
   that, applied everywhere it holds, closes every finding in it. Name it in each ledger entry
   (`Cluster:  C-03 re-check hold ownership after every parking await`). A finding that is the
   only member of its cluster is still a cluster.

Update counts: `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S open.P0=<n> open.P1=<n> open.P2=<n> rejected=<n>`.

### Plan - the fix-design gate

Run the plan panel when accepted findings require a nontrivial change; skip it when
there is no accepted fix or every accepted fix is a P3 or one-line P2. Repeat it only
when verification accepts a new P0/P1 root cause or another nontrivial cluster.

Why: over 11 past runs, 56% of all findings (68% from round 5 on) were fixes of an
earlier round's fix, and 55% of those were *incomplete* fixes - a rule applied to the one
site a reviewer named while its siblings waited for the next round. The gate makes the
rule explicit and lets the panel attack it before it becomes code. Evidence:
`docs/churn-analysis-2026-09-06.md` in the plugin repository.

1. Write `$S/fix-plan.md`, one section per cluster:

   ```markdown
   ## C-03 · re-check hold ownership after every parking await
   Findings: F-012 (P1), F-019 (P2), F-023 (P3)
   Rule:     an eviction abandons but does not cancel, so every WASM call that follows an
             await which can park must re-check that it still owns the hold.
   Sites:    src/lib/sync/useSyncTrigger.ts:141, :208; src/lib/miden/sdk/miden-client.ts:88;
             worker realm: src/workers/sync.ts:60  (found by: rg -n 'await .*lock' .)
   Must not: change the eviction timing; touch the SW driver (owned by C-04).
   Test:     sync-lock.test.ts - evict mid-await, assert the late call is dropped (fails today).
   Interacts with: C-04 (both touch the ceiling; C-04 lands first).
   ```

   `Sites` is the part that matters: enumerate by searching, not by memory, and list every
   arm, realm, caller and copy (JSDoc, README, CHANGELOG, `.d.ts`) the rule reaches.
2. Set `PLAN_SEATS` to every surviving non-extra seat, even when the preceding code
   panel included an extra or a one-seat repair. Record the full plan panel immediately
   before launch:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=plan round=<N>p "seats=$PLAN_SEATS"
   ```
   Deal the plan lenses by the same rule (`lenses = [plan-completeness,
   plan-soundness, plan-simplicity, plan-tests]`). Build one assignment per seat,
   with the plan-completeness seat as `--full-seat`. For three seats, combine
   `plan-completeness+plan-tests` on the first seat.
   For five or more, keep `plan-completeness` unique and cycle only the other
   three lenses on surplus seats.
   Bind the current plan bytes and
   prepare the plan closure before rendering:
   ```bash
   PANEL_LABEL=<N>p
   PLAN_HASH=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
   MANIFEST=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" prepare "$S" "$PANEL_LABEL" \
     --phase plan --plan "$S/fix-plan.md" --plan-sha256 "$PLAN_HASH" \
     --full-seat "$PLAN_COMPLETENESS_SEAT" "${PLAN_EVIDENCE_ARGS[@]}")
   PLAN_SNAPSHOT="$S/r$PANEL_LABEL-plan.md"
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh "$S" "$PANEL_LABEL" <seat> <plan-lens> \
     "<round emphasis>" --plan "$PLAN_SNAPSHOT" --evidence "$MANIFEST"
   ```
   Each `rev-prompt.sh` call validates its rendered plan prompt against the schema-4
   manifest before atomically publishing it. Scope, lens, manifest hash, inline plan,
   and the complete authorized artifact set must match exactly. After every plan prompt
   renders, apply the same single ordinary prelaunch verify and require every prompt's
   one embedded manifest hash to match before fan-out.
   The parser requires every cluster to have `Findings`, `Rule`, `Sites`, and at
   least one of `Test`, `Tests`, or `Regression`. Every path must resolve in the
   pinned repository snapshot. Locations may use `path:line`, `path:start-end`,
   or a shorthand `:start-end` after a path. `Sites` must include one bounded query in
   either exact form: `found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'PATTERN' .`
   or `found by: grep --exclude-dir=.git --null -r -n -- 'PATTERN' .`. These fixed
   flags cover every regular worktree file except `.git`. Do not add other globs,
   types, exclusions, path operands, maximum depth, redirects, or filename suppression.
   Keep the result below 80 lines. It must include every path named in `Sites`; native
   text search cannot certify this proof.
   Every reviewer receives the full inline plan and complete navigation index. The
   plan-completeness seat receives the full cumulative patch and every cluster's
   closure, search, and source obligations. Each cluster is also routed to one
   specialist. With a valid predecessor receipt, specialists receive only the fix delta
   for their clusters; otherwise they receive the cumulative cluster closure.
   They never receive a full-state fallback. Each specialist prompt names one exact
   primary artifact as its mandatory first native read. Do not prepend a directory
   command, search, or compound shell command. Assigned seats receive up to three
   source-context shards and the hash-bound repository-wide sibling-site search result
   prepared once from the frozen snapshot. This gives every cluster two independent
   readers. Assigned seats may run additional searches when the prepared result raises
   a question. If preparation or any render fails, fix the evidence or task compiler
   and prepare a fresh schema-4 label before launch. Never mix attempts.

   Use the matching round label `<N>p` (the plan panel is extra, not a numbered code
   panel); write its outputs as `r<N>p-<seat>.json`. Collect as usual. Before triage,
   validate the complete panel without changing code coverage:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rev-evidence.py" verify-panel "$S" "$PANEL_LABEL"
   ```
   `verify-panel` binds the plan, manifest, prompts, streams, results, patch chunks,
   source packets, finding citations, and every cluster search and source proof. It
   never writes a receipt or advances `coverage-head.json`. An individual provider
   execution failure with no invalid read audit retains valid sibling results and may
   retry only that seat once with its exact prompt, assignment, model, and effort. A
   hard plan read-audit failure stops the panel before another paid launch. If a plan seat exhausts its exact provider retry,
   preserve every completed sibling and partial stream, then report the configured
   plan panel incomplete. Do not broaden a specialist to full scope or replace the
   schema-4 task with a legacy prompt.
3. Triage the plan findings like any others (verify against the code; ledger entries carry
   the `Cluster:` line). Amend `fix-plan.md` in place: add the sites the panel found, split
   or merge rules, replace a mechanism with the reuse a seat named. A plan finding that
   the panel got wrong is `REJECTED` like any other.
4. Then, and only then, **Fix**.

The plan round costs one seat round. A plan that survives review is what the fix
commits implement - nothing outside it lands this round.

### Fix

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=fix`. Implement `fix-plan.md`
**one cluster per commit**, P0 clusters first: every enumerated site, arm, realm and copy in the
same commit. A fix that covers the cited instance and leaves a listed sibling is not done -
it is next round's finding. Within a cluster, P3 only when trivial and safe. P3 only when trivial and safe. Match the surrounding style; do not reformat
untouched code. When two findings conflict, resolve it explicitly in the ledger. A
finding that is right but out of scope is `DEFERRED (reason)`; wrong is `REJECTED
(reason)`. Rejecting is a valid outcome - never fix what is not broken to satisfy a
reviewer.

### Verify

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=verify`. Re-run the gates from
setup. Compare with `baseline.md`: pre-existing failures are not regressions; anything
newly failing is yours to repair or revert **before** the next round. Never advance on
an unverified material tree. For review-council self-hosting, run an 8-30 second
focused test after each edit, the roughly three-minute evidence fixture after a
coherent contract cluster, and the complete suite once for each material tree. Record
the tree hash and successful command so an unchanged tree reuses that gate result.
Before a paid panel after adapter, prompt, manifest, or audit changes, preflight
replays the preserved provider envelopes through the current auditor.
Replay runs after the roster probe and before any reviewer launch.
The probe binds the exact models and efforts. Preflight reuses a hash-keyed pass receipt
only when the boundary, fixtures, contract tests, and provider versions match; a replay
failure blocks the paid run.

### Commit

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=commit`. Only after verification
passes, and only if the round changed files. Stage what the round touched (never `git
add -A` blindly; the session dir is outside the repo). No push. Never `--amend`, never
`--no-verify`, never force. No AI attribution of any kind.

```
fix(rev): round 3 - C-03 re-check hold ownership after every parking await

F-012 P1  late call after eviction re-entered the client
F-019 P2  worker realm had the same late call
```

Then `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S last_commit=<sha> fixed=<total fixed so far>`.

### Record

Append a round block to `findings.md`: seats and efforts used, lenses, new findings
by severity, fixed/rejected/deferred counts, verification result, commit SHA (or
"no changes"). Tell the user in two or three sentences: round number, seats, new
findings by severity, what was fixed, gate status, commit.

## Adaptive panel plan

With four core seats, a normal review plans 12 seat launches: four simplicity,
four conditional plan, and four final verification launches. A large or high-risk
review plans 16 by adding four risk-discovery launches. An explicit round count
remains a minimum override and exclusively selects the legacy numbered schedule.

A change is large with more than 25 changed files or more than 1,500 changed lines.
It is high-risk when it crosses a security, persistence, concurrency, transaction,
or public API boundary.

| Panel | When | Lenses, in order |
|---|---|---|
| Simplicity discovery | always | simplicity for every seat |
| Risk discovery | large or high-risk only | correctness-boundaries, security-state-api, concurrency-resources-performance, tests-observability-maintenance-regression |
| Plan | accepted nontrivial fixes | plan-completeness, plan-soundness, plan-simplicity, plan-tests |
| Verification | after discovery or the latest nontrivial fix | the four risk bundles, rotated from risk discovery |

Adaptive default panels use core seats and omit extras. Explicit numeric round plans
may include extras in their configured rounds. The four risk bundles cover logic,
boundaries, error handling, security, state, API contracts, concurrency, resources,
performance, tests, observability, maintenance, and regression. Keep the same evidence
rules and the same maximum effort in every bundle.

One four-bundle verification panel reviews the latest material state: directly after
discovery when no nontrivial fix follows, or after the latest nontrivial fix. After a
risk or verification panel returns at least three valid reviewers, compute coverage
from valid outputs for any roster size; run every missing bundle as an `<N>x` repair
on a distinct surviving seat before certification. A coverage repair is one seat, so
the three-reviewer minimum does not apply. Do not certify the adaptive panel until all
four bundles have valid results. Set `REPAIR_SEATS` to exactly the seats launched for
that repair, then record `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=repair round=<N>x "seats=$REPAIR_SEATS"`
immediately before launching it.

An explicit numeric override exclusively uses the legacy numbered code-panel schedule below.
Conditional plan panels are extra and do not count toward the requested total.
For round 9 and later, target uncovered or unresolved risk.

| Round | Emphasis | Lenses, in order | Extra seat |
|---|---|---|---|
| 1 | Simplicity - could this change be smaller? | simplicity | - |
| 2 | Correctness, edge cases, error handling | correctness, edge-cases, error-handling | - |
| 3 | Security, data & state | security, data-state | `codex-review` - security |
| 4 | Concurrency, resources, performance | concurrency, resources, performance | - |
| 5 | API & contract, compatibility | api-contract, data-state, readability | - |
| 6 | Tests, observability | tests, observability | - |
| 7 | Red team - argue the change is broken | red-team | - |
| 8 | Regression + cumulative diff re-read | regression | - |
| 9+ | Whatever is least covered or still open | the uncovered lenses, rotated off the previous pairing | - |

**Simplicity first.** Round 1 belongs entirely to the question "could this change be
smaller?": every seat gets `simplicity`. Measured on eight held-out PRs (the plugin's
`docs/simplicity-lens-eval-2026-09-06.md`), four seats with the lens found the load-bearing
simplification on 6 of 10 rows; every variant that replaced one of them with a design seat
(`clean-room`, which sketches the smallest design for the named consumer before reading the
diff) found fewer, and giving the seats the author's PR description cost more load-bearing
rows than it gained - reviewers anchor on the author's framing instead of attacking it. So
neither is dealt by default: `clean-room` is available as an *additional* seat when the roster
has five or more, and `--pr` is available but off. At triage, a reuse finding is accepted only
with the existing symbol named at a location and version you have opened; a scope cut is
`DEFERRED (scope decision)` for the user. Correctness lenses start in round 2: reviewing lines
that should be deleted is the purest form of churn.

**Vacuity.** Whenever the diff touches tests, every prompt carries `--vacuity`. It is
empirically the most common defect a panel finds and it finds it late - a 12-leg
review once produced eleven, several not until round 3, three of them the
orchestrator's own.

## Extension and termination

Repeat plan, fix, and verification only when a verification panel produces a new
P0/P1 root cause, leaves a P0/P1 open, or is followed by another nontrivial fix.
A P3 or one-line P2 follow-up needs the project gates. Every other accepted fix needs
a full adaptive verification panel.

Adaptive completion requires a full four-bundle verification panel after discovery
or the latest nontrivial fix, no new or open P0/P1, no material change left
unreviewed, and gates at or better than baseline.

Only numeric mode continues past its requested minimum while any of these hold: the
last numbered code panel produced a new P0/P1; the last numbered panel's fixes were
nontrivial; any P0/P1 remains open; or a lens or major changed file remains unreviewed.
Numeric mode stops only after the requested minimum numbered code panels ran, two
consecutive numbered code panels produced no new P0/P1, no P0/P1 remains open, and
gates are at or better than baseline. Plan panels do not count as numbered code panels.
Still finding P0s in a later cycle is a rework signal and must be reported plainly.

Never append the cumulative findings ledger to reviewer prompts. For a resumed run,
write `$S/context.md` as a concise one-line digest of settled decisions; the prompt
renderer includes it automatically. Do not copy `findings.md`. After every panel, run
`${CLAUDE_PLUGIN_ROOT}/scripts/rev-profile.py $S` and relay completed calls, processed
tokens, prompt words, and provider cost when available. Current-session completion
and finding yield require a schema-valid result with a successful exit receipt. Only
exact hashed receiptless results recorded in a versioned legacy roster policy may omit
one. Usage-bearing failed attempts remain metered. Report the profiler's core-roster signature with every measurement. Treat a mixed-roster marker as a comparison boundary
for provider tokens, cost, elapsed time, and finding yield.
Prompt warnings above 1,800
code words or 3,000 plan words require removing repeated context, not truncating
evidence.

## After the loop

Not in stack-leg mode:

1. `${CLAUDE_PLUGIN_ROOT}/scripts/rev-squash.sh` (dry run) then
   `${CLAUDE_PLUGIN_ROOT}/scripts/rev-squash.sh --apply` - collapses the contiguous
   `fix(rev)` run at the tip into one `apply review findings` commit. A run broken up
   by other commits is left alone; the PR squash-merge is the real collapse. A refusal
   ("only N unpushed") means something was pushed mid-loop - leave history as is and
   say so.
2. Push once (`git push`, `-u origin HEAD` if no upstream), so CI runs on what
   reviewers will see.
3. `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=done`; write `$S/report.md`;
   stop the status Monitor with `TaskStop`; report (below).

## Stack-leg mode (`REV_STACK_LEG=1`)

You are running headless under `/review-council:stack`. Differences: no Monitor
(nobody is watching this transcript; `stack.sh` renders the status line itself); no
squash, no push (the stack does both per repo at the end); never ask a question -
decide and record the decision in the ledger; always write `$S/report.md` before your
final message, even on a stopped run - the stack treats a leg that exits without it as
incomplete and re-runs it.

**Print mode delivers no background-task notifications.** A turn that ends "waiting
for the seats" or "waiting for the gate run" ends the leg: `claude -p` returns at
end-of-turn with the loop unfinished (seen live: round-4 fixes left uncommitted, no
report). So in stack-leg mode:

- Launch the CLI seats with `run_in_background` as usual, then **wait for them with a
  foreground poll** - a Bash call that loops `until` every `$S/r<N>-<seat>.exit` for
  this round exists after the synchronous prelaunch removal (sleep 30 between checks, stop the call at ~9 minutes and issue
  another) - never by ending your turn.
- Run gates, commits, and everything else in the foreground.
- Never end a turn while a seat, a gate, a fix, or a commit is pending.

## Read-only panel

For plans, docs, prose, and code with `--read-only`. Same seats, same schema, same
ledger; one round unless `rounds` is given; no fixes, no commits.

**Code with `--read-only`** (a branch, a PR, `uncommitted`, a path - the scope is a
diff, not a document list): run **Setup** exactly as in the loop, including
`rev-preflight.sh --scope <scope> --write $S` (it only reads and writes the session
dir) and the baseline gates, and render prompts the normal way - *without*
`--read-only`, so seats get the repo, the pinned base and the changed-file list. Fan
out, collect and triage exactly as in a round. Then stop: no **Fix**, no **Verify**,
no **Commit**, no squash, no push, and no `--vacuity` exemption. Report as below,
minus the commits section; the standing rule to apply actionable findings then applies
to you *after* reporting, as its own separate change the user can see.

**Documents** (the rest of this section):

1. `mkdir -p $S`; write the document paths, one per line, to `$S/docs.txt`.
   `export REV_REPO=<the repo root if the docs live in one, else their directory>`.
   There is no git scope here, so no `rev-preflight.sh`: build the roster yourself with
   `${CLAUDE_PLUGIN_ROOT}/scripts/roster.sh --probe --brief --write $S/roster.json` (it pads a thin
   panel and exits 0; exit 5 is retryable and exit 6 is permanent, so relay the one-line
   reason verbatim and preserve or stop the run accordingly), relay its `degradation`
   sentence when the roster is degraded,
   and refuse the run if `REV_ACTIVE` was set on entry. Then arm the guard as in setup: every seat runs
   with `REV_ACTIVE=1`, and the `Agent` seat carries the same no-nested-review clause.
2. State as in setup (`seats` from the roster), arm the Monitor, then per round:
   `${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh $S <N> <seat> <lens> "<emphasis>" --read-only $S/docs.txt`
   for each seat; fan out and collect exactly as in the loop.
3. Triage verifies each claim against the document; ledger as usual; no fix/verify/
   commit phases. Report as below, minus commits. The standing rule to apply
   actionable findings then applies to you after reporting - for a document that
   means editing it as asked, not silently.

## Status tick - every 10 minutes, unprompted

`rev-status.sh` renders one line from the session dir:

```
r3/7 triage | sol: done 4f 9m | terra: running 14m ← rg "retry" src/api | opus: done 3f 8m | sonnet: done 2f 7m | open P0:0 P1:1 P2:3 fixed 6
```

On a padded panel the seat columns read `opus`, `claude-1`, `claude-2` - three Claude
seats on three different lenses, not one seat printed three times.

When a Monitor event carries such a line, relay it to the user **as-is** plus at most
one sentence saying what you are doing right now. Do this even mid-round; the user
asked for it. Keep `state.json` honest - it is the only thing the tick can see:
`round`, `phase`, `seats`, `dropped`, `open.*`, `fixed`, `agent_transcripts`. If the
loop stops early, the last relayed line says why.

## Failure handling

| Failure | Action |
|---|---|
| seat exit 1 or 2 with no invalid read audit | retry that seat once immediately at the same maximum effort; still failing leaves the configured panel incomplete |
| hard evidence-audit failure | stop the panel; preserve its diagnostics; do not relaunch that label |
| seat exit 3 | cancel pending siblings; stop; report which tool needs sign-in |
| seat exit 4 | cancel pending siblings; stop; report the usage or rate-limit blocker |
| fewer than 3 seats in a round | stop; say so; do not self-review |
| a fix breaks a gate | repair or revert before the next round |
| squash refuses | leave history; say so |
| the `agent` seat returns non-JSON twice | treat it as exit 2 for the round |

## Ledger (`$S/findings.md`)

```markdown
## F-012 · P1 · FIXED
File:     src/api/handler.ts:88
Found by: round 3 - codex-terra@max, opus@max (2/4)
Claim:    Retry loop re-sends the request after a 4xx, duplicating writes.
Verified: yes - handler.ts:88, no status check before retry.
Action:   Fixed in round 3 (a1b2c3d) - retry only on 5xx and network errors.
```

Status ∈ `OPEN | FIXED | REJECTED (reason) | DEFERRED (reason)`. Every finding ends
in one of them; never drop one silently. Round blocks append after the entries.

## Report (`$S/report.md` and in chat)

1. **Outcome**, in prose, first: what was wrong with the code and whether the change
   is sound now. When `roster.json` has `"degraded": true`, open with `Degraded panel:`
   and the roster's `degradation` sentence, before anything else - how much
   decorrelation a verdict rests on is part of the verdict.
2. **Findings table**: ID, severity, location, claim, resolution - sorted by severity.
3. **Rejected** findings with reasons, so the user can overrule a judgment call.
4. **Coverage**: rounds, seats and efforts, lenses, final gate status, any seat that
   dropped and why. On a degraded panel, state the roster's `degradation` sentence
   verbatim and name every seat carrying `"padded": true`.
5. **Commits**: one line per round commit; the squash commit; the push.
6. **Residual risk**: deferred, untestable, worth a human look.

Say plainly if P0s were still appearing in late rounds. A confident report over a
shallow review is the one failure this skill exists to prevent.

## Session directory

```
scope.env  files.txt  untracked.txt  roster.json  00-baseline.patch  baseline.md  findings.md  rejected.md  state.json  report.md
r<N>-<seat>.prompt.md   r<N>-<seat>.json   r<N>-<seat>.log   r<N>-<seat>.stream.ndjson   r<N>-<seat>.exit
fix-plan.md   context.md   r<N>p-<seat>.prompt.md   r<N>p-<seat>.json
```

## Tool notes (why the wrappers look the way they do)

- `codex exec` reads stdin to EOF and blocks forever on an open pipe. `rev-seat.sh`
  feeds the prompt file as stdin (`- < file`). Never call codex by hand without
  `</dev/null` or a file on stdin.
- Gemini has no schema flag: the adapter takes the
  outermost `{…}` from its last message and the wrapper validates it like any other seat's.
- `codex exec review --base` (the `codex-review` seat) refuses custom instructions and ignores
  `--output-schema`: it runs codex's own review prompt and answers in prose, which
  `rev-seat.sh` converts into the schema (`lib/codex-review-to-findings.py`); the prose is kept as
  `r<N>-codex-review.native.txt`. Treat its severities as that reviewer's opinion - triage re-judges.
- Never edit `rev-seat.sh` (or any script) in place while seats run: bash reads scripts lazily and a
  rewritten file corrupts the in-flight run. Write to a temp file and `mv` over it.
- Launch every seat at the exact effort recorded by preflight. Change the roster configuration
  and rerun preflight before using a different effort; launch-time overrides cannot diverge.
- The roster is rebuilt every run by preflight from the CLIs installed and signed in, with the
  effort tier read from each CLI's own model list. Never invent a slug or a tier. If an exact retry
  fails, retain the preflight effort and report the configured panel incomplete.
