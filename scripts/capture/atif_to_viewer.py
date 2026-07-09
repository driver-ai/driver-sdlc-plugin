"""ATIF trajectory -> ATIF Trajectory Viewer (local React app).

Bridges a (redacted) ATIF trajectory produced by `cc_to_atif.py` (which converts
via logs2atif) into the data layout the ATIF Trajectory Viewer reads from
`public/`:

  - public/dataset.json        (one vendor / agent / task / run, no inline steps)
  - public/runs/<runId>.json   ({"steps": [...]}, lazy-loaded by the viewer)

The viewer is vendored clone-on-demand to ~/.drvr/viewer (override --viewer-dir).
First run git-clones it and `npm install`s; subsequent runs reuse the checkout.

The viewer natively understands ATIF — its own scripts/ingest.py has a
`step_from_atif`. We port the same step/mutation mapping here (rather than import
its ingest, which is wired to its own benchmark sources) so the file-stage,
mutations, and tool calls render identically.

Usage:
    python atif_to_viewer.py <trajectory.json> [--task-id T] [--spec-id S]
        [--intent "..."] [--viewer-dir DIR] [--repo URL] [--pin SHA]
        [--port 5273] [--serve|--no-serve] [--install|--no-install]

Egress note: this is a *local* viewer. It writes only to the local viewer
checkout and serves on localhost. Nothing is uploaded. Feed it the REDACTED
trajectory — the same one you'd hand to render_trace.py / atif_to_opik.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import redact  # the one shared masking core (typed [REDACTED:label] tokens)
from cc_to_atif_core import flatten_content  # shared ContentPart-list -> text

DEFAULT_REPO = "https://github.com/driver-ai/ATIF-trajectory-viewer"
# Pin so a clone-on-demand stays reproducible. Bump deliberately, always to a
# merged fork-main SHA (never a branch tip).
DEFAULT_PIN = "b51ea867855a92547d2fae8294f6c792a87b826f"
DEFAULT_VIEWER_DIR = os.path.expanduser("~/.driver/viewer")
DEFAULT_PORT = 5273  # 5173 collides with local Opik; use a dedicated port.

# --- step/mutation mapping (ported from the viewer's scripts/ingest.py) ------

STEP_FIELD_CAP = 40_000  # per-field char cap so one huge blob can't swamp the viewer
MAX_STEPS = 4000         # whole-run step cap (defensive bound on viewer payload size)

WRITE_CMD = re.compile(
    r"(>>?|\btee\b|\bcp\b|\bmv\b|\bmkdir\b|\btouch\b|sed -i|"
    r"\bgit (add|commit|checkout|push)\b|\bmake\b|npm (run|install|ci)|"
    r"pip install|\brm\b|cargo build|cargo test|pytest|\bdd\b)"
)


def _scrub(v):
    # Mask via the shared redaction core; non-str values pass through unchanged.
    # Counts are discarded here: this is defense-in-depth on an ALREADY-redacted
    # trajectory — the authoritative flags come from redact.redact_trajectory.
    return redact.redact_text(v, None)[0] if isinstance(v, str) else v


def _cap(v):
    if isinstance(v, str) and len(v) > STEP_FIELD_CAP:
        v = v[:STEP_FIELD_CAP] + f"\n…[truncated, {len(v) - STEP_FIELD_CAP} more chars]"
    # Scrub the already-capped value: the input is already redacted, so capping
    # first cannot introduce a split-secret evasion here.
    return _scrub(v)


def _parse_tool_calls(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            try:
                return json.loads(raw.replace("'", '"'))
            except Exception:
                return []
    return []


def detect_mutation(name: str, raw_args):
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except Exception:
            args = {"_raw": raw_args}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    n = (name or "").lower()
    if any(k in n for k in ("write_file", "create_file", "str_replace", "edit_file",
                            "apply_patch", "replace_file")) or n in ("write", "edit", "replace"):
        return {"kind": "file", "tool": name,
                "target": args.get("path") or args.get("filepath") or args.get("file_path"),
                "summary": "file edit",
                "detail": (args.get("content") or args.get("new_str") or args.get("new_content")
                           or args.get("new_string") or "")[:1500]}
    if "git_commit" in n or n.endswith("git_commit"):
        return {"kind": "git", "tool": name, "target": args.get("repo_path"),
                "summary": "commit: " + (args.get("message", "") or "").splitlines()[0][:80]}
    if any(k in n for k in ("git_add", "git_create_branch", "git_checkout", "git_push")):
        return {"kind": "git", "tool": name,
                "target": args.get("repo_path") or args.get("branch_name"),
                "summary": n.replace("git_", "").replace("_", " ")}
    if ("bash" in n or "shell" in n or n in ("run_command", "exec", "execute")
            or n.endswith("_command") or n == "bash_command"):
        cmd = args.get("command") or args.get("cmd") or args.get("_raw") or ""
        if cmd and WRITE_CMD.search(str(cmd)):
            return {"kind": "command", "tool": name, "target": None,
                    "summary": str(cmd).strip()[:200]}
    return None


_META_ALLOW_TOP = ("llm_call_count",)       # step-top-level metadata keys
_META_ALLOW_EXTRA = ("service_tier",)       # keys under metrics.extra (NOT step-top-level)


def _span_kind_for(role: str) -> str:
    # role -> viewer spanKind enum {llm, tool, general, system} (capture-viewer DEC-016).
    return {"tool": "tool", "agent": "llm", "system": "system"}.get(role, "general")


def curate_metadata(s: dict) -> dict | None:
    """Pure: allow-listed, scrubbed per-step metadata for the Details tab. Never
    passes raw `extra` through -- only enumerated safe keys, each read from its REAL
    home (llm_call_count is step-top-level; service_tier + the cache breakdown live
    under metrics.extra -- capture-viewer DEC-071 lineage)."""
    md: dict = {}
    for k in _META_ALLOW_TOP:
        v = s.get(k)
        if v is not None:
            md[k] = _scrub(v) if isinstance(v, str) else v
    metrics = s.get("metrics") or {}
    extra = metrics.get("extra") or {}
    for k in _META_ALLOW_EXTRA:
        v = extra.get(k)
        if v is not None:
            md[k] = _scrub(v) if isinstance(v, str) else v
    # cache_read_input_tokens == metrics.cached_tokens (== tokens.cached) on CC captures
    # (corpus-proven 2038/2038 equal) -- keep only cache_creation here so the same count
    # is not duplicated under two names (capture-viewer DEC-022, dry-run round-2 #13).
    cache = {k: extra[k] for k in ("cache_creation_input_tokens",)
             if extra.get(k) is not None}
    if cache:
        md["cache"] = cache                 # read-cache lives only in tokens.cached (no dup)
    return md or None


def step_from_atif(s: dict, idx: int) -> dict:
    role = {"user": "user", "agent": "agent", "assistant": "agent",
            "tool": "tool", "system": "system"}.get((s.get("source") or "agent").lower(), "agent")
    raw_tcs = _parse_tool_calls(s.get("tool_calls"))
    tcs, muts = [], []
    for tc in raw_tcs:
        if not isinstance(tc, dict):
            continue
        name = (tc.get("function_name") or (tc.get("function") or {}).get("name")
                or tc.get("name") or "tool")
        args = tc.get("arguments")
        if args is None and tc.get("function"):
            args = tc["function"].get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False) if args is not None else None
        m = detect_mutation(name, args)
        if m:
            for k in ("detail", "summary", "target"):
                if m.get(k):
                    m[k] = _scrub(m[k])   # second scrub site (mutation fields)
            muts.append(m)
        tcs.append({"name": name, "args": _cap(args)})
    obs = s.get("observation")
    if isinstance(obs, dict):
        results = obs.get("results")
        if isinstance(results, list):
            # Flatten each result's content (str passthrough; ContentPart lists
            # -> display text) BEFORE the _cap/_scrub below sees it.
            obs = "\n\n".join(
                flatten_content(r.get("content")) if "content" in r else str(r)
                for r in results)
        else:
            obs = json.dumps(obs, ensure_ascii=False)
    elif isinstance(obs, list):
        obs = "\n\n".join(str(x) for x in obs)
    metrics = s.get("metrics") or {}
    out = {
        "index": idx, "role": role,
        # Flatten BEFORE _cap/_scrub so the defense-in-depth re-scrub always
        # sees a string (a list message would otherwise pass through unmasked).
        "text": _cap(flatten_content(s.get("message"))) if role != "tool" else None,
        "reasoning": _cap(s.get("reasoning_content")),
        "toolCalls": tcs or None,
        "observation": _cap(obs) if (role == "tool" or obs) else None,
        "toolName": None,
        "tokens": {"prompt": metrics.get("prompt_tokens"),
                   "completion": metrics.get("completion_tokens")} if metrics else None,
        "timestamp": s.get("timestamp"),
        "mutations": muts or None,
        "edits": None,
    }
    # payload v2: additive identity/hierarchy/model/metadata stamping. The private
    # _depth/_parentIndex/_trajId/_spanKind keys baked in by flatten_with_subagents
    # are consumed here and NOT re-emitted (capture-viewer DEC-016 / DEC-022).
    out.update({
        "stepId": s.get("step_id"),
        "trajId": s.get("_trajId"),
        "depth": s.get("_depth", 0),
        "parentIndex": s.get("_parentIndex"),
        "spanKind": s.get("_spanKind") or _span_kind_for(role),
        "model": _scrub(s.get("model_name")) if s.get("model_name") else None,
        "metadata": curate_metadata(s),
    })
    if out.get("tokens") is not None:
        out["tokens"]["cached"] = (s.get("metrics") or {}).get("cached_tokens")
    return out


def flatten_with_subagents(traj: dict) -> list[dict]:
    """Pure: parent + spliced subagent steps as ONE flat list of SHALLOW COPIES,
    each stamped with hierarchy (_depth/_parentIndex/_trajId/_spanKind). A single
    shared accumulator `out` -> _parentIndex is the GLOBAL index in this pre-cap
    list (never a per-recursion local index). A parent is always emitted before its
    children, so after raw_steps[:MAX_STEPS] a kept child's _parentIndex still
    references a kept step, and the trailing-boundary pop removes only trailing
    markers. Input trajectory is NOT mutated. (capture-viewer DEC-016)"""
    subs = traj.get("subagent_trajectories") or []
    by_id = {s.get("trajectory_id"): s for s in subs}
    placed: set = set()
    out: list[dict] = []
    root_tid = traj.get("session_id") or "root"  # root steps join the graph root node
                                                 # (same fallback as build_agent_graph -- DEC-022)

    def emit(step, *, depth, parent_index, traj_id, span_kind=None) -> int:
        idx = len(out)                           # GLOBAL position in the flat list
        s = dict(step)                           # shallow copy -> input never mutated
        s["_depth"], s["_parentIndex"], s["_trajId"] = depth, parent_index, traj_id
        if span_kind is not None:
            s["_spanKind"] = span_kind
        out.append(s)
        return idx

    def marker(sub, level, note=""):
        # `level` is the logical subagent NESTING level (1, 2, 3 ...), NOT the tree
        # `_depth` (which grows by 2 per level for indentation). The human-readable
        # label shows the nesting level so a 2nd-level subagent reads "(depth 2)",
        # not "(depth 3)" -- capture-viewer DEC-022.
        stype = ((sub.get("agent") or {}).get("name")
                 or (sub.get("extra") or {}).get("subagent_type") or "agent")
        return {"source": "system", "step_id": None, "_boundary": True,
                "message": f"↳ subagent {stype} (depth {level}{note})"}

    def walk(steps, depth, parent_index, traj_id, level):
        for step in steps:
            i = emit(step, depth=depth, parent_index=parent_index, traj_id=traj_id)
            results = (step.get("observation") or {}).get("results", [])
            res_by_call: dict = {}
            for r in results:
                res_by_call.setdefault(r.get("source_call_id"), r)
            for tc in step.get("tool_calls") or []:
                r = res_by_call.get(tc.get("tool_call_id"))
                for ref in (r.get("subagent_trajectory_ref") if r else None) or []:
                    tid = ref.get("trajectory_id")
                    sub = by_id.get(tid)
                    if not sub or tid in placed:
                        continue
                    placed.add(tid)
                    m = emit(marker(sub, level + 1), depth=depth + 1,   # label by nesting level
                             parent_index=i, traj_id=tid, span_kind="system")
                    walk(sub.get("steps") or [], depth + 2, m, tid, level + 1)

    walk(traj.get("steps") or [], 0, None, root_tid, 0)
    for sub in subs:                             # subagents never reached via a ref
        tid = sub.get("trajectory_id")
        if tid in placed:
            continue
        placed.add(tid)
        m = emit(marker(sub, 1, ", unlinked"), depth=1, parent_index=None,
                 traj_id=tid, span_kind="system")
        walk(sub.get("steps") or [], 2, m, tid, 1)
    return out


def run_artifacts(steps: list) -> list:
    seen = []
    for s in steps:
        for m in (s.get("mutations") or []):
            t = m.get("target")
            if t and t not in seen:
                seen.append(t)
    return seen[:30]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "x"


def _duration_sec(steps: list):
    ts = [s.get("timestamp") for s in steps if s.get("timestamp")]
    if len(ts) < 2:
        return None
    try:
        a = datetime.fromisoformat(ts[0].replace("Z", "+00:00"))
        b = datetime.fromisoformat(ts[-1].replace("Z", "+00:00"))
        return max(0, int((b - a).total_seconds()))
    except Exception:
        return None


# --- viewer checkout management ---------------------------------------------

def ensure_viewer(viewer_dir: str, repo: str, pin: str, do_install: bool) -> None:
    if not os.path.isdir(os.path.join(viewer_dir, ".git")):
        os.makedirs(os.path.dirname(viewer_dir), exist_ok=True)
        print(f"Cloning viewer -> {viewer_dir}")
        subprocess.run(["git", "clone", repo, viewer_dir], check=True)
    if pin and pin != "main":
        subprocess.run(["git", "-C", viewer_dir, "fetch", "--depth", "1", "origin", pin], check=True)
        subprocess.run(["git", "-C", viewer_dir, "checkout", pin], check=True)
    if do_install and not os.path.isdir(os.path.join(viewer_dir, "node_modules")):
        print("Installing viewer deps (npm install) — first run only…")
        subprocess.run(["npm", "install"], cwd=viewer_dir, check=True)


def build_dataset(traj: dict, *, task_id: str, spec_id: str, intent: str, generated_at: str):
    """generated_at injected by the shell (no datetime.now() in the core)."""
    extra = traj.get("extra") or {}
    task_id = task_id or extra.get("sdlc_task_id") or "session"
    spec_id = spec_id or extra.get("sdlc_spec_id") or "drvr"
    intent = intent or extra.get("sdlc_intent") or ""
    session_id = traj.get("session_id") or "session"
    agent_meta = traj.get("agent") or {}
    model = agent_meta.get("model_name")

    raw_steps = flatten_with_subagents(traj)
    if len(raw_steps) > MAX_STEPS:
        print(f"note: {len(raw_steps) - MAX_STEPS} step(s) beyond MAX_STEPS={MAX_STEPS} "
              f"dropped from the viewer payload", file=sys.stderr)
    capped = raw_steps[:MAX_STEPS]
    while capped and capped[-1].get("_boundary"):      # don't end on a dangling subagent marker
        capped.pop()
    steps = [step_from_atif(s, i) for i, s in enumerate(capped)]

    vid = "drvr"
    aid = slug(f"claude-code-{model or 'model'}-{vid}")
    tid = slug(f"{spec_id}-{task_id}")
    rid = slug(f"{session_id}-{task_id}")

    fm = traj.get("final_metrics") or {}
    tokens = {
        "prompt": fm.get("total_prompt_tokens"),
        "completion": fm.get("total_completion_tokens"),
        "cached": fm.get("total_cached_tokens"),
        "costUsd": fm.get("total_cost_usd"),
    }
    turns = sum(1 for s in steps if s["role"] == "agent")

    run = {
        "id": rid, "taskId": tid, "agentId": aid, "vendorId": vid, "format": "atif",
        "status": "completed", "passed": False, "reward": None,
        "steps": [],  # externalized
        "stepCount": len(steps),
        "multiUser": sum(1 for s in steps if s["role"] == "user") > 1,
        "artifacts": run_artifacts(steps),
        "turns": turns,
        "durationSec": _duration_sec(steps),
        "tokens": tokens,
        "grade": None,
        "failureReason": None,
    }
    dataset = {
        "generatedAt": generated_at,
        "vendors": [{"id": vid, "name": "drvr sessions",
                     "coverage": "Claude Code SDLC sessions captured locally"}],
        "agents": [{"id": aid, "harness": "Claude Code", "model": model,
                    "family": "Anthropic", "vendorId": vid}],
        "tasks": [{"id": tid, "vendorId": vid, "title": task_id, "source": "atif",
                   "category": spec_id, "difficulty": "n/a",
                   "instruction": intent, "files": [],
                   "metadata": {"spec_id": spec_id, "task_id": task_id,
                                "session_id": session_id}}],
        "runs": [run],
        "showcase": [{"vendorId": vid, "taskId": tid, "runId": rid,
                      "taskTitle": task_id, "passed": None, "reward": None,
                      "stepCount": len(steps), "source": "atif",
                      "why": intent or "Captured Claude Code session"}],
    }
    return dataset, rid, tid, steps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory")
    ap.add_argument("--task-id", default="")
    ap.add_argument("--spec-id", default="")
    ap.add_argument("--intent", default="")
    ap.add_argument("--viewer-dir", default=DEFAULT_VIEWER_DIR)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--pin", default=DEFAULT_PIN)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--serve", dest="serve", action="store_true", default=True)
    ap.add_argument("--no-serve", dest="serve", action="store_false")
    ap.add_argument("--install", dest="install", action="store_true", default=True)
    ap.add_argument("--no-install", dest="install", action="store_false")
    args = ap.parse_args()

    with open(args.trajectory) as fh:
        traj = json.load(fh)

    ensure_viewer(args.viewer_dir, args.repo, args.pin, args.install)

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dataset, rid, tid, steps = build_dataset(
        traj, task_id=args.task_id, spec_id=args.spec_id, intent=args.intent,
        generated_at=generated_at)

    public = os.path.join(args.viewer_dir, "public")
    runs_dir = os.path.join(public, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    with open(os.path.join(public, "dataset.json"), "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False)
    with open(os.path.join(runs_dir, f"{rid}.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": steps}, f, ensure_ascii=False)

    url = f"http://localhost:{args.port}/tasks/{tid}/runs/{rid}"
    print(f"OK  wrote dataset.json + runs/{rid}.json ({len(steps)} steps) to {public}")
    print(f"    deep link: {url}")

    if args.serve:
        print(f"\nStarting viewer on :{args.port}  (Ctrl-C to stop)…")
        try:
            subprocess.run(["npm", "run", "dev", "--", "--port", str(args.port)],
                           cwd=args.viewer_dir, check=True)
        except KeyboardInterrupt:
            print("\nviewer stopped.")
    else:
        print(f"\nTo view:  cd {args.viewer_dir} && npm run dev -- --port {args.port}")
        print(f"Then open: {url}")


if __name__ == "__main__":
    main()
