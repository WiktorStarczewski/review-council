---
name: stack
description: Run Review Council in Cursor across an explicitly requested dependency stack of repositories or PRs, including per-repository passes, seam review and a final completeness critic.
---

# Review Council stack for Cursor

Resolve `PLUGIN` to the plugin directory two levels above the directory containing
this loaded `SKILL.md`. Set `REVIEW_COUNCIL_HOST=cursor` on every runner invocation.
Read `$PLUGIN/cursor-skills/rev/SKILL.md` and its complete bundled review workflow,
then read and follow `$PLUGIN/docs/cursor-stack-workflow.md` in full.

Use this package's `scripts/stack.sh`. It launches Cursor CLI orchestrator legs
that load this package's Cursor rev entry; it never falls through to Claude Code
or Codex. Keep the default `NO_PUSH=1 NO_SQUASH=1` unless the user already authorized
changing them. Missing Cursor CLI access or a bundled workflow is a visible blocker,
not permission to switch hosts. Inspect ready receipts and publication results
before reporting completion.
