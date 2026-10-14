"""Build and push the Faultline Serverless image (``faultline image build`` / ``push``).

Thin wrappers around the ``docker`` CLI with argument lists (never a shell). The push goes to the
user's own *private* registry only: Faultline's image is not published to a public registry from
here (ADR 0031 needs a licence check and an explicit go first), so well-known public hosts and
a bare Docker Hub name are refused.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Callable, List, Optional

IMAGE_NAME = "faultline-serverless"
DEFAULT_DOCKERFILE = "deploy/serverless/Dockerfile"
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]{0,127}\Z")
_REVISION = re.compile(r"[0-9a-f]{4,40}\Z")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PATH_PART = re.compile(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*\Z")
_DIGEST = re.compile(r"digest:\s*(sha256:[0-9a-f]{64})")
_PUBLIC_HOSTS = frozenset({
    "docker.io", "index.docker.io", "registry-1.docker.io", "registry.hub.docker.com",
    "ghcr.io", "quay.io", "public.ecr.aws", "registry.gitlab.com",
})
_TAIL = 300

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class ImageCommandError(RuntimeError):
    """A docker step failed or an input was refused; the message is safe to print."""


def _check_tag(tag: Any) -> str:
    if type(tag) is not str or _TAG.fullmatch(tag) is None:
        raise ImageCommandError("the image tag is not a valid docker tag")
    return tag


def _check_path(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.startswith("-") or "\n" in value or "\0" in value:
        raise ImageCommandError("the {} is not a plain path".format(label))
    return value


def _run(run: Runner, argv: List[str], what: str) -> "subprocess.CompletedProcess[str]":
    try:
        result = run(argv, capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ImageCommandError("{} could not run (is it installed and on PATH?)".format(argv[0])) from error
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-_TAIL:]
        raise ImageCommandError("{} failed (exit {}){}".format(what, result.returncode,
                                                                ": " + tail if tail else ""))
    return result


def build(tag: str, dockerfile: str = DEFAULT_DOCKERFILE, *, context: str = ".",
          run: Runner = subprocess.run) -> str:
    """``docker build`` the image from the repository root and return its image id (``sha256:...``)."""

    _check_tag(tag)
    _check_path(dockerfile, "Dockerfile path")
    _check_path(context, "build context")
    _run(run, ["docker", "build", "--file", dockerfile, "--tag", tag, context], "docker build")
    inspected = _run(run, ["docker", "image", "inspect", "--format", "{{.Id}}", tag], "docker image inspect")
    image_id = inspected.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ImageCommandError("docker did not report an image id for the new image")
    return image_id


def _checked_registry(registry: Any) -> str:
    if type(registry) is not str or not registry:
        raise ImageCommandError("the registry must be a non-empty host/path")
    parts = registry.lower().split("/")
    host, path = parts[0], parts[1:]
    name, _, port = host.partition(":")
    if host in _PUBLIC_HOSTS or name in _PUBLIC_HOSTS:
        raise ImageCommandError("refusing to push to a public registry; use your own private registry")
    if "." not in name and ":" not in host and name != "localhost":
        raise ImageCommandError(
            "the registry needs a host (a bare name means Docker Hub, which is public); "
            "give HOST/PATH of your private registry")
    if registry != registry.lower():
        raise ImageCommandError("the registry host and path must be lowercase")
    if (not all(_HOST_LABEL.fullmatch(label) for label in name.split("."))
            or (port and (not port.isdigit() or not 1 <= int(port) <= 65535))
            or ":" in port or any(_PATH_PART.fullmatch(part) is None for part in path)):
        raise ImageCommandError("the registry is not a valid HOST[:PORT]/PATH")
    return registry


def _git_revision(run: Runner) -> str:
    try:
        result = run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError):
        result = None
    revision = (result.stdout.strip() if result is not None and result.returncode == 0 else "")
    if _REVISION.fullmatch(revision) is None:
        raise ImageCommandError("could not read the git revision for the tag; pass one explicitly")
    return revision


def push(local_tag: str, registry: str, *, revision: Optional[str] = None,
         run: Runner = subprocess.run) -> str:
    """Tag the local image ``<registry>/faultline-serverless:<git short sha>``, push it, and return
    ``<registry>/faultline-serverless@sha256:<digest>`` parsed from the push output."""

    _check_tag(local_tag)
    registry = _checked_registry(registry)
    if revision is None:
        revision = _git_revision(run)
    elif type(revision) is not str or _REVISION.fullmatch(revision) is None:
        raise ImageCommandError("the revision must be a git short sha")
    repository = "{}/{}".format(registry, IMAGE_NAME)
    remote = "{}:{}".format(repository, revision)
    _run(run, ["docker", "tag", local_tag, remote], "docker tag")
    pushed = _run(run, ["docker", "push", remote], "docker push")
    found = _DIGEST.search((pushed.stdout or "") + "\n" + (pushed.stderr or ""))
    if found is None:
        raise ImageCommandError("docker push finished but printed no digest")
    return "{}@{}".format(repository, found.group(1))


__all__ = ["DEFAULT_DOCKERFILE", "IMAGE_NAME", "ImageCommandError", "build", "push"]
