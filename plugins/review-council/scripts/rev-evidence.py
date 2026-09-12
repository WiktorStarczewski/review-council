#!/usr/bin/env python3
"""Build deterministic review scopes and certify completed snapshot coverage."""
import argparse
import ast
from bisect import bisect_right
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import posixpath

BUNDLES = ('correctness-boundaries', 'security-state-api',
           'concurrency-resources-performance', 'tests-observability-maintenance-regression')
PLAN_BUNDLES = ('plan-completeness', 'plan-soundness', 'plan-simplicity', 'plan-tests')
SOURCE_CONTEXT_LIMIT = 32768
SOURCE_SEGMENT_VISIBLE_LIMIT = SOURCE_CONTEXT_LIMIT // 2
SOURCE_SEGMENT_LINE_LIMIT = 240
SOURCE_SEGMENT_PREFIX_RESERVE = 8
PATCH_CHUNK_RAW_LIMIT = 24 * 1024
PATCH_CHUNK_VISIBLE_LIMIT = 30 * 1024
PATCH_CHUNK_LINE_LIMIT = 1000
PATCH_CHUNK_PREFIX_RESERVE = 8
PLAN_MAX_BYTES = 256 * 1024
PLAN_CLOSURE_MAX_BYTES = 8 * 1024 * 1024
SOURCE_ANCHOR_RADIUS = 8
SOURCE_CONTEXT_REASONS = ('declaration', 'production-caller', 'related-test',
                          'gate', 'extra-caller', 'extra-test')
NAVIGATION_ROW_LIMIT = 1024
NAVIGATION_TOTAL_LIMIT = 16384
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\Z')
DIFF = ['diff', '--no-ext-diff', '--no-textconv', '--no-renames',
        '--no-indent-heuristic', '--diff-algorithm=myers', '--no-color',
        '--unified=3', '--binary', '--src-prefix=a/', '--dst-prefix=b/']
OVERSIZED_BLOB = object()


def phase_bundles(phase):
    return PLAN_BUNDLES if phase == 'plan' else BUNDLES


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patch_display_lines(raw):
    return raw.count(b'\n') + (1 if raw and not raw.endswith(b'\n') else 0)


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


def patch_chunk_mode(raw, chunks, enabled):
    if not enabled or not raw or b'\0' in raw:
        return 'windows'
    try:
        raw.decode('utf-8')
    except UnicodeDecodeError:
        return 'windows'
    windows = max(1, (len(raw.splitlines()) + 239) // 240)
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


def patch_sets_for(scopes, patch_bodies, prefix, enabled):
    sets = {}
    artifacts = {}
    identities = {}
    for seat, assignment in scopes.items():
        raw = patch_bodies[seat]
        identity = assignment['patch_sha256']
        if identity not in identities:
            try:
                chunks = partition_patch_chunks(raw) if enabled else []
            except (UnicodeDecodeError, ValueError):
                chunks = []
            mode = patch_chunk_mode(raw, chunks, enabled)
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
                'patch_lines': len(raw.splitlines()),
                'read_mode': mode,
                'chunks': rows,
            }
            identities[identity] = set_id
        set_id = identities[identity]
        patch_set = sets[set_id]
        if (patch_set['patch_bytes'] != len(raw) or patch_set['patch_lines'] != len(raw.splitlines())
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


def input_hashes(session):
    result = {}
    for name in ('scope.env', 'roster.json', 'files.txt', 'untracked.txt'):
        path = session / name
        if path.exists() and not path.is_file():
            raise ValueError('input must be a regular file: ' + name)
        result[name] = digest(path.read_bytes()) if path.exists() else None
    return result


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
        self.object_repository = session / 'evidence-repository'
        for directory in (self.object_repository, self.object_repository / 'objects',
                          self.object_repository / 'objects/info', self.object_repository / 'refs'):
            if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                raise ValueError('redirected evidence object repository')
            directory.mkdir(mode=0o700, exist_ok=True)
        repository_files = {
            self.object_repository / 'HEAD': b'ref: refs/heads/review-council\n',
            self.object_repository / 'objects/info/alternates':
                (str(self.objects) + '\n' + str(objects) + '\n').encode(),
        }
        for path, content in repository_files.items():
            if path.exists():
                metadata = path.lstat()
                if path.is_symlink() or not path.is_file() or metadata.st_nlink != 1:
                    raise ValueError('redirected evidence object repository file')
                if path.read_bytes() != content:
                    raise ValueError('changed evidence object repository file')
            else:
                path.write_bytes(content)
        allowed = {
            self.object_repository.resolve(),
            (self.object_repository / 'objects').resolve(),
            (self.object_repository / 'objects/info').resolve(),
            (self.object_repository / 'refs').resolve(),
            *(path.resolve() for path in repository_files),
        }
        for directory, dirs, files in os.walk(self.object_repository, followlinks=False):
            for name in dirs + files:
                path = Path(directory) / name
                if (path.resolve() not in allowed or path.is_symlink()
                        or (path.is_file() and path.stat().st_nlink != 1)
                        or not (path.is_file() or path.is_dir())):
                    raise ValueError('unsupported evidence object repository entry: ' + name)
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
                    position = int(re.search(r'\+(\d+)', match.group()).group(1))
                    changed_lines = []
                    for line in hbody.splitlines():
                        if line.startswith(('+', '-')):
                            changed_lines.append(position)
                        if line.startswith((' ', '+')):
                            position += 1
                    hunks.append({'path': path, 'kind': kind, 'sha256': digest(encoded(atom)),
                                  'header': match.group().strip(), 'changed_lines': sorted(set(changed_lines))})
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
            or re.search(r'(?im)^.{0,8}(?:@generated|generated (?:file|by)|code generated by|do not edit)\b', '\n'.join(text.splitlines()[:8]))):
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


def facts(repo, tree, hunks, categories):
    texts = {}
    entries = {p: e for p, e in repo.entries(tree).items() if repo.scoped(p)}
    seed_paths = {h['path'] for h in hunks}
    for path, raw in repo.iter_blobs({p: e for p, e in entries.items() if p in seed_paths}):
        if entries[path][0] not in ('100644', '100755'):
            continue
        if raw is OVERSIZED_BLOB or b'\0' in raw:
            continue
        try:
            texts[path] = raw.decode('utf-8').splitlines()
        except UnicodeDecodeError:
            continue
    symbols = []; seen = set()
    declaration = re.compile(r'^\s*(?:(?:export|pub|public|private|static|async)\s+)*(?:def|fn|function|class|struct|enum|interface|type|const|let|func)\s+([A-Za-z_$][\w$]*)')
    declarations = {}
    seeds = {}
    for hunk in hunks:
        seeds.setdefault(hunk['path'], []).append(hunk.get('changed_lines') or [0])
    for path, hunk_lines in sorted(seeds.items()):
        lines = texts.get(path, [])
        if path not in declarations:
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
            declarations[path] = sorted(rows)
        candidates = declarations[path]
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
        for origin, end, name in sorted(selected, key=lambda item: (item[0], item[2] or '')):
            key = (path, origin, end, name)
            if key not in seen:
                seen.add(key); symbols.append({'path': path, 'line': origin, 'line_end': end,
                                               'name': name, 'kind': 'lexical declaration'
                                               if name else 'changed-line anchor'})
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
            lines = raw.decode('utf-8').splitlines()
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
    value_options = set()
    boolean_options = {'--line-number', '--null', '--with-filename'}
    boolean_short = set('Hn')
    recursive = tool == 'rg'
    line_number = False
    null_output = False
    if tool == 'grep':
        boolean_options.add('--recursive')
        boolean_short.update('rR')
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
            index += 2
            continue
        if any(word.startswith(option + '=') for option in value_options
               if option.startswith('--')):
            index += 1
            continue
        if any(word.startswith(option) and word != option for option in short_value_options):
            index += 1
            continue
        if word in boolean_options:
            recursive = recursive or word == '--recursive'
            line_number = line_number or word == '--line-number'
            null_output = null_output or word == '--null'
            index += 1
            continue
        if (word.startswith('-') and not word.startswith('--') and word != '-'
                and set(word[1:]) <= boolean_short):
            recursive = recursive or bool(set(word[1:]) & {'r', 'R'})
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
    domain = 'rg-default-worktree' if tool == 'rg' else 'grep-recursive-worktree'
    return {'engine': engine, 'domain': domain, 'pattern': pattern}, paths


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


