"""Machine-wide guard around evidence preparation: lock, memory gate, floor stop and retry."""

import fcntl
import importlib.util
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch


LIB = Path(__file__).resolve().parents[1] / "plugins/review-council/scripts/lib"
GUARD = LIB / "prepare_guard.py"


def wait_until(condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                           capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


class PrepareGuardTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("prepare_guard_under_test", GUARD)
        self.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.guard)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.probe = self.root / "free-memory"
        self.set_free(90)
        patcher = patch.dict(os.environ, {"REVIEW_COUNCIL_CACHE_DIR": str(self.root / "cache"),
                                          "REV_PREPARE_MEMORY_PROBE": str(self.probe)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("REV_PREPARE_GUARD", "REV_PREPARE_GUARDED", "REV_PREPARE_MIN_FREE",
                     "REV_PREPARE_FLOOR", "REV_PREPARE_WAIT"):
            os.environ.pop(name, None)

    def set_free(self, percent):
        partial = self.probe.with_suffix(".partial")
        partial.write_text(f"{percent}\n")
        os.replace(partial, self.probe)

    def script(self, body):
        return [sys.executable, "-c", textwrap.dedent(body)]

    def supervise(self, argv):
        stdout, stderr = io.BytesIO(), io.StringIO()
        text = io.TextIOWrapper(stdout, encoding="utf-8")
        with patch.object(sys, "stdout", text), patch.object(sys, "stderr", stderr):
            code = self.guard.supervise(argv, str(self.root / "session"), "1")
            text.flush()
        return code, stdout.getvalue().decode(), stderr.getvalue()

    def log_rows(self):
        lines = (self.root / "cache" / "prepare.tsv").read_text().splitlines()
        self.assertEqual(lines[0], self.guard.LOG_HEADER.rstrip("\n"))
        return [line.split("\t") for line in lines[1:]]

    def test_completed_attempt_forwards_output_and_status(self):
        code, stdout, _ = self.supervise(self.script("""
            import os, sys
            print("manifest", os.environ["REV_PREPARE_GUARDED"])
            sys.exit(3)
        """))
        self.assertEqual(code, 3)
        self.assertEqual(stdout, f"manifest {os.getpid()}\n")
        row = self.log_rows()[0]
        self.assertEqual((row[3], row[6], row[8]), ("1", "3", "1"))

    def test_guarded_child_and_disabled_guard_do_not_supervise(self):
        self.assertTrue(self.guard.should_supervise())
        with patch.dict(os.environ, {"REV_PREPARE_GUARDED": "123"}):
            self.assertFalse(self.guard.should_supervise())
        with patch.dict(os.environ, {"REV_PREPARE_GUARD": "0"}):
            self.assertFalse(self.guard.should_supervise())

    def test_waits_for_the_machine_lock(self):
        marker = self.root / "ran"
        lock_path = self.root / "cache" / "evidence-prepare.lock"
        lock_path.parent.mkdir(parents=True)
        holder = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(holder, fcntl.LOCK_EX)
        result = {}
        stderr = io.StringIO()

        def run():
            argv = self.script(f"open({str(marker)!r}, 'w').close()")
            with patch.object(sys, "stderr", stderr):
                result["code"] = self.guard.supervise(argv, "s", "1")

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(wait_until(lambda: "waiting for another evidence preparation"
                                       in stderr.getvalue()))
            time.sleep(0.3)
            self.assertFalse(marker.exists())
        finally:
            os.close(holder)
        worker.join(20)
        self.assertEqual(result.get("code"), 0)
        self.assertTrue(marker.exists())

    def test_refuses_when_memory_stays_short(self):
        marker = self.root / "ran"
        self.set_free(10)
        with patch.dict(os.environ, {"REV_PREPARE_WAIT": "1"}):
            code, stdout, stderr = self.supervise(
                self.script(f"open({str(marker)!r}, 'w').close()"))
        self.assertEqual(code, self.guard.REFUSED)
        self.assertEqual(stdout, "")
        self.assertIn("free memory stayed under 25% for 1 s; preparation refused", stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.log_rows()[0][3], "0")

    def test_stops_at_the_floor_and_retries_once_memory_frees(self):
        attempts = self.root / "attempts"
        argv = self.script(f"""
            import pathlib, time
            path = pathlib.Path({str(attempts)!r})
            count = int(path.read_text()) + 1 if path.exists() else 1
            path.write_text(str(count))
            if count == 1:
                print("partial output that must be discarded", flush=True)
                time.sleep(60)
            print("manifest")
        """)
        stderr = io.StringIO()

        def drive():
            if wait_until(lambda: attempts.exists()):
                self.set_free(5)
            if wait_until(lambda: "preparation stopped" in stderr.getvalue()):
                self.set_free(90)

        driver = threading.Thread(target=drive)
        driver.start()
        stdout = io.BytesIO()
        text = io.TextIOWrapper(stdout, encoding="utf-8")
        with patch.object(sys, "stdout", text), patch.object(sys, "stderr", stderr):
            code = self.guard.supervise(argv, "s", "1")
            text.flush()
        driver.join(20)
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().decode(), "manifest\n")
        self.assertEqual(attempts.read_text(), "2")
        self.assertIn("preparation stopped: free memory fell to 5% (floor 8%)", stderr.getvalue())
        row = self.log_rows()[0]
        self.assertEqual((row[3], row[5], row[6]), ("2", "5", "0"))

    def test_a_stopped_attempt_refuses_when_memory_stays_short(self):
        self.set_free(45)
        environment = {"REV_PREPARE_MIN_FREE": "40", "REV_PREPARE_FLOOR": "50",
                       "REV_PREPARE_WAIT": "1"}
        with patch.dict(os.environ, environment):
            code, stdout, stderr = self.supervise(self.script("""
                import time
                print("partial", flush=True)
                time.sleep(60)
            """))
        self.assertEqual(code, self.guard.REFUSED)
        self.assertEqual(stdout, "")
        self.assertIn("preparation stopped: free memory fell to 45% (floor 50%)", stderr)
        self.assertIn("preparation refused", stderr)
        self.assertEqual(self.log_rows()[0][3], "1")

    def test_a_terminated_supervisor_stops_its_child(self):
        pid_file = self.root / "child.pid"
        child = textwrap.dedent(f"""
            import os, pathlib, time
            pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))
            time.sleep(60)
        """)
        harness = textwrap.dedent(f"""
            import signal, sys
            sys.path.insert(0, {str(LIB)!r})
            import prepare_guard
            signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
            sys.exit(prepare_guard.supervise([sys.executable, "-c", {child!r}], "s", "1"))
        """)
        supervisor = subprocess.Popen([sys.executable, "-c", harness])
        self.addCleanup(lambda: supervisor.poll() is None and supervisor.kill())
        self.assertTrue(wait_until(lambda: pid_file.exists() and pid_file.read_text()))
        child_pid = int(pid_file.read_text())
        supervisor.send_signal(signal.SIGTERM)
        self.assertEqual(supervisor.wait(20), 128 + signal.SIGTERM)
        self.assertFalse(alive(child_pid))

    def test_a_guarded_child_exits_when_its_supervisor_dies(self):
        pid_file = self.root / "child.pid"
        child = textwrap.dedent(f"""
            import os, pathlib, sys, time
            sys.path.insert(0, {str(LIB)!r})
            import prepare_guard
            prepare_guard.exit_with_parent()
            pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))
            time.sleep(60)
        """)
        parent = textwrap.dedent(f"""
            import os, subprocess, sys, time
            environment = dict(os.environ, REV_PREPARE_GUARDED=str(os.getpid()))
            subprocess.Popen([sys.executable, "-c", {child!r}], env=environment)
            time.sleep(60)
        """)
        supervisor = subprocess.Popen([sys.executable, "-c", parent])
        self.addCleanup(lambda: supervisor.poll() is None and supervisor.kill())
        self.assertTrue(wait_until(lambda: pid_file.exists() and pid_file.read_text()))
        child_pid = int(pid_file.read_text())
        self.assertTrue(alive(child_pid))
        supervisor.kill()
        supervisor.wait(20)
        self.assertTrue(wait_until(lambda: not alive(child_pid)))

    def test_free_memory_reads_on_this_platform(self):
        del os.environ["REV_PREPARE_MEMORY_PROBE"]
        free = self.guard.free_percent()
        if sys.platform == "darwin" or Path("/proc/meminfo").exists():
            self.assertIsInstance(free, int)
            self.assertTrue(0 <= free <= 100, free)
        total = self.guard.physical_bytes()
        self.assertTrue(total is None or total > 0)


if __name__ == "__main__":
    unittest.main()
