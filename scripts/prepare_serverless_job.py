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
_OPTIONAL_FIELDS = frozenset({"registry_secret", "image_digest", "external_reset_file"})
_RUN_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IMAGE_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
# Nebius Jobs reject @sha256 image references (an internal label exceeds 64
# characters), so a tag in a private Nebius registry is accepted only with the
# digest it must resolve to; the submitter re-checks that mapping in the registry.
_NEBIUS_REGISTRY = re.compile(r"cr\.[a-z0-9-]+\.nebius\.cloud\Z")
_REGISTRY_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_REPOSITORY_COMPONENT = re.compile(
    r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*\Z"
)
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
        *(["--inject-file", values["external_reset_file"] + ":/etc/faultline/external-reset.json.gz"]
          if "external_reset_file" in values else []),
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
        raise ConfigError("configuration contains unknown field(s)")
    if missing:
        raise ConfigError("missing configuration field(s): " + ", ".join(sorted(missing)))
    values: dict[str, str] = {}
    for field in _REQUIRED_FIELDS:
        value = config[field]
        if type(value) is not str:
            raise ConfigError(field + " must be a string")
        values[field] = value
    for field in _OPTIONAL_FIELDS:
        if field in config:
            value = config[field]
            if type(value) is not str:
                raise ConfigError(field + " must be a string")
            values[field] = value

    if _RUN_ID.fullmatch(values["run_id"]) is None:
        raise ConfigError("run_id must be 1-63 lowercase ASCII letters, digits, or interior hyphens")
    for field, pattern in _ID_PATTERNS.items():
        if pattern.fullmatch(values[field]) is None:
            raise ConfigError(field + " has the wrong Nebius resource ID kind or syntax")
    _validate_image(values["image"], values.get("image_digest"))
    if values["platform"] != "gpu-l40s-a":
        raise ConfigError("platform must be the approved single-GPU gpu-l40s-a platform")
    if values["preset"] != "1gpu-16vcpu-64gb":
        raise ConfigError("preset must be the approved one-GPU 1gpu-16vcpu-64gb preset")
    for field in ("hf_secret", "registry_secret"):
        selector = values.get(field)
        if selector is not None and _SECRET_SELECTOR.fullmatch(selector) is None:
            raise ConfigError(field + " must be a Secret Stash selector, not a secret value")
    _validate_workload_file(values["workload_file"])
    _validate_batch_deadline(values["workload_file"])
    if "external_reset_file" in values:
        # Same local-path and 64 KiB inject limits as the workload file.
        _validate_workload_file(values["external_reset_file"])
    return values


def _validate_image(value: str, image_digest: str | None = None) -> None:
    if image_digest is not None and _IMAGE_DIGEST.fullmatch(image_digest) is None:
        raise ConfigError("image_digest must be a sha256 digest")
    if "@" in value:
        if value.count("@") != 1:
            raise ConfigError("image must be an explicit immutable @sha256 digest")
        name, digest = value.rsplit("@", 1)
        if _IMAGE_DIGEST.fullmatch(digest) is None or "://" in name:
            raise ConfigError("image must be an explicit immutable @sha256 digest")
        if image_digest is not None and image_digest != digest:
            raise ConfigError("image_digest does not match the image reference")
    else:
        name, separator, tag = value.rpartition(":")
        if (
            image_digest is None
            or not separator
            or "/" in tag
            or _IMAGE_TAG.fullmatch(tag) is None
            or "://" in name
            or _NEBIUS_REGISTRY.fullmatch(name.split("/", 1)[0]) is None
        ):
            raise ConfigError(
                "image must be an explicit immutable @sha256 digest, or a tag in a "
                "private Nebius registry together with image_digest"
            )

    components = name.split("/")
    if len(components) < 2 or any(not component for component in components):
        raise ConfigError("image must contain a valid registry and repository path")
    _validate_registry(components[0])
    repository = components[1:]
    if len("/".join(repository)) > 255 or any(
        _REPOSITORY_COMPONENT.fullmatch(component) is None for component in repository
    ):
        raise ConfigError("image contains an invalid repository path")


def _validate_registry(value: str) -> None:
    if value.count(":") > 1:
        raise ConfigError("image contains an invalid registry host or port")
    if ":" in value:
        host, port = value.rsplit(":", 1)
        if re.fullmatch(r"[0-9]{1,5}", port) is None or not 1 <= int(port) <= 65535:
            raise ConfigError("image contains an invalid registry host or port")
    else:
        host = value
    if len(host) > 253 or any(
        _REGISTRY_LABEL.fullmatch(label) is None for label in host.split(".")
    ):
        raise ConfigError("image contains an invalid registry host or port")


# The runtime reserves 600 s after the one model download (about 345 s on an
# L40S), so a batch-style workload (the M3 batching modes, the M6 modes and the
# scenario modes) needs at least this deadline or the download fails.
_BATCH_MODES = {
    "m3-batch", "m3-batch-smoke", "m6-smoke", "m6-threshold",
    "scenario-smoke", "scenario-screen", "scenario-reduce", "scenario-replay",
}
MIN_BATCH_DEADLINE_SECONDS = 1000


def _validate_batch_deadline(path: str) -> None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return  # existence and size were checked above; the runtime validates content
    try:
        workload = json.loads(text)
    except ValueError as error:
        raise ConfigError("workload_file must contain valid JSON") from error
    if not isinstance(workload, dict) or workload.get("mode") not in _BATCH_MODES:
        return
    deadline = workload.get("deadline_seconds")
    if type(deadline) not in (int, float) or deadline < MIN_BATCH_DEADLINE_SECONDS:
        raise ConfigError(
            "batch workload deadline_seconds must be at least %d to fit the model "
            "download and the runtime's 600 s post-download reserve" % MIN_BATCH_DEADLINE_SECONDS)


def _validate_workload_file(value: str) -> None:
    if not value or value.startswith("-"):
        raise ConfigError("workload_file must be a local file path")
    if value.startswith("//"):
        raise ConfigError("workload_file must not use a network path")
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
            raise ConfigError("configuration contains a duplicate JSON key")
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
