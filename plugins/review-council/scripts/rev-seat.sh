#!/bin/bash
# rev-seat.sh <seat> <session-dir> <round> <prompt-file> [--effort <e>] [--base <ref>]
#
# Launch ONE read-only reviewer seat and leave schema-valid findings at <session>/r<N>-<seat>.json.
# The seat set is not hardcoded: <session>/roster.json (written by rev-preflight.sh) says which adapter,
# model, effort and mode this seat has, and scripts/seats.d/<adapter>.sh owns the CLI invocation.
# The `agent` adapter (the Opus seat) is launched by the skill through the Agent tool, not here.
# Also writes r<N>-<seat>.log (one summarised line per event), .stream.ndjson (raw), .exit (code).
# Exit: 0 valid JSON | 2 missing/invalid JSON | 3 not signed in | 4 usage cap or rate limit | 1 other
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
[ "$ADAPTER" != agent ] || { echo "rev-seat: seat '$SEAT' is the Agent tool seat - the skill launches it, rev-seat.sh cannot" >&2; exit 1; }
ADAPTER_SH="$HERE/seats.d/$ADAPTER.sh"
[ -x "$ADAPTER_SH" ] || { echo "rev-seat: no adapter script for '$ADAPTER' (seat '$SEAT')" >&2; exit 1; }

# Effort precedence: --effort, then the per-CLI env override, then the roster's entry for this seat
# (the roster read the models cache, so this script never guesses a level the model does not offer).
case "$ADAPTER" in
  codex) ENV_EFFORT=${REV_CODEX_EFFORT:-};;
  grok)  ENV_EFFORT=${REV_GROK_EFFORT:-};;
  *)     ENV_EFFORT="";;
esac
EFFORT=${EFFORT:-${ENV_EFFORT:-$ROSTER_EFFORT}}
[ "$MODE" != review ] || [ -n "$BASE" ] || { echo "rev-seat: seat '$SEAT' (mode=review) needs --base <ref>" >&2; exit 1; }

mkdir -p "$SESSION"
ROOT=${REV_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
BASEN="$SESSION/r${ROUND}-${SEAT}"
OUT="$BASEN.json"; LOG="$BASEN.log"; RAW="$BASEN.stream.ndjson"; EXITF="$BASEN.exit"
AUDITF="$BASEN.read-audit.json"
rm -f "$OUT" "$EXITF" "$AUDITF"; : > "$LOG"
export REV_ACTIVE=1
export SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE

finish() {  # <code> - validate on 0, record, print the one-line summary, exit
  local code=$1 n="-"
  if [ "$code" = 0 ]; then n=$(python3 "$VALIDATE" "$OUT" 2>>"$LOG") || { code=2; n="-"; }; fi
  echo "$code" > "$EXITF"
  echo "seat=$SEAT round=$ROUND exit=$code findings=$n"
  exit "$code"
}
classify_failure() {  # after a non-zero rc or missing output: 3 auth, 4 cap, 2 no output, 1 other
  # Classify from CLI-ORIGINATED lines only. The model's own words reach the log as `text: …` and $RAW is
  # nothing but the model stream, so a review whose findings quote "401", "unauthorized" or "rate limit"
  # from the code under review would otherwise stop the whole run (exit 3) or drop the seat (exit 4).
  # The CLIs report their own failures as `error: …` lines (codex) or on stderr (grok, gemini), which stay.
  local cli; cli=$(grep -v -E '^(text|exec|done): |^tool_call ' "$LOG" 2>/dev/null)
  if printf '%s\n' "$cli" | grep -qiE "not logged in|login required|please (log|sign) in|run (codex|grok) login|to log in|auth method|[^0-9]401[^0-9]|unauthori[sz]ed"; then echo 3
  elif printf '%s\n' "$cli" | grep -qiE "usage limit|rate limit|too many requests|[^0-9]429[^0-9]|quota exceeded"; then echo 4
  elif [ ! -s "$OUT" ]; then echo 2
  else echo 1; fi
}
archive_raw() {
  [ -s "$RAW" ] || return 0
  local n=1 archived
  while :; do
    archived="${RAW%.ndjson}.attempt${n}.ndjson"
    [ -e "$archived" ] || break
    n=$((n+1))
  done
  mv "$RAW" "$archived"
}
has_tool_call() {
  case "$ADAPTER" in
    codex) grep -q '^exec: ' "$LOG";;
    *) grep -q '^tool_call ' "$LOG";;
  esac
}

# Under a schema (grok) or a "answer with only JSON" instruction (gemini) a model sometimes answers on turn
# one WITHOUT reading anything, even when the prompt says to run tools first (seen live: summary "I'll
# inspect the diff…", zero findings, zero tool calls). An answer with no tool calls is not a review: retry
# once at the same effort, then fail the seat so the orchestrator's retry/skip rule applies.
attempt=0
while :; do
  attempt=$((attempt+1))
  archive_raw || { echo "cannot archive prior stream before attempt $attempt" >> "$LOG"; finish 1; }
  "$ADAPTER_SH"; rc=$?
  case "$ADAPTER" in
    codex|grok|gemini|claude)
      if [ "$rc" -eq 0 ] && ! has_tool_call; then
        echo "$ADAPTER answered without a single tool call (attempt $attempt) - not a review" >> "$LOG"
        rm -f "$OUT"
        if [ "$attempt" -lt 2 ]; then continue; fi
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
  if [ "$AUDIT_RC" -ne 0 ]; then
    if grep -q '^Evidence manifest SHA-256: [0-9a-f]\{64\}$' "$PROMPT"; then
      if grep -qx 'Assigned scope: full' "$PROMPT"; then
        echo "bounded-read audit rejected full-scope evidence review; rerun this full-scope seat after correcting its evidence reads" >> "$LOG"
      else
        echo "bounded-read audit rejected narrowed review; rerun the whole panel at full scope" >> "$LOG"
      fi
      rm -f "$OUT"
      finish 2
    else
      echo "bounded-read audit found violations in a legacy review; result retained as advisory" >> "$LOG"
    fi
  fi
fi

if [ "$rc" -ne 0 ] || [ ! -s "$OUT" ]; then finish "$(classify_failure)"; fi
finish 0
