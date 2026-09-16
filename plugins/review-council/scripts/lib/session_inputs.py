#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import fcntl
import fnmatch
import os
from pathlib import Path
import stat
import sys
import tempfile

STANDARD_INPUTS = ("scope.env", "roster.json", "files.txt", "untracked.txt")


class SessionInputsError(RuntimeError):
    pass


class SessionInputsSealedError(SessionInputsError):
    pass


def _directory(path: Path) -> Path:
    path = Path(path)
    try:
        details = path.lstat()
    except OSError as exc:
        raise SessionInputsError(f"session directory unavailable: {path}: {exc}") from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise SessionInputsError(f"session path is not a directory: {path}")
    if details.st_uid != os.getuid():
        raise SessionInputsError(f"session directory is not owned by the current user: {path}")
    return path


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _read_private_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SessionInputsError(f"cannot read staged input {path.name}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or opened.st_uid != os.getuid() or not _same_file(opened, current)):
            raise SessionInputsError(f"unsafe staged input: {path.name}")
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = -1
            return stream.read()
    except OSError as exc:
        raise SessionInputsError(f"cannot validate staged input {path.name}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def find_evidence_seal(session: Path) -> Path | None:
    session = _directory(session)
    try:
        entries = sorted(session.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise SessionInputsError(f"cannot inspect session directory: {session}: {exc}") from exc
    return next((entry for entry in entries
                 if fnmatch.fnmatchcase(entry.name, 'r*-evidence.manifest.json')), None)


@contextmanager
def session_input_lock(session: Path) -> Iterator[Path]:
    session = _directory(session)
    lock_path = session / '.session-inputs.lock'
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise SessionInputsError(f"cannot open session input lock: {exc}") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        opened = os.fstat(descriptor)
        current = lock_path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or opened.st_uid != os.getuid() or not _same_file(opened, current)):
            raise SessionInputsError('session input lock is not a safe regular file')
        yield lock_path
    except OSError as exc:
        raise SessionInputsError(f"cannot validate session input lock: {exc}") from exc
    finally:
        os.close(descriptor)


def assert_unsealed(session: Path) -> None:
    seal = find_evidence_seal(session)
    if seal is not None:
        raise SessionInputsSealedError(f"session inputs are sealed by {seal.name}")


def validate_standard_inputs(session: Path, require_all: bool) -> dict[str, bytes]:
    session = _directory(session)
    expected = set(STANDARD_INPUTS if require_all else ('roster.json',))
    present = set()
    for name in STANDARD_INPUTS:
        path = session / name
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SessionInputsError(f"cannot inspect staged input {name}: {exc}") from exc
        present.add(name)
    if present != expected:
        raise SessionInputsError(
            'staged inputs must contain exactly ' + ', '.join(sorted(expected)))
    return {name: _read_private_regular(session / name) for name in STANDARD_INPUTS
            if name in expected}


def _validate_values(values: Mapping[str, bytes], complete: bool) -> dict[str, bytes]:
    expected = set(STANDARD_INPUTS if complete else ('roster.json',))
    if not isinstance(values, Mapping) or set(values) != expected:
        raise SessionInputsError('input values must contain exactly ' + ', '.join(sorted(expected)))
    result = dict(values)
    if any(not isinstance(value, bytes) for value in result.values()):
        raise SessionInputsError('session input values must be bytes')
    return result


def _validate_legacy_target(path: Path) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise SessionInputsError(f"cannot inspect existing roster.json: {exc}") from exc
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1 or details.st_uid != os.getuid()):
        raise SessionInputsError('existing roster.json is not a safe regular file')


def _has_entry(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise SessionInputsError(f"cannot inspect session input {path.name}: {exc}") from exc


def install_inputs(session: Path, values: Mapping[str, bytes], complete: bool) -> None:
    values = _validate_values(values, complete)
    session = _directory(session)
    temporaries: dict[str, Path] = {}
    with session_input_lock(session):
        assert_unsealed(session)
        initialized = [name for name in STANDARD_INPUTS if _has_entry(session / name)]
        if complete:
            conflicting = [name for name in initialized
                           if _read_private_regular(session / name) != values[name]]
            if conflicting:
                raise SessionInputsError(
                    'session inputs conflict with the staged generation: '
                    + ', '.join(conflicting))
        if not complete:
            _validate_legacy_target(session / 'roster.json')
        try:
            for name, value in values.items():
                if complete and name in initialized:
                    continue
                descriptor, temporary = tempfile.mkstemp(
                    prefix=f'.{name}.', suffix='.tmp', dir=session)
                temporary_path = Path(temporary)
                temporaries[name] = temporary_path
                with os.fdopen(descriptor, 'wb') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
            for name in STANDARD_INPUTS:
                if name in temporaries:
                    os.replace(temporaries.pop(name), session / name)
            if complete:
                descriptor = os.open(session, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError as exc:
            raise SessionInputsError(f"cannot install session inputs: {exc}") from exc
        finally:
            for temporary in temporaries.values():
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 2 and argv[0] == 'check-unsealed':
            with session_input_lock(Path(argv[1])):
                assert_unsealed(Path(argv[1]))
            return 0
        if len(argv) == 3 and argv[0] == 'install':
            values = validate_standard_inputs(Path(argv[2]), require_all=True)
            install_inputs(Path(argv[1]), values, complete=True)
            return 0
        raise SessionInputsError(
            'usage: session_inputs.py check-unsealed SESSION | install SESSION STAGING_DIR')
    except SessionInputsError as exc:
        print(f'session inputs: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
