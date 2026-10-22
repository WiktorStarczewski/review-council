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
    gh run watch "$RUN" --exit-status
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
