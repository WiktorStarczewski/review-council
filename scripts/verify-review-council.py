#!/usr/bin/env python3
"""Run the complete Review Council verification gate against one frozen tree."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time


REPO = Path(__file__).resolve().parents[1]
DEFAULT_COMMANDS = [
    {"name": "shell", "kind": "shell", "argv": ["plugins/review-council/tests/run-tests.sh"]},
    {"name": "python", "kind": "python", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]},
    {"name": "claude-marketplace", "kind": "validator", "argv": ["claude", "plugin", "validate", "--strict", ".claude-plugin/marketplace.json"]},
    {"name": "claude-plugin", "kind": "validator", "argv": ["claude", "plugin", "validate", "--strict", "plugins/review-council"]},
    {"name": "codex-marketplace", "kind": "validator", "argv": ["python3", "tests/check-codex-marketplace.py"]},
]
DEFAULT_INDIRECT_TOOLS = ("bash", "git", "node", "codex")
SELECTOR_ENV = (
    "REVIEW_COUNCIL_TEST_TASK",
    "REVIEW_COUNCIL_TEST_RESULTS_FILE",
    "REVIEW_COUNCIL_TEST_DISCOVER",
    "REVIEW_COUNCIL_TEST_SHARD",
    "REV_EVIDENCE_CASE",
    "REV_EVIDENCE_GROUP",
)
NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ACTIVE_LOCK = threading.Lock()
ACTIVE_PROCESSES = {}
CANCEL_REQUESTED = threading.Event()
SIGNAL_CANCELLATION = 0
DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY_EXEC = (
    "import os,sys; "
    "os.fchdir(int(sys.argv[1])); "
    "os.execvpe(sys.argv[2], sys.argv[2:], os.environ)"
)


class VerificationError(RuntimeError):
    pass


class VerificationCancelled(VerificationError):
    pass


class OpenDirectory:
    def __init__(self, descriptor, path):
        self.descriptor = descriptor
        self.path = Path(path)

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def duplicate(self):
        return OpenDirectory(os.dup(self.descriptor), self.path)

    def child(self, name, create=False, mode=0o700, private=False):
        validate_component(name)
        created = False
        try:
            descriptor = os.open(name, DIRECTORY_FLAGS, dir_fd=self.descriptor)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(name, mode, dir_fd=self.descriptor)
                created = True
            except FileExistsError:
                pass
            descriptor = os.open(name, DIRECTORY_FLAGS, dir_fd=self.descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            raise VerificationError("verification state path is not a directory")
        if created or private:
            os.fchmod(descriptor, mode)
        return OpenDirectory(descriptor, self.path / name)


def validate_component(name):
    if not isinstance(name, str) or not name or name in {".", ".."} or os.sep in name:
        raise VerificationError("unsafe verification state component")


def same_identity(left, right):
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def open_source_root(path):
    try:
        descriptor = os.open(str(path), DIRECTORY_FLAGS)
    except OSError as error:
        raise VerificationError("root must be a Git worktree") from error
    root = OpenDirectory(descriptor, path)
    try:
        os.stat(".git", dir_fd=descriptor, follow_symlinks=False)
    except OSError as error:
        root.close()
        raise VerificationError("root must be a Git worktree") from error
    return root


def validate_existing_state_path(source, path):
    source_identity = os.fstat(source.descriptor)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(os.sep, flags)
    try:
        for name in path.parts[1:]:
            if same_identity(os.fstat(descriptor), source_identity):
                raise VerificationError("verification state path overlaps the source tree")
            try:
                child = os.open(name, flags, dir_fd=descriptor)
            except FileNotFoundError:
                return
            except OSError as error:
                raise VerificationError("verification state path is not a directory") from error
            os.close(descriptor)
            descriptor = child
        if same_identity(os.fstat(descriptor), source_identity):
            raise VerificationError("verification state path overlaps the source tree")
    finally:
        os.close(descriptor)


def open_state_root(source, path):
    validate_existing_state_path(source, path)
    path = Path(os.path.realpath(path))
    source_identity = os.fstat(source.descriptor)
    current = OpenDirectory(os.open(os.sep, DIRECTORY_FLAGS), Path(os.sep))
    try:
        for name in path.parts[1:]:
            if same_identity(os.fstat(current.descriptor), source_identity):
                raise VerificationError("verification state path overlaps the source tree")
            try:
                child = current.child(name, create=True)
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise VerificationError(
                        "verification state path overlaps the source tree or uses a symlink"
                    ) from error
                raise
            current.close()
            current = child
            if same_identity(os.fstat(current.descriptor), source_identity):
                raise VerificationError("verification state path overlaps the source tree")
        os.fchmod(current.descriptor, 0o700)
        current.path = path
        return current
    except Exception:
        current.close()
        raise


def open_directory_path(root, relative, create=False, mode=0o700, private=False):
    current = root.duplicate()
    try:
        parts = relative if isinstance(relative, (tuple, list)) else Path(relative).parts
        for name in parts:
            child = current.child(name, create=create, mode=mode, private=private)
            current.close()
            current = child
        return current
    except Exception:
        current.close()
        raise


def run_in_directory(directory, argv, **kwargs):
    return subprocess.run(
        [sys.executable, "-c", DIRECTORY_EXEC, str(directory.descriptor), *argv],
        pass_fds=(directory.descriptor,), **kwargs,
    )


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity_key(identity):
    return digest(encoded(identity))


def build_identity(tree, commands, child_environment, platform_data, tools):
    return {
        "tree": tree,
        "commands": commands,
        "child_environment": child_environment,
        "platform": platform_data,
        "tools": tools,
    }


def platform_identity():
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
    }


def safe_unlink(directory, name):
    try:
        os.unlink(name, dir_fd=directory.descriptor)
    except FileNotFoundError:
        pass


def safe_regular(path, require_single_link=True):
    try:
        metadata = path.lstat()
    except OSError:
        return None
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        return None
    if require_single_link and metadata.st_nlink != 1:
        return None
    return metadata


def read_descriptor(descriptor):
    chunks = []
    while True:
        raw = os.read(descriptor, 1024 * 1024)
        if not raw:
            return b"".join(chunks)
        chunks.append(raw)


def open_regular_path(root, relative, require_single_link=True):
    parts = Path(relative).parts
    parent = open_directory_path(root, parts[:-1]) if len(parts) > 1 else root.duplicate()
    try:
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NONBLOCK | NOFOLLOW,
            dir_fd=parent.descriptor,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or (require_single_link and metadata.st_nlink != 1):
            os.close(descriptor)
            raise VerificationError("verification state file is not a private regular file")
        return descriptor, metadata
    finally:
        parent.close()


def atomic_write(directory, name, raw, mode=0o600):
    temporary = ".new-" + secrets.token_hex(12)
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        mode, dir_fd=directory.descriptor,
    )
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(
            temporary, name,
            src_dir_fd=directory.descriptor, dst_dir_fd=directory.descriptor,
        )
        os.fsync(directory.descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        safe_unlink(directory, temporary)


def git_paths(root):
    environment = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    result = run_in_directory(
        root, ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        env=environment, capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        raise VerificationError("cannot enumerate the Git tree: " + result.stderr.decode(errors="replace").strip())
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        pure = Path(name)
        if pure.is_absolute() or ".." in pure.parts or name == ".git" or name.startswith(".git/"):
            raise VerificationError("unsafe Git path: " + name)
        paths.append(name)
    if len(paths) != len(set(paths)):
        raise VerificationError("duplicate Git path")
    return sorted(paths)


def capture_source(root):
    paths = git_paths(root)
    records = []
    contents = {}
    for name in paths:
        try:
            descriptor, before = open_regular_path(root, name, require_single_link=False)
        except FileNotFoundError:
            records.append({"path": name, "type": "deleted"})
            continue
        except (OSError, VerificationError) as error:
            raise VerificationError("Git tree contains a nonregular path: " + name)
        try:
            raw = read_descriptor(descriptor)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        boundary_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        boundary_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if boundary_before != boundary_after:
            raise VerificationError("source tree changed while captured: " + name)
        executable = bool(after.st_mode & 0o111)
        records.append({
            "path": name,
            "type": "file",
            "executable": executable,
            "size": len(raw),
            "sha256": digest(raw),
        })
        contents[name] = raw
    return records, contents


def capture_stable_source(root):
    first_records, contents = capture_source(root)
    second_records, _ = capture_source(root)
    if first_records != second_records:
        raise VerificationError("source tree changed while captured")
    return first_records, contents


def remove_entry(parent, name):
    validate_component(name)
    try:
        metadata = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(metadata.st_mode):
        os.unlink(name, dir_fd=parent.descriptor)
        return
    child = parent.child(name)
    try:
        os.fchmod(child.descriptor, 0o700)
        for entry in os.listdir(child.descriptor):
            remove_entry(child, entry)
    finally:
        child.close()
    os.rmdir(name, dir_fd=parent.descriptor)


def expected_material_records(source_records):
    files = []
    directories = {"."}
    for record in source_records:
        if record["type"] != "file":
            continue
        parts = Path(record["path"]).parts
        for index in range(1, len(parts)):
            directories.add(str(Path(*parts[:index])))
        files.append({
            "path": record["path"],
            "mode": 0o555 if record["executable"] else 0o444,
            "size": record["size"],
            "sha256": record["sha256"],
        })
    return {
        "directories": [{"path": name, "mode": 0o555} for name in sorted(directories)],
        "files": sorted(files, key=lambda row: row["path"]),
    }


def inspect_material(root):
    directories = [{"path": ".", "mode": stat.S_IMODE(os.fstat(root.descriptor).st_mode)}]
    files = []

    def inspect(directory, prefix):
        for name in sorted(os.listdir(directory.descriptor)):
            relative = str(Path(prefix) / name) if prefix else name
            metadata = os.stat(name, dir_fd=directory.descriptor, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise VerificationError("materialized tree contains a symlink: " + relative)
            if stat.S_ISDIR(metadata.st_mode):
                child = directory.child(name)
                try:
                    actual = os.fstat(child.descriptor)
                    if not same_identity(metadata, actual):
                        raise VerificationError("materialized tree changed while inspected: " + relative)
                    directories.append({"path": relative, "mode": stat.S_IMODE(actual.st_mode)})
                    inspect(child, relative)
                finally:
                    child.close()
                continue
            try:
                descriptor = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=directory.descriptor)
            except OSError as error:
                raise VerificationError("materialized tree contains a nonregular file: " + relative) from error
            try:
                actual = os.fstat(descriptor)
                if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                        or not same_identity(metadata, actual)):
                    raise VerificationError("materialized tree contains a nonregular file: " + relative)
                raw = read_descriptor(descriptor)
            finally:
                os.close(descriptor)
            files.append({
                "path": relative,
                "mode": stat.S_IMODE(actual.st_mode),
                "size": len(raw),
                "sha256": digest(raw),
            })

    inspect(root, "")
    return {
        "directories": sorted(directories, key=lambda row: row["path"]),
        "files": sorted(files, key=lambda row: row["path"]),
    }


def freeze_directories(root):
    for name in os.listdir(root.descriptor):
        metadata = os.stat(name, dir_fd=root.descriptor, follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode):
            continue
        child = root.child(name)
        try:
            freeze_directories(child)
        finally:
            child.close()
    os.fchmod(root.descriptor, 0o555)


def materialize(state, source_records, contents):
    trees = state.child("trees", create=True, private=True)
    try:
        return materialize_in(trees, source_records, contents)
    finally:
        trees.close()


def materialize_in(trees, source_records, contents):
    source_key = digest(encoded(source_records))
    expected = expected_material_records(source_records)
    target = None
    try:
        target = trees.child(source_key)
    except FileNotFoundError:
        pass
    if target is not None:
        try:
            if inspect_material(target) == expected:
                try:
                    for sibling in os.listdir(trees.descriptor):
                        if sibling != source_key:
                            remove_entry(trees, sibling)
                except Exception:
                    target.close()
                    raise
                return target, source_key, expected
        except (OSError, VerificationError):
            pass
        target.close()
        target = None
        remove_entry(trees, source_key)
    stage_name = ".tree-" + secrets.token_hex(12)
    os.mkdir(stage_name, 0o700, dir_fd=trees.descriptor)
    stage = trees.child(stage_name)
    try:
        for record in source_records:
            if record["type"] != "file":
                continue
            parts = Path(record["path"]).parts
            parent = open_directory_path(stage, parts[:-1], create=True, private=True)
            try:
                descriptor = os.open(
                    parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
                    0o600, dir_fd=parent.descriptor,
                )
                try:
                    with os.fdopen(descriptor, "wb", closefd=False) as output:
                        output.write(contents[record["path"]])
                    os.fchmod(descriptor, 0o555 if record["executable"] else 0o444)
                finally:
                    os.close(descriptor)
            finally:
                parent.close()
        freeze_directories(stage)
        os.replace(
            stage_name, source_key,
            src_dir_fd=trees.descriptor, dst_dir_fd=trees.descriptor,
        )
        stage.close()
        stage = None
    finally:
        if stage is not None:
            stage.close()
            remove_entry(trees, stage_name)
    target = trees.child(source_key)
    if inspect_material(target) != expected:
        target.close()
        remove_entry(trees, source_key)
        raise VerificationError("materialized tree does not match its captured source")
    try:
        for sibling in os.listdir(trees.descriptor):
            if sibling != source_key:
                remove_entry(trees, sibling)
    except Exception:
        target.close()
        raise
    return target, source_key, expected


def read_commands(path):
    if path is None:
        commands = DEFAULT_COMMANDS
    else:
        metadata = safe_regular(path)
        if metadata is None or metadata.st_size > 1024 * 1024:
            raise VerificationError("commands file must be one bounded regular file")
        try:
            document = json.loads(path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise VerificationError("commands file is invalid") from error
        if not isinstance(document, dict) or set(document) != {"commands"}:
            raise VerificationError("commands file must contain only commands")
        commands = document["commands"]
    if not isinstance(commands, list) or not 2 <= len(commands) <= 32:
        raise VerificationError("verification requires 2 to 32 commands")
    normalized = []
    names = set()
    kinds = []
    for row in commands:
        if not isinstance(row, dict) or set(row) != {"name", "kind", "argv"}:
            raise VerificationError("invalid verification command")
        name, kind, argv = row["name"], row["kind"], row["argv"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise VerificationError("invalid or duplicate verification command name")
        if kind not in {"shell", "python", "validator"}:
            raise VerificationError("invalid verification command kind: " + name)
        if not isinstance(argv, list) or not argv or len(argv) > 64:
            raise VerificationError("invalid verification command argv: " + name)
        if not all(isinstance(value, str) and value and "\0" not in value for value in argv):
            raise VerificationError("invalid verification command argv: " + name)
        names.add(name)
        kinds.append(kind)
        normalized.append({"name": name, "kind": kind, "argv": list(argv)})
    if kinds.count("shell") != 1 or kinds.count("python") != 1:
        raise VerificationError("verification requires exactly one shell and one Python gate")
    return normalized


def child_environments(state, commands, workers):
    path = os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    home = state.child("home", create=True, private=True)
    home.close()
    for name in ("tmp", "xdg-cache", "xdg-config", "xdg-data"):
        directory = state.child(name, create=True, private=True)
        directory.close()
    temporary_root = state.child("tmp")
    try:
        environments = {}
        for command in commands:
            remove_entry(temporary_root, command["name"])
            temporary = temporary_root.child(command["name"], create=True, private=True)
            temporary.close()
            environment = {
                "PATH": path,
                "HOME": "../../home",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "TMPDIR": "../../tmp/" + command["name"],
                "XDG_CACHE_HOME": "../../xdg-cache",
                "XDG_CONFIG_HOME": "../../xdg-config",
                "XDG_DATA_HOME": "../../xdg-data",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            if command["kind"] == "shell":
                environment["REVIEW_COUNCIL_TEST_WORKERS"] = str(workers)
            environments[command["name"]] = environment
        return environments
    finally:
        temporary_root.close()


def executable_identity(executable, path, root):
    local = not Path(executable).is_absolute() and os.sep in executable
    if local and isinstance(root, OpenDirectory):
        try:
            descriptor, metadata = open_regular_path(root, executable, require_single_link=False)
        except (OSError, VerificationError) as error:
            raise VerificationError("verification tool is unavailable: " + executable) from error
        try:
            if not metadata.st_mode & 0o111:
                raise VerificationError("verification tool is not executable: " + executable)
            raw = read_descriptor(descriptor)
        finally:
            os.close(descriptor)
        target = root.path / executable
        return target, {"path": str(target), "size": len(raw), "sha256": digest(raw)}, True
    resolved = root / executable if local else shutil.which(executable, path=path)
    if resolved is None:
        raise VerificationError("verification tool is unavailable: " + executable)
    target = Path(resolved).resolve()
    metadata = safe_regular(target, require_single_link=False)
    if metadata is None or not metadata.st_mode & 0o111:
        raise VerificationError("verification tool is not executable: " + executable)
    raw = target.read_bytes()
    return target, {"path": str(target), "size": len(raw), "sha256": digest(raw)}, local


def tool_versions(commands, environment, root, supplemental=()):
    result = {}
    executables = [command["argv"][0] for command in commands]
    executables.extend(supplemental)
    for executable in executables:
        if executable in result:
            continue
        target, binary, local = executable_identity(executable, environment["PATH"], root)
        if local:
            version = "content-sha256:" + binary["sha256"]
        else:
            try:
                arguments = [str(target), "--version"]
                if isinstance(root, OpenDirectory):
                    probe = run_in_directory(
                        root, arguments, env=environment, capture_output=True,
                        text=True, timeout=10,
                    )
                else:
                    probe = subprocess.run(
                        arguments, env=environment, capture_output=True,
                        text=True, timeout=10,
                    )
            except (OSError, subprocess.SubprocessError) as error:
                raise VerificationError("cannot read tool version: " + executable) from error
            output = (probe.stdout + "\n" + probe.stderr).strip().splitlines()
            if probe.returncode != 0 or not output:
                raise VerificationError("cannot read tool version: " + executable)
            version = output[0][:1024]
        result[executable] = {"binary": binary, "version": version}
    return result


def read_receipt_candidate(state, name):
    try:
        descriptor, metadata = open_regular_path(state, name)
    except (OSError, VerificationError):
        return None
    try:
        if metadata.st_size > 4 * 1024 * 1024:
            return None
        value = json.loads(read_descriptor(descriptor))
    except (UnicodeError, json.JSONDecodeError):
        return None
    finally:
        os.close(descriptor)
    return value if isinstance(value, dict) else None


def log_identity(logs, name):
    try:
        descriptor, metadata = open_regular_path(logs, name)
    except (OSError, VerificationError) as error:
        raise VerificationError("verification log is missing or nonregular: " + name) from error
    try:
        if metadata.st_size <= 0:
            raise VerificationError("verification log is missing or nonregular: " + name)
        raw = read_descriptor(descriptor)
    finally:
        os.close(descriptor)
    lines = raw.splitlines()
    if not lines:
        raise VerificationError("verification log is truncated: " + name)
    try:
        footer = json.loads(lines[-1])
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VerificationError("verification log is truncated: " + name) from error
    if (not isinstance(footer, dict)
            or footer.get("review_council_log_complete") is not True
            or not isinstance(footer.get("exit_code"), int)):
        raise VerificationError("verification log is truncated: " + name)
    return {
        "path": str(logs.path / name), "size": len(raw), "sha256": digest(raw),
    }, footer["exit_code"]


def receipt_reusable(receipt, identity, key, logs_dir):
    if not isinstance(receipt, dict) or set(receipt) != {"schema_version", "key", "identity", "logs"}:
        return False
    if receipt.get("schema_version") != 1 or receipt.get("key") != key or receipt.get("identity") != identity:
        return False
    logs = receipt.get("logs")
    if not isinstance(logs, dict):
        return False
    command_names = {row["name"] for row in identity["commands"]}
    if set(logs) != command_names:
        return False
    try:
        for name, expected in logs.items():
            if not isinstance(expected, dict) or set(expected) != {"path", "size", "sha256"}:
                return False
            if expected["path"] != str(logs_dir.path / (name + ".log")):
                return False
            actual, exit_code = log_identity(logs_dir, name + ".log")
            if actual != expected or exit_code != 0:
                return False
    except (OSError, TypeError, VerificationError):
        return False
    return True


def prepare_log(logs, name, command, environment):
    safe_unlink(logs, name)
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600, dir_fd=logs.descriptor,
    )
    output = os.fdopen(descriptor, "wb", buffering=0)
    header = {"command": command, "environment": environment}
    output.write(encoded(header) + b"\n")
    return output


def process_group_exists(group):
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    return True


def terminate_remaining_group(group, grace=1.0):
    if not process_group_exists(group):
        return True
    for process_signal in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, process_signal)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not process_group_exists(group):
                return True
            time.sleep(0.02)
    return not process_group_exists(group)


def terminate_processes(processes, grace=1.0):
    processes = list(processes)
    groups = sorted({process.pid for process in processes})
    for process_signal in (signal.SIGTERM, signal.SIGKILL):
        for group in groups:
            try:
                os.killpg(group, process_signal)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            for process in processes:
                process.poll()
            if not any(process_group_exists(group) for group in groups):
                return
            time.sleep(0.02)


def register_process(process):
    with ACTIVE_LOCK:
        if CANCEL_REQUESTED.is_set():
            return False
        ACTIVE_PROCESSES[process.pid] = process
        return True


def unregister_process(process):
    with ACTIVE_LOCK:
        ACTIVE_PROCESSES.pop(process.pid, None)


def stop_active_processes():
    with ACTIVE_LOCK:
        processes = list(ACTIVE_PROCESSES.values())
    terminate_processes(processes)


def cancel_verification(signum, _frame):
    global SIGNAL_CANCELLATION
    if SIGNAL_CANCELLATION:
        return
    SIGNAL_CANCELLATION = signum
    raise VerificationCancelled


def install_signal_handlers():
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, cancel_verification)
    return previous


def restore_signal_handlers(previous):
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def run_command(command, environment, root, logs, timeout):
    output = prepare_log(logs, command["name"] + ".log", command, environment)
    process = None
    return_code = 125
    try:
        if CANCEL_REQUESTED.is_set():
            return_code = 130
        else:
            process = subprocess.Popen(
                [sys.executable, "-c", DIRECTORY_EXEC, str(root.descriptor), *command["argv"]],
                env=environment, pass_fds=(root.descriptor,),
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            )
            registered = register_process(process)
            if not registered:
                terminate_processes([process])
                return_code = 130
            else:
                try:
                    return_code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=3)
                    terminate_remaining_group(process.pid)
                    return_code = 124
                if process_group_exists(process.pid):
                    terminate_remaining_group(process.pid)
                    if return_code == 0:
                        return_code = 125
    except OSError as error:
        output.write(("launch failed: " + str(error) + "\n").encode(errors="replace"))
        return_code = 126
    finally:
        if process is not None:
            unregister_process(process)
        output.write(encoded({"review_council_log_complete": True, "exit_code": return_code}) + b"\n")
        output.flush()
        os.fsync(output.fileno())
        output.close()
    return command["name"], return_code


def shell_tallies(logs, name):
    inventory = None
    passed = None
    failed = None
    descriptor, _ = open_regular_path(logs, name)
    try:
        raw = read_descriptor(descriptor).decode(errors="replace")
    finally:
        os.close(descriptor)
    for line in raw.splitlines():
        if line.startswith("inventory_total="):
            try:
                inventory = int(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("tasks_passed="):
            match = re.fullmatch(r"tasks_passed=([0-9]+) tasks_failed=([0-9]+)", line)
            if match:
                passed, failed = map(int, match.groups())
    if inventory is None or passed is None or failed is None or inventory != passed + failed or failed != 0:
        raise VerificationError("shell result tally does not match inventory")


def state_directory(root, override):
    base = override if override is not None else Path(
        os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    )
    root_key = digest(str(root).encode())[:24]
    raw = (base / "review-council" / "verification" / root_key).expanduser()
    return Path(os.path.abspath(raw))


def open_private_lock(state, name):
    flags = os.O_RDWR | os.O_CREAT
    flags |= NOFOLLOW
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=state.descriptor)
    except OSError as error:
        raise VerificationError("verification lock is not a private regular file") from error
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise VerificationError("verification lock is not a private regular file")
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "a+b")


def verify(args):
    root_path = args.root.expanduser().resolve()
    root = open_source_root(root_path)
    state = None
    material_root = None
    logs_dir = None
    lock = None
    lock_acquired = False
    try:
        state = open_state_root(root, state_directory(root_path, args.cache_dir))
        receipt_path = state.path / "receipt.json"
        commands = read_commands(args.commands)
        lock = open_private_lock(state, "lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        lock_acquired = True
        inherited = [name for name in SELECTOR_ENV if os.environ.get(name)]
        if inherited:
            safe_unlink(state, "receipt.json")
            raise VerificationError("inherited scheduler selector: " + inherited[0])
        candidate = read_receipt_candidate(state, "receipt.json")
        records, contents = capture_stable_source(root)
        material_root, tree_key, expected_material = materialize(state, records, contents)
        environments = child_environments(state, commands, args.shell_workers)
        logs_dir = state.child("logs", create=True, private=True)
        common_environment = next(iter(environments.values())).copy()
        common_environment.pop("TMPDIR", None)
        common_environment.pop("REVIEW_COUNCIL_TEST_WORKERS", None)
        supplemental = DEFAULT_INDIRECT_TOOLS if args.commands is None else ()
        tools = tool_versions(commands, common_environment, material_root, supplemental=supplemental)
        identity = build_identity(tree_key, commands, environments, platform_identity(), tools)
        key = identity_key(identity)
        if receipt_reusable(candidate, identity, key, logs_dir):
            print("reused verification receipt: " + str(receipt_path))
            return receipt_path
        safe_unlink(state, "receipt.json")
        results = {}
        with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
            try:
                futures = {
                    pool.submit(
                        run_command, command, environments[command["name"]], material_root,
                        logs_dir, args.timeout,
                    ): command
                    for command in commands
                }
                for future in as_completed(futures):
                    name, return_code = future.result()
                    results[name] = return_code
            except VerificationCancelled:
                CANCEL_REQUESTED.set()
                safe_unlink(state, "receipt.json")
                stop_active_processes()
                raise
        failures = [name for name in sorted(results) if results[name] != 0]
        if len(results) != len(commands):
            raise VerificationError("verification command result set is incomplete")
        if failures:
            raise VerificationError("verification command failed: " + ", ".join(failures))
        shell = next(command for command in commands if command["kind"] == "shell")
        shell_tallies(logs_dir, shell["name"] + ".log")
        if inspect_material(material_root) != expected_material:
            raise VerificationError("materialized tree changed during verification")
        logs = {}
        for command in commands:
            log, return_code = log_identity(logs_dir, command["name"] + ".log")
            if return_code != 0:
                raise VerificationError("verification log records failure: " + command["name"])
            logs[command["name"]] = log
        receipt = {"schema_version": 1, "key": key, "identity": identity, "logs": logs}
        atomic_write(state, "receipt.json", encoded(receipt) + b"\n")
        print("verification receipt: " + str(receipt_path))
        return receipt_path
    except Exception:
        if lock_acquired and state is not None:
            safe_unlink(state, "receipt.json")
        raise
    finally:
        if lock is not None:
            lock.close()
        if logs_dir is not None:
            logs_dir.close()
        if material_root is not None:
            material_root.close()
        if state is not None:
            state.close()
        root.close()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=REPO)
    result.add_argument("--cache-dir", type=Path)
    result.add_argument("--commands", type=Path)
    result.add_argument("--max-workers", type=int, choices=range(1, 5), default=4)
    result.add_argument("--shell-workers", type=int, choices=range(1, 5), default=4)
    result.add_argument("--timeout", type=int, default=1800)
    return result


def main(argv=None):
    global SIGNAL_CANCELLATION
    args = parser().parse_args(argv)
    if not isinstance(args.timeout, int) or args.timeout < 1 or args.timeout > 7200:
        print("verify-review-council: timeout must be between 1 and 7200 seconds", file=sys.stderr)
        return 2
    CANCEL_REQUESTED.clear()
    SIGNAL_CANCELLATION = 0
    previous_handlers = install_signal_handlers()
    try:
        try:
            verify(args)
        except VerificationCancelled:
            print(
                "verify-review-council: cancelled by signal " + str(SIGNAL_CANCELLATION),
                file=sys.stderr,
            )
            return 1
        except (OSError, ValueError, VerificationError, subprocess.SubprocessError) as error:
            print("verify-review-council: " + str(error), file=sys.stderr)
            return 1
        return 0
    finally:
        restore_signal_handlers(previous_handlers)
        CANCEL_REQUESTED.set()
        stop_active_processes()


if __name__ == "__main__":
    sys.exit(main())
