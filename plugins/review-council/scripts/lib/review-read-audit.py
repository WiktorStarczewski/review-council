#!/usr/bin/env python3
"""Enforce bounded reviewer reads as a hook or audit an adapter NDJSON stream."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import sys
import tempfile

LIB_DIR = Path(__file__).resolve().parent
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))
from review_limits import READ_LINES, REPOSITORY_EXPANSION_CALL_LIMIT
SEARCH_RESULTS = 80
SEARCH_RESULT_SENTINEL = SEARCH_RESULTS + 1
OUTPUT_BYTES = 32 * 1024
PATCH_TURN_OUTPUT_BYTES = 60 * 1024
# Pacing codes count byte-proved reads after the fact and never withdraw credit from them.
PACING_CODES = {
    'patch-chunk-batch-too-large', 'required-source-segment-batch-too-large',
    'evidence-proof-batch-too-large', 'source-packet-batch-too-large',
}
ADVISORY_CODES = PACING_CODES | {
    'discovery-output-too-large', 'duplicate-patch-chunk', 'duplicate-required-source-segment',
    'evidence-read-order',
    'missing-evidence-index', 'repository-expansion-call-limit',
    'redundant-assigned-patch-read', 'source-output-mismatch', 'unbounded-shell-output',
    'unsupported-source-range',
    'tool-output-too-large', 'tool-turn-output-too-large', 'unbounded-read', 'unbounded-search',
    'unsupported-source-batch', 'source-batch-lines-too-large', 'overlapping-source-batch',
    'source-batch-output-mismatch',
}
CLAUDE_EMPTY_READ = '<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>'
READ_TOOLS = {'read', 'read_file'}
SEARCH_TOOLS = {'grep', 'search_file_content', 'search_files', 'code_search'}
SHELL_TOOLS = {'bash', 'shell', 'run_shell_command', 'run_terminal_command', 'command_execution'}
DISCOVERY_TOOLS = {'glob', 'list_directory'}
RECOGNIZED_TOOLS = READ_TOOLS | SEARCH_TOOLS | SHELL_TOOLS | DISCOVERY_TOOLS
TERMINAL_TOOLS = {'structuredoutput'}
SOURCE_PACKET_NAME = re.compile(r'^r[0-9A-Za-z._-]+-source-context-[1-9][0-9]*\.json$')
SOURCE_SEGMENT_NAME = re.compile(
    r'^r[0-9A-Za-z._-]+-[0-9A-Za-z._-]+-source-segment-[0-9]{3}-[0-9]{3}\.txt$')
PATCH_CHUNK_NAME = re.compile(r'^r[0-9A-Za-z._-]+-patch-p[0-9]{2}-[0-9]{3}\.txt$')
FULL_ARTIFACT = re.compile(r'^r[0-9A-Za-z._-]+(?:-[0-9A-Za-z._-]+)?\.prompt\.md$|^r[0-9A-Za-z._-]+-(?:evidence|instructions|plan)\.md$')
SESSION_ARTIFACT = re.compile(r'^r[0-9A-Za-z._-]+(?:-[0-9A-Za-z._-]+)?(?:\.prompt\.md|\.patch)$|^r[0-9A-Za-z._-]+-(?:evidence|instructions|plan)\.(?:md|json)$')
EVIDENCE_MANIFEST_PREFIX = 'Evidence manifest SHA-256:'
EVIDENCE_MANIFEST_DECLARATION = re.compile(
    r'Evidence manifest SHA-256: ([0-9a-f]{64})')
PROMPT_ARTIFACT_PREFIXES = (
    'Canonical assigned patch:', 'Assigned patch chunk ', 'Evidence navigation index:',
    'Source context packet:', 'Required source segment ', 'Exact frozen assigned patch:',
    'Read the entire assigned patch in bounded windows',
)
SEARCH_COMMANDS = {'rg', 'ripgrep', 'ag', 'grep', 'egrep', 'fgrep'}
DISCOVERY_COMMANDS = {'find', 'ls', 'tree', 'fd'}
CONTENT_COMMANDS = {
    'cat', 'less', 'more', 'awk', 'nl', 'sort', 'uniq', 'cut', 'jq', 'yq',
    'bat', 'strings', 'xxd', 'od', 'diff', 'head', 'tail', 'sed',
}
UNSUPPORTED_FILE_COMMANDS = {'column', 'paste', 'comm'}
PINNED_OBJECT = re.compile(r'([0-9a-f]{40}|[0-9a-f]{64}):(.+)')
# macOS /usr/bin/git is an xcrun shim; inside the codex sandbox it prints these on stderr before
# git runs, and codex merges stderr into the command output.
XCRUN_DIAGNOSTIC = re.compile(
    r'(?:\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ xcodebuild\[\d+:\d+\] |git: (?:warning|error): )[^\n]*\n')
METADATA_COMMANDS = {
    ':', '[', 'basename', 'cd', 'date', 'df', 'dirname', 'du', 'echo', 'env', 'false',
    'file', 'git', 'md5', 'printf', 'pwd', 'read', 'readlink', 'realpath', 'shasum',
    'shasum256', 'sleep', 'stat', 'test', 'tr', 'true', 'type', 'wc', 'which',
}
SOURCE_COMMANDS = SEARCH_COMMANDS | DISCOVERY_COMMANDS | CONTENT_COMMANDS


def load_readonly_policy():
    path = Path(__file__).with_name('readonly-bash-guard.py')
    spec = importlib.util.spec_from_file_location('review_council_readonly_bash_guard', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load read-only shell policy')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


READONLY_POLICY = load_readonly_policy()
if READONLY_POLICY.READ_CMDS != (SOURCE_COMMANDS | UNSUPPORTED_FILE_COMMANDS | METADATA_COMMANDS):
    raise RuntimeError('read-only shell command classification is incomplete')
_EVIDENCE_MODULE = None


def _load_evidence_module():
    global _EVIDENCE_MODULE
    if _EVIDENCE_MODULE is None:
        script = Path(__file__).resolve().parent.parent / 'rev-evidence.py'
        spec = importlib.util.spec_from_file_location('review_council_audit_evidence', script)
        if spec is None or spec.loader is None:
            raise ValueError('evidence validator unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _EVIDENCE_MODULE = module
    return _EVIDENCE_MODULE


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolved(path, cwd):
    value = os.path.expandvars(os.path.expanduser(str(path)))
    if re.search(r'\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[^}]*\})', value):
        raise ValueError('unresolved path variable')
    item = Path(value)
    if any(len(os.fsencode(part)) > 255 for part in item.parts):
        raise OSError('path component exceeds portable filesystem limit')
    return (item if item.is_absolute() else Path(cwd) / item).resolve(strict=False)


def inside(path, roots):
    return any(path == root or root in path.parents for root in roots)


def full_artifact(path, session):
    return session is not None \
        and bool(FULL_ARTIFACT.fullmatch(path.name) or SOURCE_PACKET_NAME.fullmatch(path.name)) \
        and path.parent == session


def complete_read_artifact(path, session):
    return full_artifact(path, session) or (
        session is not None
        and bool(PATCH_CHUNK_NAME.fullmatch(path.name) or SOURCE_SEGMENT_NAME.fullmatch(path.name))
        and path.parent == session)


def session_artifact(path, session):
    return session is not None \
        and bool(SESSION_ARTIFACT.fullmatch(path.name) or SOURCE_PACKET_NAME.fullmatch(path.name)
                 or PATCH_CHUNK_NAME.fullmatch(path.name) or SOURCE_SEGMENT_NAME.fullmatch(path.name)) \
        and path.parent == session


def prompt_permissions(prompt, root, session):
    """Return exact prompt-authorized paths and paths that may be read in full."""
    prompt = Path(prompt).resolve()
    authorized = {prompt}
    complete = {prompt}
    try:
        lines = prompt.read_text().splitlines()
    except OSError:
        return authorized, complete
    try:
        scope_start = lines.index('## Scope') + 1
    except ValueError:
        scope_start = 0
        scope_end = len(lines)
    else:
        scope_end = next((index for index in range(scope_start, len(lines))
                          if lines[index].startswith('## ')), len(lines))
    documents = False
    for line in lines[scope_start:scope_end]:
        if line == 'Documents to review (read them in full):':
            documents = True
            continue
        if documents:
            if line.startswith('- '):
                try:
                    path = resolved(line[2:], root)
                except (OSError, ValueError):
                    continue
                authorized.add(path)
                complete.add(path)
                continue
            if line:
                documents = False
        if not line.startswith(PROMPT_ARTIFACT_PREFIXES):
            continue
        matches = re.findall(
            r'(?<![0-9A-Za-z.])(/.*?)(?= SHA-256| bytes(?: |$)| raw bytes| in full(?: |$)|; continue|$)',
            line)
        if not matches:
            continue
        try:
            path = resolved(matches[-1], root)
        except (OSError, ValueError):
            continue
        if path.parent != session:
            continue
        authorized.add(path)
        if (FULL_ARTIFACT.fullmatch(path.name) or SOURCE_PACKET_NAME.fullmatch(path.name)
                or PATCH_CHUNK_NAME.fullmatch(path.name) or SOURCE_SEGMENT_NAME.fullmatch(path.name)):
            complete.add(path)
    return authorized, complete


def validate_prompt_artifact_set(manifest, seat, prompt, root, session):
    """Reject schema-4 plan prompts that authorize the wrong session artifacts."""
    if not isinstance(manifest, dict):
        return
    if manifest.get('schema_version') != 4 or manifest.get('phase') != 'plan':
        return
    session = Path(session).resolve()
    prompt = Path(prompt).resolve()
    if Path(manifest.get('session', '')).resolve() != session:
        raise ValueError('prompt session does not match the evidence manifest')
    try:
        names = (manifest['assignments'][seat]['required_artifacts']
                 + manifest['plan']['common_artifacts'])
    except (KeyError, TypeError) as error:
        raise ValueError('prompt artifact contract is missing') from error
    if (not all(isinstance(name, str) and name and Path(name).name == name for name in names)
            or len(names) != len(set(names))):
        raise ValueError('prompt artifact contract is invalid')
    expected = {session / name for name in names}
    authorized, _ = prompt_permissions(prompt, root, session)
    actual = {path for path in authorized if path != prompt and path.parent == session}
    if actual != expected:
        missing = sorted(path.name for path in expected - actual)
        surplus = sorted(path.name for path in actual - expected)
        detail = []
        if missing:
            detail.append('missing ' + ','.join(missing))
        if surplus:
            detail.append('surplus ' + ','.join(surplus))
        raise ValueError('prompt artifact authorization mismatch: ' + '; '.join(detail))


def evidence_manifest_declaration(prompt_lines):
    declarations = [line for line in prompt_lines if line.startswith(EVIDENCE_MANIFEST_PREFIX)]
    if not declarations:
        return False, None
    if len(declarations) != 1:
        return True, None
    match = EVIDENCE_MANIFEST_DECLARATION.fullmatch(declarations[0])
    return True, match.group(1) if match is not None else None


def validate_prompt(args):
    """Validate the manifest once, then bind each --seat to the --prompt at the same position."""
    root = Path(args.root).resolve()
    session = Path(args.session).resolve()
    manifest_path = Path(args.manifest).resolve()
    if len(args.seat) != len(args.prompt) or len(set(args.seat)) != len(args.seat):
        raise ValueError('prompts need one distinct seat each')
    prompts = [Path(prompt).resolve() for prompt in args.prompt]
    for prompt in prompts:
        try:
            metadata = prompt.lstat()
        except OSError as error:
            raise ValueError('prompt is unavailable') from error
        if prompt.is_symlink() or not prompt.is_file() or metadata.st_nlink != 1:
            raise ValueError('prompt must be one regular file')
    manifest, manifest_hash = _load_evidence_module().validated_manifest(
        manifest_path, replay_plan_searches=False)
    if Path(manifest['session']).resolve() != session:
        raise ValueError('prompt session does not match the evidence manifest')
    for seat, prompt in zip(args.seat, prompts):
        try:
            validate_seat_prompt(manifest, manifest_hash, seat, prompt, root, session)
        except ValueError as error:
            raise ValueError(seat + ': ' + str(error)) from error
    for prompt in prompts:
        print(prompt)
    return 0


def validate_seat_prompt(manifest, manifest_hash, seat, prompt, root, session):
    if seat not in manifest['assignments']:
        raise ValueError('prompt seat is absent from evidence manifest')
    lines = prompt.read_text().splitlines()
    if lines.count('## Scope') != 1:
        raise ValueError('prompt must contain exactly one scope heading')
    evidence_scoped, declared_hash = evidence_manifest_declaration(lines)
    if not evidence_scoped or declared_hash != manifest_hash:
        raise ValueError('prompt does not bind the evidence manifest exactly once')
    validate_assignment_prompt_binding(manifest, seat, lines)
    validate_plan_prompt_binding(manifest, seat, prompt, _load_evidence_module())
    validate_prompt_artifact_set(manifest, seat, prompt, root, session)


def session_path_allowed(path, session, authorized, dependency=None):
    if session is None or authorized is None or not (path == session or session in path.parents):
        return True
    if path in authorized:
        return True
    return dependency is not None and (path == dependency or dependency in path.parents)


def complete_path_allowed(path, session, complete):
    return path in complete if complete is not None else complete_read_artifact(path, session)


def allowed_roots(root, session=None, deps=None):
    roots = [Path(root).resolve()]
    if session:
        roots.append(Path(session).resolve())
    if deps:
        dependency_dir = Path(deps).resolve()
        roots.append(dependency_dir)
        if dependency_dir.is_dir():
            for child in dependency_dir.iterdir():
                try:
                    roots.append(child.resolve(strict=True))
                except OSError:
                    continue
    return roots


def violation(code, tool):
    return {'code': code, 'tool': tool}


def tool_path(data):
    for key in ('file_path', 'path', 'target_file', 'absolute_path', 'glob'):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def positive_bound(data, keys, maximum):
    for key in keys:
        if key in data:
            value = data[key]
            if isinstance(value, bool):
                return False
            try:
                value = int(value)
            except (TypeError, ValueError):
                return False
            return 1 <= value <= maximum
    return False


def explicit_offset(data):
    for key in ('offset', 'start_line', 'line_start'):
        if key in data:
            value = data[key]
            if isinstance(value, bool):
                return False
            try:
                return int(value) >= 1
            except (TypeError, ValueError):
                return False
    return False


def split_shell(text):
    parts = []
    current = []
    quote = None
    escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if escaped:
            current.append(char)
            escaped = False
            i += 1
            continue
        if char == '\\' and quote != "'":
            current.append(char)
            escaped = True
            i += 1
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            i += 1
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            i += 1
            continue
        pair = text[i:i + 2]
        if pair in ('&&', '||'):
            parts.append((''.join(current).strip(), pair))
            current = []
            i += 2
            continue
        if char in ('|', ';', '\n'):
            parts.append((''.join(current).strip(), char))
            current = []
            i += 1
            continue
        current.append(char)
        i += 1
    if quote:
        raise ValueError('unbalanced shell quote')
    parts.append((''.join(current).strip(), ''))
    return [(part, separator) for part, separator in parts if part]


def strip_shell_comments(text):
    """Drop what the shell never executes: an unquoted `#` that starts a word, to end of line.

    Reviewers annotate calls with a comment line, and a quote or `<` inside that comment
    must not decide how the executed command is judged."""
    kept = []
    quote = None
    escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if escaped:
            escaped = False
        elif char == '\\' and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == '#' and (i == 0 or text[i - 1] in ' \t\n;&|()'):
            while i < len(text) and text[i] != '\n':
                i += 1
            continue
        kept.append(char)
        i += 1
    return ''.join(kept)


def unwrap_shell(command):
    try:
        words = shlex.split(command)
    except ValueError:
        return strip_shell_comments(command)
    if len(words) == 3 and Path(words[0]).name in ('bash', 'sh', 'zsh', 'dash', 'ksh') and words[1] in ('-c', '-lc'):
        return strip_shell_comments(words[2])
    return strip_shell_comments(command)


def contains_unquoted(text, needle):
    quote = None
    escaped = False
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == '\\' and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == needle:
            return True
    return False


def command_words(segment):
    words = shlex.split(segment)
    while words:
        if '=' in words[0] and not words[0].startswith(('/', './', '../')):
            key = words[0].split('=', 1)[0]
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
                words.pop(0)
                continue
        name = Path(words[0]).name
        if words[0] == '!' or name in ('command', 'time', 'nice'):
            words.pop(0)
            continue
        if name == 'env':
            words.pop(0)
            while words and ('=' in words[0] or words[0].startswith('-')):
                words.pop(0)
            continue
        break
    return words


def path_candidates(words, root):
    candidates = []
    pattern_indexes = search_pattern_indexes(words)
    for index, token in enumerate(words[1:], 1):
        if index in pattern_indexes:
            continue
        if token in ('-', '--') or token.startswith(('http://', 'https://')) or '>/dev/null' in token:
            continue
        value = token.split('=', 1)[1] if token.startswith('--') and '=' in token else token
        if value.startswith('-') or re.fullmatch(r'\d+(?:,\d+)?[a-zA-Z]*', value):
            continue
        looks_like_path = value.startswith(('/', '~', './', '../', '$')) or '/' in value
        if not looks_like_path:
            try:
                looks_like_path = (Path(root) / value).exists()
            except OSError:
                looks_like_path = False
        if looks_like_path:
            candidates.append(value)
    return candidates


def search_pattern_indexes(words):
    if not words or Path(words[0]).name not in SEARCH_COMMANDS:
        return set()
    value_options = {
        '-A', '-B', '-C', '-g', '-m', '-t', '-T', '--after-context', '--before-context',
        '--context', '--encoding', '--glob', '--max-count', '--type', '--type-not',
    }
    patterns = set(); explicit = False; positional = False; index = 1
    while index < len(words):
        value = words[index]
        if value in ('-e', '--regexp'):
            if index + 1 < len(words):
                patterns.add(index + 1)
            explicit = True; index += 2; continue
        if value.startswith('--regexp='):
            explicit = True; index += 1; continue
        if value in value_options:
            index += 2; continue
        if value.startswith('-'):
            index += 1; continue
        if not explicit and not positional:
            patterns.add(index); positional = True
        index += 1
    return patterns


def line_limiter(words, maximum=READ_LINES):
    if not words:
        return False
    name = Path(words[0]).name
    if name == 'fd':
        value = None
        for index, word in enumerate(words[1:], 1):
            if word in ('--max-results', '--max-result') and index + 1 < len(words):
                if re.fullmatch(r'[0-9]+', words[index + 1]) is None:
                    return False
                value = int(words[index + 1])
            elif word.startswith(('--max-results=', '--max-result=')):
                raw = word.split('=', 1)[1]
                if re.fullmatch(r'[0-9]+', raw) is None:
                    return False
                value = int(raw)
        return value is not None and 1 <= value <= maximum
    if name in SEARCH_COMMANDS:
        value = None
        for index, word in enumerate(words[1:], 1):
            if word in ('-m', '--max-count') and index + 1 < len(words):
                if re.fullmatch(r'[0-9]+', words[index + 1]) is None:
                    return False
                value = int(words[index + 1])
            elif word.startswith('--max-count='):
                raw = word.split('=', 1)[1]
                if re.fullmatch(r'[0-9]+', raw) is None:
                    return False
                value = int(raw)
            elif re.fullmatch(r'-m[0-9]+', word):
                value = int(word[2:])
        return value is not None and 1 <= value <= maximum
    if name in ('head', 'tail'):
        value = None
        for index, word in enumerate(words[1:], 1):
            if re.fullmatch(r'-\d+', word):
                value = int(word[1:])
            elif word in ('-n', '--lines') and index + 1 < len(words):
                if re.fullmatch(r'[0-9]+', words[index + 1]) is None:
                    return False
                value = int(words[index + 1])
            elif word.startswith('--lines='):
                raw = word.split('=', 1)[1]
                if re.fullmatch(r'[0-9]+', raw) is None:
                    return False
                value = int(raw)
        return value is not None and 1 <= value <= maximum
    if name == 'sed' and '-n' in words:
        for word in words[1:]:
            match = re.fullmatch(r'(\d+),(\d+)p', word)
            if match and 0 <= int(match.group(2)) - int(match.group(1)) < maximum:
                return True
    return False


def limiter_range(words, total_lines=None, maximum=READ_LINES):
    if not words:
        return None
    name = Path(words[0]).name
    if name == 'sed' and '-n' in words:
        for word in words[1:]:
            match = re.fullmatch(r'(\d+),(\d+)p', word)
            if match and 0 <= int(match.group(2)) - int(match.group(1)) < maximum:
                return int(match.group(1)), int(match.group(2))
        return None
    if name not in ('head', 'tail'):
        return None
    count = None
    for index, word in enumerate(words[1:], 1):
        if re.fullmatch(r'-\d+', word):
            count = int(word[1:])
        elif word in ('-n', '--lines') and index + 1 < len(words) \
                and re.fullmatch(r'[0-9]+', words[index + 1]):
            count = int(words[index + 1])
        elif word.startswith('--lines=') and re.fullmatch(r'[0-9]+', word.split('=', 1)[1]):
            count = int(word.split('=', 1)[1])
    if count is None or not 1 <= count <= maximum:
        return None
    if name == 'head':
        return 1, count
    if total_lines is None:
        return None
    return max(1, total_lines - count + 1), total_lines


def cached_file(path, cache=None):
    path = Path(path).resolve()
    if cache is not None and path in cache:
        return cache[path]
    raw = path.read_bytes()
    value = raw, split_lf_lines(raw)
    if cache is not None:
        cache[path] = value
    return value


def file_line_count(path, cache=None):
    raw, _ = cached_file(path, cache)
    return raw.count(b'\n') + (1 if raw and not raw.endswith(b'\n') else 0)


def repository_file_candidates(words, root, session=None):
    found = []
    for candidate in path_candidates(words, root):
        try:
            target = resolved(candidate, root)
            target.relative_to(root)
        except (OSError, ValueError):
            continue
        if session_artifact(target, session):
            continue
        try:
            if target.is_file():
                found.append(target)
        except OSError:
            continue
    return found


def canonical_range(path, start, end, root, origin='tool', cache=None):
    try:
        relative = path.relative_to(root).as_posix()
        total = file_line_count(path, cache)
    except (OSError, ValueError):
        return None
    start = max(1, start)
    end = min(end, total)
    if start > end:
        return None
    return {'path': relative, 'line_start': start, 'line_end': end, 'origin': origin}


def pinned_object_read(pipeline):
    """Parse `git show <full oid>:<path> | sed -n 'A,Bp'` (or `| head -n N`) into its oid and range.

    The limiter must read only the pipe: a file operand would make it print another file."""
    if len(pipeline) != 2 or not pipeline[0] or Path(pipeline[0][0]).name != 'git':
        return None
    words = pipeline[0][1:]
    if words[:1] == ['--no-pager']:
        words = words[1:]
    match = PINNED_OBJECT.fullmatch(words[1]) if len(words) == 2 and words[0] == 'show' else None
    if match is None or posixpath.normpath(match.group(2)) != match.group(2) \
            or match.group(2).startswith(('/', '../')) or match.group(2) == '..':
        return None
    limiter = pipeline[1]
    options = limiter[1:]
    if not limiter or Path(limiter[0]).name not in ('sed', 'head') \
            or len(options) != sum(1 for word in options if word.startswith('-')
                                   or re.fullmatch(r'\d+(?:,\d+p)?', word)):
        return None
    selected = limiter_range(limiter)
    if selected is None:
        return None
    return match.group(1), match.group(2), selected[0], selected[1]


def shell_source_ranges(command, root, cache=None, session=None):
    """Return exact current-source ranges and whether a source read was unparseable.

    A pinned-object read carries its oid as `tree`; the audit verifies it against that frozen
    tree alone and grants no range for any object but the manifest snapshot tree."""
    try:
        parts = split_shell(unwrap_shell(command))
        parsed = [(command_words(part), separator) for part, separator in parts]
    except ValueError:
        return [], True
    pipelines = []
    current = []
    for words, separator in parsed:
        current.append(words)
        if separator != '|':
            pipelines.append(current)
            current = []
    if current:
        pipelines.append(current)
    ranges = []
    unparseable = False
    direct_source = {'cat', 'less', 'more', 'awk', 'nl', 'bat', 'strings', 'xxd', 'od', 'sed', 'head', 'tail'}
    transparent = {'cat'}
    for pipeline in pipelines:
        pinned = pinned_object_read(pipeline)
        if pinned is not None:
            ranges.append({'path': pinned[1], 'line_start': pinned[2], 'line_end': pinned[3],
                           'origin': 'tool', 'tree': pinned[0]})
            continue
        for position, words in enumerate(pipeline):
            if not words or Path(words[0]).name not in direct_source:
                continue
            files = repository_file_candidates(words, root, session)
            if not files:
                continue
            if len(files) != 1:
                unparseable = True
                continue
            name = Path(words[0]).name
            total_lines = file_line_count(files[0], cache)
            selected = limiter_range(words, total_lines) if len(pipeline) == 1 else None
            if selected is None and name in transparent and position == 0 and len(pipeline) == 2:
                selected = limiter_range(pipeline[1], total_lines)
            if selected is None:
                unparseable = True
                continue
            for path in files:
                item = canonical_range(path, selected[0], selected[1], root, cache=cache)
                if item is not None:
                    ranges.append(item)
    return ranges, unparseable


def direct_source_range(name, data, root, cache=None, session=None):
    if name.lower() not in READ_TOOLS:
        return None
    raw_path = tool_path(data)
    if raw_path is None:
        return None
    target = resolved(raw_path, root)
    if session_artifact(target, session):
        return None
    try:
        target.relative_to(root)
    except ValueError:
        return None
    offset = next((data[key] for key in ('offset', 'start_line', 'line_start') if key in data), None)
    limit = next((data[key] for key in ('limit', 'line_limit', 'max_lines') if key in data), None)
    try:
        return canonical_range(target, int(offset), int(offset) + min(int(limit), READ_LINES) - 1,
                               root, cache=cache)
    except (TypeError, ValueError):
        return None


def git_source(words):
    index = 1
    while index < len(words) and words[index].startswith('-'):
        if words[index] in ('-C', '-c'):
            index += 2
        else:
            index += 1
    if index >= len(words):
        return False
    subcommand = words[index]
    rest = words[index + 1:]
    if subcommand in ('diff', 'show'):
        return True
    if subcommand == 'log':
        patch = any(word in ('-p', '--patch', '--stat') for word in rest)
        count = None
        for position, word in enumerate(rest):
            if re.fullmatch(r'-\d+', word):
                count = int(word[1:])
            elif word in ('-n', '--max-count') and position + 1 < len(rest):
                try:
                    count = int(rest[position + 1])
                except ValueError:
                    pass
            elif word.startswith(('-n', '--max-count=')):
                try:
                    count = int(word.split('=', 1)[-1] if '=' in word else word[2:])
                except ValueError:
                    pass
        return patch or count is None or count > READ_LINES
    if subcommand == 'blame':
        for position, word in enumerate(rest):
            value = rest[position + 1] if word == '-L' and position + 1 < len(rest) else word[2:] if word.startswith('-L') else ''
            match = re.fullmatch(r'(\d+),(\d+)', value)
            if match and 0 <= int(match.group(2)) - int(match.group(1)) < READ_LINES:
                return False
        return True
    return subcommand in ('grep', 'ls-files', 'ls-tree', 'cat-file', 'status', 'shortlog', 'branch', 'tag', 'remote')


def shell_search_producer(words):
    if not words:
        return False
    name = Path(words[0]).name
    if name in SEARCH_COMMANDS:
        return True
    if name != 'git':
        return False
    index = 1
    while index < len(words) and words[index].startswith('-'):
        index += 2 if words[index] in ('-C', '-c') else 1
    return index < len(words) and words[index] == 'grep'


def shell_discovery_producer(words):
    return bool(words) and Path(words[0]).name in DISCOVERY_COMMANDS


def result_producer_call(name, data):
    normalized = name.lower()
    if normalized in SEARCH_TOOLS | DISCOVERY_TOOLS:
        return True
    if normalized not in SHELL_TOOLS:
        return False
    command = data.get('command')
    if not isinstance(command, str):
        return False
    try:
        parts = split_shell(unwrap_shell(command))
        return any(shell_search_producer(command_words(part))
                   or shell_discovery_producer(command_words(part)) for part, _ in parts)
    except ValueError:
        return False


def too_many_results(name, data, value):
    if not result_producer_call(name, data):
        return False
    text = output_text(value)
    return text is None or len(split_lf_text(text)) > SEARCH_RESULTS


def repository_expansion_call(name, data, root, session):
    normalized = name.lower()
    if normalized in SEARCH_TOOLS | DISCOVERY_TOOLS:
        return True
    try:
        opened = paths_opened_by_call(name, data, root)
    except (OSError, ValueError):
        opened = []
    if any((path == root or root in path.parents) and not session_artifact(path, session)
           for path in opened):
        return True
    if opened and all(session_artifact(path, session) for path in opened):
        return False
    if normalized not in SHELL_TOOLS:
        return False
    command = data.get('command')
    if not isinstance(command, str):
        return False
    try:
        parts = split_shell(unwrap_shell(command))
        words = [command_words(part) for part, _ in parts]
    except ValueError:
        return True
    return any(shell_search_producer(row) or (row and (
        Path(row[0]).name in SOURCE_COMMANDS or
        (Path(row[0]).name == 'git' and git_source(row)))) for row in words)


def strict_search_words(words):
    return _load_evidence_module().strict_search_words(words)


def search_pattern(words):
    try:
        return strict_search_words(words)[0]['pattern']
    except (ValueError, UnicodeError):
        return None


def repository_search_pattern(name, data, root):
    normalized = name.lower()
    if normalized in SEARCH_TOOLS:
        return None
    if normalized not in SHELL_TOOLS:
        return None
    command = data.get('command')
    if not isinstance(command, str):
        return None
    try:
        if contains_unquoted(command, '>') or contains_unquoted(command, '<'):
            return None
        parts = split_shell(unwrap_shell(command))
        if (len(parts) != 2 or parts[0][1] != '|' or parts[1][1]
                or command_words(parts[1][0]) != ['head', '-' + str(SEARCH_RESULT_SENTINEL)]):
            return None
        contract, paths = strict_search_words(command_words(parts[0][0]))
        if paths == ['.']:
            return contract
    except (OSError, ValueError):
        return None
    return None


def shell_violations(command, roots, root, session, authorized=None, complete=None, cache=None,
                     dependency=None, adapter=None, allow_source_batch=False):
    tool = 'Bash'
    command = unwrap_shell(command)
    # A refused program must never hide behind a shape code, several of which are advisories.
    try:
        READONLY_POLICY.validate(command, allow_source_batch=True)
    except Exception:
        return [violation('unsupported-shell-command', tool)]
    if contains_unquoted(command, '<'):
        return [violation('unsupported-shell-input-redirection', tool)]
    try:
        parts = split_shell(command)
        parsed = [(command_words(part), separator) for part, separator in parts]
    except ValueError:
        return [violation('unsupported-shell-shape', tool)]
    pipelines = []
    current = []
    for item in parsed:
        current.append(item[0])
        if item[1] != '|':
            pipelines.append(current)
            current = []
    if current:
        pipelines.append(current)
    quiet = {'cd', ':', 'true', 'false', 'test', '[', 'sleep'}
    producer_pipelines = sum(any(words and Path(words[0]).name not in quiet for words in pipeline)
                             for pipeline in pipelines)
    if producer_pipelines > 1:
        if adapter != 'codex' or not allow_source_batch:
            return [violation('unsupported-source-batch', tool)]
        try:
            READONLY_POLICY.strict_source_batch(command, root)
        except READONLY_POLICY.SourceBatchBlocked as error:
            return [violation(error.code, tool)]
        except (OSError, TypeError, ValueError):
            return [violation('unsupported-source-batch', tool)]
    try:
        READONLY_POLICY.validate(command, allow_source_batch=allow_source_batch)
    except Exception:
        return [violation('unsupported-shell-command', tool)]
    if any(token in command for token in ('`', '$(')):
        return [violation('unsupported-shell-shape', tool)]
    for words, _ in parsed:
        if words and words[0] in ('for', 'while', 'until', 'if', 'then', 'do', 'case', '{'):
            return [violation('unsupported-shell-shape', tool)]
        for candidate in path_candidates(words, root):
            try:
                path = resolved(candidate, root)
            except (OSError, ValueError):
                return [violation('unresolved-path-variable', tool)]
            if not session_path_allowed(path, session, authorized, dependency):
                return [violation('unnamed-session-artifact', tool)]
            if not inside(path, roots) and not (authorized is not None and path in authorized) \
                    and not session_artifact(path, session):
                return [violation('path-outside-scope', tool)]
    for pipeline in pipelines:
        for position, words in enumerate(pipeline):
            if not words:
                continue
            name = Path(words[0]).name
            if name in UNSUPPORTED_FILE_COMMANDS and path_candidates(words, root):
                return [violation('unsupported-source-range', tool)]
            is_source = name in SOURCE_COMMANDS or (name == 'git' and git_source(words))
            if name in ('head', 'tail', 'sed'):
                is_source = not line_limiter(words)
            if name == 'cat':
                try:
                    operands = [resolved(value, root) for value in path_candidates(words, root)]
                except OSError:
                    return [violation('unresolved-path-variable', tool)]
                if operands and all(complete_path_allowed(path, session, complete)
                                    for path in operands):
                    is_source = False
            result_producer = shell_search_producer(words) or shell_discovery_producer(words)
            maximum = SEARCH_RESULTS if result_producer else READ_LINES
            bounded_here = result_producer and line_limiter(words, maximum)
            downstream_maximum = (SEARCH_RESULT_SENTINEL
                                  if shell_search_producer(words) else maximum)
            if is_source and not bounded_here \
                    and not any(line_limiter(later, downstream_maximum)
                                for later in pipeline[position + 1:]):
                return [violation('unbounded-shell-output', tool)]
    _, unparseable = shell_source_ranges(command, root, cache, session)
    if unparseable:
        return [violation('unsupported-source-range', tool)]
    return []


def validate_call(name, data, roots, root, session, authorized=None, complete=None, cache=None,
                  dependency=None, adapter=None, allow_source_batch=False):
    normalized = name.lower()
    path = tool_path(data)
    if path is not None:
        try:
            target = resolved(path, root)
        except (OSError, ValueError):
            return [violation('unresolved-path-variable', name)]
        if not session_path_allowed(target, session, authorized, dependency):
            return [violation('unnamed-session-artifact', name)]
        if not inside(target, roots) and not (authorized is not None and target in authorized) \
                and not session_artifact(target, session):
            return [violation('path-outside-scope', name)]
    if normalized in READ_TOOLS:
        if path is None:
            return [violation('missing-read-path', name)]
        try:
            may_read_complete = complete_path_allowed(resolved(path, root), session, complete)
        except OSError:
            return [violation('unresolved-path-variable', name)]
        if may_read_complete:
            return []
        if not explicit_offset(data) or not positive_bound(data, ('limit', 'line_limit', 'max_lines'), READ_LINES):
            return [violation('unbounded-read', name)]
        return []
    elif normalized in SEARCH_TOOLS:
        if not positive_bound(data, ('head_limit', 'max_results', 'limit'), SEARCH_RESULTS):
            return [violation('unbounded-search', name)]
        return []
    elif normalized in DISCOVERY_TOOLS:
        return [violation('unbounded-search', name)]
    elif normalized in SHELL_TOOLS:
        command = data.get('command')
        if not isinstance(command, str) or not command.strip():
            return [violation('missing-shell-command', name)]
        return shell_violations(
            command, roots, root, session, authorized, complete, cache, dependency, adapter,
            allow_source_batch)
    elif normalized in TERMINAL_TOOLS:
        return []
    return [violation('unrecognized-review-tool', name)]


def extract_calls(adapter, event):
    calls = []
    adapter = 'claude' if adapter == 'agent' else adapter
    if adapter == 'codex':
        item = event.get('item') or {}
        if event.get('type') in ('item.started', 'item.completed') and item.get('type') == 'command_execution':
            calls.append((item.get('id'), 'command_execution', {'command': item.get('command')}))
    elif adapter == 'grok' and event.get('type') == 'tool_call':
        data = event.get('rawInput') or event.get('input') or event.get('parameters') or {}
        if not isinstance(data, dict):
            data = {}
        if event.get('toolName') in ('shell', 'Bash') and 'command' not in data:
            data = dict(data, command=event.get('title'))
        calls.append((event.get('toolCallId'), event.get('toolName', ''), data))
    elif adapter == 'gemini' and event.get('type') == 'tool_use':
        calls.append((event.get('tool_id'), event.get('tool_name', ''), event.get('parameters') or {}))
    elif adapter == 'claude' and event.get('type') == 'assistant':
        for block in (event.get('message') or {}).get('content', []):
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                calls.append((block.get('id'), block.get('name', ''), block.get('input') or {}))
    return calls


def output_bytes(value):
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode())
    if isinstance(value, list):
        total = 0
        for item in value:
            if isinstance(item, dict):
                content = item.get('text', item.get('content', item))
                total += output_bytes(content)
            else:
                total += output_bytes(item)
        return total
    return len(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def output_text(value):
    """Extract delivered textual bytes from known provider result envelopes."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            text = output_text(item)
            if text is None:
                return None
            parts.append(text)
        return ''.join(parts)
    if not isinstance(value, dict):
        return None
    file_content = value.get('FileContent')
    if isinstance(file_content, dict) and isinstance(file_content.get('content'), str):
        return file_content['content']
    if value.get('type') in ('text', 'content'):
        for key in ('text', 'content'):
            if key in value:
                return output_text(value[key])
    for key in ('output', 'content', 'result', 'text'):
        if key in value:
            return output_text(value[key])
    return None


