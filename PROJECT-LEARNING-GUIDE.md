# Two robot projects: what you would learn and build

**October 8 update:** the selected failure-diagnosis project is now named
**Faultline**. This guide preserves the original two-option discussion below;
additional HPC work is optional stretch and may move to another project.

Written September 12, 2026. This is a beginner-oriented decision guide, not a finalized architecture.

The two options are:

1. **Robot assurance:** check whether a robot's plan is still acceptable when its surroundings change.
2. **Robot failure diagnosis:** deliberately test a robot in different conditions, find failures, and turn them into small, repeatable bug reports.

Both can begin entirely in simulation. You do not need to own a robot or train an AI model from scratch to start.

The research links at the end are the sources behind this guide. Their projects and setup instructions have been inspected, but their code has not yet been reproduced on our machine. Suggested combinations below still need an integration test.

## 1. First, what is a robot AI system actually made of?

Imagine a robot arm moving a part from a tray into a box.

| Part | Plain-language meaning | Example |
| --- | --- | --- |
| Environment | The place where the robot operates | A table, tray, box, and nearby objects |
| Observation | Information the robot receives | A camera image and the arm's joint positions |
| State | A description of what is happening | The box is at a particular position; the gripper holds a part |
| Task | The desired result | Put the part in the box |
| Plan | A sequence of higher-level steps | Approach, grasp, lift, move, release |
| Policy | A rule or learned model that chooses actions from observations | Given this image, move the gripper slightly left |
| Action | A command sent to the robot | Move the gripper by a small amount or close it |
| Controller | Software translating commands into motor behavior | Make the joints follow the requested motion |
| Simulator | Software pretending to be the physical world | Compute where objects move and what the camera sees |

A **policy** is not necessarily a language model. It might be a hand-written program, a neural network, or a combination of methods.

A **VLA**, short for *vision-language-action model*, is a model that uses images and language instructions to help produce robot actions. Think of it as one possible robot brain.

A **checkpoint** is a saved trained model. Downloading a suitable checkpoint is like installing an existing robot skill rather than teaching every movement yourself. It still needs the right robot, camera inputs, action format, and task setup.

A **rollout** or **episode** is one attempt at a task, from the starting state until success, failure, or a time limit. Running 50 rollouts means giving the robot 50 attempts.

## 2. Idea A: robot assurance

### The question

> The robot has a plan. Something changes. Is it still acceptable to continue, and if not, what needs to change?

Imagine the robot intends to place a part in an empty fixture. Before it gets there, another object occupies that fixture. A useful assurance system notices that an assumption has become false and prevents the robot from blindly continuing.

### What the user would see

1. The robot starts a task in a simulated workcell—a small workspace containing the arm and its equipment.
2. The screen shows the planned steps and their requirements.
3. You introduce a change, such as occupying the destination.
4. The system marks the affected requirement: `destination must be empty`.
5. The robot pauses or selects an allowed recovery action.
6. A revised plan is checked and then executed.

The key output is an explanation backed by explicit checks, rather than a language model saying that the plan looks safe.

### Technologies you would use

#### A. A structured world model

This is a small, machine-readable description of the scene. It can start as a Python object or JSON:

```json
{
  "gripper_holds": "part_A",
  "fixture_empty": false,
  "inspection_complete": true
}
```

You would write code that updates this description from the simulator. Initially, we can use the simulator's exact object information. Inferring the same information from real camera images is a separate, harder problem.

**What you learn:** representing a messy physical situation using a limited set of facts, and understanding what that representation leaves out.

#### B. Action preconditions and effects

A **precondition** is something that must be true before an action. An **effect** is what the action is expected to change.

For a simplified `place_part` action:

- Preconditions: the robot holds the part, the fixture is empty, and inspection is complete.
- Effects: the fixture contains the part, and the gripper becomes empty.

You would define these rules for a small set of robot skills. The robot still needs a controller that can perform each skill.

**What you learn:** state machines, planning, and how software contracts relate to physical actions.

#### C. SMT and Z3

**SMT** means *satisfiability modulo theories*. The useful intuition is: give a solver logical and mathematical constraints, and ask whether they can all be true together.

