# Changelog

## 0.5.3

- The reviewer prompt now says that running an interpreter or an inline script (`node`, `python3`,
  `bash -c`, `eval`) fails the whole review, because the read-only policy refuses it. Test runners
  on existing files (`npx tsc --noEmit`, `cargo test`) are the only execution allowed. A claim that
  can only be settled by running new code stays a finding, marked unverified at runtime. It also
  says that a skipped, partial, repeated, or out-of-order patch chunk read fails the review. On
  web-sdk PR 418 both mistakes, one per codex seat, cost the final verification panel its
  security bundle: the seat's replacement ran `node -e` to test a TypeScript hypothesis.

## 0.5.2

- A seat's read audit now fails only on codes that mean the review cannot be shown complete, cannot
  be trusted as the seat's own work, or cannot be seen. Size codes (`tool-output-too-large`,
  `tool-turn-output-too-large`, `unbounded-read`, `unbounded-search`), codex source-batch conduct
  (`unsupported-source-batch`, `source-batch-lines-too-large`, `overlapping-source-batch`,
  `source-batch-output-mismatch`) and the four proof-batch pacing counts are advisories. Before,
  any one of them stopped the whole panel, forbade a retry and latched the session: on one 14-file
  pull request a single `rg ... | head -80` over minified `dist/` output did that to a seat whose
  review was otherwise complete.

- Softening a code can never make an incomplete review complete, because a call that raises any
  violation, fatal or advisory, now earns nothing: no source range, patch window or chunk, packet,
  required segment, evidence-index or plan-search proof, and so no citation. Calls in an oversized
  turn earn nothing either. An oversized output may not have reached the model in full, so its
  bytes in the transcript prove nothing. Two kinds of count revoke nothing: pacing counts, taken
  over reads that were each byte-proved on their own, and whole-transcript counts (read order,
  repository call count, a missing evidence index). A full Read of a document the prompt names earns its whole range.

- The read-only command policy now runs before every shape check, so a refused program such as a
  `python3` heredoc or `sed ...; python3 -c ...` always reports `unsupported-shell-command` and
  can never hide behind a batch or redirection code that is now an advisory. Every operand of a
  codex source batch is checked for scope and session artifacts first, so a sibling's prompt or
  result inside a batch is still `unnamed-session-artifact`.

- In a repository with a `Cargo.lock`, when `REV_DEPS_DIR` is unset, `rev-evidence.py prepare`
  builds a per-crate view, `$S/deps/<name>-<version>`, with one link per registry package the
  panel snapshot's `Cargo.lock` pins, and records it in the manifest. `rev-seat.sh` passes it to
  the read audit as `--deps`, and the prompt names it as the only place to read pinned dependency
  source. A lockfile edit gets a fresh view on the next panel; other cached versions of a crate stay
  `path-outside-scope`. A codex seat that listed and read its pinned crate in the cargo registry
  had failed with `path-outside-scope`.

- A hard audit failure no longer stops the panel or latches the session. `rev-attempt.py` refuses
  only a relaunch of the same label and seat (an invalid `read-audit.json` or an archived
  `audit-invalid.json`); the session and panel stop markers and the `stop` and `check` commands are
  gone. On the wallet C1 review, 8 hard failures had each forced a new session.

- An assignment without a valid result gets at most one replacement on another eligible seat:
  after its exact retry for an execution failure, immediately for a hard audit failure. This rule
  replaces coverage repair. `prepare <N>x --phase repair --assignment <executor>=<parent bundle>
  --parent-assignment <N>:<failed seat>` keys the child by the seat that runs it, and refuses the
  failed seat itself, an Agent seat, a parent with no recorded terminal failure (an archived
  `audit-invalid.json`, or an exact retry that also exited 1 or 2, which `rev-seat.sh` now records
  per launch) and a second replacement in the panel. The receipt reads the replacement's result,
  audit and findings under the executing seat. A failed plan seat is replaced by an ordinary
  one-seat `<N>px` plan panel, and `phase=fix` accepts `<N>p` or `<N>px`.

