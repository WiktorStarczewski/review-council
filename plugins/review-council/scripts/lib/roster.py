#!/usr/bin/env python3
"""Build the review-council reviewer roster from whichever lab CLIs are installed and signed in.

    roster.sh [--json|--brief] [--probe] [--write <file>]

Detection is CHEAP by default - a binary on PATH, one status command, a cache or credentials file -
because session start prints the `--brief` line on every startup and must never call a model.
`--probe` (preflight only) additionally sends a one-token "reply OK" to each CLI seat and drops the
seats that fail.

A panel is three seats. Fewer detected than that is never a refusal: Claude seats are padded in until
there are three, the roster is marked `degraded` with a one-sentence reason, and every line the user
sees carries it. Exit is 0 whenever a panel exists. Exit 5 marks retryable availability strictness,
including `min_labs` and unavailable exact seats. Exit 6 marks permanent configuration strictness.
The JSON is printed either way and `excluded[]` says why each CLI is missing. Standard library only.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

EFFORTS = ('max', 'xhigh', 'high')   # highest first; a mid tier is never seated
PANEL = 3                            # seats a round needs; a thinner roster is padded, never refused
LOGIN_TIMEOUT = int(os.environ.get('REVIEW_COUNCIL_LOGIN_TIMEOUT', '20'))   # a wedged status command must not hang session start
PROBE_TIMEOUT = int(os.environ.get('REVIEW_COUNCIL_PROBE_TIMEOUT', '60'))

CODEX_HOST = os.environ.get('REVIEW_COUNCIL_HOST') == 'codex'
LABS = {'codex': 'openai', 'grok': 'xai', 'gemini': 'google', 'agent': 'anthropic', 'claude': 'anthropic'}
# the name an adapter answers to in the --brief line, in `excluded[].cli` and in config `exclude`
NAMES = {'codex': 'codex', 'grok': 'grok', 'gemini': 'gemini', 'agent': 'claude', 'claude': 'claude'}
ORDER = ('codex', 'grok', 'gemini', 'claude' if CODEX_HOST else 'agent')
# (adapter, seat, mode, round) - an extra pass is seated whenever its lab has a seat
EXTRAS = (('codex', 'codex-review', 'review', 3), ('grok', 'grok-code-review', 'code-review', 4))

GEN = re.compile(r'^gpt-(\d+)(?:\.(\d+))?(?:-|$)')  # gpt-6-astra and gpt-5.6-sol
GROK_VER = re.compile(r'grok-(\d+)\.(\d+)')

PROBE_CMD = {
    'claude': lambda m: ['claude', '-p', 'Reply with exactly OK', '--model', m,
                         '--permission-mode', 'plan', '--tools', '', '--setting-sources', '',
                         '--strict-mcp-config', '--no-session-persistence', '--max-turns', '1'],
    'codex':  lambda m: ['codex', 'exec', '--ephemeral', '--skip-git-repo-check', '-s', 'read-only', '-m', m,
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
    if os.environ.get('REVIEW_COUNCIL_DEBUG'):
        sys.stderr.write('roster debug: %s → rc=%s\n  stdout: %r\n  stderr: %r\n' % (' '.join(cmd), p.returncode, dec(p.stdout)[:400], dec(p.stderr)[:400]))
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


def codex_catalog(path):
    """Return listed GPT catalog entries plus a precise retryable cache diagnostic."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return [], 'Codex model cache unavailable: %s' % path
    except Exception:
        return [], 'Codex model cache unreadable: %s' % path
    models = data.get('models') if isinstance(data, dict) else None
    if not isinstance(models, list):
        return [], 'Codex model cache unreadable: %s' % path
    listed = []
    for m in models:
        if not isinstance(m, dict) or m.get('visibility') != 'list':
            continue
        slug = m.get('slug')
        gen = GEN.match(slug) if isinstance(slug, str) else None
        if gen:
            listed.append(((int(gen.group(1)), int(gen.group(2) or 0)), m, slug))
    if not listed:
        return [], 'no usable model in %s' % path
    return listed, None


