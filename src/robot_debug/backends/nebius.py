"""Run diagnosis Jobs on Nebius AI Cloud Serverless Jobs by wrapping the ``nebius`` CLI.

This ports the flow proven by hand on October 13, 2026: one results bucket per
diagnosis (1-day expiry), a *reusable* read group and service account per
project, one access key per diagnosis (deleted in :meth:`NebiusBackend.finish`),
submission through ``scripts/prepare_serverless_job.py`` (dry run first), Job
status polling with a watchdog, and a boto3 download restricted to the Job's own
export prefix.

Secrets never appear on a command line, in a message or in a file: the S3
secret is read from ``iam v2 access-key get`` in memory only and handed to
boto3. Resource ids are redacted in every error message.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform as _platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from robot_debug.ledger import provider_timeout_seconds
from robot_debug.spec import DEFAULT_PLATFORM, DEFAULT_PRESET

from . import (
    BackendError,
    JobHandle,
    JobResult,
    check_job,
    iso_utc,
    redact,
    run_command,
    write_workload,
)

DEFAULT_REGION = "eu-north1"
GROUP_NAME = "faultline-readers"
SERVICE_ACCOUNT_NAME = "faultline-reader"
BUCKET_MAX_BYTES = 5 * 1024 ** 3
CALL_TIMEOUT_SECONDS = 60.0
SUBMIT_TIMEOUT_SECONDS = 180.0
CANCEL_GRACE_SECONDS = 300.0           # after a cancel; the provider timeout (deadline + 600 s) ends the Job anyway
WAIT_MARGIN_SECONDS = 300.0            # beyond the watchdog limits before wait() gives up for good
CREATE_LOOKUP_TRIES = 5
MAX_DOWNLOAD_BYTES = 5 * 1024 ** 3
STATE_FILE = "backend-state.json"

LIFECYCLE_RULES = [{
    "id": "expire-after-1-day", "status": "enabled", "filter": {"prefix": ""},
    "expiration": {"days": 1},
    "abort_incomplete_multipart_upload": {"days_after_initiation": 1},
}]

_PROJECT_ID = re.compile(r"project-[a-z0-9]+\Z")
_IMAGE_REGION = re.compile(r"cr\.([a-z0-9-]+)\.nebius\.cloud\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TRANSIENT = re.compile(
    r"unavailable|i/o timeout|handshake|connection reset|connection refused|"
    r"deadline.?exceeded|temporarily|unexpected eof|\bEOF\b|tls|"
    r"\b50[234]\b|too many requests|timed out", re.IGNORECASE)
_JOB_ID_TEXT = re.compile(r"\baijob-[a-z0-9]+\b")
_NOT_FOUND = re.compile(r"not.?found", re.IGNORECASE)
_EXISTS = re.compile(r"already.?exists", re.IGNORECASE)

_TERMINAL = {
    "COMPLETED": "COMPLETED", "SUCCEEDED": "COMPLETED", "FAILED": "FAILED",
    "ERROR": "ERROR", "CANCELLED": "CANCELLED", "CANCELED": "CANCELLED",
    "DELETED": "CANCELLED",
}


class CliError(BackendError):
    """One ``nebius`` call failed. ``kind`` is transient, notfound, exists or other."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


# -- executable resolution ---------------------------------------------------

class Launcher:
    """Turns CLI arguments into the argv that runs ``nebius`` here or inside WSL."""

    def __init__(self, prefix: Sequence[str] = (), wsl: bool = False, wsl_exe: str = "wsl.exe") -> None:
        self.prefix = list(prefix)
        self.wsl = wsl
        self.wsl_exe = wsl_exe

    def argv(self, args: Sequence[str], cwd: Optional[Path] = None) -> List[str]:
        if not self.wsl:
            return [*self.prefix, *args]
        command = "$HOME/.nebius/bin/nebius " + " ".join(shlex.quote(a) for a in args)
        if cwd is not None:
            command = "cd %s && %s" % (shlex.quote(to_wsl_path(cwd)), command)
        # base64 keeps JSON arguments intact through wsl.exe's argument handling.
        encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
        return [self.wsl_exe, "-e", "bash", "-lc", "echo %s|base64 -d|bash" % encoded]


def to_wsl_path(path: Path) -> str:
    """``C:\\a\\b`` as ``/mnt/c/a/b`` for commands run inside WSL."""

    windows = PureWindowsPath(str(path))
    if not windows.drive or len(windows.drive) != 2:
        return PurePosixPath(str(path).replace("\\", "/")).as_posix()
    rest = "/".join(windows.parts[1:])
    return "/mnt/%s/%s" % (windows.drive[0].lower(), rest)


