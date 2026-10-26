"""Normalize reported usage and deduplicate native assistant request records."""

import json
import math
import re
import shlex
from pathlib import Path


TERMINAL_TYPES = {"result", "turn.completed", "end"}
SDK_USAGE_FIELDS = {
    "inputTokens": "input_tokens", "outputTokens": "output_tokens",
    "totalTokens": "total_tokens", "cacheReadTokens": "cache_read_input_tokens",
    "cacheWriteTokens": "cache_write_input_tokens", "reasoningTokens": "reasoning_output_tokens",
    "costUsd": "cost_usd",
}
USAGE_FIELDS = (
    "input_tokens", "uncached_input_tokens", "uncached_input_unknown_calls",
    "output_tokens", "reasoning_output_tokens",
    "processed_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "cache_read_input_tokens", "cache_write_5m_input_tokens", "cache_write_1h_input_tokens",
    "cost_usd", "cost_usd_known_calls", "cost_usd_unknown_calls", "unidentified_terminal_calls",
)
CODEX_REQUIRED_COUNTER_FIELDS = ("input_tokens", "output_tokens")
CODEX_OPTIONAL_COUNTER_FIELDS = (
    "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens",
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
    target["calls"] += usage.get("calls", 1)
    for key in USAGE_FIELDS:
        target[key] += usage[key]


def record_usage(record, adapter=None):
    inferred = ("gemini" if isinstance(record.get("stats"), dict) else {
        "assistant": "claude", "result": "claude", "turn.completed": "codex", "end": "grok",
    }.get(record.get("type")))
    provider = adapter or inferred or "unknown"
    shape = adapter if adapter in {"claude", "codex", "grok", "gemini", "cursor-sdk"} else inferred
    container = "stats" if shape == "gemini" else "usage"
    usage = record.get(container, {})
    if not isinstance(usage, dict):
        raise ValueError("invalid usage object")
    if shape == "cursor-sdk":
        usage = dict(usage)
        for source, target in SDK_USAGE_FIELDS.items():
            if source in usage:
                if target in usage and usage[target] != usage[source]:
                    raise ValueError("conflicting SDK usage metrics")
                usage[target] = usage[source]
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
        inputs = (usage["total_tokens"] - output if "total_tokens" in usage
                  and (shape not in {"codex", "gemini", "cursor-sdk"}
                       or shape == "cursor-sdk" and "input_tokens" not in usage) else raw_input)
        if shape not in {"codex", "gemini", "cursor-sdk"} and "total_tokens" not in usage:
            inputs += read + write
        uncached = inputs - max(cached, read) - write
        if uncached < 0:
            raise ValueError("cached token count exceeds input token count")
    if shape == "cursor-sdk" and "total_tokens" in usage and usage["total_tokens"] != inputs + output:
        raise ValueError("inconsistent SDK total token count")
    costs = [record.get("total_cost_usd"), usage.get("cost_usd"), record.get("cost_usd")]
    for cost in costs:
        if cost is not None:
            number(cost)
    cost = next((value for value in costs if value is not None), None)
    return {
        "provider": provider, "input_tokens": inputs, "uncached_input_tokens": uncached,
        "uncached_input_unknown_calls": 0,
        "output_tokens": output, "reasoning_output_tokens": reasoning,
        "processed_tokens": inputs + output, "cached_input_tokens": cached,
        "cache_write_input_tokens": write, "cache_read_input_tokens": read,
        "cache_write_5m_input_tokens": write_5m, "cache_write_1h_input_tokens": write_1h,
        "cost_usd": number(cost) if cost is not None else 0.0,
        "cost_usd_known_calls": int(cost is not None), "cost_usd_unknown_calls": int(cost is None),
        "unidentified_terminal_calls": 0,
    }


def codex_cumulative_delta(record, previous):
    """Convert exec's cumulative thread snapshot into a validated turn delta."""
    usage = record.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("invalid usage object")
    if not set(CODEX_REQUIRED_COUNTER_FIELDS) <= usage.keys():
        raise ValueError("Codex cumulative usage is missing input or output counters")

    current = {key: number(usage[key], integer=True) for key in CODEX_REQUIRED_COUNTER_FIELDS}
    warnings = []
    uncached_unknown = False
    invalid_optional = set()
    for key in CODEX_OPTIONAL_COUNTER_FIELDS:
        previous_value = previous.get(key) if previous is not None else None
        if key not in usage:
            current[key] = previous_value
            if key in {"cached_input_tokens", "cache_write_input_tokens"}:
                uncached_unknown = True
            if previous_value is not None:
                warnings.append("Codex cumulative usage omitted optional counter: " + key)
            continue
        try:
            current[key] = number(usage[key], integer=True)
        except ValueError:
            current[key] = previous_value
            invalid_optional.add(key)
            warnings.append("Codex cumulative usage has invalid optional counter: " + key)
            if key in {"cached_input_tokens", "cache_write_input_tokens"}:
                uncached_unknown = True

    if previous is not None and any(
            current[key] < previous[key] for key in CODEX_REQUIRED_COUNTER_FIELDS):
        rebased = dict(current)
        for key in CODEX_OPTIONAL_COUNTER_FIELDS:
            if key not in usage:
                rebased[key] = None
        return None, rebased, "Codex cumulative usage counter reset; turn usage is unknown"

    delta = {}
    for key in CODEX_REQUIRED_COUNTER_FIELDS:
        delta[key] = current[key] - (previous[key] if previous is not None else 0)
    for key in CODEX_OPTIONAL_COUNTER_FIELDS:
        value = current[key]
        prior = previous.get(key) if previous is not None else None
        if value is None:
            delta[key] = 0
        elif previous is None:
            delta[key] = value
        elif prior is None:
            delta[key] = 0
            warnings.append("Codex cumulative usage cannot derive optional counter baseline: " + key)
            if key in {"cached_input_tokens", "cache_write_input_tokens"}:
                uncached_unknown = True
        elif value < prior:
            delta[key] = 0
            warnings.append("Codex cumulative usage optional counter reset: " + key)
            if key in {"cached_input_tokens", "cache_write_input_tokens"}:
                uncached_unknown = True
        else:
            delta[key] = value - prior

    clean_usage = {key: value for key, value in usage.items()
                   if key not in {"cost_usd", "total_cost_usd"}}
    for key in CODEX_OPTIONAL_COUNTER_FIELDS:
        if key not in clean_usage or key in invalid_optional:
            clean_usage[key] = current[key] if current[key] is not None else 0
    # Codex exec maps ThreadTokenUsage.total into every turn.completed event.
    record_usage({"type": "turn.completed", "usage": clean_usage}, "codex")
    try:
        parsed = record_usage({"type": "turn.completed", "usage": delta}, "codex")
    except (TypeError, ValueError) as error:
        return None, current, "Codex cumulative usage delta is invalid: " + str(error)
    if uncached_unknown:
        parsed["uncached_input_tokens"] = 0
        parsed["uncached_input_unknown_calls"] = 1
    return parsed, current, "; ".join(dict.fromkeys(warnings)) or None


def read_stream(path, adapter=None):
    terminal = None
    codex_turns = []
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
                    if record.get("type") == "turn.completed" and adapter in (None, "codex"):
                        codex_turns.append((line_no, record))
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
    terminal_rows = codex_turns or ([(None, terminal)] if terminal is not None else [])
    if codex_turns:
        total = empty_usage()
        previous = None
        for line_no, record in codex_turns:
            usage = record.get("usage")
            has_cost = (isinstance(usage, dict)
                        and any(key in usage for key in ("cost_usd", "total_cost_usd")))
            if has_cost or any(key in record for key in ("cost_usd", "total_cost_usd")):
                invalid.append({"stream": path.name, "line": line_no,
                                "reason": "Codex exec cost scope is not defined per turn"})
            try:
                parsed, current, error = codex_cumulative_delta(record, previous)
                if current is not None:
                    previous = current
                if error:
                    invalid.append({"stream": path.name, "line": line_no, "reason": error})
                if parsed is None:
                    unknown = empty_usage()
                    unknown["calls"] = 1
                    unknown["cost_usd_unknown_calls"] = 1
                    unknown["uncached_input_unknown_calls"] = 1
                    add_usage(total, unknown)
                else:
                    add_usage(total, parsed)
            except (TypeError, ValueError) as error:
                invalid.append({"stream": path.name, "line": line_no, "reason": str(error)})
                unknown = empty_usage()
                unknown["calls"] = 1
                unknown["cost_usd_unknown_calls"] = 1
                unknown["uncached_input_unknown_calls"] = 1
                add_usage(total, unknown)
            if not identities:
                total["unidentified_terminal_calls"] += 1
        if total["calls"]:
            total["provider"] = "codex"
            item = total
    elif terminal_rows:
        total = empty_usage()
        provider = None
        for line_no, record in terminal_rows:
            try:
                parsed = record_usage(record, adapter)
                sdk_reported = (adapter == "cursor-sdk" and isinstance(record.get("usage"), dict)
                                and any(key in record["usage"]
                                        for key in (*SDK_USAGE_FIELDS, *SDK_USAGE_FIELDS.values())))
                if parsed["processed_tokens"] or parsed["cost_usd_known_calls"] or sdk_reported:
                    provider = parsed["provider"]
                    add_usage(total, parsed)
            except (TypeError, ValueError) as error:
                entry = {"stream": path.name, "reason": str(error)}
                if line_no is not None:
                    entry["line"] = line_no
                invalid.append(entry)
        if total["calls"]:
            total["provider"] = provider
            item = total
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
        item["unidentified_terminal_calls"] = item.get("calls", 1) if not identities else 0
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
