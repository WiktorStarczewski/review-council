#!/bin/bash

preflight_cost_fixture() {
  local B=$1 R="$1/repo" C="$1/checker"
  mkrepo "$R" || return
  mkdir -p "$R/plugins/review-council/.codex-plugin" "$R/plugins/review-council/scripts"
  printf '{}\n' > "$R/plugins/review-council/.codex-plugin/plugin.json"
  printf 'old\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
  git -C "$R" add . && git -C "$R" commit -qm base || return
  git -C "$R" checkout -qb feature || return
  printf 'new\n' > "$R/plugins/review-council/scripts/rev-prompt.sh"
  copy_writable_tree "$SK" "$C" || return
  cat > "$C/scripts/roster.sh" <<'SH'
#!/bin/bash
printf 'probe\n' >> "$COST_PROBES"
while [ $# -gt 0 ]; do
  if [ "$1" = --write ]; then cp "$COST_ROSTER" "$2"; shift 2; else shift; fi
done
printf 'review-council seats: local test roster\n'
SH
  chmod +x "$C/scripts/roster.sh"
  provider_contract_roster "$B/roster.json"
  export COST_PROBES="$B/probes" COST_ROSTER="$B/roster.json"
  export REVIEW_COUNCIL_CACHE_DIR="$B/cache"
  export REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"claude":"1","codex":"1"}'
}

test_preflight_cost_static_refusal() {
  ( local B="$T/preflight-cost-static" name
    preflight_cost_fixture "$B" || return
    : > "$B/checker/tests/fixtures/provider-contract-claude.ndjson"
    (cd "$B/repo" && "$B/checker/scripts/rev-preflight.sh" --write "$B/session") \
      > "$B/out" 2> "$B/err"
    assert_eq "broken local provider envelope refuses public preflight" "$?" 1
    assert_exit "known local incompatibility spends zero roster probes" 1 test -e "$COST_PROBES"
    assert_grep "static refusal identifies the pre-probe phase" "$B/err" \
      'provider contract replay failed before the roster probe'
    for name in scope.env roster.json files.txt untracked.txt; do
      assert_exit "static refusal installs no $name" 1 test -e "$B/session/$name"
    done
    assert_exit "static refusal publishes no authoritative receipt" 1 \
      bash -c 'compgen -G "$1/contract-pass-*.json"' sh "$B/session"
  )
}

test_preflight_cost_authoritative_replay() {
  ( local B="$T/preflight-cost-authoritative" runner name
    preflight_cost_fixture "$B" || return
    runner="$B/runner"
    cat > "$runner" <<'SH'
#!/bin/bash
printf '%s\n' "$1" >> "$COST_CONTRACT_CALLS"
SH
    chmod +x "$runner"
    export REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" COST_CONTRACT_CALLS="$B/contracts"
    REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{}' \
      bash -c 'cd "$1" && "$2" --write "$3"' sh "$B/repo" \
        "$B/checker/scripts/rev-preflight.sh" "$B/rejected" > "$B/out" 2> "$B/err"
    assert_eq "healthy static replay still refuses unavailable exact versions after probing" "$?" 1
    assert_eq "healthy static replay reaches the roster probe once" "$(wc -l < "$COST_PROBES" | tr -d ' ')" 1
    assert_eq "static replay runs each local contract group once" "$(wc -l < "$COST_CONTRACT_CALLS" | tr -d ' ')" 4
    assert_grep "authoritative phase remains a public refusal" "$B/err" \
      'provider contract replay failed after the roster probe'
    for name in scope.env roster.json files.txt untracked.txt; do
      assert_exit "authoritative refusal installs no $name" 1 test -e "$B/rejected/$name"
    done
    (cd "$B/repo" && "$B/checker/scripts/rev-preflight.sh" --write "$B/accepted") \
      > "$B/out" 2> "$B/err"
    assert_eq "healthy exact-roster preflight succeeds" "$?" 0
    assert_eq "healthy preflight reuses local replay without doubling suites" \
      "$(wc -l < "$COST_CONTRACT_CALLS" | tr -d ' ')" 4
    assert_eq "successful preflight still probes the frozen roster" \
      "$(wc -l < "$COST_PROBES" | tr -d ' ')" 2
    local base; base=$(git -C "$B/repo" rev-parse main)
    python3 "$B/checker/scripts/rev-contract-check.py" --root "$B/repo" --base "$base" \
      --session "$B/accepted" --roster "$B/accepted/roster.json" --verify-only > "$B/receipt"
    assert_eq "success leaves an authoritative verifiable receipt" "$?" 0
    python3 - "$(cat "$B/receipt")" <<'PY'
import json, sys
receipt = json.load(open(sys.argv[1]))
assert receipt['identity']['provider_versions'] == {'claude': '1', 'codex': '1'}
assert [(row['model'], row['effort']) for row in receipt['identity']['core_roster']] == [
    ('gpt-5.6-sol', 'max'), ('gpt-5.6-terra', 'max'), ('opus', 'max'), ('sonnet', 'max')]
PY
    assert_eq "authoritative receipt retains exact model effort and provider versions" "$?" 0
  )
}

