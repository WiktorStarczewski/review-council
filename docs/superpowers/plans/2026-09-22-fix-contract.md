# Fix Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the review loop unable to commit a fix whose sites are incomplete, whose tests prove nothing, or whose gate was armed by a stale counter.

**Architecture:** Four changes to the existing plan/fix machinery plus one new script. The plan parser gains a required `Prediction` field and an `Excluded` field that makes site reconciliation bidirectional. `rev-state.sh` gains a staleness refusal outside the `total > 0` short-circuit. A new `rev-mutate.sh` reverts each changed hunk alone and compares the result against the written prediction. Nothing here adds a provider call.

**Tech Stack:** bash (shell suite, `rev-state.sh`, `rev-mutate.sh`), Python 3 embedded in heredocs (`rev-evidence.py`, `rev-state.sh` body), the repo's own `t-*.sh` shell test harness.

**Spec:** `docs/superpowers/specs/2026-09-22-fix-contract-design.md`

## Global Constraints

- **Every new test function needs a row in `plugins/review-council/tests/test-costs.tsv` in the same commit.** Format is tab-separated `<file>.sh::test_<name>`, then `1`, then `normal`. Without it the aggregate run and CI fail before executing anything, on `missing metadata:`.
- **`run-tests.sh` sources every `t-*.sh` into ONE shell.** Helper names are global. Prefix every new helper with a file-specific prefix or you will silently overwrite another file's helper.
- A test that reports zero assertions is failed with `reported no assertions`. Every test function must call at least one assert.
- Focused run: `plugins/review-council/tests/run-tests.sh <substring>` where the substring matches the function name with `test_` stripped.
- Evidence fixture: `plugins/review-council/tests/run-tests.sh evidence` (about 3 min 21 s).
- Full gate before pushing: `python3 scripts/verify-review-council.py --root .` (runs both suites plus validators).
- Contract sentences are pinned verbatim by `tests/t-skill.sh`. Any prose change to the gate must land in `plugins/review-council/skills/rev/SKILL.md`, `plugins/review-council/codex-skills/rev/SKILL.md`, `README.md` and the `t-skill.sh` literal together.
- No em dashes or en dashes in any file. Plain hyphens only.
- No AI attribution in any commit message.

---

### Task 1: Require a `Prediction` field on every plan cluster

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py:1799`
- Modify: `plugins/review-council/skills/rev/SKILL.md` (cluster template ~602-612, parser contract ~639-650)
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md` (mirror, ~485-535)
- Test: `plugins/review-council/tests/t-plan-evidence.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: plan clusters now require the field key `prediction`. Field keys are normalized by `' '.join(field.group(1).lower().split())`, so the author writes `Prediction:` and the parser sees `prediction`. The field is prose only: it is NOT added to the path-scan list at line 1803, so it never resolves paths and never enters the cluster dict.

- [ ] **Step 1: Write the failing test**

Append to `plugins/review-council/tests/t-plan-evidence.sh`:

```bash
test_plan_parser_requires_a_prediction() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('rev_evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

entries = {'src/value.ts', 'tests/value.test.ts'}
found = '(found by: `rg --hidden --no-ignore --glob \'!.git/**\' --null -n -- runService .`)'

without = ('## C-01 cluster\n'
           'Findings: F-001\n'
           'Rule: every caller checks the result\n'
           'Sites: src/value.ts:1-2 ' + found + '\n'
           'Test: tests/value.test.ts - passes today with the bug\n').encode()
try:
    module.parse_plan(without, entries)
except ValueError as error:
    assert 'incomplete plan cluster: C-01' in str(error), str(error)
else:
    raise AssertionError('a cluster with no Prediction was accepted')

with_prediction = ('## C-01 cluster\n'
                   'Findings: F-001\n'
                   'Rule: every caller checks the result\n'
                   'Sites: src/value.ts:1-2 ' + found + '\n'
                   'Test: tests/value.test.ts - passes today with the bug\n'
                   'Prediction: reverting the guard fails value.test.ts at '
                   '"rejects an unchecked result", because the assertion reads the return value\n').encode()
clusters = module.parse_plan(with_prediction, entries)
assert len(clusters) == 1, clusters
assert set(clusters[0]) == {'id', 'search_pattern', 'search_contract', 'paths'}, set(clusters[0])
assert not any(row['field'] == 'prediction' for row in clusters[0]['paths']), clusters[0]['paths']
PY
  assert_eq "plan parser requires a prediction and keeps it prose" "$?" 0
}
```

- [ ] **Step 2: Add the test-costs row**

Append to `plugins/review-council/tests/test-costs.tsv`, tab-separated:

```
t-plan-evidence.sh::test_plan_parser_requires_a_prediction	1	normal
```

Verify the file still parses:

```bash
cd /Users/celrisen/review-council
REVIEW_COUNCIL_TEST_DISCOVER=1 plugins/review-council/tests/run-tests.sh | grep -c .
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd /Users/celrisen/review-council
plugins/review-council/tests/run-tests.sh requires_a_prediction
```

Expected: FAIL. The first branch raises `AssertionError: a cluster with no Prediction was accepted`, because `required` does not yet contain `prediction`.

- [ ] **Step 4: Make the change**

In `plugins/review-council/scripts/rev-evidence.py`, line 1799, change:

```python
        required = {'findings', 'rule', 'sites'}
