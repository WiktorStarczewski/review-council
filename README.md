# review-council

A Claude Code plugin that runs your code review through a panel instead of one model: Codex, Grok, Gemini and an Opus subagent each read the same diff independently, in read-only mode, and answer in a shared findings schema. The orchestrating Claude session merges their claims into a ledger, verifies every one against the source before acting on it, fixes what's real, re-runs your gates, and commits — round after round until the panel stops finding anything new. The panel is never hardcoded: at the start of every session the plugin checks which lab CLIs are actually installed and signed in on your machine, builds the seat roster from that (and probes each seat with a one-token call before a review starts), so the review always runs with whatever frontier models you have. A panel is three seats; if your machine has fewer, the review still runs — the roster pads the panel with extra Claude seats, each on its own lens, and then says so everywhere it can: the session banner, the preflight line and the final report all carry `DEGRADED` and one sentence naming what decorrelation was lost. Nothing is quietly downgraded, and nothing is refused for being short-handed. Teams that would rather not review at all than review single-lab set `min_labs` and get a hard floor back.

## Install

Marketplace:

```bash
claude plugin marketplace add WiktorStarczewski/review-council
claude plugin install review-council@review-council
```

One-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install.sh | bash
```

The one-liner also turns on auto-update for the marketplace it just added (Claude Code leaves auto-update off for third-party marketplaces, so a plugin installed from one never moves on its own). It is the only thing the installer writes outside Claude Code's own install: one `autoUpdate` flag under `extraKnownMarketplaces.review-council` in `~/.claude/settings.json`. The file is rewritten atomically (tmp file, then rename) at 2-space indent with every other setting preserved, keeping its existing mode — a `600` settings file stays `600`, and one created from scratch starts there — following a symlink rather than replacing it, and leaving anything it cannot parse untouched. Skip it with `--no-auto-update`:

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install.sh | bash -s -- --no-auto-update
```

Update by hand any time with `claude plugin update review-council`; restart Claude Code (or `/reload-plugins`) after installing or updating. If you would rather be told than updated, set `check_updates: true` in the config and the session banner adds one line when a newer version is published (off by default, checked at most once a day, silent when the network is unreachable) — see [docs/config.md](docs/config.md).

## At session start

A `SessionStart` hook runs on `startup`, `clear` and `compact`. It does two cheap things — no model calls, under a second — and one optional third:

1. Injects the standing review policy (`skills/rev/POLICY.md`): use `/review-council:rev` for review requests, reviewers never edit, apply actionable findings after a review, relay the round-status line, never substitute your own reading for the panel's.
2. Injects one roster line from `scripts/roster.sh --brief`, e.g.:

   ```
   review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@max) · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max)
   ```

With `check_updates: true` in the config it adds a third line, and only when there is something to say:

   ```
   review-council 0.2.0 available: claude plugin update review-council
   ```

If roster detection itself fails, the line says `review-council seats: roster unavailable (<reason>)` and the hook still exits 0 — a broken roster never blocks a session from starting. The update check is held to the same bar and then some: it is off unless you turn it on, it asks the network at most once a day, it is capped at three seconds, and any failure means no line rather than a delay. The hook never updates the plugin itself — a plugin's own hook replacing the directory it is running from is how an install gets corrupted — so all it ever does is name the command.

## `/review-council:rev`

```
/review-council:rev [scope] [rounds] [--read-only] [--base <ref>]
```

