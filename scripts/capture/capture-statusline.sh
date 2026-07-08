#!/bin/sh
# Capture badge for statusLine. Prints "📹 capturing" or nothing. Always exits 0.
cat >/dev/null 2>&1 || true
command -v python3 >/dev/null 2>&1 || exit 0
SELF_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || exit 0
DRVR_CORE_DIR="$SELF_DIR" python3 - <<'PY' 2>/dev/null || exit 0
import json, os, sys
sys.path.insert(0, os.environ["DRVR_CORE_DIR"])
from capture_config_core import statusline_badge
try:
    with open(os.path.join(os.path.expanduser("~"), ".driver", "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except (OSError, ValueError):
    config = None
badge = statusline_badge(config)
if badge:
    print(badge)
PY
exit 0
