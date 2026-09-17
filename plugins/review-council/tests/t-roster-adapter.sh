# claude_adapter (cli/agent/auto) and plan_seats in the roster. Reuses roster_env/roster_lines from t-roster.sh.

# roster_adapter_golden <roster.py> <out.json> <config|env> - run fixed Claude Code host scenarios with a
# signed-in claude CLI on PATH, `claude_adapter: agent` set through config or the environment, and record
# each exit code, roster (without generated_at) and --brief line. tests/fixtures/roster-agent-golden.json
# was recorded from the unmodified 0.4.4 roster.py, which always seated Anthropic reviewers on `agent`.
roster_adapter_golden() {
  python3 - "$1" "$2" "$3" "$SHIMS" "$FX" <<'PY'
import json, os, shutil, subprocess, sys, tempfile
roster, out, mode, shims, fixtures = sys.argv[1:6]
exact = {'codex_models': ['gpt-5.6-sol', 'gpt-5.6-terra'], 'claude_models': ['opus', 'sonnet'],
         'extras': False}
scenarios = [
    ('full', ('codex', 'gemini', 'claude'), {}, []),
    ('exact-probe', ('codex', 'claude'), exact, ['--probe']),
    ('claude-seats-excluded', ('codex', 'claude'), {'claude_seats': 2, 'exclude': ['opus-2']}, []),
    ('claude-only', ('claude',), {}, []),
    ('claude-seat-false-min-labs', ('codex', 'claude'), {'claude_seat': False, 'min_labs': 2}, []),
    ('exclude-agent', ('codex', 'claude'), {'exclude': ['agent']}, []),
    ('pin-conflict', ('codex', 'claude'),
     dict(exact, pin={'sonnet': {'model': 'opus'}}), ['--probe']),
]
result = {}
with tempfile.TemporaryDirectory(prefix='roster-golden-') as tmp:
    for name, clis, config, args in scenarios:
        root = os.path.join(tmp, name); bin_dir = os.path.join(root, 'bin')
        os.makedirs(bin_dir); os.makedirs(os.path.join(root, 'home/.gemini'))
        for cli in clis:
            shutil.copy(os.path.join(shims, cli), os.path.join(bin_dir, cli))
        creds = os.path.join(root, 'home/.gemini/oauth_creds.json')
        if 'gemini' in clis:
            open(creds, 'w').write('{"access_token":"x"}')
        config = dict(config)
        env = {'PATH': bin_dir + ':/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': os.path.join(root, 'home'),
               'LANG': 'C.UTF-8', 'SHIM_FIXTURE_DIR': fixtures,
               'REVIEW_COUNCIL_CODEX_MODELS_CACHE': os.path.join(fixtures, 'roster-codex-cache-full.json'),
               'REVIEW_COUNCIL_CONFIG': os.path.join(root, 'config.json'),
               'REVIEW_COUNCIL_GEMINI_CREDS': creds}
        if mode == 'config':
            config['claude_adapter'] = 'agent'
        else:
            env['REVIEW_COUNCIL_CLAUDE_ADAPTER'] = 'agent'
        open(env['REVIEW_COUNCIL_CONFIG'], 'w').write(json.dumps(config))
        entry = {}
        for form in ('json', 'brief'):
            run = subprocess.run([sys.executable, roster, '--' + form, *args], env=env,
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True)
            entry[form + '_exit'] = run.returncode
            if form == 'json':
                document = json.loads(run.stdout)
                document.pop('generated_at')
                entry['roster'] = document
            else:
                entry['brief'] = run.stdout
        result[name] = entry
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2, ensure_ascii=False, sort_keys=True)
    stream.write('\n')
PY
}

