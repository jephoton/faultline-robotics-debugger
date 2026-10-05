"""Narrow, fail-closed restoration kernel for the accepted LIBERO sample."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import xml.etree.ElementTree as ET


SOURCE_SHA256 = "42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d"
SOURCE_SIZE = 780_145_352
STATE_SHA256 = "5d4cd69032368d08d09453ef6ed4fa8c4ad697bf152d919eb673837274ba0df1"
STATE_LENGTH = 110
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_XML_ELEMENTS = 50_000

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
    "problem_name": "pick_up_the_alphabet_soup_and_place_it_in_the_basket",
    "domain_name": "libero_object",
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
            if not filename or any(ord(character) < 32 for character in filename):
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
        if type(item) not in (int, float) or not math.isfinite(item):
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
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
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
        child = group.get(name)
    except (KeyError, OSError, TypeError, ValueError):
        child = None
        link = None
    if not isinstance(link, h5py.HardLink) or not isinstance(child, expected_type):
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
        (kwargs.get("camera_names"), ["agentview", "robot0_eye_in_hand"]),
        (kwargs.get("camera_heights"), 128),
        (kwargs.get("camera_widths"), 128),
        ((kwargs.get("controller_configs") or {}).get("type"), "OSC_POSE"),
    )
    if any(actual != wanted for actual, wanted in expected):
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
    before = _verified_source(path)
    try:
        import h5py  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError):
        raise ExternalResetError("h5py is required for external reset reading") from None
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
    except (OSError, TypeError, ValueError):
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
