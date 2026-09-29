"""Controlled replay benchmarks. Every provider executable is replaced locally."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def run(args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)


def git(root, *args):
    result = run(['git', '-C', str(root), *args])
    if result.returncode:
        raise ValueError(result.stderr)


def preflight_case(plugin, destination):
    destination.mkdir(parents=True)
    root, checker = destination / 'root', destination / 'checker'
    (root / 'plugins/review-council/.codex-plugin').mkdir(parents=True)
    boundary = root / 'plugins/review-council/scripts/rev-prompt.sh'
    boundary.parent.mkdir()
    (root / 'plugins/review-council/.codex-plugin/plugin.json').write_text('{}\n')
    boundary.write_text('old\n')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '.')
    git(root, '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture',
        '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Contract fixture')
    git(root, 'checkout', '-qb', 'change')
    boundary.write_text('new\n')
    shutil.copytree(plugin, checker, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    roster = destination / 'roster.json'
    roster.write_text(json.dumps({'seats': [
        {'seat': 'sol', 'adapter': 'codex', 'model': 'gpt-5.6-sol', 'effort': 'max', 'extra': False},
        {'seat': 'terra', 'adapter': 'codex', 'model': 'gpt-5.6-terra', 'effort': 'max', 'extra': False},
        {'seat': 'opus', 'adapter': 'claude', 'model': 'opus', 'effort': 'max', 'extra': False},
        {'seat': 'sonnet', 'adapter': 'claude', 'model': 'sonnet', 'effort': 'max', 'extra': False}]}))
    probe = checker / 'scripts/roster.sh'
    probe.chmod(probe.stat().st_mode | 0o200)
    probe.write_text(
        '#!/bin/bash\nprintf "probe\\n" >> "$BENCH_PROBES"\n'
        'while [ "$#" -gt 0 ]; do\n'
        'if [ "$1" = --write ]; then cp "$BENCH_ROSTER" "$2"; shift 2; else shift; fi\ndone\n')
    runner = destination / 'contract-runner'
    runner.write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> "$BENCH_CONTRACTS"\nexit 7\n')
    runner.chmod(0o755)
    binary = destination / 'bin'
    binary.mkdir()
    (binary / 'gh').write_text('#!/bin/sh\nexit 1\n')
    (binary / 'gh').chmod(0o755)
    environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
        BENCH_PROBES=str(destination / 'probes'), BENCH_ROSTER=str(roster),
        BENCH_CONTRACTS=str(destination / 'contracts'), REVIEW_COUNCIL_CACHE_DIR=str(destination / 'cache'),
        REVIEW_COUNCIL_CONTRACT_RUNNER=str(runner),
        REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS='{"codex":"fixture","claude":"fixture"}')
    for key in ('REV_ACTIVE', 'REV_RG'):
        environment.pop(key, None)
    start = time.monotonic()
    result = run(['bash', str(checker / 'scripts/rev-preflight.sh'), '--write',
                  str(destination / 'session')], cwd=root, env=environment)
    (destination / 'stdout.log').write_text(result.stdout)
    (destination / 'stderr.log').write_text(result.stderr)
    probes = destination / 'probes'
    return {'exit_code': result.returncode, 'wall_seconds': time.monotonic() - start,
            'roster_probes': len(probes.read_text().splitlines()) if probes.exists() else 0,
            'authoritative_receipt': any((destination / 'session').glob('contract-pass-*.json')),
            'provider_executions': 0, 'scenario': 'local contract runner deliberately fails'}


def accounting_case(plugin, session):
    session.mkdir(parents=True)
    (session / 'roster.json').write_text('{"seats":[{"seat":"opus","adapter":"agent"}]}')
    records = [
        {'type': 'assistant', 'message': {'id': 'a', 'usage': {'input_tokens': 5, 'output_tokens': 2}}},
        {'type': 'assistant', 'message': {'id': 'a', 'usage': {'input_tokens': 5, 'output_tokens': 6}}},
        {'type': 'assistant', 'message': {'id': 'b', 'usage': {'input_tokens': 3, 'output_tokens': 1}}}]
    first = session / 'r1-opus.stream.ndjson'
    first.write_text(''.join(json.dumps(row) + '\n' for row in records))
    shutil.copy2(first, session / 'r1-opus.stream.jsonl')
    (session / 'r2-opus.stream.ndjson').write_text(json.dumps(
        {'type': 'assistant', 'message': {'id': 'c', 'usage': {'input_tokens': 9, 'output_tokens': 2}}}) + '\n')
    (session / 'r1-opus.json').write_text('{"summary":"checked","findings":[]}')
    (session / 'r1-opus.exit').write_text('0\n')
    (session / 'r2-opus.exit').write_text('2\n')
    start = time.monotonic()
    result = run([sys.executable, str(plugin / 'scripts/rev-profile.py'), '--json', str(session)])
    if result.returncode:
        raise ValueError(result.stderr)
    profile = json.loads(result.stdout)
    (session / 'profile.json').write_text(result.stdout)
    usage = profile['sessions'][0]['usage']
    return {'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'],
            'processed_tokens': usage['processed_tokens'], 'expected_input': 17, 'expected_output': 9,
            'matches_truth': usage['input_tokens'] == 17 and usage['output_tokens'] == 9,
            'wall_seconds': time.monotonic() - start, 'provider_executions': 0}


def context_case(plugin, session):
    helper = plugin / 'scripts/rev-context.py'
    if not helper.exists():
        return {'available': False, 'provider_executions': 0}
    session.mkdir(parents=True)
    (session / 'state.json').write_text(json.dumps(
        {'round': 1, 'phase': 'risk', 'seats': ['sol', 'terra', 'opus', 'sonnet']}))
    (session / 'roster.json').write_text(json.dumps({'seats': [
        {'seat': name, 'adapter': adapter, 'model': model, 'effort': 'max'}
        for name, adapter, model in [('sol', 'codex', 'gpt-5.6-sol'),
            ('terra', 'codex', 'gpt-5.6-terra'), ('opus', 'claude', 'opus'), ('sonnet', 'claude', 'sonnet')]]}))
    text = run([sys.executable, str(helper), str(session)])
    data = run([sys.executable, str(helper), str(session), '--json'])
    start = time.monotonic()
    watch = run([sys.executable, str(helper), str(session), '--watch', '--json',
                 '--duration', '0.05', '--poll-interval', '0.01'])
    if text.returncode or data.returncode or watch.returncode:
        raise ValueError('local context helper failed')
    (session / 'briefing.txt').write_text(text.stdout)
    (session / 'watch.ndjson').write_text(watch.stdout)
    return {'available': True, 'words': len(text.stdout.split()), 'bytes': len(text.stdout.encode()),
            'certification': json.loads(data.stdout)['certification'],
            'watch_events': len(watch.stdout.splitlines()), 'watch_seconds': time.monotonic() - start,
            'provider_executions': 0}
