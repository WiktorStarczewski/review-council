#!/usr/bin/env python3
"""Choose and launch the cheap workhorse for fix plans, plan review, and implementation.

The session model orchestrates. The workhorse writes every fix plan. The
session implements a local cluster (one file, at most 3 sites, no new
mechanism, realm, or public contract). The default writer for every other
cluster is `grok-4.7-xhigh` through the Cursor agent CLI, on every host. If
it is missing, not signed in, or out of credits, the writer falls through
OpenAI Luna, then Anthropic Sonnet, then OpenAI Sol, then Anthropic Opus.
Frontier review seats stay on the roster.
"""
import json
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

LIB = Path(__file__).resolve().parent
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from roster import (AUTH_FAILURE, CLAUDE_SESSION_ENV, QUOTA_FAILURE, claude_cli_reason,
                    codex_catalog, codex_catalog_path, codex_suffix, reasoning_efforts)

HOSTS = ('claude', 'codex', 'cursor')
CHAIN = ('luna', 'sonnet', 'sol', 'opus')
ORDER = ('cursor-grok',) + CHAIN
FAMILIES = ORDER
SEAT = 'workhorse'
LABS = {'cursor-grok': 'cursor', 'luna': 'openai', 'sol': 'openai',
        'sonnet': 'anthropic', 'opus': 'anthropic'}
ADAPTERS = {'cursor-grok': ('cursor-agent',), 'luna': ('codex',), 'sol': ('codex',),
            'sonnet': ('claude', 'agent'), 'opus': ('claude', 'agent')}
LUNA_EFFORTS = ('high', 'xhigh', 'max')
SONNET_MODEL = 'sonnet'
SONNET_EFFORT = 'high'
ENFORCED_ADAPTERS = ('codex', 'claude')
WRITER_GROK_MODEL = 'grok-4.7-xhigh'
WRITER_GROK_EFFORT = 'xhigh'
CURSOR_BLOCK = re.compile(
    r'payment required|spend limit|rate_limit|usage_limit|hit_hard_limit',
    re.IGNORECASE)
CLUSTER_ID = re.compile(r'^C-[A-Za-z0-9][A-Za-z0-9-]*$')
ABSENT_KEYS = {'version', 'host', 'family', 'available', 'reason'}
SELECTED_KEYS = ABSENT_KEYS | {'lab', 'seat', 'adapter', 'model', 'effort'}
INLINE_LIMIT = 200_000
AGENTS = {
    'plan': 'review-council:rev-workhorse',
    'implement': 'review-council:rev-workhorse',
    'review': 'review-council:rev-workhorse-review',
}


def host_name(value=None):
    host = value or os.environ.get('REVIEW_COUNCIL_HOST') or 'claude'
    if host not in HOSTS:
        raise ValueError('unknown review-council host: ' + host)
    return host


def order_for(host):
    """Every host tries Cursor Grok, then Luna, Sonnet, Sol, and Opus.

    Review replacement still walks this order and skips Cursor Grok, because a
    repair executor has to be an enforced seat.
    """
    host_name(host)
    return ORDER


def families_after(host, family):
    order = order_for(host)
    key = 'cursor-grok' if family in ('grok', 'cursor-grok') else family
    if key == 'cursor-grok' and key not in order:
        return order
    if key not in order:
        raise ValueError('unknown chain family: ' + str(family))
    return order[order.index(key) + 1:]


def select_codex_family(listed, family):
    """Newest visible model of one Codex family at high, else xhigh, else max."""
    matches = [(gen, model, slug) for gen, model, slug in listed if codex_suffix(slug) == family]
    if not matches:
        return None
    newest = max(gen for gen, _, _ in matches)
    model, slug = next((model, slug) for gen, model, slug in matches if gen == newest)
    levels = reasoning_efforts(model.get('supported_reasoning_levels'))
    effort = next((name for name in LUNA_EFFORTS if name in levels), None)
    if effort is None:
        return None
    return slug, effort


def select_luna(listed):
    """Newest visible Luna at high, else xhigh, else max. `listed` is codex_catalog's list."""
    return select_codex_family(listed, 'luna')


