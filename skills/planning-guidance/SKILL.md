---
name: planning-guidance
description: |
  Guide planning methodology with TDD-first task design, test strategy, architecture fit, explicit
  constraints, and task breakdown. Use when transitioning from research to planning phase.
  Trigger phrases: "let's plan", "ready to plan", "move to planning", "create a plan",
  "how should we implement", "test strategy", "what should I test", "TDD", "tests first".
---

# Planning

You are creating an implementation plan for a software engineering task. You work from research output, gather deep codebase context via Driver MCP, and produce a plan specific enough that an engineer or agent can implement it mechanically — down to the level of specific files, functions, and code changes.

---

## How This Skill Works

1. **Ingest research** — read the research output to understand findings and decisions
2. **Clarify scope** — ask the user what exactly to build, push back on vagueness
3. **Gather broad codebase context** — use `gather_task_context` for architecture and conventions
4. **Detail with primitive tools** — use `get_code_map`, `get_file_documentation`, `get_source_file` for specific file-level understanding
5. **Write the plan** — approach, TDD-ordered task breakdown, acceptance criteria
6. **Self-review** — validate the plan against the actual codebase using Driver tools
7. **Approve** — user reviews, approves plan for implementation

---

## Step 1: Ingest Research

This skill assumes research has been done. Ask the user to point you to the research output folder.

**Read all research documents:**
- Start with `00-overview.md` for the summary and document index
- Read each numbered deep-dive document for detailed findings
- Note key decisions, open questions, and constraints

**Check for codebase standards:**
- Look for a research doc with a `## Standards Source` section (the codebase standards artifact from research)
- If found, read it — the Key Rules and Applicable Sections will be encoded as plan constraints in Step 5
- If not found, no codebase standards were discovered during research — proceed without standards constraints

If research doesn't exist, tell the user: "This skill works best with research output as input. Want to run the research skill first?"

---

## Step 2: Clarify Scope

With research context loaded, ask the user what they want to build.

**Ask focused questions:**
- Which findings from research do you want to act on?
- What's the desired end state?
- What constraints exist? (timeline, compatibility, dependencies)
- What's explicitly out of scope?

**Push back on scope creep.** If the user says "and also..." that's a signal to split into separate plans. Each plan should deliver one logical unit of work.

---

## Step 3: Gather Broad Codebase Context

### CRITICAL: Use `gather_task_context` — Not Native Agents

`gather_task_context` is Driver MCP's primary tool. **It is your default tool for codebase context.** (Full tool name: `mcp__driver-mcp__gather_task_context` — directly callable from the main conversation.)

**What it does:** It spawns a specialized context agent on Driver's servers that reads pre-computed, exhaustive codebase documentation — architecture overviews, code maps, file-level documentation, changelogs — and does live runtime analysis. It then synthesizes everything into task-specific dynamic context: relevant architecture, key files, conventions, and suggested approaches.

**How to call it for planning:** Provide a task description focused on what you're about to plan. Include architectural concerns and testing patterns.

```
Example task description:
"Planning implementation of retry logic for the notification delivery
system. Need to understand: current delivery pipeline architecture,
error handling patterns, queue configuration, existing retry mechanisms
elsewhere in the codebase, and testing patterns/frameworks used."
```

**It takes 1-3 minutes. This is expected and normal.** The tool is doing work that would take you just as long or longer to do iteratively with native tools — and it produces higher-quality dynamic context because it works from pre-computed, exhaustive documentation rather than raw source files. Wait for the full response.

### CRITICAL: Do NOT Substitute Native Agents

**Do NOT use native Explore agents, subagents, or manual file-reading/grep as a substitute for `gather_task_context`.** These native tools work from raw source only. `gather_task_context` has access to pre-computed documentation that covers architecture, symbol-level details, development history, and conventions — dynamic context that native tools cannot replicate.

Native tools are useful for **targeted follow-up** after `gather_task_context` returns (see Step 4), but they are not a replacement for it.

### Running Multiple Calls in Parallel

