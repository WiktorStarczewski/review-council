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
- Default code fix loop: minimum **8 rounds**. Explicit round count overrides the
  minimum. `--read-only` and document/plan reviews default to **1 round**, no edits or
  commits, even after reporting findings. Do not turn plain prose into a git diff.
- Reuse a requested session directory; otherwise make one with `mktemp -d
  /tmp/rev-XXXXXX`. Call it `S`. Read any existing ledger before continuing. Keep all
  logs, prompts, reviewer outputs, and ledgers there, away from the reviewed files.

For code, run from the repository root:

```bash
REVIEW_COUNCIL_HOST=codex "$PLUGIN/scripts/rev-preflight.sh" \
  --scope branch --write "$S"
```

Substitute the resolved scope and append `--base <ref>` when specified. This writes
`scope.env`, `files.txt`, `untracked.txt`, and the **probed** `roster.json`. Preflight
refuses empty scopes or shared branches; use a worktree if a code review needs one.
For documents, write absolute paths to `S/docs.txt`, set `REV_REPO` to their root,
and run `roster.sh --probe --write "$S/roster.json"` without git preflight.
Probes and reviews contact the configured providers and consume their usage.

Print the roster and any `degradation` reason before reviewing. Never replace a
missing provider with an imaginary in-process agent. Repeated CLI seats are separate
runs with different lenses, **not** additional labs. Exit 5 means the panel is
unavailable or the configured `min_labs` floor failed; report exclusions and stop.
Configuration is `~/.config/review-council/config.json` (or `REVIEW_COUNCIL_CONFIG`):
`exclude`, `pin`, `claude_seat`, `extras`, and `min_labs` are shared with Claude Code.
See [configuration](https://github.com/WiktorStarczewski/review-council/blob/main/docs/config.md) for the full format.

Read repository instructions, inspect the diff and consumers, and record existing
failures in `S/baseline.md` using relevant project checks. Do not require unrelated
checks for prose. Initialize `findings.md` and `rejected.md` without overwriting a
resumed ledger. Record state via `rev-state.sh "$S" key=value ...`:
`round`, `min_rounds`, `phase`, `seats` (JSON array), `dropped`, `open.P0` through
`open.P3`, and `fixed`. State updates are sequential.

## Run each round

Read the roster; select every non-extra seat plus extras whose `round` matches.
Rotate lenses across seats; round 1 gives every seat simplicity. With more seats than
lenses, repeat lenses. Cover all listed lenses and major changed files across the run.

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

Generate a prompt for each seat:

```bash
"$PLUGIN/scripts/rev-prompt.sh" "$S" "$ROUND" "$SEAT" "$LENS" "$EMPHASIS"
```

Add `--vacuity` whenever tests are touched. It asks which production regression
would actually make each test fail. Add `--read-only "$S/docs.txt"` for documents
only; read-only **code** still uses the normal diff prompt. PR descriptions are not
included by default: let reviewers question the design before seeing its rationale.

Launch independent seats concurrently using the available shell execution tools:

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

Before fixing after round 1, or after new P0/P1 findings or a new root-cause cluster,
write `S/fix-plan.md`: accepted findings, proposed changes, existing components to
reuse, risks, and falsifiable tests. If there are no accepted fixes, skip this gate.
Have the same seats review it using `rev-prompt.sh ... --plan "$S/fix-plan.md"` and
lenses `plan-completeness`, `plan-soundness`, `plan-simplicity`, `plan-tests`. Use a
round label such as `1-plan` to preserve the code-review artifacts. Verify and address
plan objections before editing. Plan passes do not count toward minimum rounds.

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

For fix loops, continue beyond the minimum while new P0/P1 findings, nontrivial last
round fixes, open P0/P1 findings, or unreviewed lenses/files remain. Completion needs
the minimum rounds, two consecutive rounds with no new P0/P1, no open P0/P1, and gates
at baseline or better. Respect user stops and resource limits; report incomplete
coverage honestly instead of silently lowering the minimum. Read-only panels stop
at the requested round count and report findings without requiring fixes.

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
