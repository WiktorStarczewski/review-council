"""Retry policy computes a delay from the failed attempt, without advancing a clock."""
from __future__ import annotations
from .models import Job, RetryPlan, timestamp


class RetryPolicy:
    def __init__(self, base_delay: float = 5, max_delay: float = 60):
        self.base_delay = timestamp(base_delay)
        self.max_delay = timestamp(max_delay)
        if self.base_delay <= 0 or self.max_delay < self.base_delay:
            raise ValueError('retry delays require 0 < base_delay <= max_delay')

    def delay_for(self, attempts: int) -> float:
        if type(attempts) is not int or attempts < 1:
            raise ValueError('an attempt must have started before a retry')
        exponent = min(attempts - 1, 20)
        return min(self.max_delay, self.base_delay * 2 ** exponent)

    def schedule(self, job: Job, now: float, retryable: bool) -> RetryPlan:
        """ready_at is measured from the failure time, including long-running attempts."""
        now = timestamp(now)
        if job.cancel_requested:
            return RetryPlan(False, None, 0, 'cancelled')
        if not retryable:
            return RetryPlan(False, None, 0, 'not-retryable')
        if job.attempts >= job.max_attempts:
            return RetryPlan(False, None, 0, 'attempts-exhausted')
        delay = self.delay_for(job.attempts)
        return RetryPlan(True, now + delay, delay, 'retryable')

    def describe(self, attempts: int) -> dict:
        delay = self.delay_for(attempts)
        return {'attempts': attempts, 'delay': delay, 'capped': delay == self.max_delay}

    @classmethod
    def from_config(cls, values: dict):
        allowed = {'base_delay', 'max_delay'}
        if not isinstance(values, dict) or not set(values) <= allowed:
            raise ValueError('unknown retry configuration')
        return cls(**values)

    def remaining(self, job: Job) -> int:
        return max(0, job.max_attempts - job.attempts)

    def projected_delays(self, max_attempts: int) -> tuple[float, ...]:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise ValueError('invalid attempt budget')
        return tuple(self.delay_for(attempt) for attempt in range(1, max_attempts))

    def total_wait(self, max_attempts: int) -> float:
        return sum(self.projected_delays(max_attempts))
