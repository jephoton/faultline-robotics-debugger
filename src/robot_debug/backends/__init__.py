"""Where a Faultline diagnosis runs its GPU Jobs.

A backend hides how one Job is submitted, watched, cancelled and collected, so
the orchestrator can drive Nebius Serverless Jobs or (untested on a real GPU) a
local Docker container through the same small contract.

``download`` places the contents of the Job's export (everything the Job wrote
under ``faultline-runs/<job_name>/``) directly inside ``dest``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any, List, Mapping, Optional, Protocol, Sequence, runtime_checkable


class BackendError(RuntimeError):
    """A backend operation failed. The message is safe to print (ids redacted)."""


class CapacityError(BackendError):
    """Reserved: capacity problems are reported through ``JobResult.reason``."""


@dataclass(frozen=True)
class JobHandle:
    job_name: str
    job_id: Optional[str]


@dataclass(frozen=True)
class JobResult:
    job_name: str
    job_id: Optional[str]
    # COMPLETED | FAILED | ERROR | CANCELLED | TIMEOUT | UNKNOWN
    state: str
    # e.g. "NotEnoughResources", "ContainerFailed", "watchdog_cancel", or None
    reason: Optional[str]
    started_at: Optional[str]    # ISO-8601 UTC, None if the Job never started
    finished_at: Optional[str]
    container_seconds: Optional[float]


@runtime_checkable
class Backend(Protocol):
    kind: str

    def prepare(self, run_dir: Path, spec: Mapping[str, Any]) -> None:
        """Create the per-diagnosis resources (idempotent for a resumed run)."""

    def submit(self, job_name: str, workload: Mapping[str, Any]) -> JobHandle:
        """Start one Job; ``workload["run_id"]`` must equal ``job_name``."""

    def wait(self, handle: JobHandle, *, running_max_seconds: float,
             total_max_seconds: float, poll_seconds: float = 60.0) -> JobResult:
        """Block until the Job is terminal, cancelling it itself past a limit."""

    def download(self, handle: JobHandle, dest: Path) -> Path:
        """Fetch only this Job's export into ``dest`` and return ``dest``."""

    def logs_tail(self, handle: JobHandle, lines: int = 200) -> str:
        """The last ``lines`` lines of the Job's log (best effort)."""

    def lookup(self, job_name: str) -> Optional[JobHandle]:
        """The existing Job called ``job_name``, or ``None`` when it provably does not exist.

        Raises :class:`BackendError` when that cannot be told (an outage is not "never created").
        """

    def cancel(self, handle: JobHandle) -> str:
        """Stop the Job if it is still running (the handle may carry only the name).

        Returns ``cancelled`` (the cancel was sent and accepted), ``finished`` (already
        terminal) or ``not_found`` (no such Job); raises when the cancel could not be sent.
        """

    def finish(self) -> None:
        """Delete per-run credentials; idempotent and safe after failures."""

    def price_per_hour(self) -> float:
        """Hourly USD price used for the spend cap arithmetic."""


TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "ERROR", "CANCELLED", "TIMEOUT"})

# Resource ids look like ``aijob-e00fakejob00000001``: keep the kind and four
# characters so messages stay recognisable but are not usable as handles.
_LONG_ID = re.compile(r"\b([a-z][a-z0-9]*-[a-z0-9]{4})[a-z0-9]{8,}")


_BARE_ID = re.compile(r"\b(e0[0-9][a-z0-9])[a-z0-9]{8,}")


def redact(text: str) -> str:
    """Shorten resource ids (``aijob-e00r...``) in a message."""

    return _BARE_ID.sub(r"\1...", _LONG_ID.sub(r"\1...", text))


_JOB_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def check_job(job_name: str, workload: Mapping[str, Any]) -> None:
    """Reject a Job name or workload the export-prefix logic could not trust."""

    if not isinstance(job_name, str) or _JOB_NAME.match(job_name) is None:
        raise BackendError("job name must be 1-63 lowercase letters, digits or interior hyphens")
    if workload.get("run_id") != job_name:
        raise BackendError("workload run_id must equal the job name")


def write_workload(path: Path, workload: Mapping[str, Any]) -> None:
    """Write the workload JSON the Job reads (parents created, atomic replace)."""

    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(workload, sort_keys=True), encoding="utf-8")
    partial.replace(path)


def iso_utc(epoch: float) -> str:
    """Epoch seconds as an ISO-8601 UTC timestamp ending in Z."""

    from datetime import datetime, timezone
    stamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + "%06dZ" % stamp.microsecond


def run_command(argv: Sequence[str], *, cwd: Optional[Path] = None,
                timeout: Optional[float] = None) -> "subprocess.CompletedProcess[str]":
    """Run a command to completion with captured text output (the default runner).

    Backends take an injectable ``runner`` with this signature so tests never
    start a real process. Secrets must never be placed in ``argv``.
    """

    return subprocess.run(
        list(argv), cwd=None if cwd is None else str(cwd), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )


def make_backend(spec: Mapping[str, Any]) -> Backend:
    """Build the backend named by ``spec["backend"]["kind"]``."""

    backend = spec.get("backend") if isinstance(spec, Mapping) else None
    if not isinstance(backend, Mapping):
        raise BackendError("spec has no backend section")
    kind = backend.get("kind")
    if kind == "nebius":
        from .nebius import NebiusBackend
        return NebiusBackend.from_spec(spec)
    if kind == "local":
        from .local import LocalBackend
        return LocalBackend.from_spec(spec)
    raise BackendError("unknown backend kind %r (expected 'nebius' or 'local')" % (kind,))
