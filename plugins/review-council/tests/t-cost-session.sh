test_cost_session_brief_keeps_incomplete_results_visible() {
  local S="$T/cost-session"; mkdir -p "$S"
  printf '%s\n' '{"phase":"collect","round":"2p","min_rounds":"adaptive","seats":["terra","opus"],"open":{"P1":1},"fixed":2}' > "$S/state.json"
  printf '%s\n' '{"seats":[{"seat":"terra","adapter":"codex","model":"gpt-5.6-terra","effort":"max"},{"seat":"opus","adapter":"claude","model":"opus","effort":"max"}]}' > "$S/roster.json"
  printf '0\n' > "$S/r2p-terra.exit"
  printf '%s\n' '{"summary":"INCOMPLETE PROOF: missing source","findings":[]}' > "$S/r2p-terra.json"
  : > "$S/r2p-opus.prompt.md"
  python3 "$SCRIPTS/rev-context.py" "$S" --json > "$T/cost-session.json"
  python3 - "$T/cost-session.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
assert value['round'] == '2p'
assert value['phase'] == 'collect'
assert value['seats'][0]['status'] == 'incomplete-proof', value
assert value['seats'][1]['status'] == 'running', value
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
