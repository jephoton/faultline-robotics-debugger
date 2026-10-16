"""The static gallery: ``faultline export`` (ADR 0033; this prepares the files, publishing them is a separate decision).

The export is a folder of plain files that any static host can serve: the front-end bundle, the library as JSON
(``data/session.json``, ``data/library.json``, ``data/library/<id>.json``, the same shapes the local server
answers with), the videos and case files under ``media/``, and a ``vercel.json`` that sends app routes to
``index.html``. It has no controls: ``data/session.json`` says ``mode: static``.

Everything written passes through the public projection (``Library(local=False)``): no run folder names, Job
ids, project, bucket or registry names, access keys or absolute paths. As a last guard the finished JSON and
text are scanned for such patterns and the export is refused (and removed) if one is found.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import robot_debug
from robot_debug.viewer import processes
from robot_debug.viewer.api import package_version
from robot_debug.viewer.library import Library

VERCEL_CONFIG = {"rewrites": [{"source": "/((?!assets/|data/|media/).*)", "destination": "/index.html"}]}
FORBIDDEN = {
    # A UNC path is \\server\share (JSON doubles each backslash); a lone "\(" in a LaTeX title is not one.
    "an absolute path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?!/)|\\{2,}[A-Za-z0-9._$-]+\\+[A-Za-z0-9._$-]|"
                                   r"(?<![\w.])/(?:home|Users|tmp|var|mnt|opt|root|private|srv|workspace)/|"
                                   r"(?<![\w.~/])~/[A-Za-z0-9._-]"),
    "a Job id": re.compile(r"\baijob-[a-z0-9]{6,}"),
    "a project id": re.compile(r"\bproject-[a-z0-9]{6,}"),
    "a registry, subnet or account id": re.compile(
        r"\b(?:registry|vpcsubnet|serviceaccount|accesskey)-[a-z0-9]{6,}"),
    "a registry address": re.compile(r"nebius\.cloud"),
    "a run folder name": re.compile(r"-\d{8}T\d{6}Z\b"),
    "backend state": re.compile(r"backend-state|\"bucket_name\"|\"access_key"),
    # The results bucket is named faultline-<diagnosis name>-<6 hex digits> (backends.nebius).
    "a results bucket name": re.compile(r"(?<![\w-])faultline-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{6}(?![\w-])"),
    # The Hugging Face secret: the usual names (<prefix>-hf-token); the specs' own names are added per export.
    "a secret name": re.compile(r"(?<![\w-])(?:[a-z0-9]+(?:-[a-z0-9]+)*-)?hf-token(?![\w-])"),
    "an email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
}
_SECRET_KEY = re.compile(r"^\s*hf_token_secret:\s*[\"']?([A-Za-z0-9._-]+)", re.MULTILINE)
TEXT_SUFFIXES = (".json", ".md")


class ExportError(ValueError):
    """The export was refused; the message says why and never holds a secret."""


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def check_output(out: Path, force: bool) -> None:
    """Refuse an output folder inside the package source or one that already holds something (without force)."""

    source = Path(robot_debug.__file__).resolve().parents[1]
    if _inside(out, source):
        raise ExportError("The output folder is inside the package's src folder; choose a folder outside the source tree.")
    if out.exists() and not out.is_dir():
        raise ExportError("The output path exists and is not a folder.")
    if out.is_dir() and any(out.iterdir()) and not force:
        raise ExportError("The output folder is not empty; use --force to replace a previous export in it.")


def scan_public(text: str, secret_names: Sequence[str] = ()) -> Optional[str]:
    """The name of the first kind of private detail found in ``text``, else ``None``. ``secret_names`` are
    the Hugging Face secret names of this machine's specs (see :func:`local_secret_names`)."""

    for label, pattern in FORBIDDEN.items():
        if pattern.search(text):
            return label
    for name in secret_names:
        if name and name in text:
            return "a secret name"
    return None