def select_sol(listed):
    return select_codex_family(listed, 'sol')


def select_cursor_grok(text):
    """Writer Grok is exactly grok-4.7-xhigh. Other Grok slugs do not qualify."""
    if not isinstance(text, str) or not text.strip():
        return None
    for line in text.splitlines():
        slug = line.split(' - ', 1)[0].strip()
        if slug == WRITER_GROK_MODEL:
            return WRITER_GROK_MODEL, WRITER_GROK_EFFORT
    return None


def claude_candidate(host, cli_reason, model):
    """Claude can run Opus or Sonnet without the CLI. Other hosts need the CLI."""
    if host == 'claude':
        return {'adapter': 'claude' if cli_reason is None else 'agent',
                'model': model, 'effort': SONNET_EFFORT}
    if cli_reason is None:
        return {'adapter': 'claude', 'model': model, 'effort': SONNET_EFFORT}
    return None


def sonnet_candidate(host, cli_reason):
    return claude_candidate(host, cli_reason, SONNET_MODEL)


def opus_candidate(host, cli_reason):
    return claude_candidate(host, cli_reason, 'opus')


def _record(host, family, available, **fields):
    document = {
        'version': 1,
        'host': host,
        'family': family,
        'available': [name for name in order_for(host) if name in available],
        'reason': ('host %s; no workhorse available' % host if family is None
                   else 'host %s; selected %s' % (host, family)),
    }
    document.update(fields)
    if family is not None:
        document.update(lab=LABS[family], seat=SEAT)
    validate_record(document)
    return document


def resolve_available(host, luna=None, sonnet=None, cursor_grok=None, sol=None, opus=None):
    """Pick the first family on the writer chain that was supplied.

    Every host starts at Cursor Grok, then Luna, Sonnet, Sol, and Opus.
    `luna`, `sol`, and `cursor_grok` are `(model, effort)` or None.
    `sonnet` and `opus` are candidate dicts or None. A missing Cursor Grok
    candidate is the not-installed and not-signed-in case; credit exhaustion
    is a launch failure and advances past the current family.
    """
    host = host_name(host)
    present = {}
    if luna is not None:
        present['luna'] = {'adapter': 'codex', 'model': luna[0], 'effort': luna[1]}
    if sol is not None:
        present['sol'] = {'adapter': 'codex', 'model': sol[0], 'effort': sol[1]}
    if sonnet is not None:
        present['sonnet'] = dict(sonnet)
    if opus is not None:
        present['opus'] = dict(opus)
    if cursor_grok is not None:
        present['cursor-grok'] = {'adapter': 'cursor-agent', 'model': cursor_grok[0],
                                   'effort': cursor_grok[1]}
    for family in order_for(host):
        if family in present:
            return _record(host, family, present, **present[family])
    return _record(host, None, present)


def validate_record(document):
    if not isinstance(document, dict):
        raise ValueError('workhorse record must be an object')
    family = document.get('family')
    keys = SELECTED_KEYS if family is not None else ABSENT_KEYS
    if set(document) != keys or document.get('version') != 1:
        raise ValueError('invalid workhorse record')
    host = document.get('host')
    if host not in HOSTS or not isinstance(document.get('reason'), str) or not document['reason']:
        raise ValueError('invalid workhorse host')
    available = document.get('available')
    if (not isinstance(available, list) or len(available) != len(set(available))
            or any(name not in ORDER for name in available)):
        raise ValueError('invalid workhorse availability')
    if family is None:
        if available:
            raise ValueError('an unavailable workhorse listed a family')
        return document
    if family not in ORDER or family not in available:
        raise ValueError('selected workhorse is not available')
    if (document.get('lab') != LABS[family] or document.get('seat') != SEAT
            or document.get('adapter') not in ADAPTERS[family]):
        raise ValueError('workhorse identity does not match its family')
    model, effort = document.get('model'), document.get('effort')
    if (not isinstance(model, str) or not model.strip() or model != model.strip()
            or len(model) > 120 or not isinstance(effort, str)):
        raise ValueError('invalid workhorse model')
    if family in ('luna', 'sol'):
        if codex_suffix(model) != family or effort not in LUNA_EFFORTS:
            raise ValueError('invalid %s workhorse' % family)
    elif family in ('sonnet', 'opus'):
        if model != family or effort != SONNET_EFFORT:
            raise ValueError('invalid %s workhorse' % family)
    elif model != WRITER_GROK_MODEL or effort != WRITER_GROK_EFFORT:
        raise ValueError('invalid cursor-grok workhorse')
    return document


