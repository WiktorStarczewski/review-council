# CLI Claude seats and a fast plan gate (#7, #8)

- [x] WP1 #7 roster: `claude_adapter` (cli/agent/auto) + env override, one resolver, padding follows it; `plan_seats` config recorded in roster.json only when `all`.
- [x] WP1 #7 seat: nested `claude -p` scrubs parent-session env; flags test; live Sonnet smoke from Claude Code.
- [x] WP1 #7 ripgrep: one resolver (REV_RG, PATH, Claude Code embedded ripgrep), clear failure; session input lock stops relabelling body errors.
- [x] WP3 #8 evidence: one-seat plan topology, verify-panel for one seat, parser reads paths only in `Sites:` and the first `Test:` token, refusals name cluster/field/token/fix, capacity refusal retries with chunks.
- [x] WP4 #8 prompts: `--phase` flag and verification sibling-site sentence; `--panel` render in one process with one manifest load; per-seat render time in rev-profile.
- [x] WP5 #8/#7 skills: both host skills (CLI claude rows via rev-seat.sh, evidence gated on agent rows only, one-seat plan default, plan before code, verification sentence, panel render); rev-state.sh refuses `phase=fix` without a plan or a recorded skip.
- [x] Merge, CHANGELOG, full suite, fast review panel.
- [ ] PR.

### Review

- Four parallel packages merged; the one spec deviation is issue #8 section 5: `mandatory source reads exceed repository capacity` never depends on patch chunks, so plan prepare now passes `REV_SOURCE_CONTEXT=1` like code panels instead of a chunk retry that cannot clear it.
- The 5-19 minute renders came from `dict.setdefault(tree, repo.entries(tree))` evaluating its default per source row (a whole-tree `git ls-tree -r` each time).
- Live smoke from Claude Code: a Sonnet seat on the `claude` adapter through `rev-seat.sh` exited 0 with a valid evidence read audit.
- User-authorized fast review: Anthropic-only panel (Opus, Sonnet, Sonnet), one four-bundle risk panel, one verification panel, one bounded Sonnet delta seat; 11 findings, 10 fixed, 1 deferred (eval harness `claude -p` sites).

# Token-Efficient Review Council

## 0.4.4 elapsed-time diagnosis

- [x] Stop the release path and verify no current-session reviewer or verifier remains active.
- [x] Reconstruct wall time from commits, session artifacts, attempts, and receipts.
- [x] Classify each delay as legitimate P0/P1 discovery, test/gate failure, audit failure, retry, or repeated work.
- [x] Compare this run with the plugin's measured self-review churn pattern.
- [x] Identify the smallest root-cause set and report evidence before proposing changes.

### Diagnosis review

- The feature-to-final-gate interval was 15 hours 27 minutes. Reviewer panels occupied
  6 hours 24 minutes, including 2 hours 30 minutes in incomplete panels.
- The 26 panel generations made 89 paid calls and processed 128,164,553 tokens. Ten panels
  were incomplete, and 14 paid calls did not produce a certifying result.
- The deterministic full gate is slow but stable: the final run passed 229 shell tasks,
  3,723 assertions, 89 Python tests, and all validators in about 10 minutes.
- Review work added 4,146 lines after the initial 902-line feature. Of 690 later-removed
  production and documentation lines, 510, or 73.9 percent, came from earlier review fixes.
- The primary cause is a self-amplifying review-and-fix loop. Scope expansion created real
  transaction bugs, brittle evidence audits wasted panel time, and severity policy made each
  new repair trigger another expensive certification cycle.

## 0.4.4 stable release lane

- [x] Diagnose the unbounded self-host review loop and unreliable evidence-session boundaries.
- [x] Compare the plugin release with the ordinary `/rev` population.
- [x] Reject a global correction cap for a release-specific failure mode.
- [x] Approve previous-stable review, the existing deterministic candidate gate, and a two-generation cap.
- [x] Implement and re-review the session-wide hard-audit stop.
- [x] Seal and serialize the four evidence-session inputs.
- [x] Promote composite red-team, compatibility, recovery, security, and integration coverage in normal panels.
- [x] Remove the custom release authority and document the signed-tag procedural lane.
- [x] Pressure-test both host skills.
- [x] Repair the three stale shell fixtures and run the complete frozen-tree gate.
- [x] Run the initial stable 0.4.3 P0/P1-only release panel for 0.4.4.
- [x] Repair its three accepted P1 groups with focused regression coverage.
- [x] Pass the repaired frozen-tree gate and run the one permitted stable final panel.
- [x] Repair the final panel's two independently verified P1 findings.
- [ ] Run focused regressions and the complete frozen-tree gate without another panel generation.
- [ ] Squash-merge PR #6, publish 0.4.4, reinstall, and verify fresh-session discovery.

## 0.4.4 PR review publication

- [x] Capture the canonical PR #3856 review template and approve the behavior.
- [x] Establish a clean frozen-tree verification baseline in an isolated worktree.
- [x] Add failing renderer, publisher, duplicate, failure, and no-PR tests.
- [x] Implement deterministic rendering and GitHub PR review publication.
- [x] Require publication at successful PR-review completion on both hosts.
- [x] Document the workflow and prepare the 0.4.4 release metadata.
- [x] Run focused tests, the complete frozen-tree gate, and plugin validators.
- [x] Pressure-test the edited skills against normal, read-only, and stack-failure scenarios.
- [x] Bind PR discovery and base identity to the reviewed repository and merge base.
- [x] Make no-push publication and stack finalization durable across retries.
- [x] Preserve separate-PR fix links and normalize commit counting.
- [x] Record authoritative stack sessions only after completion.
- [x] Add body-hash and non-git stack regressions.
- [x] Run a fresh complete council pass after the r9 audit-invalid panel.
- [x] Fix the final publication, stack-push, rendering, and remote-normalization findings.
- [ ] Run the complete exact-roster verification panel on the repaired tree.
- [ ] Push, open and merge the PR, publish 0.4.4, install it, and verify discovery.

### Final-panel repairs

- [x] Add red regressions for no-push rendering, copied target state, commit-pinned posts,
  base movement, stack propagation, literal session paths, and invalid empty review pages.
