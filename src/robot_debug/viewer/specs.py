"""Spec templates, validation and dry runs for the control panel (ADR 0033).

The UI never invents a second spec format: a spec is the same YAML ``faultline diagnose`` reads, checked by
``robot_debug.spec``. This module adds what a browser needs around it:

* ``template(mode)``: a starting spec from ``configs/specs/``. The user's own pinned image lives in an ignored
  local spec (``artifacts/specs-local``); a template never carries it into the page. Its ``backend.image`` reads
  ``local`` and the server fills in the real reference when the spec is checked or launched, so registry ids and
  digests never travel to the browser.
* ``validate``: the spec's errors as ``{path, message}`` pairs.
* ``dry_run``: the planned Jobs and their worst-case spend, built exactly as ``faultline diagnose --dry-run``
  builds them (no cloud call), and a ``plan_hash`` that ties a later start to what the person confirmed.
* ``persist``: the spec (and an imported start file) saved under ``artifacts/specs-ui/``, so every UI run can be
  repeated from a terminal.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from robot_debug import ledger as lg
from robot_debug import orchestrator as orch
from robot_debug import spec as sp
from robot_debug.viewer.security import ApiError
from robot_debug.workloads import WorkloadError


def _workload_message(detail: str) -> str:
    match = re.search(r"more than the (\d+) s cap", detail)
    if match:
        return ("needs a longer Job than the {}-minute limit allows; choose fewer families or rewordings, or split "
                "them across runs".format(int(match.group(1)) // 60))
    return detail

SPECS_UI = "specs-ui"
SPECS_LOCAL = "specs-local"
TEMPLATE_FILES = {
    "scenario-start": "scenario-start.yaml", "scenario-screen": "scenario-screen.yaml",
    "scenario-import": "scenario-import.yaml", "audit": "audit.yaml", "paraphrase": "paraphrase.yaml",
    "diagnose": "diagnose.yaml", "replay": "replay.yaml",
}
LOCAL_IMAGE = "local"                    # backend.image in a template: "the image pinned in my local spec"
ID_KEYS = ("project", "subnet", "registry", "image_digest")      # backend keys that can hold resource ids
MAX_YAML_BYTES = 64 * 1024
MAX_IMPORT_BYTES = 512 * 1024            # robot_debug.scenario_import.MAX_FILE_BYTES
_PLACEHOLDERS = ("REGISTRY_ID", "IMAGE_DIGEST")
_JOB_LINE = re.compile(r"^\s+(?P<step>\S+)\s+.*?\s+deadline\s+(?P<deadline>\d+) s\s+worst case US\$(?P<cost>\d+\.\d+)"
                       r"(?P<optional> \(optional\))?$")
_TOTAL_LINE = re.compile(r"^Worst case of the required Jobs: US\$(?P<total>\d+\.\d+)\.$")
_BRANCH_HEADER = re.compile(r"^(CHECK|LAYOUT|PROBES) \(")
_BRANCH_LINE = re.compile(r"^Branch (?P<branch>check|layout|probes): worst case US\$(?P<cost>\d+\.\d+), typical "
                          r"(?:unknown|about US\$(?P<typical>\d+\.\d+)(?: in about (?P<minutes>\d+) min)?)\.$")
_SLUG = re.compile(r"[^a-z0-9-]+")


class Prepared:
    """A spec ready to dry-run or launch: the parsed spec, its mapping and the import file it came with."""

    def __init__(self, spec: sp.Spec, mapping: Dict[str, Any], import_bytes: Optional[bytes],
                 import_name: Optional[str]) -> None:
        self.spec, self.mapping = spec, mapping
        self.import_bytes, self.import_name = import_bytes, import_name

    @property
    def import_sha256(self) -> Optional[str]:
        return None if self.import_bytes is None else hashlib.sha256(self.import_bytes).hexdigest()

    def canonical(self) -> str:
        """The spec as one stable text: keys sorted, the import path replaced by the file's hash."""

        import yaml

        data = copy.deepcopy(self.mapping)
        if self.import_bytes is not None:
            data[_import_section(self.spec)]["import"] = "sha256:" + str(self.import_sha256)
        return yaml.safe_dump(data, sort_keys=True, default_flow_style=False)


