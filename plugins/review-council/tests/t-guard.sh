# tests for the rev-reviewer read-only Bash guard — sourced by run-tests.sh
# The guard is an ALLOWLIST (see the file header): everything not named here is refused, so the
# matrix below is the contract. `python3 -c "print(1)"` used to be allowed by the old denylist and
# is deliberately BLOCKED now — an interpreter with -c can write any file.
guard() { printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1")" | python3 "$SCRIPTS/lib/readonly-bash-guard.py" >/dev/null 2>&1; }
test_guard() {
  for c in 'git diff abc123' 'git log --oneline -5' 'git show HEAD:src/x.ts' 'rg -n "retry" src/' \
           'cat src/x.ts 2>/dev/null' 'git diff abc | head -50' 'ls -la 2>&1' 'npx jest src/lib/x' \
           'yarn test' 'cargo test -p foo' 'grep -rn foo . 1>&2' 'git -C /repo log --oneline' \
           'git --no-pager diff' 'GIT_PAGER=cat git log -1' 'git stash list' 'git worktree list' \
           'git branch' 'git branch --list' 'git tag -l "v*"' 'git remote' 'git config --get user.name' \
           'git config --get-regexp "^user"' 'git -c core.pager=cat log' 'time git diff' 'nice rg foo' \
           'cd src && ls' 'sort f | uniq -c' 'find . -name "*.ts"' "awk '{print \$1}' f" "sed -n '1,10p' f" \
           'jq . out.json' 'npm run test:unit' 'pytest -q tests/' 'go test ./...' 'cargo clippy -- -D warnings' \
           'npx vitest run src' 'yarn test --coverage' 'git diff $(git merge-base HEAD main)' \
           'echo $(git log -1 --format=%H)' 'rg "retry|timeout" src/' 'cat "file with > in name"' \
           'git log -1 --format=%H > /dev/null' 'git diff --stat 2>&1 | tail -5' 'env' 'git'; do
    guard "$c"; assert_eq "allows: $c" "$?" 0
  done
  for c in 'git commit -m x' 'git checkout main' 'git reset --hard' 'git stash' 'git apply p.diff' 'git push' \
           'git add .' 'echo hi > f.txt' 'cat a >> b' 'sed -i "s/a/b/" f' 'rm -rf dist' 'mv a b' 'npm install' \
           'yarn add foo' 'cargo build' 'touch x' 'mkdir y' 'npx jest -u' 'git diff; git commit -am x' 'sudo ls' \
           '/usr/bin/git commit -m x' 'git -C d commit -m x' 'command git push' 'sed -i.bak s/a/b/ f' \
           'perl -i.bak -pe s/a/b/ f' 'python3 -c "open(\047f\047,\047w\047)"' 'python3 -c "print(1)"' \
           'python3 script.py' 'node -e "1"' 'bash -c "rm x"' 'sh -c "rm x"' 'ls | xargs rm' 'env X=1 git push' \
           'yarn format' 'yarn lint --fix' 'npx prettier --write .' 'eslint --fix .' 'echo `whoami`' \
           'tee out.txt' 'git config user.name bob' 'git remote add origin u' 'git branch -d feat' \
           'git worktree add ../w' "awk '{print > \"f\"}' x" 'find . -delete' 'find . -exec rm {} \;' \
           'git diff $(rm -rf x)' 'npm test --fix' 'cargo clippy --fix' 'yarn build' 'npx vitest -u' \
           './script.sh' 'git diff |& cat' 'ls > /tmp/f' 'git log > log.txt' 'source ~/.bashrc' 'eval "rm x"'; do
    guard "$c"; assert_eq "blocks: $c" "$?" 2
  done
  echo 'not json' | python3 "$SCRIPTS/lib/readonly-bash-guard.py" >/dev/null 2>&1; assert_eq "non-JSON payload is not blocked" "$?" 0
  assert_grep "header documents Read/Grep/Glob first" "$SCRIPTS/lib/readonly-bash-guard.py" "Read, Grep and Glob are the reviewer's primary tools"
  assert_grep "header says ALLOWLIST" "$SCRIPTS/lib/readonly-bash-guard.py" 'ALLOWLIST'
}
