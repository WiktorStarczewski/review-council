#!/usr/bin/env python3
"""PreToolUse hook for the rev-reviewer agent: allow only read-shaped Bash commands.

Read, Grep and Glob are the reviewer's primary tools. Bash exists for the handful of things
they cannot do — `git diff`/`log`/`show`, `rg`, and running the project's test suite — and for
nothing else. This guard is therefore an ALLOWLIST: a command runs only if every segment's
program is on the list below and its arguments carry no write-shaped flag. A denylist cannot
enforce that contract (`/usr/bin/git commit`, `command git push`, `python3 -c "open(f,'w')"`,
`sed -i.bak`, `env X=1 git push`, backticks … are all trivially outside any fixed pattern set).

stdin: Claude Code hook JSON ({"tool_name": "Bash", "tool_input": {"command": "..."}}).
exit 0 = allow; exit 2 = block (stderr is shown to the agent as the reason).
Fails OPEN on a payload it cannot parse (not a Bash call we understand), CLOSED on anything else.
"""
import json
import os
import re
import shlex
import sys


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- allowlists

READ_CMDS = {
    'git', 'rg', 'grep', 'egrep', 'fgrep', 'cat', 'head', 'tail', 'less', 'more', 'ls', 'find',
    'wc', 'sort', 'uniq', 'cut', 'tr', 'awk', 'sed', 'nl', 'diff', 'file', 'stat', 'du', 'df',
    'pwd', 'echo', 'printf', 'true', 'false', 'test', '[', 'jq', 'yq', 'basename', 'dirname',
    'realpath', 'readlink', 'which', 'type', 'env', 'date', 'sleep', 'cd', 'tree', 'column',
    'paste', 'comm', 'xxd', 'od', 'strings', 'md5', 'shasum', 'shasum256', 'ag', 'ripgrep',
    'fd', 'bat', 'read', ':',                                  # shell builtins that only read input / no-op
}
TEST_RUNNERS = {'npx', 'yarn', 'npm', 'pnpm', 'cargo', 'pytest', 'go'}
# named explicitly so the refusal says why, even though none of them is on the allowlist anyway
HARD_DENY = {
    'eval', 'exec', 'source', '.', 'sudo', 'xargs', 'bash', 'sh', 'zsh', 'ksh', 'dash',
    'python', 'python2', 'python3', 'node', 'ruby', 'perl', 'php', 'osascript', 'tee',
}
ALLOWED_ASSIGNMENTS = {'GIT_PAGER', 'PAGER', 'LC_ALL', 'LANG', 'TZ', 'NO_COLOR'}

GIT_READONLY = {
    'diff', 'log', 'show', 'status', 'blame', 'grep', 'ls-files', 'ls-tree', 'rev-parse',
    'merge-base', 'cat-file', 'describe', 'rev-list', 'shortlog', 'name-rev', 'for-each-ref',
    'show-ref', 'branch', 'tag', 'remote', 'config',
}
GIT_LIST_ONLY = {'branch', 'tag', 'config'}                    # read forms only, never a mutation
GIT_LIST_FLAGS = re.compile(r'^(--list|-l|-a|-r|-v|-vv|--all|--remotes|--verbose|--show-current|--contains(=.*)?|--merged(=.*)?|--no-merged(=.*)?|--points-at(=.*)?|--format(=.*)?|--sort(=.*)?|--get.*|--show-.*)$')
# `git -c key=value` can point git at an arbitrary program (diff.external, core.pager, core.editor,
# alias.*, core.sshCommand, credential.helper, core.hooksPath …). Only cosmetic keys pass.
GIT_SAFE_CONFIG = re.compile(r'^(color\.[A-Za-z.]+=|core\.quotepath=|diff\.noprefix=|log\.showsignature=|core\.pager=cat$|pager\.[A-Za-z.]+=(false|cat)$)', re.I)
# options that make a read-only subcommand write a file or run a program
GIT_DANGEROUS_OPTS = re.compile(r'^(--output(=.*)?|--output-directory(=.*)?|-O.*|--open-files-in-pager(=.*)?|--ext-diff|--exec(=.*)?)$')
SED_SAFE_FLAGS = {'-n', '-E', '-r', '-s', '-u', '-z', '--posix', '--debug', '--quiet', '--silent', '--regexp-extended', '-l'}
SHELL_KEYWORDS = {'for', 'while', 'until', 'if', 'elif', 'then', 'else', 'do', 'done', 'fi', 'case', 'esac', 'select', 'in', '{', '}', '!'}
SCRIPT_READ_NAMES = re.compile(r'^(test|tests|lint|typecheck|type-check|check|tsc|types|coverage|spec)(:|$)')
TEST_WRITE_FLAGS = {'-u', '--updateSnapshot', '--update', '--fix', '--write', '-w'}
SCRIPT_WRITE_NAMES = re.compile(r'fix|format|fmt|write|build|install|publish|release|deploy|prepare')
FIND_WRITE_FLAGS = ('-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint', '-fprintf', '-fls')


