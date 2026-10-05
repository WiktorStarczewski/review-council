<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
    <img alt="review-council: a multi-model review council for Claude Code and Codex" src="docs/assets/hero-light.svg" width="100%">
  </picture>
</p>

<p align="center">
  <a href="CHANGELOG.md"><img alt="version" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FWiktorStarczewski%2Freview-council%2Fmain%2Fplugins%2Freview-council%2F.claude-plugin%2Fplugin.json&query=%24.version&label=version&color=2da44e"></a>
  <a href="LICENSE"><img alt="license: MIT" src="https://img.shields.io/github/license/WiktorStarczewski/review-council?color=0969da"></a>
  <img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude%20Code-plugin-d97757">
  <img alt="Codex plugin" src="https://img.shields.io/badge/Codex-plugin-412991">
  <img alt="runtime: bash and the python3 standard library" src="https://img.shields.io/badge/runtime-bash%20%2B%20python3%20stdlib-57606a">
</p>

<p align="center">
  <a href="#install">Install</a> &nbsp;·&nbsp;
  <a href="#quick-start">Quick start</a> &nbsp;·&nbsp;
  <a href="#how-a-review-runs">How a review runs</a> &nbsp;·&nbsp;
  <a href="#configure">Configure</a> &nbsp;·&nbsp;
  <a href="#evidence-and-receipts">Evidence and receipts</a> &nbsp;·&nbsp;
  <a href="#status-and-reports">Status and reports</a> &nbsp;·&nbsp;
  <a href="#stack-reviews">Stack reviews</a> &nbsp;·&nbsp;
  <a href="#reference">Reference</a>
</p>

Review Council runs one change past independent reviewers from different labs, opens every
claim they make at its cited line, fixes what holds up, reruns your project's gates, and sends
the fixes back through review until no material risk remains. Reviewers only read. The session
you run it from owns every edit, test, commit and publication.

## Why a council

- **Different labs fail differently.** A reviewer that shares your model's weights shares its
  blind spots. OpenAI and Anthropic seats, plus Gemini when it is installed, read the same
  change independently.
- **Agreement is not proof.** Every finding is checked against source before anything changes.
  Rejected claims are recorded with their reason, so later panels do not raise them again.
- **Fixes get reviewed too.** In 11 past runs, 56% of findings were defects in an earlier
  review fix ([churn analysis](docs/churn-analysis-2026-09-06.md)). A plan gate checks each
  nontrivial fix before it is written, and a verification panel reviews the result.
- **Evidence is receipted.** Each adaptive code panel binds source, prompt, transcript, model
  and effort by hash. A run that cannot prove its panels is reported incomplete, never as a
  review.

## Install

**Claude Code**

```bash
claude plugin marketplace add WiktorStarczewski/review-council
claude plugin install review-council@review-council
```

Restart Claude Code or run `/reload-plugins`.

**Codex**

```bash
codex plugin marketplace add WiktorStarczewski/review-council
codex plugin add review-council@review-council
```

Start a new Codex chat. [Codex setup](docs/codex.md) covers branch installs, local
development and host differences.

> [!NOTE]
> Seats come from the provider CLIs you have signed in: Codex for OpenAI, Claude for
> Anthropic, and optionally Gemini. A roster of fewer than three seats is padded with extra
> seats and marked degraded. Without a signed-in Claude CLI, Claude Code falls back to
> built-in Agent seats, which run but never certify a panel.

<details>
<summary><b>One-line installers, updates and requirements</b></summary>

<br>

```bash
# Claude Code: install in one line, or update; then restart or /reload-plugins
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install.sh | bash
claude plugin update review-council

# Codex: install in one line, or update; then start a new chat
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install-codex.sh | bash
codex plugin marketplace upgrade review-council && codex plugin add review-council@review-council
```

The Claude Code one-liner also turns on auto-update for the marketplace (skip that with
`bash -s -- --no-auto-update` or `REVIEW_COUNCIL_NO_AUTO_UPDATE=1`) and updates an existing
install when rerun. It touches only Claude Code's marketplace configuration: the settings
file is rewritten at 2-space indent with
every other setting preserved, atomically and keeping its mode; an unparseable file is
refused. The Codex one-liner takes `--ref <branch>` or `REVIEW_COUNCIL_REF`.

**Requirements:** Bash, Git, Python 3 (standard library only), `gh` for PR scopes and
publication, ripgrep for plan searches (Codex needs a real `rg`), and the provider CLIs your
roster needs.

</details>

## Quick start

| In Claude Code | What it does |
| --- | --- |
| `/review-council:rev` | reviews this branch against its base, commits each fix, then pushes |
| `/review-council:rev uncommitted --read-only` | reports findings on your working tree and changes nothing |
| `/review-council:rev https://github.com/o/r/pull/12` | checks the PR out, commits and pushes fixes to its branch, posts one review |
| `/review-council:rev branch 4 --base origin/next` | at least four numbered panels against an explicit base |
| `/review-council:rev docs/design.md` | read-only review of a document |
| `/review-council:stack /absolute/path/to/stack-config.sh` | one change across several repositories, in dependency order |

In Codex, ask in plain words: *"Use review-council to review this branch against
origin/main"*, *"... for one round, read-only, on my uncommitted changes"*, or *"... to review
the SDK and wallet branches as a dependency stack"*.

