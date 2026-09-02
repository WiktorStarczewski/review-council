---
name: rev
description: Multi-model review-and-fix loop run from this session — a panel built at run time from whichever frontier CLIs are installed and signed in (Codex, Grok, Gemini) plus an Opus subagent, all at maximum effort, triaged into a ledger, fixed, verified and committed until rounds stop producing material findings. Use when the user runs /review-council:rev, asks for a review, audit, or check of code changes (a PR, a branch, uncommitted work, a path), after completing any non-trivial implementation, or for a read-only second opinion on a plan, design doc, or prose.
user_invocable: true
---

# rev — multi-model review-and-fix loop

You are the orchestrator. The reviewers are other labs' frontier models plus one Opus
subagent; **they never edit**. You fan out, verify their claims against the source,
fix, verify the gates, commit, and report. The point is decorrelation: a reviewer
that shares your weights shares your blind spots, so a review you run on your own
work alone is proofreading. Disagreement between labs is the signal worth having.

Token cost and latency are not concerns. Never shorten the loop, lower an effort
tier, or drop a seat to save tokens.

Scripts live in `${CLAUDE_PLUGIN_ROOT}/scripts/` and are written out in full below.
If `$CLAUDE_PLUGIN_ROOT` is not set in the shell a `Bash` call gets, resolve it once
from this file's own location — the plugin root is the parent of `skills/rev/` — and
export it for the rest of the run.

**The panel is not a fixed list of seats.** Preflight builds the roster from the CLIs
actually installed and signed in on this machine and writes it to `$S/roster.json`;
every seat name in this document is an example from a typical roster. Read the roster,
launch what it names, and never invent a seat, a model slug, or an effort tier.

## Parse

`/review-council:rev [scope] [rounds] [--read-only]`

| | values | default |
|---|---|---|
| scope | `branch`, `uncommitted`, a path, a PR number or URL, a branch name | `branch` |
| rounds | integer minimum | `7` |
| `--read-only` | findings only — no fixes, no commits | off |

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

