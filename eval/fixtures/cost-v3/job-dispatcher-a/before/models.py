"""Value contracts shared by the synchronous dispatcher and its integrations."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JobState(str, Enum):
    READY = 'ready'
    LEASED = 'leased'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


TERMINAL_STATES = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED})


class DispatcherError(Exception):
    """Base class for deterministic contract failures."""


class UnknownJob(DispatcherError):
    pass


class StaleLease(DispatcherError):
    pass


class InvalidTransition(DispatcherError):
    pass


class EmissionFailed(DispatcherError):
    pass


def identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(label + ' must be a nonempty identifier of at most 128 characters')
    return value


def timestamp(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError('time must be a nonnegative numeric value')
    if value != value or value == float('inf'):
        raise ValueError('time must be finite')
    return float(value)


@dataclass
class Job:
    tenant: str
    id: str
    kind: str
    payload: dict[str, Any]
    created_at: float
    ready_at: float
    max_attempts: int = 3
    dedup_key: str | None = None
    state: JobState = JobState.READY
    attempts: int = 0
    generation: int = 0
    cancel_requested: bool = False
    result: Any = None
    last_error: str | None = None
    completed_at: float | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def identity(self) -> tuple[str, str]:
        return self.tenant, self.id


@dataclass(frozen=True)
class LeaseToken:
    tenant: str
    job_id: str
    owner: str
    generation: int
    expires_at: float

    def identity(self) -> tuple[str, str]:
        return self.tenant, self.job_id


@dataclass(frozen=True)
class RetryPlan:
    retry: bool
    ready_at: float | None
    delay: float
    reason: str


@dataclass
class OutboxEvent:
    id: str
    tenant: str
    job_id: str
    kind: str
    body: dict[str, Any]
    created_at: float
    delivered: bool = False
    delivery_attempts: int = 0


@dataclass(frozen=True)
class DeliveryReceipt:
    """Only accepted_ids were durably accepted; a batch may be partly accepted."""
    accepted_ids: tuple[str, ...]


@dataclass(frozen=True)
class DispatchReport:
    attempted: int
    accepted: int
    remaining: int
    errors: tuple[str, ...] = field(default_factory=tuple)
