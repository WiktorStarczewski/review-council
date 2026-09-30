"""Normalize reported usage and deduplicate native assistant request records."""

import json
import math
import re
import shlex
from pathlib import Path


TERMINAL_TYPES = {"result", "turn.completed", "end"}
USAGE_FIELDS = (
    "input_tokens", "uncached_input_tokens", "output_tokens", "reasoning_output_tokens",
    "processed_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "cache_read_input_tokens", "cache_write_5m_input_tokens", "cache_write_1h_input_tokens",
    "cost_usd", "cost_usd_known_calls", "cost_usd_unknown_calls", "unidentified_terminal_calls",
)


def number(value, integer=False):
    if isinstance(value, bool):
        raise ValueError("boolean usage metric")
    if integer:
        if not isinstance(value, int) or value < 0:
            raise ValueError("invalid integer usage metric")
        return value
    if not isinstance(value, (int, float)):
        raise ValueError("invalid numeric usage metric")
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError("invalid finite usage metric") from error
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid finite usage metric")
    return value


def empty_usage():
    return {"calls": 0, **{key: 0.0 if key == "cost_usd" else 0 for key in USAGE_FIELDS}}


def add_usage(target, usage):
    target["calls"] += 1
    for key in USAGE_FIELDS:
        target[key] += usage[key]


def record_usage(record, adapter=None):
    inferred = ("gemini" if isinstance(record.get("stats"), dict) else {
        "assistant": "claude", "result": "claude", "turn.completed": "codex", "end": "grok",
    }.get(record.get("type")))
    provider = adapter or inferred or "unknown"
    shape = adapter if adapter in {"claude", "codex", "grok", "gemini"} else inferred
    container = "stats" if shape == "gemini" else "usage"
    usage = record.get(container, {})
    if not isinstance(usage, dict):
        raise ValueError("invalid usage object")
    for key in (
        "input_tokens", "output_tokens", "processed_tokens", "cached_input_tokens",
        "cache_write_input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
        "reasoning_output_tokens", "total_tokens",
    ):
        if key in usage:
            number(usage[key], integer=True)
    details = {}
    for key, fields in (
        ("output_tokens_details", ("thinking_tokens", "reasoning_tokens")),
        ("cache_creation", ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")),
    ):
        detail = usage.get(key, {})
        if not isinstance(detail, dict):
            raise ValueError("invalid usage detail object")
        details[key] = {field: number(detail.get(field, 0), integer=True) for field in fields}
    cached = usage.get("cached_input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    cache_detail = details["cache_creation"]
    write_5m = cache_detail["ephemeral_5m_input_tokens"]
    write_1h = cache_detail["ephemeral_1h_input_tokens"]
    write = usage.get("cache_write_input_tokens", usage.get(
        "cache_creation_input_tokens", write_5m + write_1h))
    if write_5m + write_1h > write:
        raise ValueError("cache creation detail exceeds cache write token count")
    output = usage.get("output_tokens", 0)
    output_detail = details["output_tokens_details"]
    reasoning = usage.get("reasoning_output_tokens", usage.get("output_tokens_details", {}).get(
        "reasoning_tokens", output_detail["thinking_tokens"]))
    if max(reasoning, *output_detail.values()) > output:
        raise ValueError("reasoning token count exceeds output token count")
    if "total_tokens" in usage and usage["total_tokens"] < output:
        raise ValueError("total token count is below output token count")
    raw_input = usage.get("input_tokens", 0)
    if shape == "claude":
        inputs = raw_input + write + read
        uncached = raw_input
    else:
        inputs = (usage["total_tokens"] - output if shape not in {"codex", "gemini"}
                  and "total_tokens" in usage else raw_input)
        if shape not in {"codex", "gemini"} and "total_tokens" not in usage:
            inputs += read + write
        uncached = inputs - max(cached, read) - write
        if uncached < 0:
            raise ValueError("cached token count exceeds input token count")
    costs = [record.get("total_cost_usd"), usage.get("cost_usd"), record.get("cost_usd")]
    for cost in costs:
        if cost is not None:
            number(cost)
    cost = next((value for value in costs if value is not None), None)
    return {
        "provider": provider, "input_tokens": inputs, "uncached_input_tokens": uncached,
        "output_tokens": output, "reasoning_output_tokens": reasoning,
        "processed_tokens": inputs + output, "cached_input_tokens": cached,
        "cache_write_input_tokens": write, "cache_read_input_tokens": read,
        "cache_write_5m_input_tokens": write_5m, "cache_write_1h_input_tokens": write_1h,
        "cost_usd": number(cost) if cost is not None else 0.0,
        "cost_usd_known_calls": int(cost is not None), "cost_usd_unknown_calls": int(cost is None),
        "unidentified_terminal_calls": 0,
    }


def read_stream(path, adapter=None):
    terminal = None
    messages = {}
    identities = set()
    invalid = []
    try:
        with path.open(errors="replace") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    invalid.append({"stream": path.name, "line": line_no, "reason": "malformed JSON record"})
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("type") in TERMINAL_TYPES:
                    terminal = record
                if record.get("type") != "assistant":
                    continue
                message = record.get("message")
                if not isinstance(message, dict) or "usage" not in message:
                    continue
                identity = message.get("id")
                if not isinstance(identity, str) or not identity:
                    invalid.append({"stream": path.name, "line": line_no, "reason": "missing message identity"})
                    continue
                identities.add(identity)
                try:
                    item = record_usage({"type": "assistant", "usage": message["usage"]}, adapter)
                except (TypeError, ValueError) as error:
                    invalid.append({"stream": path.name, "line": line_no, "reason": str(error)})
                    continue
                entry = {"usage": item, "content": message.get("content", [])}
                previous = messages.get(identity)
                if previous:
                    entry["content"] = list_content(previous["content"]) + list_content(entry["content"])
                    if previous["usage"]["output_tokens"] > item["output_tokens"]:
                        entry["usage"] = previous["usage"]
                messages[identity] = entry
    except OSError:
        invalid.append({"stream": path.name, "reason": "unreadable usage stream"})
    item = None
    if terminal is not None:
        try:
            parsed = record_usage(terminal, adapter)
            if parsed["processed_tokens"] or parsed["cost_usd_known_calls"]:
                item = parsed
        except (TypeError, ValueError) as error:
            invalid.append({"stream": path.name, "reason": str(error)})
    return item, messages, identities, invalid


def list_content(value):
    return value if isinstance(value, list) else []


def reviewer_streams(streams):
    parsed = {path: read_stream(path, adapter) for path, adapter in streams}
    terminal_ids = set().union(*(ids for item, _, ids, _ in parsed.values() if item))
    leaf_ids = set().union(*(ids for _, _, ids, _ in parsed.values()))
    terminal_owners = {}
    for path, (item, _, identities, _) in parsed.items():
        if item is None:
            continue
        item["unidentified_terminal_calls"] = int(not identities)
        if identities:
            identity = frozenset(identities)
            previous = terminal_owners.get(identity)
            if previous is None or item["output_tokens"] >= parsed[previous][0]["output_tokens"]:
                terminal_owners[identity] = path
    suppressed = {path for path, (item, _, ids, _) in parsed.items()
                  if item is not None and ids and terminal_owners[frozenset(ids)] != path}
    messages = {}
    for path, (item, rows, _, _) in parsed.items():
        if item is not None:
            continue
        for identity, entry in rows.items():
            if identity in terminal_ids:
                continue
            previous = messages.get(identity)
            if previous is None or entry["usage"]["output_tokens"] >= previous[1]["usage"]["output_tokens"]:
                messages[identity] = (path, entry)
    native = {}
    for path, entry in messages.values():
        total = native.setdefault(path, empty_usage())
        total["provider"] = entry["usage"]["provider"]
        add_usage(total, entry["usage"])
    results = {}
    for path, (item, _, _, invalid) in parsed.items():
        if path in suppressed:
            item = None
        elif item is None and path in native:
            item = native[path]
            item["cost_usd_known_calls"] = int(item["cost_usd_unknown_calls"] == 0)
            item["cost_usd_unknown_calls"] = int(not item["cost_usd_known_calls"])
        results[path] = (item, invalid)
    return results, leaf_ids


def command_tokens(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def council_command(command, sessions, operations):
    if not isinstance(command, str):
        return False
    groups = [[]]
    for token in command_tokens(command):
        if token and all(char in ";&|()\n" for char in token):
            groups.append([])
        else:
            groups[-1].append(token)
    for tokens in groups:
        while tokens and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0])
                          or Path(tokens[0]).name in {"env", "exec"}):
            tokens = tokens[1:]
        if tokens and Path(tokens[0]).name in {"bash", "sh", "python", "python3"}:
            tokens = tokens[1:]
        if not tokens or Path(tokens[0]).name not in operations:
            continue
        for token in tokens[1:]:
            value = token.split("=", 1)[-1] if token.startswith("--") else token
            if not value.startswith("/"):
                continue
            try:
                path = Path(value).resolve()
            except (OSError, ValueError):
                continue
            if any(path == session or session in path.parents for session in sessions):
                return True
    return False


