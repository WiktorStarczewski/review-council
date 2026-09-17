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
    assert_exit "the rendered prompt reaches the child on stdin" 0 cmp -s "$B/prompt.md" "$B/args.stdin"
  )
}
