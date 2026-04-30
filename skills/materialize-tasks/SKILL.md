---
name: materialize-tasks
description: |
  Materialize approved plan tasks into standalone task documents for sub-agent execution.
  Each task doc embeds everything a sub-agent needs: codebase root, absolute paths, standards,
  and explicit instructions. Use after plan approval and dry-run validation.
  Trigger phrases: "materialize tasks", "materialize tasks for plan X", "re-materialize",
  "create task docs".
---

# Materialize Tasks

After plan approval and dry-run gap verification, materialize each task as a standalone document. Task docs embed everything a sub-agent needs for atomic, self-contained execution — codebase root, absolute paths, standards, and explicit instructions. The task doc IS the sub-agent's execution contract.

**When to run:** After the plan has been approved (planning-guidance Step 7) and all dry-run iterations are complete.

---

## How This Skill Works

Materialization converts a plan's task breakdown into standalone task documents that sub-agents can execute independently. Each task doc is self-contained — it includes the codebase target, file paths, constraints, standards, and step-by-step instructions. This decoupling means sub-agents never need to parse the plan themselves; the task doc is their complete execution contract.

1. **Verify dry-run gaps** — confirm no blocking gaps remain from the latest dry-run
2. **Resolve codebase target** — determine which codebase this plan targets
3. **Resolve standards** — find and extract codebase quality standards if available
4. **Write task documents** — create one `.md` file per task in `plans/<plan>/tasks/`
5. **Validate** — run post-materialization checks on metadata and paths
6. **Report** — summarize what was created and hand off to implementation

---

## Step 1: Dry-Run Gap Verification

After approval, verify that outstanding dry-run gaps do not block materialization.

**Find the latest dry-run:** Match dry-run files whose filename begins with the plan's filename stem (without `.md`). For example, for plan `01-bilateral-materialization-gate.md`, match files in `dry-runs/` starting with `01-bilateral-materialization-gate-`. Sort matched files by file modification time (most recent first) — filename-based sorting is unreliable since dry-run files use inconsistent suffixes like `-deep`, `-round4`.

- **If no dry-run files match:** WARN. "No dry-run found for this plan. Consider running `/drvr:dry-run-plan` to validate before materializing. Proceed without dry-run verification?"
- **If files found:** Read the latest. Scan the gap table for rows whose Description column is NOT prefixed with `[FIXED]`. Count unfixed rows by severity:
  - Any unfixed HIGH or MEDIUM gaps → BLOCK. "N HIGH/MEDIUM gaps remain unfixed in the latest dry-run. Fix these gaps before materializing."
  - Only unfixed LOW gaps → WARN. "N LOW-severity gaps remain unfixed. These are minor — proceed with materialization?"
  - All gaps fixed or no gap table → proceed.

---

## Step 2: Resolve Codebase Target

Read `plans/00-overview.md` `## Implementation Environment`. Extract codebase paths,
Base Branch, Feature Branch, test commands, and any other environment details captured there.
Include all available environment information in each task doc's `## Codebase` section. If
the plan overview doesn't have an Implementation Environment section, read
`research/00-overview.md` `## Codebases` for codebase paths and branches. If falling back
to research Codebases and it has a single `Branch` column (legacy format), use that value
as both `**Base Branch**` and `**Feature Branch**` in the task doc.

Verify each codebase path exists on disk. If no valid paths are found, BLOCK.

**Multi-codebase resolution:** If the source has multiple valid rows:
1. First, try to infer the target codebase from the plan's `## Task Breakdown` file paths. Collect all file paths from `**Files**:` fields across tasks. For each codebase's Local Path, check if the plan's file paths resolve under it (e.g., `<Local Path>/<relative file path>` exists). If all files resolve under exactly one codebase, auto-resolve to that codebase.
2. If files resolve under multiple codebases (ambiguous), or no files resolve under any codebase, ask the user: "This plan's file paths match multiple codebases. Which codebase does this plan target? [list options]"
3. Report the resolution in Step 6: "Codebase auto-resolved from file paths" or "Codebase selected by user."

---

## Step 3: Resolve Standards

Search the feature's `research/` directory for a standards artifact (file containing `## Standards Source`). If found, extract the source path and key rules. If not found, omit the Code Quality Standards section from task docs.

If multiple files match, select the one whose Standards Source path is within the resolved codebase root from Step 2. If none match or multiple match, use the first alphabetically and warn the user. <!-- TODO: For multi-codebase features, this fallback could silently pick the wrong standards. Consider prompting the user instead of defaulting to first-alphabetically. -->

---

## Step 4: Write Task Documents

For each `### Task N` in the plan's `## Task Breakdown`:

**If no `### Task N` sections are found**, report "No tasks found in plan — skipping materialization" and return without creating the `tasks/` directory.

**If `plans/<plan-name>/tasks/` already exists with task docs**, WARN: "Task docs already exist for this plan. Re-materializing will overwrite incomplete tasks. Completed tasks (status: complete) will be preserved. Proceed?" For each task: if a corresponding task doc exists and is `status: complete`, skip it (preserve). If `not_started` or `in_progress`, overwrite it. If no corresponding task doc exists (new task added to revised plan), create it. After writing, report: "N created, M overwritten, K preserved."

**Create the directory** `plans/<plan-name>/tasks/` if it doesn't exist. The `<plan-name>` is the plan filename without its `.md` extension — the plan `.md` file and its directory coexist as siblings under `plans/`.

