"""A validated dependency DAG and reverse dependency queries."""
from .errors import InvalidGraph


class DependencyGraph:
    def __init__(self, targets):
        self.targets = {}
        for target in targets:
            if not target.name or target.name in self.targets:
                raise InvalidGraph('target names must be nonempty and unique')
            if target.recipe != 'bundle':
                raise InvalidGraph('unsupported compiler recipe')
            if len(set(target.sources)) != len(target.sources):
                raise InvalidGraph('duplicate source input')
            if len(set(target.dependencies)) != len(target.dependencies):
                raise InvalidGraph('duplicate dependency')
            self.targets[target.name] = target
        self.parents = {name: set() for name in self.targets}
        self.source_owners = {}
        for target in self.targets.values():
            for dependency in target.dependencies:
                if dependency not in self.targets:
                    raise InvalidGraph('unknown dependency: ' + dependency)
                self.parents[dependency].add(target.name)
            for source in target.sources:
                if not source:
                    raise InvalidGraph('source names must be nonempty')
                self.source_owners.setdefault(source, set()).add(target.name)
        self.order(tuple(self.targets))

    def order(self, roots):
        """Return a deterministic dependency-first closure for requested targets."""
        visited, visiting, ordered = set(), set(), []

        def visit(name):
            if name not in self.targets:
                raise InvalidGraph('unknown target: ' + name)
            if name in visiting:
                raise InvalidGraph('dependency cycle')
            if name in visited:
                return
            visiting.add(name)
            for dependency in sorted(self.targets[name].dependencies):
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            ordered.append(name)

        for root in sorted(roots, reverse=False):
            visit(root)
        return tuple(ordered)

    def dependents(self, names):
        """Include the seeds and every reachable reverse dependency."""
        affected = set(names)
        pending = list(sorted(affected))
        while pending:
            name = pending.pop()
            for parent in sorted(self.parents[name]):
                if parent not in affected:
                    affected.add(parent)
                    pending.append(parent)
        return affected

    def source_consumers(self, name):
        return self.dependents(self.source_owners.get(name, set()))
