#!/bin/bash
# stack.sh <config.sh>
# Run /review-council:rev across a STACK of repos, unattended: per-repo legs (PASSES passes), a cross-repo seam
# review, a completeness critic, then one squash + push per repo. Legs are headless
# `claude -p "/review-council:rev …"` runs marked REV_STACK_LEG=1, so they never squash or push themselves.
#
# The config defines legs() — run_leg calls in DEPENDENCY ORDER — and may set SEAM_REPO / CRITIC_REPO / premises.
# See stack.example.sh next to this script.
#
# ONE stall detector, here, and nowhere else. A leg is killed only when (a) its run.log AND session dir have been
# quiet for STALL_SECS and (b) its CPU time did not move across CPU_SAMPLE_SECS. stream-json makes run.log a real
# liveness signal (one event per assistant message and tool call); the CPU veto is what prevents false kills
# during a long silent build. A stall is never counted as an infrastructure failure.
#
# CPU and kill both see the whole leg TREE, never just the direct child: the seat CLIs (codex/grok) run as
# grandchildren under claude and are where the CPU actually goes, so measuring the child alone reads "frozen"
# while a seat is mid-run (a false kill) and killing the child alone orphans the seats (leaked usage quota).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib/compat.sh
# Guarded: without rc_mtime/rc_newest_mtime the stall detector loses the file-activity half of its
# two-condition kill rule and silently kills healthy legs, so a missing compat.sh is fatal, not a warning.
. "$HERE/lib/compat.sh" || { echo "stack: cannot load $HERE/lib/compat.sh" >&2; exit 1; }   # rc_mtime / rc_newest_mtime — BSD and GNU stat differ
# PATH is APPENDED, never prepended: an operator's (or a test's) own claude/codex/grok must keep winning.
export PATH="$PATH:$HOME/.nvm/versions/node/v22.22.0/bin:$HOME/.local/bin"
[ -z "${REV_ACTIVE:-}${REV_STACK_LEG:-}" ] || { echo "stack: refusing to nest (REV_ACTIVE or REV_STACK_LEG is set)" >&2; exit 1; }
CONFIG=${1:?usage: stack.sh <config.sh>   (template: stack.example.sh next to this script)}
[ -f "$CONFIG" ] || { echo "stack: config not found: $CONFIG" >&2; exit 1; }
ROOT=${ROOT:-/tmp/review-council-stack-$(date +%s)}
LOG=${LOG:-/tmp/review-council-stack.log}
# DETACH BY DEFAULT. A run lasts hours; anything still inside the launching tool's process tree dies with it —
# a Claude Code background Bash command was killed by the harness after ~56 min and took the leg (its whole
# process group) down mid-round. So the orchestrator re-executes itself in a NEW SESSION with HUP ignored
# (nohup; setsid via python because macOS ships none), prints where it went, and returns. Tail $LOG to follow.
# REV_STACK_FOREGROUND=1 keeps it attached (tests, or a terminal you intend to keep open).
if [ -z "${REV_STACK_FOREGROUND:-}" ] && [ -z "${REV_STACK_DETACHED:-}" ]; then
  mkdir -p "$ROOT"; OUTF="$ROOT/orchestrator.out"
  export REV_STACK_DETACHED=1 ROOT LOG
  nohup python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$0" "$@" > "$OUTF" 2>&1 < /dev/null &
  echo "stack: detached (pid $!), session root $ROOT, log $LOG, orchestrator output $OUTF"
  exit 0
fi
PASSES=${PASSES:-2}
STALL_SECS=${STALL_SECS:-1800}
CPU_SAMPLE_SECS=${CPU_SAMPLE_SECS:-45}
POLL=${POLL:-60}
STATUS_EVERY=${STATUS_EVERY:-600}
MAX_ATTEMPTS=${MAX_ATTEMPTS:-4}
MAX_INFRA_RETRIES=${MAX_INFRA_RETRIES:-12}
FAST_FAIL_SECS=${FAST_FAIL_SECS:-90}
INFRA_SLEEP_SECS=${INFRA_SLEEP_SECS:-300}
AUTH_WAIT_TRIES=${AUTH_WAIT_TRIES:-60}
AUTH_WAIT_SECS=${AUTH_WAIT_SECS:-60}
if [ "${REVIEW_COUNCIL_HOST:-claude}" = codex ]; then
  NO_PUSH=${NO_PUSH:-1}
  NO_SQUASH=${NO_SQUASH:-1}
else
  NO_PUSH=${NO_PUSH:-0}
  NO_SQUASH=${NO_SQUASH:-0}