**Write each task doc** as `NN-slugified-task-name.md`:
- Slugify by: lowercase, replace spaces and underscores with hyphens, remove non-alphanumeric characters except hyphens, collapse consecutive hyphens, trim leading/trailing hyphens
- Truncate the slugified name to 60 characters (excluding the `NN-` prefix and `.md` extension) — if truncated, ensure the slug does not end with a hyphen
- Task names should use ASCII-only text for reliable filenames. If a task name produces an empty slug after stripping, fall back to `NN-task.md`

**Task document template:**

```markdown
---
type: task
status: not_started
plan: <plan-name>
task_number: <N>
depends_on:
  - <dependency-filename.md>
created: "YYYY-MM-DD"
materialized_at: "<ISO 8601 local time, e.g., 2026-04-15T14:32:00>"
---

# Task N: <name>

## Codebase
**Root**: <absolute path from Implementation Environment or research Codebases>
**Base Branch**: <from IE or Codebases>
**Feature Branch**: <from IE or Codebases>
<include all remaining environment details from the Implementation Environment section:
test commands, and any other relevant info. Omit fields not available.>

All file paths below are relative to the codebase root.
Execute all commands from the codebase root directory.
Do NOT navigate to or modify files outside this directory.

## Goal
<copied from plan — verbatim>

## Files
<copied from plan — verbatim>

## Tests
<copied from plan — verbatim>

## Constraints
<copied from plan — verbatim>

## Code Quality Standards
**Source**: <absolute path to codebase CLAUDE.md>

Key rules for this task:
- <key rules from standards artifact relevant to this task>

## Context
**Plan**: `plans/<plan-file>.md`
**Prerequisites**: <paths to research/context docs referenced in plan>

Read the plan for full architectural context if needed.

## Instructions
1. Change directory to the codebase root
2. Read the plan for full context
3. Read the code quality standards at the source path above
4. Implement exactly what's specified — no extras
5. Verify your code follows the standards
6. Run tests after implementation (use test command from Codebase section if present, otherwise follow Pre-flight Phase 4.3 discovery)
7. Report what you built, files touched, any deviations, and standards compliance
```

**If no Code Quality Standards section** (no standards artifact found), omit that section and use a 5-step Instructions list:
1. Change directory to the codebase root
2. Read the plan for full context
3. Implement exactly what's specified — no extras
4. Run tests after implementation
5. Report what you built, files touched, and any deviations

**Frontmatter rules:**
- `created` and `updated` use `YYYY-MM-DD` format (to pass `test_date_format` validation)
- `materialized_at` uses ISO 8601 local time without timezone suffix (e.g., `2026-04-15T14:32:00`)
- `status` values use the canonical set: `not_started`, `in_progress`, `complete`
- `depends_on` uses YAML block list format — NOT inline `["..."]` syntax. Values must be **unquoted** (the plugin's `parse_frontmatter` does not strip quotes from block list items). Example:
  ```yaml
  depends_on:
    - 01-write-tests.md
  ```
- If a task has no dependencies, **omit the `depends_on` field entirely** — do NOT use `depends_on:` with empty value
- Infer dependencies from TDD pairs: Task N+1 depends on Task N within test/implement pairs. Non-paired tasks have empty depends_on unless plan Constraints state otherwise

---

### CRITICAL: Step 5: Post-Materialization Validation (Checkpoint 1)

After writing all task docs, run a quick metadata check:

1. **Codebase root path** exists on disk
2. **Codebase root is a git repo** (`<root>/.git` exists)
3. **Standards path resolves** (if referenced in task docs)
4. **All task numbers** are sequential and unique
5. **Task dependency targets** reference existing task files within the `tasks/` directory

Report: "Checkpoint 1: N/5 checks passed." If any check fails, report the specific failure and ask the user how to proceed.

---

## Step 6: Report

"Materialized N tasks to `plans/<plan-name>/tasks/`. Codebase: <name> at <path>. [Checkpoint 1 results]."

**Terminal handoff:** "Task documents ready. To implement, activate `drvr:implementation-guidance` for plan `<plan-name>`."

**Update FEATURE_LOG.md:** Append to the log table:
```markdown
| <date> | Tasks materialized for plan <name> (<N> tasks, codebase: <name>) | `plans/<plan>/tasks/` |
```
Update the Current State header to reflect the new phase.

---

## Anti-Patterns

**Do NOT:**
- Skip materialization after plan approval — task docs are the execution contract
- Materialize tasks before the plan is approved and dry-run gaps are fixed
- Skip Checkpoint 1 after materialization

**DO:**
- Run materialization after plan approval — task docs embed everything sub-agents need for execution
- Run Checkpoint 1 after materialization — verify codebase paths and task integrity

---

## Before Responding Checklist

- [ ] **Plan approved?** — Is `status: approved` in the plan frontmatter?
- [ ] **Dry-run gaps checked?** — Are all HIGH/MEDIUM gaps fixed?
- [ ] **Codebase resolved?** — Is the target codebase identified and path valid?
- [ ] **Standards resolved?** — Has the standards artifact been checked (present or absent)?
- [ ] **Tasks materialized?** — Are task docs written to `plans/<plan>/tasks/`?
- [ ] **Post-materialization validated?** — Did Checkpoint 1 pass (codebase root, standards path, task numbering)?

---

## Related

- [planning-guidance](../planning-guidance/SKILL.md) — plan creation and approval (Step 7)
- [implementation-guidance](../implementation-guidance/SKILL.md) — task execution from materialized docs
- [sdlc-orchestration](../sdlc-orchestration/SKILL.md) — lifecycle transitions including materialization
