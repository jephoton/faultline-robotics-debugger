from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

import robot_debug.external_reset as external_reset_module
from robot_debug.external_reset import (
    ExternalResetError,
    read_external_reset,
    resolve_external_assets,
    restore_external_reset,
    validate_external_reset,
)


SOURCE_SHA256 = "42189d4415d4c51aaaf0708300653fccc39239cd3f2709079a713cd8d1678a8d"
STATE_SHA256 = "5d4cd69032368d08d09453ef6ed4fa8c4ad697bf152d919eb673837274ba0df1"
XML = '<mujoco><asset><mesh file="/chiliocosm/assets/meshes/a.obj"/></asset></mujoco>'


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _float_sha(values) -> str:
    return _sha(b"".join(struct.pack("<d", float(value)) for value in values))


SYNTHETIC_STATE = [float(index) for index in range(110)]
SYNTHETIC_STATE_SHA256 = _float_sha(SYNTHETIC_STATE)


def candidate(**changes):
    value = {
        "schema_version": 1,
        "suite": "libero_object",
        "task_id": 0,
        "demo": "demo_0",
        "state_index": 0,
        "source_sha256": SOURCE_SHA256,
        "state_sha256": SYNTHETIC_STATE_SHA256,
        "state": list(SYNTHETIC_STATE),
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
        if getlink:
            return child.link
        if not isinstance(child.link, FakeHardLink):
            raise AssertionError("linked child must not be dereferenced")
        return child


class FakeFile(FakeGroup):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ForbiddenHDF5Child:
    @property
    def link(self):
        raise AssertionError("reader must not access saved actions or images")


def fake_h5py(handle):
    return types.SimpleNamespace(
        HardLink=FakeHardLink,
        Dataset=FakeDataset,
        Group=FakeGroup,
        File=lambda *_args, **_kwargs: handle,
    )


def fake_source(state=None):
    state = state or list(SYNTHETIC_STATE)
    demo = FakeGroup(
        {
            "states": FakeDataset(state),
            "actions": ForbiddenHDF5Child(),
            "obs": ForbiddenHDF5Child(),
        },
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
                        "camera_names": ["robot0_eye_in_hand", "agentview"],
                        "camera_heights": 128,
                        "camera_widths": 128,
                    },
                }
            ),
            "problem_info": json.dumps(
                {
                    "problem_name": "libero_floor_manipulation",
                    "domain_name": "robosuite",
                    "language_instruction": "pick up the alphabet soup and place it in the basket",
                }
            ),
            "bddl_file_name": "/untrusted/pick_up_the_alphabet_soup_and_place_it_in_the_basket.bddl",
            "macros_image_convention": "opengl",
        },
    )
    return FakeFile({"data": data})


