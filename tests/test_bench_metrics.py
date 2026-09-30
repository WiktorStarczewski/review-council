"""Provider-free benchmark accounting regressions."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
METRICS = REPO / "eval/bench_metrics.py"


class BenchMetricsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(METRICS.exists(), "benchmark metrics collector is not implemented")
        spec = importlib.util.spec_from_file_location("bench_metrics", METRICS)
        self.metrics = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.metrics)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def stream(self, records):
        path = self.root / "stream.ndjson"
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        return path

    def terminal(self, usage=None, **extra):
        return {"type": "turn.completed", "usage": usage or {
            "input_tokens": 100, "cached_input_tokens": 20,
            "cache_write_input_tokens": 10, "output_tokens": 11,
            "reasoning_output_tokens": 4,
        }, **extra}

    def test_single_terminal_normalizes_reported_token_categories(self):
        result = self.metrics.measure_stream(self.stream([self.terminal(cost_usd=0.4)]))
        self.assertEqual(result["terminal_count"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["provider_errors"], [])
        self.assertEqual(result["usage"]["input_tokens"], 100)
        self.assertEqual(result["usage"]["cached_input_tokens"], 20)
        self.assertEqual(result["usage"]["uncached_input_tokens"], 70)
        self.assertEqual(result["usage"]["cache_write_input_tokens"], 10)
        self.assertEqual(result["usage"]["output_tokens"], 11)
        self.assertEqual(result["usage"]["reasoning_output_tokens"], 4)
        self.assertEqual(result["usage"]["processed_tokens"], 111)
        self.assertEqual(result["usage"]["cost_usd"], 0.4)
        self.assertTrue(result["usage"]["cache_reported"])
        self.assertTrue(result["usage"]["reasoning_reported"])

    def test_tool_calls_deduplicate_completed_item_identities(self):
        records = [
            {"type": "item.started", "item": {"id": "cmd", "type": "command_execution"}},
            {"type": "item.completed", "item": {"id": "cmd", "type": "command_execution"}},
            {"type": "item.completed", "item": {"id": "cmd", "type": "command_execution"}},
            {"type": "item.completed", "item": {"id": "mcp", "type": "mcp_tool_call"}},
            {"type": "item.completed", "item": {"id": "search", "type": "web_search"}},
            {"type": "item.completed", "item": {"id": "message", "type": "agent_message"}},
            self.terminal(),
        ]
        result = self.metrics.measure_stream(self.stream(records))
        self.assertEqual(result["tool_calls"], 3)
        self.assertEqual(result["errors"], [])

    def test_missing_cache_remains_unknown_with_usable_totals(self):
        result = self.metrics.measure_stream(self.stream([self.terminal({
            "input_tokens": 100, "output_tokens": 11,
        })]))
        self.assertEqual(result["usage"]["input_tokens"], 100)
        self.assertEqual(result["usage"]["processed_tokens"], 111)
        self.assertIsNone(result["usage"]["cached_input_tokens"])
        self.assertIsNone(result["usage"]["uncached_input_tokens"])
        self.assertFalse(result["usage"]["cache_reported"])

    def test_missing_reasoning_and_dollars_remain_unknown(self):
        result = self.metrics.measure_stream(self.stream([self.terminal({
            "input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 11,
        })]))
        self.assertIsNone(result["usage"]["reasoning_output_tokens"])
        self.assertFalse(result["usage"]["reasoning_reported"])
        self.assertIsNone(result["usage"]["cost_usd"])

    def test_explicit_zero_values_remain_known(self):
        result = self.metrics.measure_stream(self.stream([self.terminal({
            "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
            "reasoning_output_tokens": 0, "cost_usd": 0,
        })]))
        self.assertEqual(result["usage"]["processed_tokens"], 0)
        self.assertEqual(result["usage"]["cost_usd"], 0)
        self.assertEqual(result["usage"]["reasoning_output_tokens"], 0)
        self.assertTrue(result["usage"]["cache_reported"])
        self.assertTrue(result["usage"]["reasoning_reported"])

    def test_reasoning_detail_is_reported_without_adding_it_to_output(self):
        for field in ("reasoning_tokens", "thinking_tokens"):
            with self.subTest(field=field):
                result = self.metrics.measure_stream(self.stream([self.terminal({
                    "input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 11,
                    "output_tokens_details": {field: 4},
                })]))
                self.assertTrue(result["usage"]["reasoning_reported"])
                self.assertEqual(result["usage"]["reasoning_output_tokens"], 4)
                self.assertEqual(result["usage"]["processed_tokens"], 111)

    def test_input_and_output_must_be_explicitly_reported(self):
        for missing in ("input_tokens", "output_tokens"):
            with self.subTest(missing=missing):
                terminal = self.terminal()
                terminal["usage"].pop(missing)
                result = self.metrics.measure_stream(self.stream([terminal]))
                self.assertIsNone(result["usage"])
                self.assertTrue(result["errors"])

    def test_multiple_terminal_envelopes_are_ambiguous(self):
        for other_type in ("turn.completed", "result", "end"):
            with self.subTest(other_type=other_type):
                second = self.terminal()
                second["type"] = other_type
                result = self.metrics.measure_stream(self.stream([self.terminal(), second]))
                self.assertEqual(result["terminal_count"], 2)
                self.assertIsNone(result["usage"])
                self.assertTrue(result["errors"])

    def test_other_provider_terminal_is_unsupported(self):
        terminal = self.terminal()
        terminal["type"] = "result"
        result = self.metrics.measure_stream(self.stream([terminal]))
        self.assertEqual(result["terminal_count"], 1)
        self.assertIsNone(result["usage"])
        self.assertTrue(result["errors"])

    def test_malformed_json_retains_usable_terminal_usage(self):
        path = self.stream([self.terminal()])
        path.write_text("{broken\n" + path.read_text())
        result = self.metrics.measure_stream(path)
        self.assertEqual(result["terminal_count"], 1)
        self.assertEqual(result["usage"]["processed_tokens"], 111)
        self.assertTrue(result["errors"])
        self.assertIn("line 1", result["errors"][0])

    def test_unreadable_or_missing_terminal_never_becomes_zero_usage(self):
        for path in (self.root / "absent", self.stream([])):
            with self.subTest(path=path.name):
                result = self.metrics.measure_stream(path)
                self.assertIsNone(result["usage"])
                self.assertEqual(result["terminal_count"], 0)
                self.assertTrue(result["errors"])

    def test_malformed_usage_is_rejected(self):
        bad_usage = [None, [], {},
                     {"input_tokens": -1, "cached_input_tokens": 0, "output_tokens": 1},
                     {"input_tokens": True, "cached_input_tokens": 0, "output_tokens": 1},
                     {"input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 1},
                     {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1,
                      "reasoning_output_tokens": 2},
                     {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1,
                      "cost_usd": float("nan")}]
        for usage in bad_usage:
            with self.subTest(usage=usage):
                result = self.metrics.measure_stream(self.stream([
                    {"type": "turn.completed", "usage": usage}]))
                self.assertIsNone(result["usage"])
                self.assertTrue(result["errors"])

    def test_non_object_json_records_are_invalid_but_do_not_hide_usage(self):
        result = self.metrics.measure_stream(self.stream([[], self.terminal()]))
        self.assertEqual(result["usage"]["processed_tokens"], 111)
        self.assertTrue(result["errors"])

    def test_missing_tool_identity_is_visible_and_not_counted(self):
        result = self.metrics.measure_stream(self.stream([
            {"type": "item.completed", "item": {"type": "command_execution"}},
            self.terminal(),
        ]))
        self.assertEqual(result["tool_calls"], 0)
        self.assertTrue(result["errors"])

    def test_provider_error_events_are_retained_with_bounded_text(self):
        result = self.metrics.measure_stream(self.stream([
            {"type": "error", "message": "quota " + "x" * 5000},
            {"type": "turn.failed", "error": {"message": "execution failed"}},
            self.terminal(),
        ]))
        self.assertEqual(result["usage"]["processed_tokens"], 111)
        self.assertEqual(len(result["provider_errors"]), 2)
        self.assertIn("quota", result["provider_errors"][0])
        self.assertIn("execution failed", result["provider_errors"][1])
        self.assertTrue(all(len(error) <= 500 for error in result["provider_errors"]))

    def test_error_collection_is_bounded_without_hiding_an_invalid_stream(self):
        records = [{"type": "error", "message": str(index)} for index in range(100)]
        result = self.metrics.measure_stream(self.stream(records))
        self.assertGreater(len(result["provider_errors"]), 0)
        self.assertLessEqual(len(result["provider_errors"]), 32)
        self.assertIsNone(result["usage"])
        self.assertTrue(result["errors"])

    def test_malformed_event_fields_do_not_hide_a_terminal(self):
        result = self.metrics.measure_stream(self.stream([
            {"type": []},
            {"type": "item.completed", "item": {"id": "bad", "type": []}},
            self.terminal(),
        ]))
        self.assertEqual(result["usage"]["processed_tokens"], 111)
        self.assertEqual(result["tool_calls"], 0)
        self.assertTrue(result["errors"])

    def test_explicit_frozen_collector_is_used_for_usage(self):
        helper = self.root / "frozen-usage.py"
        helper.write_bytes((REPO / "plugins/review-council/scripts/lib/usage.py").read_bytes())
        with patch.object(self.metrics._NORMALIZER, "record_usage", side_effect=RuntimeError):
            result = self.metrics.measure_stream(self.stream([self.terminal()]),
                                                 collector_path=helper)
        self.assertEqual(result["usage"]["processed_tokens"], 111)
        self.assertEqual(result["usage"]["uncached_input_tokens"], 70)
        self.assertEqual(result["errors"], [])

    def rate_card(self):
        path = REPO / "eval/rates/codex-standard-2026-09-29.json"
        self.assertTrue(path.exists(), "dated rate card is not implemented")
        return json.loads(path.read_text())

    def estimate(self, usage):
        self.assertTrue(hasattr(self.metrics, "credit_estimate"),
                        "estimated credit accounting is not implemented")
        return self.metrics.credit_estimate(usage, self.rate_card())

    def test_credit_estimate_prices_output_once_and_includes_cache_write_in_input(self):
        result = self.metrics.measure_stream(self.stream([self.terminal({
            "input_tokens": 1000000, "cached_input_tokens": 200000,
            "cache_write_input_tokens": 100000, "output_tokens": 50000,
            "reasoning_output_tokens": 20000,
        })]))
        self.assertEqual(self.estimate(result["usage"]), 56.0)
        self.assertIsNone(result["usage"]["cost_usd"])

    def test_missing_cache_prevents_a_credit_estimate(self):
        for usage in (None, {"input_tokens": 100, "output_tokens": 11},
                      {"input_tokens": 100, "cached_input_tokens": None, "output_tokens": 11},
                      {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 11,
                       "cache_reported": False}):
            with self.subTest(usage=usage):
                self.assertIsNone(self.estimate(usage))

    def test_zero_tokens_have_a_known_zero_credit_estimate(self):
        result = self.metrics.measure_stream(self.stream([self.terminal({
            "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
        })]))
        self.assertEqual(self.estimate(result["usage"]), 0.0)

    def test_invalid_token_values_cannot_produce_a_credit_estimate(self):
        for value in (True, -1, float("nan"), "100", None):
            with self.subTest(value=value):
                self.assertIsNone(self.estimate({
                    "input_tokens": value, "cached_input_tokens": 0, "output_tokens": 11,
                }))
        self.assertIsNone(self.estimate({
            "input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 1,
        }))

    def row(self, variant, **overrides):
        return {"case": "case-a", "variant": variant, "wall_seconds": 20,
                "usage": {"input_tokens": 100, "cached_input_tokens": 20,
                          "uncached_input_tokens": 70, "output_tokens": 40,
                          "reasoning_output_tokens": None, "processed_tokens": 140},
                "estimated_credits": 0.02, "status": "ok", "quality": {},
                "valid": True, "prompt_words": 100, "prompt_bytes": 400, **overrides}

    def pairs(self, rows):
        self.assertTrue(hasattr(self.metrics, "paired_deltas"),
                        "paired benchmark comparison is not implemented")
        return self.metrics.paired_deltas(rows)

    def test_paired_deltas_preserve_each_metric_and_its_direction(self):
        candidate = self.row("candidate", wall_seconds=15, estimated_credits=0.01,
                             prompt_words=50, prompt_bytes=200,
                             usage={"input_tokens": 80, "cached_input_tokens": 40,
                                    "uncached_input_tokens": 40, "output_tokens": 10,
                                    "reasoning_output_tokens": 2, "processed_tokens": 90})
        pair, = self.pairs([self.row("baseline"), candidate])
        self.assertEqual(pair["case"], "case-a")
        self.assertEqual(pair["baseline_status"], "ok")
        self.assertEqual(pair["candidate_status"], "ok")
        self.assertTrue(pair["valid_pair"])
        self.assertEqual(pair["metrics"]["wall_seconds"], {
            "baseline": 20, "candidate": 15, "reduction_percent": 25.0,
        })
        for metric, expected in {
            "input_tokens": 20.0, "cached_input_tokens": -100.0,
            "uncached_input_tokens": 42.857142857142854, "output_tokens": 75.0,
            "processed_tokens": 35.714285714285715, "estimated_credits": 50.0,
            "prompt_words": 50.0, "prompt_bytes": 50.0,
        }.items():
            with self.subTest(metric=metric):
                self.assertAlmostEqual(pair["metrics"][metric]["reduction_percent"], expected)
        self.assertEqual(pair["metrics"]["reasoning_output_tokens"], {
            "baseline": None, "candidate": 2, "reduction_percent": None,
        })

    def test_failed_pair_retains_raw_usage_without_savings(self):
        pair, = self.pairs([self.row("baseline"), self.row(
            "candidate", status="failed", valid=False, wall_seconds=1,
            usage={"input_tokens": 1})])
        self.assertFalse(pair["valid_pair"])
        self.assertEqual(pair["candidate_status"], "failed")
        self.assertEqual(pair["metrics"]["input_tokens"]["candidate"], 1)
        self.assertTrue(all(metric["reduction_percent"] is None
                            for metric in pair["metrics"].values()))

    def test_missing_partner_or_usage_is_unknown_not_zero(self):
        pair, = self.pairs([self.row("candidate", usage=None)])
        self.assertFalse(pair["valid_pair"])
        self.assertIsNone(pair["baseline_status"])
        self.assertEqual(pair["metrics"]["wall_seconds"], {
            "baseline": None, "candidate": 20, "reduction_percent": None,
        })
        self.assertEqual(pair["metrics"]["input_tokens"], {
            "baseline": None, "candidate": None, "reduction_percent": None,
        })

    def test_zero_baseline_has_no_reduction_percentage(self):
        pair, = self.pairs([self.row("baseline", wall_seconds=0, estimated_credits=0),
                           self.row("candidate", wall_seconds=5, estimated_credits=0)])
        self.assertTrue(pair["valid_pair"])
        self.assertEqual(pair["metrics"]["wall_seconds"], {
            "baseline": 0, "candidate": 5, "reduction_percent": None,
        })
        self.assertIsNone(pair["metrics"]["estimated_credits"]["reduction_percent"])

    def test_duplicate_case_variant_is_rejected(self):
        with self.assertRaises(ValueError):
            self.pairs([self.row("baseline"), self.row("baseline")])

    def test_unknown_variant_is_rejected(self):
        with self.assertRaises(ValueError):
            self.pairs([self.row("other")])

    def test_pairs_keep_cases_separate(self):
        pairs = self.pairs([self.row("baseline"),
                            self.row("candidate", case="case-b"),
                            self.row("candidate")])
        self.assertEqual([pair["case"] for pair in pairs], ["case-a", "case-b"])
        self.assertTrue(pairs[0]["valid_pair"])
        self.assertFalse(pairs[1]["valid_pair"])


if __name__ == "__main__":
    unittest.main()
