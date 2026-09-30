"""Project-scoped source versions, manifest heads, and weak cache references."""
from dataclasses import dataclass, field
from .errors import InvalidGraph, StaleBuild, UnknownProject
from .graph import DependencyGraph
from .models import Manifest, ProjectKey


@dataclass
class ProjectRecord:
    key: ProjectKey
    graph: DependencyGraph
    sources: dict
    options: dict
    head: Manifest
    epoch: int = 0
    dirty: set = field(default_factory=set)
    cache: dict = field(default_factory=dict)


class Catalog:
    def __init__(self):
        self._projects = {}

    def create(self, tenant, name, sources, targets, options):
        if not tenant or not name:
            raise ValueError('tenant and project name are required')
        key = ProjectKey(tenant, name)
        if key in self._projects:
            raise ValueError('project already exists')
        graph = DependencyGraph(targets)
        owned_sources = {path: bytes(payload) for path, payload in sources.items()}
        for path in graph.source_owners:
            if path not in owned_sources:
                raise InvalidGraph('missing source input: ' + path)
        owned_options = self.options(options)
        record = ProjectRecord(key, graph, owned_sources, owned_options, Manifest(key, 0))
        record.dirty.update(graph.targets)
        self._projects[key] = record
        return key

    @staticmethod
    def options(values):
        result = dict(values or {})
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in result.items()):
            raise ValueError('compiler options must be string pairs')
        return result

    def record(self, key):
        try:
            return self._projects[key]
        except KeyError:
            raise UnknownProject('project is unavailable') from None

    def set_source(self, key, path, payload):
        record = self.record(key)
        if path not in record.sources:
            raise InvalidGraph('source is not declared')
        value = bytes(payload)
        if record.sources[path] == value:
            return False
        record.sources[path] = value
        record.epoch += 1
        record.dirty.update(record.graph.source_consumers(path))
        return True

    def set_options(self, key, options):
        record = self.record(key)
        values = self.options(options)
        if record.options == values:
            return False
        record.options = values
        record.epoch += 1
        record.dirty.update(record.graph.targets)
        return True

    def check_version(self, key, epoch, revision):
        record = self.record(key)
        if record.epoch != epoch or record.head.revision != revision:
            raise StaleBuild('project changed since planning')
        return record

    def install(self, key, outputs, cache_updates, epoch, revision):
        record = self.check_version(key, epoch, revision)
        updated = dict(record.head.outputs)
        updated.update(outputs)
        cache = dict(record.cache)
        for entry in cache_updates:
            cache[(entry.target, entry.fingerprint)] = entry.artifact
        head = Manifest(key, revision + 1, tuple(sorted(updated.items())))
        record.head, record.cache = head, cache
        record.dirty.difference_update(outputs)
        return head

    def published_artifacts(self):
        return {identity for record in self._projects.values() for _, identity in record.head.outputs}

    def status(self, key):
        record = self.record(key)
        return {'epoch': record.epoch, 'revision': record.head.revision,
                'dirty': sorted(record.dirty), 'outputs': dict(record.head.outputs)}