def _error_pairs(error: sp.SpecError) -> List[Dict[str, str]]:
    """``"budget.max_hours: must be ..."`` as ``{path, message}``; a message with no path keeps path ``""``."""

    text = str(error)
    path, separator, message = text.partition(": ")
    if separator and re.fullmatch(r"[A-Za-z0-9_.\[\]-]+", path):
        return [{"path": path, "message": message}]
    return [{"path": "", "message": text}]


def _fail(errors: List[Dict[str, str]], message: Optional[str] = None, status: int = 400) -> ApiError:
    return ApiError(status, message or (errors[0]["message"] if errors else "The spec is not valid."), errors)


class SpecService:
    """Templates, validation, dry runs and saved specs for one artifacts folder."""

    def __init__(self, artifact_root: Path, *, repo_root: Optional[Path] = None, tools: Any = None,
                 backend_check: Optional[Callable[[sp.Spec], Optional[str]]] = None,
                 clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc)) -> None:
        self.artifact_root = Path(artifact_root)
        self.repo_root = Path(repo_root) if repo_root else orch.REPOSITORY_ROOT
        self.tools = tools
        self.backend_check = backend_check
        self.clock = clock

    @property
    def specs_ui(self) -> Path:
        return self.artifact_root / SPECS_UI

    def _tools(self) -> Any:
        return self.tools or orch.DefaultTools()

    # -- the local backend block --------------------------------------------------------------------

    def local_backend(self) -> Optional[Dict[str, Any]]:
        """The ``backend:`` mapping of the newest local spec that pins a real image, or ``None``."""

        candidates: List[Path] = []
        for pattern in ((SPECS_LOCAL, "*.yaml"), (SPECS_UI, "*/spec.yaml")):
            candidates += list(self.artifact_root.glob("/".join(pattern)))
        found: List[Tuple[float, Dict[str, Any]]] = []
        for path in candidates:
            try:
                if path.stat().st_size > MAX_YAML_BYTES:
                    continue
                mapping = _load_mapping(path.read_text(encoding="utf-8"))
                backend = mapping.get("backend") if isinstance(mapping, Mapping) else None
                image = backend.get("image") if isinstance(backend, Mapping) else None
                if (isinstance(image, str) and image != LOCAL_IMAGE and not any(p in image for p in _PLACEHOLDERS)
                        and backend.get("kind") == "nebius" and backend.get("hf_token_secret")):
                    found.append((path.stat().st_mtime, dict(backend)))
            except (OSError, UnicodeError, sp.SpecError):
                continue
        return max(found, key=lambda item: item[0])[1] if found else None

    def resolve(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        """The mapping with ``backend.image: local`` replaced by the real reference (and its ids) from the local
        spec. Raises :class:`ApiError` when the sentinel is used and no local spec pins an image."""

        backend = mapping.get("backend")
        if not isinstance(backend, Mapping) or backend.get("image") != LOCAL_IMAGE:
            return mapping
        local = self.local_backend()
        if local is None:
            raise _fail([{"path": "backend.image", "message": 'is "local" but no spec in artifacts/specs-local pins '
                                                              "an image; write the full image reference"}])
        resolved = dict(backend)
        resolved["image"] = local["image"]
        for key in ID_KEYS + ("hf_token_secret", "region", "platform", "preset", "hourly_usd"):
            if key not in resolved and key in local:
                resolved[key] = local[key]
        return dict(mapping, backend=resolved)

    # -- templates ----------------------------------------------------------------------------------------

    def template(self, mode: Optional[str]) -> Dict[str, str]:
        if mode not in TEMPLATE_FILES:
            raise ApiError(400, "mode must be one of: {}.".format(", ".join(TEMPLATE_FILES)))
        path = self.repo_root / "configs" / "specs" / TEMPLATE_FILES[mode]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise ApiError(404, "The spec templates are not part of this installation.") from None
        local = self.local_backend()
        if local is not None:
            text = self._with_local_backend(text, local)
        return {"yaml": text}

    @staticmethod
    def _with_local_backend(text: str, local: Mapping[str, Any]) -> str:
        """The template with its ``backend:`` section (always last) carrying the local settings and, for the
        image and every id, the word ``local`` or nothing: the real values stay on the server."""

        import yaml

        head, marker, _tail = text.partition("\nbackend:")
        if not marker:
            return text
        block: Dict[str, Any] = {"kind": "nebius"}
        for key in ("project", "platform", "preset"):
            value = local.get(key)
            if value is not None and not (key == "project" and value != "from-cli-profile"):
                block[key] = value
        block["image"] = LOCAL_IMAGE
        for key in ("hf_token_secret", "region", "hourly_usd"):
            if key in local:
                block[key] = local[key]
        note = ("\n# backend.image: local means the image pinned in your own spec under artifacts/specs-local;\n"
                "# the server fills in the real reference when the spec is checked or started.\n")
        return head + "\n" + note + yaml.safe_dump({"backend": block}, sort_keys=False, default_flow_style=False)

    # -- validation ---------------------------------------------------------------------------------------------

    def _mapping(self, yaml_text: Any) -> Dict[str, Any]:
        if not isinstance(yaml_text, str) or not yaml_text.strip():
            raise _fail([{"path": "yaml", "message": "give the spec as YAML text"}], "The spec is empty.")
        if len(yaml_text.encode("utf-8")) > MAX_YAML_BYTES:
            raise _fail([{"path": "yaml", "message": "is larger than 64 KiB"}], "The spec is larger than 64 KiB.")
        try:
            mapping = _load_mapping(yaml_text)
        except sp.SpecError as error:
            raise _fail(_error_pairs(error)) from None
        if not isinstance(mapping, dict):
            raise _fail([{"path": "spec", "message": "must be a mapping"}])
        return mapping

    def validate(self, yaml_text: Any) -> Dict[str, Any]:
        """``{"ok", "errors", "summary"}``: never raises for a bad spec, only for a bad request."""

        try:
            spec = sp.parse_spec(self.resolve(self._mapping(yaml_text)))
        except ApiError as error:
            if error.status == 400 and error.errors:
                return {"ok": False, "errors": error.errors, "summary": None}
            raise
        except sp.SpecError as error:
            return {"ok": False, "errors": _error_pairs(error), "summary": None}
        return {"ok": True, "errors": [], "summary": _summary(spec)}

    # -- preparing, dry-running, saving --------------------------------------------------------------------

    def prepare(self, yaml_text: Any, import_file: Any = None) -> Prepared:
        mapping = self.resolve(self._mapping(yaml_text))
        try:
            spec = sp.parse_spec(mapping)
        except sp.SpecError as error:
            raise _fail(_error_pairs(error)) from None
        wants_import = _needs_import(spec)
        content: Optional[bytes] = None
        name: Optional[str] = None
        if import_file is not None:
            if not wants_import:
                raise _fail([{"path": "import_file", "message": "this spec does not import a start"}])
            if (not isinstance(import_file, Mapping) or not isinstance(import_file.get("content"), str)
                    or not isinstance(import_file.get("name", ""), str)):
                raise _fail([{"path": "import_file", "message": "must be {name, content} with the file's JSON text"}])
            content = import_file["content"].encode("utf-8")
            name = re.sub(r"[^A-Za-z0-9._-]", "_", import_file.get("name") or "start.json")[:100]
            if not content or len(content) > MAX_IMPORT_BYTES:
                raise _fail([{"path": "import_file", "message": "must be 1 byte to 512 KiB"}])
        elif wants_import:
            raise _fail([{"path": _import_section(spec) + ".import",
                          "message": "attach the start file (a scenario candidate JSON)"}])
        return Prepared(spec, copy.deepcopy(dict(mapping)), content, name)

    def _staged(self, prepared: Prepared) -> Tuple[sp.Spec, Optional[Path]]:
        """The spec with ``scenario.import`` pointing at a staging copy of the import file (removed by the caller)."""

        if prepared.import_bytes is None:
            return prepared.spec, None
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(self._ensure(self.specs_ui))))
        path = staging / "import.json"
        path.write_bytes(prepared.import_bytes)
        mapping = copy.deepcopy(prepared.mapping)
        mapping[_import_section(prepared.spec)]["import"] = str(path)
        return sp.parse_spec(mapping), staging

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def dry_run(self, yaml_text: Any, import_file: Any = None, case: Optional[Mapping[str, Any]] = None
                ) -> Dict[str, Any]:
        """The plan of a spec. ``case`` is the saved case a replay spec replays: its kind decides which Jobs
        the replay runs, so the plan (and its hash) is for that case; other modes ignore it."""

        prepared = self.prepare(yaml_text, import_file)
        spec, staging = self._staged(prepared)
        try:
            lines, required = self._plan_lines(spec, case)
        finally:
            if staging is not None:
                shutil.rmtree(str(staging), ignore_errors=True)
        jobs, total, branches = parse_plan_branches(lines, required)
        digest = hashlib.sha256()
        for part in (prepared.canonical(), prepared.import_sha256 or "", "\n".join(lines)):
            digest.update(part.encode("utf-8"))
            digest.update(b"\0")
        shown = list(lines)
        if self.backend_check is not None:
            note = self.backend_check(spec)
            if note:
                shown.append(note)
        return {"plan_hash": digest.hexdigest(), "jobs": jobs, "branches": branches, "worst_case_total_usd": total,
                "cap_usd": spec.budget.max_spend_usd, "max_hours": spec.budget.max_hours, "lines": shown}

    def _plan_lines(self, spec: sp.Spec, case: Optional[Mapping[str, Any]] = None) -> Tuple[List[str], float]:
        tools = self._tools()
        try:
            if spec.mode == "replay":
                return replay_plan_lines(spec, case, tools)
            orch.check_candidate_budget(spec, tools)
            orch.check_import(spec, tools)
            return orch.dry_run_lines(spec, tools)
        except orch.StopRun as stop:
            path = {"candidates_too_large": "budget.max_candidates", "import_invalid": _import_section(spec) + ".import",
                    "import_mismatch": _import_section(spec) + ".import"}.get(stop.reason, "")
            raise _fail([{"path": path, "message": stop.detail or str(stop)}]) from None
        except orch.OrchestratorError:
            raise ApiError(501, "Planning needs a source checkout of Faultline (the scripts folder).") from None
        except WorkloadError as error:
            # A plan the Job limits cannot hold (for example too many families for one audit Job) is the user's
            # to change, not a server fault: say what is too big instead of a generic error.
            path = {"audit": "audit.families", "paraphrase": "paraphrase.count",
                    "diagnose": "diagnose.probes"}.get(spec.mode, "")
            raise _fail([{"path": path, "message": _workload_message(str(error))}]) from None

    def new_directory(self, label: str) -> Path:
        """A fresh ``artifacts/specs-ui/<UTC stamp>-<label>/`` folder (never an existing one)."""

        stamp = self.clock().astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = "{}-{}".format(stamp, _SLUG.sub("-", label.lower()).strip("-") or "run")
        root = self._ensure(self.specs_ui)
        directory, counter = root / base, 1
        while True:
            try:
                directory.mkdir()
                return directory
            except FileExistsError:
                counter += 1
                directory = root / "{}-{}".format(base, counter)

    def persist(self, prepared: Prepared) -> Tuple[Path, Path]:
        """Save the spec (and import file) in ``artifacts/specs-ui/<UTC stamp>-<name>/``.

        Returns ``(directory, spec path)``. The saved spec names the saved import file, so the same command
        line reproduces the run from a terminal."""

        import yaml

        directory = self.new_directory(prepared.spec.name)
        mapping = copy.deepcopy(prepared.mapping)
        if prepared.import_bytes is not None:
            (directory / "import.json").write_bytes(prepared.import_bytes)
            mapping[_import_section(prepared.spec)]["import"] = str((directory / "import.json").resolve())
        spec_path = directory / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(mapping, sort_keys=False, default_flow_style=False),
                             encoding="utf-8", newline="\n")
        return directory, spec_path


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _load_mapping(text: str) -> Any:
    """The spec text as a mapping, with the strict loader of ``robot_debug.spec`` (duplicate keys refused)."""

    yaml, loader = sp._loader()
    try:
        return yaml.load(text, Loader=loader)
    except sp.SpecError:
        raise
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        raise sp.SpecError("spec: not valid YAML{}".format("" if mark is None else " (line {})".format(mark.line + 1))) from None


