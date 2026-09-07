#!/bin/bash
# rev-prompt.sh <session-dir> <round> <seat> "<lens>" "<round emphasis>" [--vacuity] [--read-only <list-file>] [--plan <fix-plan-file>] [--pr <title-and-body-file>]
# Render <session>/r<N>-<seat>.prompt.md from scope.env, files.txt, untracked.txt, baseline.md, rejected.md and the schema. Prints the path.
set -u
HERE=$(cd "$(dirname "$0")" && pwd); SCHEMA="$HERE/../schema/findings.schema.json"
[ $# -ge 5 ] || { echo "usage: rev-prompt.sh <session> <round> <seat> <lens> <emphasis> [--vacuity] [--read-only <list-file>] [--plan <fix-plan-file>] [--pr <file>]" >&2; exit 1; }
S=$1; N=$2; SEAT=$3; LENS=$4; EMPH=$5; shift 5
VAC=0; RO=""; PLAN=""; PRF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --vacuity) VAC=1; shift;;
    --read-only) RO=${2:?}; shift 2;;
    --plan) PLAN=${2:?}; shift 2;;
    --pr) PRF=${2:?}; shift 2;;
    *) echo "rev-prompt: unknown argument $1" >&2; exit 1;;
  esac
done
# scope.env values are single-quoted by rev-preflight.sh (so `source` is safe); strip that quoting here.
unq() {
  local s=$1
  case "$s" in "'"*"'") s=${s#\'}; s=${s%\'}; s=${s//\'\\\'\'/\'};; esac
  printf '%s' "$s"
}
if [ -n "$PLAN" ] && [ ! -s "$PLAN" ]; then echo "rev-prompt: fix plan missing or empty: $PLAN" >&2; exit 1; fi
if [ -n "$RO" ]; then
  [ -s "$RO" ] || { echo "rev-prompt: document list missing or empty: $RO" >&2; exit 1; }
else
  [ -f "$S/scope.env" ] || { echo "rev-prompt: $S/scope.env missing — run rev-preflight.sh --write $S first" >&2; exit 1; }
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
    echo "rev-prompt: $S/scope.env is missing REV_BASE/REV_ROOT/REV_SCOPE — re-run rev-preflight.sh --write $S" >&2; exit 1; }
