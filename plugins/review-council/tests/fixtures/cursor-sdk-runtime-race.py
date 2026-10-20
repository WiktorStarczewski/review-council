"""Synthetic same-process filesystem races around the unchanged verifier."""

import builtins
import hashlib
import os
from pathlib import Path
import runpy
import sys


verifier, runtime, mode, target_name, replacement_name, installed_name, marker_name = sys.argv[1:]
target = Path(target_name)
replacement = Path(replacement_name)
installed = Path(installed_name)
marker = Path(marker_name)
original_bytes = target.read_bytes()
original_identity = (target.stat().st_dev, target.stat().st_ino)
original_sha512 = hashlib.sha512
original_hash_new = hashlib.new
original_open = builtins.open
original_os_open = os.open
swapped = False


def swap():
    global swapped
    if swapped:
        return
    swapped = True
    os.replace(replacement, target)
    if mode == 'archive':
        installed.write_bytes(b'unauthenticated replacement\n')
    marker.write_text('swapped\n')


class WatchedDigest:
    def __init__(self, data=b'', **kwargs):
        self.inner = original_sha512(data, **kwargs)
        self.seen = bytearray(data)

    def update(self, data):
        self.seen.extend(data)
        return self.inner.update(data)

    def digest(self):
        result = self.inner.digest()
        if bytes(self.seen) == original_bytes:
            swap()
        return result

    def hexdigest(self):
        result = self.inner.hexdigest()
        if bytes(self.seen) == original_bytes:
            swap()
        return result

    def copy(self):
        result = object.__new__(WatchedDigest)
        result.inner = self.inner.copy()
        result.seen = self.seen.copy()
        return result

    def __getattr__(self, name):
        return getattr(self.inner, name)


def watched_open(file, *args, **kwargs):
    result = original_open(file, *args, **kwargs)
    if isinstance(file, (str, bytes, os.PathLike)) and Path(file) == target:
        swap()
    return result


def watched_os_open(file, *args, **kwargs):
    result = original_os_open(file, *args, **kwargs)
    metadata = os.fstat(result)
    if (metadata.st_dev, metadata.st_ino) == original_identity:
        swap()
    return result


if mode == 'archive':
    hashlib.sha512 = WatchedDigest

    def watched_hash_new(name, data=b'', **kwargs):
        if name.lower().replace('-', '') == 'sha512':
            return WatchedDigest(data, **kwargs)
        return original_hash_new(name, data, **kwargs)

    hashlib.new = watched_hash_new
else:
    builtins.open = watched_open
    io_open = __import__('io').open

    def watched_io_open(file, *args, **kwargs):
        result = io_open(file, *args, **kwargs)
        if isinstance(file, (str, bytes, os.PathLike)) and Path(file) == target:
            swap()
        return result

    __import__('io').open = watched_io_open
    os.open = watched_os_open
sys.argv = [verifier, runtime]
runpy.run_path(verifier, run_name='__main__')