When you need context from multiple angles (e.g., architecture AND testing patterns), spawn native subagents as concurrency wrappers. Each subagent's **only job** is to call `gather_task_context` and return the result.

**This is the one correct use of native subagents in this skill.** The subagent is a concurrency wrapper — it does NOT do its own codebase exploration.

| Pattern | What the subagent does | Correct? |
|---------|----------------------|----------|
| **Substitution** | Its own file reading, grep, exploration — bypassing Driver | No |
| **Parallelism wrapper** | Calls `gather_task_context` with a specific task description, returns the result | Yes |

**Example:** You need architecture context and testing patterns for the same feature. Spawn two subagents, each calling `gather_task_context` with a different focused task description. Collect both results before writing the plan.

---

## Step 4: Detail with Primitive Driver MCP Tools

After `gather_task_context` gives you the broad picture, drill into specifics using Driver's primitive tools. **This step is essential for reaching code-level plan specificity.**

### `get_code_map`
Navigate codebase structure. Use this to:
- Find the exact directories and files the plan will touch
- Understand how code is organized around the area you're modifying
- Verify that files referenced in research still exist and are in expected locations

### `get_file_documentation`
Get symbol-level documentation for specific files. Use this to:
- Understand function signatures, types, classes, and interfaces in files the plan will modify
- Identify the exact methods to extend or modify
- Understand a file's public API without reading every line of source

### `get_source_file`
Read the actual source code. Use this to:
- See exact current implementation when the plan needs to prescribe specific code changes
- Understand control flow, error handling patterns, and edge cases
- Get the precise code context needed to write accurate task specifications

**The progression is: `gather_task_context` (broad) → `get_code_map` (navigate) → `get_file_documentation` (interfaces) → `get_source_file` (implementation).** You won't always need all four, but the plan should be specific enough that you've used at least the first three.

---

## Step 5: Write the Plan

## CRITICAL: Write Plans to Files

**NEVER write plan content in chat.** Always write to `plans/*.md`.

### Output Structure

```
plans/
├── 00-overview.md      # Index (only if multiple plans)
├── 01-<name>.md        # The plan
└── ...                 # Additional plans if needed (usually just 1)
```

### Plan Sizing

Each plan should produce **one reviewable PR**. Signals a plan is well-sized:

- **5-12 tasks** — fewer means tasks are too broad for subagents; more means the plan should be split
- **One logical unit of work** — a plan delivers one capability that can be tested independently
- **Focused scope** — if explaining the plan requires "and also..." it should be two plans

**Split when:**
- The PR would be too large to review (>500 lines of real code, not counting tests)
- Tasks have no dependencies on each other (parallel tracks = separate plans)
- Different codebases are involved (one plan per codebase, unless tightly coupled)

**Don't split when:**
- Tasks are sequential and tightly coupled (test + implement pairs)
- The feature only makes sense as a whole (splitting would create a broken intermediate state)

### Multi-Plan Overview

For features that span multiple plans, create `plans/00-overview.md` as the central coordination document.

**When to create an overview:**
- Feature will have 2+ plans
- Multiple codebases or components are involved
- Plans have dependencies on each other

**Overview template:**

````markdown
# <Feature Name> — Planning Overview

## Status
**Phase**: Planning
**Last Updated**: <date>

### Progress
| Plan | Status | Tests | Key Artifact |
|------|--------|-------|-------------|
| 01 <name> | NOT STARTED | — | <what it delivers> |
| 02 <name> | NOT STARTED | — | <what it delivers> |

## Planning Strategy
_Why the feature is broken into these plans, what order, what the rationale is_

## Dependency Graph
_ASCII diagram showing which plans depend on which_

## Interface Contracts Between Plans
_Key seams between plans — method signatures, data models, API routes, config_
_Each plan defines its interface; downstream plans develop against it_

## Gaps to Address in Downstream Plans
_Surfaced during implementation — deviations that affect other plans_

## Open Questions
- [ ] <unresolved decisions>
````

#### Interface Contracts Are Critical

