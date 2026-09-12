#!/usr/bin/env python3
"""Summarize prompt size, result yield, and terminal provider usage."""

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path


TERMINAL_TYPES = {"result", "turn.completed", "end"}
REVIEW_ARTIFACT = re.compile(r"^r\d+[a-z]*-", re.IGNORECASE)
VALIDATOR = Path(__file__).resolve().parent / "lib" / "validate-findings.py"
EVIDENCE_SCRIPT = Path(__file__).resolve().parent / "rev-evidence.py"
USAGE_FIELDS = (
    "input_tokens", "output_tokens", "processed_tokens", "cached_input_tokens",
    "cache_write_input_tokens", "cache_read_input_tokens", "cost_usd",
)


def session_directory(value):
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise argparse.ArgumentTypeError(
            f"{value}: session directory does not exist or cannot be resolved"
        ) from error
    if not resolved.is_dir():
        raise argparse.ArgumentTypeError(f"{value}: session path is not a directory")
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise argparse.ArgumentTypeError(f"{value}: session directory is not readable and traversable")
    return resolved


def is_plan(path):
    name = path.name.lower()
    if re.match(r"^r\d+x-", name):
        return False
    if re.match(r"^r\d+pf?-", name):
        return True
    return re.match(r"^r\d+-plan-", name) is not None


def artifact_key(path):
    name = path.name
    if ".stream." in name:
        name = name.split(".stream.", 1)[0]
    elif name.endswith(".prompt.md"):
        name = name[:-len(".prompt.md")]
    else:
        name = path.stem
    return name if REVIEW_ARTIFACT.match(name) else None


def roster_metadata(directory):
    path = directory / "roster.json"
    try:
        path.lstat()
    except FileNotFoundError:
        return {}, 0, {}
    except OSError:
        return {}, 1, {}
    try:
        document = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return {}, 1, {}
    if not isinstance(document, dict):
        return {}, 1, {}
    adapters = {}
    for item in document.get("seats", []):
        if isinstance(item, dict) and item.get("seat") and item.get("adapter"):
            adapters[str(item["seat"])] = str(item["adapter"])
    if "result_receipts" not in document:
        return adapters, 0, {}
    receipts = document["result_receipts"]
    if not isinstance(receipts, dict):
        return adapters, 1, {}
    version = receipts.get("version")
    legacy = receipts.get("legacy_no_exit_sha256")
    if (not isinstance(version, int) or isinstance(version, bool) or version < 1
            or not isinstance(legacy, dict)
            or not all(isinstance(name, str) and isinstance(digest, str)
                       and re.fullmatch(r"[0-9a-fA-F]{64}", digest) is not None
                       for name, digest in legacy.items())):
        return adapters, 1, {}
    return adapters, version, {name: digest.lower() for name, digest in legacy.items()}


def adapter_for_key(key, adapters):
    matches = (seat for seat in adapters if key.endswith("-" + seat))
    seat = max(matches, key=len, default=None)
    return adapters.get(seat) if seat else None


def terminal_record(path):
    terminal = None
    try:
        with path.open(errors="replace") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(record, dict) and record.get("type") in TERMINAL_TYPES:
                    terminal = record
    except OSError:
        return None
    return terminal


def number(value, integer=False):
    if value is None:
        return 0 if integer else 0.0
    if isinstance(value, bool):
        raise ValueError("boolean usage metric")
    if integer:
        if not isinstance(value, int) or value < 0:
            raise ValueError("invalid integer usage metric")
        return value
    if not isinstance(value, (int, float)):
        raise ValueError("invalid numeric usage metric")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid finite usage metric")
    return value


def inferred_adapter(record):
    if isinstance(record.get("stats"), dict):
        return "gemini"
    return {"result": "claude", "turn.completed": "codex", "end": "grok"}.get(record.get("type"))


