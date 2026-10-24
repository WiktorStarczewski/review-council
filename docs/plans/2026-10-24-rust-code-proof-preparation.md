# Complete code proof preparation

The 0.7.12 preparer rejects valid Rust module aliases because it adds absent alternate module layouts to frozen proof targets. It also assigns package-library roots to integration-test imports. Separate code proof obligations can exceed the manual repository-read budget even when exact source segments can carry those proofs.

## Required behavior

- Resolve ordinary modules to existing declared layouts, preserving unreadable targets when no valid layout exists.
- Honor inline and explicit-path modules without adding conventional sibling files.
- Keep integration-test crate roots separate from the package library, retaining ambiguity across reachable roots.
- Keep the complete reviewed branch snapshot. Partition diagnostics do not constitute executable scope recovery.
- Deliver every residual code proof obligation through existing byte-bound required source segments. Keep manual read and visible-output limits unchanged.
- Reject unavailable mandatory sources. Bind delivered ranges to original ownership, snapshot blobs and changed-component hashes.
- Regenerate required ranges during snapshot validation so removing a range cannot produce a self-consistent forged manifest.
- Preserve existing plan, numeric, source-context-disabled and provider-capacity behavior.

## Verification

1. Commit regression tests first and obtain intended failing assertions in CI.
2. Implement isolated Rust resolution and code source promotion corrections.
3. Exercise exact bytes, complete scope, omitted segment audit failure and removed-range validation failure.
4. Use one independent normal reviewer under repository AGENTS.md, then resolve actionable P0-P2 findings.
5. Compare both operating-system CI results with frozen release failures; do not claim inherited failures are passing.
6. Prepare a verified fixed runtime before resuming the frozen Bread branch review.