# ---------------------------------------------------------------- lexing

def read_subst(text, i):
    """text[i] == '$' and text[i+1] == '(' — return (inner, index-after-closing-paren)."""
    depth = 0
    j = i + 1
    q = None
    while j < len(text):
        c = text[j]
        if q:
            if c == '\\' and q == '"':
                j += 2
                continue
            if c == q:
                q = None
            j += 1
            continue
        if c in ('"', "'"):
            q = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[i + 2:j], j + 1
        j += 1
    raise Blocked('unterminated command substitution')


def strip_substitutions(text, depth):
    """Validate every $( … ) recursively and replace it with an inert token."""
    if depth > 8:
        raise Blocked('command substitution nested too deeply')
    out = []
    i = 0
    q = None
    while i < len(text):
        c = text[i]
        if c == '\\' and q != "'" and i + 1 < len(text):
            out.append(text[i:i + 2])
            i += 2
            continue
        if q == "'":
            if c == "'":
                q = None
            out.append(c)
            i += 1
            continue
        if c == "'" and q is None:
            q = "'"
            out.append(c)
            i += 1
            continue
        if c == '"':
            q = None if q == '"' else '"'
            out.append(c)
            i += 1
            continue
        if c == '$' and i + 1 < len(text) and text[i + 1] == '(':
            if i + 2 < len(text) and text[i + 2] == '(':        # $(( arithmetic )) — no command runs
                end = text.find('))', i)
                if end < 0:
                    raise Blocked('unterminated arithmetic expansion')
                out.append('0')
                i = end + 2
                continue
            inner, j = read_subst(text, i)
            validate(inner, depth + 1)
            out.append('SUBST')
            i = j
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def split_segments(text):
    """Split on top-level ; && || | & and newlines, honouring quotes."""
    segs, cur = [], []
    i = 0
    q = None
    while i < len(text):
        c = text[i]
        if c == '\\' and q != "'" and i + 1 < len(text):
            cur.append(text[i:i + 2])
            i += 2
            continue
        if q:
            if c == q:
                q = None
            cur.append(c)
            i += 1
            continue
        if c in ('"', "'"):
            q = c
            cur.append(c)
            i += 1
            continue
        if c == '|' and i + 1 < len(text) and text[i + 1] == '&':
            raise Blocked('`|&` pipes stderr into the next command')
        if c == '&' and i + 1 < len(text) and text[i + 1] == '>':   # &>file — a redirection, not a split
            cur.append('&>')
            i += 2
            continue
        if c == '>':                                                # keep `>&1` whole: the `&` is not a split
            cur.append(c)
            i += 1
            if i < len(text) and text[i] == '&':
                cur.append('&')
                i += 1
            continue
        if c in ';\n&|':
            two = text[i:i + 2]
            segs.append(''.join(cur))
            cur = []
            i += 2 if two in ('&&', '||') else 1
            continue
        cur.append(c)
        i += 1
    if q:
        raise Blocked('unbalanced quote')
    segs.append(''.join(cur))
    return [s for s in segs if s.strip()]


def mask_quotes(seg):
    """Replace the CONTENTS of quoted runs with 'x' so operator scans ignore them."""
    out = []
    q = None
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == '\\' and q != "'" and i + 1 < len(seg):
            out.append('xx')
            i += 2
            continue
        if q:
            out.append('x' if c != q else c)
            if c == q:
                q = None
            i += 1
            continue
        if c in ('"', "'"):
            q = c
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def check_redirections(seg):
    masked = mask_quotes(seg)
    if '<(' in masked or '>(' in masked:
        raise Blocked('process substitution')
    stripped = re.sub(r'\d?>\s*/dev/null', '', masked)      # >/dev/null, 2>/dev/null
    stripped = re.sub(r'&?\d?>&\s*\d', '', stripped)        # 2>&1, >&2, 1>&2
    if '>' in stripped:
        raise Blocked('output redirection writes a file')


# ---------------------------------------------------------------- per-command rules