- [x] Add red regressions for stack-leg ready receipts, partial multi-repository failure,
  merge-base preservation, and dirty-path diagnostics.
- [x] Bind every target back to its reviewed scope and create reviews against the frozen commit.
- [x] Let safe base-tip movement and brief post-push propagation recover without weakening
  base-branch or reviewed merge-base validation.
- [x] Give stack legs a pre-publication receipt and publish successful repositories even when a
  different repository failed.
- [x] Run focused gates, the complete frozen-tree gate, and a fresh exact-roster council panel.

### Final convergence repairs

- [x] Add red regressions for failure-atomic completion and a missing publisher.
- [x] Add the local stack validator and immutable commit, URL, and destination push.
- [x] Escape raw HTML outside balanced Markdown code spans without changing the template.
- [x] Close direct-publication head races and make the negative fixtures non-vacuous.
- [x] Accept all documented GitHub remote forms without widening host trust.
- [x] Contain malformed session text in durable failure receipts.
- [x] Validate original, finalized, and recoverable stack review states before completion.
- [x] Run focused tests and the full frozen-tree gate on the repaired implementation.
- [ ] Run the final exact-roster panel.
- [x] Reject mismatched stack push refs before any remote mutation.
- [x] Refresh the exact upstream tracking ref after a successful literal-URL push.
- [x] Add non-vacuous regressions for wrong-ref refusal and post-push tracking state.
- [ ] Rerun focused, frozen-tree, and exact-roster verification on the repaired tree.
- [x] Make publication a recoverable GitHub pending-review transaction.
- [x] Prove concurrent identical publication across separate clones submits one review.
- [x] Preserve exact COMMENTED-review idempotence and ambiguous-write recovery.
- [x] Triage the final P1 plan with three valid seats and preserve the invalid Sonnet audit.
- [x] Record the explicit override of the incomplete fourth plan seat without retrying it.
- [x] Reject publication sessions that overlap an associated PR checkout.
- [x] Make terminal write-boundary closure and post-confirmation head movement idempotent.
- [ ] Run focused gates and one final P0/P1 delta panel.
- [ ] Squash-merge PR #6, release 0.4.4, reinstall it, and verify plugin discovery.

### Review

- Pressure tests: the baseline skipped required publication in 2 of 3 scenarios;
  all 3 evaluators followed the new contract when the edited skills were loaded.
- Frozen-tree verifier passed shell tests, Python tests, both Claude validators, and
  the Codex marketplace validator.
- Post-r9 repair gate passed 222 shell tasks, 3,386 assertions, 89 Python tests,
  both Claude validators, and the Codex marketplace validator.
- The destination repair passed 302 PR-publication assertions, 282 stack assertions,
  and 447 skill-contract assertions.
- A live disposable draft on PR #6 confirmed GitHub rejects a second pending review
  for the same authenticated user and exposes the first draft through the review list.
- The remote transaction repair passed 332 PR-publication assertions and 449
  skill-contract assertions, including independent-clone serialization and safe cleanup.
- The final P1 repairs passed 350 PR-publication assertions and 453 skill-contract
  assertions, including red-green coverage for all three write-boundary races.
- The signed 0.4.3 release panel completed all four exact-roster seats with a valid
  evidence receipt and no audit violations. Three P1 repair groups were accepted.
- The release-panel repairs passed 19 neighboring audit-stop assertions, 354
  PR-publication assertions, retry and serialization coverage for immutable session
  inputs, Python compilation, and shell syntax checks.
- The final stable panel produced three valid seat audits and one invalid legacy audit.
  Independent source verification accepted two P1s: interrupted hard-stop durability
  and pre-push stack merge-base validation. The two-generation policy forbids a third panel.
- The final P1 repairs passed 33 evidence-audit failure assertions, 22 audit-stop
  assertions, 357 PR-review assertions, and 285 stack assertions. Both Python files
  compile, all edited shell files parse, and the edited files contain no Unicode dashes.

## Wall-time optimization spike

- [x] Measure phase and seat elapsed time across preserved optimizer sessions.
- [x] Attribute avoidable wall time to retries, invalid receipts, repeated gates, and serial orchestration.
- [x] Rank low-quality-risk changes by elapsed-time reduction and token effect.
- [x] Present a bounded design for approval before implementation.
- [x] Implement the approved wall-time design.
- [x] Extend the design with seat-local recovery, deterministic plan searches,
  provider proof batching, persistent retry budgets, and self-host replay.
- [x] Reject forced aligned source blocks after replay showed 82.5 percent more
  delivered source lines.
- [x] Write the approved wall-time design and implementation plan.

- [x] Profile preserved review sessions.
- [x] Approve the adaptive design.
- [x] Create an isolated worktree.
- [x] Add failing schedule and prompt-budget tests.
- [x] Implement the adaptive schedule in both host skills.
- [x] Compact common prompts and preserve Gemini schema delivery.
- [x] Add the reusable session usage profiler.
- [x] Run historical and full-suite validation.
- [x] Preserve explicit numeric schedules and isolate plan artifacts.
- [x] Correct completed, metered, unmetered, Gemini, and retry accounting.
- [x] Validate exact model and repeated Opus configuration without fallback.
- [x] Remove redundant history and Gemini prompt copies.
- [x] Install and verify the final cache-busted plugin build.
- [x] Add deterministic full-discovery and later-delta coverage receipts.
- [x] Route mechanical files to one named verification seat.
- [x] Generate deterministic evidence packets with changed symbols, callers, tests, and gates.
- [x] Add and test the bounded reviewer read protocol.
- [x] Partition semantic changes by deterministic dependency component while retaining one full-state integration seat.
- [x] Preserve finding ownership and route later fix components back to the finding seat.
- [x] Enforce bounded source and search output at the available tool boundaries, with explicit expansion receipts.
- [x] Stabilize provider prompt prefixes and report cached input separately from raw processed tokens.
- [x] Add hash-bound literal source-context packets with complete range auditing and fail-full fallback.
- [x] Repair path-scope, snapshot fidelity, roster-size, stale-stack-report, profiler, and evidence-builder findings from the final panel.
- [ ] Run held-out quality and token-efficiency evaluation for the added optimizations.
- [ ] Complete the final four-bundle optimizer verification panel.
- [x] Fold the completed optimizer work into release 0.4.1 and push checkpoint 4b7a275.
- [x] Commit and push reviewed optimizer checkpoint b546ad3.
- [ ] Resume PR #812 with the optimized council.