def plan_field_paths(text, entries):
    """Resolve every path-like token in a plan field against the pinned tree."""
    if re.search(r'(?<![\w@.-])(?:/|\.\.?/)', text):
        raise ValueError('plan field contains a path escape')
    token_re = re.compile(
        r'(?<![\w@.-])((?:[A-Za-z0-9_@.-]+/)+[A-Za-z0-9_@.-]+'
        r'|[A-Za-z0-9_@-]+(?:\.[A-Za-z0-9_@.-]+)+'
        r'|Makefile|makefile|Justfile|justfile|Dockerfile|Containerfile)'
        r'(?::(\d+)(?:-(\d+))?)?')
    rows = []
    token_matches = list(token_re.finditer(text))
    for index, match in enumerate(token_matches):
        token = match.group(1).strip('`')
        if token.startswith(('../', './', '/')) or '..' in token.split('/'):
            raise ValueError('plan field contains a path escape')
        line_start = int(match.group(2)) if match.group(2) else None
        line_end = int(match.group(3)) if match.group(3) else line_start
        if line_start is not None and line_end < line_start:
            raise ValueError('plan field contains a reversed line range')
        if '/' in token:
            if token not in entries:
                raise ValueError('plan path does not exist in pinned snapshot: ' + token)
            path = token; resolution = 'direct'
        else:
            basename_candidates = sorted(path for path in entries if Path(path).name == token)
            if len(basename_candidates) != 1:
                reason = 'ambiguous' if basename_candidates else 'missing'
                raise ValueError(reason + ' plan basename in pinned snapshot: ' + token)
            path = basename_candidates[0]; resolution = 'basename'
        row = {'path': path, 'line_start': line_start, 'line_end': line_end,
               'token': token, 'resolution': resolution}
        if row not in rows:
            rows.append(row)
        end = token_matches[index + 1].start() if index + 1 < len(token_matches) else len(text)
        for shorthand in re.finditer(
                r'(?:^|[,;])\s*:(\d+)(?:-(\d+))?\b', text[match.end():end]):
            extra_start = int(shorthand.group(1))
            extra_end = int(shorthand.group(2)) if shorthand.group(2) else extra_start
            if extra_end < extra_start:
                raise ValueError('plan field contains a reversed line range')
            extra = dict(row, line_start=extra_start, line_end=extra_end)
            if extra not in rows:
                rows.append(extra)
    return rows


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
        for line in body.splitlines():
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
        required = {'findings', 'rule', 'sites'}
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
            resolved = plan_field_paths(field_text, entries)
            if not resolved:
                raise ValueError('plan cluster field contains no resolvable path: ' + field_name)
            for row in resolved:
                item = dict(row, field=field_name)
                if item not in path_rows:
                    path_rows.append(item)
        search_contract = plan_search_contract(fields['sites'])
        clusters.append({'id': heading.group(1), 'search_pattern': search_contract['pattern'],
                         'search_contract': search_contract, 'paths': path_rows})
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
    if args.phase != 'repair' and set(chosen) != set(seats):
        raise ValueError('panel assignments must include every core seat')
    owner = args.full_seat
    chosen = {s: chosen[s] for s in seats if s in chosen}
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
    if args.phase == 'discovery' and any(b != 'simplicity' for b in chosen.values()):
        raise ValueError('discovery assignments must use simplicity')
    if args.phase == 'repair' and len(chosen) != 1:
        raise ValueError('repair requires exactly one full seat')
    validate_assignment_topology(chosen, seats, args.phase)
    return chosen, owner


def bundle_coverage(chosen, bundles=BUNDLES):
    return set(b for value in chosen.values() for b in value.split('+')) == set(bundles)


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
    if len(seats) < 3:
        raise ValueError('review panel requires at least three core seats')
    if phase == 'discovery':
        if chosen != {seat: 'simplicity' for seat in seats}:
            raise ValueError('invalid discovery seat topology')
        return
    if set(chosen.values()) == {'unassigned'} and phase != 'plan':
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


def plan_components_for(patches, dependencies, chosen, owner, clusters):
    """Give every plan specialist one identical dependency closure."""
    components = components_for(patches, dependencies, chosen, owner)
    specialists = [seat for seat in chosen if seat != owner]
    required_paths = {row['path'] for cluster in clusters for row in cluster['paths']}
    for component in components:
        component['specialists'] = specialists.copy()
        component['prior_owners'] = []
        component['boundary'] = sorted(set(component['boundary']) | required_paths)
    return components


