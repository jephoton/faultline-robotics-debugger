"""The ``faultline`` command (ADR 0031).

    faultline diagnose SPEC.yaml [--env-file .env] [--no-llm] [--dry-run] [--resume RUN_DIR] [--allow-parallel]
    faultline replay CASE_DIR --spec SPEC.yaml [--env-file .env] [--expect reproduces|fixed] [--allow-parallel]
    faultline image build [--tag TAG] [--push REGISTRY] | faultline image push REGISTRY
    faultline cases [--runs-root DIR]
    faultline stop RUN_DIR
    faultline export --out DIR [--case ID ...] [--artifacts DIR] [--runs-root DIR] [--force]
    faultline ui [--artifacts DIR] [--runs-root DIR] [--port N] [--host ADDR] [--open]

A spec's ``mode`` picks the diagnosis: ``scenario`` (mode 1), ``audit`` (mode 2) or ``paraphrase`` (Nemotron
rewords the task instruction, one Job screens the rewordings, a second reduces the failing wording to its
minimal word edits; needs the Token Factory key, so it cannot run with ``--no-llm``).

One paid run at a time: diagnose and replay (not --dry-run) refuse to start while another run under the same
runs root has a live process; --allow-parallel overrides that.

Exit codes: 0 completed, 2 invalid spec or usage, 3 stopped (no failure found, a cap
was reached, a Job failed; the run folder holds what was produced), 5 ``replay --expect``
only: the verdict is not the expected one or is inconclusive (a CI gate), 1 unexpected
error, 130 interrupted (the in-flight Job is cancelled and the message says whether the
cancel was acknowledged; ``--resume`` continues).

Nothing here reads or prints a credential: the Token Factory key is read by the
planning and explanation code from the environment or ``--env-file``, and the cloud
credentials stay in the Nebius CLI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from robot_debug import ledger as lg
from robot_debug import orchestrator as orch
from robot_debug import spec as sp

DEFAULT_RUNS_ROOT = Path("artifacts") / "runs"
EXIT_UNEXPECTED_VERDICT = 5
PROCESS_FILE = "process.json"          # {"pid", "started_at", "command"} while a diagnose/replay is running
# ``faultline replay --expect``: the word the user gives -> the replay verdict that meets it.
EXPECTATIONS = {"reproduces": "still_reproduces", "fixed": "no_longer_reproduces"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:           # argparse would exit(2) and print usage to stderr
        raise sp.SpecError("usage: " + message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="faultline", description="Find, confirm, minimise and replay robot-policy failures.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    diagnose = commands.add_parser("diagnose", help="run a whole diagnosis (scenario, audit or paraphrase) from a spec file")
    diagnose.add_argument("spec", type=Path, nargs="?", help="the spec (optional with --resume)")
    diagnose.add_argument("--env-file", type=Path, help="dotenv file holding NEBIUS_API_KEY (Token Factory)")
    diagnose.add_argument("--no-llm", action="store_true", help="no Nemotron: fixed order, no explanation "
                          "(a resume keeps the setting its run started with; this flag turns it on)")
    diagnose.add_argument("--dry-run", action="store_true", help="print the planned Jobs and worst-case spend; create nothing")
    diagnose.add_argument("--resume", type=Path, metavar="RUN_DIR", help="continue an interrupted run folder")
    diagnose.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    diagnose.add_argument("--allow-parallel", action="store_true", help="start even if another run under the "
                          "runs root is alive (two paid runs at once; for experts)")
    diagnose.add_argument("--run-dir-file", type=Path, help=argparse.SUPPRESS)

    replay = commands.add_parser("replay", help="re-run a saved case and say whether the failure still reproduces")
    replay.add_argument("case", type=Path, help="a run folder (or case.json) holding a scenario case")
    replay.add_argument("--spec", type=Path, required=True)
    replay.add_argument("--env-file", type=Path, help="dotenv file (accepted for symmetry with diagnose; "
                        "a replay makes no Token Factory call)")
    replay.add_argument("--expect", choices=sorted(EXPECTATIONS), help="gate on the verdict: exit 0 when it "
                        "matches (reproduces: the failure still reproduces; fixed: it no longer does), "
                        "exit 5 otherwise or when the verdict is inconclusive")
    replay.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    replay.add_argument("--allow-parallel", action="store_true", help="start even if another run under the "
                        "runs root is alive (two paid runs at once; for experts)")
    replay.add_argument("--run-dir-file", type=Path, help=argparse.SUPPRESS)

    image = commands.add_parser("image", help="build or push the simulator image")
    kinds = image.add_subparsers(dest="image_command", required=True, parser_class=_Parser)
    build = kinds.add_parser("build")
    build.add_argument("--tag", default="faultline-serverless:local")
    build.add_argument("--push", metavar="REGISTRY", help="push to this registry after building")
    push = kinds.add_parser("push")
    push.add_argument("registry")

    cases = commands.add_parser("cases", help="list finished runs and their cases")
    cases.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)

    commands.add_parser("ui", add_help=False,           # handled in main() before parsing; listed here for --help
                        help="open the control panel in a browser (cases, new diagnoses, run progress)")

    export = commands.add_parser("export", help="write the cases as a static gallery (a folder any web host can serve)")
    export.add_argument("--out", type=Path, required=True, help="the folder to write (empty, or --force)")
    export.add_argument("--case", action="append", default=[], metavar="ID",
                        help="export only this case (library id, case id or a long prefix); repeatable")
    export.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    export.add_argument("--runs-root", type=Path, help="the run folders (default: <artifacts>/runs)")
    export.add_argument("--force", action="store_true", help="replace a previous export in a non-empty folder")
    export.add_argument("--app-root", type=Path, help=argparse.SUPPRESS)

    stop = commands.add_parser("stop", help="stop a running diagnosis safely (the Job is cancelled; --resume continues)")
    stop.add_argument("run_dir", type=Path, help="the run folder (or its name under --runs-root)")
    stop.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    return parser


# --------------------------------------------------------------------------------------


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(str(temporary), str(path))


def _record_process(run_dir: Path, command: str, started: dt.datetime) -> None:
    """``process.json``: which process is running this folder, so the control panel (and ``faultline stop``)
    can tell a live run from a finished or crashed one. Removed again by :func:`_clear_process`."""

    stamp = started.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    record = {"pid": os.getpid(), "started_at": stamp, "command": command}
    _write_atomic(Path(run_dir) / PROCESS_FILE, json.dumps(record, sort_keys=True) + "\n")


def _clear_process(run_dir: Path) -> None:
    """Delete our own ``process.json`` (never one that names another process)."""

    path = Path(run_dir) / PROCESS_FILE
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError, AttributeError):
        pass


def _lazy_backend_factory() -> Callable[[sp.Spec], Any]:
    from robot_debug.backends import make_backend

    # The backends read the spec's raw YAML mapping (``backend:`` section), not the parsed Spec.
    return lambda spec: make_backend(spec.raw if isinstance(spec, sp.Spec) else spec)


def _lazy_image_module() -> Any:
    from robot_debug import image_cmd

    return image_cmd


def list_runs(root: Path) -> List[str]:
    """One line per run folder under ``root``: name, status, case id, spend."""

    rows = []
    base = Path(root)
    if not base.is_dir():
        return rows
    for run_dir in sorted(p for p in base.iterdir() if (p / "steps.json").is_file()):
        try:
            steps = json.loads((run_dir / "steps.json").read_text(encoding="utf-8"))
            ledger = json.loads((run_dir / "ledger.json").read_text(encoding="utf-8")) \
                if (run_dir / "ledger.json").is_file() else {}
        except (OSError, ValueError):
            rows.append("{}  unreadable".format(run_dir.name))
            continue
        run = steps.get("run", {})
        case_id = steps.get("steps", {}).get("case", {}).get("case_id")
        rows.append("{}  {}  {}  case {}  spent US${:.2f}".format(
            run_dir.name, steps.get("mode", "?"),
            run.get("status", "unfinished") + (":" + run["reason"] if run.get("reason") else ""),
            case_id[:12] if case_id else "-", float(ledger.get("spent_usd", 0.0))))
    return rows


def _final_lines(result: orch.RunResult, resumable: bool = True) -> List[str]:
    lines = ["{}{}".format(result.status.capitalize(), "" if result.reason is None else " ({})".format(result.reason)),
             "Run folder: {}".format(result.run_dir), "Spent: US${:.2f}".format(result.spent_usd)]
    if result.reason == orch.STOPPED_BY_USER and resumable:
        lines.append("Resume with: faultline diagnose --resume {}".format(result.run_dir))
    if result.case_id:
        lines.append("Case: {}".format(result.case_id[:12]))
    if result.verdict is not None or result.reproduces is not None:
        lines.append(orch.replay_text(result.verdict))
    lines += ["Note: " + note for note in result.notes]
    return lines


def main(argv: Optional[Sequence[str]] = None, *, make_backend: Optional[Callable[[sp.Spec], Any]] = None,
         tools: Any = None, image_module: Any = None, out: Callable[[str], None] = print,
         poll_seconds: float = 60.0, pause_seconds: float = orch.CAPACITY_PAUSE_SECONDS) -> int:
    run_dir: Optional[Path] = None
    runner: Optional[orch.Orchestrator] = None
    recorded: Optional[Path] = None
    started = _utc_now()
    try:
        words = list(sys.argv[1:] if argv is None else argv)
        if words[:1] == ["ui"]:                       # the viewer has its own options (and --help)
            from robot_debug.viewer.server import main as viewer_main

            return viewer_main(words[1:], out=out)
        args = _parser().parse_args(argv)
        if args.command == "cases":
            for line in list_runs(args.runs_root) or ["no runs under {}".format(args.runs_root)]:
                out(line)
            return 0
        if args.command == "image":
            return _image(args, image_module, out)
        if args.command == "stop":
            return _stop(args, out)
        if args.command == "export":
            return _export(args, out)
        tools = tools or orch.DefaultTools()
        if args.command == "diagnose":
            spec, spec_text, run_dir = _diagnose_inputs(args)
            if spec.mode == "replay":
                raise sp.SpecError("mode: a replay spec is used with `faultline replay`")
            if run_dir is not None and not args.no_llm and _recorded_no_llm(run_dir):
                args.no_llm = True                   # a resume keeps what the run started with
        else:
            spec, spec_text = _load_with_text(args.spec)
        if args.command == "diagnose":
            _precheck(spec, tools, run_dir)
        factory = make_backend
        if args.command == "diagnose" and args.dry_run:
            return _dry_run(spec, tools, factory, out)
        _refuse_if_parallel(args, run_dir)
        factory = factory or _lazy_backend_factory()
        if run_dir is None:
            run_dir = orch.create_run_dir(args.runs_root, spec, spec_text, tools.now())
        elif args.command == "diagnose" and args.resume is not None:
            orch.clear_stop_request(run_dir)         # a stop belongs to the process it stopped, not to the next one
        _record_process(run_dir, args.command, started)
        recorded = run_dir
        launch_file = getattr(args, "run_dir_file", None)
        if launch_file is not None:                  # hidden: the control panel learns the folder from this
            _write_atomic(Path(launch_file), str(Path(run_dir).resolve()))
        ledger = lg.Ledger.load(run_dir / "ledger.json", cap_usd=spec.budget.max_spend_usd,
                                max_hours=spec.budget.max_hours, hourly_usd=spec.backend.hourly_usd)
        backend = factory(spec)
        runner = orch.Orchestrator(spec, run_dir, backend, tools, ledger,
                                   env_file=getattr(args, "env_file", None),
                                   no_llm=getattr(args, "no_llm", False), out=out,
                                   poll_seconds=poll_seconds, pause_seconds=pause_seconds)
        out("Run folder: {}".format(run_dir))
        result = runner.diagnose() if args.command == "diagnose" else runner.replay(args.case)
        for line in _final_lines(result, resumable=spec.mode != "replay"):
            out(line)
        expect = getattr(args, "expect", None)
        if expect is None:
            return result.exit_code
        return _expectation_code(result, expect, out)
    except sp.SpecError as error:
        out("error: {}".format(error))
        return 2
    except KeyboardInterrupt:
        out("Interrupted: " + (runner.interrupt_report() if runner is not None else "nothing had been started."))
        if run_dir is not None:
            out("Continue with: faultline diagnose --resume {}".format(run_dir))
        return 130
    except orch.StopRun as stop:
        out("error: {}".format(stop))
        return 3
    except Exception as error:                       # noqa: BLE001 - one clean line, never a traceback with context
        out("error: {}: {}".format(type(error).__name__, error))
        if run_dir is not None:
            out("Run folder: {}".format(run_dir))
        return 1
    finally:
        if recorded is not None:
            _clear_process(recorded)


def _expectation_code(result: orch.RunResult, expect: str, out: Callable[[str], None]) -> int:
    """The exit code of ``replay --expect``: 0 when the verdict is the expected one, 5 when it is another
    one or inconclusive (including a replay that stopped after some of its Jobs), and the run's own code (3)
    when the replay was refused or stopped before any Job produced evidence."""

    wanted = EXPECTATIONS[expect]
    if result.status == "completed" and result.verdict == wanted:
        out("Expected '{}': met.".format(expect))
        return 0
    if result.status == "completed" or result.reason == "replay_inconclusive":
        out("Expected '{}': NOT met ({}).".format(expect, orch.replay_text(result.verdict).rstrip(".")))
        return EXIT_UNEXPECTED_VERDICT
    if result.verdict == "incomplete":              # stopped after some Jobs: partial evidence, no verdict
        out("Expected '{}': NOT met (inconclusive: the replay stopped ({}) before every Job finished, so nothing "
            "can be said about the policy).".format(expect, result.reason))
        return EXIT_UNEXPECTED_VERDICT
    return result.exit_code


def _precheck(spec: sp.Spec, tools: Any, run_dir: Optional[Path] = None) -> None:
    """What can be refused before anything exists: a candidate budget no reduce Job can hold, and an
    imported start file that is invalid or for another suite or task. Both are spec errors (exit 2)."""

    try:
        orch.check_candidate_budget(spec, tools)
        orch.check_import(spec, tools, run_dir)
    except orch.StopRun as stop:
        raise sp.SpecError(stop.detail) from None


def _load_with_text(path: Optional[Path]):
    if path is None:
        raise sp.SpecError("usage: a spec file is required")
    spec = sp.load_spec(path)
    return spec, Path(path).read_text(encoding="utf-8")


def _diagnose_inputs(args: argparse.Namespace):
    if args.resume is None:
        if args.spec is None:
            raise sp.SpecError("usage: give a spec file or --resume RUN_DIR")
        spec, text = _load_with_text(args.spec)
        return spec, text, None
    run_dir = Path(args.resume)
    saved = run_dir / "spec.yaml"
    if not saved.is_file() or not (run_dir / "steps.json").is_file():
        raise sp.SpecError("usage: {} is not a faultline run folder".format(run_dir))
    from robot_debug.viewer import processes

    running = processes.recorded_process(run_dir)
    if running is not None and running.get("pid") != os.getpid():
        raise sp.SpecError("usage: {} is already running; stop it first (faultline stop)".format(run_dir.name))
    spec, text = _load_with_text(saved)
    if args.spec is not None and sp.load_spec(args.spec).raw != spec.raw:
        raise sp.SpecError("spec: the given spec differs from the one this run started with")
    return spec, text, run_dir


def _refuse_if_parallel(args: argparse.Namespace, run_dir: Optional[Path]) -> None:
    """One paid run at a time, as in the control panel: refuse to start beside a run whose process is alive
    under the same runs root (a resumed run uses its own folder's parent), unless ``--allow-parallel``."""

    if getattr(args, "allow_parallel", False):
        return
    from robot_debug.viewer import processes

    root = Path(run_dir).parent if run_dir is not None else Path(args.runs_root)
    others = [folder for folder in processes.live_runs(root)
              if (run_dir is None or folder.resolve() != Path(run_dir).resolve())
              and (processes.recorded_process(folder) or {}).get("pid") != os.getpid()]
    if others:
        raise sp.SpecError("usage: another run is active ({}); stop it (faultline stop) or wait for it to finish. "
                           "Pass --allow-parallel to start a second paid run anyway.".format(
                               ", ".join(folder.name for folder in others[:3])))


def _recorded_no_llm(run_dir: Path) -> bool:
    """Whether the run folder's header says it was started with ``--no-llm`` (older folders say nothing)."""

    try:
        header = json.loads((Path(run_dir) / "steps.json").read_text(encoding="utf-8")).get("run")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(header, dict) and header.get("no_llm") is True


def _dry_run(spec: sp.Spec, tools: Any, factory: Optional[Callable[[sp.Spec], Any]], out: Callable[[str], None]) -> int:
    lines, _required = orch.dry_run_lines(spec, tools)
    for line in lines:                               # the plan first: it needs no backend and no cloud
        out(line)
    try:
        factory = factory or _lazy_backend_factory()
        factory(spec)                                # constructing validates the backend section; nothing is called
    except ImportError:
        out("Backend not checked (the backends package is not installed). Dry run: nothing was created.")
        return 0
    except Exception as error:                       # noqa: BLE001 - BackendError and friends: report, never a traceback
        out("Backend check failed: {}".format(error))
        out("Fix the backend: section before running; nothing was created or submitted.")
        return 2
    out("Backend '{}' accepted the spec. Dry run: nothing was created or submitted.".format(spec.backend.kind))
    return 0


def _stop(args: argparse.Namespace, out: Callable[[str], None]) -> int:
    """``faultline stop RUN_DIR``: ask the process running that folder to stop. The request is only a file;
    the run cancels its current Job, settles the ledger and exits, and ``--resume`` continues it."""

    run_dir = Path(args.run_dir)
    if not (run_dir / "steps.json").is_file():
        named = Path(args.runs_root) / args.run_dir
        if not (named / "steps.json").is_file():
            raise sp.SpecError("usage: {} is not a faultline run folder".format(run_dir))
        run_dir = named
    from robot_debug.viewer import processes

    if processes.recorded_process(run_dir) is None:
        raise sp.SpecError("usage: {} has no running process; there is nothing to stop".format(run_dir.name))
    orch.request_stop(run_dir)
    out("Stop requested for {}.".format(run_dir))
    out("The current Job is cancelled and charged for the time it ran; the run then ends and can be continued "
        "with: faultline diagnose --resume {}".format(run_dir))
    return 0


def _export(args: argparse.Namespace, out: Callable[[str], None]) -> int:
    """``faultline export``: the public projection of the library as files; refusals exit 2."""

    from robot_debug.viewer import export as gallery

    try:
        summary = gallery.export_gallery(
            args.out, args.artifacts, runs_root=args.runs_root or Path(args.artifacts) / "runs",
            cases=args.case, force=args.force, app_root=args.app_root)
    except gallery.ExportError as error:
        out("error: {}".format(error))
        return 2
    out("Exported {} case(s) and {} video(s) to {}".format(summary["cases"], summary["videos"], args.out))
    if summary["skipped"]:
        out("{} case(s) could not be read and were left out.".format(summary["skipped"]))
    out("Serve it with any static host; vercel.json sends app routes to index.html. Publishing is a separate step.")
    return 0


def _image(args: argparse.Namespace, module: Any, out: Callable[[str], None]) -> int:
    module = module or _lazy_image_module()
    if args.image_command == "build":
        result = module.build(args.tag)
        if result is not None:
            out(str(result))
        if args.push:
            pushed = module.push(args.push)
            if pushed is not None:
                out(str(pushed))
    else:
        pushed = module.push(args.registry)
        if pushed is not None:
            out(str(pushed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
