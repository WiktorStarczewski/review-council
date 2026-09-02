# review-council — Claude Code plugin (design)

Date: 2026-09-02 · Status: approved (design agreed in chat; "Do all of it")
Ports: the in-harness `rev` loop from `~/.claude/skills/rev` (see `2026-09-02-rev-loop-design.md`, same directory — its loop, ledger, seats, status tick and stack semantics are inherited unchanged unless this document says otherwise).

## 1. Goal

Package the multi-model review loop as a Claude Code plugin that installs in one line, bootstraps itself every session the way Superpowers does, and **builds its reviewer roster at run time from whichever lab CLIs are installed and signed in** — instead of the hardcoded four seats.

## 2. Distribution

- Repo `zoroswap/review-council` (public) is both the **marketplace** and the **plugin**, in the layout OpenAI's codex plugin uses:
  ```
  .claude-plugin/marketplace.json        name: review-council, plugins: [{ name: review-council, source: ./plugins/review-council }]
  plugins/review-council/
    .claude-plugin/plugin.json           name, version, description, author, homepage, repository, license, keywords
    skills/rev/SKILL.md                  /review-council:rev
    skills/stack/SKILL.md                /review-council:stack
    agents/rev-reviewer.md               review-council:rev-reviewer (Opus seat)
    hooks/hooks.json                     SessionStart → hooks/session-start
    hooks/session-start                  bash; injects policy + roster line as additionalContext
    scripts/…                            roster, seats, adapters, stack, lib
    tests/…                              shimmed unit suite (no network)
  install.sh                             curl-able one-liner: marketplace add + plugin install
  README.md  LICENSE (MIT)  .github/workflows/test.yml
  ```
- Install: `claude plugin marketplace add zoroswap/review-council && claude plugin install review-council@review-council`, or `curl -fsSL https://raw.githubusercontent.com/zoroswap/review-council/main/install.sh | bash`. Update: `claude plugin update review-council`.
- No npm package: Claude Code plugins are delivered by marketplaces; Superpowers' `package.json` serves other harnesses. (An npm shim can be added later without changing anything here.)
- Every path inside the plugin is `${CLAUDE_PLUGIN_ROOT}`-relative in skill text, hook commands and the agent's hook; scripts locate siblings via their own path.

## 3. Session bootstrap (the Superpowers move)

`hooks/session-start` (bash, no bun) prints `hookSpecificOutput.additionalContext` containing:

1. `skills/rev/POLICY.md` verbatim — ten lines: use `/review-council:rev` for any review request; reviewers never edit; apply actionable findings after a review; relay the 10-minute status line; never substitute your own reading for the panel.
2. One roster line from `scripts/roster.sh --brief`, e.g. `review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@max) · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max)`.

The hook does only **cheap** detection (binary on PATH, status command, config/cache files); it never calls a model, so session start stays under a second. Matcher `startup|clear|compact`.

## 4. Roster (the bonus, made the default)

`scripts/roster.sh [--brief|--json] [--probe]` writes/prints `roster.json`:

```json
{ "generated_at": "...", "seats": [
    { "seat": "codex-sol",   "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",   "effort": "max",   "extra": false },
    { "seat": "codex-terra", "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-terra", "effort": "max",   "extra": false },
    { "seat": "grok",        "lab": "xai",       "adapter": "grok",   "model": "grok-4.6",      "effort": "xhigh", "extra": false },
    { "seat": "gemini",      "lab": "google",    "adapter": "gemini", "model": "gemini-2.5-pro","effort": null,    "extra": false },
    { "seat": "opus",        "lab": "anthropic", "adapter": "agent",  "model": "opus",          "effort": "max",   "extra": false },
    { "seat": "codex-review","lab": "openai",    "adapter": "codex",  "mode": "review",         "extra": true, "round": 2 },
    { "seat": "grok-code-review","lab":"xai",    "adapter": "grok",   "mode": "code-review",    "extra": true, "round": 3 } ],
  "excluded": [ { "cli": "gemini", "reason": "not installed" } ] }
```

Detection per adapter:

| adapter | present | signed in (cheap) | models / effort |
|---|---|---|---|
| codex | `command -v codex` | `codex login status` → "Logged in" | `~/.codex/models_cache.json`: slugs with `visibility: list`, the top two by `priority` among the current generation, effort = highest of `max→xhigh→high` each supports |
| grok | `command -v grok` | `grok models` exit 0 + "You are logged in" | highest-versioned `grok-*` in that list; `xhigh` if listed else `high` |
| gemini | `command -v gemini` | `~/.gemini/oauth_creds.json` or `GEMINI_API_KEY` present | no list command: `REVIEW_COUNCIL_GEMINI_MODEL` (default `gemini-2.5-pro`); no effort knob |
| agent | always (Claude Code) | always | `opus` at `max`; `REVIEW_COUNCIL_CLAUDE_SEAT=0` removes it |

Rules (unchanged in spirit): top frontier per lab, never a mid tier, highest effort, ≥3 seats or the run refuses. `--probe` (used by preflight, not the hook) additionally sends a one-token "reply OK" to each CLI seat with a 60 s timeout and drops seats that fail, recording the reason. Overrides in `${REVIEW_COUNCIL_CONFIG:-~/.config/review-council/config.json}` (not `CLAUDE_PLUGIN_DATA`: it is per-plugin and leaks into shells): `exclude: ["gemini"]`, `pin: {"codex-sol": {"effort": "ultra"}}`, `extras: false`, `claude_seat: false`.

