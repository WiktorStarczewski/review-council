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
  git -C "$root" remote add origin https://github.com/acme/repo.git
  printf "REV_ROOT='%s'\n" "$root" > "$session/scope.env"
  pr_review_input > "$session/pr-review.json"
}

pr_review_gh_shim() {
  local bin=$1
  mkdir -p "$bin"
  cat > "$bin/gh" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$GH_CALLS"
if [ "${1:-} ${2:-}" = "pr view" ]; then
  if [ "${GH_MODE:-post}" = no-pr ]; then
    echo 'no pull requests found for branch "feat"' >&2
    exit 1
  fi
  printf '%s\n' '{"number":12,"url":"https://github.com/acme/repo/pull/12"}'
  exit 0
fi
if [ "${1:-}" = api ]; then
  if [ "${GH_MODE:-post}" = duplicate ]; then
    python3 - "$GH_DUP_BODY" <<'PY'
import json
import pathlib
import sys
print(json.dumps([[{"body": pathlib.Path(sys.argv[1]).read_text()}]]))
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

test_pr_review_publish() {
  local session="$T/pr-publish" root="$T/pr-repo" bin="$T/pr-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" GH_POSTED_BODY="$T/pr-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" --date 2026-09-15 \
    > "$T/pr-publish.out" 2> "$T/pr-publish.err"
  assert_eq "PR review publisher exits cleanly" "$?" 0
  assert_grep "PR review publisher resolves the current PR" "$T/pr.calls" \
    '^pr view --json number,url$'
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

test_pr_review_duplicate_and_no_pr() {
  local session="$T/pr-duplicate" root="$T/pr-duplicate-repo" bin="$T/pr-duplicate-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  : > "$T/pr-duplicate.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_CALLS="$T/pr-duplicate.calls" \
    GH_DUP_BODY="$session/pr-review.md" GH_POSTED_BODY="$T/should-not-exist" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" --date 2026-09-15 \
    > "$T/pr-duplicate.out" 2> "$T/pr-duplicate.err"
  assert_eq "identical PR review is a successful no-op" "$?" 0
  assert_grep "duplicate publication is reported" "$T/pr-duplicate.out" \
    '^pr-review: identical review already posted on https://github.com/acme/repo/pull/12$'
  assert_exit "duplicate publication creates no review" 0 test ! -e "$T/should-not-exist"
  assert_nogrep "duplicate path never invokes gh pr review" "$T/pr-duplicate.calls" '^pr review '

  local no_pr="$T/pr-no-pr"
  mkdir -p "$no_pr"
  : > "$T/pr-no-pr.calls"
  PATH="$bin:$PATH" GH_MODE=no-pr GH_CALLS="$T/pr-no-pr.calls" \
    GH_POSTED_BODY="$T/no-pr-body" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$no_pr" \
    > "$T/pr-no-pr.out" 2> "$T/pr-no-pr.err"
  assert_eq "review without scope is a successful no-op" "$?" 0
  assert_grep "review without scope explains the skip" "$T/pr-no-pr.out" \
    '^pr-review: no associated open PR; skipped$'
  assert_exit "review without scope never calls GitHub" 0 test ! -s "$T/pr-no-pr.calls"

  local no_remote="$T/pr-no-remote" no_remote_root="$T/pr-no-remote-repo"
  mkdir -p "$no_remote"
  mkrepo "$no_remote_root"
  printf "REV_ROOT='%s'\n" "$no_remote_root" > "$no_remote/scope.env"
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
  PATH="$bin:$PATH" GH_MODE=fail-post GH_CALLS="$T/pr-failure.calls" \
    GH_POSTED_BODY="$T/pr-failure-body" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" --date 2026-09-15 \
    > "$T/pr-failure.out" 2> "$T/pr-failure.err"
  assert_eq "failed GitHub publication fails the workflow" "$?" 1
  assert_exit "failed publication preserves the rendered review" 0 \
    test -s "$session/pr-review.md"
  assert_grep "failed publication preserves GitHub's diagnostic" "$T/pr-failure.err" \
    'remote rejected review'
  assert_grep "failed publication prints an exact retry command" "$T/pr-failure.err" \
    "retry: .*rev-pr-review.py publish $session$"
}
