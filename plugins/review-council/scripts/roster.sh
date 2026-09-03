#!/bin/bash
# roster.sh [--json|--brief] [--probe] [--write <file>] — the reviewer roster: which lab CLIs are
# installed and signed in, which models and efforts they seat. A panel is three seats; a thinner one is
# padded with Claude seats and flagged `degraded`, never refused. Exit 0 whenever a panel exists (always);
# exit 5 only in strict mode, when config `min_labs` asks for more distinct labs than the machine has.
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 "$HERE/lib/roster.py" "$@"
