"""Codex prepared-evidence stage repair: the adapter's stage decisions replay the read audit."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / 'plugins/review-council/scripts'
HELPER = SCRIPTS / 'lib/codex-proof-stages.py'
AUDIT = SCRIPTS / 'lib/review-read-audit.py'
SEAT = 'codex-luna'
MODEL = 'gpt-6-luna'


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_session(base, functions=6):
    """A real prepared session: about 20 KiB patch chunks, packets and 8 KiB source segments."""
    root, session = base / 'repo', base / 'session'
    (root / 'src').mkdir(parents=True)
    session.mkdir()
    config = base / 'gitconfig'
    config.write_text('[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n'
                      '[init]\n\tdefaultBranch = main\n')
    env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1')
    env.pop('REV_DEPS_DIR', None)

    def git(*args):
        subprocess.run(['git', '-C', str(root), *args], check=True, env=env,
                       capture_output=True)

    git('init', '-q')
    sources = []
    for index in range(functions):
        sources.append(f'def fn{index:02d}(value=None):\n    return "{"x" * 10000}"\n')
        (root / 'src' / f'use{index:02d}.py').write_text(
            f'from src.lib import fn{index:02d}\n\ndef use{index:02d}():\n'
            f'    return fn{index:02d}("{"y" * 8000}")\n')
    (root / 'src/lib.py').write_text('\n'.join(sources))
    git('add', '.')
    git('commit', '-qm', 'base')
    base_sha = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], check=True,
                              env=env, capture_output=True, text=True).stdout.strip()
    lib = root / 'src/lib.py'
    lib.write_text(lib.read_text().replace('return "x', 'return "y', functions))
    (session / 'scope.env').write_text(
        f"REV_BASE='{base_sha}'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\n"
        f"REV_ROOT='{root}'\nREV_SCOPE='branch'\n")
    (session / 'files.txt').write_text('src/lib.py\n')
    (session / 'untracked.txt').write_text('')
    seats = [{'seat': name, 'adapter': 'codex', 'model': MODEL, 'effort': 'xhigh'}
             for name in ('codex-luna', 'codex-luna-2', 'codex-luna-3', 'codex-luna-4')]
    (session / 'roster.json').write_text(json.dumps({'seats': seats}) + '\n')
    prepared = subprocess.run(
        [sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare', str(session), '1',
         '--phase', 'discovery'], env=dict(env, REV_PATCH_CHUNKS='1', REV_SOURCE_CONTEXT='1'),
        capture_output=True, text=True)
    if prepared.returncode:
        raise AssertionError(prepared.stderr)
    manifest = Path(prepared.stdout.strip())
    bundle = json.loads(manifest.read_text())['assignments'][SEAT]['bundle']
    rendered = subprocess.run(
        [str(SCRIPTS / 'rev-prompt.sh'), str(session), '1', SEAT, bundle, 'stage-repair',
         '--evidence', str(manifest)], env=env, capture_output=True, text=True)
    if rendered.returncode:
        raise AssertionError(rendered.stderr)
    return root.resolve(), session.resolve(), Path(rendered.stdout.strip()).resolve()


PLAN = """## C-01 - keep service results stable
Findings: F-001 (P1)
Rule: Apply the helper result exactly once at every service entry.
Sites: src/service.ts:1-2 (found by: rg --hidden --no-ignore --glob '!.git/**' --null -n -- 'run(Service|Alias)' .)
Excluded: src/sibling.ts - runAlias applies no helper result, so the rule cannot reach it
Must not: Change unrelated exports.
Test: tests/service.test.ts:1-2
Interacts with: none.
Prediction: reverting the guard fails tests/service.test.ts at "service" (assert on runService()), because the doubled helper result changes the return value.
## C-02 - keep helper callers visible
Findings: F-002 (P1)
Rule: Check every helper caller before changing the helper result.
Sites: src/helper.ts:1 (found by: grep --exclude-dir=.git --null -r -n -- 'helper' .)
Excluded: src/service.ts - the service entry caller is owned by C-01
Must not: Skip callers outside the service entry.
Test: tests/service.test.ts:1-2
Interacts with: C-01.
Prediction: reverting the guard fails tests/service.test.ts at "service" (assert on runService()), because an unchecked caller re-applies the changed helper result.
"""
PLAN_LENSES = {'sol': 'plan-completeness', 'terra': 'plan-soundness', 'opus': 'plan-simplicity',
               'sonnet': 'plan-tests'}


def build_plan_session(base):
    """The t-plan-evidence fix-plan panel, its Codex seats carrying a model: sol reads two patch
    chunks and terra one patch window, then the index. Without source packets, as in the real
    plan seats, every cluster source is read in a review turn after all stages."""
    root, session = base / 'repo', base / 'session'
    (root / 'src').mkdir(parents=True)
    (root / 'tests').mkdir()
    session.mkdir()
    config = base / 'gitconfig'
    config.write_text('[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n'
                      '[init]\n\tdefaultBranch = main\n')
    env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1')
    env.pop('REV_DEPS_DIR', None)

    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True, env=env,
                              capture_output=True, text=True).stdout

    git('init', '-q')
    (root / 'src/helper.ts').write_text('export function helper() { return 1; }\n')
    (root / 'src/service.ts').write_text(
        'import { helper } from "./helper";\nexport function runService() { return helper(); }\n')
    (root / 'src/sibling.ts').write_text('export function runAlias() { return 1; }\n')
    (root / 'tests/service.test.ts').write_text(
        'import { runService } from "../src/service";\ntest("service", () => runService());\n')
    (root / 'src/unrelated.ts').write_text(
        ''.join(f'export const unrelated{index} = {index};\n' for index in range(600)))
    git('add', '.')
    git('commit', '-qm', 'plan base')
    base_sha = git('rev-parse', 'HEAD').strip()
    for relative, old, new in (('src/helper.ts', 'return 1', 'return 2'),
                               ('src/service.ts', 'helper();', 'helper() + 1;'),
                               ('tests/service.test.ts', 'runService());', 'runService() + 1);'),
                               ('src/unrelated.ts', ' = ', ' = 1000 + ')):
        path = root / relative
        path.write_text(path.read_text().replace(old, new))
    (session / 'scope.env').write_text(
        f"REV_BASE='{base_sha}'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\n"
        f"REV_ROOT='{root}'\nREV_SCOPE='branch'\n")
    (session / 'files.txt').write_text(
        'src/helper.ts\nsrc/service.ts\nsrc/unrelated.ts\ntests/service.test.ts\n')
    (session / 'untracked.txt').write_text('')
    seats = [{'seat': name, 'adapter': 'codex', 'model': MODEL, 'effort': 'xhigh'}
             for name in ('sol', 'terra')] + [{'seat': name, 'adapter': 'claude'}
                                              for name in ('opus', 'sonnet')]
    (session / 'roster.json').write_text(json.dumps({'seats': seats}) + '\n')
    plan = session / 'fix-plan.md'
    plan.write_text(PLAN)
    assignments = [item for seat, lens in PLAN_LENSES.items()
                   for item in ('--assignment', f'{seat}={lens}')]
    prepared = subprocess.run(
        [sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare', str(session), '1p',
         '--phase', 'plan', '--plan', str(plan), '--plan-sha256',
         hashlib.sha256(plan.read_bytes()).hexdigest(), '--full-seat', 'sol', *assignments],
        env=dict(env, REV_PATCH_CHUNKS='auto', REV_SOURCE_CONTEXT='0'),
        capture_output=True, text=True)
    if prepared.returncode:
        raise AssertionError(prepared.stderr)
    manifest = prepared.stdout.strip()
    prompts = {}
    for seat in ('sol', 'terra'):
        rendered = subprocess.run(
            [str(SCRIPTS / 'rev-prompt.sh'), str(session), '1p', seat, PLAN_LENSES[seat], 'plan',
             '--plan', str(session / 'r1p-plan.md'), '--evidence', manifest],
            env=env, capture_output=True, text=True)
        if rendered.returncode:
            raise AssertionError(rendered.stderr)
        prompts[seat] = Path(rendered.stdout.strip()).resolve()
    return root.resolve(), session.resolve(), prompts


class Seat:
    """A scripted Codex seat that follows each stage prompt unless told to slip."""

    def __init__(self, root, session, prompt, stage_dir, name=SEAT):
        self.root, self.session, self.prompt, self.stage_dir = root, session, prompt, stage_dir
        self.name = name
        self.label = prompt.name[:-len(f'-{name}.prompt.md')]
        self.raw = session / f'{self.label}-{name}.stream.ndjson'
        self.turn = stage_dir / 'current-turn.ndjson'
        self.turns = 0
        self.ids = 0
        self.raw.write_text('')

    def step(self):
        proc = subprocess.run(
            [sys.executable, str(HELPER), '--stage-step', str(self.stage_dir),
             '--raw', str(self.raw), '--turn', str(self.turn), '--prompt', str(self.prompt),
             '--seat', self.name, '--root', str(self.root), '--session', str(self.session)],
            capture_output=True, text=True)
        if proc.returncode:
            raise AssertionError('stage step failed: ' + proc.stdout + proc.stderr)
        return proc.stdout.rstrip('\n').split('\t')

    def call(self, command):
        self.ids += 1
        words = shlex.split(command)
        if words[0] == 'cat':
            output = Path(words[-1]).read_text()
        else:
            output = subprocess.run(['bash', '-c', command], cwd=self.root,
                                    capture_output=True, text=True).stdout
        wrapped = '/bin/zsh -lc ' + shlex.quote(command)
        item = {'id': f'item_{self.ids}', 'type': 'command_execution', 'command': wrapped}
        return [{'type': 'item.started', 'item': dict(item, aggregated_output='',
                                                       exit_code=None)},
                {'type': 'item.completed', 'item': dict(item, aggregated_output=output,
                                                         exit_code=0)}]

    def run(self, commands, answer='READ_STAGE_COMPLETE'):
        self.turns += 1
        events = [{'type': 'thread.started', 'thread_id': 'thread-1'}] if self.turns == 1 else []
        events.append({'type': 'turn.started'})
        for command in commands:
            events.extend(self.call(command))
        events.append({'type': 'item.completed', 'item': {
            'id': f'answer_{self.turns}', 'type': 'agent_message', 'text': answer}})
        events.append({'type': 'turn.completed', 'usage': {}})
        text = ''.join(json.dumps(event) + '\n' for event in events)
        self.turn.write_text(text)
        with self.raw.open('a') as stream:
            stream.write(text)


def reads(prompt_path):
    return [line[len('Read exactly: '):] for line in Path(prompt_path).read_text().splitlines()
            if line.startswith('Read exactly: ')]


def name(command):
    return Path(shlex.split(command)[-1]).name


def paired_segments(plan):
    """Required source segments two per stage, the shape small patch chunks still take, to test
    the repairs a stage with two reads gets."""
    stages = []
    for stage in plan['stages']:
        if (stage['kind'] == 'required source segments' and stages
                and stages[-1]['kind'] == stage['kind'] and len(stages[-1]['reads']) == 1):
            stages[-1] = dict(stages[-1], reads=stages[-1]['reads'] + stage['reads'])
        else:
            stages.append(stage)
    return dict(plan, stages=stages)


class StageRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.fixtures = {}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, functions=6):
        if functions not in self.fixtures:
            self.fixtures[functions] = build_session(self.base / f'f{functions}', functions)
        return self.fixtures[functions]

    def seat(self, functions=6, plan=None):
        root, session, prompt = self.fixture(functions)
        stage_dir = Path(tempfile.mkdtemp(dir=self.base))
        listed = subprocess.run(
            [sys.executable, str(HELPER), '--prompt', str(prompt), '--seat', SEAT,
             '--model', MODEL, '--stage-dir', str(stage_dir)], capture_output=True, text=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        if plan is not None:
            (stage_dir / 'stage-plan.json').write_text(json.dumps(plan(json.loads(
                (stage_dir / 'stage-plan.json').read_text()))))
        return Seat(root, session, prompt, stage_dir)

    def plan_seat(self, name):
        if 'plan' not in self.fixtures:
            self.fixtures['plan'] = build_plan_session(self.base / 'plan')
        root, session, prompts = self.fixtures['plan']
        stage_dir = Path(tempfile.mkdtemp(dir=self.base))
        listed = subprocess.run(
            [sys.executable, str(HELPER), '--prompt', str(prompts[name]), '--seat', name,
             '--model', MODEL, '--stage-dir', str(stage_dir)], capture_output=True, text=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        return Seat(root, session, prompts[name], stage_dir, name)

    def drive(self, seat, slips=None, stage_slips=None, limit=60):
        """Follow every step, running other commands on the turns `slips` names by number, or on
        the first turn of the stages `stage_slips` names."""
        slips, stage_slips = slips or {}, stage_slips or {}
        transcript = []
        for _ in range(limit):
            step = seat.step()
            transcript.append(step)
            if step[0] != 'run':
                return transcript
            listed = reads(step[1])
            header = Path(step[1]).read_text().splitlines()[0]
            slip = slips.get(seat.turns + 1)
            if slip is None and 'repair' not in header:
                slip = stage_slips.get(int(header.split()[4]))
            seat.run(slip(listed) if slip else listed)
        raise AssertionError('stage steps did not finish')

    def plan_reads(self, seat):
        plan = json.loads((seat.stage_dir / 'stage-plan.json').read_text())
        return [[read['command'] for read in stage['reads']] for stage in plan['stages']]

    def finish_and_audit(self, seat):
        """Complete the review as the adapter would and return the post-run audit verdict."""
        targets = [line.split(': ', 1)[1].split(' ', 1)[0]
                   for line in seat.prompt.read_text().splitlines()
                   if line.startswith(('Required post-index original-source target: ',
                                       'Mandatory cluster source window: '))]
        self.assertTrue(targets)
        commands = []
        for location in targets:
            path, lines = location.rsplit(':', 1)
            first, last = lines.split('-')
            commands.append(f'sed -n {first},{last}p {path}')
        seat.run(commands, answer='{"status":"ready","next_step":""}')
        seat.run([], answer='{"summary":"checked","findings":[]}')
        result = seat.session / f'{seat.label}-{seat.name}.json'
        result.write_text('{"summary":"checked","findings":[]}\n')
        out = seat.session / f'{seat.label}-{seat.name}.read-audit.json'
        proc = subprocess.run(
            [sys.executable, str(AUDIT), 'audit', '--adapter', 'codex', '--raw', str(seat.raw),
             '--prompt', str(seat.prompt), '--root', str(seat.root),
             '--session', str(seat.session), '--seat', seat.name, '--out', str(out)],
            capture_output=True, text=True)
        audit = json.loads(out.read_text())
        return (proc.returncode, sorted({row['code'] for row in audit['violations']}),
                sorted({row['code'] for row in audit['advisories']}))

    def first_stage(self, seat, size, kind=None):
        plan = json.loads((seat.stage_dir / 'stage-plan.json').read_text())['stages']
        return next(index for index, stage in enumerate(plan, 1)
                    if len(stage['reads']) == size and (kind is None or stage['kind'] == kind))

    def test_exact_reads_follow_the_plan_without_repairs(self):
        seat = self.seat()
        transcript = self.drive(seat)
        self.assertEqual(transcript[-1], ['done'])
        issued = [reads(step[1]) for step in transcript[:-1]]
        self.assertEqual(issued, self.plan_reads(seat))
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_an_in_order_under_read_gets_a_repair_turn_for_exactly_the_missing_read(self):
        seat = self.seat(plan=paired_segments)
        stage = self.first_stage(seat, 2, 'required source segments')
        planned = self.plan_reads(seat)
        transcript = self.drive(seat, {stage: lambda listed: listed[:1]})
        repair = transcript[stage]
        self.assertEqual(repair[0], 'run')
        self.assertEqual(reads(repair[1]), [planned[stage - 1][1]])
        self.assertIn('repair', Path(repair[1]).read_text().splitlines()[0])
        self.assertEqual(len(repair), 3)
        self.assertIn(name(planned[stage - 1][1]), repair[2])
        self.assertEqual(reads(transcript[stage + 1][1]), planned[stage])
        self.assertEqual(transcript[-1], ['done'])
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_a_stage_with_no_reads_is_repaired_one_read_per_turn(self):
        seat = self.seat(plan=paired_segments)
        stage = self.first_stage(seat, 2, 'required source segments')
        planned = self.plan_reads(seat)
        transcript = self.drive(seat, {stage: lambda listed: []})
        self.assertEqual([reads(step[1]) for step in transcript[stage:stage + 2]],
                         [[planned[stage - 1][0]], [planned[stage - 1][1]]])
        self.assertEqual(transcript[-1], ['done'])
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_duplicates_and_extra_commands_the_audit_accepts_do_not_fail_the_seat(self):
        seat = self.seat()
        index_stage = len(self.plan_reads(seat))
        packet = self.first_stage(seat, 1, 'source context packet')
        transcript = self.drive(seat, stage_slips={
            packet: lambda listed: listed + ["printf '%s\\n' ''"],
            index_stage: lambda listed: listed + listed,
        })
        self.assertEqual(transcript[-1], ['done'])
        self.assertEqual(len(transcript), index_stage + 1)
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_a_repeated_required_source_segment_is_refused_with_the_audit_codes(self):
        seat = self.seat()
        stage = self.first_stage(seat, 1, 'required source segments')
        transcript = self.drive(seat, {stage: lambda listed: listed + listed[-1:]})
        self.assertEqual(transcript[-1][0], 'refuse')
        self.assertEqual(len(transcript), stage + 1)
        self.assertIn('duplicate-required-source-segment', transcript[-1][1])

    def test_a_repeated_source_packet_is_refused_with_the_audit_codes(self):
        seat = self.seat()
        stage = self.first_stage(seat, 1, 'source context packet')
        transcript = self.drive(seat, {stage: lambda listed: listed + listed})
        self.assertEqual(transcript[-1][0], 'refuse')
        self.assertIn('source-packet-batch-too-large', transcript[-1][1])

    def test_a_repeated_pair_over_the_turn_output_limit_is_refused(self):
        def paired(plan):
            stages = plan['stages']
            chunks = [read for stage in stages if stage['kind'] == 'patch chunks'
                      for read in stage['reads']]
            rest = [stage for stage in stages if stage['kind'] != 'patch chunks']
            pairs = [{'kind': 'patch chunks', 'reads': chunks[index:index + 2]}
                     for index in range(0, len(chunks), 2)]
            return dict(plan, stages=pairs + rest)

        seat = self.seat(plan=paired)
        transcript = self.drive(seat, {1: lambda listed: listed + listed[-1:]})
        self.assertEqual(transcript[-1][0], 'refuse')
        self.assertEqual(len(transcript), 2)
        self.assertIn('evidence-proof-batch-too-large', transcript[-1][1])

    def test_patch_chunks_are_staged_alone_when_a_repeated_pair_would_overflow_a_turn(self):
        seat = self.seat()
        plan = json.loads((seat.stage_dir / 'stage-plan.json').read_text())['stages']
        chunks = [stage for stage in plan if stage['kind'] == 'patch chunks']
        self.assertGreater(len(chunks), 2)
        self.assertEqual({len(stage['reads']) for stage in chunks}, {1})

    def test_a_repeated_patch_chunk_is_read_again_and_the_audit_accepts_it(self):
        seat = self.seat()
        transcript = self.drive(seat, stage_slips={1: lambda listed: listed + listed})
        self.assertEqual(transcript[-1], ['done'])
        repair = transcript[1]
        self.assertIn('repair', Path(repair[1]).read_text().splitlines()[0])
        self.assertEqual(reads(repair[1]), self.plan_reads(seat)[0])
        code, violations, advisories = self.finish_and_audit(seat)
        self.assertEqual((code, violations), (0, []))
        self.assertIn('tool-turn-output-too-large', advisories)

    def test_a_patch_chunk_read_ahead_is_kept_and_not_asked_for_again(self):
        seat = self.seat()
        planned = self.plan_reads(seat)
        transcript = self.drive(seat, stage_slips={1: lambda listed: listed + planned[1]})
        self.assertEqual(transcript[-1], ['done'])
        self.assertEqual(len(transcript), len(planned))
        self.assertEqual(reads(transcript[1][1]), planned[2])
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_reads_out_of_order_are_refused(self):
        seat = self.seat()
        stage = self.first_stage(seat, 1, 'required source segments')
        following = self.plan_reads(seat)[stage][0]
        transcript = self.drive(seat, {stage: lambda listed: [following] + listed})
        self.assertEqual(transcript[-1][0], 'refuse')
        self.assertIn('reordered-required-source-segments', transcript[-1][1])

    def test_required_source_segments_are_staged_one_per_turn(self):
        seat = self.seat()
        plan = json.loads((seat.stage_dir / 'stage-plan.json').read_text())['stages']
        segments = [stage for stage in plan if stage['kind'] == 'required source segments']
        self.assertGreaterEqual(len(segments), 3)
        self.assertEqual({len(stage['reads']) for stage in segments}, {1})

    def test_a_required_source_segment_read_ahead_is_kept_and_not_asked_for_again(self):
        seat = self.seat()
        planned = self.plan_reads(seat)
        flat = [read for stage in planned for read in stage]
        stage = next(index for index, listed in enumerate(planned, 1)
                     if 'source-segment' in listed[0])
        ahead = flat[flat.index(planned[stage - 1][-1]) + 1]
        self.assertIn('source-segment', ahead)
        transcript = self.drive(seat, {stage: lambda listed: listed + [ahead]})
        self.assertEqual(transcript[-1], ['done'])
        self.assertEqual(len(transcript), len(planned))
        self.assertNotIn(ahead, [read for step in transcript[stage:-1] for read in reads(step[1])])
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_a_read_ahead_the_audit_credits_is_not_asked_for_again(self):
        seat = self.seat(functions=5)
        planned = self.plan_reads(seat)
        stage = len(planned) - 1
        self.assertEqual(len(planned[stage - 1]), 1)
        transcript = self.drive(seat, {stage: lambda listed: listed + planned[-1]})
        self.assertEqual(transcript[-1], ['done'])
        self.assertEqual(len(transcript), stage + 1)
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_repairs_end_when_a_stage_keeps_slipping(self):
        seat = self.seat(plan=paired_segments)
        stage = self.first_stage(seat, 2, 'required source segments')
        slips = {turn: (lambda listed: []) for turn in range(stage, stage + 10)}
        transcript = self.drive(seat, slips)
        self.assertEqual(transcript[-1][0], 'refuse')
        self.assertEqual(len(transcript), stage + 4)
        self.assertIn('still missing', transcript[-1][1])

    def test_repairs_end_when_an_attempt_spends_its_repair_turns(self):
        seat = self.seat()
        planned = self.plan_reads(seat)
        self.assertLessEqual(len(planned), 40)
        transcript = self.drive(seat, stage_slips={
            stage: (lambda listed: []) for stage in range(1, 6)})
        self.assertEqual(transcript[-1][0], 'refuse')
        self.assertIn('repair turns', transcript[-1][1])
        repairs = [step for step in transcript
                   if step[0] == 'run' and 'repair' in Path(step[1]).read_text().splitlines()[0]]
        self.assertEqual(len(repairs), 4)

    def test_a_plan_seat_that_follows_every_stage_passes_the_audit(self):
        for name in ('sol', 'terra'):
            with self.subTest(seat=name):
                seat = self.plan_seat(name)
                transcript = self.drive(seat)
                self.assertEqual(transcript[-1], ['done'])
                self.assertEqual(len(transcript), len(self.plan_reads(seat)) + 1)
                self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_a_plan_seat_first_stage_that_reads_nothing_is_repaired(self):
        for name in ('sol', 'terra'):
            with self.subTest(seat=name):
                seat = self.plan_seat(name)
                planned = self.plan_reads(seat)
                transcript = self.drive(seat, {1: lambda listed: []})
                self.assertEqual(transcript[1][0], 'run', transcript[1])
                self.assertIn('repair', Path(transcript[1][1]).read_text().splitlines()[0])
                self.assertEqual(reads(transcript[1][1]), planned[0])
                self.assertEqual(transcript[-1], ['done'])
                self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_a_plan_seat_patch_chunk_read_ahead_is_kept(self):
        seat = self.plan_seat('sol')
        planned = self.plan_reads(seat)
        self.assertEqual([len(stage) for stage in planned[:2]], [1, 1])
        transcript = self.drive(seat, stage_slips={1: lambda listed: listed + planned[1]})
        self.assertEqual(transcript[-1], ['done'])
        self.assertEqual(len(transcript), len(planned))
        self.assertEqual(reads(transcript[1][1]), planned[2])
        self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_a_plan_seat_repeated_index_does_not_fail_the_seat(self):
        for name in ('sol', 'terra'):
            with self.subTest(seat=name):
                seat = self.plan_seat(name)
                planned = self.plan_reads(seat)
                transcript = self.drive(seat, stage_slips={
                    len(planned): lambda listed: listed + listed})
                self.assertEqual(transcript[-1], ['done'])
                self.assertEqual(len(transcript), len(planned) + 1)
                self.assertEqual(self.finish_and_audit(seat)[:2], (0, []))

    def test_a_plan_seat_first_call_outside_the_contract_is_refused(self):
        seat = self.plan_seat('terra')
        transcript = self.drive(seat, {1: lambda listed: ['ls src']})
        self.assertEqual(transcript[-1][0], 'refuse')
        self.assertEqual(len(transcript), 2)
        self.assertIn('invalid-plan-first-call', transcript[-1][1])


if __name__ == '__main__':
    unittest.main()
