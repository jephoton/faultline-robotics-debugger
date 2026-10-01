#!/usr/bin/env bash
set -euo pipefail

[[ $# == 1 ]] || { echo 'usage: launch-pair.sh SESSION' >&2; exit 2; }
SESSION=$1
[[ $SESSION =~ ^/home/robot/[A-Za-z0-9._/-]+$ && $SESSION != */ && $SESSION != *//* && $SESSION != *'/../'* && $SESSION != *'/./'* && $SESSION != *'/..' && $SESSION != *'/.' ]] || { echo 'unsafe session path' >&2; exit 2; }
[[ -d $SESSION && $(realpath -e -- "$SESSION") == "$SESSION" ]] || { echo 'session must be an existing contained directory' >&2; exit 2; }
[[ -f $SESSION/run-pair.sh && -f $SESSION/validate-mode.py ]] || { echo 'missing guest scripts' >&2; exit 2; }
[[ ! -e $SESSION/sequential && ! -e $SESSION/adaptive && ! -e $SESSION/runner.pid && ! -e $SESSION/runner.log ]] || { echo 'existing pair output or launch' >&2; exit 2; }
CLAIM="$SESSION/pair-claim"
mkdir -- "$CLAIM" || { echo 'pair already claimed; ambiguous launch must not retry' >&2; exit 2; }
printf '%s\n' "session=$SESSION" 'run_label=sequential-jobs+adaptive-portfolio' "claimed_utc=$(date -u --iso-8601=seconds)" > "$CLAIM/identity"
sync -f "$CLAIM/identity"
nohup bash "$SESSION/run-pair.sh" "$SESSION" > "$SESSION/runner.log" 2>&1 < /dev/null &
PID=$!
printf '%s\n' "$PID" > "$CLAIM/pid"
printf '%s\n' "$PID" > "$SESSION/runner.pid"
sync -f "$CLAIM/pid"
sync -f "$SESSION/runner.pid"
printf 'pair launched pid %s\n' "$PID"
