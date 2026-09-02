---
name: stack
description: Run the /review-council:rev multi-model review across a STACK of related PRs in several repos — per-PR legs in dependency order, two passes, a cross-repo seam review, a completeness critic, stall recovery, and one squashed review commit per repo. Use when one change spans multiple repositories that must be reviewed together (a protocol change plus the SDK, client and app PRs that consume it), or when a review must run unattended for many hours. For a single PR or branch, use /review-council:rev directly.
user_invocable: true
---

# stack — one review across a stack of PRs

Wraps `/review-council:rev` for the case it does not cover: **one change spread across several repos**,
each with its own PR, that only makes sense reviewed together — and a run long enough
(10–20 h) that it must survive stalls and machine contention without supervision.

`/review-council:rev` runs one loop in this session and waits. This skill runs many, in
sequence, as headless `claude -p "/review-council:rev …"` legs, and keeps them alive.

## When this is the right tool

Both must hold:

- The change spans 3+ repos whose PRs depend on each other.
- The review will outlast your attention: legs take 1–4 h each; two passes over six
  repos is most of a day.

For one PR, one branch, or uncommitted work: `/review-council:rev`. Do not reach for this.

## Shape of a run

    PHASE 1  per-PR legs, PASS 1     one review loop per repo, in dependency order
    PHASE 1  per-PR legs, PASS 2     again — pass 1 reviewed a tree that has since changed, including by pass 1 itself
    PHASE 2  cross-repo seam review  the contracts BETWEEN the PRs
    PHASE 3  completeness critic     what did every pass miss
    FINISH   one squash + one push per repo (skipped for a repo whose leg failed)

**Pass 2 is not redundant.** In the run this skill was built from, pass 2 found that a
change landing after pass 1 had invalidated a security assumption documented on the
function it rerouted. Nothing in pass 1 could have seen it.

## Preflight

Everything `/review-council:rev`'s preflight checks per leg (working branch, non-empty
scope, a roster of at least three signed-in seats), plus:

1. **Order the legs by dependency.** Review the thing others build on first; its
   findings change what the dependents should say.
2. **Give each leg a written premise.** A leg with no context "fixes" things that are
   not broken — one reverted a deliberate version pin as a P0 overnight. Say what the PR
   claims, what is already known, and **name the claim you most want attacked**; that
   sentence produced the highest-value findings in the source run.
3. **Nothing else heavy on the box** (below).

## Running it

Copy `${CLAUDE_PLUGIN_ROOT}/scripts/stack.example.sh`, fill in `legs()` and the
seam/critic repos, then — from a plain foreground `Bash` call:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/stack.sh my-stack.sh
```

It **detaches itself** into a new session (nohup + setsid) and returns at once,
printing the session root, the log path and the orchestrator's own output file.
Do NOT launch it with `run_in_background`: a Claude Code background command is
killed by the harness after roughly an hour, and the kill takes the leg's whole
process group with it mid-round — that is exactly how the first live stack run
died. `REV_STACK_FOREGROUND=1` keeps it attached for tests or a terminal you will
keep open.

Then arm ONE `Monitor` on the log so the user gets the 10-minute status line the
`/review-council:rev` skill promises:

```
Monitor({ command: "tail -n0 -f <the log path it printed> | grep --line-buffered -E '^\\S+ \\S+ (\\[status\\]|===|!!!|#####|ALL )'",
          description: "review-council stack progress", persistent: true, timeout_ms: 3600000 })
