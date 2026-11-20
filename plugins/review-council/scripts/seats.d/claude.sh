#!/bin/bash
# External Anthropic seat run through the claude CLI, on either host. No inherited plugins/MCPs and no
# parent Claude Code session identity; only native read tools audited against the current evidence contract.
set -u
[ -n "${EFFORT:-}" ] || { echo "claude adapter: missing receipted effort" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
SESSION=$(dirname "$OUT")
MAX_TURNS=$(PYTHONPATH="$HERE/../lib" python3 -c \
  'from review_limits import CLAUDE_MAX_TURNS; print(CLAUDE_MAX_TURNS)') || exit 1
SESSION_ENV=$(cd "$HERE/../lib" && python3 -c \
  'from roster import CLAUDE_SESSION_ENV; print(" ".join(CLAUDE_SESSION_ENV))') || exit 1
unset $SESSION_ENV
# The binary preflight recorded in the roster, never whichever claude is first on PATH now.
CLAUDE_CLI=$(python3 "$HERE/../lib/roster.py" --claude-cli "$SESSION/roster.json" 2>&1) || {
  printf 'claude adapter: %s\n' "$CLAUDE_CLI" | tee -a "$LOG" >&2; exit 1; }
CLAUDE_BIN=$(printf '%s\n' "$CLAUDE_CLI" | sed -n 1p)
printf 'claude CLI %s at %s\n' "$(printf '%s\n' "$CLAUDE_CLI" | sed -n 2p)" "$CLAUDE_BIN" >> "$LOG"
STOP_STATE="${OUT%.json}.stop-gate"
READ_GATE="${OUT%.json}.read-gate"
EVIDENCE_CACHE="${OUT%.json}.evidence-cache"
rm -f "$STOP_STATE" "$READ_GATE" "$EVIDENCE_CACHE" "$EVIDENCE_CACHE.lock"
python3 "$HERE/../lib/review-read-audit.py" read-gate-init --prompt "$PROMPT" --root "$ROOT" \
  --session "$SESSION" --state "$READ_GATE" 2>>"$LOG" || rm -f "$READ_GATE"
# The stop gate replays the read audit, whose evidence validation alone can outlast the hook
# timeout; validating it while the seat reads lets the replay reuse the result.
python3 "$HERE/../lib/review-read-audit.py" evidence-cache --prompt "$PROMPT" --root "$ROOT" \
  --session "$SESSION" --cache "$EVIDENCE_CACHE" </dev/null >/dev/null 2>>"$LOG" &
WARM_PID=$!
trap 'kill "$WARM_PID" 2>/dev/null; rm -f "$EVIDENCE_CACHE" "$EVIDENCE_CACHE.lock"' EXIT
SETTINGS=$(python3 - "$HERE/../lib/review-read-audit.py" \
  "$ROOT" "$SESSION" "$PROMPT" "${REV_DEPS_DIR:-}" "$RAW" "$STOP_STATE" "${SEAT:-}" "$READ_GATE" \
  "$EVIDENCE_CACHE" "$LOG" <<'PY'
import json, shlex, sys
timeout = 300
bounded = 'python3 ' + shlex.quote(sys.argv[1]) + ' hook --root ' + shlex.quote(sys.argv[2]) + ' --session ' + shlex.quote(sys.argv[3]) + ' --prompt ' + shlex.quote(sys.argv[4]) + ' --raw ' + shlex.quote(sys.argv[6]) + ' --gate ' + shlex.quote(sys.argv[9])
post = 'python3 ' + shlex.quote(sys.argv[1]) + ' post-hook --root ' + shlex.quote(sys.argv[2]) + ' --session ' + shlex.quote(sys.argv[3]) + ' --prompt ' + shlex.quote(sys.argv[4]) + ' --gate ' + shlex.quote(sys.argv[9])
stop = 'python3 ' + shlex.quote(sys.argv[1]) + ' stop-hook --adapter claude --raw ' + shlex.quote(sys.argv[6]) + ' --prompt ' + shlex.quote(sys.argv[4]) + ' --root ' + shlex.quote(sys.argv[2]) + ' --session ' + shlex.quote(sys.argv[3]) + ' --state ' + shlex.quote(sys.argv[7]) + ' --evidence-cache ' + shlex.quote(sys.argv[10]) + ' --log ' + shlex.quote(sys.argv[11]) + ' --timeout ' + str(timeout)
if sys.argv[8]:
    stop += ' --seat ' + shlex.quote(sys.argv[8])
if sys.argv[5]:
    bounded += ' --deps ' + shlex.quote(sys.argv[5])
    post += ' --deps ' + shlex.quote(sys.argv[5])
    stop += ' --deps ' + shlex.quote(sys.argv[5])
# Exit 2 blocks, so no stop-gate failure may exit 2. A --json-schema run ends at its
# StructuredOutput call without a Stop that can resume it, so the gate also checks that call.
stop = [{'type': 'command', 'command': stop + ' || true', 'timeout': timeout}]
bounded_pre = [
    {'matcher': 'Read', 'hooks': [{'type': 'command', 'command': bounded}]},
    {'matcher': 'Grep', 'hooks': [{'type': 'command', 'command': bounded}]},
    {'matcher': 'StructuredOutput', 'hooks': stop},
]
bounded_post = [
    {'matcher': tool, 'hooks': [{'type': 'command', 'command': post}]}
    for tool in ('Read', 'Grep')
]
print(json.dumps({'hooks': {
    'PreToolUse': bounded_pre, 'PostToolUse': bounded_post, 'Stop': [{'hooks': stop}]}}))
PY
) || exit 1
# Claude's validator does not load the draft-2020-12 meta-schema. This schema
# uses common object/array constraints; omit only the dialect declaration.
SCHEMA_TEXT=$(python3 - "$SCHEMA" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    schema = json.load(stream)
schema.pop('$schema', None)
print(json.dumps(schema))
PY
) || exit 1
CONTINUATION='Continue the noninteractive review without waiting for user input. While required review work remains, every nonfinal assistant message must include the next allowed Read or Grep call. Never end a response with progress text alone. A progress note may accompany a tool call.'
set -o pipefail
( cd "$ROOT" && "$CLAUDE_BIN" -p --model "$MODEL" --effort "$EFFORT" --max-turns "$MAX_TURNS" \
    --permission-mode bypassPermissions --tools 'Read,Grep' \
    --disallowedTools 'Write,Edit,NotebookEdit' --setting-sources '' \
    --strict-mcp-config --settings "$SETTINGS" --no-session-persistence \
    --exclude-dynamic-system-prompt-sections --disable-slash-commands \
    --append-system-prompt "$CONTINUATION" \
    --json-schema "$SCHEMA_TEXT" --output-format stream-json --verbose < "$PROMPT" ) 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$HERE/../lib/stream-summary.py" claude "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
