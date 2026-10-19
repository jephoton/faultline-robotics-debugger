"""Which ``faultline`` runs are alive, and how far they have got (ADR 0033).

A run is *active* when its ``process.json`` (written by ``faultline diagnose`` and ``replay`` into the run
folder and deleted when they end) names a live process, whoever started it: the control panel or a terminal.
Progress is read from the files the run already keeps (``steps.json``, ``ledger.json``, ``stop-request.json``
and the run log); nothing here calls the cloud, so it is cheap and safe to poll.

Liveness is the operating system's answer for the recorded process id, guarded against id reuse: a process
created after the recorded ``started_at`` is not the one that wrote the record.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional

from robot_debug.viewer.stop_reasons import NOT_ATTENTION, needs_attention, stop_text

PROCESS_FILE = "process.json"            # robot_debug.cli.PROCESS_FILE
STOP_REQUEST_FILE = "stop-request.json"  # robot_debug.orchestrator.STOP_REQUEST_FILE
LAUNCH_FILE = "ui-launch.json"           # written by the launcher: where the detached run's log is
LOG_TAIL_LINES = 40
LOG_LINE_LIMIT = 300
CREATED_TOLERANCE_SECONDS = 5.0          # a process created this long after started_at is another process
RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\Z")

STEP_LABELS = {
    "import": "Import the start", "screen": "Screen the starts", "plan": "Plan the reduction",
    "reduce": "Reduce the cause", "report": "Write the report", "case": "Save the case",
    "explain": "Nemotron's reading", "register": "Add to the library", "paraphrase": "Write the paraphrases",
    "audit": "Run the audit", "replay": "Replay the case",
    "rewording-screen": "Screen the rewordings", "rewording-reduce": "Reduce the wording",
    "case-audit": "Save the stress-test case", "case-wording": "Save the wording case",
}
ROUTES = ("layout", "probes", "passes", "flaky")
# Where a mode's step means something else (a paraphrase run screens rewordings, not starts).
MODE_STEP_LABELS = {
    "paraphrase": {"screen": "Screen the rewordings", "reduce": "Reduce the wording"},
}
STEP_ORDER = {
    "scenario": ["import", "screen", "plan", "reduce", "report", "case", "explain", "register"],
    "paraphrase": ["paraphrase", "screen", "reduce", "report", "case", "register"],
    "audit": ["audit", "report", "case", "register"],
    "replay": ["replay"],
}
_CONTINUATION = re.compile(r"reduce([2-9])\Z")
_PROBE_STEP = re.compile(r"probe-(image|scene)-(\d+)\Z")
_REPLAY_STEP = re.compile(r"replay-(\d+)\Z")
# A drive letter not preceded by a letter (so ``s:/`` in ``https://`` is not one), then the rest of the path:
# folder names may hold spaces ("First Last"), so it runs to the end of the line, a quote or bracket, or a
# ``:``/``;``/``,`` followed by a space (the sentence continuing after the path).
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?:(?![:;,](?:\s|$))[^\"'`<>|()\[\]{}\r\n])*")
_POSIX_PATH = re.compile(r"(?<![\w.~:/-])/(?:[\w.@+-]+/)+[\w.@+-]*")


class ProcessInfo(NamedTuple):
    alive: bool
    created: Optional[float]             # when the process was created (epoch seconds), if the system says


Probe = Callable[[int], ProcessInfo]


# --------------------------------------------------------------------------------------
# Is that process alive?
# --------------------------------------------------------------------------------------


def _windows_probe(pid: int) -> ProcessInfo:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    handle = kernel32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        # Access denied still means the process exists; anything else (invalid parameter) means it does not.
        return ProcessInfo(ctypes.get_last_error() == 5, None)
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return ProcessInfo(False, None)
        if code.value != 259:                                  # STILL_ACTIVE
            return ProcessInfo(False, None)
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        ok = kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(kernel), ctypes.byref(user))
        if not ok:
            return ProcessInfo(True, None)
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime       # 100 ns since 1601-01-01
        return ProcessInfo(True, ticks / 10_000_000 - 11_644_473_600)
    finally:
        kernel32.CloseHandle(handle)


def _linux_created(pid: int) -> Optional[float]:
    """Creation time from ``/proc`` (Linux); ``None`` elsewhere or when it cannot be read."""

    try:
        stat = Path("/proc/{}/stat".format(pid)).read_text(encoding="utf-8")
        ticks = int(stat.rsplit(")", 1)[1].split()[19])        # field 22, starttime, counted after the comm field
        boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
                    if line.startswith("btime "))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None


def _posix_probe(pid: int) -> ProcessInfo:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ProcessInfo(False, None)
    except PermissionError:
        return ProcessInfo(True, None)
    except OSError:
        return ProcessInfo(False, None)
    return ProcessInfo(True, _linux_created(pid))


def default_probe(pid: int) -> ProcessInfo:
    """Ask the operating system about ``pid`` (Windows: ``OpenProcess`` and ``GetExitCodeProcess``)."""

    if type(pid) is not int or pid <= 0:
        return ProcessInfo(False, None)
    try:
        return _windows_probe(pid) if sys.platform == "win32" else _posix_probe(pid)
    except (OSError, ValueError, AttributeError):
        return ProcessInfo(False, None)


def parse_stamp(text: Any) -> Optional[float]:
    """An ISO 8601 UTC stamp (``2026-10-17T01:02:03.456Z``) as epoch seconds; ``None`` if it is not one."""

    if not isinstance(text, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.timestamp()


def process_alive(record: Any, probe: Probe = default_probe) -> bool:
    """Whether the process a ``process.json`` record names is still the live process that wrote it."""

    if not isinstance(record, Mapping) or type(record.get("pid")) is not int or record["pid"] <= 0:
        return False
    started = parse_stamp(record.get("started_at"))
    if started is None:
        return False
    info = probe(record["pid"])
    if not info.alive:
        return False
    return info.created is None or info.created <= started + CREATED_TOLERANCE_SECONDS


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_run_header(run_dir: Path) -> Dict[str, Any]:
    """The ``run`` header of ``steps.json`` (status, reason, ``no_llm``...); empty when it cannot be read."""

    data = _read_json(Path(run_dir) / "steps.json")
    header = data.get("run") if isinstance(data, Mapping) else None
    return dict(header) if isinstance(header, Mapping) else {}


def recorded_process(run_dir: Path, probe: Probe = default_probe) -> Optional[Dict[str, Any]]:
    """The ``process.json`` record of ``run_dir`` when its process is alive, else ``None``."""

    record = _read_json(Path(run_dir) / PROCESS_FILE)
    return dict(record) if process_alive(record, probe) else None


# --------------------------------------------------------------------------------------
# Run folders
# --------------------------------------------------------------------------------------


def run_folder(runs_root: Path, run: str) -> Path:
    """The folder of run ``run``: a bare folder name under the runs root, never a path."""

    if not isinstance(run, str) or RUN_NAME.match(run) is None or ".." in run:
        raise ValueError("not a run name")
    folder = Path(runs_root) / run
    if not (folder / "steps.json").is_file():
        raise FileNotFoundError(run)
    return folder


def _run_dirs(runs_root: Path) -> List[Path]:
    root = Path(runs_root)
    try:
        return sorted(p for p in root.iterdir() if (p / PROCESS_FILE).is_file())
    except OSError:
        return []


def live_runs(runs_root: Path, probe: Probe = default_probe) -> List[Path]:
    """The run folders under ``runs_root`` whose recorded process is alive (cheap: only ``process.json`` is read)."""

    return [folder for folder in _run_dirs(runs_root) if recorded_process(folder, probe) is not None]


def _money(value: Any) -> Optional[float]:
    return float(value) if type(value) in (int, float) else None


def spec_raw(run_dir: Path) -> Mapping[str, Any]:
    try:
        import yaml

        data = yaml.safe_load((run_dir / "spec.yaml").read_text(encoding="utf-8"))
    except Exception:                    # noqa: BLE001 - a spec that cannot be read only costs the cap fallbacks
        return {}
    return data if isinstance(data, Mapping) else {}


def _ledger(run_dir: Path) -> Dict[str, Any]:
    """Spend and time from ``ledger.json``; the spec's budget when the ledger has not been written yet."""

    data = _read_json(run_dir / "ledger.json")
    if isinstance(data, Mapping) and _money(data.get("cap_usd")) is not None:
        return dict(data)
    budget = spec_raw(run_dir).get("budget")
    budget = budget if isinstance(budget, Mapping) else {}
    return {"cap_usd": _money(budget.get("max_spend_usd")) or 0.0, "max_hours": _money(budget.get("max_hours")) or 0.0,
            "spent_usd": 0.0, "reserved_usd": 0.0, "elapsed_seconds": 0.0}


