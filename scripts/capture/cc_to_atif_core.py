"""Pure helpers around the upstream logs2atif converter.

The Claude Code JSONL walk (record grouping, tool_result folding, usage/cost
math, subagent embedding) is done by the logs2atif library, called from the
imperative shell (`cc_to_atif.py`). This module keeps the small pure pieces
that the shell and the display consumers need:

  * `prefilter_records`   -- what logs2atif must never see (marker truncation,
    session-id exclusion, inline sidechain drop, list-form user content)
  * `flatten_content`     -- shared str / ContentPart-list -> display text
  * `rollup_subagent_tokens`     -- subagent-inclusive parent token totals
  * `link_nested_subagent_refs`  -- depth-agnostic subagent ref re-link
  * `sanitize_jsonl_lines`       -- staging tolerance for subagent files
  * `inject_capture_extra`       -- environment / SDLC identity on the artifact
  * `is_safe_path_component`     -- path-segment guard (imported by
    `capture_store_core` and the shell)

Pure core: values in, values out -- no I/O, time, randomness, or third-party
imports (stdlib only; logs2atif is imported only by the shell). The enrichment
passes operate on the SERIALIZED trajectory dict (`trajectory.to_json_dict()`),
never on pydantic models.
"""
from __future__ import annotations

import json
from typing import Any


def is_safe_path_component(name: Any) -> bool:
    """Pure: True when `name` is safe to use as a single filesystem path segment.

    The shell joins a transcript-supplied session_id into the subagent-dir path, so a
    value like '../../../etc' would otherwise resolve outside the capture dir. A safe
    segment is a non-empty str with no path separator or NUL byte, that is not '.'/'..'
    and does not start with '.'. Real Claude Code session ids are opaque UUIDs, which
    always pass; an unsafe id makes the shell skip subagent discovery, not crash.
    """
    if not isinstance(name, str) or not name or name.startswith("."):
        return False
    return not any(c in name for c in ("/", "\\", "\x00"))


def _blocks_to_text(content: Any) -> str:
    """Flatten raw Claude Code message content to plain text: str passes through;
    a block list joins its text blocks with newlines and renders any other typed
    block as a `[<type>]` placeholder (presence preserved, payload dropped)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if not isinstance(b, dict):
            parts.append(str(b))
        elif b.get("type") == "text":
            parts.append(b.get("text", ""))
        elif b.get("type"):                       # image / document / etc.
            parts.append(f"[{b['type']}]")
    return "\n".join(p for p in parts if p)


def _flatten_user_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Return `rec` with list-form user content flattened to a plain string, or
    `rec` itself (untouched) when nothing needs flattening. tool_result-bearing
    lists and non-user records always pass through."""
    msg = rec.get("message")
    if rec.get("type") != "user" or not isinstance(msg, dict):
        return rec
    content = msg.get("content")
    if not isinstance(content, list) or any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content):
        return rec
    return {**rec, "message": {**msg, "content": _blocks_to_text(content)}}


def prefilter_records(records: list[dict[str, Any]], *,
                      exclude_marker: str | None = None,
                      exclude_session_id: str | None = None) -> list[dict[str, Any]]:
    """Pure: drop/normalize what logs2atif must never see.

    1. Truncate at the LAST non-sidechain user record whose first command token
       equals `exclude_marker`, after unwrapping a literal `<command-name>` tag
       (whole-token match: '/drvr:capture-session foo' cuts,
       '/drvr:capture-session-foo' does not; prose mentions and sidechain user
       records never match). Pre-existing limit carried over: the unwrap does
       not fire on the modern `<command-message>`-first record shape, so only
       bare-typed commands truncate -- parity with today.
    2. Drop records whose sessionId equals `exclude_session_id`.
    3. Drop isSidechain:true records -- subagent work reaches the trajectory only
       via the separate subagent files, so an (older-CC) inline copy can never
       double-count against logs2atif's sidechain-keeping port.
    4. Flatten list-form USER content carrying no tool_result block into a plain
       string (text parts joined with newlines; non-text blocks -> '[<type>]'
       placeholder) -- the port JSON-stringifies such blocks verbatim, pasted
       screenshots' base64 payloads included. tool_result-bearing lists and
       non-user records pass through untouched.
    """
    if exclude_marker:
        cut = None
        for i, rec in enumerate(records):
            if rec.get("type") == "user" and not rec.get("isSidechain"):
                text = _blocks_to_text((rec.get("message") or {}).get("content")).strip()
                text = text.replace("<command-name>", "").lstrip()
                first_token = text.split(None, 1)[0] if text else ""
                if first_token == exclude_marker:
                    cut = i
        if cut is not None:
            records = records[:cut]
    out = []
    for rec in records:
        if exclude_session_id and rec.get("sessionId") == exclude_session_id:
            continue
        if rec.get("isSidechain"):
            continue
        out.append(_flatten_user_record(rec))
    return out


