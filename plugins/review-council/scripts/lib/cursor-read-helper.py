#!/usr/bin/env python3
"""Controller-owned IPC for the canonical reviewer read boundary."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


REQUEST_BYTES = 64 * 1024


def load_audit():
    path = Path(__file__).with_name('review-read-audit.py')
    spec = importlib.util.spec_from_file_location('council_cursor_read_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate request field')
        result[key] = value
    return result


def request_from(raw, audit):
    if len(raw) > REQUEST_BYTES:
        raise ValueError('reader request too large')
    return audit.cursor_read_request(json.loads(raw.decode('utf-8'), object_pairs_hook=closed_object))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--deps-root')
    parser.add_argument('--manifest')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--seat')
    parser.add_argument('--prompt-sha256')
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    try:
        audit = load_audit()
        context = None
        while True:
            raw = sys.stdin.buffer.readline(REQUEST_BYTES + 1) if args.serve \
                else sys.stdin.buffer.read(REQUEST_BYTES + 1)
            if not raw and args.serve:
                return 0
            if args.serve and not raw.endswith(b'\n'):
                raise ValueError('incomplete reader request')
            request = request_from(raw, audit)
            if context is None:
                context = audit.CouncilReaderContext(
                    args.root, args.session, args.prompt, args.deps_root,
                    args.manifest, args.manifest_sha256, args.seat,
                    prompt_sha256=args.prompt_sha256)
            response = context.read(request)
            sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(',', ':')) + '\n')
            sys.stdout.flush()
            if not args.serve:
                return 0
    except Exception:
        print('reader_refused', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
