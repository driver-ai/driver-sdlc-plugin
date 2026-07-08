"""Render an ATIF trajectory to a readable local HTML report for visual review.

Purpose: let a developer eyeball the FULL trajectory before approving upload --
every message, tool call, argument, and observation -- WITHOUT any of it flowing
through the Claude session context (which would bloat context and risk re-leaking
the very secrets being reviewed). The script writes a self-contained HTML file
and opens it in the browser; it prints only the path, never the content.

It also runs a "potential sensitive content" scan (broader than the redaction
pass: emails, IPs, JWTs, high-entropy tokens, secret-ish keywords) and surfaces
findings at the top, so the human can catch what regex redaction missed -- the
approval gate is the primary control; this is its review surface.

Pure stdlib, no opik/logs2atif needed:
    python3 render_trace.py <trajectory.json> [--out report.html] [--no-open]
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import subprocess
import sys

from cc_to_atif_core import flatten_content  # shared ContentPart-list -> text

# Broader than redact.py on purpose: this FLAGS for human eyes, it does not mask.
SCAN = [
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("OpenAI/Anthropic key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{12,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{16,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}")),
    ("Email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("IPv4 address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("Secret-ish assignment",
     re.compile(r"(?im)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)\s*[:=]\s*(\S+)")),
]


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in freq.values())


HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9+/=_-]{24,}\b")
# Common high-entropy-but-benign shapes to skip, so the scan stays actionable:
# git SHAs, sha256, UUIDs, and all-hex/all-digit blobs.
_BENIGN = [
    re.compile(r"^[0-9a-f]{7}$"), re.compile(r"^[0-9a-f]{40}$"),
    re.compile(r"^[0-9a-f]{64}$"), re.compile(r"^[0-9a-f]{32}$"),
    re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    re.compile(r"^\d+$"),
]


def _benign_blob(s: str) -> bool:
    return any(p.match(s) for p in _BENIGN)


def _walk_labeled(traj: dict):
    """Yield (trajectory_id, label_prefix, step) for the parent then every subagent.

    `subagent_trajectories` is flat (all depths), so one pass covers the whole tree.
    Subagent step_ids restart at 1 per trajectory, so the trajectory_id keeps scan's
    finding-dedup key distinct (an identical secret in parent step 1 and subagent
    step 1 must report as TWO findings) and the label distinguishes same-numbered
    steps in the HTML report. Pure: no I/O.
    """
    for step in traj.get("steps") or []:
        yield (None, "", step)
    for sub in traj.get("subagent_trajectories") or []:
        # Label from the converter-filled agent.name; extra.subagent_type keeps
        # artifacts from the previous converter rendering.
        stype = ((sub.get("agent") or {}).get("name")
                 or (sub.get("extra") or {}).get("subagent_type") or "agent")
        tid = sub.get("trajectory_id")
        for step in sub.get("steps") or []:
            yield (tid, f"subagent {stype} · ", step)


def _iter_strings(step: dict, prefix: str = ""):
    """Yield (location_label, text) for every reviewable string in a step.

    `prefix` (from _walk_labeled, e.g. 'subagent explorer · ') distinguishes
    subagent step locations so scan's dedup key and render's headers stay distinct
    across same-numbered parent/subagent steps.
    """
    sid = step.get("step_id")
    # Flatten so the scan sees text inside list-form messages too (a secret in
    # a ContentPart text block must be reviewable, not invisible).
    msg = flatten_content(step.get("message"))
    if msg:
        yield (f"{prefix}step {sid} message", msg)
    if step.get("reasoning_content"):
        yield (f"{prefix}step {sid} reasoning", step["reasoning_content"])
    for tc in step.get("tool_calls") or []:
        yield (f"{prefix}step {sid} tool:{tc.get('function_name')} args",
               json.dumps(tc.get("arguments"), ensure_ascii=False))
    for r in (step.get("observation") or {}).get("results", []):
        c = r.get("content")
        yield (f"{prefix}step {sid} observation",
               c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))


def scan(traj: dict) -> list[dict]:
    findings: list[dict] = []
    seen: set[tuple] = set()
    for tid, prefix, step in _walk_labeled(traj):
        for loc, text in _iter_strings(step, prefix):
            if not text:
                continue
            for label, pat in SCAN:
                for m in pat.finditer(text):
                    val = m.group(0)
                    key = (label, val, tid, loc)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append({"type": label, "where": loc,
                                     "snippet": _context(text, m.start(), m.end())})
            for m in HIGH_ENTROPY.finditer(text):
                val = m.group(0)
                if val.startswith("[REDACTED") or _entropy(val) < 4.0 or _benign_blob(val):
                    continue
                key = ("High-entropy string", val, tid, loc)
                if key in seen:
                    continue
                seen.add(key)
                findings.append({"type": "High-entropy string", "where": loc,
                                 "snippet": _context(text, m.start(), m.end())})
    # Surface high-signal hits first so the top of the report is actionable even
    # when low-signal heuristics (entropy/email/IP) add noise.
    rank = {"Private key block": 0, "AWS access key id": 0, "OpenAI/Anthropic key": 0,
            "GitHub token": 0, "Slack token": 0, "Google API key": 0, "JWT": 0,
            "Bearer token": 0, "Secret-ish assignment": 1,
            "Email address": 2, "IPv4 address": 2, "High-entropy string": 3}
    findings.sort(key=lambda f: rank.get(f["type"], 9))
    return findings


def _context(text: str, a: int, b: int, pad: int = 30) -> str:
    return ("…" if a - pad > 0 else "") + text[max(0, a - pad):a] + \
        "〈" + text[a:b] + "〉" + text[b:b + pad] + ("…" if b + pad < len(text) else "")


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _hl(s: str) -> str:
    """HTML-escape, then highlight [REDACTED:*] placeholders and the scan brackets."""
    out = _esc(s)
    out = re.sub(r"\[REDACTED:[a-z_]+\]", lambda m: f'<span class="red">{m.group(0)}</span>', out)
    out = out.replace("〈", '<span class="hit">').replace("〉", "</span>")
    return out


def render(traj: dict, findings: list[dict]) -> str:
    extra = traj.get("extra") or {}
    fm = traj.get("final_metrics") or {}
    agent = traj.get("agent") or {}
    rows = []
    for tid, prefix, step in _walk_labeled(traj):
        src = step.get("source")
        sid = step.get("step_id")
        cls = "agent" if src == "agent" else "user"
        head = f'{_esc(prefix)}#{sid} · {_esc(src)}'   # prefix is "" for parent steps
        parts = [f'<div class="step {cls}"><div class="shead">{head}'
                 f'{" · " + _esc(step.get("model_name")) if step.get("model_name") else ""}']
        m = step.get("metrics") or {}
        if m:
            parts.append(f'<span class="meta">{m.get("prompt_tokens",0):,} in / '
                         f'{m.get("completion_tokens",0):,} out · ${m.get("cost_usd",0)}</span>')
        parts.append("</div>")
        msg = flatten_content(step.get("message"))  # list-form messages display too
        if msg.strip():
            parts.append(f'<div class="msg">{_hl(msg)}</div>')
        if step.get("reasoning_content"):
            parts.append(f'<details><summary>reasoning</summary><pre>{_hl(step["reasoning_content"])}</pre></details>')
        for tc in step.get("tool_calls") or []:
            args = json.dumps(tc.get("arguments"), indent=2, ensure_ascii=False)
            parts.append(f'<details><summary>🔧 {_esc(tc.get("function_name"))}</summary>'
                         f'<pre>{_hl(args)}</pre></details>')
        for r in (step.get("observation") or {}).get("results", []):
            c = r.get("content")
            c = c if isinstance(c, str) else json.dumps(c, indent=2, ensure_ascii=False)
            parts.append(f'<details><summary>↩ observation ({_esc(r.get("source_call_id"))})</summary>'
                         f'<pre>{_hl(c)}</pre></details>')
        parts.append("</div>")
        rows.append("".join(parts))

    fl = "".join(
        f'<li><b>{_esc(f["type"])}</b> <span class="where">{_esc(f["where"])}</span>'
        f'<div class="snip">{_hl(f["snippet"])}</div></li>' for f in findings)
    fl_block = (f'<div class="warn"><h2>⚠ {len(findings)} potential sensitive item(s) — '
                f'review before approving</h2><ul>{fl}</ul></div>') if findings \
        else '<div class="ok"><h2>✓ Scan found no obvious sensitive content</h2>'\
             '<p>(Scan is heuristic — still skim the steps below.)</p></div>'

    return f"""<!doctype html><meta charset=utf-8><title>Trajectory review — {_esc(extra.get('sdlc_task_id'))}</title>
