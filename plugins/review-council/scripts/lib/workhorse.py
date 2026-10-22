#!/usr/bin/env python3
"""Choose and launch the cheap workhorse for fix plans, plan review, and implementation.

The session model orchestrates. OpenAI Luna, Anthropic Sonnet, and Cursor Grok
(`cursor-grok-*`, only on the Cursor host) do the writing. Frontier review seats
stay on the roster.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

LIB = Path(__file__).resolve().parent
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from roster import (CLAUDE_SESSION_ENV, claude_cli_reason, codex_catalog, codex_catalog_path,
                    codex_suffix, reasoning_efforts)

HOSTS = ('claude', 'codex', 'cursor')
PREFERENCE = {
    'cursor': ('cursor-grok', 'luna', 'sonnet'),
    'codex': ('luna', 'sonnet'),
    'claude': ('sonnet', 'luna'),
}
FAMILIES = ('cursor-grok', 'luna', 'sonnet')
SEAT = 'workhorse'
LABS = {'cursor-grok': 'cursor', 'luna': 'openai', 'sonnet': 'anthropic'}
ADAPTERS = {'cursor-grok': ('cursor-agent',), 'luna': ('codex',), 'sonnet': ('claude', 'agent')}
LUNA_EFFORTS = ('high', 'xhigh', 'max')
CURSOR_EFFORTS = ('high', 'medium', 'low', 'xhigh', 'max')
SONNET_MODEL = 'sonnet'
SONNET_EFFORT = 'high'
CURSOR_GROK_SLUG = re.compile(r'^cursor-grok-(\d+)(?:\.(\d+))?-(low|medium|high|xhigh|max)$')
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


def select_luna(listed):
    """Newest visible Luna at high, else xhigh, else max. `listed` is codex_catalog's list."""
    lunas = [(gen, model, slug) for gen, model, slug in listed if codex_suffix(slug) == 'luna']
    if not lunas:
        return None
    newest = max(gen for gen, _, _ in lunas)
    model, slug = next((model, slug) for gen, model, slug in lunas if gen == newest)
    levels = reasoning_efforts(model.get('supported_reasoning_levels'))
    effort = next((name for name in LUNA_EFFORTS if name in levels), None)
    if effort is None:
        return None
    return slug, effort


def select_cursor_grok(text):
    """Newest cursor-grok generation, preferring high and ignoring fast and frontier Grok slugs."""
    if not isinstance(text, str) or not text.strip():
        return None
    parsed = []
    for line in text.splitlines():
        slug = line.split(' - ', 1)[0].strip()
        if not slug or slug.endswith('-fast'):
            continue
        match = CURSOR_GROK_SLUG.match(slug)
        if match is None:
            continue
        generation = (int(match.group(1)), int(match.group(2) or 0))
        parsed.append((generation, match.group(3), slug))
    if not parsed:
        return None
    newest = max(item[0] for item in parsed)
    current = [item for item in parsed if item[0] == newest]
    rank = {name: index for index, name in enumerate(CURSOR_EFFORTS)}
    current.sort(key=lambda item: rank.get(item[1], len(rank)))
    _generation, effort, slug = current[0]
    return slug, effort


def sonnet_candidate(host, cli_reason):
    """Sonnet is the Claude-host workhorse even without the CLI. Other hosts need the CLI."""
    if host == 'claude':
        return {'adapter': 'claude' if cli_reason is None else 'agent',
                'model': SONNET_MODEL, 'effort': SONNET_EFFORT}
    if cli_reason is None:
        return {'adapter': 'claude', 'model': SONNET_MODEL, 'effort': SONNET_EFFORT}
    return None


def _record(host, family, available, **fields):
    document = {
        'version': 1,
        'host': host,
        'family': family,
        'available': [name for name in PREFERENCE[host] if name in available],
        'reason': ('host %s; no workhorse available' % host if family is None
                   else 'host %s; selected %s' % (host, family)),
    }
    document.update(fields)
    if family is not None:
        document.update(lab=LABS[family], seat=SEAT)
    validate_record(document)
    return document


