"""Harbor-free normalization kernel: Claude Code JSONL records -> NormalizedTrajectory.

Pure core (DEC-011): values in, values out -- no I/O, time, randomness, or shared
mutable state, and **no `import harbor`**. The harbor ATIF models are built by the
adapter in `cc_to_atif.to_trajectory`. The hard-won walk logic (message.id grouping,
tool_result folding, cost-from-usage, marker truncation) lives here so it is testable
under the stdlib-only rule.

Raises `EmptyTranscriptError` (not `SystemExit`) when no steps result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pricing

AGENT_NAME = "claude-code"                 # owned by the core
ADAPTER_VERSION = "cc-jsonl-adapter-0.1"   # owned by the core


class EmptyTranscriptError(ValueError):
    """No user/assistant steps found in the transcript."""


@dataclass
class StepRecord:
    step_id: int
    timestamp: str | None
    source: str                      # "agent" | "user"
    message: str = ""
    model_name: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)   # {tool_call_id, function_name, arguments}
    metrics: dict | None = None      # {prompt_tokens, completion_tokens, cached_tokens, cost_usd}
    observation_results: list[dict] = field(default_factory=list)  # {source_call_id, content, extra?}


@dataclass
class NormalizedTrajectory:
    session_id: str | None
    agent: dict                      # {name, version, model_name}
    steps: list[StepRecord]
    final_metrics: dict              # {total_prompt_tokens, ..., total_steps}
    extra: dict                      # {sdlc_*, source_client, environment?, unpriced_models?}


def _text_of(content: Any) -> str:
    """Flatten a message/tool_result content field to plain text.

    Non-text dict blocks (image, document, ...) become a `[<type>]` placeholder so
    their presence is preserved, not silently dropped (M8). Plain strings pass
    through; non-dict blocks `str()`.
    """
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
        elif b.get("type"):                       # image / document / etc. (M8)
            parts.append(f"[{b['type']}]")
    return "\n".join(p for p in parts if p)


def _usage_to_metrics(usage: dict[str, Any], model: str | None) -> dict:
    inp = usage.get("input_tokens", 0) or 0
    cc = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cost = pricing.step_cost_usd(model, input_tokens=inp, cache_creation=cc,
                                 cache_read=cr, output_tokens=out)
    return {
        "prompt_tokens": inp + cc + cr,   # total input incl cached
        "completion_tokens": out,
        "cached_tokens": cr,
        "cost_usd": round(cost, 6),
    }


def _truncate_at_marker(records: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
    """Drop the capture command's own turns (R8): cut the transcript at the LAST
    user message whose command *invokes* `marker` (e.g. "/drvr:capture-session"), so
    the trajectory ends just before capture was invoked -- a clean prefix.

    Match the marker as a **whole command token** (M9): after the optional
    `<command-name>` unwrap, the first whitespace-delimited token of the cleaned user
    text must **equal** the marker. So `/drvr:capture-session foo` truncates but
    `/drvr:capture-session-foo` (a longer command) does NOT. Prose that merely
    *mentions* the command is not a false match. User/non-sidechain turns only.
    """
    cut = None
    for i, rec in enumerate(records):
        if rec.get("type") == "user" and not rec.get("isSidechain"):
            text = _text_of((rec.get("message") or {}).get("content")).strip()
            text = text.replace("<command-name>", "").lstrip()
            first_token = text.split(None, 1)[0] if text else ""
            if first_token == marker:
                cut = i
    return records[:cut] if cut is not None else records


def normalize(records: list[dict[str, Any]], *, session_id: str | None,
              task_id: str | None, spec_id: str | None, intent: str | None,
              exclude_session_id: str | None, exclude_marker: str | None = None,
              environment: dict | None = None) -> NormalizedTrajectory:
    """Pure JSONL-records -> NormalizedTrajectory. Main transcript only (isSidechain
    skipped, DEC-018). Raises EmptyTranscriptError if no steps result.

    Ports the spike `convert` onto plain StepRecords + dict metrics:
      - message.id grouping: a run of same-id assistant records is ONE step; usage
        counted ONCE per group. H6: if the existing step's metrics is None and a
        later same-group record carries usage, FILL metrics from it (count once).
      - tool_result folding: a later user tool_result whose tool_use_id maps to a
        prior agent step folds in as an observation_result (within-step
        source_call_id); an orphan tool_result is dropped; DUPLICATE results for one
        tool_use_id are KEPT (both fold in -- M11).
      - human user turn -> its own source="user" step.
      - cost-from-usage via pricing.step_cost_usd; UNKNOWN models are collected into
        extra["unpriced_models"] so silent fallback-pricing is visible (M7).
      - newer record types (mode/last-prompt/ai-title/attachment/
        file-history-snapshot/queue-operation) skipped without perturbing pairing.
    """
    if exclude_marker:
        records = _truncate_at_marker(records, exclude_marker)   # exact-command match (M9)
    steps: list[StepRecord] = []
    # map tool_call_id -> index into `steps` so a later tool_result lands in the
    # same step as its tool_use (ATIF source_call_id within-step rule).
    call_to_step: dict[str, int] = {}
    default_model: str | None = None
    unpriced: list[str] = []                  # M7 (deduped, order-preserving)
    # Claude Code splits one assistant turn across several JSONL records (one per
    # content block: thinking, text, tool_use) that share message.id and REPEAT
    # the same usage. Merge a run of same-id records into one step, counting usage
    # exactly once. Tracked via the last-created agent step.
    last_asst_id: str | None = None
    last_asst_idx: int | None = None

    for rec in records:
        rtype = rec.get("type")
        if rtype not in ("user", "assistant"):
            continue
        if rec.get("isSidechain"):
            continue  # subagents deferred to fast-follow (DEC-018): main-transcript only
        if exclude_session_id and rec.get("sessionId") == exclude_session_id:
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        ts = rec.get("timestamp")

        if rtype == "assistant":
            model = msg.get("model")
            default_model = default_model or model
            if model is not None and not pricing.is_priced(model) and model not in unpriced:
                unpriced.append(model)        # M7
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
                    tool_calls.append({
                        "tool_call_id": b.get("id", ""),
                        "function_name": b.get("name", "unknown"),
                        "arguments": b.get("input", {}) or {},
                    })
            msg_id = msg.get("id")
            usage = msg.get("usage")
            metrics = _usage_to_metrics(usage, model) if isinstance(usage, dict) else None

            if (msg_id is not None and msg_id == last_asst_id
                    and last_asst_idx == len(steps) - 1):
                # Same logical turn split across records: merge content. Usage is
                # identical across the run, so count it once.
                prev = steps[last_asst_idx]
                if text:
                    prev.message = (prev.message + ("\n" if prev.message else "") + text
                                    ) if prev.message else text
                if reasoning:
                    prev.reasoning_content = (
                        (prev.reasoning_content + "\n") if prev.reasoning_content else ""
                    ) + reasoning
                if tool_calls:
                    prev.tool_calls = (prev.tool_calls or []) + tool_calls
                    for tc in tool_calls:
                        call_to_step[tc["tool_call_id"]] = last_asst_idx
                # H6: the first record of the group lacked usage; fill from a later one.
                if prev.metrics is None and metrics is not None:
                    prev.metrics = metrics
                continue

            step = StepRecord(
                step_id=len(steps) + 1,
                timestamp=ts,
                source="agent",
                model_name=model,
                message=text,
                reasoning_content=reasoning,
                tool_calls=tool_calls,
                metrics=metrics,
            )
            idx = len(steps)
            steps.append(step)
            last_asst_id, last_asst_idx = msg_id, idx
            for tc in tool_calls:
                call_to_step[tc["tool_call_id"]] = idx
            continue

        # rtype == "user": either tool_result(s) -> fold into prior agent step,
        # or a genuine human turn -> its own user step.
        results: list[tuple[str, dict]] = []
        human_text_blocks = []
        blocks = content if isinstance(content, list) else (
            [{"type": "text", "text": content}] if isinstance(content, str) else [])
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tuid = b.get("tool_use_id", "")
                results.append((tuid, {
                    "source_call_id": tuid,
                    "content": _text_of(b.get("content")),
                    "extra": {"is_error": True} if b.get("is_error") else None,
                }))
            elif isinstance(b, dict) and b.get("type") == "text":
                human_text_blocks.append(b.get("text", ""))
            elif isinstance(b, str):
                human_text_blocks.append(b)

        for tuid, res in results:
            si = call_to_step.get(tuid)
            if si is None:
                continue  # orphan result (e.g. call excluded); drop
            steps[si].observation_results.append(res)   # M11: keep duplicates

        human_text = "\n".join(t for t in human_text_blocks if t).strip()
        if human_text:
            steps.append(StepRecord(
                step_id=len(steps) + 1,
                timestamp=ts,
                source="user",
                message=human_text,
            ))

    if not steps:
        raise EmptyTranscriptError("No user/assistant steps found in transcript.")

    final_metrics = {
        "total_prompt_tokens":     sum((s.metrics or {}).get("prompt_tokens", 0) for s in steps),
        "total_completion_tokens": sum((s.metrics or {}).get("completion_tokens", 0) for s in steps),
        "total_cached_tokens":     sum((s.metrics or {}).get("cached_tokens", 0) for s in steps),
        "total_cost_usd": round(sum((s.metrics or {}).get("cost_usd", 0.0) for s in steps), 6),
        "total_steps": len(steps),
    }
    extra = {k: v for k, v in {
        "sdlc_task_id": task_id, "sdlc_spec_id": spec_id, "sdlc_intent": intent,
        "source_client": AGENT_NAME,
        "environment": environment or None,          # set ONLY when non-empty (M4)
        "unpriced_models": unpriced or None,         # set ONLY when non-empty (M7)
    }.items() if v is not None}

    return NormalizedTrajectory(
        session_id=session_id,
        agent={"name": AGENT_NAME, "version": ADAPTER_VERSION, "model_name": default_model},
        steps=steps,
        final_metrics=final_metrics,
        extra=extra,
    )
