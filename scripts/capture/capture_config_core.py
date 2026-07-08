"""Pure core for capture control + indicator decisions.

Values in, values out -- no I/O, time, randomness, or shared mutable state.
"""
from __future__ import annotations

import json

BANNER_SOURCES = frozenset({"startup", "resume", "clear"})
BADGE = "📹 capturing"
_BANNER_TEXT = (
    "🔴 Capture ON — this session is being recorded to the local rolling store "
    "(~/.driver/capture). Stop with /drvr:capture-stop."
)


def is_rolling_capture_enabled(config: object) -> bool:
    """True when config is a dict and rolling_capture is True or "true" -- parity with the
    shipped jq gates (`.rolling_capture // false` string-compared to "true")."""
    if not isinstance(config, dict):
        return False
    value = config.get("rolling_capture")
    return value is True or value == "true"


def set_rolling_capture(config: object, enabled: bool) -> tuple[dict, bool]:
    """Return (new_config, changed). Non-dict config treated as {} (read tolerance; the shell
    refuses non-dict files on disk before calling); unknown keys preserved; input never mutated.
    Writes the exact boolean: changed is False only when the stored value already is that
    boolean (isinstance check -- 1 == True in Python); non-bool values are normalized. Absent
    key + enabled=False -> changed=False (no key invented)."""
    base = dict(config) if isinstance(config, dict) else {}
    if "rolling_capture" not in base and not enabled:
        return base, False
    stored = base.get("rolling_capture")
    if isinstance(stored, bool) and stored == enabled:
        return base, False
    base["rolling_capture"] = enabled
    return base, True


def banner_message(config: object, source: object) -> str | None:
    """Banner text when enabled and source in BANNER_SOURCES; else None."""
    if (is_rolling_capture_enabled(config)
            and isinstance(source, str) and source in BANNER_SOURCES):
        return _BANNER_TEXT
    return None


def banner_hook_json(config: object, source: object) -> str | None:
    """Full hook stdout line: json.dumps({"continue": True, "systemMessage": msg}); None when
    banner_message is None. Default ensure_ascii kept deliberately (locale-proof stdout)."""
    message = banner_message(config, source)
    if message is None:
        return None
    return json.dumps({"continue": True, "systemMessage": message})


def statusline_badge(config: object) -> str:
    """BADGE when enabled, empty string otherwise."""
    return BADGE if is_rolling_capture_enabled(config) else ""
