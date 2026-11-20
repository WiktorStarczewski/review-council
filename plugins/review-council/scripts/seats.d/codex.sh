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
# rev-seat.sh keeps this script's stderr out of the seat log, so a refusal names itself in both.
adapter_fail() {
  printf 'codex adapter: %s\n' "$1" >> "${LOG:-/dev/null}"
  printf 'codex adapter: %s\n' "$1" >&2
  exit 1
}
SUMMARY="$HERE/../lib/stream-summary.py"
STAGES_HELPER="$HERE/../lib/codex-proof-stages.py"
[ -n "${EFFORT:-}" ] || adapter_fail "missing receipted effort"
INSTRUCTIONS="$(cd "$HERE/../lib" && pwd)/reviewer-instructions.md"
if [ "${MODE:-}" != review ] && { [ ! -f "$INSTRUCTIONS" ] || [ ! -r "$INSTRUCTIONS" ] || [ ! -s "$INSTRUCTIONS" ]; }; then
  adapter_fail "missing reviewer instructions"
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
  stage_helper() {
    local status
    python3 "$STAGES_HELPER" "$@" 2> "$STAGE_DIR/helper.err"; status=$?
    if [ -s "$STAGE_DIR/helper.err" ]; then
      cat "$STAGE_DIR/helper.err" >&2
      cat "$STAGE_DIR/helper.err" >> "$LOG"
    fi
    return "$status"
  }
  AUDIT_ROOT=$(cd "$ROOT" && pwd -P) || exit 1
  SESSION_DIR=$(cd "$(dirname "$PROMPT")" && pwd -P) || exit 1
  STAGE_COUNT=$(stage_helper --prompt "$PROMPT" --seat "$SEAT" \
    --model "$MODEL" --stage-dir "$STAGE_DIR") || exit 1
  case "$STAGE_COUNT" in
    ''|*[!0-9]*) adapter_fail "invalid proof stage count";;
  esac
  # Codex compacts an overflowing thread silently and the stream audit cannot see evidence it
  # dropped, so a seat that cannot hold its evidence refuses before any paid call.
  CAPACITY=$(stage_helper --capacity "$STAGE_DIR" --prompt "$PROMPT" --model "$MODEL") || exit 1
  IFS=$'\t' read -r CAPACITY_VERDICT CAPACITY_DETAIL CAPACITY_LIMIT CAPACITY_WINDOW <<< "$CAPACITY"
  WINDOW_ARGS=()
  case "$CAPACITY_VERDICT" in
    fits) ;;
    raise)
      case "$CAPACITY_DETAIL:$CAPACITY_LIMIT:$CAPACITY_WINDOW" in
        *[!0-9:]*|:*|*::*|*:) adapter_fail "invalid raised context window";;
      esac
      WINDOW_ARGS=(-c "model_context_window=$CAPACITY_WINDOW")
      printf 'codex adapter: running %s at its %s-token maximum context window: the assignment needs ~%s tokens before review, within %s\n' \
        "$MODEL" "$CAPACITY_WINDOW" "$CAPACITY_DETAIL" "$CAPACITY_LIMIT" >> "$LOG";;
    over) adapter_fail "$CAPACITY_DETAIL";;
    unknown) printf 'codex adapter: context capacity unknown (%s)\n' "$CAPACITY_DETAIL" >> "$LOG";;
    *) adapter_fail "invalid context capacity verdict";;
  esac
  run_codex_turn() {
    local input=$1 schema=${2:-} output=${3:-} rc
    TURN_RAW="$STAGE_DIR/current-turn.ndjson"
    : > "$TURN_RAW"
    if [ -z "$THREAD_ID" ] && [ -n "$schema" ]; then
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec --ignore-user-config \
        -s read-only -C "$ROOT" -m "$MODEL" \
        -c model_reasoning_effort="$EFFORT" -c project_doc_max_bytes=0 \
        -c model_instructions_file="$INSTRUCTIONS" ${WINDOW_ARGS[@]+"${WINDOW_ARGS[@]}"} \
        --json --output-schema "$schema" -o "$output" $GITCHECK - < "$input" ) \
        2>>"$LOG" | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$output" >> "$LOG"
    elif [ -z "$THREAD_ID" ]; then
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec --ignore-user-config \
        -s read-only -C "$ROOT" -m "$MODEL" \
        -c model_reasoning_effort="$EFFORT" -c project_doc_max_bytes=0 \
        -c model_instructions_file="$INSTRUCTIONS" ${WINDOW_ARGS[@]+"${WINDOW_ARGS[@]}"} \
        --json $GITCHECK - < "$input" ) 2>>"$LOG" \
        | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
    elif [ -n "$schema" ]; then
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec resume \
        --ignore-user-config -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
        -c project_doc_max_bytes=0 -c model_instructions_file="$INSTRUCTIONS" \
        ${WINDOW_ARGS[@]+"${WINDOW_ARGS[@]}"} \
        -c 'sandbox_mode="read-only"' --json --output-schema "$schema" \
        -o "$output" $GITCHECK "$THREAD_ID" - < "$input" ) 2>>"$LOG" \
        | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$output" >> "$LOG"
    else
      ( cd "$ROOT" && CODEX_HOME="$PRIVATE_HOME" codex exec resume \
        --ignore-user-config -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
        -c project_doc_max_bytes=0 -c model_instructions_file="$INSTRUCTIONS" \
        ${WINDOW_ARGS[@]+"${WINDOW_ARGS[@]}"} \
        -c 'sandbox_mode="read-only"' --json $GITCHECK "$THREAD_ID" - < "$input" ) \
        2>>"$LOG" | tee "$TURN_RAW" | tee -a "$RAW" \
        | python3 -u "$SUMMARY" codex "$OUT" >> "$LOG"
    fi
    rc=${PIPESTATUS[0]}
    return "$rc"
  }

  THREAD_ID=""
  if [ "$STAGE_COUNT" -gt 0 ]; then
    # The helper judges each prepared-evidence turn by the read audit's own replay and names the
    # next turn: the next stage, a bounded repair of a read the audit has not credited, or a refusal.
    STEP_ARGS=(--stage-step "$STAGE_DIR" --raw "$RAW" --turn "$STAGE_DIR/current-turn.ndjson"
      --prompt "$PROMPT" --seat "$SEAT" --root "$AUDIT_ROOT" --session "$SESSION_DIR")
    [ -z "${REV_DEPS_DIR:-}" ] || STEP_ARGS+=(--deps "$REV_DEPS_DIR")
    while :; do
      STAGE_STEP=$(stage_helper "${STEP_ARGS[@]}") || exit 1
      IFS=$'\t' read -r STEP_ACTION STEP_PROMPT STEP_NOTE <<< "$STAGE_STEP"
      case "$STEP_ACTION" in
        done) break;;
        run) [ -n "$STEP_PROMPT" ] || adapter_fail "invalid prepared evidence step";;
        refuse) adapter_fail "${STEP_PROMPT:-prepared evidence step refused}";;
        *) adapter_fail "invalid prepared evidence step";;
      esac
      [ -z "$STEP_NOTE" ] || printf 'codex adapter: %s\n' "$STEP_NOTE" >> "$LOG"
      run_codex_turn "$STEP_PROMPT" || exit $?
      RESUMED_THREAD_ID=$(stage_helper --thread-id-stream "$RAW") || exit 1
      if [ -z "$THREAD_ID" ]; then
        THREAD_ID=$RESUMED_THREAD_ID
      elif [ "$RESUMED_THREAD_ID" != "$THREAD_ID" ]; then
        adapter_fail "prepared evidence resumed a different thread"
      fi
    done
  fi

    cat > "$STAGE_DIR/review-turn.schema.json" <<'EOF'
{"type":"object","required":["status","next_step"],"properties":{"status":{"type":"string","enum":["continue","ready"]},"next_step":{"type":"string"}},"additionalProperties":false}
EOF
    REVIEW_READ_BUDGET=$(stage_helper --review-budget "$PROMPT") || exit 1
    case "$REVIEW_READ_BUDGET" in
      ''|*[!0-9]*) adapter_fail "invalid review read budget";;
    esac
    REVIEW_TURN_CALL_LIMIT=$(stage_helper \
      --review-turn-call-limit "$MODEL") || exit 1
    case "$REVIEW_TURN_CALL_LIMIT" in
      ''|*[!0-9]*) adapter_fail "invalid review turn call limit";;
    esac
    MAX_REVIEW_TURNS=$((REVIEW_READ_BUDGET + 1))
    REQUIRED_POST_INDEX=$(stage_helper --required-post-index-read "$PROMPT") || exit 1
    REQUIRED_POST_INDEX_TARGET=$(stage_helper \
      --required-post-index-target "$PROMPT") || exit 1
    REFUSAL_ARGS=(--prompt "$PROMPT" --root "$AUDIT_ROOT" --session "$SESSION_DIR")
    [ -z "${REV_DEPS_DIR:-}" ] || REFUSAL_ARGS+=(--deps "$REV_DEPS_DIR")
    # Luna seats most often overshot the call cap by exactly one, so a cap above two plans one less.
    REVIEW_TURN_PLAN=$REVIEW_TURN_CALL_LIMIT
    [ "$REVIEW_TURN_CALL_LIMIT" -le 2 ] || REVIEW_TURN_PLAN=$((REVIEW_TURN_CALL_LIMIT - 1))
    TURN_COUNT_RULE="Every command counts toward that limit, searches as well as reads: plan at most ${REVIEW_TURN_PLAN} and return continue once you have run them."
    TURN_COMMAND_RULE='Run no `node`, `python3`, `yarn`, `npm`, `npx` or other test runner in these turns: one command the read-only policy refuses makes the read audit reject the whole review. Keep the space in every result limiter, as in `| head -80`.'
    REVIEW_READS=0
    REVIEW_TARGET_READS=0
    REVIEW_READY=0
    NEXT_STEP=""
    for ((review_turn=1; review_turn<=MAX_REVIEW_TURNS; review_turn++)); do
      REVIEW_PROMPT="$STAGE_DIR/review-$review_turn.prompt"
      NO_MORE_READS=0
      READS_USED="Of that allowance, ${REVIEW_READS} of ${REVIEW_READ_BUDGET} repository tool calls are used and $((REVIEW_READ_BUDGET - REVIEW_READS)) remain."
      if [ "$review_turn" -gt 1 ]; then
        KIB_TENTHS=$(((TURN_BYTES * 10 + 1023) / 1024))
        LAST_TURN="The previous turn ran ${TURN_CALLS} of its ${REVIEW_TURN_CALL_LIMIT} allowed command_execution calls and returned $((KIB_TENTHS / 10)).$((KIB_TENTHS % 10)) KiB of its 32 KiB."
      fi
      if [ "$review_turn" = 1 ]; then
        printf '%s\n\n' "This review runs in bounded explicit turns. The turn rules after the assignment below govern how you spend its repository-call allowance and what each turn returns: at most ${REVIEW_TURN_CALL_LIMIT} command_execution calls per turn, searches included, and a status JSON instead of findings until a later prompt asks for them." \
          > "$REVIEW_PROMPT"
        stage_helper --compact-prompt "$PROMPT" >> "$REVIEW_PROMPT" || exit 1
        if [ "$STAGE_COUNT" -gt 0 ]; then
          cat >> "$REVIEW_PROMPT" <<'EOF'

