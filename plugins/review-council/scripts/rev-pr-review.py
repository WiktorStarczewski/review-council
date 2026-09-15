#!/usr/bin/env python3
"""Render and publish the canonical Review Council pull-request review."""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


BAD_INLINE = re.compile(r"[\r\n]")
PR_URL = re.compile(r"^https://github\.com/([^/]+/[^/]+)/pull/([1-9][0-9]*)/?$")
BLOB_URL = re.compile(r"^(https://github\.com/[^/]+/[^/]+/blob/)[0-9a-f]{7,40}(/.*)$")
COMMIT_URL = re.compile(r"^(https://github\.com/[^/]+/[^/]+/commit/)[0-9a-f]{7,40}/?$")
BLOB_ID_URL = re.compile(
    r"^https://github\.com/([^/]+/[^/]+)/blob/([0-9a-f]{7,40})/.*$", re.IGNORECASE)
COMMIT_ID_URL = re.compile(
    r"^https://github\.com/([^/]+/[^/]+)/commit/([0-9a-f]{7,40})/?$", re.IGNORECASE)
GITHUB_REMOTES = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"^(?:https?|git)://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    r"^git@github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    r"^ssh://git@github\.com(?::[0-9]+)?/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    r"^ssh://git@ssh\.github\.com:443/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
))
OID = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")


class ReviewError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReviewError(message)


def inline(value, field):
    require(isinstance(value, str) and value.strip(), f"{field} must be a nonempty string")
    require(not BAD_INLINE.search(value), f"{field} must fit on one line")
    return value.strip()


def prose(value, field):
    value = inline(value, field)
    rendered = []
    start = 0
    cursor = 0
    while cursor < len(value):
        if value[cursor] != "`":
            cursor += 1
            continue
        end = cursor + 1
        while end < len(value) and value[end] == "`":
            end += 1
        ticks = value[cursor:end]
        closer = re.compile(r"(?<!`)" + re.escape(ticks) + r"(?!`)").search(value, end)
        require(closer is not None, f"{field} contains an unmatched backtick delimiter")
        rendered.append(html.escape(value[start:cursor], quote=False))
        rendered.append(value[cursor:closer.end()])
        cursor = closer.end()
        start = cursor
    rendered.append(html.escape(value[start:], quote=False))
    return "".join(rendered)


def count(value, field, positive=False):
    require(isinstance(value, int) and not isinstance(value, bool), f"{field} must be an integer")
    require(value >= (1 if positive else 0), f"{field} is out of range")
    return value


def link(value, field, code=False, pattern=None, kind=None):
    require(isinstance(value, dict), f"{field} must be an object")
    label = inline(value.get("label"), f"{field}.label")
    url = inline(value.get("url"), f"{field}.url")
    require(url.startswith("https://") and " " not in url and ")" not in url,
            f"{field}.url must be an HTTPS URL without spaces or closing parentheses")
    if pattern is not None:
        require(pattern.fullmatch(url) is not None,
                f"{field}.url must be a {kind or 'supported'} GitHub URL")
    require("]" not in label and (not code or "`" not in label),
            f"{field}.label contains Markdown delimiters")
    return f"[`{label}`]({url})" if code else f"[{prose(label, f'{field}.label')}]({url})"


def inline_list(value, field):
    require(isinstance(value, list), f"{field} must be a list")
    require(value, f"{field} must not be empty")
    return [inline(item, f"{field}[{index}]") for index, item in enumerate(value)]


