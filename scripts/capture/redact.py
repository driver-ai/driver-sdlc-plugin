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

# ONE masking core. PATTERNS is a true SUPERSET of BOTH the original redact.py set
# AND the viewer's scrub_secrets set -- no source pattern is narrowed (the
# load-bearing "a secret masked by one surface is masked by all" invariant).
# Ordering rule: specific patterns first; env_secret_assignment LAST (generic
# fallback) so a value already typed by a specific pattern is not re-flagged.
PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("aws_access_key_id",  re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("anthropic_key",      re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),     # BEFORE openai
    ("openai_key",         re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")), # also sk-proj-
    ("github_token",       re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),    # {30,} (viewer parity)
    ("slack_token",        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key",     re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),        # {30,} (viewer parity)
    ("gitlab_token",       re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),      # from viewer
    ("huggingface_token",  re.compile(r"\bhf_[A-Za-z0-9]{30,}")),           # from viewer
    ("twilio_account_sid", re.compile(r"\bAC[0-9a-fA-F]{32}\b")),           # from viewer
    ("twilio_api_key",     re.compile(r"\bSK[0-9a-fA-F]{32}\b")),           # from viewer
    ("private_key_block",  re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token",       re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}")),
    # .env-style secret assignment -- adopts the viewer's ENV_SECRET coverage:
    #  - mid-line (NOT ^-anchored), case-insensitive, hyphenated names (x-api-key)
    #  - requires a COMPOUND secret word (API_KEY/_TOKEN/_SECRET/PASSWORD/...), so
    #    bare API/KEY substrings (MONKEY=banana, PUBLIC_API_URL=...) don't match
    #  - value branch captures a quoted span (incl. spaces) OR a >=6-char non-space
    #    run, so the WHOLE value is masked, not just the first token
    #  - (?!\[REDACTED:) guard => a second pass adds no new flags (idempotent)
    ("env_secret_assignment", re.compile(r"""(?ix)
        ( [A-Za-z0-9_]{0,128}
          (?: API[_-]?KEY | ACCESS[_-]?KEY | SECRET[_-]?KEY | _SECRET
            | _TOKEN | ACCESS[_-]?TOKEN | PASSWORD | PASSWD | CREDENTIALS? )
          [A-Za-z0-9_]{0,128} )  # variable name (bounded -> linear scan, no O(n^2)
                                 # split search; wide enough that a long name run
                                 # before the value still masks)
        ( \s* [:=] \s* )         # 2: separator (preserved)
        (?! \[REDACTED: )        # idempotent: never re-mask an already-masked value
        (?: "[^"]*" | '[^']*' | [^\s"',}]{6,} )   # value: quoted span OR >=6 nonspace
    """)),
]

# Known limitation (L7): masking is per-string, so a secret split across two
# content blocks / two JSON string fields won't match. The heuristic flag-scan in
# render_trace (Plan 02) is the backstop for that case.


def redact_text(s: str, counts: dict[str, int] | None = None) -> tuple[str, dict[str, int]]:
    """Mask every secret pattern in `s` with a typed [REDACTED:label] token.

    Pure: returns (masked, counts). `counts` accumulates if passed (for trajectory
    walks). Idempotent: re-running on the output adds no new counts (the env guard
    plus the fact that no typed [REDACTED:label] token re-matches any pattern).
    """
    counts = counts if counts is not None else {}
    for label, pat in PATTERNS:
        def repl(m, _label=label):
            counts[_label] = counts.get(_label, 0) + 1
            if _label == "env_secret_assignment":
                return f"{m.group(1)}{m.group(2)}[REDACTED:{_label}]"  # keep name+sep, mask value
            return f"[REDACTED:{_label}]"
        s = pat.sub(repl, s)
    return s, counts


def redact_trajectory(traj: dict) -> tuple[dict, list[dict]]:
    """Return (redacted_copy, flags). flags = [{type, count}], highest count first."""
    counts: dict[str, int] = {}

    def _walk(obj):
        if isinstance(obj, str):
            return redact_text(obj, counts)[0]
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        return obj

    redacted = _walk(copy.deepcopy(traj))
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
