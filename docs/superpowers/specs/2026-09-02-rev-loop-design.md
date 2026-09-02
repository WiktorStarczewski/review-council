# rev — multi-model review-and-fix loop (design)

Date: 2026-09-02
Status: approved design, pre-implementation
Replaces: `~/.claude/skills/review-via-cursor/`, Cursor's `~/.cursor/skills/rev/`
Rewrites: `~/.claude/skills/review-stack/`

## 1. Goal

Move the multi-model review loop out of Cursor and into Claude Code, driving the
Codex and Grok CLIs directly. Keep what made the Cursor loop worth running —
decorrelated frontier reviewers at maximum effort, a verified ledger, fixes
applied and re-verified per round — and drop what only existed because the loop
ran headless in someone else's harness (stall guards, reconnect-loop detection,
push blocking).

The orchestrator is the calling Claude session. Reviewers never edit.

## 2. Surface

One user-invocable skill, `rev`, at `~/.claude/skills/rev/`.

```
/rev [scope] [rounds] [--read-only]
```

| Arg | Values | Default |
|---|---|---|
| scope | `branch`, `uncommitted`, a path, a PR number/URL, a branch name | `branch` |
| rounds | integer minimum | `7` |
| `--read-only` | findings only, no fixes, no commits | off |

Routing:

- Code (branch, PR, uncommitted, path under a git repo) → the loop (§4).
- The read-only panel (§7) when `--read-only` is given, or when the scope is a
  document: a `.md`/`.txt`/`.rst` path, or the user names a plan, design doc,
  or prose.
- Nested call (`REV_ACTIVE` set) → refuse. The orchestrator exports
  `REV_ACTIVE=1` into every seat it launches, so nothing downstream of a review
  can start another one. Stack legs are marked `REV_STACK_LEG=1` instead (they
  must run `/rev`); `review-stack` refuses to start when either variable is
  set, so a leg can never launch a stack.

`review-stack` remains its own skill (§8); it drives `/rev` in headless legs.

## 3. Session directory

Created by the orchestrator at `/tmp/rev-<epoch>` unless the invocation names
one ("use S as the session dir" — the stack passes this). Contents:

```
00-baseline.patch        git diff <base> at setup; recovery + review artefact
baseline.md              gate status before round 1 (build/test/lint, pass/fail + failing names)
findings.md              the ledger (§6)
r<N>-<seat>.prompt.md    exact prompt sent to a seat
r<N>-<seat>.json         seat output, schema-valid (§5.2)
r<N>-<seat>.log          seat event stream (§5.4); the status tick reads its tail
r<N>-<seat>.exit         seat exit code, written when the seat finishes
state.json               orchestrator phase, written at every transition (§9.1)
report.md                final report (§9.2); the stack orchestrator reads it
```

## 4. The loop

### 4.1 Setup (once)

1. Preflight (`scripts/rev-preflight.sh`, §5.4). Refuses on empty scope, shared
   branch, missing sign-in, or recursion.
2. Resolve and pin the scope. A PR number/URL → `gh pr checkout` first; a
   branch name → check it out; a path → the branch diff restricted to that
   path. Base = `git merge-base HEAD <default-branch>` for `branch`, PR, branch
   name and path; `HEAD` for `uncommitted`. Every round diffs against this
   pinned SHA — never re-derived, because rounds commit and `uncommitted` would
   shrink to nothing. Create the session dir and write the initial `state.json`
   (`rev-state.sh`, §5.4).
3. Write `00-baseline.patch` and `baseline.md`. Run the repo's build, tests and
   linters; record what passes and what already fails.
4. Read the diff yourself. The orchestrator triages, so it needs its own model
   of the change before seeing any reviewer's.
5. Open `findings.md`. Todo list with one item per planned round.

### 4.2 Round

```
fan out → collect → triage → fix → verify → commit → record
```

**Fan out.** All seats launch in ONE message: codex and grok seats via
`rev-seat.sh` with `run_in_background: true`, the opus seat via the Agent tool
(`subagent_type: rev-reviewer`). Each seat gets its own prompt file (§5.3). The
status tick (§9.1) is armed once, before round 1, and stopped after the report.

**Collect.** Wait for every seat. A seat that exits non-zero or produces invalid
JSON is retried once, one step lower on its effort ladder (§5.1). A seat that
reports a usage cap (exit 4) is dropped for the rest of the run and named in the
report. A round needs ≥3 seats' output to proceed; with fewer, stop the loop and
say so. Never fall back to self-review and call it reviewed.

