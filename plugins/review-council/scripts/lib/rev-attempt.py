#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

TERMINAL_EXITS = ('1', '2')


def safe_regular(path):
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return not path.is_symlink() and stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def hard_audit_failure(audit: Path) -> bool:
    if not safe_regular(audit) or audit.stat().st_size == 0:
        return False
    try:
        result = json.loads(audit.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return (result.get('schema_version') == 2 and result.get('status') == 'invalid'
            and result.get('evidence_scoped') is True)


def latched(session: Path, panel: str, seat: str) -> bool:
    """A hard audit failure latches only its own (label, seat); siblings and later labels launch."""
    invalid = session / f'r{panel}-{seat}.audit-invalid.json'
    return ((safe_regular(invalid) and invalid.stat().st_size > 0)
            or hard_audit_failure(session / f'r{panel}-{seat}.read-audit.json'))


def record_path(session: Path, panel: str, seat: str, prompt: Path):
    identity = {'panel': panel, 'seat': seat,
                'prompt_sha256': hashlib.sha256(prompt.resolve().read_bytes()).hexdigest()}
    return session / 'attempts' / (hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest() + '.json'), identity


def terminal_failure(session: Path, panel: str, seat: str, prompt: Path) -> bool:
    """The assignment failed for good: a hard audit, or its one exact retry also exited 1 or 2."""
    if latched(session, panel, seat):
        return True
    exit_path = session / f'r{panel}-{seat}.exit'
    try:
        path, _ = record_path(session, panel, seat, prompt)
        launches = json.loads(path.read_text(encoding='utf-8')).get('launches') if safe_regular(path) else None
        final = exit_path.read_text(encoding='utf-8').strip() if safe_regular(exit_path) else None
    except (OSError, ValueError):
        return False
    return (isinstance(launches, list) and len(launches) >= 2
            and all(str(code) in TERMINAL_EXITS for code in launches[-2:]) and final in TERMINAL_EXITS)


def open_private(path):
    flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        descriptor = os.open(path, flags)
        created = False
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise ValueError('attempt state is not a private regular file')
    return descriptor, created


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else None
    if (command, len(sys.argv)) not in (('reserve', 6), ('record', 7)):
        return 1
    session = Path(sys.argv[2]).resolve()
    panel, seat = sys.argv[3], sys.argv[4]
    safe = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-')
    if not panel or not seat or not set(panel) <= safe or not set(seat) <= safe:
        return 1
    directory = session / 'attempts'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode) \
            or directory.resolve().parent != session:
        return 1
    panel_key = hashlib.sha256(panel.encode()).hexdigest()
    try:
        panel_descriptor, _ = open_private(directory / ('.panel-' + panel_key + '.lock'))
    except (OSError, ValueError):
        return 1
    with os.fdopen(panel_descriptor, 'r+', encoding='utf-8') as panel_lock:
        fcntl.flock(panel_lock, fcntl.LOCK_EX)
        if command == 'reserve' and latched(session, panel, seat):
            print(f'{seat} under label {panel} failed a hard evidence audit; replace the assignment '
                  'on another eligible seat, never relaunch it', file=sys.stderr)
            return 2
        path, identity = record_path(session, panel, seat, Path(sys.argv[5]))
        if command == 'record' and not path.exists():
            return 1
        try:
            descriptor, created = open_private(path)
        except (OSError, ValueError):
            return 1
        with os.fdopen(descriptor, 'r+', encoding='utf-8') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            try:
                current = json.load(stream)
            except (json.JSONDecodeError, ValueError):
                if not created or command == 'record':
                    return 1
                current = dict(identity, calls=0)
            if any(current.get(field) != value for field, value in identity.items()):
                return 1
            calls = current.get('calls')
            if type(calls) is not int or calls < 0:
                return 1
            if command == 'record':
                if sys.argv[6] not in ('0', '1', '2', '3', '4', '7'):
                    return 1
                current['launches'] = [*current.get('launches', []), int(sys.argv[6])]
            elif calls >= 4:
                return 7
            else:
                current['calls'] = calls + 1
            stream.seek(0)
            stream.truncate()
            json.dump(current, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        return 0


if __name__ == '__main__':
    sys.exit(main())
