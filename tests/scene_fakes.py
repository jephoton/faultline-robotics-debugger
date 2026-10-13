"""Fakes shared by the M7 scenario-start tests: a MuJoCo-shaped scene and a harness-shaped upstream.

Nothing here needs the simulator. ``FakeModel`` follows the MjModel arrays the scene
code reads (``body_parentid``, ``jnt_type``, ``jnt_bodyid``, ``jnt_qposadr``,
``jnt_dofadr``, ``geom_bodyid``) and the robosuite name helpers
(``body_id2name`` and ``joint_id2name``).
"""

import importlib
import sys
import types
import unittest

import numpy as np

FREE, BALL, SLIDE, HINGE = 0, 1, 2, 3
_QPOS = {FREE: 7, BALL: 4, SLIDE: 1, HINGE: 1}
_DOF = {FREE: 6, BALL: 3, SLIDE: 1, HINGE: 1}


class FakeModel:
    def __init__(self, bodies, joints, geoms):
        self._body_names = [name for name, _parent in bodies]
        self.body_parentid = np.array([parent for _name, parent in bodies], dtype=int)
        self._joint_names = [joint[0] for joint in joints]
        self.jnt_type = np.array([joint[1] for joint in joints], dtype=int)
        self.jnt_bodyid = np.array([joint[2] for joint in joints], dtype=int)
        qpos_adr, dof_adr, qpos, dof = [], [], 0, 0
        for _name, kind, _body in joints:
            qpos_adr.append(qpos)
            dof_adr.append(dof)
            qpos += _QPOS[kind]
            dof += _DOF[kind]
        self.jnt_qposadr = np.array(qpos_adr, dtype=int)
        self.jnt_dofadr = np.array(dof_adr, dtype=int)
        self.nq, self.nv = qpos, dof
        self.njnt, self.nbody = len(joints), len(bodies)
        self.geom_bodyid = np.array(geoms, dtype=int)
        self.ngeom = len(geoms)

    def body_id2name(self, index):
        return self._body_names[index]

    def joint_id2name(self, index):
        return self._joint_names[index]

    @property
    def state_length(self):
        return 1 + self.nq + self.nv


class FakeContact:
    def __init__(self, geom1, geom2, dist):
        self.geom1, self.geom2, self.dist = geom1, geom2, dist


class FakeData:
    def __init__(self):
        self.contacts = []

    @property
    def ncon(self):
        return len(self.contacts)

    @property
    def contact(self):
        return self.contacts


class FakeSim:
    def __init__(self, model):
        self.model = model
        self.data = FakeData()
        self.forwards = 0

    def forward(self):
        self.forwards += 1


# A small LIBERO-like scene. Body index -> (name, parent); 0 is the world.
BODIES = [
    ("world", 0),
    ("robot0_base", 0),             # 1
    ("robot0_link1", 1),            # 2
    ("gripper0_right_gripper", 2),  # 3
    ("main_table", 0),              # 4  static fixture
    ("alphabet_soup_1_main", 0),    # 5  free object
    ("basket_1_main", 0),           # 6  free object
    ("basket_1_lid", 6),            # 7  child body without a joint
    ("microwave_1_main", 0),        # 8  articulated fixture, no free joint
    ("microwave_1_door", 8),        # 9
    ("flat_stove_1_main", 0),       # 10 static fixture
]
JOINTS = [
    ("robot0_joint1", HINGE, 2),
    ("gripper0_finger_joint1", SLIDE, 3),
    ("gripper0_finger_joint2", SLIDE, 3),
    ("alphabet_soup_1_joint0", FREE, 5),
    ("basket_1_joint0", FREE, 6),
    ("microwave_1_door_joint", HINGE, 9),
]
GEOM_BODIES = {
    "floor": 0, "robot_link": 2, "finger": 3, "table": 4, "soup": 5,
    "basket": 6, "basket_lid": 7, "microwave": 8, "microwave_door": 9, "stove": 10,
    "robot_base": 1,
}
GEOM_ORDER = list(GEOM_BODIES)
GEOM = {name: index for index, name in enumerate(GEOM_ORDER)}


def standard_model():
    return FakeModel(BODIES, JOINTS, [GEOM_BODIES[name] for name in GEOM_ORDER])


