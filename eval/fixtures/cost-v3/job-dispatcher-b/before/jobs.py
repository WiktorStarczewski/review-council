"""Tenant-scoped submission and cancellation contracts for external callers."""
from __future__ import annotations
from copy import deepcopy

from .models import Job, JobState, identifier, timestamp
from .store import Store


class JobService:
    def __init__(self, store: Store):
        self.store = store

    def enqueue(self, tenant: str, kind: str, payload: dict, now: float,
                dedup_key: str | None = None, max_attempts: int = 3,
                ready_at: float | None = None) -> Job:
        """A dedup key identifies one submission within its tenant, including terminal jobs."""
        tenant = identifier(tenant, 'tenant')
        kind = identifier(kind, 'kind')
        now = timestamp(now)
        ready_at = now if ready_at is None else timestamp(ready_at)
        if not isinstance(payload, dict):
            raise ValueError('payload must be a dictionary')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise ValueError('max_attempts must be between 1 and 100')
        if dedup_key is not None:
            dedup_key = identifier(dedup_key, 'dedup key')
        with self.store.transaction():
            previous = self.store.find_dedup(dedup_key, tenant) if dedup_key is not None else None
            if previous is not None:
                return deepcopy(previous)
            job = Job(tenant, self.store.next_job_id(), kind, deepcopy(payload),
                      now, ready_at, max_attempts=max_attempts, dedup_key=dedup_key)
            self.store.insert(job)
            self.store.emit(job, 'job.enqueued', {'kind': kind}, now)
            return deepcopy(job)

    def cancel(self, tenant: str, job_id: str, now: float) -> bool:
        """Queued cancellation is immediate; active cancellation is observed at completion."""
        now = timestamp(now)
        with self.store.transaction():
            job = self.store.get(tenant, job_id)
            if job.terminal or job.cancel_requested:
                return False
            job.cancel_requested = True
            if job.state == JobState.READY:
                job.state = JobState.CANCELLED
                job.completed_at = now
                self.store.emit(job, 'job.cancelled', {'stage': 'queued'}, now)
            else:
                self.store.emit(job, 'job.cancel-requested', {'stage': 'active'}, now)
            return True

    def snapshot(self, tenant: str, job_id: str) -> dict:
        """Return owned public data; caller mutations cannot change a later execution."""
        job = self.store.inspect(tenant, job_id)
        return {'tenant': job.tenant, 'id': job.id, 'kind': job.kind,
                'state': job.state.value, 'payload': job.payload, 'result': job.result,
                'attempts': job.attempts, 'ready_at': job.ready_at,
                'cancel_requested': job.cancel_requested, 'last_error': job.last_error}

    def list_ready(self, tenant: str, now: float, limit: int = 20) -> list[dict]:
        if type(limit) is not int or limit < 0:
            raise ValueError('limit must be a nonnegative integer')
        rows = self.store.ready(identifier(tenant, 'tenant'), timestamp(now))
        return [self.snapshot(tenant, job.id) for job in rows[:limit]]

    def reschedule(self, tenant: str, job_id: str, ready_at: float, now: float) -> None:
        """Only a waiting job may be moved; active ownership remains with its lease."""
        from .models import InvalidTransition
        ready_at = timestamp(ready_at)
        now = timestamp(now)
        with self.store.transaction():
            job = self.store.get(tenant, job_id)
            if job.state != JobState.READY:
                raise InvalidTransition('only a ready job can be rescheduled')
            job.ready_at = ready_at
            self.store.emit(job, 'job.rescheduled', {'ready_at': ready_at}, now)

    def count(self, tenant: str) -> int:
        return self.store.stats(identifier(tenant, 'tenant'))['jobs']
