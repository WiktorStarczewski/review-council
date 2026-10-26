#!/bin/bash
# rev-seat.sh <seat> <session-dir> <round> <prompt-file> [--effort <e>] [--base <ref>]
#
# Launch ONE read-only reviewer seat and leave schema-valid findings at <session>/r<N>-<seat>.json.
# The seat set is not hardcoded: <session>/roster.json (written by rev-preflight.sh) says which adapter,
# model, effort and mode this seat has, and scripts/seats.d/<adapter>.sh owns the CLI invocation.
# The `agent` adapter is launched by the skill through the Agent tool, not here.
# Also writes r<N>-<seat>.log (one summarised line per event), .stream.ndjson (raw), .exit (code).
# Exit: 0 valid JSON | 2 missing/invalid JSON | 3 not signed in | 4 provider quota | 7 local attempt cap | 1 other
#
# This file keeps everything that is NOT CLI-specific: roster lookup, effort precedence, the
# zero-tool-call retry, native-prose conversion, validation, classification and the summary line.
#   - NEVER edit this file in place while seats are running: bash reads scripts lazily and a rewritten inode corrupts
#     the in-flight run (seen: `--max-turns: command not found`). Write to a temp file and `mv` over it instead.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SCHEMA="$HERE/../schema/findings.schema.json"
VALIDATE="$HERE/lib/validate-findings.py"
usage() { echo "usage: rev-seat.sh <seat-from-roster.json> <session-dir> <round> <prompt-file> [--effort e] [--base ref]" >&2; exit 1; }
[ $# -ge 4 ] || usage
SEAT=$1; SESSION=$2; ROUND=$3; PROMPT=$4; shift 4
EFFORT=""; BASE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --effort) EFFORT=${2:?}; shift 2;;
    --base)   BASE=${2:?}; shift 2;;
    *) echo "rev-seat: unknown argument $1" >&2; exit 1;;
  esac
done
[ -f "$PROMPT" ] || { echo "rev-seat: prompt file missing: $PROMPT" >&2; exit 1; }

# --- the roster decides the seat ------------------------------------------------------------------
ROSTER="$SESSION/roster.json"
[ -f "$ROSTER" ] || { echo "rev-seat: no roster at $ROSTER - run preflight first" >&2; exit 1; }
SEATDEF=$(REV_LIB="$HERE/lib" REV_ROSTER_FILE="$ROSTER" REV_SEAT="$SEAT" python3 - <<'PY'
import os, sys
sys.path.insert(0, os.environ['REV_LIB'])
try:
    from workhorse import lookup_launch
    row = lookup_launch(os.environ['REV_ROSTER_FILE'], os.environ['REV_SEAT'])
except Exception as e:  # noqa: BLE001 - an unreadable roster is "no seat", the caller re-runs preflight
    print(f"unreadable roster: {e}", file=sys.stderr)
    sys.exit(1)
for k in ('adapter', 'model', 'effort', 'mode'):
    v = row.get(k)
    print('' if v is None else str(v))
PY
) || { echo "rev-seat: no seat '$SEAT' in $ROSTER - run preflight first" >&2; exit 1; }
ADAPTER=$(printf '%s\n' "$SEATDEF" | sed -n 1p)
MODEL=$(printf '%s\n' "$SEATDEF" | sed -n 2p)
ROSTER_EFFORT=$(printf '%s\n' "$SEATDEF" | sed -n 3p)
MODE=$(printf '%s\n' "$SEATDEF" | sed -n 4p)
[ -n "$ADAPTER" ] && [ -n "$MODEL" ] || { echo "rev-seat: seat '$SEAT' has no adapter/model in $ROSTER - run preflight first" >&2; exit 1; }
case "$ADAPTER" in
  agent) echo "rev-seat: seat '$SEAT' is the Agent tool seat - the skill launches it, rev-seat.sh cannot" >&2; exit 1;;
  cursor-agent) echo "rev-seat: seat '$SEAT' is the Cursor workhorse - the skill launches it, rev-seat.sh cannot" >&2; exit 1;;
  codex|gemini|claude|cursor-sdk) ;;
  *) echo "rev-seat: unsupported or retired adapter '$ADAPTER' (seat '$SEAT')" >&2; exit 1;;
esac
ADAPTER_SH="$HERE/seats.d/$ADAPTER.sh"
[ -x "$ADAPTER_SH" ] || { echo "rev-seat: no adapter script for '$ADAPTER' (seat '$SEAT')" >&2; exit 1; }

# The roster is the probe, receipt, and launch authority. A matching legacy argument is accepted so
# callers can migrate without changing command construction, but no later override may diverge.
case "$ADAPTER" in
  codex) ENV_EFFORT=${REV_CODEX_EFFORT:-};;
  *)     ENV_EFFORT="";;
