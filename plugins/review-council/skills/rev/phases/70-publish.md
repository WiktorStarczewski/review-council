## After the loop

Not in stack-leg mode:

1. Push once (`git push`, `-u origin HEAD` if no upstream), when authorized. Follow
   the repository's CI request policy and verify results for the pushed revision.
   Push the fix commits as committed; the finding-to-commit
   mapping is the audit trail, and the PR's own squash-merge collapses them on the
   target branch.
2. Follow **PR review publication** below. Publication succeeds or cleanly skips
   because no open PR is associated before the run can become done.
3. `${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S phase=done`; write `$S/report.md`;
   stop the status Monitor with `TaskStop`; report (below).

## Stack-leg mode (`REV_STACK_LEG=1`)

You are running headless under `/review-council:stack`. Differences: no Monitor
(nobody is watching this transcript; `stack.sh` renders the status line itself); no
push (the stack pushes per repo at the end); never ask a question -
decide and record the decision in the ledger. After the local review, rendering, and
inspection are complete, set `phase=stack-ready` and write `$S/stack-report.md` before
your final message. Do not set `phase=done` or write `$S/report.md`; the stack promotes
that ready receipt only after guarded finalization and publication. A stopped run has
no ready receipt, so the stack treats it as incomplete and re-runs it.

**Print mode delivers no background-task notifications.** A turn that ends "waiting
for the seats" or "waiting for the gate run" ends the leg: `claude -p` returns at
end-of-turn with the loop unfinished (seen live: round-4 fixes left uncommitted, no
report). So in stack-leg mode:

