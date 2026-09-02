#!/usr/bin/env python3
"""Convert `codex exec review` native prose output into findings.schema.json.

`codex exec review` ignores --output-schema: its final message is prose of the form

    <one-line verdict>

    Full review comments:

    - [P2] <imperative title> — /abs/or/rel/path.ts:4-6
      <body, indented, possibly several lines>

Usage: codex-review-to-findings.py <in.txt> <out.json> [--root <repo-root>]
Prints the number of findings. A clean review (no `- [Pn]` blocks) yields an empty findings array.
"""
import json
import re
import sys

args = sys.argv[1:]
root = ''
if '--root' in args:
    i = args.index('--root'); root = args[i + 1].rstrip('/'); del args[i:i + 2]
inp, out = args[0], args[1]
with open(inp, errors='replace') as f:
    lines = f.read().splitlines()

summary = next((l.strip() for l in lines if l.strip()), 'codex native review')
# The location is parsed from the RIGHT (`.+?` path, anchored `:line[-line]$`), never as `\S+`:
# a path containing a space ("/repo/my dir/x.ts:4-4") is common and silently produced a CLEAN review.
HEAD = re.compile(r'^\s*[-*]\s*\[(P[0-3])\]\s*(.*?)\s+[—–-]+\s+(.+?):(\d+)(?:-(\d+))?\s*$')
MARKER = re.compile(r'^\s*[-*]\s*\[P[0-3]\]')
findings, cur = [], None
for l in lines:
    m = HEAD.match(l)
    if m is None and MARKER.match(l):
        # a finding we can see but cannot place: fail loudly rather than convert the review to "clean"
        print(f"cannot parse finding: {l.strip()}", file=sys.stderr)
        sys.exit(1)
    if m:
        cur = {'severity': m.group(1), 'file': m.group(3), 'line_start': int(m.group(4)),
               'line_end': int(m.group(5) or m.group(4)), 'claim': m.group(2).strip(),
               'evidence': '', 'suggested_fix': m.group(2).strip(), 'confidence': 0.7}
        findings.append(cur)
        continue
    if cur is None or not l.strip():
        continue
    if not l.startswith((' ', '\t')):
        cur = None
        continue
    cur['evidence'] = (cur['evidence'] + ' ' + l.strip()).strip()
for fd in findings:
    if root and fd['file'].startswith(root + '/'):
        fd['file'] = fd['file'][len(root) + 1:]
    if not fd['evidence']:
        fd['evidence'] = fd['claim']
with open(out, 'w') as f:
    json.dump({'summary': summary, 'findings': findings}, f)
print(len(findings))
