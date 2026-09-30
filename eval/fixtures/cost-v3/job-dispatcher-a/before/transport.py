"""Deterministic reference sink. Accepted identities are idempotent across retries."""
from __future__ import annotations
from copy import deepcopy

from .models import DeliveryReceipt, OutboxEvent, timestamp


class RecordingSink:
    def __init__(self, acceptance_limit: int | None = None):
        if acceptance_limit is not None and (type(acceptance_limit) is not int or acceptance_limit < 0):
            raise ValueError('acceptance_limit must be nonnegative')
        self.acceptance_limit = acceptance_limit
        self.received: dict[str, OutboxEvent] = {}
        self.attempts: list[tuple[str, ...]] = []
        self._failures = 0
        self._unknown_ack = False

    def publish(self, events: list[OutboxEvent], now: float) -> DeliveryReceipt:
        """A receipt lists only persisted event identities, possibly a strict subset."""
        timestamp(now)
        if len({event.id for event in events}) != len(events):
            raise ValueError('a batch cannot contain duplicate event identities')
        self.attempts.append(tuple(event.id for event in events))
        if self._failures:
            self._failures -= 1
            raise OSError('transport is temporarily unavailable')
        selected = events if self.acceptance_limit is None else events[:self.acceptance_limit]
        accepted = []
        for event in selected:
            previous = self.received.get(event.id)
            if previous is not None and (previous.tenant, previous.job_id, previous.kind, previous.body) != (
                    event.tenant, event.job_id, event.kind, event.body):
                raise ValueError('an event identity cannot be reused for different content')
            self.received[event.id] = deepcopy(event)
            accepted.append(event.id)
        if self._unknown_ack:
            self._unknown_ack = False
            accepted.append('event-unknown')
        return DeliveryReceipt(tuple(accepted))

    def fail_once(self) -> None:
        self._failures += 1

    def acknowledge_unknown_once(self) -> None:
        self._unknown_ack = True

    def events_for(self, tenant: str, kind: str | None = None) -> list[dict]:
        return [deepcopy(event.body) for event in self.received.values()
                if event.tenant == tenant and (kind is None or event.kind == kind)]

    def count(self, tenant: str | None = None) -> int:
        return sum(tenant is None or event.tenant == tenant for event in self.received.values())

    def reset_attempt_log(self) -> tuple[tuple[str, ...], ...]:
        previous = tuple(self.attempts)
        self.attempts.clear()
        return previous