## Final control-panel repairs

- [x] Reproduce and fix duplicate reasons in merged source-context ranges.
- [x] Bind required-source audit reads to the session snapshot object store.
- [x] Keep complete integration proofs and require relevant specialist source reads.
- [x] Preserve AGENTS.override.md precedence in adaptive evidence snapshots.
- [x] Collect legacy instructions lexically without following changed symlink targets.
- [x] Apply the 80-result cap to shell search producers.
- [x] Handle changed zero-byte source files without impossible line-range proofs.
- [x] Replace vacuous receipt and unreadable-input tests with reason-pinned coverage.
- [x] Correct full-scope evidence audit diagnostics.
- [x] Cache patch, blob, and line indexes inside one read audit.
- [x] Count Grok's model-visible tool content once instead of duplicated internal raw-output metadata.
- [x] Remove only redundant manifest derivation while preserving before-and-after freshness checks.
- [x] Install private-home traps before creation and add lease-proven stale cleanup.
- [x] Fail closed to full legacy scope for Agent seats whose plugin hooks cannot be enforced.
- [x] Compact repeated per-range hunk identity into a manifest-derived digest.
- [x] Prevent weak lexical references from collapsing independent semantic components while retaining specialist and integration coverage.
- [x] Point reviewers at the frozen assigned patch as their first native read to avoid zero-tool and blocked-shell retries.
- [x] Split assigned patches into hash-bound byte-safe read chunks so exact patch coverage needs fewer provider tool turns.
- [x] Give adaptive plan panels a hash-bound all-cluster site closure for three seats and retain one full-state plan-completeness seat.
- [x] Select innermost declarations and bounded changed-line anchors so file-scope metadata cannot force whole-file source reads.
- [x] Run focused regressions, the complete shell suite, Python discovery, validators, and static checks.
- [ ] Rerun the optimized exact-roster panel and record paired provider-token measurements.

## Live receipt repairs

- [x] Accept the Claude Read tool's exact terminal-blank-line rendering without weakening byte checks.
- [x] Keep ordered patch reads within a provider-specific audited batch limit.
- [x] Remove repeated source-context serialization, blob decoding, and manifest derivation while retaining direct snapshot-blob validation.
- [x] Replace vacuous lease, chunk-source, and plan coverage-head assertions with mutation-sensitive checks.
- [x] Replace BSD-only plan-fixture edits with portable rewrites.
- [x] Classify a wrapper-declared audit rejection directly instead of scanning reviewer-controlled text.
- [x] Count well-formed invalid evidence audits in the profiler without requiring valid-audit citation equality.
- [x] Deliver required source segments through adapter-native, hash-bound session artifacts.
- [x] Select chunk proof when a long patch line cannot fit a bounded window read.
- [x] Remove detached evidence repositories while preserving snapshot-bound source proof.
- [x] Recover deleted declarations from the base snapshot for surviving-caller discovery.

## Final low-risk cost candidates

- [x] Prove from live traces that two-chunk Grok and Claude patch reads clear the 10 percent total-token threshold.
- [x] Implement provider-specific patch batching with exact-byte, ordering, and 60 KiB fail-closed audits.
- [x] Make evidence delivery adapter-specific, remove prompt-text control parsing, and keep experimental paths off pending certification.
- [x] Segment oversized required source proofs within provider line and visible-byte limits.
- [x] Preserve cumulative component routing when delta reuse is unavailable.
- [x] Remove duplicated search parsing, unreleased manifest compatibility, and a dead model-selection wrapper.
- [x] Make profiler patch-proof tests reject the exact malformed audit and accept a complete sibling proof.
- [ ] Run a held-out exact-roster measurement of patch batching.
- [x] Measure bounded inline component evidence at 13-17 percent across the full review schedule.
- [ ] Implement inline component evidence only if batching's held-out council pass preserves review quality.
- [ ] Stop when no remaining low-quality-impact candidate is likely to save at least 10 percent.

## Codex source-window batching

- [x] Measure a conservative 21.5 percent reduction in c3 Sol tool turns.
- [x] Implement a strict Codex-only multi-range parser and frozen-byte audit.
- [x] Keep the prompt path disabled unless its exact frozen prompt opts in.
- [x] Add separate source-call and source-batch profile counters.
- [x] Pass focused prompt, guard, audit, and profiler checks.
- [x] Run the exact Sol canary before using the path in certification.

## Opus and Sonnet roster

- [x] Add a fail-closed exact Claude model list with one Opus and one Sonnet seat.
- [ ] Update active policy, skills, configuration, and tests without rewriting historical baselines.
- [x] Label every new profile with its roster and compare cross-roster runs only on model-independent workflow metrics.
- [ ] Certify the final panel as Sol, Terra, Opus, and Sonnet at maximum effort.

## Global Grok phase-out

- [x] Replace the global council policy and personal configuration with Sol, Terra, Opus, and Sonnet at maximum effort.
- [ ] Remove Grok from live discovery, launch, extras, configuration examples, status output, and current-session contracts.
- [ ] Keep only the historical Grok artifact readers needed to profile and verify preserved baselines.
- [ ] Update active tests and documentation without rewriting measurements produced by older rosters.
- [x] Revalidate the exact four-seat roster before every paid panel launched after the replacement.
- [x] Rerun the interrupted repair-plan panel with Terra in Grok's former seat.

## Certification repair

