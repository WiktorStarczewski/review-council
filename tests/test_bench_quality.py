"""Observable scoring contracts with complete manual dispositions."""
import copy
from pathlib import Path
import unittest


class BenchQualityTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / "eval/bench_quality.py").exists(),
                        "observable quality scorer is missing")
        from eval import bench_quality
        self.q = bench_quality
        self.case = {
            "id": "example", "mode": "evidence", "files": ["a.py", "b.py"],
            "defects": [
                {"id": "critical", "severity": "P1", "file": "a.py", "line_start": 4,
                 "line_end": 6, "keyword_groups": [["bug"]]},
                {"id": "clock", "severity": "P2", "file": "b.py", "line_start": 10,
                 "line_end": 12, "keyword_groups": [["bug"]]}],
            "behavior_rubric": {
                "schema_version": 1, "measurement": "Observable exposure and hypotheses",
                "critical_flows": [
                    {"id": "a-flow", "required_sources": [self.source("a.py", 4, 6)],
                     "rationale": "Inspect the critical state transition."},
                    {"id": "b-flow", "required_sources": [self.source("b.py", 10, 12)],
                     "rationale": "Inspect readiness."}],
                "hypotheses": [
                    {"id": "state", "description": "A stale generation changes state.",
                     "required_sources": [self.source("a.py", 4, 6)]}]},
        }
        self.result = {"summary": "Verified two defects", "findings": [
            self.finding("a.py", 4, 6), self.finding("b.py", 10, 12)]}
        self.audit = {
            "schema_version": 2, "status": "valid", "violations": [],
            "prompt_sha256": "1" * 64, "stream_sha256": "2" * 64,
            "result_sha256": "3" * 64, "evidence_manifest_sha256": "4" * 64,
            "source_ranges": [dict(self.source("a.py", 1, 6), origin="tool"),
                              dict(self.source("b.py", 9, 12), origin="tool")]}
        self.rows = [
            {"finding": 0, "verdict": "true_positive", "defects": ["critical"],
             "reason": "The state change at a.py:4-6 was reproduced."},
            {"finding": 1, "verdict": "true_positive", "defects": ["clock"],
             "reason": "The readiness error at b.py:10-12 was reproduced."}]

    @staticmethod
    def source(path, start, end):
        return {"path": path, "line_start": start, "line_end": end}

    @staticmethod
    def finding(path, start, end):
        return {"severity": "P1", "file": path, "line_start": start, "line_end": end,
                "claim": "Reproduced bug", "evidence": "Source and reproduction.",
                "suggested_fix": "Fix the transition.", "confidence": 0.9}

    def inputs(self):
        correctness = {"findings_sha256": self.q.canonical_sha256(self.result),
                       "dispositions": copy.deepcopy(self.rows)}
        rubric = self.case.get("behavior_rubric")
        behavior = {
            "schema_version": 1, "case_sha256": self.q.canonical_sha256(self.case),
            "rubric_sha256": self.q.canonical_sha256(rubric) if rubric else None,
            "findings_sha256": self.q.canonical_sha256(self.result),
            "audit_sha256": self.q.canonical_sha256(self.audit),
            "evidence_manifest_sha256": self.audit["evidence_manifest_sha256"],
            "citations": [{"finding": index, "verdict": "accurate",
                           "reason": "The source contains the reproduced transition."}
                          for index in range(len(self.result["findings"]))],
            "hypotheses": [{"hypothesis": row["id"], "verdict": "verified",
                            "reason": "The transition was checked with a concrete reproduction."}
                           for row in (rubric or {}).get("hypotheses", [])]}
        provenance = {key: behavior[key] for key in (
            "case_sha256", "findings_sha256", "audit_sha256", "evidence_manifest_sha256")}
        provenance["snapshot_tree"] = "a" * 40
        return correctness, behavior, provenance

    def score(self):
        correctness, behavior, provenance = self.inputs()
        return self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                                verified_provenance=provenance)

    def test_fixed_components_and_truth_severity(self):
        self.result["findings"][1]["severity"] = "P0"
        score = self.score()
        self.assertEqual(score["quality_score"], 100)
        self.assertEqual(score["core_score"], 80)
        self.assertEqual(score["critical_defects"], ["critical"])
        self.assertEqual([row["points"] for row in score["components"].values()],
                         [55, 15, 10, 15, 5])

    def test_no_scores_before_complete_correctness(self):
        _, behavior, provenance = self.inputs()
        score = self.q.score_run(self.case, self.result, None, self.audit, behavior,
                                 verified_provenance=provenance)
        self.assertFalse(score["confirmed"])
        self.assertIsNone(score["quality_score"])
        self.assertTrue(all(row["points"] is None for row in score["components"].values()))

    def test_stale_incomplete_duplicate_correctness_rejected(self):
        correctness, behavior, provenance = self.inputs()
        for change in (dict(correctness, findings_sha256="0" * 64),
                       dict(correctness, dispositions=self.rows[:1]),
                       dict(correctness, dispositions=[self.rows[0], self.rows[0]])):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.q.score_run(self.case, self.result, change, self.audit, behavior,
                                 verified_provenance=provenance)

    def test_unavailable_is_not_rescaled_and_legacy_is_screening(self):
        correctness, behavior, _ = self.inputs()
        score = self.q.score_run(self.case, self.result, correctness, self.audit, behavior)
        self.assertEqual(score["core_score"], 80)
        self.assertIsNone(score["quality_score"])
        self.assertIn("verified-provenance", score["unavailable"])
        self.assertIsNone(score["components"]["critical_flow_coverage"]["value"])
        score = self.q.score_run(self.case, self.result, correctness, self.audit, None)
        self.assertIsNone(score["core_score"])
        del self.case["behavior_rubric"]
        self.assertEqual(self.score()["core_score"], 80)
        self.assertIsNone(self.score()["quality_score"])

    def test_missing_truth_severity_unknown(self):
        del self.case["defects"][1]["severity"]
        score = self.score()
        self.assertIsNone(score["weighted_recall"])
        self.assertIsNone(score["quality_score"])
        self.assertIn("truth-severity", score["unavailable"])

    def test_weighted_recall_and_nonduplicate_precision_math(self):
        self.result["findings"].extend([self.finding("a.py", 2, 3)] * 3)
        self.rows.extend([
            {"finding": 2, "verdict": "valid_extra", "defects": [], "reason": "Reproduced an extra bug."},
            {"finding": 3, "verdict": "false_positive", "defects": [], "reason": "The source handles this."},
            {"finding": 4, "verdict": "duplicate", "defects": [], "reason": "Repeats the first claim."}])
        score = self.score()
        self.assertEqual(score["components"]["precision"]["value"], 0.75)
        self.assertEqual(score["components"]["citation_accuracy"]["value"], 0.75)
        self.assertEqual(score["quality_score"], 93.75)
        self.result["findings"] = self.result["findings"][:1]
        self.rows = self.rows[:1]
        score = self.score()
        self.assertAlmostEqual(score["weighted_recall"], 4 / 6)
        self.assertAlmostEqual(score["core_score"], 55 * 4 / 6 + 25)

    def test_invalid_audit_keeps_core_noncertifying(self):
        self.audit.update(status="invalid", violations=[
            {"code": "decision-digest-output-mismatch", "tool": "command_execution"}])
        score = self.score()
        self.assertEqual(score["core_score"], 80)
        self.assertIsNone(score["quality_score"])
        self.assertIn("valid-audit", score["unavailable"])
        self.audit["status"] = "valid"
        with self.assertRaises(ValueError):
            self.score()

    def test_git_sha256_trees_and_malformed_audit_violations(self):
        correctness, behavior, provenance = self.inputs()
        self.audit["source_ranges"][0]["origin"] = "packet"
        behavior["audit_sha256"] = self.q.canonical_sha256(self.audit)
        provenance["audit_sha256"] = behavior["audit_sha256"]
        provenance["snapshot_tree"] = "a" * 64
        provenance["snapshot_packet_ranges"] = [dict(self.source("a.py", 1, 6), blob_tree="a" * 64)]
        self.assertEqual(self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                         verified_provenance=provenance)["quality_score"], 100)
        self.audit["status"] = "invalid"
        for row in ("missing-source-proof", {"code": "", "tool": "command_execution"},
                    {"code": "bad", "tool": "command_execution", "unknown": True}):
            self.audit["violations"] = [row]
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.score()

    def test_malformed_rubric_and_truth_rejected(self):
        original = copy.deepcopy(self.case)
        for field in ("critical_flows", "hypotheses"):
            self.case = copy.deepcopy(original)
            self.case["behavior_rubric"][field].append(copy.deepcopy(self.case["behavior_rubric"][field][0]))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.score()
        self.case = copy.deepcopy(original)
        self.case["defects"][0]["severity"] = []
        with self.assertRaises(ValueError):
            self.score()

    def test_manual_inaccurate_and_bug_range_overlap(self):
        self.result["findings"][0].update(line_start=1, line_end=2)
        self.assertEqual(self.score()["quality_score"], 95)
        self.result["findings"][0].update(line_start=4, line_end=6)
        correctness, behavior, provenance = self.inputs()
        behavior["citations"][0]["verdict"] = "inaccurate"
        self.assertEqual(self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                         verified_provenance=provenance)["quality_score"], 95)

    def test_gapless_every_file_coverage_ignores_summary_and_counters(self):
        self.audit["source_ranges"] = [
            dict(self.source("a.py", 1, 4), origin="tool"),
            dict(self.source("a.py", 6, 6), origin="tool"),
            dict(self.source("b.py", 9, 12), origin="tool")]
        self.audit["finding_citations"] = 999
        self.result["summary"] = "Inspected a.py and b.py thoroughly."
        score = self.score()
        self.assertEqual(score["components"]["critical_flow_coverage"]["value"], 0.5)
        self.assertEqual(score["quality_score"], 87.5)
        self.case["behavior_rubric"]["critical_flows"][1]["required_sources"].append(
            self.source("a.py", 4, 6))
        self.assertEqual(self.score()["components"]["critical_flow_coverage"]["value"], 0)

    def test_duplicate_ranges_and_adjacent_windows(self):
        self.audit["source_ranges"] = [
            dict(self.source("a.py", 4, 4), origin="tool"),
            dict(self.source("a.py", 5, 6), origin="tool"),
            dict(self.source("b.py", 10, 12), origin="tool")] * 3
        self.assertEqual(self.score()["quality_score"], 100)

    def test_current_packets_qualified_and_base_or_forged_excluded(self):
        self.audit["source_ranges"] = [
            dict(row, origin="packet") for row in (
                self.source("a.py", 1, 6), self.source("b.py", 9, 12))]
        correctness, behavior, provenance = self.inputs()
        self.assertEqual(self.score()["quality_score"], 80)
        provenance["snapshot_packet_ranges"] = [
            dict(self.source("a.py", 1, 6), blob_tree="a" * 40),
            dict(self.source("b.py", 9, 12), blob_tree="b" * 40)]
        self.assertEqual(self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                         verified_provenance=provenance)["quality_score"], 92.5)
        provenance["snapshot_packet_ranges"][1]["blob_tree"] = "a" * 40
        self.assertEqual(self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                         verified_provenance=provenance)["quality_score"], 100)
        provenance["snapshot_packet_ranges"][0]["line_end"] = 7
        with self.assertRaises(ValueError):
            self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                             verified_provenance=provenance)

    def test_forged_audit_and_provenance_rejected(self):
        correctness, behavior, provenance = self.inputs()
        changed = copy.deepcopy(self.audit)
        changed["source_ranges"][0]["line_end"] = 100
        with self.assertRaises(ValueError):
            self.q.score_run(self.case, self.result, correctness, changed, behavior,
                             verified_provenance=provenance)
        behavior["audit_sha256"] = self.q.canonical_sha256(changed)
        with self.assertRaises(ValueError):
            self.q.score_run(self.case, self.result, correctness, changed, behavior,
                             verified_provenance=provenance)

    def test_malformed_ranges_and_duplicate_manual_rows_rejected(self):
        for row in (dict(self.source("a.py", True, 6), origin="tool"),
                    dict(self.source("../a.py", 1, 6), origin="tool"),
                    dict(self.source("a.py", 7, 6), origin="tool"),
                    dict(self.source("a.py", 1, 6), origin="summary")):
            self.audit["source_ranges"] = [row]
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.score()
        self.audit["source_ranges"] = []
        for field in ("citations", "hypotheses"):
            correctness, behavior, provenance = self.inputs()
            behavior[field].append(copy.deepcopy(behavior[field][0]))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                                 verified_provenance=provenance)

    def test_clean_empty_and_defective_empty_explicit(self):
        self.result["findings"] = []
        self.rows = []
        self.assertEqual(self.score()["core_score"], 0)
        self.assertEqual(self.score()["quality_score"], 20)
        self.case["defects"] = []
        score = self.score()
        self.assertEqual(score["core_score"], 80)
        self.assertEqual(score["quality_score"], 100)
        self.assertIsNone(score["weighted_recall"])
        self.assertIn("clean", score["clean_case_semantics"])

    def test_novel_substitution_has_one_cap_and_no_verbosity_reward(self):
        correctness, behavior, provenance = self.inputs()
        behavior["hypotheses"][0]["verdict"] = "untested"
        behavior["novel_scenarios"] = [
            {"id": "novel-" + str(index), "verdict": "refuted", "reason": "a.py:4-6 handles this.",
             "required_sources": [self.source("a.py", 4, 6)]} for index in range(3)]
        score = self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                                verified_provenance=provenance)
        self.assertEqual(score["quality_score"], 100)
        self.assertEqual(score["novel_scenarios"]["substitutions"], 1)
        for row in behavior["novel_scenarios"]:
            row["verdict"] = "speculative"
            row["reason"] *= 20
        self.assertEqual(self.q.score_run(self.case, self.result, correctness, self.audit, behavior,
                         verified_provenance=provenance)["quality_score"], 95)

    def test_comparison_requires_full_credible_valid_matching_scores(self):
        score = self.score()
        baseline = {"valid": True, "run_quality": score}
        self.assertTrue(self.q.compare_quality(baseline, copy.deepcopy(baseline))["acceptable"])
        for field, value in (("quality_score", None), ("quality_score", 89),
                             ("weighted_recall", 0.89), ("critical_hits", []),
                             ("false_positives", 1), ("case_sha256", "0" * 64)):
            candidate = copy.deepcopy(baseline)
            candidate["run_quality"][field] = value
            with self.subTest(field=field):
                self.assertFalse(self.q.compare_quality(baseline, candidate)["acceptable"])
        self.assertFalse(self.q.compare_quality(baseline, dict(baseline, valid=False))["acceptable"])

    def test_small_lower_severity_loss_allowed_and_policy_frozen(self):
        primary = self.case["defects"][0]
        self.case["defects"] = [dict(primary, id="critical-" + str(index)) for index in range(10)] + [
            dict(self.case["defects"][1], severity="P3")]
        self.rows[0]["defects"] = [row["id"] for row in self.case["defects"][:-1]]
        baseline = {"valid": True, "run_quality": self.score()}
        self.result["findings"] = self.result["findings"][:1]
        self.rows = self.rows[:1]
        candidate = {"valid": True, "run_quality": self.score()}
        comparison = self.q.compare_quality(baseline, candidate)
        self.assertTrue(comparison["acceptable"])
        self.assertAlmostEqual(comparison["quality_delta"], -55 / 41)
        self.assertEqual(comparison["policy_sha256"], self.q.canonical_sha256(comparison["policy"]))
        candidate["run_quality"]["critical_hits"].pop()
        loose = dict(comparison["policy"], minimum_quality=0, minimum_weighted_recall=0,
                     quality_delta_tolerance=100, allow_added_false_positives=True)
        self.assertIn("lost-critical-defect", self.q.compare_quality(baseline, candidate, policy=loose)["reasons"])
        for key, value in (("quality_delta_tolerance", True), ("minimum_quality", float("nan")),
                           ("minimum_weighted_recall", 2), ("allow_added_false_positives", 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.q.compare_quality(baseline, candidate, policy=dict(comparison["policy"], **{key: value}))


if __name__ == "__main__":
    unittest.main()
