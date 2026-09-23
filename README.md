# review-council

Review Council runs one change through independent reviewer seats, verifies every
claim against source, fixes confirmed defects, reruns project gates, and repeats only
while material risk remains.

One exact council, used throughout this README, is:

| Seat | Provider | Model | Effort | Primary role |
| --- | --- | --- | --- | --- |
| `codex-sol` | OpenAI | `gpt-5.6-sol` | `max` | independent review |
| `codex-terra` | OpenAI | `gpt-5.6-terra` | `max` | independent review |
| `opus` | Anthropic | `opus` | `max` | independent review |
| `sonnet` | Anthropic | `sonnet` | `max` | independent review |

The roster is built and probed at run time. Exact configuration makes this
four-seat roster a requirement instead of a silent preference.

Grok is retired from live rosters. Gemini remains supported as an optional seat but is
excluded from the exact four-seat configuration above.

## What a review does

```text
preflight and probe
  -> freeze source, base, roster, models, efforts, and provider contracts
  -> simplicity discovery
  -> optional risk discovery
  -> verify and cluster findings
  -> review the fix plan when the fix is nontrivial
  -> apply confirmed fixes and run project gates
  -> four-bundle verification
  -> repeat only for new P0/P1 risk or another nontrivial fix
  -> publish the canonical PR review when an open PR is associated
  -> seal receipts, profile usage, and write the report
```

Key properties:

- The host skill is an executable workflow contract. Every applicable step runs in
  order; omitted steps require an explicit inapplicability reason.
- Every reviewer is read-only. Reviewers return findings; the host session owns
  triage, edits, tests, commits, and any authorized publication.
- Every core seat receives an independent task and produces the same findings schema.
- Agreement increases confidence but never replaces source verification.
- The source, prompt, evidence, transcript, result, model, and effort are hash-bound.
- Valid siblings are retained. Only a missing semantic bundle may trigger one
  full-state coverage repair after at least three valid reviewers.
- Provider quota fallback is explicit, visible, temporary, and limited to quota or
  capacity failures.
- Later panels review a safe semantic delta only after a valid predecessor receipt.
- Status and usage are read from session artifacts without another model call.
- Completed PR reviews use one deterministic `COMMENTED` review format with the
  badge, verdict tip, decisions, fixes, verified-sound, coverage, and footer sections.
  The inspected body, open PR, merge base, observed base tip, and clean reviewed head
  are frozen for exact retries. Publication rebinds that state to the reviewed scope,
  accepts base-tip movement only while the merge base is unchanged, serializes local
  retries, and creates a `COMMENTED` review pinned to the reviewed commit. Only an
  identical review on that commit suppresses a duplicate post. Discovery stays within
  the reviewed checkout's GitHub remotes.
  Local branches and document reviews without an associated open PR do not post. A
  stack publishes only the latest actually completed session for each canonical repository.

## Install

### Claude Code

Marketplace:

```bash
claude plugin marketplace add WiktorStarczewski/review-council
claude plugin install review-council@review-council
```

One-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install.sh | bash
```

The one-liner enables auto-update for the added marketplace. To leave Claude Code's
third-party marketplace default unchanged:

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install.sh | bash -s -- --no-auto-update
```

Manual update:

```bash
claude plugin update review-council
```

Restart Claude Code or run `/reload-plugins` after installation or update.

The installer changes only Claude Code's marketplace configuration. Its settings file
is rewritten at 2-space indent with every other setting preserved. The rewrite is
atomic, preserves the file mode, follows an existing symlink, and refuses an
unparseable settings file.

### Codex

Marketplace:

```bash
codex plugin marketplace add WiktorStarczewski/review-council
codex plugin add review-council@review-council
```

