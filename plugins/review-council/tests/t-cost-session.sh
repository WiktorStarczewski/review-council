test_cost_session_brief_keeps_incomplete_results_visible() {
  local S="$T/cost-session"; mkdir -p "$S"
  printf '%s\n' '{"phase":"fan-out","round":"2p","min_rounds":"adaptive","seats":["terra","opus","sonnet"],"open":{"P1":1},"fixed":2}' > "$S/state.json"
  printf '%s\n' '{"seats":[{"seat":"terra","adapter":"codex","model":"gpt-5.6-terra","effort":"max"},{"seat":"opus","adapter":"claude","model":"opus","effort":"max"},{"seat":"sonnet","adapter":"claude","model":"sonnet","effort":"max"}]}' > "$S/roster.json"
  printf '0\n' > "$S/r2p-terra.exit"
  printf '%s\n' '{"summary":"INCOMPLETE PROOF: missing source","findings":[]}' > "$S/r2p-terra.json"
  : > "$S/r2p-opus.prompt.md"
  : > "$S/r2p-sonnet.prompt.md"
  rc_write_live_launch_marker "$S/r2p-sonnet.started"
  printf 'tool_call shell: rg "started" src\n' > "$S/r2p-sonnet.log"
  python3 "$SCRIPTS/rev-context.py" "$S" --json > "$T/cost-session.json"
  python3 - "$T/cost-session.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
assert value['round'] == '2p'
assert value['phase'] == 'fan-out'
assert value['seats'][0]['status'] == 'incomplete-proof', value
assert value['seats'][1]['status'] == 'pending', value
assert value['seats'][2]['status'] == 'running', value
assert value['seats'][0]['model'] == 'gpt-5.6-terra'
assert value['open'] == {'P1': 1}
assert value['certification'] == 'not evaluated'
assert value['artifacts']['findings'] == 'findings.md'
assert len(json.dumps(value)) < 4096
PY
  assert_eq "brief keeps exact plan label and unfinished obligations" "$?" 0
  rm "$S/r2p-terra.json"
  python3 "$SCRIPTS/rev-context.py" "$S" --json > "$T/cost-session.json"
  assert_grep "exit zero without result remains incomplete" "$T/cost-session.json" 'missing-result'
  printf '%s\n' '{"summary":"sound","findings":[]}' > "$S/r2p-terra.json"
  python3 "$SCRIPTS/rev-context.py" "$S" --json > "$T/cost-session.json"
  assert_grep "valid-shaped result is ready for collection, not certified" "$T/cost-session.json" 'ready-for-collection'
  printf '%s\n' '{"summary":"sound","findings":[{}]}' > "$S/r2p-terra.json"
  python3 "$SCRIPTS/rev-context.py" "$S" --json > "$T/cost-session.json"
  assert_grep "malformed findings never become ready" "$T/cost-session.json" 'invalid-result'
}

test_cost_session_brief_refuses_unsafe_state() {
  local S="$T/cost-session-unsafe"; mkdir -p "$S"
  printf '%s\n' '{"phase":"collect","round":"1","seats":["../../outside"]}' > "$S/state.json"
  assert_exit "brief rejects an artifact-traversing seat" 2 python3 "$SCRIPTS/rev-context.py" "$S" --json
  printf '%s\n' '{"phase":"collect","round":"../1","seats":[]}' > "$S/state.json"
  assert_exit "brief rejects an artifact-traversing label" 2 python3 "$SCRIPTS/rev-context.py" "$S" --json
  rm "$S/state.json"
  printf '%s\n' '{"phase":"done"}' > "$T/outside-state.json"
  ln -s "$T/outside-state.json" "$S/state.json"
  assert_exit "brief rejects a symlinked state" 2 python3 "$SCRIPTS/rev-context.py" "$S" --json
  assert_exit "brief rejects a missing session" 2 python3 "$SCRIPTS/rev-context.py" "$T/no-session" --json
  rm "$S/state.json"
  printf '%s\n' '{"phase":"collect","round":"1","seats":["terra"]}' > "$S/state.json"
  printf '0\n' > "$S/r1-terra.exit"
  ln -s "$T/outside-state.json" "$S/r1-terra.json"
  assert_exit "brief refuses a result outside the session" 2 python3 "$SCRIPTS/rev-context.py" "$S" --json
  printf '%s\n' '{"phase":"collect","phase":"done","seats":[]}' > "$S/state.json"
  assert_exit "brief refuses ambiguous duplicate state keys" 2 python3 "$SCRIPTS/rev-context.py" "$S" --json
}

