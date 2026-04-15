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
2. **Read prerequisites** — research docs, Driver context, or materials referenced in the plan's Context or Architecture Fit section
3. **Extract the Task Breakdown** — find the `## Task Breakdown` section
4. **Create a task list** — `TaskCreate` for each task in the plan
5. **Pre-flight** — Step 2 runs environment checks before execution begins
6. **Tell the user** — "I've created N tasks from the plan. Starting with Task 1."

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

### Step 1: Read Plan and Create Tasks

```
User specifies plan → Read it → Read prerequisites → Extract Task Breakdown → TaskCreate for each
```

Set up dependencies if tasks are sequential (`addBlockedBy`).

### Step 2: Pre-Flight Validation

Before executing any tasks, verify the environment is ready:

1. **Required tools** — Check that tools referenced in the plan exist and are accessible (`which <tool>` or `command -v <tool>`). Examples: compilers, build tools, database CLIs, linters.
2. **Environment variables** — Check that env vars referenced in the plan or project config are set. Flag any that are missing.
3. **Test baseline** — Run the project's test suite to establish a clean baseline. If tests fail before you've changed anything, stop and report.
4. **Referenced paths** — Verify that files and directories referenced in the plan's task breakdown actually exist. Flag any missing paths.
5. **Interface verification** — For key functions or classes the plan modifies, read the local file and verify the current signature matches what the plan assumes. If the plan says "add `retry_delivery` method to `NotificationService`" but `NotificationService` has been refactored locally since planning, flag it. This catches divergence between the remote state (used during planning) and local state (used during implementation).

**Report findings:**
> "Pre-flight complete. Found N issues: [list]. Proceed with implementation?"

**If critical issues found** (tools missing, tests failing):
> "Pre-flight found critical issues that will block implementation: [list]. These should be resolved before proceeding."

This is a gate — the user decides whether to proceed, skip, or fix issues first.

### Step 3: Execute Each Task

For each task:

1. **Set status** — `TaskUpdate` to `in_progress`
2. **Read the task spec** — Goal, Files, Tests, Constraints
3. **Execute** — spawn subagent or do it directly (see below)
4. **Review the result** — verify it matches the plan
5. **Run tests** — verify nothing is broken
6. **Track deviations** — compare actual vs. planned
7. **Commit** — if tests pass
8. **Update log** — write to `implementation/log-<plan>.md`
9. **Set status** — `TaskUpdate` to `completed`

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

