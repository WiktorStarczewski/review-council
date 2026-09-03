#!/usr/bin/env python3
"""One line if a newer review-council release is published, nothing otherwise.

    update-check.py <plugin-root>

Opt-in: silent unless the config file says {"check_updates": true}. Called from the SessionStart
hook, so the contract is severe -- every failure path (no network, bad JSON, missing manifest,
unwritable cache) prints nothing and exits 0. A session must never break, or even pause, over an
update notice. The published version is fetched at most once a day and cached; the fetch itself is
capped at two seconds and the hook caps the whole call at three.

Nothing here ever updates the plugin: a plugin's own hook replacing the directory it is running
from is how you corrupt an install. The line only tells the user which command to run -- and when
auto-update is on for the marketplace (install.sh's default) there is normally nothing to tell.
"""

import json
import os
import sys
import time
import urllib.request

DEFAULT_URL = ('https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/'
               'plugins/review-council/.claude-plugin/plugin.json')
FETCH_TIMEOUT = 2          # seconds
CACHE_TTL = 24 * 60 * 60   # seconds; REVIEW_COUNCIL_UPDATE_TTL overrides

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from roster import load_config          # the one reader of the config file; same directory
except Exception:                           # pragma: no cover - a broken roster.py must not break session start
    def load_config():
        return {}, 'roster.py unavailable'


def version_tuple(text):
    """'0.1.11' -> (0, 1, 11); None if it is not a dotted-integer version."""
    if not isinstance(text, str):
        return None
    parts = text.strip().split('.')
    if not parts or any(not p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def manifest_version(path):
    """The `version` string of a plugin.json, or None if it cannot be read."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh).get('version')
    except Exception:
        return None


def read_cache(path, ttl):
    """The cached latest version if the cache is younger than ttl, else None."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        if 0 <= time.time() - float(data['checked_at']) < ttl:
            return data['latest']
    except Exception:
        return None
    return None


def write_cache(path, latest):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.new'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'checked_at': time.time(), 'latest': latest}, fh)
        os.replace(tmp, path)
    except Exception:
        pass                                # a cache we cannot write just means we check again next time


def fetch_latest(url):
    """The published `version`, or None on any network/parse trouble. file:// works, for tests."""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as resp:
            body = resp.read(65536).decode('utf-8', 'replace')
        return json.loads(body).get('version')
    except Exception:
        return None


def main(argv):
    root = argv[1] if len(argv) > 1 else os.environ.get('CLAUDE_PLUGIN_ROOT', '')
    cfg, _ = load_config()
    if cfg.get('check_updates') is not True:   # opt-in, and only to a literal JSON true
        return 0

    installed = version_tuple(manifest_version(os.path.join(root, '.claude-plugin', 'plugin.json')))
    if installed is None:
        return 0

    cache_dir = (os.environ.get('REVIEW_COUNCIL_CACHE_DIR')
                 or os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
                                 'review-council'))
    cache_path = os.path.join(cache_dir, 'update-check.json')
    try:
        ttl = float(os.environ.get('REVIEW_COUNCIL_UPDATE_TTL') or CACHE_TTL)
    except ValueError:
        ttl = CACHE_TTL

    latest = read_cache(cache_path, ttl)
    if latest is None:
        latest = fetch_latest(os.environ.get('REVIEW_COUNCIL_UPDATE_URL') or DEFAULT_URL)
        if latest is None:
            return 0                        # stale beats wrong: say nothing rather than guess
        write_cache(cache_path, latest)

    published = version_tuple(latest)
    if published is not None and published > installed:
        print('review-council %s available: claude plugin update review-council' % latest)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except Exception:                       # nothing in an update notice is worth a broken session
        sys.exit(0)