test_roster_adapter_agent_matches_legacy_golden() {
  ( local B="$T/roster-adapter-golden" mode; mkdir -p "$B"
    for mode in config env; do
      roster_adapter_golden "$SCRIPTS/lib/roster.py" "$B/$mode.json" "$mode"
      assert_eq "claude_adapter agent through $mode ran every scenario" "$?" 0
      assert_exit "claude_adapter agent through $mode is byte-identical to the legacy roster" 0 \
        cmp -s "$B/$mode.json" "$FX/roster-agent-golden.json"
    done
    assert_grep "the golden seats Opus on the Agent adapter beside a signed-in CLI" \
      "$FX/roster-agent-golden.json" '"adapter": "agent"'
    assert_nogrep "the golden never seats the claude CLI" "$FX/roster-agent-golden.json" '"adapter": "claude"'
  )
}

roster_adapter_claude() {  # roster_adapter_claude <bin> - a claude CLI that logs sign-in checks, probes and their env
  cat > "$1/claude" <<'SH'
#!/bin/bash
if [ "${1:-}" = auth ] && [ "${2:-}" = status ]; then
  printf 'auth\n' >> "$RA_CALLS"
  env | cut -d= -f1 | sort > "$RA_CALLS.auth-env"
  printf '{"loggedIn":%s}\n' "${RA_LOGGED_IN:-true}"
  exit 0
fi
model=''
for value in "$@"; do case "$value" in opus|sonnet) model=$value;; esac; done
printf 'probe:%s\n' "$model" >> "$RA_CALLS"
env | cut -d= -f1 | sort > "$RA_CALLS.probe-env"
[ "$model" != "${RA_FAIL_MODEL:-}" ] || { echo 'provider transport failed' >&2; exit 1; }
echo OK
SH
  chmod +x "$1/claude"
}