def select_codex_models(listed, allowed=None):
    if isinstance(allowed, list):
        by_slug = {slug: m for _, m, slug in listed}
        out = []
        for slug in allowed:
            if not isinstance(slug, str) or slug not in by_slug or any(item[0] == slug for item in out):
                continue
            effort = top_effort(by_slug[slug].get('supported_reasoning_levels'))
            if effort:
                out.append((slug, effort))
            if len(out) == 2:
                break
        return out
    newest = max(gen for gen, _, _ in listed)
    current = [(m, slug) for gen, m, slug in listed if gen == newest]
    # `priority` orders the lab's own list (sol=1, terra=2, luna=3): lower ranks first.
    current.sort(key=lambda ms: ms[0].get('priority') if isinstance(ms[0].get('priority'), (int, float))
                 else float('inf'))
    out = []
    seen = set()
    for m, slug in current:
        if slug in seen:
            continue
        seen.add(slug)
        effort = top_effort(m.get('supported_reasoning_levels'))
        if effort:
            out.append((slug, effort))
        if len(out) == 2:
            break
    return out


def codex_models(path, allowed=None):
    """Return selected (slug, effort) pairs, or an empty list for an unusable catalog."""
    listed, reason = codex_catalog(path)
    return [] if reason else select_codex_models(listed, allowed)


def codex_suffix(slug):
    gen = GEN.match(slug)
    return slug[gen.end():] if gen else slug


def codex_models_setting(cfg):
    if 'codex_models' not in cfg:
        return None, None
    raw = cfg.get('codex_models')
    valid = (isinstance(raw, list) and 1 <= len(raw) <= 2
             and all(isinstance(slug, str) and slug.strip() == slug and slug for slug in raw)
             and len(set(raw)) == len(raw))
    if not valid:
        return None, 'invalid codex_models: expected 1 or 2 unique non-empty model slug strings'
    return raw, None


def codex_seat_names(models):
    suffixes = [codex_suffix(slug) for slug, _ in models]
    repeated = {suffix for suffix in suffixes if suffixes.count(suffix) > 1}
    names = []
    for (slug, _), suffix in zip(models, suffixes):
        if suffix in repeated:
            suffix = re.sub(r'[^a-zA-Z0-9]+', '-', slug.removeprefix('gpt-')).strip('-')
        names.append('codex-' + suffix if suffix else 'codex')
    return names


NEGATIVE = ('not logged in', 'not signed in', 'login required', 'please log in', 'run `codex login`', 'run codex login', 'run grok login')


def status_check(cmd, positive):
    """→ (ok, reason). A transient non-zero exit (no sign-out text) is retried once after 1 s and, if it
    persists, reported as a failed check - never as a sign-out, which is a different message to the user."""
    rc, out, err = run(cmd, LOGIN_TIMEOUT)
    if rc is None:
        return False, 'sign-in check timed out'
    low = (out + err).lower()
    if any(n in low for n in NEGATIVE):
        return False, 'not signed in'
    if rc != 0:
        time.sleep(1)
        rc, out, err = run(cmd, LOGIN_TIMEOUT)
        if rc is None:
            return False, 'sign-in check timed out'
        low = (out + err).lower()
        if any(n in low for n in NEGATIVE):
            return False, 'not signed in'
        if rc != 0:
            return False, 'status check failed: %s' % (first_line(err) or first_line(out) or 'exit %s' % rc)
    if positive.lower() not in low:
        return False, 'not signed in'
    return True, None


