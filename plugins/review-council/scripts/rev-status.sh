#!/bin/bash
# rev-status.sh <session-dir>
# ONE line (≤220 chars) describing the run, from files in the session dir only:
#   r3/7 triage | sol: done 4f 9m | terra: done 2f 11m | opus: running 14m ← rg "retry" src/api | sonnet: done 3f 8m | open P0:0 P1:1 P2:3 fixed 6
# Per seat: pending | running <t>m ← <last action> | done <k>f <t>m | failed exit=<c> | dropped
set -u
S=${1:?usage: rev-status.sh <session-dir>}
[ -d "$S" ] || { echo "no session at $S"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
python3 - "$S" "$HERE" <<'PY'
import hashlib, importlib.util, json, os, re, subprocess, sys, time
from pathlib import Path
S = sys.argv[1]
st = {}
p = os.path.join(S, 'state.json')
if os.path.exists(p):
    try:
        with open(p) as f: st = json.load(f)
    except Exception: st = {}
now = time.time()
rnd = st.get('round', '?'); mn = st.get('min_rounds', '?'); phase = st.get('phase', 'setup')
seats = st.get('seats') or []
if not isinstance(seats, list): seats = [seats]   # a bare name is one seat, not one per character
dropped = set(st.get('dropped') or [])
SHORT = {'codex-sol': 'sol', 'codex-terra': 'terra', 'codex-review': 'cx-rev'}
sdk_seats = {}
try:
    with open(os.path.join(S, 'roster.json')) as source:
        rows = json.load(source)['seats']
    sdk_seats = {row['seat']: row for row in rows if row.get('adapter') == 'cursor-sdk'}
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    pass
profile = None
if sdk_seats:
    try:
        spec = importlib.util.spec_from_file_location('sdk_status_profile', Path(sys.argv[2]) / 'rev-profile.py')
        profile = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(profile)
    except (ImportError, OSError, ValueError):
        profile = None

def mtime(path):
    try: return os.stat(path).st_mtime
    except Exception: return None

def minutes(a, b):
    return int(max(0, b - a) // 60)

def findings_count(js):
    try:
        with open(js) as f: return len(json.load(f).get('findings', []))
    except Exception: return '?'

def last_action(log):
    try:
        with open(log, errors='replace') as f:
            lines = [l.rstrip('\n') for l in f if l.startswith(('exec: ', 'tool_call ', 'done: '))]
    except Exception: return ''
    if not lines: return ''
    l = lines[-1]
    l = re.sub(r'^(exec: |tool_call [^:]*: |done: exit=\S+ )', '', l)
    l = re.sub(r"^/bin/zsh -lc '?", '', l).rstrip("'")
    return l

def transcript_action(tx):
    if not isinstance(tx, str) or not tx or not os.path.exists(tx): return ''
    try:
        out = subprocess.run(['sh', '-c', "grep -o '\"name\":\"[A-Za-z_]*\"' \"$1\" | tail -1", '_', tx],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception: return ''
    return out.split(':')[-1].strip('"') if out else ''

def seat_action(seat, log):
    transcripts = st.get('agent_transcripts')
    if isinstance(transcripts, dict) and seat in transcripts:
        action = transcript_action(transcripts[seat])
        if action: return action
    if seat == 'opus' and st.get('opus_transcript'):
        action = transcript_action(st['opus_transcript'])
        if action: return action
    return last_action(log)

MAX = 220
ACTION_MAX = 40

seats_out = []          # (prefix, action) -- action is '' when there is none
for seat in seats:
    base = os.path.join(S, f"r{rnd}-{seat}")
    js, ex, lg, pr = base + '.json', base + '.exit', base + '.log', base + '.prompt.md'
    name = SHORT.get(seat, seat)
    sdk_identity_valid = False
    if seat in sdk_seats:
        try:
            identity = profile.cursor_sdk_identity(sdk_seats[seat])
            frozen = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            name += '[' + frozen[:8] + ']'
            sdk_identity_valid = True
        except (AttributeError, ValueError, TypeError, KeyError):
            name += '[unbound]'
    started = mtime(pr)
    if seat in dropped:
        seats_out.append((f"{name}: dropped", '')); continue
    if os.path.exists(ex):
        code = open(ex).read().strip()
        if code == '0':
            if seat in sdk_seats and (not sdk_identity_valid or not profile.is_completed_sdk_result(Path(js), seat)):
                seats_out.append((f"{name}: invalid SDK proof", '')); continue
            dur = minutes(started, mtime(ex)) if started else 0
            seats_out.append((f"{name}: done {findings_count(js)}f {dur}m", ''))
        else:
            seats_out.append((f"{name}: failed exit={code}", ''))
        continue
    if started is None:
        seats_out.append((f"{name}: pending", '')); continue
    act = seat_action(seat, lg)
    seats_out.append((f"{name}: running {minutes(started, now)}m", act))

o = st.get('open') or {}
header = f"r{rnd}/{mn} {phase} | "
tail = f"open P0:{o.get('P0', 0)} P1:{o.get('P1', 0)} P2:{o.get('P2', 0)} fixed {st.get('fixed', 0)}"
# The header and the aggregate tail are never sacrificed; only the seat section flexes.
budget = MAX - len(header) - len(tail) - (len(" | ") if seats_out else 0)

def render(entries, cap):
    return " | ".join(p + (f" \u2190 {a[:cap]}" if a else '') for p, a in entries)

body = ''
if seats_out:
    for cap in (ACTION_MAX, 32, 24, 16, 12, 8):
        body = render(seats_out, cap)
        if len(body) <= budget: break
    else:
        # Still over at the smallest action budget: drop trailing seats for a count marker.
        n = len(seats_out)
        for keep in range(n - 1, -1, -1):
            cand = render(seats_out[:keep], 8)
            mark = f"+{n - keep} seats"
            cand = (cand + " | " + mark) if keep else mark
            body = cand
            if len(cand) <= budget: break

line = header + (body + " | " if seats_out else '') + tail
print(line[:MAX])
PY
