#!/bin/bash
# run-tests.sh [name-filter] — unit tests for the rev scripts. No network: real CLIs are shimmed via tests/shims.
# Each task adds tests/t-<name>.sh defining test_<name>() functions; this runner sources them all and runs every test_*.
set -u
HERE=$(cd "$(dirname "$0")" && pwd); SK=$(cd "$HERE/.." && pwd)
SCRIPTS="$SK/scripts"; FX="$HERE/fixtures"; SHIMS="$HERE/shims"
STACK="$SCRIPTS"                                   # stack.sh lives beside the other scripts in the plugin
FILTER=${1:-}
T=$(mktemp -d /tmp/rev-tests.XXXXXX); trap 'rm -rf "$T"' EXIT
# Tallies go through a file, not shell variables: test bodies run in ( … ) subshells for cd/export isolation,
# and a subshell's PASS/FAIL increments never reach this process. (Proved: a FAIL inside ( … ) tallied as 0/0, exit 0.)
RESULTS="$T/.results"; : > "$RESULTS"
ok()   { echo ok   >> "$RESULTS"; echo "  ok   $1"; }
fail() { echo fail >> "$RESULTS"; echo "  FAIL $1${2:+ — $2}"; }
assert_eq()     { [ "$2" = "$3" ] && ok "$1" || fail "$1" "expected '$3' got '$2'"; }
assert_grep()   { grep -qE -- "$3" "$2" 2>/dev/null && ok "$1" || fail "$1" "no /$3/ in $2"; }
assert_nogrep() { grep -qE ${4:-} -- "$3" "$2" 2>/dev/null && fail "$1" "found /$3/ in $2" || ok "$1"; }   # $4 = extra grep flags, e.g. -i
assert_exit()   { local name=$1 want=$2; shift 2; "$@" >/dev/null 2>&1; local got=$?; [ "$got" = "$want" ] && ok "$name" || fail "$name" "exit $got, wanted $want"; }
seat_env() {  # shims on PATH, fixtures + arg capture wired
  export PATH="$SHIMS:$PATH" SHIM_FIXTURE_DIR="$FX" SHIM_ARGS_FILE="$T/args" REV_REPO="$T"
}
mkrepo() {  # mkrepo <dir> — temp git repo on main with one commit, isolated from the user's git config
  export GIT_CONFIG_GLOBAL="$T/gitconfig" GIT_CONFIG_NOSYSTEM=1
  [ -f "$T/gitconfig" ] || printf '[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n' > "$T/gitconfig"
  mkdir -p "$1" && git -C "$1" init -q && echo a > "$1/a.txt" && git -C "$1" add . && git -C "$1" commit -qm "init"
}
# A test body that returns non-zero has stopped early — `set -e`-less bash just moves to the next test and
# the run stays green. Capture the status and record it as a failure. MATCHED guards the other vacuous pass:
# a filter that matches nothing used to print `passed=0 failed=0` and exit 0.
MATCHED=0
run() {
  [ -z "$FILTER" ] || [[ "$1" == *"$FILTER"* ]] || return 0
  MATCHED=$((MATCHED + 1)); echo "$1"
  "test_$1"; local rc=$?
  [ "$rc" -eq 0 ] || fail "$1" "exited $rc before reporting"
}

for f in "$HERE"/t-*.sh; do [ -f "$f" ] && . "$f"; done
for t in $(declare -F | awk '{print $3}' | sed -n 's/^test_//p'); do run "$t"; done
if [ "$MATCHED" -eq 0 ]; then
  if [ -n "$FILTER" ]; then fail "no test matched" "filter '$FILTER' selected nothing"
  else fail "no test matched" "no test_* functions found"; fi
fi
PASS=$(grep -c "^ok$" "$RESULTS" || true); FAIL=$(grep -c "^fail$" "$RESULTS" || true)
echo; echo "passed=$PASS failed=$FAIL"; [ "$FAIL" = 0 ]