def detect_codex(cfg):
    allowed, config_error = codex_models_setting(cfg)
    if config_error:
        return [], config_error
    cache = env_path('REVIEW_COUNCIL_CODEX_MODELS_CACHE',
                     os.path.join(env_path('CODEX_HOME', '~/.codex'), 'models_cache.json'))
    listed, catalog_error = (codex_catalog(cache) if allowed is not None else (None, None))
    if listed:
        by_slug = {slug: model for _, model, slug in listed}
        unknown = [slug for slug in allowed if slug not in by_slug]
        if unknown:
            label = 'slug' if len(unknown) == 1 else 'slugs'
            return [], 'unknown Codex model %s: %s' % (label, ', '.join(unknown))
        unsupported = [slug for slug in allowed
                       if top_effort(by_slug[slug].get('supported_reasoning_levels')) is None]
        if unsupported:
            label = 'model' if len(unsupported) == 1 else 'models'
            verb = 'has' if len(unsupported) == 1 else 'have'
            return [], 'configured Codex %s %s no supported high effort: %s' \
                       % (label, verb, ', '.join(unsupported))
    if shutil.which('codex') is None:
        return [], 'not installed'
    ok, reason = status_check(['codex', 'login', 'status'], 'logged in')
    if not ok:
        return [], reason
    if listed is None:
        listed, catalog_error = codex_catalog(cache)
    if catalog_error:
        return [], catalog_error
    models = select_codex_models(listed, allowed)
    if not models:
        return [], 'no usable model in %s' % cache
    return [make_seat(name, 'codex', slug, effort)
            for name, (slug, effort) in zip(codex_seat_names(models), models)], None


def detect_grok(cfg):
    if shutil.which('grok') is None:
        return [], 'not installed'
    ok, reason = status_check(['grok', 'models'], 'logged in')
    if not ok:
        return [], reason
    rc, out, err = run(['grok', 'models'], LOGIN_TIMEOUT)   # the model list itself (cheap, cached by grok)
    text = out + err
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


def claude_seat_count(cfg):
    if 'claude_seats' in cfg:
        value = cfg.get('claude_seats')
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4:
            return None, 'invalid claude_seats: expected an integer from 0 to 4'
    else:
        value = 1
    if os.environ.get('REVIEW_COUNCIL_CLAUDE_SEAT') == '0' or cfg.get('claude_seat') is False:
        return 0, None
    return value, None


def opus_seats(adapter, count):
    return [make_seat('opus' if index == 0 else 'opus-%d' % (index + 1),
                      adapter, 'opus', 'max') for index in range(count)]


def detect_agent(cfg):
    count, config_error = claude_seat_count(cfg)
    if config_error:
        return [], config_error
    if count == 0:
        return [], 'disabled'
    return opus_seats('agent', count), None


def detect_claude(cfg):
    count, config_error = claude_seat_count(cfg)
    if config_error:
        return [], config_error
    if count == 0:
        return [], 'disabled'
    if shutil.which('claude') is None:
        return [], 'not installed'
    rc, out, _ = run(['claude', 'auth', 'status', '--json'], LOGIN_TIMEOUT)
    if rc is None:
        return [], 'sign-in check timed out'
    try:
        status = json.loads(out)
    except ValueError:
        return [], 'sign-in check failed'
    if rc != 0 or not isinstance(status, dict) or status.get('loggedIn') is not True:
        return [], 'not signed in'
    return opus_seats('claude', count), None


DETECT = {'codex': detect_codex, 'grok': detect_grok, 'gemini': detect_gemini,
          'agent': detect_agent, 'claude': detect_claude}


# ---------------------------------------------------------------- config

def load_config():
    """→ (config, error) - an unreadable or non-object file yields ({}, 'config unreadable')."""
    # REVIEW_COUNCIL_CONFIG wins, else ~/.config. CLAUDE_PLUGIN_DATA is deliberately NOT consulted: Claude Code
    # sets it per plugin and a Bash tool call can inherit ANOTHER plugin's value (seen: the codex plugin's).
    path = os.environ.get('REVIEW_COUNCIL_CONFIG') or os.path.expanduser('~/.config/review-council/config.json')
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