**Triage.** Merge into the ledger. Deduplicate across seats and record how many
found it (agreement is signal, not proof). Open the file and verify every claim
before acting — reviewers hallucinate line numbers and invent APIs; unverifiable
→ `REJECTED (unsubstantiated)`. Assign severity:

| | Meaning |
|---|---|
| P0 | Incorrect behaviour, security hole, data loss, crash |
| P1 | Real bug on a reachable path, bad edge case, broken contract |
| P2 | Maintainability, performance, missing test, unclear API |
| P3 | Nit, style, naming, comment |

**Fix.** P0 → P1 → P2; P3 only when trivial and safe. Match surrounding style;
do not reformat untouched code. Conflicting findings are resolved explicitly in
the ledger. A finding that is wrong or out of scope is `REJECTED` with a reason —
rejecting is a valid outcome.

**Verify.** Re-run build, tests, linters. Compare to `baseline.md`; pre-existing
failures are not regressions. A fix that breaks something is repaired or reverted
before the next round. Never advance on a broken build.

**Commit.** Only after verification passes, only if the round changed files.
Stage what the round touched (the session dir is outside the repo). No push.

```
fix(rev): round 3 — retry logic and leaked handles

F-012 P1  retry loop re-sent 4xx requests, duplicating writes
F-014 P2  file handle leaked on the error path
```

No AI attribution anywhere. Never force-push, never skip hooks, never amend.

**Record.** Append the round to the ledger: seats and efforts used, lenses,
findings by severity, fixed/rejected counts, verification result, commit SHA.

### 4.3 Round plan and lenses

Carried over from Cursor's `/rev` unchanged:

| Round | Emphasis | Extra seat |
|---|---|---|
| 1 | Correctness, edge cases, error handling | — |
| 2 | Security, data & state | `codex-review` (native `codex exec review`) |
| 3 | Concurrency, resources, performance | `grok-code-review` (bundled maintainability skill) |
| 4 | API & contract, compatibility | — |
| 5 | Tests, observability | — |
| 6 | Red team | reviewers argue the change is broken |
| 7 | Regression + full cumulative diff re-read | — |

Lens catalog: correctness, security, edge cases, error handling, concurrency,
resources, API & contract, data & state, performance, tests, observability,
readability, red team, regression. Every lens is covered at least once per run.
Model↔lens pairing rotates each round.

**Vacuity primer.** Whenever the diff adds or edits tests, every seat's prompt
includes: check every touched assertion for vacuity — would it still pass if the
behaviour it names were deleted? Name the production change that would make each
new test fail; report any that has none. Watch for `.all()`/`.every()` over a
possibly-empty query, before/after read from a copying accessor, expected value
recomputed via the path under test, `expect.anything()` in the new argument's
slot, a success path that never executes.

### 4.4 Extension and termination

Keep going past the minimum while any hold: last round produced a new P0/P1;
last round's fixes were more than trivial; any P0/P1 is open; a lens or a major
changed file is unreviewed.

Stop when all hold: minimum rounds ran; two consecutive rounds produced no new
P0/P1; no P0/P1 open; gates at or better than baseline. Stop early only on empty
scope or user instruction. Still finding P0s at high round counts → say so
plainly; that is a rework signal, not a patching signal.

### 4.5 After the loop

1. `scripts/rev-squash.sh` (dry run, then `--apply`) collapses the contiguous
   `fix(rev)` run at the tip into one `apply review findings` commit. Count is
   computed, boundary asserted (`HEAD~n` must be the pushed state or the base).
   A run broken up by other commits is left alone — PR squash-merge is the real
   collapse.
2. Push once, so CI runs on what reviewers will see.
3. Write `report.md` and report (§9).

Skipped when `REV_STACK_LEG=1` (the stack squashes and pushes per repo, §8).

## 5. Seats

### 5.1 Roster

| Seat | Command | Effort ladder (top first) |
|---|---|---|
| `codex-sol` | `codex exec -m gpt-5.6-sol -s read-only` | max → xhigh → high |
| `codex-terra` | `codex exec -m gpt-5.6-terra -s read-only` | max → xhigh → high |
| `grok` | `grok --prompt-file <file> -m grok-4.6 --permission-mode plan` | xhigh → high |
| `opus` | Agent tool, `subagent_type: rev-reviewer` | max (frontmatter) |
| `codex-review` | `codex exec review --base <base>` — codex's own review prompt, our schema (round 2 extra) | max → xhigh |
| `grok-code-review` | `grok --prompt-file` with the bundled `/code-review` skill (round 3 extra) | xhigh → high |