- [x] Freeze the first exact-roster certification attempt and record its provider usage.
- [x] Triage valid and advisory findings against source.
- [x] Bootstrap audit transport for native search bounds, failed exploration, provider newline rendering, quoted patterns, and bounded Grok skill reads.
- [x] Run the required four-seat plan panel over the substantive repair plan.
- [x] Enforce patch, packet, and source-expansion phase ordering in both patch modes.
- [x] Close unclassified source and discovery output paths.
- [x] Bind every accepted session artifact to the current prompt.
- [x] Keep prior benchmark truth intact until a replacement is ready to publish.
- [x] Remove the redundant required-source live cross-check and cache worktree source bytes.
- [x] Support full reads for explicitly named document-panel inputs.
- [x] Bind the profiler to one real schema-2 audit fixture.
- [x] Enforce the 32 KiB visible-output ceiling for source-context packets.
- [x] Parse real Claude hook response envelopes, enforce LF-only coordinates, and prove empty assigned patches without fake reads.
- [x] Make plan search proof exhaustive for hidden and ignored worktree files while excluding `.git`.
- [x] Replace vacuous receipt mutations and lease cleanup checks with valid controls and pinned failures.
- [x] Prove the repaired patch, packet, segment, index, and source order with valid Opus and Sonnet canaries.
- [ ] Reinstall, rerun the exact-roster verification panel, and record paired token measurements.
- [ ] Resume the paused c3 repair only after the wall-time design is approved and integrated.

## Mixed-roster certification diagnosis

- [x] Preserve and profile the first Sol, Grok, Opus, and Sonnet certification attempt.
- [x] Independently verify every actionable claim from valid and invalid reviewer streams.
- [x] Repair Claude terminal-newline delivery checks and denied-call audit handling.
- [x] Remove planning-mode interference from the read-only Claude reviewer transport.
- [x] Isolate each parallel test shard's temporary namespace and make lease tests deterministic.
- [x] Bind provider contract receipts to current boundaries, evidence manifests, and the active roster.
- [x] Launch benchmark Agent seats with their configured Claude model and effort.
- [x] Reject plan artifact names that collide with repository paths.
- [x] Remove Grok's unsupported listing tool and recognize legacy listing transcripts defensively.
- [x] Prove exact roster order and remove extras whose configured model probe failed.
- [x] Run the required plan panel, implement its accepted corrections, and rerun local gates.
- [ ] Run a fresh exact-roster certification with four valid first-pass bundles.

## Final certification findings

- [x] Freeze optimization scope at the current C-16 through C-21 design; defer every
  non-blocking improvement until after the stable 0.4.2 release.

- [x] Replace Grok planning mode with a neutral read-only tool contract.
- [x] Prevent trusted preflight from executing contract tests from the reviewed checkout.
- [x] Reject the refuted clean-gitlink snapshot candidate without changing recursive validation.
- [x] Make plan location parsing and validation share one path and line domain.
- [x] Enforce the exact packet, required-segment, index, and source order.
- [x] Bind post-render verification to the rendered manifest without per-seat search replay.
- [x] Preserve safe denied Claude exploration without proof credit and stop irrecoverable hook failures.
- [x] Cancel pending siblings after a freshly proven panel-global failure.
- [x] Replace repeated lexical duplicate scans with one heredoc-safe parent discovery pass.
- [x] Recover later implicit provider turns after a known output without hiding missing outputs.
- [x] Run the required plan panel before nontrivial fixes.
- [x] Triage every Sol, Grok, Opus, and Sonnet plan finding and validate the amended seven-cluster plan against the frozen snapshot.
- [x] Implement C-09 through C-15 with focused failing tests before each repair.
- [x] Run focused checks, then one fresh full shell and Python gate on the final implementation tree.
- [ ] Certify the completed implementation with the exact Sol, Terra, Opus, and Sonnet roster.
- [ ] Measure the certified candidate against the preserved 0.4.0 baseline and publish only model-independent cross-roster comparisons.
- [ ] Release and install 0.4.2, then resume PR #812 with that installed version.
- [x] Run the exact-roster plan panel for C-16 through C-19 and triage every finding.
- [x] Run the amended exact-roster plan panel for C-16 through C-21.
  - [x] Complete a focused C-20/C-21 panel in which Sonnet returns a valid four-finding result instead of stopping after repository sizing.
  - [x] Fold split delta/proof ownership, launch-time head checks, no-full fallback coverage, exact test inventory, tree-drift detection, and receipt/log binding into the amended plan.
  - [x] Recheck the amended focused plan before implementation and close it with clean Sol and Terra results.
- [x] Implement C-16 through C-21 with focused failing tests.
  - [x] Compile schema-4 plan prompts against exact scope, lens, plan, hash, and artifact authorization before publication.
  - [x] Render and audit one exact native first read for every plan specialist.
  - [x] Keep plan retries seat-local and forbid legacy full-scope specialist fallback.
  - [x] Fail Agent-based plan preparation before launch with an enforceable-adapter diagnostic.
  - [x] Remove Grok from live council paths while preserving historical decoders and measurements.
  - [x] Complete receipt-relative plan routing, unified verification, and four-way evidence-test partitioning.
- [ ] Rerun the material-tree gates and final certification after the accepted fixes.
  - [x] Repair read-only-source compatibility in the bundle builder, legacy transcript audit,
    and test-owned fixture copies exposed by the first unified full gate.
  - [x] Rerun the full frozen-tree gate only after every failed task identity is focused green.

## 0.4.2 release blockers from exact-roster certification

- [x] Publish plugin bundles with one atomic directory exchange and preserve the live bundle on failure.
- [x] Keep verifier state outside the reviewed source and traverse it descriptor-relative without following symlinks.
- [x] Distinguish persistent local attempt exhaustion from provider quota failures with public exit 7.
- [x] Accept only the documented strict recursive grep form in review evidence.
- [x] Keep Claude reviewing after compaction with a constant noninteractive continuation prompt.
- [x] Compile plan proof and repository reads below provider call and turn capacity before launch.
- [x] Keep the complete inline fix plan authoritative and use its basename only as a citation label.
- [x] Add opt-in, quota-only cross-provider fallback with a fresh whole-panel restart and no configuration mutation.
- [x] Bind version probes and gates to the same descriptor-held material cwd and relative environment.
- [x] Record Gemini's supported null effort as a complete, stable profile identity.
- [x] Exclude explicitly quota-failed seats from fallback target selection.
- [x] Limit the temporary min_labs waiver to diversity loss caused by successful quota substitutions.
- [x] Fail closed on malformed evidence declarations and use audit metadata for legacy classification.
- [x] Accept exactly 80 bounded plan-search results while continuing to reject 81 or more.
- [x] Count code source proof and refutation reserve in provider turn capacity and enforce Claude's compiled cap.
- [x] Promote adjacent omitted source ranges as a group when they jointly remove a mandatory plan read.
- [x] Keep in-repository session artifacts out of repository-source classification and require the mandatory evidence-index read.
- [x] Install ripgrep explicitly in both hosted runner images used by the plan-evidence fixtures.
- [x] Remove the live zsh dependency and concurrent shared-file race from the cross-platform shell tests.
- [x] Make the parallel provider-probe unit test independent of operating-system callback completion order.