- A review-origin breaker. `rev-evidence.py review-origin <S> <N>` counts, from round `<N>`'s
  sealed receipt, the chosen citations on lines the review itself changed since its first
  receipt. `phase=fix` records the count and refuses once two rounds since the last
  `review_origin_ack=<N>` have a nonzero count, so the user decides whether to revert the review's
  own changes. `rev-state.sh <fallback> inherit-breaker <parent>` carries the window into a quota
  fallback session. On the wallet C1 review about 30 of 38 later findings were defects in the
  review's own fixes.

## 0.5.1

- A codex seat that reads the frozen snapshot through `git show <snapshot tree>:<path> | sed -n`
  (or `| head -n N`) no longer fails the bounded-read audit. The audit used to see no source
  range in that read, so a seat that read exactly its required target was rejected as having
  skipped it, and its findings as uncited. That read now earns a range, but only when its bytes
  match the frozen snapshot blob; the tree is taken from the evidence manifest, and a `git show`
  of the base commit, the base tree or any other revision is context that never earns a range or
  satisfies a citation. On macOS `/usr/bin/git` is an `xcrun` shim that, inside the codex
  sandbox, prints `xcodebuild` and `git: warning|error:` lines to stderr before git runs, and
  codex merges stderr into the output. Those leading lines are dropped for these reads alone,
  and every remaining byte must still match.

- Shell comments no longer decide how a command is audited. Seats had put a `# Question: ...` line
  on each call, as the prompt's "name the question first and record the window in the tool call"
  seemed to ask. The audit read the comment as a second command, so every such call was an
  unsupported source batch, and an apostrophe in the comment made it an unparseable shell shape.
  A comment still cannot hide a second command on its own line. The prompt now asks for the
  question in the reviewer's reasoning, not in the command. It also says that `head` limits lines,
  not bytes, so searches should stay off minified build output: a line-bounded `rg` over a
  `dist/` bundle returned about 1 MB and failed the output ceiling, a failure that is real and
  stays hard.

- On one 14-file pull request this cleared one of the two hard audit failures seen across six
  codex launches. The other was that 1 MB search.

## 0.5.0

- A fix plan now has to say which test fails without it, and the loop has to watch that happen.
  `Prediction` joins `Findings`, `Rule` and `Sites` as a required plan-cluster field, naming the
  test, the arm and the assertion or message that fails today. The Fix step then runs that test
  before the fix exists and records the observed failure line beside the prediction in
  `fix-plan.md`; a failure whose message does not match is a stop, not a note, because a test that
  fails for an unrelated reason proves nothing about the defect. Verify reads the prediction a
  second time, against the failure line `rev-mutate.sh` prints beside each pinned hunk. That
  comparison is yours to make: nothing in the tool reads a plan, so it surfaces what failed and
  stops there. The measurement behind this: over twelve fix-doing sessions, 262 of 591 findings
  were defects in the loop's own earlier fixes, and the single most common shape was a test
  asserting on the arm the fix touched rather than the arm the defect lived on. That test passes a
  mutation check and fails a red-first run, which is why both halves ship together rather than
  either alone.

- A plan's sites are now reconciled against its own search in both directions. The search already
  had to find every path the plan named; now every path the search finds must be fixed, or listed
  under `Excluded:` with a reason. Entries separate on `;` so a reason may contain a comma, a bare
  path with no reason is refused by name, and excluding a path the search never found is itself a
  refusal, so a typo cannot quietly reconcile a real hit. Reconciliation runs against every path
  the plan declares, including those in `Test`, `Tests` and `Regression`, so a cluster need not
  exclude its own test file. Incomplete-sites was the largest script-catchable class in the
  measurement, 73 of 262: a finding names one call site, the fix covers exactly that, and the next
  round finds the sibling. Covering eight of ten is no longer possible without writing down the two.

- `scripts/rev-mutate.sh` reverts each changed hunk on its own and checks whether any test notices,
  and the Verify step now runs it. A hunk whose revert leaves the suite green is unpinned: no test
  proves that line. It refuses while a panel is live, because seats read the live tree and a script
  that reverts hunks for seconds shows them a tree that is neither base nor fix. It proves each
  revert actually changed bytes before counting the verdict, since a mutation that silently fails
  to apply produces a green run indistinguishable from a real one. And it runs the command once
  before the loop and once on the restored tree afterwards: the first proves the command can pass
  at all, the second proves it still can, so a suite that was already red, a missing binary, a
  poisoned cache or a flake cannot make every hunk read as pinned.