def enforce_codex_models(cfg, seats, excluded):
    allowed, config_error = codex_models_setting(cfg)
    if allowed is None or config_error:
        return seats
    kept, seen = [], set()
    for seat in seats:
        if seat['adapter'] != 'codex':
            kept.append(seat)
            continue
        if seat['model'] not in allowed:
            excluded.append({'cli': seat['seat'],
                             'reason': 'pinned model %s is outside codex_models' % seat['model']})
            continue
        if not seat['extra'] and seat['model'] in seen:
            excluded.append({'cli': seat['seat'],
                             'reason': 'pinned model %s duplicates another Codex seat' % seat['model']})
            continue
        if not seat['extra']:
            seen.add(seat['model'])
        kept.append(seat)
    return kept


def probe_seat(s):
    """→ None if the seat answers, else the exclusion reason."""
    rc, out, err = run(PROBE_CMD[s['adapter']](s['model']), PROBE_TIMEOUT)
    if rc is None:
        return 'probe timed out'
    if rc == 0:
        return None
    line = first_line(err) or first_line(out)
    return 'probe failed: %s' % line if line else 'probe failed'


def min_labs_setting(cfg):
    """Return the distinct-lab floor and a permanent error for an invalid explicit value."""
    if 'min_labs' not in cfg:
        return 1, None
    value = cfg.get('min_labs')
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None, 'invalid min_labs: expected an integer of at least 1'
    return value, None


def configured_lab_capacity(cfg):
    """Conservative maximum number of real labs permitted by static configuration."""
    dropped = excluded_names(cfg)
    labs = set()
    for adapter in ORDER:
        lab = LABS[adapter]
        if {NAMES[adapter], adapter, lab} & dropped:
            continue
        if lab == 'anthropic':
            count, error = claude_seat_count(cfg)
            if error or count == 0:
                continue
            names = {'opus' if index == 0 else 'opus-%d' % (index + 1)
                     for index in range(count)}
            if names and names <= dropped:
                continue
        labs.add(lab)
    return len(labs)


def codex_pin_conflict(cfg, allowed):
    """Return a static exact-model pin conflict, even when Codex itself is unavailable."""
    pins = cfg.get('pin') if isinstance(cfg.get('pin'), dict) else {}
    seen = set()
    for seat, slug in zip(codex_seat_names([(slug, None) for slug in allowed]), allowed):
        pin = pins.get(seat)
        model = pin.get('model') if isinstance(pin, dict) else None
        model = model if isinstance(model, str) and model else slug
        if model not in allowed:
            return seat, 'pinned model %s is outside codex_models' % model
        if model in seen:
            return seat, 'pinned model %s duplicates another Codex seat' % model
        seen.add(model)
    return None


def opus_model(model):
    value = model.lower() if isinstance(model, str) else ''
    return value == 'opus' or value.startswith(('opus-', 'claude-opus-'))


def claude_pin_conflict(cfg, count):
    pins = cfg.get('pin') if isinstance(cfg.get('pin'), dict) else {}
    for index in range(count):
        seat = 'opus' if index == 0 else 'opus-%d' % (index + 1)
        pin = pins.get(seat)
        model = pin.get('model') if isinstance(pin, dict) else None
        if isinstance(model, str) and model and not opus_model(model):
            return seat, 'pinned model %s is outside the Opus family' % model
    return None


def append_exclusion(excluded, cli, reason):
    entry = {'cli': cli, 'reason': reason}
    if entry not in excluded:
        excluded.append(entry)


def strict_winner(current_class, current_reason, candidate_class, candidate_reason):
    if candidate_class == 'config' and current_class != 'config':
        return candidate_class, candidate_reason
    if current_class is None:
        return candidate_class, candidate_reason
    return current_class, current_reason


