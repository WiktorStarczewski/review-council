#!/usr/bin/env python3
"""Build the review-council reviewer roster from whichever lab CLIs are installed and signed in.

    roster.sh [--json|--brief] [--probe] [--write <file>]

Detection is CHEAP by default — a binary on PATH, one status command, a cache or credentials file —
because session start prints the `--brief` line on every startup and must never call a model.
`--probe` (preflight only) additionally sends a one-token "reply OK" to each CLI seat and drops the
seats that fail. Exit 0 with >= 3 non-extra seats, exit 5 with fewer; the JSON is printed either way
and `excluded[]` says why each CLI is missing. Standard library only.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

EFFORTS = ('max', 'xhigh', 'high')   # highest first; a mid tier is never seated
LOGIN_TIMEOUT = 20                   # a wedged status command must not hang session start
PROBE_TIMEOUT = 60

LABS = {'codex': 'openai', 'grok': 'xai', 'gemini': 'google', 'agent': 'anthropic'}
# the name an adapter answers to in the --brief line, in `excluded[].cli` and in config `exclude`
NAMES = {'codex': 'codex', 'grok': 'grok', 'gemini': 'gemini', 'agent': 'claude'}
ORDER = ('codex', 'grok', 'gemini', 'agent')
# (adapter, seat, mode, round) — an extra pass is seated whenever its lab has a seat
EXTRAS = (('codex', 'codex-review', 'review', 2), ('grok', 'grok-code-review', 'code-review', 3))

GEN = re.compile(r'^gpt-(\d+)\.(\d+)(?:-|$)')     # gpt-5.6-sol → generation (5, 6), suffix "sol"
GROK_VER = re.compile(r'grok-(\d+)\.(\d+)')

PROBE_CMD = {
    'codex':  lambda m: ['codex', 'exec', '--ephemeral', '-s', 'read-only', '-m', m,
                         'Reply with exactly OK'],
    'grok':   lambda m: ['grok', '-p', 'Reply with exactly OK', '-m', m, '--permission-mode', 'plan',
                         '--output-format', 'json', '--max-turns', '1'],
    'gemini': lambda m: ['gemini', '-p', 'Reply with exactly OK', '-m', m, '--approval-mode', 'plan',
                         '-o', 'json'],
}


def env_path(var, default):
    """$var if set and non-empty, else the expanded default."""
    return os.environ.get(var) or os.path.expanduser(default)


def run(cmd, timeout):
    """Run cmd with no stdin. → (rc, stdout, stderr); rc is None on timeout, 127 if it cannot start."""
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, '', ''
    except OSError as exc:
        return 127, '', str(exc)
    dec = lambda b: (b or b'').decode('utf-8', 'replace')
    return p.returncode, dec(p.stdout), dec(p.stderr)


def first_line(text, limit=200):
    for line in (text or '').splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ''


def make_seat(name, adapter, model, effort, mode=None, round_=None):
    s = {'seat': name, 'lab': LABS[adapter], 'adapter': adapter, 'model': model,
         'effort': effort, 'extra': mode is not None}
    if mode is not None:
        s['mode'] = mode
        s['round'] = round_
    return s


# ---------------------------------------------------------------- detection

def top_effort(levels):
    """The highest of max → xhigh → high the model supports, else None (never a mid tier)."""
    got = []
    for lv in levels if isinstance(levels, list) else []:
        e = lv.get('effort') if isinstance(lv, dict) else lv
        if isinstance(e, str) and e:
            got.append(e)
    return next((e for e in EFFORTS if e in got), None)


def codex_models(path):
    """→ [(slug, effort)] — listed slugs of the newest generation in the cache, best priority first."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []
    models = data.get('models') if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    listed = []
    for m in models:
        if not isinstance(m, dict) or m.get('visibility') != 'list':
            continue
        slug = m.get('slug')
        gen = GEN.match(slug) if isinstance(slug, str) else None
        if gen:
            listed.append(((int(gen.group(1)), int(gen.group(2))), m, slug))
    if not listed:
        return []
    newest = max(gen for gen, _, _ in listed)
    current = [(m, slug) for gen, m, slug in listed if gen == newest]
    # `priority` orders the lab's own list (sol=1, terra=2, luna=3): lower ranks first.
    current.sort(key=lambda ms: ms[0].get('priority') if isinstance(ms[0].get('priority'), (int, float))
                 else float('inf'))
    out = []
    for m, slug in current:
        effort = top_effort(m.get('supported_reasoning_levels'))
        if effort:
            out.append((slug, effort))
        if len(out) == 2:
            break
    return out


