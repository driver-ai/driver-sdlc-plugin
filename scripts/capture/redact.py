"""Redaction pass over an ATIF trajectory (pure core + thin CLI shell).

Security control for the capture flow: transcripts can contain secrets the agent
read off disk (.env files, credential dumps). This scans every string the
trajectory carries -- step messages, reasoning, tool-call arguments, observation
results -- replaces matches with a typed placeholder, and returns flags the
approval gate renders so the developer can reject before anything uploads.

`redact_trajectory(traj) -> (redacted_traj, flags)` is a pure function: values
in, values out, no I/O. The CLI at the bottom is the shell.
"""
from __future__ import annotations

import argparse
import copy
import json
import re

# (label, compiled pattern). Order matters only for overlapping matches.
PATTERNS = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_key",        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key",     re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("github_token",      re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token",       re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key",    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token",      re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}")),
    # .env-style assignment of a secret-looking variable: KEY=value / KEY: value
    ("env_secret_assignment",
     re.compile(r"(?im)^\s*([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|API|CREDENTIAL)[A-Z0-9_]*)\s*[:=]\s*\S+")),
]


def _redact_str(s: str, counts: dict[str, int]) -> str:
    for label, pat in PATTERNS:
        def repl(m, _label=label):
            counts[_label] = counts.get(_label, 0) + 1
            # keep the variable name for env assignments; mask the value
            if _label == "env_secret_assignment":
                return f"{m.group(1)}=[REDACTED:{_label}]"
            return f"[REDACTED:{_label}]"
        s = pat.sub(repl, s)
    return s


def _walk(obj, counts: dict[str, int]):
    if isinstance(obj, str):
        return _redact_str(obj, counts)
    if isinstance(obj, list):
        return [_walk(x, counts) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, counts) for k, v in obj.items()}
    return obj


def redact_trajectory(traj: dict) -> tuple[dict, list[dict]]:
    """Return (redacted_copy, flags). flags = [{type, count}], highest first."""
    counts: dict[str, int] = {}
    redacted = _walk(copy.deepcopy(traj), counts)
    flags = [{"type": k, "count": v} for k, v in
             sorted(counts.items(), key=lambda kv: -kv[1])]
    return redacted, flags


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory")
    ap.add_argument("--out", default="trajectory.redacted.json")
    ap.add_argument("--flags-out", default="redaction_flags.json")
    args = ap.parse_args()

    traj = json.load(open(args.trajectory))
    redacted, flags = redact_trajectory(traj)
    json.dump(redacted, open(args.out, "w"), indent=2)
    json.dump(flags, open(args.flags_out, "w"), indent=2)

    total = sum(f["count"] for f in flags)
    if total:
        print(f"REDACTED {total} secret(s) across {len(flags)} pattern type(s):")
        for f in flags:
            print(f"    {f['type']}: {f['count']}")
    else:
        print("No secrets matched. No redactions.")
    print(f"    redacted trajectory -> {args.out}")


if __name__ == "__main__":
    main()
