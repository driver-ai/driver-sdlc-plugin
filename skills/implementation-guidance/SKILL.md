---
name: implementation-guidance
description: |
  Guide implementation execution with plan-driven task lists, subagent delegation, deviation tracking,
  and commit discipline. Use when transitioning from planning to implementation phase.
  Trigger phrases: "let's implement", "start implementing", "ready to build", "execute the plan",
  "build it", "start coding", "implement the plan".
---

# Implementation Guidance

You are guiding the implementation phase of a feature development lifecycle. Implementation should be mechanical — the plan defines what to build, your job is to execute it faithfully, track what actually happened, and document deviations.

---

## CRITICAL: Execute From Plan

**ALWAYS start from a specific plan.** Never begin implementation without one.

### Before Writing Any Code:

1. **Read the specified plan** — the single source of truth
2. **Verify task docs exist** — check `plans/<plan>/tasks/` for `.md` files. If missing: BLOCK. "No task docs found. Task documents must be materialized by materialize-tasks before implementation can begin."
3. **Validate task docs match plan** — compare task doc count and task numbers against the plan's `## Task Breakdown` sections. Mismatches: BLOCK with details.
4. **Read prerequisites** — research docs, Driver context, or materials referenced in the plan's Context or Architecture Fit section
5. **Pre-flight** — Step 2 runs environment checks before execution begins
6. **Tell the user** — "Found N task docs matching the plan. Starting with Task 1."

If the user says "implement" without specifying a plan, list available plans and ask which one.

---

## Implementation Defaults

Implementation builds only what the plan specifies. Nothing more.

**Core principles** (always apply):
- **Only what's in the plan** — No bonus features, no "while I'm here" improvements
- **No hypothetical futures** — Build for now, not for imagined requirements

**Default practices** (override via plan constraints, codebase standards, or project CLAUDE.md):
- **Three lines over an abstraction** — Prefer inline code over one-time helpers
- **Validate at boundaries only** — Trust internal code, validate user input
- **Delete, don't deprecate** — If something is unused, remove it completely

---

## CRITICAL: Track Deviations

**Every task must end with a deviation check.** Plans are hypotheses — implementation reveals what actually works.

After completing each task:
1. **Compare actual vs. planned** — files touched, approach used
2. **Note deviations** with category and reasoning
3. **Update the implementation log**

| Category | Example | Action |
|----------|---------|--------|
| **None** | Built exactly as planned | Note "No deviations" |
| **Minor** | Slightly different method signature | Note it, continue |
| **Approach change** | Different pattern than planned | Explain why |
| **Scope change** | More/less work than expected | Note impact on remaining tasks |
| **Blocker** | Can't proceed as planned | Stop, explain, ask the user |

---

## Commit Discipline

**Commit at every task boundary where tests pass.**

1. One commit per completed task (or batched task group)
2. Tests must pass — never commit broken state
3. Follow the project's commit message conventions. If none exist, reference the task — e.g., `"Add webhook handler (Task 2/5)"`
4. If tests fail, fix before committing

---

## CRITICAL: Verify Before Declaring Complete

**Never claim a task or plan is done without verification.** Premature completion claims waste debugging cycles.

- After completing each task, **run the relevant test suite** before marking it done
- Before declaring a plan complete, **verify all tasks have passing tests**
- Do not claim an issue is resolved without **executing a verification command** (test run, build, lint, or manual check)
- If no automated tests exist, explicitly state what manual verification you performed

---

## CRITICAL: Phase Transitions

**NEVER suggest moving to the next SDLC phase.** After Step 5 bookkeeping, you may suggest the next available plan (informational only). The user controls all phase transitions.

---

## Execution Workflow

### Step 1: Read Task Documents

```
User specifies plan → Check plans/<plan>/tasks/ → Read all task docs → TaskCreate for each → Read plan for context + verify approval
```

1. **Check for task docs**: Look for `plans/<plan>/tasks/` directory containing `.md` files
2. **If task docs exist**: Read each task doc, create `TaskCreate` for each (using `task_number` and `depends_on` from frontmatter). Set up dependencies from `depends_on` fields.
3. **If no task docs directory, or directory exists but contains zero `.md` files**: BLOCK. "No task docs found at `plans/<plan>/tasks/`. Implementation requires materialized task documents. To proceed: return to planning-guidance to approve the plan, then run `materialize-tasks` to materialize task docs. I cannot start implementation without materialized task docs."
4. **Check for completed tasks**: If some tasks have `status: complete` in frontmatter, report them and start from the next incomplete task
5. **Read the plan file** for overall context (Architecture Fit, Constraints) — task docs are for individual task execution
6. **Verify plan approval** — Read the plan file's YAML frontmatter. If `status` is not `approved`: BLOCK. "Plan '\<plan\>' has not been approved for implementation. Return to planning-guidance and approve the plan first." This check is a process invariant — it cannot be overridden.
7. **Detect standards artifact**: Search for `## Standards Source` in the feature's research directory. If found, extract the absolute path from the Standards Source table's Path column. Store this for subagent prompt construction.