- The fix-design gate no longer accepts a stale counter. It hung entirely off `open` being greater
  than zero, so a round whose counts still held the previous round's zeroes walked straight
  through; the stale case is exactly the one that short-circuited. `rev-state.sh` now stamps
  `open_stamp` when all three severities are written in one call, and refuses `phase=fix` when the
  counts predate the round's newest seat exit. Freshness is scoped to that round's own receipts,
  `r<N>-<seat>.exit` and `r<N>x-<seat>.exit`: a repair panel produces findings needing triage so
  its exits invalidate the counts, while a plan panel reviews a triage that already happened so
  its exits must not. A session with no seat exits is not stale.

### Upgrading

Three things now refuse where they previously passed. All fail closed and name their way out.

- An existing `fix-plan.md` has no `Prediction` field and will not parse. Add one per cluster.
- A plan manifest prepared by 0.4.8 fails validation, because `excluded` joins the cluster's
  structural key set. Re-run `prepare`.
- A session resumed across the upgrade refuses its first `phase=fix`, because it carries no
  `open_stamp`. Re-run triage and set `open.P0`, `open.P1` and `open.P2` in one call.

## 0.4.8

- Plan panels now run on an Agent-only roster instead of refusing. An Agent seat cannot supply the
  enforced read transcript, so such a panel is never certified - but the value of the fix-design
  gate is its schema-4 structure (per-cluster closure obligations, sibling-site search proofs,
  source shards), and that structure works on an Agent seat. Refusing meant a Claude-only Agent
  roster, which is what a degraded panel falls back to, got no plan gate at all unless the host was
  told to force one by hand. Preparation records the seats in `unenforced_seats`, validation skips
  only their read audit while still binding their result, exit and prompt hashes, and each receipt
  row carries `enforced`. The host picks a plan seat from the whole roster rather than only from
  CLI-backed rows. The list is DERIVED from the roster during manifest validation and compared
  against the declared one, so a hand-edited manifest cannot name a CLI seat and have its audit
  skipped, and the relaxation is scoped to the plan phase: an Agent seat reaching a code manifest
  still has to prove its reads.
- Republishes the 0.4.7 Stop guard under a new version. 0.4.7's manifest bump landed in the pull
  request BEFORE its fourteen review fixes, so `main` published version 0.4.7 twice: once with the
  original guard and once with the repaired one. `claude plugin update` compares version strings,
  so an install that picked up the first never receives the second. Anyone on 0.4.7 should update.

## 0.4.7

