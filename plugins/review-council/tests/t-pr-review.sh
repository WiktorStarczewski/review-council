pr_review_input() {
  cat <<'JSON'
{
  "verdict": {
    "headline": "No correctness or security defects remain.",
    "detail": "Nothing blocking from this review; one design point is yours to decide."
  },
  "panels": 2,
  "rejected": 1,
  "fixed_in": {
    "label": "acme/repo#9",
    "url": "https://github.com/acme/repo/pull/9"
  },
  "gates": "3/3 green, 42 tests",
  "panel": ["GPT-5.6 Sol", "Claude Sonnet 5"],
  "decisions": [
    {
      "title": "Keep compatibility mode?",
      "location": {
        "label": "src/api.rs#L10-L14",
        "url": "https://github.com/acme/repo/blob/0123456/src/api.rs#L10-L14"
      },
      "detail": "Compatibility mode is safe, but it expands the public contract."
    }
  ],
  "fixes": [
    {
      "severity": "P1",
      "summary": "Reject stale tokens before dispatch",
      "commit": {
        "label": "abc1234",
        "url": "https://github.com/acme/repo/commit/abc1234"
      }
    }
  ],
  "verified_sound": ["Fresh tokens reach the same dispatch path"],
  "coverage": ["Panels: simplicity · final verification"]
}
JSON
}

