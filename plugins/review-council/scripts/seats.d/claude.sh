#!/bin/bash
# External Anthropic seat for a Codex-hosted council. No inherited plugins/MCPs;
# only read tools and Bash guarded by the same allowlist as the Claude agent.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SESSION=$(dirname "$OUT")
SETTINGS=$(python3 - "$HERE/../lib/readonly-bash-guard.py" "$HERE/../lib/review-read-audit.py" \
  "$ROOT" "$SESSION" "${REV_DEPS_DIR:-}" <<'PY'
import json, shlex, sys
readonly = 'python3 ' + shlex.quote(sys.argv[1])
bounded = 'python3 ' + shlex.quote(sys.argv[2]) + ' hook --root ' + shlex.quote(sys.argv[3]) + ' --session ' + shlex.quote(sys.argv[4])
post = 'python3 ' + shlex.quote(sys.argv[2]) + ' post-hook --root ' + shlex.quote(sys.argv[3]) + ' --session ' + shlex.quote(sys.argv[4])
if sys.argv[5]:
    bounded += ' --deps ' + shlex.quote(sys.argv[5])
    post += ' --deps ' + shlex.quote(sys.argv[5])
bounded_pre = [
    {'matcher': 'Read', 'hooks': [{'type': 'command', 'command': bounded}]},
    {'matcher': 'Grep', 'hooks': [{'type': 'command', 'command': bounded}]},
    {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': readonly},
                                  {'type': 'command', 'command': bounded}]},
]
bounded_post = [
    {'matcher': tool, 'hooks': [{'type': 'command', 'command': post}]}
    for tool in ('Read', 'Grep', 'Bash')
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
set -o pipefail
( cd "$ROOT" && claude -p --model "$MODEL" --effort "${EFFORT:-max}" \
    --permission-mode plan --tools 'Read,Glob,Grep,Bash' \
    --disallowedTools 'Write,Edit,NotebookEdit' --setting-sources '' \
    --strict-mcp-config --settings "$SETTINGS" --no-session-persistence \
    --exclude-dynamic-system-prompt-sections \
    --json-schema "$SCHEMA_TEXT" --output-format stream-json --verbose < "$PROMPT" ) 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$HERE/../lib/stream-summary.py" claude "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
