---
description: Capture the current Claude Code session as a redacted ATIF trajectory, review it in-chat and in the trajectory viewer, and — only after explicit approval — save it locally (default) or register it to a self-hosted Opik store.
argument-hint: [--task-id ID] [--spec-id ID] [--intent "..."] [--project NAME] [--upload-opik]
allowed-tools: Bash, Read, Glob, AskUserQuestion
---

# /drvr:capture-session

Capture the **current** Claude Code session, normalize it into a redacted ATIF
trajectory tied to the active task/spec, review it in-chat with redaction flags,
optionally inspect it in the trajectory viewer, and — only after the developer
approves — save the redacted trajectory locally (default) or register it to a
self-hosted Opik store (opt-in).

**Nothing leaves the machine before approval.** The `AskUserQuestion` gate
(Step 6) is the load-bearing governance control: no network egress runs before
it, and the default approved action is a local save with no egress.

**Scripts** (referenced via `${CLAUDE_PLUGIN_ROOT}`; the convert/redact/render
scripts are pure stdlib, the Opik path needs `uv`):
- `${CLAUDE_PLUGIN_ROOT}/scripts/capture/cc_to_atif.py` — JSONL transcript -> ATIF
- `${CLAUDE_PLUGIN_ROOT}/scripts/capture/redact.py` — secret redaction pass
- `${CLAUDE_PLUGIN_ROOT}/scripts/capture/render_trace.py` — egress-safe summary + local HTML review
- `${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_viewer.py` — feed the redacted trajectory into the trajectory viewer
- `${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_opik.py` — redacted ATIF -> Opik trace + spans

All in-flow artifacts live in the well-known per-run dir
`~/.driver/capture/current` (recreated fresh each run, removed on reject).

---

## Step 0 — Config gate (capture must be explicitly enabled)

Trajectory capture is **off by default**. Read the flag from the user's config and
stop unless it is explicitly `true`:

```bash
ENABLED=false
if command -v jq >/dev/null 2>&1 && [ -r "$HOME/.driver/config.json" ]; then
    VAL="$(jq -r '.trajectory_capture // false' "$HOME/.driver/config.json" 2>/dev/null)"
    [ "$VAL" = "true" ] && ENABLED=true
fi
```

If `ENABLED` is not `true` (missing/unreadable config, no `jq`, or the flag is
`false`), capture is **disabled**. Print the enable instructions and **exit 0** —
do NOT capture anyway:

```
Trajectory capture is disabled. To enable it, set:
  "trajectory_capture": true
in ~/.driver/config.json, then re-run /drvr:capture-session.
```

"Fail-open" here means *never crash* — it does **not** mean "capture regardless".

## Step 1 — Dependency preflight and well-known dir

Detect tools with `command -v` and remember which are present; do not abort on a
missing one — degrade instead:

```bash
HAVE_UV=false;  command -v uv  >/dev/null 2>&1 && HAVE_UV=true
HAVE_GIT=false; command -v git >/dev/null 2>&1 && HAVE_GIT=true
HAVE_NODE=false; command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 && HAVE_NODE=true
```

Degradation rules (all fail-open):
- `uv` absent -> skip the convert path (which runs under `uv`) and the Opik upload;
  warn that capture needs `uv` to convert the transcript.
- `git` absent or the cwd is not a git repo -> omit the git-derived env facts.
- `node`/`npm` absent, or the viewer fails to launch -> route review to the static
  HTML report instead of the viewer.

Create the well-known per-run working dir fresh (guarded cleanup, then make it):

```bash
[ -d "$HOME/.driver/capture/current" ] && rm -rf "$HOME/.driver/capture/current"
mkdir -p "$HOME/.driver/capture/current"
CUR="$HOME/.driver/capture/current"
```

All in-flow artifacts (redacted trajectory, `env.json`, `flags.json`,
`*.review.html`) live under `$CUR`.

## Step 2 — Resolve the active session transcript

The live session JSONL lives at `~/.claude/projects/<encoded-cwd>/<session_id>.jsonl`,
where `<encoded-cwd>` is the absolute cwd with every `/` replaced by `-`:

```bash
ENC="$(pwd | sed 's#/#-#g')"
DIR="$HOME/.claude/projects/$ENC"
TRANSCRIPT="$(ls -t "$DIR"/*.jsonl 2>/dev/null | head -1)"
```

The most-recently-modified `.jsonl` is the current live session. If `$DIR` does
not exist or has no `.jsonl`, **stop** and tell the user the session transcript
could not be resolved (they may be in a non-standard project dir).