**Z3** is a solver we can call from Python. It supports reasoning about things such as Boolean values, integers, and real numbers.

For example:

```text
The plan requires: fixture_empty = true
The current scene says: fixture_empty = false

These cannot both be true, so this plan is rejected.
```

That example is so simple that an ordinary `if` statement would do. SMT becomes interesting when many interdependent choices are involved: which fixture to use, which steps can be reordered, when shared equipment is available, and whether deadlines can all be met.

Two different solver questions matter:

| Question | What the answer establishes |
| --- | --- |
| Is there a plan satisfying these constraints? | A satisfying answer gives a feasible plan in the encoded model |
| Is there a modeled execution of this plan that violates the requirement? | A satisfying answer gives a counterexample; an unsatisfiable answer rules out violations within that encoding and its limits |

These are not interchangeable. Finding one good execution does not establish that every possible execution is good.

Solvers can also return **unknown**, or we can stop them after a timeout. That must remain an inconclusive result.

**What you learn:** writing constraints, interpreting solver results, debugging incorrect encodings, and stating exactly what was established.

#### D. Unsatisfiable cores

An **unsatisfiable core** is a conflicting subset of the constraints, useful when there is no solution.

Example explanation:

```text
These requirements conflict:
- The part must be placed in fixture B.
- Placing a part requires an empty fixture.
- Fixture B is occupied.
```

Z3 can help identify such a subset when constraints are appropriately tracked. It is not automatically the smallest possible explanation, and it is an explanation of the mathematical conflict—not proof of the physical root cause.

**What you learn:** turning formal outputs into explanations an engineer can understand.

#### E. Runtime monitoring and incremental checking

**Runtime** means while the system is operating. A monitor watches for changes to facts used in the plan.

**Incremental checking** means retaining useful solver work while changing relevant assumptions, instead of rebuilding the entire problem every time.

You would connect the scene updates to the checks and define the response to rejection or uncertainty. A physical system needs a suitable stopping or recovery behavior; simply rejecting the next command does not guarantee that ongoing motion stops safely.

**What you learn:** event-driven systems, maintaining consistent state, solver performance, and handling stale information.

#### F. Nemotron and a simulator

Nemotron could translate an instruction into a structured task proposal or propose repairs based on solver feedback. Deterministic code would encode the trusted constraints and validate the result.

The simulator supplies the robot, objects, observations, and visible execution. Existing research environments can provide the initial skills, avoiding a simultaneous robot-learning project.

**What you learn:** calling an AI model through an API, validating its output, and connecting planning software to robot execution.

### What you would actually spend time doing

- Writing Python rules and Z3 expressions.
- Deciding which aspects of the world to represent.
- Constructing valid and invalid plans to test your model.
- Inspecting why a solver accepted something it should reject.
- Connecting scene changes to plan rechecks.
- Comparing full replanning against more selective repair.

**The main difficulty:** your proof is only as relevant as the model. If your encoding ignores collisions, proving the encoded constraints says nothing about collision avoidance.

### Existing work that helps

- **TAMPEST:** the most directly relevant SMT planning reference; useful encodings and benchmark problems.
- **PRoC3S:** examples of robot programs checked against constraints and revised using feedback. Its approach is not simply SMT verification.
- **RoboGuard:** a precedent for constraining robot plans using temporal logic—logic about how events unfold over time.

We would select one starting point, not combine all three codebases.

### A small learning exercise before committing

Model two fixtures and three parts. Ask Z3 to find an allowed placement order. Then occupy one fixture and ask what changes. Add a deadline that makes the task impossible and inspect the conflicting requirements.

If that exercise feels satisfying, the assurance direction is likely a good fit.

## 3. Idea B: robot failure diagnosis

### The question

> Under what changes does this robot policy fail, and can we reduce a complicated failure into a useful, repeatable test?

Imagine a robot succeeds when the camera and objects are arranged exactly as expected. Move the camera slightly and add a distractor, and it starts picking up the wrong object. Which change mattered? Does the failure recur? Can we test whether a later policy fixes it?

