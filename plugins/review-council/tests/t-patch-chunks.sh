#!/bin/bash

test_patch_chunk_partition_contract() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import importlib.util
import math
import sys

spec = importlib.util.spec_from_file_location('evidence', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

raw = b''.join((b'x' * (59 if index < 1537 else 58)) + b'\n'
               for index in range(14_319))
assert len(raw) == 846_358
chunks = module.partition_patch_chunks(raw)
assert len(raw.splitlines()) == 14_319
assert math.ceil(len(raw.splitlines()) / 240) == 60
assert len(chunks) == 35, len(chunks)
assert len(chunks) <= math.floor(math.ceil(len(raw.splitlines()) / 240) * 0.9)
assert b''.join(row['content'] for row in chunks) == raw
cursor = 0
for index, row in enumerate(chunks, 1):
    assert row['index'] == index
    assert row['byte_start'] == cursor
    assert row['byte_end'] == cursor + len(row['content'])
    assert row['bytes'] == len(row['content']) <= 24 * 1024
    assert row['display_lines'] <= 1000
    assert row['bytes'] + row['display_lines'] * 8 <= 30 * 1024
    assert row['sha256'] == module.digest(row['content'])
    row['content'].decode('utf-8')
    cursor = row['byte_end']
assert cursor == len(raw)

long_line = ('a' + '\u20ac' * 25_000 + 'z').encode()
long_chunks = module.partition_patch_chunks(long_line)
assert len(long_chunks) >= 4
assert b''.join(row['content'] for row in long_chunks) == long_line
assert all(row['content'].decode('utf-8') for row in long_chunks)
assert all(not row['content'].endswith(b'\n') for row in long_chunks)

terminal = b'one\ntwo'
terminal_chunks = module.partition_patch_chunks(terminal)
assert b''.join(row['content'] for row in terminal_chunks) == terminal
assert not terminal_chunks[-1]['content'].endswith(b'\n')

assert module.patch_chunk_mode(b'one\n', module.partition_patch_chunks(b'one\n'), True) == 'windows'
assert module.patch_chunk_mode(raw, chunks, False) == 'windows'
assert module.patch_chunk_mode(b'\xff\n', [], True) == 'windows'
assert module.patch_chunk_mode(b'a\0b\n', [], True) == 'windows'

other = b'y' + raw[1:]
scopes = {
    'a': {'patch_sha256': module.digest(raw)},
    'b': {'patch_sha256': module.digest(raw)},
    'c': {'patch_sha256': module.digest(other)},
}
sets, artifacts = module.patch_sets_for(scopes, {'a': raw, 'b': raw, 'c': other}, 'r9', True)
assert scopes['a']['patch_set'] == scopes['b']['patch_set']
assert scopes['c']['patch_set'] != scopes['a']['patch_set']
assert len(sets) == 2 and artifacts
print('partition contract passes')
PY
  assert_eq "patch chunks partition and reconstruct exact UTF-8 bytes" "$?" 0
}

