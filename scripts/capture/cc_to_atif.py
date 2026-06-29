"""Claude Code JSONL transcript -> ATIF v1.7 trajectory.

Per-agent adapter boundary: this is the *Claude Code* adapter shell. The hard
normalization logic lives in the harbor-free kernel `cc_to_atif_core.normalize`;
this module isolates harbor: `to_trajectory` maps the kernel's plain StepRecords
onto real Harbor ATIF Pydantic models (harbor.models.trajectories), so the output
is validated against the actual schema, including:
  - sequential step_ids from 1
  - observation.results[].source_call_id must reference a tool_call_id in the
    SAME step  -> the kernel folds tool_result blocks back into the agent step
    that issued the tool_use, rather than emitting them as separate steps.
  - agent-only fields (model_name/tool_calls/metrics/reasoning_content) only on
    source="agent" steps.

Usage:
    python cc_to_atif.py <session.jsonl> [--task-id T] [--spec-id S]
        [--intent "..."] [--exclude-session-id SID] [--exclude-marker M]
        [--out trajectory.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from harbor.models.trajectories import (
    Agent, FinalMetrics, Metrics, Observation, ObservationResult, Step,
    ToolCall, Trajectory,
)
from pydantic import ValidationError
import cc_to_atif_core as core
import environment


def _load(path: str) -> list[dict[str, Any]]:
    """Read JSONL records, skipping lines that are not JSON objects.

    A corrupt (non-JSON) line and a valid-JSON-but-non-dict line (a bare array,
    string, or number) are each skipped with a stderr warning rather than
    aborting the whole file: one bad line in a long transcript must not lose the
    rest of the run. Used for both the main transcript and each subagent file.
    """
    out = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"warning: skipping corrupt line {n} in {path}: {e}", file=sys.stderr)
                continue
            if not isinstance(obj, dict):
                print(f"warning: skipping non-object line {n} in {path}", file=sys.stderr)
                continue
            out.append(obj)
    return out


def to_trajectory(n: "core.NormalizedTrajectory") -> Trajectory:
    """Map the harbor-free NormalizedTrajectory onto validated Harbor ATIF v1.7
    models. Mechanical 1:1 map; the nullability guards are where harbor validation
    bites:
      - tool_calls: [] -> None (harbor wants None, not an empty list).
      - metrics: dict -> Metrics(**d) when present, else None.
      - observation: built only when observation_results is non-empty, else None.
        source_call_id is preserved from the core (within-step rule).
      - trajectory_id: None on the root, set on each subagent (harbor rejects a
        null embedded subagent id).
      - subagent_trajectories: each embedded subagent is mapped the same way; a
        subagent that fails harbor validation is dropped (stderr warning) so the
        parent is still emitted. [] -> None (harbor wants None, not an empty list).
        subagent_trajectory_ref on an ObservationResult is coerced by harbor.
    """
    steps = []
    for r in n.steps:
        steps.append(Step(
            step_id=r.step_id,
            timestamp=r.timestamp,
            source=r.source,
            model_name=r.model_name,
            message=r.message,
            reasoning_content=r.reasoning_content,
            tool_calls=[ToolCall(**tc) for tc in r.tool_calls] or None,
            metrics=Metrics(**r.metrics) if r.metrics else None,
            observation=Observation(results=[ObservationResult(**o) for o in r.observation_results])
                        if r.observation_results else None,
        ))
    subs = []
    for s in n.subagent_trajectories:
        try:
            subs.append(to_trajectory(s))   # subagents are flat: recursion is one level deep
        except ValidationError as e:
            print(f"warning: dropping invalid subagent {s.trajectory_id!r}: {e}",
                  file=sys.stderr)
    return Trajectory(
        schema_version="ATIF-v1.7",
        session_id=n.session_id,
        trajectory_id=n.trajectory_id,
        agent=Agent(**n.agent),
        steps=steps,
        final_metrics=FinalMetrics(**n.final_metrics),
        subagent_trajectories=subs or None,
        extra=n.extra or None,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--task-id")
    ap.add_argument("--spec-id")
    ap.add_argument("--intent")
    ap.add_argument("--exclude-session-id",
                    help="drop records from this sessionId (the capture cmd's own session)")
    ap.add_argument("--exclude-marker",
                    help="truncate at the last user turn whose command equals this text "
                         "(e.g. '/drvr:capture-session') to drop the capture cmd's own turns")
    ap.add_argument("--env-file",
                    help="JSON file of raw env facts (codebase_url, cwd, branch, "
                         "commit_start, commit_end, mcp_endpoint, mcp_version) "
                         "gathered by the caller")
    ap.add_argument("--session-dir",
                    help="project dir; capture subagents from "
                         "<dir>/<session-id>/subagents/agent-*.jsonl")
    ap.add_argument("--out", default="trajectory.json")
    args = ap.parse_args()

    # Shell: read the env-file (I/O) and build the env block via the pure core.
    # build_environment returns {} when no facts are present; core.normalize then
    # drops an empty environment, so we pass the built dict straight through (M4).
    env_block = None
    if args.env_file:
        try:
            with open(args.env_file) as fh:
                facts = json.load(fh)
        except FileNotFoundError:
            print(f"error: --env-file not found: {args.env_file}", file=sys.stderr)
            raise SystemExit(1)
        except json.JSONDecodeError as e:
            print(f"error: --env-file is not valid JSON: {e}", file=sys.stderr)
            raise SystemExit(1)
        # Extract only the 7 known fact keys; unknown keys are ignored (M5).
        env_block = environment.build_environment(
            codebase_url=facts.get("codebase_url"), cwd=facts.get("cwd"),
            branch=facts.get("branch"), commit_start=facts.get("commit_start"),
            commit_end=facts.get("commit_end"), mcp_endpoint=facts.get("mcp_endpoint"),
            mcp_version=facts.get("mcp_version"),
        )

    records = _load(args.transcript)
    session_id = next((r.get("sessionId") for r in records if r.get("sessionId")), None)

    # Shell: discover this session's subagents (I/O). The glob is session-scoped
    # to <project-dir>/<session-id>/subagents/ so a project dir holding many
    # sessions never embeds another session's subagents. Each subagent gets a
    # session-qualified trajectory_id derived from its file stem; the kernel
    # assembles, rolls up, and links them. With no --session-dir (or no
    # sessionId) the subagents list stays empty and normalize_session reproduces
    # the main-transcript-only output.
    subagents: list[tuple[dict, list[dict[str, Any]]]] = []
    if args.session_dir:
        if session_id is None:
            print("warning: --session-dir set but no sessionId in transcript; "
                  "capturing no subagents", file=sys.stderr)
        else:
            sub_dir = Path(args.session_dir) / session_id / "subagents"
            paths = sorted(sub_dir.glob("agent-*.jsonl"))
            if not paths:
                print(f"warning: no subagents found under {sub_dir}", file=sys.stderr)
            for jp in paths:
                try:
                    recs = _load(str(jp))
                    if not recs:
                        continue
                    mp = jp.with_name(f"{jp.stem}.meta.json")
                    meta = json.loads(mp.read_text()) if mp.exists() else {}
                    meta["trajectory_id"] = f"{session_id}/{jp.stem}"
                    subagents.append((meta, recs))
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    print(f"warning: skipping subagent {jp.name}: {e}", file=sys.stderr)

    try:
        normalized = core.normalize_session(
            records, subagents, session_id=session_id, task_id=args.task_id,
            spec_id=args.spec_id, intent=args.intent,
            exclude_session_id=args.exclude_session_id,
            exclude_marker=args.exclude_marker,
            environment=env_block,
        )
    except core.EmptyTranscriptError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    traj = to_trajectory(normalized)

    with open(args.out, "w") as fh:
        json.dump(traj.to_json_dict(), fh, indent=2)

    fm = traj.final_metrics
    tools = sorted({tc.function_name for s in traj.steps for tc in (s.tool_calls or [])})
    peak = max((s.metrics.prompt_tokens or 0) for s in traj.steps if s.metrics) if traj.steps else 0
    print(f"OK  {args.out}")
    print(f"    schema={traj.schema_version} session={traj.session_id}")
    print(f"    steps={fm.total_steps}  prompt_tok={fm.total_prompt_tokens}  "
          f"compl_tok={fm.total_completion_tokens}  cost=${fm.total_cost_usd}")
    print(f"    peak_step_context_tokens={peak}")
    print(f"    tools_used={','.join(tools) if tools else '(none)'}")


if __name__ == "__main__":
    main()