def _import_section(spec: sp.Spec) -> str:
    """The spec section that holds ``import:`` (``scenario`` or, in the diagnosis mode, ``diagnose``)."""

    return "diagnose" if spec.mode == "diagnose" else "scenario"


def _needs_import(spec: sp.Spec) -> bool:
    return spec.mode in ("scenario", "diagnose") and bool(spec.scenario.import_path)


def _summary(spec: sp.Spec) -> Dict[str, Any]:
    writes_wordings = spec.mode == "paraphrase" or (spec.mode == "diagnose" and spec.paraphrase is not None)
    return {"name": spec.name, "mode": spec.mode, "suite": spec.suite, "backend": spec.backend.kind,
            "cap_usd": spec.budget.max_spend_usd, "max_hours": spec.budget.max_hours,
            "needs_import": _needs_import(spec),
            "uses_nemotron": writes_wordings or spec.nemotron.hypothesis or spec.nemotron.explain}


def parse_plan(lines: List[str], required: float) -> Tuple[List[Dict[str, Any]], float]:
    """The structured Jobs behind ``orchestrator.dry_run_lines`` text: ``name``, ``deadline_seconds``,
    ``worst_case_usd``, ``optional`` (for the continuation Jobs that run only if needed) and ``branch``
    (``check``, ``layout`` or ``probes`` for a diagnosis; ``None`` for the other modes)."""

    jobs, total, _branches = parse_plan_branches(lines, required)
    return jobs, total


