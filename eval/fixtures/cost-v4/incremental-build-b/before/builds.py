"""Synchronous build coordination with explicit compile and publication boundaries."""
from .artifacts import BlobStore
from .catalog import Catalog
from .compiler import BundleCompiler
from .errors import BuildCancelled, BuildNotReady, UnknownBuild
from .models import BuildTicket, CacheEntry
from .planner import Planner
from .publication import Publisher


class BuildService:
    def __init__(self):
        self.catalog = Catalog()
        self.blobs = BlobStore()
        self.compiler = BundleCompiler()
        self.planner = Planner(self.catalog)
        self.publisher = Publisher(self.catalog, self.blobs)
        self._tickets = {}
        self._sequence = 0

    def create_project(self, tenant, name, sources, targets, options=None):
        return self.catalog.create(tenant, name, sources, targets, options)

    def set_source(self, project, path, payload):
        return self.catalog.set_source(project, path, payload)

    def set_options(self, project, options):
        return self.catalog.set_options(project, options)

    def plan(self, project, targets):
        return self.planner.plan(project, targets)

    def begin(self, project, targets):
        plan = self.plan(project, targets)
        self._sequence += 1
        identifier = 'build-' + str(self._sequence)
        self._tickets[identifier] = BuildTicket(identifier, plan)
        return identifier

    def _ticket(self, identifier, project=None):
        ticket = self._tickets.get(identifier)
        if ticket is None or (project is not None and ticket.plan.project != project):
            raise UnknownBuild('build is unavailable')
        return ticket

    def compile(self, identifier):
        """Compile or reuse every dependency, retaining its bytes until terminal state."""
        ticket = self._ticket(identifier)
        if ticket.cancel_requested:
            raise BuildCancelled('build cancelled')
        if ticket.state == 'compiled':
            return self.ticket(ticket.plan.project, identifier)
        if ticket.state != 'planned':
            raise BuildNotReady('build cannot compile from its current state')
        plan = ticket.plan
        record = self.catalog.record(plan.project)
        sources = dict(plan.sources)
        try:
            for node in plan.nodes:
                name = node.target.name
                cached = record.cache.get((name, node.fingerprint))
                if cached is not None and self.blobs.contains(cached):
                    self.blobs.pin(identifier, cached)
                    identity = cached
                else:
                    dependencies = {item: ticket.artifacts[item] for item in node.target.dependencies}
                    payload = self.compiler.compile(node, sources, dependencies, plan.options)
                    identity = self.blobs.put(payload, identifier)
                ticket.artifacts[name] = identity
                ticket.cache_updates.append(CacheEntry(name, node.fingerprint, identity))
        except Exception:
            ticket.state = 'failed'
            self.blobs.release(identifier)
            raise
        ticket.state = 'compiled'
        return self.ticket(plan.project, identifier)

    def finish(self, identifier):
        """Publish only a complete, uncancelled build against its original project version."""
        ticket = self._ticket(identifier)
        if ticket.cancel_requested:
            raise BuildCancelled('build cancelled')
        if ticket.state != 'compiled':
            raise BuildNotReady('build must be compiled before publication')
        plan = ticket.plan
        try:
            manifest = self.publisher.commit(plan.project, ticket.artifacts, plan.source_epoch,
                                             plan.base_revision, ticket.cache_updates)
        except Exception:
            ticket.state = 'failed'
            self.blobs.release(identifier)
            raise
        ticket.state = 'published'
        self.blobs.release(identifier)
        return manifest

    def build(self, project, targets):
        identifier = self.begin(project, targets)
        self.compile(identifier)
        return self.finish(identifier)

    def cancel(self, project, identifier):
        """Cancellation before publication is terminal and releases all staging pins."""
        ticket = self._ticket(identifier, project)
        if ticket.state in ('cancelled', 'failed', 'published'):
            return False
        ticket.cancel_requested = True
        ticket.state = 'cancelled'
        self.blobs.release(identifier)
        return True

    def ticket(self, project, identifier):
        value = self._ticket(identifier, project)
        return {'id': value.identifier, 'state': value.state,
                'project': (value.plan.project.tenant, value.plan.project.name),
                'artifacts': dict(value.artifacts), 'cancel_requested': value.cancel_requested}

    def fetch(self, project, target):
        """Read only a current published output belonging to the selected project."""
        record = self.catalog.record(project)
        identity = dict(record.head.outputs).get(target)
        if target in record.dirty or identity is None:
            raise BuildNotReady('target has no current published output')
        return self.blobs.read(identity)

    def status(self, project):
        return self.catalog.status(project)

    def collect(self):
        return self.blobs.collect(self.catalog.published_artifacts())