def enforce_exact_seats(cfg, seats, excluded):
    """Refuse when an explicitly configured positive seat set did not survive selection.

    This runs before padding. A repeated fallback can make the panel runnable, but it cannot stand in
    for a model or independent run that the configuration explicitly required.
    """
    strict_class, strict_reason = None, None
    floor, floor_error = min_labs_setting(cfg)
    if floor_error:
        append_exclusion(excluded, 'min_labs', 'strict: %s' % floor_error)
        strict_class, strict_reason = 'config', floor_error
    else:
        capacity = configured_lab_capacity(cfg)
    if not floor_error and 'min_labs' in cfg and floor > capacity:
        reason = 'min_labs=%d exceeds %d configured lab(s)' % (floor, capacity)
        append_exclusion(excluded, 'min_labs', 'strict: %s' % reason)
        strict_class, strict_reason = 'config', reason
    allowed, config_error = codex_models_setting(cfg)
    if config_error:
        append_exclusion(excluded, 'codex_models', 'strict: %s' % config_error)
        strict_class, strict_reason = 'config', config_error
    elif allowed is not None:
        pin_conflict = codex_pin_conflict(cfg, allowed)
        if pin_conflict:
            append_exclusion(excluded, pin_conflict[0], pin_conflict[1])
        matched = [s for s in seats
                   if s['adapter'] == 'codex' and not s['extra'] and not s.get('padded')
                   and s['model'] in allowed]
        expected = {'codex', 'openai'} | set(
            codex_seat_names([(slug, None) for slug in allowed]))
        config_reason = None
        if pin_conflict:
            config_reason = '%s: %s' % pin_conflict
        elif expected & excluded_names(cfg):
            config_reason = '%s: excluded by config' % sorted(expected & excluded_names(cfg))[0]
        else:
            for entry in excluded:
                cli, reason = entry.get('cli'), str(entry.get('reason', ''))
                if reason.startswith('pinned model '):
                    config_reason = '%s: %s' % (cli, reason)
                    break
                if reason.startswith(('unknown Codex model ', 'configured Codex model')):
                    config_reason = reason
                    break
                if reason == 'excluded by config' and cli in expected:
                    config_reason = '%s: %s' % (cli, reason)
                    break
        if len(matched) != len(allowed):
            summary = 'codex_models requires %d matching seat(s), %d survived' \
                      % (len(allowed), len(matched))
            append_exclusion(excluded, 'codex_models', 'strict: ' + summary)
            cause = 'config' if config_reason else 'availability'
            reason = config_reason or summary
            strict_class, strict_reason = strict_winner(
                strict_class, strict_reason, cause, reason)
        elif config_reason:
            append_exclusion(excluded, 'codex_models',
                             'strict: codex_models conflicts with pin configuration')
            strict_class, strict_reason = strict_winner(
                strict_class, strict_reason, 'config', config_reason)

    raw_claude = cfg.get('claude_seats') if 'claude_seats' in cfg else None
    claude_disabled = (os.environ.get('REVIEW_COUNCIL_CLAUDE_SEAT') == '0'
                       or cfg.get('claude_seat') is False)
    valid_claude = (isinstance(raw_claude, int) and not isinstance(raw_claude, bool)
                    and 0 <= raw_claude <= 4)
    if 'claude_seats' in cfg and not valid_claude:
        reason = 'invalid claude_seats: expected an integer from 0 to 4'
        append_exclusion(excluded, 'claude_seats', 'strict: %s' % reason)
        strict_class, strict_reason = strict_winner(
            strict_class, strict_reason, 'config', reason)
    valid_positive = valid_claude and raw_claude > 0
    if valid_positive and not claude_disabled:
        adapter = 'claude' if CODEX_HOST else 'agent'
        pin_conflict = claude_pin_conflict(cfg, raw_claude)
        if pin_conflict:
            append_exclusion(excluded, pin_conflict[0], pin_conflict[1])
        matched = [s for s in seats
                   if s['adapter'] == adapter and not s['extra'] and not s.get('padded')
                   and opus_model(s.get('model'))]
        if len(matched) != raw_claude:
            summary = 'claude_seats requires %d matching seat(s), %d survived' \
                      % (raw_claude, len(matched))
            append_exclusion(excluded, 'claude_seats', 'strict: ' + summary)
            expected = {'claude', 'agent', 'anthropic'} | {
                'opus' if index == 0 else 'opus-%d' % (index + 1)
                for index in range(raw_claude)
            }
            if pin_conflict:
                config_reason = '%s: %s' % pin_conflict
            elif expected & excluded_names(cfg):
                config_reason = '%s: excluded by config' \
                                % sorted(expected & excluded_names(cfg))[0]
            else:
                config_reason = next(
                    ('%s: excluded by config' % entry.get('cli') for entry in excluded
                     if entry.get('reason') == 'excluded by config'
                     and entry.get('cli') in expected),
                    None,
                )
            cause = 'config' if config_reason else 'availability'
            strict_class, strict_reason = strict_winner(
                strict_class, strict_reason, cause, config_reason or summary)
        elif pin_conflict:
            append_exclusion(excluded, 'claude_seats',
                             'strict: claude_seats conflicts with pin configuration')
            strict_class, strict_reason = strict_winner(
                strict_class, strict_reason, 'config', '%s: %s' % pin_conflict)
    return strict_class, strict_reason


