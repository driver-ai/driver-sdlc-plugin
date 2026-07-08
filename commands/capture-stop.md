---
description: Stop rolling session capture (flips rolling_capture off in ~/.driver/config.json)
argument-hint: ""
allowed-tools: Bash, Read
---

# /drvr:capture-stop

## Step 1 — Flip the flag

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/set_rolling_capture.py" --off

## Step 2 — Report

Relay the script's output. If it stopped capture: from the next turn boundary, no further
rolls occur; already-captured data under ~/.driver/capture is left untouched. Restart anytime
with /drvr:capture-start. If it reported "already stopped", say so. Note the scope: this
affects rolling capture only — the on-demand /drvr:capture-session command has its own gate
(trajectory_capture) and is not changed.
