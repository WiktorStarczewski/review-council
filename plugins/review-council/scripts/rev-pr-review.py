#!/usr/bin/env python3
"""Render and publish the canonical Review Council pull-request review."""
import argparse
import datetime
import hashlib
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
BLOB_URL = re.compile(r"^(https://github\.com/[^/]+/[^/]+/blob/)[0-9a-f]{7,40}(/.*)$")
COMMIT_URL = re.compile(r"^(https://github\.com/[^/]+/[^/]+/commit/)[0-9a-f]{7,40}/?$")
COMMIT_ID_URL = re.compile(
    r"^https://github\.com/([^/]+/[^/]+)/commit/([0-9a-f]{7,40})/?$", re.IGNORECASE)
GITHUB_REMOTE = re.compile(
    r"^(?:(?:https?|git)://|ssh://git@|git@)github\.com[:/]"
    r"([^/\s]+/[^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
OID = re.compile(r"^[0-9a-f]{40}$")


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


def inline_list(value, field):
    require(isinstance(value, list), f"{field} must be a list")
    require(value, f"{field} must not be empty")
    return [inline(item, f"{field}[{index}]") for index, item in enumerate(value)]


def load_input(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReviewError(f"cannot read {path}: {error}") from error
    require(isinstance(data, dict), "pr-review.json must contain an object")
    return data


def commit_identity(url):
    normalized = url.rstrip("/")
    match = COMMIT_ID_URL.fullmatch(normalized)
    if match is None:
        return (normalized, None)
    return (match.group(1).lower(), match.group(2).lower())


def same_commit(left, right):
    if left[1] is None or right[1] is None:
        return left == right
    return left[0] == right[0] and (
        left[1].startswith(right[1]) or right[1].startswith(left[1]))


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
    commit_identities = []
    for index, fix in enumerate(fixes):
        field = f"fixes[{index}]"
        require(isinstance(fix, dict), f"{field} must be an object")
        severity = inline(fix.get("severity"), f"{field}.severity")
        require(re.fullmatch(r"P[0-3]", severity) is not None,
                f"{field}.severity must be P0, P1, P2, or P3")
        summary = inline(fix.get("summary"), f"{field}.summary").replace("|", "\\|")
        commit = fix.get("commit")
        commit_link = link(commit, f"{field}.commit", code=True)
        identity = commit_identity(inline(commit.get("url"), f"{field}.commit.url"))
        if not any(same_commit(identity, existing) for existing in commit_identities):
            commit_identities.append(identity)
        fix_rows.append(f"| `{severity}` | {summary} | {commit_link} |")

    fixed = len(fixes)
    decisions_count = len(decisions)
    total = fixed + decisions_count + rejected
    fixed_phrase = f"{fixed} fixed"
    if data.get("fixed_in") is not None:
        require(fixed > 0, "fixed_in requires at least one fix")
        fixed_phrase += " in " + link(data["fixed_in"], "fixed_in")
    commit_count = len(commit_identities)
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
    require(path.is_file(), f"required session scope is missing: {path}")
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
    branch = values.get("REV_BRANCH")
    base = values.get("REV_BASE")
    base_branch = values.get("REV_BASE_BRANCH")
    require(branch and base_branch and base and OID.fullmatch(base) is not None,
            f"scope has no usable reviewed base or branch identity: {path}")
    return {"root": Path(root), "branch": branch, "base": base,
            "base_branch": base_branch}


def run_gh(arguments, root):
    environment = os.environ.copy()
    environment.pop("GH_REPO", None)
    return subprocess.run(["gh", *arguments], cwd=root, text=True,
                          capture_output=True, timeout=120, env=environment)


def run_git(arguments, root):
    result = subprocess.run(["git", *arguments], cwd=root, text=True,
                            capture_output=True, timeout=30)
    if result.returncode != 0:
        raise ReviewError("git " + " ".join(arguments) + " failed: " + result.stderr.strip())
    return result.stdout.strip()


def github_repositories(root):
    remotes = subprocess.run(["git", "remote"], cwd=root, text=True,
                             capture_output=True, timeout=30)
    if remotes.returncode != 0:
        raise ReviewError("cannot inspect git remotes: " + remotes.stderr.strip())
    repositories = []
    for name in remotes.stdout.splitlines():
        urls = subprocess.run(["git", "remote", "get-url", "--all", name], cwd=root,
                              text=True, capture_output=True, timeout=30)
        if urls.returncode != 0:
            raise ReviewError("cannot inspect git remote " + name + ": " + urls.stderr.strip())
        for url in urls.stdout.splitlines():
            match = GITHUB_REMOTE.fullmatch(url.strip())
            if match is not None:
                repository = match.group(1)
                if repository.lower() not in {item.lower() for item in repositories}:
                    repositories.append(repository)
    return repositories


def parse_pr(metadata, branch):
    require(isinstance(metadata, dict), "gh returned an invalid PR object")
    number = metadata.get("number")
    url = metadata.get("url")
    state = metadata.get("state")
    head_branch = metadata.get("headRefName")
    head = metadata.get("headRefOid")
    base_branch = metadata.get("baseRefName")
    base_head = metadata.get("baseRefOid")
    require(isinstance(number, int) and number > 0 and isinstance(url, str),
            "gh omitted the PR number or URL")
    match = PR_URL.fullmatch(url)
    require(match is not None and int(match.group(2)) == number,
            "gh returned an unsupported PR URL")
    require(state in ("OPEN", "CLOSED", "MERGED"), "gh omitted the PR state")
    require(head_branch == branch, "gh returned a PR for a different branch")
    require(isinstance(head, str) and OID.fullmatch(head) is not None,
            "gh omitted the PR head")
    require(isinstance(base_branch, str) and base_branch,
            "gh omitted the PR base branch")
    require(isinstance(base_head, str) and OID.fullmatch(base_head) is not None,
            "gh omitted the PR base head")
    return {
        "repo": match.group(1), "number": number, "url": url, "state": state,
        "branch": head_branch, "head": head,
        "base_branch": base_branch, "base_head": base_head,
    }


def resolve_pr(scope):
    root = scope["root"]
    repositories = github_repositories(root)
    if not repositories:
        return None
    require(shutil.which("gh") is not None, "gh is required to publish a PR review")
    targets = []
    for repository in repositories:
        result = run_gh([
            "pr", "view", scope["branch"], "--repo", repository,
            "--json", "number,url,state,headRefName,headRefOid,baseRefName,baseRefOid",
        ], root)
        if result.returncode != 0:
            if "no pull requests found" in result.stderr.lower():
                continue
            raise ReviewError("cannot resolve the scoped PR: " + result.stderr.strip())
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ReviewError("gh pr view returned invalid JSON") from error
        target = parse_pr(metadata, scope["branch"])
        require(target["repo"].lower() == repository.lower(),
                "gh returned a PR outside the reviewed repository remotes")
        if target["state"] != "OPEN":
            continue
        merge_base = run_git(["merge-base", target["head"], target["base_head"]], root)
        require(merge_base == scope["base"],
                "the open PR merge base does not match the reviewed base")
        targets.append(target)
    require(len(targets) <= 1,
            "more than one reviewed GitHub remote has an open PR for this branch")
    return targets[0] if targets else None


def live_pr(target, root):
    result = run_gh([
        "pr", "view", str(target["number"]), "--repo", target["repo"],
        "--json", "number,url,state,headRefName,headRefOid,baseRefName,baseRefOid",
    ], root)
    if result.returncode != 0:
        raise ReviewError("cannot revalidate the frozen PR: " + result.stderr.strip())
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReviewError("gh pr view returned invalid JSON") from error
    live = parse_pr(metadata, target["branch"])
    require(live["repo"] == target["repo"] and live["number"] == target["number"]
            and live["url"] == target["url"], "the frozen PR identity changed")
    require(live["base_branch"] == target["base_branch"]
            and live["base_head"] == target["base_head"],
            "the PR base changed after review; rerun the review before publishing")
    return live


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
    require(all(isinstance(page, list) for page in pages),
            "gh api returned an invalid review page")
    return [review for page in pages for review in page]


def body_hash(body):
    return hashlib.sha256(body.encode()).hexdigest()


def require_clean_review_tree(root, session):
    arguments = ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."]
    try:
        relative = session.resolve().relative_to(root.resolve())
    except ValueError:
        relative = None
    if relative is not None:
        require(relative != Path("."), "the review session cannot be the repository root")
        session_path = relative.as_posix()
        arguments.extend([
            f":(top,exclude){session_path}",
            f":(top,exclude){session_path}/**",
        ])
    require(not run_git(arguments, root),
            "the reviewed repository has staged, unstaged, or untracked bytes outside "
            "the PR head; commit them and rerun the review before publishing")


def target_envelope(scope, target, body, date, session, allow_unpushed=False):
    root = scope["root"]
    head = run_git(["rev-parse", "HEAD"], root)
    tree = run_git(["rev-parse", "HEAD^{tree}"], root)
    require(OID.fullmatch(head) is not None and OID.fullmatch(tree) is not None,
            "git returned an invalid reviewed identity")
    envelope = {
        "version": 1,
        "associated": target is not None,
        "branch": scope["branch"],
        "base": scope["base"],
        "base_branch": target["base_branch"] if target is not None else scope["base_branch"],
        "head": head,
        "tree": tree,
        "date": date,
        "body_sha256": body_hash(body),
    }
    if target is not None:
        require_clean_review_tree(root, session)
        require(allow_unpushed or target["head"] == head,
                "the open PR head does not match the reviewed local head; push before rendering")
        envelope.update({key: target[key] for key in (
            "repo", "number", "url", "base_head")})
    return envelope


def load_target(path):
    target = load_input(path)
    require(target.get("version") == 1, "unsupported PR review target version")
    require(isinstance(target.get("associated"), bool), "target association must be boolean")
    for field in ("branch", "base", "base_branch", "head", "tree", "date", "body_sha256"):
        inline(target.get(field), f"target.{field}")
    require(OID.fullmatch(target["base"]) is not None, "target.base must be a full commit ID")
    require(OID.fullmatch(target["head"]) is not None, "target.head must be a full commit ID")
    require(OID.fullmatch(target["tree"]) is not None, "target.tree must be a full tree ID")
    require(re.fullmatch(r"[0-9a-f]{64}", target["body_sha256"]) is not None,
            "target.body_sha256 must be SHA-256")
    if target["associated"]:
        inline(target.get("base_head"), "target.base_head")
        require(OID.fullmatch(target["base_head"]) is not None,
                "target.base_head must be a full commit ID")
        frozen = parse_pr({
            "number": target.get("number"), "url": target.get("url"), "state": "OPEN",
            "headRefName": target["branch"], "headRefOid": target["head"],
            "baseRefName": target["base_branch"], "baseRefOid": target["base_head"],
        }, target["branch"])
        require(frozen["repo"] == target.get("repo"), "target repository does not match its URL")
    return target


def render_session(session, date):
    data = load_input(session / "pr-review.json")
    body = render(data, date)
    scope_path = session / "scope.env"
    target = None
    if scope_path.is_file():
        scope = parse_scope(scope_path)
        target = target_envelope(
            scope, resolve_pr(scope), body, date, session,
            allow_unpushed=os.environ.get("REV_STACK_LEG") == "1",
        )
    output = session / "pr-review.md"
    write_atomic(output, body)
    if target is not None:
        write_atomic(session / "pr-review-target.json", json.dumps(target, indent=2) + "\n")
    return output, body


def unresolved_target_skip(scope, session):
    if (session / "pr-review-target.json").is_file():
        return False
    if resolve_pr(scope) is None:
        print("pr-review: no associated open PR; skipped")
        return True
    raise ReviewError("associated open PR has no rendered target; run render first")


def publish(session, script):
    scope = parse_scope(session / "scope.env")
    if os.environ.get("NO_PUSH") == "1":
        print("pr-review: NO_PUSH=1; skipped publication")
        return
    if unresolved_target_skip(scope, session):
        return
    target = load_target(session / "pr-review-target.json")
    if not target["associated"]:
        print("pr-review: no associated open PR; skipped")
        return
    output = session / "pr-review.md"
    require(output.is_file(), f"rendered PR review is missing: {output}")
    body = output.read_text()
    require(body_hash(body) == target["body_sha256"],
            "rendered PR review does not match its frozen body hash")
    live = live_pr(target, scope["root"])
    if live["state"] != "OPEN":
        print("pr-review: no associated open PR; skipped")
        return
    require(live["head"] == target["head"],
            "the PR head changed after review; rerun the review before publishing")
    if any(isinstance(review, dict) and review.get("body") == body
           and review.get("state") == "COMMENTED"
           for review in existing_reviews(target["repo"], target["number"], scope["root"])):
        print(f"pr-review: identical review already posted on {target['url']}")
        return
    result = run_gh(["pr", "review", str(target["number"]), "--repo", target["repo"],
                     "--comment", "--body-file", str(output)], scope["root"])
    if result.returncode != 0:
        retry = shlex.join([sys.executable, str(script), "publish", str(session)])
        raise ReviewError("GitHub review post failed: " + result.stderr.strip() +
                          "\npr-review: retry: " + retry)
    print(f"pr-review: posted {target['url']}")


def replace_sha_url(url, pattern, head, field):
    value = inline(url, field)
    match = pattern.fullmatch(value)
    require(match is not None, f"{field} must be a SHA-pinned GitHub URL")
    return match.group(1) + head + (match.group(2) if match.lastindex == 2 else "")


def finalized_body(data, date, head):
    updated = json.loads(json.dumps(data))
    for index, decision in enumerate(updated.get("decisions", [])):
        location = decision.get("location", {})
        location["url"] = replace_sha_url(
            location.get("url"), BLOB_URL, head, f"decisions[{index}].location.url")
    if updated.get("fixed_in") is None:
        for index, fix in enumerate(updated.get("fixes", [])):
            commit = fix.get("commit", {})
            label = inline(commit.get("label"), f"fixes[{index}].commit.label")
            commit["label"] = head[:min(len(label), len(head))]
            commit["url"] = replace_sha_url(
                commit.get("url"), COMMIT_URL, head, f"fixes[{index}].commit.url")
    return render(updated, date)


def finalize_stack(session, head, expected_root=None):
    require(OID.fullmatch(head) is not None, "--head must be a full commit ID")
    scope = parse_scope(session / "scope.env")
    if expected_root is not None:
        require(scope["root"].resolve() == Path(expected_root).resolve(),
                "stack finalization repository does not match the reviewed session")
    if unresolved_target_skip(scope, session):
        return
    target = load_target(session / "pr-review-target.json")
    if not target["associated"]:
        print("pr-review: no associated open PR; skipped")
        return
    root = scope["root"]
    require(run_git(["rev-parse", "HEAD"], root) == head,
            "stack finalization head does not match the local checkout")
    require(run_git(["rev-parse", f"{head}^{{tree}}"], root) == target["tree"],
            "stack finalization changed the reviewed tree")
    live = live_pr(target, root)
    require(live["state"] == "OPEN" and live["head"] == head,
            "the pushed PR head does not match stack finalization")

    data = load_input(session / "pr-review.json")
    source_body = render(data, target["date"])
    body = finalized_body(data, target["date"], head)
    output = session / "pr-review.md"
    require(output.is_file(), f"rendered PR review is missing: {output}")
    current_body = output.read_text()
    source_is_frozen = body_hash(source_body) == target["body_sha256"]
    if target["head"] == head and source_is_frozen:
        require(body_hash(current_body) == target["body_sha256"],
                "rendered PR review does not match its frozen body hash")
        print(f"pr-review: stack review already uses reviewed head {head}")
        return
    if not source_is_frozen:
        require(target["head"] == head and body_hash(current_body) == target["body_sha256"]
                and current_body == body,
                "structured PR review input does not match the frozen rendered review")
        print(f"pr-review: stack review already finalized at {head}")
        return
    require(body_hash(current_body) == target["body_sha256"] or current_body == body,
            "rendered PR review does not match its frozen body hash")
    new_target = target_envelope(scope, live, body, target["date"], session)
    if current_body != body:
        write_atomic(output, body)
    write_atomic(session / "pr-review-target.json", json.dumps(new_target, indent=2) + "\n")
    print(f"pr-review: finalized stack review at {head}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("session", type=Path)
    render_parser.add_argument("--date", default=datetime.date.today().isoformat())
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("session", type=Path)
    finalize_parser = subparsers.add_parser("finalize-stack")
    finalize_parser.add_argument("session", type=Path)
    finalize_parser.add_argument("--head", required=True)
    finalize_parser.add_argument("--root")
    args = parser.parse_args()
    session = args.session.expanduser().absolute()
    try:
        if args.command == "render":
            output, _ = render_session(session, args.date)
            print(output)
        elif args.command == "finalize-stack":
            finalize_stack(session, args.head, args.root)
        else:
            publish(session, Path(__file__).resolve())
    except (OSError, ReviewError, subprocess.SubprocessError) as error:
        print(f"pr-review: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
