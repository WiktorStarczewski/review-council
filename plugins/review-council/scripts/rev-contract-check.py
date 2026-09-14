#!/usr/bin/env python3
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time


BOUNDARIES = (
    'agents/rev-reviewer.md',
    'agents/rev-reviewer-sonnet.md',
    'codex-skills/rev/SKILL.md',
    'schema/findings.schema.json',
    'scripts/lib/review-read-audit.py',
    'scripts/lib/stream-summary.py',
    'scripts/lib/validate-findings.py',
    'scripts/rev-contract-check.py',
    'scripts/rev-evidence.py',
    'scripts/rev-preflight.sh',
    'scripts/rev-prompt.sh',
    'scripts/rev-seat.sh',
    'scripts/roster.sh',
    'skills/rev/SKILL.md',
)
CONTRACT_TREES = ('scripts/lib/', 'scripts/seats.d/', 'tests/')
CONTRACT_FILES = (
    'tests/fixtures/codex-stream.ndjson',
    'tests/fixtures/grok-stream.ndjson',
    'tests/fixtures/provider-contract-claude.ndjson',
    'tests/fixtures/provider-contract-codex.ndjson',
    'tests/fixtures/provider-contract-grok.ndjson',
    'tests/run-tests.sh',
    'tests/t-plan-evidence.sh',
    'tests/t-provider-contract.sh',
    'tests/t-read-bounds.sh',
    'tests/t-rev-reviewer.sh',
)
CONTRACT_TESTS = (
    'provider_envelope_replay', 'read_audit_binds_delivered_output', 'plan_evidence',
    'rev_reviewer')
POLICY_LIMITS = {
    'shared_deadline_seconds': ('REVIEW_COUNCIL_CONTRACT_DEADLINE_SECONDS', 300, 1, 3600),
    'output_bytes': ('REVIEW_COUNCIL_CONTRACT_OUTPUT_BYTES', 4 * 1024 * 1024, 1024, 64 * 1024 * 1024),
    'diagnostic_bytes': ('REVIEW_COUNCIL_CONTRACT_DIAGNOSTIC_BYTES', 8192, 128, 64 * 1024),
    'term_grace_seconds': ('REVIEW_COUNCIL_CONTRACT_TERM_GRACE_SECONDS', 2, 1, 30),
}
_ACTIVE_GROUPS = {}
_ACTIVE_LOCK = threading.RLock()
_CANCELLED = threading.Event()
_LAUNCH_STATE = threading.local()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(root, *args):
    result = subprocess.run(
        ['git', '-C', str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise ValueError(result.stderr.decode(errors='replace').strip() or 'git command failed')
    return result.stdout


def source_plugin(root):
    nested = root / 'plugins' / 'review-council'
    if (nested / '.codex-plugin' / 'plugin.json').is_file():
        return nested, 'plugins/review-council/'
    if (root / '.codex-plugin' / 'plugin.json').is_file() and (root / 'scripts').is_dir():
        return root, ''
    return None, None


def changed_paths(root, base):
    raw = git(root, 'diff', '--no-renames', '--name-only', '-z', base, '--')
    raw += git(root, 'ls-files', '-z', '--others', '--exclude-standard')
    return {part.decode('utf-8', errors='surrogateescape') for part in raw.split(b'\0') if part}


def is_boundary(path, prefix):
    if not path.startswith(prefix):
        return False
    relative = path[len(prefix):]
    return is_contract_input(relative)


def is_contract_input(relative):
    parts = Path(relative).parts
    if '__pycache__' in parts or Path(relative).suffix == '.pyc':
        return False
    return relative in CONTRACT_FILES or relative in BOUNDARIES or any(
        relative.startswith(directory) for directory in CONTRACT_TREES)


def file_hashes(plugin):
    paths = set(CONTRACT_FILES)
    paths.update(BOUNDARIES)
    for directory in CONTRACT_TREES:
        paths.update(str(path.relative_to(plugin)) for path in (plugin / directory).rglob('*')
                     if path.is_file() and is_contract_input(str(path.relative_to(plugin))))
    hashes = {}
    for name in sorted(paths):
        path = plugin / name
        hashes[name] = digest(path.read_bytes()) if path.is_file() else None
    return hashes


def subject_boundary_hashes(plugin, prefix, touched):
    root = plugin.resolve()
    hashes = {}
    for name in touched:
        relative = name[len(prefix):]
        path = plugin / relative
        if not contains(root, path.parent.resolve()):
            raise ValueError('subject boundary path escapes the reviewed plugin')
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            hashes[relative] = None
            continue
        if stat.S_ISLNK(metadata.st_mode):
            target = os.fsencode(os.readlink(path))
            hashes[relative] = {'kind': 'symlink', 'sha256': digest(target)}
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError('subject boundary is not a regular file or symlink: ' + relative)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            current = os.fstat(stream.fileno())
            if (not stat.S_ISREG(current.st_mode)
                    or (current.st_dev, current.st_ino, current.st_mode)
                    != (metadata.st_dev, metadata.st_ino, metadata.st_mode)):
                raise ValueError('subject boundary changed while hashing: ' + relative)
            value = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65536), b''):
                value.update(chunk)
        hashes[relative] = {
            'kind': 'regular',
            'mode': stat.S_IMODE(current.st_mode),
            'sha256': value.hexdigest(),
        }
    return hashes