def hunk_binding(component_ids, component_by_id, hunks_by_path):
    return digest(encoded([
        {'component_id': component_id,
         'hunk_sha256': sorted(value for path in component_by_id[component_id]['files']
                               for value in hunks_by_path.get(path, []))}
        for component_id in sorted(component_ids)
    ]))


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
    result = {'schema_version': 1, 'enabled': enabled, 'snapshot_tree': snapshot, 'base_tree': base_tree,
              'max_shard_bytes': SOURCE_CONTEXT_LIMIT,
              'object_repository': str(repo.object_repository), 'seats': {}}
    artifacts = {}

    source_choice_cache = {}
    def source_choice(path):
        if path in source_choice_cache:
            return source_choice_cache[path]
        choices = [(entries.get(path), snapshot), (base_entries.get(path), base_tree)]
        choices = [(entry, tree) for entry, tree in choices
                   if entry and entry[0] in ('100644', '100755')]
        if not choices:
            source_choice_cache[path] = ('nontext', None)
            return source_choice_cache[path]
        readable = []
        for entry, blob_tree in choices:
            raw = repo.blob(entry)
            if raw is OVERSIZED_BLOB or b'\0' in raw:
                continue
            try:
                raw.decode('utf-8')
            except UnicodeDecodeError:
                continue
            readable.append((entry, raw.splitlines(keepends=True), blob_tree))
        choice = next((value for value in readable if value[1]), readable[0] if readable else None)
        source_choice_cache[path] = ('source' if choice else 'unrepresentable', choice)
        return source_choice_cache[path]

    for seat, assignment in assigned.items():
        component_ids = set(assignment['components'])
        relevant = [component for component in components if component['id'] in component_ids]
        hunk_ids = sorted({value for component in relevant for path in component['files']
                           for value in hunks_by_path.get(path, [])})
        if not enabled:
            result['seats'][seat] = {'role': 'integration' if seat == integration else 'specialist',
                                     'components': sorted(component_ids), 'hunk_sha256': hunk_ids,
                                     'shards': [], 'omitted': {kind: 0 for kind in SOURCE_CONTEXT_REASONS},
                                     'required_source_ranges': [],
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

        def add(kind, reason, path, line_start, line_end, mapped_components):
            ids = sorted(component['id'] for component in mapped_components)
            hashes = {value for component in mapped_components for changed in component['files']
                      for value in hunks_by_path.get(changed, [])}
            if ids and hashes:
                tiers[kind].append({'path': path, 'line_start': line_start, 'line_end': line_end,
                                    'reason': reason, 'component_ids': ids})

        for symbol in evidence['symbols']:
            symbol_components = mapped(symbol['path'])
            if not symbol_components:
                continue
            name = symbol['name'] or 'changed-line-anchor'
            add('declaration', 'declaration:' + name, symbol['path'], symbol['line'], symbol['line_end'],
                symbol_components)
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
            add('gate', 'gate:' + gate['path'] + ':' + str(gate.get('line', 'file')),
                gate['path'], line - 2 if 'line' in gate else 1,
                line + 2 if 'line' in gate else 16, relevant)

        for cluster in plan_clusters or []:
            for site in cluster['paths']:
                site_components = mapped(site['path']) or relevant
                line_start = site['line_start'] or 1
                line_end = site['line_end'] or 16
                add('declaration', 'declaration:plan-site:' + cluster['id'], site['path'],
                    max(1, line_start - 4), line_end + 4, site_components)

        candidates = []
        for kind in SOURCE_CONTEXT_REASONS:
            for row in sorted(tiers[kind], key=lambda item: (item['path'], item['line_start'],
                                                              item['line_end'], item['reason'])):
                row['priority'] = len(candidates)
                candidates.append(row)
        omitted = {kind: 0 for kind in SOURCE_CONTEXT_REASONS}
        required_ranges = []
        source_rows = {}
        nontext_paths = set()
        unrepresentable_paths = set()
        changed_paths = {path for component in relevant for path in component['files']}
        for path in sorted({row['path'] for row in candidates} | changed_paths):
            kind, choice = source_choice(path)
            if kind == 'nontext':
                nontext_paths.add(path)
                continue
            if choice is not None:
                source_rows[path] = choice
            else:
                unrepresentable_paths.add(path)

        prepared = []
        for row in candidates:
            source = source_rows.get(row['path'])
            if not source:
                if row['path'] in nontext_paths:
                    continue
                if seat == integration:
                    raise ValueError('required source range cannot be represented: ' + row['path'])
                omitted[row['reason'].split(':', 1)[0]] += 1
                continue
            entry, lines, blob_tree = source
            start = max(1, row['line_start']); end = min(len(lines), max(start, row['line_end']))
            if not lines or start > len(lines):
                continue
            prepared.append(dict(row, line_start=start, line_end=end, blob_mode=entry[0],
                                 blob_oid=entry[1], blob_tree=blob_tree))

        represented = {component['id'] for component in relevant for row in prepared
                       if row['path'] in component['files']
                       and component['id'] in row['component_ids']}
        required_components = {component['id'] for component in relevant
                               if any(path in unrepresentable_paths
                                      or (path in source_rows and source_rows[path][1])
                                      for path in component['files'])}
        missing = sorted(required_components - represented)
        if seat == integration and missing:
            details = [component['id'] + ':' + ','.join(component['files'])
                       for component in relevant if component['id'] in missing]
            raise ValueError('assigned semantic component has no representable changed-source context: '
                             + ';'.join(details))

        prepared_by_path = {}
        for row in prepared:
            prepared_by_path.setdefault(row['path'], []).append(row)
        merged = []
        for path, rows in sorted(prepared_by_path.items()):
            target = None
            for row in sorted(rows, key=lambda value: (
                    value['line_start'], value['line_end'], value['priority'])):
                if target is None or row['line_start'] > target['line_end']:
                    target = {'path': path, 'line_start': row['line_start'], 'line_end': row['line_end'],
                              'reason_rows': [(row['priority'], row['reason'])],
                              'component_ids': set(row['component_ids']), 'priority': row['priority'],
                              'blob_mode': row['blob_mode'], 'blob_oid': row['blob_oid'],
                              'blob_tree': row['blob_tree']}
                    merged.append(target)
                    continue
                target['line_end'] = max(target['line_end'], row['line_end'])
                target['reason_rows'].append((row['priority'], row['reason']))
                target['component_ids'].update(row['component_ids'])
                target['priority'] = min(target['priority'], row['priority'])

        context_entries = []
        for row in sorted(merged, key=lambda value: value['priority']):
            _, lines, _ = source_rows[row['path']]
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
        shards = []; current = []; current_bytes = 0

        def payload(index, values, count=limit):
            return {'schema_version': 1, 'snapshot_tree': snapshot, 'base_tree': base_tree,
                    'seat': seat, 'shard_index': index, 'shard_count': count, 'entries': values}

        for row in context_entries:
            index = len(shards) + 1
            single_payload_bytes = len(encoded(payload(index, [row])))
            if current:
                continuation_bytes = (len(encoded(payload(index, [{}, row])))
                                      - len(encoded(payload(index, [{}]))))
                trial_bytes = current_bytes + continuation_bytes
            else:
                trial_bytes = single_payload_bytes
            if trial_bytes <= SOURCE_CONTEXT_LIMIT:
                current.append(row)
                current_bytes = trial_bytes
                continue
            if current and len(shards) + 1 < limit:
                shards.append(current); current = []
                index = len(shards) + 1
                single_payload_bytes = len(encoded(payload(index, [row])))
                if single_payload_bytes <= SOURCE_CONTEXT_LIMIT:
                    current = [row]
                    current_bytes = single_payload_bytes
                    continue
            individually_oversized = single_payload_bytes > SOURCE_CONTEXT_LIMIT
            for reason in row['reasons']:
                omitted[reason.split(':', 1)[0]] += 1
            if individually_oversized:
                required = {key: value for key, value in row.items() if key != 'content'}
                required['required_payload_bytes'] = single_payload_bytes
                _, source_lines, _ = source_rows[row['path']]
                required['segments'] = partition_source_segments(
                    source_lines, row['line_start'], row['line_end'])
                required_ranges.append(required)
        if current:
            shards.append(current)
        shard_rows = []
        count = len(shards)
        for index, values in enumerate(shards, 1):
            name = f'{prefix}-{seat}-source-context-{index}.json'
            raw = encoded(payload(index, values, count))
            artifacts[name] = raw
            ranges = [{key: value for key, value in row.items() if key != 'content'} for row in values]
            shard_rows.append({'artifact': name, 'sha256': digest(raw), 'bytes': len(raw),
                               'entries': len(values), 'ranges': ranges})
        result['seats'][seat] = {'role': 'integration' if seat == integration else 'specialist',
                                 'components': sorted(component_ids), 'hunk_sha256': hunk_ids,
                                 'shards': shard_rows, 'omitted': omitted,
                                 'required_source_ranges': sorted(
                                     required_ranges,
                                     key=lambda row: (row['path'], row['line_start'], row['line_end'], row['priority'])),
                                 'source_read_required': any(omitted.values()) or any(
                                     'declaration:changed-line-anchor' in row['reasons']
                                     for row in context_entries)}
    return result, artifacts


def validate_source_context_snapshot(repo, session, manifest):
    """Bind recorded source packet ranges to their exact snapshot blobs."""
    context = manifest['source_context']
    if context['object_repository'] != str(repo.object_repository):
        raise ValueError('source context object storage mismatch')
    entries_by_tree = {}
    blob_lines = {}

    def expected_bytes(row):
        tree = row['blob_tree']
        entries = entries_by_tree.setdefault(tree, repo.entries(tree))
        if entries.get(row['path']) != (row['blob_mode'], row['blob_oid']):
            raise ValueError('source context blob identity mismatch: ' + row['path'])
        key = (row['blob_mode'], row['blob_oid'])
        if key not in blob_lines:
            raw = repo.blob(key)
            if raw is OVERSIZED_BLOB:
                raise ValueError('source context blob is oversized: ' + row['path'])
            blob_lines[key] = raw.splitlines(keepends=True)
        return b''.join(blob_lines[key][row['line_start'] - 1:row['line_end']])

    for packet in context['seats'].values():
        for shard in packet['shards']:
            payload = read_json(session / shard['artifact'])
            for row in payload['entries']:
                if expected_bytes(row) != row['content'].encode():
                    raise ValueError('source context content does not match snapshot: ' + row['path'])
        for row in packet['required_source_ranges']:
            parent = expected_bytes(row)
            key = (row['blob_mode'], row['blob_oid'])
            if row['segments'] != partition_source_segments(
                    blob_lines[key], row['line_start'], row['line_end']):
                raise ValueError('required source segments are not canonical: ' + row['path'])
            rebuilt = b''
            for segment in row['segments']:
                part = expected_bytes(dict(row, line_start=segment['line_start'],
                                           line_end=segment['line_end']))
                if (len(part) != segment['raw_bytes']
                        or digest(part) != segment['content_sha256']
                        or len(part) + (segment['line_end'] - segment['line_start'] + 1) \
                        * SOURCE_SEGMENT_PREFIX_RESERVE != segment['predicted_visible_bytes']):
                    raise ValueError('required source segment does not match snapshot: ' + row['path'])
                rebuilt += part
            if rebuilt != parent or digest(parent) != row['content_sha256']:
                raise ValueError('required source content does not match snapshot: ' + row['path'])


def finding_ownership(session, manifest):
    found = {}
    for seat in manifest['assignments']:
        for finding in read_json(session / f"r{manifest['label']}-{seat}.json")['findings']:
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
    adaptive = not manifest['fallback_reason'] and manifest['phase'] != 'repair'
    if manifest['phase'] == 'plan':
        closure_paths = manifest.get('plan', {}).get('closure_paths', [])
        closure = split_patch((session / f'{prefix}-plan-closure.patch').read_bytes(), closure_paths)
        if (not closure or set(closure) != set(closure_paths)
                or any(path not in full or full[path] != body for path, body in closure.items())):
            raise ValueError('plan closure patch does not match full patch')
        basis = closure
        expected = plan_components_for(basis, edges, ordered, owner, manifest['plan']['clusters'])
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
        if components != plan_components_for(basis, edges, ordered, owner, manifest['plan']['clusters']):
            raise ValueError('plan component routing is not canonical')
    else:
        synthetic = [{'file': c['files'][0], 'owners': c['prior_owners']} for c in components]
        if components != components_for(basis, edges, ordered, owner, synthetic):
            raise ValueError('component routing is not canonical')
    if adaptive and not components:
        raise ValueError('adaptive scope requires semantic components')
    for seat, assignment in assigned.items():
        ids = [c['id'] for c in components if assignment['full_state'] or seat in c['specialists']]
        if assignment.get('components') != ids:
            raise ValueError('assignment component coverage mismatch')
        if not assignment['full_state']:
            paths = {p for c in components if seat in c['specialists'] for p in c['files']}
            if not paths or Path(assignment['patch']).read_bytes() != b''.join(basis[p] for p in sorted(paths)):
                raise ValueError('specialist patch coverage mismatch')
    instruction_directories_by_path = {
        directory.as_posix(): directory for directory in instruction_directories(manifest['paths'])}
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
    if set(context) != {'schema_version', 'enabled', 'snapshot_tree', 'base_tree', 'max_shard_bytes',
                        'object_repository', 'seats'}:
        raise ValueError('invalid source context structure')
    if (context['schema_version'] != 1 or type(context['enabled']) is not bool
            or context['snapshot_tree'] != manifest['snapshot_tree']
            or context['base_tree'] != manifest['base_tree']
            or context['max_shard_bytes'] != SOURCE_CONTEXT_LIMIT
            or context['object_repository'] != str(session / 'evidence-repository')
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
        if not isinstance(packet, dict) or set(packet) != {
                'role', 'components', 'hunk_sha256', 'shards', 'omitted', 'required_source_ranges',
                'source_read_required'}:
            raise ValueError('invalid source context seat: ' + seat)
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
        if not context['enabled'] and (shards or any(omitted.values())):
            raise ValueError('disabled source context contains packet data: ' + seat)
        limit = 3 if seat == owner or manifest['phase'] == 'plan' else 1
        if not isinstance(shards, list) or len(shards) > limit:
            raise ValueError('source context shard count exceeded: ' + seat)
        priorities = []
        for index, shard in enumerate(shards, 1):
            if not isinstance(shard, dict) or set(shard) != {
                    'artifact', 'sha256', 'bytes', 'entries', 'ranges'}:
                raise ValueError('invalid source context shard metadata: ' + seat)
            name = f"r{manifest['label']}-{seat}-source-context-{index}.json"
            if (shard['artifact'] != name or not re.fullmatch(r'[0-9a-f]{64}', str(shard['sha256']))
                    or type(shard['bytes']) is not int or shard['bytes'] > SOURCE_CONTEXT_LIMIT
                    or type(shard['entries']) is not int or shard['entries'] < 1
                    or not isinstance(shard['ranges'], list)):
                raise ValueError('invalid source context shard bounds: ' + seat)
            raw = (session / name).read_bytes()
            if len(raw) != shard['bytes'] or digest(raw) != shard['sha256']:
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
                        or len(entry['content'].splitlines(keepends=True)) != entry['line_end'] - entry['line_start'] + 1
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
                seen_ranges.setdefault((seat, entry['path']), []).append(
                    (entry['line_start'], entry['line_end']))
                ranges.append({key: value for key, value in entry.items() if key != 'content'})
            if ranges != shard['ranges']:
                raise ValueError('source context manifest range mismatch: ' + name)
        if priorities != sorted(priorities) or len(priorities) != len(set(priorities)):
            raise ValueError('source context priority order mismatch: ' + seat)
        required = packet['required_source_ranges']
        range_keys = {'path', 'line_start', 'line_end', 'reasons', 'component_ids', 'hunk_binding_sha256',
                      'blob_oid', 'blob_mode', 'blob_tree', 'content_sha256', 'priority',
                      'required_payload_bytes', 'segments'}
        if (not isinstance(required, list)
                or required != sorted(required, key=lambda row: (
                    row.get('path', ''), row.get('line_start', 0), row.get('line_end', 0), row.get('priority', 0)))):
            raise ValueError('noncanonical required source ranges: ' + seat)
        for row in required:
            component_ids = row.get('component_ids')
            binding_key = tuple(component_ids) if isinstance(component_ids, list) else None
            if (binding_key is not None and binding_key not in binding_cache
                    and set(component_ids) <= set(expected_components)):
                binding_cache[binding_key] = hunk_binding(
                    component_ids, component_by_id, hunk_by_path)
            binding_hash = binding_cache.get(binding_key)
            if (not isinstance(row, dict) or set(row) != range_keys
                    or not within(row.get('path'), manifest['scope'])
                    or type(row.get('line_start')) is not int or type(row.get('line_end')) is not int
                    or row['line_start'] < 1 or row['line_end'] < row['line_start']
                    or type(row.get('priority')) is not int or row['priority'] < 0
                    or row.get('blob_mode') not in ('100644', '100755')
                    or row.get('blob_tree') not in (context['snapshot_tree'], context['base_tree'])
                    or type(row.get('required_payload_bytes')) is not int
                    or row['required_payload_bytes'] <= SOURCE_CONTEXT_LIMIT
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
                            'predicted_visible_bytes', 'content_sha256'}
            if (not isinstance(segments, list) or not segments
                    or [segment.get('index') for segment in segments] != list(range(1, len(segments) + 1))
                    or segments[0].get('line_start') != row['line_start']
                    or segments[-1].get('line_end') != row['line_end']):
                raise ValueError('invalid required source segments: ' + seat)
            cursor = row['line_start']
            for segment in segments:
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
                        or segment['predicted_visible_bytes'] > SOURCE_SEGMENT_VISIBLE_LIMIT
                        or not re.fullmatch(r'[0-9a-f]{64}', str(segment.get('content_sha256')))):
                    raise ValueError('invalid required source segment: ' + seat)
                cursor = segment['line_end'] + 1
            if cursor != row['line_end'] + 1:
                raise ValueError('incomplete required source segments: ' + seat)
            seen_ranges.setdefault((seat, row['path']), []).append((row['line_start'], row['line_end']))
        required_counts = Counter(reason.split(':', 1)[0] for row in required for reason in row['reasons'])
        if any(required_counts[key] > omitted[key] for key in SOURCE_CONTEXT_REASONS):
            raise ValueError('required source ranges exceed omitted identities')
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
    if not isinstance(sets, dict) or type(enabled) is not bool:
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
                or patch_set['patch_lines'] != len(raw.splitlines())
                or patch_set['read_mode'] not in ('chunks', 'windows')
                or not isinstance(patch_set['chunks'], list)):
            raise ValueError('invalid patch set identity: ' + set_id)
        try:
            partitioned = partition_patch_chunks(raw) if enabled else []
        except (UnicodeDecodeError, ValueError):
            partitioned = []
        expected_mode = patch_chunk_mode(raw, partitioned, enabled)
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


