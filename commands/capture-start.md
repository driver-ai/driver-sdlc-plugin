---
description: Resume rolling session capture (flips rolling_capture on in ~/.driver/config.json)
argument-hint: ""
allowed-tools: Bash, Read
---

# /drvr:capture-start

## Step 1 — Flip the flag

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/set_rolling_capture.py" --on

## Step 2 — Report

Relay the script's output. If it started capture: rolls resume from the next turn boundary.
Stop anytime with /drvr:capture-stop. If it reported "already started", say so. Note the
scope: this affects rolling capture only — the on-demand /drvr:capture-session command has
its own gate (trajectory_capture) and is not changed.
