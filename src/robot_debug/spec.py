"""The ``faultline diagnose`` spec file: load and validate it, fail closed (ADR 0031).

A spec is one YAML mapping. Every section accepts exactly its documented keys; a
missing required key, an unknown key, a wrong type, an out-of-range number or a
duplicate key is an error that names the offending path, never a silent default.
``budget.max_spend_usd`` and ``budget.max_hours`` are required in every spec: the
command refuses to run without a spend cap and a hard deadline.

Modes:

``scenario`` (mode 1)
    Screen for a natural failure, reduce its scenario, report. ``scenario`` holds
    the task and exactly one of ``start`` (a known failing start), ``screen`` (a
    range of starts to screen) or ``import`` (a validated scenario candidate file).
``audit`` (mode 2)
    One perturbation-threshold audit of a task and start.
``replay``
    Used only with ``faultline replay`` (the case supplies the scenario); the spec
    gives the name, budget and backend.

Nothing here imports the simulator, numpy or a cloud SDK.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

SPEC_VERSION = 1
MODES = ("scenario", "audit", "replay")
SUITES = ("libero_10", "libero_object")
FAMILIES = ("darken", "noise", "blur", "contrast")
BACKEND_KINDS = ("nebius", "local")
MAX_TASK = 9
MAX_START = 49
MAX_NAME = 40
MAX_CANDIDATES = 60
DEFAULT_CANDIDATES = 36
MAX_SPEND_USD = 500.0
MAX_HOURS = 24.0
MAX_HOURLY_USD = 100.0
MIN_CONFIRM, MAX_CONFIRM, DEFAULT_CONFIRM = 4, 8, 4
MAX_SCREEN_EPISODES = 600
DEFAULT_PLATFORM = "gpu-l40s-a"
DEFAULT_PRESET = "1gpu-16vcpu-64gb"

_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,63}\Z")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/:@]{0,299}\Z")
_PROJECT = re.compile(r"(?:from-cli-profile|project-[a-z0-9]{1,64})\Z")


class SpecError(ValueError):
    """The spec is invalid; the message names the offending key and never echoes secrets."""


# --- typed result ---------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    task: int
    start: Optional[int] = None
    screen_starts: Optional[Tuple[int, ...]] = None
    screen_text: Optional[str] = None
    confirm: int = DEFAULT_CONFIRM
    import_path: Optional[str] = None
    reference: Any = "auto"              # "auto" or a start index


@dataclass(frozen=True)
class Audit:
    task: int
    start: int
    families: Tuple[str, ...]


@dataclass(frozen=True)
class Budget:
    max_spend_usd: float
    max_hours: float
    max_candidates: int = DEFAULT_CANDIDATES


@dataclass(frozen=True)
class Nemotron:
    hypothesis: bool = False
    explain: bool = False


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    hourly_usd: float
    project: str = "from-cli-profile"
    platform: str = DEFAULT_PLATFORM
    preset: str = DEFAULT_PRESET
    image: Optional[str] = None
    hf_token_secret: Optional[str] = None


@dataclass(frozen=True)
class Spec:
    name: str
    mode: str
    suite: Optional[str]
    budget: Budget
    nemotron: Nemotron
    backend: BackendSpec
    scenario: Optional[Scenario] = None
    audit: Optional[Audit] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @property
    def mode_label(self) -> str:
        return {"scenario": "mode 1", "audit": "mode 2", "replay": "replay"}[self.mode]


# --- primitives -----------------------------------------------------------------------


def _fail(path: str, message: str) -> None:
    raise SpecError("{}: {}".format(path, message))


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be a mapping")
    for key in value:
        if type(key) is not str:
            _fail(path, "keys must be strings")
    return value


def _exact(value: Any, path: str, required: Tuple[str, ...], optional: Tuple[str, ...] = ()) -> Mapping[str, Any]:
    data = _mapping(value, path)
    unknown = sorted(set(data) - set(required) - set(optional))
    if unknown:
        _fail(path, "unknown key(s): {}".format(", ".join(unknown)))
    missing = [key for key in required if key not in data]
    if missing:
        _fail(path, "missing required key(s): {}".format(", ".join(missing)))
    return data


def _int(value: Any, path: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        _fail(path, "must be an integer from {} to {}".format(low, high))
    return value


def _number(value: Any, path: str, low: float, high: float, *, exclusive_low: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        _fail(path, "must be a finite number")
    number = float(value)
    if (number <= low if exclusive_low else number < low) or number > high:
        _fail(path, "must be {} {:g} and at most {:g}".format(
            "greater than" if exclusive_low else "at least", low, high))
    return number


def _bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail(path, "must be true or false")
    return value


def _text(value: Any, path: str, pattern: "re.Pattern[str]", what: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(path, "must be {}".format(what))
    return value


def parse_starts(text: Any, path: str) -> Tuple[int, ...]:
    """``"10-49"`` or ``"0,3,5"`` or ``"0-2,7"`` as distinct indices from 0 to 49, in order."""

    if type(text) is not str or not text.strip():
        _fail(path, 'must be a string such as "10-49" or "0,3,5"')
    values: List[int] = []
    try:
        for part in text.split(","):
            part = part.strip()
            if "-" in part:
                low, high = part.split("-", 1)
                low_i, high_i = int(low), int(high)
                if high_i < low_i:
                    raise ValueError
                values.extend(range(low_i, high_i + 1))
            else:
                values.append(int(part))
    except ValueError:
        _fail(path, 'must look like "10-49" or "0,3,5"')
    if not values or len(set(values)) != len(values) or any(not 0 <= v <= MAX_START for v in values):
        _fail(path, "must hold distinct start indices from 0 to {}".format(MAX_START))
    return tuple(values)


# --- sections -------------------------------------------------------------------------


def _scenario(value: Any) -> Scenario:
    data = _exact(value, "scenario", ("task",), ("start", "screen", "import", "reference"))
    task = _int(data["task"], "scenario.task", 0, MAX_TASK)
    chosen = [key for key in ("start", "screen", "import") if key in data]
    if len(chosen) != 1:
        _fail("scenario", "give exactly one of start, screen or import")
    reference = data.get("reference", "auto")
    if reference != "auto":
        reference = _int(reference, "scenario.reference", 0, MAX_START)
    start = screen_starts = screen_text = import_path = None
    confirm = DEFAULT_CONFIRM
    if chosen[0] == "start":
        start = _int(data["start"], "scenario.start", 0, MAX_START)
        if reference == start:
            _fail("scenario.reference", "must differ from scenario.start")
    elif chosen[0] == "screen":
        screen = _exact(data["screen"], "scenario.screen", ("starts",), ("confirm",))
        screen_text = screen["starts"]
        screen_starts = parse_starts(screen_text, "scenario.screen.starts")
        confirm = _int(screen.get("confirm", DEFAULT_CONFIRM), "scenario.screen.confirm", MIN_CONFIRM, MAX_CONFIRM)
        if len(screen_starts) * (1 + confirm) > MAX_SCREEN_EPISODES:
            _fail("scenario.screen", "screens more episodes than the Job allows ({})".format(MAX_SCREEN_EPISODES))
        if reference != "auto" and reference not in screen_starts:
            _fail("scenario.reference", "must be one of the screened starts")
    else:
        path = data["import"]
        if type(path) is not str or not path.strip() or len(path) > 500 or any(ord(c) < 32 for c in path):
            _fail("scenario.import", "must be a file path")
        import_path = path
    return Scenario(task=task, start=start, screen_starts=screen_starts, screen_text=screen_text,
                    confirm=confirm, import_path=import_path, reference=reference)


def _audit(value: Any) -> Audit:
    data = _exact(value, "audit", ("task", "start", "families"))
    families = data["families"]
    if type(families) is not list or not 1 <= len(families) <= len(FAMILIES):
        _fail("audit.families", "must be a non-empty list of perturbation families")
    for item in families:
        if type(item) is not str or item not in FAMILIES:
            _fail("audit.families", "unknown family (one of {})".format(", ".join(FAMILIES)))
    if len(set(families)) != len(families):
        _fail("audit.families", "must not repeat a family")
    return Audit(task=_int(data["task"], "audit.task", 0, MAX_TASK),
                 start=_int(data["start"], "audit.start", 0, MAX_START), families=tuple(families))


def _budget(value: Any) -> Budget:
    data = _exact(value, "budget", ("max_spend_usd", "max_hours"), ("max_candidates",))
    return Budget(
        max_spend_usd=_number(data["max_spend_usd"], "budget.max_spend_usd", 0.0, MAX_SPEND_USD, exclusive_low=True),
        max_hours=_number(data["max_hours"], "budget.max_hours", 0.0, MAX_HOURS, exclusive_low=True),
        max_candidates=_int(data.get("max_candidates", DEFAULT_CANDIDATES), "budget.max_candidates",
                            1, MAX_CANDIDATES))


def _nemotron(value: Any) -> Nemotron:
    data = _exact(value, "nemotron", (), ("hypothesis", "explain"))
    return Nemotron(hypothesis=_bool(data.get("hypothesis", False), "nemotron.hypothesis"),
                    explain=_bool(data.get("explain", False), "nemotron.explain"))


def _backend(value: Any) -> BackendSpec:
    data = _exact(value, "backend", ("kind",), (
        "project", "platform", "preset", "image", "hf_token_secret", "hourly_usd"))
    kind = data["kind"]
    if kind not in BACKEND_KINDS:
        _fail("backend.kind", "must be one of {}".format(", ".join(BACKEND_KINDS)))
    cloud = kind == "nebius"
    for key in (("image", "hf_token_secret", "hourly_usd") if cloud else ("image",)):
        if key not in data:
            _fail("backend", "missing required key(s) for {}: {}".format(kind, key))
    rate = _number(data.get("hourly_usd", 0.0), "backend.hourly_usd", 0.0, MAX_HOURLY_USD,
                   exclusive_low=cloud)
    secret = data.get("hf_token_secret")
    return BackendSpec(
        kind=kind,
        hourly_usd=rate,
        project=_text(data.get("project", "from-cli-profile"), "backend.project", _PROJECT,
                      "from-cli-profile or a project id (project-...)"),
        platform=_text(data.get("platform", DEFAULT_PLATFORM), "backend.platform", _TOKEN, "a platform name"),
        preset=_text(data.get("preset", DEFAULT_PRESET), "backend.preset", _TOKEN, "a preset name"),
        image=_text(data["image"], "backend.image", _IMAGE, "an image reference without spaces"),
        hf_token_secret=None if secret is None else _text(
            secret, "backend.hf_token_secret", _TOKEN, "a secret name (never the token itself)"),
    )


def parse_spec(data: Any) -> Spec:
    """Validate a decoded spec mapping; raises :class:`SpecError`."""

    top = _mapping(data, "spec")
    mode = top.get("mode")
    if mode not in MODES:
        _fail("mode", "must be one of {}".format(", ".join(MODES)))
    required = ["faultline", "name", "mode", "budget", "backend"]
    optional = ["nemotron"]
    if mode == "replay":
        optional.append("policy")
    else:
        required += ["policy", "scenario" if mode == "scenario" else "audit"]
    _exact(top, "spec", tuple(required), tuple(optional))
    if type(top["faultline"]) is not int or top["faultline"] != SPEC_VERSION:
        _fail("faultline", "must be the spec version {}".format(SPEC_VERSION))
    name = top["name"]
    if type(name) is not str or len(name) > MAX_NAME or _NAME.fullmatch(name) is None:
        _fail("name", "must be a lowercase slug of at most {} characters (letters, digits, hyphens)".format(MAX_NAME))
    suite = None
    if "policy" in top:
        policy = _exact(top["policy"], "policy", ("suite",))
        suite = policy["suite"]
        if suite not in SUITES:
            _fail("policy.suite", "must be one of {}".format(", ".join(SUITES)))
    return Spec(
        name=name, mode=mode, suite=suite, budget=_budget(top["budget"]),
        nemotron=_nemotron(top.get("nemotron", {})), backend=_backend(top["backend"]),
        scenario=_scenario(top["scenario"]) if mode == "scenario" else None,
        audit=_audit(top["audit"]) if mode == "audit" else None,
        raw=top,
    )


# --- YAML -----------------------------------------------------------------------------


def _loader():
    try:
        import yaml
    except ImportError:
        raise SpecError("PyYAML is required to read a spec (pip install \".[cli]\")") from None

    class StrictLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        seen = set()
        for key_node, _value in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise SpecError("spec: duplicate key {!r}".format(key))
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml, StrictLoader


def parse_spec_text(text: str) -> Spec:
    yaml, loader = _loader()
    try:
        data = yaml.load(text, Loader=loader)
    except SpecError:
        raise
    except yaml.YAMLError:
        raise SpecError("spec: not valid YAML") from None
    return parse_spec(data)


def load_spec(path: Any) -> Spec:
    """Read and validate a spec file."""

    target = Path(path)
    try:
        if target.stat().st_size > 64 * 1024:
            raise SpecError("spec: file is larger than 64 KiB")
        text = target.read_text(encoding="utf-8")
    except SpecError:
        raise
    except (OSError, UnicodeDecodeError):
        raise SpecError("spec: the file could not be read") from None
    return parse_spec_text(text)


__all__ = [
    "Audit", "BackendSpec", "Budget", "Nemotron", "Scenario", "Spec", "SpecError",
    "load_spec", "parse_spec", "parse_spec_text", "parse_starts",
]
