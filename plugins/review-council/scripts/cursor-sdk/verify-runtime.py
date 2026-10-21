#!/usr/bin/env python3
"""Verify a private optional runtime against locked published archive bytes."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import sys
import tarfile

HERE = Path(__file__).absolute().parent
PACKAGE_LIMIT = 256 * 1024 * 1024
TOTAL_LIMIT = 1024 * 1024 * 1024
MAX_MEMBERS = 10000


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class Inputs:
    def __init__(self):
        self.files = {}
        self.directories = {}

    def read(self, path, limit=PACKAGE_LIMIT):
        path = Path(os.path.abspath(path))
        directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        parents = Path('/')
        try:
            for name in path.parts[1:-1]:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
                metadata = os.fstat(child)
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
                    os.close(child)
                    raise ValueError()
                parents = parents / name
                captured = (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid)
                if self.directories.setdefault(parents, captured) != captured:
                    os.close(child)
                    raise ValueError()
                os.close(directory)
                directory = child
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
            try:
                before = os.fstat(descriptor)
                current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or before.st_size > limit or identity(before) != identity(current)):
                    raise ValueError()
                with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                    raw = stream.read(limit + 1)
                after = os.fstat(descriptor)
                current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                if (len(raw) != before.st_size or len(raw) > limit
                        or identity(before) != identity(after)
                        or identity(before) != identity(current)):
                    raise ValueError()
                known = self.files.setdefault(path, identity(before))
                if known != identity(before):
                    raise ValueError()
                return raw, before
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)

    def stable(self):
        for path, expected in self.directories.items():
            current = path.lstat()
            if (current.st_dev, current.st_ino, current.st_mode, current.st_uid) != expected:
                raise ValueError()
        for path, expected in self.files.items():
            if identity(path.lstat()) != expected:
                raise ValueError()


def installed_files(root):
    result = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        if 'node_modules' in directories:
            directories.remove('node_modules')
        if any((Path(directory) / name).is_symlink() for name in directories):
            raise ValueError()
        result.update((Path(directory) / name).relative_to(root).as_posix() for name in files)
    return result


def runtime_inventory(runtime, allowed_files, allowed_directories):
    files = set()
    for directory, directories, names in os.walk(runtime, followlinks=False):
        for name in directories:
            path = Path(directory) / name
            if path.is_symlink() or path.relative_to(runtime).as_posix() not in allowed_directories:
                raise ValueError()
        files.update((Path(directory) / name).relative_to(runtime).as_posix() for name in names)
    if files != allowed_files:
        raise ValueError()


def verify(runtime):
    runtime = Path(os.path.abspath(runtime))
    info = runtime.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError()
    inputs = Inputs()
    material = []
    allowed_files = {'package.json', 'package-lock.json', 'launch.mjs'}
    allowed_directories = {'.archives', 'node_modules'}
    for name in ('package.json', 'package-lock.json', 'launch.mjs'):
        raw, _ = inputs.read(runtime / name)
        controller, _ = inputs.read(HERE / name)
        if raw != controller:
            raise ValueError()
        material.append((name, hashlib.sha256(raw).hexdigest()))
    lock = json.loads(inputs.read(HERE / 'package-lock.json')[0])
    system = {'Darwin': 'darwin', 'Linux': 'linux'}.get(platform.system())
    architecture = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'AMD64': 'x64'}.get(platform.machine())
    helper = f'@cursor/sdk-{system}-{architecture}'
    sdk_entry = lock['packages']['node_modules/@cursor/sdk']
    if (not system or not architecture or sdk_entry['version'] != '1.0.38'
            or sdk_entry['optionalDependencies'].get(helper) != '1.0.38'):
        raise ValueError()
    total = 0
    inventories = []
    installed = []
    for location, package in sorted(lock['packages'].items()):
        if not location:
            continue
        if package.get('os') and system not in package['os']:
            continue
        if package.get('cpu') and architecture not in package['cpu']:
            continue
        if location == 'node_modules/' + helper and package.get('version') != '1.0.38':
            raise ValueError()
        parts = PurePosixPath(location).parts
        if (not location.startswith('node_modules/') or '..' in parts
                or str(PurePosixPath(location)) != location):
            raise ValueError()
        integrity = package['integrity']
        algorithm, encoded = integrity.split('-', 1)
        if algorithm != 'sha512':
            raise ValueError()
        archive = runtime / '.archives' / (hashlib.sha256(integrity.encode()).hexdigest() + '.tgz')
        allowed_files.add(archive.relative_to(runtime).as_posix())
        archive_raw, _ = inputs.read(archive)
        if hashlib.sha512(archive_raw).digest() != base64.b64decode(encoded, validate=True):
            raise ValueError()
        expected = set()
        count = package_size = 0
        with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as stream:
            names = set()
            for member in stream:
                count += 1
                path = PurePosixPath(member.name)
                if (count > MAX_MEMBERS or member.name in names or path.is_absolute()
                        or '..' in path.parts or not path.parts or path.parts[0] != 'package'
                        or str(path) != member.name.rstrip('/') or member.issym() or member.islnk()):
                    raise ValueError()
                names.add(member.name)
                if member.isdir():
                    allowed_directories.add((Path(location) / Path(*path.parts[1:])).as_posix())
                    continue
                if not member.isfile() or len(path.parts) < 2 or member.size > PACKAGE_LIMIT:
                    raise ValueError()
                package_size += member.size
                total += member.size
                if package_size > PACKAGE_LIMIT or total > TOTAL_LIMIT:
                    raise ValueError()
                relative = Path(*path.parts[1:])
                expected.add(relative.as_posix())
                installed_path = Path(location) / relative
                allowed_files.add(installed_path.as_posix())
                allowed_directories.update(parent.as_posix() for parent in installed_path.parents
                                           if parent.as_posix() != '.')
                actual, metadata = inputs.read(runtime / location / relative)
                if (stat.S_IMODE(metadata.st_mode) & 0o111) != (member.mode & 0o111):
                    raise ValueError()
                published = stream.extractfile(member).read(PACKAGE_LIMIT + 1)
                if len(published) != member.size or actual != published:
                    raise ValueError()
                material.append((location + '/' + relative.as_posix(),
                                 hashlib.sha256(actual).hexdigest(), member.mode & 0o111))
        package_root = runtime / location
        if installed_files(package_root) != expected:
            raise ValueError()
        inventories.append((package_root, expected))
        installed.append(location)
    if 'node_modules/' + helper not in installed:
        raise ValueError()
    retained = list((runtime / '.archives').iterdir())
    if len(retained) > 64:
        raise ValueError()
    for path in retained:
        if not re.fullmatch(r'[0-9a-f]{64}\.tgz', path.name):
            raise ValueError()
        if path.relative_to(runtime).as_posix() not in allowed_files:
            inputs.read(path)
            allowed_files.add(path.relative_to(runtime).as_posix())
    npm_lock = runtime / 'node_modules/.package-lock.json'
    if npm_lock.exists():
        inputs.read(npm_lock)
        allowed_files.add('node_modules/.package-lock.json')
    receipt_key = runtime / '.qualification-key'
    if receipt_key.exists():
        raw, key_info = inputs.read(receipt_key, 32)
        if len(raw) != 32 or key_info.st_uid != os.geteuid() or stat.S_IMODE(key_info.st_mode) != 0o600:
            raise ValueError()
        allowed_files.add('.qualification-key')
    source = HERE.parent
    controllers = sorted((source / 'lib').glob('*.py')) + [
        source / 'lib/cursor-sdk-driver.mjs', source / 'lib/cursor-sdk-reader.mjs',
        source / 'rev-evidence.py', source / 'rev-prompt.sh',
        source / 'seats.d/cursor-sdk.sh', HERE / 'verify-runtime.py', HERE / 'install.py',
        HERE / 'launch.mjs', HERE / 'package.json', HERE / 'package-lock.json']
    for path in controllers:
        raw, _ = inputs.read(path)
        material.append(('controller/' + str(path.relative_to(source)), hashlib.sha256(raw).hexdigest()))
    for package_root, expected in inventories:
        if installed_files(package_root) != expected:
            raise ValueError()
    runtime_inventory(runtime, allowed_files, allowed_directories)
    inputs.stable()
    digest = hashlib.sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()
    return {'version': 1, 'sdk_version': '1.0.38', 'runtime_sha256': digest,
            'platform': system, 'arch': architecture, 'helper': helper}


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError()
        print(json.dumps(verify(sys.argv[1]), separators=(',', ':')))
    except Exception:
        print('runtime_invalid', file=sys.stderr)
        sys.exit(5)