Rules:

- `codex-review` (`codex exec review --base`) refuses custom instructions AND ignores
  `--output-schema`: it runs codex's own review prompt and answers in prose
  (`- [Pn] title — path:a-b` blocks). `lib/codex-review-to-findings.py` converts that
  into the schema; the prose is kept as `r<N>-codex-review.native.txt`.
- Top frontier model per lab; never a mid tier (`gpt-5.6-luna`, `grok-4.5`,
  `gpt-5.4*`, `spark` are excluded). `fable` is excluded by decision — it shares
  the orchestrator's weights.
- Codex `ultra` is not used by default (it delegates to subagents, opaque to us).
  Opt in with `REV_CODEX_EFFORT=ultra`.
- Re-check availability every run: `~/.codex/models_cache.json` (slugs and
  `supported_reasoning_levels`) and `grok models`. Step down the ladder on the
  same model before substituting a model. Never invent a slug.
- Four seats launched per round (§5.6 lets a round complete with three). If the
  roster is wider than four, run a frontier model twice on different lenses
  rather than seat a weaker one.

### 5.2 Output schema

`~/.claude/skills/rev/schema/findings.schema.json`, `additionalProperties:false`:

```json
{
  "summary":  "string — two or three sentences, ship/no-ship tone",
  "findings": [{
    "severity":      "P0 | P1 | P2 | P3",
    "file":          "repo-relative path",
    "line_start":    "integer ≥ 1",
    "line_end":      "integer ≥ 1",
    "claim":         "what is wrong, one sentence",
    "evidence":      "what in the code shows it — independently read, not inherited",
    "suggested_fix": "concrete change",
    "confidence":    "number 0–1"
  }]
}
```

Every seat produces exactly this. Codex via `--output-schema <file>` and
`-o <json-out>`; grok via `--json-schema '<inline>'` with
`--output-format streaming-json` (the wrapper extracts `.structuredOutput` from
the final `end` record); opus returns it as its final message and the
orchestrator writes `r<N>-opus.json`.

### 5.3 Seat prompt

Written by the orchestrator to `r<N>-<seat>.prompt.md`, passed as a file (codex:
`codex exec … - < file`, stdin IS the file and hits EOF; grok: `--prompt-file`
with stdin from `/dev/null`; opus: the Agent prompt). Contains:

1. Role: one of several independent reviewers; report only what you can
   substantiate from the code; read surrounding code, not just the diff; reason
   exhaustively, depth over speed.
2. Repo root, pinned base SHA, the changed-file list, and the command to
   produce the diff (`git diff <base>`), which the seat runs itself.
3. Its lens for this round, and the round's emphasis.
4. Baseline gate status (so pre-existing failures are not reported as findings).
5. The ledger's `REJECTED` findings with reasons, so they are not resurfaced.
6. The vacuity primer when tests are touched (§4.3).
7. For grok only, first: "Run your tools before answering; never answer before
   you have read the code" — `--json-schema` otherwise answers on turn one.
8. The output contract: JSON only, the schema, severity definitions, one strong
   finding beats several weak ones, no style feedback unless P3 and trivial.

### 5.4 Scripts

**`scripts/rev-seat.sh <seat> <session-dir> <round> <prompt-file> [--effort <e>]`**

The one place CLI quirks live. Responsibilities:

- Resolve the repo root (`REV_REPO` or `git rev-parse --show-toplevel`).
- Codex: `codex exec --ephemeral -s read-only -C <root> -m <model>
  -c model_reasoning_effort=<e> --json --output-schema <schema> -o <out.json>
  - < <prompt>` (plus `--skip-git-repo-check` when `<root>` is not a git repo,
  i.e. a read-only panel on a document). `--json` streams JSONL events
  (`item.started`/`command_execution` carries the command being run) to the
  `.log`; `-o` still receives the final schema-valid message. `codex-review`
  uses `codex exec review --base <base>` with the same flags and the prompt as
  custom instructions.