def resolve_launcher(
    setting: Any = None,
    *,
    which: Callable[[str], Optional[str]] = shutil.which,
    system: Callable[[], str] = _platform.system,
) -> Launcher:
    """An explicit setting, else ``nebius`` on PATH, else WSL on Windows."""

    if isinstance(setting, (list, tuple)) and setting:
        return Launcher([str(part) for part in setting])
    if isinstance(setting, str) and setting:
        if setting.lower() == "wsl":
            return Launcher(wsl=True, wsl_exe=which("wsl.exe") or "wsl.exe")
        return Launcher([setting])
    found = which("nebius")
    if found:
        return Launcher([found])
    if system() == "Windows":
        wsl = which("wsl.exe") or which("wsl")
        if wsl:
            return Launcher(wsl=True, wsl_exe=wsl)
    raise BackendError(
        "the nebius CLI was not found; install it (https://docs.nebius.com/cli), put it on PATH, "
        "or set backend.nebius_executable"
    )


# -- the CLI wrapper -----------------------------------------------------------

class NebiusCli:
    """Runs ``nebius`` with timeouts, transient-error retries and redacted errors."""

    def __init__(
        self,
        launcher: Launcher,
        runner: Callable[..., Any] = run_command,
        sleep: Callable[[float], None] = time.sleep,
        profile: Optional[str] = None,
        backoff: Sequence[float] = (3.0, 10.0),
    ) -> None:
        self.launcher = launcher
        self._runner = runner
        self._sleep = sleep
        self._profile = profile
        self._backoff = list(backoff)

    def text(self, args: Sequence[str], *, cwd: Optional[Path] = None,
             timeout: float = CALL_TIMEOUT_SECONDS, tries: int = 3) -> str:
        full = (["--profile", self._profile] if self._profile else []) + list(args)
        words = []
        for arg in args:
            if re.fullmatch(r"[a-z][a-z-]*", arg) is None:
                break  # flags and resource ids end the command words
            words.append(arg)
        label = "nebius " + " ".join(words)
        error: Optional[CliError] = None
        for attempt in range(max(1, tries)):
            if attempt:
                self._sleep(self._backoff[min(attempt - 1, len(self._backoff) - 1)])
            try:
                result = self._runner(self.launcher.argv(full, cwd), cwd=cwd, timeout=timeout)
            except subprocess.TimeoutExpired:
                error = CliError("%s timed out after %ds" % (label, timeout), "transient")
                continue
            except OSError as exc:
                raise CliError("could not run %s: %s" % (label, type(exc).__name__), "other") from exc
            if result.returncode == 0:
                return result.stdout or ""
            detail = " ".join(((result.stderr or "") + " " + (result.stdout or "")).split())
            if _NOT_FOUND.search(detail):
                kind = "notfound"
            elif _EXISTS.search(detail):
                kind = "exists"
            elif _TRANSIENT.search(detail):
                kind = "transient"
            else:
                kind = "other"
            error = CliError("%s failed (exit %s): %s" % (label, result.returncode, redact(detail[-300:])), kind)
            if kind != "transient":
                raise error
        assert error is not None
        raise error

    def json(self, args: Sequence[str], **kwargs: Any) -> Any:
        text = self.text(args, **kwargs)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise CliError(redact("nebius %s returned output that is not JSON" % " ".join(
                a for a in args[:3] if not a.startswith("-"))), "other") from exc


def resource_id(payload: Any) -> Optional[str]:
    """The id of a created resource from an operation or resource response."""

    if isinstance(payload, dict):
        found = payload.get("resource_id")
        if not found and isinstance(payload.get("metadata"), dict):
            found = payload["metadata"].get("id")
        if isinstance(found, str) and found:
            return found
    return None


def _job_id_from_output(text: str) -> Optional[str]:
    """The Job id from ``ai job create`` output: JSON, or text such as ``Job ID: aijob-...``."""

    try:
        found = resource_id(json.loads(text))
    except ValueError:
        found = None
    if found:
        return found
    match = _JOB_ID_TEXT.search(text or "")
    return match.group(0) if match else None


def parse_time(value: Any) -> Optional[float]:
    """Epoch seconds from an ISO-8601 timestamp; None for missing or zero times."""

    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if stamp.year < 2000:
        return None
    return stamp.timestamp()


