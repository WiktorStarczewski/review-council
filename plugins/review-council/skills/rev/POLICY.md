## review-council — standing rules

- Any request to review, audit, or check code — a PR, a branch, uncommitted work, a path — runs through `/review-council:rev`. A plan, design doc, or prose goes through the same skill with `--read-only`.
- A change spanning several repos' PRs goes through `/review-council:stack`.
- Never substitute your own reading of the diff for the panel. A reviewer sharing your weights shares your blind spots; that is why the panel is other labs. If the panel could not run, say so — never report the change as reviewed.
- A panel short of labs is padded with extra Claude seats and still runs — reported as degraded, with the roster's reason, never silently.
- Reviewers never edit. They read, and they return findings; only you fix.
- After any review, apply the fixes for every actionable finding without waiting to be asked. Ask only when a finding needs a design decision, and name the ambiguity.
- Verify every finding against the source before acting on it. Rejecting a wrong finding is a valid outcome; record it with its reason.
- While a review runs, relay each 10-minute status line to the user as-is, plus at most one sentence of context.
- Token cost and latency are not concerns: never shorten the loop, lower an effort tier, or drop a seat to save tokens.
