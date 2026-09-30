"""Independent behavioral probes and single-defect repair controls, outside reviewed roots."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent / 'job-dispatcher-a'

REPAIRS = {
    'tenant-dedup': ('jobs.py',
        '            previous = self.store.find_dedup(dedup_key) if dedup_key is not None else None',
        '            previous = self.store.find_dedup(dedup_key, tenant) if dedup_key is not None else None'),
    'stale-lease-fence': ('leases.py',
        '        if current.owner != token.owner:',
        '        if current.owner != token.owner or current.generation != token.generation:'),
    'retry-clock-origin': ('retry.py',
        "        return RetryPlan(True, job.created_at + delay, delay, 'retryable')",
        "        return RetryPlan(True, now + delay, delay, 'retryable')"),
    'partial-outbox-ack': ('outbox.py',
        '            if accepted_ids:',
        '            if event.id in accepted_ids:'),
    'running-cancellation': ('jobs.py',
        '            job.cancel_requested = job.state == JobState.READY',
        '            job.cancel_requested = True'),
    'rollback-record-alias': ('store.py',
        '        saved_jobs = dict(self.jobs)',
        '        saved_jobs = deepcopy(self.jobs)'),
}


def apply_repair(root, identifier):
    path, broken, correct = REPAIRS[identifier]
    target = Path(root) / path
    text = target.read_text()
    if text.count(broken) != 1:
        raise ValueError('repair must match exactly one planted source span: ' + identifier)
    target.chmod(target.stat().st_mode | 0o200)
    target.write_text(text.replace(broken, correct))


def load(root):
    root = Path(root)
    name = 'dispatcher_probe_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, root / '__init__.py',
                                                submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tenant_probe(module):
    store, jobs, leases, worker = module.dispatcher()
    first = jobs.enqueue('alpha', 'mail', {'secret': 'alpha'}, 0, dedup_key='invoice')
    second = jobs.enqueue('beta', 'mail', {'secret': 'beta'}, 0, dedup_key='invoice')
    return (first.tenant, second.tenant, second.payload['secret'],
            first.id == second.id, jobs.count('alpha'), jobs.count('beta'))


def fence_probe(module):
    store, jobs, leases, worker = module.dispatcher(lease_duration=10)
    job = jobs.enqueue('alpha', 'mail', {}, 0)
    original = leases.claim('alpha', 'worker-a', 0)
    current = leases.claim('alpha', 'worker-a', 10)
    try:
        worker.complete(original, {'attempt': 'old'}, 11)
        rejected = False
    except module.leases.StaleLease:
        rejected = True
    value = jobs.snapshot('alpha', job.id)
    return (rejected, value['state'], value['result'],
            len(leases.active('alpha', 11)), current.generation)


def retry_probe(module):
    store, jobs, leases, worker = module.dispatcher(lease_duration=1000)
    job = jobs.enqueue('alpha', 'mail', {}, 0)
    token = leases.claim('alpha', 'worker-a', 0)
    worker.fail(token, 'temporary failure after slow work', 100)
    value = jobs.snapshot('alpha', job.id)
    return (value['state'], value['ready_at'], len(jobs.list_ready('alpha', 100)))


def partial_ack_probe(module):
    store, jobs, leases, worker = module.dispatcher()
    jobs.enqueue('alpha', 'mail', {'item': 1}, 0)
    jobs.enqueue('alpha', 'mail', {'item': 2}, 0)
    sink = module.RecordingSink(acceptance_limit=1)
    outbox = module.Outbox(store, sink)
    first = outbox.dispatch(0)
    sink.acceptance_limit = None
    second = outbox.dispatch(1)
    return (first.accepted, first.remaining, second.attempted, sink.count(), len(store.pending()))


def cancellation_probe(module):
    store, jobs, leases, worker = module.dispatcher()
    job = jobs.enqueue('alpha', 'mail', {}, 0)
    token = leases.claim('alpha', 'worker-a', 0)
    accepted = jobs.cancel('alpha', job.id, 1)
    intent = jobs.snapshot('alpha', job.id)['cancel_requested']
    outcome = worker.complete(token, {'sent': True}, 2)
    kinds = [event.kind for event in store.events.values() if event.kind in ('job.succeeded', 'job.cancelled')]
    return (accepted, intent, outcome, kinds)


def rollback_probe(module):
    store, jobs, leases, worker = module.dispatcher()
    job = jobs.enqueue('alpha', 'mail', {}, 0)
    token = leases.claim('alpha', 'worker-a', 0)
    store.fail_next_emission()
    try:
        worker.complete(token, {'sent': True}, 1)
    except module.store.EmissionFailed:
        rejected = True
    else:
        rejected = False
    value = jobs.snapshot('alpha', job.id)
    return (rejected, value['state'], value['result'], len(leases.active('alpha', 1)), len(store.events))


def direct_tenant_control(module):
    store, jobs, leases, worker = module.dispatcher()
    job = jobs.enqueue('alpha', 'mail', {}, 0)
    try:
        jobs.snapshot('beta', job.id)
    except module.store.UnknownJob:
        return True
    return False


def payload_ownership_control(module):
    store, jobs, leases, worker = module.dispatcher()
    payload = {'settings': {'limit': 3}}
    job = jobs.enqueue('alpha', 'mail', payload, 0)
    payload['settings']['limit'] = 9
    snapshot = jobs.snapshot('alpha', job.id)
    snapshot['payload']['settings']['limit'] = 12
    worker.register('mail', lambda data: data['settings'].pop('limit'))
    worker.execute('alpha', 'worker-a', 0)
    value = jobs.snapshot('alpha', job.id)
    return value['result'], value['payload']['settings']['limit']


def deadline_control(module):
    store, jobs, leases, worker = module.dispatcher(lease_duration=10)
    jobs.enqueue('alpha', 'mail', {}, 0)
    original = leases.claim('alpha', 'worker-a', 0)
    before = leases.claim('alpha', 'worker-b', 9)
    current = leases.claim('alpha', 'worker-b', 10)
    return before is None, current.generation, current.expires_at, original.generation


def expired_control(module):
    store, jobs, leases, worker = module.dispatcher(lease_duration=10)
    job = jobs.enqueue('alpha', 'mail', {}, 0)
    token = leases.claim('alpha', 'worker-a', 0)
    try:
        worker.complete(token, {}, 10)
    except module.leases.StaleLease:
        return jobs.snapshot('alpha', job.id)['state']
    return 'accepted-expired-token'


def retry_budget_control(module):
    store, jobs, leases, worker = module.dispatcher(base_delay=5, max_delay=12)
    job = jobs.enqueue('alpha', 'mail', {}, 0, max_attempts=1)
    token = leases.claim('alpha', 'worker-a', 0)
    outcome = worker.fail(token, 'permanent after final attempt', 1)
    return worker.retry.projected_delays(5), outcome, jobs.snapshot('alpha', job.id)['attempts']


def queued_cancel_control(module):
    store, jobs, leases, worker = module.dispatcher()
    job = jobs.enqueue('alpha', 'mail', {}, 0)
    first = jobs.cancel('alpha', job.id, 1)
    second = jobs.cancel('alpha', job.id, 2)
    return first, second, leases.claim('alpha', 'worker-a', 2), jobs.snapshot('alpha', job.id)['state']


def insert_rollback_control(module):
    store, jobs, leases, worker = module.dispatcher()
    store.fail_next_emission()
    try:
        jobs.enqueue('alpha', 'mail', {}, 0, dedup_key='new')
    except module.store.EmissionFailed:
        pass
    next_job = jobs.enqueue('alpha', 'mail', {}, 1)
    return jobs.count('alpha'), next_job.id, len(store.events), len(store.dedup)


def sink_replay_control(module):
    store, jobs, leases, worker = module.dispatcher()
    jobs.enqueue('alpha', 'mail', {}, 0)
    sink = module.RecordingSink()
    first = sink.publish(store.pending(), 0)
    second = sink.publish(store.pending(), 1)
    return first.accepted_ids == second.accepted_ids, sink.count(), len(sink.attempts)


def zero_ack_control(module):
    store, jobs, leases, worker = module.dispatcher()
    jobs.enqueue('alpha', 'mail', {}, 0)
    sink = module.RecordingSink(acceptance_limit=0)
    report = module.Outbox(store, sink).drain(0, max_batches=5)
    return report.attempted, report.accepted, report.remaining, len(sink.attempts)


def unavailable_transport_control(module):
    store, jobs, leases, worker = module.dispatcher()
    jobs.enqueue('alpha', 'mail', {}, 0)
    sink = module.RecordingSink(); sink.fail_once()
    outbox = module.Outbox(store, sink)
    first = outbox.dispatch(0)
    second = outbox.dispatch(1)
    return first.accepted, first.remaining, bool(first.errors), second.accepted, sink.count()


def unknown_ack_control(module):
    store, jobs, leases, worker = module.dispatcher()
    jobs.enqueue('alpha', 'mail', {}, 0)
    sink = module.RecordingSink(); sink.acknowledge_unknown_once()
    try:
        module.Outbox(store, sink).dispatch(0)
    except ValueError:
        return len(store.pending()), sink.count()
    return 'accepted-unknown-ack'


PROBES = [
    ('tenant-dedup', tenant_probe, ('alpha', 'beta', 'beta', False, 1, 1),
     ('alpha', 'alpha', 'alpha', True, 1, 0)),
    ('stale-lease-fence', fence_probe, (True, 'leased', None, 1, 2),
     (False, 'succeeded', {'attempt': 'old'}, 0, 2)),
    ('retry-clock-origin', retry_probe, ('ready', 105.0, 0), ('ready', 5.0, 1)),
    ('partial-outbox-ack', partial_ack_probe, (1, 1, 1, 2, 0), (1, 0, 0, 1, 0)),
    ('running-cancellation', cancellation_probe, (True, True, 'cancelled', ['job.cancelled']),
     (True, False, 'succeeded', ['job.succeeded'])),
    ('rollback-record-alias', rollback_probe, (True, 'leased', None, 1, 2),
     (True, 'succeeded', {'sent': True}, 1, 2)),
]

CONTROLS = [
    ('direct-tenant-read-isolation', direct_tenant_control, True),
    ('caller-payload-ownership', payload_ownership_control, (3, 3)),
    ('exact-lease-deadline', deadline_control, (True, 2, 20.0, 1)),
    ('expired-token-rejection', expired_control, 'leased'),
    ('retry-cap-and-exhaustion', retry_budget_control, ((5.0, 10.0, 12.0, 12.0), 'failed', 1)),
    ('queued-cancellation', queued_cancel_control, (True, False, None, 'cancelled')),
    ('new-insert-rollback', insert_rollback_control, (1, 'job-1', 1, 0)),
    ('sink-replay-deduplication', sink_replay_control, (True, 1, 2)),
    ('zero-ack-progress-stop', zero_ack_control, (1, 0, 1, 1)),
    ('transport-failure-retains-pending', unavailable_transport_control, (0, 1, True, 1, 1)),
    ('unknown-ack-rejection', unknown_ack_control, (1, 1)),
]


def run_checks(before_root=None, after_root=None, case_root=None, clean=False):
    case_root = Path(case_root or ROOT)
    before = load(before_root or case_root / 'before')
    after = load(after_root or case_root / 'after')
    checks = []
    def check(identifier, kind, actual, expected):
        checks.append({'id': identifier, 'kind': kind, 'passed': actual == expected,
                       'detail': 'expected ' + repr(expected) + '; observed ' + repr(actual)})
    for identifier, probe, correct, broken in PROBES:
        check(identifier + '-before', 'baseline', probe(before), correct)
        check(identifier + ('-clean' if clean else ''),
              'clean-control' if clean else 'defect', probe(after), correct if clean else broken)
    for identifier, probe, expected in CONTROLS:
        check(identifier + '-before', 'baseline-control', probe(before), expected)
        check(identifier, 'clean-control', probe(after), expected)
    return {'case': case_root.name, 'checks': checks, 'passed': all(row['passed'] for row in checks)}


def main(case_root=None, clean=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = run_checks(case_root=case_root, clean=clean)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for row in result['checks']:
            print(('PASS' if row['passed'] else 'FAIL') + ' ' + row['id'] + ': ' + row['detail'])
    return 0 if result['passed'] else 1
