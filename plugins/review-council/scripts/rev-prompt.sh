#!/bin/bash
# rev-prompt.sh <session-dir> <round> <seat> "<lens>" "<round emphasis>" [--vacuity] [--read-only <list-file>] [--plan <fix-plan-file>] [--pr <title-and-body-file>] [--evidence <manifest>]
# Render one compact reviewer prompt. Provider adapters supply the output schema. Prints the path.
set -u
HERE=$(cd "$(dirname "$0")" && pwd); SCHEMA="$HERE/../schema/findings.schema.json"
[ $# -ge 5 ] || { echo "usage: rev-prompt.sh <session> <round> <seat> <lens> <emphasis> [--vacuity] [--read-only <list-file>] [--plan <fix-plan-file>] [--pr <file>] [--evidence <manifest>]" >&2; exit 1; }
S=$1; N=$2; SEAT=$3; LENS=$4; EMPH=$5; shift 5
OUT="$S/r${N}-${SEAT}.prompt.md"
TMP=""; EVIDENCE_TMP=""; RULES_TMP=""; PATCH_TMP=""; PUBLISHED=0
cleanup_prompt() {
  rm -f -- "${EVIDENCE_TMP:-}" 2>/dev/null || true
  rm -f -- "${RULES_TMP:-}" 2>/dev/null || true
  rm -f -- "${PATCH_TMP:-}" 2>/dev/null || true
  [ "$PUBLISHED" = 1 ] || rm -f -- "${TMP:-}" "$OUT" 2>/dev/null || true
}
die() {
  cleanup_prompt
  echo "rev-prompt: $1" >&2
  exit 1
}
trap cleanup_prompt EXIT
# A failed same-label rerender must not leave the prior prompt looking current.
rm -f -- "$OUT" 2>/dev/null || die "cannot remove stale prompt: $OUT"
VAC=0; RO=""; PLAN=""; PRF=""; EVIDENCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --vacuity) VAC=1; shift;;
    --read-only) RO=${2:?}; shift 2;;
    --plan) PLAN=${2:?}; shift 2;;
    --pr) PRF=${2:?}; shift 2;;
    --evidence) EVIDENCE=${2:?}; shift 2;;
    *) die "unknown argument $1";;
  esac
done
if [ -n "$RO" ] && [ -n "$EVIDENCE" ]; then
  die "--evidence applies to code and plan prompts, not --read-only document prompts"
fi
# scope.env values are single-quoted by rev-preflight.sh (so `source` is safe); strip that quoting here.
unq() {
  local s=$1
  case "$s" in "'"*"'") s=${s#\'}; s=${s%\'}; s=${s//\'\\\'\'/\'};; esac
  printf '%s' "$s"
}
is_present() { [ -e "$1" ] || [ -L "$1" ]; }
require_regular() {
  [ -f "$1" ] && [ -r "$1" ] || die "$2 is not a readable regular file: $1"
}

if [ -n "$PLAN" ]; then
  require_regular "$PLAN" "fix plan"
  [ ! -L "$PLAN" ] || die "fix plan must not be a symlink: $PLAN"
  [ -s "$PLAN" ] || die "fix plan missing or empty: $PLAN"
fi
if [ -n "$PLAN" ]; then
  PLAN_DIR=$(cd "$(dirname "$PLAN")" && pwd -P) || die "cannot resolve fix plan: $PLAN"
  PLAN="$PLAN_DIR/$(basename "$PLAN")"
fi
if [ -n "$RO" ]; then
  require_regular "$RO" "document list"
  [ -s "$RO" ] || die "document list missing or empty: $RO"
else
  require_regular "$S/scope.env" "scope metadata"
  require_regular "$S/files.txt" "changed-file list"
  HAS_UNTRACKED=0
  if is_present "$S/untracked.txt"; then
    require_regular "$S/untracked.txt" "untracked-file list"
    HAS_UNTRACKED=1
  fi
  # Parsed, never sourced: a repo path with a space or a branch name with shell metacharacters must not execute.
  REV_BASE=""; REV_BRANCH=""; REV_DEFAULT=""; REV_ROOT=""; REV_SCOPE=""; k=""; v=""
  while IFS='=' read -r k v || [ -n "$k" ]; do
    case "$k" in
      REV_BASE) REV_BASE=$(unq "$v");;
      REV_BRANCH) REV_BRANCH=$(unq "$v");;
      REV_DEFAULT) REV_DEFAULT=$(unq "$v");;
      REV_ROOT) REV_ROOT=$(unq "$v");;
      REV_SCOPE) REV_SCOPE=$(unq "$v");;
    esac
  done < "$S/scope.env"
  [ -n "$REV_BASE" ] && [ -n "$REV_ROOT" ] && [ -n "$REV_SCOPE" ] || {
    die "$S/scope.env is missing REV_BASE/REV_ROOT/REV_SCOPE; re-run rev-preflight.sh --write $S"; }
