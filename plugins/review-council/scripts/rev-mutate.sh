#!/bin/bash
# rev-mutate.sh <session-dir> <test-command>
#   Reverts each changed hunk on its own, keeping every other change in the tree, and runs the
#   test command. A hunk whose revert leaves the command passing is unpinned: no test proves
#   that line. Exits 0 every hunk pinned, 2 a panel is live or its phase cannot be read, 3 an
#   unpinned hunk, 4 the run measured nothing (a hunk that would not apply, a revert that
#   changed no byte, a changed file with no text hunk, or no changed hunk at all).
#
#   4 outranks 3: a run that could not revert one hunk has not earned a verdict about the rest.
#   A mutation that does not apply is the failure this tool exists to prevent, because it reads
#   exactly like a real measurement, so every revert is proved by hash before its result counts.
#
#   It refuses while a panel is live because seats read the live tree, and a script that reverts
#   hunks for seconds at a time shows them a tree that is neither base nor fix.
#
#   Scope: unstaged changes to tracked files under REV_ROOT. Each hunk is measured against the
#   COMPLETE fix: the file is restored from a backup this run took, never from the commit.
set -u
S=${1:?usage: rev-mutate.sh <session-dir> <test-command>}
CMD=${2:?usage: rev-mutate.sh <session-dir> <test-command>}

[ -f "$S/scope.env" ] || { echo "rev-mutate: no scope.env in $S" >&2; exit 1; }
# shellcheck disable=SC1090
. "$S/scope.env"
ROOT=${REV_ROOT:?rev-mutate: scope.env has no REV_ROOT}

phase=$(python3 - "$S/state.json" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as handle:
        phase = json.load(handle).get('phase') or 'unknown'
except Exception:
    phase = 'unknown'
print(phase)
PY
)
case "$phase" in
  fan-out|collect|plan|repair)
    echo "rev-mutate: refusing while a panel is live (phase=$phase); seats read the live tree" >&2
    exit 2 ;;
  unknown)
    echo "rev-mutate: refusing: $S/state.json names no phase, so a live panel cannot be ruled out" >&2
    echo "rev-mutate: record the phase first, e.g. rev-state.sh $S phase=fix" >&2
    exit 2 ;;
esac

cd "$ROOT" || { echo "rev-mutate: cannot enter $ROOT" >&2; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "rev-mutate: $ROOT is not a git work tree" >&2; exit 1; }
[ -z "$(git rev-parse --show-prefix)" ] \
  || { echo "rev-mutate: $ROOT is not the repository root" >&2; exit 1; }

WORK=$(mktemp -d "${TMPDIR:-/tmp}/rev-mutate.XXXXXX") || exit 1
BK="$WORK/backup"; CUR=""
cleanup() {
  # A mutated file must never outlive this run, however it ends.
  [ -z "$CUR" ] || [ ! -f "$BK" ] || cp -p -- "$BK" "$CUR" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

status=0; unmeasured=0; files_seen=0; hunks_seen=0; unpinned_seen=0
unmeasurable() { echo "rev-mutate: UNMEASURED $*" >&2; unmeasured=1; }

git diff --name-only -z > "$WORK/files"
git ls-files --others --exclude-standard > "$WORK/untracked"
[ ! -s "$WORK/untracked" ] \
  || echo "rev-mutate: NOTE $(grep -c . < "$WORK/untracked") untracked file(s) are outside this measurement" >&2

while IFS= read -r -d '' f <&3; do
  [ -n "$f" ] || continue
  if [ ! -f "$f" ]; then
    unmeasurable "$f is not a regular file in the working tree"
    continue
  fi
  git diff --unified=0 -- "$f" > "$WORK/file.diff"
  count=$(grep -c '^@@' < "$WORK/file.diff")
  if [ "$count" -eq 0 ]; then
    unmeasurable "$f changed with no text hunk (binary or mode change)"
    continue
  fi
  files_seen=$((files_seen + 1))
  cp -p -- "$f" "$BK" || { echo "rev-mutate: cannot back up $f" >&2; exit 1; }
  CUR=$f
  fixhash=$(git hash-object -- "$f")
  i=1
  while [ "$i" -le "$count" ]; do
    hunks_seen=$((hunks_seen + 1))
    awk -v want="$i" '
      /^@@/ { n++; keep = (n == want); if (keep) print; next }
      n == 0 { print; next }
      keep { print }
    ' < "$WORK/file.diff" > "$WORK/hunk.diff"
    if git apply --reverse --unidiff-zero --whitespace=nowarn "$WORK/hunk.diff" 2>/dev/null; then
      if [ "$(git hash-object -- "$f")" = "$fixhash" ]; then
        unmeasurable "hunk $i of $f applied without changing a byte; the mutation was inert"
      elif ( eval "$CMD" ) </dev/null >/dev/null 2>&1; then
        echo "rev-mutate: UNPINNED $f hunk $i - the command passes without it"
        unpinned_seen=$((unpinned_seen + 1))
        status=3
      fi
    else
      unmeasurable "hunk $i of $f would not apply"
    fi
    cp -p -- "$BK" "$f" || { echo "rev-mutate: FATAL cannot restore $f from $BK" >&2; exit 1; }
    [ "$(git hash-object -- "$f")" = "$fixhash" ] || {
      echo "rev-mutate: FATAL $f differs from the fix after its restore; the tree is left mutated" >&2
      exit 1; }
    i=$((i + 1))
  done
  CUR=""
done 3< "$WORK/files"

if [ "$hunks_seen" -eq 0 ]; then
  echo "rev-mutate: measured nothing: no changed hunk under $ROOT" >&2
  unmeasured=1
fi
echo "rev-mutate: reverted $hunks_seen hunk(s) across $files_seen file(s); unpinned=$unpinned_seen"
[ "$unmeasured" -eq 0 ] || exit 4
exit "$status"
