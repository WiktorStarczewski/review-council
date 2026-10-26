#!/bin/bash
# codex adapter - run one read-only codex reviewer seat.
#
# Called by rev-seat.sh with the adapter environment contract:
#   SEAT MODEL EFFORT MODE ROOT PROMPT SCHEMA OUT LOG RAW BASE
# Streams the CLI's events to $RAW, one summarised line each to $LOG, leaves findings JSON at $OUT,
# and exits with the CLI's own exit code. Validation, retries and failure classification are the
# wrapper's job - this file is only the invocation and the quirks that come with it.
#
# Quirks that live here:
#   - codex reads stdin until EOF and BLOCKS on an open pipe: the prompt file is its stdin (`- < file`).
#   - `codex exec review` has no -C and no -s, and `--base` cannot be combined with a custom prompt:
#     that seat runs codex's OWN review prompt (that is its value) with only our output schema, from
#     $ROOT, and pins the read-only sandbox through config instead of the missing -s flag.
#   - a non-git root (a read-only panel on a document) needs --skip-git-repo-check.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SUMMARY="$HERE/../lib/stream-summary.py"
STAGES_HELPER="$HERE/../lib/codex-proof-stages.py"
[ -n "${EFFORT:-}" ] || { echo "codex adapter: missing receipted effort" >&2; exit 1; }
INSTRUCTIONS="$(cd "$HERE/../lib" && pwd)/reviewer-instructions.md"
if [ "${MODE:-}" != review ] && { [ ! -f "$INSTRUCTIONS" ] || [ ! -r "$INSTRUCTIONS" ] || [ ! -s "$INSTRUCTIONS" ]; }; then
  echo "codex adapter: missing reviewer instructions" >&2
  exit 1
fi
GITCHECK=""
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || GITCHECK="--skip-git-repo-check"
CODEX_STATE_HOME=${CODEX_HOME:-$HOME/.codex}
HOME_HELPER="$HERE/../lib/isolated-seat-home.py"
PRIVATE_HOME=$(python3 "$HOME_HELPER" path codex "$OUT") || exit 1
LEASE_READY=$(mktemp "${TMPDIR:-/tmp}/review-council-codex-ready.XXXXXX") || exit 1
LEASE_PID=""
STAGE_DIR=""
cleanup_home() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$LEASE_PID" ]; then
    kill -TERM "$LEASE_PID" >/dev/null 2>&1 || true
    wait "$LEASE_PID" >/dev/null 2>&1 || true
  fi
  [ -z "$STAGE_DIR" ] || rm -rf "$STAGE_DIR"
  rm -f "$LEASE_READY"
  return "$status"
}
trap cleanup_home EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
if [ -f "$CODEX_STATE_HOME/auth.json" ]; then
  python3 "$HOME_HELPER" hold codex "$PRIVATE_HOME" --parent "$$" \
    --auth "$CODEX_STATE_HOME/auth.json" > "$LEASE_READY" &
else
  python3 "$HOME_HELPER" hold codex "$PRIVATE_HOME" --parent "$$" > "$LEASE_READY" &
fi
LEASE_PID=$!
while [ ! -s "$LEASE_READY" ] && kill -0 "$LEASE_PID" >/dev/null 2>&1; do sleep 0.02; done
if [ ! -s "$LEASE_READY" ]; then
  wait "$LEASE_PID"; lease_status=$?
  [ "$lease_status" -ne 0 ] || lease_status=1
  exit "$lease_status"
fi

set -o pipefail
if [ "${MODE:-}" = review ]; then
  ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec review --base "$BASE" --ephemeral \
      --ignore-user-config -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
      -c project_doc_max_bytes=0 -c 'sandbox_mode="read-only"' \
      --json --output-schema "$SCHEMA" -o "$OUT" $GITCHECK </dev/null ) 2>>"$LOG" \
    | tee "$RAW" | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
  rc=${PIPESTATUS[0]}
