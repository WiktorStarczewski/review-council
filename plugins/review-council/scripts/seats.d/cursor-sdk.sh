#!/bin/bash
# The frozen SDK assignment and prior live receipt are validated before import.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SESSION=$(dirname "$OUT")
STEM=$(basename "$OUT" .json)
PREFIX="r${ROUND:-}"
if [ -z "${ROUND:-}" ]; then
  PREFIX=${STEM%"-$SEAT"}
  ROUND=${PREFIX#r}
fi
set -o pipefail
node "$HERE/../lib/cursor-sdk-driver.mjs" seat --session "$SESSION" --round "$ROUND" \
  --seat "$SEAT" --prompt "$PROMPT" --root "$ROOT" 2>>"$LOG" \
  | python3 -u "$HERE/../lib/stream-summary.py" cursor-sdk "$OUT.summary-candidate.json" >>"$LOG"
exit "${PIPESTATUS[0]}"
