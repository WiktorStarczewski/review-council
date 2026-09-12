#!/bin/bash
# rev-preflight.sh [--scope branch|uncommitted|<path>] [--write <session-dir>] [--base <ref>]
# The base branch is, in order: --base, $REV_BASE_REF, the open PR's base (gh, when installed and signed in),
# the nearest fork point among the long-lived branches (origin/HEAD's, next, develop, dev, release), else
# origin/HEAD's. origin/HEAD alone was wrong for every branch cut from a `next` line: the review then
# included everything next carried past main (74 commits in one repo).
# Refuse a bad start (exit 1 + one-line reason on stderr), or print the pinned scope and the usable seats.
# --write stores scope.env (REV_BASE/REV_BRANCH/REV_DEFAULT/REV_ROOT/REV_SCOPE) + files.txt + untracked.txt
# + roster.json in <session-dir>.
# scope.env values are SINGLE-QUOTED (with '\'' escaping) so `. scope.env` can never expand or execute a branch
# name or a path: a branch called `x$(touch pwned)` is data, not a command.
# The seats come from roster.sh, which owns detection, sign-in and the one-token probe - preflight never
# calls a lab CLI itself. A thin roster is NOT a refusal: roster.sh pads the panel to three with Claude
# seats and flags it `degraded`, and preflight relays that as a WARNING line under the roster line.
# Strict availability failures use exit 5. Permanent exact-setting conflicts use exit 6.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SCOPE=branch; WRITE=""; BASEREF=${REV_BASE_REF:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE=${2:?}; shift 2;;
    --write) WRITE=${2:?}; shift 2;;
    --base) BASEREF=${2:?}; shift 2;;
    *) echo "rev-preflight: unknown argument $1" >&2; exit 1;;
  esac
