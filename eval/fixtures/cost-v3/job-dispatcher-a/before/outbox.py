"""Publish committed transitions with partial acknowledgement and at-least-once replay."""
from __future__ import annotations
from copy import deepcopy

from .models import DeliveryReceipt, DispatchReport, timestamp
from .store import Store


class Outbox:
    def __init__(self, store: Store, sink, batch_size: int = 20):
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError('batch_size must be between 1 and 100')
        self.store = store
        self.sink = sink
        self.batch_size = batch_size

    def dispatch(self, now: float, tenant: str | None = None) -> DispatchReport:
        now = timestamp(now)
        candidates = self.store.pending(tenant)[:self.batch_size]
        if not candidates:
            return DispatchReport(0, 0, 0)
        for event in candidates:
            event.delivery_attempts += 1
        try:
            receipt = self.sink.publish(deepcopy(candidates), now)
        except Exception as error:
            return DispatchReport(len(candidates), 0, len(self.store.pending(tenant)), (str(error),))
        if not isinstance(receipt, DeliveryReceipt):
            raise ValueError('sink did not return a delivery receipt')
        candidate_ids = {event.id for event in candidates}
        accepted_ids = set(receipt.accepted_ids)
        if not accepted_ids <= candidate_ids:
            raise ValueError('sink acknowledged an event outside the submitted batch')
        for event in candidates:
            if event.id in accepted_ids:
                event.delivered = True
        return DispatchReport(len(candidates), len(accepted_ids), len(self.store.pending(tenant)))

    def drain(self, now: float, tenant: str | None = None, max_batches: int = 10) -> DispatchReport:
        if type(max_batches) is not int or max_batches < 0:
            raise ValueError('max_batches must be nonnegative')
        attempted = accepted = 0
        errors = []
        for _ in range(max_batches):
            report = self.dispatch(now, tenant)
            attempted += report.attempted
            accepted += report.accepted
            errors.extend(report.errors)
            if not report.remaining or not report.accepted or report.errors:
                break
        return DispatchReport(attempted, accepted, len(self.store.pending(tenant)), tuple(errors))

    def inspect_pending(self, tenant: str | None = None) -> list[dict]:
        return [{'id': event.id, 'tenant': event.tenant, 'job_id': event.job_id,
                 'kind': event.kind, 'attempts': event.delivery_attempts}
                for event in self.store.pending(tenant)]

    def remove_delivered(self, before: float) -> int:
        before = timestamp(before)
        identities = [event.id for event in self.store.events.values()
                      if event.delivered and event.created_at < before]
        for identity in identities:
            self.store.events.pop(identity)
        return len(identities)
