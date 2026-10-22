#!/usr/bin/env python3
"""Write the session roster config for normal or high mode before preflight."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
import panel_request


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--base')
    args = parser.parse_args(argv)
    try:
        path = panel_request.write_session(args.session, args.text, args.base)
    except ValueError as error:
        print('panel-request: ' + str(error), file=sys.stderr)
        return 2
    if path is not None:
        print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
