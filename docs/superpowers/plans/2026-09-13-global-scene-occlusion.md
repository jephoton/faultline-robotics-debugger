# Global Scene Occlusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a replayable rectangular occlusion to LIBERO's global agent-view image and validate one recorded GR00T episode through the pinned cloud stack.

**Architecture:** A pure NumPy value object validates and applies normalized rectangles without mutating observations. A thin benchmark subclass intercepts the pinned harness at `LIBEROBenchmark.make_obs()` and `_extract_frame()`, while YAML mounts this repository's source read-only into the existing container.

**Tech Stack:** Python 3.8-compatible source, NumPy, standard-library `unittest`, AllenAI VLA Evaluation Harness at `35f1200e`, LIBERO/MuJoCo, Docker, and the existing Nebius L40S pilot.

---

## File responsibilities

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | Minimal package metadata and NumPy dependency for reproducible local tests |
| `src/robot_debug/occlusion.py` | Rectangle validation, pixel conversion, blending, and observation copying |
| `src/robot_debug/libero.py` | Thin subclass of the pinned LIBERO benchmark |
| `tests/test_occlusion.py` | Pure transform and observation-boundary tests |
| `tests/test_libero_adapter.py` | Adapter behavior against a lightweight fake upstream class |
| `configs/occlusion-smoke.yaml` | One centered 6.25%-area cloud compatibility episode |
| `docs/experiments/first-occlusion.md` | Cloud result and compatibility evidence |

### Task 1: Make the project test environment reproducible

**Files:**
- Create: `pyproject.toml`
- Modify: `src/robot_debug/records.py`
- Test: `tests/test_records.py`

