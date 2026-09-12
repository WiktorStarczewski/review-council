make_eval_case_fixture() {
  local root=$1
  mkdir -p "$root/eval" "$root/plugins/review-council/scripts/lib" "$root/bin"
  cp "$SK/../../eval/bench-case.sh" "$root/eval/bench-case.sh"
  cat > "$root/plugins/review-council/scripts/rev-preflight.sh" <<'SH'
#!/bin/bash
while [ "$#" -gt 0 ]; do
  if [ "$1" = --write ]; then out=$2; shift 2; else shift; fi
done
mkdir -p "$out"
cat > "$out/roster.json" <<'JSON'
{"seats":[{"seat":"opus","adapter":"agent"},{"seat":"codex-sol","adapter":"codex"}]}
JSON
SH
  cat > "$root/plugins/review-council/scripts/rev-prompt.sh" <<'SH'
#!/bin/bash
printf 'prompt\n' > "$1/r$2-$3.prompt.md"
printf '%s\n' "$3" >> "$PROMPT_CALLS"
SH
  cat > "$root/plugins/review-council/scripts/rev-seat.sh" <<'SH'
#!/bin/bash
printf '{"summary":"direct","findings":[]}\n' > "$2/r$3-$1.json"
printf '%s\n' "${DIRECT_RC:-0}" > "$2/r$3-$1.exit"
exit "${DIRECT_RC:-0}"
SH
  cat > "$root/plugins/review-council/scripts/lib/validate-findings.py" <<'PY'
#!/usr/bin/env python3
import json, sys
json.load(open(sys.argv[1]))
PY
  cat > "$root/bin/claude" <<'SH'
#!/bin/bash
printf '{"summary":"valid despite process failure","findings":[]}\n'
exit "${AGENT_RC:-9}"
SH
  chmod +x "$root/eval/bench-case.sh" "$root/plugins/review-council/scripts/"*.sh \
    "$root/plugins/review-council/scripts/lib/validate-findings.py" "$root/bin/claude"
}

make_eval_claude_shim() {
  local root=$1
  mkdir -p "$root/bin"
  cat > "$root/bin/claude" <<'SH'
#!/bin/bash
prompt=
while [ "$#" -gt 0 ]; do
  if [ "$1" = -p ]; then prompt=$2; break; fi
  shift
done
case "$prompt" in
  *"Write the result to "*)
    path=${prompt#*Write the result to }
    path=${path%%. Your final*}
    case "${CLAUDE_MODE:-truth_success}" in
      truth_fail)
        printf 'partial truth\n' > "$path"
        printf 'ROWS K=1 S=1 C=0 NONSIMPL=0\n'
        exit 11
        ;;
      truth_fail_first)
        count=0
        [ ! -f "$TRUTH_COUNT_FILE" ] || count=$(cat "$TRUTH_COUNT_FILE")
        count=$((count + 1)); printf '%s\n' "$count" > "$TRUTH_COUNT_FILE"
        printf 'truth attempt %s\n' "$count" > "$path"
        printf 'ROWS K=1 S=1 C=0 NONSIMPL=0\n'
        [ "$count" -gt 1 ] || exit 11
        ;;
      truth_no_summary)
        printf 'truth without summary\n' > "$path"
        printf 'not a summary\n'
        ;;
      *)
        printf 'complete truth\n' > "$path"
        printf 'ROWS K=1 S=1 C=0 NONSIMPL=0\n'
        ;;
    esac
    ;;
  *"Produce, and write to "*)
    path=${prompt#*Produce, and write to }
    path=${path%%: (1)*}
    case "${CLAUDE_MODE:-score_success}" in
      score_fail)
        printf 'partial score\n' > "$path"
        printf 'SUMMARY K=1/1 S=1/1 C=0/0 verdict=PASS contradicted=0 contaminated=none\n'
        exit 12
        ;;
      score_no_summary)
        printf 'score without summary\n' > "$path"
        printf 'not a summary\n'
        ;;
      *)
        printf 'complete score\n' > "$path"
        printf 'SUMMARY K=1/1 S=1/1 C=0/0 verdict=PASS contradicted=0 contaminated=none\n'
        ;;
    esac
    ;;
  *)
    echo "unrecognized prompt" >&2
    exit 90
    ;;
esac
SH
  chmod +x "$root/bin/claude"
}

