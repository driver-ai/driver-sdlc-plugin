"""Pure env/conditions stamp for the capture spine.

Functional core (DEC-011): values in, values out -- no I/O, time, randomness, or
shared mutable state. `build_environment` transforms the raw facts handed to it
by the shell; it reads NO files and makes NO git/MCP calls. Fact-gathering (the
`--env-file` read in `cc_to_atif.main`, and later the git/MCP collection) is the
shell's job. The result becomes the trajectory's `extra["environment"]`.
"""
from __future__ import annotations


def build_environment(*, codebase_url: str | None, cwd: str | None, branch: str | None,
                      commit_start: str | None, commit_end: str | None,
                      mcp_endpoint: str | None, mcp_version: str | None) -> dict:
    """Pure env/conditions stamp -> trajectory extra["environment"].
    Omits absent facts entirely (key not present -- NOT a null value, L2). Every fact
    is best-effort: commit_start is often unrecoverable at capture time -> when None
    its key is simply absent. Derives endpoint identity:
        mcp_env = "prod" if mcp_endpoint and "app.driverai.com" in mcp_endpoint else
                  "dev"  if mcp_endpoint else (absent)
    Returns {} when no facts are present, so the caller sets extra["environment"]
    ONLY when the result is non-empty (M4)."""
    env = {}
    for key, val in (("codebase_url", codebase_url), ("cwd", cwd), ("branch", branch),
                     ("commit_start", commit_start), ("commit_end", commit_end),
                     ("mcp_endpoint", mcp_endpoint), ("mcp_version", mcp_version)):
        if val is not None:
            env[key] = val
    if mcp_endpoint:
        env["mcp_env"] = "prod" if "app.driverai.com" in mcp_endpoint else "dev"
    return env