def record_usage(record, adapter=None):
    kind = record.get("type")
    provider = adapter or inferred_adapter(record) or "unknown"
    shape = adapter if adapter in {"claude", "codex", "grok", "gemini"} else inferred_adapter(record)
    container = "stats" if shape == "gemini" else "usage"
    usage = record.get(container)
    if container in record and usage is not None and not isinstance(usage, dict):
        raise ValueError("invalid usage object")
    usage = usage if isinstance(usage, dict) else {}
    for key in (
        "input_tokens", "output_tokens", "processed_tokens", "cached_input_tokens",
        "cache_write_input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
        "reasoning_output_tokens", "total_tokens",
    ):
        if key in usage:
            number(usage[key], integer=True)
    if "total_tokens" in usage and "output_tokens" in usage \
            and usage["total_tokens"] < usage["output_tokens"]:
        raise ValueError("total token count is below output token count")
    cost = number(record.get("total_cost_usd") or usage.get("cost_usd") or record.get("cost_usd"))
    cached_input = number(usage.get("cached_input_tokens"), integer=True)
    cache_write = number(
        usage.get("cache_write_input_tokens")
        if usage.get("cache_write_input_tokens") is not None
        else usage.get("cache_creation_input_tokens"),
        integer=True,
    )
    cache_read = number(usage.get("cache_read_input_tokens"), integer=True)
    if shape == "claude" or (shape is None and kind == "result"):
        input_tokens = sum(number(usage.get(key), integer=True) for key in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"
        ))
        output_tokens = number(usage.get("output_tokens"), integer=True)
    elif shape == "codex":
        input_tokens = number(usage.get("input_tokens"), integer=True)
        output_tokens = number(usage.get("output_tokens"), integer=True)
    elif shape == "gemini":
        input_tokens = number(usage.get("input_tokens"), integer=True)
        output_tokens = number(usage.get("output_tokens"), integer=True)
    else:
        output_tokens = number(usage.get("output_tokens"), integer=True)
        total_tokens = number(usage.get("total_tokens"), integer=True)
        if "total_tokens" in usage:
            if total_tokens < output_tokens:
                raise ValueError("total token count is below output token count")
            input_tokens = total_tokens - output_tokens
        else:
            input_tokens = number(usage.get("input_tokens"), integer=True) + number(
                usage.get("cache_read_input_tokens"), integer=True
            )
    return {
        "provider": provider,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "processed_tokens": input_tokens + output_tokens,
        "cached_input_tokens": cached_input,
        "cache_write_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
        "cost_usd": cost,
    }


def empty_usage():
    return {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "processed_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cost_usd": 0.0,
    }


def empty_provider():
    item = empty_usage()
    item.update({"completed_calls": 0, "metered_calls": 0, "unmetered_calls": 0})
    return item


def add_usage(target, usage):
    target["calls"] += 1
    for key in USAGE_FIELDS:
        target[key] += usage[key]


def empty_scope_projection(with_names=True):
    return {
        "valid_manifests": 0,
        "invalid_manifests": [] if with_names else 0,
        "full_words": 0,
        "assigned_patch_words": 0,
        "delta_words": 0,
        "evidence_words": 0,
        "source_context_words": 0,
        "avoided_words": 0,
        "plan_words": 0,
        "closure_words": 0,
    }


def empty_read_activity(with_names=True):
    return {
        "audits": 0,
        "violating_audits": 0,
        "invalid_audits": [] if with_names else 0,
        "tool_calls": 0,
        "tool_turns": 0,
        "tool_output_bytes": 0,
        "max_tool_output_bytes": 0,
        "recognized_tool_calls": 0,
        "source_read_calls": 0,
        "packet_shards": 0,
        "packet_bytes": 0,
        "packet_ranges": 0,
        "opened_source_ranges": 0,
        "finding_citations": 0,
        "patch_proof_calls": 0,
        "patch_proof_turns": 0,
        "patch_proof_visible_bytes": 0,
        "expected_patch_chunks": 0,
        "opened_patch_chunks": 0,
        "window_seats": 0,
        "chunk_seats": 0,
    }


