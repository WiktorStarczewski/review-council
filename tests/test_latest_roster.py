"""Provider-free latest-family roster selection regressions."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROSTER = Path(__file__).resolve().parents[1] / "plugins/review-council/scripts/lib/roster.py"


class LatestRosterTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("latest_roster", ROSTER)
        self.roster = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.roster)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "catalog.json"
        self.models = [self.model("gpt-9.9-sol"), self.model("gpt-9.10-sol"),
                       self.model("gpt-8-luna"), self.model("gpt-10-astra"),
                       self.model("gpt-99-sol", visibility="hide")]
        self.write_catalog()
        self.cfg = {"codex_models": ["latest-sol", "latest-luna"],
                    "codex_effort": "xhigh", "claude_models": ["opus", "sonnet"],
                    "claude_adapter": "agent", "exclude": ["gemini"]}

    def model(self, slug, efforts=("high", "xhigh", "max"), visibility="list"):
        return {"slug": slug, "visibility": visibility, "priority": 1,
                "supported_reasoning_levels": [{"effort": effort} for effort in efforts]}

    def write_catalog(self):
        self.cache.write_text(json.dumps({"models": self.models}))

    def build(self, cfg=None, probe=False, status=None, quota_failed=()):
        environment = {"REVIEW_COUNCIL_CODEX_MODELS_CACHE": str(self.cache)}
        with patch.dict(os.environ, environment), \
                patch.object(self.roster, "load_config", return_value=(cfg or self.cfg, None)), \
                patch.object(self.roster.shutil, "which", return_value="/fake/codex"), \
                patch.object(self.roster, "status_check", side_effect=status or
                             (lambda *args: (True, None, "logged in"))):
            return self.roster.build(probe, quota_failed)

    def test_latest_families_use_numeric_generations_and_ignore_hidden_and_other_families(self):
        effective, error, strict = self.roster.resolve_codex_config(self.cfg, self.cache)
        self.assertIsNone(error)
        self.assertIsNone(strict)
        self.assertEqual(effective["codex_models"], ["gpt-9.10-sol", "gpt-8-luna"])
        self.assertEqual(effective["codex_effort"], "xhigh")
        self.assertEqual(self.cfg["codex_models"], ["latest-sol", "latest-luna"])

    def test_each_resolution_reads_current_catalog_without_pinning_a_generation(self):
        first, _, _ = self.roster.resolve_codex_config(self.cfg, self.cache)
        self.models.append(self.model("gpt-11-sol"))
        self.write_catalog()
        second, _, _ = self.roster.resolve_codex_config(self.cfg, self.cache)
        self.assertEqual(first["codex_models"][0], "gpt-9.10-sol")
        self.assertEqual(second["codex_models"][0], "gpt-11-sol")

    def test_newest_family_without_requested_effort_refuses_instead_of_using_older_model(self):
        self.models.append(self.model("gpt-11-sol", efforts=("max", "high")))
        self.write_catalog()
        _, error, strict = self.roster.resolve_codex_config(self.cfg, self.cache)
        self.assertEqual(strict, "config")
        self.assertIn("gpt-11-sol", error)
        self.assertIn("xhigh", error)
        with patch.object(self.roster, "probe_seat") as probe:
            result, _, strict = self.build(probe=True)
        self.assertEqual(strict, "config")
        self.assertEqual(result["seats"], [])
        probe.assert_not_called()

    def test_missing_family_and_unreadable_cache_are_retryable_without_provider_calls(self):
        self.models = [model for model in self.models if not model["slug"].endswith("-luna")]
        self.write_catalog()
        _, error, strict = self.roster.resolve_codex_config(self.cfg, self.cache)
        self.assertEqual(strict, "availability")
        self.assertIn("latest-luna", error)
        self.cache.unlink()
        _, error, strict = self.roster.resolve_codex_config(self.cfg, self.cache)
        self.assertEqual(strict, "availability")
        self.assertIn("unavailable", error)

    def test_exact_config_and_default_effort_remain_unchanged(self):
        cfg = {**self.cfg, "codex_models": ["gpt-9.9-sol", "gpt-8-luna"]}
        del cfg["codex_effort"]
        effective, error, strict = self.roster.resolve_codex_config(cfg, self.cache)
        self.assertEqual(effective, cfg)
        self.assertIsNone(error)
        self.assertIsNone(strict)
        result, _, _ = self.build(cfg)
        core = [seat for seat in result["seats"] if seat["adapter"] == "codex" and not seat["extra"]]
        self.assertEqual([seat["model"] for seat in core], cfg["codex_models"])
        self.assertEqual([seat["effort"] for seat in core], ["xhigh", "xhigh"])

    def test_resolution_is_frozen_before_login_probe_pins_and_extras(self):
        cfg = {**self.cfg, "codex_models": ["latest-luna", "latest-sol"]}
        calls = []

        def status(*args):
            self.models.append(self.model("gpt-11-sol"))
            self.write_catalog()
            return True, None, "logged in"

        def probe(seat):
            calls.append((seat["model"], seat["effort"]))
            return None, None, None

        with patch.object(self.roster, "codex_catalog", wraps=self.roster.codex_catalog) as catalog, \
                patch.object(self.roster, "probe_seat", side_effect=probe):
            result, _, strict = self.build(cfg, probe=True, status=status)
        self.assertIsNone(strict)
        self.assertEqual(catalog.call_count, 1)
        codex = [seat for seat in result["seats"] if seat["adapter"] == "codex"]
        self.assertEqual([(seat["model"], seat["effort"]) for seat in codex],
                         [("gpt-8-luna", "xhigh"), ("gpt-9.10-sol", "xhigh"),
                          ("gpt-9.10-sol", "xhigh")])
        self.assertCountEqual(calls, [("gpt-8-luna", "xhigh"), ("gpt-9.10-sol", "xhigh")])

    def test_effort_pin_cannot_override_explicit_codex_effort_before_paid_probes(self):
        cfg = {**self.cfg, "pin": {"codex-sol": {"effort": "max"}}}
        with patch.object(self.roster, "probe_seat") as probe:
            result, _, strict = self.build(cfg, probe=True)
        self.assertEqual(strict, "config")
        self.assertIn("xhigh", result["strict_reason"])
        probe.assert_not_called()

    def test_invalid_effort_and_duplicate_resolved_models_are_configuration_errors(self):
        for cfg in ({**self.cfg, "codex_effort": "medium"},
                    {**self.cfg, "codex_models": ["latest-sol", "gpt-9.10-sol"]}):
            with self.subTest(cfg=cfg):
                _, error, strict = self.roster.resolve_codex_config(cfg, self.cache)
                self.assertEqual(strict, "config")
                self.assertTrue(error)

    def test_luna_quota_fallback_retains_selected_identity_and_terra_compatibility(self):
        source = self.roster.make_seat("opus", "agent", "opus", "max")
        for family in ("luna", "terra"):
            with self.subTest(family=family):
                target = self.roster.make_seat("codex-" + family, "codex", "gpt-9-" + family, "xhigh")
                probes = {("codex", target["model"], "xhigh"): (None, None, None)}
                selected = self.roster.fallback_target(source, [target], probes)
                self.assertIs(selected, target)
                fallback = self.roster.fallback_seat(selected, source, {target["seat"]}, {})
                self.assertEqual(fallback["seat"], "codex-" + family + "-fallback-1")
                self.assertEqual(fallback["model"], target["model"])
                self.assertEqual(fallback["effort"], "xhigh")
                self.assertEqual(fallback["substitutes_for"], "opus")

    def test_existing_terra_selection_does_not_switch_to_luna_when_terra_fails(self):
        source = self.roster.make_seat("opus", "agent", "opus", "max")
        terra = self.roster.make_seat("codex-terra", "codex", "gpt-9-terra", "max")
        luna = self.roster.make_seat("codex-luna", "codex", "gpt-9-luna", "xhigh")
        probes = {("codex", terra["model"], "max"): ("probe failed", "other", "unavailable"),
                  ("codex", luna["model"], "xhigh"): (None, None, None)}
        self.assertIsNone(self.roster.fallback_target(source, [terra, luna], probes))

    def test_luna_quota_handoff_keeps_required_seat_count_and_exact_xhigh_identity(self):
        cfg = {**self.cfg, "quota_fallback": True, "extras": False, "min_labs": 2}
        with patch.object(self.roster, "probe_seat", return_value=(None, None, None)):
            result, _, strict = self.build(cfg, probe=True, quota_failed=("opus", "sonnet"))
        self.assertIsNone(strict)
        self.assertEqual([seat["seat"] for seat in result["seats"]],
                         ["codex-sol", "codex-luna", "codex-luna-fallback-1", "codex-luna-fallback-2"])
        substitutes = [seat for seat in result["seats"] if seat.get("substitutes_for")]
        self.assertEqual([seat["substitutes_for"] for seat in substitutes], ["opus", "sonnet"])
        self.assertTrue(all(seat["model"] == "gpt-8-luna" and seat["effort"] == "xhigh"
                            for seat in substitutes))

    def codex_core(self, result):
        return [seat["model"] for seat in result["seats"]
                if seat["adapter"] == "codex" and not seat["extra"]]

    def live_build(self, name, client_version, slugs, mode):
        home = Path(self.temp.name) / name
        home.mkdir()
        payload = {"models": [self.model(slug) for slug in slugs]}
        if client_version is not None:
            payload["client_version"] = client_version
        (home / "models_cache.json").write_text(json.dumps(payload))
        bindir = Path(self.temp.name) / (name + "-bin")
        bindir.mkdir()
        calls = bindir / "calls"
        refreshed = json.dumps({
            "client_version": "0.159.3",
            "models": [self.model("gpt-7.2-sol"), self.model("gpt-7-luna")],
        })
        script = """#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "codex-cli 0.159.3"
  exit 0
