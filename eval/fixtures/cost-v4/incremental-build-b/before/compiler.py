"""A deterministic compiler consuming the same identities captured by planning."""
import json


class BundleCompiler:
    def __init__(self):
        self.calls = []

    def compile(self, node, sources, dependencies, options):
        """Emit canonical bundle bytes from source contents and dependency artifacts."""
        target = node.target
        source_rows = [(path, sources[path].hex()) for path in sorted(target.sources)]
        dependency_rows = [(name, dependencies[name]) for name in sorted(target.dependencies)]
        payload = {'recipe': target.recipe, 'sources': source_rows,
                   'dependencies': dependency_rows, 'options': dict(options)}
        result = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
        self.calls.append((target.name, node.fingerprint))
        return result
