# review-council Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the working in-harness `rev` loop into the `review-council` Claude Code plugin: one-line install, Superpowers-style session bootstrap, and a reviewer roster built at run time from the lab CLIs present.

**Architecture:** This is a PORT. Task 1 (done) copied the proven scripts, skills, agent, tests, shims and fixtures from `~/.claude/skills/rev` into `plugins/review-council/`. Each task below adapts its own files in place: `${CLAUDE_PLUGIN_ROOT}` paths in markdown, self-located scripts, a roster that replaces the hardcoded four seats, per-CLI adapters, a session-start hook, and portability for Linux. File ownership is disjoint so tasks run in parallel; nobody commits — the controller commits per task after review.

**Tech Stack:** bash (macOS BSD + GNU/Linux), python3 stdlib, `codex` 0.152+, `grok` 1.0+, `gemini` 0.58+ (adapter written to its `--help`; not live-validated here), `claude` 2.1+.

**Spec:** `docs/superpowers/specs/2026-09-02-review-council-design.md` (this plan argues from it); inherited loop semantics: `docs/superpowers/specs/2026-09-02-rev-loop-design.md`.

## Global Constraints

- Plugin root is `plugins/review-council/` (below: `$P`). Markdown (skills, agent, hooks.json) references plugin files ONLY as `${CLAUDE_PLUGIN_ROOT}/...`; scripts locate siblings via `HERE=$(cd "$(dirname "$0")" && pwd)`. The string `~/.claude/skills` must not appear anywhere in `$P`.
- Namespaces: the skills are invoked as `/review-council:rev` and `/review-council:stack`; the agent is `review-council:rev-reviewer`.
- Roster JSON shape and `roster.sh` CLI are fixed by spec §4; the adapter environment contract by spec §5; `rev-seat.sh` exit codes stay `0` valid / `2` missing-or-invalid JSON / `3` not signed in / `4` usage cap / `1` other.
- Reviewers never write: codex `-s read-only` (and `-c sandbox_mode="read-only"` for `exec review`), grok `--permission-mode plan`, gemini `--approval-mode plan`, the Opus agent fenced by `scripts/lib/readonly-bash-guard.py`.
- Portability: every `stat -f` / `date -v` goes through `scripts/lib/compat.sh` (`rc_mtime`, `rc_touch_ago`, `rc_newest_mtime`); tests must pass on macOS and Linux (CI matrix).
- Tests: `$P/tests/run-tests.sh [filter]` sources `tests/t-*.sh`; shims in `tests/shims/` (codex, grok, gemini, claude) are owned by Task 1 and are NOT edited by tasks — if a shim mode is missing, say so in the report. Never run the real CLIs. Every change gets a test that fails without it.
- Scripts are replaced atomically (`.new` + `mv`); no `set -e` where exit codes are the contract; no AI attribution anywhere.

## File Structure (ownership)

```
$P/scripts/roster.sh, scripts/lib/roster.py, tests/t-roster.sh, tests/fixtures/roster-*.json        Task 2
$P/scripts/rev-seat.sh, scripts/seats.d/{codex,grok,gemini}.sh, scripts/lib/stream-summary.py,
   scripts/lib/codex-review-to-findings.py, tests/{t-seat,t-seat2,t-cxreview,t-grok-notools,t-gemini}.sh   Task 3
$P/scripts/{rev-preflight,rev-prompt,rev-state,rev-status,rev-squash}.sh, scripts/lib/validate-findings.py,
   tests/{t-preflight,t-preflight2,t-scopeenv,t-status,t-squash,t-state,t-validate,t-runner}.sh            Task 4
$P/skills/rev/SKILL.md, skills/rev/POLICY.md, skills/stack/SKILL.md, agents/rev-reviewer.md,
   scripts/lib/readonly-bash-guard.py, tests/{t-guard,t-guard2,t-skill}.sh                                   Task 5
$P/hooks/hooks.json, hooks/session-start, tests/t-hook.sh                                                    Task 6
$P/scripts/stack.sh, scripts/stack.example.sh, tests/t-stack.sh                                              Task 7
README.md, CHANGELOG.md, docs/seats.md, docs/config.md                                                      Task 8
```

---

### Task 2: Roster — detect the lab CLIs and build the seat set

**Files:**
- Create: `$P/scripts/roster.sh` (thin bash entry) and `$P/scripts/lib/roster.py` (all logic)
- Create: `$P/tests/t-roster.sh`, `$P/tests/fixtures/roster-codex-cache-full.json`, `roster-codex-cache-terra-xhigh.json`, `roster-config-exclude.json`, `roster-config-pin.json`