> [!TIP]
> Run it from a working branch: preflight refuses to start on `main`, `master`, the default
> branch or the base branch. To review someone else's PR without pushing to it, add
> `--read-only`; the review is still posted to the PR.

<details>
<summary><b>Every scope form</b></summary>

<br>

| Scope | Reviews |
| --- | --- |
| omitted or `branch` | the current branch against its resolved base |
| `uncommitted` | staged, unstaged and untracked work |
| a path | the selected files or directory |
| a branch name | that branch against its base |
| PR number or URL | the PR head against its declared base |
| `.md`, `.txt` or `.rst` paths | the documents, read-only |
| `--read-only` | findings only: no fixes, commits or push; an open PR still gets the review (`NO_PUSH=1` skips posting) |
| `--base <ref>` | an explicit base, when the printed base is wrong |
| a number | a minimum panel count on the legacy numbered schedule |

Claude Code reviews another branch or a PR by checking it out in the current checkout;
Codex uses an isolated worktree. Code reviews run the adaptive workflow. Read-only code
reviews and document reviews run one panel unless a round count is given.

</details>

## How a review runs

| Term | Meaning |
| --- | --- |
| seat | one reviewer: a model at a fixed effort, run through one provider CLI |
| panel | the seats reviewing one frozen state of the change, in parallel |
| bundle | one of four risk areas a verification seat owns |
| receipt | the hash-bound proof that every seat in a panel read its evidence and returned a valid result |
| P0-P3 | severity: P0 breaks behaviour, security or data; P1 is a reachable bug; P2 a maintainability, performance or test gap; P3 a nit |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/loop-dark.svg">
  <img alt="Discover, triage, plan, fix and gates, verify; a new P0 or P1 or another nontrivial fix loops back to triage" src="docs/assets/loop-light.svg" width="100%">
</picture>

- **Seats only read; the host edits.** The session you run it from triages, fixes, tests,
  commits and publishes.
- **Depth adapts to the change.** With four seats, an ordinary change gets simplicity
  discovery and one verification panel, 8 seat launches. A large or risky change adds a risk
  panel and a red team.
- **One commit per fix.** Each finding cluster is its own commit, P0 first, and the subject
  names the finding IDs it closes, for example `fix(rev): F-012, F-019 re-check hold
  ownership`. The loop never squashes, amends or skips hooks.
- **It stops when the latest state is clean:** a valid four-bundle verification, no new or
  open P0/P1, nothing unreviewed, and gates at or better than baseline.
- **It stops for you when the review starts reviewing itself.** If two receipted rounds cite
  lines the review changed, the run pauses and recommends reverting those changes and
  deferring the findings that caused them (the review-origin breaker).

### Anatomy of a large review

A 60-file change that touches persistence and concurrency. Discovery finds defects that need
a nontrivial fix, and verification then finds one new P1 inside that fix:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/large-review-dark.svg">
  <img alt="A large review: preflight freezes the roster; discovery runs simplicity, risk and full red-team panels of four seats each; triage, a one-seat plan panel, fix and gates, then a four-bundle verification; a second fix cycle repeats plan, fix and verification; the run seals its receipt, pushes and publishes one PR review. 22 seat launches." src="docs/assets/large-review-light.svg" width="100%">
</picture>

Each code panel seals its receipt before the next edit; plan panels are verified but never
receipted. Had r4 found only a P3 or a one-line P2, the project gates alone would cover it and
the run would end at 17 launches. Codex pushes at the end only when you authorize it.

<details>
<summary><b>Phases and when they run</b></summary>

<br>

| Phase | Runs when | Covers |
| --- | --- | --- |
| simplicity discovery | always | every core seat asks whether the change can be smaller through reuse or deletion |
| risk discovery | more than 25 files, more than 1,500 lines, or a high-risk boundary | the four risk bundles across the panel |
| full red team | once, for a large, high-risk, user-marked-important or explicitly adversarial review | four adversarial compositions over the risk bundles, with sibling-site completeness, before planning |
| plan | after triage and before any edit, when an accepted fix is nontrivial | one plan-completeness seat; `plan_seats: "all"` adds soundness, simplicity and falsifiable-test seats |
| fix and gates | after the plan passes, or a recorded plan skip | root-cause clusters, red-first regression tests, project gates at baseline or better |
| verification | after discovery when no fix follows, otherwise after the latest fixes | all four risk bundles over the latest material state, plus a sibling-site check of every fix commit |

High-risk boundaries are security, persistence, concurrency, transactions, protocols, public
APIs and irreversible mutations. The host applies these thresholds when it plans the review;
no script enforces them.

</details>

<details>
<summary><b>Seat launch budget</b></summary>

<br>

For the four-seat council:

| Change shape | Planned seat launches |
| --- | ---: |
| ordinary, no nontrivial fix | 8 |
| ordinary, with one plan panel | 9 |
| large or high-risk, no fix, current enforced combined receipt | 12 |
| large or high-risk, no fix, combined receipt ineligible | 16 |
| large or high-risk, with one plan panel | 17 |
| important or adversarial, no fix, current enforced combined receipt | 8 |
| important or adversarial, no fix, combined receipt ineligible | 12 |
| important or adversarial, with one plan panel | 13 |

Launch counts, not measured cost; `plan_seats: "all"` makes each plan panel four launches.
When no fix follows, the red team's sealed receipt can stand as verification while it still
covers the unchanged state.

