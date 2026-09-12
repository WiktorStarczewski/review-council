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


READ_LINES = 240
SEARCH_RESULTS = 80
OUTPUT_BYTES = 32 * 1024
PATCH_TURN_OUTPUT_BYTES = 60 * 1024
PATCH_CHUNKS_PER_TURN = 2
READ_TOOLS = {'read', 'read_file'}
SEARCH_TOOLS = {'grep', 'search_file_content', 'search_files', 'code_search'}
SHELL_TOOLS = {'bash', 'shell', 'run_shell_command', 'run_terminal_command', 'command_execution'}
DISCOVERY_TOOLS = {'glob', 'list_directory'}
RECOGNIZED_TOOLS = READ_TOOLS | SEARCH_TOOLS | SHELL_TOOLS | DISCOVERY_TOOLS
SOURCE_PACKET_NAME = re.compile(r'^r[0-9A-Za-z._-]+-source-context-[1-9][0-9]*\.json$')
PATCH_CHUNK_NAME = re.compile(r'^r[0-9A-Za-z._-]+-patch-p[0-9]{2}-[0-9]{3}\.txt$')
FULL_ARTIFACT = re.compile(r'^r[0-9A-Za-z._-]+(?:-[0-9A-Za-z._-]+)?\.prompt\.md$|^r[0-9A-Za-z._-]+-(?:evidence|instructions|plan)\.md$')
SESSION_ARTIFACT = re.compile(r'^r[0-9A-Za-z._-]+(?:-[0-9A-Za-z._-]+)?(?:\.prompt\.md|\.patch)$|^r[0-9A-Za-z._-]+-(?:evidence|instructions|plan)\.(?:md|json)$')
SOURCE_COMMANDS = {
    'cat', 'less', 'more', 'rg', 'ripgrep', 'ag', 'grep', 'egrep', 'fgrep',
    'find', 'ls', 'tree', 'awk', 'nl', 'sort', 'uniq', 'cut', 'jq', 'yq',
    'bat', 'strings', 'xxd', 'od', 'diff',
}


def load_readonly_policy():
    path = Path(__file__).with_name('readonly-bash-guard.py')
    spec = importlib.util.spec_from_file_location('review_council_readonly_bash_guard', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load read-only shell policy')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


READONLY_POLICY = load_readonly_policy()


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
        session is not None and PATCH_CHUNK_NAME.fullmatch(path.name) is not None
        and path.parent == session)


def session_artifact(path, session):
    return session is not None \
        and bool(SESSION_ARTIFACT.fullmatch(path.name) or SOURCE_PACKET_NAME.fullmatch(path.name)
                 or PATCH_CHUNK_NAME.fullmatch(path.name)) \
        and path.parent == session


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


def unwrap_shell(command):
    try:
        words = shlex.split(command)
    except ValueError:
        return command
    if len(words) == 3 and Path(words[0]).name in ('bash', 'sh', 'zsh', 'dash', 'ksh') and words[1] in ('-c', '-lc'):
        return words[2]
    return command


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
    for index, token in enumerate(words[1:], 1):
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


def line_limiter(words, maximum=READ_LINES):
    if not words:
        return False
    name = Path(words[0]).name
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


def file_line_count(path):
    raw = path.read_bytes()
    return raw.count(b'\n') + (1 if raw and not raw.endswith(b'\n') else 0)


def repository_file_candidates(words, root):
    found = []
    for candidate in path_candidates(words, root):
        try:
            target = resolved(candidate, root)
            target.relative_to(root)
        except (OSError, ValueError):
            continue
        try:
            if target.is_file():
                found.append(target)
        except OSError:
            continue
    return found


def canonical_range(path, start, end, root, origin='tool'):
    try:
        relative = path.relative_to(root).as_posix()
        total = file_line_count(path)
    except (OSError, ValueError):
        return None
    start = max(1, start)
    end = min(end, total)
    if start > end:
        return None
    return {'path': relative, 'line_start': start, 'line_end': end, 'origin': origin}


def shell_source_ranges(command, root):
    """Return exact current-source ranges and whether a source read was unparseable."""
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
        for position, words in enumerate(pipeline):
            if not words or Path(words[0]).name not in direct_source:
                continue
            files = repository_file_candidates(words, root)
            if not files:
                continue
            if len(files) != 1:
                unparseable = True
                continue
            name = Path(words[0]).name
            total_lines = file_line_count(files[0])
            selected = limiter_range(words, total_lines) if len(pipeline) == 1 else None
            if selected is None and name in transparent and position == 0 and len(pipeline) == 2:
                selected = limiter_range(pipeline[1], total_lines)
            if selected is None:
                unparseable = True
                continue
            for path in files:
                item = canonical_range(path, selected[0], selected[1], root)
                if item is not None:
                    ranges.append(item)
    return ranges, unparseable


