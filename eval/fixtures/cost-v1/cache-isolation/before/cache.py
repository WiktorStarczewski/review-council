"""A bounded tenant cache with expiring entries and isolated JSON-like payloads."""
from __future__ import annotations
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Callable


@dataclass(frozen=True)
class CachedValue:
    payload: dict[str, object]
    expires_at: float


class TenantCache:
    """Never share values across tenants or mutable payloads across caller reads."""

    def __init__(self, max_entries: int = 128, clock: Callable[[], float] = monotonic):
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self.clock = clock
        self._entries = OrderedDict()

    @staticmethod
    def _key(tenant: str, name: str) -> tuple[str, str]:
        if not tenant or not name:
            raise ValueError("tenant and name are required")
        return tenant, name

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, value in self._entries.items() if now >= value.expires_at]
        for key in expired:
            del self._entries[key]

    def put(self, tenant: str, name: str, payload: dict[str, object], ttl: float) -> None:
        """Own a copy of the payload and expire it exactly ttl seconds from insertion."""
        key = self._key(tenant, name)
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        now = self.clock()
        self._purge_expired(now)
        self._entries[key] = CachedValue(deepcopy(payload), now + ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def get(self, tenant: str, name: str) -> dict[str, object] | None:
        """Return an independent payload copy, or None for missing and expired entries."""
        key = self._key(tenant, name)
        self._purge_expired(self.clock())
        value = self._entries.get(key)
        if value is None:
            return None
        self._entries.move_to_end(key)
        return deepcopy(value.payload)

    def invalidate(self, tenant: str, name: str) -> bool:
        """Remove an entry in this tenant's namespace if it is still stored."""
        key = self._key(tenant, name)
        return self._entries.pop(key, None) is not None

    def __len__(self) -> int:
        """Count unexpired entries across all tenants."""
        self._purge_expired(self.clock())
        return len(self._entries)
