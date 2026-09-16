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
SEATDEF=$(REV_ROSTER_FILE="$ROSTER" REV_SEAT="$SEAT" python3 - <<'PY'
import json, os, sys
try:
    with open(os.environ['REV_ROSTER_FILE']) as f:
        doc = json.load(f)
except Exception as e:  # noqa: BLE001 - an unreadable roster is "no seat", the caller re-runs preflight
    print(f"unreadable roster: {e}", file=sys.stderr)
    sys.exit(1)
for s in (doc.get('seats') or []) if isinstance(doc, dict) else []:
    if isinstance(s, dict) and s.get('seat') == os.environ['REV_SEAT']:
        for k in ('adapter', 'model', 'effort', 'mode'):
            v = s.get(k)
            print('' if v is None else str(v))
        sys.exit(0)
sys.exit(1)
PY
) || { echo "rev-seat: no seat '$SEAT' in $ROSTER - run preflight first" >&2; exit 1; }
ADAPTER=$(printf '%s\n' "$SEATDEF" | sed -n 1p)
MODEL=$(printf '%s\n' "$SEATDEF" | sed -n 2p)
ROSTER_EFFORT=$(printf '%s\n' "$SEATDEF" | sed -n 3p)
MODE=$(printf '%s\n' "$SEATDEF" | sed -n 4p)
[ -n "$ADAPTER" ] && [ -n "$MODEL" ] || { echo "rev-seat: seat '$SEAT' has no adapter/model in $ROSTER - run preflight first" >&2; exit 1; }
case "$ADAPTER" in
  agent) echo "rev-seat: seat '$SEAT' is the Agent tool seat - the skill launches it, rev-seat.sh cannot" >&2; exit 1;;
  codex|gemini|claude) ;;
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
if [ "$ADAPTER" = codex ] || [ "$ADAPTER" = claude ]; then
  [ -n "$ROSTER_EFFORT" ] || { echo "rev-seat: seat '$SEAT' has no receipted effort" >&2; exit 1; }
fi
if [ -n "$REQUESTED_EFFORT" ] && [ "$REQUESTED_EFFORT" != "$ROSTER_EFFORT" ]; then
  echo "rev-seat: requested effort '$REQUESTED_EFFORT' diverges from receipted effort '$ROSTER_EFFORT'" >&2
  exit 1
fi
EFFORT=$ROSTER_EFFORT
[ "$MODE" != review ] || [ -n "$BASE" ] || { echo "rev-seat: seat '$SEAT' (mode=review) needs --base <ref>" >&2; exit 1; }