def prose_list(value, field):
    require(isinstance(value, list), f"{field} must be a list")
    require(value, f"{field} must not be empty")
    return [prose(item, f"{field}[{index}]") for index, item in enumerate(value)]


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
    headline = prose(verdict.get("headline"), "verdict.headline")
    detail = prose(verdict.get("detail"), "verdict.detail")
    require("**" not in headline, "verdict.headline contains a Markdown delimiter")
    panels = count(data.get("panels"), "panels", positive=True)
    rejected = count(data.get("rejected"), "rejected")
    gates = prose(data.get("gates"), "gates")
    panel = prose_list(data.get("panel"), "panel")
    decisions = data.get("decisions")
    fixes = data.get("fixes")
    require(isinstance(decisions, list), "decisions must be a list")
    require(isinstance(fixes, list), "fixes must be a list")
    verified = prose_list(data.get("verified_sound"), "verified_sound")
    coverage = prose_list(data.get("coverage"), "coverage")
    date = inline(date, "date")
    require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date) is not None,
            "date must use YYYY-MM-DD")

    decision_rows = []
    decision_details = []
    for index, decision in enumerate(decisions):
        field = f"decisions[{index}]"
        require(isinstance(decision, dict), f"{field} must be an object")
        title = prose(decision.get("title"), f"{field}.title")
        require("**" not in title, f"{field}.title contains a Markdown delimiter")
        location = link(decision.get("location"), f"{field}.location", code=True,
                        pattern=BLOB_URL, kind="SHA-pinned blob")
        decision_rows.append(f"- **{title}** · {location}")
        decision_details.append(
            f"{index + 1}. **{title}** {prose(decision.get('detail'), f'{field}.detail')}"
        )

    fix_rows = []
    commit_identities = []
    for index, fix in enumerate(fixes):
        field = f"fixes[{index}]"
        require(isinstance(fix, dict), f"{field} must be an object")
        severity = inline(fix.get("severity"), f"{field}.severity")
        require(re.fullmatch(r"P[0-3]", severity) is not None,
                f"{field}.severity must be P0, P1, P2, or P3")
        summary = prose(fix.get("summary"), f"{field}.summary").replace("|", "\\|")
        commit = fix.get("commit")
        commit_link = link(commit, f"{field}.commit", code=True,
                           pattern=COMMIT_URL, kind="SHA-pinned commit")
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
        fixed_phrase += " in " + link(
            data["fixed_in"], "fixed_in", pattern=PR_URL, kind="pull-request")
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


def run_gh(arguments, root, input_data=None):
    environment = os.environ.copy()
    environment.pop("GH_REPO", None)
    environment["GH_HOST"] = "github.com"
    return subprocess.run(["gh", *arguments], cwd=root, text=True,
                          capture_output=True, timeout=120, env=environment,
                          input=input_data)


def run_git(arguments, root):
    result = subprocess.run(["git", *arguments], cwd=root, text=True,
                            capture_output=True, timeout=30)
    if result.returncode != 0:
        raise ReviewError("git " + " ".join(arguments) + " failed: " + result.stderr.strip())
    return result.stdout.strip()


def github_repository(url):
    for pattern in GITHUB_REMOTES:
        match = pattern.fullmatch(url.strip())
        if match is not None:
            return match.group(1).lower()
    return None


def github_repositories(root):
    remotes = subprocess.run(["git", "remote"], cwd=root, text=True,
                             capture_output=True, timeout=30)
    if remotes.returncode != 0:
        raise ReviewError("cannot inspect git remotes: " + remotes.stderr.strip())
    repositories = set()
    for name in remotes.stdout.splitlines():
        urls = subprocess.run(["git", "remote", "get-url", "--all", name], cwd=root,
                              text=True, capture_output=True, timeout=30)
        if urls.returncode != 0:
            raise ReviewError("cannot inspect git remote " + name + ": " + urls.stderr.strip())
        for url in urls.stdout.splitlines():
            repository = github_repository(url)
            if repository is not None:
                repositories.add(repository)
    return sorted(repositories)


def remote_merge_base(repository, base_head, head, root):
    local = subprocess.run(["git", "merge-base", head, base_head], cwd=root,
                           text=True, capture_output=True, timeout=30)
    if local.returncode == 0:
        merge_base = local.stdout.strip()
        require(OID.fullmatch(merge_base) is not None,
                "git returned an invalid merge base")
        return merge_base
    result = run_gh(["api", f"repos/{repository}/compare/{base_head}...{head}"], root)
    if result.returncode != 0:
        raise ReviewError("cannot verify the reviewed merge base: " + result.stderr.strip())
    try:
        comparison = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReviewError("gh compare returned invalid JSON") from error
    merge_base = (comparison.get("merge_base_commit") or {}).get("sha") \
        if isinstance(comparison, dict) else None
    require(isinstance(merge_base, str) and OID.fullmatch(merge_base) is not None,
            "gh compare omitted the merge base")
    return merge_base


