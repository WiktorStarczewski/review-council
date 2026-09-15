# Pull-request review publication

Every completed code review that has an associated open GitHub pull request publishes
one `COMMENTED` review before the run reports success. Reviews without an associated
open PR do not post. Document reviews do not post.

The renderer owns the exact Markdown structure. Do not hand-build, reorder, rename,
remove, or add sections in `pr-review.md`.

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
- Keep every string on one line. Put depth in the decision details, verified-sound
  bullets, and coverage bullets while preserving the renderer's fixed structure.
- State measured gates and test counts. Do not use an adjective in place of a result.

## Render, inspect, and publish

Run:

```bash
python3 "$PLUGIN_ROOT/scripts/rev-pr-review.py" render "$S"
```

Read `$S/pr-review.md` and check every claim, count, model, link, commit, gate, and
test total against the completed session and pushed head. Do not edit the Markdown.
Correct `pr-review.json` and render again when anything is wrong.

For a normal or read-only code review, publish before setting `phase=done` or writing
`report.md`:

```bash
python3 "$PLUGIN_ROOT/scripts/rev-pr-review.py" publish "$S"
```

The publisher resolves the current branch's open PR, skips cleanly when none exists,
checks all existing PR reviews for an identical body, and posts with
`gh pr review --comment`. An identical body is success without a duplicate post.

Any other nonzero exit leaves the PR review incomplete. Preserve `pr-review.json` and
`pr-review.md`, write `incomplete.md` with the failure and retry command, and do not
set `phase=done` or write the success receipt.

In `REV_STACK_LEG=1`, render and inspect the body but do not publish it. The stack
publishes completed session bodies only after its final squash and push phase. A
stack publication failure makes the stack incomplete.
