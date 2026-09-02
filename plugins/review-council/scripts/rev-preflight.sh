#!/bin/bash
# rev-preflight.sh [--scope branch|uncommitted|<path>] [--write <session-dir>]
# Refuse a bad start (exit 1 + one-line reason on stderr), or print the pinned scope and the usable seats.
# --write stores scope.env (REV_BASE/REV_BRANCH/REV_DEFAULT/REV_ROOT/REV_SCOPE) + files.txt + untracked.txt
# + roster.json in <session-dir>.
# scope.env values are SINGLE-QUOTED (with '\'' escaping) so `. scope.env` can never expand or execute a branch
# name or a path: a branch called `x$(touch pwned)` is data, not a command.
# The seats come from roster.sh, which owns detection, sign-in and the one-token probe — preflight never
# calls a lab CLI itself.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SCOPE=branch; WRITE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE=${2:?}; shift 2;;
    --write) WRITE=${2:?}; shift 2;;
    *) echo "rev-preflight: unknown argument $1" >&2; exit 1;;
  esac
done
die() { echo "preflight: $*" >&2; exit 1; }
q() { local s=$1; s=${s//\'/\'\\\'\'}; printf "'%s'" "$s"; }   # shell-quote one value for scope.env
[ -z "${REV_ACTIVE:-}" ] || die "REV_ACTIVE is set — a review is already running here; refusing to nest"
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
case "$BRANCH" in main|master|"$DEFAULT") die "HEAD is on shared branch '$BRANCH' — cut a working branch first";; esac
# Pathspec as an array so a scope path containing spaces survives; ${P[@]+…} keeps bash 3.2 + set -u happy on an empty array.
PS=()
if [ "$SCOPE" = uncommitted ]; then
  BASE=$(git rev-parse HEAD)
  [ -n "$(git status --porcelain)" ] || die "scope is empty — no uncommitted changes"
else
  BASE=$(git merge-base HEAD "origin/$DEFAULT" 2>/dev/null || git merge-base HEAD "$DEFAULT" 2>/dev/null) || die "cannot find the merge-base with $DEFAULT"
  if [ "$SCOPE" != branch ]; then
    # A path the change DELETES is still a reviewable scope: accept it if it exists in the worktree OR at the base.
    [ -e "$SCOPE" ] || git cat-file -e "$BASE:$SCOPE" 2>/dev/null \
      || die "path '$SCOPE' does not exist in the worktree or at $BASE"
    PS=(-- "$SCOPE")
  fi
  [ -n "$(git diff --stat "$BASE" ${PS[@]+"${PS[@]}"})$(git status --porcelain ${PS[@]+"${PS[@]}"})" ] || die "scope is empty — nothing differs from $BASE${PS[0]+ under $SCOPE}"
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
  RJSON=$(mktemp "${TMPDIR:-/tmp}/rev-roster.XXXXXX") || die "cannot create a temporary file for the roster"
  trap 'rm -f "$RJSON"' EXIT
fi
BRIEF=$("$HERE/roster.sh" --probe --brief --write "$RJSON"); RC=$?
if [ "$RC" = 5 ]; then
  # roster.sh still emits JSON when it refuses: report the seat count and every exclusion reason.
  NR=$(ROSTER_JSON="$RJSON" python3 - <<'PY'
import json, os
try:
    with open(os.environ['ROSTER_JSON']) as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError('not an object')
    seats = [s for s in (d.get('seats') or []) if isinstance(s, dict) and not s.get('extra')]
    ex = [e for e in (d.get('excluded') or []) if isinstance(e, dict)]
    reasons = '; '.join(f"{e.get('cli', '?')}: {e.get('reason', '?')}" for e in ex) or 'no reason recorded'
    print(f"{len(seats)}|{reasons}")
except Exception:
    print("0|roster JSON unreadable")
PY
)
  die "only ${NR%%|*} seats available (need 3): ${NR#*|}"
fi
[ "$RC" = 0 ] || die "roster.sh failed (exit $RC) — run $HERE/roster.sh --json to see why"
# -z + tr, never field-splitting: git quotes paths containing spaces in porcelain/diff output otherwise.
UNTRACKED=$(git ls-files -z --others --exclude-standard ${PS[@]+"${PS[@]}"} | tr '\0' '\n' | grep .)
FILES=$( { git diff --name-only -z "$BASE" ${PS[@]+"${PS[@]}"} | tr '\0' '\n'
           printf '%s\n' "$UNTRACKED"; } | sort -u | grep . )
N=$(printf '%s\n' "$FILES" | grep -c .)
echo "base=$BASE branch=$BRANCH default=$DEFAULT root=$ROOT scope=$SCOPE changed_files=$N"
[ -n "$BRIEF" ] && printf '%s\n' "$BRIEF"
if [ -n "$WRITE" ]; then
  { printf 'REV_BASE=%s\n'    "$(q "$BASE")"
    printf 'REV_BRANCH=%s\n'  "$(q "$BRANCH")"
    printf 'REV_DEFAULT=%s\n' "$(q "$DEFAULT")"
    printf 'REV_ROOT=%s\n'    "$(q "$ROOT")"
    printf 'REV_SCOPE=%s\n'   "$(q "$SCOPE")"
  } > "$WRITE/scope.env" || die "cannot write $WRITE/scope.env"
  printf '%s\n' "$FILES" > "$WRITE/files.txt" || die "cannot write $WRITE/files.txt"
  # untracked files are invisible to `git diff`: the seats are told to read them in full (rev-prompt.sh)
  if [ -n "$UNTRACKED" ]; then printf '%s\n' "$UNTRACKED" > "$WRITE/untracked.txt" || die "cannot write $WRITE/untracked.txt"
  else : > "$WRITE/untracked.txt" || die "cannot write $WRITE/untracked.txt"; fi
fi
exit 0
