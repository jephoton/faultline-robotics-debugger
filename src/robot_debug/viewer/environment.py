"""The setup checklist behind ``GET /api/environment`` (ADR 0033).

Each check says whether one thing a run needs is in place and, when it is not, what to do. The answers are
names and presence only: the Token Factory key is looked for but never read into a response, a pinned image is
reported as "set", and no account, project or registry id is ever returned. The one slow check (``nebius iam
whoami``) is cached for 60 seconds and given 20 seconds to answer.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from robot_debug.backends import BackendError, run_command
from robot_debug.backends.nebius import resolve_launcher
from robot_debug.viewer.specs import SpecService

WHOAMI_TIMEOUT_SECONDS = 20.0
WHOAMI_CACHE_SECONDS = 60.0
KEY_NAME = "NEBIUS_API_KEY"
_ASSIGNMENT = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def dotenv_has(path: Path, name: str) -> bool:
    """Whether ``name`` is set to something in a dotenv file. The value is never returned."""

    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        found = _ASSIGNMENT.fullmatch(line)
        if found and found.group(1) == name:
            value = found.group(2).split(" #", 1)[0].strip().strip("'\"")
            if value:
                return True
    return False


class Environment:
    """The checks, with every outside effect injectable."""

    def __init__(self, specs: SpecService, *, env_file: Path = Path(".env"),
                 environ: Optional[Mapping[str, str]] = None, runner: Callable[..., Any] = run_command,
                 which: Callable[[str], Optional[str]] = shutil.which,
                 launcher_factory: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.specs, self.env_file = specs, Path(env_file)
        self.environ = os.environ if environ is None else environ
        self.runner, self.which, self.clock = runner, which, clock
        self._launcher_factory = launcher_factory or (lambda: resolve_launcher(None, which=which))
        self._cache: Optional[Dict[str, Any]] = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    # -- the checks --------------------------------------------------------------------------------

    def _nebius(self) -> Dict[str, Any]:
        """Installed and signed in. The identity ``whoami`` prints is thrown away."""

        with self._lock:
            now = self.clock()
            if self._cache is not None and now - self._cached_at < WHOAMI_CACHE_SECONDS:
                return dict(self._cache)
            result = self._ask_nebius()
            self._cache, self._cached_at = result, now
            return dict(result)

    def _ask_nebius(self) -> Dict[str, Any]:
        try:
            launcher = self._launcher_factory()
        except BackendError:
            return {"key": "nebius_cli", "ok": False, "detail": "The nebius CLI was not found.",
                    "fix": "Install the Nebius CLI (https://docs.nebius.com/cli) and put it on PATH, "
                           "then sign in with `nebius init`."}
        try:
            answer = self.runner(launcher.argv(["iam", "whoami"]), cwd=None, timeout=WHOAMI_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return {"key": "nebius_cli", "ok": False,
                    "detail": "The nebius CLI did not answer within {:g} seconds.".format(WHOAMI_TIMEOUT_SECONDS),
                    "fix": "Run `nebius iam whoami` in a terminal; if it asks you to sign in, do that, then check again."}
        except OSError:
            return {"key": "nebius_cli", "ok": False, "detail": "The nebius CLI could not be started.",
                    "fix": "Check the installation by running `nebius --version` in a terminal."}
        if getattr(answer, "returncode", 1) == 0:
            return {"key": "nebius_cli", "ok": True, "detail": "signed in"}
        return {"key": "nebius_cli", "ok": False, "detail": "The nebius CLI is not signed in, or the sign-in expired.",
                "fix": "Run `nebius iam whoami` in a terminal and sign in, then check again (a stopped run "
                       "continues with Resume)."}

    def _docker(self) -> Dict[str, Any]:
        found = self.which("docker") is not None
        check: Dict[str, Any] = {"key": "docker", "ok": found, "optional": True,
                                 "detail": "Docker is available." if found else "Docker was not found."}
        if not found:
            check["fix"] = "Docker is only needed to build the simulator image (`faultline image build`)."
        return check

    def _token_factory(self) -> Dict[str, Any]:
        present = bool(self.environ.get(KEY_NAME)) or dotenv_has(self.env_file, KEY_NAME)
        check: Dict[str, Any] = {"key": "token_factory_key", "ok": present,
                                 "detail": "{} found".format(KEY_NAME) if present
                                 else "{} not found in .env".format(KEY_NAME)}
        if not present:
            check["fix"] = ("Add a line {}=<your Token Factory key> to the .env file in the project folder. "
                            "It stays on this machine. Paraphrase mode and Nemotron's reading need it.").format(KEY_NAME)
        return check

    def _spec_template(self) -> Dict[str, Any]:
        local = self.specs.local_backend()
        if local is None:
            return {"key": "spec_template", "ok": False,
                    "detail": "No local spec pins an image and a Hugging Face secret name.",
                    "fix": "Copy a spec from configs/specs into artifacts/specs-local, fill backend.image and "
                           "backend.hf_token_secret (docs/setup/diagnose.md), then check again."}
        return {"key": "spec_template", "ok": True,
                "detail": "Pinned image set; Hugging Face secret name: {}".format(local.get("hf_token_secret"))}

    def check(self) -> Dict[str, List[Dict[str, Any]]]:
        return {"checks": [self._nebius(), self._token_factory(), self._spec_template(), self._docker()]}