test_roster_adapter_resolution() {
  ( local B="$T/roster-adapter"; roster_env "$B"; roster_adapter_claude "$B"
    export RA_CALLS="$B/calls" REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/auto.json"; assert_eq "auto roster exits 0" "$?" 0
    roster_lines "$B/auto.json" "$B/auto"
    assert_grep "auto seats Opus on a signed-in claude CLI" "$B/auto" '^seat opus anthropic claude opus max false'
    assert_grep "auto pads with the same CLI" "$B/auto" '^seat claude-2 anthropic claude opus max false'
    assert_eq "auto checks sign-in once for resolution and detection" "$(grep -c '^auth$' "$RA_CALLS")" 1
    "$SCRIPTS/roster.sh" --brief > "$B/auto.brief"
    assert_grep "a CLI seat reads like the Agent seat in the banner" "$B/auto.brief" 'claude ✓ \(opus@max\)'

    : > "$RA_CALLS"
    RA_LOGGED_IN=false "$SCRIPTS/roster.sh" > "$B/signed-out.json"
    roster_lines "$B/signed-out.json" "$B/signed-out"
    assert_grep "auto falls back to agent when the CLI is signed out" "$B/signed-out" '^seat opus anthropic agent opus max false'
    assert_grep "auto pads signed-out hosts with agent seats" "$B/signed-out" '^seat claude-2 anthropic agent opus max false'
    assert_eq "a signed-out CLI is checked once" "$(grep -c '^auth$' "$RA_CALLS")" 1

    mv "$B/claude" "$B/claude.off"; : > "$RA_CALLS"
    "$SCRIPTS/roster.sh" > "$B/missing.json"
    roster_lines "$B/missing.json" "$B/missing"
    assert_grep "auto falls back to agent when the CLI is not installed" "$B/missing" '^seat opus anthropic agent opus max false'
    assert_eq "a missing CLI is never run" "$(wc -c < "$RA_CALLS" | tr -d ' ')" 0
    printf '%s' '{"claude_adapter":"cli"}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/cli-missing.json"
    roster_lines "$B/cli-missing.json" "$B/cli-missing"
    assert_grep "cli reports a missing CLI" "$B/cli-missing" '^excluded claude -> not installed$'
    assert_nogrep "cli never seats a detected Agent reviewer" "$B/cli-missing" '^seat opus '
    mv "$B/claude.off" "$B/claude"

    : > "$RA_CALLS"
    "$SCRIPTS/roster.sh" > "$B/cli.json"
    roster_lines "$B/cli.json" "$B/cli"
    assert_grep "cli seats Opus on the claude CLI" "$B/cli" '^seat opus anthropic claude opus max false'
    assert_eq "cli checks sign-in once through detection" "$(grep -c '^auth$' "$RA_CALLS")" 1
    : > "$RA_CALLS"
    REVIEW_COUNCIL_CLAUDE_ADAPTER=agent "$SCRIPTS/roster.sh" > "$B/env-agent.json"
    roster_lines "$B/env-agent.json" "$B/env-agent"
    assert_grep "the environment overrides config cli with agent" "$B/env-agent" '^seat opus anthropic agent opus max false'
    assert_eq "agent never runs the claude CLI" "$(wc -c < "$RA_CALLS" | tr -d ' ')" 0
    printf '%s' '{"claude_adapter":"agent"}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_CLAUDE_ADAPTER=cli "$SCRIPTS/roster.sh" > "$B/env-cli.json"
    roster_lines "$B/env-cli.json" "$B/env-cli"
    assert_grep "the environment overrides config agent with cli" "$B/env-cli" '^seat opus anthropic claude opus max false'

    : > "$RA_CALLS"
    printf '%s' '{"claude_adapter":"yes"}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/invalid.json"; assert_eq "an invalid claude_adapter is permanent config" "$?" 6
    roster_lines "$B/invalid.json" "$B/invalid"
    assert_grep "invalid config names the key" "$B/invalid" \
      '^excluded claude_adapter -> strict: invalid claude_adapter: expected cli, agent or auto$'
    assert_grep "invalid config is the strict reason" "$B/invalid" \
      '^strict_reason invalid claude_adapter: expected cli, agent or auto$'
    assert_nogrep "invalid config launches no probe" "$RA_CALLS" '^probe:'
    printf '%s' '{}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_CLAUDE_ADAPTER=CLI "$SCRIPTS/roster.sh" > "$B/invalid-env.json"
    assert_eq "an invalid environment override is permanent config" "$?" 6
    roster_lines "$B/invalid-env.json" "$B/invalid-env"
    assert_grep "invalid environment names the variable" "$B/invalid-env" \
      '^strict_reason invalid REVIEW_COUNCIL_CLAUDE_ADAPTER: expected cli, agent or auto$'

    : > "$RA_CALLS"
    CLAUDECODE=1 CLAUDE_CODE_ENTRYPOINT=cli CLAUDE_CODE_SESSION_ID=parent CLAUDE_PID=1 \
      CLAUDE_CODE_OAUTH_TOKEN=token ANTHROPIC_API_KEY=key CLAUDE_CONFIG_DIR="$B.home" CLAUDE_CODE_USE_BEDROCK=1 \
      "$SCRIPTS/roster.sh" --probe > "$B/scrub.json"
    assert_eq "a nested roster probe exits 0" "$?" 0
    local stage var
    for stage in auth probe; do
      for var in CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION_ID CLAUDE_PID; do
        assert_nogrep "the $stage check does not inherit $var" "$RA_CALLS.$stage-env" "^$var\$"
      done
      for var in CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY CLAUDE_CONFIG_DIR CLAUDE_CODE_USE_BEDROCK; do
        assert_grep "the $stage check keeps $var" "$RA_CALLS.$stage-env" "^$var\$"
      done
    done

    printf '%s' '{"claude_adapter":"agent","claude_models":["opus","sonnet"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=codex "$SCRIPTS/roster.sh" > "$B/codex-agent.json"
    REVIEW_COUNCIL_HOST=codex REVIEW_COUNCIL_CLAUDE_ADAPTER=agent "$SCRIPTS/roster.sh" > "$B/codex-env.json"
    printf '%s' '{"claude_models":["opus","sonnet"],"extras":false}' > "$REVIEW_COUNCIL_CONFIG"
    REVIEW_COUNCIL_HOST=codex "$SCRIPTS/roster.sh" > "$B/codex-default.json"
    python3 - "$B/codex-default.json" "$B/codex-agent.json" "$B/codex-env.json" <<'PY'
import json, sys
documents = [json.load(open(path)) for path in sys.argv[1:]]
for document in documents:
    document.pop('generated_at')
assert documents[0] == documents[1] == documents[2], documents
assert [(s['seat'], s['adapter']) for s in documents[0]['seats']] == [('opus', 'claude'), ('sonnet', 'claude'), ('opus-1', 'claude')], documents[0]
PY
    assert_eq "a Codex host keeps the claude CLI whatever claude_adapter says" "$?" 0
  )
}