### What the user would see

1. Choose an existing robot policy and task.
2. Select allowed changes, such as camera position or object placement.
3. Run a collection of task attempts.
4. Open a failed attempt and watch its recording.
5. Ask the system to remove unnecessary changes while preserving the failure.
6. Save the reduced case and compare it against another policy version.

The key output is a reproducible robot bug report, not just a success-rate chart.

### Technologies you would use

#### A. An existing policy and benchmark

A **benchmark** is a defined set of tasks and a procedure for measuring performance. LIBERO, RoboCasa, and COLOSSEUM are examples in robot manipulation.

A benchmark can provide scenes, objects, task definitions, and success checks. A compatible pretrained policy gives us something to evaluate immediately.

You would load an existing checkpoint, run its supported task, and first confirm that it succeeds often enough for later failures to be meaningful.

**What you learn:** model inference, robot observation/action formats, and how experimental protocols affect results.

#### B. Simulation and rendering

**Physics simulation** calculates motion and interactions. **Rendering** generates images of the scene, including what the robot's camera sees.

These are separate workloads. A robot using camera images needs both. This matters when choosing hardware: not every GPU suited to model inference supports every simulator's rendering requirements.

Possible foundations include a LIBERO-compatible environment or Isaac Lab-Arena. We would start with one simulator and one supported policy combination.

**What you learn:** configuring scenes, cameras, object states, and repeatable task execution.

#### C. Perturbations and domain randomization

A **perturbation** is a controlled change to a test. **Domain randomization** means varying such conditions across attempts.

Examples:

- Move an object within a permitted region.
- Change camera angle or lighting.
- Add a distractor.
- Vary friction or delay an action, if the environment supports it.

You would define parameters and allowed ranges. Tests must preserve the intended task; putting a target outside the robot's reach can create an impossible task rather than expose a useful policy weakness.

**What you learn:** experimental design and the difference between challenging a system and changing the problem entirely.

#### D. Failure definitions and monitors

A **failure oracle** is simply the code deciding whether an attempt failed.

Different checks answer different questions:

| Check | Example |
| --- | --- |
| Task success | Did the correct part reach the destination? |
| Constraint violation | Did the robot enter a forbidden region? |
| Damage | Did a measured simulator signal exceed a chosen damage threshold? |
| Timing | Did the attempt exceed its deadline? |

You would inspect the benchmark's existing success check and add only the measurements needed for the research question. OopsieVerse is a precedent for evaluating damage as well as task completion.

**What you learn:** measurement design, instrumentation, and avoiding misleading success metrics.

#### E. Adaptive search and falsification

Random search tries different changes without learning from earlier results. **Adaptive search** uses previous outcomes to decide what to try next.

For example, if camera shifts to the right repeatedly cause failures, the search can investigate that region more closely.

**Falsification** means finding an execution that violates a stated requirement. VerifAI provides tools for specification-guided simulation and failure search. Scenic is a language for describing distributions of possible scenes with constraints.

These tools are useful references, but we do not need to adopt both on day one. A simple random-search baseline should come first.

**What you learn:** optimization, search efficiency, and evaluating a method against a fair baseline.

#### F. Failure reduction

Suppose a failed attempt has five changed conditions. A reducer removes one change, reruns the attempt, and checks whether it still fails. It can also try reducing the magnitude of a change.

```text
Original failure: camera shift + dim light + distractor + object shift
Reduced failure: camera shift + object shift
```

This resembles reducing a crashing software program to a small bug reproduction.

You would define what “smaller” means and how many repeat attempts are needed. A reduced case is not automatically globally minimal, and a failure that survives one rerun may still be unreliable.

**What you learn:** debugging algorithms, repeated experiments, and distinguishing reproducible triggers from causal claims.

#### G. Parallel evaluation and HPC

Most task attempts can run independently. We can distribute them across workers and combine their results.

**Batched inference** means passing observations from several attempts to the model together. It can improve GPU utilization, but depends on the policy and runner.

You would measure where time goes: simulation, rendering, model inference, startup, or saving recordings. Only then would we choose what to parallelize.