def parse_plan_branches(lines: List[str], required: float) -> Tuple[List[Dict[str, Any]], float, List[Dict[str, Any]]]:
    """:func:`parse_plan` plus the branch summaries of a diagnosis: ``{branch, worst_case_usd, typical_usd,
    typical_minutes}`` (the typical figures are estimates from measured runs, ``None`` when unknown; empty list
    for the other modes). ``typical_minutes`` is end to end, excluding any wait for a GPU."""

    jobs: List[Dict[str, Any]] = []
    branches: List[Dict[str, Any]] = []
    total: Optional[float] = None
    current: Optional[str] = None
    for line in lines:
        header = _BRANCH_HEADER.match(line)
        if header:
            current = header.group(1).lower()
            continue
        job = _JOB_LINE.match(line)
        if job:
            jobs.append({"name": job.group("step"), "deadline_seconds": int(job.group("deadline")),
                         "worst_case_usd": float(job.group("cost")), "optional": bool(job.group("optional")),
                         "branch": current})
            continue
        summary = _BRANCH_LINE.match(line)
        if summary:
            typical, minutes = summary.group("typical"), summary.group("minutes")
            branches.append({"branch": summary.group("branch"), "worst_case_usd": float(summary.group("cost")),
                             "typical_usd": None if typical is None else float(typical),
                             "typical_minutes": None if minutes is None else int(minutes)})
            continue
        found = _TOTAL_LINE.match(line)
        if found:
            total = float(found.group("total"))
    return jobs, round(required, 2) if total is None else total, branches


