"""Provisional source matches and complete, hash-bound correctness adjudication."""
import hashlib
import json


def findings_sha256(result: dict) -> str:
    """Bind the full reviewer result with deterministic JSON, including its summary."""
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_matches(case, findings):
    matches = []
    for index, finding in enumerate(findings):
        text = " ".join(finding[key] for key in ("claim", "evidence", "suggested_fix")).casefold()
        defects = [
            defect["id"] for defect in case["defects"]
            if finding["file"] == defect["file"]
            and finding["line_start"] <= defect["line_end"]
            and finding["line_end"] >= defect["line_start"]
            and all(any(word.casefold() in text for word in group)
                    for group in defect["keyword_groups"])
        ]
        if defects:
            matches.append({"finding": index, "defects": defects, "provisional": True})
    return matches


def _adjudicated_rows(adjudication, expected_hash, finding_count, truth_ids):
    if not isinstance(adjudication, dict) or set(adjudication) != {"findings_sha256", "dispositions"}:
        raise ValueError("adjudication requires findings hash and dispositions only")
    if adjudication["findings_sha256"] != expected_hash:
        raise ValueError("adjudication findings hash does not match the reviewer result")
    rows = adjudication["dispositions"]
    if not isinstance(rows, list):
        raise ValueError("adjudication dispositions must be a list")
    seen = set()
    verdicts = {"true_positive", "false_positive", "valid_extra", "duplicate"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"finding", "verdict", "defects", "reason"}:
            raise ValueError("each disposition requires finding, verdict, defects and reason only")
        index = row["finding"]
        if type(index) is not int or not 0 <= index < finding_count or index in seen:
            raise ValueError("every finding must be adjudicated exactly once by its integer index")
        seen.add(index)
        verdict = row["verdict"]
        if not isinstance(verdict, str) or verdict not in verdicts:
            raise ValueError("disposition verdict is not recognized")
        if not isinstance(row["reason"], str) or not row["reason"].strip():
            raise ValueError("each disposition requires a nonblank reason")
        defects = row["defects"]
        if not isinstance(defects, list) or any(not isinstance(value, str) for value in defects):
            raise ValueError("disposition defects must be a list of truth IDs")
        if len(set(defects)) != len(defects) or any(value not in truth_ids for value in defects):
            raise ValueError("disposition defects must be distinct, known truth IDs")
        if verdict == "true_positive" and not defects:
            raise ValueError("true_positive requires at least one truth ID")
        if verdict != "true_positive" and defects:
            raise ValueError("only true_positive dispositions may claim truth IDs")
    if len(seen) != finding_count:
        raise ValueError("every finding must be adjudicated exactly once")
    return rows


def score_findings(case: dict, result: dict, adjudication=None) -> dict:
    """Keep all quality measurements unknown until every finding is adjudicated."""
    findings = result["findings"]
    result_hash = findings_sha256(result)
    scored = {
        "candidate_matches": _candidate_matches(case, findings),
        "confirmed": False, "defect_hits": [],
        "defect_total": len(case["defects"]), "recall": None,
        "false_positives": None, "true_positive_findings": None,
        "valid_extra_findings": None, "duplicate_findings": None,
        "precision": None, "findings_sha256": result_hash,
    }
    if adjudication is None:
        return scored
    truth_ids = [defect["id"] for defect in case["defects"]]
    rows = _adjudicated_rows(adjudication, result_hash, len(findings), set(truth_ids))
    counts = {verdict: sum(row["verdict"] == verdict for row in rows)
              for verdict in ("true_positive", "false_positive", "valid_extra", "duplicate")}
    hit_ids = {value for row in rows if row["verdict"] == "true_positive" for value in row["defects"]}
    hits = [value for value in truth_ids if value in hit_ids]
    denominator = len(findings) - counts["duplicate"]
    scored.update(
        confirmed=True, defect_hits=hits,
        recall=len(hits) / len(truth_ids) if truth_ids else None,
        false_positives=counts["false_positive"],
        true_positive_findings=counts["true_positive"],
        valid_extra_findings=counts["valid_extra"], duplicate_findings=counts["duplicate"],
        precision=(counts["true_positive"] + counts["valid_extra"]) / denominator if denominator else None,
    )
    return scored