The goal is useful failures found per compute-hour, not simply the largest number of GPUs.

**What you learn:** worker orchestration, batching, queues, profiling, resource limits, and cost/performance tradeoffs.

#### H. Replay and regression testing

A **regression test** checks whether a previously observed problem returns after a change.

A useful replay bundle records the scene parameters, model/checkpoint version, simulator version, random seed, task instruction, actions, and outcome. A seed alone may not reproduce GPU or simulator behavior exactly; repeated replay needs to be measured.

**What you learn:** reproducible systems and comparing software/model versions fairly.

### What you would actually spend time doing

- Getting an existing policy to perform one task successfully.
- Running and watching simulation episodes.
- Writing scripts that change scene parameters.
- Collecting results, plots, and videos.
- Building a search and reduction loop.
- Debugging dependency, camera, and action-format mismatches.
- Comparing methods using the same compute or episode budget.

**The main difficulty:** making failures informative and reproducible, while avoiding excessive compute and misleading measurements.

### Where SMT could fit—optionally

SMT could check the logical validity of generated scenarios or whether a simplified task plan remains feasible. It would not automatically establish continuous motion feasibility or explain every policy failure.

This project is worthwhile without SMT. Add it only if checking scenario validity becomes the central research question you want to investigate.

### Existing work that helps

- **LIBERO-Plus / COLOSSEUM:** ready-made robustness tasks and perturbation ideas.
- **AllenAI VLA evaluation harness:** model/benchmark adapters, recordings, and evaluation infrastructure.
- **Isaac Lab-Arena:** an alternative foundation for composable, scalable robot evaluation.
- **VerifAI / Scenic:** specification-guided search and scene generation.
- **OopsieVerse:** damage measurements beyond task completion.

These are alternatives and references, not a shopping list of dependencies. The starting stack should be one benchmark, one policy, and one runner.

### A small learning exercise before committing

Run a pretrained policy on one supported task. Change one scene parameter, record outcomes across several attempts, and find a failure that repeats. Try undoing part of the change while keeping the failure.

If you enjoy inspecting the videos and designing the next experiment, the evaluation direction is likely a good fit.

## 4. How the two experiences differ

| Question | Assurance | Failure diagnosis |
| --- | --- | --- |
| Main activity | Build and check a model of allowed behavior | Run experiments and isolate failure conditions |
| Most central technology | SMT, action contracts, runtime state tracking | Simulator, existing policy, search and replay |
| Mathematics | Logic, constraints, bounded reasoning | Statistics, optimization, performance measurement |
| Typical debugging question | Why did my encoding accept this invalid plan? | Why does this policy fail in this scene, and does it repeat? |
| Early compute needs | Small logical examples can run on CPU; full robot integration adds requirements | Model inference and rendered simulation usually dominate |
| What you produce | Accepted/rejected plans, explanations, monitored execution | Failure cases, recordings, reduced scenarios, comparisons |
| Biggest conceptual trap | Mistaking a property of the model for a guarantee about the physical world | Mistaking failure search or a benchmark score for a general safety guarantee |
| Strong personal fit | You enjoy logic puzzles, precise specifications, and explaining correctness | You enjoy experiments, debugging behavior, and improving system throughput |
| Possible later direction | Verification and planning research | Robot evaluation infrastructure and reliability research |

Neither is a requirement to become an expert in all of robotics. We can keep the robot's low-level control fixed and build around it.

## 5. What the competition technologies would do

| Technology | Assurance role | Failure-diagnosis role |
| --- | --- | --- |
| NVIDIA Nemotron | Propose structured plans or repairs | Propose test hypotheses or summarize measured failures, if useful |
| NVIDIA GR00T | Optional learned robot policy to supervise | A candidate existing robot policy to evaluate |
| Nebius Token Factory | Hosted model calls | Hosted model calls if an agent is part of the workflow |
| Nebius AI Cloud | Run the simulator or other application components | Run policy inference and batches of evaluation jobs |
| Docker | Package dependencies so the system can be reproduced | Separate model and simulator dependencies and package workers |

