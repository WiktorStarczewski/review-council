---
name: rev
description: Convene Review Council in Cursor for independent multi-model review and verified fixes. Use when the user requests review-council, a council review, or multiple model opinions on a branch, PR, uncommitted change, path, plan or document.
---

# Review Council for Cursor

Resolve `PLUGIN` to the plugin directory two levels above the directory containing
this loaded `SKILL.md`. Keep that absolute path for the whole review. Set
`REVIEW_COUNCIL_HOST=cursor` on every runner invocation, starting with preflight.

Read and follow `$PLUGIN/docs/cursor-review-workflow.md` in full before running
anything. The package builder derives that contract from the canonical review
workflow with explicit Cursor host bindings. Its phase order, evidence, receipts,
retry limits, scope, fix and publication requirements all apply.

Use this package's scripts and schema. Native Claude Agent seats are unavailable
on the Cursor host. An optional Grok seat uses the qualified `cursor-sdk` transport
through `rev-seat.sh`; selecting a host never adds it to the roster. If the bundled
workflow is absent, stop with an incomplete installation. Do not substitute an
installed skill from another host or invent a shorter review protocol.