test_roster_adapter_padding_follows_probe() {
  ( local B="$T/roster-adapter-pad"; roster_env "$B"; roster_adapter_claude "$B"
    export RA_CALLS="$B/calls" REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    printf '%s' '{"claude_models":["sonnet"]}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" --probe > "$B/sonnet.json"; assert_eq "a probed Sonnet CLI roster exits 0" "$?" 0
    roster_lines "$B/sonnet.json" "$B/sonnet"
    assert_grep "Sonnet runs on the CLI" "$B/sonnet" '^seat sonnet anthropic claude sonnet max false'
    assert_grep "padding follows the resolved CLI adapter" "$B/sonnet" '^seat claude-1 anthropic claude opus max false'
    assert_grep "…for every padded seat" "$B/sonnet" '^seat claude-2 anthropic claude opus max false'

    printf '%s' '{}' > "$REVIEW_COUNCIL_CONFIG"
    RA_FAIL_MODEL=opus "$SCRIPTS/roster.sh" --probe > "$B/opus-failed.json"
    assert_eq "a failed Opus CLI probe still builds a panel" "$?" 0
    roster_lines "$B/opus-failed.json" "$B/opus-failed"
    assert_grep "the failed probe is reported" "$B/opus-failed" '^excluded opus -> probe failed: provider transport failed$'
    assert_grep "padding falls back to agent after an Opus probe failure" "$B/opus-failed" \
      '^seat claude-1 anthropic agent opus max false'
    assert_grep "…for the whole floor" "$B/opus-failed" '^seat claude-3 anthropic agent opus max false'
    assert_nogrep "no CLI seat survives a failed Opus probe" "$B/opus-failed" '^seat .* claude opus '
  )
}

test_roster_plan_seats_setting() {
  ( local B="$T/roster-plan-seats"; roster_env "$B"
    export REVIEW_COUNCIL_CONFIG="$B.home/cfg.json"
    local value
    for value in '{}' '{"plan_seats":"completeness"}'; do
      printf '%s' "$value" > "$REVIEW_COUNCIL_CONFIG"
      "$SCRIPTS/roster.sh" > "$B/out.json"; assert_eq "$value roster exits 0" "$?" 0
      assert_exit "$value leaves plan_seats out of the roster" 0 \
        python3 -c 'import json,sys; assert "plan_seats" not in json.load(open(sys.argv[1]))' "$B/out.json"
    done
    printf '%s' '{"plan_seats":"all"}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/all.json"; assert_eq "plan_seats all exits 0" "$?" 0
    assert_exit "plan_seats all is recorded at the top level" 0 \
      python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["plan_seats"] == "all"' "$B/all.json"
    printf '%s' '{"plan_seats":"four"}' > "$REVIEW_COUNCIL_CONFIG"
    "$SCRIPTS/roster.sh" > "$B/invalid.json"; assert_eq "an invalid plan_seats is permanent config" "$?" 6
    roster_lines "$B/invalid.json" "$B/invalid"
    assert_grep "invalid plan_seats names the key" "$B/invalid" \
      '^excluded plan_seats -> strict: invalid plan_seats: expected completeness or all$'
    assert_exit "an invalid plan_seats is not recorded" 0 \
      python3 -c 'import json,sys; assert "plan_seats" not in json.load(open(sys.argv[1]))' "$B/invalid.json"
  )
}