**Interfaces:**
- Produces: `roster.sh [--json|--brief] [--probe] [--write <file>]`. Default `--json` to stdout. `--brief` prints ONE line: `review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@max) · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max)`. `--write` also stores the JSON. Exit `0` when ≥3 non-extra seats, `5` when fewer (JSON still emitted, `excluded[]` says why). JSON shape exactly as spec §4 (keys `generated_at`, `seats[]` with `seat lab adapter model effort extra` and, for extras, `mode round`; `excluded[]` with `cli reason`).
- Detection (cheap, always): codex = `command -v codex` + `codex login status` contains `Logged in` + `${REVIEW_COUNCIL_CODEX_MODELS_CACHE:-$HOME/.codex/models_cache.json}`: slugs with `visibility == "list"` whose slug starts with the newest `gpt-<major>.<minor>` generation present, sorted by `priority`, take up to two; effort = first of `max, xhigh, high` in that model's `supported_reasoning_levels`. grok = `command -v grok` + `grok models` exit 0 and output contains `logged in` but not `not logged in`; model = the highest-versioned `grok-N.N` line; effort `xhigh`. gemini = `command -v gemini` + (`GEMINI_API_KEY` set or `${REVIEW_COUNCIL_GEMINI_CREDS:-$HOME/.gemini/oauth_creds.json}` exists); model `${REVIEW_COUNCIL_GEMINI_MODEL:-gemini-2.5-pro}`, effort `null`. agent (claude) = always, model `opus`, effort `max`, unless `REVIEW_COUNCIL_CLAUDE_SEAT=0` or config `claude_seat: false`.
- Extras: `codex-review` (adapter codex, mode review, round 2) whenever codex is seated; `grok-code-review` (adapter grok, mode code-review, round 3) whenever grok is seated; config `extras: false` removes both.
- `--probe`: for each CLI seat run a one-token call with a 60 s timeout (python `subprocess.run(..., timeout=60)`, stdin `/dev/null`): codex `codex exec --ephemeral -s read-only -m <model> "Reply with exactly OK"`, grok `grok -p "Reply with exactly OK" -m <model> --permission-mode plan --output-format json --max-turns 1`, gemini `gemini -p "Reply with exactly OK" -m <model> --approval-mode plan -o json`. Non-zero exit or timeout → the seat moves to `excluded` with reason `probe failed: <first stderr line>` / `probe timed out`. The agent seat is never probed.
- Config: `${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}` with `exclude: [labs or seats]`, `pin: {seat: {model, effort}}`, `extras: bool`, `claude_seat: bool`. Unknown keys ignored; a malformed file is reported in `excluded` as `config unreadable` and otherwise ignored.
- Consumed by: preflight (Task 4) writes `$S/roster.json`; `rev-seat.sh` (Task 3) reads it; the hook (Task 6) prints `--brief`; the stack (Task 7) polls `--brief` exit code for auth.

- [ ] **Step 1: Write the failing tests** in `tests/t-roster.sh`: build a temp `bin/` containing only the shims you want "installed" and put it first on PATH (the real CLIs must never be found: also prepend a dir that shadows them). Cases: all three shims + full cache → 4 seats + 2 extras, exit 0, `--brief` line matches the format above; cache where terra lists no `max` → `codex-terra` effort `xhigh`; no gemini shim → `excluded` has `{cli: gemini, reason: "not installed"}`; gemini present but no creds → `not signed in`; `SHIM_MODE=grok-notauth` → grok excluded, exit still 0 (3 seats left); only codex + claude → exit 5; config `exclude: ["grok"]`; config `pin` changes effort; `claude_seat: false`; `--probe` with `SHIM_MODE=ratelimit` on codex → codex seats excluded with `probe failed`; `--write` file equals stdout JSON.
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** `roster.py` (stdlib only: json, os, shutil, subprocess, re, datetime) and the 3-line `roster.sh` wrapper (`exec python3 "$HERE/lib/roster.py" "$@"`).
- [ ] **Step 4: Run `run-tests.sh roster` → green; then the full suite.**

---

### Task 3: Adapters — `rev-seat.sh` dispatches on the roster

