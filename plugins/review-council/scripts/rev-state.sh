#!/bin/bash
# rev-state.sh <session-dir> key=value...
# Merge keys into <session>/state.json (created if absent). Dotted keys nest: open.P1=1.
# Values that parse as JSON are stored typed (1, true, null, ["a"], {"x":1}); otherwise as strings.
set -u
S=${1:?usage: rev-state.sh <session-dir> key=value...}; shift
[ $# -gt 0 ] || { echo "usage: rev-state.sh <session-dir> key=value..." >&2; exit 1; }
mkdir -p "$S"
python3 - "$S/state.json" "$@" <<'PY'
import json, math, os, sys

def _reject_constant(name):
    raise ValueError(f"rev-state: non-standard JSON constant {name!r} rejected")

path, kvs = sys.argv[1], sys.argv[2:]
state = {}
if os.path.exists(path):
    with open(path) as f:
        state = json.load(f)
for kv in kvs:
    k, sep, v = kv.partition('=')
    if not sep or not k:
        print(f"rev-state: bad argument '{kv}' (want key=value)", file=sys.stderr); sys.exit(1)
    try:
        val = json.loads(v, parse_constant=_reject_constant)
        # A numeric literal (e.g. "1e23456") can parse successfully yet overflow
        # to a non-finite float; treat that the same as a rejected NaN/Infinity
        # token and fall back to storing the original string.
        if isinstance(val, float) and not math.isfinite(val):
            raise ValueError(f"rev-state: non-finite numeric literal {v!r} rejected")
    except Exception:
        val = v
    node = state
    parts = k.split('.')
    for p in parts[:-1]:
        node = node.setdefault(p, {})
        if not isinstance(node, dict):
            print(f"rev-state: '{k}': '{p}' is not an object", file=sys.stderr); sys.exit(1)
    node[parts[-1]] = val
tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(state, f, indent=1, allow_nan=False)
os.replace(tmp, path)
PY
