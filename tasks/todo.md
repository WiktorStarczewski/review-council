# PR #109: bounded Codex patch chunk batching

- [x] Add exact chunk batching, byte ceiling, mixed-read, ordering and loss tests.
- [x] Inspect initial exact-head expected-red run 41296670721. It reached the tests, with 5,333 passed and 8 failed, but the embedded capacity fixture requested 14 mandatory reads against the existing limit of 12, so the run is not accepted as a clean red proof.
- [x] Correct the fixture to 12 mandatory reads while preserving the expected 6-chunk batch assertions. The guarded local shell check refused at load 6.96 over the 6.0 limit, so no local check ran.
- [x] Rerun exact-head expected-red CI and confirm the implementation contract is red. Run 41300194311 on test head 13009216 passed proof preparation; package run 41300194333 passed. Ubuntu and macOS each reached the full shell verifier with 5,333 assertions passing and the 8 new capacity, six-chunk audit, helper, and prompt assertions failing.
- [x] Implement Codex-only six-chunk patch reads with the separate 144 KiB ceiling, exact consecutive chunk hashes/order and the existing mixed-read and per-read audit checks unchanged. Normal review found and fixed the stale three-chunk rejection assertion and inaccurate window-mode prompt claim; re-review caught fixture indentation and a seven-read grouping error, both corrected before CI.
- [x] Inspect exact-head run 41311497176. Proof preparation passed; Ubuntu and macOS reached the verifier and each reported five fixture/assertion mismatches. Correct the batch-six turn count, Terra's Codex limit, the expected oversized-batch violation, and window-mode prompt assertions. Independent normal re-review found no actionable issues; guarded syntax and diff checks pass.
- [ ] Pass exact-head CI and package checks.
- [x] Complete independent normal re-review of all corrected findings; the reviewer confirmed the heredoc, seven-read rejection, and window-mode prompt corrections with no remaining actionable issues.
- [x] Integrate current Review Council main e1d2feaa into the local PR branch. Merge commit fa70d45; not pushed.
- [ ] Push the reviewed branch and merge only after all required current-head gates pass.

## Luna per-turn command budget follow-up

- [x] Trace the matched #1830 failures to the Codex per-turn two-command ceiling; aggregate read budgets were not exhausted.
- [x] Add a regression proving a Luna turn can use the observed five calls while Sol remains capped at two; CI confirmed the pre-fix behavior, alongside stale prompt assertions and one separate macOS stack timing failure.
- [x] Implement a model-specific six-call Luna turn cap with the existing byte, scope, ordering, read-budget, proof, and four-attempt limits unchanged.
- [x] Correct exact-head CI assertions to match the numeric limits generated for Luna and Sol; independent normal review found no issue.
- [x] Pass implementation exact-head CI and package validation on head `b27b4bf` in run `40390452887`.
- [x] Bump all plugin manifests, changelog, and release instructions to 0.8.14; independent normal review found no issue.
- [ ] Pass final exact-head CI, squash-merge, and publish the signed 0.8.14 release.
- [ ] Replay a large scope on released Luna and compare first-attempt validity and runtime to the preserved Sol evidence.

# Issue #77: Luna reviewer proof reliability

- [x] Fix the reviewer launch root and publish signed 0.8.3.
- [x] Make prepared packet ranges usable as source proof and publish signed 0.8.4.
- [x] Correct Codex fixed-string search guidance and publish signed 0.8.5.
- [x] Repair navigation packet byte accounting and publish signed 0.8.6.
- [x] Collect the first post-0.8.6 sample: 5 rejected first attempts in 20 seats (25%).
- [x] Trace the five failures to 3 expansion-budget gaps and 2 source/patch-read audit failures.
- [x] Reconcile the pending evidence-order and prepared-source prompt work with the 0.8.6 baseline.
- [x] Add regressions for complete patch-chunk reads, explicit no-context source targets, and risk-scoped proof budgets.
- [x] Fix the two reproduced prompt/audit mismatches and give affected no-context source-required seats additional expansion capacity.
- [x] Complete independent internal review and resolve its actionable P2 finding.
- [x] Pass expected-red and all required current-head CI checks.
- [x] Squash-merge PR #83, publish signed release 0.8.7, reinstall all hosts, and verify installed identity.
- [x] Release 0.8.9 with per-prepare source-context reconstruction memoization.
- [x] Trace historical #1830 proof-read turn counts and inspect the retired compound-batch failure.
- [x] Draft the separate-read pairing design and receive a clear builder check.
- [x] Get approval of the pairing design before writing its implementation plan.
- [x] Implement the approved source-context memo scope with red-before-green tests, normal review, exact-head CI, and release.
- [x] Add a 6x aggregate repository-read budget for actual Luna model seats, with source, scope, ordering, per-response, and output-byte proof bounds unchanged.
- [x] Prove the new per-model limits fail on a test-only CI commit.
- [x] Implement and pass normal internal review plus exact-head proof-preparation, Ubuntu, macOS, and Cursor package CI.
- [x] Add regressions for Codex prepared-evidence reads and post-index investigation across real explicit turns without changing per-read, ordering, scope, or output limits.
- [x] Stage prepared Codex proof artifacts when present, and run no-manifest custom reviews through bounded resumable turns, then finalize findings in a tool-free turn.
- [x] Make Claude's existing two-read source-turn allowance explicit so large reviews do not spend one model turn per required segment.
- [x] Complete normal internal review and exact-head CI for the staged Codex runner.
- [x] Squash-merge and publish signed 0.8.11, reinstall all hosts, and verify installed identity.
- [x] Run the matched post-merge #1830 Luna replay and update the eligible post-0.8.9 failure rate.
- [ ] Monitor fresh post-release first-attempt Luna results until the failure rate is below 5%; keep issue #77 open until then.
- [ ] Correct status reporting so a prompt without seat launch evidence is not labeled as a provider review in progress.
- [ ] Publish first attempt records atomically so cancellation cannot leave an empty record that blocks same-label retry.
- [ ] Read launch marker state and its duration from one file snapshot.
- [ ] Hold PR progression while an Agent launch marker has no terminal exit.

The expected-red CI run 40280999224 is terminal on Ubuntu and macOS. It exposed the intended usage-snapshot and exact post-index target failures, plus fixture assumptions that counted Codex turns as provider launches, relied on `/tmp` string identity, and selected native review mode while expecting a custom-prompt audit. Those fixtures are being corrected alongside the local production fixes before the next exact-head CI run.

PR #93 exact-head run `40296296699` at `09eaa4d` passed proof preparation and failed one Ubuntu assertion (5,187 passed): the no-manifest fixture compared an absolute temporary `--output-schema` path with a bare filename. The adapter command is correct; the fixture now verifies absolute review-schema paths under the generated staging directory and binds the final schema to the expected fixture. The package run passed and macOS was still running when this failure was recorded.

Independent normal re-review of the fixture correction found no actionable P0-P2 findings. It verifies absolute schema paths, the shared generated directory for review-turn schemas, and the exact expected findings schema.

The 0.8.3 fix resolves a confirmed launch-root mismatch. It did not resolve the Luna proof-budget failures. In `r3p`, the three locale ranges named by the incomplete result were already present in required source-context packets, but the reviewer spent its limited post-index calls reopening other source. In `r2-codex-luna-3`, the reviewer read repository source before the evidence index. The prompt's numbered required-read sequence omitted the index.

For 0.8.11, the selected Luna allowance is six times the standard per-seat aggregate repository-read budget. Keep per-response byte ceilings and proof validity rules unchanged; the larger allowance is for more ordered, in-scope reads.

Exact-head verifier run `40292649184` on `a9f500dc` failed the same no-manifest continuation assertion on Ubuntu and macOS: each platform passed 5,187 checks and failed one, because the second recorded invocation was a fresh `exec` instead of `exec resume`. The adapter now uses its established thread ID as the sole fresh-versus-resume signal. Independent normal review is clean; fresh exact-head CI is still required.

The user chose to keep the four-reservation per-seat adapter attempt cap and count resumable provider turns separately; do not turn it into a four-turn limit. Codex JSONL exposes cumulative thread token totals on completed turns, so profile usage differences validated snapshots, discloses resets or malformed snapshots, and leaves dollar cost unknown when the stream does not define its scope. `rev-profile.py` reports audited read-turn totals separately from calls.

The active #1877 review provides a concrete 0.8.9 budget sample: Luna-2 was instructed to stop required reads at call 12 and use at most 16 repository calls, while its prepared workload named 35 required source segments. Its audit recorded 44 source-read calls and both `repository-expansion-call-limit` and `path-outside-scope`; 0.8.9 classifies the budget code as advisory, while the scope violation is fatal and explains exit 2. The larger budget addresses the overage and wasted follow-up, but preserves rejection of out-of-scope reads.

The frozen #1830 replay identifies a separate audit-history issue: 0.8.8 counted each Codex tool output as a turn despite one explicit `turn.started`/`turn.completed` pair, accepting oversized batches. The 0.8.10 parser counts the explicit turn and correctly rejects the output overflow. The adapter and prompt files are unchanged between those versions, so this was an old false pass, not a new 0.8.10 prompt regression.

