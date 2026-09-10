#!/usr/bin/env python3
"""Exercise real Codex installation and discovery without starting a model turn."""

import argparse
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time


REPO = Path(__file__).resolve().parents[1]
PLUGIN_ID = 'review-council@review-council'
EXPECTED_SKILLS = {'review-council:rev', 'review-council:stack'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_json(command, env, cwd):
    result = subprocess.run(
        command, env=env, cwd=cwd, capture_output=True, text=True, timeout=120
    )
    require(
        result.returncode == 0,
        '{} failed ({}):\n{}\n{}'.format(
            ' '.join(command), result.returncode, result.stdout, result.stderr
        ),
    )
    return json.loads(result.stdout)


def discover(codex, env, cwd, marketplace):
    """Use metadata APIs only: no thread/start or turn/start requests."""
    requests = [
        {
            'id': 1,
            'method': 'initialize',
            'params': {
                'clientInfo': {'name': 'review-council-install-test', 'version': '1.0.0'},
                'capabilities': {'experimentalApi': True},
            },
        },
        {'method': 'initialized', 'params': {}},
        {
            'id': 2,
            'method': 'plugin/read',
            'params': {'marketplacePath': str(marketplace), 'pluginName': 'review-council'},
        },
        {
            'id': 3,
            'method': 'skills/list',
            'params': {'cwds': [str(cwd)], 'forceReload': True},
        },
    ]
    responses = {}
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            [codex, 'app-server'],
            env=env,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
        )
        try:
            for request in requests:
                process.stdin.write((json.dumps(request) + '\n').encode())
                process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 30
                buffer = b''
                while time.monotonic() < deadline and not {2, 3}.issubset(responses):
                    if not selector.select(0.2):
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    require(chunk, 'Codex app-server closed stdout before returning metadata')
                    buffer += chunk
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        response = json.loads(line)
                        if 'id' not in response:
                            continue
                        require('error' not in response, 'Codex API error: {}'.format(response))
                        responses[response['id']] = response['result']
                require({2, 3}.issubset(responses), 'Timed out waiting for Codex plugin metadata')
        except Exception as error:
            stderr.seek(0)
            diagnostics = stderr.read().decode(errors='replace')
            raise RuntimeError('{}\n{}'.format(error, diagnostics)) from error
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
    return responses[2]['plugin'], responses[3]['data']


def check(source, ref):
    codex = shutil.which('codex')
    require(codex is not None, 'Install the Codex CLI before running this integration check')
    with tempfile.TemporaryDirectory(prefix='review-council-marketplace-') as directory:
        root = Path(directory).resolve()
        home = root / 'home'
        codex_home = root / 'codex'
        home.mkdir()
        codex_home.mkdir()
        env = dict(
            os.environ,
            HOME=str(home),
            CODEX_HOME=str(codex_home),
            XDG_CONFIG_HOME=str(root / 'config'),
            XDG_CACHE_HOME=str(root / 'cache'),
        )
        add = [codex, 'plugin', 'marketplace', 'add', source, '--json']
        if ref:
            add.extend(['--ref', ref])
        added = run_json(add, env, root)
        require(added['marketplaceName'] == 'review-council', 'Unexpected marketplace name')
        repeated = run_json(add, env, root)
        require(repeated['alreadyAdded'], 'Repeated marketplace registration was not idempotent')
        marketplace = Path(added['installedRoot']) / '.agents/plugins/marketplace.json'

        install = [codex, 'plugin', 'add', PLUGIN_ID, '--json']
        installed = run_json(install, env, root)
        repeated_install = run_json(install, env, root)
        require(installed['pluginId'] == PLUGIN_ID, 'Installed the wrong plugin')
        require(
            repeated_install['installedPath'] == installed['installedPath'],
            'Repeated installation changed the installed plugin path',
        )
        package = Path(installed['installedPath']).resolve()
        require(package.is_relative_to(codex_home), 'Installation escaped the temporary Codex home')
        adapter = package / 'scripts/seats.d/claude.sh'
        require(adapter.is_file() and os.access(adapter, os.X_OK), 'Claude adapter is missing or not executable')
        subprocess.run(['bash', '-n', str(adapter)], check=True, env=env, cwd=root, timeout=10)
        schema = json.loads((package / 'schema/findings.schema.json').read_text())
        require(isinstance(schema, dict) and 'properties' in schema, 'Findings schema is missing or invalid')

        listing = run_json([codex, 'plugin', 'list', '--json'], env, root)
        own_plugins = [item for item in listing['installed'] if item['pluginId'] == PLUGIN_ID]
        require(len(own_plugins) == 1 and own_plugins[0]['enabled'], 'Plugin is not installed and enabled')
        detail, entries = discover(codex, env, root, marketplace)
        require(detail['hooks'] == [], 'Codex discovered Claude hooks: {}'.format(detail['hooks']))
        require(
            {skill['name'] for skill in detail['skills']} == EXPECTED_SKILLS,
            'Plugin metadata does not expose exactly the two Codex skills',
        )
        require(not any(entry['errors'] for entry in entries), 'Codex reported skill loading errors')
        skills = [
            skill for entry in entries for skill in entry['skills']
            if skill.get('pluginId') == PLUGIN_ID
        ]
        require(
            len(skills) == 2 and {skill['name'] for skill in skills} == EXPECTED_SKILLS,
            'Installed skill discovery does not expose exactly rev and stack',
        )
        for skill in skills:
            path = Path(skill['path']).resolve()
            require(skill['enabled'], 'Codex skill is disabled: {}'.format(skill['name']))
            require(path.is_relative_to(package / 'codex-skills'), 'Loaded a Claude skill: {}'.format(path))
            require(path.is_file(), 'Loaded skill path does not exist: {}'.format(path))
    print('Codex marketplace check passed: repeatable install, rev/stack only, no hooks, shared adapter and schema.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=str(REPO), help='Local repository path or owner/repo')
    parser.add_argument('--ref', help='Git branch, tag, or commit for a remote marketplace source')
    args = parser.parse_args()
    try:
        check(args.source, args.ref)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print('Codex marketplace check failed: {}'.format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
