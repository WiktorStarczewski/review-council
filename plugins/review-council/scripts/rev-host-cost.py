#!/usr/bin/env python3
"""Compare injected host-skill bytes with the 0.7.5 rev skills.

The skill loader injects SKILL.md on every host turn. Phase files are not
injected. Tokens use the same bytes/4 ratio as issue 55 (90 KB ~ 23k tokens).
This does not rerun a review and does not change seat coverage, audits, or receipts.
"""
import argparse
import json
from pathlib import Path
import sys


PLUGIN = Path(__file__).resolve().parents[1]
# Injected skill sizes on review-council 0.7.5, measured 2026-10-22.
BEFORE = {'claude': 90481, 'codex': 65039}
CORES = {
    'claude': PLUGIN / 'skills' / 'rev' / 'SKILL.md',
    'codex': PLUGIN / 'codex-skills' / 'rev' / 'SKILL.md',
}


def tokens(size):
    return size // 4


def report():
    rows = {}
    for host, path in CORES.items():
        after = path.stat().st_size
        before = BEFORE[host]
        rows[host] = {
            'before_bytes': before,
            'after_bytes': after,
            'before_tokens_per_turn': tokens(before),
            'after_tokens_per_turn': tokens(after),
            'saved_tokens_per_turn': tokens(before) - tokens(after),
        }
    return {'version': 1, 'ratio': 'bytes/4', 'injected': 'SKILL.md', 'hosts': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns', type=int, default=0,
                        help='multiply the per-turn saving by this many host turns')
    args = parser.parse_args(argv)
    document = report()
    if args.turns:
        for row in document['hosts'].values():
            row['saved_tokens'] = row['saved_tokens_per_turn'] * args.turns
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