else
  STAGE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/review-council-codex-stages.XXXXXX") || exit 1
  AUDIT_ROOT=$(cd "$ROOT" && pwd -P) || exit 1
  SESSION_DIR=$(cd "$(dirname "$PROMPT")" && pwd -P) || exit 1
  STAGE_COUNT=$(python3 "$STAGES_HELPER" --prompt "$PROMPT" --seat "$SEAT" \
    --model "$MODEL" --stage-dir "$STAGE_DIR") || exit 1
  case "$STAGE_COUNT" in
    ''|*[!0-9]*) echo "codex adapter: invalid proof stage count" >&2; exit 1;;
  esac
  run_codex_turn() {
    local input=$1 schema=${2:-} output=${3:-} rc
    TURN_RAW="$STAGE_DIR/current-turn.ndjson"
    : > "$TURN_RAW"
    if [ -z "$THREAD_ID" ] && [ -n "$schema" ]; then
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec --ignore-user-config \
        -s read-only -C "$ROOT" -m "$MODEL" \
        -c model_reasoning_effort="$EFFORT" -c project_doc_max_bytes=0 \
        -c model_instructions_file="$INSTRUCTIONS" \
        --json --output-schema "$schema" -o "$output" $GITCHECK - < "$input" ) \
        2>>"$LOG" | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$output" >> "$LOG"
    elif [ -z "$THREAD_ID" ]; then
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec --ignore-user-config \
        -s read-only -C "$ROOT" -m "$MODEL" \
        -c model_reasoning_effort="$EFFORT" -c project_doc_max_bytes=0 \
        -c model_instructions_file="$INSTRUCTIONS" \
        --json $GITCHECK - < "$input" ) 2>>"$LOG" \
        | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
    elif [ -n "$schema" ]; then
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec resume \
        --ignore-user-config -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
        -c project_doc_max_bytes=0 -c model_instructions_file="$INSTRUCTIONS" \
        -c 'sandbox_mode="read-only"' --json --output-schema "$schema" \
        -o "$output" $GITCHECK "$THREAD_ID" - < "$input" ) 2>>"$LOG" \
        | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$output" >> "$LOG"
    else
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec resume \
        --ignore-user-config -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
        -c project_doc_max_bytes=0 -c model_instructions_file="$INSTRUCTIONS" \
        -c 'sandbox_mode="read-only"' --json $GITCHECK "$THREAD_ID" - < "$input" ) \
        2>>"$LOG" | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
    fi
    rc=${PIPESTATUS[0]}
    return "$rc"
  }

  THREAD_ID=""
  if [ "$STAGE_COUNT" -gt 0 ]; then
    for ((stage=1; stage<=STAGE_COUNT; stage++)); do
      printf -v stage_name 'stage-%04d.prompt' "$stage"
      STAGE_PROMPT="$STAGE_DIR/$stage_name"
      EXPECTED_STAGE_READS=$(python3 "$STAGES_HELPER" --stage-read-count "$STAGE_PROMPT") || exit 1
      run_codex_turn "$STAGE_PROMPT" || exit $?
      STAGE_STATS=$(python3 "$STAGES_HELPER" --turn-stats "$TURN_RAW" \
        --root "$AUDIT_ROOT" --session "$SESSION_DIR") || exit 1
      IFS=$'\t' read -r STAGE_READS STAGE_BYTES STAGE_EXPANSION_READS <<< "$STAGE_STATS"
      if [ "$STAGE_READS" -ne "$EXPECTED_STAGE_READS" ] \
          || [ "$STAGE_BYTES" -gt 61440 ] || [ "$STAGE_EXPANSION_READS" -ne 0 ]; then
        echo "codex adapter: prepared proof turn omitted reads or exceeded its output budget" >&2
        exit 1
      fi
      if [ "$stage" = 1 ]; then
        THREAD_ID=$(python3 "$STAGES_HELPER" --thread-id-stream "$RAW") || exit 1
      else
        RESUMED_THREAD_ID=$(python3 "$STAGES_HELPER" --thread-id-stream "$RAW") || exit 1
        if [ "$RESUMED_THREAD_ID" != "$THREAD_ID" ]; then
          echo "codex adapter: prepared evidence resumed a different thread" >&2
          exit 1
        fi
      fi
    done
  fi

    cat > "$STAGE_DIR/review-turn.schema.json" <<'EOF'
{"type":"object","required":["status","next_step"],"properties":{"status":{"type":"string","enum":["continue","ready"]},"next_step":{"type":"string"}},"additionalProperties":false}
EOF
    REVIEW_READ_BUDGET=$(python3 "$STAGES_HELPER" --review-budget "$PROMPT") || exit 1
    case "$REVIEW_READ_BUDGET" in
      ''|*[!0-9]*) echo "codex adapter: invalid review read budget" >&2; exit 1;;
    esac
    MAX_REVIEW_TURNS=$((REVIEW_READ_BUDGET + 1))
    REQUIRED_POST_INDEX=$(python3 "$STAGES_HELPER" --required-post-index-read "$PROMPT") || exit 1
    REQUIRED_POST_INDEX_TARGET=$(python3 "$STAGES_HELPER" \
      --required-post-index-target "$PROMPT") || exit 1
    REVIEW_READS=0
    REVIEW_TARGET_READS=0
    REVIEW_READY=0
    NEXT_STEP=""
    for ((review_turn=1; review_turn<=MAX_REVIEW_TURNS; review_turn++)); do
      REVIEW_PROMPT="$STAGE_DIR/review-$review_turn.prompt"
      NO_MORE_READS=0
      if [ "$review_turn" = 1 ]; then
        cat "$PROMPT" > "$REVIEW_PROMPT" || exit 1
        if [ "$STAGE_COUNT" -gt 0 ]; then
          cat >> "$REVIEW_PROMPT" <<'EOF'

