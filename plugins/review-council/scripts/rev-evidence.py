#!/usr/bin/env python3
"""Build deterministic review scopes and certify completed snapshot coverage."""
import argparse
import ast
from bisect import bisect_right
from collections import Counter
from contextlib import contextmanager, redirect_stdout
from difflib import SequenceMatcher
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import posixpath

LIB_DIR = Path(__file__).resolve().parent / 'lib'
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))
from review_limits import (CLAUDE_MAX_TURNS, MANDATORY_REPOSITORY_READ_LIMIT,
                           PROVIDER_TURN_RESERVE, READ_LINES,
                           REPOSITORY_EXPANSION_CALL_LIMIT,
                           REPOSITORY_REFUTATION_CALL_RESERVE)
from session_inputs import session_input_lock, validate_standard_inputs

BUNDLES = ('correctness-boundaries', 'security-state-api',
           'concurrency-resources-performance', 'tests-observability-maintenance-regression')
PLAN_BUNDLES = ('plan-completeness', 'plan-soundness', 'plan-simplicity', 'plan-tests')
SOURCE_CONTEXT_LIMIT = 16 * 1024
SOURCE_SEGMENT_VISIBLE_LIMIT = 16 * 1024
SOURCE_SEGMENT_SINGLE_LINE_VISIBLE_LIMIT = 32 * 1024
SOURCE_SEGMENT_LINE_LIMIT = READ_LINES
SOURCE_SEGMENT_PREFIX_RESERVE = 8
PATCH_CHUNK_RAW_LIMIT = 24 * 1024
PATCH_CHUNK_VISIBLE_LIMIT = 30 * 1024
PATCH_CHUNK_LINE_LIMIT = 1000
PATCH_CHUNK_PREFIX_RESERVE = 8
PLAN_MAX_BYTES = 256 * 1024
PLAN_CLOSURE_MAX_BYTES = 8 * 1024 * 1024
PLAN_SEARCH_MAX_BYTES = 32 * 1024
PLAN_SEARCH_MAX_RESULTS = 80
PLAN_SEARCH_OVERFLOW_RESULTS = PLAN_SEARCH_MAX_RESULTS + 1
PLAN_SEARCH_TIMEOUT_DEFAULT = 30
SOURCE_PACKET_BATCH_LIMIT = 1
SOURCE_ANCHOR_RADIUS = 8
DECLARATION_PAIR_LIMIT = 4096
DECLARATION_PAIR_TOKEN_LIMIT = 1_000_000
SOURCE_CONTEXT_REASONS = ('declaration', 'production-caller', 'related-test',
                          'gate', 'extra-caller', 'extra-test')
NAVIGATION_ROW_LIMIT = 1024
NAVIGATION_TOTAL_LIMIT = 16384
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\Z')
DIFF = ['diff', '--no-ext-diff', '--no-textconv', '--no-renames',
        '--no-indent-heuristic', '--diff-algorithm=myers', '--no-color',
        '--unified=3', '--binary', '--src-prefix=a/', '--dst-prefix=b/']
OVERSIZED_BLOB = object()
ACTIVE_PLAN_SEARCHES = set()


def phase_bundles(phase):
    return PLAN_BUNDLES if phase == 'plan' else BUNDLES


def read_batch_limit(adapter):
    return 2 if adapter == 'claude' else 1


def plan_search_timeout(environment):
    value = environment.get('REV_PLAN_SEARCH_TIMEOUT', str(PLAN_SEARCH_TIMEOUT_DEFAULT))
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
        raise ValueError('REV_PLAN_SEARCH_TIMEOUT must be an integer from 1 to 300')
    timeout = int(value)
    if not 1 <= timeout <= 300:
        raise ValueError('REV_PLAN_SEARCH_TIMEOUT must be an integer from 1 to 300')
    return timeout


def evidence_modes(environment, parent=None):
    chunk_explicit = 'REV_PATCH_CHUNKS' in environment
    source_explicit = 'REV_SOURCE_CONTEXT' in environment
    chunk_mode = environment.get('REV_PATCH_CHUNKS', 'auto')
    source_mode = environment.get('REV_SOURCE_CONTEXT', '0')
    if chunk_mode not in ('auto', '0', '1'):
        raise ValueError('REV_PATCH_CHUNKS must be auto, 0, or 1')
    if source_mode not in ('0', '1'):
        raise ValueError('REV_SOURCE_CONTEXT must be 0 or 1')
    if parent is None:
        return chunk_mode, source_mode == '1'
    parent_chunk_mode = parent.get('patch_chunks_mode')
    parent_source_enabled = parent.get('source_context', {}).get('enabled')
    if (parent_chunk_mode not in ('auto', '0', '1')
            or type(parent_source_enabled) is not bool):
        raise ValueError('parent evidence modes are invalid')
    if chunk_explicit and chunk_mode != parent_chunk_mode:
        raise ValueError('repair patch chunk setting conflicts with parent assignment')
    if source_explicit and (source_mode == '1') is not parent_source_enabled:
        raise ValueError('repair source context setting conflicts with parent assignment')
    return parent_chunk_mode, parent_source_enabled


def validate_live_roster_adapters(roster):
    if (not isinstance(roster, dict) or not isinstance(roster.get('seats'), list)
            or any(not isinstance(row, dict) for row in roster['seats'])):
        raise ValueError('invalid roster shape')
    unsupported = sorted({str(row.get('adapter')) for row in roster['seats']
                          if row.get('adapter') not in ('codex', 'gemini', 'claude', 'agent')})
    if unsupported:
        raise ValueError('unsupported or retired roster adapter: ' + ', '.join(unsupported))


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patch_display_lines(raw):
    return raw.count(b'\n') + (1 if raw and not raw.endswith(b'\n') else 0)


def predicted_source_visible_bytes(raw):
    return len(raw) + patch_display_lines(raw) * SOURCE_SEGMENT_PREFIX_RESERVE