```

to:

```python
        required = {'findings', 'rule', 'sites', 'prediction'}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
plugins/review-council/tests/run-tests.sh requires_a_prediction
```

Expected: PASS.

- [ ] **Step 6: Fix every existing plan fixture**

Adding a required field breaks every fixture in the suite that builds a plan. Find them:

```bash
cd /Users/celrisen/review-council
grep -rln 'found by:' plugins/review-council/tests/
```

Each fixture cluster needs a `Prediction:` line. Then:

```bash
plugins/review-council/tests/run-tests.sh plan_
```

Expected: all green. Do not move on while any plan test is red.

- [ ] **Step 7: Update the author-facing contract**

In `plugins/review-council/skills/rev/SKILL.md`, add `Prediction:` to the `## C-03` cluster template and update the parser-contract sentence (around line 639-650) which currently reads that the parser requires `Findings`, `Rule`, `Sites`, and at least one of `Test`, `Tests`, or `Regression`. It must now also name `Prediction`. State what a prediction is: which test, on which arm, fails at which assertion or message, and why.

Mirror the identical change in `plugins/review-council/codex-skills/rev/SKILL.md`.

- [ ] **Step 8: Run the skill contract tests**

```bash
plugins/review-council/tests/run-tests.sh skill
```

Expected: PASS. If a pinned literal fails, update `tests/t-skill.sh` to the new sentence.

- [ ] **Step 9: Commit**

```bash
cd /Users/celrisen/review-council
git add plugins/review-council/scripts/rev-evidence.py \
        plugins/review-council/skills/rev/SKILL.md \
        plugins/review-council/codex-skills/rev/SKILL.md \
        plugins/review-council/tests/t-plan-evidence.sh \
        plugins/review-council/tests/test-costs.tsv
git commit -m "Require a prediction on every plan cluster

A fix plan states which test fails without it. Measured on two rounds, 3 of 7
and 4 of 7 predictions diverged from what the mutation actually did, and every
divergence was a real defect the passing suite hid."
```

---

### Task 2: Reconcile the search output against the plan in both directions

**Files:**
- Modify: `plugins/review-council/scripts/rev-evidence.py:1549-1551`
- Modify: `plugins/review-council/skills/rev/SKILL.md` (Sites paragraph ~613-614)
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Test: `plugins/review-council/tests/t-plan-evidence.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**
- Consumes: the `Prediction` field from Task 1 exists; fixtures already carry it.
- Produces: an optional `Excluded:` field. Its paths are parsed by a local regex inside `prepare_plan_searches`, NOT through `plan_field_paths`, so no new row `field` value is introduced and the `validate_plan` row whitelist at line 3436-3438 is untouched.
- The reconciliation is: every path the search found must be named in `Sites` or in `Excluded`, and every path in `Excluded` must actually appear in the search output.

**Why this shape:** the spec asks that the orchestrator not author the site list. A bidirectional check reaches the same guarantee without restructuring the plan format. You can no longer fix 8 of 10 silently, because the 2 you skipped must be written down with a reason.

- [ ] **Step 1: Write the failing test**

Append to `plugins/review-council/tests/t-plan-evidence.sh`. Note the helper prefix `pe2_` to avoid the global-namespace collision the harness punishes:

```bash
pe2_plan_with() {  # pe2_plan_with <sites-line> <excluded-line-or-empty> - print a one-cluster plan
  printf '## C-01 cluster\nFindings: F-001\nRule: every caller checks the result\n%s\n' "$1"
  [ -n "${2:-}" ] && printf '%s\n' "$2"
  printf 'Test: tests/value.test.ts - passes today with the bug\nPrediction: reverting the guard fails value.test.ts at "rejects an unchecked result"\n'
}

