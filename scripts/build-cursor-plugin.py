#!/usr/bin/env python3
"""Build a self-contained native Cursor bundle from the shared Council runtime."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    '_council_bundle_helpers', Path(__file__).with_name('build-codex-plugin.py'))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
_atomic_exchange = _helpers._atomic_exchange
_make_staging_writable = _helpers._make_staging_writable
PACKAGE_TREES = ('.cursor-plugin', 'agents', 'cursor-skills', 'docs', 'scripts', 'schema', 'tests')
REQUIRED_FILES = (
    '.cursor-plugin/plugin.json', 'cursor-skills/rev/SKILL.md',
    'cursor-skills/stack/SKILL.md', 'docs/cursor-review-workflow.md',
    'docs/cursor-stack-workflow.md', 'docs/config.md', 'docs/cursor.md',
    'docs/seats.md', 'docs/cost-accounting.md',
    'scripts/roster.sh', 'scripts/stack.sh', 'scripts/rev-seat.sh',
    'scripts/lib/review-read-audit.py', 'scripts/lib/cursor-sdk-driver.mjs',
    'scripts/lib/cursor-sdk-reader.mjs', 'scripts/lib/cursor-read-helper.py',
    'schema/findings.schema.json', 'tests/run-tests.sh', 'LICENSE',
)
IGNORED = ('__pycache__', '*.pyc', 'node_modules', '.archives', '.qualification-key')


def _regular_tree(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError('package input must be a regular directory: ' + str(root))
    for current, directories, files in os.walk(root, followlinks=False):
        ignored = shutil.ignore_patterns(*IGNORED)(current, directories + files)
        directories[:] = [name for name in directories if name not in ignored]
        for name in directories + [name for name in files if name not in ignored]:
            path = Path(current) / name
            metadata = path.lstat()
            if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                raise ValueError('package input must be a regular file or directory: ' + str(path))


def _replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('canonical workflow changed; update the Cursor host binding')
    return text.replace(before, after, 1)


def cursor_workflow(kind):
    text = (REPO / 'plugins/review-council/codex-skills' / kind / 'SKILL.md').read_text()
    header = text.split('---', 2)
    if len(header) != 3:
        raise ValueError('canonical workflow has no skill front matter')
    text = header[2].lstrip()
    text = text.replace('REVIEW_COUNCIL_HOST=codex', 'REVIEW_COUNCIL_HOST=cursor')
    text = text.replace('../../../../docs/cost-accounting.md', 'cost-accounting.md')
    if kind == 'rev':
        replacements = (
            ('# Review Council for Codex', '# Review Council for Cursor'),
            ('Resolve `PLUGIN` to the directory two levels above **this loaded SKILL.md**. Never\n'
             'assume the shell cwd is the plugin or use `CLAUDE_PLUGIN_ROOT`. All script paths below\n'
             'are relative to that absolute `PLUGIN`; quote paths and use arrays for arguments.',
             'Keep `PLUGIN` bound to the native Cursor skill entry\'s plugin directory. All\n'
             'script paths below are relative to that absolute `PLUGIN`; quote paths and use\n'
             'arrays for arguments. Do not derive it from this workflow document or the cwd.'),
            ('All seats in the\n  Codex roster are actual external CLI processes, including Anthropic Claude seats.',
             'All seats in the\n  Cursor roster use explicit external transports, including the Claude CLI and an\n'
             'optional, qualified `cursor-sdk` Grok seat. Never use native Claude Agent seats.'),
            ('Rows on adapters `codex`, `gemini`, and `claude` launch through `rev-seat.sh`',
             'Rows on adapters `codex`, `gemini`, `claude`, and `cursor-sdk` launch through `rev-seat.sh`'),
            ('a Codex host always seats them on `claude`.',
             'a Codex or Cursor host always seats them on `claude`.'),
            ('Use the actual tools available in this Codex\nsession;',
             'Use the actual tools available in this Cursor\nsession;'),
        )
        for before, after in replacements:
            text = _replace_once(text, before, after)
    elif kind == 'stack':
        replacements = (
            ('# Review Council stack for Codex', '# Review Council stack for Cursor'),
            ('Resolve `PLUGIN` two directories above this loaded skill. Read the sibling\n'
             '`rev/SKILL.md` for the review contract. The shared runner launches headless Codex\n'
             'legs, waits for receipts, tracks activity and process-tree CPU before declaring a\n'
             'stall, and resumes from the same session root and ledger.',
             'Keep `PLUGIN` bound to the native Cursor skill entry\'s plugin directory. Read\n'
             '`$PLUGIN/cursor-skills/rev/SKILL.md` for the review contract. The shared runner\n'
             'launches headless Cursor legs, waits for receipts, tracks activity and process-tree\n'
             'CPU before declaring a stall, and resumes from the same session root and ledger.'),
            ('under the Codex host', 'under the Cursor host'),
            ('Codex legs use `workspace-write`, network access for reviewer provider calls, and\n'
             'write access to the session root. They inherit the configured Codex model as orchestrator; it writes and implements a local cluster (one file, at most 3 sites), and the resolved workhorse writes the plan and implements every other cluster. They do\n'
             'not bypass the sandbox. If a gate or nested CLI needs unavailable permissions,\n'
             'report the concrete failure; do not change to unrestricted execution implicitly.',
             'Cursor legs use the installed `cursor-agent` or `agent` CLI. The configured host\n'
             'model writes and implements a local cluster (one file, at most 3 sites); the resolved\n'
             'workhorse writes the plan and implements every other cluster. Reviewer seats keep\n'
             'their own enforced transport boundaries. If a gate or nested transport needs\n'
             'unavailable permissions, report the concrete failure. Never change host permissions\n'
             'or use another host implicitly.'),
        )
        for before, after in replacements:
            text = _replace_once(text, before, after)
    else:
        raise ValueError('unknown Cursor workflow')
    return text


def validate_bundle(root):
    _regular_tree(root)
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            raise ValueError('Cursor package is missing ' + relative)
    metadata = json.loads((root / '.cursor-plugin/plugin.json').read_text())
    if (metadata.get('name') != 'review-council'
            or not isinstance(metadata.get('version'), str)
            or re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', metadata['version']) is None
            or metadata.get('skills') != './cursor-skills/' or metadata.get('agents') != []
            or any(key in metadata for key in ('hooks', 'mcpServers', 'commands', 'rules'))):
        raise ValueError('invalid native Cursor manifest')
    for relative in ('.claude-plugin', '.codex-plugin', 'hooks', 'skills', 'codex-skills'):
        if (root / relative).exists():
            raise ValueError('Cursor package contains another host discovery path: ' + relative)
    shared = REPO / 'plugins/review-council'
    for name in PACKAGE_TREES:
        for path in (root / name).rglob('*'):
            source = shared / path.relative_to(root)
            if path.is_file() and source.is_file():
                if path.stat().st_mode & 0o111 != source.stat().st_mode & 0o111:
                    raise ValueError('Cursor package changed executable mode: ' + str(path))
    for kind in ('rev', 'stack'):
        skill = (root / 'cursor-skills' / kind / 'SKILL.md').read_text()
        if re.search(r'^name:\s*' + kind + r'\s*$', skill, re.M) is None:
            raise ValueError('invalid Cursor skill identity')
        if 'REVIEW_COUNCIL_HOST=cursor' not in skill:
            raise ValueError('Cursor skill is missing its explicit host')
    for name in ('roster.sh', 'stack.sh'):
        if not (root / 'scripts' / name).read_text().startswith(
                '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=cursor\n'):
            raise ValueError('Cursor runner is missing its explicit host')


def build(output):
    output = output.expanduser().absolute()
    if output.name != 'review-council':
        raise ValueError('output directory must be named review-council')
    if output.is_symlink():
        raise ValueError('refusing to replace a symlink')
    destination = output.resolve()
    inputs = (REPO / 'plugins/review-council', REPO / 'docs', REPO / 'scripts', REPO / 'LICENSE')
    for source in inputs:
        source = source.resolve()
        if (destination == source or source in destination.parents
                or destination in source.parents):
            raise ValueError('output overlaps package source')
    if output.exists():
        manifest = output / '.cursor-plugin/plugin.json'
        if (manifest.is_symlink() or not manifest.is_file()
                or json.loads(manifest.read_text()).get('name') != output.name):
            raise ValueError('existing output is not a review-council Cursor bundle')
        if any((output / name).exists() or (output / name).is_symlink()
               for name in ('.claude-plugin', '.codex-plugin', 'hooks', 'skills', 'codex-skills')):
            raise ValueError('existing output contains another host discovery path')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.review-council-build-', dir=output.parent) as temp:
        stage = Path(temp) / 'review-council'
        stage.mkdir()
        shared = REPO / 'plugins/review-council'
        for name in PACKAGE_TREES:
            _regular_tree(shared / name)
            shutil.copytree(shared / name, stage / name,
                            ignore=shutil.ignore_patterns(*IGNORED))
        _make_staging_writable(stage)
        for name in ('config.md', 'cursor.md', 'seats.md', 'cost-accounting.md'):
            shutil.copy2(REPO / 'docs' / name, stage / 'docs' / name)
        shutil.copy2(REPO / 'LICENSE', stage / 'LICENSE')
        _make_staging_writable(stage)
        for kind, name in (('rev', 'cursor-review-workflow.md'), ('stack', 'cursor-stack-workflow.md')):
            (stage / 'docs' / name).write_text(cursor_workflow(kind))
        for name in ('roster.sh', 'stack.sh'):
            path = stage / 'scripts' / name
            content = _replace_once(path.read_text(), '#!/bin/bash\n',
                                    '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=cursor\n')
            path.write_text(content)
        validate_bundle(stage)
        if output.exists():
            _atomic_exchange(stage, output)
        else:
            stage.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'dist/cursor/review-council',
                        help='generated directory to replace (must end in review-council)')
    args = parser.parse_args()
    try:
        print(build(args.output))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'build-cursor: {exc}\n')
