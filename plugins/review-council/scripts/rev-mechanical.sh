#!/bin/bash
# One call for a deterministic host phase: ci, publish, or closeout.
# Seat coverage, audits, and receipts are not decided here.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CMD=${1:?usage: rev-mechanical.sh <ci|publish|closeout> <session>}
S=${2:?usage: rev-mechanical.sh <ci|publish|closeout> <session>}
[ -d "$S" ] || { echo "rev-mechanical: session is not a directory: $S" >&2; exit 2; }

case "$CMD" in
  ci)
    RUN=$(python3 - "$S" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1]) / 'state.json'
try:
    state = json.loads(path.read_text(encoding='utf-8'))
except (OSError, UnicodeError, json.JSONDecodeError):
    state = {}
run = state.get('ci_run') if isinstance(state, dict) else None
if not isinstance(run, (str, int)) or not str(run).strip():
    raise SystemExit(2)
print(str(run).strip())
PY
    ) || { echo 'rev-mechanical: state.json has no ci_run' >&2; exit 2; }
    # One bounded call: a host tool call times out near ten minutes and a turn that ends to wait
    # reaches the parent as a notification. 124 means still running; call again.
    POLL=${REV_CI_POLL_SECS:-30}
    DEADLINE=$((SECONDS + ${REV_CI_WAIT_SECS:-540}))
    while :; do
      STATE=$(gh run view "$RUN" --json status,conclusion --jq '.status + " " + .conclusion' 2>/dev/null) || STATE=
      set -- $STATE
      if [ "${1:-}" = completed ]; then
        echo "ci run $RUN: completed ${2:-}"
        [ "${2:-}" = success ] && exit 0
        exit 1
      fi
      [ "$SECONDS" -lt "$DEADLINE" ] || { echo "ci run $RUN still running (${1:-status unavailable}); call again" >&2; exit 124; }
      sleep "$POLL"
    done
    ;;
  publish)
    python3 "$HERE/rev-pr-review.py" render "$S"
    python3 "$HERE/rev-pr-review.py" publish "$S"
    ;;
  closeout)
    python3 "$HERE/rev-brief.py" "$S" --host "${REVIEW_COUNCIL_HOST:-claude}"
    ;;
  *)
    echo "rev-mechanical: unknown command: $CMD" >&2
    exit 2
    ;;
esac
