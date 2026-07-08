#!/bin/sh
# Stop / SessionEnd hook: roll the current session's redacted trajectory to a keyed
# local store. Local-only, config-gated, throttled, fail-open. Per-turn (Stop) work
# is backgrounded so the turn is never blocked; the SessionEnd finalize runs in the
# foreground (forced, unthrottled) so the final roll completes before teardown.
# Always exits 0. No set -e.

INPUT="$(cat)"                                   # consume stdin (hook protocol)

# Hook shells (notably GUI-launched Claude Code on macOS) often don't inherit the
# interactive shell's PATH, so uv — installed to ~/.local/bin (or ~/.cargo/bin) — is
# invisible and the roll silently no-ops at the `command -v uv` gate below. (jq and
# python3 stay resolvable via the inherited PATH, which is why SessionStart still runs.)
# Make ONLY uv findable, and only when it isn't already: APPEND its dir so we never
# shadow an already-working tool. Prepending package-manager dirs like /usr/local/bin
# is deliberately avoided — it can put a broken python3 (e.g. a dangling python.org
# symlink) ahead of the homebrew one and turn the redact step into a silent no-op.
if ! command -v uv >/dev/null 2>&1; then
  for _d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    if [ -x "$_d/uv" ]; then PATH="$PATH:$_d"; export PATH; break; fi
  done
fi

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
# backs off instead of re-spawning logs2atif every turn. The mktemp template ends in
# the X-run (no suffix) so it is portable on BSD/macOS mktemp.
do_roll() {
  mkdir -p "$STORE_DIR" 2>/dev/null || return 0
  TMP="$(mktemp "${TMPDIR:-/tmp}/driver-roll-$SID.XXXXXX")" || return 0
  # --session-dir locates subagent sidechains at <dir>/<session_id>/subagents/.
  if uv run --with 'logs2atif @ git+ssh://git@github.com/driver-ai/logs2atif.git@3364a76' python "$PLUGIN_ROOT/scripts/capture/cc_to_atif.py" \
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

# --- per-roll branch-keyed enrich (authoritative index writer) ---
# Runs after do_roll. Derives branch from cwd (git) and reads final_metrics
# (counts/cost only — content-free) from the just-written REDACTED store, then
# enriches the session's branch:<branch> index entry with real counts/cost. Task/spec
# are NOT read — the rolled store never carries them.
update_index_from_store() {
  STORE="$HOME/.driver/capture/sessions/$SID/trajectory.redacted.json"
  [ -f "$STORE" ] || return 0
  CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)"
  # Stop/SessionEnd may omit .cwd from the hook payload; fall back to the cwd recorded on
  # the last transcript record that HAS one. Most but not all record types carry .cwd —
  # trailing `mode` / `last-prompt` / `file-history-snapshot` records do NOT (~20% of real
  # transcripts end in such a record), so `tail -n 1 | jq .cwd` is unreliable; scan
  # BACKWARD for the last record with a .cwd so the authoritative writer never hinges on an
  # absent payload field (RUN-verified to recover the cwd where tail -n 1 returns empty).
  [ -n "$CWD" ] || CWD="$(python3 -c 'import sys, json
for line in reversed(open(sys.argv[1]).read().splitlines()):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if rec.get("cwd"):
        print(rec["cwd"]); break' "$TRANSCRIPT" 2>/dev/null)"
  [ -n "$CWD" ] || return 0
  BRANCH="$(git -C "$CWD" branch --show-current 2>/dev/null)"
  INDEX="$HOME/.driver/capture/index.json"
  DRVR_PLUGIN_ROOT="$PLUGIN_ROOT" python3 - "$INDEX" "$STORE" "$SID" "$CWD" "$BRANCH" <<'PY' || return 0
import json, os, sys, datetime
sys.path.insert(0, os.path.join(os.environ["DRVR_PLUGIN_ROOT"], "scripts", "capture"))
from capture_store_core import group_key_for, update_index, resolve_lineage
index_path, store_path, sid, cwd, branch = (
    sys.argv[1], sys.argv[2], sys.argv[3], os.path.realpath(sys.argv[4]), (sys.argv[5] or None))
try:
    traj = json.load(open(store_path))
except Exception:
    sys.exit(0)
fm = traj.get("final_metrics") or {}
index = {}
if os.path.exists(index_path):
    try:
        index = json.load(open(index_path))
    except Exception as e:
        print(f"Warning: capture index unreadable ({e.__class__.__name__}); "
              f"treating as empty: {index_path}", file=sys.stderr)
        index = {}
# branch-keyed rolling arc (no task/spec read). The same key SessionStart wrote, so
# this enriches in place; a branch switch mid-session migrates the entry.
gk = group_key_for(None, None, branch)
if gk == "ungrouped":
    sys.exit(0)             # off-git roll: not a real arc; don't bloat the index
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
prev = resolve_lineage(index, gk, cwd, sid)
# fm.get(...) is None when a metric is absent -> the is-None merge keeps the prior;
# a genuine 0/0.0 (free/cached roll) is a real value and overwrites.
entry = {"group_key": gk, "session_id": sid, "cwd": cwd,
         "first_seen": now, "last_seen": now,
         "store_path": store_path,
         "record_count": fm.get("total_steps"),
         "total_cost_usd": fm.get("total_cost_usd"),
         "prev_session_id": prev}
index = update_index(index, entry)
os.makedirs(os.path.dirname(index_path), exist_ok=True)
tmp = index_path + ".tmp." + str(os.getpid())
try:
    json.dump(index, open(tmp, "w"), indent=2)
    os.replace(tmp, index_path)
finally:
    if os.path.exists(tmp):
        os.remove(tmp)
PY
}

# call it after do_roll (foreground on SessionEnd, inside the backgrounded subshell
# on Stop so it never blocks the turn):
if [ "$EVENT" = "SessionEnd" ]; then
  do_roll
  update_index_from_store
else
  ( do_roll; update_index_from_store ) >/dev/null 2>&1 &
fi

exit 0
