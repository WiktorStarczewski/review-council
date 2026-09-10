#!/usr/bin/env python3
"""Build and install through Codex's implicitly discovered personal marketplace."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


def install():
    if shutil.which('codex') is None:
        raise ValueError('codex CLI is required (with plugin add support)')
    home = Path.home()
    marketplace = home / '.agents/plugins/marketplace.json'
    data = json.loads(marketplace.read_text()) if marketplace.exists() else {
        'name': 'personal', 'interface': {'displayName': 'Personal'}, 'plugins': []}
    name = data.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('invalid existing personal marketplace name')
    plugins = data.get('plugins')
    if not isinstance(plugins, list) or any(not isinstance(p, dict) for p in plugins):
        raise ValueError('invalid existing marketplace plugins list')
    existing = next((p for p in plugins if p.get('name') == 'review-council'), None)
    source = {'source': 'local', 'path': './plugins/review-council'}
    if existing and existing.get('source') != source:
        raise ValueError('review-council already points elsewhere; refusing to replace its source')
    spec = importlib.util.spec_from_file_location('builder', Path(__file__).with_name('build-codex-plugin.py'))
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    output = builder.build(home / 'plugins/review-council')
    manifest = output / '.codex-plugin/plugin.json'
    metadata = json.loads(manifest.read_text())
    metadata['version'] = metadata['version'].split('+')[0] + '+codex.' + str(time.time_ns())
    manifest.write_text(json.dumps(metadata, indent=2) + '\n')
    if existing is None:
        plugins.append({'name': 'review-council', 'source': source,
                        'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
                        'category': 'Productivity'})
        marketplace.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=marketplace.parent, prefix='.marketplace-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2)
                stream.write('\n')
            os.replace(temp, marketplace)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    subprocess.run(['codex', 'plugin', 'add', 'review-council@' + name], check=True)
    print('Installed Review Council. Start a new Codex chat to load its skills.')


if __name__ == '__main__':
    try:
        install()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'install-codex: {exc}')