def replay_jobs(case: Optional[Mapping[str, Any]], tools: Any) -> List[Tuple[str, str, int]]:
    """The Jobs a replay of ``case`` runs, as ``(step, what it does, deadline seconds)``, from the same
    workload builders the replay itself uses (so the plan cannot drift from the run).

    * a scenario case (or no case): one Job, two scenes of ``orchestrator.REPLAY_ATTEMPTS`` attempts;
    * a stress-test case: one Job per original probe group that holds a failing family;
    * a wording case: one rewording-screen Job.
    """

    from robot_debug import scenario_experiment as se

    kind = case.get("kind") if isinstance(case, Mapping) else None
    try:
        if kind == "audit":
            block = case.get("replay") if isinstance(case.get("replay"), Mapping) else {}
            attempts = block.get("attempts") if type(block.get("attempts")) is int else orch.pipeline_replay_attempts()
            required = block.get("required_failures") if type(block.get("required_failures")) is int else 4
            jobs = []
            groups = [g for g in block.get("groups") or () if isinstance(g, Mapping) and g.get("families")]
            for index, group in enumerate(groups):
                wanted = [(f["family"], f["severity"]) for f in group["families"]]
                workload = tools.audit_replay_workload(
                    case, [f for f, _s in wanted], sorted({s for _f, s in wanted}), attempts, required, "plan-replay")
                step = "replay" if index == 0 else "replay-{}".format(index + 1)
                jobs.append((step, "replay the stress test: {} ({} attempts per level)".format(
                    ", ".join(f for f, _s in wanted), attempts), int(workload["deadline_seconds"])))
            if jobs:
                return jobs
        elif kind == "paraphrase_reduction":
            replay = case.get("replay") if isinstance(case.get("replay"), Mapping) else {}
            config = replay.get("config") if isinstance(replay.get("config"), Mapping) else {}
            wording = config.get("instruction")
            original = replay.get("reference_instruction") or case.get("instruction")
            if isinstance(wording, str) and isinstance(original, str):
                workload = tools.wording_replay_workload(case, wording, original, "plan-replay")
                return [("replay", "replay the failing wording against the original",
                         int(workload["deadline_seconds"]))]
    except (orch.StopRun, KeyError, TypeError, ValueError):
        pass                                  # an unusable case falls back to the scenario plan
    deadline = se.recommended_deadline_seconds("scenario-replay", {"scenes": [None, None], "attempts": orch.REPLAY_ATTEMPTS})
    return [("replay", "replay the saved case ({} attempts per scene)".format(orch.REPLAY_ATTEMPTS), deadline)]


