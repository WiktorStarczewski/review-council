#!/usr/bin/env python3
"""Resolve or launch the cheap workhorse for a review session."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
import workhorse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    resolve = commands.add_parser('resolve')
    resolve.add_argument('--write', required=True)
    resolve.add_argument('--refresh', action='store_true')
    show = commands.add_parser('show')
    show.add_argument('path')
    launch = commands.add_parser('launch')
    launch.add_argument('--session', required=True)
    launch.add_argument('--task', required=True, choices=('plan', 'implement', 'review'))
    launch.add_argument('--cluster')
    launch.add_argument('--prompt')
    launch.add_argument('--out')
    launch.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'resolve':
            written = workhorse.write_record(args.write, workhorse.probe(), refresh=args.refresh)
            print(json.dumps(written, sort_keys=True))
            return 0
        if args.command == 'show':
            document = workhorse.read_record(args.path)
            if document is None:
                print('workhorse: record is missing', file=sys.stderr)
                return 3
            print(json.dumps(document, sort_keys=True))
            return 0
        return workhorse.execute_launch(args.session, args.task, args.cluster, args.prompt,
                                         args.out, args.dry_run)
    except ValueError as error:
        print('workhorse: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
