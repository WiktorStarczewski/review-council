"""Run one evidence preparation at a time on this machine, and only with memory to spare.

A preparation scans every text blob of the snapshot for the changed symbols, and on a large
repository it holds many gigabytes. The supervisor holds a machine-wide lock for the whole
preparation, starts it only when enough memory is free, stops it when free memory falls to a
floor, and runs it again once memory frees. Only a completed attempt's output reaches stdout.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

GUARDED = 'REV_PREPARE_GUARDED'
ATTEMPTS = 3
REFUSED = 75
LOG_HEADER = 'asked\twaited_s\tran_s\tattempts\tpeak_mb\tlowest_free_pct\texit\tsession\tlabel\n'


def setting(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def should_supervise():
    return os.environ.get('REV_PREPARE_GUARD', '1') != '0' and not os.environ.get(GUARDED)


def cache_dir():
    explicit = os.environ.get('REVIEW_COUNCIL_CACHE_DIR')
    if explicit:
        return Path(explicit)
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'review-council'


def free_percent():
    """The share of memory the system can hand out now, or None where it cannot be read."""
    probe = os.environ.get('REV_PREPARE_MEMORY_PROBE')
    try:
        if probe:
            return int(Path(probe).read_text().strip())
        if sys.platform == 'darwin':
            result = subprocess.run(['sysctl', '-n', 'kern.memorystatus_level'],
                                    capture_output=True, text=True, timeout=5)
            return int(result.stdout.strip())
        fields = {}
        with open('/proc/meminfo') as stream:
            for line in stream:
                name, _, value = line.partition(':')
                fields[name] = int(value.split()[0])
        return fields['MemAvailable'] * 100 // fields['MemTotal']
    except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError, subprocess.SubprocessError):
        return None


def physical_bytes():
    try:
        if sys.platform == 'darwin':
            result = subprocess.run(['sysctl', '-n', 'hw.memsize'],
                                    capture_output=True, text=True, timeout=5)
            return int(result.stdout.strip())
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def peak_bytes(usage):
    if usage is None:
        return 0
    return usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)


@contextmanager
def machine_lock(note):
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / 'evidence-prepare.lock',
                         os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            note('waiting for another evidence preparation on this machine')
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def wait_for_memory(needed, patience, note):
    """True once free memory reaches `needed` percent, False after `patience` seconds."""
    deadline = time.monotonic() + patience
    announced = None
    while True:
        free = free_percent()
        if free is None or free >= needed:
            return True
        now = time.monotonic()
        if now >= deadline:
            return False
        if announced is None or now - announced >= 60:
            note(f'waiting for memory: {free}% free, {needed}% needed to start the preparation')
            announced = now
        time.sleep(min(1.0, deadline - now))


def stop(pid):
    """Terminate the child, kill it if it still runs after five seconds, and reap it."""
    try:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            reaped, status, usage = os.wait4(pid, os.WNOHANG)
            if reaped:
                return status, usage
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
        _, status, usage = os.wait4(pid, 0)
        return status, usage
    except (ProcessLookupError, ChildProcessError):
        return 0, None


def run_once(argv, floor):
    """Run one attempt. Returns (exit status or None when stopped, stdout, peak, lowest, stopped at)."""
    environment = dict(os.environ, **{GUARDED: str(os.getpid())})
    lowest = None
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(argv, stdout=output, env=environment)
        try:
            delay = 0.02
            while True:
                reaped, status, usage = os.wait4(child.pid, os.WNOHANG)
                if reaped:
                    break
                free = free_percent()
                if free is not None:
                    lowest = free if lowest is None else min(lowest, free)
                    if free < floor:
                        status, usage = stop(child.pid)
                        child.returncode = os.waitstatus_to_exitcode(status)
                        return None, b'', peak_bytes(usage), lowest, free
                time.sleep(delay)
                delay = min(delay * 2, 1.0)
        except BaseException:
            if child.returncode is None:
                stop(child.pid)
                child.returncode = -signal.SIGTERM
            raise
        child.returncode = os.waitstatus_to_exitcode(status)
        output.seek(0)
        return child.returncode, output.read(), peak_bytes(usage), lowest, None


def exit_with_parent():
    """In the guarded child: exit when the supervisor that holds the machine lock is gone."""
    try:
        parent = int(os.environ.get(GUARDED, ''))
    except ValueError:
        return

    def watch():
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(REFUSED)

    threading.Thread(target=watch, daemon=True).start()


def record(row):
    path = cache_dir() / 'prepare.tsv'
    try:
        new = not path.exists()
        with open(path, 'a') as stream:
            if new:
                stream.write(LOG_HEADER)
            stream.write('\t'.join(str(value) for value in row) + '\n')
    except OSError:
        pass


def supervise(argv, session, label):
    """Run the preparation command `argv` under the guard and return its exit status."""
    def note(message):
        print('evidence: ' + message, file=sys.stderr, flush=True)

    start = setting('REV_PREPARE_MIN_FREE', 25)
    floor = setting('REV_PREPARE_FLOOR', 8)
    patience = setting('REV_PREPARE_WAIT', 1800)
    asked = time.time()
    began = None
    peak, lowest, attempts, code, needed = 0, None, 0, REFUSED, start
    with machine_lock(note):
        while True:
            if not wait_for_memory(needed, patience, note):
                note(f'free memory stayed under {needed}% for {patience} s; preparation refused')
                break
            attempts += 1
            began = began or time.time()
            status, output, used, low, stopped_at = run_once(argv, floor)
            peak = max(peak, used)
            if low is not None:
                lowest = low if lowest is None else min(lowest, low)
            if stopped_at is None:
                sys.stdout.buffer.write(output)
                sys.stdout.flush()
                code = status if status >= 0 else 128 - status
                break
            if attempts == ATTEMPTS:
                note(f'preparation stopped {ATTEMPTS} times for memory; free memory and run it again')
                break
            total = physical_bytes()
            if total:
                needed = max(start, min(95, floor + used * 125 // total))
            note(f'preparation stopped: free memory fell to {stopped_at}% (floor {floor}%) '
                 f'at {used >> 20} MB; retrying once {needed}% is free')
    finished = time.time()
    record([time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(asked)),
            int((began or finished) - asked), int(finished - began) if began else 0,
            attempts, peak >> 20, '-' if lowest is None else lowest, code, session, label])
    return code