- Install a `Stop` hook that refuses to end a turn while a review session is mid-run. The
  recurring failure is stopping on a status summary with queue items left, so the hook reads the
  newest session's `state.json` and blocks while it is not `done`, naming the round, phase and
  open findings. It fails open in every ambiguous case - no session, a session untouched for six
  hours, unreadable state, no `python3`, or a counter it cannot persist - releases after three
  consecutive blocks, and allows a genuine wait where the round is parked on unanswered seats,
  every returned seat is triaged and the tree is clean. The consecutive-block counter is keyed per
  stopping session and the release is sticky: one shared counter was not a cap at all, because every
  allow path resets it, so any other session ending a turn zeroed the count of a session being
  blocked and it never reached the release - observed live, a session blocked four times against a
  cap of three. Resetting to zero on release also made the cap a toll rather than a release, costing
  three more blocked turns on every later stop. Session discovery is limited to directories owned by
  the current user, since /tmp is world-writable, and accepts a root override so tests can own the
  state they read instead of planting fixtures in the shared namespace. Session text never reaches a
  shell or JSON control channel: the state fields cross one per line rather than positionally,
  because a single space in an attacker-writable `phase` shifted every later field and made the cap
  unreachable, and responses are built with `json.dumps` rather than interpolated, so a crafted
  `phase` cannot inject a decision. A run can also end without reaching `done` - a stack leg is
  required to finish at `stack-ready` - so the terminal set is wider, and a receipt counts only as a
  non-empty regular file (matching `rev-state.sh`), so `touch report.md` cannot end a live review.
  The candidate list is capped after scoping rather than before, so out-of-scope sessions cannot
  push the live one out of it. A seat that FAILED counts as answered: `rev-seat.sh` writes `.exit`
  for every outcome and `.json` only on a valid result, so scoring "no result" as "still running"
  made the guard allow the stop, claiming every returned seat was triaged, at the exact moment the
  contract requires an immediate retry or a halt. A result sitting untriaged is outstanding work
  too. Receipts are matched with `lstat`, the call `rev-state.sh` itself uses, so a symlink is not
  a receipt in either place. State is untrusted in SHAPE as well as content: rev-state.sh stores a
  value that is not JSON as a bare string, so `seats=sol` arrived as a string whose every character
  read as an unanswered seat and produced a false "genuine wait" during a live panel; a seats list
  the hook cannot parse is now never a wait. Plan and repair panels park on seats with the same
  receipt shape, so they count as waits too. The candidate cap keeps the newest sessions rather than
  whatever order the filesystem returned, and a `git status` that fails is no longer read as a clean
  tree. It is scoped to the stopping session's
  working tree: review sessions share a `/tmp` namespace, so an unscoped guard blocks every
  concurrent session on the machine for as long as one review is open anywhere, which was observed
  live. A review whose `scope.env` cannot be read still blocks, since dropping it would disarm the
  guard. The stdin read is bounded, so a missing or never-closed payload cannot hang the hook to
  its timeout. Hosts that already installed the guard by hand should remove their personal `Stop`
  entry, or it runs twice against two counters.

## 0.4.6

- Tell a plan seat which cluster source windows it must open. Preparation already bounds the cited plan rows a seat opens by hand to at most `MANDATORY_REPOSITORY_READ_LIMIT` merged windows, but the prompt listed only the cited rows, so a seat had to derive the window set itself; two plan panels on a 112-file review each stopped a few windows short and failed the audit with `missing-plan-cluster-source` after a full paid run. The seat packet now publishes `mandatory_source_windows`, the plan prompt renders one `Mandatory cluster source window: <path>:<start>-<end>` line per window, and the auditor binds those lines so a prompt cannot drop or duplicate one. Manifest validation checks the rows for shape, scope, line bounds, the window limit, and that they still close the plan, so a stale list fails preparation instead of a panel. The field is optional, so manifests written before it still validate, and a plan panel prepared with source context disabled publishes the same list.

## 0.4.5

- Seat Claude Code's Opus and Sonnet rows on the `claude` CLI adapter when the CLI is signed in, so plan panels and evidence-mode code panels run from a Claude Code host. `claude_adapter` (`auto`, `cli`, `agent`; env `REVIEW_COUNCIL_CLAUDE_ADAPTER`) controls the choice, and `agent` keeps the previous roster byte for byte. Padding falls back to Agent seats when the CLI is unusable, and `roster.json` records why `auto` fell back. Every nested `claude -p` (seat, probe, or stack leg) drops the parent session's identity variables and keeps auth and provider variables.
- Resolve ripgrep once for plan searches: `REV_RG`, then `PATH`, then Claude Code's embedded ripgrep, else `ripgrep binary not found on PATH; set REV_RG to a ripgrep executable`. The session input lock no longer relabels errors raised inside it.
- Make the plan panel one plan-completeness seat by default (`plan_seats: "all"` restores four lenses), run it after triage and before any edit, and refuse `rev-state.sh phase=fix` while P0-P2 findings are open until the plan panel completes or `findings.md` records `Plan panel r<N>p - SKIPPED: <reason>`. Plan preparation uses source context like code panels. A normal adaptive review now plans 9 launches, a large or high-risk one 17, and an important one 13.
- Plan preparation refuses only an assigned plan seat on the `agent` adapter, and `rev-state.sh` refuses a plan launch whose `seats` is not a JSON array of names.
- Read plan locations only from `Sites:` and the first token of a test field, so prose such as `600`, `client.sync`, `try/catch` and `onStage(a)/b` no longer fails preparation. Every plan refusal names the cluster, field and token and suggests the fix.
- Add a sibling-site completeness sentence to every verification prompt, including a repair seat that names the verification panel it covers with `--phase`, render a whole panel with `rev-prompt.sh --panel` and one manifest validation, and report per-seat render time in `rev-profile.py`.
- Stop listing the same git tree once per source-context row during evidence validation. On a 7,680-line synthetic change one seat's evidence render drops from 35.6 s to 0.72 s and `verify` from 33.4 s to 0.55 s.