def _diagnose_keys(steps: Mapping[str, Any], spec: Mapping[str, Any], route: Optional[str]) -> List[str]:
    """The steps a diagnosis shows: the check first, then the branch the run took (known once the check is read)."""

    keys = ["import", "screen"] if (isinstance(spec.get("diagnose"), Mapping) and "import" in spec["diagnose"]) \
        else ["screen"]
    if route == "layout":
        later = sorted((k for k in steps if _CONTINUATION.match(k)), key=lambda k: int(k[6:]))
        keys += ["plan", "reduce"] + later + ["report", "case", "explain", "register"]
    elif route in ("probes", "flaky"):
        keys += sorted(k for k in steps if _PROBE_STEP.match(k))
        keys += [k for k in ("paraphrase", "rewording-screen", "rewording-reduce") if k in steps]
        keys += ["case-audit", "case-wording"] if "case-wording" in steps or "rewording-screen" in steps \
            else ["case-audit"]
        keys += ["register"]
    elif route == "passes":
        keys += ["report"]
    return keys


def _step_keys(mode: str, steps: Mapping[str, Any], spec: Mapping[str, Any],
               route: Optional[str] = None) -> List[str]:
    if mode == "diagnose":
        return _diagnose_keys(steps, spec, route)
    if mode == "replay":
        extra = sorted((k for k in steps if _REPLAY_STEP.match(k)), key=lambda k: int(k[7:]))
        return ["replay"] + extra
    keys = list(STEP_ORDER.get(mode, []))
    scenario = spec.get("scenario")
    if mode == "scenario" and "import" not in steps and not (isinstance(scenario, Mapping) and "import" in scenario):
        keys.remove("import")
    if mode == "scenario":
        later = sorted((k for k in steps if _CONTINUATION.match(k)), key=lambda k: int(k[6:]))
        keys[keys.index("reduce") + 1:keys.index("reduce") + 1] = later
    return keys