**Files:**
- Modify: `$P/scripts/rev-seat.sh`; Create: `$P/scripts/seats.d/codex.sh`, `seats.d/grok.sh`, `seats.d/gemini.sh`; Modify: `$P/scripts/lib/stream-summary.py` (add `gemini`), `$P/scripts/lib/codex-review-to-findings.py` (no change expected)
- Modify: `$P/tests/t-seat.sh`, `t-seat2.sh`, `t-cxreview.sh`, `t-grok-notools.sh`; Create: `$P/tests/t-gemini.sh`

**Interfaces:**
- Consumes: `<session>/roster.json` (Task 2 shape). `rev-seat.sh <seat> <session> <round> <prompt> [--effort e] [--base ref]` looks the seat up; unknown seat or missing roster → exit 1 with `run preflight first`. Tests write a roster.json fixture into the session dir by hand (do not call roster.sh).
- Produces: adapter contract — `seats.d/<adapter>.sh` is executed with env `SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE` and must: run the CLI read-only from `$ROOT`, stream to `$RAW` and summarise into `$LOG` via `python3 "$LIB/stream-summary.py" <adapter> "$OUT"`, leave findings JSON at `$OUT`, exit with the CLI's code. Exact invocations: spec §5 table. Codex `MODE=review` → prose converted by the wrapper (existing logic). Gemini: `gemini -p "Follow the instructions on stdin exactly. Run your tools first — never answer before reading the code. Answer with only the JSON object requested." -m "$MODEL" --approval-mode plan -o stream-json < "$PROMPT"` from `$ROOT`; `stream-summary.py gemini` prints `tool_call <tool_name>: <command or path>` for `tool_use` events, `text:` for assistant messages, `end status=…` for `result`, and writes to `$OUT` the outermost `{…}` found in the last assistant message (fence-stripped) — the fixture `tests/fixtures/gemini-stream.ndjson` is the reference shape (assumed from the CLI's documented `stream-json`; say so in a comment).
- The wrapper keeps: validation, `.exit`, one-line summary, retry-on-zero-tool-calls for grok AND gemini, CLI-only failure classification, `REV_ACTIVE=1` export, effort from the roster when `--effort` is absent (`REV_CODEX_EFFORT`/`REV_GROK_EFFORT` still override).

- [ ] Port the existing tests to write `roster.json` first; add `t-gemini.sh` (ok → exit 0 findings=1 + `tool_call run_shell_command` line in log; notauth → 3; ratelimit → 4; empty → 2; badjson → 2; notools → retried then 2; prompt on stdin; `--approval-mode plan`; `cwd` = root via `args.env`).
- [ ] Implement, run `run-tests.sh seat`, `cxreview`, `grok_notools`, `gemini`, then the full suite.

---

### Task 4: Preflight, prompt, state, status, squash — port + roster + compat

**Files:** `$P/scripts/rev-preflight.sh`, `rev-prompt.sh`, `rev-state.sh`, `rev-status.sh`, `rev-squash.sh`, `scripts/lib/validate-findings.py`; tests `t-preflight.sh`, `t-preflight2.sh`, `t-scopeenv.sh`, `t-status.sh`, `t-squash.sh`, `t-state.sh`, `t-validate.sh`, `t-runner.sh`.

**Interfaces:**
- `rev-preflight.sh [--scope …] [--write <S>]` now: after the git checks, runs `"$HERE/roster.sh" --probe --write "$S/roster.json"` (only with `--write`; without it `--json` to a temp file) and refuses with `preflight: only N seats available (need 3): <excluded reasons>` on exit 5; on success prints the `base=…` line, then the `--brief` roster line, and writes `scope.env` (single-quoted), `files.txt`, `untracked.txt`, `roster.json`. The old hardcoded `codex login status`/`grok models` checks are removed (the roster owns sign-in). Tests use the shims and `REVIEW_COUNCIL_CODEX_MODELS_CACHE`.
- `rev-status.sh` reads seats from `state.json` as before (the orchestrator copies `roster.seats` names into state); replace `os.stat` usage is fine (python) — but any bash `stat -f` in these scripts/tests goes through `compat.sh`.
- Everything else unchanged; just make the ported tests pass here (paths, `$STACK`, compat).

---

### Task 5: Skills, policy, agent, guard

**Files:** `$P/skills/rev/SKILL.md`, `$P/skills/rev/POLICY.md` (new), `$P/skills/stack/SKILL.md`, `$P/agents/rev-reviewer.md`, `$P/scripts/lib/readonly-bash-guard.py` (unchanged), tests `t-guard.sh`, `t-guard2.sh`, `t-skill.sh`.

