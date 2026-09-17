# ripgrep resolution for plan-search replay, and session input lock error labels. Sourced by run-tests.sh.
test_ripgrep_resolution_order() {
  ( local B="$T/ripgrep-resolution"; mkdir -p "$B/path" "$B/embedded" "$B/impostor"
    printf '#!/bin/sh\necho "ripgrep 14.1.1"\n' > "$B/path/rg"
    printf '#!/bin/sh\necho "ripgrep 14.1.1 (rev test)"\necho features\n' > "$B/embedded/claude"
    printf '#!/bin/sh\necho "2.1.0 (Claude Code)"\n' > "$B/impostor/claude"
    chmod +x "$B/path/rg" "$B/embedded/claude" "$B/impostor/claude"
    python3 - "$SCRIPTS/rev-evidence.py" "$B" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('evidence', sys.argv[1])
evidence = importlib.util.module_from_spec(spec); spec.loader.exec_module(evidence)
root = sys.argv[2]; empty = root + '/empty'
missing = 'ripgrep binary not found on PATH; set REV_RG to a ripgrep executable'
def refused(environment):
    try:
        evidence.ripgrep_executable(environment)
    except ValueError as error:
        return str(error)
    return None
embedded = root + '/embedded/claude'
assert evidence.ripgrep_executable({'REV_RG': '/opt/rg', 'PATH': root + '/path',
                                    'CLAUDE_CODE_EXECPATH': embedded}) == '/opt/rg'
assert evidence.ripgrep_executable({'PATH': root + '/path',
                                    'CLAUDE_CODE_EXECPATH': embedded}) == root + '/path/rg'
assert evidence.ripgrep_executable({'PATH': empty, 'CLAUDE_CODE_EXECPATH': embedded}) == embedded
assert refused({'PATH': empty, 'CLAUDE_CODE_EXECPATH': root + '/impostor/claude'}) == missing
assert refused({'PATH': empty, 'CLAUDE_CODE_EXECPATH': root + '/absent'}) == missing
assert refused({'PATH': empty}) == missing
PY
    assert_eq "ripgrep resolves REV_RG, then PATH, then a verified embedded ripgrep" "$?" 0
  )
}

test_plan_prepare_reports_missing_ripgrep() {
  ( local R="$T/plan-rg-root" S="$T/plan-rg-session" B="$T/plan-rg-bin"
    mkrepo "$R"; mkdir -p "$R/src" "$R/tests" "$S" "$B/git-only"
    printf 'export function runService() { return 1; }\n' > "$R/src/service.ts"
    printf 'import { runService } from "../src/service";\ntest("service", () => runService());\n' \
      > "$R/tests/service.test.ts"
    git -C "$R" add . && git -C "$R" commit -qm "plan base"
    local base; base=$(git -C "$R" rev-parse HEAD)
    printf 'export function runService() { return 2; }\n' > "$R/src/service.ts"
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/service.ts\n' > "$S/files.txt"
    : > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$S/roster.json"
    cat > "$S/fix-plan.md" <<'EOF'
## C-01 - keep service results stable
Findings: F-001 (P1)
Rule: Return the service result exactly once at every entry.
Sites: src/service.ts:1 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'runService' .)
Must not: Change unrelated exports.
Test: tests/service.test.ts:1-2
Interacts with: none.
EOF
    ln -s "$(command -v git)" "$B/git-only/git"
    cat > "$B/rg" <<'SH'
#!/bin/sh
printf '%s\n' "$@" > "$PLAN_RG_ARGS"
printf './src/service.ts\0001:export function runService() { return 2; }\n'
SH
    chmod +x "$B/rg"
    local python plan_hash
    python=$(command -v python3)
    plan_hash=$("$python" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$S/fix-plan.md")
    local prepare=("$python" "$SCRIPTS/rev-evidence.py" prepare "$S" 1p --phase plan
      --plan "$S/fix-plan.md" --plan-sha256 "$plan_hash" --full-seat sol
      --assignment sol=plan-completeness --assignment terra=plan-soundness
      --assignment opus=plan-simplicity --assignment sonnet=plan-tests)
    env -u REV_RG -u CLAUDE_CODE_EXECPATH PATH="$B/git-only" REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 \
      "${prepare[@]}" > "$B/missing.out" 2> "$B/missing.err"
    assert_eq "plan prepare without ripgrep is refused" "$?" 2
    assert_eq "the refusal names ripgrep and REV_RG, not the session lock" "$(cat "$B/missing.err")" \
      'evidence: ripgrep binary not found on PATH; set REV_RG to a ripgrep executable'
    assert_exit "a refused prepare writes no manifest" 1 test -e "$S/r1p-evidence.manifest.json"
    env -u CLAUDE_CODE_EXECPATH PATH="$B/git-only" REV_RG="$B/rg" PLAN_RG_ARGS="$B/rg.args" \
      REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 "${prepare[@]}" > "$B/rev-rg.out" 2> "$B/rev-rg.err"
    assert_eq "plan prepare with REV_RG succeeds" "$?" 0
    assert_exit "REV_RG prepare writes the plan manifest" 0 test -f "$S/r1p-evidence.manifest.json"
    assert_eq "REV_RG runs the canonical plan search" "$(tr '\n' ' ' < "$B/rg.args")" \
      "--hidden --no-ignore --glob !.git/** --null -n -- runService . "
  )
}

test_session_input_lock_keeps_body_errors() {
  ( local S="$T/session-lock-body"; mkdir -p "$S"
    python3 - "$SCRIPTS/lib/session_inputs.py" "$S" <<'PY'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('session_inputs', sys.argv[1])
session_inputs = importlib.util.module_from_spec(spec); spec.loader.exec_module(session_inputs)
failure = FileNotFoundError(2, 'No such file or directory', 'rg')
try:
    with session_inputs.session_input_lock(pathlib.Path(sys.argv[2])):
        raise failure
except FileNotFoundError as error:
    assert error is failure
else:
    raise AssertionError('body error was swallowed or relabelled')
lock = pathlib.Path(sys.argv[2]) / '.session-inputs.lock'
lock.unlink(); lock.mkdir()
try:
    with session_inputs.session_input_lock(pathlib.Path(sys.argv[2])):
        raise AssertionError('an unsafe lock entered the body')
except session_inputs.SessionInputsError as error:
    assert 'session input lock' in str(error), error
PY
    assert_eq "the session input lock relabels only its own failures" "$?" 0
  )
}
