#!/bin/bash
# rev-squash.sh [--apply] [repo-name ...]
# Collapse the contiguous run of review commits at the TIP into one "apply review findings" commit.
#   single repo (the common case):  rev-squash.sh            # dry run in the repo containing the cwd
#                                    rev-squash.sh --apply
#   a stack:                         REPO_ROOT=<parent-dir> rev-squash.sh [--apply] repoA repoB   (or REPOS="repoA repoB")
# Safety: only review-titled commits count and the run stops at the first other commit, so real work is never swallowed;
# a run that is already (partly) on the upstream is refused rather than rewritten. The squash commit is the user's —
# no tool attribution, ever. The count is computed here, never hardcoded: loops keep adding rounds.
APPLY=0; [ "${1:-}" = "--apply" ] && { APPLY=1; shift; }
# ANCHORED, always: an unanchored `from review` / `found in review` matched ordinary work
# ("fix: add the null check found in review") and would have swallowed it into the squash.
PATTERN='^(fix|chore|test|docs|refactor)\(rev\)|^rev:|^apply review findings$|^review round'
if [ $# -eq 0 ] && [ -z "${REPOS:-}" ]; then
  top=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not in a git repo, and no REPO_ROOT/REPOS given"; exit 1; }
  REPO_ROOT=$(dirname "$top"); REPOS_ARG=$(basename "$top")
else
  REPO_ROOT=${REPO_ROOT:?set REPO_ROOT to the directory containing the repos}
  REPOS_ARG=${*:-$REPOS}
fi
rc=0
for d in $REPOS_ARG; do
  cd "$REPO_ROOT/$d" 2>/dev/null || { printf "  %-20s not found under %s\n" "$d" "$REPO_ROOT"; rc=1; continue; }
  default=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
  if [ -z "$default" ]; then
    for cand in main master; do git show-ref --verify -q "refs/heads/$cand" && { default=$cand; break; }; done
  fi
  base=""
  [ -n "$default" ] && base=$(git merge-base HEAD "origin/$default" 2>/dev/null || git merge-base HEAD "$default" 2>/dev/null)
  if [ -z "$base" ]; then
    printf "  %-20s cannot determine a base branch (no origin/HEAD, no local main/master) — refusing\n" "$d"; rc=1; continue
  fi
  if [ "$APPLY" = 1 ] && ! git diff --cached --quiet; then
    # `git reset --soft` + `git commit` would sweep whatever is already staged into the squash commit.
    printf "  %-20s index has staged changes; commit or unstage them first\n" "$d"; rc=1; continue
  fi
  n=0
  while [ -n "$(git rev-parse --verify -q "HEAD~$n")" ] && [ "$(git rev-parse "HEAD~$n")" != "$base" ] \
        && git log --format=%s -1 "HEAD~$n" | grep -qiE "$PATTERN"; do n=$((n+1)); done
  if [ "$n" -lt 2 ]; then printf "  %-20s %s review commit(s) at tip — nothing to collapse\n" "$d" "$n"; continue; fi
  if up=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null); then
    unpushed=$(git rev-list --count "$up..HEAD")
    if [ "$unpushed" -lt "$n" ]; then
      printf "  %-20s refusing: %s review commits at tip but only %s unpushed (would rewrite %s)\n" "$d" "$n" "$unpushed" "$up"; rc=1; continue
    fi
  fi
  printf "  %-20s collapsing %s review commits\n" "$d" "$n"
  git log --format="      %h %s" -n "$n"
  if [ "$APPLY" = 1 ]; then
    orig=$(git rev-parse HEAD)
    if git reset -q --soft "HEAD~$n" && git commit -q -m "apply review findings"; then
      echo "      -> $(git log --oneline -1)"
    else
      printf "  %-20s squash failed after reset (commit rejected, e.g. by a hook) — restoring original tip %s\n" "$d" "${orig:0:7}"
      git reset -q --soft "$orig"
      rc=1
    fi
  fi
done
[ "$APPLY" = 0 ] && echo "  (dry run — rerun with --apply once the review is green)"
exit $rc