def require_reviewed_merge_base(target, head, base_head, root):
    require(remote_merge_base(target["repo"], base_head, head, root) == target["base"],
            "the PR merge base does not match the reviewed merge base")


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


def resolve_pr(scope, repositories=None):
    root = scope["root"]
    repositories = github_repositories(root) if repositories is None else repositories
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
        merge_base = remote_merge_base(
            target["repo"], target["base_head"], target["head"], root)
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
    if live["state"] != "OPEN":
        return live
    require(live["base_branch"] == target["base_branch"],
            "the PR base branch changed after review; rerun the review before publishing")
    require_reviewed_merge_base(target, live["head"], live["base_head"], root)
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
    require(isinstance(pages, list) and pages,
            "gh api returned an invalid review list")
    require(all(isinstance(page, list) for page in pages),
            "gh api returned an invalid review page")
    reviews = [review for page in pages for review in page]
    require(all(isinstance(review, dict) for review in reviews),
            "gh api returned an invalid review item")
    return reviews


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
            f":(top,literal,exclude){session_path}",
            f":(top,literal,exclude){session_path}/**",
        ])
    dirty = run_git(arguments, root)
    require(not dirty,
            "the reviewed repository has staged, unstaged, or untracked bytes outside "
            "the PR head; commit them and rerun the review before publishing. Dirty paths:\n"
            + dirty.replace("\0", "\n").rstrip())


def target_envelope(scope, target, body, date, session, repositories,
                    allow_unpushed=False):
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
        "repositories": repositories,
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
    repositories = target.get("repositories")
    require(isinstance(repositories, list), "target.repositories must be a list")
    normalized = []
    for index, repository in enumerate(repositories):
        repository = inline(repository, f"target.repositories[{index}]")
        require(REPOSITORY.fullmatch(repository) is not None,
                f"target.repositories[{index}] must be owner/repo")
        normalized.append(repository.lower())
    require(repositories == sorted(set(normalized)),
            "target.repositories must be a sorted, unique, normalized list")
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
        require(frozen["repo"].lower() in repositories,
                "target repository is outside its frozen repository set")
    return target


def associate_target(target, resolved):
    associated = dict(target)
    associated["associated"] = True
    associated["base_branch"] = resolved["base_branch"]
    associated.update({key: resolved[key] for key in (
        "repo", "number", "url", "base_head")})
    return associated


def bind_target(scope, target, session, allow_rewritten_head=False):
    root = scope["root"]
    require(target["branch"] == scope["branch"] and target["base"] == scope["base"],
            "the PR review target does not match its reviewed session scope")
    repositories = github_repositories(root)
    require(repositories == target["repositories"],
            "the reviewed GitHub repository remotes changed; rerender before publishing")
    resolved = resolve_pr(scope, target["repositories"])
    if resolved is None:
        if not target["associated"]:
            return target, None, False
        live = live_pr(target, root)
        require(live["state"] != "OPEN",
                "the frozen open PR cannot be resolved from the reviewed session scope")
        return target, live, False
    local_head = run_git(["rev-parse", "HEAD"], root)
    local_tree = run_git(["rev-parse", "HEAD^{tree}"], root)
    require(local_tree == target["tree"],
            "the PR review target tree does not match the reviewed session scope")
    require(allow_rewritten_head or local_head == target["head"],
            "the PR review target head does not match the reviewed session scope")
    require_clean_review_tree(root, session)
    if target["associated"]:
        require(all(resolved[key] == target[key] for key in ("repo", "number", "url")),
                "the PR review target does not match the scoped open PR")
        require(resolved["base_branch"] == target["base_branch"],
                "the PR base branch changed after review; rerun the review before publishing")
        return target, resolved, False

    require(allow_rewritten_head or resolved["head"] == local_head,
            "the open PR head does not match the reviewed local head")
    return associate_target(target, resolved), resolved, True


def git_is_ancestor(ancestor, descendant, root):
    result = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant],
                            cwd=root, text=True, capture_output=True, timeout=30)
    if result.returncode not in (0, 1):
        raise ReviewError("cannot compare PR head ancestry: " + result.stderr.strip())
    return result.returncode == 0


