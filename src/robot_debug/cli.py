"""The ``faultline`` command (ADR 0031).

    faultline diagnose SPEC.yaml [--env-file .env] [--no-llm] [--dry-run] [--resume RUN_DIR]
    faultline replay CASE_DIR --spec SPEC.yaml [--env-file .env]
    faultline image build [--tag TAG] [--push REGISTRY] | faultline image push REGISTRY
    faultline cases [--runs-root DIR]

Exit codes: 0 completed, 2 invalid spec or usage, 3 stopped (no failure found, a cap
was reached, a Job failed; the run folder holds what was produced), 1 unexpected
error, 130 interrupted (the in-flight Job is cancelled; ``--resume`` continues).

Nothing here reads or prints a credential: the Token Factory key is read by the
planning and explanation code from the environment or ``--env-file``, and the cloud
credentials stay in the Nebius CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from robot_debug import ledger as lg
from robot_debug import orchestrator as orch
from robot_debug import spec as sp

DEFAULT_RUNS_ROOT = Path("artifacts") / "runs"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:           # argparse would exit(2) and print usage to stderr
        raise sp.SpecError("usage: " + message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="faultline", description="Find, confirm, minimise and replay robot-policy failures.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    diagnose = commands.add_parser("diagnose", help="run a whole diagnosis from a spec file")
    diagnose.add_argument("spec", type=Path, nargs="?", help="the spec (optional with --resume)")
    diagnose.add_argument("--env-file", type=Path, help="dotenv file holding NEBIUS_API_KEY (Token Factory)")
    diagnose.add_argument("--no-llm", action="store_true", help="no Nemotron: fixed order, no explanation")
    diagnose.add_argument("--dry-run", action="store_true", help="print the planned Jobs and worst-case spend; create nothing")
    diagnose.add_argument("--resume", type=Path, metavar="RUN_DIR", help="continue an interrupted run folder")
    diagnose.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)

    replay = commands.add_parser("replay", help="re-run a saved case and say whether the failure still reproduces")
    replay.add_argument("case", type=Path, help="a run folder (or case.json) holding a scenario case")
    replay.add_argument("--spec", type=Path, required=True)
    replay.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)

    image = commands.add_parser("image", help="build or push the simulator image")
    kinds = image.add_subparsers(dest="image_command", required=True, parser_class=_Parser)
    build = kinds.add_parser("build")
    build.add_argument("--tag", default="faultline-serverless:local")
    build.add_argument("--push", metavar="REGISTRY", help="push to this registry after building")
    push = kinds.add_parser("push")
    push.add_argument("registry")

    cases = commands.add_parser("cases", help="list finished runs and their cases")
    cases.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    return parser


# --------------------------------------------------------------------------------------


def _lazy_backend_factory() -> Callable[[sp.Spec], Any]:
    from robot_debug.backends import make_backend

    return make_backend


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


def _final_lines(result: orch.RunResult) -> List[str]:
    lines = ["{}{}".format(result.status.capitalize(), "" if result.reason is None else " ({})".format(result.reason)),
             "Run folder: {}".format(result.run_dir), "Spent: US${:.2f}".format(result.spent_usd)]
    if result.case_id:
        lines.append("Case: {}".format(result.case_id[:12]))
    if result.reproduces is not None:
        lines.append("The failure {}.".format("still reproduces" if result.reproduces else "no longer reproduces"))
    lines += ["Note: " + note for note in result.notes]
    return lines


def main(argv: Optional[Sequence[str]] = None, *, make_backend: Optional[Callable[[sp.Spec], Any]] = None,
         tools: Any = None, image_module: Any = None, out: Callable[[str], None] = print,
         poll_seconds: float = 60.0, pause_seconds: float = orch.CAPACITY_PAUSE_SECONDS) -> int:
    run_dir: Optional[Path] = None
    try:
        args = _parser().parse_args(argv)
        if args.command == "cases":
            for line in list_runs(args.runs_root) or ["no runs under {}".format(args.runs_root)]:
                out(line)
            return 0
        if args.command == "image":
            return _image(args, image_module, out)
        tools = tools or orch.DefaultTools()
        if args.command == "diagnose":
            spec, spec_text, run_dir = _diagnose_inputs(args)
            if spec.mode == "replay":
                raise sp.SpecError("mode: a replay spec is used with `faultline replay`")
        else:
            spec, spec_text = _load_with_text(args.spec)
        factory = make_backend
        if args.command == "diagnose" and args.dry_run:
            return _dry_run(spec, tools, factory, out)
        factory = factory or _lazy_backend_factory()
        if run_dir is None:
            run_dir = orch.create_run_dir(args.runs_root, spec, spec_text, tools.now())
        ledger = lg.Ledger.load(run_dir / "ledger.json", cap_usd=spec.budget.max_spend_usd,
                                max_hours=spec.budget.max_hours, hourly_usd=spec.backend.hourly_usd)
        backend = factory(spec)
        runner = orch.Orchestrator(spec, run_dir, backend, tools, ledger,
                                   env_file=getattr(args, "env_file", None),
                                   no_llm=getattr(args, "no_llm", False), out=out,
                                   poll_seconds=poll_seconds, pause_seconds=pause_seconds)
        out("Run folder: {}".format(run_dir))
        result = runner.diagnose() if args.command == "diagnose" else runner.replay(args.case)
        for line in _final_lines(result):
            out(line)
        return result.exit_code
    except sp.SpecError as error:
        out("error: {}".format(error))
        return 2
    except KeyboardInterrupt:
        out("Interrupted: the in-flight Job was cancelled and cloud resources released.")
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
    spec, text = _load_with_text(saved)
    if args.spec is not None and sp.load_spec(args.spec).raw != spec.raw:
        raise sp.SpecError("spec: the given spec differs from the one this run started with")
    return spec, text, run_dir


def _dry_run(spec: sp.Spec, tools: Any, factory: Optional[Callable[[sp.Spec], Any]], out: Callable[[str], None]) -> int:
    lines, _required = orch.dry_run_lines(spec, tools)
    try:
        factory = factory or _lazy_backend_factory()
        factory(spec)                                # constructing validates the backend section; nothing is called
        lines.append("Backend '{}' accepted the spec. Dry run: nothing was created or submitted.".format(spec.backend.kind))
    except ImportError:
        lines.append("Backend not checked (the backends package is not installed). Dry run: nothing was created.")
    for line in lines:
        out(line)
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
