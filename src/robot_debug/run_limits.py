"""Raise the spend cap or the hour limit of a stopped run so it can be resumed.

A run stopped by ``spend_cap`` or ``max_hours`` is continued from its own folder, with the spec saved there. This
rewrites that spec's ``budget`` (the ledger then accepts the larger limits when the run is resumed). The limits can
only go up: a smaller cap or limit than the run has now is refused, and so is any cap below what is already spent.
Nothing else in the spec changes and nothing is sent to the cloud.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from robot_debug import spec as sp

LIMIT_KEYS = ("max_spend_usd", "max_hours")


class RunLimitError(ValueError):
    """The new limits are not acceptable; the message says why, in plain words."""


def _number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RunLimitError("{} must be a number.".format(label))
    return float(value)


def _text(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(value)


def _load(text: str) -> Dict[str, Any]:
    yaml, loader = sp._loader()
    try:
        data = yaml.load(text, Loader=loader)
    except Exception:           # noqa: BLE001 - any YAML error means the spec cannot be read
        raise ValueError("not valid YAML") from None
    if not isinstance(data, dict) or not isinstance(data.get("budget"), dict):
        raise ValueError("no budget")
    return data


def _budget(text: str) -> Dict[str, float]:
    """The ``max_spend_usd`` and ``max_hours`` a spec text sets."""

    budget = _load(text)["budget"]
    return {key: _number(budget.get(key), key) for key in LIMIT_KEYS}


def _spent(run_dir: Path) -> float:
    try:
        ledger = json.loads((run_dir / "ledger.json").read_text(encoding="utf-8"))
        jobs = ledger.get("jobs") if isinstance(ledger, dict) else None
        return round(sum(float(job.get("cost_usd") or 0.0) for job in (jobs or {}).values()
                         if isinstance(job, dict) and job.get("state") == "settled"), 6)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0


def _rewrite_budget_lines(text: str, new: Dict[str, float]) -> str:
    """The spec text with the ``budget:`` block's limit lines replaced (comments and other keys kept)."""

    lines = text.split(chr(10))
    inside = False
    for index, line in enumerate(lines):
        if re.match(r"^budget:\s*(#.*)?$", line):
            inside = True
            continue
        if inside and line.strip() and not line.startswith((" ", chr(9), "#")):
            inside = False
        if not inside:
            continue
        match = re.match(r"^(\s+)(max_spend_usd|max_hours):\s*[^\s#][^#]*?(\s*(?:#.*)?)$", line)
        if match and match.group(2) in new:
            lines[index] = "{}{}: {}{}".format(match.group(1), match.group(2), _text(new[match.group(2)]),
                                                 match.group(3))
    return chr(10).join(lines)


def raise_limits(run_dir: Any, max_spend_usd: Optional[float] = None, max_hours: Optional[float] = None) -> Dict[str, float]:
    """Raise ``budget.max_spend_usd`` and/or ``budget.max_hours`` in the run's saved spec; returns the limits now.

    Raises :class:`RunLimitError` for a value that is not a number, is below the current limit, is below what the
    run has spent, or is above the most a spec may ask for (the spec's own bounds apply)."""

    folder = Path(run_dir)
    path = folder / "spec.yaml"
    try:
        text = path.read_text(encoding="utf-8")
        now = _budget(text)
    except (OSError, UnicodeDecodeError, ValueError):
        raise RunLimitError("The run's saved spec could not be read.") from None
    asked = {"max_spend_usd": max_spend_usd, "max_hours": max_hours}
    bounds = {"max_spend_usd": sp.MAX_SPEND_USD, "max_hours": sp.MAX_HOURS}
    new: Dict[str, float] = {}
    for key, label in (("max_spend_usd", "The spend cap"), ("max_hours", "The hour limit")):
        if asked[key] is None:
            continue
        value = _number(asked[key], label)
        if value < now[key]:
            raise RunLimitError("{} can be raised on a resume, never lowered (it is {:g}, not {:g}).".format(
                label, now[key], value))
        if value > bounds[key]:
            raise RunLimitError("{} can be at most {:g}.".format(label, bounds[key]))
        if key == "max_spend_usd" and value < _spent(folder):
            raise RunLimitError("The spend cap cannot be lower than the US${:.2f} already spent.".format(_spent(folder)))
        if value != now[key]:
            new[key] = value
    if not new:
        return dict(now)
    updated = _rewrite_budget_lines(text, new)
    wanted = dict(now, **new)
    try:
        ok = _budget(updated) == wanted
    except ValueError:
        ok = False
    if not ok:                                   # a flow-style budget the line edit cannot reach: dump the spec
        import yaml

        raw = _load(text)
        raw["budget"] = dict(raw["budget"], **new)
        updated = yaml.safe_dump(raw, sort_keys=False)
        if _budget(updated) != wanted:
            raise RunLimitError("The run's saved spec could not be updated.")
    temporary = path.with_name("spec.yaml.tmp")
    temporary.write_text(updated, encoding="utf-8", newline=chr(10))
    os.replace(str(temporary), str(path))
    return wanted
