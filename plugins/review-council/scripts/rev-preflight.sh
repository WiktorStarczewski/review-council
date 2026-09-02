#!/bin/bash
# rev-preflight.sh [--scope branch|uncommitted|<path>] [--write <session-dir>]
# Refuse a bad start (exit 1 + one-line reason on stderr), or print the pinned scope and the usable seats.
# --write stores scope.env (REV_BASE/REV_BRANCH/REV_DEFAULT/REV_ROOT/REV_SCOPE) + files.txt + untracked.txt in <session-dir>.
# scope.env values are SINGLE-QUOTED (with '\'' escaping) so `. scope.env` can never expand or execute a branch
# name or a path: a branch called `x$(touch pwned)` is data, not a command.
set -u
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
CX=$(codex login status 2>&1) && printf '%s\n' "$CX" | grep -q "Logged in using" || die "codex is not signed in — run: codex login"
# "logged in" as a substring also matches "Not logged in": require the positive phrase AND the absence of the negative.
GM=$(grok models 2>&1) && printf '%s\n' "$GM" | grep -qi "you are logged in" \
  && ! printf '%s\n' "$GM" | grep -qi "not logged in" || die "grok is not signed in — run: grok login"
# -z + tr, never field-splitting: git quotes paths containing spaces in porcelain/diff output otherwise.
UNTRACKED=$(git ls-files -z --others --exclude-standard ${PS[@]+"${PS[@]}"} | tr '\0' '\n' | grep .)
FILES=$( { git diff --name-only -z "$BASE" ${PS[@]+"${PS[@]}"} | tr '\0' '\n'
           printf '%s\n' "$UNTRACKED"; } | sort -u | grep . )
N=$(printf '%s\n' "$FILES" | grep -c .)
echo "base=$BASE branch=$BRANCH default=$DEFAULT root=$ROOT scope=$SCOPE changed_files=$N"
echo "seats:"
REV_CODEX_MODELS_CACHE=${REV_CODEX_MODELS_CACHE:-$HOME/.codex/models_cache.json} python3 - <<'PY'
import json, os
path = os.environ['REV_CODEX_MODELS_CACHE']
try:
    with open(path) as f: d = json.load(f)
except Exception:
    d = {}
if not isinstance(d, dict): d = {}
models = d.get('models') or []
seated = 0
for m in models if isinstance(models, list) else []:
    if not isinstance(m, dict) or m.get('slug') not in ('gpt-5.6-sol', 'gpt-5.6-terra'):
        continue
    levels = m.get('supported_reasoning_levels') or []
    lv = [l.get('effort') for l in levels if isinstance(l, dict) and l.get('effort')]
    top = next((e for e in ('max', 'xhigh', 'high') if e in lv), lv[-1] if lv else None)
    if not top:
        continue
    print(f"  codex-{m['slug'].rsplit('-', 1)[1]}@{top}")
    seated += 1
if not seated:
    print(f"  codex: no usable model in {path} — check codex login / models cache")
PY
if echo "$GM" | grep -q "grok-4.6"; then echo "  grok@xhigh"; else echo "  grok: grok-4.6 not listed — check 'grok models'"; fi
echo "  opus@max (rev-reviewer agent)"
if [ -n "$WRITE" ]; then
  mkdir -p "$WRITE" || die "cannot create session dir $WRITE"
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