All prepared patch chunks, source-context packets, required source segments, and the evidence navigation index listed above have already been read in earlier explicit turns. Do not reread those prepared artifacts. Continue the assigned review using their contents already present in this conversation.
EOF
        else
          cat >> "$REVIEW_PROMPT" <<'EOF'

This is the first explicit review turn; no prepared evidence was read in an earlier turn. Follow the original assignment's read order and source scope.
EOF
        fi
        cat >> "$REVIEW_PROMPT" <<EOF

Keep post-index repository investigation within bounded explicit turns. Each explicit turn permits at most ${REVIEW_TURN_CALL_LIMIT} command_execution calls total, of any kind, and no more than 32 KiB of combined output. ${TURN_COUNT_RULE} Use at most two source reads per investigation turn and target at most 12 KiB per read. Return continue before reading additional ranges. ${TURN_COMMAND_RULE} The assignment's aggregate in-scope repository-read allowance applies across the full review and all explicit turns; it does not reset at a turn boundary. ${READS_USED} If more evidence is needed after this turn, return status "continue" with one concrete next evidence question in next_step. If the evidence is sufficient to finish, return status "ready" with an empty next_step. Do not return findings in these bounded turns.
EOF
      elif [ "$REVIEW_READS" -ge "$REVIEW_READ_BUDGET" ]; then
        NO_MORE_READS=1
        {
          printf '%s ' "$LAST_TURN" "All ${REVIEW_READ_BUDGET} repository tool calls are used."
          cat <<'EOF'
The assignment's aggregate in-scope repository-read allowance is exhausted across all explicit turns. Do not use tools. Review the evidence and reasoning already in this conversation. Return status "ready" with an empty next_step if you can finish; otherwise return status "continue" and name the unfinished evidence obligation. Do not return findings yet.

Unfinished evidence question:
EOF
          printf '%s\n' "$NEXT_STEP"
        } > "$REVIEW_PROMPT"
      else
        {
          cat <<EOF
Continue the same assigned review using the prepared evidence and prior review reasoning in this conversation. Do not reread prepared artifacts. This explicit turn permits at most ${REVIEW_TURN_CALL_LIMIT} command_execution calls total, of any kind, and at most 32 KiB of combined output. ${TURN_COUNT_RULE} Use at most two source reads per investigation turn and target at most 12 KiB per read. Return continue before reading additional ranges. ${TURN_COMMAND_RULE} The assignment's aggregate in-scope repository-read allowance applies across the full review and all explicit turns; it does not reset at a turn boundary. ${READS_USED} ${LAST_TURN} If more evidence is needed, return status "continue" and one concrete next evidence question in next_step. If ready to finish, return status "ready" with an empty next_step. Do not return findings yet.

Next evidence question:
EOF
          printf '%s\n' "$NEXT_STEP"
        } > "$REVIEW_PROMPT"
      fi
      TURN_OUT="$STAGE_DIR/review-turn.json"
      rm -f "$TURN_OUT"
      run_codex_turn "$REVIEW_PROMPT" "$STAGE_DIR/review-turn.schema.json" \
        "$TURN_OUT" || exit $?
      RESUMED_THREAD_ID=$(stage_helper --thread-id-stream "$RAW") || exit 1
      if [ -z "$THREAD_ID" ]; then
        THREAD_ID=$RESUMED_THREAD_ID
      elif [ "$RESUMED_THREAD_ID" != "$THREAD_ID" ]; then
        adapter_fail "source review resumed a different thread"
      fi
      TURN_STATS=$(stage_helper --turn-stats "$TURN_RAW" \
        --root "$AUDIT_ROOT" --session "$SESSION_DIR") || exit 1
      IFS=$'\t' read -r TURN_CALLS TURN_BYTES TURN_READS <<< "$TURN_STATS"
      case "$TURN_CALLS:$TURN_BYTES:$TURN_READS" in
        *[!0-9:]*|:*) adapter_fail "invalid review turn metrics";;
      esac
      # A command the read audit rejects fails the stream whatever the seat reads next.
      TURN_REFUSAL=$(stage_helper --turn-refusal "$TURN_RAW" "${REFUSAL_ARGS[@]}") || exit 1
      if [ -n "$TURN_REFUSAL" ]; then
        adapter_fail "review turn ran a command the read audit rejects ($TURN_REFUSAL)"
      fi
      if [ "$TURN_CALLS" -gt "$REVIEW_TURN_CALL_LIMIT" ]; then
        adapter_fail "review turn exceeded its command-call budget"
      fi
      if [ "$TURN_BYTES" -gt 32768 ] \
          || [ "$((REVIEW_READS + TURN_READS))" -gt "$REVIEW_READ_BUDGET" ] \
          || { [ "$NO_MORE_READS" = 1 ] && [ "$TURN_CALLS" -ne 0 ]; }; then
        adapter_fail "review turn exceeded its read or output budget"
      fi
      REVIEW_READS=$((REVIEW_READS + TURN_READS))
      REVIEW_STATE=$(stage_helper --review-status "$TURN_OUT") || exit 1
      case "$REVIEW_STATE" in
        ready)
          if [ "$REQUIRED_POST_INDEX" = 1 ]; then
            REVIEW_TARGET_PROOF=$(stage_helper \
              --post-index-target-read-count "$RAW" --prompt "$PROMPT" \
              --root "$AUDIT_ROOT" --session "$SESSION_DIR") || exit 1
            IFS=$'\t' read -r REVIEW_TARGET_READS REVIEW_INDEX_READS \
              <<< "$REVIEW_TARGET_PROOF"
            case "$REVIEW_TARGET_READS:$REVIEW_INDEX_READS" in
              ''|*[!0-9:]*|:*|*:) adapter_fail "invalid post-index source proof state";;
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
        *) adapter_fail "invalid bounded review state";;
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
Finalize the review now. The bounded post-index turn limit or assignment-wide repository-read allowance is exhausted. Do not use tools or reread prepared evidence. If evidence is insufficient to finish any required check, return an empty findings array and a summary beginning `INCOMPLETE PROOF:` that names the unfinished obligations.

Last evidence question:
EOF
        printf '%s\n' "$NEXT_STEP"
      } > "$FINAL_PROMPT"
    fi
    run_codex_turn "$FINAL_PROMPT" "$SCHEMA" "$OUT" || exit $?
    RESUMED_THREAD_ID=$(stage_helper --thread-id-stream "$RAW") || exit 1
    if [ "$RESUMED_THREAD_ID" != "$THREAD_ID" ]; then
      adapter_fail "findings resumed a different thread"
    fi
    FINAL_TURN_STATS=$(stage_helper --turn-stats "$TURN_RAW" \
      --root "$AUDIT_ROOT" --session "$SESSION_DIR") || exit 1
    IFS=$'\t' read -r FINAL_TURN_CALLS FINAL_TURN_BYTES FINAL_TURN_READS <<< "$FINAL_TURN_STATS"
    if [ "$FINAL_TURN_CALLS" -ne 0 ] || [ "$FINAL_TURN_BYTES" -ne 0 ] \
        || [ "$FINAL_TURN_READS" -ne 0 ]; then
      adapter_fail "final findings turn used repository tools"
    fi
    rc=0
fi
exit "$rc"