def split_lf_lines(raw):
    parts = raw.split(b'\n')
    return [part + b'\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def split_lf_text(text):
    parts = text.split('\n')
    return parts[:-1] + ([parts[-1]] if parts[-1] else [])


def partition_patch_chunks(raw):
    """Split valid UTF-8 patch bytes into gapless, model-output-safe chunks."""
    if not raw:
        return []
    raw.decode('utf-8')
    if b'\0' in raw:
        raise ValueError('patch chunk input contains NUL')
    chunks = []
    start = 0
    size = len(raw)
    while start < size:
        hard_end = min(size, start + PATCH_CHUNK_RAW_LIMIT)
        while hard_end > start and hard_end < size and raw[hard_end] & 0xC0 == 0x80:
            hard_end -= 1
        if hard_end == start:
            raise ValueError('UTF-8 scalar exceeds patch chunk limit')
        maximum = start
        last_newline = None
        cursor = start
        lines = 0
        in_line = False
        while cursor < hard_end:
            lead = raw[cursor]
            width = (1 if lead < 0x80 else 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4)
            next_cursor = cursor + width
            if next_cursor > hard_end:
                break
            if lead == 0x0A:
                if not in_line:
                    lines += 1
                in_line = False
            elif not in_line:
                lines += 1
                in_line = True
            visible = next_cursor - start + lines * PATCH_CHUNK_PREFIX_RESERVE
            if lines > PATCH_CHUNK_LINE_LIMIT or visible > PATCH_CHUNK_VISIBLE_LIMIT:
                break
            maximum = next_cursor
            if lead == 0x0A:
                last_newline = next_cursor
            cursor = next_cursor
        if maximum == start:
            raise ValueError('patch chunk constraints cannot fit one UTF-8 scalar')
        end = last_newline if last_newline is not None else maximum
        content = raw[start:end]
        display_lines = patch_display_lines(content)
        chunks.append({
            'index': len(chunks) + 1,
            'byte_start': start,
            'byte_end': end,
            'bytes': len(content),
            'display_lines': display_lines,
            'predicted_visible_bytes': len(content) + display_lines * PATCH_CHUNK_PREFIX_RESERVE,
            'starts_mid_line': start > 0 and raw[start - 1:start] != b'\n',
            'ends_mid_line': end < size and raw[end - 1:end] != b'\n',
            'sha256': digest(content),
            'content': content,
        })
        start = end
    return chunks


def patch_chunk_mode(raw, chunks, setting):
    if isinstance(setting, bool):
        setting = 'auto' if setting else '0'
    if setting not in ('auto', '0', '1'):
        raise ValueError('invalid patch chunk setting')
    if setting == '0' or not raw or b'\0' in raw:
        return 'windows'
    try:
        raw.decode('utf-8')
    except UnicodeDecodeError:
        return 'windows'
    if setting == '1':
        return 'chunks' if chunks else 'windows'
    lines = split_lf_lines(raw)
    windows = max(1, (len(lines) + 239) // 240)
    for start in range(0, len(lines), 240):
        window = lines[start:start + 240]
        predicted_visible = sum(map(len, window)) + len(window) * PATCH_CHUNK_PREFIX_RESERVE
        if predicted_visible > PATCH_CHUNK_VISIBLE_LIMIT:
            return 'chunks' if chunks else 'windows'
    return 'chunks' if chunks and len(chunks) * 10 <= windows * 9 else 'windows'


def partition_source_segments(lines, line_start, line_end):
    """Partition one immutable source range into bounded, gapless line segments."""
    segments = []
    cursor = line_start
    while cursor <= line_end:
        segment_start = cursor
        raw = b''
        while cursor <= line_end and cursor - segment_start < SOURCE_SEGMENT_LINE_LIMIT:
            candidate = raw + lines[cursor - 1]
            line_count = cursor - segment_start + 1
            predicted = len(candidate) + line_count * SOURCE_SEGMENT_PREFIX_RESERVE
            if predicted > SOURCE_SEGMENT_VISIBLE_LIMIT:
                if not raw and predicted <= SOURCE_SEGMENT_SINGLE_LINE_VISIBLE_LIMIT:
                    raw = candidate
                    cursor += 1
                break
            raw = candidate
            cursor += 1
        if cursor == segment_start:
            raise ValueError('required source line exceeds visible segment limit')
        segments.append({
            'index': len(segments) + 1,
            'line_start': segment_start,
            'line_end': cursor - 1,
            'raw_bytes': len(raw),
            'predicted_visible_bytes': len(raw) + (cursor - segment_start) * SOURCE_SEGMENT_PREFIX_RESERVE,
            'content_sha256': digest(raw),
        })
    return segments


def patch_sets_for(scopes, patch_bodies, prefix, setting):
    sets = {}
    artifacts = {}
    identities = {}
    for seat, assignment in scopes.items():
        raw = patch_bodies[seat]
        identity = assignment['patch_sha256']
        if identity not in identities:
            try:
                chunks = partition_patch_chunks(raw) if setting != '0' and setting is not False else []
            except (UnicodeDecodeError, ValueError):
                chunks = []
            mode = patch_chunk_mode(raw, chunks, setting)
            set_id = f'p{len(identities) + 1:02d}'
            rows = []
            if mode == 'chunks':
                for chunk in chunks:
                    name = f"{prefix}-patch-{set_id}-{chunk['index']:03d}.txt"
                    content = chunk.pop('content')
                    rows.append({'artifact': name, **chunk})
                    artifacts[name] = content
            sets[set_id] = {
                'patch_sha256': identity,
                'patch_bytes': len(raw),
                'patch_lines': len(split_lf_lines(raw)),
                'read_mode': mode,
                'chunks': rows,
            }
            identities[identity] = set_id
        set_id = identities[identity]
        patch_set = sets[set_id]
        if (patch_set['patch_bytes'] != len(raw) or patch_set['patch_lines'] != len(split_lf_lines(raw))
                or patch_set['patch_sha256'] != digest(raw)):
            raise ValueError('assigned patch hash collision')
        assignment['patch_set'] = set_id
        assignment['patch_read_mode'] = patch_set['read_mode']
    return sets, artifacts


def digest_git_blob(data, oid_length):
    content = ('blob ' + str(len(data))).encode() + b'\0' + data
    return (hashlib.sha256(content) if oid_length == 64 else hashlib.sha1(content)).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def publish(path, data):
    fd, name = tempfile.mkstemp(prefix='.evidence-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def scope(session):
    values = {}
    for line in (session / 'scope.env').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'REV_[A-Z_]+', key) or key in values:
            raise ValueError('invalid scope metadata')
        parts = shlex.split(value)
        if len(parts) != 1:
            raise ValueError('invalid scope value')
        values[key] = parts[0]
    if not all(values.get(k) for k in ('REV_ROOT', 'REV_BASE', 'REV_SCOPE')):
        raise ValueError('scope requires root, base and scope')
    return values


def git_quote(path):
    escaped = []
    for value in os.fsencode(path):
        if value in (34, 92):
            escaped.append('\\' + chr(value))
        elif 32 <= value < 127:
            escaped.append(chr(value))
        else:
            escaped.append('\\%03o' % value)
    return '"' + ''.join(escaped) + '"'


def literal_scope(value, root):
    if value in ('branch', 'uncommitted'):
        return '.'
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            raise ValueError('scope lies outside repository')
    if '..' in path.parts:
        raise ValueError('scope must be a literal repository path')
    return path.as_posix().rstrip('/') or '.'


def within(path, selected):
    return bool(path and not Path(path).is_absolute() and '..' not in Path(path).parts
                and (selected == '.' or path == selected or path.startswith(selected + '/')))


STANDARD_INPUTS = ('scope.env', 'roster.json', 'files.txt', 'untracked.txt')


def input_hashes(session, contract_name=None):
    result = {}
    names = list(STANDARD_INPUTS)
    if contract_name is not None:
        names.append(contract_name)
    for name in names:
        path = session / name
        if path.exists() and not path.is_file():
            raise ValueError('input must be a regular file: ' + name)
        result[name] = digest(path.read_bytes()) if path.exists() else None
    return result


def provider_contract_input(session):
    values = scope(session)
    script = Path(__file__).with_name('rev-contract-check.py')
    result = subprocess.run([
        sys.executable, str(script), '--root', values['REV_ROOT'], '--session', str(session),
        '--base', values['REV_BASE'], '--roster', str(session / 'roster.json'), '--verify-only',
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        reason = result.stderr.strip()
        if reason.startswith('contract replay: '):
            reason = reason[len('contract replay: '):]
        raise ValueError(reason or 'provider contract verification failed')
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines or lines[-1] in (
            'contract replay: unrelated repository',
            'contract replay: no provider boundary changes'):
        return None
    path = Path(lines[-1]).resolve()
    try:
        path.relative_to(session)
    except ValueError as error:
        raise ValueError('provider contract receipt is outside the session') from error
    match = re.fullmatch(r'contract-pass-([0-9a-f]{64})\.json', path.name)
    metadata = path.lstat()
    if (not match or path.parent != session or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
        raise ValueError('invalid provider contract receipt path')
    raw = path.read_bytes()
    receipt = read_json(path)
    if (not isinstance(receipt, dict) or receipt.get('schema_version') != 2
            or receipt.get('key') != match.group(1)):
        raise ValueError('invalid provider contract receipt identity')
    return path.name, digest(raw)


def contract_binding_from_inputs(session, inputs):
    extra = set(inputs) - set(STANDARD_INPUTS)
    if not extra:
        return None
    if len(extra) != 1:
        raise ValueError('invalid provider contract input binding')
    name = next(iter(extra))
    match = re.fullmatch(r'contract-pass-([0-9a-f]{64})\.json', name)
    value = inputs.get(name)
    path = session / name
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError('invalid provider contract input binding') from error
    if (not match or not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
            or path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
            or digest(path.read_bytes()) != value):
        raise ValueError('invalid provider contract input binding')
    receipt = read_json(path)
    if (not isinstance(receipt, dict) or receipt.get('schema_version') != 2
            or receipt.get('key') != match.group(1)):
        raise ValueError('invalid provider contract input binding')
    return name, value


def diff_quote(path):
    raw = os.fsencode(path)
    escapes = {7: '\\a', 8: '\\b', 9: '\\t', 10: '\\n', 11: '\\v', 12: '\\f', 13: '\\r', 34: '\\"', 92: '\\\\'}
    if all(32 <= n < 127 and n not in (34, 92) for n in raw):
        return raw
    return ('"' + ''.join(escapes.get(n, chr(n) if 32 <= n < 127 else '\\%03o' % n) for n in raw) + '"').encode()


def split_patch(patch, paths):
    headers = {b'diff --git ' + diff_quote('a/' + p) + b' ' + diff_quote('b/' + p): p for p in paths}
    result = {}
    for block in re.split(rb'(?m)(?=^diff --git )', patch):
        if not block:
            continue
        header = block.split(b'\n', 1)[0]
        if header not in headers:
            raise ValueError('patch contains an unknown or out-of-scope path')
        name = headers[header]
        result[name] = result.get(name, b'') + block
    if set(result) != set(paths):
        raise ValueError('patch path inventory is incomplete')
    return result


class Repository:
    def __init__(self, session):
        self.session = session
        self.scope = scope(session)
        self.root = Path(self.scope['REV_ROOT']).resolve()
        self.selected = literal_scope(self.scope['REV_SCOPE'], self.root)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_OPTIONAL_LOCKS='0', GIT_LITERAL_PATHSPECS='1', LC_ALL='C')
        objects = self.git('rev-parse', '--git-path', 'objects').decode().strip()
        objects = (self.root / objects).resolve()
        self.objects = session / 'evidence-objects'
        if self.objects.is_symlink():
            raise ValueError('object storage must not be a symlink')
        self.objects.mkdir(mode=0o700, exist_ok=True)
        if self.objects.resolve().parent != session or self.objects.resolve() == objects or objects in self.objects.resolve().parents:
            raise ValueError('object storage must belong to the session')
        for directory, dirs, files in os.walk(self.objects, followlinks=False):
            for name in dirs + files:
                path = Path(directory) / name
                if path.is_symlink() or (path.is_file() and path.stat().st_nlink != 1):
                    raise ValueError('redirected object storage entry: ' + name)
                if not (path.is_file() or path.is_dir()):
                    raise ValueError('unsupported object storage entry: ' + name)
        self.env.update(GIT_OBJECT_DIRECTORY=str(self.objects),
                        GIT_ALTERNATE_OBJECT_DIRECTORIES=git_quote(str(objects)))
        self.blob_cache = {}

    def scoped(self, path):
        return within(path, self.selected)

    def git(self, *args, data=None, env=None):
        result = subprocess.run(['git', '-C', str(self.root), *args], input=data,
                                env=env or self.env, capture_output=True)
        if result.returncode:
            raise ValueError('git ' + args[0] + ': ' + result.stderr.decode(errors='replace').strip())
        return result.stdout

    def tree(self, ref):
        return self.git('rev-parse', '--verify', '--end-of-options', ref + '^{tree}').decode().strip()

    def entries(self, tree):
        entries = {}
        for row in self.git('ls-tree', '-rz', tree).split(b'\0'):
            if row:
                meta, path = row.split(b'\t', 1)
                mode, kind, oid = meta.decode().split()
                entries[os.fsdecode(path)] = (mode, oid)
        return entries

    def snapshot(self, ref=None):
        head = self.tree('HEAD')
        anchor = self.tree(self.scope['REV_BASE']) if self.selected != '.' else head
        entries = self.entries(anchor)
        if ref:
            target = self.tree(ref)
            if self.selected == '.':
                return target, []
            current = self.entries(target)
            overlay = {p: e for p, e in current.items() if self.scoped(p)}
            paths = {p for p in entries.keys() | current.keys() if self.scoped(p)}
        else:
            current = {}
            for row in self.git('ls-files', '--stage', '-z').split(b'\0'):
                if not row:
                    continue
                metadata, name = row.split(b'\t', 1); mode, oid, stage = metadata.decode().split()
                if stage != '0':
                    raise ValueError('unmerged index cannot be represented safely')
                current[os.fsdecode(name)] = (mode, oid)
            sparse = {os.fsdecode(row[2:]) for row in self.git('ls-files', '-t', '-z').split(b'\0') if row.startswith(b'S ')}
            paths = set(entries) | set(current) | set(self.entries(head))
            paths.update(os.fsdecode(p) for p in self.git('ls-files', '-z', '--others', '--exclude-standard').split(b'\0') if p)
            paths = {p for p in paths if self.scoped(p)}
            overlay = {}; regular = []; modes = {}; symlinks = []
            for name in sorted(paths):
                path = self.root / name
                if path == self.session or self.session in path.parents:
                    if name in entries:
                        raise ValueError('session overlaps a tracked snapshot path')
                    continue
                ancestors = list(path.parents); ancestors = ancestors[:ancestors.index(self.root)]
                if any(p.is_symlink() or not p.is_dir() for p in reversed(ancestors)):
                    continue
                entry = current.get(name, entries.get(name))
                if entry and entry[0] == '160000':
                    if name not in current and not os.path.lexists(path):
                        continue
                    overlay[name] = ('160000', self.gitlink(name, entry[1]))
                    continue
                try:
                    mode = path.lstat().st_mode
                except (FileNotFoundError, NotADirectoryError):
                    if name in sparse and entry:
                        overlay[name] = entry
                    continue
                if stat.S_ISREG(mode):
                    regular.append(name); modes[name] = '100755' if mode & 0o111 else '100644'
                elif stat.S_ISLNK(mode):
                    body = os.fsencode(os.readlink(path))
                    oid = digest_git_blob(body, len(head))
                    overlay[name] = ('120000', oid)
                    if entries.get(name) != overlay[name]:
                        symlinks.append((name, body, oid))
                elif stat.S_ISDIR(mode):
                    continue
                else:
                    raise ValueError('unsupported special snapshot path: ' + name)
            hashes = self.hash_paths(regular)
            overlay.update({name: (modes[name], hashes[name]) for name in regular})
            differing = [name for name in regular if entries.get(name) != overlay[name]]
            if self.hash_paths(differing, write=True) != {name: hashes[name] for name in differing}:
                raise ValueError('worktree changed during snapshot')
            for name, body, oid in symlinks:
                if self.git('hash-object', '-w', '--no-filters', '--stdin', data=body).decode().strip() != oid:
                    raise ValueError('symlink changed during snapshot')
        fd, index = tempfile.mkstemp(prefix='.evidence-index-', dir=self.session)
        os.close(fd); os.unlink(index)
        env = dict(self.env, GIT_INDEX_FILE=index)
        try:
            self.git('read-tree', anchor, env=env)
            updates = []
            for name in sorted(paths):
                if entries.get(name) != overlay.get(name):
                    updates.append(b'0 ' + b'0' * len(head) + b'\t' + os.fsencode(name) + b'\0')
            for name in sorted(overlay):
                if entries.get(name) != overlay[name]:
                    mode, oid = overlay[name]
                    updates.append((mode + ' ' + oid + '\t').encode() + os.fsencode(name) + b'\0')
            if updates:
                self.git('update-index', '-z', '--index-info', data=b''.join(updates), env=env)
            return self.git('write-tree', env=env).decode().strip(), []
        finally:
            for path in (index, index + '.lock'):
                if os.path.exists(path):
                    os.unlink(path)

    def gitlink(self, name, fallback):
        root = self.root / name
        if not os.path.lexists(root):
            return fallback
        if not root.is_dir() or root.is_symlink():
            raise ValueError('unsupported gitlink worktree: ' + name)
        if not (root / '.git').exists():
            if any(root.iterdir()):
                raise ValueError('uninitialized gitlink has local contents: ' + name)
            return fallback
        env = {k: v for k, v in self.env.items() if k not in ('GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES')}
        def read(*args, data=None):
            result = subprocess.run(['git', '-C', str(root), *args], env=env, input=data, capture_output=True)
            if result.returncode:
                raise ValueError('cannot inspect gitlink: ' + name)
            return result.stdout
        commit = read('rev-parse', 'HEAD').decode().strip()
        tree = {}
        for row in read('ls-tree', '-rz', 'HEAD').split(b'\0'):
            if row:
                meta, path = row.split(b'\t', 1); mode, _, oid = meta.decode().split()
                tree[os.fsdecode(path)] = (mode, oid)
        indexed = {}
        for row in read('ls-files', '--stage', '-z').split(b'\0'):
            if row:
                meta, path = row.split(b'\t', 1); mode, oid, stage = meta.decode().split()
                if stage != '0':
                    raise ValueError('dirty gitlink: ' + name)
                indexed[os.fsdecode(path)] = (mode, oid)
        if indexed != tree or read('ls-files', '--others', '--exclude-standard', '-z'):
            raise ValueError('dirty gitlink: ' + name)
        regular = []
        for path, (mode, oid) in tree.items():
            item = root / path
            if any(p.is_symlink() for p in item.parents if p != root and root in p.parents):
                raise ValueError('dirty gitlink: ' + name)
            if mode == '120000' and item.is_symlink():
                if digest_git_blob(os.fsencode(os.readlink(item)), len(commit)) != oid:
                    raise ValueError('dirty gitlink: ' + name)
            elif mode in ('100644', '100755') and item.is_file() and not item.is_symlink():
                actual_mode = '100755' if item.stat().st_mode & 0o111 else '100644'
                if mode != actual_mode:
                    raise ValueError('dirty gitlink: ' + name)
                regular.append(path)
            else:
                raise ValueError('unsupported or dirty nested gitlink: ' + name)
        if regular:
            hashes = read('hash-object', '--no-filters', '--stdin-paths', data=('\n'.join(git_quote(str(root / p)) for p in regular) + '\n').encode()).decode().splitlines()
            if len(hashes) != len(regular) or any(tree[p][1] != oid for p, oid in zip(regular, hashes)):
                raise ValueError('dirty gitlink: ' + name)
        return commit

    def hash_paths(self, paths, write=False):
        if not paths:
            return {}
        args = ['hash-object', '--no-filters', '--stdin-paths']
        if write:
            args.append('-w')
        data = ('\n'.join(git_quote(str(self.root / path)) for path in paths) + '\n').encode()
        hashes = self.git(*args, data=data).decode().splitlines()
        if len(hashes) != len(paths):
            raise ValueError('incomplete worktree hash batch')
        return dict(zip(paths, hashes))

    def blob(self, entry):
        if not entry or entry[0] == '160000':
            return b''
        if entry[1] not in self.blob_cache:
            self.blob_cache[entry[1]] = self.git('cat-file', 'blob', entry[1])
        return self.blob_cache[entry[1]]

    def preload(self, entries):
        for path, body in self.iter_blobs(entries):
            self.blob_cache[entries[path][1]] = body

    def iter_blobs(self, entries):
        process = subprocess.Popen(['git', '-C', str(self.root), 'cat-file', '--batch'],
                                   env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for path, (mode, oid) in sorted(entries.items()):
                if mode == '160000':
                    continue
                process.stdin.write((oid + '\n').encode()); process.stdin.flush()
                fields = process.stdout.readline().split()
                if len(fields) != 3 or fields[0].decode() != oid or fields[1] != b'blob':
                    raise ValueError('invalid batch blob response')
                size = int(fields[2]); remaining = size; chunks = []
                while remaining:
                    chunk = process.stdout.read(min(remaining, 65536))
                    if not chunk:
                        raise ValueError('incomplete batch blob')
                    if size <= 2_000_000:
                        chunks.append(chunk)
                    remaining -= len(chunk)
                if process.stdout.read(1) != b'\n':
                    raise ValueError('invalid batch blob terminator')
                yield path, b''.join(chunks) if size <= 2_000_000 else OVERSIZED_BLOB
            process.stdin.close()
            if process.wait() != 0:
                raise ValueError('batch blob reader failed')
        finally:
            if process.poll() is None:
                process.terminate(); process.wait()
            process.stdout.close(); process.stderr.close()
            if not process.stdin.closed:
                process.stdin.close()

    def materialize_regular(self, tree, destination, paths=None):
        entries = self.entries(tree)
        if paths is not None:
            selected = set(paths)
            if not selected <= set(entries):
                raise ValueError('materialized path is absent from tree')
            entries = {path: entry for path, entry in entries.items() if path in selected}
        process = subprocess.Popen(['git', '-C', str(self.root), 'cat-file', '--batch'],
                                   env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        try:
            for path, (mode, oid) in sorted(entries.items()):
                if mode not in ('100644', '100755'):
                    continue
                parts = Path(path).parts
                if not parts or path.startswith('/') or '..' in parts:
                    raise ValueError('unsafe snapshot path')
                process.stdin.write((oid + '\n').encode())
                process.stdin.flush()
                fields = process.stdout.readline().split()
                if len(fields) != 3 or fields[0].decode() != oid or fields[1] != b'blob':
                    raise ValueError('invalid materialized blob response')
                size = int(fields[2])
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ValueError('snapshot paths collide while materializing')
                with target.open('wb') as stream:
                    remaining = size
                    while remaining:
                        chunk = process.stdout.read(min(remaining, 65536))
                        if not chunk:
                            raise ValueError('incomplete materialized blob')
                        stream.write(chunk)
                        remaining -= len(chunk)
                if process.stdout.read(1) != b'\n':
                    raise ValueError('invalid materialized blob terminator')
            process.stdin.close()
            if process.wait() != 0:
                raise ValueError('snapshot materialization failed')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
            process.stdout.close()
            process.stderr.close()
            if not process.stdin.closed:
                process.stdin.close()

    def changes(self, old, new):
        before, after = self.entries(old), self.entries(new)
        patches = []; hunks = []; categories = {}; unsafe = []
        changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p) and self.scoped(p))
        self.preload({str(i): entry for i, entry in enumerate({e for p in changed for e in (before.get(p), after.get(p)) if e})})
        whole = self.git('-c', 'core.quotePath=true', *DIFF, old, new, '--', self.selected) if changed else b''
        by_path = split_patch(whole, changed)
        for path in changed:
            left, right = before.get(path), after.get(path)
            if left == right:
                continue
            patch = by_path[path]
            body = self.blob(right or left)
            mode = (right or left)[0]
            sides = [classify(path, self.blob(entry), entry[0]) for entry in (left, right) if entry]
            category = sides[0] if len(set(sides)) == 1 else 'semantic'
            categories[path] = category
            kind = 'add' if left is None else 'delete' if right is None else 'modify'
            text = patch.decode('utf-8', errors='replace')
            matches = list(re.finditer(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@[^\n]*\n', text, re.M))
            unsupported = (any(entry and (entry[0] not in ('100644', '100755')
                                         or self.blob(entry) is OVERSIZED_BLOB
                                         or b'\0' in self.blob(entry)) for entry in (left, right))
                           or body is OVERSIZED_BLOB or (left and right and left[0] != right[0])
                           or '\ufffd' in text)
            safe_empty = kind in ('add', 'delete') and body == b'' and not matches and not unsupported
            opaque = unsupported or not matches
            if opaque:
                categories[path] = 'semantic'
                atom = {'kind': kind, 'path': path, 'before': left, 'after': right}
                hunks.append({'path': path, 'kind': 'opaque', 'sha256': digest(encoded(atom))})
                if not safe_empty:
                    unsafe.append(path)
            else:
                for i, match in enumerate(matches):
                    hbody = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
                    atom = {'kind': kind, 'path': path, 'body': hbody}
                    old_position = int(re.search(r'-(\d+)', match.group()).group(1))
                    new_position = int(re.search(r'\+(\d+)', match.group()).group(1))
                    changed_lines = []; base_changed_lines = []
                    replacement_groups = []; group_base = []; group_added = []
                    for line in hbody.split('\n'):
                        if line.startswith(' ') and (group_base or group_added):
                            if group_base:
                                replacement_groups.append({'base_lines': group_base,
                                                           'added_lines': group_added})
                            group_base = []; group_added = []
                        if line.startswith(('+', '-')):
                            changed_lines.append(old_position if kind == 'delete' else new_position)
                        if line.startswith('-'):
                            base_changed_lines.append(old_position)
                            group_base.append(old_position)
                        if line.startswith('+'):
                            group_added.append(new_position)
                        if line.startswith((' ', '-')):
                            old_position += 1
                        if line.startswith((' ', '+')):
                            new_position += 1
                    if group_base:
                        replacement_groups.append({'base_lines': group_base,
                                                   'added_lines': group_added})
                    hunks.append({'path': path, 'kind': kind, 'sha256': digest(encoded(atom)),
                                  'header': match.group().strip(),
                                  'changed_lines': sorted(set(changed_lines)),
                                  'base_changed_lines': sorted(set(base_changed_lines)),
                                  'replacement_groups': replacement_groups})
            patches.append((path, patch))
        return patches, hunks, categories, unsafe


def classify(path, body, mode):
    parts = Path(path).parts; name = parts[-1]; lower = path.lower()
    if mode not in ('100644', '100755') or body is OVERSIZED_BLOB or b'\0' in body:
        return 'semantic'
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        return 'semantic'
    if any(p.lower() in ('fixtures', 'fixture', 'golden', 'goldens', 'vendor', 'vendored', 'patches') for p in parts):
        return 'semantic'
    if name in ('Cargo.lock', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock', 'go.sum', 'Package.resolved', '.terraform.lock.hcl'):
        return 'lockfile'
    if any(p.lower() in ('__snapshots__', 'snapshots') for p in parts[:-1]) or name.endswith('.snap'):
        return 'snapshot'
    locale_roots = {'locale', 'locales', '_locales', 'i18n', 'l10n', 'translations'}
    if any(p.lower() in locale_roots for p in parts[:-1]):
        locale_tag = re.compile(r'[a-z]{2}(?:[-_][A-Za-z0-9]+)*\Z')
        direct_locale = any(i + 1 < len(parts) and locale_tag.fullmatch(parts[i + 1])
                            for i, part in enumerate(parts[:-1]) if part.lower() in locale_roots)
        if Path(path).suffix.lower() in ('.po', '.pot', '.ftl', '.strings', '.stringsdict', '.arb') or (Path(path).suffix.lower() in ('.json', '.yaml', '.yml') and (locale_tag.fullmatch(Path(path).stem) or direct_locale)):
            return 'locale'
    if (any(p.lower() in ('generated', '__generated__') for p in parts[:-1])
            or re.search(r'\.(generated\.[^.]+|min\.(js|css)|map)$', lower)
            or re.search(r'(?im)^.{0,8}(?:@generated|generated (?:file|by)|code generated by|do not edit)\b', '\n'.join(split_lf_text(text)[:8]))):
        return 'generated'
    return 'semantic'


def brace_code(source, extension):
    masked = list(source)
    index = 0
    while index < len(source):
        start = index
        char = source[index]
        if source.startswith('//', index):
            end = source.find('\n', index)
            index = len(source) if end < 0 else end
        elif source.startswith('/*', index):
            depth = 1; index += 2
            while index < len(source) and depth:
                if source.startswith('/*', index):
                    depth += 1; index += 2
                elif source.startswith('*/', index):
                    depth -= 1; index += 2
                else:
                    index += 1
            if depth:
                return None
        elif extension == '.rs' and (raw := re.compile(r'(?:br|r)(#*)"').match(source, index)):
            delimiter = '"' + raw.group(1)
            end = source.find(delimiter, raw.end())
            if end < 0:
                return None
            index = end + len(delimiter)
        elif extension in ('.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx', '.h') and (raw := re.compile(r'R"([^\s()\\]{0,16})\(').match(source, index)):
            delimiter = ')' + raw.group(1) + '"'
            end = source.find(delimiter, raw.end())
            if end < 0:
                return None
            index = end + len(delimiter)
        elif char in ('"', "'", '`'):
            if char == "'" and extension == '.rs':
                lifetime = re.compile(r"'[A-Za-z_][\w]*").match(source, index)
                if lifetime and source[lifetime.end():lifetime.end() + 1] != "'":
                    index = lifetime.end()
                    continue
            index += 1
            while index < len(source) and source[index] != char:
                index += 2 if source[index] == '\\' else 1
            if index >= len(source):
                return None
            index += 1
        elif char == '/' and extension in ('.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx'):
            prefix = ''.join(masked[max(0, index - 24):index]).rstrip()
            regex_start = not prefix or prefix[-1] in '=([{,:;!&|?~%^+*-' or re.search(r'\b(?:return|throw|yield|case)\s*$', prefix)
            if not regex_start:
                index += 1
                continue
            index += 1; in_class = False
            while index < len(source):
                current = source[index]
                if current == '\\':
                    index += 2; continue
                if current == '[':
                    in_class = True
                elif current == ']':
                    in_class = False
                elif current == '/' and not in_class:
                    break
                elif current == '\n':
                    return None
                index += 1
            if index >= len(source):
                return None
            index += 1
        elif char == '#' and extension in ('.c', '.h', '.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx') and not source[source.rfind('\n', 0, index) + 1:index].strip():
            end = source.find('\n', index)
            index = len(source) if end < 0 else end
        else:
            index += 1
            continue
        for position in range(start, index):
            if masked[position] != '\n':
                masked[position] = ' '
    return ''.join(masked)


def brace_spans(lines, extension):
    source = '\n'.join(lines)
    code = brace_code(source, extension)
    if code is None:
        return []
    line_starts = [0] + [match.end() for match in re.finditer('\n', code)]
    identifier = r'(?P<name>[A-Za-z_$][\w$]*)'
    named = [
        re.compile(r'\b(?:const|let|var)\s+' + identifier + r'\b[^;{}]*=\s*(?:async\s+)?(?:[^;{}]*=>\s*|function\s*[^;{}]*)$'),
        re.compile(r'\bfunction\s*\*?\s+' + identifier + r'\s*(?:<[^;{}]*>)?\s*\('),
        re.compile(r'\bfn\s+' + identifier + r'\s*(?:<[^;{}]*>)?\s*\('),
        re.compile(r'\bfunc\s+(?:\([^()]*\)\s*)?' + identifier + r'\s*(?:\[[^\]]*\])?\s*\('),
    ]
    generic = re.compile(identifier + r'\s*\(')
    controls = {'if', 'for', 'while', 'switch', 'catch', 'with', 'synchronized',
                'match', 'sizeof', 'alignof', 'noexcept', 'decltype', 'requires',
                'function', 'func', 'fn'}
    spans = []; stack = []; boundary = 0
    for position, char in enumerate(code):
        if char == '{':
            header = code[boundary:position]
            names = [(m.group('name'), boundary + m.start('name'))
                     for pattern in named for m in pattern.finditer(header)]
            if header.count('(') != header.count(')'):
                names = []
            elif not names:
                container = bool(stack and stack[-1][2])
                for match in generic.finditer(header):
                    name = match.group('name'); prefix = header[:match.start()].strip()
                    if name in controls or prefix.endswith('.') or (not prefix and not container):
                        continue
                    if set(re.findall(r'\b\w+\b', prefix)) & controls:
                        continue
                    if not re.fullmatch(r'[\w\s$:<>,*&.\[\]~@]*', prefix) or re.search(r'\b(?:return|throw|new|await|yield)\b', prefix):
                        continue
                    depth = 1; end = match.end()
                    while end < len(header) and depth:
                        if header[end] == '(':
                            depth += 1
                        elif header[end] == ')':
                            depth -= 1
                        end += 1
                    if depth or not re.fullmatch(r'[\w\s$:<>,*&.\[\]()\-]*', header[end:]):
                        continue
                    names.append((name, boundary + match.start('name')))
            container = not names and bool(re.search(r'\b(?:class|struct|impl|interface)\b|(?:=|:)\s*$', header))
            stack.append((position, names, container))
            boundary = position + 1
        elif char == '}':
            if not stack:
                return []
            _, names, _ = stack.pop()
            for name, start in names:
                spans.append((bisect_right(line_starts, start), bisect_right(line_starts, position), name))
            boundary = position + 1
        elif char == ';':
            boundary = position + 1
    return [] if stack else spans


def facts(repo, tree, hunks, categories, base_tree=None):
    entries = {p: e for p, e in repo.entries(tree).items() if repo.scoped(p)}
    base_entries = ({p: e for p, e in repo.entries(base_tree).items() if repo.scoped(p)}
                    if base_tree else {})
    seed_paths = {h['path'] for h in hunks}
    texts = {}
    for blob_tree, tree_entries in ((tree, entries), (base_tree, base_entries)):
        if not blob_tree:
            continue
        selected = {p: e for p, e in tree_entries.items() if p in seed_paths}
        for path, raw in repo.iter_blobs(selected):
            if selected[path][0] not in ('100644', '100755'):
                continue
            if raw is OVERSIZED_BLOB or b'\0' in raw:
                continue
            try:
                texts[(path, blob_tree)] = split_lf_text(raw.decode('utf-8'))
            except UnicodeDecodeError:
                continue
    symbols = []; seen = set()
    declaration = re.compile(r'^\s*(?:(?:export|pub|public|private|static|async)\s+)*(?:def|fn|function|class|struct|enum|interface|type|const|let|func)\s+([A-Za-z_$][\w$]*)')
    declarations = {}
    current_seeds = {}; base_seeds = {}
    hunks_by_path = {}
    for hunk in hunks:
        hunks_by_path.setdefault(hunk['path'], []).append(hunk)
        current_seeds.setdefault(hunk['path'], []).append(hunk.get('changed_lines') or [0])
        if hunk.get('base_changed_lines'):
            base_seeds.setdefault(hunk['path'], []).append(hunk['base_changed_lines'])

    def selected_symbols(path, blob_tree, hunk_lines):
        lines = texts.get((path, blob_tree), [])
        declaration_key = (path, blob_tree)
        if declaration_key not in declarations:
            rows = [(i, i, m.group(1)) for i, line in enumerate(lines, 1)
                    for m in [declaration.search(line)] if m]
            if Path(path).suffix == '.py':
                try:
                    rows = [(node.lineno, node.end_lineno, node.name)
                            for node in ast.walk(ast.parse('\n'.join(lines)))
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
                except SyntaxError:
                    pass
            elif Path(path).suffix in ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rs', '.go', '.java', '.c', '.h', '.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx'):
                rows.extend(brace_spans(lines, Path(path).suffix))
            declarations[declaration_key] = sorted(rows)
        candidates = declarations[declaration_key]
        selected = set()
        cursor = 0
        active = {}
        outside = set()
        for line in sorted({line for changed in hunk_lines for line in changed}):
            while cursor < len(candidates) and candidates[cursor][0] <= line:
                start, end, name = candidates[cursor]
                active[(start, name)] = end
                cursor += 1
            active = {key: end for key, end in active.items() if end >= line}
            if active:
                (start, name), end = max(active.items(), key=lambda item: (
                    item[0][0], -item[1], item[0][1]))
                selected.add((start, end, name))
            else:
                outside.add(line)
        for changed in hunk_lines:
            anchors = sorted(set(changed) & outside)
            if not anchors:
                continue
            anchor = min(max(1, anchors[len(anchors) // 2]), max(1, len(lines)))
            previous_end = max((end for start, end, _ in candidates if end < anchor), default=0)
            next_start = min((start for start, _, _ in candidates if start > anchor),
                             default=max(1, len(lines)) + 1)
            selected.add((max(previous_end + 1, anchor - SOURCE_ANCHOR_RADIUS),
                          min(next_start - 1, max(1, len(lines)), anchor + SOURCE_ANCHOR_RADIUS), None))
        if not selected:
            selected.add((1, min(max(1, len(lines)), 1 + SOURCE_ANCHOR_RADIUS), None))
        return selected

    for path, hunk_lines in sorted(current_seeds.items()):
        blob_tree = tree if (path, tree) in texts else base_tree
        if (path, blob_tree) not in texts:
            continue
        selected = selected_symbols(path, blob_tree, hunk_lines)
        for origin, end, name in sorted(selected, key=lambda item: (item[0], item[2] or '')):
            key = (path, origin, end, name, blob_tree)
            if key not in seen:
                seen.add(key)
                symbols.append({'path': path, 'line': origin, 'line_end': end,
                                'name': name,
                                'kind': ('lexical declaration' if name else 'changed-line anchor')
                                if blob_tree == tree else
                                ('deleted lexical declaration' if name else
                                 'deleted changed-line anchor'),
                                'blob_tree': blob_tree})
    for path, hunk_lines in sorted(base_seeds.items()):
        if (path, base_tree) not in texts:
            continue
        removed_lines = {line for changed in hunk_lines for line in changed}
        selected = selected_symbols(path, base_tree, hunk_lines)
        base_candidates = sorted(set(declarations[(path, base_tree)]))
        current_candidates = sorted(set(declarations.get((path, tree), [])))
        replaced = set()
        base_lines = texts[(path, base_tree)]
        current_lines = texts.get((path, tree), [])
        token_cache = {}

        def declaration_tokens(lines, row):
            cache_key = (id(lines), row)
            if cache_key in token_cache:
                return token_cache[cache_key]
            start, end, _ = row
            container = ''
            for line in reversed(lines[max(0, start - 41):start - 1]):
                if re.search(r'\b(?:class|struct|impl|interface|enum|namespace|module)\b', line):
                    container = line
                    break
            source = '\n'.join([container, *lines[start - 1:end]])
            token_cache[cache_key] = re.findall(
                r'[A-Za-z_$][\w$]*|\d+|[^\s\w]', source)
            return token_cache[cache_key]

        for hunk in hunks_by_path[path]:
            for group in hunk.get('replacement_groups', []):
                old_rows = [row for row in base_candidates if row[0] in group['base_lines']]
                new_rows = [row for row in current_candidates if row[0] in group['added_lines']]
                names = sorted({row[2] for row in old_rows} & {row[2] for row in new_rows})
                for name in names:
                    old = {row for row in old_rows if row[2] == name}
                    new = {row for row in new_rows if row[2] == name}
                    if len(old) == len(new) == 1:
                        replaced.update(old)
                        continue
                    if len(old) * len(new) > DECLARATION_PAIR_LIMIT:
                        continue
                    old_tokens = {row: declaration_tokens(base_lines, row) for row in old}
                    new_tokens = {row: declaration_tokens(current_lines, row) for row in new}
                    token_work = (sum(map(len, old_tokens.values())) * len(new)
                                  + sum(map(len, new_tokens.values())) * len(old))
                    if token_work > DECLARATION_PAIR_TOKEN_LIMIT:
                        continue
                    scores = {(old_row, new_row): SequenceMatcher(
                        None, old_tokens[old_row], new_tokens[new_row]).ratio()
                              for old_row in old for new_row in new}
                    while old and new:
                        old_best = {row: max(scores[(row, candidate)] for candidate in new)
                                    for row in old}
                        new_best = {row: max(scores[(candidate, row)] for candidate in old)
                                    for row in new}
                        choices = [
                            (old_row, new_row) for old_row in old for new_row in new
                            if scores[(old_row, new_row)] == old_best[old_row]
                            and sum(scores[(old_row, candidate)] == old_best[old_row]
                                    for candidate in new) == 1
                            and scores[(old_row, new_row)] == new_best[new_row]
                            and sum(scores[(candidate, new_row)] == new_best[new_row]
                                    for candidate in old) == 1]
                        if not choices:
                            break
                        for old_row, new_row in choices:
                            replaced.add(old_row); old.remove(old_row); new.remove(new_row)
        for origin, end, name in sorted(selected, key=lambda item: (item[0], item[2] or '')):
            if name is None and path in entries:
                continue
            if name is not None:
                if origin not in removed_lines:
                    continue
                if (origin, end, name) in replaced:
                    continue
            key = (path, origin, end, name, base_tree)
            if key not in seen:
                seen.add(key); symbols.append({'path': path, 'line': origin, 'line_end': end,
                                               'name': name, 'kind': 'deleted lexical declaration'
                                               if name else 'deleted changed-line anchor',
                                               'blob_tree': base_tree})
    calls = []; tests = []; gates = []; dependencies = set()
    names = {s['name'] for s in symbols if s['name']}
    definitions = {}
    for symbol in symbols:
        if symbol['name']:
            definitions.setdefault(symbol['name'], set()).add(symbol['path'])
    changed_stems = {Path(p).stem for p in categories}
    tokens = re.compile(r'\b[A-Za-z_$][\w$]*\b')
    call_tokens = re.compile(r'\b([A-Za-z_$][\w$]*)\s*\(')
    for path, raw in repo.iter_blobs(entries):
        if entries[path][0] not in ('100644', '100755') or raw is OVERSIZED_BLOB or b'\0' in raw:
            continue
        try:
            lines = split_lf_text(raw.decode('utf-8'))
        except UnicodeDecodeError:
            continue
        is_test = is_test_path(path)
        related = Path(path).stem.replace('test_', '').replace('_test', '') in changed_stems
        for i, line in enumerate(lines, 1):
            matches = set(tokens.findall(line)) & names
            for name in matches:
                dependencies.update((path, target, 'lexical-reference') for target in definitions[name] if target != path)
            for name in sorted(set(call_tokens.findall(line)) & names):
                calls.append({'path': path, 'line': i, 'name': name, 'kind': 'lexical name( match, not resolved dispatch'})
            if is_test and not related:
                related = bool(matches)
            imports = re.findall(r'(?:from\s+|require\s*\(\s*|import\s*(?:\(\s*)?)["\']([^"\']+)["\']', line)
            imports += re.findall(r'\b(?:from|import)\s+([\w.]+)', line) if Path(path).suffix == '.py' else []
            for imported in imports:
                target = resolve_import(path, imported, entries)
                if target and target != path:
                    dependencies.add((path, target, 'local-import'))
        if is_test and related:
            tests.append({'path': path, 'basis': 'test path with lexical reference or same stem'})
            stem = Path(path).stem.replace('test_', '').replace('_test', '')
            dependencies.update((path, changed, 'related-test') for changed in categories if Path(changed).stem == stem and changed != path)
        basename = Path(path).name
        config = bool(re.search(r'(?:^|[.])(eslint|prettier|vitest|jest|nyc|coverage|ruff|mypy|pytest|tsconfig)', basename))
        if basename in ('package.json', 'Cargo.toml', 'pyproject.toml', 'Makefile', 'makefile', 'justfile', 'Justfile', 'go.mod') or path.startswith('.github/workflows/') or config:
            gates.append({'path': path, 'kind': 'gate candidate'})
            for i, line in enumerate(lines, 1):
                if re.search(r'\b(test|lint|check|typecheck|coverage|run)\b|^[\w-]+:', line):
                    gates.append({'path': path, 'line': i, 'command': line.strip(), 'kind': 'lexical gate candidate'})
    return {'symbols': symbols, 'call_sites': calls, 'related_tests': tests, 'gates': gates,
            'dependencies': [{'source': a, 'target': b, 'kind': kind} for a, b, kind in sorted(dependencies)],
            'limitations': ['Lexical navigation only; open source to prove findings.',
                            'Dynamic dispatch and unsupported declarations require file-scope search.',
                            'Binary and files over 2000000 bytes have no lexical index.']}


def is_test_path(path):
    return bool(re.search(r'(^|/)(__tests__|tests?|specs?)(/|_)|(?:test|spec)[._]|[._](?:test|spec)\.', path, re.I))


def resolve_import(path, reference, entries):
    if reference.startswith('.'):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(path), reference))
    else:
        base = reference.replace('.', '/') if Path(path).suffix == '.py' else reference
    candidates = [base]
    for suffix in ('.ts', '.tsx', '.js', '.jsx', '.py', '.rs', '.go', '.java', '.c', '.h', '.cpp'):
        candidates.extend((base + suffix, base + '/index' + suffix))
    candidates.append(base + '/__init__.py')
    matches = [candidate for candidate in candidates if candidate in entries]
    return matches[0] if len(matches) == 1 else None


def strict_search_words(words):
    """Parse one supported rg/grep expression without guessing option arity."""
    tool = words[0] if words else ''
    if tool not in ('rg', 'grep'):
        raise ValueError('search must use rg or grep')
    value_options = {'--glob'} if tool == 'rg' else {'--exclude-dir'}
    boolean_options = {'--line-number', '--null', '--with-filename'}
    boolean_short = set('Hn')
    option_values = {option: [] for option in value_options}
    flags = set()
    recursive = tool == 'rg'
    line_number = False
    null_output = False
    if tool == 'rg':
        boolean_options.update(('--hidden', '--no-ignore'))
    else:
        boolean_options.add('--recursive')
        boolean_short.add('r')
    short_value_options = tuple(option for option in value_options
                                if option.startswith('-') and not option.startswith('--'))
    expressions = []
    operands = []
    index = 1
    while index < len(words):
        word = words[index]
        if word == '--':
            operands.extend(words[index + 1:])
            break
        if word in ('-e', '--regexp'):
            index += 1
            if index >= len(words):
                raise ValueError('search lacks a pattern')
            expressions.append(words[index])
            index += 1
            continue
        if word.startswith('--regexp='):
            expressions.append(word.split('=', 1)[1])
            index += 1
            continue
        if word in value_options:
            if index + 1 >= len(words):
                raise ValueError('search has an incomplete option')
            option_values[word].append(words[index + 1])
            index += 2
            continue
        matched_value = next((option for option in value_options
                              if word.startswith(option + '=')), None)
        if matched_value is not None:
            option_values[matched_value].append(word.split('=', 1)[1])
            index += 1
            continue
        if any(word.startswith(option) and word != option for option in short_value_options):
            index += 1
            continue
        if word in boolean_options:
            flags.add(word)
            recursive = recursive or word == '--recursive'
            line_number = line_number or word == '--line-number'
            null_output = null_output or word == '--null'
            index += 1
            continue
        if (word.startswith('-') and not word.startswith('--') and word != '-'
                and set(word[1:]) <= boolean_short):
            recursive = recursive or 'r' in word[1:]
            line_number = line_number or 'n' in word[1:]
            index += 1
            continue
        if word.startswith('-'):
            raise ValueError('search contains an unsupported option: ' + word)
        operands.append(word)
        index += 1
    if len(expressions) > 1:
        raise ValueError('search contains multiple expressions')
    if expressions:
        pattern = expressions[0]
        paths = operands
    else:
        if not operands:
            raise ValueError('search lacks a pattern')
        pattern = operands[0]
        paths = operands[1:]
    if not pattern or len(pattern.encode()) > 1024 or '\0' in pattern:
        raise ValueError('search has an invalid pattern')
    if not recursive:
        raise ValueError('grep search must be recursive')
    if not line_number:
        raise ValueError('search must include line numbers')
    if not null_output:
        raise ValueError('search must use NUL-delimited filenames')
    if paths != ['.']:
        raise ValueError('search must cover the exact repository root')
    engine = 'rg' if tool == 'rg' else 'grep-bre'
    if tool == 'rg':
        if not {'--hidden', '--no-ignore'} <= flags or option_values['--glob'] != ['!.git/**']:
            raise ValueError('rg search must cover hidden and ignored worktree files except .git')
        domain = 'rg-complete-worktree'
    else:
        if option_values['--exclude-dir'] != ['.git']:
            raise ValueError('grep search must exclude only .git')
        domain = 'grep-complete-worktree'
    return {'engine': engine, 'domain': domain, 'pattern': pattern}, paths


def plan_search_argv(contract):
    pattern = contract['pattern']
    if contract['engine'] == 'rg':
        return ['rg', '--hidden', '--no-ignore', '--glob', '!.git/**', '--null', '-n',
                '--', pattern, '.']
    return ['grep', '--exclude-dir=.git', '--null', '-r', '-n', '--', pattern, '.']


def ripgrep_executable(environment):
    """The binary plan searches execute as `rg`: REV_RG, then PATH, then Claude Code's embedded ripgrep."""
    if environment.get('REV_RG'):
        return environment['REV_RG']
    found = shutil.which('rg', path=environment.get('PATH'))
    if found:
        return found
    # In Claude Code `rg` is a shell function that runs the claude binary under argv0 `rg`.
    embedded = environment.get('CLAUDE_CODE_EXECPATH')
    if embedded:
        try:
            version = subprocess.run(['rg', '--version'], executable=embedded, env=environment,
                                     stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            version = None
        if version is not None and any(line.startswith(b'ripgrep')
                                       for line in version.stdout.splitlines()):
            return embedded
    raise ValueError('ripgrep binary not found on PATH; set REV_RG to a ripgrep executable')


def plan_search_paths(raw):
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('plan search output is not UTF-8') from error
    lines = split_lf_text(text)
    if len(lines) >= PLAN_SEARCH_OVERFLOW_RESULTS:
        raise ValueError('plan search output is saturated')
    paths = set()
    for line in lines:
        match = re.match(r'^(?:\./)?(.+?)\0[1-9][0-9]*:', line)
        if not match:
            raise ValueError('plan search output is malformed')
        path = posixpath.normpath(match.group(1))
        if path in ('', '.', '..') or path.startswith('../') or path.startswith('/'):
            raise ValueError('plan search output escapes the repository')
        paths.add(path)
    return sorted(paths)


def process_group_exists(group):
    try:
        os.killpg(group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def terminate_plan_search(process):
    group = process.pid
    for chosen_signal in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, chosen_signal)
        except ProcessLookupError:
            pass
        except PermissionError:
            continue
        deadline = time.monotonic() + 0.25
        while process_group_exists(group) and time.monotonic() < deadline:
            time.sleep(0.01)
        if not process_group_exists(group):
            break
    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait()


@contextmanager
def plan_search_signal_handlers():
    previous = {}

    def cancel(signum, _frame):
        for process in tuple(ACTIVE_PLAN_SEARCHES):
            terminate_plan_search(process)
        raise SystemExit(128 + signum)

    for signum in (signal.SIGHUP, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, cancel)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_plan_search(command, directory, environment, deadline, executable=None):
    process = None
    selector = selectors.DefaultSelector()
    completed = False
    try:
        change_mask = getattr(signal, 'pthread_sigmask', None)
        previous_mask = (change_mask(signal.SIG_BLOCK, {signal.SIGHUP, signal.SIGTERM})
                         if change_mask is not None else None)
        try:
            process = subprocess.Popen(
                command, executable=executable, cwd=directory, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            ACTIVE_PLAN_SEARCHES.add(process)
        finally:
            if previous_mask is not None:
                change_mask(signal.SIG_SETMASK, previous_mask)
        for stream, kind in ((process.stdout, 'stdout'), (process.stderr, 'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, kind)
        output = bytearray()
        errors = bytearray()
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('plan search timed out')
            ready = selector.select(remaining)
            if not ready:
                raise ValueError('plan search timed out')
            for key, _ in ready:
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = output if key.data == 'stdout' else errors
                target.extend(chunk)
                if len(target) > PLAN_SEARCH_MAX_BYTES:
                    if key.data == 'stdout':
                        raise ValueError('plan search output exceeds the byte limit')
                    raise ValueError('plan search command failed')
                if key.data == 'stdout' \
                        and patch_display_lines(output) >= PLAN_SEARCH_OVERFLOW_RESULTS:
                    raise ValueError('plan search output is saturated')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('plan search timed out')
        try:
            status = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise ValueError('plan search timed out') from error
        if status not in (0, 1) or errors:
            raise ValueError('plan search command failed')
        completed = True
        return bytes(output), status
    finally:
        selector.close()
        if process is not None:
            if not completed:
                terminate_plan_search(process)
            ACTIVE_PLAN_SEARCHES.discard(process)
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass


def plan_excluded_paths(fields_text):
    """Paths named in an Excluded field: ';'-separated `<path> - <reason>` entries.

    Semicolons separate entries so a reason may contain commas, which the Sites field
    already uses to separate locations. A reason is mandatory: a bare path would let an
    author skip a site without ever saying why, which is the whole point of the field.
    """
    found = set()
    for entry in fields_text.split(';'):
        entry = entry.strip()
        if not entry:
            continue
        # The path is the first whitespace-delimited word and the separator is the ' - '
        # immediately after it. Anything else is refused by name rather than silently
        # attributed to a prefix of what the author wrote.
        words = entry.split(None, 1)
        token = words[0].strip('`')
        if not token:
            raise ValueError(f'no path in excluded entry "{entry}"')
        separator = re.fullmatch(r'-(?:\s+(.*))?', words[1], re.S) if len(words) > 1 else None
        if len(words) > 1 and separator is None:
            raise ValueError(f'excluded entry is not <path> - <reason>: "{entry}"')
        reason = (separator.group(1) or '') if separator else ''
        if not reason.strip():
            raise ValueError(f'no reason for excluded path "{token}"')
        # A prefix strip, never lstrip('./'): that is a character class and would turn
        # .github/workflows/ci.yml into a path nobody can find.
        found.add(re.sub(r'^\./', '', token))
    return found


def reconcile_plan_sites(declared, excluded, paths):
    """Return search hits the plan names nowhere. Raise on a phantom exclusion.

    `declared` is every path the cluster names in any field, not only Sites: a cluster's
    own test file usually matches its search pattern, and it is already declared under
    Test/Tests/Regression, so making the author exclude it by name would train exclusions
    to be written mechanically.

    Every set here is already repository-relative - hits through plan_search_paths,
    declared through plan_field_paths, exclusions through plan_excluded_paths - so nothing
    is normalized again. A dot-path stays whole and compares as itself.
    """
    hits = set(paths)
    phantom = sorted(path for path in excluded if path not in hits)
    if phantom:
        raise ValueError('plan cluster excludes a path the search did not find: ' + phantom[0])
    named = set(declared) | set(excluded)
    return sorted(hit for hit in hits if hit not in named)


def prepare_plan_searches(repo, snapshot, clusters, prefix, base_tree=None):
    prepared = []
    artifacts = {}
    search_env = {key: value for key, value in repo.env.items()
                  if key not in ('GREP_OPTIONS', 'GREP_COLORS', 'RIPGREP_CONFIG_PATH')}
    search_env.update(NO_COLOR='1', TERM='dumb')
    ripgrep = (ripgrep_executable(search_env)
               if any(cluster['search_contract']['engine'] == 'rg' for cluster in clusters) else None)
    timeout = plan_search_timeout(os.environ)
    with tempfile.TemporaryDirectory(prefix='.evidence-search-', dir=repo.session) as directory:
        root = Path(directory)
        snapshot_root = root / 'snapshot'
        snapshot_root.mkdir()
        repo.materialize_regular(snapshot, snapshot_root)
        search_roots = [snapshot_root]
        if base_tree is not None:
            snapshot_entries = repo.entries(snapshot)
            base_only = sorted(
                path for path, entry in repo.entries(base_tree).items()
                if path not in snapshot_entries and entry[0] in ('100644', '100755'))
            if base_only:
                base_root = root / 'base-only'
                base_root.mkdir()
                repo.materialize_regular(base_tree, base_root, base_only)
                search_roots.append(base_root)
        deadline = time.monotonic() + timeout
        for cluster in clusters:
            contract = cluster['search_contract']
            results = [run_plan_search(
                plan_search_argv(contract), search_root, search_env, deadline,
                ripgrep if contract['engine'] == 'rg' else None)
                       for search_root in search_roots]
            body = b''.join(sorted(
                line for raw, _ in results for line in split_lf_lines(raw)))
            if len(body) > PLAN_SEARCH_MAX_BYTES:
                raise ValueError('plan search output exceeds the byte limit')
            status = 0 if any(result_status == 0 for _, result_status in results) else 1
            paths = plan_search_paths(body) if body else []
            sites = {row['path'] for row in cluster['paths'] if row['field'] == 'sites'}
            if not sites <= set(paths):
                raise ValueError('plan search output omits a named site')
            declared = {row['path'] for row in cluster['paths']}
            unreconciled = reconcile_plan_sites(declared, cluster.get('excluded', set()), paths)
            if unreconciled:
                raise ValueError('plan search found a site the cluster neither fixes nor excludes: '
                                 + unreconciled[0])
            name = f'{prefix}-plan-search-{cluster["id"]}.txt'
            proof = {'artifact': name, 'status': status, 'saturated': False,
                     'bytes': len(body), 'sha256': digest(body), 'paths': paths}
            prepared.append(dict(cluster, search_proof=proof))
            artifacts[name] = body
    return prepared, artifacts


def plan_search_contract(text):
    match = re.search(r'\(\s*found\s+by:\s*(.+)\)\s*$', text, re.I)
    if not match:
        raise ValueError('plan cluster Sites field lacks a found by search')
    command = match.group(1).strip()
    if command.startswith('`'):
        if len(command) < 2 or not command.endswith('`'):
            raise ValueError('plan cluster has a malformed found by search')
        command = command[1:-1]
    try:
        contract, paths = strict_search_words(shlex.split(command))
    except (ValueError, UnicodeError) as error:
        raise ValueError('plan cluster has a malformed found by search') from error
    if paths != ['.']:
        raise ValueError('plan cluster found by search must cover the exact repository root')
    pattern = contract['pattern']
    if not pattern or len(pattern.encode()) > 1024 or '\0' in pattern:
        raise ValueError('plan cluster found by search has an invalid pattern')
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError('plan cluster found by search pattern is invalid') from error
    return contract


def plan_search_pattern(text):
    return plan_search_contract(text)['pattern']


def validate_plan_range(line_start, line_end, line_count=None, location=None):
    if line_start is None and line_end is None:
        return
    if (type(line_start) is not int or type(line_end) is not int
            or line_start < 1 or line_end < line_start):
        raise ValueError(f'invalid line range "{location}"')
    if line_count is not None and line_end > line_count:
        raise ValueError(f'line range is outside pinned source "{location}"')


def plan_path_boundary(text, start, end):
    before = text[start - 1] if start else ''
    if before and not (before.isspace() or before in '([{,;'):
        return False
    if end == len(text):
        return True
    after = text[end]
    if after.isspace() or after in ',;)]}':
        return True
    return after == '.' and (end + 1 == len(text) or text[end + 1].isspace())


def plan_location_suffix(text, end):
    match = re.match(r':(\d+)(?:-(\d+))?', text[end:])
    if not match:
        return None, None, end
    line_start = int(match.group(1))
    line_end = int(match.group(2)) if match.group(2) else line_start
    return line_start, line_end, end + match.end()


def plan_path_resolution(token, entries):
    if token in entries:
        return token, 'direct'
    if '/' in token:
        raise ValueError(f'path does not exist in pinned snapshot "{token}"')
    candidates = sorted(path for path in entries if Path(path).name == token)
    if len(candidates) != 1:
        reason = 'ambiguous' if candidates else 'missing'
        raise ValueError(f'{reason} basename in pinned snapshot "{token}"')
    return candidates[0], 'basename'


def plan_field_paths(text, entries):
    """Resolve every path-like token in a plan field against the pinned tree."""
    escape = re.search(r'(?<!\S)\S*?(?<![\w@.-])(?:/|\.\.?/)\S*', text)
    if escape:
        raise ValueError(f'path escape "{escape.group(0)}"')
    entries = set(entries)
    candidates = []
    protected = []

    for quoted in re.finditer(r'`([^`\n]+)`(?::(\d+)(?:-(\d+))?)?', text):
        protected.append(quoted.span())
        token = quoted.group(1)
        line_start = int(quoted.group(2)) if quoted.group(2) else None
        line_end = int(quoted.group(3)) if quoted.group(3) else line_start
        if line_start is None:
            inside = re.fullmatch(r'(.+):(\d+)(?:-(\d+))?', token)
            if inside and token not in entries:
                token = inside.group(1)
                line_start = int(inside.group(2))
                line_end = int(inside.group(3)) if inside.group(3) else line_start
        try:
            path, resolution = plan_path_resolution(token, entries)
        except ValueError:
            if '/' in token or '.' in token:
                raise
            continue
        validate_plan_range(line_start, line_end, location=quoted.group(0))
        candidates.append((quoted.start(), quoted.end(), token, path, resolution,
                           line_start, line_end))

    occupied = list(protected)
    for token in sorted((path for path in entries if '/' in path),
                        key=lambda value: (-len(value), value)):
        start = 0
        while True:
            start = text.find(token, start)
            if start < 0:
                break
            path_end = start + len(token)
            line_start, line_end, end = plan_location_suffix(text, path_end)
            if (not any(left <= start < right or left < end <= right
                        for left, right in occupied)
                    and plan_path_boundary(text, start, end)):
                validate_plan_range(line_start, line_end, location=text[start:end])
                candidates.append((start, end, token, token, 'direct', line_start, line_end))
                occupied.append((start, end))
            start = path_end

    basename_paths = {}
    for path in entries:
        basename_paths.setdefault(Path(path).name, []).append(path)
    for token in sorted(basename_paths, key=lambda value: (-len(value), value)):
        start = 0
        while True:
            start = text.find(token, start)
            if start < 0:
                break
            path_end = start + len(token)
            line_start, line_end, end = plan_location_suffix(text, path_end)
            if (not any(left <= start < right or left < end <= right
                        for left, right in occupied)
                    and plan_path_boundary(text, start, end)):
                paths = sorted(basename_paths[token])
                if len(paths) != 1:
                    raise ValueError(f'ambiguous basename in pinned snapshot "{token}"')
                validate_plan_range(line_start, line_end, location=text[start:end])
                candidates.append((start, end, token, paths[0], 'basename',
                                   line_start, line_end))
                occupied.append((start, end))
            start = path_end

    token_re = re.compile(
        r'(?<![\w@.-])((?:[\w@.-]+/)+[\w@.-]+'
        r'|[\w@-]+(?:\.[\w@.-]+)+'
        r'|Makefile|makefile|Justfile|justfile|Dockerfile|Containerfile)'
        r'(?::(\d+)(?:-(\d+))?)?')
    for match in token_re.finditer(text):
        if any(left <= match.start() and match.end() <= right for left, right in occupied):
            continue
        token = match.group(1)
        plan_path_resolution(token, entries)
        raise ValueError(f'unparsed path "{token}"')

    rows = []
    bound_spans = []
    candidates.sort(key=lambda row: row[0])
    for index, match in enumerate(candidates):
        start, end, token, path, resolution, line_start, line_end = match
        bound_spans.append((start, end))
        row = {'path': path, 'line_start': line_start, 'line_end': line_end,
               'token': token, 'resolution': resolution}
        if row not in rows:
            rows.append(row)
        next_start = candidates[index + 1][0] if index + 1 < len(candidates) else len(text)
        for shorthand in re.finditer(
                r'(?:^|[,;])\s*:(\d+)(?:-(\d+))?\b', text[end:next_start]):
            bound_spans.append((end + shorthand.start(), end + shorthand.end()))
            extra_start = int(shorthand.group(1))
            extra_end = int(shorthand.group(2)) if shorthand.group(2) else extra_start
            validate_plan_range(extra_start, extra_end, location=shorthand.group(0).lstrip(',; '))
            extra = dict(row, line_start=extra_start, line_end=extra_end)
            if extra not in rows:
                rows.append(extra)
    for number in re.finditer(r'(?<![\w.]):?\d+(?:-\d+)?(?![\w.])', text):
        if not any(start <= number.start() and number.end() <= end for start, end in bound_spans):
            raise ValueError(f'unparsed line range "{number.group(0)}"')
    return rows


def validate_plan_source_location(repo, entries, row):
    try:
        entry = entries[row['path']]
    except KeyError as error:
        raise ValueError(f'path is absent from pinned source "{row["path"]}"') from error
    body = repo.blob(entry)
    if (entry[0] not in ('100644', '100755') or body is OVERSIZED_BLOB or b'\0' in body):
        raise ValueError(f'path is opaque or oversized "{row["path"]}"')
    try:
        lines = split_lf_text(body.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ValueError(f'path is not UTF-8 "{row["path"]}"') from error
    location = f"{row['path']}:{row['line_start']}"
    if row['line_end'] != row['line_start']:
        location += f"-{row['line_end']}"
    validate_plan_range(row['line_start'], row['line_end'], len(lines), location)


def plan_field_refusal(cluster_id, field, error):
    name = field.capitalize()
    form = ('<path>[:<start>[-<end>]], ... (found by: <search>)' if field == 'sites'
            else '<path> - <reason>; <path> - <reason>' if field == 'excluded'
            else '<path> - <what fails today>')
    return ValueError(f'plan cluster {cluster_id} field {name}: {error}; expected {name}: {form}')


def reject_plan_artifact_collision(entries, label):
    name = f'r{label}-plan.md'
    if name in entries:
        raise ValueError('repository path collides with generated plan artifact: ' + name)


def parse_plan(raw, entries):
    if not raw or len(raw) > PLAN_MAX_BYTES or b'\0' in raw:
        raise ValueError('plan snapshot is empty, opaque, or oversized')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('plan snapshot is not UTF-8') from error
    headings = list(re.finditer(r'(?m)^##\s+(C-[A-Za-z0-9][A-Za-z0-9-]*)\b[^\n]*$', text))
    if not headings:
        raise ValueError('plan contains no parseable clusters')
    clusters = []
    for index, heading in enumerate(headings):
        body = text[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)]
        fields = {}; current = None
        for line in split_lf_text(body):
            if not line.strip():
                continue
            field = re.match(r'^([A-Za-z][A-Za-z ]*):\s*(.*)$', line)
            if field:
                key = ' '.join(field.group(1).lower().split())
                if key in fields:
                    raise ValueError('duplicate plan cluster field: ' + key)
                fields[key] = field.group(2).strip(); current = key
            elif current is not None and (line[:1].isspace() or line.lstrip().startswith(('-', '*'))):
                fields[current] = (fields[current] + ' ' + line.strip()).strip()
            else:
                raise ValueError('unparsed plan cluster content: ' + heading.group(1))
        required = {'findings', 'rule', 'sites', 'prediction'}
        if not required <= set(fields) or not any(key in fields for key in ('test', 'tests', 'regression')):
            raise ValueError('incomplete plan cluster: ' + heading.group(1))
        path_rows = []
        for field_name in ('sites', 'test', 'tests', 'regression'):
            if field_name not in fields:
                continue
            field_text = fields[field_name]
            if field_name == 'sites':
                search = re.search(r'\(\s*found\s+by:', field_text, re.I)
                if search:
                    field_text = field_text[:search.start()].rstrip()
            else:
                # Only the leading test path is a location; the rest of the field is prose.
                field_text = re.match(r'(?:`[^`\n]+`\S*|\S+)?', field_text).group(0)
            try:
                resolved = plan_field_paths(field_text, entries)
                if not resolved:
                    raise ValueError(f'no resolvable path "{field_text}"')
            except ValueError as error:
                raise plan_field_refusal(heading.group(1), field_name, error) from None
            for row in resolved:
                item = dict(row, field=field_name)
                if item not in path_rows:
                    path_rows.append(item)
        search_contract = plan_search_contract(fields['sites'])
        try:
            excluded = plan_excluded_paths(fields.get('excluded', ''))
        except ValueError as error:
            raise plan_field_refusal(heading.group(1), 'excluded', error) from None
        clusters.append({'id': heading.group(1), 'search_pattern': search_contract['pattern'],
                         'search_contract': search_contract, 'paths': path_rows,
                         'excluded': sorted(excluded)})
    ids = [cluster['id'] for cluster in clusters]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate plan cluster identifier')
    return clusters


def plan_closure_paths(clusters, dependencies, changed):
    resolved = {row['path'] for cluster in clusters for row in cluster['paths']}
    closure = resolved & set(changed)
    for edge in dependencies:
        if edge['kind'] != 'local-import':
            continue
        if edge['source'] in resolved and edge['target'] in changed:
            closure.add(edge['target'])
        if edge['target'] in resolved and edge['source'] in changed:
            closure.add(edge['source'])
    return sorted(closure)


def markdown(data, json_path):
    lines = ['# Evidence navigation index', '', f'Complete deterministic facts: {json_path}',
             'Navigation only. Verify claims in source and expand when evidence is insufficient.']
    for section in ('symbols', 'call_sites', 'related_tests', 'gates', 'instructions'):
        rows = data[section]
        lines.extend(['', section.replace('_', ' ').title() + ':'])
        included = 0
        for row in rows[:12]:
            rendered = json.dumps(row, sort_keys=True, ensure_ascii=True)
            if len(rendered.encode()) > NAVIGATION_ROW_LIMIT:
                continue
            candidate = '- ' + rendered
            projected = ('\n'.join([*lines, candidate]) + '\n').encode()
            if len(projected) > NAVIGATION_TOTAL_LIMIT - 512:
                continue
            lines.append(candidate); included += 1
        row_hash = digest(encoded(rows))
        lines.append(f'Omitted: {len(rows) - included}; complete list SHA-256: {row_hash}; complete list in JSON.')
    lines.extend(['', *data['limitations']])
    packet = ('\n'.join(lines) + '\n').encode()
    if len(packet) > NAVIGATION_TOTAL_LIMIT:
        raise ValueError('navigation packet exceeds byte limit')
    return packet


def assignments(args, roster):
    if not isinstance(roster, dict) or not isinstance(roster.get('seats'), list) or any(not isinstance(s, dict) for s in roster['seats']):
        raise ValueError('invalid roster shape')
    seats = [s['seat'] for s in roster['seats'] if not s.get('extra')]
    if not seats or len(set(seats)) != len(seats) or any(not SAFE_NAME.fullmatch(s) for s in seats):
        raise ValueError('invalid core roster')
    chosen = {}
    for assignment in args.assignment:
        seat, sep, bundle = assignment.partition('=')
        if not sep or seat not in seats or not bundle:
            raise ValueError('invalid assignment')
        values = chosen.get(seat, '').split('+') if seat in chosen else []
        values.extend(bundle.split('+'))
        chosen[seat] = '+'.join(dict.fromkeys(values))
    if not chosen and args.phase == 'plan':
        raise ValueError('plan panel requires explicit canonical assignments')
    if not chosen:
        chosen = {s: 'simplicity' if args.phase == 'discovery' else 'unassigned' for s in seats}
    if args.phase not in ('repair', 'plan') and set(chosen) != set(seats):
        raise ValueError('panel assignments must include every core seat')
    owner = args.full_seat
    chosen = {s: chosen[s] for s in seats if s in chosen}
    validate_assignment_topology(chosen, seats, args.phase)
    bundles = phase_bundles(args.phase)
    regression_owner = next((s for s, b in chosen.items() if bundles[-1] in b.split('+')), None)
    if args.phase == 'plan':
        regression_owner = next((s for s, b in chosen.items() if PLAN_BUNDLES[0] in b.split('+')), None)
    if args.phase in ('risk', 'verification', 'plan') and owner is not None and owner != regression_owner:
        raise ValueError('full seat conflicts with regression bundle owner')
    if owner is None:
        owner = regression_owner
        if args.phase in ('discovery', 'repair'):
            owner = next(iter(chosen))
    if owner is not None and owner not in chosen:
        raise ValueError('full seat must be assigned')
    if args.phase == 'repair' and len(chosen) != 1:
        raise ValueError('repair requires exactly one full seat')
    return chosen, owner


def bundle_coverage(chosen, bundles=BUNDLES):
    return set(b for value in chosen.values() for b in value.split('+')) == set(bundles)


def single_seat_plan(chosen):
    """A one-seat plan panel is one plan-completeness seat that owns every cluster."""
    return list(chosen.values()) == [PLAN_BUNDLES[0]]


def canonical_bundle_topology(seats, bundles=BUNDLES):
    if len(seats) < 3:
        return None
    if tuple(bundles) == PLAN_BUNDLES:
        if len(seats) == 3:
            return {seats[0]: PLAN_BUNDLES[0] + '+' + PLAN_BUNDLES[3],
                    seats[1]: PLAN_BUNDLES[1], seats[2]: PLAN_BUNDLES[2]}
        topology = [[PLAN_BUNDLES[index]] for index in range(4)]
        topology.extend([[PLAN_BUNDLES[1 + (index - 4) % 3]]
                         for index in range(4, len(seats))])
        return {seat: '+'.join(values) for seat, values in zip(seats, topology)}
    topology = [[bundles[index % len(bundles)]] for index in range(len(seats))]
    if len(seats) == 3:
        topology[0].append(bundles[3])
    return {seat: '+'.join(values) for seat, values in zip(seats, topology)}


def validate_assignment_topology(chosen, seats, phase):
    if phase == 'repair':
        return
    if phase == 'plan':
        expected = canonical_bundle_topology(seats, PLAN_BUNDLES)
        if single_seat_plan(chosen) or chosen == expected:
            return
        panel = ' '.join(seat + '=' + bundle for seat, bundle in (expected or {}).items())
        raise ValueError('plan assignment does not match canonical seat topology; expected '
                         + (panel + ' or ' if panel else '') + 'one <seat>=' + PLAN_BUNDLES[0])
    if len(seats) < 3:
        raise ValueError('review panel requires at least three core seats')
    if phase == 'discovery':
        if chosen != {seat: 'simplicity' for seat in seats}:
            raise ValueError('invalid discovery seat topology')
        return
    if set(chosen.values()) == {'unassigned'}:
        return
    if chosen != canonical_bundle_topology(seats, phase_bundles(phase)):
        raise ValueError('risk bundle assignment does not match canonical seat topology')


def instruction_directories(paths):
    directories = {Path('.')}
    for path in paths:
        parent = Path(path).parent
        directories.update(directory for directory in (*reversed(parent.parents), parent)
                           if not directory.is_absolute() and '..' not in directory.parts)
    return sorted(directories, key=lambda directory: (len(directory.parts), directory.as_posix()))


def selected_instruction_paths(paths, exists):
    selected = []
    for directory in instruction_directories(paths):
        override = (directory / 'AGENTS.override.md').as_posix()
        ordinary = (directory / 'AGENTS.md').as_posix()
        if exists(override):
            selected.append(override)
        elif exists(ordinary):
            selected.append(ordinary)
    return selected


def instruction_coverage_paths(evidence, changed, clusters=None):
    paths = set(changed)
    for field in ('symbols', 'call_sites', 'related_tests', 'gates'):
        paths.update(row['path'] for row in evidence.get(field, []) if isinstance(row, dict))
    for edge in evidence.get('dependencies', []):
        if isinstance(edge, dict):
            paths.update(edge.get(key) for key in ('source', 'target') if edge.get(key))
    paths.update(row['path'] for cluster in clusters or [] for row in cluster['paths'])
    return sorted(paths)


def instructions(repo, snapshot, paths, worktree=True):
    entries = repo.entries(snapshot)
    wanted = selected_instruction_paths(
        paths, (lambda name: os.path.lexists(repo.root / name)) if worktree else entries.__contains__)
    rows = []; packet = []
    def local_files():
        for name in wanted:
            path = repo.root / name
            if any(parent.is_symlink() for parent in path.parents if parent != repo.root and repo.root in parent.parents):
                raise ValueError('redirected repository instruction ancestor: ' + name)
            if not os.path.lexists(path):
                continue
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
                raise ValueError('applicable instruction file is not safe regular text: ' + name)
            yield name, path.read_bytes()
    if worktree:
        source = local_files()
    else:
        repo.preload({name: entries[name] for name in wanted})
        source = ((name, repo.blob(entries[name])) for name in wanted)
    for name, raw in source:
        if (not worktree and (entries[name][0] not in ('100644', '100755')
                             or raw is OVERSIZED_BLOB)) or b'\0' in raw:
            raise ValueError('applicable instruction file is not readable text: ' + name)
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('applicable instruction file is not readable text: ' + name) from error
        rows.append({'path': name, 'sha256': digest(raw)})
        packet.append('# ' + name + '\n\n' + text.rstrip() + '\n')
    return rows, ('\n'.join(packet)).encode()


def is_prose_path(path):
    return Path(path).suffix.lower() in {
        '.adoc', '.asc', '.markdown', '.md', '.mdx', '.org', '.rst', '.text', '.txt'}


def components_for(patches, dependencies, chosen, owner, findings=None):
    changed = set(patches)
    parents = {path: path for path in changed}
    def leader(path):
        while parents[path] != path:
            parents[path] = parents[parents[path]]; path = parents[path]
        return path
    def join(source, target):
        left, right = leader(source), leader(target)
        parents[max(left, right)] = min(left, right)
    edges = [{'source': source, 'target': target, 'kind': kind}
             for source, target, kind in sorted({
                 (edge['source'], edge['target'], edge['kind']) for edge in dependencies})]
    production = {path for path in changed if not is_test_path(path) and not is_prose_path(path)}
    for edge in edges:
        if (edge['kind'] == 'local-import' and edge['source'] in production
                and edge['target'] in production):
            join(edge['source'], edge['target'])
    for test in sorted(path for path in changed if is_test_path(path)):
        targets = {edge['target'] for edge in edges
                   if edge['source'] == test and edge['kind'] in ('local-import', 'related-test')
                   and edge['target'] in production}
        if len(targets) == 1:
            join(test, next(iter(targets)))
    groups = {}
    for path in sorted(changed):
        groups.setdefault(leader(path), []).append(path)
    specialists = [seat for seat in chosen if seat != owner]
    loads = {seat: 0 for seat in specialists}; result = []
    for root, files in groups.items():
        files = sorted(files)
        component_edges = [edge for edge in edges
                           if edge['source'] in files or edge['target'] in files]
        boundary = sorted(set(files) | {edge[key] for edge in component_edges
                                       for key in ('source', 'target')})
        result.append({'id': digest(encoded(files)), 'files': files, 'boundary': boundary,
                       'edges': component_edges,
                       'words': sum(len(patches[p].split()) for p in files), 'specialists': [],
                       'prior_owners': [], 'full_state_owner': owner})
    for component in sorted(result, key=lambda c: (-c['words'], c['files'])):
        prior = sorted({s for finding in (findings or []) if finding['file'] in component['boundary']
                        for s in finding['owners'] if s in chosen})
        component['prior_owners'] = prior
        targets = [s for s in specialists if s in prior]
        if not targets and specialists:
            targets = [min(specialists, key=lambda s: loads[s])]
        component['specialists'] = targets
        for seat in targets:
            loads[seat] += component['words']
    if result:
        smallest = min(result, key=lambda c: (c['words'], c['files']))
        for seat in specialists:
            if not any(seat in c['specialists'] for c in result):
                smallest['specialists'].append(seat)
    return sorted(result, key=lambda c: c['files'])


def plan_cluster_assignments(chosen, owner, clusters):
    specialists = [seat for seat in chosen if seat != owner]
    assigned = {seat: [] for seat in chosen}
    assigned[owner] = [cluster['id'] for cluster in clusters]
    for index, cluster in enumerate(clusters if specialists else []):
        assigned[specialists[index % len(specialists)]].append(cluster['id'])
    return assigned


def split_plan_cluster_assignments(chosen, owner, clusters):
    delta = plan_cluster_assignments(chosen, owner, clusters)
    proof = {seat: list(cluster_ids) for seat, cluster_ids in delta.items()}
    delta[owner] = []
    specialists = [seat for seat in chosen if seat != owner]
    for index, seat in enumerate(specialists):
        if not proof[seat]:
            proof[seat] = [clusters[index % len(clusters)]['id']]
    return proof, delta


def plan_delta_paths(chosen, owner, clusters, delta_assignments, dependencies, changed):
    specialists = [seat for seat in chosen if seat != owner]
    closure_by_cluster = {
        cluster['id']: set(plan_closure_paths([cluster], dependencies, changed))
        for cluster in clusters
    }
    result = {seat: [] for seat in chosen}
    for path in sorted(changed):
        candidates = [seat for seat in specialists
                      if any(path in closure_by_cluster[cluster_id]
                             for cluster_id in delta_assignments[seat])]
        if candidates:
            target = min(candidates, key=lambda seat: (
                sum(len(changed[value].split()) for value in result[seat]),
                specialists.index(seat)))
            result[target].append(path)
    return result


def plan_components_for(patches, dependencies, chosen, owner, clusters, routed=True,
                        cluster_assignments=None):
    components = components_for(patches, dependencies, chosen, owner)
    if not routed or len(chosen) == 1:
        specialists = [seat for seat in chosen if seat != owner]
        required = {row['path'] for cluster in clusters for row in cluster['paths']}
        for component in components:
            component['specialists'] = specialists.copy()
            component['prior_owners'] = []
            component['boundary'] = sorted(set(component['boundary']) | required)
        return components
    split_contract = cluster_assignments is not None
    assigned = cluster_assignments or plan_cluster_assignments(chosen, owner, clusters)
    specialist_order = [seat for seat in chosen if seat != owner]
    changed = set(patches)
    cluster_paths = {
        cluster['id']: set(plan_closure_paths([cluster], dependencies, changed))
        for cluster in clusters
    }
    routed_components = []
    for component in components:
        ids = [cluster['id'] for cluster in clusters
               if set(component['files']) & cluster_paths[cluster['id']]]
        cluster_owner = {cluster_id: seat for seat in specialist_order
                         for cluster_id in assigned[seat]}
        owners = [seat for seat in specialist_order
                  if any(cluster_id in assigned[seat] for cluster_id in ids)]
        files_by_owner = {seat: [] for seat in owners}
        if not split_contract:
            for path in component['files']:
                candidates = [cluster_owner[cluster_id] for cluster_id in ids
                              if path in cluster_paths[cluster_id]]
                candidates = [seat for seat in owners if seat in candidates]
                if candidates:
                    target = min(candidates, key=lambda seat: (
                        sum(len(patches[value].split()) for value in files_by_owner[seat]),
                        specialist_order.index(seat)))
                    files_by_owner[target].append(path)
        for seat in owners:
            owned_ids = [cluster_id for cluster_id in ids if cluster_id in assigned[seat]]
            if split_contract:
                files = sorted(path for path in component['files']
                               if any(path in cluster_paths[cluster_id] for cluster_id in owned_ids))
            else:
                if not files_by_owner[seat]:
                    candidates = sorted(path for cluster_id in owned_ids
                                        for path in set(component['files']) & cluster_paths[cluster_id])
                    if candidates:
                        files_by_owner[seat].append(candidates[0])
                files = sorted(set(files_by_owner[seat]))
            if not files:
                continue
            required = {row['path'] for cluster in clusters if cluster['id'] in owned_ids
                        for row in cluster['paths']}
            edges = [edge for edge in component['edges']
                     if edge['source'] in files or edge['target'] in files]
            boundary = set(files) | required
            boundary.update(edge[key] for edge in edges for key in ('source', 'target'))
            routed_components.append({
                'id': digest(encoded({'files': files, 'specialist': seat,
                                      'clusters': owned_ids})),
                'files': files,
                'boundary': sorted(boundary),
                'edges': edges,
                'words': sum(len(patches[path].split()) for path in files),
                'specialists': [seat],
                'prior_owners': [],
                'full_state_owner': owner,
            })
    return sorted(routed_components, key=lambda component: component['files'])


def hunk_binding(component_ids, component_by_id, hunks_by_path):
    return digest(encoded([
        {'component_id': component_id,
         'hunk_sha256': sorted(value for path in component_by_id[component_id]['files']
                               for value in hunks_by_path.get(path, []))}
        for component_id in sorted(component_ids)
    ]))


def plan_mandatory_source_windows(manifest, packet):
    """Cluster source windows the seat opens itself, in the order the prompt lists them.

    Every cited cluster row is either delivered as a prepared segment or a packet entry, or
    falls inside one of these windows, so reading them all closes the cluster obligation.
    """
    if manifest.get('phase') != 'plan':
        return []
    return list(packet.get('mandatory_source_windows') or [])


def merge_repository_windows(ranges):
    by_path = {}
    for path, start, end in ranges:
        by_path.setdefault(path, []).append((start, end))
    result = []
    for path, values in sorted(by_path.items()):
        union = []
        for start, end in sorted(values):
            if union and start <= union[-1][1] + 1:
                union[-1] = (union[-1][0], max(union[-1][1], end))
            else:
                union.append((start, end))
        windows = []
        for start, end in union:
            while start <= end:
                windows.append((start, min(end, start + READ_LINES - 1)))
                start += READ_LINES
        merged = []
        for start, end in windows:
            if merged and end - merged[-1][0] + 1 <= READ_LINES:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        result.extend((path, start, end) for start, end in merged)
    return result


def plan_source_requirements(assignment, plan_clusters):
    assigned = set(assignment.get('plan_clusters', []))
    return [row for cluster in plan_clusters or [] if cluster['id'] in assigned
            for row in cluster['paths']]


def uncovered_plan_ranges(assignment, plan_clusters, delivered):
    missing = []
    for required in plan_source_requirements(assignment, plan_clusters):
        matching = [row for row in delivered if row['path'] == required['path']]
        if required['line_start'] is None:
            if not matching:
                missing.append((required['path'], 1, 1))
            continue
        intervals = [(required['line_start'], required['line_end'])]
        for row in sorted(matching, key=lambda value: (value['line_start'], value['line_end'])):
            remaining = []
            for start, end in intervals:
                if row['line_end'] < start or row['line_start'] > end:
                    remaining.append((start, end))
                    continue
                if start < row['line_start']:
                    remaining.append((start, row['line_start'] - 1))
                if row['line_end'] < end:
                    remaining.append((row['line_end'] + 1, end))
            intervals = remaining
        missing.extend((required['path'], start, end) for start, end in intervals)
    return missing


def mandatory_repository_windows(assignment, plan_clusters, delivered):
    return merge_repository_windows(
        uncovered_plan_ranges(assignment, plan_clusters, delivered))


def published_mandatory_windows(assignment, plan_clusters, delivered):
    """The cluster source windows a plan seat opens itself, as published manifest rows."""
    if not plan_clusters:
        return []
    return [{'path': path, 'line_start': start, 'line_end': end}
            for path, start, end in mandatory_repository_windows(
                assignment, plan_clusters, delivered)]


def grouped_plan_source_promotions(assignment, plan_clusters, delivered, omitted,
                                   segment_cost):
    selected = set()
    while True:
        promoted = delivered + [omitted[index] for index in sorted(selected)]
        missing = uncovered_plan_ranges(assignment, plan_clusters, promoted)
        direct = merge_repository_windows(missing)
        if len(direct) <= MANDATORY_REPOSITORY_READ_LIMIT:
            return sorted(selected)
        choices = []
        for path, window_start, window_end in direct:
            intervals = sorted([
                (max(start, window_start), min(end, window_end))
                for missing_path, start, end in missing
                if missing_path == path and start <= window_end and end >= window_start
            ])
            targets = []
            for start, end in intervals:
                if targets and start <= targets[-1][1] + 1:
                    targets[-1] = (targets[-1][0], max(targets[-1][1], end))
                else:
                    targets.append((start, end))
            group = set()
            target_index = 0
            cursor = targets[0][0] if targets else None
            while cursor is not None:
                candidates = [
                    (row['line_end'], -row.get('priority', index), -index, index)
                    for index, row in enumerate(omitted)
                    if index not in selected and row['path'] == path
                    and row['line_start'] <= cursor <= row['line_end']
                ]
                if not candidates:
                    group = set()
                    break
                index = max(candidates)[-1]
                group.add(index)
                cursor = omitted[index]['line_end'] + 1
                while target_index < len(targets) and targets[target_index][1] < cursor:
                    target_index += 1
                if target_index == len(targets):
                    cursor = None
                elif cursor < targets[target_index][0]:
                    cursor = targets[target_index][0]
            if not group:
                continue
            trial_delivered = promoted + [omitted[index] for index in sorted(group)]
            trial = mandatory_repository_windows(assignment, plan_clusters, trial_delivered)
            reduction = len(direct) - len(trial)
            if reduction <= 0:
                continue
            cost = sum(segment_cost(index, omitted[index]) for index in group)
            priorities = tuple(sorted(omitted[index].get('priority', index) for index in group))
            choices.append((-reduction, cost, priorities, path, window_start, window_end,
                            tuple(sorted(group))))
        if not choices:
            raise ValueError('mandatory plan source reads exceed repository capacity')
        selected.update(min(choices)[-1])


def source_context(repo, snapshot, base_tree, evidence, components, assigned, owner, prefix,
                   enabled=True, plan_clusters=None):
    entries = repo.entries(snapshot)
    base_entries = repo.entries(base_tree)
    hunks_by_path = {}
    for hunk in evidence['hunks']:
        hunks_by_path.setdefault(hunk['path'], []).append(hunk['sha256'])
    integration = owner if owner in assigned else next(iter(assigned))
    component_by_id = {component['id']: component for component in components}
    calls_by_name = {}
    for call in evidence['call_sites']:
        calls_by_name.setdefault(call['name'], []).append(call)
    tests_by_path = {test['path']: test for test in evidence['related_tests']}
    result = {'schema_version': 3, 'enabled': enabled, 'snapshot_tree': snapshot,
              'base_tree': base_tree, 'max_shard_bytes': SOURCE_CONTEXT_LIMIT,
              'packet_batch_limit': SOURCE_PACKET_BATCH_LIMIT, 'seats': {}}
    artifacts = {}

    source_choice_cache = {}
    def source_choice(path, preferred_tree=None):
        cache_key = (path, preferred_tree)
        if cache_key in source_choice_cache:
            return source_choice_cache[cache_key]
        choices = [(entries.get(path), snapshot), (base_entries.get(path), base_tree)]
        if preferred_tree == base_tree:
            choices.reverse()
        choices = [(entry, tree) for entry, tree in choices
                   if entry and entry[0] in ('100644', '100755')]
        if not choices:
            source_choice_cache[cache_key] = ('nontext', None)
            return source_choice_cache[cache_key]
        readable = []
        for entry, blob_tree in choices:
            raw = repo.blob(entry)
            if raw is OVERSIZED_BLOB or b'\0' in raw:
                continue
            try:
                raw.decode('utf-8')
            except UnicodeDecodeError:
                continue
            readable.append((entry, split_lf_lines(raw), blob_tree))
        choice = next((value for value in readable if value[1]), readable[0] if readable else None)
        source_choice_cache[cache_key] = ('source' if choice else 'unrepresentable', choice)
        return source_choice_cache[cache_key]

    for seat, assignment in assigned.items():
        component_ids = set(assignment['components'])
        relevant = [component for component in components if component['id'] in component_ids]
        hunk_ids = sorted({value for component in relevant for path in component['files']
                           for value in hunks_by_path.get(path, [])})
        if not enabled:
            result['seats'][seat] = {'role': 'integration' if seat == integration else 'specialist',
                                     'components': sorted(component_ids), 'hunk_sha256': hunk_ids,
                                     'shards': [], 'omitted': {kind: 0 for kind in SOURCE_CONTEXT_REASONS},
                                     'omitted_source_ranges': [],
                                     'required_source_ranges': [],
                                     'mandatory_source_windows': published_mandatory_windows(
                                         assignment, plan_clusters, []),
                                     'source_read_required': bool(component_ids)}
            continue
        tiers = {kind: [] for kind in SOURCE_CONTEXT_REASONS}
        relevant_by_path = {}
        for component in relevant:
            for path in component['boundary']:
                relevant_by_path.setdefault(path, []).append(component)

        def mapped(path, candidates=None):
            values = relevant_by_path.get(path, [])
            if candidates is None:
                return values
            ids = {component['id'] for component in candidates}
            return [component for component in values if component['id'] in ids]

        def add(kind, reason, path, line_start, line_end, mapped_components,
                preferred_tree=None):
            ids = sorted(component['id'] for component in mapped_components)
            hashes = {value for component in mapped_components for changed in component['files']
                      for value in hunks_by_path.get(changed, [])}
            if ids and hashes:
                tiers[kind].append({'path': path, 'line_start': line_start, 'line_end': line_end,
                                    'reason': reason, 'component_ids': ids,
                                    'preferred_tree': preferred_tree})

        for symbol in evidence['symbols']:
            symbol_components = mapped(symbol['path'])
            if not symbol_components:
                continue
            name = symbol['name'] or 'changed-line-anchor'
            add('declaration', 'declaration:' + name, symbol['path'], symbol['line'], symbol['line_end'],
                symbol_components, symbol.get('blob_tree'))
            if not symbol['name']:
                continue
            calls = [call for call in calls_by_name.get(symbol['name'], [])
                     if not is_test_path(call['path'])
                     and (call['path'], call['line']) != (symbol['path'], symbol['line'])]
            calls = [call for call in calls if mapped(call['path'], symbol_components)]
            if calls:
                call = calls[0]
                add('production-caller', 'production-caller:' + symbol['name'], call['path'],
                    call['line'] - 2, call['line'] + 2, mapped(call['path'], symbol_components))
            for call in calls[1:]:
                add('extra-caller', 'extra-caller:' + symbol['name'], call['path'],
                    call['line'] - 2, call['line'] + 2, mapped(call['path'], symbol_components))

        for component in relevant:
            tests = [tests_by_path[path] for path in component['boundary'] if path in tests_by_path]
            if tests:
                test = tests[0]
                add('related-test', 'related-test:' + component['id'], test['path'], 1, 16, [component])
            for test in tests[1:]:
                add('extra-test', 'extra-test:' + component['id'], test['path'], 1, 16, [component])

        for gate in evidence['gates']:
            line = gate.get('line', 1)
            gate_components = mapped(gate['path']) or relevant
            add('gate', 'gate:' + gate['path'] + ':' + str(gate.get('line', 'file')),
                gate['path'], line - 2 if 'line' in gate else 1,
                line + 2 if 'line' in gate else 16, gate_components)

        seat_cluster_ids = set(assignment.get('plan_clusters', []))
        for cluster in (cluster for cluster in plan_clusters or []
                        if cluster['id'] in seat_cluster_ids):
            for site in cluster['paths']:
                site_components = mapped(site['path']) or relevant
                line_start = site['line_start'] or 1
                line_end = site['line_end'] or 16
                add('declaration', 'declaration:plan-site:' + cluster['id'], site['path'],
                    max(1, line_start - 4), line_end + 4, site_components)

        candidates = []
        for kind in SOURCE_CONTEXT_REASONS:
            for row in sorted(tiers[kind], key=lambda item: (item['path'], item['line_start'],
                                                              item['line_end'], item['reason'],
                                                              item['preferred_tree'] or '')):
                candidates.append(row)
        def context_rank(row):
            reason = row['reason']
            if reason.startswith('declaration:plan-site:'):
                return 0
            if reason.startswith('declaration:') and reason != 'declaration:changed-line-anchor':
                return 0
            if reason.startswith('production-caller:'):
                return 1
            if reason.startswith('related-test:'):
                return 2
            if reason.startswith('extra-caller:'):
                return 3
            if reason.startswith('extra-test:'):
                return 4
            if reason.startswith('gate:'):
                return 5
            return 6
        candidates.sort(key=lambda row: (context_rank(row), row['path'], row['line_start'],
                                         row['line_end'], row['reason'],
                                         row['preferred_tree'] or ''))
        for priority, row in enumerate(candidates):
            row['priority'] = priority
        omitted = {kind: 0 for kind in SOURCE_CONTEXT_REASONS}
        required_ranges = []
        omitted_source_ranges = []
        source_rows = {}
        nontext_paths = set()
        unrepresentable_paths = set()
        changed_paths = {path for component in relevant for path in component['files']}
        source_keys = {(row['path'], row['preferred_tree']) for row in candidates}
        source_keys.update((path, None) for path in changed_paths)
        for path, preferred_tree in sorted(source_keys, key=lambda item: (item[0], item[1] or '')):
            kind, choice = source_choice(path, preferred_tree)
            source_key = (path, preferred_tree)
            if kind == 'nontext':
                nontext_paths.add(source_key)
                continue
            if choice is not None:
                source_rows[source_key] = choice
            else:
                unrepresentable_paths.add(source_key)

        prepared = []
        for row in candidates:
            source_key = (row['path'], row['preferred_tree'])
            source = source_rows.get(source_key)
            if not source:
                if source_key in nontext_paths:
                    continue
                if seat == integration:
                    raise ValueError('required source range cannot be represented: ' + row['path'])
                omitted[row['reason'].split(':', 1)[0]] += 1
                continue
            entry, lines, blob_tree = source
            start = max(1, row['line_start']); end = min(len(lines), max(start, row['line_end']))
            if not lines or start > len(lines):
                continue
            prepared.append(dict(
                {key: value for key, value in row.items() if key != 'preferred_tree'},
                line_start=start, line_end=end, blob_mode=entry[0], blob_oid=entry[1],
                blob_tree=blob_tree))

        represented = {component['id'] for component in relevant for row in prepared
                       if row['path'] in component['files']
                       and component['id'] in row['component_ids']}
        required_components = {component['id'] for component in relevant
                               if any((path, None) in unrepresentable_paths
                                      or ((path, None) in source_rows and source_rows[(path, None)][1])
                                      for path in component['files'])}
        missing = sorted(required_components - represented)
        if seat == integration and missing:
            details = [component['id'] + ':' + ','.join(component['files'])
                       for component in relevant if component['id'] in missing]
            raise ValueError('assigned semantic component has no representable changed-source context: '
                             + ';'.join(details))

        prepared_by_path = {}
        for row in prepared:
            prepared_by_path.setdefault((row['path'], row['blob_tree']), []).append(row)
        merged = []
        for (path, blob_tree), rows in sorted(prepared_by_path.items()):
            target = None
            for row in sorted(rows, key=lambda value: (
                    value['line_start'], value['line_end'], value['priority'])):
                if target is None or row['line_start'] > target['line_end']:
                    target = {'path': path, 'line_start': row['line_start'], 'line_end': row['line_end'],
                              'reason_rows': [(row['priority'], row['reason'])],
                              'component_ids': set(row['component_ids']), 'priority': row['priority'],
                              'blob_mode': row['blob_mode'], 'blob_oid': row['blob_oid'],
                              'blob_tree': blob_tree}
                    merged.append(target)
                    continue
                target['line_end'] = max(target['line_end'], row['line_end'])
                target['reason_rows'].append((row['priority'], row['reason']))
                target['component_ids'].update(row['component_ids'])
                target['priority'] = min(target['priority'], row['priority'])

        context_entries = []
        for row in sorted(merged, key=lambda value: value['priority']):
            _, lines, _ = source_choice(row['path'], row['blob_tree'])[1]
            content = b''.join(lines[row['line_start'] - 1:row['line_end']]).decode('utf-8')
            reason_priority = {}
            for priority, reason in row['reason_rows']:
                reason_priority[reason] = min(priority, reason_priority.get(reason, priority))
            ids = sorted(row['component_ids'])
            context_entries.append({'path': row['path'], 'line_start': row['line_start'],
                                    'line_end': row['line_end'],
                                    'reasons': [reason for reason, _ in sorted(
                                        reason_priority.items(), key=lambda item: (item[1], item[0]))],
                                    'component_ids': ids,
                                    'hunk_binding_sha256': hunk_binding(ids, component_by_id, hunks_by_path),
                                    'blob_oid': row['blob_oid'], 'blob_mode': row['blob_mode'],
                                    'blob_tree': row['blob_tree'],
                                    'content_sha256': digest(content.encode()),
                                    'priority': row['priority'], 'content': content})

        limit = 3 if seat == integration or plan_clusters is not None else 1
        shards = []; current = []; current_visible_bytes = 0

        def payload(index, values, count=limit):
            return {'schema_version': 1, 'snapshot_tree': snapshot, 'base_tree': base_tree,
                    'seat': seat, 'shard_index': index, 'shard_count': count, 'entries': values}

        for row in context_entries:
            index = len(shards) + 1
            single_payload = encoded(payload(index, [row]))
            single_payload_bytes = len(single_payload)
            single_payload_visible_bytes = predicted_source_visible_bytes(single_payload)
            if current:
                continuation_visible_bytes = (
                    predicted_source_visible_bytes(encoded(payload(index, [{}, row])))
                    - predicted_source_visible_bytes(encoded(payload(index, [{}]))))
                trial_visible_bytes = current_visible_bytes + continuation_visible_bytes
            else:
                trial_visible_bytes = single_payload_visible_bytes
            if trial_visible_bytes <= SOURCE_CONTEXT_LIMIT:
                current.append(row)
                current_visible_bytes = trial_visible_bytes
                continue
            if current and len(shards) + 1 < limit:
                shards.append(current); current = []
                index = len(shards) + 1
                single_payload = encoded(payload(index, [row]))
                single_payload_bytes = len(single_payload)
                single_payload_visible_bytes = predicted_source_visible_bytes(single_payload)
                if single_payload_visible_bytes <= SOURCE_CONTEXT_LIMIT:
                    current = [row]
                    current_visible_bytes = single_payload_visible_bytes
                    continue
            individually_oversized = single_payload_visible_bytes > SOURCE_CONTEXT_LIMIT
            for reason in row['reasons']:
                omitted[reason.split(':', 1)[0]] += 1
            if individually_oversized:
                required = {key: value for key, value in row.items() if key != 'content'}
                required['required_payload_bytes'] = single_payload_bytes
                required['required_payload_predicted_visible_bytes'] = single_payload_visible_bytes
                _, source_lines, _ = source_choice(row['path'], row['blob_tree'])[1]
                required['segments'] = partition_source_segments(
                    source_lines, row['line_start'], row['line_end'])
                required_ranges.append(required)
            else:
                omitted_source_ranges.append({
                    key: value for key, value in row.items() if key != 'content'})
        if current:
            shards.append(current)

        delivered = [
            {key: value for key, value in row.items() if key != 'content'}
            for shard in shards for row in shard
        ] + list(required_ranges)

        promotion_cache = {}
        def promotion(index, row):
            if index in promotion_cache:
                return promotion_cache[index]
            _, source_lines, _ = source_choice(row['path'], row['blob_tree'])[1]
            content = b''.join(source_lines[row['line_start'] - 1:row['line_end']]).decode('utf-8')
            payload_entry = dict(row, content=content)
            raw_payload = encoded(payload(1, [payload_entry], 1))
            required = dict(
                row,
                required_payload_bytes=len(raw_payload),
                required_payload_predicted_visible_bytes=predicted_source_visible_bytes(raw_payload),
                segments=partition_source_segments(
                    source_lines, row['line_start'], row['line_end']),
            )
            promotion_cache[index] = required
            return required

        try:
            promoted_indices = set(grouped_plan_source_promotions(
                assignment, plan_clusters, delivered, omitted_source_ranges,
                lambda index, row: len(promotion(index, row)['segments'])))
        except ValueError:
            raise ValueError(
                'mandatory plan source reads exceed repository capacity: ' + seat) from None
        retained = []
        for index, row in enumerate(omitted_source_ranges):
            if index in promoted_indices:
                required = promotion(index, row)
                required_ranges.append(required)
                delivered.append(required)
            else:
                retained.append(row)
        omitted_source_ranges = retained
        shard_rows = []
        count = len(shards)
        for index, values in enumerate(shards, 1):
            name = f'{prefix}-{seat}-source-context-{index}.json'
            raw = encoded(payload(index, values, count))
            artifacts[name] = raw
            ranges = [{key: value for key, value in row.items() if key != 'content'} for row in values]
            shard_rows.append({'artifact': name, 'sha256': digest(raw), 'bytes': len(raw),
                               'predicted_visible_bytes': predicted_source_visible_bytes(raw),
                               'entries': len(values), 'ranges': ranges})
        required_ranges = sorted(
            required_ranges,
            key=lambda row: (row['path'], row['blob_tree'], row['line_start'],
                             row['line_end'], row['priority']))
        for range_index, required in enumerate(required_ranges, 1):
            _, source_lines, _ = source_choice(required['path'], required['blob_tree'])[1]
            for segment in required['segments']:
                name = (f'{prefix}-{seat}-source-segment-{range_index:03d}-'
                        f"{segment['index']:03d}.txt")
                raw = b''.join(source_lines[segment['line_start'] - 1:segment['line_end']])
                segment['artifact'] = name
                artifacts[name] = raw
        # The promotion loop above already bounded what the seat must still open by hand.
        # Publish that exact window list: deriving it from every cited cluster row is what
        # two plan seats got wrong, each stopping a few windows short of the obligation.
        mandatory_source_windows = published_mandatory_windows(
            assignment, plan_clusters, delivered)
        result['seats'][seat] = {'role': 'integration' if seat == integration else 'specialist',
                                 'components': sorted(component_ids), 'hunk_sha256': hunk_ids,
                                 'shards': shard_rows, 'omitted': omitted,
                                 'omitted_source_ranges': omitted_source_ranges,
                                 'required_source_ranges': required_ranges,
                                 'mandatory_source_windows': mandatory_source_windows,
                                 'source_read_required': any(omitted.values()) or any(
                                     'declaration:changed-line-anchor' in row['reasons']
                                     for row in context_entries)}
    return result, artifacts


def compile_task_capacity(assignments, patch_sets, context, plan_clusters=None):
    seats = {}
    for seat, assignment in assignments.items():
        patch_set = patch_sets[assignment['patch_set']]
        patch_calls = (len(patch_set['chunks']) if patch_set['read_mode'] == 'chunks'
                       else (assignment['patch_lines'] + READ_LINES - 1) // READ_LINES)
        batch = read_batch_limit(assignment['adapter'])
        packet = context['seats'][seat]
        packet_calls = len(packet['shards'])
        segment_calls = sum(len(row['segments']) for row in packet['required_source_ranges'])
        delivered = [row for shard in packet['shards'] for row in shard['ranges']]
        delivered += packet['required_source_ranges']
        if plan_clusters is not None:
            direct_calls = len(mandatory_repository_windows(
                assignment, plan_clusters, delivered))
        elif packet.get('source_read_required'):
            direct_calls = int(bool(packet.get('omitted_source_ranges'))
                               or not packet['required_source_ranges'])
        else:
            direct_calls = 0
        patch_turns = (patch_calls + batch - 1) // batch
        segment_turns = (segment_calls + batch - 1) // batch
        direct_turns = (direct_calls + batch - 1) // batch
        projected = (patch_turns + packet_calls + segment_turns + direct_turns
                     + 1 + REPOSITORY_REFUTATION_CALL_RESERVE
                     + 1 + PROVIDER_TURN_RESERVE)
        seats[seat] = {
            'patch_proof_calls': patch_calls,
            'patch_proof_turns': patch_turns,
            'source_packet_calls': packet_calls,
            'source_packet_turns': packet_calls,
            'source_segment_calls': segment_calls,
            'source_segment_turns': segment_turns,
            'mandatory_repository_reads': direct_calls,
            'mandatory_repository_read_turns': direct_turns,
            'evidence_index_turns': 1,
            'repository_refutation_turns': REPOSITORY_REFUTATION_CALL_RESERVE,
            'final_result_turns': 1,
            'projected_turns': projected,
            'provider_turn_limit': CLAUDE_MAX_TURNS if assignment['adapter'] == 'claude' else None,
        }
    return {
        'schema_version': 1,
        'repository_expansion_call_limit': REPOSITORY_EXPANSION_CALL_LIMIT,
        'repository_refutation_call_reserve': REPOSITORY_REFUTATION_CALL_RESERVE,
        'mandatory_repository_read_limit': MANDATORY_REPOSITORY_READ_LIMIT,
        'provider_turn_reserve': PROVIDER_TURN_RESERVE,
        'seats': seats,
    }


def task_capacity_errors(capacity):
    errors = []
    for seat, row in capacity['seats'].items():
        if row['mandatory_repository_reads'] > MANDATORY_REPOSITORY_READ_LIMIT:
            errors.append('mandatory source reads exceed repository capacity: ' + seat)
        limit = row['provider_turn_limit']
        if limit is not None and row['projected_turns'] > limit:
            errors.append('task exceeds provider turn capacity: ' + seat)
    return errors


def validate_source_context_snapshot(repo, session, manifest):
    """Bind recorded source packet ranges to their exact snapshot blobs."""
    context = manifest['source_context']
    entries_by_tree = {}
    blob_lines = {}

    def expected_bytes(row):
        tree = row['blob_tree']
        # Not setdefault: its eager default ran a whole-tree ls-tree per source row.
        if tree not in entries_by_tree:
            entries_by_tree[tree] = repo.entries(tree)
        entries = entries_by_tree[tree]
        if entries.get(row['path']) != (row['blob_mode'], row['blob_oid']):
            raise ValueError('source context blob identity mismatch: ' + row['path'])
        key = (row['blob_mode'], row['blob_oid'])
        if key not in blob_lines:
            raw = repo.blob(key)
            if raw is OVERSIZED_BLOB:
                raise ValueError('source context blob is oversized: ' + row['path'])
            blob_lines[key] = split_lf_lines(raw)
        return b''.join(blob_lines[key][row['line_start'] - 1:row['line_end']])

    for seat, packet in context['seats'].items():
        for shard in packet['shards']:
            payload = read_json(session / shard['artifact'])
            for row in payload['entries']:
                if expected_bytes(row) != row['content'].encode():
                    raise ValueError('source context content does not match snapshot: ' + row['path'])
        for row in packet['omitted_source_ranges']:
            if digest(expected_bytes(row)) != row['content_sha256']:
                raise ValueError('omitted source content does not match snapshot: ' + row['path'])
        for row in packet['required_source_ranges']:
            parent = expected_bytes(row)
            source_entry = {
                key: value for key, value in row.items()
                if key not in ('required_payload_bytes',
                               'required_payload_predicted_visible_bytes', 'segments')}
            source_entry['content'] = parent.decode()
            candidate = encoded({
                'schema_version': 1, 'snapshot_tree': context['snapshot_tree'],
                'base_tree': context['base_tree'], 'seat': seat, 'shard_index': 1,
                'shard_count': 1, 'entries': [source_entry]})
            if (len(candidate) != row['required_payload_bytes']
                    or predicted_source_visible_bytes(candidate)
                    != row['required_payload_predicted_visible_bytes']):
                raise ValueError('required source payload size does not match snapshot: ' + row['path'])
            key = (row['blob_mode'], row['blob_oid'])
            canonical = partition_source_segments(
                blob_lines[key], row['line_start'], row['line_end'])
            recorded = [{key: value for key, value in segment.items() if key != 'artifact'}
                        for segment in row['segments']]
            if recorded != canonical:
                raise ValueError('required source segments are not canonical: ' + row['path'])
            rebuilt = b''
            for segment in row['segments']:
                part = expected_bytes(dict(row, line_start=segment['line_start'],
                                           line_end=segment['line_end']))
                artifact = session / segment['artifact']
                if (len(part) != segment['raw_bytes']
                        or digest(part) != segment['content_sha256']
                        or artifact.read_bytes() != part
                        or len(part) + (segment['line_end'] - segment['line_start'] + 1) \
                        * SOURCE_SEGMENT_PREFIX_RESERVE != segment['predicted_visible_bytes']):
                    raise ValueError('required source segment does not match snapshot: ' + row['path'])
                rebuilt += part
            if rebuilt != parent or digest(parent) != row['content_sha256']:
                raise ValueError('required source content does not match snapshot: ' + row['path'])


def generation_stem(manifest, generations, seat):
    """The file stem of an assignment's chosen result: a replacement runs under its own seat."""
    row = (generations or {}).get(seat)
    return f"r{row['label']}-{row['seat']}" if row else f"r{manifest['label']}-{seat}"


def finding_ownership(session, manifest, generations=None):
    found = {}
    for seat in manifest['assignments']:
        for finding in read_json(session / (generation_stem(manifest, generations, seat) + '.json'))['findings']:
            path = finding['file']
            if not within(path, manifest['scope']):
                raise ValueError('finding outside literal review scope: ' + path)
            identity = digest(encoded({'file': path, 'claim': ' '.join(finding['claim'].split())}))
            row = found.setdefault(identity, {'id': identity, 'file': path, 'claim': finding['claim'], 'owners': []})
            if seat not in row['owners']:
                row['owners'].append(seat)
    return [dict(found[key], owners=sorted(found[key]['owners'])) for key in sorted(found)]


def validate_components(session, manifest, evidence):
    selected = literal_scope(scope(session)['REV_SCOPE'], Path(scope(session)['REV_ROOT']))
    if manifest.get('scope') != selected:
        raise ValueError('manifest literal scope mismatch')
    for field in ('paths', 'semantic_paths', 'delta_paths'):
        paths = manifest.get(field)
        if not isinstance(paths, list) or any(not isinstance(p, str) or not within(p, selected) for p in paths) or paths != sorted(set(paths)):
            raise ValueError('invalid scoped path inventory: ' + field)
    prefix = 'r' + manifest['label']
    full = split_patch((session / f'{prefix}-full.patch').read_bytes(), manifest['paths'])
    semantic = split_patch((session / f'{prefix}-semantic.patch').read_bytes(), manifest['semantic_paths'])
    delta = split_patch((session / f'{prefix}-delta.patch').read_bytes(), manifest['delta_paths'])
    if not set(semantic) <= set(full) or any(full[p] != patch for p, patch in semantic.items()):
        raise ValueError('semantic patch does not match full patch')
    for field in ('symbols', 'call_sites', 'related_tests', 'gates'):
        if not isinstance(evidence.get(field), list) or any(not isinstance(r, dict) or not within(r.get('path'), selected) for r in evidence[field]):
            raise ValueError('evidence fact outside literal scope: ' + field)
    edges = evidence.get('dependencies')
    if not isinstance(edges, list) or any(not isinstance(e, dict) or not within(e.get('source'), selected)
                                         or not within(e.get('target'), selected) or not isinstance(e.get('kind'), str) for e in edges):
        raise ValueError('invalid dependency edge')
    components = manifest.get('components')
    if not isinstance(components, list) or any(not isinstance(c, dict) for c in components):
        raise ValueError('invalid dependency components')
    assigned = manifest['assignments']; owner = manifest['mechanical_owner']
    ordered = {row['seat']: assigned[row['seat']] for row in read_json(session / 'roster.json')['seats'] if row['seat'] in assigned}
    adaptive = (not manifest['fallback_reason'] and manifest['phase'] != 'repair'
                and len(assigned) > 1)
    if manifest['phase'] == 'plan':
        routed_plan = any('plan_clusters' in assignment for assignment in assigned.values())
        closure_paths = manifest.get('plan', {}).get('closure_paths', [])
        closure = split_patch((session / f'{prefix}-plan-closure.patch').read_bytes(), closure_paths)
        if (not closure or set(closure) != set(closure_paths)
                or any(path not in full or full[path] != body for path, body in closure.items())):
            raise ValueError('plan closure patch does not match full patch')
        basis = closure
        proof_assignments = ({seat: assignment['plan_clusters']
                              for seat, assignment in assigned.items()}
                             if manifest['schema_version'] == 4 else None)
        expected = plan_components_for(
            basis, edges, ordered, owner, manifest['plan']['clusters'], routed_plan,
            proof_assignments)
    else:
        verification_mode = (verification_specialist_mode(assigned, owner)
                             if adaptive and manifest['phase'] == 'verification' else None)
        basis = delta if verification_mode == 'delta' else semantic
        expected = components_for(basis, edges, ordered, owner)
    if len(components) != len(expected):
        raise ValueError('component count mismatch')
    for component, reference in zip(components, expected):
        for key in ('id', 'files', 'boundary', 'edges', 'words', 'full_state_owner'):
            if component.get(key) != reference[key]:
                raise ValueError('component structure mismatch: ' + key)
        for key in ('specialists', 'prior_owners'):
            values = component.get(key)
            if not isinstance(values, list) or any(not isinstance(s, str) or s not in assigned for s in values) or len(set(values)) != len(values):
                raise ValueError('invalid component ownership: ' + key)
        if adaptive and (not component['specialists'] or owner in component['specialists']):
            raise ValueError('semantic component lacks independent specialist')
        if manifest['phase'] != 'verification' and component['prior_owners']:
            raise ValueError('prior owners only belong to verification')
    if manifest['phase'] == 'plan':
        if components != plan_components_for(
                basis, edges, ordered, owner, manifest['plan']['clusters'], routed_plan,
                proof_assignments):
            raise ValueError('plan component routing is not canonical')
    else:
        synthetic = [{'file': c['files'][0], 'owners': c['prior_owners']} for c in components]
        if components != components_for(basis, edges, ordered, owner, synthetic):
            raise ValueError('component routing is not canonical')
    if adaptive and not components:
        raise ValueError('adaptive scope requires semantic components')
    plan_owned_paths = None
    if manifest['phase'] == 'plan' and manifest['schema_version'] == 4:
        patch_basis = (delta if manifest['plan']['delta_mode'] == 'receipt-delta'
                       else full)
        delta_assignments = {
            seat: assignment['delta_clusters'] for seat, assignment in assigned.items()}
        plan_owned_paths = plan_delta_paths(
            ordered, owner, manifest['plan']['clusters'], delta_assignments,
            edges, patch_basis)
    for seat, assignment in assigned.items():
        ids = [c['id'] for c in components if assignment['full_state'] or seat in c['specialists']]
        if assignment.get('components') != ids:
            raise ValueError('assignment component coverage mismatch')
        if not assignment['full_state']:
            if manifest['phase'] == 'plan' and manifest['schema_version'] == 4:
                paths = plan_owned_paths[seat]
                if assignment.get('delta_paths') != paths:
                    raise ValueError('plan delta path ownership mismatch')
            else:
                paths = {p for c in components if seat in c['specialists'] for p in c['files']}
            empty_plan_assignment = (manifest['phase'] == 'plan'
                                     and (manifest['schema_version'] == 4
                                          or assignment.get('plan_clusters') == []))
            expected_patch = b''.join(
                patch_basis[p] if manifest['phase'] == 'plan'
                and manifest['schema_version'] == 4 else basis[p]
                for p in sorted(paths))
            if ((not paths and not empty_plan_assignment)
                    or Path(assignment['patch']).read_bytes() != expected_patch):
                raise ValueError('specialist patch coverage mismatch: ' + seat)
    coverage_paths = instruction_coverage_paths(
        evidence, manifest['paths'], manifest.get('plan', {}).get('clusters'))
    instruction_directories_by_path = {
        directory.as_posix(): directory for directory in instruction_directories(coverage_paths)}
    instruction_paths = {
        (directory / name).as_posix()
        for directory in instruction_directories_by_path.values()
        for name in ('AGENTS.override.md', 'AGENTS.md')}
    rows = manifest.get('instructions')
    if (not isinstance(rows, list)
            or any(not isinstance(r, dict) or set(r) != {'path', 'sha256'}
                   or r.get('path') not in instruction_paths
                   or not re.fullmatch('[0-9a-f]{64}', str(r.get('sha256'))) for r in rows)
            or len({Path(row['path']).parent.as_posix() for row in rows}) != len(rows)
            or rows != sorted(rows, key=lambda row: (
                len(Path(row['path']).parent.parts), Path(row['path']).parent.as_posix()))):
        raise ValueError('invalid applicable repository instructions')


def validate_source_context(session, manifest, evidence):
    context = manifest.get('source_context')
    if evidence.get('source_context') != context or not isinstance(context, dict):
        raise ValueError('evidence/manifest mismatch: source_context')
    if set(context) != {'schema_version', 'enabled', 'snapshot_tree', 'base_tree',
                        'max_shard_bytes', 'packet_batch_limit', 'seats'}:
        raise ValueError('invalid source context structure')
    if (context['schema_version'] != 3 or type(context['enabled']) is not bool
            or context['snapshot_tree'] != manifest['snapshot_tree']
            or context['base_tree'] != manifest['base_tree']
            or context['max_shard_bytes'] != SOURCE_CONTEXT_LIMIT
            or context['packet_batch_limit'] != SOURCE_PACKET_BATCH_LIMIT
            or not isinstance(context['seats'], dict)
            or set(context['seats']) != set(manifest['assignments'])):
        raise ValueError('invalid source context identity')
    assigned = manifest['assignments']; components = manifest['components']
    component_by_id = {component['id']: component for component in components}
    owner = manifest['mechanical_owner'] if manifest['mechanical_owner'] in assigned else next(iter(assigned))
    hunk_by_path = {}
    for hunk in evidence['hunks']:
        hunk_by_path.setdefault(hunk['path'], []).append(hunk['sha256'])
    seen_ranges = {}
    binding_cache = {}
    for seat, assignment in assigned.items():
        packet = context['seats'].get(seat)
        # mandatory_source_windows is optional, so a manifest written before it existed
        # (a stored fixture, or a restored receipt) still validates.
        if not isinstance(packet, dict) or set(packet) - {'mandatory_source_windows'} != {
                'role', 'components', 'hunk_sha256', 'shards', 'omitted',
                'omitted_source_ranges', 'required_source_ranges', 'source_read_required'}:
            raise ValueError('invalid source context seat: ' + seat)
        if 'mandatory_source_windows' in packet:
            windows = packet['mandatory_source_windows']
            if not isinstance(windows, list) or len(windows) > MANDATORY_REPOSITORY_READ_LIMIT:
                raise ValueError('invalid mandatory source windows: ' + seat)
            for row in windows:
                if (not isinstance(row, dict) or set(row) != {'path', 'line_start', 'line_end'}
                        or not within(row['path'], manifest['scope'])
                        or type(row['line_start']) is not int or type(row['line_end']) is not int
                        or row['line_start'] < 1 or row['line_end'] < row['line_start']
                        or row['line_end'] - row['line_start'] + 1 > READ_LINES):
                    raise ValueError('invalid mandatory source window: ' + seat)
        expected_components = sorted(assignment['components'])
        relevant = [component for component in components if component['id'] in expected_components]
        expected_hunks = sorted({value for component in relevant for path in component['files']
                                 for value in hunk_by_path.get(path, [])})
        if (packet['role'] != ('integration' if seat == owner else 'specialist')
                or packet['components'] != expected_components or packet['hunk_sha256'] != expected_hunks):
            raise ValueError('source context assignment mismatch: ' + seat)
        omitted = packet['omitted']
        if (not isinstance(omitted, dict) or set(omitted) != set(SOURCE_CONTEXT_REASONS)
                or any(type(value) is not int or value < 0 for value in omitted.values())
                or type(packet['source_read_required']) is not bool):
            raise ValueError('invalid source context omissions: ' + seat)
        shards = packet['shards']
        if not context['enabled'] and (
                shards or packet['omitted_source_ranges'] or any(omitted.values())):
            raise ValueError('disabled source context contains packet data: ' + seat)
        limit = 3 if seat == owner or manifest['phase'] == 'plan' else 1
        if not isinstance(shards, list) or len(shards) > limit:
            raise ValueError('source context shard count exceeded: ' + seat)
        priorities = []
        for index, shard in enumerate(shards, 1):
            if not isinstance(shard, dict) or set(shard) != {
                    'artifact', 'sha256', 'bytes', 'predicted_visible_bytes', 'entries', 'ranges'}:
                raise ValueError('invalid source context shard metadata: ' + seat)
            name = f"r{manifest['label']}-{seat}-source-context-{index}.json"
            if (shard['artifact'] != name or not re.fullmatch(r'[0-9a-f]{64}', str(shard['sha256']))
                    or type(shard['bytes']) is not int or shard['bytes'] > SOURCE_CONTEXT_LIMIT
                    or type(shard['predicted_visible_bytes']) is not int
                    or shard['predicted_visible_bytes'] > SOURCE_CONTEXT_LIMIT
                    or type(shard['entries']) is not int or shard['entries'] < 1
                    or not isinstance(shard['ranges'], list)):
                raise ValueError('invalid source context shard bounds: ' + seat)
            raw = (session / name).read_bytes()
            if (len(raw) != shard['bytes'] or digest(raw) != shard['sha256']
                    or predicted_source_visible_bytes(raw) != shard['predicted_visible_bytes']):
                raise ValueError('source context shard hash mismatch: ' + name)
            payload = read_json(session / name)
            if (not isinstance(payload, dict)
                    or set(payload) != {'schema_version', 'snapshot_tree', 'base_tree', 'seat',
                                        'shard_index', 'shard_count', 'entries'}
                    or payload['schema_version'] != 1 or payload['snapshot_tree'] != manifest['snapshot_tree']
                    or payload['base_tree'] != manifest['base_tree'] or payload['seat'] != seat
                    or payload['shard_index'] != index or payload['shard_count'] != len(shards)
                    or not isinstance(payload['entries'], list) or len(payload['entries']) != shard['entries']):
                raise ValueError('invalid source context shard payload: ' + name)
            ranges = []
            for entry in payload['entries']:
                keys = {'path', 'line_start', 'line_end', 'reasons', 'component_ids', 'hunk_binding_sha256',
                        'blob_oid', 'blob_mode', 'blob_tree', 'content_sha256', 'priority', 'content'}
                if not isinstance(entry, dict) or set(entry) != keys:
                    raise ValueError('invalid source context range structure: ' + name)
                if (not within(entry['path'], manifest['scope'])
                        or type(entry['line_start']) is not int or type(entry['line_end']) is not int
                        or entry['line_start'] < 1 or entry['line_end'] < entry['line_start']
                        or type(entry['priority']) is not int or entry['priority'] < 0
                        or not isinstance(entry['content'], str)
                        or digest(entry['content'].encode()) != entry['content_sha256']
                        or len(split_lf_lines(entry['content'].encode())) != entry['line_end'] - entry['line_start'] + 1
                        or entry['blob_mode'] not in ('100644', '100755')
                        or entry['blob_tree'] not in (context['snapshot_tree'], context['base_tree'])
                        or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', str(entry['blob_oid']))):
                    raise ValueError('invalid source context range: ' + name)
                reasons = entry['reasons']; component_ids = entry['component_ids']
                binding_key = tuple(component_ids) if isinstance(component_ids, list) else None
                if (binding_key is not None and binding_key not in binding_cache
                        and set(component_ids) <= set(expected_components)):
                    binding_cache[binding_key] = hunk_binding(
                        component_ids, component_by_id, hunk_by_path)
                binding_hash = binding_cache.get(binding_key)
                if (not isinstance(reasons, list) or not reasons or len(reasons) != len(set(reasons))
                        or any(reason.split(':', 1)[0] not in SOURCE_CONTEXT_REASONS for reason in reasons)
                        or not isinstance(component_ids, list) or not component_ids
                        or component_ids != sorted(set(component_ids)) or not set(component_ids) <= set(expected_components)
                        or entry.get('hunk_binding_sha256') != binding_hash):
                    raise ValueError('invalid source context mapping: ' + name)
                priorities.append(entry['priority'])
                seen_ranges.setdefault((seat, entry['path'], entry['blob_tree']), []).append(
                    (entry['line_start'], entry['line_end']))
                ranges.append({key: value for key, value in entry.items() if key != 'content'})
            if ranges != shard['ranges']:
                raise ValueError('source context manifest range mismatch: ' + name)
        if priorities != sorted(priorities) or len(priorities) != len(set(priorities)):
            raise ValueError('source context priority order mismatch: ' + seat)
        omitted_ranges = packet['omitted_source_ranges']
        omitted_keys = {'path', 'line_start', 'line_end', 'reasons', 'component_ids',
                        'hunk_binding_sha256', 'blob_oid', 'blob_mode', 'blob_tree',
                        'content_sha256', 'priority'}
        if (not isinstance(omitted_ranges, list)
                or omitted_ranges != sorted(omitted_ranges, key=lambda row: row.get('priority', -1))):
            raise ValueError('noncanonical omitted source ranges: ' + seat)
        for row in omitted_ranges:
            component_ids = row.get('component_ids') if isinstance(row, dict) else None
            binding_key = tuple(component_ids) if isinstance(component_ids, list) else None
            if (binding_key is not None and binding_key not in binding_cache
                    and set(component_ids) <= set(expected_components)):
                binding_cache[binding_key] = hunk_binding(
                    component_ids, component_by_id, hunk_by_path)
            if (not isinstance(row, dict) or set(row) != omitted_keys
                    or not within(row.get('path'), manifest['scope'])
                    or type(row.get('line_start')) is not int
                    or type(row.get('line_end')) is not int
                    or row['line_start'] < 1 or row['line_end'] < row['line_start']
                    or type(row.get('priority')) is not int or row['priority'] < 0
                    or row.get('blob_mode') not in ('100644', '100755')
                    or row.get('blob_tree') not in (context['snapshot_tree'], context['base_tree'])
                    or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', str(row.get('blob_oid')))
                    or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('content_sha256')))
                    or not isinstance(row.get('reasons'), list) or not row['reasons']
                    or len(row['reasons']) != len(set(row['reasons']))
                    or any(reason.split(':', 1)[0] not in SOURCE_CONTEXT_REASONS
                           for reason in row['reasons'])
                    or component_ids != sorted(set(component_ids or []))
                    or not component_ids or not set(component_ids) <= set(expected_components)
                    or row.get('hunk_binding_sha256') != binding_cache.get(binding_key)):
                raise ValueError('invalid omitted source range: ' + seat)
            seen_ranges.setdefault((seat, row['path'], row['blob_tree']), []).append(
                (row['line_start'], row['line_end']))
        required = packet['required_source_ranges']
        range_keys = {'path', 'line_start', 'line_end', 'reasons', 'component_ids', 'hunk_binding_sha256',
                      'blob_oid', 'blob_mode', 'blob_tree', 'content_sha256', 'priority',
                      'required_payload_bytes', 'required_payload_predicted_visible_bytes', 'segments'}
        if (not isinstance(required, list)
                or required != sorted(required, key=lambda row: (
                    row.get('path', ''), row.get('blob_tree', ''), row.get('line_start', 0),
                    row.get('line_end', 0), row.get('priority', 0)))):
            raise ValueError('noncanonical required source ranges: ' + seat)
        for range_index, row in enumerate(required, 1):
            component_ids = row.get('component_ids')
            binding_key = tuple(component_ids) if isinstance(component_ids, list) else None
            if (binding_key is not None and binding_key not in binding_cache
                    and set(component_ids) <= set(expected_components)):
                binding_cache[binding_key] = hunk_binding(
                    component_ids, component_by_id, hunk_by_path)
            binding_hash = binding_cache.get(binding_key)
            payload_entry = {
                key: value for key, value in row.items()
                if key not in ('required_payload_bytes',
                               'required_payload_predicted_visible_bytes', 'segments')}
            payload_entry['content'] = ''
            payload_lines = patch_display_lines(encoded({
                'schema_version': 1, 'snapshot_tree': context['snapshot_tree'],
                'base_tree': context['base_tree'], 'seat': seat, 'shard_index': 1,
                'shard_count': 1, 'entries': [payload_entry]}))
            if (not isinstance(row, dict) or set(row) != range_keys
                    or not within(row.get('path'), manifest['scope'])
                    or type(row.get('line_start')) is not int or type(row.get('line_end')) is not int
                    or row['line_start'] < 1 or row['line_end'] < row['line_start']
                    or type(row.get('priority')) is not int or row['priority'] < 0
                    or row.get('blob_mode') not in ('100644', '100755')
                    or row.get('blob_tree') not in (context['snapshot_tree'], context['base_tree'])
                    or type(row.get('required_payload_bytes')) is not int
                    or row['required_payload_bytes'] < 1
                    or type(row.get('required_payload_predicted_visible_bytes')) is not int
                    or row['required_payload_predicted_visible_bytes']
                    != row['required_payload_bytes'] \
                    + payload_lines * SOURCE_SEGMENT_PREFIX_RESERVE
                    or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', str(row.get('blob_oid')))
                    or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('content_sha256')))
                    or not isinstance(row.get('reasons'), list) or not row['reasons']
                    or len(row['reasons']) != len(set(row['reasons']))
                    or any(reason.split(':', 1)[0] not in SOURCE_CONTEXT_REASONS for reason in row['reasons'])
                    or component_ids != sorted(set(component_ids or []))
                    or not component_ids or not set(component_ids) <= set(expected_components)
                    or row.get('hunk_binding_sha256') != binding_hash):
                raise ValueError('invalid required source range: ' + seat)
            segments = row['segments']
            segment_keys = {'index', 'line_start', 'line_end', 'raw_bytes',
                            'predicted_visible_bytes', 'content_sha256', 'artifact'}
            if (not isinstance(segments, list) or not segments
                    or [segment.get('index') for segment in segments] != list(range(1, len(segments) + 1))
                    or segments[0].get('line_start') != row['line_start']
                    or segments[-1].get('line_end') != row['line_end']):
                raise ValueError('invalid required source segments: ' + seat)
            cursor = row['line_start']
            for segment in segments:
                expected_name = (f"r{manifest['label']}-{seat}-source-segment-{range_index:03d}-"
                                 f"{segment.get('index', 0):03d}.txt")
                artifact = session / expected_name
                try:
                    metadata = artifact.lstat()
                    artifact_safe = (not artifact.is_symlink() and artifact.is_file()
                                     and metadata.st_nlink == 1)
                    raw = artifact.read_bytes() if artifact_safe else b''
                except OSError:
                    artifact_safe = False
                    raw = b''
                if (not isinstance(segment, dict) or set(segment) != segment_keys
                        or type(segment.get('line_start')) is not int
                        or type(segment.get('line_end')) is not int
                        or segment['line_start'] != cursor
                        or segment['line_end'] < segment['line_start']
                        or segment['line_end'] - segment['line_start'] + 1 > SOURCE_SEGMENT_LINE_LIMIT
                        or type(segment.get('raw_bytes')) is not int or segment['raw_bytes'] < 1
                        or type(segment.get('predicted_visible_bytes')) is not int
                        or segment['predicted_visible_bytes'] != segment['raw_bytes'] \
                        + (segment['line_end'] - segment['line_start'] + 1) * SOURCE_SEGMENT_PREFIX_RESERVE
                        or segment['predicted_visible_bytes'] > (
                            SOURCE_SEGMENT_SINGLE_LINE_VISIBLE_LIMIT
                            if segment['line_start'] == segment['line_end']
                            else SOURCE_SEGMENT_VISIBLE_LIMIT)
                        or not re.fullmatch(r'[0-9a-f]{64}', str(segment.get('content_sha256')))
                        or segment.get('artifact') != expected_name or not artifact_safe
                        or len(raw) != segment.get('raw_bytes')
                        or digest(raw) != segment.get('content_sha256')):
                    raise ValueError('invalid required source segment: ' + seat)
                cursor = segment['line_end'] + 1
            if cursor != row['line_end'] + 1:
                raise ValueError('incomplete required source segments: ' + seat)
            seen_ranges.setdefault((seat, row['path'], row['blob_tree']), []).append(
                (row['line_start'], row['line_end']))
        represented_omissions = [*required, *omitted_ranges]
        required_counts = Counter(
            reason.split(':', 1)[0] for row in represented_omissions for reason in row['reasons'])
        if any(required_counts[key] > omitted[key] for key in SOURCE_CONTEXT_REASONS):
            raise ValueError('source omission ranges exceed omitted identities')
        anchor_present = any(
            'declaration:changed-line-anchor' in row['reasons']
            for shard in shards for row in shard['ranges']) or any(
                'declaration:changed-line-anchor' in row['reasons'] for row in required)
        expected_read_required = (bool(expected_components) if not context['enabled']
                                  else any(omitted.values()) or anchor_present)
        if packet['source_read_required'] is not expected_read_required:
            raise ValueError('invalid source context read requirement: ' + seat)
    for ranges in seen_ranges.values():
        ordered = sorted(ranges)
        for left, right in zip(ordered, ordered[1:]):
            if right[0] <= left[1]:
                raise ValueError('overlapping source context ranges were not merged')


def validate_patch_sets(session, manifest, expected_artifacts):
    sets = manifest.get('patch_sets')
    enabled = manifest.get('patch_chunks_enabled')
    mode = manifest.get('patch_chunks_mode')
    effective = manifest.get('patch_chunks_effective_mode')
    if (not isinstance(sets, dict) or type(enabled) is not bool
            or mode not in ('auto', '0', '1') or effective not in ('auto', '0', '1')
            or enabled is not (mode != '0')
            or (mode != 'auto' and effective != mode)
            or (mode == 'auto' and effective not in ('auto', '1'))):
        raise ValueError('invalid patch set manifest structure')
    expected_ids = [f'p{index:02d}' for index in range(1, len(sets) + 1)]
    if list(sets) != expected_ids:
        raise ValueError('noncanonical patch set order')
    used = []
    identities = {}
    for seat, assignment in manifest['assignments'].items():
        set_id = assignment.get('patch_set')
        mode = assignment.get('patch_read_mode')
        if set_id not in sets or mode not in ('chunks', 'windows'):
            raise ValueError('invalid assignment patch set: ' + seat)
        patch_set = sets[set_id]
        if mode != patch_set.get('read_mode'):
            raise ValueError('assignment patch mode mismatch: ' + seat)
        if (assignment['patch_sha256'], assignment['patch_bytes'], assignment['patch_lines']) != (
                patch_set.get('patch_sha256'), patch_set.get('patch_bytes'), patch_set.get('patch_lines')):
            raise ValueError('assignment patch set identity mismatch: ' + seat)
        if assignment['patch_sha256'] in identities and identities[assignment['patch_sha256']] != set_id:
            raise ValueError('identical assigned patches use different patch sets')
        identities[assignment['patch_sha256']] = set_id
        used.append(set_id)
    if set(used) != set(sets):
        raise ValueError('unused patch set')
    for set_id, patch_set in sets.items():
        if not isinstance(patch_set, dict) or set(patch_set) != {
                'patch_sha256', 'patch_bytes', 'patch_lines', 'read_mode', 'chunks'}:
            raise ValueError('invalid patch set: ' + set_id)
        matching = next(assignment for assignment in manifest['assignments'].values()
                        if assignment['patch_set'] == set_id)
        raw = Path(matching['patch']).read_bytes()
        if (patch_set['patch_sha256'] != digest(raw)
                or type(patch_set['patch_bytes']) is not int or patch_set['patch_bytes'] != len(raw)
                or type(patch_set['patch_lines']) is not int
                or patch_set['patch_lines'] != len(split_lf_lines(raw))
                or patch_set['read_mode'] not in ('chunks', 'windows')
                or not isinstance(patch_set['chunks'], list)):
            raise ValueError('invalid patch set identity: ' + set_id)
        try:
            partitioned = partition_patch_chunks(raw) if effective != '0' else []
        except (UnicodeDecodeError, ValueError):
            partitioned = []
        expected_mode = patch_chunk_mode(raw, partitioned, effective)
        if patch_set['read_mode'] != expected_mode:
            raise ValueError('invalid patch set mode: ' + set_id)
        if expected_mode == 'windows':
            if patch_set['chunks']:
                raise ValueError('window patch set contains chunks: ' + set_id)
            continue
        if len(patch_set['chunks']) != len(partitioned):
            raise ValueError('patch chunk count mismatch: ' + set_id)
        reconstructed = []
        for index, (row, expected) in enumerate(zip(patch_set['chunks'], partitioned), 1):
            if not isinstance(row, dict) or set(row) != {
                    'artifact', 'index', 'byte_start', 'byte_end', 'bytes', 'display_lines',
                    'predicted_visible_bytes', 'starts_mid_line', 'ends_mid_line', 'sha256'}:
                raise ValueError('invalid patch chunk metadata: ' + set_id)
            content = expected.pop('content')
            name = f"r{manifest['label']}-patch-{set_id}-{index:03d}.txt"
            artifact = session / name
            try:
                metadata = artifact.lstat()
            except OSError as error:
                raise ValueError('missing patch chunk artifact: ' + name) from error
            if (row.get('artifact') != name or row != {'artifact': name, **expected}
                    or not stat.S_ISREG(metadata.st_mode) or artifact.is_symlink()
                    or metadata.st_nlink != 1 or artifact.read_bytes() != content
                    or row['bytes'] > PATCH_CHUNK_RAW_LIMIT
                    or row['display_lines'] > PATCH_CHUNK_LINE_LIMIT
                    or row['predicted_visible_bytes'] > PATCH_CHUNK_VISIBLE_LIMIT):
                raise ValueError('invalid patch chunk artifact: ' + name)
            expected_artifacts.add(name)
            reconstructed.append(content)
        if b''.join(reconstructed) != raw:
            raise ValueError('patch chunks do not reconstruct assigned patch: ' + set_id)


def validate_plan(session, manifest, evidence, check_source, replay_searches=True):
    plan = manifest.get('plan')
    if (manifest['schema_version'] not in (3, 4)
            or evidence.get('plan') != plan or not isinstance(plan, dict)):
        raise ValueError('invalid plan manifest binding')
    plan_keys = {'source', 'source_sha256', 'artifact', 'sha256', 'bytes', 'clusters',
                 'closure_paths'}
    if manifest['schema_version'] == 4:
        plan_keys |= {'routing_version', 'delta_mode', 'delta_reason', 'common_artifacts'}
    if set(plan) != plan_keys:
        raise ValueError('invalid plan manifest structure')
    if manifest['schema_version'] == 4:
        common = [f"r{manifest['label']}-evidence.md"]
        if (plan['routing_version'] != 1
                or plan['delta_mode'] not in ('receipt-delta', 'cumulative-closure')
                or plan['common_artifacts'] != common
                or (plan['delta_mode'] == 'receipt-delta' and plan['delta_reason'] is not None)
                or (plan['delta_mode'] == 'cumulative-closure'
                    and (not isinstance(plan['delta_reason'], str) or not plan['delta_reason']))):
            raise ValueError('invalid receipt-relative plan routing')
    artifact_name = f"r{manifest['label']}-plan.md"
    source = Path(plan['source'])
    try:
        source.relative_to(session)
    except (TypeError, ValueError):
        raise ValueError('plan source is outside the session')
    artifact = session / artifact_name
    artifact_metadata = artifact.lstat(); raw = artifact.read_bytes()
    if (plan['artifact'] != artifact_name or plan['source_sha256'] != plan['sha256']
            or not re.fullmatch(r'[0-9a-f]{64}', str(plan['sha256']))
            or type(plan['bytes']) is not int or plan['bytes'] != len(raw)
            or plan['sha256'] != digest(raw) or artifact.is_symlink()
            or not stat.S_ISREG(artifact_metadata.st_mode) or artifact_metadata.st_nlink != 1):
        raise ValueError('plan snapshot identity mismatch')
    clusters = plan['clusters']
    if not isinstance(clusters, list) or not clusters:
        raise ValueError('invalid plan clusters')
    ids = []
    for cluster in clusters:
        base_keys = {'id', 'search_pattern', 'search_contract', 'paths', 'excluded'}
        if (not isinstance(cluster, dict) or set(cluster) not in (
                base_keys, base_keys | {'search_proof'})
                or not isinstance(cluster['id'], str) or not re.fullmatch(r'C-[A-Za-z0-9][A-Za-z0-9-]*', cluster['id'])
                or not isinstance(cluster['search_pattern'], str) or not cluster['search_pattern']
                or not isinstance(cluster['excluded'], list)
                or any(not isinstance(path, str) or not path for path in cluster['excluded'])
                or cluster['excluded'] != sorted(set(cluster['excluded']))
                or not isinstance(cluster['search_contract'], dict)
                or set(cluster['search_contract']) != {'engine', 'domain', 'pattern'}
                or cluster['search_contract'].get('engine') not in ('rg', 'grep-bre')
                or cluster['search_contract'].get('domain') != {
                    'rg': 'rg-complete-worktree',
                    'grep-bre': 'grep-complete-worktree',
                }.get(cluster['search_contract'].get('engine'))
                or cluster['search_contract'].get('pattern') != cluster['search_pattern']
                or not isinstance(cluster['paths'], list) or not cluster['paths']):
            raise ValueError('invalid plan cluster structure')
        ids.append(cluster['id'])
        proof = cluster.get('search_proof')
        if proof is not None:
            name = f"r{manifest['label']}-plan-search-{cluster['id']}.txt"
            artifact = session / name
            try:
                metadata = artifact.lstat()
                body = artifact.read_bytes()
            except OSError as error:
                raise ValueError('missing plan search artifact: ' + name) from error
            if (not isinstance(proof, dict) or set(proof) != {
                    'artifact', 'status', 'saturated', 'bytes', 'sha256', 'paths'}
                    or proof.get('artifact') != name
                    or proof.get('status') not in (0, 1)
                    or proof.get('saturated') is not False
                    or type(proof.get('bytes')) is not int or proof['bytes'] != len(body)
                    or proof.get('sha256') != digest(body)
                    or proof.get('paths') != plan_search_paths(body)
                    or artifact.is_symlink() or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1):
                raise ValueError('invalid plan search proof: ' + cluster['id'])
        for row in cluster['paths']:
            if isinstance(row, dict):
                try:
                    validate_plan_range(row.get('line_start'), row.get('line_end'))
                except ValueError as error:
                    raise ValueError('invalid plan cluster path') from error
            if (not isinstance(row, dict) or set(row) != {
                    'path', 'line_start', 'line_end', 'token', 'resolution', 'field'}
                    or not within(row.get('path'), manifest['scope'])
                    or row.get('resolution') not in ('direct', 'basename')
                    or row.get('field') not in ('sites', 'test', 'tests', 'regression')
                    or not isinstance(row.get('token'), str) or not row['token']):
                raise ValueError('invalid plan cluster path')
        if proof is not None:
            sites = {row['path'] for row in cluster['paths'] if row['field'] == 'sites'}
            if not sites <= set(proof['paths']):
                raise ValueError('plan search proof omits a named site: ' + cluster['id'])
            # Re-checked here because the replay that would catch it is skipped on the
            # render and verify-panel paths.
            declared = {row['path'] for row in cluster['paths']}
            if reconcile_plan_sites(declared, cluster['excluded'], proof['paths']):
                raise ValueError('plan search proof leaves a site unreconciled: ' + cluster['id'])
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate plan cluster identifier')
    if any('search_proof' in cluster for cluster in clusters) \
            and not all('search_proof' in cluster for cluster in clusters):
        raise ValueError('mixed prepared and legacy plan searches')
    assignments = manifest['assignments']
    roster_order = [row['seat'] for row in read_json(session / 'roster.json')['seats']
                    if row.get('seat') in assignments]
    ordered_assignments = {seat: assignments[seat] for seat in roster_order}
    if any('plan_clusters' in assignment for assignment in assignments.values()):
        if manifest['schema_version'] == 4:
            expected_assignments, expected_delta = split_plan_cluster_assignments(
                ordered_assignments, manifest['mechanical_owner'], clusters)
        else:
            expected_assignments = plan_cluster_assignments(
                ordered_assignments, manifest['mechanical_owner'], clusters)
            expected_delta = None
        for seat, assignment in assignments.items():
            if assignment.get('plan_clusters') != expected_assignments[seat]:
                raise ValueError('invalid plan cluster assignment: ' + seat)
            if (expected_delta is not None
                    and assignment.get('delta_clusters') != expected_delta[seat]):
                raise ValueError('invalid plan delta ownership: ' + seat)
            if (manifest['schema_version'] == 4 and seat != manifest['mechanical_owner']
                    and not assignment['plan_clusters']):
                raise ValueError('plan specialist lacks a proof cluster: ' + seat)
        if manifest['schema_version'] == 4:
            clusters_by_id = {cluster['id']: cluster for cluster in clusters}
            for seat, assignment in assignments.items():
                required = {Path(assignment['patch']).name}
                required.update(chunk['artifact'] for chunk in
                                manifest['patch_sets'][assignment['patch_set']]['chunks'])
                source_packet = manifest['source_context']['seats'][seat]
                required.update(shard['artifact'] for shard in source_packet['shards'])
                required.update(segment['artifact']
                                for source_range in source_packet['required_source_ranges']
                                for segment in source_range['segments'])
                if assignment.get('required_artifacts') != sorted(required):
                    raise ValueError('invalid plan assignment artifact set: ' + seat)
        if len(assignments) > 1 and all('search_proof' in cluster for cluster in clusters):
            clusters_by_id = {cluster['id']: cluster for cluster in clusters}
            prepared_bytes = sum(
                clusters_by_id[cluster_id]['search_proof']['bytes']
                for assignment in assignments.values()
                for cluster_id in assignment['plan_clusters'])
            if (sum(assignment['patch_bytes'] for assignment in assignments.values())
                    + prepared_bytes
                    > len((session / f"r{manifest['label']}-full.patch").read_bytes())
                    * len(assignments) * 9 // 10):
                raise ValueError('routed plan inputs save less than 10 percent')
    closure_paths = plan['closure_paths']
    if (not isinstance(closure_paths, list) or closure_paths != sorted(set(closure_paths))
            or not closure_paths or any(path not in manifest['paths'] for path in closure_paths)):
        raise ValueError('invalid plan closure paths')
    if check_source:
        try:
            metadata = source.lstat()
        except OSError as error:
            raise ValueError('plan source unavailable') from error
        source_raw = source.read_bytes()
        if (source.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or source_raw != raw or digest(source_raw) != plan['source_sha256']):
            raise ValueError('plan source changed after prepare')
        repo = Repository(session)
        base_entries = repo.entries(manifest['base_tree'])
        snapshot_entries = repo.entries(manifest['snapshot_tree'])
        entry_map = dict(base_entries); entry_map.update(snapshot_entries)
        entries = set(entry_map)
        reject_plan_artifact_collision(entries, manifest['label'])
        parsed = parse_plan(raw, entries)
        if parsed != [
                {key: value for key, value in cluster.items() if key != 'search_proof'}
                for cluster in clusters]:
            raise ValueError('plan cluster parse changed')
        for cluster in parsed:
            for row in cluster['paths']:
                try:
                    validate_plan_source_location(repo, entry_map, row)
                except ValueError as error:
                    raise plan_field_refusal(cluster['id'], row['field'], error) from None
        if replay_searches and all('search_proof' in cluster for cluster in clusters):
            expected_clusters, expected_artifacts = prepare_plan_searches(
                repo, manifest['snapshot_tree'], parsed, f"r{manifest['label']}",
                manifest['base_tree'])
            if expected_clusters != clusters or any(
                    (session / name).read_bytes() != body
                    for name, body in expected_artifacts.items()):
                raise ValueError('plan search proof changed')
        expected_closure = plan_closure_paths(clusters, evidence['dependencies'], manifest['paths'])
        if expected_closure != closure_paths:
            raise ValueError('plan closure dependency mismatch')
    # The prompt renders these windows verbatim as read instructions and the audit enforces
    # the obligation they close, so a stale or trimmed list fails here rather than after a
    # whole plan panel has run.
    for seat, packet in manifest['source_context']['seats'].items():
        if 'mandatory_source_windows' not in packet:
            continue
        delivered = packet['required_source_ranges'] + [
            dict(row) for shard in packet['shards'] for row in shard['ranges']]
        if packet['mandatory_source_windows'] != published_mandatory_windows(
                manifest['assignments'][seat], clusters, delivered):
            raise ValueError('mandatory source windows do not close the plan: ' + seat)


def validated_manifest(path, fresh=True, seen=None, offline=False, replay_plan_searches=True):
    """Validate local evidence; offline mode never accesses Git or predecessor results."""
    try:
        return _validated_manifest(path, fresh, seen, offline, replay_plan_searches)
    except (OSError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as error:
        raise ValueError('invalid manifest: ' + str(error)) from error


def _validated_manifest(path, fresh, seen, offline, replay_plan_searches):
    path = Path(path).resolve(); raw = path.read_bytes(); manifest = read_json(path)
    session = path.parent
    seen = set() if seen is None else set(seen)
    if str(path) in seen:
        raise ValueError('cyclic coverage predecessor')
    seen.add(str(path))
    if not isinstance(manifest, dict):
        raise ValueError('manifest must be an object')
    for field in ('source', 'assignments', 'artifacts', 'inputs', 'word_counts', 'mechanical', 'source_context'):
        if not isinstance(manifest.get(field), dict):
            raise ValueError('invalid manifest object: ' + field)
    for field in ('snapshot_unsafe', 'delta_unsafe'):
        if not isinstance(manifest.get(field), list) or any(not isinstance(s, str) for s in manifest[field]):
            raise ValueError('invalid manifest list: ' + field)
    for field in ('label', 'phase', 'session', 'snapshot_tree', 'base_tree'):
        if not isinstance(manifest.get(field), str):
            raise ValueError('invalid manifest string: ' + field)
    if manifest.get('fallback_reason') is not None and (not isinstance(manifest['fallback_reason'], str) or not manifest['fallback_reason']):
        raise ValueError('invalid fallback reason')
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] not in (2, 3, 4) or manifest['session'] != str(session):
        raise ValueError('invalid manifest session/version')
    if any(not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', manifest[key]) for key in ('snapshot_tree', 'base_tree')):
        raise ValueError('invalid manifest tree identifier')
    if not SAFE_NAME.fullmatch(manifest['label']) or path.name != f"r{manifest['label']}-evidence.manifest.json":
        raise ValueError('invalid manifest label')
    if manifest['phase'] not in ('discovery', 'risk', 'verification', 'repair', 'plan'):
        raise ValueError('invalid manifest phase')
    if (manifest['phase'] == 'plan') != (manifest['schema_version'] in (3, 4)):
        raise ValueError('manifest phase/version mismatch')
    expected = {f"r{manifest['label']}-{suffix}" for suffix in
                ('full.patch', 'semantic.patch', 'delta.patch', 'evidence.json', 'evidence.md', 'instructions.md')}
    if manifest['phase'] == 'plan':
        expected.update((f"r{manifest['label']}-plan.md", f"r{manifest['label']}-plan-closure.patch"))
        expected.update(cluster['search_proof']['artifact'] for cluster in manifest['plan']['clusters']
                        if 'search_proof' in cluster)
    source = manifest['source']
    if source not in ({'mode': 'worktree'},) and not (source.get('mode') == 'ref' and isinstance(source.get('ref'), str) and source['ref']):
        raise ValueError('invalid snapshot source')
    assigned = manifest['assignments']
    if not assigned:
        raise ValueError('missing assignments')
    for seat, assignment in assigned.items():
        if not isinstance(assignment, dict) or not isinstance(assignment.get('bundle'), str) or not assignment['bundle']:
            raise ValueError('invalid assignment structure')
        mode = assignment['scope']
        if not SAFE_NAME.fullmatch(seat) or mode not in ('full', 'semantic', 'delta', 'closure'):
            raise ValueError('invalid assignment')
        suffix = ('full' if mode == 'full' else
                  'plan-closure' if mode == 'closure' and 'plan_clusters' not in assignment else seat)
        expected_path = str(session / f"r{manifest['label']}-{suffix}.patch")
        expected.add(Path(expected_path).name)
        if assignment['patch'] != expected_path or assignment['full_state'] is not (mode == 'full'):
            raise ValueError('assignment patch/full-state mismatch')
        patch = (session / Path(expected_path).name).read_bytes()
        if (assignment.get('patch_sha256') != digest(patch)
                or type(assignment.get('patch_bytes')) is not int or assignment['patch_bytes'] != len(patch)
                or type(assignment.get('patch_lines')) is not int
                or assignment['patch_lines'] != len(split_lf_lines(patch))):
            raise ValueError('assignment patch identity mismatch')
        if assignment.get('bundles') != assignment['bundle'].split('+') or len(set(assignment['bundles'])) != len(assignment['bundles']):
            raise ValueError('assignment bundle list mismatch')
    for packet in manifest['source_context'].get('seats', {}).values():
        for shard in packet.get('shards', []):
            expected.add(shard['artifact'])
        for required in packet.get('required_source_ranges', []):
            for segment in required.get('segments', []):
                expected.add(segment['artifact'])
    validate_patch_sets(session, manifest, expected)
    contract_binding = contract_binding_from_inputs(session, manifest['inputs'])
    expected_inputs = set(STANDARD_INPUTS)
    if contract_binding is not None:
        expected_inputs.add(contract_binding[0])
    if set(manifest['artifacts']) != expected or set(manifest['inputs']) != expected_inputs:
        raise ValueError('invalid manifest artifact set')
    roster = read_json(session / 'roster.json')
    if not isinstance(roster, dict) or not isinstance(roster.get('seats'), list) or any(not isinstance(s, dict) for s in roster['seats']):
        raise ValueError('invalid roster shape')
    if fresh and not offline and provider_contract_input(session) != contract_binding:
        raise ValueError('provider contract input changed after prepare')
    core = {s['seat'] for s in roster['seats'] if not s.get('extra')}
    core_order = [s['seat'] for s in roster['seats'] if not s.get('extra')]
    bundles_by_seat = {seat: assignment['bundle'] for seat, assignment in assigned.items()}
    if not set(assigned) <= core or (
            manifest['phase'] != 'repair' and set(assigned) != core
            and not (manifest['phase'] == 'plan' and single_seat_plan(bundles_by_seat))):
        raise ValueError('assignment roster mismatch')
    adapters = {s['seat']: s.get('adapter', '') for s in roster['seats']}
    if any(a.get('adapter') != adapters[s] for s, a in assigned.items()):
        raise ValueError('assignment adapter mismatch')
    # unenforced_seats decides whose read audit is skipped, so it is DERIVED here and compared,
    # never taken on the manifest's word. Declared and untyped, a hand-edited list could name a
    # CLI seat, or be a bare string whose `in` test degrades to a substring match.
    view = manifest.get('dependency_view')
    if 'dependency_view' in manifest and (
            not isinstance(view, dict) or set(view) != {'path', 'crates'}
            or view['path'] != str(session / 'deps') or not isinstance(view['crates'], list)
            or any(not isinstance(crate, str) or not CRATE_NAME.fullmatch(crate)
                   for crate in view['crates'])
            or view['crates'] != sorted(set(view['crates']))):
        raise ValueError('invalid dependency view')
    expected_unenforced = sorted(seat for seat in assigned if adapters[seat] == 'agent')
    declared_unenforced = manifest.get('unenforced_seats', [])
    if (not isinstance(declared_unenforced, list)
            or any(not isinstance(x, str) for x in declared_unenforced)
            or declared_unenforced != expected_unenforced):
        raise ValueError('unenforced_seats does not match the roster')
    validate_assignment_topology({seat: assigned[seat]['bundle'] for seat in core_order if seat in assigned},
                                 [seat for seat in core_order if seat in assigned], manifest['phase'])
    for name, meta in manifest['artifacts'].items():
        if not isinstance(meta, dict):
            raise ValueError('invalid artifact metadata')
        if Path(name).name != name or digest((session / name).read_bytes()) != meta['sha256']:
            raise ValueError('evidence artifact hash mismatch: ' + name)
        if type(meta.get('words')) is not int or meta['words'] != len((session / name).read_bytes().split()):
            raise ValueError('evidence artifact word count mismatch: ' + name)
    for name, actual in input_hashes(
            session, contract_binding[0] if contract_binding is not None else None).items():
        if actual != manifest['inputs'][name]:
            raise ValueError('evidence input changed: ' + name)
    evidence = read_json(session / f"r{manifest['label']}-evidence.json")
    if not isinstance(evidence, dict):
        raise ValueError('evidence must be an object')
    for field in ('assignments', 'mechanical_owner', 'mechanical', 'phase', 'snapshot_tree',
                  'base_tree', 'fallback_reason', 'predecessor', 'delta_unsafe', 'components',
                  'scope', 'paths', 'semantic_paths', 'delta_paths', 'instructions'):
        if field not in manifest or evidence.get(field) != manifest[field]:
            raise ValueError('evidence/manifest mismatch: ' + field)
    binding = manifest.get('parent_assignment')
    if evidence.get('parent_assignment') != binding:
        raise ValueError('evidence/manifest mismatch: parent_assignment')
    if binding is not None:
        keys = {'manifest', 'manifest_sha256', 'seat', 'snapshot_tree', 'roster_sha256',
                'assignment_sha256', 'bundle', 'adapter', 'model', 'effort',
                'patch_chunks_mode', 'source_context_enabled'}
        if (manifest['phase'] != 'repair' or not isinstance(binding, dict) or set(binding) != keys
                or not isinstance(binding.get('manifest'), str)
                or Path(binding['manifest']).name != binding['manifest']
                or not SAFE_NAME.fullmatch(str(binding.get('seat', '')))):
            raise ValueError('invalid parent assignment binding')
        parent, parent_hash = validated_manifest(
            session / binding['manifest'], fresh=fresh, seen=seen, offline=offline,
            replay_plan_searches=False)
        seat = binding['seat']
        if parent['phase'] == 'repair' or seat not in parent['assignments']:
            raise ValueError('invalid parent assignment binding')
        parent_assignment = parent['assignments'][seat]
        roster_seat = next((row for row in roster['seats'] if row.get('seat') == seat), None)
        expected_binding = {
            'manifest': f"r{parent['label']}-evidence.manifest.json",
            'manifest_sha256': parent_hash,
            'seat': seat,
            'snapshot_tree': parent['snapshot_tree'],
            'roster_sha256': parent['inputs']['roster.json'],
            'assignment_sha256': digest(encoded(parent_assignment)),
            'bundle': parent_assignment['bundle'],
            'adapter': parent_assignment['adapter'],
            'model': roster_seat.get('model') if roster_seat else None,
            'effort': roster_seat.get('effort') if roster_seat else None,
            'patch_chunks_mode': parent['patch_chunks_mode'],
            'source_context_enabled': parent['source_context']['enabled'],
        }
        executor, child_assignment = next(iter(assigned.items()))
        if (binding != expected_binding or len(assigned) != 1 or executor == seat
                or child_assignment['adapter'] == 'agent'
                or manifest['label'] != parent['label'] + 'x'
                or child_assignment['scope'] != 'full'
                or child_assignment['bundle'] != parent_assignment['bundle']
                or manifest['snapshot_tree'] != parent['snapshot_tree']
                or manifest['base_tree'] != parent['base_tree']
                or manifest['source'] != parent['source']
                or manifest['inputs']['roster.json'] != parent['inputs']['roster.json']
                or manifest['patch_chunks_mode'] != parent['patch_chunks_mode']
                or manifest['source_context']['enabled'] is not parent['source_context']['enabled']):
            raise ValueError('repair child does not match its parent assignment')
    elif manifest['phase'] != 'repair' and 'parent_assignment' in manifest:
        raise ValueError('parent assignment belongs only to repair evidence')
    phase = manifest['phase']; owner = manifest['mechanical_owner']; fallback = manifest['fallback_reason']
    bundles = [a['bundle'] for a in assigned.values()]
    regression = [s for s in adapters if s in assigned and BUNDLES[-1] in assigned[s]['bundles']]
    if phase == 'discovery' and any(b != 'simplicity' for b in bundles):
        raise ValueError('invalid discovery bundle')
    if phase in ('risk', 'verification') and bundle_coverage({s: a['bundle'] for s, a in assigned.items()}):
        if owner != regression[0]:
            raise ValueError('full owner must own regression bundle')
    elif phase in ('risk', 'verification') and not fallback:
        raise ValueError('missing bundle assignment')
    if phase == 'repair' and len(assigned) != 1:
        raise ValueError('repair must have one full-state seat')
    if phase == 'plan':
        completeness = [s for s in adapters if s in assigned and PLAN_BUNDLES[0] in assigned[s]['bundles']]
        if (fallback or completeness != [owner] or not (
                bundle_coverage(bundles_by_seat, PLAN_BUNDLES) or single_seat_plan(bundles_by_seat))):
            raise ValueError('invalid plan assignment coverage')
        specialist_scope = ('closure' if manifest['schema_version'] == 3 else
                            'delta' if manifest['plan']['delta_mode'] == 'receipt-delta'
                            else 'closure')
        if any(a['scope'] != ('full' if seat == owner else specialist_scope)
               for seat, a in assigned.items()):
            raise ValueError('plan panel scope mismatch')
    elif fallback or phase == 'repair':
        if any(a['scope'] != 'full' for a in assigned.values()):
            raise ValueError('fallback and repair require all-full scope')
    else:
        if owner not in assigned:
            raise ValueError('missing full-state owner')
        other = verification_specialist_mode(assigned, owner) if phase == 'verification' else 'semantic'
        if any(a['scope'] != ('full' if s == owner else other) for s, a in assigned.items()):
            raise ValueError('phase-inconsistent scope assignment')
    if manifest['snapshot_unsafe'] and not fallback:
        raise ValueError('unsafe snapshot requires full fallback')
    prefix = 'r' + manifest['label']
    words = {kind: len((session / f'{prefix}-{kind}.patch').read_bytes().split()) for kind in ('full', 'semantic', 'delta')}
    words['evidence'] = sum(len((session / f'{prefix}-{name}.md').read_bytes().split()) for name in ('evidence', 'instructions'))
    words['source_context'] = sum(
        len((session / artifact).read_bytes().split())
        for packet in manifest['source_context']['seats'].values()
        for artifact in ([shard['artifact'] for shard in packet['shards']]
                         + [segment['artifact'] for required in packet['required_source_ranges']
                            for segment in required['segments']]))
    words['assigned_patch'] = sum(len(Path(a['patch']).read_bytes().split()) for a in assigned.values())
    if phase == 'plan':
        words['plan'] = len((session / f'{prefix}-plan.md').read_bytes().split())
        words['closure'] = len((session / f'{prefix}-plan-closure.patch').read_bytes().split())
        if (all('search_proof' in cluster for cluster in manifest['plan']['clusters'])
                and all('plan_clusters' in assignment for assignment in assigned.values())):
            clusters_by_id = {cluster['id']: cluster for cluster in manifest['plan']['clusters']}
            words['prepared_search'] = sum(
                len((session / clusters_by_id[cluster_id]['search_proof']['artifact']).read_bytes().split())
                for assignment in assigned.values()
                for cluster_id in assignment['plan_clusters'])
    words['avoided'] = max(0, len(assigned) * words['full'] - words['assigned_patch']
                           - len(assigned) * words['evidence'] - words['source_context']
                           - words.get('prepared_search', 0))
    if manifest['word_counts'] != words or any(type(n) is not int for n in manifest['word_counts'].values()):
        raise ValueError('manifest word counts mismatch')
    validate_components(session, manifest, evidence)
    validate_source_context(session, manifest, evidence)
    verification_mode = (verification_specialist_mode(assigned, owner)
                         if phase == 'verification' and not fallback else None)
    if verification_mode == 'delta':
        if not isinstance(manifest['predecessor'], dict):
            raise ValueError('delta verification requires an explicit predecessor')
        reference = manifest['predecessor']
        if (set(reference) != {'receipt', 'sha256'} or not isinstance(reference.get('receipt'), str)
                or Path(reference['receipt']).name != reference['receipt']
                or not re.fullmatch(r'[0-9a-f]{64}', str(reference.get('sha256')))):
            raise ValueError('invalid delta predecessor reference')
        delta = (session / f'{prefix}-delta.patch').read_bytes()
        if manifest['delta_unsafe'] or not delta or words['delta'] + words['evidence'] >= words['semantic']:
            raise ValueError('delta is unsafe, incomplete, empty, or not smaller')
        if not offline:
            repo = Repository(session)
            prior = prior_coverage(session, repo, manifest['base_tree'], manifest['predecessor'], seen)
            previous = prior['coverage']
            if prior['status'] != 'valid' or previous['snapshot_tree'] == manifest['snapshot_tree']:
                raise ValueError('invalid delta predecessor: ' + str(prior['reason']))
            changes, _, categories, unsafe = repo.changes(previous['snapshot_tree'], manifest['snapshot_tree'])
            actual = b''.join(patch for name, patch in changes if categories[name] == 'semantic')
            if unsafe or delta != actual:
                raise ValueError('delta is unsafe or incomplete')
            chosen = {row['seat']: assigned[row['seat']] for row in roster['seats'] if row['seat'] in assigned}
            basis = {name: patch for name, patch in changes if categories[name] == 'semantic'}
            if manifest['components'] != components_for(basis, evidence['dependencies'], chosen, owner, previous.get('findings')):
                raise ValueError('component ownership does not match predecessor findings')
    elif phase == 'plan' and manifest['schema_version'] == 4:
        reference = manifest['predecessor']
        receipt_mode = manifest['plan']['delta_mode'] == 'receipt-delta'
        if receipt_mode and not isinstance(reference, dict):
            raise ValueError('receipt-relative plan requires an explicit predecessor')
        if reference is not None:
            if (not isinstance(reference, dict) or set(reference) != {'receipt', 'sha256'}
                    or not isinstance(reference.get('receipt'), str)
                    or Path(reference['receipt']).name != reference['receipt']
                    or not re.fullmatch(r'[0-9a-f]{64}', str(reference.get('sha256')))):
                raise ValueError('invalid plan predecessor reference')
            if not offline:
                repo = Repository(session)
                prior = prior_coverage(
                    session, repo, manifest['base_tree'], reference, seen)
                previous = prior['coverage']
                if prior['status'] != 'valid':
                    raise ValueError('invalid plan predecessor: ' + str(prior['reason']))
                changes, _, categories, unsafe = repo.changes(
                    previous['snapshot_tree'], manifest['snapshot_tree'])
                actual = b''.join(patch for name, patch in changes
                                  if categories[name] == 'semantic')
                if actual != (session / f'{prefix}-delta.patch').read_bytes():
                    raise ValueError('plan predecessor delta changed')
                if receipt_mode and unsafe:
                    raise ValueError('receipt-relative plan delta is unsafe or opaque')
                if not receipt_mode and not unsafe:
                    raise ValueError('cumulative plan routing does not match its predecessor')
        elif receipt_mode:
            raise ValueError('receipt-relative plan predecessor is missing')
    elif manifest['predecessor'] is not None:
        raise ValueError('predecessor only belongs to delta verification or schema-4 plan evidence')
    if phase == 'plan':
        validate_plan(session, manifest, evidence, fresh and not offline, replay_plan_searches)
    expected_capacity = compile_task_capacity(
        assigned, manifest['patch_sets'], manifest['source_context'],
        manifest['plan']['clusters'] if phase == 'plan' else None)
    if manifest.get('task_capacity') != expected_capacity:
        raise ValueError('invalid task capacity contract')
    capacity_failures = task_capacity_errors(expected_capacity)
    if capacity_failures:
        raise ValueError(capacity_failures[0])
    if fresh and not offline:
        repo = Repository(session)
        current, unsafe = repo.snapshot(manifest['source'].get('ref'))
        if current != manifest['snapshot_tree'] or unsafe != manifest['snapshot_unsafe']:
            raise ValueError('snapshot changed after prepare')
        if repo.tree(repo.scope['REV_BASE']) != manifest['base_tree']:
            raise ValueError('manifest base does not match pinned review base')
        patches, hunks, categories, _ = repo.changes(manifest['base_tree'], current)
        if (b''.join(p for _, p in patches) != (session / f'{prefix}-full.patch').read_bytes()
                or sorted(categories) != manifest['paths'] or hunks != evidence.get('hunks')
                or sorted(p for p in categories if categories[p] == 'semantic') != manifest['semantic_paths']):
            raise ValueError('cumulative patch does not cover the actual snapshot')
        rows, packet = instructions(
            repo, current,
            instruction_coverage_paths(
                evidence, categories, manifest.get('plan', {}).get('clusters')),
            manifest['source']['mode'] == 'worktree')
        if rows != manifest['instructions'] or packet != (session / f'{prefix}-instructions.md').read_bytes():
            raise ValueError('repository instruction coverage mismatch')
        validate_source_context_snapshot(repo, session, manifest)
    return manifest, digest(raw)


def validate_panel_coverage(manifest):
    if manifest['snapshot_unsafe']:
        raise ValueError('unsupported snapshot cannot establish complete coverage')
    if not any(a['full_state'] for a in manifest['assignments'].values()):
        raise ValueError('missing full-state coverage')
    phase = manifest['phase']
    bundles = [a['bundle'] for a in manifest['assignments'].values()]
    if phase == 'repair':
        raise ValueError('standalone repair cannot certify parent panel coverage')
    chosen = {s: a['bundle'] for s, a in manifest['assignments'].items()}
    if phase == 'plan' and not (bundle_coverage(chosen, PLAN_BUNDLES) or single_seat_plan(chosen)):
        raise ValueError('plan validation requires all four plan lenses or one plan-completeness seat')
    if phase not in ('discovery', 'plan') and not bundle_coverage(chosen):
        raise ValueError('coverage requires all four bundles')


def audit_gate(manifest, manifest_hash, phase, seat, stem, assignment, prompt, result,
               result_data, audit_path):
    """Run the receipt's read-audit gate for one seat, raising on the first failure.

    Lifted out of validate_results unchanged so an UNENFORCED seat can run the same gate
    without it deciding the receipt. A second, parallel implementation would drift, and a
    would-have-passed verdict produced by a different gate would measure nothing.
    """
    component_by_id = {component['id']: component for component in manifest['components']}
    stream = Path(str(stem) + '.stream.ndjson')
    audit = read_json(audit_path)
    narrow = assignment['scope'] != 'full'
    zero_tool_plan = (phase == 'plan' and assignment.get('plan_clusters') == []
                      and assignment['patch_bytes'] == 0)
    advisories = audit.get('advisories', []) if isinstance(audit, dict) else None
    if (not isinstance(audit, dict) or type(audit.get('schema_version')) is not int or audit['schema_version'] != 2
            or audit.get('status') != 'valid' or audit.get('narrow') is not narrow
            or audit.get('adapter') != assignment['adapter'] or audit.get('violations') != []
            or not isinstance(advisories, list)
            or any(not isinstance(item, dict) or set(item) != {'code', 'tool'}
                   or not isinstance(item.get('code'), str) or not item['code']
                   or not isinstance(item.get('tool'), str) or not item['tool']
                   for item in advisories)
            or audit.get('prompt_sha256') != digest(prompt.read_bytes())
            or audit.get('stream_sha256') != digest(stream.read_bytes())
            or audit.get('result_sha256') != digest(result.read_bytes())
            or audit.get('evidence_manifest_sha256') != manifest_hash):
        raise ValueError('invalid or stale read audit: ' + seat)
    if (any(type(audit.get(key)) is not int or audit[key] < 0 for key in
            ('tool_calls', 'tool_turns', 'tool_output_bytes', 'max_tool_output_bytes',
             'recognized_tool_calls', 'source_read_calls', 'packet_shards', 'packet_bytes',
                 'packet_ranges', 'opened_source_ranges', 'finding_citations',
                 'assigned_patch_bytes', 'assigned_patch_lines', 'assigned_patch_reads',
                 'required_source_ranges_covered'))
            or (audit['recognized_tool_calls'] < 1 and not zero_tool_plan)
            or audit['recognized_tool_calls'] > audit['tool_calls']
            or audit['max_tool_output_bytes'] > audit['tool_output_bytes']
            or audit['packet_bytes'] > audit['tool_output_bytes']
            or (assignment['patch_bytes'] > 0 and audit['assigned_patch_reads'] < 1)
            or (assignment['patch_bytes'] == 0 and audit['assigned_patch_reads'] != 0)
            or audit['assigned_patch_reads'] > audit['tool_calls']
            or audit.get('assigned_patch_sha256') != assignment['patch_sha256']
            or audit['assigned_patch_bytes'] != assignment['patch_bytes']
            or audit['assigned_patch_lines'] != assignment['patch_lines']
            or audit['assigned_patch_bytes'] > audit['tool_output_bytes']):
        raise ValueError('invalid read audit counters: ' + seat)
    patch_counter_fields = (
        'patch_proof_calls', 'patch_proof_turns', 'patch_proof_visible_bytes',
        'expected_patch_chunks', 'opened_patch_chunks')
    if (any(type(audit.get(key)) is not int or audit[key] < 0
            for key in patch_counter_fields)
            or audit.get('patch_proof_mode') != assignment['patch_read_mode']
            or audit['patch_proof_calls'] != audit['assigned_patch_reads']
            or audit['patch_proof_turns'] > audit['patch_proof_calls']
            or audit['patch_proof_visible_bytes'] > audit['tool_output_bytes']):
        raise ValueError('invalid patch proof counters: ' + seat)
    patch_ranges = audit.get('assigned_patch_ranges')
    if (not isinstance(patch_ranges, list)
            or any(not isinstance(row, dict) or set(row) != {'line_start', 'line_end'}
                   or type(row.get('line_start')) is not int or type(row.get('line_end')) is not int
                   or row['line_start'] < 1 or row['line_end'] < row['line_start']
                   or row['line_end'] - row['line_start'] + 1 > 240
                   or row['line_end'] > assignment['patch_lines'] for row in patch_ranges)
            or patch_ranges != sorted(patch_ranges, key=lambda row: (row['line_start'], row['line_end']))
            or len({(row['line_start'], row['line_end']) for row in patch_ranges}) != len(patch_ranges)):
        raise ValueError('invalid assigned patch audit ranges: ' + seat)
    if assignment['patch_read_mode'] == 'chunks':
        expected_chunks = len(manifest['patch_sets'][assignment['patch_set']]['chunks'])
        if (patch_ranges or audit['expected_patch_chunks'] != expected_chunks
                or audit['opened_patch_chunks'] != expected_chunks
                or audit['patch_proof_calls'] != expected_chunks):
            raise ValueError('assigned patch chunk audit is incomplete: ' + seat)
    else:
        cursor = 1
        for row in patch_ranges:
            if row['line_start'] > cursor:
                raise ValueError('assigned patch audit has an uncovered line gap: ' + seat)
            cursor = max(cursor, row['line_end'] + 1)
        if cursor != assignment['patch_lines'] + 1 or audit['assigned_patch_reads'] < len(patch_ranges):
            raise ValueError('assigned patch audit is incomplete: ' + seat)
    ranges = audit.get('source_ranges')
    if (not isinstance(ranges, list) or any(not isinstance(row, dict) or set(row) != {
            'path', 'line_start', 'line_end', 'origin'} or not within(row.get('path'), manifest['scope'])
            or type(row.get('line_start')) is not int or type(row.get('line_end')) is not int
            or row['line_start'] < 1 or row['line_end'] < row['line_start']
            or (row.get('origin') == 'tool' and row['line_end'] - row['line_start'] + 1 > 240)
            or row.get('origin') not in ('packet', 'tool') for row in ranges)):
        raise ValueError('invalid read audit source ranges: ' + seat)
    canonical = sorted(ranges, key=lambda row: (row['path'], row['line_start'], row['line_end'], row['origin']))
    identities = {(row['path'], row['line_start'], row['line_end'], row['origin']) for row in ranges}
    if ranges != canonical or len(identities) != len(ranges):
        raise ValueError('noncanonical read audit source ranges: ' + seat)
    packet_ranges = [row for row in ranges if row['origin'] == 'packet']
    tool_ranges = [row for row in ranges if row['origin'] == 'tool']
    opened = []
    packet_keys = {(row['path'], row['line_start'], row['line_end']) for row in packet_ranges}
    for shard in manifest['source_context']['seats'][seat]['shards']:
        shard_keys = {(row['path'], row['line_start'], row['line_end']) for row in shard['ranges']}
        if shard_keys and shard_keys <= packet_keys:
            opened.append(shard)
    expected_packet_keys = {(row['path'], row['line_start'], row['line_end'])
                            for shard in opened for row in shard['ranges']}
    if packet_keys != expected_packet_keys:
        raise ValueError('read audit packet ranges do not match complete assigned shards: ' + seat)
    context = manifest['source_context']['seats'][seat]
    if len(opened) != len(context['shards']):
        raise ValueError('read audit did not open every assigned source context shard: ' + seat)
    required_covered = 0
    required_intersected = False
    for required in context['required_source_ranges']:
        cursor = required['line_start']
        for row in tool_ranges:
            if (row['path'] == required['path']
                    and row['line_start'] <= required['line_end']
                    and required['line_start'] <= row['line_end']):
                required_intersected = True
            if row['path'] != required['path'] or row['line_end'] < cursor:
                continue
            if row['line_start'] > cursor:
                break
            cursor = max(cursor, row['line_end'] + 1)
            if cursor > required['line_end']:
                break
        required_covered += cursor > required['line_end']
    proof_keys = {'path', 'line_start', 'line_end', 'blob_tree', 'blob_oid', 'content_sha256'}
    proofs = audit.get('required_source_range_proofs')
    if (not isinstance(proofs, list)
            or any(not isinstance(row, dict) or set(row) != proof_keys
                   or not within(row.get('path'), manifest['scope'])
                   or type(row.get('line_start')) is not int or type(row.get('line_end')) is not int
                   or row['line_start'] < 1 or row['line_end'] < row['line_start']
                   or row.get('blob_tree') not in (manifest['snapshot_tree'], manifest['base_tree'])
                   or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', str(row.get('blob_oid')))
                   or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('content_sha256')))
                   for row in proofs)):
        raise ValueError('invalid required source range proofs: ' + seat)
    proof_order = lambda row: (row['path'], row['line_start'], row['line_end'], row['blob_tree'],
                               row['blob_oid'], row['content_sha256'])
    if proofs != sorted(proofs, key=proof_order) or len({proof_order(row) for row in proofs}) != len(proofs):
        raise ValueError('noncanonical required source range proofs: ' + seat)
    expected_proofs = sorted(({
        key: row[key] for key in proof_keys
    } for row in context['required_source_ranges']), key=proof_order)
    if any(proof not in expected_proofs for proof in proofs):
        raise ValueError('required source range proof identity mismatch: ' + seat)
    plan_name = f"r{manifest['label']}-plan.md" if phase == 'plan' else None
    source_findings = [finding for finding in result_data['findings']
                       if finding['file'] != plan_name]
    cited = sum(any(row['path'] == finding['file']
                    and row['line_start'] <= finding['line_end']
                    and finding['line_start'] <= row['line_end'] for row in ranges)
                for finding in source_findings)
    boundary_paths = {path for component_id in context['components']
                      for path in component_by_id[component_id]['boundary']}
    boundary_intersected = any(row['path'] in boundary_paths for row in tool_ranges)
    omitted_intersected = any(
        row['path'] == omitted['path']
        and row['line_start'] <= omitted['line_end']
        and omitted['line_start'] <= row['line_end']
        for row in tool_ranges for omitted in context['omitted_source_ranges'])
    if (audit['packet_shards'] != len(opened)
            or audit['packet_bytes'] != sum(shard['bytes'] for shard in opened)
            or audit['packet_ranges'] != len(packet_ranges)
            or audit['opened_source_ranges'] != len(tool_ranges)
            or bool(tool_ranges) != bool(audit['source_read_calls'])
            or (context['source_read_required']
                and (audit['source_read_calls'] < 1
                     or (not omitted_intersected if context['omitted_source_ranges']
                         else not (boundary_intersected or required_intersected))
                     or (context['required_source_ranges'] and context['role'] == 'specialist'
                         and not required_intersected)))
            or audit['required_source_ranges_covered'] != required_covered
            or audit['required_source_ranges_covered'] != len(proofs)
            or (context['role'] == 'integration'
                and (required_covered != len(context['required_source_ranges'])
                     or proofs != expected_proofs))
            or audit['finding_citations'] != cited
            or cited != len(source_findings)):
        raise ValueError('read audit evidence coverage mismatch: ' + seat)
    if phase == 'plan':
        search_proofs = audit.get('plan_cluster_search_proofs')
        source_proofs = audit.get('plan_cluster_source_proofs')
        assigned_cluster_ids = set(assignment.get(
            'plan_clusters', [cluster['id'] for cluster in manifest['plan']['clusters']]))
        clusters = [cluster for cluster in manifest['plan']['clusters']
                    if cluster['id'] in assigned_cluster_ids]
        expected_searches = [(cluster['id'], cluster['search_contract']) for cluster in clusters]
        actual_searches = [(row.get('cluster'), row.get('search_contract')) for row in search_proofs or []
                           if isinstance(row, dict)]
        expected_sources = [(cluster['id'], row['path'], row['line_start'], row['line_end'])
                            for cluster in clusters for row in cluster['paths']]
        actual_sources = [(row.get('cluster'), row.get('path'),
                           row.get('line_start'), row.get('line_end'))
                          for row in source_proofs or [] if isinstance(row, dict)]
        expected_plan_citations = [
            {'line_start': finding['line_start'], 'line_end': finding['line_end']}
            for finding in result_data['findings'] if finding['file'] == plan_name]
        def plan_range_covered(proof):
            if proof['line_start'] is None:
                return bool(proof['ranges'])
            cursor = proof['line_start']
            for source_range in sorted(proof['ranges'], key=lambda value: (
                    value['line_start'], value['line_end'])):
                if source_range['line_end'] < cursor:
                    continue
                if source_range['line_start'] > cursor:
                    return False
                cursor = max(cursor, source_range['line_end'] + 1)
                if cursor > proof['line_end']:
                    return True
            return cursor > proof['line_end']
        if (audit.get('plan_sha256') != manifest['plan']['sha256']
                or audit.get('plan_artifact_sha256') != manifest['plan']['sha256']
                or audit.get('plan_citation_ranges') != expected_plan_citations
                or audit.get('plan_finding_citations') != len(expected_plan_citations)
                or cited + len(expected_plan_citations) != len(result_data['findings'])
                or actual_searches != expected_searches
                or not all(set(row) == {
                    'cluster', 'search_contract', 'call_id', 'output_sha256'}
                           and isinstance(row['call_id'], str) and row['call_id']
                           and re.fullmatch(r'[0-9a-f]{64}', str(row['output_sha256']))
                           for row in search_proofs or [])
                or any(cluster.get('search_proof') is not None and (
                    row.get('call_id') != 'prepared:' + cluster['search_proof']['artifact']
                    or row.get('output_sha256') != cluster['search_proof']['sha256'])
                       for cluster, row in zip(clusters, search_proofs or []))
                or actual_sources != expected_sources
                or not all(set(row) == {
                    'cluster', 'path', 'line_start', 'line_end', 'ranges'}
                           and isinstance(row['ranges'], list) and row['ranges']
                           and all(source_range in ranges for source_range in row['ranges'])
                           and all(source_range['path'] == row['path']
                                   for source_range in row['ranges'])
                           and plan_range_covered(row)
                           for row in source_proofs or [])):
            raise ValueError('read audit plan proof mismatch: ' + seat)
    elif (audit.get('plan_artifact_sha256') is not None
          or audit.get('plan_citation_ranges') not in (None, [])
          or audit.get('plan_finding_citations') not in (None, 0)):
        raise ValueError('non-plan audit contains plan citation coverage: ' + seat)


UNENFORCED_AUDIT_SUFFIX = '.unenforced-audit.json'
# Both receipt-path children are short-lived, take every input as an argument, and now run per
# selected seat on every verify-panel, receipt and predecessor walk. Inheriting this process's
# stdin is what lets one block forever, and neither bounds its own work on a pathological input,
# so each gets a closed stdin and a deadline far above any real run.
CHILD_TIMEOUT_SECONDS = 300


def unenforced_verdict(session, manifest, manifest_hash, phase, seat, stem, assignment,
                       prompt, result, result_data):
    """Audit an unenforced seat's transcript and report whether it WOULD have passed the gate.

    Nothing here gates: every path returns a verdict, including the ones where the auditor
    cannot run. Whether an Agent transcript can clear the gate is unmeasured, and gating on an
    unmeasured pass rate would trade one blanket refusal for another; recording it is how that
    rate gets measured.

    The audit lands on a name that neither rev-attempt.py's hard-failure scan
    (`r*-*.read-audit.json`, `r*-*.audit.json`) nor rev-profile.py's metric scan globs. An
    invalid advisory audit under either name would stop the session or move a measurement,
    which is gating by another route.
    """
    stream = Path(str(stem) + '.stream.ndjson')
    audit_path = Path(str(stem) + UNENFORCED_AUDIT_SUFFIX)
    verdict = {'audit': audit_path.name, 'audit_sha256': None, 'status': None,
               'would_pass': False, 'reason': None}
    if not stream.is_file():
        verdict['reason'] = 'no transcript'
        return verdict
    command = [sys.executable, str(Path(__file__).parent / 'lib' / 'review-read-audit.py'),
               'audit', '--adapter', assignment['adapter'], '--raw', str(stream),
               '--prompt', str(prompt), '--root', scope(session)['REV_ROOT'],
               '--session', str(session), '--out', str(audit_path),
               # --out is not the enforced name, so the result cannot be inferred from it.
               '--result', str(result)]
    deps = os.environ.get('REV_DEPS_DIR') or (manifest.get('dependency_view') or {}).get('path')
    if deps:
        command += ['--deps', deps]
    try:
        completed = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                                   timeout=CHILD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        verdict['reason'] = f'read audit did not run: timed out after {CHILD_TIMEOUT_SECONDS}s'
        return verdict
    except OSError as error:
        verdict['reason'] = 'read audit did not run: ' + str(error)
        return verdict
    if not audit_path.is_file():
        verdict['reason'] = 'read audit did not run: exit ' + str(completed.returncode)
        return verdict
    verdict['audit_sha256'] = digest(audit_path.read_bytes())
    try:
        audit = read_json(audit_path)
        if isinstance(audit, dict) and isinstance(audit.get('status'), str):
            verdict['status'] = audit['status']
        audit_gate(manifest, manifest_hash, phase, seat, stem, assignment, prompt, result,
                   result_data, audit_path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError,
            RecursionError) as error:
        verdict['reason'] = str(error)
    else:
        verdict['would_pass'] = True
    return verdict


def validate_results(session, manifest, manifest_hash, seats=None, verdicts=None):
    result_hashes = {}
    component_by_id = {component['id']: component for component in manifest['components']}
    if seats is None:
        validate_panel_coverage(manifest)
        selected = list(manifest['assignments'])
    else:
        selected = list(seats)
        if (not selected or len(set(selected)) != len(selected)
                or any(seat not in manifest['assignments'] for seat in selected)):
            raise ValueError('invalid result generation selection')
    phase = manifest['phase']
    validator = Path(__file__).parent / 'lib' / 'validate-findings.py'
    for seat in selected:
        stem = session / f"r{manifest['label']}-{seat}"
        result = Path(str(stem) + '.json'); exit_path = Path(str(stem) + '.exit')
        prompt = Path(str(stem) + '.prompt.md')
        if exit_path.read_text().strip() != '0':
            raise ValueError('seat failed: ' + seat)
        token = 'Evidence manifest SHA-256: ' + manifest_hash
        if token not in prompt.read_text().splitlines():
            raise ValueError('prompt manifest hash mismatch: ' + seat)
        try:
            valid = subprocess.run([sys.executable, str(validator), str(result)],
                                   capture_output=True, stdin=subprocess.DEVNULL,
                                   timeout=CHILD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            # main() does not catch SubprocessError, so an uncaught one would surface as a
            # traceback rather than a refusal.
            raise ValueError('result validation timed out: ' + seat) from None
        if valid.returncode:
            raise ValueError('invalid result: ' + seat)
        result_data = read_json(result)
        assignment = manifest['assignments'][seat]
        # An agent seat produces no read audit by construction (Claude Code subagents ignore the
        # hook frontmatter the enforced transcript depends on). Its result, exit status and
        # prompt-hash binding are still checked above; only the audit is skipped, and the manifest
        # records the seat as unenforced so no caller can read this panel as certified.
        if seat in manifest.get('unenforced_seats', []):
            if assignment['adapter'] != 'agent':
                raise ValueError('unenforced seat is not an agent adapter: ' + seat)
            # Everything that DOES exist is HASHED into the receipt. That is not a binding: of
            # these four, only the prompt is tied to this manifest, by the manifest-hash line
            # checked above. The result, exit and transcript are recorded and never compared to
            # this panel, so one filed under the wrong seat or round is not detected. The enforced
            # path gets that binding from the read audit, which names manifest, prompt, stream and
            # result in one record; an unenforced seat has no such record.
            for artifact in (result, exit_path, prompt):
                result_hashes[artifact.name] = digest(artifact.read_bytes())
            agent_stream = Path(str(stem) + '.stream.ndjson')
            if agent_stream.exists():
                result_hashes[agent_stream.name] = digest(agent_stream.read_bytes())
            verdict = unenforced_verdict(session, manifest, manifest_hash, phase, seat, stem,
                                         assignment, prompt, result, result_data)
            if verdicts is not None:
                verdicts[seat] = verdict
            continue
        audit_path = Path(str(stem) + '.read-audit.json')
        stream = Path(str(stem) + '.stream.ndjson')
        audit_gate(manifest, manifest_hash, phase, seat, stem, assignment, prompt, result,
                   result_data, audit_path)
        for artifact in (audit_path, stream):
            result_hashes[artifact.name] = digest(artifact.read_bytes())
        for artifact in (result, exit_path, prompt):
            result_hashes[artifact.name] = digest(artifact.read_bytes())
    return result_hashes


def result_generation(session, manifest, manifest_hash, seat):
    verdicts = {}
    hashes = validate_results(session, manifest, manifest_hash, [seat], verdicts)
    stem = f"r{manifest['label']}-{seat}"
    roster = read_json(session / 'roster.json')
    roster_seat = next(row for row in roster['seats'] if row.get('seat') == seat)
    assignment = manifest['assignments'][seat]
    row = {
        'label': manifest['label'],
        'seat': seat,
        'manifest': f"r{manifest['label']}-evidence.manifest.json",
        'manifest_sha256': manifest_hash,
        'snapshot_tree': manifest['snapshot_tree'],
        'roster_sha256': manifest['inputs']['roster.json'],
        'assignment_sha256': digest(encoded(assignment)),
        'bundle': assignment['bundle'],
        'adapter': assignment['adapter'],
        'model': roster_seat.get('model'),
        'effort': roster_seat.get('effort'),
        'prompt_sha256': hashes[stem + '.prompt.md'],
        'stream_sha256': hashes.get(stem + '.stream.ndjson'),
        'result_sha256': hashes[stem + '.json'],
        'audit_sha256': hashes.get(stem + '.read-audit.json'),
        'enforced': seat not in manifest.get('unenforced_seats', []),
        'exit_sha256': hashes[stem + '.exit'],
    }
    # Only an unenforced seat carries one, so an all-CLI generation row is byte-identical to the
    # rows this receipt format already published.
    if seat in verdicts:
        row['unenforced_audit'] = verdicts[seat]
    return hashes, row


def verification_specialist_mode(assignments, owner):
    modes = {assignment['scope'] for seat, assignment in assignments.items() if seat != owner}
    if len(modes) != 1 or not modes <= {'semantic', 'delta'}:
        raise ValueError('verification specialists must use one authenticated scope')
    return modes.pop()


def prior_coverage(session, repo, base_tree, reference=None, seen=None):
    try:
        if reference is None:
            head_path = session / 'coverage-head.json'
            try:
                metadata = head_path.lstat()
            except FileNotFoundError:
                return {'status': 'absent', 'coverage': None, 'reason': None}
            if (stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1):
                raise ValueError('invalid coverage head')
            head = read_json(head_path)
        else:
            head = reference
        if not isinstance(head, dict) or set(head) != {'receipt', 'sha256'} or not isinstance(head['receipt'], str):
            raise ValueError('invalid coverage reference')
        name = head['receipt']
        if Path(name).name != name:
            raise ValueError('invalid receipt name')
        raw = (session / name).read_bytes()
        if digest(raw) != head['sha256']:
            raise ValueError('receipt hash mismatch')
        receipt = json.loads(raw)
        if not isinstance(receipt, dict) or not isinstance(receipt.get('manifest'), str) or Path(receipt['manifest']).name != receipt['manifest']:
            raise ValueError('invalid receipt manifest')
        manifest, mh = validated_manifest(session / receipt['manifest'], fresh=False, seen=seen)
        if receipt['manifest_sha256'] != mh or receipt['snapshot_tree'] != manifest['snapshot_tree'] or manifest['base_tree'] != base_tree:
            raise ValueError('receipt snapshot/base mismatch')
        if receipt.get('schema_version') == 2:
            replacements = receipt.get('replacements')
            generations = receipt.get('selected_generations')
            if (not isinstance(replacements, dict) or not isinstance(generations, dict)
                    or any(not isinstance(seat, str) or not isinstance(label, str)
                           for seat, label in replacements.items())):
                raise ValueError('invalid composite receipt')
            values = [seat + '=' + label for seat, label in sorted(replacements.items())]
            selected_manifest, selected_hash, results, selected, canonical = verify_panel_selection(
                session, manifest['label'], values, fresh=False, seen=seen)
            if (selected_manifest != manifest or selected_hash != mh or results != receipt.get('results')
                    or selected != generations or canonical != replacements):
                raise ValueError('composite receipt generations changed')
        else:
            if validate_results(session, manifest, mh) != receipt['results']:
                raise ValueError('receipt results changed')
            selected = None
        ownership = finding_ownership(session, manifest, selected)
        if receipt.get('findings') != ownership:
            receipt['findings'] = []
            receipt['ownership_fallback_reason'] = 'missing or invalid prior finding ownership'
        repo.tree(receipt['snapshot_tree'])
        return {'status': 'valid', 'coverage': dict(receipt, coverage_reference=head), 'reason': None}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as error:
        return {'status': 'invalid', 'coverage': None,
                'reason': 'invalid coverage predecessor: ' + str(error)}


def current_coverage_head(session):
    path = session / 'coverage-head.json'
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if (stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1 or not metadata.st_mode & 0o444):
        raise ValueError('invalid coverage head')
    try:
        head = read_json(path)
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise ValueError('invalid coverage head') from error
    if (not isinstance(head, dict) or set(head) != {'receipt', 'sha256'}
            or not isinstance(head.get('receipt'), str)
            or Path(head['receipt']).name != head['receipt']
            or not re.fullmatch(r'[0-9a-f]{64}', str(head.get('sha256')))):
        raise ValueError('invalid coverage head')
    return head


CRATE_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*')


def locked_registry_crates(raw):
    """`<name>-<version>` for every Cargo.lock [[package]] carrying a registry checksum."""
    crates = set()
    for block in re.split(r'^\[\[package\]\][ \t]*$', raw.decode('utf-8', 'replace'), flags=re.M)[1:]:
        fields = dict(re.findall(r'^(name|version|checksum) = "([^"\n]*)"', block, re.M))
        if fields.get('checksum') and all(CRATE_NAME.fullmatch(fields.get(key, ''))
                                          for key in ('name', 'version')):
            crates.add(fields['name'] + '-' + fields['version'])
    return sorted(crates)


def dependency_view(repo, session, snapshot):
    """Link each crate the snapshot's Cargo.lock pins into $S/deps; None without a lockfile.

    A user-supplied REV_DEPS_DIR is the dependency root instead, so no view is built."""
    if os.environ.get('REV_DEPS_DIR'):
        return None
    entry = repo.entries(snapshot).get('Cargo.lock')
    if entry is None or entry[0] not in ('100644', '100755'):
        return None
    home = Path(os.environ.get('CARGO_HOME') or Path.home() / '.cargo')
    registry = home / 'registry' / 'src'
    indexes = sorted(path for path in registry.iterdir() if path.is_dir()) if registry.is_dir() else []
    wanted = {}
    for crate in locked_registry_crates(repo.git('cat-file', 'blob', entry[1])):
        source = next((index / crate for index in indexes if (index / crate).is_dir()), None)
        if source is not None:
            wanted[crate] = str(source)
    view = session / 'deps'
    if view.is_symlink() or (view.exists() and not view.is_dir()):
        raise ValueError('dependency view must be a session directory')
    view.mkdir(mode=0o700, exist_ok=True)
    for child in view.iterdir():
        if not child.is_symlink():
            raise ValueError('unexpected dependency view entry: ' + child.name)
        if os.readlink(child) != wanted.get(child.name):
            child.unlink()
    for crate, source in wanted.items():
        if not (view / crate).is_symlink():
            os.symlink(source, view / crate)
    return {'path': str(view), 'crates': sorted(wanted)}


def attempt_module():
    spec = importlib.util.spec_from_file_location(
        'rev_attempt', Path(__file__).resolve().parent / 'lib' / 'rev-attempt.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(args):
    session = Path(args.session).resolve()
    with session_input_lock(session):
        validate_standard_inputs(session, require_all=True)
        return _prepare_locked(args, session)


def _prepare_locked(args, session):
    repo = Repository(session)
    roster = read_json(session / 'roster.json')
    validate_live_roster_adapters(roster)
    parent_assignment = None
    parent_manifest = None
    parent_manifest_hash = None
    parent_value = getattr(args, 'parent_assignment', None)
    if parent_value is not None:
        parent_label, separator, parent_seat = parent_value.partition(':')
        if (not parent_value or args.phase != 'repair' or not separator
                or not SAFE_NAME.fullmatch(parent_label)
                or not SAFE_NAME.fullmatch(parent_seat) or parent_label == args.label):
            raise ValueError('invalid parent assignment')
        parent_manifest, parent_manifest_hash = validated_manifest(
            session / f'r{parent_label}-evidence.manifest.json')
        if parent_manifest['phase'] == 'plan':
            raise ValueError('plan parent assignments require whole-panel recovery')
        if parent_manifest['phase'] == 'repair' or parent_seat not in parent_manifest['assignments']:
            raise ValueError('invalid parent assignment')
        if args.label != parent_label + 'x':
            raise ValueError('replacement label must be ' + parent_label + 'x')
    chunk_mode, source_context_enabled = evidence_modes(os.environ, parent_manifest)
    source_head = args.head
    if parent_manifest is not None:
        parent_source = parent_manifest['source']
        parent_head = parent_source.get('ref') if parent_source['mode'] == 'ref' else None
        if args.head is not None and args.head != parent_head:
            raise ValueError('explicit source selector conflicts with parent assignment')
        source_head = parent_head
    if args.phase == 'plan':
        if not getattr(args, 'plan', None) or not getattr(args, 'plan_sha256', None):
            raise ValueError('plan phase requires --plan and --plan-sha256')
        plan_input = Path(args.plan)
        try:
            plan_input_metadata = plan_input.lstat()
        except OSError as error:
            raise ValueError('plan source is unavailable') from error
        plan_source = plan_input.resolve(strict=True)
        if (stat.S_ISLNK(plan_input_metadata.st_mode) or plan_input_metadata.st_nlink != 1
                or plan_source.parent != session
                or plan_source.is_symlink() or not plan_source.is_file()
                or not re.fullmatch(r'[0-9a-f]{64}', args.plan_sha256)):
            raise ValueError('plan source must be a regular session file with an exact SHA-256')
        plan_raw = plan_source.read_bytes()
        if digest(plan_raw) != args.plan_sha256:
            raise ValueError('stale plan hash')
    else:
        if getattr(args, 'plan', None) or getattr(args, 'plan_sha256', None):
            raise ValueError('--plan belongs only to the plan phase')
        plan_source = None; plan_raw = None
    chosen, owner = assignments(args, roster)
    # An agent seat cannot produce an enforced read transcript, so a panel that includes one cannot
    # be CERTIFIED. That is not a reason to refuse the panel: the value of evidence mode is its
    # structure - bounded assignments, hash-bound patch and source packets, per-cluster closure
    # obligations on a plan - and that structure works on an agent seat. The panel runs and the seat
    # is recorded unenforced, so nothing downstream can mistake it for a certified gate.
    # This covers CODE panels as well as plan panels. The host used to skip preparation for a whole
    # code panel holding an agent row, and since Claude rows resolve to `agent` on every host that
    # does not seat the Claude CLI, that skip meant no code panel ever ran in evidence mode. The
    # seat's audit is not gated on, because the agent pass rate is unmeasured and gating on an
    # unmeasured pass rate would trade one blanket refusal for another.
    unenforced_seats = sorted(row['seat'] for row in roster['seats']
                              if row.get('adapter') == 'agent' and row.get('seat') in chosen)
    if parent_manifest is not None:
        parent = parent_manifest['assignments'][parent_seat]
        executor = next(iter(chosen)) if len(chosen) == 1 else None
        if executor == parent_seat:
            raise ValueError('replacement executor must differ from the parent seat')
        if executor is None or chosen[executor] != parent['bundle']:
            raise ValueError('repair assignment does not match its parent')
        executor_row = next((row for row in roster['seats'] if row.get('seat') == executor), None)
        if executor_row is None or executor_row.get('adapter') == 'agent':
            # An Agent result cannot be bound against copying, so it cannot stand in for another seat.
            raise ValueError('replacement executor must be an enforced seat')
        if not attempt_module().terminal_failure(session, parent_label, parent_seat,
                                                 session / f'r{parent_label}-{parent_seat}.prompt.md'):
            raise ValueError('parent assignment has no recorded terminal failure')
        existing = session / f'r{args.label}-evidence.manifest.json'
        if existing.exists():
            prior = read_json(existing)
            if ((prior.get('parent_assignment') or {}).get('seat') != parent_seat
                    or list(prior.get('assignments') or {}) != [executor]):
                raise ValueError('panel already has a replacement')
        roster_seat = next((row for row in roster['seats'] if row.get('seat') == parent_seat), None)
        if roster_seat is None:
            raise ValueError('parent assignment seat is absent from roster')
        parent_assignment = {
            'manifest': f'r{parent_label}-evidence.manifest.json',
            'manifest_sha256': parent_manifest_hash,
            'seat': parent_seat,
            'snapshot_tree': parent_manifest['snapshot_tree'],
            'roster_sha256': parent_manifest['inputs']['roster.json'],
            'assignment_sha256': digest(encoded(parent)),
            'bundle': parent['bundle'],
            'adapter': parent['adapter'],
            'model': roster_seat.get('model'),
            'effort': roster_seat.get('effort'),
            'patch_chunks_mode': chunk_mode,
            'source_context_enabled': source_context_enabled,
        }
    contract_input = provider_contract_input(session)
    inputs = input_hashes(session, contract_input[0] if contract_input else None)
    for name in ('files.txt', 'untracked.txt'):
        if inputs[name] is not None:
            for path in (session / name).read_text().splitlines():
                if path and not repo.scoped(path):
                    raise ValueError('inventory path outside literal scope: ' + path)
    base_tree = repo.tree(repo.scope['REV_BASE'])
    source = {'mode': 'ref', 'ref': source_head} if source_head else {'mode': 'worktree'}
    unknown_ref = False
    try:
        snapshot, snapshot_unsafe = repo.snapshot(source_head)
    except ValueError:
        if not source_head:
            raise
        snapshot, snapshot_unsafe = repo.snapshot()
        source = {'mode': 'worktree'}
        unknown_ref = True
    patches, hunks, categories, opaque = repo.changes(base_tree, snapshot)
    data = facts(repo, snapshot, hunks, categories, base_tree)
    deps_view = dependency_view(repo, session, snapshot)
    plan_clusters = None
    if args.phase == 'plan':
        snapshot_entries = repo.entries(snapshot); base_entries = repo.entries(base_tree)
        plan_entry_map = dict(base_entries); plan_entry_map.update(snapshot_entries)
        reject_plan_artifact_collision(plan_entry_map, args.label)
        plan_clusters = parse_plan(plan_raw, set(plan_entry_map))
        for cluster in plan_clusters:
            for row in cluster['paths']:
                try:
                    if not repo.scoped(row['path']):
                        raise ValueError(f'path is outside literal scope "{row["path"]}"')
                    validate_plan_source_location(repo, plan_entry_map, row)
                except ValueError as error:
                    raise plan_field_refusal(cluster['id'], row['field'], error) from None
        if snapshot_unsafe:
            raise ValueError('unsupported snapshot cannot support receipt-relative plan evidence')
    data['instructions'], instruction_packet = instructions(
        repo, snapshot, instruction_coverage_paths(data, categories, plan_clusters),
        source['mode'] == 'worktree')
    data.update(hunks=hunks, mechanical={p: c for p, c in categories.items() if c != 'semantic'},
                mechanical_owner=owner)
    prefix = f'r{args.label}'
    plan_search_artifacts = {}
    if args.phase == 'plan':
        plan_clusters, plan_search_artifacts = prepare_plan_searches(
            repo, snapshot, plan_clusters, prefix, base_tree)
    full = b''.join(patch for _, patch in patches)
    semantic = b''.join(patch for path, patch in patches if categories[path] == 'semantic')
    packet = markdown(data, session / (prefix + '-evidence.json'))
    prior = (prior_coverage(session, repo, base_tree) if args.phase in ('verification', 'plan')
             else {'status': 'absent', 'coverage': None, 'reason': None})
    previous = prior['coverage']
    fallback = prior['reason']
    delta = b''; delta_unsafe = []; delta_categories = {}; changes = []
    if previous and args.phase in ('verification', 'plan'):
        changes, _, delta_categories, delta_unsafe = repo.changes(previous['snapshot_tree'], snapshot)
        delta = b''.join(patch for path, patch in changes if delta_categories[path] == 'semantic')
    use_delta = False
    if args.phase == 'verification':
        if not bundle_coverage(chosen) or owner is None:
            fallback = 'missing bundle or full-state assignment'
        elif prior['status'] == 'invalid':
            fallback = prior['reason']
        elif not previous:
            pass
        elif previous['snapshot_tree'] == snapshot:
            pass
        elif snapshot_unsafe or delta_unsafe:
            fallback = 'unsafe or opaque delta'
        elif not delta:
            pass
        elif len(delta.split()) + len(packet.split()) + len(instruction_packet.split()) >= len(semantic.split()):
            pass
        else:
            fallback = None; use_delta = True
    elif args.phase != 'plan':
        fallback = None
    if args.phase == 'risk' and (not bundle_coverage(chosen) or owner is None):
        fallback = 'missing bundle or full-state assignment'
    if snapshot_unsafe:
        fallback = 'snapshot contains unsupported files'; use_delta = False
    if unknown_ref:
        fallback = 'unknown reviewed ref; full current worktree required'; use_delta = False
    plan_delta_mode = None
    plan_delta_reason = None
    if args.phase == 'plan':
        if prior['status'] != 'valid':
            plan_delta_mode = 'cumulative-closure'
            plan_delta_reason = prior['reason'] or 'coverage predecessor is absent'
        elif snapshot_unsafe or delta_unsafe:
            plan_delta_mode = 'cumulative-closure'
            plan_delta_reason = 'coverage predecessor delta is unsafe or opaque'
        else:
            plan_delta_mode = 'receipt-delta'
        fallback = None
    basis = {p: patch for p, patch in (changes if use_delta else patches)
             if (delta_categories if use_delta else categories)[p] == 'semantic'}
    closure_paths = []
    plan_patch_basis = None
    if args.phase == 'plan':
        changed = {path: patch for path, patch in patches}
        closure_paths = plan_closure_paths(plan_clusters, data['dependencies'], changed)
        if not closure_paths:
            raise ValueError('plan closure contains no changed paths')
        if set(closure_paths) & set(opaque):
            raise ValueError('plan closure contains opaque changed paths')
        basis = {path: changed[path] for path in closure_paths}
        closure_raw = b''.join(basis[path] for path in sorted(basis))
        if len(closure_raw) > PLAN_CLOSURE_MAX_BYTES:
            raise ValueError('plan closure is oversized')
        if plan_delta_mode == 'receipt-delta':
            plan_patch_basis = {path: patch for path, patch in changes
                                if delta_categories[path] == 'semantic'}
        else:
            plan_patch_basis = changed
    if not basis and not fallback and args.phase != 'repair':
        fallback = 'no semantic components'; use_delta = False
    if args.phase == 'plan':
        plan_assignments, plan_delta_assignments = split_plan_cluster_assignments(
            chosen, owner, plan_clusters)
        components = plan_components_for(
            basis, data['dependencies'], chosen, owner, plan_clusters,
            cluster_assignments=plan_assignments)
    else:
        plan_assignments = {}; plan_delta_assignments = {}
        components = components_for(
            basis, data['dependencies'], chosen, owner,
            previous.get('findings') if use_delta else None)
    scopes = {}
    specialist_artifacts = {}
    patch_bodies = {}
    plan_owned_paths = (plan_delta_paths(
        chosen, owner, plan_clusters, plan_delta_assignments,
        data['dependencies'], plan_patch_basis) if args.phase == 'plan' else {})
    adapters = {s['seat']: s.get('adapter', '') for s in roster['seats']}
    for seat, bundle in chosen.items():
        mode = 'full' if seat == owner or args.phase == 'repair' else 'semantic'
        if args.phase == 'plan':
            mode = ('full' if seat == owner else
                    'delta' if plan_delta_mode == 'receipt-delta' else 'closure')
        if args.phase == 'verification':
            mode = ('full' if seat == owner else 'delta' if use_delta else 'semantic')
            if fallback:
                mode = 'full'
        if fallback and args.phase != 'verification':
            mode = 'full'
        name = f'{prefix}-full.patch' if mode == 'full' else f'{prefix}-{seat}.patch'
        component_ids = [c['id'] for c in components if mode == 'full' or seat in c['specialists']]
        if mode != 'full':
            if args.phase == 'plan':
                paths = plan_owned_paths[seat]
                specialist_artifacts[name] = b''.join(
                    plan_patch_basis[p] for p in paths)
            else:
                paths = {p for c in components if seat in c['specialists'] for p in c['files']}
                specialist_artifacts[name] = b''.join(basis[p] for p in sorted(paths))
        patch_body = full if mode == 'full' else specialist_artifacts[name]
        patch_bodies[seat] = patch_body
        scopes[seat] = {'bundle': bundle, 'bundles': bundle.split('+'), 'scope': mode,
                        'full_state': mode == 'full', 'adapter': adapters[seat], 'components': component_ids,
                        'patch': str(session / name), 'patch_sha256': digest(patch_body),
                        'patch_bytes': len(patch_body), 'patch_lines': len(split_lf_lines(patch_body))}
        if args.phase == 'plan':
            scopes[seat]['plan_clusters'] = plan_assignments[seat]
            scopes[seat]['delta_clusters'] = plan_delta_assignments[seat]
            scopes[seat]['delta_paths'] = sorted(paths) if mode != 'full' else []
    patch_sets, patch_chunk_artifacts = patch_sets_for(
        scopes, patch_bodies, prefix, chunk_mode)
    prepared_search_bytes = 0
    prepared_search_words = 0
    if args.phase == 'plan':
        clusters_by_id = {cluster['id']: cluster for cluster in plan_clusters}
        for assignment in scopes.values():
            for cluster_id in assignment['plan_clusters']:
                proof = clusters_by_id[cluster_id]['search_proof']
                raw = plan_search_artifacts[proof['artifact']]
                prepared_search_bytes += len(raw)
                prepared_search_words += len(raw.split())
        if len(chosen) > 1 and (sum(len(body) for body in patch_bodies.values()) + prepared_search_bytes
                                > len(full) * len(chosen) * 9 // 10):
            raise ValueError('routed plan inputs save less than 10 percent')
    data['assignments'] = scopes
    predecessor = (previous['coverage_reference']
                   if previous and (use_delta or args.phase == 'plan') else None)
    data.update(phase=args.phase, snapshot_tree=snapshot, base_tree=base_tree,
                fallback_reason=fallback, predecessor=predecessor, delta_unsafe=delta_unsafe,
                scope=repo.selected, paths=sorted(categories),
                semantic_paths=sorted(p for p in categories if categories[p] == 'semantic'),
                delta_paths=sorted(p for p in delta_categories if delta_categories[p] == 'semantic'),
                components=components)
    if parent_assignment is not None:
        if (snapshot != parent_manifest['snapshot_tree'] or base_tree != parent_manifest['base_tree']
                or source != parent_manifest['source'] or inputs['roster.json'] != parent_assignment['roster_sha256']):
            raise ValueError('repair child does not match its parent panel boundary')
        data['parent_assignment'] = parent_assignment
    if args.phase == 'plan':
        plan_name = prefix + '-plan.md'
        data['plan'] = {'source': str(plan_source), 'source_sha256': args.plan_sha256,
                        'artifact': plan_name, 'sha256': digest(plan_raw), 'bytes': len(plan_raw),
                        'clusters': plan_clusters, 'closure_paths': closure_paths,
                        'routing_version': 1, 'delta_mode': plan_delta_mode,
                        'delta_reason': plan_delta_reason,
                        'common_artifacts': [prefix + '-evidence.md']}
    data['source_context'], source_artifacts = source_context(
        repo, snapshot, base_tree, data, components, scopes, owner, prefix, source_context_enabled,
        plan_clusters)
    patch_chunks_effective_mode = chunk_mode
    task_capacity = compile_task_capacity(
        scopes, patch_sets, data['source_context'], plan_clusters)
    capacity_failures = task_capacity_errors(task_capacity)
    if chunk_mode == 'auto' and any(
            failure.startswith('task exceeds provider turn capacity: ')
            for failure in capacity_failures):
        forced_sets, forced_artifacts = patch_sets_for(
            scopes, patch_bodies, prefix, '1')
        forced_capacity = compile_task_capacity(
            scopes, forced_sets, data['source_context'], plan_clusters)
        if not task_capacity_errors(forced_capacity):
            patch_sets = forced_sets
            patch_chunk_artifacts = forced_artifacts
            task_capacity = forced_capacity
            capacity_failures = []
            patch_chunks_effective_mode = '1'
    if capacity_failures:
        raise ValueError(capacity_failures[0])
    if args.phase == 'plan':
        clusters_by_id = {cluster['id']: cluster for cluster in plan_clusters}
        for seat, assignment in scopes.items():
            required = {Path(assignment['patch']).name}
            patch_set = patch_sets[assignment['patch_set']]
            required.update(chunk['artifact'] for chunk in patch_set['chunks'])
            source_packet = data['source_context']['seats'][seat]
            required.update(shard['artifact'] for shard in source_packet['shards'])
            required.update(segment['artifact']
                            for source_range in source_packet['required_source_ranges']
                            for segment in source_range['segments'])
            assignment['required_artifacts'] = sorted(required)
    packet = markdown(data, session / (prefix + '-evidence.json'))
    artifacts = {prefix + '-full.patch': full, prefix + '-semantic.patch': semantic,
                 prefix + '-delta.patch': delta, prefix + '-evidence.json': encoded(data),
                 prefix + '-evidence.md': packet, prefix + '-instructions.md': instruction_packet,
                 **specialist_artifacts, **source_artifacts, **patch_chunk_artifacts,
                 **plan_search_artifacts}
    if args.phase == 'plan':
        artifacts[prefix + '-plan.md'] = plan_raw
        artifacts[prefix + '-plan-closure.patch'] = closure_raw
    words = {'full': len(full.split()), 'semantic': len(semantic.split()), 'delta': len(delta.split()),
             'evidence': len(packet.split()) + len(instruction_packet.split())}
    words['source_context'] = sum(len(raw.split()) for raw in source_artifacts.values())
    words['assigned_patch'] = sum(len(artifacts[Path(a['patch']).name].split()) for a in scopes.values())
    if args.phase == 'plan':
        words['plan'] = len(plan_raw.split())
        words['closure'] = len(artifacts[prefix + '-plan-closure.patch'].split())
        words['prepared_search'] = prepared_search_words
    words['avoided'] = max(0, len(scopes) * words['full'] - words['assigned_patch']
                           - len(scopes) * words['evidence'] - words['source_context']
                           - words.get('prepared_search', 0))
    manifest = {'schema_version': 4 if args.phase == 'plan' else 2, 'session': str(session), 'label': args.label,
                'phase': args.phase, 'snapshot_tree': snapshot, 'base_tree': base_tree,
                'source': source, 'snapshot_unsafe': snapshot_unsafe, 'assignments': scopes,
                'predecessor': predecessor, 'delta_unsafe': delta_unsafe,
                'mechanical_owner': owner, 'mechanical': data['mechanical'], 'fallback_reason': fallback,
                'scope': repo.selected, 'paths': data['paths'], 'semantic_paths': data['semantic_paths'],
                'delta_paths': data['delta_paths'], 'components': components, 'instructions': data['instructions'],
                'source_context': data['source_context'],
                'patch_chunks_mode': chunk_mode,
                'patch_chunks_effective_mode': patch_chunks_effective_mode,
                'patch_chunks_enabled': chunk_mode != '0', 'patch_sets': patch_sets,
                'task_capacity': task_capacity,
                'word_counts': words, 'inputs': inputs,
                'artifacts': {name: {'sha256': digest(raw), 'words': len(raw.split())} for name, raw in artifacts.items()}}
    if args.phase == 'plan':
        manifest['plan'] = data['plan']
    if deps_view is not None:
        manifest['dependency_view'] = deps_view
    # Recorded on EVERY manifest, so a consumer never has to infer enforcement from the roster.
    # A non-empty list means those seats cannot supply a read audit and the panel is not certified.
    manifest['unenforced_seats'] = unenforced_seats
    if parent_assignment is not None:
        manifest['parent_assignment'] = parent_assignment
    manifest_path = session / (prefix + '-evidence.manifest.json')
    receipt_path = session / (prefix + '-coverage.receipt.json')
    if receipt_path.exists() and (not manifest_path.exists() or manifest_path.read_bytes() != encoded(manifest)):
        raise ValueError('cannot replace an already receipted manifest')
    for name, raw in artifacts.items():
        publish(session / name, raw)
    publish(manifest_path, encoded(manifest))
    print(manifest_path)


def render(args):
    manifest, mh = validated_manifest(
        args.manifest, fresh=not args.offline, offline=args.offline,
        replay_plan_searches=False)
    render_seat(manifest, mh, args.seat, args.plan_source)


def render_panel(args):
    """Render every seat from one manifest read; validate-prompt binds the embedded hash."""
    raw = Path(args.manifest).read_bytes()
    manifest = json.loads(raw)
    output = Path(args.output_dir)
    if output.is_symlink() or not output.is_dir():
        raise ValueError('fragment output is not a directory')
    if len(set(args.seats)) != len(args.seats):
        raise ValueError('duplicate panel seat')
    if args.phase is not None and args.phase != manifest['phase']:
        raise ValueError('evidence manifest phase is ' + str(manifest['phase']) + ', not ' + args.phase)
    mh = digest(raw)
    for seat in args.seats:
        if not SAFE_NAME.fullmatch(seat):
            raise ValueError('invalid panel seat: ' + seat)
        fragment = io.StringIO()
        with redirect_stdout(fragment):
            render_seat(manifest, mh, seat, args.plan_source)
        (output / seat).write_bytes(fragment.getvalue().encode(sys.stdout.encoding, sys.stdout.errors))
    print(manifest['phase'])


def render_seat(manifest, mh, seat, plan_source):
    assignment = manifest['assignments'].get(seat)
    if assignment is None:
        raise ValueError('seat not assigned')
    expected_plan = (Path(manifest['session']) / manifest['plan']['artifact']
                     if manifest['phase'] == 'plan' else None)
    if expected_plan is None:
        if plan_source:
            raise ValueError('--plan-source belongs only to plan evidence')
    elif not plan_source or Path(plan_source).resolve() != expected_plan:
        raise ValueError('plan evidence requires its immutable plan snapshot')
    print('Evidence manifest SHA-256: ' + mh)
    print('Assigned scope: ' + assignment['scope'])
    print('Assigned risk bundle: ' + assignment['bundle'])
    patch_mode = assignment['patch_read_mode']
    context = manifest['source_context']['seats'][seat]
    if (manifest['schema_version'] == 4 and manifest['phase'] == 'plan'
            and seat != manifest['mechanical_owner']):
        primary = None
        if assignment['patch_bytes']:
            if patch_mode == 'chunks':
                primary = str(Path(manifest['session']) /
                              manifest['patch_sets'][assignment['patch_set']]['chunks'][0]['artifact'])
            else:
                primary = assignment['patch']
        if primary is None:
            patch_name = Path(assignment['patch']).name
            candidates = [name for name in assignment['required_artifacts']
                          if name != patch_name]
            first_evidence = (candidates[0] if candidates
                              else manifest['plan']['common_artifacts'][0])
            primary = str(Path(manifest['session']) / first_evidence)
        if assignment['adapter'] == 'codex':
            if assignment['patch_bytes'] and patch_mode != 'chunks':
                primary_action = ("run sed -n '1," + str(min(240, assignment['patch_lines']))
                                  + "p' " + shlex.quote(primary))
            else:
                primary_action = 'run ' + shlex.join(['cat', '--', primary])
        else:
            tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
            if assignment['patch_bytes'] and patch_mode != 'chunks':
                primary_action = ('use ' + tool + ' with offset 1 and limit 240 on '
                                  + primary)
            else:
                primary_action = 'use ' + tool + ' to read ' + primary + ' in full'
        print('Plan specialist first-call contract: ' + primary_action
              + ' as exactly one native primary-artifact read. Do not run a directory command, '
              + 'search, or compound shell command before or with this read.')
    if manifest['phase'] == 'plan':
        plan = manifest['plan']
        print('Immutable plan snapshot SHA-256: ' + plan['sha256'])
        cluster_ids = set(assignment.get('plan_clusters', [
            cluster['id'] for cluster in plan['clusters']]))
        for cluster in (cluster for cluster in plan['clusters']
                        if cluster['id'] in cluster_ids):
            proof = cluster.get('search_proof')
            if proof is None:
                command = (shlex.join(plan_search_argv(cluster['search_contract']))
                           + ' | head -' + str(PLAN_SEARCH_OVERFLOW_RESULTS))
                print('Required cluster sibling search: ' + cluster['id'] + ' run ' + command
                      + ' from repository root; at most 80 result lines are accepted, and an '
                      + '81st line invalidates proof.')
            else:
                body = (Path(manifest['session']) / proof['artifact']).read_text()
                print('Prepared cluster sibling search: ' + cluster['id'] + ' '
                      + proof['artifact'] + ' SHA-256 ' + proof['sha256'])
                print('Prepared cluster search output: '
                      + json.dumps(body, ensure_ascii=True, separators=(',', ':')))
            for row in cluster['paths']:
                location = row['path']
                if row['line_start'] is not None:
                    location += ':' + str(row['line_start'])
                    if row['line_end'] != row['line_start']:
                        location += '-' + str(row['line_end'])
                print('Required cluster source: ' + cluster['id'] + ' ' + location
                      + ' resolution ' + row['resolution'] + ' field ' + row['field'])
        for row in plan_mandatory_source_windows(manifest, context):
            print('Mandatory cluster source window: ' + row['path'] + ':'
                  + str(row['line_start']) + '-' + str(row['line_end']))
    print('Assigned patch read mode: ' + patch_mode)
    first_action = None
    if patch_mode == 'chunks':
        patch_set = manifest['patch_sets'][assignment['patch_set']]
        batch_limit = read_batch_limit(assignment['adapter'])
        print('Patch chunk batch limit: ' + str(batch_limit))
        print('Canonical assigned patch: ' + assignment['patch'] + ' SHA-256 '
              + assignment['patch_sha256'] + ' bytes ' + str(assignment['patch_bytes']))
        total = len(patch_set['chunks'])
        for chunk in patch_set['chunks']:
            print('Assigned patch chunk ' + str(chunk['index']) + '/' + str(total) + ': '
                  + str(Path(manifest['session']) / chunk['artifact']) + ' bytes '
                  + str(chunk['byte_start']) + '-' + str(chunk['byte_end']) + ' SHA-256 '
                  + chunk['sha256'])
        first = str(Path(manifest['session']) / patch_set['chunks'][0]['artifact'])
        if assignment['adapter'] == 'codex':
            first_action = ('run ' + shlex.join(['cat', '--', first])
                            + '; then read one listed chunk per command in exact order.')
        else:
            tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
            first_action = ('use ' + tool + ' to read ' + str(batch_limit)
                            + ' consecutive listed chunk' + ('' if batch_limit == 1 else 's')
                            + ' in full; continue in exact order.')
    else:
        print('Read the entire assigned patch in bounded windows of at most 240 lines: '
              + assignment['patch'])
        if assignment['patch_lines'] == 0:
            print('Assigned patch is empty; no assigned-patch read is required.')
        elif assignment['adapter'] == 'codex':
            end = min(240, assignment['patch_lines'])
            first_action = ("run sed -n '1," + str(end) + "p' "
                            + shlex.quote(assignment['patch'])
                            + '; continue with consecutive windows of at most 240 lines.')
        else:
            tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
            first_action = ('use ' + tool + ' with offset 1 and limit 240 on '
                            + assignment['patch'] + '; continue with consecutive windows.')
    if first_action is not None:
        print('First assigned-patch action: ' + first_action
              + ' Do not read the evidence index, source context, or original source until '
              + 'the assigned patch is complete.')
    print('Source context enabled: ' + str(manifest['source_context']['enabled']).lower())
    if manifest['source_context']['enabled']:
        print('Post-patch evidence order: read every listed source-context packet and required '
              + 'source segment in exact order before the evidence index or original source.')
        if context['shards']:
            print('Source context packet batch limit: '
                  + str(manifest['source_context']['packet_batch_limit']))
            first_packet = str(Path(manifest['session']) / context['shards'][0]['artifact'])
            if assignment['adapter'] == 'codex':
                packet_action = 'run ' + shlex.join(['cat', '--', first_packet])
            else:
                tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
                packet_action = 'use ' + tool + ' to read ' + first_packet + ' in full'
            print('First source-context action: ' + packet_action
                  + ' as the only source-context packet read in this turn; continue with one '
                  + 'listed packet per turn in exact order.')
        for shard in context['shards']:
            print('Source context packet: ' + str(Path(manifest['session']) / shard['artifact']))
        for row in context['required_source_ranges']:
            print('Required source range: ' + row['path'] + ':' + str(row['line_start']) + '-'
                  + str(row['line_end']) + ' tree ' + row['blob_tree'] + ' blob ' + row['blob_oid']
                  + ' content SHA-256 '
                  + row['content_sha256'] + ' reasons ' + json.dumps(row['reasons'], ensure_ascii=True))
            total = len(row['segments'])
            for segment in row['segments']:
                path = str(Path(manifest['session']) / segment['artifact'])
                if assignment['adapter'] == 'codex':
                    action = 'run ' + shlex.join(['cat', '--', path])
                else:
                    tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
                    action = 'use ' + tool + ' to read ' + path + ' in full'
                print('Required source segment ' + str(segment['index']) + '/' + str(total)
                      + ': ' + action + ' raw bytes ' + str(segment['raw_bytes'])
                      + ' visible bytes ' + str(segment['predicted_visible_bytes'])
                      + ' content SHA-256 ' + segment['content_sha256'])
            print('Required source segment batch limit: '
                  + str(read_batch_limit(assignment['adapter'])))
        print('Source read required: ' + str(context['source_read_required']).lower())
    else:
        print('Post-patch evidence order: read the evidence index before original source.')
        print('Source read required: true')
    print('Evidence navigation index: '
          + str(Path(manifest['session']) / f"r{manifest['label']}-evidence.md"))
    omitted_ranges = context['omitted_source_ranges'] if manifest['source_context']['enabled'] else []
    if omitted_ranges:
        row = min(omitted_ranges, key=lambda value: (
            value['priority'], value['path'], value['blob_tree'], value['line_start'],
            value['line_end']))
        target_kind = 'Required' if context['source_read_required'] else 'Optional'
        print(target_kind + ' post-index original-source target: ' + row['path'] + ':'
              + str(row['line_start']) + '-' + str(row['line_end']) + ' tree '
              + row['blob_tree'] + ' blob ' + row['blob_oid'] + ' content SHA-256 '
              + row['content_sha256'] + ' reasons '
              + json.dumps(row['reasons'], ensure_ascii=True))
        print('Additional omitted source identities retained in manifest: '
              + str(len(omitted_ranges) - 1)
              + '. Read them only for a concrete question that could prove or refute a finding.')
    print('Mechanical owner: ' + str(manifest['mechanical_owner']))
    print('After completing the post-patch evidence order, open original source to prove each '
          + 'finding; expand beyond this index when needed.')


def verify(args):
    manifest, mh = validated_manifest(args.manifest)
    print(str(Path(manifest['session']) / f"r{manifest['label']}-evidence.manifest.json") + ' ' + mh)


def same_source(args):
    def load(path):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('schema_version') not in (2, 3, 4)
                or not isinstance(value.get('scope'), str)
                or not isinstance(value.get('paths'), list)
                or any(not isinstance(item, str) for item in value['paths'])
                or not isinstance(value.get('source'), dict)
                or not isinstance(value.get('snapshot_unsafe'), list)
                or any(not isinstance(item, str) for item in value['snapshot_unsafe'])
                or any(not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value.get(field, ''))
                       for field in ('snapshot_tree', 'base_tree'))):
            raise ValueError('invalid source identity manifest')
        return value

    parent = load(args.parent)
    candidate = load(args.candidate)
    fields = ('snapshot_tree', 'base_tree', 'scope', 'paths', 'source', 'snapshot_unsafe')
    changed = [field for field in fields if parent.get(field) != candidate.get(field)]
    if changed:
        raise ValueError('source identity changed: ' + ', '.join(changed))
    print(parent['snapshot_tree'])


def parse_replacements(values):
    replacements = {}
    for value in values or []:
        seat, separator, label = value.partition('=')
        if (not separator or not SAFE_NAME.fullmatch(seat)
                or not SAFE_NAME.fullmatch(label)):
            raise ValueError('invalid replacement assignment')
        if seat in replacements:
            raise ValueError('duplicate replacement seat: ' + seat)
        replacements[seat] = label
    return replacements


def verify_panel_selection(session, label, replacement_values=None, fresh=True, seen=None,
                           verdicts=None):
    manifest_path = session / f'r{label}-evidence.manifest.json'
    manifest, mh = validated_manifest(
        manifest_path, fresh=fresh, seen=seen, replay_plan_searches=False)
    replacements = parse_replacements(replacement_values)
    if not replacements:
        results = validate_results(session, manifest, mh, verdicts=verdicts)
        final_manifest, final_hash = validated_manifest(
            manifest_path, fresh=fresh, seen=seen, replay_plan_searches=False)
        if final_hash != mh or final_manifest != manifest:
            raise ValueError('panel manifest changed during verification')
        return manifest, mh, results, None, replacements
    validate_panel_coverage(manifest)
    if len(replacements) > 1:
        raise ValueError('at most one replacement per panel')
    if not set(replacements) <= set(manifest['assignments']):
        raise ValueError('replacement seat is absent from parent panel')
    if any(child_label != label + 'x' for child_label in replacements.values()):
        raise ValueError('replacement label must be ' + label + 'x')
    results = {}
    generations = {}
    children = {}
    for seat in manifest['assignments']:
        child_label = replacements.get(seat)
        if child_label is None:
            hashes, generation = result_generation(session, manifest, mh, seat)
        else:
            try:
                result_generation(session, manifest, mh, seat)
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError,
                    RecursionError, UnicodeError):
                pass
            else:
                raise ValueError('replacement parent assignment is already valid: ' + seat)
            child_path = session / f'r{child_label}-evidence.manifest.json'
            child, child_hash = validated_manifest(child_path, fresh=fresh, seen=seen)
            binding = child.get('parent_assignment')
            if (not isinstance(binding, dict) or binding.get('manifest') != manifest_path.name
                    or binding.get('manifest_sha256') != mh or binding.get('seat') != seat):
                raise ValueError('replacement child is bound to another parent seat: ' + seat)
            hashes, generation = result_generation(session, child, child_hash,
                                                   next(iter(child['assignments'])))
            children[seat] = (child_path, child, child_hash)
        overlap = set(results) & set(hashes)
        if overlap:
            raise ValueError('mixed result generations: ' + ', '.join(sorted(overlap)))
        results.update(hashes)
        generations[seat] = generation
        if verdicts is not None and 'unenforced_audit' in generation:
            verdicts[seat] = generation['unenforced_audit']
    final_manifest, final_hash = validated_manifest(
        manifest_path, fresh=fresh, seen=seen, replay_plan_searches=False)
    if final_hash != mh or final_manifest != manifest:
        raise ValueError('panel manifest changed during verification')
    for seat, (child_path, child, child_hash) in children.items():
        final_child, final_child_hash = validated_manifest(
            child_path, fresh=fresh, seen=seen, replay_plan_searches=False)
        if final_child_hash != child_hash or final_child != child:
            raise ValueError('replacement manifest changed during verification: ' + seat)
    return manifest, mh, results, generations, replacements


def verify_panel_data(session, label):
    manifest, mh, results, _, _ = verify_panel_selection(session, label)
    return manifest, mh, results


def selected_advisories(session, manifest, generations):
    rows = {}
    # An unenforced seat has no enforced read audit to carry advisories: the receipt skipped it, and
    # in production nothing wrote the file at all. Reading it here would have failed the whole
    # receipt for a seat the panel deliberately does not enforce.
    unenforced = set(manifest.get('unenforced_seats', []))
    for seat in manifest['assignments']:
        if seat in unenforced:
            continue
        audit = read_json(session / (generation_stem(manifest, generations, seat) + '.read-audit.json'))
        advisories = audit.get('advisories', [])
        if advisories:
            rows[seat] = advisories
    return rows


def verify_panel(args):
    session = Path(args.session).resolve()
    verdicts = {}
    manifest, mh, results, generations, replacements = verify_panel_selection(
        session, args.label, args.replacement, verdicts=verdicts)
    data = {'manifest': f'r{args.label}-evidence.manifest.json',
            'manifest_sha256': mh, 'phase': manifest['phase'], 'results': results,
            'advisories': selected_advisories(session, manifest, generations)}
    if verdicts:
        data['unenforced_audits'] = verdicts
    if generations is not None:
        data.update(replacements=replacements, selected_generations=generations)
    print(json.dumps(data, sort_keys=True, separators=(',', ':')))


def receipt(args):
    session = Path(args.session).resolve()
    manifest_path = session / f'r{args.label}-evidence.manifest.json'
    verdicts = {}
    manifest, mh, results, generations, replacements = verify_panel_selection(
        session, args.label, args.replacement, verdicts=verdicts)
    if manifest['phase'] == 'plan':
        raise ValueError('plan panels never advance code coverage')
    data = {'schema_version': 1, 'manifest': manifest_path.name, 'manifest_sha256': mh,
            'snapshot_tree': manifest['snapshot_tree'], 'base_tree': manifest['base_tree'],
            'phase': manifest['phase'], 'assignments': manifest['assignments'], 'results': results,
            'advisories': selected_advisories(session, manifest, generations),
            'findings': finding_ownership(session, manifest, generations)}
    if verdicts:
        data['unenforced_audits'] = verdicts
    if generations is not None:
        data.update(schema_version=2, replacements=replacements,
                    selected_generations=generations)
    path = session / f'r{args.label}-coverage.receipt.json'; raw = encoded(data)
    head = current_coverage_head(session)
    created = not path.exists()
    if not created:
        if path.read_bytes() != raw:
            raise ValueError('coverage receipt is immutable')
    else:
        publish(path, raw)
    if created or head is None:
        publish(session / 'coverage-head.json', encoded({'receipt': path.name, 'sha256': digest(raw)}))
    print(path)


def first_receipt_tree(session):
    labels = sorted(int(match.group(1)) for match in (
        re.fullmatch(r'r([0-9]+)-coverage\.receipt\.json', path.name) for path in session.iterdir())
        if match)
    if not labels:
        raise ValueError('no code round receipt to anchor the review base')
    return read_json(session / f'r{labels[0]}-coverage.receipt.json')['snapshot_tree']


def review_origin(args):
    """Count the round's chosen citations that land on lines the review itself changed."""
    session = Path(args.session).resolve()
    receipt = read_json(session / f'r{args.label}-coverage.receipt.json')
    manifest, mh = validated_manifest(session / receipt['manifest'], fresh=False,
                                      replay_plan_searches=False)
    if receipt.get('manifest_sha256') != mh or receipt.get('snapshot_tree') != manifest['snapshot_tree']:
        raise ValueError('receipt does not match its manifest')
    base = args.base_tree or first_receipt_tree(session)
    repo = Repository(session)
    _, hunks, _, _ = repo.changes(base, receipt['snapshot_tree'])
    after = repo.entries(receipt['snapshot_tree'])
    whole, changed = set(), {}
    for hunk in hunks:
        body = repo.blob(after[hunk['path']]) if hunk['path'] in after else b''
        total = len(split_lf_lines(body))
        if hunk['kind'] == 'opaque' or total == 0:
            whole.add(hunk['path'])
            continue
        # A deletion is anchored where it happened; clamp line 0 and EOF+1 to a surviving line.
        changed.setdefault(hunk['path'], set()).update(
            min(max(line, 1), total) for line in hunk['changed_lines'])
    citations = 0
    for seat in manifest['assignments']:
        stem = generation_stem(manifest, receipt.get('selected_generations'), seat)
        raw = (session / (stem + '.json')).read_bytes()
        if receipt['results'].get(stem + '.json') != digest(raw):
            raise ValueError('result changed after the receipt: ' + stem)
        for finding in json.loads(raw)['findings']:
            lines = changed.get(finding['file'], ())
            if finding['file'] in whole or any(
                    finding['line_start'] <= line <= finding['line_end'] for line in lines):
                citations += 1
    print(json.dumps({'label': args.label, 'review_base_tree': base, 'citations': citations},
                     sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('session'); prep.add_argument('label')
    prep.add_argument('--phase', required=True, choices=('discovery', 'risk', 'verification', 'repair', 'plan'))
    prep.add_argument('--head'); prep.add_argument('--assignment', action='append', default=[])
    prep.add_argument('--full-seat')
    prep.add_argument('--plan'); prep.add_argument('--plan-sha256')
    prep.add_argument('--parent-assignment')
    rend = commands.add_parser('render'); rend.add_argument('manifest'); rend.add_argument('seat')
    rend.add_argument('--offline', action='store_true')
    rend.add_argument('--plan-source')
    rend_panel = commands.add_parser('render-panel')
    rend_panel.add_argument('manifest'); rend_panel.add_argument('seats', nargs='+')
    rend_panel.add_argument('--output-dir', required=True)
    rend_panel.add_argument('--plan-source'); rend_panel.add_argument('--phase')
    check = commands.add_parser('verify'); check.add_argument('manifest')
    source = commands.add_parser('same-source')
    source.add_argument('parent'); source.add_argument('candidate')
    panel = commands.add_parser('verify-panel'); panel.add_argument('session'); panel.add_argument('label')
    panel.add_argument('--replacement', action='append', default=[])
    rec = commands.add_parser('receipt'); rec.add_argument('session'); rec.add_argument('label')
    rec.add_argument('--replacement', action='append', default=[])
    origin = commands.add_parser('review-origin')
    origin.add_argument('session'); origin.add_argument('label'); origin.add_argument('--base-tree')
    args = parser.parse_args()
    try:
        if hasattr(args, 'label') and not SAFE_NAME.fullmatch(args.label):
            raise ValueError('invalid label')
        with plan_search_signal_handlers():
            {'prepare': prepare, 'render': render, 'render-panel': render_panel,
             'verify': verify, 'same-source': same_source,
             'verify-panel': verify_panel, 'receipt': receipt,
             'review-origin': review_origin}[args.command](args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as error:
        print('evidence: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
