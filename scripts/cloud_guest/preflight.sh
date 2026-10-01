#!/usr/bin/env bash
set -euo pipefail

[[ $# == 1 ]] || { echo 'usage: preflight.sh SESSION' >&2; exit 2; }
SESSION=$1
[[ $SESSION =~ ^/home/robot/[A-Za-z0-9._/-]+$ && $SESSION != */ && $SESSION != *//* && $SESSION != *'/../'* && $SESSION != *'/./'* && $SESSION != *'/..' && $SESSION != *'/.' ]] || { echo 'unsafe session path' >&2; exit 2; }
[[ -d $SESSION && $(realpath -e -- "$SESSION") == "$SESSION" ]] || { echo 'session must be an existing contained directory' >&2; exit 2; }

date -u
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
systemctl is-active docker
if ! systemctl is-active nvidia-fabricmanager; then
  echo 'fabricmanager inactive; CUDA allocation remains authoritative' >&2
fi
/home/robot/.venvs/vla-eval/bin/python -c 'import torch; x=torch.ones((64,64),device="cuda"); assert torch.cuda.is_available() and (x@x)[0,0].item()==64; torch.cuda.synchronize(); print("CUDA allocation/matmul/synchronize passed")'
[[ $(git -C /home/robot/vla-evaluation-harness rev-parse HEAD) == 35f1200eb15608aa898f727a3722f7eef889c6cd ]] || { echo 'upstream revision mismatch' >&2; exit 2; }
PYTHONPATH="$SESSION/source/src" /home/robot/.venvs/vla-eval/bin/python -c 'from robot_debug.libero import DiagnosticLIBEROBenchmark; suite="libero_object"; seed=7; all_tasks=DiagnosticLIBEROBenchmark(suite=suite,seed=seed).get_tasks(); ids={row["task_id"] for row in all_tasks}; assert {0,1,2} <= ids; [(lambda chosen, task_id: (_ for _ in ()).throw(ValueError("task catalog mismatch")) if len(chosen)!=1 or chosen[0]["task_id"]!=task_id else None)(DiagnosticLIBEROBenchmark(suite=suite,seed=seed,task_id=task_id).get_tasks(),task_id) for task_id in (0,1,2)]; print("task catalog 0/1/2 passed")'
echo 'guest preflight passed'