The matched 0.8.10 #1830 replay exposes the adapter gap behind that rejection: all four Luna attempts and all four Sol replacements emitted 18-27 tool calls in one explicit Codex turn, with 76-206 KB of output and missing or reordered proof. The prompt allowed up to two ordered reads per turn, but `codex exec` kept the entire run inside one explicit turn. The adapter needs to stage required artifact reads through resumable turns before the final review call; the proof auditor and its byte ceilings remain unchanged.

That frozen replay completed against the same source tree for every seat. The 0.8.8 audit had accepted the same one-turn stream shape by inferring a separate turn for each tool output, so the historical Sol result is a false pass. Replaying with 0.8.10 verified the corrected audit rejects the batch. The matched 0.8.11 Luna replay is now complete: all four Luna first attempts exited 2 without sealed audits, with 49 calls, 29 provider turns, 382,153 output bytes, all 28 required artifacts read plus one duplicate index read, and 20 post-index expansions. The Luna-2 Sol replacement exposed command-ID reuse across explicit turns; the other initial Luna failures hit turn-local call/output guards. None exhausted the sixfold aggregate allowance. Four selected replacements were valid (three Opus, one Sonnet). The first Luna panel took 348.3s and the full replacement path took 6,506.5s. The 0.8.8 Sol reference reported 4/4 first-attempt success in 288.8s, but its turn count is the known false pass, so only elapsed time is comparable. Issue #77 stays open; a matched current-parser Sol result is still needed before claiming equal proof success.

The live #1894 run confirmed both sides of that gap at larger scale. Its four Luna seats required 193, 180, 22, and 16 source segments; each raw stream still contained one explicit turn. The largest seat made 202 prepared-evidence reads and then 17 post-index reads with 46,371 bytes of output in that same turn. All four results were rejected for proof violations. The runner therefore needs resumable turns for prepared reads and for bounded post-index investigation. The 6x Luna call allowance addresses the observed 17-call overflow; it does not relax the two-read batch, 32 KiB output, scope, order, or exact-evidence checks.

Fresh #1880 round 5 artifacts show a related 0.8.9 budget result. Luna returned INCOMPLETE PROOF after its 16-call investigation budget with no audit violations. Luna-2 and Luna-3 returned findings, but each raw stream has one actual Codex turn and 397-408 KB of output; the old audit reports 56 inferred turns. Luna-4 stopped after four calls and 98 KB, before reading the remaining evidence. Under 0.8.10's explicit-turn audit, the first three old receipts would fail the per-turn output bound. This is a parser-era false pass, separate from Luna's aggregate call-budget exhaustion.

The staged 0.8.11 runner retains the current two-read and 32 KiB bounds. The #1894 largest Luna workload has 193 separate required source ranges across 178 paths, so those source segments alone require about 97 prepared turns, plus patch, packet, and index reads. Measure that latency on the matched replay after release; any packetization follow-up must preserve each range, order, and byte limit.

The live #1894 Sonnet replacement in `r1x2` failed twice with exit 2 after 9 and 10 turns, without findings JSON or a read audit. Raw streams show only clean patch reads and a few source queries before `hook_stopped`; they contain neither an API/auth error nor a rejected read. The Council retried the assignment, then advanced to Sol. Keep this separate from Luna budget exhaustion and do not claim the stop source without stronger evidence.

The next #1894 Sol replacement returned a result, but the 0.8.10 audit rejected it: 25 repository reads produced 158,236 bytes in one explicit Codex turn, exceeding the turn-output limit. No single tool output exceeded 15 KiB. This directly confirms that the adapter must resume between bounded read batches, not merely increase call budgets or single-read limits.

The following #1894 round 2 uses four Luna seats on installed 0.8.10. Luna-4 is incomplete proof after 28 calls and 104,030 output bytes in one explicit turn; the largest single output was 9,006 bytes, and its unfinished checks name the changed consumers and Playwright/Android fixture lifecycle. The audit rejected the one-turn aggregate output. Two sibling Luna seats returned valid empty findings while a third was still reviewing at the latest poll.

The #1894 round 2 prompt has no evidence manifest, so `codex-proof-stages.py` returns zero prepared stages and `seats.d/codex.sh` falls back to a single ephemeral `codex exec`. That leaves large direct-source reviews exposed to the same one-turn audit failure. The runner must use bounded resumable review turns even when there are no prepared proof artifacts; its first turn must not claim any evidence was staged.

The live #1894 round 3 reproduces this failure across all four Luna seats: their raw streams each contain one explicit Codex turn, 16-34 repository calls, and 84-117 KB of output. All four audits reject the aggregate output; two summaries also correctly stop at the 16-call investigation limit before assigned checks finish. Luna-3's P2 is also rejected for an unsubstantiated source range. This is the same no-manifest one-shot runner defect, with the budget exhaustion remaining a separate proof gap.

The current #1894 round 4 confirms the same cause on 0.8.10: all four Luna attempts exited 2 with one explicit turn, 23-44 reads, and 102-216 KB of command output. Audits reject missing or reordered prepared evidence, oversized evidence batches, and one-turn output overflow. This is covered by the staged, resumable runner without relaxing proof limits.

PR #93 adds Codex usage-profile regressions because `turn.completed.usage` carries cumulative thread totals. Its test-only commit `dc5e7ff2271bf8010551abed6379a4b494394918` has proof preparation and Cursor packaging green. Expected-red run `40280999224` is terminal: Ubuntu and macOS both failed on the intended usage-delta and exact post-index proof regressions, along with stale fixture assumptions recorded above. The normal internal review found and closed two P2 accounting risks: preserve input/output from legacy two-counter streams, and do not infer uncached input when Codex omits cache counters. Its final review of the complete local diff is in progress. The implementation and fixture corrections remain local until that review finishes, then they will go to an exact-head CI run.

The separate #1894 `r1x5` status still says its Sol replacement is running after more than an hour. Its 207-artifact evidence manifest, including 193 required source ranges, three source-context packets, and 112 projected review turns, and its prompt were ready at 03:46-03:48 UTC, shortly before the controller marked the seat running at 03:53 UTC. This rules out the hypothesized 53-minute preparation delay; the 112 turns include 97 for required source segments, so the assignment is expensive if launched. The status has not advanced since 03:56 UTC. There is no seat log, stream, result, exit, attempt record, panel lock, or matching CLI process. The wrapper normally creates the log before invoking the adapter, so the seat likely never reached provider invocation or was killed before it, but missing historical stage logs prevent a stronger cause claim. This is stale lifecycle reporting, not evidence of a slow provider or slow source preparation. In #1894's second session, the one-seat Grok workhorse plan is an actual live process, now running about 16 minutes with a 7 KB prompt and no output so far; keep monitoring it without inferring provider failure. The fresh `r3x3` Sol replacement completed in about two minutes, reported a P2, and entered triage; its audit is invalid for one-turn output overflow and an unsubstantiated citation, so the finding is not verified.

The 0.8.10 status scripts call every prompt with no exit file “running,” even when no seat log or agent transcript exists. In #1894 `r1x5`, the prompt exists but there is no launch log, so the displayed 106-minute run is not evidence that Sol started. Correct this separately from the source-proof changes so the release can stay focused.

Expected-red run `40268778865` on `491887724871dae0648e59966226b644588ad5d9` completed on both OSes. Proof preparation and Cursor packaging passed; each verifier recorded 5,168 passing assertions and 4 failures across 3 tasks: the Luna budget assertion still expected old prompt wording, the Claude batching instruction was missing, and Codex patch-chunk stages lacked their command field and failed before provider launch. The budget prompt already printed 120 total calls with 24 reserved; the test now checks the current rendered contract. The command field and Claude instruction are fixed in local commits `fa2a7dd` and `a08db37`.

The no-manifest resumable-turn regression is isolated in test commit `fa2a7dd`; exact-head test run `40271013311` on `a08db375d2a2cb40656f81627711543243e3b1b1` is the completed expected-red proof, and its Cursor package run `40271013303` passed. The red run confirmed the regression before the uncommitted adapter changes.

The internal reviewer found a P2 in the no-manifest path: any repository read could satisfy a required post-index source target. The worktree now parses and hash-checks the named path and range, requires the evidence index to be read completely first, and accumulates byte-verified target windows across later explicit turns. Regressions cover unrelated reads, same-turn ordering, and a 250-line target split at the 200-line Codex source limit. These changes still need CI and a follow-up internal review.

Expected-red run `40247606189` on test-only commit `b511dacb2f04b7be6dc107eee521cf2fac66bfb2` failed only the new model-specific budget assertions on Ubuntu and macOS; each platform passed 5,160 assertions and failed 4. Proof preparation passed, and Cursor package run `40247606175` passed.

Expected-red run `40250312984` on test-only commit `34f2f81ee3a0b005fa68cfc264e4f0abc82d737e` failed the new legacy schema-1 Luna reserve-display assertion plus the four model-budget regressions on both Ubuntu and macOS. Each platform passed 5,160 shell assertions; all 582 Python tests and proof preparation passed. Cursor package run `40250312987` passed.