- Grok: `grok --prompt-file <prompt> --cwd <root> -m grok-4.6
  --reasoning-effort <e> --permission-mode plan --output-format streaming-json
  --json-schema "$(cat <schema>)" --max-turns <n>`. NDJSON goes to the `.log`
  (`tool_call` events carry `title`/`toolName`); the final `{"type":"end"}`
  record carries `structuredOutput`, which the wrapper extracts to the `.json`.
  `grok-code-review` prefixes the prompt with `/code-review`.
- Never leave stdin as an open pipe: codex reads it until EOF and blocks (the
  prompt file provides the EOF); grok gets `</dev/null`.
- Export `REV_ACTIVE=1` into the seat's environment.
- Write `<session>/r<N>-<seat>.json`, `.log`, and `.exit`.
- Validate the JSON against the schema (python3 + a minimal check; no new deps).
- Exit codes: `0` valid; `2` missing/invalid JSON; `3` not signed in; `4` usage
  cap or rate limit detected in the log (`usage limit`, `rate limit`, HTTP 429);
  `1` anything else. Print one line: `seat=<s> round=<n> exit=<c> findings=<k>`.

**`scripts/rev-state.sh <session-dir> key=value…`** — merges the given keys
into `state.json` (dotted keys for nesting: `open.P1=1`; JSON literals for
lists), creating it if absent. Keeps the orchestrator's transitions to one
short command each.

**`scripts/rev-preflight.sh`** — exits non-zero with a one-line reason on:
empty scope (`git status --porcelain` and `git diff --stat <base>` both empty);
HEAD on `main`/`master`/the default branch; `REV_ACTIVE` set; codex not signed
in (`codex login status`); grok not signed in (`grok models`). On success prints
base SHA, branch, changed-file count, and the seats available with their top
effort.

**`scripts/rev-squash.sh [--apply]`** — carried over; single repo by default,
`REPOS`/`REPO_ROOT` for a stack. Title pattern matches `^fix(rev)` and the
existing variants. Computes the count, asserts the boundary.

### 5.5 `rev-reviewer` agent

`~/.claude/agents/rev-reviewer.md`:

```yaml
name: rev-reviewer
description: One seat on the /rev review panel. Read-only; returns findings JSON.
model: opus
effort: max
tools: Read, Grep, Glob, Bash, LSP
disallowedTools: Write, Edit, NotebookEdit
maxTurns: 80
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: ~/.claude/skills/rev/scripts/lib/readonly-bash-guard.py
```

(`permissionMode: plan` is not used: the user's `defaultMode: auto` overrides a
subagent's frontmatter mode, so tool restriction plus the PreToolUse guard is the
fence: the guard blocks write-shaped Bash — git state changes, redirections,
in-place edits, installs, snapshot updates — while allowing diff/log/show/rg/cat
and test runs.) Body: reviewer
persona, the JSON contract, "never edit, never run anything that writes", and
the instruction to verify line numbers by opening files.

### 5.6 Failure handling

| Failure | Action |
|---|---|
| Seat exit 2 or 1 | Retry once, one effort step lower. Then drop for this round. |
| Seat exit 3 | Stop the run; report which tool needs sign-in. |
| Seat exit 4 | Drop the seat for the rest of the run; continue if ≥3 seats remain. |
| <3 seats in a round | Stop; say so. Do not self-review and call it reviewed. |
| Fix breaks a gate | Repair or revert before the next round. |
| Squash boundary assertion fails | Leave history as is; say so. |

## 6. Ledger

`findings.md`, one entry per finding:

```markdown
## F-012 · P1 · FIXED
File:     src/api/handler.ts:88
Found by: round 3 — codex-terra@max, opus@max (2/4)
Claim:    Retry loop re-sends the request after a 4xx, duplicating writes.
Verified: yes — handler.ts:88, no status check before retry.
Action:   Fixed in round 3 (a1b2c3d) — retry only on 5xx and network errors.
```

Status ∈ `OPEN | FIXED | REJECTED (reason) | DEFERRED (reason)`. Every finding
ends in one of them. Round entries append below.

## 7. Read-only panel

For plans, docs, prose, and code with `--read-only`. Same seats, same schema,
same prompt structure; the "scope" is the file list instead of a diff, `file`
is the document path and `line_start`/`line_end` are document lines. The
`rounds` argument applies; one round by default. Triage still verifies each
claim against the document. No fixes, no commits. Report as §9.2 minus commits.
The standing "apply actionable findings" rule then applies to the orchestrator
after reporting, per the user's global CLAUDE.md.