fi
REV_SCRIPTS=${REV_SCRIPTS:-$HERE}   # roster.sh, rev-status.sh and rev-squash.sh live beside this script
SEAM_REPO=${SEAM_REPO:-}
SEAM_PREMISE=${SEAM_PREMISE:-"Review the SEAMS between the PRs in this stack, not the code again: what each PR promises the others, what each assumes of the others, and every claim that a sibling PR invalidates."}
CRITIC_REPO=${CRITIC_REPO:-}
CRITIC_PREMISE=${CRITIC_PREMISE:-"What did every previous pass MISS? Name modalities never run and claims never verified. Read every leg's findings.md under the stack session root first."}
VACUITY=${VACUITY:-"Check every assertion the diff adds or touches for VACUITY: would it still pass if the behaviour it names were deleted? Name the production change that would make each new test fail, and report any that has none."}
REPOS_SEEN=""
FAILED_LABELS=""      # every leg that ended without a completed review
FAILED_REPOS=""       # …and the repos they belong to: those are NOT squashed at the end
mkdir -p "$ROOT"

say() { echo "$(date '+%m-%d %H:%M') $*" | tee -a "$LOG"; }
note_failure() {  # <label> <repo-dir> — a failed leg must not be reported as a complete run
  FAILED_LABELS="$FAILED_LABELS $1"
  case " $FAILED_REPOS " in *" $2 "*) ;; *) FAILED_REPOS="$FAILED_REPOS $2";; esac
}
leg_group() {  # the leg's own process-group id, and only when it leads that group (see leg_tree)
  local g; g=$(ps -o pgid= -p "$1" 2>/dev/null | tr -d ' ')
  [ -n "$g" ] && [ "$g" = "$1" ] && echo "$g"
}
leg_tree() {  # every pid in the leg's tree: its process group when it owns one, else a recursive walk of children
  local g c; g=$(leg_group "$1")
  if [ -n "$g" ]; then pgrep -g "$g" 2>/dev/null; return 0; fi
  kill -0 "$1" 2>/dev/null && echo "$1"
  for c in $(pgrep -P "$1" 2>/dev/null); do leg_tree "$c"; done
}
cpu_of() {  # summed CPU seconds over the whole leg tree — the seat CLIs burn it, not the leg's own shell
  local pids; pids=$(leg_tree "$1" | sort -un | tr '\n' ','); pids=${pids%,}
  [ -n "$pids" ] || return 0
  ps -o time= -p "$pids" 2>/dev/null |
    awk '{n=split($1,a,":"); s=0; for(i=1;i<=n;i++) s=s*60+a[i]; t+=s} END{if (NR>0) printf "%.2f", t}'
}
kill_leg() {  # TERM then KILL the whole tree; the group is resolved BEFORE the leader dies or the seats orphan
  local g pids; g=$(leg_group "$1"); pids=$(leg_tree "$1" | sort -un | tr '\n' ' ')
  if [ -n "$g" ]; then kill -TERM "-$g" 2>/dev/null; else kill -TERM $pids 2>/dev/null; fi
  sleep 3
  if [ -n "$g" ]; then kill -9 "-$g" 2>/dev/null; else kill -9 $pids 2>/dev/null; fi
}
last_activity() {  # <session-dir> → newest mtime of run.log or anything under it, 0 when nothing exists yet
  local m1 m2
  m1=$(rc_mtime "$1/run.log"); m1=${m1:-0}
  m2=$(rc_newest_mtime "$1"); m2=${m2:-0}
  [ "$m2" -gt "$m1" ] && m1=$m2
  echo "$m1"
}

status_of() {  # one status line, never empty: a blank or failing rev-status.sh is itself reported, its stderr kept in the orchestrator output
  local line; line=$("$REV_SCRIPTS/rev-status.sh" "$1" 2>>"${ROOT}/status.err") || line=""
  [ -n "$line" ] && printf '%s' "$line" || printf '(status unavailable — see %s/status.err)' "$ROOT"
}

wait_for_auth() {
  # The roster owns sign-in detection for every lab; the stack only asks whether it will seat a panel at all.
  # `roster.sh --brief` exits 0 whenever a panel exists — it pads a thin one with Claude seats and marks it
  # degraded rather than refusing — and non-zero only in strict mode (config `min_labs`). That exit code is
  # the entire gate: a degraded panel is a panel, and the leg's own report says it was degraded.
  local i
  for i in $(seq 1 "$AUTH_WAIT_TRIES"); do
    "$REV_SCRIPTS/roster.sh" --brief >/dev/null && return 0
    say "    auth not ready ($i/$AUTH_WAIT_TRIES)"; sleep "$AUTH_WAIT_SECS"
  done
  return 1
}

