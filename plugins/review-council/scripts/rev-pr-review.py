#!/usr/bin/env python3
"""Render and publish the canonical Review Council pull-request review."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


BAD_INLINE = re.compile(r"[\r\n]")
PR_URL = re.compile(r"^https://github\.com/([^/]+/[^/]+)/pull/([1-9][0-9]*)/?$")


class ReviewError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReviewError(message)


def inline(value, field):
    require(isinstance(value, str) and value.strip(), f"{field} must be a nonempty string")
    require(not BAD_INLINE.search(value), f"{field} must fit on one line")
    return value.strip()


def count(value, field, positive=False):
    require(isinstance(value, int) and not isinstance(value, bool), f"{field} must be an integer")
    require(value >= (1 if positive else 0), f"{field} is out of range")
    return value


def link(value, field, code=False):
    require(isinstance(value, dict), f"{field} must be an object")
    label = inline(value.get("label"), f"{field}.label")
    url = inline(value.get("url"), f"{field}.url")
    require(url.startswith("https://") and " " not in url and ")" not in url,
            f"{field}.url must be an HTTPS URL without spaces or closing parentheses")
    require("]" not in label and (not code or "`" not in label),
            f"{field}.label contains Markdown delimiters")
    return f"[`{label}`]({url})" if code else f"[{label}]({url})"


def inline_list(value, field, allow_empty=False):
    require(isinstance(value, list), f"{field} must be a list")
    require(allow_empty or value, f"{field} must not be empty")
    return [inline(item, f"{field}[{index}]") for index, item in enumerate(value)]


def load_input(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReviewError(f"cannot read {path}: {error}") from error
    require(isinstance(data, dict), "pr-review.json must contain an object")
    return data


def render(data, date):
    verdict = data.get("verdict")
    require(isinstance(verdict, dict), "verdict must be an object")
    headline = inline(verdict.get("headline"), "verdict.headline")
    detail = inline(verdict.get("detail"), "verdict.detail")
    require("**" not in headline, "verdict.headline contains a Markdown delimiter")
    panels = count(data.get("panels"), "panels", positive=True)
    rejected = count(data.get("rejected"), "rejected")
    gates = inline(data.get("gates"), "gates")
    panel = inline_list(data.get("panel"), "panel")
    decisions = data.get("decisions")
    fixes = data.get("fixes")
    require(isinstance(decisions, list), "decisions must be a list")
    require(isinstance(fixes, list), "fixes must be a list")
    verified = inline_list(data.get("verified_sound"), "verified_sound")
    coverage = inline_list(data.get("coverage"), "coverage")
    date = inline(date, "date")
    require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date) is not None,
            "date must use YYYY-MM-DD")

    decision_rows = []
    decision_details = []
    for index, decision in enumerate(decisions):
        field = f"decisions[{index}]"
        require(isinstance(decision, dict), f"{field} must be an object")
        title = inline(decision.get("title"), f"{field}.title")
        require("**" not in title, f"{field}.title contains a Markdown delimiter")
        location = link(decision.get("location"), f"{field}.location", code=True)
        decision_rows.append(f"- **{title}** · {location}")
        decision_details.append(
            f"{index + 1}. **{title}** {inline(decision.get('detail'), f'{field}.detail')}"
        )

    fix_rows = []
    commit_urls = set()
    for index, fix in enumerate(fixes):
        field = f"fixes[{index}]"
        require(isinstance(fix, dict), f"{field} must be an object")
        severity = inline(fix.get("severity"), f"{field}.severity")
        require(re.fullmatch(r"P[0-3]", severity) is not None,
                f"{field}.severity must be P0, P1, P2, or P3")
        summary = inline(fix.get("summary"), f"{field}.summary").replace("|", "\\|")
        commit = fix.get("commit")
        commit_link = link(commit, f"{field}.commit", code=True)
        commit_urls.add(commit["url"])
        fix_rows.append(f"| `{severity}` | {summary} | {commit_link} |")

    fixed = len(fixes)
    decisions_count = len(decisions)
    total = fixed + decisions_count + rejected
    fixed_phrase = f"{fixed} fixed"
    if data.get("fixed_in") is not None:
        require(fixed > 0, "fixed_in requires at least one fix")
        fixed_phrase += " in " + link(data["fixed_in"], "fixed_in")
    commit_count = len(commit_urls)
    commit_word = "commit" if commit_count == 1 else "commits"
    if not decision_rows:
        decision_rows = ["- None."]
        decision_details = ["No decisions remain."]
    if not fix_rows:
        fix_rows = ["| - | No fixes required | - |"]

    lines = [
        "[![Reviewed by review-council](https://img.shields.io/badge/reviewed_by-review--council-5b21b6?style=flat-square)](https://github.com/WiktorStarczewski/review-council)",
        "",
        "## Review summary",
        "",
        "> [!TIP]",
        f"> **{headline}** {detail}",
        "",
        f"{panels} panels · {total} findings: {fixed_phrase}, {decisions_count} for you, {rejected} rejected · gates {gates}",
        "Panel: " + " · ".join(panel) + ", each at maximum effort",
        "",
        "### Decisions for you",
        "",
        *decision_rows,
        "",
        "<details>",
        "<summary>Decisions in detail</summary>",
        "",
        *decision_details,
        "",
        "</details>",
        "",
        "<details>",
        f"<summary>Fixes ({commit_count} {commit_word})</summary>",
        "",
        "| Severity | Fix | Commit |",
        "| :-- | :-- | :-- |",
        *fix_rows,
        "",
        "</details>",
        "",
        "<details>",
        "<summary>Verified sound</summary>",
        "",
        *(f"- {item}" for item in verified),
        "",
        "</details>",
        "",
        "<details>",
        "<summary>Coverage</summary>",
        "",
        *(f"- {item}" for item in coverage),
        "",
        "</details>",
        "",
        '<sub>Reviewed by <a href="https://github.com/WiktorStarczewski/review-council">review-council</a>, an independent multi-model review panel. Every finding was checked against the source before it was fixed or reported. ' + date + "</sub>",
    ]
    return "\n".join(lines) + "\n"


def write_atomic(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pr-review-", text=True)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(body)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_scope(path):
    if not path.is_file():
        return None
    values = {}
    for raw in path.read_text().splitlines():
        if not raw or "=" not in raw:
            continue
        key, encoded = raw.split("=", 1)
        parsed = shlex.split(encoded, posix=True)
        require(len(parsed) == 1, f"invalid {key} in {path}")
        values[key] = parsed[0]
    root = values.get("REV_ROOT")
    require(root and Path(root).is_dir(), f"scope has no usable REV_ROOT: {path}")
    return Path(root)


def run_gh(arguments, root):
    return subprocess.run(["gh", *arguments], cwd=root, text=True,
                          capture_output=True, timeout=120)


def has_github_remote(root):
    remotes = subprocess.run(["git", "remote"], cwd=root, text=True,
                             capture_output=True, timeout=30)
    if remotes.returncode != 0:
        raise ReviewError("cannot inspect git remotes: " + remotes.stderr.strip())
    for name in remotes.stdout.splitlines():
        urls = subprocess.run(["git", "remote", "get-url", "--all", name], cwd=root,
                              text=True, capture_output=True, timeout=30)
        if urls.returncode != 0:
            raise ReviewError("cannot inspect git remote " + name + ": " + urls.stderr.strip())
        if any(re.search(r"(?:^|@|://)github\.com[:/]", url)
               for url in urls.stdout.splitlines()):
            return True
    return False


def resolve_pr(root):
    if not has_github_remote(root):
        return None
    require(shutil.which("gh") is not None, "gh is required to publish a PR review")
    result = run_gh(["pr", "view", "--json", "number,url"], root)
    if result.returncode != 0:
        if "no pull requests found" in result.stderr.lower():
            return None
        raise ReviewError("cannot resolve the current PR: " + result.stderr.strip())
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReviewError("gh pr view returned invalid JSON") from error
    require(isinstance(metadata, dict), "gh pr view returned an invalid object")
    number = metadata.get("number")
    url = metadata.get("url")
    require(isinstance(number, int) and number > 0 and isinstance(url, str),
            "gh pr view omitted number or URL")
    match = PR_URL.fullmatch(url)
    require(match is not None and int(match.group(2)) == number,
            "gh pr view returned an unsupported PR URL")
    return match.group(1), number, url


def existing_reviews(repo, number, root):
    result = run_gh(["api", "--paginate", "--slurp",
                     f"repos/{repo}/pulls/{number}/reviews?per_page=100"], root)
    if result.returncode != 0:
        raise ReviewError("cannot inspect existing PR reviews: " + result.stderr.strip())
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReviewError("gh api returned invalid review JSON") from error
    require(isinstance(pages, list), "gh api returned an invalid review list")
    reviews = []
    for page in pages:
        if isinstance(page, list):
            reviews.extend(page)
        elif isinstance(page, dict):
            reviews.append(page)
        else:
            raise ReviewError("gh api returned an invalid review page")
    return reviews


def render_session(session, date):
    body = render(load_input(session / "pr-review.json"), date)
    output = session / "pr-review.md"
    write_atomic(output, body)
    return output, body


def publish(session, date, script):
    root = parse_scope(session / "scope.env")
    if root is None:
        print("pr-review: no associated open PR; skipped")
        return
    target = resolve_pr(root)
    if target is None:
        print("pr-review: no associated open PR; skipped")
        return
    repo, number, url = target
    output, body = render_session(session, date)
    if any(isinstance(review, dict) and review.get("body") == body
           for review in existing_reviews(repo, number, root)):
        print(f"pr-review: identical review already posted on {url}")
        return
    result = run_gh(["pr", "review", str(number), "--repo", repo, "--comment",
                     "--body-file", str(output)], root)
    if result.returncode != 0:
        retry = shlex.join([sys.executable, str(script), "publish", str(session)])
        raise ReviewError("GitHub review post failed: " + result.stderr.strip() +
                          "\npr-review: retry: " + retry)
    print(f"pr-review: posted {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("render", "publish"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("session", type=Path)
        subparser.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args()
    session = args.session.expanduser().absolute()
    try:
        if args.command == "render":
            output, _ = render_session(session, args.date)
            print(output)
        else:
            publish(session, args.date, Path(__file__).resolve())
    except (OSError, ReviewError, subprocess.SubprocessError) as error:
        print(f"pr-review: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
