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
``paraphrase`` (ADR 0032)
    Reword the task instruction with Nemotron, screen the paraphrases for a failure, reduce the
    failing wording to its minimal word edits. ``paraphrase`` holds the task, the benchmark start,
    how many paraphrases to ask for, optionally the Token Factory model and the original
    instruction text (required unless the suite and task are one Faultline knows).
``replay``
    Used only with ``faultline replay`` (the case supplies the scenario); the spec
    gives the name, budget and backend.

``policy.checkpoint`` (optional, any mode; a replay spec may give it without ``policy.suite``) is
``{id: org/name, revision: <40-hex commit>}``: serve that Hugging Face repository at that commit instead of
the suite's pinned GR00T checkpoint, so a saved case can be replayed against a changed policy.

Nothing here imports the simulator, numpy or a cloud SDK.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from robot_debug import checkpoint_override as _checkpoint_module
from robot_debug import paraphrase as _paraphrase_module

SPEC_VERSION = 1
MODES = ("scenario", "audit", "paraphrase", "replay")
SUITES = ("libero_10", "libero_object", "libero_spatial", "libero_goal")
FAMILIES = ("darken", "noise", "blur", "contrast",
            "jpeg", "colour_cast", "motion_blur", "dead_pixels", "viewpoint", "lighting")
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

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/]{0,127}\Z")
_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,63}\Z")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/:@]{0,299}\Z")
_PROJECT = re.compile(r"(?:from-cli-profile|project-[a-z0-9]{1,64})\Z")
_REGION = re.compile(r"[a-z][a-z0-9-]{1,30}\Z")
_SUBNET = re.compile(r"vpcsubnet-[a-z0-9]{1,64}\Z")
_REGISTRY = re.compile(r"registry-[a-z0-9]{1,64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
# Optional ``backend:`` keys that only the named backend reads.
NEBIUS_KEYS = ("region", "subnet", "profile", "nebius_executable", "image_digest", "registry")
LOCAL_KEYS = ("docker_executable",)


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
    pool_text: str = "0-19"              # starts screened to find a reference for ``start``


@dataclass(frozen=True)
class Audit:
    task: int
    start: int
    families: Tuple[str, ...]


@dataclass(frozen=True)
class Paraphrase:
    task: int
    start: int
    count: int = _paraphrase_module.DEFAULT_COUNT
    model: str = _paraphrase_module.PARAPHRASE_MODEL
    instruction: Optional[str] = None      # the original task text (None: the known text of this suite and task)


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
class Checkpoint:
    """``policy.checkpoint``: serve this Hugging Face repository at this commit instead of the suite's pin."""

    id: str
    revision: str

    @property
    def pair(self) -> Tuple[str, str]:
        return self.id, self.revision


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
    paraphrase: Optional[Paraphrase] = None
    checkpoint: Optional[Checkpoint] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @property
    def mode_label(self) -> str:
        return {"scenario": "mode 1", "audit": "mode 2", "paraphrase": "paraphrase",
                "replay": "replay"}[self.mode]


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
    data = _exact(value, "scenario", ("task",), ("start", "screen", "import", "reference", "pool"))
    task = _int(data["task"], "scenario.task", 0, MAX_TASK)
    chosen = [key for key in ("start", "screen", "import") if key in data]
    if len(chosen) != 1:
        _fail("scenario", "give exactly one of start, screen or import")
    reference = data.get("reference", "auto")
    if reference != "auto":
        reference = _int(reference, "scenario.reference", 0, MAX_START)
    start = screen_starts = screen_text = import_path = None
    confirm = DEFAULT_CONFIRM
    pool_text = "0-19"
    if "pool" in data and chosen[0] != "start":
        _fail("scenario.pool", "only applies with scenario.start")
    if chosen[0] == "start":
        start = _int(data["start"], "scenario.start", 0, MAX_START)
        if reference == start:
            _fail("scenario.reference", "must differ from scenario.start")
        if "pool" in data:
            pool_text = data["pool"]
            parse_starts(pool_text, "scenario.pool")
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
                    confirm=confirm, import_path=import_path, reference=reference,
                    pool_text=pool_text.replace(" ", ""))


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


def _paraphrase(value: Any, suite: Optional[str]) -> Paraphrase:
    data = _exact(value, "paraphrase", ("task", "start"), ("count", "model", "instruction"))
    task = _int(data["task"], "paraphrase.task", 0, MAX_TASK)
    model = data.get("model", _paraphrase_module.PARAPHRASE_MODEL)
    _text(model, "paraphrase.model", _MODEL, "a Token Factory model id such as nvidia/nemotron-3-super-120b-a12b")
    instruction = data.get("instruction", _paraphrase_module.KNOWN_INSTRUCTIONS.get((suite, task)))
    if instruction is None:
        _fail("paraphrase.instruction", "is required for this suite and task (the task's language, as the "
              "benchmark gives it)")
    try:
        instruction = _paraphrase_module.clean_instruction(instruction)
    except _paraphrase_module.ParaphraseError:
        _fail("paraphrase.instruction", "must be 1 to {} printable ASCII characters".format(
            _paraphrase_module.MAX_CHARS))
    if not _paraphrase_module.has_words(instruction):
        _fail("paraphrase.instruction", "must contain words")
    return Paraphrase(
        task=task, start=_int(data["start"], "paraphrase.start", 0, MAX_START),
        count=_int(data.get("count", _paraphrase_module.DEFAULT_COUNT), "paraphrase.count", 1,
                   _paraphrase_module.MAX_COUNT),
        model=model, instruction=instruction)


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


