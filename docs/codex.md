# Codex port

## Install and update

Marketplace:

```bash
codex plugin marketplace add WiktorStarczewski/review-council
codex plugin add review-council@review-council
```

One-liner (no checkout required):

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install-codex.sh | bash
```

The repository contains a Codex marketplace manifest. Codex fetches a Git snapshot
of this repo and installs the selected plugin into its cache. The one-liner runs the
same two marketplace commands. This is a repository marketplace you explicitly add;
it does not submit the plugin to the public curated catalog.

Start a new Codex chat after installation. To update:

```bash
codex plugin marketplace upgrade review-council
codex plugin add review-council@review-council
```

To try a branch before it is merged, pass `--ref <branch>` to `marketplace add`, or
pipe that branch's installer to `bash -s -- --ref <branch>`. The script also accepts
`REVIEW_COUNCIL_REF`; it defaults to `main`.

For local development, `python3 scripts/install-codex-plugin.py` builds
`~/plugins/review-council`, adds it to the personal marketplace, and installs
`review-council@personal` with a fresh version build suffix. Keep only one variant
enabled in a session. Use `codex plugin remove review-council@personal` to remove a
previous local installation after switching to the repository marketplace.

Build without installing with `python3 scripts/build-codex-plugin.py --output
/tmp/review-council`. The output is generated; rebuilding replaces it. An unrelated
output directory or conflicting personal marketplace entry is refused.

To uninstall the repository version:

```bash
codex plugin remove review-council@review-council
```

## Invocation

Ask Codex to use review-council; select its `rev` or `stack` skill from the skills
picker when available. Examples:

```text
Use review-council to review this branch against origin/main.
Use review-council for one round, read-only, on my uncommitted changes.
Use review-council to review these design documents.
Use review-council to review the SDK and wallet branches as a dependency stack.
```

Code fix loops default to eight rounds, then continue until the termination criteria
are met. Read-only panels default to one round. Explicit round counts override the
minimum. Actual reviewer calls consume the corresponding provider's usage.

## Provider and orchestration differences

| Behavior | Claude Code | Codex |
| --- | --- | --- |
| Anthropic seat | Built-in Opus agent | Installed, signed-in Claude CLI |
| Other seats | Detected Codex/Grok/Gemini CLIs | Same |
| Thin-panel padding | Opus agents | Repeated surviving CLI runs, reported as degraded |
| No usable external CLI | Built-in Claude panel | Refuse if no actual provider survives |
| Session policy | Claude SessionStart hook | Native skills, no global review hook |
| Stack engine | `claude -p` | `codex exec` |
| Stack finishing defaults | Squash and push | Keep history and changes local |

Codex selects its newest visible model generation from its local model cache, up to
two seats, using the existing supported effort ladder. A single-provider panel is
reported as degraded. Use `min_labs` for a stronger diversity floor. See
[configuration](config.md) for pins, exclusions, and environment variables.

Both hosts install the same plugin directory. The Codex manifest selects
`codex-skills/`; Claude keeps its existing `skills/`. Claude's hook config lives in
`.claude-plugin/hooks.json` and is explicitly registered by its manifest, so Codex
does not discover it as a default startup hook. The review scripts and schema have
one shared source.

The Claude CLI adapter permits Read/Glob/Grep and Bash checked by the original
allowlist hook. It disables inherited settings/plugins and MCP configuration,
uses plan mode, and excludes editing tools. Codex seats retain the read-only sandbox.
Both emit the shared findings schema; missing/malformed answers fail validation.
A Claude structured-output event alone does not count as inspecting source files.

Stack legs use Codex's workspace-write sandbox, network access to contact reviewers,
and write access to their session directory. The runner keeps the existing activity
and CPU stall detector. A fresh report is required for every attempt, so an old
receipt cannot make a failed pass look successful. Some sandbox/platform setups may
restrict nested CLIs or repository gates; these failures remain visible and do not
implicitly enable unrestricted execution. A full multi-repository live stack can
consume substantial usage; automated tests exercise its orchestration with doubles.

## Development checks

```bash
plugins/review-council/tests/run-tests.sh
python3 -m unittest discover -s tests -v
```

Both run on macOS and Linux in CI. The second suite exercises Codex roster fallback,
Claude auth and stream parsing, adapter permissions, packaging/installation, and
stack receipts. Live reviewer smoke tests should use disposable files and a known
failure; never treat stub responses as proof of provider compatibility.