def flatten_content(content: Any) -> str:
    """Pure: message/observation content -> display text.

    str passes through; a list of ATIF ContentPart-shaped dicts joins its
    type=="text" parts and renders type=="image" as
    '[image: <media_type> <path>]' -- both fields read from the NESTED source
    block (part["source"]["media_type"] / ["path"], the real ATIF shape); other
    dict types become '[<type>]'; non-dict items str(). None -> "". Shared by
    the viewer, Opik, and render_trace so all review/display surfaces show the
    same flattened text.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if not isinstance(part, dict):
            parts.append(str(part))
        elif part.get("type") == "image":
            src = part.get("source") or {}
            parts.append(f"[image: {src.get('media_type', '?')} {src.get('path', '?')}]")
        elif part.get("type") == "text":
            parts.append(part.get("text", ""))
        elif part.get("type"):
            parts.append(f"[{part['type']}]")
    return "\n".join(p for p in parts if p)


_TOKEN_TOTALS = (("total_prompt_tokens", "prompt_tokens"),
                 ("total_completion_tokens", "completion_tokens"),
                 ("total_cached_tokens", "cached_tokens"))


def rollup_subagent_tokens(traj: dict) -> dict:
    """Pure: make parent final_metrics token totals subagent-INCLUSIVE (in place
    on the serialized trajectory dict; returns it for chaining).

    Upstream keeps total_{prompt,completion,cached}_tokens parent-only (safe for
    batch root-summing) while total_cost_usd is already subtree-inclusive -- and
    embedded subagents carry NO final_metrics token totals at all (cost-only
    after exclude_none), so the sum walks each subagent's PER-STEP metrics
    (steps[].metrics.{prompt,completion,cached}_tokens). Our only consumers are
    single-session human displays where tokens and cost must reconcile. Cost and
    total_steps are never touched. None-safe: absent metrics/keys count 0;
    parent totals created when absent; no subagent_trajectories -> identity.
    The embedded list is flat (children never nest their own subagents) -- no
    recursion.
    """
    subs = traj.get("subagent_trajectories") or []
    if not subs:
        return traj
    sums = dict.fromkeys((total for total, _ in _TOKEN_TOTALS), 0)
    for sub in subs:
        for step in sub.get("steps") or []:
            metrics = step.get("metrics") or {}
            for total, per_step in _TOKEN_TOTALS:
                sums[total] += metrics.get(per_step) or 0
    fm = traj.setdefault("final_metrics", {})
    for total, _ in _TOKEN_TOTALS:
        fm[total] = (fm.get(total) or 0) + sums[total]
    return traj


def link_nested_subagent_refs(traj: dict) -> dict:
    """Pure: depth-agnostic subagent_trajectory_ref re-link on the serialized
    trajectory (in place; returns it for chaining).

    Upstream attaches refs to PARENT steps only; a depth>=2 subagent (spawned by
    another subagent) is embedded but unreferenced, so viewer/Opik render it
    "(unlinked)" at root instead of nested. Build toolUseId -> trajectory_id
    from every subagent_trajectories[].agent.extra, then over parent AND
    subagent steps alike attach {"trajectory_id": ...} under
    steps[].observation.results[] -- the results entry whose source_call_id
    equals a mapped tool_call_id in the same step (the within-step rule).
    Idempotent: refs upstream already attached are not duplicated; unmatched
    ids no-op.
    """
    subs = traj.get("subagent_trajectories") or []
    by_tool_use = {}
    for sub in subs:
        tuid = ((sub.get("agent") or {}).get("extra") or {}).get("toolUseId")
        if tuid and sub.get("trajectory_id"):
            by_tool_use[tuid] = sub["trajectory_id"]
    for holder in (traj, *subs):
        for step in holder.get("steps") or []:
            for call in step.get("tool_calls") or []:
                traj_id = by_tool_use.get(call.get("tool_call_id"))
                if traj_id is None:
                    continue
                # Serialized shape: results nest under step["observation"].
                results = (step.get("observation") or {}).get("results") or []
                for result in results:
                    if result.get("source_call_id") != call.get("tool_call_id"):
                        continue
                    refs = result.get("subagent_trajectory_ref")
                    if not isinstance(refs, list):
                        refs = []
                        result["subagent_trajectory_ref"] = refs
                    if not any(r.get("trajectory_id") == traj_id for r in refs):
                        refs.append({"trajectory_id": traj_id})
    return traj


def sanitize_jsonl_lines(lines: list[str]) -> list[str]:
    """Pure: keep only lines that json-parse to dicts (kept lines
    byte-identical). Staged subagent copies are built from this -- upstream
    tolerates unparseable lines but crashes the WHOLE conversion on valid-JSON
    non-dict lines (null / strings / arrays), where today we lose only the
    line.
    """
    kept = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            kept.append(line)
    return kept


def inject_capture_extra(traj: dict, *, environment: dict | None,
                         task_id: str | None, spec_id: str | None,
                         intent: str | None) -> dict:
    """Pure: set extra.environment / extra.sdlc_{task_id,spec_id,intent} on the
    serialized trajectory (in place; returns it for chaining). A key is set ONLY
    when its value is truthy -- absent facts stay absent (never null). Creates
    `extra` if the upstream trajectory has none and something is set (nothing
    truthy leaves the trajectory unchanged); preserves upstream extra keys.
    """
    injected = {k: v for k, v in {
        "environment": environment,
        "sdlc_task_id": task_id,
        "sdlc_spec_id": spec_id,
        "sdlc_intent": intent,
    }.items() if v}
    if injected:
        extra = traj.get("extra")
        if not isinstance(extra, dict):
            extra = {}
            traj["extra"] = extra
        extra.update(injected)
    return traj
