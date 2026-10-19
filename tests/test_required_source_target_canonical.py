"""Mandatory source targets retain their canonical semantic interval."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_deleted_source_proof import SourceFixture, load_evidence


class RequiredSourceTargetCanonicalTests(unittest.TestCase):
    def test_self_consistent_shortened_target_cannot_replace_canonical_range(self):
        with tempfile.TemporaryDirectory(prefix='canonical-source-target-') as directory:
            fixture = SourceFixture(Path(directory), 'current')
            evidence = load_evidence()
            repository = evidence.Repository(fixture.session)
            index = json.loads((fixture.session / 'r1-evidence.json').read_text())
            evidence.validate_source_context(fixture.session, fixture.manifest, index)
            evidence.validate_source_context_snapshot(repository, fixture.session, fixture.manifest)
            target = fixture.target()
            self.assertEqual(target['blob_tree'], fixture.manifest['snapshot_tree'])
            self.assertGreater(target['line_end'], target['line_start'])
            self.assertTrue(fixture.context['source_read_required'])

            forged = copy.deepcopy(fixture.manifest)
            rows = forged['source_context']['seats'][fixture.seat]['omitted_source_ranges']
            matches = [row for row in rows if all(row[key] == value
                                                for key, value in target.items())]
            self.assertEqual(len(matches), 1, 'the rendered target must name one omitted identity')
            shortened = matches[0]
            original = dict(shortened)
            entry = repository.entries(target['blob_tree'])[target['path']]
            self.assertEqual(entry, (shortened['blob_mode'], target['blob_oid']))
            lines = evidence.split_lf_lines(repository.blob(entry))
            full = b''.join(lines[target['line_start'] - 1:target['line_end']])
            self.assertEqual(hashlib.sha256(full).hexdigest(), target['content_sha256'])
            shortened['line_end'] = shortened['line_start']
            shortened['content_sha256'] = hashlib.sha256(
                lines[shortened['line_start'] - 1]).hexdigest()
            self.assertEqual({key for key in original if original[key] != shortened[key]},
                             {'line_end', 'content_sha256'})
            forged_index = copy.deepcopy(index)
            forged_index['source_context'] = copy.deepcopy(forged['source_context'])
            evidence.validate_source_context(fixture.session, forged, forged_index)
            with self.assertRaises(
                    ValueError, msg='shortened target must not replace canonical semantic range'):
                evidence.validate_source_context_snapshot(repository, fixture.session, forged)


if __name__ == '__main__':
    unittest.main()