The capture command's own turns are dropped via `--exclude-marker
'/drvr:capture-session'` in Step 4 — the transcript is truncated at the last user
turn that invoked this command, yielding a clean prefix. Re-capturing after more
work upserts the same trace, so capturing a prefix is safe.

## Step 3 — Resolve task / spec / intent

Establish linkage metadata, in this order of precedence:

1. **Arguments**: parse `$ARGUMENTS` for `--task-id`, `--spec-id`, `--intent`, `--project`.
2. **Feature context**: if a `FEATURE_LOG.md` is in cwd or up to 3 parents, derive
   the spec id from the feature directory name, read the active task from the most
   recent `implementation/log-*.md`, and read intent from `research/00-intent.md`.
3. **Fallback**: `--task-id` = a short slug of the work in progress, `--spec-id` =
   the feature/repo name, `--intent` = a one-line summary you write from the session.

Default `--project` = `drvr-sessions` (override with the `--project` flag).

## Step 4 — Gather env facts, convert, and redact (local only, nothing uploaded)

Gather environment facts failure-tolerantly. Each fact is best-effort: capture it,
and include the key only when it is non-empty. `commit_start` and `mcp_version` are
omitted (best-effort, not reliably available at capture time). Write the facts as
JSON to `$CUR/env.json` (only the present keys):

```bash
# Each fact is optional; collect only the ones that resolve.
if [ "$HAVE_GIT" = true ] && git rev-parse --git-dir >/dev/null 2>&1; then
    CODEBASE_URL="$(git remote get-url origin 2>/dev/null)"
    COMMIT_END="$(git rev-parse HEAD 2>/dev/null)"
    BRANCH="$(git branch --show-current 2>/dev/null)"
fi
CWD="$(pwd)"
# MCP endpoint: resolve from the active Driver MCP config if available.
```

Build `$CUR/env.json` containing only the non-empty keys among `codebase_url`,
`commit_end`, `branch`, `cwd`, `mcp_endpoint` (use `jq -n` to emit valid JSON;
skip env-fact gathering entirely if `git` was absent / not a repo).

Produce the redacted trajectory, **preferring the rolling store**. If rolling
capture has been writing a redacted store for this session and it is still fresh
(the live transcript has grown by fewer than the roll threshold since the last
roll), copy that store in as the flush artifact — it is the same canonical
redacted ATIF the re-derive path produces, already local. Otherwise re-derive
from the transcript with the convert→redact path (that arm runs under `uv` — skip
with a warning if `uv` is absent). The store copy is a local file read **before**
the Step 6 approval gate — not egress. Either way the outputs stay under `$CUR`,
so the working tree is untouched, and both arms end with
`$CUR/trajectory.redacted.json` + `$CUR/flags.json`:

```bash
# The rolling store is keyed by the live session id, which is the transcript's
# basename (<session_id>.jsonl). Prefer it when fresh; else re-derive.
SID="$(basename "$TRANSCRIPT" .jsonl)"
STORE="$(DRVR_ROOT="${CLAUDE_PLUGIN_ROOT}" python3 - "$HOME/.driver/capture" "$SID" <<'PY' 2>/dev/null
import os, sys
sys.path.insert(0, os.path.join(os.environ["DRVR_ROOT"], "scripts", "capture"))
from capture_store_core import store_path_for
try: print(store_path_for(sys.argv[1], sys.argv[2]))
except Exception: pass
PY
)"
STATE="$HOME/.driver/capture/sessions/$SID/roll-state.json"
CUR_COUNT="$(wc -l < "$TRANSCRIPT" 2>/dev/null | tr -d ' ')"
FRESH="$(DRVR_ROOT="${CLAUDE_PLUGIN_ROOT}" python3 - "$STATE" "${CUR_COUNT:-0}" <<'PY' 2>/dev/null
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["DRVR_ROOT"], "scripts", "capture"))
from capture_store_core import is_store_fresh, RollThreshold
prev = 0
try: prev = json.load(open(sys.argv[1])).get("record_count", 0)
except Exception: pass
print("1" if is_store_fresh(prev, int(sys.argv[2]), RollThreshold()) else "0")
PY
)"
if [ -n "$STORE" ] && [ -f "$STORE" ] && [ "$FRESH" = "1" ]; then
    cp "$STORE" "$CUR/trajectory.redacted.json"
    cp "$(dirname "$STORE")/flags.json" "$CUR/flags.json" 2>/dev/null || true
else
    uv run --with 'harbor~=0.16' python "${CLAUDE_PLUGIN_ROOT}/scripts/capture/cc_to_atif.py" \
        "$TRANSCRIPT" --task-id "$TASK" --spec-id "$SPEC" --intent "$INTENT" \
        --exclude-marker '/drvr:capture-session' --env-file "$CUR/env.json" \
        --session-dir "$DIR" \
        --out "$CUR/trajectory.json"
    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/redact.py" \
        "$CUR/trajectory.json" --out "$CUR/trajectory.redacted.json" \
        --flags-out "$CUR/flags.json"
fi
```

The converter prints `steps`, token totals, `cost`, `peak_step_context_tokens`,
and `tools_used`. The redactor prints the secrets it masked. Only the redacted
trajectory (`$CUR/trajectory.redacted.json`) is ever fed to review/viewer/upload.

## Step 5 — Render the in-chat review summary (egress-safe, no content)

Run `render_trace.py --summary`, which prints an egress-safe block built only from
metadata + redaction-flag counts — never step content — and **relay its stdout
verbatim**. Do NOT author your own summary from the trajectory:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/render_trace.py" \
    "$CUR/trajectory.redacted.json" --summary --no-open \
    --flags-file "$CUR/flags.json"
```