test_cost_session_watch_preserves_scheduled_relays() {
  python3 - "$SCRIPTS/rev-context.py" "$T/cost-watch" <<'PY'
import contextlib, importlib.util, io, json, sys
from pathlib import Path
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('cost_context', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
session = Path(sys.argv[2]); session.mkdir()
(session/'state.json').write_text(json.dumps({'phase':'collect','round':'1','seats':['terra']}))
clock = [0.0]
def sleep(seconds):
    clock[0] += seconds
    if clock[0] >= 300:
        (session/'r1-terra.exit').write_text('2\n')
stream = io.StringIO()
with patch.object(module.time, 'monotonic', side_effect=lambda:clock[0]), patch.object(module.time, 'sleep', side_effect=sleep), contextlib.redirect_stdout(stream):
    module.watch(session, interval=600, poll_interval=300, duration=1200, json_output=True)
events = [json.loads(line) for line in stream.getvalue().splitlines()]
assert [x['event'] for x in events] == ['initial','changed','scheduled','scheduled'], events
assert events[1]['context']['seats'][0]['status'] == 'failed'
assert events[-1]['elapsed_seconds'] == 1200
assert all(x['context']['certification'] == 'not evaluated' for x in events)
PY
  assert_eq "local watcher emits changes without shifting ten-minute cadence" "$?" 0
}

test_cost_session_watch_stops_on_declared_terminal_state() {
  python3 - "$SCRIPTS/rev-context.py" "$T/cost-watch-terminal" <<'PY'
import contextlib, importlib.util, io, json, sys
from pathlib import Path
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('cost_context_terminal', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
session = Path(sys.argv[2]); session.mkdir()
(session/'state.json').write_text('{"phase":"done","round":"1","seats":["terra"]}')
stream=io.StringIO()
with patch.object(module.time,'sleep') as sleep, contextlib.redirect_stdout(stream):
    module.watch(session, interval=600, poll_interval=1, duration=600, json_output=True)
sleep.assert_not_called()
events=[json.loads(line) for line in stream.getvalue().splitlines()]
assert len(events)==1
assert events[0]['context']['seats'][0]['status']=='pending'
assert events[0]['context']['certification']=='not evaluated'
PY
  assert_eq "declared terminal phase stops watcher without claiming coverage" "$?" 0
  assert_exit "watch refuses zero cadence" 2 python3 "$SCRIPTS/rev-context.py" "$T/cost-watch-terminal" --watch --interval 0
}

test_cost_session_watch_without_duration_runs_until_terminal_state() {
  python3 - "$SCRIPTS/rev-context.py" "$T/cost-watch-unbounded" <<'PY'
import contextlib, importlib.util, io, json, sys
from pathlib import Path
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('cost_context_unbounded', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
session = Path(sys.argv[2]); session.mkdir()
state = {'phase':'collect','round':'1','seats':['terra']}
(session/'state.json').write_text(json.dumps(state))
clock = [0.0]
def sleep(seconds):
    clock[0] += seconds
    if clock[0] >= 1200:
        state['phase'] = 'done'
        (session/'state.json').write_text(json.dumps(state))
stream = io.StringIO()
with patch.object(module.time, 'monotonic', side_effect=lambda:clock[0]), patch.object(module.time, 'sleep', side_effect=sleep), contextlib.redirect_stdout(stream):
    module.watch(session, interval=600, poll_interval=300, json_output=True)
events = [json.loads(line) for line in stream.getvalue().splitlines()]
assert events[-1]['context']['phase'] == 'done', events
assert events[-1]['elapsed_seconds'] == 1200, events
assert [x['event'] for x in events] == ['initial','scheduled','scheduled'], events
PY
  assert_eq "default watcher remains attached beyond ten minutes until terminal state" "$?" 0
}

test_cost_session_watch_uses_narrated_live_status() {
  python3 - "$SCRIPTS/rev-context.py" "$T/cost-watch-narrated" <<'PY'
import contextlib, importlib.util, io, json, os, subprocess, sys
from pathlib import Path
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('cost_context_narrated', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
session = Path(sys.argv[2]); session.mkdir()
(session/'state.json').write_text(json.dumps({
    'phase':'collect','round':'1','min_rounds':1,'seats':['opus'],
    'open':{'P1':1},'fixed':0}))
(session/'r1-opus.prompt.md').write_text('review prompt\n')
pid = os.getpid()
started = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='], capture_output=True,
                         text=True, check=True, env={**os.environ, 'LC_ALL':'C'}).stdout.strip()
(session/'r1-opus.started').write_text(f'cli\n{pid}\n{started}\n')
log = session/'r1-opus.log'
log.write_text('tool_call shell: rg "pair" src/pair.ts\n')
state = json.loads((session/'state.json').read_text())
clock = [0.0]
def sleep(seconds):
    clock[0] += seconds
    if clock[0] >= 5:
        log.write_text('tool_call shell: sed -n 10,20p src/pair.ts\n')
    if clock[0] >= 10:
        (session/'r1-opus.exit').write_text('0\n')
        (session/'r1-opus.json').write_text(json.dumps({
            'summary':'one finding','findings':[{'severity':'P1','file':'src/pair.ts',
        'line_start':14,'line_end':14,'claim':'pair validation is skipped',
                'evidence':'fixture','suggested_fix':'','confidence':0.9}]}))
        state['phase'] = 'done'
        (session/'state.json').write_text(json.dumps(state))
def run_status(args, **kwargs):
    if args and isinstance(args, (list, tuple)) and args[0] == 'ps':
        return subprocess.CompletedProcess(args, 0, started + '\n', '')
    if state['phase'] == 'done':
        status = 'Council is in done; live finding: pair validation is skipped'
    else:
        status = 'live step: ' + log.read_text().split(': ', 1)[1].strip()
    return subprocess.CompletedProcess(args, 0, status + '\n', '')
stream = io.StringIO()
with patch.object(module.subprocess, 'run', side_effect=run_status), \
     patch.object(module.time, 'monotonic', side_effect=lambda:clock[0]), \
     patch.object(module.time, 'sleep', side_effect=sleep), contextlib.redirect_stdout(stream):
    module.watch(session, interval=600, poll_interval=5)
lines = stream.getvalue().splitlines()
assert len(lines) == 3, lines
assert lines[0].startswith('[initial 0s]') and 'rg "pair" src/pair.ts' in lines[0], lines
assert lines[1].startswith('[changed 5s]') and 'sed -n 10,20p src/pair.ts' in lines[1], lines
output = lines[-1]
assert 'Council is in done' in output, output
assert 'pair validation is skipped' in output, output
PY
  assert_eq "scheduled watcher uses the live narration and returned finding" "$?" 0
}