## 5. Adapters

`scripts/rev-seat.sh <seat> <session> <round> <prompt> [--effort e] [--base ref]` keeps its CLI and exit-code contract (0/2/3/4/1) but dispatches on the roster: it reads `roster.json` for the seat's adapter/model/effort/mode and executes `scripts/seats.d/<adapter>.sh`. Adapter contract: environment `SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE`; the adapter runs the CLI read-only, streams events through `lib/stream-summary.py <adapter>` into `LOG` (raw stream to `RAW`), leaves schema JSON at `OUT`, returns the CLI's exit code. The wrapper validates, converts native prose (codex review), retries a zero-tool-call grok answer, classifies failures from CLI-originated lines only, and writes `.exit`.

| adapter | invocation |
|---|---|
| codex | `codex exec --ephemeral -s read-only -C $ROOT -m $MODEL -c model_reasoning_effort=$EFFORT --json --output-schema $SCHEMA -o $OUT - < $PROMPT`; `MODE=review`: `codex exec review --base $BASE … -c sandbox_mode="read-only"` from `$ROOT`, prose → `lib/codex-review-to-findings.py` |
| grok | `grok --prompt-file $PROMPT --cwd $ROOT -m $MODEL --reasoning-effort $EFFORT --permission-mode plan --output-format streaming-json --json-schema "$(cat $SCHEMA)" --max-turns 120 </dev/null`; `MODE=code-review` prefixes `/code-review` |
| gemini | `gemini -p "Follow the instructions on stdin exactly; run your tools first; answer with only the JSON object." -m $MODEL --approval-mode plan -o stream-json < $PROMPT` from `$ROOT`; no schema flag: the adapter extracts the outermost `{…}` from the final text and the wrapper validates; `stream-summary.py gemini` maps its stream-json tool events to `tool_call` lines |
| agent | not a script: the skill launches `review-council:rev-reviewer` via the Agent tool, saves its JSON, validates, writes `.exit` |

Effort defaults come from the roster (which read the cache), so `rev-seat.sh` no longer guesses `max`.

## 6. Loop changes vs. the `rev` spec

- Fan-out iterates `roster.seats` (non-extra) in one message; extras join in their round when present. Lens assignment: the round's emphasis list, round-robin over seats, rotated by round number, so a 3-, 4- or 6-seat roster all cover every lens.
- The "minimum three seats" rule is enforced at preflight (roster) and again at collect.
- `preflight` prints the roster and writes `roster.json` + `scope.env` (single-quoted values) + `files.txt` + `untracked.txt`.
- Everything else (ledger, status tick, squash, read-only panel, stack-leg mode, failure table) is inherited.

## 7. Stack

`skills/stack` + `scripts/stack.sh` = the ported `rev-stack.sh`: self-detaching, one stall detector with the pid/mtime/CPU re-checks, `report.md` completion receipt, failure tracking with `COMPLETE WITH FAILURES`, squash decoupled from push, auth wait via `roster.sh --brief` (≥3 seats signed in). Legs run `claude -p "/review-council:rev branch N — use S as the session dir. …"` with `REV_STACK_LEG=1`.

## 8. Portability and CI

- `scripts/lib/compat.sh`: `rc_mtime <path>` (`stat -f %m` on BSD, `stat -c %Y` on GNU), `rc_touch_ago <secs> <ref>`; every BSD-only call routes through it. `pgrep`/`ps -o time=` are POSIX enough.
- `tests/run-tests.sh` (ported, file-tallied, filter-must-match) with shims for `codex`, `grok`, `gemini`, `claude`; runs on `macos-latest` and `ubuntu-latest` in `.github/workflows/test.yml`, plus `claude plugin validate --strict` on both manifests (claude installed from npm in CI).

## 9. Retiring the local copy (this machine)

After the plugin installs from GitHub and a live `/review-council:rev branch 2` passes on a self-test branch: delete `~/.claude/skills/rev`, `~/.claude/skills/review-stack`, `~/.claude/agents/rev-reviewer.md`; point the global CLAUDE.md review rules at `/review-council:rev`; update the `rev-toolchain` memory note. The SessionStart hook then carries the policy.

## 10. Testing

| # | Check | Pass |
|---|---|---|
| U | `tests/run-tests.sh` on macOS and Linux (CI) | `failed=0`; every adapter has shim-backed tests incl. the roster (fixtures for each detection state) |
| V | `claude plugin validate --strict` on marketplace + plugin | clean |
| L1 | `claude plugin marketplace add /Users/celrisen/review-council` + install; new session shows the bootstrap context and roster line | policy text + `codex ✓ … gemini ✗` visible |
| L2 | `/review-council:rev branch 2` on a re-planted self-test branch | roster = codex×2 + grok + opus; plants found; loop terminates; squash; report |
| L3 | one headless stack leg (`/review-council:stack`) | DONE with report.md, no false kill, orchestrator finish |
| L4 | reinstall from GitHub (`marketplace add zoroswap/review-council`) | same as L1 |
| L5 | roster with gemini shim present | gemini seat appears with the configured model; adapter unit-tested against a fixture stream (no live Gemini on this box — documented) |

## 11. Non-goals

- npm publication; Cursor/Copilot/pi hook variants; Gemini live validation (no CLI here); a GUI.
