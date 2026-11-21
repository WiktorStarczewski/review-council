# claude CLI seat launched by rev-seat.sh from inside a Claude Code session. Sourced by run-tests.sh.
test_seat_claude_cli_scrubs_parent_session() {
  ( local B="$T/seat-claude-cli" R="$T/seat-claude-cli-repo"; mkrepo "$R"; mkdir -p "$B/bin" "$B/session" "$R/src"
    local S="$B/session"
    printf 'alpha\nterminal\n\n' > "$R/src/provider-contract.txt"
    printf 'Assigned scope: full\n' > "$B/prompt.md"
    cat > "$S/roster.json" <<'JSON'
{"seats":[{"seat":"sonnet","lab":"anthropic","adapter":"claude","model":"sonnet","effort":"max","extra":false}],"excluded":[]}
JSON
    cat > "$B/bin/claude" <<'SH'
#!/bin/bash
[ "${1:-}" = --version ] && { echo '2.1.328 (Claude Code)'; exit 0; }
printf '%s\n' "$@" > "$SEAT_CLAUDE_ARGS"
env | cut -d= -f1 | sort > "$SEAT_CLAUDE_ARGS.env"
printf 'REV_ACTIVE=%s\ncwd=%s\n' "${REV_ACTIVE:-unset}" "$PWD" >> "$SEAT_CLAUDE_ARGS.env"
cat > "$SEAT_CLAUDE_ARGS.stdin"
cat "$SEAT_CLAUDE_STREAM"
SH
    chmod +x "$B/bin/claude"
    export PATH="$B/bin:$PATH" REV_REPO="$R" SEAT_CLAUDE_ARGS="$B/args" \
           SEAT_CLAUDE_STREAM="$FX/provider-contract-claude.ndjson"
    local scrubbed=(CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION_ID CLAUDE_CODE_CHILD_SESSION
                    CLAUDE_CODE_SESSION_ATTENDED CLAUDE_CODE_BRIDGE_SESSION_ID CLAUDE_CODE_MESSAGING_SOCKET
                    CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_CODE_EXECPATH CLAUDE_CODE_SSE_PORT CLAUDE_PID
                    CLAUDE_EFFORT CLAUDE_PLUGIN_DATA CLAUDE_PLUGIN_ROOT)
    local kept=(CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_BASE_URL CLAUDE_CONFIG_DIR
                CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX)
    local var
    for var in "${scrubbed[@]}" "${kept[@]}"; do export "$var=parent-$var"; done
    printf '{"blocks":3}\n' > "$S/r1-sonnet.stop-gate"
    printf '{"gate":1}\n{"credit":"stale","id":"old"}\n' > "$S/r1-sonnet.read-gate"
    "$SCRIPTS/rev-seat.sh" sonnet "$S" 1 "$B/prompt.md" > "$B/out.txt" 2> "$B/err.txt"
    assert_eq "a nested claude CLI seat exits 0" "$?" 0
    assert_grep "the nested seat returns a schema-valid result" "$B/out.txt" '^seat=sonnet round=1 exit=0 findings=0$'
    assert_exit "the nested result validates against the findings schema" 0 \
      python3 "$SCRIPTS/lib/validate-findings.py" "$S/r1-sonnet.json"
    assert_grep "the nested seat is read-audited" "$S/r1-sonnet.read-audit.json" '"status":"valid"'
    for var in "${scrubbed[@]}"; do
      assert_nogrep "the child does not inherit $var" "$B/args.env" "^$var\$"
    done
    for var in "${kept[@]}"; do
      assert_grep "the child keeps $var" "$B/args.env" "^$var\$"
    done
    assert_grep "the recursion guard survives the scrub" "$B/args.env" '^REV_ACTIVE=1$'
    assert_grep "the child runs from the repo root" "$B/args.env" "^cwd=$R\$"
    assert_exit "the child loads no setting sources and only strict MCP config" 0 python3 - "$B/args" <<'PY'
import sys
args = open(sys.argv[1]).read().split('\n')
index = args.index('--setting-sources')
assert args[index + 1] == '', args
assert '--strict-mcp-config' in args, args
assert args[args.index('--model') + 1] == 'sonnet' and args[args.index('--effort') + 1] == 'max', args
PY
    assert_exit "each attempt starts a fresh stop-gate count" 1 test -e "$S/r1-sonnet.stop-gate"
    assert_exit "the stop gate replays this attempt's raw stream" 0 python3 - "$B/args" "$S" <<'PY'
import json, shlex, sys
args = open(sys.argv[1]).read().split('\n')
session = sys.argv[2]
settings = json.loads(args[args.index('--settings') + 1])['hooks']
hooks = settings['Stop']
assert len(hooks) == 1 and len(hooks[0]['hooks']) == 1, hooks
submit = [row for row in settings['PreToolUse'] if row.get('matcher') == 'StructuredOutput']
assert len(submit) == 1 and submit[0]['hooks'] == hooks[0]['hooks'], settings
command = hooks[0]['hooks'][0]['command']
assert command.endswith(' || true'), command
words = shlex.split(command[:-len(' || true')])
assert words[1].endswith('/lib/review-read-audit.py') and words[2] == 'stop-hook', words
option = {words[index]: words[index + 1] for index in range(3, len(words) - 1, 2)}
assert option['--adapter'] == 'claude', option
assert option['--raw'] == session + '/r1-sonnet.stream.ndjson', option
assert option['--state'] == session + '/r1-sonnet.stop-gate', option
assert option['--seat'] == 'sonnet' and option['--session'] == session, option
assert option['--evidence-cache'] == session + '/r1-sonnet.evidence-cache', option
assert option['--log'] == session + '/r1-sonnet.log', option
assert option['--timeout'] == str(hooks[0]['hooks'][0]['timeout']), (option, hooks)
PY
    assert_exit "a prompt without an evidence manifest leaves no read-gate state" 1 \
      test -e "$S/r1-sonnet.read-gate"
    assert_grep "the read gate was started for this prompt" "$S/r1-sonnet.log" \
      '^read gate off: the prompt declares no evidence manifest$'
    assert_exit "the read hooks share this attempt's read-gate state" 0 python3 - "$B/args" "$S" <<'PY'
import json, shlex, sys
args = open(sys.argv[1]).read().split('\n')
session = sys.argv[2]
settings = json.loads(args[args.index('--settings') + 1])['hooks']
for event, tools in (('PreToolUse', ('Read', 'Grep')), ('PostToolUse', ('Read', 'Grep'))):
    for tool in tools:
        rows = [row for row in settings[event] if row.get('matcher') == tool]
        assert len(rows) == 1, (event, tool, settings)
        words = shlex.split(rows[0]['hooks'][0]['command'])
        option = {words[index]: words[index + 1] for index in range(3, len(words) - 1, 2)}
        assert option['--gate'] == session + '/r1-sonnet.read-gate', (event, option)
        if event == 'PreToolUse':
            assert option['--raw'] == session + '/r1-sonnet.stream.ndjson', option
PY
    assert_exit "the rendered prompt reaches the child on stdin" 0 cmp -s "$B/prompt.md" "$B/args.stdin"
  )
}