- Launch every `rev-seat.sh` row - `codex`, `gemini`, and `claude` alike - with
  `run_in_background` as usual, then **wait for them with a foreground poll** - a Bash
  call that loops `until` every `$S/r$PANEL_LABEL-<seat>.exit` for this panel exists
  after the synchronous prelaunch removal (sleep 30 between checks, stop the call at ~9 minutes and issue
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
no **Commit**, no push, and no `--vacuity` exemption. Follow **PR review publication**
below, then report as below, minus the commits section; the standing rule to apply actionable findings then applies
to you *after* reporting, as its own separate change the user can see.

**Documents** (the rest of this section):

1. `mkdir -p $S`; write the document paths, one per line, to `$S/docs.txt`.
   `export REV_REPO=<the repo root if the docs live in one, else their directory>`.
   There is no git scope here, so no `rev-preflight.sh`: build the roster yourself with
   `${CLAUDE_PLUGIN_ROOT}/scripts/roster.sh --probe --brief --write $S/roster.json --review-mode documents` (it pads a thin
   panel and exits 0; exit 5 is retryable and exit 6 is permanent, so relay the one-line
   reason verbatim and preserve or stop the run accordingly), relay its `degradation`
   sentence when the roster is degraded,
   and refuse the run if `REV_ACTIVE` was set on entry. Then arm the guard as in setup: every seat runs
   with `REV_ACTIVE=1`, and every `agent` row's `Agent` prompt carries the same no-nested-review clause.
2. State as in setup (`seats` from the roster), arm the Monitor, then per round:
   `${CLAUDE_PLUGIN_ROOT}/scripts/rev-prompt.sh $S <N> <seat> <lens> "<emphasis>" --read-only $S/docs.txt`
   for each seat; fan out and collect exactly as in the loop.
3. Triage verifies each claim against the document; ledger as usual; no fix/verify/
   commit phases. Report as below, minus commits. The standing rule to apply
   actionable findings then applies to you after reporting - for a document that
   means editing it as asked, not silently.

## Status tick - every 10 minutes, unprompted

Arm this monitor only when `status_tick` is true (see Setup). Otherwise run `rev-status.sh` on a phase change, a seat failure, or a terminal result, and do not start the 10-minute loop.

`rev-status.sh` renders one line from the session dir:

```
r3/7 triage | sol: done 4f 9m | terra: running 14m ← rg "retry" src/api | opus: done 3f 8m | sonnet: done 2f 7m | open P0:0 P1:1 P2:3 fixed 6
```

On a padded panel the seat columns read `opus`, `claude-1`, `claude-2` - three Claude
seats on three different lenses, not one seat printed three times.

When a Monitor event carries such a line, relay it to the user **as-is** plus at most
one sentence saying what you are doing right now. Do this even mid-round; the user
asked for it. Keep `state.json` honest - it is the only thing the tick can see:
`round`, `phase`, `seats`, `dropped`, `open.*`, `fixed`, and `agent_transcripts` for `agent` rows. If the
loop stops early, the last relayed line says why.

For a bounded local watch, use `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-context.py "$S" --watch --duration 600`.
It emits state changes and a fixed ten-minute scheduled tick without provider calls.
When the tick is enabled, relay every scheduled event and keep the Monitor above armed; a change does not reset
the scheduled cadence. The briefing reports missing or invalid results explicitly
and leaves certification to the receipt checks.

## Failure handling

| Failure | Action |
|---|---|
| seat exit 1 or 2 with no invalid read audit | retry that seat once immediately at the same receipted effort, even if it left an `INCOMPLETE PROOF` result, unless `rev-attempt.py` refused the launch for one; if the retry fails, continue through the configured replacement chain |
| hard evidence-audit failure | keep siblings running; never relaunch that seat under that label. After the exact retry for an execution failure, or immediately after a hard audit failure or exit-0 `INCOMPLETE PROOF` result, continue that assignment through the configured eligible replacement chain until valid proof exists or no eligible seat remains. There is no panel-wide cap either; every attempt uses a unique child label and binds to the immediately failed parent, preserving lineage to the original assignment. |
| seat exit 0 with an `INCOMPLETE PROOF` result, or a relaunch `rev-attempt.py` refused for one | replace now, as for a hard evidence-audit failure: it is never a valid result; keep siblings running; never relaunch that seat under that label |
| seat exit 3 | cancel that provider's pending siblings; retry through `rev-workhorse.py escalate`, honoring a matching per-review override before the normal chain; if that fails, finish the lens yourself |
| seat exit 4 | cancel that provider's pending siblings; retry through `rev-workhorse.py escalate`, honoring a matching per-review override before the normal chain; if that fails, finish the lens yourself |
| fewer than 3 seats in a code round | retry each missing assignment through `rev-workhorse.py escalate`, honoring matching per-review overrides before the normal chain, then cover any that remain yourself and record orchestrator coverage |
| a fix breaks a gate | repair or revert before the next round |
| an `agent` row returns non-JSON twice | treat it as exit 2 for the round |

## Ledger (`$S/findings.md`)

```markdown
## F-012 · P1 · FIXED
File:     src/api/handler.ts:88
Found by: round 3 - codex-terra@max, opus@max (2/4)
Claim:    Retry loop re-sends the request after a 4xx, duplicating writes.
Verified: yes - handler.ts:88, no status check before retry.
Action:   Fixed in round 3 (a1b2c3d) - retry only on 5xx and network errors.
```

Finding IDs are unique within the session and never reused, so a commit subject names its
findings without the round. Status ∈ `OPEN | FIXED | REJECTED (reason) | DEFERRED (reason)`. Every finding ends
in one of them; never drop one silently. Round blocks append after the entries.

## PR review publication

For every completed code review, read
`${CLAUDE_PLUGIN_ROOT}/docs/pr-review.md` and follow it exactly. Write the structured
`$S/pr-review.json`, including the exact orchestrator model, render the canonical `$S/pr-review.md`, inspect its facts, and
publish it as a `COMMENTED` GitHub PR review. This applies to normal and read-only
code reviews. A branch with no associated open PR skips cleanly. Document reviews do
not post. In stack-leg mode, prepare and render the body but leave guarded
finalization, final rendering, and publication to the stack after its final push.
A required publication failure writes
`incomplete.md` and blocks `phase=done` and `report.md`.
When `NO_PUSH=1`, render and inspect the body but let the publisher's no-push gate
skip every external GitHub call.

## Report (`$S/report.md` and in chat)

1. **Outcome**, in prose, first: what was wrong with the code and whether the change
   is sound now. When `roster.json` has `"degraded": true`, open with `Degraded panel:`
   and the roster's `degradation` sentence, before anything else - how much
   decorrelation a verdict rests on is part of the verdict.
2. **Findings table**: ID, severity, location, claim, resolution - sorted by severity.
3. **Rejected** findings with reasons, so the user can overrule a judgment call.
4. **Coverage**: rounds, seats and efforts, lenses, final gate status, any seat that
   dropped and why. Name the workhorse family, model, and effort, or `Workhorse: unavailable` and the reason. On a degraded panel, state the roster's `degradation` sentence
   verbatim and name every seat carrying `"padded": true`.
5. **Commits**: one line per fix commit (finding IDs and SHA); the push.
6. **Residual risk**: deferred, untestable, worth a human look.

Say plainly if P0s were still appearing in late rounds. A confident report over a
shallow review is the one failure this skill exists to prevent.

## Session directory

```
scope.env  files.txt  untracked.txt  roster.json  00-baseline.patch  baseline.md  findings.md  rejected.md  state.json  pr-review.json  pr-review.md  pr-review-target.json  stack-report.md  report.md
r<N>-panel.tsv   r<N>-<seat>.prompt.md   r<N>-<seat>.json   r<N>-<seat>.log   r<N>-<seat>.stream.ndjson   r<N>-<seat>.exit
fix-plan.md   workhorse.json   context.md   r<N>p-panel.tsv   r<N>p-<seat>.prompt.md   r<N>p-<seat>.json   r<N>p-<seat>.exit
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
- Launch every seat at the exact effort recorded by the session roster; launch-time overrides
  cannot diverge. Roster configuration changes require a fresh session. Start that session and
  run preflight once before using a different effort.
- A fresh session rebuilds its roster once during preflight from the CLIs installed and signed in,
  with the effort tier read from each CLI's own model list. An initialized session validates and
  reuses its frozen roster without probing. Never invent a slug or a tier. If an exact retry fails,
  retain the recorded effort and report the configured panel incomplete.
