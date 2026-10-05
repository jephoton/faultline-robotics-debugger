from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from robot_debug.external_reset import (
    ExternalResetError,
    read_external_reset,
    validate_external_reset,
)


SOURCE_SHA256 = "42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d"
STATE_SHA256 = "5d4cd69032368d08d09453ef6ed4fa8c4ad697bf152d919eb673837274ba0df1"
XML = '<mujoco><asset><mesh file="/chiliocosm/assets/meshes/a.obj"/></asset></mujoco>'


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def candidate(**changes):
    value = {
        "schema_version": 1,
        "suite": "libero_object",
        "task_id": 0,
        "demo": "demo_0",
        "state_index": 0,
        "source_sha256": SOURCE_SHA256,
        "state_sha256": STATE_SHA256,
        "state": [float(index) for index in range(110)],
        "model_xml": XML,
        "model_xml_sha256": _sha(XML.encode("utf-8")),
    }
    value.update(changes)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    value["reset_id"] = _sha(payload)
    return value


class FakeHardLink:
    pass


class FakeSoftLink:
    pass


class FakeAttrs(dict):
    class Id:
        def __init__(self, value):
            self.shape = getattr(value, "shape", ())
            self.dtype = getattr(value, "dtype", types.SimpleNamespace(kind="O"))
            self._value = value

        def get_storage_size(self):
            if isinstance(self._value, str):
                return len(self._value.encode("utf-8"))
            return getattr(self._value, "nbytes", 8)

    def get_id(self, key):
        return self.Id(self[key])


class FakeDataset:
    def __init__(self, row, *, link=None, virtual=False, external=()):
        self._row = row
        self.shape = (1, len(row))
        self.ndim = 2
        self.dtype = types.SimpleNamespace(kind="f", itemsize=8, byteorder="<")
        self.is_virtual = virtual
        self.external = external
        self.link = link or FakeHardLink()

    def __getitem__(self, index):
        if index != 0:
            raise AssertionError("reader may only access states[0]")
        return self._row


class FakeGroup:
    def __init__(self, children=None, attrs=None, *, link=None):
        self.children = children or {}
        self.attrs = FakeAttrs(attrs or {})
        self.link = link or FakeHardLink()

    def get(self, name, default=None, *, getlink=False):
        child = self.children.get(name)
        if child is None:
            return default
        return child.link if getlink else child


class FakeFile(FakeGroup):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def fake_h5py(handle):
    return types.SimpleNamespace(
        HardLink=FakeHardLink,
        Dataset=FakeDataset,
        Group=FakeGroup,
        File=lambda *_args, **_kwargs: handle,
    )


def fake_source(state=None):
    state = state or [float(index) for index in range(110)]
    demo = FakeGroup(
        {"states": FakeDataset(state)},
        {"init_state": state, "model_file": XML},
    )
    data = FakeGroup(
        {"demo_0": demo},
        {
            "env_args": json.dumps(
                {
                    "env_name": "Libero_Floor_Manipulation",
                    "env_kwargs": {
                        "robots": ["Panda"],
                        "controller_configs": {"type": "OSC_POSE"},
                        "control_freq": 20,
                        "camera_names": ["agentview", "robot0_eye_in_hand"],
                        "camera_heights": 128,
                        "camera_widths": 128,
                    },
                }
            ),
            "problem_info": json.dumps(
                {
                    "problem_name": "pick_up_the_alphabet_soup_and_place_it_in_the_basket",
                    "domain_name": "libero_object",
                    "language_instruction": "pick up the alphabet soup and place it in the basket",
                }
            ),
            "bddl_file_name": "/untrusted/pick_up_the_alphabet_soup_and_place_it_in_the_basket.bddl",
            "macros_image_convention": "opengl",
        },
    )
    return FakeFile({"data": data})