fi
if [ -n "$PRF" ]; then require_regular "$PRF" "PR description"; fi
if [ -n "$EVIDENCE" ]; then
  require_regular "$EVIDENCE" "evidence manifest"
  [ ! -L "$EVIDENCE" ] || die "evidence manifest must not be a symlink: $EVIDENCE"
  SESSION_DIR=$(cd "$S" && pwd -P) || die "cannot resolve session directory: $S"
  EVIDENCE_DIR=$(cd "$(dirname "$EVIDENCE")" && pwd -P) || die "cannot resolve evidence manifest: $EVIDENCE"
  EVIDENCE="$EVIDENCE_DIR/$(basename "$EVIDENCE")"
  [ "$EVIDENCE" = "$SESSION_DIR/r${N}-evidence.manifest.json" ] \
    || die "evidence manifest does not match session and prompt label: $EVIDENCE"
fi
HAS_BASELINE=0; HAS_REJECTED=0; HAS_CONTEXT=0
if is_present "$S/baseline.md"; then require_regular "$S/baseline.md" "baseline"; HAS_BASELINE=1; fi
if is_present "$S/rejected.md"; then require_regular "$S/rejected.md" "rejected-findings digest"; HAS_REJECTED=1; fi
if is_present "$S/context.md"; then require_regular "$S/context.md" "decision digest"; HAS_CONTEXT=1; fi
SHOW_PR=0; SHOW_UNTRACKED=0; SHOW_REJECTED=0; SHOW_CONTEXT=0
if [ -n "$PRF" ] && [ -s "$PRF" ]; then SHOW_PR=1; fi
if [ -z "$RO" ] && [ "$HAS_UNTRACKED" = 1 ] && [ -s "$S/untracked.txt" ]; then SHOW_UNTRACKED=1; fi
if [ "$HAS_REJECTED" = 1 ] && [ -s "$S/rejected.md" ]; then SHOW_REJECTED=1; fi
if [ "$HAS_CONTEXT" = 1 ] && [ -s "$S/context.md" ]; then SHOW_CONTEXT=1; fi
INLINE_SCHEMA=1
if is_present "$S/roster.json"; then
  require_regular "$S/roster.json" "roster"
  ADAPTER=$(python3 - "$S/roster.json" "$SEAT" <<'PY' 2>/dev/null
import json, sys
with open(sys.argv[1], encoding='utf-8') as source:
    doc = json.load(source)
if not isinstance(doc, dict) or not isinstance(doc.get('seats'), list):
    raise SystemExit(1)
matches = [item for item in doc['seats']
           if isinstance(item, dict) and item.get('seat') == sys.argv[2]
           and isinstance(item.get('adapter'), str) and item['adapter']]
if not matches:
    raise SystemExit(1)
print(matches[0]['adapter'])
PY
) || die "roster is invalid or does not contain selected seat $SEAT: $S/roster.json"
  INLINE_SCHEMA=0
  case "$ADAPTER" in agent|gemini) INLINE_SCHEMA=1;; esac
fi
if [ "$INLINE_SCHEMA" = 1 ]; then require_regular "$SCHEMA" "findings schema"; fi
check_read() { cat -- "$1" >/dev/null || die "cannot read $2: $1"; }
if [ -n "$RO" ]; then
  check_read "$RO" "document list"
else
  check_read "$S/scope.env" "scope metadata"
  check_read "$S/files.txt" "changed-file list"
  [ "$HAS_UNTRACKED" = 0 ] || check_read "$S/untracked.txt" "untracked-file list"
