"""Pure planners for the localhost capture-viewer backend.

`/drvr:capture-viewer` serves the capture store (`~/.driver/capture`) to a
local trajectory-viewer UI: a live session list with sync status, per-session
step payloads, PII-scan counts, and a gated multi-session upload. This module
mirrors the functional-core / imperative-shell split of `atif_to_s3.py`: the
PURE planners below decide the viewer Dataset (sync status, uploadability,
run/task shapes), the per-run step payload, the sync-request gate, and the
request routing; the imperative shell (`capture_viewer_server.py` -- sockets,
files, subprocess) calls these.

Pure core discipline (matches `capture_store_core.py`): values in, values out
-- no I/O, clock, or randomness. Timestamps (`generated_at`) and content
hashes (`artifact_shas`) are passed in as arguments so every planner is
deterministic and unit-testable with plain dicts. `is_safe_path_component` is
imported at module top from its defining module (`cc_to_atif_core`, exactly as
`capture_store_core` and `atif_to_s3` do) and guards every URL-supplied
session id inside `route` before any path composition -- a request-supplied id
can never traverse.

The step transform in `build_run_payload` is `atif_to_viewer.build_dataset`'s,
composed from the same imported pieces (`flatten_with_subagents`, `MAX_STEPS`,
`step_from_atif`) -- one transform, not a re-implementation.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime

from atif_to_s3 import branch_from_group_key, is_synced, strip_branch_owner
from atif_to_viewer import (
    MAX_STEPS,
    build_agent_graph,
    flatten_with_subagents,
    step_from_atif,
)
from cc_to_atif_core import is_safe_path_component

# Sync-status wire strings: the viewer's status chips switch on these exact
# values (they also drive the uploadable predicate -- see build_sessions_dataset).
SYNCED, PENDING, MISSING = "synced", "pending", "missing"

# The synthetic vendor/agent every session run hangs off (the viewer's data
# model demands a vendor->agent->task->run hierarchy; sessions get one of each).
_VENDOR_ID = "drvr"
_AGENT_ID = "claude-code"


def sync_status(ledger: dict, session_id: str, artifact_sha: str | None) -> str:
    """Pure: one session's sync status against the ledger.

    MISSING when the artifact could not be hashed (`artifact_sha` is None --
    unreadable or absent); SYNCED when the ledger records this exact sha
    (`is_synced`, so a re-rolled artifact flips back); else PENDING.
    """
    if artifact_sha is None:
        return MISSING
    if is_synced(ledger or {}, session_id, artifact_sha):
        return SYNCED
    return PENDING


def _duration_sec(first_seen, last_seen):
    """Pure: whole seconds between two ISO-8601 stamps, else None (never raises)."""
    if not first_seen or not last_seen:
        return None
    try:
        a = datetime.fromisoformat(str(first_seen).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((b - a).total_seconds()))


def session_run(entry: dict, *, status: str, uploadable: bool) -> dict:
    """Pure: one index entry -> a viewer Run dict.

    Core fields the viewer dereferences without guards: id == sessionId ==
    taskId == session_id, agentId/vendorId singletons, format "atif", status
    "completed", passed False, reward None, steps [] (externalized -- the
    viewer lazy-fetches runs/<id>.json), stepCount and turns = record_count or
    1 (a None/0 count must still trigger the lazy fetch), multiUser True (the
    transcript view keys off it), durationSec from first/last_seen (else None),
    tokens {"costUsd": total_cost_usd}. Plus the extension fields of the
    overview contract: syncStatus/uploadable (computed by the caller --
    build_sessions_dataset owns the predicate), branch (owner-stripped, None
    for ungrouped), codebase (basename(cwd), None when empty), firstSeen/
    lastSeen, costUsd threaded top-level as well as under tokens, and groupKey
    (the raw index thread key for plan-05 grouping -- capture-viewer DEC-023).
    """
    sid = entry.get("session_id")
    raw_branch = branch_from_group_key(entry.get("group_key"))
    branch = strip_branch_owner(raw_branch) if raw_branch is not None else None
    codebase = os.path.basename(entry.get("cwd") or "") or None
    count = entry.get("record_count") or 1
    cost = entry.get("total_cost_usd")
    return {
        "id": sid,
        "taskId": sid,
        "agentId": _AGENT_ID,
        "vendorId": _VENDOR_ID,
        "format": "atif",
        "status": "completed",
        "passed": False,
        "reward": None,
        "steps": [],
        "stepCount": count,
        "multiUser": True,
        "turns": count,
        "durationSec": _duration_sec(entry.get("first_seen"), entry.get("last_seen")),
        "tokens": {"costUsd": cost},
        "sessionId": sid,
        "syncStatus": status,
        "uploadable": uploadable,
        "branch": branch,
        "codebase": codebase,
        "firstSeen": entry.get("first_seen"),
        "lastSeen": entry.get("last_seen"),
        "costUsd": cost,
        # Live session-run thread key for plan 05 grouping: the index entry already
        # carries it, so read it directly (session_run lacks the task/spec/branch
        # group_key_for would recompute from -- capture-viewer DEC-023).
        "groupKey": entry.get("group_key"),
    }


def build_sessions_dataset(index: dict, ledger: dict, artifact_shas: dict,
                           *, generated_at: str) -> dict:
    """Pure: the whole 2-level index -> a viewer-native Dataset dict.

    Covers EVERY group (branch-keyed AND ungrouped) with one task + one run per
    session; task.id == run.id == session_id (the viewer's id<->filename lookup
    contract). Non-dict groups are skipped exactly as `select_sessions` does,
    and the same isinstance discipline extends to entries. Runs (and their
    tasks, pairwise) are sorted by last_seen descending with a `or ""` key so a
    None never raises -- it just sorts last. Task fields mirror
    `atif_to_viewer.build_dataset`'s task shape verbatim (incl. files: [],
    which TaskDetail requires); the title is `<codebase>@<branch>`, falling
    back to the session id when branch is None or codebase is empty/None.

    `artifact_shas` maps session_id -> sha-or-None for EVERY session (the
    all-groups hash pass); `generated_at` is injected by the shell (no clock
    here). uploadable = branch-keyed AND readable AND NOT synced -- exactly the
    sessions `select_sessions` would pick for upload (capture-viewer DEC-008).
    """
    items = []
    for group_key, group in (index or {}).items():
        if not isinstance(group, dict):
            continue
        for sid, entry in group.items():
            if not isinstance(entry, dict):
                continue
            items.append((sid, group_key, entry))
    items.sort(key=lambda item: item[2].get("last_seen") or "", reverse=True)

    tasks: list = []
    runs: list = []
    for sid, group_key, entry in items:
        sha = (artifact_shas or {}).get(sid)
        status = sync_status(ledger or {}, sid, sha)
        branch_keyed = branch_from_group_key(group_key) is not None
        uploadable = branch_keyed and sha is not None and status != SYNCED
        run = session_run(entry, status=status, uploadable=uploadable)
        if run["branch"] and run["codebase"]:
            title = f"{run['codebase']}@{run['branch']}"
        else:
            title = run["id"]
        tasks.append({
            "id": run["id"],
            "vendorId": _VENDOR_ID,
            "title": title,
            "source": "atif",
            "category": _VENDOR_ID,
            "difficulty": "n/a",
            "instruction": "",
            "files": [],
            "metadata": {"spec_id": _VENDOR_ID, "task_id": title,
                         "session_id": run["id"]},
        })
        runs.append(run)

    return {
        "generatedAt": generated_at,
        "vendors": [{"id": _VENDOR_ID, "name": "drvr sessions"}],
        "agents": [{"id": _AGENT_ID, "harness": "Claude Code", "model": None,
                    "family": "Anthropic", "vendorId": _VENDOR_ID}],
        "tasks": tasks,
        "runs": runs,
    }


def build_run_payload(traj: dict) -> dict:
    """Pure: a redacted ATIF traj -> {"steps": [...], "truncated": bool, "agentGraph": {...}}.

    The exact `build_dataset` step transform: `flatten_with_subagents` splices
    subagent subtrees, the `MAX_STEPS` cap bounds the payload, a trailing
    dangling subagent boundary marker is popped, and each step maps through
    `step_from_atif`. `truncated` is True iff the cap trimmed steps -- the UI
    must not present a capped transcript as complete. `agentGraph` rides here as
    the PRIMARY (fork-consumed) home of the subagent-spawn DAG -- session_id
    rooted so a root step's trajId joins its node (capture-viewer DEC-023).
    """
    raw_steps = flatten_with_subagents(traj)
    truncated = len(raw_steps) > MAX_STEPS
    capped = raw_steps[:MAX_STEPS]
    while capped and capped[-1].get("_boundary"):  # never end on a dangling marker
        capped.pop()
    steps = [step_from_atif(s, i) for i, s in enumerate(capped)]
    return {"steps": steps, "truncated": truncated,
            "agentGraph": build_agent_graph(traj)}


def validate_sync_request(body: object, runs_by_id: dict) -> tuple[list[str], str | None]:
    """Pure: THE gate check for the TRAJECTORY sync route (POST /api/sync) -- the
    trajectory route's egress decision is made nowhere else.

    (The sibling annotations-sync route, POST /api/sessions/<id>/annotations/sync,
    has its OWN egress decision point -- `validate_annotations_sync_request` here
    plus `plan_annotations_upload`'s synced-trajectory gate in atif_to_s3 --
    capture-viewer DEC-032/DEC-034.)

    `body` must be a JSON object; `confirm` must be the boolean True (strict
    identity -- "true"/1 and every other truthy look-alike are rejected: the
    confirm click is a deliberate act, not a coercion); `session_ids` must be a
    non-empty list of strings; every id must exist in `runs_by_id` and be
    uploadable, which excludes ungrouped, unreadable, and already-synced
    sessions (capture-viewer DEC-008). Returns (ids, None) on success or
    ([], reason) -- one bad id rejects the whole batch.
    """
    if not isinstance(body, dict):
        return [], "request body must be a JSON object"
    if body.get("confirm") is not True:
        return [], "confirm must be the JSON boolean true"
    ids = body.get("session_ids")
    if (not isinstance(ids, list) or not ids
            or not all(isinstance(i, str) for i in ids)):
        return [], "session_ids must be a non-empty list of strings"
    for sid in ids:
        run = runs_by_id.get(sid)
        if run is None:
            return [], f"unknown session id: {sid}"
        if not run.get("uploadable"):
            return [], f"session is not uploadable: {sid}"
    return list(ids), None


def validate_annotations_sync_request(body: object, doc: dict | None) -> str | None:
    """Pure: THE egress gate for the annotations-sync route (capture-viewer
    DEC-032; sibling of `validate_sync_request`, which gates the trajectory
    route). Returns an error string (-> 400) or None.

    Rules: `body` must be a JSON object carrying the JSON boolean True under
    "confirm" (strict identity -- "true"/1 and every truthy look-alike are
    rejected, exactly as `validate_sync_request` does); the annotations `doc`
    must exist and carry at least one label or tag ("no annotations to sync").
    The synced-trajectory gate itself lives in `plan_annotations_upload`
    (capture-viewer DEC-034) -- this validator is request-shape only.
    """
    if not isinstance(body, dict):
        return "request body must be a JSON object"
    if body.get("confirm") is not True:
        return "confirm must be the JSON boolean true"
    if not isinstance(doc, dict):
        return "no annotations to sync"
    if not (doc.get("stepLabels") or doc.get("runLabels") or doc.get("tags")):
        return "no annotations to sync"
    return None


DEFAULT_ANNOTATIONS = {"version": 1, "sessionId": None,
                       "stepLabels": [], "runLabels": [], "tags": []}
_DECISIONS = {"correct", "incorrect", "unsure"}


def validate_annotations(body: object) -> tuple[bool, str | None]:
    """Pure shape/enum check for a client-posted annotations doc.

    Returns (True, None) on a well-formed doc, else (False, reason). `decision` is
    REQUIRED on every step/run label and must be a known value (capture-viewer
    DEC-026); a stepLabel's `anchor` must be an object carrying both `trajId` and
    `stepId` keys (values may be null -- trajId=session_id for roots, stepId is
    number|null; capture-viewer DEC-025). Absent collections default to empty.
    """
    if not isinstance(body, dict):
        return False, "request body must be a JSON object"
    for key in ("stepLabels", "runLabels"):
        labels = body.get(key, [])
        if not isinstance(labels, list):
            return False, f"{key} must be a list"
        for lab in labels:
            if not isinstance(lab, dict):
                return False, f"{key} entries must be objects"
            if lab.get("decision") not in _DECISIONS:   # decision REQUIRED on every label
                return False, f"invalid decision in {key}"
            if key == "stepLabels":                     # anchor must be {trajId, stepId}
                anchor = lab.get("anchor")               # (keys present; values may be null --
                if (not isinstance(anchor, dict)         #  trajId=session_id for roots,
                        or "trajId" not in anchor        #  stepId is number|null) --
                        or "stepId" not in anchor):      #  capture-viewer DEC-025
                    return False, "stepLabels entries need an anchor {trajId, stepId}"
    tags = body.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return False, "tags must be a list of strings"
    return True, None


def build_annotations_doc(body: dict, *, session_id: str, author: str, now: str) -> dict:
    """Pure: validated client doc -> stored doc. Stamps version/sessionId + per-label
    updatedAt=now; PRESERVES client createdAt AND client per-label author (both
    client-authoritative under LWW full-doc PUT -- capture-viewer DEC-021/DEC-026),
    defaulting each to the current server value only when the client omits it. This
    keeps attribution stable when a *different* reviewer re-posts the doc (plan-06
    cross-machine S3 sync would otherwise rewrite every prior label's author). Notes
    NOT scrubbed (user-authored, local -- capture-viewer DEC-020)."""
    def stamp(lab):
        return {**lab, "author": lab.get("author") or author,
                "createdAt": lab.get("createdAt") or now, "updatedAt": now}
    return {"version": 1, "sessionId": session_id,
            "stepLabels": [stamp(l) for l in body.get("stepLabels", [])],
            "runLabels": [stamp(l) for l in body.get("runLabels", [])],
            "tags": list(body.get("tags", []))}


def parse_annotations(text: str | None, *, session_id: str) -> dict:
    """Pure: sidecar JSON text (or None for a missing file) -> a doc. None/corrupt/
    non-dict -> default doc stamped with sessionId (tolerant -- a corrupt LOCAL
    annotations file degrades to empty, never 500; capture-viewer DEC-019)."""
    if not text:
        return {**DEFAULT_ANNOTATIONS, "sessionId": session_id}
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return {**DEFAULT_ANNOTATIONS, "sessionId": session_id}
    if not isinstance(doc, dict):
        return {**DEFAULT_ANNOTATIONS, "sessionId": session_id}
    if not doc.get("sessionId"):            # backfill a missing OR explicit-null sessionId
        doc["sessionId"] = session_id
    return doc


def normalize_path(raw: str) -> str:
    """Pure: a raw request path -> the routing path.

    Strips the query and fragment (on the RAW path, so an encoded %3F stays
    path data), percent-decodes exactly ONCE (%2540 -> %40, never @ -- a
    double decode would let a doubly-encoded id sneak past the safety check),
    and collapses duplicate slashes. This is the system's ONLY normalization
    site: the shell never decodes, and `route` matches on this output.
    """
    path = (raw or "").split("#", 1)[0].split("?", 1)[0]
    path = urllib.parse.unquote(path)
    return re.sub(r"/{2,}", "/", path)


def route(method: str, raw_path: str) -> tuple[str, dict]:
    """Pure: (method, RAW path) -> (kind, params), kind in 'dataset'|'run'|'scan'|
    'sync'|'annotations_get'|'annotations_post'|'annotations_scan'|
    'annotations_sync'|'api_404'|'static'.

    Normalizes the raw path internally via `normalize_path` before matching.
    HEAD routes like GET (a headers-only reply is the shell's job). POST matches
    /api/sync, /api/sessions/<id>/annotations/sync, and
    /api/sessions/<id>/annotations; any other POST -> api_404, as does any other
    non-GET method. The plan-06 sibling endpoints
    (`/annotations/scan` GET, `/annotations/sync` POST) are MORE-SPECIFIC
    suffixes of `/scan` and `/annotations`, so their branches sit BEFORE those
    and FALL THROUGH (rather than api_404-ing) when the id before the suffix is
    empty/unsafe -- so a session whose id is literally "annotations"
    (`/api/sessions/annotations/scan`) is still handled by the plain `/scan`
    branch instead of being falsely swallowed. The GET branches sit BEFORE the
    /api/ catch-all so the SPA fallback never shadows them; unknown /api/ paths
    are api_404, never static. run/scan/annotations ids must be safe single path
    components (`is_safe_path_component`) or the route degrades to api_404 -- a
    URL-supplied id can never traverse; the id reaches the shell only inside
    `params["session_id"]`.
    """
    path = normalize_path(raw_path)
    verb = "GET" if method == "HEAD" else method
    if verb == "POST":
        if path == "/api/sync":
            return ("sync", {})
        # More-specific suffix first: /annotations/sync before /annotations.
        if path.startswith("/api/sessions/") and path.endswith("/annotations/sync"):
            sid = path[len("/api/sessions/"):-len("/annotations/sync")]
            if is_safe_path_component(sid):
                return ("annotations_sync", {"session_id": sid})
            # else fall through -> api_404 below (empty/unsafe id is not a sync)
        if path.startswith("/api/sessions/") and path.endswith("/annotations"):
            sid = path[len("/api/sessions/"):-len("/annotations")]
            if is_safe_path_component(sid):
                return ("annotations_post", {"session_id": sid})
        return ("api_404", {})
    if verb != "GET":
        return ("api_404", {})
    if path == "/dataset.json":
        return ("dataset", {})
    if path.startswith("/runs/") and path.endswith(".json"):
        sid = path[len("/runs/"):-len(".json")]
        if is_safe_path_component(sid):
            return ("run", {"session_id": sid})
        return ("api_404", {})
    # More-specific suffix first: /annotations/scan before /scan. A fall-through
    # (not api_404) on an empty/unsafe id lets /api/sessions/annotations/scan
    # resolve as the /scan of a session literally named "annotations".
    if path.startswith("/api/sessions/") and path.endswith("/annotations/scan"):
        sid = path[len("/api/sessions/"):-len("/annotations/scan")]
        if is_safe_path_component(sid):
            return ("annotations_scan", {"session_id": sid})
        # else fall through to the /scan branch / api_404 catch-all below
    if path.startswith("/api/sessions/") and path.endswith("/scan"):
        sid = path[len("/api/sessions/"):-len("/scan")]
        if is_safe_path_component(sid):
            return ("scan", {"session_id": sid})
        return ("api_404", {})
    if path.startswith("/api/sessions/") and path.endswith("/annotations"):
        sid = path[len("/api/sessions/"):-len("/annotations")]
        if is_safe_path_component(sid):
            return ("annotations_get", {"session_id": sid})
        return ("api_404", {})
    if path.startswith("/api/"):            # catch-all -- MUST stay AFTER the
        return ("api_404", {})              # annotations GET branch above
    return ("static", {})
