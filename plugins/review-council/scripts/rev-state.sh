#!/bin/bash
# rev-state.sh <session-dir> key=value...
# Merge keys into <session>/state.json (created if absent). Dotted keys nest: open.P1=1.
# Values that parse as JSON are stored typed (1, true, null, ["a"], {"x":1}); otherwise as strings.
# phase=plan round=<N>p (or <N>px) seats=[...] also records plans.<label>. phase=fix exits 2 with state
# unchanged while open P0+P1+P2 > 0, unless plan <N>p or <N>px completed or findings.md records its skip.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
S=${1:?usage: rev-state.sh <session-dir> key=value...}; shift
[ $# -gt 0 ] || { echo "usage: rev-state.sh <session-dir> key=value..." >&2; exit 1; }
mkdir -p "$S"
REV_STATE_EVIDENCE="$HERE/rev-evidence.py" python3 - "$S/state.json" "$@" <<'PY'
import json, math, os, re, stat, subprocess, sys

def _reject_constant(name):
    raise ValueError(f"rev-state: non-standard JSON constant {name!r} rejected")

path, kvs = sys.argv[1], sys.argv[2:]
session = os.path.dirname(path)
state = {}
if os.path.exists(path):
    with open(path) as f:
        state = json.load(f)
BREAKER_KEYS = ('review_base_tree', 'review_origin', 'review_origin_ack')


def save():
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=1, allow_nan=False)
    os.replace(tmp, path)


if kvs[:1] == ['inherit-breaker']:
    # A quota-fallback session carries the parent's breaker window instead of starting a new one.
    if len(kvs) != 2:
        print("usage: rev-state.sh <fallback-session> inherit-breaker <parent-session>", file=sys.stderr); sys.exit(1)
    if any(key in state for key in BREAKER_KEYS):
        print("rev-state: refusing inherit-breaker: this session already has breaker state", file=sys.stderr); sys.exit(2)
    with open(os.path.join(kvs[1], 'state.json')) as f:
        parent = json.load(f)
    state.update({key: parent[key] for key in BREAKER_KEYS if key in parent})
    save()
    sys.exit(0)
assigned = set()
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
    assigned.add(k)


SEAT_NAME = r'[A-Za-z0-9][A-Za-z0-9._-]*'


def refuse(message):
    print(f"rev-state: {message}", file=sys.stderr)
    sys.exit(2)


def receipt_file(name):
    try:
        info = os.lstat(os.path.join(session, name))
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) and info.st_size > 0 else None


def newest_seat_exit():
    # Newest r<N>[x]-<seat>.exit mtime, the moment this round's findings stopped arriving.
    # rev-seat.sh deletes the receipt before every relaunch, so the mtime is this launch's.
    # Plan rounds (r<N>p-) are excluded on purpose: the plan panel runs after triage by
    # design, so counting its exits would refuse every sanctioned triage-plan-fix path.
    newest = 0.0
    try:
        names = os.listdir(session)
    except OSError:
        return newest
    for name in names:
        if not re.fullmatch(rf'r[0-9]+x?-{SEAT_NAME}\.exit', name):
            continue
        try:
            newest = max(newest, os.lstat(os.path.join(session, name)).st_mtime)
        except OSError:
            continue
    return newest


def plan_completed(label):
    seats = (state.get('plans') or {}).get(label) if isinstance(state.get('plans'), dict) else None
    if not isinstance(seats, list) or not seats:
        return False
    for seat in seats:
        if not isinstance(seat, str) or not re.fullmatch(SEAT_NAME, seat):
            return False
        if not receipt_file(f'r{label}-{seat}.json') or not receipt_file(f'r{label}-{seat}.exit'):
            return False
        with open(os.path.join(session, f'r{label}-{seat}.exit'), encoding='utf-8', errors='replace') as f:
            if f.read().strip() != '0':
                return False
    return True


def plan_skipped(label):
    prefix = f'Plan panel r{label} - SKIPPED:'
    ledger = os.path.join(session, 'findings.md')
    if not os.path.isfile(ledger):
        return False
    with open(ledger, encoding='utf-8', errors='replace') as f:
        return any(line.startswith(prefix) and line[len(prefix):].strip() for line in f)


