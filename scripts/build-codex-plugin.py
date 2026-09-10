#!/usr/bin/env python3
"""Build a self-contained Codex bundle, without Claude skill/hook discovery."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

REPO = Path(__file__).resolve().parents[1]


def build(output):
    output = output.expanduser().absolute()
    if output.name != 'review-council':
        raise ValueError('output directory must be named review-council')
    if output.is_symlink():
        raise ValueError('refusing to replace a symlink')
    if output.exists():
        manifest = output / '.codex-plugin/plugin.json'
        if not manifest.is_file() or json.loads(manifest.read_text()).get('name') != output.name:
            raise ValueError('existing output is not a review-council Codex bundle')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.review-council-build-', dir=output.parent) as temp:
        stage = Path(temp) / 'review-council'
        stage.mkdir()
        shared = REPO / 'plugins/review-council'
        for name in ('.codex-plugin', 'codex-skills', 'scripts', 'schema'):
            shutil.copytree(shared / name, stage / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (stage / 'docs').mkdir()
        shutil.copy2(REPO / 'docs/config.md', stage / 'docs/config.md')
        shutil.copy2(REPO / 'LICENSE', stage / 'LICENSE')
        # Host selection also works for direct CLI use; no shell/session hook needed.
        for name in ('roster.sh', 'stack.sh'):
            path = stage / 'scripts' / name
            content = path.read_text()
            path.write_text(content.replace('#!/bin/bash\n',
                            '#!/bin/bash\nexport REVIEW_COUNCIL_HOST=codex\n', 1))
        old = Path(temp) / 'previous'
        if output.exists():
            output.rename(old)
        try:
            stage.rename(output)
        except OSError:
            if old.exists():
                old.rename(output)
            raise
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'dist/review-council',
                        help='generated directory to replace (must end in review-council)')
    args = parser.parse_args()
    try:
        print(build(args.output))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'build-codex: {exc}\n')