run_leg() {  # <repo-path> <rounds> <label> "<premise>"
  local dir="$1" rounds="$2" label="$3" extra="$4"
  local S="$ROOT/$label" attempt=1 infra=0
  case " $REPOS_SEEN " in *" $dir "*) ;; *) REPOS_SEEN="$REPOS_SEEN $dir";; esac
  # Resume keys on THIS run's session root as well as the label: a different stack sharing the default LOG must
  # never skip a leg it has not actually run (that would fall straight through to the squash + push phase).
  grep -qF "=== DONE $label pass${PASS} exit=0 root=$ROOT" "$LOG" 2>/dev/null && { say "=== SKIP $label pass${PASS} (already done in $LOG)"; return 0; }
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    mkdir -p "$S"
    wait_for_auth || { say "!!! $label: auth never came back; skipping"; note_failure "$label" "$dir"; return 1; }
    local resume=""
    [ -f "$S/findings.md" ] && resume="

NOTE: an earlier pass of this review exists. Read $S/findings.md FIRST and do not re-raise what it fixed, rejected with sound reasoning, or deferred with a stated reason. Start from the current branch state."
    say "=== START $label pass${PASS} (attempt $attempt/$MAX_ATTEMPTS) rounds=$rounds"
    local t0; t0=$(date +%s)
    local prompt="/review-council:rev branch $rounds — use $S as the session dir.

${extra}

${VACUITY}${resume}"
    if [ "${REVIEW_COUNCIL_HOST:-claude}" = codex ]; then
      local skill="$HERE/../codex-skills/rev/SKILL.md"
      [ -f "$skill" ] || { say "!!! missing Codex rev skill: $skill"; note_failure "$label" "$dir"; return 1; }
      prompt="Read and follow the Codex review-council skill at $skill.
Review branch $rounds rounds; use $S as the session dir. This is a stack leg: do not squash or push.

${extra}

${VACUITY}${resume}"
      # A previous pass's receipt cannot certify this attempt completed.
      [ ! -f "$S/report.md" ] || mv "$S/report.md" "$S/report.previous.md"
    fi
    set -m   # give the leg its own process group, so the CPU veto and the kill can address the whole tree
    (
      cd "$dir" || exit 1
      export REV_STACK_LEG=1
      if [ "${REVIEW_COUNCIL_HOST:-claude}" = codex ]; then
        printf '%s\n' "$prompt" | codex exec --ephemeral -s workspace-write \
          -c sandbox_workspace_write.network_access=true --add-dir "$ROOT" --json -
      else
        claude -p "$prompt" --permission-mode bypassPermissions --effort max --output-format stream-json --verbose </dev/null
      fi
    ) > "$S/run.log" 2>&1 &
    set +m
    local pid=$! last_seen last_cpu="" last_status stalled=0
    last_seen=$(date +%s); last_status=$last_seen
    while kill -0 "$pid" 2>/dev/null; do
      sleep "$POLL"
      local now m idle; now=$(date +%s)
      m=$(last_activity "$S")
      [ "$m" -gt "$last_seen" ] && last_seen=$m
      idle=$(( now - last_seen )); [ "$idle" -lt 0 ] && idle=0   # an mtime a second ahead of the clock is not negative idleness
      if [ $(( now - last_status )) -ge "$STATUS_EVERY" ]; then
        local c mv n; c=$(cpu_of "$pid"); mv=frozen; [ "$c" != "$last_cpu" ] && mv=moving; last_cpu=$c
        n=$(cd "$dir" && git rev-list --count '@{u}..HEAD' 2>/dev/null || echo -)
        say "[status] $label pass${PASS} attempt$attempt | $(status_of "$S") | idle=${idle}s cpu=${c:-none}($mv) commits=$n"
        last_status=$now
      fi
      if [ "$idle" -ge "$STALL_SECS" ]; then
        local c1 c2 idle2; c1=$(cpu_of "$pid"); sleep "$CPU_SAMPLE_SECS"; c2=$(cpu_of "$pid")
        # The sample is a blind window: the leg can finish or come back to life inside it. Re-check
        # BOTH before killing, or a leg that completed normally is recorded as stalled and retried.
        if ! kill -0 "$pid" 2>/dev/null; then
          say "    $label finished during the ${CPU_SAMPLE_SECS}s cpu sample — not killing"; break
        fi
        m=$(last_activity "$S")
        [ "$m" -gt "$last_seen" ] && last_seen=$m
        idle2=$(( $(date +%s) - last_seen ))
        if [ "$idle2" -lt "$STALL_SECS" ]; then
          say "    $label spoke during the cpu sample (idle ${idle2}s) — not killing"; continue
        fi
        if [ -n "$c2" ] && [ "$c1" != "$c2" ]; then
          say "    $label quiet ${idle}s but cpu $c1 -> $c2 — working, not killing"; last_seen=$(date +%s); continue
        fi
        say "!!! $label STALLED (${idle2}s idle, cpu frozen at ${c1:-n/a}) — killing"; stalled=1
        kill_leg "$pid"; break
      fi
    done
    wait "$pid" 2>/dev/null; local rc=$? dur=$(( $(date +%s) - t0 ))
    if [ "$rc" -eq 0 ] && [ "$stalled" = 0 ] && [ ! -f "$S/report.md" ]; then
      # A headless leg that ends its turn waiting on a background task exits 0 with the loop unfinished (seen live:
      # round 4 fixes uncommitted, no report). report.md is the leg's completion receipt; without it, retry with resume.
      say "!!! $label exited 0 after ${dur}s but wrote no report.md — incomplete; retrying with resume"; rc=75
    fi
    if [ "$rc" -eq 0 ] && [ "$stalled" = 0 ]; then say "=== DONE $label pass${PASS} exit=0 root=$ROOT (${dur}s)"; return 0; fi
    if [ "$stalled" = 0 ] && [ "$dur" -lt "$FAST_FAIL_SECS" ] && [ "$infra" -lt "$MAX_INFRA_RETRIES" ]; then
      infra=$(( infra + 1 )); say "    $label failed in ${dur}s — infrastructure; sleeping ${INFRA_SLEEP_SECS}s"; sleep "$INFRA_SLEEP_SECS"; continue
    fi
    say "=== $label ended rc=$rc after ${dur}s (attempt $attempt)"; attempt=$(( attempt + 1 ))
  done
  say "=== GAVE UP on $label"; note_failure "$label" "$dir"; return 1
}