fi
[ -z "$PLAN" ] || check_read "$PLAN" "fix plan"
[ -z "$PRF" ] || check_read "$PRF" "PR description"
[ -z "$EVIDENCE" ] || check_read "$EVIDENCE" "evidence manifest"
[ "$HAS_BASELINE" = 0 ] || check_read "$S/baseline.md" "baseline"
[ "$HAS_REJECTED" = 0 ] || check_read "$S/rejected.md" "rejected-findings digest"
[ "$HAS_CONTEXT" = 0 ] || check_read "$S/context.md" "decision digest"
[ "$INLINE_SCHEMA" = 0 ] || check_read "$SCHEMA" "findings schema"
if [ -n "$EVIDENCE" ]; then
  EVIDENCE_TMP=$(mktemp "$S/.rev-evidence-fragment.XXXXXX") || die "cannot create evidence fragment in $S"
  python3 "$HERE/rev-evidence.py" render "$EVIDENCE" "$SEAT" > "$EVIDENCE_TMP"
  EVIDENCE_RC=$?
  [ "$EVIDENCE_RC" = 0 ] || die "cannot render evidence for $SEAT from $EVIDENCE"
  [ -s "$EVIDENCE_TMP" ] || die "empty evidence fragment for $SEAT from $EVIDENCE"
  EXPECTED_PLAN=$(sed -n 's/^Immutable plan snapshot: \(.*\) SHA-256 [0-9a-f]*$/\1/p' "$EVIDENCE_TMP")
  EXPECTED_PLAN_HASH=$(sed -n 's/^Immutable plan snapshot: .* SHA-256 \([0-9a-f]*\)$/\1/p' "$EVIDENCE_TMP")
  PLAN_DECLARATIONS=$(printf '%s\n' "$EXPECTED_PLAN" | grep -c .)
  [ "$PLAN_DECLARATIONS" -le 1 ] \
    || die "plan evidence names multiple immutable plan snapshots"
  if [ "$PLAN_DECLARATIONS" = 1 ]; then
    [ -n "$PLAN" ] || die "plan evidence requires --plan with its immutable plan snapshot"
    [ "$PLAN" = "$EXPECTED_PLAN" ] || die "--plan does not match the evidence-bound plan snapshot"
    ACTUAL_PLAN_HASH=$(python3 - "$PLAN" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest())
PY
    ) || die "cannot hash immutable plan snapshot"
    [ "$ACTUAL_PLAN_HASH" = "$EXPECTED_PLAN_HASH" ] || die "immutable plan snapshot hash changed"
  elif [ -n "$PLAN" ]; then
    die "--plan requires a plan evidence manifest"
  fi
  INSTRUCTIONS="$S/r${N}-instructions.md"
  require_regular "$INSTRUCTIONS" "repository instruction snapshot"
  check_read "$INSTRUCTIONS" "repository instruction snapshot"
fi
PATCH_ARTIFACT=""; PATCH_AVAILABLE=0; PATCH_READ_MODE=windows; PATCH_CHUNKS=""; PATCH_CHUNK_BATCH=1
if [ -z "$RO" ]; then
  SESSION_DIR=$(cd "$S" && pwd -P) || die "cannot resolve session directory: $S"
  if [ -n "$EVIDENCE" ]; then
    PATCH_READ_MODE=$(sed -n 's/^Assigned patch read mode: //p' "$EVIDENCE_TMP")
    [ "$PATCH_READ_MODE" = chunks ] || [ "$PATCH_READ_MODE" = windows ] \
      || die "evidence fragment has an invalid assigned patch mode"
    if [ "$PATCH_READ_MODE" = chunks ]; then
      PATCH_CHUNK_BATCH=$(sed -n 's/^Patch chunk batch limit: //p' "$EVIDENCE_TMP")
      [ "$PATCH_CHUNK_BATCH" = 1 ] || [ "$PATCH_CHUNK_BATCH" = 2 ] \
        || die "evidence fragment has an invalid patch chunk batch limit"
      PATCH_ARTIFACT=$(sed -n 's/^Canonical assigned patch: \(.*\) SHA-256 [0-9a-f]* bytes [0-9][0-9]*$/\1/p' "$EVIDENCE_TMP")
      PATCH_CHUNKS=$(sed -n 's/^Assigned patch chunk [0-9][0-9]*\/[0-9][0-9]*: \(.*\) bytes [0-9][0-9]*-[0-9][0-9]* SHA-256 [0-9a-f]*$/\1/p' "$EVIDENCE_TMP")
      [ -n "$PATCH_CHUNKS" ] || die "evidence fragment names no assigned patch chunks"
    else
      PATCH_ARTIFACT=$(sed -n 's/^Read the entire assigned patch in bounded windows of at most 240 lines: //p' "$EVIDENCE_TMP")
    fi
    [ "$(printf '%s\n' "$PATCH_ARTIFACT" | grep -c .)" = 1 ] \
      || die "evidence fragment does not name exactly one assigned patch"
    require_regular "$PATCH_ARTIFACT" "assigned patch"
    [ ! -L "$PATCH_ARTIFACT" ] || die "assigned patch must not be a symlink: $PATCH_ARTIFACT"
    check_read "$PATCH_ARTIFACT" "assigned patch"
    if [ "$PATCH_READ_MODE" = chunks ]; then
      while IFS= read -r patch_chunk; do
        require_regular "$patch_chunk" "assigned patch chunk"
        [ ! -L "$patch_chunk" ] || die "assigned patch chunk must not be a symlink: $patch_chunk"
        check_read "$patch_chunk" "assigned patch chunk"
      done <<EOF
