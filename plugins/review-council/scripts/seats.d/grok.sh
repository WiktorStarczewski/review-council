#!/bin/bash
# grok adapter — run one read-only grok reviewer seat.
#
# Called by rev-seat.sh with the adapter environment contract:
#   SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
# Streams the CLI's events to $RAW, one summarised line each to $LOG, leaves findings JSON at $OUT
# (stream-summary.py lifts it out of the final {"type":"end"} record), and exits with the CLI's code.
#
# Quirks that live here:
#   - `--prompt-file` alone is single-turn headless; `-p` REQUIRES an inline prompt value, so
#     `-p --prompt-file` is a usage error.
#   - the structured answer is only in the final {"type":"end"} record of the stream.
#   - stdin must not stay an open pipe: </dev/null.
#   - MODE=code-review prefixes grok's own /code-review skill. NEVER write that copy to
#     <base>.prompt.md — that is the path rev-prompt.sh renders to, so > would truncate the file cat
#     is reading and spin forever. A distinct name is also idempotent on a retry.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SUMMARY="$HERE/../lib/stream-summary.py"
EFFORT=${EFFORT:-xhigh}
P="$PROMPT"
if [ "${MODE:-}" = code-review ]; then
  P="${OUT%.json}.cr-prompt.md"; { printf '/code-review\n\n'; cat "$PROMPT"; } > "$P"
fi

set -o pipefail
grok --prompt-file "$P" --cwd "$ROOT" -m "$MODEL" --reasoning-effort "$EFFORT" \
    --permission-mode plan --output-format streaming-json --json-schema "$(cat "$SCHEMA")" \
    --max-turns "${REV_GROK_MAX_TURNS:-120}" </dev/null 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$SUMMARY" grok "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
