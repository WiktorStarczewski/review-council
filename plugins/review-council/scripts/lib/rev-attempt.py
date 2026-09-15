#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

SESSION_STOP = "session.stopped.json"
STOP_MESSAGE = "review session stopped after a hard evidence audit failure; preserve this session and start a fresh review session"


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


def session_stop_path(session: Path) -> Path:
    return session / "attempts" / SESSION_STOP


def prior_hard_audit(session: Path) -> Path | None:
    marker = session_stop_path(session)
    if marker.exists() or marker.is_symlink():
        return marker
    for audit in sorted(session.glob("r*-*.audit.json")):
        if hard_audit_failure(audit):
            return audit
    return None


def stop_notice(path: Path) -> str:
    if path.name != SESSION_STOP or not safe_regular(path):
        return STOP_MESSAGE
    try:
        reason = json.loads(path.read_text(encoding='utf-8')).get('reason')
    except (OSError, json.JSONDecodeError, ValueError):
        reason = None
    return f'{reason}; {STOP_MESSAGE}' if isinstance(reason, str) and reason else STOP_MESSAGE


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


def write_immutable(path, raw):
    try:
        descriptor, created = open_private(path)
    except (OSError, ValueError):
        return False
    with os.fdopen(descriptor, 'r+', encoding='utf-8') as stream:
        if created:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            return True
        stream.seek(0)
        return stream.read() == raw


def main():
    if sys.argv[1:2] not in (['check'], ['reserve'], ['stop']):
        return 1
    command = sys.argv[1]
    if command == 'reserve' and len(sys.argv) != 6:
        return 1
    if command == 'check' and len(sys.argv) != 4:
        return 1
    if command == 'stop' and len(sys.argv) not in (4, 6):
        return 1
    if command == 'stop' and len(sys.argv) == 6 and sys.argv[4] != '--reason':
        return 1
    session = Path(sys.argv[2]).resolve()
    panel = sys.argv[3]
    if not panel or any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'
                        for character in panel):
        return 1
    reason = sys.argv[5] if command == 'stop' and len(sys.argv) == 6 else 'hard evidence audit failed'
    directory = session / 'attempts'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode) \
            or directory.resolve().parent != session:
        return 1
    try:
        session_descriptor, _ = open_private(directory / '.session.lock')
    except (OSError, ValueError):
        return 1
    with os.fdopen(session_descriptor, 'r+', encoding='utf-8') as session_lock:
        fcntl.flock(session_lock, fcntl.LOCK_EX)
        panel_key = hashlib.sha256(panel.encode()).hexdigest()
        try:
            panel_descriptor, _ = open_private(directory / ('.panel-' + panel_key + '.lock'))
        except (OSError, ValueError):
            return 1
        with os.fdopen(panel_descriptor, 'r+', encoding='utf-8') as panel_lock:
            fcntl.flock(panel_lock, fcntl.LOCK_EX)
            stopped = directory / ('panel-' + panel_key + '.stopped.json')
            if command == 'stop':
                raw = json.dumps({'panel': panel, 'stopped': True}, sort_keys=True,
                                 separators=(',', ':')) + '\n'
                session_raw = json.dumps({'panel': panel, 'reason': reason, 'stopped': True},
                                         sort_keys=True, separators=(',', ':')) + '\n'
                return 0 if write_immutable(stopped, raw) and write_immutable(session_stop_path(session), session_raw) else 1
            prior = prior_hard_audit(session)
            if prior is not None:
                print(stop_notice(prior), file=sys.stderr)
                return 2
            if command == 'check':
                return 0
            identity = {
                'panel': panel,
                'seat': sys.argv[4],
                'prompt_sha256': hashlib.sha256(Path(sys.argv[5]).resolve().read_bytes()).hexdigest(),
            }
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            path = directory / (key + '.json')
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
                    if not created:
                        return 1
                    current = dict(identity, calls=0)
                if any(current.get(field) != value for field, value in identity.items()):
                    return 1
                calls = current.get('calls')
                if type(calls) is not int or calls < 0:
                    return 1
                if calls >= 4:
                    return 7
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
