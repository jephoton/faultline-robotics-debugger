"""Direct, bounded evaluator execution for a finite POSIX Job.

The evaluator is launched without a shell in a new session.  Its process group
must be gone before a result (including a robot-policy failure) is returned.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Mapping, Sequence
import uuid


class InfrastructureError(RuntimeError):
    """The evaluator lifecycle could not be proven safely contained."""


def direct_command(executable: os.PathLike[str] | str, command: Sequence[str]) -> list[str]:
    """Translate the one supported runner command to a no-Docker direct exec."""

    executable_text = _path_text(executable, "executable")
    if isinstance(command, (str, bytes)) or not isinstance(command, (list, tuple)):
        raise TypeError("command must be a list or tuple of strings")
    if any(not isinstance(argument, str) for argument in command):
        raise TypeError("command arguments must be strings")
    if (
        len(command) != 4
        or command[0] not in ("vla-eval", executable_text)
        or list(command[1:3]) != ["run", "--config"]
    ):
        raise ValueError("only the configured evaluator 'run --config PATH' is supported")
    config_path = command[3]
    if not config_path or "\x00" in config_path:
        raise ValueError("config path must be a non-empty string without NUL")
    return [executable_text, "run", "--config", config_path, "--no-docker"]


class DirectEvaluator:
    """Callable runner that owns and bounds one evaluator process group."""

    def __init__(
        self,
        *,
        executable: os.PathLike[str] | str,
        timeout_seconds: float,
        env: Mapping[str, str],
        log_root: os.PathLike[str] | str,
        term_grace_seconds: float = 5.0,
        kill_grace_seconds: float = 2.0,
    ) -> None:
        self._executable = _path_text(executable, "executable")
        self._timeout_seconds = _positive_finite(timeout_seconds, "timeout_seconds")
        self._term_grace_seconds = _nonnegative_finite(
            term_grace_seconds, "term_grace_seconds"
        )
        self._kill_grace_seconds = _nonnegative_finite(
            kill_grace_seconds, "kill_grace_seconds"
        )
        if self._term_grace_seconds > 5.0:
            raise ValueError("term_grace_seconds cannot exceed 5 seconds")
        if self._kill_grace_seconds > 2.0:
            raise ValueError("kill_grace_seconds cannot exceed 2 seconds")
        if not isinstance(env, Mapping):
            raise TypeError("env must be a mapping of strings")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
            raise TypeError("env must be a mapping of strings")
        self._env = dict(env)
        self._log_root = Path(_path_text(log_root, "log_root"))

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: os.PathLike[str] | str,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if os.name != "posix":
            raise InfrastructureError("direct evaluator execution requires POSIX process groups")
        if not isinstance(check, bool):
            raise TypeError("check must be a boolean")
        cwd_text = _path_text(cwd, "cwd")
        argv = direct_command(self._executable, command)
        stdout_path, stderr_path = self._new_log_paths()

        with stdout_path.open("xb") as stdout_log, stderr_path.open("xb") as stderr_log:
            process = subprocess.Popen(
                argv,
                cwd=cwd_text,
                env=self._env,
                shell=False,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=stdout_log,
                stderr=stderr_log,
            )
            process_group = process.pid
            try:
                try:
                    return_code = process.wait(timeout=self._timeout_seconds)
                except subprocess.TimeoutExpired:
                    self._terminate_and_confirm(process, process_group)
                    raise
                except KeyboardInterrupt:
                    self._terminate_and_confirm(process, process_group)
                    raise
                except BaseException:
                    self._terminate_and_confirm(process, process_group)
                    raise

                if _process_group_exists(process_group):
                    self._terminate_and_confirm(process, process_group)
                if _process_group_exists(process_group):
                    raise InfrastructureError(
                        "evaluator process group absence could not be confirmed"
                    )
                result = subprocess.CompletedProcess(argv, return_code)
                if check:
                    result.check_returncode()
                return result
            finally:
                # ``wait`` and cleanup normally reap the leader.  This final poll
                # also reaps a leader that exited during an exceptional path.
                process.poll()

    def _new_log_paths(self) -> tuple[Path, Path]:
        if self._log_root.is_symlink():
            raise InfrastructureError("log_root must not be a symbolic link")
        try:
            self._log_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise InfrastructureError("log_root could not be created") from error
        if not self._log_root.is_dir():
            raise InfrastructureError("log_root must be a directory")
        identifier = uuid.uuid4().hex
        return (
            self._log_root / (identifier + ".stdout.log"),
            self._log_root / (identifier + ".stderr.log"),
        )

    def _terminate_and_confirm(
        self, process: subprocess.Popen[bytes], process_group: int
    ) -> None:
        if not _process_group_exists(process_group):
            process.poll()
            return
        _signal_process_group(process_group, signal.SIGTERM)
        if _await_group_absence(process, process_group, self._term_grace_seconds):
            return
        _signal_process_group(process_group, signal.SIGKILL)
        if _await_group_absence(process, process_group, self._kill_grace_seconds):
            return
        raise InfrastructureError("evaluator process group cleanup could not be confirmed")


def _path_text(value: os.PathLike[str] | str, name: str) -> str:
    if isinstance(value, bytes):
        raise TypeError("{} must be a text path".format(name))
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise TypeError("{} must be a text path".format(name)) from error
    if not isinstance(text, str):
        raise TypeError("{} must be a text path".format(name))
    if not text or "\x00" in text:
        raise ValueError("{} must be non-empty and contain no NUL".format(name))
    return text


def _positive_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("{} must be a number".format(name))
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("{} must be finite and positive".format(name))
    return result


def _nonnegative_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("{} must be a number".format(name))
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("{} must be finite and non-negative".format(name))
    return result


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError as error:
        raise InfrastructureError("cannot inspect evaluator process group") from error
    return True


def _signal_process_group(process_group: int, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(process_group, requested_signal)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        raise InfrastructureError("cannot signal evaluator process group") from error


def _await_group_absence(
    process: subprocess.Popen[bytes], process_group: int, grace_seconds: float
) -> bool:
    deadline = time.monotonic() + grace_seconds
    while True:
        process.poll()
        _reap_group_children(process_group)
        if not _process_group_exists(process_group):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _reap_group_children(process_group: int) -> None:
    """Reap group orphans when this runtime is PID 1 or a Linux subreaper."""

    while True:
        try:
            child_pid, _ = os.waitpid(-process_group, os.WNOHANG)
        except ChildProcessError:
            return
        if child_pid == 0:
            return