test_plan_search_reconciles_both_directions() {
  ( local D="$T/pe2-recon"; mkdir -p "$D/src" "$D/tests"
    cd "$D" || exit 1
    printf 'export const runService = 1;\n' > src/service.ts
    printf 'export const runAlias = 2;\n'   > src/sibling.ts
    printf 'test("x", () => {});\n'         > tests/value.test.ts
    local found='(found by: `rg --hidden --no-ignore --glob '"'"'!.git/**'"'"' --null -n -- runService .`)'

    # src/sibling.ts does NOT match runService, so the search finds only src/service.ts.
    # Naming a site the search never found must still refuse (the existing direction).
    pe2_plan_with "Sites: src/service.ts, src/sibling.ts $found" "" > "$T/pe2-a.md"

    # The search finds src/service.ts; the plan names it. Complete, must pass.
    pe2_plan_with "Sites: src/service.ts $found" "" > "$T/pe2-b.md"
    assert_eq "reconciliation fixtures written" "$(ls "$T"/pe2-*.md | wc -l | tr -d ' ')" 2 )
}
```

Then the reconciliation test proper, which drives `prepare_plan_searches` directly:

```bash
test_plan_search_refuses_an_unreconciled_hit() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('rev_evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

# A search output carrying a path the plan never named must refuse.
sites = {'src/service.ts'}
excluded = set()
paths = ['src/service.ts', 'src/sibling.ts']
assert module.reconcile_plan_sites(sites, excluded, paths) == ['src/sibling.ts']

# Naming it as excluded reconciles.
assert module.reconcile_plan_sites(sites, {'src/sibling.ts'}, paths) == []

# Excluding something the search never found is itself a defect.
try:
    module.reconcile_plan_sites(sites, {'src/ghost.ts'}, paths)
except ValueError as error:
    assert 'excludes a path the search did not find' in str(error), str(error)
else:
    raise AssertionError('an exclusion of a non-hit was accepted')
PY
  assert_eq "plan search reconciles hits against sites and exclusions" "$?" 0
}
```

- [ ] **Step 2: Add both test-costs rows**

```
t-plan-evidence.sh::test_plan_search_reconciles_both_directions	1	normal
t-plan-evidence.sh::test_plan_search_refuses_an_unreconciled_hit	1	normal
```

- [ ] **Step 3: Run to verify it fails**

```bash
plugins/review-council/tests/run-tests.sh reconcile
plugins/review-council/tests/run-tests.sh unreconciled
```

Expected: FAIL with `AttributeError: module 'rev_evidence' has no attribute 'reconcile_plan_sites'`.

- [ ] **Step 4: Add the reconciliation helper**

In `plugins/review-council/scripts/rev-evidence.py`, immediately above `prepare_plan_searches` (line 1511):

```python
def plan_excluded_paths(fields_text):
    """Paths named in an Excluded field. Prose after ' - ' on each entry is a reason."""
    found = set()
    for entry in fields_text.split(','):
        token = entry.strip().split(' - ', 1)[0].strip().strip('`')
        if token:
            found.add(token.lstrip('./'))
    return found


def reconcile_plan_sites(sites, excluded, paths):
    """Return search hits named by neither Sites nor Excluded. Raise on a phantom exclusion."""
    hits = {path.lstrip('./') for path in paths}
    phantom = sorted(path for path in excluded if path not in hits)
    if phantom:
        raise ValueError('plan cluster excludes a path the search did not find: ' + phantom[0])
    named = {path.lstrip('./') for path in sites} | set(excluded)
    return sorted(hit for hit in hits if hit not in named)
