---
description: Sync redacted capture trajectories to the internal S3 trajectory bucket after resolving the caller identity, previewing the object keys, scanning for residual PII, and getting explicit approval — nothing leaves the machine before the gate.
argument-hint: [--session-id ID]
allowed-tools: Bash, Read, Glob, AskUserQuestion, mcp__driver-mcp__get_caller_identity
---

# /drvr:capture-sync

Upload the redacted ATIF trajectories the rolling capture hooks have collected
(`~/.driver/capture/sessions/<id>/trajectory.redacted.json`, indexed in
`~/.driver/capture/index.json`) to the internal trajectory bucket under an
opaque, identity-scrubbed key. The sync is **idempotent** — a session already
recorded in the local `s3-sync-ledger.json` (with an unchanged artifact hash) is
skipped — so re-running is safe.

**Nothing leaves the machine before approval.** The approval gate (Step 4) is the
load-bearing governance control: the SSO preflight, identity lookup, `--dry-run`
key preview, and `--scan` PII counts run first, but **none of them egress a single
trajectory byte** — only the Step 5 real upload does, and it runs *only* after the
developer approves at the gate.

**Script** (referenced via `${CLAUDE_PLUGIN_ROOT}`; it is pure stdlib, so the
`python3` here is the plugin's script-runner convention, not a test runner):
- `${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_s3.py` — plans and performs the
  idempotent S3 sync. It exposes `--dry-run` (print the composed keys, upload
  nothing), `--scan` (emit by-type PII counts as JSON), and the real upload (no
  `--dry-run`/`--scan`). Flags: `--session-id`, `--bucket` (default
  `trajectory-uploads-1ddbee`), `--profile` (default `dev-admin`),
  `--principal-id`, `--principal-type`, `--org-id`, `--base-dir`. The identity
  args (`--principal-id/--principal-type/--org-id`) are **required in every mode**
  because keys and selection are computed from them.

Parse `$ARGUMENTS` for an optional `--session-id ID`. When present, the sync is
narrowed to that one session; otherwise every un-synced branch-keyed session is
considered.

---

## Step 0 — SSO preflight

The real upload authenticates with an AWS SSO profile. Confirm the session is
usable *before* doing any work, and give the developer a **distinct** message for
each failure so they know exactly what to fix. The script itself also preflights
before it egresses, but doing it here sets expectations and fails fast:

```bash
PROFILE="dev-admin"   # the only SSO identity with kms:GenerateDataKey on the CMK (DEC-067)

if ! command -v aws >/dev/null 2>&1; then
    echo "aws CLI not found on PATH — install it (e.g. 'brew install awscli') before syncing."
    # stop here: nothing to preflight against.
elif ! aws sts get-caller-identity --profile "$PROFILE" >/dev/null 2>&1; then
    # Re-run capturing stderr so we can distinguish the failure modes.
    ERR="$(aws sts get-caller-identity --profile "$PROFILE" 2>&1 >/dev/null)"
    case "$ERR" in
        *"could not be found"*|*"not found"*|*"does not exist"*)
            echo "AWS profile '$PROFILE' not found — configure it ('aws configure sso') or pass --profile." ;;
        *)
            echo "SSO session expired or invalid — run 'aws sso login --profile $PROFILE', then retry." ;;
    esac
    # stop here: the real upload would fail; fix the profile/session first.
else
    echo "SSO session OK for profile '$PROFILE'."
fi
```

If the preflight does not succeed, **stop** and relay the guidance above — do not
continue to the upload. (`--dry-run` / `--scan` themselves need no AWS access, so
you may still preview locally, but the real upload cannot proceed until SSO is
healthy.)

## Step 1 — Resolve the caller identity

Call `mcp__driver-mcp__get_caller_identity` to learn who is syncing. The tool
returns a **`DriverMcpToolResponse` envelope** — you must unwrap it:

- If the envelope's **`error_message`** is set, identity could not be resolved
  (the no-token case, DEC-073). **ABORT** with a clear message, e.g.:
  *"Cannot resolve caller identity (no Driver token configured). Configure a
  Driver token and re-run /drvr:capture-sync."* Do not fall back to a guessed
  identity — the S3 key namespace is identity-scoped and must be correct.
- Otherwise read the **`payload`** and pull:
  - `payload["id"]`   → the principal id (for `--principal-id`)
  - `payload["type"]` → the principal type, `user` or `machine` (for `--principal-type`)
  - `payload["organization_id"]` → the org id (for `--org-id`)

Note the org field is **`organization_id`**, NOT `org_id`. Bind these to shell
variables for the invocations below:

```bash
PRINCIPAL_ID="<payload.id>"
PRINCIPAL_TYPE="<payload.type>"      # "user" or "machine"
ORG_ID="<payload.organization_id>"
SESSION_ID="<--session-id arg, or empty>"
```

## Step 2 — Preview the keys (`--dry-run`, no egress)

Run the sync in `--dry-run` mode with the identity args to see the **real S3 keys**
that would be written. This reads no trajectory bytes for the body and uploads
nothing:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_s3.py" --dry-run \
    --principal-id "$PRINCIPAL_ID" --principal-type "$PRINCIPAL_TYPE" \
    --org-id "$ORG_ID" ${SESSION_ID:+--session-id "$SESSION_ID"}
```

If the command prints `nothing to sync`, there is nothing to do (every candidate
session is already synced, or the index is empty / off-git-only). **STOP here** —
do not present a gate, do not upload. Otherwise relay the previewed keys; these
are exactly the objects the real upload will write.

## Step 3 — Scan for residual PII (`--scan`, no egress)

Run the same invocation with `--scan` (same identity args) to get the by-type PII
counts across the selected sessions. This reads only the **redacted** artifacts
and emits **counts by type as JSON** — never raw snippets — and uploads nothing:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_s3.py" --scan \
    --principal-id "$PRINCIPAL_ID" --principal-type "$PRINCIPAL_TYPE" \
    --org-id "$ORG_ID" ${SESSION_ID:+--session-id "$SESSION_ID"}
```

Keep the parsed `by_type` counts — they are the input to the approval gate.

## Step 4 — Approval gate (REQUIRED before any egress)

Use `AskUserQuestion` to get an explicit decision. **Do not upload until this is
answered.** No trajectory bytes have left the machine yet, and none leave until
the developer approves here. Present an **honest** picture of the `--scan`
counts — do not oversell the safety of the redaction:

- **Show the by-type counts** from Step 3 for the sessions about to sync.
- **Mark `High-entropy` and `Secret-ish` as LOW-signal.** On already-redacted
  data these are overwhelmingly noise (spike: ~97% of findings), not real leaks.
- **Highlight the HIGH-signal types** — `Email`, `JWT`, and key/token findings.
  These are the ones worth inspecting before approving.
- **State explicitly what the scan does NOT catch:** developer **names and
  usernames**, and `/Users/<name>/…` (or other home-directory) **file paths**,
  are **not detected** by the scan and **may remain in the trajectory body**.
  This residual is accepted for internal use (DEC-071/075) but the developer must
  know it before approving. There is no name/path masking this cycle.

Gate shape:

- **Header**: `Sync`
- **Question**: `Scan reviewed — upload these redacted trajectories to S3?`
- **Options**:
  - `Upload to S3` — proceed to Step 5 and perform the real upload.
  - `Cancel` — do nothing; nothing egresses. Confirm "Nothing was uploaded." and stop.

Only proceed to Step 5 on the explicit `Upload to S3` choice.

## Step 5 — Real upload (egress; only after approval)

Only after the developer chose `Upload to S3` at the Step 4 gate, run the script
**without** `--dry-run` / `--scan` to perform the actual upload. This is the only
step that egresses trajectory bytes:

```bash
# REAL UPLOAD (egress) — runs ONLY after the Step 4 approval gate. This invocation
# is deliberately distinct from the Step 2/3 --dry-run/--scan previews: it carries
# no preview flag, so it is the point at which redacted bytes leave the machine.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/capture/atif_to_s3.py" \
    --principal-id "$PRINCIPAL_ID" --principal-type "$PRINCIPAL_TYPE" \
    --org-id "$ORG_ID" ${SESSION_ID:+--session-id "$SESSION_ID"} \
    --bucket trajectory-uploads-1ddbee --profile "$PROFILE"
```

The script preflights SSO again, uploads each selected session's redacted
artifact (upload **before** the per-session ledger write, so a crash mid-batch
just re-uploads that one session next run), and continues on a per-session
failure rather than aborting the whole batch. It prints an `OK  <key>  (etag …)`
line per successful upload and an `error: …` line per failure.

## Step 6 — Report

Summarize the outcome from the Step 5 output:

- **Uploaded**: the keys with an `OK …` line (relay the key + etag).
- **Skipped**: sessions that were already synced (idempotent) or whose redacted
  artifact was missing/unreadable (the script warns and skips these).
- **Failed**: any `error: …` lines (e.g. a per-session upload failure, a KMS 403,
  or an SSO issue) — relay the script's message verbatim so the developer can act.

A non-zero exit from the script means at least one session failed; the successes
are already recorded in the ledger, so a re-run retries only the failures.

---

## Notes / current limitations

- **Only `trajectory.redacted.json` is ever read or uploaded** — never the raw
  transcript, and never the `flags.json` / `meta.json` siblings (this cycle).
- **No name/path masking this cycle.** The scan flags secrets/entropy but does
  **not** detect developer names, usernames, or `/Users/<name>/…` paths; the gate
  says so. Accepted for internal use (DEC-071/075); must be revisited before any
  customer-facing generalization.
- **`dev-admin` is required** because it is the only SSO identity with
  `kms:GenerateDataKey` on the bucket's CMK (DEC-067). The bucket applies KMS via
  default encryption, so the upload carries no SSE flags. A later presigned-URL
  path will remove client-side credentials.
- **Off-git / ungrouped sessions are skipped** — only branch-keyed sessions sync.
