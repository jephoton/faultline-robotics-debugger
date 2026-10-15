"""Fakes for the backend tests: a clock, a fake docker and a fake process."""

import json
import subprocess


class FakeClock:
    """Epoch seconds that advance only when the fake ``sleep`` is called."""

    def __init__(self, start=1_800_000_000.0):
        self.now = float(start)
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(list(argv), returncode, stdout, stderr)


class FakeProcess:
    """Exits with ``returncode`` once the clock passes ``run_for`` seconds."""

    def __init__(self, argv, clock, run_for, returncode, kwargs):
        self.argv = list(argv)
        self.kwargs = kwargs
        self._clock = clock
        self._end = clock() + run_for
        self._final = returncode
        self.returncode = None
        self.killed = False

    def poll(self):
        if self.returncode is None and self._clock() >= self._end:
            self.returncode = self._final
        return self.returncode

    def end_now(self, returncode=137):
        self.returncode = returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeDocker:
    """A fake docker CLI: ``run`` is the runner, ``popen`` starts containers."""

    def __init__(self, clock, runtimes=("runc", "nvidia"), run_for=10.0,
                 returncode=0, ignore_stop=False):
        self.clock = clock
        self.runtimes = runtimes
        self.run_for = run_for
        self.returncode = returncode
        self.ignore_stop = ignore_stop
        self.calls = []
        self.processes = []

    def run(self, argv, cwd=None, timeout=None):
        self.calls.append(list(argv))
        if list(argv[1:2]) == ["info"]:
            return completed(argv, 0, json.dumps({name: {} for name in self.runtimes}), "")
        if list(argv[1:2]) == ["inspect"]:
            known = any(argv[-1] in process.argv for process in self.processes)
            return completed(argv, 0 if known else 1, "running" if known else "", "" if known else "No such object")
        if list(argv[1:2]) == ["stop"]:
            if not self.ignore_stop:
                for process in self.processes:
                    process.end_now(137)
            return completed(argv, 0, argv[-1], "")
        return completed(argv, 1, "", "unexpected docker call")

    def popen(self, argv, **kwargs):
        process = FakeProcess(argv, self.clock, self.run_for, self.returncode, kwargs)
        self.processes.append(process)
        return process