## 8. review-stack

Same phases as today (per-PR legs ×2 passes, cross-repo seam review,
completeness critic), same leg premises, same dependency ordering. What changes:

**Leg launch** (inside `run_leg`):

```bash
( cd "$dir" && REV_STACK_LEG=1 \
  claude -p "/rev branch $rounds — use $S as the session dir. ${PREMISE} ${VACUITY} ${extra}${resume}" \
    --permission-mode bypassPermissions --effort max \
    --output-format stream-json --verbose </dev/null > "$S/run.log" 2>&1 ) &
```

No `--bare` (it drops user skills, verified). No `--model` (inherits the user's
default). `--verbose` is required for `stream-json` in print mode.
`REV_STACK_LEG=1` makes the leg skip §4.5 and makes `review-stack` refuse to
nest; the orchestrator runs `rev-squash.sh --apply` and pushes once per repo
after all phases (`NO_PUSH=1` to skip). `rev-stack.sh` itself refuses to start
when `REV_ACTIVE` or `REV_STACK_LEG` is set.

**Liveness.** `stream-json` writes an event per assistant message and tool
call, so `run.log` mtime is a real liveness signal. ONE detector, in `run_leg`:
`idle = now − max(run.log mtime, newest session-dir mtime)`; kill only if
`idle ≥ STALL_SECS` (default 1800) AND the claude process's CPU time did not
move across a 45 s sample. Four attempts per leg, with resume text pointing at
the existing `findings.md`. Fast failure (<90 s) counts as infrastructure and
sleeps 300 s, up to 12 times.

**Status.** Every 10 minutes `run_leg` appends one line to `/tmp/rev-stack.log`:
`[HH:MM] <leg> pass<N> attempt<a> | <rev-status.sh one-liner for the leg's
session dir> | idle=<s>s cpu=<t>(moving|frozen) commits=<n>`. The session that
launched the stack arms `Monitor` on `tail -f /tmp/rev-stack.log` filtered to
status and transition lines, and relays each to the user (§9.1). The
standalone `rev-stall-guard.sh` and `rev-status-tick.sh` are deleted.

**Auth wait.** `codex login status` and `grok models` both succeed, up to 60
minutes, before each leg.

**Dropped.** `push-block.sh` — nothing pushes mid-loop any more.

## 9. Reporting

### 9.1 Status tick — every 10 minutes, unprompted

The user is told every 10 minutes what each seat is doing or has done and where
the loop stands, without asking.

**State file.** The orchestrator writes `state.json` at every transition:

```json
{"round": 3, "min_rounds": 7, "phase": "fan-out | collect | triage | fix | verify | commit | squash | done",
 "seats": ["codex-sol","codex-terra","grok","opus"],
 "open": {"P0": 0, "P1": 1, "P2": 3}, "fixed": 6, "rejected": 2,
 "last_commit": "a1b2c3d", "started_at": "<iso>", "opus_transcript": "<path or null>"}
```

**`scripts/rev-status.sh <session-dir>`** prints ONE line, no more than ~200
characters, built only from files in the session dir:

```
r3/7 triage | sol: done 4f 9m | terra: done 2f 11m | grok: running 14m ← rg "retry" src/api | opus: done 3f 8m | open P0:0 P1:1 P2:3 fixed 6
```

Per seat: `done <k>f <t>m` (from `.json` + `.exit`), `running <t>m ← <last
action>` (last `command_execution`/`tool_call` line in the `.log`, truncated to
40 chars), `failed exit=<c>` (from `.exit`), or `dropped` (usage cap). The opus
seat's last action comes from its Agent transcript when `opus_transcript` is
set: `grep -o '"name":"[A-Za-z]*"' | tail -1` — nothing else is read from that
file. Overall from `state.json`.

**Timer.** Before round 1 the orchestrator arms one `Monitor`
(`persistent: true`, description `rev status <session>`):

```bash
while true; do sleep 600; ~/.claude/skills/rev/scripts/rev-status.sh <session>; done
```

Each emitted line arrives as an event; the orchestrator relays it to the user
as-is plus at most one sentence of context (what it is doing right now). The
monitor is stopped with `TaskStop` after the final report. If the loop stops
early, the last relayed line says why.