def read_activity(directory, adapters):
    activity = empty_read_activity()
    metric_fields = ("tool_calls", "tool_turns", "tool_output_bytes", "max_tool_output_bytes")
    source_fields = (
        "recognized_tool_calls", "source_read_calls", "packet_shards", "packet_bytes",
        "packet_ranges", "opened_source_ranges", "finding_citations",
    )
    for path in sorted(directory.glob("r*-*.read-audit.json")):
        try:
            audit = json.loads(path.read_text())
            if not isinstance(audit, dict):
                raise ValueError("read audit must be an object")
            stem = path.name[:-len(".read-audit.json")]
            prompt = directory / (stem + ".prompt.md")
            stream_candidates = [
                candidate for candidate in (
                    directory / (stem + ".stream.ndjson"),
                    directory / (stem + ".stream.jsonl"),
                ) if candidate.is_file()
            ]
            version = audit.get("schema_version")
            values = [audit.get(field) for field in metric_fields]
            if (version not in (1, 2)
                    or audit.get("status") not in ("valid", "invalid")
                    or not isinstance(audit.get("narrow"), bool)
                    or not isinstance(audit.get("adapter"), str) or not audit["adapter"]
                    or not isinstance(audit.get("violations"), list)
                    or any(not isinstance(value, int) or isinstance(value, bool) or value < 0
                           for value in values)):
                raise ValueError("invalid read audit structure")
            if ((audit["status"] == "valid") != (audit["violations"] == [])
                    or audit["tool_turns"] > audit["tool_calls"]
                    or audit["max_tool_output_bytes"] > audit["tool_output_bytes"]):
                raise ValueError("inconsistent read audit metrics")
            if version == 2:
                source_values = [audit.get(field) for field in source_fields]
                ranges = audit.get("source_ranges")
                if (any(not isinstance(value, int) or isinstance(value, bool) or value < 0
                        for value in source_values)
                        or audit["recognized_tool_calls"] > audit["tool_calls"]
                        or audit["source_read_calls"] > audit["recognized_tool_calls"]
                        or not isinstance(ranges, list)
                        or any(not isinstance(row, dict) or set(row) != {
                            "path", "line_start", "line_end", "origin"
                        } or not isinstance(row["path"], str) or not row["path"]
                            or type(row["line_start"]) is not int or type(row["line_end"]) is not int
                            or row["line_start"] < 1 or row["line_end"] < row["line_start"]
                            or row["origin"] not in ("packet", "tool") for row in ranges)
                        or audit["packet_ranges"] != sum(row["origin"] == "packet" for row in ranges)
                        or audit["opened_source_ranges"] != sum(row["origin"] == "tool" for row in ranges)):
                    raise ValueError("invalid source evidence audit structure")
                result = directory / (stem + ".json")
                result_hash = audit.get("result_sha256")
                if not isinstance(result_hash, str) or re.fullmatch(r"[0-9a-f]{64}", result_hash) is None:
                    raise ValueError("read audit result hash mismatch")
                findings = None
                if result.is_file():
                    if result_hash != hashlib.sha256(result.read_bytes()).hexdigest():
                        raise ValueError("read audit result hash mismatch")
                    try:
                        findings = json.loads(result.read_text()).get("findings")
                    except (OSError, ValueError, AttributeError) as error:
                        raise ValueError("invalid audited result") from error
                elif audit["status"] == "valid":
                    raise ValueError("read audit result hash mismatch")
                plan_citations = audit.get("plan_citation_ranges", [])
                plan_finding_citations = audit.get("plan_finding_citations", 0)
                plan_artifact_sha256 = audit.get("plan_artifact_sha256")
                finding_coverage = audit["finding_citations"] + plan_finding_citations
                if (type(plan_finding_citations) is not int or plan_finding_citations < 0
                        or not isinstance(plan_citations, list)
                        or len(plan_citations) != plan_finding_citations
                        or any(not isinstance(row, dict) or set(row) != {"line_start", "line_end"}
                               or type(row["line_start"]) is not int or type(row["line_end"]) is not int
                               or row["line_start"] < 1 or row["line_end"] < row["line_start"]
                               for row in plan_citations)
                        or (findings is not None and not isinstance(findings, list))
                        or (audit["status"] == "valid" and finding_coverage != len(findings))
                        or (audit["status"] == "invalid" and findings is not None
                            and finding_coverage > len(findings))):
                    raise ValueError("read audit finding coverage mismatch")
                manifest_hash = audit.get("evidence_manifest_sha256")
                if manifest_hash is not None:
                    if not isinstance(manifest_hash, str) or re.fullmatch(r"[0-9a-f]{64}", manifest_hash) is None:
                        raise ValueError("invalid read audit manifest hash")
                    manifests = [candidate for candidate in directory.glob("r*-evidence.manifest.json")
                                 if hashlib.sha256(candidate.read_bytes()).hexdigest() == manifest_hash]
                    if len(manifests) != 1:
                        raise ValueError("read audit manifest hash mismatch")
                    manifest = json.loads(manifests[0].read_text())
                    if manifest.get("phase") == "plan":
                        plan = manifest.get("plan") or {}
                        artifact = directory / str(plan.get("artifact", ""))
                        line_count = len(artifact.read_bytes().splitlines())
                        if (plan_artifact_sha256 != plan.get("sha256")
                                or any(row["line_end"] > line_count for row in plan_citations)):
                            raise ValueError("read audit plan citation binding mismatch")
                    elif (plan_artifact_sha256 is not None or plan_citations
                          or plan_finding_citations):
                        raise ValueError("non-plan audit contains plan citation coverage")
                elif (plan_artifact_sha256 is not None or plan_citations or plan_finding_citations):
                    raise ValueError("plan citations require an evidence manifest")
                patch_mode = audit.get("patch_proof_mode")
                patch_fields = (
                    "patch_proof_calls", "patch_proof_turns", "patch_proof_visible_bytes",
                    "expected_patch_chunks", "opened_patch_chunks",
                )
                if manifest_hash is not None and patch_mode is None:
                    raise ValueError("evidence audit lacks patch proof counters")
                if patch_mode is not None:
                    patch_values = [audit.get(field) for field in patch_fields]
                    if (patch_mode not in ("chunks", "windows")
                            or any(not isinstance(value, int) or isinstance(value, bool) or value < 0
                                   for value in patch_values)
                            or audit["patch_proof_calls"] > audit["tool_calls"]
                            or audit["patch_proof_turns"] > audit["patch_proof_calls"]
                            or audit["patch_proof_visible_bytes"] > audit["tool_output_bytes"]
                            or audit["opened_patch_chunks"] > audit["expected_patch_chunks"]
                            or (patch_mode == "windows" and (
                                audit["expected_patch_chunks"] or audit["opened_patch_chunks"]))
                            or (audit["status"] == "valid" and patch_mode == "chunks"
                                and not (audit["opened_patch_chunks"]
                                         == audit["expected_patch_chunks"]
                                         == audit["patch_proof_calls"]))):
                        raise ValueError("invalid patch proof audit structure")
            expected_adapter = adapter_for_key(stem, adapters)
            if expected_adapter and audit["adapter"] != expected_adapter:
                raise ValueError("read audit adapter mismatch")
            if (not prompt.is_file()
                    or audit.get("prompt_sha256") != hashlib.sha256(prompt.read_bytes()).hexdigest()):
                raise ValueError("read audit prompt hash mismatch")
            matching_streams = [candidate for candidate in stream_candidates
                                if audit.get("stream_sha256") == hashlib.sha256(candidate.read_bytes()).hexdigest()]
            if len(matching_streams) != 1:
                raise ValueError("read audit stream hash mismatch")
        except json.JSONDecodeError:
            reason = "malformed read audit JSON"
        except (OSError, TypeError, ValueError) as error:
            reason = str(error).strip() or error.__class__.__name__
        else:
            activity["audits"] += 1
            activity["violating_audits"] += audit["status"] == "invalid"
            for field in metric_fields[:-1]:
                activity[field] += audit[field]
            activity["max_tool_output_bytes"] = max(
                activity["max_tool_output_bytes"], audit["max_tool_output_bytes"]
            )
            if version == 2:
                for field in source_fields:
                    activity[field] += audit[field]
                if audit.get("patch_proof_mode") is not None:
                    for field in patch_fields:
                        activity[field] += audit[field]
                    activity["chunk_seats" if audit["patch_proof_mode"] == "chunks"
                             else "window_seats"] += 1
            continue
        activity["invalid_audits"].append({"audit": path.name, "reason": reason})
    return activity


