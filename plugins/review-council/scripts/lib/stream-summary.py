#!/usr/bin/env python3
"""Summarise a codex `--json` or grok `--output-format streaming-json` event stream.

Usage: stream-summary.py <codex|grok> <out.json>
  stdin:  NDJSON events, one per line, as the CLI emits them
  stdout: one short line per event that matters (unbuffered, so a status tick can read it live)
  grok:   the final {"type":"end"} record's structuredOutput is written to <out.json>
Unknown or malformed lines are echoed clipped, never dropped silently.
"""
import json
import sys

kind, out = sys.argv[1], sys.argv[2]
text_buf = []


def clip(s, n=160):
    s = str(s).replace('\n', ' ')
    return s if len(s) <= n else s[:n] + '…'


def emit(line):
    print(line, flush=True)


def flush_text():
    if text_buf:
        emit(f"text: {clip(''.join(text_buf))}")
        text_buf.clear()


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