**Stack.** Legs run headless, so their own ticks are invisible; `rev-stack.sh`
writes the same one-liner into `/tmp/rev-stack.log` every 10 minutes (§8), and
the launching session's `Monitor` on that log relays it.

### 9.2 Per round and final

Per round: two or three sentences — round number, seats, new findings by
severity, what was fixed, verification result, commit SHA.

Final (`report.md` and in chat):

1. Outcome, in prose, first: what was wrong and whether the change is sound now.
2. Findings table: ID, severity, location, claim, resolution, sorted by severity.
3. Rejected findings with reasons.
4. Coverage: rounds, seats and efforts, lenses, gate status, seats that dropped.
5. Commits: one line per round commit; the squash commit; the push.
6. Residual risk: deferred, untestable, worth a human look.

Say plainly if P0s were still appearing in late rounds.

## 10. Files

Create:

```
~/.claude/skills/rev/SKILL.md
~/.claude/skills/rev/schema/findings.schema.json
~/.claude/skills/rev/scripts/rev-seat.sh
~/.claude/skills/rev/scripts/rev-preflight.sh
~/.claude/skills/rev/scripts/rev-status.sh
~/.claude/skills/rev/scripts/rev-state.sh
~/.claude/skills/rev/scripts/rev-squash.sh        (moved from review-via-cursor, pattern updated)
~/.claude/agents/rev-reviewer.md
```

Rewrite:

```
~/.claude/skills/review-stack/SKILL.md
~/.claude/skills/review-stack/scripts/rev-stack.sh
```

Delete:

```
~/.claude/skills/review-via-cursor/                (SKILL.md, rev-stall-guard.sh, rev-status-tick.sh, rev-squash.sh)
~/.claude/skills/review-stack/scripts/push-block.sh
```

Update:

- `~/.claude/CLAUDE.md` "Review workflows": `review-via-cursor` → `rev`; the
  loop is in-harness; codex/grok are the decorrelated seats; reviews still never
  substitute the orchestrator's own reading for the panel.
- `~/.claude/skills/verification-panel/SKILL.md` description: "use
  review-via-cursor" → "use rev".
- Memory: delete `codex-rescue-model-access-broken.md` (codex works under the
  ChatGPT login); replace with a `rev-toolchain` reference note (CLI versions,
  the stdin and json-schema gotchas); update `MEMORY.md`; note in
  `decision-profile.md` that on 2026-09-02 he chose the full review-stack port
  over a staged follow-up.

Cursor is not touched. `~/.cursor/skills/rev/SKILL.md` stays as-is for reference.

## 11. Testing

On a throwaway branch `rev-selftest` in the wallet repo, carrying a planted
off-by-one in a small pure helper plus a vacuous test for it:

| # | Check | Pass criterion |
|---|---|---|
| T1 | `rev-preflight.sh` on `main` | exit ≠ 0, reason names the branch |
| T2 | `rev-preflight.sh` on `rev-selftest` | exit 0, prints base SHA and ≥4 seats |
| T3 | `rev-seat.sh` for each of the six seats, round 1, correctness lens | exit 0, JSON validates, ≥1 seat's findings name the planted line |
| T4 | Seat with a bogus effort | exit ≠ 0 and the retry path steps down |
| T5 | `/rev branch 2` in this session | planted bug fixed, vacuity reported, 1–2 `fix(rev)` commits, gates green, `rev-squash.sh` dry run shows the run |
| T6 | `rev-stack.sh` with one leg on the same branch, `STALL_SECS=600` | leg completes, no false kill, status lines present, `report.md` written |
| T7 | `REV_ACTIVE=1 claude -p "/rev branch 1"`; `REV_STACK_LEG=1 rev-stack.sh` | both refuse with the recursion message |
| T8 | `REV_STACK_LEG=1` leg | no push, no squash; orchestrator squash + push works afterwards (push to a throwaway remote branch, then deleted) |
| T9 | `rev-status.sh` mid-fan-out (during T5) and after | one line, every seat present with running/done/failed state and a last action for running seats, overall counts match `state.json` |
| T10 | `Monitor` armed during T5 | at least one status event relayed to the user during the run; stopped after the report |

Branch and remote branch deleted after T8.

## 12. Non-goals

- A Gemini seat (no current-generation Pro CLI on this box).
- Fable on the panel.
- Per-round pushes, PR comment posting, GitHub review submission.
- Keeping Cursor as a fallback.
- Cost accounting beyond what the CLIs print.
