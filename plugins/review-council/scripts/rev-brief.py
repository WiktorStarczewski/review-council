#!/usr/bin/env python3
"""Print the compact brief a fresh orchestrator needs for one wake."""
import argparse
import json
from pathlib import Path
import sys


PLUGIN = Path(__file__).resolve().parents[1]
MECHANICAL = {'publish', 'ci', 'closeout', 'render', 'done'}
PHASE_FILES = {
    'setup': '10-setup.md',
    'discovery': '20-discovery.md',
    'fan-out': '20-discovery.md',
    'collect': '20-discovery.md',
    'triage': '30-triage.md',
    'plan': '40-plan.md',
    'fix': '50-fix.md',
    'verify': '60-verification.md',
    'verification': '60-verification.md',
    'commit': '60-verification.md',
    'publish': '70-publish.md',
    'ci': '70-publish.md',
    'closeout': '70-publish.md',
    'render': '70-publish.md',
    'done': '70-publish.md',
}


def skill_dir(host):
    if host == 'codex':
        return PLUGIN / 'codex-skills' / 'rev'
    if host == 'cursor':
        cursor = PLUGIN / 'cursor-skills' / 'rev'
        if (cursor / 'phases').is_dir():
            return cursor
        return PLUGIN / 'codex-skills' / 'rev'
    return PLUGIN / 'skills' / 'rev'


def load_json(path):
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def phase_file(phases, phase):
    name = PHASE_FILES.get(phase, '20-discovery.md')
    if phase in ('plan', 'fix') and not (phases / name).is_file():
        name = '30-triage.md'
    if phase in ('verify', 'verification', 'commit') and not (phases / '60-verification.md').is_file():
        name = '30-triage.md'
    return 'phases/' + name


def brief(session, host, config_path):
    state = load_json(Path(session) / 'state.json')
    config = load_json(Path(config_path)) if config_path else {}
    phase = state.get('phase') if isinstance(state.get('phase'), str) else 'setup'
    skill = skill_dir(host)
    mechanical = phase in MECHANICAL
    document = {
        'session': str(Path(session)),
        'phase': phase,
        'round': state.get('round'),
        'open': {key: state.get(key) for key in ('open.P0', 'open.P1', 'open.P2', 'open.P3')},
        'phase_file': phase_file(skill / 'phases', phase),
        'mechanical': mechanical,
        'status_tick': bool(state.get('status_tick') or config.get('status_tick') is True),
    }
    model = config.get('host_mechanical_model')
    if mechanical and isinstance(model, str) and model.strip():
        document['model'] = model.strip()
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session')
    parser.add_argument('--host', default='claude')
    parser.add_argument('--config')
    args = parser.parse_args(argv)
    if args.host not in ('claude', 'codex', 'cursor'):
        print('rev-brief: unknown host', file=sys.stderr)
        return 2
    print(json.dumps(brief(args.session, args.host, args.config), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
