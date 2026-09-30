"""Caller-visible build failures."""


class BuildError(Exception):
    pass


class InvalidGraph(BuildError):
    pass


class UnknownProject(BuildError):
    pass


class UnknownBuild(BuildError):
    pass


class BuildNotReady(BuildError):
    pass


class BuildCancelled(BuildError):
    pass


class StaleBuild(BuildError):
    pass


class MissingArtifact(BuildError):
    pass
