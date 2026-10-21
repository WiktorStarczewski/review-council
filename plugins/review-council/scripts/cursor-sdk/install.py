#!/usr/bin/env python3
"""Explicitly install the pinned optional runtime into a new private directory."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request

HERE = Path(__file__).resolve().parent


def install(destination):
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    archives = destination / '.archives'
    archives.mkdir(mode=0o700)
    for name in ('package.json', 'package-lock.json', 'launch.mjs'):
        shutil.copyfile(HERE / name, destination / name)
    lock = json.loads((HERE / 'package-lock.json').read_text())
    system = {'Darwin': 'darwin', 'Linux': 'linux', 'Windows': 'win32'}.get(platform.system())
    architecture = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'AMD64': 'x64'}.get(platform.machine())
    for location, package in lock['packages'].items():
        if not location:
            continue
        if package.get('os') and system not in package['os']:
            continue
        if package.get('cpu') and architecture not in package['cpu']:
            continue
        url = package['resolved']
        if not url.startswith('https://registry.npmjs.org/'):
            raise ValueError('registry_invalid')
        integrity = package['integrity']
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read(256 * 1024 * 1024 + 1)
        if (len(raw) > 256 * 1024 * 1024 or not integrity.startswith('sha512-')
                or hashlib.sha512(raw).digest() != base64.b64decode(integrity[7:], validate=True)):
            raise ValueError('archive_integrity')
        (archives / (hashlib.sha256(integrity.encode()).hexdigest() + '.tgz')).write_bytes(raw)
    subprocess.run(['npm', 'ci', '--ignore-scripts', '--no-bin-links', '--no-audit', '--no-fund'],
                   cwd=destination, check=True)
    subprocess.run([sys.executable, str(HERE / 'verify-runtime.py'), str(destination)], check=True)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('destination_required')
        install(Path(os.path.abspath(sys.argv[1])))
    except Exception:
        print('optional_runtime_install_failed', file=sys.stderr)
        sys.exit(1)
