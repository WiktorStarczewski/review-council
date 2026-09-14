"""Unified local verification contract."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/verify-review-council.py"


def load_module():
    spec = importlib.util.spec_from_file_location("verify_review_council", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class VerifyReviewCouncilTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "commit.gpgsign", "false"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "core.hooksPath", "/dev/null"], check=True)
        (self.repo / "marker.txt").write_text("captured\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.cache = self.base / "cache"
        self.commands = self.base / "commands.json"

    def write_commands(self, shell_code, python_code="pass", validators=None):
        commands = [
            {"name": "shell", "kind": "shell", "argv": [sys.executable, "-c", shell_code]},
            {"name": "python", "kind": "python", "argv": [sys.executable, "-c", python_code]},
        ]
        for index, code in enumerate(validators or ["pass"]):
            commands.append({
                "name": f"validator-{index}",
                "kind": "validator",
                "argv": [sys.executable, "-c", code],
            })
        self.commands.write_text(json.dumps({"commands": commands}))

    @staticmethod
    def passing_shell(extra=""):
        return extra + "\nprint('inventory_total=1')\nprint('tasks_passed=1 tasks_failed=0')\n"

    def run_verify(self, env=None, timeout=20, extra_args=None):
        command = [
            sys.executable, str(SCRIPT), "--root", str(self.repo),
            "--cache-dir", str(self.cache), "--commands", str(self.commands),
            "--timeout", "8",
        ]
        command.extend(extra_args or [])
        return subprocess.run(
            command, text=True, capture_output=True, timeout=timeout,
            env=dict(os.environ, **(env or {})),
        )

    def receipt(self):
        return self.owned_state() / "receipt.json"

    def owned_state(self, cache=None):
        root_key = hashlib.sha256(str(self.repo.resolve()).encode()).hexdigest()[:24]
        return (cache or self.cache) / "review-council" / "verification" / root_key

    def test_explicit_cache_root_preserves_caller_files_and_mode(self):
        cache = self.base / "caller-cache"
        victim = cache / "trees" / "victim" / "keep"
        victim.parent.mkdir(parents=True)
        victim.write_text("owned by caller\n")
        cache.chmod(0o755)
        self.write_commands(self.passing_shell())

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.repo),
             "--cache-dir", str(cache), "--commands", str(self.commands), "--timeout", "8"],
            text=True, capture_output=True, timeout=20,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(cache.stat().st_mode & 0o777, 0o755)
        self.assertEqual(victim.read_text(), "owned by caller\n")
        self.assertTrue((self.owned_state(cache) / "receipt.json").is_file())

    def test_source_cache_aliases_fail_before_state_creation_or_launch(self):
        sentinel = self.base / "command-launched"
        self.write_commands(
            self.passing_shell(f"from pathlib import Path; Path({str(sentinel)!r}).touch()")
        )
        marker = self.repo / "marker.txt"
        marker.chmod(0o640)
        original = (marker.read_bytes(), marker.stat().st_mode & 0o777)
        aliases = {
            "source": self.repo,
            "descendant": self.repo / "state-cache",
            "lexical": self.repo / "nested" / "..",
        }

        external = self.base / "external"
        external.mkdir()
        inward = external / "inward"
        inward.symlink_to(self.repo, target_is_directory=True)
        aliases["symlink-into-source"] = inward
        outward = self.repo / "outward"
        outward.symlink_to(external, target_is_directory=True)
        aliases["symlink-out-of-source"] = outward

        alternate_case = self.repo.with_name(self.repo.name.swapcase())
        if alternate_case.exists():
            aliases["case-fold-alias"] = alternate_case

        for name, cache in aliases.items():
            with self.subTest(alias=name):
                result = self.run_verify(extra_args=["--cache-dir", str(cache)])
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("overlaps the source tree", result.stderr)
                self.assertEqual((marker.read_bytes(), marker.stat().st_mode & 0o777), original)
                self.assertFalse(sentinel.exists())
        self.assertFalse((self.repo / "review-council").exists())
        self.assertFalse((self.repo / "state-cache").exists())
        self.assertFalse((external / "review-council").exists())

    def test_opened_external_ancestor_survives_swap_into_source(self):
        verifier = load_module()
        external = self.base / "external-state"
        external.mkdir(mode=0o750)
        external.chmod(0o750)
        keep = external / "keep"
        keep.write_text("caller bytes\n")
        keep.chmod(0o640)
        detached = self.base / "detached-state"
        sentinel = self.base / "command-launched"
        self.write_commands(
            self.passing_shell(f"from pathlib import Path; Path({str(sentinel)!r}).touch()")
        )
        real_mkdir = os.mkdir
        swapped = False

        def swap_before_cache_creation(path, mode=0o777, *, dir_fd=None):
            nonlocal swapped
            path_text = os.fspath(path)
            path_call = dir_fd is None and external / "cache" in Path(path_text).parents
            descriptor_call = dir_fd is not None and path_text == "cache"
            if not swapped and (path_call or descriptor_call):
                external.rename(detached)
                external.symlink_to(self.repo, target_is_directory=True)
                swapped = True
            return real_mkdir(path, mode, dir_fd=dir_fd)

        args = verifier.parser().parse_args([
            "--root", str(self.repo), "--cache-dir", str(external / "cache"),
            "--commands", str(self.commands), "--timeout", "8",
        ])
        with patch.object(verifier.os, "mkdir", side_effect=swap_before_cache_creation):
            verifier.verify(args)

        self.assertTrue(swapped)
        preserved = detached / "keep"
        self.assertEqual(preserved.read_bytes(), b"caller bytes\n")
        self.assertEqual(preserved.stat().st_mode & 0o777, 0o640)
        self.assertEqual(detached.stat().st_mode & 0o777, 0o750)
        self.assertFalse((self.repo / "cache").exists())
        self.assertTrue(sentinel.exists())
        receipt = self.owned_state(detached / "cache") / "receipt.json"
        self.assertTrue(receipt.is_file())

    def test_descriptor_bound_external_cache_reuses_receipt(self):
        calls = self.base / "external-cache-calls"
        self.write_commands(self.passing_shell(
            f"from pathlib import Path\np=Path({str(calls)!r}); "
            "p.write_text(p.read_text() + 'x' if p.exists() else 'x')"
        ))

        first = self.run_verify()
        second = self.run_verify()

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("reused verification receipt", second.stdout)
        self.assertEqual(calls.read_text(), "x")

    def test_cancelled_lock_waiter_preserves_owner_receipt(self):
        cache = self.base / "shared-cache"
        state = self.owned_state(cache)
        cache.mkdir()
        state.mkdir(parents=True)
        locks = []
        for directory in (cache, state):
            handle = (directory / "lock").open("a+b")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locks.append(handle)
        self.addCleanup(lambda: [handle.close() for handle in locks])
        self.write_commands(self.passing_shell())
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--root", str(self.repo),
             "--cache-dir", str(cache), "--commands", str(self.commands), "--timeout", "8"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(0.3)
        sentinels = [cache / "receipt.json", state / "receipt.json"]
        for receipt in sentinels:
            receipt.write_text("owner receipt\n")

        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)

        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        for receipt in sentinels:
            self.assertEqual(receipt.read_text(), "owner receipt\n")

    def test_lock_open_failure_preserves_existing_receipt(self):
        state = self.owned_state()
        state.mkdir(parents=True)
        receipt = state / "receipt.json"
        receipt.write_text("owner receipt\n")
        (state / "lock").mkdir()
        self.write_commands(self.passing_shell())

        result = self.run_verify()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(receipt.read_text(), "owner receipt\n")

    def test_primary_gates_overlap_and_unchanged_identity_reuses(self):
        ready_shell = self.base / "shell.ready"
        ready_python = self.base / "python.ready"
        calls_shell = self.base / "shell.calls"
        calls_python = self.base / "python.calls"
        barrier = """
