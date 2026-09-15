#!/usr/bin/env python3
"""Build a self-contained Codex bundle, without Claude skill/hook discovery."""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
AT_FDCWD = -100
RENAME_EXCHANGE = 0x00000002


def _atomic_exchange(left, right):
    libc = ctypes.CDLL(None, use_errno=True)
    left_bytes = os.fsencode(left)
    right_bytes = os.fsencode(right)
    if sys.platform == 'darwin':
        operation = libc.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(left_bytes, right_bytes, RENAME_EXCHANGE)
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        operation = libc.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p,
                              ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(AT_FDCWD, left_bytes, AT_FDCWD, right_bytes, RENAME_EXCHANGE)
    else:
        raise OSError(errno.ENOTSUP, 'atomic directory exchange is unavailable')
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(left), None, str(right))


def _make_staging_writable(root):
    for current, directories, files in os.walk(root, followlinks=False):
        paths = [Path(current)]
        paths.extend(Path(current) / name for name in directories + files)
        for path in paths:
            metadata = os.stat(path, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode):
                os.chmod(path, stat.S_IMODE(metadata.st_mode) | stat.S_IWUSR,
                         follow_symlinks=False)


def _stamp_cachebuster(stage, cachebuster):
    manifest = stage / '.codex-plugin/plugin.json'
    metadata = json.loads(manifest.read_text())
    version = metadata.get('version')
    if not isinstance(version, str) or not version:
        raise ValueError('Codex plugin manifest has no version')
    metadata['version'] = version.split('+', 1)[0] + '+codex.' + str(cachebuster)
    manifest.write_text(json.dumps(metadata, indent=2) + '\n')


def build(output, cachebuster=None):
    output = output.expanduser().absolute()
    if output.name != 'review-council':
        raise ValueError('output directory must be named review-council')
    if output.is_symlink():
        raise ValueError('refusing to replace a symlink')
    if output.exists():
        manifest = output / '.codex-plugin/plugin.json'
        if not manifest.is_file() or json.loads(manifest.read_text()).get('name') != output.name:
            raise ValueError('existing output is not a review-council Codex bundle')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.review-council-build-', dir=output.parent) as temp:
        stage = Path(temp) / 'review-council'
        stage.mkdir()
        shared = REPO / 'plugins/review-council'
        for name in ('.codex-plugin', 'agents', 'codex-skills', 'docs', 'scripts', 'schema', 'tests'):
            shutil.copytree(shared / name, stage / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        _make_staging_writable(stage)
        shutil.copy2(REPO / 'docs/config.md', stage / 'docs/config.md')
        shutil.copy2(REPO / 'LICENSE', stage / 'LICENSE')
        _make_staging_writable(stage)
        # Host selection also works for direct CLI use; no shell/session hook needed.
        for name in ('roster.sh', 'stack.sh'):
            path = stage / 'scripts' / name
            content = path.read_text()
            path.write_text(content.replace('#!/bin/bash\n',
                            '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=codex\n', 1))
        if cachebuster is not None:
            _stamp_cachebuster(stage, cachebuster)
        if output.exists():
            _atomic_exchange(stage, output)
        else:
            stage.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'dist/review-council',
                        help='generated directory to replace (must end in review-council)')
    args = parser.parse_args()
    try:
        print(build(args.output))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'build-codex: {exc}\n')
