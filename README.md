# review-council

A Claude Code plugin, now also available for Codex, that runs your code review through a panel instead of one model: Codex, Grok, Gemini and an Opus subagent each read the same diff independently, in read-only mode, and answer in a shared findings schema. The orchestrating Claude session merges their claims into a ledger, verifies every one against the source before acting on it, fixes what's real, re-runs your gates, and commits - round after round until the panel stops finding anything new. The panel is never hardcoded: at the start of every session the plugin checks which lab CLIs are actually installed and signed in on your machine, builds the seat roster from that (and probes each seat with a one-token call before a review starts), so the review always runs with whatever frontier models you have. A panel is three seats; by default, a short machine roster is padded with extra Claude seats, each on its own lens, and every visible status names the lost diversity. Strict lab floors and explicit positive model or seat counts refuse before padding when exact coverage is required.

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

The one-liner also turns on auto-update for the marketplace it just added (Claude Code leaves auto-update off for third-party marketplaces, so a plugin installed from one never moves on its own). It is the only thing the installer writes outside Claude Code's own install: one `autoUpdate` flag under `extraKnownMarketplaces.review-council` in `~/.claude/settings.json`. The file is rewritten atomically (tmp file, then rename) at 2-space indent with every other setting preserved, keeping its existing mode - a `600` settings file stays `600`, and one created from scratch starts there - following a symlink rather than replacing it, and leaving anything it cannot parse untouched. Skip it with `--no-auto-update`:

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install.sh | bash -s -- --no-auto-update
```

Update by hand any time with `claude plugin update review-council`; restart Claude Code (or `/reload-plugins`) after installing or updating. If you would rather be told than updated, set `check_updates: true` in the config and the session banner adds one line when a newer version is published (off by default, checked at most once a day, silent when the network is unreachable) - see [docs/config.md](docs/config.md).

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

Start a new Codex chat, then ask “Use review-council to review this branch.” The
plugin includes native `rev` and `stack` skills and uses the provider CLIs installed
and signed in on your machine. Codex requires its CLI with plugin support, Python 3,
and Bash. See [Codex setup and behavior](docs/codex.md) for updates and local development.

The remaining instructions below describe Claude Code. The Codex skills retain the
review loop and findings format, with CLI-based Anthropic seats and Codex stack legs.

## At session start

A `SessionStart` hook runs on `startup`, `clear` and `compact`. It does two cheap things - no model calls, under a second - and one optional third:

1. Injects the standing review policy (`skills/rev/POLICY.md`): use `/review-council:rev` for review requests, reviewers never edit, apply actionable findings after a review, relay the round-status line, never substitute your own reading for the panel's.
2. Injects one roster line from `scripts/roster.sh --brief`, e.g.:

   ```
   review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@max) · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max)
   ```

With `check_updates: true` in the config it adds a third line, and only when there is something to say:

   ```
   review-council 0.2.0 available: claude plugin update review-council
   ```

If roster detection itself fails, the line says `review-council seats: roster unavailable (<reason>)` and the hook still exits 0 - a broken roster never blocks a session from starting. The update check is held to the same bar and then some: it is off unless you turn it on, it asks the network at most once a day, it is capped at three seconds, and any failure means no line rather than a delay. The hook never updates the plugin itself - a plugin's own hook replacing the directory it is running from is how an install gets corrupted - so all it ever does is name the command.

## `/review-council:rev`

```
/review-council:rev [scope] [rounds] [--read-only] [--base <ref>]
```

`scope` is `branch` (default), `uncommitted`, a path, a PR number/URL, or a branch name; `rounds` is an optional minimum that selects the legacy numbered schedule instead of the adaptive default; `--read-only` reports findings without fixing or committing, for plans and docs as well as code; `--base` names the branch the change was cut from when the guess is wrong (the guess is the open PR's base, else the nearest fork point among `main`, `next`, `develop`, else `origin/HEAD`).

The loop uses four adaptive phases:

1. **Discover** - every seat reviews simplicity; large or high-risk changes get one additional full risk panel.
2. **Triage and plan** - claims are verified, deduplicated by root cause, and nontrivial fixes receive one full plan review before editing.
3. **Fix and verify** - accepted findings are fixed by cluster and gates are re-run. One four-bundle verification panel reviews the latest material state: directly after discovery when no nontrivial fix follows, or after the latest nontrivial fix.
4. **Continue only when needed** - a new or open P0/P1 or another nontrivial fix starts another plan and verification cycle. A P3 or one-line P2 follow-up needs the project gates; every other fix needs the full panel.

With four core seats, a normal review plans 12 seat launches: four simplicity, four conditional plan, and four final verification launches. A large or high-risk review plans 16 by adding four risk-discovery launches. Adaptive completion requires valid results for all four verification bundles, no new or open P0/P1, no material unreviewed change, and gates at or above baseline. At the end it squashes the review commits, pushes once, and writes `report.md`.

### Adaptive panel plan

Every core seat reviews simplicity first. Large means more than 25 changed files or more than 1,500 changed lines. High-risk means the change crosses a security, persistence, concurrency, transaction, or public API boundary.

| Panel | When | Lenses |
|---|---|---|
| Simplicity discovery | always | simplicity on every seat |
| Risk discovery | large or high-risk only | correctness and boundaries; security, state, and APIs; concurrency, resources, and performance; tests, observability, maintenance, and regression |
| Plan | accepted nontrivial fixes | completeness, soundness, simplicity, and falsifiable tests |
| Verification | after discovery or the latest nontrivial fix | the four risk bundles, rotated |

Adaptive default panels use core seats and omit extras. Explicit numeric round plans may include extras in their configured rounds. Reviewer prompts carry concise baseline and decision context, never the cumulative findings ledger. Native structured-output adapters receive the schema out of band; rendered Agent and Gemini prompts include it once. The session profiler reports completed calls, metered and unmetered coverage, processed tokens, prompt words, and provider cost after each panel. Current sessions require a schema-valid result and a successful exit receipt for completion and finding yield. A valid versioned roster policy preserves only exact, hashed receiptless results from older sessions. Missing receipt metadata in a valid historical roster remains compatible, while present invalid roster or receipt metadata fails closed. Usage-bearing failed attempts remain metered.

Adaptive code panels prepare a hashed snapshot, semantic dependency components, and
a deterministic navigation index. One integration seat receives the full cumulative
patch and all mechanical files. Specialists receive component patches, with later
fixes routed back to the seat that found the issue. Every seat must prove it read every
assigned patch byte. Large UTF-8 patches are delivered as ordered, hash-bound chunks
only when that reduces proof reads by at least 10%; smaller, binary, NUL-containing,
or unsafe patches retain bounded 240-line windows. Concatenating the chunks reproduces
the canonical patch exactly, and each delivered tool result remains below the 32 KiB
audit ceiling. Hash-bound source packets then supply exact
enclosing declarations, callers, tests, and gates from the snapshot or base tree.
When a source body does not fit, the integration seat must prove gap-free bounded
reads against the exact tree, blob, and content hashes. The audit checks successful
returned bytes, not only tool arguments.

Adaptive plan panels bind the immutable fix plan and parse every root-cause cluster.
The plan-completeness seat receives the full cumulative patch. Every other seat receives
the same closure containing every named site, test, regression path, and changed local
import boundary, plus up to three literal source packets. Each reviewer still sees the
complete plan and navigation index, runs the plan's bounded repository-root sibling
search for every cluster, and proves every named source range. Searches accept only a
single `rg` or recursive `grep` expression whose only path operand is literal `.`;
the manifest binds its regex engine and pattern, and engine substitutions, traversal
filters, redirected or saturated output, missing path or line fields, absent named sites,
and producer errors fail closed. Shell proof uses `--null` filenames so colon-bearing
paths remain unambiguous; native text search cannot certify it. A non-persisting panel
validator checks plan, prompt, patch, packet, search, source, result, and transcript
hashes without advancing code coverage. Missing, ambiguous, stale, unsafe, or incomplete
plan evidence reruns every plan seat under a fresh legacy full-scope label.

After a valid coverage receipt, verification seats start from the semantic fix delta
only when that delta plus its evidence is smaller. The regression-bundle seat still
reads the full cumulative patch. Missing, stale, malformed, unsafe, incomplete, or
unrepresentable evidence sends every seat back to full cumulative scope. Explicit
numeric and document reviews retain full scope. `rev-profile.py` labels planned word
savings separately from actual provider usage and cache metrics, and reports patch
proof calls, turns, visible bytes, chunks, and delivery modes.

### Simplicity first

Round 1 belongs entirely to one question: could the change be smaller? Every seat runs the `simplicity` lens, a checklist for shrinking by reuse and proportionality - workarounds whose stated reason no longer holds on the pinned dependency (open the registry or `.d.ts` source), hand-rolled mechanisms the engine or framework provides, machinery sized for a consumer the PR names, parameters every caller passes identically, generics no implementation varies, migrations from schemas born on the same unreleased branch, test axes left with one value. Reuse findings are accepted only with the existing symbol named at a location and version; scope cuts are deferred to the author. Correctness starts in round 2, because reviewing lines that should be deleted is the purest form of churn.

Why every seat, and why nothing else: measured blind on eight held-out PRs ([docs/simplicity-lens-eval-2026-09-06.md](docs/simplicity-lens-eval-2026-09-06.md)), four seats with the lens found the load-bearing simplification on 6 of 10 rows, one seat alone about half of that; replacing one seat with a `clean-room` design seat lost rows, and handing seats the author's PR description lost more than it gained. Both remain available as opt-ins (`clean-room` as a fifth seat; `rev-prompt.sh --pr`), neither is a default.

### The fix-plan gate

Between triage and a nontrivial fix, the orchestrator writes `fix-plan.md`: one rule per cluster, with every site, branch, realm and doc copy the rule reaches enumerated by search, what it must not break, and the test that fails without it. The same seats review an immutable snapshot of that plan before code is written, and fixes land one cluster per commit with every listed site in it.

The reason is measured, not felt: over 11 past runs, 56% of all findings were fixes of an earlier round's fix, 68% from round five on, and 55% of those were a rule applied to the one site a reviewer named while its siblings waited for the next round. Every seat's `suggested_fix` is now required to state the rule and its siblings, not a patch for the cited line. Details and numbers: [docs/churn-analysis-2026-09-06.md](docs/churn-analysis-2026-09-06.md).

Whenever the diff touches tests, every prompt in every round also carries the vacuity check: for each new or changed assertion, name the production change that would make it fail, and report any that has none. It is the single most common defect a panel finds, and it finds it late.

`rounds` remains a minimum override and selects that host's legacy numbered schedule. Numeric mode continues past the minimum while a new or open P0/P1, a nontrivial last fix, or an unreviewed lens or major file remains. It stops after the minimum, two consecutive rounds without a new P0/P1, no open P0/P1, and gates at baseline or better. Plan panels do not count as numbered rounds. Without a numeric value, the adaptive stopping rules above apply.

### The 10-minute status line

While a run is active you get one line every ten minutes without asking, built only from files in the session directory:

```
r3/adaptive triage | sol: done 4f 9m | grok: running 14m | opus: done 3f 8m | open P0:0 P1:1 P2:3 fixed 6
```

Per seat: done with a finding count and elapsed time, running with its last observed action, failed with an exit code, or dropped (usage cap). The overall counts come from `state.json`.

## `/review-council:stack`

```
/review-council:stack <config>
```

For a change that spans several repositories that must be reviewed together (a protocol change plus every SDK/client/app PR that depends on it):

1. Runs one `/review-council:rev` leg per repo, headless, in dependency order.
2. Detaches from your session so a multi-hour run doesn't hold the terminal.
3. Watches each leg for real staleness (log activity and CPU time, not just a timer) and retries a genuinely stalled leg rather than a slow one.
4. Adds a cross-repo seam pass once every leg's own rounds finish, checking the interfaces between repos specifically.
5. Once every phase has run, squashes and pushes each repo that had no failed leg - a repo with a failed leg is skipped entirely, neither squashed nor pushed. Each leg's own `report.md` (written by that leg's `/review-council:rev` run, inside its session directory) is its completion receipt; the stack keeps no separate aggregate report, only its own running log and, if any leg failed, a final `COMPLETE WITH FAILURES` line and non-zero exit.

## Seat roster

The roster is rebuilt at run time, never hardcoded. Per lab: the CLI must be on `PATH`, and cheaply confirmed signed in - no model call.

| Lab | CLI | Model(s) | Effort | Detected via |
|---|---|---|---|---|
| OpenAI | `codex` | top two current-generation `gpt-<major>.<minor>` slugs by priority | highest of `max → xhigh → high` each model supports | `codex login status` contains "Logged in"; models read from `~/.codex/models_cache.json` |
| xAI | `grok` | highest-versioned `grok-N.N` line | `xhigh` | `grok models` exits 0 and reports logged in |
| Google | `gemini` | `gemini-2.5-pro` (override via config/env) | none - Gemini has no effort knob | `GEMINI_API_KEY` set, or `~/.gemini/oauth_creds.json` exists |
| Anthropic | - (Agent tool) | `opus` | `max` | always available; opt out with `claude_seat: false` |

Two optional extra seats remain available for explicit numeric round plans: `codex-review` uses Codex's native review prompt and `grok-code-review` uses Grok's bundled `/code-review` skill. Adaptive default runs omit both. `extras: false` in config removes them entirely.

**With only Claude Code installed** - no `codex`, no `grok`, no `gemini` - the roster does not refuse. It pads the panel up to three seats with Claude seats (`opus`, `claude-1`, `claude-2`; adapter `agent`, `opus@max`, each marked `"padded": true`), deals them three different lenses like any other seats, and marks the whole roster `"degraded": true` with one sentence explaining what that costs:

```
review-council seats: codex ✗ not installed · grok ✗ not installed · gemini ✗ not installed · claude ✓ (opus@max) · DEGRADED: only Claude is available - 3 Claude seats, no cross-lab decorrelation
```

The same sentence comes back on preflight's warning line and opens the final report as `Degraded panel: <sentence>`, so a verdict is never read without knowing how many independent voices produced it. Padding also applies part-way: one lab plus the Claude seat is two, so one seat is padded in and the banner names the lost diversity. Set `min_labs: 2` or higher to turn that trade into a refusal. Explicit positive `codex_models` and `claude_seats` settings also become strict before padding. To require Sol, Grok, and two Opus runs, select Sol and two Opus seats, exclude Gemini, disable extras, and set `min_labs: 3`.

Strict roster refusals preserve their cause in `strict_reason` and append it to the one-line `--brief` output. Preflight propagates the class instead of collapsing it: exit 5 is retryable availability, such as a missing sign-in, failed probe, unavailable model cache, or a satisfiable lab floor whose provider is currently unavailable. Exit 6 is a permanent configuration conflict, such as a malformed exact setting, invalid `min_labs`, a lab floor above the maximum allowed by exclusions and disable settings, an unknown or unsupported configured model, a required exclusion, or an incompatible pin. Configuration wins when both causes occur, so a stack fails that leg immediately instead of waiting on a condition time cannot clear. A known permanent configuration refusal is decided before paid probes.

**Gemini caveat:** there was no Gemini CLI on the machine this was built on, so the adapter is written against the CLI's documented interface (`-p`, `--approval-mode plan`, `-o stream-json`) and fixture-tested against an assumed `stream-json` shape rather than a live response. The roster's cheap detection only checks for credentials; the `--probe` run at the start of a review does send Gemini a one-token call and drops the seat if it fails. Treat a Gemini finding with the same verification rigor as any other seat's, and expect to be the first to hit a shape mismatch if the CLI's output differs - `stream-summary.py`'s gemini branch and `tests/fixtures/gemini-stream.ndjson` are the two places to fix.

Detection is always cheap (binary + sign-in check); `roster.sh --probe` additionally sends each CLI seat a one-token round trip with a 60-second timeout and drops any seat that fails or times out - used by preflight before a real run starts, never by the session-start hook.

## Read-only guard

Every reviewer runs in a mode that cannot write, independent of what it's asked to do:

- Codex, Grok and Gemini are invoked with their own vendor read-only/plan flags (`-s read-only`, `--permission-mode plan`, `--approval-mode plan`) - the CLI itself refuses writes, not just our prompt.
- The Opus seat has `Write`/`Edit`/`NotebookEdit` disallowed by the harness, and every Bash call it makes passes through a `PreToolUse` guard script that blocks git state changes, redirections, in-place edits and installs while allowing diff/log/show/grep/test commands.
- Reviewers only ever return findings JSON; the calling Claude session is the sole actor that edits files, commits, or pushes - nothing a reviewer says is ever executed directly.

## Requirements

- `bash`, `python3` (stdlib only - no pip installs), `git`.
- Nothing beyond that: with no lab CLI at all the panel is padded to three Claude seats and runs degraded. Three or more seats across two or more labs is what the loop is designed for, and `min_labs` makes that a hard requirement if you want one.

## Development

```bash
plugins/review-council/tests/run-tests.sh          # full suite
plugins/review-council/tests/run-tests.sh roster   # name filter, matches any test_* containing "roster"
```

Tests are shimmed and hermetic - `tests/shims/{codex,grok,gemini,claude}` stand in for the real CLIs so the suite never touches the network or a real account and can run in CI unattended. CI (`.github/workflows/test.yml`) runs the suite on `macos-latest` and `ubuntu-latest`, plus `claude plugin validate --strict` on both the marketplace and plugin manifests.

## Why

A reviewer that shares the orchestrator's weights shares its blind spots - the same training data produces the same confident gaps. Running the same diff past several labs' frontier models, each with a different training mix and failure mode, catches what any one of them alone would call fine, and cross-seat agreement is a genuine (if imperfect) signal separate from any single model's confidence. That decorrelation is the entire reason this exists as a panel instead of one more prompt to the model already writing the code.