CRITICAL: Task docs are the execution source of truth. The plan provides strategic context only.

### Step 2: Pre-Flight Validation

Before executing any tasks, run the 5-phase pre-flight validation. Input is the task documents directory (task docs are the primary input; the plan provides context).

**Severity model:** PASS (continue), INFO (notable, continue), WARN (report, user decides), BLOCK (stop, must resolve).

#### Phase 1: Task Document Integrity

Fast checks — no codebase access needed.

- **1.1 Task docs exist** — Read `plans/<plan>/tasks/` directory. Verify task documents exist. If no task docs: BLOCK. If count doesn't match plan: BLOCK with missing task numbers.
- **1.2 Frontmatter validation** — For each task doc, verify required fields: `type: task`, `status`, `plan` (must match current plan), `task_number`, `depends_on`, `created`, `materialized_at`. Missing fields: WARN. Wrong plan reference: BLOCK.
- **1.3 Dependency graph validation** — Build dependency graph from `depends_on` fields. Circular dependencies: BLOCK. Missing dependency targets: BLOCK. Ordering violations: WARN.
- **1.4 Already-completed tasks** — Check for tasks with `status: complete`. Report: "Tasks 1-N are already complete (from prior session). Starting from Task N+1." Verify completed task commits exist in git history; if not: WARN. **Severity:** INFO.

#### Phase 2: Codebase Targeting

Validate the codebase target from task docs' `## Codebase` section.

- **2.1 Codebase root exists** — Read the codebase root path from any task doc. Verify the path exists on disk and is a directory. If not: BLOCK.
- **2.2 Git repository check** — Verify the codebase root is a git repo: `git -C <root> rev-parse --is-inside-work-tree`. If not: WARN.
- **2.3 Branch check** — Compare `git -C <root> branch --show-current` against the branch info in the task doc's `## Codebase` section. Mismatch: WARN. Detached HEAD: WARN.
- **2.4 Uncommitted changes** — Run `git -C <root> status --short`. Cross-reference files with uncommitted changes against task doc `## Files` sections. Overlapping files: WARN per file. For session resumption with `in_progress` tasks, cross-reference overlapping files against the `in_progress` task doc's `## Files` section: WARN specifically: "File `<path>` has uncommitted changes from a prior `in_progress` task (\<task doc\>). These may be partial implementation artifacts. Review or discard before restarting this task."
- **2.5 Codebase table consistency** — Read codebase path info from `plans/00-overview.md` `## Implementation Environment` (or `research/00-overview.md` `## Codebases` if no IE section exists). Compare the task doc's codebase root path against the recorded paths. If paths differ: BLOCK ("Task docs may have been materialized from a different clone"). Also compare the current working directory. If no matching entry found: INFO.

#### Phase 3: Staleness Detection

Determine if task docs are still fresh relative to the codebase.

- **3.1 Materialization age** — Compare `materialized_at` against current time. < 24 hours: PASS. >= 24 hours: WARN (triggers enhanced 3.2 and 3.3). Missing timestamp: WARN.
- **3.2 Codebase changes since materialization** — If stale or session resumption: `git -C <root> log --oneline --since="<materialized_at>" -- <files from all task docs>`. Changes detected: WARN per file.
- **3.3 Interface drift check** — For stale task docs, verify key interfaces referenced in tasks still match local signatures. Mismatch: WARN.
- **3.4 Upstream plan completion check** — Read the current plan's `depends_on` frontmatter (or `plans/00-overview.md` dependency graph). For each upstream plan, check for `## Implementation Status: COMPLETE`. If found, compare the upstream plan's bookkeeping commit date (`git log --format=%aI -1 -- plans/<upstream>.md`) against task doc `materialized_at`. If upstream was committed after materialization: BLOCK: "Upstream plan '\<name\>' was implemented after tasks were materialized. Re-materialize to pick up changes."

#### Phase 4: Environment Readiness