The interface contracts section prevents the most expensive planning failure: discovering during implementation that Plan B's assumptions don't match Plan A's definitions. Define contracts explicitly when writing each plan.

#### Consumer Validation

After writing a plan, check whether downstream plans are compatible:

1. Read the overview's dependency graph — find plans that depend on this one
2. For each downstream plan that already exists as a document:
   - Compare interface contracts: does THIS plan's definition match what the downstream plan assumes?
   - Flag mismatches: "Plan 01b assumes a 7-method interface. Plan 01a defines 4 methods."
3. If no downstream plans exist yet, note what the interface contract is so future plans can develop against it

This catches interface design problems during planning (free to fix) rather than during implementation (expensive refactor).

### Plan Document Template

```markdown
# Plan: <name>

## Context
_Summary from research — problem statement, scope, key decisions_

## Architecture Fit
_Existing patterns to follow, with specific file paths from Driver context_
_Directories and files this plan touches_
_Integration points with existing code_

## Acceptance Criteria
- [ ] Criterion 1 (specific, testable)
- [ ] Criterion 2

## Test Strategy

### Testing Patterns
_Testing framework, file organization, and conventions discovered via Driver_

### Unit Tests
- [ ] Test: `<test_name>` — verifies <specific behavior>

### Integration Tests
- [ ] Test: `<test_name>` — verifies <specific behavior>

## Implementation Approach
_High-level approach, key design decisions, rationale_

## Scope
**In scope (explicitly requested):** ...
**In scope (surfaced during planning):** ...
**Out of scope (deferred):** ...

## Constraints
- <constraints from codebase standards artifact, with source citations — omit if no standards artifact>
- <specific, actionable constraints — not generic advice>

## Task Breakdown

### Task 1: Write tests for <component>
**Goal**: Define test expectations (TDD red phase)
**Files**: `path/to/test_file.py` (create)
**Tests**: <specific test cases from Test Strategy>
**Constraints**: Tests should fail initially — implementation comes in Task 2

### Task 2: Implement <component>
**Goal**: Make Task 1 tests pass (TDD green phase)
**Files**: `path/to/source_file.py` (modify — add `function_name` method to `ClassName`)
**Tests**: Task 1 tests should now pass
**Constraints**: Follow patterns from `path/to/existing_similar.py`
```

### TDD Task Ordering

**Always order test tasks before implementation tasks.**

```
WRONG:
  Task 1: Implement retry logic
  Task 2: Write tests for retry logic

RIGHT:
  Task 1: Write tests for retry logic (TDD red phase)
  Task 2: Implement retry logic (TDD green phase — make Task 1 tests pass)
```

### Code-Level Specificity

Each task must prescribe concrete changes — not hand-wavy descriptions:

**Too vague:** "Implement the notification handler"

**Specific enough:** "Add `retry_delivery` method to `NotificationService` in `backend/services/notification_service.py`. Method should accept a `notification_id: str` and `attempt: int`, look up the notification from the database using the existing `get_notification` method, and re-enqueue it via `delivery_queue.enqueue()` with exponential backoff. Follow the retry pattern in `backend/services/email_service.py:retry_send`."

This level of detail comes from Step 4 — using Driver's primitive tools to understand the exact files, functions, and patterns involved.

### Explicit Constraints

Be specific. Generic advice is not a constraint.

**Encode codebase standards as constraints:**
If a codebase standards artifact exists from research, encode each applicable standard as a plan constraint. Standards-derived constraints follow the same format as other constraints — the source citation is the only difference. Use the standard's own language and cite the source:

| Good Constraint (from standards) | Bad Constraint |
|----------------------------------|---------------|
| "§6: try/except blocks must be as narrow as possible. Source: driver/backend/CLAUDE.md" | "Follow good error handling practices" |
| "§4: Prefer Pydantic models over raw dicts for structured data. Source: driver/backend/CLAUDE.md" | "Use appropriate data structures" |
| "§8: Separate I/O from logic for testability. Source: driver/backend/CLAUDE.md" | "Write testable code" |

