---
name: stack
description: Run Review Council across an explicitly requested stack of dependent repositories or PRs, with per-repository passes, cross-repository seam review, and a final completeness critic. Use when the user requests a council stack or coordinated multi-repository council reviews.
---

# Review Council stack for Codex

Resolve `PLUGIN` two directories above this loaded skill. Read the sibling
`rev/SKILL.md` for the review contract. The shared runner launches headless Codex
legs, waits for receipts, tracks activity and process-tree CPU before declaring a
stall, and resumes from the same session root and ledger.

1. Resolve the repositories, branches, dependency order, rounds/passes, and premises
   from the user and current context. Prepare isolated worktrees if needed. Inspect
   the relevant instructions and existing changes. Do not switch dirty checkouts.
2. Create a concrete config from `PLUGIN/scripts/stack.example.sh`, with `legs()`
   containing `run_leg <absolute-repo-path> <round-count> <label> <premise>` in dependency
   order. Use unique, simple labels and quote shell data properly. The config is an
   executable shell file: inspect it before sourcing it. Set `PASSES`, `SEAM_REPO`,
   and `CRITIC_REPO` to reflect the request. Omit optional phases only deliberately.
   Existing numeric round counts explicitly select the legacy numbered schedule.
   Numeric legs may continue past the requested minimum under the numeric completion
   rules in `rev`; plan panels do not count toward that minimum. These counts do not
   opt a leg into the direct adaptive default.
3. Set `REVIEW_COUNCIL_HOST=codex`. Default `NO_PUSH=1 NO_SQUASH=1` keeps changes local
   and history intact. Set either to `0` only with the user's prior authorization.
   Existing Claude configs may set these explicitly, so inspect and adapt them.
   This skill does not grant publication or history-rewrite permission.
4. Run `roster.sh --brief` under the Codex host and show any degradation. No usable
   provider is a blocker. Exit 5 is retryable: retain the session and use the bounded
   attempt loop. Exit 6 is permanent: relay the one-line reason verbatim, fail that
   leg, and do not retry the same contract. Each leg performs its own preflight and
   probes.
5. Launch the runner with a unique root and log:

   ```bash
   REVIEW_COUNCIL_HOST=codex NO_PUSH=1 NO_SQUASH=1 \
     ROOT="$SESSION_ROOT" LOG="$SESSION_ROOT/stack.log" \
     "$PLUGIN/scripts/stack.sh" "$CONFIG"
   ```

   It detaches and prints paths. Follow the log, per-leg `run.log`, and
   `rev-status.sh <leg-session>` with bounded waits. Remain engaged through completion
   unless the user explicitly wants a background handoff. Never nest a stack inside
   `REV_ACTIVE` or `REV_STACK_LEG`. A retry uses the same root and logs.

Codex legs use `workspace-write`, network access for reviewer provider calls, and
write access to the session root. They inherit the configured Codex model. They do
not bypass the sandbox. If a gate or nested CLI needs unavailable permissions,
report the concrete failure; do not change to unrestricted execution implicitly.
Legs may fix within the requested review scope; they never squash or push themselves.

Inspect completion receipts, not just process exit codes. A missing `report.md`, a
failed leg, or `COMPLETE WITH FAILURES` means the stack is incomplete. Never label a
partial stack clean. Summarize per-repository results, seam findings, critic findings,
actual provider coverage, tests, commit/publication status, and the session-root path.
