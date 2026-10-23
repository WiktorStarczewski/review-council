## Locate and set up

Before running repository checks, read its instructions, CI workflows and request
helper. Follow its configured runner routing and guarded local fallback policy.
Keep existing runner assignments and local guards when checks queue. This applies
to baseline, fix, mutation and final verification commands.
Run the required gates within the user's authorized scope; keep optional full
suites and E2E opt-in. For manual-only CI, use the documented helper or explicit
dispatch with the selected checks and exact source revision. A push alone is not
a CI request. Record the run URL, tested revision and result; a queued, skipped or
absent check is not a pass. Preserve required merge gates and report blockers.

Resolve `PLUGIN` to the directory two levels above **this loaded SKILL.md**. Never
assume the shell cwd is the plugin or use `CLAUDE_PLUGIN_ROOT`. All script paths below
are relative to that absolute `PLUGIN`; quote paths and use arrays for arguments.

- Check `REV_ACTIVE` on entry: if set, refuse a nested council.
- Set `REVIEW_COUNCIL_HOST=codex` on **every** runner invocation, including preflight.
  Shell environment changes may not persist between tool calls. All seats in the
  Codex roster are actual external CLI processes, including Anthropic Claude seats.
- Default scope is `branch`; accept `uncommitted`, a path, branch name, PR number or
  URL, or document paths. Resolve PR metadata and base read-only with `gh`; review a
  different branch in an isolated worktree instead of changing a dirty checkout.
  Respect an explicit `--base`. Do not fabricate a base when it cannot be resolved.
- For an open PR review, use `--pr <number>` in preflight. It binds the scope to
  the live PR number, branch, head SHA and base head SHA, and refuses a closed PR,
  mismatched or dirty checkout, or a local base ref that does not match GitHub.
  Fetch the exact base and head refs in a clean worktree before preflight. Do not
  replace a refused PR-bound preflight with an unbound branch review.
- The default code fix loop is adaptive. With the configured four-seat panel, a
  normal review uses eight code-seat launches plus one conditional plan. A large
  or high-risk review uses twelve code-seat launches before fixes: four simplicity,
  four risk-discovery, and four combined red-team/verification launches. An important
  or explicitly adversarial review that is not otherwise large or high-risk uses
  eight before fixes. If any fix follows the combined panel, run four separate
  verification launches; a one-seat plan then gives totals of 17 or 13 respectively.
  With `"plan_seats": "all"`, every plan panel launches
  all four core seats instead of one.
  An explicit round count is a minimum override and exclusively selects the
  legacy numbered schedule. `--read-only` and
  document or plan reviews default to one panel with no edits or commits.
- A change is large with more than 25 changed files or more than 1,500 changed lines.
  It is high-risk when it crosses a security, persistence, concurrency,
  transaction, protocol, public API, or irreversible mutation boundary. Large or
  high-risk changes add risk discovery and the full red-team panel.
- Reuse a requested session directory; otherwise make one with `mktemp -d
  /tmp/rev-XXXXXX`. Call it `S`. Read any existing ledger before continuing. Keep all
  logs, prompts, reviewer outputs, and ledgers there, away from the reviewed files.
- For a code review associated with an open PR, `S` must resolve outside the reviewed repository.
  An unassociated local render may remain inside, but it cannot publish.

Immediately after selecting the session, canonicalize it once. This makes macOS `/tmp` and `/private/tmp`
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
`$PLUGIN/scripts/lib/session_inputs.py`, call
`validate_standard_inputs(Path(S), require_all=True)`, and continue with those exact
bytes. Never rerun preflight or repair inputs in that session. Any validation failure
makes the state `invalid`; preserve that session untouched and choose a fresh session
before retrying. Only a `fresh` code session runs this from the repository root. Before that preflight, run `python3 "$PLUGIN/scripts/rev-panel-request.py" --text "<the user request>" --session "$S" --base "${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}"`. A printed path is `$S/roster-config.json`. Pass it as `REVIEW_COUNCIL_CONFIG` for this preflight only. Do not edit the user's config. A non-zero exit is fatal: relay it and do not preflight. The default mode is normal: four Luna seats, or four Cursor Grok seats when this host is Cursor and the SDK can seat them. `high effort` selects high: one Opus, one Sol, one Sonnet, and one Luna. An explicit `4*luna` or `4*grok` overrides that preset. `$S/panel-request.json` records the mode and the chain. Every later code panel and the plan panel uses that frozen roster. Do not rebuild it, and do not put the workhorse in those panels.

```bash
REVIEW_COUNCIL_HOST=codex "$PLUGIN/scripts/rev-preflight.sh" \
  --scope branch --write "$S" [--pr <number>]
```

Substitute the resolved scope, append `--pr <number>` for a PR, or append
`--base <ref>` for a non-PR review with an explicit base. Do not combine `--pr`
and `--base`. After preflight, source `$S/scope.env` for `REV_BASE`, `REV_ROOT`,
`REV_SCOPE`, and `REV_PR_NUMBER` plus `REV_PR_REPO` when present. Preserve the
optional PR identity for any quota fallback preflight. Fresh preflight writes
`scope.env`, `files.txt`, `untracked.txt`, and the **probed** `roster.json`. Preflight
refuses empty scopes or shared branches; use a worktree if a code review needs one.
For documents, write absolute paths to `S/docs.txt`, set `REV_REPO` to their root,
and run `roster.sh --probe --brief --write "$S/roster.json" --review-mode documents` without git preflight.
Probes and reviews contact the configured providers and consume their usage.

Print the roster and any `degradation` reason before reviewing. Never replace a
missing provider with an imaginary in-process agent. Repeated CLI seats are separate
runs with different lenses, **not** additional labs. Exit 5 is retryable. Relay the
one-line reason verbatim, preserve the session, and retry when provider availability
recovers. Exit 6 is permanent. Relay the one-line reason verbatim and stop because the
scope or strict roster contract cannot run as asked.
Configuration is `~/.config/review-council/config.json` (or `REVIEW_COUNCIL_CONFIG`):
`exclude`, `pin`, `codex_models`, `claude_seat`, `claude_seats`, `extras`,
`min_labs`, `plan_seats`, and `quota_fallback` are shared with Claude Code.
A fresh session rebuilds its roster once during preflight. An initialized session validates
and reuses its frozen roster without probing.
Roster configuration changes require a fresh session, whose preflight applies the new
configuration once.
See [configuration](https://github.com/WiktorStarczewski/review-council/blob/main/docs/config.md) for the full format.

Read repository instructions, inspect the diff and consumers, and record existing
failures in `S/baseline.md` using relevant project checks. Do not require unrelated
checks for prose. Initialize `findings.md` and `rejected.md` without overwriting a
resumed ledger. Record state via `rev-state.sh "$S" key=value ...`:
`round`, `min_rounds` (the explicit override or `adaptive`), `phase`, `seats` (JSON array), `dropped`, `open.P0` through
`open.P3`, and `fixed`. State updates are sequential.

An optional `S/baseline.json` records each check's command, outcome, applicability,
and failure evidence using the [structured baseline format](../../../../docs/cost-accounting.md).
When present it replaces `baseline.md` in reviewer prompts; include the full baseline,
including skipped checks and pre-existing failures.
