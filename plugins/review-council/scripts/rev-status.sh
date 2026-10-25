#!/bin/bash
# rev-status.sh <session-dir>
# One narrative status line plus compact metrics, from session files only.
# The narrative reports phase, reviewer activity, open P0-P2 findings, fixes, and a recent returned finding.
# Per seat: pending | running <t>m ← <last action> | done <k>f <t>m | failed exit=<c> | dropped
set -u
S=${1:?usage: rev-status.sh <session-dir>}
[ -d "$S" ] || { echo "no session at $S"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
python3 - "$S" "$HERE" <<'PY'
import hashlib, importlib.util, json, os, re, runpy, subprocess, sys, time
from pathlib import Path
S = sys.argv[1]
st = {}
p = os.path.join(S, 'state.json')
if os.path.exists(p):
    try:
        with open(p) as f: st = json.load(f)
    except Exception: st = {}
now = time.time()
context_tools = runpy.run_path(os.path.join(sys.argv[2], 'rev-context.py'))
read_file = context_tools['read_file']
valid_result = context_tools['valid_result']
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

def completed_report(js):
    try:
        raw = read_file(Path(js), optional=True)
    except (OSError, ValueError):
        return 'invalid', None
    if raw is None:
        return 'missing', None
    report = valid_result(raw)
    if report is None:
        return 'invalid', None
    if report['summary'].startswith('INCOMPLETE PROOF'):
        return 'incomplete', report
    return 'complete', report

def plain(value, limit):
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value))
    value = re.sub(r'\s+', ' ', value).replace('|', '/')
    return value.strip()[:limit]

def readable_action(action):
    try:
        data = json.loads(action)
    except (TypeError, ValueError):
        return plain(action, 64)
    if not isinstance(data, dict):
        return plain(action, 64)
    command = data.get('command')
    if isinstance(command, str) and command:
        return plain(command, 64)
    pattern = data.get('pattern')
    path = data.get('path') or data.get('file_path')
    if isinstance(pattern, str) and pattern:
        return plain(f'search {pattern!r}' + (f' in {path}' if path else ''), 64)
    if isinstance(path, str) and path:
        return plain(f'inspect {path}', 64)
    return plain(action, 64)

def last_action(log):
    try:
        with open(log, errors='replace') as f:
            lines = [l.rstrip('\n') for l in f if l.startswith(('exec: ', 'tool_call ', 'done: '))]
    except Exception: return ''
    if not lines: return ''
    l = lines[-1]
    l = re.sub(r'^(exec: |tool_call [^:]*: |done: exit=\S+ )', '', l)
    l = re.sub(r"^/bin/zsh -lc '?", '', l).rstrip("'")
    return readable_action(l)

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
STORY_MAX = 560
ACTION_MAX = 40

seats_out = []          # (prefix, action) -- action is '' when there is none
valid_reports = {}
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
    semantic = context_tools['semantic_rejection_state'](S, rnd, seat)
    if semantic is not None:
        seats_out.append((f"{name}: {semantic}", '')); continue
    if os.path.exists(ex):
        code = open(ex).read().strip()
        if code == '0':
            proof, report = completed_report(js)
            if proof == 'missing':
                seats_out.append((f"{name}: missing result", '')); continue
            if proof == 'invalid':
                seats_out.append((f"{name}: invalid result", '')); continue
            if proof == 'incomplete':
                seats_out.append((f"{name}: incomplete proof", '')); continue
            if seat in sdk_seats and (not sdk_identity_valid or not profile.is_completed_sdk_result(Path(js), seat)):
                seats_out.append((f"{name}: invalid SDK proof", '')); continue
            dur = minutes(started, mtime(ex)) if started else 0
            valid_reports[seat] = report
            seats_out.append((f"{name}: done {len(report['findings'])}f {dur}m", ''))
        else:
            seats_out.append((f"{name}: failed exit={code}", ''))
        continue
    if started is None:
        seats_out.append((f"{name}: pending", '')); continue
    act = seat_action(seat, lg)
    seats_out.append((f"{name}: running {minutes(started, now)}m", act))

o = st.get('open') or {}
header = f"r{rnd}/{mn} {phase} | "
def count(value):
    try: return max(0, int(value or 0))
    except (TypeError, ValueError): return 0

counts = {severity: count(o.get(severity)) for severity in ('P0', 'P1', 'P2')}
fixed = count(st.get('fixed'))
tail = f"open P0:{counts['P0']} P1:{counts['P1']} P2:{counts['P2']} fixed {fixed}"
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

done = sum(': done ' in prefix for prefix, _ in seats_out)
running = [(prefix, action) for prefix, action in seats_out if ': running ' in prefix]
pending = sum(': pending' in prefix for prefix, _ in seats_out)
failed = sum(any(marker in prefix for marker in (
    ': failed ', ': invalid SDK proof', ': missing result', ': invalid result',
    ': incomplete proof', ': semantic rejection', ': invalid semantic rejection')) for prefix, _ in seats_out)
dropped_count = sum(': dropped' in prefix for prefix, _ in seats_out)
open_count = sum(counts.values())
story = [f"Council is in {phase}, round {rnd} of {mn}: {done} of {len(seats_out)} review seats have returned results."]
for prefix, action in running[:2]:
    name = prefix.split(':', 1)[0]
    story.append(f"{name} is still reviewing" +
                 (f"; its last recorded step was {plain(action, 64)}." if action else '.'))
if pending:
    story.append(f"{pending} reviewer seat{'s are' if pending != 1 else ' is'} waiting to start.")
if dropped_count:
    story.append(f"{dropped_count} reviewer seat{'s were' if dropped_count != 1 else ' was'} dropped.")
if failed:
    story.append(f"{failed} reviewer seat{'s have' if failed != 1 else ' has'} failed or returned invalid proof.")
if phase in ('setup', 'discovery', 'fan-out', 'collect') and done:
    story.append(f"Returned findings have not yet been triaged; {open_count} P0-P2 findings are currently recorded as open (P0: {counts['P0']}, P1: {counts['P1']}, P2: {counts['P2']}); {fixed} fixes are recorded.")
elif open_count:
    story.append(f"{open_count} P0-P2 findings are currently recorded as open (P0: {counts['P0']}, P1: {counts['P1']}, P2: {counts['P2']}); {fixed} fixes are recorded.")
else:
    story.append(f"No P0-P2 findings are currently recorded as open; {fixed} fixes are recorded.")

recent = []
for seat, (prefix, _) in zip(seats, seats_out):
    if ': done ' not in prefix:
        continue
    report = valid_reports.get(seat)
    if report is None:
        continue
    stamp = mtime(os.path.join(S, f"r{rnd}-{seat}.json")) or 0
    for finding in report.get('findings', []):
        if finding.get('severity') in ('P0', 'P1', 'P2'):
            recent.append((stamp, finding))
if recent:
    _, finding = max(recent, key=lambda row: row[0])
    claim = plain(finding.get('claim', ''), 100)
    location = plain(finding.get('file', ''), 100)
    line_number = finding.get('line_start')
    if location and isinstance(line_number, int):
        location = f"{location}:{line_number}"
    if claim:
        story.append(f"A recent returned report flags {finding.get('severity')} at {location}: {claim}.")

narrative = ' '.join(story)
if len(narrative) > STORY_MAX:
    narrative = narrative[:STORY_MAX - 3].rstrip() + '...'
print(header + narrative + ' | ' + (body + ' | ' if seats_out else '') + tail)
PY
