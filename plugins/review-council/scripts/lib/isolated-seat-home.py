#!/usr/bin/env python3
"""Create and lease a private, deterministic temporary home for one seat."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import tempfile
import time


def seat_path(kind, identity):
    key = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / f'review-council-{kind}-{os.getuid()}-{key}'


def validate_path(path, kind):
    prefix = f'review-council-{kind}-{os.getuid()}-'
    if path.parent.resolve() != Path(tempfile.gettempdir()).resolve() or not path.name.startswith(prefix):
        raise ValueError('refusing to use an unexpected seat home')


def lease_path(kind):
    return Path(tempfile.gettempdir()) / f'.review-council-{kind}-{os.getuid()}.leases'


def lease_offset(path):
    digest = hashlib.sha256(path.name.encode()).digest()
    return int.from_bytes(digest[:8], 'big') & ((1 << 63) - 1)


def acquire_lease(path, kind, blocking):
    validate_path(path, kind)
    lock_path = lease_path(kind)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        details = os.fstat(descriptor)
        current = lock_path.lstat()
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
                or (details.st_dev, details.st_ino) != (current.st_dev, current.st_ino)):
            raise ValueError('refusing to use an unsafe seat lease')
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.lockf(descriptor, operation, 1, lease_offset(path), os.SEEK_SET)
        except BlockingIOError:
            os.close(descriptor)
            return None
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def safe_remove(path, kind):
    validate_path(path, kind)
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode) or details.st_uid != os.getuid():
        raise ValueError('refusing to clean an unsafe seat home')
    shutil.rmtree(path)


def create_home(path, kind, auth):
    safe_remove(path, kind)
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    if kind == 'codex' and auth:
        auth_path = Path(auth).resolve(strict=True)
        if not auth_path.is_file():
            raise ValueError('Codex auth path is not a file')
        (path / 'auth.json').symlink_to(auth_path)


def sweep(kind, exclude=None):
    prefix = f'review-council-{kind}-{os.getuid()}-'
    for path in Path(tempfile.gettempdir()).iterdir():
        if not path.name.startswith(prefix) or path == exclude:
            continue
        try:
            details = path.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode)
                or details.st_uid != os.getuid()):
            continue
        descriptor = acquire_lease(path, kind, blocking=False)
        if descriptor is None:
            continue
        try:
            try:
                safe_remove(path, kind)
            except ValueError:
                pass
        finally:
            os.close(descriptor)


def process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def hold(path, kind, auth, parent):
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    sweep(kind, exclude=path)
    descriptor = None
    while descriptor is None and not stopped and process_exists(parent):
        descriptor = acquire_lease(path, kind, blocking=False)
        if descriptor is None:
            time.sleep(0.05)
    if descriptor is None:
        return 0
    if stopped or not process_exists(parent):
        os.close(descriptor)
        return 0
    try:
        create_home(path, kind, auth)
        print(path, flush=True)
        while not stopped and process_exists(parent):
            time.sleep(0.05)
        safe_remove(path, kind)
        return 0
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    path_command = commands.add_parser('path')
    path_command.add_argument('kind', choices=('codex', 'grok'))
    path_command.add_argument('identity')
    create = commands.add_parser('create')
    create.add_argument('kind', choices=('codex', 'grok'))
    create.add_argument('identity')
    create.add_argument('--auth')
    hold_command = commands.add_parser('hold')
    hold_command.add_argument('kind', choices=('codex', 'grok'))
    hold_command.add_argument('path')
    hold_command.add_argument('--auth')
    hold_command.add_argument('--parent', type=int, required=True)
    clean = commands.add_parser('clean')
    clean.add_argument('kind', choices=('codex', 'grok'))
    clean.add_argument('path')
    sweep_command = commands.add_parser('sweep')
    sweep_command.add_argument('kind', choices=('codex', 'grok'))
    args = parser.parse_args()
    try:
        if args.command == 'path':
            print(seat_path(args.kind, args.identity))
            return 0
        if args.command == 'hold':
            return hold(Path(args.path), args.kind, args.auth, args.parent)
        if args.command == 'sweep':
            sweep(args.kind)
            return 0
        if args.command == 'clean':
            path = Path(args.path)
            descriptor = acquire_lease(path, args.kind, blocking=False)
            if descriptor is None:
                raise ValueError('refusing to clean a leased seat home')
            try:
                safe_remove(path, args.kind)
            finally:
                os.close(descriptor)
            return 0
        path = seat_path(args.kind, args.identity)
        descriptor = acquire_lease(path, args.kind, blocking=True)
        try:
            create_home(path, args.kind, args.auth)
        finally:
            os.close(descriptor)
        print(path)
        return 0
    except (OSError, ValueError) as error:
        print('isolated-seat-home: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