One four-bundle verification panel reviews the latest material state: the current combined
panel when no fix follows, a separate panel after simplicity-only discovery, or a fresh panel
after fixes. Reuse needs `rev-evidence.py current-coverage` to report the receipt eligible,
both before skipping a panel and just before completing.

Adaptive default panels use core seats and omit extras. Explicit numeric round plans may
include extras in their configured rounds.

Another plan and verification cycle starts only for a new P0/P1 root cause, an open P0/P1, or
another nontrivial fix; a P3 or one-line P2 needs only the project gates.

</details>

<details>
<summary><b>Review bundles and red-team emphasis</b></summary>

<br>

| Bundle | Asks about |
| --- | --- |
| `correctness-boundaries` | logic, edge cases, errors, input and output boundaries |
| `security-state-api` | trust boundaries, durable state, compatibility, public contracts |
| `concurrency-resources-performance` | races, cancellation, ownership, cleanup, limits, hot paths |
| `tests-observability-maintenance-regression` | meaningful tests, failure visibility, maintainability, cumulative regressions |

Every risk and verification panel covers all four, one per seat (with three seats, one seat
takes two), and the regression seat also reads the whole cumulative change. Each code panel
gives one seat, rotating, a red-team emphasis at no extra call; the full red-team panel pairs
the bundles with attacker, rollback, exhaustion and compatibility emphases.

</details>

<details>
<summary><b>Simplicity first</b></summary>

<br>

Every core seat looks for:

- an existing framework, engine or repository mechanism that replaces new machinery;
- a workaround whose stated dependency limitation no longer exists;
- a parameter every caller passes identically;
- a generic or test axis with only one implementation or value;
- an unreleased migration that can fold into the schema it changes;
- a public surface that does not follow the repository's export convention;
- scope larger than the named consumer requires.

A reuse finding must name the existing symbol, its location and version; scope cuts stay the
author's call. On eight held-out PRs, four simplicity seats found 6 of 10 load-bearing
simplifications, where earlier single-seat runs found about half. Swapping in a `clean-room`
design seat, or showing seats the author's PR description, lowered recall, so both are opt-in
([evaluation](docs/simplicity-lens-eval-2026-09-06.md)).

</details>

<details>
<summary><b>Plan gate</b></summary>

<br>

Accepted findings are grouped by root cause into clusters in `fix-plan.md` before anything is
edited. Preparation parses each cluster, so the fields are fixed:

```markdown
## C-03 · re-check hold ownership after every parking await
Findings:   F-012 (P1), F-019 (P2)
Rule:       every call after an await that can park re-checks that it still owns the hold
Sites:      src/sync/trigger.ts:141, :208; src/workers/sync.ts:60
            (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'await .*lock' .)
Excluded:   src/workers/index.ts - re-exports only, never awaits the hold
Must not:   change the eviction timing
Test:       sync-lock.test.ts - evict mid-await, assert the late call is dropped
Prediction: reverting the guard fails sync-lock.test.ts at "drops the late call"
```

`Findings`, `Rule`, `Sites`, `Prediction` and a `Test`, `Tests` or `Regression` field are
required, and every path must resolve in the frozen snapshot. The `found by` search must use
exactly that `rg` form or `grep --exclude-dir=.git --null -r -n -- 'PATTERN' .`; it is
replayed once on the frozen tree and must return 1-80 records, each a named site, a
test-field path, or an `Excluded: <path> - <reason>` entry. Patterns are capped at 1024 bytes
and output at 32 KiB; anything else fails closed.

One plan-completeness seat (the first core seat not on the Agent adapter, when there is one)
reviews the full patch and every cluster. `plan_seats: "all"` adds a specialist per cluster,
whose first read must be its one assigned artifact; any listing or search before it
invalidates the attempt. A failed plan seat gets one `<N>px` replacement; if that fails too,
the plan stays incomplete.

`rev-state.sh` refuses `phase=fix` while P0-P2 findings are open until the plan panel
completes or `findings.md` records `Plan panel r<N>p - SKIPPED: <reason>`. When tests change,
prompts add a vacuity check: an assertion no production change would break is a P1.

</details>

<details>
<summary><b>Severity levels, triage and convergence</b></summary>

<br>

Every claim is opened at its cited location and followed through the control flow before it
is accepted.

| Level | Meaning | Examples |
| --- | --- | --- |
| P0 | incorrect behaviour, security hole, data loss or crash | authorization bypass, destructive state corruption |
| P1 | reachable bug, edge case or broken contract | duplicate side effect, missing retry boundary, incompatible API behaviour |
| P2 | maintainability, performance, missing test or unclear API | avoidable hot-path cost, untested failure branch |
| P3 | trivial style, naming or comment issue | stale harmless comment, naming nit |

Each finding ends `OPEN`, `FIXED`, `REJECTED (reason)` or `DEFERRED (reason)`. Duplicates merge
by root cause, and rejections carry a source-backed reason so later panels do not resurface
them. P3s are fixed only inside a cluster, when trivial; correct but out-of-scope findings are
deferred.

**Fixing**, cluster by cluster and P0 first: apply one rule at every listed site; run the
predicted test red first (a different failure stops the fix); keep unrelated user changes;
run the repository's full gate list, not the subset the diff suggests, back to baseline or
better; run `rev-mutate.sh` against the prediction; and commit the cluster on its own.

