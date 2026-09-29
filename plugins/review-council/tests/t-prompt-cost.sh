#!/bin/bash

prompt_cost_fixture() {
  local R=$1 S=$2
  mkrepo "$R"; mkdir -p "$S"
  printf 'changed\n' > "$R/a.txt"
  printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
    "$(git -C "$R" rev-parse HEAD)" "$R" > "$S/scope.env"
  printf 'a.txt\n' > "$S/files.txt"
  : > "$S/untracked.txt"
  printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"native","adapter":"agent"},{"seat":"gemini","adapter":"gemini"}]}' > "$S/roster.json"
}

test_prompt_cost_adapter_and_lens_contracts() {
  ( local R="$T/prompt-cost-adapters-repo" S="$T/prompt-cost-adapters-session"
    prompt_cost_fixture "$R" "$S"
    local seat p
    for seat in sol opus native gemini; do
      p=$("$SCRIPTS/rev-prompt.sh" "$S" legacy "$seat" correctness focused) || return
      assert_nogrep "$seat ordinary lens has no clean-room instruction" "$p" 'Clean-room ordering:|Do NOT read the diff first'
      assert_nogrep "$seat legacy has no chunks or source-packet guidance" "$p" 'chunk mode|patch-chunk|source-context packet|source-context packet range|source-context packet reads'
      assert_nogrep "$seat legacy has no evidence-index budget precondition" "$p" 'After the evidence index, use at most'
      assert_grep "$seat retains bounded call reserve" "$p" 'use at most 16 repository tool calls.*no new evidence path after call 12'
      assert_grep "$seat retains refutation" "$p" 'Try to refute each candidate'
      assert_grep "$seat retains incomplete-proof return" "$p" 'summary.*INCOMPLETE PROOF:.*unfinished obligations'
      assert_grep "$seat retains required JSON" "$p" 'Return only the JSON object required by the runner'
      case "$seat" in
        sol)
          assert_nogrep 'Codex has no native Read/Grep instructions' "$p" 'source Read call|Every Grep|use Read|use read_file'
          assert_nogrep 'Codex schema remains adapter supplied' "$p" '"[$]schema"'
          ;;
        opus|native)
          assert_grep "$seat retains native source bounds" "$p" 'source Read call.*offset.*limit.*240'
          assert_grep "$seat retains native search bounds" "$p" 'Every Grep.*result limit.*80'
          ;;
        gemini)
          assert_grep 'Gemini gets read_file source bounds' "$p" 'source read_file call.*240'
          assert_nogrep 'Gemini has no Claude source guidance' "$p" 'source Read call|Every Grep'
          ;;
      esac
      case "$seat" in native|gemini) assert_grep "$seat embeds schema" "$p" '"[$]schema"';; esac
    done
    p=$("$SCRIPTS/rev-prompt.sh" "$S" clean sol 'correctness+clean-room' focused) || return
    python3 - "$p" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
assert text.index('Clean-room ordering:') < text.index('## Bounded evidence protocol')
assert 'write the smallest design before any patch or source read' in text
assert 'Do NOT read the diff first' in text
assert 'Logic errors, off-by-one' in text
PY
    assert_eq 'composite clean-room design precedes all patch guidance' "$?" 0
    p=$("$SCRIPTS/rev-prompt.sh" "$S" false-clean sol clean-roomish focused) || return
    assert_nogrep 'lens substring does not activate clean-room ordering' "$p" 'Clean-room ordering:'
  )
}

test_prompt_cost_evidence_mode_matrix() {
  ( local R="$T/prompt-cost-modes-repo" S="$T/prompt-cost-modes-session"
    prompt_cost_fixture "$R" "$S"
    python3 - "$R/long.py" <<'PY'
from pathlib import Path
import sys
body = 'def long_function():\n' + ''.join(
    '    value_' + str(i) + ' = "' + 'x' * 60 + '"\n' for i in range(400))
Path(sys.argv[1]).write_text(body + '    return value_399\n')
PY
    printf 'from long import long_function\n\ndef caller():\n    return long_function()\n' > "$R/caller.py"
    git -C "$R" add long.py caller.py; git -C "$R" commit -qm 'source fixture'
    python3 - "$R" "$S/scope.env" <<'PY'
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1]); scope = Path(sys.argv[2])
base = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
scope.write_text('\n'.join("REV_BASE='" + base + "'" if row.startswith('REV_BASE=') else row
                           for row in scope.read_text().splitlines()) + '\n')
