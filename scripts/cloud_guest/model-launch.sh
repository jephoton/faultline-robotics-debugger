#!/usr/bin/env bash
set -euo pipefail

[[ $# == 1 ]] || { echo 'usage: model-launch.sh SESSION' >&2; exit 2; }
SESSION=$1
[[ $SESSION =~ ^/home/robot/[A-Za-z0-9._/-]+$ && $SESSION != */ && $SESSION != *//* && $SESSION != *'/../'* && $SESSION != *'/./'* && $SESSION != *'/..' && $SESSION != *'/.' ]] || { echo 'unsafe session path' >&2; exit 2; }
[[ -d $SESSION && $(realpath -e -- "$SESSION") == "$SESSION" ]] || { echo 'session must be an existing contained directory' >&2; exit 2; }
[[ ! -e $SESSION/model-server.pid && ! -e $SESSION/model-server.log ]] || { echo 'model launch already claimed' >&2; exit 2; }

UPSTREAM=/home/robot/vla-evaluation-harness
PY=/home/robot/.cache/uv/environments-v2/lerobot-a05c932b8b6ff773/bin/python
[[ $(git -C "$UPSTREAM" rev-parse HEAD) == 35f1200eb15608aa898f727a3722f7eef889c6cd ]] || { echo 'upstream revision mismatch' >&2; exit 2; }
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 UV_OFFLINE=1
"$PY" -c 'from huggingface_hub import snapshot_download; p=snapshot_download("nvidia/gr00t17-lerobot-libero_object-640",local_files_only=True); assert p.endswith("1499db357f6ca3762b56c2e8c00b530eb9a09444"),p; print(p)' > "$SESSION/checkpoint-resolution.log"
cd "$UPSTREAM"
nohup "$PY" "$UPSTREAM/src/vla_eval/model_servers/lerobot.py" \
  --port=8000 --args.device=cuda --args.policy_type=groot \
  --args.checkpoint=nvidia/gr00t17-lerobot-libero_object-640 \
  --args.state_key=observation.state --args.chunk_size=null \
  --args.image_keys='{"agentview":"observation.images.image","wrist":"observation.images.wrist_image"}' \
  --args.policy_kwargs='{"base_model_path":"nvidia/GR00T-N1.7-3B"}' \
  > "$SESSION/model-server.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$SESSION/model-server.pid"
echo 'model launch requested; cached checkpoint revision validated'