Expected-red run `40257552976` on test-only commit `60f8677ff6d0487a7ea94f51d7c8cb3ceb6e92d0` passed proof preparation and failed the intended verifier assertions on both platforms: the manifest-free Luna audit/prompt still used the shared budget, and prepared assignments did not pin the roster model. The failure logs also confirm the staged implementation fixes are absent from that frozen test head.

Live 0.8.9 sessions `#1837`, `#1844`, and `#1880` expose another version boundary: the 0.8.9 auditor reported 20-43 turns for streams containing one explicit Codex turn, because it assigned implicit turns to individual calls. The 0.8.10 parser tracks actual `turn.started` / `turn.completed` boundaries, so those old “valid” receipts are false passes for large proof batches. The #1830 replay's one-turn rejections are consistent with the corrected parser.

PR #83 merged as `6be75ef10b46db6159337bddb3b8dcb074aa6ff1` from `656212573ae690c4cbc8047a23d4ecf64f339260`. Exact-head test run `40175923246` and Cursor package run `40175923301` passed. Signed release `review-council--v0.8.7` was published, and Claude, Codex, and Cursor installs match the release. Issue #77 remains open because no eligible first-attempt Luna sample pinned to 0.8.7 or later has completed.

PR #79 merged as `383218599c6efc4cb812821740fc77e9ca67d9f3`. Required PR-head CI passed on `25c3154bca9045b0caa239a06cbd992ba4ef5be8`; the release tag is signed and published. Claude, Codex, and Cursor 0.8.3 installs match the released source or CI package by file and mode identity.

Merge-triggered main gate `40142430721` passed on `383218599c6efc4cb812821740fc77e9ca67d9f3` on Ubuntu and macOS, with proof preparation also passing.

An independent normal internal review and follow-up re-review found no actionable P0-P2 findings. The follow-up confirmed packet ranges count as proof only after exact packet reads, while uncovered sites, required source reads, and the existing call and output limits remain enforced.

Expected-red run `40142951169` on test-only commit `3207ae860e2ae37b295e1fc113f0087411a7cd9f` failed only the two new prompt assertions for each of four seats on Ubuntu and macOS. Each platform passed 5,098 assertions and failed 8; proof preparation passed.

Candidate run `40144222587` on `7ee84f6b5ac0c236e36a06335d04514886756e9e` exposed four existing cost-mode assertions that require source-context-disabled prompts to omit packet guidance. Each platform passed 5,102 assertions and failed 4; proof preparation passed. Prompt and footer wording now depend on the prepared packet and segment list.

Final candidate run `40145281389` on `3da7ae1ce7e2bd115320e02fa4863814651043e3` failed the same prompt assertion four times per platform. The risk-phase fixture has source-context packets but no required source segments, so its expected index wording must mention packets only. Run `40146454334` on `b0765d0a2cd4780559b3702b9456cad216374ca8` exposed the same format assumption in the added plan fixture: plan source obligations render as cluster sources, while its relevant ranges are in packets rather than generic source segments. The test now checks the assigned cluster-source obligation and packet-only index ordering. The current 0.8.6 baseline already contains the ordered index and packet-as-proof behavior, so the stale branch changes are not reapplied.

## Post-0.8.6 sample and 0.8.7 repair

The first post-0.8.6 sample is 25%, so 0.8.6 does not meet the issue target. Three seats exhausted the 16-call expansion budget while proving assigned behavior. Two audits failed on source-read issues: one assignment had no rendered boundary target, and a chunk-mode prompt combined full-chunk reads with later line-window instructions. Keep the global budget at 16, add a narrow reserve only for source-required seats without prepared context, and make source targets and chunk read shapes explicit.

Expected-red run `40171439450` is on test-only SHA `2018c6f38607996c3710c7624111a49d6cc8eff5`. Proof preparation passed. Ubuntu and macOS each passed 5,122 assertions and failed 9 across only the three new regression groups for chunk reads, the assigned no-context boundary/budget, and the 20-call audit bound. Cursor package run `40171439488` passed on the same SHA. The failed assertions are intentional and recorded in both OS artifacts.

P1 regression run `40172561766` is on test-only SHA `56cedf15fe3e51ac7cf26359a8bbcedff4c9c896`. Proof preparation passed. Ubuntu and macOS each passed 5,122 assertions and failed 10 across only the three intended regression groups; both added deleted-boundary assertions failed because `000-deleted.py` was rendered instead of live `a.txt`. Cursor package run `40172561840` passed on the same SHA. The selector now filters component boundaries against regular files in the frozen snapshot. Independent internal re-review confirmed the P1 fixed and found no additional actionable P0-P2 issues. Guarded local `git diff --check` was initially refused at load 6.10 (exit 75), then passed once load fell below the limit.

## PR #84: Retry-safe semantic receipt publication

- [x] Add a regression reproducing interruption after publishing a successor receipt but before advancing `coverage-head.json`.
- [x] Confirm the regression fails on the exact test-only head for the intended head-promotion assertion.
- [x] Advance the head on retry only when it still matches the successor's recorded predecessor; preserve a newer head.
- [x] Complete an independent internal review, resolve actionable P0-P2 findings, and re-review.
- [ ] Pass exact-head macOS, Ubuntu, and Cursor package CI, then squash-merge and publish signed release 0.8.8.

Expected-red run `40177694903` on test-only commit `645ecb8644e536dd9e8cc9ba67124fd4467da715` failed only `semantic_rejection_retry_promotes_existing_successor` on proof preparation, Ubuntu, and macOS. All other shell tests passed on both platforms, and Cursor package validation passed.

The independent internal re-review confirmed the retry fix advances the head only from its recorded predecessor, preserves a later panel's head, and found no actionable P0-P2 findings.


The active wallet PR #1830 review is initialized at 0.8.4 and is excluded from the post-release denominator. Its original Luna-2 audit was valid but returned INCOMPLETE PROOF after using all 16 post-index repository calls before checking sibling direct-switch callers and the production copy; the audit itself had no violations. At 09:04 UTC, the plan review remains 0/1 with 8 P1/P2 findings open and no fixes; its Sonnet escalation is still running at 286 minutes. It is not a Luna attempt.

The active wallet PR #1844 review is initialized at 0.8.6 and is excluded from the post-0.8.7 denominator. At 09:04 UTC, one of four seats returned a valid Luna result and three Luna seats were rejected for proof/audit failures. Two exceeded the repository expansion-call limit and missed required source reads; the third also had unbounded shell output, unsupported source ranges, and incomplete assigned patch-chunk reads. These are not provider failures. Its separate base Luna report found a P1 that the wallet review owner is handling.

# Luna seat repository-root fix

- [x] Confirm that `rev-seat.sh` ignores the reviewed session's frozen `REV_ROOT`.
- [x] Add a regression for launching from outside the reviewed repository.
- [x] Confirm the regression fails on the test-only commit in CI.
- [x] Resolve the seat root from `scope.env` and preserve legacy fallback when scope metadata is absent.
- [x] Complete one independent normal review and resolve its P2 finding.
- [x] Pass required checks on the exact PR head.
- [x] Squash-merge and publish a signed release with the fix installed.

The active wallet PR replacement was launched from the home directory while its session scope points at the wallet checkout. The runner therefore assigned the wrong root to both its adapter and read audit. The session scope is the audited authority for that review.

Final-head run `40141054096` passed proof preparation and release-tree verification on Ubuntu and macOS, and Cursor package run `40141054102` passed on the same source tree. PR #79 was squash-merged, signed tag `review-council--v0.8.3` was published and verified, and the release was installed on Claude, Codex, and Cursor.

The expected-red test-only run `40139997146` on `347b673d3cb521a103ed6935d96477b5d0c987c4` failed only the two new repository-root assertions on Ubuntu and macOS. Each platform passed 5,093 assertions; proof preparation and Cursor package validation passed.

## Review

Initial normal review found one P2: shell-quoted repository paths containing apostrophes were not decoded by the shared scope parser. The parser now uses `shlex.split`, and the seat regression covers an apostrophe path. Follow-up review confirmed the fix and found no actionable P0-P2 findings.

# Issue #77 and release 0.8.2

- [x] Compare issue #77 with current main and verify the signed 0.8.1 release.
- [x] Add a regression for optional tests blocked by missing tools or an unwritable package cache.
- [x] Clarify that optional test environment limits leave runtime validation unverified; preserve incomplete status for required proof or exhausted review capacity.
- [x] Align the three plugin manifests, changelog, and release procedure at 0.8.2.
- [x] Complete one independent normal review, fix actionable P0-P2 findings, and pass all required CI checks on the exact PR head.
- [x] Squash-merge, publish the signed 0.8.2 release, reinstall each host, and verify installed identity.

The read-shape instructions and advisory audit codes were already present on 0.8.1. This release targeted the remaining reproduced optional-test environment case and kept the audit fail-closed when required evidence is incomplete. PR #78 merged and signed release 0.8.2 was published.

Expected-red run `40128169457` on test-only commit `b862620d1be54359eb84b4d67059999724bc9c44` reached the new prompt assertions on both Ubuntu and macOS and failed them as intended: each platform passed 5,076 assertions and failed 8 across the four adapters. Cursor package validation and proof preparation passed on that exact head.

