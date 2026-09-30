"""Deterministic incremental builds with tenant-scoped project publication."""
from .builds import BuildService
from .errors import (BuildCancelled, BuildError, BuildNotReady, InvalidGraph,
                     MissingArtifact, StaleBuild, UnknownBuild, UnknownProject)
from .models import ProjectKey, TargetSpec


def build_system():
    return BuildService()