**Completion:** the latest four-bundle verification is valid, no P0/P1 is new or open,
nothing material is unreviewed, gates are at or better than baseline, and the final receipt
seals. P2s gate the fix phase through the plan gate, never completion.

**Review-origin breaker:** at each `phase=fix` it counts findings on lines the review itself
changed; two receipted rounds with any since your last acknowledgement stop the run until you
decide.

**Numeric mode:** a round count is a minimum on the legacy schedule. The run continues while
the last numbered panel found a new P0/P1 or needed nontrivial fixes, a P0/P1 is open, or a
lens or major file is unreviewed, and stops after two consecutive clean numbered code panels
with gates at or better than baseline. Plan panels do not count.

**Read-only code reviews** run setup and baseline gates, fan out, triage and publish the PR
review, then stop before any fix, commit or push.

</details>

<details>
<summary><b>Legacy numeric schedule</b></summary>

<br>

| Round | Emphasis | Lenses | Extra |
| ---: | --- | --- | --- |
| 1 | reduce the change | simplicity on every core seat | - |
| 2 | logic and boundaries | correctness, edge cases, error handling | - |
| 3 | security and state | security, data state | `codex-review` |
| 4 | concurrency and resources | concurrency, resources, performance | - |
| 5 | contracts and compatibility | API contract, readability, plus data state (Claude Code) or maintainability (Codex) | - |
| 6 | verification | tests, observability | - |
| 7 | adversarial challenge | red team | - |
| 8 | cumulative reread | regression | - |
| 9+ | remaining gaps | uncovered or unresolved lenses | - |

</details>

## Configure

Out of the box, with no config file, the roster is built from whatever is installed and
signed in:

| Seat | Model | Effort | Seated when |
| --- | --- | --- | --- |
| `codex-sol` | newest Sol | `xhigh` | Codex CLI signed in |
| `codex-luna` | newest Luna | `xhigh` | Codex CLI signed in |
| `opus` | Opus | `xhigh` | Claude CLI signed in, or Claude Code Agent seats |
| `gemini` | `gemini-2.5-pro` | default | Gemini CLI installed and signed in |

Sol and Luna resolve once per run and freeze to exact slugs before probing. The
`codex-review` extra is available to explicit numeric schedules.

**The four-seat council.** For two OpenAI and two Anthropic seats, and a run that refuses to
start without them, create `~/.config/review-council/config.json`:

```json
{
  "exclude": ["gemini"],
  "codex_models": ["latest-sol", "latest-luna"],
  "codex_effort": "xhigh",
  "claude_models": ["opus", "sonnet"],
  "extras": false,
  "min_labs": 2,
  "quota_fallback": true
}
```

- The newest visible Sol and Luna must support `xhigh` and pass their probes.
- Opus and Sonnet must both be seated at `xhigh`; Claude CLI seats must pass their probes.
- Gemini and the `codex-review` extra are left out.
- At least two provider labs must be available before ordinary execution.
- A quota or capacity failure may temporarily swap in a substitute seat, visibly.

> [!NOTE]
> Without `codex_models` selectors or `codex_effort` in the config, a Sol or Luna that cannot
> be resolved (missing from the catalog, or a model cache written by another Codex version)
> drops the Codex lab, and the panel is padded and marked degraded. With either set, the run
> stops instead and names the problem.

