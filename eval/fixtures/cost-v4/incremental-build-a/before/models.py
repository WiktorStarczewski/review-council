"""Project, graph, plan, and publication value objects."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProjectKey:
    tenant: str
    name: str


@dataclass(frozen=True)
class TargetSpec:
    name: str
    recipe: str
    sources: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'sources', tuple(self.sources))
        object.__setattr__(self, 'dependencies', tuple(self.dependencies))


@dataclass(frozen=True)
class PlanNode:
    target: TargetSpec
    fingerprint: str
    source_digests: tuple[tuple[str, str], ...]
    dependency_fingerprints: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BuildPlan:
    project: ProjectKey
    source_epoch: int
    base_revision: int
    roots: tuple[str, ...]
    nodes: tuple[PlanNode, ...]
    options: tuple[tuple[str, str], ...]
    sources: tuple[tuple[str, bytes], ...]

    def node(self, name: str) -> PlanNode:
        for node in self.nodes:
            if node.target.name == name:
                return node
        raise KeyError(name)


@dataclass(frozen=True)
class CacheEntry:
    target: str
    fingerprint: str
    artifact: str


@dataclass(frozen=True)
class Manifest:
    project: ProjectKey
    revision: int
    outputs: tuple[tuple[str, str], ...] = ()


@dataclass
class BuildTicket:
    identifier: str
    plan: BuildPlan
    state: str = 'planned'
    cancel_requested: bool = False
    artifacts: dict[str, str] = field(default_factory=dict)
    cache_updates: list[CacheEntry] = field(default_factory=list)