test_patch_chunk_manifest_contract() {
  ( local R="$T/patch-chunk-manifest-root" S="$T/patch-chunk-manifest-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R/src/large.py" <<'PY'
import sys
with open(sys.argv[1], 'w') as stream:
    for index in range(4200):
        stream.write(f'value_{index:04d} = {index:04d}\n')
PY
    local base manifest
    base=$(git -C "$R" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/large.py\n' > "$S/files.txt"; printf 'src/large.py\n' > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"gemini"}]}' > "$S/roster.json"
    manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 21 --phase discovery) || return
    python3 - "$manifest" <<'PY'
import hashlib, json, pathlib, sys
m = json.load(open(sys.argv[1])); session = pathlib.Path(sys.argv[1]).parent
assert m['schema_version'] == 2
assignments = list(m['assignments'].values())
assert {row['patch_read_mode'] for row in assignments} == {'chunks'}
sets = {row['patch_set'] for row in assignments}
assert len(sets) == 1
chunks = m['patch_sets'][assignments[0]['patch_set']]['chunks']
assert 2 <= len(chunks) < (assignments[0]['patch_lines'] + 239) // 240
assert all(m['patch_sets'][row['patch_set']]['chunks'] == chunks for row in assignments)
raw = b''.join((session / row['artifact']).read_bytes() for row in chunks)
assert hashlib.sha256(raw).hexdigest() == assignments[0]['patch_sha256']
assert len(raw) == assignments[0]['patch_bytes']
assert sum(row['bytes'] for row in chunks) == len(raw)
assert sum(row['display_lines'] for row in chunks) >= assignments[0]['patch_lines']
assert len({row['artifact'] for row in chunks}) == len(chunks)
PY
    assert_eq "identical assignments share one immutable patch chunk set" "$?" 0

    local prompt
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 21 sol correctness chunks --evidence "$manifest") || return
    assert_grep "chunk prompt names chunk mode" "$prompt" '^Assigned patch read mode: chunks$'
    assert_eq "chunk prompt renders each artifact once" \
      "$(grep -c '^Assigned patch chunk [0-9]' "$prompt")" \
      "$(python3 - "$manifest" <<'PY'
import json, sys
m=json.load(open(sys.argv[1])); a=m['assignments']['sol']; print(len(m['patch_sets'][a['patch_set']]['chunks']))
PY
)"
    assert_nogrep "chunk prompt does not request line windows" "$prompt" \
      '^Read the entire assigned patch in bounded windows'
    assert_grep "Codex keeps one patch chunk per turn" "$prompt" \
      '^Patch chunk batch limit: 1$'
    assert_grep "Codex chunk prompt gives an exact shell recipe" "$prompt" \
      '^First assigned-patch action: run cat -- '
    assert_nogrep "Codex chunk prompt never requests a native read tool" "$prompt" \
      '^First assigned-patch action:.*Read|^First assigned-patch action:.*read_file'
    local grok_prompt opus_prompt gemini_prompt
    grok_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 21 grok correctness chunks --evidence "$manifest") || return
    opus_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 21 opus correctness chunks --evidence "$manifest") || return
    gemini_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 21 opus-2 correctness chunks --evidence "$manifest") || return
    assert_grep "Grok batches two consecutive patch chunks" "$grok_prompt" \
      '^Patch chunk batch limit: 2$'
    assert_grep "Opus batches two consecutive patch chunks" "$opus_prompt" \
      '^Patch chunk batch limit: 2$'
    assert_grep "Grok chunk prompt uses read_file" "$grok_prompt" \
      '^First assigned-patch action: use read_file to read 2 consecutive listed chunks in full'
    assert_grep "Opus chunk prompt uses Read" "$opus_prompt" \
      '^First assigned-patch action: use Read to read 2 consecutive listed chunks in full'
    assert_grep "Gemini keeps one patch chunk per turn" "$gemini_prompt" \
      '^Patch chunk batch limit: 1$'
    assert_grep "Gemini chunk prompt uses read_file" "$gemini_prompt" \
      '^First assigned-patch action: use read_file to read 1 consecutive listed chunk in full'
    printf '1. Verify the large change.\n' > "$S/fix-plan.md"
    assert_exit "chunk prompt rejects a non-plan evidence manifest" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 21 sol plan-tests chunks \
      --plan "$S/fix-plan.md" --evidence "$manifest"

    python3 - "$manifest" "$SCRIPTS/rev-evidence.py" <<'PY'
