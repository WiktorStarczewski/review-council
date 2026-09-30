# Review cost first wave

Implement the approved cost recommendations without reducing production review coverage, changing the roster, or weakening evidence certification.

The design extends the existing scripts. Usage remains observational, all recovery decisions stay with the existing state and receipt machinery, and local status collection never invokes a provider. Development uses local regression fixtures and a bounded four-call Terra benchmark.

## Task 1: trustworthy usage

Files: `plugins/review-council/scripts/rev-profile.py`, a usage helper if needed, and dedicated usage tests.

Interface: preserve existing CLI and normalized totals; add explicit host-log input and separate host attribution. Reasoning is a subset of output. Streaming assistant blocks are deduplicated by message identity. Terminal totals and per-message totals are alternative representations of one stream, never additive. Preserve metered failures and unknown costs.

- [x] Add failing cases for duplicate assistant blocks, repeated log input, cache creation/read normalization, reasoning detail, mixed host work, and malformed records.
- [x] Implement aggregate-only host accounting and native Agent usage support. Keep whole host envelopes separate from session-associated operations and reviewer totals.
- [x] Run `plugins/review-council/tests/run-tests.sh profile` and the new focused cases. Expected: all assertions pass; malformed data stays disclosed.

## Task 2: reject unusable launches early

Files: `scripts/rev-preflight.sh`, `scripts/rev-contract-check.py`, `scripts/lib/roster.py`, and dedicated preflight/probe tests under the plugin.

Interface: static replay precedes paid probes. The existing exact-roster, provider-version-bound replay remains authoritative after probe. No static receipt earns review coverage. Availability probes use supported reviewer isolation controls without changing authentication or model/effort.

- [x] Add failing public-entrypoint tests proving a broken local contract spends zero probes and that healthy input still reaches the authoritative check.
- [x] Add failing probe command/environment tests for isolation and retained authentication.
- [x] Implement static precheck and probe isolation with existing helpers and cache invalidation.
- [x] Run focused preflight, roster and provider-contract cases. Expected: scope/config failures stay early, roster identity and exit semantics remain unchanged.

## Task 3: compact active prompts and orchestration

Files: `scripts/rev-prompt.sh`, small session helpers, both host skills, dedicated prompt/helper tests, docs, and test-cost metadata.

Interface: active-mode compilation preserves exact evidence fragments and all active proof, source, refutation, budget and output obligations. Session briefing is a bounded read-only view of current state and artifact identities, never a replacement receipt. Watching invokes only local status collection, emits scheduled ten-minute relays and meaningful state changes, and requires terminal handles to be collected independently.

- [x] Add failing prompt cases for adapter-specific source instructions, clean-room ordering, window/chunk modes and incomplete-proof output.
- [x] Compile mode-specific contract text and derive read/call budgets from existing constants.
- [x] Add failing session briefing/watch cases for exact artifact labels, pending versus failed seats, missing results, scheduled relays and changed state.
- [x] Implement small local helpers and document their use in both host workflows.
- [x] Run focused prompt and helper cases. Expected: exact evidence hash and assignments survive; status never certifies completion or spends provider calls.

## Integration and delivery

- [x] Register every new shell test in `test-costs.tsv` and measure deterministic prompt/brief sizes.
- [x] Run `python3 scripts/verify-review-council.py` on the corrected final material tree. The gate includes shell tests, Python tests and plugin/marketplace validators; do not separately repeat its shell suite or edit source while it runs.
- [x] Run the user-selected four-call Terra benchmark instead of the earlier single-call development check. Inspect every finding, retain valid proofs and costs, and report that this does not review the implementation or provide full Council certification.
- [x] Prepare coherent changes and the feature-branch draft PR as the repository author for delivery from the verified tree. Do not release or change installed production configuration.

## Review focus

Check duplicate usage identities across files, mixed host attribution, missing terminal receipts, reasoning/output overlap, static-versus-authoritative replay boundaries, startup authentication, inactive-mode removal, source citation obligations, ten-minute status cadence and incomplete seat results.

## Review

Focused implementation is complete. The default evidence fixture renders 1135 to 991 words for Codex and 1097 to 985 words for Claude; legacy prompts render 1030 to 831 and 1036 to 869 words respectively. These are prompt-word reductions on one deterministic fixture, not measured token costs or recall equivalence. A four-seat state briefing renders 32 words and 358 bytes. Integration verification remains pending. Higher-risk proposals such as quota sibling reuse, schedule cuts, reviewer resumption, changed proof semantics and roster/effort changes require a later measured design.

The first integration run exposed an outdated probe mock; its signature and environment checks were corrected. The resumed gate passed all 90 Python tests and all plugin/marketplace validators. A later session permission change denied `/bin/ps` in the process-group cancellation test. The incomplete gate was stopped, and the required assertion remains intact. Delivery and the one paid development check await restored session permissions. No production configuration, release, commit or remote branch was changed.

September 30 continuation: Full access is effective and all four paired Terra executions completed. Both versions found all four planted fixture defects with zero false positives. Estimated credits fell 6.8% and provider time fell 14.7%; the bounded sample does not establish production savings or quality equivalence. All 145 Python tests pass. Final integration verification and feature-branch delivery remain.

Final verification: 351 shell cases, 4,683 assertions, all 147 Python tests and all three validators passed. The retained receipt is bound to tree `2c6b2c2e818d41787a47d16c7a0628084e878f4de77e10253f99e66b2077b921`. Only task and plan completion records change after this gate. Feature delivery is a draft PR; full Council implementation review remains pending.