class CandidateValidationTests(unittest.TestCase):
    def test_valid_candidate_is_detached_and_canonical(self):
        value = candidate()
        with mock.patch("robot_debug.external_reset._state_sha256", return_value=STATE_SHA256):
            result = validate_external_reset(value)
        self.assertEqual(result, value)
        self.assertIsNot(result, value)
        self.assertIsNot(result["state"], value["state"])

    def test_rejects_unknown_or_missing_keys_and_boolean_integers(self):
        cases = [
            {**candidate(), "extra": 1},
            {key: value for key, value in candidate().items() if key != "demo"},
            candidate(schema_version=True),
            candidate(state=[False] + [0.0] * 109),
        ]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ExternalResetError, "invalid external reset candidate"):
                    validate_external_reset(value)

    def test_rejects_nonfinite_wrong_length_and_cycles(self):
        cycle = candidate()
        cycle["state"].append(cycle)
        nonfinite = candidate()
        nonfinite["state"][0] = math.inf
        for value in (candidate(state=[0.0] * 109), nonfinite, cycle):
            with self.subTest(kind=type(value["state"]).__name__):
                with self.assertRaises(ExternalResetError):
                    validate_external_reset(value)

    def test_rejects_forged_hashes_and_oversized_or_unsafe_xml(self):
        unsafe = [
            "<!DOCTYPE mujoco><mujoco/>",
            "<!ENTITY x 'y'><mujoco/>",
            "<include file='x'/>",
            "<not-mujoco/>",
            "<mujoco>" + ("x" * (2 * 1024 * 1024)) + "</mujoco>",
        ]
        values = [
            candidate(source_sha256="0" * 64),
            candidate(state_sha256="0" * 64),
            candidate(model_xml_sha256="0" * 64),
            candidate(reset_id="0" * 64),
        ] + [candidate(model_xml=xml) for xml in unsafe]
        for value in values:
            with self.subTest(field=value.get("model_xml", "hash")[:30]):
                with self.assertRaises(ExternalResetError):
                    validate_external_reset(value)


class SourceReaderTests(unittest.TestCase):
    def read_fixture(self, handle, *, state_hash=STATE_SHA256):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.hdf5"
            path.write_bytes(b"fixture")
            identity = (1, 2, 780145352, 3)
            with (
                mock.patch.dict(sys.modules, {"h5py": fake_h5py(handle)}),
                mock.patch("robot_debug.external_reset._verified_source", return_value=identity),
                mock.patch("robot_debug.external_reset._same_file_identity", return_value=True),
                mock.patch("robot_debug.external_reset._state_sha256", return_value=state_hash),
            ):
                return read_external_reset(path)

    def test_reads_only_first_hard_linked_state_and_required_metadata(self):
        result = self.read_fixture(fake_source())
        self.assertEqual(result["reset_id"], candidate()["reset_id"])
        self.assertEqual(len(result["state"]), 110)

    def test_rejects_soft_virtual_and_external_storage_states(self):
        for dataset in (
            FakeDataset([0.0] * 110, link=FakeSoftLink()),
            FakeDataset([0.0] * 110, virtual=True),
            FakeDataset([0.0] * 110, external=(("elsewhere", 0, 8),)),
        ):
            handle = fake_source()
            handle.children["data"].children["demo_0"].children["states"] = dataset
            with self.subTest(dataset=dataset):
                with self.assertRaisesRegex(ExternalResetError, "invalid external reset source"):
                    self.read_fixture(handle)

    def test_rejects_mismatched_init_state_and_metadata(self):
        mismatch = fake_source()
        mismatch.children["data"].children["demo_0"].attrs["init_state"] = [9.0] * 110
        bad_metadata = fake_source()
        bad_metadata.children["data"].attrs["macros_image_convention"] = "opencv"
        for handle in (mismatch, bad_metadata):
            with self.assertRaises(ExternalResetError):
                self.read_fixture(handle)

    def test_rejects_changed_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.hdf5"
            path.write_bytes(b"fixture")
            with (
                mock.patch.dict(sys.modules, {"h5py": fake_h5py(fake_source())}),
                mock.patch("robot_debug.external_reset._verified_source", return_value=(1, 2, 780145352, 3)),
                mock.patch("robot_debug.external_reset._same_file_identity", return_value=False),
                mock.patch("robot_debug.external_reset._state_sha256", return_value=STATE_SHA256),
            ):
                with self.assertRaisesRegex(ExternalResetError, "external reset source changed"):
                    read_external_reset(path)

    def test_missing_h5py_has_fixed_safe_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.hdf5"
            path.write_bytes(b"fixture")
            with (
                mock.patch("robot_debug.external_reset._verified_source", return_value=(1, 2, 780145352, 3)),
                mock.patch.dict(sys.modules, {"h5py": None}),
            ):
                with self.assertRaisesRegex(ExternalResetError, "h5py is required for external reset reading"):
                    read_external_reset(path)


if __name__ == "__main__":
    unittest.main()
