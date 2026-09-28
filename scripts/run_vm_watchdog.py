"""Windows entry point for the independently armed exact-VM watchdog.

Real use accepts no inline credentials.  ``--fake-cli`` is deliberately
rejected unless ``--local-test`` is also present, and that combination never
executes WSL or the Nebius CLI.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

from robot_debug import vm_watchdog
from robot_debug.vm_watchdog import GuardRecord, RecordError, load_record, watch


class ArmError(RuntimeError):
    """The watchdog could not be armed with a verified live child."""


def check(record_path: Path, control_root: Path, *, invoke: Callable[[list[str]], Any]) -> str:
    """Read only: validate and exact-ID read-back, never issue a stop."""

    record = load_record(record_path, control_root=control_root, now_utc=datetime.now(timezone.utc))
    vm_watchdog._get_verified(record, invoke)
    return "checked"


def arm(
    record_path: Path,
    control_root: Path,
    *,
    local_test: bool = False,
    fake_cli: Path | None = None,
    process_factory: Callable[..., Any] = subprocess.Popen,
    handshake_seconds: float = 15.0,
) -> int:
    """Start watch detached and return only after durable ``armed`` evidence."""

    record = load_record(record_path, control_root=control_root, now_utc=datetime.now(timezone.utc))
    if fake_cli is not None and not local_test:
        raise ArmError("fake CLI is permitted only in explicit local-test mode")
    if local_test and fake_cli is None:
        raise ArmError("local-test arm requires a fake CLI response file")
    if fake_cli is not None and not fake_cli.is_file():
        raise ArmError("fake CLI response file is missing")
    run_dir = record.log_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / "arm.lock"
    if record.log_path.exists():
        raise ArmError("watchdog log already exists; use a fresh run directory after verifying the exact VM")
    _create_lock(lock_path)
    stdout_path = run_dir / "watchdog.stdout.log"
    stderr_path = run_dir / "watchdog.stderr.log"
    command = [
        sys.executable, str(Path(__file__).resolve()), "watch", "--record", str(record_path),
        "--control-root", str(control_root),
    ]
    if local_test:
        command.extend(["--local-test", "--fake-cli", str(fake_cli)])
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        child = process_factory(
            command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=env,
            creationflags=flags, close_fds=True,
        )
    deadline = time.monotonic() + handshake_seconds
    while time.monotonic() <= deadline:
        if child.poll() is not None:
            raise ArmError("watch child exited before durable armed event")
        if _has_event(record.log_path, "armed"):
            (run_dir / "watchdog.pid").write_text(str(child.pid), encoding="ascii")
            # The parent deliberately does not own or reap this detached
            # watchdog.  Mark the disposable Popen handle closed so CPython
            # does not emit a false "still running" ResourceWarning on arm
            # process exit; this does not signal or alter the child process.
            if isinstance(child, subprocess.Popen):
                child.returncode = 0
            return int(child.pid)
        time.sleep(0.05)
    raise ArmError("watch child did not write durable armed event before handshake deadline")


def _create_lock(path: Path) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as error:
        raise ArmError("arm lock exists; verify exact VM state before human removal") from error
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write("armed-pending\n")
        handle.flush()
        os.fsync(handle.fileno())


def _has_event(path: Path, expected: str) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("event") == expected:
            return True
    return False


def _real_invoke(argv: list[str]) -> Any:
    completed = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=45)
    return completed.stdout


def _fake_invoke(path: Path) -> Callable[[list[str]], Any]:
    """Return deterministic fixture responses and never create a subprocess."""

    try:
        responses = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecordError("fake CLI response file must be JSON") from error
    if not isinstance(responses, list):
        raise RecordError("fake CLI response file must be a JSON array")
    index = 0
    def invoke(_: list[str]) -> Any:
        nonlocal index
        if index >= len(responses):
            raise OSError("fake CLI response exhausted")
        response = responses[index]
        index += 1
        if isinstance(response, dict) and "raise" in response:
            raise OSError(str(response["raise"]))
        return response
    return invoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "arm", "watch"))
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--local-test", action="store_true")
    parser.add_argument("--fake-cli", type=Path)
    args = parser.parse_args(argv)
    if args.fake_cli is not None and not args.local_test:
        parser.error("--fake-cli requires --local-test")
    invoke = _fake_invoke(args.fake_cli) if args.local_test and args.fake_cli else _real_invoke
    try:
        if args.mode == "check":
            check(args.record, args.control_root, invoke=invoke)
        elif args.mode == "arm":
            arm(args.record, args.control_root, local_test=args.local_test, fake_cli=args.fake_cli)
        else:
            record = load_record(args.record, control_root=args.control_root, now_utc=datetime.now(timezone.utc))
            result = watch(record, invoke=invoke)
            if result == "stop_unconfirmed":
                print("URGENT: exact VM stop is unconfirmed; inspect the Nebius console and stop it manually", file=sys.stderr)
                return 2
    except (ArmError, RecordError, OSError, subprocess.SubprocessError) as error:
        print("watchdog failed closed: {}".format(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
