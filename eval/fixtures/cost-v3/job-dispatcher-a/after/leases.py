"""Lease generation fences attempts even when the same worker name is reused."""
from __future__ import annotations
from dataclasses import replace

from .models import JobState, LeaseToken, StaleLease, identifier, timestamp
from .store import Store


class LeaseManager:
    def __init__(self, store: Store, duration: float = 30):
        self.store = store
        self.duration = timestamp(duration)
        if not self.duration:
            raise ValueError('lease duration must be positive')

    def claim(self, tenant: str, owner: str, now: float) -> LeaseToken | None:
        tenant = identifier(tenant, 'tenant')
        owner = identifier(owner, 'owner')
        now = timestamp(now)
        self.recover(now, tenant)
        with self.store.transaction():
            candidates = self.store.ready(tenant, now)
            if not candidates:
                return None
            job = candidates[0]
            if job.cancel_requested:
                return None
            job.attempts += 1
            job.generation += 1
            job.state = JobState.LEASED
            token = LeaseToken(tenant, job.id, owner, job.generation, now + self.duration)
            self.store.leases[job.identity()] = token
            self.store.emit(job, 'job.claimed', {'attempt': job.attempts, 'owner': owner}, now)
            return token

    def require(self, token: LeaseToken, now: float):
        now = timestamp(now)
        job = self.store.get(token.tenant, token.job_id)
        current = self.store.leases.get(token.identity())
        if (job.state != JobState.LEASED or current is None
                or current.expires_at <= now):
            raise StaleLease('the active lease is unavailable or expired')
        if current.owner != token.owner:
            raise StaleLease('the token does not own this attempt')
        return job

    def renew(self, token: LeaseToken, now: float) -> LeaseToken:
        now = timestamp(now)
        with self.store.transaction():
            job = self.require(token, now)
            renewed = replace(self.store.leases[token.identity()], expires_at=now + self.duration)
            self.store.leases[token.identity()] = renewed
            self.store.emit(job, 'job.lease-renewed', {'expires_at': renewed.expires_at}, now)
            return renewed

    def release(self, token: LeaseToken, now: float) -> None:
        now = timestamp(now)
        with self.store.transaction():
            job = self.require(token, now)
            self.store.leases.pop(token.identity())
            job.state = JobState.READY
            job.ready_at = now
            self.store.emit(job, 'job.released', {'attempt': job.attempts}, now)

    def recover(self, now: float, tenant: str | None = None) -> int:
        """At the exact deadline the attempt is expired and may be reclaimed."""
        now = timestamp(now)
        recovered = 0
        with self.store.transaction():
            for key, token in list(self.store.leases.items()):
                if token.expires_at > now or (tenant is not None and token.tenant != tenant):
                    continue
                job = self.store.get(*key)
                self.store.leases.pop(key)
                if job.cancel_requested:
                    job.state = JobState.CANCELLED
                    job.completed_at = now
                    self.store.emit(job, 'job.cancelled', {'stage': 'lease-expired'}, now)
                elif job.attempts >= job.max_attempts:
                    job.state = JobState.FAILED
                    job.completed_at = now
                    job.last_error = 'lease expired after final attempt'
                    self.store.emit(job, 'job.failed', {'error': job.last_error}, now)
                else:
                    job.state = JobState.READY
                    job.ready_at = now
                    self.store.emit(job, 'job.lease-expired', {'attempt': job.attempts}, now)
                recovered += 1
        return recovered

    def active(self, tenant: str, now: float) -> list[LeaseToken]:
        now = timestamp(now)
        return sorted((token for token in self.store.leases.values()
                       if token.tenant == tenant and token.expires_at > now),
                      key=lambda token: token.job_id)
