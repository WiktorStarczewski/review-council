# Configuration

review-council needs no configuration to run - the roster is detected from whatever's installed. This document covers the config file and environment variables for shaping or overriding that detection.

## Config file

Path: `${REVIEW_COUNCIL_CONFIG:-$HOME/.config/review-council/config.json}`.

Read by `scripts/roster.sh` (via `scripts/lib/roster.py`) on every invocation. A missing file is not an error - it is the common case, and detection proceeds with defaults. A file that exists but fails to parse refuses reviewer selection as a permanent configuration error so an exact roster cannot silently fall back to defaults. Unknown keys are ignored, so the file is forward-compatible with a future release adding more.

| Key | Type | Default | Effect |
|---|---|---|---|
| `exclude` | array of strings | `[]` | Lab or seat names to drop from the roster even if detected and signed in, e.g. `["gemini"]` or `["codex-review"]`. Applies to detected seats only: padded seats are added afterwards and cannot be excluded, because the three-seat floor is not something config is allowed to remove - excluding the Claude lab is instead recorded as overridden in `excluded[]`. |
| `pin` | object | `{}` | Per-seat override of the detected `model`/`effort`, e.g. `{"codex-sol": {"effort": "ultra"}}`. Only overrides the given field(s); anything omitted keeps its detected value. A Codex model pin outside `codex_models` is excluded and reported. Applies to detected seats only: padded seats are added afterwards and cannot be pinned. |
| `codex_models` | array of 1 or 2 unique strings | newest two | Exact visible Codex model slugs to seat, in order. Invalid values and unknown slugs exclude Codex with the reason in `excluded[]`; they never fall back to another model. When this key is present, every listed model must survive exclusions, pins, and probes before padding. Permanent configuration conflicts exit 6; retryable provider availability exits 5. Models from different generations that share a suffix receive generation-qualified seat IDs. |
| `claude_models` | array of 1 or 2 unique strings | absent | Exact Claude model families to seat, in order. Supported values are `opus` and `sonnet`; both run at maximum effort with stable seat IDs. Every listed model must survive exclusions, pins, and probes before padding. This setting is mutually exclusive with `claude_seats`; malformed lists, incompatible pins, and using both settings exit 6. Provider availability failures exit 5. |
| `claude_seats` | integer from 0 to 4 | `1` | Number of independent Opus runs. Invalid values exclude the detected Claude seats with the reason in `excluded[]`; they never fall back to one seat. When this key is explicitly positive, that many Opus seats must survive before padding. Permanent configuration conflicts exit 6; retryable provider availability exits 5. `0` disables detected Claude seats. If Claude-host padding must restore the three-seat floor, `excluded[]` records that override. `claude_seat: false` and `REVIEW_COUNCIL_CLAUDE_SEAT=0` also disable them. |
| `claude_adapter` | `"cli"`, `"agent"` or `"auto"` | `"auto"` | How a Claude Code host runs Anthropic seats. `cli` seats them on adapter `claude`: the `claude` CLI, launched by `rev-seat.sh` like any CLI seat, probed by `--probe`, and usable by evidence mode and the plan panel. `agent` seats them on adapter `agent`, a Claude Code subagent that needs no sign-in but cannot run evidence mode or plan panels. `auto` picks `cli` when the `claude` CLI is on PATH and `claude auth status` reports signed in, else `agent`, checking once per roster build; when it falls back to `agent`, `roster.json` records why as an `excluded` entry for `claude_adapter`. Padded seats use the chosen adapter, except that a CLI that is not usable, or whose `--probe` of Opus failed, pads with `agent` instead. A CLI seat started from inside Claude Code drops the parent session's identity variables (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID` and similar) and keeps auth and provider variables. A Codex host always uses the CLI and ignores this key. Any other value exits 6. `REVIEW_COUNCIL_CLAUDE_ADAPTER` overrides it. |
| `plan_seats` | `"completeness"` or `"all"` | `"completeness"` | Size of the plan panel. `completeness` is one plan-completeness seat: the first surviving core seat in roster order whose adapter is not `agent`. `all` is the four-lens plan panel (completeness, soundness, simplicity, tests). The roster records `"plan_seats": "all"` at the top level only for `all`; absence means `completeness`. Any other value exits 6. |
| `extras` | boolean | `true` | Makes the `codex-review` extra seat available to explicit numeric round plans. Adaptive defaults omit it. `false` removes it entirely. |
| `claude_seat` | boolean | `true` | `false` removes the `opus` seat - equivalent to `REVIEW_COUNCIL_CLAUDE_SEAT=0`. It cannot empty the panel: if fewer than three seats remain, Claude seats are padded back in and `excluded[]` records the override. |
| `min_labs` | integer at least 1 | `1` | Hard floor on how many distinct labs must be **detected** - padded seats never count towards it. Invalid values and floors above the maximum allowed by exclusions and disable settings exit 6 before probes. A satisfiable floor that current provider availability cannot meet exits 5. The default of `1` preserves graceful degradation. Set `2` to reject a single-lab review. Set `3` to require Codex, Gemini, and Claude. |
| `quota_fallback` | boolean | `false` | Temporarily replaces each Claude seat blocked by a provider quota or capacity error with a unique Terra seat, or each blocked OpenAI seat with a unique Sonnet seat. The active run records a `min_labs` waiver only when successful substitutions account for the complete diversity shortfall. Authentication, configuration, model, unknown, missing-target, and failed-target errors remain strict. The roster records every substitution and never changes this file. |
| `check_updates` | boolean | `false` | `true` adds one line to the session banner when a newer release is published: `review-council <version> available: claude plugin update review-council`. Nothing is ever installed by it. Off unless the value is literally `true`. |