## Review

One normal reviewer found a P2 test gap: the optional-test exception needed an assertion that unread assigned evidence and exhausted review-call budgets still require `INCOMPLETE PROOF`. The assertion was added and re-reviewed at `6c7a22c`; no actionable P0-P2 findings remained before PR #78 merged.

# Release 0.8.1 follow-up

- [x] Pull the latest stable Council release into the 0.8.1 candidate and preserve the completed normal internal review.
- [x] Run current-head CI and retain its exact Linux, macOS, proof-preparation, and packaging results.
- [x] Correct the failing verifier cases: ambiguous TypeScript project candidates, replacement-chain identities, deterministic live-status polling, and canonical paths through a symlinked temp root.
- [x] Correct the workflow test to assert the actual `proof-preparation` job key.
- [x] Complete normal internal review and correct its P2 finding about the stale CI handoff status.
- [x] Diagnose the next exact-head failures: the workflow test searched for a literal `\\n`, and the stack-test fixture omitted `rev-context.py` beside its temporary `rev-status.sh`.
- [x] Fix the workflow split to use a newline and initialize fake session state before the delay.
- [x] Add the missing status-context symlink to the stack-test fixture.
- [x] Complete normal internal review of the fixture correction and push it.
- [ ] Pass proof-preparation, Ubuntu, macOS, and Cursor package CI on the exact final head.
- [ ] Squash-merge PR #74, publish the signed 0.8.1 tag and release, install it on Claude, Codex, and Cursor, and verify each installation.

PR #74 is at `cf6baa078bf0afbc51cbfa5996d8f91b0419a89a`, based on latest `origin/main` `58862c988d545dee67f79fafdf0e8008a4e66632`. Old-head run `40061351310` confirmed the escaped-newline Python error and the stack status-line failure. The newline and state-timing fixes are on this candidate. On `40062066942`, Ubuntu's 519 Python tests passed, but the shell gate still failed because its temporary `REV_SCRIPTS` directory linked `rev-status.sh` without the required adjacent `rev-context.py`. The test fixture now links that companion, and normal internal follow-up review found no actionable P0-P2 findings. Exact-head proof preparation and Cursor packaging passed; macOS is still running.

# Release 0.8.0

- [x] Verify and merge the latest signed release, `review-council--v0.7.14`, into the candidate.
- [x] Bind PR-number preflight to the live head and base before provider probes.
- [x] Preserve the exact PR identity in session inputs and reject a checkout change before evidence preparation.
- [x] Continue failed review assignments through multiple replacements until success or chain exhaustion.
- [x] Set all three host manifests and the release procedure to 0.8.0.
- [x] Push tests-only regressions and confirm expected failures for PR pinning, quota fallback, repository binding, and replacement-chain certification.
- [x] Finish and re-review the exact-PR renderer/evidence checks and all internal-review fixes.
- [x] Integrate PR #69, signed tag `review-council--v0.7.12`, into this candidate.
- [x] Fetch and merge latest `origin/main` at `ff13856` in merge commit `f562d78`.
- [x] Complete the one-seat normal internal review and merge the combined candidate as PR #67.
- [x] Publish signed 0.8.0 as explicitly authorized, preserving the exact failed run for the 0.8.1 follow-up.

## Release review

- Expected-red run `40010322339` confirmed on Ubuntu and macOS: `prepare --head <other>` succeeded, omitted the pinned-PR refusal, and published a manifest before the fix.
- The latest stable source is the signed `review-council--v0.7.14` tag, now merged into this candidate.
- The normal one-seat internal review found a P1 exact-PR identity gap and a P2 live-PR drift gap. The follow-up review found three more P2 gaps: quota fallback dropped the PR number, evidence could certify an unknown replacement family, and ambient `GH_REPO` could select the wrong repository. Regressions and fixes are now prepared locally.
- Expected-red run `40028556658` confirmed the new PR pinning, live metadata drift, quota fallback, repository binding, and replacement-family regressions on both Ubuntu and macOS. Package CI `40028556537` passed on the same test-only commit.
- Full verifier run `40031235290` finished with the same placeholder-family replacement-fixture failures on Ubuntu and macOS; the multiple-replacement test through Opus passed on both. Updated the affected fixtures locally and queued normal internal review before the next push.
- The first internal fixture follow-up caught an idempotent duplicate-label assertion. Reparenting to Opus exposed a bundle mismatch, so the retry now carries Opus's assigned bundle and reaches the rebinding check; requested another focused re-review.
- The focused normal internal re-review confirmed the fixture now reaches the intended rebinding refusal and found no open issues.
- Normal one-seat internal review completed with no open P0-P2 findings and verified closure of the three follow-up gaps above. Review Council was not used to review its own repository.
- Current-head CI run `40034257541` exposed three stale test fixtures: a Codex executor expected Claude in its receipt, a review-origin replacement used identities outside the enforced chain, and the preflight stub reused `PR_HEAD`, which the script clears internally. Corrected those fixtures and passed normal internal review.
- Baseline verifier `40025636171` failed on both platforms at `39724b5`: a shell quoting error in preflight broke its embedded Python, and plan-gate fixtures did not provide 0.7.11's required manifests. Both root causes are fixed in local commit `e54e369`; macOS's 476 Python tests passed. Package CI `40025636204` passed.

## Internal review follow-up: exact PR identity and live evidence scope

- [x] Add regressions for renderer PR pinning, evidence checkout/live metadata drift, quota fallback identity, ambient repository overrides, and enforced replacement families.
- [x] Pin exact PR number and repository, recheck live PR identity during evidence preparation, and keep quota fallback bound to the same PR in both hosts.
- [x] Run the expected-red gates and send the complete implementation diff for normal internal re-review.
- [ ] Push the reviewed implementation and wait for current-head macOS, Ubuntu, and Cursor package CI before release work.

The rolling 180-minute sample ending 2026-10-23 23:25 UTC contained 74 Luna audit
artifacts under `/private/tmp`: 11 were invalid (14.9%). They are attempts, not
independent seats. Eight invalid artifacts exceeded both the tool-output and whole-turn
limits; four also exceeded the discovery-output limit, and codes overlap. Other observed
causes included unbounded shell output, unsupported source batching, invalid source
context, search expansion, and unsupported ranges. In #1752, repeated 240-line Codex
reads returned 44-45 KiB against a 32 KiB hard cap, while a `head -81` example exceeded
the 80-result audit rule. A Luna plan assignment passed with four bounded patch chunks
and a 24,562-byte maximum output. This points to prompt and audit-contract mismatches,
not finding quality. Codex patch and repository source windows now use 40 lines across
prompt, audit, and capacity estimates; the prompt targets 24 KiB with a 32 KiB hard cap.
Compiler-rendered searches are quoted, manually composed searches reject shell expansion,
and result searches remain capped at 80. Fresh independent review found no remaining
actionable P0-P2 issues. `git diff --check` and `bash -n` preflights pass; the full tests
were not run locally. Exact-head CI will be recorded, and the user authorized publishing
0.8.0 with failures followed by a 0.8.1 correction release.

# Release 0.8.1

- [x] Pull the merged 0.8.0 source and inspect the exact main CI failures from run `40054245261`.
- [x] Fix deleted-reference proof, explicit PR repository path validation, and replacement failure precedence.
- [x] Correct stale plan-read, repository-call, search, workflow-split, and progress-monitor fixtures.
- [ ] Finish the normal internal review and apply actionable findings.
- [ ] Push the candidate PR and require proof-preparation, macOS, Ubuntu, and Cursor package CI to pass on the exact head.
- [ ] Squash-merge, publish signed 0.8.1, reinstall all hosts, and verify installed versions and file identity.

## 0.8.1 follow-up evidence

- Main CI run `40054245261` failed on `58862c9` in proof preparation, the Python verifier, and the shell verifier on both operating systems. Complete artifacts are preserved under `/tmp/council-main-40054245261`.
- The 0.8.1 candidate is not yet CI-validated. Release remains blocked until all required checks pass on the exact candidate head.

# Release 0.5.10

- [x] Let `codex_models` repeat an entry, one numbered seat per entry, up to four.
- [x] Match Claude and Codex manifests, changelog, and release procedure at 0.5.10.
- [ ] Run the roster tests and the candidate gate in CI.
- [ ] Open the pull request.
- [ ] Review the candidate with signed stable 0.5.9. Repair verified P0/P1 only.
- [ ] Wait for required CI, squash-merge, and publish the signed 0.5.10 release.
- [ ] Reinstall on Claude and Codex and check `rev` and `stack` at 0.5.10.

# Release 0.5.9

- [x] Bind `latest-sol` and `latest-luna` to the seat CLI catalog (issue 32).
- [x] Match Claude and Codex manifests, changelog, and release procedure at 0.5.9.
- [ ] Run the latest-roster tests and the candidate gate.
- [ ] Open the pull request.
- [ ] Review the candidate with signed stable 0.5.8. Repair verified P0/P1 only.
- [ ] Wait for required CI, squash-merge, and publish the signed 0.5.9 release.
- [ ] Reinstall on Claude and Codex and check `rev` and `stack` at 0.5.9.