test_eval_preflight_status() {
  ( local E="$T/eval-preflight" OUT="$T/eval-preflight-out"
    mkdir -p "$E/eval" "$E/plugins/review-council/scripts" "$OUT/repo/.git"
    cp "$SK/../../eval/bench-case.sh" "$E/eval/bench-case.sh"
    cat > "$E/plugins/review-council/scripts/rev-preflight.sh" <<'SH'
#!/bin/bash
echo "preflight: review-council strict failure" >&2
exit "${PREFLIGHT_RC:-5}"
SH
    chmod +x "$E/eval/bench-case.sh" "$E/plugins/review-council/scripts/rev-preflight.sh"
    "$E/eval/bench-case.sh" sample unused HEAD BASE "$OUT" > "$T/eval-preflight.out" 2>&1
    assert_eq "bench case preserves preflight exit 5" "$?" 5
    assert_grep "bench case preserves preflight cause" "$T/eval-preflight.out" \
      'review-council strict failure'
    PREFLIGHT_RC=6 "$E/eval/bench-case.sh" sample unused HEAD BASE "$OUT" > "$T/eval-preflight6.out" 2>&1
    assert_eq "bench case preserves preflight exit 6" "$?" 6
    assert_grep "bench case keeps permanent failure diagnostics" "$T/eval-preflight6.out" \
      'review-council strict failure'
  )
}

test_eval_case_statuses() {
  ( local E="$T/eval-case-status" OUT="$T/eval-case-status-out"
    make_eval_case_fixture "$E"
    mkdir -p "$OUT/repo/.git"
    export PATH="$E/bin:$PATH" PROMPT_CALLS="$T/eval-case-prompts" AGENT_RC=9 DIRECT_RC=0
    "$E/eval/bench-case.sh" sample unused HEAD BASE "$OUT" > "$T/eval-case-status.out" 2>&1
    local rc=$?
    assert_eq "bench case fails after all seats report" "$rc" 1
    assert_grep "failed Agent status is preserved" "$T/eval-case-status.out" '^sample seat=opus exit=9 findings=\?$'
    assert_grep "successful direct seat still reports" "$T/eval-case-status.out" '^sample seat=codex-sol exit=0 findings=0$'
    python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$OUT/session/r1-opus.raw" >/dev/null 2>&1
    assert_eq "failed Agent emitted valid JSON" "$?" 0
    [ ! -e "$OUT/session/r1-opus.json" ] && ok "failed Agent output is not accepted" || fail "failed Agent output is not accepted"
  )

  ( local E="$T/eval-deps" OUT="$T/eval-deps-out" REAL_PYTHON
    make_eval_case_fixture "$E"
    mkdir -p "$OUT/repo/.git"
    REAL_PYTHON=$(command -v python3)
    cat > "$E/bin/python3" <<'SH'
#!/bin/bash
if [ "${1:-}" = - ] && [ "${3##*/}" = deps ]; then exit 8; fi
exec "$REAL_PYTHON" "$@"
SH
    chmod +x "$E/bin/python3"
    export PATH="$E/bin:$PATH" REAL_PYTHON PROMPT_CALLS="$T/eval-deps-prompts"
    "$E/eval/bench-case.sh" sample unused HEAD BASE "$OUT" > "$T/eval-deps.out" 2>&1
    local rc=$?
    assert_eq "dependency construction status is preserved" "$rc" 8
    assert_grep "dependency construction failure is reported" "$T/eval-deps.out" '^sample: dependency view failed$'
    [ ! -e "$PROMPT_CALLS" ] && ok "dependency failure stops seat rendering" || fail "dependency failure stops seat rendering"
  )
}

test_eval_truth_publication() {
  ( local E="$T/eval-truth" OUT="$T/eval-truth-out"
    mkdir -p "$E/eval" "$OUT/full/.git"
    cp "$SK/../../eval/bench-truth.sh" "$E/eval/bench-truth.sh"
    make_eval_claude_shim "$E"
    export PATH="$E/bin:$PATH" CLAUDE_MODE=truth_fail
    "$E/eval/bench-truth.sh" sample owner/repo 1 HEAD BASE MERGED "$OUT" > "$T/eval-truth-fail.out" 2>&1
    local rc=$?
    assert_eq "truth generator status is preserved" "$rc" 11
    [ ! -e "$OUT/truth.md" ] && ok "failed truth is not published" || fail "failed truth is not published"
    [ ! -e "$OUT/truth.complete" ] && ok "failed truth has no completion marker" || fail "failed truth has no completion marker"
    [ -z "$(find "$OUT" -maxdepth 1 -name '.truth.*' -print -quit)" ] && ok "failed truth temporary files are removed" || fail "failed truth temporary files are removed"

    export CLAUDE_MODE=truth_success
    "$E/eval/bench-truth.sh" sample owner/repo 1 HEAD BASE MERGED "$OUT" > "$T/eval-truth-ok.out" 2>&1
    rc=$?
    assert_eq "successful truth generation completes" "$rc" 0
    assert_grep "truth artifact is published" "$OUT/truth.md" '^complete truth$'
    assert_grep "truth completion marker records summary" "$OUT/truth.complete" '^ROWS K=1 S=1 C=0 NONSIMPL=0$'

    export CLAUDE_MODE=truth_no_summary
    "$E/eval/bench-truth.sh" sample owner/repo 1 HEAD BASE MERGED "$OUT" > "$T/eval-truth-summary.out" 2>&1
    rc=$?
    assert_eq "truth requires a terminal summary" "$rc" 1
    [ ! -e "$OUT/truth.md" ] && ok "summary failure removes truth" || fail "summary failure removes truth"
    [ ! -e "$OUT/truth.complete" ] && ok "summary failure removes marker" || fail "summary failure removes marker"
  )
}