def _step_label(key: str, mode: str = "") -> str:
    if _CONTINUATION.match(key):
        return "Continue the reduction ({})".format(key[6:])
    probe = _PROBE_STEP.match(key)
    if probe:
        return "Stress test: {} disturbances ({})".format(probe.group(1), probe.group(2))
    again = _REPLAY_STEP.match(key)
    if again:
        return "Replay the case ({})".format(again.group(1))
    return MODE_STEP_LABELS.get(mode, {}).get(key) or STEP_LABELS.get(key, key.capitalize())


def _check_label(spec: Mapping[str, Any]) -> Optional[str]:
    """A diagnosis of one start checks it untouched; only a range search screens starts."""

    diagnose = spec.get("diagnose") if isinstance(spec.get("diagnose"), Mapping) else {}
    if "import" in diagnose:
        return "Check the imported start"
    if "start" in diagnose:
        return "Check the start untouched"
    return None


def step_rows(mode: str, steps: Mapping[str, Any], spec: Mapping[str, Any], finished: Optional[str],
              route: Optional[str] = None) -> List[Dict]:
    """The step timeline: the planned steps in order, with what each has done so far.

    A planned step the run never recorded is ``pending`` while the run can still reach it, ``skipped`` once the
    run completed without it (for example no explanation under ``--no-llm``) and ``pending`` after a stop."""

    rows = []
    for key in _step_keys(mode, steps, spec, route):
        record = steps.get(key) if isinstance(steps.get(key), Mapping) else None
        attempts = [a for a in (record or {}).get("attempts", []) if isinstance(a, Mapping)]
        status = (record or {}).get("status") or ("skipped" if finished == "completed" else "pending")
        label = (_check_label(spec) if mode == "diagnose" and key == "screen" else None) or _step_label(key, mode)
        rows.append({"key": key, "label": label, "status": status,
                     "state": (record or {}).get("state") if isinstance((record or {}).get("state"), str) else None,
                     "attempts": len(attempts),
                     "capacity_waits": sum(1 for a in attempts if a.get("state") == "capacity")})
    return rows


