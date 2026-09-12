# Configuration

review-council needs no configuration to run - the roster is detected from whatever's installed. This document covers the config file and environment variables for shaping or overriding that detection.

## Config file

Path: `${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}`.

Read by `scripts/roster.sh` (via `scripts/lib/roster.py`) on every invocation. A missing file is not an error - it's the common case, and detection proceeds with defaults. A file that exists but fails to parse is reported in the roster's `excluded[]` list with reason `config unreadable`, and is otherwise ignored - a broken config degrades the roster, it never crashes it. Unknown keys are ignored, so the file is forward-compatible with a future release adding more.

| Key | Type | Default | Effect |
|---|---|---|---|
| `exclude` | array of strings | `[]` | Lab or seat names to drop from the roster even if detected and signed in, e.g. `["gemini"]` or `["grok-code-review"]`. Applies to detected seats only: padded seats are added afterwards and cannot be excluded, because the three-seat floor is not something config is allowed to remove - excluding the Claude lab is instead recorded as overridden in `excluded[]`. |
| `pin` | object | `{}` | Per-seat override of the detected `model`/`effort`, e.g. `{"codex-sol": {"effort": "ultra"}}`. Only overrides the given field(s); anything omitted keeps its detected value. A Codex model pin outside `codex_models` is excluded and reported. Applies to detected seats only: padded seats are added afterwards and cannot be pinned. |
| `codex_models` | array of 1 or 2 unique strings | newest two | Exact visible Codex model slugs to seat, in order. Invalid values and unknown slugs exclude Codex with the reason in `excluded[]`; they never fall back to another model. When this key is present, every listed model must survive exclusions, pins, and probes before padding. Permanent configuration conflicts exit 6; retryable provider availability exits 5. Models from different generations that share a suffix receive generation-qualified seat IDs. |
| `claude_seats` | integer from 0 to 4 | `1` | Number of independent Opus runs. Invalid values exclude the detected Claude seats with the reason in `excluded[]`; they never fall back to one seat. When this key is explicitly positive, that many Opus seats must survive before padding. Permanent configuration conflicts exit 6; retryable provider availability exits 5. `0` disables detected Claude seats. If Claude-host padding must restore the three-seat floor, `excluded[]` records that override. `claude_seat: false` and `REVIEW_COUNCIL_CLAUDE_SEAT=0` also disable them. |
| `extras` | boolean | `true` | Makes both extra seats available to explicit numeric round plans. Adaptive defaults omit them. `false` removes them entirely. |
| `claude_seat` | boolean | `true` | `false` removes the `opus` seat - equivalent to `REVIEW_COUNCIL_CLAUDE_SEAT=0`. It cannot empty the panel: if fewer than three seats remain, Claude seats are padded back in and `excluded[]` records the override. |
| `min_labs` | integer at least 1 | `1` | Hard floor on how many distinct labs must be **detected** - padded seats never count towards it. Invalid values and floors above the maximum allowed by exclusions and disable settings exit 6 before probes. A satisfiable floor that current provider availability cannot meet exits 5. The default of `1` preserves graceful degradation. Set `2` to reject a single-lab review. Set `3` with Gemini excluded to require Codex, Grok, and Claude. |
| `check_updates` | boolean | `false` | `true` adds one line to the session banner when a newer release is published: `review-council <version> available: claude plugin update review-council`. Nothing is ever installed by it. Off unless the value is literally `true`. |

Example:

```json
{
  "exclude": ["gemini"],
  "pin": { "grok": { "effort": "high" } },
  "codex_models": ["gpt-5.6-sol"],
  "claude_seats": 2,
  "extras": false,
  "min_labs": 3
}
```

## Environment overrides

Environment variables take precedence over the config file, which takes precedence over detected defaults.

