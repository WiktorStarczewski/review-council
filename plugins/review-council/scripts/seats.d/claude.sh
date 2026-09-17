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
SETTINGS=$(python3 - "$HERE/../lib/review-read-audit.py" \
  "$ROOT" "$SESSION" "$PROMPT" "${REV_DEPS_DIR:-}" <<'PY'
import json, shlex, sys
bounded = 'python3 ' + shlex.quote(sys.argv[1]) + ' hook --root ' + shlex.quote(sys.argv[2]) + ' --session ' + shlex.quote(sys.argv[3]) + ' --prompt ' + shlex.quote(sys.argv[4])
post = 'python3 ' + shlex.quote(sys.argv[1]) + ' post-hook --root ' + shlex.quote(sys.argv[2]) + ' --session ' + shlex.quote(sys.argv[3]) + ' --prompt ' + shlex.quote(sys.argv[4])
if sys.argv[5]:
    bounded += ' --deps ' + shlex.quote(sys.argv[5])
    post += ' --deps ' + shlex.quote(sys.argv[5])
bounded_pre = [
    {'matcher': 'Read', 'hooks': [{'type': 'command', 'command': bounded}]},
    {'matcher': 'Grep', 'hooks': [{'type': 'command', 'command': bounded}]},
]
bounded_post = [
    {'matcher': tool, 'hooks': [{'type': 'command', 'command': post}]}
    for tool in ('Read', 'Grep')
]
print(json.dumps({'hooks': {'PreToolUse': bounded_pre, 'PostToolUse': bounded_post}}))
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
( cd "$ROOT" && claude -p --model "$MODEL" --effort "$EFFORT" --max-turns "$MAX_TURNS" \
    --permission-mode bypassPermissions --tools 'Read,Grep' \
    --disallowedTools 'Write,Edit,NotebookEdit' --setting-sources '' \
    --strict-mcp-config --settings "$SETTINGS" --no-session-persistence \
    --exclude-dynamic-system-prompt-sections --disable-slash-commands \
    --append-system-prompt "$CONTINUATION" \
    --json-schema "$SCHEMA_TEXT" --output-format stream-json --verbose < "$PROMPT" ) 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$HERE/../lib/stream-summary.py" claude "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