def _current_step(rows: List[Dict]) -> Optional[Dict]:
    return next((row for row in rows if row["status"] not in ("done", "skipped")), None)


def _job(run_dir: Path, rows: List[Dict], steps: Mapping[str, Any], active: bool) -> Optional[Dict[str, Any]]:
    """The newest Job of the run and where it is: derived from the last attempt's state, never the cloud."""

    if not active:
        return None
    for row in reversed(rows):
        attempts = [a for a in (steps.get(row["key"]) or {}).get("attempts", []) if isinstance(a, Mapping)]
        if not attempts:
            continue
        last = attempts[-1]
        name, state = last.get("job_name"), last.get("state")
        if not isinstance(name, str):
            return None
        if state == "submitting":
            phase = "submitting"
        elif state == "capacity":
            phase = "waiting_for_gpu"           # no GPU came: the run pauses, then submits again
        elif state in ("submitted", "unconfirmed"):
            phase = "downloading" if (run_dir / "jobs" / name / "result.json").is_file() else "running"
        else:
            phase = "settled"
        return {"name": name, "phase": phase}
    return None


def scrub_text(text: str) -> str:
    """Text safe to show: resource ids shortened (``backends.redact``) and absolute paths replaced."""

    from robot_debug.backends import redact

    return _POSIX_PATH.sub("[local path omitted]", _WINDOWS_PATH.sub("[local path omitted]", redact(text)))


def _scrub(line: str) -> str:
    """One log line safe to show: ids and paths removed, long lines cut."""

    return scrub_text(line)[:LOG_LINE_LIMIT]


def _log_path(run_dir: Path) -> Optional[Path]:
    launch = _read_json(run_dir / LAUNCH_FILE)
    if isinstance(launch, Mapping) and isinstance(launch.get("log"), str):
        return Path(launch["log"])
    fallback = run_dir / "run.log"
    return fallback if fallback.is_file() else None


def log_tail(run_dir: Path, lines: int = LOG_TAIL_LINES) -> List[str]:
    path = _log_path(Path(run_dir))
    if path is None:
        return []
    try:
        with path.open("rb") as stream:                                   # only the end of a possibly long log
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 65536))
            text = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [_scrub(line.rstrip()) for line in text.splitlines()[-lines:]]


# --------------------------------------------------------------------------------------
# The read models
# --------------------------------------------------------------------------------------


def _status(active: bool, stopping: bool, run: Mapping[str, Any]) -> str:
    if active:
        return "stopping" if stopping else "running"
    recorded = run.get("status")
    return recorded if recorded in ("completed", "stopped", "failed", "interrupted") else "interrupted"