fi
if [ "$1" = "debug" ] && [ "$2" = "models" ]; then
  if [ "$REFRESH_MODE" = "fail" ] || [ "$REFRESH_MODE" = "forbidden" ]; then
    printf '%s\\n' "catalog refresh failed" >&2
    exit 1
  fi
  cat > "$CODEX_HOME/models_cache.json" <<'ENDCACHE'
""" + refreshed + """
ENDCACHE
  exit 0
fi
printf '%s\\n' "unexpected codex command: $*" >&2
exit 1
"""
        executable = bindir / "codex"
        executable.write_text(script)
        executable.chmod(0o755)
        environment = {
            "REVIEW_COUNCIL_CODEX_MODELS_CACHE": "",
            "CODEX_HOME": str(home),
            "CALLS": str(calls),
            "REFRESH_MODE": mode,
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
        }
        with patch.dict(os.environ, environment), \
                patch.object(self.roster, "load_config", return_value=(self.cfg, None)), \
                patch.object(self.roster, "status_check",
                             return_value=(True, None, "logged in")):
            result, _, strict = self.roster.build(False)
        text = calls.read_text() if calls.exists() else ""
        return result, strict, text

    def test_stale_cache_is_refreshed_before_latest_resolution(self):
        result, strict, calls = self.live_build(
            "refresh", "0.154.0", ["gpt-5.6-sol", "gpt-5.6-luna"], "rewrite")
        self.assertIsNone(strict)
        self.assertEqual(self.codex_core(result), ["gpt-7.2-sol", "gpt-7-luna"])
        self.assertNotIn("gpt-5.6-sol", self.codex_core(result))
        self.assertIn("--version", calls)
        self.assertIn("debug models", calls)

    def test_failed_refresh_names_both_versions_and_does_not_resolve(self):
        for name, version, label in (("refuse", "0.154.0", "0.154.0"),
                                     ("missing", None, "missing")):
            with self.subTest(name=name):
                result, strict, calls = self.live_build(
                    name, version, ["gpt-5.6-sol", "gpt-5.6-luna"], "fail")
                self.assertEqual(strict, "availability")
                self.assertEqual(result["seats"], [])
                self.assertIn("0.159.3", result["strict_reason"])
                self.assertIn(label, result["strict_reason"])
                self.assertNotIn("gpt-5.6-sol", result["strict_reason"])
                self.assertIn("debug models", calls)

    def test_matching_client_version_resolves_without_refresh(self):
        result, strict, calls = self.live_build(
            "match", "0.159.3", ["gpt-7-sol", "gpt-7-luna"], "forbidden")
        self.assertIsNone(strict)
        self.assertEqual(self.codex_core(result), ["gpt-7-sol", "gpt-7-luna"])
        self.assertIn("--version", calls)
        self.assertNotIn("debug models", calls)

    def test_explicit_cache_pin_is_not_refreshed(self):
        self.cache.write_text(json.dumps({
            "client_version": "0.1.0",
            "models": [self.model("gpt-4-sol"), self.model("gpt-4-luna")],
        }))
        commands = []

        def fake_run(cmd, _timeout, environment=None):
            commands.append(list(cmd))
            if list(cmd)[:2] == ["claude", "auth"]:
                return 0, '{"loggedIn":false}', ""
            raise AssertionError("live codex command %r" % (cmd,))

        with patch.object(self.roster, "run", side_effect=fake_run):
            result, _, strict = self.build()
        self.assertIsNone(strict)
        self.assertEqual(self.codex_core(result), ["gpt-4-sol", "gpt-4-luna"])
        self.assertFalse(any(cmd[:2] == ["codex", "--version"]
                             or cmd[:3] == ["codex", "debug", "models"]
                             for cmd in commands))


if __name__ == "__main__":
    unittest.main()