def read_record(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('unreadable workhorse record') from error
    return validate_record(document)


def plan_seat(session):
    """Seat row for a plan panel, or None when no workhorse was selected."""
    document = read_record(Path(session) / 'workhorse.json')
    if document is None or document.get('family') is None:
        return None
    return seat_row(document)


def seat_row(document):
    validate_record(document)
    if document.get('family') is None:
        return None
    return {'seat': document['seat'], 'lab': document['lab'], 'adapter': document['adapter'],
            'model': document['model'], 'effort': document['effort'], 'extra': False}


def roster_family(row):
    """Chain family of a roster or escalation seat, or None when it is not on the chain."""
    if not isinstance(row, dict):
        return None
    adapter = row.get('adapter')
    model = row.get('model')
    if adapter == 'cursor-sdk' or (
            adapter == 'cursor-agent' and model == WRITER_GROK_MODEL):
        return 'cursor-grok'
    if adapter == 'codex' and isinstance(model, str) and codex_suffix(model) in ('luna', 'sol'):
        return codex_suffix(model)
    if adapter in ('claude', 'agent') and model in ('sonnet', 'opus'):
        return model
    return None


def choose_escalation(host, family, roster_rows, candidates, target_family=None):
    """Next enforced family on this host's chain, preferring a seat already on the roster.

    `candidates` maps a family to a launch spec or None. Agent-only specs are
    skipped: a repair executor has to be an enforced seat. Returns `(row, existing)`.
    """
    rows = roster_rows if isinstance(roster_rows, list) else []
    specs = candidates if isinstance(candidates, dict) else {}
    remaining = families_after(host, family)
    if target_family is not None:
        if target_family not in remaining:
            raise ValueError('requested escalation family is not higher than ' + family)
        remaining = [target_family]
    for nxt in remaining:
        for row in rows:
            if not isinstance(row, dict) or row.get('extra'):
                continue
            if roster_family(row) != nxt or row.get('adapter') not in ENFORCED_ADAPTERS:
                continue
            return dict(row), True
        spec = specs.get(nxt)
        if not isinstance(spec, dict) or spec.get('adapter') not in ENFORCED_ADAPTERS:
            continue
        return {
            'version': 1,
            'seat': 'escalate-' + nxt,
            'family': nxt,
            'lab': spec['lab'],
            'adapter': spec['adapter'],
            'model': spec['model'],
            'effort': spec['effort'],
            'extra': False,
        }, False
    if target_family is not None:
        raise ValueError('requested escalation family is unavailable: ' + target_family)
    return None


def read_escalation(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('unreadable escalation record') from error
    if not isinstance(document, dict):
        raise ValueError('unreadable escalation record')
    family = document.get('family')
    if (document.get('version') != 1 or family not in CHAIN
            or document.get('seat') != 'escalate-' + family
            or document.get('lab') != LABS[family]
            or document.get('adapter') not in ENFORCED_ADAPTERS
            or document.get('adapter') not in ADAPTERS[family]
            or document.get('extra') is not False):
        raise ValueError('invalid escalation record')
    model, effort = document.get('model'), document.get('effort')
    if family in ('luna', 'sol'):
        if not isinstance(model, str) or codex_suffix(model) != family or effort not in LUNA_EFFORTS:
            raise ValueError('invalid escalation record')
    elif model != family or effort != SONNET_EFFORT:
        raise ValueError('invalid escalation record')
    return document


def escalation_row(session):
    document = read_escalation(Path(session) / 'escalation.json')
    if document is None:
        return None
    return {'seat': document['seat'], 'lab': document['lab'], 'adapter': document['adapter'],
            'model': document['model'], 'effort': document['effort'], 'extra': False}


def _roster_document(path):
    try:
        document = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('unreadable roster') from error
    if not isinstance(document, dict):
        raise ValueError('unreadable roster')
    return document


def _clear_escalation(session):
    path = Path(session) / 'escalation.json'
    if path.exists():
        path.unlink()


def escalation_override(session, family):
    """Return the per-review target family for a failed family, if configured."""
    path = Path(session) / 'state.json'
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('unreadable review state') from error
    overrides = state.get('escalation_overrides', {}) if isinstance(state, dict) else None
    if not isinstance(overrides, dict):
        raise ValueError('invalid escalation_overrides in review state')
    if any(not isinstance(source, str) or source not in CHAIN
           or not isinstance(target, str) or target not in CHAIN
           for source, target in overrides.items()):
        raise ValueError('invalid escalation_overrides in review state')
    target = overrides.get(family)
    return target


def record_quota_disabled_escalation(session, panel, failed_seat, replacement_seat):
    attempt_path = Path(__file__).resolve().with_name('rev-attempt.py')
    spec = importlib.util.spec_from_file_location('rev_attempt_for_escalation', attempt_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.record_quota_disabled_escalation(
        Path(session), panel, failed_seat, replacement_seat)


def escalate(session, seat, panel=None):
    """Write the next enforced chain seat for a review seat that failed twice.

    An existing core seat of that family is reused and any stale escalation file
    is removed. A family that cannot launch is skipped. The chain ends at Opus.
    Cursor Grok is not a review replacement and this path does not probe it.
    """
    session = Path(session)
    document = _roster_document(session / 'roster.json')
    rows = [row for row in document.get('seats') or [] if isinstance(row, dict)]
    matched = next((row for row in rows if row.get('seat') == seat), None)
    if matched is None:
        prior = read_escalation(session / 'escalation.json')
        if prior is not None and prior.get('seat') == seat:
            matched = prior
    if matched is None:
        raise ValueError('no seat %s' % seat)
    family = roster_family(matched)
    if family is None:
        raise ValueError('seat has no chain family: ' + seat)
    host = host_name()
    record_path = session / 'workhorse.json'
    if record_path.is_file():
        host = read_record(record_path)['host']
    _chosen, candidates = _candidates(host, include_cursor=False)
    target_family = escalation_override(session, family)
    chosen = choose_escalation(host, family, rows, candidates, target_family)
    if chosen is None:
        _clear_escalation(session)
        raise ValueError('normal chain is exhausted')
    spec, existing = chosen
    if panel is not None:
        status = record_quota_disabled_escalation(session, panel, seat, spec['seat'])
        if status == 1:
            raise ValueError('cannot bind the quota-disabled exit-4 escalation to this panel')
    if existing:
        _clear_escalation(session)
        return {'seat': spec['seat'], 'family': roster_family(spec), 'existing': True}
    spec = dict(spec)
    spec['substitutes_for'] = seat
    path = session / 'escalation.json'
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(spec, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(temporary, path)
    return {'seat': spec['seat'], 'family': spec['family'], 'existing': False, 'wrote': str(path)}


def advance(session):
    """Move the workhorse to the next family on this host's chain that can launch."""
    session = Path(session)
    current = read_record(session / 'workhorse.json')
    if current is None or current.get('family') is None:
        raise ValueError('no workhorse to advance')
    host = current['host']
    _chosen, candidates = _candidates(host)
    later = set(families_after(host, current['family']))
    picked = {}
    for family in order_for(host):
        if family not in later:
            continue
        spec = candidates.get(family)
        if not isinstance(spec, dict):
            continue
        if family in ('luna', 'sol', 'cursor-grok'):
            picked[family] = (spec['model'], spec['effort'])
        else:
            picked[family] = {'adapter': spec['adapter'], 'model': spec['model'],
                              'effort': spec['effort']}
    record = resolve_available(
        host, luna=picked.get('luna'), sol=picked.get('sol'),
        cursor_grok=picked.get('cursor-grok'), sonnet=picked.get('sonnet'),
        opus=picked.get('opus'))
    if record.get('family') is None:
        raise ValueError('normal chain is exhausted')
    return write_record(session / 'workhorse.json', record, refresh=True)


def lookup_launch(roster_path, seat):
    """Roster row, or the workhorse or chain-escalation row when that seat is not on it."""
    path = Path(roster_path)
    document = _roster_document(path)
    matched = None
    for row in document.get('seats') or []:
        if isinstance(row, dict) and row.get('seat') == seat:
            matched = row
            break
    record = None
    workhorse_path = path.parent / 'workhorse.json'
    if matched is None or seat == SEAT:
        record = read_record(workhorse_path) if workhorse_path.is_file() else None
    if matched is not None:
        if record is not None and record.get('seat') == seat:
            wanted = seat_row(record)
            if any(matched.get(key) != wanted[key] for key in ('adapter', 'model', 'effort')):
                raise ValueError('workhorse seat collides with a roster seat')
        return matched
    if record is not None and record.get('seat') == seat:
        return seat_row(record)
    escalation = read_escalation(path.parent / 'escalation.json')
    if escalation is not None and escalation.get('seat') == seat:
        return escalation_row(path.parent)
    raise ValueError('no seat %s' % seat)


def lookup_adapter(roster_path, seat):
    row = lookup_launch(roster_path, seat)
    adapter = row.get('adapter')
    if not isinstance(adapter, str) or not adapter:
        raise ValueError('seat %s has no adapter' % seat)
    return adapter


def overlay_roster(roster, row, seats_in_play):
    """Append the workhorse only when this plan panel actually seats it.

    Code panels and `plan_seats: all` keep the frozen core roster. A name collision
    with a different identity is a hard error.
    """
    if row is None:
        return roster
    if not isinstance(seats_in_play, (list, tuple, set)) or row['seat'] not in seats_in_play:
        return roster
    if not isinstance(roster, dict) or not isinstance(roster.get('seats'), list):
        raise ValueError('invalid roster shape')
    for existing in roster['seats']:
        if not isinstance(existing, dict) or existing.get('seat') != row['seat']:
            continue
        if any(existing.get(key) != row[key] for key in ('adapter', 'model', 'effort', 'extra')):
            raise ValueError('workhorse seat collides with a roster seat')
        return roster
    overlaid = dict(roster)
    overlaid['seats'] = list(roster['seats']) + [row]
    return overlaid


def scope_value(session, key):
    path = Path(session) / 'scope.env'
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as error:
        raise ValueError('unreadable scope.env') from error
    prefix = key + '='
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        raw = line[len(prefix):]
        try:
            values = shlex.split(raw)
        except ValueError as error:
            raise ValueError('unsafe scope.env value: ' + key) from error
        if len(values) == 1:
            return values[0]
        raise ValueError('unsafe scope.env value: ' + key)
    raise ValueError('missing scope.env value: ' + key)


def _read_capped(path):
    file = Path(path)
    if not file.is_file():
        return None
    raw = file.read_bytes()
    if len(raw) > INLINE_LIMIT:
        return None
    return raw.decode('utf-8')


def prompt_text(record, task, root, session, cluster=None, findings=None, plan=None):
    identity = '%s %s at %s' % (record['family'], record['model'], record['effort'])
    header = (
        'You are the Review Council workhorse (%s). The session model is the orchestrator. '
        'Do not invoke review-council, /rev, /review-council:stack, or another model. '
        'Do not commit, push, amend, or rewrite history.\n\n' % identity)
    if task == 'plan':
        findings_block = findings if isinstance(findings, str) and findings else (
            'Read %s/findings.md.' % session)
        return header + (
            'Write the fix plan for the accepted findings. Repository: %s. '
            'Search it; do not edit it. The entire final message is the plan markdown, '
            'starting with a `## C-...` heading, with no preamble and no code fence.\n\n'
            'Each cluster has Findings, Rule, Sites, Prediction, and one of Test, Tests, '
            'or Regression. Sites includes one search in either exact form, and the replay '
            'of that search must stay under 80 lines:\n'
            "`found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'PATTERN' .`\n"
            "or `found by: grep --exclude-dir=.git --null -r -n -- 'PATTERN' .`.\n"
            'Every path that search finds is named under Sites, under a test field, or as '
            '`Excluded: <path> - <reason>`.\n\n'
            'Accepted findings:\n%s\n' % (root, findings_block))
    if task == 'implement':
        if not isinstance(cluster, str) or CLUSTER_ID.match(cluster) is None:
            raise ValueError('implement requires a plan cluster id')
        plan_block = plan if isinstance(plan, str) and plan else (
            'Read %s/fix-plan.md.' % session)
        return header + (
            'Implement only cluster %s in %s. Edit every site that cluster names and nothing '
            'it does not name. Match the surrounding style. Do not reformat untouched code. '
            'The final message is one short paragraph of what changed.\n\n'
            'Fix plan:\n%s\n' % (cluster, root, plan_block))
    raise ValueError('unknown workhorse task')


def strip_fence(text):
    body = text.strip()
    if body.startswith('```'):
        lines = body.splitlines()
        if lines and lines[-1].strip() == '```':
            body = '\n'.join(lines[1:-1]).strip()
    return body


def plan_markdown(text):
    body = strip_fence(text)
    if not body.startswith('## '):
        raise ValueError('workhorse plan did not start with a cluster heading')
    return body + '\n'


def findings_json(text):
    body = strip_fence(text)
    try:
        json.loads(body)
        chosen = body
    except json.JSONDecodeError:
        start, end = body.find('{'), body.rfind('}')
        if start < 0 or end <= start:
            raise ValueError('workhorse review did not return findings JSON') from None
        chosen = body[start:end + 1]
        json.loads(chosen)
    return chosen if chosen.endswith('\n') else chosen + '\n'


def launch_spec(record, task, root, session, prompt_path, cluster=None, out=None):
    validate_record(record)
    if record.get('family') is None:
        raise ValueError('no workhorse to launch')
    session = str(Path(session))
    root = str(Path(root))
    prompt_path = str(Path(prompt_path))
    adapter = record['adapter']
    if task not in ('plan', 'implement', 'review'):
        raise ValueError('unknown workhorse task')
    if task == 'implement' and CLUSTER_ID.match(cluster or '') is None:
        raise ValueError('implement requires a plan cluster id')
    if task == 'review' and adapter in ('codex', 'claude'):
        raise ValueError('review on %s launches through rev-seat.sh' % adapter)
    if adapter == 'agent':
        return {'kind': 'agent', 'agent': AGENTS[task], 'model': record['model'],
                'effort': record['effort'], 'prompt': prompt_path, 'task': task,
                'cluster': cluster}
    if task == 'review' and out is None:
        raise ValueError('review launch requires --out')
    stdin = prompt_path
    if adapter == 'codex':
        argv = ['codex', 'exec', '--ephemeral', '--ignore-user-config', '-s', 'workspace-write',
                '-C', root, '--add-dir', session, '-m', record['model'],
                '-c', 'model_reasoning_effort=%s' % record['effort'],
                '-c', 'project_doc_max_bytes=0']
    elif adapter == 'claude':
        tools = 'Read,Grep' if task == 'review' else 'Read,Grep,Write,Edit,Bash'
        argv = ['claude', '-p', '--model', record['model'], '--effort', record['effort'],
                '--permission-mode', 'bypassPermissions', '--tools', tools,
                '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
                '--exclude-dynamic-system-prompt-sections', '--disable-slash-commands',
                '--output-format', 'text']
    else:
        argv = ['agent', '--print', '--trust', '--workspace', root, '--add-dir', session,
                '--model', record['model'], '--output-format', 'text']
        if task == 'implement':
            argv.extend(['--sandbox', 'disabled'])
        elif task == 'review':
            argv.extend(['--mode', 'ask', '--sandbox', 'enabled'])
        else:
            argv.extend(['--sandbox', 'enabled'])
        argv.append('Read %s and follow it exactly.' % prompt_path)
        stdin = None
    destination = out
    if task == 'plan':
        destination = destination or str(Path(session) / 'fix-plan.md')
    elif task == 'implement':
        destination = destination or str(Path(session) / ('workhorse-implement-%s.log' % cluster))
    return {'kind': 'exec', 'argv': argv, 'stdin': stdin, 'cwd': root, 'out': destination,
            'task': task, 'adapter': adapter, 'model': record['model'], 'effort': record['effort'],
            'prompt': prompt_path}


def _cursor_binary():
    return shutil.which('agent') or shutil.which('cursor-agent')


def _blocked_text(text):
    return bool(text and (AUTH_FAILURE.search(text) or QUOTA_FAILURE.search(text)
                          or CURSOR_BLOCK.search(text)))


def cursor_writer_blocked(returncode, stdout, stderr):
    """A failed Cursor agent run that is unsigned-in or out of credits.

    A zero exit is a finished writer result. A long stdout is the writer's
    own text, so a quoted limit in it does not retire the family. Stderr and
    a short stdout banner still do.
    """
    if returncode == 0:
        return False
    if _blocked_text(stderr):
        return True
    banner = (stdout or '').strip()
    if len(banner) > 4000 or banner.startswith('## ') or banner.startswith('{'):
        return False
    return _blocked_text(banner)


def cursor_launch_status(returncode, stdout, stderr):
    """Map a Cursor agent exit onto the writer contract.

    4 retires the writer. A raw exit 4 that is not a credit or auth failure
    becomes 1, so the skill retries it instead of advancing. None keeps the
    raw exit.
    """
    if returncode == 0:
        return None
    if cursor_writer_blocked(returncode, stdout, stderr):
        return 4
    if returncode == 4:
        return 1
    return None


def cursor_models_text():
    binary = _cursor_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run([binary, '--list-models'], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _candidates(host, include_cursor=True):
    """Writer resolution probes Cursor Grok. Review replacement does not.

    `include_cursor` stays false for `escalate` so a failed review seat never
    gains a Cursor writer and never calls the Cursor agent CLI.
    """
    host = host_name(host)
    listed, _error = codex_catalog(codex_catalog_path())
    cli_reason = claude_cli_reason()
    grok = select_cursor_grok(cursor_models_text()) if include_cursor else None
    return resolve_available(host, luna=select_luna(listed), sol=select_sol(listed),
                             sonnet=sonnet_candidate(host, cli_reason),
                             opus=opus_candidate(host, cli_reason),
                             cursor_grok=grok), {
        'cursor-grok': None if grok is None else {'adapter': 'cursor-agent', 'model': grok[0],
                                                   'effort': grok[1], 'lab': 'cursor'},
        'luna': _codex_spec(select_luna(listed)),
        'sol': _codex_spec(select_sol(listed)),
        'sonnet': _claude_spec(sonnet_candidate(host, cli_reason)),
        'opus': _claude_spec(opus_candidate(host, cli_reason)),
    }


def _codex_spec(found):
    if found is None:
        return None
    return {'adapter': 'codex', 'model': found[0], 'effort': found[1], 'lab': 'openai'}


def _claude_spec(found):
    if found is None:
        return None
    spec = dict(found)
    spec['lab'] = 'anthropic'
    return spec


def probe(host=None):
    chosen, _candidates_by_family = _candidates(host)
    return chosen


def write_record(path, document, refresh=False):
    path = Path(path)
    if path.exists() and not refresh:
        current = read_record(path)
        if current is None:
            raise ValueError('workhorse path exists and is not a record')
        return current
    validate_record(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(temporary, path)
    return document


def _prompt_path(session, task, cluster):
    if task == 'implement':
        return Path(session) / ('workhorse-implement-%s.prompt.md' % cluster)
    return Path(session) / ('workhorse-%s.prompt.md' % task)


def prepare_launch(session, task, cluster=None, prompt=None, out=None):
    session = Path(session)
    record = read_record(session / 'workhorse.json')
    if record is None or record.get('family') is None:
        raise ValueError('no workhorse to launch')
    root = scope_value(session, 'REV_ROOT')
    if task == 'review':
        if prompt is None:
            raise ValueError('review requires --prompt')
        prompt_path = Path(prompt)
        if not prompt_path.is_file():
            raise ValueError('review prompt is missing')
    else:
        if task == 'implement' and CLUSTER_ID.match(cluster or '') is None:
            raise ValueError('implement requires a plan cluster id')
        text = prompt_text(record, task, root, session, cluster=cluster,
                           findings=_read_capped(session / 'findings.md'),
                           plan=_read_capped(session / 'fix-plan.md'))
        prompt_path = _prompt_path(session, task, cluster)
        prompt_path.write_text(text, encoding='utf-8')
    return record, launch_spec(record, task, root, session, prompt_path, cluster, out)


def _leased_home():
    import importlib.util
    spec = importlib.util.spec_from_file_location('workhorse_seat_home', LIB / 'isolated-seat-home.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.leased_home


def _note(path, text):
    if text.strip():
        Path(str(path) + '.err').write_text(text, encoding='utf-8')


def _run_exec(spec):
    argv = list(spec['argv'])
    out_path = Path(spec['out'])
    env = os.environ.copy()
    if spec['adapter'] == 'cursor-agent':
        binary = _cursor_binary()
        if binary is None:
            print('workhorse: cursor agent CLI is not installed', file=sys.stderr)
            return 4
        argv[0] = binary
    if spec['adapter'] == 'claude':
        for name in CLAUDE_SESSION_ENV:
            env.pop(name, None)
    def run():
        stream = open(spec['stdin'], encoding='utf-8') if spec['stdin'] else subprocess.DEVNULL
        try:
            return subprocess.run(argv, stdin=stream, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, cwd=spec['cwd'], check=False)
        finally:
            if spec['stdin']:
                stream.close()

    if spec['adapter'] == 'codex':
        state = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        auth = state / 'auth.json'
        identity = 'workhorse:%s:%s' % (os.getpid(), spec['model'])
        with _leased_home()('codex', identity, auth if auth.is_file() else None) as home:
            env['CODEX_HOME'] = str(home)
            result = run()
    else:
        result = run()
    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')
    _note(out_path, stderr)
    status = result.returncode
    if spec['adapter'] == 'cursor-agent':
        mapped = cursor_launch_status(status, stdout, stderr)
        if mapped == 4:
            print('workhorse: Cursor writer is unavailable or out of credits', file=sys.stderr)
            return 4
        if mapped is not None:
            status = mapped
    if spec['task'] == 'plan':
        try:
            body = plan_markdown(stdout)
        except ValueError as error:
            out_path.with_name('workhorse-plan.rejected.txt').write_text(stdout, encoding='utf-8')
            print('workhorse: ' + str(error), file=sys.stderr)
            return 1
        out_path.write_text(body, encoding='utf-8')
        return status
    if spec['task'] == 'review':
        try:
            body = findings_json(stdout)
        except (ValueError, json.JSONDecodeError) as error:
            Path(str(out_path) + '.rejected.txt').write_text(stdout, encoding='utf-8')
            print('workhorse: ' + str(error), file=sys.stderr)
            status = 1
        else:
            out_path.write_text(body, encoding='utf-8')
        name = out_path.name
        exit_path = (out_path.with_name(name[:-5] + '.exit') if name.endswith('.json')
                     else Path(str(out_path) + '.exit'))
        exit_path.write_text(str(status) + '\n', encoding='utf-8')
        return status
    out_path.write_text(stdout, encoding='utf-8')
    return status


def execute_launch(session, task, cluster=None, prompt=None, out=None, dry_run=False):
    _record, spec = prepare_launch(session, task, cluster, prompt, out)
    if spec['kind'] == 'agent' or dry_run:
        print(json.dumps(spec, indent=2, sort_keys=True))
        if spec['kind'] == 'agent' and not dry_run:
            print('workhorse: the orchestrator launches this agent', file=sys.stderr)
            return 3
        return 0
    return _run_exec(spec)
