#!/bin/bash
# codex adapter - run one read-only codex reviewer seat.
#
# Called by rev-seat.sh with the adapter environment contract:
#   SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
# Streams the CLI's events to $RAW, one summarised line each to $LOG, leaves findings JSON at $OUT,
# and exits with the CLI's own exit code. Validation, retries and failure classification are the
# wrapper's job - this file is only the invocation and the quirks that come with it.
#
# Quirks that live here:
#   - codex reads stdin until EOF and BLOCKS on an open pipe: the prompt file is its stdin (`- < file`).
#   - `codex exec review` has no -C and no -s, and `--base` cannot be combined with a custom prompt:
#     that seat runs codex's OWN review prompt (that is its value) with only our output schema, from
#     $ROOT, and pins the read-only sandbox through config instead of the missing -s flag.
#   - a non-git root (a read-only panel on a document) needs --skip-git-repo-check.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SUMMARY="$HERE/../lib/stream-summary.py"
EFFORT=${EFFORT:-max}
GITCHECK=""
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || GITCHECK="--skip-git-repo-check"
CODEX_STATE_HOME=${CODEX_HOME:-$HOME/.codex}
HOME_HELPER="$HERE/../lib/isolated-seat-home.py"
PRIVATE_HOME=$(python3 "$HOME_HELPER" path codex "$OUT") || exit 1
LEASE_READY=$(mktemp "${TMPDIR:-/tmp}/review-council-codex-ready.XXXXXX") || exit 1
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
if [ -f "$CODEX_STATE_HOME/auth.json" ]; then
  python3 "$HOME_HELPER" hold codex "$PRIVATE_HOME" --parent "$$" \
    --auth "$CODEX_STATE_HOME/auth.json" > "$LEASE_READY" &
else
  python3 "$HOME_HELPER" hold codex "$PRIVATE_HOME" --parent "$$" > "$LEASE_READY" &
fi
LEASE_PID=$!
while [ ! -s "$LEASE_READY" ] && kill -0 "$LEASE_PID" >/dev/null 2>&1; do sleep 0.02; done
if [ ! -s "$LEASE_READY" ]; then
  wait "$LEASE_PID"; lease_status=$?
  [ "$lease_status" -ne 0 ] || lease_status=1
  exit "$lease_status"
fi

set -o pipefail
if [ "${MODE:-}" = review ]; then
  ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec review --base "$BASE" --ephemeral \
      --ignore-user-config -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
      -c project_doc_max_bytes=0 -c 'sandbox_mode="read-only"' \
      --json --output-schema "$SCHEMA" -o "$OUT" $GITCHECK </dev/null ) 2>>"$LOG" \
    | tee "$RAW" | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
  rc=${PIPESTATUS[0]}
else
  CODEX_HOME="$PRIVATE_HOME" codex exec --ephemeral --ignore-user-config -s read-only -C "$ROOT" \
      -m "$MODEL" -c model_reasoning_effort="$EFFORT" -c project_doc_max_bytes=0 \
      --json --output-schema "$SCHEMA" -o "$OUT" $GITCHECK - < "$PROMPT" 2>>"$LOG" \
    | tee "$RAW" | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
  rc=${PIPESTATUS[0]}
fi
exit "$rc"
