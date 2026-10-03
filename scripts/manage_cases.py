"""Manage existing M4 diagnostic evidence as offline case metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE) not in sys.path: sys.path.insert(0, str(SOURCE))

from robot_debug.case_io import SanitizedCaseValidationError, import_m4
from robot_debug.case_store import register_case, inspect_case, list_cases, export_case, reimport_case


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SanitizedCaseValidationError("invalid arguments")


def _parser():
    parser = Parser(description=__doc__, add_help=True)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("import-m4", "list", "inspect", "export", "reimport"):
        command = sub.add_parser(name)
        command.add_argument("--workspace", type=Path, default=Path("artifacts/cases"))
        if name in ("import-m4", "reimport"): command.add_argument("--source-root", required=True, type=Path)
        if name == "import-m4":
            command.add_argument("--summary", default="failure-reduction/session_summary.json")
            command.add_argument("--replay", default="failure-reduction/replay_case.json")
            command.add_argument("--profile")
        if name in ("inspect", "export"): command.add_argument("--case-id", required=True)
        if name == "export": command.add_argument("--output", required=True, type=Path)
        if name == "reimport": command.add_argument("--index", required=True, type=Path)
    return parser


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "import-m4":
            case = import_m4(args.source_root, args.summary, args.replay, args.profile)
            register_case(case, args.source_root, args.workspace)
            result = {"case_id": case["case_id"], "capabilities": case["capabilities"]}
        elif args.command == "list": result = list_cases(args.workspace)
        elif args.command == "inspect": result = inspect_case(args.workspace, args.case_id)
        elif args.command == "export":
            export_case(args.workspace, args.case_id, args.output)
            result = {"case_id": args.case_id, "exported": True}
        else:
            path = reimport_case(args.index, args.source_root, args.workspace)
            result = {"case_id": path.name, "imported": True}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except SanitizedCaseValidationError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        print(json.dumps({"error": "case operation failed"}))
        return 2


if __name__ == "__main__": sys.exit(main())
