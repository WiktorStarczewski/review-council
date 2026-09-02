#!/bin/bash
# One-line install for review-council:  curl -fsSL https://raw.githubusercontent.com/zoroswap/review-council/main/install.sh | bash
set -eu
command -v claude >/dev/null 2>&1 || { echo "review-council: the claude CLI is not on PATH (install Claude Code first)" >&2; exit 1; }
claude plugin marketplace add zoroswap/review-council 2>/dev/null || claude plugin marketplace update review-council
claude plugin install review-council@review-council
echo
echo "review-council installed. Restart Claude Code (or run /reload-plugins), then use /review-council:rev."
echo "Seats are built from the lab CLIs on this machine; the session banner shows which were detected."