def check_git(args):
    i = 0
    while i < len(args):
        a = args[i]
        if a == '-C':
            i += 2
            continue
        if a == '-c' or (a.startswith('-c') and len(a) > 2 and '=' in a):
            val = a[2:] if len(a) > 2 else (args[i + 1] if i + 1 < len(args) else '')
            if not GIT_SAFE_CONFIG.match(val):
                raise Blocked(f'git -c {val.split("=")[0]!r} can change git behaviour or run a program')
            i += 1 if len(a) > 2 else 2
            continue
        if a.startswith('--git-dir') or a.startswith('--work-tree'):
            i += 1 if '=' in a else 2
            continue
        if a == '--no-pager':
            i += 1
            continue
        if a.startswith('-'):
            raise Blocked(f'git option {a} before the subcommand')
        break
    if i >= len(args):
        return                                              # bare `git`: prints usage
    sub, rest = args[i], args[i + 1:]
    for a in rest:
        if GIT_DANGEROUS_OPTS.match(a):
            raise Blocked(f'git {sub} {a} writes a file or runs a program')
    if sub == 'remote':
        if not rest or (len(rest) == 1 and rest[0] in ('-v', '--verbose')) or rest[0] in ('show', 'get-url'):
            return
        raise Blocked(f'git remote {rest[0]} is not read-only')
    if sub in ('stash', 'worktree'):
        if rest and rest[0] == 'list':
            return
        raise Blocked(f'git {sub} {rest[0] if rest else ""}'.strip() + ' is not read-only')
    if sub not in GIT_READONLY:
        raise Blocked(f'git {sub} is not a read-only subcommand')
    if sub in GIT_LIST_ONLY:
        flags = [a for a in rest if a.startswith('-')]
        if not rest:
            return
        if not flags or not all(GIT_LIST_FLAGS.match(f) for f in flags):
            raise Blocked(f'git {sub} only in its --list/--get/--show form')


SED_ADDR = r'(?:\d+|\$|/(?:[^/\\]|\\.)*/|\\.(?:[^\\]|\\.)*?.)'
SED_CMD = re.compile(
    r'^\s*(?:' + SED_ADDR + r'(?:\s*,\s*(?:' + SED_ADDR + r'|\+\d+|~\d+))?)?\s*!?\s*'
    r'(?:[pdlqQnNhHgGxDPz=]|[{}]|[btT]\s*[A-Za-z_0-9]*|:[A-Za-z_0-9]+'
    r'|[aic]\\?.*|[rR]\s*\S+'
    r'|s(.)(?:(?!\1)[^\\]|\\.)*\1(?:(?!\1)[^\\]|\\.)*\1[gIimp0-9]*'
    r'|y(.)(?:(?!\2)[^\\]|\\.)*\2(?:(?!\2)[^\\]|\\.)*\2)?\s*$')


def check_sed_script(script):
    # split on ; and newlines outside of s/// bodies is hard in general; split conservatively on
    # newlines and on `;` not preceded by a backslash, then validate every command against the
    # read-only grammar above (p d l q n N h H g G x D P z = { } b t T : a i c r R s y). w/W/e are
    # absent by construction, and anything unrecognised is refused.
    for part in re.split(r'(?<!\\)[;\n]', script):
        if part.strip() == '':
            continue
        if not SED_CMD.match(part):
            raise Blocked(f'sed command {part.strip()[:40]!r} is not in the read-only grammar')


def check_sed(args):
    scripts, i, seen_script = [], 0, False
    while i < len(args):
        a = args[i]
        if a.startswith('-i') or a.startswith('--in-place'):
            raise Blocked('sed -i / --in-place edits in place')
        if a in ('-f', '--file') or a.startswith('--file='):
            raise Blocked('sed -f runs a script file')
        if a in ('-e', '--expression'):
            if i + 1 >= len(args):
                raise Blocked('sed -e without a script')
            scripts.append(args[i + 1]); seen_script = True; i += 2; continue
        if a.startswith('--expression='):
            scripts.append(a.split('=', 1)[1]); seen_script = True; i += 1; continue
        if a.startswith('-') and a != '-':
            if a in SED_SAFE_FLAGS or re.match(r'^-[nErsuz]+$', a):
                i += 1; continue
            raise Blocked(f'sed flag {a} is not allowed')
        if not seen_script:
            scripts.append(a); seen_script = True
        i += 1
    for sc in scripts:
        check_sed_script(sc)


def check_awk(args):
    for a in args:
        if '>' in a:
            raise Blocked('awk program contains a redirection')


def check_find(args):
    for a in args:
        if a in FIND_WRITE_FLAGS or a.startswith('-fprint'):
            raise Blocked(f'find {a} runs or writes')


