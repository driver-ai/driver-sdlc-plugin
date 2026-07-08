"""Plan an idempotent upload of redacted capture trajectories to S3.

`/drvr:capture-sync` uploads each redacted ATIF trajectory
(`~/.driver/capture/sessions/<id>/trajectory.redacted.json`, indexed in
`~/.driver/capture/index.json`) to the internal trajectory bucket, keyed by an
opaque, identity-scrubbed schema. This module mirrors the functional-core /
imperative-shell split of `atif_to_opik.py`: the PURE planners below decide the
S3 key, the `x-amz-meta-*` metadata, the PII-scan aggregation, and the sync
ledger / session selection; the imperative shell (`aws` shell-out, ledger I/O,
`render_trace.scan`, `main()`) lands in a later task and calls these.

Pure core discipline (matches `capture_store_core.py`): values in, values out --
no I/O, clock, or randomness. Timestamps and content hashes are passed in as
arguments so every planner is deterministic and unit-testable with plain dicts.
`is_safe_path_component` is imported at module top (not lazily) exactly as
`capture_store_core` does, and used for the session guard the same way
`store_path_for` rejects a traversal-bearing id.

Key schema (DEC-070), no raw identity PII (DEC-068):
    trajectories/v1/<sha256(org_id)[:63]>/<principal>/<codebase>/<branch>/
        <session_id>/trajectory.redacted.json
where <principal> is "auth0|<sub>" (user / PAT) or "machine|<id>" (machine),
<codebase> = basename(cwd), and <branch> is the entry's group_key with the
"branch:" prefix and the owner segment stripped.
"""
from __future__ import annotations

import copy
import hashlib
import os

from cc_to_atif_core import is_safe_path_component  # module-top; mirrors capture_store_core

# The S3-key schema version; also emitted as the `schema-version` metadata value
# so the object's metadata and its key prefix (`trajectories/v1/...`) agree. This
# is the SYNC schema version, NOT the ATIF trajectory schema (which lives inside
# the uploaded body as `schema_version`).
_SCHEMA_VERSION = "v1"

# Fallback segments so a missing/blank branch or codebase can never collapse a
# path component (an empty segment would fold two slashes in the S3 key).
_UNKNOWN_BRANCH = "unknown-branch"
_UNKNOWN_CODEBASE = "unknown-codebase"
_UNKNOWN_KIND = "unknown"

_BRANCH_PREFIX = "branch:"


def render_principal_segment(principal_id: str, principal_type: str) -> str:
    """Pure: the opaque `<principal>` key segment for the caller identity.

    A user (or PAT-derived) principal id is already the auth0 subject
    ("auth0|<sub>") and is used verbatim; a machine principal (a bare id) is
    namespaced with a "machine|" prefix so the two identity spaces never collide
    in the key. Any other principal type is a hard error -- an unrecognized
    identity must never be silently keyed.
    """
    if principal_type == "user":
        return principal_id                      # already "auth0|<sub>"
    if principal_type == "machine":
        return f"machine|{principal_id}"
    raise ValueError(f"unknown principal type: {principal_type!r}")


def branch_from_group_key(group_key: str | None) -> str | None:
    """Pure: the raw branch ref from an index entry's `group_key`, or None.

    The rolling index keys each session by `group_key` -- "branch:<x>" on git,
    or "ungrouped" off git (task:/spec: keys are possible but not branch-bearing
    either). Only a "branch:<x>" key yields a branch (the "branch:" prefix
    stripped, owner still attached -- `strip_branch_owner` removes that); every
    other key returns None so the caller skips the session (ungrouped/off-git
    sessions are not synced).
    """
    if not group_key or not group_key.startswith(_BRANCH_PREFIX):
        return None
    return group_key[len(_BRANCH_PREFIX):]


def strip_branch_owner(branch: str | None) -> str:
    """Pure: a single S3-key-safe branch segment (leading `owner/` dropped).

    A ref like "eric/agent-session-capture" keys as "agent-session-capture"; a
    deeper ref "a/b/c" flattens to one component "b__c" (S3 would allow the
    slashes but the schema keeps branch a single path segment). A bare branch
    with no owner ("main") is kept verbatim. Empty / None, or an owner with an
    empty branch remainder ("owner/"), returns the `_UNKNOWN_BRANCH` sentinel so
    the caller never emits an empty key segment.
    """
    if not branch:
        return _UNKNOWN_BRANCH
    if "/" not in branch:
        return branch                            # no owner prefix (e.g. "main")
    rest = [p for p in branch.split("/")[1:] if p]  # drop owner; drop empty parts
    if not rest:
        return _UNKNOWN_BRANCH                    # e.g. "owner/" -> nothing left
    return "__".join(rest)                        # "a/b/c" -> "b__c"