def valid_result_receipt_policy(policy):
    if not isinstance(policy, dict):
        return False
    version = policy.get('version')
    legacy = policy.get('legacy_no_exit_sha256')
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        return False
    if not isinstance(legacy, dict):
        return False
    return all(isinstance(name, str) and isinstance(digest, str)
               and re.fullmatch(r'[0-9a-fA-F]{64}', digest) is not None
               for name, digest in legacy.items())


def result_receipt_policy(roster_path):
    """Preserve a receipt policy or hash missing-receipt legacy results before upgrading it."""
    try:
        with open(roster_path, encoding='utf-8') as f:
            previous = json.load(f)
    except FileNotFoundError:
        if os.path.lexists(roster_path):
            return {'version': 1, 'legacy_no_exit_sha256': {}}
        previous = None
    except Exception:
        return {'version': 1, 'legacy_no_exit_sha256': {}}
    if previous is not None and not isinstance(previous, dict):
        return {'version': 1, 'legacy_no_exit_sha256': {}}
    if isinstance(previous, dict) and 'result_receipts' in previous:
        policy = previous['result_receipts']
        return policy if valid_result_receipt_policy(policy) \
            else {'version': 1, 'legacy_no_exit_sha256': {}}

    legacy = {}
    directory = os.path.dirname(os.path.abspath(roster_path))
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    for name in names:
        if not re.match(r'^r[0-9]+[a-z]*-[^/]+\.json$', name, re.IGNORECASE):
            continue
        result_path = os.path.join(directory, name)
        exit_path = os.path.splitext(result_path)[0] + '.exit'
        if os.path.exists(exit_path) or not os.path.isfile(result_path):
            continue
        try:
            with open(result_path, 'rb') as f:
                legacy[name] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            continue
    return {'version': 1, 'legacy_no_exit_sha256': legacy}


