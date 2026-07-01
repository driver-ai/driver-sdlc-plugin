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
from urllib.parse import urlsplit

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


def is_local_opik(url: str | None) -> bool:
    """Pure: True when the resolved Opik base URL targets localhost. A non-local
    auth-less OSS Opik would expose the redacted (incl. subagent) trajectory, so
    main() warns when this is False. Fails SAFE: an empty or unparseable host is
    treated as NON-local (warn), never silently trusted. None == unset == local
    default."""
    if not url:
        return True
    if "://" in url:
        netloc = url
    elif ":" in url and url.count(":") > 1 and "[" not in url:
        netloc = f"//[{url}]"                           # bare IPv6 literal (e.g. ::1) needs brackets
    else:
        netloc = f"//{url}"                             # bare host or host:port
    host = urlsplit(netloc).hostname
    if not host:
        return False                                   # unparseable/empty -> warn
    return host in ("localhost", "127.0.0.1", "::1")


def _opik_host_port(url: str | None) -> tuple[str, int] | None:
    """Pure: (host, port) to probe for reachability, or None when the URL has no
    parseable host. The port defaults by scheme when the URL omits it. main()
    probes this before uploading because the SDK's batching thread swallows a
    connection failure (it just logs 'retried later' and flush() returns), so an
    unreachable server would otherwise look like a successful upload."""
    if not url:
        return None
    parts = urlsplit(url if "://" in url else f"//{url}")
    host = parts.hostname
    if not host:
        return None
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None                                    # malformed port
    return (host, port)


def plan_spans(traj: dict, trace_id: str) -> list[dict]:
    """Pure: trajectory -> ordered client.span(**kw) dicts (caller adds trace_id).
    One span per step, a child per tool_call, and recursively each subagent's steps
    parented under the spawning tool_call's span, in tool_calls order.
    subagent_trajectories is flat (all depths) -> one lookup map serves every level.
    No opik, no I/O. Deterministic ids: top-level suffixes are unchanged from the
    prior register() (existing spans upsert in place); subagent suffixes are qualified
    by trajectory_id. Each subagent is emitted at most once; any subagent never reached
    via a ref (truncation-unlinked or dangling) is appended under the trace root so
    Opik never silently omits one."""
    subs = traj.get("subagent_trajectories") or []
    by_id = {s.get("trajectory_id"): s for s in subs}
    placed: set = set()
    spans: list[dict] = []

    def emit(steps: list[dict], *, prefix: str, step_parent: str | None) -> None:
        for step in steps:
            sid = step.get("step_id")
            src = step.get("source")
            ts = step.get("timestamp")
            sdt = _dt(ts)
            metrics = step.get("metrics") or {}
            usage = ({"prompt_tokens": metrics.get("prompt_tokens"),
                      "completion_tokens": metrics.get("completion_tokens"),
                      "total_tokens": (metrics.get("prompt_tokens") or 0)
                      + (metrics.get("completion_tokens") or 0)} if metrics else None)
            step_span_id = _span_id(trace_id, f"{prefix}step{sid}")
            step_kw = {"id": step_span_id, "name": f"step {sid} ({src})",
                       "type": "llm" if src == "agent" else "general",
                       "input": {"message": _truncate(str(step.get("message", "")))},
                       "output": {"reasoning": _truncate(str(step.get("reasoning_content") or ""))}
                       if step.get("reasoning_content") else None,
                       "metadata": {"source": src, "timestamp": ts},
                       "model": step.get("model_name"), "usage": usage,
                       "total_cost": metrics.get("cost_usd"),
                       "start_time": sdt, "end_time": sdt}
            if step_parent is not None:
                step_kw["parent_span_id"] = step_parent
            spans.append(step_kw)

            results = (step.get("observation") or {}).get("results", [])
            obs_by_call = {r.get("source_call_id"): r.get("content") for r in results}
            res_by_call: dict = {}
            for r in results:
                res_by_call.setdefault(r.get("source_call_id"), r)
            for tc in step.get("tool_calls") or []:
                cid = tc.get("tool_call_id")
                tool_span_id = _span_id(trace_id, f"{prefix}step{sid}:tool:{cid}")
                spans.append({"id": tool_span_id, "parent_span_id": step_span_id,
                              "name": f"tool: {tc.get('function_name')}", "type": "tool",
                              "input": {"arguments": tc.get("arguments")},
                              "output": {"result": _truncate(str(obs_by_call.get(cid, "")))},
                              "metadata": {"tool_call_id": cid},
                              "start_time": sdt, "end_time": sdt})
                r = res_by_call.get(cid)               # placement via tool_calls -> first matching result
                for ref in (r.get("subagent_trajectory_ref") if r else None) or []:
                    tid = ref.get("trajectory_id")
                    sub = by_id.get(tid)
                    if sub and tid not in placed:
                        placed.add(tid)
                        emit(sub.get("steps") or [], prefix=f"{tid}:", step_parent=tool_span_id)

    emit(traj.get("steps") or [], prefix="", step_parent=None)
    for sub in subs:                                   # subagents not reached via a ref -> under root
        tid = sub.get("trajectory_id")
        if tid not in placed:                          # surface every subagent (matches the viewer flatten)
            placed.add(tid)
            emit(sub.get("steps") or [], prefix=f"{tid}:", step_parent=None)
    return spans