pr_review_expected() {
  cat <<'MARKDOWN'
[![Reviewed by review-council](https://img.shields.io/badge/reviewed_by-review--council-5b21b6?style=flat-square)](https://github.com/WiktorStarczewski/review-council)

## Review summary

> [!TIP]
> **No correctness or security defects remain.** Nothing blocking from this review; one design point is yours to decide.

2 panels · 3 findings: 1 fixed in [acme/repo#9](https://github.com/acme/repo/pull/9), 1 for you, 1 rejected · gates 3/3 green, 42 tests
Panel: GPT-5.6 Sol · Claude Sonnet 5, each at maximum effort

### Decisions for you

- **Keep compatibility mode?** · [`src/api.rs#L10-L14`](https://github.com/acme/repo/blob/0123456/src/api.rs#L10-L14)

<details>
<summary>Decisions in detail</summary>

1. **Keep compatibility mode?** Compatibility mode is safe, but it expands the public contract.

</details>

<details>
<summary>Fixes (1 commit)</summary>

| Severity | Fix | Commit |
| :-- | :-- | :-- |
| `P1` | Reject stale tokens before dispatch | [`abc1234`](https://github.com/acme/repo/commit/abc1234) |

</details>

<details>
<summary>Verified sound</summary>

- Fresh tokens reach the same dispatch path

</details>

<details>
<summary>Coverage</summary>

- Panels: simplicity · final verification

</details>

<sub>Reviewed by <a href="https://github.com/WiktorStarczewski/review-council">review-council</a>, an independent multi-model review panel. Every finding was checked against the source before it was fixed or reported. 2026-09-15</sub>
MARKDOWN
}

pr_review_session() {
  local session=$1 root=$2
  mkdir -p "$session"
  mkrepo "$root"
  git -C "$root" checkout -qb feat
  git -C "$root" remote add origin https://github.com/acme/repo.git
  printf "REV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" "$root" \
    > "$session/scope.env"
  pr_review_input > "$session/pr-review.json"
}

pr_review_gh_shim() {
  local bin=$1
  mkdir -p "$bin"
  cat > "$bin/gh" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$GH_CALLS"
head=${GH_HEAD_OID:-$(git rev-parse HEAD 2>/dev/null || printf '%040d' 0)}
if [ "${1:-} ${2:-}" = "pr view" ]; then
  if [ "${GH_MODE:-post}" = no-pr ]; then
    echo 'no pull requests found for branch "feat"' >&2
    exit 1
  fi
  live_head=${GH_LIVE_HEAD:-$head}
  live_state=${GH_LIVE_STATE:-OPEN}
  live_base=${GH_LIVE_BASE:-main}
  printf '{"number":12,"url":"https://github.com/acme/repo/pull/12","state":"%s","headRefName":"feat","headRefOid":"%s","baseRefName":"%s"}\n' "$live_state" "$live_head" "$live_base"
  exit 0
fi
if [ "${1:-}" = api ]; then
  if [ "${GH_MODE:-post}" = invalid-page ]; then
    printf '%s\n' '[{"body":"x"}]'
    exit 0
  fi
  if [ "${GH_MODE:-post}" = duplicate ]; then
    python3 - "$GH_DUP_BODY" "${GH_DUP_STATE:-COMMENTED}" <<'PY'
import json
import pathlib
import sys
print(json.dumps([[{"body": pathlib.Path(sys.argv[1]).read_text(), "state": sys.argv[2]}]]))
PY
  else
    printf '%s\n' '[[]]'
  fi
  exit 0
fi
if [ "${1:-} ${2:-}" = "pr review" ]; then
  shift 2
  while [ $# -gt 0 ]; do
    if [ "$1" = --body-file ]; then cp "$2" "$GH_POSTED_BODY"; fi
    shift
  done
  if [ "${GH_MODE:-post}" = fail-post ]; then
    echo 'remote rejected review' >&2
    exit 1
  fi
  exit 0
fi
exit 2
SH
  chmod +x "$bin/gh"
}

test_pr_review_render() {
  local session="$T/pr-render" expected="$T/pr-expected.md"
  mkdir -p "$session"
  pr_review_input > "$session/pr-review.json"
  pr_review_expected > "$expected"
  python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-render.out" 2> "$T/pr-render.err"
  assert_eq "PR review renderer exits cleanly" "$?" 0
  assert_exit "PR review renderer matches the canonical template" 0 \
    cmp -s "$expected" "$session/pr-review.md"
  assert_eq "PR review renderer reports its output" \
    "$(cat "$T/pr-render.out")" "$session/pr-review.md"
  assert_nogrep "PR review renderer emits no diagnostics" "$T/pr-render.err" '.'
}

test_pr_review_empty_sections() {
  local session="$T/pr-empty"
  mkdir -p "$session"
  cat > "$session/pr-review.json" <<'JSON'
{
  "verdict": {
    "headline": "The reviewed change is sound.",
    "detail": "Nothing blocks this review."
  },
  "panels": 1,
  "rejected": 0,
  "gates": "2/2 green, 8 tests",
  "panel": ["GPT-5.6 Sol"],
  "decisions": [],
  "fixes": [],
  "verified_sound": ["The boundary remains fail-closed"],
  "coverage": ["Panels: final verification"]
}
JSON
  python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  assert_eq "empty-section PR review renders cleanly" "$?" 0
  assert_grep "empty review keeps the decisions heading" "$session/pr-review.md" \
    '^### Decisions for you$'
  assert_grep "empty review states that no decisions remain" "$session/pr-review.md" \
    '^No decisions remain\.$'
  assert_grep "empty review keeps the fixes section" "$session/pr-review.md" \
    '^<summary>Fixes \(0 commits\)</summary>$'
  assert_grep "empty review keeps the fixes table" "$session/pr-review.md" \
    '^\| - \| No fixes required \| - \|$'
}

test_pr_review_required_lists() {
  local field session
  for field in panel verified_sound coverage; do
    session="$T/pr-required-$field"
    mkdir -p "$session"
    pr_review_input > "$session/pr-review.json"
    python3 - "$session/pr-review.json" "$field" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data[sys.argv[2]] = []
path.write_text(json.dumps(data))
PY
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" \
      > "$T/pr-required-$field.out" 2> "$T/pr-required-$field.err"
    assert_eq "$field is required to be nonempty" "$?" 1
    assert_grep "$field validation names the empty list" "$T/pr-required-$field.err" \
      "$field must not be empty"
  done
}

test_pr_review_clean_identity() {
  local bin="$T/pr-clean-bin" mode session root
  pr_review_gh_shim "$bin"
  for mode in staged unstaged untracked; do
    session="$T/pr-dirty-$mode"
    root="$T/pr-dirty-$mode-repo"
    pr_review_session "$session" "$root"
    case "$mode" in
      staged) echo changed > "$root/staged.txt"; git -C "$root" add staged.txt;;
      unstaged) echo changed >> "$root/a.txt";;
      untracked) echo changed > "$root/untracked.txt";;
    esac
    : > "$T/pr-dirty-$mode.calls"
    PATH="$bin:$PATH" GH_CALLS="$T/pr-dirty-$mode.calls" \
      python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
      > "$T/pr-dirty-$mode.out" 2> "$T/pr-dirty-$mode.err"
    assert_eq "$mode reviewed bytes block PR rendering" "$?" 1
    assert_exit "$mode failure writes no rendered review" 0 test ! -e "$session/pr-review.md"
    assert_exit "$mode failure writes no target envelope" 0 test ! -e "$session/pr-review-target.json"
  done

  local no_pr="$T/pr-dirty-no-open" no_pr_root="$T/pr-dirty-no-open-repo"
  pr_review_session "$no_pr" "$no_pr_root"
  echo local >> "$no_pr_root/a.txt"
  : > "$T/pr-dirty-no-open.calls"
  PATH="$bin:$PATH" GH_MODE=no-pr GH_CALLS="$T/pr-dirty-no-open.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$no_pr" --date 2026-09-15 \
    > "$T/pr-dirty-no-open.out" 2> "$T/pr-dirty-no-open.err"
  assert_eq "dirty branch without an open PR still renders for local inspection" "$?" 0

  local nested_root="$T/pr-nested-repo" nested
  mkrepo "$nested_root"
  git -C "$nested_root" checkout -qb feat
  git -C "$nested_root" remote add origin https://github.com/acme/repo.git
  nested="$nested_root/.review-session"
  mkdir -p "$nested"
  printf "REV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" "$nested_root" \
    > "$nested/scope.env"
  pr_review_input > "$nested/pr-review.json"
  : > "$T/pr-nested.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-nested.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$nested" --date 2026-09-15 \
    > "$T/pr-nested.out" 2> "$T/pr-nested.err"
  assert_eq "an in-repository session directory is excluded exactly" "$?" 0

  local stack="$T/pr-clean-stack" stack_root="$T/pr-clean-stack-repo" remote_head
  pr_review_session "$stack" "$stack_root"
  echo committed > "$stack_root/committed.txt"
  git -C "$stack_root" add committed.txt
  git -C "$stack_root" commit -qm 'fix(rev): local stack fix'
  remote_head=$(git -C "$stack_root" rev-parse HEAD^)
  : > "$T/pr-clean-stack.calls"
  PATH="$bin:$PATH" GH_HEAD_OID="$remote_head" GH_CALLS="$T/pr-clean-stack.calls" \
    REV_STACK_LEG=1 python3 "$SCRIPTS/rev-pr-review.py" render "$stack" --date 2026-09-15 \
    > "$T/pr-clean-stack.out" 2> "$T/pr-clean-stack.err"
  assert_eq "clean unpushed stack leg renders" "$?" 0

  local dirty_stack="$T/pr-dirty-stack" dirty_stack_root="$T/pr-dirty-stack-repo"
  pr_review_session "$dirty_stack" "$dirty_stack_root"
  echo local > "$dirty_stack_root/untracked.txt"
  : > "$T/pr-dirty-stack.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-dirty-stack.calls" REV_STACK_LEG=1 \
    python3 "$SCRIPTS/rev-pr-review.py" render "$dirty_stack" --date 2026-09-15 \
    > "$T/pr-dirty-stack.out" 2> "$T/pr-dirty-stack.err"
  assert_eq "dirty stack leg fails before rendering" "$?" 1
  assert_exit "dirty stack leg writes no rendered review" 0 test ! -e "$dirty_stack/pr-review.md"
  assert_exit "dirty stack leg writes no target envelope" 0 test ! -e "$dirty_stack/pr-review-target.json"
}

test_pr_review_publish() {
  local session="$T/pr-publish" root="$T/pr-repo" bin="$T/pr-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" GH_POSTED_BODY="$T/pr-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-render-publish.out" 2> "$T/pr-render-publish.err"
  assert_eq "PR review target render exits cleanly" "$?" 0
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" GH_POSTED_BODY="$T/pr-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-publish.out" 2> "$T/pr-publish.err"
  assert_eq "PR review publisher exits cleanly" "$?" 0
  assert_grep "PR review renderer freezes the scoped PR" "$T/pr.calls" \
    '^pr view feat --json number,url,state,headRefName,headRefOid,baseRefName$'
  assert_grep "PR review publisher revalidates the frozen PR" "$T/pr.calls" \
    '^pr view 12 --repo acme/repo --json number,url,state,headRefName,headRefOid,baseRefName$'
  assert_exit "PR review target envelope is written" 0 test -s "$session/pr-review-target.json"
  assert_grep "PR review publisher checks existing reviews" "$T/pr.calls" \
    '^api --paginate --slurp repos/acme/repo/pulls/12/reviews\?per_page=100$'
  assert_grep "PR review publisher creates a COMMENTED review" "$T/pr.calls" \
    "^pr review 12 --repo acme/repo --comment --body-file $session/pr-review.md$"
  assert_exit "posted body is the rendered body" 0 \
    cmp -s "$session/pr-review.md" "$T/pr-posted.md"
  assert_grep "publisher reports the target PR" "$T/pr-publish.out" \
    '^pr-review: posted https://github.com/acme/repo/pull/12$'
  assert_nogrep "successful publication emits no diagnostics" "$T/pr-publish.err" '.'
}

test_pr_review_frozen_publication() {
  local session="$T/pr-frozen" root="$T/pr-frozen-repo" bin="$T/pr-frozen-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-frozen.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-14 >/dev/null
  assert_eq "frozen publication fixture renders" "$?" 0
  cp "$session/pr-review.md" "$T/pr-frozen-inspected.md"
  sed 's/Nothing blocking from this review/Changed after inspection/' \
    "$session/pr-review.json" > "$T/pr-frozen-mutated.json"
  mv "$T/pr-frozen-mutated.json" "$session/pr-review.json"

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_DUP_STATE=COMMENTED \
    GH_DUP_BODY="$T/pr-frozen-inspected.md" GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen.out" 2> "$T/pr-frozen.err"
  assert_eq "cross-day retry is an exact-body no-op" "$?" 0
  assert_exit "publish preserves the inspected review bytes" 0 \
    cmp -s "$session/pr-review.md" "$T/pr-frozen-inspected.md"
  assert_nogrep "exact COMMENTED review suppresses a duplicate post" "$T/pr-frozen.calls" \
    '^pr review '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_DUP_STATE=APPROVED \
    GH_DUP_BODY="$T/pr-frozen-inspected.md" GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-approved-post.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" >/dev/null 2>&1
  assert_eq "non-COMMENTED duplicate body does not satisfy publication" "$?" 0
  assert_grep "non-COMMENTED duplicate body still posts a comment" "$T/pr-frozen.calls" \
    '^pr review '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_HEAD=0000000000000000000000000000000000000001 \
    GH_CALLS="$T/pr-frozen.calls" GH_POSTED_BODY="$T/pr-frozen-stale.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-stale.out" 2> "$T/pr-frozen-stale.err"
  assert_eq "changed PR head fails frozen publication" "$?" 1
  assert_nogrep "changed PR head is never posted" "$T/pr-frozen.calls" '^pr review '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_STATE=CLOSED GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-closed.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-closed.out" 2> "$T/pr-frozen-closed.err"
  assert_eq "closed frozen PR skips cleanly" "$?" 0
  assert_grep "closed frozen PR explains the skip" "$T/pr-frozen-closed.out" \
    '^pr-review: no associated open PR; skipped$'
  assert_nogrep "closed frozen PR is never posted" "$T/pr-frozen.calls" '^pr review '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_BASE=release GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-retargeted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-retargeted.out" 2> "$T/pr-frozen-retargeted.err"
  assert_eq "retargeted PR base fails frozen publication" "$?" 1
  assert_nogrep "retargeted PR is never posted" "$T/pr-frozen.calls" '^pr review '
}

test_pr_review_finalization_integrity() {
  local bin="$T/pr-integrity-bin" head
  pr_review_gh_shim "$bin"

  local json_session="$T/pr-json-tamper" json_root="$T/pr-json-tamper-repo"
  pr_review_session "$json_session" "$json_root"
  : > "$T/pr-json-tamper.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-json-tamper.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$json_session" --date 2026-09-15 >/dev/null
  cp "$json_session/pr-review.md" "$T/pr-json-original.md"
  cp "$json_session/pr-review-target.json" "$T/pr-json-original-target.json"
  sed 's/Nothing blocking from this review/Tampered after review/' \
    "$json_session/pr-review.json" > "$T/pr-json-mutated.json"
  mv "$T/pr-json-mutated.json" "$json_session/pr-review.json"
  head=$(git -C "$json_root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_HEAD_OID="$head" GH_CALLS="$T/pr-json-tamper.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$json_session" --head "$head" \
    > "$T/pr-json-tamper.out" 2> "$T/pr-json-tamper.err"
  assert_eq "mutated structured input blocks finalization" "$?" 1
  assert_exit "structured-input failure leaves the rendered body unchanged" 0 \
    cmp -s "$json_session/pr-review.md" "$T/pr-json-original.md"
  assert_exit "structured-input failure leaves the target unchanged" 0 \
    cmp -s "$json_session/pr-review-target.json" "$T/pr-json-original-target.json"

  local body_session="$T/pr-body-tamper" body_root="$T/pr-body-tamper-repo"
  pr_review_session "$body_session" "$body_root"
  : > "$T/pr-body-tamper.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-body-tamper.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$body_session" --date 2026-09-15 >/dev/null
  cp "$body_session/pr-review.json" "$T/pr-body-original.json"
  cp "$body_session/pr-review-target.json" "$T/pr-body-original-target.json"
  echo tampered >> "$body_session/pr-review.md"
  head=$(git -C "$body_root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_HEAD_OID="$head" GH_CALLS="$T/pr-body-tamper.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$body_session" --head "$head" \
    > "$T/pr-body-tamper.out" 2> "$T/pr-body-tamper.err"
  assert_eq "mutated rendered body blocks finalization" "$?" 1
  assert_exit "body failure leaves structured input unchanged" 0 \
    cmp -s "$body_session/pr-review.json" "$T/pr-body-original.json"
  assert_exit "body failure leaves the target unchanged" 0 \
    cmp -s "$body_session/pr-review-target.json" "$T/pr-body-original-target.json"

  local base_session="$T/pr-base-retarget" base_root="$T/pr-base-retarget-repo"
  pr_review_session "$base_session" "$base_root"
  : > "$T/pr-base-retarget.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-base-retarget.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$base_session" --date 2026-09-15 >/dev/null
  cp "$base_session/pr-review.md" "$T/pr-base-original.md"
  cp "$base_session/pr-review-target.json" "$T/pr-base-original-target.json"
  head=$(git -C "$base_root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_HEAD_OID="$head" GH_LIVE_BASE=release \
    GH_CALLS="$T/pr-base-retarget.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$base_session" --head "$head" \
    > "$T/pr-base-retarget.out" 2> "$T/pr-base-retarget.err"
  assert_eq "retargeted PR base blocks stack finalization" "$?" 1
  assert_exit "retargeted finalization leaves the body unchanged" 0 \
    cmp -s "$base_session/pr-review.md" "$T/pr-base-original.md"
  assert_exit "retargeted finalization leaves the target unchanged" 0 \
    cmp -s "$base_session/pr-review-target.json" "$T/pr-base-original-target.json"

  local format_session="$T/pr-json-format" format_root="$T/pr-json-format-repo"
  pr_review_session "$format_session" "$format_root"
  : > "$T/pr-json-format.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-json-format.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$format_session" --date 2026-09-15 >/dev/null
  python3 - "$format_session/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.write_text(json.dumps(json.loads(path.read_text()), sort_keys=True, separators=(",", ":")))
PY
  head=$(git -C "$format_root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_HEAD_OID="$head" GH_CALLS="$T/pr-json-format.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$format_session" --head "$head" \
    > "$T/pr-json-format.out" 2> "$T/pr-json-format.err"
  assert_eq "semantic JSON reformat remains finalizable" "$?" 0
}

test_pr_review_stack_finalization() {
  local session="$T/pr-finalize" root="$T/pr-finalize-repo" bin="$T/pr-finalize-bin"
  local interrupted="$T/pr-finalize-interrupted"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  echo one > "$root/one.txt"; git -C "$root" add one.txt
  git -C "$root" commit -qm 'fix(rev): one'
  echo two > "$root/two.txt"; git -C "$root" add two.txt
  git -C "$root" commit -qm 'fix(rev): two'
  local before after
  before=$(git -C "$root" rev-parse HEAD)
  cp "$session/pr-review.json" "$T/pr-finalize-original.json"
  : > "$T/pr-finalize.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  cp -R "$session" "$interrupted"
  git -C "$root" reset -q --soft HEAD~2
  git -C "$root" commit -qm 'apply review findings'
  after=$(git -C "$root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_HEAD_OID="$after" GH_CALLS="$T/pr-finalize.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$session" --head "$after" \
    > "$T/pr-finalize.out" 2> "$T/pr-finalize.err"
  assert_eq "equal-tree stack squash finalizes review links" "$?" 0
  assert_grep "stack finalization maps decision links to the aggregate SHA" \
    "$session/pr-review.md" "/blob/$after/"
  assert_grep "stack finalization maps fix links to the aggregate SHA" \
    "$session/pr-review.md" "/commit/$after"
  assert_exit "stack finalization leaves structured input immutable" 0 \
    cmp -s "$session/pr-review.json" "$T/pr-finalize-original.json"
  assert_eq "stack finalization binds the aggregate head" \
    "$(jq -r .head "$session/pr-review-target.json")" "$after"

  cp "$session/pr-review.md" "$interrupted/pr-review.md"
  : > "$T/pr-finalize-interrupted.calls"
  PATH="$bin:$PATH" GH_HEAD_OID="$after" GH_CALLS="$T/pr-finalize-interrupted.calls" \
    GH_POSTED_BODY="$T/pr-finalize-interrupted-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$interrupted" \
    > "$T/pr-finalize-interrupted-publish.out" 2> "$T/pr-finalize-interrupted-publish.err"
  assert_eq "interrupted finalization is not publishable" "$?" 1
  assert_nogrep "interrupted finalization never posts" \
    "$T/pr-finalize-interrupted.calls" '^pr review '
  PATH="$bin:$PATH" GH_HEAD_OID="$after" GH_CALLS="$T/pr-finalize-interrupted.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$interrupted" --head "$after" \
    > "$T/pr-finalize-interrupted.out" 2> "$T/pr-finalize-interrupted.err"
  assert_eq "interrupted finalization completes on retry" "$?" 0
  assert_eq "recovered finalization binds the aggregate head" \
    "$(jq -r .head "$interrupted/pr-review-target.json")" "$after"
  PATH="$bin:$PATH" GH_HEAD_OID="$after" GH_CALLS="$T/pr-finalize-interrupted.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$interrupted" --head "$after" \
    > "$T/pr-finalize-idempotent.out" 2> "$T/pr-finalize-idempotent.err"
  assert_eq "completed finalization retry is idempotent" "$?" 0
  assert_grep "completed finalization retry reports its state" \
    "$T/pr-finalize-idempotent.out" 'already finalized'

  local bad="$T/pr-finalize-bad" bad_root="$T/pr-finalize-bad-repo"
  pr_review_session "$bad" "$bad_root"
  : > "$T/pr-finalize-bad.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize-bad.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$bad" --date 2026-09-15 >/dev/null
  echo changed > "$bad_root/changed.txt"; git -C "$bad_root" add changed.txt
  git -C "$bad_root" commit -qm 'fix(rev): changed tree'
  local changed; changed=$(git -C "$bad_root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_HEAD_OID="$changed" GH_CALLS="$T/pr-finalize-bad.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$bad" --head "$changed" \
    > "$T/pr-finalize-bad.out" 2> "$T/pr-finalize-bad.err"
  assert_eq "tree-changing stack transition fails closed" "$?" 1
  assert_grep "tree-changing transition names the reviewed-tree mismatch" \
    "$T/pr-finalize-bad.err" 'tree'
  assert_eq "failed finalization retains the reviewed head" \
    "$(jq -r .head "$bad/pr-review-target.json")" \
    "$(git -C "$bad_root" rev-parse HEAD^)"
}

test_pr_review_rejects_invalid_review_pages() {
  local session="$T/pr-pages" root="$T/pr-pages-repo" bin="$T/pr-pages-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-pages.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-pages.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  PATH="$bin:$PATH" GH_MODE=invalid-page GH_CALLS="$T/pr-pages.calls" \
    GH_POSTED_BODY="$T/pr-pages-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-pages.out" 2> "$T/pr-pages.err"
  assert_eq "non-array review API page fails closed" "$?" 1
  assert_nogrep "invalid review API page never posts" "$T/pr-pages.calls" '^pr review '
}

test_pr_review_duplicate_and_no_pr() {
  local session="$T/pr-duplicate" root="$T/pr-duplicate-repo" bin="$T/pr-duplicate-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-duplicate.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-duplicate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  : > "$T/pr-duplicate.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_CALLS="$T/pr-duplicate.calls" \
    GH_DUP_BODY="$session/pr-review.md" GH_POSTED_BODY="$T/should-not-exist" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-duplicate.out" 2> "$T/pr-duplicate.err"
  assert_eq "identical PR review is a successful no-op" "$?" 0
  assert_grep "duplicate publication is reported" "$T/pr-duplicate.out" \
    '^pr-review: identical review already posted on https://github.com/acme/repo/pull/12$'
  assert_exit "duplicate publication creates no review" 0 test ! -e "$T/should-not-exist"
  assert_nogrep "duplicate path never invokes gh pr review" "$T/pr-duplicate.calls" '^pr review '

  local no_pr="$T/pr-no-scope"
  mkdir -p "$no_pr"
  : > "$T/pr-no-pr.calls"
  PATH="$bin:$PATH" GH_MODE=no-pr GH_CALLS="$T/pr-no-pr.calls" \
    GH_POSTED_BODY="$T/no-pr-body" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$no_pr" \
    > "$T/pr-no-pr.out" 2> "$T/pr-no-pr.err"
  assert_eq "review without scope fails closed" "$?" 1
  assert_grep "review without scope names the missing contract" "$T/pr-no-pr.err" \
    'scope\.env'
  assert_exit "review without scope never calls GitHub" 0 test ! -s "$T/pr-no-pr.calls"

  local no_remote="$T/pr-no-remote" no_remote_root="$T/pr-no-remote-repo"
  mkdir -p "$no_remote"
  mkrepo "$no_remote_root"
  printf "REV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" "$no_remote_root" \
    > "$no_remote/scope.env"
  PATH=/usr/bin:/bin python3 "$SCRIPTS/rev-pr-review.py" publish "$no_remote" \
    > "$T/pr-no-remote.out" 2> "$T/pr-no-remote.err"
  assert_eq "repository without a GitHub remote is a successful no-op" "$?" 0
  assert_grep "repository without a GitHub remote explains the skip" "$T/pr-no-remote.out" \
    '^pr-review: no associated open PR; skipped$'
  assert_nogrep "repository without a GitHub remote emits no diagnostics" "$T/pr-no-remote.err" '.'

  local no_open="$T/pr-no-open" no_open_root="$T/pr-no-open-repo"
  pr_review_session "$no_open" "$no_open_root"
  : > "$T/pr-no-open.calls"
  PATH="$bin:$PATH" GH_MODE=no-pr GH_CALLS="$T/pr-no-open.calls" \
    GH_POSTED_BODY="$T/no-open-body" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$no_open" \
    > "$T/pr-no-open.out" 2> "$T/pr-no-open.err"
  assert_eq "branch without a PR is a successful no-op" "$?" 0
  assert_grep "branch without a PR explains the skip" "$T/pr-no-open.out" \
    '^pr-review: no associated open PR; skipped$'
  assert_nogrep "branch without a PR never attempts a review" "$T/pr-no-open.calls" '^pr review '
}

test_pr_review_publish_failure() {
  local session="$T/pr-failure" root="$T/pr-failure-repo" bin="$T/pr-failure-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-failure.calls" \
    GH_POSTED_BODY="$T/pr-failure-body" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  PATH="$bin:$PATH" GH_MODE=fail-post GH_CALLS="$T/pr-failure.calls" \
    GH_POSTED_BODY="$T/pr-failure-body" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-failure.out" 2> "$T/pr-failure.err"
  assert_eq "failed GitHub publication fails the workflow" "$?" 1
  assert_exit "failed publication preserves the rendered review" 0 \
    test -s "$session/pr-review.md"
  assert_grep "failed publication preserves GitHub's diagnostic" "$T/pr-failure.err" \
    'remote rejected review'
  assert_grep "failed publication prints an exact retry command" "$T/pr-failure.err" \
    "retry: .*rev-pr-review.py publish $session$"
}