<style>
body{{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1a1a1a}}
header,.warn,.ok,.step{{max-width:980px;margin:14px auto;padding:14px 18px;background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
header h1{{margin:.2em 0;font-size:18px}} .kv{{color:#555}} .kv b{{color:#000}}
.warn{{border-left:5px solid #d33}} .ok{{border-left:5px solid #2a2}}
.warn ul{{margin:.4em 0;padding-left:1.1em}} .warn li{{margin:.5em 0}}
.where{{color:#888;font-size:12px}} .snip{{font-family:ui-monospace,monospace;font-size:12px;background:#faf3f3;padding:4px 8px;border-radius:5px;margin-top:3px;white-space:pre-wrap;word-break:break-all}}
.step{{border-left:5px solid #bbb}} .step.agent{{border-left-color:#3b6}} .step.user{{border-left-color:#36c}}
.shead{{font-weight:600;display:flex;justify-content:space-between;gap:10px}} .meta{{font-weight:400;color:#777;font-size:12px}}
.msg{{margin:.4em 0;white-space:pre-wrap}} details{{margin:.3em 0}} summary{{cursor:pointer;color:#36c}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f3f4f6;padding:8px 10px;border-radius:6px;font-size:12px;margin:.3em 0}}
.red{{background:#ffe3e3;color:#900;border-radius:3px;padding:0 2px;font-weight:600}}
.hit{{background:#fff1a8;border-radius:3px;padding:0 2px;font-weight:600}}
</style>
<header>
<h1>Trajectory review — {_esc(extra.get('sdlc_task_id') or 'session')}</h1>
<div class=kv>Spec <b>{_esc(extra.get('sdlc_spec_id'))}</b> · Session <b>{_esc(traj.get('session_id'))}</b> · {_esc(traj.get('schema_version'))}</div>
<div class=kv>Intent: <b>{_esc(extra.get('sdlc_intent'))}</b></div>
<div class=kv>Steps <b>{_esc(fm.get('total_steps'))}</b> · completion tokens <b>{_esc(fm.get('total_completion_tokens'))}</b> · cost <b>${_esc(fm.get('total_cost_usd'))}</b> · agent <b>{_esc(agent.get('name'))}</b></div>
<div class=kv style="color:#888;font-size:12px">Red = redacted by the pipeline · Yellow = flagged by this review scan</div>
</header>
{fl_block}
{''.join(rows)}
"""


def _build_meta(traj: dict) -> dict:
    """Pure Contract-A -> summary-meta mapping. Derives counts/tools/peak from steps[]."""
    steps = traj.get("steps", []) or []
    fm = traj.get("final_metrics", {}) or {}
    extra = traj.get("extra", {}) or {}
    tools = sorted({tc.get("function_name")
                    for s in steps for tc in (s.get("tool_calls") or [])
                    if tc.get("function_name")})
    peak_context = max(
        (((s.get("metrics") or {}).get("prompt_tokens", 0)
          + ((s.get("metrics") or {}).get("cached_tokens", 0)))
         for s in steps), default=0)               # derived downstream, not in final_metrics
    subs = traj.get("subagent_trajectories") or []  # flat (all depths) -> every subagent once
    return {
        "task_id": extra.get("sdlc_task_id"), "spec_id": extra.get("sdlc_spec_id"),
        "intent": extra.get("sdlc_intent"), "session_id": traj.get("session_id"),
        "steps": fm.get("total_steps", len(steps)),
        "agent_steps": sum(1 for s in steps if s.get("source") == "agent"),
        "user_steps": sum(1 for s in steps if s.get("source") == "user"),
        "tools": tools,
        "completion_tokens": fm.get("total_completion_tokens", 0),
        "peak_context": peak_context,
        "cost_usd": fm.get("total_cost_usd", 0.0),
        "subagents": len(subs),
        "subagent_steps": sum(len(s.get("steps") or []) for s in subs),
        "subagent_cost_usd": round(
            sum((s.get("final_metrics") or {}).get("total_cost_usd", 0.0) for s in subs), 6),
    }


def format_inline_summary(meta: dict, flags: list[dict]) -> str:
    """Egress-safe in-chat review block. Consumes ONLY metadata + flag counts --
    never step content -- so the summary cannot leak trajectory text into the
    conversation. `flags` = [{type, count}] (from redact.redact_trajectory /
    redact.py --flags-out). Tool NAMES are metadata and are surfaced; tool
    ARGUMENTS (content) are never read here.
    """
    tools = meta.get("tools") or []
    if flags:
        flag_line = "Redaction flags: " + ", ".join(
            f"{f.get('type')}×{f.get('count')}" for f in flags)
    else:
        flag_line = "Redaction flags: none (no flags raised)"
    lines = [
        f"Session {meta.get('session_id') or '(unknown)'} · "
        f"task {meta.get('task_id') or '(none)'} · spec {meta.get('spec_id') or '(none)'}",
        f"Intent: {meta.get('intent') or '(none)'}",
        f"Steps: {meta.get('steps', 0)} "
        f"(agent {meta.get('agent_steps', 0)} / user {meta.get('user_steps', 0)})",
        f"Tools: {', '.join(tools) if tools else '(none)'}",
        f"Completion tokens: {meta.get('completion_tokens', 0)} · "
        f"peak context: {meta.get('peak_context', 0)} · cost: ${meta.get('cost_usd', 0.0)}",
    ]
    # Metadata/counts ONLY -- never a subagent step or the free-text subagent_type.
    if meta.get("subagents"):
        lines.append(f"Subagents: {meta['subagents']} "
                     f"({meta.get('subagent_steps', 0)} steps · "
                     f"${meta.get('subagent_cost_usd', 0.0)})")
    lines.append(flag_line)
    return "\n".join(lines)


def _load_trajectory(path: str) -> dict:
    """Guarded load: a missing/corrupt trajectory yields a one-line message and a
    non-zero exit, never a raw traceback (which could echo file content)."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        print(f"error: could not read trajectory {path} ({e.__class__.__name__})",
              file=sys.stderr)
        raise SystemExit(1)


def _load_flags(path: str | None) -> list[dict]:
    """Guarded load of redact.py --flags-out JSON ([{type, count}]). Missing or
    malformed -> one-line stderr warning + [] (the summary still renders)."""
    if not path:
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"warning: could not read --flags-file {path} "
              f"({e.__class__.__name__}); continuing with no flags", file=sys.stderr)
        return []
    if not isinstance(data, list):
        print(f"warning: --flags-file {path} is not a JSON array; ignoring", file=sys.stderr)
        return []
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory")
    ap.add_argument("--out", default=None, help="HTML output path (default: alongside input)")
    ap.add_argument("--no-open", action="store_true", help="do not auto-open in browser")
    ap.add_argument("--summary", action="store_true",
                    help="print the egress-safe in-chat block (paths/counts only); "
                         "writes no HTML and opens no browser")
    ap.add_argument("--flags-file", default=None,
                    help="redaction flags JSON ([{type,count}]) from redact.py --flags-out")
    args = ap.parse_args()

    # --summary is exclusive: metadata + flag counts to stdout, no HTML, no browser.
    if args.summary:
        traj = _load_trajectory(args.trajectory)
        flags = _load_flags(args.flags_file)
        print(format_inline_summary(_build_meta(traj), flags))
        return

    traj = _load_trajectory(args.trajectory)
    findings = scan(traj)
    out = args.out or os.path.splitext(args.trajectory)[0] + ".review.html"
    with open(out, "w") as fh:
        fh.write(render(traj, findings))

    # IMPORTANT: print only the path + counts, never the content (keeps it out of
    # the agent's context). The human opens the file themselves.
    total_steps = (traj.get("final_metrics") or {}).get("total_steps", len(traj.get("steps", [])))
    print(f"review report written: {out}")
    print(f"  {total_steps} steps · "
          f"{len(findings)} potential sensitive item(s) flagged for visual review")
    if not args.no_open:
        opener = {"darwin": "open", "linux": "xdg-open"}.get(sys.platform, None)
        if opener:
            try:
                subprocess.run([opener, out], check=False)
                print("  opened in your default browser")
            except Exception:
                print(f"  open it manually: file://{os.path.abspath(out)}")
        else:
            print(f"  open it manually: file://{os.path.abspath(out)}")


if __name__ == "__main__":
    main()