def sanitize_segment(value: str | None, *, fallback: str) -> str:
    """Pure: an ASCII, single-component key/metadata segment (or `fallback`).

    Both an S3 key path component and an `x-amz-meta-*` HTTP header value must be
    ASCII and free of separators/whitespace; anything non-ASCII, non-printable,
    whitespace, or a "/" is dropped. An input that reduces to empty (including
    None or whitespace-only) returns the provided sentinel so a segment is never
    blank. Git branch names and directory basenames never contain spaces, so
    stripping whitespace here is lossless in practice.
    """
    cleaned = "".join(
        c for c in (value or "")
        if c.isascii() and c.isprintable() and not c.isspace() and c != "/")
    return cleaned or fallback


def render_s3_key(*, org_id: str, principal_id: str, principal_type: str,
                  codebase: str, branch: str | None, session_id: str) -> str:
    """Pure: the DEC-070 S3 key for a session's redacted trajectory.

    Composes `trajectories/v1/<sha256(org_id)[:63]>/<principal>/<codebase>/
    <branch>/<session_id>/trajectory.redacted.json`. The org id is hashed (never
    stored raw); the principal is opaque; codebase and branch are ASCII-sanitized
    with sentinel fallbacks. Raises ValueError when `session_id` is not a safe
    single path component (mirrors `store_path_for`) so a transcript-supplied id
    can never traverse the key namespace.
    """
    if not is_safe_path_component(session_id):
        raise ValueError(f"unsafe session_id for S3 key: {session_id!r}")
    org_hash = hashlib.sha256(org_id.encode()).hexdigest()[:63]
    principal = render_principal_segment(principal_id, principal_type)
    cb = sanitize_segment(codebase, fallback=_UNKNOWN_CODEBASE)
    br = sanitize_segment(strip_branch_owner(branch), fallback=_UNKNOWN_BRANCH)
    return (f"trajectories/v1/{org_hash}/{principal}/{cb}/"
            f"{br}/{session_id}/trajectory.redacted.json")


def _capture_kind(group_key: str | None) -> str:
    """Pure: the capture kind = the `group_key` prefix before ':' (e.g.
    "branch:eric/foo" -> "branch"). Only branch-keyed sessions reach upload (the
    caller skips ungrouped/non-branch), so this is "branch" in practice; a key
    with no ':' falls back to the `_UNKNOWN_KIND` sentinel."""
    if isinstance(group_key, str) and ":" in group_key:
        return group_key.split(":", 1)[0]
    return _UNKNOWN_KIND


def build_metadata(*, session_id: str, branch: str | None, cwd: str | None,
                   capture_kind: str, cost_usd=None, steps=None,
                   schema_version: str = _SCHEMA_VERSION) -> dict:
    """Pure: the `x-amz-meta-*` dict for the upload -- identity-free by design.

    Keys are exactly {session-id, branch, codebase, schema-version, cost-usd,
    steps, capture-kind}: NO principal, name, email, or org id ever appears in
    object metadata (DEC-068). The branch is owner-stripped and sanitized (same
    as the key); codebase is `basename(cwd)` sanitized; both fall back to a
    sentinel when empty. cost/steps are `.get`-defaulted so a None/missing value
    becomes the string "0". Every value is an ASCII string (safe as an HTTP
    header). schema-version is the SYNC schema ("v1"), matching the key prefix.
    """
    return {
        "session-id": str(session_id),
        "branch": sanitize_segment(strip_branch_owner(branch),
                                   fallback=_UNKNOWN_BRANCH),
        "codebase": sanitize_segment(os.path.basename(cwd or ""),
                                     fallback=_UNKNOWN_CODEBASE),
        "schema-version": str(schema_version),
        "cost-usd": str(cost_usd if cost_usd is not None else 0),
        "steps": str(steps if steps is not None else 0),
        "capture-kind": sanitize_segment(str(capture_kind), fallback=_UNKNOWN_KIND),
    }


