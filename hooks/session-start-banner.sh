#!/bin/sh
# Capture-awareness banner. Local-only, config-gated, fail-open.
command -v python3 >/dev/null 2>&1 || exit 0
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || exit 0
PAYLOAD="$(cat 2>/dev/null)" || PAYLOAD=""
DRVR_PLUGIN_ROOT="$PLUGIN_ROOT" DRVR_PAYLOAD="$PAYLOAD" python3 - <<'PY' 2>/dev/null || exit 0
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["DRVR_PLUGIN_ROOT"], "scripts", "capture"))
from capture_config_core import banner_hook_json
try:
    payload = json.loads(os.environ.get("DRVR_PAYLOAD") or "{}")
except ValueError:
    sys.exit(0)
try:
    with open(os.path.join(os.path.expanduser("~"), ".driver", "config.json"), encoding="utf-8") as f:
        config = json.load(f)
except (OSError, ValueError):
    sys.exit(0)
out = banner_hook_json(config, payload.get("source") if isinstance(payload, dict) else None)
if out:
    print(out)
PY
exit 0