def validate_publication_links(data, repositories, head, root):
    allowed = {repository.lower() for repository in repositories}
    head = head.lower()
    for index, decision in enumerate(data.get("decisions", [])):
        field = f"decisions[{index}].location.url"
        url = inline(decision.get("location", {}).get("url"), field)
        match = BLOB_ID_URL.fullmatch(url)
        require(match is not None, f"{field} must be a SHA-pinned blob GitHub URL")
        require(match.group(1).lower() in allowed,
                f"{field} points outside the reviewed repository")
        require(head.startswith(match.group(2).lower()),
                f"{field} does not point at the reviewed head")

    if data.get("fixed_in") is None:
        for index, fix in enumerate(data.get("fixes", [])):
            field = f"fixes[{index}].commit.url"
            url = inline(fix.get("commit", {}).get("url"), field)
            match = COMMIT_ID_URL.fullmatch(url)
            require(match is not None, f"{field} must be a SHA-pinned commit GitHub URL")
            require(match.group(1).lower() in allowed,
                    f"{field} points outside the reviewed repository")
            commit = run_git(
                ["rev-parse", "--verify", f"{match.group(2)}^{{commit}}"], root)
            require(commit.lower().startswith(match.group(2).lower()),
                    f"{field} does not resolve to its displayed commit")
            require(git_is_ancestor(commit, head, root),
                    f"{field} is not an ancestor of the reviewed head")


def wait_for_expected_head(target, root, expected, initial):
    live = initial
    for delay in (0, 1, 2, 4, 8, 15):
        if live["state"] != "OPEN" or live["head"] == expected:
            return live
        if live["head"] != target["head"] \
                and not git_is_ancestor(live["head"], expected, root):
            return live
        time.sleep(delay)
        live = live_pr(target, root)
    return live


@contextmanager
def publication_lock(root):
    common = Path(run_git(["rev-parse", "--git-common-dir"], root))
    if not common.is_absolute():
        common = root / common
    lock_path = common.resolve() / "review-council-pr-review.lock"
    with lock_path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def render_session(session, date):
    data = load_input(session / "pr-review.json")
    body = render(data, date)
    scope_path = session / "scope.env"
    target = None
    if scope_path.is_file():
        scope = parse_scope(scope_path)
        repositories = github_repositories(scope["root"])
        resolved = None if os.environ.get("NO_PUSH") == "1" \
            else resolve_pr(scope, repositories)
        target = target_envelope(
            scope, resolved, body, date, session, repositories,
            allow_unpushed=os.environ.get("REV_STACK_LEG") == "1",
        )
        if repositories:
            validate_publication_links(data, repositories, target["head"], scope["root"])
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


def require_publishable_head(target, live):
    require(live["state"] == "OPEN",
            "the PR closed after review; rerun the review before publishing")
    require(live["head"] == target["head"],
            "the PR head changed after review; rerun the review before publishing")


def publish(session, script):
    scope = parse_scope(session / "scope.env")
    retry = publication_retry(session, script)
    with publication_transaction(session, scope, retry):
        if os.environ.get("NO_PUSH") == "1":
            print("pr-review: NO_PUSH=1; skipped publication")
            return
        if unresolved_target_skip(scope, session):
            return
        target = load_target(session / "pr-review-target.json")
        output = session / "pr-review.md"
        require(output.is_file(), f"rendered PR review is missing: {output}")
        body = output.read_text()
        require(body_hash(body) == target["body_sha256"],
                "rendered PR review does not match its frozen body hash")
        target, live, promoted = bind_target(scope, target, session)
        if live is None or live["state"] != "OPEN":
            print("pr-review: no associated open PR; skipped")
            return
        if promoted:
            write_atomic(session / "pr-review-target.json",
                         json.dumps(target, indent=2) + "\n")
        require_publishable_head(target, live)
        reviews = existing_reviews(target["repo"], target["number"], scope["root"])
        live = live_pr(target, scope["root"])
        if live["state"] != "OPEN":
            print("pr-review: no associated open PR; skipped")
            return
        require_publishable_head(target, live)
        if any(review.get("body") == body
               and review.get("state") == "COMMENTED"
               and review.get("commit_id") == target["head"]
               for review in reviews):
            print(f"pr-review: identical review already posted on {target['url']}")
            return
        payload = json.dumps({
            "commit_id": target["head"], "body": body, "event": "COMMENT",
        })
        result = run_gh([
            "api", "--method", "POST",
            f"repos/{target['repo']}/pulls/{target['number']}/reviews", "--input", "-",
        ], scope["root"], payload)
        if result.returncode != 0:
            raise ReviewError("GitHub review post failed: " + result.stderr.strip())
        try:
            posted = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ReviewError("GitHub returned invalid created-review JSON") from error
        require(isinstance(posted, dict) and posted.get("body") == body
                and posted.get("state") == "COMMENTED"
                and posted.get("commit_id") == target["head"],
                "GitHub did not confirm the commit-pinned COMMENTED review")
        require_publishable_head(target, live_pr(target, scope["root"]))
    print(f"pr-review: posted {target['url']}")