source = root / 'long.py'
source.write_text(source.read_text().replace('value_200 = ', 'value_200_changed = '))
PY
    printf 'a.txt\nlong.py\n' > "$S/files.txt"
    local chunks source manifest seat lens p fragment mode before
    for chunks in 0 1; do
      for source in 0 1; do
        mode="${chunks}${source}"
        manifest=$(REV_PATCH_CHUNKS="$chunks" REV_SOURCE_CONTEXT="$source" python3 "$SCRIPTS/rev-evidence.py" prepare \
          "$S" "$mode" --phase risk --assignment sol=correctness-boundaries --assignment opus=security-state-api --assignment native=concurrency-resources-performance --assignment gemini=tests-observability-maintenance-regression) || return
        before=$(shasum -a 256 "$manifest")
        for seat in sol opus; do
          lens=correctness-boundaries; [ "$seat" = sol ] || lens=security-state-api
          p=$("$SCRIPTS/rev-prompt.sh" "$S" "$mode" "$seat" "$lens" focused --evidence "$manifest") || return
          fragment="$T/prompt-cost-$mode-$seat.fragment"
          python3 "$SCRIPTS/rev-evidence.py" render "$manifest" "$seat" > "$fragment" || return
          python3 - "$p" "$fragment" "$chunks" "$source" "$seat" <<'PY'
from pathlib import Path
import sys
text, fragment = (Path(value).read_text() for value in sys.argv[1:3])
prefix = text.split('\n## Review assignment\n')[0]
assert fragment in text, 'evidence fragment changed'
assert ('In chunk mode' in prefix) == (sys.argv[3] == '1'), prefix
assert ('In window mode' in prefix) == (sys.argv[3] == '0'), prefix
assert ('source-context packet' in prefix) == ('Source context packet:' in fragment), prefix
assert ('required-source-segment' in prefix) == ('Required source segment 1/' in fragment), prefix
if sys.argv[4] == '1' and sys.argv[5] == 'sol':
    assert 'Required source segment 1/' in fragment, 'fixture must exercise active segments'
assert 'After the evidence index, use at most 16' in prefix
assert 'INCOMPLETE PROOF:' in prefix
assert 'Try to refute each candidate' in prefix
assert 'Never run an interpreter or inline script' in prefix
PY
          assert_eq "$seat mode $mode compiles only active proof clauses and preserves evidence" "$?" 0
        done
        assert_eq "mode $mode keeps exact manifest hash" "$(shasum -a 256 "$manifest")" "$before"
      done
    done
  )
}

test_prompt_cost_shared_limits_and_copy() {
  ( local R="$T/prompt-cost-limits-repo" S="$T/prompt-cost-limits-session" COPY="$T/prompt-cost-copy"
    prompt_cost_fixture "$R" "$S"
    mkdir -p "$COPY/scripts/lib" "$COPY/schema"
    cp "$SCRIPTS/rev-prompt.sh" "$SCRIPTS/rev-evidence.py" "$COPY/scripts/"
    cp -R "$SCRIPTS/lib/" "$COPY/scripts/lib/"
    cp "$SCRIPTS/../schema/findings.schema.json" "$COPY/schema/"
    chmod u+w "$COPY/scripts/lib/review_limits.py"
    printf 'READ_LINES = 120\nREPOSITORY_EXPANSION_CALL_LIMIT = 9\nMANDATORY_REPOSITORY_READ_LIMIT = 6\n' > "$COPY/scripts/lib/review_limits.py"
    printf 'frozen patch\n' > "$S/rlimits-full.patch"
    local p; p=$("$COPY/scripts/rev-prompt.sh" "$S" limits sol correctness focused) || return
    assert_grep 'copied prompt derives window bounds from bundled constants' "$p" 'END - START \+ 1 <= 120'
    assert_grep 'copied prompt derives expansion and reserve from bundled constants' "$p" 'use at most 9 repository tool calls.*no new evidence path after call 6'
  )
}

