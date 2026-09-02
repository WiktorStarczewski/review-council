# tests for Task 7 — sourced by run-tests.sh
# Static checks on the rev-reviewer agent file. They lock in the ONE frontmatter
# shape this build's agent loader actually resolves the way the file's prose says
# (traced in the shipped claude binary, see the Task 7 report, fix round 3):
#   * `tools:` entries resolve by BARE tool name — rule content is kept only for
#     Agent(...), so `Bash(git diff:*)` grants the whole unscoped Bash tool.
#   * every `disallowedTools` entry registers its BARE name in the deny set, and
#     denies are applied to the pool BEFORE the allowlist is matched, so
#     `Bash(git commit:*)` removes Bash entirely and the seat spawns shell-less
#     and silent (the zero-tool guard only fires when NOTHING resolves).
# Hence: bare `Bash` in tools:, bare write tools in disallowedTools, and no
# `Bash(...)` rule anywhere in the frontmatter. Nothing here can prove harness
# semantics at runtime — that is the live smoke the brief's Step 2 defers.
test_rev_reviewer() {
  local A="$HOME/.claude/agents/rev-reviewer.md"
  if [ ! -f "$A" ]; then fail "agent file exists" "$A missing"; return; fi
  ok "agent file exists"
  assert_grep "name field" "$A" '^name: rev-reviewer$'
  assert_grep "opus model" "$A" '^model: opus$'
  assert_grep "max effort" "$A" '^effort: max$'
  assert_grep "maxTurns 80" "$A" '^maxTurns: 80$'

  python3 - "$A" > "$T/rr-keys" <<'PY'
import re, sys
m = re.match(r'^---\n(.*?)\n---\n', open(sys.argv[1]).read(), re.S)
print(",".join(l.split(":", 1)[0] for l in m.group(1).split("\n") if l and not l[0].isspace()) if m else "NO-FRONTMATTER")
PY
  assert_eq "frontmatter keys, in spec order, nothing extra" "$(cat "$T/rr-keys")" \
    "name,description,model,effort,tools,disallowedTools,maxTurns,hooks"
  assert_grep "PreToolUse guard hook on Bash" "$A" 'readonly-bash-guard.py'
  assert_grep "hook matcher is Bash" "$A" '^    - matcher: Bash$'

  grep '^tools:' "$A" > "$T/rr-tools.line"
  grep '^disallowedTools:' "$A" > "$T/rr-deny.line"

  # the grant: spec-verbatim, and Bash must really be in it — rev-prompt.sh tells
  # the seat to produce the diff itself with `git diff`, so a Bash-less seat is broken
  assert_grep "tools: is the spec line" "$T/rr-tools.line" '^tools: Read, Grep, Glob, Bash, LSP$'
  assert_grep "Bash granted (seat runs git diff)" "$T/rr-tools.line" '(: |, )Bash(,|$)'
  assert_grep "Read granted" "$T/rr-tools.line" '(: |, )Read(,|$)'
  assert_grep "Grep granted" "$T/rr-tools.line" '(: |, )Grep(,|$)'
  assert_grep "Glob granted" "$T/rr-tools.line" '(: |, )Glob(,|$)'
  assert_grep "LSP granted" "$T/rr-tools.line" '(: |, )LSP(,|$)'

  # the fence: bare write tools only. A Bash(...) rule on either line is a bug —
  # in tools: it silently grants unscoped Bash, in disallowedTools: it silently
  # takes Bash away entirely.
  assert_grep "disallowedTools is the spec line" "$T/rr-deny.line" '^disallowedTools: Write, Edit, NotebookEdit$'
  assert_grep "Write denied" "$T/rr-deny.line" '(: |, )Write(,|$)'
  assert_grep "Edit denied" "$T/rr-deny.line" '(: |, )Edit(,|$)'
  assert_grep "NotebookEdit denied" "$T/rr-deny.line" '(: |, )NotebookEdit(,|$)'
  assert_nogrep "no scoped Bash rule in tools: (rule content is dropped)" "$T/rr-tools.line" 'Bash\('
  assert_nogrep "no scoped Bash rule in disallowedTools: (would strip Bash)" "$T/rr-deny.line" 'Bash\('
  assert_nogrep "no bare Bash deny (would strip Bash)" "$T/rr-deny.line" '(: |, )Bash(,|$)'

  # body: the behavioural rules, and prose that matches what the harness enforces
  assert_grep "body states read-only" "$A" 'You are read-only'
  assert_grep "body forbids git commit in prose too" "$A" 'no `git commit`'
  assert_grep "body names the tools the harness really refuses" "$A" '`Write`, `Edit` and `NotebookEdit` are refused by the harness'
  assert_grep "body admits the shell is unscoped" "$A" 'the shell is not scoped'
  assert_nogrep "body does not claim a harness-scoped shell" "$A" 'refused by the harness itself'
  assert_grep "body verifies line numbers" "$A" 'verify the line numbers yourself'
  assert_grep "body demands refutation" "$A" 'refute each finding'
  assert_grep "final message must be bare JSON" "$A" 'ONLY the JSON object'
}