test_seat_claude_cli_runs_the_pinned_binary() {
  ( local B="$T/seat-claude-pin" R="$T/seat-claude-pin-repo"; mkrepo "$R"; mkdir -p "$B/session"
    local S="$B/session" dir P
    printf 'Assigned scope: full\n' > "$B/prompt.md"
    P=$(cd "$B" && pwd -P)
    for dir in pinned impostor stale; do
      mkdir -p "$B/$dir"
      cat > "$B/$dir/claude" <<'SH'
#!/bin/bash
case "$0" in */stale/*) version=2.1.121;; */impostor/*) version=2.1.400;; *) version=2.1.328;; esac
[ "${1:-}" = --version ] && { printf '%s (Claude Code)\n' "$version"; exit 0; }
printf '%s\n' "$0" >> "$PIN_CALLS"
cat > /dev/null
printf '%s\n' '{"type":"system","subtype":"init","claude_code_version":"'"$version"'","model":"claude-haiku-5-5"}'
cat "$SEAT_CLAUDE_STREAM"
SH
      chmod +x "$B/$dir/claude"
    done
    export PATH="$B/impostor:$PATH" REV_REPO="$R" PIN_CALLS="$B/calls" \
           SEAT_CLAUDE_STREAM="$FX/provider-contract-claude.ndjson"
    pin_roster() {
      printf '{"seats":[{"seat":"opus","lab":"anthropic","adapter":"claude","model":"opus","effort":"max","extra":false}],"excluded":[],"claude_cli":{"path":"%s","version":"%s"}}\n' \
        "$B/$1/claude" "$2" > "$S/roster.json"
    }
    pin_roster pinned 2.1.328
    "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$B/prompt.md" > "$B/out.txt" 2> "$B/err.txt"
    assert_eq "a pinned claude seat exits 0" "$?" 0
    assert_eq "the seat runs the recorded binary, not the first claude on PATH" \
      "$(cat "$B/calls")" "$P/pinned/claude"
    assert_grep "the seat log names the CLI it checked" "$S/r1-opus.log" \
      "^claude CLI 2.1.328 at $P/pinned/claude\$"
    assert_grep "the seat log records the version and model that ran" "$S/r1-opus.log" \
      '^init claude_code_version=2.1.328 model=claude-haiku-5-5$'

    : > "$B/calls"
    pin_roster stale 2.1.121
    rm -f "$S"/r1-opus.*
    "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$B/prompt.md" > "$B/out.txt" 2> "$B/err.txt"
    assert_eq "an old claude CLI fails the seat" "$?" 2
    assert_eq "an old claude CLI never runs the review" "$(cat "$B/calls")" ""
    assert_grep "the refusal names the version, path and minimum" "$B/err.txt" \
      "claude CLI 2.1.121 at $P/stale/claude is older than 2.1.328\$"
    assert_grep "the seat log keeps the refusal" "$S/r1-opus.log" \
      "^claude adapter: claude CLI 2.1.121 at $P/stale/claude is older than 2.1.328\$"
  )
}

test_seat_claude_stream_summary_names_a_non_completed_terminal_reason() {
  ( local B="$T/stream-summary-reason" run
    mkdir -p "$B"
    summarize() {
      printf '{"type":"result","subtype":"success","is_error":false,"num_turns":3%s}\n' "$1" \
        | python3 "$SCRIPTS/lib/stream-summary.py" claude "$B/out.json" 2>&1
    }
    run=$(summarize ',"terminal_reason":"hook_stopped"')
    assert_eq "a result stopped by a hook names its terminal reason" "$run" \
      "end status=success turns=3 terminal_reason=hook_stopped"
    run=$(summarize ',"terminal_reason":"completed"')
    assert_eq "a completed terminal reason adds nothing" "$run" "end status=success turns=3"
    run=$(summarize '')
    assert_eq "a result with no terminal reason adds nothing" "$run" "end status=success turns=3"
  )
}