from pathlib import Path
import sys, time
own, peer, calls = map(Path, sys.argv[1:4])
calls.write_text(calls.read_text() + 'x' if calls.exists() else 'x')
own.write_text('ready')
deadline = time.monotonic() + 4
while not peer.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not peer.exists():
    raise SystemExit(9)
"""
        shell_code = barrier + "\nprint('inventory_total=1')\nprint('tasks_passed=1 tasks_failed=0')\n"
        shell_argv = [str(ready_shell), str(ready_python), str(calls_shell)]
        python_argv = [str(ready_python), str(ready_shell), str(calls_python)]
        self.write_commands("pass")
        data = json.loads(self.commands.read_text())
        data["commands"][0]["argv"] = [sys.executable, "-c", shell_code, *shell_argv]
        data["commands"][1]["argv"] = [sys.executable, "-c", barrier, *python_argv]
        self.commands.write_text(json.dumps(data))

        first = self.run_verify()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(calls_shell.read_text(), "x")
        self.assertEqual(calls_python.read_text(), "x")
        receipt = json.loads(self.receipt().read_text())
        self.assertEqual(set(receipt["logs"]), {"shell", "python", "validator-0"})

        second = self.run_verify()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("reused verification receipt", second.stdout)
        self.assertEqual(calls_shell.read_text(), "x")
        self.assertEqual(calls_python.read_text(), "x")

    def test_selector_inheritance_fails_before_launch_without_receipt(self):
        sentinel = self.base / "launched"
        self.write_commands(self.passing_shell(f"from pathlib import Path; Path({str(sentinel)!r}).touch()"))
        for name in (
            "REVIEW_COUNCIL_TEST_TASK",
            "REVIEW_COUNCIL_TEST_RESULTS_FILE",
            "REVIEW_COUNCIL_TEST_DISCOVER",
            "REVIEW_COUNCIL_TEST_SHARD",
            "REV_EVIDENCE_CASE",
            "REV_EVIDENCE_GROUP",
        ):
            with self.subTest(name=name):
                result = self.run_verify(env={name: "inherited"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("inherited scheduler selector", result.stderr)
                self.assertFalse(self.receipt().exists())
                self.assertFalse(sentinel.exists())

    def test_sanitized_environment_drops_unbound_behavior_variables(self):
        observed = self.base / "observed.json"
        calls = self.base / "calls"
        code = self.passing_shell(
            "import json, os\n"
            f"from pathlib import Path\nPath({str(observed)!r}).write_text(json.dumps({{"
            "'PYTHONPATH': os.environ.get('PYTHONPATH'), 'NODE_OPTIONS': os.environ.get('NODE_OPTIONS')}))\n"
            f"Path({str(calls)!r}).write_text('called')"
        )
        self.write_commands(code)
        first = self.run_verify(env={"PYTHONPATH": "/unexpected/one", "NODE_OPTIONS": "--inspect"})
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(json.loads(observed.read_text()), {"PYTHONPATH": None, "NODE_OPTIONS": None})
        second = self.run_verify(env={"PYTHONPATH": "/unexpected/two", "NODE_OPTIONS": "--trace-warnings"})
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("reused verification receipt", second.stdout)

    def test_child_observes_frozen_read_only_tree_while_source_changes(self):
        ready = self.base / "ready"
        release = self.base / "release"
        observed = self.base / "observed"
        code = self.passing_shell(f"""