def plan_trace(traj: dict, trace_id: str) -> dict:
    """Pure: trajectory -> client.trace(**kw) kwargs. Mirrors plan_spans so the
    trace metadata (incl. the arc group key) is unit-testable without opik. No opik,
    no I/O. register() passes the result straight to client.trace().

    sdlc_group_key = group_key_for(task, spec, branch): task/spec when the manual flush
    supplies them, branch as the fallback so a no-task capture groups under the same
    branch:<x> the local index uses, never 'ungrouped'. The env block lives at
    extra["environment"] (the converter nests it there), NOT at the top level."""
    import capture_store_core  # sibling on sys.path (same dir; tests path-insert it)
    extra = traj.get("extra") or {}
    env = extra.get("environment") or {}   # converter nests environment under extra
    session_id = traj.get("session_id") or "unknown-session"
    task_id = extra.get("sdlc_task_id") or "no-task"
    fm = traj.get("final_metrics") or {}
    agent = traj.get("agent") or {}
    steps = traj.get("steps", [])
    start_ts = next((s.get("timestamp") for s in steps if s.get("timestamp")), None)
    end_ts = next((s.get("timestamp") for s in reversed(steps) if s.get("timestamp")), None)
    group_key = capture_store_core.group_key_for(
        task_id if task_id != "no-task" else None, extra.get("sdlc_spec_id"),
        env.get("branch"))
    return {
        "id": trace_id,
        "name": f"{agent.get('name','agent')} :: {task_id}",
        "input": {"intent": extra.get("sdlc_intent"), "session_id": session_id},
        "output": {"total_steps": fm.get("total_steps"),
                   "total_cost_usd": fm.get("total_cost_usd")},
        "metadata": {"schema_version": traj.get("schema_version"), "agent": agent,
                     "sdlc_task_id": task_id, "sdlc_spec_id": extra.get("sdlc_spec_id"),
                     "sdlc_group_key": group_key, "final_metrics": fm},
        "start_time": _dt(start_ts), "end_time": _dt(end_ts),
    }


def register(traj: dict, *, project: str) -> tuple[str, bool]:
    import opik  # lazy: keep module importable (and pure helpers testable) without opik
    extra = traj.get("extra") or {}
    session_id = traj.get("session_id") or "unknown-session"
    task_id = extra.get("sdlc_task_id") or "no-task"
    trace_id, reused = trace_id_for(trace_key(session_id, task_id))

    client = opik.Opik(project_name=project)
    # Single complete message (start+end together), no separate .end() update --
    # same create-drop race as spans otherwise nulls name/metadata. The complete
    # trace payload (incl. the arc group key) is planned purely in plan_trace.
    client.trace(**plan_trace(traj, trace_id))

    # Log each span as ONE complete message (start_time + end_time together) via
    # the low-level client.span(). The trace.span()+span.end() pattern races the
    # create against the update under batching and drops the create payload
    # (name/type/usage vanish) -- the warning Opik prints is load-bearing. The
    # per-step/per-tool/per-subagent span layout is planned purely in plan_spans;
    # this loop is the thin I/O edge that writes each planned span.
    for kw in plan_spans(traj, trace_id):
        client.span(trace_id=trace_id, **kw)

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

    if not is_local_opik(os.environ.get("OPIK_URL_OVERRIDE")):
        print("warning: uploading to a non-local Opik. Self-hosted Opik has no auth; "
              "the redacted trajectory (including subagents) is exposed to whoever can "
              "reach that host.", file=sys.stderr)

    traj = json.load(open(args.trajectory))

    # Probe reachability before uploading: the Opik SDK batches spans on a
    # background thread that catches a connection failure, logs it, and returns
    # from flush() without raising -- so an unreachable server otherwise exits 0
    # as if the upload succeeded. A pre-flight connect surfaces it deterministically.
    target = _opik_host_port(os.environ.get("OPIK_URL_OVERRIDE"))
    if target is not None:
        try:
            socket.create_connection(target, timeout=2).close()
        except OSError as e:
            print(f"Opik upload failed (unreachable: {e.__class__.__name__}): {e}",
                  file=sys.stderr)
            print(f"  Local redacted trajectory is intact: {args.trajectory}",
                  file=sys.stderr)
            print("  Nothing was uploaded. Re-run capture when Opik is reachable.",
                  file=sys.stderr)
            raise SystemExit(1)

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
