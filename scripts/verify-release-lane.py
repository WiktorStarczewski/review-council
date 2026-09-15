#!/usr/bin/env python3
"""Validate immutable evidence for a Review Council stable release lane."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time


PLUGIN_PREFIX = "plugins/review-council"
TAG_PATTERN = re.compile(r"review-council--v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
CANARY_OUTPUT_LIMIT = 4 * 1024 * 1024
CANARY_TIMEOUT_SECONDS = 900
CANARY_TERM_GRACE_SECONDS = 2
DIRECT_CANARIES = {
    "scripts/seats.d/codex.sh": ("provider-codex",),
    "scripts/seats.d/claude.sh": ("provider-claude",),
    "scripts/seats.d/gemini.sh": ("provider-gemini",),
    "scripts/lib/review-read-audit.py": ("provider-codex", "provider-claude"),
    "scripts/lib/stream-summary.py": ("provider-codex", "provider-claude"),
    "scripts/lib/codex-review-to-findings.py": ("provider-codex",),
    "scripts/rev-pr-review.py": ("github-publication",),
    "scripts/stack.sh": ("github-publication",),
    "docs/pr-review.md": ("github-publication",),
}
PREFIX_CANARIES = {
    "skills/rev/": ("host-claude",),
    "skills/stack/": ("host-claude",),
    "codex-skills/rev/": ("host-codex",),
    "codex-skills/stack/": ("host-codex",),
    "hooks/": ("host-claude",),
}
KNOWN_CANARIES = frozenset(
    canary for values in (*DIRECT_CANARIES.values(), *PREFIX_CANARIES.values())
    for canary in values
)
_ACTIVE_CANARY = None
DEFAULT_COMMANDS = [
    {"name": "shell", "kind": "shell", "argv": ["plugins/review-council/tests/run-tests.sh"]},
    {"name": "python", "kind": "python", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]},
    {"name": "claude-marketplace", "kind": "validator", "argv": ["claude", "plugin", "validate", "--strict", ".claude-plugin/marketplace.json"]},
    {"name": "claude-plugin", "kind": "validator", "argv": ["claude", "plugin", "validate", "--strict", "plugins/review-council"]},
    {"name": "codex-marketplace", "kind": "validator", "argv": ["python3", "tests/check-codex-marketplace.py"]},
]


class ReleaseError(RuntimeError):
    pass


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_json(raw, source):
    try:
        return json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ReleaseError(source + " is not valid JSON") from error


def direct_directory(path, label):
    lexical = Path(path).expanduser()
    if ".." in lexical.parts:
        raise ReleaseError(label + " must be a direct directory path")
    absolute = Path(os.path.abspath(lexical))
    try:
        metadata = absolute.lstat()
    except OSError as error:
        raise ReleaseError(label + " must be a direct directory path") from error
    if absolute.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ReleaseError(label + " must be a direct directory path")
    return absolute.resolve()


def regular_bytes(path, label, maximum=16 * 1024 * 1024, mode=None):
    path = Path(path)
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | NOFOLLOW)
    except OSError as error:
        raise ReleaseError(label + " must be a regular one-link file") from error
    try:
        current = os.fstat(descriptor)
        if (path.is_symlink() or not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
                or current.st_size > maximum
                or mode is not None and stat.S_IMODE(current.st_mode) != mode):
            raise ReleaseError(label + " must be a regular one-link file")
        chunks = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != current.st_size:
            raise ReleaseError(label + " changed while read")
        after = os.fstat(descriptor)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ReleaseError(label + " changed while read")
        return raw
    finally:
        os.close(descriptor)


def publish_json(path, value):
    path = Path(path).expanduser()
    if ".." in path.parts or path.is_symlink():
        raise ReleaseError("receipt must be a direct path")
    absolute = Path(os.path.abspath(path))
    absolute.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    direct_directory(absolute.parent, "receipt parent")
    raw = encoded(value)
    if absolute.exists() or absolute.is_symlink():
        if absolute.is_symlink():
            raise ReleaseError("receipt must be a direct path")
        current = regular_bytes(absolute, "receipt", maximum=16 * 1024 * 1024, mode=0o600)
        if current != raw:
            raise ReleaseError("receipt collision")
        return absolute
    descriptor, temporary = tempfile.mkstemp(prefix="." + absolute.name + ".", dir=absolute.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, absolute, follow_symlinks=False)
        except FileExistsError:
            if absolute.is_symlink():
                raise ReleaseError("receipt must be a direct path")
            current = regular_bytes(
                absolute, "receipt", maximum=16 * 1024 * 1024, mode=0o600,
            )
            if current != raw:
                raise ReleaseError("receipt collision")
        return absolute
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def publish_bytes(path, raw, label):
    path = Path(path).expanduser()
    if ".." in path.parts or path.is_symlink():
        raise ReleaseError(label + " must be a direct path")
    absolute = Path(os.path.abspath(path))
    absolute.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    direct_directory(absolute.parent, label + " parent")
    if absolute.exists() or absolute.is_symlink():
        current = regular_bytes(
            absolute, label, maximum=CANARY_OUTPUT_LIMIT + 4096, mode=0o600,
        )
        if current != raw:
            raise ReleaseError(label + " collision")
        return absolute
    descriptor, temporary = tempfile.mkstemp(prefix="." + absolute.name + ".", dir=absolute.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, absolute, follow_symlinks=False)
        except FileExistsError:
            current = regular_bytes(
                absolute, label, maximum=CANARY_OUTPUT_LIMIT + 4096, mode=0o600,
            )
            if current != raw:
                raise ReleaseError(label + " collision")
        return absolute
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def git(root, *arguments, error="Git command failed", environment=None):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment,
        )
    except OSError as failure:
        raise ReleaseError(error) from failure
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise ReleaseError(error + (": " + detail if detail else ""))
    return result.stdout


def repository_root(path):
    root = direct_directory(path, "root")
    resolved = Path(git(root, "rev-parse", "--show-toplevel", error="root must be a Git worktree")
                    .decode().strip())
    if resolved != root:
        raise ReleaseError("root must be the Git worktree top level")
    return root


def version_tuple(value, source):
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value
        if isinstance(value, str) else "",
    )
    if not match:
        raise ReleaseError(source + " version is invalid")
    return tuple(map(int, match.groups()))


def tag_version(tag):
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ReleaseError("stable tag name is invalid")
    return match.group(1)


def resolve_tag(root, tag):
    tag_version(tag)
    tag_ref = "refs/tags/" + tag
    before_object = git(
        root, "rev-parse", "--verify", tag_ref + "^{tag}",
        error="stable tag must be annotated",
    ).decode().strip()
    before_commit = git(
        root, "rev-parse", "--verify", tag_ref + "^{commit}",
        error="stable tag commit is invalid",
    ).decode().strip()
    try:
        subprocess_result = subprocess.run(
            ["git", "-C", str(root), "verify-tag", tag],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise ReleaseError("stable tag signature verification failed") from error
    if subprocess_result.returncode != 0:
        raise ReleaseError("stable tag signature verification failed")
    after_object = git(
        root, "rev-parse", "--verify", tag_ref + "^{tag}",
        error="stable tag changed during verification",
    ).decode().strip()
    after_commit = git(
        root, "rev-parse", "--verify", tag_ref + "^{commit}",
        error="stable tag changed during verification",
    ).decode().strip()
    if (before_object, before_commit) != (after_object, after_commit):
        raise ReleaseError("stable tag changed during verification")
    tag_object = git(root, "cat-file", "tag", before_object, error="stable tag object is invalid")
    declared = next(
        (line[4:].decode(errors="surrogateescape") for line in tag_object.splitlines()
         if line.startswith(b"tag ")),
        None,
    )
    if declared != tag:
        raise ReleaseError("stable tag object name mismatch")
    return before_commit


def tag_plugin_records(root, revision):
    raw = git(
        root, "ls-tree", "-rz", revision + ":" + PLUGIN_PREFIX,
        error="stable tag plugin tree is unavailable",
    )
    records = []
    contents = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, separator, path_raw = entry.partition(b"\t")
        fields = header.split()
        if not separator or len(fields) != 3:
            raise ReleaseError("stable tag plugin tree is invalid")
        mode, kind, object_id = (field.decode() for field in fields)
        path = path_raw.decode("utf-8", errors="surrogateescape")
        relative = Path(path)
        if (relative.is_absolute() or not path or "." in relative.parts
                or ".." in relative.parts or kind != "blob"
                or mode not in {"100644", "100755", "120000"}):
            raise ReleaseError("stable tag plugin tree contains an unsafe path")
        blob = git(root, "cat-file", "blob", object_id, error="stable plugin blob is unavailable")
        record = {
            "kind": "symlink" if mode == "120000" else "regular",
            "mode": mode,
            "path": path,
            "sha256": digest(blob),
            "size": len(blob),
        }
        records.append(record)
        contents[path] = blob
    records.sort(key=lambda row: row["path"])
    if not records or len({row["path"] for row in records}) != len(records):
        raise ReleaseError("stable tag plugin tree is invalid")
    return records, contents


def installed_plugin_material(plugin, capture=()):
    root = direct_directory(plugin, "stable plugin")
    records = []
    capture = frozenset(capture)
    captured = {}

    def visit(directory, prefix=""):
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            relative = prefix + entry.name
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                if entry.is_symlink():
                    raise ReleaseError("installed stable plugin contains an unsafe path")
                visit(Path(entry.path), relative + "/")
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raw = os.fsencode(os.readlink(entry.path))
                mode = "120000"
                kind = "symlink"
            elif stat.S_ISREG(metadata.st_mode):
                descriptor = os.open(entry.path, os.O_RDONLY | NOFOLLOW)
                try:
                    current = os.fstat(descriptor)
                    if (not stat.S_ISREG(current.st_mode)
                            or (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino)):
                        raise ReleaseError("installed stable plugin changed while read")
                    chunks = []
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    after = os.fstat(descriptor)
                    if (current.st_size, current.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ReleaseError("installed stable plugin changed while read")
                finally:
                    os.close(descriptor)
                mode = "100755" if metadata.st_mode & 0o111 else "100644"
                kind = "regular"
            else:
                raise ReleaseError("installed stable plugin contains a non-file entry")
            records.append({
                "kind": kind,
                "mode": mode,
                "path": relative,
                "sha256": digest(raw),
                "size": len(raw),
            })
            if relative in capture:
                captured[relative] = raw

    visit(root)
    records.sort(key=lambda row: row["path"])
    if set(captured) != set(capture):
        raise ReleaseError("installed stable plugin mismatch")
    return root, records, captured


def installed_plugin_records(plugin):
    root, records, _ = installed_plugin_material(plugin)
    return root, records


def manifest_version(raw, source):
    document = parse_json(raw, source)
    if (not isinstance(document, dict) or document.get("name") != "review-council"
            or not isinstance(document.get("version"), str)):
        raise ReleaseError(source + " is invalid")
    version_tuple(document["version"], source)
    return document["version"]


def stable_tag_identity(root, tag):
    root = repository_root(root)
    commit = resolve_tag(root, tag)
    records, contents = tag_plugin_records(root, commit)
    versions = {
        manifest_version(contents.get(name, b""), "stable " + name)
        for name in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
    }
    if len(versions) != 1 or next(iter(versions)) != tag_version(tag):
        raise ReleaseError("stable manifest version does not match tag")
    tree = git(root, "rev-parse", commit + "^{tree}", error="stable commit tree is invalid").decode().strip()
    return {
        "public": {"tag": tag, "commit": commit, "tree": tree},
        "records": records,
        "version": next(iter(versions)),
    }


def verified_stable_material(root, tag, plugin, capture=()):
    identity = stable_tag_identity(root, tag)
    _, installed, captured = installed_plugin_material(plugin, capture)
    if installed != identity["records"]:
        raise ReleaseError("installed stable plugin mismatch")
    public = dict(identity["public"])
    public["plugin_identity"] = digest(encoded(installed))
    return public, captured


def stable_identity(root, tag, plugin):
    public, _ = verified_stable_material(root, tag, plugin)
    return public


def candidate_identity(root, commit, stable_version):
    root = repository_root(root)
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseError("candidate commit must be a full object ID")
    resolved = git(
        root, "rev-parse", "--verify", commit + "^{commit}",
        error="candidate commit is invalid",
    ).decode().strip()
    if resolved != commit:
        raise ReleaseError("candidate commit must be a full object ID")
    head = git(root, "rev-parse", "HEAD", error="candidate HEAD is invalid").decode().strip()
    if head != commit:
        raise ReleaseError("candidate commit does not equal HEAD")
    environment = dict(
        os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
    )
    if git(
            root, "-c", "core.fileMode=true", "status", "--porcelain=v1", "-z",
            "--untracked-files=all", environment=environment):
        raise ReleaseError("candidate worktree is not clean")
    expected_plugin, _ = tag_plugin_records(root, commit)
    _, physical_plugin = installed_plugin_records(root / PLUGIN_PREFIX)
    if physical_plugin != expected_plugin:
        raise ReleaseError("candidate worktree is not clean")
    versions = set()
    for relative in (
            ".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        raw = regular_bytes(root / PLUGIN_PREFIX / relative, "candidate " + relative)
        versions.add(manifest_version(raw, "candidate " + relative))
    if len(versions) != 1:
        raise ReleaseError("candidate manifest versions do not match")
    version = next(iter(versions))
    if version_tuple(version, "candidate") <= version_tuple(stable_version, "stable"):
        raise ReleaseError("candidate version must be greater than stable version")
    tree = git(root, "rev-parse", commit + "^{tree}", error="candidate tree is invalid").decode().strip()
    return {"version": version, "commit": commit, "tree": tree}


def changed_plugin_paths(root, stable_revision, candidate_commit):
    raw = git(
        root, "diff", "--name-only", "-z", "--no-renames",
        stable_revision + ".." + candidate_commit, "--",
        error="cannot derive stable-to-candidate changes",
    )
    prefix = PLUGIN_PREFIX + "/"
    result = []
    for value in raw.split(b"\0"):
        if not value:
            continue
        path = value.decode("utf-8", errors="surrogateescape")
        if not path.startswith(prefix):
            continue
        relative = path[len(prefix):]
        parts = Path(relative).parts
        if (not relative or Path(relative).is_absolute() or "." in parts
                or ".." in parts):
            raise ReleaseError("candidate contains an unsafe changed path")
        result.append(relative)
    return sorted(set(result))


def canaries_for_paths(paths):
    selected = {}
    for path in paths:
        canaries = DIRECT_CANARIES.get(path)
        if canaries is None:
            canaries = next(
                (values for prefix, values in PREFIX_CANARIES.items()
                 if path.startswith(prefix)),
                None,
            )
        if canaries is None:
            remainder = path[len("scripts/seats.d/"):] if path.startswith(
                "scripts/seats.d/") else ""
            if remainder.endswith(".sh") and "/" not in remainder:
                raise ReleaseError("unmapped provider boundary: " + path)
            continue
        for canary in canaries:
            selected.setdefault(canary, []).append(path)
    return {name: sorted(trigger_paths) for name, trigger_paths in sorted(selected.items())}


def trigger_identity(root, commit, relative):
    repository_path = PLUGIN_PREFIX + "/" + relative
    raw = git(
        root, "ls-tree", "-z", commit, "--", repository_path,
        error="cannot read canary trigger identity",
    )
    entries = [entry for entry in raw.split(b"\0") if entry]
    if not entries:
        return {"kind": "absent", "mode": None, "path": relative, "sha256": None, "size": 0}
    if len(entries) != 1:
        raise ReleaseError("canary trigger identity is ambiguous: " + relative)
    header, separator, actual_path = entries[0].partition(b"\t")
    fields = header.split()
    if (not separator or len(fields) != 3
            or actual_path.decode("utf-8", errors="surrogateescape") != repository_path):
        raise ReleaseError("canary trigger identity is invalid: " + relative)
    mode, kind, object_id = (field.decode() for field in fields)
    if kind != "blob" or mode not in {"100644", "100755", "120000"}:
        raise ReleaseError("canary trigger is not a file: " + relative)
    blob = git(root, "cat-file", "blob", object_id, error="cannot read canary trigger blob")
    return {
        "kind": "symlink" if mode == "120000" else "regular",
        "mode": mode,
        "path": relative,
        "sha256": digest(blob),
        "size": len(blob),
    }


def release_selection(root_path, stable_tag, candidate_commit=None):
    root = repository_root(root_path)
    stable = stable_tag_identity(root, stable_tag)
    if candidate_commit is None:
        candidate_commit = git(
            root, "rev-parse", "HEAD", error="candidate HEAD is invalid",
        ).decode().strip()
    candidate = candidate_identity(root, candidate_commit, stable["version"])
    paths = changed_plugin_paths(root, stable["public"]["commit"], candidate_commit)
    selected = canaries_for_paths(paths)
    identities = {
        canary: [trigger_identity(root, candidate_commit, path) for path in trigger_paths]
        for canary, trigger_paths in selected.items()
    }
    return root, stable, candidate, identities


def command_vector(values):
    command = list(values)
    if command[:1] == ["--"]:
        command = command[1:]
    if (not command or len(command) > 128
            or any(not isinstance(value, str) or not value or "\0" in value for value in command)):
        raise ReleaseError("canary command vector is invalid")
    return command


def process_group_exists(group):
    try:
        os.killpg(group, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def terminate_canary(process):
    if process.poll() is None or process_group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + CANARY_TERM_GRACE_SECONDS
    while process_group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    if process_group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=CANARY_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=CANARY_TERM_GRACE_SECONDS)


class CanaryInterrupted(Exception):
    def __init__(self, signum):
        super().__init__("canary interrupted")
        self.signum = signum


def interrupt_canary(signum, _frame):
    process = _ACTIVE_CANARY
    if process is not None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    raise CanaryInterrupted(signum)


def capture_canary(command, root):
    global _ACTIVE_CANARY
    try:
        process = subprocess.Popen(
            command, cwd=root, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )
    except OSError as error:
        raise ReleaseError("cannot launch canary command") from error
    _ACTIVE_CANARY = process
    output = bytearray()
    selector = selectors.DefaultSelector()
    overflow = False
    timed_out = False
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + CANARY_TIMEOUT_SECONDS
        eof = False
        while not eof and not overflow and not timed_out:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(0.05, remaining)):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    eof = True
                    break
                available = CANARY_OUTPUT_LIMIT - len(output)
                if len(chunk) > available:
                    output.extend(chunk[:available])
                    overflow = True
                    break
                output.extend(chunk)
        if overflow or timed_out:
            terminate_canary(process)
        else:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_canary(process)
            if not timed_out and process_group_exists(process.pid):
                terminate_canary(process)
                if process.returncode == 0:
                    raise ReleaseError("canary command left a descendant process running")
        if overflow:
            return bytes(output), 125, "canary output limit exceeded"
        if timed_out:
            return bytes(output), 124, "canary command timed out"
        return bytes(output), process.returncode, None
    finally:
        if process.poll() is None or process_group_exists(process.pid):
            terminate_canary(process)
        _ACTIVE_CANARY = None
        if process.stdout is not None and not process.stdout.closed:
            try:
                selector.unregister(process.stdout)
            except KeyError:
                pass
            process.stdout.close()
        selector.close()


def evidence_identity(path_value):
    path = Path(path_value).expanduser()
    if not path.is_absolute() or ".." in path.parts or path.is_symlink():
        raise ReleaseError("canary evidence path is unsafe")
    absolute = path.resolve()
    raw = regular_bytes(absolute, "canary evidence")
    metadata = absolute.stat()
    return {
        "mode": stat.S_IMODE(metadata.st_mode),
        "path": str(absolute),
        "sha256": digest(raw),
        "size": len(raw),
    }


def emitted_evidence(output):
    paths = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or "evidence_paths" not in value:
            continue
        if set(value) != {"evidence_paths"} or encoded(value).rstrip(b"\n") != line:
            raise ReleaseError("canary evidence declaration is not canonical JSON")
        declared = value["evidence_paths"]
        if (not isinstance(declared, list)
                or any(not isinstance(path, str) or not path for path in declared)):
            raise ReleaseError("canary evidence declaration is invalid")
        paths.extend(declared)
    identities = [evidence_identity(path) for path in paths]
    if len({row["path"] for row in identities}) != len(identities):
        raise ReleaseError("canary evidence declaration contains duplicates")
    return identities


def canary_log_bytes(output, exit_code):
    raw = output
    if raw and not raw.endswith(b"\n"):
        raw += b"\n"
    return raw + encoded({"exit_code": exit_code, "release_canary_log_complete": True})


def release_output(path, root):
    lexical = Path(path).expanduser()
    if ".." in lexical.parts or lexical.is_symlink():
        raise ReleaseError("receipt must be a direct path")
    absolute = Path(os.path.abspath(lexical))
    try:
        absolute.resolve().relative_to(root)
    except ValueError:
        return absolute
    raise ReleaseError("release receipt path overlaps the candidate root")


def canary_receipt_document(path, expected_stable, canary_id, triggers, command=None):
    path = Path(path).expanduser()
    raw = regular_bytes(path, "canary receipt", mode=0o600)
    document = parse_json(raw, "canary receipt")
    if raw != encoded(document):
        raise ReleaseError("canary receipt is not canonical JSON")
    if (not isinstance(document, dict)
            or set(document) != {"schema_version", "stable", "canary", "command", "log", "evidence"}
            or document.get("schema_version") != 1
            or document.get("stable") != expected_stable
            or not isinstance(document.get("canary"), dict)
            or set(document["canary"]) != {"id", "triggers"}
            or document["canary"].get("id") != canary_id):
        raise ReleaseError("canary receipt identity is invalid")
    if document["canary"].get("triggers") != triggers:
        raise ReleaseError("stale canary trigger identity")
    actual_command = document.get("command")
    if (not isinstance(actual_command, list) or not actual_command
            or any(not isinstance(value, str) or not value for value in actual_command)
            or command is not None and actual_command != command):
        raise ReleaseError("canary command identity is invalid")
    log = document.get("log")
    expected_log_path = Path(str(path) + ".log").resolve()
    if (not isinstance(log, dict) or set(log) != {"path", "size", "sha256"}
            or log.get("path") != str(expected_log_path)
            or type(log.get("size")) is not int or log["size"] <= 0
            or log["size"] > CANARY_OUTPUT_LIMIT + 4096
            or not HASH_PATTERN.fullmatch(str(log.get("sha256", "")))):
        raise ReleaseError("canary log identity is invalid")
    log_raw = regular_bytes(
        expected_log_path, "canary log", CANARY_OUTPUT_LIMIT + 4096, mode=0o600,
    )
    if len(log_raw) != log["size"] or digest(log_raw) != log["sha256"]:
        raise ReleaseError("canary log hash mismatch")
    lines = log_raw.splitlines()
    try:
        footer = json.loads(lines[-1])
    except (IndexError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseError("canary log is truncated") from error
    if footer != {"exit_code": 0, "release_canary_log_complete": True}:
        raise ReleaseError("canary log is failed or truncated")
    evidence = document.get("evidence")
    if not isinstance(evidence, list):
        raise ReleaseError("canary evidence identity is invalid")
    try:
        actual_evidence = [evidence_identity(row["path"]) for row in evidence]
    except (KeyError, TypeError) as error:
        raise ReleaseError("canary evidence identity is invalid") from error
    if actual_evidence != evidence:
        raise ReleaseError("canary evidence identity mismatch")
    return document, digest(raw)


def validate_canaries(root_path, stable_tag, supplied):
    if not isinstance(supplied, dict):
        raise ReleaseError("canary receipt set is invalid")
    _, stable, _, requirements_map = release_selection(root_path, stable_tag)
    extra = sorted(set(supplied) - set(requirements_map))
    if extra:
        raise ReleaseError("unknown extra canary: " + extra[0])
    missing = sorted(set(requirements_map) - set(supplied))
    if missing:
        raise ReleaseError("missing required canary: " + missing[0])
    identities = {}
    for canary_id in sorted(requirements_map):
        document, receipt_hash = canary_receipt_document(
            supplied[canary_id], stable["public"], canary_id, requirements_map[canary_id],
        )
        identities[canary_id] = {"receipt": document, "sha256": receipt_hash}
    return identities


def run_canary(args):
    root, stable, candidate, requirements_map = release_selection(args.root, args.stable_tag)
    if args.id not in KNOWN_CANARIES or args.id not in requirements_map:
        raise ReleaseError("canary is not required by the current candidate: " + args.id)
    command = command_vector(args.command)
    out = release_output(args.out, root)
    if out.exists() or out.is_symlink():
        try:
            canary_receipt_document(
                out, stable["public"], args.id, requirements_map[args.id], command,
            )
        except ReleaseError as error:
            raise ReleaseError("receipt collision") from error
        print(out)
        return
    log_path = Path(str(out) + ".log")
    if log_path.exists() or log_path.is_symlink():
        raise ReleaseError("canary log collision")
    output, exit_code, failure = capture_canary(command, root)
    log_raw = canary_log_bytes(output, exit_code)
    if failure is not None:
        publish_bytes(log_path, log_raw, "canary log")
        raise ReleaseError(failure)
    if exit_code != 0:
        publish_bytes(log_path, log_raw, "canary log")
        raise ReleaseError("canary command failed with exit " + str(exit_code))
    evidence = emitted_evidence(output)
    final_root, final_stable, final_candidate, final_requirements = release_selection(
        root, args.stable_tag,
    )
    if (final_root != root or final_stable != stable or final_candidate != candidate
            or final_requirements.get(args.id) != requirements_map[args.id]):
        raise ReleaseError("release identity changed during canary execution")
    log_path = publish_bytes(log_path, log_raw, "canary log")
    receipt = {
        "schema_version": 1,
        "stable": stable["public"],
        "canary": {"id": args.id, "triggers": requirements_map[args.id]},
        "command": command,
        "log": {"path": str(log_path.resolve()), "size": len(log_raw), "sha256": digest(log_raw)},
        "evidence": evidence,
    }
    path = publish_json(out, receipt)
    print(path)


def session_name(value, source):
    if (not isinstance(value, str) or not value or Path(value).name != value
            or value in {".", ".."} or "\0" in value):
        raise ReleaseError(source + " path is invalid")
    return value


def session_file(session, name, source, captured, maximum=16 * 1024 * 1024):
    name = session_name(name, source)
    path = session / name
    raw = regular_bytes(path, source, maximum=maximum)
    prior = captured.get(path)
    if prior is not None and prior != raw:
        raise ReleaseError(source + " changed during validation")
    captured[path] = raw
    return raw


def scope_values(raw):
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise ReleaseError("scope metadata is invalid") from error
    values = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if (not separator or not re.fullmatch(r"REV_[A-Z_]+", name)
                or name in values):
            raise ReleaseError("scope metadata is invalid")
        try:
            words = shlex.split(value, posix=True)
        except ValueError as error:
            raise ReleaseError("scope metadata is invalid") from error
        if len(words) != 1 or not words[0]:
            raise ReleaseError("scope metadata is invalid")
        values[name] = words[0]
    if not all(values.get(name) for name in ("REV_ROOT", "REV_BASE", "REV_SCOPE")):
        raise ReleaseError("scope metadata is incomplete")
    return values


def run_stable_checker(stable_plugin, checker_snapshot, root, session, base, roster_path):
    checker = stable_plugin / "scripts" / "rev-contract-check.py"
    launcher = (
        "import os,sys;"
        "path=sys.argv[1];"
        "sys.path[0]=os.path.dirname(path);"
        "sys.argv=sys.argv[1:];"
        "source=sys.stdin.buffer.read();"
        "namespace={'__name__':'__main__','__file__':path};"
        "exec(compile(source,path,'exec'),namespace)"
    )
    command = [
        sys.executable, "-I", "-B", "-c", launcher, str(checker), "--root", str(root),
        "--session", str(session), "--base", base, "--roster", str(roster_path),
        "--verify-only",
    ]
    try:
        result = subprocess.run(
            command, input=checker_snapshot, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseError("stable contract checker failed") from error
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise ReleaseError("stable contract checker failed" + (": " + detail if detail else ""))
    lines = [
        line.strip() for line in result.stdout.decode(errors="replace").splitlines()
        if line.strip()
    ]
    if not lines:
        raise ReleaseError("stable contract checker did not name a contract receipt")
    raw_path = Path(lines[-1]).expanduser()
    if not raw_path.is_absolute() or ".." in raw_path.parts or raw_path.is_symlink():
        raise ReleaseError("stable contract checker returned an unsafe receipt path")
    path = Path(os.path.abspath(raw_path))
    if path.parent.resolve() != session or path.parent.is_symlink():
        raise ReleaseError("stable contract receipt is outside the session")
    match = re.fullmatch(r"contract-pass-([0-9a-f]{64})\.json", path.name)
    if not match:
        raise ReleaseError("stable contract receipt path is invalid")
    return path, match.group(1)


def validate_review_session(session_path, root, candidate, stable_plugin, checker_snapshot):
    session = direct_directory(session_path, "session")
    captured = {}
    scope_raw = session_file(session, "scope.env", "scope metadata", captured)
    values = scope_values(scope_raw)
    try:
        scoped_root = Path(values["REV_ROOT"]).expanduser().resolve(strict=True)
    except OSError as error:
        raise ReleaseError("scope root is invalid") from error
    if scoped_root != root:
        raise ReleaseError("scope root does not match candidate root")
    roster_raw = session_file(session, "roster.json", "session roster", captured)
    roster = parse_json(roster_raw, "session roster")
    if not isinstance(roster, dict) or not isinstance(roster.get("seats"), list):
        raise ReleaseError("session roster is invalid")
    roster_path = session / "roster.json"
    contract_path, contract_key = run_stable_checker(
        stable_plugin, checker_snapshot, root, session, values["REV_BASE"], roster_path,
    )
    contract_raw = regular_bytes(contract_path, "stable contract receipt")
    captured[contract_path] = contract_raw
    contract = parse_json(contract_raw, "stable contract receipt")
    expected_contract_keys = {
        "schema_version", "key", "identity", "touched_boundaries", "log_sha256",
    }
    if (not isinstance(contract, dict) or set(contract) != expected_contract_keys
            or contract.get("schema_version") != 2 or contract.get("key") != contract_key
            or not HASH_PATTERN.fullmatch(str(contract.get("log_sha256", "")))):
        raise ReleaseError("stable contract receipt is invalid")
    contract_identity = contract.get("identity")
    executor = contract_identity.get("executor") if isinstance(contract_identity, dict) else None
    if not isinstance(executor, dict) or executor.get("plugin") != str(stable_plugin):
        raise ReleaseError("contract executor is not the verified stable plugin")
    head_raw = session_file(session, "coverage-head.json", "coverage head", captured)
    head = parse_json(head_raw, "coverage head")
    if (not isinstance(head, dict) or set(head) != {"receipt", "sha256"}
            or not HASH_PATTERN.fullmatch(str(head.get("sha256", "")))):
        raise ReleaseError("coverage head is invalid")
    coverage_name = session_name(head.get("receipt"), "coverage receipt")
    coverage_raw = session_file(session, coverage_name, "coverage receipt", captured)
    if digest(coverage_raw) != head["sha256"]:
        raise ReleaseError("coverage receipt hash mismatch")
    coverage = parse_json(coverage_raw, "coverage receipt")
    required_coverage = {
        "schema_version", "manifest", "manifest_sha256", "snapshot_tree", "base_tree",
        "phase", "assignments", "results", "advisories", "findings",
    }
    if (not isinstance(coverage, dict) or coverage.get("schema_version") not in {1, 2}
            or not required_coverage <= set(coverage)
            or not HASH_PATTERN.fullmatch(str(coverage.get("manifest_sha256", "")))):
        raise ReleaseError("coverage receipt is invalid")
    manifest_name = session_name(coverage.get("manifest"), "coverage manifest")
    manifest_raw = session_file(session, manifest_name, "coverage manifest", captured)
    if digest(manifest_raw) != coverage["manifest_sha256"]:
        raise ReleaseError("coverage manifest hash mismatch")
    manifest = parse_json(manifest_raw, "coverage manifest")
    if (not isinstance(manifest, dict)
            or manifest.get("snapshot_tree") != coverage.get("snapshot_tree")
            or manifest.get("base_tree") != coverage.get("base_tree")):
        raise ReleaseError("coverage manifest identity mismatch")
    if coverage["snapshot_tree"] != candidate["tree"]:
        raise ReleaseError("reviewed tree does not equal candidate tree")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ReleaseError("coverage manifest inputs are invalid")
    required_inputs = {"scope.env", "roster.json", "files.txt", "untracked.txt", contract_path.name}
    if not required_inputs <= set(inputs):
        raise ReleaseError("coverage manifest is missing decision inputs")
    for name, expected_hash in inputs.items():
        if not HASH_PATTERN.fullmatch(str(expected_hash or "")):
            raise ReleaseError("coverage input hash is invalid")
        raw = session_file(session, name, "coverage input", captured)
        if digest(raw) != expected_hash:
            raise ReleaseError("coverage input hash mismatch: " + name)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ReleaseError("coverage manifest artifacts are invalid")
    for name, metadata in artifacts.items():
        if (not isinstance(metadata, dict) or set(metadata) != {"sha256", "words"}
                or not HASH_PATTERN.fullmatch(str(metadata.get("sha256", "")))
                or not isinstance(metadata.get("words"), int)
                or isinstance(metadata.get("words"), bool) or metadata["words"] < 0):
            raise ReleaseError("coverage artifact identity is invalid")
        raw = session_file(session, name, "coverage artifact", captured)
        if digest(raw) != metadata["sha256"]:
            raise ReleaseError("coverage artifact hash mismatch: " + name)
        if len(raw.split()) != metadata["words"]:
            raise ReleaseError("coverage artifact word count mismatch: " + name)
    results = coverage.get("results")
    if not isinstance(results, dict) or not results:
        raise ReleaseError("coverage result hashes are invalid")
    for name, expected_hash in results.items():
        if not HASH_PATTERN.fullmatch(str(expected_hash or "")):
            raise ReleaseError("coverage result hash is invalid")
        raw = session_file(session, name, "coverage result", captured)
        if digest(raw) != expected_hash:
            raise ReleaseError("coverage result hash mismatch: " + name)
    state_raw = session_file(session, "state.json", "review state", captured)
    if not isinstance(parse_json(state_raw, "review state"), dict):
        raise ReleaseError("review state is invalid")
    findings_raw = session_file(session, "findings.md", "findings ledger", captured)
    try:
        findings = findings_raw.decode("utf-8")
    except UnicodeError as error:
        raise ReleaseError("findings ledger is invalid") from error
    if not findings.strip():
        raise ReleaseError("findings ledger is invalid")
    stop = None
    attempts_path = session / "attempts"
    if attempts_path.exists() or attempts_path.is_symlink():
        attempts = direct_directory(attempts_path, "attempt state")
        stop_path = attempts / "session.stopped.json"
        if stop_path.exists() or stop_path.is_symlink():
            stop_raw = regular_bytes(stop_path, "session stop marker")
            captured[stop_path] = stop_raw
            stop = parse_json(stop_raw, "session stop marker")
            if (not isinstance(stop, dict) or stop.get("stopped") is not True
                    or not isinstance(stop.get("reason"), str) or not stop["reason"]):
                raise ReleaseError("session stop marker is invalid")
    for path, original in captured.items():
        if regular_bytes(path, "review decision artifact") != original:
            raise ReleaseError("review decision artifact changed during validation")
    records = []
    for path, raw in captured.items():
        try:
            name = path.relative_to(session).as_posix()
        except ValueError as error:
            raise ReleaseError("review decision artifact is outside the session") from error
        records.append({"path": name, "sha256": digest(raw), "size": len(raw)})
    records.sort(key=lambda row: row["path"])
    return digest(encoded(records)), stop


def nonnegative(value):
    if not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise argparse.ArgumentTypeError("count must be a nonnegative integer")
    return int(value)


def record_review(args):
    root = repository_root(args.root)
    stable_plugin = direct_directory(args.stable_plugin, "stable plugin")
    checker_name = "scripts/rev-contract-check.py"
    stable, stable_material = verified_stable_material(
        root, args.stable_tag, stable_plugin, (checker_name,),
    )
    checker_snapshot = stable_material[checker_name]
    stable_version = tag_version(args.stable_tag)
    candidate = candidate_identity(root, args.candidate_commit, stable_version)
    session_identity, stop = validate_review_session(
        args.session, root, candidate, stable_plugin, checker_snapshot,
    )
    counts = {
        "new_p0": args.new_p0, "new_p1": args.new_p1,
        "open_p0": args.open_p0, "open_p1": args.open_p1,
    }
    if stop is not None and any(counts.values()):
        raise ReleaseError("stopped session accepts no product counts")
    final_stable = stable_identity(root, args.stable_tag, stable_plugin)
    final_candidate = candidate_identity(root, args.candidate_commit, stable_version)
    if final_stable != stable or final_candidate != candidate:
        raise ReleaseError("release identity changed during review validation")
    status = (
        "infrastructure-blocked" if stop is not None
        else "clean" if not any(counts.values())
        else "correction-required"
    )
    receipt = {
        "schema_version": 1,
        "stable": stable,
        "candidate": candidate,
        "review": {"session_identity": session_identity, **counts},
        "status": status,
    }
    path = publish_json(release_output(args.out, root), receipt)
    print(path)


def frozen_source_key(root):
    environment = dict(
        os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
    )
    raw_paths = git(
        root, "ls-files", "-z", "--cached", "--others", "--exclude-standard",
        error="cannot enumerate the final candidate",
        environment=environment,
    )
    paths = []
    for raw_path in raw_paths.split(b"\0"):
        if not raw_path:
            continue
        name = raw_path.decode("utf-8", errors="surrogateescape")
        path = Path(name)
        if path.is_absolute() or "." in path.parts or ".." in path.parts:
            raise ReleaseError("final candidate contains an unsafe Git path")
        paths.append(name)
    if len(paths) != len(set(paths)):
        raise ReleaseError("final candidate contains a duplicate Git path")
    records = []
    for name in sorted(paths):
        path = root / name
        try:
            descriptor = os.open(path, os.O_RDONLY | NOFOLLOW)
        except FileNotFoundError:
            records.append({"path": name, "type": "deleted"})
            continue
        except OSError as error:
            raise ReleaseError("final candidate contains a nonregular path: " + name) from error
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ReleaseError("final candidate contains a nonregular path: " + name)
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ReleaseError("final candidate changed while captured: " + name)
        file_raw = b"".join(chunks)
        records.append({
            "path": name,
            "type": "file",
            "executable": bool(after.st_mode & 0o111),
            "size": len(file_raw),
            "sha256": digest(file_raw),
        })
    canonical_records = json.dumps(
        records, sort_keys=True, separators=(",", ":"),
    ).encode()
    return digest(canonical_records)


def historical_candidate(root, document, stable_version):
    if not isinstance(document, dict) or set(document) != {"version", "commit", "tree"}:
        raise ReleaseError("review candidate identity is invalid")
    commit = document.get("commit")
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseError("review candidate commit is invalid")
    resolved = git(
        root, "rev-parse", "--verify", commit + "^{commit}",
        error="review candidate commit is invalid",
    ).decode().strip()
    tree = git(
        root, "rev-parse", commit + "^{tree}", error="review candidate tree is invalid",
    ).decode().strip()
    if resolved != commit or document.get("tree") != tree:
        raise ReleaseError("review candidate identity is invalid")
    versions = set()
    for relative in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        raw = git(
            root, "show", commit + ":" + PLUGIN_PREFIX + "/" + relative,
            error="review candidate manifest is unavailable",
        )
        versions.add(manifest_version(raw, "review candidate " + relative))
    if (len(versions) != 1 or document.get("version") != next(iter(versions))
            or version_tuple(document["version"], "review candidate")
            <= version_tuple(stable_version, "stable")):
        raise ReleaseError("review candidate version is invalid")
    return document


def review_receipt_document(path, root, stable):
    raw = regular_bytes(path, "review receipt", mode=0o600)
    document = parse_json(raw, "review receipt")
    if raw != encoded(document):
        raise ReleaseError("review receipt is not canonical JSON")
    if (not isinstance(document, dict)
            or set(document) != {"schema_version", "stable", "candidate", "review", "status"}
            or document.get("schema_version") != 1 or document.get("stable") != stable):
        raise ReleaseError("review receipt identity is invalid")
    historical_candidate(root, document.get("candidate"), tag_version(stable["tag"]))
    review = document.get("review")
    count_names = ("new_p0", "new_p1", "open_p0", "open_p1")
    if (not isinstance(review, dict)
            or set(review) != {"session_identity", *count_names}
            or not HASH_PATTERN.fullmatch(str(review.get("session_identity", "")))
            or any(type(review.get(name)) is not int or review[name] < 0 for name in count_names)):
        raise ReleaseError("review decision is invalid")
    has_counts = any(review[name] for name in count_names)
    status = document.get("status")
    if (status == "clean" and has_counts
            or status == "correction-required" and not has_counts
            or status == "infrastructure-blocked" and has_counts
            or status not in {"clean", "correction-required", "infrastructure-blocked"}):
        raise ReleaseError("review decision status is invalid")
    return document, digest(raw)


def verifier_receipt_document(path, expected_tree_key):
    raw = regular_bytes(path, "verifier receipt", mode=0o600)
    document = parse_json(raw, "verifier receipt")
    if raw != encoded(document):
        raise ReleaseError("verifier receipt is not canonical JSON")
    if (not isinstance(document, dict)
            or set(document) != {"schema_version", "key", "identity", "logs"}
            or document.get("schema_version") != 1
            or not isinstance(document.get("identity"), dict)):
        raise ReleaseError("verifier receipt is invalid")
    identity = document["identity"]
    if set(identity) != {"tree", "commands", "child_environment", "platform", "tools"}:
        raise ReleaseError("verifier identity is invalid")
    if identity.get("tree") != expected_tree_key:
        raise ReleaseError("verifier tree does not equal final candidate")
    if identity.get("commands") != DEFAULT_COMMANDS:
        raise ReleaseError("verifier command set mismatch")
    identity_raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    if document.get("key") != digest(identity_raw):
        raise ReleaseError("verifier key mismatch")
    logs = document.get("logs")
    command_names = [command["name"] for command in DEFAULT_COMMANDS]
    if not isinstance(logs, dict) or set(logs) != set(command_names):
        raise ReleaseError("verifier log set mismatch")
    log_parent = None
    for name in command_names:
        log = logs[name]
        if (not isinstance(log, dict) or set(log) != {"path", "size", "sha256"}
                or not isinstance(log.get("path"), str)
                or type(log.get("size")) is not int or log["size"] <= 0
                or not HASH_PATTERN.fullmatch(str(log.get("sha256", "")))):
            raise ReleaseError("verifier log identity is invalid: " + name)
        log_path = Path(log["path"]).expanduser()
        if (not log_path.is_absolute() or ".." in log_path.parts or log_path.is_symlink()
                or log_path.name != name + ".log"):
            raise ReleaseError("verifier log path is invalid: " + name)
        if log_parent is None:
            log_parent = log_path.parent.resolve()
        elif log_path.parent.resolve() != log_parent:
            raise ReleaseError("verifier logs do not share one directory")
        log_raw = regular_bytes(log_path, "verifier log", maximum=256 * 1024 * 1024)
        if len(log_raw) != log["size"] or digest(log_raw) != log["sha256"]:
            raise ReleaseError("verifier log hash mismatch: " + name)
        lines = log_raw.splitlines()
        try:
            footer = json.loads(lines[-1])
        except (IndexError, UnicodeError, json.JSONDecodeError) as error:
            raise ReleaseError("verifier log is failed or truncated: " + name) from error
        if footer != {"review_council_log_complete": True, "exit_code": 0}:
            raise ReleaseError("verifier log is failed or truncated: " + name)
    return document, digest(raw)


def canary_arguments(values):
    result = {}
    for value in values:
        canary_id, separator, path = value.partition("=")
        if not separator or not canary_id or not path or canary_id in result:
            raise ReleaseError("canary argument is invalid or duplicate")
        result[canary_id] = Path(path)
    return result


def certify(args):
    if len(args.review) not in {1, 2}:
        raise ReleaseError("certification requires one or two review receipts")
    root = repository_root(args.root)
    stable_plugin = direct_directory(args.stable_plugin, "stable plugin")
    stable = stable_identity(root, args.stable_tag, stable_plugin)
    candidate = candidate_identity(root, args.candidate_commit, tag_version(args.stable_tag))
    review_documents = []
    review_hashes = []
    for path in args.review:
        document, receipt_hash = review_receipt_document(path, root, stable)
        review_documents.append(document)
        review_hashes.append(receipt_hash)
    latest = review_documents[-1]
    if latest["status"] != "clean":
        raise ReleaseError("latest review is not clean")
    if latest["candidate"] != candidate:
        raise ReleaseError("latest review does not cover the final candidate")
    if len(review_documents) == 2:
        first, second = review_documents
        if first["status"] == "clean":
            raise ReleaseError("clean initial review forbids a second review")
        if first["status"] != "correction-required":
            raise ReleaseError("initial review does not authorize a delta review")
        if first["candidate"]["commit"] == second["candidate"]["commit"]:
            raise ReleaseError("delta review must use a different candidate commit")
    tree_key = frozen_source_key(root)
    verification, verification_hash = verifier_receipt_document(
        args.verification_receipt, tree_key,
    )
    canaries = validate_canaries(root, args.stable_tag, canary_arguments(args.canary))
    final_stable = stable_identity(root, args.stable_tag, stable_plugin)
    final_candidate = candidate_identity(root, args.candidate_commit, tag_version(args.stable_tag))
    if final_stable != stable or final_candidate != candidate or frozen_source_key(root) != tree_key:
        raise ReleaseError("release identity changed during certification")
    receipt = {
        "schema_version": 1,
        "stable": stable,
        "candidate": candidate,
        "reviews": review_hashes,
        "verification": {"key": verification["key"], "sha256": verification_hash},
        "canaries": {name: value["sha256"] for name, value in sorted(canaries.items())},
        "status": "certified",
    }
    path = publish_json(release_output(args.out, root), receipt)
    print(path)


def requirements(args):
    _, _, _, selected = release_selection(
        args.root, args.stable_tag, args.candidate_commit,
    )
    sys.stdout.buffer.write(encoded(sorted(selected)))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    required = commands.add_parser("requirements")
    required.add_argument("--root", required=True, type=Path)
    required.add_argument("--candidate-commit", required=True)
    required.add_argument("--stable-tag", required=True)
    required.set_defaults(function=requirements)
    review = commands.add_parser("record-review")
    review.add_argument("--root", required=True, type=Path)
    review.add_argument("--candidate-commit", required=True)
    review.add_argument("--stable-plugin", required=True, type=Path)
    review.add_argument("--stable-tag", required=True)
    review.add_argument("--session", required=True, type=Path)
    review.add_argument("--new-p0", required=True, type=nonnegative)
    review.add_argument("--new-p1", required=True, type=nonnegative)
    review.add_argument("--open-p0", required=True, type=nonnegative)
    review.add_argument("--open-p1", required=True, type=nonnegative)
    review.add_argument("--out", required=True, type=Path)
    review.set_defaults(function=record_review)
    canary = commands.add_parser("run-canary")
    canary.add_argument("--root", required=True, type=Path)
    canary.add_argument("--stable-tag", required=True)
    canary.add_argument("--id", required=True)
    canary.add_argument("--out", required=True, type=Path)
    canary.add_argument("command", nargs=argparse.REMAINDER)
    canary.set_defaults(function=run_canary)
    certificate = commands.add_parser("certify")
    certificate.add_argument("--root", required=True, type=Path)
    certificate.add_argument("--candidate-commit", required=True)
    certificate.add_argument("--stable-plugin", required=True, type=Path)
    certificate.add_argument("--stable-tag", required=True)
    certificate.add_argument("--review", action="append", default=[], type=Path)
    certificate.add_argument("--verification-receipt", required=True, type=Path)
    certificate.add_argument("--canary", action="append", default=[])
    certificate.add_argument("--out", required=True, type=Path)
    certificate.set_defaults(function=certify)
    return result


def main():
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    for handled_signal in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(handled_signal, interrupt_canary)
    try:
        main()
    except CanaryInterrupted as error:
        sys.exit(128 + error.signum)
    except (OSError, ReleaseError, subprocess.SubprocessError) as error:
        print("release lane: " + str(error), file=sys.stderr)
        sys.exit(2)
