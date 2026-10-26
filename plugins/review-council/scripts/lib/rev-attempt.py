#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

LIB_DIR = Path(__file__).resolve().parent
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))
from session_inputs import session_input_lock

TERMINAL_EXITS = ('1', '2')
RECORDED_EXITS = ('0', '1', '2', '3', '4', '7', '129', '130', '143')
PROVIDER_FAILURE_EXITS = ('3',)
PROVIDER_CANCELLATION_EXITS = ('129', '130', '143')


def safe_regular(path):
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return not path.is_symlink() and stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def private_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                         | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('artifact is not a private regular file: ' + path.name)
        raw = stream.read()
        after = os.fstat(stream.fileno())
        current = path.lstat()
        def identity(metadata):
            return (metadata.st_dev, metadata.st_ino, metadata.st_size,
                    metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_nlink)
        if (not stat.S_ISREG(current.st_mode) or identity(before) != identity(after)
                or identity(after) != identity(current)):
            raise ValueError('artifact changed while reading: ' + path.name)
    return raw


def hard_audit_failure(audit: Path) -> bool:
    if not safe_regular(audit) or audit.stat().st_size == 0:
        return False
    try:
        result = json.loads(audit.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return (result.get('schema_version') == 2 and result.get('status') == 'invalid'
            and result.get('evidence_scoped') is True)


def incomplete_summary(document) -> bool:
    return (isinstance(document, dict) and isinstance(document.get('summary'), str)
            and document['summary'].startswith('INCOMPLETE PROOF'))


def semantic_rejection_path(session, panel, seat):
    return session / f'r{panel}-{seat}.semantic-rejection.json'


def semantic_rejection(session, panel, seat):
    path = semantic_rejection_path(session, panel, seat)
    try:
        record = json.loads(private_bytes(path))
    except FileNotFoundError:
        return None
    if (not isinstance(record, dict) or set(record) != {
            'schema_version', 'label', 'seat', 'generation', 'obligation', 'evidence', 'reason'}
            or type(record['schema_version']) is not int or record['schema_version'] != 1
            or record['label'] != panel or record['seat'] != seat
            or any(not isinstance(record[key], str) or not record[key].strip()
                   for key in ('obligation', 'evidence', 'reason'))):
        raise ValueError('invalid semantic rejection: ' + seat)
    generation = record['generation']
    stem = f'r{panel}-{seat}'
    manifest_name = f'r{panel}-evidence.manifest.json'
    if (not isinstance(generation, dict) or generation.get('label') != panel
            or generation.get('seat') != seat or generation.get('manifest') != manifest_name):
        raise ValueError('invalid semantic rejection generation: ' + seat)
    manifest = json.loads(private_bytes(session / manifest_name))
    if (not isinstance(manifest, dict) or not isinstance(manifest.get('assignments'), dict)
            or not isinstance(manifest.get('inputs'), dict)
            or not isinstance(manifest.get('unenforced_seats', []), list)):
        raise ValueError('invalid semantic rejection manifest: ' + seat)
    assignment = manifest['assignments'].get(seat)
    enforced = seat not in manifest.get('unenforced_seats', [])
    if (not isinstance(assignment, dict) or generation.get('enforced') is not enforced
            or generation.get('adapter') != assignment.get('adapter')):
        raise ValueError('invalid semantic rejection assignment: ' + seat)
    bindings = {'manifest_sha256': manifest_name, 'prompt_sha256': stem + '.prompt.md',
                'result_sha256': stem + '.json', 'exit_sha256': stem + '.exit',
                'stream_sha256': stem + '.stream.ndjson', 'audit_sha256': stem + '.read-audit.json'}
    for key, name in bindings.items():
        expected = generation.get(key)
        if key in ('stream_sha256', 'audit_sha256') and expected is None and not enforced:
            continue
        if (not isinstance(expected, str) or len(expected) != 64
                or not set(expected) <= set('0123456789abcdef')
                or hashlib.sha256(private_bytes(session / name)).hexdigest() != expected):
            raise ValueError('stale semantic rejection binding: ' + seat + ' ' + key)
    encoded_assignment = (json.dumps(assignment, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode()
    if (manifest.get('session') != str(session.resolve()) or manifest.get('label') != panel
            or assignment is None or generation.get('snapshot_tree') != manifest.get('snapshot_tree')
            or generation.get('roster_sha256') != manifest.get('inputs', {}).get('roster.json')
            or generation.get('assignment_sha256') != hashlib.sha256(encoded_assignment).hexdigest()
            or private_bytes(session / (stem + '.exit')).strip() != b'0'):
        raise ValueError('invalid semantic rejection identity: ' + seat)
    prompt = private_bytes(session / (stem + '.prompt.md')).decode('utf-8')
    result = json.loads(private_bytes(session / (stem + '.json')))
    if (not isinstance(result, dict) or not isinstance(result.get('summary'), str)
            or record['obligation'] not in prompt or record['evidence'] not in result['summary']
            or prompt.splitlines().count('Evidence manifest SHA-256: ' + generation['manifest_sha256']) != 1):
        raise ValueError('unbound semantic rejection evidence: ' + seat)
    return record


def publish_semantic_rejection(session, panel, seat, raw):
    path = semantic_rejection_path(session, panel, seat)
    descriptor, temporary = tempfile.mkstemp(prefix='.semantic-rejection-', dir=session)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if private_bytes(path) != raw:
                raise ValueError('semantic rejection is immutable: ' + seat)
    finally:
        os.unlink(temporary)


def incomplete_proof(result: Path) -> bool:
    try:
        raw = private_bytes(result)
    except FileNotFoundError:
        return False
    try:
        return incomplete_summary(json.loads(raw))
    except (ValueError, RecursionError):
        return False


def latched(session: Path, panel: str, seat: str) -> bool:
    """A hard audit failure latches only its own (label, seat); siblings and later labels launch."""
    invalid = session / f'r{panel}-{seat}.audit-invalid.json'
    return ((safe_regular(invalid) and invalid.stat().st_size > 0)
            or hard_audit_failure(session / f'r{panel}-{seat}.read-audit.json'))


def record_path(session: Path, panel: str, seat: str, prompt: Path):
    identity = {'panel': panel, 'seat': seat,
                'prompt_sha256': hashlib.sha256(prompt.resolve().read_bytes()).hexdigest()}
    return session / 'attempts' / (hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest() + '.json'), identity


def retirement_path(session: Path, panel: str, seat: str):
    return session / f'r{panel}-{seat}.incomplete-proof'


def retired_incomplete_proof(session: Path, panel: str, seat: str) -> bool:
    try:
        record = json.loads(private_bytes(retirement_path(session, panel, seat)))
    except FileNotFoundError:
        return False
    if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
            or record['schema_version'] != 1
            or record.get('panel') != panel or record.get('seat') != seat
            or type(record.get('exit')) is not int or record['exit'] != 0
            or not incomplete_summary(record)
            or any(not isinstance(record.get(key), str) or len(record[key]) != 64
                   or not set(record[key]) <= set('0123456789abcdef')
                   for key in ('prompt_sha256', 'result_sha256'))):
        raise ValueError('invalid incomplete-proof retirement: ' + seat)
    return True


def remember_incomplete_proof(session: Path, panel: str, seat: str, prompt: Path):
    if retired_incomplete_proof(session, panel, seat):
        return
    result = session / f'r{panel}-{seat}.json'
    try:
        raw = private_bytes(result)
    except FileNotFoundError:
        return
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):
        return
    if not incomplete_summary(document):
        return
    _, identity = record_path(session, panel, seat, prompt)
    record = dict(identity, schema_version=1, exit=0, summary=document['summary'],
                  result_sha256=hashlib.sha256(raw).hexdigest())
    descriptor, _ = open_private(retirement_path(session, panel, seat))
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def completed_launch(session: Path, panel: str, seat: str, prompt: Path) -> bool:
    """Only the current explicit exit can establish an unrecorded completion."""
    exit_path = session / f'r{panel}-{seat}.exit'
    try:
        return private_bytes(exit_path).strip() == b'0'
    except FileNotFoundError:
        return False


def ended_by_incomplete_proof(session: Path, panel: str, seat: str, prompt: Path) -> bool:
    """A completed launch's INCOMPLETE PROOF result ends its assignment; a failed launch keeps its exact retry."""
    return (retired_incomplete_proof(session, panel, seat)
            or (completed_launch(session, panel, seat, prompt)
                and incomplete_proof(session / f'r{panel}-{seat}.json')))


def completed_attempt(session: Path, panel: str, seat: str, prompt: Path):
    try:
        path, identity = record_path(session, panel, seat, prompt)
        raw = private_bytes(path)
        current = json.loads(raw)
        final = private_bytes(session / f'r{panel}-{seat}.exit').strip().decode('ascii')
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    calls = current.get('calls') if isinstance(current, dict) else None
    launches = current.get('launches') if isinstance(current, dict) else None
    token = current.get('last_launch') if isinstance(current, dict) else None
    if (any(current.get(key) != value for key, value in identity.items())
            or current.get('lifecycle_version') != 2
            or type(calls) is not int or calls < 1
            or type(current.get('completed_calls')) is not int or current['completed_calls'] != calls
            or current.get('active_launch') is not None
            or current.get('terminal_intent') is not None
            or not isinstance(launches, list) or len(launches) != calls
            or any(type(code) is not int or str(code) not in RECORDED_EXITS for code in launches)
            or str(launches[-1]) != final or final not in RECORDED_EXITS
            or not isinstance(token, str) or len(token) != 32
            or not set(token) <= set('0123456789abcdef')):
        return None
    return {'exit': final, 'path': path, 'raw': raw, 'record': current,
            'sha256': hashlib.sha256(raw).hexdigest()}


def roster_adapter(session: Path, seat: str):
    try:
        roster = json.loads(private_bytes(session / 'roster.json'))
    except (OSError, ValueError, json.JSONDecodeError, RecursionError):
        return None
    rows = roster.get('seats') if isinstance(roster, dict) else None
    matches = [row for row in rows if isinstance(row, dict) and row.get('seat') == seat] \
        if isinstance(rows, list) else []
    if len(matches) != 1:
        return None
    adapter = matches[0].get('adapter')
    return adapter if adapter in ('codex', 'claude', 'gemini') else None


def recovery_record(session: Path, panel: str, seat: str):
    current_path = session / f'r{panel}-{seat}.provider-recovery.json'
    try:
        return json.loads(private_bytes(current_path)), current_path
    except FileNotFoundError:
        pass
    except (OSError, ValueError, json.JSONDecodeError, RecursionError):
        return None, current_path
    legacy_path = session / f'r{panel}-provider-recovery.json'
    try:
        return json.loads(private_bytes(legacy_path)), legacy_path
    except (OSError, ValueError, json.JSONDecodeError):
        return None, legacy_path


def provider_cancellation(session: Path, panel: str, seat: str, cancelled: dict) -> bool:
    record, path = recovery_record(session, panel, seat)
    if not isinstance(record, dict):
        return False
    trigger_seat = record.get('trigger_seat')
    cancelled_seat = record.get('cancelled_seat', record.get('cancelled_sibling'))
    trigger_exit = record.get('trigger_exit')
    cancellation_exit = record.get('cancellation_result')
    started = session / f'r{panel}-{seat}.started'
    try:
        started_identity = private_bytes(started).decode('utf-8')
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if (cancelled_seat != seat or trigger_exit != 3
            or str(cancellation_exit) != cancelled['exit']
            or cancellation_exit not in (129, 130, 143)
            or record.get('started_identity') != started_identity
            or roster_adapter(session, trigger_seat) is None
            or roster_adapter(session, trigger_seat) != roster_adapter(session, seat)):
        return False
    trigger_prompt = session / f'r{panel}-{trigger_seat}.prompt.md'
    trigger = completed_attempt(session, panel, trigger_seat, trigger_prompt)
    if trigger is None or trigger['exit'] != '3':
        return False
    if type(record.get('schema_version')) is int and record['schema_version'] == 1:
        expected = {'schema_version', 'panel', 'trigger_seat', 'trigger_exit',
                    'trigger_prompt_sha256', 'trigger_attempt_sha256', 'cancelled_seat',
                    'cancellation_result', 'cancelled_prompt_sha256',
                    'cancelled_attempt_sha256', 'started_identity', 'execution_handle'}
        if (set(record) != expected or record.get('panel') != panel
                or record.get('trigger_prompt_sha256') != record_path(
                    session, panel, trigger_seat, trigger_prompt)[1]['prompt_sha256']
                or record.get('trigger_attempt_sha256') != trigger['sha256']
                or record.get('cancelled_prompt_sha256') != cancelled['record']['prompt_sha256']
                or record.get('cancelled_attempt_sha256') != cancelled['sha256']
                or not isinstance(record.get('execution_handle'), str)
                or not record['execution_handle'].strip()):
            return False
    else:
        expected = {'trigger_seat', 'trigger_exit', 'diagnostic', 'claim',
                    'cancelled_sibling', 'owned_execution_handle', 'started_identity',
                    'cancellation_result', 'preserved_valid', 'source_unchanged'}
        if (path.name != f'r{panel}-provider-recovery.json' or set(record) != expected
                or type(record.get('trigger_exit')) is not int
                or type(record.get('owned_execution_handle')) is not int
                or record['owned_execution_handle'] <= 0
                or record.get('source_unchanged') is not True
                or any(not isinstance(record.get(key), str) or not record[key].strip()
                       for key in ('diagnostic', 'claim', 'preserved_valid'))):
            return False
    return True


def terminal_failure(session: Path, panel: str, seat: str, prompt: Path) -> bool:
    """The assignment failed for good under a recorded audit, provider, or retry outcome."""
    if (semantic_rejection(session, panel, seat) is not None
            or latched(session, panel, seat) or ended_by_incomplete_proof(session, panel, seat, prompt)):
        return True
    attempt = completed_attempt(session, panel, seat, prompt)
    if attempt is not None:
        if attempt['exit'] in PROVIDER_FAILURE_EXITS:
            return True
        if attempt['exit'] in PROVIDER_CANCELLATION_EXITS:
            return provider_cancellation(session, panel, seat, attempt)
    exit_path = session / f'r{panel}-{seat}.exit'
    try:
        path, _ = record_path(session, panel, seat, prompt)
        current = json.loads(private_bytes(path)) if safe_regular(path) else None
        launches = current.get('launches') if isinstance(current, dict) else None
        final = private_bytes(exit_path).strip().decode('ascii')
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (isinstance(launches, list) and len(launches) >= 2
            and all(str(code) in TERMINAL_EXITS for code in launches[-2:])
            and final in TERMINAL_EXITS)


def record_provider_cancellation(session: Path, panel: str, trigger_seat: str,
                                 cancelled_seat: str, execution_handle: str):
    safe = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-')
    if (not panel or not trigger_seat or not cancelled_seat
            or any(not value or not set(value) <= safe
                   for value in (panel, trigger_seat, cancelled_seat))
            or trigger_seat == cancelled_seat or not execution_handle.strip()):
        return 1
    directory = session / 'attempts'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode) \
            or directory.resolve().parent != session:
        return 1
    panel_key = hashlib.sha256(panel.encode()).hexdigest()
    try:
        panel_descriptor, _ = open_private(directory / ('.panel-' + panel_key + '.lock'))
    except (OSError, ValueError):
        return 1
    with os.fdopen(panel_descriptor, 'r+', encoding='utf-8') as panel_lock:
        fcntl.flock(panel_lock, fcntl.LOCK_EX)
        trigger_prompt = session / f'r{panel}-{trigger_seat}.prompt.md'
        cancelled_prompt = session / f'r{panel}-{cancelled_seat}.prompt.md'
        trigger = completed_attempt(session, panel, trigger_seat, trigger_prompt)
        cancelled = completed_attempt(session, panel, cancelled_seat, cancelled_prompt)
        if (trigger is None or trigger['exit'] != '3' or cancelled is None
                or cancelled['exit'] not in PROVIDER_CANCELLATION_EXITS
                or roster_adapter(session, trigger_seat) is None
                or roster_adapter(session, trigger_seat) != roster_adapter(session, cancelled_seat)):
            return 1
        try:
            started_identity = private_bytes(
                session / f'r{panel}-{cancelled_seat}.started').decode('utf-8')
        except (OSError, UnicodeDecodeError, ValueError):
            return 1
        trigger_identity = record_path(session, panel, trigger_seat, trigger_prompt)[1]
        event = {
            'schema_version': 1,
            'panel': panel,
            'trigger_seat': trigger_seat,
            'trigger_exit': 3,
            'trigger_prompt_sha256': trigger_identity['prompt_sha256'],
            'trigger_attempt_sha256': trigger['sha256'],
            'cancelled_seat': cancelled_seat,
            'cancellation_result': int(cancelled['exit']),
            'cancelled_prompt_sha256': cancelled['record']['prompt_sha256'],
            'cancelled_attempt_sha256': cancelled['sha256'],
            'started_identity': started_identity,
            'execution_handle': execution_handle,
        }
        path = session / f'r{panel}-{cancelled_seat}.provider-recovery.json'
        descriptor, temporary = tempfile.mkstemp(prefix='.provider-recovery-', dir=session)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(event, stream, sort_keys=True, separators=(',', ':'))
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        except FileExistsError:
            return 1
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return 0


