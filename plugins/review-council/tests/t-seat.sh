# tests for Task 3 — sourced by run-tests.sh
# NB: the bodies run in the RUNNER's shell, not a subshell, so ok()/fail()'s PASS/FAIL increments
# survive; seat_env's exports are undone at the end so later tests see a clean environment.
seat_timeout() {  # seat_timeout <secs> <cmd...> — hard cap, so a runaway seat cannot hang the suite
  local lim=$(( $1 * 10 )); shift
  "$@" >/dev/null 2>&1 &
  local pid=$! i=0
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt "$lim" ]; do sleep 0.1; i=$((i+1)); done
  if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124; fi
  wait "$pid"; return $?
}
seat_env_reset() { PATH="$1"; unset SHIM_FIXTURE_DIR SHIM_ARGS_FILE REV_REPO SHIM_MODE; }
seat_roster() {  # seat_roster <session-dir> — the roster.json rev-preflight.sh leaves in the session dir.
  # Written by hand on purpose: these tests exercise rev-seat.sh's dispatch, not roster.sh's detection.
  mkdir -p "$1"
  cat > "$1/roster.json" <<'JSON'
{ "generated_at": "2026-09-02T00:00:00Z",
  "seats": [
    { "seat": "codex-sol",        "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",    "effort": "max",   "extra": false },
    { "seat": "codex-terra",      "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-terra",  "effort": "xhigh", "extra": false },
    { "seat": "grok",             "lab": "xai",       "adapter": "grok",   "model": "grok-4.6",       "effort": "xhigh", "extra": false },
    { "seat": "gemini",           "lab": "google",    "adapter": "gemini", "model": "gemini-2.5-pro", "effort": null,    "extra": false },
    { "seat": "opus",             "lab": "anthropic", "adapter": "agent",  "model": "opus",           "effort": "max",   "extra": false },
    { "seat": "codex-review",     "lab": "openai",    "adapter": "codex",  "model": "gpt-5.6-sol",    "effort": "max",   "mode": "review",      "extra": true, "round": 2 },
    { "seat": "grok-code-review", "lab": "xai",       "adapter": "grok",   "model": "grok-4.6",       "effort": "xhigh", "mode": "code-review", "extra": true, "round": 3 }
  ],
  "excluded": [] }
JSON
}
test_seat_codex() {
  local _path="$PATH"; seat_env
  local S="$T/seat-codex"; seat_roster "$S"; echo "review the diff" > "$S/p.md"; : > "$T/args.env"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$S" 1 "$S/p.md" > "$T/out.txt"; local rc=$?
  assert_eq "codex ok exit" "$rc" 0
  assert_grep "prints summary line" "$T/out.txt" '^seat=codex-sol round=1 exit=0 findings=1$'
  assert_grep "writes .exit" "$S/r1-codex-sol.exit" '^0$'
  assert_grep "json copied" "$S/r1-codex-sol.json" '"severity": ?"P1"'
  assert_grep "log has exec line" "$S/r1-codex-sol.log" '^exec: .*git diff abc123'
  assert_grep "log has done line" "$S/r1-codex-sol.log" '^done: exit=0'
  assert_grep "prompt via stdin" "$T/args.stdin" 'review the diff'
  assert_grep "model comes from the roster" "$T/args" '^gpt-5.6-sol$'
  assert_grep "effort comes from the roster" "$T/args" '^model_reasoning_effort=max$'
  # the seat's environment is not visible in argv: REV_ACTIVE is the recursion guard, -C is the repo root
  assert_grep "seat carries REV_ACTIVE=1" "$T/args.env" '^REV_ACTIVE=1$'
  assert_nogrep "no seat runs unguarded" "$T/args.env" '^REV_ACTIVE=unset$'
  assert_grep "seat records its cwd" "$T/args.env" '^cwd=/'
  assert_grep "codex gets the repo root with -C" "$T/args" "^$T$"
  assert_grep "read-only sandbox" "$T/args" '^read-only$'
  assert_grep "schema passed" "$T/args" 'findings.schema.json$'
  assert_nogrep "no write flags" "$T/args" 'danger|workspace-write|--approve'
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 2 "$S/p.md" >/dev/null
  assert_grep "terra model from the roster" "$T/args" '^gpt-5.6-terra$'
  assert_grep "terra effort is its own roster entry" "$T/args" '^model_reasoning_effort=xhigh$'
  assert_exit "notauth → 3" 3 env SHIM_MODE=notauth "$SCRIPTS/rev-seat.sh" codex-sol "$S" 3 "$S/p.md"
  assert_exit "ratelimit → 4" 4 env SHIM_MODE=ratelimit "$SCRIPTS/rev-seat.sh" codex-sol "$S" 4 "$S/p.md"
  assert_exit "empty → 2" 2 env SHIM_MODE=empty "$SCRIPTS/rev-seat.sh" codex-sol "$S" 5 "$S/p.md"
  assert_exit "badjson → 2" 2 env SHIM_MODE=badjson "$SCRIPTS/rev-seat.sh" codex-sol "$S" 6 "$S/p.md"
  assert_grep "exit file records 2" "$S/r6-codex-sol.exit" '^2$'
  assert_exit "codex-review needs --base" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-review "$S" 7 "$S/p.md"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-review "$S" 7 "$S/p.md" --base abc123 >/dev/null
  assert_grep "codex-review uses review subcommand" "$T/args" '^review$'
  assert_grep "codex-review passes base" "$T/args" '^abc123$'
    assert_nogrep "codex-review passes no sandbox flag (exec review has no -s)" "$T/args" '^(-s|read-only)$'
  assert_exit "seat that is not in the roster → 1" 1 "$SCRIPTS/rev-seat.sh" mystery "$S" 8 "$S/p.md"
  "$SCRIPTS/rev-seat.sh" mystery "$S" 8 "$S/p.md" 2> "$T/noseat.err"
  assert_grep "unknown seat says run preflight first" "$T/noseat.err" 'run preflight first'
  assert_exit "missing prompt → 1" 1 "$SCRIPTS/rev-seat.sh" codex-sol "$S" 9 "$S/nope.md"
  # a session without a roster has not been through preflight: refuse, do not guess a model
  local N="$T/seat-noroster"; mkdir -p "$N"; echo "review" > "$N/p.md"
  assert_exit "no roster → 1" 1 "$SCRIPTS/rev-seat.sh" codex-sol "$N" 1 "$N/p.md"
  "$SCRIPTS/rev-seat.sh" codex-sol "$N" 1 "$N/p.md" 2> "$T/noroster.err"
  assert_grep "missing roster says run preflight first" "$T/noroster.err" 'run preflight first'
  # a roster naming an adapter this plugin has no script for is a broken roster, not a seat to guess at
  local A="$T/seat-badadapter"; mkdir -p "$A"; echo "review" > "$A/p.md"
  cat > "$A/roster.json" <<'JSON'
{ "generated_at": "t", "seats": [ { "seat": "codex-sol", "lab": "openai", "adapter": "nosuchcli", "model": "m", "effort": "max", "extra": false } ], "excluded": [] }
JSON
  assert_exit "roster adapter with no script → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$A" 1 "$A/p.md"
  # a truncated roster must fail like a missing one, not crash with a python traceback for an exit code
  local B="$T/seat-badroster"; mkdir -p "$B"; echo "review" > "$B/p.md"; printf '{ "seats": [ {' > "$B/roster.json"
  assert_exit "unreadable roster → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$B" 1 "$B/p.md"
  env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$B" 1 "$B/p.md" 2> "$T/badroster.err"
  assert_grep "unreadable roster says run preflight first" "$T/badroster.err" 'run preflight first'
  # the agent seat is launched by the skill through the Agent tool — there is no CLI to run here
  assert_exit "agent seat → 1" 1 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$S/p.md"
  "$SCRIPTS/rev-seat.sh" opus "$S" 1 "$S/p.md" 2> "$T/agent.err"
  assert_grep "agent seat explains itself" "$T/agent.err" 'Agent tool'
  # a failed run whose model stream merely quotes a 401 is "no output" (2), not "not signed in" (3)
  assert_exit "quoted 401 in stream → 2, not 3" 2 env SHIM_MODE=noise401 "$SCRIPTS/rev-seat.sh" codex-sol "$S" 10 "$S/p.md"
  assert_grep "the 401 really is in the raw stream" "$S/r10-codex-sol.stream.ndjson" '401 Unauthorized'
  # …and it reaches the LOG too, as the model's own `text:` line — that is exactly the line classify_failure
  # must ignore. Only CLI-originated lines decide sign-in and cap.
  assert_grep "the 401 is in the log as model text" "$S/r10-codex-sol.log" '^text: .*401 Unauthorized'
  assert_nogrep "no CLI-originated 401 line" "$S/r10-codex-sol.log" '^(error|exec|done): .*401'
  # effort precedence: --effort > REV_CODEX_EFFORT > the roster's entry for this seat
  REV_CODEX_EFFORT=high SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 11 "$S/p.md" >/dev/null
  assert_grep "REV_CODEX_EFFORT overrides the roster" "$T/args" '^model_reasoning_effort=high$'
  REV_CODEX_EFFORT=high SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-terra "$S" 12 "$S/p.md" --effort max >/dev/null
  assert_grep "--effort wins over both" "$T/args" '^model_reasoning_effort=max$'
  # a roster entry with no effort (the shape roster.sh emits for a model with no effort knob) still runs
  local E="$T/seat-noeffort"; mkdir -p "$E"; echo "review" > "$E/p.md"
  cat > "$E/roster.json" <<'JSON'
{ "generated_at": "t", "seats": [ { "seat": "codex-sol", "lab": "openai", "adapter": "codex", "model": "gpt-5.6-sol", "effort": null, "extra": false } ], "excluded": [] }
JSON
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" codex-sol "$E" 1 "$E/p.md" >/dev/null
  assert_grep "effort-less roster entry falls back to max" "$T/args" '^model_reasoning_effort=max$'
  seat_env_reset "$_path"
}
test_seat_grok() {
  local _path="$PATH"; seat_env
  local S="$T/seat-grok"; seat_roster "$S"; echo "review the diff" > "$S/p.md"; : > "$T/args.env"
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok "$S" 1 "$S/p.md" > "$T/out.txt"; local rc=$?
  assert_eq "grok ok exit" "$rc" 0
  assert_grep "summary line" "$T/out.txt" '^seat=grok round=1 exit=0 findings=1$'
  assert_grep "structuredOutput extracted" "$S/r1-grok.json" '"claim": "loop skips the last element"'
  assert_grep "log has tool_call" "$S/r1-grok.log" '^tool_call shell: git diff abc123'
  assert_grep "log collapses text deltas" "$S/r1-grok.log" '^text: \{"summary":"Planted off-by-one found."\}$'
  assert_nogrep "log drops thoughts" "$S/r1-grok.log" 'Let me read'
  assert_grep "log has end" "$S/r1-grok.log" '^end stopReason=end_turn'
  assert_grep "raw stream kept" "$S/r1-grok.stream.ndjson" '"type":"end"'
  assert_grep "plan mode" "$T/args" '^plan$'
  assert_grep "streaming format" "$T/args" '^streaming-json$'
  assert_grep "model comes from the roster" "$T/args" '^grok-4.6$'
  assert_grep "effort comes from the roster" "$T/args" '^xhigh$'
  assert_grep "prompt file passed" "$T/args" "^$S/p.md$"
  assert_grep "schema inline" "$T/args" '"severity"'
  assert_grep "seat carries REV_ACTIVE=1" "$T/args.env" '^REV_ACTIVE=1$'
  assert_nogrep "no seat runs unguarded" "$T/args.env" '^REV_ACTIVE=unset$'
  assert_grep "grok gets the repo root with --cwd" "$T/args" "^$T$"
  REV_GROK_EFFORT=high SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok "$S" 9 "$S/p.md" >/dev/null
  assert_grep "REV_GROK_EFFORT overrides the roster" "$T/args" '^high$'
  SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok-code-review "$S" 2 "$S/p.md" >/dev/null
  assert_grep "code-review prefixes skill" "$S/r2-grok-code-review.cr-prompt.md" '^/code-review$'
  assert_grep "code-review keeps prompt" "$S/r2-grok-code-review.cr-prompt.md" 'review the diff'
  assert_grep "code-review sends the prefixed copy" "$T/args" "^$S/r2-grok-code-review.cr-prompt.md$"
  # handed the very path rev-prompt.sh renders to (SKILL.md's documented argument): must not
  # read and rewrite one file without bound, and must leave the rendered prompt intact.
  printf 'review the diff\n' > "$S/r3-grok-code-review.prompt.md"
  seat_timeout 20 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok-code-review "$S" 3 "$S/r3-grok-code-review.prompt.md"
  local rc3=$?
  assert_eq "code-review on its own prompt path terminates" "$rc3" 0
  assert_grep "source prompt intact" "$S/r3-grok-code-review.prompt.md" '^review the diff$'
  assert_nogrep "source prompt not rewritten" "$S/r3-grok-code-review.prompt.md" '/code-review'
  seat_timeout 20 env SHIM_MODE=ok "$SCRIPTS/rev-seat.sh" grok-code-review "$S" 3 "$S/r3-grok-code-review.prompt.md"
  assert_eq "rerun stays single-prefixed" "$(grep -c '^/code-review$' "$S/r3-grok-code-review.cr-prompt.md")" 1
  assert_exit "notauth → 3" 3 env SHIM_MODE=notauth "$SCRIPTS/rev-seat.sh" grok "$S" 4 "$S/p.md"
  assert_exit "ratelimit → 4" 4 env SHIM_MODE=ratelimit "$SCRIPTS/rev-seat.sh" grok "$S" 5 "$S/p.md"
  assert_exit "empty → 2" 2 env SHIM_MODE=empty "$SCRIPTS/rev-seat.sh" grok "$S" 6 "$S/p.md"
  seat_env_reset "$_path"
}