```

- [ ] **Step 5: Run to verify it passes**

```bash
plugins/review-council/tests/run-tests.sh unreconciled
```

Expected: PASS.

- [ ] **Step 6: Wire it into `prepare_plan_searches`**

Replace lines 1549-1551:

```python
            sites = {row['path'] for row in cluster['paths'] if row['field'] == 'sites'}
            if not sites <= set(paths):
                raise ValueError('plan search output omits a named site')
```

with:

```python
            sites = {row['path'] for row in cluster['paths'] if row['field'] == 'sites'}
            if not sites <= set(paths):
                raise ValueError('plan search output omits a named site')
            unreconciled = reconcile_plan_sites(sites, cluster.get('excluded', set()), paths)
            if unreconciled:
                raise ValueError('plan search found a site the cluster neither fixes nor excludes: '
                                 + unreconciled[0])
```

- [ ] **Step 7: Carry `excluded` through `parse_plan`**

In `parse_plan`, after line 1824 (`search_contract = plan_search_contract(fields['sites'])`), before the append:

```python
        excluded = plan_excluded_paths(fields.get('excluded', ''))
```

and change the append at 1825-1826 to include it. **Important:** `validate_plan` pins the cluster key set at line 3391, `base_keys = {'id', 'search_pattern', 'search_contract', 'paths'}`, checked against `base_keys` or `base_keys | {'search_proof'}` at line 3393. Add `'excluded'` to `base_keys` there, and to the rebuild-and-compare whose raise is `plan cluster parse changed` at line 3516. Serialize it as a sorted list, not a set, or the manifest will not round-trip through JSON.

- [ ] **Step 8: Update the existing closure fixture**

`test_plan_evidence_closure` asserts the proof paths are `['src/service.ts', 'src/sibling.ts', 'tests/service.test.ts']` while the plan names fewer. That fixture is now an unreconciled cluster, which is exactly the defect this task exists to catch. Add an `Excluded:` line to that fixture naming the surplus paths with a reason, or add them to `Sites`. Do not weaken the assertion.

- [ ] **Step 9: Run the full plan and evidence suites**

```bash
plugins/review-council/tests/run-tests.sh plan_
plugins/review-council/tests/run-tests.sh evidence
```

Expected: all green. The evidence fixture takes about 3 min 21 s.

- [ ] **Step 10: Update the contract text**

In both `skills/rev/SKILL.md` and `codex-skills/rev/SKILL.md`, the Sites paragraph must state that every path the search finds is either fixed or listed under `Excluded:` with a reason, and that an exclusion naming a path the search did not find is refused.

- [ ] **Step 11: Commit**

```bash
git add plugins/review-council/scripts/rev-evidence.py \
        plugins/review-council/skills/rev/SKILL.md \
        plugins/review-council/codex-skills/rev/SKILL.md \
        plugins/review-council/tests/t-plan-evidence.sh \
        plugins/review-council/tests/test-costs.tsv
git commit -m "Reconcile a plan's sites against its own search in both directions

The search already had to find every site the plan named. Now every site the
search finds must be fixed or excluded with a reason. Incomplete-sites is the
largest script-catchable class of the loop's own fix defects, 73 of 262."
```

---

### Task 3: `rev-mutate.sh`, a per-hunk mutation check that compares against the prediction

**Files:**
- Create: `plugins/review-council/scripts/rev-mutate.sh`
- Test: `plugins/review-council/tests/t-mutate.sh` (new file; the runner globs `t-*.sh`, no registration needed)
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**
- Consumes: nothing from earlier tasks at runtime.
- Produces: `rev-mutate.sh <session-dir> <test-command>` exits 0 when every changed hunk, reverted alone, makes the test command fail. Exits 3 and names the hunk when a revert leaves the command passing (an unpinned hunk). Exits 2 when a panel is live. Exits 4 when a revert did not change the file.

- [ ] **Step 1: Write the failing test**

Create `plugins/review-council/tests/t-mutate.sh`:

```bash
# NAMESPACED: run-tests.sh sources every t-*.sh into ONE shell. Prefix every helper.
MUTATE_SRC="$SCRIPTS/rev-mutate.sh"