def open_private(path):
    flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        descriptor = os.open(path, flags)
        created = False
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise ValueError('attempt state is not a private regular file')
    return descriptor, created


def open_existing_private(path):
    descriptor = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
                         | getattr(os, 'O_NONBLOCK', 0))
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise ValueError('attempt state is not a private regular file')
    return descriptor


def write_attempt(path, current):
    # The session and panel locks serialize writers across atomic inode replacement.
    descriptor, temporary = tempfile.mkstemp(prefix='.attempt-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(current, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_new_attempt(path, current):
    descriptor, temporary = tempfile.mkstemp(prefix='.attempt-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(current, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        # The caller holds the panel lock, so no reservation can race this absent-path check.
        if os.path.lexists(path):
            raise FileExistsError(f'attempt state already exists: {path.name}')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def archive_stream(session, panel, seat):
    raw = session / f'r{panel}-{seat}.stream.ndjson'
    try:
        if raw.stat().st_size == 0:
            return None
    except FileNotFoundError:
        return None
    n = 1
    while True:
        archived = session / f'r{panel}-{seat}.stream.attempt{n}.ndjson'
        if not os.path.lexists(archived):
            os.replace(raw, archived)
            return archived
        n += 1


def restore_stream(archived, raw):
    if archived is None:
        return
    if os.path.lexists(raw):
        raise OSError('cannot restore prior provider stream because its path is occupied')
    os.replace(archived, raw)


def recover_completion(session, panel, seat, prompt):
    path, identity = record_path(session, panel, seat, prompt)
    if not path.exists():
        return
    descriptor, _ = open_private(path)
    with os.fdopen(descriptor, 'r+', encoding='utf-8') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            current = json.load(stream)
        except json.JSONDecodeError:
            return
        if not isinstance(current, dict):
            return
        intent = current.get('terminal_intent')
        if intent is None:
            return
        calls = current.get('calls')
        if (any(current.get(key) != value for key, value in identity.items())
                or current.get('lifecycle_version') != 2
                or not isinstance(intent, dict) or set(intent) != {'token', 'calls', 'exit'}
                or type(calls) is not int or calls < 1
                or type(current.get('completed_calls')) is not int
                or not 0 <= current['completed_calls'] < calls
                or type(intent['calls']) is not int or intent['calls'] != calls
                or type(intent['exit']) is not int or str(intent['exit']) not in RECORDED_EXITS
                or not isinstance(intent['token'], str) or len(intent['token']) != 32
                or not set(intent['token']) <= set('0123456789abcdef')
                or intent['token'] != current.get('active_launch')):
            raise ValueError('unbound terminal completion intent')
        current['launches'] = [*current.get('launches', []), intent['exit']]
        current.update(completed_calls=calls, active_launch=None, last_launch=intent['token'])
        del current['terminal_intent']
        write_attempt(path, current)
    if intent['exit'] == 0:
        remember_incomplete_proof(session, panel, seat, prompt)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else None
    if command == 'record-provider-cancellation' and len(sys.argv) == 7:
        session = Path(sys.argv[2]).resolve()
        with session_input_lock(session):
            return record_provider_cancellation(session, *sys.argv[3:])
    if (command, len(sys.argv)) not in (('check', 6), ('reserve', 6), ('reserve', 7), ('record', 7), ('record', 8), ('complete', 8)):
        return 1
    token = sys.argv[-1] if (command, len(sys.argv)) in (('reserve', 7), ('record', 8), ('complete', 8)) else None
    if token is not None and (len(token) != 32 or not set(token) <= set('0123456789abcdef')):
        return 1
    session = Path(sys.argv[2]).resolve()
    # Preparation holds this lock through its final idle scan and generation publication.
    with session_input_lock(session):
        return _main_locked(session, command, token)


def _main_locked(session, command, token):
    panel, seat = sys.argv[3], sys.argv[4]
    safe = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-')
    if not panel or not seat or not set(panel) <= safe or not set(seat) <= safe:
        return 1
    directory = session / 'attempts'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode) \
            or directory.resolve().parent != session:
        return 1
    panel_key = hashlib.sha256(panel.encode()).hexdigest()
    try:
        panel_descriptor, _ = open_private(directory / ('.panel-' + panel_key + '.lock'))
    except (OSError, ValueError):
        return 1
    with os.fdopen(panel_descriptor, 'r+', encoding='utf-8') as panel_lock:
        fcntl.flock(panel_lock, fcntl.LOCK_EX)
        if command in ('check', 'reserve'):
            recover_completion(session, panel, seat, Path(sys.argv[5]))
        if command in ('check', 'reserve') and semantic_rejection(session, panel, seat) is not None:
            print(f'{seat} under label {panel} has a semantic rejection; replace the assignment '
                  'on another eligible seat, never relaunch it', file=sys.stderr)
            return 2
        if command in ('check', 'reserve') and latched(session, panel, seat):
            print(f'{seat} under label {panel} failed a hard evidence audit; replace the assignment '
                  'on another eligible seat, never relaunch it', file=sys.stderr)
            return 2
        if command in ('check', 'reserve') and ended_by_incomplete_proof(session, panel, seat, Path(sys.argv[5])):
            remember_incomplete_proof(session, panel, seat, Path(sys.argv[5]))
            print(f'{seat} under label {panel} returned an INCOMPLETE PROOF result; replace the assignment '
                  'on another eligible seat, never relaunch it', file=sys.stderr)
            return 2
        if command == 'check':
            return 0
        path, identity = record_path(session, panel, seat, Path(sys.argv[5]))
        try:
            descriptor = open_existing_private(path)
        except FileNotFoundError:
            if command != 'reserve':
                return 1
            try:
                archived_stream = archive_stream(session, panel, seat)
            except OSError:
                return 1
            current = dict(identity, calls=1)
            if token is not None:
                current.update(lifecycle_version=2, completed_calls=0,
                               active_launch=token, last_launch=None)
            try:
                publish_new_attempt(path, current)
            except OSError as error:
                restore_error = None
                try:
                    restore_stream(archived_stream, session / f'r{panel}-{seat}.stream.ndjson')
                except OSError as failure:
                    restore_error = failure
                if restore_error is not None:
                    raise OSError(f'{error}; {restore_error}') from error
                raise
            return 0
        except (OSError, ValueError):
            return 1
        with os.fdopen(descriptor, 'r+', encoding='utf-8') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            try:
                current = json.load(stream)
            except (json.JSONDecodeError, ValueError):
                return 1
            if any(current.get(field) != value for field, value in identity.items()):
                return 1
            calls = current.get('calls')
            if type(calls) is not int or calls < 0:
                return 1
            if 'lifecycle_version' in current and (type(current['lifecycle_version']) is not int
                                                    or current['lifecycle_version'] != 2):
                return 1
            bound = current.get('lifecycle_version') == 2
            if token is not None:
                if not bound:
                    if calls or current.get('launches'):
                        print('legacy attempt cannot acquire an inferred completion watermark', file=sys.stderr)
                        return 1
                    current.update(lifecycle_version=2, completed_calls=0, active_launch=None, last_launch=None)
                completed = current.get('completed_calls')
                active = current.get('active_launch')
                if type(completed) is not int or not 0 <= completed <= calls:
                    return 1
                if command in ('record', 'complete'):
                    if active != token or completed == calls:
                        return 1
                elif (active is not None and active != token) or current.get('last_launch') == token:
                    return 1
                elif active is None and completed != calls:
                    return 1
            elif bound:
                return 1
            if command in ('record', 'complete'):
                if sys.argv[6] not in RECORDED_EXITS:
                    return 1
                intent = dict(token=token, calls=calls, exit=int(sys.argv[6]))
                if current.get('terminal_intent') not in (None, intent):
                    return 1
                if command == 'complete':
                    current['terminal_intent'] = intent
                else:
                    current['launches'] = [*current.get('launches', []), int(sys.argv[6])]
                    if token is not None:
                        current.update(completed_calls=calls, active_launch=None, last_launch=token)
                    current.pop('terminal_intent', None)
            elif calls >= 4:
                return 7
            else:
                archived_stream = None
                if command == 'reserve':
                    try:
                        archived_stream = archive_stream(session, panel, seat)
                    except OSError:
                        raise
                current['calls'] = calls + 1
                if token is not None:
                    current['active_launch'] = token
            try:
                write_attempt(path, current)
            except OSError as error:
                restore_error = None
                if command == 'reserve':
                    try:
                        restore_stream(archived_stream, session / f'r{panel}-{seat}.stream.ndjson')
                    except OSError as failure:
                        restore_error = failure
                if restore_error is not None:
                    raise OSError(f'{error}; {restore_error}') from error
                raise error
        if command == 'record' and sys.argv[6] == '0':
            remember_incomplete_proof(session, panel, seat, Path(sys.argv[5]))
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RecursionError, RuntimeError) as error:
        print('attempt state: ' + str(error), file=sys.stderr)
        sys.exit(1)
