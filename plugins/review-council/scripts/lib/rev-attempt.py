#!/usr/bin/env python3
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def main():
    if len(sys.argv) != 6 or sys.argv[1] != 'reserve':
        return 1
    session = Path(sys.argv[2]).resolve()
    identity = {
        'panel': sys.argv[3],
        'seat': sys.argv[4],
        'prompt_sha256': hashlib.sha256(Path(sys.argv[5]).resolve().read_bytes()).hexdigest(),
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = session / 'attempts'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode) \
            or directory.resolve().parent != session:
        return 1
    path = directory / (key + '.json')
    flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    created = False
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return 1
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
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
