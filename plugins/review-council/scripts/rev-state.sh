#!/bin/bash
# rev-state.sh <session-dir> key=value...
# Merge keys into <session>/state.json (created if absent). Dotted keys nest: open.P1=1.
# Values that parse as JSON are stored typed (1, true, null, ["a"], {"x":1}); otherwise as strings.
# phase=plan round=<N>p[2...] (or <root>x[2...]) seats=[...] records plans.<label>.
# plan_replacement_for=<root>:<failed-seat> binds a child to one exact root assignment.
# phase=fix exits 2 with state unchanged while open P0+P1+P2 > 0 unless every plan assignment passed.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
S=${1:?usage: rev-state.sh <session-dir> key=value...}; shift
[ $# -gt 0 ] || { echo "usage: rev-state.sh <session-dir> key=value..." >&2; exit 1; }
mkdir -p "$S"
REV_STATE_EVIDENCE="$HERE/rev-evidence.py" python3 - "$S/state.json" "$@" <<'PY'
import hashlib, json, math, os, re, stat, subprocess, sys

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


def refuse(message):
    print(f"rev-state: {message}", file=sys.stderr)
    sys.exit(2)


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
plan_replacement_for = None
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
    if k == 'plan_replacement_for':
        if k in assigned:
            refuse("'plan_replacement_for' may be supplied only once")
        if not isinstance(val, str):
            refuse("'plan_replacement_for' must be '<N>p:<failed-seat>'")
        plan_replacement_for = val
        assigned.add(k)
        continue
    node = state
    parts = k.split('.')
    for p in parts[:-1]:
        node = node.setdefault(p, {})
        if not isinstance(node, dict):
            print(f"rev-state: '{k}': '{p}' is not an object", file=sys.stderr); sys.exit(1)
    node[parts[-1]] = val
    assigned.add(k)


SEAT_NAME = r'[A-Za-z0-9][A-Za-z0-9._-]*'


def receipt_file(name):
    try:
        info = os.lstat(os.path.join(session, name))
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) and info.st_size > 0 else None


def newest_seat_exit():
    # Newest r<N>x<optional-index>-<seat>.exit mtime, when this round's findings stopped arriving.
    # rev-seat.sh deletes the receipt before every relaunch, so the mtime is this launch's.
    # Plan rounds (r<N>p-) are excluded on purpose: the plan panel runs after triage by
    # design, so counting its exits would refuse every sanctioned triage-plan-fix path.
    newest = 0.0
    try:
        names = os.listdir(session)
    except OSError:
        return newest
    for name in names:
        if not re.fullmatch(rf'r[0-9]+(?:x[0-9]*)?-{SEAT_NAME}\.exit', name):
            continue
        try:
            newest = max(newest, os.lstat(os.path.join(session, name)).st_mtime)
        except OSError:
            continue
    return newest


def plan_manifest(label):
    try:
        with open(os.path.join(session, f'r{label}-evidence.manifest.json'), encoding='utf-8') as f:
            manifest = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (not isinstance(manifest, dict) or manifest.get('label') != label
            or manifest.get('phase') != 'plan' or not isinstance(manifest.get('plan'), dict)):
        return None
    return manifest