def codex_suffix(slug):
    gen = GEN.match(slug)
    return slug[gen.end():] if gen else slug


def detect_codex(cfg):
    if shutil.which('codex') is None:
        return [], 'not installed'
    rc, out, err = run(['codex', 'login', 'status'], LOGIN_TIMEOUT)
    if rc is None:
        return [], 'sign-in check timed out'
    if rc != 0 or 'Logged in' not in (out + err):
        return [], 'not signed in'
    cache = env_path('REVIEW_COUNCIL_CODEX_MODELS_CACHE', '~/.codex/models_cache.json')
    models = codex_models(cache)
    if not models:
        return [], 'no usable model in %s' % cache
    seats = []
    for slug, effort in models:
        suffix = codex_suffix(slug)
        seats.append(make_seat('codex-' + suffix if suffix else 'codex', 'codex', slug, effort))
    return seats, None


def detect_grok(cfg):
    if shutil.which('grok') is None:
        return [], 'not installed'
    rc, out, err = run(['grok', 'models'], LOGIN_TIMEOUT)
    if rc is None:
        return [], 'sign-in check timed out'
    text = (out + err)
    low = text.lower()
    # "logged in" is a substring of "not logged in": require the positive phrase AND the absence of the negative
    if rc != 0 or 'logged in' not in low or 'not logged in' in low:
        return [], 'not signed in'
    versions = [(int(a), int(b)) for a, b in GROK_VER.findall(text)]
    if not versions:
        return [], 'no grok model listed'
    major, minor = max(versions)
    return [make_seat('grok', 'grok', 'grok-%d.%d' % (major, minor), 'xhigh')], None


def detect_gemini(cfg):
    if shutil.which('gemini') is None:
        return [], 'not installed'
    creds = env_path('REVIEW_COUNCIL_GEMINI_CREDS', '~/.gemini/oauth_creds.json')
    if not os.environ.get('GEMINI_API_KEY') and not os.path.exists(creds):
        return [], 'not signed in'
    model = os.environ.get('REVIEW_COUNCIL_GEMINI_MODEL') or 'gemini-2.5-pro'
    return [make_seat('gemini', 'gemini', model, None)], None   # no effort knob on gemini


def detect_agent(cfg):
    if os.environ.get('REVIEW_COUNCIL_CLAUDE_SEAT') == '0' or cfg.get('claude_seat') is False:
        return [], 'disabled'
    return [make_seat('opus', 'agent', 'opus', 'max')], None     # the in-harness rev-reviewer agent


DETECT = {'codex': detect_codex, 'grok': detect_grok, 'gemini': detect_gemini, 'agent': detect_agent}


# ---------------------------------------------------------------- config

def load_config():
    """→ (config, error) — an unreadable or non-object file yields ({}, 'config unreadable')."""
    path = env_path('REVIEW_COUNCIL_CONFIG', '~/.config/review-council/config.json')
    if not os.path.exists(path):
        return {}, None
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        return {}, 'config unreadable'
    if not isinstance(cfg, dict):
        return {}, 'config unreadable'
    return cfg, None


def excluded_names(cfg):
    raw = cfg.get('exclude')
    return {v.strip().lower() for v in raw if isinstance(v, str)} if isinstance(raw, list) else set()


def apply_pins(cfg, seats):
    pins = cfg.get('pin') if isinstance(cfg.get('pin'), dict) else {}
    for s in seats:
        pin = pins.get(s['seat'])
        if not isinstance(pin, dict):
            continue
        if isinstance(pin.get('model'), str) and pin['model']:
            s['model'] = pin['model']
        if isinstance(pin.get('effort'), str) and pin['effort']:
            s['effort'] = pin['effort']


