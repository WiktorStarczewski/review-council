"""Independent runtime observations and isolated source repairs for the build corpus."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True
_sequence = 0
ROOT = Path(__file__).resolve().parent / 'incremental-build-a'

REPAIRS = {
    'transitive-input-identity': ('planner.py',
        '            dependencies = tuple((item, item) for item in sorted(target.dependencies))',
        '            dependencies = tuple((item, nodes[item].fingerprint) for item in sorted(target.dependencies))'),
    'reverse-invalidation-closure': ('graph.py',
        '                    pending.extend(())',
        '                    pending.append(parent)'),
    'complete-manifest-validation': ('publication.py',
        '        references = tuple(owned_outputs.values())[:1]',
        '        references = tuple(owned_outputs.values())'),
    'active-staging-retention': ('artifacts.py',
        '        staged = set()',
        '        staged = set().union(*self._pins.values()) if self._pins else set()'),
    'compiler-option-identity': ('planner.py',
        "                          'options': ()}, sort_keys=True, separators=(',', ':')).encode()",
        "                          'options': options}, sort_keys=True, separators=(',', ':')).encode()"),
}


def apply_repair(root, identifier):
    path, broken, correct = REPAIRS[identifier]
    target = Path(root) / path
    text = target.read_text()
    if text.count(broken) != 1:
        raise ValueError('repair must match exactly one source span: ' + identifier)
    target.write_text(text.replace(broken, correct))


def load(root):
    global _sequence
    _sequence += 1
    root = Path(root)
    name = 'heldout_build_' + str(_sequence)
    for existing in tuple(sys.modules):
        if existing == name or existing.startswith(name + '.'):
            del sys.modules[existing]
    spec = importlib.util.spec_from_file_location(name, root / '__init__.py',
                                                submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def workspace(module, chain=False, options=None, tenant='tenant', name='project', service=None):
    service = service or module.build_system()
    targets = [module.TargetSpec('leaf', 'bundle', ('input',))]
    if chain:
        targets.extend([module.TargetSpec('middle', 'bundle', (), ('leaf',)),
                        module.TargetSpec('root', 'bundle', (), ('middle',))])
    project = service.create_project(tenant, name, {'input': b'one'}, targets, options)
    return service, project


def transitive_probe(module):
    service, project = workspace(module, chain=True)
    service.build(project, ('root',))
    published = service.fetch(project, 'root')
    original = service.plan(project, ('root',))
    service.set_source(project, 'input', b'two')
    current = service.plan(project, ('root',))
    changed = [original.node(name).fingerprint != current.node(name).fingerprint
               for name in ('root', 'leaf', 'middle')]
    service.build(project, ('root',))
    return changed + [published != service.fetch(project, 'root')]


def invalidation_probe(module):
    service, project = workspace(module, chain=True)
    service.build(project, ('root',))
    service.set_source(project, 'input', b'two')
    try:
        service.fetch(project, 'root')
    except module.BuildNotReady:
        blocked = True
    else:
        blocked = False
    return service.status(project)['dirty'], blocked


def publication_probe(module):
    service, project = workspace(module, chain=True)
    previous = service.build(project, ('root',))
    state = service.status(project)
    available = dict(previous.outputs)['leaf']
    try:
        service.publisher.commit(project, {'leaf': available, 'root': '0' * 64},
                                 state['epoch'], state['revision'], ())
    except module.MissingArtifact:
        rejected = True
    else:
        rejected = False
    current = service.status(project)
    return rejected, current['revision'], current['outputs'] == state['outputs']


def staging_probe(module):
    service, project = workspace(module)
    ticket = service.begin(project, ('leaf',))
    service.compile(ticket)
    identity = service.ticket(project, ticket)['artifacts']['leaf']
    service.collect()
    retained = service.blobs.contains(identity)
    try:
        service.finish(ticket)
    except module.MissingArtifact:
        published = False
    else:
        published = True
    return retained, published, service.status(project)['revision']


def options_probe(module):
    service, project = workspace(module, options={'mode': 'debug'})
    service.build(project, ('leaf',))
    original = service.fetch(project, 'leaf')
    service.set_options(project, {'mode': 'release'})
    service.build(project, ('leaf',))
    current = service.fetch(project, 'leaf')
    return original != current, json.loads(current)['options'], len(service.compiler.calls)


def project_control(module):
    service, first = workspace(module)
    _, second = workspace(module, tenant='other', service=service)
    service.build(first, ('leaf',))
    try:
        service.fetch(second, 'leaf')
    except module.BuildNotReady:
        private_head = True
    else:
        private_head = False
    service.build(second, ('leaf',))
    return private_head, service.fetch(first, 'leaf') == service.fetch(second, 'leaf'), len(service.blobs)


def cancellation_control(module):
    service, project = workspace(module)
    service.build(project, ('leaf',))
    service.set_source(project, 'input', b'two')
    state = service.status(project)
    ticket = service.begin(project, ('leaf',))
    service.compile(ticket)
    first, repeated = service.cancel(project, ticket), service.cancel(project, ticket)
    try:
        service.finish(ticket)
    except module.BuildCancelled:
        rejected = True
    else:
        rejected = False
    return first, repeated, rejected, state == service.status(project), len(service.collect())


def version_control(module):
    service, project = workspace(module)
    first, second = service.begin(project, ('leaf',)), service.begin(project, ('leaf',))
    service.compile(first)
    service.compile(second)
    service.finish(first)
    try:
        service.finish(second)
    except module.StaleBuild:
        revision_rejected = True
    else:
        revision_rejected = False
    third = service.begin(project, ('leaf',))
    service.compile(third)
    service.set_source(project, 'input', b'two')
    try:
        service.finish(third)
    except module.StaleBuild:
        source_rejected = True
    else:
        source_rejected = False
    return revision_rejected, source_rejected, service.status(project)['revision']


def no_op_control(module):
    service, project = workspace(module, options={'mode': 'debug'})
    ticket = service.begin(project, ('leaf',))
    service.compile(ticket)
    same_source = service.set_source(project, 'input', b'one')
    same_options = service.set_options(project, {'mode': 'debug'})
    return same_source, same_options, service.finish(ticket).revision


def ownership_control(module):
    service = module.build_system()
    sources, options = {'input': b'one'}, {'mode': 'debug'}
    project = service.create_project('tenant', 'project', sources,
                                     [module.TargetSpec('leaf', 'bundle', ('input',))], options)
    sources['input'], options['mode'] = b'two', 'release'
    service.build(project, ('leaf',))
    snapshot = service.status(project)
    snapshot['outputs'].clear()
    snapshot['dirty'].append('leaf')
    result = json.loads(service.fetch(project, 'leaf'))
    return result['sources'], result['options'], service.status(project)['dirty']


def graph_control(module):
    service = module.build_system()
    cases = [
        [module.TargetSpec('a', 'bundle', (), ('b',)), module.TargetSpec('b', 'bundle', (), ('a',))],
        [module.TargetSpec('a', 'bundle', (), ('missing',))],
        [module.TargetSpec('a', 'bundle'), module.TargetSpec('a', 'bundle')],
    ]
    rejected = 0
    for index, targets in enumerate(cases):
        try:
            service.create_project('tenant', str(index), {}, targets)
        except module.InvalidGraph:
            rejected += 1
    return rejected


def weak_cache_control(module):
    service, project = workspace(module)
    service.build(project, ('leaf',))
    original = service.fetch(project, 'leaf')
    service.set_source(project, 'input', b'two')
    service.build(project, ('leaf',))
    removed = service.collect()
    service.set_source(project, 'input', b'one')
    service.build(project, ('leaf',))
    return len(removed), original == service.fetch(project, 'leaf'), len(service.compiler.calls)


def duplicate_roots_control(module):
    service, project = workspace(module, chain=True)
    plan = service.plan(project, ('root', 'leaf', 'root'))
    service.build(project, ('root', 'leaf', 'root'))
    return plan.roots, tuple(node.target.name for node in plan.nodes), len(service.compiler.calls)


def option_order_control(module):
    service, project = workspace(module, options={'z': 'last', 'a': 'first'})
    first = service.plan(project, ('leaf',)).node('leaf').fingerprint
    service.build(project, ('leaf',))
    original = service.fetch(project, 'leaf')
    changed = service.set_options(project, {'a': 'first', 'z': 'last'})
    second = service.plan(project, ('leaf',)).node('leaf').fingerprint
    service.build(project, ('leaf',))
    return changed, first == second, original == service.fetch(project, 'leaf'), len(service.compiler.calls)


def head_merge_control(module):
    service = module.build_system()
    project = service.create_project('tenant', 'project', {'a': b'one', 'b': b'two'},
                                     [module.TargetSpec('a', 'bundle', ('a',)),
                                      module.TargetSpec('b', 'bundle', ('b',))])
    service.build(project, ('a',))
    first = service.fetch(project, 'a')
    service.build(project, ('b',))
    return sorted(service.status(project)['outputs']), first == service.fetch(project, 'a'), service.collect()


def ticket_scope_control(module):
    service, first = workspace(module)
    _, second = workspace(module, tenant='other', service=service)
    ticket = service.begin(first, ('leaf',))
    rejected = 0
    for operation in (service.ticket, service.cancel):
        try:
            operation(second, ticket)
        except module.UnknownBuild:
            rejected += 1
    return rejected, service.ticket(first, ticket)['state']


PROBES = [
    ('transitive-input-identity', transitive_probe, [True, True, True, True], [False, True, False, False]),
    ('reverse-invalidation-closure', invalidation_probe, (['leaf', 'middle', 'root'], True), (['leaf', 'middle'], False)),
    ('complete-manifest-validation', publication_probe, (True, 1, True), (False, 2, False)),
    ('active-staging-retention', staging_probe, (True, True, 1), (False, False, 0)),
    ('compiler-option-identity', options_probe, (True, {'mode': 'release'}, 2), (False, {'mode': 'debug'}, 1)),
]

CONTROLS = [
    ('project-heads-and-global-content', project_control, (True, True, 1)),
    ('cancel-after-staging', cancellation_control, (True, False, True, True, 1)),
    ('project-version-fences', version_control, (True, True, 1)),
    ('identical-input-noops', no_op_control, (False, False, 1)),
    ('caller-snapshot-ownership', ownership_control, ([['input', '6f6e65']], {'mode': 'debug'}, [])),
    ('invalid-graph-rejection', graph_control, 3),
    ('weak-cache-rebuild', weak_cache_control, (1, True, 3)),
    ('root-order-and-deduplication', duplicate_roots_control, (('leaf', 'root'), ('leaf', 'middle', 'root'), 3)),
    ('canonical-option-order', option_order_control, (False, True, True, 1)),
    ('partial-target-head-merge', head_merge_control, (['a', 'b'], True, [])),
    ('project-scoped-ticket-access', ticket_scope_control, (2, 'planned')),
]


def run_checks(before_root=None, after_root=None, case_root=None, clean=False):
    case_root = Path(case_root or ROOT)
    before = load(before_root or case_root / 'before')
    after = load(after_root or case_root / 'after')
    checks = []

    def check(identifier, kind, probe, module, expected):
        try:
            actual = probe(module)
        except Exception as error:
            actual = 'unexpected ' + type(error).__name__ + ': ' + str(error)
        checks.append({'id': identifier, 'kind': kind, 'passed': actual == expected,
                       'detail': 'expected ' + repr(expected) + '; observed ' + repr(actual)})

    for identifier, probe, correct, broken in PROBES:
        check(identifier + '-before', 'baseline', probe, before, correct)
        check(identifier + ('-clean' if clean else ''), 'clean-control' if clean else 'defect',
              probe, after, correct if clean else broken)
    for identifier, probe, expected in CONTROLS:
        check(identifier + '-before', 'baseline-control', probe, before, expected)
        check(identifier, 'clean-control', probe, after, expected)
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