def publication_retry(session, script):
    override = os.environ.get("REVIEW_COUNCIL_RETRY_COMMAND")
    if override and override.strip() and not BAD_INLINE.search(override):
        return override.strip()
    return shlex.join([sys.executable, str(script), "publish", str(session)])


def write_incomplete(session, error, retry):
    body = (
        "# Incomplete review\n\n"
        "PR review publication failed.\n\n"
        + error + "\n\n"
        "pr-review: retry: " + retry + "\n"
    )
    write_atomic(session / "incomplete.md", body)


def clear_incomplete(session):
    try:
        (session / "incomplete.md").unlink()
    except FileNotFoundError:
        pass


@contextmanager
def publication_transaction(session, scope, retry):
    with publication_lock(scope["root"]):
        try:
            yield
            if os.environ.get("REV_STACK_PUBLICATION") != "1":
                clear_incomplete(session)
        except (OSError, ReviewError, subprocess.SubprocessError) as error:
            message = str(error)
            if session.is_dir():
                try:
                    write_incomplete(session, message, retry)
                except OSError as receipt_error:
                    message += "\npr-review: cannot write incomplete receipt: " + str(receipt_error)
            raise ReviewError(message + "\npr-review: retry: " + retry) from error


def replace_sha_url(url, pattern, head, field):
    value = inline(url, field)
    match = pattern.fullmatch(value)
    require(match is not None, f"{field} must be a SHA-pinned GitHub URL")
    return match.group(1) + head + (match.group(2) if match.lastindex == 2 else "")


def finalized_data(data, head):
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
    return updated


def validate_stack(session, head, expected_root=None, push_url=None):
    require(OID.fullmatch(head) is not None, "--head must be a full commit ID")
    scope = parse_scope(session / "scope.env")
    root = scope["root"]
    if expected_root is not None:
        require(root.resolve() == Path(expected_root).resolve(),
                "stack validation repository does not match the reviewed session")
    target = load_target(session / "pr-review-target.json")
    require(target["branch"] == scope["branch"] and target["base"] == scope["base"],
            "the PR review target does not match its reviewed session scope")
    require(run_git(["branch", "--show-current"], root) == target["branch"],
            "stack validation branch does not match the reviewed branch")
    require(run_git(["rev-parse", "HEAD"], root) == head,
            "stack validation head does not match the local checkout")
    require(run_git(["rev-parse", f"{head}^{{tree}}"], root) == target["tree"],
            "stack validation changed the reviewed tree")
    require(git_is_ancestor(target["base"], head, root),
            "stack validation head does not preserve the reviewed base")
    require(github_repositories(root) == target["repositories"],
            "the reviewed GitHub repository remotes changed; rerender before pushing")
    require_clean_review_tree(root, session)

    output = session / "pr-review.md"
    require(output.is_file(), f"rendered PR review is missing: {output}")
    require(body_hash(output.read_text()) == target["body_sha256"],
            "rendered PR review does not match its frozen body hash")
    source_body = render(load_input(session / "pr-review.json"), target["date"])
    require(body_hash(source_body) == target["body_sha256"],
            "structured PR review input does not match the frozen rendered review")
    if target["repositories"]:
        repository = github_repository(push_url or "")
        require(repository in target["repositories"],
                "the push URL is outside the frozen GitHub repository set")
    print(f"pr-review: validated stack review at {head}")


