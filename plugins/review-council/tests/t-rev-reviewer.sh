# tests for Task 7 - sourced by run-tests.sh
# Static checks on the two Anthropic agent profiles and the external Claude
# adapter. Reviewers receive bounded evidence through native read tools, so the
# profiles and adapter must never expose a general-purpose shell.
test_rev_reviewer() {
  local A="$SK/agents/rev-reviewer.md" S="$SK/agents/rev-reviewer-sonnet.md" C="$SK/scripts/seats.d/claude.sh"
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
    "name,description,model,effort,tools,disallowedTools,maxTurns"
  assert_nogrep "agent does not advertise ignored hook frontmatter" "$A" '^hooks:'

  grep '^tools:' "$A" > "$T/rr-tools.line"
  grep '^disallowedTools:' "$A" > "$T/rr-deny.line"

  assert_grep "tools: contains only receipted native reads" "$T/rr-tools.line" '^tools: Read, Grep$'
  assert_nogrep "Bash withheld from the agent" "$T/rr-tools.line" '(: |, )Bash(,|$)'
  assert_grep "Read granted" "$T/rr-tools.line" '(: |, )Read(,|$)'
  assert_grep "Grep granted" "$T/rr-tools.line" '(: |, )Grep(,|$)'
  assert_nogrep "Glob withheld because it cannot be bounded" "$T/rr-tools.line" '(: |, )Glob(,|$)'
  assert_nogrep "unreceipted LSP is withheld" "$T/rr-tools.line" '(: |, )LSP(,|$)'

  # Write-capable native tools stay denied even though they are absent from the
  # allowlist. This keeps the read-only intent explicit at both boundaries.
  assert_grep "disallowedTools is the spec line" "$T/rr-deny.line" '^disallowedTools: Write, Edit, NotebookEdit$'
  assert_grep "Write denied" "$T/rr-deny.line" '(: |, )Write(,|$)'
  assert_grep "Edit denied" "$T/rr-deny.line" '(: |, )Edit(,|$)'
  assert_grep "NotebookEdit denied" "$T/rr-deny.line" '(: |, )NotebookEdit(,|$)'

  # body: the behavioural rules, and prose that matches what the harness enforces
  assert_grep "body states read-only" "$A" 'You are read-only'
  assert_grep "body names the tools the harness really refuses" "$A" '`Write`, `Edit` and `NotebookEdit` are refused by the harness'
  assert_nogrep "body does not describe shell access" "$A" 'Bash|shell|git diff|git commit'
  assert_grep "body verifies line numbers" "$A" 'verify the line numbers yourself'
  assert_grep "body demands refutation" "$A" 'refute each finding'
  assert_grep "final message must be bare JSON" "$A" 'ONLY the JSON object'

  if [ ! -f "$S" ]; then fail "Sonnet agent file exists" "$S missing"; return; fi
  ok "Sonnet agent file exists"
  assert_grep "Sonnet agent name field" "$S" '^name: rev-reviewer-sonnet$'
  assert_grep "Sonnet model" "$S" '^model: sonnet$'
  assert_grep "Sonnet max effort" "$S" '^effort: max$'
  assert_grep "Sonnet tools contain only receipted native reads" "$S" '^tools: Read, Grep$'
  assert_nogrep "Sonnet profile withholds unreceipted LSP" "$S" '^tools:.*LSP'
  assert_nogrep "Sonnet profile contains no Bash surface" "$S" 'Bash'
  assert_grep "Sonnet has the same read-only rule" "$S" 'You are read-only'
  assert_grep "Sonnet has the same bounded-read rule" "$S" 'limit of at most 240 lines'
  assert_grep "Sonnet final message must be bare JSON" "$S" 'ONLY the JSON object'
  python3 - "$A" "$S" > "$T/rr-agent-parity" <<'PY'
import re, sys

def split(path):
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', open(path).read(), re.S)
    assert match, path
    fields = dict(line.split(': ', 1) for line in match.group(1).splitlines())
    return fields, match.group(2)

opus, opus_body = split(sys.argv[1])
sonnet, sonnet_body = split(sys.argv[2])
assert opus_body == sonnet_body
for key in ('effort', 'tools', 'disallowedTools', 'maxTurns'):
    assert opus[key] == sonnet[key], key
print('same')
PY
  assert_eq "Claude reviewer contracts stay in sync" "$(cat "$T/rr-agent-parity")" "same"

  if [ ! -f "$C" ]; then fail "Claude adapter exists" "$C missing"; return; fi
  ok "Claude adapter exists"
  assert_grep "adapter grants only audited native reads" "$C" \
    "--tools 'Read,Grep'"
  assert_nogrep "adapter contains no Bash tool surface" "$C" 'Bash'
  assert_grep "adapter audits Read before use" "$C" "'matcher': 'Read'"
  assert_grep "adapter audits Grep before use" "$C" "'matcher': 'Grep'"
  assert_grep "adapter audits Read and Grep after use" "$C" \
    "for tool in \('Read', 'Grep'\)"
}