import hashlib, json, pathlib, subprocess, sys
manifest_path=pathlib.Path(sys.argv[1]); script=sys.argv[2]; session=manifest_path.parent
m=json.load(open(manifest_path)); manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
for seat, assignment in m['assignments'].items():
    prompt=session / f'r21-{seat}.prompt.md'
    prompt.write_text(subprocess.check_output([script, 'render', str(manifest_path), seat], text=True))
    result=session / f'r21-{seat}.json'; result.write_text('{"summary":"checked","findings":[]}\n')
    exit_path=session / f'r21-{seat}.exit'; exit_path.write_text('0\n')
    stream=session / f'r21-{seat}.stream.ndjson'; stream.write_text('{}\n')
    context=m['source_context']['seats'][seat]
    assert not context['required_source_ranges']
    ranges=[{'path':row['path'],'line_start':row['line_start'],'line_end':row['line_end'],'origin':'packet'}
            for shard in context['shards'] for row in shard['ranges']]
    source_calls=0
    if context['source_read_required']:
        component=next(c for c in m['components'] if c['id'] == context['components'][0])
        ranges.append({'path':component['boundary'][0],'line_start':1,'line_end':1,'origin':'tool'})
        source_calls=1
    ranges.sort(key=lambda row:(row['path'],row['line_start'],row['line_end'],row['origin']))
    chunks=m['patch_sets'][assignment['patch_set']]['chunks']
    packet_bytes=sum(row['bytes'] for row in context['shards'])
    calls=len(chunks)+len(context['shards'])+source_calls
    audit={
        'schema_version':2,'status':'valid','narrow':assignment['scope'] != 'full',
        'adapter':assignment['adapter'],'prompt_sha256':hashlib.sha256(prompt.read_bytes()).hexdigest(),
        'stream_sha256':hashlib.sha256(stream.read_bytes()).hexdigest(),
        'result_sha256':hashlib.sha256(result.read_bytes()).hexdigest(),
        'evidence_manifest_sha256':manifest_hash,'violations':[],'tool_calls':calls,'tool_turns':calls,
        'tool_output_bytes':assignment['patch_bytes']+packet_bytes+source_calls,
        'max_tool_output_bytes':max([row['bytes'] for row in chunks]+[row['bytes'] for row in context['shards']]+[source_calls]),
        'recognized_tool_calls':calls,'source_read_calls':source_calls,'packet_shards':len(context['shards']),
        'packet_bytes':packet_bytes,'packet_ranges':sum(row['origin']=='packet' for row in ranges),
        'opened_source_ranges':sum(row['origin']=='tool' for row in ranges),'finding_citations':0,
        'required_source_ranges_covered':0,'required_source_range_proofs':[],
        'assigned_patch_sha256':assignment['patch_sha256'],'assigned_patch_bytes':assignment['patch_bytes'],
        'assigned_patch_lines':assignment['patch_lines'],'assigned_patch_reads':len(chunks),
        'assigned_patch_ranges':[],'patch_proof_mode':'chunks','patch_proof_calls':len(chunks),
        'patch_proof_turns':len(chunks),'patch_proof_visible_bytes':assignment['patch_bytes'],
        'expected_patch_chunks':len(chunks),'opened_patch_chunks':len(chunks),'source_ranges':ranges,
    }
    (session / f'r21-{seat}.read-audit.json').write_text(json.dumps(audit))
PY
    python3 - "$S/r21-sol.read-audit.json" <<'PY'
import json, sys
path=sys.argv[1]; audit=json.load(open(path)); audit['opened_patch_chunks']-=1
json.dump(audit,open(path,'w'))
PY
    python3 "$SCRIPTS/rev-evidence.py" receipt "$S" 21 >/dev/null 2>&1
    assert_eq "coverage receipt rejects an incomplete chunk proof" "$?" 2

    local saved_chunk
    saved_chunk=$(python3 - "$manifest" <<'PY'
import json, pathlib, sys
m=json.load(open(sys.argv[1])); a=m['assignments']['sol']; print(pathlib.Path(sys.argv[1]).parent / m['patch_sets'][a['patch_set']]['chunks'][0]['artifact'])
PY
) || return
    printf 'tamper\n' >> "$saved_chunk"
    python3 "$SCRIPTS/rev-evidence.py" verify "$manifest" >/dev/null 2>&1
    assert_eq "chunk artifact tampering invalidates the manifest" "$?" 2
    python3 - "$saved_chunk" <<'PY'