## 0.4.4

- Document the bounded release lane: N-1 review from the signed 0.4.3 tag, the existing
  deterministic candidate gate, P0/P1-only repairs, and a two-generation cap without a
  separate release authority.
- Add rotating composite red-team emphasis to every code panel at zero extra provider calls, plus one pre-plan four-bundle adversarial panel for large, high-risk, important, or explicitly adversarial adaptive reviews, with explicit compatibility, recovery, security, and integration routing.
- Publish every completed PR-associated review as a `COMMENTED` GitHub review using the canonical badge, verdict tip, decisions, fixes, verified-sound, coverage, and footer structure. Rendering is deterministic from validated session JSON; the inspected body, open PR, and reviewed head are frozen for exact retries; reviews without an associated open PR skip without posting.
- Make GitHub publication part of the success receipt for normal and read-only code reviews. Preserve the rendered body and an exact retry command on every post-dispatch failure. Bind discovery and durable target state to an exact frozen GitHub remote repository set, a clean committed tree, the reviewed merge base, and the pushed head. Pin every CLI request to `github.com`, require GitHub object links with immutable commit identities, bind source links to the reviewed head, accept GitHub's explicit-port and SSH-over-HTTPS clone forms, and escape raw HTML outside balanced Markdown code spans. Create each review through the GitHub API with the frozen commit ID, serialize finalization and publication state, revalidate the head after review listing and POST confirmation, validate every paginated review item, and accept a moved base tip only when the merge base remains unchanged. No-push rendering makes no GitHub calls. Stack legs inherit no-push and no-squash settings, use a distinct joint completion receipt until publication, recover brief post-push head propagation, publish successful repositories when a sibling fails, validate the unchanged reviewed tree before push, push an immutable commit to a captured literal endpoint, prove the merge base before mapping reviewed-PR SHA links, preserve separate-PR fix links, attribute missing durable state to the failing phase, and derive retry finalization from durable review state.
- Treat closure or merge before the review POST, including during stack head propagation, as the exact no-open-PR skip. Persist every publication failure and exact retry command in the session; direct success clears it immediately, while stack success clears it only after final report promotion.
- Contain malformed session text inside the durable publication receipt boundary. Freeze the original semantic render separately from the published body, validate complete original and finalized stack states before both push and no-push completion, and let only real-push retries recover an interrupted body-before-target finalization.

## 0.4.3

- Make the host skill an explicit executable workflow contract in both the always-loaded Claude Code policy and the Claude and Codex skill bodies. Runs that omit an applicable step or an artifact required by their selected mode remain incomplete and cannot claim Review Council completion.
- Preserve substantively complete reviews when only evidence read order, repository call budget, output overflow, navigation-index omission, or duplicate completed patch and required-source reads fail. These conditions remain receipt advisories, while incomplete patch, required-source, citation, result, or transcript proof still fails closed.
- Stop the current panel after a hard evidence-audit failure instead of retrying the same prompt or widening into full-state repair. Preserve the rejected findings under a diagnostic filename, keep them outside receipt selection, block every seat under the failed label before another provider call, and direct the host to stop. Provider execution failures retain one exact seat-local retry, and receipt failures end the run before another reviewer launch.
- Render required original-source expansion only after the evidence index, with one deterministic qualifying target. Quota fallback now uses a fresh sibling session, refuses to overwrite an initialized session, verifies content-addressed source identity, and permits at most one full-panel restart.
- Keep source-context packets within the 16 KiB envelope observed across live reviewer transports while retaining 16 KiB required-source segments.

