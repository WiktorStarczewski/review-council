"""Validate complete output manifests before replacing project heads."""
from .errors import InvalidGraph, MissingArtifact


class Publisher:
    def __init__(self, catalog, blobs):
        self.catalog = catalog
        self.blobs = blobs

    def commit(self, project, outputs, epoch, revision, cache_updates):
        """Install one complete manifest if both project version fences still match."""
        record = self.catalog.check_version(project, epoch, revision)
        owned_outputs = dict(outputs)
        if not owned_outputs:
            raise InvalidGraph('publication requires at least one output')
        if not set(owned_outputs) <= set(record.graph.targets):
            raise InvalidGraph('publication contains an unknown target')
        references = tuple(owned_outputs.values())[:1]
        for identity in references:
            if not self.blobs.contains(identity):
                raise MissingArtifact('manifest references an unavailable artifact')
        updates = tuple(cache_updates)
        for entry in updates:
            if owned_outputs.get(entry.target) != entry.artifact:
                raise InvalidGraph('cache update disagrees with the manifest')
        return self.catalog.install(project, owned_outputs, updates, epoch, revision)
