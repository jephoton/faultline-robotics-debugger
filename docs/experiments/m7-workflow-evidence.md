# M7: public evidence for the "episode n failed → start n" workflow (October 19, 2026)

**Question:** how does a team evaluating a policy on LIBERO see a failing
episode? Does its episode number map to a Faultline start?

**Method:** read-only review of public repositories, issues and papers.
Commits are pinned. "Verified" means the file or page was opened. Nothing
here is reproduced from third-party figures; link to them instead.

## The mapping, per evaluation tool

| Tool | Per-episode record | Episode number = start? |
| --- | --- | --- |
| [allenai/vla-evaluation-harness](https://github.com/allenai/vla-evaluation-harness/blob/41bd8a44dbe5ba0f7902adb5b7c121c1c174dc84/src/vla_eval/benchmarks/libero/benchmark.py#L186-L210) | Result JSON with `episode_id` and `success` | **Yes**, counted from 0: `set_init_state(initial_states[episode_idx])`. An optional throughput mode wraps the index. |
| [OpenVLA](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/experiments/robot/libero/run_libero_eval.py) and [OpenVLA-OFT](https://github.com/moojink/openvla-oft/blob/e4287e94541f459edc4feabc4e181f537cd569a8/experiments/robot/libero/run_libero_eval.py#L386-L440) | Text log "Starting episode k… Success: …" and a rollout video per episode (`--episode=…--success=…--task=…`) | Uses `initial_states[episode_idx]`, but the log counts from 1 within a task, and the video name counts from 1 across tasks. |
| [openpi](https://github.com/Physical-Intelligence/openpi/blob/215abfb217dbac7d5f1273282331b9b1866c0479/examples/libero/main.py#L82-L186) | Text log; videos named by task and outcome only | Uses `initial_states[episode_idx]`; the video name has no index. |
| [Original LIBERO](https://github.com/Lifelong-Robot-Learning/LIBERO/blob/8f1084e3132a39270c3a13ebe37270a43ece2a01/libero/lifelong/metric.py#L104-L157) | Success rate per task only | Not reported per episode. |
| [Isaac-GR00T](https://github.com/NVIDIA/Isaac-GR00T/blob/dac54b313160c201c450f97df0fd74ebd379c892/gr00t/eval/sim/LIBERO/libero_env.py#L161-L167) | Overall success rate; videos named by a random id and outcome | **No**: the environment is seeded and reset without `set_init_state` (inferred from this file). |
| [LeRobot](https://github.com/huggingface/lerobot/blob/146d8474932c8b566717eb2738ba459337ab71c4/src/lerobot/scripts/lerobot_eval.py#L676-L689) | `eval_info.json` with `per_episode` and videos `eval_episode_{n}.mp4` | Not reliably: resets can drift ([lerobot#4152](https://github.com/huggingface/lerobot/issues/4152)). |

**Conclusion:** the mapping holds in the standard LIBERO setup (counted from
0), as in the vla-evaluation-harness. It does not hold for every tool. The
panel, the Reference and the runbook were reworded on October 19 so they no
longer say "always".

## The same failure, found independently

The vla-evaluation-harness publishes per-episode results for GR00T N1.6 (a
community checkpoint, not our N1.7) on LIBERO-10:
[`merged_libero_10.json`, lines 1570–1577](https://github.com/allenai/vla-evaluation-harness/blob/41bd8a44dbe5ba0f7902adb5b7c121c1c174dc84/docs/reproductions/data/groot-libero/merged_libero_10.json#L1570-L1577).
The file is stored with Git LFS, so the raw view may be needed. It records
`"episode_id": 14`, `"success": false` for "put both the alphabet soup and
the tomato sauce in the basket". That is LIBERO-10 task 0, start 14: the
start Faultline diagnoses in `FL-S-AFB5` and in the October 19 showcase
run 2.

This shows a different policy version failing on the same start in a public
evaluation. That is how a team would come to Faultline: "task 0, episode 14
failed". It does not show that the cause is the same.

## Stability of a start number

- LeRobot's LIBERO docs advise fixed init states and the same seed to compare
  policies "on the same episodes"
  ([libero.mdx](https://github.com/huggingface/lerobot/blob/146d8474932c8b566717eb2738ba459337ab71c4/docs/source/libero.mdx)).
- The harness's
  [common pitfalls](https://github.com/allenai/vla-evaluation-harness/blob/41bd8a44dbe5ba0f7902adb5b7c121c1c174dc84/docs/reproductions/common-pitfalls.md)
  note that the environment seed can still move objects under a fixed init
  state.
- Issues show the same index behaving differently:
  - [openvla#342](https://github.com/openvla/openvla/issues/342): fixture
    placement varied when an environment was reused;
  - [openvla#172](https://github.com/openvla/openvla/issues/172): seeds had
    no effect;
  - [LIBERO#141](https://github.com/Lifelong-Robot-Learning/LIBERO/issues/141)
    and [lerobot#4390](https://github.com/huggingface/lerobot/issues/4390):
    an object does not settle, depending on the MuJoCo version.

A start number is therefore a stable reference only together with the
simulator versions and reset policy. Faultline pins these in its image, and
a failure counts only when it repeats 4 of 5 times.

## For the demo and Devpost

Show the harness JSON entry (episode 14 failed on the soup-and-sauce task)
next to Faultline's New diagnosis with LIBERO-10, task 0, start 14. Link to
it; do not copy it. Mention in one line that some tools count episodes from
1.