| Variable | Used by | Effect |
|---|---|---|
| `REVIEW_COUNCIL_CONFIG` | `roster.sh` | Path to the config file, instead of `~/.config/review-council/config.json`. |
| `REVIEW_COUNCIL_CODEX_MODELS_CACHE` | `roster.sh` | Path to Codex's models cache, instead of `~/.codex/models_cache.json` - the source for which `gpt-<major>.<minor>` slugs exist and what effort levels each supports. |
| `REVIEW_COUNCIL_GEMINI_CREDS` | `roster.sh` | Path to Gemini's OAuth credentials file, instead of `~/.gemini/oauth_creds.json`, used as one of the two "signed in" signals (the other is `GEMINI_API_KEY`). |
| `REVIEW_COUNCIL_GEMINI_MODEL` | `roster.sh` | Model slug for the Gemini seat, instead of `gemini-2.5-pro`. Gemini has no effort knob, so there is no matching effort variable. |
| `GEMINI_API_KEY` | `roster.sh` | Presence alone counts as "signed in" for Gemini, alongside the credentials file. |
| `REVIEW_COUNCIL_CLAUDE_SEAT` | `roster.sh` | `0` removes the `opus` seat for this invocation - the env-var form of `claude_seat: false`. |
| `REV_CODEX_EFFORT` | `rev-seat.sh` | Overrides the roster-selected effort for any Codex seat on a single call, without touching the roster. |
| `REV_GROK_EFFORT` | `rev-seat.sh` | Same, for the Grok seat. |
| `REV_ACTIVE` | the loop | Set to `1` automatically inside every seat's environment once a review starts; a nested `/review-council:rev` refuses to start while it's set. Not meant to be set by hand. |
| `REV_STACK_LEG` | `stack.sh` | Set to `1` automatically inside each stack leg so it skips the top-level squash/push and so a leg can never itself launch a stack. Not meant to be set by hand. |
| `REV_SOURCE_CONTEXT` | `rev-evidence.py` | Set to `1` to enable literal source-context packets for the held-out adoption candidate. The default remains `0` until certification. |
| `REV_PATCH_CHUNKS` | `rev-evidence.py` | Set to `1` to enable exact patch chunks for the held-out adoption candidate. The default remains `0` until certification; chunk mode also requires at least 10% fewer proof reads and every byte, line, and UTF-8 bound. |
| `REVIEW_COUNCIL_UPDATE_URL` | `update-check.py` | Where the published `plugin.json` is read from, instead of this repo's `main`. |
| `REVIEW_COUNCIL_UPDATE_TTL` | `update-check.py` | Seconds before the cached answer is refetched (default 86400 - once a day). |
| `REVIEW_COUNCIL_CACHE_DIR` | `update-check.py` | Directory for `update-check.json`, instead of `${XDG_CACHE_HOME:-~/.cache}/review-council`. |
| `XDG_CACHE_HOME` | `update-check.py` | The standard cache root, used when `REVIEW_COUNCIL_CACHE_DIR` is unset. |
| `REVIEW_COUNCIL_SETTINGS` | `install.sh` | The `settings.json` whose `autoUpdate` flag the installer sets, instead of `~/.claude/settings.json`. |
| `REVIEW_COUNCIL_NO_AUTO_UPDATE` | `install.sh` | `1` is the env form of `--no-auto-update`: the installer leaves `settings.json` alone. |
| `CLAUDE_PLUGIN_ROOT` | set by Claude Code | The installed plugin's own directory; every skill, hook and agent path in this plugin is written relative to it. Not something you configure - set by the harness at plugin load. |

## Graceful degradation

A panel is three seats. When detection finds fewer, `roster.sh` appends Claude seats (`claude-1`, `claude-2`, … - adapter `agent`, `opus@max`, `"padded": true`) until there are three, and the roster gains three top-level keys: `labs` (the distinct labs among the non-extra seats, in seat order), `padded` (how many seats were added), and `degraded` - true when anything was padded or only one lab is left - plus a one-sentence `degradation` when it is. Padded seats are dealt lenses like any other seat, so three Claude seats review through three different lenses.

Exact positive model and seat counts are checked against unpadded survivors before padding. Padding then runs last - after `exclude`, after `pin`, and after the `--probe` round trip - so it replaces seats only for non-strict degraded panels. It cannot satisfy an exact count or `min_labs`. Padded seats are not addressable by `exclude` or `pin`.