def council_content(content, sessions, operations):
    return any(isinstance(block, dict) and block.get("type") == "tool_use"
               and isinstance(block.get("input"), dict)
               and any(council_command(block["input"].get(key), sessions, operations)
                       for key in ("command", "cmd")) for block in list_content(content))


def host_usage(paths, sessions, leaf_ids, operations):
    unique_paths = list(dict.fromkeys(paths))
    messages = {}
    invalid = []
    for path in unique_paths:
        _, rows, _, errors = read_stream(path)
        invalid.extend(errors)
        for identity, entry in rows.items():
            linked = council_content(entry["content"], sessions, operations)
            previous = messages.get(identity)
            if previous:
                linked = linked or previous["linked"]
                if previous["usage"]["output_tokens"] > entry["usage"]["output_tokens"]:
                    entry = previous
            messages[identity] = {"usage": entry["usage"], "linked": linked}
    overlap = messages.keys() & leaf_ids
    envelope, council = empty_usage(), empty_usage()
    for identity, entry in messages.items():
        if identity in overlap:
            continue
        add_usage(envelope, entry["usage"])
        if entry["linked"]:
            add_usage(council, entry["usage"])
    return {
        "files": len(unique_paths), "duplicate_inputs": len(paths) - len(unique_paths),
        "leaf_overlap_messages": len(overlap), "envelope": envelope,
        "council_operations": council, "invalid_usage": invalid,
        "attribution": "Deduplicated supplied host envelopes include mixed work and exclude leaf mirrors; Council operations require an exact session path and script invocation.",
        "cost_basis": "Reported USD only; credits, subscription quota and unreported dollars are unknown.",
    }
