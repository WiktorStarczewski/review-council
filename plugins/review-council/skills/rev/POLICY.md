## review-council - standing rules

- Any request to review, audit, or check code - a PR, a branch, uncommitted work, a path - runs through `/review-council:rev`. A plan, design doc, or prose goes through the same skill with `--read-only`.
- A change spanning several repos' PRs goes through `/review-council:stack`.
- Never substitute your own reading of the diff for the panel. A reviewer sharing your weights shares your blind spots; that is why the panel is other labs. If the panel could not run, say so - never report the change as reviewed.
- A panel short of labs is padded with extra Claude seats and reported as degraded. Exact configuration conflicts refuse permanently; temporary provider shortages refuse only when a strict floor requires them.
- Reviewers never edit. The resolved workhorse writes the fix plan and implements every cluster that is not local. You implement a local cluster: one file, at most 3 sites, and no new mechanism, realm, or public contract. You verify and commit.
- After any review, apply the fixes for every actionable finding without waiting to be asked. A design decision is the smallest change that serves the named consumer. Record it in the ledger and continue. Never stop to ask the user.
- Verify every finding against the source before acting on it. Rejecting a wrong finding is a valid outcome; record it with its reason.
- While a review runs, relay each status line to the user as-is, plus at most one sentence of context. Arm the 10-minute wake only when `status_tick` is true.
- Preserve full discovery and verification panels at the configured effort. Bound cost with adaptive stopping, compact decision digests, and a usage report after every panel.
- Treat `/review-council:rev` as an executable workflow contract: follow every applicable step in order, name why any step is inapplicable, and never claim council review without its required receipt.