Preflight caches each probe by adapter and model. Two independent Opus seats therefore make one availability probe, then run as separate reviewers during the council.

Nothing about this is quiet: the `--brief` banner ends in ` · DEGRADED: <sentence>` for a runnable thin panel or ` · STRICT <class>: <reason>` for a refusal. Preflight preserves the strict status and reason. A satisfiable requirement blocked by current provider availability exits 5. An invalid setting or a lab floor made impossible by exclusions and disable settings exits 6 before paid probes. The roster records `strict_class` as `availability` or `config` and the matching `strict_reason`, with config taking precedence when both occur.

## Precedence in one line

For anything with both a config key and an env var (`claude_seat`/`REVIEW_COUNCIL_CLAUDE_SEAT`): env var wins if set, else the config key, else the built-in default. For anything config-only (`exclude`, `pin`, `extras`): there is no env-var equivalent - edit the config file.


## Where the config file is looked up

1. `$REVIEW_COUNCIL_CONFIG` if set.
2. `~/.config/review-council/config.json`.

`CLAUDE_PLUGIN_DATA` is deliberately not consulted: Claude Code sets it per plugin and a shell can inherit another plugin's value.

An unreadable file is reported in the session banner as `config unreadable (pins and exclusions ignored)`. Extras (`codex-review`, `grok-code-review`) can be excluded or pinned by seat name. `REVIEW_COUNCIL_LOGIN_TIMEOUT` (default 20 s) and `REVIEW_COUNCIL_PROBE_TIMEOUT` (default 60 s) bound the sign-in and probe calls.

## Update notices and auto-update

Two separate things, both off unless you ask for them:

- **Auto-update** is Claude Code's own, per marketplace: `extraKnownMarketplaces.review-council.autoUpdate` in `~/.claude/settings.json`. It defaults to off for third-party marketplaces; `install.sh` turns it on unless you pass `--no-auto-update`, and `scripts/lib/set-auto-update.py <settings.json> review-council <true|false>` flips it afterwards without disturbing anything else in the file: the rewrite is atomic, keeps the file's mode (a `600` settings file stays `600`), follows a symlinked `settings.json` instead of replacing it, refuses to touch a file it cannot parse, and - when there is no entry for the marketplace yet - writes the `source` object alongside the flag so the entry is usable. Updates are gated on the plugin manifest's `version`, which is why the marketplace entry pins no version of its own - one there would silently override the manifest.
- **The update notice** (`check_updates`) only tells you. `scripts/lib/update-check.py` compares the installed `plugin.json` version against the published one, caches the answer for a day under `~/.cache/review-council`, and prints a single line the `SessionStart` hook appends to the banner. It never updates anything: a plugin's own hook replacing the directory it runs from is how an install gets corrupted. Every failure - no network, unparseable JSON, unwritable cache - prints nothing and exits 0, and the hook caps the whole call at three seconds.

With auto-update on there is normally nothing for the notice to report; it is there for people who turned auto-update off and still want to know.

## Codex host

The generated Codex bundle selects `REVIEW_COUNCIL_HOST=codex` automatically in its
roster and stack entrypoints. Set that variable explicitly when using shared source
scripts. The same config file, exclusions, pins, and `min_labs` apply in both hosts.
The differences are:

- `opus` uses adapter `claude`: an installed CLI with positive `claude auth status`
  is required. `claude_seat: false` and provider exclusions are honored.
- Padding duplicates only surviving CLI seats after probing. Each gets a unique seat
  name and `padded: true`; duplicates never count as another lab. No usable CLI exits
  5 even with the default `min_labs: 1`.
- Codex models are read from `$CODEX_HOME/models_cache.json` when `CODEX_HOME` is set,
  otherwise `~/.codex/models_cache.json`. The explicit cache override still wins.
- Codex stack defaults are `NO_PUSH=1` and `NO_SQUASH=1`. Existing shell stack configs
  can override these, so inspect them before reusing a Claude stack configuration.
- Claude session hooks, update notices, and auto-update settings are not installed
  in Codex. Refresh the Git marketplace and reinstall, or rerun the curl installer, then start a new chat.