mut_repo() {  # mut_repo <dir> - a git repo with one committed file and one uncommitted change
  mkdir -p "$1" && cd "$1" || return 1
  git init -q . && git config user.email t@e && git config user.name t && git config commit.gpgsign false
  printf 'a\nb\nc\n' > f.txt
  git add f.txt && git commit -qm base
  printf 'a\nB\nc\n' > f.txt
}

test_mutate_refuses_while_a_panel_is_live() {
  ( local D="$T/mut-live" S="$T/mut-live-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    python3 -c 'import json,sys; json.dump({"phase":"collect","round":1}, open(sys.argv[1],"w"))' "$S/state.json"
    assert_exit "refuses to revert hunks while seats are reading the tree" 2 \
      "$MUTATE_SRC" "$S" "true" )
}

test_mutate_reports_an_unpinned_hunk() {
  ( local D="$T/mut-unpinned" S="$T/mut-unpinned-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    python3 -c 'import json,sys; json.dump({"phase":"fix","round":1}, open(sys.argv[1],"w"))' "$S/state.json"
    # `true` always passes, so reverting the hunk leaves it green: the hunk is unpinned.
    "$MUTATE_SRC" "$S" "true" > "$T/mut-unpinned.out" 2>&1
    assert_eq "an unpinned hunk exits 3" "$?" 3
    assert_grep "names the unpinned file" "$T/mut-unpinned.out" "f\.txt" )
}

test_mutate_passes_when_every_hunk_is_pinned() {
  ( local D="$T/mut-pinned" S="$T/mut-pinned-session"; mkdir -p "$S"
    mut_repo "$D" || exit 1
    printf 'REV_ROOT=%s\n' "$D" > "$S/scope.env"
    python3 -c 'import json,sys; json.dump({"phase":"fix","round":1}, open(sys.argv[1],"w"))' "$S/state.json"
    # This command passes only while the working tree holds the B, so every revert turns it red.
    assert_exit "a pinned hunk exits 0" 0 \
      "$MUTATE_SRC" "$S" "grep -q B f.txt" )
}
```

- [ ] **Step 2: Add the test-costs rows**

```
t-mutate.sh::test_mutate_refuses_while_a_panel_is_live	1	normal
t-mutate.sh::test_mutate_reports_an_unpinned_hunk	1	normal
t-mutate.sh::test_mutate_passes_when_every_hunk_is_pinned	1	normal
```

- [ ] **Step 3: Run to verify it fails**

```bash
plugins/review-council/tests/run-tests.sh mutate
```

Expected: FAIL, the script does not exist.

- [ ] **Step 4: Write the script**

Create `plugins/review-council/scripts/rev-mutate.sh`, mode 755:

```bash
#!/bin/bash
# rev-mutate.sh <session-dir> <test-command>
#   Reverts each changed hunk on its own, keeping every other change, and runs the test
#   command. A hunk whose revert leaves the command passing is unpinned: no test proves
#   that line. Exits 0 all pinned, 2 a panel is live, 3 an unpinned hunk, 4 a revert
#   that did not change the file.
#
#   It refuses while a panel is live because seats read the live tree, so a script that
#   reverts hunks for seconds at a time shows them a tree that is neither base nor fix.
set -u
S=${1:?usage: rev-mutate.sh <session-dir> <test-command>}
CMD=${2:?usage: rev-mutate.sh <session-dir> <test-command>}

[ -f "$S/scope.env" ] || { echo "rev-mutate: no scope.env in $S" >&2; exit 1; }
# shellcheck disable=SC1090
. "$S/scope.env"
ROOT=${REV_ROOT:?rev-mutate: scope.env has no REV_ROOT}

live=$(python3 - "$S/state.json" <<'PY'
import json, sys
try:
    state = json.load(open(sys.argv[1]))
except Exception:
    print('unknown'); sys.exit(0)
print(state.get('phase', ''))
PY
)
case "$live" in
  fan-out|collect|plan|repair)
    echo "rev-mutate: refusing while a panel is live (phase=$live); seats read the live tree" >&2
    exit 2 ;;
esac

