#!/usr/bin/env python3
"""Plan bounded Codex turns for immutable, prepared review evidence."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile

LIB_DIR = Path(__file__).resolve().parent
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))
from review_limits import codex_review_turn_call_limit_for_model

OUTPUT_BYTES = 32 * 1024
PROOF_TURN_BYTES = 60 * 1024
STAGE_PLAN = 'stage-plan.json'
STAGE_STATE = 'stage-state.json'
# A plan seat proves its cluster searches and sources in review turns, after every stage.
STAGING_GAP_CODES = {'missing-plan-cluster-search', 'missing-plan-cluster-source'}
# The context a staged seat holds before its first review turn, fitted on completed Codex streams
# (projected over actual: median 1.10, minimum 0.85). Review turns then added a median 33K and at
# most 126K tokens, so staging may fill only 55% of the model's usable window.
CONTEXT_BASE_TOKENS = 17_000
CONTEXT_READ_TOKENS = 120
CONTEXT_STAGE_TURN_TOKENS = 300
READ_BYTES_PER_TOKEN = 2.8
PACKET_BYTES_PER_TOKEN = 2.4
PROMPT_BYTES_PER_TOKEN = 3.0
CONTEXT_SHARE_PERCENT = 55
HEX_RUN = re.compile(rb'[0-9a-f]{32,}')


class StageError(ValueError):
    pass


def safe_read(path, parent, limit=None):
    path = Path(path)
    if not path.is_absolute() or path.parent.resolve(strict=True) != parent:
        raise StageError('prepared artifact is outside the evidence session')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise StageError('cannot open prepared artifact: ' + path.name) from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise StageError('prepared artifact is not a private regular file: ' + path.name)
        if limit is not None and info.st_size > limit:
            raise StageError('prepared artifact exceeds its bounded size: ' + path.name)
        with os.fdopen(fd, 'rb', closefd=False) as source:
            raw = source.read() if limit is None else source.read(limit + 1)
        if limit is not None and len(raw) > limit:
            raise StageError('prepared artifact changed while reading: ' + path.name)
        return raw
    finally:
        os.close(fd)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def all_matches(lines, pattern):
    return [match for line in lines if (match := re.fullmatch(pattern, line))]


def artifact_bytes(session, artifacts, name, expected_hash=None, expected_size=None,
                   size_limit=None):
    entry = artifacts.get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get('sha256'), str):
        raise StageError('prepared artifact is not bound by the evidence manifest: ' + name)
    path = session / name
    raw = safe_read(path, session, size_limit)
    if sha256(raw) != entry['sha256']:
        raise StageError('prepared artifact hash differs from the evidence manifest: ' + name)
    if expected_hash is not None and sha256(raw) != expected_hash:
        raise StageError('prepared artifact hash differs from the prompt: ' + name)
    if expected_size is not None and len(raw) != expected_size:
        raise StageError('prepared artifact size differs from the prompt: ' + name)
    return raw


def direct_path(value, session, expected_name=None):
    path = Path(value)
    if (not path.is_absolute() or path.parent.resolve(strict=True) != session
            or expected_name is not None and path.name != expected_name):
        raise StageError('prompt artifact path is not the assigned session file')
    return path


def grouped(items, limit, visible, turn_bytes=PROOF_TURN_BYTES):
    if not 1 <= limit <= 2:
        raise StageError('Codex proof batch limit must be one or two')
    stages = []
    pending = []
    size = 0
    for item in items:
        amount = visible(item)
        if amount < 0 or amount > OUTPUT_BYTES:
            raise StageError('one prepared proof read exceeds the hard output limit')
        if pending and (len(pending) >= limit or size + amount > turn_bytes):
            stages.append(pending)
            pending = [item]
            size = amount
        else:
            pending.append(item)
            size += amount
    if pending:
        stages.append(pending)
    return stages


def command_file(path):
    return 'cat -- ' + shlex.quote(str(path))


def review_budget(prompt):
    matches = []
    for line in Path(prompt).read_text(encoding='utf-8').splitlines():
        match = re.search(r'use at most ([0-9]+) repository tool calls', line)
        if match:
            matches.append(int(match.group(1)))
    if len(matches) != 1 or matches[0] < 1:
        raise StageError('review prompt has no unique repository-call budget')
    return matches[0]


def read_audit_module():
    audit_path = Path(__file__).with_name('review-read-audit.py')
    spec = importlib.util.spec_from_file_location('review_read_audit_for_codex_staging', audit_path)
    if spec is None or spec.loader is None:
        raise StageError('review read auditor is unavailable')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    return audit


def required_post_index_read(prompt):
    audit = read_audit_module()
    try:
        return audit.parse_required_post_index_source_target(
            Path(prompt).read_text(encoding='utf-8').splitlines()) is not None
    except (OSError, UnicodeError, ValueError) as error:
        raise StageError(str(error)) from error


def required_post_index_target_description(prompt):
    audit = read_audit_module()
    try:
        target = audit.parse_required_post_index_source_target(
            Path(prompt).read_text(encoding='utf-8').splitlines())
    except (OSError, UnicodeError, ValueError) as error:
        raise StageError(str(error)) from error
    if target is None:
        return ''
    return f"{target['path']}:{target['line_start']}-{target['line_end']}"


def codex_call_rows(path):
    calls = {}
    turn = None
    turn_sequence = 0
    completed_turns = set()
    order = 0
    try:
        with open(path, encoding='utf-8') as source:
            for line in source:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get('type')
                if event_type == 'turn.started':
                    if turn is not None:
                        raise StageError('Codex review stream nested explicit turns')
                    turn_sequence += 1
                    turn = turn_sequence
                elif event_type == 'turn.completed':
                    if turn is None:
                        raise StageError('Codex review stream completed an inactive turn')
                    completed_turns.add(turn)
                    turn = None
                item = event.get('item') or {}
                if (event_type not in ('item.started', 'item.completed')
                        or item.get('type') != 'command_execution'):
                    continue
                if turn is None:
                    raise StageError('Codex review command fell outside its explicit turn')
                call_id = item.get('id')
                command = item.get('command')
                if not isinstance(call_id, str) or not call_id \
                        or not isinstance(command, str):
                    raise StageError('Codex review turn has an invalid command event')
                identity = (turn, call_id)
                call = calls.get(identity)
                if call is None:
                    order += 1
                    call = {'command': command, 'turn': turn, 'order': order}
                    calls[identity] = call
                elif call['command'] != command or call['turn'] != turn:
                    raise StageError('Codex review turn changed a command identity')
                if event_type == 'item.completed':
                    if 'output' in call:
                        raise StageError('Codex review turn repeated a command output')
                    if 'aggregated_output' not in item and 'output' not in item:
                        raise StageError('Codex review turn omitted a command output')
                    call['output'] = item.get('aggregated_output', item.get('output'))
                    call['success'] = item.get('exit_code') == 0
    except OSError as error:
        raise StageError('Codex review stream is unavailable') from error
    if turn is not None or any(
            'output' not in call or call['turn'] not in completed_turns
            for call in calls.values()):
        raise StageError('Codex review stream has incomplete explicit turn or command boundaries')
    return calls


def post_index_target_read_count(path, prompt, root, session):
    audit = read_audit_module()
    root = Path(root).resolve()
    session = Path(session).resolve()
    try:
        prompt_lines = Path(prompt).read_text(encoding='utf-8').splitlines()
        target = audit.parse_required_post_index_source_target(prompt_lines)
        if target is None:
            return 0, 0
        audit.validate_required_post_index_source_target(target, root)
        index = audit.required_evidence_index_path(prompt_lines, session)
        calls = codex_call_rows(path)
    except (OSError, UnicodeError, ValueError) as error:
        raise StageError(str(error)) from error
    ordered = sorted(calls.items(), key=lambda row: row[1]['order'])
    index_reads = [
        (call_id, call) for call_id, call in ordered
        if call['success'] and audit.evidence_index_call_matches(
            'codex', 'command_execution', {'command': call['command']},
            call['output'], index, root)
    ]
    if not index_reads:
        return 0, 0
    _, index_call = index_reads[0]
    post_index_ranges = []
    for _, call in ordered:
        if not call['success'] or call['turn'] <= index_call['turn'] \
                or call['order'] <= index_call['order']:
            continue
        ranges, _ = audit.shell_source_ranges(
            call['command'], root, session=session,
            line_limit=audit.CODEX_SOURCE_READ_LINES)
        if not audit.delivered_matches_source_ranges(
                'codex', 'command_execution', call['output'], ranges, root):
            continue
        post_index_ranges.extend(ranges)
        if audit._load_evidence_module().source_target_covered(
                target, post_index_ranges):
            return 1, 1
    return 0, 1


def review_status(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as error:
        raise StageError('Codex review-turn result is invalid') from error
    if not isinstance(value, dict) or set(value) != {'status', 'next_step'}:
        raise StageError('Codex review-turn result has an invalid shape')
    status = value.get('status')
    next_step = value.get('next_step')
    if status not in ('continue', 'ready') or not isinstance(next_step, str):
        raise StageError('Codex review-turn result is missing its status')
    next_step = ' '.join(next_step.split())
    if (status == 'continue' and not next_step
            or status == 'ready' and next_step
            or len(next_step) > 3000):
        raise StageError('Codex review-turn continuation is invalid')
    return status, next_step


def turn_stats(path, root, session):
    calls = {}
    outputs = set()
    total = 0
    starts = 0
    completions = 0
    active_turn = False

    def visible_bytes(value):
        if value is None:
            return 0
        if isinstance(value, str):
            return len(value.encode())
        if isinstance(value, list):
            return sum(visible_bytes(
                item.get('text', item.get('content', item)) if isinstance(item, dict) else item)
                       for item in value)
        return len(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())

    audit = read_audit_module()

    try:
        with open(path, encoding='utf-8') as source:
            for line in source:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get('type')
                if event_type == 'turn.started':
                    starts += 1
                    if active_turn:
                        raise StageError('Codex review stream nested explicit turns')
                    active_turn = True
                elif event_type == 'turn.completed':
                    completions += 1
                    if not active_turn:
                        raise StageError('Codex review stream completed an inactive turn')
                    active_turn = False
                item = event.get('item') or {}
                if (event_type in ('item.started', 'item.completed')
                        and item.get('type') == 'command_execution'):
                    if not active_turn:
                        raise StageError('Codex review command fell outside its explicit turn')
                    call_id = item.get('id')
                    command = item.get('command')
                    if not isinstance(call_id, str) or not call_id \
                            or not isinstance(command, str):
                        raise StageError('Codex review turn has an invalid command event')
                    if call_id in calls and calls[call_id] != command:
                        raise StageError('Codex review turn changed a command identity')
                    calls[call_id] = command
                    if event_type == 'item.completed':
                        if call_id in outputs:
                            raise StageError('Codex review turn repeated a command output')
                        if 'aggregated_output' not in item and 'output' not in item:
                            raise StageError('Codex review turn omitted a command output')
                        output = item.get('aggregated_output', item.get('output'))
                        total += visible_bytes(output)
                        outputs.add(call_id)
    except OSError as error:
        raise StageError('Codex review-turn stream is unavailable') from error
    if starts != 1 or completions != 1 or active_turn or set(calls) != outputs:
        raise StageError('Codex review turn has incomplete explicit turn or command boundaries')
    expansions = sum(audit.repository_expansion_call(
        'command_execution', {'command': command}, Path(root), Path(session))
        for command in calls.values())
    return len(calls), total, expansions


def prepared_stages(prompt, seat, model, stage_dir):
    session = prompt.parent.resolve(strict=True)
    lines = prompt.read_text(encoding='utf-8').splitlines()
    digest_rows = [re.fullmatch(r'Evidence manifest SHA-256: ([0-9a-f]{64})', line)
                   for line in lines]
    digests = [match.group(1) for match in digest_rows if match]
    if not digests:
        return []
    if len(digests) != 1:
        raise StageError('prompt must bind exactly one evidence manifest')
    suffix = '-' + seat + '.prompt.md'
    if not prompt.name.endswith(suffix):
        raise StageError('prepared prompt name does not bind the assigned seat')
    label = prompt.name[:-len(suffix)]
    if not re.fullmatch(r'r[A-Za-z0-9_.-]+', label):
        raise StageError('prepared prompt name does not bind a review round')
    manifest_path = session / (label + '-evidence.manifest.json')
    manifest_raw = safe_read(manifest_path, session, 16 * 1024 * 1024)
    if sha256(manifest_raw) != digests[0]:
        raise StageError('prepared prompt evidence manifest hash changed')
    try:
        manifest = json.loads(manifest_raw)
    except (UnicodeError, ValueError) as error:
        raise StageError('prepared evidence manifest is invalid') from error
    if (not isinstance(manifest, dict) or manifest.get('label') != label[1:]
            or manifest.get('session') != str(session)):
        raise StageError('prepared evidence manifest identity changed')
    assignment = manifest.get('assignments', {}).get(seat)
    if not isinstance(assignment, dict) or assignment.get('adapter') != 'codex':
        raise StageError('prepared assignment does not match the pinned Codex seat')
    if assignment.get('model') is None:
        return []
    if assignment.get('model') != model:
        raise StageError('prepared assignment model differs from the pinned Codex seat')
    artifacts = manifest.get('artifacts')
    if not isinstance(artifacts, dict):
        raise StageError('prepared evidence artifact table is missing')

    stages = []
    patch_mode = assignment.get('patch_read_mode')
    if patch_mode == 'chunks':
        canonical = assignment.get('patch')
        canonical_path = direct_path(canonical, session)
        canonical_raw = artifact_bytes(session, artifacts, canonical_path.name,
                                       assignment.get('patch_sha256'),
                                       assignment.get('patch_bytes'))
        patch_sets = manifest.get('patch_sets', {})
        patch_set = patch_sets.get(assignment.get('patch_set')) if isinstance(patch_sets, dict) else None
        chunks = patch_set.get('chunks') if isinstance(patch_set, dict) else None
        if (not isinstance(chunks, list) or not chunks
                or patch_set.get('patch_sha256') != sha256(canonical_raw)
                or patch_set.get('patch_bytes') != len(canonical_raw)):
            raise StageError('assigned patch chunk manifest is invalid')
        chunk_lines = all_matches(
            lines, r'Assigned patch chunk ([0-9]+)/([0-9]+): (.+) bytes ([0-9]+)-([0-9]+) SHA-256 ([0-9a-f]{64})')
        expected_lines = []
        verified_chunks = []
        cursor = 0
        for index, row in enumerate(chunks, 1):
            name = row.get('artifact')
            if (not isinstance(name, str) or row.get('index') != index
                    or row.get('byte_start') != cursor):
                raise StageError('assigned patch chunks are not contiguous')
            raw = artifact_bytes(session, artifacts, name, row.get('sha256'), row.get('bytes'), OUTPUT_BYTES)
            end = cursor + len(raw)
            if end != row.get('byte_end') or canonical_raw[cursor:end] != raw:
                raise StageError('assigned patch chunk differs from the canonical patch')
            path = direct_path(str(session / name), session, name)
            expected_lines.append((index, len(chunks), str(path), cursor, end, row['sha256']))
            verified_chunks.append({'path': path, 'command': command_file(path),
                                    'visible': row.get('predicted_visible_bytes', len(raw))})
            cursor = end
        observed_lines = [(int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)),
                           int(m.group(5)), m.group(6)) for m in chunk_lines]
        if observed_lines != expected_lines or cursor != len(canonical_raw):
            raise StageError('prompt patch chunks differ from the assigned evidence manifest')
        limit_rows = all_matches(lines, r'Patch chunk batch limit: ([0-9]+)')
        if len(limit_rows) != 1:
            raise StageError('prompt patch chunk batch limit is missing or repeated')
        patch_limit = int(limit_rows[0].group(1))
        # A chunk pair read twice in its turn is only an audit advisory while the turn stays
        # within 32 KiB; past that the audit voids the turn and counts its reads past the batch
        # limit, so larger chunks are read one per turn, where a repeat can still be repaired.
        stages.extend([{'kind': 'patch chunks', 'files': group}
                       for group in grouped(verified_chunks, patch_limit,
                                            lambda item: item['visible'],
                                            turn_bytes=OUTPUT_BYTES // 2)])
    elif patch_mode in ('full', 'windows'):
        patch_path = direct_path(assignment.get('patch'), session)
        raw = artifact_bytes(session, artifacts, patch_path.name,
                             assignment.get('patch_sha256'), assignment.get('patch_bytes'),
                             32 * 1024 * 1024)
        read_rows = all_matches(
            lines, r'Read the entire assigned patch in bounded windows of at most ([0-9]+) lines, ending at line ([0-9]+): (.+)')
        if assignment.get('patch_bytes') and len(read_rows) != 1:
            raise StageError('prompt full-patch window contract is missing or repeated')
        if read_rows:
            line_limit, total_lines = int(read_rows[0].group(1)), int(read_rows[0].group(2))
            content_lines = raw.split(b'\n')
            if content_lines and content_lines[-1] == b'':
                content_lines.pop()
            if (read_rows[0].group(3) != str(patch_path) or total_lines != len(content_lines)
                    or not 1 <= line_limit <= 160):
                raise StageError('prompt full-patch window contract differs from the manifest')
            start = 0
            while start < len(content_lines):
                end = min(len(content_lines), start + line_limit)
                while end > start and sum(len(line) + 1 for line in content_lines[start:end]) > OUTPUT_BYTES:
                    end -= 1
                if end == start:
                    raise StageError('one assigned patch line exceeds the hard output limit')
                first, last = start + 1, end
                command = shlex.join(['sed', '-n', f'{first},{last}p', str(patch_path)])
                stages.append({'kind': 'patch window', 'files': [{
                    'path': patch_path, 'command': command, 'window': [first, last]}]})
                start = end
    elif patch_mode != 'empty':
        raise StageError('unsupported assigned patch read mode')

    context = manifest.get('source_context', {})
    packet = context.get('seats', {}).get(seat, {}) if isinstance(context, dict) else {}
    shards = packet.get('shards', []) if isinstance(packet, dict) else []
    packet_paths = all_matches(lines, r'Source context packet: (.+)')
    expected_packets = [row.get('artifact') for row in shards]
    observed_packets = [m.group(1) for m in packet_paths]
    if observed_packets != [str(session / name) for name in expected_packets]:
        raise StageError('prompt source packets differ from the assigned evidence manifest')
    if shards:
        packet_limit_rows = all_matches(lines, r'Source context packet batch limit: ([0-9]+)')
        if len(packet_limit_rows) != 1:
            raise StageError('source packet batch limit is missing or repeated')
        packet_limit = int(packet_limit_rows[0].group(1))
        if packet_limit != context.get('packet_batch_limit'):
            raise StageError('prompt source packet batch limit differs from the manifest')
    elif all_matches(lines, r'Source context packet batch limit: ([0-9]+)'):
        raise StageError('prompt contains an unassigned source packet batch limit')
    for row in shards:
        name = row.get('artifact')
        artifact_bytes(session, artifacts, name, expected_size=row.get('bytes'),
                       size_limit=OUTPUT_BYTES)
        stages.append({'kind': 'source context packet',
                       'files': [{'path': session / name, 'command': command_file(session / name)}]})

    required = packet.get('required_source_ranges', [])
    segment_lines = all_matches(
        lines, r'Required source segment ([0-9]+)/([0-9]+): run (.+) raw bytes ([0-9]+) visible bytes ([0-9]+) content SHA-256 ([0-9a-f]{64})')
    expected_segments = []
    segment_files = []
    for range_row in required:
        segments = range_row.get('segments', [])
        for index, row in enumerate(segments, 1):
            name = row.get('artifact')
            path = session / name
            raw = artifact_bytes(session, artifacts, name, row.get('content_sha256'),
                                 row.get('raw_bytes'), OUTPUT_BYTES)
            expected_segments.append((index, len(segments), command_file(path), len(raw),
                                      row['predicted_visible_bytes'], row['content_sha256']))
            segment_files.append({'path': path, 'visible': row['predicted_visible_bytes']})
    observed_segments = []
    for match in segment_lines:
        try:
            command = shlex.split(match.group(3))
        except ValueError as error:
            raise StageError('prompt source segment command is malformed') from error
        if len(command) != 3 or command[:2] != ['cat', '--']:
            raise StageError('prompt source segment is not one bounded cat command')
        observed_segments.append((int(match.group(1)), int(match.group(2)),
                                  shlex.join(command), int(match.group(4)),
                                  int(match.group(5)), match.group(6)))
    if observed_segments != expected_segments:
        raise StageError('prompt source segments differ from the assigned evidence manifest')
    segment_limits = [int(match.group(1)) for match in all_matches(
        lines, r'Required source segment batch limit: ([0-9]+)')]
    if segment_limits != [2] * sum(bool(row.get('segments')) for row in required):
        if any(row.get('segments') for row in required):
            raise StageError('prompt source segment batch limits are missing or changed')
        if segment_limits:
            raise StageError('prompt contains an unassigned source segment batch limit')
    if segment_files:
        # In a segment pair a read-ahead makes three proof reads, past the audit's batch limit of
        # two, and can never be repaired, so segments are read one per turn; that limit still
        # lets a turn read exactly the next segment ahead.
        for group in grouped(segment_files, 1, lambda item: item['visible']):
            stages.append({'kind': 'required source segments',
                           'files': [{'path': item['path'], 'command': command_file(item['path'])}
                                     for item in group]})

    index_path = session / (label + '-evidence.md')
    index_rows = all_matches(lines, r'Evidence navigation index: (.+)')
    if len(index_rows) != 1 or index_rows[0].group(1) != str(index_path):
        raise StageError('prompt evidence index differs from the assigned session')
    artifact_bytes(session, artifacts, index_path.name, size_limit=16 * 1024)
    stages.append({'kind': 'evidence navigation index',
                   'files': [{'path': index_path, 'command': command_file(index_path)}]})

    stage_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for index, stage in enumerate(stages, 1):
        (stage_dir / f'stage-{index:04d}.prompt').write_text(stage_prompt_text(
            index, len(stages), stage['kind'], [item['command'] for item in stage['files']]),
            encoding='utf-8')
    write_json(stage_dir / STAGE_PLAN, {'stages': [
        {'kind': stage['kind'], 'reads': [
            {'command': item['command'], 'path': str(Path(item['path']).resolve()),
             'window': item.get('window')} for item in stage['files']]}
        for stage in stages]})
    return stages


def stage_prompt_text(number, total, kind, commands, repair=None):
    heading = f'Prepared evidence read stage {number} of {total} ({kind})'
    lines = [heading + (f', repair turn {repair}.' if repair else '.')]
    if repair:
        lines.append('The previous turn did not deliver the read below. Do not reread anything else.')
    lines.extend([
        'Read exactly the listed prepared artifact(s), in order, with one native shell tool call per line.',
        'Do not search, read anything else, review the change, or combine commands.',
        'After all reads succeed, respond exactly READ_STAGE_COMPLETE and stop.',
    ])
    lines.extend('Read exactly: ' + command for command in commands)
    return '\n'.join(lines) + '\n'


def write_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True)
    os.replace(temporary, path)


def repair_turn_limit(stage_count):
    """The repair turns one attempt may spend: a tenth of its stages, and at least four."""
    return max(4, -(-stage_count // 10))


def read_label(read):
    window = read.get('window')
    name = Path(read['path']).name
    return f'{name} lines {window[0]}-{window[1]}' if window else name


def read_bytes(read, session, audit):
    raw = safe_read(read['path'], session, 32 * 1024 * 1024)
    if not read.get('window'):
        return raw
    first, last = read['window']
    return b''.join(audit.split_lf_lines(raw)[first - 1:last])


def context_tokens(raw, bytes_per_token):
    """Estimated tokens for text; a hash or other long hex run costs about one token per byte."""
    hex_bytes = sum(len(run) for run in HEX_RUN.findall(raw))
    return (len(raw) - hex_bytes) / bytes_per_token + hex_bytes


def usable_context_window(model):
    """(usable tokens, None) from the model's row in the Codex model cache that the roster reads,
    or (None, why it is unknown)."""
    from roster import codex_catalog_path
    path = codex_catalog_path()
    try:
        with open(path, encoding='utf-8') as source:
            models = json.load(source).get('models')
    except (OSError, UnicodeError, ValueError, AttributeError):
        return None, f'no readable Codex model cache at {path} for {model}'
    rows = [row for row in models if isinstance(row, dict) and row.get('slug') == model] \
        if isinstance(models, list) else []
    if len(rows) != 1:
        return None, f'{model} is not listed once in {path}'
    window = rows[0].get('context_window')
    percent = rows[0].get('effective_context_window_percent')
    if (type(window) is not int or window <= 0 or type(percent) not in (int, float)
            or not 0 < percent <= 100):
        return None, f'{model} has no valid context window in {path}'
    return math.floor(window * percent / 100), None


def context_capacity(stage_dir, prompt, model):
    """('fits', projected, limit), ('over', reason) or ('unknown', reason) for the context a seat
    holds before review: the staged reads and their turns, then the assignment prompt."""
    usable, unknown = usable_context_window(model)
    if unknown:
        return ('unknown', unknown)
    plan_path = Path(stage_dir) / STAGE_PLAN
    stages = (json.loads(plan_path.read_text(encoding='utf-8'))['stages']
              if plan_path.exists() else [])
    session = Path(prompt).parent.resolve(strict=True)
    audit = read_audit_module()
    projected = CONTEXT_BASE_TOKENS + CONTEXT_STAGE_TURN_TOKENS * len(stages)
    for stage in stages:
        rate = (PACKET_BYTES_PER_TOKEN if stage['kind'] == 'source context packet'
                else READ_BYTES_PER_TOKEN)
        for read in stage['reads']:
            projected += (context_tokens(read_bytes(read, session, audit), rate)
                          + CONTEXT_READ_TOKENS)
    projected = math.ceil(projected + context_tokens(Path(prompt).read_bytes(),
                                                     PROMPT_BYTES_PER_TOKEN))
    limit = usable * CONTEXT_SHARE_PERCENT // 100
    if projected > limit:
        return ('over', f'the assignment needs ~{projected} tokens of context before review, over'
                f" {limit} ({CONTEXT_SHARE_PERCENT}% of {model}'s {usable} usable)")
    return ('fits', str(projected), str(limit))


def exact_stage_turn(turn, reads, root, session, audit):
    """Whether the turn ran exactly these planned reads, each delivering the prepared bytes."""
    turn_stats(turn, root, session)
    rows = sorted(codex_call_rows(turn).values(), key=lambda row: row['order'])
    if len(rows) != len(reads):
        return False
    total = 0
    for row, read in zip(rows, reads):
        try:
            words = shlex.split(audit.unwrap_shell(row['command']))
        except ValueError:
            return False
        text = audit.output_text(row['output'])
        if (not row['success'] or text is None or words != shlex.split(read['command'])
                or not audit.delivered_matches_bytes(
                    'codex', 'command_execution', row['output'],
                    read_bytes(read, session, audit), 1)):
            return False
        total += len(text.encode())
    return total <= PROOF_TURN_BYTES


def audit_credited_reads(plan, raw, prompt, root, session, seat, deps, audit):
    """Replay the post-run audit over the stream so far: the planned reads it credits, or why
    no later read can make the stream pass."""
    progress = {}
    with tempfile.TemporaryDirectory(prefix='codex-stage-audit-') as directory:
        result = Path(directory) / 'result.json'
        result.write_text('{"findings":[]}\n', encoding='utf-8')
        with contextlib.redirect_stdout(sys.stderr):
            assessment, unique = audit.assessed(argparse.Namespace(
                adapter='codex', raw=str(raw), prompt=str(prompt), root=str(root),
                session=str(session), seat=seat, deps=deps, result=str(result),
                out=str(Path(directory) / 'audit.json')), progress)
    gaps = audit.READABLE_GAP_CODES | STAGING_GAP_CODES
    if not assessment.get('tool_calls'):
        # Only the stream's first call can satisfy or break the plan first-call contract.
        gaps = gaps | {'invalid-plan-first-call'}
    rejected = sorted(set(progress.get('fatal') or []) - gaps)
    if unique and rejected:
        return None, 'the read audit rejects this stream (' + ', '.join(rejected) + ')'
    if unique and not progress.get('recoverable', False):
        return None, ('it read a prepared artifact ahead of an unread one, which the read audit'
                      ' cannot accept')
    missing = [item for item in progress.get('missing') or [] if isinstance(item, str)]
    gaps = [(match.group(1), int(match.group(2)), int(match.group(3))) for match in (
        re.fullmatch(r'(.+) lines ([0-9]+)-([0-9]+)', item) for item in missing) if match]
    # A read the audit lists nowhere still needs a call that opened it, so a replay that stops
    # early can never skip a planned read.
    opened = {str(path) for row in codex_call_rows(raw).values() if row['success']
              for path in audit.paths_opened_by_call(
                  'command_execution', {'command': row['command']}, root)}
    credited = set()
    for stage in plan:
        for read in stage['reads']:
            window = read.get('window')
            if read['path'] not in opened:
                continue
            if window and any(path == read['path'] and start <= window[1] and window[0] <= end
                              for path, start, end in gaps):
                continue
            if not window and read['path'] in missing:
                continue
            credited.add(read['command'])
    return credited, None


def stage_step(stage_dir, raw, turn, prompt, seat, root, session, deps=None):
    """Judge the last prepared-evidence turn, then name the next turn: ('run', prompt, note),
    ('done',) or ('refuse', reason)."""
    stage_dir, root, session = Path(stage_dir), Path(root).resolve(), Path(session).resolve()
    try:
        plan = json.loads((stage_dir / STAGE_PLAN).read_text(encoding='utf-8'))['stages']
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise StageError('prepared evidence stage plan is unavailable') from error
    state_path = stage_dir / STAGE_STATE
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
    else:
        state = {'issued': -1, 'pending': None, 'credited': [], 'repairs': 0,
                 'stage_repairs': {}}
    audit = read_audit_module()
    total = len(plan)
    credited = set(state['credited'])
    pending = state['pending']
    if pending is not None:
        reads = pending['reads']
        if exact_stage_turn(turn, reads, root, session, audit):
            credited.update(read['command'] for read in reads)
        else:
            credited, reason = audit_credited_reads(
                plan, raw, prompt, root, session, seat, deps, audit)
            if reason:
                return ('refuse', f"prepared evidence stage {pending['stage'] + 1} of {total}"
                        ' cannot be repaired: ' + reason)
        state['pending'] = None
    state['credited'] = sorted(credited)
    for index, stage in enumerate(plan):
        remaining = [read for read in stage['reads'] if read['command'] not in credited]
        if remaining:
            break
    else:
        write_json(state_path, state)
        return ('done',)
    where = f'prepared evidence stage {index + 1} of {total}'
    note = None
    repair = None
    if index <= state['issued']:
        count = state['stage_repairs'].get(str(index), 0)
        label = read_label(remaining[0])
        if count >= len(stage['reads']) + 1:
            return ('refuse', f'{where} is still missing {label} after {count} repair turns')
        limit = repair_turn_limit(total)
        if state['repairs'] >= limit:
            return ('refuse', f'{where} is missing {label}, and this attempt has used all'
                    f' {limit} of its repair turns')
        repair = count + 1
        state['stage_repairs'][str(index)] = repair
        state['repairs'] += 1
        remaining = remaining[:1]
        note = (f'{where}: repair turn {repair} reads {label}, which the read audit has not'
                ' credited yet')
    else:
        state['issued'] = index
    state['turns'] = state.get('turns', 0) + 1
    path = stage_dir / f"turn-{state['turns']:04d}.prompt"
    path.write_text(stage_prompt_text(index + 1, total, stage['kind'],
                                      [read['command'] for read in remaining], repair),
                    encoding='utf-8')
    state['pending'] = {'stage': index, 'reads': remaining}
    write_json(state_path, state)
    return ('run', str(path)) + ((note,) if note else ())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt')
    parser.add_argument('--seat')
    parser.add_argument('--model')
    parser.add_argument('--stage-dir')
    parser.add_argument('--thread-id-stream')
    parser.add_argument('--review-budget')
    parser.add_argument('--review-turn-call-limit')
    parser.add_argument('--stage-step')
    parser.add_argument('--capacity')
    parser.add_argument('--raw')
    parser.add_argument('--turn')
    parser.add_argument('--deps')
    parser.add_argument('--required-post-index-read')
    parser.add_argument('--required-post-index-target')
    parser.add_argument('--review-status')
    parser.add_argument('--turn-stats')
    parser.add_argument('--post-index-target-read-count')
    parser.add_argument('--root')
    parser.add_argument('--session')
    args = parser.parse_args()
    if args.review_turn_call_limit is not None:
        print(codex_review_turn_call_limit_for_model(args.review_turn_call_limit))
        return 0
    if args.review_budget:
        try:
            print(review_budget(args.review_budget))
        except (OSError, UnicodeError, StageError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.stage_step:
        try:
            if not all((args.raw, args.turn, args.prompt, args.seat, args.root, args.session)):
                raise StageError('a prepared evidence step needs its stream, prompt and roots')
            print('\t'.join(stage_step(args.stage_step, args.raw, args.turn, args.prompt,
                                       args.seat, args.root, args.session, args.deps)))
        except (OSError, UnicodeError, StageError, KeyError, TypeError, ValueError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.capacity:
        try:
            if not args.prompt or not args.model:
                raise StageError('a context capacity check needs the prompt and the model')
            print('\t'.join(context_capacity(args.capacity, args.prompt, args.model)))
        except (OSError, UnicodeError, StageError, KeyError, TypeError, ValueError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.required_post_index_read:
        try:
            print('1' if required_post_index_read(args.required_post_index_read) else '0')
        except (OSError, UnicodeError, StageError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.required_post_index_target:
        try:
            print(required_post_index_target_description(args.required_post_index_target))
        except (OSError, UnicodeError, StageError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.review_status:
        try:
            status, next_step = review_status(args.review_status)
            print(status if status == 'ready' else status + '\t' + next_step)
        except StageError as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.turn_stats:
        try:
            if not args.root or not args.session:
                raise StageError('review turn metrics require the repository and session roots')
            calls, output_bytes, expansions = turn_stats(
                args.turn_stats, args.root, args.session)
            print(f'{calls}\t{output_bytes}\t{expansions}')
        except (OSError, UnicodeError, StageError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.post_index_target_read_count:
        try:
            if not args.prompt or not args.root or not args.session:
                raise StageError('post-index target proof requires the prompt and review roots')
            target_read, index_read = post_index_target_read_count(
                args.post_index_target_read_count, args.prompt, args.root, args.session)
            print(f'{target_read}\t{index_read}')
        except (OSError, UnicodeError, StageError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        return 0
    if args.thread_id_stream:
        try:
            ids = set()
            with open(args.thread_id_stream, encoding='utf-8') as source:
                for line in source:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get('type') == 'thread.started':
                        thread_id = event.get('thread_id')
                        if not isinstance(thread_id, str) or not thread_id:
                            raise StageError('Codex did not return a resumable thread ID')
                        ids.add(thread_id)
            if len(ids) != 1:
                raise StageError('Codex returned no unique resumable thread ID')
        except (OSError, UnicodeError, StageError, TypeError) as error:
            print('codex proof staging: ' + str(error), file=sys.stderr)
            return 1
        print(next(iter(ids)))
        return 0
    if not all((args.prompt, args.seat, args.model, args.stage_dir)):
        parser.error('--prompt, --seat, --model, and --stage-dir are required')
    try:
        stages = prepared_stages(Path(args.prompt), args.seat, args.model,
                                 Path(args.stage_dir))
    except (OSError, StageError, TypeError, KeyError, ValueError) as error:
        print('codex proof staging: ' + str(error), file=sys.stderr)
        return 1
    print(len(stages))
    return 0


if __name__ == '__main__':
    sys.exit(main())