def contains(root, path):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def regular_executable(path, source):
    path = Path(path).expanduser().absolute()
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(source + ' contract runner is unavailable') from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
        raise ValueError(source + ' contract runner must be a regular executable file')
    return path.resolve(), path, digest(path.read_bytes())


def execution_policy():
    result = {}
    for key, (name, default, minimum, maximum) in POLICY_LIMITS.items():
        raw = os.environ.get(name)
        try:
            value = default if raw is None else int(raw)
        except ValueError as error:
            raise ValueError('invalid ' + name) from error
        if value < minimum or value > maximum:
            raise ValueError('invalid ' + name)
        result[key] = value
    if result['diagnostic_bytes'] > result['output_bytes']:
        raise ValueError('contract diagnostic limit exceeds output limit')
    return result


def contract_executor(subject_plugin, subject_alias):
    plugin = Path(__file__).resolve().parents[1]
    manifest = plugin / '.codex-plugin' / 'plugin.json'
    if not manifest.is_file() or not (plugin / 'scripts').is_dir():
        raise ValueError('checker-owned plugin root is unavailable')
    override = os.environ.get('REVIEW_COUNCIL_CONTRACT_RUNNER')
    if override:
        runner, requested_runner, runner_hash = regular_executable(override, 'override')
        if (plugin != subject_plugin
                and (contains(subject_alias.absolute(), requested_runner)
                     or contains(subject_plugin.absolute(), requested_runner)
                     or contains(subject_plugin.resolve(), runner))):
            raise ValueError('contract runner must be outside the foreign review target')
        policy = 'external-override'
    else:
        runner, _, runner_hash = regular_executable(
            plugin / 'tests' / 'run-tests.sh', 'checker-owned')
        policy = 'checker-owned'
    return plugin, runner, {
        'policy': policy,
        'plugin': str(plugin),
        'runner': str(runner),
        'runner_sha256': runner_hash,
        'execution': execution_policy(),
    }