$PATCH_CHUNKS
EOF
    fi
    PATCH_AVAILABLE=1
  else
    PATCH_ARTIFACT="$SESSION_DIR/r${N}-full.patch"
    if is_present "$PATCH_ARTIFACT"; then
      require_regular "$PATCH_ARTIFACT" "frozen patch"
      [ ! -L "$PATCH_ARTIFACT" ] || die "frozen patch must not be a symlink: $PATCH_ARTIFACT"
      PATCH_AVAILABLE=1
    elif git -C "$REV_ROOT" cat-file -e "$REV_BASE^{commit}" 2>/dev/null; then
      PATCH_TMP=$(mktemp "$S/.rev-patch.XXXXXX") || die "cannot create frozen patch temporary in $S"
      python3 - "$HERE/rev-evidence.py" "$S" "$PATCH_TMP" <<'PY'
from pathlib import Path
import runpy
import sys

module = runpy.run_path(sys.argv[1])
repository = module['Repository'](Path(sys.argv[2]).resolve())
base = repository.tree(repository.scope['REV_BASE'])
snapshot, _ = repository.snapshot()
patches, _, _, _ = repository.changes(base, snapshot)
Path(sys.argv[3]).write_bytes(b''.join(patch for _, patch in patches))
PY
      [ "$?" = 0 ] || die "cannot freeze assigned patch from $REV_ROOT"
      [ -s "$PATCH_TMP" ] || die "frozen assigned patch is empty"
      if ! ln -- "$PATCH_TMP" "$PATCH_ARTIFACT" 2>/dev/null; then
        is_present "$PATCH_ARTIFACT" || die "cannot publish frozen assigned patch: $PATCH_ARTIFACT"
        require_regular "$PATCH_ARTIFACT" "concurrently published frozen patch"
        [ ! -L "$PATCH_ARTIFACT" ] \
          || die "concurrently published frozen patch must not be a symlink: $PATCH_ARTIFACT"
      fi
      rm -f -- "$PATCH_TMP"; PATCH_TMP=""
      PATCH_AVAILABLE=1
    fi
    if [ "$PATCH_AVAILABLE" = 1 ]; then
      check_read "$PATCH_ARTIFACT" "frozen patch"
    else
      PATCH_ARTIFACT=""
    fi
  fi
fi
if [ -z "$RO" ] && [ -z "$EVIDENCE" ]; then
  RULES_TMP=$(mktemp "$S/.rev-repo-rules.XXXXXX") || die "cannot create repository instruction fragment in $S"
  python3 - "$REV_ROOT" "$S/files.txt" > "$RULES_TMP" <<'PY'
from pathlib import Path, PurePosixPath
import stat
import sys

root = Path(sys.argv[1]).resolve()
paths = [line for line in Path(sys.argv[2]).read_text().splitlines() if line]
directories = {root}
for name in paths:
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise SystemExit('changed path escapes repository: ' + name)
    current = root
    for part in relative.parent.parts:
        if part in ('', '.'):
            continue
        candidate = current / part
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            break
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            break
        current = candidate
        directories.add(current)
rules = []
for directory in sorted(directories, key=lambda path: (len(path.relative_to(root).parts), path.as_posix())):
    override = directory / 'AGENTS.override.md'
    ordinary = directory / 'AGENTS.md'
    chosen = None
    for candidate in (override, ordinary):
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise SystemExit('repository instruction is not a regular file: ' + str(candidate))
        chosen = candidate
        break
    if chosen is None:
        continue
    rules.append(chosen)
if rules:
    print('## Applicable repository instructions')
    print('These files are embedded so provider rule discovery stays disabled. Apply each file only to paths below its directory; a deeper file wins on conflict.')
    print()
    for path in rules:
        print('### `' + path.relative_to(root).as_posix() + '`')
        print(path.read_text(), end='' if path.read_bytes().endswith(b'\n') else '\n')
        print()
PY
  [ "$?" = 0 ] || die "cannot collect applicable repository instructions from $REV_ROOT"