fi
OUT="$S/r${N}-${SEAT}.prompt.md"
lens_text() {
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
    simplicity)      echo "Could this change be smaller? The burden of proof is on every new mechanism, not on you: do not defend the design; make each piece justify itself against the simplest thing that serves its named consumer. Before judging correctness, ask, and search the tree for the answer: (1) Reuse: every comment of the form \"done by hand because X\" or \"until upstream does Y\" — open the pinned dependency source (cargo registry, node_modules .d.ts) and check whether X or Y still holds on the version this change pins; a dependency bumped in this same change or stack is the first place to look, so diff its public API for the feature area. (2) Native features: for every hand-rolled mechanism — a sequence computed as MAX plus one, a cursor codec, a retry loop, a serialization, a middleware stack — ask whether the engine, framework or standard library already provides it (an autoincrement column, an iterator instead of a collected copy, the framework router); name the feature. (3) Proportionality: for every new endpoint, transport, abstraction or option, name its consumer from the change description and ask whether the machinery fits that consumer — a browser or a script does not need a typed RPC framework with reflection, tracing layers and a timeout; a client that reads a whole collection in one sitting does not need pagination; a demo does not need a policy hook. (4) One value, one implementation: every new optional parameter, flag or config field — list every production caller; if they all pass the same value it is not a parameter. Every new trait, strategy parameter, associated type or generic — count the implementations in the change; if there is one, or none uses the freedom, replace it with the concrete type and delete the generic it forces onto every signature and error. Every wrapper or helper — does it do more than forward to an existing one plus one injected argument? (5) Unreleased history: for every migration, compatibility shim, backfill or deprecation path, check whether the thing it migrates from was created on this same unreleased branch or version; if so, fold it into the original and delete the shim and its legacy-data tests. (6) Surface: for every new public item, who outside this repository calls it, and does the file convention re-export types from private modules rather than expose module paths? (7) Tests: every test-matrix axis and cross-implementation vector test — after the sibling changes, does the axis have more than one value, is there more than one implementation? Every test helper and case — is it implied by a sibling in the same module? Every divergence test — can the two sources still differ in the new data flow? Consistency with sibling code is not a justification: a mechanism the siblings use is still unjustified here when this consumer does not need it. When a generic or associated type is forced by one bound, ask which of the two should collapse — the container or the error — and prefer collapsing the one no implementation varies. Name the existing symbol, its location and version for every reuse you propose, and the consumer for every proportionality finding. A scope cut is a finding too, marked as such — the author decides it.";;
    clean-room)      echo "Do NOT read the diff first. Read the change description above (and, failing that, the changed-file list and the names of the tests it adds) and write down for yourself the smallest design that serves the named consumer: which existing types, methods, endpoints and framework or engine features it would use, and what it would not add. Only then read the diff. Report as findings every place the change is larger than your design, each naming the smaller design concretely (existing symbol, location, version) and what the extra machinery costs; where the change is as small as your design or smaller, say so. Put your five-line design in the summary.";;
    plan-completeness) echo "The plan states rules. For each rule, verify its list of sites, arms, realms, callers and copies by searching the code yourself; list every one the plan misses, with file:line. An incomplete list is the defect this gate exists to catch.";;
    plan-soundness)  echo "For each rule, find the case where applying it breaks behaviour or an invariant, and any two rules that interact or contradict. Read the code the rule touches, not just the plan.";;
    plan-simplicity) echo "For each rule, look for a simpler fix: an existing helper, type, hook, or path in this repository that already does the job (name it with its location), a smaller change with the same effect, or two rules that should be one. Prefer reuse over new mechanism.";;
    plan-tests)      echo "For each rule, decide whether the named test would fail without the fix and pass with it. If it would not, name the test that would. A rule with no failing test is unverified.";;
    *)               echo "$1";;
  esac
}
{
  echo "You are one of several independent reviewers on a multi-model review panel. Others review the same change on different models; your value is what you can substantiate yourself. Report only what you can prove from the code. Read the surrounding code, not just the diff. Reason exhaustively — depth over speed; there is no time or token budget."
  echo
  case "$SEAT" in grok*) echo "FIRST run your tools: read the diff and open the files. Never answer before you have read the code. Do not write, edit, or run anything that modifies the repository."; echo;; esac
  echo "## Scope"
  if [ -n "$RO" ]; then
    echo "Documents to review (read them in full):"; sed 's/^/- /' "$RO"; echo
    echo "In findings, \`file\` is the document path and \`line_start\`/\`line_end\` are lines in that document."; echo
  else
    echo "Repository: $REV_ROOT"
    echo "Base commit: $REV_BASE (branch \`$REV_BRANCH\`, default branch \`$REV_DEFAULT\`)"
    case "$REV_SCOPE" in
      uncommitted) echo "Produce the diff yourself: \`git diff\` and \`git diff --cached\` in $REV_ROOT, plus \`git status --porcelain\` for untracked files.";;
      branch)      echo "Produce the diff yourself: \`git diff $REV_BASE\` in $REV_ROOT (committed, staged and unstaged work, all against the pinned base).";;
      *)           echo "Produce the diff yourself: \`git diff $REV_BASE -- $REV_SCOPE\` in $REV_ROOT.";;
    esac
    echo "Changed files:"
    if [ -s "$S/untracked.txt" ]; then
      awk 'NR==FNR{u[$0]=1;next} {printf "- %s%s\n", $0, ($0 in u ? " (untracked)" : "")}' "$S/untracked.txt" "$S/files.txt" 2>/dev/null
      echo
      echo "Files marked (untracked) do not appear in \`git diff\`; read them in full."
    else
      sed 's/^/- /' "$S/files.txt" 2>/dev/null
    fi
    echo
  fi
  if [ -n "$PRF" ] && [ -s "$PRF" ]; then
    echo "## Change description (from the author)"; cat "$PRF"; echo
    echo "The consumer and purpose named above are the yardstick for proportionality: machinery the change adds beyond what that consumer needs is a finding."; echo
  fi
  if [ "${REV_SEAT_OFFLINE:-}" = 1 ]; then
    echo "## Offline review"
    echo "Judge only what is in the repository above and in the pinned dependency sources already on this machine (the cargo registry, node_modules). Do not use the network, web search, package downloads, or any other checkout of this repository on this machine; do not fetch, and do not read published versions of packages that this repository itself publishes — they may postdate the change — and do not search the whole registry; open only the specific crates or packages this repository pins. Do not read build directories outside the repository (a global CARGO_TARGET_DIR, another checkout\'s target/ or node_modules/): they hold artifacts of other states of this code. If you cannot establish something from those sources, say so instead of looking it up."; echo
  fi
  if [ -n "$PLAN" ]; then
    echo "## Fix plan under review — nothing in it is implemented yet"
    echo "Read $PLAN in full. It clusters the previous round's accepted findings into rules; per rule it lists the sites the rule applies to, what it must not break, and the test that fails without it. Your job is to attack the plan BEFORE code is written, so the fixes land once: verify every claim against the repository above. In findings, \`file\` is the plan path with its line numbers when the defect is in the plan, or a code path when the plan missed something in the code. A sound plan returns an empty findings array."; echo
  fi
  echo "## Your lens this round: $LENS"; lens_text "$LENS"; echo; echo "Round emphasis: $EMPH"; echo
  if [ -f "$S/baseline.md" ]; then
    echo "## Baseline (before any review fix)"; cat "$S/baseline.md"; echo
    echo "Anything already failing above is pre-existing, not a finding of this change."; echo
  fi
  echo "## Already rejected — do not resurface these"
  if [ -s "$S/rejected.md" ]; then cat "$S/rejected.md"; else echo "(none yet)"; fi; echo
  if [ "$VAC" = 1 ]; then
    cat <<'EOV'
