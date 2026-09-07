#!/bin/bash
# bench.sh <cases.tsv> <tag> [parallel]  — run every case blind against the current lens, build truth once per case,
# score each run, print one summary line per case. cases.tsv columns (whitespace): name  owner/repo  pr  clone-url
# review-head  base  merged. Results under eval/runs/<tag>/<name>/; truth under eval/truth/<name>/ (shared across tags).
set -u
CASES=$1; TAG=$2; PAR=${3:-3}
HERE=$(cd "$(dirname "$0")" && pwd)
one() {
  read -r name repo pr url head base merged <<< "$1"   # whitespace-separated; no field ever contains a space
  RUN="$HERE/runs/$TAG/$name"; TR="$HERE/truth/$name"
  # eval/nopr.txt lists cases whose PR description was edited after the first review (it could describe the final
  # design); those run without --pr so the description cannot leak the answer.
  pr_repo=$repo; pr_num=$pr; { [ "${NOPR_ALL:-}" = 1 ] || grep -qx "$name" "$HERE/nopr.txt" 2>/dev/null; } && { pr_repo=""; pr_num=""; }   # NOPR_ALL=1: ablation without any PR description
  "$HERE/bench-case.sh" "$name" "$url" "$head" "$base" "$RUN" "${LENSES:-simplicity}" "$pr_repo" "$pr_num" > "$RUN.seats.txt" 2>&1 || { echo "$name: seats failed: $(tail -1 "$RUN.seats.txt")"; return; }
  [ -s "$TR/truth.md" ] || "$HERE/bench-truth.sh" "$name" "$repo" "$pr" "$head" "$base" "$merged" "$TR" > "$TR.txt" 2>&1 || { echo "$name: truth failed"; return; }
  "$HERE/bench-score.sh" "$name" "$repo" "$pr" "$head" "$merged" "$RUN" "$TR/truth.md" "$TR/full"
}
export -f one; export HERE TAG LENSES NOPR_ALL
mkdir -p "$HERE/runs/$TAG" "$HERE/truth"
grep -v '^#' "$CASES" | grep -v '^$' | xargs -P "$PAR" -I{} bash -c 'one "$@"' _ {}