def check_test_runner(cmd, args):
    for a in args:
        if a in TEST_WRITE_FLAGS:
            raise Blocked(f'{cmd} {a} rewrites files')
    def script(name):
        if SCRIPT_WRITE_NAMES.search(name):
            raise Blocked(f'package script {name!r} writes')
    if cmd == 'npx':
        if not args:
            raise Blocked('npx with no tool')
        if args[0] == 'jest':
            return
        if args[0] == 'vitest':
            if len(args) > 1 and args[1] == 'run':
                return
            raise Blocked('npx vitest only as `vitest run`')
        if args[0] == 'tsc':
            if '--noEmit' in args:
                return
            raise Blocked('npx tsc only with --noEmit (it writes .js otherwise)')
        if args[0] in ('eslint', 'mocha'):
            return                                              # --fix is caught by TEST_WRITE_FLAGS
        if args[0] == 'prettier':
            if '--check' in args or '-c' in args:
                return
            raise Blocked('npx prettier only with --check')
        raise Blocked(f'npx {args[0]} is not a test runner')
    if cmd in ('yarn', 'npm', 'pnpm'):
        if not args:
            raise Blocked(f'{cmd} with no script')
        if args[0] == 'run':
            if len(args) < 2:
                raise Blocked(f'{cmd} run with no script')
            name = args[1]
        else:
            name = args[0]
        if not SCRIPT_READ_NAMES.match(name):
            raise Blocked(f'{cmd} {name} is not a test/lint/typecheck script')
        script(name)
        return
    if cmd == 'cargo':
        if not args or args[0] not in ('test', 'clippy'):
            raise Blocked(f'cargo {args[0] if args else ""} is not test or clippy')
        return
    if cmd == 'go':
        if not args or args[0] != 'test':
            raise Blocked(f'go {args[0] if args else ""} is not go test')
        return
    if cmd == 'pytest':
        return
    raise Blocked(f'{cmd} is not allowed')


# ---------------------------------------------------------------- driver

def check_segment(seg):
    check_redirections(seg)
    try:
        words = shlex.split(seg, comments=False, posix=True)
    except ValueError as e:
        raise Blocked(f'cannot parse command ({e})')
    words = [w for w in words if not re.match(r'^&?\d?>', w) and not re.match(r'^\d?<', w)]
    while words:
        w = words[0]
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=', w)
        if m:
            if m.group(1) not in ALLOWED_ASSIGNMENTS:
                raise Blocked(f'environment assignment {m.group(1)}=… before a command')
            words = words[1:]
            continue
        if w in ('time', 'nice', 'command', 'env'):
            words = words[1:]
            continue
        break
    if not words:
        return
    # shell control flow is not a command: `for f in …` / `case x in` carry data (substitutions were
    # validated already); `if`/`while`/`until`/`elif` wrap a command that must itself pass; `then`,
    # `else`, `do` may prefix one; `done`/`fi`/`esac`/braces stand alone.
    while words and words[0] in SHELL_KEYWORDS:
        kw = words[0]
        if kw in ('for', 'case', 'select', 'in'):
            return
        if kw in ('done', 'fi', 'esac', '}'):
            return                                              # only redirections/filenames can follow (`done < list`)
        words = words[1:]
    if not words:
        return
    cmd = os.path.basename(words[0]) if '/' in words[0] else words[0]
    args = words[1:]
    if cmd in HARD_DENY:
        raise Blocked(f'{cmd} can run arbitrary code')
    if cmd in TEST_RUNNERS:
        check_test_runner(cmd, args)
        return
    if cmd not in READ_CMDS:
        raise Blocked(f'{cmd} is not on the read-only allowlist')
    if cmd == 'git':
        check_git(args)
    elif cmd == 'sed':
        check_sed(args)
    elif cmd == 'awk':
        check_awk(args)
    elif cmd == 'find':
        check_find(args)


def validate(text, depth=0):
    if '`' in text:
        raise Blocked('backtick command substitution')
    for seg in split_segments(strip_substitutions(text, depth)):
        check_segment(seg)


def main():
    try:
        cmd = json.load(sys.stdin).get('tool_input', {}).get('command', '') or ''
    except Exception:
        sys.exit(0)  # not a Bash payload we understand: do not block
    if not cmd.strip():
        sys.exit(0)
    try:
        validate(cmd)
    except Blocked as why:
        print(f"rev-reviewer is read-only: blocked ({why}): {cmd[:200]}", file=sys.stderr)
        sys.exit(2)
    except Exception as why:  # noqa: BLE001 — anything unexpected fails CLOSED
        print(f"rev-reviewer is read-only: cannot verify command ({why}): {cmd[:200]}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