Every key and environment variable is under [Reference](#reference), and in full in
[docs/config.md](docs/config.md).

<details>
<summary><b>Roster, probing and padding</b></summary>

<br>

`roster.json` records each seat's name, lab, adapter, exact model and effort, and whether it
is core, extra or padded, plus exclusions, degradation, refusal class and quota substitutions;
[docs/seats.md](docs/seats.md) has the adapter contract. Detection checks binaries, sign-in
and the model cache, then preflight probes each unique CLI model and effort (Agent seats are
not probed). The Codex catalog counts only when its `client_version` matches
`codex --version`; a mismatch is refreshed once with `codex debug models`, and if it persists
the Codex lab is dropped, or, with `codex_models` selectors or `codex_effort` configured, the
run exits 5.

A roster of fewer than three seats is padded to three and marked degraded. Padded seats get
their own lenses but never count as a lab, and `min_labs` makes lab diversity a hard floor.
Claude Code pads with Opus on the resolved adapter (Agent seats when the CLI is unusable or its
probe failed); Codex pads only from surviving CLI seats and refuses when none remain.

</details>

<details>
<summary><b>Quota fallback</b></summary>

<br>

Off by default; enable it with `{ "quota_fallback": true }`.

| Blocked provider | Temporary substitute |
| --- | --- |
| Anthropic quota or capacity | a uniquely named seat of the selected Luna, or of Terra (another OpenAI family) when one is seated |
| OpenAI quota or capacity | a uniquely named Sonnet seat, when a probed Sonnet CLI seat is in the roster |

Only provider-reported quota or capacity qualifies (for Agent seats, platform metadata, never
reviewer prose); authentication, configuration and unknown errors never substitute.
Substitutes record `substitutes_for`, and `min_labs` is waived only when they cover the whole
shortfall. The fallback restarts the panel once, in a fresh sibling session over the same
frozen source, inheriting the review-origin window; a substitute that also hits quota stops
it. Configuration is never edited, so the next review tries the preferred roster again.

</details>

<details>
<summary><b>Claude Code and Codex differences</b></summary>

<br>

| Behaviour | Claude Code | Codex |
| --- | --- | --- |
| Anthropic seats | signed-in Claude CLI, else built-in Agent seats (`claude_adapter`) | signed-in Claude CLI |
| OpenAI seats | Codex CLI | Codex CLI |
| thin roster padding | Opus on the resolved Claude adapter | surviving external CLI seats |
| no usable external CLI | a visibly degraded Agent panel | refuses |
| another branch or a PR | checked out in the current checkout | reviewed in an isolated worktree |
| push after the loop | once, automatically | only when authorized |
| session startup policy | plugin hook | native skill discovery |
| stop guard while a review is open | `Stop` hook | none |
| stack leg | `claude -p` | `codex exec` |
| stack finishing default | push and publish, unsquashed | local and unsquashed |

Both hosts share the roster, evidence compiler, schema, adapters, ledgers, status, profiling
and receipts.

</details>

## Evidence and receipts

A plausible answer is not a review. A seat's result counts only when it is bound to the
frozen source, proves it read every byte of the change it was assigned, cites only ranges it
actually read, and validates against the shared schema. A panel counts only when one valid
result covers every assignment. A run missing any audit, receipt or final report its mode
requires is incomplete and cannot be described as a Review Council review.

> [!IMPORTANT]
> A receipt proves the review contract ran over the named bytes. It does not make a finding
> true. Triage still checks every claim against source.

<details>
<summary><b>Preflight and frozen scope</b></summary>

<br>

Preflight runs before any reviewer launch. It resolves root, base, head and changed paths;
refuses an empty scope, an unresolvable base, an active review, a non-Git directory or `HEAD`
on a shared branch; writes `scope.env`, `files.txt`, `untracked.txt` and `roster.json`; probes
the roster (a small paid call per CLI seat); and replays preserved provider envelopes when
self-host boundaries changed. The host then records the baseline patch and existing gate
failures.

The base is the first of: `--base`, `$REV_BASE_REF`, the open PR's base, the nearest fork
point among the default branch, `next`, `develop`, `dev` and `release`, then `origin/HEAD` or a
local `main` or `master`. Every later artifact binds that frozen identity, and an initialized
session resumes without rerunning preflight.

</details>

<details>
<summary><b>Evidence compiler</b></summary>

<br>

Adaptive code and plan panels read a deterministic packet that `rev-evidence.py` builds from
the frozen scope, not the whole repository. Changed code is grouped into dependency
components, each read by a specialist and by the integration seat, which sees the whole
cumulative change. A component with a prior finding returns to that finding's seat, and after
a valid receipt specialists see only the delta since. Lockfiles, generated output, snapshots
and locale copies go to the integration seat alone. Without proof of complete coverage, every
seat gets the full patch.

Source packets hold exact bytes of enclosing declarations, callers, local imports, related
tests and configuration gates, in 16 KiB shards: one per specialist, up to three for the
integration and plan seats. Oversized ranges become ordered artifacts of at most 240 lines.
Every read obligation is checked against the adapter's capacity before launch, so a contract
that cannot fit fails early, and prompts over 1,800 words (code) or 3,000 (plans) warn
instead of truncating.

| Patch delivery | Used when | Limits |
| --- | --- | --- |
| bounded windows | the patch is empty, has NUL bytes or invalid UTF-8, chunks are disabled or unrepresentable, or chunks save under 10% of reads | 240 lines per window |
| ordered chunks | a safe UTF-8 patch where chunks save at least 10% of reads, or capacity requires them | 24 KiB raw, 30 KiB rendered and 1,000 displayed lines per chunk |

Chunks reconstruct the canonical patch byte for byte and must be read in order; they prove
the change was read, never a citation. `REV_PATCH_CHUNKS` is `auto`; `1` forces chunks and
`0` forces windows.

</details>

<details>
<summary><b>Reviewer read contract</b></summary>

<br>

The audit requires the exact manifest and prompt hashes, a supported transcript with at least
one review tool call, complete patch, packet and required-source reads, repository expansion
inside scope (at most 16 calls), every citation inside an audited range, and schema-valid
JSON. Claude CLI seats get only `Read` and `Grep` behind bounded hooks, with no inherited
settings, plugins or MCP configuration, and may batch two proof reads per turn under 60 KiB.

Agent-adapter seats run evidence mode but cannot be enforced, so a panel holding one lists
them in `unenforced_seats` and is never certified. `REV_UNENFORCED_AUDIT=1` adds an advisory
audit of those seats; nothing gates on it.

</details>

<details>
<summary><b>Result validation and seat recovery</b></summary>

<br>

A result counts only when its process terminated, its `.exit` receipt is written, its JSON
validates against `findings.schema.json`, it matches an immutable prompt generation, its read
audit passes, and the panel receipt selects it. Transport failures (unknown stream shapes,
zero-tool answers, missing or malformed output, stale or mismatched hashes) never certify;
read order, call counts and duplicate reads are advisories. A seat generation gets at most
four provider calls.

| Failure | Recovery |
| --- | --- |
| exit 1 or 2, with no invalid read audit | retry only that seat, once, with the exact prompt, assignment, model and effort |
| hard read-audit failure | keep every artifact, never relaunch under that label, and replace the assignment once on another enforced seat (`<N>x`, or a one-seat `<N>px` plan panel) |
| a seat still failing after its retry | replace the assignment once on another enforced seat |
| no eligible seat, a second failure in the panel, or a failed replacement | leave the panel incomplete and ask the user |
| receipt failure | diagnose the provenance or contract defect and end the run |

A hard audit failure ends only that seat's assignment; siblings keep running and keep their
results. Fixes wait until the receipt seals. Exit codes are under [Reference](#reference).

</details>

<details>
<summary><b>Security boundaries</b></summary>

<br>

- Codex seats run in the read-only sandbox, Gemini seats in plan mode, and Claude CLI seats
  with only audited `Read` and `Grep`; prompts cannot grant editing, execution, publication or
  credential access.
- Evidence search accepts one documented repository-root form and treats pattern and paths as
  data, and every provider call is bounded in time and output.
- Session evidence lives outside the reviewed source; verifier reads reject symlink traversal
  and recheck source identity around use.
- Plugin installs are atomic, so a failed replacement keeps the live plugin.
- `REV_ACTIVE=1` blocks nested reviews and `REV_STACK_LEG=1` nested stacks.
- Reviewers never execute findings; the host verifies each claim before changing code.

</details>

## Status and reports

`scripts/rev-status.sh <session-dir>` prints one status line from session files, without
contacting a provider. During a run the host relays one every ten minutes:

```text
r3/adaptive triage | sol: done 4f 9m | codex-luna: running 14m ← rg "retry" src/api | opus: done 3f 8m | sonnet: done 2f 7m | open P0:0 P1:1 P2:3 fixed 6
```

Each seat is `pending`, `running` with its last action, `done` with finding count and time,
`failed exit=<code>`, or `dropped`; the line is capped at 220 characters and ends `+N seats`
when seats are cut. `scripts/rev-context.py <session-dir>` gives a compact briefing for a
resumed session; with `--watch` it emits at start, on each change and at ten-minute ticks.
Sessions live outside the reviewed tree, normally at `/tmp/rev-<epoch>`.

<details>
<summary><b>Completion report</b></summary>

<br>

On Claude Code, `report.md` opens with the outcome (prefixed `Degraded panel:` and the exact
reason when the roster is degraded), then a findings table by severity, rejected findings with
reasons, coverage (rounds, seats and efforts, lenses, final gate status, dropped seats), one
line per fix commit and the push, and the residual risk that deserves human attention. Codex
writes scope and base, roster and degradation, rounds and lenses, findings with evidence,
commits, baseline and final gates, and remaining limitations. Late P0s are stated plainly.

Codex writes `incomplete.md` for an interrupted or blocked run. On either host, a failed
publication writes `incomplete.md` with the command that retries it.

</details>

<details>
<summary><b>PR review publication</b></summary>

<br>

A completed code review of a branch with an open PR, read-only or not, posts one
deterministic review (badge, verdict, counts, decisions, fixes, verified-sound, coverage,
footer) as a `COMMENT` pinned to the reviewed commit. Its inputs are frozen for exact
retries, base-tip movement is accepted only while the merge base holds, and an identical
review on that commit is never posted twice.

Branches without an open PR and document reviews do not post, and `NO_PUSH=1` renders without
calling GitHub. With an open PR, rendering refuses a session directory inside the repository
or a dirty tree, and an unrelated pending review of yours blocks posting. A stack publishes
only the latest completed session per repository. Details:
[pr-review.md](plugins/review-council/docs/pr-review.md).

</details>

<details>
<summary><b>Profiling and cost benchmarks</b></summary>

<br>

```bash
python3 plugins/review-council/scripts/rev-profile.py /tmp/rev-<epoch>
```

It separates completed, metered and unmetered calls, token categories, known and unknown
cost, prompt and scope words, patch-proof reads and finding yield, and marks a mixed roster as
a measurement boundary ([cost accounting](docs/cost-accounting.md)).
[Reusable benchmarks](eval/COST_BENCHMARKS.md) compare frozen plugin versions:

| Study | Result |
| --- | --- |
| [wave 1](docs/cost-benchmark-wave1-2026-09-29.md) | 6.8% fewer estimated credits and 14.7% less provider time over 4 live runs, both finding 4/4 defects |
| [wave 2](docs/cost-benchmark-wave2-2026-09-30.md) | compact startup: 12.0% fewer credits and 14.4% less time on two canaries, recall 4/4; shipped |
| [wave 3](docs/cost-benchmark-wave3-2026-09-30.md) | lean packets plus decision digests: 1.0% more credits and 25.4% more time; discarded |
| [wave 4](docs/cost-benchmark-wave4-2026-09-30.md) | packet-only: 24.6% fewer credits but lower quality scores; discarded |
| [screening](docs/cost-benchmark-screening-2026-09-30.md) | every later candidate failed the fixed quality gates |

</details>

## Stack reviews

When one change spans dependent repositories, `/review-council:stack <config>` runs a review
leg per repository in dependency order, optionally reviews the seam between them, and
publishes per repository. Start from
[the config template](plugins/review-council/scripts/stack.example.sh).

<details>
<summary><b>How the stack runner works</b></summary>

<br>

1. It detaches by default (`REV_STACK_FOREGROUND=1` stays attached), logging to
   `/tmp/review-council-stack.log`.
2. Each repository runs as an isolated leg, `PASSES` times (default 2), in dependency order.
3. Stalls are detected from log activity and process CPU (`STALL_SECS=1800`,
   `MAX_ATTEMPTS=4`), and a retried leg resumes its own session.
4. With `SEAM_REPO` set, a two-round seam leg reviews the boundary, then an optional
   completeness critic runs.
5. Each successful repository publishes even if a sibling fails; the run then ends
   `COMPLETE WITH FAILURES` with exit 1.

Claude Code legs run `claude -p`; Codex legs run `codex exec` with workspace-write, reviewer
network access and the session root writable. Legs never launch another stack. Claude Code
defaults to `NO_PUSH=0` and pushes and publishes; Codex defaults to `NO_PUSH=1`. Both default
to `NO_SQUASH=1`, so review commits stay one per fix on both hosts. A real push needs an
upstream of the same branch name.

</details>

## Reference

<details>
<summary><b>Every config key</b></summary>

<br>

| Key | Default | Purpose |
| --- | --- | --- |
| `exclude` | `[]` | drop detected labs or seats, e.g. `["gemini"]` |
| `pin` | `{}` | override a detected seat's model or effort |
| `codex_models` | absent: newest Sol and Luna | require one or two exact slugs or `latest-<family>` selectors |
| `codex_effort` | absent: `xhigh` | require one effort (`max`, `xhigh` or `high`) on every OpenAI seat |
| `claude_models` | absent | require exact `opus` and/or `sonnet` seats |
| `claude_seats` | `1` | legacy count of Opus seats; mutually exclusive with `claude_models` |
| `claude_seat` | `true` | `false` disables detected Claude seats |
| `claude_adapter` | `auto` | Claude Code runs Anthropic seats on the CLI (`cli`), as Agent subagents (`agent`), or on the CLI when signed in (`auto`) |
| `plan_seats` | `completeness` | one plan-completeness seat per plan panel, or `all` for the four-lens plan panel |
| `extras` | `true` | expose `codex-review` to explicit numeric schedules |
| `min_labs` | `1` | minimum detected provider labs before padding |
| `quota_fallback` | `false` | allow temporary cross-provider quota substitution |
| `check_updates` | `false` | print an available-update line in Claude Code |

The path is `${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}`. An
environment variable overrides its config key where one exists. Every key and its exit
codes: [docs/config.md](docs/config.md).

</details>

<details>
<summary><b>Environment variables</b></summary>

<br>

| Variable | Default | Purpose |
| --- | --- | --- |
| `REV_BASE_REF` | unset | the environment form of `--base` |
| `REV_PATCH_CHUNKS` | `auto` | automatic, forced (`1`) or disabled (`0`) exact patch chunks |
| `REV_SOURCE_CONTEXT` | `1` in the skills, `0` in the script | literal source packets and required-source segments; `0` is for labeled baseline measurement |
| `REV_UNENFORCED_AUDIT` | unset | `1` runs, and caches, the advisory read audit of Agent seats |
| `REV_PLAN_SEARCH_TIMEOUT` | `30` | seconds shared by all plan sibling-site searches, at most 300 |
| `REV_RG` | `rg` on PATH | the ripgrep that replays plan searches |
| `REV_CODEX_SOURCE_BATCH` | `0` | retired Codex source-window batching; only `0` is accepted |
| `REVIEW_COUNCIL_CLAUDE_ADAPTER` | unset | the environment form of `claude_adapter` |
| `REVIEW_COUNCIL_CLAUDE_SEAT` | unset | `0` disables detected Claude seats |
| `REVIEW_COUNCIL_CODEX_MODELS_CACHE` | shared cache | pin a Codex catalog and skip its version check |
| `REVIEW_COUNCIL_GEMINI_MODEL` | `gemini-2.5-pro` | the Gemini seat's model |
| `REVIEW_COUNCIL_LOGIN_TIMEOUT` | 20 s | bound on each sign-in check |
| `REVIEW_COUNCIL_PROBE_TIMEOUT` | 60 s | bound on each live probe |
| `REVIEW_COUNCIL_CODEX_VERSION_TIMEOUT` | 5 s | bound on `codex --version` for the catalog check |
| `REVIEW_COUNCIL_CATALOG_REFRESH_TIMEOUT` | 30 s | bound on one `codex debug models` refresh |
| `REVIEW_COUNCIL_PROVIDER_OUTPUT_BYTES` | 1 MiB | provider status and probe output cap |

Installer, update-check and contract-check variables are in [docs/config.md](docs/config.md).

</details>

<details>
<summary><b>Exit codes and fail-closed conditions</b></summary>

<br>

Seat runs (`rev-seat.sh`) return 0-4 and 7; roster builds and preflight return 5 and 6.

| Exit | Class | Meaning | Action |
| ---: | --- | --- | --- |
| 0 | success | valid findings result | audit and retain |
| 1 | seat-local | retryable provider or adapter failure | exact retry once when no invalid audit exists |
| 2 | seat-local | missing or invalid findings JSON; also a hard audit failure, or a refused relaunch under a failed label | exact retry once when no invalid audit exists; otherwise replace the assignment |
| 3 | provider-global | not signed in | stop and name the required sign-in |
| 4 | provider-global | quota, rate or capacity | stop, or use explicit quota fallback |
| 5 | roster availability | possible roster not currently available | keep the session and retry when availability changes |
| 6 | roster configuration | malformed or impossible exact configuration | fix the configuration first |
| 7 | local attempt budget | the seat generation used all four calls | stop the panel without substitution or replacement; keep valid siblings; never quota |

The run also fails closed when the source changed after freeze; on a prompt, manifest,
transcript or result hash mismatch; on incomplete patch, packet, segment, search or citation
proof; on a provider stream shape the auditor does not support; when a plan task exceeds
compiled capacity; when a project gate falls below baseline; and when a stack leg exits
without a fresh `stack-report.md` and `phase=stack-ready`.

</details>

<details>
<summary><b>Session artifacts and receipts</b></summary>

<br>

| Kind | Files |
| --- | --- |
| scope and roster | `scope.env`, `files.txt`, `untracked.txt`, `roster.json`, `00-baseline.patch`, `baseline.md`, optional `baseline.json`, `docs.txt` for document reviews |
| ledger and state | `findings.md`, `rejected.md`, `fix-plan.md`, `context.md`, `state.json`, `coverage-head.json` |
| per panel | `r<label>-evidence.manifest.json`, evidence packets and patches, `r<label>-panel.tsv`, `r<label>-coverage.receipt.json` |
| per seat | `.prompt.md`, `.stream.ndjson`, `.log`, `.json`, `.exit`, `.read-audit.json`, and `.audit-invalid.json` only after a hard audit failure |
| attempts and contracts | `attempts/<sha>.json`, `contract-pass-<sha>.json` |
| publication and outcome | `pr-review.json`, `pr-review.md`, `pr-review-target.json`, `stack-report.md`, `report.md`, `incomplete.md` |

| Receipt | Proves |
| --- | --- |
| provider contract | the current adapter and auditor accept preserved provider envelopes for the exact provider boundary and CLI versions |
| exit | the seat generation's terminal exit code; only `0` is success |
| read audit | the transcript met its hash-bound evidence obligations |
| panel | one immutable valid generation covers every assignment |
| `stack-report.md` | a stack leg completed locally and is ready to finish and publish |
| `report.md` | publication succeeded or cleanly skipped, and the review completed |

Current-session completion and finding yield require a schema-valid result with a successful
exit receipt. Only exact hashed receiptless results recorded in a versioned legacy roster
policy may omit one.

</details>

<details>
<summary><b>Claude Code hooks</b></summary>

<br>

The Claude Code plugin installs two hooks; Codex installs neither.

**Session hook** (`startup`, `clear`, `compact`): injects the review policy and the roster
summary and, with `check_updates: true`, reports an available update (cached for a day,
bounded to 3 s, never self-replacing). It makes no model call.

**Stop hook:** a review is a queue, and the recurring failure is ending a turn on a status
summary while items remain. The hook blocks a stop while the newest review in the current
working tree is unfinished, naming its round, phase and open findings. It allows the stop once
the session is `done`, `stack-ready` or `blocked`, has a report or `incomplete.md`, or is
genuinely waiting on seats with everything triaged and the tree clean.

It errs toward allowing (no session, state untouched for 6 hours, unreadable state, no
`python3`) and releases after three consecutive blocks, but an unreadable `scope.env` still
blocks. Only `/tmp/rev-*` sessions owned by you whose `REV_ROOT` matches the tree count, so
stack legs are not guarded. `REVIEW_COUNCIL_STATE_DIR` and `REVIEW_COUNCIL_SESSION_ROOTS`
override its paths.

</details>

<details>
<summary><b>Limitations</b></summary>

<br>

- Probes and reviewer calls consume provider usage; a multi-repository stack can consume a lot.
- Exact rosters need installed, signed-in CLIs and a Codex model cache matching the `codex`
  binary.
- Quota fallback covers quota and capacity only, and an OpenAI outage can fall back only to a
  probed Sonnet CLI seat.
- A panel with an Agent-adapter seat is never certified.
- Numeric code reviews and document reviews keep full scope and carry no evidence receipt.
- Chunk reads prove the change was read; they do not replace source reads for a finding.
- Publication cannot find a PR whose head branch lives on a fork and skips it as if there
  were none; post the rendered `pr-review.md` by hand.
- The Gemini adapter is fixture-tested, not certified on a live Gemini CLI.
- Sandboxes that restrict nested CLIs or gates fail visibly and never widen permissions.

</details>

<details>
<summary><b>Development and release</b></summary>

<br>

```bash
plugins/review-council/tests/run-tests.sh roster      # name-filtered shell tests
plugins/review-council/tests/run-tests.sh             # full shell suite
python3 -m unittest discover -s tests -v              # Python suite
python3 scripts/verify-review-council.py --root .     # unified release gate
```

The release gate freezes one tree, reconciles the test inventory, runs both suites,
`claude plugin validate --strict` and the Codex marketplace check, and writes a hash-bound
receipt only when every stage saw the same tree (needs the `claude` CLI; `--timeout 1800`,
four workers). Tests use local CLI shims and never contact providers.

`python3 scripts/install-codex-plugin.py` builds the Codex bundle into
`~/plugins/review-council` and registers it in your personal marketplace, atomically;
`scripts/build-codex-plugin.py --output dist/review-council` only builds it for inspection.
Each release is reviewed by the previous signed release; see
[the release procedure](docs/release.md).

</details>

## License

[MIT](LICENSE)