def run_progress(runs_root: Path, run: str, probe: Probe = default_probe,
                 now: Callable[[], float] = time.time) -> Dict[str, Any]:
    """``Progress`` for one run folder (the API contract's shape). Raises ``ValueError`` for a name that is
    not a bare folder name and ``FileNotFoundError`` for a run that does not exist."""

    folder = run_folder(runs_root, run)
    data = _read_json(folder / "steps.json")
    if not isinstance(data, Mapping) or not isinstance(data.get("steps"), Mapping):
        raise FileNotFoundError(run)
    steps, header = data["steps"], data.get("run") if isinstance(data.get("run"), Mapping) else {}
    mode = data.get("mode") if isinstance(data.get("mode"), str) else "scenario"
    active = recorded_process(folder, probe) is not None
    stopping = active and (folder / STOP_REQUEST_FILE).is_file()
    # The CLI removes process.json when it exits normally; one left behind by a dead process means the run was
    # cut off (its header may still say what the segment before it ended with), so it reads as interrupted.
    orphaned = not active and (folder / PROCESS_FILE).is_file()
    if orphaned:
        header = dict(header, status="interrupted", reason="process_ended", detail=None)
    # "No failure repeated" is the diagnosis's answer, not a problem: the run is finished, there is nothing to resume,
    # and its result is in the library (as a run without a case when nothing was registered).
    negative = (not active and header.get("status") == "stopped" and isinstance(header.get("reason"), str)
                and header["reason"] in NOT_ATTENTION)
    if negative:
        header = dict(header, status="completed")
    status = _status(active, stopping, header)
    spec = spec_raw(folder)
    route = header.get("route") if header.get("route") in ROUTES else None
    rows = step_rows(mode, steps, spec, header.get("status") if not active else None, route)
    current = _current_step(rows) if active else None
    ledger = _ledger(folder)
    elapsed = _money(ledger.get("elapsed_seconds")) or 0.0
    if active:                          # the ledger only rewrites its clock when money moves; add the time since
        try:
            elapsed += max(0.0, now() - (folder / "ledger.json").stat().st_mtime)
        except OSError:
            pass
    # A resumed run still carries the status of the segment before it; while a process runs there is no stop.
    reason = header.get("reason") if not active and isinstance(header.get("reason"), str) else None
    registered = (steps.get("register") or {}).get("case_id") if isinstance(steps.get("register"), Mapping) else None
    job = _job(folder, rows, steps, active)
    attention = bool(job and job["phase"] == "waiting_for_gpu") if active else (status in ("stopped", "failed", "interrupted") and
                                        (needs_attention(reason) or reason is None))
    progress = {
        "run": folder.name, "name": data.get("name") if isinstance(data.get("name"), str) else folder.name,
        "mode": mode, "status": status, "step": current["label"] if current else None,
        "spent_usd": _money(ledger.get("spent_usd")) or 0.0, "cap_usd": _money(ledger.get("cap_usd")) or 0.0,
        "attention": attention,
        "stop_reason": reason, "stop_text": stop_text(reason, None if active else header.get("detail")),
        "steps": rows, "job": job,
        "reserved_usd": _money(ledger.get("reserved_usd")) or 0.0, "elapsed_seconds": round(elapsed, 1),
        "max_hours": _money(ledger.get("max_hours")) or 0.0, "log_tail": log_tail(folder),
        "route": route,
        "library_id": ("d-" + registered if isinstance(registered, str) and registered
                       else "r-" + folder.name if (negative or route == "passes") and mode != "replay" else None),
        "resumable": (not active) and mode != "replay" and status in ("stopped", "failed", "interrupted"),
        "stoppable": active and not stopping,
    }
    return progress


def active_runs(runs_root: Path, probe: Probe = default_probe, now: Callable[[], float] = time.time) -> List[Dict]:
    """``RunSummary`` for every run whose process is alive, oldest folder name first."""

    found = []
    for folder in _run_dirs(runs_root):
        if recorded_process(folder, probe) is None:
            continue
        try:
            progress = run_progress(runs_root, folder.name, probe, now)
        except (ValueError, FileNotFoundError):
            continue
        found.append({key: progress[key] for key in (
            "run", "name", "mode", "status", "step", "spent_usd", "cap_usd", "attention")})
    return found
