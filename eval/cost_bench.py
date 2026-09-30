#!/usr/bin/env python3
"""Freeze, run and report bounded single-seat version comparisons."""
import argparse
import csv
import fcntl
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / 'eval/fixtures/cost-v1'
RATE = REPO / 'eval/rates/codex-standard-2026-09-30.json'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=True).encode() + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    temporary.replace(path)


def tree_identity(root):
    entries = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if '.git' in relative.parts or '__pycache__' in relative.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError('source symlink: ' + str(relative))
        if path.is_file():
            entries.append([relative.as_posix(), stat.S_IMODE(path.stat().st_mode),
                            hashlib.sha256(path.read_bytes()).hexdigest()])
    return hashlib.sha256(encoded(entries)).hexdigest()


def snapshot_tree(source, destination):
    before = tree_identity(source)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
    if before != tree_identity(source) or before != tree_identity(destination):
        raise ValueError('source changed during freeze')
    return before


def make_worktree_writable(root):
    """Permit fixture setup in a private copy without changing frozen sources."""
    for path in [root, *root.rglob('*')]:
        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)


class Budget:
    def __init__(self, path, identity, maximum):
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
            raise ValueError('invalid call budget')
        self.path, self.identity, self.maximum = path, identity, maximum
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock():
            self.read()

    def lock(self):
        stream = self.path.with_suffix('.lock').open('a+')
        fcntl.flock(stream, fcntl.LOCK_EX)
        return stream

    def read(self):
        if not self.path.exists():
            return {'identity': self.identity, 'maximum': self.maximum, 'attempts': []}
        value = json.loads(self.path.read_text())
        if value.get('identity') != self.identity or value.get('maximum') != self.maximum:
            raise ValueError('changed benchmark identity or call budget')
        attempts = value.get('attempts')
        if not isinstance(attempts, list) or len(attempts) > self.maximum:
            raise ValueError('invalid call budget ledger')
        ids = [row.get('run_id') for row in attempts if isinstance(row, dict)]
        if len(ids) != len(attempts) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('invalid call budget reservations')
        return value

    def reserve(self, run_id):
        with self.lock():
            value = self.read()
            if any(row['run_id'] == run_id for row in value['attempts']):
                return False
            if len(value['attempts']) >= self.maximum:
                raise ValueError('reviewer execution budget exhausted')
            value['attempts'].append({'run_id': run_id, 'status': 'reserved',
                                      'reserved_at': time.time()})
            write_json(self.path, value)
        return True

    def complete(self, run_id, result):
        with self.lock():
            value = self.read()
            row = next(row for row in value['attempts'] if row['run_id'] == run_id)
            row.update(status='finished', exit_code=result['exit_code'],
                       timed_out=result['timed_out'])
            write_json(self.path, value)


def run_process(command, cwd, environment, log, timeout):
    start = time.monotonic()
    with log.open('ab') as stream:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            cancel(process)
        except BaseException:
            cancel(process)
            raise
    return {'exit_code': process.returncode, 'timed_out': timed_out,
            'wall_seconds': time.monotonic() - start}


