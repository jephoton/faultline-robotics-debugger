"""Narrow, fail-closed restoration kernel for the accepted LIBERO sample."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import stat
import struct
import unicodedata
import xml.etree.ElementTree as ET

import numpy as np


SOURCE_SHA256 = "42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d"
SOURCE_SIZE = 780_145_352
STATE_SHA256 = "5d4cd69032368d08d09453ef6ed4fa8c4ad697bf152d919eb673837274ba0df1"
STATE_LENGTH = 110
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_XML_ELEMENTS = 50_000
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_CLOSURE_BYTES = 256 * 1024 * 1024
MAX_ASSET_REFERENCES = 128

_CANDIDATE_KEYS = {
    "schema_version",
    "suite",
    "task_id",
    "demo",
    "state_index",
    "source_sha256",
    "state_sha256",
    "state",
    "model_xml",
    "model_xml_sha256",
    "reset_id",
}
_EXPECTED_PROBLEM = {
    "problem_name": "libero_floor_manipulation",
    "domain_name": "robosuite",
    "language_instruction": "pick up the alphabet soup and place it in the basket",
}
_EXPECTED_BDDL = "pick_up_the_alphabet_soup_and_place_it_in_the_basket.bddl"


class ExternalResetError(ValueError):
    """A safe, source-content-free failure at the external reset boundary."""


def _fail(message: str = "invalid external reset candidate") -> None:
    raise ExternalResetError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail()


def _state_sha256(values) -> str:
    try:
        payload = b"".join(struct.pack("<d", float(value)) for value in values)
    except (OverflowError, TypeError, ValueError, struct.error):
        _fail()
    return _sha256(payload)


def _has_control(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _parse_xml(xml: str) -> ET.Element:
    if type(xml) is not str:
        _fail()
    try:
        encoded = xml.encode("utf-8", errors="strict")
    except UnicodeError:
        _fail()
    if not encoded or len(encoded) > MAX_XML_BYTES or b"\x00" in encoded:
        _fail()
    upper = encoded.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        _fail()
    try:
        root = ET.fromstring(encoded)
    except (ET.ParseError, ValueError):
        _fail()
    if root.tag != "mujoco":
        _fail()
    for index, element in enumerate(root.iter(), start=1):
        if index > MAX_XML_ELEMENTS or element.tag == "include":
            _fail()
        if "file" in element.attrib:
            if element.tag not in {"mesh", "texture", "hfield"}:
                _fail()
            filename = element.attrib["file"]
            if not filename or _has_control(filename):
                _fail()
        if element.tag == "compiler":
            for directory_key in ("meshdir", "texturedir", "assetdir"):
                if directory_key not in element.attrib:
                    continue
                if directory_key != "meshdir" or element.attrib[directory_key] != "meshes/":
                    _fail()
    return root


def validate_external_reset(value: dict) -> dict:
    """Validate and detach the one accepted external reset candidate."""
    if type(value) is not dict or set(value) != _CANDIDATE_KEYS:
        _fail()
    fixed = (
        ("schema_version", 1),
        ("suite", "libero_object"),
        ("task_id", 0),
        ("demo", "demo_0"),
        ("state_index", 0),
        ("source_sha256", SOURCE_SHA256),
        ("state_sha256", STATE_SHA256),
    )
    for key, expected in fixed:
        actual = value.get(key)
        if type(actual) is not type(expected) or actual != expected:
            _fail()
    state = value.get("state")
    if type(state) is not list or len(state) != STATE_LENGTH:
        _fail()
    for item in state:
        if type(item) not in (int, float):
            _fail()
        try:
            if not math.isfinite(item):
                _fail()
        except (OverflowError, TypeError, ValueError):
            _fail()
    if _state_sha256(state) != STATE_SHA256:
        _fail()
    xml = value.get("model_xml")
    _parse_xml(xml)
    xml_sha256 = _sha256(xml.encode("utf-8"))
    if type(value.get("model_xml_sha256")) is not str or value["model_xml_sha256"] != xml_sha256:
        _fail()
    reset_id = value.get("reset_id")
    if type(reset_id) is not str:
        _fail()
    unsigned = {key: value[key] for key in _CANDIDATE_KEYS if key != "reset_id"}
    if reset_id != _sha256(_canonical_bytes(unsigned)):
        _fail()
    # Round-tripping gives a recursively detached structure after all strict checks.
    return json.loads(_canonical_bytes(value).decode("utf-8"))


def _is_reparse(stat_result: os.stat_result) -> bool:
    return bool(getattr(stat_result, "st_file_attributes", 0) & 0x400)


def _safe_regular_path(path: Path, *, directory: bool = False) -> os.stat_result:
    try:
        absolute = path.absolute()
        current = absolute
        while True:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise OSError
            if current.parent == current:
                break
            current = current.parent
        result = absolute.stat()
    except (OSError, ValueError):
        raise ExternalResetError("invalid external reset path") from None
    expected = stat.S_ISDIR(result.st_mode) if directory else stat.S_ISREG(result.st_mode)
    if not expected:
        raise ExternalResetError("invalid external reset path")
    return result


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _verified_source(path: Path) -> tuple[int, int, int, int]:
    info = _safe_regular_path(path)
    if info.st_size != SOURCE_SIZE:
        raise ExternalResetError("invalid external reset source")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            if _identity(os.fstat(stream.fileno())) != _identity(info):
                raise OSError
            bytes_read = 0
            while chunk := stream.read(1024 * 1024):
                bytes_read += len(chunk)
                if bytes_read > SOURCE_SIZE:
                    raise OSError
                digest.update(chunk)
            if bytes_read != SOURCE_SIZE:
                raise OSError
    except OSError:
        raise ExternalResetError("invalid external reset source") from None
    if digest.hexdigest() != SOURCE_SHA256:
        raise ExternalResetError("invalid external reset source")
    return _identity(info)


def _same_file_identity(path: Path, expected: tuple[int, int, int, int]) -> bool:
    try:
        return _identity(_safe_regular_path(path)) == expected
    except ExternalResetError:
        return False


def _strict_json(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise ExternalResetError("invalid external reset source") from None
    if type(result) is not dict:
        raise ExternalResetError("invalid external reset source")
    return result


def _text_attr(obj, key: str, limit: int) -> str:
    try:
        attr_id = obj.attrs.get_id(key)
        if attr_id.get_storage_size() > limit:
            raise ValueError
        value = obj.attrs[key]
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="strict")
        if type(value) is not str or len(value.encode("utf-8")) > limit:
            raise ValueError
        return value
    except (KeyError, OSError, TypeError, UnicodeError, ValueError):
        raise ExternalResetError("invalid external reset source") from None


def _hard_child(h5py, group, name: str, expected_type):
    try:
        link = group.get(name, getlink=True)
    except (KeyError, OSError, TypeError, ValueError):
        link = None
    if not isinstance(link, h5py.HardLink):
        raise ExternalResetError("invalid external reset source")
    try:
        child = group.get(name)
    except (KeyError, OSError, TypeError, ValueError):
        child = None
    if not isinstance(child, expected_type):
        raise ExternalResetError("invalid external reset source")
    return child


def _validate_metadata(data) -> None:
    env = _strict_json(_text_attr(data, "env_args", MAX_METADATA_BYTES))
    problem = _strict_json(_text_attr(data, "problem_info", MAX_METADATA_BYTES))
    if any(problem.get(key) != expected for key, expected in _EXPECTED_PROBLEM.items()):
        raise ExternalResetError("invalid external reset source")
    kwargs = env.get("env_kwargs")
    if type(kwargs) is not dict:
        raise ExternalResetError("invalid external reset source")
    expected = (
        (env.get("env_name"), "Libero_Floor_Manipulation"),
        (kwargs.get("robots"), ["Panda"]),
        (kwargs.get("control_freq"), 20),
        (kwargs.get("camera_names"), ["robot0_eye_in_hand", "agentview"]),
        (kwargs.get("camera_heights"), 128),
        (kwargs.get("camera_widths"), 128),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise ExternalResetError("invalid external reset source")
    controller = kwargs.get("controller_configs")
    if type(controller) is not dict or controller.get("type") != "OSC_POSE":
        raise ExternalResetError("invalid external reset source")
    bddl = _text_attr(data, "bddl_file_name", MAX_METADATA_BYTES).replace("\\", "/").rsplit("/", 1)[-1]
    if bddl != _EXPECTED_BDDL or _text_attr(data, "macros_image_convention", MAX_METADATA_BYTES) != "opengl":
        raise ExternalResetError("invalid external reset source")


def _read_state(demo, dataset) -> list[float]:
    dtype = getattr(dataset, "dtype", None)
    if (
        getattr(dataset, "ndim", None) != 2
        or len(getattr(dataset, "shape", ())) != 2
        or dataset.shape[0] < 1
        or dataset.shape[1] != STATE_LENGTH
        or getattr(dtype, "kind", None) != "f"
        or getattr(dtype, "itemsize", None) != 8
        or bool(getattr(dataset, "is_virtual", False))
        or bool(getattr(dataset, "external", ()))
    ):
        raise ExternalResetError("invalid external reset source")
    try:
        row = [float(value) for value in dataset[0]]
        attr_id = demo.attrs.get_id("init_state")
        if attr_id.get_storage_size() > STATE_LENGTH * 8:
            raise ValueError
        initial = [float(value) for value in demo.attrs["init_state"]]
    except (KeyError, OSError, TypeError, ValueError, OverflowError):
        raise ExternalResetError("invalid external reset source") from None
    if len(row) != STATE_LENGTH or len(initial) != STATE_LENGTH:
        raise ExternalResetError("invalid external reset source")
    if any(not math.isfinite(value) for value in row + initial) or row != initial:
        raise ExternalResetError("invalid external reset source")
    if _state_sha256(row) != STATE_SHA256:
        raise ExternalResetError("invalid external reset source")
    return row


def read_external_reset(path: Path) -> dict:
    """Read the sole accepted state/XML pair from a verified local HDF5 file."""
    if not isinstance(path, Path):
        raise ExternalResetError("invalid external reset path")
    try:
        import h5py  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError):
        raise ExternalResetError("h5py is required for external reset reading") from None
    before = _verified_source(path)
    try:
        with h5py.File(path, "r") as handle:
            data = _hard_child(h5py, handle, "data", h5py.Group)
            demo = _hard_child(h5py, data, "demo_0", h5py.Group)
            states = _hard_child(h5py, demo, "states", h5py.Dataset)
            state = _read_state(demo, states)
            xml = _text_attr(demo, "model_file", MAX_XML_BYTES)
            _parse_xml(xml)
            _validate_metadata(data)
    except ExternalResetError:
        raise
    except Exception:
        raise ExternalResetError("invalid external reset source") from None
    if not _same_file_identity(path, before):
        raise ExternalResetError("external reset source changed")
    result = {
        "schema_version": 1,
        "suite": "libero_object",
        "task_id": 0,
        "demo": "demo_0",
        "state_index": 0,
        "source_sha256": SOURCE_SHA256,
        "state_sha256": STATE_SHA256,
        "state": state,
        "model_xml": xml,
        "model_xml_sha256": _sha256(xml.encode("utf-8")),
    }
    result["reset_id"] = _sha256(_canonical_bytes(result))
    return validate_external_reset(result)


_ASSET_MARKERS = {
    "/chiliocosm/assets/": "libero",
    "/robosuite/models/assets/": "robosuite",
}
_RESOLVED_KEYS = {
    "xml",
    "source_xml_sha256",
    "resolved_xml_sha256",
    "assets",
    "asset_closure_sha256",
}


def _asset_reference(filename: str) -> tuple[str, str]:
    if (
        type(filename) is not str
        or not filename
        or "\\" in filename
        or _has_control(filename)
        or "://" in filename
    ):
        raise ExternalResetError("invalid external asset reference")
    matches = [
        (marker, namespace)
        for marker, namespace in _ASSET_MARKERS.items()
        for _ in range(filename.count(marker))
    ]
    if len(matches) != 1:
        raise ExternalResetError("invalid external asset reference")
    marker, namespace = matches[0]
    marker_end = filename.index(marker) + len(marker)
    suffix = filename[marker_end:]
    if not suffix or suffix.startswith("/") or ":" in suffix:
        raise ExternalResetError("invalid external asset reference")
    normalized: list[str] = []
    for part in PurePosixPath(suffix).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized:
                raise ExternalResetError("invalid external asset reference")
            normalized.pop()
        else:
            normalized.append(part)
    if not normalized:
        raise ExternalResetError("invalid external asset reference")
    return namespace, "/".join(normalized)


def _asset_digest(path: Path) -> tuple[str, int]:
    info = _safe_regular_path(path)
    if info.st_size > MAX_ASSET_BYTES:
        raise ExternalResetError("external asset closure exceeds limits")
    before = _identity(info)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            if _identity(os.fstat(stream.fileno())) != before:
                raise OSError
            bytes_read = 0
            while chunk := stream.read(1024 * 1024):
                bytes_read += len(chunk)
                if bytes_read > MAX_ASSET_BYTES:
                    raise ExternalResetError("external asset closure exceeds limits")
                digest.update(chunk)
            if bytes_read != info.st_size:
                raise OSError
    except ExternalResetError:
        raise
    except OSError:
        raise ExternalResetError("invalid external asset") from None
    if not _same_file_identity(path, before):
        raise ExternalResetError("external asset changed")
    return digest.hexdigest(), info.st_size


def _asset_target(root: Path, relative_path: str) -> Path:
    root_absolute = root.absolute()
    target = root_absolute.joinpath(*relative_path.split("/"))
    try:
        if os.path.commonpath((str(root_absolute), str(target.absolute()))) != str(root_absolute):
            raise ValueError
    except ValueError:
        raise ExternalResetError("invalid external asset reference") from None
    _safe_regular_path(target)
    try:
        return target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ExternalResetError("invalid external asset") from None


def resolve_external_assets(xml: str, roots: dict) -> dict:
    """Rewrite recognized source aliases to a bounded installed asset closure."""
    root = _parse_xml(xml)
    if type(roots) is not dict or set(roots) != {"libero", "robosuite"}:
        raise ExternalResetError("invalid external asset roots")
    checked_roots: dict[str, Path] = {}
    for namespace in ("libero", "robosuite"):
        value = roots[namespace]
        if not isinstance(value, Path):
            raise ExternalResetError("invalid external asset roots")
        _safe_regular_path(value, directory=True)
        try:
            checked_roots[namespace] = value.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ExternalResetError("invalid external asset roots") from None

    references = []
    for element in root.iter():
        if "file" not in element.attrib:
            continue
        references.append((element, *_asset_reference(element.attrib["file"])))
        if len(references) > MAX_ASSET_REFERENCES:
            raise ExternalResetError("external asset closure exceeds limits")

    assets_by_key: dict[tuple[str, str], dict] = {}
    targets: dict[tuple[str, str], Path] = {}
    closure_bytes = 0
    for _element, namespace, relative_path in references:
        key = (namespace, relative_path)
        if key in assets_by_key:
            continue
        target = _asset_target(checked_roots[namespace], relative_path)
        digest, byte_count = _asset_digest(target)
        closure_bytes += byte_count
        if closure_bytes > MAX_CLOSURE_BYTES:
            raise ExternalResetError("external asset closure exceeds limits")
        targets[key] = target
        assets_by_key[key] = {
            "namespace": namespace,
            "relative_path": relative_path,
            "sha256": digest,
        }

    for element, namespace, relative_path in references:
        element.attrib["file"] = str(targets[(namespace, relative_path)])
    for element in root.iter("compiler"):
        element.attrib.pop("meshdir", None)

    assets = sorted(
        assets_by_key.values(),
        key=lambda item: (item["namespace"], item["relative_path"], item["sha256"]),
    )
    rewritten = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return {
        "xml": rewritten,
        "source_xml_sha256": _sha256(xml.encode("utf-8")),
        "resolved_xml_sha256": _sha256(rewritten.encode("utf-8")),
        "assets": assets,
        "asset_closure_sha256": _sha256(_canonical_bytes(assets)),
    }


def _xml_shape(root: ET.Element) -> bytes:
    for element in root.iter():
        if "file" in element.attrib:
            element.attrib["file"] = "[resolved-asset]"
        if element.tag == "compiler":
            element.attrib.pop("meshdir", None)
    return ET.tostring(root, encoding="utf-8", short_empty_elements=True)


def _validated_resolved(candidate: dict, resolved: dict) -> dict:
    if type(resolved) is not dict or set(resolved) != _RESOLVED_KEYS:
        raise ExternalResetError("invalid resolved external assets")
    string_keys = ("xml", "source_xml_sha256", "resolved_xml_sha256", "asset_closure_sha256")
    if any(type(resolved.get(key)) is not str for key in string_keys):
        raise ExternalResetError("invalid resolved external assets")
    if resolved["source_xml_sha256"] != candidate["model_xml_sha256"]:
        raise ExternalResetError("invalid resolved external assets")
    try:
        resolved_xml_sha256 = _sha256(resolved["xml"].encode("utf-8", errors="strict"))
    except UnicodeError:
        raise ExternalResetError("invalid resolved external assets") from None
    if resolved_xml_sha256 != resolved["resolved_xml_sha256"]:
        raise ExternalResetError("invalid resolved external assets")
    assets = resolved.get("assets")
    if type(assets) is not list or len(assets) > MAX_ASSET_REFERENCES:
        raise ExternalResetError("invalid resolved external assets")
    canonical_assets = []
    for item in assets:
        if type(item) is not dict or set(item) != {"namespace", "relative_path", "sha256"}:
            raise ExternalResetError("invalid resolved external assets")
        namespace = item.get("namespace")
        relative_path = item.get("relative_path")
        digest = item.get("sha256")
        if (
            type(namespace) is not str
            or namespace not in {"libero", "robosuite"}
            or type(relative_path) is not str
            or type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ExternalResetError("invalid resolved external assets")
        canonical_assets.append(dict(item))
    expected_order = sorted(
        canonical_assets,
        key=lambda item: (item["namespace"], item["relative_path"], item["sha256"]),
    )
    if canonical_assets != expected_order or len({(item["namespace"], item["relative_path"]) for item in assets}) != len(assets):
        raise ExternalResetError("invalid resolved external assets")
    if _sha256(_canonical_bytes(canonical_assets)) != resolved["asset_closure_sha256"]:
        raise ExternalResetError("invalid resolved external assets")

    source_root = _parse_xml(candidate["model_xml"])
    resolved_root = _parse_xml(resolved["xml"])
    source_files = [element.attrib["file"] for element in source_root.iter() if "file" in element.attrib]
    resolved_files = [element.attrib["file"] for element in resolved_root.iter() if "file" in element.attrib]
    if len(source_files) != len(resolved_files) or len(source_files) > MAX_ASSET_REFERENCES:
        raise ExternalResetError("invalid resolved external assets")
    if _xml_shape(source_root) != _xml_shape(resolved_root):
        raise ExternalResetError("invalid resolved external assets")

    records = {(item["namespace"], item["relative_path"]): item for item in canonical_assets}
    seen = set()
    total_bytes = 0
    for source_file, resolved_file in zip(source_files, resolved_files):
        try:
            namespace, relative_path = _asset_reference(source_file)
            target = Path(resolved_file)
            if not target.is_absolute():
                raise ValueError
            relative_parts = tuple(relative_path.split("/"))
            if tuple(target.parts[-len(relative_parts) :]) != relative_parts:
                raise ValueError
            record = records[(namespace, relative_path)]
            digest, byte_count = _asset_digest(target)
        except (ExternalResetError, KeyError, OSError, TypeError, ValueError):
            raise ExternalResetError("invalid resolved external assets") from None
        if digest != record["sha256"]:
            raise ExternalResetError("invalid resolved external assets")
        key = (namespace, relative_path)
        if key not in seen:
            total_bytes += byte_count
        seen.add(key)
        if total_bytes > MAX_CLOSURE_BYTES:
            raise ExternalResetError("invalid resolved external assets")
    if seen != set(records):
        raise ExternalResetError("invalid resolved external assets")
    return {
        "xml": resolved["xml"],
        "source_xml_sha256": resolved["source_xml_sha256"],
        "resolved_xml_sha256": resolved["resolved_xml_sha256"],
        "asset_closure_sha256": resolved["asset_closure_sha256"],
    }


def _sim_state(value, error: str) -> list[float]:
    try:
        array = np.asarray(value)
        if array.dtype.kind not in "fiu" or array.size != STATE_LENGTH:
            raise ValueError
        flattened = [float(item) for item in array.reshape(-1)]
    except (OverflowError, TypeError, ValueError):
        raise ExternalResetError(error) from None
    if any(not math.isfinite(item) for item in flattened):
        raise ExternalResetError(error)
    return flattened


def restore_external_reset(env, candidate: dict, resolved: dict) -> dict:
    """Restore one validated external state and collect ten-step settle evidence."""
    candidate = validate_external_reset(candidate)
    checked = _validated_resolved(candidate, resolved)
    try:
        env.reset()
        env.reset_from_xml_string(checked["xml"])
        dimension_state = _sim_state(env.get_sim_state(), "external simulator state dimension mismatch")
    except ExternalResetError:
        raise
    except Exception:
        raise ExternalResetError("external simulator reset failed") from None
    if len(dimension_state) != STATE_LENGTH:
        raise ExternalResetError("external simulator state dimension mismatch")
    try:
        env.set_init_state(list(candidate["state"]))
        pre_state = _sim_state(env.get_sim_state(), "external simulator state mismatch")
    except ExternalResetError:
        raise
    except Exception:
        raise ExternalResetError("external simulator state restore failed") from None
    pre_hash = _state_sha256(pre_state)
    if pre_hash != candidate["state_sha256"]:
        raise ExternalResetError("external simulator state mismatch")
    observation = None
    try:
        for _ in range(10):
            step_result = env.step([0, 0, 0, 0, 0, 0, -1])
            if not isinstance(step_result, (tuple, list)) or not step_result:
                raise ValueError
            observation = step_result[0]
    except Exception:
        raise ExternalResetError("external simulator settling failed") from None
    try:
        post_state = _sim_state(env.get_sim_state(), "invalid settled simulator state")
    except ExternalResetError:
        raise
    except Exception:
        raise ExternalResetError("invalid settled simulator state") from None
    post_hash = _state_sha256(post_state)
    return {
        "observation": observation,
        "reset_metadata": {
            "reset_id": candidate["reset_id"],
            "source_sha256": candidate["source_sha256"],
            "state_sha256": candidate["state_sha256"],
            "source_xml_sha256": checked["source_xml_sha256"],
            "resolved_xml_sha256": checked["resolved_xml_sha256"],
            "asset_closure_sha256": checked["asset_closure_sha256"],
            "pre_settle_state_sha256": pre_hash,
            "post_settle_state_sha256": post_hash,
            "settling_steps": 10,
            "restoration_verified": False,
        },
    }