mkdir -p "$SESSION"
ROOT=${REV_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
BASEN="$SESSION/r${ROUND}-${SEAT}"
OUT="$BASEN.json"; LOG="$BASEN.log"; RAW="$BASEN.stream.ndjson"; EXITF="$BASEN.exit"
AUDITF="$BASEN.read-audit.json"
AUDIT_INVALID_OUT="$BASEN.audit-invalid.json"
export REV_ACTIVE=1
export SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
preserve_audit_invalid_result() {
  if [ -s "$OUT" ]; then mv -f "$OUT" "$AUDIT_INVALID_OUT"
  else rm -f "$OUT" "$AUDIT_INVALID_OUT"
  fi
}
stop_panel_generation() {
  python3 "$HERE/lib/rev-attempt.py" stop "$SESSION" "$ROUND" --reason "hard evidence audit failed" >>"$LOG" 2>&1
}

finish() {  # <code> - validate on 0, record, print the one-line summary, exit
  local code=$1 n="-"
  if [ "$code" = 0 ]; then n=$(python3 "$VALIDATE" "$OUT" 2>>"$LOG") || { code=2; n="-"; }; fi
  echo "$code" > "$EXITF"
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
archive_raw() {
  ARCHIVED_RAW=""
  [ -s "$RAW" ] || return 0
  local n=1 archived
  while :; do
    archived="${RAW%.ndjson}.attempt${n}.ndjson"
    [ -e "$archived" ] || break
    n=$((n+1))
  done
  mv "$RAW" "$archived" || return 1
  ARCHIVED_RAW=$archived
}
restore_raw() {
  [ -n "${ARCHIVED_RAW:-}" ] || return 0
  mv "$ARCHIVED_RAW" "$RAW" || return 1
  ARCHIVED_RAW=""
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
PANEL_CHECK_ERROR=$(python3 "$HERE/lib/rev-attempt.py" check "$SESSION" "$ROUND" 2>&1)
PANEL_CHECK_RC=$?
if [ "$PANEL_CHECK_RC" -eq 2 ]; then
  echo "$PANEL_CHECK_ERROR" >> "$LOG"
  printf 'rev-seat: %s\n' "$PANEL_CHECK_ERROR" >&2
  finish 2
elif [ "$PANEL_CHECK_RC" -ne 0 ]; then
  echo "cannot validate panel attempt state" >> "$LOG"
  finish 1
fi
rm -f "$EXITF"
attempt=0
while :; do
  attempt=$((attempt+1))
  archive_raw || { echo "cannot archive prior stream before attempt $attempt" >> "$LOG"; finish 1; }
  reserve_error=$(python3 "$HERE/lib/rev-attempt.py" reserve "$SESSION" "$ROUND" "$SEAT" "$PROMPT" 2>&1)
  reserve_rc=$?
  if [ "$reserve_rc" -ne 0 ]; then
    restore_raw || { echo "cannot restore prior stream after reservation refusal" >> "$LOG"; finish 1; }
    [ -z "$reserve_error" ] || printf 'rev-seat: %s\n' "$reserve_error" >&2
    if [ "$reserve_rc" -eq 7 ]; then
      echo "persistent provider-call cap reached for this seat generation" >> "$LOG"
      echo "rev-seat: persistent provider-call cap reached for this seat generation" >&2
    fi
    finish "$reserve_rc"
  fi
  rm -f "$OUT" "$AUDITF"
  [ "$attempt" -ne 1 ] || : > "$LOG"
  "$ADAPTER_SH"; rc=$?
  case "$ADAPTER" in
    codex|gemini|claude)
      if [ "$rc" -eq 0 ] && ! has_tool_call; then
        echo "$ADAPTER answered without a single tool call (attempt $attempt) - not a review" >> "$LOG"
        if [ "$attempt" -lt 2 ]; then continue; fi
        rm -f "$OUT"
        rc=1
      fi;;
  esac
  break
done

if [ "$ADAPTER" = codex ] && [ "$MODE" = review ] && [ -s "$OUT" ] && ! python3 "$VALIDATE" "$OUT" >/dev/null 2>&1; then
  # `codex exec review` ignores --output-schema and answers in prose; keep the prose and convert it.
  cp "$OUT" "$BASEN.native.txt"
  python3 "$HERE/lib/codex-review-to-findings.py" "$BASEN.native.txt" "$OUT" --root "$ROOT" >>"$LOG" 2>&1 || true
fi

if [ "$rc" -eq 0 ] && [ -s "$OUT" ]; then
  AUDIT_ARGS=(audit --adapter "$ADAPTER" --raw "$RAW" --prompt "$PROMPT" --root "$ROOT" --session "$SESSION" --out "$AUDITF")
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
    echo "bounded-read audit metadata is missing, malformed, or inconsistent" >> "$LOG"
    preserve_audit_invalid_result
    stop_panel_generation || echo "cannot persist panel hard-stop state" >> "$LOG"
    finish 2
  fi
  if [ "$AUDIT_RC" -ne 0 ]; then
    case "$AUDIT_SCOPE" in
      full)
        echo "bounded-read audit rejected full-scope evidence review; stop the panel before another reviewer launch" >> "$LOG"
        preserve_audit_invalid_result
        stop_panel_generation || echo "cannot persist panel hard-stop state" >> "$LOG"
        finish 2;;
      narrow)
        echo "bounded-read audit rejected narrowed review; stop the panel before another reviewer launch" >> "$LOG"
        preserve_audit_invalid_result
        stop_panel_generation || echo "cannot persist panel hard-stop state" >> "$LOG"
        finish 2;;
      legacy)
        echo "bounded-read audit found violations in a legacy review; result retained as advisory" >> "$LOG";;
    esac
  fi
fi

if [ "$rc" -ne 0 ] || [ ! -s "$OUT" ]; then finish "$(classify_failure)"; fi
finish 0