- [x] Make evidence order accept multiple repository reads in a later turn while still rejecting
  repository expansion mixed with proof delivery.
- [x] Give source-context packets an exact one-packet read action and audit the same batch limit.
- [x] Preserve capacity-omitted source identities and require direct proof of the omitted range.
- [x] Keep retained omission identities in the manifest while rendering one deterministic direct-read
  target so large code prompts remain within their word budget.
- [x] Bound and reap every provider, version, contract, and plan-search process group on success,
  failure, timeout, and host cancellation.
- [x] Derive provider-contract replay triggers from the complete hashed contract input set.
- [x] Prevent same-label retry collection from consuming a stale completion marker.
- [x] Namespace caller-provided verifier cache roots and mutate receipts only while holding the
  coordination lock.
- [x] Bind verifier receipts to local script interpreters and declared transitive gate tools, and
  probe current external tool versions on every identity calculation.
- [x] Run each focused regression red, implement the minimal fix, and make its focused gate green.
- [x] Run one fresh frozen-tree gate, then a fresh exact-roster four-bundle panel that seals.
- [ ] Commit, push, release, and install 0.4.2.

### Discovery-panel repairs

- [x] Remove Bash and unreceipted LSP from every Anthropic reviewer surface and retain native Read/Grep auditing.
- [x] Infer Codex concurrent tool batches from call-start and output ordering so batch limits seal.
- [x] Make the roster cancellation test wait for every provider started by its fixture.
- [x] Search the accepted plan source domain, including base-only deleted files, under one post-materialization deadline.
- [x] Permit a singleton required-source line up to the per-read ceiling while keeping ordinary segments batch-safe.
- [x] Stamp the Codex cachebuster inside the builder staging tree before the atomic live swap.
- [x] Reserve provider-call budget only after fallible pre-launch transcript archival succeeds.
- [x] Bind foreign-target provider receipts to reviewed content and executable mode without executing target code.
- [x] Bound attempted post-proof reviewer expansion so a complete evidence read still leaves room for required JSON.
- [ ] Run focused red-green regressions, one final frozen-tree gate, and a fresh exact-roster delta panel.

Deferred after the frozen release:

- Evaluate transitive changed local-import closure as a possible design change. The accepted 0.4.2
  contract deliberately uses one-hop neighbors plus one full-state completeness seat.
- Make isolated-seat-home cancellation atomic across create and readiness publication.
- Publish persistent attempt counters by atomic replacement under a stable lock.
- Reap dead process-group leaders during the Linux termination grace loop while retaining live-descendant detection.
- Isolate stale-home cleanup errors per unrelated candidate so an abnormal leftover cannot block a new seat.
- Compile narrower Sol discovery queries so the reviewer cannot repeatedly hit the 81-result audit sentinel.

## Review

- Six preserved sessions: 193 metered calls and 1,050,576,445 provider-reported
  processed tokens. Provider cost fields totaled USD 321.01 but were incomplete.
- Completed fixed-loop sessions rendered 58-62 seat prompts. The adaptive
  high-risk schedule renders 16, a 3.63x-3.88x reduction in reviewer launches.
- A matched PR #812 code plus plan cycle fell from 41,728 prompt words to
  20,237, a 2.06x reduction without removing the plan snapshot.
- The final frozen tree passed 2,349 shell checks and 41 Python tests. Both Claude
  plugin validators, the Codex marketplace validator, shell syntax, Python
  compilation, executable-bit checks, Unicode checks, and diff hygiene passed.
- The generic plugin validator still rejects the existing Codex
  `./codex-skills/` manifest layout; the repository marketplace validator accepts
  and repeatably installs that layout.
- The 846,358-byte patch-chunk reference fell from 60 bounded windows to 35
  exact chunks, a 41.67% reduction in patch proof calls and turns. The live
  795,245-byte optimizer patch fell from 56 windows to 33 chunks, a 41.07%
  reduction. These are delivery-path measurements; provider token adoption still
  requires the paired exact-roster panel.
- The fresh optimizer plan projection fell from 443,564 legacy four-seat scope
  words to 280,688 words including evidence and source-proof overhead, a 36.7%
  reduction or 1.58x. Patch-only scope fell 45.2%, from 443,064 to 242,808
  words. Provider-token adoption still requires the paired exact-roster panel.
- The first exact-roster certification attempt consumed 37,034,947 processed
  tokens across five provider calls and USD 23.10. One of four seats had a valid
  evidence audit. Treat this run as transport diagnosis, not certification.
- The second exact-roster attempt consumed 48,430,089 processed tokens across
  five calls and USD 25.68. It exposed provider-envelope, bounded-search, and
  negative-test gaps, so it is diagnostic and cannot support a savings claim.
- The final candidate tree passes 2,766 shell assertions and 48 Python tests before
  the exact-roster certification run.
- The first parallel full-suite sample finished in 270.75 seconds versus the
  571.4-second serial baseline, a 52.6 percent reduction or 2.11x speedup. It also
  exposed six deterministic shard and audit-fixture failures that focused tests
  then reproduced and repaired before certification.
- The exact Sol canary completed in 43 seconds and returned one wrapped two-window
  source call. Offline replay certified two exact source ranges, one source batch,
  and zero audit violations.