`scope` is `branch` (default), `uncommitted`, a path, a PR number/URL, or a branch name; `rounds` is a minimum round count (default 8); `--read-only` reports findings without fixing or committing, for plans and docs as well as code; `--base` names the branch the change was cut from when the guess is wrong (the guess is the open PR's base, else the nearest fork point among `main`, `next`, `develop`, else `origin/HEAD`).

The loop, in six steps, repeated each round:

1. **Fan out** — every seat reviews the same pinned diff in parallel, each assigned a lens (correctness, security, concurrency, API contract, tests, red team, …) that rotates by round so every lens gets covered.
2. **Collect** — wait for all seats; a failed seat retries once a step down its effort ladder; fewer than three seats *reporting* stops the round rather than reviewing short-handed (three are always launched — the roster pads the panel if it has to).
3. **Triage** — findings are deduplicated across seats, every claim is independently verified against the code before it's trusted, and accepted findings are clustered by root cause; agreement across seats is signal, not proof.
4. **Plan** — after round 1, and after any later round with a P0/P1 or a new cluster, the fix plan (one rule per cluster, every site enumerated) is reviewed by the panel before code is written.
5. **Fix and verify** — real findings are fixed P0 first, gates (build/test/lint) are re-run against the pre-round baseline, and a fix that breaks something is repaired or reverted before moving on.
6. **Commit and record** — the round's fixes are committed one cluster per commit and the ledger (`findings.md`) is updated with what was found, fixed, or rejected and why.

The loop keeps going past the minimum while new P0/P1s are still surfacing, and stops once two consecutive rounds add nothing and every open issue is resolved. At the end it squashes the round commits, pushes once, and writes `report.md`.

### Round plan

Each round has a fixed emphasis; that is what makes seven rounds worth more than one round seven times. **Every base seat reviews in every round** (on a typical machine: two Codex models, Grok, Gemini when installed, and the Opus subagent). The lenses listed for a round are dealt round-robin over those seats, offset by the round number, so a three-seat and a six-seat panel both cover the same ground and no seat keeps the same lens twice in a row. Every seat's prompt names its lens and the round's emphasis.

The last column is a **one-off additional reviewer** that joins that round on top of the base seats, the way Cursor's `bugbot` and `security-review` did: in round 2, `codex exec review` runs Codex's own built-in review prompt instead of ours; in round 3, Grok's bundled maintainability skill runs. Each fires once per run and only when its lab is seated.

| Round | Emphasis | Lenses | One-off reviewer added this round |
|---|---|---|---|
| 1 | Simplicity: could this change be smaller? | simplicity ×3, clean-room ×1 | — |
| 2 | Correctness, edge cases, error handling | correctness, edge-cases, error-handling | — |
| 3 | Security, data and state | security, data-state | `codex-review` (Codex's own review prompt) |
| 4 | Concurrency, resources, performance | concurrency, resources, performance | `grok-code-review` (Grok's maintainability skill) |
| 5 | API and contract, compatibility | api-contract, data-state, readability | — |
| 6 | Tests, observability | tests, observability | — |
| 7 | Red team: every seat argues the change is broken | red-team | — |
| 8 | Regression: re-read the cumulative diff including all fixes | regression | — |
| 9+ | Whatever is least covered or still open | the uncovered lenses, rotated | — |

### Simplicity first

Round 1 belongs entirely to one question: could the change be smaller? Three seats run the `simplicity` lens, a checklist for shrinking by reuse and proportionality — workarounds whose stated reason no longer holds on the pinned dependency (open the registry or `.d.ts` source), hand-rolled mechanisms the engine or framework provides, machinery sized for a consumer the PR names, parameters every caller passes identically, generics no implementation varies, migrations from schemas born on the same unreleased branch, test axes left with one value. The fourth seat runs `clean-room`: it writes the smallest design for the named consumer before reading the diff, then reports where the change exceeds it. All seats get the author's PR description, since proportionality is judged against the consumer the author names. Reuse findings are accepted only with the existing symbol named at a location and version; scope cuts are deferred to the author. Correctness starts in round 2, because reviewing lines that should be deleted is the purest form of churn. Why the whole round: measured on held-out PRs, one seat with the lens found about half of what four found together.

### The fix-plan gate

Between triage and fixing, after round 1 and after any later round that accepts a P0/P1 or opens a new root-cause cluster, the orchestrator writes `fix-plan.md`: one rule per cluster, with every site, branch, realm and doc copy the rule reaches enumerated by search, what it must not break, and the test that fails without it. The same seats then review the plan (lenses: completeness of the site list, soundness, a simpler fix by reuse, and whether the test can fail) before any code is written, and fixes land one cluster per commit with every listed site in it.

The reason is measured, not felt: over 11 past runs, 56% of all findings were fixes of an earlier round's fix, 68% from round five on, and 55% of those were a rule applied to the one site a reviewer named while its siblings waited for the next round. Every seat's `suggested_fix` is now required to state the rule and its siblings, not a patch for the cited line. Details and numbers: [docs/churn-analysis-2026-09-06.md](docs/churn-analysis-2026-09-06.md).

Whenever the diff touches tests, every prompt in every round also carries the vacuity check: for each new or changed assertion, name the production change that would make it fail, and report any that has none. It is the single most common defect a panel finds, and it finds it late.

`rounds` is a minimum. The loop extends past it while the last round produced a new P0/P1, its fixes were more than trivial, a P0/P1 is still open, or a lens or major changed file has not been reviewed; it stops when the minimum has run, two consecutive rounds produced no new P0/P1, nothing P0/P1 is open, and the gates are at or above the baseline.

### The 10-minute status line

While a run is active you get one line every ten minutes without asking, built only from files in the session directory:

```
r3/7 triage | sol: done 4f 9m | terra: done 2f 11m | grok: running 14m ← rg "retry" src/api | opus: done 3f 8m | open P0:0 P1:1 P2:3 fixed 6
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
5. Once every phase has run, squashes and pushes each repo that had no failed leg — a repo with a failed leg is skipped entirely, neither squashed nor pushed. Each leg's own `report.md` (written by that leg's `/review-council:rev` run, inside its session directory) is its completion receipt; the stack keeps no separate aggregate report, only its own running log and, if any leg failed, a final `COMPLETE WITH FAILURES` line and non-zero exit.

## Seat roster

The roster is rebuilt at run time, never hardcoded. Per lab: the CLI must be on `PATH`, and cheaply confirmed signed in — no model call.

| Lab | CLI | Model(s) | Effort | Detected via |
|---|---|---|---|---|
| OpenAI | `codex` | top two current-generation `gpt-<major>.<minor>` slugs by priority | highest of `max → xhigh → high` each model supports | `codex login status` contains "Logged in"; models read from `~/.codex/models_cache.json` |
| xAI | `grok` | highest-versioned `grok-N.N` line | `xhigh` | `grok models` exits 0 and reports logged in |
| Google | `gemini` | `gemini-2.5-pro` (override via config/env) | none — Gemini has no effort knob | `GEMINI_API_KEY` set, or `~/.gemini/oauth_creds.json` exists |
| Anthropic | — (Agent tool) | `opus` | `max` | always available; opt out with `claude_seat: false` |

Two extra seats join later rounds when their lab is seated: `codex-review` (codex's own native review prompt, round 3) and `grok-code-review` (grok with its bundled `/code-review` skill, round 4). `extras: false` in config removes both.

**With only Claude Code installed** — no `codex`, no `grok`, no `gemini` — the roster does not refuse. It pads the panel up to three seats with Claude seats (`opus`, `claude-1`, `claude-2`; adapter `agent`, `opus@max`, each marked `"padded": true`), deals them three different lenses like any other seats, and marks the whole roster `"degraded": true` with one sentence explaining what that costs:

```
review-council seats: codex ✗ not installed · grok ✗ not installed · gemini ✗ not installed · claude ✓ (opus@max) · DEGRADED: only Claude is available — 3 Claude seats, no cross-lab decorrelation
```

The same sentence comes back on preflight's own `preflight: WARNING — …` line and opens the final report as `Degraded panel: …`, so a verdict is never read without knowing how many independent voices produced it. Padding also applies part-way: one lab plus the Claude seat is two, so one seat is padded in and the banner reads `DEGRADED: only xai, anthropic available — padded with 1 Claude seat`. Three seats reviewed by one lab is still a worse review than three labs — it is just a much better one than none, and the loudness is the trade. Set `min_labs: 2` (or higher) in the config to turn that trade back into a refusal: below the floor the roster exits 5 and preflight stops the run with `strict: 1 lab(s) available, min_labs=2`.

**Gemini caveat:** there was no Gemini CLI on the machine this was built on, so the adapter is written against the CLI's documented interface (`-p`, `--approval-mode plan`, `-o stream-json`) and fixture-tested against an assumed `stream-json` shape rather than a live response. The roster's cheap detection only checks for credentials; the `--probe` run at the start of a review does send Gemini a one-token call and drops the seat if it fails. Treat a Gemini finding with the same verification rigor as any other seat's, and expect to be the first to hit a shape mismatch if the CLI's output differs — `stream-summary.py`'s gemini branch and `tests/fixtures/gemini-stream.ndjson` are the two places to fix.

Detection is always cheap (binary + sign-in check); `roster.sh --probe` additionally sends each CLI seat a one-token round trip with a 60-second timeout and drops any seat that fails or times out — used by preflight before a real run starts, never by the session-start hook.

## Read-only guard

Every reviewer runs in a mode that cannot write, independent of what it's asked to do:

- Codex, Grok and Gemini are invoked with their own vendor read-only/plan flags (`-s read-only`, `--permission-mode plan`, `--approval-mode plan`) — the CLI itself refuses writes, not just our prompt.
- The Opus seat has `Write`/`Edit`/`NotebookEdit` disallowed by the harness, and every Bash call it makes passes through a `PreToolUse` guard script that blocks git state changes, redirections, in-place edits and installs while allowing diff/log/show/grep/test commands.
- Reviewers only ever return findings JSON; the calling Claude session is the sole actor that edits files, commits, or pushes — nothing a reviewer says is ever executed directly.

## Requirements

- `bash`, `python3` (stdlib only — no pip installs), `git`.
- Nothing beyond that: with no lab CLI at all the panel is padded to three Claude seats and runs degraded. Three or more seats across two or more labs is what the loop is designed for, and `min_labs` makes that a hard requirement if you want one.

## Development

```bash
plugins/review-council/tests/run-tests.sh          # full suite
plugins/review-council/tests/run-tests.sh roster   # name filter, matches any test_* containing "roster"
```

Tests are shimmed and hermetic — `tests/shims/{codex,grok,gemini,claude}` stand in for the real CLIs so the suite never touches the network or a real account and can run in CI unattended. CI (`.github/workflows/test.yml`) runs the suite on `macos-latest` and `ubuntu-latest`, plus `claude plugin validate --strict` on both the marketplace and plugin manifests.

## Why

A reviewer that shares the orchestrator's weights shares its blind spots — the same training data produces the same confident gaps. Running the same diff past several labs' frontier models, each with a different training mix and failure mode, catches what any one of them alone would call fine, and cross-seat agreement is a genuine (if imperfect) signal separate from any single model's confidence. That decorrelation is the entire reason this exists as a panel instead of one more prompt to the model already writing the code.
