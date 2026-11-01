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
    return plan_assignment_failures(label) == []


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


def stable_receipt_bytes(name):
    path = os.path.join(session, name)
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            return None
        with open(path, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read()
        after = os.lstat(path)
    except OSError:
        return None
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_nlink)
    if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(after.st_mode)
            or identity(before) != identity(opened) or identity(opened) != identity(after)
            or len(raw) != after.st_size):
        return None
    return raw


def plan_prepare_failed(label):
    raw = stable_receipt_bytes(f'prepare-diagnostic-{label}.json')
    if raw is None:
        return False
    try:
        diagnostic = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return False
    return (isinstance(diagnostic, dict)
            and type(diagnostic.get('schema_version')) is int
            and diagnostic['schema_version'] == 1
            and diagnostic.get('kind') == 'prepare-diagnostic'
            and diagnostic.get('certifying') is False
            and diagnostic.get('label') == label
            and diagnostic.get('phase') == 'plan'
            and isinstance(diagnostic.get('stage'), str) and bool(diagnostic['stage'].strip())
            and type(diagnostic.get('timed_out')) is bool
            and isinstance(diagnostic.get('error'), str) and bool(diagnostic['error'].strip())
            and isinstance(diagnostic.get('refusals'), list))


def plan_assignment_failures(label):
    plans = state.get('plans')
    if not isinstance(plans, dict):
        return None
    original_seats = plans.get(label)
    if (not isinstance(original_seats, list) or not original_seats
            or any(not isinstance(seat, str) or not re.fullmatch(SEAT_NAME, seat)
                   for seat in original_seats)
            or len(set(original_seats)) != len(original_seats)):
        return None
    manifest_bytes = stable_receipt_bytes(f'r{label}-evidence.manifest.json')
    current_plan = stable_receipt_bytes('fix-plan.md')
    if manifest_bytes is None or current_plan is None:
        return None
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return None
    current_sha = hashlib.sha256(current_plan).hexdigest()
    if (not isinstance(manifest, dict) or manifest.get('label') != label
            or manifest.get('phase') != 'plan' or not isinstance(manifest.get('plan'), dict)
            or not isinstance(manifest.get('assignments'), dict)
            or set(manifest['assignments']) != set(original_seats)):
        return None
    replacement_map = state.get('plan_replacements', {})
    if not isinstance(replacement_map, dict):
        return None
    replacements = replacement_map.get(label, {})
    if (not isinstance(replacements, dict)
            or not set(replacements) <= set(original_seats)):
        return None
    mapped_children = set()
    failures = []
    for seat in original_seats:
        children = replacements.get(seat, [])
        if (not isinstance(children, list)
                or any(not isinstance(child, str) for child in children)
                or len(set(children)) != len(children)):
            return None
        child_success = False
        for child in children:
            if child in mapped_children:
                return None
            parsed = parse_plan_label(child)
            child_seats = plans.get(child)
            child_manifest_raw = stable_receipt_bytes(f'r{child}-evidence.manifest.json')
            if child_manifest_raw is None:
                child_seat = child_seats[0] if isinstance(child_seats, list) and len(child_seats) == 1 else None
                if (parsed is None or parsed['child'] is None or parsed['root'] != label
                        or not isinstance(child_seat, str)
                        or os.path.lexists(os.path.join(session, f'r{child}-evidence.manifest.json'))
                        or not plan_prepare_failed(child)
                        or any(os.path.lexists(os.path.join(session, f'r{child}-{child_seat}{suffix}'))
                               for suffix in ('.prompt.md', '.json', '.exit', '.audit-invalid.json',
                                              '.read-audit.json'))):
                    return None
                mapped_children.add(child)
                continue
            try:
                child_manifest = json.loads(child_manifest_raw)
            except (UnicodeError, json.JSONDecodeError, RecursionError):
                return None
            if (parsed is None or parsed['child'] is None or parsed['root'] != label
                    or not isinstance(child_seats, list) or len(child_seats) != 1
                    or not isinstance(child_seats[0], str)
                    or not isinstance(child_manifest, dict)
                    or child_manifest.get('label') != child
                    or child_manifest.get('phase') != 'plan'
                    or not isinstance(child_manifest.get('plan'), dict)
                    or child_manifest['plan'].get('sha256') != current_sha
                    or not isinstance(child_manifest.get('assignments'), dict)):
                return None
            if os.path.lexists(os.path.join(session, f'prepare-diagnostic-{child}.json')):
                return None
            child_seat = child_seats[0]
            child_assignment = child_manifest['assignments'].get(child_seat)
            if (set(child_manifest['assignments']) != {child_seat}
                    or not isinstance(child_assignment, dict)
                    or child_assignment.get('bundle') != 'plan-completeness'
                    or child_assignment.get('scope') != 'full'):
                return None
            mapped_children.add(child)
            if plan_assignment_completed(child, child_seat, child_manifest, current_sha):
                child_success = True
            elif not plan_assignment_terminal_failure(child, child_seat):
                return None
        original_complete = plan_assignment_completed(label, seat, manifest, current_sha)
        if original_complete or child_success:
            continue
        if not plan_assignment_terminal_failure(label, seat):
            return None
        failures.append(seat)

    for child, seats in plans.items():
        parsed = parse_plan_label(child)
        if (parsed is not None and parsed['child'] is not None and parsed['root'] == label
                and child not in mapped_children):
            return None
    return failures