def resolve_available(host, luna=None, sonnet=None, cursor_grok=None):
    """Pick the host-native workhorse, then the other available families.

    `luna` and `cursor_grok` are `(model, effort)` or None. `sonnet` is a candidate
    dict from `sonnet_candidate` or None. Cursor Grok is ignored off the Cursor host.
    """
    host = host_name(host)
    present = {}
    if luna is not None:
        present['luna'] = {'adapter': 'codex', 'model': luna[0], 'effort': luna[1]}
    if sonnet is not None:
        present['sonnet'] = dict(sonnet)
    if host == 'cursor' and cursor_grok is not None:
        present['cursor-grok'] = {'adapter': 'cursor-agent', 'model': cursor_grok[0],
                                   'effort': cursor_grok[1]}
    for family in PREFERENCE[host]:
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
    if (not isinstance(available, list) or any(name not in PREFERENCE[host] for name in available)
            or available != [name for name in PREFERENCE[host] if name in available]):
        raise ValueError('invalid workhorse availability')
    if family is None:
        if available:
            raise ValueError('an unavailable workhorse listed a family')
        return document
    if family not in PREFERENCE[host] or family not in available:
        raise ValueError('selected workhorse is not available on this host')
    if (document.get('lab') != LABS[family] or document.get('seat') != SEAT
            or document.get('adapter') not in ADAPTERS[family]):
        raise ValueError('workhorse identity does not match its family')
    model, effort = document.get('model'), document.get('effort')
    if (not isinstance(model, str) or not model.strip() or model != model.strip()
            or len(model) > 120 or not isinstance(effort, str)):
        raise ValueError('invalid workhorse model')
    if family == 'luna':
        if codex_suffix(model) != 'luna' or effort not in LUNA_EFFORTS:
            raise ValueError('invalid luna workhorse')
    elif family == 'sonnet':
        if model != SONNET_MODEL or effort != SONNET_EFFORT:
            raise ValueError('invalid sonnet workhorse')
    elif effort not in CURSOR_EFFORTS or CURSOR_GROK_SLUG.match(model) is None:
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


def lookup_launch(roster_path, seat):
    """Roster row, or the workhorse row when that seat is not on the review roster."""
    path = Path(roster_path)
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('unreadable roster') from error
    if not isinstance(document, dict):
        raise ValueError('unreadable roster')
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


def _scope_value(session, key):
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
        if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
            return raw[1:-1]
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
    return {'kind': 'exec', 'argv': argv, 'stdin': stdin, 'out': destination,
            'task': task, 'adapter': adapter, 'model': record['model'], 'effort': record['effort'],
            'prompt': prompt_path}


def _cursor_binary():
    return shutil.which('agent') or shutil.which('cursor-agent')


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


def probe(host=None):
    host = host_name(host)
    listed, _error = codex_catalog(codex_catalog_path())
    return resolve_available(host, luna=select_luna(listed),
                             sonnet=sonnet_candidate(host, claude_cli_reason()),
                             cursor_grok=select_cursor_grok(cursor_models_text())
                             if host == 'cursor' else None)


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
    root = _scope_value(session, 'REV_ROOT')
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
            return 1
        argv[0] = binary
    if spec['adapter'] == 'claude':
        for name in CLAUDE_SESSION_ENV:
            env.pop(name, None)
    def run():
        stream = open(spec['stdin'], encoding='utf-8') if spec['stdin'] else subprocess.DEVNULL
        try:
            return subprocess.run(argv, stdin=stream, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, check=False)
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
    if spec['task'] == 'plan':
        try:
            body = plan_markdown(stdout)
        except ValueError as error:
            out_path.with_name('workhorse-plan.rejected.txt').write_text(stdout, encoding='utf-8')
            print('workhorse: ' + str(error), file=sys.stderr)
            return 1
        out_path.write_text(body, encoding='utf-8')
        return result.returncode
    if spec['task'] == 'review':
        try:
            body = findings_json(stdout)
        except (ValueError, json.JSONDecodeError) as error:
            Path(str(out_path) + '.rejected.txt').write_text(stdout, encoding='utf-8')
            print('workhorse: ' + str(error), file=sys.stderr)
            status = 1
        else:
            out_path.write_text(body, encoding='utf-8')
            status = result.returncode
        name = out_path.name
        exit_path = (out_path.with_name(name[:-5] + '.exit') if name.endswith('.json')
                     else Path(str(out_path) + '.exit'))
        exit_path.write_text(str(status) + '\n', encoding='utf-8')
        return status
    out_path.write_text(stdout, encoding='utf-8')
    return result.returncode


def execute_launch(session, task, cluster=None, prompt=None, out=None, dry_run=False):
    _record, spec = prepare_launch(session, task, cluster, prompt, out)
    if spec['kind'] == 'agent' or dry_run:
        print(json.dumps(spec, indent=2, sort_keys=True))
        if spec['kind'] == 'agent' and not dry_run:
            print('workhorse: the orchestrator launches this agent', file=sys.stderr)
            return 3
        return 0
    return _run_exec(spec)
