# Pi setup

## Install

```bash
pi install git:github.com/WiktorStarczewski/review-council
```

Run `/reload` or start a new Pi session. The package registers `/council`, the `/rev` compatibility alias and the
uniquely named `review-council-rev` skill. It does not register `/stack`, load
Claude hooks, or change another host's installation. No build step, optional
subagent package or npm runtime dependency is required.

For a pinned release:

```bash
pi install git:github.com/WiktorStarczewski/review-council@review-council--v0.9.2
```

Pi manages Git package installation, updates and removal. To update an unpinned
install, run `pi update --extensions` and `/reload`. A pinned tag does not move;
install the new release ref explicitly. Council uses a transformed TypeScript entrypoint
so `/reload` also picks up an upgrade inside the existing Pi process, including an
upgrade from the earlier native ESM entrypoint. No restart is required.
To remove the package:

```bash
pi remove git:github.com/WiktorStarczewski/review-council
```

Project-local installation is supported by `pi install --local <source>` and
requires project trust. For development, use `pi install /absolute/path/to/review-council`.
Pi loads that directory directly, so keep it available and reload after edits.

## Setup

Run `/council --setup`. This reports executable presence only and makes no model
calls. Required tools are Bash, Git, Python 3 and ripgrep. GitHub CLI (`gh`) is
required for PR scopes and publication. Authenticate GitHub with `gh auth login`.

Reviewers use the same external provider CLIs and Council configuration as other
hosts: `codex login`, `claude auth login`, and optionally the Gemini CLI's normal
sign-in. Install missing CLIs using their providers' official instructions. Pi's
own login does not authenticate reviewer CLIs, and the package never reads or
copies Pi credentials. Normal preflight verifies the selected roster and can
consume provider usage. Setup output is not proof of authenticated availability.

## Invoke

```text
/council
/council uncommitted --read-only
/council https://github.com/owner/repo/pull/12
/council branch 4 --base origin/next
/council --help
/council eco
/council high
/council status
```

Bare `/council` starts a review, just like `/rev`. Exact `eco`, `high` and `status`
subcommands do not start reviews or call providers. Autocomplete offers these commands.
Use `./high`, for example, to review a path whose name matches a subcommand.

The independent footer shows `⚖  council: 🌿 ECO` or `⚖  council: 🔥 HIGH`, with two
spaces after the scales icon. It does not require Ponytail or another extension.
ECO is the default four-Luna panel. HIGH uses the existing Opus, Sol, Sonnet and Luna
preset, retaining installed effort, availability and recovery rules.

The selection applies to new reviews throughout this Pi session, including conversational
and direct-skill requests. It survives reload/resume and follows the selected session-tree
branch; a new session starts at ECO. A deliberate per-review mode or roster overrides the
session default without changing it. An initialized review keeps its frozen roster.
No permanent Council configuration is changed.

All existing review scopes, audit/receipt requirements and fix-loop rules apply.
Arguments reach the workflow as text, not shell commands. Running `/council` or `/rev` while Pi
is busy or a nested review is active is refused. Publication and pushing retain
the original workflow's authorization boundaries; invoking the command does not
grant unrelated write permissions.

The command binds its own installed skill directly. A shared `~/.agents/skills/rev`
from Codex cannot shadow `/council` or `/rev`. For explicit skill invocation or natural-language
requests, use `/skill:review-council-rev`; do not use another host's shared `rev`.
If another extension also registers `/rev`, Pi adds numeric suffixes. Inspect the
command's provenance and select this package's command rather than assuming a suffix.

## Host differences

Every runtime invocation sets `REVIEW_COUNCIL_HOST=pi`. All reviewers use explicit
external transports; there is no implicit Claude Agent fallback. The Pi session
orchestrates the workflow, with session-owned logs, process identities and exit
markers for CLI seats. It polls bounded shell calls and retains evidence for
resumption. No in-process subagent facility is assumed. Reviewer models, effort,
proof requirements and canonical receipts are unchanged.

Pi stack hosting is not supported. Missing reviewer availability or invalid proof
remains an incomplete review, never a clean result. Package tests establish native
command and skill discovery; they do not certify a live provider review.

## Maintenance

The Pi skill and phases are generated from the canonical external-CLI contract:

```bash
python3 scripts/generate-pi-skills.py
python3 scripts/generate-pi-skills.py --check
```

CI checks drift, host routing, command behavior and real Pi installation/RPC
command discovery without calling a model. Update the generator's explicit host
bindings when the canonical contract changes; do not edit generated phases alone.