1. Resolve the scope. PR number/URL: `gh pr checkout <n>`. Branch name: `git checkout
   <name>`. Then `mkdir -p $S` and:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-preflight.sh --scope <branch|uncommitted|path> --write $S
   ```
   Non-zero → stop and relay the one-line reason verbatim. Do not work around it: a
   shared branch, an empty scope, or a roster with fewer than three usable seats each
   means the review cannot run as asked. Zero → it printed `base=… branch=…
   changed_files=…` and the roster line; `$S/scope.env`, `$S/files.txt`,
   `$S/untracked.txt` and `$S/roster.json` now exist. Source `scope.env` for
   `REV_BASE`, `REV_ROOT`, `REV_SCOPE` — every value in it is single-quoted, so a
   branch name or path with shell metacharacters is inert data.
   Arm the recursion guard once preflight has passed (it refuses when `REV_ACTIVE` is
   already set, so arming it earlier would block your own run): from here on every seat
   runs with `REV_ACTIVE=1` in its environment — `rev-seat.sh` exports it itself, and
   each `Bash` call is a fresh shell, so prefix any other seat-side command you run with
   `REV_ACTIVE=1`. Do not run `rev-preflight.sh` again inside this run. The `Agent` seat
   carries no environment; the clause in its prompt (below) is its fence.
2. Baseline patch, scoped exactly as the review is — a path scope must not capture
   the whole branch, and untracked files appear in **no** diff at all:
   ```bash
   case "$REV_SCOPE" in
     branch|uncommitted) git diff $REV_BASE ;;
     *)                  git diff $REV_BASE -- "$REV_SCOPE" ;;
   esac > $S/00-baseline.patch
   # untracked files are listed in files.txt but are invisible to git diff — append them as add-patches
   while IFS= read -r f; do [ -n "$f" ] && git diff --no-index /dev/null "$f" >> $S/00-baseline.patch; done < $S/untracked.txt
   ```
   (`git diff --no-index` exits 1 when the files differ; that is the normal case here.)
   Then run the repo's build, tests and linters (from its CLAUDE.md, `package.json`
   scripts, `Cargo.toml`, `Makefile` — whatever the project uses) and write
   `$S/baseline.md`: one line per gate, `pass` or `fail` with the failing test/lint
   names. Pre-existing failures are not regressions later.
3. Read the diff yourself — the same command as the baseline patch above, plus every
   file in `$S/untracked.txt` read in full (nothing in a diff will show them). You
   triage; you need your own model of the change before you see anyone else's.
4. State and ledger. The seat list comes from the roster, not from memory:
   ```bash
   SEATS=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps([s['seat'] for s in d['seats'] if not s.get('extra')]))" $S/roster.json)
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S round=0 min_rounds=<rounds> phase=setup "seats=$SEATS" open.P0=0 open.P1=0 open.P2=0 fixed=0 rejected=0 started_at=<iso-now>
   [ -f $S/findings.md ] || printf '# Findings ledger — %s\n\nScope: %s @ %s\n\n' "$S" "$REV_BRANCH" "$REV_BASE" > $S/findings.md
   [ -f $S/rejected.md ] || : > $S/rejected.md
   ```
   **Create, never truncate.** A session dir is reused across passes and retries
   (`/review-council:stack` hands you the same `$S` for pass 2 and for every retry of a
   leg), and `findings.md` is the whole prior verdict. When either file already exists,
   READ it before round 1 and treat its `FIXED` / `REJECTED` / `DEFERRED` entries as
   settled: do not re-raise them, and append this run's entries below the existing
   ones. `>` there would have deleted the ledger the resume note tells seats to read.
   Make a todo list with one item per planned round.
5. Arm the status tick, once (not in stack-leg mode):
   ```
   Monitor({ command: "while true; do sleep 600; ${CLAUDE_PLUGIN_ROOT}/scripts/rev-status.sh <S>; done",
             description: "rev status <S>", persistent: true, timeout_ms: 3600000 })
   ```
   Every event it emits is relayed to the user (see **Status tick**).

## The loop — one round

`fan out → collect → triage → fix → verify → commit → record`

### Fan out

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=fan-out round=<N>`. Read the
roster for this round's seats:

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1]));
print('\n'.join('%s\t%s\t%s' % (s['seat'], s['adapter'], ('extra round %s' % s.get('round')) if s.get('extra') else 'base') for s in d['seats']))" $S/roster.json
```

Take this round's lens list from the **Round plan** and assign lenses by the rule
below. Render one prompt per seat playing this round (add `--vacuity` whenever
`files.txt` contains a test file):

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh $S <N> <seat> <lens> "<round emphasis>" [--vacuity]
```

Then launch **every non-extra seat in ONE message**, plus any extra seat whose `round`
is this round: one `Bash` call with `run_in_background: true` per seat whose adapter is
an adapter script, and one `Agent` call for the seat whose adapter is `agent`.

```
Bash: ${CLAUDE_PLUGIN_ROOT}/scripts/rev-seat.sh <seat> $S <N> $S/r<N>-<seat>.prompt.md   (run_in_background)
      … one per adapter seat (codex, grok, gemini — whatever the roster lists) …
Agent: { subagent_type: "review-council:rev-reviewer", description: "rev r<N> <seat> <lens>",
         prompt: "Your instructions are in $S/r<N>-<seat>.prompt.md. Read that file first with the Read tool, follow it exactly, and return ONLY the JSON object it asks for. You are one seat inside a review that is already running: never invoke /review-council:rev, /review-council:stack, or claude -p, and never start a review by any other means." }
```

The `agent` adapter is not a script: it is that `Agent` call. `rev-seat.sh` refuses it.

