"""Prepare, but never execute, a bounded Nebius AI Job command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


_REQUIRED_FIELDS = frozenset({
    "run_id",
    "project_id",
    "image",
    "platform",
    "preset",
    "subnet_id",
    "bucket_id",
    "hf_secret",
    "workload_file",
})
_OPTIONAL_FIELDS = frozenset({"registry_secret"})
_RUN_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_IMAGE = re.compile(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}\Z")
_SECRET_SELECTOR = re.compile(
    r"mbsec-[a-z0-9]+(?:@mbsecver-[a-z0-9]+)?\Z"
)
_ID_PATTERNS = {
    "project_id": re.compile(r"project-[a-z0-9]+\Z"),
    "subnet_id": re.compile(r"vpcsubnet-[a-z0-9]+\Z"),
    "bucket_id": re.compile(r"storagebucket-[a-z0-9]+\Z"),
}
_MAX_WORKLOAD_BYTES = 64 * 1024


class ConfigError(ValueError):
    """Configuration is missing, malformed, or outside the bounded contract."""


def prepare(config: dict[str, object]) -> list[str]:
    """Return an argument vector for a validated, dry-run-only Job preview."""

    values = _validate(config)
    command = [
        "nebius", "ai", "job", "create",
        "--parent-id", values["project_id"],
        "--name", values["run_id"],
        "--image", values["image"],
        "--platform", values["platform"],
        "--preset", values["preset"],
        "--subnet-id", values["subnet_id"],
        "--disk-size", "150Gi",
        "--shm-size", "16Gi",
        "--timeout", "1h",
        "--restart-policy", "never",
        "--volume", values["bucket_id"] + ":/persistent:rw",
        "--env-secret", "HF_TOKEN=" + values["hf_secret"],
    ]
    registry_secret = values.get("registry_secret")
    if registry_secret is not None:
        command.extend(["--registry-secret", registry_secret])
    command.extend([
        "--inject-file", values["workload_file"] + ":/etc/faultline/workload.json",
        "--working-dir", "/opt/robot-debug",
        "--container-command", "/opt/conda/envs/libero/bin/python",
        "--args",
        "/opt/robot-debug/scripts/run_serverless_workload.py --config /etc/faultline/workload.json",
        "--dry-run", "--async",
    ])
    return command


def _validate(config: object) -> dict[str, str]:
    if not isinstance(config, dict):
        raise ConfigError("configuration must be a JSON object")
    keys = set(config)
    unknown = keys - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    missing = _REQUIRED_FIELDS - keys
    if unknown:
        raise ConfigError("unknown configuration field(s): " + ", ".join(sorted(map(str, unknown))))
    if missing:
        raise ConfigError("missing configuration field(s): " + ", ".join(sorted(missing)))
    values: dict[str, str] = {}
    for field in _REQUIRED_FIELDS:
        value = config[field]
        if type(value) is not str:
            raise ConfigError(field + " must be a string")
        values[field] = value
    if "registry_secret" in config:
        value = config["registry_secret"]
        if type(value) is not str:
            raise ConfigError("registry_secret must be a string")
        values["registry_secret"] = value

    if _RUN_ID.fullmatch(values["run_id"]) is None:
        raise ConfigError("run_id must be 1-63 lowercase ASCII letters, digits, or interior hyphens")
    for field, pattern in _ID_PATTERNS.items():
        if pattern.fullmatch(values[field]) is None:
            raise ConfigError(field + " has the wrong Nebius resource ID kind or syntax")
    if _IMAGE.fullmatch(values["image"]) is None:
        raise ConfigError("image must be an explicit immutable @sha256 digest")
    if values["platform"] != "gpu-l40s-a":
        raise ConfigError("platform must be the approved single-GPU gpu-l40s-a platform")
    if values["preset"] != "1gpu-16vcpu-64gb":
        raise ConfigError("preset must be the approved one-GPU 1gpu-16vcpu-64gb preset")
    for field in ("hf_secret", "registry_secret"):
        selector = values.get(field)
        if selector is not None and _SECRET_SELECTOR.fullmatch(selector) is None:
            raise ConfigError(field + " must be a Secret Stash selector, not a secret value")
    _validate_workload_file(values["workload_file"])
    return values


def _validate_workload_file(value: str) -> None:
    if not value or value.startswith("-"):
        raise ConfigError("workload_file must be a local file path")
    if ":" in value or "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ConfigError("workload_file must use safe POSIX path syntax without the CLI colon delimiter")
    if ".." in Path(value).parts:
        raise ConfigError("workload_file may not traverse a parent directory")
    path = Path(value)
    try:
        is_file = path.is_file()
        size = path.stat().st_size if is_file else 0
    except OSError as error:
        raise ConfigError("workload_file could not be inspected") from error
    if not is_file:
        raise ConfigError("workload_file must name an existing local file")
    if size > _MAX_WORKLOAD_BYTES:
        raise ConfigError("workload_file must be no larger than 64 KiB")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _load_config(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a bounded serverless Job config and print its JSON argv preview."
    )
    parser.add_argument("--config", required=True, type=Path, help="JSON configuration path")
    args = parser.parse_args(argv)
    try:
        command = prepare(_load_config(args.config))
    except (ConfigError, OSError, json.JSONDecodeError) as error:
        print("configuration rejected: {}".format(error), file=sys.stderr)
        return 2
    print(json.dumps(command))
    print(
        "PAID ACTION GATE: preview only; this includes --dry-run and does not create resources. "
        "Verify account, credit expiry, quota, live price, capacity, and a run-specific cap before any paid run.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
