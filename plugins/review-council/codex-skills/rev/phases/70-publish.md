## Finish

Adaptive completion requires a full four-bundle verification panel after discovery
or the latest nontrivial fix, no new or open P0/P1 findings, no material change left
unreviewed, and gates at baseline or better.
Immediately before finishing with a reused combined panel, rerun
`python3 "$PLUGIN/scripts/rev-evidence.py" current-coverage "$S"` and require
`eligible: true`. A failed final check requires fresh verification before completion.

Only numeric mode continues past its requested minimum while any of these hold: the
last numbered code panel produced a new P0/P1; the last numbered panel's fixes were
nontrivial; any P0/P1 remains open; or a lens or major changed file remains unreviewed.
Numeric mode stops only after the requested minimum numbered code panels ran, two
consecutive numbered code panels produced no new P0/P1, no P0/P1 remains open, and
gates are at or better than baseline. Plan panels do not count as numbered code panels.
Respect user stops and resource limits; report incomplete coverage honestly. Read-only
panels stop at the requested panel count and report findings without requiring fixes.

After every panel, run `rev-profile.py "$S"` and report completed calls, processed
tokens, prompt words, and provider cost when available. Current-session completion
and finding yield require a schema-valid result with a successful exit receipt. Only
exact hashed receiptless results recorded in a versioned legacy roster policy may omit
one. Usage-bearing failed attempts remain metered. Report the profiler's core-roster signature with every measurement. Treat a mixed-roster marker as a comparison boundary
for provider tokens, cost, elapsed time, and finding yield.
Prompt generation warns above
1,800 words for code and 3,000 words for plans; investigate the repeated context
instead of silently truncating evidence.

Do not push unless the user authorized it, and never squash review commits. Push only
the authorized branch. In `REV_STACK_LEG=1`, never push; the stack controls
it. If blocked in a headless leg, record `phase=blocked` and exit without
a completion receipt; do not guess approval or report success.

Before completing any code review, read `$PLUGIN/docs/pr-review.md` and follow it
exactly. Write `S/pr-review.json`, render and inspect `S/pr-review.md`, and publish it
as a `COMMENTED` GitHub PR review. This applies to normal and read-only code reviews.
A branch with no associated open PR skips cleanly. Document reviews do not post. In
`REV_STACK_LEG=1`, prepare and render the body but leave guarded finalization, final
rendering, and publication to the stack after its final push. A completed
leg sets `phase=stack-ready` and writes `S/stack-report.md`, not `phase=done` or
`S/report.md`; the stack promotes the ready receipt only after publication. A required
publication failure writes
`incomplete.md` and blocks `phase=done` and `report.md`.
When `NO_PUSH=1`, render and inspect the body but let the publisher's no-push gate
skip every external GitHub call.

After publication succeeds or cleanly skips, set `phase=done` and write `S/report.md`
with scope/base, actual roster and degradation, the workhorse family, model, and effort or `Workhorse: unavailable` and the reason, rounds/lenses,
accepted/rejected/deferred findings and evidence, changes/commits, baseline/final
gates, and remaining limitations. Outside stack-leg mode, write `report.md` only for
a completed review. In stack-leg mode, put the same content in `stack-report.md` and
leave its promotion to the stack. Interrupted/blocked
runs write `incomplete.md`. End with the substantive results and report path.