# Release 0.5.8

- [x] Confirm main is `8a8104e`, one commit after the signed tag `review-council--v0.5.7`.
- [x] Prepare matching 0.5.8 manifests and release notes.
- [ ] Run the complete frozen candidate gate.
- [ ] Push, wait for CI, and squash-merge.
- [ ] Publish the signed tag and GitHub release.
- [ ] Update Claude, Codex, and the Grok marketplace checkout. Verify `rev` and `stack` at 0.5.8.

### Release review

The stable release panel is explicitly waived for 0.5.8. Anthropic seats are out
of tokens, so a four-seat stable review cannot complete. Publication stays gated
on the deterministic candidate gate and green CI. This release is not
Council-certified.

# Release 0.5.7

- [x] Confirm the retained wave 1 and wave 2 changes and discarded experiment scope.
- [x] Verify the signed stable 0.5.6 tag and inspect remote PR and release state.
- [x] Prepare matching 0.5.7 manifests and release notes.
- [x] Run the complete frozen candidate gate and resolve the stable release-review requirement.
- [ ] Push and squash-merge the three stacked PRs with exact-head green CI.
- [ ] Verify the merged release tree, publish a signed tag and GitHub release.
- [ ] Update both installed hosts and verify version, source identity and skill discovery.

### Release review

The stable release panel is explicitly waived for 0.5.7. Publication remains gated
on deterministic verification and green CI. The local candidate gate passes 354
shell cases, 4,701 assertions, 229 Python tests and all three validators. Single-seat
benchmark results do not certify the release implementation. The release procedure
now names the latest Sol and Luna families at xhigh, preserving exact frozen run
identities and supported maximum effort for Opus and Sonnet.

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
- [x] Verify the final functional source against the complete gate and commit measured outcomes.
- Draft stacked delivery and exact CI results are tracked in the final PR.

The instruction components remain private and unretained. The combined runtime
passes the dispatcher but fails the independent clean holdout depth floor. Mean
holdout quality rises 92.19 to 92.50 while minimum stays 86.25; the mean cannot
override that failed case gate. No scoring policy or rubric was relaxed.

### Next bounded experiment

- [x] Validate a private immutable snapshot batch contract with real captured tool output. Sixteen new tests and 182 existing focused checks pass; no production adoption.
- [x] Test a general caller/state-flow inspection cue without fixture-specific hints; the clean holdout fails its quality floor.
- [x] Run finite heldout measurements only after local proof and prompt contracts pass; keep proof-invalid measurements separate.

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

### Finite-completion screen

Two Luna/xhigh calls complete with valid proof, no probes, graders or retries.
Both avoid empty patch probes. All five faults are found with accurate citations;
complex quality is 98.75 and clean quality 86.875. Pooled credits fall 15.69% and
provider time 16.00%, but the clean floor fails. The combined runtime is discarded.
The private immutable-source prototype passes its local lane and exact reused-control
identity check; a separate two-call heldout screen is running.

### Source producer validation

The immutable-source screen completes both paid executions, but both exact audits
fail on merged Apple Git sandbox diagnostics. Full quality remains unknown and
no qualified savings percentage is published. All raw artifacts stay frozen.
A separate producer correction will be tested locally before another finite stage.
The optional native live-file compound proof path is independently retired after
587 focused assertions and 21 unchanged-prompt comparisons. Its new portable
regression is registered; the active complete frozen-source gate is running.

agentic-kb: codex-seats-git-show-base-fails-read-audit explains the merged sandbox
stderr failure and helped avoid loosening byte proof. Usage and a generic current
sandbox CLI recipe are pushed from an isolated clean KB checkout in 6914a65;
the original KB checkout's existing merge conflicts remain untouched.

The prospective proof correction passes the complete frozen gate: 354 shell cases,
4,701 assertions, 229 Python tests and all three validators. All five terminal
logs and hashes verify exit 0. Tested tree is
006cdc2c6212fe7ed76a08c4ac8c99fad53b557a94bd18c5c09664c05d2bb7ab.
Signed commit dbff79b retains only that independent correction. New result metadata
and task prose differ from the frozen tree; code, tests and fixtures are identical.

### Exact stderr suppression screen

- [x] Prove the real read-only sandbox failure and exact producer correction locally. Nineteen focused tests pass; warning-like source bytes remain unchanged.
- [x] Measure the signed corrected immutable-source candidate on both heldout cases with two fresh executions and unchanged frozen controls.
- [x] Retain only if each case passes fixed correctness, citation, source-flow and quality gates; the unchanged dispatcher transfer fails, so discard runtime changes.

Candidate db5dce0a0e546207548b9d0f93d568b109057b46 is isolated. No arbitrary
stderr stripping, score revision or reinterpretation of wave 16 is permitted.

Wave 17 passes both case gates: A 98.75 and B 91.25, mean 95.00 and minimum
91.25. Pooled estimated credits fall 20.05% and provider time 37.68%. Original
wave 16 remains invalid. An unchanged two-call dispatcher transfer is running,
with a private prospective integration preserving retired native compound proof.
No runtime is adopted before transfer and fresh paired validation.

### Completed transfer and stopping decision

Wave 18 finds all six dispatcher faults with accurate citations (98.00), but its
clean twin exposes no storage ranges and scores 80.00. Pooled credits rise 7.78%
and time 36.44%. The combination is discarded; the private prospective integration
remains clean at dbff79b with no code edits. Four-case mean is 92.00 versus 90.91,
minimum 80.00 versus 86.25. Lower pooled credits cannot override that failed gate.
Distinct evidence-backed cost mechanisms are exhausted for this pass; no further
paid cue retries or unmeasurable tool/prefix canaries are justified.

- [x] Preserve every completed stage, exact identities, manual adjudications and numeric comparison.
- [x] Reconcile 14 unique execution cost components and bind their public inputs.
- [x] Verify final metadata and commit the transfer disposition.
- Final draft-PR delivery and both operating-system CI results are tracked in the PR.

Final pre-push verification confirms all 285 tracked functional files match the
complete gate snapshot in bytes and executable modes. All five terminal logs
match receipt hashes and exit 0. Later changes are benchmark records and prose;
complete-case summaries, component totals and bound input hashes verify separately.

### Standalone component closure

The final untested component isolation uses two new Luna/xhigh executions with
control packets and source-read rules. Candidate source exactly matches wave 11.
Wave 19 scores A 98.75 and B 86.25: all five faults and accurate citations, but
only one clean source flow. Credits fall 8.44% and time rises 14.04%. The standalone
output instructions are discarded independently of packet and batching changes.
Their four-case mean is 93.15, minimum 86.25, pooled credits -8.46% and time +1.73%.
Six new executions and two reused controls are explicitly recorded. No scoring
policy, rubric or original stream changes. All evidence-backed screens are closed.

PR #29 at bb4c168 passes macOS and Ubuntu CI. The final added files contain only
wave 19 records and prose; functional code remains identical to that verified head.

## Cursor host and optional SDK Grok release

- [x] Verify official CLI automation support and known per-run isolation limitation.
- [x] User approved native Cursor host plus SDK Grok with strict qualification, unchanged defaults.
- [x] Builder check and detailed implementation plan complete.
- [ ] Task1 test-only contracts, normal review and actual expected-red CI.
- [ ] Task2 canonical bounded reader and SDK audit normalization.
- [ ] Task3 optional SDK driver, catalog, auth availability and runtime.
- [ ] Task4 roster/evidence/status/stack integration.
- [ ] Task5 native Cursor packaging/discovery and documentation.
- [ ] Task6 live qualification, normal cumulative reviews, full both-OS CI and signed release.

Review results: pending. SDK credentials absent; no live SDK qualification or product code exists yet. Existing wallet runtimes remain frozen.

## PR #67: Exact PR Binding and Exhaustible Model Replacement

- [x] Verify latest published Council is signed 0.7.14; Council changes use one normal internal reviewer, never Review Council.
- [x] Confirm the checkout-binding test-only CI red on both macOS and Ubuntu before implementation.
- [x] Confirm test-only checkout-binding and repeated replacement-chain regressions fail on both Ubuntu and macOS before implementation. CI run `40001522036` failed `replacement_chain_reaches_opus` with `assignment roster mismatch` after escalation advances; the same test-only head also has the expected checkout-binding failures.
- [x] Fix the candidate failures and align both host skill trees, fixtures, and replacement-chain assertions.
- [x] Re-run the frozen test-only failures and complete the normal internal review before the latest main merge.
- [ ] Finish normal internal review of the combined post-0.7.14 diff, then release and install 0.8.0.

### Current-head verifier repair

- [x] Run `40035902345` completed with the same `replacement_runs_on_another_seat` fixture failure on Ubuntu and macOS: it wrote a terminal exit without recording the launch attempts required by `rev-attempt.py`.
- [x] Correct the fixture so refusal is checked before two recorded terminal failures; syntax, diff check, and normal internal review pass.
- [x] Commit and push the fixture correction. Test run `40038629026` is on pre-merge head `6a4d6f31`; Ubuntu failed and macOS is still running. Package run `40038629054` passed on that old head. These do not satisfy the required post-merge-head gate.