fi
lens_one() {
  case "$1" in
    correctness)     echo "Logic errors, off-by-one, wrong operators, inverted conditions, unreachable code.";;
    security)        echo "Injection, authz/authn gaps, secrets, unsafe deserialization, path traversal, SSRF, trust-boundary violations.";;
    edge-cases)      echo "Empty/null/zero, boundaries, Unicode, huge inputs, partial failure.";;
    error-handling)  echo "Swallowed errors, wrong error types, missing cleanup, misleading messages.";;
    concurrency)     echo "Races, deadlocks, unsafe shared state, cancellation, ordering assumptions.";;
    resources)       echo "Leaks, unclosed handles, unbounded growth, missing backpressure.";;
    api-contract)    echo "Breaking changes, inconsistent signatures, bad defaults, leaky abstractions, compatibility.";;
    data-state)      echo "Migrations, serialization compatibility, invariants, idempotency.";;
    performance)     echo "N+1s, needless allocation, hot-path cost, pathological complexity.";;
    tests)           echo "Missing cases, tests that cannot fail, over-mocking, fixture coupling.";;
    observability)   echo "Missing or noisy logs, unactionable errors, absent metrics.";;
    readability)     echo "Naming, dead code, misleading comments, structure.";;
    red-team)        echo "Assume the change is wrong and try to prove it. Adversarial reading: find the input, timing, or state that breaks it.";;
    regression)      echo "Re-review the fixes made in prior rounds and the cumulative diff as a whole; look for fixes that introduced new defects.";;
    maintainability) echo "Abstraction quality, file growth, spaghetti conditionals, logic in the wrong layer.";;
    simplicity)      echo "Could this change be smaller? The burden of proof is on every new mechanism, not on you: do not defend the design; make each piece justify itself against the simplest thing that serves its named consumer. Before judging correctness, ask, and search the tree for the answer: (1) Reuse: every comment of the form \"done by hand because X\" or \"until upstream does Y\" - open the pinned dependency source (cargo registry, node_modules .d.ts) and check whether X or Y still holds on the version this change pins; a dependency bumped in this same change or stack is the first place to look, so diff its public API for the feature area. (2) Native features: for every hand-rolled mechanism - a sequence computed as MAX plus one, a cursor codec, a retry loop, a serialization, a middleware stack - ask whether the engine, framework or standard library already provides it (an autoincrement column, an iterator instead of a collected copy, the framework router); name the feature. (3) Proportionality: for every new endpoint, transport, abstraction or option, name its consumer from the change description and ask whether the machinery fits that consumer - a browser or a script does not need a typed RPC framework with reflection, tracing layers and a timeout; a client that reads a whole collection in one sitting does not need pagination; a demo does not need a policy hook. (4) One value, one implementation: every new optional parameter, flag or config field - list every production caller; if they all pass the same value it is not a parameter. Every new trait, strategy parameter, associated type or generic - count the implementations in the change; if there is one, or none uses the freedom, replace it with the concrete type and delete the generic it forces onto every signature and error. Every wrapper or helper - does it do more than forward to an existing one plus one injected argument? (5) Unreleased history: for every migration, compatibility shim, backfill or deprecation path, check whether the thing it migrates from was created on this same unreleased branch or version; if so, fold it into the original and delete the shim and its legacy-data tests. (6) Surface: for every new public item, who outside this repository calls it, and does the file convention re-export types from private modules rather than expose module paths? (7) Tests: every test-matrix axis and cross-implementation vector test - after the sibling changes, does the axis have more than one value, is there more than one implementation? Every test helper and case - is it implied by a sibling in the same module? Every divergence test - can the two sources still differ in the new data flow? Consistency with sibling code is not a justification: a mechanism the siblings use is still unjustified here when this consumer does not need it. When a generic or associated type is forced by one bound, ask which of the two should collapse - the container or the error - and prefer collapsing the one no implementation varies. Name the existing symbol, its location and version for every reuse you propose, and the consumer for every proportionality finding. A scope cut is a finding too, marked as such - the author decides it.";;
    clean-room)      echo "Do NOT read the diff first. Read the change description above (and, failing that, the changed-file list and the names of the tests it adds) and write down for yourself the smallest design that serves the named consumer: which existing types, methods, endpoints and framework or engine features it would use, and what it would not add. Only then read the diff. Report as findings every place the change is larger than your design, each naming the smaller design concretely (existing symbol, location, version) and what the extra machinery costs; where the change is as small as your design or smaller, say so. Put your five-line design in the summary.";;
    plan-completeness) echo "The plan states rules. For each rule, verify its list of sites, arms, realms, callers and copies by searching the code yourself; list every one the plan misses, with file:line. An incomplete list is the defect this gate exists to catch.";;
    plan-soundness)  echo "For each rule, find the case where applying it breaks behaviour or an invariant, and any two rules that interact or contradict. Read the code the rule touches, not just the plan.";;
    plan-simplicity) echo "For each rule, look for a simpler fix: an existing helper, type, hook, or path in this repository that already does the job (name it with its location), a smaller change with the same effect, or two rules that should be one. Prefer reuse over new mechanism.";;
    plan-tests)      echo "For each rule, decide whether the named test would fail without the fix and pass with it. If it would not, name the test that would. A rule with no failing test is unverified.";;
    correctness-boundaries) echo "Check logic, boundary inputs, partial failure, cleanup, and error contracts. Trace only the consumers needed to prove or refute a concrete failure.";;
    security-state-api) echo "Check trust boundaries, authorization, durable-state invariants, serialization, idempotency, compatibility, and public API behavior.";;
    concurrency-resources-performance) echo "Check ordering, cancellation, shared state, cleanup, backpressure, leaks, and pathological hot-path cost.";;
    tests-observability-maintenance-regression) echo "Check whether tests can fail for the named behavior, whether failures are diagnosable, whether the structure remains maintainable, and whether prior fixes introduced regressions.";;
    *)               echo "$1";;
  esac
}
lens_text() {
  local remaining=$1 bundle
  while :; do
    case "$remaining" in
      *+*) bundle=${remaining%%+*}; remaining=${remaining#*+};;
      *) bundle=$remaining; remaining="";;
    esac
    [ -n "$bundle" ] || { echo "$1"; return; }
    lens_one "$bundle"
    [ -n "$remaining" ] || return 0
  done
}
render_prompt() (
  set -e
  set -o pipefail
  if [ -z "$RO" ]; then
    cat <<'EOC'
# Reviewer contract
You are one independent reviewer on a read-only multi-model code review panel. Substantiate every claim yourself, finish every assigned check, combine sibling sites under one root cause, and return no more than five distinct findings.

- Read only inside the repository, the named review-session artifacts, and explicitly named pinned dependency roots. Do not read user or global rules, memories, skills, caches, other checkouts, or unrelated files.
- Never edit files or run a command that changes the repository or its dependencies.
- Clean-room ordering: Do NOT read the diff first. For a clean-room lens, write the smallest design before any patch or source read. For every other lens, begin with assigned-hunk discovery.

## Bounded evidence protocol
1. After any required clean-room design, read every byte of the assigned patch using its rendered mode. In chunk mode, obey the rendered patch chunk batch limit, reading only consecutive chunks in exact order and in full. In window mode, use consecutive windows of at most 240 lines until coverage is complete. Then read every listed source-context packet in full before source expansion. Treat each packet entry as exact original source at its recorded path and one-based lines.
2. Locate the enclosing symbol or named section, then search definitions, direct references, related tests, and config gates. When `Source read required` is true, resolve every relevant omission with a bounded original-source read.
3. Read the smallest useful line window around each match. Every source Read call must set an explicit one-based `offset` and a `limit` of at most 240 lines. Every Grep or search call must set a result limit of at most 80. The rendered prompt, compact evidence index, assigned patch chunks, and listed source-context packets are the only full-read exceptions.
4. Shell commands that print source, diffs, or logs must select at most 240 lines. Shell search commands must select at most 80 results. Use byte-preserving `sed -n 'START,ENDp' -- FILE` for source windows. Do not use `nl -ba ... | sed`; its added prefixes change the bytes, and a rejected call invalidates the audit.
5. Batch independent bounded windows discovered from the evidence index into one tool turn, with a 32 KiB combined output ceiling. Claude can issue parallel Read or Grep calls; shell-based seats can combine independent bounded `sed` or `rg` queries.
6. Expand to another bounded block, file, or pinned dependency only to answer a concrete question that could prove or refute a finding. Name the concrete symbol or invariant question first and record the next bounded window in the tool call.
7. Stop that evidence path when the question is answered. Finish every assigned check and expand again when evidence is insufficient; never treat the navigation index or a summary as proof.

## Evidence and output
- Every finding names a file and lines you opened yourself. Its cited range must intersect a source-context packet range you opened or an audited original source range from a bounded source read. Search results, navigation summaries, and patches do not establish citation coverage. `evidence` states what the source shows.
- Try to refute each candidate. `confidence` is your honest probability that it remains real.
- P0: incorrect behavior, security hole, data loss, or crash. P1: reachable bug, edge case, or broken contract. P2: maintainability, performance, missing test, or unclear API. P3: trivial style, naming, or comment issue.
- One strong finding beats several weak ones. No style findings unless P3 and trivial.
- `suggested_fix` states the general rule, every sibling site or branch it covers, and the test that would fail without it.
- Return only the JSON object required by the runner. If the change is sound, return an empty `findings` array and say so in `summary`.
EOC
    echo
    echo "## Review assignment"
  else
    echo "You are one of several independent reviewers on a multi-model review panel. Others review the same documents on different models; your value is what you can substantiate yourself. Follow the scope and lens below, combine sibling issues under one root cause, and return no more than five distinct findings."
    echo
  fi
  case "$SEAT" in grok*) echo "Follow the lens ordering below before using tools. Inspect the assigned patch and source before answering. Do not write, edit, or run anything that modifies the repository."; echo;; esac
  echo "## Scope"
  if [ -n "$RO" ]; then
    echo "Documents to review (read them in full):"; sed 's/^/- /' "$RO"; echo
    echo "In findings, \`file\` is the document path and \`line_start\`/\`line_end\` are lines in that document."; echo
  else
    echo "Repository: $REV_ROOT"
    echo "Base commit: $REV_BASE (branch \`$REV_BRANCH\`, default branch \`$REV_DEFAULT\`)"
    if [ "$PATCH_AVAILABLE" = 1 ]; then
      if [ "$PATCH_READ_MODE" = chunks ]; then
        echo "Exact frozen assigned patch identity: $PATCH_ARTIFACT"
        if [ -n "$PLAN" ]; then
          echo "Evidence order: study the full inline immutable plan snapshot first. Then use your native file-read tool (Read or read_file) to read at most $PATCH_CHUNK_BATCH consecutive assigned patch chunks per tool turn, once in the rendered order and in full, before source-context packets or source expansion."
        else
          echo "First evidence action after any required clean-room design: use your native file-read tool (Read or read_file) to read at most $PATCH_CHUNK_BATCH consecutive assigned patch chunks per tool turn, once in the rendered order and in full, before source-context packets or source expansion."
        fi
      else
        echo "Exact frozen assigned patch: $PATCH_ARTIFACT"
        if [ -n "$PLAN" ]; then
          echo "Evidence order: study the full inline immutable plan snapshot first. Then use your native file-read tool (Read or read_file) to read the exact frozen assigned patch $PATCH_ARTIFACT in consecutive windows of at most 240 lines before source expansion."
        else
          echo "First evidence action after any required clean-room design: use your native file-read tool (Read or read_file) to read the exact frozen assigned patch $PATCH_ARTIFACT in consecutive windows of at most 240 lines, starting at line 1."
        fi
      fi
      echo "Do not generate a live diff or use a shell command to produce the patch."
    fi
    if [ -n "$EVIDENCE" ]; then
      echo "Prepared review scope:"
      cat "$EVIDENCE_TMP"
    else
      if [ "$PATCH_AVAILABLE" = 1 ]; then
        echo "The frozen patch contains committed, staged, unstaged, and listed untracked changes against the pinned base."
      else
        case "$REV_SCOPE" in
          uncommitted) echo "Produce the diff yourself: \`git diff\` and \`git diff --cached\` in $REV_ROOT, plus \`git status --porcelain\` for untracked files.";;
          branch)      echo "Produce the diff yourself: \`git diff $REV_BASE\` in $REV_ROOT (committed, staged and unstaged work, all against the pinned base).";;
          *)           echo "Produce the diff yourself: \`git diff $REV_BASE -- $REV_SCOPE\` in $REV_ROOT.";;
        esac
      fi
      echo "Changed files:"
      if [ "$SHOW_UNTRACKED" = 1 ]; then
        awk 'NR==FNR{u[$0]=1;next} {printf "- %s%s\n", $0, ($0 in u ? " (untracked)" : "")}' "$S/untracked.txt" "$S/files.txt" 2>/dev/null
        if [ "$PATCH_AVAILABLE" = 0 ]; then
          echo
          echo "Files marked (untracked) do not appear in \`git diff\`; read them in full."
        fi
      else
        sed 's/^/- /' "$S/files.txt" 2>/dev/null
      fi
    fi
    echo
  fi
  if [ -z "$RO" ]; then
    if [ -n "$EVIDENCE" ] && [ -s "$INSTRUCTIONS" ]; then
      echo "## Applicable repository instructions"
      echo "These instructions come from the manifest-bound repository snapshot and are embedded because provider rule discovery is disabled."
      echo
      cat "$INSTRUCTIONS"
      echo
    elif [ -s "$RULES_TMP" ]; then
      cat "$RULES_TMP"
    fi
  fi
  if [ "$SHOW_PR" = 1 ]; then
    echo "## Change description (from the author)"; cat "$PRF"; echo
    echo "The consumer and purpose named above are the yardstick for proportionality: machinery the change adds beyond what that consumer needs is a finding."; echo
  fi
  if [ "${REV_SEAT_OFFLINE:-}" = 1 ]; then
    echo "## Offline review"
    if [ -n "${REV_DEPS_DIR:-}" ]; then
      echo "Judge only what is in the repository above and in the pinned third-party dependency sources linked under $REV_DEPS_DIR (one directory per pinned crate, taken from the lockfile). That view is the only dependency source you may read: never the cargo registry itself, which also holds other versions of the crates this repository publishes."
    else
      echo "Judge only what is in the repository above and in the pinned dependency sources already on this machine (the cargo registry, node_modules). Do not read published versions of packages that this repository itself publishes, and do not search the whole registry; open only the specific crates or packages this repository pins."
    fi
    echo "Do not use the network, web search, package downloads, or any other checkout of this repository on this machine; do not fetch. Do not read build directories outside the repository (a global CARGO_TARGET_DIR, the target or node_modules directory of another checkout): they hold artifacts of other states of this code. If you cannot establish something from those sources, say so instead of looking it up."; echo
  fi
  if [ -n "$PLAN" ]; then
    echo "## Immutable fix plan snapshot - nothing in it is implemented yet"
    echo "Source: \`$PLAN\` (source line numbers shown below)"
    echo "This snapshot clusters accepted findings into rules, sites, invariants, and falsifiable tests. Attack it before code is written and verify its claims against the repository. For a defect in the plan, use \`$(basename "$PLAN")\` as the finding file; use a code path when the plan missed code. A sound plan returns an empty findings array."; echo
    if [ -n "$EVIDENCE" ]; then
      echo "For every cluster, run its rendered required sibling-site search from the repository root with the bounded search limit, and prove every rendered required cluster source location from an assigned packet or bounded original-source read. Missing one cluster invalidates the panel."; echo
    fi
    nl -ba "$PLAN"; echo
  fi
  echo "## Your lens this round: $LENS"; lens_text "$LENS"; echo; echo "Round emphasis: $EMPH"; echo
  if [ "$HAS_BASELINE" = 1 ]; then
    echo "## Baseline (before any review fix)"; cat "$S/baseline.md"; echo
    echo "Anything already failing above is pre-existing, not a finding of this change."; echo
  fi
  echo "## Already rejected - do not resurface these"
  if [ "$SHOW_REJECTED" = 1 ]; then cat "$S/rejected.md"; else echo "(none yet)"; fi; echo
  if [ "$SHOW_CONTEXT" = 1 ]; then
    echo "## Prior decision digest"
    cat "$S/context.md"; echo
    echo "Use this digest only to avoid duplicate work. Never infer that an uncited area was already reviewed."; echo
  fi
  if [ "$VAC" = 1 ]; then
    cat <<'EOV'