finish_repos() {
  local d srq
  for d in $REPOS_SEEN; do
    case " $FAILED_REPOS " in *" $d "*)
      say "--- skipping $(basename "$d") — a leg on it failed; its review is not complete"; continue;; esac
    say "--- finishing $(basename "$d")"
    set -o pipefail
    ( cd "$d" && if [ "$NO_SQUASH" = 1 ]; then echo "(NO_SQUASH=1: keeping review commits)"; else "$REV_SCRIPTS/rev-squash.sh" --apply; fi ) 2>&1 | sed 's/^/    /' | tee -a "$LOG"
    srq=$?
    set +o pipefail
    # A refused squash is not a reason to withhold the push: the round commits are real work and CI
    # must see them. Squash and push are therefore independent steps, not one && chain.
    [ "$srq" -eq 0 ] || say "!!! squash refused for $(basename "$d") — pushing the un-collapsed review commits"
    ( cd "$d" && if [ "$NO_PUSH" = 1 ]; then echo "(NO_PUSH=1: not pushing)"; else git push; fi ) 2>&1 | sed 's/^/    /' | tee -a "$LOG"
  done
}

# shellcheck disable=SC1090
set +u; . "$CONFIG"; set -u   # a user's stack config stays forgiving; this script does not
type legs >/dev/null 2>&1 || { echo "stack: $CONFIG must define legs() containing run_leg calls in dependency order" >&2; exit 1; }
say "########## review-council stack: session root $ROOT, log $LOG ##########"
for PASS in $(seq 1 "$PASSES"); do export PASS; say "########## PHASE 1 — PER-PR, PASS ${PASS}/${PASSES} ##########"; legs; done
say "ALL PHASE 1 COMPLETE"
if [ -n "$SEAM_REPO" ]; then PASS=seam; say "########## PHASE 2 — CROSS-REPO SEAMS ##########"; run_leg "$SEAM_REPO" 2 seams "$SEAM_PREMISE"; else say "PHASE 2 skipped (SEAM_REPO unset)"; fi
if [ -n "$CRITIC_REPO" ]; then PASS=critic; say "########## PHASE 3 — COMPLETENESS CRITIC ##########"; run_leg "$CRITIC_REPO" 1 critic "$CRITIC_PREMISE"; else say "PHASE 3 skipped (CRITIC_REPO unset)"; fi
say "########## FINISH — squash + push per repo ##########"; finish_repos
if [ -n "$FAILED_LABELS" ]; then say "COMPLETE WITH FAILURES:$FAILED_LABELS"; exit 1; fi
say "ALL PHASES COMPLETE"