### Candidate CI repair notes

### Live review progress narration

- [x] Extend `rev-status.sh` with a short narrative derived only from current session state, seat actions, and returned P0-P2 findings.
- [x] Preserve the existing compact status metrics for stack consumers, and update status, stack, and skill tests/docs.
- [x] Add regressions for normal config opt-out loading, pre-triage findings, and unresolved related-test evidence.
- [x] Push the first regression-only commit and confirm the intended narration/config failures on both verifier platforms. Exact-head run `40046718778` was red on Ubuntu and macOS; it also exposed existing 0.7.12 verifier failures that need a separate baseline assessment.
- [x] Add regression tests for long-running Codex watch narration and explicit TypeScript `files` roots in test-only commit `c42ed4c`.
- [x] Confirm the new watcher and explicit-files tests fail for their intended reasons before implementation. Exact-head run `40048223443` failed on Ubuntu and macOS; both logs show the narration, indefinite-watch, and explicit `files`-root regressions.
- [x] Fetch origin/main after the user requested an update. It advanced to `ff13856` and was merged as `f562d78`.
- [x] Test-only run `40050561834` confirms the live narration, watcher, and incomplete-result regressions fail on Ubuntu and macOS. Package run `40050561782` passed on that exact head.
- [ ] Repair the proof-preparation fixture that omits its assigned patch range, and fix current-main verifier failures when they are within the 0.8.0 candidate scope; preserve any remaining red results for the authorized 0.8.1 follow-up.
- [ ] Fix actionable review findings, separate current-main baseline failures from new regressions, and rerun normal internal review after fixes.

Main verifier history: the last green test run was `39960935469` on `268b65d` (0.7.10). The failure streak starts at `40023278462` on `67972f4` (0.7.11). The latest-main run `40039675890` on `6208b71` and exact-head run `40050561834` expose failures that predate the narration implementation; use the artifact logs to separate those from new regressions.

- [x] Register the stray `REV_PR_BASE_REF` regression in `test-costs.tsv`. Run `40040867680` failed before test execution with missing metadata, so it is not regression proof. Cursor package validation passed at `2543495d`.
- [x] Rerun test-only CI and confirm the stray-base-ref assertion fails on Ubuntu and macOS before changing production code. Exact-head run `40041805103` confirmed both assertions fail as intended, alongside the red 0.7.12 main baseline.
- [x] Capture the exact `rev-preflight.sh --pr` refusal and verify successful and stale-base paths against local refs.
- [x] Keep `rev-evidence.py`'s documented CLI refusal status consistent while asserting nonzero PR binding refusals.
- [x] Permit `REV_PR_BASE_REF` alone to trigger partial-identity validation and require its presence in a complete identity.
- [ ] Repair candidate-caused verifier failures without removing or weakening the new proof and read-limit behavior; carry unresolved baseline failures into 0.8.1.
- [ ] Complete normal internal review and record current-head macOS, Ubuntu, and Cursor package results before merging.
- [ ] Squash-merge PR #67, publish the signed `review-council--v0.8.0` tag and release, then verify installed host copies; publish 0.8.1 follow-up if any CI job fails.
- [x] Keep failed ancestors in a replacement chain as terminal-failure evidence; validate only the selected final generation as a successful result.
- [x] Preserve the pre-existing unchained replacement coverage path without weakening chained executor metadata or assignment binding.
- [x] Ensure all verification prompt entry points append the sibling-site check, while risk and unphased prompts remain unchanged.
- [x] Update both bundled skill copies and exact text assertions for the local-cluster fallback and unique replacement labels.

Review results: the focused fixture re-review was clean before integrating 0.7.12. Post-merge internal review is pending. The user authorized publishing 0.8.0 with exact-head CI failures preserved and fixed in a 0.8.1 follow-up.

## 0.7.12 proof-capacity recovery for #1752

- [x] Trace the exact source of the 2,000+ mandatory reads and confirm the failed recovery contract.
- [x] Implement a scope-safe change that keeps the full changed patch reviewable while bounding valid proof work.
- [x] Preserve every unresolved TypeScript import and Rust use-tree caller as a capacity-counted, fail-closed proof obligation.
- [x] Clarify Codex tool-call batching and add bounded, copyable source-read and search examples without relaxing read-audit enforcement.
- [x] Add regression coverage for the observed failure modes. The full test suite was not run.
- [x] Run one independent normal code review, fix actionable P0-P2 findings, and re-verify.
- [x] Publish the signed 0.7.12 tag and GitHub release; the release is published at `review-council--v0.7.12`.
- [ ] Resume #1752 on the new runtime and report its exact review state.

## Luna proof-capacity follow-up

- [x] Reproduce the #1752 preflight refusal in a copy of the review session.
- [x] Add regressions for wildcard re-export proof and numeric-only no-SDK legacy wording.
- [x] Add regressions for 160-line Codex patch windows, 200-line source reads, path-specific limits, exact patch end bounds, and sandbox-blocked tests.
- [x] Resolve imported symbols through TypeScript wildcard re-exports while retaining exact source proof.
- [x] Prepare bounded evidence for adaptive panels without requiring an SDK seat.
- [x] Keep repository source reads within 200 lines and the existing byte ceiling, and use 160-line patch windows.
- [ ] Run focused evidence tests and repeat the #1752 capacity preflight for every seat.
- [x] Get one independent normal review of the Council diff and resolve its actionable P2 findings.
- [ ] Record the test, CI, PR, and release state before closing this item.

### Luna follow-up review

The independent normal review found three P2 gaps in the wildcard re-export resolver
and regression: multiline exports were not parsed, the first-route fixture did not
exercise the multiline route, and CRLF files retained a trailing carriage return at
EOF. The parser and regressions now cover exact source-line routing for single-line,
multiline, and CRLF exports. A follow-up review found that multi-hop route lines were
indexed but not included in prepared source packets. Route ranges now flow through
packet planning and proof obligations, with a two-barrel packet regression. After
reconciling current main, review found that the Codex skill still described the old
no-SDK fallback for every panel. Its rule and contract test now match the generic skill.
The final independent re-review found no actionable P0-P2 findings. CI run 40047800326
failed on both platforms at 539465a; its only additional failing test group versus the
0.7.12 baseline is the wildcard route packet regression fixed in 8a5fd35. `git diff
--check` passes. Guarded shell preflight was refused twice, most recently at load 6.54
against the 6.0 limit, so no tests ran. Main advanced to 0.7.14 while this PR was open,
leaving its old head conflicting and preventing a current-head check from appearing.
The branch is now reconciled with current main. `bash -n` and `git diff --check` pass.
Exact-head run 40050428060 found that a shared test fixture replayed patch chunks even
when `auto` selected a direct patch window, producing a false `missing-assigned-patch-range`
violation. The fixture now replays the assigned patch file in windows mode, and its
regression asserts that mode. Independent re-review and fresh exact-head CI are pending.

## WLG Bread review preparation repair

- [x] Freeze Bread source at 747e032b and reproduce latest 0.7.12 preparation refusal.
- [x] Add Rust module resolution regression tests and obtain intended failing CI evidence.
- [x] Correct absent-alternative handling while retaining missing-import proof failures.
- [x] Resolve proof-capacity recovery with complete scope and unchanged proof limits.
- [x] Run one independent normal reviewer, address actionable P0-P2 findings.
- [ ] Verify both platform CI gates, publish a concrete repair PR and prepare a fixed runtime.
- [ ] Resume the complete Bread review on the frozen source and deliver the feature PR.

Review results: pending. No Bread review receipt, merge or deployment is claimed.

### Repair verification evidence

- Expected-red run40045649035 at9076df0:8 of9 Rust resolution regressions fail on intended targets/root identity; missing-module protection passes.
- Expected-red focused job120729884016 in run40046674469 at05ea5a0: capacity cases reject23 and16 reads against12; search80, compiler81 and discovery80 incorrectly reject. Boundary negatives pass.
- Independent normal review: three P2 findings require historical blob identity, physical Rust module directories, and comment-masked declaration parsing. Corrections are in progress.
- Frozen release baseline6208b71 already fails27 shell task groups on both operating systems. Fixture corrections retain source40, search80/sentinel81, byte ceilings and the12-read manual limit.

Independent cumulative recheck: all three P2 findings are fixed; no additional P0-P2 findings. This is source-review approval, not passing candidate CI. New pushes are held for cross-session ownership coordination requested by the user. Native queue messages to both peer sessions remain pending and are not acknowledgements.

Release authorization: the user explicitly requested releasing0.7.13 without CI and then resuming the frozen Bread review. CI is waived for this release; no passing current-candidate CI is claimed. Prior normal review is clean after all three P2 corrections.

## Routed source proof ownership follow-up

- [x] Preserve actual0.7.13 enabled-context Bread refusal at prepare-diagnostic-1s.json.
- [x] Recover assigned ownership from source range component IDs without dropping boundary proof.
- [x] Add a routed-specialist regression and obtain one independent normal review.
- [x] Verify preparation on the actual frozen Bread branch before publication.
- [ ] Publish the narrow follow-up under the user's Council release CI waiver and resume Bread review.

