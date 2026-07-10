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

import argparse
import contextlib
import copy
import datetime
import hashlib
import json
import os
import subprocess
import sys

import render_trace  # module-top; the shell's scan_sessions calls render_trace.scan
from capture_store_core import (  # sibling redacted-artifact + annotations paths
    annotations_path_for,
    store_path_for,
)
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
                    session_id: str | None = None, *,
                    session_ids: set[str] | None = None) -> list:
    """Pure: the index entries to sync -- flattened, un-synced, branch-only.

    Flattens the 2-level index ({group_key: {session_id: entry}}), skipping any
    group whose key is not "branch:<x>" (ungrouped / off-git / task-keyed
    sessions are never synced). Within the branch groups, an entry is selected
    unless it is already synced (`is_synced` against `artifact_shas[session_id]`,
    so a changed artifact re-selects). `session_id` narrows to that one session
    (still subject to the synced check, keeping the explicit path idempotent);
    `session_ids` (keyword-only) narrows to that set the same way -- ids absent
    from the index are silently unmatched (validating the request is the
    caller's job). Passing both `session_id` and `session_ids` raises
    ValueError. An empty or missing index yields an empty selection. Each
    returned item is the original index entry dict (retains session_id /
    group_key / cwd).
    """
    if session_id is not None and session_ids is not None:
        raise ValueError("pass session_id or session_ids, not both")
    selected: list = []
    for group_key, group in (index or {}).items():
        if not isinstance(group, dict):
            continue
        if branch_from_group_key(group_key) is None:   # skip ungrouped/non-branch
            continue
        for sid, entry in group.items():
            if session_id is not None and sid != session_id:
                continue
            if session_ids is not None and sid not in session_ids:
                continue
            if is_synced(ledger or {}, sid, (artifact_shas or {}).get(sid)):
                continue
            selected.append(entry)
    return selected


def render_annotations_key(trajectory_key: str) -> str:
    """Pure: the annotations sibling key, derived FROM the trajectory's ledger-stored
    key (capture-viewer DEC-030 — never recomputed from launch identity; identity
    drift was proven to land a recomputed 'sibling' under a different org-hash
    prefix than the object actually occupies).
    Raises ValueError unless the leaf is exactly 'trajectory.redacted.json'."""
    prefix, _, leaf = trajectory_key.rpartition("/")
    if leaf != "trajectory.redacted.json" or not prefix:
        raise ValueError(f"not a trajectory key: {trajectory_key!r}")
    return f"{prefix}/annotations.json"


def annotations_ledger_row(s3_key: str, sha: str, etag: str, now: str) -> dict:
    """Pure: mutable last-write-wins row. Unlike the trajectory row (one-shot,
    capture-viewer DEC-008), a changed sha UPDATES the row — annotations re-upload
    on edit."""
    return {"s3_key": s3_key, "annotations_sha": sha, "etag": etag, "updated_at": now}


def plan_annotations_upload(*, session_id: str, trajectory_ledger: dict,
                            annotations_ledger: dict, annotations_sha: str,
                            entry: dict | None) -> dict:
    """Pure: the annotations-sync decision for one session.

    Gate (capture-viewer DEC-034): the TRAJECTORY ledger row must exist — a row
    implies the object is in S3, so no orphan annotation object is possible. (NOT
    is_synced: a drifted artifact sha — a re-rolled session — still has its object
    in S3; a DEC-024 missing-artifact session could never re-match.) The sibling
    key is derived FROM that row's `s3_key` (DEC-030), never from launch identity.
    Then last-write-wins: an unchanged sha is a no-op; a changed/new sha uploads
    (a changed sha UPDATES the row — not a DEC-008 violation). Metadata is
    identity-free (capture-viewer DEC-068), sanitized like the trajectory's.
    Returns {"action": "upload"|"noop"|"refuse", "reason": str|None,
             "s3_key": str|None, "metadata": dict|None}."""
    row = trajectory_ledger.get(session_id)
    if not isinstance(row, dict) or not row.get("s3_key"):
        return {"action": "refuse", "reason": "trajectory not synced — sync it first "
                "(no orphan annotation objects)", "s3_key": None, "metadata": None}
    key = render_annotations_key(row["s3_key"])
    prev = annotations_ledger.get(session_id)
    if isinstance(prev, dict) and prev.get("annotations_sha") == annotations_sha:
        return {"action": "noop", "reason": None, "s3_key": key, "metadata": None}
    entry = entry or {}
    metadata = {  # identity-free (capture-viewer DEC-068); sanitized like the trajectory's
        "session-id": session_id,
        "codebase": sanitize_segment(entry.get("codebase"), fallback=_UNKNOWN_CODEBASE),
        "branch": sanitize_segment(strip_branch_owner(entry.get("branch")),
                                   fallback=_UNKNOWN_BRANCH),
        "content-kind": "annotations",
        "schema-version": "1",
    }
    return {"action": "upload", "reason": None, "s3_key": key, "metadata": metadata}


