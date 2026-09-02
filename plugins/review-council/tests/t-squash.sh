# tests for Task 6 — sourced by run-tests.sh
test_squash() {
  local R="$T/sq" start_pwd="$PWD"
  mkrepo "$R"; cd "$R" || { cd "$start_pwd"; return 1; }
  git checkout -qb feat; echo w > w.txt; git add w.txt; git commit -qm "feat: real work"
  for i in 1 2 3; do echo "$i" > "f$i.txt"; git add "f$i.txt"; git commit -qm "fix(rev): round $i — thing $i"; done
  "$SCRIPTS/rev-squash.sh" > "$T/sq.out"; assert_eq "dry run exit 0" "$?" 0
  assert_grep "dry run counts 3" "$T/sq.out" 'collapsing 3 review commits'
  assert_grep "dry run says dry" "$T/sq.out" 'dry run'
  assert_eq "dry run changed nothing" "$(git rev-list --count main..HEAD)" "4"
  "$SCRIPTS/rev-squash.sh" --apply > "$T/sq.out"; assert_eq "apply exit 0" "$?" 0
  assert_eq "one review commit left" "$(git rev-list --count main..HEAD)" "2"
  assert_eq "squash title" "$(git log --format=%s -1)" "apply review findings"
  assert_eq "real work preserved below" "$(git log --format=%s -1 HEAD~1)" "feat: real work"
  assert_eq "tree intact" "$(ls f1.txt f2.txt f3.txt w.txt | wc -l | tr -d ' ')" "4"
  assert_nogrep "no attribution in message" <(git log -1 --format=%B) 'claude|co-authored|generated' -i
  echo 4 > f4.txt; git add f4.txt; git commit -qm "fix(rev): round 4 — more"
  "$SCRIPTS/rev-squash.sh" > "$T/sq.out"
  assert_grep "apply+fix re-collapsible" "$T/sq.out" 'collapsing 2 review commits'
  echo x > x.txt; git add x.txt; git commit -qm "docs: unrelated on top"
  "$SCRIPTS/rev-squash.sh" > "$T/sq.out"
  assert_grep "broken run: nothing to collapse" "$T/sq.out" '0 review commit\(s\) at tip'
  # pushed review commits must never be rewritten
  git init -q --bare "$T/sq-remote.git"; git remote add origin "$T/sq-remote.git"
  for i in 5 6; do echo "$i" > "g$i.txt"; git add "g$i.txt"; git commit -qm "fix(rev): round $i — pushed"; done
  git push -q -u origin feat
  "$SCRIPTS/rev-squash.sh" --apply > "$T/sq.out"; assert_eq "refuses pushed commits (exit 1)" "$?" 1
  assert_grep "refusal names upstream" "$T/sq.out" 'refusing: 2 review commits at tip but only 0 unpushed'
  assert_eq "history untouched" "$(git log --format=%s -1)" "fix(rev): round 6 — pushed"
  # a title that merely MENTIONS a review is ordinary work and must never be collapsed
  git reset -q --hard HEAD; git checkout -qb feat2 main
  echo n > n.txt; git add n.txt; git commit -qm "fix: add the null check found in review"
  for i in 1 2; do echo "$i" > "h$i.txt"; git add "h$i.txt"; git commit -qm "rev: tighten retry $i"; done
  "$SCRIPTS/rev-squash.sh" > "$T/sq.out"
  assert_grep "anchored pattern collapses rev: commits" "$T/sq.out" 'collapsing 2 review commits'
  assert_nogrep "and stops at the mention-only commit" "$T/sq.out" 'found in review'
  git commit -q --allow-empty -m "fix: add the null check found in review"
  "$SCRIPTS/rev-squash.sh" > "$T/sq.out"
  assert_grep "a mention-only tip is not a review commit" "$T/sq.out" '0 review commit\(s\) at tip'
  # --apply must never sweep a pre-existing index into the squash commit
  git checkout -qb feat3 main
  for i in 1 2; do echo "$i" > "k$i.txt"; git add "k$i.txt"; git commit -qm "fix(rev): round $i — k$i"; done
  local head_before; head_before=$(git rev-parse HEAD)
  echo staged > staged.txt; git add staged.txt
  "$SCRIPTS/rev-squash.sh" --apply > "$T/sq.out" 2>&1; assert_eq "staged index refuses (exit 1)" "$?" 1
  assert_grep "refusal explains" "$T/sq.out" 'index has staged changes; commit or unstage them first'
  assert_eq "history untouched by the refusal" "$(git rev-parse HEAD)" "$head_before"
  assert_eq "the staged file is still staged" "$(git diff --cached --name-only)" "staged.txt"
  git reset -q; rm -f staged.txt
  cd "$start_pwd"
}
