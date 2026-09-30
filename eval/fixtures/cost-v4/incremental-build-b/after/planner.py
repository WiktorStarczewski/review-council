"""Freeze a project's build inputs and derive complete content identities."""
import hashlib
import json
from .artifacts import digest
from .errors import InvalidGraph
from .models import BuildPlan, PlanNode


def fingerprint(recipe, sources, dependencies, options):
    encoded = json.dumps({'recipe': recipe, 'sources': sources, 'dependencies': dependencies,
                          'options': options}, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


class Planner:
    def __init__(self, catalog):
        self.catalog = catalog

    def plan(self, project, roots):
        """Source, option, and dependency identities are frozen for the whole closure."""
        record = self.catalog.record(project)
        requested = tuple(sorted(frozenset(roots)))
        if not requested:
            raise InvalidGraph('at least one target is required')
        names = record.graph.order(requested)
        nodes = {}
        options = tuple(sorted(record.options.items()))
        used_sources = set()
        for name in names:
            target = record.graph.targets[name]
            sources = tuple((path, digest(record.sources[path])) for path in sorted(target.sources))
            dependencies = tuple((item, nodes[item].fingerprint) for item in sorted(target.dependencies))
            identity = fingerprint(target.recipe, sources, dependencies, options)
            nodes[name] = PlanNode(target, identity, sources, dependencies)
            used_sources.update(target.sources)
        snapshots = tuple((path, record.sources[path]) for path in sorted(used_sources))
        return BuildPlan(project, record.epoch, record.head.revision, requested,
                         tuple(nodes[name] for name in names), options, snapshots)