## 0.4.2

- Add opt-in quota fallback that temporarily maps unavailable Claude seats to Terra and unavailable OpenAI seats to Sonnet, restarts a quota-failed panel from the same frozen source, records every substitution in roster profiles, and retries the preferred roster on the next review. Persistent local attempt exhaustion has its own exit code and cannot be mistaken for provider quota.
- Compile proof, source, repository, and response obligations against provider call and turn capacity before launch. The optimized source packets and patch chunks are now the default, while explicit baseline settings remain available for comparable measurements.
- Publish installed plugin bundles with one atomic directory exchange, keep verifier state descriptor-relative outside reviewed source, constrain recursive evidence search to one documented form, keep Claude moving after compaction, and make the inline fix plan the sole plan artifact reviewers may open.
- Add fail-closed ordered `claude_models` rosters so Opus and Sonnet can run as distinct maximum-effort seats, while preserving `claude_seats` as the repeated-Opus compatibility setting.
- Retain valid reviewers when one code evidence seat fails. Retry the exact generation once, then bind a full-scope child generation to the failed parent assignment and seal one composite receipt without rerunning valid siblings. A persistent four-call budget survives wrapper restarts and refuses before changing prior artifacts.
- Route schema-4 plan specialists to receipt-relative fix deltas or cumulative cluster closures while one completeness seat retains full state. Compile each rendered task against its exact plan, scope, lens, manifest hash, and authorized artifacts before publication; name and audit one mandatory native first read; reserve capacity for the required result JSON; retain valid siblings on exact seat retries; and never broaden a plan specialist to legacy full scope. Agent plan rosters fail before publication because they cannot supply the enforced transcript.
- Replay preserved provider envelopes through the current auditor before paid self-host probes, classify unused read-only exploration separately from required-proof failures, probe independent providers concurrently, and fail malformed exact-roster configuration closed.
- Batch exact patch and required-source proof for Claude, narrow reviewer tool surfaces, inspect completed seats while siblings run, and schedule exact isolated shell tests longest first. The unified verifier freezes one tree, runs shell, Python, build, validator, and static gates once, and publishes a hash-bound receipt only after exact inventory and log reconciliation. Add a disabled-by-default Codex source-window batch with strict line, byte, path, overlap, and frozen-output checks for a single Sol canary. Provider-specific inline evidence remains gated on a clean held-out council run.
- Bind self-host replay to provider boundaries, local CLI versions, evidence inputs, and the ordered core roster. Claude accepts its exact terminal-newline rendering and omits only provider-confirmed nonexecuted Read or Grep calls, while neutral reviewer mode retains the read-only guards. Plan artifacts reject source-name collisions, finding ranges require a bound path, benchmark seats use their configured model and effort, and extras survive only a matching model probe.
- Replace Grok in every live roster, probe, launch, extra, status, example, and current-session contract with Terra while preserving historical transcript decoders and baseline labels. The exact configured council is Sol, Terra, Opus, and Sonnet at maximum effort.
- Reject reciprocal quota substitutions and keep unrelated provider failures subject to `min_labs`. Fail malformed evidence declarations closed, accept the documented 80-result plan-search boundary, enforce Claude's compiled turn cap, count code source and refutation turns, and promote adjacent omitted source ranges together when they jointly remove a mandatory read.
- Treat exact bound evidence artifacts as artifacts even when a session is inside the repository, and require every evidence-scoped transcript to read the complete byte-matching evidence index before repository expansion.

## 0.4.1