def validate_plan(session, manifest, evidence, check_source):
    plan = manifest.get('plan')
    if manifest['schema_version'] != 3 or evidence.get('plan') != plan or not isinstance(plan, dict):
        raise ValueError('invalid plan manifest binding')
    if set(plan) != {'source', 'source_sha256', 'artifact', 'sha256', 'bytes', 'clusters', 'closure_paths'}:
        raise ValueError('invalid plan manifest structure')
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
        if (not isinstance(cluster, dict) or set(cluster) != {
                'id', 'search_pattern', 'search_contract', 'paths'}
                or not isinstance(cluster['id'], str) or not re.fullmatch(r'C-[A-Za-z0-9][A-Za-z0-9-]*', cluster['id'])
                or not isinstance(cluster['search_pattern'], str) or not cluster['search_pattern']
                or not isinstance(cluster['search_contract'], dict)
                or set(cluster['search_contract']) != {'engine', 'domain', 'pattern'}
                or cluster['search_contract'].get('engine') not in ('rg', 'grep-bre')
                or cluster['search_contract'].get('domain') != {
                    'rg': 'rg-default-worktree',
                    'grep-bre': 'grep-recursive-worktree',
                }.get(cluster['search_contract'].get('engine'))
                or cluster['search_contract'].get('pattern') != cluster['search_pattern']
                or not isinstance(cluster['paths'], list) or not cluster['paths']):
            raise ValueError('invalid plan cluster structure')
        ids.append(cluster['id'])
        for row in cluster['paths']:
            line_start = row.get('line_start') if isinstance(row, dict) else None
            line_end = row.get('line_end') if isinstance(row, dict) else None
            valid_lines = ((line_start is None and line_end is None)
                           or (type(line_start) is int and type(line_end) is int
                               and line_start >= 1 and line_end >= line_start))
            if (not isinstance(row, dict) or set(row) != {
                    'path', 'line_start', 'line_end', 'token', 'resolution', 'field'}
                    or not within(row.get('path'), manifest['scope'])
                    or row.get('resolution') not in ('direct', 'basename')
                    or row.get('field') not in ('sites', 'test', 'tests', 'regression')
                    or not isinstance(row.get('token'), str) or not row['token']
                    or not valid_lines):
                raise ValueError('invalid plan cluster path')
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate plan cluster identifier')
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
        entries = set(repo.entries(manifest['snapshot_tree'])) | set(repo.entries(manifest['base_tree']))
        if parse_plan(raw, entries) != clusters:
            raise ValueError('plan cluster parse changed')
        expected_closure = plan_closure_paths(clusters, evidence['dependencies'], manifest['paths'])
        if expected_closure != closure_paths:
            raise ValueError('plan closure dependency mismatch')


