"""Turn a caller's panel roster, such as 4*luna, into a session config.

The user's permanent config is left untouched. Later panels read the frozen roster
this config produces; they do not rebuild the default Sol, Opus, and Sonnet mix.
"""
import json
from pathlib import Path
import re


FAMILIES = ('luna', 'sol', 'terra')
REQUEST = re.compile(
    r'(?i)(?<![A-Za-z0-9])(\d+)\s*[*x×]\s*(?:latest-)?(luna|sol|terra)\b')


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
        raise ValueError('panel request must be 1 to 4 luna, sol, or terra seats')
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


def session_config(base, request):
    """Overlay the caller's panel onto a copy of the current config."""
    if not isinstance(base, dict):
        raise ValueError('roster config must be an object')
    config = dict(base)
    config.pop('claude_models', None)
    config['codex_models'] = list(request['codex_models'])
    config['claude_seats'] = 0
    config['extras'] = False
    config['min_labs'] = 1
    return config


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


def write_session(session, text, base_path=None):
    request = parse_panel_request(text)
    if request is None:
        return None
    session = Path(session)
    session.mkdir(parents=True, exist_ok=True)
    config_path = session / 'roster-config.json'
    request_path = session / 'panel-request.json'
    config = session_config(load_base(base_path), request)
    _write(request_path, request)
    _write(config_path, config)
    return config_path


def _write(path, document):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)
