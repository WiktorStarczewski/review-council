---
name: rev
description: Multi-model review-and-fix loop run from this session - a panel built at run time from whichever frontier CLIs are installed and signed in (Codex and Gemini) plus configured Claude seats, at their receipted efforts, triaged into a ledger, fixed, verified and committed until rounds stop producing material findings. Use when the user runs /review-council:rev, asks for a review, audit, or check of code changes (a PR, a branch, uncommitted work, a path), after completing any non-trivial implementation, or for a read-only second opinion on a plan, design doc, or prose.
user_invocable: true
---

# rev - multi-model review-and-fix loop

This skill is an executable workflow contract. Follow every applicable step in its stated order. Do not cherry-pick, replace, or improvise around steps. Before omitting a step, record the exact reason it is inapplicable. A run missing any audit, receipt, or final report required by its selected mode is incomplete and must not be described as a Review Council review.

You are the orchestrator. The reviewers are other labs' frontier models plus configured
Claude seats; **they never edit**. You fan out, verify their claims against the source,
dispatch the workhorse, verify the gates, commit, and report. The point is decorrelation: a reviewer
that shares your weights shares your blind spots, so a review you run on your own
work alone is proofreading. Disagreement between labs is the signal worth having.

Keep the independent panel and its receipted efforts. Bound cost by running only the panels
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
roster appends Claude seats - `claude-1`, `claude-2`, … , on the resolved Claude
adapter (`claude` or `agent`), marked `"padded": true` - until there are three, and
sets `"degraded": true` with a one-sentence `degradation`. Those seats are full seats:
they are dealt lenses like any other, so three Claude seats read the diff through three
different lenses. What is lost is decorrelation, not coverage - and losing it is
something you say out loud (see **Report**), never a reason to skip the loop or to read
the diff yourself instead.

## Workhorse

The session model orchestrates. Never stop to ask the user. A cluster is local when its Sites list names one file and at most 3 sites, and the change does not add a mechanism, cross a realm, or change a public contract. Two anchors in one file are two sites. Excluded paths are not sites. The workhorse writes the fix plan whenever it is available. You implement each local cluster. You launch the workhorse for every other cluster. When a panel or assignment is incomplete, fix a local cause you can see. By default, retry on the next higher enforced seat: Luna, then Sonnet, then Sol, then Opus. For an explicit per-review override, record `escalation_overrides` in `$S/state.json` with `rev-state.sh` (for example, `rev-state.sh "$S" 'escalation_overrides={"luna":"sol"}'`); the selected family replaces the default only for matching failures, and an unavailable selected family must not silently fall through. There is no panel-wide replacement cap: each failed assignment may receive one separately bound replacement, so distinct failed assignments in the same panel can all be replaced. Keep each child label unique (`<N>x`, then `<N>x2`, and upward), preserve valid siblings, and record the result. If a replacement fails, finish that assignment yourself in the spirit of its lens and this contract. Do not leave the run waiting, and do not describe orchestrator coverage as a certified seat. You still run the red test, the gates, and the commit. Frontier seats still review the code.