All prepared patch chunks, source-context packets, required source segments, and the evidence navigation index listed above have already been read in earlier explicit turns. Do not reread those prepared artifacts. Continue the assigned review using their contents already present in this conversation.
EOF
        else
          cat >> "$REVIEW_PROMPT" <<'EOF'

This is the first explicit review turn; no prepared evidence was read in an earlier turn. Follow the original assignment's read order and source scope.
EOF
        fi
        cat >> "$REVIEW_PROMPT" <<'EOF'

Keep post-index repository investigation within bounded explicit turns. In each turn, use no more than two separate repository read commands and keep their combined output at or below 32 KiB. If more evidence is needed after this turn, return status "continue" with one concrete next evidence question in next_step. If the evidence is sufficient to finish, return status "ready" with an empty next_step. Do not return findings in these bounded turns.
EOF
      elif [ "$REVIEW_READS" -ge "$REVIEW_READ_BUDGET" ]; then
        NO_MORE_READS=1
        {
          cat <<'EOF'
The repository expansion-call budget is exhausted. Do not use tools. Review the evidence and reasoning already in this conversation. Return status "ready" with an empty next_step if you can finish; otherwise return status "continue" and name the unfinished evidence obligation. Do not return findings yet.

Unfinished evidence question:
EOF
          printf '%s\n' "$NEXT_STEP"
        } > "$REVIEW_PROMPT"
      else
        {
          cat <<'EOF'
Continue the same assigned review using the prepared evidence and prior review reasoning in this conversation. Do not reread prepared artifacts. Keep this explicit turn to at most two separate repository read commands and at most 32 KiB combined output. If more evidence is needed, return status "continue" and one concrete next evidence question in next_step. If ready to finish, return status "ready" with an empty next_step. Do not return findings yet.

Next evidence question:
EOF
          printf '%s\n' "$NEXT_STEP"
        } > "$REVIEW_PROMPT"
      fi
      TURN_OUT="$STAGE_DIR/review-turn.json"
      rm -f "$TURN_OUT"
      run_codex_turn "$REVIEW_PROMPT" "$STAGE_DIR/review-turn.schema.json" \
        "$TURN_OUT" || exit $?
      RESUMED_THREAD_ID=$(python3 "$STAGES_HELPER" --thread-id-stream "$RAW") || exit 1
      if [ -z "$THREAD_ID" ]; then
        THREAD_ID=$RESUMED_THREAD_ID
      elif [ "$RESUMED_THREAD_ID" != "$THREAD_ID" ]; then
        echo "codex adapter: source review resumed a different thread" >&2
        exit 1
      fi
      TURN_STATS=$(python3 "$STAGES_HELPER" --turn-stats "$TURN_RAW" \
        --root "$AUDIT_ROOT" --session "$SESSION_DIR") || exit 1
      IFS=$'\t' read -r TURN_CALLS TURN_BYTES TURN_READS <<< "$TURN_STATS"
      case "$TURN_CALLS:$TURN_BYTES:$TURN_READS" in
        *[!0-9:]*|:*) echo "codex adapter: invalid review turn metrics" >&2; exit 1;;
      esac
      if [ "$TURN_CALLS" -gt 2 ] || [ "$TURN_BYTES" -gt 32768 ] \
          || [ "$((REVIEW_READS + TURN_READS))" -gt "$REVIEW_READ_BUDGET" ] \
          || { [ "$NO_MORE_READS" = 1 ] && [ "$TURN_CALLS" -ne 0 ]; }; then
        echo "codex adapter: review turn exceeded its read or output budget" >&2
        exit 1
      fi
      REVIEW_READS=$((REVIEW_READS + TURN_READS))
      REVIEW_STATE=$(python3 "$STAGES_HELPER" --review-status "$TURN_OUT") || exit 1
      case "$REVIEW_STATE" in
        ready)
          if [ "$REQUIRED_POST_INDEX" = 1 ]; then
            REVIEW_TARGET_PROOF=$(python3 "$STAGES_HELPER" \
              --post-index-target-read-count "$RAW" --prompt "$PROMPT" \
              --root "$AUDIT_ROOT" --session "$SESSION_DIR") || exit 1
            IFS=$'\t' read -r REVIEW_TARGET_READS REVIEW_INDEX_READS \
              <<< "$REVIEW_TARGET_PROOF"
            case "$REVIEW_TARGET_READS:$REVIEW_INDEX_READS" in
              ''|*[!0-9:]*|:*|*:) echo "codex adapter: invalid post-index source proof state" >&2; exit 1;;
            esac
          fi
          if [ "$REQUIRED_POST_INDEX" = 1 ] && [ "$REVIEW_TARGET_READS" -eq 0 ]; then
            if [ "$REVIEW_INDEX_READS" -eq 0 ]; then
              NEXT_STEP="Read the complete evidence navigation index named in the original assignment, then read the exact required original-source target $REQUIRED_POST_INDEX_TARGET in a later turn before finalizing."
            else
              NEXT_STEP="Read the exact required original-source target $REQUIRED_POST_INDEX_TARGET in a later explicit turn before finalizing."
            fi
          else
            REVIEW_READY=1
            break
          fi
          ;;
        continue$'\t'*) NEXT_STEP=${REVIEW_STATE#continue$'\t'};;
        *) echo "codex adapter: invalid bounded review state" >&2; exit 1;;
      esac
      if [ "$review_turn" -ge "$MAX_REVIEW_TURNS" ] || [ "$NO_MORE_READS" = 1 ]; then
        break
      fi
    done
    FINAL_PROMPT="$STAGE_DIR/final-review.prompt"
    if [ "$REVIEW_READY" = 1 ]; then
      cat > "$FINAL_PROMPT" <<'EOF'
