"""Turn a review invocation into one session roster config.

Normal is the default. On Cursor that panel is four Grok seats when the SDK can
seat them, and four Luna seats otherwise. Off Cursor it is four Luna seats.
`high effort` selects one Opus, one Sol, one Sonnet, and one Luna. An explicit
`4*luna` or `4*grok` replaces that preset. The user's permanent config is left
untouched. Later panels read the frozen roster this config produces.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile


HOSTS = ('claude', 'codex', 'cursor')
FAMILIES = ('luna', 'sol', 'terra', 'grok')
NORMAL_CHAIN = ('luna', 'sonnet', 'sol', 'opus')
REQUEST = re.compile(
    r'(?i)(?<![A-Za-z0-9])(\d+)\s*[*x×]\s*(?:latest-)?(luna|sol|terra|grok)\b')
HIGH_MODE = re.compile(
    r'(?i)(?<![A-Za-z0-9])(?:high[\s_-]+effort|mode[\s:_-]+high|effort[\s:_-]+high)\b')
NORMAL_MODE = re.compile(
    r'(?i)(?<![A-Za-z0-9])(?:normal[\s_-]+effort|mode[\s:_-]+normal|effort[\s:_-]+normal)\b')
CODEX_CLEAR = ('codex', 'openai', 'luna', 'sol', 'terra', 'codex-luna', 'codex-sol', 'codex-terra')
GROK_CLEAR = ('cursor-sdk', 'xai', 'grok', 'grok-1', 'grok-2', 'grok-3', 'grok-4')
HIGH_CLEAR = CODEX_CLEAR + (
    'claude', 'agent', 'anthropic', 'opus', 'sonnet', 'opus-2', 'opus-3', 'opus-4')


def chain_for(host):
    """Normal chain. Cursor prefixes Grok; every other host starts at Luna."""
    if host == 'cursor':
        return ('grok',) + NORMAL_CHAIN
    return NORMAL_CHAIN


def chosen_mode(text):
    """Default normal. `high effort` selects high. A later explicit mode wins."""
    events = [(match.start(), 'high') for match in HIGH_MODE.finditer(text or '')]
    events.extend((match.start(), 'normal') for match in NORMAL_MODE.finditer(text or ''))
    if not events:
        return 'normal'
    events.sort()
    return events[-1][1]


def parse_panel_request(text):
    """Return the one N*family request, None when the text names none, or raise."""
    matches = REQUEST.findall(text or '')
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('panel request names more than one roster')
    count = int(matches[0][0])
    family = matches[0][1].lower()
    if family not in FAMILIES or not 1 <= count <= 4:
        raise ValueError('panel request must be 1 to 4 luna, sol, terra, or grok seats')
    if family == 'grok':
        return {'version': 1, 'count': count, 'family': 'grok',
                'cursor_sdk_models': ['latest-grok'] * count}
    selector = 'latest-' + family
    return {
        'version': 1,
        'count': count,
        'family': family,
        'selector': selector,
        'codex_models': [selector] * count,
        'claude_seats': 0,
        'extras': False,
        'min_labs': 1,
    }


def _exclude(config, drop, add):
    raw = config.get('exclude')
    current = {item.strip().lower() for item in raw if isinstance(item, str)} if isinstance(raw, list) else set()
    return sorted((current - set(drop)) | set(add))


def _without_sdk(config):
    for key in ('cursor_sdk_models', 'cursor_sdk_model_selections', 'cursor_sdk_effort'):
        config.pop(key, None)
    return config


def luna_config(base, fallback=False):
    """Four Luna seats, with Gemini and Cursor SDK kept out of the panel."""
    config = dict(base)
    config.pop('claude_models', None)
    config.pop('claude_seat', None)
    config.pop('panel_fallback', None)
    _without_sdk(config)
    config['panel_mode'] = 'normal'
    config['panel_family'] = 'luna'
    config['codex_models'] = ['latest-luna'] * 4
    config['claude_seats'] = 0
    config['extras'] = False
    config['min_labs'] = 1
    config['exclude'] = _exclude(config, CODEX_CLEAR, {'gemini', 'cursor-sdk'})
    if fallback:
        config['panel_grok_fallback'] = True
    else:
        config.pop('panel_grok_fallback', None)
    return config


def grok_config(base, count, fallback=False):
    """Grok seats only. `fallback` lets roster build replace a failed SDK with four Luna seats."""
    config = dict(base)
    for key in ('claude_models', 'claude_seat', 'codex_models', 'codex_effort', 'panel_grok_fallback'):
        config.pop(key, None)
    config.pop('cursor_sdk_model_selections', None)
    config['panel_mode'] = 'normal' if fallback else 'explicit'
    config['panel_family'] = 'grok'
    config['cursor_sdk_models'] = ['latest-grok'] * count
    config['cursor_sdk_effort'] = 'xhigh'
    config['claude_seats'] = 0
    config['extras'] = False
    config['min_labs'] = 1
    config['exclude'] = _exclude(config, GROK_CLEAR, {'codex', 'openai', 'gemini'})
    if fallback:
        config['panel_fallback'] = 'luna'
    else:
        config.pop('panel_fallback', None)
    return config


def high_config(base):
    """One Opus, one Sol, one Sonnet, one Luna. Pair substitution happens during roster build."""
    config = dict(base)
    for key in ('claude_seats', 'claude_seat', 'panel_fallback', 'panel_grok_fallback'):
        config.pop(key, None)
    _without_sdk(config)
    config['panel_mode'] = 'high'
    config['panel_family'] = 'high'
    config['codex_models'] = ['latest-sol', 'latest-luna']
    if 'codex_effort' not in config:
        config['codex_effort'] = 'xhigh'
    config['claude_models'] = ['opus', 'sonnet']
    config['extras'] = False
    config['min_labs'] = 1
    config['exclude'] = _exclude(config, HIGH_CLEAR, {'gemini', 'cursor-sdk'})
    return config


def session_config(base, request, host='claude', grok_ready=False):
    """Overlay an explicit N*family roster onto a copy of the current config."""
    if not isinstance(base, dict):
        raise ValueError('roster config must be an object')
    if request.get('family') == 'grok':
        if host != 'cursor' or not grok_ready:
            raise ValueError('grok panel requires Cursor and the Cursor SDK runtime')
        return grok_config(base, request['count'], fallback=False)
    config = dict(base)
    config.pop('claude_models', None)
    config.pop('claude_seat', None)
    _without_sdk(config)
    config.pop('panel_fallback', None)
    config.pop('panel_grok_fallback', None)
    config['panel_mode'] = 'explicit'
    config['panel_family'] = request['family']
    config['codex_models'] = list(request['codex_models'])
    config['claude_seats'] = 0
    config['extras'] = False
    config['min_labs'] = 1
    config['exclude'] = _exclude(config, CODEX_CLEAR, {'gemini', 'cursor-sdk'})
    return config


def mode_config(base, mode, host, grok_ready):
    if mode == 'high':
        return high_config(base)
    if host == 'cursor' and grok_ready:
        return grok_config(base, 4, fallback=True)
    return luna_config(base, fallback=False)


def load_base(path):
    file = Path(path) if path else None
    if file is None or not file.is_file():
        return {}
    try:
        document = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('unreadable roster config') from error
    if not isinstance(document, dict):
        raise ValueError('roster config must be an object')
    return document


def sdk_ready():
    runtime = os.environ.get('REVIEW_COUNCIL_CURSOR_SDK_RUNTIME')
    receipt = os.environ.get('REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION')
    return bool(runtime and receipt and Path(runtime).is_dir() and Path(receipt).is_file())


def _attempt_policy():
    cached = getattr(_attempt_policy, 'module', None)
    if cached is not None:
        return cached
    path = Path(__file__).with_name('rev-attempt.py')
    spec = importlib.util.spec_from_file_location('rev_attempt_policy', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _attempt_policy.module = module
    return module


def _install_policy(path, raw):
    descriptor, temporary = tempfile.mkstemp(prefix='.fallback-policy.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_session(session, text, base_path=None, host=None, grok_ready=None):
    """Write the session roster and return its path. The default mode is normal."""
    host = host or os.environ.get('REVIEW_COUNCIL_HOST') or 'claude'
    if host not in HOSTS:
        raise ValueError('unknown review-council host: ' + host)
    if grok_ready is None:
        grok_ready = sdk_ready()
    explicit = parse_panel_request(text)
    mode = chosen_mode(text)
    base = load_base(base_path)
    if explicit is not None:
        config = session_config(base, explicit, host=host, grok_ready=grok_ready)
        request = dict(explicit)
        request.update(mode=mode, host=host, chain=list(chain_for(host)), roster='explicit')
    else:
        config = mode_config(base, mode, host, grok_ready)
        request = {
            'version': 1,
            'mode': mode,
            'host': host,
            'chain': list(chain_for(host)),
            'panel_family': config.get('panel_family'),
            'roster': mode,
        }
    session = Path(session)
    session.mkdir(parents=True, exist_ok=True)
    attempt = _attempt_policy()
    from session_inputs import (
        SessionInputsError, find_evidence_seal, preflight_inputs_present, session_input_lock)
    config_path = session / 'roster-config.json'
    policy = attempt.fallback_policy_bytes(attempt.eligible_document(config))
    try:
        with session_input_lock(session):
            if find_evidence_seal(session) is not None or preflight_inputs_present(session):
                raise ValueError('session policy is sealed')
            _write(session / 'panel-request.json', request)
            _write(config_path, config)
            _install_policy(session / 'fallback-policy.json', policy)
    except SessionInputsError as error:
        raise ValueError(str(error)) from error
    return config_path


def _write(path, document):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)
