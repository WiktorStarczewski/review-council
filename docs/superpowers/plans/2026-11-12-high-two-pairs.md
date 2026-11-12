# HIGH: two Sol and two Opus

**Goal:** Change the shared HIGH preset to two Sol reviewers and two Opus reviewers. ECO remains four Luna reviewers. Preserve current effort/availability rules, explicit per-review overrides and initialized frozen rosters.

**Approach:** Reuse existing repeated Codex model selectors and `claude_seats: 2`, which already creates `opus` and `opus-2`. Do not broaden the public `claude_models` validation merely to repeat Opus. Make existing HIGH pair substitution account for every required seat name rather than only one name per family. Keep legacy explicit HIGH configurations compatible.

- [ ] Add regression coverage for the new preset on every host, healthy four-seat naming, two missing Opus substitutions, two missing Sol substitutions, partially missing seats, explicit exclusions and legacy mixed-family HIGH behavior. Prove intended failures before implementation.
- [ ] Implement the preset and count-aware substitution once in shared code. Update Pi policy, canonical setup phases, generated Pi phases, user-facing HIGH documentation and version 0.9.4 metadata. Keep default/ECO and recovery/workhorse policies unchanged. Pass focused tests and generated-contract drift checks.
- [ ] Obtain one independent normal review (no Council self-review), pass exact-head full/package gates, squash merge, publish signed 0.9.4 and install with backup and identity checks. New reviews receive the new HIGH preset; no initialized review is rebuilt.

No live provider probe or review is authorized by changing the setting. Use deterministic fixtures for verification. No Python CPU optimization, permanent user roster-config rewrite, new dependency or per-host special mode is included.
