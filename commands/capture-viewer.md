---
description: Launch the local capture viewer — resolve the caller identity, start the localhost-only server that presents the capture store to the trajectory-viewer UI, and report the URL. Browsing and scans are read-only; upload happens only through the viewer's confirm gate.
argument-hint: [--port PORT]
allowed-tools: Bash, Read, mcp__driver-mcp__get_caller_identity
---

# /drvr:capture-viewer

Serve the rolling capture store (`~/.driver/capture` — `index.json`, the
`s3-sync-ledger.json`, and `sessions/<id>/trajectory.redacted.json`) to the
local trajectory-viewer UI: browse every captured session with its sync
status, open per-session transcripts, review counts-only PII scans, and sync
selected sessions to the internal trajectory bucket — all from the browser.

**Launching the server egresses nothing.** The dataset, run, and scan routes
are read-only; the one egress route is the gated `POST /api/sync`, and
the confirm click in the viewer UI is the gate: the server refuses any sync
without `confirm: true` in the request body, refuses unknown or
non-uploadable session ids (already-synced and ungrouped sessions included),
and binds 127.0.0.1 only — the viewer is never reachable off this machine.

**Script** (referenced via `${CLAUDE_PLUGIN_ROOT}`; it is pure stdlib, so the
`python3` here is the plugin's script-runner convention, not a test runner):
- `${CLAUDE_PLUGIN_ROOT}/scripts/capture/capture_viewer_server.py` — the
  localhost HTTP server. Flags: `--port` (default 5273), `--base-dir`,
  `--viewer-dir`, `--repo`, `--pin`, `--bucket`, `--profile`,
  `--principal-id`, `--principal-type`, `--org-id` (identity args — required),
  `--no-build` (pure serve mode), `--no-install`. On a cold start it clones
  the pinned viewer fork, runs `npm install`, and builds it; warm launches
  skip all of that.

Parse `$ARGUMENTS` for an optional `--port PORT`. When present, pass it
through to the server; otherwise the default port 5273 is used.

---

## Step 1 — Resolve the caller identity

Call `mcp__driver-mcp__get_caller_identity` to learn who is launching the
viewer (the server holds no long-lived credentials — identity is injected at
launch and scopes the S3 keys any later sync writes). The tool returns a
**`DriverMcpToolResponse` envelope** — you must unwrap it:

- If the envelope's **`error_message`** is set, identity could not be
  resolved (the no-token case). **ABORT** with the MCP error message, e.g.:
  *"Cannot resolve caller identity (no Driver token configured). Configure a
  Driver token and re-run /drvr:capture-viewer."* Do not fall back to a
  guessed identity — the S3 key namespace is identity-scoped and must be
  correct.
- Otherwise read the **`payload`** and pull:
  - `payload["id"]`   → the principal id (for `--principal-id`)
  - `payload["type"]` → the principal type, `user` or `machine` (for `--principal-type`)
  - `payload["organization_id"]` → the org id (for `--org-id`)

Note the org field is **`organization_id`**, NOT `org_id`. Bind these to
shell variables for the launch below:

```bash
PRINCIPAL_ID="<payload.id>"
PRINCIPAL_TYPE="<payload.type>"      # "user" or "machine"
ORG_ID="<payload.organization_id>"
PORT="<--port arg, or empty>"
```

## Step 2 — Launch the server (background) and report the URL

Run the server as a **background Bash task** — it serves until killed, so it
must not block the conversation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/capture_viewer_server.py" \
    --principal-id "$PRINCIPAL_ID" --principal-type "$PRINCIPAL_TYPE" \
    --org-id "$ORG_ID" ${PORT:+--port "$PORT"}
```

Watch the task's output for the single stdout line
`http://127.0.0.1:<port>/` — **the printed URL is the readiness signal**.
Relay that URL to the developer so they can open it in their browser.

- **First launch can take a few minutes**: the server clones the pinned
  viewer fork into `~/.driver/viewer`, runs `npm install`, and builds it
  before binding the port. Later launches reuse the build and print the URL
  almost immediately.
- **The server is request-log-quiet by design.** After the URL line, no
  per-request output appears — do not wait for more; errors surface as JSON
  responses in the browser, not on the console.
- **Port in use?** If the task exits immediately with
  `error: port <port> in use — viewer already running?`, a viewer is almost
  certainly already serving on that port: **reuse the printed URL** from the
  earlier launch instead of starting a second server (or pass a different
  `--port` if something else owns the port).
- Any other `error: …` exit (a failed clone, `npm` missing, a failed build)
  is actionable — relay the message verbatim so the developer can fix it and
  re-run /drvr:capture-viewer.

## Step 3 — Hand off to the browser

Everything else happens in the viewer UI — this command does not gate or
perform uploads itself:

- The session list shows every captured session with its sync status
  (`synced` / `pending` / `missing`) and which sessions are uploadable
  (branch-keyed, readable, not already synced — capture-viewer DEC-008).
- Selecting sessions to sync surfaces the by-type PII scan counts for the
  selection; the confirm click in the viewer UI is the gate — no trajectory
  bytes leave the machine until the developer clicks it, and the server
  refuses any sync without `confirm: true`.
- The sync reuses the same S3 machinery as /drvr:capture-sync: idempotent
  sha256 ledger, per-session continue-on-error, and the `dev-admin` SSO
  profile (capture-s3-sync DEC-067). If the SSO session is expired the sync returns an
  actionable error in the UI — run `aws sso login --profile dev-admin` and
  retry from the browser.

## Step 4 — Stopping the server

The server runs until killed. When the developer is done:

- **Kill the background Bash task** that launched it (the task's PID is the
  server's), or
- find and kill by port: `lsof -ti tcp:<port> | xargs kill` (default port
  5273).

The server shuts down cleanly on SIGTERM/Ctrl-C; nothing needs flushing —
the store on disk is never mutated by browsing (only a confirmed sync writes
the ledger).

---

## Notes / current limitations

- **Localhost-only, no auth** (internal-only cycle): the server binds
  127.0.0.1 and rejects any request whose `Host` header hostname is not
  `127.0.0.1`/`localhost` (DNS-rebind defense).
- **Only `trajectory.redacted.json` is ever read, served, or uploaded** —
  never the raw transcript.
- **Scan counts are honest but incomplete**: the scan emits by-type counts
  only (never snippets) and does **not** detect developer names, usernames,
  or `/Users/<name>/…` home-directory paths — the same posture as
  /drvr:capture-sync. The developer must know this before confirming a sync.
- **Idempotent sync**: already-synced sessions are not uploadable in the UI;
  a session whose artifact changed after a sync flips back to `pending` and
  can be synced again.