import pathlib, sys
path=pathlib.Path(sys.argv[1]); target=path.with_name('redirected.txt')
path.write_bytes(path.read_bytes()[:-7]); target.write_bytes(path.read_bytes())
path.unlink(); path.symlink_to(target)
PY
    python3 "$SCRIPTS/rev-evidence.py" verify "$manifest" >/dev/null 2>&1
    assert_eq "symlinked patch chunk invalidates the manifest" "$?" 2
  )
}

test_patch_chunk_decline_and_switch() {
  ( local R="$T/patch-chunk-decline-root" S="$T/patch-chunk-decline-session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R/src/wide.py" <<'PY'
import sys
with open(sys.argv[1], 'w') as stream:
    for index in range(480):
        stream.write(f'{index:04d}:' + 'x' * 110 + '\n')
PY
    local base manifest disabled
    base=$(git -C "$R" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/wide.py\n' > "$S/files.txt"; printf 'src/wide.py\n' > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 22 --phase discovery) || return
    assert_eq "chunk mode declines when it saves less than ten percent of reads" \
      "$(python3 - "$manifest" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['assignments']['sol']['patch_read_mode'])
PY
)" windows
    cp "$manifest" "$T/r22-evidence.manifest.valid.json"
    python3 "$SCRIPTS/rev-evidence.py" verify "$manifest" >/dev/null 2>&1
    assert_eq "schema 2 non-plan evidence remains valid" "$?" 0
    python3 - "$manifest" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1]); m=json.load(open(path)); m['schema_version']=1
path.write_text(json.dumps(m, sort_keys=True, ensure_ascii=True, indent=2)+'\n')
PY
    python3 "$SCRIPTS/rev-evidence.py" verify "$manifest" >/dev/null 2>"$T/schema1.err"
    assert_eq "schema 1 non-plan evidence is rejected" "$?" 2
    assert_grep "schema 1 rejection has a stable version error" "$T/schema1.err" \
      'invalid manifest session/version'
    cp "$T/r22-evidence.manifest.valid.json" "$manifest"
    python3 - "$manifest" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1]); m=json.load(open(path)); m['schema_version']=3
path.write_text(json.dumps(m, sort_keys=True, ensure_ascii=True, indent=2)+'\n')
PY
    python3 "$SCRIPTS/rev-evidence.py" verify "$manifest" >/dev/null 2>"$T/schema3-nonplan.err"
    assert_eq "schema 3 non-plan evidence is rejected" "$?" 2
    assert_grep "schema 3 non-plan rejection names the phase mismatch" \
      "$T/schema3-nonplan.err" 'manifest phase/version mismatch'
    cp "$T/r22-evidence.manifest.valid.json" "$manifest"
    python3 - "$manifest" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1]); m=json.load(open(path)); m['phase']='plan'
path.write_text(json.dumps(m, sort_keys=True, ensure_ascii=True, indent=2)+'\n')
PY
    python3 "$SCRIPTS/rev-evidence.py" verify "$manifest" >/dev/null 2>"$T/schema2-plan.err"
    assert_eq "schema 2 plan evidence is rejected" "$?" 2
    assert_grep "schema 2 plan rejection names the phase mismatch" \
      "$T/schema2-plan.err" 'manifest phase/version mismatch'
    cp "$T/r22-evidence.manifest.valid.json" "$manifest"
    disabled=$(REV_PATCH_CHUNKS=0 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 23 --phase discovery) || return
    assert_eq "REV_PATCH_CHUNKS disables chunk artifacts" \
      "$(python3 - "$disabled" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); print(','.join(sorted({a['patch_read_mode'] for a in m['assignments'].values()})), len(list(__import__('pathlib').Path(sys.argv[1]).parent.glob('r23-patch-*.txt'))))