**Interfaces:**
- `skills/rev/SKILL.md` frontmatter `name: rev`; body references scripts as `${CLAUDE_PLUGIN_ROOT}/scripts/...`, the agent as `subagent_type: "review-council:rev-reviewer"`, the stack as `/review-council:stack`. Fan-out reads `$S/roster.json`: launch every non-extra seat (adapters via `rev-seat.sh`, the `agent` adapter via the Agent tool) in one message; extras join in their `round`. Lens assignment: the round's emphasis list from the round-plan table, assigned round-robin over the roster's seats with an offset equal to the round number (write the rule and a worked example for 3, 4 and 6 seats). Everything else inherited from the ported text (keep the failure table, stack-leg rules, status tick, ledger, report).
- `POLICY.md`: ≤ 12 lines, the standing rules the hook injects (see spec §3).
- `skills/stack/SKILL.md`: `name: stack`; launch line `${CLAUDE_PLUGIN_ROOT}/scripts/stack.sh <config>`; legs run `/review-council:rev`.
- `agents/rev-reviewer.md`: hook command `${CLAUDE_PLUGIN_ROOT}/scripts/lib/readonly-bash-guard.py`; body unchanged.
- `t-skill.sh`: assert no `~/.claude/skills` / `review-via-cursor` / `rev-stack.sh` strings under `$P`, every `${CLAUDE_PLUGIN_ROOT}/scripts/<x>` referenced in the skills exists, the agent hook path exists, POLICY.md ≤ 12 lines and mentions `/review-council:rev`.

---

### Task 6: Session-start hook

**Files:** `$P/hooks/hooks.json`, `$P/hooks/session-start` (bash, executable), `$P/tests/t-hook.sh`.

**Interfaces:**
- `hooks.json`: `SessionStart` with matcher `startup|clear|compact`, command `"${CLAUDE_PLUGIN_ROOT}/hooks/session-start"`.
- `session-start`: no external deps beyond bash/python3; reads `${CLAUDE_PLUGIN_ROOT}/skills/rev/POLICY.md`, runs `${CLAUDE_PLUGIN_ROOT}/scripts/roster.sh --brief` (cheap detection only; never `--probe`; 5 s cap via python timeout inside roster.py or `--brief` never blocking), and prints `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"<policy>\n\n<roster line>"}}` with proper JSON escaping (use python3 `json.dumps` — no hand escaping). Exit 0 always; if the roster fails, the line says `review-council seats: roster unavailable (<reason>)`.
- `t-hook.sh`: run with `CLAUDE_PLUGIN_ROOT=$P` and shims on PATH: output parses as JSON, contains the policy's first line and a `review-council seats:` line; with no shims on PATH it still exits 0 and reports `not installed`.

---

### Task 7: Stack orchestrator port

**Files:** `$P/scripts/stack.sh` (from `rev-stack.sh`), `$P/scripts/stack.example.sh`, `$P/tests/t-stack.sh`.

**Interfaces:**
- `REV_SCRIPTS` default = the script's own directory. `wait_for_auth` → `"$REV_SCRIPTS/roster.sh" --brief >/dev/null` exit 0 (≥3 seats). Leg command: `claude -p "/review-council:rev branch $rounds — use $S as the session dir. …"`. `stat -f`/`newest_mtime` via `compat.sh`. Everything else (detach, one detector with re-checks, report.md receipt, failure tracking, decoupled squash/push) unchanged.
- `t-stack.sh`: port (`$STACK/stack.sh`), keep every case incl. detach, noreport, slowstart, failures, squash refusal.

---

### Task 8: README and docs

**Files:** `README.md`, `CHANGELOG.md`, `docs/seats.md`, `docs/config.md`.

- README (≤ 200 lines): what it is (one paragraph), install (both ways), what happens at session start, `/review-council:rev` usage and the round loop in five lines, the 10-minute status line, `/review-council:stack` in five lines, the seat roster table (labs, CLIs, models, efforts, how detection works, the Gemini caveat), the read-only guard's security model in three lines, requirements (bash, python3, git, at least three seats), development (`tests/run-tests.sh`, CI, shims), and a "why" paragraph (decorrelation). `docs/seats.md`: the adapter contract and how to add a lab (one adapter, one shim, one fixture, one test). `docs/config.md`: the config file keys and env overrides. `CHANGELOG.md`: `0.1.0`.

---

### Task 9 (controller): validate, install locally, live checks, publish, retire the local copy

Per spec §10 L1–L5 and §9; not delegated.
