#!/usr/bin/env python3
"""Summarise a codex `--json`, grok `--output-format streaming-json` or gemini `-o stream-json` event stream.

Usage: stream-summary.py <codex|grok|gemini> <out.json>
  stdin:  NDJSON events, one per line, as the CLI emits them
  stdout: one short line per event that matters (unbuffered, so a status tick can read it live)
  grok:   the final {"type":"end"} record's structuredOutput is written to <out.json>
  gemini: the outermost {…} in the last assistant message (fences stripped) is written to <out.json>
Unknown or malformed lines are echoed clipped, never dropped silently.
"""
import json
import re
import sys

kind, out = sys.argv[1], sys.argv[2]
text_buf = []
last_message = ''


def clip(s, n=160):
    s = str(s).replace('\n', ' ')
    return s if len(s) <= n else s[:n] + '…'


def emit(line):
    print(line, flush=True)


def flush_text():
    if text_buf:
        emit(f"text: {clip(''.join(text_buf))}")
        text_buf.clear()


def outermost_object(text):
    """The JSON object a model wrapped in prose and/or a ``` fence, or None if there isn't one."""
    fenced = re.findall(r'```(?:[A-Za-z0-9_-]*)\s*\n(.*?)```', text, re.S)
    for body in (fenced[-1] if fenced else text, text):
        i, j = body.find('{'), body.rfind('}')
        if i == -1 or j <= i:
            continue
        try:
            obj = json.loads(body[i:j + 1])
        except Exception:  # noqa: BLE001 — not JSON after all; the wrapper reports "no findings"
            continue
        if isinstance(obj, dict):
            return obj
    return None


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        e = json.loads(raw)
    except Exception:
        flush_text()
        emit(clip(raw))
        continue
    t = e.get('type', '')
    if kind == 'codex':
        item = e.get('item') or {}
        it = item.get('type')
        if t == 'item.started' and it == 'command_execution':
            emit(f"exec: {clip(item.get('command', ''))}")
        elif t == 'item.completed' and it == 'command_execution':
            emit(f"done: exit={item.get('exit_code', '?')} {clip(item.get('command', ''), 80)}")
        elif t == 'item.completed' and it == 'agent_message':
            emit(f"text: {clip(item.get('text', ''))}")
        elif t == 'item.completed' and it == 'error':
            emit(f"error: {clip(item.get('message', item))}")
        elif t == 'turn.completed':
            emit(f"end usage={json.dumps(e.get('usage', {}))}")
        elif t == 'error':
            emit(f"error: {clip(e.get('message', e))}")
    elif kind == 'claude':
        if t == 'assistant':
            for block in (e.get('message') or {}).get('content', []):
                if block.get('type') == 'tool_use' and block.get('name') in ('Read', 'Glob', 'Grep', 'Bash'):
                    emit(f"tool_call {block.get('name', '')}: {clip(json.dumps(block.get('input', {})))}")
                elif block.get('type') == 'text':
                    emit(f"text: {clip(block.get('text', ''))}")
        elif t == 'result':
            if e.get('is_error'):
                emit(f"error: {clip(e.get('errors') or e.get('result') or e.get('subtype'))}")
            else:
                obj = e.get('structured_output')
                if isinstance(obj, dict):
                    with open(out, 'w') as f:
                        json.dump(obj, f)
            emit(f"end status={e.get('subtype')} turns={e.get('num_turns')}")
        elif t == 'error':
            emit(f"error: {clip(e.get('message', e))}")
    elif kind == 'gemini':
        # Shape per the gemini CLI's documented `-o stream-json` NDJSON — assumed, not observed: there is
        # no gemini on the box this was written on. tests/fixtures/gemini-stream.ndjson is the reference:
        # {"type":"tool_use","tool_name":…,"parameters":{…}} · {"type":"message","role":"assistant","content":…}
        # · {"type":"result","status":…}. Anything else falls through to the clipped-echo path below.
        if t == 'tool_use':
            p = e.get('parameters') or {}
            detail = ''
            if isinstance(p, dict):
                for k in ('command', 'path', 'file_path', 'absolute_path', 'pattern', 'query'):
                    if p.get(k):
                        detail = p[k]
                        break
                else:
                    detail = json.dumps(p)
            emit(f"tool_call {e.get('tool_name', '')}: {clip(detail)}")
        elif t == 'message' and e.get('role') == 'assistant':
            c = e.get('content', '')
            c = c if isinstance(c, str) else json.dumps(c)
            last_message = c
            emit(f"text: {clip(c)}")
        elif t == 'result':
            emit(f"end status={e.get('status')}")
        elif t == 'error':
            emit(f"error: {clip(e.get('message', e))}")
        # init / tool_result / thought / usage: intentionally silent
    else:
        if t == 'text':
            text_buf.append(str(e.get('data', '')))
            continue
        flush_text()
        if t == 'tool_call':
            emit(f"tool_call {e.get('toolName', '')}: {clip(e.get('title', ''))}")
        elif t == 'end':
            so = e.get('structuredOutput')
            if so is not None:
                with open(out, 'w') as f:
                    json.dump(so, f)
            emit(f"end stopReason={e.get('stopReason')} turns={e.get('num_turns')} cost={e.get('total_cost_usd')}")
        elif t == 'error':
            emit(f"error: {clip(e.get('message', e))}")
        # thought / tool_call_update / usage / available_commands: intentionally silent
flush_text()

if kind == 'gemini' and last_message:
    # gemini has no --output-schema: the answer is prose that ends in the JSON object we asked for.
    obj = outermost_object(last_message)
    if obj is not None:
        with open(out, 'w') as f:
            json.dump(obj, f)