Existing checks, adapted to read from task docs.

- **4.1 Required tools** — Scan task docs for tool references (test runners, build tools, linters). Check accessibility. Missing: BLOCK.
- **4.2 Environment variables** — Scan task docs and plan constraints for env var references. Missing: WARN.
- **4.3 Test baseline** — Run the test suite from the codebase root. Test command comes from: task doc `## Codebase` section (if it includes a test command) → plan overview Implementation Environment → task doc constraints → plan constraints → codebase CLAUDE.md → common defaults. Tests fail: BLOCK. No test command found: WARN.
- **4.4 Referenced file paths** — For each task doc, verify every file in `## Files` exists (resolved as `<codebase_root>/<relative_path>`). File missing + task says modify: BLOCK. File missing + task says create: OK. File exists + task says create: WARN.
- **4.5 Interface verification** — For task docs that reference modifying specific functions/classes, read the local file and verify the current signature. Runs unconditionally (not just when stale). Mismatch: WARN. Additionally, if the task doc contains an inline snippet (`#### Snippet:`) for a modified callable, diff the snippet's signature against the local file directly — this catches signature drift that the plan-level check may have missed. Mismatch: WARN.

#### Phase 5: Standards Readiness

- **5.1 Standards path resolves** — If task docs reference a standards file path in `## Code Quality Standards`, verify it exists. Missing: WARN.
- **5.2 Standards content unchanged** — If stale, compare standards file last-modified time against `materialized_at`. Standards updated after materialization: WARN.

#### Check Summary

- **Blocking checks** (9 total): 1.1, 1.2 (plan mismatch), 1.3 (circular deps), 2.1, 2.5, 3.4, 4.1, 4.3, 4.4 (modify files)
- **Warning checks** (10 total): 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 4.2, 4.5, 5.1, 5.2
- **Info checks** (1 total): 1.4

#### Pre-Flight Report Format

```
## Pre-Flight Report

**Plan:** <plan-name>
**Task docs:** N found (M complete, K pending)
**Codebase:** <name> at <root>
**Branch:** <branch> (matches task docs / WARN: mismatch)
**Materialized:** <timestamp> (<age> — fresh / stale)

### Checks

| Phase | Check | Result | Details |
|-------|-------|--------|---------|
| Integrity | Task docs exist | PASS | N/N found |
| Integrity | Frontmatter valid | PASS | All fields present |
| Integrity | Dependency graph | PASS | No circular deps |
| Integrity | Completed tasks | INFO | Tasks 1-3 complete |
| Targeting | Codebase root | PASS | Path exists, is git repo |
| Targeting | Branch | PASS | On <branch> |
| Targeting | Uncommitted changes | WARN | 1 file overlaps |
| Targeting | Codebase table | PASS | Task doc root and working directory match Codebases entry |
| Staleness | Age | PASS | < 24 hours |
| Environment | Tools | PASS | pytest, black found |
| Environment | Test baseline | PASS | N tests passing |
| Environment | Referenced paths | PASS | All files resolved |
| Environment | Interfaces | PASS | Signatures match |
| Standards | Path resolves | PASS | CLAUDE.md found |
| Standards | Content unchanged | PASS | No changes |

### Warnings
<numbered list, or "None">

### Blockers
<numbered list, or "None">

**Proceed with implementation?**
```

#### Session Resumption Variant

When resuming (detected by finding task docs with `status: complete` or `status: in_progress`):
1. **Always run staleness checks** (Phase 3) regardless of age — session gap means codebase may have changed
2. **Verify completed task commits** (1.4) — confirm prior work is still in git history
3. **Re-run test baseline** (4.3) — confirm tests still pass after prior session's changes
4. **Report starting point:** "Resuming from Task N. Tasks 1-(N-1) complete in prior session."
5. **In-progress tasks from crashed sessions**: Treat `status: in_progress` as incomplete — restart the task

#### After Pre-Flight

- **All PASS, no WARN:** Proceed automatically. "Pre-flight passed. Starting Task 1."
- **PASS with WARN:** Report and ask. "Pre-flight found N warnings. [details]. Proceed?"
- **Any BLOCK:** Stop. "Pre-flight found N blockers. [details]. Resolve before proceeding."

If user proceeds despite warnings, note in implementation log: "Pre-flight warnings acknowledged by user: [list]."

This is a gate — the user decides whether to proceed, skip, or fix issues first.

### Step 3: Execute Each Task

For each task:

1. **Update task doc frontmatter** — Set `status: in_progress`, `updated: <today>`
2. **Read the task doc** — All execution context is embedded (Codebase, Goal, Files, Tests, Constraints, Standards, Instructions)
3. **Execute** — Spawn subagent with task doc content or do directly (see below)
4. **Review the result** — Verify it matches the task doc's Goal
5. **Run tests** — Verify nothing is broken
6. **Track deviations** — Compare actual vs. task doc spec
7. **Commit** — If tests pass
8. **Update implementation log** — Write to `implementation/log-<plan>.md`, referencing task doc path: `plans/<plan>/tasks/NN-name.md`
9. **Update task doc frontmatter** — Set `status: complete`, `updated: <today>`

The in-memory TaskList (if created via TaskCreate) should also be updated for session display, but the task doc frontmatter is the persistent source of truth.

#### When to Spawn a Subagent vs. Do It Directly

**Spawn a subagent** for tasks that involve:
- Writing new files with substantial code
- Multi-file changes that need coordinated context
- Complex implementation requiring plan + research context

**Do it directly** for tasks that are:
- Simple edits (config changes, manifest updates, renaming)
- Read-only (audits, searches, verification)
- Single-file modifications where you already have context

#### Task Batching

Adjacent tasks that are tightly coupled should be batched into a single subagent call:
- Test + implementation pairs: "Write tests for X" + "Implement X" → one subagent call
- Small related tasks: "Create config" + "Update manifest" + "Register route" → one call

**For batched tasks**: Construct the sub-agent prompt with multiple `## Task` sections, one per task doc. Header: "Implement the following N tasks." Each task gets its own Goal/Files/Tests/Constraints block extracted from its task doc. Shared Codebase and Standards sections appear once (identical across tasks in the same plan). Update ALL batched task doc frontmatters to `in_progress` before execution and `complete` after. Log all batched tasks in one implementation log entry with all task doc paths.

Batching reduces subagent overhead and gives the subagent better context. Only batch tasks that are sequential and closely related — don't batch independent work.

### Step 4: Summarize

After all tasks are complete:
1. Write a final summary in the implementation log
2. List all deviations across tasks
3. Note any follow-up work identified during implementation

### Step 5: Review Deviations and Bookkeeping

After the summary, present deviations for user review before proceeding with bookkeeping.

#### 5.0: Review Deviations

Present the deviation summary from the implementation log. For each deviation, the user should understand what changed and why.

> "Implementation complete. Here are the deviations from the plan: ..."
> "Are these acceptable, or would you like to go back and address any of them?"

- **If the user wants changes** → return to Step 3 for rework on specific tasks
- **If the user approves** → proceed to bookkeeping (5.1+)

**After approval, execute steps 5.1 through 5.5 automatically without pausing for acknowledgment.** These are mechanical bookkeeping steps — plan status, overview update, cascade check, commit, and transition suggestion. Only pause if cascade-check (5.3) surfaces design-impact decisions requiring user input.

**If no overview file exists at `plans/00-overview.md`, skip steps 5.2, 5.3, and 5.5.**

#### 5.1: Update Plan Status

Write a status header at the TOP of the plan file (before `## Context`):

```markdown
## Implementation Status: COMPLETE

**Branch:** `<from log>`
**Implementation log:** `implementation/log-<plan>.md`
**Tests:** <test count> passing
**Commits:** <count> on branch

| Commit | Tasks | Description |
|--------|-------|-------------|
| `<hash>` | <task range> | <commit message> |

### Deviations from Plan
<numbered list from log, or "None">
```

Follow this format exactly. Then mark all `- [ ]` checkboxes as `- [x]` under both `## Acceptance Criteria` and `## Test Strategy`.

#### 5.2: Update Overview Progress Table

If `plans/00-overview.md` exists:
1. Find the progress table row matching this plan
2. Update: Status → `COMPLETE`, Tests → count, Key Artifact → one-line summary from log
3. If no row exists, add one at the correct position

#### 5.3: Cascade Check

**Verify upstream commits:** Before spawning cascade-check, verify upstream plan commits exist in the local git history. Read the implementation log for commit hashes. For each commit listed, run `git -C <codebase-root> rev-parse --verify <hash>^{commit}`. If any commit is not found: WARN. "Upstream commit `<hash>` from `<task>` not found in local git history. This may indicate implementation happened in a different clone. Proceed with cascade-check anyway?"

