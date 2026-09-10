#!/bin/bash
# curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install-codex.sh | bash
set -eu
REF=${REVIEW_COUNCIL_REF:-main}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref)
      [ "$#" -ge 2 ] && [ -n "$2" ] || { echo 'review-council: --ref needs a Git ref' >&2; exit 2; }
      REF=$2; shift 2;;
    -h|--help) echo 'usage: install-codex.sh [--ref <branch-or-tag>]'; exit 0;;
    *) echo "review-council: unknown option '$1'" >&2; exit 2;;
  esac
done
command -v codex >/dev/null 2>&1 || { echo 'review-council: install the Codex CLI first (plugin support required)' >&2; exit 1; }
codex plugin marketplace add WiktorStarczewski/review-council --ref "$REF"
codex plugin add review-council@review-council
echo 'Installed Review Council. Start a new Codex chat to load its skills.'
