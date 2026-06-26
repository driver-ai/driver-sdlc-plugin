"""Register an ATIF trajectory.json as an Opik trace with nested spans.

Replicates the documented Opik<-Harbor mapping:
  trajectory          -> one trace
  each step           -> one nested span (llm span for agent steps, general otherwise)
  tool_calls          -> child "tool" spans under their step span
  observations        -> attached to the tool span output (keyed by source_call_id)
  step metrics        -> span usage + cost; final_metrics -> trace metadata

Idempotency (R7): the trace id is a deterministic UUIDv7-shaped value derived
from session_id + task_id, so re-capturing upserts the same trace.

Local Opik needs no API key. Configure via env before running:
  export OPIK_URL_OVERRIDE=http://localhost:5173/api
  export OPIK_WORKSPACE=default
or pass --base-url; this script sets sane local defaults if unset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket  # R9: socket.gaierror is a connection-class error to catch in main
import sys     # R9: warnings/errors go to stderr
import time
from datetime import datetime

# Default to local self-hosted Opik unless the caller already configured it.
# Dep-free (just env defaults) so the module imports without opik installed.
os.environ.setdefault("OPIK_URL_OVERRIDE", "http://localhost:5173/api")
os.environ.setdefault("OPIK_WORKSPACE", "default")

# NOTE: `import opik` is deliberately NOT at module top — it's lazy inside
# register() so this module (and its pure helpers) import with opik absent.


# Per-developer ledger in a stable home-cache dir (not the cwd, so it never
# pollutes the project being captured). Overridable for tests via DRVR_LEDGER.
LEDGER = os.environ.get(
    "DRVR_LEDGER", os.path.expanduser("~/.driver/capture/ledger.json"))


def trace_key(session_id: str | None, task_id: str | None) -> str:
    """Pure idempotency key for the ledger / trace id derivation."""
    return f"{session_id or 'unknown-session'}::{task_id or 'no-task'}"


def _mint_uuid7(key: str, ms: int) -> str:
    """A valid UUIDv7: 48-bit `ms` timestamp + deterministic random bits from key.

    Opik enforces that the embedded timestamp is within 24h of now, so the
    timestamp must be ~now; the remaining bits are hash-derived for stability.
    """
    h = hashlib.sha256(key.encode()).digest()
    b = bytearray(ms.to_bytes(6, "big") + h[:10])
    b[6] = (b[6] & 0x0F) | 0x70          # version 7
    b[8] = (b[8] & 0x3F) | 0x80          # variant RFC4122
    hx = b.hex()
    return f"{hx[0:8]}-{hx[8:12]}-{hx[12:16]}-{hx[16:20]}-{hx[20:32]}"


def trace_id_for(key: str) -> tuple[str, bool]:
    """Return (trace_id, reused). Idempotency ledger: reuse the id for a key so
    re-capture upserts the same Opik trace instead of duplicating (R7). The
    ledger also serves as the local capture-outcome record (observability NFR).

    A missing OR corrupt ledger is treated as empty (warn, don't crash) — a
    truncated/garbled file must never abort a capture. Writes are atomic
    (temp file in the same dir + os.replace) so a crash mid-write can't corrupt
    it."""
    ledger = {}
    if os.path.exists(LEDGER):
        try:
            with open(LEDGER) as f:
                ledger = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"Warning: ledger unreadable ({e.__class__.__name__}); "
                  f"treating as empty: {LEDGER}", file=sys.stderr)
            ledger = {}
    if key in ledger:
        return ledger[key]["trace_id"], True
    tid = _mint_uuid7(key, int(time.time() * 1000))
    ledger[key] = {"trace_id": tid, "key": key}
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    tmp = LEDGER + f".tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(ledger, f, indent=2)
    os.replace(tmp, LEDGER)  # atomic swap into place
    return tid, False


def _truncate(s: str, n: int = 8000) -> str:
    return s if len(s) <= n else s[:n] + f"\n…[truncated {len(s)-n} chars]"


def _dt(ts: str | None):
    """Parse an ISO-8601 timestamp to a tz-aware datetime. The Opik SDK expects
    datetime objects, NOT strings -- passing a string silently drops the whole
    create payload (name/metadata/usage all vanish)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _span_id(trace_id: str, suffix: str) -> str:
    """Deterministic span id so re-capture UPSERTS spans instead of duplicating
    them (trace-id idempotency alone leaves child spans doubling each run).
    Reuses the trace's own embedded ms (first 48 bits of the trace id) so the
    span id is stable across runs AND stays inside Opik's 24h ingest window."""
    trace_ms = int(trace_id.replace("-", "")[:12], 16)
    return _mint_uuid7(f"{trace_id}::{suffix}", trace_ms)


def register(traj: dict, *, project: str) -> tuple[str, bool]:
    import opik  # lazy: keep module importable (and pure helpers testable) without opik
    extra = traj.get("extra") or {}
    session_id = traj.get("session_id") or "unknown-session"
    task_id = extra.get("sdlc_task_id") or "no-task"
    trace_id, reused = trace_id_for(trace_key(session_id, task_id))

    steps = traj.get("steps", [])
    fm = traj.get("final_metrics") or {}
    agent = traj.get("agent") or {}
    start_ts = next((s.get("timestamp") for s in steps if s.get("timestamp")), None)
    end_ts = next((s.get("timestamp") for s in reversed(steps) if s.get("timestamp")), None)

    client = opik.Opik(project_name=project)
    # Single complete message (start+end together), no separate .end() update --
    # same create-drop race as spans otherwise nulls name/metadata.
    client.trace(
        id=trace_id,
        name=f"{agent.get('name','agent')} :: {task_id}",
        input={"intent": extra.get("sdlc_intent"), "session_id": session_id},
        output={"total_steps": fm.get("total_steps"),
                "total_cost_usd": fm.get("total_cost_usd")},
        metadata={
            "schema_version": traj.get("schema_version"),
            "agent": agent,
            "sdlc_task_id": task_id,
            "sdlc_spec_id": extra.get("sdlc_spec_id"),
            "final_metrics": fm,
        },
        start_time=_dt(start_ts),
        end_time=_dt(end_ts),
    )

    # Log each span as ONE complete message (start_time + end_time together) via
    # the low-level client.span(). The trace.span()+span.end() pattern races the
    # create against the update under batching and drops the create payload
    # (name/type/usage vanish) -- the warning Opik prints is load-bearing.
    for step in steps:
        src = step.get("source")
        sid = step.get("step_id")
        sdt = _dt(step.get("timestamp"))
        metrics = step.get("metrics") or {}
        usage = None
        if metrics:
            usage = {
                "prompt_tokens": metrics.get("prompt_tokens"),
                "completion_tokens": metrics.get("completion_tokens"),
                "total_tokens": (metrics.get("prompt_tokens") or 0)
                + (metrics.get("completion_tokens") or 0),
            }
        step_span_id = _span_id(trace_id, f"step{sid}")
        client.span(
            trace_id=trace_id,
            id=step_span_id,
            name=f"step {sid} ({src})",
            type="llm" if src == "agent" else "general",
            input={"message": _truncate(str(step.get("message", "")))},
            output={"reasoning": _truncate(str(step.get("reasoning_content") or ""))}
            if step.get("reasoning_content") else None,
            metadata={"source": src, "timestamp": step.get("timestamp")},
            model=step.get("model_name"),
            usage=usage,
            total_cost=metrics.get("cost_usd"),
            start_time=sdt,
            end_time=sdt,
        )
        # observations keyed by tool_call_id for pairing
        obs_by_call = {}
        for r in (step.get("observation") or {}).get("results", []):
            obs_by_call[r.get("source_call_id")] = r.get("content")
        for tc in step.get("tool_calls") or []:
            cid = tc.get("tool_call_id")
            client.span(
                trace_id=trace_id,
                parent_span_id=step_span_id,
                id=_span_id(trace_id, f"step{sid}:tool:{cid}"),
                name=f"tool: {tc.get('function_name')}",
                type="tool",
                input={"arguments": tc.get("arguments")},
                output={"result": _truncate(str(obs_by_call.get(cid, "")))},
                metadata={"tool_call_id": cid},
                start_time=sdt,
                end_time=sdt,
            )

    client.flush()
    return trace_id, reused


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory", nargs="?", default="trajectory.json")
    ap.add_argument("--project", default="drvr-sessions")
    ap.add_argument("--base-url", help="override OPIK_URL_OVERRIDE")
    args = ap.parse_args()
    if args.base_url:
        os.environ["OPIK_URL_OVERRIDE"] = args.base_url

    traj = json.load(open(args.trajectory))
    try:
        trace_id, reused = register(traj, project=args.project)
    except (ConnectionError, TimeoutError, socket.gaierror, OSError) as e:
        # Opik server can't be reached — the local artifact is untouched and a
        # later re-run will succeed. Distinct, retry-able message.
        print(f"Opik upload failed (unreachable: {e.__class__.__name__}): {e}",
              file=sys.stderr)
        print(f"  Local redacted trajectory is intact: {args.trajectory}",
              file=sys.stderr)
        print("  Nothing was uploaded. Re-run capture when Opik is reachable.",
              file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:
        # Auth / bad project / SDK-version mismatch — NOT a connectivity problem,
        # so don't tell the user to "re-run" (a blind retry won't fix it). The
        # artifact is still intact; we don't queue a retry.
        print(f"Opik upload failed ({e.__class__.__name__}): {e}", file=sys.stderr)
        print(f"  Local redacted trajectory is intact: {args.trajectory}; "
              f"not retried.", file=sys.stderr)
        raise SystemExit(1)
    base = os.environ["OPIK_URL_OVERRIDE"].replace("/api", "")
    print(f"OK  {'UPSERTED (reused id)' if reused else 'registered new'} trace {trace_id}")
    print(f"    project={args.project}")
    print(f"    view: {base}  (Projects -> {args.project})")


if __name__ == "__main__":
    main()
