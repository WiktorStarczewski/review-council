#!/bin/bash
# agy adapter - run one read-only Gemini reviewer seat through Antigravity (`agy`).
#
# Google ToC gate: Gemini models via `agy` are permitted ONLY when orchestrating inside `agy`
# (`REVIEW_COUNCIL_HOST=agy`). Called by rev-seat.sh with:
#   SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SUMMARY="$HERE/../lib/stream-summary.py"
if [ "${REVIEW_COUNCIL_HOST:-}" != agy ]; then
  printf 'agy adapter: requires REVIEW_COUNCIL_HOST=agy\n' >> "${LOG:-/dev/null}"
  printf 'agy adapter: requires REVIEW_COUNCIL_HOST=agy\n' >&2
  exit 1
fi
[ -n "${EFFORT:-}" ] || {
  printf 'agy adapter: missing receipted effort\n' >> "${LOG:-/dev/null}"
  printf 'agy adapter: missing receipted effort\n' >&2
  exit 1
}
[ -f "$PROMPT" ] && [ -r "$PROMPT" ] || {
  printf 'agy adapter: prompt missing: %s\n' "${PROMPT:-}" >> "${LOG:-/dev/null}"
  printf 'agy adapter: prompt missing: %s\n' "${PROMPT:-}" >&2
  exit 1
}
SESSION_DIR=$(dirname "$OUT")
ADD_DIRS=(--add-dir "$SESSION_DIR")
if [ -n "${REV_DEPS_DIR:-}" ]; then
  ADD_DIRS+=(--add-dir "$REV_DEPS_DIR")
fi
set -o pipefail
( cd "$ROOT" && python3 -c 'import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    print(json.dumps({"event": "user", "message": {"content": fh.read()}}))' "$PROMPT" \
  | agy --model "$MODEL" --input-format stream-json --output-format stream-json \
      --json-schema "$SCHEMA" "${ADD_DIRS[@]}" --disable-slash-commands --sandbox ) 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$SUMMARY" agy "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