| Good Constraint | Bad Constraint |
|----------------|---------------|
| "Follow error handling pattern in `src/errors.ts`" | "Write good error handling" |
| "NO TODOs or stubbed functions" | "Write complete code" |
| "Run `pytest backend/tests/` after every change" | "Run tests" |
| "All new functions must have type hints" | "Follow best practices" |

### Testing Methodology

Testing is a planning concern. The test strategy shapes task ordering and acceptance criteria.

#### Test Pyramid

| Type | Typical Ratio | Purpose |
|------|---------------|---------|
| **Unit** | 70% | Business logic, pure functions |
| **Integration** | 20% | Component interactions, API contracts |
| **E2E** | 10% | Critical user journeys |

Adjust per project: API-heavy → more integration; UI-heavy → more e2e; library → more unit.

#### Coverage Targets

| Code Type | Target |
|-----------|--------|
| Business logic | 100% |
| API contracts | 100% |
| Edge cases / error handling | 90%+ |
| Critical user paths | E2E covered |
| Utilities / helpers | 80%+ |
| Glue code / wiring | Lower priority |

#### Mocking Boundaries

**Mock:** External APIs, database (in unit tests), time/date, random values.
**Don't mock:** The code under test, internal modules, simple data structures.
**Over-mocking signal:** Test setup is longer than the test itself.

#### Test Lifecycle

Not all TDD tests are permanent. Some are **scaffolding** — they help you build (verify wiring, assert mock call sequences, confirm implementation details). Others are **durable** — they help you maintain (assert observable behavior, test contracts, cover edge cases).

During planning, design both kinds deliberately:
- Scaffolding tests validate that components are wired correctly during construction
- Durable tests validate behavior that should survive refactoring
- Coverage targets (above) apply to durable tests — scaffolding tests don't count toward long-term coverage