Operational acceptance: complete Bread snapshot5b9ce74207af51bba5831a318bf48e28f2dd056c prepared with source context enabled at /private/tmp/wlg-bread-owner-probe-yw2di0gt. All four seats fit the unchanged12-read limit, using1,1,6,2 post-index reads. Exact required segments remain mandatory. Independent normal source review approved. The existing user waiver applies to this narrow follow-up release; no passing candidate CI is claimed.

## Review Council PR #90 and review speed

- [x] Merge current `origin/main` into the PR #90 worktree and preserve both Unreleased notes.
- [x] Confirm the stale skipped-plan regression with expected-red CI run `40200399044`.
- [x] Trace #1841 preparation time to repeated predecessor source-context validation; observed 42 replays for each Luna seat and 13 for Sonnet.
- [x] Finish the registered-plan skip fix and independent review.
- [x] Push PR #90, pass exact-head CI, and squash-merge as `e2df2f54`; exact-head run `40205729814` and Cursor package run `40205729829` passed.
- [x] Confirm post-merge main verification and Cursor package runs `40207680238` and `40207680225` passed at `e2df2f54`.
- [x] Design per-prepare canonical reconstruction memo and obtain user approval; design `2d5cdd6b`, plan `0028777`.
- [x] Add the shared-predecessor regression and capture the intentional exact-head CI failure.
- [x] Implement the process-local memo and pass exact-head CI.
- [x] Complete an independent normal review, merge, and release signed 0.8.9.
- [ ] Run the matched #1830 Luna comparison after merge and update issue #77 with the eligible result.
- [ ] Continue monitoring #1830 and #1841 to terminal reviewer results.

Release 0.8.9 is published at signed tag `review-council--v0.8.9`, targeting merge commit `9795a4e9bdd812fbcda8f23872523115ec74737b`. PR #91 passed its independent normal review and exact-head CI before merge. The matched #1830 Luna comparison remains pending its merge and final Sol scope identity; issue #77 remains open because there is no eligible post-0.8.9 Luna sample yet.

## #77 Codex proof-read pairing candidate

The historical #1830 Luna plan audit on 0.8.4 was valid but used 62 tool calls, including 39 source-read calls and 23 required source segments. 0.8.9 improves repeated preparation work, not reviewer proof-read turns. The proposed follow-up allows two separate, ordered Codex proof-read calls in one turn while preserving per-path byte checks and all existing output caps. Compound shell batching remains disabled because joined output could be credited to the wrong source after a source mutation was restored.

Design: `docs/superpowers/specs/2026-10-25-codex-proof-read-pairing-design.md`. The user approved this design. Implementation plan: `docs/superpowers/plans/2026-10-25-codex-proof-read-pairing.md`; it tests real Codex turn boundaries, preserves packet limits, and keeps oversized one-line source segments alone.

- [x] Add the ordered-read, malformed-turn, packet-limit, byte-cap, and oversized-segment regressions.
- [x] Prove the intended failures on exact head `c5c61dde1407c673e66f6fc0a2cbc2f5c2f4144e` in Ubuntu and macOS CI run `40235826237`.
- [x] Implement Codex turn grouping, paired proof-read auditing, and accurate capacity estimates.
- [x] Update generated and installed discovery instructions and Codex prompt contract tests.
- [x] Complete independent internal review and fix actionable P0-P2 findings.
- [x] Pass PR #93 exact-head Ubuntu, macOS, proof-preparation, and package CI.
- [x] Squash-merge PR #93, publish signed Review Council 0.8.11, and verify Claude, Codex, and Cursor installs against the release.
- [ ] Run the matched #1830 Luna comparison after merge and update issue #77 with the eligible result.

Normal review found a P2 where Codex output events after `turn.completed` could still earn pair credit. Re-review confirmed the same-turn output check and the final release candidate, with no actionable P0-P2 findings. Expected-red run `40239050569` on test-only SHA `0d6e1e04f1b1bfb5aa0c1b9d52cd9880cb34a95e` passed proof preparation and Cursor packaging, while Ubuntu and macOS exposed that regression plus stale packet, duplicate-read, turn-boundary, and capacity expectations. Those failures are recorded as input to the current exact-head candidate; no green result is claimed yet.

Candidate run `40241061688` on `c30dbeff64ee38bf58ab47413f0b84d5af1b4ce4` passed proof preparation and Cursor packaging. Ubuntu and macOS each passed 5,155 shell assertions and failed four in two stale fixtures: the oversized-sibling plan case lacked explicit Codex turn boundaries, and the host skill assertion expected Claude-only wording. Ubuntu's 582 Python tests passed. Both fixture corrections were re-reviewed clean and committed as `83585e5`. PR #93 later passed exact-head CI in `40299377328` and package validation in `40299376198`, merged as `8d2697b`, and released as signed `review-council--v0.8.11`. All three installed bundles match the release source or Cursor build byte-for-byte and mode-for-mode. The matched #1830 replay is now pending on the same frozen 18-path `src/` scope with four Luna xhigh seats.

## Prompt-only seats must remain pending

- [x] Add a regression proving CLI launch markers appear only after a successful reservation.
- [x] Prove the marker regression fails on exact source in Ubuntu and macOS CI.
- [x] Add regressions for repeated Codex command IDs across turns, catchable cancellation, and CLI/Agent launch status; prove the expected red on Ubuntu and macOS in run `40312978967`.
- [x] Prove the bounded search-guidance regression red on Ubuntu and macOS in run `40316652546`.
- [x] Prove the signal-finalization races and per-turn call-cap wording regression red on Ubuntu and macOS in run `40320097283`.
- [x] Prove process-group cancellation after durable reservation fails on Ubuntu and macOS; test-only commit `0e33201`, expected-red run `40323741575`.
- [x] Prove PR progression accepts a closed reservation whose recorded exit is a catchable signal; expected-red run `40327587192`.
- [x] Prove a signal before first-record publication leaves no corrupt attempt and permits the same-label retry; expected-red run `40332170227`.
- [x] Prove PR progression refuses an unresolved Agent launch marker; expected-red run `40332170227`.
- [x] Prove launch status uses the timestamp from the marker snapshot it validated; expected-red run `40332170227`.
- [ ] Record CLI process identity, persist catchable cancellation exits, and report dead launches as interrupted.
- [ ] Keep Agent launch markers and active status tied to the stored task ID.
- [ ] Complete independent normal review and exact-head Ubuntu, macOS, proof-preparation, and package checks.
- [ ] Integrate after the 0.8.11 release and publish the next signed release.

Run `40292882622` on test head `e9746c8` confirms the prompt-only state and duration regressions on both operating systems. Each verifier passed 5,158 assertions and failed the four expected assertions across `t-cost-session.sh` and `t-status.sh`; proof preparation passed. The separate launch-marker writer regression is now being added before implementation.

The launch-marker writer regression passed proof preparation and failed the intended CLI marker, prompt-only status, elapsed-time origin, and cost-session status assertions on Ubuntu in `40296561539`; macOS showed those same regressions plus an unrelated race in the existing stack stall test. The intended regression failures are now implemented against explicit launch evidence in the CLI wrapper and Agent launch instructions.

Run `40316652546` on test-only SHA `788a0d635587edc6f8307fc2d6b223a8d7ece39c` passed proof preparation and package run `40316652693`. Ubuntu and macOS each passed 5,168 assertions and failed 42 across 13 tasks; after normalizing temp paths, their failure lists matched. Run `40320097283` on test-only SHA `78bb9c6e8d1cc6b182b23be1f05f2101107e4b21` passed proof preparation and package run `40320097299`. Both platforms passed 5,170 assertions and failed the same 47 labels: the prior 42 plus five new signal-finalization and per-turn cap assertions. Ubuntu completed in 15m48 and macOS in 26m51. The normal review then found a further P2: process-group cancellation can kill the reserve helper after its durable token write but before the wrapper sees success. Test-only commit `0e33201` adds that reproduction. Expected-red run `40323741575` completed on the exact test SHA with proof preparation green; Ubuntu passed 5,173 and Mac passed 5,172. Each platform repeated all 47 prior failures plus the two new group-cancellation assertions. Mac also had one unrelated, non-reproducible stack-stall assertion not present on Ubuntu or run `40320097283`.

Independent normal re-review found three more P2 lifecycle gaps: a signal during initial attempt-record creation can leave a corrupt empty file, PR progression ignores unresolved Agent launch markers, and status reads a launch timestamp separately from the marker state. Add focused expected-red regressions before fixing each path.

Expected-red run `40327587192` on test-only SHA `c2adf015d1ca119e6fbe963b1f44b0fb6d61b05a` passed proof preparation and package run `40327587216`. Both platforms passed 5,173 shell assertions and failed 50. Compared with `40323741575`, Linux added only the intended closed-signal progression failure; macOS added that assertion and its prior one-off stack-stall race did not recur. Full verifier logs are preserved under `/tmp/council-40327587192`.

