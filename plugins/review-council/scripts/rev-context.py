#!/usr/bin/env python3
"""Read a compact session briefing or watch changes on a fixed status cadence."""
import argparse
import contextlib
import io
import json
import math
import os
from pathlib import Path
import re
import runpy
import stat
import sys
import time

LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z')
TERMINAL_PHASES = {'done', 'blocked', 'stack-ready'}
ARTIFACTS = {
    'findings': 'findings.md', 'rejected': 'rejected.md', 'decisions': 'context.md',
    'baseline': 'baseline.md', 'structured_baseline': 'baseline.json',
    'coverage': 'coverage-head.json',
}
VALIDATOR = runpy.run_path(str(Path(__file__).parent / 'lib/validate-findings.py'))
SCHEMA = json.loads(Path(VALIDATOR['SCHEMA']).read_text())


def read_file(path, optional=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError(f'missing {path.name}') from None
    except OSError:
        raise ValueError(f'cannot safely read {path.name}') from None
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f'{path.name} must be a regular file')
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError(f'{path.name} exceeds the briefing read limit')
    try:
        return raw.decode('utf-8')
    except UnicodeError:
        raise ValueError(f'{path.name} must contain UTF-8') from None


def pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def parse_json(raw):
    def invalid_constant(value):
        raise ValueError(f'invalid JSON number: {value}')
    return json.loads(raw, object_pairs_hook=pairs_unique, parse_constant=invalid_constant)


def label(value, name):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError(f'invalid {name}')
    value = str(value)
    if not LABEL.fullmatch(value):
        raise ValueError(f'invalid {name}')
    return value


def valid_result(raw):
    try:
        value = parse_json(raw)
        with contextlib.redirect_stderr(io.StringIO()):
            VALIDATOR['check'](value, SCHEMA, '$')
        return value
    except (ValueError, SystemExit):
        return None


def briefing(session):
    session = Path(session).resolve(strict=True)
    if not session.is_dir():
        raise ValueError('session must be a directory')
    state = parse_json(read_file(session / 'state.json'))
    if not isinstance(state, dict):
        raise ValueError('state must be an object')
    round_label = label(state.get('round', 1), 'round')
    phase = label(state.get('phase', 'setup'), 'phase')
    seats = state.get('seats', [])
    dropped = state.get('dropped', [])
    if not isinstance(seats, list) or not isinstance(dropped, list):
        raise ValueError('seats and dropped must be lists')
    seats = [label(seat, 'seat') for seat in seats]
    dropped = {label(seat, 'dropped seat') for seat in dropped}
    if len(seats) > 64 or len(set(seats)) != len(seats):
        raise ValueError('invalid seat count or duplicate seat')
    raw_roster = read_file(session / 'roster.json', optional=True)
    roster = parse_json(raw_roster) if raw_roster is not None else {}
    if not isinstance(roster, dict) or not isinstance(roster.get('seats', []), list):
        raise ValueError('invalid roster')
    identities = {}
    for row in roster.get('seats', []):
        if not isinstance(row, dict):
            raise ValueError('invalid roster seat')
        name = label(row.get('seat'), 'roster seat')
        if name in identities:
            raise ValueError('duplicate roster seat')
        identities[name] = {key: row[key] for key in ('adapter', 'model', 'effort') if key in row}
        if any(not isinstance(value, str) or len(value) > 120 for value in identities[name].values()):
            raise ValueError('invalid roster identity')
    summaries = []
    for seat in seats:
        base = session / f'r{round_label}-{seat}'
        entry = {'seat': seat, **identities.get(seat, {})}
        raw_exit = read_file(Path(f'{base}.exit'), optional=True)
        if seat in dropped:
            status = 'dropped'
        elif read_file(Path(f'{base}.audit-invalid.json'), optional=True) is not None:
            status = 'audit-invalid'
        elif raw_exit is not None:
            code = raw_exit.strip()
            if not re.fullmatch(r'[0-9]{1,3}', code):
                status = 'invalid-exit'
            elif code != '0':
                status = 'failed'
                entry['exit_code'] = int(code)
            else:
                raw_result = read_file(Path(f'{base}.json'), optional=True)
                result = valid_result(raw_result) if raw_result is not None else None
                status = 'missing-result' if raw_result is None else 'invalid-result'
                if result is not None:
                    status = 'incomplete-proof' if result['summary'].startswith('INCOMPLETE PROOF') else 'ready-for-collection'
                    entry['findings'] = len(result['findings'])
        else:
            status = 'running' if read_file(Path(f'{base}.prompt.md'), optional=True) is not None else 'pending'
        entry['status'] = status
        summaries.append(entry)
    opened = state.get('open', {})
    fixed = state.get('fixed', 0)
    if not isinstance(opened, dict) or any(key not in {'P0', 'P1', 'P2', 'P3'} or not isinstance(value, int) or isinstance(value, bool) or value < 0 for key, value in opened.items()):
        raise ValueError('invalid open counts')
    if not isinstance(fixed, int) or isinstance(fixed, bool) or fixed < 0:
        raise ValueError('invalid fixed count')
    minimum = state.get('min_rounds', '?')
    if not isinstance(minimum, (str, int)) or isinstance(minimum, bool) or len(str(minimum)) > 40:
        raise ValueError('invalid minimum rounds')
    return {'phase': phase, 'round': round_label, 'min_rounds': minimum,
            'seats': summaries, 'open': opened, 'fixed': fixed,
            'certification': 'not evaluated', 'artifacts': ARTIFACTS}


def render(context):
    seats = ', '.join(f"{seat['seat']}: {seat['status']}" for seat in context['seats'])
    return (f"r{context['round']}/{context['min_rounds']} {context['phase']} | {seats} | "
            f"open {json.dumps(context['open'], separators=(',', ':'))} fixed {context['fixed']}\n"
            'Certification: not evaluated. Collect and receipt checks remain required.\n'
            'Artifacts: ' + ', '.join(f'{key}={value}' for key, value in context['artifacts'].items()))


def watch(session, interval=600, poll_interval=1, duration=600, json_output=False):
    start = time.monotonic()
    next_tick = start + interval
    end = start + duration
    previous = None
    while True:
        now = time.monotonic()
        context = briefing(session)
        scheduled = now >= next_tick
        event = 'initial' if previous is None else 'scheduled' if scheduled else 'changed'
        if previous is None or context != previous or scheduled:
            if json_output:
                print(json.dumps({'event': event, 'elapsed_seconds': round(now - start, 3), 'context': context}), flush=True)
            else:
                print(f'[{event} {int(now - start)}s] {render(context)}', flush=True)
        previous = context
        while next_tick <= now:
            next_tick += interval
        if context['phase'] in TERMINAL_PHASES or now >= end:
            return
        time.sleep(min(poll_interval, next_tick - now, end - now))


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be positive and finite')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=positive, default=600)
    parser.add_argument('--poll-interval', type=positive, default=1)
    parser.add_argument('--duration', type=positive, default=600)
    args = parser.parse_args()
    try:
        if args.watch:
            watch(args.session, args.interval, args.poll_interval, args.duration, args.json)
        else:
            context = briefing(args.session)
            print(json.dumps(context) if args.json else render(context))
    except (OSError, ValueError) as error:
        print(f'context: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