from pathlib import Path
import os, stat, time
source = Path('marker.txt')
first = source.read_text()
Path({str(ready)!r}).touch()
deadline = time.monotonic() + 5
while not Path({str(release)!r}).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
second = source.read_text()
mode = stat.S_IMODE(source.stat().st_mode)
parent_mode = stat.S_IMODE(source.parent.stat().st_mode)
Path({str(observed)!r}).write_text(first + '|' + second + '|' + oct(mode) + '|' + oct(parent_mode))
if first != second or mode & 0o222 or parent_mode & 0o222:
    raise SystemExit(8)
""")
        self.write_commands(code)
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--root", str(self.repo), "--cache-dir", str(self.cache),
             "--commands", str(self.commands), "--timeout", "8"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists())
        (self.repo / "marker.txt").write_text("mutated\n")
        release.touch()
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertTrue(observed.read_text().startswith("captured\n|captured\n|"))

    def test_materialized_tree_mutation_blocks_receipt_publication(self):
        ready = self.base / "ready"
        release = self.base / "release"
        material_path = self.base / "material-path"
        code = self.passing_shell(f"""
from pathlib import Path
import time
Path({str(material_path)!r}).write_text(str(Path.cwd() / 'marker.txt'))
Path({str(ready)!r}).touch()
deadline = time.monotonic() + 5
while not Path({str(release)!r}).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
""")
        self.write_commands(code)
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--root", str(self.repo), "--cache-dir", str(self.cache),
             "--commands", str(self.commands), "--timeout", "8"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        target = Path(material_path.read_text())
        target.chmod(0o600)
        target.write_text("tampered\n")
        release.touch()
        stdout, stderr = process.communicate(timeout=10)
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        self.assertIn("materialized tree changed", stderr)
        self.assertFalse(self.receipt().exists())

    def test_tree_argv_and_child_environment_changes_rerun(self):
        calls = self.base / "calls"
        code = self.passing_shell(
            f"from pathlib import Path\np=Path({str(calls)!r}); p.write_text(p.read_text() + 'x' if p.exists() else 'x')"
        )
        self.write_commands(code)
        first = self.run_verify()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(calls.read_text(), "x")

        (self.repo / "marker.txt").write_text("new tree\n")
        second = self.run_verify()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(calls.read_text(), "xx")

        data = json.loads(self.commands.read_text())
        data["commands"][0]["argv"].append("unused-argv")
        self.commands.write_text(json.dumps(data))
        third = self.run_verify()
        self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
        self.assertEqual(calls.read_text(), "xxx")

        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        changed_path = str(bin_dir) + os.pathsep + os.environ["PATH"]
        fourth = self.run_verify(env={"PATH": changed_path})
        self.assertEqual(fourth.returncode, 0, fourth.stdout + fourth.stderr)
        self.assertEqual(calls.read_text(), "xxxx")

    def test_platform_and_tool_versions_are_receipt_identity(self):
        verifier = load_module()
        base = verifier.build_identity("tree", [], {"PATH": "/bin"}, {"system": "one"}, {"python": "one"})
        platform_changed = verifier.build_identity(
            "tree", [], {"PATH": "/bin"}, {"system": "two"}, {"python": "one"}
        )
        tool_changed = verifier.build_identity(
            "tree", [], {"PATH": "/bin"}, {"system": "one"}, {"python": "two"}
        )
        self.assertNotEqual(verifier.identity_key(base), verifier.identity_key(platform_changed))
        self.assertNotEqual(verifier.identity_key(base), verifier.identity_key(tool_changed))

    def test_repository_executable_uses_content_identity_without_version_probe(self):
        verifier = load_module()
        executable = self.repo / "runner.sh"
        executable.write_text("#!/bin/sh\nexit 19\n")
        executable.chmod(0o755)
        commands = [{"name": "shell", "kind": "shell", "argv": ["./runner.sh"]}]
        tools = verifier.tool_versions(commands, {"PATH": os.environ["PATH"]}, self.repo)
        expected = verifier.digest(executable.read_bytes())
        self.assertEqual(tools["./runner.sh"]["version"], "content-sha256:" + expected)

    def test_external_tool_versions_are_reprobed_when_binary_bytes_match(self):
        executable = self.base / "mutable-version-tool"
        version = self.base / "mutable-version"
        calls = self.base / "mutable-version-calls"
        executable.write_text(
            "#!/bin/sh\n"
            f"if [ \"$1\" = --version ]; then cat {str(version)!r}; "
            f"else printf x >> {str(calls)!r}; fi\n"
        )
        executable.chmod(0o755)
        version.write_text("version one\n")
        self.write_commands(self.passing_shell(), validators=[])
        data = json.loads(self.commands.read_text())
        data["commands"].append({
            "name": "external", "kind": "validator", "argv": [str(executable)],
        })
        self.commands.write_text(json.dumps(data))

        first = self.run_verify()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(calls.read_text(), "x")
        version.write_text("version two\n")

        second = self.run_verify()

        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(calls.read_text(), "xx")
        identity = json.loads(self.receipt().read_text())["identity"]
        self.assertEqual(identity["tools"][str(executable)]["version"], "version two")

    def test_external_version_probe_uses_gate_working_directory_and_home(self):
        executable = self.base / "context-version-tool"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import os,sys\n"
            "from pathlib import Path\n"
            "home=Path(os.environ['HOME'])\n"
            "home.mkdir(parents=True,exist_ok=True)\n"
            "context=home/'version-context'\n"
            "cwd=str(Path.cwd().resolve())\n"
            "if sys.argv[1:]==['--version']:\n"
            " context.write_text(cwd)\n"
            " print('context-tool 1')\n"
            "else:\n"
            " if context.read_text()!=cwd: raise SystemExit(17)\n"
            " (home/'gate-context').write_text(cwd)\n"
        )
        executable.chmod(0o755)
        self.write_commands(self.passing_shell())
        document = json.loads(self.commands.read_text())
        document["commands"].append({
            "name": "context-tool", "kind": "validator", "argv": [str(executable)],
        })
        self.commands.write_text(json.dumps(document))
        launcher = self.base / "launcher" / "work"
        launcher.mkdir(parents=True)

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.repo),
             "--cache-dir", str(self.cache), "--commands", str(self.commands), "--timeout", "8"],
            cwd=launcher, text=True, capture_output=True, timeout=20,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = self.owned_state()
        material = next((state / "trees").iterdir()).resolve()
        expected = str(material)
        self.assertEqual((state / "home" / "version-context").read_text(), expected)
        self.assertEqual((state / "home" / "gate-context").read_text(), expected)
        self.assertFalse((self.base / "home").exists())
        identity = json.loads(self.receipt().read_text())["identity"]
        self.assertEqual(identity["tools"][str(executable)]["version"], "context-tool 1")

    def test_default_indirect_toolchain_is_bound(self):
        verifier = load_module()
        tool_bin = self.base / "tool-bin"
        tool_bin.mkdir()
        for name in ("bash", "git", "node", "codex"):
            executable = tool_bin / name
            executable.write_text(f"#!/bin/sh\necho {name}-version\n")
            executable.chmod(0o755)
        commands = [{"name": "shell", "kind": "shell", "argv": [sys.executable, "-V"]}]

        tools = verifier.tool_versions(
            commands, {"PATH": str(tool_bin)}, self.repo,
            supplemental=verifier.DEFAULT_INDIRECT_TOOLS,
        )

        self.assertEqual(verifier.DEFAULT_INDIRECT_TOOLS, ("bash", "git", "node", "codex"))
        self.assertTrue({"bash", "git", "node", "codex"}.issubset(tools))

    def test_failed_command_or_tally_mismatch_writes_no_receipt(self):
        self.write_commands(self.passing_shell("raise SystemExit(7)"))
        failed = self.run_verify()
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(self.receipt().exists())

        self.write_commands("print('inventory_total=2'); print('tasks_passed=1 tasks_failed=0')")
        mismatch = self.run_verify()
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("shell result tally does not match inventory", mismatch.stderr)
        self.assertFalse(self.receipt().exists())

    def test_validator_timeout_is_bounded_and_writes_no_receipt(self):
        self.write_commands(self.passing_shell(), validators=["import time; time.sleep(30)"])
        started = time.monotonic()
        result = self.run_verify(extra_args=["--timeout", "1"])
        elapsed = time.monotonic() - started
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("verification command failed: validator-0", result.stderr)
        self.assertLess(elapsed, 6)
        self.assertFalse(self.receipt().exists())

    def test_successful_parent_with_stubborn_descendant_is_killed_and_fails(self):
        descendant_pid = self.base / "descendant.pid"
        descendant_ready = self.base / "descendant.ready"
        child_code = (
            "import signal,time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"Path({str(descendant_ready)!r}).touch()\n"
            "time.sleep(30)\n"
        )
        shell_code = self.passing_shell(
            "import subprocess,sys,time\n"
            "from pathlib import Path\n"
            f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            f"Path({str(descendant_pid)!r}).write_text(str(child.pid))\n"
            "deadline=time.monotonic()+3\n"
            f"while not Path({str(descendant_ready)!r}).exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
        )
        self.write_commands(shell_code)
        result = self.run_verify(timeout=20)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("verification command failed: shell", result.stderr)
        self.assertFalse(self.receipt().exists())
        pid = int(descendant_pid.read_text())
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail("verification left its command descendant running")
        finally:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

    def test_signal_cancellation_kills_every_gate_process_group(self):
        child_code = (
            "import signal,time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "Path(__import__('sys').argv[1]).write_text(str(__import__('os').getpid()))\n"
            "time.sleep(30)\n"
        )
        gate_code = (
            "import os,subprocess,sys,time\n"
            "from pathlib import Path\n"
            "name=sys.argv[1]\n"
            "root=Path(sys.argv[2])\n"
            "Path(root/(name+'.direct')).write_text(str(os.getpid()))\n"
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}, str(root/(name+'.descendant'))])\n"
            "deadline=time.monotonic()+5\n"
            "while not (root/(name+'.descendant')).exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
            "time.sleep(30)\n"
        )
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signal.Signals(signum).name):
                records = self.base / ("processes-" + str(signum))
                records.mkdir()
                cache = self.base / ("cache-" + str(signum))
                commands = []
                for name, kind in (("shell", "shell"), ("python", "python"), ("validator", "validator")):
                    commands.append({
                        "name": name,
                        "kind": kind,
                        "argv": [sys.executable, "-c", gate_code, name, str(records)],
                    })
                self.commands.write_text(json.dumps({"commands": commands}))
                process = subprocess.Popen(
                    [sys.executable, str(SCRIPT), "--root", str(self.repo),
                     "--cache-dir", str(cache), "--commands", str(self.commands), "--timeout", "30"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                expected = [records / (name + suffix)
                            for name in ("shell", "python", "validator")
                            for suffix in (".direct", ".descendant")]
                deadline = time.monotonic() + 8
                while not all(path.exists() for path in expected) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(all(path.exists() for path in expected))
                process.send_signal(signum)
                stdout, stderr = process.communicate(timeout=10)
                self.assertNotEqual(process.returncode, 0, stdout + stderr)
                self.assertFalse((self.owned_state(cache) / "receipt.json").exists())
                pids = [int(path.read_text()) for path in expected]
                try:
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        alive = []
                        for pid in pids:
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                continue
                            alive.append(pid)
                        if not alive:
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("signal cancellation left gate processes running: " + repr(alive))
                finally:
                    for pid in pids:
                        try:
                            os.kill(pid, 9)
                        except ProcessLookupError:
                            pass

    def test_installed_signal_handler_never_waits_for_coordination_lock(self):
        code = f"""