- The final Opus and Sonnet canaries both produced schema-2 receipts with every
  assigned chunk and required source segment complete, ordered, and free of audit
  violations. The canary caught and removed one redundant instructions-file read
  before the four-seat certification.
- The final parallel shell suite completed in 158.47 seconds versus the preserved
  571.4-second serial baseline, a 72.3 percent reduction or 3.61x speedup, while
  increasing the suite from 2,349 to 2,766 assertions.
- The completed C-09 through C-15 tree passed 2,876 shell assertions in 174.7
  seconds and 49 Python tests in 28.0 seconds. The final phase-order fix was
  reproduced by two failing integration assertions, then passed all 36 focused
  patch-order assertions before the clean full run.
- The first Opus and Sonnet roster certification diagnostic consumed 80,995,512
  processed tokens across 10 metered calls and USD 26.41. Only Opus produced a valid
  audited result, so this run is transport diagnosis and does not certify savings.
- The receipt-relative plan-packet design projects 264,068 deterministic reviewer
  words versus 403,287 for the current routed panel, a further 34.5 percent reduction,
  while retaining one complete 1.65 MB pass and every specialist cluster proof.
- A validated longest-first local scheduler prototype ran all 73 existing shell tasks
  green in 106.948 seconds versus the 174.656-second current gate, a measured 38.77
  percent reduction or 1.63x speedup with unchanged test coverage.
- The first 0.4.2 verification candidate produced valid Terra, Opus, and Sonnet audits.
  Sol repeated one assigned chunk on both attempts, so the panel did not seal. Source
  triage accepted three P1 and three P2 boundary findings. Two low-impact hardening
  items were recorded for a later release.
- The final code-focused panel sealed with Terra, Opus, Sonnet, and a Sol correctness
  replacement. Six metered calls processed 25,627,649 tokens at a reported USD 9.83;
  four reviewer results were valid. Two high-confidence auditor P1s were accepted and
  fixed, one orchestration P1 was rejected as unreachable under compliant callers, and
  two bounded P2 hardening items were deferred.

## 0.4.3 audit-convergence repair

- [x] Reproduce the wallet PR #814 failure cascade from preserved session artifacts.
- [x] Quantify accepted calls, audit failures, dominant violation families, and retry amplification.
- [x] Make completed evidence choreography and budget overruns advisory when substantive coverage is complete.
- [x] Keep incomplete patch, required-source, citation, and result proof as hard audit failures.
- [x] Remove the contradictory pre-index original-source target from generated prompts.
- [x] Stop paid retry and full-state repair after a hard evidence-audit failure.
- [x] Preserve the original session and limit quota fallback to one isolated full-panel restart.
- [x] Replay the preserved PR #814 audits against the new policy: acceptance rises from 16/32 to 31/32; the remaining attempt lacks required source proof.
- [x] Run focused tests and the complete release gate: 208 shell tasks, 3,154 assertions, 89 Python tests, and all marketplace and plugin validators passed.
- [x] Run one bounded self-host panel. Two valid seats found two contract contradictions; one hard audit failure stopped the panel with no retry, fallback, or repair cascade.
- [x] Run a fresh bounded post-fix panel without automatic retry. Three valid seats found the remaining same-label relaunch path and required-source duplicate mismatch; the hard-audit Sonnet result was preserved and stopped without retry.
- [x] Block a same-label relaunch in `rev-seat.sh` before provider-call reservation, preserve its hard-audit artifacts, qualify every host exit 1/2 retry, and make duplicate complete required-source reads advisory.
- [x] Validate duplicate patch and source reads before classifying them as advisory, fit source packets inside the observed live transport envelope, and bind quota fallback to identical content-addressed source.
- [x] Run one final fresh bounded panel without retries. Sol, Terra, and Sonnet completed valid reviews; the Opus result was preserved after one harmless trailing patch-window overshoot. The panel found the atomic fallback transition, panel-wide hard stop, advisory receipt, and two vacuous-test gaps fixed below.
- [x] Make the Claude Code policy and both `/rev` skills executable workflow contracts, with explicit reasons for skipped steps and non-certifying missing artifacts.
- [x] Promote every fallback session variable atomically, stop all sibling launches under a hard-failed panel label, retain per-seat advisories in durable receipts, and replace both vacuous regressions with exercised malformed or omitted cases.
- [x] Treat a trailing out-of-range patch read as advisory only after complete byte proof, while preserving the fatal boundary before proof completes.
- [ ] Re-run the complete release gate after the accepted council fixes.
- [ ] Push, release, and reinstall 0.4.3 before resuming wallet PR #814.

Deferred to 0.4.4 after the stable release:

- Keep evidence mode for enforceable CLI seats in mixed Claude Code panels while Agent seats receive explicit unaudited full-state coverage, and define the combined receipt and certification semantics.

### 0.4.3 review

- The preserved PR #814 replay converts 15 choreography-only rejections to valid advisory audits. Acceptance rises from 50.0 percent to 96.9 percent; the remaining attempt still lacks required source proof.
- The first 0.4.3 self-host panel launched exactly Sol, Terra, Opus, and Sonnet once. Sol and Terra returned valid audits. Opus missed required source proof, which stopped the panel and canceled pending Sonnet without any automatic reviewer launch.
- Sol found a stale plan-panel audit-retry instruction in both host skills. Terra found the nearby duplicate-chunk wording still described every duplicate as fatal. Both contradictions were fixed to match the deterministic auditor policy.
- The live hard-stop exposed a stale retry directive in `rev-seat.sh`. Hard audit failures now preserve rejected findings as `.audit-invalid.json`, remove the canonical result, and tell the host to stop before another reviewer launch.
- The next bounded panel returned three valid audits. Sol and Opus independently found that stale collection instructions and a wrapper relaunch could still retry a failed audit label; Terra found duplicate required-source reads remained fatal despite the advisory contract. All three were fixed with focused regressions.
- Sonnet completed a useful result but missed required source proof. The wrapper preserved it under `.audit-invalid.json`, emitted exit 2, and made no retry. Its mixed advisory/fatal classification suggestion was rejected because 0.4.3 intentionally promotes choreography issues to advisories only after every substantive proof gate passes.
- The third bounded panel stopped on Terra's truncated source packet without retrying any seat. Sol found malformed duplicate patch reads could skip completeness validation, and Terra identified quota fallback's path-only source comparison. The fixes validate duplicate bytes, cap normal source packets at 16 KiB, and compare frozen content identities across fallback sessions.
- The final bounded panel launched each configured seat once and performed no automatic retry, fallback, or repair. Sol found that quota fallback did not promote all active generation variables. Opus's preserved result found that a hard stop was seat-local and two tests were vacuous. Sonnet found that receipt output dropped advisory detail. Terra reported no findings. All source-verifiable P1 and P2 findings were fixed. Opus's audit failure came from a redundant Read after the full patch had already been proven; that exact sequence is now a valid advisory regression, while a premature overshoot remains fatal.

