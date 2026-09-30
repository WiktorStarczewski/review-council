"""Hash-bound correctness and observable source exposure, with fixed score weights."""
import hashlib
import json
import math
import re

try:
    from .bench_score import score_findings
except ImportError:
    from bench_score import score_findings


WEIGHTS = {"defect_recall": 55, "precision": 15, "citation_accuracy": 10,
           "critical_flow_coverage": 15, "useful_hypotheses": 5}
SEVERITIES = {"P0": 8, "P1": 4, "P2": 2, "P3": 1}
DEFAULT_POLICY = {"quality_delta_tolerance": 3, "minimum_quality": 90,
                  "minimum_weighted_recall": 0.90, "allow_added_false_positives": False}


def canonical_sha256(value):
    """Hash deterministic complete JSON; raw artifact hashes use different bytes."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(optional):
        raise ValueError("object has missing or unexpected fields")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a nonblank string is required")


def _hash(value, length=64):
    lengths = (length,) if type(length) is int else length
    pattern = "|".join("[0-9a-f]{" + str(size) + "}" for size in lengths)
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("invalid hash identity")


def _source(row, extra=()):
    _keys(row, {"path", "line_start", "line_end"} | set(extra))
    path = row["path"]
    if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path
            or "\x00" in path or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValueError("source path must be a literal relative path")
    start, end = row["line_start"], row["line_end"]
    if type(start) is not int or type(end) is not int or not 1 <= start <= end:
        raise ValueError("source ranges must be positive inclusive integer intervals")
    return path, start, end


def _sources(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("required sources must be a nonempty list")
    return [_source(row) for row in rows]


def _covered(source, ranges):
    path, start, end = source
    next_line = start
    for left, right in sorted((left, right) for name, left, right in ranges if name == path):
        if right < next_line:
            continue
        if left > next_line:
            break
        next_line = max(next_line, right + 1)
        if next_line > end:
            return True
    return False


def _rubric(value):
    if value is None:
        return None
    _keys(value, {"schema_version", "measurement", "critical_flows", "hypotheses"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported behavior rubric schema")
    _text(value["measurement"])
    for field, description in (("critical_flows", "rationale"), ("hypotheses", "description")):
        rows, seen = value[field], set()
        if not isinstance(rows, list) or not rows:
            raise ValueError("rubric collections must be nonempty lists")
        for row in rows:
            _keys(row, {"id", "required_sources", description})
            _text(row["id"])
            _text(row[description])
            if row["id"] in seen:
                raise ValueError("rubric IDs must be unique")
            seen.add(row["id"])
            _sources(row["required_sources"])
    return value


def _audit(value):
    if value is None:
        return None
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 2:
        raise ValueError("unsupported audit schema")
    if value.get("status") not in ("valid", "invalid"):
        raise ValueError("unrecognized audit status")
    violations = value.get("violations")
    if not isinstance(violations, list):
        raise ValueError("audit violations must be a list")
    for row in violations:
        _keys(row, {"code", "tool"})
        _text(row["code"])
        _text(row["tool"])
    if value["status"] == "valid" and violations:
        raise ValueError("valid audit cannot contain violations")
    for field in ("prompt_sha256", "stream_sha256", "result_sha256"):
        if value["status"] == "valid" or value.get(field) is not None:
            _hash(value.get(field))
    if value.get("evidence_manifest_sha256") is not None:
        _hash(value["evidence_manifest_sha256"])
    rows = value.get("source_ranges")
    if not isinstance(rows, list):
        raise ValueError("audit source ranges must be a list")
    for row in rows:
        _source(row, {"origin"})
        if row["origin"] not in ("tool", "packet"):
            raise ValueError("unrecognized source range origin")
    return value


def _manual(rows, field, expected, verdicts):
    if not isinstance(rows, list):
        raise ValueError("manual dispositions must be a list")
    output = {}
    for row in rows:
        _keys(row, {field, "verdict", "reason"})
        identity = row[field]
        if (type(identity) is not type(next(iter(expected), "")) or identity not in expected
                or identity in output or not isinstance(row["verdict"], str) or row["verdict"] not in verdicts):
            raise ValueError("manual dispositions require unique known identities and verdicts")
        _text(row["reason"])
        output[identity] = row
    if set(output) != set(expected):
        raise ValueError("every item requires exactly one manual disposition")
    return output


def _behavior(value, identities, finding_count, rubric):
    if value is None:
        return None
    _keys(value, {"schema_version", "citations", "hypotheses"} | set(identities), {"novel_scenarios"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported behavior adjudication schema")
    if any(value[key] != expected for key, expected in identities.items()):
        raise ValueError("behavior adjudication identities do not match")
    citations = _manual(value["citations"], "finding", set(range(finding_count)), {"accurate", "inaccurate"})
    hypotheses = _manual(value["hypotheses"], "hypothesis", {row["id"] for row in (rubric or {}).get("hypotheses", [])},
                         {"verified", "refuted", "untested"})
    novel = value.get("novel_scenarios", [])
    if not isinstance(novel, list):
        raise ValueError("novel scenarios must be a list")
    seen = {row["id"] for row in (rubric or {}).get("hypotheses", [])}
    for row in novel:
        _keys(row, {"id", "verdict", "reason", "required_sources"})
        _text(row["id"])
        _text(row["reason"])
        if row["id"] in seen or row["verdict"] not in ("verified", "refuted", "speculative"):
            raise ValueError("novel scenarios require unique IDs and recognized verdicts")
        seen.add(row["id"])
        _sources(row["required_sources"])
    return citations, hypotheses, novel


def _exposure(provenance, identities, audit):
    if provenance is None:
        return None
    bindings = {key: identities[key] for key in ("case_sha256", "findings_sha256", "audit_sha256",
                                                "evidence_manifest_sha256")}
    _keys(provenance, set(bindings) | {"snapshot_tree"}, {"snapshot_packet_ranges"})
    if any(provenance[key] != expected for key, expected in bindings.items()):
        raise ValueError("verified provenance identities do not match")
    _hash(provenance["snapshot_tree"], (40, 64))
    packets = provenance.get("snapshot_packet_ranges", [])
    if not isinstance(packets, list):
        raise ValueError("qualified packet ranges must be a list")
    rows = (audit or {}).get("source_ranges", [])
    ranges = [_source(row, {"origin"}) for row in rows if row["origin"] == "tool"]
    delivered_packets = [_source(row, {"origin"}) for row in rows if row["origin"] == "packet"]
    for row in packets:
        source = _source(row, {"blob_tree"})
        _hash(row["blob_tree"], (40, 64))
        if row["blob_tree"] != provenance["snapshot_tree"]:
            continue
        if not _covered(source, delivered_packets):
            raise ValueError("qualified packet range exceeds audited packet exposure")
        ranges.append(source)
    return ranges


def score_run(case, result, correctness, audit, behavior_adjudication, *, verified_provenance=None):
    """Score complete manual judgments; full quality requires trusted artifact provenance."""
    if not isinstance(case, dict) or not isinstance(case.get("defects"), list):
        raise ValueError("case requires a list of defects")
    truth = {}
    for defect in case["defects"]:
        if not isinstance(defect, dict):
            raise ValueError("defects must be objects")
        _text(defect.get("id"))
        if defect["id"] in truth:
            raise ValueError("truth IDs must be unique")
        _source({"path": defect.get("file"), "line_start": defect.get("line_start"), "line_end": defect.get("line_end")})
        if "severity" in defect and (not isinstance(defect["severity"], str) or defect["severity"] not in SEVERITIES):
            raise ValueError("unrecognized truth severity")
        groups = defect.get("keyword_groups")
        if (not isinstance(groups, list) or any(not isinstance(group, list)
                or any(not isinstance(word, str) for word in group) for group in groups)):
            raise ValueError("truth keyword groups must contain string lists")
        truth[defect["id"]] = defect
    if not isinstance(result, dict) or not isinstance(result.get("findings"), list):
        raise ValueError("result requires a list of findings")
    for finding in result["findings"]:
        if not isinstance(finding, dict):
            raise ValueError("findings must be objects")
        _source({"path": finding.get("file"), "line_start": finding.get("line_start"), "line_end": finding.get("line_end")})
        for field in ("claim", "evidence", "suggested_fix"):
            if not isinstance(finding.get(field), str):
                raise ValueError("finding descriptions must be strings")
    rubric, audit = _rubric(case.get("behavior_rubric")), _audit(audit)
    identities = {"case_sha256": canonical_sha256(case), "rubric_sha256": canonical_sha256(rubric) if rubric else None,
                  "findings_sha256": canonical_sha256(result), "audit_sha256": canonical_sha256(audit) if audit else None,
                  "evidence_manifest_sha256": (audit or {}).get("evidence_manifest_sha256")}
    manual = _behavior(behavior_adjudication, identities, len(result["findings"]), rubric)
    exposure = _exposure(verified_provenance, identities, audit)
    correctness_score = score_findings(case, result, correctness)
    critical = [key for key, value in truth.items() if value.get("severity") in ("P0", "P1")]
    output = dict(identities, schema_version=1, score_version="quality-v1", confirmed=correctness_score["confirmed"],
                  quality_score=None, core_score=None, core_maximum=80, maximum=100, weighted_recall=None,
                  critical_defects=critical, critical_hits=[], defect_hits=correctness_score["defect_hits"],
                  false_positives=correctness_score["false_positives"], behavior_available=False, unavailable=[],
                  clean_case_semantics="clean recall points measure zero false positives; clean empty precision and citations earn full points",
                  novel_scenarios={"grounded": None, "speculative": None, "substitutions": None},
                  components={key: {"weight": weight, "value": None, "points": None} for key, weight in WEIGHTS.items()})
    unavailable = output["unavailable"]
    for missing, reason in ((correctness is None, "correctness-adjudication"), (manual is None, "behavior-adjudication"),
                            (rubric is None, "behavior-rubric"), (exposure is None, "verified-provenance"),
                            (audit is None or audit["status"] != "valid", "valid-audit"),
                            (identities["evidence_manifest_sha256"] is None, "evidence-manifest"),
                            (any("severity" not in row for row in truth.values()), "truth-severity")):
        if missing:
            unavailable.append(reason)
    if not correctness_score["confirmed"]:
        return output
    hits = set(output["defect_hits"])
    output["critical_hits"] = [key for key in critical if key in hits]
    values = {}
    if "truth-severity" not in unavailable:
        total = sum(SEVERITIES[row["severity"]] for row in truth.values())
        output["weighted_recall"] = sum(SEVERITIES[truth[key]["severity"]] for key in hits) / total if total else None
        values["defect_recall"] = output["weighted_recall"] if total else float(output["false_positives"] == 0)
    rows = correctness["dispositions"]
    denominator = sum(row["verdict"] != "duplicate" for row in rows)
    values["precision"] = correctness_score["precision"] if denominator else float(not truth)
    if manual is not None:
        citations, hypotheses, novel = manual
        accurate = 0
        for row in rows:
            if row["verdict"] not in ("true_positive", "valid_extra") or citations[row["finding"]]["verdict"] != "accurate":
                continue
            finding = result["findings"][row["finding"]]
            if all(finding["file"] == truth[key]["file"] and finding["line_start"] <= truth[key]["line_end"]
                   and finding["line_end"] >= truth[key]["line_start"] for key in row["defects"]):
                accurate += 1
        values["citation_accuracy"] = accurate / denominator if denominator else float(not truth)
        if rubric is not None and exposure is not None and "valid-audit" not in unavailable and "evidence-manifest" not in unavailable:
            grounded = lambda row: all(_covered(source, exposure) for source in _sources(row["required_sources"]))
            flows = rubric["critical_flows"]
            values["critical_flow_coverage"] = sum(grounded(row) for row in flows) / len(flows)
            tested = sum(hypotheses[row["id"]]["verdict"] in ("verified", "refuted") and grounded(row)
                         for row in rubric["hypotheses"])
            novel_count = sum(row["verdict"] in ("verified", "refuted") and grounded(row) for row in novel)
            substitutes = int(novel_count > 0 and any(row["verdict"] == "untested" for row in hypotheses.values()))
            output["novel_scenarios"] = {"grounded": novel_count, "speculative": sum(row["verdict"] == "speculative" for row in novel),
                                         "substitutions": substitutes}
            values["useful_hypotheses"] = (tested + substitutes) / len(rubric["hypotheses"])
            output["behavior_available"] = True
    for key, value in values.items():
        output["components"][key].update(value=value, points=value * WEIGHTS[key])
    if all(key in values for key in list(WEIGHTS)[:3]):
        output["core_score"] = sum(output["components"][key]["points"] for key in list(WEIGHTS)[:3])
    if len(values) == len(WEIGHTS):
        output["quality_score"] = sum(row["points"] for row in output["components"].values())
    return output


def compare_quality(baseline_row, candidate_row, *, policy=None):
    """Gate retention on full quality, critical recall and a frozen explicit policy."""
    policy = dict(DEFAULT_POLICY if policy is None else policy)
    _keys(policy, set(DEFAULT_POLICY))
    for field, maximum in (("quality_delta_tolerance", 100), ("minimum_quality", 100), ("minimum_weighted_recall", 1)):
        value = policy[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise ValueError("invalid comparison policy number")
    if type(policy["allow_added_false_positives"]) is not bool:
        raise ValueError("false-positive policy must be boolean")
    reasons = []
    scores = [row.get("run_quality") if isinstance(row, dict) else None for row in (baseline_row, candidate_row)]
    for name, row, score in zip(("baseline", "candidate"), (baseline_row, candidate_row), scores):
        if not isinstance(row, dict) or row.get("valid") is not True:
            reasons.append(name + "-invalid-audit")
        if not isinstance(score, dict) or score.get("confirmed") is not True or score.get("maximum") != 100:
            reasons.append(name + "-unconfirmed-quality")
    full = all(isinstance(score, dict) and type(score.get("quality_score")) in (int, float)
               and math.isfinite(score["quality_score"]) and 0 <= score["quality_score"] <= 100 for score in scores)
    delta = None
    if not full:
        reasons.append("full-quality-unavailable")
    else:
        baseline, candidate = scores
        for field in ("score_version", "case_sha256", "rubric_sha256"):
            if not baseline.get(field) or baseline.get(field) != candidate.get(field):
                reasons.append("mismatched-" + field)
        delta = candidate["quality_score"] - baseline["quality_score"]
        if delta < -policy["quality_delta_tolerance"]:
            reasons.append("quality-loss")
        if candidate["quality_score"] < policy["minimum_quality"]:
            reasons.append("quality-floor")
        recall = candidate.get("weighted_recall")
        if recall is not None and (type(recall) not in (int, float) or not math.isfinite(recall)
                                   or not policy["minimum_weighted_recall"] <= recall <= 1):
            reasons.append("weighted-recall-floor")
        critical = candidate.get("critical_defects")
        hits, previous_hits = candidate.get("critical_hits"), baseline.get("critical_hits")
        if not all(isinstance(row, list) and all(isinstance(item, str) for item in row) for row in (critical, hits, previous_hits)):
            reasons.append("critical-recall-unavailable")
        elif not set(critical) <= set(hits) or not set(previous_hits) <= set(hits):
            reasons.append("lost-critical-defect")
        old_fp, new_fp = baseline.get("false_positives"), candidate.get("false_positives")
        if type(old_fp) is not int or type(new_fp) is not int or min(old_fp, new_fp) < 0:
            reasons.append("false-positives-unavailable")
        elif not policy["allow_added_false_positives"] and new_fp > old_fp:
            reasons.append("added-false-positive")
    return {"acceptable": not reasons, "reasons": reasons, "quality_delta": delta,
            "policy": policy, "policy_sha256": canonical_sha256(policy), "screening_only": not full}


def _summary_value(row, identity):
    score = row.get("run_quality") if isinstance(row, dict) else None
    if (not isinstance(row, dict) or row.get("valid") is not True or not isinstance(score, dict)
            or score.get("confirmed") is not True or score.get("behavior_available") is not True
            or score.get("unavailable") != [] or score.get("score_version") != "quality-v1"
            or type(score.get("schema_version")) is not int or score["schema_version"] != 1
            or type(score.get("maximum")) is not int or score["maximum"] != 100):
        return None
    value = score.get("quality_score")
    if type(value) not in (int, float) or not 0 <= value <= 100 or not math.isfinite(value):
        return None
    for key in ("case_sha256", "rubric_sha256"):
        if identity[key] is None or score.get(key) != identity[key]:
            return None
    try:
        for key in ("findings_sha256", "audit_sha256", "evidence_manifest_sha256"):
            _hash(score.get(key))
    except ValueError:
        return None
    return value


def summarize_quality(rows, expected_cases):
    """Average full scores equally across a complete, identity-bound frozen case set."""
    expected = {}
    for case in expected_cases:
        _text(case.get("id"))
        case_id = case["id"]
        if case_id in expected:
            raise ValueError("duplicate expected quality case: " + case_id)
        rubric = case.get("behavior_rubric")
        expected[case_id] = {"case": case_id, "case_sha256": canonical_sha256(case),
                             "rubric_sha256": canonical_sha256(rubric) if rubric else None}
    variants = {"baseline": {}, "candidate": {}}
    versions = set()
    for row in rows:
        variant = row.get("variant")
        if not isinstance(variant, str) or variant not in variants:
            raise ValueError("unsupported quality summary variant")
        _text(row.get("case"))
        case_id = row["case"]
        if case_id in variants[variant]:
            raise ValueError("duplicate quality case/variant: " + case_id + "/" + variant)
        variants[variant][case_id] = row
        score = row.get("run_quality")
        if isinstance(score, dict) and isinstance(score.get("score_version"), str):
            versions.add(score["score_version"])
    summaries = {}
    identities = [expected[key] for key in sorted(expected)]
    for variant, cases in variants.items():
        unavailable = ["mixed-score-versions"] if len(versions) > 1 else []
        if not expected:
            unavailable.append("no-expected-cases")
        unavailable.extend("unexpected-case:" + key for key in sorted(set(cases) - set(expected)))
        scores = []
        for case_id, identity in sorted(expected.items()):
            value = _summary_value(cases.get(case_id), identity)
            if value is None:
                unavailable.append(case_id + (":full-quality-unavailable" if case_id in cases else ":missing-case"))
            else:
                scores.append(value)
        known = not unavailable
        summaries[variant] = {"status": "known" if known else "unknown",
                              "quality_score": math.fsum(scores) / len(expected) if known else None,
                              "minimum_quality_score": min(scores) if known else None,
                              "complete_cases": len(scores), "expected_cases": len(expected),
                              "maximum": 100, "score_version": "quality-v1",
                              "aggregation_version": "quality-equal-case-v1",
                              "case_identities": identities, "unavailable": unavailable}
    return summaries
