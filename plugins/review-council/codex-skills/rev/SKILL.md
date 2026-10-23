---
name: rev
description: Convene the Review Council for independent multi-model review, adversarial review panels, or iterative council review and fixes. Use when the user asks for review-council, a council review, or multiple model/provider opinions on code, a PR, a plan, or documents. Supports branch, uncommitted, path, PR, read-only, and round-count scopes.
---

# Review Council for Codex

This skill is an executable workflow contract. Follow every applicable step in its stated order. Do not cherry-pick, replace, or improvise around steps. Before omitting a step, record the exact reason it is inapplicable. A run missing any audit, receipt, or final report required by its selected mode is incomplete and must not be described as a Review Council review.

You are the orchestrator. Independent CLI reviewers inspect the scope; you verify
claims against evidence, dispatch the workhorse to fix actionable defects within the user's scope, and repeat.
Agreement is a signal, never proof. Preserve the user's requested scope and prior
authorization. A request for report-only review remains report-only. This skill does
not authorize pushing, rewriting history, or changing unrelated files. The completion
contract authorizes only the canonical `COMMENTED` PR review for an associated open PR.
Do not start a council automatically after unrelated implementation work.

## Workhorse

The session model orchestrates. Never stop to ask the user. A cluster is local when its Sites list names one file and at most 3 sites, and the change does not add a mechanism, cross a realm, or change a public contract. Two anchors in one file are two sites. Excluded paths are not sites. The workhorse writes the fix plan whenever it is available. You implement each local cluster. You launch the workhorse for every other cluster. When a panel or assignment is incomplete, fix a local cause you can see. By default, retry on the next higher enforced seat: Luna, then Sonnet, then Sol, then Opus. For an explicit per-review override, record `escalation_overrides` in `$S/state.json` with `rev-state.sh` (for example, `rev-state.sh "$S" 'escalation_overrides={"luna":"sol"}'`); the selected family replaces the default only for matching failures, and an unavailable selected family must not silently fall through. There is no replacement-attempt cap while eligible configured seats remain: after the exact execution retry, continue through the configured escalation chain until an attempt returns valid proof or the chain is exhausted. Give every attempt a unique child label (`<N>x`, then `<N>x2`, and upward), preserve valid siblings, and record each result. On every `rev-workhorse.py escalate` call, pass `--seat` for the most recently failed executor, including a failed replacement, so the chain advances; keep the child bound to the original failed assignment. Never use a failed child as the parent of another attempt. If the chain is exhausted without valid proof, finish that assignment yourself in the spirit of its lens and this contract. Do not leave the run waiting, and do not describe orchestrator coverage as a certified seat. You still run the red test, the gates, and the commit. Frontier seats still review the code.

The default writer is `grok-4.7-xhigh` through the Cursor agent CLI on every host, including Codex and Claude Code. A launched writer uses that slug. If it is missing, not signed in, or out of credits, the writer falls through OpenAI Luna, then Anthropic Sonnet, then OpenAI Sol, then Anthropic Opus. Review seats stay on the roster. After the roster exists, resolve once and reuse a valid file. Do not edit it.

```bash
REVIEW_COUNCIL_HOST=codex python3 "$PLUGIN/scripts/rev-workhorse.py" resolve --write "$S/workhorse.json"
```

`family` null means none of that chain is available: do these three jobs in this session, report `Workhorse: unavailable` with the file's `reason`, and use the plan-seat fallback below. Otherwise launch only the recorded `family`, `model`, `effort`, and `adapter`. Effort is `high` when that model offers it. Do not substitute the session model, a frontier reviewer, or a higher effort.

- **Fix plan.** `python3 "$PLUGIN/scripts/rev-workhorse.py" launch --dry-run --session "$S" --task plan`. When the JSON `kind` is `agent`, launch that agent on the prompt path (`review-council:rev-workhorse`) with its workspace set to `REV_ROOT`. When `kind` is `exec`, run the same command without `--dry-run`; it writes `$S/fix-plan.md` and starts in `REV_ROOT`. You do not draft the plan. Exit 4 means the Cursor writer is missing, not signed in, or out of credits: run advance immediately and do not retry that family. Any other non-zero exit, or a plan preparation rejection, gets one identical retry. A rejection of `mandatory source reads exceed repository capacity` or `preparation timed out` is not that retry: read `prepare-diagnostic-<label>.json` and follow the plan-phase recovery. A second failure runs `python3 "$PLUGIN/scripts/rev-workhorse.py" advance --session "$S"`. A printed record is the next family on the chain: retry that task once with it. A non-zero advance means the writer chain is exhausted: write that plan or implement that cluster yourself in the plan contract, then continue. The implementation launch uses the same advance rule.
- **Fix plan review.** When `$S/panel-request.json` exists, skip this workhorse seat and review the plan with the frozen caller roster. Otherwise the default plan seat is `seat` from the file. Adapters `codex` and `claude` launch through `rev-seat.sh`. Adapter `agent` launches `review-council:rev-workhorse-review` on the rendered prompt and is recorded like any other Agent seat. Adapter `cursor-agent` runs `python3 "$PLUGIN/scripts/rev-workhorse.py" launch --session "$S" --task review --prompt <rendered prompt> --out "$S/r<N>p-workhorse.json"`. That review launch follows the fix-plan exit 4 rule. `"plan_seats": "all"` still reviews with the core roster.
- **Implementation.** After the red run, implement a local cluster yourself. For every other cluster: `python3 "$PLUGIN/scripts/rev-workhorse.py" launch --dry-run --session "$S" --task implement --cluster <id>`, then the exec form when `kind` is `exec` (it starts in `REV_ROOT`), or `review-council:rev-workhorse` when `kind` is `agent`, with that workspace set to `REV_ROOT`. Then you run the gates, `rev-mutate.sh`, and commit.

Report the family, model, and effort, or the unavailable reason.

## Phase files

The text above is the core that stays loaded. Seat coverage, audits, and receipts are unchanged. Before a phase, Read exactly that phase file from the `phases` directory next to this skill and follow it. Do not Read the other phase files in the same turn.

| Phase | File |
|---|---|
| setup | `phases/10-setup.md` |
| discovery | `phases/20-discovery.md` |
| triage, plan, fix, verification | `phases/30-triage.md` |
| publish | `phases/70-publish.md` |

## Fresh orchestrator

When this skill is invoked from a conversation that already has other work, launch one fresh agent and stop the parent turn. Its only inputs are the session directory and `$S/state.json`; that agent owns the review through terminal state. Do not launch another orchestrator from inside it. A new run starts at `phases/10-setup.md`. Run `python3 "$PLUGIN/scripts/rev-brief.py" "$S" --host "${REVIEW_COUNCIL_HOST:-codex}"` and Read only the `phase_file` it prints. Every completed command or seat task is a continuation signal: refresh status, preserve its result, apply the matching retry or replacement path, and continue the phase. Do not return control while seats, required assignments, or a later authorized phase remain. A user pause or an explicit external blocker is the only reason to stop before terminal state.

## Mechanical phases

Render, publish, a CI watch, and close-out are one call, not a series of host turns:

```bash
"$PLUGIN/scripts/rev-mechanical.sh" publish "$S"
"$PLUGIN/scripts/rev-mechanical.sh" ci "$S"
"$PLUGIN/scripts/rev-mechanical.sh" closeout "$S"
```

When config sets `host_mechanical_model`, run that call under that model. Keep the strongest model for finding verification and fix planning. Seat models, efforts, coverage, audits, and receipts do not change.
