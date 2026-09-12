#!/bin/bash
# grok adapter - run one read-only grok reviewer seat.
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
#     <base>.prompt.md - that is the path rev-prompt.sh renders to, so > would truncate the file cat
#     is reading and spin forever. A distinct name is also idempotent on a retry.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SUMMARY="$HERE/../lib/stream-summary.py"
EFFORT=${EFFORT:-xhigh}
P="$PROMPT"
GROK_STATE_HOME=${GROK_HOME:-$HOME/.grok}
HOME_HELPER="$HERE/../lib/isolated-seat-home.py"
PRIVATE_HOME=$(python3 "$HOME_HELPER" path grok "$OUT") || exit 1
LEASE_READY=$(mktemp "${TMPDIR:-/tmp}/review-council-grok-ready.XXXXXX") || exit 1
LEASE_PID=""
cleanup_home() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$LEASE_PID" ]; then
    kill -TERM "$LEASE_PID" >/dev/null 2>&1 || true
    wait "$LEASE_PID" >/dev/null 2>&1 || true
  fi
  rm -f "$LEASE_READY"
  return "$status"
}
trap cleanup_home EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
python3 "$HOME_HELPER" hold grok "$PRIVATE_HOME" --parent "$$" > "$LEASE_READY" &
LEASE_PID=$!
while [ ! -s "$LEASE_READY" ] && kill -0 "$LEASE_PID" >/dev/null 2>&1; do sleep 0.02; done
if [ ! -s "$LEASE_READY" ]; then
  wait "$LEASE_PID"; lease_status=$?
  [ "$lease_status" -ne 0 ] || lease_status=1
  exit "$lease_status"
fi
VERBATIM=--verbatim
if [ "${MODE:-}" = code-review ]; then
  P="${OUT%.json}.cr-prompt.md"; { printf '/code-review\n\n'; cat "$PROMPT"; } > "$P"
  VERBATIM=""
fi

set -o pipefail
HOME="$PRIVATE_HOME" GROK_HOME="$GROK_STATE_HOME" grok $VERBATIM --prompt-file "$P" \
    --cwd "$ROOT" -m "$MODEL" --reasoning-effort "$EFFORT" \
    --permission-mode plan --output-format streaming-json --json-schema "$(cat "$SCHEMA")" \
    --max-turns "${REV_GROK_MAX_TURNS:-120}" </dev/null 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$SUMMARY" grok "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