def manual_plan_review_complete(label):
    raw = stable_receipt_bytes(f'r{label}-manual-plan-review.json')
    manifest_raw = stable_receipt_bytes(f'r{label}-evidence.manifest.json')
    plan_raw = stable_receipt_bytes('fix-plan.md')
    failures = plan_assignment_failures(label)
    if raw is None or manifest_raw is None or plan_raw is None or not failures:
        return False
    try:
        review = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return False
    fields = {'schema_version', 'plan_label', 'plan_sha256', 'manifest_sha256',
              'reviewed_assignments', 'failed_assignments', 'escalation_exhausted',
              'decision', 'summary', 'contract_checks'}
    plans = state.get('plans')
    seats = plans.get(label) if isinstance(plans, dict) else None
    expected_checks = {'required_cluster_fields', 'bounded_site_search_and_path_accounting',
                       'falsifiable_tests_and_predictions', 'authorized_scope_preserved',
                       'objections_resolved'}
    if (not isinstance(review, dict) or set(review) != fields
            or type(review.get('schema_version')) is not int or review['schema_version'] != 1
            or review.get('plan_label') != label
            or review.get('plan_sha256') != hashlib.sha256(plan_raw).hexdigest()
            or review.get('manifest_sha256') != hashlib.sha256(manifest_raw).hexdigest()
            or not isinstance(seats, list)
            or not isinstance(review.get('reviewed_assignments'), list)
            or any(not isinstance(seat, str) for seat in review['reviewed_assignments'])
            or len(set(review['reviewed_assignments'])) != len(review['reviewed_assignments'])
            or set(review['reviewed_assignments']) != set(seats)
            or not isinstance(review.get('failed_assignments'), list)
            or any(not isinstance(seat, str) for seat in review['failed_assignments'])
            or len(set(review['failed_assignments'])) != len(review['failed_assignments'])
            or set(review['failed_assignments']) != set(failures)
            or review.get('escalation_exhausted') is not True
            or review.get('decision') != 'accepted'
            or not isinstance(review.get('summary'), str) or not review['summary'].strip()
            or not isinstance(review.get('contract_checks'), dict)
            or set(review['contract_checks']) != expected_checks
            or any(value is not True for value in review['contract_checks'].values())):
        return False
    return True


def plan_skipped(label):
    prefix = f'Plan panel r{label} - SKIPPED:'
    ledger = os.path.join(session, 'findings.md')
    if not os.path.isfile(ledger):
        return False
    with open(ledger, encoding='utf-8', errors='replace') as f:
        recorded = any(line.startswith(prefix) and line[len(prefix):].strip() for line in f)
    manifest = plan_manifest(label)
    current_sha = current_plan_sha()
    return (recorded and manifest is not None and current_sha is not None
            and manifest['plan'].get('sha256') == current_sha)


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
            if any(not isinstance(existing, list) for existing in links.values()):
                refuse(f"refusing phase=plan round={label}: replacement mapping contains malformed links")
            if any(label in existing for existing in links.values()):
                refuse(f"refusing phase=plan round={label}: replacement is already bound to another assignment")
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
        if (not plan_gate_complete(label) and not plan_skipped(label)
                and not manual_plan_review_complete(label)):
            refuse(f"refusing phase=fix for round {code_number}: {total} open P0-P2 findings need "
                   f"the plan gate - complete plan panel r{label}, or bind a successful one-seat "
                   f"replacement to each failed or stale assignment with "
                   f"plan_replacement_for={label}:<failed-seat> (phase=plan round=<label>x[2...] "
                   f"\"seats=[...]\", then every covered seat's result JSON and 0 exit), or append a findings.md line "
                   f"'Plan panel r{label} - SKIPPED: <reason>', or record an accepted, full-scope "
                   f"manual review in r{label}-manual-plan-review.json after the eligible chain is exhausted")
save()
PY
