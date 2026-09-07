# Seats: the adapter contract, and how to add a lab

A "seat" is one reviewer in the `/review-council:rev` panel: a lab (`openai`, `xai`, `google`, `anthropic`), an adapter that knows how to drive that lab's CLI, and a model/effort pair the roster picked for it. This document is for adding a new lab, not for using the plugin — see the root `README.md` for that.

## The roster

`scripts/roster.sh [--json|--brief] [--probe] [--write <file>]` detects which lab CLIs are installed and signed in and writes `roster.json`:

```json
{
  "generated_at": "2026-09-02T12:00:00Z",
  "seats": [
    { "seat": "codex-sol",   "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",   "effort": "max",   "extra": false },
    { "seat": "grok",        "lab": "xai",       "adapter": "grok",   "model": "grok-4.6",      "effort": "xhigh", "extra": false },
    { "seat": "gemini",      "lab": "google",    "adapter": "gemini", "model": "gemini-2.5-pro","effort": null,    "extra": false },
    { "seat": "opus",        "lab": "anthropic", "adapter": "agent",  "model": "opus",          "effort": "max",   "extra": false },
    { "seat": "codex-review","lab": "openai",    "adapter": "codex",  "mode": "review",         "extra": true, "round": 3 }
  ],
  "excluded": [ { "cli": "gemini", "reason": "not installed" } ]
}
```

Every non-agent seat names an `adapter` — the script in `scripts/seats.d/` that knows how to drive that CLI. Several seats can share one adapter (`codex-sol`, `codex-terra` and the `codex-review` extra all use `seats.d/codex.sh`, distinguished by `model` and `mode`).

## `rev-seat.sh`: the dispatcher

`scripts/rev-seat.sh <seat> <session-dir> <round> <prompt-file> [--effort e] [--base ref]` is the one thing the review loop calls. It:

1. Reads `<session-dir>/roster.json` and looks up `<seat>`. An unknown seat, or a missing roster file, exits `1` with `run preflight first` — it never guesses a model or adapter.
2. Resolves effort: `--effort` on the command line, else `REV_CODEX_EFFORT`/`REV_GROK_EFFORT` for that adapter, else the roster's `effort` for the seat.
3. Executes `scripts/seats.d/<adapter>.sh` with the environment described below, capturing its exit code.
4. Validates the JSON left at `<session-dir>/r<round>-<seat>.json` against `schema/findings.schema.json`, retries once (one effort step down) on a zero-tool-call or invalid-JSON result, and writes `<session-dir>/r<round>-<seat>.exit`.
5. Prints one summary line: `seat=<s> round=<n> exit=<c> findings=<k>`.

Exit codes are a fixed contract, unchanged regardless of adapter: `0` valid findings, `2` missing or invalid JSON, `3` not signed in, `4` usage cap or rate limit, `1` anything else.

## The adapter contract

`scripts/seats.d/<adapter>.sh` is a standalone script invoked with these environment variables set, and nothing else assumed:

| Var | Meaning |
|---|---|
| `SEAT` | seat name, e.g. `codex-terra` |
| `MODEL` | model slug for this seat |
| `EFFORT` | reasoning effort, or empty for a lab with no effort knob |
| `MODE` | empty for a normal review round, or a lab-specific mode (`review`, `code-review`) for an extra seat |
| `ROOT` | repo root (or document root for a read-only panel over prose) to run the CLI from |
| `PROMPT` | path to the prompt file — pass as a file, not inline, and never leave stdin as an open pipe |
| `SCHEMA` | path to `findings.schema.json` |
| `OUT` | where the adapter must leave the findings JSON |
| `LOG` | human-readable event summary the status line tails |
| `RAW` | the CLI's raw stream, unmodified, for debugging |
| `BASE` | pinned base SHA (used by review-mode adapters that diff against it themselves) |

An adapter must, in order:

1. Run its CLI **read-only** from `$ROOT` — the vendor's own read-only/plan flag, never just a polite prompt (see the root README's read-only guard section for why this matters).
2. Stream the CLI's raw output to `$RAW` and, at the same time or after, summarize it into `$LOG` via `python3 "$SUMMARY" <adapter> "$OUT"`, where `SUMMARY="$HERE/../lib/stream-summary.py"` and `HERE=$(cd "$(dirname "$0")" && pwd)` — the same pattern every shipped adapter uses to find its siblings, since `$LIB` is not part of the environment contract below. This is what `rev-status.sh` tails for the "running … ← last action" text.
3. Leave findings JSON (matching `findings.schema.json`) at `$OUT`.
4. Exit with the CLI's own exit code — the adapter does not reinterpret it; `rev-seat.sh` does the exit-code classification.

`rev-seat.sh` exports `REV_ACTIVE=1` into the adapter's environment so a reviewer's CLI can never itself launch another review loop.

## Adding a new lab

Four pieces, each independently testable:

1. **One adapter** — `scripts/seats.d/<lab>.sh` implementing the contract above for that lab's CLI.
2. **One shim** — `tests/shims/<lab>`, a fake binary the test suite puts first on `PATH` so no test ever calls a real CLI or touches the network. The shipped shims (`codex`, `grok`, `gemini`, `claude`) are frozen for this plugin's initial wave; adding a fifth lab means adding a fifth shim to that set, which is a maintainer change, not something a single adapter change should do unilaterally.
3. **One fixture** — `tests/fixtures/<lab>-stream.ndjson` (or whatever shape that CLI's streaming output actually takes), the reference the shim plays back and the test asserts against.
4. **One test** — `tests/t-<lab>.sh`, covering at minimum: a clean success (exit 0, findings present, a recognizable log line), a not-signed-in case (exit 3), a rate-limit/usage-cap case (exit 4), and a malformed/empty-output case (exit 2).

Also wire the lab into detection and status reporting:

- `scripts/lib/roster.py` — add the cheap presence + signed-in check and the model/effort selection for the new lab (see `docs/config.md` for the env vars that should gate this).
- `scripts/lib/stream-summary.py` — add a branch mapping that lab's stream events to the same three summary line shapes every adapter uses (`tool_call …`, `text: …`, `end status=…`).

Nothing else in the loop, ledger, triage or reporting logic is lab-specific — every seat, once seated, is driven identically by `rev-seat.sh` regardless of which lab it belongs to.
