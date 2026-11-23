#!/bin/bash
# curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install-agy.sh | bash
#
# Builds the native Antigravity (agy) package and installs it at
# ~/.gemini/config/plugins/review-council. Running it again replaces that bundle.
# It does not change Claude Code, Codex, Cursor, or Pi installations.
#
# Env: REVIEW_COUNCIL_REF        git branch or tag to clone (default main)
#      REVIEW_COUNCIL_SOURCE     use this checkout instead of cloning
#      REVIEW_COUNCIL_AGY_DEST   install directory (default ~/.gemini/config/plugins/review-council)
set -eu

REF=${REVIEW_COUNCIL_REF:-main}
DEST=${REVIEW_COUNCIL_AGY_DEST:-$HOME/.gemini/config/plugins/review-council}
DEST=${DEST%/}
SOURCE=${REVIEW_COUNCIL_SOURCE:-}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --ref)
      [ "$#" -ge 2 ] && [ -n "$2" ] || { echo 'review-council: --ref needs a Git ref' >&2; exit 2; }
      REF=$2; shift 2;;
    -h|--help) echo 'usage: install-agy.sh [--ref <branch-or-tag>]'; exit 0;;
    *) echo "review-council: unknown option '$1'" >&2; exit 2;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo 'review-council: python3 is required' >&2; exit 1; }
case "$DEST" in
  /*) ;;
  *) echo 'review-council: the Antigravity install directory must be absolute' >&2; exit 2;;
esac
[ "$(basename "$DEST")" = review-council ] || {
  echo 'review-council: the Antigravity install directory must be named review-council' >&2
  exit 2
}

WORK=
cleanup() {
  if [ -n "$WORK" ] && [ -d "$WORK" ]; then
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

if [ -n "$SOURCE" ]; then
  [ -f "$SOURCE/scripts/build-agy-plugin.py" ] || {
    echo 'review-council: REVIEW_COUNCIL_SOURCE is not a review-council checkout' >&2
    exit 1
  }
  ROOT=$SOURCE
else
  command -v git >/dev/null 2>&1 || { echo 'review-council: git is required' >&2; exit 1; }
  parent=${TMPDIR:-/tmp}
  case "$parent" in
    /*) ;;
    *) parent=$(CDPATH= cd -- "$parent" && pwd) || {
         echo "review-council: TMPDIR is not a directory: ${TMPDIR:-/tmp}" >&2
         exit 1
       } ;;
  esac
  WORK=$(mktemp -d "$parent/review-council-agy.XXXXXX")
  git clone --depth 1 --branch "$REF" https://github.com/WiktorStarczewski/review-council.git "$WORK"
  ROOT=$WORK
fi

python3 "$ROOT/scripts/build-agy-plugin.py" --output "$DEST"
VERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' \
  "$DEST/plugin.json")
echo "Installed Review Council $VERSION for Antigravity at $DEST"
echo "Start a new agy session to load rev and stack."