test_eval_score_publication() {
  ( local E="$T/eval-score" RUN="$T/eval-score-run" FULL="$T/eval-score-full" TRUTH="$T/eval-score-truth.md"
    mkdir -p "$E/eval" "$RUN/session" "$FULL"
    cp "$SK/../../eval/bench-score.sh" "$E/eval/bench-score.sh"
    make_eval_claude_shim "$E"
    printf 'truth\n' > "$TRUTH"
    printf 'stale score\n' > "$RUN/score.md"
    export PATH="$E/bin:$PATH" CLAUDE_MODE=score_fail
    "$E/eval/bench-score.sh" sample owner/repo 1 HEAD MERGED "$RUN" "$TRUTH" "$FULL" > "$T/eval-score-fail.out" 2>&1
    local rc=$?
    assert_eq "scorer status is preserved despite a valid summary" "$rc" 12
    [ ! -e "$RUN/score.md" ] && ok "failed score is not published" || fail "failed score is not published"
    [ -z "$(find "$RUN" -maxdepth 1 -name '.score.*' -print -quit)" ] && ok "failed score temporary files are removed" || fail "failed score temporary files are removed"

    export CLAUDE_MODE=score_success
    "$E/eval/bench-score.sh" sample owner/repo 1 HEAD MERGED "$RUN" "$TRUTH" "$FULL" > "$T/eval-score-ok.out" 2>&1
    rc=$?
    assert_eq "successful scoring completes" "$rc" 0
    assert_grep "score artifact is published" "$RUN/score.md" '^complete score$'
    assert_grep "score summary is reported" "$T/eval-score-ok.out" '^sample SUMMARY K=1/1 S=1/1 C=0/0 verdict=PASS contradicted=0 contaminated=none$'

    export CLAUDE_MODE=score_no_summary
    "$E/eval/bench-score.sh" sample owner/repo 1 HEAD MERGED "$RUN" "$TRUTH" "$FULL" > "$T/eval-score-summary.out" 2>&1
    rc=$?
    assert_eq "score requires a terminal summary" "$rc" 1
    [ ! -e "$RUN/score.md" ] && ok "summary failure removes score" || fail "summary failure removes score"
  )
}

test_eval_truth_retry() {
  ( local E="$T/eval-retry" CASES="$T/eval-retry.tsv"
    mkdir -p "$E/eval/truth/sample/full/.git"
    cp "$SK/../../eval/bench.sh" "$SK/../../eval/bench-truth.sh" "$E/eval/"
    make_eval_claude_shim "$E"
    cat > "$E/eval/bench-case.sh" <<'SH'
#!/bin/bash
echo "$1 seats complete"
SH
    cat > "$E/eval/bench-score.sh" <<'SH'
#!/bin/bash
printf '%s\n' "$1 score complete"
printf 'called\n' >> "$SCORE_CALLED"
SH
    chmod +x "$E/eval/"*.sh
    printf 'sample owner/repo 1 url head base merged\n' > "$CASES"
    export PATH="$E/bin:$PATH" CLAUDE_MODE=truth_fail_first \
      TRUTH_COUNT_FILE="$T/eval-truth-count" SCORE_CALLED="$T/eval-score-called"
    "$E/eval/bench.sh" "$CASES" retry 1 > "$T/eval-retry-first.out" 2>&1
    local rc=$?
    if [ "$rc" -ne 0 ]; then ok "failed truth makes benchmark fail"
    else fail "failed truth makes benchmark fail" "exit 0"; fi
    assert_eq "first truth attempt ran once" "$(cat "$TRUTH_COUNT_FILE")" 1
    [ ! -e "$E/eval/truth/sample/truth.md" ] && ok "partial truth is not cached" || fail "partial truth is not cached"
    [ ! -e "$E/eval/truth/sample/truth.complete" ] && ok "partial truth has no marker" || fail "partial truth has no marker"
    [ ! -e "$SCORE_CALLED" ] && ok "scoring stops after truth failure" || fail "scoring stops after truth failure"

    "$E/eval/bench.sh" "$CASES" retry 1 > "$T/eval-retry-second.out" 2>&1
    rc=$?
    assert_eq "second benchmark run succeeds" "$rc" 0
    assert_eq "truth regenerates after partial failure" "$(cat "$TRUTH_COUNT_FILE")" 2
    assert_grep "regenerated truth is published" "$E/eval/truth/sample/truth.md" '^truth attempt 2$'
    assert_grep "regenerated truth gets completion marker" "$E/eval/truth/sample/truth.complete" '^ROWS K=1 S=1 C=0 NONSIMPL=0$'
    assert_grep "scoring runs after completed truth" "$SCORE_CALLED" '^called$'
  )
}

