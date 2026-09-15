# Pull-request review publication

Every completed code review that has an associated open GitHub pull request publishes
one `COMMENTED` review before the run reports success. Reviews without an associated
open PR do not post. Document reviews do not post.

The renderer owns the exact Markdown structure. Do not hand-build, reorder, rename,
remove, or add sections in `pr-review.md`. It also writes
`pr-review-target.json`, which freezes the associated PR, reviewed merge base, observed
PR base tip, reviewed head and tree, footer date, exact body hash, and exact normalized
GitHub repository set.

Set `PLUGIN_ROOT` to the plugin root already resolved by the host: `PLUGIN` on Codex
or `CLAUDE_PLUGIN_ROOT` on Claude Code.

## Prepare the input

Write `$S/pr-review.json` with this exact shape:

```json
{
  "verdict": {
    "headline": "One bold sentence with the merge verdict.",
    "detail": "One sentence explaining blockers or decisions left to the author."
  },
  "panels": 3,
  "rejected": 2,
  "fixed_in": {
    "label": "owner/repo#123",
    "url": "https://github.com/owner/repo/pull/123"
  },
  "gates": "7/7 green, 240 tests",
  "panel": ["GPT-5.6 Sol", "GPT-5.6 Terra", "Claude Opus 5", "Claude Sonnet 5"],
  "decisions": [
    {
      "title": "Short question or decision claim",
      "location": {
        "label": "src/file.rs#L10-L18",
        "url": "https://github.com/owner/repo/blob/<head-sha>/src/file.rs#L10-L18"
      },
      "detail": "Evidence, tradeoff, and the concrete choice for the author."
    }
  ],
  "fixes": [
    {
      "severity": "P1",
      "summary": "One-line description of the behavior now fixed",
      "commit": {
        "label": "abc1234",
        "url": "https://github.com/owner/repo/commit/<full-sha>"
      }
    }
  ],
  "verified_sound": [
    "One important property checked directly against the source"
  ],
  "coverage": [
    "Panels: simplicity · risk discovery · final verification",
    "Gates on the fix tip: format, lint, full test suite (240 tests)"
  ]
}
```

Rules:

- `decisions` contains every `DEFERRED` item or other material design choice left to
  the author. Use an empty list when none remain. Keep the section.
- `fixes` contains one row per fixed finding. Reuse a commit link when one commit
  closes several findings. Use an empty list when no fixes were required. Keep the
  section and table.
- `rejected` counts rejected findings. The total finding count is calculated from
  fixes, decisions, and rejections.
- `panels` counts completed panels, not reviewer seats or provider calls.
- `panel` names the actual core models from `roster.json` in roster order. Include
  only models that produced valid results. The fixed suffix says every listed model
  ran at maximum effort, so do not list a lower-effort seat.
- Omit `fixed_in` when the fixes are on the reviewed PR. Include it only when they
  landed in a separate PR, as in the canonical review.
- Use immutable pushed commit links and source links pinned to the reviewed head SHA.
  The renderer rejects other link types, and publication binds same-PR links to a
  reviewed GitHub remote and commit ancestry.
- Keep every string on one line. Put depth in the decision details, verified-sound
  bullets, and coverage bullets while preserving the renderer's fixed structure.
- Free prose may use balanced Markdown code spans. Raw HTML outside those spans is
  escaped, unmatched backticks are rejected, and URL values are never rewritten.
- State measured gates and test counts. Do not use an adjective in place of a result.

## Render, inspect, and publish

Run:

```bash
python3 "$PLUGIN_ROOT/scripts/rev-pr-review.py" render "$S"
```

Read `$S/pr-review.md` and check every claim, count, model, link, commit, gate, and
test total against the completed session and pushed head. Do not edit the Markdown.
Correct `pr-review.json` and render again when anything is wrong.

For an associated PR, render resolves the branch and base recorded by preflight,
pins every GitHub CLI call to `github.com`,
requires an open PR at the reviewed local head, and freezes that PR, branch, base,
head, tree, date, and body hash in the target envelope. Rendering fails when the
repository has staged, unstaged, or untracked bytes outside the exact active session
directory because those bytes are absent from the PR head. A normal or read-only
review therefore renders only after its final authorized push. Stack legs may render
their clean unpushed reviewed head because the stack performs the guarded final
transition below.