def validated_manifest(path, fresh=True, seen=None, offline=False):
    """Validate local evidence; offline mode never accesses Git or predecessor results."""
    try:
        return _validated_manifest(path, fresh, seen, offline)
    except (OSError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as error:
        raise ValueError('invalid manifest: ' + str(error)) from error


def _validated_manifest(path, fresh, seen, offline):
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
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] not in (2, 3) or manifest['session'] != str(session):
        raise ValueError('invalid manifest session/version')
    if any(not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', manifest[key]) for key in ('snapshot_tree', 'base_tree')):
        raise ValueError('invalid manifest tree identifier')
    if not SAFE_NAME.fullmatch(manifest['label']) or path.name != f"r{manifest['label']}-evidence.manifest.json":
        raise ValueError('invalid manifest label')
    if manifest['phase'] not in ('discovery', 'risk', 'verification', 'repair', 'plan'):
        raise ValueError('invalid manifest phase')
    if (manifest['phase'] == 'plan') != (manifest['schema_version'] == 3):
        raise ValueError('manifest phase/version mismatch')
    expected = {f"r{manifest['label']}-{suffix}" for suffix in
                ('full.patch', 'semantic.patch', 'delta.patch', 'evidence.json', 'evidence.md', 'instructions.md')}
    if manifest['phase'] == 'plan':
        expected.update((f"r{manifest['label']}-plan.md", f"r{manifest['label']}-plan-closure.patch"))
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
        suffix = 'full' if mode == 'full' else 'plan-closure' if mode == 'closure' else seat
        expected_path = str(session / f"r{manifest['label']}-{suffix}.patch")
        expected.add(Path(expected_path).name)
        if assignment['patch'] != expected_path or assignment['full_state'] is not (mode == 'full'):
            raise ValueError('assignment patch/full-state mismatch')
        patch = (session / Path(expected_path).name).read_bytes()
        if (assignment.get('patch_sha256') != digest(patch)
                or type(assignment.get('patch_bytes')) is not int or assignment['patch_bytes'] != len(patch)
                or type(assignment.get('patch_lines')) is not int
                or assignment['patch_lines'] != len(patch.splitlines())):
            raise ValueError('assignment patch identity mismatch')
        if assignment.get('bundles') != assignment['bundle'].split('+') or len(set(assignment['bundles'])) != len(assignment['bundles']):
            raise ValueError('assignment bundle list mismatch')
    for packet in manifest['source_context'].get('seats', {}).values():
        for shard in packet.get('shards', []):
            expected.add(shard['artifact'])
    validate_patch_sets(session, manifest, expected)
    if set(manifest['artifacts']) != expected or set(manifest['inputs']) != {'scope.env', 'roster.json', 'files.txt', 'untracked.txt'}:
        raise ValueError('invalid manifest artifact set')
    roster = read_json(session / 'roster.json')
    if not isinstance(roster, dict) or not isinstance(roster.get('seats'), list) or any(not isinstance(s, dict) for s in roster['seats']):
        raise ValueError('invalid roster shape')
    core = {s['seat'] for s in roster['seats'] if not s.get('extra')}
    core_order = [s['seat'] for s in roster['seats'] if not s.get('extra')]
    if not set(assigned) <= core or (manifest['phase'] != 'repair' and set(assigned) != core):
        raise ValueError('assignment roster mismatch')
    adapters = {s['seat']: s.get('adapter', '') for s in roster['seats']}
    if any(a.get('adapter') != adapters[s] for s, a in assigned.items()):
        raise ValueError('assignment adapter mismatch')
    validate_assignment_topology({seat: assigned[seat]['bundle'] for seat in core_order if seat in assigned},
                                 [seat for seat in core_order if seat in assigned], manifest['phase'])
    for name, meta in manifest['artifacts'].items():
        if not isinstance(meta, dict):
            raise ValueError('invalid artifact metadata')
        if Path(name).name != name or digest((session / name).read_bytes()) != meta['sha256']:
            raise ValueError('evidence artifact hash mismatch: ' + name)
        if type(meta.get('words')) is not int or meta['words'] != len((session / name).read_bytes().split()):
            raise ValueError('evidence artifact word count mismatch: ' + name)
    for name, actual in input_hashes(session).items():
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
        if (fallback or not bundle_coverage({s: a['bundle'] for s, a in assigned.items()}, PLAN_BUNDLES)
                or completeness != [owner]):
            raise ValueError('invalid plan assignment coverage')
        if any(a['scope'] != ('full' if seat == owner else 'closure')
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
    words['source_context'] = sum(len((session / shard['artifact']).read_bytes().split())
                                  for packet in manifest['source_context']['seats'].values()
                                  for shard in packet['shards'])
    words['assigned_patch'] = sum(len(Path(a['patch']).read_bytes().split()) for a in assigned.values())
    words['avoided'] = max(0, len(assigned) * words['full'] - words['assigned_patch']
                           - len(assigned) * words['evidence'] - words['source_context'])
    if phase == 'plan':
        words['plan'] = len((session / f'{prefix}-plan.md').read_bytes().split())
        words['closure'] = len((session / f'{prefix}-plan-closure.patch').read_bytes().split())
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
    elif manifest['predecessor'] is not None:
        raise ValueError('predecessor only belongs to delta verification')
    if phase == 'plan':
        validate_plan(session, manifest, evidence, fresh and not offline)
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
        rows, packet = instructions(repo, current, categories, manifest['source']['mode'] == 'worktree')
        if rows != manifest['instructions'] or packet != (session / f'{prefix}-instructions.md').read_bytes():
            raise ValueError('repository instruction coverage mismatch')
        validate_source_context_snapshot(repo, session, manifest)
    return manifest, digest(raw)


def validate_results(session, manifest, manifest_hash):
    result_hashes = {}
    component_by_id = {component['id']: component for component in manifest['components']}
    if manifest['snapshot_unsafe']:
        raise ValueError('unsupported snapshot cannot establish complete coverage')
    if not any(a['full_state'] for a in manifest['assignments'].values()):
        raise ValueError('missing full-state coverage')
    phase = manifest['phase']
    bundles = [a['bundle'] for a in manifest['assignments'].values()]
    if phase == 'repair':
        raise ValueError('standalone repair cannot certify parent panel coverage')
    if phase == 'plan' and not bundle_coverage(
            {s: a['bundle'] for s, a in manifest['assignments'].items()}, PLAN_BUNDLES):
        raise ValueError('plan validation requires all four plan lenses')
    if phase not in ('discovery', 'plan') and not bundle_coverage(
            {s: a['bundle'] for s, a in manifest['assignments'].items()}):
        raise ValueError('coverage requires all four bundles')
    validator = Path(__file__).parent / 'lib' / 'validate-findings.py'
    for seat in manifest['assignments']:
        stem = session / f"r{manifest['label']}-{seat}"
        result = Path(str(stem) + '.json'); exit_path = Path(str(stem) + '.exit')
        prompt = Path(str(stem) + '.prompt.md')
        if exit_path.read_text().strip() != '0':
            raise ValueError('seat failed: ' + seat)
        token = 'Evidence manifest SHA-256: ' + manifest_hash
        if token not in prompt.read_text().splitlines():
            raise ValueError('prompt manifest hash mismatch: ' + seat)
        valid = subprocess.run([sys.executable, str(validator), str(result)], capture_output=True)
        if valid.returncode:
            raise ValueError('invalid result: ' + seat)
        result_data = read_json(result)
        assignment = manifest['assignments'][seat]
        audit_path = Path(str(stem) + '.read-audit.json')
        stream = Path(str(stem) + '.stream.ndjson')
        audit = read_json(audit_path)
        narrow = assignment['scope'] != 'full'
        if (not isinstance(audit, dict) or type(audit.get('schema_version')) is not int or audit['schema_version'] != 2
                or audit.get('status') != 'valid' or audit.get('narrow') is not narrow
                or audit.get('adapter') != assignment['adapter'] or audit.get('violations') != []
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
                or audit['recognized_tool_calls'] < 1 or audit['recognized_tool_calls'] > audit['tool_calls']
                or audit['max_tool_output_bytes'] > audit['tool_output_bytes']
                or audit['packet_bytes'] > audit['tool_output_bytes']
                or audit['assigned_patch_reads'] < 1
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
        if (audit['packet_shards'] != len(opened)
                or audit['packet_bytes'] != sum(shard['bytes'] for shard in opened)
                or audit['packet_ranges'] != len(packet_ranges)
                or audit['opened_source_ranges'] != len(tool_ranges)
                or bool(tool_ranges) != bool(audit['source_read_calls'])
                or (context['source_read_required']
                    and (audit['source_read_calls'] < 1
                         or not (boundary_intersected or required_intersected)
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
            clusters = manifest['plan']['clusters']
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
        for artifact in (audit_path, stream):
            result_hashes[artifact.name] = digest(artifact.read_bytes())
        for artifact in (result, exit_path, prompt):
            result_hashes[artifact.name] = digest(artifact.read_bytes())
    return result_hashes


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
        if validate_results(session, manifest, mh) != receipt['results']:
            raise ValueError('receipt results changed')
        ownership = finding_ownership(session, manifest)
        if receipt.get('findings') != ownership:
            receipt['findings'] = []
            receipt['ownership_fallback_reason'] = 'missing or invalid prior finding ownership'
        repo.tree(receipt['snapshot_tree'])
        return {'status': 'valid', 'coverage': dict(receipt, coverage_reference=head), 'reason': None}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as error:
        return {'status': 'invalid', 'coverage': None,
                'reason': 'invalid coverage predecessor: ' + str(error)}


def prepare(args):
    session = Path(args.session).resolve(); repo = Repository(session)
    roster = read_json(session / 'roster.json')
    if args.phase == 'plan' and any(row.get('adapter') == 'agent' for row in roster.get('seats', [])):
        raise ValueError('agent seat requires legacy full plan panel')
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
    inputs = input_hashes(session)
    for name in ('files.txt', 'untracked.txt'):
        if inputs[name] is not None:
            for path in (session / name).read_text().splitlines():
                if path and not repo.scoped(path):
                    raise ValueError('inventory path outside literal scope: ' + path)
    base_tree = repo.tree(repo.scope['REV_BASE'])
    source = {'mode': 'ref', 'ref': args.head} if args.head else {'mode': 'worktree'}
    unknown_ref = False
    try:
        snapshot, snapshot_unsafe = repo.snapshot(args.head)
    except ValueError:
        if not args.head:
            raise
        snapshot, snapshot_unsafe = repo.snapshot()
        source = {'mode': 'worktree'}
        unknown_ref = True
    patches, hunks, categories, opaque = repo.changes(base_tree, snapshot)
    data = facts(repo, snapshot, hunks, categories)
    plan_clusters = None
    if args.phase == 'plan':
        snapshot_entries = repo.entries(snapshot); base_entries = repo.entries(base_tree)
        plan_entry_map = dict(base_entries); plan_entry_map.update(snapshot_entries)
        plan_clusters = parse_plan(plan_raw, set(plan_entry_map))
        for row in (row for cluster in plan_clusters for row in cluster['paths']):
            if not repo.scoped(row['path']):
                raise ValueError('plan site is outside literal scope: ' + row['path'])
            entry = plan_entry_map[row['path']]
            body = repo.blob(entry)
            if (entry[0] not in ('100644', '100755') or body is OVERSIZED_BLOB or b'\0' in body):
                raise ValueError('plan site is opaque or oversized: ' + row['path'])
            try:
                lines = body.decode('utf-8').splitlines()
            except UnicodeDecodeError as error:
                raise ValueError('plan site is not UTF-8: ' + row['path']) from error
            if row['line_end'] is not None and row['line_end'] > max(1, len(lines)):
                raise ValueError('plan site line range is outside pinned source: ' + row['path'])
        if snapshot_unsafe:
            raise ValueError('unsupported snapshot requires legacy full plan panel')
    data['instructions'], instruction_packet = instructions(repo, snapshot, categories, source['mode'] == 'worktree')
    data.update(hunks=hunks, mechanical={p: c for p, c in categories.items() if c != 'semantic'},
                mechanical_owner=owner)
    prefix = f'r{args.label}'
    full = b''.join(patch for _, patch in patches)
    semantic = b''.join(patch for path, patch in patches if categories[path] == 'semantic')
    packet = markdown(data, session / (prefix + '-evidence.json'))
    prior = (prior_coverage(session, repo, base_tree) if args.phase == 'verification'
             else {'status': 'absent', 'coverage': None, 'reason': None})
    previous = prior['coverage']
    fallback = prior['reason']
    delta = b''; delta_unsafe = []; delta_categories = {}; changes = []
    if previous and args.phase == 'verification':
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
    else:
        fallback = None
    if args.phase == 'risk' and (not bundle_coverage(chosen) or owner is None):
        fallback = 'missing bundle or full-state assignment'
    if snapshot_unsafe:
        fallback = 'snapshot contains unsupported files'; use_delta = False
    if unknown_ref:
        fallback = 'unknown reviewed ref; full current worktree required'; use_delta = False
    if args.phase == 'plan' and fallback:
        raise ValueError('plan evidence requires legacy full fallback: ' + fallback)
    basis = {p: patch for p, patch in (changes if use_delta else patches)
             if (delta_categories if use_delta else categories)[p] == 'semantic'}
    closure_paths = []
    if args.phase == 'plan':
        changed = {path: patch for path, patch in patches}
        closure_paths = plan_closure_paths(plan_clusters, data['dependencies'], changed)
        if not closure_paths:
            raise ValueError('plan closure contains no changed paths')
        if set(closure_paths) & set(opaque):
            raise ValueError('plan closure contains opaque changed paths')
        basis = {path: changed[path] for path in closure_paths}
        closure_raw = b''.join(basis[path] for path in sorted(basis))
        if (len(closure_raw) > PLAN_CLOSURE_MAX_BYTES
                or len(closure_raw) * max(1, len(chosen) - 1) + len(full) > len(full) * len(chosen) * 9 // 10):
            raise ValueError('plan closure is oversized or saves less than 10 percent')
    if not basis and not fallback and args.phase != 'repair':
        fallback = 'no semantic components'; use_delta = False
    components = (plan_components_for(basis, data['dependencies'], chosen, owner, plan_clusters)
                  if args.phase == 'plan' else components_for(
                      basis, data['dependencies'], chosen, owner,
                      previous.get('findings') if use_delta else None))
    scopes = {}
    specialist_artifacts = {}
    patch_bodies = {}
    adapters = {s['seat']: s.get('adapter', '') for s in roster['seats']}
    for seat, bundle in chosen.items():
        mode = 'full' if seat == owner or args.phase == 'repair' else 'semantic'
        if args.phase == 'plan':
            mode = 'full' if seat == owner else 'closure'
        if args.phase == 'verification':
            mode = ('full' if seat == owner else 'delta' if use_delta else 'semantic')
            if fallback:
                mode = 'full'
        if fallback and args.phase != 'verification':
            mode = 'full'
        name = (f'{prefix}-full.patch' if mode == 'full' else
                f'{prefix}-plan-closure.patch' if mode == 'closure' else f'{prefix}-{seat}.patch')
        component_ids = [c['id'] for c in components if mode == 'full' or seat in c['specialists']]
        if mode != 'full':
            paths = {p for c in components if seat in c['specialists'] for p in c['files']}
            specialist_artifacts[name] = b''.join(basis[p] for p in sorted(paths))
        patch_body = full if mode == 'full' else specialist_artifacts[name]
        patch_bodies[seat] = patch_body
        scopes[seat] = {'bundle': bundle, 'bundles': bundle.split('+'), 'scope': mode,
                        'full_state': mode == 'full', 'adapter': adapters[seat], 'components': component_ids,
                        'patch': str(session / name), 'patch_sha256': digest(patch_body),
                        'patch_bytes': len(patch_body), 'patch_lines': len(patch_body.splitlines())}
    chunk_flag = os.environ.get('REV_PATCH_CHUNKS', '0')
    if chunk_flag not in ('0', '1'):
        raise ValueError('REV_PATCH_CHUNKS must be 0 or 1')
    patch_sets, patch_chunk_artifacts = patch_sets_for(
        scopes, patch_bodies, prefix, chunk_flag == '1')
    data['assignments'] = scopes
    predecessor = previous['coverage_reference'] if use_delta else None
    data.update(phase=args.phase, snapshot_tree=snapshot, base_tree=base_tree,
                fallback_reason=fallback, predecessor=predecessor, delta_unsafe=delta_unsafe,
                scope=repo.selected, paths=sorted(categories),
                semantic_paths=sorted(p for p in categories if categories[p] == 'semantic'),
                delta_paths=sorted(p for p in delta_categories if delta_categories[p] == 'semantic'),
                components=components)
    if args.phase == 'plan':
        plan_name = prefix + '-plan.md'
        data['plan'] = {'source': str(plan_source), 'source_sha256': args.plan_sha256,
                        'artifact': plan_name, 'sha256': digest(plan_raw), 'bytes': len(plan_raw),
                        'clusters': plan_clusters, 'closure_paths': closure_paths}
    context_flag = os.environ.get('REV_SOURCE_CONTEXT', '0')
    if context_flag not in ('0', '1'):
        raise ValueError('REV_SOURCE_CONTEXT must be 0 or 1')
    data['source_context'], source_artifacts = source_context(
        repo, snapshot, base_tree, data, components, scopes, owner, prefix, context_flag == '1',
        plan_clusters)
    packet = markdown(data, session / (prefix + '-evidence.json'))
    artifacts = {prefix + '-full.patch': full, prefix + '-semantic.patch': semantic,
                 prefix + '-delta.patch': delta, prefix + '-evidence.json': encoded(data),
                 prefix + '-evidence.md': packet, prefix + '-instructions.md': instruction_packet,
                 **specialist_artifacts, **source_artifacts, **patch_chunk_artifacts}
    if args.phase == 'plan':
        artifacts[prefix + '-plan.md'] = plan_raw
    words = {'full': len(full.split()), 'semantic': len(semantic.split()), 'delta': len(delta.split()),
             'evidence': len(packet.split()) + len(instruction_packet.split())}
    words['source_context'] = sum(len(raw.split()) for raw in source_artifacts.values())
    words['assigned_patch'] = sum(len(artifacts[Path(a['patch']).name].split()) for a in scopes.values())
    words['avoided'] = max(0, len(scopes) * words['full'] - words['assigned_patch']
                           - len(scopes) * words['evidence'] - words['source_context'])
    if args.phase == 'plan':
        words['plan'] = len(plan_raw.split())
        words['closure'] = len(artifacts[prefix + '-plan-closure.patch'].split())
    manifest = {'schema_version': 3 if args.phase == 'plan' else 2, 'session': str(session), 'label': args.label,
                'phase': args.phase, 'snapshot_tree': snapshot, 'base_tree': base_tree,
                'source': source, 'snapshot_unsafe': snapshot_unsafe, 'assignments': scopes,
                'predecessor': predecessor, 'delta_unsafe': delta_unsafe,
                'mechanical_owner': owner, 'mechanical': data['mechanical'], 'fallback_reason': fallback,
                'scope': repo.selected, 'paths': data['paths'], 'semantic_paths': data['semantic_paths'],
                'delta_paths': data['delta_paths'], 'components': components, 'instructions': data['instructions'],
                'source_context': data['source_context'],
                'patch_chunks_enabled': chunk_flag == '1', 'patch_sets': patch_sets,
                'word_counts': words, 'inputs': inputs,
                'artifacts': {name: {'sha256': digest(raw), 'words': len(raw.split())} for name, raw in artifacts.items()}}
    if args.phase == 'plan':
        manifest['plan'] = data['plan']
    manifest_path = session / (prefix + '-evidence.manifest.json')
    receipt_path = session / (prefix + '-coverage.receipt.json')
    if receipt_path.exists() and (not manifest_path.exists() or manifest_path.read_bytes() != encoded(manifest)):
        raise ValueError('cannot replace an already receipted manifest')
    for name, raw in artifacts.items():
        publish(session / name, raw)
    publish(manifest_path, encoded(manifest))
    print(manifest_path)


def render(args):
    manifest, mh = validated_manifest(args.manifest, fresh=not args.offline, offline=args.offline)
    assignment = manifest['assignments'].get(args.seat)
    if assignment is None:
        raise ValueError('seat not assigned')
    expected_plan = (Path(manifest['session']) / manifest['plan']['artifact']
                     if manifest['phase'] == 'plan' else None)
    if expected_plan is None:
        if args.plan_source:
            raise ValueError('--plan-source belongs only to plan evidence')
    elif not args.plan_source or Path(args.plan_source).resolve() != expected_plan:
        raise ValueError('plan evidence requires its immutable plan snapshot')
    print('Evidence manifest SHA-256: ' + mh)
    print('Assigned scope: ' + assignment['scope'])
    print('Assigned risk bundle: ' + assignment['bundle'])
    if manifest['phase'] == 'plan':
        plan = manifest['plan']
        print('Immutable plan snapshot: ' + str(Path(manifest['session']) / plan['artifact'])
              + ' SHA-256 ' + plan['sha256'])
        for cluster in plan['clusters']:
            print('Required cluster sibling search: ' + cluster['id'] + ' engine '
                  + cluster['search_contract']['engine'] + ' domain '
                  + cluster['search_contract']['domain'] + ' pattern '
                  + json.dumps(cluster['search_pattern'], ensure_ascii=True) + ' from repository root')
            for row in cluster['paths']:
                location = row['path']
                if row['line_start'] is not None:
                    location += ':' + str(row['line_start'])
                    if row['line_end'] != row['line_start']:
                        location += '-' + str(row['line_end'])
                print('Required cluster source: ' + cluster['id'] + ' ' + location
                      + ' resolution ' + row['resolution'] + ' field ' + row['field'])
    patch_mode = assignment['patch_read_mode']
    print('Assigned patch read mode: ' + patch_mode)
    if patch_mode == 'chunks':
        patch_set = manifest['patch_sets'][assignment['patch_set']]
        batch_limit = 2 if assignment['adapter'] in ('claude', 'grok') else 1
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
            print('First assigned-patch action: run ' + shlex.join(['cat', '--', first])
                  + '; then read one listed chunk per command in exact order.')
        else:
            tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
            print('First assigned-patch action: use ' + tool + ' to read '
                  + str(batch_limit) + ' consecutive listed chunk'
                  + ('' if batch_limit == 1 else 's') + ' in full; continue in exact order.')
    else:
        print('Read the entire assigned patch in bounded windows of at most 240 lines: '
              + assignment['patch'])
        if assignment['adapter'] == 'codex':
            end = min(240, assignment['patch_lines'])
            print("First assigned-patch action: run sed -n '1," + str(end) + "p' "
                  + shlex.quote(assignment['patch'])
                  + '; continue with consecutive windows of at most 240 lines.')
        else:
            tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
            print('First assigned-patch action: use ' + tool
                  + ' with offset 1 and limit 240 on ' + assignment['patch']
                  + '; continue with consecutive windows.')
    print('Evidence navigation index: ' + str(Path(manifest['session']) / f"r{manifest['label']}-evidence.md"))
    print('Read applicable repository instructions: ' + str(Path(manifest['session']) / f"r{manifest['label']}-instructions.md"))
    context = manifest['source_context']['seats'][args.seat]
    print('Source context enabled: ' + str(manifest['source_context']['enabled']).lower())
    if manifest['source_context']['enabled']:
        for shard in context['shards']:
            print('Source context packet: ' + str(Path(manifest['session']) / shard['artifact']))
        for row in context['required_source_ranges']:
            print('Required source range: ' + row['path'] + ':' + str(row['line_start']) + '-'
                  + str(row['line_end']) + ' tree ' + row['blob_tree'] + ' blob ' + row['blob_oid']
                  + ' content SHA-256 '
                  + row['content_sha256'] + ' reasons ' + json.dumps(row['reasons'], ensure_ascii=True))
            total = len(row['segments'])
            for segment in row['segments']:
                command = ('git --git-dir=' + shlex.quote(
                    manifest['source_context']['object_repository'])
                           + " show '" + row['blob_oid'] + "' | sed -n '"
                           + str(segment['line_start']) + ',' + str(segment['line_end']) + "p'")
                print('Required source segment ' + str(segment['index']) + '/' + str(total)
                      + ': run ' + command + ' raw bytes ' + str(segment['raw_bytes'])
                      + ' visible bytes ' + str(segment['predicted_visible_bytes'])
                      + ' content SHA-256 ' + segment['content_sha256'])
            batch_limit = 2 if assignment['adapter'] in ('claude', 'grok') else 1
            print('Required source segment batch limit: ' + str(batch_limit))
        print('Source read required: ' + str(context['source_read_required']).lower())
    else:
        print('Source read required: true')
    print('Mechanical owner: ' + str(manifest['mechanical_owner']))
    print('Open original source to prove each finding; expand beyond this index when needed.')


def verify(args):
    manifest, mh = validated_manifest(args.manifest)
    print(str(Path(manifest['session']) / f"r{manifest['label']}-evidence.manifest.json") + ' ' + mh)


def verify_panel_data(session, label):
    manifest_path = session / f'r{label}-evidence.manifest.json'
    manifest, mh = validated_manifest(manifest_path)
    results = validate_results(session, manifest, mh)
    validated_manifest(manifest_path)
    return manifest, mh, results


def verify_panel(args):
    session = Path(args.session).resolve()
    manifest, mh, results = verify_panel_data(session, args.label)
    print(json.dumps({'manifest': f'r{args.label}-evidence.manifest.json',
                      'manifest_sha256': mh, 'phase': manifest['phase'],
                      'results': results}, sort_keys=True, separators=(',', ':')))


def receipt(args):
    session = Path(args.session).resolve()
    manifest_path = session / f'r{args.label}-evidence.manifest.json'
    manifest, mh, results = verify_panel_data(session, args.label)
    if manifest['phase'] == 'plan':
        raise ValueError('plan panels never advance code coverage')
    data = {'schema_version': 1, 'manifest': manifest_path.name, 'manifest_sha256': mh,
            'snapshot_tree': manifest['snapshot_tree'], 'base_tree': manifest['base_tree'],
            'phase': manifest['phase'], 'assignments': manifest['assignments'], 'results': results,
            'findings': finding_ownership(session, manifest)}
    path = session / f'r{args.label}-coverage.receipt.json'; raw = encoded(data)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('coverage receipt is immutable')
    else:
        publish(path, raw)
    publish(session / 'coverage-head.json', encoded({'receipt': path.name, 'sha256': digest(raw)}))
    print(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('session'); prep.add_argument('label')
    prep.add_argument('--phase', required=True, choices=('discovery', 'risk', 'verification', 'repair', 'plan'))
    prep.add_argument('--head'); prep.add_argument('--assignment', action='append', default=[])
    prep.add_argument('--full-seat')
    prep.add_argument('--plan'); prep.add_argument('--plan-sha256')
    rend = commands.add_parser('render'); rend.add_argument('manifest'); rend.add_argument('seat')
    rend.add_argument('--offline', action='store_true')
    rend.add_argument('--plan-source')
    check = commands.add_parser('verify'); check.add_argument('manifest')
    panel = commands.add_parser('verify-panel'); panel.add_argument('session'); panel.add_argument('label')
    rec = commands.add_parser('receipt'); rec.add_argument('session'); rec.add_argument('label')
    args = parser.parse_args()
    try:
        if hasattr(args, 'label') and not SAFE_NAME.fullmatch(args.label):
            raise ValueError('invalid label')
        {'prepare': prepare, 'render': render, 'verify': verify,
         'verify-panel': verify_panel, 'receipt': receipt}[args.command](args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as error:
        print('evidence: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