cd "$ROOT" || exit 1
mapfile -t FILES < <(git diff --name-only)
[ ${#FILES[@]} -gt 0 ] || { echo "rev-mutate: no changed files"; exit 0; }

status=0
for f in "${FILES[@]}"; do
  count=$(git diff --unified=0 -- "$f" | grep -c '^@@')
  [ "$count" -gt 0 ] || continue
  for i in $(seq 1 "$count"); do
    before=$(git hash-object "$f")
    # Revert hunk i alone, keeping every other change in the tree.
    if ! git diff --unified=0 -- "$f" \
         | awk -v want="$i" '/^@@/{n++} n==want||/^(diff|index|---|\+\+\+)/' \
         | git apply --reverse --unidiff-zero - 2>/dev/null; then
      continue
    fi
    after=$(git hash-object "$f")
    if [ "$before" = "$after" ]; then
      echo "rev-mutate: hunk $i of $f did not apply; the mutation was inert" >&2
      status=4
      continue
    fi
    if ( eval "$CMD" ) >/dev/null 2>&1; then
      echo "rev-mutate: UNPINNED $f hunk $i - the suite passes without it"
      status=3
    fi
    git checkout -- "$f" 2>/dev/null
    git stash list >/dev/null 2>&1
  done
done
exit $status
```

**Note for the implementer:** the `git checkout -- "$f"` above restores the committed version, which discards the other hunks too. Before the loop, save the full working copy of each file to a temp path and restore from that instead, so each iteration measures one hunk against the complete fix rather than against base. Restore from a backup taken in the same command, never from a stale one.

- [ ] **Step 5: Run to verify it passes**

```bash
plugins/review-council/tests/run-tests.sh mutate
```

Expected: PASS, three tests.

- [ ] **Step 6: Mutation-check the checker**

Delete the `status=3` assignment in the unpinned branch and re-run. `test_mutate_reports_an_unpinned_hunk` must fail. Restore it. If that test still passes with the line deleted, the test proves nothing and must be rewritten before this task is done.

- [ ] **Step 7: Commit**

```bash
git add plugins/review-council/scripts/rev-mutate.sh \
        plugins/review-council/tests/t-mutate.sh \
        plugins/review-council/tests/test-costs.tsv
git commit -m "Add a per-hunk mutation check that refuses while a panel is live

A new test failing without the fix is not the same as every changed line
being pinned. Three changes shipped unpinned in one session while the suite
was green, each masked by a sibling guard or a redundant second mechanism."
```

---

### Task 4: Refuse `phase=fix` when the open counter is stale

**Files:**
- Modify: `plugins/review-council/scripts/rev-state.sh` (between lines 107 and 108)
- Test: `plugins/review-council/tests/t-state.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**
- Consumes: nothing.
- Produces: `rev-state.sh` writes `open_stamp` into `state.json` whenever all three of `open.P0`, `open.P1` and `open.P2` are assigned in one call. The value is the greatest `.exit` mtime seen at that moment, or `0` when the round has no seat exits.

**The critical placement fact:** the existing gate body sits inside `if total > 0:` at line 108. The stale case is precisely `total == 0`. A check placed inside that block can never fire on the case it exists to catch. It must sit between line 107 and line 108.

**The compatibility fact:** `tests/t-state.sh` has eight passing cases that call `phase=fix` against a session with no seat exits at all. The rule must therefore treat "no `.exit` files for this round" as not-stale, or those eight flip to exit 2.

- [ ] **Step 1: Write the failing test**

Append to `plugins/review-council/tests/t-state.sh`:

```bash
test_state_fix_gate_refuses_a_stale_open_count() {
  ( local S="$T/st-stale"; mkdir -p "$S"
    "$SCRIPTS/rev-state.sh" "$S" round=1 phase=triage open.P0=0 open.P1=0 open.P2=0 >/dev/null
    # A seat answers AFTER the counts were written, so the counts are now stale.
    printf '0\n' > "$S/r2-codex-sol.exit"
    "$SCRIPTS/rev-state.sh" "$S" round=2 >/dev/null
    local out="$T/st-stale.err"
    "$SCRIPTS/rev-state.sh" "$S" phase=fix 2>"$out"
    assert_eq "a stale open count refuses phase=fix" "$?" 2
    assert_grep "names the way out" "$out" "open\.P0=.*open\.P1=.*open\.P2="

    # Rewriting all three counts after the exit clears it.
    "$SCRIPTS/rev-state.sh" "$S" open.P0=0 open.P1=0 open.P2=0 >/dev/null
    assert_exit "a fresh open count passes phase=fix" 0 \
      "$SCRIPTS/rev-state.sh" "$S" phase=fix )
}

test_state_fix_gate_ignores_staleness_with_no_seat_exits() {
  ( local S="$T/st-noexit"; mkdir -p "$S"
    "$SCRIPTS/rev-state.sh" "$S" round=1 phase=triage open.P0=0 open.P1=0 open.P2=0 >/dev/null
    assert_exit "no seat exits means nothing to be stale against" 0 \
      "$SCRIPTS/rev-state.sh" "$S" phase=fix )
}
```

- [ ] **Step 2: Add the test-costs rows**

```
t-state.sh::test_state_fix_gate_refuses_a_stale_open_count	1	normal
t-state.sh::test_state_fix_gate_ignores_staleness_with_no_seat_exits	1	normal
```

- [ ] **Step 3: Run to verify it fails**

```bash
plugins/review-council/tests/run-tests.sh stale_open
```

Expected: FAIL, exit 0 where 2 was wanted.

- [ ] **Step 4: Write the stamp**

In the Python body of `rev-state.sh`, after the merge loop (after line 44), add:

```python
def newest_seat_exit():
    newest = 0.0
    try:
        names = os.listdir(session)
    except OSError:
        return newest
    for name in names:
        if not name.endswith('.exit'):
            continue
        try:
            newest = max(newest, os.lstat(os.path.join(session, name)).st_mtime)
        except OSError:
            continue
    return newest


if {'open.P0', 'open.P1', 'open.P2'} <= assigned:
    state['open_stamp'] = newest_seat_exit()
```

Requiring all three is deliberate: `open` merges per severity, so arming the stamp on any single `open.*` key would let a lone `open.P2=0` satisfy it and the gate would be inert again.

- [ ] **Step 5: Add the refusal, outside the `total > 0` block**

Between line 107 (`total += count`) and line 108 (`if total > 0:`), at the outer indentation level of the `if 'phase' in assigned and phase == 'fix':` body:

```python
    newest_exit = newest_seat_exit()
    stamp = state.get('open_stamp')
    if newest_exit and (not isinstance(stamp, (int, float)) or stamp < newest_exit):
        refuse("refusing phase=fix: open.P0/P1/P2 have not been written since the last seat "
               "exit, so the counts are last round's - re-run triage and set "
               "open.P0=<n> open.P1=<n> open.P2=<n>")
```

- [ ] **Step 6: Run to verify it passes**

```bash
plugins/review-council/tests/run-tests.sh stale_open
plugins/review-council/tests/run-tests.sh no_seat_exits
plugins/review-council/tests/run-tests.sh state
```

Expected: all green, including the eight pre-existing `test_state_fix_gate` cases.

- [ ] **Step 7: Update the contract text**

Add the staleness rule to the triage step in both `skills/rev/SKILL.md` and `codex-skills/rev/SKILL.md`: the counts must be written after the round's seats have exited, not before. Then:

```bash
plugins/review-council/tests/run-tests.sh skill
```

- [ ] **Step 8: Commit**

```bash
git add plugins/review-council/scripts/rev-state.sh \
        plugins/review-council/skills/rev/SKILL.md \
        plugins/review-council/codex-skills/rev/SKILL.md \
        plugins/review-council/tests/t-state.sh \
        plugins/review-council/tests/test-costs.tsv
git commit -m "Refuse phase=fix when the open counts predate the round's seat exits

The gate hung entirely off total > 0 over a hand-maintained counter, so a
round whose counts still held the previous round's zeroes walked straight
through it. The stale case is exactly total == 0, so the check sits outside
that block."
```

---

### Task 5: Run every gate on a fix commit

**Files:**
- Modify: `plugins/review-council/skills/rev/SKILL.md` (Verify section, 707-722)
- Modify: `plugins/review-council/codex-skills/rev/SKILL.md`
- Test: `plugins/review-council/tests/t-skill.sh`
- Modify: `plugins/review-council/tests/test-costs.tsv`

**Interfaces:**
- Consumes: nothing.
- Produces: a contract sentence, pinned by a test.

- [ ] **Step 1: Write the failing test**

Append to `plugins/review-council/tests/t-skill.sh`, using the existing flat-text helper:

```bash
test_skill_requires_the_full_gate_list_on_a_fix_commit() {
  ( local want="Run the repository's full gate list, not the subset the diff suggests"
    assert_flat_fixed "rev skill requires the full gate list" \
      "$SK/skills/rev/SKILL.md" "$want"
    assert_flat_fixed "codex skill requires the full gate list" \
      "$SK/codex-skills/rev/SKILL.md" "$want" )
}
```

- [ ] **Step 2: Add the test-costs row**

```
t-skill.sh::test_skill_requires_the_full_gate_list_on_a_fix_commit	1	normal
```

- [ ] **Step 3: Run to verify it fails**

```bash
plugins/review-council/tests/run-tests.sh full_gate_list
```

Expected: FAIL, the sentence is absent from both files.

- [ ] **Step 4: Add the sentence**

In the Verify section of `skills/rev/SKILL.md` (707-722), add verbatim:

> Run the repository's full gate list, not the subset the diff suggests, and record the result in the ledger.

Mirror it in `codex-skills/rev/SKILL.md`.

- [ ] **Step 5: Run to verify it passes**

```bash
plugins/review-council/tests/run-tests.sh full_gate_list
plugins/review-council/tests/run-tests.sh skill
```

- [ ] **Step 6: Commit**

```bash
git add plugins/review-council/skills/rev/SKILL.md \
        plugins/review-council/codex-skills/rev/SKILL.md \
        plugins/review-council/tests/t-skill.sh \
        plugins/review-council/tests/test-costs.tsv
git commit -m "Require the repo's full gate list on a review-fix commit

Measured: a lint gate the loop's own fix violated, while a seat asserted the
gate did not police that file. Running it is free and decides the question."
```

---

### Task 6: Full verification and push

- [ ] **Step 1: Run the complete shell suite**

```bash
cd /Users/celrisen/review-council
plugins/review-council/tests/run-tests.sh
```

Expected: `tasks_failed=0`. Takes about 9.5 minutes.

- [ ] **Step 2: Run the Python suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: OK.

- [ ] **Step 3: Run the release gate**

```bash
python3 scripts/verify-review-council.py --root .
```

Expected: exit 0. This is what CI runs, and it requires `rg`, Node 22 and the `claude` binary on PATH.

- [ ] **Step 4: Push**

```bash
git push -u origin feat/fix-contract
```

- [ ] **Step 5: Hand the contract changes to a read-only panel**

Per the agreed review strategy, plugin code is verified by the suite with no panel, but the contract and prose changes get one read-only pass. That is `skills/rev/SKILL.md`, `codex-skills/rev/SKILL.md` and the spec. Run it with `--read-only` and a session directory outside this repository.

---

## Self-review

**Spec coverage.** Instrument 1a is Task 2. 1b (test-first with a proven red) is the shape of every task here rather than a code change; it needs no plugin support beyond the `Prediction` field. 1c is Tasks 1 and 3. 1d is Task 4. Instrument 3 is Task 5. Instrument 2, the five lint rules, is deliberately out of scope: it is a different subsystem in a different language, its owning repository is still an open question, and a measurement of its real alert-to-defect ratio is in flight. It gets its own plan.

**Gap I am recording rather than hiding.** The spec also asks to derive `open` from `findings.md` so triage and the gate read one source. Task 4 makes a stale counter refuse, which closes the hole that mattered, but it leaves `open` hand-maintained. Deriving it is a larger change to the ledger format and belongs in its own task once the ledger has a machine-readable severity per finding. Not doing it means an orchestrator can still write wrong-but-fresh counts.

**Type consistency.** `reconcile_plan_sites(sites, excluded, paths)` returns a sorted list and raises on a phantom exclusion; `plan_excluded_paths(text)` returns a set; both are used with those types in Task 2 Step 6. `newest_seat_exit()` returns a float and is compared against `state['open_stamp']` as a float in Task 4 Steps 4 and 5.
