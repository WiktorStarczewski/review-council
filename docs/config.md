# Configuration

review-council needs no configuration to run — the roster is detected from whatever's installed. This document covers the config file and environment variables for shaping or overriding that detection.

## Config file

Path: `${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}`.

Read by `scripts/roster.sh` (via `scripts/lib/roster.py`) on every invocation. A missing file is not an error — it's the common case, and detection proceeds with defaults. A file that exists but fails to parse is reported in the roster's `excluded[]` list with reason `config unreadable`, and is otherwise ignored — a broken config degrades the roster, it never crashes it. Unknown keys are ignored, so the file is forward-compatible with a future release adding more.

| Key | Type | Default | Effect |
|---|---|---|---|
| `exclude` | array of strings | `[]` | Lab or seat names to drop from the roster even if detected and signed in, e.g. `["gemini"]` or `["grok-code-review"]`. |
| `pin` | object | `{}` | Per-seat override of the detected `model`/`effort`, e.g. `{"codex-sol": {"effort": "ultra"}}`. Only overrides the given field(s); anything omitted keeps its detected value. |
| `extras` | boolean | `true` | `false` removes both extra seats (`codex-review`, `grok-code-review`) regardless of whether their base lab is seated. |
| `claude_seat` | boolean | `true` | `false` removes the `opus` seat — equivalent to `REVIEW_COUNCIL_CLAUDE_SEAT=0`. |

Example:

```json
{
  "exclude": ["gemini"],
  "pin": { "grok": { "effort": "high" } },
  "extras": false
}
```

## Environment overrides

Environment variables take precedence over the config file, which takes precedence over detected defaults.

| Variable | Used by | Effect |
|---|---|---|
| `REVIEW_COUNCIL_CONFIG` | `roster.sh` | Path to the config file, instead of `~/.config/review-council/config.json`. |
| `REVIEW_COUNCIL_CODEX_MODELS_CACHE` | `roster.sh` | Path to Codex's models cache, instead of `~/.codex/models_cache.json` — the source for which `gpt-<major>.<minor>` slugs exist and what effort levels each supports. |
| `REVIEW_COUNCIL_GEMINI_CREDS` | `roster.sh` | Path to Gemini's OAuth credentials file, instead of `~/.gemini/oauth_creds.json`, used as one of the two "signed in" signals (the other is `GEMINI_API_KEY`). |
| `REVIEW_COUNCIL_GEMINI_MODEL` | `roster.sh` | Model slug for the Gemini seat, instead of `gemini-2.5-pro`. Gemini has no effort knob, so there is no matching effort variable. |
| `GEMINI_API_KEY` | `roster.sh` | Presence alone counts as "signed in" for Gemini, alongside the credentials file. |
| `REVIEW_COUNCIL_CLAUDE_SEAT` | `roster.sh` | `0` removes the `opus` seat for this invocation — the env-var form of `claude_seat: false`. |
| `REV_CODEX_EFFORT` | `rev-seat.sh` | Overrides the roster-selected effort for any Codex seat on a single call, without touching the roster. |
| `REV_GROK_EFFORT` | `rev-seat.sh` | Same, for the Grok seat. |
| `REV_ACTIVE` | the loop | Set to `1` automatically inside every seat's environment once a review starts; a nested `/review-council:rev` refuses to start while it's set. Not meant to be set by hand. |
| `REV_STACK_LEG` | `stack.sh` | Set to `1` automatically inside each stack leg so it skips the top-level squash/push and so a leg can never itself launch a stack. Not meant to be set by hand. |
| `CLAUDE_PLUGIN_ROOT` | set by Claude Code | The installed plugin's own directory; every skill, hook and agent path in this plugin is written relative to it. Not something you configure — set by the harness at plugin load. |

## Precedence in one line

For anything with both a config key and an env var (`claude_seat`/`REVIEW_COUNCIL_CLAUDE_SEAT`): env var wins if set, else the config key, else the built-in default. For anything config-only (`exclude`, `pin`, `extras`): there is no env-var equivalent — edit the config file.
