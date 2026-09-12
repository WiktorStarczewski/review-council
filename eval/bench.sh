#!/bin/bash
# bench.sh <cases.tsv> <tag> [parallel]  - run every case blind against the current lens, build truth once per case,
# score each run, print one summary line per case. cases.tsv columns (whitespace): name  owner/repo  pr  clone-url
# review-head  base  merged. Results under eval/runs/<tag>/<name>/; truth under eval/truth/<name>/ (shared across tags).
set -u
CASES=$1; TAG=$2; PAR=${3:-3}
HERE=$(cd "$(dirname "$0")" && pwd)
if [ ! -f "$CASES" ] || [ ! -r "$CASES" ]; then
  echo "bench: cases file is missing or unreadable: $CASES" >&2
  exit 1
fi
EFFECTIVE_CASES=$(mktemp /tmp/review-council-cases.XXXXXX) || exit 1
trap 'rm -f "$EFFECTIVE_CASES"' EXIT
awk '!/^[[:space:]]*#/ && NF { print }' "$CASES" > "$EFFECTIVE_CASES"
cases_rc=$?
if [ "$cases_rc" -ne 0 ]; then
  echo "bench: cannot read cases file: $CASES" >&2
  exit "$cases_rc"
fi
if [ ! -s "$EFFECTIVE_CASES" ]; then
  echo "bench: cases file has no effective cases: $CASES" >&2
  exit 1
fi
one() {
  read -r name repo pr url head base merged <<< "$1"   # whitespace-separated; no field ever contains a space
  RUN="$HERE/runs/$TAG/$name"; TR="$HERE/truth/$name"
  # eval/nopr.txt lists cases whose PR description was edited after the first review (it could describe the final
  # design); those run without --pr so the description cannot leak the answer.
  pr_repo=$repo; pr_num=$pr; { [ "${NOPR_ALL:-}" = 1 ] || grep -qx "$name" "$HERE/nopr.txt" 2>/dev/null; } && { pr_repo=""; pr_num=""; }   # NOPR_ALL=1: ablation without any PR description
  "$HERE/bench-case.sh" "$name" "$url" "$head" "$base" "$RUN" "${LENSES:-simplicity}" "$pr_repo" "$pr_num" > "$RUN.seats.txt" 2>&1
  local rc=$?
  if [ "$rc" -ne 0 ]; then echo "$name: seats failed: $(tail -1 "$RUN.seats.txt")"; return "$rc"; fi
  if [ ! -s "$TR/truth.md" ] || [ ! -s "$TR/truth.complete" ]; then
    "$HERE/bench-truth.sh" "$name" "$repo" "$pr" "$head" "$base" "$merged" "$TR" > "$TR.txt" 2>&1
    rc=$?
    if [ "$rc" -ne 0 ]; then echo "$name: truth failed: $(tail -1 "$TR.txt")"; return "$rc"; fi
  fi
  "$HERE/bench-score.sh" "$name" "$repo" "$pr" "$head" "$merged" "$RUN" "$TR/truth.md" "$TR/full"
}
export -f one; export HERE TAG LENSES NOPR_ALL
mkdir -p "$HERE/runs/$TAG" "$HERE/truth"
xargs -P "$PAR" -I{} bash -c 'one "$@"' _ {} < "$EFFECTIVE_CASES"
exit $?