- [ ] **Step 1: Add package metadata**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "robot-debug"
version = "0.1.0"
requires-python = ">=3.8"
dependencies = ["numpy>=1.24,<1.25"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Replace Python 3.11-only `StrEnum`**

Use `class AttemptOutcome(str, Enum)` so importing the project source in the
LIBERO Python 3.8 image remains valid while preserving serialized string values.

- [ ] **Step 3: Create and install the local environment**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Expected: installation completes and NumPy 1.24.x is installed.

- [ ] **Step 4: Run the existing tests**

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: the three attempt-record tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/robot_debug/records.py
git commit -m "chore: add Python 3.8 package environment"
```

### Task 2: Implement the pure rectangle transform with TDD

**Files:**
- Create: `src/robot_debug/occlusion.py`
- Create: `tests/test_occlusion.py`

- [ ] **Step 1: Write failing tests**

Tests construct small RGB arrays and require:

```python
spec = RectOcclusion(x=0.25, y=0.25, width=0.5, height=0.5)
masked = spec.apply(np.full((4, 4, 3), 255, dtype=np.uint8))
self.assertTrue(np.array_equal(masked[1:3, 1:3], np.zeros((2, 2, 3), dtype=np.uint8)))
```

Add cases for a 50% blend, disabled byte equality, input immutability,
dictionary conversion, coordinate/color/opacity rejection, shape rejection,
data-type rejection, and `apply_agentview_occlusion()` preserving wrist and
state objects while replacing only `images.agentview`.

- [ ] **Step 2: Run the focused tests and confirm the missing module failure**

```bash
.venv/bin/python -m unittest tests.test_occlusion -v
```

Expected: import fails because `robot_debug.occlusion` does not exist.

- [ ] **Step 3: Implement the value object and observation transform**

```python
@dataclass(frozen=True)
class RectOcclusion:
    enabled: bool = True
    x: float = 0.0
    y: float = 0.0
    width: float = 0.25
    height: float = 0.25
    color: Tuple[int, int, int] = (0, 0, 0)
    opacity: float = 1.0

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "RectOcclusion":
        if value is None:
            return cls(enabled=False)
        data = dict(value)
        if "color" in data:
            data["color"] = tuple(data["color"])
        return cls(**data)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        values = (self.x, self.y, self.width, self.height, self.opacity)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("rectangle values must be finite")
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError("rectangle position must be non-negative and extent must be positive")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("rectangle must stay within normalized image bounds")
        if self.opacity < 0 or self.opacity > 1:
            raise ValueError("opacity must be between 0 and 1")
        if len(self.color) != 3 or any(type(channel) is not int or channel < 0 or channel > 255 for channel in self.color):
            raise ValueError("color must contain three integer channels between 0 and 255")

    def apply(self, image: np.ndarray) -> np.ndarray:
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image must have shape H x W x 3")
        if image.dtype != np.uint8:
            raise TypeError("image must use uint8 pixels")
        output = np.ascontiguousarray(image.copy())
        if not self.enabled or self.opacity == 0:
            return output
        height, width, _ = output.shape
        x0 = int(math.floor(self.x * width))
        y0 = int(math.floor(self.y * height))
        x1 = int(math.ceil((self.x + self.width) * width))
        y1 = int(math.ceil((self.y + self.height) * height))
        color = np.asarray(self.color, dtype=np.float32)
        region = output[y0:y1, x0:x1].astype(np.float32)
        blended = (1.0 - self.opacity) * region + self.opacity * color
        output[y0:y1, x0:x1] = np.rint(blended).astype(np.uint8)
        return output


def apply_agentview_occlusion(
    observation: Mapping[str, Any], spec: RectOcclusion
) -> Dict[str, Any]:
    result = dict(observation)
    images = dict(result["images"])
    images["agentview"] = spec.apply(images["agentview"])
    result["images"] = images
    return result
```

The implementation must reject non-finite values and rectangles whose right or
bottom edge exceeds 1.0. Use `np.rint` for deterministic alpha blending.

- [ ] **Step 4: Run focused and full tests**

```bash
.venv/bin/python -m unittest tests.test_occlusion -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all transform and record tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robot_debug/occlusion.py tests/test_occlusion.py
git commit -m "feat(perturb): add rectangular agent-view occlusion"
```

### Task 3: Add the LIBERO adapter with TDD

**Files:**
- Create: `src/robot_debug/libero.py`
- Create: `tests/test_libero_adapter.py`

- [ ] **Step 1: Write a failing adapter test**

Inject a fake `vla_eval.benchmarks.libero.benchmark` module whose
`LIBEROBenchmark` returns an observation containing agent-view, wrist, and
state. Import `robot_debug.libero`, instantiate the diagnostic subclass with a
rectangle mapping, and assert that `make_obs()` changes agent-view only and
`_extract_frame()` applies the same rectangle.

- [ ] **Step 2: Run the focused test and confirm the missing module failure**

```bash
.venv/bin/python -m unittest tests.test_libero_adapter -v
```

Expected: import fails because `robot_debug.libero` does not exist.

- [ ] **Step 3: Implement the thin subclass**

```python
class DiagnosticLIBEROBenchmark(LIBEROBenchmark):
    def __init__(self, agentview_occlusion=None, **kwargs):
        self.agentview_occlusion = RectOcclusion.from_mapping(agentview_occlusion)
        super().__init__(**kwargs)

    def make_obs(self, raw_obs, task):
        observation = super().make_obs(raw_obs, task)
        return apply_agentview_occlusion(observation, self.agentview_occlusion)

    def _extract_frame(self, raw_obs):
        frame = super()._extract_frame(raw_obs)
        if frame is None:
            return None
        return self.agentview_occlusion.apply(frame)
```

Keep this module valid under Python 3.8 syntax.

- [ ] **Step 4: Run focused and full tests**

```bash
.venv/bin/python -m unittest tests.test_libero_adapter -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all adapter, transform, and record tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robot_debug/libero.py tests/test_libero_adapter.py
git commit -m "feat(libero): inject global scene occlusion"
```

### Task 4: Configure and validate one cloud compatibility episode

**Files:**
- Create: `configs/occlusion-smoke.yaml`
- Create: `docs/experiments/first-occlusion.md`
- Modify: `docs/superpowers/plans/2026-09-12-robot-debugging-startup.md`

- [ ] **Step 1: Create the pinned smoke configuration**

Use the validated baseline image/server/task settings. Add:

```yaml
docker:
  volumes:
    - "${oc.env:ROBOT_DEBUG_SRC}:/workspace/robot-debug-src:ro"
  env:
    - "PYTHONPATH=/workspace/robot-debug-src:/workspace/src"
benchmarks:
  - benchmark: "robot_debug.libero:DiagnosticLIBEROBenchmark"
    params:
      agentview_occlusion:
        enabled: true
        x: 0.375
        y: 0.375
        width: 0.25
        height: 0.25
        color: [0, 0, 0]
        opacity: 1.0
```

Retain one Object task, one episode, seeds 7/7, video, step recording, and the
pinned simulator digest.

- [ ] **Step 2: Copy source/config to the stopped pilot disk after startup**

Place the repository source at `/home/robot/nebius-nvidia-hackathon/src` and
the YAML at `/home/robot/occlusion-smoke.yaml`. Do not transfer `.git`, local
artifacts, credentials, or model files.

- [ ] **Step 3: Validate import inside the pinned image before model startup**

```bash
docker run --rm \
  -v /home/robot/nebius-nvidia-hackathon/src:/workspace/robot-debug-src:ro \
  -e PYTHONPATH=/workspace/robot-debug-src:/workspace/src \
  --entrypoint python \
  ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0 \
  -c "from robot_debug.libero import DiagnosticLIBEROBenchmark; print(DiagnosticLIBEROBenchmark.__name__)"
```

Expected: `DiagnosticLIBEROBenchmark`.

- [ ] **Step 4: Run one recorded episode**

From `/home/robot/vla-evaluation-harness`, wait for the existing model server's
health endpoint, then run:

```bash
ROBOT_DEBUG_SRC=/home/robot/nebius-nvidia-hackathon/src \
  /home/robot/.venvs/vla-eval/bin/vla-eval run \
  --config /home/robot/occlusion-smoke.yaml --yes
```

Expected: one completed `success` or `fail` episode, with no infrastructure
error and a video containing the centered rectangle.

- [ ] **Step 5: Preserve and document evidence**

Copy aggregate JSON, per-step JSONL, SQLite, video, and run log into an ignored
local artifact directory. Record outcome, step count, elapsed time, perturbation
specification, model/container revisions, import evidence, and visual-review
status in `docs/experiments/first-occlusion.md`.

- [ ] **Step 6: Stop the VM and run local regression tests**

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass and the VM reports `STOPPED` while its managed disk
retains the cache.

- [ ] **Step 7: Commit**

```bash
git add configs/occlusion-smoke.yaml docs/experiments/first-occlusion.md \
  docs/superpowers/plans/2026-09-12-robot-debugging-startup.md
git commit -m "docs: record first global occlusion episode"
```