PY
)" 'windows 0'
  )
}

test_patch_chunk_audit_contract() {
  ( local R="$T/patch-chunk-audit-root" S="$T/patch chunk audit session"
    mkrepo "$R"; mkdir -p "$R/src" "$S"
    python3 - "$R/src/large.py" <<'PY'
import sys
with open(sys.argv[1], 'w') as stream:
    for index in range(4200):
        stream.write(f'value_{index:04d} = {index:04d}\n')
PY
    local base manifest prompt
    base=$(git -C "$R" rev-parse HEAD)
    printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
      "$base" "$R" > "$S/scope.env"
    printf 'src/large.py\n' > "$S/files.txt"; printf 'src/large.py\n' > "$S/untracked.txt"
    printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"grok","adapter":"grok"},{"seat":"opus","adapter":"claude"},{"seat":"opus-2","adapter":"claude"}]}' > "$S/roster.json"
    manifest=$(REV_PATCH_CHUNKS=1 REV_SOURCE_CONTEXT=1 \
      python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 24 --phase discovery) || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 24 sol correctness chunk-audit --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r24-sol.json"

    write_transcript() {
      python3 - "$manifest" "$S/r24-sol.stream.ndjson" "$R" "$1" <<'PY'
import json, pathlib, shlex, sys
manifest = json.load(open(sys.argv[1])); out = pathlib.Path(sys.argv[2])
root = pathlib.Path(sys.argv[3]); mode = sys.argv[4]; session = pathlib.Path(sys.argv[1]).parent
assignment = manifest['assignments']['sol']
chunks = list(manifest['patch_sets'][assignment['patch_set']]['chunks'])
if mode == 'reorder':
    chunks[0], chunks[1] = chunks[1], chunks[0]
elif mode == 'missing':
    chunks = chunks[:-1]
events = []
def command(call_id, command_text, output):
    events.extend([
        {'type':'item.started','item':{'id':call_id,'type':'command_execution','command':command_text}},
        {'type':'item.completed','item':{'id':call_id,'type':'command_execution','command':command_text,
                                         'aggregated_output':output,'exit_code':0}},
    ])
def packets():
    for row in manifest['source_context']['seats']['sol']['shards']:
        path = session / row['artifact']
        command('packet-' + str(row['artifact']), "cat '" + str(path) + "'", path.read_text())
if mode == 'packet-first':
    packets()
if mode == 'search-first':
    command('search-first', "rg -n 'value_1' . | head -80", 'src/large.py:2:value_0001 = 0001\n')
for position, row in enumerate(chunks, 1):
    path = session / row['artifact']; content = path.read_text()
    if mode == 'replace' and position == 1:
        content = ('X' if content[:1] != 'X' else 'Y') + content[1:]
    if mode == 'oversized' and position == 1:
        content += 'z' * (33 * 1024)
    if mode == 'truncate' and position == 1:
        command('chunk-' + str(position), "sed -n '1,1p' '" + str(path) + "'",
                content.splitlines(keepends=True)[0])
    else:
        command('chunk-' + str(position), 'cat -- ' + shlex.quote(str(path)), content)
if mode == 'duplicate':
    row = chunks[0]; path = session / row['artifact']
    command('chunk-copy', 'cat -- ' + shlex.quote(str(path)), path.read_text())
if mode == 'unassigned':
    source = session / chunks[0]['artifact']; extra = session / 'r24-patch-p99-999.txt'
    extra.write_bytes(source.read_bytes())
    command('chunk-unassigned', 'cat -- ' + shlex.quote(str(extra)), extra.read_text())
if mode != 'packet-first':
    packets()
source = root / 'src/large.py'
if manifest['source_context']['seats']['sol']['source_read_required']:
    command('source', "sed -n '1,1p' 'src/large.py'", source.read_text().splitlines(keepends=True)[0])
with out.open('w') as stream:
    for event in events:
        stream.write(json.dumps(event) + '\n')
PY
    }

    write_transcript complete
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r24-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r24-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "ordered full chunk reads establish assigned patch coverage" "$?" 0
    assert_grep "chunk audit records chunk mode" "$S/r24-sol.read-audit.json" \
      '"patch_proof_mode":"chunks"'
    assert_grep "chunk audit records no line-window evidence" "$S/r24-sol.read-audit.json" \
      '"assigned_patch_ranges":\[\]'
    python3 - "$S/r24-sol.read-audit.json" "$manifest" <<'PY'