test_eval_case_input_and_parallel_reporting() {
  ( local E="$T/eval-inputs" LAUNCH_LOG="$T/eval-input-launches"
    mkdir -p "$E/eval"
    cp "$SK/../../eval/bench.sh" "$E/eval/bench.sh"
    for script in bench-case.sh bench-truth.sh bench-score.sh; do
      cat > "$E/eval/$script" <<'SH'
#!/bin/bash
printf '%s\n' "$0" >> "$LAUNCH_LOG"
SH
      chmod +x "$E/eval/$script"
    done
    export LAUNCH_LOG
    "$E/eval/bench.sh" "$T/no-such-cases.tsv" missing 1 > "$T/eval-input-missing.out" 2>&1
    assert_eq "missing case input fails" "$?" 1
    assert_grep "missing case input names its guard" "$T/eval-input-missing.out" \
      '^bench: cases file is missing or unreadable:'
    printf 'sample owner/repo 1 https://example.invalid/repo head base merged\n' > "$T/eval-input-unreadable.tsv"
    chmod 000 "$T/eval-input-unreadable.tsv"
    if [ "$(id -u)" -eq 0 ]; then
      ok "unreadable case input is skipped for privileged runners"
    else
      "$E/eval/bench.sh" "$T/eval-input-unreadable.tsv" unreadable 1 > "$T/eval-input-unreadable.out" 2>&1
      assert_eq "unreadable case input fails" "$?" 1
      assert_grep "unreadable case input names its guard" "$T/eval-input-unreadable.out" \
        '^bench: cases file is missing or unreadable:'
    fi
    : > "$T/eval-input-empty.tsv"
    "$E/eval/bench.sh" "$T/eval-input-empty.tsv" empty 1 > "$T/eval-input-empty.out" 2>&1
    assert_eq "empty case input fails" "$?" 1
    assert_grep "empty case input names its guard" "$T/eval-input-empty.out" \
      '^bench: cases file has no effective cases:'
    printf '# comment\n   \n' > "$T/eval-input-comments.tsv"
    "$E/eval/bench.sh" "$T/eval-input-comments.tsv" comments 1 > "$T/eval-input-comments.out" 2>&1
    assert_eq "case input without effective rows fails" "$?" 1
    assert_grep "comment-only case input names its guard" "$T/eval-input-comments.out" \
      '^bench: cases file has no effective cases:'
    [ ! -e "$LAUNCH_LOG" ] && ok "invalid case inputs launch no stages" || fail "invalid case inputs launch no stages"
  )

  ( local E="$T/eval-batch" CASES="$T/eval-cases.tsv"
    mkdir -p "$E/eval"
    cp "$SK/../../eval/bench.sh" "$E/eval/bench.sh"
    cat > "$E/eval/bench-case.sh" <<'SH'
#!/bin/bash
mkdir -p "$5/session"
if [ "$1" = fail ]; then echo "deliberate case failure"; exit 7; fi
echo "$1 seats complete"
SH
    cat > "$E/eval/bench-truth.sh" <<'SH'
#!/bin/bash
mkdir -p "$7"; echo truth > "$7/truth.md"; echo complete > "$7/truth.complete"
SH
    cat > "$E/eval/bench-score.sh" <<'SH'
#!/bin/bash
echo "$1 score complete"
SH
    chmod +x "$E/eval/"*.sh
    cat > "$CASES" <<'TSV'
first owner/repo 1 url head base merged
fail owner/repo 2 url head base merged
last owner/repo 3 url head base merged
TSV
    "$E/eval/bench.sh" "$CASES" batch 3 > "$T/eval-batch.out" 2>&1
    local rc=$?
    if [ "$rc" -ne 0 ]; then ok "benchmark batch fails when one parallel case fails"
    else fail "benchmark batch fails when one parallel case fails" "exit 0"; fi
    assert_grep "failed case reports its cause" "$T/eval-batch.out" '^fail: seats failed: deliberate case failure$'
    assert_grep "first parallel case still reports" "$T/eval-batch.out" '^first score complete$'
    assert_grep "last parallel case still reports" "$T/eval-batch.out" '^last score complete$'
  )
}
