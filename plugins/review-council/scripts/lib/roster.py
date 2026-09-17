#!/usr/bin/env python3
"""Build the review-council reviewer roster from whichever lab CLIs are installed and signed in.

    roster.sh [--json|--brief] [--probe] [--quota-failed-seat <seat>] [--write <file>]

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
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_inputs import SessionInputsError, assert_unsealed, install_inputs

EFFORTS = ('max', 'xhigh', 'high')   # highest first; a mid tier is never seated
PANEL = 3                            # seats a round needs; a thinner roster is padded, never refused
LOGIN_TIMEOUT = int(os.environ.get('REVIEW_COUNCIL_LOGIN_TIMEOUT', '20'))   # a wedged status command must not hang session start
PROBE_TIMEOUT = int(os.environ.get('REVIEW_COUNCIL_PROBE_TIMEOUT', '60'))
_ACTIVE_PROCESSES = {}
_ACTIVE_LOCK = threading.RLock()
_CANCELLED = threading.Event()
_LAUNCH_STATE = threading.local()
_RESOLVED = {}   # one build()'s Anthropic adapter, and the claude CLI check `auto` ran to choose it

CODEX_HOST = os.environ.get('REVIEW_COUNCIL_HOST') == 'codex'
LABS = {'codex': 'openai', 'gemini': 'google', 'agent': 'anthropic', 'claude': 'anthropic'}
# the name an adapter answers to in the --brief line, in `excluded[].cli` and in config `exclude`
NAMES = {'codex': 'codex', 'gemini': 'gemini', 'agent': 'claude', 'claude': 'claude'}
# detection order; build() seats the Anthropic slot on anthropic_adapter()
ORDER = ('codex', 'gemini', 'claude')
# (adapter, seat, mode, round) - an extra pass is seated whenever its lab has a seat
EXTRAS = (('codex', 'codex-review', 'review', 3),)

GEN = re.compile(r'^gpt-(\d+)(?:\.(\d+))?(?:-|$)')  # gpt-6-astra and gpt-5.6-sol

PROBE_CMD = {
    'claude': lambda m, e: ['claude', '-p', 'Reply with exactly OK', '--model', m,
                         '--effort', e,
                         '--permission-mode', 'plan', '--tools', '', '--setting-sources', '',
                         '--strict-mcp-config', '--no-session-persistence', '--max-turns', '1'],
    'codex':  lambda m, e: ['codex', 'exec', '--ephemeral', '--skip-git-repo-check',
                         '-s', 'read-only', '-m', m, '-c', 'model_reasoning_effort=' + e,
                         'Reply with exactly OK'],
    'gemini': lambda m, _e: ['gemini', '-p', 'Reply with exactly OK', '-m', m, '--approval-mode', 'plan',
                         '-o', 'json'],
}


def env_path(var, default):
    """$var if set and non-empty, else the expanded default."""
    return os.environ.get(var) or os.path.expanduser(default)


def register_process(process):
    with _ACTIVE_LOCK:
        _ACTIVE_PROCESSES[process.pid] = process
        cancelled = _CANCELLED.is_set()
    if cancelled:
        terminate_process_group(process)
        unregister_process(process)
        return False
    return True


def unregister_process(process):
    with _ACTIVE_LOCK:
        _ACTIVE_PROCESSES.pop(process.pid, None)


def begin_process_launch():
    _LAUNCH_STATE.depth = getattr(_LAUNCH_STATE, 'depth', 0) + 1


def finish_process_launch():
    depth = _LAUNCH_STATE.depth - 1
    _LAUNCH_STATE.depth = depth
    if depth == 0 and hasattr(_LAUNCH_STATE, 'pending_signal'):
        signum = _LAUNCH_STATE.pending_signal
        del _LAUNCH_STATE.pending_signal
        cancel_active_process_groups()
        raise SystemExit(128 + signum)


def run(cmd, timeout):
    """Run cmd with no stdin. → (rc, stdout, stderr); rc is None on timeout, 127 if it cannot start."""
    try:
        output_limit = int(os.environ.get('REVIEW_COUNCIL_PROVIDER_OUTPUT_BYTES', 1024 * 1024))
    except ValueError:
        output_limit = 1024 * 1024
    if output_limit < 256 or output_limit > 64 * 1024 * 1024:
        output_limit = 1024 * 1024
    p = None
    begin_process_launch()
    try:
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
            registered = register_process(p)
        finally:
            finish_process_launch()
    except OSError as exc:
        return 127, '', str(exc)
    except BaseException:
        if p is not None:
            terminate_process_group(p)
            unregister_process(p)
            p.stdout.close()
            p.stderr.close()
        raise
    if not registered:
        p.stdout.close(); p.stderr.close()
        return 125, '', 'provider command cancelled'
    selector = selectors.DefaultSelector()
    streams = {p.stdout: bytearray(), p.stderr: bytearray()}
    total = 0
    failure = None
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = 'timeout'
                break
            for key, _ in selector.select(min(0.05, remaining)):
                stream = key.fileobj
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                total += len(chunk)
                if total > output_limit:
                    failure = 'output'
                    break
                streams[stream].extend(chunk)
            if failure is not None:
                break
        if failure is None:
            remaining = max(0, deadline - time.monotonic())
            try:
                p.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                failure = 'timeout'
        if failure is None and process_group_alive(p.pid):
            failure = 'descendant'
    except BaseException:
        terminate_process_group(p)
        raise
    finally:
        if failure is not None:
            terminate_process_group(p)
        selector.close()
        for stream in streams:
            stream.close()
        unregister_process(p)
    if failure is not None:
        if failure == 'timeout':
            return None, '', ''
        if failure == 'descendant':
            return 125, '', 'provider command left a descendant process running'
        return 125, '', 'provider command output limit exceeded'
    dec = lambda b: (b or b'').decode('utf-8', 'replace')
    if os.environ.get('REVIEW_COUNCIL_DEBUG'):
        sys.stderr.write('roster debug: %s → rc=%s\n  stdout: %r\n  stderr: %r\n' % (
            ' '.join(cmd), p.returncode, dec(streams[p.stdout])[:400],
            dec(streams[p.stderr])[:400]))
    return p.returncode, dec(streams[p.stdout]), dec(streams[p.stderr])


def process_group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def terminate_process_groups(processes):
    processes = list({process.pid: process for process in processes}.values())
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and any(
            process_group_alive(process.pid) for process in processes):
        time.sleep(0.02)
    for process in processes:
        if process_group_alive(process.pid):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    for process in processes:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def terminate_process_group(process):
    terminate_process_groups([process])


def cancel_active_process_groups():
    _CANCELLED.set()
    with _ACTIVE_LOCK:
        processes = list(_ACTIVE_PROCESSES.values())
    terminate_process_groups(processes)


def cancellation_signal(signum, _frame):
    _CANCELLED.set()
    if getattr(_LAUNCH_STATE, 'depth', 0):
        _LAUNCH_STATE.pending_signal = signum
        return
    cancel_active_process_groups()
    raise SystemExit(128 + signum)


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


NEGATIVE = ('not logged in', 'not signed in', 'login required', 'please log in',
            'run `codex login`', 'run codex login')


def status_check(cmd, positive):
    """Return (ok, reason, output), retaining the successful check output for callers that need it."""
    rc, out, err = run(cmd, LOGIN_TIMEOUT)
    if rc is None:
        return False, 'sign-in check timed out', ''
    low = (out + err).lower()
    if any(n in low for n in NEGATIVE):
        return False, 'not signed in', out + err
    if rc != 0:
        time.sleep(1)
        rc, out, err = run(cmd, LOGIN_TIMEOUT)
        if rc is None:
            return False, 'sign-in check timed out', ''
        low = (out + err).lower()
        if any(n in low for n in NEGATIVE):
            return False, 'not signed in', out + err
        if rc != 0:
            reason = first_line(err) or first_line(out) or 'exit %s' % rc
            return False, 'status check failed: %s' % reason, out + err
    if positive.lower() not in low:
        return False, 'not signed in', out + err
    return True, None, out + err


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
    ok, reason, _ = status_check(['codex', 'login', 'status'], 'logged in')
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


def detect_gemini(cfg):
    if shutil.which('gemini') is None:
        return [], 'not installed'
    creds = env_path('REVIEW_COUNCIL_GEMINI_CREDS', '~/.gemini/oauth_creds.json')
    if not os.environ.get('GEMINI_API_KEY') and not os.path.exists(creds):
        return [], 'not signed in'
    model = os.environ.get('REVIEW_COUNCIL_GEMINI_MODEL') or 'gemini-2.5-pro'
    return [make_seat('gemini', 'gemini', model, None)], None   # no effort knob on gemini


def claude_seat_count(cfg):
    if 'claude_models' in cfg and 'claude_seats' in cfg:
        return None, 'claude_models and claude_seats are mutually exclusive'
    if 'claude_seats' in cfg:
        value = cfg.get('claude_seats')
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4:
            return None, 'invalid claude_seats: expected an integer from 0 to 4'
    else:
        value = 1
    if os.environ.get('REVIEW_COUNCIL_CLAUDE_SEAT') == '0' or cfg.get('claude_seat') is False:
        return 0, None
    return value, None


def claude_models_setting(cfg):
    if 'claude_models' in cfg and 'claude_seats' in cfg:
        return None, 'claude_models and claude_seats are mutually exclusive'
    if 'claude_models' not in cfg:
        return None, None
    raw = cfg.get('claude_models')
    valid = (isinstance(raw, list) and 1 <= len(raw) <= 2
             and all(model in ('opus', 'sonnet') for model in raw)
             and len(set(raw)) == len(raw))
    if not valid:
        return None, 'invalid claude_models: expected 1 or 2 unique values from opus and sonnet'
    return raw, None


def claude_model_seat_names(models):
    return list(models)


def opus_seats(adapter, count):
    return [make_seat('opus' if index == 0 else 'opus-%d' % (index + 1),
                      adapter, 'opus', 'max') for index in range(count)]


def claude_seats(adapter, cfg):
    models, config_error = claude_models_setting(cfg)
    if config_error:
        return [], config_error
    count, config_error = claude_seat_count(cfg)
    if config_error:
        return [], config_error
    if count == 0:
        return [], 'disabled'
    if models is None:
        return opus_seats(adapter, count), None
    return [make_seat(name, adapter, model, 'max')
            for name, model in zip(claude_model_seat_names(models), models)], None


def detect_agent(cfg):
    return claude_seats('agent', cfg)


def claude_cli_reason():
    """None when the claude CLI is installed and signed in, else why it cannot seat a reviewer."""
    if shutil.which('claude') is None:
        return 'not installed'
    rc, out, _ = run(['claude', 'auth', 'status', '--json'], LOGIN_TIMEOUT)
    if rc is None:
        return 'sign-in check timed out'
    try:
        status = json.loads(out)
    except ValueError:
        return 'sign-in check failed'
    if rc != 0 or not isinstance(status, dict) or status.get('loggedIn') is not True:
        return 'not signed in'
    return None


def detect_claude(cfg):
    seats, reason = claude_seats('claude', cfg)
    if reason:
        return [], reason
    reason = _RESOLVED['cli'] if 'cli' in _RESOLVED else claude_cli_reason()
    if reason:
        return [], reason
    return seats, None


def claude_adapter_setting(cfg):
    """Return cli, agent or auto (REVIEW_COUNCIL_CLAUDE_ADAPTER wins) and a permanent config error."""
    name = 'REVIEW_COUNCIL_CLAUDE_ADAPTER'
    value = os.environ.get(name)
    if not value:
        name, value = 'claude_adapter', cfg.get('claude_adapter', 'auto')
    if value not in ('cli', 'agent', 'auto'):
        return None, 'invalid %s: expected cli, agent or auto' % name
    return value, None


def anthropic_adapter(cfg):
    """The adapter this build seats Anthropic reviewers on: `claude` (the CLI) or `agent` (the host's
    Agent tool). A Codex host has no Agent tool. `auto` prefers a signed-in CLI, whose evidence the
    host can audit, and checks it once per build."""
    if CODEX_HOST:
        return 'claude'
    if 'adapter' not in _RESOLVED:
        setting, _ = claude_adapter_setting(cfg)
        if setting == 'auto':
            _RESOLVED['cli'] = claude_cli_reason()
        _RESOLVED['adapter'] = ('claude' if setting == 'cli'
                                or setting == 'auto' and _RESOLVED['cli'] is None else 'agent')
    return _RESOLVED['adapter']


def provider_order(cfg):
    return tuple(anthropic_adapter(cfg) if LABS[adapter] == 'anthropic' else adapter
                 for adapter in ORDER)


def plan_seats_setting(cfg):
    value = cfg.get('plan_seats', 'completeness')
    if value not in ('completeness', 'all'):
        return None, 'invalid plan_seats: expected completeness or all'
    return value, None


DETECT = {'codex': detect_codex, 'gemini': detect_gemini,
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


def enforce_claude_models(cfg, seats, excluded):
    allowed, config_error = claude_models_setting(cfg)
    if allowed is None or config_error:
        return seats
    adapter = anthropic_adapter(cfg)
    required = dict(zip(claude_model_seat_names(allowed), allowed))
    kept, seen = [], set()
    for seat in seats:
        if seat['adapter'] != adapter:
            kept.append(seat)
            continue
        if seat['model'] not in allowed:
            excluded.append({'cli': seat['seat'],
                             'reason': 'pinned model %s is outside claude_models'
                                       % seat['model']})
            continue
        if not seat['extra'] and seat['seat'] in required \
                and seat['model'] != required[seat['seat']]:
            excluded.append({
                'cli': seat['seat'],
                'reason': 'pinned model %s does not match required model %s'
                          % (seat['model'], required[seat['seat']]),
            })
            continue
        if not seat['extra'] and seat['model'] in seen:
            excluded.append({'cli': seat['seat'],
                             'reason': 'pinned model %s duplicates another Claude seat'
                                       % seat['model']})
            continue
        if not seat['extra'] and seat.get('effort') != 'max':
            excluded.append({'cli': seat['seat'],
                             'reason': 'pinned effort %s does not match required effort max'
                                       % seat.get('effort')})
            continue
        if not seat['extra']:
            seen.add(seat['model'])
        kept.append(seat)
    return kept


AUTH_FAILURE = re.compile(
    r"not logged in|login required|please (?:log|sign) in|run codex login|to log in|"
    r"auth(?:entication)? (?:method|required)|[^0-9]401[^0-9]|unauthori[sz]ed",
    re.IGNORECASE,
)
QUOTA_FAILURE = re.compile(
    r"usage limit|rate limit|too many requests|[^0-9]429[^0-9]|quota exceeded|"
    r"resource_exhausted|capacity exhausted|credit balance|insufficient credits|"
    r"out of credits|hit your limit",
    re.IGNORECASE,
)


def provider_stream_errors(adapter, output):
    errors = []
    if adapter not in ('codex', 'gemini', 'claude'):
        return errors
    for line in (output or '').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('type') == 'error' or event.get('is_error') is True \
                or event.get('subtype') == 'error':
            errors.append(json.dumps(event, ensure_ascii=False))
    return errors


def classify_provider_failure(adapter, stdout='', stderr='', summary_log=None):
    if summary_log is not None:
        lines = []
        for line in summary_log.splitlines():
            if re.match(r'^(?:text|exec|done): |^tool_call ', line):
                continue
            lines.append(line)
        cli_text = '\n'.join(lines)
    else:
        cli_text = '\n'.join([stderr or ''] + provider_stream_errors(adapter, stdout))
    if AUTH_FAILURE.search(cli_text):
        return 'auth', 'authentication unavailable'
    if QUOTA_FAILURE.search(cli_text):
        return 'quota', 'quota exhausted'
    return 'other', 'unclassified provider failure'


def probe_seat(s):
    """Return (reason, class, sanitized cause), with reason None when the seat answers."""
    rc, out, err = run(PROBE_CMD[s['adapter']](s['model'], s.get('effort')), PROBE_TIMEOUT)
    if rc is None:
        return 'probe timed out', 'other', 'probe timed out'
    if rc == 0:
        return None, None, None
    line = first_line(err) or first_line(out)
    failure_class, cause = classify_provider_failure(s['adapter'], out, err)
    reason = 'probe failed: %s' % line if line else 'probe failed'
    return reason, failure_class, cause


def quota_fallback_setting(cfg):
    value = cfg.get('quota_fallback', False)
    if not isinstance(value, bool):
        return False, 'invalid quota_fallback: expected true or false'
    return value, None


def fallback_target(source, seats, probe_results, unavailable=()):
    if source['lab'] == 'anthropic':
        candidates = [s for s in seats if not s['extra'] and s['adapter'] == 'codex'
                      and codex_suffix(s['model']) == 'terra']
    elif source['lab'] == 'openai':
        candidates = [s for s in seats if not s['extra']
                      and s['adapter'] in ('agent', 'claude') and s['model'] == 'sonnet']
    else:
        return None
    for candidate in candidates:
        if candidate['seat'] in unavailable:
            continue
        key = (candidate['adapter'], candidate['model'], candidate.get('effort'))
        result = probe_results.get(key)
        if result is not None and result[0] is None:
            return candidate
    return None


def fallback_seat(target, source, used, counters):
    family = 'codex-terra' if target['adapter'] == 'codex' else 'claude-sonnet'
    counters[family] = counters.get(family, 0) + 1
    name = '%s-fallback-%d' % (family, counters[family])
    while name in used:
        counters[family] += 1
        name = '%s-fallback-%d' % (family, counters[family])
    used.add(name)
    substitute = make_seat(name, target['adapter'], target['model'], target.get('effort'))
    substitute['padded'] = True
    substitute['substitutes_for'] = source['seat']
    return substitute


def quota_handoff_error(names, do_probe, fallback_enabled, seats):
    if not names:
        return None
    if not do_probe:
        return '--quota-failed-seat requires --probe'
    if not fallback_enabled:
        return '--quota-failed-seat requires quota_fallback: true'
    if len(set(names)) != len(names):
        return 'duplicate --quota-failed-seat value'
    current = {seat['seat']: seat for seat in seats}
    for name in names:
        seat = current.get(name)
        if seat is None or seat['extra'] or seat['lab'] not in ('openai', 'anthropic'):
            return ('invalid --quota-failed-seat %s: expected a current non-extra '
                    'OpenAI or Anthropic seat' % name)
    return None


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
    for adapter in provider_order(cfg):
        lab = LABS[adapter]
        if {NAMES[adapter], adapter, lab} & dropped:
            continue
        if lab == 'anthropic':
            models, models_error = claude_models_setting(cfg)
            count, error = claude_seat_count(cfg)
            if models_error or error or count == 0:
                continue
            names = (set(claude_model_seat_names(models)) if models is not None else
                     {'opus' if index == 0 else 'opus-%d' % (index + 1)
                      for index in range(count)})
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


def claude_models_pin_conflict(cfg, allowed):
    pins = cfg.get('pin') if isinstance(cfg.get('pin'), dict) else {}
    seen = set()
    for seat, default_model in zip(claude_model_seat_names(allowed), allowed):
        pin = pins.get(seat)
        model = pin.get('model') if isinstance(pin, dict) else None
        model = model if isinstance(model, str) and model else default_model
        effort = pin.get('effort') if isinstance(pin, dict) else None
        effort = effort if isinstance(effort, str) and effort else 'max'
        if model not in allowed:
            return seat, 'pinned model %s is outside claude_models' % model
        if model != default_model:
            return seat, 'pinned model %s does not match required model %s' \
                         % (model, default_model)
        if model in seen:
            return seat, 'pinned model %s duplicates another Claude seat' % model
        if effort != 'max':
            return seat, 'pinned effort %s does not match required effort max' % effort
        seen.add(model)
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
    _, fallback_error = quota_fallback_setting(cfg)
    if fallback_error:
        append_exclusion(excluded, 'quota_fallback', 'strict: %s' % fallback_error)
        strict_class, strict_reason = 'config', fallback_error
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
    for key, setting in (('claude_adapter', claude_adapter_setting),
                         ('plan_seats', plan_seats_setting)):
        _, setting_error = setting(cfg)
        if setting_error:
            append_exclusion(excluded, key, 'strict: %s' % setting_error)
            strict_class, strict_reason = strict_winner(
                strict_class, strict_reason, 'config', setting_error)
    allowed, config_error = codex_models_setting(cfg)
    if config_error:
        append_exclusion(excluded, 'codex_models', 'strict: %s' % config_error)
        strict_class, strict_reason = 'config', config_error
    elif allowed is not None:
        pin_conflict = codex_pin_conflict(cfg, allowed)
        if pin_conflict:
            append_exclusion(excluded, pin_conflict[0], pin_conflict[1])
        required_names = set(codex_seat_names([(slug, None) for slug in allowed]))
        matched = {s.get('substitutes_for') for s in seats
                   if not s['extra'] and s.get('substitutes_for') in required_names}
        matched.update(s['seat'] for s in seats
                       if s['adapter'] == 'codex' and not s['extra']
                       and not s.get('padded') and s['seat'] in required_names
                       and s['model'] in allowed)
        expected = {'codex', 'openai'} | required_names
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

    allowed_claude, claude_models_error = claude_models_setting(cfg)
    if claude_models_error:
        append_exclusion(excluded, 'claude_models', 'strict: %s' % claude_models_error)
        strict_class, strict_reason = strict_winner(
            strict_class, strict_reason, 'config', claude_models_error)
    elif allowed_claude is not None:
        adapter = anthropic_adapter(cfg)
        pin_conflict = claude_models_pin_conflict(cfg, allowed_claude)
        if pin_conflict:
            append_exclusion(excluded, pin_conflict[0], pin_conflict[1])
        required_names = set(claude_model_seat_names(allowed_claude))
        matched = {s.get('substitutes_for') for s in seats
                   if not s['extra'] and s.get('substitutes_for') in required_names}
        matched.update(s['seat'] for s in seats
                       if s['adapter'] == adapter and not s['extra']
                       and not s.get('padded') and s['seat'] in required_names
                       and s['model'] in allowed_claude and s.get('effort') == 'max')
        expected = {'claude', 'agent', 'anthropic'} | required_names
        if cfg.get('claude_seat') is False:
            config_reason = 'claude_models conflicts with claude_seat: false'
        elif os.environ.get('REVIEW_COUNCIL_CLAUDE_SEAT') == '0':
            config_reason = 'claude_models conflicts with REVIEW_COUNCIL_CLAUDE_SEAT=0'
        elif pin_conflict:
            config_reason = '%s: %s' % pin_conflict
        elif expected & excluded_names(cfg):
            config_reason = '%s: excluded by config' \
                            % sorted(expected & excluded_names(cfg))[0]
        else:
            config_reason = next(
                ('%s: %s' % (entry.get('cli'), entry.get('reason'))
                 for entry in excluded
                 if entry.get('cli') in expected
                 and (entry.get('reason') == 'excluded by config'
                      or str(entry.get('reason', '')).startswith(('pinned model ',
                                                                  'pinned effort ')))),
                None,
            )
        if len(matched) != len(allowed_claude):
            summary = 'claude_models requires %d matching seat(s), %d survived' \
                      % (len(allowed_claude), len(matched))
            append_exclusion(excluded, 'claude_models', 'strict: ' + summary)
            cause = 'config' if config_reason else 'availability'
            strict_class, strict_reason = strict_winner(
                strict_class, strict_reason, cause, config_reason or summary)
        elif config_reason:
            append_exclusion(excluded, 'claude_models',
                             'strict: claude_models conflicts with configuration')
            strict_class, strict_reason = strict_winner(
                strict_class, strict_reason, 'config', config_reason)

    raw_claude = cfg.get('claude_seats') if 'claude_seats' in cfg else None
    claude_disabled = (os.environ.get('REVIEW_COUNCIL_CLAUDE_SEAT') == '0'
                       or cfg.get('claude_seat') is False)
    valid_claude = (isinstance(raw_claude, int) and not isinstance(raw_claude, bool)
                    and 0 <= raw_claude <= 4)
    if 'claude_models' not in cfg and 'claude_seats' in cfg and not valid_claude:
        reason = 'invalid claude_seats: expected an integer from 0 to 4'
        append_exclusion(excluded, 'claude_seats', 'strict: %s' % reason)
        strict_class, strict_reason = strict_winner(
            strict_class, strict_reason, 'config', reason)
    valid_positive = ('claude_models' not in cfg and valid_claude and raw_claude > 0)
    if valid_positive and not claude_disabled:
        adapter = anthropic_adapter(cfg)
        pin_conflict = claude_pin_conflict(cfg, raw_claude)
        if pin_conflict:
            append_exclusion(excluded, pin_conflict[0], pin_conflict[1])
        required_names = {
            'opus' if index == 0 else 'opus-%d' % (index + 1)
            for index in range(raw_claude)
        }
        matched = {s.get('substitutes_for') for s in seats
                   if not s['extra'] and s.get('substitutes_for') in required_names}
        matched.update(s['seat'] for s in seats
                       if s['adapter'] == adapter and not s['extra']
                       and not s.get('padded') and s['seat'] in required_names
                       and opus_model(s.get('model')))
        if len(matched) != raw_claude:
            summary = 'claude_seats requires %d matching seat(s), %d survived' \
                      % (raw_claude, len(matched))
            append_exclusion(excluded, 'claude_seats', 'strict: ' + summary)
            expected = {'claude', 'agent', 'anthropic'} | required_names
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


def pad(seats, excluded, cfg, probe_results):
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
    # The Agent tool needs no sign-in, so a CLI whose Opus probe just failed never pads the floor.
    adapter = anthropic_adapter(cfg)
    probe = probe_results.get(('claude', 'opus', 'max'))
    if adapter == 'claude' and probe is not None and probe[0] is not None:
        adapter = 'agent'
    used = {s['seat'] for s in seats}
    n = 0
    for _ in range(missing):
        n += 1
        name = 'claude-%d' % n
        while name in used:
            n += 1
            name = 'claude-%d' % n
        used.add(name)
        seat = make_seat(name, adapter, 'opus', 'max')
        seat['padded'] = True
        seats.append(seat)
    return missing


def degradation(seats, padded):
    """→ (labs, degraded, sentence). Degraded = padded at all, or only one lab left to disagree."""
    labs = []
    for s in seats:
        if not s['extra'] and s['lab'] not in labs:
            labs.append(s['lab'])
    substitutions = [s for s in seats if not s['extra'] and s.get('substitutes_for')]
    if substitutions:
        detail = ', '.join('%s -> %s' % (s['substitutes_for'], s['seat'])
                           for s in substitutions)
        return labs, True, 'quota fallback: %s; reduced provider diversity' % detail
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

def build(do_probe, quota_failed_seats=()):
    cfg, cfg_error = load_config()
    if cfg_error:
        roster = {
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'seats': [],
            'labs': [],
            'padded': 0,
            'degraded': True,
            'degradation': 'configuration is unreadable - reviewer selection refused',
            'strict_class': 'config',
            'strict_reason': cfg_error,
            'excluded': [{'cli': 'config', 'reason': cfg_error}],
        }
        return roster, {}, 'config'
    _RESOLVED.clear()
    excluded = []
    dropped = excluded_names(cfg)
    seats, adapter_of = [], {}

    for adapter in provider_order(cfg):
        name = NAMES[adapter]
        if {name, adapter, LABS[adapter]} & dropped:
            excluded.append({'cli': name, 'reason': 'excluded by config'})
            continue
        found, reason = DETECT[adapter](cfg)
        if reason:
            excluded.append({'cli': name, 'reason': reason})
        seats.extend(found)

    # Extras are built BEFORE exclusion and pins so config can address them by seat name
    # (`exclude: ["codex-review"]`, `pin: {"codex-review": ...}`), then follow their base lab through the probe.
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
    kept = enforce_claude_models(cfg, kept, excluded)
    preferred_labs = {s['seat']: s['lab'] for s in kept if not s['extra']}

    fallback_enabled, _ = quota_fallback_setting(cfg)
    handoff_error = quota_handoff_error(
        quota_failed_seats, do_probe, fallback_enabled, kept)
    if handoff_error:
        append_exclusion(excluded, 'quota_fallback', 'strict: ' + handoff_error)
    static_class = None
    probe_results = {}
    if do_probe:
        static_excluded = [dict(entry) for entry in excluded]
        static_class, _ = enforce_exact_seats(cfg, kept, static_excluded)
    if handoff_error:
        static_class = 'config'
    if do_probe and static_class != 'config':
        survivors = []
        targets = {}
        for s in kept:
            key = (s['adapter'], s['model'], s.get('effort'))
            if s['adapter'] in PROBE_CMD:
                targets.setdefault(key, s)
        with ThreadPoolExecutor(max_workers=min(4, len(targets) or 1)) as pool:
            pending = {key: pool.submit(probe_seat, seat) for key, seat in targets.items()}
            try:
                probe_results = {key: pending[key].result() for key in targets}
            except BaseException:
                cancel_active_process_groups()
                for future in pending.values():
                    future.cancel()
                raise
        used = {s['seat'] for s in kept}
        counters = {}
        policy_failures = []
        forced_quota = set(quota_failed_seats)
        for s in kept:
            key = (s['adapter'], s['model'], s.get('effort'))
            result = (('probe failed', 'quota', 'quota exhausted')
                      if s['seat'] in forced_quota else probe_results.get(key))
            if result is None or result[0] is None:
                survivors.append(s)
                continue
            reason, failure_class, cause = result
            eligible = fallback_enabled and not s['extra'] and s['lab'] in ('openai', 'anthropic')
            if eligible and failure_class == 'quota':
                target = fallback_target(s, kept, probe_results, forced_quota)
                if target is not None:
                    substitute = fallback_seat(target, s, used, counters)
                    survivors.append(substitute)
                    adapter_of[substitute['seat']] = substitute['adapter']
                    excluded.append({
                        'cli': s['seat'],
                        'reason': 'probe %s; substituted by %s' % (cause, substitute['seat']),
                    })
                    continue
                reason = 'probe %s; fallback target unavailable' % cause
                policy_failures.append('%s has no usable fallback target' % s['seat'])
            elif eligible:
                policy_failures.append('%s failed outside the quota fallback policy' % s['seat'])
            excluded.append({'cli': s['seat'], 'reason': reason})
        kept = survivors
    else:
        policy_failures = []
    # an extra rides on its lab: no surviving base seat → no extra
    kept = [s for s in kept if not s['extra'] or any(
        b['adapter'] == s['adapter'] and b['model'] == s['model'] and not b['extra']
        for b in kept)]

    policy_class = None
    policy_reason = None
    if policy_failures:
        policy_class = 'availability'
        policy_reason = '; '.join(policy_failures)
        append_exclusion(excluded, 'quota_fallback', 'strict: ' + policy_reason)
    exact_class, exact_reason = enforce_exact_seats(cfg, kept, excluded)
    exact_class, exact_reason = strict_winner(
        'config' if handoff_error else None, handoff_error,
        exact_class, exact_reason)
    exact_class, exact_reason = strict_winner(
        policy_class, policy_reason, exact_class, exact_reason)

    # Padding comes LAST - after config, after exclusions, after the probe - so it replaces the seats
    # those steps actually removed rather than a count taken before they ran.
    pad(kept, excluded, cfg, probe_results)
    padded = len([s for s in kept if not s['extra'] and s.get('padded')])
    labs, degraded, sentence = degradation(kept, padded)

    # Strict mode counts the labs that were actually DETECTED. Padded Claude seats are not a second
    # opinion, so they must not satisfy a floor whose whole purpose is to demand one - with
    # `claude_seat: false` and one real lab, counting them would let `min_labs: 2` pass on one lab.
    # `floor > 1` keeps the default of 1 unable to refuse anything: a bare machine with the Claude seat
    # turned off has ZERO real labs and still gets a padded panel, which is the point of this task.
    floor, floor_error = min_labs_setting(cfg)
    real = [l for l in labs
            if any(s['lab'] == l and not s['extra'] and not s.get('padded') for s in kept)]
    quota_labs = {preferred_labs.get(s.get('substitutes_for')) for s in kept
                  if not s['extra'] and s.get('substitutes_for')}
    quota_labs.discard(None)
    quota_floor_met = (not floor_error and fallback_enabled and quota_labs
                       and len(set(real) | quota_labs) >= floor)
    labs_strict = (not floor_error and (floor > 1 or CODEX_HOST)
                   and len(real) < floor and not quota_floor_met)
    if labs_strict:
        append_exclusion(excluded, 'min_labs',
                         'strict: %d lab(s) available, min_labs=%d' % (len(real), floor))
    elif not floor_error and len(real) < floor and quota_floor_met:
        append_exclusion(excluded, 'quota_fallback',
                         'min_labs=%d temporarily waived for quota substitution' % floor)
    labs_reason = (None if floor_error else
                   '%d lab(s) available, min_labs=%d' % (len(real), floor))
    strict_class = ('config' if exact_class == 'config' else
                    'availability' if exact_class or labs_strict else None)
    strict_reason = exact_reason if exact_class else (labs_reason if labs_strict else None)

    roster = {'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'seats': kept, 'labs': labs, 'padded': padded, 'degraded': degraded}
    if degraded:
        roster['degradation'] = sentence
    if plan_seats_setting(cfg)[0] == 'all':
        roster['plan_seats'] = 'all'
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
                  if NAMES[s['adapter']] == name and not s['extra'] and not s.get('padded')]
        if seated:
            models = ', '.join(s['model'] + ('@' + s['effort'] if s['effort'] else '') for s in seated)
            parts.append('%s ✓ (%s)' % (name, models))
        else:
            reason = by_cli.get(name) or next(
                (e['reason'] for e in roster['excluded']
                 if NAMES.get(adapter_of.get(e['cli'])) == name),
                'unavailable')
            # `claude ✗ disabled` beside `DEGRADED: only Claude is available` reads as a contradiction:
            # the detected seat IS off and padded seats of that lab are in the panel. Name them here.
            n = len([s for s in roster['seats']
                     if NAMES[s['adapter']] == name and not s['extra'] and s.get('padded')])
            if n:
                reason += ' (%d padded seat%s)' % (n, '' if n == 1 else 's')
            parts.append('%s ✗ %s' % (name, reason))
    if any(e.get('reason') == 'config unreadable' for e in roster['excluded']):
        parts.append('config unreadable (reviewer selection refused)')
    line = 'review-council seats: ' + ' · '.join(parts)
    if roster.get('degraded'):
        line += ' · DEGRADED: ' + (roster.get('degradation') or 'the panel is short of voices')
    if roster.get('strict_class'):
        line += ' · STRICT %s: %s' % (roster['strict_class'], roster.get('strict_reason'))
    return line


def usage(message):
    sys.stderr.write(
        'roster: %s\nusage: roster.sh [--json|--brief] [--probe] '
        '[--quota-failed-seat <seat>] [--write <file>]\n' % message)
    return 1


def main(argv):
    if len(argv) == 3 and argv[0] == '--classify-log':
        try:
            with open(argv[2], encoding='utf-8', errors='replace') as stream:
                content = stream.read()
        except OSError:
            content = ''
        failure_class, _ = classify_provider_failure(argv[1], summary_log=content)
        sys.stdout.write(failure_class + '\n')
        return 0
    fmt, do_probe, write = 'json', False, None
    quota_failed_seats = []
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == '--json':
            fmt = 'json'
        elif a == '--brief':
            fmt = 'brief'
        elif a == '--probe':
            do_probe = True
        elif a == '--quota-failed-seat':
            if not args:
                return usage('--quota-failed-seat needs a seat')
            quota_failed_seats.append(args.pop(0))
        elif a == '--write':
            if not args:
                return usage('--write needs a file')
            write = args.pop(0)
        else:
            return usage('unknown argument %s' % a)

    if quota_failed_seats and not do_probe:
        return usage('--quota-failed-seat requires --probe')
    session_write = None
    if write:
        write_path = Path(write)
        resolved_write = write_path.resolve()
        if write_path.name == 'roster.json':
            session_write = write_path
        elif resolved_write.name == 'roster.json':
            session_write = resolved_write
        if session_write is not None:
            try:
                assert_unsealed(session_write.parent)
            except SessionInputsError as exc:
                sys.stderr.write('roster: cannot write %s: %s\n' % (write, exc))
                return 1
    roster, adapter_of, strict_class = build(do_probe, quota_failed_seats)
    if write:
        roster['result_receipts'] = result_receipt_policy(write)
    text = json.dumps(roster, indent=2, ensure_ascii=False) + '\n'
    if write:
        try:
            if session_write is not None:
                install_inputs(session_write.parent, {'roster.json': text.encode('utf-8')},
                               complete=False)
            else:
                tmp = write + '.new'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(text)
                os.replace(tmp, write)
        except (OSError, SessionInputsError) as exc:
            sys.stderr.write('roster: cannot write %s: %s\n' % (write, exc))
            return 1
    sys.stdout.write(text if fmt == 'json' else brief_line(roster, adapter_of) + '\n')
    if strict_class == 'config':
        return 6
    return 5 if strict_class == 'availability' else 0


if __name__ == '__main__':
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, cancellation_signal)
    try:                                  # a C-locale shell must not break the ✓/✗/· line
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        cancel_active_process_groups()
        sys.exit(130)