test_preflight_cost_static_cache_identity() {
  ( local B="$T/preflight-cost-cache" runner base check
    preflight_cost_fixture "$B" || return
    runner="$B/runner"; check="$B/checker/scripts/rev-contract-check.py"
    base=$(git -C "$B/repo" rev-parse main)
    cat > "$runner" <<'SH'
#!/bin/bash
printf '%s\n' "$1" >> "$COST_CONTRACT_CALLS"
SH
    chmod +x "$runner"
    export REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" COST_CONTRACT_CALLS="$B/contracts"
    static_cost_check() {
      python3 "$check" --root "$B/repo" --base "$base" --session "$B/session" \
        --static-check --static-result "$B/$1.json" > "$B/$1.out" 2> "$B/$1.err"
    }
    static_cost_check first; assert_eq "static phase needs no roster" "$?" 0
    static_cost_check cached; assert_eq "matching static cache is reusable" "$?" 0
    assert_eq "matching static cache launches only one fixture replay" "$(wc -l < "$B/contracts" | tr -d ' ')" 4
    assert_exit "static replay alone earns no authoritative session receipt" 1 \
      bash -c 'compgen -G "$1/contract-pass-*.json"' sh "$B/session"
    assert_exit "static result cannot satisfy authoritative verify-only" 2 \
      python3 "$check" --root "$B/repo" --base "$base" --session "$B/session" \
        --roster "$B/roster.json" --verify-only
    printf '\n' >> "$B/checker/tests/fixtures/provider-contract-codex.ndjson"
    assert_exit "changed fixtures reject an earlier staged static result" 2 \
      python3 "$check" --root "$B/repo" --base "$base" --session "$B/stale" \
        --roster "$B/roster.json" --static-result "$B/first.json"
    static_cost_check fixture; assert_eq "fixture mutation requires fresh replay" "$?" 0
    printf '\n' >> "$B/checker/scripts/lib/review_limits.py"
    static_cost_check script; assert_eq "script mutation requires fresh replay" "$?" 0
    chmod +x "$B/checker/scripts/lib/review_limits.py"
    static_cost_check mode; assert_eq "chmod-only script mutation requires fresh replay" "$?" 0
    printf '\n' >> "$runner"
    static_cost_check runner; assert_eq "runner mutation requires fresh replay" "$?" 0
    REVIEW_COUNCIL_CONTRACT_DEADLINE_SECONDS=299 static_cost_check policy
    assert_eq "execution policy mutation requires fresh replay" "$?" 0
    assert_eq "fixture script mode runner and policy each invalidate the static cache" \
      "$(wc -l < "$B/contracts" | tr -d ' ')" 24
    cat >> "$runner" <<'SH'
if [ "$1" = provider_envelope_replay ]; then
  printf '\n' >> "$COST_MUTATE_SCRIPT"
fi
SH
    COST_MUTATE_SCRIPT="$B/checker/scripts/lib/review_limits.py" static_cost_check changing
    assert_eq "static replay refuses inputs that changed during execution" "$?" 2
    assert_exit "changed execution publishes no reusable static result" 1 test -e "$B/changing.json"
  )
}

test_preflight_cost_unrelated_scope() {
  ( local B="$T/preflight-cost-unrelated" PF runner
    seat_env; PF="$(pf_bin)/rev-preflight.sh"; runner="$B/runner"
    mkrepo "$B/repo" || return
    git -C "$B/repo" checkout -qb feature || return
    printf 'changed\n' > "$B/repo/change.txt"
    cat > "$runner" <<'SH'
#!/bin/bash
printf 'unexpected replay\n' >> "$COST_CONTRACT_CALLS"
exit 7
SH
    chmod +x "$runner"
    export REVIEW_COUNCIL_CONTRACT_RUNNER="$runner" COST_CONTRACT_CALLS="$B/contracts"
    (cd "$B/repo" && "$PF" --write "$B/session") > "$B/out" 2> "$B/err"
    assert_eq "ordinary repository preflight preserves its existing scope" "$?" 0
    assert_exit "ordinary repository launches no contract replay" 1 test -e "$B/contracts"
    assert_exit "ordinary repository still installs the frozen roster" 0 test -f "$B/session/roster.json"
  )
}