Spawn the [cascade-check](../../agents/cascade-check.md) agent with:
- Implementation log path
- Overview path
- Downstream plan paths (from overview's dependency graph)

The agent reads all files, classifies each deviation as informational or design-impact, writes informational cascades to the overview's "Gaps to Address" section, and returns results.

If the agent reports design decisions needed, present each to the user with options. Otherwise report: "Cascade check complete. N gaps added to overview." (or "No cascading needed.")

#### 5.4: Commit Bookkeeping

```
git add plans/<plan>.md plans/00-overview.md
git commit -m "chore: Update plan status and overview for plan <name>"
```

#### 5.5: Transition Suggestion

Use the overview's progress table and dependency graph to identify the next unblocked plan:
- "Next unblocked plan is X. It has [a plan document / no plan document yet]."
- Multiple unblocked: "Two plans are unblocked: X and Y."
- None unblocked: "All dependencies for remaining plans are not yet complete."
- All complete: "All plans complete. Run `/assess` to curate the test suite before handoff."

This is informational — the user decides what to do.

---

## Subagent Task Prompts

When spawning subagents, construct prompts from the plan's task spec:

```
Implement the following task from the approved plan.

## Task: <name>
**Goal**: <from plan>
**Files**: <from plan>
**Tests**: <from plan>
**Constraints**: <from plan>

## Code Quality Standards
**Source**: <absolute path to codebase CLAUDE.md>
Standards document for reference during implementation.
Your code must comply with these standards. Key rules for this task:
- <relevant rules from plan constraints that cite codebase standards>

## Context
- Plan: <path to plan file>
- Prerequisites: <paths to research/context docs>

## Instructions
1. Read the plan for full context
2. Read the code quality standards document at the path above
3. Implement exactly what's specified — no extras
4. Verify your code follows the standards (naming, error handling, types, structure, testing patterns)
5. Run tests after implementation
6. Report what you built, files touched, any deviations, and any standards compliance concerns
```

Include the full task spec — don't summarize. Copy constraints verbatim.

**Code Quality Standards section:** Include this section only if a codebase standards artifact exists in the feature's research directory (search for a file containing `## Standards Source`). If no standards artifact exists, omit the Code Quality Standards section entirely AND revert to the original 4-item Instructions list:
1. Read the plan for full context
2. Implement exactly what's specified — no extras
3. Run tests after implementation
4. Report what you built, files touched, and any deviations

The 6-item Instructions list (with items about reading standards and verifying compliance) is only used when the Code Quality Standards section is present. Without that section, instructions 2 and 4 would reference something that doesn't exist.

**Data flow:** The implementation-guidance skill must read the standards artifact to extract the source path. In Step 1 (Read Plan and Create Tasks), after reading the plan, search for a codebase standards artifact in the feature's research directory (same detection: search for `## Standards Source`). If found, extract the absolute path from the Standards Source table's Path column. Use that absolute path as the `<Source>` in the subagent prompt — the subagent reads the authoritative, current version, not the research artifact. Key rules should be copied from the plan's constraints that cite codebase standards.

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

Implementation often spans multiple sessions. The **implementation log** is the cross-session artifact — TaskList does not persist across sessions.

### Starting a New Session Mid-Implementation

1. **Read the implementation log** — it tells you what's done, what's next, and what deviated
2. **Read the plan** — refresh on remaining task specs
3. **Recreate tasks** if needed (TaskList is session-only)
4. **Continue from the next incomplete task**

The log should always have enough context for a fresh session to continue: completed tasks with commit hashes, what's next, blockers, and deviations affecting remaining tasks.

---

## Anti-Patterns

**Don't:**
- Start coding without reading the plan
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
- Read the plan before every task
- Track deviations for every task, even "None"
- Commit at task boundaries
- Batch tightly coupled tasks for subagent efficiency
- Do simple tasks directly, spawn subagents for complex ones
- Write to the implementation log as you go
- Run Step 5 bookkeeping after all tasks complete
- Keep scaffolding tests intact — curation happens post-implementation via `/assess`
- Suggest next unblocked plan (informational only)
- Include codebase standards in subagent prompts when available — the subagent is the actor writing code and must know the quality bar

---

## Related

- Previous phase: [planning-guidance](../planning-guidance/SKILL.md) → [/dry-run-plan](../../commands/dry-run-plan.md)
- Context gathering: [driver-task-context](../../agents/driver-task-context.md)
- Cascade check: [cascade-check](../../agents/cascade-check.md)
- After completion: [sdlc-orchestration](../sdlc-orchestration/SKILL.md)
- Handoff: [/docs-artifacts](../../commands/docs-artifacts.md)

---

## Before Responding Checklist

- [ ] **Read plan?** — Have I read the specific plan the user specified?
- [ ] **Tasks created?** — Is there a task list tracking progress?
- [ ] **Pre-flight done?** — Ran environment checks before starting task execution
- [ ] **Current task in_progress?** — Is the active task marked correctly?
- [ ] **Deviations tracked?** — Did I compare actual vs. planned?
- [ ] **Verified?** — Did I run a verification command before claiming this task is done?
- [ ] **Tests passing?** — Are tests green before committing?
- [ ] **Log updated?** — Is `implementation/log-<plan>.md` current?
- [ ] **Committed?** — Is the completed task committed?
- [ ] **Bookkeeping done?** — If all tasks complete, did I run Step 5?
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` at implementation start and completion?
- [ ] **Standards in subagent prompt?** — If a codebase standards artifact exists, did I include the Code Quality Standards section in the subagent prompt?