**Extra seats** carry `"extra": true` and a `round` in the roster — typically
`codex-review` in round 2 and `grok-code-review` in round 3. In their round, add them
to `seats` in state, render their prompts too, and launch them in the same message as
the rest:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh $S 2 codex-review     security        "<round emphasis>" [--vacuity]   # round 2
${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh $S 3 grok-code-review maintainability "<round emphasis>" [--vacuity]   # round 3
```

`codex-review` never sees its prompt (`codex exec review --base` refuses custom
instructions) — render it anyway: it is the record of what that seat was asked, and
`grok-code-review` genuinely reads the one rendered for it.

```
Bash: ${CLAUDE_PLUGIN_ROOT}/scripts/rev-seat.sh codex-review $S <N> $S/r<N>-codex-review.prompt.md --base $REV_BASE   (run_in_background)
Bash: cp $S/r<N>-grok-code-review.prompt.md $S/r<N>-grok-code-review.src.md &&
      ${CLAUDE_PLUGIN_ROOT}/scripts/rev-seat.sh grok-code-review $S <N> $S/r<N>-grok-code-review.src.md              (run_in_background)
```

The `grok-code-review` seat writes its own `/code-review`-prefixed copy of whatever
prompt it is handed, to `$S/r<N>-<seat>.prompt.md` — the very path `rev-prompt.sh`
renders to. Give it that path and it reads and rewrites one file without bound, so
always pass the rendered prompt under a different name (`.src.md` above).

Immediately after: `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=collect opus_transcript=<the Agent result's output_file path>`.

### Lens assignment

Order the non-extra seats exactly as `roster.seats` lists them and index them from
`0`. With `L` lenses in this round's list and round number `N`:

```
seat i gets lenses[(i + N) mod L]
```

The `+ N` offset is what makes a small roster cover everything: without it a 2-lens
round would hand the same seat the same lens in every round it appears. Extra seats do
not take part — each keeps the fixed lens the round plan names for it.

Worked, round 3 (`lenses = [concurrency, resources, performance]`, `L = 3`, `N = 3`):

- **3 seats** (`codex-sol, grok, opus`) → `(0+3)%3=0`, `(1+3)%3=1`, `(2+3)%3=2` →
  concurrency, resources, performance. Every lens covered once.
- **4 seats** (`codex-sol, codex-terra, grok, opus`) → concurrency, resources,
  performance, concurrency. The repeat is deliberate: two models on one lens is the
  agreement signal. Plus the round-3 extra `grok-code-review` at maintainability.
- **6 seats** (`codex-sol, codex-terra, grok, gemini, opus, …`) → concurrency,
  resources, performance, concurrency, resources, performance — two seats per lens.

Worked, round 5 (`lenses = [tests, observability]`, `L = 2`, `N = 5`) with 4 seats →
`(0+5)%2=1`, `(1+5)%2=0`, `(2+5)%2=1`, `(3+5)%2=0` → observability, tests,
observability, tests. In round 6 the same seats would swap sides.

### Collect

Wait for all notifications. Do not edit the working tree while seats run.

- Each `rev-seat.sh` prints `seat=<s> round=<n> exit=<c> findings=<k>` when it exits.
- The Agent returns the `agent` seat's JSON as text. Write it to `$S/r<N>-<seat>.json`
  — take the outermost `{…}` and drop anything around it: a ```` ```json ```` fence, or
  a sentence of prose before the object (seen live in round 1). Then
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lib/validate-findings.py $S/r<N>-<seat>.json`;
  write `0` (valid) or `2` to `$S/r<N>-<seat>.exit`.

| seat exit | action |
|---|---|
| `0` | done |
| `1` or `2` | retry once with `--effort <one step lower>` (codex `max→xhigh→high`, grok `xhigh→high`; a seat with no effort knob, such as gemini, and the `agent` seat: re-run once unchanged). Still failing → skip this round, note it in the ledger |
| `3` | stop the run; tell the user which tool needs sign-in |
| `4` | drop the seat for the rest of the run: `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S 'dropped=[…]'`; name it in the report |

A round needs **three or more** seats' output. With fewer, stop and say so. Never fall
back to reviewing the diff yourself and calling it reviewed.

### Triage

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=triage`. Read every
`$S/r<N>-*.json` (they are small). For each finding:

1. **Deduplicate** across seats; record how many independently found it. Agreement is
   signal, not proof.
2. **Verify against the source yourself.** Open the file at the cited lines. Reviewers
   hallucinate line numbers, invent APIs, and misread control flow. A claim you cannot
   substantiate is `REJECTED (unsubstantiated)`.
3. **Assign severity** — P0 incorrect behaviour / security hole / data loss / crash;
   P1 real bug on a reachable path, bad edge case, broken contract; P2
   maintainability, performance, missing test, unclear API; P3 nit.
4. Append the ledger entry (format below). For every rejection, append one line to
   `$S/rejected.md`: `- F-xxx REJECTED: <reason> (<file>:<line>)` — the next round's
   prompts carry it so seats do not resurface settled items.

Update counts: `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S open.P0=<n> open.P1=<n> open.P2=<n> rejected=<n>`.

### Fix

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=fix`. Fix P0 → P1 → P2, highest
first. P3 only when trivial and safe. Match the surrounding style; do not reformat
untouched code. When two findings conflict, resolve it explicitly in the ledger. A
finding that is right but out of scope is `DEFERRED (reason)`; wrong is `REJECTED
(reason)`. Rejecting is a valid outcome — never fix what is not broken to satisfy a
reviewer.

### Verify

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=verify`. Re-run the gates from
setup. Compare with `baseline.md`: pre-existing failures are not regressions; anything
newly failing is yours to repair or revert **before** the next round. Never advance on
a broken build.

### Commit

`${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=commit`. Only after verification
passes, and only if the round changed files. Stage what the round touched (never `git
add -A` blindly; the session dir is outside the repo). No push. Never `--amend`, never
`--no-verify`, never force. No AI attribution of any kind.

```
fix(rev): round 3 — retry logic and leaked handles

F-012 P1  retry loop re-sent 4xx requests, duplicating writes
F-014 P2  file handle leaked on the error path
```

Then `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S last_commit=<sha> fixed=<total fixed so far>`.

### Record

Append a round block to `findings.md`: seats and efforts used, lenses, new findings
by severity, fixed/rejected/deferred counts, verification result, commit SHA (or
"no changes"). Tell the user in two or three sentences: round number, seats, new
findings by severity, what was fixed, gate status, commit.

## Round plan

Minimum seven rounds. The lens list is per round; the seats that get each lens come
from **Lens assignment** above. The same lens under a different model finds different
things, and repeats within a round give agreement signal.

| Round | Emphasis | Lenses, in order | Extra seat |
|---|---|---|---|
| 1 | Correctness, edge cases, error handling | correctness, edge-cases, error-handling | — |
| 2 | Security, data & state | security, data-state | `codex-review` — security |
| 3 | Concurrency, resources, performance | concurrency, resources, performance | `grok-code-review` — maintainability |
| 4 | API & contract, compatibility | api-contract, data-state, readability | — |
| 5 | Tests, observability | tests, observability | — |
| 6 | Red team — argue the change is broken | red-team | — |
| 7 | Regression + cumulative diff re-read | regression | — |
| 8+ | Whatever is least covered or still open | the uncovered lenses, rotated off the previous pairing | — |

Lens catalog (as `rev-prompt.sh` knows them): `correctness security edge-cases
error-handling concurrency resources api-contract data-state performance tests
observability readability red-team regression maintainability`. Every lens is
covered at least once per run.

**Vacuity.** Whenever the diff touches tests, every prompt carries `--vacuity`. It is
empirically the most common defect a panel finds and it finds it late — a 12-leg
review once produced eleven, several not until round 3, three of them the
orchestrator's own.

## Extension and termination

Keep going past the minimum while any hold: the last round produced a new P0/P1; the
last round's fixes were more than trivial; any P0/P1 is open; a lens or a major
changed file is unreviewed.

Stop when all hold: minimum rounds ran; two **consecutive** rounds produced no new
P0/P1; no P0/P1 open; gates at or better than baseline. Stop early only on an empty
scope or the user's instruction. Still finding P0s at high round counts → say so
plainly; that is a rework signal, not a patching signal.

## After the loop

Not in stack-leg mode:

1. `${CLAUDE_PLUGIN_ROOT}/scripts/rev-squash.sh` (dry run) then
   `${CLAUDE_PLUGIN_ROOT}/scripts/rev-squash.sh --apply` — collapses the contiguous
   `fix(rev)` run at the tip into one `apply review findings` commit. A run broken up
   by other commits is left alone; the PR squash-merge is the real collapse. A refusal
   ("only N unpushed") means something was pushed mid-loop — leave history as is and
   say so.
2. Push once (`git push`, `-u origin HEAD` if no upstream), so CI runs on what
   reviewers will see.
3. `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=done`; write `$S/report.md`;
   stop the status Monitor with `TaskStop`; report (below).

## Stack-leg mode (`REV_STACK_LEG=1`)

You are running headless under `/review-council:stack`. Differences: no Monitor
(nobody is watching this transcript; `stack.sh` renders the status line itself); no
squash, no push (the stack does both per repo at the end); never ask a question —
decide and record the decision in the ledger; always write `$S/report.md` before your
final message, even on a stopped run — the stack treats a leg that exits without it as
incomplete and re-runs it.

**Print mode delivers no background-task notifications.** A turn that ends "waiting
for the seats" or "waiting for the gate run" ends the leg: `claude -p` returns at
end-of-turn with the loop unfinished (seen live: round-4 fixes left uncommitted, no
report). So in stack-leg mode:

- Launch the CLI seats with `run_in_background` as usual, then **wait for them with a
  foreground poll** — a Bash call that loops `until` every `$S/r<N>-<seat>.exit` for
  this round exists (sleep 30 between checks, stop the call at ~9 minutes and issue
  another) — never by ending your turn.
- Run gates, commits, and everything else in the foreground.
- Never end a turn while a seat, a gate, a fix, or a commit is pending.

## Read-only panel

For plans, docs, prose, and code with `--read-only`. Same seats, same schema, same
ledger; one round unless `rounds` is given; no fixes, no commits.

**Code with `--read-only`** (a branch, a PR, `uncommitted`, a path — the scope is a
diff, not a document list): run **Setup** exactly as in the loop, including
`rev-preflight.sh --scope <scope> --write $S` (it only reads and writes the session
dir) and the baseline gates, and render prompts the normal way — *without*
`--read-only`, so seats get the repo, the pinned base and the changed-file list. Fan
out, collect and triage exactly as in a round. Then stop: no **Fix**, no **Verify**,
no **Commit**, no squash, no push, and no `--vacuity` exemption. Report as below,
minus the commits section; the standing rule to apply actionable findings then applies
to you *after* reporting, as its own separate change the user can see.

**Documents** (the rest of this section):

1. `mkdir -p $S`; write the document paths, one per line, to `$S/docs.txt`.
   `export REV_REPO=<the repo root if the docs live in one, else their directory>`.
   There is no git scope here, so no `rev-preflight.sh`: build the roster yourself with
   `${CLAUDE_PLUGIN_ROOT}/scripts/roster.sh --probe --write $S/roster.json` (it refuses with
   exit 5 when fewer than three seats are usable — relay that and stop), and refuse the
   run if `REV_ACTIVE` was set on entry. Then arm the guard as in setup: every seat runs
   with `REV_ACTIVE=1`, and the `Agent` seat carries the same no-nested-review clause.
2. State as in setup (`seats` from the roster), arm the Monitor, then per round:
   `${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh $S <N> <seat> <lens> "<emphasis>" --read-only $S/docs.txt`
   for each seat; fan out and collect exactly as in the loop.
3. Triage verifies each claim against the document; ledger as usual; no fix/verify/
   commit phases. Report as below, minus commits. The standing rule to apply
   actionable findings then applies to you after reporting — for a document that
   means editing it as asked, not silently.

## Status tick — every 10 minutes, unprompted

`rev-status.sh` renders one line from the session dir:

```
r3/7 triage | sol: done 4f 9m | terra: done 2f 11m | grok: running 14m ← rg "retry" src/api | opus: done 3f 8m | open P0:0 P1:1 P2:3 fixed 6
```

When a Monitor event carries such a line, relay it to the user **as-is** plus at most
one sentence saying what you are doing right now. Do this even mid-round; the user
asked for it. Keep `state.json` honest — it is the only thing the tick can see:
`round`, `phase`, `seats`, `dropped`, `open.*`, `fixed`, `opus_transcript`. If the
loop stops early, the last relayed line says why.

## Failure handling

| Failure | Action |
|---|---|
| seat exit 1 or 2 | retry once one effort step lower (or unchanged where there is no effort knob), then skip for the round |
| seat exit 3 | stop; report which tool needs sign-in |
| seat exit 4 | drop the seat for the run; continue with ≥3 |
| fewer than 3 seats in a round | stop; say so; do not self-review |
| a fix breaks a gate | repair or revert before the next round |
| squash refuses | leave history; say so |
| the `agent` seat returns non-JSON twice | treat it as exit 2 for the round |

## Ledger (`$S/findings.md`)

```markdown
## F-012 · P1 · FIXED
File:     src/api/handler.ts:88
Found by: round 3 — codex-terra@max, opus@max (2/4)
Claim:    Retry loop re-sends the request after a 4xx, duplicating writes.
Verified: yes — handler.ts:88, no status check before retry.
Action:   Fixed in round 3 (a1b2c3d) — retry only on 5xx and network errors.
```

Status ∈ `OPEN | FIXED | REJECTED (reason) | DEFERRED (reason)`. Every finding ends
in one of them; never drop one silently. Round blocks append after the entries.

## Report (`$S/report.md` and in chat)

1. **Outcome**, in prose, first: what was wrong with the code and whether the change
   is sound now.
2. **Findings table**: ID, severity, location, claim, resolution — sorted by severity.
3. **Rejected** findings with reasons, so the user can overrule a judgment call.
4. **Coverage**: rounds, seats and efforts, lenses, final gate status, any seat that
   dropped and why.
5. **Commits**: one line per round commit; the squash commit; the push.
6. **Residual risk**: deferred, untestable, worth a human look.

Say plainly if P0s were still appearing in late rounds. A confident report over a
shallow review is the one failure this skill exists to prevent.

## Session directory

```
scope.env  files.txt  untracked.txt  roster.json  00-baseline.patch  baseline.md  findings.md  rejected.md  state.json  report.md
r<N>-<seat>.prompt.md   r<N>-<seat>.json   r<N>-<seat>.log   r<N>-<seat>.stream.ndjson   r<N>-<seat>.exit
```

## Tool notes (why the wrappers look the way they do)

- `codex exec` reads stdin to EOF and blocks forever on an open pipe. `rev-seat.sh`
  feeds the prompt file as stdin (`- < file`). Never call codex by hand without
  `</dev/null` or a file on stdin.
- `grok --json-schema` sometimes answers on turn one without reading anything, even with the
  tools-first instruction `rev-prompt.sh` puts at the top of grok prompts (seen live: summary
  "I'll inspect the diff…", zero findings, zero tool calls). `rev-seat.sh` treats an answer
  with no `tool_call` events as not-a-review: it retries once, then fails the seat (exit 2).
  The gemini adapter is held to the same rule.
- grok's structured output lives only in the stream's final `{"type":"end"}` record;
  `stream-summary.py` extracts it. Gemini has no schema flag at all: the adapter takes the
  outermost `{…}` from its last message and the wrapper validates it like any other seat's.
- `codex exec review --base` (the `codex-review` seat) refuses custom instructions and ignores
  `--output-schema`: it runs codex's own review prompt and answers in prose, which
  `rev-seat.sh` converts into the schema (`lib/codex-review-to-findings.py`); the prose is kept as
  `r<N>-codex-review.native.txt`. Treat its severities as that reviewer's opinion — triage re-judges.
- Never edit `rev-seat.sh` (or any script) in place while seats run: bash reads scripts lazily and a
  rewritten file corrupts the in-flight run. Write to a temp file and `mv` over it.
- Codex `ultra` effort delegates to subagents and is opaque; `max` is the default.
  `REV_CODEX_EFFORT=ultra` opts in.
- The roster is rebuilt every run by preflight from the CLIs installed and signed in, with the
  effort tier read from each CLI's own model list. Never invent a slug or a tier: if a seat fails,
  step down the effort ladder on the same model before substituting anything.
