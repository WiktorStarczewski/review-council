# Antigravity (agy) setup

Council's native Antigravity package provides `rev` and `stack` for `agy` and runs
Gemini `hydrogen` and `neon` reviewer and workhorse seats exclusively when
orchestrating from Antigravity (`REVIEW_COUNCIL_HOST=agy`).

## Install

No checkout required:

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install-agy.sh | bash
```

That builds the native plugin bundle and installs it at
`~/.gemini/config/plugins/review-council`, replacing an existing Council bundle
there. `--ref <branch-or-tag>` or `REVIEW_COUNCIL_REF` selects the Git ref.
`REVIEW_COUNCIL_SOURCE` installs from a local checkout instead of cloning.
`REVIEW_COUNCIL_AGY_DEST` overrides the install directory (must be absolute and
end in `review-council`).

Verify structure and discovery with the Antigravity CLI:

```bash
agy plugin validate --strict ~/.gemini/config/plugins/review-council
agy plugin list --json
```

## Build only

From a checkout, the same install is `REVIEW_COUNCIL_SOURCE="$PWD" ./install-agy.sh`.
To only build the bundle directory without installing it:

```bash
python3 scripts/build-agy-plugin.py --output dist/agy/review-council
agy plugin validate --strict dist/agy/review-council
```

The bundle contains root `plugin.json`, `skills/rev/SKILL.md` (with `phases/*.md`),
`skills/stack/SKILL.md`, scripts, schema, docs and tests. Foreign host manifests and
hooks (`.claude-plugin`, `.codex-plugin`, `.cursor-plugin`, `hooks`) are omitted.

## Chain and Google ToC isolation

When running from Antigravity (`REVIEW_COUNCIL_HOST=agy`):

- The current Gemini model in your `agy` session orchestrates the review loop.
- The normal default panel seats four Gemini `hydrogen` reviewers via `agy`,
  falling back to four Codex Luna seats if `hydrogen` is unavailable.
- `high effort` still selects two Codex Sol seats and two Claude Opus seats.
- Explicit requests support `N*hydrogen`, `N*neon`, `N*luna`, `N*sol`, `N*terra`.
- The workhorse and review escalation chain is:
  `hydrogen -> luna -> sonnet -> sol -> neon -> opus`.
- `hydrogen` and `neon` models through `agy` are strictly refused on all other
  hosts (`claude`, `codex`, `cursor`, `pi`) across roster building, panel
  requests, workhorse escalation, `rev-seat.sh`, and `seats.d/agy.sh` to respect
  Google Terms of Service.

## How seats execute

Antigravity reviewer seats launch as isolated headless `agy` processes in read-only
`--sandbox` mode (`--output-format stream-json --json-schema <findings.schema.json>`),
so every finding carries an independent schema-validated stream transcript and bounded
read audit. Reviewers use shell `cat --`, `sed -n`, and bounded `rg ... | head -80` via
`run_command` so exact file bytes appear verbatim in the `stream-json` audit log.
Evidence navigation indexes, evidence packets, patch chunks, and required source
segments for `agy` seats are capped at 8 KiB so `cat --` output stays below `agy`
`run_command`'s ~10 KiB stdout truncation limit; when an index still exceeds the limit,
the read audit accepts complete coverage across bounded `sed -n` windows, and prompts
guide `agy` seats to keep source reads to at most 100 lines.