def claude_hook_output(name, value):
    """Return model-visible text and a conservative result count for PostToolUse."""
    if isinstance(value, str):
        return value, len(split_lf_text(value))
    if not isinstance(value, dict):
        raise ValueError('unsupported hook response')
    normalized = name.lower()
    if normalized in READ_TOOLS:
        file = value.get('file')
        if value.get('type') != 'text' or not isinstance(file, dict):
            raise ValueError('unsupported read hook response')
        content = file.get('content')
        start = file.get('startLine')
        count = file.get('numLines')
        total = file.get('totalLines')
        if (not isinstance(content, str) or type(start) is not int or start < 1
                or type(count) is not int or count < 0 or type(total) is not int or total < count):
            raise ValueError('invalid read hook response')
        provider_lines = content.split('\n')
        logical_lines = split_lf_text(content)
        if len(provider_lines) == count:
            lines = provider_lines
        elif len(logical_lines) == count:
            lines = logical_lines
        else:
            raise ValueError('read hook line count mismatch')
        rendered = '\n'.join(str(start + index) + '\t' + line
                             for index, line in enumerate(lines))
        return rendered, len(lines)
    if normalized in SEARCH_TOOLS:
        mode = value.get('mode')
        truncated = value.get('truncated', False)
        if type(truncated) is not bool:
            raise ValueError('invalid search truncation marker')
        if isinstance(value.get('content'), str):
            text = value['content']
            observed = len(split_lf_text(text))
            counters = [value.get(key) for key in ('numLines', 'totalLines')
                        if value.get(key) is not None]
        elif isinstance(value.get('filenames'), list) and all(
                isinstance(path, str) for path in value['filenames']):
            text = '\n'.join(value['filenames'])
            observed = len(value['filenames'])
            counters = [value.get(key) for key in ('numFiles', 'totalFiles')
                        if value.get(key) is not None]
        else:
            raise ValueError('unsupported search hook response')
        if any(type(counter) is not int or counter < 0 for counter in counters):
            raise ValueError('invalid search hook count')
        count = max([observed, *counters])
        if truncated or value.get('countIsComplete') is False:
            count = max(count, SEARCH_RESULT_SENTINEL)
        if mode is not None and not isinstance(mode, str):
            raise ValueError('invalid search hook mode')
        return text, count
    if normalized in SHELL_TOOLS:
        stdout = value.get('stdout')
        stderr = value.get('stderr')
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise ValueError('unsupported shell hook response')
        separator = '\n' if stdout and stderr and not stdout.endswith('\n') else ''
        text = stdout + separator + stderr
        return text, len(split_lf_text(text))
    raise ValueError('unsupported hook tool')