def evidence_validator():
    spec = importlib.util.spec_from_file_location("review_council_evidence", EVIDENCE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ValueError("evidence validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validated_manifest


def evidence_words(path, validate):
    manifest, manifest_hash = validate(path, fresh=False, offline=True)
    words = manifest.get("word_counts")
    required = ("full", "semantic", "delta", "evidence", "source_context", "assigned_patch", "avoided")
    if not isinstance(words, dict) or any(
        not isinstance(words.get(key), int) or isinstance(words.get(key), bool) or words[key] < 0
        for key in required
    ):
        raise ValueError("invalid evidence word counts")

    label = manifest["label"]
    session = path.parent
    direct = {
        "full": session / f"r{label}-full.patch",
        "semantic": session / f"r{label}-semantic.patch",
        "delta": session / f"r{label}-delta.patch",
    }
    for key, artifact in direct.items():
        actual = len(artifact.read_bytes().split())
        metadata = manifest["artifacts"][artifact.name]
        if words[key] != actual or metadata.get("words") != actual:
            raise ValueError("evidence word count mismatch")
    shared_evidence = sum(
        len((session / f"r{label}-{suffix}").read_bytes().split())
        for suffix in ("evidence.md", "instructions.md")
    )
    if words["evidence"] != shared_evidence:
        raise ValueError("evidence word count mismatch")
    source_context = manifest.get("source_context")
    if not isinstance(source_context, dict) or not isinstance(source_context.get("seats"), dict):
        raise ValueError("source context word count unavailable")
    source_context_words = 0
    for packet in source_context["seats"].values():
        for shard in packet["shards"]:
            artifact = session / shard["artifact"]
            actual = len(artifact.read_bytes().split())
            if manifest["artifacts"][artifact.name].get("words") != actual:
                raise ValueError("source context artifact word count mismatch")
            source_context_words += actual
    if words["source_context"] != source_context_words:
        raise ValueError("source context word count mismatch")

    assignments = manifest["assignments"]
    manifest_line = "Evidence manifest SHA-256: " + manifest_hash
    assigned = 0
    for seat, assignment in assignments.items():
        prompt = session / f"r{label}-{seat}.prompt.md"
        try:
            prompt_lines = prompt.read_text(errors="replace").splitlines()
        except OSError as error:
            raise ValueError("evidence prompt unavailable: " + seat) from error
        if manifest_line not in prompt_lines:
            raise ValueError("evidence prompt manifest hash mismatch")
        try:
            assigned_patch = Path(assignment["patch"]).resolve(strict=True)
            assigned_patch.relative_to(session)
            assigned += len(assigned_patch.read_bytes().split())
        except (KeyError, OSError, ValueError) as error:
            raise ValueError("assigned evidence patch unavailable: " + seat) from error
    avoided = max(0, len(assignments) * words["full"] - assigned
                  - len(assignments) * words["evidence"] - source_context_words)
    if words["assigned_patch"] != assigned or words["avoided"] != avoided:
        raise ValueError("invalid evidence scope projection")
    plan_words = 0
    closure_words = 0
    if manifest.get("phase") == "plan":
        if any(not isinstance(words.get(key), int) or isinstance(words.get(key), bool)
               or words[key] < 0 for key in ("plan", "closure")):
            raise ValueError("invalid plan evidence word counts")
        plan_words = len((session / f"r{label}-plan.md").read_bytes().split())
        closure_words = len((session / f"r{label}-plan-closure.patch").read_bytes().split())
        if words["plan"] != plan_words or words["closure"] != closure_words:
            raise ValueError("plan evidence word count mismatch")
    return {
        "full_words": words["full"],
        "assigned_patch_words": words["assigned_patch"],
        "delta_words": words["delta"],
        "evidence_words": words["evidence"],
        "source_context_words": source_context_words,
        "avoided_words": words["avoided"],
        "plan_words": plan_words,
        "closure_words": closure_words,
    }


def profile_evidence(directory):
    projection = empty_scope_projection()
    try:
        validate = evidence_validator()
    except (ImportError, OSError, ValueError):
        validate = None
    for path in sorted(directory.glob("r*-evidence.manifest.json")):
        try:
            if validate is None:
                raise ValueError("evidence validator is unavailable")
            item = evidence_words(path, validate)
        except (AttributeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, json.JSONDecodeError):
                reason = "malformed manifest JSON"
            else:
                reason = str(error).strip() or error.__class__.__name__
            projection["invalid_manifests"].append({"manifest": path.name, "reason": reason})
            continue
        projection["valid_manifests"] += 1
        for key, value in item.items():
            projection[key] += value
    return projection


def is_completed_result(path, receipt_version=0, legacy_no_exit_sha256=None):
    exit_path = path.with_suffix(".exit")
    if exit_path.exists():
        try:
            if exit_path.read_text(errors="replace").strip() != "0":
                return False
        except OSError:
            return False
    elif receipt_version >= 1:
        expected = (legacy_no_exit_sha256 or {}).get(path.name)
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return False
        if expected != actual:
            return False
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def profile_session(directory):
    adapters, receipt_version, legacy_no_exit_sha256 = roster_metadata(directory)
    prompts = {"code": {"count": 0, "words": 0}, "plan": {"count": 0, "words": 0}}
    for path in directory.glob("*.prompt.md"):
        if artifact_key(path) is None:
            continue
        phase = "plan" if is_plan(path) else "code"
        prompts[phase]["count"] += 1
        prompts[phase]["words"] += len(path.read_text(errors="replace").split())

    results = {"code": {"calls": 0, "findings": 0}, "plan": {"calls": 0, "findings": 0}}
    completed = []
    for path in directory.glob("*.json"):
        key = artifact_key(path)
        if key is None:
            continue
        if not is_completed_result(path, receipt_version, legacy_no_exit_sha256):
            continue
        try:
            document = json.loads(path.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        phase = "plan" if is_plan(path) else "code"
        results[phase]["calls"] += 1
        results[phase]["findings"] += len(document["findings"])
        completed.append((key, adapter_for_key(key, adapters)))

    usage = empty_usage()
    providers = {}
    metered_keys = set()
    stream_providers = {}
    invalid_usage = []
    for path in directory.glob("*.stream.*"):
        key = artifact_key(path)
        if key is None:
            continue
        record = terminal_record(path)
        if record is None:
            continue
        try:
            item = record_usage(record, adapter_for_key(key, adapters))
        except (TypeError, ValueError) as error:
            invalid_usage.append({"stream": path.name, "reason": str(error)})
            continue
        if item["processed_tokens"] == 0 and item["cost_usd"] == 0:
            continue
        add_usage(usage, item)
        metered_keys.add(key)
        stream_providers[key] = item["provider"]
        provider_usage = providers.setdefault(item["provider"], empty_provider())
        add_usage(provider_usage, item)
        provider_usage["metered_calls"] = provider_usage["calls"]

    unmetered = 0
    for key, adapter in completed:
        provider = adapter or stream_providers.get(key) or "unknown"
        provider_usage = providers.setdefault(provider, empty_provider())
        provider_usage["completed_calls"] += 1
        if key not in metered_keys:
            unmetered += 1
            provider_usage["unmetered_calls"] += 1

    calls = {"completed": len(completed), "metered": usage["calls"], "unmetered": unmetered}

    return {
        "session": directory.name,
        "path": str(directory),
        "prompts": prompts,
        "results": results,
        "calls": calls,
        "usage": usage,
        "providers": providers,
        "invalid_usage": invalid_usage,
        "read_activity": read_activity(directory, adapters),
        "scope_projection": profile_evidence(directory),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("sessions", nargs="+", type=session_directory)
    args = parser.parse_args()

    sessions = [profile_session(directory) for directory in args.sessions]
    totals = empty_usage()
    totals.update({"completed_calls": 0, "metered_calls": 0, "unmetered_calls": 0})
    totals["invalid_usage"] = 0
    scope_totals = empty_scope_projection(with_names=False)
    read_totals = empty_read_activity(with_names=False)
    for session in sessions:
        usage = session["usage"]
        totals["calls"] += usage["calls"]
        for key in USAGE_FIELDS:
            totals[key] += usage[key]
        totals["completed_calls"] += session["calls"]["completed"]
        totals["metered_calls"] += session["calls"]["metered"]
        totals["unmetered_calls"] += session["calls"]["unmetered"]
        totals["invalid_usage"] += len(session["invalid_usage"])
        activity = session["read_activity"]
        read_totals["audits"] += activity["audits"]
        read_totals["violating_audits"] += activity["violating_audits"]
        read_totals["invalid_audits"] += len(activity["invalid_audits"])
        for key in (
            "tool_calls", "tool_turns", "tool_output_bytes", "recognized_tool_calls",
            "source_read_calls", "packet_shards", "packet_bytes", "packet_ranges",
            "opened_source_ranges", "finding_citations", "patch_proof_calls",
            "patch_proof_turns", "patch_proof_visible_bytes", "expected_patch_chunks",
            "opened_patch_chunks", "window_seats", "chunk_seats",
        ):
            read_totals[key] += activity[key]
        read_totals["max_tool_output_bytes"] = max(
            read_totals["max_tool_output_bytes"], activity["max_tool_output_bytes"]
        )
        projection = session["scope_projection"]
        scope_totals["valid_manifests"] += projection["valid_manifests"]
        scope_totals["invalid_manifests"] += len(projection["invalid_manifests"])
        for key in ("full_words", "assigned_patch_words", "delta_words", "evidence_words",
                    "source_context_words", "avoided_words", "plan_words", "closure_words"):
            scope_totals[key] += projection[key]
    totals["scope_projection"] = scope_totals
    totals["read_activity"] = read_totals
    document = {"sessions": sessions, "totals": totals}

    if args.as_json:
        print(json.dumps(document, indent=2, sort_keys=True, allow_nan=False))
        return
    for session in sessions:
        usage = session["usage"]
        code = session["prompts"]["code"]
        plan = session["prompts"]["plan"]
        scope = session["scope_projection"]
        print(
            "%s calls=%d processed=%d input=%d output=%d cached_input=%d cache_write_input=%d cache_read_input=%d cost_usd=%.2f completed=%d metered=%d unmetered=%d usage_invalid=%d prompt_words=%d/%d projected_scope_words=full:%d assigned:%d delta:%d evidence:%d avoided:%d packet:%d evidence_invalid=%d"
            % (
                session["session"], usage["calls"], usage["processed_tokens"], usage["input_tokens"],
                usage["output_tokens"], usage["cached_input_tokens"], usage["cache_write_input_tokens"],
                usage["cache_read_input_tokens"], usage["cost_usd"],
                session["calls"]["completed"], session["calls"]["metered"], session["calls"]["unmetered"],
                len(session["invalid_usage"]), code["words"], plan["words"], scope["full_words"], scope["assigned_patch_words"],
                scope["delta_words"], scope["evidence_words"], scope["avoided_words"],
                scope["source_context_words"],
                len(scope["invalid_manifests"])
            )
        )
        for invalid in scope["invalid_manifests"]:
            print("  evidence_invalid_detail=%s: %s" % (invalid["manifest"], invalid["reason"]))
        for invalid in session["invalid_usage"]:
            print("  usage_invalid_detail=%s: %s" % (invalid["stream"], invalid["reason"]))
        activity = session["read_activity"]
        print(
            "  read_activity=audits:%d violating:%d calls:%d turns:%d output_bytes:%d max_output_bytes:%d invalid:%d packet_shards:%d packet_bytes:%d packet_ranges:%d source_reads:%d opened_ranges:%d finding_citations:%d patch_proof_calls:%d patch_proof_turns:%d patch_proof_bytes:%d expected_chunks:%d opened_chunks:%d patch_modes:window:%d,chunk:%d"
            % (
                activity["audits"], activity["violating_audits"], activity["tool_calls"],
                activity["tool_turns"], activity["tool_output_bytes"],
                activity["max_tool_output_bytes"], len(activity["invalid_audits"]),
                activity["packet_shards"], activity["packet_bytes"], activity["packet_ranges"],
                activity["source_read_calls"], activity["opened_source_ranges"],
                activity["finding_citations"],
                activity["patch_proof_calls"], activity["patch_proof_turns"],
                activity["patch_proof_visible_bytes"], activity["expected_patch_chunks"],
                activity["opened_patch_chunks"], activity["window_seats"],
                activity["chunk_seats"],
            )
        )
        for invalid in activity["invalid_audits"]:
            print("  read_audit_invalid_detail=%s: %s" % (invalid["audit"], invalid["reason"]))
    print(
        "TOTAL calls=%d processed=%d input=%d output=%d cached_input=%d cache_write_input=%d cache_read_input=%d cost_usd=%.2f completed=%d metered=%d unmetered=%d usage_invalid=%d projected_scope_words=full:%d assigned:%d delta:%d evidence:%d avoided:%d packet:%d evidence_invalid=%d"
        % (
            totals["calls"], totals["processed_tokens"], totals["input_tokens"], totals["output_tokens"],
            totals["cached_input_tokens"], totals["cache_write_input_tokens"],
            totals["cache_read_input_tokens"], totals["cost_usd"], totals["completed_calls"],
            totals["metered_calls"], totals["unmetered_calls"], totals["invalid_usage"], scope_totals["full_words"],
            scope_totals["assigned_patch_words"], scope_totals["delta_words"],
            scope_totals["evidence_words"], scope_totals["avoided_words"],
            scope_totals["source_context_words"],
            scope_totals["invalid_manifests"]
        )
    )
    print(
        "TOTAL_READ_ACTIVITY audits=%d violating=%d calls=%d turns=%d output_bytes=%d max_output_bytes=%d invalid=%d packet_shards=%d packet_bytes=%d packet_ranges=%d source_reads:%d opened_ranges:%d finding_citations:%d patch_proof_calls:%d patch_proof_turns:%d patch_proof_bytes:%d expected_chunks:%d opened_chunks:%d patch_modes:window:%d,chunk:%d"
        % (
            read_totals["audits"], read_totals["violating_audits"], read_totals["tool_calls"],
            read_totals["tool_turns"], read_totals["tool_output_bytes"],
            read_totals["max_tool_output_bytes"], read_totals["invalid_audits"],
            read_totals["packet_shards"], read_totals["packet_bytes"], read_totals["packet_ranges"],
            read_totals["source_read_calls"], read_totals["opened_source_ranges"],
            read_totals["finding_citations"],
            read_totals["patch_proof_calls"], read_totals["patch_proof_turns"],
            read_totals["patch_proof_visible_bytes"], read_totals["expected_patch_chunks"],
            read_totals["opened_patch_chunks"], read_totals["window_seats"],
            read_totals["chunk_seats"],
        )
    )


if __name__ == "__main__":
    main()
