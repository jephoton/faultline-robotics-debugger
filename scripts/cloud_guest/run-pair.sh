#!/usr/bin/env bash
set -euo pipefail

[[ $# == 1 ]] || { echo 'usage: run-pair.sh SESSION' >&2; exit 2; }
SESSION=$1
[[ $SESSION =~ ^/home/robot/[A-Za-z0-9._/-]+$ && $SESSION != */ && $SESSION != *//* && $SESSION != *'/../'* && $SESSION != *'/./'* && $SESSION != *'/..' && $SESSION != *'/.' ]] || { echo 'unsafe session path' >&2; exit 2; }
[[ -d $SESSION && $(realpath -e -- "$SESSION") == "$SESSION" ]] || { echo 'session must be an existing contained directory' >&2; exit 2; }
[[ -d $SESSION/pair-claim ]] || { echo 'missing launch claim' >&2; exit 2; }

terminal() {
  status=$?
  printf 'pair terminal exit=%s utc=%s\n' "$status" "$(date -u --iso-8601=seconds)" >> "$SESSION/pair-events.log"
}
trap terminal EXIT
PROJECT="$SESSION/source"
UPSTREAM=/home/robot/vla-evaluation-harness
PY=/home/robot/.venvs/vla-eval/bin/python
export PATH=/home/robot/.venvs/vla-eval/bin:$PATH PYTHONPATH="$PROJECT/src"
[[ -d $PROJECT && -f $SESSION/source.bundle && -f $SESSION/expected-source-sha.txt && -f $SESSION/manifest.json && -f $SESSION/deadline.txt ]] || { echo 'missing inputs' >&2; exit 2; }
EXPECTED_SHA=$(tr -d '\r\n' < "$SESSION/expected-source-sha.txt")
[[ $EXPECTED_SHA =~ ^[a-f0-9]{64}$ ]] || { echo 'invalid source SHA' >&2; exit 2; }
[[ $(sha256sum "$SESSION/source.bundle" | cut -d' ' -f1) == "$EXPECTED_SHA" ]] || { echo 'source bundle SHA mismatch' >&2; exit 2; }
[[ $(git -C "$UPSTREAM" rev-parse HEAD) == 35f1200eb15608aa898f727a3722f7eef889c6cd ]] || { echo 'upstream revision mismatch' >&2; exit 2; }
grep -F 'ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0' "$PROJECT/scripts/run_failure_search.py" >/dev/null
curl -fsS --max-time 5 http://127.0.0.1:8000/config > "$SESSION/model-server-config.json"
grep -F 'nvidia/gr00t17-lerobot-libero_object-640' "$SESSION/model-server.log" >/dev/null
grep -F '1499db357f6ca3762b56c2e8c00b530eb9a09444' "$SESSION/checkpoint-resolution.log" >/dev/null
grep -F 'nvidia/gr00t17-lerobot-libero_object-640' "$SESSION/model-server-config.json" >/dev/null
DEADLINE=$(date -u -d "$(tr -d '\r\n' < "$SESSION/deadline.txt")" +%s)
[[ $DEADLINE =~ ^[0-9]+$ ]] || { echo 'invalid deadline' >&2; exit 2; }
RATE=$(tr -d '\r\n' < "$SESSION/hourly-rate.txt")
USD=$("$PY" -c 'import math,sys; r=float(sys.argv[1]); math.isfinite(r) and r>0 or sys.exit("invalid hourly rate"); print(repr(r*1800/3600))' "$RATE")
CONTAINERS=$(docker ps --format '{{.Names}}')
if grep -q '^vla-eval-' <<< "$CONTAINERS"; then
  echo 'unsafe: evaluator container already active' >&2; exit 2
fi

for MODE in sequential-jobs adaptive-portfolio; do
  NAME=sequential; REQUIRED=4500; CAP=()
  if [[ $MODE == adaptive-portfolio ]]; then NAME=adaptive; REQUIRED=2400; CAP=(--max-workers 2); fi
  REMAINING=$((DEADLINE - $(date -u +%s)))
  [[ $REMAINING -ge $REQUIRED ]] || { echo "insufficient deadline for $MODE" >&2; exit 2; }
  [[ ! -e $SESSION/$NAME ]] || { echo "existing $MODE output" >&2; exit 2; }
  printf 'mode begin=%s utc=%s remaining=%s\n' "$MODE" "$(date -u --iso-8601=seconds)" "$REMAINING" >> "$SESSION/pair-events.log"
  set +e
  "$PY" "$PROJECT/scripts/run_diagnostic_portfolio.py" --manifest "$SESSION/manifest.json" \
    --mode "$MODE" "${CAP[@]}" --results-root "$SESSION/$NAME" --upstream-root "$UPSTREAM" \
    --project-root "$PROJECT" --episodes 111 --seconds 1800 --estimated-usd "$USD" --hourly-rate "$RATE" \
    > "$SESSION/$NAME-runner.log" 2>&1
  STATUS=$?
  set -e
  printf 'mode end=%s exit=%s utc=%s\n' "$MODE" "$STATUS" "$(date -u --iso-8601=seconds)" >> "$SESSION/pair-events.log"
  [[ $STATUS == 0 || $STATUS == 1 ]] || { echo "runner crashed in $MODE" >&2; exit "$STATUS"; }
  "$PY" "$SESSION/validate-mode.py" "$SESSION" "$MODE"
  CONTAINERS=$(docker ps --format '{{.Names}}')
  if grep -q '^vla-eval-' <<< "$CONTAINERS"; then
    echo 'unsafe: evaluator container still active' >&2; exit 2
  fi
done