## Vacuity check (tests are touched)
Check every assertion the diff adds or edits for VACUITY: would it still pass if the behaviour it names were deleted? For each new or changed test, name the production change that would make it fail; report any test that has none as a P1 with lens `tests`. Watch for: `.all()`/`.every()` over a possibly-empty query; a before/after measurement read from an accessor that returns a copy; a test recomputing its expected value via the path under test; `expect.anything()` in the slot holding the new argument; a success path that never executes; arguments in the wrong order so the test never ran.

EOV
  fi
  echo "## Runner schema"
  if [ "$INLINE_SCHEMA" = 1 ]; then
    echo '```json'; cat "$SCHEMA"; echo '```'
  fi
)
TMP=$(mktemp "$S/.rev-prompt.XXXXXX") || die "cannot create temporary prompt in $S"
render_prompt > "$TMP"
RENDER_RC=$?
[ "$RENDER_RC" = 0 ] || die "cannot render prompt: $OUT"
WORDS=$(wc -w < "$TMP" | tr -d ' ') || die "cannot measure prompt: $OUT"
if [ -n "$PLAN" ]; then KIND=plan; LIMIT=3000; else KIND=code; LIMIT=1800; fi
if [ "$WORDS" -gt "$LIMIT" ]; then
  echo "rev-prompt: WARNING: $KIND prompt has $WORDS words and exceeds $LIMIT words" >&2
fi
mv -f -- "$TMP" "$OUT" || die "cannot publish prompt: $OUT"
TMP=""; PUBLISHED=1
echo "$OUT"
