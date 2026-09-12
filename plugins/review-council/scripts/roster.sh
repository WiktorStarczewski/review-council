#!/bin/bash
# roster.sh [--json|--brief] [--probe] [--write <file>] - the reviewer roster: which lab CLIs are
# installed and signed in, which models and efforts they seat. A panel is three seats; a thinner one is
# padded with Claude seats and flagged `degraded`. Exit 5 marks retryable availability strictness.
# Exit 6 marks permanent exact-setting conflicts.
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 "$HERE/lib/roster.py" "$@"