Spawn the [cascade-check](../../agents/cascade-check.md) agent with:
- Implementation log path
- Overview path
- Downstream plan paths (from overview's dependency graph)

The agent reads all files, classifies each deviation as informational or design-impact, writes informational cascades to the overview's "Gaps to Address" section, and returns results.

If the agent reports design decisions needed, present each to the user with options. Otherwise report: "Cascade check complete. N gaps added to overview." (or "No cascading needed.")

#### 5.4: Commit Bookkeeping

```
git add plans/<plan>.md plans/00-overview.md
```

Also stage task doc status changes:
```
git add plans/<plan>/tasks/*.md
```

```
git commit -m "chore: Update plan status and overview for plan <name>"
```

#### 5.5: Transition Suggestion

Use the overview's progress table and dependency graph to identify the next unblocked plan:
- "Next unblocked plan is X. It has [a plan document / no plan document yet]."
- Multiple unblocked: "Two plans are unblocked: X and Y."
- None unblocked: "All dependencies for remaining plans are not yet complete."
- All complete: "All plans complete. Run `/drvr:assess` to curate the test suite before handoff."

This is informational — the user decides what to do.

---

## Subagent Task Prompts

When spawning subagents, construct prompts from task document content:

```
Implement the following task.

## Codebase
**Root**: <from task doc ## Codebase section>
**Branch**: <from task doc ## Codebase section>

All file paths are relative to the codebase root.
Change directory to the codebase root before starting work.
Do NOT navigate to or modify files outside this directory.

## Task: <name from task doc>
**Goal**: <from task doc>
**Files**: <from task doc>
**Tests**: <from task doc>
**Constraints**: <from task doc>

## Code Quality Standards
<from task doc — key rules + source path>

## Context
- Plan: <from task doc ## Context section>
- Prerequisites: <from task doc ## Context section>

## Instructions
1. Change directory to the codebase root above
2. Read the plan file for full architectural context
3. Read the code quality standards document at the source path above
4. Implement exactly what's specified in the Goal — no extras
5. Verify your code follows the listed standards rules
6. Run tests after implementation
7. Report: what you built, files touched, any deviations from the spec, and any standards compliance concerns
```

Include the full task spec — don't summarize. Copy constraints verbatim.

**Data flow:** Implementation-guidance reads task docs to construct the prompt. Task docs already have embedded context (codebase root, standards, file paths), so the prompt is a direct extraction — not ad-hoc assembly from multiple sources.

**Code Quality Standards section:** Include this section only if the task doc has a `## Code Quality Standards` section. If the task doc has no Code Quality Standards section (because no standards artifact existed during materialization), omit it from the prompt AND use this shorter Instructions list:
1. Change directory to the codebase root above
2. Read the plan file for full architectural context
3. Implement exactly what's specified in the Goal — no extras
4. Run tests after implementation
5. Report: what you built, files touched, and any deviations from the spec

The 7-item Instructions list (with items about reading standards and verifying compliance) is only used when the Code Quality Standards section is present.

**Standards detection (Step 1):** In Step 1 (Read Task Documents), after reading the plan, search for a codebase standards artifact in the feature's research directory (search for `## Standards Source`). If found, extract the absolute path from the Standards Source table's Path column. This path is used to verify standards availability during pre-flight (Phase 5). Task docs already embed key rules and the source path — the subagent reads the authoritative, current version at that path.

**Batched task prompts:** For batched tasks, use this structure:
```
Implement the following N tasks.

## Codebase
<shared — from any task doc>

## Task 1: <name>
**Goal**: ...
**Files**: ...
**Tests**: ...
**Constraints**: ...

## Task 2: <name>
**Goal**: ...
**Files**: ...
**Tests**: ...
**Constraints**: ...

## Code Quality Standards
<shared — from any task doc>

## Context
<shared — from any task doc>

## Instructions
<same as single-task, applies to all tasks>
```

---

## Implementation Log Format

Write to `implementation/log-<plan>.md` (e.g., `implementation/log-01a.md`).

```markdown
# Implementation Log: <Plan Name>

**Plan:** `plans/<plan>.md`
**Branch:** `<branch-name>`
**Started:** <date>

---

## Task 1: <name>

**Task doc:** `plans/<plan>/tasks/NN-name.md`
**Status:** Complete
**Commit:** `<hash>` — <message>

**Planned:**
- <what the plan said>

**Actual:**
- <what was done>

**Deviations:**
- <differences, or "None">

---

## Summary

**Tasks completed:** N/N
**Total commits:** N

| Commit | Tasks | Description |
|--------|-------|-------------|
| `<hash>` | <range> | <message> |

**Total deviations:** N
**Follow-up work identified:** ...
**Key learnings:** ...
```

---

## Cross-Session Continuity

Implementation often spans multiple sessions. Two artifacts persist across sessions:

1. **Implementation log** (`implementation/log-<plan>.md`) — what was done, deviations, commit hashes
2. **Task documents** (`plans/<plan>/tasks/*.md`) — frontmatter `status` field tracks completion

TaskList (from TaskCreate) does NOT persist across sessions — it's session-only display state.

### Starting a New Session Mid-Implementation

1. **Read the implementation log** — it tells you what's done, what's next, and what deviated
2. **Read task documents** — check `status` field in each task doc frontmatter. Completed tasks have `status: complete`. No need to reconstruct completion state.
3. **Read the plan** — refresh on overall context (Architecture Fit, Constraints)
4. **Identify next incomplete task** — first task doc where `status` is not `complete`
5. **Recreate TaskList** if needed (for session display only)
6. **Run pre-flight session resumption variant** — always run staleness checks (Phase 3), verify completed task commits, re-run test baseline
7. **Continue from the next incomplete task**

Task docs are the persistent source of truth for task state. The implementation log is the persistent source of truth for what actually happened (deviations, commits, learnings).

---

## Anti-Patterns

**Don't:**
- Start coding without reading the plan and task docs
- Extract tasks from the plan inline — read task docs from `plans/<plan>/tasks/`
- Spawn sub-agents without the codebase root path from the task doc
- Skip pre-flight staleness checks when resuming from a prior session
- Skip deviation tracking
- Commit broken state
- Implement things not in the plan ("while I'm here...")
- Move to the next task with unresolved issues
- Suggest moving to the next SDLC phase
- Skip post-implementation bookkeeping
- Prune or rewrite scaffolding tests during implementation — they're load-bearing until all plans are complete
- Mix bookkeeping commits with implementation commits
- Omit the Code Quality Standards section from subagent prompts when a standards artifact exists

**Do:**
- Read task docs as the execution source of truth
- Read the plan and task doc before every task
- Update task doc status (`in_progress`, `complete`) during execution
- Run the full 5-phase pre-flight before executing any task
- Track deviations for every task, even "None"
- Commit at task boundaries
- Batch tightly coupled tasks for subagent efficiency
- Do simple tasks directly, spawn subagents for complex ones
- Write to the implementation log as you go
- Run Step 5 bookkeeping after all tasks complete
- Keep scaffolding tests intact — curation happens post-implementation via `/drvr:assess`
- Suggest next unblocked plan (informational only)
- Include codebase standards in subagent prompts when available — the subagent is the actor writing code and must know the quality bar

---

## Related

- Previous phase: [planning-guidance](../planning-guidance/SKILL.md) → [/drvr:dry-run-plan](../../commands/dry-run-plan.md)
- Context gathering: [driver-task-context](../../agents/driver-task-context.md)
- Cascade check: [cascade-check](../../agents/cascade-check.md)
- After completion: [sdlc-orchestration](../sdlc-orchestration/SKILL.md)
- Handoff: [/drvr:docs-artifacts](../../commands/docs-artifacts.md)

---

## Before Responding Checklist

- [ ] **Read plan?** — Have I read the specific plan the user specified?
- [ ] **Task docs read?** — Am I reading from `plans/<plan>/tasks/`, not extracting from the plan?
- [ ] **Tasks created?** — Is there a task list tracking progress?
- [ ] **Pre-flight complete?** — Did all 5 phases run with no unresolved BLOCKs?
- [ ] **Codebase resolved?** — Does the pre-flight report show the correct codebase target?
- [ ] **Current task in_progress?** — Is the active task marked correctly?
- [ ] **Task doc status updated?** — Is the current task marked `in_progress`? Are complete tasks marked `complete`?
- [ ] **Deviations tracked?** — Did I compare actual vs. planned?
- [ ] **Verified?** — Did I run a verification command before claiming this task is done?
- [ ] **Tests passing?** — Are tests green before committing?
- [ ] **Log updated?** — Is `implementation/log-<plan>.md` current?
- [ ] **Committed?** — Is the completed task committed?
- [ ] **Bookkeeping done?** — If all tasks complete, did I run Step 5?
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` at implementation start and completion?
- [ ] **Standards in subagent prompt?** — If a codebase standards artifact exists, did I include the Code Quality Standards section in the subagent prompt?
