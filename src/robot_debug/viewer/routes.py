"""The routes of API version 1, wired to the services behind them (ADR 0033).

Reads (library, progress, environment, templates) answer in local mode and, as files, in the static export.
Controls (validate, dry run, start, stop, resume, replay) are POSTs, so they only ever run behind the guard of
:class:`robot_debug.viewer.api.Api`. A start or replay needs the ``plan_hash`` of a dry run of the very same
spec: the plan the person confirmed is the plan that runs.
"""

from __future__ import annotations

import hmac
import re
from pathlib import Path

from robot_debug.viewer import processes
from robot_debug.viewer.api import Api, Request, TextResponse
from robot_debug.viewer.environment import Environment
from robot_debug.viewer.launcher import Launcher
from robot_debug.viewer.library import FILE_NAMES, Library
from robot_debug.viewer.security import ApiError
from robot_debug.viewer.specs import SpecService

LIBRARY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}\Z")
CONTENT_TYPES = {".md": "text/markdown; charset=utf-8", ".json": "application/json; charset=utf-8"}


def register_routes(api: Api, *, library: Library, runs_root: Path, specs: SpecService, launcher: Launcher,
                    environment: Environment) -> None:
    """Add every route of the control panel to ``api``."""

    def item_id(request: Request) -> str:
        found = request.params["id"]
        if LIBRARY_ID.match(found) is None:
            raise ApiError(404, "There is no such case.")
        return found

    # -- reads ------------------------------------------------------------------------------------------

    api.add_route("GET", r"/api/library", lambda request: (200, library.list()))

    def detail(request: Request):
        try:
            return 200, library.detail(item_id(request))
        except KeyError:
            raise ApiError(404, "There is no such case.") from None
        except (ValueError, OSError):            # e.g. the old case's evidence moved: not a crash, not a detail
            raise ApiError(503, "This case's evidence is temporarily unavailable.") from None

    api.add_route("GET", r"/api/library/(?P<id>[^/]+)", detail)

    def case_file(request: Request):
        name = request.params["name"]
        if name not in FILE_NAMES:
            raise ApiError(404, "There is no such file.")
        try:
            path = library.file_path(item_id(request), name)
        except (KeyError, ValueError, FileNotFoundError):
            raise ApiError(404, "There is no such file.") from None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise ApiError(404, "There is no such file.") from None
        return TextResponse(processes.scrub_text(text), CONTENT_TYPES.get(path.suffix, "text/plain; charset=utf-8"))

    api.add_route("GET", r"/api/library/(?P<id>[^/]+)/files/(?P<name>[^/]+)", case_file)

    api.add_route("GET", r"/api/runs/active", lambda request: (200, {"runs": launcher.active()}),
                  local_only=True)

    def progress(request: Request):
        try:
            return 200, processes.run_progress(runs_root, request.params["run"], launcher.probe)
        except (ValueError, FileNotFoundError):
            raise ApiError(404, "There is no such run.") from None

    api.add_route("GET", r"/api/runs/(?P<run>[^/]+)/progress", progress, local_only=True)
    api.add_route("GET", r"/api/environment", lambda request: (200, environment.check()), local_only=True)
    api.add_route("GET", r"/api/specs/template", lambda request: (200, specs.template(request.first("mode"))),
                  local_only=True)

    # -- controls -----------------------------------------------------------------------------------------

    api.add_route("POST", r"/api/specs/validate", lambda request: (200, specs.validate(request.body.get("yaml"))))
    api.add_route("POST", r"/api/specs/dry-run", lambda request: (
        200, specs.dry_run(request.body.get("yaml"), request.body.get("import_file"))))

    def verify_plan(request: Request) -> None:
        """The plan hash the person confirmed must be the hash of a fresh dry run of the same spec."""

        supplied = request.body.get("plan_hash")
        if not isinstance(supplied, str) or not supplied:
            raise ApiError(412, "Review the dry run first, then start it with the plan it showed.")
        fresh = specs.dry_run(request.body.get("yaml"), request.body.get("import_file"))["plan_hash"]
        if not hmac.compare_digest(supplied.encode("utf-8"), fresh.encode("utf-8")):
            raise ApiError(412, "The plan changed since you reviewed it. Run the dry run again.")

    def refuse_if_busy() -> None:
        if launcher.busy():
            raise ApiError(409, "Another run is active. Stop it or wait for it to finish before starting another.")

    def start_run(request: Request):
        prepared = specs.prepare(request.body.get("yaml"), request.body.get("import_file"))
        if prepared.spec.mode == "replay":
            raise ApiError(400, "A replay is started from its case; use a diagnosis spec here.")
        no_llm = request.body.get("no_llm")
        if no_llm is not None and not isinstance(no_llm, bool):
            raise ApiError(400, "no_llm must be true or false.")
        if no_llm and prepared.spec.mode == "paraphrase":
            raise ApiError(400, "Paraphrase mode needs Nemotron to write the rewordings; turn Nemotron on.")
        refuse_if_busy()
        verify_plan(request)
        directory, spec_path = specs.persist(prepared)
        run = launcher.start(spec_path, directory, no_llm=bool(no_llm))
        return 202, {"run": run, "library_id": None}

    api.add_route("POST", r"/api/runs", start_run)

    def stop_run(request: Request):
        return 202, launcher.stop(request.params["run"])

    api.add_route("POST", r"/api/runs/(?P<run>[^/]+)/stop", stop_run)

    def resume_run(request: Request):
        return 202, {"run": launcher.resume(request.params["run"])}

    api.add_route("POST", r"/api/runs/(?P<run>[^/]+)/resume", resume_run)

    def replay_case(request: Request):
        identifier = item_id(request)
        try:
            case = library.detail(identifier)
        except KeyError:
            raise ApiError(404, "There is no such case.") from None
        if not case["replayable"]:
            raise ApiError(409, "This case cannot be replayed: it has no saved replay inputs.")
        expect = request.body.get("expect")
        if expect is not None and expect not in ("reproduces", "fixed"):
            raise ApiError(400, "expect must be reproduces or fixed.")
        prepared = specs.prepare(request.body.get("yaml"), None)
        if prepared.spec.mode != "replay":
            raise ApiError(400, "A replay needs a replay spec (mode: replay).")
        if prepared.spec.suite is not None and prepared.spec.suite != case["suite"]:
            raise ApiError(400, "The spec's suite differs from the case's.",
                           [{"path": "policy.suite", "message": "must match the case's suite"}])
        refuse_if_busy()
        verify_plan(request)
        directory, spec_path = specs.persist(prepared)
        run = launcher.replay(library.diagnoses_root / case["case_id"], spec_path, directory, expect)
        return 202, {"run": run}

    api.add_route("POST", r"/api/library/(?P<id>[^/]+)/replay", replay_case)
