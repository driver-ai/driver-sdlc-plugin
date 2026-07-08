"""Claude Code JSONL transcript -> ATIF v1.7 trajectory, via logs2atif.

Imperative shell around the logs2atif converter: the record walk (grouping,
tool_result folding, usage/cost math, subagent embedding) is upstream's job;
this module owns the I/O seams around it:

  1. tolerant read      -- corrupt / non-dict transcript lines are skipped with
     a warning, so upstream only ever sees re-serialized clean records;
  2. pre-filter (pure)  -- marker truncation, session-id exclusion, inline
     sidechain drop, list-form user-content flatten (cc_to_atif_core);
  3. staging            -- filtered records land as <tmp>/<session_id>.jsonl;
     this session's subagent files are line-cleaned into <tmp>/subagents/ with
     .meta.json sidecars copied verbatim. The session_id is guarded by
     is_safe_path_component BEFORE any path use (fallback stem: `session`);
  4. convert            -- get_adapter("claude-code").convert(...) with builtin
     pricing; logs2atif is imported ONLY here, lazily, so --help and input
     validation never need the dependency;
  5. dict enrichment (pure) -- on the serialized trajectory: capture extras
     (environment + sdlc_*), depth-agnostic subagent ref re-link, and a
     subagent-inclusive token rollup.

Token-rollup divergence, on purpose: upstream keeps the parent's
total_{prompt,completion,cached}_tokens parent-only so batch consumers can sum
root totals without double counting, while total_cost_usd is already
subtree-inclusive. Our artifacts feed single-session human displays where the
token and cost figures must reconcile, so the wrapper folds each embedded
subagent's per-step token metrics into the parent totals (cost and total_steps
untouched).

Failure contract: nothing convertible (empty transcript, everything
pre-filtered away, no valid events) -> error on stderr + exit 1.

Usage:
    python cc_to_atif.py <session.jsonl> [--task-id T] [--spec-id S]
        [--intent "..."] [--exclude-session-id SID] [--exclude-marker M]
        [--env-file env.json] [--session-dir DIR] [--out trajectory.json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import cc_to_atif_core as core
import environment


def _load(path: str) -> list[dict[str, Any]]:
    """Read JSONL records, skipping lines that are not JSON objects.

    A corrupt (non-JSON) line and a valid-JSON-but-non-dict line (a bare array,
    string, or number) are each skipped with a stderr warning rather than
    aborting the whole file: one bad line in a long transcript must not lose the
    rest of the run.
    """
    out = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"warning: skipping corrupt line {n} in {path}: {e}", file=sys.stderr)
                continue
            if not isinstance(obj, dict):
                print(f"warning: skipping non-object line {n} in {path}", file=sys.stderr)
                continue
            out.append(obj)
    return out


def _convert_via_logs2atif(filtered: list[dict], *, session_id: str,
                           subagent_src: Path | None, source_path: str) -> dict:
    """Shell: stage filtered records as <tmp>/<session_id>.jsonl; when
    subagent_src exists, stage line-cleaned copies (sanitize_jsonl_lines) of
    its agent-*.jsonl plus verbatim .meta.json sidecars under <tmp>/subagents
    and attach that as SessionSource.subagent_dir; run
    get_adapter('claude-code').convert(source, pricing=builtin_pricing(),
    opts=ConvertOptions(file_path=source_path)), and return
    trajectory.to_json_dict(). Releases `filtered` before convert. Returns {}
    when the adapter yields None (no convertible events) — main() maps that to
    exit 1. The ONLY function that imports logs2atif (from logs2atif.adapters /
    logs2atif.pricing).

    session_id doubles as the staged file stem AND SessionSource.session_id —
    upstream derives its session-id fallback from the staged session dir name
    (built from SessionSource.session_id) while the file stem qualifies each
    subagent trajectory_id, so the two must never diverge. Upstream re-derives
    the ATIF session_id from the records themselves when they carry one.
    Subagent files are only line-cleaned, never pre-filtered: they are already
    session-scoped, all-sidechain, and carry no command turns — but upstream
    aborts the whole conversion on a valid-JSON non-dict line, where dropping
    just that line preserves the rest of the run.
    """
    from logs2atif.adapters import ConvertOptions, SessionSource, get_adapter
    from logs2atif.pricing import builtin_pricing

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / f"{session_id}.jsonl"
        with open(staged, "w") as fh:
            for rec in filtered:
                fh.write(json.dumps(rec) + "\n")
        del filtered  # staged on disk; don't hold a large transcript twice

        staged_subagents = None
        if subagent_src is not None:
            paths = sorted(subagent_src.glob("agent-*.jsonl"))
            if not paths:
                print(f"warning: no subagents found under {subagent_src}",
                      file=sys.stderr)
            else:
                staged_subagents = Path(tmp) / "subagents"
                staged_subagents.mkdir()
                for jp in paths:
                    kept = core.sanitize_jsonl_lines(jp.read_text().splitlines())
                    (staged_subagents / jp.name).write_text(
                        "".join(line + "\n" for line in kept))
                    mp = jp.with_name(f"{jp.stem}.meta.json")
                    if mp.exists():
                        shutil.copyfile(mp, staged_subagents / mp.name)

        source = SessionSource(session_id, [staged], subagent_dir=staged_subagents)
        traj = get_adapter("claude-code").convert(
            source, pricing=builtin_pricing(),
            opts=ConvertOptions(file_path=source_path))
        if traj is None:
            return {}
        return traj.to_json_dict()


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
    ap.add_argument("--env-file",
                    help="JSON file of raw env facts (codebase_url, cwd, branch, "
                         "commit_start, commit_end, mcp_endpoint, mcp_version) "
                         "gathered by the caller")
    ap.add_argument("--session-dir",
                    help="project dir; capture subagents from "
                         "<dir>/<session-id>/subagents/agent-*.jsonl")
    ap.add_argument("--out", default="trajectory.json")
    args = ap.parse_args()

    # Shell: read the env-file (I/O) and build the env block via the pure core.
    # Validated BEFORE any logs2atif import, so these errors never need the dep.
    # build_environment returns {} when no facts are present; inject_capture_extra
    # sets the key only when truthy, so we pass the built dict straight through.
    env_block = None
    if args.env_file:
        try:
            with open(args.env_file) as fh:
                facts = json.load(fh)
        except FileNotFoundError:
            print(f"error: --env-file not found: {args.env_file}", file=sys.stderr)
            raise SystemExit(1)
        except json.JSONDecodeError as e:
            print(f"error: --env-file is not valid JSON: {e}", file=sys.stderr)
            raise SystemExit(1)
        # Extract only the 7 known fact keys; unknown keys are ignored.
        env_block = environment.build_environment(
            codebase_url=facts.get("codebase_url"), cwd=facts.get("cwd"),
            branch=facts.get("branch"), commit_start=facts.get("commit_start"),
            commit_end=facts.get("commit_end"), mcp_endpoint=facts.get("mcp_endpoint"),
            mcp_version=facts.get("mcp_version"),
        )

    records = _load(args.transcript)
    filtered = core.prefilter_records(records,
                                      exclude_marker=args.exclude_marker,
                                      exclude_session_id=args.exclude_session_id)
    del records

    # session_id comes from the FILTERED records (the excluded session's ids
    # must not leak in) and is guarded before ANY path use: it becomes the
    # staged file stem, and — only when safe — the subagent-dir join below.
    session_id = next((r.get("sessionId") for r in filtered if r.get("sessionId")), None)
    subagent_src = None
    if session_id is None or not core.is_safe_path_component(session_id):
        if args.session_dir:
            if session_id is None:
                print("warning: --session-dir set but no sessionId in transcript; "
                      "capturing no subagents", file=sys.stderr)
            else:
                print(f"warning: --session-dir set but sessionId {session_id!r} is "
                      "not a safe path component; capturing no subagents",
                      file=sys.stderr)
        session_id = "session"
    elif args.session_dir:
        # Session-scoped: a project dir holding many sessions never
        # contributes another session's subagents.
        subagent_src = Path(args.session_dir) / session_id / "subagents"

    d = _convert_via_logs2atif(filtered, session_id=session_id,
                               subagent_src=subagent_src,
                               source_path=str(args.transcript))
    if not d:
        print("error: no convertible events in transcript", file=sys.stderr)
        raise SystemExit(1)

    # Pure dict-level enrichment on the serialized trajectory.
    core.inject_capture_extra(d, environment=env_block, task_id=args.task_id,
                              spec_id=args.spec_id, intent=args.intent)
    core.link_nested_subagent_refs(d)
    core.rollup_subagent_tokens(d)

    with open(args.out, "w") as fh:
        json.dump(d, fh, indent=2)

    # OK summary from the enriched dict, None-safe throughout: serialization
    # drops absent metrics (usage-less transcripts, unpriced models), so token
    # totals default to 0 and a missing cost prints as n/a.
    fm = d.get("final_metrics") or {}
    tools = sorted({tc["function_name"] for s in d.get("steps") or []
                    for tc in s.get("tool_calls") or []})
    cost = fm.get("total_cost_usd")
    peak = (fm.get("extra") or {}).get("peak_context_tokens") or 0
    print(f"OK  {args.out}")
    print(f"    schema={d.get('schema_version')} session={d.get('session_id')}")
    print(f"    steps={fm.get('total_steps', 0)}  "
          f"prompt_tok={fm.get('total_prompt_tokens', 0)}  "
          f"compl_tok={fm.get('total_completion_tokens', 0)}  "
          f"cost={f'${cost}' if cost is not None else 'n/a'}")
    print(f"    peak_step_context_tokens={peak}")
    print(f"    tools_used={','.join(tools) if tools else '(none)'}")


if __name__ == "__main__":
    main()