Expected-red run `40332170227` on test-only SHA `99d9abbce1f1f8f3a1c3665a470661d9b0b32ad9` passed proof preparation; package run `40332170476` passed on the same SHA. Ubuntu and macOS each passed 5,177 assertions and failed 56 across 15 test tasks. Compared with `40327587192`, the only six additional failure labels cover unresolved Agent progression, atomic first-record cancellation/retry, and status snapshot consistency; both platform failure lists match. Complete diagnostics are saved under `/tmp/council-40332170227`.

The completed Agent transcript regression is isolated in test-only commit `c8772c6`; Cursor package run `40335594237` passed on its exact SHA. Expected-red run `40335594238` passed proof preparation; Ubuntu and macOS each passed 5,177 assertions and failed 56 across 15 tasks. Each platform added only the intended terminal-Agent-transcript failure while removing the prior Agent launch-result label. The production correction is committed separately as `f9baa41`; its independent normal review is clean. Final gate run `40340748712` at `5256c1e` passed package and proof preparation; Ubuntu passed 5,230 assertions and failed three test assertions. Two status expectations used the full `codex-sol` name while the status formatter emits `sol`; PR progression was given `p.md` instead of the required canonical round-seat prompt. The production cancellation lifecycle assertions passed. The test fixtures are corrected locally; macOS is still running on the previous SHA.

## Review Council issue #77 exit-3 recovery

- [x] Verify 0.8.14 release, reopen #77, and reproduce the exit-3 refusal.
- [x] Add focused regression cases for exit 3, exit 4, and controller-recorded same-provider cancellation.
- [x] Complete attempt-record validation, event recording, workflow docs, and normal internal review.
- [x] Send the exact candidate identity and safe-boundary install instructions to the release owner.
- [ ] Run exact-head CI and prepare the 0.8.15 release candidate.
- [ ] Measure fresh post-0.8.6 first-attempt Luna audit failure rate; keep #77 open until below 5%.

Review: normal internal review found a path-traversal risk in the recovery record. The fix rejects unsafe or unassigned trigger seats before reading artifacts; re-review was clean. Exact-head CI then caught two cancellation-test fixtures selecting Sonnet after a Sol parent, against the configured Luna -> Sonnet -> Sol -> Opus order. The fixtures now select Opus; re-review and a fresh exact-head gate remain pending.
## Quota-disabled exit-4 replacement recovery

- [ ] Confirm the documented exit-4 path and bind the `quota_fallback` policy to a durable escalation record.
- [ ] Add regression cases proving exit 4 and the exact `[4,2]` attempt sequence require a same-panel escalation record, while other retry sequences are rejected when quota fallback is disabled.
- [ ] Add regression cases separating Codex `output_tokens: 429` usage telemetry from an explicit provider quota error.
- [ ] Implement the smallest validator and escalation-record change that preserves full scope and receipt checks.
- [ ] Run the focused regression through the repository's approved CI route and confirm all existing replacement cases.
- [ ] Complete the required Council review with a canonical receipt, address actionable findings, and share the adopted workflow change with live walletissues sessions.

Progress (2026-10-31): Test-only head `b7f0aed` completed expected-red run `41161800743` on both platforms. The Python case failed on the missing `panel` argument, and the shell case refused exit 4 without its durable record; proof preparation passed. Test-only commit `5c5bee6` adds usage-count and explicit-quota classifier cases. Package run `41163092848` passed. Expected-red run `41163092865` completed on Ubuntu and macOS: both platform logs show the intended usage-count classifier assertion and exit-4 binding checks failing, with all other Python and shell checks passing. The classifier filter and durable exit-4 changes are local and uncommitted; current implementation CI has not run. `ci-local` refused the named Python invocation before execution because Python is not on its allowlist; no local test ran.


## Review Council manual plan-review fallback

- [x] Reproduce the phase=fix refusal after the configured plan-seat chain fails; expected-red run `41205101249`.
- [x] Add a separate manual-review record bound to the current plan and evidence manifest, and reject missing, stale, incomplete, or pending-replacement evidence; treat replacement prepare diagnostics as settled failures, never success.
- [x] Update both host phase guides and their contract test.
- [ ] Pass exact-head Ubuntu, macOS, proof-preparation, and package checks.
- [x] Complete the first independent normal review; it found that one replacement child can be bound to multiple failed root assignments.
- [ ] Add the duplicate-child regression, reject duplicate bindings at registration and gate validation, then re-review.
- [ ] Merge the small workflow fix and share the adopted recovery step with walletissues sessions.

Run `41209614941` on `7af3e37` exposed stale state-gate fixtures: they wrote exit files without the attempt journal now required to prove two terminal failures. Run `41211125996` caught an unbound-variable failure in the new fixture helper under `set -u`; the assignment order is corrected. Run `41215562217` found two more fixture issues: child manifests overwrote the frozen root plan, and the unrecorded-exit case also wrote a hard-audit latch. Both fixtures are corrected; a fresh full exact-head run is required.

## Exact retry exit-130 replacement candidate

- [x] Trace why a completed retry sequence `[2, 130]` is not eligible for configured replacement.
- [x] Add a focused regression for exact `[2, 130]` retries, standalone 130, provider cancellation, and incomplete attempt state.
- [x] Preserve adapter cancellation exit codes at the seat wrapper boundary.
- [x] Implement replacement eligibility only for a complete exact retry; keep 130 out of reviewer results and receipts.
- [ ] Run the focused test and exact candidate CI on the final documentation head.
- [x] Complete an independent normal review of the code at `1ffe0a1` with no actionable P0-P2 findings.
- [x] Reconcile the `rev-attempt.py` overlap with PR #102 without editing its branch. #102 binds missing-child-manifest retries to root prompt and attempt hashes; this candidate handles the exact `[2, 130]` retry sequence.

Review: independent normal review was clean at code head `1ffe0a1`; the follow-up commit records this result and reconciles the separate PR #102 behavior. Re-run exact-head CI before merge.

# Claude source-only four-read batching for full-scope evidence preparation

- [x] Add estimator and audit regressions for Claude source-only turns, preserving the two-read limit for mixed proofs.
- [x] Confirm expected-red run 41219263183 fails the four intended assertions on frozen source.
- [x] Implement up to four consecutive source segments under a 60 KiB turn cap, with existing 32 KiB per-response bounds.
- [x] Update evidence manifest validation, prompt contract and both discovery guides.
- [x] Recompute the unchanged frozen #2069 evidence manifest: 142 paths, 368 hunks, 54 components, 288 required ranges, and 298 source segments. The original projection is 175 turns; the candidate projection is 101 turns (75 source-segment turns and 14 patch turns). This is an estimator result, not a live provider run or measured token/cost saving.
- [ ] Fix exact-head CI failures in both verifier platforms, complete Council review, rebase on current main and pass exact-head CI.
- [ ] Push the reviewed branch and open a draft PR.

Review: One independent normal reviewer found no actionable findings. The candidate is limited to Claude source-only required segment reads, retaining the 32 KiB response cap, 60 KiB turn cap, exact order/hash/completeness checks, the two-read mixed-proof limit and other-adapter behavior. Expected-red run 41219263183 confirmed all four intended assertions failed; 5,251 other release tests passed. Exact-head passing CI remains pending after the merge of PR #107.

CI diagnosis: exact-head run 41227193633 failed on both Ubuntu and macOS. The shell failures were stale contract assertions. The Python failure exposed that `evidence-proof-batch-too-large` was advisory for Claude, allowing a mixed source-plus-index turn above the two-read limit to remain valid. The fix makes that mixed-batch violation fatal for Claude while keeping the four-read exemption restricted to source-only required segments.

## Plan-phase quota-disabled replacement binding

- [x] Trace why the current `phase=plan` gate cannot accept the quota-disabled exit-4 record added by PR #101.
- [ ] Add red state tests for `[4]` and `[4,2]` markers bound to the replacement seat, plus missing and mismatched marker rejection.
- [ ] Thread the next replacement seat through plan registration and the final plan gate without making exit 4 generally terminal.
- [ ] Run focused state tests and exact-head CI.
- [ ] Complete the repository-required independent normal review and share the adopted workflow fix with walletissues sessions.

CI diagnosis: exact-head run 41298649446 failed before executing shell tests because the new `t-state.sh` test lacked a `test-costs.tsv` row; the 594-test Python suite passed. The metadata row is added, and functional red-before-fix is still pending.

CI diagnosis: exact-head run 41299502380 executed the shell regression but failed its marker fixtures because the helper used legacy unbound attempt records. The fixtures now use lifecycle-v2 launch tokens; rerun the regression on this corrected test-only head before counting it as red-before-fix.

Review: Current main `9c4b7bb` records the selected replacement seat, but `rev-state.sh` calls `terminal_failure` without it in the plan registration and completion paths. This leaves the marker unverifiable in plan phase. The #516 `r4p2` attempt is one exit-4 launch caused by command-call-budget exhaustion; `output_tokens: 429` is usage data, not a provider quota error. The earlier run's quota setting is not proven, so recovery must preserve the same fail-closed marker requirement.