```

Relay each event to the user as-is with at most one sentence of context. The
Monitor has its own lifetime cap; re-arm it if it expires while the run is alive
(`pgrep -f stack.sh`), and never treat a quiet Monitor as a finished run —
the log is the record.

Legs run with `REV_STACK_LEG=1`, so a leg never squashes or pushes; the orchestrator
does both once per repo at the end (`NO_PUSH=1` to skip the push). Give every
working branch an upstream of the same name first (`git push -u origin HEAD`): a
branch created from `origin/main` tracks `main`, and the final `git push` is only
saved from targeting it by `push.default=simple`. `ROOT` (session root, one
`<leg>/` dir each), `LOG`, `PASSES`, `STALL_SECS`, `MAX_ATTEMPTS` are env knobs; see
the script header.

**Resume.** Re-running with the same `LOG` skips legs already marked `=== DONE`.

## Stalls and status — one detector, in the orchestrator

A headless leg that hangs looks exactly like one that is working. `stack.sh`
polls each leg and kills it only when **both** hold:

- `run.log` (stream-json: one event per assistant message and tool call) **and** the
  leg's session dir have been quiet for `STALL_SECS` (default 30 min);
- the leg's CPU time did not move across a 45 s sample — the veto that stops a long,
  silent compile from being mistaken for a hang.

A killed leg is retried (4 attempts) with a resume note pointing at its own ledger. A
stall is never counted as an "infrastructure" fast failure.

Every 10 minutes the log gets one line per running leg:

```
[status] wallet pass1 attempt1 | r3/7 triage | sol: done 4f 9m | terra: running 12m ← git diff … | grok: done 2f 8m | opus: done 3f 7m | open P0:0 P1:1 P2:3 fixed 6 | idle=41s cpu=12:07(moving) commits=3
```

Read `idle` and `cpu` together. A large `idle` with `cpu=…(moving)` is a leg mid-build;
`idle` climbing past the limit with `cpu=…(frozen)` is what gets killed.

**There is exactly one stall detector.** The previous version of this skill had two —
an external guard script and one inside the orchestrator — and the one nobody had
hardened false-killed a working leg. Do not arm a second one. If you need a different
threshold, set `STALL_SECS`; do not add a watcher.

## Do not run heavy work beside the review

On one box, review legs and E2E suites contend for CPU and any shared prover. In the
source run this produced three false failures in one night: a unit test that "failed"
under sweep load, a "hung" suite that was debug-mode proving, and an E2E spec dying on
`Deadline expired`. Any failure whose text mentions a timeout or deadline is suspect:
re-run it idle before touching code.

## Finishing: squash, push, then promote

Each leg commits per round as crash recovery; the orchestrator collapses each repo's run
with `${CLAUDE_PLUGIN_ROOT}/scripts/rev-squash.sh --apply` and pushes once. Squash and push are **independent**: a
refused squash is logged (`!!! squash refused for <repo>`) and the push still happens,
because the round commits are real work that CI has to see. If a repo prints
"refusing: … only N unpushed", something was pushed mid-run — leave that history alone.

A repo whose leg never completed is **not** finished: it is skipped (no squash, no
push) and the run ends `COMPLETE WITH FAILURES: <labels>` with a non-zero exit instead
of `ALL PHASES COMPLETE`. Re-run the stack — the resume check skips the legs already
DONE for this session root — before touching those repos by hand.

**Promote out of draft LAST**, and by whether CI can go green, not by position in the
stack:

| State | Action |
|---|---|
| CI structurally cannot pass until the root ships | stay draft, say what it waits on |
| CI can pass; only a merge gate is pending | promote — review starts while the gate waits |

Check `mergeable`, not just `isDraft`: a long run gives the base branch time to move.
Once the root PR needs a human reviewer it is the critical path; say so rather than
generating motion on the consumers.

## Reading the output

Each leg leaves `<ROOT>/<leg>/report.md` and `findings.md`. Findings cluster into
shapes worth naming when you summarise:

- **Tests that cannot fail** — assertions satisfied by the call under test, fixtures
  that only exercise the benign ordering. The single most common P1.
- **Coverage that does not execute** — comparing hashes instead of running the thing.
  Ask for mutation evidence: a test proven to fail when the code is broken.
- **Docs contradicting their own code** — especially a stated precondition a later
  change invalidated.
- **The same defect in N repos** — the seam finding; it usually has one upstream fix.