import json, sys
a=json.load(open(sys.argv[1])); m=json.load(open(sys.argv[2]))
assert a['expected_patch_chunks'] == a['opened_patch_chunks'] == a['patch_proof_calls']
assert 0 < a['patch_proof_turns'] <= a['patch_proof_calls']
assert a['patch_proof_visible_bytes'] > 0
chunk_artifacts = {row['artifact'] for value in m['patch_sets'].values() for row in value['chunks']}
assert all(row['path'] not in chunk_artifacts for row in a['source_ranges'])
PY
    assert_eq "chunk proof counters are internally consistent" "$?" 0

    local mode code
    for mode in missing reorder replace duplicate unassigned truncate oversized packet-first search-first; do
      case "$mode" in
        missing) code=missing-assigned-patch-chunk;;
        reorder) code=reordered-patch-chunks;;
        replace) code=assigned-patch-output-mismatch;;
        duplicate) code=duplicate-patch-chunk;;
        unassigned) code=unassigned-patch-chunk;;
        truncate) code=partial-patch-chunk;;
        oversized) code=tool-output-too-large;;
        packet-first) code=patch-chunk-read-order;;
        search-first) code=patch-chunk-read-order;;
      esac
      write_transcript "$mode"
      python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
        --raw "$S/r24-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
        --out "$S/r24-sol.read-audit.json" >/dev/null 2>&1
      assert_eq "$mode patch chunk transcript is rejected" "$?" 2
      assert_grep "$mode patch chunk rejection is stable" "$S/r24-sol.read-audit.json" \
        "\"code\":\"$code\""
    done

    local opus_prompt grok_prompt
    opus_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 24 opus correctness chunk-audit \
      --evidence "$manifest") || return
    grok_prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 24 grok correctness chunk-audit \
      --evidence "$manifest") || return
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r24-opus.json"
    python3 - "$manifest" "$S/r24-opus.stream.ndjson" "$R" <<'PY'
import json, pathlib, sys
m=json.load(open(sys.argv[1])); out=pathlib.Path(sys.argv[2]); root=pathlib.Path(sys.argv[3])
session=pathlib.Path(sys.argv[1]).parent; assignment=m['assignments']['opus']
chunks=m['patch_sets'][assignment['patch_set']]['chunks']; events=[]
def turn(identity, calls):
    events.append({'type':'assistant','message':{'id':identity,'content':[
        {'type':'tool_use','id':call_id,'name':name,'input':data}
        for call_id,name,data,_ in calls]}})
    events.append({'type':'user','message':{'content':[
        {'type':'tool_result','tool_use_id':call_id,'content':output}
        for call_id,_,_,output in calls]}})
for row in chunks[:-1]:
    path=session/row['artifact']
    turn('msg-'+str(row['index']), [('chunk-'+str(row['index']),'Read',{'file_path':str(path)},path.read_text())])
last=chunks[-1]; last_path=session/last['artifact']
turn('msg-final', [
    ('chunk-'+str(last['index']),'Read',{'file_path':str(last_path)},last_path.read_text()),
    ('search-same-turn','Bash',{'command':"rg -n 'value_1' . | head -80"},'src/large.py:2:value_0001 = 0001\n'),
])
for index,row in enumerate(m['source_context']['seats']['opus']['shards'],1):
    path=session/row['artifact']; turn('packet-'+str(index),[
        ('packet-call-'+str(index),'Read',{'file_path':str(path)},path.read_text())])