## Review cost first wave

- [x] Trustworthy reviewer and host usage with deduplicated streaming records.
- [x] Static launch prechecks and isolated availability probes.
- [x] Active-mode prompt compilation with unchanged evidence obligations.
- [x] Compact session briefing and local status watching.
- [x] Register new tests and complete the bounded four-call development benchmark.
- [x] Complete the full local gate and prepare the feature branch and draft PR.

Review: Implemented on a worktree based on 0.5.6. Focused cases cover streaming identities, explicit zero cost, incomplete results, static replay, probe isolation, active evidence modes and scheduled local status. Production roster and certification coverage are preserved. The final frozen gate passes 351 shell cases, 4,683 assertions, all 147 Python tests and all validators. Read-only-copy setup failures were fixed in temporary copies; the runtime implementation remains unchanged after measurement. The four-call allocation replaced the earlier one-call development check. It benchmarks reviewed fixtures and does not certify the first-wave implementation. Feature-branch delivery uses this verified code and the prepared draft PR; full Council certification remains pending while Claude quota is exhausted.

## Reusable cost benchmarks

- [x] Freeze 0.5.6 and first-wave source identities and two sealed correctness cases.
- [x] Add provider-free scorer and bounded runner regressions.
- [x] Measure local correctness, prompt compilation and preflight work.
- [x] Run the approved four Terra executions, two paired cases in opposite orders.
- [x] Inspect all eight returned findings against source and runtime truth.
- [x] Save complete hash-bound adjudications and JSON/CSV/Markdown results.
- [x] Preserve two earlier routing failures separately with unknown usage.

Plan: `docs/superpowers/plans/2026-09-29-review-cost-benchmarks.md`. Live identity is `gpt-5.6-terra` at `max`. Four successful executions, no availability probes, scoring calls, replacement models or automatic reviewer retries. This is a single-seat benchmark, with no full Council certification.

Review: All four results pass schema and read audits. Each version finds four of four planted defects with zero false positives. Pooled estimated Standard credits fall from 6.91687 to 6.44636 (6.8%); provider time falls from 187.71 s to 160.08 s (14.7%). Total input falls 0.9%, uncached input 0.1%, output 17.3%. Most observed savings come from output, and two cases do not establish statistical quality equivalence or production savings. Dollars remain unknown because the CLI does not report them.

Results: `docs/cost-benchmark-wave1-2026-09-29.md`. Complete raw artifacts and aggregate metrics are retained in `wave1-20260930-network` under the research-notes benchmark directory. `wave1-20260929` and `wave1-20260930-live` preserve the two earlier routing failures at 17.28 s and 17.13 s with no usage or findings. Both transport failures stopped their original batches. The final successful batch followed a fresh network reachability check under Full access.

# Cost optimization wave 2

- [x] Resolve newest Sol and Luna from the provider catalog, at xhigh, with no generation pins.
- [x] Update the benchmark to freeze selected model, effort and rate card and allow two-call stages.
- [x] Measure two fixtures on the existing wave 1 workflow before context or round changes.
- [x] Select and implement wave 2 context and repeated-round optimizations from the measured baseline.
- [x] Measure the same two fixtures on the frozen candidate, staying inside four total calls.
- [x] Adjudicate findings, compare correctness, time and credits, and document limitations.
- [x] Run the configured gate and commit the verified wave 2 source.
- [x] Push a separate draft change.

### Constraints

Latest models are discovered per run; historical identities stay fixed. OpenAI effort is xhigh.
Anthropic keeps Opus/Sonnet aliases and supported max effort. Astra and Grok remain excluded.
Only four new Luna reviewer executions are authorized. No paid probes, graders or retries.
The model/effort measurement precedes wave 2 implementation and its measurement.

### Wave 2 results

Four new Luna/xhigh calls completed with no probes, graders or reviewer retries.
The model-settings controls precede workflow changes. Workflow credits fell 12.0%
(0.315339 to 0.2773925) and pooled provider time fell 14.4% (234.20 to 200.48 s).
Both versions find four of four planted defects with zero false positives. One
candidate ledger citation misses the predicate; severity calibration is unmeasured.
The historical Terra/max migration reference is 95.1% cheaper and 46.3% slower,
with model and effort changed. Combined-panel launch savings are contract-tested
projections, require enforced CLI receipts, and have no live panel quality/cost result.

The full local gate passes 353 shell cases, 4,700 assertions, 161 Python tests and
all validators. Signed commit 4571f99 and draft PR #28 deliver wave 2. Global installed
plugin/config activation and full Council certification remain separate.

# Cost optimization wave 3

Plan: `docs/superpowers/plans/2026-09-30-review-cost-wave3.md`.
User chose packets plus relevant decision digests and two paid reviewer test executions
on one paired evidence case. Production retains four seats.

- [x] Implement lean packets with identical source selection and strict v1/v2 validation.
- [x] Implement optional conservative decision routing and full-context expansion proof.
- [x] Freeze one paired specialist case, with unchanged cache truth and neutral history.
- [x] Pass local contracts and run the two authorized Luna/xhigh test executions.
- [x] Adjudicate and document correctness, time, credits and representation-size metrics.
- [x] Complete the full local gate after discarding the runtime.
- [ ] Commit and push a separate draft with preserved measurements.

### Wave 3 results

