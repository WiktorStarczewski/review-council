#!/bin/bash
# roster.sh [--json|--brief] [--probe] [--write <file>] — the reviewer roster: which lab CLIs are
# installed and signed in, which models and efforts they seat. Exit 0 with >= 3 seats, 5 with fewer.
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 "$HERE/lib/roster.py" "$@"
