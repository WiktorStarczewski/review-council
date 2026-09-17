#!/bin/bash
# Panel prompt rendering: manifest cost, sibling-site verification text, and render timing.

test_panel_source_snapshot_lists_each_tree_once() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import hashlib, importlib.util, sys, tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('panel_snapshot_cost', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raw = b''.join(b'line %d\n' % index for index in range(1, 41))
lines = raw.splitlines(True)
oid = hashlib.sha1(b'blob %d\0' % len(raw) + raw).hexdigest()

class Repo:
    listings = 0
    def entries(self, tree):
        Repo.listings += 1
        return {'main.py': ('100644', oid)}
    def blob(self, entry):
        return raw

rows = [{'path': 'main.py', 'blob_tree': '1' * 40, 'blob_mode': '100644', 'blob_oid': oid,
         'line_start': start, 'line_end': start + 1,
         'content_sha256': hashlib.sha256(b''.join(lines[start - 1:start + 1])).hexdigest()}
        for start in range(1, 40, 2)]
manifest = {'source_context': {'snapshot_tree': '1' * 40, 'base_tree': '2' * 40, 'seats': {
    'sol': {'shards': [], 'omitted_source_ranges': rows, 'required_source_ranges': []}}}}
with tempfile.TemporaryDirectory() as session:
    module.validate_source_context_snapshot(Repo(), Path(session), manifest)
assert Repo.listings == 1, Repo.listings
PY
  assert_eq "source snapshot validation lists each tree once, not once per range" "$?" 0
}