def bounded_setting(name, default, minimum, maximum):
    raw = os.environ.get(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as error:
        raise ValueError('invalid ' + name) from error
    if value < minimum or value > maximum:
        raise ValueError('invalid ' + name)
    return value


def register_group(group):
    process = group['process']
    with _ACTIVE_LOCK:
        _ACTIVE_GROUPS[process.pid] = group
        cancelled = _CANCELLED.is_set()
    if cancelled:
        terminate_groups([group], 1)
        unregister_group(group)
        return False
    return True


def unregister_group(group):
    with _ACTIVE_LOCK:
        _ACTIVE_GROUPS.pop(group['process'].pid, None)


def begin_group_launch():
    _LAUNCH_STATE.depth = getattr(_LAUNCH_STATE, 'depth', 0) + 1


def finish_group_launch():
    depth = _LAUNCH_STATE.depth - 1
    _LAUNCH_STATE.depth = depth
    if depth == 0 and hasattr(_LAUNCH_STATE, 'pending_signal'):
        signum = _LAUNCH_STATE.pending_signal
        del _LAUNCH_STATE.pending_signal
        cancel_active_groups()
        raise SystemExit(128 + signum)


def cancel_active_groups():
    _CANCELLED.set()
    with _ACTIVE_LOCK:
        groups = list(_ACTIVE_GROUPS.values())
    terminate_groups(groups, 1)


def cancellation_signal(signum, _frame):
    _CANCELLED.set()
    if getattr(_LAUNCH_STATE, 'depth', 0):
        _LAUNCH_STATE.pending_signal = signum
        return
    cancel_active_groups()
    raise SystemExit(128 + signum)


def launch_group(command, values, grace, **options):
    process = None
    group = None
    begin_group_launch()
    try:
        try:
            process = subprocess.Popen(command, **options)
            group = dict(values)
            group['process'] = process
            registered = register_group(group)
        finally:
            finish_group_launch()
    except BaseException:
        if process is not None:
            owned = group if group is not None else {'process': process}
            terminate_groups([owned], grace)
            unregister_group(owned)
            if process.stdout is not None and not process.stdout.closed:
                process.stdout.close()
        raise
    if not registered:
        process.stdout.close()
        return None
    return group


def run_provider_version(command, timeout, output_limit):
    try:
        group = launch_group(
            command, {}, 1, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, 'NO_COLOR': '1', 'TERM': 'dumb'})
    except OSError:
        return None
    if group is None:
        return None
    process = group['process']
    selector = selectors.DefaultSelector()
    output = bytearray()
    complete = False
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            events = selector.select(min(0.05, remaining))
            for key, _ in events:
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if len(output) + len(chunk) > output_limit:
                    return None
                output.extend(chunk)
        remaining = max(0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            return None
        if group_alive(process.pid):
            return None
        complete = True
        return process.returncode, bytes(output)
    finally:
        if not complete:
            terminate_groups([group], 1)
        if process.stdout is not None and not process.stdout.closed:
            try:
                selector.unregister(process.stdout)
            except KeyError:
                pass
            process.stdout.close()
        selector.close()
        unregister_group(group)


def one_version(name):
    path = shutil.which(name)
    if path is None:
        return name, 'missing'
    timeout = bounded_setting(
        'REVIEW_COUNCIL_CONTRACT_VERSION_TIMEOUT_SECONDS', 5, 1, 60)
    output_limit = bounded_setting(
        'REVIEW_COUNCIL_CONTRACT_VERSION_OUTPUT_BYTES', 64 * 1024, 256, 1024 * 1024)
    result = run_provider_version([path, '--version'], timeout, output_limit)
    if result is None:
        return name, 'unavailable'
    returncode, raw = result
    first = raw.decode(errors='replace').strip().splitlines()
    value = first[0][:240] if returncode == 0 and first else 'exit-' + str(returncode)
    return name, value


def provider_versions(adapters):
    names = sorted(set(adapters) & {'claude', 'codex', 'gemini'})
    override = os.environ.get('REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS')
    if override:
        value = json.loads(override)
        if not isinstance(value, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) or not v.strip()
                for k, v in value.items()):
            raise ValueError('invalid REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS')
        if any(name not in value for name in names):
            raise ValueError('incomplete REVIEW_COUNCIL_CONTRACT_PROVIDER_VERSIONS')
        versions = {name: value[name] for name in names}
    elif not names:
        versions = {}
    else:
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            futures = [pool.submit(one_version, name) for name in names]
            try:
                versions = dict(future.result() for future in futures)
            except BaseException:
                cancel_active_groups()
                for future in futures:
                    future.cancel()
                raise
    unavailable = sorted(name for name, version in versions.items()
                         if version in ('missing', 'unavailable') or version.startswith('exit-'))
    if unavailable:
        raise ValueError('provider versions unavailable: ' + ', '.join(unavailable))
    return versions