def probe_seat(s):
    """→ None if the seat answers, else the exclusion reason."""
    rc, out, err = run(PROBE_CMD[s['adapter']](s['model']), PROBE_TIMEOUT)
    if rc is None:
        return 'probe timed out'
    if rc == 0:
        return None
    line = first_line(err) or first_line(out)
    return 'probe failed: %s' % line if line else 'probe failed'


# ---------------------------------------------------------------- assembly

def build(do_probe):
    cfg, cfg_error = load_config()
    excluded = []
    if cfg_error:
        excluded.append({'cli': 'config', 'reason': cfg_error})
    dropped = excluded_names(cfg)
    seats, adapter_of = [], {}

    for adapter in ORDER:
        name = NAMES[adapter]
        if {name, adapter, LABS[adapter]} & dropped:
            excluded.append({'cli': name, 'reason': 'excluded by config'})
            continue
        found, reason = DETECT[adapter](cfg)
        if reason:
            excluded.append({'cli': name, 'reason': reason})
        seats.extend(found)

    for s in seats:
        adapter_of[s['seat']] = s['adapter']

    kept = []
    for s in seats:
        if s['seat'].lower() in dropped:
            excluded.append({'cli': s['seat'], 'reason': 'excluded by config'})
        else:
            kept.append(s)

    apply_pins(cfg, kept)

    if do_probe:
        survivors = []
        for s in kept:
            reason = probe_seat(s) if s['adapter'] in PROBE_CMD else None
            if reason:
                excluded.append({'cli': s['seat'], 'reason': reason})
            else:
                survivors.append(s)
        kept = survivors

    if cfg.get('extras') is not False:
        for adapter, name, mode, round_ in EXTRAS:
            base = next((s for s in kept if s['adapter'] == adapter and not s['extra']), None)
            if base:
                kept.append(make_seat(name, adapter, base['model'], base['effort'], mode, round_))

    roster = {'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'seats': kept, 'excluded': excluded}
    return roster, adapter_of


def brief_line(roster, adapter_of):
    by_cli = {}
    for e in roster['excluded']:
        by_cli.setdefault(e['cli'], e['reason'])
    parts = []
    for adapter in ORDER:
        name = NAMES[adapter]
        seated = [s for s in roster['seats'] if s['adapter'] == adapter and not s['extra']]
        if seated:
            models = ', '.join(s['model'] + ('@' + s['effort'] if s['effort'] else '') for s in seated)
            parts.append('%s ✓ (%s)' % (name, models))
        else:
            reason = by_cli.get(name) or next(
                (e['reason'] for e in roster['excluded'] if adapter_of.get(e['cli']) == adapter),
                'unavailable')
            parts.append('%s ✗ %s' % (name, reason))
    return 'review-council seats: ' + ' · '.join(parts)


def usage(message):
    sys.stderr.write('roster: %s\nusage: roster.sh [--json|--brief] [--probe] [--write <file>]\n' % message)
    return 1


def main(argv):
    fmt, do_probe, write = 'json', False, None
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == '--json':
            fmt = 'json'
        elif a == '--brief':
            fmt = 'brief'
        elif a == '--probe':
            do_probe = True
        elif a == '--write':
            if not args:
                return usage('--write needs a file')
            write = args.pop(0)
        else:
            return usage('unknown argument %s' % a)

    roster, adapter_of = build(do_probe)
    text = json.dumps(roster, indent=2, ensure_ascii=False) + '\n'
    if write:
        tmp = write + '.new'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(text)
            os.replace(tmp, write)
        except OSError as exc:
            sys.stderr.write('roster: cannot write %s: %s\n' % (write, exc))
            return 1
    sys.stdout.write(text if fmt == 'json' else brief_line(roster, adapter_of) + '\n')
    return 0 if len([s for s in roster['seats'] if not s['extra']]) >= 3 else 5


if __name__ == '__main__':
    try:                                  # a C-locale shell must not break the ✓/✗/· line
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