def scan_note_pii(doc: dict) -> dict:
    """Pure: by-type PII counts over the human-authored text in an annotations doc
    (stepLabels[].note + runLabels[].note + tags — capture-viewer DEC-031).
    render_trace.scan walks a TRAJECTORY dict (steps[].message), so each text is
    wrapped as its own synthetic step — one step per text, so scan's value@location
    dedup cannot under-count a value repeated across notes. Counts only: the
    findings' snippet/where fields never leave this function (DEC-071 lineage)."""
    texts = [lbl.get("note") for lbl in doc.get("stepLabels", [])]
    texts += [lbl.get("note") for lbl in doc.get("runLabels", [])]
    texts += list(doc.get("tags", []))
    steps = [{"step_id": i, "message": t} for i, t in enumerate(texts) if t]
    if not steps:
        return {}
    counts: dict[str, int] = {}
    for finding in render_trace.scan({"steps": steps}):
        counts[finding["type"]] = counts.get(finding["type"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Imperative shell (I/O, subprocess, clock) — mirrors atif_to_opik's split: the
# pure planners above decide WHAT to do; everything below reads/writes files,
# shells out to `aws`, and reads the clock. Kept stdlib-only (no boto3): `aws`
# is invoked via subprocess with an explicit argv list.
# ---------------------------------------------------------------------------

DEFAULT_BUCKET = "trajectory-uploads-1ddbee"
# `dev-admin` is the only SSO identity with kms:GenerateDataKey on the bucket's
# CMK (DEC-067); the bucket applies KMS via default encryption, so put-object
# carries NO SSE flags. A later presigned-URL path removes client-side creds.
DEFAULT_PROFILE = "dev-admin"
_DEFAULT_BASE_DIR = "~/.driver/capture"
_INDEX_NAME = "index.json"
LEDGER_NAME = "s3-sync-ledger.json"      # separate from the hook-owned index.json
# The annotations sync ledger is its OWN file (never a section of s3-sync-ledger.json:
# a same-file section is lost-update-prone under the whole-file save_ledger write and
# creates an is_synced phantom) — capture-viewer DEC-030. Readers/writers reuse
# load_ledger/save_ledger with this path; the row is mutable/last-write-wins (a changed
# sha re-uploads), unlike the trajectory's one-shot row (DEC-008).
ANNOTATIONS_LEDGER_NAME = "annotations-sync-ledger.json"


def _load_json_map(path: str, *, label: str) -> dict:
    """Load a JSON object from `path`, treating missing OR corrupt as empty.

    A missing file is a normal first-run state (silent empty); a corrupt or
    non-object file warns to stderr and degrades to {} rather than crashing the
    sync (mirrors atif_to_opik.trace_id_for's corrupt-ledger recovery)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"warning: {label} unreadable ({e.__class__.__name__}); "
              f"treating as empty: {path}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"warning: {label} is not a JSON object; treating as empty: {path}",
              file=sys.stderr)
        return {}
    return data


def load_index(path: str) -> dict:
    """Shell: read the hook-owned capture index; corrupt/missing -> warn + {}."""
    return _load_json_map(path, label="capture index")


def load_ledger(path: str) -> dict:
    """Shell: read the sync ledger; corrupt/missing -> warn + {}."""
    return _load_json_map(path, label="sync ledger")


def save_ledger(path: str, ledger: dict) -> None:
    """Shell: atomically persist the ledger (temp file in its OWN dir + os.replace).

    Reimplements the atomic pattern inlined in atif_to_opik.trace_id_for (there is
    no shared helper): the temp file lives beside the target so os.replace is a
    same-filesystem atomic swap, and a crash mid-write can never leave a torn
    ledger. The index.json is never touched — idempotency state stays here."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(ledger, f, indent=2)
    os.replace(tmp, path)


def artifact_sha256(path: str) -> str | None:
    """Shell: sha256 hex of a redacted artifact, or None if it can't be read.

    Streams the file so a large artifact never loads whole into memory. A missing
    or unreadable file warns to stderr and returns None so the caller can SKIP that
    session and keep the batch going (never a raised traceback)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        print(f"warning: cannot read artifact ({e.__class__.__name__}); "
              f"skipping: {path}", file=sys.stderr)
        return None


def hash_candidates(index: dict, base_dir: str, *,
                    session_id: str | None = None,
                    session_ids: set[str] | None = None,
                    all_groups: bool = False) -> tuple[dict, dict]:
    """Shell (extracted from main): resolve store_path_for + sha256 artifacts.

    Default (the CLI path): branch-keyed groups only; unreadable/unsafe entries
    warn to stderr and are OMITTED from shas, so they never enter a selection or
    an upload. all_groups=True (the dataset path): EVERY session across EVERY
    group appears in shas with sha-or-None (unreadable/missing -> None, never
    omitted) -- the full artifact_shas map build_sessions_dataset needs.
    `session_id` narrows TRUTHILY (an empty string narrows nothing, exactly as
    main() always treated --session-id ""); `session_ids` narrows to that set
    before any hashing. Returns (shas, paths); paths holds readable artifacts
    only."""
    shas: dict = {}
    paths: dict = {}
    for group_key, group in (index or {}).items():
        if not isinstance(group, dict):
            continue
        if not all_groups and branch_from_group_key(group_key) is None:
            continue                                   # skip ungrouped/non-branch
        for sid, entry in group.items():
            if session_id and sid != session_id:
                continue
            if session_ids is not None and sid not in session_ids:
                continue
            try:
                path = store_path_for(base_dir, sid)   # sibling artifact convention
            except ValueError as e:
                print(f"warning: skipping {sid!r} ({e})", file=sys.stderr)
                if all_groups:
                    shas[sid] = None
                continue
            sha = artifact_sha256(path)
            if sha is None:                            # already warned
                if all_groups:
                    shas[sid] = None
                continue
            shas[sid] = sha
            paths[sid] = path
    return shas, paths


def scan_sessions(selected: list) -> dict:
    """Shell: read each selected session's redacted artifact and scan it.

    Returns {session_id: findings_list} (findings shaped {type, where, snippet})
    for aggregate_scan, which folds them to counts-only. Reads each entry's
    `store_path` (the index-recorded redacted-artifact path, equal to the base-dir
    convention). An unreadable artifact warns and contributes an empty finding
    list so the session still appears in the aggregate. Only redacted bytes are
    read — never a raw transcript."""
    out: dict = {}
    for entry in selected or []:
        sid = entry.get("session_id")
        path = entry.get("store_path")
        try:
            with open(path) as f:
                traj = json.load(f)
        except (OSError, ValueError, TypeError) as e:
            print(f"warning: cannot scan {sid} ({e.__class__.__name__}); "
                  f"treating as no findings", file=sys.stderr)
            out[sid] = []
            continue
        out[sid] = render_trace.scan(traj)
    return out


def preflight_sso(profile: str) -> None:
    """Shell: verify the SSO session before egress; raise a clear RuntimeError.

    Runs `aws sts get-caller-identity --profile <p>` and distinguishes three
    failure modes with distinct, actionable messages and NO traceback:
      - expired/invalid SSO token -> tell the user to `aws sso login --profile <p>`;
      - the profile isn't configured -> a distinct "profile not found" message;
      - `aws` isn't installed (FileNotFoundError) -> "install/enable aws".
    Returns None on success."""
    try:
        proc = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile,
             "--output", "json"],
            capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "aws CLI not found on PATH — install/enable it "
            "(e.g. `brew install awscli`) before syncing") from e
    if proc.returncode == 0:
        return
    err = proc.stderr.strip()
    low = err.lower()
    if "token" in low or "expired" in low or "sso" in low:
        raise RuntimeError(
            f"SSO session expired or invalid — run "
            f"`aws sso login --profile {profile}`, then retry")
    if "profile" in low and ("could not be found" in low or "not found" in low
                             or "does not exist" in low):
        raise RuntimeError(
            f"AWS profile {profile!r} not found — configure it "
            f"(`aws configure sso`) or pass --profile")
    raise RuntimeError(
        f"aws sts get-caller-identity failed for profile {profile!r}: {err}")


def upload_one(key: str, body_path: str, metadata: dict, *,
               bucket: str, profile: str) -> str:
    """Shell: PUT one redacted artifact to S3 via `aws s3api put-object`.

    Metadata is passed as a single JSON string (`--metadata '{...}'`), NOT the
    `k=v,k=v` shorthand, so values containing ',' or '=' survive intact. No SSE
    flags — the bucket's default encryption applies aws:kms server-side
    (DEC-066/067). Returns the object's ETag (unquoting the `"..."` form S3
    returns). A KMS 403 maps to a clear message; a missing `aws` maps to an
    install hint. Both raise RuntimeError (no traceback)."""
    try:
        proc = subprocess.run(
            ["aws", "s3api", "put-object", "--bucket", bucket, "--key", key,
             "--body", body_path, "--content-type", "application/json",
             "--metadata", json.dumps(metadata),   # JSON form: safe for ',' '=' in values
             "--profile", profile, "--output", "json"],
            capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError("aws CLI not found on PATH — install/enable it") from e
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "AccessDenied" in err and "kms" in err.lower():
            raise RuntimeError(
                f"KMS access denied for {key}: the profile lacks CMK "
                f"GenerateDataKey (DEC-067)")
        raise RuntimeError(f"s3 put-object failed for {key}: {err}")
    return json.loads(proc.stdout).get("ETag", "").strip('"')


def _now_iso() -> str:
    """Shell: current UTC timestamp for the ledger (the clock stays out of core)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def sync_sessions(selected: list, *, paths: dict, shas: dict, identity: dict,
                  bucket: str, profile: str, ledger: dict,
                  ledger_path: str) -> tuple[dict, list[dict]]:
    """Shell (extracted from main's upload loop): per-session plan_upload ->
    upload_one -> mark_synced -> save_ledger, continue-on-error. The upload runs
    BEFORE the ledger write, and the ledger is saved PER session, so a crash
    mid-batch just re-hashes/re-uploads this one session next run. SILENT -- no
    printing; the caller renders results (main() to the CLI lines, a server to
    its response body, which must never receive CLI output on its stdio).

    Returns (final_ledger, results) where each result is {"session_id", "ok",
    "s3_key"?, "etag"?, "error"?}. save_ledger raising AFTER a successful upload
    yields ok: false with a ledger-mentioning error and the record is NOT kept
    in the returned ledger (the session re-uploads next run -- an idempotent
    re-PUT of identical bytes -- rather than silently reading as synced); the
    batch continues either way. Caller runs preflight_sso first."""
    results: list = []
    for entry in selected:
        sid = entry["session_id"]
        try:
            with open(paths[sid]) as f:
                traj = json.load(f)                    # only redacted bytes, ever
            plan = plan_upload(traj, entry, identity)
            # Single-PUT put-object caps at 5 GB; an artifact above that would
            # need a multipart upload (not implemented — captures are far smaller).
            etag = upload_one(plan["key"], paths[sid], plan["metadata"],
                              bucket=bucket, profile=profile)
        except Exception as e:   # continue-on-error: one bad session never aborts
            results.append({"session_id": sid, "ok": False, "error": str(e)})
            continue
        try:
            new_ledger = mark_synced(ledger, sid, s3_key=plan["key"], etag=etag,
                                     synced_at=_now_iso(), artifact_sha=shas[sid])
            save_ledger(ledger_path, new_ledger)
        except Exception as e:
            results.append({"session_id": sid, "ok": False,
                            "error": f"uploaded but ledger write failed: {e}"})
            continue
        ledger = new_ledger
        results.append({"session_id": sid, "ok": True,
                        "s3_key": plan["key"], "etag": etag})
    return ledger, results


def _index_entry_for(index: dict, session_id: str) -> dict:
    """Shell helper: the flattened index entry for `session_id` (or {}). Used to
    read the session's codebase/branch for identity-free annotations metadata."""
    for group in (index or {}).values():
        if isinstance(group, dict):
            entry = group.get(session_id)
            if isinstance(entry, dict):
                return entry
    return {}


def sync_annotations(*, base_dir: str, session_id: str, bucket: str,
                     profile: str) -> dict:
    """Shell: gate -> snapshot -> upload -> ledger write, for ONE session -- the
    deliberate sibling of `sync_sessions` (capture-viewer DEC-030/DEC-032). Reads
    the annotations sidecar bytes ONCE, sha256s those exact bytes, uploads from a
    temp snapshot of them (sidecar TOCTOU self-heals on the next sync -- LWW),
    then writes the annotations ledger row (upload-before-ledger-write, so a crash
    mid-upload just re-uploads next run). SILENT -- no printing; the caller (the
    viewer's annotations-sync route) renders the result to its response body.

    The synced-trajectory gate is `plan_annotations_upload` (capture-viewer
    DEC-034: the trajectory ledger row must exist -> no orphan annotation
    objects); the sibling key is derived FROM that row's `s3_key` (DEC-030). The
    annotations ledger is its OWN file (`ANNOTATIONS_LEDGER_NAME`), read/written
    with the shared corrupt-tolerant load_ledger/atomic save_ledger; its row is
    mutable last-write-wins (a changed sha re-uploads -- DEC-008's one-shot rule
    is the trajectory's alone). Caller runs preflight_sso first.

    Returns the flat wire object {ok, s3_key?, etag?, noop?, error?}: an unchanged
    sha -> {ok:true, noop:true}; an upload/KMS failure -> {ok:false, error}
    (consistent with sync_sessions' continue-on-error posture, but flat because
    this route is single-session, not a batch).
    """
    traj_ledger = load_ledger(os.path.join(base_dir, LEDGER_NAME))
    ann_ledger_path = os.path.join(base_dir, ANNOTATIONS_LEDGER_NAME)
    ann_ledger = load_ledger(ann_ledger_path)           # corrupt -> {} (re-upload)
    index = load_index(os.path.join(base_dir, _INDEX_NAME))
    idx_entry = _index_entry_for(index, session_id)
    meta_entry = {
        "codebase": os.path.basename(idx_entry.get("cwd") or "") or None,
        "branch": branch_from_group_key(idx_entry.get("group_key")),
    }

    sidecar = annotations_path_for(base_dir, session_id)
    # Snapshot the bytes ONCE and sha THOSE bytes -- sha-what-you-upload.
    try:
        with open(sidecar, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"ok": False, "error": f"cannot read annotations sidecar: {e}"}
    sha = hashlib.sha256(raw).hexdigest()

    try:
        plan = plan_annotations_upload(
            session_id=session_id, trajectory_ledger=traj_ledger,
            annotations_ledger=ann_ledger, annotations_sha=sha, entry=meta_entry)
    except ValueError as e:                             # malformed trajectory key
        return {"ok": False, "error": str(e)}
    if plan["action"] == "refuse":
        return {"ok": False, "error": plan["reason"]}
    if plan["action"] == "noop":                        # unchanged sha -> no re-PUT
        return {"ok": True, "noop": True, "s3_key": plan["s3_key"]}

    # Upload from a temp snapshot of the hashed bytes (never the live sidecar):
    # a concurrent edit between the sha and the PUT self-heals on the next sync.
    tmp = sidecar + f".sync.{os.getpid()}"
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
        etag = upload_one(plan["s3_key"], tmp, plan["metadata"],
                          bucket=bucket, profile=profile)
    except Exception as e:      # continue-on-error posture: flat ok:false + error
        return {"ok": False, "error": str(e), "s3_key": plan["s3_key"]}
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)

    # Ledger write AFTER a successful upload (upload-before-ledger-write). The row
    # is mutable LWW, so re-assigning the session's entry is the intended update.
    try:
        new_ledger = dict(ann_ledger)
        new_ledger[session_id] = annotations_ledger_row(
            plan["s3_key"], sha, etag, _now_iso())
        save_ledger(ann_ledger_path, new_ledger)
    except Exception as e:
        return {"ok": False, "s3_key": plan["s3_key"], "etag": etag,
                "error": f"uploaded but ledger write failed: {e}"}
    return {"ok": True, "s3_key": plan["s3_key"], "etag": etag}


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="atif_to_s3.py",
        description="Idempotently sync redacted capture trajectories to S3.")
    ap.add_argument("--session-id", help="sync only this session (default: all un-synced)")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--profile", default=DEFAULT_PROFILE,
                    help="AWS profile (default dev-admin — the CMK-authorized SSO identity)")
    # Identity is supplied by the command (from get_caller_identity) for ALL modes
    # — --dry-run and --scan compute keys/selection too, so they need it as well.
    ap.add_argument("--principal-id", required=True)
    ap.add_argument("--principal-type", required=True, choices=["user", "machine"])
    ap.add_argument("--org-id", required=True)
    ap.add_argument("--base-dir", default=_DEFAULT_BASE_DIR,
                    help="capture base dir (index.json, ledger, sessions/ live here)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the composed S3 keys; upload nothing, write no ledger")
    ap.add_argument("--scan", action="store_true",
                    help="print by-type PII-scan counts (JSON) for the approval gate")
    return ap


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    base_dir = os.path.expanduser(args.base_dir)
    index_path = os.path.join(base_dir, _INDEX_NAME)
    ledger_path = os.path.join(base_dir, LEDGER_NAME)
    index = load_index(index_path)
    ledger = load_ledger(ledger_path)
    identity = {"principal_id": args.principal_id,
                "principal_type": args.principal_type,
                "org_id": args.org_id}

    # Candidate pool: branch-keyed sessions (optionally the one --session-id),
    # each artifact hashed up front; a missing/unreadable file is skipped inside
    # hash_candidates with a warning so it never enters a selection or an upload.
    shas, paths = hash_candidates(index, base_dir, session_id=args.session_id)

    selected = select_sessions(index, ledger, shas, args.session_id)
    # Only sessions whose artifact we could actually hash are uploadable/scannable.
    selected = [e for e in selected if e.get("session_id") in shas]

    # Empty selection is a clean no-op BEFORE any scan / preflight / upload.
    if not selected:
        print("nothing to sync")
        return 0

    if args.scan:
        print(json.dumps(aggregate_scan(scan_sessions(selected)), indent=2))
        return 0

    if args.dry_run:
        # Keys derive from identity + the entry (session/branch/codebase); the
        # trajectory body is not needed, so dry-run reads no artifact bytes.
        for entry in selected:
            print(plan_upload({}, entry, identity)["key"])
        return 0

    # Real upload. Preflight once so an expired/missing SSO profile fails fast with
    # one clear message instead of N identical per-object errors.
    try:
        preflight_sso(args.profile)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    _, results = sync_sessions(selected, paths=paths, shas=shas,
                               identity=identity, bucket=args.bucket,
                               profile=args.profile, ledger=ledger,
                               ledger_path=ledger_path)
    exit_code = 0
    for result in results:
        if result["ok"]:
            print(f"OK  {result['s3_key']}  (etag {result['etag']})")
        else:
            print(f"error: failed to sync {result['session_id']}: "
                  f"{result['error']}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
