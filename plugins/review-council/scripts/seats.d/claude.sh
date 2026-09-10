#!/bin/bash
# External Anthropic seat for a Codex-hosted council. No inherited plugins/MCPs;
# only read tools and Bash guarded by the same allowlist as the Claude agent.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SETTINGS=$(python3 - "$HERE/../lib/readonly-bash-guard.py" <<'PY'
import json, shlex, sys
print(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
    {'type': 'command', 'command': 'python3 ' + shlex.quote(sys.argv[1])}
]}]}}))
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
    --json-schema "$SCHEMA_TEXT" --output-format stream-json --verbose < "$PROMPT" ) 2>>"$LOG" \
  | tee "$RAW" | python3 -u "$HERE/../lib/stream-summary.py" claude "$OUT" >> "$LOG"
exit "${PIPESTATUS[0]}"