esac
REQUESTED_EFFORT=${EFFORT:-$ENV_EFFORT}
if [ "$ADAPTER" = codex ] || [ "$ADAPTER" = claude ] || [ "$ADAPTER" = cursor-sdk ]; then
  [ -n "$ROSTER_EFFORT" ] || { echo "rev-seat: seat '$SEAT' has no receipted effort" >&2; exit 1; }
fi
if [ -n "$REQUESTED_EFFORT" ] && [ "$REQUESTED_EFFORT" != "$ROSTER_EFFORT" ]; then
  echo "rev-seat: requested effort '$REQUESTED_EFFORT' diverges from receipted effort '$ROSTER_EFFORT'" >&2
  exit 1
fi
EFFORT=$ROSTER_EFFORT
[ "$MODE" != review ] || [ -n "$BASE" ] || { echo "rev-seat: seat '$SEAT' (mode=review) needs --base <ref>" >&2; exit 1; }

mkdir -p "$SESSION"
if [ -f "$SESSION/scope.env" ]; then
  ROOT=$(python3 - "$HERE/lib" "$SESSION" <<'PY'
import sys

sys.path.insert(0, sys.argv[1])
from workhorse import scope_value

try:
    print(scope_value(sys.argv[2], 'REV_ROOT'))
except (OSError, ValueError) as error:
    print('rev-seat: invalid repository root in scope.env: ' + str(error), file=sys.stderr)
    raise SystemExit(1)
PY
  ) || exit 1
else
  ROOT=${REV_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
fi
[ -d "$ROOT" ] || { echo "rev-seat: repository root is not a directory: $ROOT" >&2; exit 1; }
BASEN="$SESSION/r${ROUND}-${SEAT}"
OUT="$BASEN.json"; LOG="$BASEN.log"; RAW="$BASEN.stream.ndjson"; EXITF="$BASEN.exit"
AUDITF="$BASEN.read-audit.json"
AUDIT_INVALID_OUT="$BASEN.audit-invalid.json"
export REV_ACTIVE=1
export SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
# An explicit REV_DEPS_DIR wins; otherwise the panel manifest's per-crate view is the dependency root.
if [ -z "${REV_DEPS_DIR:-}" ] && [ -f "$SESSION/r${ROUND}-evidence.manifest.json" ]; then
  REV_DEPS_DIR=$(python3 - "$SESSION" "$ROUND" <<'PY'
import json, os, sys
view = json.load(open(os.path.join(sys.argv[1], f'r{sys.argv[2]}-evidence.manifest.json'))).get('dependency_view')
if isinstance(view, dict) and isinstance(view.get('path'), str) \
        and os.path.realpath(view['path']) == os.path.realpath(os.path.join(sys.argv[1], 'deps')):
    print(view['path'])
PY
) || REV_DEPS_DIR=""
fi
[ -z "${REV_DEPS_DIR:-}" ] || export REV_DEPS_DIR
REPLACE_RULE="replace this assignment on another eligible seat; never relaunch this seat under this label"
preserve_audit_invalid_result() {
  if [ -s "$OUT" ]; then mv -f "$OUT" "$AUDIT_INVALID_OUT"
  else rm -f "$OUT" "$AUDIT_INVALID_OUT"
  fi
}

RESERVED=0
PUBLISH_UNRESERVED_EXIT=0
LAUNCH_TOKEN=$(python3 -c 'import uuid; print(uuid.uuid4().hex)') || exit 1
finish() {  # <code> - validate on 0, record, print the one-line summary, exit
  local code=$1 n="-"
  if [ "$code" = 0 ]; then n=$(python3 "$VALIDATE" "$OUT" 2>>"$LOG") || { code=2; n="-"; }; fi
  if [ "$RESERVED" = 1 ] || [ "$PUBLISH_UNRESERVED_EXIT" = 1 ]; then echo "$code" > "$EXITF"; fi
  # A launch that reserved a call records its exit, so an exhausted exact retry is on record.
  if [ "$RESERVED" = 1 ]; then
    python3 "$HERE/lib/rev-attempt.py" complete "$SESSION" "$ROUND" "$SEAT" "$PROMPT" "$code" "$LAUNCH_TOKEN" >>"$LOG" 2>&1 \
      || echo "cannot persist this launch's terminal intent" >> "$LOG"
    python3 "$HERE/lib/rev-attempt.py" record "$SESSION" "$ROUND" "$SEAT" "$PROMPT" "$code" "$LAUNCH_TOKEN" >>"$LOG" 2>&1 \
      || echo "cannot record this launch's exit" >> "$LOG"
  fi
  echo "seat=$SEAT round=$ROUND exit=$code findings=$n"
  exit "$code"
}
classify_failure() {  # after a non-zero rc or missing output: 3 auth, 4 cap, 2 no output, 1 other
  local kind
  kind=$(python3 "$HERE/lib/roster.py" --classify-log "$ADAPTER" "$LOG" 2>/dev/null) || kind=other
  case "$kind" in
    auth) echo 3;;
    quota) echo 4;;
    *) if [ ! -s "$OUT" ]; then echo 2; else echo 1; fi;;
  esac
}
has_tool_call() {
  case "$ADAPTER" in
    codex) grep -q '^exec: ' "$LOG";;
    *) grep -q '^tool_call ' "$LOG";;
  esac
}

