#!/bin/sh
# SessionStart hook: on a genuinely NEW session (source=startup), record an index
# entry under the branch arc key, with lineage to the most-recent prior session of
# that branch+cwd. The roll path later enriches it with counts/cost (branch-keyed).
# Local-only, config-gated, fail-open. Always exits 0. No set -e.

INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || exit 0
CONFIG="$HOME/.driver/config.json"
[ -r "$CONFIG" ] || exit 0
[ "$(jq -r '.rolling_capture // false' "$CONFIG" 2>/dev/null)" = "true" ] || exit 0

SOURCE="$(printf '%s' "$INPUT" | jq -r '.source // empty' 2>/dev/null)"
[ "$SOURCE" = "startup" ] || exit 0          # only a new session needs a fresh entry
SID="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)"
[ -n "$SID" ] || exit 0
[ -n "$CWD" ] || exit 0                       # no cwd -> skip (don't guess the hook's pwd)
BRANCH="$(git -C "$CWD" branch --show-current 2>/dev/null)"

INDEX="$HOME/.driver/capture/index.json"
DRVR_PLUGIN_ROOT="$PLUGIN_ROOT" python3 - "$INDEX" "$SID" "$CWD" "$BRANCH" <<'PY' || exit 0
import json, os, sys, datetime
sys.path.insert(0, os.path.join(os.environ["DRVR_PLUGIN_ROOT"], "scripts", "capture"))
from capture_store_core import group_key_for, update_index, resolve_lineage
index_path, sid, cwd, branch = sys.argv[1], sys.argv[2], os.path.realpath(sys.argv[3]), (sys.argv[4] or None)
index = {}
if os.path.exists(index_path):
    try:
        index = json.load(open(index_path))
    except Exception as e:
        print(f"Warning: capture index unreadable ({e.__class__.__name__}); "
              f"treating as empty: {index_path}", file=sys.stderr)
        index = {}
# task/spec ids are not on any hook payload and the rolled store never carries them;
# the rolling index keys on the branch arc. The roll path enriches this same
# branch:<x> entry in place with real counts/cost.
gk = group_key_for(None, None, branch)
if gk == "ungrouped":
    sys.exit(0)              # off-git / no branch is not a real arc; don't bloat the index
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
prev = resolve_lineage(index, gk, cwd, sid)
# counts seeded as None (not 0) so the first real roll overwrites them (is-None merge)
entry = {"group_key": gk, "session_id": sid, "cwd": cwd,
         "first_seen": now, "last_seen": now, "record_count": None,
         "total_cost_usd": None, "prev_session_id": prev}
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

exit 0