We need a substantive qualifying NVIDIA model integration and qualifying Nebius usage. We do not need every row in the table. A GR00T-based evaluation system running on Nebius could have no chat interface.

**Docker** packages software and dependencies into a container. It makes deployment more repeatable; it does not create missing GPU capabilities or remove all driver compatibility issues.

**An API** is a defined way for one program to call another. Token Factory lets our Python application send requests to a hosted model rather than loading that model ourselves.

**A Serverless Job** runs a containerized workload until it finishes or times out. **An Endpoint** keeps a service available to receive requests. “Serverless” does not mean free compute.

The user has confirmed that cloud compute is among the main hackathon resources. Account access, allocation details, compatible GPU availability, and exact policy checkpoints still need checking. Ask the user to configure cloud credentials when access is needed. No cloud resources have been provisioned for these ideas.

## 6. What I suggest learning first

### Shared foundation

1. Understand the observation → policy → action → environment loop.
2. Learn enough Python to read a simulation loop and manipulate structured data.
3. Run an existing example and identify where it decides success or failure.
4. Learn how to record a configuration and replay an experiment.

### Then try assurance

1. Boolean logic and simple Z3 constraints.
2. Action preconditions and effects.
3. Bounded plan checking and counterexamples.
4. Explaining conflicts.
5. Updating assumptions while execution proceeds.

### Or try failure diagnosis

1. Loading a checkpoint and running rollouts.
2. Controlled scene perturbations.
3. Success/failure metrics and repeated trials.
4. Random search followed by adaptive search.
5. Failure reduction, replay, and parallel execution.

Do not begin by reading every linked paper. Start with the two small exercises above. They expose the kind of work you would actually be doing.

## 7. Sources and suggested reading order

### Assurance

1. [PRoC3S project page](https://aidan-curtis.github.io/proc3s.github.io/) — watch the manipulation examples first; understand why a plausible plan can still be infeasible.
2. [RoboGuard project page](https://robo-guard.github.io/) — understand what a guardrail does between a requested plan and execution.
3. [TAMPEST repository](https://github.com/fbk-pso/tampest) — inspect the problem examples and reproduction instructions when ready for the SMT implementation.
4. [Z3 guide](https://microsoft.github.io/z3guide/) — introductory solver material for the proposed learning exercise.

### Failure diagnosis

1. [COLOSSEUM project page](https://robot-colosseum.github.io/) — look at the perturbation and failure videos.
2. [LIBERO-Plus repository](https://github.com/sylvestf/LIBERO-plus) — see how scene changes are organized into robustness tests.
3. [OopsieVerse project page](https://robin-lab.cs.utexas.edu/oopsieverse/) — understand the difference between task success and avoiding damage.
4. [AllenAI VLA evaluation harness](https://github.com/allenai/vla-evaluation-harness) — a candidate implementation foundation; check the exact supported policy/benchmark combination.
5. [Isaac Lab-Arena](https://github.com/isaac-sim/IsaacLab-Arena) — an alternative evaluation foundation with NVIDIA integration.
6. [VerifAI](https://github.com/BerkeleyLearnVerify/VerifAI) and [Scenic documentation](https://scenic-lang.readthedocs.io/) — read after understanding basic random perturbation testing.

### Platform and competition

- [Hackathon official rules](https://nebiusglobalaihackathon.devpost.com/rules)
- [Nebius Token Factory quickstart](https://docs.tokenfactory.nebius.com/quickstart)
- [Nebius Serverless overview](https://docs.nebius.com/serverless/overview)
- [NVIDIA GR00T workflow](https://developer.nvidia.com/blog/develop-humanoid-robot-policies-end-to-end-with-nvidia-isaac-gr00t/)
- [Isaac Sim hardware requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/requirements.html)

## 8. The decision to make

Choose **assurance** if you are most curious about:

> How do I turn requirements into precise checks, and what can I establish about the robot's next steps?

Choose **failure diagnosis** if you are most curious about:

> How do I systematically discover where a robot breaks, explain the conditions, and help someone fix it?

You can choose either without committing to the other. My suggested next step is a small hands-on example of each before selecting the final project.