For a normal or read-only code review, publish before setting `phase=done` or writing
`report.md`:

```bash
python3 "$PLUGIN_ROOT/scripts/rev-pr-review.py" publish "$S"
```

When `NO_PUSH=1`, render and inspect the review but do not post it. Rendering writes a
local unassociated target envelope without calling GitHub. The publisher and stack
finalizer enforce the no-push gate before making any GitHub call. A later authorized
publication binds that envelope only when its reviewed scope, clean tree, and pushed
head still match the scoped open PR.

The publisher reads the saved Markdown without rerendering it, verifies its body hash,
and rebinds the durable target to the reviewed session scope. It revalidates the PR
identity, open state, branch, base branch, reviewed merge base, and head. A forward
move of the base tip is accepted only when the merge base remains the reviewed commit.
PR discovery is restricted to repositories named by the reviewed checkout's GitHub
remotes. The exact normalized repository set is frozen at render time, and adding,
removing, or repointing one of those remotes requires a fresh render. Ambient GitHub
CLI repository selection or copied target state therefore cannot redirect the post.
Accepted remotes are GitHub HTTPS, git protocol, SCP-style SSH, explicit-port SSH on
`github.com`, and GitHub's documented `ssh.github.com:443` SSH-over-HTTPS form.
Under a repository-local lock, it reads and updates the rendered body and target,
checks all existing reviews, then revalidates the frozen open head before choosing a
duplicate or creating a review. After creation it revalidates the head again before
reporting success. Closure or merge before the POST becomes the exact no-open-PR skip,
including closure during stack head propagation. Closure after the POST remains a
retryable ambiguity. It
treats only an exact `COMMENTED` review body on the reviewed commit as idempotent
success. The API request sets `commit_id` to the frozen head and `event` to `COMMENT`,
then verifies the returned body, state, and commit. A real
no-PR association skips cleanly; missing session scope or artifacts fail closed.

Any other nonzero publish exit leaves the PR review incomplete. Preserve
`pr-review.json`, `pr-review.md`, and the frozen target, then atomically write
`incomplete.md` with the failure and exact retry command. Direct success or a clean
skip clears stale publication failure state. Stack publication retains it until the
done state and final report promotion both succeed, including on a no-push retry.

In `REV_STACK_LEG=1`, render and inspect the body but do not publish it. The stack
leg records `phase=stack-ready` and writes `stack-report.md`, not `phase=done` or
`report.md`. The stack records the latest ready session for each canonical repository.
After pushes, it finalizes and publishes each successful repository even when a sibling
repository failed, while the overall stack still exits nonzero. When a squash changes
commit identity, guarded final rendering first proves that the pushed aggregate commit
has the inspected tree and reviewed merge base, verifies the frozen structured input
and body, and maps decision
blob links plus reviewed-PR fix links to that aggregate SHA. Fix links covered by
`fixed_in` remain pinned to their separate PR. The structured input remains
immutable. The body is written before the target envelope, which is the commit marker;
publication rejects a mismatched pair and an exact retry completes an interrupted update.
The post-squash body is rendered from the immutable input with the frozen date.
Only the latest completed session for each repository is finalized and published. A
pushed retry derives finalization from the frozen target and current head, so recovery
does not depend on a marker written after history changes.
Stack no-push and no-squash settings are exported to every child leg, including values
assigned by the stack config.
Before every real push, the stack validates the authoritative session, clean reviewed
tree, merge base, frozen body and target, repository set, and push endpoint without
calling GitHub. It then pushes the captured commit to the captured literal URL and
destination ref, so later branch or remote configuration changes cannot widen or
redirect the push.
The finalizer tolerates brief GitHub head propagation only while the visible head is
the frozen head or its ancestor. After successful publication or an explicit no-push
skip, the stack sets `phase=done` before promoting `stack-report.md` to `report.md`.
The two artifacts jointly form the completion receipt; either one alone is incomplete
and remains retryable. The stack clears a stale publication failure receipt only after
that joint completion succeeds.
For every completed repository, the push must succeed before finalization starts.
Read the final body before reporting success. A push, tree or merge-base check,
finalization, or publication failure keeps the ready receipt unpromoted.