# Under an "answer with only JSON" instruction, a model can answer on turn
# one WITHOUT reading anything, even when the prompt says to run tools first (seen live: summary "I'll
# inspect the diff…", zero findings, zero tool calls). An answer with no tool calls is not a review: retry
# once at the same effort, then fail the seat so the orchestrator's retry/skip rule applies.
if [ "$ADAPTER" = cursor-sdk ]; then
  SDK_ENV=$(python3 - "$HERE/lib" "$ROSTER" "$SEAT" 2>>"$LOG" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
from roster import cursor_sdk_environment
try:
    rows = [row for row in json.load(open(sys.argv[2]))['seats'] if row.get('seat') == sys.argv[3]]
    if len(rows) != 1:
        raise ValueError()
    environment = cursor_sdk_environment(rows[0])
    print(environment['REVIEW_COUNCIL_CURSOR_SDK_RUNTIME'])
    print(environment['REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION'])
except (OSError, ValueError, KeyError, TypeError):
    print('cursor-sdk frozen identity unavailable or changed', file=sys.stderr)
    raise SystemExit(2)
PY
  ) || finish 2
  REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=$(printf '%s\n' "$SDK_ENV" | sed -n 1p)
  REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION=$(printf '%s\n' "$SDK_ENV" | sed -n 2p)
  export REVIEW_COUNCIL_CURSOR_SDK_RUNTIME REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION
fi
check_error=$(python3 "$HERE/lib/rev-attempt.py" check "$SESSION" "$ROUND" "$SEAT" "$PROMPT" 2>&1)
check_rc=$?
if [ "$check_rc" -ne 0 ]; then
  [ -z "$check_error" ] || printf 'rev-seat: %s\n' "$check_error" >&2
  [ -z "$check_error" ] || printf '%s\n' "$check_error" >> "$LOG"
  if [ "$check_rc" -ne 2 ]; then
    # No provider launched, so a local check error must preserve its previous completion evidence.
    echo "seat=$SEAT round=$ROUND exit=$check_rc findings=-"
    exit "$check_rc"
  fi
  PUBLISH_UNRESERVED_EXIT=1
  finish "$check_rc"
fi
attempt=0
while :; do
  attempt=$((attempt+1))
  reserve_error=$(python3 "$HERE/lib/rev-attempt.py" reserve "$SESSION" "$ROUND" "$SEAT" "$PROMPT" "$LAUNCH_TOKEN" 2>&1)
  reserve_rc=$?
  if [ "$reserve_rc" -ne 0 ]; then
    [ -z "$reserve_error" ] || printf 'rev-seat: %s\n' "$reserve_error" >&2
    [ -z "$reserve_error" ] || printf '%s\n' "$reserve_error" >> "$LOG"
    if [ "$reserve_rc" -eq 7 ]; then
      echo "persistent adapter-launch cap reached for this seat generation" >> "$LOG"
      echo "rev-seat: persistent adapter-launch cap reached for this seat generation" >&2
      PUBLISH_UNRESERVED_EXIT=1
    fi
    finish "$reserve_rc"
  fi
  RESERVED=1
  rm -f "$EXITF" "$OUT" "$AUDITF"
  [ "$attempt" -ne 1 ] || : > "$LOG"
  "$ADAPTER_SH"; rc=$?
  case "$ADAPTER" in
    codex|gemini|claude)
      if [ "$rc" -eq 0 ] && ! has_tool_call; then
        echo "$ADAPTER answered without a single tool call (attempt $attempt) - not a review" >> "$LOG"
        rm -f "$OUT"
        if [ "$attempt" -lt 2 ]; then continue; fi
        rc=1
      fi;;
  esac
  break
done

if [ "$ADAPTER" = cursor-sdk ] && [ "$rc" -ne 0 ]; then
  [ ! -s "$OUT" ] || mv "$OUT" "$BASEN.transport-invalid.json"
  case "$rc" in 1|2|3|4) finish "$rc";; *) finish 1;; esac
fi