if m['source_context']['seats']['opus']['source_read_required']:
    path=root/'src/large.py'; turn('source-later',[
        ('source-call','Read',{'file_path':str(path),'offset':1,'limit':1},path.read_text().splitlines(keepends=True)[0])])
out.write_text(''.join(json.dumps(event)+'\n' for event in events))
PY
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r24-opus.stream.ndjson" --prompt "$opus_prompt" --root "$R" --session "$S" \
      --out "$S/r24-opus.read-audit.json" >/dev/null 2>&1
    assert_eq "Claude search parallel with the final chunk is rejected" "$?" 2
    assert_grep "Claude same-turn expansion has a stable chunk-order failure" \
      "$S/r24-opus.read-audit.json" '"code":"patch-chunk-read-order"'

    write_provider_batch() {
      python3 - "$manifest" "$S/r24-$1.stream.ndjson" "$R" "$1" "$2" <<'PY'
import json, pathlib, sys
m=json.load(open(sys.argv[1])); out=pathlib.Path(sys.argv[2]); root=pathlib.Path(sys.argv[3])
seat=sys.argv[4]; batch=int(sys.argv[5]); session=pathlib.Path(sys.argv[1]).parent
adapter='claude' if seat == 'opus' else 'grok'
assignment=m['assignments'][seat]; chunks=m['patch_sets'][assignment['patch_set']]['chunks']; events=[]
def emit(calls, identity):
    if adapter == 'claude':
        events.append({'type':'assistant','message':{'id':identity,'content':[
            {'type':'tool_use','id':call_id,'name':name,'input':data}
            for call_id,name,data,_ in calls]}})
        events.append({'type':'user','message':{'content':[
            {'type':'tool_result','tool_use_id':call_id,'content':output}
            for call_id,_,_,output in calls]}})
    else:
        for call_id,name,data,_ in calls:
            events.append({'type':'tool_call','toolCallId':call_id,'toolName':name,
                           'rawInput':data})
        for call_id,_,_,output in calls:
            events.append({'type':'tool_call_update','toolCallId':call_id,'status':'completed',
                           'rawOutput':output})
for start in range(0, len(chunks), batch):
    calls=[]
    for row in chunks[start:start + batch]:
        path=session/row['artifact']; data={'file_path':str(path)} if adapter == 'claude' else {'target_file':str(path)}
        name='Read' if adapter == 'claude' else 'read_file'
        content=path.read_text()
        if adapter == 'grok':
            content='\n'.join(str(index) + '\u2192' + line for index,line in enumerate(content.splitlines(),1))
        calls.append(('chunk-'+str(row['index']),name,data,content))
    emit(calls, 'patch-'+str(start))
context=m['source_context']['seats'][seat]
for index,row in enumerate(context['shards'],1):
    path=session/row['artifact']; data={'file_path':str(path)} if adapter == 'claude' else {'target_file':str(path)}
    name='Read' if adapter == 'claude' else 'read_file'; content=path.read_text()
    if adapter == 'grok':
        content='\n'.join(str(line) + '\u2192' + value for line,value in enumerate(content.splitlines(),1))
    emit([('packet-'+str(index),name,data,content)], 'packet-'+str(index))
if context['source_read_required']:
    path=root/'src/large.py'; raw=path.read_text().splitlines(keepends=True)[0]
    data={'file_path':str(path),'offset':1,'limit':1} if adapter == 'claude' else {
        'target_file':str(path),'offset':1,'limit':1}
    content='1\u2192'+raw.rstrip('\n') if adapter == 'grok' else '1\t'+raw.rstrip('\n')
    emit([('source', 'Read' if adapter == 'claude' else 'read_file', data, content)], 'source')
out.write_text(''.join(json.dumps(event)+'\n' for event in events))
PY
    }
    write_provider_batch opus 2
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r24-opus.stream.ndjson" --prompt "$opus_prompt" --root "$R" --session "$S" \
      --out "$S/r24-opus.read-audit.json" >/dev/null 2>&1
    assert_eq "Claude accepts two consecutive patch chunks in one turn" "$?" 0
    actual=$(python3 - "$S/r24-opus.read-audit.json" <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))