def pad(seats, excluded, cfg):
    """Top the panel up to PANEL non-extra seats with Claude seats. → the number added.

    A machine with only Claude Code installed still gets a panel; it gets a WORSE one, and saying so is
    the whole point of the `degraded` flag. Padded seats are ordinary seats - dealt lenses like any
    other - so three Claude seats read the diff through three different lenses. `claude_seat: false`
    is overridden here rather than honoured into an empty panel: the config asks for one fewer voice,
    not for no review at all, and the override is recorded in `excluded[]`.
    """
    missing = PANEL - len([s for s in seats if not s['extra']])
    if missing <= 0:
        return 0
    if CODEX_HOST:
        # Codex has no implicit Anthropic agent. Reuse only a real surviving CLI,
        # after exclusions and probes; independent runs are not independent labs.
        bases = [s for s in seats if not s['extra']]
        if not bases:
            return 0
        used = {s['seat'] for s in seats} | excluded_names(cfg)
        for i in range(missing):
            base = bases[i % len(bases)]
            n = 1
            name = '%s-%d' % (base['seat'], n)
            while name in used:
                n += 1
                name = '%s-%d' % (base['seat'], n)
            used.add(name)
            seats.append(dict(base, seat=name, padded=True))
        return missing
    # Whichever config turned the Claude lab off, padding overrides it - and says so. Silently
    # obeying would leave an empty panel; silently overriding would hide that the config was ignored.
    if cfg.get('claude_seat') is False:
        off = 'claude_seat: false overridden'
    elif os.environ.get('REVIEW_COUNCIL_CLAUDE_SEAT') == '0':
        off = 'REVIEW_COUNCIL_CLAUDE_SEAT=0 overridden'
    elif cfg.get('claude_seats') == 0:
        off = 'claude_seats: 0 overridden'
    elif {'claude', 'agent', 'anthropic'} & excluded_names(cfg):
        off = 'claude excluded by config, overridden'
    else:
        off = None
    if off:
        excluded.append({'cli': 'padding', 'reason': '%s - a panel needs %d seats' % (off, PANEL)})
    used = {s['seat'] for s in seats}
    n = 0
    for _ in range(missing):
        n += 1
        name = 'claude-%d' % n
        while name in used:
            n += 1
            name = 'claude-%d' % n
        used.add(name)
        seat = make_seat(name, 'agent', 'opus', 'max')
        seat['padded'] = True
        seats.append(seat)
    return missing