def direct_source_range(name, data, root):
    if name.lower() not in READ_TOOLS:
        return None
    raw_path = tool_path(data)
    if raw_path is None:
        return None
    target = resolved(raw_path, root)
    try:
        target.relative_to(root)
    except ValueError:
        return None
    offset = next((data[key] for key in ('offset', 'start_line', 'line_start') if key in data), None)
    limit = next((data[key] for key in ('limit', 'line_limit', 'max_lines') if key in data), None)
    try:
        return canonical_range(target, int(offset), int(offset) + int(limit) - 1, root)
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
    if name in ('rg', 'ripgrep', 'ag', 'grep', 'egrep', 'fgrep'):
        return True
    if name != 'git':
        return False
    index = 1
    while index < len(words) and words[index].startswith('-'):
        index += 2 if words[index] in ('-C', '-c') else 1
    return index < len(words) and words[index] == 'grep'


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
                or not line_limiter(command_words(parts[1][0]), SEARCH_RESULTS)):
            return None
        contract, paths = strict_search_words(command_words(parts[0][0]))
        if paths == ['.']:
            return contract
    except (OSError, ValueError):
        return None
    return None


def shell_violations(command, roots, root, session):
    tool = 'Bash'
    command = unwrap_shell(command)
    if contains_unquoted(command, '<'):
        return [violation('unsupported-shell-input-redirection', tool)]
    try:
        READONLY_POLICY.validate(command)
    except Exception:
        return [violation('unsupported-shell-command', tool)]
    if any(token in command for token in ('`', '$(')):
        return [violation('unsupported-shell-shape', tool)]
    try:
        parts = split_shell(command)
        parsed = [(command_words(part), separator) for part, separator in parts]
    except ValueError:
        return [violation('unsupported-shell-shape', tool)]
    for words, _ in parsed:
        if words and words[0] in ('for', 'while', 'until', 'if', 'then', 'do', 'case', '{'):
            return [violation('unsupported-shell-shape', tool)]
        for candidate in path_candidates(words, root):
            try:
                path = resolved(candidate, root)
            except (OSError, ValueError):
                return [violation('unresolved-path-variable', tool)]
            if not inside(path, roots) and not session_artifact(path, session):
                return [violation('path-outside-scope', tool)]
    pipelines = []
    current = []
    for item in parsed:
        current.append(item[0])
        if item[1] != '|':
            pipelines.append(current)
            current = []
    if current:
        pipelines.append(current)
    for pipeline in pipelines:
        for position, words in enumerate(pipeline):
            if not words:
                continue
            name = Path(words[0]).name
            is_source = name in SOURCE_COMMANDS or (name == 'git' and git_source(words))
            if name in ('head', 'tail', 'sed'):
                is_source = not line_limiter(words)
            if name == 'cat':
                try:
                    operands = [resolved(value, root) for value in path_candidates(words, root)]
                except OSError:
                    return [violation('unresolved-path-variable', tool)]
                if operands and all(complete_read_artifact(path, session) for path in operands):
                    is_source = False
            maximum = SEARCH_RESULTS if shell_search_producer(words) else READ_LINES
            if is_source and not any(line_limiter(later, maximum) for later in pipeline[position + 1:]):
                return [violation('unbounded-shell-output', tool)]
    _, unparseable = shell_source_ranges(command, root)
    if unparseable:
        return [violation('unsupported-source-range', tool)]
    return []


def validate_call(name, data, roots, root, session):
    normalized = name.lower()
    path = tool_path(data)
    if path is not None:
        try:
            target = resolved(path, root)
        except (OSError, ValueError):
            return [violation('unresolved-path-variable', name)]
        if not inside(target, roots) and not session_artifact(target, session):
            return [violation('path-outside-scope', name)]
    if normalized in READ_TOOLS:
        if path is None:
            return [violation('missing-read-path', name)]
        try:
            complete = complete_read_artifact(resolved(path, root), session)
        except OSError:
            return [violation('unresolved-path-variable', name)]
        if complete:
            return []
        if not explicit_offset(data) or not positive_bound(data, ('limit', 'line_limit', 'max_lines'), READ_LINES):
            return [violation('unbounded-read', name)]
    elif normalized in SEARCH_TOOLS:
        if not positive_bound(data, ('head_limit', 'max_results', 'limit'), SEARCH_RESULTS):
            return [violation('unbounded-search', name)]
    elif normalized in SHELL_TOOLS:
        command = data.get('command')
        if not isinstance(command, str) or not command.strip():
            return [violation('missing-shell-command', name)]
        return shell_violations(command, roots, root, session)
    return []


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