The default writer is `grok-4.7-xhigh` through the Cursor agent CLI on every host, including Codex and Claude Code. A launched writer uses that slug. If it is missing, not signed in, or out of credits, the writer falls through OpenAI Luna, then Anthropic Sonnet, then OpenAI Sol, then Anthropic Opus. Review seats stay on the roster. After the roster exists, resolve once and reuse a valid file. Do not edit it.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-workhorse.py resolve --write "$S/workhorse.json"
```

`family` null means none of that chain is available: do these three jobs in this session, report `Workhorse: unavailable` with the file's `reason`, and use the plan-seat fallback below. Otherwise launch only the recorded `family`, `model`, `effort`, and `adapter`. Effort is `high` when that model offers it. Do not substitute the session model, a frontier reviewer, or a higher effort.

- **Fix plan.** `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-workhorse.py launch --dry-run --session "$S" --task plan`. When the JSON `kind` is `agent`, launch that agent on the prompt path (`review-council:rev-workhorse`) with its workspace set to `REV_ROOT`. When `kind` is `exec`, run the same command without `--dry-run`; it writes `$S/fix-plan.md` and starts in `REV_ROOT`. You do not draft the plan. Exit 4 means the Cursor writer is missing, not signed in, or out of credits: run advance immediately and do not retry that family. Any other non-zero exit, or a plan preparation rejection, gets one identical retry. A rejection of `mandatory source reads exceed repository capacity` or `preparation timed out` is not that retry: read `prepare-diagnostic-<label>.json` and follow the plan-phase recovery. A second failure runs `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-workhorse.py advance --session "$S"`. A printed record is the next family on the chain: retry that task once with it. A non-zero advance means the writer chain is exhausted: write that plan or implement that cluster yourself in the plan contract, then continue. The implementation launch uses the same advance rule.
- **Fix plan review.** When `$S/panel-request.json` exists, skip this workhorse seat and review the plan with the frozen caller roster. Otherwise the default plan seat is `seat` from the file. Adapters `codex` and `claude` launch through `rev-seat.sh`. Adapter `agent` launches `review-council:rev-workhorse-review` on the rendered prompt and is recorded like any other Agent seat. Adapter `cursor-agent` runs `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-workhorse.py launch --session "$S" --task review --prompt <rendered prompt> --out "$S/r<N>p-workhorse.json"`. That review launch follows the fix-plan exit 4 rule. `"plan_seats": "all"` still reviews with the core roster.
- **Implementation.** After the red run, implement a local cluster yourself. For every other cluster: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-workhorse.py launch --dry-run --session "$S" --task implement --cluster <id>`, then the exec form when `kind` is `exec` (it starts in `REV_ROOT`), or `review-council:rev-workhorse` when `kind` is `agent`, with that workspace set to `REV_ROOT`. Then you run the gates, `rev-mutate.sh`, and commit.

Report the family, model, and effort, or the unavailable reason.

## Parse

`/review-council:rev [scope] [rounds] [--read-only]`

| | values | default |
|---|---|---|
| scope | `branch`, `uncommitted`, a path, a PR number or URL, a branch name | `branch` |
| rounds | optional integer minimum override | adaptive |
| `--read-only` | findings only - no fixes, no commits | off |

"use S as the session dir" in the invocation names the session directory
(`/review-council:stack` passes this). Otherwise `S=/tmp/rev-$(date +%s)`.
For a code review associated with an open PR, `S` must resolve outside the reviewed repository.
An unassociated local render may remain inside, but it cannot publish.

## Route

- `REV_ACTIVE` set on entry → refuse: "a review is already running here". Test it
  yourself, first thing (`echo "REV_ACTIVE=${REV_ACTIVE:-unset}"`): `rev-preflight.sh`
  is the only script that checks it, and the read-only panel never runs it. Nothing
  downstream of a review may start another.
- `--read-only`, or the scope is a document (`.md`/`.txt`/`.rst` path, or the user
  named a plan, design doc, or prose) → **Read-only panel** (below).
- Otherwise → read `phases/10-setup.md` and follow **Setup (once)**. The loop is `phases/20-discovery.md`.
- `REV_STACK_LEG=1` → **Stack-leg mode** differences apply (below).

## Phase files

The text above is the core that stays loaded. Seat coverage, audits, and receipts are unchanged. Before a phase, Read exactly that phase file from the `phases` directory next to this skill and follow it. Do not Read the other phase files in the same turn.

| Phase | File |
|---|---|
| setup | `phases/10-setup.md` |
| discovery | `phases/20-discovery.md` |
| triage | `phases/30-triage.md` |
| plan | `phases/40-plan.md` |
| fix, then commit | `phases/50-fix.md`, then `phases/60-verification.md` |
| verification | `phases/60-verification.md` |
| publish | `phases/70-publish.md` |

## Fresh orchestrator

When this skill is invoked from a conversation that already has other work, launch one fresh agent and stop. Its only inputs are the session directory and `$S/state.json`. That agent is the orchestrator. Do not launch another orchestrator from inside it. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-brief.py "$S" --host claude` and Read only the `phase_file` it prints. A session with no `phase` starts at setup.

## Mechanical phases

Render, publish, a CI watch, and close-out are one call, not a series of host turns:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/rev-mechanical.sh publish "$S"
${CLAUDE_PLUGIN_ROOT}/scripts/rev-mechanical.sh ci "$S"
${CLAUDE_PLUGIN_ROOT}/scripts/rev-mechanical.sh closeout "$S"
```

When config sets `host_mechanical_model`, run that call under that model. Keep the strongest model for finding verification and fix planning. Seat models, efforts, coverage, audits, and receipts do not change.