If there are redaction flags, **call them out prominently** — they are the main
reason to reject. **Do NOT print the trajectory content into the chat.** It is
large and may still contain sensitive material; for a full read, use the local
review surfaces below — they stay on disk and open in the browser.

## Step 6 — Approval gate (REQUIRED before any egress)

Use `AskUserQuestion` to get an explicit decision. **Do not save, render-for-export,
or upload until this is answered.** No network egress has run yet, and none runs
until the developer chooses an egress action here. The default approved action is a
**local save** — Opik upload is opt-in.

- **Header**: `Capture`
- **Question**: `Trajectory reviewed — what should I do with it?`
- **Options**:
  - `Open in trajectory viewer` — when `node`/`npm` are available, run
    `atif_to_viewer.py` (Step 7), let the developer replay it in the browser, then
    re-ask this question. Recommended review path when node/npm is present.
  - `Open static report` — run `render_trace.py` for a no-dependency HTML scan
    (Step 7), then re-ask this question. Use this when node/npm is unavailable.
  - `Save locally` — copy the redacted trajectory to `./captured-trajectory.json`,
    then remove the unredacted intermediate and any viewer-loaded copies (symmetry
    with `Reject` — the viewer holds the redacted trajectory and has no auth). No
    egress. **This is the default approved action.**

    ```bash
    cp "$CUR/trajectory.redacted.json" ./captured-trajectory.json
    rm -f "$CUR/trajectory.json"
    rm -f "$HOME/.driver/viewer/public/dataset.json" 2>/dev/null
    rm -rf "$HOME/.driver/viewer/public/runs"/* 2>/dev/null
    ```
  - `Upload to Opik` — register the **redacted** trajectory to a self-hosted Opik
    store (Step 8). Only offered/honored when the developer explicitly chooses it
    (or `--upload-opik` was passed).
  - `Reject` — nothing leaves the machine; clean up all local run data:

    ```bash
    [ -d "$HOME/.driver/capture/current" ] && rm -rf "$HOME/.driver/capture/current"
    rm -f "$HOME/.driver/viewer/public/dataset.json" 2>/dev/null
    rm -rf "$HOME/.driver/viewer/public/runs"/* 2>/dev/null
    ```

    Then confirm "Nothing was uploaded; local files removed." and stop.

## Step 7 — Local visual review (only when chosen at the gate)

Both options read the **redacted** trajectory and print only paths / flag counts
(never content). After the developer reviews, re-ask the Step 6 question.

**Trajectory viewer (interactive).** A scrubbable step-by-step replay. The viewer
is cloned on demand to `~/.driver/viewer` (first run git-clones and `npm install`s;
needs node/npm). Run it with `--no-serve` so it writes the data and prints a deep
link / manual launch command and control returns to the gate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_viewer.py" \
    "$CUR/trajectory.redacted.json" --task-id "$TASK" --spec-id "$SPEC" \
    --intent "$INTENT" --no-serve
```

If node/npm are absent or the viewer fails, fall back to the static report below.

**Static HTML report (stdlib only, no node).** A single self-contained page that
highlights redactions and runs a broader heuristic scan. Run with `--no-open` and
relay the `file://` path so control returns to the gate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/render_trace.py" \
    "$CUR/trajectory.redacted.json" --no-open
```

## Step 8 — Register to Opik (optional, only when "Upload to Opik" chosen)

This runs **only** when the developer explicitly selected `Upload to Opik` at the
gate (or passed `--upload-opik`). It is not the default path and needs `uv`:

```bash
uv run --with opik==2.0.64 python "${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_opik.py" \
    "$CUR/trajectory.redacted.json" --project "drvr-sessions"
```

The loader is idempotent: a deterministic trace id keyed on session + task means
re-capturing upserts the same trace instead of duplicating, tracked in a local
ledger at `~/.driver/capture/ledger.json`.

> **Security note.** Self-hosted Opik (the OSS deployment) has no authentication.
> Pointing the upload at a non-local `--base-url` exposes the redacted trajectory
> (including any captured subagents) to whoever can reach that host — that is the
> user's security responsibility. Keep the upload local unless you have explicitly
> secured the target. The upload step prints a warning when the resolved target is
> non-local; relay that warning and reconfirm with the developer before proceeding.

If the upload **fails**, the conversion already succeeded locally: the redacted
trajectory is intact at `$CUR/trajectory.redacted.json` and nothing was uploaded.
Tell the user it was saved locally and, if Opik was unreachable, to re-run when it
is reachable. (There is no retry queue — a failed upload is not data loss.)

On success, report the trace id and the Opik URL it prints, then remove the
unredacted intermediate (the redacted copy and flags remain):

```bash
rm -f "$CUR/trajectory.json"
```

---

## Notes / current limitations

- **Viewer is single-session.** The trajectory viewer holds one trajectory at a
  time — each capture overwrites it. The viewer is for inspection, not storage.
- **v1 is Claude Code + internal only.** The converter keeps a per-agent adapter
  boundary so other-agent adapters can plug in later.
