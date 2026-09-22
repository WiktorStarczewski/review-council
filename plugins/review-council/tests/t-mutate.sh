# tests for Task 3 - sourced by run-tests.sh
# NAMESPACED: run-tests.sh sources every t-*.sh into ONE shell. Prefix every helper.
MUTATE_SRC="$SCRIPTS/rev-mutate.sh"

mut_repo() {  # mut_repo <dir> [base] [fix] - a git repo with one committed file and one uncommitted change
  local base=${2:-$'a\nb\nc\n'} fix=${3:-$'a\nB\nc\n'}
  mkdir -p "$1" && cd "$1" || return 1
  export GIT_CONFIG_GLOBAL="$T/mut-gitconfig" GIT_CONFIG_NOSYSTEM=1
  git init -q . && git config user.email t@e && git config user.name t && git config commit.gpgsign false
  printf '%s' "$base" > f.txt
  git add f.txt && git commit -qm base
  printf '%s' "$fix" > f.txt
}

mut_phase() {  # mut_phase <session-dir> <phase>
  python3 -c 'import json,sys; json.dump({"phase":sys.argv[2],"round":1}, open(sys.argv[1],"w"))' "$1/state.json" "$2"
}

test_mutate_refuses_while_a_panel_is_live() {
  ( local D="$T/mut-live" S="$T/mut-live-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    mut_phase "$S" collect
    assert_exit "refuses to revert hunks while seats are reading the tree" 2 \
      "$MUTATE_SRC" "$S" "true" )
}

test_mutate_reports_an_unpinned_hunk() {
  ( local D="$T/mut-unpinned" S="$T/mut-unpinned-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    mut_phase "$S" fix
    # `true` always passes, so reverting the hunk leaves it green: the hunk is unpinned.
    "$MUTATE_SRC" "$S" "true" > "$T/mut-unpinned.out" 2>&1
    assert_eq "an unpinned hunk exits 3" "$?" 3
    assert_grep "names the unpinned file" "$T/mut-unpinned.out" "f\.txt" )
}

test_mutate_passes_when_every_hunk_is_pinned() {
  ( local D="$T/mut-pinned" S="$T/mut-pinned-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    mut_phase "$S" fix
    # This command passes only while the working tree holds the B, so every revert turns it red.
    assert_exit "a pinned hunk exits 0" 0 \
      "$MUTATE_SRC" "$S" "grep -q B f.txt" )
}

# Each hunk must be measured against the COMPLETE fix, not against the commit: restoring with
# `git checkout` would drop the sibling hunks, so hunk 2 would be measured on a tree at base.
test_mutate_measures_each_hunk_against_the_whole_fix() {
  ( local D="$T/mut-whole" S="$T/mut-whole-session"; mkdir -p "$S"
    mut_repo "$D" $'a\nb\nc\nd\ne\n' $'a\nB\nc\nd\nE\n' || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    mut_phase "$S" fix
    # Only the B is pinned. Reverting the E alone leaves the command green, so hunk 2 is unpinned
    # and hunk 1 is not - a verdict that is only reachable while the other hunk is still present.
    "$MUTATE_SRC" "$S" "grep -q B f.txt" > "$T/mut-whole.out" 2>&1
    assert_eq "an unpinned second hunk exits 3" "$?" 3
    assert_grep "names the unpinned second hunk" "$T/mut-whole.out" "f\.txt hunk 2"
    assert_nogrep "does not blame the pinned first hunk" "$T/mut-whole.out" "f\.txt hunk 1"
    assert_nogrep "measures every hunk" "$T/mut-whole.out" "did not apply|would not apply"
    assert_eq "the run leaves the complete fix in the tree" \
      "$(cat "$D/f.txt")" "$(printf 'a\nB\nc\nd\nE\n')" )
}

test_mutate_refuses_when_the_phase_cannot_be_read() {
  ( local D="$T/mut-phase" S="$T/mut-phase-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    assert_exit "a missing state.json cannot rule a panel out" 2 "$MUTATE_SRC" "$S" "true"
    printf 'not json\n' > "$S/state.json"
    assert_exit "a malformed state.json cannot rule a panel out" 2 "$MUTATE_SRC" "$S" "true"
    printf '{"round": 1}\n' > "$S/state.json"
    assert_exit "a state.json with no phase cannot rule a panel out" 2 "$MUTATE_SRC" "$S" "true"
    assert_eq "a refusal leaves the working tree alone" "$(cat "$D/f.txt")" "$(printf 'a\nB\nc\n')" )
}

# A revert that changes no byte is the failure this tool exists to prevent: it reads exactly like
# a real measurement and every later verdict rests on it.
test_mutate_fails_a_run_that_measured_nothing() {
  ( local D="$T/mut-nothing" S="$T/mut-nothing-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    mut_phase "$S" fix
    git checkout -- f.txt
    "$MUTATE_SRC" "$S" "true" > "$T/mut-nothing.out" 2>&1
    assert_eq "a run with nothing to revert is not a pass" "$?" 4
    assert_grep "says it measured nothing" "$T/mut-nothing.out" "measured nothing"
    python3 -c 'open("bin.dat","wb").write(b"\x00\x01\x02")'
    git add bin.dat && git commit -qm bin
    python3 -c 'open("bin.dat","wb").write(b"\x00\x09\x02")'
    printf 'a\nB\nc\n' > f.txt
    "$MUTATE_SRC" "$S" "true" > "$T/mut-binary.out" 2>&1
    assert_eq "an unmeasurable file outranks an unpinned hunk" "$?" 4
    assert_grep "names the unmeasured file" "$T/mut-binary.out" "bin\.dat"
    assert_grep "still reports the unpinned hunk" "$T/mut-binary.out" "UNPINNED f\.txt hunk 1" )
}