test_prompt_cost_structured_baseline() {
  ( local R="$T/prompt-cost-baseline-repo" S="$T/prompt-cost-baseline-session"
    prompt_cost_fixture "$R" "$S"
    printf 'LEGACY_BASELINE_SENTINEL\n' > "$S/baseline.md"
    cat > "$S/baseline.json" <<'JSON'
{"schema_version":1,"checks":[{"command":"npm test -- a.test.ts","outcome":"failed","failure":"a.test.ts::fails on empty input","applicability":"unchanged main at base","log":"baseline-test.log"},{"command":"npm run build","outcome":"passed","applicability":"base worktree"},{"command":"npm run lint","outcome":"skipped","applicability":"tool missing","log":"baseline-lint.log"}]}
JSON
    local p; p=$("$SCRIPTS/rev-prompt.sh" "$S" baseline sol correctness focused) || return
    assert_grep 'structured baseline retains exact command' "$p" 'npm test -- a\.test\.ts'
    assert_grep 'structured baseline retains failure identity' "$p" 'a\.test\.ts::fails on empty input'
    assert_grep 'structured baseline retains applicability and log reference' "$p" 'unchanged main at base.*baseline-test\.log'
    assert_grep 'structured baseline retains passed and skipped outcomes' "$p" '"outcome":"passed"|"outcome":"skipped"'
    assert_nogrep 'structured baseline replaces legacy ledger' "$p" 'LEGACY_BASELINE_SENTINEL'
    assert_grep 'baseline exception requires matching failure identity and applicability' "$p" 'command, failure identity, and applicability match'
    rm "$S/baseline.json"
    p=$("$SCRIPTS/rev-prompt.sh" "$S" fallback sol correctness focused) || return
    assert_grep 'legacy baseline remains supported' "$p" 'LEGACY_BASELINE_SENTINEL'
    python3 - "$S/baseline.json" <<'PY'
import json, sys
checks = [{'command': 'check ' + str(i), 'outcome': 'failed', 'failure': 'failure ' + str(i),
           'applicability': 'exact scope ' + str(i), 'log': 'log ' + str(i)} for i in range(75)]
checks[-1]['failure'] = 'FINAL_CHECK_SENTINEL'
with open(sys.argv[1], 'w') as stream:
    json.dump({'schema_version': 1, 'checks': checks}, stream)
PY
    p=$("$SCRIPTS/rev-prompt.sh" "$S" all sol correctness focused) || return
    assert_grep 'structured baseline is never silently truncated' "$p" 'FINAL_CHECK_SENTINEL'
  )
}

test_prompt_cost_structured_baseline_invalid() {
  ( local R="$T/prompt-cost-invalid-repo" S="$T/prompt-cost-invalid-session"
    prompt_cost_fixture "$R" "$S"
    printf 'fallback must not mask malformed structured input\n' > "$S/baseline.md"
    local bad n=0
    for bad in \
      '{oops}' \
      '{"schema_version":1,"checks":[]}' \
      '{"schema_version":true,"checks":[]}' \
      '{"schema_version":1,"checks":[{"command":"x","outcome":"failed","applicability":"base"}]}' \
      '{"schema_version":1,"checks":[{"command":"x","outcome":"passed","applicability":"base","failure":"unexpected"}]}' \
      '{"schema_version":1,"checks":[{"command":"x","outcome":"unknown","applicability":"base"}]}' \
      '{"schema_version":1,"checks":[{"command":" ","outcome":"passed","applicability":"base"}]}' \
      '{"schema_version":1,"checks":[{"command":"x","outcome":"passed","applicability":"base","log":false}]}' \
      '{"schema_version":1,"schema_version":1,"checks":[]}' \
      '{"schema_version":1,"checks":[{"command":"x","command":"y","outcome":"passed","applicability":"base"}]}' \
      '{"schema_version":1,"checks":[{"command":"x","outcome":"passed","applicability":"base","unexpected":1}]}' \
      '{"schema_version":1,"checks":[],"unexpected":1}'; do
      n=$((n + 1)); printf '%s\n' "$bad" > "$S/baseline.json"
      printf 'stale\n' > "$S/rinvalid-sol.prompt.md"
      "$SCRIPTS/rev-prompt.sh" "$S" invalid sol correctness focused > "$T/prompt-cost-invalid.out" 2> "$T/prompt-cost-invalid.err"
      assert_eq "invalid baseline $n rejects rendering" "$?" 1
      assert_eq "invalid baseline $n publishes no prompt path" "$(cat "$T/prompt-cost-invalid.out")" ''
      assert_exit "invalid baseline $n removes stale prompt" 1 test -e "$S/rinvalid-sol.prompt.md"
      assert_grep "invalid baseline $n has an explicit diagnostic" "$T/prompt-cost-invalid.err" 'baseline'
    done
    rm "$S/baseline.json"; mkdir "$S/baseline.json"
    assert_exit 'baseline directory is rejected' 1 "$SCRIPTS/rev-prompt.sh" "$S" directory sol correctness focused
    rmdir "$S/baseline.json"; printf '{}\n' > "$T/baseline-target.json"; ln -s "$T/baseline-target.json" "$S/baseline.json"
    assert_exit 'structured baseline symlink is rejected' 1 "$SCRIPTS/rev-prompt.sh" "$S" symlink sol correctness focused
  )
}