Both paid executions finish and both semantic results find 2/2 bugs with no false
positives. The candidate spends 0.1976955 versus 0.195727 credits and takes 175.67
versus 140.05 s. Its original audit is invalid, with all original files preserved.
Offline replay passes after narrow EOF and complete bounded-index proof fixes.
Packet bytes fall 49.3%, but digest restoration and extra tool turns erase any
observed cost/time benefit. The combined implementation is discarded; its frozen artifacts remain for reproduction.

# Continued cost experiments

The user authorized autonomous continuation after the wave 3 pair, testing ideas,
benchmarking and retaining what works. This supersedes the completed wave 3 cap for
new experiments; its original two-execution ledger remains unchanged.

- [x] Verify and commit wave 3 measurements and independent audit correction after discarding the losing runtime.
- [x] Add a complex multi-file case with executable truth and clean controls before retention decisions.
- [x] Add a versioned 0-100 quality score from severity-weighted recall, precision, citation accuracy, observable source-flow coverage and manually verified hypotheses.
- [x] Require valid proof, no lost P0/P1, no added false positives, at least 90/100 quality and at most a 3-point paired drop before retaining an optimization.
- [x] Test packets without routed digest restoration on complex and clean cases. Discard after quality regression.
- [x] Test explicit complete-read transition cues against redundant EOF tool turns. Discard after a fresh pair fails.
- [x] Evaluate duplicate schema prose: the current adapter already supplies schema exactly once, so no change qualifies.
- [ ] Evaluate further backlog ideas with local contracts before paid canaries.
- [ ] Preserve unsuccessful experiments and retain measured improvements separately.

Use Luna at xhigh for low-cost screening, preserve production roster and independent
review obligations, freeze each identity, and prohibit automatic reviewer retries.
Use two executions per one-case screening pair, with four only when a second case
is necessary to check a concrete quality risk. Report variance and toy-case limits.

The next packet-only pair uses four executions because a wholly clean twin is
needed to measure specificity alongside the complex defective subsystem. Both
identities stay frozen. Quality scoring uses observed evidence and complete local
adjudications, never hidden reasoning or a paid grader. Legacy cases without the
private behavior rubric report an explicitly limited core score rather than an
invented 100-point score. Scoring policy changes require a new version and replay
of both sides of a comparison.

### Numeric quality and packet-only screen

The full frozen gate passes 353 shell cases, 4,701 assertions, 191 Python tests and
all three validators. Receipt tree: 35e96b952b44bceb0ea16f4b693426f301406faf685012eb61beee44098d301e.
Wave 4 completes four Luna/xhigh executions: pooled credits fall 24.6%, but complex
quality falls 92.5 to 83.5 with a lost P1 and two inaccurate citations. Clean quality
falls 91.25 to 88.75. Both candidates fail fixed retention gates and are discarded.
The independent bounded-index correction and reusable quality/complex-case suite remain.
Read-cue and source-batch screens reuse exactly matching frozen baseline controls,
with fresh two-execution candidate ledgers, no paid probes, graders or retries.
Full Council certification remains pending while fewer than three allowed seats are available.

### Continued screening results

Waves 5-9 are measured and losing runtime candidates remain isolated. The uncapped
complex result reaches 98/100 with all six faults, but its clean twin is 88.75 and
fails the frozen floor. Both batching variants lose observable source-flow proof;
the safer version also raises credits 8.8% and time 69.7%. Fresh read-cue testing
reduces credits only 1.0% with lower quality and higher elapsed time. No score or
rubric was relaxed after observing these results.

### Transfer and aggregate quality checks

- [x] Measure decisive-summary cue on both frozen cases with exact reused controls.
- [x] Measure complete-findings plus summary cue against four fresh executions. Both cases pass; pooled credits fall 8.49% and provider time 17.06%.
- [x] Test line-addressed packets on the qualified complete-checks control and repeat the combination against four fresh executions. All case gates pass; repeat credits fall 2.34% and provider time 21.90%.
- [x] Validate the combined runtime on an unrelated frozen build-cache holdout. Five faults are found, but clean depth is 86.25 and fails the fixed floor; discard the combination despite lower credits and time.
- [x] Integrate complete-case numeric run summaries after frozen paid stages finish. Forty focused quality/report tests pass; 22 portable holdout tests pass without skips.
- [ ] Run the final active-source gate, commit and push a draft stacked PR.

The instruction components remain private and unretained. The combined runtime
passes the dispatcher but fails the independent clean holdout depth floor. Mean
holdout quality rises 92.19 to 92.50 while minimum stays 86.25; the mean cannot
override that failed case gate. No scoring policy or rubric was relaxed.

### Next bounded experiment

- [x] Validate a private immutable snapshot batch contract with real captured tool output. Sixteen new tests and 182 existing focused checks pass; no production adoption.
- [ ] Test a general caller/state-flow inspection cue without fixture-specific hints.
- [ ] Run fresh paired measurements only after local proof and prompt contracts pass.

Native live-source batching remains off. A preserved reproduction shows ambiguous
joined producer output can be credited to incorrect individual source ranges.
Current-coverage rejects persistent source mutation, but restoration before audit
cannot prove which producer supplied each byte. A prospective pinned-snapshot
contract must avoid that ambiguity; original streams, audits and scores stay frozen.

The first aggregate gate catches six read-only mutation-copy errors and one flaky
shared argv-spy assertion during concurrent roster probes. Temporary copies now
copy bytes rather than frozen modes; all 22 holdout tests pass under a sealed tree.
The probe test records each process's arguments separately, preserving its original
availability assertion. Its 19 focused assertions pass. The repaired frozen gate passes 353 shell cases, 4,701 assertions, 229 Python tests
and all three validators. All five terminal logs and hashes are verified. Tested tree:
28afabf094c45fa2474c9857c30d7bc98af5fd267548b8f5bdde0f459fd9f33c.
Only this task record differs from the sealed tested source.

The next cheaper screen isolates finite patch completion plus a generic caller/state-flow
cue on the experimental packet anchor. Local rendering must preserve all unaffected
phase/adapter bytes before a finite two-call heldout stage, using exact frozen controls.