- Replace the fixed eight-round default with adaptive discovery, plan, and verification panels. A normal four-seat review plans 12 launches: four simplicity, four conditional plan, and four final verification launches. A large or high-risk review plans 16 by adding four risk-discovery launches. Explicit numeric rounds keep each host's legacy schedule and convergence rules.
- Compact reviewer prompts, remove repeated schemas and cumulative ledgers, inline immutable plans, warn on oversized context, and bound evidence collection. Gemini now receives the rendered prompt unchanged.
- Add `rev-profile.py` for completed, metered, and unmetered call counts, prompt size, provider usage, cost, and finding yield. Current sessions require schema-valid results with successful exit receipts; a valid versioned roster policy preserves exact hashed receiptless results from older sessions, while present invalid receipt metadata fails closed. Usage-bearing failed attempts remain metered. Retry streams are archived before each adapter attempt so usage is not overwritten.
- Add hashed review snapshots, dependency-component routing, finding ownership, immutable coverage receipts, later-round semantic deltas, single-seat routing for mechanical files, and deterministic navigation. Every seat proves bounded coverage of its assigned patch. Large safe patches use ordered hash-bound chunks only when they save at least 10% of proof reads; exact reconstruction, provider-visible bytes, and read order are audited. Literal source packets carry exact declarations, callers, tests, and gates; oversized bodies require tree-bound, byte-verified integration reads. Every evidence error restores full scope. The profiler separates projected words, provider usage, cache metrics, and patch proof activity.
- Narrow adaptive plan panels with an immutable all-cluster site and local-import closure for every specialist while retaining the full cumulative patch on the plan-completeness seat. Every seat sees the complete plan, runs each cluster's bounded repository-root sibling search, and proves its named source ranges. Search proof binds one `rg` or recursive `grep` engine and pattern rooted at literal `.`, requires 1-79 NUL-delimited, line-numbered path results that include each named site, and rejects engine substitutions, traversal filters, redirects, filename suppression, and producer errors. A non-persisting validator rejects stale or incomplete attempts without advancing code coverage; any failure reruns the whole plan panel at fresh full scope.
- Honor exact `codex_models`, `claude_seats`, and `min_labs` settings before probes and launches, require explicitly counted Claude seats to remain Opus, ignore stale pins on inactive extras, refuse incomplete explicit counts before padding, propagate retryable versus permanent status with one canonical reason, and cache repeated adapter-model probes. Invalid or configuration-impossible lab floors exit 6 before probes; satisfiable availability shortfalls remain retryable exit 5.

## 0.4.0

- Add a Codex plugin with native review and stack skills, a GitHub marketplace and curl installer, a guarded Claude CLI reviewer, provider-aware fallback panels, and Codex stack legs. Both plugins share the existing engine with separate skill and hook discovery. Detect integer-major Codex model names and respect `CODEX_HOME` for the model cache.

## 0.3.2

- Measured on the eight-case blind benchmark, the 0.3.0/0.3.1 defaults lost recall: the author's PR description in seat prompts cost more load-bearing rows than it gained (anchoring on the author's framing), and replacing one simplicity seat with the `clean-room` design seat lost rows outright. Round 1 is back to `simplicity` on every seat; `clean-room` stays available as an additional seat and `--pr` as an opt-in, neither a default. The eight-round plan and the benchmark tooling stay.

## 0.3.1

- The `clean-room` lens is dealt to the Claude seat (listed first in the round-1 lens list, so the dealing rule lands it on the last roster position) instead of the third seat; on the benchmark it had landed on the weakest seat.

## 0.3.0

- Round 1 is simplicity for the whole panel: three seats run the `simplicity` lens and one runs the new `clean-room` lens, which writes the smallest design for the named consumer before reading the diff and reports where the change exceeds it. Correctness lenses move to round 2; the minimum is eight rounds; the extra seats join in rounds 3 and 4. Measured on held-out PRs, one seat with the lens found about half of what four found together.
- Every prompt carries the author's PR description (`rev-prompt.sh --pr`, saved to `$S/pr.md` at setup), because proportionality is judged against the consumer the author names.
- `eval/`: the blind held-out benchmark - isolated single-lineage checkouts, all seats including a headless Claude seat, a ground-truth builder and a scorer that prints only a summary line - with lens and PR-description options.

## 0.2.2

- The `simplicity` lens is rewritten from a two-case held-out evaluation (`docs/simplicity-lens-eval-2026-09-06.md`): the burden of proof sits on each new mechanism; native engine or framework features over hand-rolled ones; proportionality to the named consumer; one value or one implementation means no parameter and no generic; migrations from schemas created on the same unreleased branch fold into the original; public surface follows the file's re-export convention; test axes, helpers and divergence tests must still have two sides; consistency with siblings is not a justification. Structural recall on the held-out cases went from 1/3 and 1/5 to 2/3 and 3/5 with no case-specific wording.
- `REV_SEAT_OFFLINE=1` at prompt-render time adds an offline paragraph to every seat prompt for blind evaluations: no network, no other checkout, no published versions of the repository's own packages, no whole-registry searches.

