from __future__ import annotations

import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from robot_debug.job_process import DirectEvaluator, InfrastructureError, direct_command


class DirectCommandTests(unittest.TestCase):
    def test_builds_direct_no_docker_command(self) -> None:
        self.assertEqual(
            direct_command(
                "/opt/conda/envs/libero/bin/vla-eval",
                ["vla-eval", "run", "--config", "episode.yaml"],
            ),
            [
                "/opt/conda/envs/libero/bin/vla-eval",
                "run",
                "--config",
                "episode.yaml",
                "--no-docker",
            ],
        )

    def test_rejects_unsupported_command_shapes(self) -> None:
        unsupported = (
            ["vla-eval", "inspect", "--config", "episode.yaml"],
            ["other", "run", "--config", "episode.yaml"],
            ["vla-eval", "run", "episode.yaml"],
            ["vla-eval", "run", "--config", "episode.yaml", "--verbose"],
            ["vla-eval", "run", "--config", "episode.yaml", "--config", "other.yaml"],
            ["vla-eval", "run", "--config", "episode.yaml", "--no-docker"],
        )
        for command in unsupported:
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    direct_command("/usr/bin/vla-eval", command)

    def test_rejects_invalid_argument_types(self) -> None:
        invalid_calls = (
            (None, ["vla-eval", "run", "--config", "episode.yaml"]),
            ("", ["vla-eval", "run", "--config", "episode.yaml"]),
            ("/usr/bin/vla-eval\x00bad", ["vla-eval", "run", "--config", "episode.yaml"]),
            ("/usr/bin/vla-eval", "vla-eval run --config episode.yaml"),
            ("/usr/bin/vla-eval", ["vla-eval", "run", "--config", 3]),
            ("/usr/bin/vla-eval", ["vla-eval", "run", "--config", ""]),
        )
        for executable, command in invalid_calls:
            with self.subTest(executable=executable, command=command):
                with self.assertRaises((TypeError, ValueError)):
                    direct_command(executable, command)  # type: ignore[arg-type]


class DirectEvaluatorValidationTests(unittest.TestCase):
    def test_rejects_invalid_timeouts_and_environment(self) -> None:
        invalid_timeouts = (True, 0, -1, float("inf"), float("nan"), "5")
        for timeout in invalid_timeouts:
            with self.subTest(timeout=timeout):
                with self.assertRaises((TypeError, ValueError)):
                    DirectEvaluator(
                        executable="/usr/bin/vla-eval",
                        timeout_seconds=timeout,  # type: ignore[arg-type]
                        env={},
                        log_root="logs",
                    )
        with self.assertRaises(TypeError):
            DirectEvaluator(
                executable="/usr/bin/vla-eval",
                timeout_seconds=1,
                env={"COUNT": 1},  # type: ignore[dict-item]
                log_root="logs",
            )

    @unittest.skipIf(os.name == "posix", "Windows-only fail-closed check")
    def test_fails_closed_on_non_posix(self) -> None:
        evaluator = DirectEvaluator(
            executable="C:/vla-eval.exe",
            timeout_seconds=1,
            env={},
            log_root="logs",
        )
        with self.assertRaisesRegex(InfrastructureError, "POSIX"):
            evaluator(
                ["vla-eval", "run", "--config", "episode.yaml"],
                cwd=".",
                check=False,
            )


@unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
class DirectEvaluatorPosixTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.logs = self.root / "logs"
        self.executable = self.root / "fixture-evaluator"
        self.executable.write_text(
            textwrap.dedent(
                """\
                #!{python}
                import pathlib
                import sys

                config = pathlib.Path(sys.argv[sys.argv.index("--config") + 1])
                exec(compile(config.read_text(encoding="utf-8"), str(config), "exec"))
                """
            ).format(python=sys.executable),
            encoding="utf-8",
        )
        self.executable.chmod(0o755)
        self._owned_groups: set[int] = set()

    def tearDown(self) -> None:
        for process_group in self._owned_groups:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self._temporary.cleanup()

    def _config(self, source: str) -> Path:
        path = self.root / "scenario.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return path

    def _evaluator(self, timeout: float = 2.0, **kwargs: object) -> DirectEvaluator:
        return DirectEvaluator(
            executable=str(self.executable),
            timeout_seconds=timeout,
            env=dict(os.environ),
            log_root=self.logs,
            **kwargs,
        )

    def _run(self, source: str, *, timeout: float = 2.0) -> subprocess.CompletedProcess[str]:
        config = self._config(source)
        return self._evaluator(timeout)(
            ["vla-eval", "run", "--config", str(config)],
            cwd=self.root,
            check=False,
        )

    def _remember_group(self, path: Path) -> int:
        process_group = int(path.read_text(encoding="utf-8"))
        self._owned_groups.add(process_group)
        return process_group

    def assertGroupAbsent(self, process_group: int) -> None:  # noqa: N802
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            self._owned_groups.discard(process_group)
            return
        self.fail("test-owned process group {} still exists".format(process_group))

    def test_success_returns_only_after_group_is_absent_and_writes_logs(self) -> None:
        group_file = self.root / "group.txt"
        result = self._run(
            """
            import os
            import pathlib
            pathlib.Path({group_file!r}).write_text(str(os.getpgrp()), encoding="utf-8")
            print("fixture output", flush=True)
            """.format(group_file=str(group_file))
        )
        process_group = self._remember_group(group_file)

        self.assertEqual(result.returncode, 0)
        self.assertGroupAbsent(process_group)
        stdout_logs = list(self.logs.glob("*.stdout.log"))
        stderr_logs = list(self.logs.glob("*.stderr.log"))
        self.assertEqual(len(stdout_logs), 1)
        self.assertEqual(len(stderr_logs), 1)
        self.assertIn("fixture output", stdout_logs[0].read_text(encoding="utf-8"))

    def test_nonzero_return_retains_code_after_group_is_absent(self) -> None:
        group_file = self.root / "group.txt"
        result = self._run(
            """
            import os
            import pathlib
            import sys
            pathlib.Path({group_file!r}).write_text(str(os.getpgrp()), encoding="utf-8")
            sys.exit(7)
            """.format(group_file=str(group_file))
        )
        process_group = self._remember_group(group_file)

        self.assertEqual(result.returncode, 7)
        self.assertGroupAbsent(process_group)

    def test_successful_leader_with_live_child_is_cleaned_before_return(self) -> None:
        if sys.platform != "linux":
            self.skipTest("Linux subreaper acceptance")
        child_file = self.root / "child.txt"
        group_file = self.root / "group.txt"
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        try:
            result = self._run(
                """
                import os
                import pathlib
                import subprocess
                import sys
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                pathlib.Path({child_file!r}).write_text(str(child.pid), encoding="utf-8")
                pathlib.Path({group_file!r}).write_text(str(os.getpgrp()), encoding="utf-8")
                """.format(child_file=str(child_file), group_file=str(group_file))
            )
        finally:
            self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)
        process_group = self._remember_group(group_file)

        self.assertEqual(result.returncode, 0)
        self.assertGroupAbsent(process_group)
        child_pid = int(child_file.read_text(encoding="utf-8"))
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_timeout_cleans_group_then_raises_timeout_expired(self) -> None:
        group_file = self.root / "group.txt"
        config = self._config(
            """
            import os
            import pathlib
            import time
            pathlib.Path({group_file!r}).write_text(str(os.getpgrp()), encoding="utf-8")
            time.sleep(60)
            """.format(group_file=str(group_file))
        )

        with self.assertRaises(subprocess.TimeoutExpired):
            self._evaluator(0.5)(
                ["vla-eval", "run", "--config", str(config)],
                cwd=self.root,
                check=False,
            )
        process_group = self._remember_group(group_file)
        self.assertGroupAbsent(process_group)

    def test_keyboard_interrupt_cleans_group_then_reraises(self) -> None:
        group_file = self.root / "group.txt"
        config = self._config(
            """
            import os
            import pathlib
            import signal
            import time
            pathlib.Path({group_file!r}).write_text(str(os.getpgrp()), encoding="utf-8")
            os.kill(os.getppid(), signal.SIGINT)
            time.sleep(60)
            """.format(group_file=str(group_file))
        )

        with self.assertRaises(KeyboardInterrupt):
            self._evaluator()(
                ["vla-eval", "run", "--config", str(config)],
                cwd=self.root,
                check=False,
            )
        process_group = self._remember_group(group_file)
        self.assertGroupAbsent(process_group)

    def test_unconfirmed_group_cleanup_raises_infrastructure_error(self) -> None:
        config = self._config("pass")
        evaluator = self._evaluator(
            term_grace_seconds=0.01,
            kill_grace_seconds=0.01,
        )
        with mock.patch("robot_debug.job_process._process_group_exists", return_value=True):
            with self.assertRaisesRegex(InfrastructureError, "process group"):
                evaluator(
                    ["vla-eval", "run", "--config", str(config)],
                    cwd=self.root,
                    check=False,
                )


if __name__ == "__main__":
    unittest.main()
