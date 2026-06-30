#!/bin/sh
# Stop / SessionEnd hook: roll the current session's redacted trajectory to a keyed
# local store. Local-only, config-gated, throttled, fail-open. Per-turn (Stop) work
# is backgrounded so the turn is never blocked; the SessionEnd finalize runs in the
# foreground (forced, unthrottled) so the final roll completes before teardown.
# Always exits 0. No set -e.

INPUT="$(cat)"                                   # consume stdin (hook protocol)
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0     # python3 backs the pure throttle

# Resolve the plugin root from $0 (hooks.json passes the full expanded command path).
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || exit 0

# Config gate: rolling_capture must be explicitly true.
CONFIG="$HOME/.driver/config.json"
[ -r "$CONFIG" ] || exit 0
[ "$(jq -r '.rolling_capture // false' "$CONFIG" 2>/dev/null)" = "true" ] || exit 0

SID="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)"
EVENT="$(printf '%s' "$INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null)"
[ -n "$SID" ] && [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0
command -v uv >/dev/null 2>&1 || exit 0          # roll path needs uv; degrade

# Guard on the WRITE path: reject a session_id that is not a safe single path
# segment before it is ever joined into a filesystem path (mirrors is_safe_path_component).
# Real Claude Code session ids are UUIDs and always pass.
case "$SID" in
  ""|.*)    exit 0 ;;        # empty, '.', '..', or any leading-dot
  */*|*\\*) exit 0 ;;        # path separators
esac

STORE_DIR="$HOME/.driver/capture/sessions/$SID"
STATE="$STORE_DIR/roll-state.json"
CUR_COUNT="$(wc -l < "$TRANSCRIPT" 2>/dev/null | tr -d ' ')"
CUR_MTIME="$(stat -f %m "$TRANSCRIPT" 2>/dev/null || stat -c %Y "$TRANSCRIPT" 2>/dev/null)"
[ -n "$CUR_COUNT" ] && [ -n "$CUR_MTIME" ] || exit 0   # transcript vanished/unreadable

# Throttle (pure should_roll via a tiny python3 heredoc) — UNLESS this is the
# SessionEnd finalize, which forces a final roll regardless of the throttle.
if [ "$EVENT" != "SessionEnd" ]; then
  ROLL="$(DRVR_PLUGIN_ROOT="$PLUGIN_ROOT" python3 - "$STATE" "$CUR_COUNT" "$CUR_MTIME" <<'PY' 2>/dev/null
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["DRVR_PLUGIN_ROOT"], "scripts", "capture"))
from capture_store_core import should_roll, RollThreshold
state_path, cur_count, cur_mtime = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
prev_count, prev_mtime = 0, 0.0
try:
    s = json.load(open(state_path)); prev_count = s.get("record_count", 0); prev_mtime = s.get("mtime", 0.0)
except Exception:
    pass
print("1" if should_roll(prev_count, prev_mtime, cur_count, cur_mtime, RollThreshold()) else "0")
PY
)"
  [ "$ROLL" = "1" ] || exit 0
fi

# do_roll: convert -> redact -> keyed store. The store only ever holds the redacted
# artifact, PUBLISHED ATOMICALLY (write a $$-suffixed temp in the store dir, then mv),
# so an overlapping roll or a concurrent flush never sees a torn file. roll-state is
# advanced whether or not the convert succeeds, so a persistently-failing convert
# backs off instead of re-spawning harbor every turn. The mktemp template ends in the
# X-run (no suffix) so it is portable on BSD/macOS mktemp.
do_roll() {
  mkdir -p "$STORE_DIR" 2>/dev/null || return 0
  TMP="$(mktemp "${TMPDIR:-/tmp}/driver-roll-$SID.XXXXXX")" || return 0
  # --session-dir locates subagent sidechains at <dir>/<session_id>/subagents/.
  if uv run --with 'harbor~=0.16' python "$PLUGIN_ROOT/scripts/capture/cc_to_atif.py" \
        "$TRANSCRIPT" --session-dir "$(dirname "$TRANSCRIPT")" --out "$TMP" >/dev/null 2>&1; then
    RTMP="$STORE_DIR/.redacted.$$.tmp"
    FTMP="$STORE_DIR/.flags.$$.tmp"
    if python3 "$PLUGIN_ROOT/scripts/capture/redact.py" \
          "$TMP" --out "$RTMP" --flags-out "$FTMP" >/dev/null 2>&1; then
      mv "$RTMP" "$STORE_DIR/trajectory.redacted.json"    # atomic publish
      mv "$FTMP" "$STORE_DIR/flags.json"
    fi
    rm -f "$RTMP" "$FTMP"
  fi
  printf '{"record_count":%s,"mtime":%s}\n' "$CUR_COUNT" "$CUR_MTIME" > "$STATE.$$.tmp" \
    && mv "$STATE.$$.tmp" "$STATE"                          # advance throttle (backoff)
  rm -f "$TMP"
}

if [ "$EVENT" = "SessionEnd" ]; then
  do_roll                       # foreground: must complete before teardown
else
  do_roll >/dev/null 2>&1 &     # background: never block the turn
fi

exit 0
