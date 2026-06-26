"""Claude Code JSONL transcript -> ATIF v1.7 trajectory.

Per-agent adapter boundary: this is the *Claude Code* adapter. It builds real
Harbor ATIF Pydantic models (harbor.models.trajectories), so the output is
validated against the actual schema, including:
  - sequential step_ids from 1
  - observation.results[].source_call_id must reference a tool_call_id in the
    SAME step  -> we fold tool_result blocks back into the agent step that
    issued the tool_use, rather than emitting them as separate steps.
  - agent-only fields (model_name/tool_calls/metrics/reasoning_content) only on
    source="agent" steps.

Usage:
    python cc_to_atif.py <session.jsonl> [--task-id T] [--spec-id S]
        [--intent "..."] [--exclude-session-id SID] [--out trajectory.json]
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from harbor.models.trajectories import (
    Agent, FinalMetrics, Metrics, Observation, ObservationResult, Step,
    ToolCall, Trajectory,
)
import pricing

AGENT_NAME = "claude-code"


def _load(path: str) -> list[dict[str, Any]]:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _text_of(content: Any) -> str:
    """Flatten a message/tool_result content field to plain text."""
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
    return "\n".join(p for p in parts if p)


def _usage_to_metrics(usage: dict[str, Any], model: str | None) -> Metrics:
    inp = usage.get("input_tokens", 0) or 0
    cc = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cost = pricing.step_cost_usd(model, input_tokens=inp, cache_creation=cc,
                                 cache_read=cr, output_tokens=out)
    return Metrics(
        prompt_tokens=inp + cc + cr,   # total input incl cached
        completion_tokens=out,
        cached_tokens=cr,
        cost_usd=round(cost, 6),
    )


def _truncate_at_marker(records: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
    """Drop the capture command's own turns (R8): cut the transcript at the LAST
    user message that *invokes* `marker` (e.g. "/drvr:capture-session"), so the
    trajectory ends just before capture was invoked -- a clean prefix.

    Anchored to the start of the message (optionally inside a <command-name>
    wrapper) so prose that merely *mentions* the command is not a false match."""
    cut = None
    for i, rec in enumerate(records):
        if rec.get("type") == "user" and not rec.get("isSidechain"):
            text = _text_of((rec.get("message") or {}).get("content")).strip()
            text = text.replace("<command-name>", "").lstrip()
            if text.startswith(marker):
                cut = i
    return records[:cut] if cut is not None else records


def convert(records: list[dict[str, Any]], *, session_id: str | None,
            task_id: str | None, spec_id: str | None, intent: str | None,
            exclude_session_id: str | None,
            exclude_marker: str | None = None) -> Trajectory:
    if exclude_marker:
        records = _truncate_at_marker(records, exclude_marker)
    steps: list[Step] = []
    # map tool_call_id -> index into `steps` so a later tool_result lands in the
    # same step as its tool_use (ATIF source_call_id within-step rule).
    call_to_step: dict[str, int] = {}
    default_model: str | None = None
    # Claude Code splits one assistant turn across several JSONL records (one per
    # content block: thinking, text, tool_use) that share message.id and REPEAT
    # the same usage. Merge a run of same-id records into one step, counting
    # usage exactly once. Tracked via the last-created agent step.
    last_asst_id: str | None = None
    last_asst_idx: int | None = None

    for rec in records:
        rtype = rec.get("type")
        if rtype not in ("user", "assistant"):
            continue
        if rec.get("isSidechain"):
            continue  # subagent internal turns; out of scope for this test
        if exclude_session_id and rec.get("sessionId") == exclude_session_id:
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        ts = rec.get("timestamp")

        if rtype == "assistant":
            model = msg.get("model")
            default_model = default_model or model
            text, reasoning, tool_calls = "", None, []
            blocks = content if isinstance(content, list) else [
                {"type": "text", "text": content}] if isinstance(content, str) else []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text":
                    text += (("\n" if text else "") + b.get("text", ""))
                elif t == "thinking":
                    reasoning = ((reasoning + "\n") if reasoning else "") + b.get("thinking", "")
                elif t == "tool_use":
                    tool_calls.append(ToolCall(
                        tool_call_id=b.get("id", ""),
                        function_name=b.get("name", "unknown"),
                        arguments=b.get("input", {}) or {},
                    ))
            msg_id = msg.get("id")
            if (msg_id is not None and msg_id == last_asst_id
                    and last_asst_idx == len(steps) - 1):
                # Same logical turn split across records: merge content, keep the
                # already-counted usage (identical across the run).
                prev = steps[last_asst_idx]
                if text:
                    prev.message = (prev.message + ("\n" if prev.message else "") + text
                                    ) if isinstance(prev.message, str) else text
                if reasoning:
                    prev.reasoning_content = (
                        (prev.reasoning_content + "\n") if prev.reasoning_content else ""
                    ) + reasoning
                if tool_calls:
                    prev.tool_calls = (prev.tool_calls or []) + tool_calls
                    for tc in tool_calls:
                        call_to_step[tc.tool_call_id] = last_asst_idx
                continue

            metrics = None
            usage = msg.get("usage")
            if isinstance(usage, dict):
                metrics = _usage_to_metrics(usage, model)
            step = Step(
                step_id=len(steps) + 1,
                timestamp=ts,
                source="agent",
                model_name=model,
                message=text,
                reasoning_content=reasoning,
                tool_calls=tool_calls or None,
                metrics=metrics,
            )
            idx = len(steps)
            steps.append(step)
            last_asst_id, last_asst_idx = msg_id, idx
            for tc in tool_calls:
                call_to_step[tc.tool_call_id] = idx
            continue

        # rtype == "user": either tool_result(s) -> fold into prior agent step,
        # or a genuine human turn -> its own user step.
        results: list[tuple[str, ObservationResult]] = []
        human_text_blocks = []
        blocks = content if isinstance(content, list) else (
            [{"type": "text", "text": content}] if isinstance(content, str) else [])
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tuid = b.get("tool_use_id", "")
                results.append((tuid, ObservationResult(
                    source_call_id=tuid,
                    content=_text_of(b.get("content")),
                    extra={"is_error": True} if b.get("is_error") else None,
                )))
            elif isinstance(b, dict) and b.get("type") == "text":
                human_text_blocks.append(b.get("text", ""))
            elif isinstance(b, str):
                human_text_blocks.append(b)

        for tuid, res in results:
            si = call_to_step.get(tuid)
            if si is None:
                continue  # orphan result (e.g. call excluded); drop
            existing = steps[si].observation.results if steps[si].observation else []
            steps[si].observation = Observation(results=existing + [res])

        human_text = "\n".join(t for t in human_text_blocks if t).strip()
        if human_text:
            steps.append(Step(
                step_id=len(steps) + 1,
                timestamp=ts,
                source="user",
                message=human_text,
            ))

    if not steps:
        raise SystemExit("No user/assistant steps found in transcript.")

    fm = FinalMetrics(
        total_prompt_tokens=sum((s.metrics.prompt_tokens or 0) for s in steps if s.metrics),
        total_completion_tokens=sum((s.metrics.completion_tokens or 0) for s in steps if s.metrics),
        total_cached_tokens=sum((s.metrics.cached_tokens or 0) for s in steps if s.metrics),
        total_cost_usd=round(sum((s.metrics.cost_usd or 0.0) for s in steps if s.metrics), 6),
        total_steps=len(steps),
    )
    extra = {k: v for k, v in {
        "sdlc_task_id": task_id, "sdlc_spec_id": spec_id, "sdlc_intent": intent,
        "source_client": AGENT_NAME,
    }.items() if v is not None}

    return Trajectory(
        schema_version="ATIF-v1.7",
        session_id=session_id,
        agent=Agent(name=AGENT_NAME, version="cc-jsonl-adapter-0.1", model_name=default_model),
        steps=steps,
        final_metrics=fm,
        extra=extra or None,
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
                    help="truncate at the last user turn containing this text "
                         "(e.g. '/drvr:capture-session') to drop the capture cmd's own turns")
    ap.add_argument("--out", default="trajectory.json")
    args = ap.parse_args()

    records = _load(args.transcript)
    session_id = next((r.get("sessionId") for r in records if r.get("sessionId")), None)
    traj = convert(records, session_id=session_id, task_id=args.task_id,
                   spec_id=args.spec_id, intent=args.intent,
                   exclude_session_id=args.exclude_session_id,
                   exclude_marker=args.exclude_marker)

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