class CandidateValidationTests(unittest.TestCase):
    def validate_synthetic(self, value):
        with mock.patch("robot_debug.external_reset.STATE_SHA256", SYNTHETIC_STATE_SHA256):
            return validate_external_reset(value)

    def test_valid_candidate_is_detached_and_canonical(self):
        value = candidate()
        result = self.validate_synthetic(value)
        self.assertEqual(result, value)
        self.assertIsNot(result, value)
        self.assertIsNot(result["state"], value["state"])

    def test_production_state_hash_is_fixed_and_synthetic_mismatch_is_rejected(self):
        self.assertEqual(external_reset_module.STATE_SHA256, STATE_SHA256)
        with self.assertRaisesRegex(ExternalResetError, "invalid external reset candidate"):
            validate_external_reset(candidate())

        mismatched = candidate()
        mismatched["state"][0] = -1.0
        with self.assertRaisesRegex(ExternalResetError, "invalid external reset candidate"):
            self.validate_synthetic(mismatched)

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
                    self.validate_synthetic(value)

    def test_rejects_nonfinite_wrong_length_and_cycles(self):
        cycle = candidate()
        cycle["state"].append(cycle)
        nonfinite = candidate()
        nonfinite["state"][0] = math.inf
        for value in (candidate(state=[0.0] * 109), nonfinite, cycle):
            with self.subTest(kind=type(value["state"]).__name__):
                with self.assertRaises(ExternalResetError):
                    self.validate_synthetic(value)

    def test_rejects_huge_integer_with_fixed_safe_error(self):
        value = candidate()
        value["state"][0] = 10**1000
        with self.assertRaisesRegex(ExternalResetError, "invalid external reset candidate"):
            self.validate_synthetic(value)

    def test_rejects_forged_hashes_and_oversized_or_unsafe_xml(self):
        unsafe = [
            "<!DOCTYPE mujoco><mujoco/>",
            "<!ENTITY x 'y'><mujoco/>",
            "<include file='x'/>",
            "<not-mujoco/>",
            "<mujoco>" + ("x" * (2 * 1024 * 1024)) + "</mujoco>",
        ]
        baseline = candidate()
        self.validate_synthetic(baseline)
        mutations = [
            ("source_sha256", "0" * 64),
            ("state_sha256", "0" * 64),
            ("model_xml_sha256", "0" * 64),
            ("reset_id", "0" * 64),
        ] + [("model_xml", xml) for xml in unsafe]
        for field, forged in mutations:
            value = {**baseline, field: forged}
            with self.subTest(field=field, value=str(forged)[:30]):
                with self.assertRaises(ExternalResetError):
                    self.validate_synthetic(value)

    def test_rejects_del_and_c1_controls_in_xml_asset_paths(self):
        for codepoint in (0x7F, 0x85):
            xml = (
                '<mujoco><asset><mesh file="/chiliocosm/assets/meshes/'
                f'a&#x{codepoint:x};.obj"/></asset></mujoco>'
            )
            value = candidate(model_xml=xml, model_xml_sha256=_sha(xml.encode("utf-8")))
            with self.subTest(codepoint=codepoint):
                with self.assertRaisesRegex(ExternalResetError, "invalid external reset candidate"):
                    self.validate_synthetic(value)


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
        self.assertEqual(result["reset_id"], candidate(state_sha256=STATE_SHA256)["reset_id"])
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

    def test_rejects_malformed_controller_metadata_safely(self):
        handle = fake_source()
        data = handle.children["data"]
        metadata = json.loads(data.attrs["env_args"])
        metadata["env_kwargs"]["controller_configs"] = []
        data.attrs["env_args"] = json.dumps(metadata)
        with self.assertRaisesRegex(ExternalResetError, "invalid external reset source"):
            self.read_fixture(handle)

    def test_wraps_unexpected_hdf5_failure_with_safe_error(self):
        handle = fake_source()
        handle.get = mock.Mock(side_effect=RuntimeError("private HDF5 detail"))
        with self.assertRaisesRegex(ExternalResetError, "invalid external reset source"):
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

    def test_rejects_source_that_grows_past_bound_while_reading(self):
        info = types.SimpleNamespace(st_dev=1, st_ino=2, st_size=5, st_mtime_ns=3)

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def fileno(self):
                return 10

            def read(self, _size):
                if hasattr(self, "done"):
                    return b""
                self.done = True
                return b"123456"

        fake_path = types.SimpleNamespace(open=lambda _mode: Stream())
        with (
            mock.patch("robot_debug.external_reset.SOURCE_SIZE", 5),
            mock.patch("robot_debug.external_reset.SOURCE_SHA256", _sha(b"123456")),
            mock.patch("robot_debug.external_reset._safe_regular_path", return_value=info),
            mock.patch("robot_debug.external_reset.os.fstat", return_value=info),
        ):
            with self.assertRaisesRegex(ExternalResetError, "invalid external reset source"):
                external_reset_module._verified_source(fake_path)