test_preflight_cost_probe_isolation() {
  ( local B="$T/preflight-cost-probes"; mkdir -p "$B/bin" "$B/state"
    printf '{"fixture_auth":true}\n' > "$B/state/auth.json"
    printf 'untrusted user config\n' > "$B/state/config.toml"
    cat > "$B/bin/codex" <<'PY'
#!/usr/bin/env python3
import json, os, pathlib, stat, sys
home = pathlib.Path(os.environ['CODEX_HOME'])
auth = home / 'auth.json'
pathlib.Path(os.environ['COST_CODEX_OBSERVED']).write_text(json.dumps({
    'argv': sys.argv[1:], 'home': str(home), 'mode': stat.S_IMODE(home.stat().st_mode),
    'auth': auth.is_file() and auth.read_bytes() == pathlib.Path(os.environ['COST_SOURCE_AUTH']).read_bytes(),
    'config': (home / 'config.toml').exists(), 'api': os.environ.get('OPENAI_API_KEY')}))
print('OK')
PY
    cat > "$B/bin/claude" <<'PY'
#!/usr/bin/env python3
import json, os, pathlib, sys
pathlib.Path(os.environ['COST_CLAUDE_OBSERVED']).write_text(json.dumps({
    'argv': sys.argv[1:], 'environment': dict(os.environ)}))
print('OK')
PY
    chmod +x "$B/bin/codex" "$B/bin/claude"
    PATH="$B/bin:/usr/bin:/bin" CODEX_HOME="$B/state" OPENAI_API_KEY=fixture-openai \
      CLAUDECODE=1 CLAUDE_CODE_SESSION_ID=parent CLAUDE_CODE_OAUTH_TOKEN=fixture-token \
      ANTHROPIC_API_KEY=fixture-anthropic CLAUDE_CODE_USE_BEDROCK=1 CLAUDE_CONFIG_DIR="$B/claude-state" \
      COST_CODEX_OBSERVED="$B/codex.json" COST_CLAUDE_OBSERVED="$B/claude.json" \
      COST_SOURCE_AUTH="$B/state/auth.json" \
      python3 - "$SCRIPTS/lib" "$B" <<'PY'
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import roster
base = pathlib.Path(sys.argv[2])
for adapter, model in [('codex', 'gpt-5.6-terra'), ('claude', 'sonnet')]:
    result = roster.probe_seat({'adapter': adapter, 'model': model, 'effort': 'max'})
    assert result == (None, None, None), result
codex = json.loads((base / 'codex.json').read_text())
args = codex['argv']
assert '--ignore-user-config' in args, args
assert 'project_doc_max_bytes=0' in args, args
assert args[args.index('-m') + 1] == 'gpt-5.6-terra'
assert 'model_reasoning_effort=max' in args
assert pathlib.Path(codex['home']) != base / 'state'
assert codex['mode'] == 0o700 and codex['auth'] and not codex['config'], codex
assert codex['api'] == 'fixture-openai'
assert not pathlib.Path(codex['home']).exists()
claude = json.loads((base / 'claude.json').read_text())
args, environment = claude['argv'], claude['environment']
assert '--exclude-dynamic-system-prompt-sections' in args, args
assert '--disable-slash-commands' in args, args
assert args[args.index('--model') + 1] == 'sonnet'
assert args[args.index('--effort') + 1] == 'max'
assert args[args.index('--setting-sources') + 1] == ''
assert args[args.index('--tools') + 1] == ''
assert not any(name in environment for name in roster.CLAUDE_SESSION_ENV)
assert environment['CLAUDE_CODE_OAUTH_TOKEN'] == 'fixture-token'
assert environment['ANTHROPIC_API_KEY'] == 'fixture-anthropic'
assert environment['CLAUDE_CODE_USE_BEDROCK'] == '1'
assert environment['CLAUDE_CONFIG_DIR'] == str(base / 'claude-state')
PY
    assert_eq "availability probes isolate startup and retain exact settings authentication and provider selection" "$?" 0
  )
}