def cancel(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
            break
        except subprocess.TimeoutExpired:
            pass


def schedule(cases, maximum, variants=('baseline', 'candidate')):
    if not variants or len(set(variants)) != len(variants) or set(variants) - {'baseline', 'candidate'}:
        raise ValueError('invalid benchmark variants')
    if len(variants) * len(cases) > maximum:
        raise ValueError('call budget is smaller than the paired schedule')
    return [(case['id'], variant) for index, case in enumerate(cases)
            for variant in (('baseline', 'candidate') if index % 2 == 0
                            else ('candidate', 'baseline')) if variant in variants]


def model_rates(card, model):
    rates = card.get('models', {}).get(model) if 'models' in card else card if card.get('model') == model else None
    if not isinstance(rates, dict):
        raise ValueError('no frozen credit rate for selected model: ' + model)
    for key in ('input_per_million', 'cached_per_million', 'output_per_million'):
        value = rates.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError('invalid frozen credit rate: ' + key)
    return rates


def resolve_profile(plugin, reviewer='codex-luna'):
    path = Path(os.environ.get('REVIEW_COUNCIL_CONFIG', Path.home() / '.config/review-council/config.json'))
    config = json.loads(path.read_text())
    spec = importlib.util.spec_from_file_location('benchmark_roster', plugin / 'scripts/lib/roster.py')
    roster = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(roster)
    effective, error, _ = roster.resolve_codex_config(config)
    if error:
        raise ValueError(error)
    if config.get('codex_models') != ['latest-sol', 'latest-luna'] or effective.get('codex_effort') != 'xhigh':
        raise ValueError('production model selection must be latest Sol/Luna at xhigh')
    if config.get('claude_models') != ['opus', 'sonnet'] or 'grok' not in config.get('exclude', []):
        raise ValueError('production model selection must retain Opus/Sonnet and exclude Grok')
    models = effective['codex_models']
    names = roster.codex_seat_names([(model, None) for model in models])
    rows = [dict(seat=name, adapter='codex', model=model, effort='xhigh', mode='prompt', extra=False)
            for name, model in zip(names, models)]
    selected = next((row for row in rows if row['seat'] == reviewer), None)
    if selected is None:
        raise ValueError('requested reviewer not in resolved roster: ' + reviewer)
    rows.append(dict(seat='opus', adapter='claude', model='opus', effort='max', mode='prompt', extra=False))
    return dict(selected, roster=rows, selectors=config['codex_models'])


def command(argv, cwd=None, environment=None):
    result = subprocess.run(argv, cwd=cwd, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(result.stderr[-2000:] or result.stdout[-2000:] or 'command failed')
    return result.stdout.strip()


def git(root, *args):
    return command(['git', '-C', str(root), *args])


def prepare(out, baseline, candidate, maximum, profile, variants=('baseline', 'candidate'), rate_card=RATE, suite=SUITE):
    if out.exists() and any(out.iterdir()):
        raise ValueError('prepare requires an empty output directory')
    out.mkdir(parents=True, exist_ok=True)
    frozen = out / 'sources'
    frozen.mkdir()
    commit = git(candidate, 'rev-parse', baseline + '^{commit}')
    archive = subprocess.check_output(['git', '-c', 'tar.umask=0022', '-C', str(candidate), 'archive', commit,
                                      'plugins/review-council'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for entry in bundle.getmembers():
            if entry.issym() or entry.islnk() or Path(entry.name).is_absolute() or '..' in Path(entry.name).parts:
                raise ValueError('unsafe baseline archive member')
        bundle.extractall(frozen / 'baseline')
    baseline_plugin = frozen / 'baseline/plugins/review-council'
    candidate_plugin = frozen / 'candidate/plugins/review-council'
    candidate_plugin.parent.mkdir(parents=True)
    sources = {'baseline': tree_identity(baseline_plugin),
               'candidate': snapshot_tree(candidate / 'plugins/review-council', candidate_plugin)}
    snapshot_tree(suite, out / 'cases')
    model_rates(json.loads(rate_card.read_text()), profile['model'])
    shutil.copy2(rate_card, out / 'rate-card.json')
    cases = [json.loads(path.read_text()) for path in sorted((out / 'cases').glob('*/case.json'))]
    planned = schedule(cases, maximum, variants)
    version = command(['codex', '--version'])
    identity = {'sources': sources, 'cases': tree_identity(out / 'cases'),
                'baseline_commit': commit, 'model': profile['model'], 'effort': profile['effort'],
                'profile': profile,
                'codex_version': version, 'rate_card': hashlib.sha256(rate_card.read_bytes()).hexdigest(),
                'collector': hashlib.sha256((candidate / 'plugins/review-council/scripts/lib/usage.py').read_bytes()).hexdigest(),
                'engine': engine_identity(), 'python_version': platform.python_version(),
                'platform': platform.platform()}
    identity['subjects'] = {}
    for case in cases:
        root = out / 'work' / case['id'] / 'root'
        root.parent.mkdir(parents=True)
        snapshot_tree(out / 'cases' / case['id'] / 'before', root)
        make_worktree_writable(root)
        git(root, 'init', '-q', '-b', 'main')
        git(root, 'add', '.')
        git(root, '-c', 'commit.gpgsign=false', '-c', 'user.name=Fixture',
            '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Baseline fixture')
        git(root, 'checkout', '-qb', 'change')
        for path in (out / 'cases' / case['id'] / 'after').rglob('*'):
            if path.is_file():
                target = root / path.relative_to(out / 'cases' / case['id'] / 'after')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        identity['subjects'][case['id']] = {'base': git(root, 'rev-parse', 'main'),
                                           'source': tree_identity(root)}
    engine = out / 'engine'
    (engine / 'eval').mkdir(parents=True)
    for name in identity['engine']:
        shutil.copy2(REPO / 'eval' / name, engine / 'eval' / name)
    helper = engine / 'plugins/review-council/scripts/lib/usage.py'
    helper.parent.mkdir(parents=True)
    shutil.copy2(candidate_plugin / 'scripts/lib/usage.py', helper)
    write_json(out / 'manifest.json', {'format_version': 1, 'identity': identity,
                                      'maximum': maximum, 'schedule': planned,
                                      'created_at': time.time()})
    return load_manifest(out)


def engine_identity():
    return {name: hashlib.sha256((REPO / 'eval' / name).read_bytes()).hexdigest()
            for name in ('cost_bench.py', 'bench_local.py', 'bench_metrics.py', 'bench_score.py',
                         'bench_quality.py')}


def load_manifest(out):
    manifest = json.loads((out / 'manifest.json').read_text())
    identity = manifest['identity']
    for variant, digest in identity['sources'].items():
        if tree_identity(out / 'sources' / variant / 'plugins/review-council') != digest:
            raise ValueError('frozen source identity changed')
    if tree_identity(out / 'cases') != identity['cases']:
        raise ValueError('frozen truth identity changed')
    if hashlib.sha256((out / 'rate-card.json').read_bytes()).hexdigest() != identity['rate_card']:
        raise ValueError('frozen rate card changed')
    if identity.get('engine') != engine_identity():
        raise ValueError('benchmark engine changed; use a new output directory')
    for case_id, subject in identity.get('subjects', {}).items():
        root = out / 'work' / case_id / 'root'
        if tree_identity(root) != subject['source'] or git(root, 'rev-parse', 'main') != subject['base']:
            raise ValueError('reviewed fixture changed: ' + case_id)
    return manifest


def environment():
    values = dict(os.environ, REV_PATCH_CHUNKS='0', REV_SOURCE_CONTEXT='1')
    for key in ('REV_ACTIVE', 'REV_RG', 'REV_DEPS_DIR', 'REV_EVIDENCE_MANIFEST',
                'REV_CODEX_SOURCE_BATCH'):
        values.pop(key, None)
    return values


def render(out, case, variant, session, profile=None):
    start = time.monotonic()
    plugin = out / 'sources' / variant / 'plugins/review-council'
    scripts = plugin / 'scripts'
    root = out / 'work' / case['id'] / 'root'
    session.mkdir(parents=True, exist_ok=True)
    scope = {'REV_BASE': git(root, 'rev-parse', 'main'), 'REV_BRANCH': 'change',
             'REV_DEFAULT': 'main', 'REV_ROOT': str(root), 'REV_SCOPE': 'branch'}
    (session / 'scope.env').write_text(''.join(k + '=' + shlex.quote(v) + '\n' for k, v in scope.items()))
    (session / 'files.txt').write_text('\n'.join(case['files']) + '\n')
    (session / 'untracked.txt').write_text('')
    profile = profile or json.loads((out / 'manifest.json').read_text())['identity']['profile']
    seat = profile['seat']
    role = case.get('reviewer_role', 'cumulative')
    if role not in ('cumulative', 'specialist') or (role == 'specialist' and case['mode'] != 'evidence'):
        raise ValueError('invalid benchmark reviewer role')
    other = next(row['seat'] for row in profile['roster'] if row['adapter'] == 'codex' and row['seat'] != seat)
    full = other if role == 'specialist' else seat
    specialist = seat if role == 'specialist' else other
    rows = sorted(profile['roster'], key=lambda row: row['seat'] != full)
    write_json(session / 'roster.json', {'seats': rows})
    if case.get('decision_context'):
        shutil.copy2(out / 'cases' / case['id'] / 'context.md', session / 'context.md')
    lens = case['lens'] if case['mode'] == 'legacy' else (
        'security-state-api' if role == 'specialist' else
        'correctness-boundaries+tests-observability-maintenance-regression')
    args = [str(scripts / 'rev-prompt.sh'), str(session), '1', seat, lens,
            'Review the behavior change and substantiate actionable correctness findings.']
    if case['mode'] == 'evidence':
        manifest = command([sys.executable, str(scripts / 'rev-evidence.py'), 'prepare',
                            str(session), '1', '--phase', 'risk', '--assignment',
                            full + '=correctness-boundaries+tests-observability-maintenance-regression', '--assignment',
                            specialist + '=security-state-api', '--assignment',
                            'opus=concurrency-resources-performance'], environment=environment())
        if case.get('decision_context'):
            routes = json.loads((out / 'cases' / case['id'] / 'context.routes.json').read_text())
            routes.update(context_sha256=hashlib.sha256((session / 'context.md').read_bytes()).hexdigest(),
                          snapshot_tree=json.loads(Path(manifest).read_text())['snapshot_tree'])
            write_json(session / 'context.routes.json', routes)
        args += ['--evidence', manifest]
    prompt = Path(command(args, environment=environment()).splitlines()[-1])
    return prompt, time.monotonic() - start


def local(out, repetitions):
    from bench_local import accounting_case, context_case, preflight_case
    manifest = load_manifest(out)
    rows = []
    for case, variant in manifest['schedule']:
        data = json.loads((out / 'cases' / case / 'case.json').read_text())
        for index in range(repetitions + 1):
            session = out / 'local' / case / variant / str(index)
            prompt, elapsed = render(out, data, variant, session)
            rows.append({'case': case, 'variant': variant, 'warmup': index == 0,
                         'compile_seconds': elapsed, 'prompt_words': len(prompt.read_text().split()),
                         'prompt_bytes': prompt.stat().st_size})
    oracles = [json.loads(command([sys.executable, str(path), '--json']))
               for path in sorted((out / 'cases').glob('*/oracle.py'))]
    mechanics = {}
    for variant in ('baseline', 'candidate'):
        plugin = out / 'sources' / variant / 'plugins/review-council'
        destination = out / 'local/mechanics' / variant
        mechanics[variant] = {'preflight': preflight_case(plugin, destination / 'preflight'),
                              'accounting': accounting_case(plugin, destination / 'accounting'),
                              'context': context_case(plugin, destination / 'context')}
    summaries = []
    for case_id, variant in manifest['schedule']:
        sample = [row for row in rows if row['case'] == case_id and row['variant'] == variant and not row['warmup']]
        summaries.append({'case': case_id, 'variant': variant, 'samples': len(sample),
                          'median_compile_seconds': statistics.median(row['compile_seconds'] for row in sample),
                          'min_compile_seconds': min(row['compile_seconds'] for row in sample),
                          'max_compile_seconds': max(row['compile_seconds'] for row in sample),
                          'prompt_words': sample[0]['prompt_words'], 'prompt_bytes': sample[0]['prompt_bytes']})
    candidate = mechanics['candidate']
    result = {'repetitions': repetitions, 'warmup_per_variant': 1, 'renders': rows,
              'compile_summaries': summaries, 'mechanics': mechanics,
              'oracles': oracles, 'passed': all(row['passed'] for row in oracles),
              'provider_executions': 0}
    result['passed'] &= candidate['accounting']['matches_truth'] and candidate['preflight']['roster_probes'] == 0
    write_json(out / 'local.json', result)
    return result


def check_selection(out, profile):
    current = resolve_profile(out / 'sources/candidate/plugins/review-council', profile['seat'])
    if current != profile:
        raise ValueError('production model selection changed since freeze')


def live(out, timeout):
    from bench_metrics import credit_estimate, measure_stream
    from bench_score import score_findings
    manifest = load_manifest(out)
    if not (out / 'local.json').exists() or not json.loads((out / 'local.json').read_text())['passed']:
        raise ValueError('run the passing local lane before live executions')
    profile = manifest['identity']['profile']
    check_selection(out, profile)
    if command(['codex', '--version']) != manifest['identity']['codex_version']:
        raise ValueError('CLI version changed since freeze')
    budget = Budget(out / 'budget.json', manifest['identity'], manifest['maximum'])
    rate = model_rates(json.loads((out / 'rate-card.json').read_text()), profile['model'])
    for case_id, variant in manifest['schedule']:
        run_id = case_id + '/' + variant
        if any(row['run_id'] == run_id for row in budget.read()['attempts']):
            continue
        case = json.loads((out / 'cases' / case_id / 'case.json').read_text())
        session = out / 'runs' / case_id / variant
        prompt, render_seconds = render(out, case, variant, session)
        plugin = out / 'sources' / variant / 'plugins/review-council'
        root = out / 'work' / case_id / 'root'
        stem = 'r1-' + profile['seat']
        raw, findings = session / (stem + '.stream.ndjson'), session / (stem + '.json')
        values = environment()
        values.update(SEAT=profile['seat'], MODEL=profile['model'], EFFORT=profile['effort'], MODE='prompt', ROOT=str(root),
                      PROMPT=str(prompt), SCHEMA=str(plugin / 'schema/findings.schema.json'),
                      OUT=str(findings), LOG=str(session / (stem + '.log')), RAW=str(raw),
                      BASE=git(root, 'rev-parse', 'main'))
        if not budget.reserve(run_id):
            continue
        print('launch ' + run_id + ' ' + profile['model'] + '/' + profile['effort'], flush=True)
        run = run_process(['bash', str(plugin / 'scripts/seats.d/codex.sh')], root,
                          values, session / 'adapter.log', timeout)
        budget.complete(run_id, run)
        usage = measure_stream(raw, out / 'sources/candidate/plugins/review-council/scripts/lib/usage.py')
        row = dict(run, case=case_id, variant=variant, status='provider-failed', valid=False,
                   compile_seconds=render_seconds, prompt_words=len(prompt.read_text().split()),
                   prompt_bytes=prompt.stat().st_size, **usage)
        row['estimated_credits'] = credit_estimate(row['usage'], rate)
        row.update(validation_seconds=0, audit_seconds=0)
        if run['exit_code'] == 0 and findings.exists():
            checked = run_process([sys.executable, str(plugin / 'scripts/lib/validate-findings.py'),
                                   str(findings)], root, values, session / 'validation.log', 30)
            row['schema_valid'] = checked['exit_code'] == 0
            row['validation_seconds'] = checked['wall_seconds']
            if row['schema_valid']:
                result = json.loads(findings.read_text())
                row['incomplete_proof'] = result['summary'].startswith('INCOMPLETE PROOF')
                row['quality'] = score_findings(case, result)
                audit = run_process([sys.executable, str(plugin / 'scripts/lib/review-read-audit.py'),
                    'audit', '--adapter', 'codex', '--raw', str(raw), '--prompt', str(prompt),
                    '--root', str(root), '--session', str(session), '--result', str(findings),
                    '--out', str(session / (stem + '.audit.json'))], root, values, session / 'audit.log', 60)
                row['audit_valid'] = audit['exit_code'] == 0
                row['audit_seconds'] = audit['wall_seconds']
                row['valid'] = row['audit_valid'] and not row['incomplete_proof'] and not row['errors']
                row['status'] = 'complete' if row['valid'] else 'invalid-proof'
            else:
                row['status'] = 'invalid-schema'
        row['artifacts'] = {'prompt': str(prompt.relative_to(out)), 'raw': str(raw.relative_to(out)),
                            'findings': str(findings.relative_to(out))}
        row['machine_seconds'] = sum(row[key] for key in (
            'compile_seconds', 'wall_seconds', 'validation_seconds', 'audit_seconds'))
        write_json(session / 'measurement.json', row)
        print(run_id + ': ' + row['status'] + ', %.2f s' % row['wall_seconds'], flush=True)
        report(out)
        if run['exit_code'] != 0:
            break


def check_reference(before, after, variant='candidate'):
    if variant not in ('baseline', 'candidate'):
        raise ValueError('invalid reference variant')
    first, second = before['identity'], after['identity']
    for key in ('model', 'effort', 'profile', 'cases', 'codex_version', 'rate_card', 'collector', 'engine'):
        if first.get(key) != second.get(key):
            raise ValueError('reference differs in ' + key)
    if first['sources'][variant] != second['sources']['baseline']:
        raise ValueError('reference source differs from baseline')


def verified_quality_provenance(out, manifest, row, result, case, audit):
    from bench_quality import canonical_sha256
    if not row.get('valid') or not audit or audit.get('status') != 'valid' or audit.get('violations'):
        return None
    paths = {key: out / value for key, value in row['artifacts'].items()}
    for key, field in (('prompt', 'prompt_sha256'), ('raw', 'stream_sha256'),
                       ('findings', 'result_sha256')):
        if hashlib.sha256(paths[key].read_bytes()).hexdigest() != audit.get(field):
            raise ValueError('quality audit artifact binding changed: ' + key)
    if json.loads(paths['findings'].read_text()) != result:
        raise ValueError('quality result differs from the bound artifact')
    evidence_path = paths['prompt'].parent / 'r1-evidence.manifest.json'
    if not evidence_path.exists():
        return None
    evidence = json.loads(evidence_path.read_text())
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    if audit.get('evidence_manifest_sha256') != digest:
        raise ValueError('quality evidence manifest binding changed')
    plugin = out / 'sources' / row['variant'] / 'plugins/review-council'
    root = out / 'work' / row['case'] / 'root'
    with tempfile.TemporaryDirectory(prefix='review-quality-proof-') as temporary:
        replay_path = Path(temporary) / 'audit.json'
        command([sys.executable, str(plugin / 'scripts/lib/review-read-audit.py'),
                 'audit', '--adapter', 'codex', '--raw', str(paths['raw']),
                 '--prompt', str(paths['prompt']), '--root', str(root),
                 '--session', str(paths['prompt'].parent), '--result', str(paths['findings']),
                 '--out', str(replay_path)], cwd=root, environment=environment())
        if json.loads(replay_path.read_text()) != audit:
            raise ValueError('quality audit differs from replayed tool evidence')
    packet_keys = {(r['path'], r['line_start'], r['line_end'])
                   for r in audit.get('source_ranges', []) if r.get('origin') == 'packet'}
    seat = manifest['identity']['profile']['seat']
    packet = evidence.get('source_context', {}).get('seats', {}).get(seat, {})
    snapshot_ranges = [dict(path=r['path'], line_start=r['line_start'], line_end=r['line_end'],
                            blob_tree=r['blob_tree'])
                       for shard in packet.get('shards', []) for r in shard['ranges']
                       if r['blob_tree'] == evidence['snapshot_tree']
                       and (r['path'], r['line_start'], r['line_end']) in packet_keys]
    return {'case_sha256': canonical_sha256(case),
            'findings_sha256': canonical_sha256(result),
            'audit_sha256': canonical_sha256(audit),
            'evidence_manifest_sha256': digest, 'snapshot_tree': evidence['snapshot_tree'],
            'snapshot_packet_ranges': snapshot_ranges}


def report(out, reference=None, reference_variant='candidate'):
    from bench_metrics import paired_deltas
    from bench_score import score_findings
    from bench_quality import score_run, compare_quality
    manifest = load_manifest(out)
    rows = []
    for path in sorted((out / 'runs').glob('*/*/measurement.json')):
        row = json.loads(path.read_text())
        adjudication = path.parent / 'adjudication.json'
        if adjudication.exists() and row.get('schema_valid'):
            case = json.loads((out / 'cases' / row['case'] / 'case.json').read_text())
            result = json.loads((path.parent / ('r1-' + manifest['identity']['profile']['seat'] + '.json')).read_text())
            dispositions = json.loads(adjudication.read_text())
            row['quality'] = score_findings(case, result, dispositions)
            behavior_path = path.parent / 'behavior-adjudication.json'
            audit_path = path.parent / ('r1-' + manifest['identity']['profile']['seat'] + '.audit.json')
            behavior = json.loads(behavior_path.read_text()) if behavior_path.exists() else None
            audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
            provenance = (verified_quality_provenance(out, manifest, row, result, case, audit)
                          if behavior is not None and case.get('behavior_rubric') else None)
            row['run_quality'] = score_run(case, result, dispositions, audit, behavior,
                                           verified_provenance=provenance)
        rows.append(row)
    ledger = out / 'budget.json'
    attempts = json.loads(ledger.read_text())['attempts'] if ledger.exists() else []
    local_path = out / 'local.json'
    paired_rows = rows
    reference_identity = None
    if reference is not None:
        original = report(reference)
        check_reference(original['manifest'], manifest, reference_variant)
        originals = [dict(row, variant='baseline') for row in original['rows']
                     if row['variant'] == reference_variant]
        if any(row['variant'] != 'candidate' for row in rows):
            raise ValueError('reference comparison requires a candidate-only stage')
        paired_rows = originals + rows
        reference_identity = {'path': str(reference), 'variant': reference_variant,
            'manifest_sha256': hashlib.sha256((reference / 'manifest.json').read_bytes()).hexdigest()}
    case_count = len({case for case, _ in manifest['schedule']})
    case_limit = (str(case_count) + (' case provides' if case_count == 1 else ' cases provide')
                  + ' no statistical quality equivalence.')
    result = {'manifest': manifest, 'rows': rows, 'pairs': paired_deltas(paired_rows),
              'reference': reference_identity,
              'local': json.loads(local_path.read_text()) if local_path.exists() else None,
              'reserved_executions': len(attempts), 'maximum_executions': manifest['maximum'],
              'unmeasured_reservations': [x['run_id'] for x in attempts
                  if x['run_id'] not in {r['case'] + '/' + r['variant'] for r in rows}],
              'limits': [case_limit,
                         'Server cache cannot be cleared; single stages have temporal ordering bias.',
                         'No full panel certification or subscription cost claim.',
                         'One reviewer execution may include multiple provider HTTP requests.']}
    result['quality_comparisons'] = []
    for case_id in sorted({row['case'] for row in paired_rows}):
        pair = {row['variant']: row for row in paired_rows if row['case'] == case_id}
        if set(pair) == {'baseline', 'candidate'}:
            result['quality_comparisons'].append(dict(case=case_id,
                **compare_quality(pair['baseline'], pair['candidate'])))
    write_json(out / 'report.json', result)
    fields = ['case', 'variant', 'status', 'valid', 'wall_seconds', 'prompt_words', 'prompt_bytes',
              'tool_calls', 'estimated_credits', 'input_tokens', 'cached_input_tokens',
              'uncached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'cost_usd',
              'quality_score', 'core_score', 'weighted_recall']
    with (out / 'report.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for row in rows:
            values = dict(row, **(row.get('usage') or {}))
            values.update({key: (row.get('run_quality') or {}).get(key)
                           for key in ('quality_score', 'core_score', 'weighted_recall')})
            writer.writerow({key: values.get(key) for key in fields})
    text = ['# Review cost benchmark', '', 'Baseline: `' + manifest['identity']['baseline_commit'] + '`.',
            'Model: `' + manifest['identity']['model'] + '`, effort `' + manifest['identity']['effort'] + '`.', '',
            '| Case | Version | Status | Seconds | Estimated credits | Recall | FP | Quality /100 | Core /80 |',
            '| --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: |']
    for row in rows:
        usage, quality = row.get('usage') or {}, row.get('quality') or {}
        run_quality = row.get('run_quality') or {}
        text.append('| %s | %s | %s | %.2f | %s | %s | %s | %s | %s |' % (
            row['case'], row['variant'], row['status'], row['wall_seconds'],
            row.get('estimated_credits'), quality.get('recall'), quality.get('false_positives'),
            run_quality.get('quality_score'), run_quality.get('core_score')))
    text += ['', 'Dollars are unknown unless reported. Credits are a dated Standard estimate.', '']
    if result['quality_comparisons']:
        text += ['## Quality gates', '',
                 'A missing score is unknown. Observable source coverage is a proxy for inspection,',
                 'not a measurement of hidden reasoning. Components and policy hashes are in JSON.', '']
        for comparison in result['quality_comparisons']:
            text.append('- %s: acceptable %s, quality delta %s; %s.' % (
                comparison['case'], comparison['acceptable'], comparison['quality_delta'],
                '; '.join(comparison['reasons']) or 'all frozen quality gates pass'))
        text += ['']
    if result['local']:
        text += ['## Local lane', '', '| Case | Version | Prompt words | Median compile seconds |',
                 '| --- | --- | ---: | ---: |']
        for row in result['local']['compile_summaries']:
            text.append('| %s | %s | %d | %.3f |' % (row['case'], row['variant'], row['prompt_words'], row['median_compile_seconds']))
        text += ['', 'Contract refusal and accounting replay:', '']
        for variant, mechanics in result['local']['mechanics'].items():
            text.append('- %s: %d roster probes, accounting truth %s (%d input, %d output).' % (
                variant, mechanics['preflight']['roster_probes'], mechanics['accounting']['matches_truth'],
                mechanics['accounting']['input_tokens'], mechanics['accounting']['output_tokens']))
        text += ['']
    text += ['- ' + item for item in result['limits']]
    (out / 'report.md').write_text('\n'.join(text) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'local', 'live', 'report'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', default='4151007')
    parser.add_argument('--candidate', type=Path, default=REPO)
    parser.add_argument('--max-calls', type=int, default=4)
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--reviewer', default='codex-luna')
    parser.add_argument('--variants', choices=('both', 'candidate'), default='both')
    parser.add_argument('--rate-card', type=Path, default=RATE)
    parser.add_argument('--suite', type=Path, default=SUITE)
    parser.add_argument('--reference-variant', choices=('baseline', 'candidate'), default='candidate')
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    if args.repetitions < 1 or args.timeout <= 0:
        parser.error('repetitions and timeout must be positive')
    try:
        if args.command == 'prepare':
            profile = resolve_profile(args.candidate.resolve() / 'plugins/review-council', args.reviewer)
            variants = ('baseline', 'candidate') if args.variants == 'both' else ('candidate',)
            prepare(out, args.baseline, args.candidate.resolve(), args.max_calls, profile, variants, args.rate_card, args.suite.resolve())
        elif args.command == 'local':
            result = local(out, args.repetitions)
            if not result['passed']:
                raise ValueError('fixture oracle failed')
        elif args.command == 'live':
            with (out / 'live.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                live(out, args.timeout)
        result = report(out, args.reference.expanduser().resolve() if args.reference else None,
                        args.reference_variant)
        print(str(out / 'report.md') + ' (%d/%d reserved)' % (
            result['reserved_executions'], result['maximum_executions']))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('benchmark: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
