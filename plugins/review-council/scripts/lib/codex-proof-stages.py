#!/usr/bin/env python3
"""Plan bounded Codex turns for immutable, prepared review evidence."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys

LIB_DIR = Path(__file__).resolve().parent
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))
from review_limits import codex_review_turn_call_limit_for_model

OUTPUT_BYTES = 32 * 1024
PROOF_TURN_BYTES = 60 * 1024
SOURCE_SEGMENT_VISIBLE_LIMIT = 16 * 1024
PREPARED_READS_PER_TURN = 1


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


def grouped(items, limit, visible, standalone=None):
    if not 1 <= limit <= 2:
        raise StageError('Codex proof batch limit must be one or two')
    stages = []
    pending = []
    size = 0
    for item in items:
        amount = visible(item)
        if amount < 0 or amount > OUTPUT_BYTES:
            raise StageError('one prepared proof read exceeds the hard output limit')
        alone = standalone(item) if standalone else False
        if alone:
            if pending:
                stages.append(pending)
                pending = []
                size = 0
            stages.append([item])
        elif pending and (len(pending) >= limit or size + amount > PROOF_TURN_BYTES):
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


def stage_read_count(prompt):
    count = sum(line.startswith('Read exactly: ')
                for line in Path(prompt).read_text(encoding='utf-8').splitlines())
    if count != PREPARED_READS_PER_TURN:
        raise StageError('prepared proof stage must contain exactly one read')
    return count


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


def expected_stage_read(prompt, session):
    lines = Path(prompt).read_text(encoding='utf-8').splitlines()
    reads = [line[len('Read exactly: '):] for line in lines
             if line.startswith('Read exactly: ')]
    if len(reads) != PREPARED_READS_PER_TURN:
        raise StageError('prepared proof stage must contain exactly one read')
    try:
        words = shlex.split(reads[0])
    except ValueError as error:
        raise StageError('prepared proof stage read command is malformed') from error
    if len(words) != 3 or words[:2] != ['cat', '--']:
        raise StageError('prepared proof stage read must be one bounded cat command')
    target = direct_path(words[2], Path(session).resolve(strict=True))
    return target, safe_read(target, Path(session).resolve(strict=True), OUTPUT_BYTES)


def turn_stats(path, root, session, stage_prompt=None):
    calls = {}
    outputs = set()
    output_values = {}
    successes = {}
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
                        output_values[call_id] = output
                        successes[call_id] = item.get('exit_code') == 0
    except OSError as error:
        raise StageError('Codex review-turn stream is unavailable') from error
    if starts != 1 or completions != 1 or active_turn or set(calls) != outputs:
        raise StageError('Codex review turn has incomplete explicit turn or command boundaries')
    root_path = Path(root).resolve()
    session_path = Path(session).resolve()
    if stage_prompt is not None:
        expected_path, expected_raw = expected_stage_read(stage_prompt, session_path)
        if len(calls) != PREPARED_READS_PER_TURN:
            raise StageError('prepared proof turn did not read its listed artifact')
        call_id, command = next(iter(calls.items()))
        call_data = {'command': command}
        if (not successes.get(call_id)
                or audit.paths_opened_by_call('command_execution', call_data, root_path)
                != [expected_path]
                or not audit.complete_packet_read(
                    'command_execution', call_data, expected_path, root_path)
                or not audit.delivered_matches_bytes(
                    'codex', 'command_execution', output_values[call_id], expected_raw, 1)):
            raise StageError('prepared proof turn did not exactly read its listed artifact')
    expansions = sum(audit.repository_expansion_call(
        'command_execution', {'command': command}, root_path, session_path)
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
        batches = grouped(verified_chunks, patch_limit, lambda item: item['visible'])
        stages.extend({'kind': 'patch chunks', 'files': [item]}
                      for group in batches for item in group)
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
                stages.append({'kind': 'patch window', 'files': [{'path': patch_path,
                                                                   'command': command}]})
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
            segment_files.append({'path': path, 'visible': row['predicted_visible_bytes'],
                                  'oversized': (row['line_start'] == row['line_end']
                                                and row['predicted_visible_bytes']
                                                > SOURCE_SEGMENT_VISIBLE_LIMIT)})
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
    if segment_limits != [2] * len(required):
        if required:
            raise StageError('prompt source segment batch limits are missing or changed')
        if segment_limits:
            raise StageError('prompt contains an unassigned source segment batch limit')
    if segment_files:
        for group in grouped(segment_files, PREPARED_READS_PER_TURN,
                             lambda item: item['visible'],
                             lambda item: item['oversized']):
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
        stage_prompt = [
            f'Prepared evidence read stage {index} of {len(stages)} ({stage["kind"]}).',
            'Read exactly the one listed prepared artifact in full with one native shell tool call.',
            'Do not search, read anything else, review the change, or combine commands.',
            'After all reads succeed, respond exactly READ_STAGE_COMPLETE and stop.',
        ]
        stage_prompt.extend('Read exactly: ' + item['command'] for item in stage['files'])
        (stage_dir / f'stage-{index:04d}.prompt').write_text(
            '\n'.join(stage_prompt) + '\n', encoding='utf-8')
    return stages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt')
    parser.add_argument('--seat')
    parser.add_argument('--model')
    parser.add_argument('--stage-dir')
    parser.add_argument('--thread-id-stream')
    parser.add_argument('--review-budget')
    parser.add_argument('--review-turn-call-limit')
    parser.add_argument('--stage-read-count')
    parser.add_argument('--required-post-index-read')
    parser.add_argument('--required-post-index-target')
    parser.add_argument('--review-status')
    parser.add_argument('--turn-stats')
    parser.add_argument('--stage-prompt')
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
    if args.stage_read_count:
        try:
            print(stage_read_count(args.stage_read_count))
        except (OSError, UnicodeError, StageError) as error:
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
                args.turn_stats, args.root, args.session, args.stage_prompt)
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