After all plans are implemented, `/drvr:assess` curates the test suite by categorizing each test as **PRUNE** (scaffolding that's served its purpose), **KEEP** (durable tests covering observable behavior), or **PROMOTE** (tests worth keeping but needing refactoring to assert behavior instead of implementation details). Plan accordingly: write scaffolding tests freely during TDD, knowing they'll be categorized and acted on during assessment.

#### Fixture Sourcing

Test fixtures for external API responses must come from **real API calls**, not reconstructed from documentation. Documentation-sourced fixtures can encode incorrect assumptions about response structure.

If the API isn't available, document: "fixture sourced from docs — verify against real response during integration testing."

#### Test Specificity in Plans

Each test case must have enough detail for a subagent to write it:

**Too vague:** "Test: user authentication works"

**Good:** "Test: `login_with_valid_credentials_returns_token` — POST `/auth/login` with valid credentials returns 200 with JWT containing `user_id` claim"

---

## Step 6: Self-Review

After drafting the plan, validate it against the actual codebase. **This step is required, not optional.**

### Big-Picture Check
Call `gather_task_context` with a task description focused on validating the plan:

```
Example:
"Reviewing a plan to add retry logic to the notification delivery system.
Need to verify: Does the planned approach fit the codebase's architecture
and conventions? Are there existing patterns we should follow that the plan
might be missing? Any concerns about the approach?"
```

### Specific Checks
Use primitive tools to verify concrete plan details:

- **`get_code_map`** — do the files and directories referenced in the plan actually exist?
- **`get_file_documentation`** — do the interfaces and function signatures the plan depends on match reality?
- **`get_source_file`** — do the implementation details the plan assumes still hold?

### Local Validation

Driver MCP shows committed state, not local changes. After the remote checks above, verify plan assumptions against local state:

1. **File existence** — for each file in the plan's Task Breakdown, verify it exists locally at the stated path using `Glob` or `ls`. Flag files that exist in Driver but not locally (renamed? deleted?) or that exist locally but not in Driver (new? uncommitted?).
2. **Interface check** — for key functions or classes the plan modifies or depends on, read the local version and compare against what Driver's `get_file_documentation` reported. If signatures differ, update the plan to match local state.
3. **Uncommitted changes** — run `git status --short` in the target codebase for files the plan touches. If there are local modifications, note them: the plan should be based on local state, not Driver's committed version.

If research was conducted in the same session and included local validation, focus this check on files specific to the plan's Task Breakdown (not the full codebase). If planning runs in a new session, do the full check.

When divergence is found, update the plan to match local reality. Note the divergence in the self-review report.

### Report Findings
Tell the user what you found:
- Confirmed: what matches
- Discrepancies: what doesn't match (with specifics)
- Suggestions: adjustments to the plan based on what you discovered

Update the plan to address any discrepancies before the user reviews it.

---

## Step 7: Approve

> **Returning to approve a prior-session plan?** If the plan was written in a prior session and the user is returning to approve, skip Steps 1-6. Read the existing plan, verify it's current (check `updated` date), and proceed with the approval flow below.

Present the plan to the user for review.

- "The plan is at `plans/01-<name>.md`. I've validated it against the codebase — [summary of self-review findings]."
- Address any questions or change requests

**Approval flow:**

1. Present the plan for review
2. Address any questions or change requests
3. Suggest dry-run: "Want to run `/drvr:dry-run-plan <plan-name>` before approving?" — this is advisory, the user can skip
4. After the user returns from dry-run (or declines), prompt: "Do you approve plan `<plan-name>` for implementation?"
5. **If the user approves:** Write the following fields to the plan's YAML frontmatter:
   - `status: approved`
   - `approved_at: <ISO 8601 UTC timestamp>` (e.g., `2026-04-16T14:30:00Z`)
   - `approved_by: <user identity>` — use the `userEmail` setting if available in conversation context, otherwise `"user"`
6. End with: "Plan approved. Activate `materialize-tasks` to materialize task documents for plan `<plan-name>`."

**If the user declines:** List what needs to change. Do not proceed. The user controls when to re-present for approval.

---

## Anti-Patterns

**Do NOT:**
- Use native Explore agents or subagents as a substitute for `gather_task_context`
- Abandon `gather_task_context` if it takes 1-3 minutes — this is expected behavior
- Fall back to `get_architecture_overview` or other tools because `gather_task_context` "seems slow"
- Write plan content only in chat — always write to files
- Skip reading research output before planning
- Write vague task descriptions ("implement the feature")
- Order implementation tasks before test tasks
- Skip the self-review step
- Suggest moving to implementation — the user controls phase transitions

**DO:**
- Call `gather_task_context` with detailed, planning-focused task descriptions
- Wait for the full response — it is doing compressed expert-level codebase analysis
- Use primitive tools (`get_code_map`, `get_file_documentation`, `get_source_file`) to reach code-level specificity
- Write tasks specific enough that an engineer can implement without ambiguity
- Order tests before implementation (TDD)
- Validate the plan against the codebase before presenting to the user
- Include explicit, actionable constraints — not generic advice

---

## Before Responding Checklist

- [ ] **Read research first?** — Have I checked `research/*.md`?
- [ ] **Driver context?** — Have I called `gather_task_context` for architecture AND testing patterns?
- [ ] **Writing to file?** — Plan content goes in `plans/*.md`, not chat
- [ ] **Overview needed?** — Multi-plan feature? Create `plans/00-overview.md`
- [ ] **All sections covered?** — Context, Architecture, Acceptance, Tests, Approach, Scope, Constraints, Tasks
- [ ] **Consumer validation?** — Do downstream plans match this plan's interface?
- [ ] **TDD task ordering?** — Test tasks before implementation tasks
- [ ] **Constraints explicit?** — Specific rules, not generic advice
- [ ] **Plan sized right?** — 5-12 tasks, one PR, one logical unit
- [ ] **Feature log?** — Did I update `FEATURE_LOG.md` when creating plans or the overview?
- [ ] **Standards encoded?** — If a codebase standards artifact exists, are applicable standards included as plan constraints with source citations?
- [ ] **Local state validated?** — Did the self-review include local file checks alongside Driver tool checks?