## Vacuity check (tests are touched)
Check every assertion the diff adds or edits for VACUITY: would it still pass if the behaviour it names were deleted? For each new or changed test, name the production change that would make it fail; report any test that has none as a P1 with lens `tests`. Watch for: `.all()`/`.every()` over a possibly-empty query; a before/after measurement read from an accessor that returns a copy; a test recomputing its expected value via the path under test; `expect.anything()` in the slot holding the new argument; a success path that never executes; arguments in the wrong order so the test never ran.

EOV
  fi
  echo "## Output — JSON only"
  echo "Return ONLY a JSON object matching this schema, no prose outside it:"; echo '```json'; cat "$SCHEMA"; echo '```'
  cat <<'EOR'
Severity: P0 = incorrect behaviour, security hole, data loss, or crash. P1 = real bug on a reachable path, bad edge case, broken contract. P2 = maintainability, performance, missing test, unclear API. P3 = nit, style, naming, comment.
Rules:
- Every finding names a file and lines you opened yourself; `evidence` is what the code shows, not what a diff summary says.
- One strong finding beats several weak ones. No style findings unless P3 and trivial.
- `confidence` is your honest probability the finding is real after trying to refute it.
- `suggested_fix` states the general rule, never a patch for the cited line alone: name every sibling site, branch, realm, or copy the rule applies to (search for them yourself) and the test that would fail without it. Half of all churn in this loop's history came from fixes that covered one instance of a class.
- If the change is sound, return an empty `findings` array and say so in `summary`.
EOR
} > "$OUT" || { echo "rev-prompt: cannot write $OUT" >&2; exit 1; }
echo "$OUT"
