#!/usr/bin/env python3
"""Turn Claude Code's per-marketplace auto-update on or off.

    set-auto-update.py <settings.json> <marketplace-name> <true|false>

Auto-update defaults to OFF for third-party marketplaces, so a plugin installed from one never
moves until the user runs `claude plugin update`. This flips the one flag that changes that --
`extraKnownMarketplaces.<name>.autoUpdate` in the user's settings.json -- and nothing else: the
file is rewritten atomically at 2-space indent with every other key preserved, its mode is kept
(a 600 settings.json stays 600), symlinks are followed rather than replaced, and a file that is
unreadable or shaped wrong is left alone rather than overwritten. Standard library only.

install.sh carries a byte-identical copy of the marked block below, because it runs from curl
before this file exists on disk; tests/t-install.sh diffs the two so they cannot drift.
"""

import json
import os
import sys


# --- begin json-edit (byte-identical in install.sh and scripts/lib/set-auto-update.py; t-install.sh diffs them)
# What `claude plugin marketplace add` writes for a marketplace we know. An entry we create
# ourselves needs it: a name carrying a flag and no repo behind it is not a usable marketplace.
KNOWN_SOURCES = {
    'review-council': {'source': 'github', 'repo': 'WiktorStarczewski/review-council'},
}


def set_auto_update(path, name, enabled):
    """Set extraKnownMarketplaces[<name>].autoUpdate in <path>; every other key is preserved.

    A missing or empty settings file is filled in; anything unreadable or shaped wrong is reported
    and left exactly as it was. Deliberately does NOT touch the entry's `version`: a version pinned
    in the marketplace entry silently overrides the plugin manifest, which is where this plugin's
    single version lives. Returns a process exit status.
    """
    target = os.path.realpath(path)          # follow symlinks: dotfile managers link settings.json,
    try:                                     # and replacing the LINK would strand the real file
        with open(target, encoding='utf-8') as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ''
    except OSError as exc:
        sys.stderr.write('review-council: cannot read %s (%s) -- left unchanged\n' % (path, exc))
        return 1
    try:
        data = json.loads(text) if text.strip() else {}   # an empty file is absence, not corruption
    except ValueError as exc:
        sys.stderr.write('review-council: cannot read %s (%s) -- left unchanged\n' % (path, exc))
        return 1
    if not isinstance(data, dict):
        sys.stderr.write('review-council: %s is not a JSON object -- left unchanged\n' % path)
        return 1
    markets = data.get('extraKnownMarketplaces', {})
    if not isinstance(markets, dict):
        sys.stderr.write('review-council: extraKnownMarketplaces in %s is not an object -- left unchanged\n' % path)
        return 1
    entry = markets.get(name, {})
    if not isinstance(entry, dict):
        sys.stderr.write('review-council: the %s entry in %s is not an object -- left unchanged\n' % (name, path))
        return 1
    if not entry and name in KNOWN_SOURCES:
        entry['source'] = dict(KNOWN_SOURCES[name])   # a fresh entry gets its repo too
    entry['autoUpdate'] = enabled            # an existing entry keeps the source it already has
    markets[name] = entry
    data['extraKnownMarketplaces'] = markets
    tmp = target + '.new'
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        try:
            mode = os.stat(target).st_mode & 0o7777    # settings.json can hold secrets: a 600 file
        except OSError:                                # stays 600, and a file we create starts 600
            mode = 0o600
        os.chmod(tmp, mode)
        os.replace(tmp, target)              # atomic: an interrupted write never truncates settings.json
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        sys.stderr.write('review-council: cannot write %s (%s)\n' % (path, exc))
        return 1
    print('auto-update %s for %s in %s' % ('on' if enabled else 'off', name, path))
    return 0
# --- end json-edit ---


def main(argv):
    if len(argv) != 4 or argv[3] not in ('true', 'false'):
        sys.stderr.write('usage: set-auto-update.py <settings.json> <marketplace-name> <true|false>\n')
        return 2
    return set_auto_update(argv[1], argv[2], argv[3] == 'true')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
