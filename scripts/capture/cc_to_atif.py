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
from typing import Any

from harbor.models.trajectories import (
    Agent, FinalMetrics, Metrics, Observation, ObservationResult, Step,
    ToolCall, Trajectory,
)
import cc_to_atif_core as core


def _load(path: str) -> list[dict[str, Any]]:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def to_trajectory(n: "core.NormalizedTrajectory") -> Trajectory:
    """Map the harbor-free NormalizedTrajectory onto validated Harbor ATIF v1.7
    models. Mechanical 1:1 map; the nullability guards are where harbor validation
    bites:
      - tool_calls: [] -> None (harbor wants None, not an empty list).
      - metrics: dict -> Metrics(**d) when present, else None.
      - observation: built only when observation_results is non-empty, else None.
        source_call_id is preserved from the core (within-step rule).
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
    return Trajectory(
        schema_version="ATIF-v1.7",
        session_id=n.session_id,
        agent=Agent(**n.agent),
        steps=steps,
        final_metrics=FinalMetrics(**n.final_metrics),
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
    ap.add_argument("--out", default="trajectory.json")
    args = ap.parse_args()

    records = _load(args.transcript)
    session_id = next((r.get("sessionId") for r in records if r.get("sessionId")), None)
    try:
        normalized = core.normalize(
            records, session_id=session_id, task_id=args.task_id,
            spec_id=args.spec_id, intent=args.intent,
            exclude_session_id=args.exclude_session_id,
            exclude_marker=args.exclude_marker,
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
