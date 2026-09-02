#!/bin/bash
# rev-seat.sh <seat> <session-dir> <round> <prompt-file> [--effort <e>] [--base <ref>]
#
# Launch ONE read-only reviewer seat and leave schema-valid findings at <session>/r<N>-<seat>.json.
# Seats: codex-sol codex-terra grok codex-review grok-code-review   (opus runs via the Agent tool, not here)
# Also writes r<N>-<seat>.log (one summarised line per event), .stream.ndjson (raw), .exit (code).
# Exit: 0 valid JSON | 2 missing/invalid JSON | 3 not signed in | 4 usage cap or rate limit | 1 other
#
# The CLI quirks live here and nowhere else:
#   - codex reads stdin until EOF and BLOCKS on an open pipe: the prompt file is its stdin (`- < file`).
#   - grok answers on turn one under --json-schema unless the prompt says to run tools first (rev-prompt.sh does).
#   - grok's structured output is only in the final {"type":"end"} record of the stream.
#   - grok: `--prompt-file` alone is single-turn headless; `-p` REQUIRES an inline prompt value, so `-p --prompt-file` is a usage error.
#   - NEVER edit this file in place while seats are running: bash reads scripts lazily and a rewritten inode corrupts
#     the in-flight run (seen: `--max-turns: command not found`). Write to a temp file and `mv` over it instead.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SCHEMA="$HERE/../schema/findings.schema.json"
VALIDATE="$HERE/lib/validate-findings.py"
SUMMARY="$HERE/lib/stream-summary.py"
usage() { echo "usage: rev-seat.sh <codex-sol|codex-terra|grok|codex-review|grok-code-review> <session-dir> <round> <prompt-file> [--effort e] [--base ref]" >&2; exit 1; }
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
case "$SEAT" in codex-sol|codex-terra|grok|codex-review|grok-code-review) ;; *) echo "rev-seat: unknown seat '$SEAT'" >&2; usage;; esac
mkdir -p "$SESSION"
ROOT=${REV_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
BASEN="$SESSION/r${ROUND}-${SEAT}"
OUT="$BASEN.json"; LOG="$BASEN.log"; RAW="$BASEN.stream.ndjson"; EXITF="$BASEN.exit"
rm -f "$OUT" "$EXITF"; : > "$LOG"
export REV_ACTIVE=1

finish() {  # <code> — validate on 0, record, print the one-line summary, exit
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
  # The CLIs report their own failures as `error: …` lines (codex) or on stderr (grok), which stay.
  local cli; cli=$(grep -v -E '^(text|exec|done): ' "$LOG" 2>/dev/null)
  if printf '%s\n' "$cli" | grep -qiE "not logged in|login required|please (log|sign) in|run (codex|grok) login|[^0-9]401[^0-9]|unauthori[sz]ed"; then echo 3
  elif printf '%s\n' "$cli" | grep -qiE "usage limit|rate limit|too many requests|[^0-9]429[^0-9]|quota exceeded"; then echo 4
  elif [ ! -s "$OUT" ]; then echo 2
  else echo 1; fi
}

GITCHECK=""
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || GITCHECK="--skip-git-repo-check"

case "$SEAT" in
  codex-sol|codex-terra|codex-review)
    case "$SEAT" in
      codex-sol)    MODEL=gpt-5.6-sol;;
      codex-terra)  MODEL=gpt-5.6-terra;;
      codex-review) MODEL=${REV_CODEX_REVIEW_MODEL:-gpt-5.6-sol};;
    esac
    if [ -z "$EFFORT" ] && [ -z "${REV_CODEX_EFFORT:-}" ]; then
      # Ladder is max → xhigh → high, but a model that does not offer `max` must not be asked for it:
      # take the highest level the models cache actually lists for this slug (fall back to max if unreadable).
      EFFORT=$(REV_CODEX_MODELS_CACHE="${REV_CODEX_MODELS_CACHE:-$HOME/.codex/models_cache.json}" REV_SLUG="$MODEL" python3 - <<'PY'
import json, os
try:
    with open(os.environ['REV_CODEX_MODELS_CACHE']) as f: d = json.load(f)
except Exception:
    d = {}
lv = []
if isinstance(d, dict):
    for m in d.get('models') or []:
        if isinstance(m, dict) and m.get('slug') == os.environ['REV_SLUG']:
            lv = [l.get('effort') for l in (m.get('supported_reasoning_levels') or []) if isinstance(l, dict)]
print(next((e for e in ('max', 'xhigh', 'high') if e in lv), 'max'))
PY
)
    fi
    EFFORT=${EFFORT:-${REV_CODEX_EFFORT:-max}}
    set -o pipefail
    if [ "$SEAT" = codex-review ]; then
      [ -n "$BASE" ] || { echo "rev-seat: codex-review needs --base <ref>" >&2; exit 1; }
      # `codex exec review` has no -C and no -s (read-only by construction), and `--base` cannot be combined with a
      # custom [PROMPT] at all: this seat runs codex's OWN review prompt (that is its value — a prompt we did not
      # write) and only our output schema. The rendered prompt file is kept beside it for the record, unused.
      # `exec review` has no -s, so the sandbox is pinned through config instead: a reviewer never writes.
      ( cd "$ROOT" && codex exec review --base "$BASE" --ephemeral -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
          -c 'sandbox_mode="read-only"' \
          --json --output-schema "$SCHEMA" -o "$OUT" $GITCHECK </dev/null ) 2>>"$LOG" \
        | tee "$RAW" | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
    else
      codex exec --ephemeral -s read-only -C "$ROOT" -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
          --json --output-schema "$SCHEMA" -o "$OUT" $GITCHECK - < "$PROMPT" 2>>"$LOG" \
        | tee "$RAW" | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
    fi
    rc=${PIPESTATUS[0]}
    if [ "$SEAT" = codex-review ] && [ -s "$OUT" ] && ! python3 "$VALIDATE" "$OUT" >/dev/null 2>&1; then
      # `codex exec review` ignores --output-schema and answers in prose; keep the prose and convert it.
      cp "$OUT" "$BASEN.native.txt"
      python3 "$HERE/lib/codex-review-to-findings.py" "$BASEN.native.txt" "$OUT" --root "$ROOT" >>"$LOG" 2>&1 || true
    fi
    ;;
  grok|grok-code-review)
    EFFORT=${EFFORT:-${REV_GROK_EFFORT:-xhigh}}
    P="$PROMPT"
    if [ "$SEAT" = grok-code-review ]; then
      # NEVER $BASEN.prompt.md: that is the path rev-prompt.sh renders to, so > would truncate
      # the file cat is reading and spin forever. A distinct name is also idempotent on a retry.
      P="$BASEN.cr-prompt.md"; { printf '/code-review\n\n'; cat "$PROMPT"; } > "$P"
    fi
    set -o pipefail
    # Under --json-schema grok sometimes answers on turn one WITHOUT reading anything, even when the prompt says
    # to run tools first (seen live: summary "I'll inspect the diff…", zero findings, zero tool calls). An answer
    # with no tool calls is not a review: retry once at the same effort, then fail the seat so the orchestrator's
    # retry/skip rule applies.
    attempt=0
    while :; do
      attempt=$((attempt+1))
      grok --prompt-file "$P" --cwd "$ROOT" -m "${REV_GROK_MODEL:-grok-4.6}" --reasoning-effort "$EFFORT" \
          --permission-mode plan --output-format streaming-json --json-schema "$(cat "$SCHEMA")" \
          --max-turns "${REV_GROK_MAX_TURNS:-120}" </dev/null 2>>"$LOG" \
        | tee "$RAW" | python3 -u "$SUMMARY" grok "$OUT" >> "$LOG"
      rc=${PIPESTATUS[0]}
      if [ "$rc" -eq 0 ] && ! grep -q '^tool_call ' "$LOG"; then
        echo "grok answered without a single tool call (attempt $attempt) — not a review" >> "$LOG"
        rm -f "$OUT"
        [ "$attempt" -lt 2 ] && continue
        rc=1
      fi
      break
    done
    ;;
esac

if [ "$rc" -ne 0 ] || [ ! -s "$OUT" ]; then finish "$(classify_failure)"; fi
finish 0