turns = row['patch_proof_turns']
calls = row['patch_proof_calls']
print('yes' if turns == (calls + 1) // 2 and turns < calls else 'no')
PY
)
    assert_eq "Claude batching halves patch proof turns" "$actual" "yes"
    write_provider_batch grok 2
    printf '%s\n' '{"summary":"checked","findings":[]}' > "$S/r24-grok.json"
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter grok \
      --raw "$S/r24-grok.stream.ndjson" --prompt "$grok_prompt" --root "$R" --session "$S" \
      --out "$S/r24-grok.read-audit.json" >/dev/null 2>&1
    assert_eq "Grok accepts two consecutive patch chunks in one turn" "$?" 0
    actual=$(python3 - "$S/r24-grok.read-audit.json" <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))
turns = row['patch_proof_turns']
calls = row['patch_proof_calls']
print('yes' if turns == (calls + 1) // 2 and turns < calls else 'no')
PY
)
    assert_eq "Grok batching halves patch proof turns" "$actual" "yes"
    write_provider_batch opus 3
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter claude \
      --raw "$S/r24-opus.stream.ndjson" --prompt "$opus_prompt" --root "$R" --session "$S" \
      --out "$S/r24-opus.read-audit.json" >/dev/null 2>&1
    assert_eq "three patch chunks in one Claude turn are rejected" "$?" 2
    assert_grep "oversized patch batch has a stable violation" "$S/r24-opus.read-audit.json" \
      '"code":"patch-chunk-batch-too-large"'

    write_transcript complete
    cat > "$S/r24-sol.json" <<'JSON'
{"summary":"checked","findings":[{"severity":"P1","file":"src/large.py","line_start":2000,"line_end":2000,"claim":"bad","evidence":"bad","suggested_fix":"fix","confidence":0.9}]}
JSON
    python3 "$SCRIPTS/lib/review-read-audit.py" audit --adapter codex \
      --raw "$S/r24-sol.stream.ndjson" --prompt "$prompt" --root "$R" --session "$S" \
      --out "$S/r24-sol.read-audit.json" >/dev/null 2>&1
    assert_eq "patch chunks do not establish source citation evidence" "$?" 2
    assert_grep "chunk-only citation is rejected" "$S/r24-sol.read-audit.json" \
      '"code":"unsubstantiated-finding-range"'
  )
}

test_patch_chunk_native_prefix_normalization() {
  python3 - "$SCRIPTS/lib/review-read-audit.py" <<'PY'
import importlib.util, sys
spec=importlib.util.spec_from_file_location('audit', sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
expected=b'alpha\nbeta\n'
assert module.delivered_matches_bytes('grok', 'read_file', '1\u2192alpha\n2\u2192beta', expected, 1)
assert module.delivered_matches_bytes('claude', 'Read', '1\talpha\n2\tbeta', expected, 1)
terminal_blank=b'alpha\n\n'
assert module.delivered_matches_bytes('claude', 'Read', '1\talpha\n2\t', terminal_blank, 1)
assert not module.delivered_matches_bytes('claude', 'Read', '1\talpha\n', terminal_blank, 1)
assert not module.delivered_matches_bytes('grok', 'read_file', '1\u2192alpha\n3\u2192beta', expected, 1)
assert not module.delivered_matches_bytes('claude', 'Read', '1\talpha\n2\tchanged', expected, 1)
PY
  assert_eq "native Claude and Grok prefixes preserve exact chunk bytes" "$?" 0
}
