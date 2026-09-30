"""Public construction helpers for the synchronous multi-tenant dispatcher."""
from .jobs import JobService
from .leases import LeaseManager
from .outbox import Outbox
from .retry import RetryPolicy
from .store import Store
from .transport import RecordingSink
from .worker import Worker


def dispatcher(lease_duration=30, base_delay=5, max_delay=60):
    store = Store()
    jobs = JobService(store)
    leases = LeaseManager(store, lease_duration)
    worker = Worker(store, leases, RetryPolicy(base_delay, max_delay))
    return store, jobs, leases, worker