if {'open.P0', 'open.P1', 'open.P2'} <= assigned:
    state['open_stamp'] = newest_seat_exit()

phase = state.get('phase')
if 'phase' in assigned and phase == 'plan' and {'round', 'seats'} <= assigned:
    label, seats = state.get('round'), state.get('seats')
    if isinstance(label, str) and re.fullmatch(r'[0-9]+px?', label):
        if (not isinstance(seats, list) or not seats
                or not all(isinstance(seat, str) and re.fullmatch(SEAT_NAME, seat) for seat in seats)):
            refuse(f"refusing phase=plan round={label}: seats must be a JSON array of seat names, "
                   f"for example 'seats=[\"codex-sol\"]', not {seats!r}")
        plans = state.setdefault('plans', {})
        if not isinstance(plans, dict):
            print("rev-state: 'plans' is not an object", file=sys.stderr); sys.exit(1)
        plans[label] = seats

if 'phase' in assigned and phase == 'fix':
    opened = state.get('open') if isinstance(state.get('open'), dict) else {}
    total = 0
    for severity in ('P0', 'P1', 'P2'):
        count = opened.get(severity, 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            refuse(f"refusing phase=fix: open.{severity}={count!r} is not a non-negative integer")
        total += count
    newest_exit = newest_seat_exit()
    stamp = state.get('open_stamp')
    if newest_exit and (not isinstance(stamp, (int, float)) or stamp < newest_exit):
        refuse("refusing phase=fix: open.P0/P1/P2 have not been written since the last seat "
               "exit, so the counts are last round's - re-run triage and set "
               "open.P0=<n> open.P1=<n> open.P2=<n>")
    code_round = re.fullmatch(r'([0-9]+)(?:px|p|x)?', str(state.get('round')))
    if code_round and receipt_file(f'r{int(code_round.group(1))}-coverage.receipt.json'):
        number = str(int(code_round.group(1)))
        command = [sys.executable, os.environ['REV_STATE_EVIDENCE'], 'review-origin', session, number]
        if isinstance(state.get('review_base_tree'), str):
            command += ['--base-tree', state['review_base_tree']]
        origin = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if origin.returncode:
            refuse(f"refusing phase=fix: cannot count review-origin citations for round {number}: "
                   + origin.stderr.strip())
        counted = json.loads(origin.stdout)
        state.setdefault('review_base_tree', counted['review_base_tree'])
        state.setdefault('review_origin', {})[number] = counted['citations']
    ack = state.get('review_origin_ack', 0)
    if isinstance(ack, bool) or not isinstance(ack, int):
        refuse(f"refusing phase=fix: review_origin_ack={ack!r} is not a round number")
    tripped = sorted(int(label) for label, count in (state.get('review_origin') or {}).items()
                     if count and int(label) > ack)
    if len(tripped) >= 2:
        refuse(f"refusing phase=fix: rounds {', '.join(map(str, tripped))} cite lines this review "
               "changed. Ask the user first (recommended: revert the cited review changes and defer "
               f"the originating findings), then record review_origin_ack={tripped[-1]}")
    if total > 0:
        match = code_round
        if not match:
            refuse(f"refusing phase=fix: cannot determine the code round from round={state.get('round')!r}; "
                   "set round=<N> before phase=fix")
        label = f'{int(match.group(1))}p'
        # A failed plan seat is replaced by a one-seat <N>px plan panel.
        if not plan_completed(label) and not plan_completed(label + 'x') and not plan_skipped(label):
            refuse(f"refusing phase=fix for round {int(match.group(1))}: {total} open P0-P2 findings need "
                   f"the plan gate - complete plan panel r{label} (phase=plan round={label} \"seats=[...]\", "
                   f"then every seat's r{label}-<seat>.json with a 0 exit) or append a findings.md line "
                   f"'Plan panel r{label} - SKIPPED: <reason>'")
save()
PY