class FakeEnv:
    """Env-wrapper shaped like LIBERO's: ``reset``, ``set_init_state``, ``step``, ``get_sim_state``."""

    def __init__(self, model=None):
        self.model = model or standard_model()
        self.sim = FakeSim(self.model)
        self.robots = []
        self.state = np.zeros(self.model.state_length)
        self.calls = []
        self.drift = np.zeros(self.model.state_length)
        self.closed = False
        self.after_set = None  # a callable run after set_init_state, e.g. to place contacts

    def reset(self):
        self.calls.append("reset")
        return {"frame": np.zeros((2, 2, 3), dtype=np.uint8)}

    def set_init_state(self, state):
        self.calls.append("set_init_state")
        self.state = np.array(state, dtype=np.float64)
        if self.after_set is not None:
            self.after_set(self)
        return {"frame": np.full((2, 2, 3), 9, dtype=np.uint8), "from": "set_init_state"}

    def step(self, action):
        self.calls.append("step")
        self.state = self.state + self.drift
        return {"frame": np.full((2, 2, 3), 5, dtype=np.uint8), "from": "step"}, 0.0, False, {}

    def get_sim_state(self):
        return self.state.copy()

    def close(self):
        self.closed = True


class FakeTaskSuite:
    def __init__(self, states):
        self._states = states

    def get_task_init_states(self, task_id):
        return self._states[task_id]


class StepResult:
    def __init__(self, obs, reward, done, info):
        self.obs, self.reward, self.done, self.info = obs, reward, done, info


class FakeRecorder:
    def __init__(self):
        self.frames, self.steps = [], []

    def record_video(self, frame):
        self.frames.append(frame)

    def record_step(self, **fields):
        self.steps.append(fields)


class FakeUpstream:
    """The parts of the pinned ``LIBEROBenchmark`` that the adapter relies on."""

    def __init__(self, suite="libero_spatial", seed=7, num_steps_wait=10, send_wrist_image=False,
                 send_state=False, absolute_action=False, max_steps=None, env_seed=None,
                 quat_no_antipodal=False):
        self.upstream_kwargs = {"suite": suite, "seed": seed, "send_wrist_image": send_wrist_image,
                                "send_state": send_state}
        self.suite = suite
        self.seed = seed
        self.num_steps_wait = num_steps_wait
        self.absolute_action = absolute_action
        self.env_seed = env_seed if env_seed is not None else seed
        self._env = None
        self._current_task_id = None
        self._task_suite = None
        self._recorder = FakeRecorder()
        self.upstream_reset_tasks = []

    def get_tasks(self):
        return [{"task_id": task_id, "task_obj": object(), "name": "task {}".format(task_id)}
                for task_id in range(3)]

    def reset(self, task):  # mirrors upstream reset: env.reset(), set_init_state(states[episode_idx]), wait steps
        self.upstream_reset_tasks.append(task)
        env = self._make_env(task)
        self._env = env
        env.reset()
        states = self._task_suite.get_task_init_states(task["task_id"])
        obs = env.set_init_state(states[task.get("episode_idx", 0)])
        for _ in range(self.num_steps_wait):
            obs, _, _, _ = env.step([0.0] * 6 + [-1.0])
        self._recorder.record_video(self._extract_frame(obs))
        return obs

    def step(self, action):
        obs, reward, done, info = self._env.step(action)
        self._recorder.record_video(self._extract_frame(obs))
        self._recorder.record_step(reward=float(reward), done=bool(done), success=bool(done))
        return StepResult(obs, reward, done, info)

    def check_done(self, step_result):
        return step_result.done

    def get_step_result(self, step_result):
        return {"success": step_result.done}

    def make_obs(self, raw_obs, task):
        return {"images": {"agentview": raw_obs["frame"].copy(), "wrist": raw_obs["frame"].copy()},
                "task_description": task["name"]}

    @staticmethod
    def _extract_frame(raw_obs):
        if not isinstance(raw_obs, dict):
            return None
        return raw_obs.get("frame")


_MODULES = (
    "vla_eval",
    "vla_eval.benchmarks",
    "vla_eval.benchmarks.base",
    "vla_eval.benchmarks.libero",
    "vla_eval.benchmarks.libero.benchmark",
    "robot_debug.libero",
)


class FakeHarnessCase(unittest.TestCase):
    """Imports ``robot_debug.libero`` against ``FakeUpstream`` and restores ``sys.modules``."""

    def setUp(self):
        saved = {name: sys.modules.get(name) for name in _MODULES}
        for name in _MODULES:
            sys.modules.pop(name, None)
        for name in _MODULES[:-1]:
            sys.modules[name] = types.ModuleType(name)
        benchmark_module = sys.modules["vla_eval.benchmarks.libero.benchmark"]
        benchmark_module.LIBEROBenchmark = FakeUpstream
        benchmark_module.LIBERO_DUMMY_ACTION = [0.0] * 6 + [-1.0]
        sys.modules["vla_eval.benchmarks.base"].StepResult = StepResult
        self.adapter = importlib.import_module("robot_debug.libero")
        self.benchmark_type = self.adapter.DiagnosticLIBEROBenchmark

        def restore():
            for name, original in saved.items():
                sys.modules.pop(name, None)
                if original is not None:
                    sys.modules[name] = original

        self.addCleanup(restore)