def _items(payload: Any, *keys: str) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        for key in (*keys, "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _by_name(items: List[Dict[str, Any]], name: str) -> Optional[str]:
    for item in items:
        meta = item.get("metadata") or {}
        if meta.get("name") == name and meta.get("id"):
            return str(meta["id"])
    return None


def default_s3_factory(endpoint: str, region: str, key_id: str, secret: str) -> Any:
    """A boto3 S3 client (optional ``cloud`` extra) trusting the system certificates."""

    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise BackendError(
            "downloading results needs boto3: pip install 'robot-debug[cloud]' (or pip install boto3 truststore)"
        ) from exc
    return boto3.client(
        "s3", endpoint_url=endpoint, region_name=region,
        aws_access_key_id=key_id, aws_secret_access_key=secret,
        config=Config(retries={"max_attempts": 5}, connect_timeout=15, read_timeout=60),
    )


def region_from_image(image: str) -> str:
    """The region in a ``cr.<region>.nebius.cloud/...`` image host, else the default region."""

    found = _IMAGE_REGION.match(image.split("/", 1)[0])
    return found.group(1) if found else DEFAULT_REGION


def _sanitise_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return cleaned[:40].strip("-") or "run"


# -- the backend ---------------------------------------------------------------

class NebiusBackend:
    """Nebius Serverless Jobs backend. ``runner`` is injectable so tests use a fake CLI."""

    kind = "nebius"

    def __init__(
        self,
        *,
        project: str,
        platform: str,
        preset: str,
        image: str,
        hf_token_secret: str,
        hourly_usd: float,
        region: str = DEFAULT_REGION,
        image_digest: Optional[str] = None,
        registry: Optional[str] = None,
        subnet: Optional[str] = None,
        profile: Optional[str] = None,
        executable: Any = None,
        runner: Callable[..., Any] = run_command,
        script_runner: Callable[..., Any] = run_command,
        s3_factory: Callable[..., Any] = default_s3_factory,
        which: Callable[[str], Optional[str]] = shutil.which,
        system: Callable[[], str] = _platform.system,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        prepare_script: Optional[Path] = None,
        suffix: Callable[[], str] = lambda: secrets.token_hex(3),
        max_download_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> None:
        if project != "from-cli-profile" and _PROJECT_ID.match(project) is None:
            raise BackendError("backend.project must be 'from-cli-profile' or a project-... id")
        if not isinstance(hourly_usd, (int, float)) or isinstance(hourly_usd, bool) or hourly_usd <= 0:
            raise BackendError("backend.hourly_usd must be a positive number")
        self.project = project
        self.platform = platform
        self.preset = preset
        self.hf_token_secret = hf_token_secret
        self.hourly_usd = float(hourly_usd)
        self.region = region
        self._subnet = subnet
        self._registry = registry
        self._image, self._image_digest, self._preferred_tag = self._check_image(image, image_digest)
        self._launcher = resolve_launcher(executable, which=which, system=system)
        self._cli = NebiusCli(self._launcher, runner, sleep, profile)
        self._script_runner = script_runner
        self._s3_factory = s3_factory
        self._clock = clock
        self._sleep = sleep
        self._suffix = suffix
        self._max_download_bytes = max_download_bytes
        self._prepare_script = prepare_script or (
            Path(__file__).resolve().parents[3] / "scripts" / "prepare_serverless_job.py")
        self._run_dir: Optional[Path] = None
        self._state: Dict[str, Any] = {}
        self.cleanup_report: Dict[str, str] = {}

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any], **overrides: Any) -> "NebiusBackend":
        backend = spec.get("backend", {})
        for field in ("image", "hf_token_secret", "hourly_usd"):
            if field not in backend:
                raise BackendError("backend.%s is required for the nebius backend" % field)
        return cls(
            project=str(backend.get("project", "from-cli-profile")),
            platform=str(backend.get("platform", DEFAULT_PLATFORM)),
            preset=str(backend.get("preset", DEFAULT_PRESET)),
            image=str(backend["image"]),
            hf_token_secret=str(backend["hf_token_secret"]),
            hourly_usd=backend["hourly_usd"],
            region=str(backend.get("region") or region_from_image(str(backend["image"]))),
            image_digest=backend.get("image_digest"),
            registry=backend.get("registry"),
            subnet=backend.get("subnet"),
            profile=backend.get("profile"),
            executable=backend.get("nebius_executable"),
            **overrides,
        )

    @staticmethod
    def _check_image(image: str, image_digest: Optional[str]) -> "tuple[str, str, Optional[str]]":
        """Return (repository, digest, preferred tag); the tag is verified in the registry."""

        if not isinstance(image, str) or not image:
            raise BackendError("backend.image is required")
        if "@" in image:
            name, _, digest = image.partition("@")
        else:
            name, digest = image, image_digest or ""
            last = name.rsplit("/", 1)[-1]
            if ":" not in last or not digest:
                raise BackendError(
                    "backend.image must be pinned: repo@sha256:<digest>, or repo:tag with backend.image_digest")
        if _DIGEST.match(digest) is None:
            raise BackendError("backend.image digest must be sha256:<64 hex characters>")
        if image_digest is not None and "@" in image and image_digest != digest:
            raise BackendError("backend.image_digest does not match the image reference")
        tag: Optional[str] = None
        head, _, last = name.rpartition("/")
        if ":" in last:
            last, _, tag = last.partition(":")
            name = head + "/" + last
        return name, digest, tag

    # -- Backend protocol -------------------------------------------------

    def price_per_hour(self) -> float:
        return self.hourly_usd

    def prepare(self, run_dir: Path, spec: Mapping[str, Any]) -> None:
        self._run_dir = Path(run_dir)
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
        state = self._state
        cli = self._cli

        # Cheap read-only checks first so a bad setup fails before anything is created.
        if "project_id" not in state:
            state["project_id"] = self._resolve_project()
            self._save_state()
        project = state["project_id"]
        if "tenant_id" not in state:
            meta = cli.json(["iam", "project", "get", project, "--format", "json"]).get("metadata") or {}
            if not meta.get("parent_id"):
                raise BackendError("could not read the tenant of the project")
            state["tenant_id"] = meta["parent_id"]
            self._save_state()
        if "hf_secret_id" not in state:
            listing = cli.json(["mysterybox", "secret", "list", "--parent-id", project, "--format", "json"])
            found = _by_name(_items(listing), self.hf_token_secret)
            if found is None:
                raise BackendError("MysteryBox secret %r not found in the project" % self.hf_token_secret)
            state["hf_secret_id"] = found
            self._save_state()
        if "subnet_id" not in state:
            state["subnet_id"] = self._subnet or self._first_subnet(project)
            self._save_state()
        tag = self._resolve_tag()
        state["image_tag"] = tag
        self._save_state()

        # Reusable identity: found by name, created only when missing.
        if "group_id" not in state:
            state["group_id"] = self._find_or_create(
                ["iam", "group", "list", "--parent-id", state["tenant_id"], "--format", "json"],
                ["iam", "group", "create", "--parent-id", state["tenant_id"], "--name", GROUP_NAME,
                 "--format", "json"], GROUP_NAME)
            self._save_state()
        if "service_account_id" not in state:
            state["service_account_id"] = self._find_or_create(
                ["iam", "service-account", "list", "--parent-id", project, "--format", "json"],
                ["iam", "service-account", "create", "--parent-id", project, "--name",
                 SERVICE_ACCOUNT_NAME, "--format", "json"], SERVICE_ACCOUNT_NAME)
            self._save_state()
        if not state.get("membership_ok"):
            self._ensure_membership(state["group_id"], state["service_account_id"])
            state["membership_ok"] = True
            self._save_state()

        # One bucket per diagnosis (a resumed run after finish() removed it gets a fresh one).
        if "bucket_id" not in state or state.get("bucket_deleted"):
            name = str(spec.get("name") or self._run_dir.name)
            bucket_name = "faultline-%s-%s" % (_sanitise_name(name), self._suffix())
            state["bucket_name"] = bucket_name
            state["bucket_id"] = self._create_bucket(bucket_name, project, state["group_id"])
            state["bucket_deleted"] = False
            state.pop("bucket_delete_outcome", None)
            state["pending_jobs"] = []
            self._save_state()

        # One access key per diagnosis (a resumed run after finish() gets a fresh one).
        if "access_key_id" not in state or state.get("access_key_deleted"):
            created = cli.json([
                "iam", "v2", "access-key", "create", "--parent-id", project,
                "--account-service-account-id", state["service_account_id"],
                "--description", "faultline %s read-only download" % _sanitise_name(
                    str(spec.get("name") or "run")),
                "--format", "json"])
            key_id = resource_id(created)
            if key_id is None:
                raise BackendError("access key creation returned no id")
            state["access_key_id"] = key_id
            state["access_key_deleted"] = False
            self._save_state()

    def submit(self, job_name: str, workload: Mapping[str, Any]) -> JobHandle:
        run_dir = self._need_prepared()
        check_job(job_name, workload)
        job_dir = run_dir / "jobs" / job_name
        record = job_dir / "job.json"
        if record.is_file():
            try:
                saved = json.loads(record.read_text(encoding="utf-8"))
                if saved.get("job_id"):
                    self._mark_pending(job_name)
                    return JobHandle(job_name, saved["job_id"])  # never resubmit a known Job
            except (OSError, ValueError):
                pass
        state = self._state
        tag = self._resolve_tag()  # the tag must still resolve to the pinned digest
        write_workload(job_dir / "workload.json", workload)
        config = {
            "run_id": job_name, "project_id": state["project_id"],
            "image": "%s:%s" % (self._image, tag), "image_digest": self._image_digest,
            "platform": self.platform, "preset": self.preset,
            "subnet_id": state["subnet_id"], "bucket_id": state["bucket_id"],
            "hf_secret": state["hf_secret_id"], "workload_file": "workload.json",
        }
        deadline = workload.get("deadline_seconds")
        if type(deadline) in (int, float) and deadline > 0:
            # The provider stops the Job at deadline + grace even if this process sleeps or dies.
            config["timeout_seconds"] = provider_timeout_seconds(deadline)
        (job_dir / "job-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        argv = self._prepared_argv(job_dir)

        dry = self._cli.text(argv[1:], cwd=job_dir, timeout=SUBMIT_TIMEOUT_SECONDS)
        del dry  # only the exit status matters
        create = argv[1:-2] + ["--async", "--format", "json"]
        job_id = self._create_job(job_name, create, job_dir)
        record.write_text(json.dumps({"job_name": job_name, "job_id": job_id}), encoding="utf-8")
        self._mark_pending(job_name)
        return JobHandle(job_name, job_id)

    def wait(self, handle: JobHandle, *, running_max_seconds: float,
             total_max_seconds: float, poll_seconds: float = 60.0) -> JobResult:
        job_id = handle.job_id or self._lookup_job_id(handle.job_name)
        if job_id is None:
            raise BackendError("job %s was not found" % handle.job_name)
        entered = self._clock()
        origin: Optional[float] = None
        running_since: Optional[float] = None
        cancel_sent_at: Optional[float] = None
        failures = 0
        # Hard ceiling: the watchdog limits, the cancel grace and a margin. Past it the API has not shown a
        # final state for the whole worst case (unreachable, or a cancel that never goes through): stop
        # polling and let the caller charge the worst case and try one more cancel.
        ceiling = max(total_max_seconds, running_max_seconds) + CANCEL_GRACE_SECONDS + WAIT_MARGIN_SECONDS
        while True:
            job: Optional[Dict[str, Any]] = None
            try:
                job = self._get_job(job_id)
                failures = 0
            except CliError as error:
                failures += 1
                if error.kind != "transient" and failures >= 5:
                    raise
            now = self._clock()
            if job is not None:
                status = job.get("status") or {}
                state = str(status.get("state") or "").upper()
                if origin is None:
                    origin = parse_time((job.get("metadata") or {}).get("created_at"))
                if state in _TERMINAL:
                    result = self._result(handle.job_name, job_id, job, cancel_sent_at is not None)
                    if result.started_at is None:
                        self._clear_pending(handle.job_name)          # it never ran: it exported nothing
                    return result
                if state == "RUNNING" and running_since is None:
                    running_since = parse_time(status.get("started_at")) or now
            if now - (origin or entered) > ceiling:
                raise BackendError(
                    "gave up waiting for job %s after %d s without a final state from the API; it may still "
                    "be running, so check the console" % (handle.job_name, now - (origin or entered)))
            if cancel_sent_at is None:
                over_running = running_since is not None and now - running_since > running_max_seconds
                over_total = now - (origin or entered) > total_max_seconds
                if over_running or over_total:
                    try:
                        self._cli.text(["ai", "job", "cancel", job_id])
                        cancel_sent_at = now
                    except BackendError:
                        pass  # try again on the next poll
            elif now - cancel_sent_at > CANCEL_GRACE_SECONDS:
                return JobResult(handle.job_name, job_id, "TIMEOUT", "watchdog_cancel", None, None, None)
            self._sleep(poll_seconds)

    def download(self, handle: JobHandle, dest: Path) -> Path:
        state = self._state
        if not state.get("access_key_id") or state.get("access_key_deleted"):
            raise BackendError("no active access key; call prepare() before downloading")
        info = self._cli.json(["iam", "v2", "access-key", "get", "--id", state["access_key_id"],
                               "--format", "json"])
        status = info.get("status") if isinstance(info, dict) else None
        key_id = status.get("aws_access_key_id") if isinstance(status, dict) else None
        secret = status.get("secret") if isinstance(status, dict) else None
        if not key_id or not secret:
            raise BackendError("the access key response did not contain usable credentials")
        endpoint = "https://storage.%s.nebius.cloud" % self.region
        client = self._s3_factory(endpoint, self.region, key_id, secret)
        del secret, status, info
        prefix = "faultline-runs/%s/" % handle.job_name
        bucket = state["bucket_name"]
        objects = self._list_objects(client, bucket, prefix)
        if not objects:
            raise BackendError("no evidence found under %s in the results bucket" % prefix)
        total = sum(size for _, size in objects)
        if total > self._max_download_bytes:
            raise BackendError("the job export is %d bytes, over the %d byte limit" % (
                total, self._max_download_bytes))
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        for key, size in objects:
            relative = key[len(prefix):]
            if not relative or relative.endswith("/"):
                continue
            parts = relative.split("/")
            if (key.startswith("/") or "\\" in relative or ":" in relative
                    or any(part in ("", ".", "..") for part in parts)):
                raise BackendError("refusing unsafe object key in the job export")
            target = dest.joinpath(*parts)
            if root not in target.resolve().parents:
                raise BackendError("refusing unsafe object key in the job export")
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            client.download_file(bucket, key, str(partial))
            if partial.stat().st_size != size:
                partial.unlink()
                raise BackendError("size mismatch downloading %s" % relative)
            partial.replace(target)
        self._clear_pending(handle.job_name)
        return dest

    def logs_tail(self, handle: JobHandle, lines: int = 200) -> str:
        job_id = handle.job_id
        try:
            job_id = job_id or self._lookup_job_id(handle.job_name)
            if job_id is None:
                return ""
            text = self._cli.text(["ai", "job", "logs", job_id, "--timestamps"], timeout=120.0)
        except BackendError as error:
            return "(logs unavailable: %s)" % error
        return "\n".join(text.splitlines()[-max(1, lines):])

    def lookup(self, job_name: str) -> Optional[JobHandle]:
        """The Job called ``job_name`` or ``None`` when the API says there is none.

        Raises :class:`BackendError` when the API cannot answer, so the caller never mistakes
        an outage for "never created".
        """

        job_id = self._lookup_job_id(job_name)
        return None if job_id is None else JobHandle(job_name, job_id)

    def cancel(self, handle: JobHandle) -> str:
        """Cancel the Job. Returns ``cancelled`` (the API accepted the cancel), ``finished`` (already
        terminal) or ``not_found`` (no such Job); raises when the cancel could not be sent."""

        job_id = handle.job_id or self._lookup_job_id(handle.job_name)
        if job_id is None:
            return "not_found"
        try:
            status = (self._get_job(job_id).get("status") or {})
            if str(status.get("state") or "").upper() in _TERMINAL:
                return "finished"
        except BackendError:
            pass
        try:
            self._cli.text(["ai", "job", "cancel", job_id])
        except CliError as error:
            if error.kind == "notfound":
                return "not_found"
            raise
        return "cancelled"

    def finish(self) -> None:
        """Delete the per-run access key, then try to delete the results bucket.

        The bucket is only attempted when every submitted Job's results were downloaded (or the Job
        never started), and ``storage bucket delete`` succeeds only on an EMPTY bucket: no object is
        ever deleted here. A bucket that is not empty (the normal case, because the Jobs wrote their
        evidence into it) is kept and the outcome is recorded in ``backend-state.json`` and
        :attr:`cleanup_report`. Leftover buckets expire their objects after 1 day (the lifecycle
        rule set at creation) but still count against the per-tenant bucket-policy quota, so remove
        old ``faultline-*`` buckets once they are empty.
        """

        state = self._state
        report: Dict[str, str] = {}
        self.cleanup_report = report
        key_id = state.get("access_key_id")
        if key_id and not state.get("access_key_deleted"):
            try:
                self._cli.text(["iam", "v2", "access-key", "delete", "--id", key_id])
            except CliError as error:
                if error.kind != "notfound":
                    report["access_key"] = "not deleted: " + str(error)
                    raise
            state["access_key_deleted"] = True
            self._save_state()
            report["access_key"] = "deleted"
        elif key_id:
            report["access_key"] = "already deleted"
        self._delete_bucket(report)

    def _delete_bucket(self, report: Dict[str, str]) -> None:
        state = self._state
        bucket_id = state.get("bucket_id")
        if not bucket_id or state.get("bucket_deleted"):
            return
        pending = list(state.get("pending_jobs") or [])
        if pending:
            report["bucket"] = "kept: results of %d Job(s) not downloaded yet" % len(pending)
            return
        try:
            self._cli.text(["storage", "bucket", "delete", "--id", bucket_id])
        except CliError as error:
            if error.kind == "notfound":
                state["bucket_deleted"] = True
                report["bucket"] = "deleted"
            else:
                detail = "not empty" if re.search(r"not.?empty|precondition", str(error), re.IGNORECASE) else "refused"
                outcome = "kept: %s (objects expire after 1 day)" % detail
                state["bucket_delete_outcome"] = outcome + ": " + str(error)[-200:]
                report["bucket"] = outcome
        else:
            state["bucket_deleted"] = True
            report["bucket"] = "deleted"
        if state.get("bucket_deleted"):
            state.pop("bucket_delete_outcome", None)
        self._save_state()

    # -- internals ----------------------------------------------------------

    def _mark_pending(self, job_name: str) -> None:
        pending = self._state.setdefault("pending_jobs", [])
        if job_name not in pending:
            pending.append(job_name)
            self._save_state()

    def _clear_pending(self, job_name: str) -> None:
        pending = self._state.get("pending_jobs") or []
        if job_name in pending:
            pending.remove(job_name)
            self._save_state()

    def _need_prepared(self) -> Path:
        if self._run_dir is None or "bucket_id" not in self._state:
            raise BackendError("backend.prepare() must be called first")
        return self._run_dir

    def _load_state(self) -> None:
        path = self._run_dir / STATE_FILE  # type: ignore[operator]
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise BackendError("%s is unreadable; fix or remove it" % STATE_FILE) from exc
            if isinstance(loaded, dict):
                self._state = loaded

    def _save_state(self) -> None:
        path = self._run_dir / STATE_FILE  # type: ignore[operator]
        partial = path.with_name(path.name + ".part")
        partial.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")
        partial.replace(path)

    def _resolve_project(self) -> str:
        if self.project != "from-cli-profile":
            return self.project
        text = self._cli.text(["config", "get", "parent-id"])
        for line in reversed(text.splitlines()):
            line = line.strip()
            if _PROJECT_ID.match(line):
                return line
        raise BackendError(
            "the nebius CLI profile has no project (parent-id); run `nebius init` or set backend.project")

    def _first_subnet(self, project: str) -> str:
        listing = self._cli.json(["vpc", "subnet", "list", "--parent-id", project, "--format", "json"])
        for item in _items(listing):
            found = (item.get("metadata") or {}).get("id")
            if found:
                return str(found)
        raise BackendError("the project has no VPC subnet; set backend.subnet")

    def _registry_id(self) -> str:
        if self._registry:
            return self._registry
        parts = self._image.split("/")
        if len(parts) < 3 or not re.match(r"cr\.[a-z0-9-]+\.nebius\.cloud\Z", parts[0]):
            raise BackendError("cannot tell the registry from backend.image; set backend.registry")
        return "registry-" + parts[1]

    def _resolve_tag(self) -> str:
        """The registry tag that points at the pinned digest (Jobs reject @sha256 references)."""

        listing = self._cli.json(["registry", "image", "list", "--parent-id", self._registry_id(),
                                  "--format", "json"])
        tags: List[str] = []
        for item in _items(listing):
            if item.get("digest") == self._image_digest:
                tags.extend(str(tag) for tag in (item.get("tags") or []))
        if not tags:
            raise BackendError(
                "no registry tag points at %s; push the image with a tag (faultline image build)"
                % self._image_digest[:19])
        if self._preferred_tag is not None and self._preferred_tag not in tags:
            raise BackendError("registry tag %r does not point at the pinned digest" % self._preferred_tag)
        return self._preferred_tag or sorted(tags)[0]

    def _find_or_create(self, list_args: List[str], create_args: List[str], name: str) -> str:
        found = _by_name(_items(self._cli.json(list_args)), name)
        if found:
            return found
        try:
            created = resource_id(self._cli.json(create_args))
        except CliError as error:
            if error.kind != "exists":
                raise
            created = _by_name(_items(self._cli.json(list_args)), name)
        if not created:
            raise BackendError("could not find or create %s" % name)
        return created

    def _ensure_membership(self, group_id: str, sa_id: str) -> None:
        listed = ""
        try:
            listed = self._cli.text(["iam", "group-membership", "list-members", "--parent-id", group_id,
                                     "--format", "json"])
        except CliError:
            pass  # fall through to create; an existing membership reports AlreadyExists
        if sa_id in listed:
            return
        try:
            self._cli.text(["iam", "group-membership", "create", "--parent-id", group_id,
                            "--member-id", sa_id, "--format", "json"])
        except CliError as error:
            if error.kind != "exists":
                raise

    def _create_bucket(self, name: str, project: str, group_id: str) -> str:
        policy = [{"group_id": group_id, "paths": ["*"], "roles": ["storage.viewer"]}]
        args = ["storage", "bucket", "create", "--parent-id", project, "--name", name,
                "--max-size-bytes", str(BUCKET_MAX_BYTES),
                "--bucket-policy-rules", json.dumps(policy, separators=(",", ":")),
                "--lifecycle-configuration-rules", json.dumps(LIFECYCLE_RULES, separators=(",", ":")),
                "--format", "json"]
        try:
            created = resource_id(self._cli.json(args))
        except CliError as error:
            if error.kind != "exists":
                raise
            created = resource_id(self._cli.json(
                ["storage", "bucket", "get-by-name", "--parent-id", project, "--name", name,
                 "--format", "json"]))
        if not created:
            raise BackendError("bucket creation returned no id")
        return created

    def _prepared_argv(self, job_dir: Path) -> List[str]:
        if not self._prepare_script.is_file():
            raise BackendError("scripts/prepare_serverless_job.py was not found next to the package")
        result = self._script_runner(
            [sys.executable, str(self._prepare_script), "--config", "job-config.json"],
            cwd=job_dir, timeout=60.0)
        if result.returncode != 0:
            message = " ".join((result.stderr or "").split())
            raise BackendError(redact(message[-300:]) or "the Job configuration was rejected")
        try:
            argv = json.loads(result.stdout)
        except ValueError as exc:
            raise BackendError("prepare_serverless_job.py printed no argument list") from exc
        if (not isinstance(argv, list) or argv[:4] != ["nebius", "ai", "job", "create"]
                or argv[-2:] != ["--dry-run", "--async"]):
            raise BackendError("prepare_serverless_job.py returned an unexpected command")
        return [str(part) for part in argv]

    def _create_job(self, job_name: str, create: List[str], job_dir: Path) -> str:
        """Create once; recover the id from the output or by name.

        The create command is retried only when it failed (nonzero exit) and the Job provably does
        not exist. After an exit-0 create it is NEVER run again: the id is read from the output
        (JSON, or the ``Job ID: aijob-...`` text the CLI printed on October 13) or the Job is
        looked up by name a bounded number of times.
        """

        last: Optional[BackendError] = None
        for attempt in range(3):
            if attempt:
                self._sleep(10.0 * attempt)
            try:
                text = self._cli.text(create, cwd=job_dir, timeout=SUBMIT_TIMEOUT_SECONDS, tries=1)
            except CliError as error:
                last = error
                if error.kind not in ("transient", "exists"):
                    raise
                found = self._lookup_job_id(job_name)      # may exist although the response was lost
                if found:
                    return found
                continue
            created = _job_id_from_output(text)
            if created:
                return created
            return self._find_created(job_name)
        raise last or BackendError("job %s could not be created" % job_name)

    def _find_created(self, job_name: str) -> str:
        """Look a just-created Job up by name (bounded); never creates anything."""

        for attempt in range(CREATE_LOOKUP_TRIES):
            if attempt:
                self._sleep(5.0 * attempt)
            try:
                found = self._lookup_job_id(job_name)
            except CliError as error:
                if error.kind != "transient":
                    raise
                continue
            if found:
                return found
        raise BackendError("job %s was created (the create command succeeded) but could not be found by name; "
                           "check the console" % job_name)

    def _lookup_job_id(self, job_name: str) -> Optional[str]:
        try:
            payload = self._cli.json(["ai", "job", "get-by-name", "--parent-id",
                                      self._state["project_id"], "--name", job_name, "--format", "json"])
        except CliError as error:
            if error.kind == "notfound":
                return None
            raise
        return resource_id(payload)

    def _get_job(self, job_id: str) -> Dict[str, Any]:
        payload = self._cli.json(["ai", "job", "get", job_id, "--format", "json"])
        if not isinstance(payload, dict):
            raise CliError("nebius ai job get returned an unexpected response", "other")
        return payload

    def _result(self, job_name: str, job_id: str, job: Dict[str, Any], cancelled: bool) -> JobResult:
        status = job.get("status") or {}
        state = _TERMINAL[str(status.get("state")).upper()]
        details = status.get("state_details") or {}
        code = details.get("code") if isinstance(details, dict) else None
        reason = str(code) if code else None
        if cancelled and state == "CANCELLED":
            reason = "watchdog_cancel"
        started = parse_time(status.get("started_at"))
        finished = parse_time(status.get("finished_at"))
        seconds = max(0.0, finished - started) if started is not None and finished is not None else None
        return JobResult(
            job_name=job_name, job_id=job_id, state=state, reason=reason,
            started_at=None if started is None else iso_utc(started),
            finished_at=None if finished is None else iso_utc(finished),
            container_seconds=seconds,
        )

    def _list_objects(self, client: Any, bucket: str, prefix: str) -> List["tuple[str, int]"]:
        last: Optional[Exception] = None
        for attempt in range(3):
            if attempt:
                self._sleep(5.0 * attempt)  # a new key can take a moment to propagate
            try:
                found: List["tuple[str, int]"] = []
                for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
                    for item in page.get("Contents", []):
                        found.append((str(item["Key"]), int(item["Size"])))
                return found
            except Exception as exc:  # boto3 raises botocore errors we cannot import here
                last = exc
        raise BackendError("listing the results bucket failed: %s" % type(last).__name__)
