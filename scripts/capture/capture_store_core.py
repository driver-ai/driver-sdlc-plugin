"""Pure helpers for the rolling capture store + throttle (and, later, the
multi-session capture index).

Pure core: values in, values out — no I/O, time, randomness, or shared
mutable state, and no `import harbor`. The shell (hooks/roll-capture.sh) performs
all file I/O and calls these.
"""
from __future__ import annotations

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
