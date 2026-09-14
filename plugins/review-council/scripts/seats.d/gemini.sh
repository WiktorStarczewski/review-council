#!/bin/bash
# gemini adapter - run one read-only gemini reviewer seat.
#
# Called by rev-seat.sh with the adapter environment contract:
#   SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
# Streams the CLI's events to $RAW, one summarised line each to $LOG, leaves findings JSON at $OUT,
# and exits with the CLI's code.
#
# Quirks that live here:
#   - gemini has no --cwd: it reviews whatever directory it is started in, so run it from $ROOT.
#   - it has no schema flag and no reasoning-effort knob. The renderer puts the schema in the
#     prompt; stream-summary.py lifts the outermost
#     JSON object out of the final assistant message and the wrapper validates it.
#   - EFFORT is ignored on purpose: the roster records `null` for this seat.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SUMMARY="$HERE/../lib/stream-summary.py"
INSTRUCTION='Follow the instructions on stdin exactly. Run your tools first - never answer before reading the code. Answer with only the JSON object requested.'

set -o pipefail
( cd "$ROOT" && gemini -p "$INSTRUCTION" -m "$MODEL" --approval-mode plan -o stream-json ) < "$PROMPT" 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$SUMMARY" gemini "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