done
die() { echo "preflight: $*" >&2; exit 1; }
q() { local s=$1; s=${s//\'/\'\\\'\'}; printf "'%s'" "$s"; }   # shell-quote one value for scope.env
[ -z "${REV_ACTIVE:-}" ] || die "REV_ACTIVE is set - a review is already running here; refusing to nest"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
# --write is relative to the CALLER's cwd: resolve it before the cd to the repo root, or `--write sess`
# from a subdirectory would silently land at <repo-root>/sess.
case "$WRITE" in ""|/*) ;; *) WRITE="$PWD/$WRITE";; esac
ROOT=$(git rev-parse --show-toplevel); cd "$ROOT" || die "cannot cd to $ROOT"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
if [ -z "$DEFAULT" ]; then
  for cand in main master; do git show-ref --verify -q "refs/heads/$cand" && { DEFAULT=$cand; break; }; done
fi
[ -n "$DEFAULT" ] || die "cannot determine the default branch (no origin/HEAD, no local main or master)"
# ref_for <name> → the ref to measure against: the remote-tracking branch when it exists, else the local one.
ref_for() { git show-ref --verify -q "refs/remotes/origin/$1" && { echo "origin/$1"; return; }; git show-ref --verify -q "refs/heads/$1" && { echo "$1"; return; }; return 1; }
BASE_BRANCH=""; BASE_HOW=""
if [ -n "$BASEREF" ]; then
  BASE_BRANCH=$BASEREF; BASE_HOW="given"
  BASE_TARGET=$(ref_for "$BASEREF" || git rev-parse --verify -q "$BASEREF^{commit}") || die "base '$BASEREF' is not a branch, tag or commit here"
else
  if command -v gh >/dev/null 2>&1; then
    prb=$(GH_PROMPT_DISABLED=1 gh pr view --json baseRefName -q .baseRefName 2>/dev/null || true)
    [ -n "$prb" ] && ref_for "$prb" >/dev/null && { BASE_BRANCH=$prb; BASE_HOW="open PR"; }
  fi
  if [ -z "$BASE_BRANCH" ]; then
    # nearest fork point: the candidate with the fewest commits between its merge-base and HEAD is the branch
    # this one was cut from; ties go to the default branch (listed first).
    bestn=""
    for cand in "$DEFAULT" next develop dev release; do
      r=$(ref_for "$cand") || continue
      mb=$(git merge-base HEAD "$r" 2>/dev/null) || continue
      n=$(git rev-list --count "$mb..HEAD")
      if [ -z "$bestn" ] || [ "$n" -lt "$bestn" ]; then BASE_BRANCH=$cand; bestn=$n; fi
    done
    BASE_HOW="nearest fork point"
  fi
  [ -n "$BASE_BRANCH" ] || { BASE_BRANCH=$DEFAULT; BASE_HOW="default"; }
  BASE_TARGET=$(ref_for "$BASE_BRANCH") || die "cannot resolve base branch $BASE_BRANCH"
fi
case "$BRANCH" in main|master|"$DEFAULT"|"$BASE_BRANCH") die "HEAD is on shared branch '$BRANCH' - cut a working branch first";; esac
# Pathspec as an array so a scope path containing spaces survives; ${P[@]+…} keeps bash 3.2 + set -u happy on an empty array.
PS=()
if [ "$SCOPE" = uncommitted ]; then
  BASE=$(git rev-parse HEAD)
  [ -n "$(git status --porcelain)" ] || die "scope is empty - no uncommitted changes"
else
  BASE=$(git merge-base HEAD "$BASE_TARGET" 2>/dev/null) || die "cannot find the merge-base with $BASE_TARGET"
  if [ "$SCOPE" != branch ]; then
    # A path the change DELETES is still a reviewable scope: accept it if it exists in the worktree OR at the base.
    [ -e "$SCOPE" ] || git cat-file -e "$BASE:$SCOPE" 2>/dev/null \
      || die "path '$SCOPE' does not exist in the worktree or at $BASE"
    PS=(-- "$SCOPE")
  fi
  [ -n "$(git diff --stat "$BASE" ${PS[@]+"${PS[@]}"})$(git status --porcelain ${PS[@]+"${PS[@]}"})" ] || die "scope is empty - nothing differs from $BASE${PS[0]+ under $SCOPE}"
fi
# --- seats -------------------------------------------------------------------------------------------
# The roster is built AFTER the git checks: a run that is going to be refused for scope reasons must not
# spend a probe. --probe costs one token per CLI seat and drops the ones that cannot answer.
# ONE call does both jobs: --write stores the JSON the fan-out reads, --brief prints the human line from
# the SAME probed roster (asking twice would probe twice and could print a seat the probe had just dropped).
if [ -n "$WRITE" ]; then
  mkdir -p "$WRITE" || die "cannot create session dir $WRITE"
  RJSON="$WRITE/roster.json"
else
  SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/rev-preflight.XXXXXX") \
    || die "cannot create a temporary directory for the roster"
  RJSON="$SCRATCH/roster.json"
  trap 'rm -rf -- "$SCRATCH"' EXIT
fi
BRIEF=$("$HERE/roster.sh" --probe --brief --write "$RJSON"); RC=$?
if [ "$RC" = 5 ] || [ "$RC" = 6 ]; then
  # Only the roster may assign a strict status. Preserve it after validating that the written
  # object carries the matching class and a concrete one-line cause.
  if [ "$RC" = 6 ]; then CLASS=config; KIND=permanent; else CLASS=availability; KIND=retryable; fi
  REASON=$(ROSTER_JSON="$RJSON" EXPECTED_CLASS="$CLASS" python3 - <<'PY'
import json, os
try:
    with open(os.environ['ROSTER_JSON']) as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError('not an object')
    if not isinstance(d.get('seats'), list) or not isinstance(d.get('excluded'), list):
        raise ValueError('invalid roster shape')
    reason = d.get('strict_reason')
    if d.get('strict_class') != os.environ['EXPECTED_CLASS']:
        raise ValueError('class mismatch')
    if not isinstance(reason, str) or not reason.strip() or '\n' in reason or '\r' in reason:
        raise ValueError('invalid reason')
    print(reason)
except Exception:
    raise SystemExit(2)
PY
  ); META_RC=$?
  [ "$META_RC" = 0 ] || die "roster.sh returned exit $RC without valid matching strict metadata"
  [ -z "$BRIEF" ] || printf '%s\n' "$BRIEF" >&2
  printf 'preflight: strict %s (%s): %s\n' "$CLASS" "$KIND" "$REASON" >&2
  exit "$RC"
fi
[ "$RC" = 0 ] || die "roster.sh failed (exit $RC) - run $HERE/roster.sh --json to see why"
# -z + tr, never field-splitting: git quotes paths containing spaces in porcelain/diff output otherwise.
UNTRACKED=$(git ls-files -z --others --exclude-standard ${PS[@]+"${PS[@]}"} | tr '\0' '\n' | grep .)
FILES=$( { git diff --name-only -z "$BASE" ${PS[@]+"${PS[@]}"} | tr '\0' '\n'
           printf '%s\n' "$UNTRACKED"; } | sort -u | grep . )
N=$(printf '%s\n' "$FILES" | grep -c .)
echo "base=$BASE base_branch=$BASE_BRANCH ($BASE_HOW) branch=$BRANCH default=$DEFAULT root=$ROOT scope=$SCOPE changed_files=$N"
[ -n "$BRIEF" ] && printf '%s\n' "$BRIEF"
# A degraded panel runs, loudly. The roster line already ends in `· DEGRADED: …`; this second line makes
# it impossible to miss in a transcript, and the skill copies the sentence verbatim into the report.
WARN=$(ROSTER_JSON="$RJSON" python3 - <<'PY'
import json, os
try:
    with open(os.environ['ROSTER_JSON']) as f:
        d = json.load(f)
    if isinstance(d, dict) and d.get('degraded'):
        print(d.get('degradation') or 'the panel is short of voices')
except Exception:
    pass
PY
)
[ -z "$WARN" ] || printf 'preflight: WARNING - %s\n' "$WARN"
if [ -n "$WRITE" ]; then
  { printf 'REV_BASE=%s\n'    "$(q "$BASE")"
    printf 'REV_BRANCH=%s\n'  "$(q "$BRANCH")"
    printf 'REV_DEFAULT=%s\n' "$(q "$DEFAULT")"
    printf 'REV_BASE_BRANCH=%s\n' "$(q "$BASE_BRANCH")"
    printf 'REV_ROOT=%s\n'    "$(q "$ROOT")"
    printf 'REV_SCOPE=%s\n'   "$(q "$SCOPE")"
  } > "$WRITE/scope.env" || die "cannot write $WRITE/scope.env"
  printf '%s\n' "$FILES" > "$WRITE/files.txt" || die "cannot write $WRITE/files.txt"
  # untracked files are invisible to `git diff`: the seats are told to read them in full (rev-prompt.sh)
  if [ -n "$UNTRACKED" ]; then printf '%s\n' "$UNTRACKED" > "$WRITE/untracked.txt" || die "cannot write $WRITE/untracked.txt"
  else : > "$WRITE/untracked.txt" || die "cannot write $WRITE/untracked.txt"; fi
fi
exit 0
