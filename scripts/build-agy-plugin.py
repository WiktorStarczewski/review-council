#!/usr/bin/env python3
"""Build a self-contained native Antigravity (agy) bundle from the shared Council runtime."""
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

SHARED_TREES = ('docs', 'scripts', 'schema', 'tests')
FOREIGN_PATHS = ('.claude-plugin', '.codex-plugin', '.cursor-plugin', 'hooks',
                 'codex-skills', 'cursor-skills', 'pi-skills')
REQUIRED_FILES = (
    'plugin.json',
    'skills/rev/SKILL.md',
    'skills/rev/phases/10-setup.md',
    'skills/rev/phases/20-discovery.md',
    'skills/rev/phases/30-triage.md',
    'skills/rev/phases/70-publish.md',
    'skills/stack/SKILL.md',
    'docs/config.md',
    'docs/agy.md',
    'docs/seats.md',
    'docs/cost-accounting.md',
    'scripts/roster.sh',
    'scripts/stack.sh',
    'scripts/rev-seat.sh',
    'scripts/seats.d/agy.sh',
    'scripts/lib/review-read-audit.py',
    'schema/findings.schema.json',
    'tests/run-tests.sh',
    'LICENSE',
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
        raise ValueError('canonical workflow changed; update the Antigravity host binding')
    return text.replace(before, after, 1)


def agy_manifest():
    source = json.loads((REPO / 'plugins/review-council/.claude-plugin/plugin.json').read_text())
    return {
        'name': 'review-council',
        'version': source['version'],
        'description': (
            'Multi-model code review council for Antigravity: Gemini hydrogen/neon, '
            'OpenAI Codex, and Anthropic Claude seats reviewing the same change with '
            'verified findings, fix loops, and bounded-read receipts.'
        ),
        'author': source['author'],
        'homepage': source['homepage'],
        'repository': source['repository'],
        'license': source['license'],
        'keywords': [
            'review',
            'code-review',
            'multi-model',
            'antigravity',
            'gemini',
            'codex',
            'claude',
        ],
    }


def agy_skill_text(kind):
    text = (REPO / 'plugins/review-council/codex-skills' / kind / 'SKILL.md').read_text()
    text = text.replace('REVIEW_COUNCIL_HOST=codex', 'REVIEW_COUNCIL_HOST=agy')
    text = text.replace('${REVIEW_COUNCIL_HOST:-codex}', '${REVIEW_COUNCIL_HOST:-agy}')
    if kind == 'rev':
        replacements = (
            ('# Review Council for Codex', '# Review Council for Antigravity'),
            ('By default, retry on the next higher enforced seat: Luna, then Sonnet, then Sol, then Opus.',
             'By default on Antigravity, retry on the next higher enforced seat: '
             'Hydrogen, then Luna, then Sonnet, then Sol, then Neon, then Opus.'),
            ('The default writer is `grok-4.7-xhigh` through the Cursor agent CLI on every host, '
             'including Codex and Claude Code. A launched writer uses that slug. If it is missing, '
             'not signed in, or out of credits, the writer falls through OpenAI Luna, then '
             'Anthropic Sonnet, then OpenAI Sol, then Anthropic Opus. Review seats stay on the roster.',
             'On Antigravity (`REVIEW_COUNCIL_HOST=agy`), the writer and escalation chain starts '
             'at Google Gemini `hydrogen` (`agy` CLI), then OpenAI Luna, Anthropic Sonnet, OpenAI '
             'Sol, Google Gemini `neon` (`agy` CLI), and Anthropic Opus. Gemini `hydrogen` and '
             '`neon` seats are exclusive to the Antigravity host and never run from other '
             'harnesses. Review seats stay on the roster.'),
            ('Exit 4 means the Cursor writer is missing, not signed in, or out of credits: '
             'run advance immediately and do not retry that family.',
             'Exit 4 means the Antigravity (`agy`) writer is missing, not signed in, or out of '
             'credits: run advance immediately and do not retry that family.'),
            ('Adapters `codex` and `claude` launch through `rev-seat.sh`.',
             'Adapters `agy`, `codex` and `claude` launch through `rev-seat.sh`.'),
            ('Before a phase, Read exactly that phase file from the `phases` directory next to this skill and follow it.',
             'Before a phase, read the matching phase file from `$PLUGIN/skills/rev/phases/` and follow it.'),
        )
        for before, after in replacements:
            text = _replace_once(text, before, after)
    elif kind == 'stack':
        replacements = (
            ('# Review Council stack for Codex', '# Review Council stack for Antigravity'),
            ('The shared runner launches headless Codex\nlegs',
             'The shared runner launches headless Antigravity (`agy`)\nlegs'),
            ('under the Codex host', 'under the Antigravity host'),
            ('Codex legs use `workspace-write`, network access for reviewer provider calls, and\n'
             'write access to the session root. They inherit the configured Codex model as orchestrator; '
             'the resolved workhorse writes the fix plan, the host implements a local cluster '
             '(one file, at most 3 sites), and the workhorse implements every other cluster. They do\n'
             'not bypass the sandbox. If a gate or nested CLI needs unavailable permissions,\n'
             'report the concrete failure; do not change to unrestricted execution implicitly.',
             'Antigravity legs invoke the `agy` CLI with `--dangerously-skip-permissions`,\n'
             'inherited session-root and worktree access, and the current Antigravity Gemini model as\n'
             'orchestrator. The resolved workhorse writes the fix plan, the host implements a local\n'
             'cluster (one file, at most 3 sites), and the workhorse implements every other cluster.\n'
             'Reviewer seats keep their own enforced read-only transport boundaries. If a gate or\n'
             'nested CLI needs unavailable permissions, report the concrete failure.'),
        )
        for before, after in replacements:
            text = _replace_once(text, before, after)
    else:
        raise ValueError('unknown Antigravity skill: ' + kind)
    return text


def agy_phase_text(text):
    text = text.replace('REVIEW_COUNCIL_HOST=codex', 'REVIEW_COUNCIL_HOST=agy')
    text = text.replace('../../../../docs/cost-accounting.md', '../../../docs/cost-accounting.md')
    replacements = (
        ('All seats in the\n  Codex roster are actual external CLI processes, including Anthropic Claude seats.',
         'All seats in the\n  Antigravity roster are actual external CLI processes, including Gemini (`agy`) and Anthropic Claude seats.'),
        ('run `python3 "$PLUGIN/scripts/rev-panel-request.py"',
         'run `REVIEW_COUNCIL_HOST=agy python3 "$PLUGIN/scripts/rev-panel-request.py"'),
        ('The default mode is normal: four Luna seats, or four Cursor Grok seats when this host is '
         'Cursor and the SDK can seat them. `high effort` selects high: two Sol seats and two '
         'Opus seats. An explicit `4*luna` or `4*grok` overrides that preset.',
         'The default mode is normal: four Gemini `hydrogen` seats through `agy` (falling back '
         'to four Luna seats if `hydrogen` is unavailable). `high effort` selects high: two Sol '
         'seats and two Opus seats. An explicit `4*hydrogen`, `4*neon`, or `4*luna` overrides '
         'that preset.'),
        ('`exclude`, `pin`, `codex_models`, `claude_seat`, `claude_seats`, `extras`,',
         '`exclude`, `pin`, `agy_models`, `agy_effort`, `codex_models`, `claude_seat`, `claude_seats`, `extras`,'),
        ('native full-file action: shell `cat` for Codex, `Read` for Claude, and `read_file` for\nGemini.',
         'native full-file action: shell `cat` for Codex and Antigravity (`agy`), `Read` for Claude, and `read_file` for\nGemini.'),
        ('Rows on adapters `codex`, `gemini`, and `claude` launch through `rev-seat.sh`',
         'Rows on adapters `agy`, `codex`, `gemini`, and `claude` launch through `rev-seat.sh`'),
        ('a Codex host always seats them on `claude`.',
         'a Codex or Antigravity host always seats them on `claude`.'),
        ('Use the actual tools available in this Codex\nsession;',
         'Use the actual tools available in this Antigravity\nsession;'),
    )
    for before, after in replacements:
        if before not in text:
            continue
        text = _replace_once(text, before, after)
    return text


def _inject_host_env(stage):
    for name in ('roster.sh', 'stack.sh'):
        path = stage / 'scripts' / name
        path.write_text(_replace_once(
            path.read_text(), '#!/bin/bash\n',
            '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=agy\n'))
    for name in ('rev-preflight.sh', 'rev-seat.sh'):
        path = stage / 'scripts' / name
        path.write_text(_replace_once(
            path.read_text(), '#!/bin/bash\n',
            '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=${REVIEW_COUNCIL_HOST:-agy}\n'))
    for name in ('rev-panel-request.py', 'rev-workhorse.py'):
        path = stage / 'scripts' / name
        text = path.read_text()
        if 'import os\n' in text:
            updated = text.replace(
                'import sys\n',
                "import sys\nos.environ.setdefault('REVIEW_COUNCIL_HOST', 'agy')\n", 1)
        else:
            updated = text.replace(
                'import sys\n',
                "import os\nimport sys\nos.environ.setdefault('REVIEW_COUNCIL_HOST', 'agy')\n", 1)
        if updated == text:
            raise ValueError('could not bind host env in ' + name)
        path.write_text(updated)


def validate_bundle(root):
    _regular_tree(root)
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            raise ValueError('Antigravity package is missing ' + relative)
    metadata = json.loads((root / 'plugin.json').read_text())
    if (metadata.get('name') != 'review-council'
            or not isinstance(metadata.get('version'), str)
            or re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', metadata['version']) is None):
        raise ValueError('invalid Antigravity plugin.json manifest')
    for relative in FOREIGN_PATHS:
        if (root / relative).exists():
            raise ValueError('Antigravity package contains another host discovery path: ' + relative)
    shared = REPO / 'plugins/review-council'
    for name in SHARED_TREES:
        for path in (root / name).rglob('*'):
            source = shared / path.relative_to(root)
            if path.is_file() and source.is_file():
                if path.stat().st_mode & 0o111 != source.stat().st_mode & 0o111:
                    raise ValueError('Antigravity package changed executable mode: ' + str(path))
    for kind in ('rev', 'stack'):
        skill = (root / 'skills' / kind / 'SKILL.md').read_text()
        if re.search(r'^name:\s*' + kind + r'\s*$', skill, re.M) is None:
            raise ValueError('invalid Antigravity skill identity: ' + kind)
        if 'REVIEW_COUNCIL_HOST=agy' not in skill:
            raise ValueError('Antigravity skill is missing its explicit host: ' + kind)
        if 'REVIEW_COUNCIL_HOST=codex' in skill:
            raise ValueError('Antigravity skill kept Codex host binding: ' + kind)
    for path in (root / 'skills/rev/phases').glob('*.md'):
        if 'REVIEW_COUNCIL_HOST=codex' in path.read_text():
            raise ValueError('Antigravity phase file kept Codex host binding: ' + path.name)
    for name in ('roster.sh', 'stack.sh'):
        if not (root / 'scripts' / name).read_text().startswith(
                '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=agy\n'):
            raise ValueError('Antigravity runner is missing its explicit host: ' + name)


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
        manifest = output / 'plugin.json'
        existing = (json.loads(manifest.read_text())
                    if (not manifest.is_symlink() and manifest.is_file()) else None)
        if not isinstance(existing, dict) or existing.get('name') != output.name:
            raise ValueError('existing output is not a review-council Antigravity bundle')
        if any((output / name).exists() or (output / name).is_symlink() for name in FOREIGN_PATHS):
            raise ValueError('existing output contains another host discovery path')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.review-council-build-', dir=output.parent) as temp:
        stage = Path(temp) / 'review-council'
        stage.mkdir()
        shared = REPO / 'plugins/review-council'
        for name in SHARED_TREES:
            _regular_tree(shared / name)
            shutil.copytree(shared / name, stage / name,
                            ignore=shutil.ignore_patterns(*IGNORED))
        _make_staging_writable(stage)
        for name in ('config.md', 'agy.md', 'seats.md', 'cost-accounting.md'):
            shutil.copy2(REPO / 'docs' / name, stage / 'docs' / name)
        shutil.copy2(REPO / 'LICENSE', stage / 'LICENSE')
        (stage / 'plugin.json').write_text(json.dumps(agy_manifest(), indent=2) + '\n')
        for kind in ('rev', 'stack'):
            skill_dir = stage / 'skills' / kind
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / 'SKILL.md').write_text(agy_skill_text(kind))
        phases_src = shared / 'codex-skills' / 'rev' / 'phases'
        phases_dst = stage / 'skills' / 'rev' / 'phases'
        shutil.copytree(phases_src, phases_dst)
        _make_staging_writable(phases_dst)
        for path in phases_dst.glob('*.md'):
            path.write_text(agy_phase_text(path.read_text()))
        _make_staging_writable(stage)
        _inject_host_env(stage)
        validate_bundle(stage)
        if output.exists():
            _atomic_exchange(stage, output)
        else:
            stage.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'dist/agy/review-council',
                        help='generated directory to replace (must end in review-council)')
    args = parser.parse_args()
    try:
        print(build(args.output))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'build-agy: {exc}\n')
