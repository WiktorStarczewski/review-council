## Setup (once)

Before running repository checks, read its instructions, CI workflows and request
helper. Follow its configured runner routing and guarded local fallback policy.
Keep existing runner assignments and local guards when checks queue. This applies
to baseline, fix, mutation and final verification commands.
Run the required gates within the user's authorized scope; keep optional full
suites and E2E opt-in. For manual-only CI, use the documented helper or explicit
dispatch with the selected checks and exact source revision. A push alone is not
a CI request. Record the run URL, tested revision and result; a queued, skipped or
absent check is not a pass. Preserve required merge gates and report blockers.

Configuration lives at `~/.config/review-council/config.json` or the path in
`REVIEW_COUNCIL_CONFIG`. The optional `quota_fallback` boolean and `plan_seats` value
are shared with the Codex host. `claude_adapter` (`cli`, `agent`, or `auto`, default
`auto`; `REVIEW_COUNCIL_CLAUDE_ADAPTER` wins) picks how this host seats Claude rows:
`cli` uses adapter `claude`, the `claude -p` CLI launched through `rev-seat.sh`;
`agent` uses `Agent` subagents; `auto` uses `claude` when that CLI is installed and
signed in, else `agent`. Each roster row records its `adapter`, so a session keeps its
preflight choice.

1. Resolve the scope. PR number/URL: `gh pr checkout <n>`, then save the author's own
   description for the seats: `gh pr view <n> --json title,body --jq '"# " + .title + "\n\n" + .body' > $S/pr.md`.
   For a branch or path scope, try the same with `gh pr view` (no number) and ignore failure.
   `$S/pr.md` is for you (triage, scope decisions); do **not** pass `--pr $S/pr.md` to seat
   prompts by default - measured, it anchors reviewers on the author's framing and loses
   findings. Pass it only when the user asks for it. Branch name: `git checkout
   <name>`. Then canonicalize the session once so macOS `/tmp` and `/private/tmp`
   share one manifest identity:
   ```bash
   mkdir -p "$S"
   S=$(cd "$S" && pwd -P)
   ```
   Before any preflight or provider probe, classify a code session by inspecting
   `scope.env`, `files.txt`, `untracked.txt`, and `roster.json` with `lstat`:

   - `fresh`: none of the four inputs exists, so preflight may run once
   - `initialized`: all four safe inputs exist, so validate and reuse them without probing
   - `invalid`: a partial or unsafe set exists, so stop incomplete and use a fresh session

   For `initialized`, import `validate_standard_inputs` from
   `${CLAUDE_PLUGIN_ROOT}/scripts/lib/session_inputs.py`, call
   `validate_standard_inputs(Path(S), require_all=True)`, and continue with those exact
   bytes. Never rerun preflight or repair inputs in that session. Any validation failure
   makes the state `invalid`; preserve that session untouched and choose a fresh session
   before retrying. Only `fresh` runs. Before that preflight, run:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-panel-request.py --text "<the user request>" --session "$S" --base "${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}"
   ```
   A printed path is `$S/roster-config.json`. Pass it as `REVIEW_COUNCIL_CONFIG` for this preflight only. Do not edit the user's config. A non-zero exit is fatal: relay it and do not preflight. Then:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-preflight.sh --scope <branch|uncommitted|path> --write $S [--pr <number>]
   ```
   For an open PR review, pass `--pr <number>`. This binds the scope to the live PR
   number, branch, head SHA and base head SHA. It refuses a closed PR, mismatched or
   dirty checkout, or a local base ref that does not match GitHub. Fetch the exact
   refs into a clean worktree before preflight, then retry only with a fresh session.
   Do not replace a refused PR-bound preflight with an unbound branch review. Do not
   combine `--pr` with an explicit `--base`.
   The default mode is normal: four Luna seats, or four Cursor Grok seats when this host is Cursor and the SDK can seat them. `high effort` selects high: one Opus, one Sol, one Sonnet, and one Luna. An explicit `4*luna` or `4*grok` overrides that preset. `$S/panel-request.json` records the mode and the chain. Every later code panel and the plan panel uses that frozen roster. Do not rebuild it, and do not put the workhorse in those panels.
   For a fresh session, non-zero → relay the one-line reason verbatim. Exit 5 is retryable. Preserve the
   session and retry after the temporary provider availability problem clears. Exit 6 is permanent.
   Stop because the scope or strict roster contract cannot run as asked. A thin
   roster is not one of those; it is
   padded and run. Zero → it printed `base=… base_branch=… (how) branch=… changed_files=…` - check
   `base_branch` (the open PR's base, else the nearest fork point) and re-run with `--base <ref>`
   if it is wrong, since a wrong base reviews someone else's commits - the roster
   line, and, when the panel is degraded, a second line `preflight: WARNING - <sentence>`;
   carry that sentence into the report. After fresh initialization, or immediately for a
   validated initialized session, `$S/scope.env`, `$S/files.txt`, `$S/untracked.txt` and
   `$S/roster.json` exist. Source `scope.env` for
   `REV_BASE`, `REV_ROOT`, `REV_SCOPE`, and `REV_PR_NUMBER` plus `REV_PR_REPO` when
   present - every
   value in it is single-quoted, so a branch name or path with shell metacharacters
   is inert data. Preserve the optional PR number for any quota fallback preflight.
   Arm the recursion guard once preflight has passed (it refuses when `REV_ACTIVE` is
   already set, so arming it earlier would block your own run): from here on every seat
   runs with `REV_ACTIVE=1` in its environment - `rev-seat.sh` exports it itself, and
   each `Bash` call is a fresh shell, so prefix any other seat-side command you run with
   `REV_ACTIVE=1`. Do not run `rev-preflight.sh` again inside this run. An `agent` row
   carries no environment; the clause in its `Agent` prompt (below) is its fence.
2. Baseline patch, scoped exactly as the review is - a path scope must not capture
   the whole branch, and untracked files appear in **no** diff at all:
   ```bash
   case "$REV_SCOPE" in
     branch|uncommitted) git diff $REV_BASE ;;
     *)                  git diff $REV_BASE -- "$REV_SCOPE" ;;
   esac > $S/00-baseline.patch
   # untracked files are listed in files.txt but are invisible to git diff - append them as add-patches
   while IFS= read -r f; do [ -n "$f" ] && git diff --no-index /dev/null "$f" >> $S/00-baseline.patch; done < $S/untracked.txt
   ```
   (`git diff --no-index` exits 1 when the files differ; that is the normal case here.)
   Then run the repo's build, tests and linters (from its CLAUDE.md, `package.json`
   scripts, `Cargo.toml`, `Makefile` - whatever the project uses) and write
   `$S/baseline.md`: one line per gate, `pass` or `fail` with the failing test/lint
   names. Pre-existing failures are not regressions later.
   Optional `$S/baseline.json` uses the [structured baseline format](../../../../docs/cost-accounting.md)
   and replaces `baseline.md` in reviewer prompts. Record every relevant check,
   including applicability, skipped checks and failure evidence.
