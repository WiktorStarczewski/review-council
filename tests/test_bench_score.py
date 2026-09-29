"""Sealed correctness fixtures and hash-bound human adjudication."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCORE = REPO / "eval/bench_score.py"
FIXTURES = REPO / "eval/fixtures/cost-v1"


def load_scorer(test):
    test.assertTrue(SCORE.exists(), "sealed correctness scorer is not implemented")
    spec = importlib.util.spec_from_file_location("bench_score", SCORE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finding(**changes):
    row = {
        "severity": "P1", "file": "ledger.py", "line_start": 15, "line_end": 16,
        "claim": "Exact quota boundary rejects a valid credit",
        "evidence": "A total equal to the limit raises ValueError.",
        "suggested_fix": "Accept equality with the limit.", "confidence": 0.9,
    }
    row.update(changes)
    return row


class BenchScoreTests(unittest.TestCase):
    def setUp(self):
        self.scorer = load_scorer(self)
        self.case = {
            "id": "example", "mode": "legacy", "files": ["ledger.py"],
            "lens": "correctness-boundaries",
            "defects": [
                {"id": "quota", "file": "ledger.py", "line_start": 16, "line_end": 18,
                 "description": "Exact quota must be accepted.",
                 "keyword_groups": [["quota", "limit"], ["equality", "equal", "exact"]]},
                {"id": "window", "file": "ledger.py", "line_start": 40, "line_end": 42,
                 "description": "The end of a range must be exclusive.",
                 "keyword_groups": [["end", "upper"], ["exclusive", "half-open"]]},
            ],
        }
        self.result = {"summary": "Two boundary checks", "findings": [finding()]}

    def adjudication(self, rows=None):
        return {
            "findings_sha256": self.scorer.findings_sha256(self.result),
            "dispositions": rows if rows is not None else [
                {"finding": 0, "verdict": "true_positive", "defects": ["quota"],
                 "reason": "The equality rejection was reproduced against the source."},
            ],
        }

    def test_candidates_do_not_confirm_quality_metrics(self):
        scored = self.scorer.score_findings(self.case, self.result)
        self.assertEqual(scored["candidate_matches"], [
            {"finding": 0, "defects": ["quota"], "provisional": True},
        ])
        self.assertFalse(scored["confirmed"])
        self.assertEqual(scored["defect_hits"], [])
        self.assertEqual(scored["defect_total"], 2)
        for key in ("recall", "false_positives", "precision", "true_positive_findings",
                    "valid_extra_findings", "duplicate_findings"):
            self.assertIsNone(scored[key], key)

    def test_candidate_requires_file_overlapping_range_and_every_group(self):
        rows = [
            finding(file="other/ledger.py"),
            finding(line_start=19, line_end=21),
            finding(claim="Quota rejection", evidence="Bad branch", suggested_fix="Change it"),
            finding(line_start=1, line_end=16, claim="QUOTA", evidence="EQUAL", suggested_fix=""),
        ]
        self.result["findings"] = rows
        self.assertEqual(self.scorer.score_findings(self.case, self.result)["candidate_matches"], [
            {"finding": 3, "defects": ["quota"], "provisional": True},
        ])

    def test_candidate_can_collect_groups_from_fix_and_evidence(self):
        self.result["findings"] = [finding(
            line_start=42, line_end=45, claim="Range iteration overlaps windows",
            evidence="The upper bound is included", suggested_fix="Use an exclusive bound",
        )]
        self.assertEqual(self.scorer.score_findings(self.case, self.result)["candidate_matches"], [
            {"finding": 0, "defects": ["window"], "provisional": True},
        ])

    def test_hash_is_canonical_json_and_binds_the_entire_result(self):
        self.assertEqual(self.scorer.findings_sha256({"summary": "x", "findings": []}),
                         "320d7d78d14bbd000e7664c54e93560c6a43415d74751611d5f21afb3b35f962")
        reordered = {"findings": self.result["findings"], "summary": self.result["summary"]}
        self.assertEqual(self.scorer.findings_sha256(reordered), self.scorer.findings_sha256(self.result))
        changed = dict(self.result, summary="Changed summary")
        self.assertNotEqual(self.scorer.findings_sha256(changed), self.scorer.findings_sha256(self.result))

    def test_complete_adjudication_counts_hits_extras_false_positives_and_duplicates(self):
        self.result["findings"] = [finding() for _ in range(4)]
        rows = [
            {"finding": 0, "verdict": "true_positive", "defects": ["quota", "window"],
             "reason": "One finding demonstrates both behavior failures."},
            {"finding": 1, "verdict": "valid_extra", "defects": [],
             "reason": "A separate reproducible issue outside planted truth."},
            {"finding": 2, "verdict": "false_positive", "defects": [],
             "reason": "The API intentionally rejects invalid inputs."},
            {"finding": 3, "verdict": "duplicate", "defects": [],
             "reason": "Repeats finding zero."},
        ]
        scored = self.scorer.score_findings(self.case, self.result, self.adjudication(rows))
        self.assertTrue(scored["confirmed"])
        self.assertEqual(scored["defect_hits"], ["quota", "window"])
        self.assertEqual(scored["recall"], 1.0)
        self.assertEqual(scored["false_positives"], 1)
        self.assertEqual(scored["true_positive_findings"], 1)
        self.assertEqual(scored["valid_extra_findings"], 1)
        self.assertEqual(scored["duplicate_findings"], 1)
        self.assertAlmostEqual(scored["precision"], 2 / 3)

    def test_adjudication_does_not_depend_on_keyword_candidates(self):
        self.result["findings"][0].update(claim="Reproduced issue", evidence="See execution", suggested_fix="")
        scored = self.scorer.score_findings(self.case, self.result, self.adjudication())
        self.assertEqual(scored["candidate_matches"], [])
        self.assertEqual(scored["defect_hits"], ["quota"])
        self.assertEqual(scored["recall"], 0.5)

    def test_empty_findings_need_adjudication_and_have_unknown_precision(self):
        self.result["findings"] = []
        initial = self.scorer.score_findings(self.case, self.result)
        self.assertFalse(initial["confirmed"])
        self.assertIsNone(initial["false_positives"])
        scored = self.scorer.score_findings(self.case, self.result, self.adjudication([]))
        self.assertTrue(scored["confirmed"])
        self.assertEqual(scored["recall"], 0.0)
        self.assertEqual(scored["false_positives"], 0)
        self.assertIsNone(scored["precision"])

    def test_duplicate_only_findings_have_unknown_precision(self):
        rows = [{"finding": 0, "verdict": "duplicate", "defects": [], "reason": "Repeated issue."}]
        scored = self.scorer.score_findings(self.case, self.result, self.adjudication(rows))
        self.assertEqual(scored["recall"], 0.0)
        self.assertIsNone(scored["precision"])

    def test_adjudication_rejects_stale_or_missing_hash(self):
        stale = self.adjudication()
        self.result["findings"][0]["evidence"] += " Changed."
        with self.assertRaisesRegex(ValueError, "hash"):
            self.scorer.score_findings(self.case, self.result, stale)
        stale.pop("findings_sha256")
        with self.assertRaises(ValueError):
            self.scorer.score_findings(self.case, self.result, stale)

    def test_adjudication_requires_every_finding_exactly_once(self):
        self.result["findings"] = [finding(), finding()]
        row = self.adjudication()["dispositions"][0]
        for rows in ([row], [row, copy.deepcopy(row)], [dict(row, finding=2), dict(row, finding=1)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.scorer.score_findings(self.case, self.result, self.adjudication(rows))

    def test_adjudication_rejects_invalid_fields(self):
        base = self.adjudication()["dispositions"][0]
        invalid = [
            dict(base, finding=True), dict(base, finding=0.0), dict(base, finding=-1),
            dict(base, verdict="unreviewed"), dict(base, reason=" \n "),
            dict(base, reason=None), dict(base, defects=["unknown"]),
            dict(base, defects=[]), dict(base, defects="quota"),
            dict(base, defects=["quota", "quota"]), dict(base, extra="unsupported"),
        ]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.scorer.score_findings(self.case, self.result, self.adjudication([row]))

    def test_non_true_positive_dispositions_cannot_claim_truth_hits(self):
        for verdict in ("false_positive", "valid_extra", "duplicate"):
            row = {"finding": 0, "verdict": verdict, "defects": ["quota"], "reason": "Checked source."}
            with self.subTest(verdict=verdict), self.assertRaises(ValueError):
                self.scorer.score_findings(self.case, self.result, self.adjudication([row]))

    def test_adjudication_rejects_non_object_and_incomplete_rows(self):
        row = self.adjudication()["dispositions"][0]
        for invalid in (None, 3, "confirmed", [], {}, {"finding": 0}, dict(row, defects=[None])):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.scorer.score_findings(self.case, self.result, self.adjudication([invalid]))
        for invalid in ([], "confirmed", {"findings_sha256": self.scorer.findings_sha256(self.result),
                                         "dispositions": {}}, dict(self.adjudication(), extra=True)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.scorer.score_findings(self.case, self.result, invalid)


class SealedFixtureTests(unittest.TestCase):
    def run_oracle(self, root):
        self.assertTrue((root / "oracle.py").exists(), "sealed runtime oracle is not implemented")
        return subprocess.run([sys.executable, str(root / "oracle.py"), "--json"],
                              text=True, capture_output=True, timeout=5)

    def test_oracles_prove_each_plant_baselines_and_clean_controls(self):
        for case_id, mode, defects in (
            ("boundary-ledger", "legacy", {"quota-equality", "exclusive-window-end"}),
            ("cache-isolation", "evidence", {"tenant-key", "nested-read-alias"}),
        ):
            with self.subTest(case=case_id):
                root = FIXTURES / case_id
                self.assertTrue((root / "case.json").exists(), "sealed fixture metadata is not implemented")
                case = json.loads((root / "case.json").read_text())
                self.assertEqual(case["id"], case_id)
                self.assertEqual(case["mode"], mode)
                self.assertEqual({row["id"] for row in case["defects"]}, defects)
                for snapshot in ("before", "after"):
                    files = {str(path.relative_to(root / snapshot)) for path in (root / snapshot).rglob("*")
                             if path.is_file() and "__pycache__" not in path.parts}
                    self.assertEqual(files, set(case["files"]))
                result = self.run_oracle(root)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                proof = json.loads(result.stdout)
                self.assertEqual(proof["case"], case_id)
                self.assertTrue(proof["passed"])
                self.assertTrue(all(row["passed"] for row in proof["checks"]))
                self.assertEqual({row["id"] for row in proof["checks"] if row["kind"] == "defect"}, defects)
                self.assertEqual(sum(row["kind"] == "baseline" for row in proof["checks"]), 2)
                self.assertGreaterEqual(sum(row["kind"] == "clean-control" for row in proof["checks"]), 2)

    def test_oracles_fail_if_the_regressions_are_removed(self):
        for case_id in ("boundary-ledger", "cache-isolation"):
            with self.subTest(case=case_id), tempfile.TemporaryDirectory() as temp:
                original = FIXTURES / case_id
                self.assertTrue(original.exists(), "sealed fixture is not implemented")
                root = Path(temp) / case_id
                shutil.copytree(original, root)
                case = json.loads((root / "case.json").read_text())
                for source in case["files"]:
                    target = root / "after" / source
                    target.chmod(target.stat().st_mode | 0o200)
                    shutil.copyfile(root / "before" / source, target)
                result = self.run_oracle(root)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                proof = json.loads(result.stdout)
                self.assertFalse(proof["passed"])
                self.assertTrue(all(not row["passed"] for row in proof["checks"] if row["kind"] == "defect"))
                self.assertTrue(all(row["passed"] for row in proof["checks"] if row["kind"] != "defect"))


if __name__ == "__main__":
    unittest.main()
