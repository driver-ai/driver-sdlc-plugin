"""Pure helpers for the rolling capture store + throttle (and, later, the
multi-session capture index).

Pure core: values in, values out — no I/O, time, randomness, or shared
mutable state, and no `import harbor`. The shell (hooks/roll-capture.sh) performs
all file I/O and calls these.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass

from cc_to_atif_core import is_safe_path_component  # traversal guard reuse


def store_path_for(base_dir: str, session_id: str,
                   task_id: str | None = None) -> str:
    """Pure: the keyed store path for a session's rolled redacted trajectory.

    Returns "<base_dir>/sessions/<session_id>/trajectory.redacted.json". Raises
    ValueError when session_id is not a safe single path segment so a
    transcript-supplied id can never traverse out of base_dir. task_id is accepted
    for forward-compat with arc-keyed layouts but does not widen the path today.
    """
    if not is_safe_path_component(session_id):
        raise ValueError(f"unsafe session_id path component: {session_id!r}")
    return os.path.join(base_dir, "sessions", session_id, "trajectory.redacted.json")


@dataclass(frozen=True)
class RollThreshold:
    min_record_delta: int = 20    # roll after >= this many new transcript lines
    min_seconds: float = 30.0     # ...or after this many seconds since last roll
    min_first_count: int = 2      # ...but hold the first roll until the transcript has content


def should_roll(prev_count: int, prev_mtime: float, cur_count: int,
                cur_mtime: float, threshold: RollThreshold) -> bool:
    """Pure throttle decision: True when enough has changed to re-derive.

    First roll (prev_count <= 0) fires once the transcript has at least
    min_first_count lines, so a brand-new session is captured early but a
    too-thin transcript (no completed assistant step yet) is not converted
    prematurely. Otherwise True when the line-count delta OR the elapsed
    transcript mtime crosses the threshold. Values in, bool out — no clock, no I/O.
    """
    if prev_count <= 0:
        return cur_count >= threshold.min_first_count
    return ((cur_count - prev_count) >= threshold.min_record_delta
            or (cur_mtime - prev_mtime) >= threshold.min_seconds)


def is_store_fresh(prev_count: int, cur_count: int,
                   threshold: RollThreshold) -> bool:
    """Pure: True when a previously-rolled store is fresh enough to flush as-is.

    Fresh <=> a roll was recorded (prev_count > 0) and the transcript has grown by
    fewer than min_record_delta lines since that roll. The flush uses this to choose
    store-read vs. re-derive; values in, bool out.
    """
    if prev_count <= 0:
        return False
    return (cur_count - prev_count) < threshold.min_record_delta


def group_key_for(task_id: str | None, spec_id: str | None,
                  branch: str | None) -> str:
    """Pure: the arc identity (stable across the sessions of one work arc).

    Precedence: task_id, then spec_id, then 'branch:<branch>', then 'ungrouped'.
    task/spec are the explicit SDLC ids; branch is the automatic fallback. Empty
    or whitespace-only strings count as absent, so a blank or stray-whitespace CLI
    flag falls through to the next level (and a returned key is never padded).
    """
    task_id = task_id.strip() if isinstance(task_id, str) else task_id
    spec_id = spec_id.strip() if isinstance(spec_id, str) else spec_id
    branch = branch.strip() if isinstance(branch, str) else branch
    if task_id:
        return task_id
    if spec_id:
        return spec_id
    if branch:
        return f"branch:{branch}"
    return "ungrouped"


def is_provisional_group(group_key: object) -> bool:
    """Pure: True for the non-globally-unique keys ('branch:*' / 'ungrouped') that
    resolve_lineage must guard with a cwd match (a bare branch name can collide
    across repos/worktrees). The rolling index always uses such keys.
    Tolerates a non-str argument (returns False) so a stray key can't crash a
    fail-open caller."""
    if not isinstance(group_key, str):
        return False
    return group_key == "ungrouped" or group_key.startswith("branch:")


def update_index(index: dict, entry: dict) -> dict:
    """Pure: return a NEW index with `entry` recorded under entry['group_key'].

    A session belongs to exactly ONE group:
      - same session_id, same group  -> merge in place (resume / roll enrich);
      - new session_id               -> union (no dedup; disjoint sessions);
      - same session_id, DIFFERENT group key -> migrate the record to the new group.
        The rolling index is branch-keyed, so this fires only on a branch switch
        mid-session (e.g. 'branch:main' -> 'branch:feature'). first_seen is preserved;
        the emptied old group is pruned.
    first_seen is preserved. prev_session_id (the lineage parent) is fixed at the session's
    first appearance and is immutable for re-rolls within the same arc (so the chain can't
    churn into cycles, even when the first session's prev is None); a branch-switch migrate
    recomputes it for the new arc. An accumulator (record_count/total_cost_usd)
    is treated as absent ONLY when the incoming value is None, so a genuine 0/0.0 from a
    free/cached roll overwrites a stale prior; an absent (None) incoming value never
    clobbers a real prior. Input is not mutated (deep-copied).

    Shape: {group_key: {session_id: {session_id, store_path, cwd, first_seen,
    last_seen, record_count, total_cost_usd, prev_session_id}}}.
    """
    out = copy.deepcopy(index)
    new_gk = entry["group_key"]
    sid = entry["session_id"]
    prior_gk, prior = None, None
    for gk, group in out.items():               # find this session anywhere (migrate)
        if sid in group:
            prior_gk, prior = gk, group[sid]
            break
    if prior is not None:
        merged = {**prior, **entry}
        merged["first_seen"] = prior.get("first_seen", entry.get("first_seen"))
        if prior_gk == new_gk:                  # same arc: lineage is immutable (fixed at
            merged["prev_session_id"] = prior.get("prev_session_id")  # first appearance, so
            #                            re-rolls can't churn the chain into a cycle, even
            #                            when the first session's prev is None)
        # else (branch switch): keep entry's freshly-computed prev for the NEW arc
        for acc in ("record_count", "total_cost_usd"):
            if entry.get(acc) is None:          # absent only when None -> keep prior
                merged[acc] = prior.get(acc)
        if prior_gk != new_gk:                  # branch switch: drop from the old group
            del out[prior_gk][sid]
            if not out[prior_gk]:
                del out[prior_gk]
    else:
        merged = dict(entry)
    out.setdefault(new_gk, {})[sid] = merged
    return out


def resolve_lineage(index: dict, group_key: str, cwd: str,
                    new_session_id: str) -> str | None:
    """Pure: the most-recent prior session_id for this arc (the lineage parent CC
    does not record), or None for the first session / an unidentifiable arc.

    'ungrouped' is never linked. For a 'branch:<x>' key (the rolling index's normal
    key), candidates are restricted to a matching cwd (caller MUST pass
    a realpath-normalized cwd; the stored cwd is normalized the same way) so a bare
    branch shared across repos/worktrees does not cross-link unrelated work. A
    task/spec key (kept for generality; unused by the rolling index) ignores cwd.
    'Most recent' = max (last_seen, session_id) -> deterministic tie-break.
    """
    if group_key == "ungrouped":
        return None
    group = index.get(group_key) or {}
    generic = is_provisional_group(group_key)
    candidates = [v for sid, v in group.items()
                  if sid != new_session_id and (not generic or v.get("cwd") == cwd)]
    if not candidates:
        return None
    best = max(candidates,
               key=lambda v: (v.get("last_seen", ""), v.get("session_id", "")))
    return best.get("session_id")


def complete_identity(traj: dict, task_id: str | None, spec_id: str | None,
                      branch: str | None) -> dict:
    """Pure: return a NEW traj with an absent grouping identity filled from the
    flush's resolved task/spec + git branch, so a store-fresh artifact (converted
    with none of the identity flags) groups in Opik by task/branch instead of
    'ungrouped'.

    Absent-only and idempotent: a value already present is never overwritten, so the
    re-derive arm (which already carries task/spec/branch) is a no-op. Whitespace-only
    inputs count as absent (never stored). A non-dict 'extra' or 'extra.environment'
    is coerced to a dict, so a malformed artifact can't crash a fail-open caller.
    Content-free: only ids and the branch are written. Input is not mutated (deep-copied).
    """
    def _clean(v):
        v = v.strip() if isinstance(v, str) else v
        return v or None
    task_id, spec_id, branch = _clean(task_id), _clean(spec_id), _clean(branch)
    out = copy.deepcopy(traj)
    extra = out.get("extra")
    if not isinstance(extra, dict):
        extra = out["extra"] = {}
    # presence checks _clean the STORED value too, so a stored whitespace-only id/branch
    # counts as absent and is filled -- matching group_key_for's strip semantics and closing
    # the last asymmetry between input-cleaning and stored-value detection (a real value stays
    # truthy after _clean, so the re-derive arm is still a no-op / idempotent).
    if task_id and not _clean(extra.get("sdlc_task_id")):
        extra["sdlc_task_id"] = task_id
    if spec_id and not _clean(extra.get("sdlc_spec_id")):
        extra["sdlc_spec_id"] = spec_id
    if branch:
        env = extra.get("environment")
        if not isinstance(env, dict):
            env = extra["environment"] = {}
        if not _clean(env.get("branch")):
            env["branch"] = branch
    return out