3. Read the diff yourself - the same command as the baseline patch above, plus every
   file in `$S/untracked.txt` read in full (nothing in a diff will show them). You
   triage; you need your own model of the change before you see anyone else's.
4. State and ledger. The seat list comes from the roster, not from memory:
   ```bash
   SEATS=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps([s['seat'] for s in d['seats'] if not s.get('extra')]))" $S/roster.json)
   ${CLAUDE_PLUGIN_ROOT}/scripts/rev-state.sh $S round=0 min_rounds=<explicit-rounds-or-adaptive> phase=setup "seats=$SEATS" open.P0=0 open.P1=0 open.P2=0 fixed=0 rejected=0 started_at=<iso-now>
   [ -f $S/findings.md ] || printf '# Findings ledger - %s\n\nScope: %s @ %s\n\n' "$S" "$REV_BRANCH" "$REV_BASE" > $S/findings.md
   [ -f $S/rejected.md ] || : > $S/rejected.md
   ```
   **Create, never truncate.** A session dir is reused across passes and retries
   (`/review-council:stack` hands you the same `$S` for pass 2 and for every retry of a
   leg), and `findings.md` is the whole prior verdict. When either file already exists,
   READ it before round 1 and treat its `FIXED` / `REJECTED` / `DEFERRED` entries as
   settled: do not re-raise them, and append this run's entries below the existing
   ones. `>` there would have deleted the ledger the resume note tells seats to read.
   Make a todo list with one item per planned panel.
   At a phase handoff or resume, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rev-context.py "$S"`
   for a compact briefing from current state, exact roster identities and artifacts.
   Follow its references when evaluating a claim; it does not evaluate certification
   or replace collection and receipt checks.
5. Do not arm a 10-minute status monitor unless `$S/state.json` has `"status_tick": true` or the config key `status_tick` is true. By default, wake only on a phase change, a seat failure, or a terminal result, and run `rev-status.sh` then. When the tick is enabled (not in stack-leg mode):
   ```
   Monitor({ command: "while true; do sleep 600; ${CLAUDE_PLUGIN_ROOT}/scripts/rev-status.sh <S>; done",
             description: "rev status <S>", persistent: true, timeout_ms: 3600000 })
   ```
   Every event it emits is relayed to the user (see **Status tick**).