## 0.2.1

- Preflight no longer assumes the change was cut from `origin/HEAD`: the base is `--base <ref>` (or `REV_BASE_REF`), else the open PR's base via `gh`, else the nearest fork point among the default branch, `next`, `develop`, `dev` and `release`. A branch cut from a `next` line was previously reviewed with everything `next` carried past `main`. `scope.env` gains `REV_BASE_BRANCH`, the preflight line prints `base_branch=<name> (<how>)`, and HEAD sitting on the chosen base is refused like any shared branch.

## 0.2.0

- The fix-plan gate: triage now clusters accepted findings by root cause, and after round 1 (and any later round that accepts a P0/P1 or opens a new cluster) the orchestrator writes `fix-plan.md` - one rule per cluster with every site, branch, realm and doc copy enumerated by search, what it must not break, and the test that fails without it - and the same seats review the plan before any code is written. Fixes then land one cluster per commit with every listed site in it.
- `rev-prompt.sh --plan <file>` renders the plan-review prompt; four plan lenses (`plan-completeness`, `plan-soundness`, `plan-simplicity`, `plan-tests`) are dealt like any round's. Every seat's `suggested_fix` must now state the general rule and its sibling sites, not a patch for the cited line.
- A `simplicity` lens leads round 1: a checklist for shrinking the change by reuse - workarounds whose stated reason no longer holds on the pinned dependency, parameters every caller passes identically, forwarding-only wrappers, single-value test axes - accepted at triage only with the existing symbol named at a location and version; scope cuts are deferred to the author.
- Why: measured over 11 past runs, 56% of findings were fixes of an earlier round's fix (68% from round 5 on), 55% of them incomplete fixes. `docs/churn-analysis-2026-09-06.md` has the numbers and method.

## 0.1.3

- Stack: a blank or failing status script is reported on the status line (`(status unavailable - see status.err)`) and its stderr is kept, instead of an empty field; `idle` can no longer print negative when a file mtime runs a second ahead of the clock.

## 0.1.2

- Graceful degradation: a machine with fewer than three seats is no longer refused. The roster pads the panel up to three with Claude seats (`claude-1`, `claude-2`, … , each dealt its own lens) and marks itself `degraded` with a one-sentence reason, which the session banner, preflight's `WARNING` line and the report's `Degraded panel:` opener all carry. A Claude-Code-only machine can now use the plugin.
- `min_labs` (default 1) is the opt-in hard floor that brings the old refusal back: below it the roster exits 5 with `strict: <k> lab(s) available, min_labs=<N>` and preflight stops the run.
- `roster.json` gains `labs`, `padded` and `degraded` (plus `degradation` when degraded), and padded seats carry `"padded": true`.

## 0.1.1

- Installing through `install.sh` now turns on auto-update for the review-council marketplace, so new releases arrive on their own; `--no-auto-update` (or `REVIEW_COUNCIL_NO_AUTO_UPDATE=1`) opts out and leaves `settings.json` untouched.
- The plugin's version lives only in `plugins/review-council/.claude-plugin/plugin.json`; the marketplace entry no longer pins one, where it would silently have overridden the manifest.
- Opt-in update notice: with `check_updates: true` in the config, the session banner adds one line when a newer version is published. Off by default, cached for a day, and silent on any failure.

## 0.1.0

- Initial release: `/review-council:rev` multi-model review-and-fix loop and `/review-council:stack` cross-repo orchestrator, ported from the in-harness `rev` skill.
- Roster built at run time from whichever of the Codex, Grok, Gemini and Claude (Opus) seats are installed and signed in, instead of a hardcoded seat list.
- `SessionStart` hook injects the standing review policy and a one-line roster summary every session.
- Portable across macOS and Linux; shimmed unit test suite with no network access, run in CI on both platforms.
