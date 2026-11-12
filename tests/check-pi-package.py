#!/usr/bin/env python3
"""Exercise real Pi installation and RPC discovery without provider/model calls."""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parents[1]


def check():
    executable = Path(shutil.which('pi')).resolve()
    package_root = next(parent for parent in executable.parents
                        if (parent / 'package.json').is_file()
                        and json.loads((parent / 'package.json').read_text()).get('name')
                        == '@earendil-works/pi-coding-agent')
    loader = package_root / 'dist/core/extensions/loader.js'
    subprocess.run(['node', '--test', str(REPO / 'tests/pi-reload.test.mjs')],
                   env=dict(os.environ, PI_TEST_LOADER=loader.as_uri()), check=True, timeout=30)
    with tempfile.TemporaryDirectory(prefix='council-pi-discovery-') as directory:
        root = Path(directory)
        env = dict(os.environ, HOME=str(root), PI_CODING_AGENT_DIR=str(root / 'agent'),
                   PI_OFFLINE='1')
        env.pop('REV_ACTIVE', None)
        subprocess.run(['pi', 'install', str(REPO)], env=env, cwd=root,
                       check=True, timeout=30)
        settings = json.loads((root / 'agent/settings.json').read_text())
        assert REPO in [(root / 'agent' / source).resolve()
                        for source in settings['packages']], settings
        with (root / 'stderr.log').open('w+') as errors:
            proc = subprocess.Popen(['pi', '--mode', 'rpc', '--no-session',
                                     '--no-context-files', '--offline'],
                                    cwd=root, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=errors, text=True)
            records = queue.Queue()

            def consume():
                for line in proc.stdout:
                    records.put(json.loads(line))
                records.put(None)

            reader = threading.Thread(target=consume, daemon=True)
            reader.start()

            def request(command):
                proc.stdin.write(json.dumps(command) + '\n')
                proc.stdin.flush()
                deadline = time.monotonic() + 30
                seen = []
                while time.monotonic() < deadline:
                    record = records.get(timeout=max(0.01, deadline - time.monotonic()))
                    assert record is not None, 'Pi exited before response'
                    assert record.get('type') != 'agent_start', 'discovery must not call a model'
                    seen.append(record)
                    if record.get('type') == 'response' and record.get('id') == command['id']:
                        assert record.get('success'), record
                        return record, seen
                raise AssertionError('Pi RPC response deadline exceeded')

            try:
                response, _ = request({'id': 'commands', 'type': 'get_commands'})
                commands = response['data']['commands']
                for name in ('council', 'rev'):
                    command = [item for item in commands if item['name'] == name]
                    assert len(command) == 1, commands
                    assert command[0]['source'] == 'extension', command
                    provenance = command[0]['sourceInfo']['path']
                    assert Path(provenance).resolve() == REPO / 'pi/rev.ts', command
                skills = [item['name'] for item in commands if item['source'] == 'skill']
                assert skills == ['skill:review-council-rev'], skills
                assert not any(item['name'] == 'stack' for item in commands), commands
                for flag in ('--help', '--setup', 'high', 'status', 'eco'):
                    response, seen = request({'id': flag, 'type': 'prompt', 'message': '/council ' + flag})
                    assert response['data']['disposition'] == 'handled', response
                    notices = [item for item in seen if item.get('type') == 'extension_ui_request']
                    assert notices, seen
                    if flag in ('high', 'eco'):
                        statuses = [item for item in notices if item.get('method') == 'setStatus']
                        assert len(statuses) == 1, notices
                        assert statuses[0]['statusKey'] == 'review-council', statuses
                        expected = '⚖️ council: 🔥 HIGH' if flag == 'high' else '⚖️ council: 🌿 ECO'
                        plain = re.sub(r'\x1b\[[0-9;]*m', '', statuses[0]['statusText'])
                        assert plain == expected, plain
            finally:
                proc.stdin.close()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                proc.stdout.close()
                reader.join(timeout=5)
                errors.seek(0)
                diagnostics = errors.read()
                assert proc.returncode == 0, diagnostics
                assert 'Failed to load extension' not in diagnostics, diagnostics
        print('PASS: installed Pi package discovers /council, /rev and its unique skill; mode/status/help/setup make no model calls')


if __name__ == '__main__':
    check()