def degradation(seats, padded):
    """→ (labs, degraded, sentence). Degraded = padded at all, or only one lab left to disagree."""
    labs = []
    for s in seats:
        if not s['extra'] and s['lab'] not in labs:
            labs.append(s['lab'])
    if padded <= 0 and len(labs) > 1:
        return labs, False, None
    if CODEX_HOST:
        if not labs:
            return labs, True, 'no usable reviewer CLI - sign in to a supported provider'
        detail = ('%d repeat CLI seats; ' % padded) if padded else ''
        return labs, True, 'available labs: %s - %sreduced panel diversity' % (', '.join(labs), detail)
    if labs == ['anthropic']:
        n = len([s for s in seats if not s['extra']])
        return labs, True, ('only Claude is available - %d Claude seats, no cross-lab decorrelation' % n)
    if padded:
        return labs, True, ('only %s available - padded with %d Claude %s'
                            % (', '.join(labs), padded, 'seat' if padded == 1 else 'seats'))
    return labs, True, 'only %s available - no cross-lab decorrelation' % ', '.join(labs)


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

    # Extras are built BEFORE exclusion and pins so config can address them by seat name
    # (`exclude: ["codex-review"]`, `pin: {"grok-code-review": …}`), then follow their base lab through the probe.
    if cfg.get('extras') is not False:
        for adapter, name, mode, round_ in EXTRAS:
            base = next((s for s in seats if s['adapter'] == adapter and not s['extra']), None)
            if base:
                seats.append(make_seat(name, adapter, base['model'], base['effort'], mode, round_))

    for s in seats:
        adapter_of[s['seat']] = s['adapter']

    kept = []
    for s in seats:
        if s['seat'].lower() in dropped:
            excluded.append({'cli': s['seat'], 'reason': 'excluded by config'})
        else:
            kept.append(s)

    apply_pins(cfg, kept)
    kept = enforce_codex_models(cfg, kept, excluded)

    static_class = None
    if do_probe:
        static_excluded = [dict(entry) for entry in excluded]
        static_class, _ = enforce_exact_seats(cfg, kept, static_excluded)
    if do_probe and static_class != 'config':
        survivors = []
        probe_results = {}
        for s in kept:
            key = (s['adapter'], s['model'])
            if s['adapter'] in PROBE_CMD and not s['extra'] and key not in probe_results:
                probe_results[key] = probe_seat(s)
            reason = probe_results.get(key) if not s['extra'] else None
            if reason:
                excluded.append({'cli': s['seat'], 'reason': reason})
            else:
                survivors.append(s)
        kept = survivors
    # an extra rides on its lab: no surviving base seat → no extra
    kept = [s for s in kept if not s['extra'] or any(b['adapter'] == s['adapter'] and not b['extra'] for b in kept)]

    exact_class, exact_reason = enforce_exact_seats(cfg, kept, excluded)

    # Padding comes LAST - after config, after exclusions, after the probe - so it replaces the seats
    # those steps actually removed rather than a count taken before they ran.
    padded = pad(kept, excluded, cfg)
    labs, degraded, sentence = degradation(kept, padded)

    # Strict mode counts the labs that were actually DETECTED. Padded Claude seats are not a second
    # opinion, so they must not satisfy a floor whose whole purpose is to demand one - with
    # `claude_seat: false` and one real lab, counting them would let `min_labs: 2` pass on one lab.
    # `floor > 1` keeps the default of 1 unable to refuse anything: a bare machine with the Claude seat
    # turned off has ZERO real labs and still gets a padded panel, which is the point of this task.
    floor, floor_error = min_labs_setting(cfg)
    real = [l for l in labs
            if any(s['lab'] == l and not s['extra'] and not s.get('padded') for s in kept)]
    labs_strict = (not floor_error and (floor > 1 or CODEX_HOST)
                   and len(real) < floor)
    if labs_strict:
        append_exclusion(excluded, 'min_labs',
                         'strict: %d lab(s) available, min_labs=%d' % (len(real), floor))
    labs_reason = (None if floor_error else
                   '%d lab(s) available, min_labs=%d' % (len(real), floor))
    strict_class = ('config' if exact_class == 'config' else
                    'availability' if exact_class or labs_strict else None)
    strict_reason = exact_reason if exact_class else (labs_reason if labs_strict else None)

    roster = {'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'seats': kept, 'labs': labs, 'padded': padded, 'degraded': degraded}
    if degraded:
        roster['degradation'] = sentence
    if strict_class:
        roster['strict_class'] = strict_class
        roster['strict_reason'] = strict_reason
    roster['excluded'] = excluded
    return roster, adapter_of, strict_class


def brief_line(roster, adapter_of):
    by_cli = {}
    for e in roster['excluded']:
        by_cli.setdefault(e['cli'], e['reason'])
    parts = []
    for adapter in ORDER:
        name = NAMES[adapter]
        # padded seats are not something this lab was detected offering - they belong to the DEGRADED clause
        seated = [s for s in roster['seats']
                  if s['adapter'] == adapter and not s['extra'] and not s.get('padded')]
        if seated:
            models = ', '.join(s['model'] + ('@' + s['effort'] if s['effort'] else '') for s in seated)
            parts.append('%s ✓ (%s)' % (name, models))
        else:
            reason = by_cli.get(name) or next(
                (e['reason'] for e in roster['excluded'] if adapter_of.get(e['cli']) == adapter),
                'unavailable')
            # `claude ✗ disabled` beside `DEGRADED: only Claude is available` reads as a contradiction:
            # the detected seat IS off and padded seats of that lab are in the panel. Name them here.
            n = len([s for s in roster['seats']
                     if s['adapter'] == adapter and not s['extra'] and s.get('padded')])
            if n:
                reason += ' (%d padded seat%s)' % (n, '' if n == 1 else 's')
            parts.append('%s ✗ %s' % (name, reason))
    if any(e.get('reason') == 'config unreadable' for e in roster['excluded']):
        parts.append('config unreadable (pins and exclusions ignored)')
    line = 'review-council seats: ' + ' · '.join(parts)
    if roster.get('degraded'):
        line += ' · DEGRADED: ' + (roster.get('degradation') or 'the panel is short of voices')
    if roster.get('strict_class'):
        line += ' · STRICT %s: %s' % (roster['strict_class'], roster.get('strict_reason'))
    return line


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

    roster, adapter_of, strict_class = build(do_probe)
    if write:
        roster['result_receipts'] = result_receipt_policy(write)
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
    if strict_class == 'config':
        return 6
    return 5 if strict_class == 'availability' else 0


if __name__ == '__main__':
    try:                                  # a C-locale shell must not break the ✓/✗/· line
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))
