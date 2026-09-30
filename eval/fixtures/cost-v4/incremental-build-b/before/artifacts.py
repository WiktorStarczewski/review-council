"""Immutable content-addressed bytes with explicit staging ownership."""
import hashlib
from .errors import MissingArtifact


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


class BlobStore:
    def __init__(self):
        self._objects = {}
        self._pins = {}

    def put(self, payload, owner):
        """Store owned bytes and pin their digest to an active build."""
        value = bytes(payload)
        identity = digest(value)
        self._objects.setdefault(identity, value)
        self.pin(owner, identity)
        return identity

    def pin(self, owner, identity):
        if identity not in self._objects:
            raise MissingArtifact('cannot pin an unavailable artifact')
        self._pins.setdefault(owner, set()).add(identity)

    def release(self, owner):
        self._pins.pop(owner, None)

    def contains(self, identity):
        return identity in self._objects

    def read(self, identity):
        try:
            return self._objects[identity]
        except KeyError:
            raise MissingArtifact('artifact is unavailable') from None

    def collect(self, published):
        """Retain current manifests and every artifact owned by active staging."""
        retained = set(published)
        staged = set().union(*self._pins.values()) if self._pins else set()
        retained.update(staged)
        removed = sorted(set(self._objects) - retained)
        for identity in removed:
            del self._objects[identity]
        return removed

    def __len__(self):
        return len(self._objects)