def plan_upload(traj: dict, index_entry: dict, identity: dict) -> dict:
    """Pure: the full upload plan for one session -> {key, metadata, content_type}.

    Composes the S3 key from `identity` ({principal_id, principal_type, org_id})
    plus the session's codebase (basename of the entry's `cwd`) and branch
    (`branch_from_group_key(entry["group_key"])`), and the identity-free metadata
    from the trajectory's final_metrics (cost/steps). `content_type` is always
    "application/json". No I/O -- the caller reads the trajectory and the entry.
    """
    session_id = traj.get("session_id") or index_entry.get("session_id")
    group_key = index_entry.get("group_key")
    branch = branch_from_group_key(group_key)
    cwd = index_entry.get("cwd") or ""
    fm = traj.get("final_metrics") or {}
    key = render_s3_key(
        org_id=identity["org_id"],
        principal_id=identity["principal_id"],
        principal_type=identity["principal_type"],
        codebase=os.path.basename(cwd),
        branch=branch,
        session_id=session_id,
    )
    metadata = build_metadata(
        session_id=session_id,
        branch=branch,
        cwd=cwd,
        capture_kind=_capture_kind(group_key),
        cost_usd=fm.get("total_cost_usd"),
        steps=fm.get("total_steps"),
    )
    return {"key": key, "metadata": metadata, "content_type": "application/json"}


def aggregate_scan(findings_by_session: dict) -> dict:
    """Pure: fold `render_trace.scan()` finding lists into COUNTS only.

    `findings_by_session` maps session_id -> list of findings (each shaped
    {type, where, snippet}). Returns {"by_type": {type: total},
    "per_session": {session_id: {type: count}}}. The scan snippets/locations are
    intentionally never carried into the output -- the approval gate presents
    by-type counts, so a snippet (which may echo already-redacted-but-flagged
    text) must not leak into the summary. A session with no findings still
    appears with an empty per-session map.
    """
    by_type: dict = {}
    per_session: dict = {}
    for session_id, findings in (findings_by_session or {}).items():
        counts: dict = {}
        for finding in findings or []:
            ftype = finding.get("type", _UNKNOWN_KIND)
            by_type[ftype] = by_type.get(ftype, 0) + 1
            counts[ftype] = counts.get(ftype, 0) + 1
        per_session[session_id] = counts
    return {"by_type": by_type, "per_session": per_session}


def is_synced(ledger: dict, session_id: str, artifact_sha: str) -> bool:
    """Pure: True when `session_id` is recorded in the ledger AND its stored
    `artifact_sha256` equals `artifact_sha`. A changed hash (a re-rolled, grown
    capture) reads as NOT synced so it re-uploads (latest-wins); an unseen
    session is never synced."""
    record = (ledger or {}).get(session_id)
    return bool(record) and record.get("artifact_sha256") == artifact_sha


def mark_synced(ledger: dict, session_id: str, *, s3_key: str, etag: str,
                synced_at: str, artifact_sha: str) -> dict:
    """Pure: a NEW ledger with `session_id`'s sync record set (input untouched).

    The record is {s3_key, etag, synced_at, artifact_sha256}; `synced_at` (the
    clock) is passed in by the shell so this stays deterministic. Deep-copies the
    input (mirrors `capture_store_core.update_index`) so a caller's ledger dict is
    never mutated mid-batch."""
    out = copy.deepcopy(ledger) if ledger else {}
    out[session_id] = {
        "s3_key": s3_key,
        "etag": etag,
        "synced_at": synced_at,
        "artifact_sha256": artifact_sha,
    }
    return out


def select_sessions(index: dict, ledger: dict, artifact_shas: dict,
                    session_id: str | None = None) -> list:
    """Pure: the index entries to sync -- flattened, un-synced, branch-only.

    Flattens the 2-level index ({group_key: {session_id: entry}}), skipping any
    group whose key is not "branch:<x>" (ungrouped / off-git / task-keyed
    sessions are never synced). Within the branch groups, an entry is selected
    unless it is already synced (`is_synced` against `artifact_shas[session_id]`,
    so a changed artifact re-selects). `session_id` narrows to that one session
    (still subject to the synced check, keeping the explicit path idempotent). An
    empty or missing index yields an empty selection. Each returned item is the
    original index entry dict (retains session_id / group_key / cwd).
    """
    selected: list = []
    for group_key, group in (index or {}).items():
        if not isinstance(group, dict):
            continue
        if branch_from_group_key(group_key) is None:   # skip ungrouped/non-branch
            continue
        for sid, entry in group.items():
            if session_id is not None and sid != session_id:
                continue
            if is_synced(ledger or {}, sid, (artifact_shas or {}).get(sid)):
                continue
            selected.append(entry)
    return selected