def _checkpoint(value: Any) -> Checkpoint:
    data = _exact(value, "policy.checkpoint", (), ("id", "revision"))
    if "id" not in data:
        _fail("policy.checkpoint", "missing required key(s): id")
    if "revision" not in data:
        _fail("policy.checkpoint.revision", "is required when id is given (the 40-character commit to serve)")
    try:
        checkpoint_id = _checkpoint_module.validate_id(data["id"])
    except _checkpoint_module.CheckpointOverrideError as error:
        _fail("policy.checkpoint.id", str(error))
    try:
        revision = _checkpoint_module.validate_revision(data["revision"])
    except _checkpoint_module.CheckpointOverrideError as error:
        _fail("policy.checkpoint.revision", str(error))
    return Checkpoint(id=checkpoint_id, revision=revision)


def _executable(value: Any, path: str) -> None:
    parts = value if type(value) is list else [value]
    if not 1 <= len(parts) <= 8 or any(
            type(part) is not str or not part.strip() or len(part) > 300 or any(ord(c) < 32 for c in part)
            for part in parts):
        _fail(path, "must be a program path or a list of up to 8 non-empty strings")


def _backend_options(data: Mapping[str, Any]) -> None:
    """The optional keys the backends read from the raw ``backend:`` mapping (checked, not defaulted)."""

    checks = (("region", _REGION, "a region name such as eu-north1"),
              ("subnet", _SUBNET, "a subnet id (vpcsubnet-...)"),
              ("registry", _REGISTRY, "a registry id (registry-...)"),
              ("image_digest", _DIGEST, "sha256:<64 hex characters>"),
              ("profile", _TOKEN, "a CLI profile name"))
    for key, pattern, what in checks:
        if key in data:
            _text(data[key], "backend." + key, pattern, what)
    for key in ("nebius_executable", "docker_executable"):
        if key in data:
            _executable(data[key], "backend." + key)


def _backend(value: Any) -> BackendSpec:
    data = _exact(value, "backend", ("kind",), (
        "project", "platform", "preset", "image", "hf_token_secret", "hourly_usd") + NEBIUS_KEYS + LOCAL_KEYS)
    kind = data["kind"]
    if kind not in BACKEND_KINDS:
        _fail("backend.kind", "must be one of {}".format(", ".join(BACKEND_KINDS)))
    cloud = kind == "nebius"
    for key in (LOCAL_KEYS if cloud else NEBIUS_KEYS):
        if key in data:
            _fail("backend." + key, "only applies to the {} backend".format("local" if cloud else "nebius"))
    _backend_options(data)
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
        required += ["policy", mode]
    _exact(top, "spec", tuple(required), tuple(optional))
    if type(top["faultline"]) is not int or top["faultline"] != SPEC_VERSION:
        _fail("faultline", "must be the spec version {}".format(SPEC_VERSION))
    name = top["name"]
    if type(name) is not str or len(name) > MAX_NAME or _NAME.fullmatch(name) is None:
        _fail("name", "must be a lowercase slug of at most {} characters (letters, digits, hyphens)".format(MAX_NAME))
    suite = None
    checkpoint = None
    if "policy" in top:
        # A replay spec may name only a checkpoint (the case supplies the suite).
        policy = _exact(top["policy"], "policy", () if mode == "replay" else ("suite",), (
            "suite", "checkpoint") if mode == "replay" else ("checkpoint",))
        if "suite" in policy:
            suite = policy["suite"]
            if suite not in SUITES:
                _fail("policy.suite", "must be one of {}".format(", ".join(SUITES)))
        if "checkpoint" in policy:
            checkpoint = _checkpoint(policy["checkpoint"])
    return Spec(
        name=name, mode=mode, suite=suite, budget=_budget(top["budget"]),
        nemotron=_nemotron(top.get("nemotron", {})), backend=_backend(top["backend"]),
        scenario=_scenario(top["scenario"]) if mode == "scenario" else None,
        audit=_audit(top["audit"]) if mode == "audit" else None,
        paraphrase=_paraphrase(top["paraphrase"], suite) if mode == "paraphrase" else None,
        checkpoint=checkpoint, raw=top,
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
    "Audit", "BackendSpec", "Budget", "Checkpoint", "Nemotron", "Paraphrase", "Scenario", "Spec", "SpecError",
    "load_spec", "parse_spec", "parse_spec_text", "parse_starts",
]