Return the final findings JSON for the review completed in this conversation. Follow the original assignment, findings schema, and severity rules. Do not use tools or reread prepared evidence.
EOF
    else
      {
        cat <<'EOF'
Finalize the review now. The bounded post-index review turns or repository read budget are exhausted. Do not use tools or reread prepared evidence. If evidence is insufficient to finish any required check, return an empty findings array and a summary beginning `INCOMPLETE PROOF:` that names the unfinished obligations.

Last evidence question:
EOF
        printf '%s\n' "$NEXT_STEP"
      } > "$FINAL_PROMPT"
    fi
    run_codex_turn "$FINAL_PROMPT" "$SCHEMA" "$OUT" || exit $?
    RESUMED_THREAD_ID=$(python3 "$STAGES_HELPER" --thread-id-stream "$RAW") || exit 1
    if [ "$RESUMED_THREAD_ID" != "$THREAD_ID" ]; then
      echo "codex adapter: findings resumed a different thread" >&2
      exit 1
    fi
    FINAL_TURN_STATS=$(python3 "$STAGES_HELPER" --turn-stats "$TURN_RAW" \
      --root "$AUDIT_ROOT" --session "$SESSION_DIR") || exit 1
    IFS=$'\t' read -r FINAL_TURN_CALLS FINAL_TURN_BYTES FINAL_TURN_READS <<< "$FINAL_TURN_STATS"
    if [ "$FINAL_TURN_CALLS" -ne 0 ] || [ "$FINAL_TURN_BYTES" -ne 0 ] \
        || [ "$FINAL_TURN_READS" -ne 0 ]; then
      echo "codex adapter: final findings turn used repository tools" >&2
      exit 1
    fi
    rc=0
fi
exit "$rc"