import importlib.util, os, signal
spec=importlib.util.spec_from_file_location('verifier', {str(SCRIPT)!r})
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
previous=module.install_signal_handlers()
module.ACTIVE_LOCK.acquire()
try:
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except module.VerificationCancelled:
        print('cancelled-with-lock-held')
finally:
    module.ACTIVE_LOCK.release()
    module.restore_signal_handlers(previous)
"""
        result = subprocess.run(
            [sys.executable, "-c", code], text=True, capture_output=True, timeout=3,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "cancelled-with-lock-held")

    def test_repeated_mixed_signals_do_not_interrupt_bounded_cleanup(self):
        records = self.base / "repeated-signal-processes"
        records.mkdir()
        cache = self.base / "repeated-signal-cache"
        child_code = (
            "import os,signal,sys,time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        gate_code = (
            "import os,signal,subprocess,sys,time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "name=sys.argv[1]\n"
            "root=Path(sys.argv[2])\n"
            "Path(root/(name+'.direct')).write_text(str(os.getpid()))\n"
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}, str(root/(name+'.descendant'))])\n"
            "deadline=time.monotonic()+5\n"
            "while not (root/(name+'.descendant')).exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
            "time.sleep(30)\n"
        )
        commands = [
            {"name": name, "kind": kind,
             "argv": [sys.executable, "-c", gate_code, name, str(records)]}
            for name, kind in (("shell", "shell"), ("python", "python"), ("validator", "validator"))
        ]
        self.commands.write_text(json.dumps({"commands": commands}))
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--root", str(self.repo),
             "--cache-dir", str(cache), "--commands", str(self.commands), "--timeout", "30"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        expected = [records / (name + suffix)
                    for name in ("shell", "python", "validator")
                    for suffix in (".direct", ".descendant")]
        deadline = time.monotonic() + 8
        while not all(path.exists() for path in expected) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(all(path.exists() for path in expected))
        started = time.monotonic()
        process.send_signal(signal.SIGINT)
        time.sleep(0.1)
        self.assertIsNone(process.poll())
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGTERM):
            process.send_signal(signum)
            time.sleep(0.03)
        stdout, stderr = process.communicate(timeout=8)
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        self.assertLess(time.monotonic() - started, 6)
        self.assertFalse((self.owned_state(cache) / "receipt.json").exists())
        pids = [int(path.read_text()) for path in expected]
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                alive = []
                for pid in pids:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        continue
                    alive.append(pid)
                if not alive:
                    break
                time.sleep(0.02)
            else:
                self.fail("repeated signals left gate processes running: " + repr(alive))
        finally:
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass

    def test_invalid_receipts_and_logs_rerun_fail_closed(self):
        calls = self.base / "calls"
        code = self.passing_shell(
            f"from pathlib import Path\np=Path({str(calls)!r}); p.write_text(p.read_text() + 'x' if p.exists() else 'x')"
        )
        self.write_commands(code)
        self.assertEqual(self.run_verify().returncode, 0)
        receipt = self.receipt()
        data = json.loads(receipt.read_text())
        shell_log = Path(data["logs"]["shell"]["path"])

        shell_log.write_text("truncated")
        self.assertEqual(self.run_verify().returncode, 0)
        self.assertEqual(calls.read_text(), "xx")

        receipt.write_text("{")
        self.assertEqual(self.run_verify().returncode, 0)
        self.assertEqual(calls.read_text(), "xxx")

        valid = self.base / "valid-receipt"
        valid.write_bytes(receipt.read_bytes())
        receipt.unlink()
        os.link(valid, receipt)
        self.assertEqual(self.run_verify().returncode, 0)
        self.assertEqual(calls.read_text(), "xxxx")

        valid.write_bytes(receipt.read_bytes())
        receipt.unlink()
        receipt.symlink_to(valid)
        self.assertEqual(self.run_verify().returncode, 0)
        self.assertEqual(calls.read_text(), "xxxxx")

        receipt.chmod(0)
        self.assertEqual(self.run_verify().returncode, 0)
        self.assertEqual(calls.read_text(), "xxxxxx")

        data = json.loads(receipt.read_text())
        shell_log = Path(data["logs"]["shell"]["path"])
        linked_log = self.base / "linked-log"
        linked_log.write_bytes(shell_log.read_bytes())
        shell_log.unlink()
        os.link(linked_log, shell_log)
        self.assertEqual(self.run_verify().returncode, 0)
        self.assertEqual(calls.read_text(), "xxxxxxx")

        data = json.loads(receipt.read_text())
        Path(data["logs"]["shell"]["path"]).unlink()
        self.assertEqual(self.run_verify().returncode, 0)
        self.assertEqual(calls.read_text(), "xxxxxxxx")

    def test_receipt_cannot_redirect_a_bound_log(self):
        calls = self.base / "calls"
        code = self.passing_shell(
            f"from pathlib import Path\np=Path({str(calls)!r}); p.write_text(p.read_text() + 'x' if p.exists() else 'x')"
        )
        self.write_commands(code)
        self.assertEqual(self.run_verify().returncode, 0)
        receipt = json.loads(self.receipt().read_text())
        original = Path(receipt["logs"]["shell"]["path"])
        redirected = self.base / "redirected.log"
        redirected.write_bytes(original.read_bytes())
        receipt["logs"]["shell"]["path"] = str(redirected)
        self.receipt().write_text(json.dumps(receipt))
        result = self.run_verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("reused verification receipt", result.stdout)
        self.assertEqual(calls.read_text(), "xx")

    def test_default_commands_and_workflow_use_one_verifier(self):
        verifier = load_module()
        self.assertEqual(
            [(row["name"], row["kind"], row["argv"]) for row in verifier.DEFAULT_COMMANDS],
            [
                ("shell", "shell", ["plugins/review-council/tests/run-tests.sh"]),
                ("python", "python", ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]),
                ("claude-marketplace", "validator", ["claude", "plugin", "validate", "--strict", ".claude-plugin/marketplace.json"]),
                ("claude-plugin", "validator", ["claude", "plugin", "validate", "--strict", "plugins/review-council"]),
                ("codex-marketplace", "validator", ["python3", "tests/check-codex-marketplace.py"]),
            ],
        )
        workflow = (REPO / ".github/workflows/test.yml").read_text()
        self.assertIn("python3 scripts/verify-review-council.py", workflow)
        self.assertNotIn("python3 -m unittest discover", workflow)
        self.assertNotIn("plugins/review-council/tests/run-tests.sh", workflow)


if __name__ == "__main__":
    unittest.main()