Example:

```json
{
  "exclude": ["gemini"],
  "pin": { "codex-sol": { "effort": "ultra" } },
  "codex_models": ["gpt-5.6-sol", "gpt-5.6-terra"],
  "claude_models": ["opus", "sonnet"],
  "extras": false,
  "min_labs": 2,
  "quota_fallback": true
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
| `REVIEW_COUNCIL_CLAUDE_ADAPTER` | `roster.sh` | `cli`, `agent` or `auto` for this invocation - the env-var form of `claude_adapter`. Any other non-empty value exits 6. |
| `REVIEW_COUNCIL_PROVIDER_OUTPUT_BYTES` | `roster.sh` | Combined stdout/stderr cap for each provider status or probe command. Defaults to 1 MiB. Exceeding it rejects that command and terminates its process group. |
| `REVIEW_COUNCIL_CONTRACT_VERSION_TIMEOUT_SECONDS` | `rev-contract-check.py` | Per-provider CLI version timeout. Defaults to 5 seconds. |
| `REVIEW_COUNCIL_CONTRACT_VERSION_OUTPUT_BYTES` | `rev-contract-check.py` | Output cap for each provider CLI version command. Defaults to 64 KiB. |
| `REV_ACTIVE` | the loop | Set to `1` automatically inside every seat's environment once a review starts; a nested `/review-council:rev` refuses to start while it's set. Not meant to be set by hand. |
| `REV_STACK_LEG` | `stack.sh` | Set to `1` automatically inside each stack leg so it skips the top-level squash/push and so a leg can never itself launch a stack. Not meant to be set by hand. |
| `REV_SOURCE_CONTEXT` | `rev-evidence.py` | `1` enables literal source-context packets and required-source segments. This is the host default. Set `0` only for a labeled baseline measurement. |
| `REV_PATCH_CHUNKS` | `rev-evidence.py` | `auto` selects exact patch chunks when they save proof reads or are required to fit compiled provider capacity. `1` forces chunks when representable. `0` requests window mode and fails preparation when that mode cannot fit. The host default is `auto`. |
| `REV_RG` | `rev-evidence.py` | The ripgrep executable that replays `rg` plan searches. Unset, `rg` on PATH is used, then Claude Code's embedded ripgrep (`$CLAUDE_CODE_EXECPATH` run as `rg`, accepted only when `rg --version` prints `ripgrep`). When none is found, `prepare` fails with `ripgrep binary not found on PATH; set REV_RG to a ripgrep executable`. |
| `REV_CODEX_SOURCE_BATCH` | `rev-prompt.sh` | Set to `1` only for a certified Codex prompt. It permits semicolon-separated pure source windows under one 240-line aggregate and a 32 KiB exact-output cap. The script default remains `0`. |
| `REVIEW_COUNCIL_UPDATE_URL` | `update-check.py` | Where the published `plugin.json` is read from, instead of this repo's `main`. |
| `REVIEW_COUNCIL_UPDATE_TTL` | `update-check.py` | Seconds before the cached answer is refetched (default 86400 - once a day). |
| `REVIEW_COUNCIL_CACHE_DIR` | `update-check.py` | Directory for `update-check.json`, instead of `${XDG_CACHE_HOME:-~/.cache}/review-council`. |
| `XDG_CACHE_HOME` | `update-check.py` | The standard cache root, used when `REVIEW_COUNCIL_CACHE_DIR` is unset. |
| `REVIEW_COUNCIL_SETTINGS` | `install.sh` | The `settings.json` whose `autoUpdate` flag the installer sets, instead of `~/.claude/settings.json`. |
| `REVIEW_COUNCIL_NO_AUTO_UPDATE` | `install.sh` | `1` is the env form of `--no-auto-update`: the installer leaves `settings.json` alone. |
| `CLAUDE_PLUGIN_ROOT` | set by Claude Code | The installed plugin's own directory; every skill, hook and agent path in this plugin is written relative to it. Not something you configure - set by the harness at plugin load. |

## Graceful degradation

A panel is three seats. When detection finds fewer, `roster.sh` appends Claude seats (`claude-1`, `claude-2`, … - on the adapter `claude_adapter` selects, `opus@max`, `"padded": true`) until there are three, and the roster gains three top-level keys: `labs` (the distinct labs among the non-extra seats, in seat order), `padded` (how many seats were added), and `degraded` - true when anything was padded or only one lab is left - plus a one-sentence `degradation` when it is. Padded seats are dealt lenses like any other seat, so three Claude seats review through three different lenses.

Exact positive model and seat counts are checked against unpadded survivors before padding. Padding then runs last - after `exclude`, after `pin`, and after the `--probe` round trip - so it replaces seats only for non-strict degraded panels. It cannot satisfy an exact count or `min_labs`. Padded seats are not addressable by `exclude` or `pin`.

Quota fallback is a separate opt-in path for an exact roster. It accepts quota or capacity errors emitted by a provider CLI, or platform terminal metadata for a Claude Code Agent seat; reviewer prose never qualifies. Every substitute has a unique padded seat name, keeps maximum effort, and records `substitutes_for` with the preferred seat name. An active substitution may waive `min_labs` only for diversity lost through successful quota substitutions. Authentication, transport, or other provider failures still enforce the floor; the roster records either result. A mid-panel quota failure cancels pending work and passes the failed seat explicitly into preflight in a fresh sibling session. Preflight refuses an initialized fallback target. The new scope, file list, and untracked-file list must byte-match the original. Before the whole panel restarts, `rev-evidence.py same-source` also requires identical content-addressed base and snapshot trees, scope, and paths, including same-path tracked, staged, and untracked content. Completed outputs from the failed label remain diagnostic. One fallback panel is the full-panel restart ceiling, and a hard audit failure stops it without repair. The next review probes the preferred providers again, so restored credits restore the configured roster automatically.

Preflight selects every effective effort before provider calls and caches each probe by adapter, model, and effort. Repeated seats share an availability probe only when all three values match. The roster, provider contract receipt, evidence manifest, and launch retain that exact identity. A later `--effort` argument is accepted only when it equals the roster value.

Nothing about this is quiet: the `--brief` banner ends in ` · DEGRADED: <sentence>` for a runnable thin panel or ` · STRICT <class>: <reason>` for a refusal. Preflight preserves the strict status and reason. A satisfiable requirement blocked by current provider availability exits 5. An invalid setting or a lab floor made impossible by exclusions and disable settings exits 6 before paid probes. The roster records `strict_class` as `availability` or `config` and the matching `strict_reason`, with config taking precedence when both occur.

## Precedence in one line

For anything with both a config key and an env var (`claude_seat`/`REVIEW_COUNCIL_CLAUDE_SEAT`, `claude_adapter`/`REVIEW_COUNCIL_CLAUDE_ADAPTER`): env var wins if set, else the config key, else the built-in default. For anything config-only (`exclude`, `pin`, `extras`, `quota_fallback`, `plan_seats`): there is no env-var equivalent - edit the config file.


## Where the config file is looked up

1. `$REVIEW_COUNCIL_CONFIG` if set.
2. `~/.config/review-council/config.json`.

`CLAUDE_PLUGIN_DATA` is deliberately not consulted: Claude Code sets it per plugin and a shell can inherit another plugin's value.

An unreadable file is reported in the session banner as `config unreadable (reviewer selection refused)`. The `codex-review` extra can be excluded or pinned by seat name. `REVIEW_COUNCIL_LOGIN_TIMEOUT` (default 20 s) and `REVIEW_COUNCIL_PROBE_TIMEOUT` (default 60 s) bound the sign-in and probe calls.

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
  is required, whatever `claude_adapter` says. `claude_seat: false` and provider
  exclusions are honored.
- Padding duplicates only surviving CLI seats after probing. Each gets a unique seat
  name and `padded: true`; duplicates never count as another lab. No usable CLI exits
  5 even with the default `min_labs: 1`.
- Codex models are read from `$CODEX_HOME/models_cache.json` when `CODEX_HOME` is set,
  otherwise `~/.codex/models_cache.json`. The explicit cache override still wins.
- Codex stack defaults are `NO_PUSH=1` and `NO_SQUASH=1`. Existing shell stack configs
  can override these, so inspect them before reusing a Claude stack configuration.
- Claude session hooks, update notices, and auto-update settings are not installed
  in Codex. Refresh the Git marketplace and reinstall, or rerun the curl installer, then start a new chat.
