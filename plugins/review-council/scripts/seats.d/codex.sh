#!/bin/bash
# codex adapter — run one read-only codex reviewer seat.
#
# Called by rev-seat.sh with the adapter environment contract:
#   SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
# Streams the CLI's events to $RAW, one summarised line each to $LOG, leaves findings JSON at $OUT,
# and exits with the CLI's own exit code. Validation, retries and failure classification are the
# wrapper's job — this file is only the invocation and the quirks that come with it.
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

set -o pipefail
if [ "${MODE:-}" = review ]; then
  ( cd "$ROOT" && codex exec review --base "$BASE" --ephemeral -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
      -c 'sandbox_mode="read-only"' \
      --json --output-schema "$SCHEMA" -o "$OUT" $GITCHECK </dev/null ) 2>>"$LOG" \
    | tee "$RAW" | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
  rc=${PIPESTATUS[0]}
else
  codex exec --ephemeral -s read-only -C "$ROOT" -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
      --json --output-schema "$SCHEMA" -o "$OUT" $GITCHECK - < "$PROMPT" 2>>"$LOG" \
    | tee "$RAW" | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
  rc=${PIPESTATUS[0]}
fi
exit "$rc"
