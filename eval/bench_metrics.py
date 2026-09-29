"""Collect comparable usage and paired benchmark measurements."""

import importlib.util
import json
from pathlib import Path


_NORMALIZER_PATH = (Path(__file__).resolve().parents[1]
                    / "plugins/review-council/scripts/lib/usage.py")
_TOOL_TYPES = {"command_execution", "mcp_tool_call", "web_search"}
_TOKEN_METRICS = ("input_tokens", "cached_input_tokens", "uncached_input_tokens",
                  "output_tokens", "reasoning_output_tokens", "processed_tokens")
_METRICS = ("wall_seconds", *_TOKEN_METRICS, "estimated_credits", "prompt_words", "prompt_bytes")


def _load_normalizer(path):
    spec = importlib.util.spec_from_file_location("benchmark_usage", path)
    normalizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(normalizer)
    return normalizer


_NORMALIZER = _load_normalizer(_NORMALIZER_PATH)


def _retain(errors, message):
    if len(errors) < 20:
        errors.append(str(message)[:500])


def _terminal_usage(terminal, normalizer):
    raw = terminal.get("usage")
    if not isinstance(raw, dict):
        raise ValueError("invalid usage object")
    missing = [key for key in ("input_tokens", "output_tokens") if key not in raw]
    if missing:
        raise ValueError("missing reported " + ", ".join(missing))
    usage = normalizer.record_usage(terminal, "codex")
    usage["cache_reported"] = "cached_input_tokens" in raw
    details = raw.get("output_tokens_details", {})
    usage["reasoning_reported"] = ("reasoning_output_tokens" in raw
                                   or "reasoning_tokens" in details
                                   or "thinking_tokens" in details)
    if not usage["cache_reported"]:
        usage["cached_input_tokens"] = None
        usage["uncached_input_tokens"] = None
    if not usage["reasoning_reported"]:
        usage["reasoning_output_tokens"] = None
    if not usage["cost_usd_known_calls"]:
        usage["cost_usd"] = None
    return usage


def measure_stream(path: Path, collector_path=None) -> dict:
    """Normalize one ordinary execution with the common usage collector."""
    normalizer = _load_normalizer(collector_path) if collector_path is not None else _NORMALIZER
    terminal = None
    terminal_count = 0
    tool_ids = set()
    errors, provider_errors = [], []
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    _retain(errors, f"line {line_no}: malformed JSON record")
                    continue
                if not isinstance(record, dict):
                    _retain(errors, f"line {line_no}: record is not an object")
                    continue
                kind = record.get("type")
                if not isinstance(kind, str):
                    _retain(errors, f"line {line_no}: invalid event type")
                    continue
                if kind in normalizer.TERMINAL_TYPES:
                    terminal_count += 1
                    if terminal is None:
                        terminal = record
                if kind in {"error", "turn.failed"}:
                    detail = record.get("message", record.get("error", "provider error"))
                    if isinstance(detail, dict):
                        detail = detail.get("message", json.dumps(detail, ensure_ascii=True))
                    _retain(provider_errors, f"{kind}: {detail}")
                item = record.get("item")
                if kind != "item.completed" or not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if not isinstance(item_type, str):
                    _retain(errors, f"line {line_no}: invalid item type")
                    continue
                if item_type not in _TOOL_TYPES:
                    continue
                identity = item.get("id")
                if isinstance(identity, str) and identity:
                    tool_ids.add(identity)
                else:
                    _retain(errors, f"line {line_no}: completed tool lacks item identity")
    except OSError:
        _retain(errors, "unreadable usage stream")
    usage = None
    if terminal_count != 1:
        _retain(errors, f"expected one terminal usage envelope, found {terminal_count}")
    elif terminal.get("type") != "turn.completed":
        _retain(errors, "unsupported terminal type: " + terminal["type"])
    else:
        try:
            usage = _terminal_usage(terminal, normalizer)
        except (TypeError, ValueError) as error:
            _retain(errors, str(error))
    return {"usage": usage, "tool_calls": len(tool_ids), "terminal_count": terminal_count,
            "errors": errors, "provider_errors": provider_errors}


def credit_estimate(usage, rate_card: dict):
    """Estimate Standard credits only when input, cache and output are reported."""
    if not isinstance(usage, dict) or usage.get("cache_reported") is False:
        return None
    try:
        inputs, cached, output = (_NORMALIZER.number(usage.get(key), integer=True)
                                  for key in ("input_tokens", "cached_input_tokens", "output_tokens"))
    except (TypeError, ValueError):
        return None
    if cached > inputs:
        return None
    rates = [_NORMALIZER.number(rate_card[key])
             for key in ("input_per_million", "cached_per_million", "output_per_million")]
    return ((inputs - cached) * rates[0] + cached * rates[1] + output * rates[2]) / 1000000


def _metric_value(row, metric):
    if row is None:
        return None
    source = row.get("usage") if metric in _TOKEN_METRICS else row
    return source.get(metric) if isinstance(source, dict) else None


def paired_deltas(rows: list) -> list:
    """Keep raw paired metrics and calculate reductions for valid pairs only."""
    cases = {}
    for row in rows:
        variant = row["variant"]
        if variant not in ("baseline", "candidate"):
            raise ValueError("unsupported benchmark variant: " + str(variant))
        case = row["case"]
        pair = cases.setdefault(case, {})
        if variant in pair:
            raise ValueError(f"duplicate benchmark case/variant: {case}/{variant}")
        pair[variant] = row
    result = []
    for case, pair in cases.items():
        baseline, candidate = pair.get("baseline"), pair.get("candidate")
        valid_pair = (baseline is not None and candidate is not None
                      and baseline.get("valid") is True and candidate.get("valid") is True)
        metrics = {}
        for metric in _METRICS:
            before, after = _metric_value(baseline, metric), _metric_value(candidate, metric)
            reduction = None
            if valid_pair and before is not None and after is not None and before > 0:
                reduction = (before - after) / before * 100
            metrics[metric] = {"baseline": before, "candidate": after,
                               "reduction_percent": reduction}
        result.append({"case": case, "baseline_status": baseline.get("status") if baseline else None,
                       "candidate_status": candidate.get("status") if candidate else None,
                       "valid_pair": valid_pair, "metrics": metrics})
    return result