def finalize_stack(session, head, expected_root=None):
    require(OID.fullmatch(head) is not None, "--head must be a full commit ID")
    scope = parse_scope(session / "scope.env")
    if os.environ.get("NO_PUSH") == "1":
        print("pr-review: NO_PUSH=1; skipped stack finalization")
        return
    if expected_root is not None:
        require(scope["root"].resolve() == Path(expected_root).resolve(),
                "stack finalization repository does not match the reviewed session")
    if unresolved_target_skip(scope, session):
        return
    root = scope["root"]
    with publication_lock(root):
        target = load_target(session / "pr-review-target.json")
        require(run_git(["rev-parse", "HEAD"], root) == head,
                "stack finalization head does not match the local checkout")
        require(run_git(["rev-parse", f"{head}^{{tree}}"], root) == target["tree"],
                "stack finalization changed the reviewed tree")
        target, live, promoted = bind_target(
            scope, target, session, allow_rewritten_head=True)
        if live is None or live["state"] != "OPEN":
            print("pr-review: no associated open PR; skipped")
            return
        live = wait_for_expected_head(target, root, head, live)
        if live["state"] != "OPEN":
            print("pr-review: no associated open PR; skipped")
            return
        require(live["head"] == head, "the pushed PR head does not match stack finalization")
        require_reviewed_merge_base(target, head, live["base_head"], root)

        data = load_input(session / "pr-review.json")
        source_body = render(data, target["date"])
        updated = finalized_data(data, head)
        validate_publication_links(updated, target["repositories"], head, root)
        body = render(updated, target["date"])
        output = session / "pr-review.md"
        require(output.is_file(), f"rendered PR review is missing: {output}")
        current_body = output.read_text()
        source_is_frozen = body_hash(source_body) == target["body_sha256"]
        if target["head"] == head and source_is_frozen and not promoted:
            require(body_hash(current_body) == target["body_sha256"],
                    "rendered PR review does not match its frozen body hash")
            print(f"pr-review: stack review already uses reviewed head {head}")
            return
        if not source_is_frozen:
            require(target["head"] == head
                    and body_hash(current_body) == target["body_sha256"]
                    and current_body == body,
                    "structured PR review input does not match the frozen rendered review")
            print(f"pr-review: stack review already finalized at {head}")
            return
        require(body_hash(current_body) == target["body_sha256"] or current_body == body,
                "rendered PR review does not match its frozen body hash")
        new_target = target_envelope(
            scope, live, body, target["date"], session, target["repositories"])
        if current_body != body:
            write_atomic(output, body)
        write_atomic(session / "pr-review-target.json",
                     json.dumps(new_target, indent=2) + "\n")
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
    validate_parser = subparsers.add_parser("validate-stack")
    validate_parser.add_argument("session", type=Path)
    validate_parser.add_argument("--head", required=True)
    validate_parser.add_argument("--root")
    validate_parser.add_argument("--push-url", required=True)
    args = parser.parse_args()
    session = args.session.expanduser().absolute()
    try:
        if args.command == "render":
            output, _ = render_session(session, args.date)
            print(output)
        elif args.command == "finalize-stack":
            finalize_stack(session, args.head, args.root)
        elif args.command == "validate-stack":
            validate_stack(session, args.head, args.root, args.push_url)
        else:
            publish(session, Path(__file__).resolve())
    except (OSError, ReviewError, subprocess.SubprocessError) as error:
        message = str(error)
        if args.command == "publish" and "\npr-review: retry: " not in message:
            retry = publication_retry(session, Path(__file__).resolve())
            message += "\npr-review: retry: " + retry
            if session.is_dir():
                try:
                    write_incomplete(session, str(error), retry)
                except OSError as receipt_error:
                    message += "\npr-review: cannot write incomplete receipt: " + str(receipt_error)
        print("pr-review: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
