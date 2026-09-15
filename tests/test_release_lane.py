"""Stable release authority contract tests."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import time
import stat
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/verify-release-lane.py"
TAG = "review-council--v0.4.3"
DEFAULT_COMMANDS = [
    {"name": "shell", "kind": "shell", "argv": ["plugins/review-council/tests/run-tests.sh"]},
    {"name": "python", "kind": "python", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]},
    {"name": "claude-marketplace", "kind": "validator", "argv": ["claude", "plugin", "validate", "--strict", ".claude-plugin/marketplace.json"]},
    {"name": "claude-plugin", "kind": "validator", "argv": ["claude", "plugin", "validate", "--strict", "plugins/review-council"]},
    {"name": "codex-marketplace", "kind": "validator", "argv": ["python3", "tests/check-codex-marketplace.py"]},
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def load_module():
    spec = importlib.util.spec_from_file_location("verify_release_lane", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseLaneFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "candidate"
        self.root.mkdir()
        self.real_git = shutil.which("git")
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", "/dev/null")
        self.plugin = self.root / "plugins" / "review-council"
        self.write_manifests("0.4.3")
        executable = self.plugin / "scripts" / "stable-tool.py"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/usr/bin/env python3\n")
        executable.chmod(0o755)
        helper = self.plugin / "scripts" / "checker_fixture_helper.py"
        helper.write_text("IDENTITY = 'stable checker helper'\n")
        runner = self.plugin / "tests" / "run-tests.sh"
        runner.parent.mkdir(parents=True)
        runner.write_text("#!/bin/sh\nexit 0\n")
        runner.chmod(0o755)
        checker = self.plugin / "scripts" / "rev-contract-check.py"
        checker.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, hashlib, json, os, pathlib, sys\n"
            "from checker_fixture_helper import IDENTITY\n"
            "assert IDENTITY == 'stable checker helper'\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--root', required=True)\n"
            "parser.add_argument('--session', required=True)\n"
            "parser.add_argument('--base', required=True)\n"
            "parser.add_argument('--roster', required=True)\n"
            "parser.add_argument('--verify-only', action='store_true')\n"
            "args = parser.parse_args()\n"
            "calls = os.environ.get('RELEASE_TEST_CHECKER_CALLS')\n"
            "if calls:\n"
            "    pathlib.Path(calls).write_text(json.dumps(sys.argv[1:]))\n"
            "if os.environ.get('RELEASE_TEST_CHECKER_FAIL'):\n"
            "    print('fixture checker failure', file=sys.stderr)\n"
            "    raise SystemExit(2)\n"
            "session = pathlib.Path(args.session)\n"
            "paths = list(session.glob('contract-pass-*.json'))\n"
            "if len(paths) != 1:\n"
            "    raise SystemExit(2)\n"
            "receipt = json.loads(paths[0].read_text())\n"
            "runner = pathlib.Path(__file__).resolve().parents[1] / 'tests' / 'run-tests.sh'\n"
            "runner_hash = hashlib.sha256(runner.read_bytes()).hexdigest()\n"
            "roster = json.loads(pathlib.Path(args.roster).read_text())\n"
            "core = [{k: row.get(k) for k in ('seat', 'adapter', 'model', 'effort')} "
            "        for row in roster['seats'] if not row.get('extra', False)]\n"
            "executor = receipt.get('identity', {}).get('executor', {})\n"
            "if (receipt.get('key') != paths[0].stem.removeprefix('contract-pass-') "
            "        or receipt.get('identity', {}).get('core_roster') != core "
            "        or executor.get('runner_sha256') != runner_hash):\n"
            "    raise SystemExit(2)\n"
            "print(paths[0])\n"
        )
        checker.chmod(0o755)
        (self.plugin / "stable.txt").write_text("stable bytes\n")
        (self.plugin / "stable-link").symlink_to("stable.txt")
        self.commit("stable")
        self.stable_commit = self.head()
        self.git("tag", "-a", TAG, "-m", "stable")
        self.installed = self.base / "installed" / "review-council" / "0.4.3"
        self.installed.parent.mkdir(parents=True)
        shutil.copytree(self.plugin, self.installed, symlinks=True)
        (self.plugin / "stable-link").unlink()
        self.write_manifests("0.4.4")
        (self.plugin / "candidate.txt").write_text("candidate bytes\n")
        self.commit("candidate")
        self.candidate_commit = self.head()
        self.shim_dir = self.base / "bin"
        self.shim_dir.mkdir()
        shim = self.shim_dir / "git"
        shim.write_text(
            "#!/usr/bin/env python3\n"
            "import os, subprocess, sys\n"
            f"real = {self.real_git!r}\n"
            "if 'verify-tag' in sys.argv:\n"
            "    target = os.environ.get('RELEASE_TEST_MOVE_TAG_TO')\n"
            "    if target:\n"
            "        root = sys.argv[sys.argv.index('-C') + 1]\n"
            "        tag = sys.argv[-1]\n"
            "        subprocess.run([real, '-C', root, 'update-ref', "
            "                        'refs/tags/' + tag, target], check=True)\n"
            "    raise SystemExit(int(os.environ.get('RELEASE_TEST_VERIFY_TAG_EXIT', '0')))\n"
            "os.execv(real, [real, *sys.argv[1:]])\n"
        )
        shim.chmod(0o755)
        previous_path = os.environ.get("PATH")
        os.environ["PATH"] = str(self.shim_dir) + os.pathsep + (previous_path or "")
        self.addCleanup(
            lambda: os.environ.pop("PATH", None)
            if previous_path is None else os.environ.__setitem__("PATH", previous_path)
        )

    def git(self, *args, check=True):
        return subprocess.run(
            [self.real_git or "git", "-C", str(self.root), *args],
            check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()

    def tree(self, commit="HEAD"):
        return self.git("rev-parse", commit + "^{tree}").stdout.strip()

    def commit(self, subject):
        self.git("add", ".")
        self.git("commit", "-qm", subject)

    def write_manifests(self, version):
        for directory in (".claude-plugin", ".codex-plugin"):
            path = self.plugin / directory / "plugin.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(canonical({"name": "review-council", "version": version}))

    def set_candidate_version(self, version):
        self.write_manifests(version)
        self.commit("candidate version " + version)
        self.candidate_commit = self.head()

    def signed_env(self, **extra):
        return dict(
            os.environ,
            PATH=str(self.shim_dir) + os.pathsep + os.environ.get("PATH", ""),
            **extra,
        )

    def run_lane(self, *arguments, env=None, timeout=20):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            text=True, capture_output=True, timeout=timeout,
            env=env or self.signed_env(),
        )

    def requirements(self, **overrides):
        values = {
            "root": self.root,
            "candidate_commit": self.candidate_commit,
            "stable_tag": TAG,
        }
        values.update(overrides)
        return self.run_lane(
            "requirements", "--root", values["root"],
            "--candidate-commit", values["candidate_commit"],
            "--stable-tag", values["stable_tag"],
        )

    def advance_candidate(self, name="repair.txt"):
        (self.plugin / name).write_text("verified repair\n")
        self.commit("candidate repair")
        self.candidate_commit = self.head()

    def make_session(self, name="session", tree=None):
        session = self.base / name
        session.mkdir()
        scope = (
            "REV_BASE=" + shlex.quote(self.stable_commit) + "\n"
            "REV_ROOT=" + shlex.quote(str(self.root.resolve())) + "\n"
            "REV_SCOPE='branch'\n"
        )
        (session / "scope.env").write_text(scope)
        roster = {
            "seats": [{
                "seat": "sol", "adapter": "codex", "model": "gpt-5.6-sol",
                "effort": "max", "extra": False,
            }],
        }
        (session / "roster.json").write_text(canonical(roster))
        (session / "files.txt").write_text("plugins/review-council/candidate.txt\n")
        (session / "untracked.txt").write_text("")
        (session / "state.json").write_text(canonical({"phase": "done", "open": {"P0": 0, "P1": 0}}))
        (session / "findings.md").write_text("# Findings\n\nNo release-blocking findings.\n")
        key = "1" * 64
        core = [{name: row.get(name) for name in ("seat", "adapter", "model", "effort")}
                for row in roster["seats"]]
        stable_plugin = self.installed.resolve()
        stable_runner = stable_plugin / "tests" / "run-tests.sh"
        contract = {
            "schema_version": 2,
            "key": key,
            "identity": {
                "schema_version": 2,
                "executor": {
                    "policy": "checker-owned",
                    "plugin": str(stable_plugin),
                    "runner": str(stable_runner),
                    "runner_sha256": hashlib.sha256(stable_runner.read_bytes()).hexdigest(),
                    "execution": {
                        "shared_deadline_seconds": 300,
                        "output_bytes": 4 * 1024 * 1024,
                        "diagnostic_bytes": 8192,
                        "term_grace_seconds": 2,
                    },
                },
                "core_roster": core,
                "boundaries": {},
                "provider_versions": {},
                "subject_boundaries": {},
                "touched_boundaries": ["scripts/rev-contract-check.py"],
                "tests": ["provider_envelope_replay"],
            },
            "touched_boundaries": ["scripts/rev-contract-check.py"],
            "log_sha256": "3" * 64,
        }
        contract_name = "contract-pass-" + key + ".json"
        (session / contract_name).write_text(canonical(contract))
        result_name = "r1-sol.json"
        (session / result_name).write_text(canonical({"findings": [], "summary": "clean"}))
        artifact_name = "r1-evidence.md"
        (session / artifact_name).write_text("# Evidence\n\nCandidate review context.\n")
        inputs = {}
        for input_name in ("scope.env", "roster.json", "files.txt", "untracked.txt", contract_name):
            inputs[input_name] = hashlib.sha256((session / input_name).read_bytes()).hexdigest()
        reviewed_tree = tree or self.tree(self.candidate_commit)
        manifest_name = "r1-evidence.manifest.json"
        manifest = {
            "schema_version": 5,
            "label": "1",
            "snapshot_tree": reviewed_tree,
            "base_tree": self.tree(self.stable_commit),
            "inputs": inputs,
            "artifacts": {
                artifact_name: {
                    "sha256": hashlib.sha256((session / artifact_name).read_bytes()).hexdigest(),
                    "words": len((session / artifact_name).read_bytes().split()),
                },
            },
        }
        (session / manifest_name).write_text(canonical(manifest))
        coverage_name = "r1-coverage.receipt.json"
        coverage = {
            "schema_version": 1,
            "manifest": manifest_name,
            "manifest_sha256": hashlib.sha256((session / manifest_name).read_bytes()).hexdigest(),
            "snapshot_tree": reviewed_tree,
            "base_tree": self.tree(self.stable_commit),
            "phase": "verification",
            "assignments": {},
            "results": {result_name: hashlib.sha256((session / result_name).read_bytes()).hexdigest()},
            "advisories": {},
            "findings": [],
        }
        (session / coverage_name).write_text(canonical(coverage))
        head = {
            "receipt": coverage_name,
            "sha256": hashlib.sha256((session / coverage_name).read_bytes()).hexdigest(),
        }
        (session / "coverage-head.json").write_text(canonical(head))
        return session

    def record_review(self, session, out=None, counts=None, env=None):
        counts = counts or {"new_p0": 0, "new_p1": 0, "open_p0": 0, "open_p1": 0}
        out = out or self.base / (session.name + "-review.json")
        arguments = [
            "record-review", "--root", self.root,
            "--candidate-commit", self.candidate_commit,
            "--stable-plugin", self.installed,
            "--stable-tag", TAG, "--session", session,
        ]
        for name in ("new_p0", "new_p1", "open_p0", "open_p1"):
            arguments.extend(["--" + name.replace("_", "-"), str(counts[name])])
        arguments.extend(["--out", out])
        checker_calls = self.base / (session.name + "-checker-calls.json")
        call_env = self.signed_env(RELEASE_TEST_CHECKER_CALLS=str(checker_calls))
        if env:
            call_env.update(env)
        return self.run_lane(*arguments, env=call_env), out, checker_calls

    def change_trigger(self, relative, content="changed trigger\n"):
        path = self.plugin / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if path.suffix in {".sh", ".py"}:
            path.chmod(0o755)
        self.commit("change " + relative)
        self.candidate_commit = self.head()
        return path

    def run_canary(self, canary_id, command, out=None, env=None, timeout=20):
        out = out or self.base / (canary_id + ".json")
        result = self.run_lane(
            "run-canary", "--root", self.root, "--stable-tag", TAG,
            "--id", canary_id, "--out", out, "--", *command,
            env=env or self.signed_env(), timeout=timeout,
        )
        return result, out

    def frozen_tree_key(self):
        paths = self.git("ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
        records = []
        for name in sorted(path for path in paths.split("\0") if path):
            path = self.root / name
            raw = path.read_bytes()
            records.append({
                "path": name,
                "type": "file",
                "executable": bool(path.stat().st_mode & 0o111),
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
        raw = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def make_verification_receipt(self, name="verification"):
        directory = self.base / name
        logs = directory / "logs"
        logs.mkdir(parents=True)
        log_identities = {}
        for command in DEFAULT_COMMANDS:
            body = "verified " + command["name"] + "\n"
            if command["name"] == "shell":
                body += "inventory_total=1\ntasks_passed=1 tasks_failed=0\n"
            body += canonical({"review_council_log_complete": True, "exit_code": 0})
            path = logs / (command["name"] + ".log")
            path.write_text(body)
            path.chmod(0o600)
            raw = path.read_bytes()
            log_identities[command["name"]] = {
                "path": str(path.resolve()), "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        identity = {
            "tree": self.frozen_tree_key(),
            "commands": DEFAULT_COMMANDS,
            "child_environment": {},
            "platform": {},
            "tools": {},
        }
        key_raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        receipt = {
            "schema_version": 1,
            "key": hashlib.sha256(key_raw).hexdigest(),
            "identity": identity,
            "logs": log_identities,
        }
        path = directory / "receipt.json"
        path.write_text(canonical(receipt))
        path.chmod(0o600)
        return path

    def refresh_verification_key(self, path):
        receipt = json.loads(path.read_text())
        raw = json.dumps(receipt["identity"], sort_keys=True, separators=(",", ":")).encode()
        receipt["key"] = hashlib.sha256(raw).hexdigest()
        path.write_text(canonical(receipt))

    def refresh_verification_log(self, receipt_path, command_name):
        receipt = json.loads(receipt_path.read_text())
        path = Path(receipt["logs"][command_name]["path"])
        raw = path.read_bytes()
        receipt["logs"][command_name] = {
            "path": str(path), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        }
        receipt_path.write_text(canonical(receipt))

    def make_review_receipt(self, session_name="review", counts=None, out=None):
        session = self.make_session(session_name)
        result, path, _ = self.record_review(session, out=out, counts=counts)
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def certify(self, reviews, verification, canaries=None, out=None,
                candidate_commit=None, stable_plugin=None, env=None):
        out = out or self.base / "release-receipt.json"
        arguments = [
            "certify", "--root", self.root,
            "--candidate-commit", candidate_commit or self.candidate_commit,
            "--stable-plugin", stable_plugin or self.installed,
            "--stable-tag", TAG,
        ]
        for review in reviews:
            arguments.extend(["--review", review])
        arguments.extend(["--verification-receipt", verification])
        for canary_id, path in sorted((canaries or {}).items()):
            arguments.extend(["--canary", canary_id + "=" + str(path)])
        arguments.extend(["--out", out])
        return self.run_lane(*arguments, timeout=30, env=env), out


class ReleaseLaneIdentityTests(ReleaseLaneFixture):
    def test_clean_candidate_prints_canonical_empty_requirements(self):
        result = self.requirements()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "[]\n")

    def test_signed_tag_command_failure_is_rejected(self):
        result = self.run_lane(
            "requirements", "--root", self.root,
            "--candidate-commit", self.candidate_commit,
            "--stable-tag", TAG,
            env=dict(os.environ, PATH=os.path.dirname(self.real_git)),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stable tag signature verification failed", result.stderr)

    def test_tag_move_during_signature_verification_is_rejected(self):
        (self.root / "outside-plugin.txt").write_text("later stable commit\n")
        self.commit("moved stable target")
        moved_commit = self.head()
        self.git("tag", "-a", "moved-tag", "-m", "moved", moved_commit)
        moved_tag_object = self.git("rev-parse", "moved-tag").stdout.strip()
        self.git("reset", "--hard", self.candidate_commit)

        result = self.run_lane(
            "requirements", "--root", self.root,
            "--candidate-commit", self.candidate_commit,
            "--stable-tag", TAG,
            env=self.signed_env(RELEASE_TEST_MOVE_TAG_TO=moved_tag_object),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stable tag changed during verification", result.stderr)

    def test_stable_tree_reads_use_the_verified_commit_not_the_movable_tag(self):
        original_tag_object = self.git("rev-parse", TAG).stdout.strip()
        self.git("reset", "--hard", self.stable_commit)
        (self.plugin / "stable.txt").write_text("alternate bytes\n")
        self.commit("alternate stable")
        self.git("tag", "-a", "alternate-stable", "-m", "alternate")
        alternate_tag_object = self.git("rev-parse", "alternate-stable").stdout.strip()
        self.git("reset", "--hard", self.candidate_commit)
        module = load_module()
        resolve_tag = module.resolve_tag

        def resolve_then_move(root, tag):
            commit = resolve_tag(root, tag)
            self.git("update-ref", "refs/tags/" + TAG, alternate_tag_object)
            return commit

        module.resolve_tag = resolve_then_move
        self.addCleanup(
            self.git, "update-ref", "refs/tags/" + TAG, original_tag_object,
        )

        identity = module.stable_tag_identity(self.root, TAG)
        stable_file = next(row for row in identity["records"] if row["path"] == "stable.txt")

        self.assertEqual(identity["public"]["commit"], self.stable_commit)
        self.assertEqual(stable_file["sha256"], hashlib.sha256(b"stable bytes\n").hexdigest())

    def test_stable_bundle_byte_mutation_is_rejected(self):
        (self.installed / "stable.txt").write_text("mutated\n")

        module = load_module()
        with self.assertRaisesRegex(module.ReleaseError, "installed stable plugin mismatch"):
            module.stable_identity(self.root, TAG, self.installed)

    def test_stable_bundle_executable_mode_mutation_is_rejected(self):
        (self.installed / "scripts" / "stable-tool.py").chmod(0o644)

        module = load_module()
        with self.assertRaisesRegex(module.ReleaseError, "installed stable plugin mismatch"):
            module.stable_identity(self.root, TAG, self.installed)

    def test_stable_tag_version_forgery_is_rejected(self):
        self.git("tag", "-a", "review-council--v0.4.2", "-m", "forged", self.stable_commit)

        module = load_module()
        with self.assertRaisesRegex(module.ReleaseError, "stable manifest version does not match tag"):
            module.stable_identity(self.root, "review-council--v0.4.2", self.installed)

    def test_dirty_candidate_is_rejected(self):
        (self.root / "dirty.txt").write_text("untracked\n")

        result = self.requirements()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate worktree is not clean", result.stderr)

    def test_config_hidden_plugin_mode_mutation_is_rejected(self):
        self.git("config", "core.fileMode", "false")
        tool = self.plugin / "scripts" / "stable-tool.py"
        tool.chmod(0o644)
        self.assertEqual(self.git("status", "--porcelain=v1").stdout, "")

        result = self.requirements()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate worktree is not clean", result.stderr)

    def test_candidate_commit_must_equal_head(self):
        (self.root / "later.txt").write_text("later\n")
        self.commit("later")

        result = self.requirements()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate commit does not equal HEAD", result.stderr)

    def test_candidate_version_must_be_greater_than_stable(self):
        for version in ("0.4.3", "0.4.2"):
            with self.subTest(version=version):
                self.set_candidate_version(version)
                result = self.requirements()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("candidate version must be greater than stable version", result.stderr)

    def test_root_symlink_is_rejected_as_an_unsafe_direct_path(self):
        alias = self.base / "candidate-alias"
        alias.symlink_to(self.root, target_is_directory=True)

        result = self.requirements(root=alias)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("root must be a direct directory path", result.stderr)

    def test_publication_is_exact_idempotent_private_and_collision_safe(self):
        module = load_module()
        receipt = self.base / "receipts" / "decision.json"
        value = {"z": [2, 1], "a": {"ok": True}}

        module.publish_json(receipt, value)
        first = receipt.read_bytes()
        module.publish_json(receipt, value)

        self.assertEqual(first, canonical(value).encode())
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        with self.assertRaisesRegex(module.ReleaseError, "receipt collision"):
            module.publish_json(receipt, {"different": True})
        linked = self.base / "linked.json"
        os.link(receipt, linked)
        with self.assertRaisesRegex(module.ReleaseError, "receipt must be a regular one-link file"):
            module.publish_json(receipt, value)

    def test_publication_refuses_a_symlink_output(self):
        module = load_module()
        target = self.base / "target.json"
        target.write_text("caller-owned\n")
        receipt = self.base / "receipt.json"
        receipt.symlink_to(target)

        with self.assertRaisesRegex(module.ReleaseError, "receipt must be a direct path"):
            module.publish_json(receipt, {"safe": True})
        self.assertEqual(target.read_text(), "caller-owned\n")


class ReleaseLaneReviewTests(ReleaseLaneFixture):
    def test_checker_snapshot_preserves_the_stable_script_import_path(self):
        session = self.make_session()

        result, output, _ = self.record_review(session)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.exists())

    def test_checker_path_replacement_cannot_change_the_executed_bytes(self):
        session = self.make_session()
        output = self.base / "review.json"
        marker = self.base / "replacement-executed"
        checker = self.installed.resolve() / "scripts" / "rev-contract-check.py"
        original_checker = checker.read_bytes()
        replacement = (
            "#!/usr/bin/env python3\n"
            "import pathlib,sys\n"
            f"pathlib.Path({str(marker)!r}).write_text('executed\\n')\n"
            "session = pathlib.Path(sys.argv[sys.argv.index('--session') + 1])\n"
            "print(next(session.glob('contract-pass-*.json')))\n"
        ).encode()
        module = load_module()
        arguments = module.parser().parse_args([
            "record-review", "--root", str(self.root),
            "--candidate-commit", self.candidate_commit,
            "--stable-plugin", str(self.installed), "--stable-tag", TAG,
            "--session", str(session), "--new-p0", "0", "--new-p1", "0",
            "--open-p0", "0", "--open-p1", "0", "--out", str(output),
        ])
        subprocess_run = module.subprocess.run
        raced = False

        def replace_at_launch(command, *args, **kwargs):
            nonlocal raced
            vector = [str(value) for value in command] if isinstance(command, list) else []
            if not raced and vector[:1] == [sys.executable] and str(checker) in vector:
                raced = True
                checker.write_bytes(replacement)
                checker.chmod(0o755)
                try:
                    return subprocess_run(command, *args, **kwargs)
                finally:
                    checker.write_bytes(original_checker)
                    checker.chmod(0o755)
            return subprocess_run(command, *args, **kwargs)

        module.subprocess.run = replace_at_launch
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                module.record_review(arguments)
        finally:
            module.subprocess.run = subprocess_run
            checker.write_bytes(original_checker)
            checker.chmod(0o755)

        self.assertTrue(raced)
        self.assertTrue(output.exists())
        self.assertFalse(marker.exists())

    def test_checker_import_replacement_cannot_change_the_executed_bytes(self):
        session = self.make_session()
        output = self.base / "review.json"
        marker = self.base / "replacement-imported"
        stable_scripts = self.installed.resolve() / "scripts"
        checker = stable_scripts / "rev-contract-check.py"
        helper = stable_scripts / "checker_fixture_helper.py"
        backup = stable_scripts / ".checker_fixture_helper.original"
        replacement = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed\\n')\n"
            "IDENTITY = 'stable checker helper'\n"
        ).encode()
        module = load_module()
        arguments = module.parser().parse_args([
            "record-review", "--root", str(self.root),
            "--candidate-commit", self.candidate_commit,
            "--stable-plugin", str(self.installed), "--stable-tag", TAG,
            "--session", str(session), "--new-p0", "0", "--new-p1", "0",
            "--open-p0", "0", "--open-p1", "0", "--out", str(output),
        ])
        subprocess_run = module.subprocess.run
        raced = False

        def replace_at_launch(command, *args, **kwargs):
            nonlocal raced
            vector = [str(value) for value in command] if isinstance(command, list) else []
            if not raced and vector[:1] == [sys.executable] and str(checker) in vector:
                raced = True
                os.replace(helper, backup)
                helper.write_bytes(replacement)
                helper.chmod(0o644)
                try:
                    return subprocess_run(command, *args, **kwargs)
                finally:
                    helper.unlink()
                    os.replace(backup, helper)
            return subprocess_run(command, *args, **kwargs)

        module.subprocess.run = replace_at_launch
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                module.record_review(arguments)
        finally:
            module.subprocess.run = subprocess_run
            if backup.exists():
                if helper.exists():
                    helper.unlink()
                os.replace(backup, helper)

        self.assertTrue(raced)
        self.assertTrue(output.exists())
        self.assertFalse(marker.exists())

    def test_contract_runner_identity_must_match_the_verified_stable_snapshot(self):
        session = self.make_session()
        output = self.base / "review.json"
        stable_plugin = self.installed.resolve()
        checker = stable_plugin / "scripts" / "rev-contract-check.py"
        runner = stable_plugin / "tests" / "run-tests.sh"
        backup = stable_plugin / "tests" / ".run-tests.original"
        replacement = b"#!/bin/sh\nexit 23\n"
        contract_path = next(session.glob("contract-pass-*.json"))
        contract = json.loads(contract_path.read_text())
        contract["identity"]["executor"]["runner_sha256"] = hashlib.sha256(
            replacement,
        ).hexdigest()
        contract_path.write_text(canonical(contract))
        manifest_path = session / "r1-evidence.manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["inputs"][contract_path.name] = hashlib.sha256(
            contract_path.read_bytes(),
        ).hexdigest()
        manifest_path.write_text(canonical(manifest))
        coverage_path = session / "r1-coverage.receipt.json"
        coverage = json.loads(coverage_path.read_text())
        coverage["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        coverage_path.write_text(canonical(coverage))
        head_path = session / "coverage-head.json"
        head = json.loads(head_path.read_text())
        head["sha256"] = hashlib.sha256(coverage_path.read_bytes()).hexdigest()
        head_path.write_text(canonical(head))
        module = load_module()
        arguments = module.parser().parse_args([
            "record-review", "--root", str(self.root),
            "--candidate-commit", self.candidate_commit,
            "--stable-plugin", str(self.installed), "--stable-tag", TAG,
            "--session", str(session), "--new-p0", "0", "--new-p1", "0",
            "--open-p0", "0", "--open-p1", "0", "--out", str(output),
        ])
        subprocess_run = module.subprocess.run
        raced = False
        checker_accepted = False

        def replace_at_launch(command, *args, **kwargs):
            nonlocal raced, checker_accepted
            vector = [str(value) for value in command] if isinstance(command, list) else []
            if not raced and vector[:1] == [sys.executable] and str(checker) in vector:
                raced = True
                os.replace(runner, backup)
                runner.write_bytes(replacement)
                runner.chmod(0o755)
                try:
                    result = subprocess_run(command, *args, **kwargs)
                    checker_accepted = result.returncode == 0
                    return result
                finally:
                    runner.unlink()
                    os.replace(backup, runner)
            return subprocess_run(command, *args, **kwargs)

        module.subprocess.run = replace_at_launch
        try:
            with self.assertRaisesRegex(
                    module.ReleaseError, "contract executor is not the verified stable plugin"):
                with contextlib.redirect_stdout(io.StringIO()):
                    module.record_review(arguments)
        finally:
            module.subprocess.run = subprocess_run
            if backup.exists():
                if runner.exists():
                    runner.unlink()
                os.replace(backup, runner)

        self.assertTrue(raced)
        self.assertTrue(checker_accepted)
        self.assertFalse(output.exists())

    def test_clean_first_review_records_canonical_decision_and_exact_checker_call(self):
        session = self.make_session()

        result, receipt_path, calls_path = self.record_review(session)

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(set(receipt), {"schema_version", "stable", "candidate", "review", "status"})
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["candidate"], {
            "version": "0.4.4", "commit": self.candidate_commit,
            "tree": self.tree(self.candidate_commit),
        })
        self.assertEqual(receipt["review"] | {"session_identity": "ignored"}, {
            "session_identity": "ignored", "new_p0": 0, "new_p1": 0,
            "open_p0": 0, "open_p1": 0,
        })
        self.assertRegex(receipt["review"]["session_identity"], r"^[0-9a-f]{64}$")
        self.assertEqual(receipt["status"], "clean")
        self.assertEqual(receipt_path.read_text(), canonical(receipt))
        self.assertEqual(json.loads(calls_path.read_text()), [
            "--root", str(self.root.resolve()), "--session", str(session.resolve()),
            "--base", self.stable_commit, "--roster", str((session / "roster.json").resolve()),
            "--verify-only",
        ])

    def test_new_finding_records_correction_required(self):
        session = self.make_session()

        result, path, _ = self.record_review(
            session, counts={"new_p0": 0, "new_p1": 1, "open_p0": 0, "open_p1": 0},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(path.read_text())["status"], "correction-required")

    def test_clean_delta_on_a_new_commit_records_the_new_tree(self):
        first_session = self.make_session("first")
        first, first_path, _ = self.record_review(
            first_session,
            counts={"new_p0": 0, "new_p1": 1, "open_p0": 0, "open_p1": 0},
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        first_commit = self.candidate_commit
        self.advance_candidate()
        second_session = self.make_session("delta")

        second, second_path, _ = self.record_review(second_session)

        self.assertEqual(second.returncode, 0, second.stderr)
        first_receipt = json.loads(first_path.read_text())
        second_receipt = json.loads(second_path.read_text())
        self.assertNotEqual(first_commit, second_receipt["candidate"]["commit"])
        self.assertEqual(first_receipt["status"], "correction-required")
        self.assertEqual(second_receipt["status"], "clean")

    def test_open_p0_or_p1_records_correction_required(self):
        for field in ("open_p0", "open_p1"):
            with self.subTest(field=field):
                session = self.make_session("session-" + field)
                counts = {"new_p0": 0, "new_p1": 0, "open_p0": 0, "open_p1": 0}
                counts[field] = 1
                result, path, _ = self.record_review(session, counts=counts)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(path.read_text())["status"], "correction-required")

    def test_session_stop_records_infrastructure_blocked_without_product_counts(self):
        session = self.make_session()
        attempts = session / "attempts"
        attempts.mkdir()
        (attempts / "session.stopped.json").write_text(canonical({
            "panel": "1", "reason": "provider evidence failed", "stopped": True,
        }))

        result, path, _ = self.record_review(session)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(path.read_text())["status"], "infrastructure-blocked")
        counts = {"new_p0": 0, "new_p1": 1, "open_p0": 0, "open_p1": 0}
        refused, _, _ = self.record_review(session, out=self.base / "refused.json", counts=counts)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("stopped session accepts no product counts", refused.stderr)

    def test_stable_contract_checker_failure_blocks_review_receipt(self):
        session = self.make_session()

        result, path, _ = self.record_review(
            session, env={"RELEASE_TEST_CHECKER_FAIL": "1"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stable contract checker failed", result.stderr)
        self.assertFalse(path.exists())

    def test_contract_receipt_must_name_the_verified_stable_executor(self):
        session = self.make_session()
        contract_path = next(session.glob("contract-pass-*.json"))
        contract = json.loads(contract_path.read_text())
        contract["identity"]["executor"]["plugin"] = str(self.base / "candidate-engine")
        contract_path.write_text(canonical(contract))

        result, path, _ = self.record_review(session)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contract executor is not the verified stable plugin", result.stderr)
        self.assertFalse(path.exists())

    def test_roster_mutation_is_rejected_by_the_stable_checker(self):
        session = self.make_session()
        roster = json.loads((session / "roster.json").read_text())
        roster["seats"][0]["model"] = "mutated-model"
        (session / "roster.json").write_text(canonical(roster))

        result, path, _ = self.record_review(session)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stable contract checker failed", result.stderr)
        self.assertFalse(path.exists())

    def test_contract_mutation_is_rejected_by_the_stable_checker(self):
        session = self.make_session()
        contract_path = next(session.glob("contract-pass-*.json"))
        contract = json.loads(contract_path.read_text())
        contract["key"] = "9" * 64
        contract_path.write_text(canonical(contract))

        result, path, _ = self.record_review(session)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stable contract checker failed", result.stderr)
        self.assertFalse(path.exists())

    def test_missing_coverage_head_blocks_review_receipt(self):
        session = self.make_session()
        (session / "coverage-head.json").unlink()

        result, path, _ = self.record_review(session)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("coverage head", result.stderr)
        self.assertFalse(path.exists())

    def test_coverage_receipt_hash_mutation_blocks_review_receipt(self):
        session = self.make_session()
        coverage = session / "r1-coverage.receipt.json"
        coverage.write_bytes(coverage.read_bytes() + b"\n")

        result, path, _ = self.record_review(session)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("coverage receipt hash mismatch", result.stderr)
        self.assertFalse(path.exists())

    def test_manifest_artifact_hash_mutation_blocks_review_receipt(self):
        session = self.make_session()
        artifact = session / "r1-evidence.md"
        artifact.write_bytes(artifact.read_bytes() + b"mutated\n")

        result, path, _ = self.record_review(session)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("coverage artifact hash mismatch", result.stderr)
        self.assertFalse(path.exists())

    def test_reviewed_tree_must_equal_the_candidate_tree(self):
        session = self.make_session(tree=self.tree(self.stable_commit))

        result, path, _ = self.record_review(session)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reviewed tree does not equal candidate tree", result.stderr)
        self.assertFalse(path.exists())

    def test_session_identity_binds_state_and_findings_bytes(self):
        first_session = self.make_session("first")
        second_session = self.make_session("second")
        (second_session / "findings.md").write_text("# Findings\n\nDeferred detail changed.\n")

        first, first_path, _ = self.record_review(first_session)
        second, second_path, _ = self.record_review(second_session)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotEqual(
            json.loads(first_path.read_text())["review"]["session_identity"],
            json.loads(second_path.read_text())["review"]["session_identity"],
        )


class ReleaseLaneCanaryTests(ReleaseLaneFixture):
    def test_each_direct_trigger_selects_its_exact_canary_set(self):
        cases = {
            "scripts/seats.d/codex.sh": ["provider-codex"],
            "scripts/seats.d/claude.sh": ["provider-claude"],
            "scripts/seats.d/gemini.sh": ["provider-gemini"],
            "scripts/lib/review-read-audit.py": ["provider-claude", "provider-codex"],
            "scripts/lib/stream-summary.py": ["provider-claude", "provider-codex"],
            "scripts/lib/codex-review-to-findings.py": ["provider-codex"],
            "scripts/rev-pr-review.py": ["github-publication"],
            "scripts/stack.sh": ["github-publication"],
            "docs/pr-review.md": ["github-publication"],
        }
        original = self.candidate_commit
        for relative, expected in cases.items():
            with self.subTest(relative=relative):
                self.git("reset", "--hard", original)
                self.git("clean", "-fd")
                self.candidate_commit = original
                self.change_trigger(relative)
                result = self.requirements()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)

    def test_each_prefix_trigger_selects_its_host_canary(self):
        cases = {
            "skills/rev/new.md": ["host-claude"],
            "skills/stack/new.md": ["host-claude"],
            "codex-skills/rev/new.md": ["host-codex"],
            "codex-skills/stack/new.md": ["host-codex"],
            "hooks/new-hook": ["host-claude"],
        }
        original = self.candidate_commit
        for relative, expected in cases.items():
            with self.subTest(relative=relative):
                self.git("reset", "--hard", original)
                self.git("clean", "-fd")
                self.candidate_commit = original
                self.change_trigger(relative)
                result = self.requirements()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)

    def test_unmatched_change_requires_no_live_canary(self):
        result = self.requirements()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "[]\n")

    def test_unknown_provider_adapter_trigger_fails_closed(self):
        self.change_trigger("scripts/seats.d/new-provider.sh")

        result = self.requirements()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unmapped provider boundary", result.stderr)

    def test_run_canary_executes_the_exact_vector_and_binds_emitted_evidence(self):
        self.change_trigger("scripts/seats.d/codex.sh")
        evidence = self.base / "evidence.json"
        code = (
            "import json,pathlib,sys; "
            "pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:])); "
            "print(json.dumps({'evidence_paths':[sys.argv[1]]},sort_keys=True,separators=(',',':')))"
        )
        command = [sys.executable, "-c", code, str(evidence), "a b", "$literal"]

        result, receipt_path = self.run_canary("provider-codex", command)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(evidence.read_text()), ["a b", "$literal"])
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["command"], command)
        self.assertEqual(receipt["canary"]["id"], "provider-codex")
        self.assertEqual([row["path"] for row in receipt["canary"]["triggers"]],
                         ["scripts/seats.d/codex.sh"])
        self.assertEqual(receipt["evidence"][0]["path"], str(evidence.resolve()))
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(receipt["log"]["path"]).stat().st_mode), 0o600)

    def test_nonzero_canary_exit_writes_no_receipt(self):
        self.change_trigger("scripts/seats.d/codex.sh")

        result, receipt_path = self.run_canary(
            "provider-codex", [sys.executable, "-c", "raise SystemExit(7)"],
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canary command failed with exit 7", result.stderr)
        self.assertFalse(receipt_path.exists())

    def test_canary_output_limit_terminates_the_group_and_writes_no_receipt(self):
        self.change_trigger("scripts/seats.d/codex.sh")
        code = "import os; os.write(1, b'x' * (5 * 1024 * 1024))"

        result, receipt_path = self.run_canary(
            "provider-codex", [sys.executable, "-c", code], timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canary output limit exceeded", result.stderr)
        self.assertFalse(receipt_path.exists())

    def test_canary_timeout_still_applies_after_the_command_closes_its_output(self):
        module = load_module()
        module.CANARY_TIMEOUT_SECONDS = 0.1
        module.CANARY_TERM_GRACE_SECONDS = 0.1
        command = [
            sys.executable, "-c",
            "import os,time; os.close(1); os.close(2); time.sleep(2)",
        ]

        started = time.monotonic()
        output, exit_code, failure = module.capture_canary(command, self.root)

        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(output, b"")
        self.assertEqual(exit_code, 124)
        self.assertEqual(failure, "canary command timed out")

    def test_signal_termination_kills_the_canary_process_group(self):
        self.change_trigger("scripts/seats.d/codex.sh")
        child_pid_path = self.base / "child.pid"
        receipt = self.base / "signal.json"
        code = (
            "import os,pathlib,time; "
            f"pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid())); "
            "time.sleep(60)"
        )
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "run-canary", "--root", str(self.root),
             "--stable-tag", TAG, "--id", "provider-codex", "--out", str(receipt),
             "--", sys.executable, "-c", code],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.signed_env(),
        )
        deadline = time.monotonic() + 10
        while not child_pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(child_pid_path.exists(), "canary child did not start")
        child_pid = int(child_pid_path.read_text())

        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=10)

        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(receipt.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_stale_trigger_identity_is_rejected(self):
        path = self.change_trigger("scripts/seats.d/codex.sh")
        result, receipt = self.run_canary(
            "provider-codex", [sys.executable, "-c", "print('ok')"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        path.write_text("new trigger bytes\n")
        self.commit("change trigger again")
        self.candidate_commit = self.head()

        module = load_module()
        with self.assertRaisesRegex(module.ReleaseError, "stale canary trigger identity"):
            module.validate_canaries(self.root, TAG, {"provider-codex": receipt})

    def test_malformed_required_canary_receipt_is_rejected(self):
        self.change_trigger("scripts/seats.d/codex.sh")
        receipt = self.base / "malformed.json"
        receipt.write_text("{")
        receipt.chmod(0o600)

        module = load_module()
        with self.assertRaisesRegex(module.ReleaseError, "canary receipt is not valid JSON"):
            module.validate_canaries(self.root, TAG, {"provider-codex": receipt})

    def test_receipt_collision_refuses_before_launch(self):
        self.change_trigger("scripts/seats.d/codex.sh")
        receipt = self.base / "collision.json"
        receipt.write_text("caller-owned\n")
        marker = self.base / "launched"

        result, _ = self.run_canary(
            "provider-codex",
            [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
            out=receipt,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("receipt collision", result.stderr)
        self.assertEqual(receipt.read_text(), "caller-owned\n")
        self.assertFalse(marker.exists())

    def test_missing_required_canary_receipt_is_rejected(self):
        self.change_trigger("scripts/seats.d/codex.sh")

        module = load_module()
        with self.assertRaisesRegex(module.ReleaseError, "missing required canary"):
            module.validate_canaries(self.root, TAG, {})

    def test_unknown_extra_canary_is_rejected(self):
        self.change_trigger("scripts/seats.d/codex.sh")
        result, receipt = self.run_canary(
            "provider-codex", [sys.executable, "-c", "print('ok')"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        module = load_module()
        with self.assertRaisesRegex(module.ReleaseError, "unknown extra canary"):
            module.validate_canaries(
                self.root, TAG,
                {"provider-codex": receipt, "invented-canary": receipt},
            )


class ReleaseLaneCertificationTests(ReleaseLaneFixture):
    def test_caller_global_git_excludes_cannot_hide_candidate_dirtiness(self):
        ignored = self.root / "globally-ignored.txt"
        ignored.write_text("must still be verified\n")
        ignore_patterns = self.base / "global-ignore"
        ignore_patterns.write_text("globally-ignored.txt\n")
        global_config = self.base / "global.gitconfig"
        self.git("config", "--file", global_config, "core.excludesFile", ignore_patterns)
        environment = self.signed_env(
            GIT_CONFIG_GLOBAL=str(global_config), GIT_CONFIG_NOSYSTEM="1",
        )

        result = self.run_lane(
            "requirements", "--root", self.root,
            "--candidate-commit", self.candidate_commit, "--stable-tag", TAG,
            env=environment,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate worktree is not clean", result.stderr)

    def test_verifier_tree_mismatch_is_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        receipt = json.loads(verification.read_text())
        receipt["identity"]["tree"] = "0" * 64
        verification.write_text(canonical(receipt))
        self.refresh_verification_key(verification)

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verifier tree does not equal final candidate", result.stderr)
        self.assertFalse(out.exists())

    def test_verifier_key_mismatch_is_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        receipt = json.loads(verification.read_text())
        receipt["key"] = "0" * 64
        verification.write_text(canonical(receipt))

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verifier key mismatch", result.stderr)
        self.assertFalse(out.exists())

    def test_verifier_must_contain_the_exact_default_command_set(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        receipt = json.loads(verification.read_text())
        removed = receipt["identity"]["commands"].pop()
        receipt["logs"].pop(removed["name"])
        verification.write_text(canonical(receipt))
        self.refresh_verification_key(verification)

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verifier command set mismatch", result.stderr)
        self.assertFalse(out.exists())

    def test_failed_or_truncated_verifier_log_is_rejected(self):
        for kind in ("failed", "truncated"):
            with self.subTest(kind=kind):
                review = self.make_review_receipt("review-" + kind)
                verification = self.make_verification_receipt("verification-" + kind)
                receipt = json.loads(verification.read_text())
                log = Path(receipt["logs"]["python"]["path"])
                if kind == "failed":
                    log.write_text(canonical({"review_council_log_complete": True, "exit_code": 1}))
                else:
                    log.write_text("truncated output\n")
                log.chmod(0o600)
                self.refresh_verification_log(verification, "python")

                result, out = self.certify(
                    [review], verification, out=self.base / ("release-" + kind + ".json"),
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("verifier log is failed or truncated", result.stderr)
                self.assertFalse(out.exists())

    def test_verifier_log_hash_mismatch_is_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        receipt = json.loads(verification.read_text())
        Path(receipt["logs"]["python"]["path"]).write_text("mutated\n")

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verifier log hash mismatch", result.stderr)
        self.assertFalse(out.exists())

    def test_nonregular_verifier_log_is_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        receipt = json.loads(verification.read_text())
        log = Path(receipt["logs"]["python"]["path"])
        other = self.base / "linked-verifier-log"
        os.link(log, other)

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verifier log must be a regular one-link file", result.stderr)
        self.assertFalse(out.exists())

    def test_dirty_final_candidate_is_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        (self.root / "dirty-final.txt").write_text("dirty\n")

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate worktree is not clean", result.stderr)
        self.assertFalse(out.exists())

    def test_moved_final_candidate_is_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        old_commit = self.candidate_commit
        self.advance_candidate()

        result, out = self.certify([review], verification, candidate_commit=old_commit)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate commit does not equal HEAD", result.stderr)
        self.assertFalse(out.exists())

    def test_stale_stable_bundle_is_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        (self.installed / "stable.txt").write_text("stale installed bytes\n")

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed stable plugin mismatch", result.stderr)
        self.assertFalse(out.exists())

    def test_zero_or_three_review_receipts_are_rejected(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()
        for count, reviews in ((0, []), (3, [review, review, review])):
            with self.subTest(count=count):
                result, out = self.certify(
                    reviews, verification, out=self.base / ("release-" + str(count) + ".json"),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("certification requires one or two review receipts", result.stderr)
                self.assertFalse(out.exists())

    def test_clean_initial_review_rejects_an_unnecessary_second_review(self):
        first = self.make_review_receipt("first")
        second = self.make_review_receipt("second")
        verification = self.make_verification_receipt()

        result, out = self.certify([first, second], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clean initial review forbids a second review", result.stderr)
        self.assertFalse(out.exists())

    def test_delta_review_must_use_a_different_candidate_commit(self):
        counts = {"new_p0": 0, "new_p1": 1, "open_p0": 0, "open_p1": 0}
        first = self.make_review_receipt("first", counts=counts)
        second = self.make_review_receipt("second")
        verification = self.make_verification_receipt()

        result, out = self.certify([first, second], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("delta review must use a different candidate commit", result.stderr)
        self.assertFalse(out.exists())

    def test_unclean_latest_review_blocks_certification(self):
        counts = {"new_p0": 1, "new_p1": 0, "open_p0": 0, "open_p1": 0}
        review = self.make_review_receipt(counts=counts)
        verification = self.make_verification_receipt()

        result, out = self.certify([review], verification)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("latest review is not clean", result.stderr)
        self.assertFalse(out.exists())

    def test_one_clean_review_certifies_with_full_evidence_hashes(self):
        review = self.make_review_receipt()
        verification = self.make_verification_receipt()

        result, out = self.certify([review], verification)

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(out.read_text())
        self.assertEqual(receipt["status"], "certified")
        self.assertEqual(receipt["candidate"]["commit"], self.candidate_commit)
        self.assertEqual(receipt["reviews"], [hashlib.sha256(review.read_bytes()).hexdigest()])
        self.assertEqual(receipt["verification"], {
            "key": json.loads(verification.read_text())["key"],
            "sha256": hashlib.sha256(verification.read_bytes()).hexdigest(),
        })
        self.assertEqual(receipt["canaries"], {})
        self.assertEqual(out.read_text(), canonical(receipt))

    def test_correction_then_clean_delta_on_new_commit_certifies(self):
        counts = {"new_p0": 0, "new_p1": 1, "open_p0": 0, "open_p1": 0}
        first = self.make_review_receipt("first", counts=counts)
        self.advance_candidate()
        second = self.make_review_receipt("second")
        verification = self.make_verification_receipt()

        result, out = self.certify([first, second], verification)

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(out.read_text())
        self.assertEqual(receipt["status"], "certified")
        self.assertEqual(receipt["reviews"], [
            hashlib.sha256(first.read_bytes()).hexdigest(),
            hashlib.sha256(second.read_bytes()).hexdigest(),
        ])


class ReleaseDocumentationTests(unittest.TestCase):
    def test_readme_links_to_the_release_operator_document(self):
        readme = (REPO / "README.md").read_text()

        self.assertIn("[release procedure](docs/release.md)", readme)

    def test_release_operator_document_names_the_bounded_lane(self):
        document = (REPO / "docs" / "release.md").read_text()

        for phrase in (
            "N-1 review",
            "P0/P1-only repairs",
            "two-generation cap",
            "candidate non-self-review",
            "deterministic gate",
            "targeted canaries",
            "squash merge",
            "signed tag",
            "git verify-tag review-council--v0.4.3",
            "fresh-session discovery",
            "python3 scripts/verify-release-lane.py requirements --root .",
            "python3 scripts/verify-review-council.py --root .",
            "python3 scripts/verify-release-lane.py certify --root .",
            "record-review",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, document)


if __name__ == "__main__":
    unittest.main()