def current_plan_sha():
    try:
        with open(os.path.join(session, 'fix-plan.md'), 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def plan_assignment_has_hard_audit_failure(label, seat):
    invalid_name = f'r{label}-{seat}.audit-invalid.json'
    if os.path.lexists(os.path.join(session, invalid_name)):
        return True
    audit_name = f'r{label}-{seat}.read-audit.json'
    audit_path = os.path.join(session, audit_name)
    if not os.path.lexists(audit_path):
        return False
    if not receipt_file(audit_name):
        return True
    try:
        with open(os.path.join(session, audit_name), encoding='utf-8') as f:
            audit = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    return (isinstance(audit, dict) and audit.get('schema_version') == 2
            and audit.get('status') == 'invalid' and audit.get('evidence_scoped') is True)


def plan_assignment_completed(label, seat, manifest=None, current_sha=None):
    manifest = manifest if manifest is not None else plan_manifest(label)
    current_sha = current_sha if current_sha is not None else current_plan_sha()
    if (manifest is None or current_sha is None
            or manifest['plan'].get('sha256') != current_sha
            or not isinstance(manifest.get('assignments'), dict)
            or seat not in manifest['assignments']
            or plan_assignment_has_hard_audit_failure(label, seat)):
        return False
    if not receipt_file(f'r{label}-{seat}.json') or not receipt_file(f'r{label}-{seat}.exit'):
        return False
    try:
        with open(os.path.join(session, f'r{label}-{seat}.exit'), encoding='utf-8', errors='replace') as f:
            if f.read().strip() != '0':
                return False
        with open(os.path.join(session, f'r{label}-{seat}.json'), encoding='utf-8') as f:
            result = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(result, dict) and not str(result.get('summary', '')).startswith('INCOMPLETE PROOF')


def plan_completed(label):
    seats = (state.get('plans') or {}).get(label) if isinstance(state.get('plans'), dict) else None
    if not isinstance(seats, list) or not seats:
        return False
    manifest = plan_manifest(label)
    if (manifest is None or not isinstance(manifest.get('assignments'), dict)
            or set(manifest['assignments']) != set(seats)):
        return False
    if any(not isinstance(seat, str) or not re.fullmatch(SEAT_NAME, seat)
           or not plan_assignment_completed(label, seat, manifest)
           for seat in seats):
        return False
    return True


def parse_plan_label(label):
    match = (re.fullmatch(r'([0-9]+)p([2-9]|[1-9][0-9]+)?(?:x([0-9]*))?', label)
             if isinstance(label, str) else None)
    if match is None:
        return None
    code, generation, child = match.groups()
    if child not in (None, '') and int(child) < 2:
        return None
    return {'code': int(code), 'generation': int(generation or '1'),
            'root': label.split('x', 1)[0], 'child': child}


def valid_plan_label(label):
    return parse_plan_label(label) is not None


def latest_plan_root(number):
    roots = []
    plans = state.get('plans')
    for label in plans if isinstance(plans, dict) else ():
        parsed = parse_plan_label(label)
        if parsed is not None and parsed['child'] is None and parsed['code'] == number:
            roots.append((parsed['generation'], label))
    if not roots:
        return f'{number}p'
    newest = max(generation for generation, _ in roots)
    selected = [label for generation, label in roots if generation == newest]
    if len(selected) != 1:
        refuse(f'refusing phase=fix: ambiguous plan roots for round {number}: '
               + ', '.join(sorted(selected)))
    return selected[0]


def plan_gate_complete(label):
    if plan_completed(label):
        return True
    plans = state.get('plans')
    if not isinstance(plans, dict):
        return False
    original_seats = plans.get(label)
    if not isinstance(original_seats, list) or not original_seats:
        return False
    manifest = plan_manifest(label)
    if (manifest is None or not isinstance(manifest.get('assignments'), dict)
            or set(manifest['assignments']) != set(original_seats)):
        return False
    replacement_map = state.get('plan_replacements', {})
    if not isinstance(replacement_map, dict):
        return False
    replacements = replacement_map.get(label, {})
    if not isinstance(replacements, dict):
        return False
    def successful_child(child):
        parsed = parse_plan_label(child)
        if (parsed is None or parsed['child'] is None or parsed['root'] != label
                or not isinstance(plans.get(child), list) or len(plans[child]) != 1
                or not plan_completed(child)):
            return False
        child_manifest = plan_manifest(child)
        assignment = ((child_manifest or {}).get('assignments') or {}).get(plans[child][0])
        return (isinstance(assignment, dict) and assignment.get('bundle') == 'plan-completeness'
                and assignment.get('scope') == 'full')

    for seat in original_seats:
        if plan_assignment_completed(label, seat, manifest):
            continue
        children = replacements.get(seat)
        if not isinstance(children, list) or not any(successful_child(child) for child in children):
            return False
    return True


def plan_assignment_terminal_failure(label, seat):
    evidence = os.environ.get('REV_STATE_EVIDENCE')
    if not evidence:
        return False
    attempt_script = os.path.join(os.path.dirname(evidence), 'lib', 'rev-attempt.py')
    prompt = os.path.join(session, f'r{label}-{seat}.prompt.md')
    if not os.path.isfile(attempt_script) or not os.path.isfile(prompt):
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('rev_attempt_for_state', attempt_script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from pathlib import Path
        return module.terminal_failure(Path(session), label, seat, Path(prompt))
    except (OSError, ValueError, AttributeError, ImportError):
        return False


def plan_assignment_needs_replacement(label, seat):
    manifest = plan_manifest(label)
    if manifest is None or seat not in (manifest.get('assignments') or {}):
        return False
    current_sha = current_plan_sha()
    if current_sha is None:
        return False
    if manifest['plan'].get('sha256') != current_sha:
        return True
    if plan_assignment_completed(label, seat, manifest, current_sha):
        return False
    return plan_assignment_terminal_failure(label, seat)


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
if 'plan_replacement_for' in assigned and (
        'phase' not in assigned or phase != 'plan' or not {'round', 'seats'} <= assigned):
    refuse("'plan_replacement_for' requires phase=plan with round and seats")
if 'plan_replacement_for' in assigned and not valid_plan_label(state.get('round')):
    refuse("'plan_replacement_for' requires a valid <N>p[2...]x[2...] round label")
if 'phase' in assigned and phase == 'plan' and {'round', 'seats'} <= assigned:
    label, seats = state.get('round'), state.get('seats')
    parsed = parse_plan_label(label)
    if parsed is None and re.match(r'[0-9]+p', str(label)):
        refuse(f'refusing phase=plan round={label}: invalid plan generation or replacement label')
    if parsed is not None:
        if (not isinstance(seats, list) or not seats
                or not all(isinstance(seat, str) and re.fullmatch(SEAT_NAME, seat) for seat in seats)):
            refuse(f"refusing phase=plan round={label}: seats must be a JSON array of seat names, "
                   f"for example 'seats=[\"codex-sol\"]', not {seats!r}")
        plans = state.setdefault('plans', {})
        if not isinstance(plans, dict):
            print("rev-state: 'plans' is not an object", file=sys.stderr); sys.exit(1)
        parent_label = parsed['root']
        if parent_label != label:
            binding = re.fullmatch(r'([^:]+):(' + SEAT_NAME + r')', plan_replacement_for or '')
            if not binding or binding.group(1) != parent_label:
                refuse(f"refusing phase=plan round={label}: replacement labels require "
                       f"plan_replacement_for='{parent_label}:<failed-seat>'")
            failed_seat = binding.group(2)
            parent_seats = plans.get(parent_label)
            if (not isinstance(parent_seats, list) or failed_seat not in parent_seats
                    or len(seats) != 1 or seats[0] == failed_seat):
                refuse(f"refusing phase=plan round={label}: replacement must cover one different seat "
                       f"and bind to an assignment in r{parent_label}")
            if not plan_assignment_needs_replacement(parent_label, failed_seat):
                refuse(f"refusing phase=plan round={label}: original assignment {failed_seat} in "
                       f"r{parent_label} has no terminal failure or stale plan hash")
            replacement_map = state.setdefault('plan_replacements', {})
            if not isinstance(replacement_map, dict):
                refuse("refusing phase=plan: 'plan_replacements' is not an object")
            links = replacement_map.setdefault(parent_label, {})
            if not isinstance(links, dict):
                refuse(f"refusing phase=plan round={label}: replacement mapping is not an object")
            children = links.setdefault(failed_seat, [])
            if not isinstance(children, list) or label in children:
                refuse(f"refusing phase=plan round={label}: duplicate or malformed replacement link")
            children.append(label)
        elif plan_replacement_for is not None:
            refuse(f"refusing phase=plan round={label}: base plan panels cannot name a replacement parent")
        if label in plans and plans[label] != seats:
            refuse(f"refusing phase=plan round={label}: plan label already records different seats")
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
    plan_round = parse_plan_label(state.get('round'))
    code_round = re.fullmatch(r'([0-9]+)(?:x[0-9]*)?', str(state.get('round')))
    code_number = (plan_round['code'] if plan_round is not None
                   else int(code_round.group(1)) if code_round else None)
    if code_number is not None and receipt_file(f'r{code_number}-coverage.receipt.json'):
        number = str(code_number)
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
               "changed. Apply the standing decision: revert the cited review changes and defer "
               f"the originating findings, then record review_origin_ack={tripped[-1]}")
    if total > 0:
        if code_number is None:
            refuse(f"refusing phase=fix: cannot determine the code round from round={state.get('round')!r}; "
                   "set round=<N> before phase=fix")
        label = latest_plan_root(code_number)
        if not plan_gate_complete(label) and not plan_skipped(label):
            refuse(f"refusing phase=fix for round {code_number}: {total} open P0-P2 findings need "
                   f"the plan gate - complete plan panel r{label}, or bind a successful one-seat "
                   f"replacement to each failed or stale assignment with "
                   f"plan_replacement_for={label}:<failed-seat> (phase=plan round=<label>x[2...] "
                   f"\"seats=[...]\", then every covered seat's result JSON and 0 exit), or append a findings.md line "
                   f"'Plan panel r{label} - SKIPPED: <reason>'")
save()
PY
