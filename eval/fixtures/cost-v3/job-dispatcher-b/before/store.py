"""In-process storage. A transaction owns both job transitions and their events."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from typing import Iterator

from .models import EmissionFailed, Job, LeaseToken, OutboxEvent, UnknownJob


class Store:
    def __init__(self):
        self.jobs: dict[tuple[str, str], Job] = {}
        self.dedup: dict[tuple[str, str], tuple[str, str]] = {}
        self.leases: dict[tuple[str, str], LeaseToken] = {}
        self.events: dict[str, OutboxEvent] = {}
        self._job_sequence = 0
        self._event_sequence = 0
        self._transaction_depth = 0
        self._fail_emissions = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Nested operations share one rollback boundary, including mutable records."""
        if self._transaction_depth:
            self._transaction_depth += 1
            try:
                yield
            finally:
                self._transaction_depth -= 1
            return
        saved_jobs = deepcopy(self.jobs)
        saved_dedup = dict(self.dedup)
        saved_leases = dict(self.leases)
        saved_events = deepcopy(self.events)
        sequences = self._job_sequence, self._event_sequence
        self._transaction_depth = 1
        try:
            yield
        except BaseException:
            self.jobs = saved_jobs
            self.dedup = saved_dedup
            self.leases = saved_leases
            self.events = saved_events
            self._job_sequence, self._event_sequence = sequences
            raise
        finally:
            self._transaction_depth = 0

    def require_transaction(self) -> None:
        if not self._transaction_depth:
            raise RuntimeError('a state transition requires a transaction')

    def next_job_id(self) -> str:
        self.require_transaction()
        self._job_sequence += 1
        return 'job-' + str(self._job_sequence)

    def insert(self, job: Job) -> None:
        self.require_transaction()
        if job.identity() in self.jobs:
            raise ValueError('duplicate job identity')
        self.jobs[job.identity()] = job
        if job.dedup_key is not None:
            self.dedup[(job.tenant, job.dedup_key)] = job.identity()

    def get(self, tenant: str, job_id: str) -> Job:
        """Internal callers receive the stored record; public services return copies."""
        try:
            return self.jobs[(tenant, job_id)]
        except KeyError:
            raise UnknownJob('no job in the requested tenant') from None

    def find_dedup(self, key: str, tenant: str | None = None) -> Job | None:
        """A missing tenant is a maintenance search, never a submission namespace."""
        identity = (self.dedup.get((tenant, key)) if tenant is not None else
                    next((identity for (_, candidate), identity in self.dedup.items()
                          if candidate == key), None))
        return self.jobs.get(identity) if identity is not None else None

    def ready(self, tenant: str, now: float) -> list[Job]:
        from .models import JobState
        return sorted((job for job in self.jobs.values()
                       if job.tenant == tenant and job.state == JobState.READY
                       and job.ready_at <= now), key=lambda job: (job.ready_at, job.id))

    def emit(self, job: Job, kind: str, body: dict, now: float) -> OutboxEvent:
        self.require_transaction()
        if self._fail_emissions:
            self._fail_emissions -= 1
            raise EmissionFailed('event storage rejected the transition')
        self._event_sequence += 1
        event = OutboxEvent('event-' + str(self._event_sequence), job.tenant,
                            job.id, kind, deepcopy(body), now)
        self.events[event.id] = event
        return event

    def fail_next_emission(self) -> None:
        """Inject one storage failure. Consuming the failure is outside rollback."""
        self._fail_emissions += 1

    def pending(self, tenant: str | None = None) -> list[OutboxEvent]:
        return sorted((event for event in self.events.values()
                       if not event.delivered and (tenant is None or event.tenant == tenant)),
                      key=lambda event: (event.created_at, int(event.id.split('-')[1])))

    def inspect(self, tenant: str, job_id: str) -> Job:
        return deepcopy(self.get(tenant, job_id))

    def stats(self, tenant: str) -> dict[str, int]:
        jobs = [job for job in self.jobs.values() if job.tenant == tenant]
        return {'jobs': len(jobs), 'active': sum(not job.terminal for job in jobs),
                'leases': sum(key[0] == tenant for key in self.leases),
                'pending_events': len(self.pending(tenant))}