class AssetResolutionTests(unittest.TestCase):
    def make_roots(self, directory):
        libero = Path(directory) / "libero"
        robosuite = Path(directory) / "robosuite"
        libero.mkdir()
        robosuite.mkdir()
        return {"libero": libero, "robosuite": robosuite}

    def write_asset(self, root, relative, content=b"asset"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def test_resolves_explicit_aliases_full_suffixes_and_normalized_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            first = self.write_asset(roots["libero"], "textures/shared.png", b"libero")
            second = self.write_asset(roots["robosuite"], "meshes/shared.png", b"robosuite")
            xml = (
                '<mujoco><compiler meshdir="meshes/"/><asset>'
                '<texture file="/chiliocosm/assets/scenes/../textures/shared.png"/>'
                '<mesh file="/robosuite/models/assets/meshes/shared.png"/>'
                "</asset></mujoco>"
            )
            result = resolve_external_assets(xml, roots)
        self.assertNotIn("meshdir", result["xml"])
        self.assertIn(str(first.resolve()), result["xml"])
        self.assertIn(str(second.resolve()), result["xml"])
        self.assertEqual(
            [(item["namespace"], item["relative_path"]) for item in result["assets"]],
            [("libero", "textures/shared.png"), ("robosuite", "meshes/shared.png")],
        )
        self.assertEqual(result["source_xml_sha256"], _sha(xml.encode()))
        self.assertEqual(set(result), {"xml", "source_xml_sha256", "resolved_xml_sha256", "assets", "asset_closure_sha256"})

    def test_resolves_prefixed_paths_for_both_source_namespaces(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            libero_asset = self.write_asset(roots["libero"], "textures/a.png", b"libero")
            robosuite_asset = self.write_asset(roots["robosuite"], "meshes/b.obj", b"robosuite")
            xml = (
                '<mujoco><asset>'
                '<texture file="/installed/libero/chiliocosm/assets/textures/a.png"/>'
                '<mesh file="/installed/robosuite/robosuite/models/assets/meshes/b.obj"/>'
                '</asset></mujoco>'
            )
            result = resolve_external_assets(xml, roots)
        self.assertIn(str(libero_asset.resolve()), result["xml"])
        self.assertIn(str(robosuite_asset.resolve()), result["xml"])
        self.assertEqual(
            [(item["namespace"], item["relative_path"]) for item in result["assets"]],
            [("libero", "textures/a.png"), ("robosuite", "meshes/b.obj")],
        )

    def test_deduplicates_repeated_full_path_without_changing_source_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            self.write_asset(roots["libero"], "textures/a.png")
            xml = (
                '<mujoco><asset><texture file="/chiliocosm/assets/textures/a.png"/>'
                '<texture file="/chiliocosm/assets/textures/a.png"/></asset></mujoco>'
            )
            original = xml[:]
            result = resolve_external_assets(xml, roots)
        self.assertEqual(xml, original)
        self.assertEqual(len(result["assets"]), 1)

    def test_rejects_escape_unknown_ambiguous_backslash_url_and_empty_suffix(self):
        unsafe = [
            "/chiliocosm/assets/../escape.obj",
            "/unknown/assets/a.obj",
            "/chiliocosm/assets/a/robosuite/models/assets/b.obj",
            "/prefix/chiliocosm/assets/a/chiliocosm/assets/b.obj",
            "/chiliocosm/assets/folder\\a.obj",
            "https://example.test/chiliocosm/assets/a.obj",
            "/chiliocosm/assets/",
        ]
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            for filename in unsafe:
                xml = f'<mujoco><asset><mesh file="{filename}"/></asset></mujoco>'
                with self.subTest(filename=filename):
                    with self.assertRaisesRegex(ExternalResetError, "invalid external asset reference"):
                        resolve_external_assets(xml, roots)

    def test_rejects_del_and_c1_controls_in_asset_references(self):
        for control in ("\x7f", "\x85"):
            with self.subTest(codepoint=ord(control)):
                with self.assertRaisesRegex(ExternalResetError, "invalid external asset reference"):
                    external_reset_module._asset_reference(
                        f"/chiliocosm/assets/meshes/a{control}.obj"
                    )

    def test_rejects_missing_or_extra_roots_and_missing_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            xml = '<mujoco><asset><mesh file="/chiliocosm/assets/missing.obj"/></asset></mujoco>'
            for bad_roots in ({"libero": roots["libero"]}, {**roots, "other": roots["libero"]}, roots):
                with self.subTest(keys=set(bad_roots)):
                    with self.assertRaises(ExternalResetError):
                        resolve_external_assets(xml, bad_roots)

    def test_wraps_root_disappearance_without_leaking_path(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            with mock.patch.object(Path, "resolve", side_effect=FileNotFoundError("private root path")):
                with self.assertRaisesRegex(ExternalResetError, "invalid external asset roots") as raised:
                    resolve_external_assets("<mujoco/>", roots)
        self.assertNotIn("private root path", str(raised.exception))

    def test_wraps_asset_disappearance_without_leaking_path(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            self.write_asset(roots["libero"], "meshes/a.obj")
            original_resolve = Path.resolve

            def disappear_asset(path, *args, **kwargs):
                if path.name == "a.obj":
                    raise FileNotFoundError("private asset path")
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(Path, "resolve", autospec=True, side_effect=disappear_asset):
                with self.assertRaisesRegex(ExternalResetError, "invalid external asset") as raised:
                    resolve_external_assets(XML, roots)
        self.assertNotIn("private asset path", str(raised.exception))

    def test_rejects_more_than_128_references(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            self.write_asset(roots["libero"], "a.obj")
            refs = "".join('<mesh file="/chiliocosm/assets/a.obj"/>' for _ in range(129))
            with self.assertRaisesRegex(ExternalResetError, "external asset closure exceeds limits"):
                resolve_external_assets(f"<mujoco><asset>{refs}</asset></mujoco>", roots)

    def test_rejects_asset_over_per_file_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.make_roots(directory)
            self.write_asset(roots["libero"], "large.obj")
            xml = '<mujoco><asset><mesh file="/chiliocosm/assets/large.obj"/></asset></mujoco>'
            with mock.patch("robot_debug.external_reset.MAX_ASSET_BYTES", 0):
                with self.assertRaisesRegex(ExternalResetError, "external asset closure exceeds limits"):
                    resolve_external_assets(xml, roots)

    def test_rejects_asset_that_grows_past_limit_while_reading(self):
        info = types.SimpleNamespace(st_dev=1, st_ino=2, st_size=1, st_mtime_ns=3)

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def fileno(self):
                return 10

            def read(self, _size):
                if hasattr(self, "done"):
                    return b""
                self.done = True
                return b"123456"

        fake_path = types.SimpleNamespace(open=lambda _mode: Stream())
        with (
            mock.patch("robot_debug.external_reset.MAX_ASSET_BYTES", 5),
            mock.patch("robot_debug.external_reset._safe_regular_path", return_value=info),
            mock.patch("robot_debug.external_reset.os.fstat", return_value=info),
            mock.patch("robot_debug.external_reset._same_file_identity", return_value=True),
        ):
            with self.assertRaisesRegex(ExternalResetError, "external asset closure exceeds limits"):
                external_reset_module._asset_digest(fake_path)


class FakeEnvironment:
    def __init__(self, state, *, dimension=110, pre_state=None, post_state=None, fail_step=None):
        self.calls = []
        self.state = [0.0] * dimension
        self.requested_state = list(state)
        self.pre_state = list(pre_state) if pre_state is not None else list(state)
        self.post_state = list(post_state) if post_state is not None else [value + 0.25 for value in state]
        self.fail_step = fail_step
        self.steps = 0

    def reset(self):
        self.calls.append(("reset",))

    def reset_from_xml_string(self, xml):
        self.calls.append(("reset_from_xml_string", xml))

    def get_sim_state(self):
        self.calls.append(("get_sim_state",))
        return list(self.state)

    def set_init_state(self, state):
        self.calls.append(("set_init_state", list(state)))
        self.state = list(self.pre_state)
        return {"set": True}

    def step(self, action):
        self.steps += 1
        self.calls.append(("step", list(action)))
        if self.fail_step == self.steps:
            raise RuntimeError("private simulator detail")
        if self.steps == 10:
            self.state = list(self.post_state)
        return ({"step": self.steps}, 0.0, False, {})


class RestorationTests(unittest.TestCase):
    def fixture(self, directory):
        state = list(SYNTHETIC_STATE)
        value = candidate(state=state)
        libero = Path(directory) / "libero"
        robosuite = Path(directory) / "robosuite"
        (libero / "meshes").mkdir(parents=True)
        robosuite.mkdir()
        (libero / "meshes" / "a.obj").write_bytes(b"asset")
        roots = {"libero": libero, "robosuite": robosuite}
        resolved = resolve_external_assets(XML, roots)
        return state, value, resolved, libero / "meshes" / "a.obj"

    def restore(self, env, value, resolved, state):
        with mock.patch("robot_debug.external_reset.STATE_SHA256", SYNTHETIC_STATE_SHA256):
            return restore_external_reset(env, value, resolved)

    def test_restores_in_order_settles_ten_steps_and_returns_last_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            state, value, resolved, _asset = self.fixture(directory)
            env = FakeEnvironment(state)
            result = self.restore(env, value, resolved, state)
        self.assertEqual(env.calls[0], ("reset",))
        self.assertEqual(env.calls[1], ("reset_from_xml_string", resolved["xml"]))
        self.assertEqual(env.calls[2], ("get_sim_state",))
        self.assertEqual(env.calls[3], ("set_init_state", state))
        self.assertEqual(env.calls[4], ("get_sim_state",))
        self.assertEqual([call for call in env.calls if call[0] == "step"], [("step", [0, 0, 0, 0, 0, 0, -1])] * 10)
        self.assertEqual(result["observation"], {"step": 10})
        metadata = result["reset_metadata"]
        self.assertEqual(
            set(metadata),
            {
                "reset_id", "source_sha256", "state_sha256", "source_xml_sha256",
                "resolved_xml_sha256", "asset_closure_sha256", "pre_settle_state_sha256",
                "post_settle_state_sha256", "settling_steps", "restoration_verified",
            },
        )
        self.assertEqual(metadata["settling_steps"], 10)
        self.assertIs(metadata["restoration_verified"], False)
        self.assertEqual(metadata["pre_settle_state_sha256"], SYNTHETIC_STATE_SHA256)

    def test_dimension_mismatch_stops_before_state_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            state, value, resolved, _asset = self.fixture(directory)
            env = FakeEnvironment(state, dimension=109)
            with self.assertRaisesRegex(ExternalResetError, "external simulator state dimension mismatch"):
                self.restore(env, value, resolved, state)
        self.assertFalse(any(call[0] == "set_init_state" for call in env.calls))

    def test_pre_settle_mismatch_stops_before_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            state, value, resolved, _asset = self.fixture(directory)
            env = FakeEnvironment(state, pre_state=[-1.0] * 110)
            with self.assertRaisesRegex(ExternalResetError, "external simulator state mismatch"):
                self.restore(env, value, resolved, state)
        self.assertFalse(any(call[0] == "step" for call in env.calls))

    def test_step_failure_is_safe_and_nonfinite_post_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            state, value, resolved, _asset = self.fixture(directory)
            failing = FakeEnvironment(state, fail_step=3)
            with self.assertRaisesRegex(ExternalResetError, "external simulator settling failed"):
                self.restore(failing, value, resolved, state)
            nonfinite = FakeEnvironment(state, post_state=[math.nan] + [0.0] * 109)
            with self.assertRaisesRegex(ExternalResetError, "invalid settled simulator state"):
                self.restore(nonfinite, value, resolved, state)

    def test_changed_asset_is_rejected_before_environment_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            state, value, resolved, asset = self.fixture(directory)
            asset.write_bytes(b"changed")
            env = FakeEnvironment(state)
            with self.assertRaisesRegex(ExternalResetError, "invalid resolved external assets"):
                self.restore(env, value, resolved, state)
        self.assertEqual(env.calls, [])

    def test_malformed_resolved_text_is_rejected_before_environment_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            state, value, resolved, _asset = self.fixture(directory)
            resolved["xml"] = "\ud800"
            env = FakeEnvironment(state)
            with self.assertRaisesRegex(ExternalResetError, "invalid resolved external assets"):
                self.restore(env, value, resolved, state)
        self.assertEqual(env.calls, [])

    def test_malformed_asset_namespace_is_rejected_before_environment_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            state, value, resolved, _asset = self.fixture(directory)
            for namespace in ([], {}):
                malformed = {
                    **resolved,
                    "assets": [{**resolved["assets"][0], "namespace": namespace}],
                }
                env = FakeEnvironment(state)
                with self.subTest(namespace=namespace):
                    with self.assertRaisesRegex(ExternalResetError, "invalid resolved external assets"):
                        self.restore(env, value, malformed, state)
                    self.assertEqual(env.calls, [])

if __name__ == "__main__":
    unittest.main()