if [ "$ADAPTER" = cursor-sdk ] && [ "$rc" -eq 0 ]; then
  SDK_STRICT_DIR=$(mktemp -d "$BASEN.strict-result.XXXXXX") || {
    [ ! -s "$OUT" ] || mv "$OUT" "$BASEN.transport-invalid.json"
    finish 2
  }
  if python3 "$HERE/lib/stream-summary.py" cursor-sdk "$SDK_STRICT_DIR/result.json" < "$RAW" >>"$LOG" 2>&1 &&
    python3 - "$SDK_STRICT_DIR/result.json" "$OUT" >>"$LOG" 2>&1 <<'PY'
import json, sys

def unique(rows):
    value = {}
    for key, item in rows:
        if key in value:
            raise ValueError('duplicate published result key')
        value[key] = item
    return value

def finite(token):
    raise ValueError('non-finite published result')

def load(path):
    with open(path) as source:
        value = json.load(source, object_pairs_hook=unique, parse_constant=finite)
    json.dumps(value, allow_nan=False)
    return value

def same(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right

if not same(load(sys.argv[1]), load(sys.argv[2])):
    raise ValueError('SDK terminal and published result disagree')
PY
  then
    rm -rf "$SDK_STRICT_DIR"
  else
    rm -rf "$SDK_STRICT_DIR"
    [ ! -s "$OUT" ] || mv "$OUT" "$BASEN.transport-invalid.json"
    finish 2
  fi
fi

if [ "$ADAPTER" = codex ] && [ "$MODE" = review ] && [ -s "$OUT" ] && ! python3 "$VALIDATE" "$OUT" >/dev/null 2>&1; then
  # `codex exec review` ignores --output-schema and answers in prose; keep the prose and convert it.
  cp "$OUT" "$BASEN.native.txt"
  python3 "$HERE/lib/codex-review-to-findings.py" "$BASEN.native.txt" "$OUT" --root "$ROOT" >>"$LOG" 2>&1 || true
fi

if [ "$rc" -eq 0 ] && [ -s "$OUT" ]; then
  AUDIT_ARGS=(audit --adapter "$ADAPTER" --raw "$RAW" --prompt "$PROMPT" \
    --root "$ROOT" --session "$SESSION" --seat "$SEAT" --out "$AUDITF")
  [ -z "${REV_DEPS_DIR:-}" ] || AUDIT_ARGS+=(--deps "$REV_DEPS_DIR")
  python3 "$HERE/lib/review-read-audit.py" "${AUDIT_ARGS[@]}" >>"$LOG" 2>&1
  AUDIT_RC=$?
  AUDIT_SCOPE=$(python3 - "$AUDITF" "$AUDIT_RC" 2>>"$LOG" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding='utf-8') as stream:
    audit = json.load(stream)
status = audit.get('status')
evidence_scoped = audit.get('evidence_scoped')
narrow = audit.get('narrow')
violations = audit.get('violations')
exit_code = int(sys.argv[2])
if (audit.get('schema_version') != 2 or status not in ('valid', 'invalid')
        or type(evidence_scoped) is not bool or type(narrow) is not bool
        or not isinstance(violations, list) or narrow and not evidence_scoped
        or exit_code not in (0, 2) or (status == 'valid') != (exit_code == 0)
        or (status == 'valid') != (not violations)):
    raise ValueError('inconsistent bounded-read audit metadata')
manifest_hash = audit.get('evidence_manifest_sha256')
if ((not evidence_scoped and manifest_hash is not None)
        or (status == 'valid' and evidence_scoped
            and re.fullmatch(r'[0-9a-f]{64}', manifest_hash or '') is None)):
    raise ValueError('inconsistent bounded-read audit evidence binding')
print('narrow' if narrow else 'full' if evidence_scoped else 'legacy')
PY
  )
  AUDIT_META_RC=$?
  if [ "$AUDIT_META_RC" -ne 0 ]; then
    echo "bounded-read audit metadata is missing, malformed, or inconsistent; $REPLACE_RULE" >> "$LOG"
    preserve_audit_invalid_result
    finish 2
  fi
  if [ "$AUDIT_RC" -ne 0 ]; then
    case "$AUDIT_SCOPE" in
      full)
        echo "bounded-read audit rejected full-scope evidence review; $REPLACE_RULE" >> "$LOG"
        preserve_audit_invalid_result
        finish 2;;
      narrow)
        echo "bounded-read audit rejected narrowed review; $REPLACE_RULE" >> "$LOG"
        preserve_audit_invalid_result
        finish 2;;
      legacy)
        echo "bounded-read audit found violations in a legacy review; result retained as advisory" >> "$LOG";;
    esac
  fi
fi

if [ "$rc" -ne 0 ] || [ ! -s "$OUT" ]; then finish "$(classify_failure)"; fi
finish 0