def search_result_paths(value):
    text = output_text(value)
    if text is None:
        return None
    lines = text.splitlines()
    if not lines or len(lines) >= SEARCH_RESULTS:
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
                    return [(item.get('id'), success, item[key])]
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
        return [(event.get('toolCallId'), event.get('status') == 'completed', value)]
    elif adapter == 'gemini' and event.get('type') == 'tool_result':
        for key in ('output', 'content', 'result'):
            if key in event:
                return [(event.get('tool_id'), event.get('status') == 'success', event[key])]
    elif adapter == 'claude' and event.get('type') == 'user':
        found = []
        for block in (event.get('message') or {}).get('content', []):
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                found.append((block.get('tool_use_id'), block.get('is_error') is not True,
                              block.get('content')))
        return found
    return []


def byte_exempt(name, data, root, session):
    if name.lower() not in READ_TOOLS:
        return False
    path = tool_path(data)
    try:
        return path is not None and full_artifact(resolved(path, root), session)
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


def load_evidence_manifest(session, prompt_lines, prompt, root):
    tokens = [line.split(': ', 1)[1] for line in prompt_lines
              if re.fullmatch(r'Evidence manifest SHA-256: [0-9a-f]{64}', line)]
    if not tokens:
        return None, None, None, None
    if len(tokens) != 1:
        raise ValueError('ambiguous evidence manifest hash')
    matches = [path for path in session.glob('r*-evidence.manifest.json')
               if path.is_file() and digest(path) == tokens[0]]
    if len(matches) != 1:
        raise ValueError('evidence manifest hash does not resolve uniquely')
    path = matches[0]
    script = Path(__file__).resolve().parent.parent / 'rev-evidence.py'
    spec = importlib.util.spec_from_file_location('review_council_audit_evidence', script)
    if spec is None or spec.loader is None:
        raise ValueError('evidence validator unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest, manifest_hash = module.validated_manifest(path)
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
        return repository_file_candidates(words, root) == [] and packet in paths_opened_by_call(name, data, root)
    except (OSError, ValueError):
        return False


def line_range_bytes(path, start, end):
    return byte_range(path.read_bytes(), start, end)


def byte_range(raw, start, end):
    return byte_range_lines(raw.splitlines(keepends=True), start, end)


def byte_range_lines(lines, start, end):
    if end < start:
        return b''
    return b''.join(lines[start - 1:end])


def strip_number_prefixes(text, start, separator):
    cleaned = []
    for index, line in enumerate(text.splitlines(keepends=True), start):
        prefix = str(index) + separator
        cleaned.append(line[len(prefix):] if line.startswith(prefix) else line)
    return ''.join(cleaned)


def delivered_matches(adapter, name, output, path, start, end):
    return delivered_matches_bytes(adapter, name, output, line_range_bytes(path, start, end), start)


def delivered_matches_bytes(adapter, name, output, expected, start):
    text = output_text(output)
    if text is None:
        return False
    candidates = [text]
    normalized = []
    if name.lower() in READ_TOOLS:
        if adapter == 'grok':
            normalized.append(strip_number_prefixes(text, start, '→'))
        elif adapter in ('claude', 'agent'):
            normalized.append(strip_number_prefixes(text, start, '\t'))
        candidates.extend(normalized)
        candidates.extend(candidate + '\n' for candidate in list(candidates)
                          if not candidate.endswith('\n'))
        expected_lines = len(expected.splitlines(keepends=True))
        if len(text.splitlines()) == expected_lines:
            candidates.extend(candidate + '\n' for candidate in normalized
                              if candidate.endswith('\n'))
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
    cache[key] = raw, raw.splitlines(keepends=True)
    return cache[key]


def git_blob_read_range(name, data, row, total_lines, object_repository):
    if name.lower() not in SHELL_TOOLS:
        return None
    command = data.get('command')
    if not isinstance(command, str):
        return None
    try:
        parts = split_shell(unwrap_shell(command))
        if len(parts) != 2 or parts[0][1] != '|' or parts[1][1] != '':
            return None
        producer = command_words(parts[0][0])
        limiter = command_words(parts[1][0])
        expected = ['git', '--git-dir=' + object_repository, 'show', row['blob_oid']]
        if producer != expected:
            return None
        selected = limiter_range(limiter, total_lines)
        if selected is None:
            return None
        start, end = selected
        end = min(end, total_lines)
        return (start, end) if start <= end else None
    except (TypeError, ValueError):
        return None


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


def ranges_cover_file(ranges, total_lines):
    if total_lines == 0:
        return bool(ranges)
    cursor = 1
    for start, end in sorted(set(ranges)):
        if start > cursor:
            return False
        cursor = max(cursor, end + 1)
    return cursor == total_lines + 1


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
    try:
        event = json.load(sys.stdin)
        name = event.get('tool_name', '')
        data = event.get('tool_input') or {}
        root = Path(args.root).resolve()
        session = Path(args.session).resolve()
        roots = allowed_roots(root, session, args.deps)
        failures = validate_call(name, data, roots, root, session)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        failures = [violation('invalid-hook-payload', 'unknown')]
    if failures:
        print('review read blocked: ' + failures[0]['code'], file=sys.stderr)
        return 2
    return 0


def post_hook(args):
    try:
        event = json.load(sys.stdin)
        name = event.get('tool_name', '')
        data = event.get('tool_input') or {}
        root = Path(args.root).resolve()
        session = Path(args.session).resolve()
        size = output_bytes(event.get('tool_response'))
        blocked = size > OUTPUT_BYTES and not byte_exempt(name, data, root, session)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        blocked = True
    if blocked:
        print('review read blocked: tool-output-too-large', file=sys.stderr)
        return 2
    return 0


def audit(args):
    root = Path(args.root).resolve()
    session = Path(args.session).resolve()
    roots = allowed_roots(root, session, args.deps)
    failures = []
    calls = {}
    outputs = {}
    turns = {}
    implicit_turn = 0
    implicit_pending = set()
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
                    elif args.adapter in ('grok', 'gemini'):
                        if not implicit_pending and any(str(value).startswith('implicit-') for value in turns):
                            implicit_turn += 1
                        turn = 'implicit-' + str(implicit_turn)
                        implicit_pending.add(call_id)
                    else:
                        turn = f'event-{line_number}'
                    calls[call_id] = (name, data, turn)
                    turns.setdefault(turn, []).append(call_id)
                    failures.extend(validate_call(name, data, roots, root, session))
                for call_id, success, value in event_outputs:
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
                                        'bytes': output_bytes(value)}
                    implicit_pending.discard(call_id)
    except OSError:
        failures.append(violation('missing-transcript', args.adapter))
    prompt = Path(args.prompt)
    try:
        prompt_lines = prompt.read_text().splitlines()
    except OSError:
        prompt_lines = []
        failures.append(violation('missing-prompt', args.adapter))
    has_manifest = any(line.startswith('Evidence manifest SHA-256: ') for line in prompt_lines)
    full_scope = any(line == 'Assigned scope: full' for line in prompt_lines)
    narrow = has_manifest and not full_scope
    turn_sizes = {}
    recognized_tool_calls = 0
    tool_ranges = []
    source_read_call_ids = set()
    verified_call_ranges = {}
    for call_id, (name, data, turn) in calls.items():
        if name.lower() in RECOGNIZED_TOOLS:
            recognized_tool_calls += 1
        if call_id not in outputs:
            failures.append(violation('missing-tool-output', name))
            continue
        output = outputs[call_id]
        size = output['bytes']
        turn_sizes[turn] = turn_sizes.get(turn, 0) + size
        if not output['success']:
            failures.append(violation('failed-tool-output', name))
            continue
        if size > OUTPUT_BYTES and not byte_exempt(name, data, root, session):
            failures.append(violation('tool-output-too-large', name))
        call_ranges = []
        try:
            direct = direct_source_range(name, data, root)
            if direct is not None:
                call_ranges.append(direct)
            if name.lower() in SHELL_TOOLS:
                shell_ranges, unparseable = shell_source_ranges(data.get('command', ''), root)
                call_ranges.extend(shell_ranges)
                if unparseable:
                    failures.append(violation('unsupported-source-range', name))
        except (OSError, TypeError, ValueError):
            failures.append(violation('unsupported-source-range', name))
        if call_ranges:
            try:
                expected = b''.join(line_range_bytes(root / row['path'], row['line_start'], row['line_end'])
                                    for row in call_ranges)
                matched = delivered_matches_bytes(args.adapter, name, output['value'], expected,
                                                  call_ranges[0]['line_start'])
            except (OSError, UnicodeError, ValueError):
                matched = False
            if matched:
                source_read_call_ids.add(call_id)
                verified_call_ranges[call_id] = call_ranges
                tool_ranges.extend(call_ranges)
            else:
                failures.append(violation('source-output-mismatch', name))
    if recognized_tool_calls == 0:
        failures.append(violation('no-recognized-review-tools', args.adapter))

    manifest = None
    manifest_hash = None
    seat = None
    evidence_repository = None
    try:
        manifest, manifest_hash, seat, evidence_repository = load_evidence_manifest(
            session, prompt_lines, prompt, root)
    except (AttributeError, ImportError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        failures.append(violation('invalid-source-context', args.adapter))

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
            assigned = context['shards']
            assigned_paths = {session / shard['artifact']: shard for shard in assigned}
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

            assignment = manifest['assignments'][seat]
            assigned_patch = Path(assignment['patch']).resolve(strict=True)
            assigned_patch_raw = assigned_patch.read_bytes()
            assigned_patch_line_index = assigned_patch_raw.splitlines(keepends=True)
            assigned_patch_sha256 = hashlib.sha256(assigned_patch_raw).hexdigest()
            assigned_patch_bytes = len(assigned_patch_raw)
            assigned_patch_lines = len(assigned_patch_line_index)
            if (assigned_patch_sha256 != assignment['patch_sha256']
                    or assigned_patch_bytes != assignment['patch_bytes']
                    or assigned_patch_lines != assignment['patch_lines']):
                raise ValueError('assigned patch changed after manifest validation')
            patch_proof_mode = assignment.get('patch_read_mode', 'windows')
            if patch_proof_mode == 'chunks':
                patch_set = manifest['patch_sets'][assignment['patch_set']]
                expected_chunks = patch_set['chunks']
                expected_patch_chunks = len(expected_chunks)
                chunk_by_path = {session / row['artifact']: row for row in expected_chunks}
                observed = []
                exact_calls = []
                seen_chunk_paths = set()
                call_positions = {call_id: index for index, call_id in enumerate(calls)}
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
                            if path in seen_chunk_paths:
                                failures.append(violation('duplicate-patch-chunk', name))
                                continue
                            seen_chunk_paths.add(path)
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
                            observed.append(row['index'])
                            exact_calls.append((call_id, turn, output['bytes']))
                            exact_patch_chunk_calls.add(call_id)
                expected_order = [row['index'] for row in expected_chunks]
                if observed != sorted(observed):
                    failures.append(violation('reordered-patch-chunks', args.adapter))
                if observed != expected_order:
                    failures.append(violation('missing-assigned-patch-chunk', args.adapter))
                if exact_calls:
                    last_chunk_position = max(call_positions[call_id] for call_id, _, _ in exact_calls)
                    final_chunk_turns = {turn for call_id, turn, _ in exact_calls
                                         if call_positions[call_id] == last_chunk_position}
                    for call_id, (name, data, turn) in calls.items():
                        opened = paths_opened_by_call(name, data, root)
                        if any(path in assigned_paths or path in chunk_by_path for path in opened):
                            continue
                        expands = verified_call_ranges.get(call_id) \
                            or repository_expansion_call(name, data, root, session)
                        if expands and (call_positions[call_id] < last_chunk_position
                                        or turn in final_chunk_turns):
                            failures.append(violation('patch-chunk-read-order', name))
                    packet_calls = [
                        (call_positions[call_id], turn)
                        for call_id, (name, data, turn) in calls.items()
                        if any(path in assigned_paths for path in paths_opened_by_call(name, data, root))
                    ]
                    if any(position < last_chunk_position or turn in final_chunk_turns
                           for position, turn in packet_calls):
                        failures.append(violation('patch-chunk-read-order', args.adapter))
                assigned_patch_reads = len(exact_calls)
                patch_proof_calls = assigned_patch_reads
                patch_proof_turns = len({turn for _, turn, _ in exact_calls})
                patch_proof_visible_bytes = sum(size for _, _, size in exact_calls)
                opened_patch_chunks = len(observed)
                batch_limit = PATCH_CHUNKS_PER_TURN if assignment['adapter'] in ('claude', 'grok') else 1
                for turn in {turn for _, turn, _ in exact_calls}:
                    if sum(call_turn == turn for _, call_turn, _ in exact_calls) > batch_limit:
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
                        expected_patch = byte_range_lines(assigned_patch_line_index, start, end)
                        if delivered_matches_bytes(
                                args.adapter, name, output['value'], expected_patch, start):
                            assigned_patch_reads += 1
                            verified_patch_ranges.append((start, end))
                            proof_call_ids.add(call_id)
                            proof_turns.add(turn)
                            patch_proof_visible_bytes += output['bytes']
                        else:
                            failures.append(violation('assigned-patch-output-mismatch', name))
                if not ranges_cover_file(verified_patch_ranges, assigned_patch_lines):
                    failures.append(violation('missing-assigned-patch-range', args.adapter))
                assigned_patch_ranges = [
                    {'line_start': start, 'line_end': end}
                    for start, end in sorted(set(verified_patch_ranges)) if end >= start
                ]
                patch_proof_calls = len(proof_call_ids)
                patch_proof_turns = len(proof_turns)

            observed_required_segments = []
            required_segment_calls = []
            for required_index, required in enumerate(required_source_ranges):
                try:
                    blob, blob_line_index = manifest_blob(
                        evidence_repository, required, manifest_blob_cache)
                    expected_required = byte_range_lines(
                        blob_line_index, required['line_start'], required['line_end'])
                    if hashlib.sha256(expected_required).hexdigest() != required['content_sha256']:
                        raise ValueError('required source content hash mismatch')
                    expected_segments = required['segments']
                    expected_by_bounds = {
                        (row['line_start'], row['line_end']): row for row in expected_segments}
                    observed = []
                    seen = set()
                    for call_id, (name, data, turn) in calls.items():
                        output = outputs.get(call_id)
                        if output is None or not output['success']:
                            continue
                        live_candidates = [row for row in verified_call_ranges.get(call_id, [])
                                           if row['path'] == required['path']]
                        for row in live_candidates:
                            if (row['line_end'] < required['line_start']
                                    or row['line_start'] > required['line_end']):
                                continue
                            expected = byte_range_lines(
                                blob_line_index, row['line_start'], row['line_end'])
                            if not delivered_matches_bytes(
                                    args.adapter, name, output['value'], expected, row['line_start']):
                                failures.append(violation('required-source-output-mismatch', name))
                        blob_read = git_blob_read_range(
                            name, data, required, len(blob_line_index),
                            manifest['source_context']['object_repository'])
                        if blob_read is None:
                            continue
                        segment = expected_by_bounds.get(blob_read)
                        if segment is None:
                            if not (blob_read[1] < required['line_start']
                                    or blob_read[0] > required['line_end']):
                                failures.append(violation('required-source-segment-bounds', name))
                            continue
                        identity = (required_index, segment['index'])
                        if identity in seen:
                            failures.append(violation('duplicate-required-source-segment', name))
                            continue
                        expected = byte_range_lines(blob_line_index, *blob_read)
                        if (len(expected) != segment['raw_bytes']
                                or hashlib.sha256(expected).hexdigest() != segment['content_sha256']
                                or not delivered_matches_bytes(
                                    args.adapter, name, output['value'], expected, blob_read[0])):
                            failures.append(violation('required-source-output-mismatch', name))
                            continue
                        seen.add(identity)
                        observed.append(segment['index'])
                        observed_required_segments.append(identity)
                        required_segment_calls.append((call_id, turn))
                        tool_ranges.append({'path': required['path'],
                                            'line_start': blob_read[0], 'line_end': blob_read[1],
                                            'origin': 'tool'})
                        source_read_call_ids.add(call_id)
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
            source_segment_batch_limit = 2 if assignment['adapter'] in ('claude', 'grok') else 1
            for turn in {turn for _, turn in required_segment_calls}:
                if (sum(call_turn == turn for _, call_turn in required_segment_calls)
                        > source_segment_batch_limit):
                    failures.append(violation('required-source-segment-batch-too-large', args.adapter))
            required_source_range_proofs.sort(key=lambda row: (
                row['path'], row['line_start'], row['line_end'], row['blob_tree'],
                row['blob_oid'], row['content_sha256']))
            if context['source_read_required']:
                component_ids = set(context['components'])
                boundary_paths = {
                    path for component in manifest['components']
                    if component['id'] in component_ids for path in component['boundary']
                }
                boundary_reads = [opened for opened in tool_ranges
                                  if opened['path'] in boundary_paths]
                required_reads = [
                    opened for opened in tool_ranges
                    if any(opened['path'] == required['path']
                           and opened['line_start'] <= required['line_end']
                           and required['line_start'] <= opened['line_end']
                           for required in required_source_ranges)
                ]
                if (not boundary_reads and not required_reads) \
                        or (context['role'] == 'specialist'
                            and required_source_ranges and not required_reads):
                    failures.append(violation('missing-required-source-read', args.adapter))
        except (KeyError, OSError, TypeError, ValueError):
            failures.append(violation('invalid-source-context', args.adapter))

    for turn, size in turn_sizes.items():
        if size <= OUTPUT_BYTES:
            continue
        output_calls = [call_id for call_id in turns.get(turn, []) if call_id in outputs]
        ordinary_exempt = all(byte_exempt(calls[call_id][0], calls[call_id][1], root, session)
                              for call_id in output_calls)
        patch_exempt = (args.adapter in ('claude', 'grok')
                        and size <= PATCH_TURN_OUTPUT_BYTES
                        and 1 < len(output_calls) <= PATCH_CHUNKS_PER_TURN
                        and all(call_id in exact_patch_chunk_calls for call_id in output_calls))
        if not ordinary_exempt and not patch_exempt:
            failures.append(violation('tool-turn-output-too-large', args.adapter))

    source_ranges = []
    for row in [*packet_ranges, *tool_ranges]:
        if row not in source_ranges:
            source_ranges.append(row)
    source_ranges.sort(key=lambda row: (row['path'], row['line_start'], row['line_end'], row['origin']))
    source_read_calls = len(source_read_call_ids)
    required_source_ranges_covered = len(required_source_range_proofs)
    if required_source_role == 'integration' \
            and required_source_ranges_covered != len(required_source_ranges):
        failures.append(violation('missing-required-source-range', args.adapter))
    if manifest is not None and manifest.get('phase') == 'plan':
        try:
            plan = manifest['plan']; plan_sha256 = plan['sha256']
            plan_artifact_sha256 = plan['sha256']
            searches = []
            for call_id, (name, data, _) in calls.items():
                output = outputs.get(call_id)
                if output is None or not output['success']:
                    continue
                result_paths = search_result_paths(output['value'])
                contract = None if result_paths is None else repository_search_pattern(name, data, root)
                if contract is not None:
                    searches.append((call_id, contract, output_digest(output['value']), result_paths))
            for cluster in plan['clusters']:
                site_paths = {row['path'] for row in cluster['paths'] if row['field'] == 'sites'}
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
            plan_lines = len((session / plan_name).read_bytes().splitlines()) if plan_name else 0
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
    result = {
        'schema_version': 2,
        'status': 'invalid' if unique else 'valid',
        'narrow': narrow,
        'adapter': args.adapter,
        'prompt_sha256': digest(args.prompt) if prompt.is_file() else None,
        'stream_sha256': digest(args.raw) if Path(args.raw).is_file() else None,
        'result_sha256': result_hash,
        'evidence_manifest_sha256': manifest_hash,
        'violations': unique,
        'tool_calls': len(calls),
        'tool_turns': len(turns),
        'tool_output_bytes': sum(output['bytes'] for output in outputs.values()),
        'max_tool_output_bytes': max((output['bytes'] for output in outputs.values()), default=0),
        'recognized_tool_calls': recognized_tool_calls,
        'source_read_calls': source_read_calls,
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
    publish(args.out, result)
    return 2 if unique else 0


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    hooks = commands.add_parser('hook')
    hooks.add_argument('--root', required=True)
    hooks.add_argument('--session', required=True)
    hooks.add_argument('--deps')
    post_hooks = commands.add_parser('post-hook')
    post_hooks.add_argument('--root', required=True)
    post_hooks.add_argument('--session', required=True)
    post_hooks.add_argument('--deps')
    audits = commands.add_parser('audit')
    audits.add_argument('--adapter', required=True, choices=('codex', 'grok', 'gemini', 'claude', 'agent'))
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
    return audit(args)


if __name__ == '__main__':
    sys.exit(main())