def core_roster(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not isinstance(data.get('seats'), list):
        raise ValueError('invalid provider contract roster')
    result = []
    for row in data['seats']:
        if not isinstance(row, dict):
            raise ValueError('invalid provider contract roster')
        if row.get('adapter') not in ('codex', 'gemini', 'claude', 'agent'):
            raise ValueError('provider contract roster contains an unsupported or retired adapter')
        if row.get('extra'):
            continue
        item = {name: row.get(name) for name in ('seat', 'adapter', 'model', 'effort')}
        if (any(not isinstance(item[name], str) or not item[name]
                for name in ('seat', 'adapter', 'model'))
                or item['effort'] is not None
                and (not isinstance(item['effort'], str) or not item['effort'])):
            raise ValueError('provider contract core roster lacks an exact identity')
        result.append(item)
    if not result or len({row['seat'] for row in result}) != len(result):
        raise ValueError('invalid provider contract core roster')
    return result


def contract_identity(plugin, executor, roster, touched, subject_boundaries):
    core = core_roster(roster)
    return {
        'schema_version': 2,
        'boundaries': file_hashes(plugin),
        'executor': executor,
        'provider_versions': provider_versions(row['adapter'] for row in core),
        'core_roster': core,
        'subject_boundaries': subject_boundaries,
        'touched_boundaries': touched,
        'tests': list(CONTRACT_TESTS),
    }


def validate_receipt(raw, identity, key, touched, source):
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError('invalid ' + source + ' contract receipt') from error
    expected = {
        'schema_version': 2,
        'key': key,
        'identity': identity,
        'touched_boundaries': touched,
    }
    if (not isinstance(receipt, dict)
            or {name: receipt.get(name) for name in expected} != expected
            or set(receipt) != {*expected, 'log_sha256'}
            or not isinstance(receipt.get('log_sha256'), str)
            or not all(value in '0123456789abcdef' for value in receipt['log_sha256'])
            or len(receipt['log_sha256']) != 64):
        raise ValueError('invalid ' + source + ' contract receipt')
    return receipt


def receipt_bytes(path, source):
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(source + ' contract receipt is unavailable') from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError('invalid ' + source + ' contract receipt')
    return path.read_bytes()


def publish(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('contract receipt collision')
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return False


def terminate_groups(groups, grace):
    for group in groups:
        try:
            os.killpg(group['process'].pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(
            group_alive(group['process'].pid) for group in groups):
        time.sleep(0.02)
    for group in groups:
        if group_alive(group['process'].pid):
            try:
                os.killpg(group['process'].pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    for group in groups:
        try:
            group['process'].wait(timeout=1)
        except subprocess.TimeoutExpired:
            group['process'].kill()
            group['process'].wait(timeout=1)


def append_output(group, chunk, policy):
    group['tail'].extend(chunk)
    if len(group['tail']) > policy['diagnostic_bytes']:
        del group['tail'][:-policy['diagnostic_bytes']]
    group['size'] += len(chunk)
    if group['size'] > policy['output_bytes']:
        return False
    group['output'].extend(chunk)
    return True


def drain_group(selector, group, policy):
    while True:
        try:
            chunk = os.read(group['process'].stdout.fileno(), 65536)
        except BlockingIOError:
            return None
        if chunk:
            if not append_output(group, chunk, policy):
                return contract_failure(
                    'contract replay failed: ' + group['name']
                    + ' (output limit exceeded)', group)
            continue
        selector.unregister(group['process'].stdout)
        group['process'].stdout.close()
        group['eof'] = True
        return None


def contract_failure(message, group=None):
    return message, bytes(group['tail']) if group is not None else b''


def run_contracts(runner, plugin, environment, policy):
    groups = []
    selector = selectors.DefaultSelector()
    started = time.monotonic()
    failure = None
    succeeded = False
    try:
        for index, name in enumerate(CONTRACT_TESTS):
            try:
                group = launch_group(
                    [str(runner), name],
                    {'index': index, 'name': name, 'output': bytearray(),
                     'tail': bytearray(), 'size': 0, 'eof': False},
                    policy['term_grace_seconds'], cwd=plugin, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment,
                    start_new_session=True)
            except OSError as error:
                failure = contract_failure(
                    'contract replay failed: ' + name + ' (launch error: '
                    + str(error) + ')')
                break
            if group is None:
                failure = contract_failure('contract replay failed: cancelled')
                break
            groups.append(group)
            process = group['process']
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, group)
        deadline = started + policy['shared_deadline_seconds']
        while failure is None and len(groups) == len(CONTRACT_TESTS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pending = [group['name'] for group in groups
                           if group['process'].poll() is None or not group['eof']]
                failure = contract_failure(
                    'contract replay failed: shared deadline exceeded'
                    + (': ' + ', '.join(pending) if pending else ''))
                break
            for key, _ in sorted(selector.select(min(0.05, remaining)),
                                 key=lambda item: item[0].data['index']):
                group = key.data
                failure = drain_group(selector, group, policy)
                if failure is not None:
                    break
            if failure is not None:
                break
            for group in groups:
                code = group['process'].poll()
                if code is not None and code != 0:
                    failure = contract_failure(
                        'contract replay failed: ' + group['name']
                        + ' (exit ' + str(code) + ')', group)
                    break
            if failure is not None:
                break
            if all(group['eof'] and group['process'].poll() == 0 for group in groups):
                descendant = next((group for group in groups
                                   if group_alive(group['process'].pid)), None)
                if descendant is not None:
                    failure = contract_failure(
                        'contract replay failed: ' + descendant['name']
                        + ' left a descendant process running', descendant)
                    break
                succeeded = True
                return [bytes(group['output']) for group in groups], None
    finally:
        if not succeeded:
            terminate_groups(groups, policy['term_grace_seconds'])
        for group in groups:
            stream = group['process'].stdout
            if stream is not None and not stream.closed:
                try:
                    selector.unregister(stream)
                except KeyError:
                    pass
                stream.close()
            unregister_group(group)
        selector.close()
    return None, failure


def print_contract_failure(failure):
    message, tail = failure
    print(message, file=sys.stderr)
    if tail:
        sys.stderr.flush()
        sys.stderr.buffer.write(tail)
        if not tail.endswith(b'\n'):
            sys.stderr.buffer.write(b'\n')
        sys.stderr.buffer.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--roster', required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root_alias = Path(args.root).expanduser().absolute()
    root = root_alias.resolve()
    session = Path(args.session).resolve()
    subject_plugin, prefix = source_plugin(root)
    if subject_plugin is None:
        print('contract replay: unrelated repository')
        return 0
    changed = changed_paths(root, args.base)
    touched = sorted(path for path in changed if is_boundary(path, prefix))
    if not touched:
        print('contract replay: no provider boundary changes')
        return 0
    subject_alias, _ = source_plugin(root_alias)
    plugin, runner, executor = contract_executor(subject_plugin, subject_alias or subject_plugin)
    identity = contract_identity(
        plugin, executor, args.roster, touched,
        subject_boundary_hashes(subject_plugin, prefix, touched))
    key = digest(encoded(identity))
    cache_root = Path(os.environ.get(
        'REVIEW_COUNCIL_CACHE_DIR', '~/.cache/review-council')).expanduser().resolve()
    cache_path = cache_root / 'contracts' / (key + '.json')
    session_path = session / ('contract-pass-' + key + '.json')
    if args.verify_only:
        if not session_path.exists():
            raise ValueError('matching provider contract receipt is missing')
        raw = receipt_bytes(session_path, 'session')
        validate_receipt(raw, identity, key, touched, 'session')
        print(session_path)
        return 0
    if cache_path.is_file():
        raw = receipt_bytes(cache_path, 'cached')
        validate_receipt(raw, identity, key, touched, 'cached')
        publish(session_path, raw)
        print(session_path)
        return 0
    environment = dict(os.environ)
    environment.update(NO_COLOR='1', TERM='dumb')
    outputs, failure = run_contracts(runner, plugin, environment, executor['execution'])
    if failure is not None:
        print_contract_failure(failure)
        return 2
    log_hash = digest(b''.join(outputs))
    receipt = {'schema_version': 2, 'key': key, 'identity': identity,
               'touched_boundaries': touched, 'log_sha256': log_hash}
    raw = encoded(receipt)
    publish(cache_path, raw)
    publish(session_path, raw)
    print(session_path)
    return 0


if __name__ == '__main__':
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, cancellation_signal)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        cancel_active_groups()
        sys.exit(130)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print('contract replay: ' + str(error), file=sys.stderr)
        sys.exit(2)