def search_result_paths(value):
    text = output_text(value)
    if text is None:
        return None
    lines = split_lf_text(text)
    if not lines or len(lines) > SEARCH_RESULTS:
        return None
    error = re.compile(
        r'^(?:rg|ripgrep|grep|egrep|fgrep):(?:\s|$).*'
        r'(?:error|invalid|unrecognized|unknown option|is a directory|permission denied|'
        r'operation not permitted|no such file|not found|input/output error|i/o error)',
        re.IGNORECASE)
    shell_error = re.compile(
        r'^(?:(?:/bin/)?(?:ba|z|da)?sh|fish|env):.*(?:command not found|no such file|not found)'
        r'|^(?:\./|/|[^:\s]+/)[^:]*:\s*(?:no such file|not found)',
        re.IGNORECASE)
    paths = set()
    for line in lines:
        if error.search(line) or shell_error.search(line):
            return None
        match = re.match(r'^(?:\./)?(.+?)\0([1-9][0-9]*):', line)
        if not match:
            return None
        path = posixpath.normpath(match.group(1))
        if path in ('', '.', '..') or path.startswith('../') or path.startswith('/'):
            return None
        paths.add(path)
    return paths


def search_output_failed(value):
    return search_result_paths(value) is None


def output_digest(value):
    text = output_text(value)
    raw = text.encode() if text is not None else json.dumps(
        value, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def extract_outputs(adapter, event):
    adapter = 'claude' if adapter == 'agent' else adapter
    if adapter == 'codex':
        item = event.get('item') or {}
        if event.get('type') == 'item.completed' and item.get('type') == 'command_execution':
            for key in ('aggregated_output', 'output'):
                if key in item:
                    success = type(item.get('exit_code')) is int and item['exit_code'] == 0 \
                        and item.get('status') != 'failed'
                    return [(item.get('id'), success, item[key], None)]
    elif adapter == 'grok' and event.get('type') == 'tool_call_update' \
            and event.get('status') in ('completed', 'failed'):
        content = event.get('content')
        visible = output_text(content)
        if 'content' in event and content not in (None, [], {}) and visible is not None:
            value = visible
        elif 'rawOutput' in event:
            raw = event['rawOutput']
            value = output_text(raw)
            if value is None:
                value = raw
        else:
            return []
        return [(event.get('toolCallId'), event.get('status') == 'completed', value, None)]
    elif adapter == 'gemini' and event.get('type') == 'tool_result':
        for key in ('output', 'content', 'result'):
            if key in event:
                return [(event.get('tool_id'), event.get('status') == 'success', event[key], None)]
    elif adapter == 'claude' and event.get('type') == 'user':
        found = []
        metadata = event.get('tool_result_meta')
        metadata = metadata if isinstance(metadata, list) else []
        for block in (event.get('message') or {}).get('content', []):
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                matches = [row for row in metadata if isinstance(row, dict)
                           and row.get('id') == block.get('tool_use_id')]
                non_execution = (len(matches) == 1
                                 and matches[0].get('non_execution_kind') == 'permission-rule')
                found.append((block.get('tool_use_id'), block.get('is_error') is not True,
                              block.get('content'), non_execution))
        return found
    return []


def claude_nonexecuted_exploration(adapter, name, data, output):
    normalized = name.lower()
    if (adapter not in ('claude', 'agent')
            or normalized not in READ_TOOLS | SEARCH_TOOLS | SHELL_TOOLS):
        return False
    if output.get('success') is not False:
        return False
    if output.get('non_execution') is not True:
        return False
    visible = output_text(output.get('value'))
    if not isinstance(visible, str):
        return False
    if re.fullmatch(
            r'PreToolUse:' + re.escape(name) + r' hook error: [^\r\n]+\n?', visible) is None:
        return False
    if normalized in SHELL_TOOLS:
        command = data.get('command')
        if not isinstance(command, str) or not command.strip():
            return False
        try:
            READONLY_POLICY.validate(command)
        except (READONLY_POLICY.Blocked, OSError, TypeError, ValueError):
            return False
    return True


def byte_exempt(name, data, root, session, complete=None):
    if name.lower() not in READ_TOOLS:
        return False
    path = tool_path(data)
    try:
        if path is None:
            return False
        target = resolved(path, root)
        if complete is not None:
            return target in complete and not SOURCE_PACKET_NAME.fullmatch(target.name)
        return full_artifact(target, session) and not SOURCE_PACKET_NAME.fullmatch(target.name)
    except (OSError, ValueError):
        return False


def publish(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '.', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_evidence_manifest(session, declared_hash, prompt, root):
    matches = [path for path in session.glob('r*-evidence.manifest.json')
               if path.is_file() and digest(path) == declared_hash]
    if len(matches) != 1:
        raise ValueError('evidence manifest hash does not resolve uniquely')
    path = matches[0]
    module = _load_evidence_module()
    manifest, manifest_hash = module.validated_manifest(path, fresh=False)
    repository = module.Repository(session)
    if repository.root != root:
        raise ValueError('evidence repository root mismatch')
    prefix = 'r' + manifest['label'] + '-'
    suffix = '.prompt.md'
    if not prompt.name.startswith(prefix) or not prompt.name.endswith(suffix):
        raise ValueError('prompt name does not identify manifest seat')
    seat = prompt.name[len(prefix):-len(suffix)]
    if seat not in manifest['assignments']:
        raise ValueError('prompt seat is absent from evidence manifest')
    return manifest, manifest_hash, seat, repository


def validate_plan_prompt_binding(manifest, seat, prompt, module):
    if manifest is None or manifest.get('phase') != 'plan':
        return
    session = Path(manifest['session'])
    plan = manifest['plan']
    text = Path(prompt).read_text()
    plan_path = session / plan['artifact']
    lines = plan_path.read_text().splitlines()
    numbered = '\n'.join(f'{index:6d}\t{line}' for index, line in enumerate(lines, 1))
    required_once = [
        'Immutable plan snapshot SHA-256: ' + plan['sha256'],
        'The immutable snapshot is embedded below with source line numbers.',
        numbered,
    ]
    assignment = manifest['assignments'][seat]
    first_call = plan_specialist_first_call_contract(manifest, seat, session)
    if first_call is not None:
        required_once.append(first_call)
    assigned = set(assignment.get('plan_clusters', [cluster['id'] for cluster in plan['clusters']]))
    for cluster in plan['clusters']:
        cluster_id = cluster['id']
        if cluster_id not in assigned:
            forbidden = [
                'Prepared cluster sibling search: ' + cluster_id + ' ',
                'Required cluster sibling search: ' + cluster_id + ' ',
                'Required cluster source: ' + cluster_id + ' ',
            ]
            if any(token in text for token in forbidden):
                raise ValueError('prompt contains an unassigned plan cluster')
            continue
        proof = cluster.get('search_proof')
        if proof is None:
            command = (shlex.join(module.plan_search_argv(cluster['search_contract']))
                       + ' | head -' + str(SEARCH_RESULT_SENTINEL))
            required_once.append(
                'Required cluster sibling search: ' + cluster_id + ' run ' + command
                + ' from repository root; at most 80 result lines are accepted, and an 81st '
                + 'line invalidates proof.')
        else:
            body = (session / proof['artifact']).read_text()
            required_once.extend([
                'Prepared cluster sibling search: ' + cluster_id + ' ' + proof['artifact']
                + ' SHA-256 ' + proof['sha256'],
                'Prepared cluster search output: '
                + json.dumps(body, ensure_ascii=True, separators=(',', ':')),
            ])
        for row in cluster['paths']:
            location = row['path']
            if row['line_start'] is not None:
                location += ':' + str(row['line_start'])
                if row['line_end'] != row['line_start']:
                    location += '-' + str(row['line_end'])
            required_once.append(
                'Required cluster source: ' + cluster_id + ' ' + location
                + ' resolution ' + row['resolution'] + ' field ' + row['field'])
    for row in module.plan_mandatory_source_windows(
            manifest, manifest['source_context']['seats'][seat]):
        required_once.append(
            'Mandatory cluster source window: ' + row['path'] + ':'
            + str(row['line_start']) + '-' + str(row['line_end']))
    if any(not token or text.count(token) != 1 for token in required_once):
        raise ValueError('prompt omits or duplicates bound plan evidence')
    if first_call is not None:
        prompt_lines = text.splitlines()
        first_index = prompt_lines.index(first_call)
        competing = (
            'Prepared cluster sibling search:', 'Required cluster sibling search:',
            'Required cluster source:', 'Mandatory cluster source window:',
            'Assigned patch read mode:',
            'Canonical assigned patch:', 'Read the entire assigned patch',
            'Source context packet:', 'Required source segment ',
            'Evidence navigation index:',
        )
        competing_indices = [index for index, line in enumerate(prompt_lines)
                             if line.startswith(competing)]
        if competing_indices and first_index >= min(competing_indices):
            raise ValueError('plan specialist first-call contract is not first')


def validate_assignment_prompt_binding(manifest, seat, prompt_lines):
    if manifest is None:
        return
    assignment = manifest['assignments'][seat]
    required = (
        'Assigned scope: ' + assignment['scope'],
        'Assigned risk bundle: ' + assignment['bundle'],
        '## Your lens this round: ' + assignment['bundle'],
    )
    if any(prompt_lines.count(line) != 1 for line in required):
        raise ValueError('prompt omits or duplicates its assigned scope, bundle, or lens')


def paths_opened_by_call(name, data, root):
    raw = []
    path = tool_path(data)
    if path is not None:
        raw.append(path)
    if name.lower() in SHELL_TOOLS:
        command = data.get('command')
        if isinstance(command, str):
            try:
                for part, _ in split_shell(unwrap_shell(command)):
                    raw.extend(path_candidates(command_words(part), root))
            except ValueError:
                pass
    paths = []
    for value in raw:
        try:
            target = resolved(value, root)
        except (OSError, ValueError):
            continue
        if target not in paths:
            paths.append(target)
    return paths


def complete_packet_read(name, data, packet, root):
    normalized = name.lower()
    if normalized in READ_TOOLS:
        raw_path = tool_path(data)
        if raw_path is None or any(key in data for key in (
                'offset', 'start_line', 'line_start', 'limit', 'line_limit', 'max_lines')):
            return False
        try:
            return resolved(raw_path, root) == packet
        except (OSError, ValueError):
            return False
    if normalized not in SHELL_TOOLS:
        return False
    command = data.get('command')
    if not isinstance(command, str):
        return False
    try:
        parts = split_shell(unwrap_shell(command))
        if len(parts) != 1 or parts[0][1] != '':
            return False
        words = command_words(parts[0][0])
        if not words or Path(words[0]).name != 'cat':
            return False
        return (repository_file_candidates(words, root, packet.parent) == []
                and paths_opened_by_call(name, data, root) == [packet])
    except (OSError, ValueError):
        return False


def line_range_bytes(path, start, end, cache=None):
    _, lines = cached_file(path, cache)
    return byte_range_lines(lines, start, end)


def byte_range(raw, start, end):
    return byte_range_lines(split_lf_lines(raw), start, end)


def split_lf_lines(raw):
    parts = raw.split(b'\n')
    return [part + b'\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def split_lf_text(text, keepends=False):
    parts = text.split('\n')
    if keepends:
        return [part + '\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    return parts[:-1] + ([parts[-1]] if parts[-1] else [])


def byte_range_lines(lines, start, end):
    if end < start:
        return b''
    return b''.join(lines[start - 1:end])


def strip_number_prefixes(text, start, separator):
    cleaned = []
    for index, line in enumerate(split_lf_text(text, keepends=True), start):
        prefix = str(index) + separator
        cleaned.append(line[len(prefix):] if line.startswith(prefix) else line)
    return ''.join(cleaned)


def delivered_matches(adapter, name, output, path, start, end, cache=None):
    return delivered_matches_bytes(
        adapter, name, output, line_range_bytes(path, start, end, cache), start)


def delivered_matches_bytes(adapter, name, output, expected, start):
    text = output_text(output)
    if text is None:
        return False
    if adapter in ('claude', 'agent') and name.lower() in READ_TOOLS \
            and expected == b'' and text == CLAUDE_EMPTY_READ:
        return True
    candidates = [text]
    normalized = []
    if name.lower() in READ_TOOLS:
        expected_lines = len(split_lf_lines(expected))
        delivered_lines = len(split_lf_text(text))
        if adapter == 'grok':
            grok_omitted_terminal_blank = (
                expected.endswith(b'\n\n') and delivered_lines + 1 == expected_lines)
            if delivered_lines == expected_lines or grok_omitted_terminal_blank:
                normalized.append(strip_number_prefixes(text, start, '→'))
        elif adapter in ('claude', 'agent'):
            rendered = [text]
            final_prefix = str(start + expected_lines - 1) + '\t'
            if expected.endswith(b'\n\n') and text.endswith(final_prefix):
                rendered.append(text + '\n')
            for candidate in rendered:
                if len(split_lf_text(candidate)) in (expected_lines, expected_lines + 1):
                    normalized.append(strip_number_prefixes(candidate, start, '\t'))
        candidates.extend(normalized)
        if adapter == 'grok' or not expected.endswith(b'\n\n'):
            candidates.extend(candidate + '\n' for candidate in list(candidates))
    return any(candidate.encode() == expected for candidate in candidates)


def manifest_blob(repository, row, cache):
    tree = row['blob_tree']
    oid = row['blob_oid']
    path = row['path']
    key = (tree, oid, path, row['blob_mode'])
    if key in cache:
        return cache[key]
    listed = repository.git('ls-tree', '-z', tree, '--', path)
    records = [record for record in listed.split(b'\0') if record]
    if len(records) != 1:
        raise ValueError('required source tree path is ambiguous')
    header, listed_path = records[0].split(b'\t', 1)
    mode, kind, listed_oid = header.decode().split()
    if (listed_path.decode() != path or mode != row['blob_mode'] or kind != 'blob'
            or listed_oid != oid):
        raise ValueError('required source blob identity mismatch')
    raw = repository.git('cat-file', 'blob', oid)
    cache[key] = raw, split_lf_lines(raw)
    return cache[key]


def target_file_candidates(words, target, root):
    found = []
    for candidate in path_candidates(words, root):
        try:
            path = resolved(candidate, root)
        except (OSError, ValueError):
            continue
        if path == target:
            found.append(path)
        elif path.is_file():
            found.append(path)
    return found


def shell_target_ranges(command, target, root, total_lines=None):
    """Return bounded line ranges selected from one exact non-repository artifact."""
    try:
        parts = split_shell(unwrap_shell(command))
        parsed = [(command_words(part), separator) for part, separator in parts]
    except ValueError:
        return []
    pipelines = []
    current = []
    for words, separator in parsed:
        current.append(words)
        if separator != '|':
            pipelines.append(current)
            current = []
    if current:
        pipelines.append(current)
    if total_lines is None:
        total_lines = file_line_count(target)
    ranges = []
    transparent = {'cat'}
    direct = {'cat', 'less', 'more', 'nl', 'bat', 'strings', 'xxd', 'od', 'sed', 'head', 'tail'}
    for pipeline in pipelines:
        for position, words in enumerate(pipeline):
            if not words or Path(words[0]).name not in direct:
                continue
            files = target_file_candidates(words, target, root)
            if files != [target]:
                continue
            name = Path(words[0]).name
            selected = limiter_range(words, total_lines) if len(pipeline) == 1 else None
            if selected is None and name in transparent and position == 0 and len(pipeline) == 2:
                selected = limiter_range(pipeline[1], total_lines)
            if selected is None:
                continue
            start, end = selected
            if total_lines == 0:
                ranges.append((1, 0))
            else:
                start = max(1, start)
                end = min(total_lines, end)
                if start <= end:
                    ranges.append((start, end))
    return ranges


def assigned_patch_ranges_for_call(name, data, patch, root, total_lines):
    normalized = name.lower()
    if normalized in READ_TOOLS:
        raw_path = tool_path(data)
        if raw_path is None:
            return []
        try:
            if resolved(raw_path, root) != patch:
                return []
            offset = next(data[key] for key in ('offset', 'start_line', 'line_start') if key in data)
            limit = next(data[key] for key in ('limit', 'line_limit', 'max_lines') if key in data)
            start = int(offset)
            return [(start, min(total_lines, start + int(limit) - 1))] if total_lines else [(1, 0)]
        except (KeyError, OSError, TypeError, ValueError):
            return []
    if normalized in SHELL_TOOLS:
        command = data.get('command')
        if isinstance(command, str):
            return shell_target_ranges(command, patch, root, total_lines)
    return []


def plan_specialist_primary(manifest, seat, session):
    """Return the schema-4 specialist's mandatory first artifact and read mode."""
    assignment = manifest['assignments'][seat]
    if assignment['patch_bytes']:
        if assignment['patch_read_mode'] == 'chunks':
            chunks = manifest['patch_sets'][assignment['patch_set']]['chunks']
            if not chunks:
                raise ValueError('chunked plan patch has no primary chunk')
            return session / chunks[0]['artifact'], 'full', None
        return Path(assignment['patch']), 'window', min(READ_LINES, assignment['patch_lines'])
    patch_name = Path(assignment['patch']).name
    candidates = [name for name in assignment['required_artifacts'] if name != patch_name]
    artifact = candidates[0] if candidates else manifest['plan']['common_artifacts'][0]
    return session / artifact, 'full', None


def plan_specialist_first_call_contract(manifest, seat, session):
    """Return the exact first-call instruction bound into a schema-4 plan prompt."""
    if (manifest.get('schema_version') != 4 or manifest.get('phase') != 'plan'
            or seat == manifest.get('mechanical_owner')):
        return None
    assignment = manifest['assignments'][seat]
    primary, mode, window_end = plan_specialist_primary(manifest, seat, Path(session))
    if assignment['adapter'] == 'codex':
        if mode == 'window':
            action = "run sed -n '1," + str(window_end) + "p' " + shlex.quote(str(primary))
        else:
            action = 'run ' + shlex.join(['cat', '--', str(primary)])
    else:
        tool = 'Read' if assignment['adapter'] in ('agent', 'claude') else 'read_file'
        if mode == 'window':
            action = 'use ' + tool + ' with offset 1 and limit 240 on ' + str(primary)
        else:
            action = 'use ' + tool + ' to read ' + str(primary) + ' in full'
    return ('Plan specialist first-call contract: ' + action
            + ' as exactly one native primary-artifact read. Do not run a directory command, '
            + 'search, or compound shell command before or with this read.')


def exact_single_shell_read(data, primary, mode, window_end, root):
    command = data.get('command')
    if not isinstance(command, str):
        return False
    try:
        parts = split_shell(unwrap_shell(command))
        if len(parts) != 1 or parts[0][1] != '':
            return False
        words = command_words(parts[0][0])
        expected = (['cat', '--', str(primary)] if mode == 'full' else
                    ['sed', '-n', f'1,{window_end}p', str(primary)])
        if len(words) != len(expected) or Path(words[0]).name != expected[0] \
                or words[1:-1] != expected[1:-1]:
            return False
        return resolved(words[-1], root) == primary
    except (OSError, TypeError, ValueError):
        return False


def exact_native_first_read(adapter, name, data, primary, mode, window_end, root):
    normalized = name.lower()
    if adapter == 'codex':
        return normalized in SHELL_TOOLS \
            and exact_single_shell_read(data, primary, mode, window_end, root)
    expected_tool = 'read' if adapter in ('claude', 'agent') else 'read_file'
    if normalized != expected_tool:
        return False
    raw_path = tool_path(data)
    try:
        if raw_path is None or resolved(raw_path, root) != primary:
            return False
    except (OSError, ValueError):
        return False
    bounds = ('offset', 'start_line', 'line_start', 'limit', 'line_limit', 'max_lines')
    if mode == 'full':
        return not any(key in data for key in bounds)
    try:
        offset = next(data[key] for key in ('offset', 'start_line', 'line_start') if key in data)
        limit = next(data[key] for key in ('limit', 'line_limit', 'max_lines') if key in data)
        return type(offset) is int and offset == 1 and type(limit) is int and limit == READ_LINES
    except StopIteration:
        return False


def validate_plan_first_call(manifest, seat, adapter, calls, root, session):
    if (not isinstance(manifest, dict)
            or manifest.get('schema_version') != 4 or manifest.get('phase') != 'plan'
            or seat == manifest.get('mechanical_owner')):
        return []
    if not calls:
        return [violation('invalid-plan-first-call', adapter)]
    name, data, _ = next(iter(calls.values()))
    primary, mode, window_end = plan_specialist_primary(manifest, seat, session)
    if exact_native_first_read(adapter, name, data, primary, mode, window_end, root):
        return []
    return [violation('invalid-plan-first-call', name)]


def without_xcrun_preamble(value):
    text = output_text(value)
    if text is None:
        return value
    position = 0
    while match := XCRUN_DIAGNOSTIC.match(text, position):
        position = match.end()
    return text[position:]


def pinned_snapshot_ranges(call_ranges, entries, repository):
    """Clamp snapshot-tree rows to their frozen blobs; None when a path is absent from the tree."""
    rows = []
    for row in call_ranges:
        entry = entries.get(row['path'])
        if entry is None:
            return None
        end = min(row['line_end'], len(split_lf_lines(repository.blob(entry))))
        if row['line_start'] <= end:
            rows.append({'path': row['path'], 'line_start': row['line_start'], 'line_end': end,
                         'origin': 'tool'})
    return rows


def ranges_cover_file(ranges, total_lines):
    if total_lines == 0:
        return ranges == []
    cursor = 1
    for start, end in sorted(set(ranges)):
        if start > cursor:
            return False
        cursor = max(cursor, end + 1)
    return cursor == total_lines + 1


def ranges_cover_file_in_order(ranges, total_lines):
    if total_lines == 0:
        return ranges == []
    cursor = 1
    for start, end in ranges:
        if start != cursor or end < start:
            return False
        cursor = end + 1
    return cursor == total_lines + 1


def evidence_order_violations(calls, outputs, patch_calls, packet_paths, segment_paths,
                              evidence_index, root, session, verified_ranges):
    """Enforce the ordered patch, context, segment, index, and expansion phases."""
    packet_order = {path: index for index, path in enumerate(packet_paths)}
    segment_order = {path: index for index, path in enumerate(segment_paths)}
    previous = (-1, -1)
    previous_turn = None
    for call_id, (name, data, turn) in calls.items():
        output = outputs.get(call_id)
        if output is None or not output['success']:
            continue
        phases = []
        if call_id in patch_calls:
            phases.append((0, 0))
        opened = paths_opened_by_call(name, data, root)
        for path in opened:
            if path in packet_order:
                phases.append((1, packet_order[path]))
            elif path in segment_order:
                phases.append((2, segment_order[path]))
            elif path == evidence_index:
                phases.append((3, 0))
        if (verified_ranges.get(call_id)
                or repository_expansion_call(name, data, root, session)):
            phases.append((4, 0))
        for phase in phases:
            if (phase < previous
                    or (phase[0] == 4 and previous[0] != 4 and previous_turn is not None
                        and turn == previous_turn)):
                return [violation('evidence-read-order', 'audit')]
            previous = phase
            previous_turn = turn
    return []


def turn_batch_violations(calls, call_ids, limit, code, adapter):
    turns = {}
    for call_id in call_ids:
        if call_id in calls:
            turns[calls[call_id][2]] = turns.get(calls[call_id][2], 0) + 1
    return [violation(code, adapter)] if any(count > limit for count in turns.values()) else []


def ranges_intersect(left, right):
    return (left['path'] == right['path']
            and left['line_start'] <= right['line_end']
            and right['line_start'] <= left['line_end'])


def source_read_requirement_violations(context, boundary_paths, tool_ranges, adapter):
    if not context['source_read_required']:
        return []
    required = context['required_source_ranges']
    omitted = context.get('omitted_source_ranges', [])
    boundary_reads = [row for row in tool_ranges if row['path'] in boundary_paths]
    required_reads = [row for row in tool_ranges
                      if any(ranges_intersect(row, wanted) for wanted in required)]
    omitted_reads = [row for row in tool_ranges
                     if any(ranges_intersect(row, wanted) for wanted in omitted)]
    missing = not (omitted_reads if omitted else boundary_reads or required_reads)
    if context['role'] == 'specialist' and required and not required_reads:
        missing = True
    return [violation('missing-required-source-read', adapter)] if missing else []


def ordered_proof_turn_exempt(batch_limit, output_calls, proof_calls, size):
    return (batch_limit > 1
            and size <= PATCH_TURN_OUTPUT_BYTES
            and 1 < len(output_calls) <= batch_limit
            and all(call_id in proof_calls for call_id in output_calls))


def required_range_covered(required, ranges):
    cursor = required['line_start']
    for row in sorted((row for row in ranges if row['path'] == required['path']
                       and row['line_end'] >= cursor and row['line_start'] <= required['line_end']),
                      key=lambda row: (row['line_start'], row['line_end'])):
        if row['line_start'] > cursor:
            return False
        cursor = max(cursor, row['line_end'] + 1)
        if cursor > required['line_end']:
            return True
    return cursor > required['line_end']


def result_for_audit(args):
    # The result is normally the sibling of --out, which only works while --out is the enforced
    # `r<label>-<seat>.read-audit.json`. An unenforced seat's audit is deliberately written under a
    # name no attempt-state or profiling glob matches, so it names its result explicitly; without
    # that, result_sha256 comes back null and the audit can never be valid whatever the transcript
    # proves, which would pin an ungated would-have-passed verdict to false by construction.
    explicit = getattr(args, 'result', None)
    if explicit:
        result = Path(explicit)
    else:
        out = Path(args.out)
        suffix = '.read-audit.json'
        if not out.name.endswith(suffix) or not out.name.startswith('r'):
            return None, None
        result = out.with_name(out.name[:-len(suffix)] + '.json')
    document = json.loads(result.read_text())
    if not isinstance(document, dict) or not isinstance(document.get('findings'), list):
        raise ValueError('invalid review result structure')
    return result, document


def intersects(finding, ranges):
    path = finding.get('file')
    start = finding.get('line_start')
    end = finding.get('line_end')
    if (not isinstance(path, str) or not path or type(start) is not int or type(end) is not int
            or start < 1 or end < start):
        return False
    return any(row['path'] == path and start <= row['line_end'] and row['line_start'] <= end
               for row in ranges)


def hook(args):
    name = ''
    data = {}
    try:
        event = json.load(sys.stdin)
        name = event.get('tool_name', '')
        data = event.get('tool_input') or {}
        root = Path(args.root).resolve()
        session = Path(args.session).resolve()
        authorized, complete = prompt_permissions(args.prompt, root, session) \
            if args.prompt else (None, None)
        dependency = Path(args.deps).resolve() if args.deps else None
        roots = allowed_roots(root, session, args.deps)
        failures = validate_call(
            name, data, roots, root, session, authorized, complete, {}, dependency)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        failures = [violation('invalid-hook-payload', 'unknown')]
    if failures:
        reason = 'review read blocked: ' + failures[0]['code']
        print(reason, file=sys.stderr)
        if name.lower() in SHELL_TOOLS:
            command = data.get('command')
            try:
                if not isinstance(command, str) or not command.strip():
                    raise READONLY_POLICY.Blocked('missing command')
                READONLY_POLICY.validate(command)
            except (READONLY_POLICY.Blocked, OSError, TypeError, ValueError):
                READONLY_POLICY.emit_pretool_deny(reason, terminal=True)
                return 0
        return 2
    return 0


def post_hook(args):
    code = 'invalid-hook-payload'
    try:
        event = json.load(sys.stdin)
        name = event.get('tool_name', '')
        data = event.get('tool_input') or {}
        root = Path(args.root).resolve()
        session = Path(args.session).resolve()
        authorized, complete = prompt_permissions(args.prompt, root, session) \
            if args.prompt else (None, None)
        dependency = Path(args.deps).resolve() if args.deps else None
        failures = validate_call(
            name, data, allowed_roots(root, session, args.deps), root, session,
            authorized, complete, {}, dependency)
        if failures:
            code = failures[0]['code']
            blocked = True
        else:
            try:
                visible, result_count = claude_hook_output(name, event.get('tool_response'))
            except (TypeError, ValueError):
                code = 'unsupported-hook-response'
                blocked = True
            else:
                size = len(visible.encode())
                excessive_results = result_producer_call(name, data) \
                    and result_count > SEARCH_RESULTS
                if excessive_results:
                    code = 'discovery-output-too-large'
                else:
                    code = 'tool-output-too-large'
                blocked = excessive_results or (
                    size > OUTPUT_BYTES and not byte_exempt(
                        name, data, root, session, complete))
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        blocked = True
    if blocked:
        reason = 'review read blocked: ' + code
        print(reason, file=sys.stderr)
        READONLY_POLICY.emit_terminal_stop(reason)
        return 0
    return 0


def audit(args):
    # A call raising any violation but a pacing count earns no credit. Credit granted before its
    # violation surfaced (an oversized turn is judged last) is revoked by assessing again.
    blocked = set()
    while True:
        result, unique, revoked = assess(args, blocked)
        if not revoked:
            break
        blocked |= revoked
    publish(args.out, result)
    return 2 if unique else 0


def assess(args, blocked):
    blocked = set(blocked)
    credited = set()
    root = Path(args.root).resolve()
    session = Path(args.session).resolve()
    prompt = Path(args.prompt).resolve()
    try:
        prompt_lines = prompt.read_text().splitlines()
    except OSError:
        prompt_lines = []
    source_batch_enabled = (
        args.adapter == 'codex'
        and prompt_lines.count('Codex source batching enabled: true') == 1
        and 'Codex source batching enabled: false' not in prompt_lines
    )
    adapter_read_batch_limit = _load_evidence_module().read_batch_limit(args.adapter)
    authorized, complete_paths = prompt_permissions(prompt, root, session)
    dependency = Path(args.deps).resolve() if args.deps else None
    roots = allowed_roots(root, session, args.deps)
    source_cache = {}
    failures = []

    if not prompt_lines:
        failures.append(violation('missing-prompt', args.adapter))
    evidence_scoped, declared_manifest_hash = evidence_manifest_declaration(prompt_lines)
    if evidence_scoped and declared_manifest_hash is None:
        failures.append(violation('invalid-evidence-manifest-declaration', args.adapter))
    calls = {}
    outputs = {}
    turns = {}
    implicit_turn = 0
    implicit_output_seen = False
    try:
        with open(args.raw, encoding='utf-8') as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    failures.append(violation('malformed-transcript', args.adapter))
                    continue
                try:
                    event_calls = extract_calls(args.adapter, event)
                    event_outputs = extract_outputs(args.adapter, event)
                except (AttributeError, TypeError):
                    failures.append(violation('unsupported-transcript-shape', args.adapter))
                    continue
                for call_id, name, data in event_calls:
                    if not isinstance(call_id, str) or not call_id:
                        failures.append(violation('missing-tool-call-id', args.adapter))
                        continue
                    if not isinstance(name, str) or not name or not isinstance(data, dict):
                        failures.append(violation('invalid-tool-call-shape', args.adapter))
                        continue
                    if call_id in calls:
                        if calls[call_id][:2] != (name, data):
                            failures.append(violation('duplicate-tool-call', args.adapter))
                        continue
                    explicit_turn = event.get('turn_id') or event.get('turnId') or event.get('message_id')
                    if args.adapter in ('claude', 'agent') and not explicit_turn:
                        explicit_turn = (event.get('message') or {}).get('id')
                    if explicit_turn:
                        turn = str(explicit_turn)
                    elif args.adapter in ('codex', 'grok', 'gemini'):
                        if implicit_output_seen:
                            implicit_turn += 1
                            implicit_output_seen = False
                        turn = 'implicit-' + str(implicit_turn)
                    else:
                        turn = f'event-{line_number}'
                    calls[call_id] = (name, data, turn)
                    turns.setdefault(turn, []).append(call_id)
                for call_id, success, value, non_execution in event_outputs:
                    if not isinstance(call_id, str) or not call_id:
                        failures.append(violation('missing-tool-call-id', args.adapter))
                        continue
                    if call_id not in calls:
                        failures.append(violation('orphan-tool-output', args.adapter))
                        continue
                    if call_id in outputs:
                        failures.append(violation('duplicate-tool-output', args.adapter))
                        continue
                    outputs[call_id] = {'success': success, 'value': value,
                                        'bytes': output_bytes(value),
                                        'non_execution': non_execution}
                    if calls[call_id][2].startswith('implicit-'):
                        implicit_output_seen = True
    except OSError:
        failures.append(violation('missing-transcript', args.adapter))
    attempted_calls = dict(calls)
    skipped = {
        call_id for call_id, (name, data, _) in calls.items()
        if call_id in outputs
        and claude_nonexecuted_exploration(args.adapter, name, data, outputs[call_id])
    }
    for call_id in skipped:
        calls.pop(call_id, None)
        outputs.pop(call_id, None)
    turns = {
        turn: [call_id for call_id in call_ids if call_id not in skipped]
        for turn, call_ids in turns.items()
        if any(call_id not in skipped for call_id in call_ids)
    }
    full_scope = any(line == 'Assigned scope: full' for line in prompt_lines)
    narrow = evidence_scoped and not full_scope
    turn_sizes = {}
    recognized_tool_calls = 0
    tool_ranges = []
    source_read_call_ids = set()
    source_batch_call_ids = set()
    verified_call_ranges = {}
    pending_source_ranges = []
    for call_id, (name, data, turn) in calls.items():
        call_failures = validate_call(
            name, data, roots, root, session, authorized, complete_paths, source_cache,
            dependency, args.adapter, source_batch_enabled)
        failures.extend(call_failures)
        if call_failures:
            blocked.add(call_id)
        if name.lower() in RECOGNIZED_TOOLS:
            recognized_tool_calls += 1
        if call_id not in outputs:
            failures.append(violation('missing-tool-output', name))
            continue
        output = outputs[call_id]
        size = output['bytes']
        turn_sizes[turn] = turn_sizes.get(turn, 0) + size
        if size > OUTPUT_BYTES and not byte_exempt(name, data, root, session, complete_paths):
            failures.append(violation('tool-output-too-large', name))
            blocked.add(call_id)
        if not output['success']:
            continue
        if too_many_results(name, data, output['value']):
            failures.append(violation('discovery-output-too-large', name))
        call_ranges = []
        try:
            direct = direct_source_range(name, data, root, source_cache, session)
            if direct is not None:
                call_ranges.append(direct)
            if name.lower() in SHELL_TOOLS:
                shell_ranges, unparseable = shell_source_ranges(
                    data.get('command', ''), root, source_cache, session)
                call_ranges.extend(shell_ranges)
                if unparseable:
                    failures.append(violation('unsupported-source-range', name))
        except (OSError, TypeError, ValueError):
            failures.append(violation('unsupported-source-range', name))
        if call_ranges:
            pending_source_ranges.append((call_id, name, output['value'], call_ranges))
            if source_batch_enabled and name.lower() in SHELL_TOOLS and len(call_ranges) > 1:
                try:
                    READONLY_POLICY.strict_source_batch(
                        unwrap_shell(data.get('command', '')), root)
                except (OSError, TypeError, ValueError, READONLY_POLICY.SourceBatchBlocked):
                    pass
                else:
                    source_batch_call_ids.add(call_id)
    manifest = None
    manifest_hash = None
    seat = None
    evidence_repository = None
    if declared_manifest_hash is not None:
        try:
            manifest, manifest_hash, seat, evidence_repository = load_evidence_manifest(
                session, declared_manifest_hash, prompt, root)
        except (AttributeError, ImportError, KeyError, OSError, TypeError, ValueError,
                json.JSONDecodeError):
            failures.append(violation('invalid-source-context', args.adapter))
        else:
            try:
                validate_assignment_prompt_binding(manifest, seat, prompt_lines)
            except (KeyError, TypeError, ValueError):
                failures.append(violation('invalid-assignment-prompt-binding', args.adapter))
            try:
                validate_plan_prompt_binding(manifest, seat, prompt, _load_evidence_module())
            except (KeyError, OSError, TypeError, ValueError):
                failures.append(violation('invalid-plan-prompt-binding', args.adapter))
            try:
                validate_prompt_artifact_set(manifest, seat, prompt, root, session)
            except (KeyError, OSError, TypeError, ValueError):
                failures.append(violation('invalid-prompt-artifact-set', args.adapter))
            try:
                failures.extend(validate_plan_first_call(
                    manifest, seat, args.adapter, attempted_calls, root, session))
            except (KeyError, OSError, TypeError, ValueError):
                failures.append(violation('invalid-plan-first-call', args.adapter))
    zero_tool_plan = False
    if manifest is not None and seat in manifest.get('assignments', {}):
        assignment = manifest['assignments'][seat]
        zero_tool_plan = (manifest.get('phase') == 'plan'
                          and assignment.get('plan_clusters') == []
                          and assignment.get('patch_bytes') == 0)
    if recognized_tool_calls == 0 and not zero_tool_plan:
        failures.append(violation('no-recognized-review-tools', args.adapter))

    frozen_entries = {}
    if evidence_repository is not None:
        try:
            for tree in dict.fromkeys((manifest['snapshot_tree'], manifest['base_tree'])):
                frozen_entries[tree] = evidence_repository.entries(tree)
        except (KeyError, OSError, TypeError, ValueError):
            failures.append(violation('invalid-source-context', args.adapter))
            frozen_entries = {}
    snapshot_tree = manifest.get('snapshot_tree') if manifest is not None else None
    for call_id, name, value, call_ranges in pending_source_ranges:
        if call_id in blocked:
            continue
        expected_values = []
        trees = frozen_entries
        if any('tree' in row for row in call_ranges):
            # The base or any other revision is context only: never a receipt, never a citation.
            if snapshot_tree not in frozen_entries \
                    or any(row.get('tree', snapshot_tree) != snapshot_tree for row in call_ranges):
                continue
            trees = {snapshot_tree: frozen_entries[snapshot_tree]}
            try:
                call_ranges = pinned_snapshot_ranges(
                    call_ranges, trees[snapshot_tree], evidence_repository)
            except (OSError, ValueError):
                call_ranges = None
            if call_ranges is None:
                failures.append(violation('source-output-mismatch', name))
                continue
            if not call_ranges:
                continue
            value = without_xcrun_preamble(value)
        try:
            if trees:
                for tree, entries in trees.items():
                    chunks = []
                    for row in call_ranges:
                        entry = entries.get(row['path'])
                        if entry is None:
                            break
                        raw = evidence_repository.blob(entry)
                        chunks.append(byte_range_lines(
                            split_lf_lines(raw), row['line_start'], row['line_end']))
                    else:
                        expected_values.append(b''.join(chunks))
            elif not evidence_scoped:
                expected_values.append(b''.join(line_range_bytes(
                    root / row['path'], row['line_start'], row['line_end'], source_cache)
                                                for row in call_ranges))
            matched = any(delivered_matches_bytes(
                args.adapter, name, value, expected, call_ranges[0]['line_start'])
                          for expected in expected_values)
        except (OSError, UnicodeError, ValueError):
            matched = False
        if matched:
            credited.add(call_id)
            source_read_call_ids.add(call_id)
            verified_call_ranges[call_id] = call_ranges
            tool_ranges.extend(call_ranges)
        else:
            failures.append(violation(
                'source-batch-output-mismatch' if call_id in source_batch_call_ids
                else 'source-output-mismatch', name))

    packet_ranges = []
    packet_bytes = 0
    packet_shards = 0
    assigned_patch_sha256 = None
    assigned_patch_bytes = 0
    assigned_patch_lines = 0
    assigned_patch_reads = 0
    assigned_patch_ranges = []
    patch_proof_mode = None
    patch_proof_calls = 0
    patch_proof_turns = 0
    patch_proof_visible_bytes = 0
    expected_patch_chunks = 0
    opened_patch_chunks = 0
    exact_patch_chunk_calls = set()
    exact_evidence_index_calls = set()
    required_segment_calls = []
    # Byte-proved ordered reads, credited or not: the pacing counts are taken over these.
    paced_chunk_calls = []
    paced_packet_calls = set()
    paced_index_calls = set()
    paced_segment_calls = []
    required_source_ranges = []
    required_source_role = None
    required_source_range_proofs = []
    plan_sha256 = None
    plan_cluster_search_proofs = []
    plan_cluster_source_proofs = []
    plan_artifact_sha256 = None
    plan_citation_ranges = []
    plan_finding_citations = 0
    manifest_blob_cache = {}
    if manifest is not None:
        try:
            context = manifest['source_context']['seats'][seat]
            required_source_ranges = context.get('required_source_ranges', [])
            required_source_role = context.get('role')
            required_segment_paths = {
                session / segment['artifact']: (required_index, required, segment)
                for required_index, required in enumerate(required_source_ranges)
                for segment in required['segments']
            }
            assigned = context['shards']
            assigned_paths = {session / shard['artifact']: shard for shard in assigned}
            evidence_index = session / f"r{manifest['label']}-evidence.md"
            for call_id, (name, data, _) in calls.items():
                output = outputs.get(call_id)
                if output is None or not output['success']:
                    continue
                if (evidence_index in paths_opened_by_call(name, data, root)
                        and complete_packet_read(name, data, evidence_index, root)
                        and delivered_matches(
                            args.adapter, name, output['value'], evidence_index,
                            1, file_line_count(evidence_index))):
                    paced_index_calls.add(call_id)
                    if call_id not in blocked:
                        credited.add(call_id)
                        exact_evidence_index_calls.add(call_id)
            if not exact_evidence_index_calls:
                failures.append(violation('missing-evidence-index', args.adapter))
            opened_packets = set()
            for call_id, (name, data, _) in calls.items():
                if call_id not in outputs:
                    continue
                output = outputs[call_id]
                if not output['success']:
                    continue
                for path in paths_opened_by_call(name, data, root):
                    if SOURCE_PACKET_NAME.fullmatch(path.name) and path.parent == session:
                        if path not in assigned_paths:
                            failures.append(violation('unassigned-source-packet', name))
                        else:
                            complete = complete_packet_read(name, data, path, root)
                            exact_output = complete and delivered_matches(
                                args.adapter, name, output['value'], path, 1, file_line_count(path))
                            if not complete:
                                failures.append(violation('partial-source-packet', name))
                            if complete and not exact_output:
                                failures.append(violation('source-packet-output-mismatch', name))
                            if exact_output:
                                paced_packet_calls.add(call_id)
                            if exact_output and call_id not in blocked:
                                credited.add(call_id)
                                opened_packets.add(path)
            for path in assigned_paths:
                if path not in opened_packets:
                    failures.append(violation('missing-source-packet', args.adapter))
            for path in sorted(opened_packets):
                shard = assigned_paths[path]
                packet_shards += 1
                packet_bytes += shard['bytes']
                for row in shard['ranges']:
                    packet_ranges.append({'path': row['path'], 'line_start': row['line_start'],
                                          'line_end': row['line_end'], 'origin': 'packet'})
            failures.extend(turn_batch_violations(
                calls, paced_packet_calls,
                manifest['source_context']['packet_batch_limit'],
                'source-packet-batch-too-large', args.adapter))

            assignment = manifest['assignments'][seat]
            assigned_patch = Path(assignment['patch']).resolve(strict=True)
            assigned_patch_raw = assigned_patch.read_bytes()
            assigned_patch_line_index = split_lf_lines(assigned_patch_raw)
            assigned_patch_sha256 = hashlib.sha256(assigned_patch_raw).hexdigest()
            assigned_patch_bytes = len(assigned_patch_raw)
            assigned_patch_lines = len(assigned_patch_line_index)
            if (assigned_patch_sha256 != assignment['patch_sha256']
                    or assigned_patch_bytes != assignment['patch_bytes']
                    or assigned_patch_lines != assignment['patch_lines']):
                raise ValueError('assigned patch changed after manifest validation')
            patch_proof_mode = assignment['patch_read_mode']
            if patch_proof_mode == 'chunks':
                patch_set = manifest['patch_sets'][assignment['patch_set']]
                expected_chunks = patch_set['chunks']
                expected_patch_chunks = len(expected_chunks)
                chunk_by_path = {session / row['artifact']: row for row in expected_chunks}
                observed = []
                exact_calls = []
                seen_chunk_paths = set()
                for call_id, (name, data, turn) in calls.items():
                    output = outputs.get(call_id)
                    if output is None or not output['success']:
                        continue
                    opened = paths_opened_by_call(name, data, root)
                    for path in opened:
                        if path.parent == session and PATCH_CHUNK_NAME.fullmatch(path.name):
                            if path not in chunk_by_path:
                                failures.append(violation('unassigned-patch-chunk', name))
                                continue
                            duplicate = path in seen_chunk_paths
                            row = chunk_by_path[path]
                            complete = complete_packet_read(name, data, path, root)
                            if not complete:
                                failures.append(violation('partial-patch-chunk', name))
                                continue
                            try:
                                metadata = path.lstat()
                                safe = (not path.is_symlink() and metadata.st_nlink == 1
                                        and path.is_file() and path.stat().st_size == row['bytes'])
                            except OSError:
                                safe = False
                            if not safe:
                                failures.append(violation('redirected-patch-chunk', name))
                                continue
                            if not delivered_matches_bytes(
                                    args.adapter, name, output['value'], path.read_bytes(), 1):
                                failures.append(violation('assigned-patch-output-mismatch', name))
                                continue
                            if duplicate:
                                failures.append(violation('duplicate-patch-chunk', name))
                                continue
                            paced_chunk_calls.append((call_id, turn))
                            if call_id in blocked:
                                continue
                            credited.add(call_id)
                            seen_chunk_paths.add(path)
                            observed.append(row['index'])
                            exact_calls.append((call_id, turn, output['bytes']))
                            exact_patch_chunk_calls.add(call_id)
                expected_order = [row['index'] for row in expected_chunks]
                if observed != sorted(observed):
                    failures.append(violation('reordered-patch-chunks', args.adapter))
                if observed != expected_order:
                    failures.append(violation('missing-assigned-patch-chunk', args.adapter))
                assigned_patch_reads = len(exact_calls)
                patch_proof_calls = assigned_patch_reads
                patch_proof_turns = len({turn for _, turn, _ in exact_calls})
                patch_proof_visible_bytes = sum(size for _, _, size in exact_calls)
                opened_patch_chunks = len(observed)
                batch_limit = adapter_read_batch_limit
                for turn in {turn for _, turn in paced_chunk_calls}:
                    if sum(call_turn == turn for _, call_turn in paced_chunk_calls) > batch_limit:
                        failures.append(violation('patch-chunk-batch-too-large', args.adapter))
            else:
                verified_patch_ranges = []
                proof_call_ids = set()
                proof_turns = set()
                for call_id, (name, data, turn) in calls.items():
                    output = outputs.get(call_id)
                    if output is None or not output['success']:
                        continue
                    requested = assigned_patch_ranges_for_call(
                        name, data, assigned_patch, root, assigned_patch_lines)
                    if len(requested) > 1:
                        failures.append(violation('ambiguous-assigned-patch-read', name))
                        continue
                    for start, end in requested:
                        if end < start and ranges_cover_file(
                                verified_patch_ranges, assigned_patch_lines):
                            failures.append(violation('redundant-assigned-patch-read', name))
                            continue
                        expected_patch = byte_range_lines(assigned_patch_line_index, start, end)
                        if delivered_matches_bytes(
                                args.adapter, name, output['value'], expected_patch, start):
                            if call_id in blocked:
                                continue
                            credited.add(call_id)
                            assigned_patch_reads += 1
                            verified_patch_ranges.append((start, end))
                            proof_call_ids.add(call_id)
                            proof_turns.add(turn)
                            patch_proof_visible_bytes += output['bytes']
                        else:
                            failures.append(violation('assigned-patch-output-mismatch', name))
                if not ranges_cover_file(verified_patch_ranges, assigned_patch_lines):
                    failures.append(violation('missing-assigned-patch-range', args.adapter))
                elif not ranges_cover_file_in_order(verified_patch_ranges, assigned_patch_lines):
                    failures.append(violation('evidence-read-order', args.adapter))
                assigned_patch_ranges = [
                    {'line_start': start, 'line_end': end}
                    for start, end in sorted(set(verified_patch_ranges)) if end >= start
                ]
                patch_proof_calls = len(proof_call_ids)
                patch_proof_turns = len(proof_turns)

            observed_required_segments = []
            required_segment_calls = []
            observed_by_required = {index: [] for index in range(len(required_source_ranges))}
            seen_required_segments = set()
            for call_id, (name, data, turn) in calls.items():
                output = outputs.get(call_id)
                if output is None or not output['success']:
                    continue
                for path in paths_opened_by_call(name, data, root):
                    if path.parent != session or not SOURCE_SEGMENT_NAME.fullmatch(path.name):
                        continue
                    assigned_segment = required_segment_paths.get(path)
                    if assigned_segment is None:
                        failures.append(violation('unassigned-required-source-segment', name))
                        continue
                    required_index, required, segment = assigned_segment
                    identity = (required_index, segment['index'])
                    duplicate = identity in seen_required_segments
                    if not complete_packet_read(name, data, path, root):
                        failures.append(violation('partial-required-source-segment', name))
                        continue
                    try:
                        metadata = path.lstat()
                        safe = (not path.is_symlink() and metadata.st_nlink == 1
                                and path.is_file() and metadata.st_size == segment['raw_bytes'])
                        raw = path.read_bytes() if safe else b''
                    except OSError:
                        safe = False
                        raw = b''
                    if not safe:
                        failures.append(violation('redirected-required-source-segment', name))
                        continue
                    if (hashlib.sha256(raw).hexdigest() != segment['content_sha256']
                            or not delivered_matches_bytes(
                                args.adapter, name, output['value'], raw, 1)):
                        failures.append(violation('required-source-output-mismatch', name))
                        continue
                    if duplicate:
                        failures.append(violation('duplicate-required-source-segment', name))
                        continue
                    paced_segment_calls.append((call_id, turn))
                    if call_id in blocked:
                        continue
                    credited.add(call_id)
                    seen_required_segments.add(identity)
                    observed_by_required[required_index].append(segment['index'])
                    observed_required_segments.append(identity)
                    required_segment_calls.append((call_id, turn))
                    tool_ranges.append({'path': required['path'],
                                        'line_start': segment['line_start'],
                                        'line_end': segment['line_end'], 'origin': 'tool'})
                    source_read_call_ids.add(call_id)
            for required_index, required in enumerate(required_source_ranges):
                try:
                    blob, blob_line_index = manifest_blob(
                        evidence_repository, required, manifest_blob_cache)
                    expected_required = byte_range_lines(
                        blob_line_index, required['line_start'], required['line_end'])
                    if hashlib.sha256(expected_required).hexdigest() != required['content_sha256']:
                        raise ValueError('required source content hash mismatch')
                    expected_segments = required['segments']
                    observed = observed_by_required[required_index]
                    for segment in expected_segments:
                        expected = byte_range_lines(
                            blob_line_index, segment['line_start'], segment['line_end'])
                        if (len(expected) != segment['raw_bytes']
                                or hashlib.sha256(expected).hexdigest() != segment['content_sha256']
                                or (session / segment['artifact']).read_bytes() != expected):
                            raise ValueError('required source segment identity mismatch')
                    expected_order = [row['index'] for row in expected_segments]
                    if observed != sorted(observed):
                        failures.append(violation('reordered-required-source-segments', args.adapter))
                    if observed != expected_order:
                        failures.append(violation('missing-required-source-segment', args.adapter))
                    if observed == expected_order:
                        required_source_range_proofs.append({
                            key: required[key] for key in (
                                'path', 'line_start', 'line_end', 'blob_tree', 'blob_oid',
                                'content_sha256')
                        })
                except (KeyError, OSError, TypeError, ValueError, UnicodeError):
                    failures.append(violation('invalid-required-source-identity', args.adapter))
            if observed_required_segments != sorted(observed_required_segments):
                failures.append(violation('reordered-required-source-segments', args.adapter))
            source_segment_batch_limit = adapter_read_batch_limit
            for turn in {turn for _, turn in paced_segment_calls}:
                if (sum(call_turn == turn for _, call_turn in paced_segment_calls)
                        > source_segment_batch_limit):
                    failures.append(violation('required-source-segment-batch-too-large', args.adapter))
            order_patch_calls = exact_patch_chunk_calls if patch_proof_mode == 'chunks' \
                else proof_call_ids
            order_packet_paths = list(assigned_paths)
            order_segment_paths = [
                session / segment['artifact']
                for required in required_source_ranges for segment in required['segments']
            ]
            failures.extend(evidence_order_violations(
                calls, outputs, order_patch_calls, order_packet_paths, order_segment_paths,
                evidence_index, root, session,
                verified_call_ranges))
            expansion_calls = [
                call_id for call_id, (name, data, _) in calls.items()
                if repository_expansion_call(name, data, root, session)
            ]
            if len(expansion_calls) > REPOSITORY_EXPANSION_CALL_LIMIT:
                failures.append(violation('repository-expansion-call-limit', args.adapter))
            ordered_proof_calls = ({call_id for call_id, _ in paced_chunk_calls}
                                   | {call_id for call_id, _ in paced_segment_calls}
                                   | paced_index_calls)
            for turn in turns:
                proof_reads = [call_id for call_id in turns[turn]
                               if call_id in ordered_proof_calls]
                if len(proof_reads) > adapter_read_batch_limit:
                    failures.append(violation('evidence-proof-batch-too-large', args.adapter))
            required_source_range_proofs.sort(key=lambda row: (
                row['path'], row['line_start'], row['line_end'], row['blob_tree'],
                row['blob_oid'], row['content_sha256']))
            component_ids = set(context['components'])
            boundary_paths = {
                path for component in manifest['components']
                if component['id'] in component_ids for path in component['boundary']
            }
            failures.extend(source_read_requirement_violations(
                context, boundary_paths, tool_ranges, args.adapter))
        except (KeyError, OSError, TypeError, ValueError):
            failures.append(violation('invalid-source-context', args.adapter))

    for turn, size in turn_sizes.items():
        if size <= OUTPUT_BYTES:
            continue
        output_calls = [call_id for call_id in turns.get(turn, []) if call_id in outputs]
        ordinary_exempt = (len(output_calls) == 1 and byte_exempt(
            calls[output_calls[0]][0], calls[output_calls[0]][1],
            root, session, complete_paths))
        proof_exempt = ordered_proof_turn_exempt(
            adapter_read_batch_limit, output_calls,
            exact_patch_chunk_calls
            | {call_id for call_id, _ in required_segment_calls}
            | exact_evidence_index_calls,
            size)
        if not ordinary_exempt and not proof_exempt:
            failures.append(violation('tool-turn-output-too-large', args.adapter))
            blocked.update(turns.get(turn, []))

    source_ranges = []
    for row in [*packet_ranges, *tool_ranges]:
        if row not in source_ranges:
            source_ranges.append(row)
    source_ranges.sort(key=lambda row: (row['path'], row['line_start'], row['line_end'], row['origin']))
    source_read_calls = len(source_read_call_ids)
    source_read_batches = len(source_read_call_ids & source_batch_call_ids)
    required_source_ranges_covered = len(required_source_range_proofs)
    if required_source_role == 'integration' \
            and required_source_ranges_covered != len(required_source_ranges):
        failures.append(violation('missing-required-source-range', args.adapter))
    if manifest is not None and manifest.get('phase') == 'plan':
        try:
            plan = manifest['plan']; plan_sha256 = plan['sha256']
            assigned_cluster_ids = set(assignment.get(
                'plan_clusters', [cluster['id'] for cluster in plan['clusters']]))
            assigned_clusters = [cluster for cluster in plan['clusters']
                                 if cluster['id'] in assigned_cluster_ids]
            plan_artifact_sha256 = plan['sha256']
            searches = []
            for call_id, (name, data, _) in calls.items():
                output = outputs.get(call_id)
                if output is None or not output['success'] or call_id in blocked:
                    continue
                result_text = output_text(output['value'])
                if result_text is None or len(split_lf_text(result_text)) > SEARCH_RESULTS:
                    continue
                result_paths = search_result_paths(output['value'])
                contract = None if result_paths is None else repository_search_pattern(name, data, root)
                if contract is not None:
                    searches.append((call_id, contract, output_digest(output['value']), result_paths))
            for cluster in assigned_clusters:
                site_paths = {row['path'] for row in cluster['paths'] if row['field'] == 'sites'}
                prepared = cluster.get('search_proof')
                if prepared is not None:
                    plan_cluster_search_proofs.append({
                        'cluster': cluster['id'], 'search_contract': cluster['search_contract'],
                        'call_id': 'prepared:' + prepared['artifact'],
                        'output_sha256': prepared['sha256']})
                else:
                    matches = [(call_id, result_hash) for call_id, contract, result_hash, result_paths in searches
                               if contract == cluster['search_contract'] and site_paths <= result_paths]
                    if not matches:
                        failures.append(violation('missing-plan-cluster-search', args.adapter))
                    else:
                        call_id, result_hash = matches[0]
                        plan_cluster_search_proofs.append({
                            'cluster': cluster['id'], 'search_contract': cluster['search_contract'],
                            'call_id': call_id, 'output_sha256': result_hash})
                for required in cluster['paths']:
                    relevant = [row for row in source_ranges if row['path'] == required['path']
                                and (required['line_start'] is None
                                     or (row['line_start'] <= required['line_end']
                                         and required['line_start'] <= row['line_end']))]
                    covered = (bool(relevant) if required['line_start'] is None
                               else required_range_covered(required, relevant))
                    if not covered:
                        failures.append(violation('missing-plan-cluster-source', args.adapter))
                        continue
                    plan_cluster_source_proofs.append({
                        'cluster': cluster['id'], 'path': required['path'],
                        'line_start': required['line_start'], 'line_end': required['line_end'],
                        'ranges': relevant})
        except (KeyError, TypeError, ValueError):
            failures.append(violation('invalid-plan-evidence', args.adapter))
    result_path = None
    result = None
    result_hash = None
    finding_citations = 0
    try:
        result_path, result = result_for_audit(args)
        if result_path is not None:
            result_hash = digest(result_path)
            plan_name = f"r{manifest['label']}-plan.md" if manifest is not None \
                and manifest.get('phase') == 'plan' else None
            plan_lines = len(split_lf_lines((session / plan_name).read_bytes())) if plan_name else 0
            for finding in result['findings']:
                if plan_name is not None and finding.get('file') == plan_name:
                    start = finding.get('line_start'); end = finding.get('line_end')
                    if (type(start) is int and type(end) is int
                            and 1 <= start <= end <= plan_lines):
                        plan_finding_citations += 1
                        plan_citation_ranges.append({'line_start': start, 'line_end': end})
                    else:
                        failures.append(violation('invalid-plan-finding-range', args.adapter))
                elif intersects(finding, source_ranges):
                    finding_citations += 1
                else:
                    failures.append(violation('unsubstantiated-finding-range', args.adapter))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        failures.append(violation('invalid-review-result', args.adapter))
    unique = []
    for item in failures:
        if item not in unique:
            unique.append(item)
    advisories = []
    if manifest is not None:
        fatal = [item for item in unique if item.get('code') not in ADVISORY_CODES]
        if not fatal:
            advisories = unique
            unique = []
    result = {
        'schema_version': 2,
        'status': 'invalid' if unique else 'valid',
        'evidence_scoped': evidence_scoped,
        'narrow': narrow,
        'adapter': args.adapter,
        'prompt_sha256': digest(args.prompt) if prompt.is_file() else None,
        'stream_sha256': digest(args.raw) if Path(args.raw).is_file() else None,
        'result_sha256': result_hash,
        'evidence_manifest_sha256': manifest_hash,
        'violations': unique,
        'advisories': advisories,
        'tool_calls': len(calls),
        'tool_turns': len(turns),
        'tool_output_bytes': sum(output['bytes'] for output in outputs.values()),
        'max_tool_output_bytes': max((output['bytes'] for output in outputs.values()), default=0),
        'recognized_tool_calls': recognized_tool_calls,
        'source_read_calls': source_read_calls,
        'source_read_batches': source_read_batches,
        'packet_shards': packet_shards,
        'packet_bytes': packet_bytes,
        'packet_ranges': sum(row['origin'] == 'packet' for row in source_ranges),
        'opened_source_ranges': sum(row['origin'] == 'tool' for row in source_ranges),
        'required_source_ranges_covered': required_source_ranges_covered,
        'required_source_range_proofs': required_source_range_proofs,
        'assigned_patch_sha256': assigned_patch_sha256,
        'assigned_patch_bytes': assigned_patch_bytes,
        'assigned_patch_lines': assigned_patch_lines,
        'assigned_patch_reads': assigned_patch_reads,
        'assigned_patch_ranges': assigned_patch_ranges,
        'patch_proof_mode': patch_proof_mode,
        'patch_proof_calls': patch_proof_calls,
        'patch_proof_turns': patch_proof_turns,
        'patch_proof_visible_bytes': patch_proof_visible_bytes,
        'expected_patch_chunks': expected_patch_chunks,
        'opened_patch_chunks': opened_patch_chunks,
        'plan_sha256': plan_sha256,
        'plan_cluster_search_proofs': plan_cluster_search_proofs,
        'plan_cluster_source_proofs': plan_cluster_source_proofs,
        'plan_artifact_sha256': plan_artifact_sha256,
        'plan_citation_ranges': plan_citation_ranges,
        'plan_finding_citations': plan_finding_citations,
        'finding_citations': finding_citations,
        'source_ranges': source_ranges,
    }
    return result, unique, blocked & credited


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    hooks = commands.add_parser('hook')
    hooks.add_argument('--root', required=True)
    hooks.add_argument('--session', required=True)
    hooks.add_argument('--prompt')
    hooks.add_argument('--deps')
    post_hooks = commands.add_parser('post-hook')
    post_hooks.add_argument('--root', required=True)
    post_hooks.add_argument('--session', required=True)
    post_hooks.add_argument('--prompt')
    post_hooks.add_argument('--deps')
    prompts = commands.add_parser('validate-prompt')
    prompts.add_argument('--root', required=True)
    prompts.add_argument('--session', required=True)
    prompts.add_argument('--manifest', required=True)
    prompts.add_argument('--seat', required=True, action='append')
    prompts.add_argument('--prompt', required=True, action='append')
    audits = commands.add_parser('audit')
    audits.add_argument('--adapter', required=True, choices=('codex', 'grok', 'gemini', 'claude', 'agent'))
    audits.add_argument('--result')
    audits.add_argument('--raw', required=True)
    audits.add_argument('--prompt', required=True)
    audits.add_argument('--root', required=True)
    audits.add_argument('--session', required=True)
    audits.add_argument('--deps')
    audits.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.command == 'hook':
        return hook(args)
    if args.command == 'post-hook':
        return post_hook(args)
    if args.command == 'validate-prompt':
        try:
            return validate_prompt(args)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            print('prompt validation: ' + str(error), file=sys.stderr)
            return 2
    return audit(args)


if __name__ == '__main__':
    sys.exit(main())
