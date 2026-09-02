# review-council

A Claude Code plugin that runs your code review through a panel instead of one model: Codex, Grok, Gemini and an Opus subagent each read the same diff independently, in read-only mode, and answer in a shared findings schema. The orchestrating Claude session merges their claims into a ledger, verifies every one against the source before acting on it, fixes what's real, re-runs your gates, and commits — round after round until the panel stops finding anything new. The panel is never hardcoded: at the start of every session the plugin probes which lab CLIs are actually installed and signed in on your machine and builds the seat roster from that, so the review always runs with whatever frontier models you have, and refuses outright rather than quietly reviewing with fewer voices than that implies.

## Install

Marketplace:

```bash
claude plugin marketplace add zoroswap/review-council
claude plugin install review-council@review-council
```

One-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/zoroswap/review-council/main/install.sh | bash
```

Update with `claude plugin update review-council`. Restart Claude Code (or `/reload-plugins`) after installing.

## At session start

A `SessionStart` hook runs on `startup`, `clear` and `compact`. It does two cheap things — no model calls, under a second:

1. Injects the standing review policy (`skills/rev/POLICY.md`): use `/review-council:rev` for review requests, reviewers never edit, apply actionable findings after a review, relay the round-status line, never substitute your own reading for the panel's.
2. Injects one roster line from `scripts/roster.sh --brief`, e.g.:

   ```
   review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@max) · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max)
   ```

If roster detection itself fails, the line says `review-council seats: roster unavailable (<reason>)` and the hook still exits 0 — a broken roster never blocks a session from starting.

## `/review-council:rev`

```
/review-council:rev [scope] [rounds] [--read-only]
```

`scope` is `branch` (default), `uncommitted`, a path, a PR number/URL, or a branch name; `rounds` is a minimum round count (default 7); `--read-only` reports findings without fixing or committing, for plans and docs as well as code.

The loop, in five steps, repeated each round:

1. **Fan out** — every seat reviews the same pinned diff in parallel, each assigned a lens (correctness, security, concurrency, API contract, tests, red team, …) that rotates by round so every lens gets covered.
2. **Collect** — wait for all seats; a failed seat retries once a step down its effort ladder; fewer than three seats reporting stops the run rather than reviewing short-handed.
3. **Triage** — findings are deduplicated across seats and every claim is independently verified against the code before it's trusted; agreement across seats is signal, not proof.
4. **Fix and verify** — real findings are fixed P0 first, gates (build/test/lint) are re-run against the pre-round baseline, and a fix that breaks something is repaired or reverted before moving on.
5. **Commit and record** — the round's fixes are committed and the ledger (`findings.md`) is updated with what was found, fixed, or rejected and why.

The loop keeps going past the minimum while new P0/P1s are still surfacing, and stops once two consecutive rounds add nothing and every open issue is resolved. At the end it squashes the round commits, pushes once, and writes `report.md`.

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

Two extra seats join later rounds when their lab is seated: `codex-review` (codex's own native review prompt, round 2) and `grok-code-review` (grok with its bundled `/code-review` skill, round 3). `extras: false` in config removes both.

**Gemini caveat:** detection only checks for credentials, never a live call — there is no `--probe` support and no CLI available to verify the adapter end-to-end during development, so the Gemini seat is fixture-tested against a documented `stream-json` shape rather than proven against a live response. Treat a Gemini finding with the same verification rigor as any other seat's, and expect to be the first to hit a real shape mismatch if Google changes that output format.

Detection is always cheap (binary + sign-in check); `roster.sh --probe` additionally sends each CLI seat a one-token round trip with a 60-second timeout and drops any seat that fails or times out — used by preflight before a real run starts, never by the session-start hook.

## Read-only guard

Every reviewer runs in a mode that cannot write, independent of what it's asked to do:

- Codex, Grok and Gemini are invoked with their own vendor read-only/plan flags (`-s read-only`, `--permission-mode plan`, `--approval-mode plan`) — the CLI itself refuses writes, not just our prompt.
- The Opus seat has `Write`/`Edit`/`NotebookEdit` disallowed by the harness, and every Bash call it makes passes through a `PreToolUse` guard script that blocks git state changes, redirections, in-place edits and installs while allowing diff/log/show/grep/test commands.
- Reviewers only ever return findings JSON; the calling Claude session is the sole actor that edits files, commits, or pushes — nothing a reviewer says is ever executed directly.

## Requirements

- `bash`, `python3` (stdlib only — no pip installs), `git`.
- At least three seats detected and signed in, in any combination of the labs above; fewer than three and every entry point (roster, preflight, the loop's own collect step) refuses rather than reviewing short-handed.

## Development

```bash
plugins/review-council/tests/run-tests.sh          # full suite
plugins/review-council/tests/run-tests.sh roster   # name filter, matches any test_* containing "roster"
```

Tests are shimmed and hermetic — `tests/shims/{codex,grok,gemini,claude}` stand in for the real CLIs so the suite never touches the network or a real account and can run in CI unattended. CI (`.github/workflows/test.yml`) runs the suite on `macos-latest` and `ubuntu-latest`, plus `claude plugin validate --strict` on both the marketplace and plugin manifests.

## Why

A reviewer that shares the orchestrator's weights shares its blind spots — the same training data produces the same confident gaps. Running the same diff past several labs' frontier models, each with a different training mix and failure mode, catches what any one of them alone would call fine, and cross-seat agreement is a genuine (if imperfect) signal separate from any single model's confidence. That decorrelation is the entire reason this exists as a panel instead of one more prompt to the model already writing the code.