def local_secret_names(artifact_root: Path, runs_root: Path) -> List[str]:
    """The ``backend.hf_token_secret`` values of the specs kept on this machine (run folders and the panel's
    saved specs), so a name that does not look like ``*-hf-token`` is still refused."""

    names = set()
    candidates = list(Path(runs_root).glob("*/spec.yaml")) + list((Path(artifact_root) / "specs-ui").glob("*/spec.yaml"))
    for path in candidates:
        try:
            names.update(_SECRET_KEY.findall(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError):
            continue
    return sorted(names)


def _write_json(path: Path, value: Any, secrets: Sequence[str] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    leak = scan_public(text, secrets)
    if leak is not None:
        raise ExportError("Refused: {} would be exported in {}.".format(leak, path.name))
    path.write_text(text, encoding="utf-8", newline="\n")


def _select(library: Library, wanted: Sequence[str]) -> List[Dict[str, Any]]:
    items = library.list()["items"]
    if not wanted:
        return [item for item in items if not item["id"].startswith("r-")]
    chosen: List[Dict[str, Any]] = []
    for ask in wanted:
        matches = [i for i in items if i["id"] == ask or (i["case_id"] and i["case_id"] == ask)
                   or (len(ask) >= 8 and i["case_id"] and i["case_id"].startswith(ask.lower()))]
        if len(matches) != 1:
            raise ExportError("No single case matches {!r}.".format(ask[:24]) if not matches
                              else "{!r} matches more than one case; give more of its id.".format(ask[:24]))
        if matches[0] not in chosen:
            chosen.append(matches[0])
    return chosen


def public_id(item_id: str) -> str:
    """A run-based id (``r-<run folder>``) would publish the folder name: the export uses a digest instead."""

    if item_id.startswith("r-"):
        return "r-" + hashlib.sha256(item_id[2:].encode("utf-8")).hexdigest()[:12]
    return item_id


def _copy(source: Optional[Path], target: Path, scrub: bool = False, secrets: Sequence[str] = ()) -> bool:
    if source is None or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix in TEXT_SUFFIXES:
        text = source.read_text(encoding="utf-8")
        text = processes.scrub_text(text) if scrub else text
        leak = scan_public(text, secrets)
        if leak is not None:
            raise ExportError("Refused: {} would be exported in {}.".format(leak, target.name))
        target.write_text(text, encoding="utf-8", newline="\n")
    else:
        shutil.copyfile(str(source), str(target))
    return True


def _media_source(library: Library, url: Optional[str]) -> Optional[Path]:
    """The file behind a ``/media/<relative to the artifacts>`` URL, only if it is under the artifacts."""

    if not url or not url.startswith("/media/"):
        return None
    candidate = (library.artifact_root / url[len("/media/"):]).resolve()
    return candidate if _inside(candidate, library.artifact_root) and candidate.is_file() else None


def _rewrite_media(library: Library, detail: Dict[str, Any], out: Path, identifier: str,
                   secrets: Sequence[str] = ()) -> None:
    """Copy this item's videos and files into ``media/<id>/`` and point the JSON at the copies."""

    base = out / "media" / identifier
    for video in detail.get("videos") or []:
        copied = _copy(_media_source(library, video.get("url")), base / "videos" / (video["role"] + ".mp4"),
                       secrets=secrets)
        video["url"] = "/media/{}/videos/{}.mp4".format(identifier, video["role"]) if copied else None
    block = detail.get("occlusion")
    if block:
        for episode in block["episodes"]:
            name = "episodes/{}.mp4".format(episode["episode_id"])
            copied = _copy(_media_source(library, episode.get("url")), base / name, secrets=secrets)
            episode["url"] = "/media/{}/{}".format(identifier, name) if copied else None
    kept = []
    for entry in detail.get("files") or []:
        try:
            source = library.file_path(detail["id"], entry["name"])
        except (KeyError, ValueError, FileNotFoundError):
            continue
        if _copy(source, base / "files" / entry["name"], scrub=entry["name"] == "report.md", secrets=secrets):
            kept.append({"name": entry["name"], "url": "/media/{}/files/{}".format(identifier, entry["name"])})
    detail["files"] = kept


def export_gallery(out: Path, artifact_root: Path, *, runs_root: Optional[Path] = None,
                   cases: Sequence[str] = (), force: bool = False, app_root: Optional[Path] = None,
                   library: Optional[Library] = None) -> Dict[str, Any]:
    """Write the static gallery to ``out``; returns ``{"cases": n, "videos": n, "out": ...}``."""

    out = Path(out)
    app = Path(app_root) if app_root else Path(__file__).with_name("app")
    if not (app / "index.html").is_file():
        raise ExportError("The front-end bundle is missing; build it with `npm run build` in web/.")
    check_output(out, force)
    library = library or Library(Path(artifact_root), runs_root=runs_root, local=False)
    selected = _select(library, list(cases))
    secrets = local_secret_names(Path(artifact_root), Path(runs_root) if runs_root else Path(artifact_root) / "runs")
    if force and out.is_dir():
        for entry in list(app.iterdir()) + [Path(n) for n in ("data", "media", "vercel.json")]:
            target = out / entry.name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(str(target))
            elif target.exists():
                target.unlink()
    created_out = not out.exists()
    out.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(str(app), str(out), dirs_exist_ok=True)
        _write_json(out / "data" / "session.json", {
            "api_version": 1, "mode": "static", "controls": False, "token": None, "version": package_version()})
        listing, warnings = [], []
        for item in selected:
            try:
                detail = library.detail(item["id"])
            except (KeyError, ValueError, OSError):          # e.g. the old case's evidence moved: skip it, say so
                warnings.append("A case could not be read and was left out of the export.")
                continue
            identifier = public_id(item["id"])
            _rewrite_media(library, detail, out, identifier, secrets)       # while detail["id"] still names the source
            detail["id"] = identifier
            detail["run"] = None
            _write_json(out / "data" / "library" / (identifier + ".json"), detail, secrets)
            summary = {k: v for k, v in detail.items() if k in item}
            listing.append(summary)
        _write_json(out / "data" / "library.json", {"items": listing, "warnings": warnings}, secrets)
        _write_json(out / "vercel.json", VERCEL_CONFIG)
    except BaseException:
        if created_out:
            shutil.rmtree(str(out), ignore_errors=True)
        else:
            for name in ("data", "media", "vercel.json"):
                target = out / name
                if target.is_dir():
                    shutil.rmtree(str(target), ignore_errors=True)
                elif target.exists():
                    target.unlink()
        raise
    videos = sum(1 for _ in (out / "media").rglob("*.mp4")) if (out / "media").is_dir() else 0
    return {"cases": len(listing), "videos": videos, "out": str(out), "skipped": len(warnings)}