def replay_plan_lines(spec: sp.Spec, case: Optional[Mapping[str, Any]] = None, tools: Any = None
                      ) -> Tuple[List[str], float]:
    """The dry-run text for a replay, in the format of ``orchestrator.dry_run_lines``.

    The Jobs depend on the kind of ``case`` (see :func:`replay_jobs`); without a case the plan is the
    scenario replay. Every Job is reserved on its own against the cap, so the worst case is their sum."""

    rate = spec.backend.hourly_usd
    jobs = replay_jobs(case, tools if tools is not None else orch.DefaultTools())
    costs = [lg.worst_case_seconds(deadline) / 3600.0 * rate for _step, _what, deadline in jobs]
    lines = ["Planned Jobs ({} backend, US${:.4f}/h, cap US${:.2f}, {:g} h):".format(
        spec.backend.kind, rate, spec.budget.max_spend_usd, spec.budget.max_hours)]
    for (step, what, deadline), cost in zip(jobs, costs):
        lines.append("  {:<8} {:<56} deadline {:>4d} s  worst case US${:.2f}".format(step, what, deadline, cost))
    total = sum(costs)
    lines.append("Worst case of the required Jobs: US${:.2f}.".format(total))
    if costs and costs[0] > spec.budget.max_spend_usd:
        lines.append("WARNING: the first Job exceeds the cap; the spend ledger will refuse it and the replay will "
                     "stop early.")
    elif total > spec.budget.max_spend_usd:
        lines.append("WARNING: the Jobs together exceed the cap; the replay will stop after the Jobs that fit.")
    lines.append("Each Job is reserved at its worst case before submission and settled at measured container time.")
    return lines, total
