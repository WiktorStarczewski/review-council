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

pin_pr_review_links() {
  local session=$1 root=$2 head
  head=$(git -C "$root" rev-parse HEAD)
  python3 - "$session/pr-review.json" "$head" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
for decision in data['decisions']:
    decision['location']['url'] = (
        f'https://github.com/acme/repo/blob/{sys.argv[2]}/src/api.rs#L10-L14')
if data.get('fixed_in') is None:
    for fix in data['fixes']:
        fix['commit']['label'] = sys.argv[2][:7]
        fix['commit']['url'] = f'https://github.com/acme/repo/commit/{sys.argv[2]}'
path.write_text(json.dumps(data))
PY
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
  local session=$1 root=$2 base
  mkdir -p "$session"
  mkrepo "$root"
  git -C "$root" checkout -qb feat
  git -C "$root" remote add origin https://github.com/acme/repo.git
  base=$(git -C "$root" rev-parse main)
  printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" \
    "$base" "$root" \
    > "$session/scope.env"
  pr_review_input > "$session/pr-review.json"
  pin_pr_review_links "$session" "$root"
}

pr_review_gh_shim() {
  local bin=$1
  mkdir -p "$bin"
  cat > "$bin/gh" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$GH_CALLS"
[ -z "${GH_HOST_CAPTURE:-}" ] || printf '%s\n' "${GH_HOST:-}" >> "$GH_HOST_CAPTURE"
head=${GH_HEAD_OID:-$(git rev-parse HEAD 2>/dev/null || printf '%040d' 0)}
base_oid=${GH_BASE_OID:-$(git rev-parse main 2>/dev/null || printf '%040d' 0)}
if [ "${1:-} ${2:-}" = "pr view" ]; then
  if [ -n "${GH_BLOCK_ENTERED:-}" ]; then
    : > "$GH_BLOCK_ENTERED"
    while [ ! -e "$GH_BLOCK_RELEASE" ]; do sleep 0.05; done
  fi
  if [ "${GH_MODE:-post}" = no-pr ]; then
    echo 'no pull requests found for branch "feat"' >&2
    exit 1
  fi
  live_head=${GH_LIVE_HEAD:-$head}
  live_state=${GH_LIVE_STATE:-OPEN}
  live_base=${GH_LIVE_BASE:-main}
  live_base_oid=${GH_LIVE_BASE_OID:-$base_oid}
  if [ -n "${GH_VIEW_COUNT_FILE:-}" ]; then
    count=0
    [ ! -f "$GH_VIEW_COUNT_FILE" ] || count=$(cat "$GH_VIEW_COUNT_FILE")
    count=$((count + 1))
    printf '%s\n' "$count" > "$GH_VIEW_COUNT_FILE"
    [ "$count" -ne 1 ] || live_head=${GH_FIRST_LIVE_HEAD:-$live_head}
    if [ -n "${GH_SWITCH_HEAD_AFTER:-}" ] && [ "$count" -gt "$GH_SWITCH_HEAD_AFTER" ]; then
      live_head=${GH_SWITCHED_HEAD:?}
    fi
    if [ -n "${GH_SWITCH_STATE_AFTER:-}" ] && [ "$count" -gt "$GH_SWITCH_STATE_AFTER" ]; then
      live_state=${GH_SWITCHED_STATE:?}
      live_head=${GH_SWITCHED_HEAD:-$live_head}
      live_base=${GH_SWITCHED_BASE:-$live_base}
      live_base_oid=${GH_SWITCHED_BASE_OID:-$live_base_oid}
    fi
  fi
  if [ -n "${GH_REVIEW_MARKER:-}" ] && [ -e "$GH_REVIEW_MARKER" ]; then
    if [ "${GH_MODE:-post}" = post-confirm-move ]; then
      live_head=${GH_SWITCHED_HEAD:?}
    fi
    if [ "${GH_MODE:-post}" = close-create ] \
        || [ "${GH_MODE:-post}" = close-submit ]; then
      live_state=CLOSED
    fi
  fi
  repo=${GH_REPO:-acme/repo}
  previous=
  for argument in "$@"; do
    [ "$previous" != --repo ] || repo=$argument
    previous=$argument
  done
  if [ -n "${GH_ONLY_REPO:-}" ] && [ "$repo" != "$GH_ONLY_REPO" ]; then
    echo 'no pull requests found for branch "feat"' >&2
    exit 1
  fi
  printf '{"number":12,"url":"https://github.com/%s/pull/12","state":"%s","headRefName":"feat","headRefOid":"%s","baseRefName":"%s","baseRefOid":"%s"}\n' "$repo" "$live_state" "$live_head" "$live_base" "$live_base_oid"
  exit 0
fi
  if [ "${1:-}" = api ]; then
  if [ "${2:-}" = user ]; then
    printf '{"login":"%s"}\n' "${GH_ACTOR:-tester}"
    exit 0
  fi
  if [ "${2:-}" = --paginate ] && [[ "${4:-}" == repos/*/pulls/*/reviews/*/comments\?per_page=100 ]]; then
    if [ "${GH_DUP_COMMENTS:-0}" = 0 ]; then
      printf '%s\n' '[[]]'
    else
      printf '%s\n' '[[{"id":1,"body":"unrelated inline comment"}]]'
    fi
    exit 0
  fi
  if [[ "${2:-}" == repos/*/pulls/*/reviews/[0-9]* ]]; then
    review_id=${2##*/}
    body_file=${GH_DUP_BODY:-$GH_CALLS.pending-body}
    python3 - "$body_file" "${GH_GET_STATE:-PENDING}" \
      "${GH_GET_COMMIT:-$head}" "${GH_GET_ACTOR:-${GH_ACTOR:-tester}}" "$review_id" <<'PY'
import json
import pathlib
import sys
print(json.dumps({"body": pathlib.Path(sys.argv[1]).read_text(), "state": sys.argv[2],
                  "commit_id": sys.argv[3], "id": int(sys.argv[5]),
                  "user": {"login": sys.argv[4]}}))
PY
    exit 0
  fi
  if [ "${2:-}" = --method ] && [ "${3:-}" = DELETE ]; then
    if [ "${GH_MODE:-post}" = fail-delete ]; then
      echo 'remote rejected pending-review cleanup' >&2
      exit 1
    fi
    [ -z "${GH_DELETED_REVIEW:-}" ] || printf '%s\n' "${4##*/}" > "$GH_DELETED_REVIEW"
    exit 0
  fi
  if [ "${2:-}" = --method ] && [ "${3:-}" = POST ]; then
    payload=$(cat)
    if [[ "${4:-}" == repos/*/pulls/*/reviews/*/events ]]; then
      if [ "${GH_MODE:-post}" = fail-submit ]; then
        echo 'remote rejected pending-review submission' >&2
        exit 1
      fi
      if [ "${GH_MODE:-post}" = concurrent ]; then
        if ! mkdir "$GH_REVIEW_MARKER.submit" 2>/dev/null; then
          echo 'pending review was already submitted' >&2
          exit 1
        fi
        rm -rf "$GH_REVIEW_MARKER.pending"
        mkdir "$GH_REVIEW_MARKER.commented"
        [ -z "${GH_SUBMIT_COUNT:-}" ] || printf 'submitted\n' >> "$GH_SUBMIT_COUNT"
      fi
      [ -z "${GH_POSTED_PAYLOAD:-}" ] || printf '%s' "$payload" > "$GH_POSTED_PAYLOAD"
      [ -z "${GH_POSTED_BODY:-}" ] || printf '%s' "$payload" | jq -j .body > "$GH_POSTED_BODY"
      if [ "${GH_MODE:-post}" = ambiguous-submit ]; then
        : > "$GH_REVIEW_MARKER"
        echo 'connection closed after pending-review submission' >&2
        exit 1
      fi
      if [ "${GH_MODE:-post}" = close-submit ]; then
        : > "$GH_REVIEW_MARKER"
        echo 'pull request is closed' >&2
        exit 1
      fi
      if [ "${GH_MODE:-post}" = post-confirm-move ]; then
        : > "$GH_REVIEW_MARKER"
      fi
      if [ "${GH_MODE:-post}" = invalid-submit-json ]; then
        printf '%s\n' '{invalid'
        exit 0
      fi
      if [ "${GH_MODE:-post}" = mismatched-submit ]; then
        printf '%s' "$payload" | jq \
          '{id: 80, body: .body, state: "COMMENTED", commit_id: "0000000000000000000000000000000000000001", user: {login: "tester"}}'
        exit 0
      fi
      printf '%s' "$payload" | jq --arg commit "$head" --arg actor "${GH_ACTOR:-tester}" \
        '{id: 80, body: .body, state: "COMMENTED", commit_id: $commit, user: {login: $actor}}'
      exit 0
    fi
    if [ "${GH_MODE:-post}" = fail-post ]; then
      echo 'remote rejected review' >&2
      exit 1
    fi
    if [ "${GH_MODE:-post}" = concurrent ]; then
      sleep 1
      if ! mkdir "$GH_REVIEW_MARKER.pending" 2>/dev/null; then
        echo 'User can only have one pending review per pull request' >&2
        exit 1
      fi
    fi
    printf '%s' "$payload" | jq -j .body > "$GH_CALLS.pending-body"
    [ -z "${GH_CREATED_PAYLOAD:-}" ] || printf '%s' "$payload" > "$GH_CREATED_PAYLOAD"
    [ -z "${GH_POSTED_PAYLOAD:-}" ] || printf '%s' "$payload" > "$GH_POSTED_PAYLOAD"
    [ -z "${GH_POSTED_BODY:-}" ] || printf '%s' "$payload" | jq -j .body > "$GH_POSTED_BODY"
    if [ "${GH_MODE:-post}" = ambiguous-create ]; then
      : > "$GH_REVIEW_MARKER"
      echo 'connection closed after pending-review creation' >&2
      exit 1
    fi
    if [ "${GH_MODE:-post}" = close-create ]; then
      : > "$GH_REVIEW_MARKER"
      echo 'pull request is closed' >&2
      exit 1
    fi
    if [ "${GH_MODE:-post}" = invalid-post-json ]; then
      printf '%s\n' '{invalid'
      exit 0
    fi
    if [ "${GH_MODE:-post}" = mismatched-post ]; then
      printf '%s' "$payload" | jq \
        '{id: 80, body: .body, state: "PENDING", commit_id: "0000000000000000000000000000000000000001", user: {login: "tester"}}'
      exit 0
    fi
    printf '%s' "$payload" | jq --arg actor "${GH_ACTOR:-tester}" \
      '{id: 80, body: .body, state: "PENDING", commit_id: .commit_id, user: {login: $actor}}'
    exit 0
  fi
  case "${2:-}" in
    repos/*/compare/*)
      printf '{"merge_base_commit":{"sha":"%s"}}\n' "${GH_MERGE_BASE:?}"
      exit 0
      ;;
  esac
  if [ "${GH_MODE:-post}" = invalid-page ]; then
    printf '%s\n' '[{"body":"x"}]'
    exit 0
  fi
  if [ "${GH_MODE:-post}" = empty-pages ]; then
    printf '%s\n' '[]'
    exit 0
  fi
  if [ "${GH_MODE:-post}" = null-item ]; then
    printf '%s\n' '[[null]]'
    exit 0
  fi
  if [ "${GH_MODE:-post}" = scalar-item ]; then
    printf '%s\n' '[[1]]'
    exit 0
  fi
  if [ "${GH_MODE:-post}" = null-fields ]; then
    printf '%s\n' '[[{"body":null,"state":"COMMENTED","commit_id":null}]]'
    exit 0
  fi
  if [ "${GH_MODE:-post}" = duplicate ] \
      || { [ "${GH_MODE:-post}" = ambiguous-create ] && [ -f "$GH_REVIEW_MARKER" ]; } \
      || { [ "${GH_MODE:-post}" = ambiguous-submit ] && [ -f "$GH_REVIEW_MARKER" ]; } \
      || { [ "${GH_MODE:-post}" = close-submit ] && [ -f "$GH_REVIEW_MARKER" ]; } \
      || { [ "${GH_MODE:-post}" = post-confirm-move ] && [ -f "$GH_REVIEW_MARKER" ]; } \
      || { [ "${GH_MODE:-post}" = concurrent ] \
        && { [ -d "$GH_REVIEW_MARKER.pending" ] || [ -d "$GH_REVIEW_MARKER.commented" ]; }; }; then
    state=${GH_DUP_STATE:-COMMENTED}
    [ "${GH_MODE:-post}" != ambiguous-create ] || state=PENDING
    [ "${GH_MODE:-post}" != ambiguous-submit ] || state=COMMENTED
    [ "${GH_MODE:-post}" != close-submit ] || state=PENDING
    [ "${GH_MODE:-post}" != post-confirm-move ] || state=COMMENTED
    if [ "${GH_MODE:-post}" = concurrent ]; then
      if [ -d "$GH_REVIEW_MARKER.commented" ]; then state=COMMENTED; else state=PENDING; fi
    fi
    python3 - "$GH_DUP_BODY" "$state" "${GH_DUP_COMMIT:-$head}" "${GH_DUP_ACTOR:-${GH_ACTOR:-tester}}" "${GH_DUP_ID:-80}" <<'PY'
import json
import pathlib
import sys
print(json.dumps([[{"body": pathlib.Path(sys.argv[1]).read_text(), "state": sys.argv[2],
                    "commit_id": sys.argv[3], "id": int(sys.argv[5]),
                    "user": {"login": sys.argv[4]}}]]))
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
  if [ "${GH_MODE:-post}" = concurrent ]; then
    sleep 1
    : > "$GH_REVIEW_MARKER"
  fi
  exit 0
fi
exit 2
SH
  chmod +x "$bin/gh"
}

test_pr_review_commit_deduplication() {
  local session="$T/pr-commit-dedupe"
  mkdir -p "$session"
  pr_review_input > "$session/pr-review.json"
  python3 - "$session/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data['fixes'].append({
    'severity': 'P2',
    'summary': 'Keep the same fix identity',
    'commit': {
        'label': 'abc1234',
        'url': ' https://github.com/acme/repo/commit/abc1234/ ',
    },
})
path.write_text(json.dumps(data))
PY
  python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  assert_eq "equivalent fix links render cleanly" "$?" 0
  assert_grep "equivalent fix links count one commit" "$session/pr-review.md" \
    '^<summary>Fixes \(1 commit\)</summary>$'
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

test_pr_review_escapes_html_contexts() {
  local session="$T/pr-html" unmatched="$T/pr-html-unmatched"
  mkdir -p "$session" "$unmatched"
  pr_review_input > "$session/pr-review.json"
  python3 - "$session/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
attack = '</details><details>&x'
data['verdict']['headline'] = f'Safe {attack} and `code <kept>&`'
data['verdict']['detail'] = attack
data['gates'] = attack
data['panel'] = [attack]
data['decisions'][0]['title'] = attack
data['decisions'][0]['detail'] = attack
data['decisions'][0]['location']['label'] = attack
data['decisions'][0]['location']['url'] = (
    'https://github.com/acme/repo/blob/0123456/src/a&b.rs')
data['fixes'][0]['summary'] = attack
data['fixes'][0]['commit']['label'] = attack
data['fixed_in']['label'] = attack
data['verified_sound'] = [attack]
data['coverage'] = [attack]
path.write_text(json.dumps(data))
PY
  python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-html.out" 2> "$T/pr-html.err"
  assert_eq "HTML-bearing review prose renders safely" "$?" 0
  assert_eq "hostile prose cannot add collapsible sections" \
    "$(grep -c '^<details>$' "$session/pr-review.md")" 4
  assert_grep "ordinary prose escapes raw HTML" "$session/pr-review.md" \
    '&lt;/details&gt;&lt;details&gt;&amp;x'
  assert_grep "balanced inline code remains byte-identical" "$session/pr-review.md" \
    '`code <kept>&`'
  assert_grep "decision code labels remain byte-identical" "$session/pr-review.md" \
    '\[`</details><details>&x`\]\(https://github.com/acme/repo/blob/0123456/src/a&b.rs\)'
  assert_grep "commit code labels remain byte-identical" "$session/pr-review.md" \
    '\[`</details><details>&x`\]\(https://github.com/acme/repo/commit/abc1234\)'
  assert_grep "validated link URLs remain byte-identical" "$session/pr-review.md" \
    'https://github.com/acme/repo/blob/0123456/src/a&b.rs'

  cp "$session/pr-review.json" "$unmatched/pr-review.json"
  python3 - "$unmatched/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data['decisions'][0]['title'] = 'unmatched ` code'
path.write_text(json.dumps(data))
PY
  python3 "$SCRIPTS/rev-pr-review.py" render "$unmatched" --date 2026-09-15 \
    > "$T/pr-html-unmatched.out" 2> "$T/pr-html-unmatched.err"
  assert_eq "unmatched prose backticks fail closed" "$?" 1
  assert_grep "unmatched backtick failure names the field" \
    "$T/pr-html-unmatched.err" 'decisions\[0\]\.title.*backtick'
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

test_pr_review_rejects_untrusted_links() {
  local field session="$T/pr-untrusted-links"
  for field in fixed_in decisions fixes; do
    rm -rf "$session"
    mkdir -p "$session"
    pr_review_input > "$session/pr-review.json"
    python3 - "$session/pr-review.json" "$field" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
field = sys.argv[2]
if field == 'fixed_in':
    data[field]['url'] = 'https://example.com/acme/repo/pull/9'
elif field == 'decisions':
    data[field][0]['location']['url'] = 'https://github.com/acme/repo/blob/main/src/api.rs'
else:
    data[field][0]['commit']['url'] = 'https://example.com/acme/repo/commit/abc1234'
path.write_text(json.dumps(data))
PY
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
      > "$T/pr-untrusted-$field.out" 2> "$T/pr-untrusted-$field.err"
    assert_eq "$field rejects an untrusted review link" "$?" 1
    assert_grep "$field names its GitHub URL requirement" "$T/pr-untrusted-$field.err" \
      'must be a .*GitHub URL'
  done
}

test_pr_review_binds_links_to_reviewed_state() {
  local session="$T/pr-bound-links" root="$T/pr-bound-links-repo" bin="$T/pr-bound-links-bin"
  local unrelated
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"

  python3 - "$session/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data['decisions'][0]['location']['url'] = data['decisions'][0]['location']['url'].replace(
    'github.com/acme/repo/', 'github.com/evil/repo/')
path.write_text(json.dumps(data))
PY
  : > "$T/pr-bound-links.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-bound-links.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-bound-links.out" 2> "$T/pr-bound-links.err"
  assert_eq "decision links outside the reviewed repository fail closed" "$?" 1
  assert_grep "decision repository mismatch is explicit" "$T/pr-bound-links.err" \
    'outside the reviewed repository'
  assert_exit "invalid bound links write no review" 0 test ! -e "$session/pr-review.md"

  pr_review_session "$session-fix" "$root-fix"
  python3 - "$session-fix/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data.pop('fixed_in')
data['fixes'][0]['commit']['url'] = data['fixes'][0]['commit']['url'].replace(
    'github.com/acme/repo/', 'github.com/evil/repo/')
path.write_text(json.dumps(data))
PY
  : > "$T/pr-bound-fix.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-bound-fix.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session-fix" --date 2026-09-15 \
    > "$T/pr-bound-fix.out" 2> "$T/pr-bound-fix.err"
  assert_eq "same-PR fix links outside the reviewed repository fail closed" "$?" 1
  assert_grep "fix repository mismatch is explicit" "$T/pr-bound-fix.err" \
    'outside the reviewed repository'

  pr_review_session "$session-ancestry" "$root-ancestry"
  unrelated=$(printf 'unrelated fix\n' | git -C "$root-ancestry" \
    commit-tree "$(git -C "$root-ancestry" rev-parse 'HEAD^{tree}')")
  python3 - "$session-ancestry/pr-review.json" "$unrelated" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data.pop('fixed_in')
data['fixes'][0]['commit']['url'] = f'https://github.com/acme/repo/commit/{sys.argv[2]}'
path.write_text(json.dumps(data))
PY
  : > "$T/pr-bound-ancestry.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-bound-ancestry.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session-ancestry" --date 2026-09-15 \
    > "$T/pr-bound-ancestry.out" 2> "$T/pr-bound-ancestry.err"
  assert_eq "same-PR fix links outside reviewed ancestry fail closed" "$?" 1
  assert_grep "fix ancestry mismatch is explicit" "$T/pr-bound-ancestry.err" \
    'not an ancestor of the reviewed head'

  local no_remote="$session-no-remote" no_remote_root="$root-no-remote"
  mkdir -p "$no_remote"
  mkrepo "$no_remote_root"
  git -C "$no_remote_root" checkout -qb feat
  printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" \
    "$(git -C "$no_remote_root" rev-parse main)" "$no_remote_root" \
    > "$no_remote/scope.env"
  pr_review_input > "$no_remote/pr-review.json"
  pin_pr_review_links "$no_remote" "$no_remote_root"
  : > "$T/pr-no-remote-bound.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-no-remote-bound.calls" NO_PUSH=1 \
    python3 "$SCRIPTS/rev-pr-review.py" render "$no_remote" --date 2026-09-15 >/dev/null
  git -C "$no_remote_root" remote add origin https://github.com/acme/repo.git
  PATH="$bin:$PATH" GH_CALLS="$T/pr-no-remote-bound.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$no_remote" \
    > "$T/pr-no-remote-bound.out" 2> "$T/pr-no-remote-bound.err"
  assert_eq "a target rendered without GitHub remotes requires a fresh render" "$?" 1
  assert_nogrep "a newly added remote receives no deferred review" \
    "$T/pr-no-remote-bound.calls" '^api --method POST '

  local repoint="$session-repoint" repoint_root="$root-repoint"
  pr_review_session "$repoint" "$repoint_root"
  : > "$T/pr-repoint.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-repoint.calls" NO_PUSH=1 \
    python3 "$SCRIPTS/rev-pr-review.py" render "$repoint" --date 2026-09-15 >/dev/null
  git -C "$repoint_root" remote set-url origin https://github.com/evil/repo.git
  PATH="$bin:$PATH" GH_CALLS="$T/pr-repoint.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$repoint" \
    > "$T/pr-repoint.out" 2> "$T/pr-repoint.err"
  assert_eq "a repointed remote cannot redirect deferred publication" "$?" 1
  assert_nogrep "a repointed remote receives no review" "$T/pr-repoint.calls" \
    '^api --method POST '

  local widen="$session-widen" widen_root="$root-widen" widen_head
  pr_review_session "$widen" "$widen_root"
  : > "$T/pr-widen.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-widen.calls" NO_PUSH=1 \
    python3 "$SCRIPTS/rev-pr-review.py" render "$widen" --date 2026-09-15 >/dev/null
  cp "$widen/pr-review.md" "$T/pr-widen-original.md"
  cp "$widen/pr-review-target.json" "$T/pr-widen-original-target.json"
  git -C "$widen_root" remote add mirror https://github.com/evil/repo.git
  widen_head=$(git -C "$widen_root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_ONLY_REPO=evil/repo GH_CALLS="$T/pr-widen.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$widen" --head "$widen_head" \
    > "$T/pr-widen.out" 2> "$T/pr-widen.err"
  assert_eq "an expanded remote set cannot redirect stack finalization" "$?" 1
  assert_exit "failed widened finalization preserves the body" 0 \
    cmp -s "$widen/pr-review.md" "$T/pr-widen-original.md"
  assert_exit "failed widened finalization preserves the target" 0 \
    cmp -s "$widen/pr-review-target.json" "$T/pr-widen-original-target.json"
  assert_nogrep "an expanded remote set receives no review" "$T/pr-widen.calls" \
    '^api --method POST '
}

test_pr_review_pins_github_host() {
  local session="$T/pr-host" root="$T/pr-host-repo" bin="$T/pr-host-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-host.calls"
  : > "$T/pr-host.capture"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-host.calls" GH_HOST_CAPTURE="$T/pr-host.capture" \
    GH_HOST=attacker.example \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-host.out" 2> "$T/pr-host.err"
  assert_eq "ambient GH_HOST cannot redirect PR discovery" "$?" 0
  assert_exit "every GitHub call is pinned to github.com" 0 \
    sh -c 'test -s "$1" && test "$(sort -u "$1")" = github.com' sh "$T/pr-host.capture"
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
    case "$mode" in
      staged) assert_grep "staged diagnostic names its dirty path" "$T/pr-dirty-$mode.err" 'staged\.txt';;
      unstaged) assert_grep "unstaged diagnostic names its dirty path" "$T/pr-dirty-$mode.err" 'a\.txt';;
      untracked) assert_grep "untracked diagnostic names its dirty path" "$T/pr-dirty-$mode.err" 'untracked\.txt';;
    esac
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
  mkdir -p "$nested_root/project"
  echo source > "$nested_root/project/code.txt"
  git -C "$nested_root" add project/code.txt
  git -C "$nested_root" commit -qm 'test: add tracked project directory'
  git -C "$nested_root" checkout -qb feat
  git -C "$nested_root" remote add origin https://github.com/acme/repo.git
  nested="$nested_root/project"
  printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" \
    "$(git -C "$nested_root" rev-parse main)" "$nested_root" \
    > "$nested/scope.env"
  pr_review_input > "$nested/pr-review.json"
  pin_pr_review_links "$nested" "$nested_root"
  : > "$T/pr-nested.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-nested.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$nested" --date 2026-09-15 \
    > "$T/pr-nested.out" 2> "$T/pr-nested.err"
  assert_eq "an associated session cannot overlap the reviewed repository" "$?" 1
  assert_grep "overlapping session reports the publication boundary" "$T/pr-nested.err" \
    'review session must be outside the reviewed repository'
  assert_exit "overlapping associated session writes no target" 0 \
    test ! -e "$nested/pr-review-target.json"

  : > "$T/pr-nested.calls"
  PATH="$bin:$PATH" GH_MODE=no-pr GH_CALLS="$T/pr-nested.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$nested" --date 2026-09-15 \
    > "$T/pr-nested-no-pr.out" 2> "$T/pr-nested-no-pr.err"
  assert_eq "an in-repository session without an open PR still renders" "$?" 0
  assert_exit "nested local render records an unassociated target" 0 \
    jq -e '.associated == false' "$nested/pr-review-target.json"

  local literal_root="$T/pr-literal-repo" literal
  mkrepo "$literal_root"
  git -C "$literal_root" checkout -qb feat
  git -C "$literal_root" remote add origin https://github.com/acme/repo.git
  literal="$literal_root/.review*"
  mkdir -p "$literal" "$literal_root/.review-hidden"
  printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" \
    "$(git -C "$literal_root" rev-parse main)" "$literal_root" > "$literal/scope.env"
  pr_review_input > "$literal/pr-review.json"
  echo dirty > "$literal_root/.review-hidden/dirty.txt"
  : > "$T/pr-literal.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-literal.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$literal" --date 2026-09-15 \
    > "$T/pr-literal.out" 2> "$T/pr-literal.err"
  assert_eq "pathspec metacharacters cannot bypass the external-session rule" "$?" 1
  assert_grep "literal session path reports the publication boundary" "$T/pr-literal.err" \
    'review session must be outside the reviewed repository'

  local stack="$T/pr-clean-stack" stack_root="$T/pr-clean-stack-repo" remote_head
  pr_review_session "$stack" "$stack_root"
  echo committed > "$stack_root/committed.txt"
  git -C "$stack_root" add committed.txt
  git -C "$stack_root" commit -qm 'fix(rev): local stack fix'
  pin_pr_review_links "$stack" "$stack_root"
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
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" NO_PUSH=1 \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-no-push-render.out" 2> "$T/pr-no-push-render.err"
  assert_eq "NO_PUSH still renders the PR review body" "$?" 0
  assert_nogrep "NO_PUSH rendering never calls GitHub" "$T/pr.calls" '.'
  assert_exit "NO_PUSH rendering keeps a local target envelope" 0 \
    test -s "$session/pr-review-target.json"
  assert_eq "NO_PUSH target remains unassociated until guarded publication" \
    "$(jq -r .associated "$session/pr-review-target.json")" false
  local local_head; local_head=$(git -C "$root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" NO_PUSH=1 \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$session" --head "$local_head" \
    > "$T/pr-no-push-finalize.out" 2> "$T/pr-no-push-finalize.err"
  assert_eq "NO_PUSH suppresses direct stack finalization" "$?" 0
  assert_nogrep "NO_PUSH stack finalization never calls GitHub" "$T/pr.calls" '.'
  : > "$T/pr.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" GH_POSTED_BODY="$T/pr-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-render-publish.out" 2> "$T/pr-render-publish.err"
  assert_eq "PR review target render exits cleanly" "$?" 0
  assert_grep "PR review renderer freezes the scoped PR" "$T/pr.calls" \
    '^pr view feat --repo acme/repo --json number,url,state,headRefName,headRefOid,baseRefName,baseRefOid$'
  : > "$T/pr.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" GH_POSTED_BODY="$T/pr-no-push-posted.md" \
    NO_PUSH=1 python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-no-push.out" 2> "$T/pr-no-push.err"
  assert_eq "NO_PUSH suppresses direct PR review publication" "$?" 0
  assert_grep "NO_PUSH publication skip is explicit" "$T/pr-no-push.out" \
    '^pr-review: NO_PUSH=1; skipped publication$'
  assert_nogrep "NO_PUSH never calls GitHub" "$T/pr.calls" '.'

  : > "$T/pr.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr.calls" GH_POSTED_BODY="$T/pr-posted.md" \
    GH_CREATED_PAYLOAD="$T/pr-created.json" GH_POSTED_PAYLOAD="$T/pr-posted.json" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-publish.out" 2> "$T/pr-publish.err"
  assert_eq "PR review publisher exits cleanly" "$?" 0
  assert_grep "PR review publisher rebinds to the scoped open PR" "$T/pr.calls" \
    '^pr view feat --repo acme/repo --json number,url,state,headRefName,headRefOid,baseRefName,baseRefOid$'
  assert_exit "PR review target envelope is written" 0 test -s "$session/pr-review-target.json"
  assert_grep "PR review publisher checks existing reviews" "$T/pr.calls" \
    '^api --paginate --slurp repos/acme/repo/pulls/12/reviews\?per_page=100$'
  assert_grep "PR review publisher creates a commit-pinned review" "$T/pr.calls" \
    '^api --method POST repos/acme/repo/pulls/12/reviews --input -$'
  assert_grep "PR review publisher submits the pending review" "$T/pr.calls" \
    '^api --method POST repos/acme/repo/pulls/12/reviews/80/events --input -$'
  assert_nogrep "PR review publisher never uses the unpinned CLI review command" \
    "$T/pr.calls" '^pr review '
  assert_eq "created review payload pins the reviewed head" \
    "$(jq -r .commit_id "$T/pr-created.json")" "$local_head"
  assert_eq "created review payload remains pending" \
    "$(jq -r 'has("event")' "$T/pr-created.json")" false
  assert_eq "submitted review payload posts a comment" \
    "$(jq -r .event "$T/pr-posted.json")" COMMENT
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

  echo tampered >> "$session/pr-review.md"
  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-tampered-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-body.out" 2> "$T/pr-frozen-body.err"
  assert_eq "edited rendered body blocks publication at the body-hash gate" "$?" 1
  assert_grep "edited rendered body names the body-hash failure" "$T/pr-frozen-body.err" \
    'frozen body hash'
  assert_nogrep "edited rendered body is never posted" "$T/pr-frozen.calls" \
    '^api --method POST '
  cp "$T/pr-frozen-inspected.md" "$session/pr-review.md"

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
  assert_exit "successful frozen retry clears the stale failure receipt" 0 \
    test ! -e "$session/incomplete.md"
  assert_nogrep "exact COMMENTED review suppresses a duplicate post" "$T/pr-frozen.calls" \
    '^api --method POST '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_DUP_STATE=APPROVED \
    GH_DUP_BODY="$T/pr-frozen-inspected.md" GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-approved-post.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" >/dev/null 2>&1
  assert_eq "non-COMMENTED duplicate body does not satisfy publication" "$?" 0
  assert_grep "non-COMMENTED duplicate body still posts a comment" "$T/pr-frozen.calls" \
    '^api --method POST '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_HEAD=0000000000000000000000000000000000000001 \
    GH_MERGE_BASE="$(git -C "$root" rev-parse main)" \
    GH_CALLS="$T/pr-frozen.calls" GH_POSTED_BODY="$T/pr-frozen-stale.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-stale.out" 2> "$T/pr-frozen-stale.err"
  assert_eq "changed PR head fails frozen publication" "$?" 1
  assert_grep "changed PR head reaches the intended identity gate" \
    "$T/pr-frozen-stale.err" 'the PR head changed after review'
  assert_nogrep "changed PR head is never posted" "$T/pr-frozen.calls" \
    '^api --method POST '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_STATE=CLOSED GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-closed.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-closed.out" 2> "$T/pr-frozen-closed.err"
  assert_eq "closed frozen PR skips cleanly" "$?" 0
  assert_grep "closed frozen PR explains the skip" "$T/pr-frozen-closed.out" \
    '^pr-review: no associated open PR; skipped$'
  assert_nogrep "closed frozen PR is never posted" "$T/pr-frozen.calls" \
    '^api --method POST '

  local terminal_state
  for terminal_state in CLOSED MERGED; do
    : > "$T/pr-frozen.calls"
    PATH="$bin:$PATH" GH_LIVE_STATE="$terminal_state" \
      GH_LIVE_HEAD=0000000000000000000000000000000000000006 \
      GH_LIVE_BASE=release GH_LIVE_BASE_OID=0000000000000000000000000000000000000007 \
      GH_MERGE_BASE=0000000000000000000000000000000000000008 \
      GH_CALLS="$T/pr-frozen.calls" \
      python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
      > "$T/pr-frozen-$terminal_state.out" 2> "$T/pr-frozen-$terminal_state.err"
    assert_eq "$terminal_state frozen PR ignores mutable metadata and skips" "$?" 0
    assert_grep "$terminal_state frozen PR reports the exact skip" \
      "$T/pr-frozen-$terminal_state.out" '^pr-review: no associated open PR; skipped$'
    assert_nogrep "$terminal_state frozen PR makes no API request" \
      "$T/pr-frozen.calls" '^api '
  done

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_BASE=release GH_CALLS="$T/pr-frozen.calls" \
    GH_POSTED_BODY="$T/pr-frozen-retargeted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-retargeted.out" 2> "$T/pr-frozen-retargeted.err"
  assert_eq "retargeted PR base fails frozen publication" "$?" 1
  assert_nogrep "retargeted PR is never posted" "$T/pr-frozen.calls" \
    '^api --method POST '

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_BASE_OID=0000000000000000000000000000000000000001 \
    GH_MERGE_BASE="$(git -C "$root" rev-parse main)" \
    GH_CALLS="$T/pr-frozen.calls" GH_POSTED_BODY="$T/pr-frozen-base-drift.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-base-drift.out" 2> "$T/pr-frozen-base-drift.err"
  assert_eq "same-name base movement with the reviewed merge base publishes" "$?" 0
  assert_grep "safe base movement verifies the reviewed merge base" "$T/pr-frozen.calls" \
    '^api repos/acme/repo/compare/0000000000000000000000000000000000000001\.\.\.'

  : > "$T/pr-frozen.calls"
  PATH="$bin:$PATH" GH_LIVE_BASE_OID=0000000000000000000000000000000000000002 \
    GH_MERGE_BASE=0000000000000000000000000000000000000003 \
    GH_CALLS="$T/pr-frozen.calls" GH_POSTED_BODY="$T/pr-frozen-wrong-base.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-wrong-base.out" 2> "$T/pr-frozen-wrong-base.err"
  assert_eq "changed merge base blocks publication" "$?" 1
  assert_nogrep "changed merge base is never posted" "$T/pr-frozen.calls" \
    '^api --method POST '

  local reviewed_head changed_head
  reviewed_head=$(git -C "$root" rev-parse HEAD)
  changed_head=0000000000000000000000000000000000000004
  : > "$T/pr-frozen-list-race.calls"
  : > "$T/pr-frozen-list-race.views"
  PATH="$bin:$PATH" GH_HEAD_OID="$reviewed_head" GH_SWITCH_HEAD_AFTER=1 \
    GH_SWITCHED_HEAD="$changed_head" GH_MERGE_BASE="$(git -C "$root" rev-parse main)" \
    GH_VIEW_COUNT_FILE="$T/pr-frozen-list-race.views" \
    GH_CALLS="$T/pr-frozen-list-race.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-list-race.out" 2> "$T/pr-frozen-list-race.err"
  assert_eq "head movement after review listing blocks publication" "$?" 1
  assert_nogrep "post-list head movement creates no review" \
    "$T/pr-frozen-list-race.calls" '^api --method POST '
  assert_grep "post-list head movement reaches the frozen-head gate" \
    "$T/pr-frozen-list-race.err" 'the PR head changed after review'

  : > "$T/pr-frozen-close-race.calls"
  : > "$T/pr-frozen-close-race.views"
  PATH="$bin:$PATH" GH_HEAD_OID="$reviewed_head" GH_SWITCH_STATE_AFTER=1 \
    GH_SWITCHED_STATE=CLOSED GH_SWITCHED_HEAD="$changed_head" GH_SWITCHED_BASE=release \
    GH_SWITCHED_BASE_OID=0000000000000000000000000000000000000007 \
    GH_VIEW_COUNT_FILE="$T/pr-frozen-close-race.views" \
    GH_CALLS="$T/pr-frozen-close-race.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-close-race.out" 2> "$T/pr-frozen-close-race.err"
  assert_eq "closure after review listing skips cleanly" "$?" 0
  assert_grep "post-list closure reports the exact skip" \
    "$T/pr-frozen-close-race.out" '^pr-review: no associated open PR; skipped$'
  assert_nogrep "post-list closure creates no review" \
    "$T/pr-frozen-close-race.calls" '^api --method POST '
  assert_grep "post-list closure is the final GitHub request" \
    "$T/pr-frozen-close-race.calls" 'pr view 12 --repo acme/repo'

  : > "$T/pr-frozen-pending-close.calls"
  : > "$T/pr-frozen-pending-close.views"
  rm -f "$T/pr-frozen-pending-close.deleted"
  PATH="$bin:$PATH" GH_HEAD_OID="$reviewed_head" GH_SWITCH_STATE_AFTER=2 \
    GH_SWITCHED_STATE=CLOSED GH_SWITCHED_HEAD="$changed_head" GH_SWITCHED_BASE=release \
    GH_SWITCHED_BASE_OID=0000000000000000000000000000000000000007 \
    GH_VIEW_COUNT_FILE="$T/pr-frozen-pending-close.views" \
    GH_DELETED_REVIEW="$T/pr-frozen-pending-close.deleted" \
    GH_CALLS="$T/pr-frozen-pending-close.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-pending-close.out" 2> "$T/pr-frozen-pending-close.err"
  assert_eq "closure after pending creation skips cleanly" "$?" 0
  assert_grep "closure after pending creation discards only the owned draft" \
    "$T/pr-frozen-pending-close.calls" \
    '^api --method DELETE repos/acme/repo/pulls/12/reviews/80$'
  assert_nogrep "closure after pending creation never submits the draft" \
    "$T/pr-frozen-pending-close.calls" 'reviews/80/events'

  : > "$T/pr-frozen-changed-draft.calls"
  : > "$T/pr-frozen-changed-draft.views"
  PATH="$bin:$PATH" GH_HEAD_OID="$reviewed_head" GH_SWITCH_STATE_AFTER=2 \
    GH_SWITCHED_STATE=CLOSED GH_SWITCHED_HEAD="$changed_head" GH_SWITCHED_BASE=release \
    GH_SWITCHED_BASE_OID=0000000000000000000000000000000000000007 \
    GH_VIEW_COUNT_FILE="$T/pr-frozen-changed-draft.views" GH_GET_ACTOR=other \
    GH_CALLS="$T/pr-frozen-changed-draft.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-changed-draft.out" 2> "$T/pr-frozen-changed-draft.err"
  assert_eq "a pending review that changed ownership is not deleted" "$?" 1
  assert_nogrep "changed pending ownership blocks cleanup deletion" \
    "$T/pr-frozen-changed-draft.calls" '^api --method DELETE '
  assert_grep "changed pending ownership has an actionable diagnostic" \
    "$T/pr-frozen-changed-draft.err" 'pending review changed before cleanup'

  : > "$T/pr-frozen-post-race.calls"
  : > "$T/pr-frozen-post-race.views"
  rm -f "$T/pr-frozen-post-race.deleted"
  PATH="$bin:$PATH" GH_HEAD_OID="$reviewed_head" GH_SWITCH_HEAD_AFTER=2 \
    GH_SWITCHED_HEAD="$changed_head" GH_MERGE_BASE="$(git -C "$root" rev-parse main)" \
    GH_VIEW_COUNT_FILE="$T/pr-frozen-post-race.views" \
    GH_DELETED_REVIEW="$T/pr-frozen-post-race.deleted" \
    GH_CALLS="$T/pr-frozen-post-race.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-frozen-post-race.out" 2> "$T/pr-frozen-post-race.err"
  assert_eq "head movement after pending creation fails publication" "$?" 1
  assert_grep "head movement after pending creation discards the owned draft" \
    "$T/pr-frozen-post-race.calls" \
    '^api --method DELETE repos/acme/repo/pulls/12/reviews/80$'
  assert_nogrep "head movement after pending creation never submits the draft" \
    "$T/pr-frozen-post-race.calls" 'reviews/80/events'
  assert_grep "post-creation head movement prints the exact retry" \
    "$T/pr-frozen-post-race.err" "retry: .*rev-pr-review.py publish $session$"
}

test_pr_review_github_remote_forms() {
  local variant session root bin="$T/pr-remotes-bin" url
  pr_review_gh_shim "$bin"
  for variant in explicit-port ssh-over-https; do
    session="$T/pr-remote-$variant"
    root="$T/pr-remote-$variant-repo"
    pr_review_session "$session" "$root"
    case "$variant" in
      explicit-port) url='ssh://git@github.com:22/acme/repo.git';;
      ssh-over-https) url='ssh://git@ssh.github.com:443/acme/repo.git';;
    esac
    git -C "$root" remote set-url origin "$url"
    : > "$T/pr-remote-$variant.calls"
    PATH="$bin:$PATH" GH_CALLS="$T/pr-remote-$variant.calls" \
      python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
      > "$T/pr-remote-$variant-render.out" 2> "$T/pr-remote-$variant-render.err"
    assert_eq "$variant GitHub remote renders an associated target" "$?" 0
    assert_eq "$variant GitHub remote normalizes its repository" \
      "$(jq -r .repo "$session/pr-review-target.json")" acme/repo
    PATH="$bin:$PATH" GH_CALLS="$T/pr-remote-$variant.calls" \
      python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
      > "$T/pr-remote-$variant-publish.out" 2> "$T/pr-remote-$variant-publish.err"
    assert_eq "$variant GitHub remote publishes" "$?" 0
    assert_grep "$variant GitHub remote posts to the normalized repository" \
      "$T/pr-remote-$variant.calls" '^api --method POST repos/acme/repo/pulls/12/reviews --input -$'
  done

  session="$T/pr-remote-lookalike"
  root="$T/pr-remote-lookalike-repo"
  pr_review_session "$session" "$root"
  git -C "$root" remote set-url origin \
    'ssh://git@ssh.github.com.evil.example:443/acme/repo.git'
  : > "$T/pr-remote-lookalike.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-remote-lookalike.calls" NO_PUSH=1 \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  PATH="$bin:$PATH" GH_CALLS="$T/pr-remote-lookalike.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-remote-lookalike.out" 2> "$T/pr-remote-lookalike.err"
  assert_eq "lookalike GitHub host remains an unassociated no-op" "$?" 0
  assert_nogrep "lookalike GitHub host makes no GitHub calls" \
    "$T/pr-remote-lookalike.calls" '.'
}

test_pr_review_repository_and_base_identity() {
  local session="$T/pr-identity" root="$T/pr-identity-repo" bin="$T/pr-identity-bin"
  local base ref variant
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  base=$(git -C "$root" rev-parse main)
  git -C "$root" tag reviewed-base main
  cp "$session/scope.env" "$T/pr-identity-original.scope"

  for variant in remote tag sha; do
    case "$variant" in
      remote) ref=origin/main;;
      tag) ref=reviewed-base;;
      sha) ref=$base;;
    esac
    sed "s#REV_BASE_BRANCH='main'#REV_BASE_BRANCH='$ref'#" \
      "$T/pr-identity-original.scope" > "$T/pr-identity-$variant.scope"
    cp "$T/pr-identity-$variant.scope" "$session/scope.env"
    : > "$T/pr-identity-$variant.calls"
    PATH="$bin:$PATH" GH_CALLS="$T/pr-identity-$variant.calls" \
      python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
      > "$T/pr-identity-$variant.out" 2> "$T/pr-identity-$variant.err"
    assert_eq "$variant base ref resolves through the reviewed merge base" "$?" 0
    assert_eq "$variant base ref freezes the actual PR base branch" \
      "$(jq -r .base_branch "$session/pr-review-target.json")" main
  done

  cp "$T/pr-identity-original.scope" "$session/scope.env"
  : > "$T/pr-identity-ambient.calls"
  PATH="$bin:$PATH" GH_REPO=evil/other GH_CALLS="$T/pr-identity-ambient.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 \
    > "$T/pr-identity-ambient.out" 2> "$T/pr-identity-ambient.err"
  assert_eq "ambient GH_REPO cannot redirect PR discovery" "$?" 0
  assert_eq "PR discovery stays bound to a reviewed GitHub remote" \
    "$(jq -r .repo "$session/pr-review-target.json")" acme/repo
  assert_grep "PR discovery names the reviewed remote explicitly" \
    "$T/pr-identity-ambient.calls" '^pr view feat --repo acme/repo '

  python3 - "$session/pr-review-target.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
target = json.loads(path.read_text())
target['repo'] = 'evil/other'
target['url'] = 'https://github.com/evil/other/pull/12'
path.write_text(json.dumps(target))
PY
  : > "$T/pr-identity-copied.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-identity-copied.calls" \
    GH_POSTED_BODY="$T/pr-identity-copied.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-identity-copied.out" 2> "$T/pr-identity-copied.err"
  assert_eq "cross-repository target state fails scope rebinding" "$?" 1
  assert_nogrep "cross-repository target state never posts" \
    "$T/pr-identity-copied.calls" '^api --method POST '

  PATH="$bin:$PATH" GH_CALLS="$T/pr-identity-copied.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  python3 - "$session/pr-review-target.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
target = json.loads(path.read_text())
target['tree'] = '0000000000000000000000000000000000000000'
path.write_text(json.dumps(target))
PY
  : > "$T/pr-identity-tree.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-identity-tree.calls" \
    GH_POSTED_BODY="$T/pr-identity-tree.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-identity-tree.out" 2> "$T/pr-identity-tree.err"
  assert_eq "altered target tree fails scope rebinding" "$?" 1
  assert_nogrep "altered target tree never posts" "$T/pr-identity-tree.calls" \
    '^api --method POST '
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

  local ancestry_session="$T/pr-ancestry" ancestry_root="$T/pr-ancestry-repo"
  pr_review_session "$ancestry_session" "$ancestry_root"
  : > "$T/pr-ancestry.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-ancestry.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$ancestry_session" --date 2026-09-15 >/dev/null
  local ancestry_tree other_parent unrelated_head
  ancestry_tree=$(git -C "$ancestry_root" rev-parse 'HEAD^{tree}')
  other_parent=$(printf 'other root\n' | git -C "$ancestry_root" commit-tree \
    "$(git -C "$ancestry_root" rev-parse 'main^{tree}')")
  unrelated_head=$(printf 'same tree, unrelated parent\n' | git -C "$ancestry_root" \
    commit-tree "$ancestry_tree" -p "$other_parent")
  git -C "$ancestry_root" reset -q --hard "$unrelated_head"
  PATH="$bin:$PATH" GH_HEAD_OID="$unrelated_head" GH_MERGE_BASE="$other_parent" \
    GH_CALLS="$T/pr-ancestry.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$ancestry_session" \
    --head "$unrelated_head" > "$T/pr-ancestry.out" 2> "$T/pr-ancestry.err"
  assert_eq "same-tree finalization with a different merge base fails" "$?" 1
  assert_grep "different-parent failure names the reviewed merge base" \
    "$T/pr-ancestry.err" 'the open PR merge base does not match the reviewed base'
}

test_pr_review_validate_stack() {
  local session="$T/pr-validate" root="$T/pr-validate-repo" bin="$T/pr-validate-bin"
  local head next
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-validate.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  head=$(git -C "$root" rev-parse HEAD)
  : > "$T/pr-validate.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$head" --root "$root" \
    > "$T/pr-validate-no-mode.out" 2> "$T/pr-validate-no-mode.err"
  assert_eq "missing push URL outside no-push mode fails closed" "$?" 1
  assert_grep "missing push URL names the local-mode requirement" \
    "$T/pr-validate-no-mode.err" 'push URL.*NO_PUSH=1'

  PATH="$bin:$PATH" NO_PUSH=1 GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$head" --root "$root" \
    > "$T/pr-validate-local.out" 2> "$T/pr-validate-local.err"
  assert_eq "no-push stack validation accepts the frozen review" "$?" 0

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$head" --root "$root" --push-url 'https://github.com/acme/repo.git' \
    > "$T/pr-validate-missing-ref.out" 2> "$T/pr-validate-missing-ref.err"
  assert_eq "push URL without a destination ref fails closed" "$?" 1
  assert_grep "missing push ref names the paired requirement" \
    "$T/pr-validate-missing-ref.err" 'push URL and ref.*together'

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$head" --root "$root" --push-ref 'refs/heads/feat' \
    > "$T/pr-validate-missing-url.out" 2> "$T/pr-validate-missing-url.err"
  assert_eq "push ref without a URL fails closed" "$?" 1
  assert_grep "missing push URL names the paired requirement" \
    "$T/pr-validate-missing-url.err" 'push URL and ref.*together'

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$head" --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/main' \
    > "$T/pr-validate-wrong-ref.out" 2> "$T/pr-validate-wrong-ref.err"
  assert_eq "a different destination branch fails closed" "$?" 1
  assert_grep "wrong push ref names the reviewed branch boundary" \
    "$T/pr-validate-wrong-ref.err" 'push ref.*reviewed branch'

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$head" --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-validate.out" 2> "$T/pr-validate.err"
  assert_eq "local stack validation accepts the frozen review" "$?" 0
  assert_nogrep "local stack validation makes no GitHub calls" "$T/pr-validate.calls" '.'

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack-destination "$session" \
    --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-validate-destination.out" 2> "$T/pr-validate-destination.err"
  assert_eq "pre-squash destination validation accepts the reviewed branch" "$?" 0

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack-destination "$session" \
    --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/main' \
    > "$T/pr-validate-destination-ref.out" 2> "$T/pr-validate-destination-ref.err"
  assert_eq "pre-squash destination validation rejects another branch" "$?" 1
  assert_grep "pre-squash wrong ref names the reviewed branch" \
    "$T/pr-validate-destination-ref.err" 'push ref.*reviewed branch'

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack-destination "$session" \
    --root "$root" --push-url 'https://github.com/evil/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-validate-destination-url.out" 2> "$T/pr-validate-destination-url.err"
  assert_eq "pre-squash destination validation rejects another repository" "$?" 1
  assert_grep "pre-squash wrong URL names the frozen repository" \
    "$T/pr-validate-destination-url.err" 'push URL.*frozen GitHub repository'

  git -C "$root" commit --allow-empty -qm 'fix(rev): same tree'
  next=$(git -C "$root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$next" --root "$root" --push-url 'ssh://git@github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-validate-same-tree.out" 2> "$T/pr-validate-same-tree.err"
  assert_eq "local stack validation accepts a same-tree aggregate commit" "$?" 0

  echo dirty > "$root/dirty.txt"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$next" --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-validate-dirty.out" 2> "$T/pr-validate-dirty.err"
  assert_eq "local stack validation rejects dirty bytes" "$?" 1
  assert_grep "dirty validation names the clean-tree gate" \
    "$T/pr-validate-dirty.err" 'staged, unstaged, or untracked bytes'
  git -C "$root" clean -qf

  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$next" --root "$root" --push-url 'https://github.com/evil/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-validate-push.out" 2> "$T/pr-validate-push.err"
  assert_eq "local stack validation rejects a redirected GitHub push" "$?" 1
  assert_grep "redirected push names the frozen repository boundary" \
    "$T/pr-validate-push.err" 'push URL.*frozen GitHub repository'

  echo tampered >> "$session/pr-review.md"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-validate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" \
    --head "$next" --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-validate-body.out" 2> "$T/pr-validate-body.err"
  assert_eq "local stack validation rejects a tampered rendered body" "$?" 1
  assert_grep "tampered validation names the frozen body" \
    "$T/pr-validate-body.err" 'frozen body hash'
  assert_nogrep "every local validation path avoids GitHub" "$T/pr-validate.calls" '.'
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
  python3 - "$session/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data.pop('fixed_in')
path.write_text(json.dumps(data))
PY
  pin_pr_review_links "$session" "$root"
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
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" --head "$after" \
    --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-finalize-validate.out" 2> "$T/pr-finalize-validate.err"
  assert_eq "real-push validation accepts a finalized review" "$?" 0
  PATH="$bin:$PATH" NO_PUSH=1 GH_CALLS="$T/pr-finalize.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$session" --head "$after" \
    --root "$root" \
    > "$T/pr-finalize-validate-local.out" 2> "$T/pr-finalize-validate-local.err"
  assert_eq "no-push validation accepts a finalized review" "$?" 0

  local changed_input="$T/pr-finalize-changed-input"
  cp -R "$session" "$changed_input"
  python3 - "$changed_input/pr-review.json" <<'PY'
import json
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data['decisions'][0]['location']['url'] = re.sub(
    r'/blob/[0-9a-f]{40}/', '/blob/' + '0' * 40 + '/',
    data['decisions'][0]['location']['url'])
path.write_text(json.dumps(data))
PY
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$changed_input" --head "$after" \
    --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-finalize-changed-url.out" 2> "$T/pr-finalize-changed-url.err"
  assert_eq "finalized validation rejects a changed original decision SHA" "$?" 1
  assert_grep "changed decision SHA names the semantic source mismatch" \
    "$T/pr-finalize-changed-url.err" 'structured PR review input'

  cp -R "$session" "$T/pr-finalize-changed-label"
  changed_input="$T/pr-finalize-changed-label"
  python3 - "$changed_input/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
label = data['fixes'][0]['commit']['label']
data['fixes'][0]['commit']['label'] = '0' * len(label)
path.write_text(json.dumps(data))
PY
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$changed_input" --head "$after" \
    --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-finalize-changed-label.out" 2> "$T/pr-finalize-changed-label.err"
  assert_eq "finalized validation rejects a changed original fix label" "$?" 1
  assert_grep "changed fix label names the semantic source mismatch" \
    "$T/pr-finalize-changed-label.err" 'structured PR review input'

  cp "$session/pr-review.md" "$interrupted/pr-review.md"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize-interrupted.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$interrupted" --head "$after" \
    --root "$root" --push-url 'https://github.com/acme/repo.git' \
    --push-ref 'refs/heads/feat' \
    > "$T/pr-finalize-interrupted-validate.out" \
    2> "$T/pr-finalize-interrupted-validate.err"
  assert_eq "real-push validation accepts an interrupted finalization" "$?" 0
  PATH="$bin:$PATH" NO_PUSH=1 GH_CALLS="$T/pr-finalize-interrupted.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" validate-stack "$interrupted" --head "$after" \
    --root "$root" \
    > "$T/pr-finalize-interrupted-local.out" 2> "$T/pr-finalize-interrupted-local.err"
  assert_eq "no-push validation rejects an interrupted finalization" "$?" 1
  : > "$T/pr-finalize-interrupted.calls"
  PATH="$bin:$PATH" GH_HEAD_OID="$after" GH_CALLS="$T/pr-finalize-interrupted.calls" \
    GH_POSTED_BODY="$T/pr-finalize-interrupted-posted.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$interrupted" \
    > "$T/pr-finalize-interrupted-publish.out" 2> "$T/pr-finalize-interrupted-publish.err"
  assert_eq "interrupted finalization is not publishable" "$?" 1
  assert_nogrep "interrupted finalization never posts" \
    "$T/pr-finalize-interrupted.calls" '^api --method POST '
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

  local separate="$T/pr-finalize-separate" separate_root="$T/pr-finalize-separate-repo"
  pr_review_session "$separate" "$separate_root"
  echo one > "$separate_root/one.txt"; git -C "$separate_root" add one.txt
  git -C "$separate_root" commit -qm 'fix(rev): separate one'
  echo two > "$separate_root/two.txt"; git -C "$separate_root" add two.txt
  git -C "$separate_root" commit -qm 'fix(rev): separate two'
  pin_pr_review_links "$separate" "$separate_root"
  : > "$T/pr-finalize-separate.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize-separate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$separate" --date 2026-09-15 >/dev/null
  git -C "$separate_root" reset -q --soft HEAD~2
  git -C "$separate_root" commit -qm 'apply review findings'
  after=$(git -C "$separate_root" rev-parse HEAD)
  PATH="$bin:$PATH" GH_HEAD_OID="$after" GH_CALLS="$T/pr-finalize-separate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$separate" --head "$after" \
    > "$T/pr-finalize-separate.out" 2> "$T/pr-finalize-separate.err"
  assert_eq "separate-PR fix finalization succeeds" "$?" 0
  assert_grep "separate-PR fix link remains immutable" "$separate/pr-review.md" \
    '/commit/abc1234)'
  assert_nogrep "separate-PR fix link is not rewritten to the reviewed PR" \
    "$separate/pr-review.md" "/commit/$after"

  local lag="$T/pr-finalize-lag" lag_root="$T/pr-finalize-lag-repo" lag_before lag_after
  pr_review_session "$lag" "$lag_root"
  echo lag > "$lag_root/lag.txt"; git -C "$lag_root" add lag.txt
  git -C "$lag_root" commit -qm 'fix(rev): lag one'
  pin_pr_review_links "$lag" "$lag_root"
  lag_before=$(git -C "$lag_root" rev-parse HEAD)
  : > "$T/pr-finalize-lag.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize-lag.calls" NO_PUSH=1 \
    python3 "$SCRIPTS/rev-pr-review.py" render "$lag" --date 2026-09-15 >/dev/null
  assert_eq "lag fixture starts with an unassociated target" \
    "$(jq -r .associated "$lag/pr-review-target.json")" false
  git -C "$lag_root" reset -q --soft HEAD~1
  git -C "$lag_root" commit -qm 'apply review findings'
  lag_after=$(git -C "$lag_root" rev-parse HEAD)
  : > "$T/pr-finalize-lag.views"
  PATH="$bin:$PATH" GH_HEAD_OID="$lag_after" GH_FIRST_LIVE_HEAD="$lag_before" \
    GH_VIEW_COUNT_FILE="$T/pr-finalize-lag.views" GH_CALLS="$T/pr-finalize-lag.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$lag" --head "$lag_after" \
    > "$T/pr-finalize-lag.out" 2> "$T/pr-finalize-lag.err"
  assert_eq "stack finalization tolerates one stale post-push PR read" "$?" 0
  assert_eq "stack finalization polls until GitHub exposes the pushed head" \
    "$(cat "$T/pr-finalize-lag.views")" 2
  assert_eq "stack finalization promotes only the pushed head" \
    "$(jq -r .head "$lag/pr-review-target.json")" "$lag_after"

  local closing="$T/pr-finalize-closing"
  cp -R "$lag" "$closing"
  python3 - "$closing/pr-review-target.json" "$lag_before" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data['associated'] = False
data['head'] = sys.argv[2]
path.write_text(json.dumps(data, indent=2) + '\n')
PY
  : > "$T/pr-finalize-closing.calls"
  : > "$T/pr-finalize-closing.views"
  PATH="$bin:$PATH" GH_HEAD_OID="$lag_after" GH_FIRST_LIVE_HEAD="$lag_before" \
    GH_SWITCH_STATE_AFTER=1 GH_SWITCHED_STATE=MERGED \
    GH_SWITCHED_HEAD=0000000000000000000000000000000000000006 \
    GH_SWITCHED_BASE=release \
    GH_SWITCHED_BASE_OID=0000000000000000000000000000000000000007 \
    GH_VIEW_COUNT_FILE="$T/pr-finalize-closing.views" \
    GH_CALLS="$T/pr-finalize-closing.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$closing" --head "$lag_after" \
    > "$T/pr-finalize-closing.out" 2> "$T/pr-finalize-closing.err"
  assert_eq "closure during stack head polling skips cleanly" "$?" 0
  assert_grep "stack polling closure reports the exact skip" \
    "$T/pr-finalize-closing.out" '^pr-review: no associated open PR; skipped$'
  assert_nogrep "stack polling closure makes no API request" \
    "$T/pr-finalize-closing.calls" '^api '
  assert_eq "stack polling closure does not promote the frozen target" \
    "$(jq -r .head "$closing/pr-review-target.json")" "$lag_before"
}

test_pr_review_rejects_invalid_review_pages() {
  local session="$T/pr-pages" root="$T/pr-pages-repo" bin="$T/pr-pages-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-pages.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-pages.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  local mode
  for mode in invalid-page empty-pages null-item scalar-item; do
    : > "$T/pr-pages.calls"
    PATH="$bin:$PATH" GH_MODE="$mode" GH_CALLS="$T/pr-pages.calls" \
      GH_POSTED_BODY="$T/pr-pages-posted.md" \
      python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
      > "$T/pr-pages-$mode.out" 2> "$T/pr-pages-$mode.err"
    assert_eq "$mode review API page fails closed" "$?" 1
    assert_nogrep "$mode review API page never posts" "$T/pr-pages.calls" \
      '^api --method POST '
  done

  : > "$T/pr-pages.calls"
  PATH="$bin:$PATH" GH_MODE=null-fields GH_CALLS="$T/pr-pages.calls" \
    GH_POSTED_BODY="$T/pr-pages-null-fields.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-pages-null-fields.out" 2> "$T/pr-pages-null-fields.err"
  assert_eq "null comparison fields remain valid nonmatches" "$?" 0
  assert_eq "a null-field nonmatch creates one pending review" \
    "$(grep -Ec '^api --method POST repos/acme/repo/pulls/12/reviews --input -$' \
      "$T/pr-pages.calls")" 1
  assert_eq "a null-field nonmatch submits one pending review" \
    "$(grep -Ec '^api --method POST repos/acme/repo/pulls/12/reviews/80/events --input -$' \
      "$T/pr-pages.calls")" 1
}

test_pr_review_concurrent_publication() {
  local session="$T/pr-concurrent" root="$T/pr-concurrent-repo" bin="$T/pr-concurrent-bin"
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-concurrent.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-concurrent.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  rm -rf "$T/pr-concurrent.marker.pending" "$T/pr-concurrent.marker.commented" \
    "$T/pr-concurrent.marker.submit"
  : > "$T/pr-concurrent.submits"
  PATH="$bin:$PATH" GH_MODE=concurrent GH_CALLS="$T/pr-concurrent.calls" \
    GH_REVIEW_MARKER="$T/pr-concurrent.marker" GH_DUP_BODY="$session/pr-review.md" \
    GH_SUBMIT_COUNT="$T/pr-concurrent.submits" \
    GH_POSTED_BODY="$T/pr-concurrent-one.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" >/dev/null 2>&1 &
  local first=$!
  PATH="$bin:$PATH" GH_MODE=concurrent GH_CALLS="$T/pr-concurrent.calls" \
    GH_REVIEW_MARKER="$T/pr-concurrent.marker" GH_DUP_BODY="$session/pr-review.md" \
    GH_SUBMIT_COUNT="$T/pr-concurrent.submits" \
    GH_POSTED_BODY="$T/pr-concurrent-two.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" >/dev/null 2>&1 &
  local second=$!
  wait "$first"; local first_rc=$?
  wait "$second"; local second_rc=$?
  assert_eq "first concurrent publication exits cleanly" "$first_rc" 0
  assert_eq "second concurrent publication exits cleanly" "$second_rc" 0
  assert_eq "concurrent retries create exactly one review" \
    "$(cat "$T/pr-concurrent.submits" | wc -l | tr -d ' ')" 1

  local clone_one="$T/pr-clone-one" clone_two="$T/pr-clone-two"
  local clone_session_one="$T/pr-clone-session-one" clone_session_two="$T/pr-clone-session-two"
  local clone_base clone_first clone_second clone_first_rc clone_second_rc
  pr_review_session "$clone_session_one" "$clone_one"
  git clone -q "$clone_one" "$clone_two"
  git -C "$clone_two" remote set-url origin https://github.com/acme/repo.git
  clone_base=$(git -C "$clone_one" rev-parse main)
  git -C "$clone_two" branch main "$clone_base"
  mkdir -p "$clone_session_two"
  cp "$clone_session_one/pr-review.json" "$clone_session_two/pr-review.json"
  printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" \
    "$clone_base" "$clone_two" > "$clone_session_two/scope.env"
  : > "$T/pr-clone-render.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-clone-render.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$clone_session_one" \
    --date 2026-09-15 >/dev/null
  PATH="$bin:$PATH" GH_CALLS="$T/pr-clone-render.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$clone_session_two" \
    --date 2026-09-15 >/dev/null
  rm -rf "$T/pr-clone.marker.pending" "$T/pr-clone.marker.commented" \
    "$T/pr-clone.marker.submit"
  : > "$T/pr-clone.calls"
  : > "$T/pr-clone.submits"
  PATH="$bin:$PATH" GH_MODE=concurrent GH_CALLS="$T/pr-clone.calls" \
    GH_REVIEW_MARKER="$T/pr-clone.marker" \
    GH_DUP_BODY="$clone_session_one/pr-review.md" \
    GH_SUBMIT_COUNT="$T/pr-clone.submits" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$clone_session_one" \
    > "$T/pr-clone-one.out" 2> "$T/pr-clone-one.err" &
  clone_first=$!
  PATH="$bin:$PATH" GH_MODE=concurrent GH_CALLS="$T/pr-clone.calls" \
    GH_REVIEW_MARKER="$T/pr-clone.marker" \
    GH_DUP_BODY="$clone_session_one/pr-review.md" \
    GH_SUBMIT_COUNT="$T/pr-clone.submits" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$clone_session_two" \
    > "$T/pr-clone-two.out" 2> "$T/pr-clone-two.err" &
  clone_second=$!
  wait "$clone_first"; clone_first_rc=$?
  wait "$clone_second"; clone_second_rc=$?
  assert_eq "first separate-clone publication exits cleanly" "$clone_first_rc" 0
  assert_eq "second separate-clone publication exits cleanly" "$clone_second_rc" 0
  assert_eq "separate clones submit one COMMENTED review" \
    "$(cat "$T/pr-clone.submits" | wc -l | tr -d ' ')" 1
  assert_exit "separate clones leave no pending review" 0 \
    test ! -d "$T/pr-clone.marker.pending"

  local final_session="$T/pr-finalize-lock" final_root="$T/pr-finalize-lock-repo"
  local final_head finalize_pid publish_pid finalize_rc publish_rc
  pr_review_session "$final_session" "$final_root"
  python3 - "$final_session/pr-review.json" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data.pop('fixed_in')
path.write_text(json.dumps(data))
PY
  pin_pr_review_links "$final_session" "$final_root"
  : > "$T/pr-finalize-lock-render.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-finalize-lock-render.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$final_session" --date 2026-09-15 >/dev/null
  git -C "$final_root" commit -q --allow-empty -m 'apply review findings'
  final_head=$(git -C "$final_root" rev-parse HEAD)
  rm -f "$T/pr-finalize-lock.entered" "$T/pr-finalize-lock.release"
  : > "$T/pr-finalize-lock.calls"
  : > "$T/pr-publish-lock.calls"
  PATH="$bin:$PATH" GH_HEAD_OID="$final_head" \
    GH_BLOCK_ENTERED="$T/pr-finalize-lock.entered" \
    GH_BLOCK_RELEASE="$T/pr-finalize-lock.release" \
    GH_CALLS="$T/pr-finalize-lock.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" finalize-stack "$final_session" \
    --head "$final_head" >/dev/null 2>&1 &
  finalize_pid=$!
  for _ in $(seq 1 100); do
    [ ! -e "$T/pr-finalize-lock.entered" ] || break
    sleep 0.05
  done
  assert_exit "finalization reaches the guarded GitHub read" 0 \
    test -e "$T/pr-finalize-lock.entered"
  PATH="$bin:$PATH" GH_HEAD_OID="$final_head" GH_CALLS="$T/pr-publish-lock.calls" \
    GH_POSTED_BODY="$T/pr-publish-lock.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$final_session" >/dev/null 2>&1 &
  publish_pid=$!
  sleep 0.2
  assert_nogrep "publication waits while finalization owns the state lock" \
    "$T/pr-publish-lock.calls" '.'
  : > "$T/pr-finalize-lock.release"
  wait "$finalize_pid"; finalize_rc=$?
  wait "$publish_pid"; publish_rc=$?
  assert_eq "locked finalization exits cleanly" "$finalize_rc" 0
  assert_eq "publication resumes after locked finalization" "$publish_rc" 0
  assert_exit "publication posts only the finalized body" 0 \
    cmp -s "$final_session/pr-review.md" "$T/pr-publish-lock.md"
  assert_eq "locked finalization and publication retain one target head" \
    "$(jq -r .head "$final_session/pr-review-target.json")" "$final_head"
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
  assert_nogrep "duplicate path never creates another review" "$T/pr-duplicate.calls" \
    '^api --method POST '

  : > "$T/pr-duplicate.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_DUP_STATE=PENDING \
    GH_DUP_BODY="$session/pr-review.md" GH_CALLS="$T/pr-duplicate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-pending-recovery.out" 2> "$T/pr-pending-recovery.err"
  assert_eq "an exact owned pending review is recovered" "$?" 0
  assert_grep "pending recovery submits the owned review" "$T/pr-duplicate.calls" \
    '^api --method POST repos/acme/repo/pulls/12/reviews/80/events --input -$'

  printf '%s\n' 'different pending body' > "$T/pr-unrelated-pending.md"
  : > "$T/pr-duplicate.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_DUP_STATE=PENDING \
    GH_DUP_BODY="$T/pr-unrelated-pending.md" GH_CALLS="$T/pr-duplicate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-unrelated-pending.out" 2> "$T/pr-unrelated-pending.err"
  assert_eq "an unrelated owned pending review blocks publication" "$?" 1
  assert_grep "unrelated pending review has an actionable diagnostic" \
    "$T/pr-unrelated-pending.err" 'unrelated pending review.*submit or discard it on GitHub'
  assert_nogrep "unrelated pending review is never submitted or deleted" \
    "$T/pr-duplicate.calls" 'reviews/80($|/events)'

  : > "$T/pr-duplicate.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_DUP_STATE=PENDING GH_DUP_COMMENTS=1 \
    GH_DUP_BODY="$session/pr-review.md" GH_CALLS="$T/pr-duplicate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-commented-pending.out" 2> "$T/pr-commented-pending.err"
  assert_eq "a comment-bearing pending review blocks publication" "$?" 1
  assert_grep "comment-bearing pending review names its unsafe state" \
    "$T/pr-commented-pending.err" 'pending review.*inline comments'
  assert_nogrep "comment-bearing pending review is never submitted or deleted" \
    "$T/pr-duplicate.calls" 'reviews/80($|/events)'

  : > "$T/pr-duplicate.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_DUP_STATE=PENDING GH_DUP_ACTOR=other \
    GH_DUP_ID=81 GH_DUP_BODY="$session/pr-review.md" GH_CALLS="$T/pr-duplicate.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-foreign-pending.out" 2> "$T/pr-foreign-pending.err"
  assert_eq "a foreign pending review does not block owned publication" "$?" 0
  assert_nogrep "foreign pending review is never submitted or deleted" \
    "$T/pr-duplicate.calls" 'reviews/81($|/events)'
  assert_grep "publisher submits only its own new pending review" \
    "$T/pr-duplicate.calls" 'reviews/80/events'

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
  printf "REV_BASE='%s'\nREV_ROOT='%s'\nREV_BRANCH='feat'\nREV_BASE_BRANCH='main'\n" \
    "$(git -C "$no_remote_root" rev-parse main)" "$no_remote_root" \
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
  assert_nogrep "branch without a PR never attempts a review" "$T/pr-no-open.calls" \
    '^api --method POST '
}

test_pr_review_publish_failure() {
  local session="$T/pr-failure" root="$T/pr-failure-repo" bin="$T/pr-failure-bin" base moved_head
  pr_review_session "$session" "$root"
  pr_review_gh_shim "$bin"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-failure.calls" \
    GH_POSTED_BODY="$T/pr-failure-body" \
    python3 "$SCRIPTS/rev-pr-review.py" render "$session" --date 2026-09-15 >/dev/null
  cp "$session/pr-review.json" "$T/pr-failure-input.json"
  cp "$session/pr-review.md" "$T/pr-failure-rendered.md"
  cp "$session/pr-review-target.json" "$T/pr-failure-target.json"
  cp "$session/scope.env" "$T/pr-failure-scope.env"
  base=$(git -C "$root" rev-parse main)
  moved_head=$(printf '%040d' 7)
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
  assert_exit "failed publication writes the durable failure receipt" 0 \
    test -s "$session/incomplete.md"
  assert_grep "failure receipt preserves GitHub's diagnostic" \
    "$session/incomplete.md" 'remote rejected review'
  assert_grep "failure receipt preserves the exact retry command" \
    "$session/incomplete.md" "retry: .*rev-pr-review.py publish $session$"
  assert_exit "failure receipt preserves the structured input" 0 \
    cmp -s "$session/pr-review.json" "$T/pr-failure-input.json"
  assert_exit "failure receipt preserves the rendered review" 0 \
    cmp -s "$session/pr-review.md" "$T/pr-failure-rendered.md"
  assert_exit "failure receipt preserves the frozen target" 0 \
    cmp -s "$session/pr-review-target.json" "$T/pr-failure-target.json"

  rm -f "$T/pr-close-create.marker"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=close-create GH_CALLS="$T/pr-failure.calls" \
    GH_REVIEW_MARKER="$T/pr-close-create.marker" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-close-create.out" 2> "$T/pr-close-create.err"
  assert_eq "closure at pending creation becomes a clean skip" "$?" 0
  assert_grep "creation-boundary closure explains the skip" "$T/pr-close-create.out" \
    '^pr-review: no associated open PR; skipped$'
  assert_exit "creation-boundary closure clears the failure receipt" 0 \
    test ! -e "$session/incomplete.md"
  assert_nogrep "creation-boundary closure never submits or deletes a draft" \
    "$T/pr-failure.calls" 'reviews/[0-9]+(/events)?$'

  rm -f "$T/pr-close-submit.marker"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=close-submit GH_CALLS="$T/pr-failure.calls" \
    GH_REVIEW_MARKER="$T/pr-close-submit.marker" GH_DUP_BODY="$session/pr-review.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-close-submit.out" 2> "$T/pr-close-submit.err"
  assert_eq "closure at pending submission becomes a clean skip" "$?" 0
  assert_grep "submission-boundary closure explains the skip" "$T/pr-close-submit.out" \
    '^pr-review: no associated open PR; skipped$'
  assert_grep "submission-boundary closure deletes the exact owned draft" \
    "$T/pr-failure.calls" '^api --method DELETE repos/acme/repo/pulls/12/reviews/80$'
  assert_exit "submission-boundary closure clears the failure receipt" 0 \
    test ! -e "$session/incomplete.md"

  rm -f "$T/pr-ambiguous-create.marker"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=ambiguous-create GH_CALLS="$T/pr-failure.calls" \
    GH_REVIEW_MARKER="$T/pr-ambiguous-create.marker" \
    GH_DUP_BODY="$session/pr-review.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-ambiguous-create.out" 2> "$T/pr-ambiguous-create.err"
  assert_eq "ambiguous pending creation recovers through the review list" "$?" 0
  assert_grep "ambiguous creation submits the recovered pending review" \
    "$T/pr-failure.calls" 'reviews/80/events'
  assert_nogrep "ambiguous creation preserves the recovered pending review" \
    "$T/pr-failure.calls" '^api --method DELETE '
  assert_exit "ambiguous creation recovery clears the failure receipt" 0 \
    test ! -e "$session/incomplete.md"

  rm -f "$T/pr-ambiguous-submit.marker"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=ambiguous-submit GH_CALLS="$T/pr-failure.calls" \
    GH_REVIEW_MARKER="$T/pr-ambiguous-submit.marker" \
    GH_DUP_BODY="$session/pr-review.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-ambiguous-submit.out" 2> "$T/pr-ambiguous-submit.err"
  assert_eq "ambiguous pending submission recovers exact COMMENTED state" "$?" 0
  assert_exit "ambiguous submission recovery clears the failure receipt" 0 \
    test ! -e "$session/incomplete.md"

  rm -f "$T/pr-post-confirm-move.marker"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=post-confirm-move GH_CALLS="$T/pr-failure.calls" \
    GH_REVIEW_MARKER="$T/pr-post-confirm-move.marker" GH_DUP_BODY="$session/pr-review.md" \
    GH_SWITCHED_HEAD="$moved_head" GH_MERGE_BASE="$base" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-post-confirm-move.out" 2> "$T/pr-post-confirm-move.err"
  assert_eq "confirmed submission remains successful after a head move" "$?" 0
  assert_exit "confirmed submission clears the failure receipt" 0 \
    test ! -e "$session/incomplete.md"

  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=post-confirm-move GH_CALLS="$T/pr-failure.calls" \
    GH_REVIEW_MARKER="$T/pr-post-confirm-move.marker" GH_DUP_BODY="$session/pr-review.md" \
    GH_SWITCHED_HEAD="$moved_head" GH_MERGE_BASE="$base" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-post-confirm-retry.out" 2> "$T/pr-post-confirm-retry.err"
  assert_eq "moved-head retry recognizes the exact frozen review" "$?" 0
  assert_grep "moved-head retry reports exact idempotence" "$T/pr-post-confirm-retry.out" \
    'identical review already posted'
  assert_nogrep "moved-head retry creates no second review" "$T/pr-failure.calls" \
    '^api --method POST '

  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=invalid-post-json GH_CALLS="$T/pr-failure.calls" \
    GH_POSTED_BODY="$T/pr-failure-invalid-body.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-failure-invalid.out" 2> "$T/pr-failure-invalid.err"
  assert_eq "invalid post confirmation fails publication" "$?" 1
  assert_grep "invalid confirmation occurs after the remote side effect" \
    "$T/pr-failure.calls" '^api --method POST '
  assert_grep "invalid confirmation preserves the exact retry command" \
    "$T/pr-failure-invalid.err" "retry: .*rev-pr-review.py publish $session$"
  assert_grep "invalid confirmation updates the failure receipt" \
    "$session/incomplete.md" 'invalid created-review JSON'

  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=mismatched-post GH_CALLS="$T/pr-failure.calls" \
    GH_POSTED_BODY="$T/pr-failure-mismatched-body.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-failure-mismatched.out" 2> "$T/pr-failure-mismatched.err"
  assert_eq "mismatched post confirmation fails publication" "$?" 1
  assert_grep "mismatched confirmation reaches the commit-pinned gate" \
    "$T/pr-failure-mismatched.err" \
    'GitHub did not confirm the exact owned PENDING review'
  assert_grep "mismatched confirmation preserves the exact retry command" \
    "$T/pr-failure-mismatched.err" "retry: .*rev-pr-review.py publish $session$"
  assert_grep "mismatched confirmation updates the failure receipt" \
    "$session/incomplete.md" 'did not confirm the exact owned PENDING review'
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_MODE=duplicate GH_CALLS="$T/pr-failure.calls" \
    GH_DUP_BODY="$session/pr-review.md" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-failure-retry.out" 2> "$T/pr-failure-retry.err"
  assert_eq "retry after ambiguous confirmation is idempotent" "$?" 0
  assert_nogrep "ambiguous-confirmation retry creates no duplicate" \
    "$T/pr-failure.calls" '^api --method POST '
  assert_exit "successful duplicate retry clears the failure receipt" 0 \
    test ! -e "$session/incomplete.md"

  echo tampered >> "$session/pr-review.md"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-failure.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-failure-predispatch.out" 2> "$T/pr-failure-predispatch.err"
  assert_eq "pre-dispatch publication failure is terminal" "$?" 1
  assert_grep "pre-dispatch failure receipt names the frozen body" \
    "$session/incomplete.md" 'frozen body hash'
  assert_grep "pre-dispatch failure receipt contains the exact retry" \
    "$session/incomplete.md" "retry: .*rev-pr-review.py publish $session$"
  cp "$T/pr-failure-rendered.md" "$session/pr-review.md"
  PATH="$bin:$PATH" NO_PUSH=1 GH_CALLS="$T/pr-failure.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-failure-no-push.out" 2> "$T/pr-failure-no-push.err"
  assert_eq "no-push retry is a clean skip" "$?" 0
  assert_exit "no-push retry clears the stale failure receipt" 0 \
    test ! -e "$session/incomplete.md"

  local artifact original
  for artifact in scope.env pr-review-target.json pr-review.md; do
    case "$artifact" in
      scope.env) original="$T/pr-failure-scope.env";;
      pr-review-target.json) original="$T/pr-failure-target.json";;
      pr-review.md) original="$T/pr-failure-rendered.md";;
    esac
    printf '\377' > "$session/$artifact"
    cp "$session/$artifact" "$T/pr-failure-invalid-bytes"
    : > "$T/pr-failure.calls"
    PATH="$bin:$PATH" GH_CALLS="$T/pr-failure.calls" \
      python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
      > "$T/pr-failure-invalid-text.out" 2> "$T/pr-failure-invalid-text.err"
    assert_eq "invalid UTF-8 in $artifact fails publication cleanly" "$?" 1
    assert_nogrep "invalid UTF-8 in $artifact emits no traceback" \
      "$T/pr-failure-invalid-text.err" 'Traceback'
    assert_nogrep "invalid UTF-8 in $artifact never posts" \
      "$T/pr-failure.calls" '^api --method POST '
    assert_grep "invalid UTF-8 in $artifact writes the exact retry" \
      "$session/incomplete.md" "retry: .*rev-pr-review.py publish $session$"
    assert_exit "invalid UTF-8 in $artifact remains unchanged" 0 \
      cmp -s "$session/$artifact" "$T/pr-failure-invalid-bytes"
    cp "$original" "$session/$artifact"
  done

  printf "REV_BASE='unterminated\n" > "$session/scope.env"
  cp "$session/scope.env" "$T/pr-failure-invalid-scope.env"
  : > "$T/pr-failure.calls"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-failure.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$session" \
    > "$T/pr-failure-invalid-scope.out" 2> "$T/pr-failure-invalid-scope.err"
  assert_eq "unterminated scope value fails publication cleanly" "$?" 1
  assert_nogrep "unterminated scope value emits no traceback" \
    "$T/pr-failure-invalid-scope.err" 'Traceback'
  assert_nogrep "unterminated scope value never posts" \
    "$T/pr-failure.calls" '^api --method POST '
  assert_grep "unterminated scope value writes the parse failure" \
    "$session/incomplete.md" 'No closing quotation'
  assert_grep "unterminated scope value writes the exact retry" \
    "$session/incomplete.md" "retry: .*rev-pr-review.py publish $session$"
  assert_exit "unterminated scope value remains unchanged" 0 \
    cmp -s "$session/scope.env" "$T/pr-failure-invalid-scope.env"
  cp "$T/pr-failure-scope.env" "$session/scope.env"

  local missing="$T/pr-failure-missing-session"
  PATH="$bin:$PATH" GH_CALLS="$T/pr-failure.calls" \
    python3 "$SCRIPTS/rev-pr-review.py" publish "$missing" \
    > "$T/pr-failure-missing.out" 2> "$T/pr-failure-missing.err"
  assert_eq "missing publication session fails" "$?" 1
  assert_exit "missing publication session is not created for a receipt" 0 \
    test ! -e "$missing"
}
