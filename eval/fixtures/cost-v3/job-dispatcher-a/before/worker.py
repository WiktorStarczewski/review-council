"""Execution owns lease checks and atomically commits job outcomes with events."""
from __future__ import annotations
from copy import deepcopy
from typing import Callable

from .jobs import JobService
from .leases import LeaseManager
from .models import JobState, LeaseToken, timestamp
from .retry import RetryPolicy
from .store import Store


class Worker:
    def __init__(self, store: Store, leases: LeaseManager, retry: RetryPolicy):
        if leases.store is not store:
            raise ValueError('worker and lease manager must share a store')
        self.store = store
        self.leases = leases
        self.retry = retry
        self.handlers: dict[str, Callable[[dict], object]] = {}

    def register(self, kind: str, handler: Callable[[dict], object]) -> None:
        if kind in self.handlers:
            raise ValueError('handler is already registered')
        if not callable(handler):
            raise ValueError('handler must be callable')
        self.handlers[kind] = handler

    def complete(self, token: LeaseToken, result: object, now: float) -> str:
        now = timestamp(now)
        with self.store.transaction():
            job = self.leases.require(token, now)
            self.store.leases.pop(token.identity())
            job.completed_at = now
            if job.cancel_requested:
                job.state = JobState.CANCELLED
                job.result = None
                self.store.emit(job, 'job.cancelled', {'stage': 'active'}, now)
            else:
                job.state = JobState.SUCCEEDED
                job.result = deepcopy(result)
                job.last_error = None
                self.store.emit(job, 'job.succeeded', {'result': result}, now)
            return job.state.value

    def fail(self, token: LeaseToken, error: str, now: float, retryable: bool = True) -> str:
        now = timestamp(now)
        with self.store.transaction():
            job = self.leases.require(token, now)
            plan = self.retry.schedule(job, now, retryable)
            self.store.leases.pop(token.identity())
            job.last_error = str(error)[:512]
            if job.cancel_requested:
                job.state = JobState.CANCELLED
                job.completed_at = now
                self.store.emit(job, 'job.cancelled', {'stage': 'failed-active'}, now)
            elif plan.retry:
                job.state = JobState.READY
                job.ready_at = plan.ready_at
                self.store.emit(job, 'job.retry-scheduled',
                                {'ready_at': plan.ready_at, 'error': job.last_error}, now)
            else:
                job.state = JobState.FAILED
                job.completed_at = now
                self.store.emit(job, 'job.failed', {'reason': plan.reason, 'error': job.last_error}, now)
            return job.state.value

    def execute(self, tenant: str, owner: str, now: float) -> str | None:
        """A synchronous attempt uses the supplied time for claim and completion."""
        now = timestamp(now)
        token = self.leases.claim(tenant, owner, now)
        if token is None:
            return None
        job = self.leases.require(token, now)
        handler = self.handlers.get(job.kind)
        if handler is None:
            return self.fail(token, 'unknown handler: ' + job.kind, now, retryable=False)
        if job.cancel_requested:
            return self.complete(token, None, now)
        try:
            result = handler(deepcopy(job.payload))
        except Exception as error:
            return self.fail(token, str(error), now)
        return self.complete(token, result, now)

    def process_ready(self, tenant: str, owner: str, now: float, limit: int = 10) -> list[str]:
        if type(limit) is not int or limit < 0:
            raise ValueError('limit must be nonnegative')
        outcomes = []
        for _ in range(limit):
            state = self.execute(tenant, owner, now)
            if state is None:
                break
            outcomes.append(state)
        return outcomes

    def status(self, tenant: str, job_id: str) -> dict:
        return JobService(self.store).snapshot(tenant, job_id)

    def diagnostic(self, tenant: str) -> str:
        stats = self.store.stats(tenant)
        return 'jobs={jobs} active={active} leases={leases} pending={pending_events}'.format(**stats)