One-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install-codex.sh | bash
```

Manual update:

```bash
codex plugin marketplace upgrade review-council
codex plugin add review-council@review-council
```

Start a new Codex chat after installation or update. See [Codex setup and
behavior](docs/codex.md) for branch installs, local development, and host differences.

## Quick start

Claude Code:

```text
/review-council:rev
/review-council:rev uncommitted --read-only
/review-council:rev https://github.com/owner/repo/pull/123
/review-council:rev branch 4 --base origin/next
/review-council:stack /absolute/path/to/stack-config.sh
```

Codex:

```text
Use review-council to review this branch against origin/main.
Use review-council for one round, read-only, on my uncommitted changes.
Use review-council to review these design documents.
Use review-council to review the SDK and wallet branches as a dependency stack.
```

Review scope can be:

| Scope | Behavior |
| --- | --- |
| omitted or `branch` | current branch against the resolved base |
| `uncommitted` | staged, unstaged, and untracked work |
| path | selected files or directory |
| branch name | named branch against its resolved base |
| PR number or URL | PR head against its declared base |
| document paths | full read-only document review |
| `--read-only` | findings only, with no fixes, commits, squash, or push |
| `--base <ref>` | explicit base when automatic resolution is wrong |
| numeric rounds | minimum count using the legacy numbered schedule |

Code review defaults to the adaptive workflow. Read-only document and plan reviews
default to one full-scope panel.

The author's PR description is omitted from reviewer prompts by default to reduce
anchoring. It remains an explicit prompt-rendering option for controlled use.

## Requirements

- Bash
- Python 3 standard library, with no package installation
- Git
- a host with plugin support
- provider CLIs and sign-ins required by the selected roster

## Configure the exact four-seat council

Create `~/.config/review-council/config.json`:

```json
{
  "exclude": ["gemini"],
  "pin": {
    "codex-sol": { "effort": "max" },
    "codex-terra": { "effort": "max" }
  },
  "codex_models": ["gpt-5.6-sol", "gpt-5.6-terra"],
  "claude_models": ["opus", "sonnet"],
  "extras": false,
  "min_labs": 2,
  "quota_fallback": true
}
```

This means:

- both configured OpenAI models must exist and pass their probes;
- both configured Anthropic model families must pass their probes;
- all four seats run at maximum effort;
- Gemini and the optional `codex-review` extra are absent;
- at least two provider labs must be available before ordinary execution;
- quota fallback may temporarily preserve seat count with visible substitutions.

The config path is `${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}`.
Environment variables override config values where an environment equivalent exists.
See [configuration](docs/config.md) for every key and override.

## Preflight and frozen scope

Preflight runs before any paid review task.

| Step | Output or check |
| --- | --- |
| resolve scope | exact repository root, base branch, base SHA, head, and changed paths |
| reject unsafe start | empty scope, unresolved base, or a shared branch that should use a worktree |
| snapshot | `scope.env`, `files.txt`, `untracked.txt`, and canonical baseline patch |
| build roster | configured core seats, extras, models, efforts, labs, and exclusions |
| cheap detection | binary, sign-in state, credentials, and local model cache |
| provider probe | bounded live round trip for each unique adapter, model, and effort |
| contract replay | preserved provider envelopes checked against current adapters and auditors when self-host boundaries changed |
| baseline | existing project-gate failures recorded before review fixes |

The base is resolved in this order unless `--base` is supplied:

1. The open PR's declared base.
2. The nearest fork point among common development branches.
3. The repository's remote default branch.

All later artifacts bind the frozen source identity. A changed snapshot cannot be
combined with earlier prompts, results, audits, or receipts.

## Provider roster and probing

The roster is data, not an assumption. `roster.json` records:

- stable seat name;
- provider lab and adapter;
- exact model and effort;
- core, extra, or padded status;
- exclusions and their reasons;
- active degradation;
- strict refusal class and reason;
- temporary quota substitutions through `substitutes_for`;
- result-receipt policy for current and compatible historical sessions.

Detection is cheap. Preflight adds the live probe, with bounded time and output. An
identical adapter, model, and effort tuple shares its availability probe. Review tasks
still run independently.

Without exact settings, a short roster may be padded to three seats and marked
degraded. Padded seats receive different lenses but do not count as another lab.
`min_labs` turns provider diversity into a hard floor. Exact positive model or seat
counts are checked before padding.

Claude Code pads with Opus seats on the resolved Claude adapter: the Claude CLI, or
built-in Agent seats. Codex can pad only from surviving external CLI seats and refuses
when no usable external CLI remains.

## Adaptive phases

| Phase | When it runs | Coverage |
| --- | --- | --- |
| simplicity discovery | always | every core seat asks whether the change can be smaller through reuse or deletion |
| risk discovery | more than 25 files, more than 1,500 lines, or a high-risk boundary | the four risk bundles across the full panel |
| full red team | exactly once for a large, high-risk, user-marked-important, or explicitly adversarial adaptive review | four distinct adversarial compositions over the existing risk bundles, before planning |
| plan | after triage and before any edit, when an accepted fix is nontrivial | one plan-completeness seat; `plan_seats: "all"` adds soundness, simplicity, and falsifiable tests |
| fix and gates | after accepted and plan-approved findings, or a recorded plan skip | root-cause clusters, relevant regression tests, project gates at baseline or better |
| verification | after discovery when no nontrivial fix follows, or after the latest nontrivial fix | all four risk bundles over the latest material state, plus a sibling-site check of every fix commit |

High-risk boundaries include security, persistence, concurrency, transactions,
protocols, public APIs, and irreversible mutations.

For the four-seat council:

| Change shape | Planned seat launches |
| --- | ---: |
| ordinary, no nontrivial fix | 8 |
| ordinary, with one plan panel | 9 |
| large or high-risk, no nontrivial fix | 16 |
| large or high-risk, with one plan panel | 17 |

With four core seats, a normal review plans 9 seat launches: four simplicity, one
conditional plan, and four final verification launches. A large or high-risk review
plans 17 by adding four risk-discovery and four full red-team launches. An important
or explicitly adversarial review that is not otherwise large or high-risk adds the
four full red-team launches. With `plan_seats: "all"`, every plan panel launches all
four core seats instead of one.

`rev-state.sh` refuses `phase=fix` while P0-P2 findings are open until the round's plan
panel completed or `findings.md` records `Plan panel r<N>p - SKIPPED: <reason>`. It also
refuses when the open counts predate the round's newest seat exit, so a counter still
holding the previous round's zeroes cannot short-circuit the gate.

One four-bundle verification panel reviews the latest material state: directly after
discovery when no nontrivial fix follows, or after the latest nontrivial fix. Adaptive
default panels use core seats and omit extras. Explicit numeric round plans may include
extras in their configured rounds.

Another plan and verification cycle starts only for a new P0/P1 root cause, an open
P0/P1, or another nontrivial fix. A P3 or one-line P2 follow-up needs project gates.
Every other accepted fix needs the full adaptive verification panel.

## Review bundles

Every risk and verification panel covers all four bundles:

| Bundle | Questions |
| --- | --- |
| `correctness-boundaries` | logic, edge cases, errors, input and output boundaries |
| `security-state-api` | trust boundaries, durable state, compatibility, public contracts |
| `concurrency-resources-performance` | races, cancellation, ownership, cleanup, limits, hot paths |
| `tests-observability-maintenance-regression` | meaningful tests, failure visibility, maintainability, cumulative regressions |

With four seats, each seat receives one bundle. With three seats, one seat receives
two. Surplus seats cycle the bundles. The regression bundle owns the full cumulative
state during risk and verification.

Every code panel also composes red-team emphasis into one existing core seat, selected
from stable roster order and rotated across panels. This preserves the seat's normal
lens and bundle and adds no provider call or panel, including in numeric and read-only
code reviews. The conditional full red-team panel reuses the four bundles with distinct
attacker and trust-boundary, rollback and recovery, duplication and exhaustion, and
consumer compatibility and integration emphases. Document panels are excluded unless
the user explicitly requests adversarial document review.

### Why simplicity runs first

Every core seat checks for:

- an existing framework, engine, or repository mechanism that replaces new machinery;
- a workaround whose stated dependency limitation no longer exists;
- a parameter every caller passes identically;
- a generic or test axis with only one implementation or value;
- an unreleased migration that can fold into the schema it changes;
- a public surface that does not follow the repository's export convention;
- scope larger than the named consumer requires.

Reuse findings must name the existing symbol, location, and version. Scope cuts remain
author decisions. On eight held-out PRs, four simplicity seats found 6 of 10
load-bearing simplifications; one seat found about half that. Substituting one
`clean-room` seat or including the author's PR description reduced recall, so both are
opt-in rather than defaults. See
[the held-out evaluation](docs/simplicity-lens-eval-2026-09-06.md).

### Legacy numeric schedule

An explicit round count selects this minimum schedule:

| Round | Emphasis | Lenses or extra |
| ---: | --- | --- |
| 1 | reduce the change | simplicity on every core seat |
| 2 | logic and boundaries | correctness, edge cases, error handling |
| 3 | security and state | security, data state, optional `codex-review` extra |
| 4 | concurrency and resources | concurrency, resources, performance |
| 5 | contracts | API contract, readability, maintainability |
| 6 | verification | tests, observability |
| 7 | adversarial challenge | red team |
| 8 | cumulative reread | regression |
| 9+ | remaining gaps | uncovered or unresolved lenses |

## Evidence compiler

Adaptive code and plan panels do not paste the full repository into every prompt.
`rev-evidence.py` builds a deterministic, auditable evidence packet from the frozen
scope.

### Semantic routing

- Changed code is grouped into dependency components.
- Every component gets a specialist and the full-state integration seat.
- A component with a prior finding returns to that finding's seat when safe.
- Mechanical lockfiles, generated output, snapshots, and locale copies go to the
  named full-state seat instead of every seat.
- If complete component coverage cannot be proved, the affected panel returns to the
  full cumulative patch.

### Patch proof

| Delivery | Used when | Limits and proof |
| --- | --- | --- |
| bounded windows | small, binary, NUL-containing, invalid UTF-8, or chunking disabled | at most 240 lines per window |
| ordered chunks | safe UTF-8 patch where reads drop by at least 10 percent, or capacity requires it | at most 24 KiB raw, 30 KiB rendered, and 1,000 displayed lines per chunk |

Chunk byte ranges are contiguous and reconstruct the canonical patch exactly. Each
reviewer reads every assigned chunk once, in order, before opening source packets.
Chunk reads prove change coverage; they do not prove a finding's source citation.

`REV_PATCH_CHUNKS=auto` is the default. `1` forces representable chunks. `0` requests
window mode and makes preparation fail when window mode cannot fit.

### Source packets

Literal source packets contain exact bytes from the frozen tree:

- enclosing declarations;
- direct callers and changed local imports;
- related tests;
- configuration gates;
- repository instructions in a separate bound snapshot.

A specialist receives at most one 32 KiB source shard. The integration seat receives
at most three. Oversized required ranges become ordered, gap-free session artifacts of
at most 240 lines and normally at most 16 KiB each. An indivisible single line may use
the 32 KiB tool-output ceiling.

`REV_SOURCE_CONTEXT=1` is the host default. Setting it to `0` is reserved for a
labeled baseline measurement.

### Capacity compilation

Before prompt publication, the compiler checks every obligation against the selected
adapter's call and turn capacity:

- patch chunks or windows;
- source shards and required-source segments;
- evidence index and repository expansion;
- mandatory first read for plan specialists;
- reserved capacity for investigation and the final findings JSON.

Excess source ranges are promoted to deterministic session artifacts. Chunks can be
enabled automatically when bounded windows cannot fit. If the complete read contract
still cannot fit, preparation fails before a reviewer launch. Each assignment records
its capacity decision in the evidence manifest and receipt.

Prompt generation warns above 1,800 words for code and 3,000 words for plans. The
operator must investigate repeated context rather than silently truncate evidence.

## Plan gate

Accepted findings are grouped by root cause before editing. Each nontrivial cluster in
`fix-plan.md` contains:

- finding IDs and severities;
- the general rule that closes the defect;
- every affected site, branch, realm, caller, test, and documentation copy;
- behavior that must remain unchanged;
- interactions and landing order;
- a falsifiable regression test.

Each cluster's sibling-site search is run once by preparation against the frozen
repository. Only these forms can certify the search:

```bash
rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'PATTERN' .
grep --exclude-dir=.git --null -r -n -- 'PATTERN' .
```

The search must return 1-80 NUL-delimited, line-numbered path records and include every
named site. Extra path operands, traversal filters, redirected output, alternate grep
frontends, saturated results, or producer errors fail closed.
Live fallback searches append `| head -81`; the 81st record is an overflow sentinel and
never earns a completeness proof.

Plan routing:

- `plan-completeness` receives the full cumulative patch and every cluster. By default
  it is the whole plan panel: the first core seat whose adapter is not `agent`.
- With `plan_seats: "all"`, each cluster also goes to one specialist.
- Specialists receive a valid receipt-relative fix delta when available.
- Otherwise specialists receive the cumulative closure for their clusters.
- Every seat receives the complete inline plan and navigation index.
- The inline plan is authoritative; no separate plan snapshot may be opened.
- Every specialist receives one exact primary artifact as its mandatory first native
  read. A directory listing, search, or compound command before or with it invalidates
  the attempt.

Plan panels never broaden a failed specialist to legacy full scope. A repeated
seat-local failure leaves the plan incomplete so invalid evidence cannot become code.

The plan gate addresses measured fix churn. Across 11 past runs, 56 percent of findings
were defects in an earlier review fix, rising to 68 percent from round five onward; 55
percent of those fixes applied the right rule to only one site. See
[the churn analysis](docs/churn-analysis-2026-09-06.md).

Whenever tests change, every review prompt also applies a vacuity check: name the
production change that would make each assertion fail and report an assertion that has
no such mutation.

## Reviewer read contract

Each evidence prompt names the only authorized artifacts and their order. The audit
requires:

- the exact manifest and prompt hashes;
- a supported provider transcript;
- at least one recognized review tool call;
- complete assigned patch reads;
- complete source-packet and required-source reads;
- required chunk order and byte coverage;
- the plan specialist's mandatory first native read;
- bounded repository expansion;
- every finding citation to intersect an audited source range;
- valid findings JSON matching the shared schema.

Claude CLI seats receive only `Read` and `Grep`, with bounded pre-tool and post-tool
checks. Inherited settings, plugins, MCP configuration, and editing tools are disabled.
Codex seats use the read-only sandbox. Agent-adapter seats (`claude_adapter: agent`, or
`auto` without a signed-in Claude CLI) disable editing tools, but their native read hooks
cannot satisfy enforced evidence. They run evidence mode anyway and are recorded in the
manifest's `unenforced_seats`: their read audit stops gating rather than the panel stopping, so a
panel holding one is partially unenforced and never certified. That audit is still produced and
reported under `unenforced_audits` with its would-have-passed verdict, so the agent pass rate can
be measured before anyone decides whether it can be enforced.

Nonfinal Claude CLI responses carry a continuation instruction: while required review
work remains, the response must include the next allowed read or search. Progress text
alone cannot end the task after compaction.

## Result validation and transport audit

A plausible prose answer is not a valid review result. Completion requires:

1. Provider process termination.
2. A terminal `.exit` receipt.
3. Findings JSON that validates against `findings.schema.json`.
4. A matching immutable prompt generation.
5. A valid read audit for evidence panels.
6. A panel receipt selecting exactly one valid generation per assignment.

A run missing any audit, receipt, or final report required by its selected mode is
incomplete and cannot be described as a Review Council review. This rule appears in
the always-loaded Claude Code policy and in both host-specific `/rev` skills.

The audit distinguishes provider transport failure from a source-backed finding.
Unsupported stream shapes, zero-tool answers, missing output, malformed JSON, stale
receipts, hash mismatches, and incomplete evidence reads cannot certify the panel.
When patch, required-source, citation, and result proof are complete, read order,
repository call count, output overflow, a missing navigation index, and duplicate
completed reads remain visible as advisories. They do not discard the review.

A persistent attempt budget allows at most four provider calls for one seat generation
across wrapper and host retries. Exhaustion is a local exit 7 and is never reclassified
as provider quota.

## Seat-local recovery

| Failure | Recovery |
| --- | --- |
| first provider exit 1 or 2 without an invalid audit | retry only that seat once with the exact prompt, assignment, model, and effort |
| hard evidence-audit failure | preserve all artifacts, block every seat under that label, and stop the panel before another paid launch |
| valid sibling | retain its result, transcript, audit, and usage |
| at least three valid reviewers but one missing semantic bundle | run one full-state coverage repair on a surviving seat |
| provider seat fails twice or a plan seat fails twice | leave the configured panel incomplete |
| receipt failure | diagnose the provenance or contract defect and end the run without automatic reviewers |

Audit failures never widen into a full-state repair. Review fixes wait until the
receipt seals, even when valid results are triaged while slower siblings remain active.

## Quota fallback

Quota fallback is off by default. Enable it with:

```json
{ "quota_fallback": true }
```

| Failed preferred provider | Temporary substitutes |
| --- | --- |
| Anthropic quota or capacity | unique Terra seats |
| OpenAI quota or capacity | unique Sonnet seats |

Rules:

- Only provider-reported quota or capacity qualifies.
- A Claude Code Agent seat uses platform terminal metadata, never reviewer prose.
- Authentication, configuration, unknown, missing-target, and failed-target errors do
  not substitute.
- A substitute records `substitutes_for`. A temporary `min_labs` waiver applies only
  when successful quota substitutions account for the complete diversity shortfall.
- Pending siblings are stopped after their terminal state is preserved.
- Preflight runs in a fresh sibling session and refuses an initialized target.
- The fallback session's scope, file list, and untracked-file list must byte-match the
  original before the complete panel restarts.
- Its evidence manifest must also match the original content-addressed base and snapshot
  trees, scope, and paths, including same-path tracked, staged, and untracked content.
- Results from the quota-failed label remain diagnostic and do not enter the receipt.
- One quota fallback panel is the only permitted full-panel restart.
- A hard audit failure in fallback stops without repair or another fallback.
- Fallback never edits configuration.
- The next review probes the preferred roster again, so restored capacity restores the
  configured council automatically.
- A fallback seat that also reports quota stops the panel. There is no recursive chain.

## Triage and finding levels

Every claim is opened at its cited location and checked through the relevant control
flow before acceptance.

| Level | Meaning | Examples |
| --- | --- | --- |
| P0 | incorrect behavior, security hole, data loss, or crash | unsafe authorization bypass, destructive state corruption |
| P1 | reachable bug, edge case, or broken contract | duplicate side effect, missing retry boundary, incompatible API behavior |
| P2 | maintainability, performance, missing test, or unclear API | avoidable hot-path cost, untested failure branch, misleading public contract |
| P3 | trivial style, naming, or comment issue | stale harmless comment, local naming nit, harmless formatting inconsistency |

Each finding gets a durable ledger status:

- `OPEN`
- `FIXED`
- `REJECTED (reason)`
- `DEFERRED (reason)`

Duplicate findings are merged by root cause and record every independent reporting
seat. Rejections include source-backed reasons so later panels do not resurface settled
claims. Confirmed P3 findings can remain explicitly deferred for a later cleanup while
release-blocking review converges on P0-P2.

## Fix, tests, and convergence

The host session applies accepted findings automatically within the authorized scope:

1. Apply one root-cause rule across every listed sibling site.
2. Preserve unrelated user changes.
3. Add a regression test that fails under the broken behavior when warranted.
4. Run the repository's full gate list, not the subset the diff suggests, and
   restore baseline or better.
5. Run the mutation check over the changed hunks before committing.
6. Commit coherent clusters only when the workflow authorizes commits.
7. Run a full four-bundle verification panel after a material fix.

Adaptive review completes only when:

- all four verification bundles have valid results;
- no new or open P0/P1 remains;
- no material change remains unreviewed;
- project gates are at baseline or better;
- the final panel receipt seals.

An explicit numeric round count selects the legacy schedule. It is a minimum, not an
automatic stop. Numeric mode also requires two consecutive numbered code panels with
no new P0/P1, no open P0/P1, complete lens and major-file coverage, and passing gates.
Plan panels do not count toward the requested numeric total.

Read-only runs report findings and stop at the requested panel count. They never fix,
commit, squash, push, or require code convergence.

## Status

During an active run, `rev-status.sh` reports one line every ten minutes:

```text
r3/adaptive triage | sol: done 4f 9m | terra: running 14m | opus: done 3f 8m | sonnet: done 2f 7m | open P0:0 P1:1 P2:3 fixed 6
```

Each seat is `running`, `done`, `failed`, or `dropped`, with elapsed time and the last
recorded action where available. Overall counts come from `state.json`. Reading status
does not contact a provider.

## Receipts and session artifacts

A session lives outside the reviewed tree, normally under `/tmp/rev-*`.

```text
scope.env
files.txt
untracked.txt
roster.json
00-baseline.patch
baseline.md
findings.md
rejected.md
fix-plan.md
context.md
state.json
stack-report.md
report.md
r<label>-evidence.manifest.json
r<label>-<seat>.prompt.md
r<label>-<seat>.stream.ndjson
r<label>-<seat>.log
r<label>-<seat>.json
r<label>-<seat>.exit
r<label>-<seat>.read-audit.json
r<label>-<seat>.audit-invalid.json  # hard audit failure only; diagnostic, never accepted
r<label>-coverage.receipt.json
```

Receipt roles:

| Receipt | Proves |
| --- | --- |
| provider contract | current adapter and auditor accept preserved provider envelopes for the exact provider boundary and CLI versions |
| exit | the specific seat generation terminated successfully |
| read audit | the transcript completed its hash-bound evidence obligations |
| panel | one immutable valid generation covers every assignment |
| `stack-report.md` | a stack leg completed locally and is ready for finalization and publication |
| `report.md` | publication succeeded or cleanly skipped and the review completed |

Interrupted or blocked runs write `incomplete.md`. They do not write a success report.
Current sessions require successful receipts. Compatible historical receiptless results
are accepted only when a versioned roster policy already records their exact hashes.

## Completion report

`report.md` contains:

1. outcome and current soundness;
2. exact roster, efforts, padding, substitution, and degradation;
3. accepted, fixed, rejected, and deferred findings, sorted by severity;
4. panel, bundle, lens, and changed-file coverage;
5. baseline and final project gates;
6. commits, squash, and push status when those actions were authorized;
7. residual risk and anything that still deserves human attention.

The report states late P0 findings plainly. A degraded verdict opens with its exact
degradation reason.

## Profiling and measurement

Run:

```bash
python3 plugins/review-council/scripts/rev-profile.py /tmp/rev-SESSION
```

The profile separates:

- completed, metered, and unmetered calls;
- provider input, output, processed, cached-read, and cache-write tokens;
- provider-reported cost where available;
- prompt words for code and plan panels;
- full, assigned, delta, evidence, and avoided projected scope words;
- patch proof calls, turns, visible bytes, chunks, and delivery modes;
- receipt-relative and cumulative plan routing;
- finding yield from receipt-valid results;
- the deterministic core-roster signature.

Mixed-roster output is marked as a measurement boundary. Historical baselines retain
the roster that produced them. Planned word savings remain separate from actual
provider usage and cost.

## Stack reviews

Use a stack when one change crosses dependent repositories or PRs.

```text
/review-council:stack <config>
```

The stack runner:

1. Runs one Review Council leg per repository in dependency order.
2. Uses isolated repository paths or worktrees supplied by the config.
3. Keeps one session root with per-leg ledgers, logs, and stack-ready reports.
4. Detects stalls from both log activity and process-tree CPU before retrying.
5. Resumes a leg from its existing session instead of discarding verified work.
6. Runs cross-repository seam passes after repository-local review.
7. Runs a final completeness critic when configured.
8. Promotes `stack-report.md` to `report.md` only after publication or a no-push skip.
9. Publishes successful repositories even when a sibling fails, while preserving the
   overall nonzero stack result.

Claude Code stack legs use `claude -p`. Codex stack legs use `codex exec` with
workspace-write for authorized fixes, network access for reviewer providers, and write
access to the session root. Legs never launch another stack.

Codex defaults to `NO_PUSH=1 NO_SQUASH=1`. Publication and history rewriting require
the caller's existing authorization. A failed repository is skipped entirely during
stack finishing.

See [the stack config example](plugins/review-council/scripts/stack.example.sh).

## Failure and exit behavior

| Exit | Class | Meaning | Action |
| ---: | --- | --- | --- |
| 0 | success | valid findings result | audit and retain |
| 1 | seat-local | retryable provider or adapter failure | exact retry once when no invalid audit exists |
| 2 | seat-local | missing or invalid findings JSON | exact retry once when no invalid audit exists |
| 3 | provider-global | not signed in | stop and name the required sign-in |
| 4 | provider-global | provider quota, rate, or capacity | stop, or use explicit quota fallback |
| 5 | roster availability | currently unsatisfied but possible roster | preserve session and retry when availability changes |
| 6 | roster configuration | malformed or impossible exact configuration | fix configuration before retry |
| 7 | local attempt budget | persistent seat-generation attempt cap exhausted | preserve valid siblings; never treat as quota |

Other fail-closed conditions include:

- source changed after freeze;
- prompt, manifest, transcript, or result hash mismatch;
- incomplete patch, packet, segment, search, or citation proof;
- provider stream shape unsupported by the current auditor;
- plan task exceeds compiled provider capacity;
- project gate falls below baseline;
- squash safety check refuses;
- stack leg exits without a fresh `stack-report.md` and `phase=stack-ready` state.

A hard read-audit failure stops the current run before another reviewer launch. It is
reported as an evidence compiler or contract defect, with valid siblings and partial
streams preserved for diagnosis.

## Read-only and security boundaries

- Reviewer processes receive vendor-enforced read-only or plan modes.
- Reviewer prompts cannot grant editing, execution, publication, or credential access.
- Claude CLI review processes inherit no user plugins or MCP configuration and expose
  only audited `Read` and `Grep` tools.
- Evidence search accepts one documented repository-root form and treats pattern and
  paths as data.
- Prompt, output, provider-status, and provider-version calls have bounded time and
  output.
- Provider attempts preserve raw streams for diagnosis before retry.
- Session evidence stays outside reviewed source.
- Verifier state and material reads are descriptor-relative, reject symlink traversal,
  and recheck source identity around use.
- Local plugin publication uses an atomic directory install or exchange, so a failed
  replacement preserves the live plugin.
- `REV_ACTIVE=1` blocks nested review loops. `REV_STACK_LEG=1` blocks nested stacks and
  delegates finishing to the stack runner.
- Reviewers never execute findings. The host session independently verifies each claim
  before changing code.

## Claude Code hooks

The Claude Code plugin installs two hooks. Codex uses native skills and installs neither.

### Session hook

On `startup`, `clear`, and `compact`, the Claude Code plugin performs cheap local work:

1. Inject the standing review policy.
2. Print the detected roster summary.
3. Optionally report an available update when `check_updates: true`.

The hook makes no model call. Update checks are off by default, cached for one day,
bounded to three seconds, and silent on failure. The hook reports an update but never
replaces the plugin directory it is running from.

### Stop hook

A review is a queue, and the recurring failure is ending a turn on a status summary while
items remain: finishing a round, a cluster or a commit reads like a handoff point and is not
one. The `Stop` hook makes that structural rather than advisory. It reads the newest review
session's `state.json` and blocks the stop while that session is not `done`, naming the round,
phase and open findings in its reason.

It is built to be wrong in the safe direction, because a guard that wrongly blocks is worse
than one that misses: it allows whenever there is no session, the session is over six hours
old, the state is unreadable, `python3` is missing, or its own counter cannot be persisted. It
allows after three consecutive blocks so it can never loop, and once released it stays released
for that session until the review is done. It allows a genuine wait, where the round is parked on
seats that have not answered, every returned seat is triaged and the tree is clean. It makes no
model call and never touches the repository.

It is scoped to the working tree the stopping session is in, matched against each review's
recorded `REV_ROOT`, because review sessions share one `/tmp` namespace and concurrent sessions
are normal. A review whose `scope.env` cannot be read still blocks, since dropping it would
disarm the guard. Only session directories owned by the current user count, because `/tmp` is
world-writable.

The consecutive-block counter lives in `$XDG_STATE_HOME/review-council` (or
`~/.local/state/review-council`), one file per stopping session, so another session's outcome
cannot move it - a single shared counter is not a cap, because every allow path resets it.
`REVIEW_COUNCIL_STATE_DIR` overrides that directory, and `REVIEW_COUNCIL_SESSION_ROOTS` overrides
where sessions are discovered so a test can own the state it reads.

## Host differences

| Behavior | Claude Code | Codex |
| --- | --- | --- |
| Anthropic core seats | signed-in Claude CLI, else built-in Agent seats (`claude_adapter`) | signed-in Claude CLI |
| OpenAI seats | Codex CLI | Codex CLI |
| thin roster padding | Opus seats on the resolved Claude adapter | surviving external CLI seats |
| no usable external CLI | can run a visibly degraded Agent panel | refuses |
| session startup policy | plugin hook | native skill discovery |
| stack leg | `claude -p` | `codex exec` |
| stack finishing default | config-controlled | local and unsquashed |

Both hosts share the roster, evidence, schema, adapters, ledgers, status, profiling,
and receipt implementation.

## Configuration reference

| Key | Default | Purpose |
| --- | --- | --- |
| `exclude` | `[]` | omit detected labs or seats |
| `pin` | `{}` | override a detected seat model or effort |
| `codex_models` | newest two visible | require one or two exact OpenAI model slugs |
| `claude_models` | absent | require exact `opus` and/or `sonnet` families |
| `claude_seats` | `1` | legacy count of independent Opus seats, mutually exclusive with `claude_models` |
| `claude_seat` | `true` | disable detected Claude seats when false |
| `claude_adapter` | `auto` | Claude Code seats Claude rows on the CLI (`cli`), Agent subagents (`agent`), or the CLI when signed in (`auto`) |
| `plan_seats` | `completeness` | one plan-completeness seat per plan panel, or `all` for the four-lens plan panel |
| `extras` | `true` | expose `codex-review` to explicit numeric schedules |
| `min_labs` | `1` | minimum detected provider labs before padding |
| `quota_fallback` | `false` | permit explicit temporary cross-provider quota substitution |
| `check_updates` | `false` | print an available-update line in Claude Code |

Useful evidence controls:

| Variable | Default | Purpose |
| --- | --- | --- |
| `REV_PATCH_CHUNKS` | `auto` | automatic, forced, or disabled exact patch chunks |
| `REV_SOURCE_CONTEXT` | `1` in host skills | literal source packets and required-source segments |
| `REV_CODEX_SOURCE_BATCH` | `0` | certified Codex-only source-window batch canary |
| `REVIEW_COUNCIL_PROVIDER_OUTPUT_BYTES` | 1 MiB | provider status and probe output cap |
| `REVIEW_COUNCIL_CONTRACT_VERSION_TIMEOUT_SECONDS` | 5 | provider CLI version timeout |
| `REVIEW_COUNCIL_CONTRACT_VERSION_OUTPUT_BYTES` | 64 KiB | provider CLI version output cap |

Full reference: [docs/config.md](docs/config.md).

## Current limitations

- Provider probes and reviewer calls consume each provider's usage.
- Exact rosters depend on installed, signed-in CLIs and a current local Codex model
  cache.
- Quota fallback covers quota and capacity only. It does not hide authentication,
  configuration, model, adapter, or unknown failures.
- A panel seating a reviewer on the `agent` adapter is never certified, because that
  adapter cannot provide the enforced read transcript. It still runs: the seat is recorded
  unenforced, its audit is reported without gating, and the panel is reported as partially
  unenforced.
- Explicit numeric code reviews and document reviews retain full scope instead of
  adaptive evidence narrowing.
- Evidence chunks prove complete change reads but do not replace source reads for
  findings.
- A valid receipt proves that the review contract ran over the named bytes. It does not
  make a finding true; triage still verifies the claim.
- The Gemini adapter is fixture-tested against the documented streaming interface but
  has not been certified on a live Gemini CLI in this repository's development setup.
- Some sandboxes restrict nested provider CLIs or repository gates. The failure stays
  visible and does not enable broader permissions automatically.
- A full live multi-repository stack can consume substantial provider usage.
- Provider-specific inline evidence beyond the current audited packet delivery remains
  gated on a clean held-out council run.

## Development and release verification

The bounded 0.4.4 operator sequence is documented in the [release procedure](docs/release.md).
It uses a signed-tag 0.4.3 worktree for N-1 review, the existing deterministic
candidate gate, P0/P1-only repairs, and at most one clean delta generation.

Fast name-filtered shell tests:

```bash
plugins/review-council/tests/run-tests.sh roster
plugins/review-council/tests/run-tests.sh evidence
plugins/review-council/tests/run-tests.sh quota
```

Full suites:

```bash
plugins/review-council/tests/run-tests.sh
python3 -m unittest discover -s tests -v
```

Unified release gate:

```bash
python3 scripts/verify-review-council.py --root .
```

The unified verifier freezes one tree, reconciles the exact test inventory, runs shell
and Python suites, builds the Codex bundle, validates manifests and static contracts,
checks command logs for terminal success, and publishes a hash-bound receipt only when
every stage refers to the same source tree.

Tests use local CLI shims and do not contact live provider accounts. Live compatibility
checks use preserved provider-envelope replay and the signed previous-stable review.

Local Codex bundle:

```bash
python3 scripts/build-codex-plugin.py --output /tmp/review-council
python3 scripts/install-codex-plugin.py
```

Installation refuses an unrelated output directory or conflicting personal marketplace
entry. Bundle replacement is atomic, so an interrupted update does not leave a partial
live plugin.

## Why a council

Reviewers from different providers fail differently. Independent reads expose blind
spots that repeated self-review often preserves. The council keeps that diversity while
making the result auditable: every accepted claim is source-verified, every evidence
read is bounded and receipted, and every material fix returns through verification.
